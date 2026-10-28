# oc-timer

A small floating desktop widget: drag it anywhere, set a countdown, and the
machine shuts itself down when the countdown lands — or when every opencode
session has stopped working.

No tray icon, no window decorations, no dashboard. One 270 px card that stays
on top of every workspace.

```
┌───────────────────────────────┐
│ ● OCTIMER            TIMER  ✕ │
│ 30:00                         │
│ ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔  │
│ opencode idle · ends 07:01    │
│ [−5m][−1m][+1m][+5m]          │
│ [ 5m ][ 15m ][ 30m ][ 60m ]   │
│ [ TIMER ][ WATCH OC ]         │
│ ☐ wait for opencode  SHUT ▾   │
│ [          ARM            ]   │
└───────────────────────────────┘
```

## Install

```bash
./install.sh              # ~/.local/bin/oc-timer + application menu entry
./install.sh --autostart  # also start it (idle) at login
./install.sh --uninstall
```

Only dependency is Python 3 + PyGObject GTK 3 (`python3-gi`), both already on
Pop!_OS. There is nothing to pip install.

## Use

```bash
oc-timer                       # 30 min timer, remembered from last time
oc-timer --minutes 45
oc-timer --watch               # shut down when opencode goes idle
oc-timer --watch --dry-run     # rehearse it, never powers off
oc-timer --minutes 20 --drain  # timer ends early? wait for opencode, then off
oc-timer --minutes 0.5 --arm --log-file ~/.local/state/oc-timer.log
```

Widget controls: **drag anywhere** to move, **scroll** over the card to nudge
the time (±1 min, ⇧ for ±5), **right-click** for reset-position/quit,
**Esc** cancels while armed or quits while idle, **Enter** arms.
The window position, last duration, mode and action are remembered in
`~/.config/octimer/state.json`.

CLI flags: `--minutes N` `--watch` `--drain/--no-drain` `--action
shutdown|suspend|lock|notify` `--grace SECS` `--countdown SECS` `--arm`
`--dry-run` `--log-file PATH` `--shoot PNG`.

## The two triggers

**TIMER** — counts down from N minutes. At zero it fires. Tick
*"wait for opencode"* (`--drain`) and it instead waits for the agent to stop
working before it pulls the plug: the timer says *when you want to be done*, the
session watcher makes sure nothing is cut off mid-edit.

**WATCH OC** — no countdown. It waits for opencode work to appear, then powers
off once everything is finished. Armed while nothing is running, it gives you 30
seconds (`--grace`-independent `arm_grace`) to start a session before deciding
nothing was going to happen.

Either way the action is preceded by a **10 second cancellable countdown** with
beeps, a red border and a big CANCEL button. Default action is shutdown; suspend,
lock and notify-only are in the `SHUT ▾` menu.

### What counts as "finished"

The probe asks opencode itself:

```bash
opencode api GET /api/session/active
# {"data":{"ses_…":{"type":"running"}}}
```

That endpoint reports sessions that currently own a foreground agent turn — it
stays `running` during long tool calls, so a five-minute build is not mistaken
for idle. Sessions disappear from it the moment the turn ends, including when the
agent is just waiting for your next message.

`finished` = that set is empty for a continuous 12 s (`--grace`). The delay keeps
a between-steps gap from firing the shutdown early.

If the CLI or API is unavailable (standalone server, odd install), the probe
degrades to the mtime of `~/.local/share/opencode/opencode.db-wal`, which is
touched by any commit during a turn. The status line shows which source answered:
`source=api` vs `source=db`.

## Permissions

`systemctl --no-block poweroff` is used, so systemd tears things down properly.
On a normal local session polkit allows this without a password. Check first:

```bash
pkcheck --action-id org.freedesktop.login1.power-off --process $$
```

If that fails, add `/etc/polkit-1/rules.d/49-oc-timer.rules`:

```javascript
polkit.addRule(function (action, subject) {
  if ((action.id == "org.freedesktop.login1.power-off" ||
       action.id == "org.freedesktop.login1.power-off-multiple-sessions") &&
      subject.isInGroup("arman")) {
    return polkit.Result.YES;
  }
});
```

