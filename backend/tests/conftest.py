import os
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
