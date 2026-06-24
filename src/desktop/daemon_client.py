"""Window-side daemon client: discover or spawn the daemon, then talk to it.

The window process is thin: on startup it ensures a daemon is reachable, and
all non-local calls go through ``DaemonClient`` over HTTP. Window-only concerns
(minimize/resize/native dialogs/open-folder) stay in DesktopBridge.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

from daemon.locking import DEFAULT_DAEMON_PORT, HEALTH_PATH, get_base_url

_HEALTH_TIMEOUT = 0.5
_STARTUP_WAIT_SECONDS = 15.0
_STARTUP_POLL_INTERVAL = 0.25


class DaemonNotReadyError(RuntimeError):
    """Raised when the daemon cannot be reached or started."""


def _python_daemon_command() -> list[str]:
    """Command to launch the daemon, working in both source and frozen modes."""
    if getattr(sys, "frozen", False):
        # Frozen exe: re-invoke the same executable. The daemon module is the
        # entry point selected by argument (handled by the bootloader).
        return [sys.executable, "daemon"]
    src_root = Path(__file__).resolve().parents[1]
    return [sys.executable, "-m", "daemon"]


def health_check(port: int = DEFAULT_DAEMON_PORT, timeout: float = _HEALTH_TIMEOUT) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(get_base_url(port) + HEALTH_PATH)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def ensure_daemon(port: int = DEFAULT_DAEMON_PORT) -> str:
    """Return the daemon base URL, spawning the daemon if needed.

    1. If a daemon already answers on ``port``, reuse it.
    2. Otherwise spawn one (``python -m daemon``) and poll until healthy.
    """
    if health_check(port):
        return get_base_url(port)

    try:
        subprocess.Popen(
            _python_daemon_command(),
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise DaemonNotReadyError(f"无法启动守护进程：{exc}") from exc

    deadline = time.perf_counter() + _STARTUP_WAIT_SECONDS
    while time.perf_counter() < deadline:
        if health_check(port):
            return get_base_url(port)
        time.sleep(_STARTUP_POLL_INTERVAL)

    raise DaemonNotReadyError("守护进程启动超时，请稍后重试。")


class DaemonClient:
    """Synchronous HTTP client for the daemon.

    Used by the thin DesktopBridge for calls that must round-trip before the JS
    frontend takes over (bootstrap). The JS frontend talks to the daemon
    directly via fetch through the getApi() proxy.
    """

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def post(self, path: str, body: dict | None = None) -> dict:
        response = self._client.post(path, json=body or {})
        response.raise_for_status()
        return response.json()

    def get(self, path: str) -> dict:
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()
