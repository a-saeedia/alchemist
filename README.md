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
