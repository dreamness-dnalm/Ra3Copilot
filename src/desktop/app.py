"""Window process for Ra3Copilot.

Thin shell: owns the pywebview window and the few capabilities a remote daemon
cannot provide (window controls, native dialogs, opening OS folders/terminals).
Everything else — agent runs, projects, history, settings, usage — is served by
the daemon and reached directly by the frontend via fetch.

The daemon base URL is exposed to JS through ``getDaemonInfo()``; the frontend
uses it to build its getApi() proxy.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import webview
from webview.window import FixPoint

from core.runtime_env import load_runtime_env
from daemon.locking import DEFAULT_DAEMON_PORT
from desktop.daemon_client import DaemonNotReadyError, ensure_daemon

APP_TITLE = "Ra3Copilot"
MIN_WINDOW_WIDTH = 980
MIN_WINDOW_HEIGHT = 640


def _web_index_path() -> Path:
    """Return the frontend file path both in source and PyInstaller builds."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "desktop" / "web" / "index.html"
    return Path(__file__).resolve().parent / "web" / "index.html"


class DesktopBridge:
    """JS bridge: window control + native dialogs + daemon bootstrap only."""

    def __init__(self) -> None:
        self._window = None
        self._is_maximized = False
        self.daemon_base_url: str = ""
        self.daemon_error: str | None = None

    def bind_window(self, window) -> None:
        self._window = window

    # -- daemon bootstrap -------------------------------------------------

    def get_daemon_info(self) -> dict:
        """Return the daemon base URL (spawning it on first call if needed).

        The frontend polls this on boot until ``ready`` is true.
        """
        if self.daemon_base_url:
            return {"ok": True, "ready": True, "baseUrl": self.daemon_base_url}
        if self.daemon_error:
            return {"ok": False, "ready": False, "error": self.daemon_error}
        try:
            self.daemon_base_url = ensure_daemon(DEFAULT_DAEMON_PORT)
            return {"ok": True, "ready": True, "baseUrl": self.daemon_base_url}
        except DaemonNotReadyError as exc:
            self.daemon_error = str(exc)
            return {"ok": False, "ready": False, "error": self.daemon_error}

    # -- window controls --------------------------------------------------

    def _window_action(self, action: str) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪。"}
        try:
            if action == "minimize":
                self._window.minimize()
            elif action == "toggle_maximize":
                if self._is_maximized:
                    self._window.restore()
                else:
                    self._window.maximize()
                self._is_maximized = not self._is_maximized
            elif action == "close":
                self._window.destroy()
            else:
                return {"ok": False, "error": f"未知窗口动作：{action}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def minimize_window(self) -> dict:
        return self._window_action("minimize")

    def toggle_maximize_window(self) -> dict:
        return self._window_action("toggle_maximize")

    def close_window(self) -> dict:
        return self._window_action("close")

    def resize_window_by(self, edge: str, delta_x: int | float = 0, delta_y: int | float = 0) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪。"}

        edge_text = str(edge or "").lower()
        try:
            dx = int(round(float(delta_x or 0)))
            dy = int(round(float(delta_y or 0)))
            width = int(getattr(self._window, "width", MIN_WINDOW_WIDTH) or MIN_WINDOW_WIDTH)
            height = int(getattr(self._window, "height", MIN_WINDOW_HEIGHT) or MIN_WINDOW_HEIGHT)

            new_width = width
            new_height = height
            if "e" in edge_text:
                new_width += dx
            if "w" in edge_text:
                new_width -= dx
            if "s" in edge_text:
                new_height += dy
            if "n" in edge_text:
                new_height -= dy

            new_width = max(MIN_WINDOW_WIDTH, new_width)
            new_height = max(MIN_WINDOW_HEIGHT, new_height)

            horizontal_fix = FixPoint.EAST if "w" in edge_text else FixPoint.WEST
            vertical_fix = FixPoint.SOUTH if "n" in edge_text else FixPoint.NORTH
            self._window.resize(new_width, new_height, horizontal_fix | vertical_fix)
            self._is_maximized = False
            return {"ok": True, "width": new_width, "height": new_height}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_new_window(self) -> dict:
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable]
                cwd = Path(sys.executable).resolve().parent
            else:
                src_root = Path(__file__).resolve().parents[1]
                command = [sys.executable, "-m", "desktop.app"]
                if "--debug" in sys.argv:
                    command.append("--debug")
                cwd = src_root

            subprocess.Popen(
                command,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def open_project_folder(self, project_path: str) -> dict:
        try:
            path = Path(project_path).expanduser().resolve(strict=False)
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer.exe", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_project_terminal(self, project_path: str) -> dict:
        try:
            path = Path(project_path).expanduser().resolve(strict=False)
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                quoted_path = "'" + str(path).replace("'", "''") + "'"
                subprocess.Popen(
                    [
                        "cmd.exe",
                        "/c",
                        "start",
                        "",
                        "powershell.exe",
                        "-NoExit",
                        "-NoLogo",
                        "-Command",
                        f"Set-Location -LiteralPath {quoted_path}",
                    ]
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(path)])
            else:
                subprocess.Popen(["x-terminal-emulator", "--working-directory", str(path)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # -- native dialogs ---------------------------------------------------

    def choose_directory(self, initial_path: str | None = None) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪"}
        try:
            from core.user_data.projects import PROJECTS_DIR

            initial = Path(initial_path or PROJECTS_DIR).expanduser()
            directory = initial if initial.is_dir() else initial.parent
            selected = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=str(directory),
                allow_multiple=False,
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def run(debug: bool = False) -> None:
    load_runtime_env()
    index_path = _web_index_path()
    if not index_path.exists():
        raise FileNotFoundError(f"Desktop frontend not found: {index_path}")

    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    bridge = DesktopBridge()
    window = webview.create_window(
        APP_TITLE,
        index_path.as_uri(),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
        resizable=True,
        frameless=True,
        easy_drag=False,
        text_select=True,
    )
    bridge.bind_window(window)
    webview.start(debug=debug)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ra3Copilot desktop frontend.")
    parser.add_argument("--debug", action="store_true", help="Enable the webview debug mode.")
    args = parser.parse_args(argv)
    run(debug=args.debug)


if __name__ == "__main__":
    main()
