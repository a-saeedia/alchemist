"""Full-window VPN platform dashboard.

A companion to the floating corner card: same backends, but a real window with
room for a provider grid, profile list and connection details. Launched with
`oc-vpn --dashboard` or from the card's right-click menu.
"""

from __future__ import annotations

import os
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import creds, nm, providers  # noqa: E402

CSS = """
#dash-root { background-color: #0b1220; color: #dbe7ee; }
.dash-title { font-size: 20px; font-weight: 700; color: #22d3ee; }
.dash-sub { font-size: 11px; color: #7d95a5; }
.card { background-color: rgba(255,255,255,0.03); border: 1px solid rgba(34,211,238,0.18);
        border-radius: 12px; padding: 12px; }
.card-title { font-size: 12px; font-weight: 700; color: #9fb3c1; letter-spacing: 1px; }
.status-on { color: #4ade80; font-weight: 700; }
.status-off { color: #94a3b8; }
.ip { font-family: monospace; font-size: 14px; color: #22d3ee; font-weight: 700; }
.provider-row { padding: 6px; border-bottom: 1px solid rgba(255,255,255,0.05); }
button.launch { background-color: rgba(34,211,238,0.15); color: #a5f3fc; }
"""


class DashboardWindow(Gtk.Window):
    def __init__(self, store=None):
        super().__init__(title="oc-vpn · VPN Platform")
        self.store = store or {}
        self.set_default_size(900, 620)
        self._busy = False
        self._status = nm.Status()
        self._show_paid = False

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_start(16)
        root.set_margin_end(16)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_name("dash-root")
        self.add(root)

        # header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t = Gtk.Label(label="VPN Platform")
        t.get_style_context().add_class("dash-title")
        t.set_xalign(0)
        hdr.pack_start(t, True, True, 0)
        sub = Gtk.Label(label="Free + paid providers, one place.")
        sub.get_style_context().add_class("dash-sub")
        sub.set_xalign(0)
        hdr.pack_start(sub, True, True, 0)
        root.pack_start(hdr, False, False, 0)

        # connection card
        conn = Gtk.Frame()
        conn.get_style_context().add_class("card")
        conn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        conn.add(conn_box)
        ct = Gtk.Label(label="CONNECTION")
        ct.get_style_context().add_class("card-title")
        ct.set_xalign(0)
        conn_box.pack_start(ct, False, False, 0)

        self.conn_status = Gtk.Label(label="disconnected")
        self.conn_status.set_xalign(0)
        conn_box.pack_start(self.conn_status, False, False, 0)

        self.conn_ip = Gtk.Label(label="—")
        self.conn_ip.get_style_context().add_class("ip")
        self.conn_ip.set_xalign(0)
        conn_box.pack_start(self.conn_ip, False, False, 0)

        self.conn_detail = Gtk.Label(label="")
        self.conn_detail.set_xalign(0)
        conn_box.pack_start(self.conn_detail, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_connect = Gtk.Button(label="Connect")
        self.btn_connect.connect("clicked", lambda *_: self._on_connect())
        self.btn_disconnect = Gtk.Button(label="Disconnect")
        self.btn_disconnect.connect("clicked", lambda *_: self._on_disconnect())
        self.btn_rotate = Gtk.Button(label="New IP")
        self.btn_rotate.connect("clicked", lambda *_: self._on_rotate())
        self.btn_save = Gtk.Button(label="Save login")
        self.btn_save.connect("clicked", lambda *_: self._on_save_login())
        for b in (self.btn_connect, self.btn_disconnect, self.btn_rotate, self.btn_save):
            actions.pack_start(b, False, False, 0)
        conn_box.pack_start(actions, False, False, 0)
        root.pack_start(conn, False, False, 0)

        # providers grid
        prov_opts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.chk_paid = Gtk.CheckButton(label="Show paid providers")
        self.chk_paid.connect("toggled", self._on_toggle_paid)
        prov_opts.pack_start(self.chk_paid, False, False, 0)
        root.pack_start(prov_opts, False, False, 0)
        prov_frame = Gtk.Frame()
        prov_frame.get_style_context().add_class("card")
        prov_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        prov_frame.add(prov_box)
        pt = Gtk.Label(label="PROVIDERS")
        pt.get_style_context().add_class("card-title")
        pt.set_xalign(0)
        prov_box.pack_start(pt, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.prov_list = Gtk.ListBox()
        scrolled.add(self.prov_list)
        prov_box.pack_start(scrolled, True, True, 0)
        root.pack_start(prov_frame, True, True, 0)

        # profiles list
        prof_frame = Gtk.Frame()
        prof_frame.get_style_context().add_class("card")
        prof_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        prof_frame.add(prof_box)
        pr = Gtk.Label(label="OPENVPN / WIREGUARD PROFILES")
        pr.get_style_context().add_class("card-title")
        pr.set_xalign(0)
        prof_box.pack_start(pr, False, False, 0)
        self.prof_list = Gtk.ListBox()
        prof_box.pack_start(self.prof_list, True, True, 0)
        root.pack_start(prof_frame, True, True, 0)

        self._refresh_providers()
        self._refresh_profiles()
        self._poll()

        self.connect("destroy", lambda *_: Gtk.main_quit())

    def _on_toggle_paid(self, btn):
        self._show_paid = btn.get_active()
        self._refresh_providers()

    def _refresh_providers(self):
        for c in self.prov_list.get_children():
            self.prov_list.remove(c)
        cat = providers.catalog(free_only=not self._show_paid)
        for p in cat:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(4)
            box.set_margin_end(4)
            box.set_margin_top(2)
            box.set_margin_bottom(2)
            name = Gtk.Label(label=p.name)
            name.set_xalign(0)
            box.pack_start(name, True, True, 0)
            free = Gtk.Label(label="free" if p.free else "paid")
            free.set_xalign(0)
            box.pack_start(free, False, False, 0)
            status = "installed" if providers.is_installed(p) else "missing"
            st = Gtk.Label(label=status)
            st.set_xalign(0)
            box.pack_start(st, False, False, 0)
            if providers.is_installed(p) and p.launch:
                btn = Gtk.Button(label="Launch")
                btn.get_style_context().add_class("launch")
                btn.connect("clicked", lambda _w, pid=p.id: self._launch(pid))
                box.pack_end(btn, False, False, 0)
            row.add(box)
            self.prov_list.add(row)
        self.prov_list.show_all()

    def _refresh_profiles(self):
        for c in self.prof_list.get_children():
            self.prof_list.remove(c)
        names = nm.profile_names()
        if not names:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label="(no profiles)"))
            self.prof_list.add(row)
        for name in names:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(4)
            box.set_margin_end(4)
            lbl = Gtk.Label(label=name)
            lbl.set_xalign(0)
            box.pack_start(lbl, True, True, 0)
            login = "login" if nm.has_login(name) else "no-login"
            ls = Gtk.Label(label=login)
            box.pack_start(ls, False, False, 0)
            btn = Gtk.Button(label="Connect")
            btn.connect("clicked", lambda _w, n=name: self._connect_profile(n))
            box.pack_end(btn, False, False, 0)
            row.add(box)
            self.prof_list.add(row)
        self.prof_list.show_all()

    def _launch(self, pid):
        ok, msg = providers.launch(pid)
        self.conn_detail.set_text(msg)

    def _connect_profile(self, name):
        def worker():
            ok, msg = nm.up(name)
            GLib.idle_add(self._after_action, f"{name}: {msg}", not ok)
        threading.Thread(target=worker, daemon=True).start()

    def _on_connect(self):
        names = nm.profile_names()
        if not names:
            self.conn_detail.set_text("no profiles")
            return
        target = names[0]
        if not nm.has_login(target):
            self.conn_detail.set_text("save login first")
            return
        self._connect_profile(target)

    def _on_disconnect(self):
        st = nm.status()
        if st.connected:
            def worker():
                ok, msg = nm.down(st.name)
                GLib.idle_add(self._after_action, msg, not ok)
            threading.Thread(target=worker, daemon=True).start()

    def _on_rotate(self):
        names = nm.profile_names()
        if not names:
            return
        st = nm.status()
        cands = nm.rotate_candidates(names, st.name or "", [])
        def worker():
            res = nm.rotate(cands, st.name or "")
            if res.ok:
                ip = nm.public_ip()
                GLib.idle_add(self._after_action, f"{res.name}  {ip}", False)
            else:
                GLib.idle_add(self._after_action, res.message, True)
        threading.Thread(target=worker, daemon=True).start()

    def _on_save_login(self):
        names = nm.profile_names()
        pair = creds.prompt(names)
        if not pair:
            return
        res = creds.save_login(names, *pair)
        self.conn_detail.set_text(res.summary())
        self._refresh_profiles()

    def _after_action(self, msg, err):
        self.conn_detail.set_text(msg)
        self._poll(force_ip=True)
        return False

    def _poll(self, force_ip=False):
        def work():
            try:
                st = nm.status()
            except Exception:
                st = nm.Status()
            if (st.connected or st.external) and (force_ip or not st.ip):
                st.ip = nm.public_ip(4)
            GLib.idle_add(self._apply, st)
            return False
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, st):
        self._status = st
        if st.connected:
            self.conn_status.set_markup(f'<span class="status-on">ON</span>  {st.name}')
        elif st.external:
            self.conn_status.set_markup(f'<span class="status-on">EXTERNAL</span>  {st.iface}')
        else:
            self.conn_status.set_markup('<span class="status-off">OFF</span>')
        self.conn_ip.set_text(st.ip or "—")
        self.conn_detail.set_text(f"{st.iface or '—'} · {st.count} profiles")
        return False


def run(store=None):
    w = DashboardWindow(store=store)
    w.show_all()
    Gtk.main()
