import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('LEDGER_PATH', str(tmp_path / 'ledger.db'))
    monkeypatch.setenv('KEY_DIR', str(tmp_path / 'keys'))
    monkeypatch.setenv('LYZR_API_KEY', '')
    monkeypatch.setenv('LYZR_DISABLED', 'true')
    monkeypatch.setenv('APP_ENV', 'development')


@pytest.fixture
def client():
    """A TestClient signed in as the bootstrap administrator with its CSRF header set."""
    from fastapi.testclient import TestClient
    from app.main import app
    from helpers import PASSWORD

    with TestClient(app) as c:
        assert c.post('/api/auth/setup', json={'username': 'preparer', 'password': PASSWORD}).status_code == 200
        login = c.post('/api/auth/login', json={'username': 'preparer', 'password': PASSWORD})
        c.headers['x-csrf-token'] = login.json()['csrf']
        yield c
