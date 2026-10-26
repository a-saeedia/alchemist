"""GTK3 front end: a small frameless always-on-top widget you can drag anywhere."""

from __future__ import annotations

import os
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import power  # noqa: E402
from .engine import (  # noqa: E402
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

CSS = """
window, window.background { background-color: transparent; }
#root {
  background-color: rgba(7, 11, 15, 0.96);
  border: 1px solid rgba(34, 211, 238, 0.22);
  border-radius: 16px;
  padding: 14px 15px 12px 15px;
}
#root.fire { border-color: rgba(248, 113, 113, 0.85); }
#root.drain { border-color: rgba(245, 184, 61, 0.70); }
label { color: #cbd5e1; }
.brand {
  color: #5c7285; font-family: "Fira Sans", sans-serif; font-size: 9px;
  font-weight: 700; letter-spacing: 2.4px;
}
.chip {
  color: #07110f; background-color: #22d3ee; border-radius: 7px;
  font-family: "Fira Sans", sans-serif; font-size: 8.5px; font-weight: 800;
  letter-spacing: 1.2px; padding: 2px 7px;
}
.chip.watch { background-color: #f5b83d; }
.chip.drain { background-color: #f5b83d; }
.chip.fire { background-color: #f87171; }
.dot { color: #22d3ee; font-size: 10px; }
.dot.watch, .dot.drain { color: #f5b83d; }
.dot.fire { color: #f87171; }
.dot.done { color: #4ade80; }
.dot.idle { color: #46565f; }
.dot.timer { color: #22d3ee; }
.clock {
  font-family: "Fira Mono", "DejaVu Sans Mono", monospace;
  font-size: 33px; font-weight: 700; letter-spacing: 1.5px;
  color: #4a5c68;
}
.clock.c-cyan { color: #22d3ee; }
.clock.c-gold { color: #f5b83d; }
.clock.c-red { color: #f87171; }
.clock.c-green { color: #4ade80; }
.clock.c-ghost { color: #46565f; }
.rail { background-color: rgba(148, 163, 184, 0.15); border-radius: 2px; }
.railfill { background-color: #22d3ee; border-radius: 2px; }
.railfill.c-gold { background-color: #f5b83d; }
.railfill.c-red { background-color: #f87171; }
.railfill.c-green { background-color: #4ade80; }
.railfill.c-ghost { background-color: #46565f; }
.status {
  font-family: "Fira Sans", sans-serif; font-size: 10.5px; color: #7d95a5;
  padding: 1px 0 0 0;
}
.status.fire { color: #fca5a5; }
button {
  background-image: none; background-color: rgba(148, 163, 184, 0.10);
  border: 1px solid rgba(148, 163, 184, 0.16); box-shadow: none;
  border-radius: 8px; padding: 3px 0; min-height: 19px;
  color: #b6c8d4; font-family: "Fira Sans", sans-serif; font-size: 10.5px;
  font-weight: 600;
}
button:hover { background-color: rgba(34, 211, 238, 0.16); color: #e2f6fb; }
button:active { background-color: rgba(34, 211, 238, 0.26); }
button.arm {
  background-color: rgba(34, 211, 238, 0.20); border-color: rgba(34, 211, 238, 0.55);
  color: #a5f3fc; font-weight: 800; letter-spacing: 2.4px; min-height: 25px;
}
button.arm:hover { background-color: rgba(34, 211, 238, 0.34); color: #ecfeff; }
button.arm.watch {
  background-color: rgba(245, 184, 61, 0.18); border-color: rgba(245, 184, 61, 0.55);
  color: #fde68a;
}
button.arm.watch:hover { background-color: rgba(245, 184, 61, 0.30); }
button.cancel {
  background-color: rgba(248, 113, 113, 0.18); border-color: rgba(248, 113, 113, 0.55);
  color: #fecaca; font-weight: 800; letter-spacing: 2.4px; min-height: 27px;
}
button.cancel:hover { background-color: rgba(248, 113, 113, 0.34); color: #fff1f2; }
button.sel {
  background-color: rgba(34, 211, 238, 0.22); border-color: rgba(34, 211, 238, 0.55);
  color: #a5f3fc;
}
button.sel.watch {
  background-color: rgba(245, 184, 61, 0.20); border-color: rgba(245, 184, 61, 0.55);
  color: #fde68a;
}
button.flat { background-color: transparent; border: none; padding: 0; min-height: 0; }
button.flat:hover { background-color: rgba(248, 113, 113, 0.20); border-radius: 6px; }
button.flat label { color: #5c7285; font-size: 11px; }
button.flat:hover label { color: #fca5a5; }
button.actionbtn {
  background-color: rgba(34, 211, 238, 0.09);
  border: 1px solid rgba(34, 211, 238, 0.28); border-radius: 7px;
  padding: 0; min-height: 19px;
}
.action {
  font-family: "Fira Sans", sans-serif; font-size: 9px; font-weight: 700;
  color: #8fdfe9; letter-spacing: 1.1px; padding: 1px 7px;
}
checkbutton {
  font-family: "Fira Sans", sans-serif; font-size: 10px; color: #7d95a5;
  padding: 0; min-height: 16px;
}
checkbutton:checked { color: #a5f3fc; }
checkbutton check {
  min-width: 11px; min-height: 11px; border-radius: 3px;
  border: 1px solid rgba(148, 163, 184, 0.45);
  background-color: rgba(148, 163, 184, 0.08); background-image: none;
}
checkbutton:checked check { background-color: #22d3ee; border-color: #22d3ee; }
menuitem { font-size: 11px; }
"""

PRESETS = (5, 15, 30, 60)
TRIMS = (-5, -1, 1, 5)

CYAN = (0.13, 0.83, 0.93)
GOLD = (0.96, 0.72, 0.24)
RED = (0.97, 0.44, 0.44)
MUTED = (0.49, 0.56, 0.61)
GHOST = (0.28, 0.35, 0.40)
GREEN = (0.29, 0.87, 0.50)


def fmt_time(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_clock_epoch(epoch: float | None) -> str:
    if not epoch:
        return ""
    return time.strftime("%H:%M", time.localtime(epoch))


COLOR_CLASS = {
    CYAN: "c-cyan",
    GOLD: "c-gold",
    RED: "c-red",
    GREEN: "c-green",
    GHOST: "c-ghost",
    MUTED: "c-ghost",
}
ALL_COLOR_CLASSES = tuple(COLOR_CLASS.values())


class Rail(Gtk.Box):
    """Plain two-box hairline rail.

    Gtk.ProgressBar would be one line of code, but COSMIC's GTK theme paints its
    trough with the accent colour at a higher CSS priority, so the phase colour
    never showed. Two boxes with our own class names cannot be overridden.
    """

    def __init__(self, width: int = 238, height: int = 3) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_size_request(width, height)
        self.get_style_context().add_class("rail")
        self.fraction = 1.0
        self._height = height

        self.fill = Gtk.Box()
        self.fill.get_style_context().add_class("railfill")
        self.fill.get_style_context().add_class("c-ghost")
        self.pack_start(self.fill, False, False, 0)
        self.spacer = Gtk.Box()
        self.pack_start(self.spacer, True, True, 0)
        self.connect("size-allocate", self._on_alloc)

    def _on_alloc(self, _w, alloc) -> None:
        self.fill.set_size_request(max(0, int(round(alloc.width * self.fraction))), self._height)

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        width = self.get_allocated_width() or self.get_width()
        self.fill.set_size_request(
            max(0, int(round(width * self.fraction))), self._height
        )

    def set_colour(self, colour) -> None:
        ctx = self.fill.get_style_context()
        for old in ALL_COLOR_CLASSES:
            ctx.remove_class(old)
        ctx.add_class(COLOR_CLASS.get(colour, "c-ghost"))


class ClockCanvas(Gtk.Box):
    """Big monospace readout over a hairline progress rail."""

    def __init__(self, width: int = 238) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.set_size_request(width, -1)
        self.set_margin_top(1)
        self.set_margin_bottom(1)

        self.label = Gtk.Label(label="30:00")
        self.label.set_xalign(0.0)
        self.label.set_yalign(0.5)
        ctx = self.label.get_style_context()
        ctx.add_class("clock")
        ctx.add_class("c-ghost")
        self.pack_start(self.label, False, False, 0)

        self.bar = Rail(width)
        self.pack_start(self.bar, False, False, 0)

        self.text = "30:00"
        self.fraction = 1.0
        self.fg = GHOST

    def set_state(self, text: str, fraction: float, colour) -> None:
        if text != self.text:
            self.text = text
            self.label.set_text(text)
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self.fraction) > 0.002:
            self.fraction = fraction
            self.bar.set_fraction(fraction)
        if colour != self.fg:
            self.fg = colour
            ctx = self.label.get_style_context()
            for old in ALL_COLOR_CLASSES:
                ctx.remove_class(old)
            ctx.add_class(COLOR_CLASS.get(colour, "c-ghost"))
            self.bar.set_colour(colour)


class OctimerWindow(Gtk.Window):
    def __init__(
        self, settings: Settings, probe, store=None, arm_on_start: bool = False,
        log_file: str | None = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.probe = probe
        self.store = store
        self.engine = Engine(
            settings=settings,
            on_fire=self._on_fire,
            on_note=self._log,
        )
        self._log_lines: list[str] = []
        self._pending_poll = False
        self._quitting = False
        self._snap_detail = ""
        self._snap_source = ""
        self._last_beep = -1
        self._log_file = log_file
        self._arm_on_start = arm_on_start

        self.set_title("oc-timer")
        self.set_wmclass("octimer", "Octimer")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_position(Gtk.WindowPosition.NONE)
        self.set_app_paintable(True)
        self.set_border_width(0)
        screen = self.get_screen()
        if screen is not None and screen.get_rgba_visual() is not None:
            self.set_visual(screen.get_rgba_visual())
        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key)
        self.connect("map-event", self._on_map)
        self.stick()

        self._build()
        self._load_position()
        self._poll_probe(force=True)
        GLib.timeout_add(250, self._tick)
        GLib.timeout_add(2000, self._poll_probe)
        self._render()

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
        )

        self.eventbox = Gtk.EventBox()
        self.eventbox.set_visible_window(False)
        # The EventBox shares the toplevel GdkWindow (visible_window=False), so it
        # is never the event target -- presses and scrolls arrive on the window
        # itself. Buttons still consume their own clicks first (they own input
        # windows), so the drag only starts on empty card area.
        self.connect("button-press-event", self._on_press)
        self.connect("scroll-event", self._on_scroll)
        self.add(self.eventbox)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root.set_name("root")
        self.root.set_size_request(238, -1)
        self.eventbox.add(self.root)

        # -- header
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dot = Gtk.Label(label="\u25cf")
        self.dot.get_style_context().add_class("dot")
        self.dot.set_valign(Gtk.Align.CENTER)
        brand = Gtk.Label(label="OCTIMER")
        brand.get_style_context().add_class("brand")
        brand.set_valign(Gtk.Align.CENTER)
        self.chip = Gtk.Label(label="TIMER")
        self.chip.get_style_context().add_class("chip")
        self.chip.set_valign(Gtk.Align.CENTER)
        close = self.close_btn = Gtk.Button(label="\u2715")
        close.get_style_context().add_class("flat")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.set_tooltip_text("Quit")
        close.connect("clicked", lambda *_: self._quit())
        head.pack_start(self.dot, False, False, 0)
        head.pack_start(brand, False, False, 0)
        head.pack_start(Gtk.Box(), True, True, 0)
        head.pack_end(close, False, False, 0)
        head.pack_end(self.chip, False, False, 5)
        self.root.pack_start(head, False, False, 0)

        # -- clock + rail
        self.clock = ClockCanvas()
        self.root.pack_start(self.clock, False, False, 0)

        # -- status
        self.status = Gtk.Label(label="ready")
        self.status.get_style_context().add_class("status")
        self.status.set_xalign(0.0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_max_width_chars(42)
        self.root.pack_start(self.status, False, False, 0)

        # -- idle controls
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.controls.set_margin_top(10)
        self.root.pack_start(self.controls, False, False, 0)

        self.trim_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.trim_row.set_homogeneous(True)
        for delta in TRIMS:
            txt = ("\u2212" if delta < 0 else "+") + f"{abs(delta)}m"
            self.trim_row.pack_start(
                self._mk_button(txt, lambda _b, d=delta: self._bump(d * 60)), True, True, 0
            )
        self.controls.pack_start(self.trim_row, False, False, 0)

        self.preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.preset_row.set_homogeneous(True)
        for minutes in PRESETS:
            self.preset_row.pack_start(
                self._mk_button(f"{minutes}m", lambda _b, m=minutes: self._set_minutes(m)),
                True,
                True,
                0,
            )
        self.controls.pack_start(self.preset_row, False, False, 0)

        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        mode_row.set_homogeneous(True)
        self.btn_timer = self._mk_button("TIMER", lambda *_: self._set_mode(MODE_TIMER))
        self.btn_watch = self._mk_button("WATCH OC", lambda *_: self._set_mode(MODE_WATCH))
        mode_row.pack_start(self.btn_timer, True, True, 0)
        mode_row.pack_start(self.btn_watch, True, True, 0)
        self.controls.pack_start(mode_row, False, False, 0)

        opts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.chk_drain = Gtk.CheckButton(label="wait for opencode")
        self.chk_drain.set_active(self.engine.settings.drain)
        self.chk_drain.connect("toggled", self._on_drain_toggled)
        opts.pack_start(self.chk_drain, False, False, 0)
        opts.pack_start(Gtk.Box(), True, True, 0)
        self.action_btn = Gtk.MenuButton()
        self.action_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.action_btn.set_focus_on_click(False)
        self.action_btn.get_style_context().add_class("actionbtn")
        self.action_lbl = Gtk.Label(label=self._action_text())
        self.action_lbl.get_style_context().add_class("action")
        self.action_btn.add(self.action_lbl)
        self._build_action_menu()
        opts.pack_start(self.action_btn, False, False, 0)
        self.controls.pack_start(opts, False, False, 0)

        self.arm_btn = Gtk.Button(label="ARM")
        self.arm_btn.get_style_context().add_class("arm")
        self.arm_btn.set_focus_on_click(False)
        self.arm_btn.connect("clicked", self._on_arm)
        self.arm_btn.set_margin_top(3)
        self.controls.pack_start(self.arm_btn, False, False, 0)

        # -- armed control
        self.cancel_btn = Gtk.Button(label="CANCEL")
        self.cancel_btn.get_style_context().add_class("cancel")
        self.cancel_btn.set_focus_on_click(False)
        self.cancel_btn.connect("clicked", lambda *_: self._cancel())
        self.cancel_btn.set_margin_top(10)
        self.cancel_btn.set_no_show_all(True)
        self.root.pack_start(self.cancel_btn, False, False, 0)

        # -- context menu
        self.menu = Gtk.Menu()
        for text, cb in (("Reset position", self._reset_position), ("Quit", self._quit)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _w, fn=cb: fn())
            self.menu.append(item)
        self.menu.show_all()

        self.root.show_all()
        self.cancel_btn.hide()

    def _mk_button(self, label: str, cb) -> Gtk.Button:
        b = Gtk.Button(label=label)
        b.set_focus_on_click(False)
        b.connect("clicked", cb)
        return b

    def _build_action_menu(self) -> None:
        menu = Gtk.Menu()
        for action in ("shutdown", "suspend", "lock", "notify"):
            item = Gtk.MenuItem(label=power.label(action))
            item.connect("activate", lambda _w, a=action: self._set_action(a))
            menu.append(item)
        menu.show_all()
        self.action_btn.set_popup(menu)

    def _action_text(self) -> str:
        return f"{power.label(self.engine.settings.action).upper()}  \u25be"

    def start(self) -> None:
        """Show everything, then re-hide whatever the phase does not need.

        show_all() is required or the event box (and therefore the whole card)
        never gets mapped; _render() runs right after so the CANCEL button does
        not flash on an idle widget.
        """
        self.show_all()
        self._render()
        self.present()

    def _on_map(self, *_a) -> bool:
        self._render()
        if self._arm_on_start:
            self._arm_on_start = False
            GLib.timeout_add(350, lambda: (self._on_arm(), False)[1])
        return False

    # -------------------------------------------------------------- handlers
    def _over_control(self, x_root: int, y_root: int) -> bool:
        """True if the screen point sits on a control we must not steal clicks from."""
        for widget in (
            self.close_btn,
            self.arm_btn,
            self.cancel_btn,
            self.action_btn,
            self.chk_drain,
            self.btn_timer,
            self.btn_watch,
            *self.trim_row.get_children(),
            *self.preset_row.get_children(),
        ):
            if not widget.get_visible() or not widget.get_mapped():
                continue
            res = widget.translate_coordinates(self, 0, 0)
            if len(res) == 3:
                ok, wx, wy = res
            else:
                wx, wy = res
                ok = wx is not None
            if not ok:
                continue
            if (
                wx <= x_root <= wx + widget.get_allocated_width()
                and wy <= y_root <= wy + widget.get_allocated_height()
            ):
                return True
        return False

    def _on_press(self, _w, event) -> bool:
        if event.button == 1 and self._over_control(event.x, event.y):
            return False
        if event.button == 1:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        if event.button == 3:
            self.menu.popup_at_pointer(event)
            return True
        return False

    def _on_scroll(self, _w, event) -> bool:
        if self.engine.state.armed:
            return False
        step = 300 if event.state & Gdk.ModifierType.SHIFT_MASK else 60
        if event.direction == Gdk.ScrollDirection.UP:
            delta = step
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = -step
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = event.get_scroll_deltas()
            if not ok or not dy:
                return False
            delta = -step if dy > 0 else step
        else:
            return False
        self._bump(delta)
        return True

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            if self.engine.state.armed:
                self._cancel()
            else:
                self._quit()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if not self.engine.state.armed:
                self._on_arm()
                return True
        return False

    def _on_drain_toggled(self, btn) -> None:
        self.engine.settings.drain = btn.get_active()
        self._save_state()
        self._render()

    def _set_action(self, action: str) -> None:
        self.engine.settings.action = action
        self.action_lbl.set_text(self._action_text())
        self._save_state()
        self._render()

    def _set_mode(self, mode: str) -> None:
        if self.engine.state.armed:
            return
        self.engine.settings.mode = mode
        if mode == MODE_WATCH:
            self.engine.settings.drain = True
            self.chk_drain.set_active(True)
        self._save_state()
        self._render()

    def _set_minutes(self, minutes: float) -> None:
        if self.engine.state.armed:
            return
        self.engine.settings.minutes = max(0.05, min(24 * 60.0, float(minutes)))
        self._save_state()
        self._render()

    def _bump(self, seconds: float) -> None:
        self._set_minutes(self.engine.settings.minutes + seconds / 60.0)

    def _on_arm(self, *_a) -> None:
        if self.engine.state.armed:
            return
        self.engine.arm(time.monotonic())
        self._render()
        mode = "WATCH" if self.engine.settings.mode == MODE_WATCH else "TIMER"
        self._notify(
            "oc-timer armed",
            f"{mode} \u00b7 {self.engine.state.note} \u00b7 {power.label(self.engine.settings.action)}",
        )
        self._log(f"armed {mode}")

    def _cancel(self) -> None:
        self.engine.cancel(time.monotonic())
        self._render()

    def _reset_position(self) -> None:
        self.move(60, 60)
        self._save_state()

    def _quit(self) -> None:
        if self._quitting:
            return
        self._save_state()
        self._quitting = True
        Gtk.main_quit()

    def _on_delete(self, *_a) -> bool:
        self._quit()
        return True

    # --------------------------------------------------------------- firing
    def _on_fire(self, action: str) -> None:
        ok, msg = power.execute(action, log=self._log)
        self._log(f"fire {action}: ok={ok} {msg}")
        self._notify(
            f"oc-timer: {power.label(action)}", msg if ok else f"failed: {msg}"
        )
        if ok and action in ("shutdown", "suspend"):
            GLib.timeout_add(2500, self._quit)

    # ---------------------------------------------------------------- probe
    def _poll_probe(self, force: bool = False):
        if self._pending_poll:
            return True
        self._pending_poll = True

        def work():
            try:
                snap = self.probe.snapshot(force)
            except Exception as exc:  # never kill the widget over a probe
                self._log(f"probe error: {exc}")
                snap = None
            GLib.idle_add(self._apply_snapshot, snap)
            return False

        threading.Thread(target=work, daemon=True).start()
        return True

    def _apply_snapshot(self, snap) -> bool:
        self._pending_poll = False
        if self._quitting:
            return False
        if snap is not None:
            self.engine.set_activity(snap.busy, snap.ids, time.monotonic())
            self._snap_detail = snap.detail
            self._snap_source = snap.source
        self._render()
        return False

    # ----------------------------------------------------------------- tick
    def _tick(self):
        if self._quitting:
            return False
        prev = self.engine.state.phase
        st = self.engine.tick(time.monotonic())
        if st.phase == FIRE:
            second = int(round(st.remaining))
            if prev != FIRE or second != self._last_beep:
                self._last_beep = second
                Gdk.beep()
        else:
            self._last_beep = -1
        self._render()
        if st.phase == DONE and prev != DONE:
            self._log("done")
        return True

    # --------------------------------------------------------------- render
    def _render(self) -> None:
        if self._quitting:
            return
        st = self.engine.state
        s = self.engine.settings
        armed = st.armed

        chip_text = {
            IDLE: "TIMER" if s.mode == MODE_TIMER else "WATCH",
            TIMER: "TIMER",
            WATCH: "WATCH",
            DRAIN: "DRAIN",
            FIRE: "FIRE",
            DONE: "DONE",
        }[st.phase]
        self.chip.set_text(chip_text)
        chip_ctx = self.chip.get_style_context()
        for cls in ("watch", "drain", "fire"):
            chip_ctx.remove_class(cls)
        if st.phase in (WATCH, DRAIN):
            chip_ctx.add_class("watch")
        elif st.phase == FIRE:
            chip_ctx.add_class("fire")

        dot_ctx = self.dot.get_style_context()
        for cls in ("watch", "drain", "fire", "done", "idle", "timer"):
            dot_ctx.remove_class(cls)
        dot_state = {
            IDLE: "idle",
            TIMER: "timer",
            WATCH: "watch",
            DRAIN: "drain",
            FIRE: "fire",
            DONE: "done",
        }
        dot_ctx.add_class(dot_state.get(st.phase, "idle"))

        root_ctx = self.root.get_style_context()
        for cls in ("fire", "drain"):
            root_ctx.remove_class(cls)
        if st.phase == FIRE:
            root_ctx.add_class("fire")
        elif st.phase == DRAIN:
            root_ctx.add_class("drain")

        status_ctx = self.status.get_style_context()
        status_ctx.remove_class("fire")
        if st.phase == FIRE:
            status_ctx.add_class("fire")

        # clock
        if st.phase == FIRE:
            self.clock.set_state(fmt_time(st.remaining), st.fraction, RED)
        elif st.phase == TIMER:
            self.clock.set_state(fmt_time(st.remaining), st.fraction, CYAN)
        elif st.phase in (WATCH, DRAIN):
            self.clock.set_state("--:--", 1.0, GOLD if st.phase == WATCH else GOLD)
        elif st.phase == DONE:
            self.clock.set_state("00:00", 0.0, GREEN)
        else:
            if s.mode == MODE_WATCH:
                self.clock.set_state("--:--", 1.0, GOLD)
            else:
                self.clock.set_state(fmt_time(s.minutes * 60), 1.0, GHOST)

        # status
        active = st.active
        oc = f"{active} running" if active else "idle"
        if st.phase == IDLE:
            if s.mode == MODE_WATCH:
                text = f"opencode {oc} \u00b7 arm to wait for finish"
            else:
                end = time.time() + s.minutes * 60
                text = f"opencode {oc} \u00b7 ends {fmt_clock_epoch(end)}"
                if s.drain:
                    text += " \u00b7 then waits"
        elif st.phase == TIMER:
            text = f"{st.note} \u00b7 opencode {oc}"
            if s.drain and active:
                text = f"timer {fmt_time(st.remaining)} \u00b7 {active} running, will wait"
        elif st.phase == WATCH:
            if active:
                text = f"opencode busy \u00b7 {active} running"
            elif st.wait_left is not None and not st.note.startswith("waiting"):
                text = f"nothing running \u00b7 fires in {st.wait_left:.0f}s unless work starts"
            else:
                left = st.wait_left if st.wait_left is not None else s.idle_grace
                text = f"opencode idle {st.idle_for:.0f}s \u00b7 off in {left:.0f}s"
        elif st.phase == DRAIN:
            if active:
                text = f"{active} session(s) still working \u00b7 shuts down when idle"
            else:
                left = st.wait_left if st.wait_left is not None else s.idle_grace
                text = f"opencode idle {st.idle_for:.0f}s \u00b7 {left:.0f}s to shutdown"
        elif st.phase == FIRE:
            text = f"{power.label(s.action)} in {int(round(st.remaining))}s \u00b7 cancel to stop"
        else:
            text = st.note or "done"
        self.status.set_text(text)

        # controls
        self.controls.set_visible(not armed)
        self.cancel_btn.set_visible(armed)
        if not armed:
            watch = s.mode == MODE_WATCH
            self.trim_row.set_visible(not watch)
            self.preset_row.set_visible(not watch)
            self.arm_btn.set_label("WATCH" if watch else "ARM")
            actx = self.arm_btn.get_style_context()
            actx.remove_class("watch")
            if watch:
                actx.add_class("watch")
            for btn, selected in ((self.btn_timer, not watch), (self.btn_watch, watch)):
                bctx = btn.get_style_context()
                bctx.remove_class("sel")
                bctx.remove_class("watch")
                if selected:
                    bctx.add_class("sel")
                    if watch:
                        bctx.add_class("watch")
            self.chk_drain.set_sensitive(not watch)
        if st.phase == FIRE:
            self.cancel_btn.set_label(f"CANCEL  \u00b7  {int(round(st.remaining))}")
        else:
            self.cancel_btn.set_label("CANCEL")

    # ---------------------------------------------------------------- store
    def _state_path(self) -> str:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "octimer", "state.json")

    def _save_state(self) -> None:
        import json

        s = self.engine.settings
        try:
            x, y = self.get_position()
        except Exception:
            x = y = None
        data = {
            "minutes": s.minutes,
            "mode": s.mode,
            "drain": s.drain,
            "action": s.action,
            "x": x,
            "y": y,
        }
        try:
            path = self._state_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _load_position(self) -> None:
        data = self.store if isinstance(self.store, dict) else {}
        x, y = data.get("x"), data.get("y")
        if isinstance(x, int) and isinstance(y, int):
            GLib.idle_add(lambda: (self.move(x, y), False)[1])
        else:
            GLib.idle_add(lambda: (self.move(80, 80), False)[1])

    # ------------------------------------------------------------- utilities
    def _log(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        self._log_lines.append(line)
        del self._log_lines[:-400]
        if not self._log_file:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._log_file)), exist_ok=True)
            with open(self._log_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _notify(self, title: str, body: str) -> None:
        try:
            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            if not Notify.is_initted():
                Notify.init("oc-timer")
            n = Notify.Notification.new(title, body, "system-shutdown")
            n.set_urgency(2 if "shut" in title.lower() else 1)
            n.show()
        except Exception:
            pass

    # --------------------------------------------------------------- shoot
    def shoot(self, path: str) -> bool:
        win = self.get_window()
        if win is None:
            return False
        w = min(self.get_allocated_width(), win.get_width())
        h = min(self.get_allocated_height(), win.get_height())
        pb = Gdk.pixbuf_get_from_window(win, 0, 0, w, h)
        if pb is None:
            return False
        pb.savev(path, "png", [], [])
        return True
