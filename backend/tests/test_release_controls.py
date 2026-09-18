import json
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app.main import app
from app.ledger import db
from app.security import secret
from app import operations, runtime
from test_workspace import client, inventory, PASSWORD


def test_supplier_approval_is_required_bound_to_content_and_audited(client):
    run = inventory(client)
    run_id = run['summary']['run_id']
    base = '/api/runs/' + run_id
    response = client.post(base + '/suppliers', json={
        'supplier': 'Demo Supplier', 'contact_email': 'supplier@example.com',
        'due_date': '2026-12-01', 'line_ids': [run['entries'][0]['item']['line_id']]})
    assert response.status_code == 200
    record = client.get(base + '/workspace').json()['suppliers'][0]
    url = base + '/suppliers/' + record['id']
    assert not record['approved']
    assert client.get(url + '/draft').status_code == 409
    approval = {'content_sha256': record['content_sha256'],
                'statement': 'I reviewed the intended recipient and the exact message content.'}
    assert client.post(url + '/approve', json={**approval, 'content_sha256': '0'*64}).status_code == 409
    assert client.post(url + '/approve', json=approval, headers={'x-csrf-token': ''}).status_code == 403
    assert client.post(url + '/approve', json=approval).status_code == 200
    result = client.get(url + '/draft')
    assert result.status_code == 200
    assert b'X-Unsent: 1' in result.content
    assert b'To: supplier@example.com' in result.content
    assert client.get(base + '/workspace').json()['suppliers'][0]['approved']
    event = [e for e in db.audit(run_id) if e['action'] == 'supplier.draft_downloaded'][-1]
    assert event['actor'] == 'preparer'
    # Receiving evidence does not change the approved outgoing message.
    doc = client.get(base + '/workspace').json()['documents'][0]['document_id']
    assert client.post(url + '/response', json={'evidence_ids': [doc],
                       'notes': 'Supplier evidence received and queued for accounting review.'}).status_code == 200
    assert client.get(url + '/draft').status_code == 200
    # Even a future workflow that revises the recipient cannot reuse an old approval.
    current = db.get_artifact(run_id, 'supplier', record['id'])
    db.put_artifact(run_id, 'supplier', record['id'],
                    {**current, 'contact_email': 'different@example.com'}, 'preparer')
    assert client.get(url + '/draft').status_code == 409
    assert not client.get(base + '/workspace').json()['suppliers'][0]['approved']
    assert db.verify()['valid']


def test_supplier_analyst_cannot_approve(client):
    run = inventory(client)
    base = '/api/runs/' + run['summary']['run_id']
    client.post(base + '/suppliers', json={'supplier': 'Demo Supplier',
        'contact_email': 'supplier@example.com', 'due_date': '2026-12-01',
        'line_ids': [run['entries'][0]['item']['line_id']]})
    record = client.get(base + '/workspace').json()['suppliers'][0]
    assert client.post('/api/auth/users', json={'username': 'analyst', 'password': PASSWORD,
                                               'role': 'analyst'}).status_code == 200
    login = client.post('/api/auth/login', json={'username': 'analyst', 'password': PASSWORD}).json()
    client.headers['x-csrf-token'] = login['csrf']
    assert client.post(base + '/suppliers/' + record['id'] + '/approve', json={
        'content_sha256': record['content_sha256'], 'statement': 'I have checked this supplier request carefully.'}).status_code == 403
    assert client.get('/api/operations').status_code == 403


def test_readiness_and_bounded_private_telemetry(client, monkeypatch):
    run = inventory(client)
    run_id = run['summary']['run_id']
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/ready').json() == {'ready': True}
        assert anonymous.get('/api/operations').status_code == 401
    response = client.get('/api/runs/' + run_id + '?private=do-not-retain')
    assert response.status_code == 200
    assert len(response.headers['X-Request-ID']) == 32
    assert client.post('/api/demo', headers={'content-length': str(56*1024*1024)}).status_code == 413
    for index in range(5):
        client.request('CUSTOM' + str(index), '/api/no-such-route')
    status = client.get('/api/operations').json()
    assert status['email_delivery'].startswith('disabled')
    serialized = json.dumps(status['requests'])
    assert run_id not in serialized and 'do-not-retain' not in serialized
    assert sum(1 for method, route in runtime._metrics if method.startswith('CUSTOM')) == 0
    monkeypatch.setenv('DATA_ENCRYPTION_KEY', Fernet.generate_key().decode())
    assert client.get('/api/ready').status_code == 503


def test_secret_file_loading_and_conflicts(tmp_path, monkeypatch):
    key = Fernet.generate_key()
    path = tmp_path / 'mounted-secret'
    path.write_bytes(key + b'\n')
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEY_FILE', str(path))
    assert secret('BACKUP_ENCRYPTION_KEY') == key
    monkeypatch.setenv('BACKUP_ENCRYPTION_KEY', key.decode())
    with pytest.raises(RuntimeError, match='only one'):
        secret('BACKUP_ENCRYPTION_KEY')


def test_backup_emits_matching_external_checkpoint(client, tmp_path):
    inventory(client)
    checkpoint = tmp_path / 'checkpoint.json'
    backup = tmp_path / 'backup.enc'
    receipt = operations.create_backup(backup, checkpoint)
    assert json.loads(checkpoint.read_text()) == receipt['checkpoint']
    assert operations.restore_drill(backup, checkpoint)['valid']
    with pytest.raises(FileExistsError):
        operations.create_backup(tmp_path / 'other.enc', checkpoint)
    assert not (tmp_path / 'other.enc').exists()
