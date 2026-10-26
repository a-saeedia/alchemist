"""Pure state machine for oc-timer.

No GTK, no subprocesses, no clocks of its own -- everything is injected so the
whole trigger logic is unit-testable.

Phases
------
idle    nothing armed
timer   counting down to zero
watch   armed: waiting for opencode to be busy, then idle
drain   timer/session target reached but opencode is still working
fire    final "shutdown in N" window, cancellable
done    action executed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

IDLE = "idle"
TIMER = "timer"
WATCH = "watch"
DRAIN = "drain"
FIRE = "fire"
DONE = "done"

MODE_TIMER = "timer"
MODE_WATCH = "watch"
MODES = (MODE_TIMER, MODE_WATCH)

ACTIONS = ("shutdown", "suspend", "lock", "notify")


@dataclass
class Settings:
    minutes: float = 30.0
    mode: str = MODE_TIMER
    drain: bool = False          # finish the timer, then wait for opencode
    action: str = "shutdown"
    idle_grace: float = 12.0     # continuous idle seconds that count as "finished"
    arm_grace: float = 30.0      # watch armed while already idle -> fire after this
    countdown: float = 10.0      # cancellable final countdown

    def clamped(self) -> "Settings":
        s = Settings(**self.__dict__)
        s.minutes = max(0.05, min(float(s.minutes), 24 * 60))
        if s.mode not in MODES:
            s.mode = MODE_TIMER
        if s.action not in ACTIONS:
            s.action = "shutdown"
        s.idle_grace = max(0.0, min(float(s.idle_grace), 600.0))
        s.arm_grace = max(0.0, min(float(s.arm_grace), 3600.0))
        s.countdown = max(0.0, min(float(s.countdown), 120.0))
        return s


@dataclass
class State:
    phase: str = IDLE
    remaining: float = 0.0       # seconds left (timer) or left in countdown (fire)
    total: float = 0.0
    active: int = 0
    active_ids: tuple = ()
    note: str = ""
    fired: bool = False
    fire_at: float | None = None  # epoch seconds, for "fires at HH:MM"
    idle_for: float = 0.0         # continuous idle seconds as of the last tick
    wait_left: float | None = None  # seconds until the phase resolves

    @property
    def armed(self) -> bool:
        return self.phase not in (IDLE, DONE)

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining / self.total))


@dataclass
class Engine:
    settings: Settings = field(default_factory=Settings)
    on_fire: Callable[[str], None] | None = None
    on_note: Callable[[str], None] | None = None

    state: State = field(default_factory=State)
    busy: bool = False
    busy_ids: tuple = ()
    busy_seen: bool = False
    idle_since: float | None = None
    armed_at: float = 0.0
    deadline: float | None = None
    countdown_until: float | None = None

    # ---------------------------------------------------------------- arming
    def arm(self, now: float) -> State:
        self.settings = self.settings.clamped()
        self.busy_seen = self.busy
        self.idle_since = None
        self.armed_at = now
        self.countdown_until = None
        st = self.state = State(active=len(self.busy_ids), active_ids=self.busy_ids)
        if self.settings.mode == MODE_WATCH:
            st.phase = WATCH
            st.note = "waiting for opencode work" if not self.busy else "opencode busy"
            self.deadline = None
        else:
            st.phase = TIMER
            st.total = self.settings.minutes * 60.0
            st.remaining = st.total
            self.deadline = now + st.total
            st.note = "counting down"
        return st

    def cancel(self, now: float) -> State:
        self.deadline = None
        self.countdown_until = None
        self.idle_since = None
        self.state = State(active=len(self.busy_ids), active_ids=self.busy_ids)
        self._note("cancelled")
        return self.state

    # -------------------------------------------------------------- activity
    def set_activity(
        self, busy: bool, ids: Sequence[str] = (), now: float = 0.0
    ) -> None:
        self.busy_ids = tuple(ids)
        self.busy = bool(busy)
        self.state.active = len(self.busy_ids)
        self.state.active_ids = self.busy_ids
        if self.busy:
            self.busy_seen = True
            self.idle_since = None

    # ------------------------------------------------------------------ tick
    def tick(self, now: float) -> State:
        st = self.state
        st.active = len(self.busy_ids)
        st.active_ids = self.busy_ids
        if not st.armed:
            return st

        if self.busy:
            self.idle_since = None
        elif self.idle_since is None:
            self.idle_since = now
        idle_for = 0.0 if self.idle_since is None else now - self.idle_since

        phase = st.phase

        if phase == TIMER:
            st.idle_for = idle_for
            st.wait_left = None
            assert self.deadline is not None
            st.remaining = max(0.0, self.deadline - now)
            st.fire_at = self.deadline
            if st.remaining <= 0.0:
                if self.settings.drain and self.busy:
                    self._enter_drain(now, "timer done, opencode still working")
                else:
                    self._enter_fire(now, "timer done")
            return st

        if phase == WATCH:
            st.idle_for = idle_for
            if self.busy:
                st.note = "opencode busy"
                st.wait_left = None
            elif self.busy_seen:
                st.note = "waiting for idle"
                st.wait_left = max(0.0, self.settings.idle_grace - idle_for)
                if idle_for >= self.settings.idle_grace:
                    self._enter_fire(now, "all sessions finished")
            else:
                st.note = "nothing running yet"
                st.wait_left = max(0.0, self.settings.arm_grace - (now - self.armed_at))
                if now - self.armed_at >= self.settings.arm_grace:
                    self._enter_fire(now, "nothing was running")
            return st

        if phase == DRAIN:
            st.idle_for = idle_for
            st.note = "draining"
            st.wait_left = max(0.0, self.settings.idle_grace - idle_for)
            if not self.busy and idle_for >= self.settings.idle_grace:
                self._enter_fire(now, "all sessions finished")
            return st

        if phase == FIRE:
            assert self.countdown_until is not None
            st.remaining = max(0.0, self.countdown_until - now)
            st.fire_at = self.countdown_until
            if st.remaining <= 0.0:
                st.phase = DONE
                st.remaining = 0.0
                st.fired = True
                st.note = f"{self.settings.action} issued"
                if self.on_fire:
                    self.on_fire(self.settings.action)
            return st

        return st

    # --------------------------------------------------------------- helpers
    def _enter_drain(self, now: float, note: str) -> None:
        self.state.phase = DRAIN
        self.state.remaining = 0.0
        self.state.note = note
        self.state.fire_at = None
        self.idle_since = None
        self._note(note)

    def _enter_fire(self, now: float, note: str) -> None:
        self.state.phase = FIRE
        self.state.total = max(self.settings.countdown, 0.1)
        self.state.remaining = self.state.total
        self.countdown_until = now + self.settings.countdown
        self.state.fire_at = self.countdown_until
        self.state.note = note
        self._note(f"{note} -> {self.settings.action} in {self.settings.countdown:.0f}s")

    def _note(self, msg: str) -> None:
        if self.on_note:
            self.on_note(msg)
