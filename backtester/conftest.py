"""
Forces the test suite onto its own SQLite file, isolated from backtester.db.

Without this, running `pytest` while a dev server (`python main.py`) is also
running against backtester.db causes cross-process interference: both
processes' independent, per-process `_live_tasks` dicts (orchestrator.pipeline)
fight over rows in the same DB file, and each sweep_loop() misinterprets rows
it didn't create the task for. This was diagnosed as the root cause of two
separate rounds of flaky pipeline test failures. Setting DATABASE_URL here,
before any test module imports config/database, means pytest always gets a
private DB file regardless of what else is running.
"""
# Project packages live at the repo root (one folder per project); make them importable.
import sys as _sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parent.parent)
if _repo_root not in _sys.path:
    _sys.path.insert(1, _repo_root)

import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.gettempdir(), 'tradeved_pytest.db')}"
