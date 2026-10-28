"""Alchemist: system-tray VPN platform (Ayatana AppIndicator)."""

from __future__ import annotations

import os
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk  # noqa: E402

from . import nm, providers  # noqa: E402


class AlchemistTray:
    def __init__(self):
        self._status = nm.Status()
        self.ind = AyatanaAppIndicator3.Indicator.new(
            "alchemist", "network-vpn",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.ind.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.ind.set_title("Alchemist VPN")
        self.menu = Gtk.Menu()
        self._build_menu()
        self.ind.set_menu(self.menu)
        self._poll()
        GLib.timeout_add(5000, self._tick)

    def _build_menu(self):
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

        for label, cb in (("Connect", self._connect), ("Disconnect", self._disconnect), ("New IP", self._rotate)):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda *_ , f=cb: f())
            self.menu.append(mi)

        self.menu.append(Gtk.SeparatorMenuItem())
        dash = Gtk.MenuItem(label="Open Dashboard")
        dash.connect("activate", lambda *_: self._open_dashboard())
        self.menu.append(dash)

        prov_menu = Gtk.Menu()
        pitem = Gtk.MenuItem(label="Providers")
        pitem.set_submenu(prov_menu)
        for p in providers.installed_providers(free_only=True):
            mi = Gtk.MenuItem(label=p.name)
            mi.connect("activate", lambda _w, pid=p.id: providers.launch(pid))
            prov_menu.append(mi)
        prov_menu.show_all()
        self.menu.append(pitem)

        # configs submenu
        cfg_menu = Gtk.Menu()
        citem = Gtk.MenuItem(label="Configs")
        citem.set_submenu(cfg_menu)
        configs = providers.discover_ovpn_configs()
        if not configs:
            mi = Gtk.MenuItem(label="(no .ovpn files found)")
            mi.set_sensitive(False)
            cfg_menu.append(mi)
        else:
            for path in configs:
                name = os.path.basename(path)
                mi = Gtk.MenuItem(label=name)
                mi.connect("activate", lambda _w, p=path: self._connect_config(p))
                cfg_menu.append(mi)
        cfg_menu.show_all()
        self.menu.append(citem)

        self.menu.append(Gtk.SeparatorMenuItem())
        qi = Gtk.MenuItem(label="Quit")
        qi.connect("activate", lambda *_: Gtk.main_quit())
        self.menu.append(qi)
        self.menu.show_all()

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
        threading.Thread(target=lambda: nm.rotate(cands, st.name or ""), daemon=True).start()

    def _connect_config(self, path: str):
        import shutil
        # ensure cred file exists for engine
        cred = os.path.expanduser("~/cred.txt")
        src = os.path.expanduser("~/.ovpn_creds.txt")
        if os.path.exists(src) and not os.path.exists(cred):
            try:
                shutil.copyfile(src, cred)
            except OSError:
                pass
        def worker():
            subprocess.run(["pkexec", "/usr/local/bin/ovpn-engine", "start", path],
                           capture_output=True, text=True, timeout=60)
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

    def _apply(self, st):
        self._status = st
        self._build_menu()
        if st.connected:
            self.ind.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        else:
            self.ind.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        return False

    def _tick(self):
        self._poll()
        return True


def run():
    AlchemistTray()
    Gtk.main()


if __name__ == "__main__":
    run()
