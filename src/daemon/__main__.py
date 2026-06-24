"""Daemon entry point: ``python -m daemon`` (or the frozen exe with this arg).

Claims a port (preferring the default 30034) and serves the FastAPI app. If the
default port is busy with a non-daemon process, fall back to a free port; the
window process discovers the actual port via the pidfile.
"""

from __future__ import annotations

import argparse

from daemon.locking import DEFAULT_DAEMON_PORT, find_free_port
from daemon.server import run_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ra3Copilot daemon.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DAEMON_PORT,
        help="Port to listen on (default 30034).",
    )
    args = parser.parse_args(argv)
    port = find_free_port(args.port)
    run_server(port)


if __name__ == "__main__":
    main()
