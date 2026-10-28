"""NetworkManager/OpenVPN backend for oc-vpn.

Everything here is plain `nmcli` — no root, no daemon of our own, no root
password. NetworkManager already owns the tunnel and writes VPN secrets into
its own 0600 root-only store, so the widget never touches a plaintext file.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field

NMCLI = shutil.which("nmcli") or "/usr/bin/nmcli"
VPN_TYPES = ("vpn", "wireguard")
TUN_RE = re.compile(r"^(tun|tap|wg)\d+$")


# --------------------------------------------------------------------- shell
def _split(line: str) -> list[str]:
    """Split one `nmcli -t` row on unescaped ':' and undo nmcli's escaping."""
    out: list[str] = []
    buf: list[str] = []
    esc = False
    for ch in line.rstrip("\n"):
        if esc:
            buf.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _run(args: list[str], timeout: float = 20) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            [NMCLI, *args], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return p.returncode, p.stdout, p.stderr


def quote_dict_value(value: str) -> str:
    """Escape a value for nmcli's `key=value,key=value` dictionary syntax."""
    return value.replace("\\", "\\\\").replace(",", "\\,")


# ------------------------------------------------------------------ profiles
@dataclass(frozen=True)
class Profile:
    name: str
    kind: str
    uuid: str = ""


def profiles() -> list[Profile]:
    """Every VPN connection NetworkManager knows about, in menu order."""
    rc, out, _ = _run(["-t", "-f", "NAME,TYPE,UUID", "connection", "show"])
    if rc != 0:
        return []
    found: list[Profile] = []
    for line in out.splitlines():
        parts = _split(line)
        if len(parts) < 3:
            continue
        name, kind, uuid = parts[0], parts[1], parts[2]
        if kind in VPN_TYPES and name:
            found.append(Profile(name, kind, uuid))
    return found


def profile_names() -> list[str]:
    return [p.name for p in profiles()]


