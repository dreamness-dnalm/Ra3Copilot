"""System-tray controller for Ra3Copilot.

The tray is owned by the **daemon** process, not the window process, so there is
exactly one tray icon no matter how many windows are open. It runs on its own
thread because ``pystray.Icon.run()`` blocks on a native message loop.

"显示主窗口" launches a fresh window process (the daemon owns no window, so it
cannot un-hide one); "退出" is delegated to a callback the daemon supplies (it
stops the server and exits). The icon is generated at runtime with Pillow so
there is no external asset to ship.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import PIL.Image
import PIL.ImageDraw
from pystray import Icon, Menu, MenuItem


APP_TITLE = "Ra3Copilot"
_ICON_SIZE = 64


def _make_icon_image() -> PIL.Image.Image:
    """A simple dark-blue rounded square with a white "R" glyph."""
    image = PIL.Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(image)
    radius = _ICON_SIZE // 5
    draw.rounded_rectangle(
        (0, 0, _ICON_SIZE - 1, _ICON_SIZE - 1),
        radius=radius,
        fill=(54, 99, 236, 255),  # deep blue, matches the app accent
    )
    glyph = _ICON_SIZE // 2
    draw.text(
        (glyph, glyph),
        "R",
        fill=(255, 255, 255, 255),
        anchor="mm",
    )
    return image


def launch_window_command() -> list[str]:
    """Command to start a window process, in both source and frozen modes."""
    if getattr(sys, "frozen", False):
        # The frozen exe dispatches by argv token (see __main__.py); a bare
        # invocation runs the desktop window.
        return [sys.executable]
    src_root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "desktop.app"]
    if "--debug" in sys.argv:
        command.append("--debug")
    del src_root
    return command


class TrayController:
    """Owns the tray icon lifecycle on a background thread."""

    def __init__(self) -> None:
        self._icon: Icon | None = None
        self._thread: threading.Thread | None = None
        self._quit_app: Callable[[], None] | None = None

    def start(self, *, quit_app: Callable[[], None]) -> None:
        """Build the icon and start its message loop on a daemon thread."""
        if self._icon is not None:
            return
        self._quit_app = quit_app

        menu = Menu(
            MenuItem("显示主窗口", self._on_show, default=True),
            Menu.SEPARATOR,
            MenuItem("退出", self._on_quit),
        )
        self._icon = Icon("Ra3Copilot", _make_icon_image(), APP_TITLE, menu)
        self._icon.on_left_click = self._on_show

        self._thread = threading.Thread(
            target=self._icon.run,
            name="ra3-tray",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Tear down the icon. Idempotent."""
        icon = self._icon
        if icon is None:
            return
        self._icon = None
        try:
            icon.stop()
        except Exception:
            pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    # -- tray callbacks (run on the tray thread) -------------------------

    def _on_show(self, _icon=None, _item=None) -> None:
        try:
            subprocess.Popen(
                launch_window_command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _on_quit(self, _icon=None, _item=None) -> None:
        if self._quit_app is not None:
            self._quit_app()
