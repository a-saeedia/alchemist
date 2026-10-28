"""One-time credential capture for every VPN profile.

OpenVPN profiles here authenticate with `auth-user-pass` (username + password),
so each one needs the same pair. NetworkManager stores those secrets itself
(0600, root-owned keyfile) as soon as we set `password-flags=0`, which is what
lets `nmcli connection up` succeed with zero prompts and zero sudo later.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from . import nm


@dataclass
class Result:
    ok: bool
    saved: list[str]
    failed: dict[str, str]

    def summary(self) -> str:
        if self.ok:
            return f"saved login for {len(self.saved)} profile(s)"
        if self.failed:
            first = next(iter(self.failed.items()))
            return f"{len(self.saved)} saved, {len(self.failed)} failed ({first[0]}: {first[1]})"
        return "nothing saved"


def save_login(
    names: list[str] | None, username: str, password: str
) -> Result:
    """Write username+password into every named profile via nmcli.

    `+vpn.data` merges the keys instead of replacing the whole dictionary, so
    remote/cipher/ta settings survive untouched.
    """
    names = names if names is not None else nm.profile_names()
    if not shutil.which(nm.NMCLI):
        return Result(False, [], {"*": "nmcli not found"})
    if not names:
        return Result(False, [], {"*": "no VPN profiles"})

    esc_u = nm.quote_dict_value(username)
    esc_p = nm.quote_dict_value(password)
    saved: list[str] = []
    failed: dict[str, str] = {}

    for name in names:
        rc, _, err = nm._run(
            ["connection", "modify", name, "+vpn.data",
             f"username={esc_u},password-flags=0"],
            timeout=30,
        )
        if rc != 0:
            failed[name] = (err.strip().splitlines() or [f"exit {rc}"])[-1]
            continue
        rc, _, err = nm._run(
            ["connection", "modify", name, "vpn.secrets", f"password={esc_p}"],
            timeout=30,
        )
        if rc != 0:
            failed[name] = (err.strip().splitlines() or [f"exit {rc}"])[-1]
            continue
        if not nm.has_login(name):
            failed[name] = "NetworkManager did not keep the secret"
            continue
        saved.append(name)

    return Result(bool(saved) and not failed, saved, failed)


def wifi_username(names: list[str] | None = None) -> str:
    """Reuse the login already baked into the profiles, so the dialog prefills."""
    for name in (names or nm.profile_names()):
        user = nm.vpn_data(name).get("username", "")
        if user:
            return user
    return ""


# ------------------------------------------------------------------- dialogs
def _gtk():
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    return Gtk


def prompt_gtk(
    names: list[str] | None = None,
    user: str = "",
    css: str = "",
    widget: bool = False,
) -> tuple[str, str] | None:
    """Ask for the account once. `widget=True` keeps the dialog attached to the
    floating card so it appears on the same workspace and never behind it."""
    Gtk = _gtk()

    if css:
        from gi.repository import Gdk

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
            )

    dlg = Gtk.Dialog(title="oc-vpn · save login")
    dlg.set_modal(True)
    dlg.set_resizable(False)
    dlg.set_keep_above(True)
    dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
    dlg.add_button("Save", Gtk.ResponseType.OK)
    dlg.set_default_response(Gtk.ResponseType.OK)

    box = dlg.get_content_area()
    box.set_spacing(6)
    box.set_border_width(14)

    head = Gtk.Label(label="OpenVPN account")
    head.set_xalign(0.0)
    head.get_style_context().add_class("vpn-head")
    box.pack_start(head, False, False, 0)

    sub = Gtk.Label(
        label="Stored by NetworkManager for every profile.\n"
        "Never written to a plaintext file."
    )
    sub.set_xalign(0.0)
    sub.get_style_context().add_class("vpn-sub")
    box.pack_start(sub, False, False, 0)

    grid = Gtk.Grid(column_spacing=8, row_spacing=6)
    grid.set_margin_top(6)
    user_lbl = Gtk.Label(label="user")
    user_lbl.set_xalign(1.0)
    user_lbl.get_style_context().add_class("vpn-sub")
    pass_lbl = Gtk.Label(label="pass")
    pass_lbl.set_xalign(1.0)
    pass_lbl.get_style_context().add_class("vpn-sub")
    user_entry = Gtk.Entry()
    user_entry.set_text(user)
    user_entry.set_width_chars(24)
    user_entry.set_activates_default(True)
    pass_entry = Gtk.Entry()
    pass_entry.set_visibility(False)
    pass_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    pass_entry.set_activates_default(True)
    reveal = Gtk.CheckButton(label="show")
    reveal.connect(
        "toggled", lambda b: pass_entry.set_visibility(b.get_active())
    )
    grid.attach(user_lbl, 0, 0, 1, 1)
    grid.attach(user_entry, 1, 0, 1, 1)
    grid.attach(pass_lbl, 0, 1, 1, 1)
    grid.attach(pass_entry, 1, 1, 1, 1)
    grid.attach(reveal, 2, 1, 1, 1)
    box.pack_start(grid, False, False, 0)

    if names:
        scope = Gtk.Label(
            label=f"applies to {len(names)} profile(s): "
            + ", ".join(names[:3])
            + ("…" if len(names) > 3 else "")
        )
        scope.set_xalign(0.0)
        scope.set_line_wrap(True)
        scope.set_max_width_chars(46)
        scope.get_style_context().add_class("vpn-sub")
        box.pack_start(scope, False, False, 0)

    dlg.show_all()
    if widget:
        dlg.set_transient_for(None)
    if not user:
        user_entry.grab_focus()
    else:
        pass_entry.grab_focus()

    answer = dlg.run()
    username = user_entry.get_text().strip()
    password = pass_entry.get_text()
    dlg.destroy()
    if answer != Gtk.ResponseType.OK:
        return None
    if not username or not password:
        return None
    return username, password


def prompt_terminal(names: list[str] | None = None) -> tuple[str, str] | None:
    import getpass

    user = wifi_username(names)
    try:
        username = input(f"user [{user}]: ").strip() or user
        password = getpass.getpass("pass: ")
    except (EOFError, KeyboardInterrupt):
        return None
    if not username or not password:
        return None
    return username, password


def prompt(
    names: list[str] | None = None, css: str = "", widget: bool = False
) -> tuple[str, str] | None:
    """GUI dialog when a display exists, terminal prompt otherwise."""
    import os

    if os.environ.get("DISPLAY") and not os.environ.get("OCVPN_TERMINAL"):
        try:
            return prompt_gtk(names, wifi_username(names), css, widget)
        except ImportError:
            pass
    return prompt_terminal(names)


def activate_without_prompt_check(name: str) -> tuple[bool, str]:
    """Small preflight used by the CLI: is this profile ready to come up?"""
    if not name:
        return False, "no profile"
    if not nm.has_login(name):
        return False, "no saved login for this profile"
    return True, "ok"
