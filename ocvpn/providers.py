"""Discovery and launch of the free VPN clients installed on this machine.

oc-vpn's own tunnel is OpenVPN/WireGuard through NetworkManager. Everything else
(Proton, Cloudflare WARP, Nym, Mullvad, Tor, ...) is a separate client that the
user may have installed for a different exit. This module is the catalogue the
card uses for its "Providers" menu and for the `--providers` / `--launch` CLI,
so the widget never has to know which binaries exist at import time.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    free: bool
    kind: str                 # "client" | "network" | "browser" | "proxy"
    description: str
    binary: str = ""          # primary executable to look up
    binaries: tuple = ()      # any of these counts as "installed"
    launch: tuple = ()        # command argv to start the GUI/CLI
    status: tuple = ()        # command argv to query status (best effort)
    install_hint: str = ""


PROVIDERS: list[Provider] = [
    Provider(
        "openvpn-nm", "OpenVPN (NetworkManager)", True, "network",
        "Whole-device tunnel through NetworkManager. Rotates exit IPs.",
        binary="nmcli", binaries=("nmcli",),
        launch=(), status=("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"),
        install_hint="sudo apt install network-manager-openvpn-gnome",
    ),
    Provider(
        "wireguard", "WireGuard", True, "network",
        "Fast modern kernel VPN. Managed as an NM connection or wg-quick.",
        binary="wg", binaries=("wg", "wg-quick"),
        launch=(), status=("wg", "show"),
        install_hint="sudo apt install wireguard-tools",
    ),
    Provider(
        "protonvpn", "Proton VPN", True, "client",
        "Free tier (3 countries). Official GTK client already installed.",
        binary="protonvpn-app", binaries=("protonvpn-app", "protonvpn", "protonvpn-cli"),
        launch=("protonvpn-app",), status=("protonvpn-cli", "status"),
        install_hint="sudo apt install proton-vpn-gtk-app",
    ),
    Provider(
        "cloudflare-warp", "Cloudflare WARP", True, "client",
        "Free. 1.1.1.1 + WARP. warp-cli + optional GUI.",
        binary="warp-cli", binaries=("warp-cli", "warp-svc"),
        launch=("warp-cli", "connect"), status=("warp-cli", "status"),
        install_hint="see https://pkg.cloudflareclient.com (apt repo)",
    ),
    Provider(
        "riseup", "Riseup VPN", True, "client",
        "Free, no account, activist-run. OpenVPN based.",
        binary="riseup-vpn", binaries=("riseup-vpn",),
        launch=("riseup-vpn",), status=(),
        install_hint="sudo apt install riseup-vpn",
    ),
    Provider(
        "nym", "NymVPN", True, "client",
        "Decentralized mixnet VPN with a free tier.",
        binary="nymvpn", binaries=("nymvpn",),
        launch=("flatpak", "run", "net.nymtech.NymVPN"),
        status=(),
        install_hint="flatpak install flathub net.nymtech.NymVPN",
    ),
    Provider(
        "eovpn", "eOVPN", True, "client",
        "OpenVPN configuration manager. Good for imported .ovpn files.",
        binary="eovpn", binaries=("eovpn",),
        launch=("flatpak", "run", "com.github.jkotra.eovpn"),
        status=(),
        install_hint="flatpak install flathub com.github.jkotra.eovpn",
    ),
    Provider(
        "trayscale", "Trayscale", True, "client",
        "GUI for Tailscale (free personal tier).",
        binary="trayscale", binaries=("trayscale",),
        launch=("flatpak", "run", "dev.deedles.Trayscale"),
        status=(),
        install_hint="flatpak install flathub dev.deedles.Trayscale",
    ),
    Provider(
        "outline", "Outline", True, "client",
        "Self-hosted Outline servers (Shadowsocks based).",
        binary="outline-manager", binaries=("outline-manager",),
        launch=("flatpak", "run", "org.getoutline.OutlineManager"),
        status=(),
        install_hint="flatpak install flathub org.getoutline.OutlineManager",
    ),
    Provider(
        "tor", "Tor", True, "proxy",
        "Anonymity network. SOCKS proxy on 9050.",
        binary="tor", binaries=("tor",),
        launch=("tor",), status=("pgrep", "-x", "tor"),
        install_hint="sudo apt install tor",
    ),
    Provider(
        "i2p", "I2P", True, "network",
        "Anonymous overlay network.",
        binary="i2pd", binaries=("i2pd", "i2p"),
        launch=("i2pd",), status=(),
        install_hint="sudo apt install i2pd",
    ),
    Provider(
        "mullvad-browser", "Mullvad Browser", True, "browser",
        "Privacy browser with Mullvad's VPN integration (paid VPN).",
        binary="mullvad-browser", binaries=("mullvad-browser",),
        launch=("flatpak", "run", "net.mullvad.MullvadBrowser"),
        status=(),
        install_hint="flatpak install flathub net.mullvad.MullvadBrowser",
    ),
]


def _installed_binaries(p: Provider) -> list[str]:
    found = []
    for b in (p.binaries or (p.binary,)):
        if b and shutil.which(b):
            found.append(b)
    # flatpak apps: detect via flatpak list
    return found


def is_installed(p: Provider) -> bool:
    if _installed_binaries(p):
        return True
    # flatpak launch entries
    if p.launch and p.launch[0] == "flatpak":
        try:
            out = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and len(p.launch) >= 3 and p.launch[2] in out.stdout:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def installed_providers(free_only: bool = False) -> list[Provider]:
    out = [p for p in PROVIDERS if is_installed(p)]
    if free_only:
        out = [p for p in out if p.free]
    return out


def catalog(free_only: bool = False) -> list[Provider]:
    out = list(PROVIDERS)
    if free_only:
        out = [p for p in out if p.free]
    return out


def get(provider_id: str) -> Provider | None:
    for p in PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def launch(provider_id: str) -> tuple[bool, str]:
    p = get(provider_id)
    if p is None:
        return False, f"unknown provider: {provider_id}"
    if not is_installed(p):
        return False, f"{p.name} is not installed ({p.install_hint})"
    if not p.launch:
        return False, f"{p.name} has no GUI launcher"
    try:
        subprocess.Popen(list(p.launch), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"launched {p.name}"
    except OSError as exc:
        return False, f"launch failed: {exc}"


def status(provider_id: str) -> tuple[bool, str]:
    p = get(provider_id)
    if p is None or not p.status:
        return False, ""
    try:
        out = subprocess.run(list(p.status), capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return out.returncode == 0, (text[0] if text else "")


def free_providers() -> list[Provider]:
    return [p for p in PROVIDERS if p.free]


def summary() -> dict:
    inst = installed_providers()
    return {
        "total": len(PROVIDERS),
        "installed": len(inst),
        "free_installed": sum(1 for p in inst if p.free),
        "names": [p.name for p in inst],
    }


import glob as _glob
import os as _os


def _config_dirs():
    home = _os.path.expanduser("~")
    return [
        _os.path.join(home, "Documents", "openvpn"),
        _os.path.join(home, "Documents", "ovpn", "vpnbook"),
        _os.path.join(home, "Documents", "ovpn"),
        _os.path.join(home, "Documents"),
        _os.path.join(home, "openvpn"),
    ]


def discover_ovpn_configs() -> list[str]:
    """All .ovpn files under the common config folders (deduped, sorted)."""
    found: set[str] = set()
    for d in _config_dirs():
        if not _os.path.isdir(d):
            continue
        for path in _glob.glob(_os.path.join(d, "**", "*.ovpn"), recursive=True):
            found.add(path)
    return sorted(found)
