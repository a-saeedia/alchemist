"""GTK3 front end: a small always-on-top VPN switch that lives in the corner.

Same visual language as oc-timer (frameless card, dark glass, mono readout) and
the same X11-via-XWayland trick, because COSMIC gives Wayland clients neither
always-on-top nor self-initiated moves.
"""

from __future__ import annotations

import os
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import creds, nm  # noqa: E402

CSS = """
window, window.background { background-color: transparent; }
#root {
  background-color: rgba(7, 11, 15, 0.96);
  border: 1px solid rgba(34, 211, 238, 0.22);
  border-radius: 16px;
  padding: 14px 16px 13px 16px;
}
#root.warn { border-color: rgba(245, 184, 61, 0.70); }
#root.err  { border-color: rgba(248, 113, 113, 0.75); }
#root.dotmode { padding: 9px; border-radius: 9999px; }
#root.dotmode .dot { font-size: 16px; }
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
.chip.off   { background-color: rgba(148, 163, 184, 0.28); color: #9fb3c1; }
.chip.warn  { background-color: #f5b83d; }
.chip.err   { background-color: #f87171; color: #1a0707; }
.dot { color: #4ade80; font-size: 10px; }
.dot.off  { color: #46565f; }
.dot.warn { color: #f5b83d; }
.dot.err  { color: #f87171; }
.profile {
  font-family: "Fira Sans", sans-serif; font-size: 11.5px; font-weight: 600;
  color: #dbe7ee;
}
.ip {
  font-family: "Fira Mono", "DejaVu Sans Mono", monospace;
  font-size: 12px; font-weight: 700; letter-spacing: 0.4px; color: #22d3ee;
}
.ip.off { color: #46565f; }
.status {
  font-family: "Fira Sans", sans-serif; font-size: 9.5px; color: #7d95a5;
}
.status.err { color: #fca5a5; }
button {
  background-image: none; background-color: rgba(148, 163, 184, 0.10);
  border: 1px solid rgba(148, 163, 184, 0.16); box-shadow: none;
  border-radius: 8px; padding: 2px 0; min-height: 21px;
  color: #b6c8d4; font-family: "Fira Sans", sans-serif; font-size: 10.5px;
  font-weight: 600;
}
button:hover { background-color: rgba(34, 211, 238, 0.16); color: #e2f6fb; }
button:active { background-color: rgba(34, 211, 238, 0.26); }
button:disabled { background-color: rgba(148, 163, 184, 0.06); color: #52636f; }
button.power {
  background-color: rgba(34, 211, 238, 0.16); border-color: rgba(34, 211, 238, 0.45);
  color: #a5f3fc; font-size: 12px; padding: 0 9px;
}
button.power:hover { background-color: rgba(34, 211, 238, 0.30); color: #ecfeff; }
button.power.off { background-color: rgba(148, 163, 184, 0.10); color: #8fa3b0; }
button.newip {
  background-color: rgba(245, 184, 61, 0.13); border-color: rgba(245, 184, 61, 0.42);
  color: #fde68a; letter-spacing: 0.8px;
}
button.newip:hover { background-color: rgba(245, 184, 61, 0.26); color: #fffbeb; }
button.flat { background-color: transparent; border: none; padding: 0; min-height: 0; }
button.flat:hover { background-color: rgba(248, 113, 113, 0.20); border-radius: 6px; }
button.flat label { color: #5c7285; font-size: 11px; }
button.flat:hover label { color: #fca5a5; }
menuitem { font-size: 11px; }
.vpn-head { font-family: "Fira Sans", sans-serif; font-size: 12px; font-weight: 700; color: #dbe7ee; }
.vpn-sub  { font-family: "Fira Sans", sans-serif; font-size: 10px; color: #7d95a5; }
entry { font-family: "Fira Sans", sans-serif; font-size: 11px; }
"""

WIDTH = 300

CYAN = (0.13, 0.83, 0.93)


