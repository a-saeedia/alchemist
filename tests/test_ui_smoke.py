"""Headless-ish UI smoke test: every control must survive a real click.

This is the regression test for the bug that shipped in the first build -- the
ARM button was wired straight to `_on_arm`, GTK passes the button as an argument,
and the handler died with `TypeError: takes 1 positional argument but 2 were
given` while the widget just sat there.

`Gtk.test_widget_click` pushes press/release through the widget's signal chain
(real `clicked` emission), and stderr is captured so a crashing handler fails the
test instead of scrolling past.

Needs a display; skipped when there is none.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GDK_BACKEND", "x11")
os.environ.setdefault("OCTIMER_DRY_RUN", "1")
# never let the tests write the operator's real ~/.config/octimer/state.json
import tempfile  # noqa: E402

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="octimer-test-")

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    _GTK_OK = Gtk.init_check(sys.argv)[0]
except Exception:  # pragma: no cover - no display in CI
    _GTK_OK = False

if _GTK_OK:
    from octimer.engine import MODE_TIMER, MODE_WATCH, Settings
    from octimer.probes import Snapshot
    from octimer.ui import OctimerWindow

    class FakeProbe:
        def __init__(self, busy=False):
            self.busy = busy

        def snapshot(self, force=False):
            ids = ("ses_a", "ses_b") if self.busy else ()
            return Snapshot(busy=self.busy, ids=ids, source="api", detail="fake")

        def wal_age(self):
            return 0.0


@unittest.skipUnless(_GTK_OK, "no display")
class WidgetClicks(unittest.TestCase):
    def setUp(self):
        self.win = OctimerWindow(
            settings=Settings(minutes=30, countdown=5),
            probe=FakeProbe(),
            store={},
        )
        self.win.start()
        self.pump()

    def tearDown(self):
        self.win._quitting = True
        self.win.destroy()

    # ------------------------------------------------------------------ utils
    def pump(self, rounds: int = 6) -> None:
        for _ in range(rounds):
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

    def click(self, widget) -> str:
        """Emit a real `clicked`; return captured stderr (tracebacks land there).

        Gtk.test_widget_click is inert on GTK3 + XInput2, so the signal is
        emitted the way the button would: with the widget as its argument. That
        is exactly the shape that crashed the first build.
        """
        self.pump()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            if isinstance(widget, Gtk.CheckButton):
                widget.set_active(not widget.get_active())
            else:
                widget.emit("clicked")
            self.pump()
        return buf.getvalue()

    def assertClean(self, err: str) -> None:
        self.assertNotIn("Traceback", err, f"handler crashed:\n{err}")
        self.assertNotIn("Error", err, f"handler crashed:\n{err}")

    # ------------------------------------------------------------------ tests
    def test_arm_button_arms_the_timer(self):
        err = self.click(self.win.arm_btn)
        self.assertClean(err)
        self.assertEqual(self.win.engine.state.phase, "timer")
        self.assertTrue(self.win.cancel_btn.get_visible())
        self.assertFalse(self.win.controls.get_visible())

    def test_cancel_button_disarms(self):
        self.assertClean(self.click(self.win.arm_btn))
        err = self.click(self.win.cancel_btn)
        self.assertClean(err)
        self.assertEqual(self.win.engine.state.phase, "idle")
        self.assertTrue(self.win.controls.get_visible())
        self.assertFalse(self.win.cancel_btn.get_visible())

    def test_presets_set_minutes(self):
        for btn, minutes in zip(self.win.preset_row.get_children(), (5, 15, 30, 60)):
            err = self.click(btn)
            self.assertClean(err)
            self.assertEqual(self.win.engine.settings.minutes, minutes)

    def test_trim_buttons_adjust_minutes(self):
        self.win._set_minutes(30)
        minus_one = self.win.trim_row.get_children()[1]
        self.assertClean(self.click(minus_one))
        self.assertEqual(self.win.engine.settings.minutes, 29)
        plus_five = self.win.trim_row.get_children()[3]
        self.assertClean(self.click(plus_five))
        self.assertEqual(self.win.engine.settings.minutes, 34)

    def test_mode_toggle(self):
        self.assertClean(self.click(self.win.btn_watch))
        self.assertEqual(self.win.engine.settings.mode, MODE_WATCH)
        self.assertTrue(self.win.engine.settings.drain)
        err = self.click(self.win.btn_timer)
        self.assertClean(err)
        self.assertEqual(self.win.engine.settings.mode, MODE_TIMER)

    def test_drain_checkbox(self):
        before = self.win.engine.settings.drain
        err = self.click(self.win.chk_drain)
        self.assertClean(err)
        self.assertNotEqual(self.win.engine.settings.drain, before)

    def test_arm_is_idempotent(self):
        self.assertClean(self.click(self.win.arm_btn))
        phase = self.win.engine.state.phase
        self.assertClean(self.click(self.win.arm_btn))
        self.assertEqual(self.win.engine.state.phase, phase)

    def test_watch_mode_arms_without_timer(self):
        self.assertClean(self.click(self.win.btn_watch))
        self.assertClean(self.click(self.win.arm_btn))
        self.assertEqual(self.win.engine.state.phase, "watch")
        self.assertTrue(self.win.cancel_btn.get_visible())


@unittest.skipUnless(_GTK_OK, "no display")
class DragRouting(unittest.TestCase):
    """A press on empty card area starts a move; a press on a control does not."""

    def setUp(self):
        self.win = OctimerWindow(
            settings=Settings(minutes=30), probe=FakeProbe(), store={}
        )
        self.win.start()
        for _ in range(6):
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

    def tearDown(self):
        self.win._quitting = True
        self.win.destroy()

    def test_controls_are_excluded_from_drag(self):
        arm = self.win.arm_btn
        res = arm.translate_coordinates(self.win, 0, 0)
        x, y = (res[-2], res[-1]) if len(res) >= 2 else (0, 0)
        self.assertTrue(
            self.win._over_control(x + arm.get_allocated_width() // 2,
                                   y + arm.get_allocated_height() // 2)
        )

    def test_empty_area_is_draggable(self):
        self.assertFalse(self.win._over_control(4, 4))


if __name__ == "__main__":
    unittest.main(verbosity=2)
