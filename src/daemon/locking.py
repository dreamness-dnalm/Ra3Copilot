"""Process singleton for the daemon.

A window process starts the daemon only if no healthy one is already running.
Detection is two-layered:

1. Try to reach ``GET /health`` on the configured port. If it answers, the
   daemon is alive and we reuse it.
2. Otherwise claim the port. A stale pidfile from a crashed daemon is harmless
   because health-probe failure is authoritative.

This avoids races where two windows start simultaneously: only the one that
binds the port becomes the daemon; the other observes health and connects.
"""

from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path

from core.user_data import user_data_path

DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 30035
PIDFILE_PATH = Path(user_data_path) / "daemon.pid"
TOKEN_PATH = Path(user_data_path) / "daemon.token"
TOKEN_BYTES = 32

HEALTH_PATH = "/health"
BASE_URL_CACHE: str | None = None


def get_base_url(port: int | None = None) -> str:
    global BASE_URL_CACHE
    if port is not None:
        BASE_URL_CACHE = f"http://{DAEMON_HOST}:{port}"
    if BASE_URL_CACHE is None:
        BASE_URL_CACHE = f"http://{DAEMON_HOST}:{DEFAULT_DAEMON_PORT}"
    return BASE_URL_CACHE


def write_pidfile(port: int) -> None:
    PIDFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE_PATH.write_text(f"{os.getpid()}\n{port}\n", encoding="utf-8")


def read_token() -> str | None:
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def get_or_create_token() -> str:
    token = read_token()
    if token:
        return token

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    try:
        fd = os.open(str(TOKEN_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = read_token()
        if existing:
            return existing
        # The file exists but is empty; replace it with a usable token.
        TOKEN_PATH.write_text(token, encoding="utf-8")
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(token)

    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def clear_pidfile() -> None:
    try:
        PIDFILE_PATH.unlink()
    except OSError:
        pass


def is_port_in_use(port: int) -> bool:
    """True if something is already listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((DAEMON_HOST, port)) == 0


def find_free_port(preferred: int = DEFAULT_DAEMON_PORT) -> int:
    """Return ``preferred`` if free, otherwise the next free port."""
    if not is_port_in_use(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DAEMON_HOST, 0))
        return sock.getsockname()[1]
