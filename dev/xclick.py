"""Dev tool: real X11 clicks via XTest, for end-to-end widget input QA.

`Gdk.test_simulate_button` is a no-op on GTK3 with XInput2, so pointer/keyboard
injection goes through libXtst directly. This moves the real pointer, so only
aim it at windows you own.

    from dev.xclick import click_at_screen, click_widget
    click_widget(gtk_window, gtk_button)
"""

from __future__ import annotations

import ctypes
import ctypes.util
import time

_x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
_xtst = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst") or "libXtst.so.6")

_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XFlush.argtypes = [ctypes.c_void_p]
_x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
_x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
_xtst.XTestFakeMotionEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong
]
_xtst.XTestFakeButtonEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong
]


def _display():
    dpy = _x11.XOpenDisplay(None)
    if not dpy:
        raise RuntimeError("cannot open X display")
    return dpy


def click_at_screen(x: int, y: int, button: int = 1, settle: float = 0.06) -> None:
    dpy = _display()
    try:
        _xtst.XTestFakeMotionEvent(dpy, -1, int(x), int(y), 0)
        _x11.XSync(dpy, 0)
        time.sleep(settle)
        _xtst.XTestFakeButtonEvent(dpy, button, 1, 0)
        _x11.XSync(dpy, 0)
        time.sleep(settle)
        _xtst.XTestFakeButtonEvent(dpy, button, 0, 0)
        _x11.XSync(dpy, 0)
    finally:
        _x11.XCloseDisplay(dpy)


def click_widget(window, widget, dx: int = -1, dy: int = -1) -> tuple[int, int]:
    """Click the centre (or centre+dx/dy) of `widget` inside `window`."""
    gdk = window.get_window()
    ok, ox, oy = gdk.get_origin()
    if not ok:
        raise RuntimeError("window has no origin yet")
    rel = widget.translate_coordinates(window, 0, 0)
    wx, wy = rel[-2:]
    w = widget.get_allocated_width()
    h = widget.get_allocated_height()
    x = ox + wx + (w // 2 if dx < 0 else dx)
    y = oy + wy + (h // 2 if dy < 0 else dy)
    click_at_screen(x, y)
    return x, y
