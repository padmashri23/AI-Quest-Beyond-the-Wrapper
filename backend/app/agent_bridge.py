"""Make the repo-level `agents/` package importable from the backend regardless of how
the process was started (uvicorn from backend/, pytest, or Docker with /app as root)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.orchestrator import Orchestrator  # noqa: E402
from agents.lyzr_client import LyzrClient  # noqa: E402

__all__ = ["Orchestrator", "LyzrClient"]
