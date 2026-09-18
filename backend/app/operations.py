"""Offline maintenance: consistent encrypted backups and non-overwriting restores.

SQLite online backup includes committed WAL content. See https://sqlite.org/backup.html.
Keep encryption/signing keys and audit checkpoints outside the backup's trust domain.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid
import zipfile

from cryptography.fernet import Fernet, InvalidToken

from .ledger import db
from .security import canonical, secret, sign

MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_BACKUP_BYTES = 400 * 1024 * 1024


def _exclusive_write(path: Path, data: bytes):
    """Refuse replacement, including symlinks; only remove our own incomplete write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def snapshot():
    source_path = db._path().resolve()
    if not source_path.is_file():
        raise ValueError('Initialize the ledger before creating a backup')
    with tempfile.TemporaryDirectory(prefix='carbon-snapshot-') as directory:
        target = Path(directory) / 'ledger.sqlite'
        source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(target)
        page_size = source.execute('PRAGMA page_size').fetchone()[0]
        started = time.monotonic()
        try:
            def progress(status, remaining, total):
                if time.monotonic() - started > 60:
                    raise TimeoutError('Snapshot deadline exceeded; retry during lower write activity')
                if total * page_size > MAX_DATABASE_BYTES:
                    raise ValueError('Database exceeds this maintenance implementation size limit')
            source.backup(destination, pages=256, progress=progress)
        finally:
            destination.close()
            source.close()
        if target.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError('This backup implementation supports snapshots up to 256 MB')
        yield target


def verify_snapshot(path: Path):
    with db.using(path):
        with db._conn() as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite integrity check failed')
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('SQLite foreign-key check failed')
        result = db.verify()
        if not result['valid']:
            raise ValueError('Audit verification failed: ' + '; '.join(result['errors']))
        return result


def checkpoint_for(path: Path):
    state = verify_snapshot(path)
    body = {'format': 'carbon-checkpoint-v1', 'created_at': db.now(),
            'events': state['events'], 'head': state['head']}
    return {**body, 'signature': sign(canonical(body))}


def verify_checkpoint(path: Path, checkpoint: dict):
    body = {k: v for k, v in checkpoint.items() if k != 'signature'}
    if body.get('format') != 'carbon-checkpoint-v1' or not hmac.compare_digest(
            sign(canonical(body)), str(checkpoint.get('signature', ''))):
        raise ValueError('Checkpoint signature is invalid')
    if not isinstance(body.get('events'), int) or body['events'] < 0:
        raise ValueError('Checkpoint event count is invalid')
    with db.using(path):
        state = verify_snapshot(path)
        events = db.audit()
        count = body['events']
        if count > len(events):
            raise ValueError('Ledger is older than the retained checkpoint: audit tail is missing')
        head_at_count = events[count - 1]['event_hash'] if count else '0' * 64
        if body['head'] != head_at_count:
            raise ValueError('Ledger does not match the retained checkpoint')
    return state


def create_checkpoint(destination: Path):
    with snapshot() as path:
        checkpoint = checkpoint_for(path)
    _exclusive_write(destination, (canonical(checkpoint) + '\n').encode())
    return checkpoint


def create_backup(destination: Path, checkpoint_destination: Path | None = None):
    # Independent backup key: database/signing keys are never bundled in the archive.
    if checkpoint_destination is not None:
        if checkpoint_destination.resolve() == destination.resolve():
            raise ValueError('Backup and checkpoint must use different paths')
        if checkpoint_destination.exists() or checkpoint_destination.is_symlink():
            raise FileExistsError('Checkpoint destination already exists')
    cipher = Fernet(secret('BACKUP_ENCRYPTION_KEY'))
    with snapshot() as path:
        checkpoint = checkpoint_for(path)
        connection = sqlite3.connect(path)
        try:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            connection.close()
        raw = path.read_bytes()
        body = {'format': 'carbon-backup-v1', 'backup_id': uuid.uuid4().hex,
                'created_at': db.now(), 'database_sha256': hashlib.sha256(raw).hexdigest(),
                'database_bytes': len(raw), 'checkpoint': checkpoint,
                'data_key_fingerprint': hashlib.sha256(secret('DATA_ENCRYPTION_KEY')).hexdigest()}
        manifest = {**body, 'signature': sign(canonical(body))}
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', canonical(manifest))
            archive.writestr('ledger.sqlite', raw)
        _exclusive_write(destination, cipher.encrypt(bundle.getvalue()))
    if checkpoint_destination is not None:
        _exclusive_write(checkpoint_destination, (canonical(checkpoint) + '\n').encode())
    return {'backup_id': body['backup_id'], 'created_at': body['created_at'],
            'database_bytes': len(raw), 'checkpoint': checkpoint, 'destination': str(destination)}


