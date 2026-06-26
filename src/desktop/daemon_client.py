"""Window-side daemon client: discover or spawn the daemon, then talk to it.

The window process is thin: on startup it ensures a daemon is reachable, and
all non-local calls go through ``DaemonClient`` over HTTP. Window-only concerns
(minimize/resize/native dialogs/open-folder) stay in DesktopBridge.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from daemon.locking import (
    DEFAULT_DAEMON_PORT,
    HEALTH_PATH,
    PIDFILE_PATH,
    get_base_url,
    get_or_create_token,
)

_HEALTH_TIMEOUT = 0.5
_STARTUP_WAIT_SECONDS = 15.0
_STARTUP_POLL_INTERVAL = 0.15
_START_LOCK_STALE_SECONDS = 20.0
_START_LOCK_PATH = PIDFILE_PATH.with_name("daemon.start.lock")


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


def _daemon_cwd() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _pidfile_port() -> int | None:
    try:
        lines = PIDFILE_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        try:
            port = int(line.strip())
        except ValueError:
            continue
        if 0 < port < 65536:
            return port
    return None


def _candidate_ports(preferred: int) -> list[int]:
    ports: list[int] = []
    for candidate in (preferred, _pidfile_port()):
        if candidate and candidate not in ports:
            ports.append(candidate)
    return ports


def _healthy_base_url(preferred: int) -> str | None:
    for candidate in _candidate_ports(preferred):
        if health_check(candidate):
            return get_base_url(candidate)
    return None


def _try_claim_start_lock() -> bool:
    _START_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(_START_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - _START_LOCK_PATH.stat().st_mtime
        except OSError:
            age = _START_LOCK_STALE_SECONDS + 1
        if age > _START_LOCK_STALE_SECONDS:
            try:
                _START_LOCK_PATH.unlink()
            except OSError:
                pass
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(f"{os.getpid()}\n{time.time():.3f}\n")
    return True


def _release_start_lock() -> None:
    try:
        _START_LOCK_PATH.unlink()
    except OSError:
        pass


def health_check(port: int = DEFAULT_DAEMON_PORT, timeout: float = _HEALTH_TIMEOUT) -> bool:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(get_base_url(port) + HEALTH_PATH)
            if response.status_code != 200:
                return False
            payload = response.json()
            return payload.get("ok") is True and "version" in payload and "pid" in payload
    except (httpx.HTTPError, ValueError):
        return False


def ensure_daemon(port: int = DEFAULT_DAEMON_PORT) -> str:
    """Return the daemon base URL, spawning the daemon if needed.

    1. If a daemon already answers on ``port``, reuse it.
    2. Otherwise spawn one (``python -m daemon``) and poll until healthy.
    """
    healthy = _healthy_base_url(port)
    if healthy:
        return healthy

    deadline = time.perf_counter() + _STARTUP_WAIT_SECONDS
    claimed_lock = False
    while time.perf_counter() < deadline:
        healthy = _healthy_base_url(port)
        if healthy:
            return healthy
        claimed_lock = _try_claim_start_lock()
        if claimed_lock:
            break
        time.sleep(_STARTUP_POLL_INTERVAL)

    if not claimed_lock:
        raise DaemonNotReadyError("守护进程启动超时，请稍后重试。")

    try:
        try:
            subprocess.Popen(
                _python_daemon_command(),
                cwd=str(_daemon_cwd()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise DaemonNotReadyError(f"无法启动守护进程：{exc}") from exc

        deadline = time.perf_counter() + _STARTUP_WAIT_SECONDS
        while time.perf_counter() < deadline:
            healthy = _healthy_base_url(port)
            if healthy:
                return healthy
            time.sleep(_STARTUP_POLL_INTERVAL)
    finally:
        _release_start_lock()

    raise DaemonNotReadyError("守护进程启动超时，请稍后重试。")


class DaemonClient:
    """Synchronous HTTP client for the daemon.

    Used by the thin DesktopBridge for calls that must round-trip before the JS
    frontend takes over (bootstrap). The JS frontend talks to the daemon
    directly via fetch through the getApi() proxy.
    """

    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self._base_url = base_url
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

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
