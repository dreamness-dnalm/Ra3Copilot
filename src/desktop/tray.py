"""System-tray controller for Ra3Copilot.

The tray is owned by the **daemon** process, not the window process, so there is
exactly one tray icon no matter how many windows are open. It runs on its own
thread because ``pystray.Icon.run()`` blocks on a native message loop.

Left-clicking or right-clicking the icon opens the tray menu. "新建窗口" launches
a fresh window process; "退出" is delegated to a callback the daemon supplies
(it stops the server and exits). The icon is generated at runtime with Pillow so
there is no external asset to ship.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import PIL.Image
import PIL.ImageDraw
from pystray import Icon as PystrayIcon
from pystray import Menu, MenuItem


APP_TITLE = "Ra3Copilot"
_ICON_SIZE = 64


if sys.platform.startswith("win"):
    from pystray import _win32 as pystray_win32

    class TrayIcon(pystray_win32.Icon):
        """Windows tray icon that opens the popup menu on either mouse button."""

        def _popup_menu(self) -> None:
            if not self._menu_handle:
                return

            win32 = pystray_win32.win32
            win32.SetForegroundWindow(self._hwnd)

            point = wintypes.POINT()
            win32.GetCursorPos(ctypes.byref(point))

            hmenu, descriptors = self._menu_handle
            index = win32.TrackPopupMenuEx(
                hmenu,
                win32.TPM_RIGHTALIGN | win32.TPM_BOTTOMALIGN | win32.TPM_RETURNCMD,
                point.x,
                point.y,
                self._menu_hwnd,
                None,
            )
            if index > 0:
                descriptors[index - 1](self)

        def _on_notify(self, wparam, lparam):
            win32 = pystray_win32.win32
            if lparam in (win32.WM_LBUTTONUP, win32.WM_RBUTTONUP):
                self._popup_menu()

else:
    TrayIcon = PystrayIcon


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


def _window_launch_target() -> tuple[list[str], Path]:
    """Command/cwd to launch a new desktop window in source or frozen mode."""
    if getattr(sys, "frozen", False):
        return [sys.executable], Path(sys.executable).resolve().parent

    src_root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "desktop.app"]
    if "--debug" in sys.argv:
        command.append("--debug")
    return command, src_root


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
            MenuItem(APP_TITLE, self._noop, enabled=False),
            MenuItem("新建窗口", self._on_new_window),
            Menu.SEPARATOR,
            MenuItem("退出", self._on_quit),
        )
        self._icon = TrayIcon("Ra3Copilot", _make_icon_image(), APP_TITLE, menu)

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

    def _noop(self, _icon=None, _item=None) -> None:
        pass

    def _on_new_window(self, _icon=None, _item=None) -> None:
        try:
            command, cwd = _window_launch_target()
            subprocess.Popen(
                command,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _on_quit(self, _icon=None, _item=None) -> None:
        if self._quit_app is not None:
            self._quit_app()
