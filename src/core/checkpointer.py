"""Shared persistent LangGraph checkpointer.

The SQLite saver keeps agent conversation state in ``user_data/checkpoints.sqlite``
so that runs survive daemon restarts and can be shared across windows.

A single connection is reused for the lifetime of the process. SQLite runs in WAL
mode (also used by the usage store) so concurrent reads do not block the single
writer. The saver is created lazily so importing this module is cheap.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from core.user_data import user_data_path

CHECKPOINT_DB_PATH = Path(user_data_path) / "checkpoints.sqlite"

_lock = threading.Lock()
_saver: SqliteSaver | None = None


def get_checkpointer() -> SqliteSaver:
    """Return the process-wide ``SqliteSaver``, creating it on first use."""
    global _saver
    if _saver is not None:
        return _saver

    with _lock:
        if _saver is not None:
            return _saver

        CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(CHECKPOINT_DB_PATH), check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        saver = SqliteSaver(connection)
        saver.setup()
        _saver = saver
        return _saver
