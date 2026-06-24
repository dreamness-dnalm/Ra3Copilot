"""Shared persistent LangGraph checkpointer.

The async SQLite saver keeps agent conversation state in
``user_data/checkpoints.sqlite`` so that runs survive daemon restarts and can be
shared across windows.

The agent runtime drives the graph with ``astream`` (async streaming), which
requires an :class:`AsyncSqliteSaver`; the synchronous ``SqliteSaver`` rejects
async methods. ``AsyncSqliteSaver.__init__`` binds itself to the running event
loop, so the saver must be constructed lazily from within the loop (the agent
factories already run inside ``ensure_agent``'s ``asyncio.run``). The connection
is held for the lifetime of the process and reused across runs.

WAL mode keeps concurrent reads from blocking the writer.
"""

from __future__ import annotations

import threading
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from core.user_data import user_data_path

CHECKPOINT_DB_PATH = Path(user_data_path) / "checkpoints.sqlite"

_lock = threading.Lock()
_saver: AsyncSqliteSaver | None = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """Return the process-wide ``AsyncSqliteSaver``, creating it on first use.

    Must be awaited from a running event loop (the saver binds to it).
    """
    global _saver
    if _saver is not None:
        return _saver

    with _lock:
        if _saver is not None:
            return _saver

        CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(CHECKPOINT_DB_PATH))
        await connection.execute("PRAGMA journal_mode=WAL")
        saver = AsyncSqliteSaver(connection)
        await saver.setup()
        _saver = saver
        return _saver
