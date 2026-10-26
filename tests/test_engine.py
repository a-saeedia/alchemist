"""Unit tests for the pure state machine. `python3 -m unittest discover tests`"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from octimer.engine import (  # noqa: E402
    DONE,
    DRAIN,
    FIRE,
    IDLE,
    MODE_TIMER,
    MODE_WATCH,
    TIMER,
    WATCH,
    Engine,
    Settings,
)


class Harness:
    def __init__(self, **kw):
        self.t = 1000.0
        self.fired: list[str] = []
        self.notes: list[str] = []
        self.engine = Engine(
            settings=Settings(**kw),
            on_fire=self.fired.append,
            on_note=self.notes.append,
        )

    def activity(self, busy: bool, ids=("ses_a",)):
        self.engine.set_activity(busy, ids if busy else (), self.t)

    def advance(self, seconds: float, step: float = 0.25) -> None:
        end = self.t + seconds
        while self.t < end:
            self.t = min(end, self.t + step)
            self.engine.tick(self.t)

    def arm(self):
        return self.engine.arm(self.t)


class TimerMode(unittest.TestCase):
    def test_counts_down_and_fires(self):
        h = Harness(minutes=1, countdown=0)
        h.arm()
        self.assertEqual(h.engine.state.phase, TIMER)
        h.advance(59)
        self.assertAlmostEqual(h.engine.state.remaining, 1, delta=0.3)
        self.assertEqual(h.fired, [])
        h.advance(1.1)
        self.assertEqual(h.engine.state.phase, DONE)
        self.assertEqual(h.fired, ["shutdown"])

    def test_final_countdown_is_cancellable(self):
        h = Harness(minutes=0.1, countdown=10)
        h.arm()
        h.advance(6.1)  # timer done, now in the 10 s countdown
        self.assertEqual(h.engine.state.phase, FIRE)
        self.assertEqual(h.fired, [])
        h.engine.cancel(h.t)
        h.advance(30)
        self.assertEqual(h.engine.state.phase, IDLE)
        self.assertEqual(h.fired, [])

    def test_drain_waits_for_busy_sessions(self):
        h = Harness(minutes=0.05, countdown=0, drain=True)
        h.activity(True)
        h.arm()
        h.advance(4)  # timer expired while busy
        self.assertEqual(h.engine.state.phase, DRAIN)
        self.assertEqual(h.fired, [])
        h.activity(False)
        h.advance(6)
        self.assertEqual(h.engine.state.phase, DRAIN, "grace not elapsed yet")
        h.advance(8)
        self.assertEqual(h.engine.state.phase, DONE)
        self.assertEqual(h.fired, ["shutdown"])

    def test_drain_rearms_grace_when_work_resumes(self):
        h = Harness(minutes=0.05, countdown=0, drain=True, idle_grace=12)
        h.activity(True)
        h.arm()
        h.advance(4)
        self.assertEqual(h.engine.state.phase, DRAIN)
        h.activity(False)
        h.advance(8)
        h.activity(True)   # a new message arrived
        h.advance(8)
        self.assertEqual(h.engine.state.phase, DRAIN)
        h.activity(False)
        h.advance(13)
        self.assertEqual(h.engine.state.phase, DONE)

    def test_no_drain_fires_even_when_busy(self):
        h = Harness(minutes=0.05, countdown=0, drain=False)
        h.activity(True)
        h.arm()
        h.advance(4.5)
        self.assertEqual(h.fired, ["shutdown"])


class WatchMode(unittest.TestCase):
    def test_fires_after_work_finishes(self):
        h = Harness(mode=MODE_WATCH, countdown=0)
        h.activity(True, ("ses_1", "ses_2"))
        h.arm()
        self.assertEqual(h.engine.state.phase, WATCH)
        h.advance(60)
        self.assertEqual(h.fired, [])
        h.activity(False)
        self.assertEqual(h.engine.state.active, 0)
        h.advance(11)
        self.assertEqual(h.fired, [])
        h.advance(3)
        self.assertEqual(h.fired, ["shutdown"])
        self.assertEqual(h.engine.state.phase, DONE)

    def test_armed_while_idle_still_waits_for_late_work(self):
        h = Harness(mode=MODE_WATCH, countdown=0, arm_grace=30)
        h.activity(False)
        h.arm()
        h.advance(10)
        h.activity(True)          # work started in time -> no shutdown
        h.advance(120)
        self.assertEqual(h.fired, [])
        h.activity(False)
        h.advance(13)
        self.assertEqual(h.fired, ["shutdown"])

    def test_armed_while_idle_fires_after_arm_grace(self):
        h = Harness(mode=MODE_WATCH, countdown=0, arm_grace=30)
        h.activity(False)
        h.arm()
        h.advance(29)
        self.assertEqual(h.fired, [])
        h.advance(2)
        self.assertEqual(h.fired, ["shutdown"])

    def test_cancel_inside_countdown(self):
        h = Harness(mode=MODE_WATCH, countdown=5)
        h.activity(False)
        h.arm()
        h.advance(31)
        self.assertEqual(h.engine.state.phase, FIRE)
        h.engine.cancel(h.t)
        h.advance(10)
        self.assertEqual(h.fired, [])


class SettingsTest(unittest.TestCase):
    def test_clamping(self):
        s = Settings(minutes=-4, mode="nope", action="nuke", countdown=-1).clamped()
        self.assertGreaterEqual(s.minutes, 0.05)
        self.assertEqual(s.mode, MODE_TIMER)
        self.assertEqual(s.action, "shutdown")
        self.assertEqual(s.countdown, 0.0)
        self.assertLessEqual(Settings(minutes=99999).clamped().minutes, 24 * 60)

    def test_fraction(self):
        h = Harness(minutes=10, countdown=0)
        h.arm()
        h.advance(300)
        self.assertAlmostEqual(h.engine.state.fraction, 0.5, delta=0.02)


if __name__ == "__main__":
    unittest.main(verbosity=2)
