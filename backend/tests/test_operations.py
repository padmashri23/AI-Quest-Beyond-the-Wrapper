from pathlib import Path
import json
import sqlite3
import pytest
from cryptography.fernet import Fernet
from app import operations
from app.ledger import db
from app.auth import create_user
from app.pipeline import Pipeline


def seed():
    create_user('operator','test-only-long-password','Operator','admin',bootstrap=True)
    summary,entries,_=Pipeline().run([('gas.csv',b'description,quantity,unit,region,period\nNatural gas,100,therm,US,FY2025\n')],'Backup Test',actor='operator')
    return summary


def test_backup_restores_data_documents_and_revokes_sessions(tmp_path):
    summary=seed()
    with db.transaction() as conn:
        conn.execute('INSERT INTO sessions VALUES (?,?,?,?)',('fake-session','operator','fake-csrf',9999999999))
    source_head=db.verify()['head']
    backup=tmp_path/'safe.carbon-backup'; checkpoint=tmp_path/'checkpoint.json'
    receipt=operations.create_backup(backup)
    checkpoint.write_text(json.dumps(receipt['checkpoint']),encoding='utf-8')
    assert b'Backup Test' not in backup.read_bytes()
    restored=tmp_path/'restore'/'ledger.sqlite'
    result=operations.restore_backup(backup,restored,checkpoint)
    assert result['valid'] and result['sessions_revoked']
    with db.using(restored):
        assert db.get_run(summary.run_id).org_name=='Backup Test'
        doc=db.documents(summary.run_id)[0]
        assert b'Natural gas' in db.get_document(summary.run_id,doc['document_id'])[1]
        with db._conn() as conn: assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        assert db.verify()['valid']
    assert db.verify()['head']==source_head
    assert operations.restore_drill(backup,checkpoint)['valid']


def test_backup_refuses_overwrite_and_modified_archive(tmp_path):
    seed(); backup=tmp_path/'backup.enc'; checkpoint=tmp_path/'checkpoint.json'
    receipt=operations.create_backup(backup); checkpoint.write_text(json.dumps(receipt['checkpoint']),encoding='utf-8')
    with pytest.raises(FileExistsError):operations.create_backup(backup)
    target=tmp_path/'existing.db';target.write_bytes(b'do not replace')
    with pytest.raises(FileExistsError):operations.restore_backup(backup,target,checkpoint)
    assert target.read_bytes()==b'do not replace'
    raw=bytearray(backup.read_bytes());raw[len(raw)//2]^=1;backup.write_bytes(raw)
    with pytest.raises(ValueError,match='authentication'):operations.restore_backup(backup,tmp_path/'new.db',checkpoint)
    assert not (tmp_path/'new.db').exists()


def test_external_checkpoint_detects_rollback(tmp_path):
    seed();backup=tmp_path/'backup.enc'
    operations.create_backup(backup)
    db.event('workspace','operator','test.newer_event',{})
    checkpoint=tmp_path/'newer-checkpoint.json';operations.create_checkpoint(checkpoint)
    with pytest.raises(ValueError,match='older than'):
        operations.restore_backup(backup,tmp_path/'old.db',checkpoint)
    with operations.snapshot() as path:
        assert operations.verify_checkpoint(path,json.loads(checkpoint.read_text()))['valid']


def test_wrong_keys_fail_closed(tmp_path,monkeypatch):
    seed();backup=tmp_path/'backup.enc';cp=tmp_path/'checkpoint.json'
    receipt=operations.create_backup(backup);cp.write_text(json.dumps(receipt['checkpoint']),encoding='utf-8')
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEY',Fernet.generate_key().decode())
    with pytest.raises(ValueError,match='authentication'):
        operations.restore_backup(backup,tmp_path/'wrong.db',cp)


def test_context_override_does_not_redirect_live_ledger(tmp_path):
    original=db._path()
    with db.using(tmp_path/'other.sqlite'):
        assert db._path().name=='other.sqlite'
    assert db._path()==original


def test_checkpoint_signature_is_checked(tmp_path):
    seed();cp=tmp_path/'checkpoint.json';checkpoint=operations.create_checkpoint(cp)
    checkpoint['head']='f'*64
    with operations.snapshot() as path:
        with pytest.raises(ValueError,match='signature'):
            operations.verify_checkpoint(path,checkpoint)
