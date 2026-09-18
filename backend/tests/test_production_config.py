"""Exercise import-time production controls in isolated child processes."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]


def production_env():
    env = os.environ.copy()
    env.update(APP_ENV='production', ALLOWED_ORIGINS='https://carbon.example.com',
               ALLOWED_HOSTS='carbon.example.com', LYZR_DISABLED='true',
               DATA_ENCRYPTION_KEY=Fernet.generate_key().decode(),
               AUDIT_SIGNING_KEY=Fernet.generate_key().decode())
    for name in ('DATA_ENCRYPTION_KEY_FILE', 'AUDIT_SIGNING_KEY_FILE'):
        env.pop(name, None)
    return env


@pytest.mark.parametrize('overrides,message', [
    ({'ALLOWED_ORIGINS': '*'}, 'explicit ALLOWED_ORIGINS'),
    ({'ALLOWED_ORIGINS': 'http://carbon.example.com'}, 'HTTPS origins'),
    ({'ALLOWED_ORIGINS': 'https://carbon.example.com/path'}, 'HTTPS origins'),
    ({'ALLOWED_HOSTS': ''}, 'explicit ALLOWED_HOSTS'),
    ({'ALLOWED_HOSTS': '*'}, 'explicit ALLOWED_HOSTS'),
])
def test_production_refuses_unsafe_configuration(overrides, message):
    env = production_env()
    env.update(overrides)
    result = subprocess.run([sys.executable, '-c', 'import app.main'], env=env,
                            cwd=BACKEND, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert message in result.stderr


def test_production_cookie_host_and_origin_controls():
    code = '''
from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_user
with TestClient(app, base_url='https://carbon.example.com') as client:
    create_user('operator', 'isolated-production-test-password', 'Operator', 'admin', bootstrap=True)
    assert client.get('/api/ready').status_code == 200
    assert client.get('/api/ready', headers={'host': 'attacker.invalid'}).status_code == 400
    assert client.post('/api/auth/login', headers={'origin': 'https://attacker.invalid'},
                       json={'username': 'operator', 'password': 'isolated-production-test-password'}).status_code == 403
    response = client.post('/api/auth/login', json={'username': 'operator', 'password': 'isolated-production-test-password'})
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
    assert 'max-age=31536000' in response.headers['strict-transport-security']
    assert client.get('/api/operations').status_code == 200
    assert client.get('/api/auth/status').json()['local_setup_allowed'] is False
'''
    result = subprocess.run([sys.executable, '-c', code], env=production_env(),
                            cwd=BACKEND, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_production_refuses_shared_signing_and_encryption_key():
    env = production_env()
    env['AUDIT_SIGNING_KEY'] = env['DATA_ENCRYPTION_KEY']
    result = subprocess.run([sys.executable, '-c',
        'from fastapi.testclient import TestClient\nfrom app.main import app\nwith TestClient(app): pass'],
        env=env, cwd=BACKEND, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'must be independent' in result.stderr