class VpnWindow(Gtk.Window):
    def __init__(
        self,
        store: dict | None = None,
        profile: str = "",
        log_file: str | None = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.POPUP)
        self.store = store or {}
        self.preferred = profile or self.store.get("profile", "")
        self._log_file = log_file
        self._quitting = False
        self._busy = False
        self._placed = False
        self._drag = None
        self._dragged = False
        self._collapsed = bool(self.store.get("collapsed", False))
        self._applied_collapsed = None
        self._good = list(self.store.get("good", []))
        self._status = nm.Status()
        self._pending = False
        self._ip_due = 0.0
        self._msg = ""
        self._msg_err = False
        self.no_save = False  # --shoot must never touch the user's state file

        self.set_title("oc-vpn")
        self.set_wmclass("ocvpn", "Ocvpn")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_position(Gtk.WindowPosition.NONE)
        self.set_app_paintable(True)
        self.set_border_width(0)
        screen = self.get_screen()
        if screen is not None and screen.get_rgba_visual() is not None:
            self.set_visual(screen.get_rgba_visual())
        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key)
        self.connect("map-event", self._on_map)
        self.connect("button-press-event", self._on_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )

        self._build()
        self._render()
        self._poll()
        GLib.timeout_add(3000, self._poll)
        GLib.timeout_add(1000, self._tick)

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
        )

        self.eventbox = Gtk.EventBox()
        self.eventbox.set_visible_window(False)
        self.add(self.eventbox)

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.root.set_name("root")
        self.root.set_size_request(WIDTH, -1)
        self.eventbox.add(self.root)

        # -- header
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dot = Gtk.Label(label="\u25cf")
        self.dot.get_style_context().add_class("dot")
        self.dot.get_style_context().add_class("off")
        self.dot.set_valign(Gtk.Align.CENTER)
        brand = self.brand = Gtk.Label(label="OC-VPN")
        brand.get_style_context().add_class("brand")
        brand.set_valign(Gtk.Align.CENTER)
        self.chip = Gtk.Label(label="OFF")
        self.chip.get_style_context().add_class("chip")
        self.chip.get_style_context().add_class("off")
        self.chip.set_valign(Gtk.Align.CENTER)
        close = self.close_btn = Gtk.Button(label="\u2715")
        close.get_style_context().add_class("flat")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.set_tooltip_text("Quit")
        close.connect("clicked", lambda *_: self._quit())

        self.min_btn = Gtk.Button(label="\u2013")
        self.min_btn.get_style_context().add_class("flat")
        self.min_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.min_btn.set_focus_on_click(False)
        self.min_btn.set_tooltip_text("Collapse to a bar")
        self.min_btn.connect("clicked", lambda *_: self._toggle_collapse())

        head.pack_start(self.dot, False, False, 0)
        head.pack_start(brand, False, False, 0)
        head.pack_start(Gtk.Box(), True, True, 0)
        head.pack_end(close, False, False, 0)
        head.pack_end(self.min_btn, False, False, 2)
        head.pack_end(self.chip, False, False, 6)
        self.root.pack_start(head, False, False, 0)

        # -- profile
        self.profile_lbl = Gtk.Label(label="disconnected")
        self.profile_lbl.get_style_context().add_class("profile")
        self.profile_lbl.set_xalign(0.0)
        self.profile_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.profile_lbl.set_max_width_chars(30)
        self.profile_lbl.set_margin_top(7)
        self.root.pack_start(self.profile_lbl, False, False, 0)

        # -- ip + actions
        row = self.actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_top(3)
        self.ip_lbl = Gtk.Label(label="\u2014")
        self.ip_lbl.get_style_context().add_class("ip")
        self.ip_lbl.get_style_context().add_class("off")
        self.ip_lbl.set_xalign(0.0)
        self.ip_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.ip_lbl.set_max_width_chars(16)

        self.power_btn = Gtk.Button(label="\u23fb")
        self.power_btn.get_style_context().add_class("power")
        self.power_btn.get_style_context().add_class("off")
        self.power_btn.set_focus_on_click(False)
        self.power_btn.set_tooltip_text("Connect / disconnect")
        self.power_btn.set_size_request(34, -1)
        self.power_btn.connect("clicked", lambda *_: self._on_power())

        self.newip_btn = Gtk.Button(label="NEW IP")
        self.newip_btn.get_style_context().add_class("newip")
        self.newip_btn.set_focus_on_click(False)
        self.newip_btn.set_tooltip_text("Switch to the next server and reconnect")
        self.newip_btn.set_size_request(70, -1)
        self.newip_btn.connect("clicked", lambda *_: self._on_new_ip())

        row.pack_start(self.ip_lbl, True, True, 0)
        row.pack_end(self.newip_btn, False, False, 0)
        row.pack_end(self.power_btn, False, False, 0)
        self.root.pack_start(row, False, False, 0)

        # -- status
        self.status_lbl = Gtk.Label(label="")
        self.status_lbl.get_style_context().add_class("status")
        self.status_lbl.set_xalign(0.0)
        self.status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_lbl.set_max_width_chars(40)
        self.status_lbl.set_margin_top(4)
        self.root.pack_start(self.status_lbl, False, False, 0)

        # -- context menu
        self.menu = Gtk.Menu()
        self.profile_menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Profiles")
        item.set_submenu(self.profile_menu)
        self.menu.append(item)

        self.providers_menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Providers")
        item.set_submenu(self.providers_menu)
        self.menu.append(item)

        self._add_item("Save login\u2026", self._on_save_login)
        self._add_item("New IP now", self._on_new_ip)
        self._add_item("Stop manual openvpn", self._on_adopt)
        self._add_item("Open dashboard", self._on_dashboard)
        self.menu.append(Gtk.SeparatorMenuItem())
        self._add_item("Reset position", self._reset_position)
        self._add_item("Quit", self._quit)
        self.menu.show_all()

        self.root.show_all()

    def _add_item(self, label: str, cb) -> None:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _w: cb())
        self.menu.append(item)

    def _refresh_menu(self) -> None:
        for child in self.profile_menu.get_children():
            self.profile_menu.remove(child)
        names = nm.profile_names()
        if not names:
            item = Gtk.MenuItem(label="(no VPN profiles)")
            item.set_sensitive(False)
            self.profile_menu.append(item)
        for name in names:
            item = Gtk.MenuItem(label=name)
            if name == self._status.name:
                item.set_label(f"\u2713 {name}")
            item.connect("activate", lambda _w, n=name: self._on_pick(n))
            self.profile_menu.append(item)
        self.profile_menu.show_all()
        self._refresh_providers_menu()

    def _refresh_providers_menu(self) -> None:
        for child in self.providers_menu.get_children():
            self.providers_menu.remove(child)
        try:
            from . import providers
        except Exception:
            self.providers_menu.show_all()
            return
        installed = providers.installed_providers(free_only=True)
        if not installed:
            item = Gtk.MenuItem(label="(no providers installed)")
            item.set_sensitive(False)
            self.providers_menu.append(item)
        for p in installed:
            item = Gtk.MenuItem(label=f"{p.name} ({'free' if p.free else 'paid'})")
            item.connect("activate", lambda _w, pid=p.id: self._on_launch_provider(pid))
            self.providers_menu.append(item)
        self.providers_menu.append(Gtk.SeparatorMenuItem())
        missing = [p for p in providers.PROVIDERS if p.free and not providers.is_installed(p)]
        if missing:
            more = Gtk.MenuItem(label=f"{len(missing)} more available")
            more.set_sensitive(False)
            self.providers_menu.append(more)
        self.providers_menu.show_all()

    def _on_launch_provider(self, pid: str) -> None:
        try:
            from . import providers
            ok, msg = providers.launch(pid)
        except Exception as exc:
            ok, msg = False, str(exc)
        self._note(msg, err=not ok)

    # -------------------------------------------------------------- position
    #
    # COSMIC's XWayland ignores programmatic moves on WM-managed windows, so a
    # normal toplevel always opens wherever the compositor felt like putting it.
    # A POPUP toplevel is override-redirect: no WM, real `move()`, and it stacks
    # above managed windows for free -- which is exactly the always-on-top card
    # we wanted. The trade-off is that dragging is ours to implement.
    def _on_map(self, *_a) -> bool:
        if self._placed:
            return False
        self._applied_collapsed = None  # show_all() just re-showed everything
        self._apply_collapsed()
        x, y = self.store.get("x"), self.store.get("y")
        if isinstance(x, int) and isinstance(y, int) and self._on_screen(x, y):
            self.move(x, y)
            self._placed = True
            return False
        GLib.timeout_add(40, self._place_once)
        return False

    def _on_screen(self, x: int, y: int) -> bool:
        """A saved position from a different monitor layout is not worth keeping."""
        screen = self.get_screen()
        if screen is None:
            return False
        for i in range(screen.get_n_monitors()):
            geo = screen.get_monitor_geometry(i)
            if geo.x <= x < geo.x + geo.width and geo.y <= y < geo.y + geo.height:
                return True
        return False

    def _place_once(self) -> bool:
        """Wait for a real allocation before pinning the card to the corner."""
        if self._placed:
            return False
        if self.get_allocated_width() < 50 or self.get_allocated_height() < 30:
            return True  # not laid out yet, try again on the next tick
        self._corner()
        return False

    def _corner(self) -> bool:
        screen = self.get_screen()
        if screen is None:
            return False
        monitor = screen.get_primary_monitor()
        geo = screen.get_monitor_geometry(monitor)
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        if w < 50 or h < 30:
            w, h = WIDTH + 28, 118
        # 28 px off the right edge, clear of the COSMIC panel at the bottom.
        self.move(geo.x + geo.width - w - 28, geo.y + geo.height - h - 72)
        self._placed = True
        return False

    def _reset_position(self) -> None:
        self._store_clear("x")
        self._store_clear("y")
        self._corner()
        self._save_state()

    # ------------------------------------------------------------- collapse
    #
    # There is no WM on an override-redirect card, so `iconify()` would make it
    # vanish with no taskbar entry to get it back. Collapsing to the header bar
    # is the honest version of "minimize", and it keeps the bottom edge planted.
    def _toggle_collapse(self) -> None:
        pos = self.get_position()
        bottom = pos[1] + self.get_allocated_height()
        self._collapsed = not self._collapsed
        self._apply_collapsed()
        self._save_state()
        GLib.timeout_add(50, self._settle_bottom, bottom)

    def _settle_bottom(self, bottom: int) -> bool:
        x, _y = self.get_position()
        h = self.get_allocated_height()
        self.move(x, bottom - h)
        self._save_state()
        return False

    def _apply_collapsed(self) -> None:
        if self._applied_collapsed == self._collapsed:
            return
        self._applied_collapsed = self._collapsed
        show = not self._collapsed
        self.profile_lbl.set_visible(show)
        self.actions_row.set_visible(show)
        self.status_lbl.set_visible(show)
        self.brand.set_visible(show)
        self.chip.set_visible(show)
        self.close_btn.set_visible(show)
        self.min_btn.set_visible(show)
        ctx = self.root.get_style_context()
        if self._collapsed:
            ctx.add_class("dotmode")
        else:
            ctx.remove_class("dotmode")
        self.dot.set_tooltip_text("Expand oc-vpn" if self._collapsed else "")
        self.min_btn.set_label("\u25b4" if self._collapsed else "\u2013")
        self.min_btn.set_tooltip_text("Expand" if self._collapsed else "Collapse to a dot")
        self.root.set_size_request(-1 if self._collapsed else WIDTH, -1)

    # -------------------------------------------------------------- handlers
    def _over_control(self, x: int, y: int) -> bool:
        """True when the press landed on a button we must not steal."""
        for widget in (self.close_btn, self.min_btn, self.power_btn, self.newip_btn):
            if not widget.get_visible() or not widget.get_mapped():
                continue
            res = widget.translate_coordinates(self, 0, 0)
            wx, wy = (res[1], res[2]) if len(res) == 3 else (res[0], res[1])
            if wx is None:
                continue
            if (
                wx <= x <= wx + widget.get_allocated_width()
                and wy <= y <= wy + widget.get_allocated_height()
            ):
                return True
        return False

    def _on_press(self, _w, event) -> bool:
        if event.button == 3:
            self._refresh_menu()
            self.menu.popup_at_pointer(event)
            return True
        if event.button != 1 or self._over_control(event.x, event.y):
            return False
        pos = self.get_position()
        self._drag = (event.x_root, event.y_root, pos[0], pos[1])
        self._dragged = False
        return True

    def _on_motion(self, _w, event) -> bool:
        if not self._drag:
            return False
        ox, oy, wx, wy = self._drag
        dx = int(event.x_root - ox)
        dy = int(event.y_root - oy)
        if not self._dragged and abs(dx) + abs(dy) < 3:
            return True
        self._dragged = True
        self.move(wx + dx, wy + dy)
        return True

    def _on_release(self, _w, _event) -> bool:
        if not self._drag:
            return False
        self._drag = None
        if self._dragged:
            self._dragged = False
            self._save_state()
        elif self._collapsed:
            # the collapsed card is a single dot: a plain click (not a drag)
            # expands it, since the header buttons are hidden
            self._toggle_collapse()
        return True

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self._quit()
            return True
        return False

    def _on_power(self) -> None:
        if self._busy:
            return
        st = self._status
        if st.external:
            self._on_adopt()
            return
        if st.connected:
            self._work(self._do_down, st.name or st.iface)
            return
        target = self._target_profile()
        if not target:
            self._note("no VPN profile to connect", err=True)
            return
        if not nm.has_login(target):
            if not self._save_login(target):
                return
        self._work(self._do_up, target)

    def _on_new_ip(self) -> None:
        if self._busy:
            return
        names = nm.profile_names()
        if not names:
            self._note("no VPN profile to connect", err=True)
            return
        if self._status.external:
            self._note("manual openvpn running \u2014 press \u23fb to adopt it", err=True)
            return
        if not all(nm.has_login(n) for n in names):
            if not self._save_login(self._target_profile()):
                return
        self._work(self._do_rotate, nm.rotate_candidates(names, self._status.name or "", self._good))

    def _on_pick(self, name: str) -> None:
        if self._busy or name == self._status.name:
            return
        if not nm.has_login(name) and not self._save_login(name):
            return
        self._work(self._do_rotate, [name])

    def _on_adopt(self) -> None:
        self._work(self._do_adopt)

    def _on_dashboard(self) -> None:
        import subprocess
        try:
            subprocess.Popen(["oc-vpn", "--dashboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            self._note(str(exc), err=True)

    def _target_profile(self) -> str:
        names = nm.profile_names()
        if not names:
            return ""
        if self.preferred in names:
            return self.preferred
        return names[0]

    # ------------------------------------------------------------- credentials
    def _save_login(self, name: str) -> bool:
        names = nm.profile_names()
        pair = creds.prompt(names, CSS)
        if not pair:
            return False
        user, password = pair
        res = creds.save_login(names, user, password)
        self._note(res.summary(), err=not res.ok)
        return res.ok

    def _on_save_login(self) -> None:
        name = self._status.name or self._target_profile()
        if self._save_login(name):
            self._poll()

    # ------------------------------------------------------------- async work
    def _work(self, fn, *args) -> None:
        if self._busy:
            return
        self._busy = True
        self._msg, self._msg_err = "", False
        self._render()

        def runner():
            try:
                fn(*args)
            except Exception as exc:  # a broken nmcli must not kill the card
                self._msg, self._msg_err = f"{exc}", True
            GLib.idle_add(self._done_work)
            return False

        threading.Thread(target=runner, daemon=True).start()

    def _done_work(self) -> bool:
        self._busy = False
        self._ip_due = 0.0
        self._save_state()
        self._poll(force_ip=True)
        return False

    def _do_up(self, name: str) -> None:
        self._msg = f"connecting {name}\u2026"
        ok, msg = nm.up(name)
        if ok:
            self.preferred = name
            self._remember(name)
        self._msg, self._msg_err = msg, not ok
        self._log(f"up {name}: ok={ok} {msg}")

    def _do_down(self, name: str) -> None:
        self._msg = "disconnecting\u2026"
        ok, msg = nm.down(name) if name else (True, "already down")
        self._msg, self._msg_err = msg, not ok
        self._log(f"down {name}: ok={ok} {msg}")

    def _do_rotate(self, candidates: list[str]) -> None:
        cur = self._status.name
        if not candidates:
            self._msg, self._msg_err = "no other server to switch to", True
            return
        self._msg = f"switching to {candidates[0]}\u2026"
        res = nm.rotate(candidates, cur, attempts=min(3, len(candidates)))
        if res.ok:
            self.preferred = res.name
            self._remember(res.name)
        self._msg, self._msg_err = res.message, not res.ok
        self._log(
            f"rotate {cur} -> {res.name}: ok={res.ok} {res.message}"
            + (f" tried={res.tried}" if res.tried else "")
        )

    def _do_adopt(self) -> None:
        self._msg = "stopping manual openvpn\u2026"
        ok, msg = nm.kill_external()
        if not ok:
            self._msg, self._msg_err = f"adopt failed: {msg}", True
            return
        time.sleep(1.0)
        name = self._target_profile()
        ok, msg = nm.up(name) if name else (False, "no profile")
        if ok:
            self._remember(name)
        self._msg, self._msg_err = msg, not ok
        self._log(f"adopt -> {name}: ok={ok} {msg}")

    # ------------------------------------------------------------------ poll
    def _poll(self, force_ip: bool = False):
        if self._pending:
            return True
        self._pending = True

        def work():
            try:
                st = nm.status()
            except Exception as exc:
                self._log(f"status error: {exc}")
                st = nm.Status()
            want_ip = force_ip or (time.monotonic() >= self._ip_due)
            if want_ip and (st.connected or st.external):
                st.ip = nm.public_ip(4)
                self._ip_due = time.monotonic() + 20
            GLib.idle_add(self._apply, st, want_ip)
            return False

        threading.Thread(target=work, daemon=True).start()
        return True

    def _apply(self, st: nm.Status, want_ip: bool) -> bool:
        self._pending = False
        if self._quitting:
            return False
        if want_ip and not (st.connected or st.external):
            st.ip = ""
        elif not want_ip:
            st.ip = self._status.ip
        self._status = st
        self._render()
        return False

    def _tick(self):
        return not self._quitting

    # ---------------------------------------------------------------- render
    def _note(self, text: str, err: bool = False) -> None:
        self._msg, self._msg_err = text, err
        self._render()

    def _render(self) -> None:
        if self._quitting:
            return
        st = self._status
        chip_ctx = self.chip.get_style_context()
        dot_ctx = self.dot.get_style_context()
        root_ctx = self.root.get_style_context()
        for ctx in (chip_ctx, dot_ctx, root_ctx):
            for cls in ("off", "warn", "err"):
                ctx.remove_class(cls)
        ip_ctx = self.ip_lbl.get_style_context()
        ip_ctx.remove_class("off")
        pwr_ctx = self.power_btn.get_style_context()
        pwr_ctx.remove_class("off")
        st_ctx = self.status_lbl.get_style_context()
        st_ctx.remove_class("err")

        if self._busy:
            chip, cls = "WORKING", "warn"
        elif st.connected:
            chip, cls = "ON", ""
        elif st.external:
            chip, cls = "EXTERNAL", "warn"
        else:
            chip, cls = "OFF", "off"
        if self._msg_err and not self._busy:
            cls = "err"
        self.chip.set_text(chip)
        if cls:
            chip_ctx.add_class(cls)
            dot_ctx.add_class(cls)
            if cls in ("warn", "err"):
                root_ctx.add_class(cls)

        self.profile_lbl.set_text(st.label if not self._busy else (st.name or "working\u2026"))
        if st.connected or st.external:
            self.ip_lbl.set_text(st.ip or "\u2026")
        else:
            self.ip_lbl.set_text("\u2014")
            ip_ctx.add_class("off")

        self.power_btn.set_label("\u23fb" if st.connected else "\u23fb")
        if not st.connected and not st.external:
            pwr_ctx.add_class("off")
        self.power_btn.set_sensitive(not self._busy)
        self.newip_btn.set_sensitive(not self._busy and st.count > 1)

        if self._msg:
            text = self._msg
            if self._msg_err:
                st_ctx.add_class("err")
        try:
            from . import providers
            _prov = len(providers.installed_providers())
        except Exception:
            _prov = 0
        if st.external:
            text = f"manual {st.iface} \u00b7 press \u23fb to adopt \u00b7 {_prov} providers"
        elif st.connected:
            text = f"{st.iface or 'tunnel'} \u00b7 {st.count} servers \u00b7 {_prov} providers"
        elif not st.has_login:
            text = f"{st.count} servers \u00b7 no login saved \u00b7 {_prov} providers"
        else:
            text = f"{st.count} servers \u00b7 ready \u00b7 {_prov} providers"
        self.status_lbl.set_text(text)
        self.status_lbl.set_tooltip_text(text)
        self._apply_collapsed()

    # ---------------------------------------------------------------- state
    def _state_path(self) -> str:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "ocvpn", "state.json")

    def _store_clear(self, key: str) -> None:
        self.store.pop(key, None)

    def _remember(self, name: str) -> None:
        """MRU of servers that actually completed a handshake (saved on the main
        thread, from _done_work -- GTK must not be touched from a worker)."""
        if not name:
            return
        self._good = [g for g in self._good if g != name]
        self._good.insert(0, name)
        del self._good[8:]

    def _save_state(self) -> None:
        import json

        if self.no_save:
            return
        try:
            x, y = self.get_position()
        except Exception:
            x = y = None
        data = {
            "x": x,
            "y": y,
            "profile": self.preferred or self._status.name,
            "collapsed": self._collapsed,
            "good": self._good[:8],
        }
        try:
            path = self._state_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            pass

    def _quit(self) -> None:
        if self._quitting:
            return
        self._save_state()
        self._quitting = True
        Gtk.main_quit()

    def _on_delete(self, *_a) -> bool:
        self._quit()
        return True

    # ------------------------------------------------------------- utilities
    def _log(self, msg: str) -> None:
        if not self._log_file:
            return
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._log_file)), exist_ok=True)
            with open(self._log_file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

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