Use `--dry-run` (or `OCTIMER_DRY_RUN=1`) to exercise the whole flow without
touching the power state.

## Layout

```
oc-timer                 launcher (forces the X11 backend via XWayland)
octimer/
  __main__.py            arg parsing, state file, Gtk.main
  engine.py              pure state machine: idle → timer/watch → drain → fire
  probes.py              opencode activity probe (API first, WAL fallback)
  power.py               shutdown/suspend/lock, polkit preflight, dry-run
  ui.py                  GTK3 widget: frameless, always-on-top, drag anywhere
tests/                   engine + probe unit tests (20, no display needed)
dev/shots.py             renders every widget state to PNG for visual QA
packaging/, icons/       .desktop template + app icon for install.sh
```

## Develop

```bash
python3 -m unittest discover -s tests -v      # 20 tests, no display needed
OCTIMER_DRY_RUN=1 GDK_BACKEND=x11 python3 dev/shots.py /tmp/shots
./oc-timer --minutes 0.05 --countdown 2 --dry-run --arm --log-file /tmp/e2e.log
cat /tmp/e2e.log
```

Two notes for future edits:

* The widget runs on `GDK_BACKEND=x11` on purpose. Plain Wayland gives clients no
  always-on-top and no self-initiated move, so the card would behave like a
  normal window.
* COSMIC's GTK theme paints `Gtk.ProgressBar` with its accent colour at a CSS
  priority that beats application rules, so the progress rail is two plain boxes
  (`.rail` / `.railfill`) instead. Same reason the clock is a `Gtk.Label` with a
  `min-height`-free CSS size: 38 px+ Fira Mono clipped its ascenders.

---

# oc-vpn

The other half of the suite: OpenVPN on the whole device (every app, Chrome and
all, because the tunnel is the default route — not a browser proxy), plus a
corner switch that changes the exit IP in one click.

```
┌──────────────────────────────────┐
│ ● OC-VPN              [ ON ] – ✕ │
│ USA-Google-UDP                   │
│ 162.217.248.178       [⏻] [NEW IP]│
│ tun0 · 15 servers                │
└──────────────────────────────────┘
```

## Install

```bash
./install-vpn.sh              # ~/.local/bin/oc-vpn + application menu entry
./install-vpn.sh --autostart  # also start the card at login
./install-vpn.sh --uninstall
```

Nothing here needs root. NetworkManager already owns the tunnel and its polkit
rules let the logged-in user toggle their own VPN, so there is no sudoers rule,
no stored root password and no `sudo` in either the widget or the CLI.

## Save the login once

The profiles authenticate with `auth-user-pass`, so each one needs the account.
Do this once and every profile keeps working:

```bash
oc-vpn --save-login
```

The dialog (or terminal prompt) asks for user and password, then writes them
into **all** VPN profiles with `password-flags=0` and lets NetworkManager store
the secret itself. `nmcli con up <name>` then connects with no prompt at all.
Details:

* The secret lives in NetworkManager's own store — a 0600, root-owned keyfile
  under `/etc/NetworkManager/system-connections/`. It is never written to a
  plaintext file next to the app and never into `state.json`.
* `+vpn.data` merges instead of replacing, so `remote`, `cipher`, `ta` and
  `remote-random` survive the edit (there is a test for exactly that).
