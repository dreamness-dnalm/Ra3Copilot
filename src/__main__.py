"""Unified entry point for both source and frozen (PyInstaller) execution.

When frozen into a single exe, ``sys.executable`` IS the launcher. The window
process spawns the daemon as ``[sys.executable, "daemon"]``; this module
detects that argv token and runs the daemon instead of the window. In source
mode the real ``python -m daemon`` / ``python -m desktop.app`` paths are used.

This module is the script passed to PyInstaller (see Ra3Copilot.spec), so the
single frozen artifact can act as either window or daemon.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    if "daemon" in args:
        # Remove the "daemon" token and run the daemon entry point.
        daemon_args = [a for a in args if a != "daemon"]
        from daemon.__main__ import main as run_daemon

        run_daemon(daemon_args)
        return

    from desktop.app import main as run_desktop

    run_desktop(args)


if __name__ == "__main__":
    main()
