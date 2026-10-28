"""oc-vpn — whole-device OpenVPN switch with a corner button.

    oc-vpn                 floating card, bottom-right, remembers where you put it
    oc-vpn --status         one-line tunnel state (exit code 0 when up)
    oc-vpn --save-login     store the account in every profile, once
    oc-vpn --up NAME        connect a specific NetworkManager profile
    oc-vpn --rotate         disconnect, connect the next profile, report new IP
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import creds, nm, providers


def _state_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ocvpn", "state.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(patch: dict) -> None:
    data = _load_state()
    data.update(patch)
    try:
        os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def _remember_good(name: str, limit: int = 8) -> None:
    """Keep a short MRU list of profiles that actually completed a handshake."""
    if not name:
        return
    good = [g for g in _load_state().get("good", []) if g != name]
    good.insert(0, name)
    _save_state({"good": good[:limit]})


def _print_status(st: nm.Status, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(st, default=lambda o: o.__dict__))
        return
    if st.connected:
        print(f"up    {st.name}  iface={st.iface or '-'}  {st.ip or '(ip unknown)'}")
    elif st.external:
        print(f"up    {st.iface} (manual openvpn, not managed)  {st.ip or ''}".rstrip())
    else:
        print("down")


# ---------------------------------------------------------------- commands
def cmd_up(name: str) -> int:
    names = nm.profile_names()
    if name not in names:
        print(f"no such profile: {name}\nprofiles: {', '.join(names)}", file=sys.stderr)
        return 2
    if not nm.has_login(name):
        pair = creds.prompt(names)
        if not pair:
            print("no saved login and none provided", file=sys.stderr)
            return 2
        res = creds.save_login(names, *pair)
        if not res.ok:
            print(res.summary(), file=sys.stderr)
            return 1
    ok, msg = nm.up(name)
    if ok:
        _remember_good(name)
    print(f"{name}: {msg}")
    return 0 if ok else 1


def cmd_down() -> int:
    st = nm.status()
    if st.external:
        print(f"{st.iface} is a manual openvpn; use --adopt", file=sys.stderr)
        return 2
    if not st.connected:
        print("already down")
        return 0
    ok, msg = nm.down(st.name or st.iface)
    print(msg)
    return 0 if ok else 1


def cmd_rotate() -> int:
    names = nm.profile_names()
    if not names:
        print("no VPN profiles", file=sys.stderr)
        return 2
    st = nm.status()
    if st.external:
        print(f"manual openvpn on {st.iface}; use --adopt", file=sys.stderr)
        return 2
    if not all(nm.has_login(n) for n in names):
        missing = [n for n in names if not nm.has_login(n)]
        pair = creds.prompt(missing)
        if not pair:
            print("no saved login for every profile", file=sys.stderr)
            return 2
        creds.save_login(missing, *pair)
    good = _load_state().get("good", [])
    cands = nm.rotate_candidates(names, st.name, good)
    res = nm.rotate(cands, st.name)
    if not res.ok:
        print(res.message, file=sys.stderr)
        return 1
    _remember_good(res.name)
    ip = nm.public_ip()
    print(f"{res.name}: {res.message}{'  ' + ip if ip else ''}")
    return 0


def cmd_status(as_json: bool) -> int:
    st = nm.status()
    if st.connected or st.external:
        st.ip = nm.public_ip(4)
    _print_status(st, as_json)
    return 0 if (st.connected or st.external) else 1


def cmd_list() -> int:
    names = nm.profile_names()
    if not names:
        print("no VPN profiles", file=sys.stderr)
        return 1
    st = nm.status()
    for name in names:
        marks = []
        if name == st.name:
            marks.append("active")
        marks.append("login" if nm.has_login(name) else "no-login")
        marks.append("tls-auth" if nm.has_tls_auth(name) else "no-tls-auth")
        print(f"{name:28s} {', '.join(marks)}")
    return 0


def cmd_save_login() -> int:
    names = nm.profile_names()
    if not names:
        print("no VPN profiles", file=sys.stderr)
        return 2
    pair = creds.prompt(names)
    if not pair:
        print("cancelled", file=sys.stderr)
        return 2
    res = creds.save_login(names, *pair)
    print(res.summary())
    for name, err in res.failed.items():
        print(f"  {name}: {err}", file=sys.stderr)
    return 0 if res.ok else 1


def cmd_adopt() -> int:
    ok, msg = nm.kill_external()
    print(msg)
    if not ok:
        return 1
    name = nm.profile_names()[0] if nm.profile_names() else ""
    if name:
        ok, msg = nm.up(name)
        print(f"{name}: {msg}")
    return 0 if ok else 1


def cmd_providers() -> int:
    for p in providers.PROVIDERS:
        state = "installed" if providers.is_installed(p) else "missing"
        free = "free" if p.free else "paid"
        print(f"{p.id:18s} {state:9s} {free:4s}  {p.name}  -- {p.description}")
    s = providers.summary()
    print(f"\n{ s['installed']}/{s['total']} installed ({s['free_installed']} free)")
    return 0


def cmd_launch(pid: str) -> int:
    ok, msg = providers.launch(pid)
    print(msg)
    return 0 if ok else 1


def cmd_provider_status(pid: str) -> int:
    ok, msg = providers.status(pid)
    print(f"{pid}: {'up' if ok else 'down'} {msg}".rstrip())
    return 0 if ok else 1


def cmd_gui(
    profile: str, shoot: str | None, log_file: str | None, collapsed: bool = False
) -> int:
    from .ui import VpnWindow

    store = _load_state()
    if collapsed:
        store["collapsed"] = True
    win = VpnWindow(store=store, profile=profile, log_file=log_file)
    if shoot:
        win.no_save = True
    win.show_all()
    win.present()
    if shoot:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib

        def snap():
            ok = win.shoot(shoot)
            print(f"{'wrote' if ok else 'failed'}: {shoot}")
            from gi.repository import Gtk

            Gtk.main_quit()
            return False

        GLib.timeout_add(int(os.environ.get("OCVPN_SHOOT_DELAY", "2200")), snap)
    from gi.repository import Gtk

    Gtk.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="oc-vpn",
        description="OpenVPN on the whole device, with a corner button that changes the exit IP.",
    )
    p.add_argument("--status", action="store_true", help="print tunnel state")
    p.add_argument("--json", action="store_true", help="with --status: machine readable")
    p.add_argument("--list", action="store_true", help="list profiles and login state")
    p.add_argument("--up", metavar="NAME", help="connect this profile")
    p.add_argument("--down", action="store_true", help="disconnect")
    p.add_argument("--rotate", action="store_true", help="next server, same tunnel")
    p.add_argument("--save-login", action="store_true", help="store user/pass once")
    p.add_argument("--adopt", action="store_true", help="stop manual openvpn, take over")
    p.add_argument("--profile", default="", help="profile to preselect in the card")
    p.add_argument("--collapsed", action="store_true", help="start as the header bar only")
    p.add_argument("--shoot", metavar="PNG", help="render the card to a PNG and exit")
    p.add_argument("--log-file", metavar="PATH", help="append actions to PATH")
    p.add_argument("--providers", action="store_true", help="list known VPN providers and install state")
    p.add_argument("--launch", metavar="ID", help="launch a provider by id (see --providers)")
    p.add_argument("--provider-status", metavar="ID", help="query a provider status")
    p.add_argument("--dashboard", action="store_true", help="open the full VPN platform dashboard")
    p.add_argument("--tray", action="store_true", help="run as a system-tray indicator (Alchemist)")
    args = p.parse_args(argv)

    if args.status:
        return cmd_status(args.json)
    if args.list:
        return cmd_list()
    if args.up:
        return cmd_up(args.up)
    if args.down:
        return cmd_down()
    if args.rotate:
        return cmd_rotate()
    if args.save_login:
        return cmd_save_login()
    if args.adopt:
        return cmd_adopt()
    if args.providers:
        return cmd_providers()
    if args.launch:
        return cmd_launch(args.launch)
    if args.provider_status:
        return cmd_provider_status(args.provider_status)
    if args.dashboard:
        from .dashboard import run as run_dash
        run_dash(_load_state())
        return 0
    if args.tray:
        from .tray import run as run_tray
        run_tray()
        return 0
    return cmd_gui(args.profile, args.shoot, args.log_file, args.collapsed)


if __name__ == "__main__":
    raise SystemExit(main())