* Passwords containing `,` or `\` are escaped for nmcli's dictionary syntax.
* `oc-vpn --list` marks every profile `login` or `no-login`, so you can see what
  still needs the account.

## The corner button

`oc-vpn` floats bottom-right, above other windows, and remembers where you drag
it (`~/.config/ocvpn/state.json`).

| control | what it does |
| --- | --- |
| card body | drag to move |
| `⏻` | connect the last-used profile / disconnect |
| `NEW IP` | disconnect, connect the next server, refresh the IP readout |
| `–` | collapse to the header bar (the compact pill) |
| `✕` / `Esc` | quit |
| right-click | profiles menu, save login, new IP, adopt, reset position, quit |

`–` is a collapse rather than `iconify()` on purpose: the card is an
override-redirect X11 window with no taskbar entry, so a real minimise would
hide it somewhere you cannot click it back. Collapsing keeps the bottom edge
planted and leaves the state chip visible; `▴` expands it again.

The readout line shows the live egress IP — the address the VPN exit presents to
the internet, so a rotation is visible immediately, not just after a reconnect.
The chip is the state: `ON` (cyan), `OFF` (grey), `EXTERNAL` (amber, an openvpn
you started by hand), `WORKING` while a switch is in flight.

### What `NEW IP` will and will not try

Rotation is round-robin past the current server with three filters:

* never the server already connected;
* skip profiles with no `tls-auth` (`ta`) key — broken imports that can never
  handshake, and they would otherwise eat a 20 s timeout each;
* one candidate per remote host, so provider duplicates don't repeat.

Servers that have handshook before are tried first (a small MRU list in
`state.json`), and if every candidate fails the previous profile is brought back
up before the card reports the error. It never leaves the device on the raw
uplink by accident.

## CLI

```bash
oc-vpn --status          # up/down + exit IP, exit code 0 when tunneled
oc-vpn --status --json
oc-vpn --list            # profiles + login state
oc-vpn --up USA-UDP      # connect one
oc-vpn --down
oc-vpn --rotate          # next server, prints the new exit IP
oc-vpn --adopt           # stop a hand-started openvpn, take over via NetworkManager
```

`oc-vpn --rotate` is the scriptable form of the button:

```bash
oc-vpn --rotate && oc-vpn --status
```

## Why the card is an X11 POPUP

COSMIC's XWayland ignores `move()` on WM-managed windows, so an ordinary
toplevel always opens wherever the compositor decides — the bottom-right corner
would just be a wish. A `Gtk.WindowType.POPUP` toplevel is override-redirect:
the compositor leaves it alone, `move()` lands exactly where asked, and it stacks
above managed windows. The card position is verified against the X server
(`xwininfo` reports `272x117+1620+891` on a 1920x1080 screen, i.e. 28 px from the
right edge and 72 px above the panel).

The two consequences are handled in `ui.py`: dragging is implemented by hand
(press → motion → move → release saves), and `–` collapses instead of iconifying
because there is no taskbar entry to restore an iconified override-redirect
window from.

## Adopting a hand-started tunnel
`sudo openvpn --config X.ovpn --redirect-gateway def1` works, but NetworkManager
cannot see it, so it cannot be rotated, restored after sleep, or stopped without
`sudo`. The card detects that case and shows `EXTERNAL`; press `⏻` and it runs
`pkexec pkill -f "openvpn --config"` (a normal desktop password dialog, once)
then brings the profile up under NetworkManager.

The managed path is also the one that survives reboots: with a login saved, the
profile reconnects by itself at login and `NEW IP` keeps working.

## Layout

```
oc-vpn                     launcher (forces the X11 backend via XWayland)
ocvpn/
  __main__.py              CLI: status/list/up/down/rotate/save-login/adopt
  nm.py                    nmcli backend: profiles, status, rotate, egress IP
  creds.py                 one-time login capture, GTK dialog + terminal fallback
  ui.py                    GTK3 card: corner placement, chip states, async actions
tests/test_vpn.py          parsing, rotation order, status shapes (no nmcli)
```

## Not in here

The button changes the **VPN exit IP**. It does not reset, wipe or reroute any
local application state, and there is no code here that clears another app's
database or tries to defeat a service's usage limits. Rotating an exit gives you
a different network vantage point; it does not change what a service counts
against your account, and a client-side reset usually just loses your sessions.

---

# VPN Platform (dashboard + providers)

The corner card now ships with a full dashboard and a provider catalogue:

```bash
oc-vpn --dashboard        # full window: connection, profiles, provider grid
oc-vpn --providers        # list known VPN backends and install state
oc-vpn --launch nym       # launch a provider by id
oc-vpn --provider-status protonvpn
```

Right-click the card → "Open dashboard" / "Providers" for the same.

Free backends detected when installed: OpenVPN/WireGuard (NM), Proton VPN,
Cloudflare WARP, Riseup, NymVPN, eOVPN, Trayscale, Outline, Tor, I2P, Mullvad
Browser. Install the missing system ones with `sudo ./install-free-vpns.sh`.