def default_iface() -> str:
    """Interface holding the default route (tun0 while the VPN is up)."""
    try:
        p = subprocess.run(
            ["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"\bdev (\S+)", p.stdout)
    return m.group(1) if m else ""


@dataclass
class Status:
    connected: bool = False
    name: str = ""          # NetworkManager profile name
    iface: str = ""         # tun0 / wg0 ...
    external: bool = False  # a tunnel NetworkManager does not manage
    ip: str = ""            # public egress IP, filled in by refresh_ip()
    has_login: bool = False
    count: int = 0

    @property
    def label(self) -> str:
        if self.connected:
            return self.name or self.iface or "connected"
        if self.external:
            return f"{self.iface} (manual)"
        return "disconnected"


def status() -> Status:
    """One cheap snapshot: active VPN, default route, whether a login is stored."""
    st = Status(count=len(profiles()))
    rc, out, _ = _run(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    active = None
    if rc == 0:
        for line in out.splitlines():
            parts = _split(line)
            if len(parts) >= 3 and parts[1] in VPN_TYPES:
                active = parts
                break
    iface = default_iface()
    if active:
        st.connected = True
        st.name = active[0]
        # NetworkManager reports the *parent* device (wlp4s0) for a VPN; the
        # interesting one is whatever actually carries the default route.
        reported = active[2] if len(active) > 2 and active[2] != "--" else ""
        st.iface = iface if TUN_RE.match(iface) else (reported or iface)
        st.has_login = has_login(st.name)
    elif iface and TUN_RE.match(iface):
        # `openvpn --config x.ovpn` running by hand: tunnel is real, but it is
        # invisible to NetworkManager, so it cannot be rotated or restored.
        st.external = True
        st.iface = iface
    return st


def has_login(name: str) -> bool:
    """True when the profile stores a password (password-flags=0)."""
    if not name:
        return False
    rc, out, _ = _run(["-g", "vpn.data", "connection", "show", name])
    m = re.search(r"password-flags\s*=\s*(\d+)", out)
    return bool(m and m.group(1) == "0")


def vpn_data(name: str) -> dict[str, str]:
    """The profile's `vpn.data` dictionary (remote, cipher, username, ...)."""
    rc, out, _ = _run(["-t", "-g", "vpn.data", "connection", "show", name])
    if rc != 0:
        return {}
    data: dict[str, str] = {}
    for chunk in re.split(r"(?<!\\),", out.strip()):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        data[key.strip()] = value.strip().replace("\\:", ":")
    return data


def next_profile(names: list[str], current: str) -> str:
    """The profile after `current`, wrapping around. Pure, so it is testable."""
    if not names:
        return ""
    if current in names:
        return names[(names.index(current) + 1) % len(names)]
    return names[0]


def has_tls_auth(name: str) -> bool:
    """Profiles imported with the inline `tls-auth` key carry a `ta` entry.

    The duplicates in this machine's list were imported without it and can never
    complete a handshake, so rotation must not land on them.
    """
    return "ta" in vpn_data(name)


def rotate_candidates(
    names: list[str], current: str, good: list[str] | None = None
) -> list[str]:
    """Order to try when changing servers: round-robin past the current one.

    Three filters, in order:
      * never the server you are already on,
      * drop profiles that carry no `tls-auth` (they cannot handshake),
      * one candidate per remote host, so duplicates of the same provider do not
        burn an attempt each.

    `good` (servers that already handshook) is only the anchor when we are not
    connected. Everything except the nmcli reads is pure.
    """
    good = good or []
    pool = [n for n in names if n != current]
    if not pool:
        return []
    data = {n: vpn_data(n) for n in pool}
    authed = [n for n in pool if "ta" in data[n]]
    # If nothing advertises tls-auth this is a different provider and every
    # profile is fair game; otherwise the ta-less duplicates must not cost an
    # attempt.
    pool = authed or pool
    anchor = current if current in names else (good[0] if good and good[0] in names else "")
    if anchor in names:
        start = names.index(anchor)
        ordered = names[start + 1:] + names[:start]
        ordered = [n for n in ordered if n in pool]
    else:
        ordered = pool
    seen: set[str] = set()
    unique: list[str] = []
    for name in ordered:
        key = data.get(name, {}).get("remote") or name
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    # Servers that already handshook go first, so a press of NEW IP tries the
    # ones that work before paying a timeout on a dead one.
    proven = [n for n in unique if n in good]
    fresh = [n for n in unique if n not in good]
    return proven + fresh


@dataclass
class RotateResult:
    ok: bool
    name: str = ""
    message: str = ""
    tried: list[tuple[str, str]] = field(default_factory=list)


def rotate(
    candidates: list[str],
    current: str,
    attempts: int = 3,
    timeout: int = 20,
) -> RotateResult:
    """Disconnect, bring up the next candidate, and never leave the device bare.

    If every candidate fails, the previous profile is restored before returning.
    """
    if not candidates:
        return RotateResult(False, current, "no other server to switch to")
    if current:
        down(current, timeout=15)
    tried: list[tuple[str, str]] = []
    for name in candidates[:attempts]:
        ok, msg = up(name, timeout=timeout)
        if ok:
            return RotateResult(True, name, msg, tried)
        tried.append((name, msg))
    restored = ""
    if current:
        ok, _msg = up(current, timeout=timeout)
        if ok:
            restored = current
    detail = "; ".join(f"{n}: {m}" for n, m in tried) or "no candidates"
    if restored:
        return RotateResult(False, restored, f"no server answered, back on {restored}", tried)
    return RotateResult(False, "", detail, tried)


# ------------------------------------------------------------------- control
def up(name: str, timeout: float = 60) -> tuple[bool, str]:
    cap = int(timeout)
    rc, out, err = _run(
        ["--wait", str(cap), "connection", "up", name], timeout=cap + 10
    )
    if rc == 0:
        return True, "connected"
    blob = f"{err}\n{out}"
    low = blob.lower()
    if "already active" in low:
        return True, "already active"
    reason = err.strip().splitlines()[-1] if err.strip() else f"nmcli exit {rc}"
    if "no valid secrets" in low or "secrets were required" in low:
        reason = "no saved login (right-click → Save login)"
    elif "timeout expired" in low:
        reason = "server did not answer"
    return False, reason


def down(name: str, timeout: float = 30) -> tuple[bool, str]:
    cap = int(timeout)
    rc, _, err = _run(["--wait", str(cap), "connection", "down", name], timeout=cap + 5)
    if rc == 0:
        return True, "disconnected"
    if "not an active connection" in err.lower():
        return True, "already down"
    return False, (err.strip().splitlines()[-1] if err.strip() else f"nmcli exit {rc}")


def public_ip(timeout: float = 6) -> str:
    """Egress IP as the internet sees it, i.e. the VPN exit address."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "oc-vpn/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                txt = fh.read(64).decode("ascii", "replace").strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""


def kill_external() -> tuple[bool, str]:
    """Stop a hand-started `openvpn --config ...` so NetworkManager can own it.

    Runs through pkexec, which asks for the password in a normal desktop dialog;
    there is no sudoers rule and no stored root password.
    """
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False, "pkexec not installed"
    try:
        p = subprocess.run(
            [pkexec, "pkill", "-f", "openvpn --config"],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if p.returncode == 0:
        return True, "manual openvpn stopped"
    return False, (p.stderr.strip() or "cancelled")
