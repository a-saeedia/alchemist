"""Dev tool: render every widget state to PNG for visual QA.

    GDK_BACKEND=x11 python3 dev/shots.py /tmp/shots
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from octimer.engine import MODE_WATCH, Settings  # noqa: E402
from octimer.probes import Snapshot  # noqa: E402
from octimer.ui import OctimerWindow  # noqa: E402


class FakeProbe:
    def __init__(self):
        self.snap = Snapshot(busy=False, source="api", detail="fake")
        self.ttl = 0

    def snapshot(self, force: bool = False):
        return self.snap

    def wal_age(self):
        return 0.0


def pump() -> None:
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def shoot(win: OctimerWindow, out_dir: str, name: str) -> None:
    """Render, let the frame clock actually paint, then grab."""
    win._render()
    win.queue_draw()
    path = os.path.join(out_dir, name)
    loop = GLib.MainLoop()
    result = {"ok": False, "tries": 0, "last": None}

    def grab() -> bool:
        gdk = win.get_window()
        size = (gdk.get_width(), gdk.get_height()) if gdk else (0, 0)
        settled = (
            size == (win.get_allocated_width(), win.get_allocated_height())
            and size == result["last"]
        )
        result["last"] = size
        result["tries"] += 1
        # Wait for the toplevel to finish resizing after a phase change, else the
        # grab returns the previous frame's pixels.
        if settled or result["tries"] > 20:
            result["ok"] = win.shoot(path)
            loop.quit()
            return False
        return True

    GLib.timeout_add(120, grab)
    loop.run()
    print(("ok  " if result["ok"] else "FAIL"), path)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots"
    os.makedirs(out, exist_ok=True)
    probe = FakeProbe()
    win = OctimerWindow(settings=Settings(minutes=30, drain=False), probe=probe, store={})
    win.show_all()
    pump()
    eng = win.engine
    now = time.monotonic()

    shoot(win, out, "01-idle-timer.png")

    eng.settings.minutes = 45
    eng.settings.drain = True
    win._on_arm()
    eng.deadline = time.monotonic() + 272
    eng.tick(time.monotonic())
    shoot(win, out, "02-running-timer.png")

    win._cancel()
    eng.settings.mode = MODE_WATCH
    probe.snap = Snapshot(busy=True, ids=("ses_a", "ses_b"), source="api")
    eng.set_activity(True, ("ses_a", "ses_b"), time.monotonic())
    win._on_arm()
    shoot(win, out, "03-watch-busy.png")

    probe.snap = Snapshot(busy=False, source="api")
    eng.set_activity(False, (), time.monotonic())
    eng.tick(time.monotonic())
    shoot(win, out, "04-watch-idle.png")

    win._cancel()
    eng.settings.mode = "timer"
    eng.settings.drain = True
    eng.set_activity(True, ("ses_c",), time.monotonic())
    win._on_arm()
    eng.deadline = time.monotonic() - 0.1
    eng.tick(time.monotonic())
    shoot(win, out, "05-drain.png")

    eng._enter_fire(time.monotonic(), "all sessions finished")
    eng.tick(time.monotonic())
    shoot(win, out, "06-fire.png")

    eng.countdown_until = time.monotonic() - 1
    eng.tick(time.monotonic())
    shoot(win, out, "07-done.png")

    win.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
