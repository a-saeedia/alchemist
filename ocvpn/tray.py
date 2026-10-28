"""Alchemist: system-tray VPN platform.

A sleek indicator that lives in the panel. Left-click opens the dashboard;
right-click gives quick actions. Runs quietly in the tray until quit.
"""

from __future__ import annotations

import os
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import nm, providers  # noqa: E402


class AlchemistTray:
    def __init__(self):
        self._status = nm.Status()
        self.icon = Gtk.StatusIcon()
        try:
            self.icon.set_from_icon_name("network-vpn")
        except Exception:
            pass
        self.icon.set_tooltip_text("Alchemist — VPN")
        self.icon.set_visible(True)
        self.icon.connect("popup-menu", self._on_popup)
        self.icon.connect("activate", self._on_activate)

        self.menu = Gtk.Menu()
        self._build_menu()
        self.menu.show_all()

        self._poll()
        GLib.timeout_add(5000, self._tick)

    def _build_menu(self):
        # clear
        for c in self.menu.get_children():
            self.menu.remove(c)

        title = Gtk.MenuItem(label="Alchemist VPN")
        title.set_sensitive(False)
        self.menu.append(title)
        self.menu.append(Gtk.SeparatorMenuItem())

        st = self._status
        status_txt = "Connected" if st.connected else ("External" if st.external else "Disconnected")
        si = Gtk.MenuItem(label=f"Status: {status_txt}")
        si.set_sensitive(False)
        self.menu.append(si)
        if st.ip:
            ipi = Gtk.MenuItem(label=f"IP: {st.ip}")
            ipi.set_sensitive(False)
            self.menu.append(ipi)

        self.menu.append(Gtk.SeparatorMenuItem())

        ci = Gtk.MenuItem(label="Connect")
        ci.connect("activate", lambda *_: self._connect())
        self.menu.append(ci)
        di = Gtk.MenuItem(label="Disconnect")
        di.connect("activate", lambda *_: self._disconnect())
        self.menu.append(di)
        ri = Gtk.MenuItem(label="New IP")
        ri.connect("activate", lambda *_: self._rotate())
        self.menu.append(ri)

        self.menu.append(Gtk.SeparatorMenuItem())

        dash = Gtk.MenuItem(label="Open Dashboard")
        dash.connect("activate", lambda *_: self._open_dashboard())
        self.menu.append(dash)

        # providers submenu
        prov_menu = Gtk.Menu()
        pitem = Gtk.MenuItem(label="Providers")
        pitem.set_submenu(prov_menu)
        for p in providers.installed_providers(free_only=True):
            mi = Gtk.MenuItem(label=p.name)
            mi.connect("activate", lambda _w, pid=p.id: providers.launch(pid))
            prov_menu.append(mi)
        prov_menu.show_all()
        self.menu.append(pitem)

        self.menu.append(Gtk.SeparatorMenuItem())
        qi = Gtk.MenuItem(label="Quit")
        qi.connect("activate", lambda *_: Gtk.main_quit())
        self.menu.append(qi)
        self.menu.show_all()

    def _on_popup(self, icon, button, time):
        self._poll_sync()
        self._build_menu()
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

    def _on_activate(self, icon):
        self._open_dashboard()

    def _open_dashboard(self):
        try:
            subprocess.Popen(["oc-vpn", "--dashboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _connect(self):
        names = nm.profile_names()
        if not names:
            return
        target = names[0]
        if not nm.has_login(target):
            return
        threading.Thread(target=lambda: nm.up(target), daemon=True).start()

    def _disconnect(self):
        st = nm.status()
        if st.connected:
            threading.Thread(target=lambda: nm.down(st.name), daemon=True).start()

    def _rotate(self):
        names = nm.profile_names()
        if not names:
            return
        st = nm.status()
        cands = nm.rotate_candidates(names, st.name or "", [])
        def worker():
            nm.rotate(cands, st.name or "")
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        def work():
            try:
                st = nm.status()
                if st.connected or st.external:
                    st.ip = nm.public_ip(4)
            except Exception:
                st = nm.Status()
            GLib.idle_add(self._apply, st)
            return False
        threading.Thread(target=work, daemon=True).start()
        return True

    def _poll_sync(self):
        try:
            st = nm.status()
            if st.connected or st.external:
                st.ip = nm.public_ip(4)
            self._status = st
        except Exception:
            pass

    def _apply(self, st):
        self._status = st
        if st.connected:
            self.icon.set_tooltip_text(f"Alchemist — Connected ({st.ip})")
        elif st.external:
            self.icon.set_tooltip_text(f"Alchemist — External ({st.ip})")
        else:
            self.icon.set_tooltip_text("Alchemist — Disconnected")
        return False

    def _tick(self):
        self._poll()
        return True


def run():
    AlchemistTray()
    Gtk.main()


if __name__ == "__main__":
    run()