def _read_backup(source: Path):
    if source.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError('Backup file exceeds the configured size limit')
    try:
        bundle = Fernet(secret('BACKUP_ENCRYPTION_KEY')).decrypt(source.read_bytes())
    except InvalidToken as exc:
        raise ValueError('Backup authentication failed; wrong key or modified backup') from exc
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        if sorted(archive.namelist()) != ['ledger.sqlite', 'manifest.json']:
            raise ValueError('Unexpected archive members')
        if archive.getinfo('ledger.sqlite').file_size > MAX_DATABASE_BYTES or archive.getinfo('manifest.json').file_size > 16384:
            raise ValueError('Backup contents exceed maintenance limits')
        manifest = json.loads(archive.read('manifest.json'))
        body = {k: v for k, v in manifest.items() if k != 'signature'}
        if body.get('format') != 'carbon-backup-v1' or not hmac.compare_digest(
                sign(canonical(body)), str(manifest.get('signature', ''))):
            raise ValueError('Backup manifest signature is invalid')
        if body.get('data_key_fingerprint') != hashlib.sha256(secret('DATA_ENCRYPTION_KEY')).hexdigest():
            raise ValueError('The original data encryption key is required for restoration')
        raw = archive.read('ledger.sqlite')
        if len(raw) != body.get('database_bytes') or hashlib.sha256(raw).hexdigest() != body.get('database_sha256'):
            raise ValueError('Backup database hash or length does not match')
    return raw, manifest


def restore_backup(source: Path, destination: Path, expected_checkpoint: Path):
    """Restore to a NEW path only; never replace a running ledger or recover sessions."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Restore destination must not exist; live ledgers are never overwritten')
    retained = json.loads(expected_checkpoint.read_text(encoding='utf-8'))
    raw, manifest = _read_backup(source)
    with tempfile.TemporaryDirectory(prefix='carbon-restore-') as directory:
        staged = Path(directory) / 'ledger.sqlite'
        _exclusive_write(staged, raw)
        verify_checkpoint(staged, manifest['checkpoint'])
        verify_checkpoint(staged, retained)
        with db.using(staged):
            with db.transaction() as conn:
                conn.execute('DELETE FROM sessions')
                conn.execute('DELETE FROM login_attempts')
                db._event(conn, 'workspace', 'recovery-operator', 'backup.restored',
                          {'backup_id': manifest['backup_id'], 'source_checkpoint': manifest['checkpoint']['head']})
            state = verify_snapshot(staged)
            with db._conn() as conn:
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        _exclusive_write(destination, staged.read_bytes())
    return {'destination': str(destination), 'backup_id': manifest['backup_id'],
            'valid': state['valid'], 'head': state['head'], 'sessions_revoked': True}


def restore_drill(source: Path, expected_checkpoint: Path):
    """Exercises decryption, audit verification and recovery without touching live data."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='carbon-drill-') as directory:
        result = restore_backup(source, Path(directory) / 'restored.sqlite', expected_checkpoint)
        result.pop('destination')
    return {**result, 'drill_at': datetime.now(timezone.utc).isoformat(),
            'duration_ms': round((time.monotonic() - started) * 1000)}
