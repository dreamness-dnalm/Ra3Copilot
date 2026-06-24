"""Process-wide, long-lived asyncio event loop for agent runs.

The AsyncSqliteSaver (and the cached agent instances) bind themselves to the
running event loop on first construction. If each run created its own loop via
``asyncio.run()``, the saver/agents from the first run would be tied to a now-
dead loop and the next run would fail with
``<Lock ...> is bound to a different event loop``.

To keep the agent cache valid across runs, every run submits its coroutine to
this single, shared loop via :func:`asyncio.run_coroutine_threadsafe`. The loop
is created lazily on a dedicated daemon thread and lives for the daemon's
lifetime.
"""

from __future__ import annotations

import asyncio
import threading

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def get_loop() -> asyncio.AbstractEventLoop:
    """Return the shared event loop, starting its thread on first call."""
    global _loop
    if _loop is not None:
        return _loop

    with _lock:
        if _loop is None:
            ready = threading.Event()

            def _runner() -> None:
                global _loop
                _loop = asyncio.new_event_loop()
                asyncio.set_event_loop(_loop)
                ready.set()
                _loop.run_forever()

            thread = threading.Thread(
                target=_runner, name="ra3-agent-loop", daemon=True
            )
            thread.start()
            ready.wait(5.0)
            if _loop is None:
                raise RuntimeError("agent event loop failed to start")

    return _loop


# Eagerly exposed for `asyncio.run_coroutine_threadsafe(coro, agent_loop.loop)`.
class _AgentLoop:
    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return get_loop()


agent_loop = _AgentLoop()
