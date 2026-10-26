"""oc-timer: a tiny drag-anywhere countdown that switches the box off.

    python3 -m octimer --minutes 45
    python3 -m octimer --watch          # shut down when opencode goes idle
    python3 -m octimer --watch --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import power
from .engine import ACTIONS, MODE_TIMER, MODE_WATCH, Settings
from .probes import Probe

STATE_KEYS = ("minutes", "mode", "drain", "action", "x", "y")


def state_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "octimer", "state.json")


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in STATE_KEYS}


def lock_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "octimer", "pid")


def running_pid() -> int | None:
    """PID of a live oc-timer, so a second launch does not stack widgets."""
    try:
        with open(lock_path(), encoding="utf-8") as fh:
            pid = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        return None
    if "octimer" in cmd:
        return pid
    return None


def take_lock() -> None:
    try:
        path = lock_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass


def drop_lock() -> None:
    try:
        if running_pid() is None:
            os.unlink(lock_path())
    except OSError:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="octimer",
        description="Draggable countdown that shuts the system down when it ends, "
        "or when every opencode session finishes.",
    )
    p.add_argument("-m", "--minutes", type=float, help="countdown length in minutes")
    p.add_argument("-w", "--watch", action="store_true", help="start in WATCH mode")
    p.add_argument("--drain", dest="drain", action="store_true", default=None,
                   help="when the timer ends, wait for opencode to finish first")
    p.add_argument("--no-drain", dest="drain", action="store_false")
    p.add_argument("-a", "--action", choices=ACTIONS, help="what to do when it fires")
    p.add_argument("--grace", type=float, help="seconds of continuous idle = finished")
    p.add_argument("--countdown", type=float, help="cancellable seconds before firing")
    p.add_argument("--dry-run", action="store_true", help="never actually power off")
    p.add_argument("--arm", action="store_true", help="arm immediately on start")
    p.add_argument("--log-file", metavar="PATH", help="append a timestamped event log")
    p.add_argument("--shoot", metavar="PNG", help="render once to PNG and exit (QA)")
    p.add_argument(
        "--new-instance", action="store_true", help="start even if one is already running"
    )
    p.add_argument("--version", action="version", version="oc-timer 1.0")
    return p.parse_args(argv)


def build_settings(args: argparse.Namespace, state: dict) -> Settings:
    s = Settings(
        minutes=state.get("minutes", 30.0),
        mode=state.get("mode", MODE_TIMER),
        drain=bool(state.get("drain", False)),
        action=state.get("action", "shutdown"),
    )
    if args.minutes is not None:
        s.minutes = args.minutes
    if args.watch:
        s.mode = MODE_WATCH
    if args.drain is not None:
        s.drain = args.drain
    if args.action:
        s.action = args.action
    if args.grace is not None:
        s.idle_grace = args.grace
    if args.countdown is not None:
        s.countdown = args.countdown
    if s.mode == MODE_WATCH:
        s.drain = True
    return s.clamped()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        os.environ["OCTIMER_DRY_RUN"] = "1"

    if not args.new_instance:
        pid = running_pid()
        if pid:
            print(f"oc-timer already running (pid {pid}); use --new-instance to stack another")
            return 0
    take_lock()

    from .ui import OctimerWindow  # imported late: needs a display

    state = load_state()
    settings = build_settings(args, state)
    window = OctimerWindow(
        settings=settings,
        probe=Probe(),
        store=state,
        arm_on_start=args.arm,
        log_file=args.log_file,
    )
    if args.shoot:
        window.show_all()
    else:
        window.start()

    if args.shoot:
        from gi.repository import GLib

        out = os.path.abspath(args.shoot)

        def grab() -> bool:
            ok = window.shoot(out)
            print(f"{'wrote' if ok else 'failed'}: {out}")
            window.destroy()
            from gi.repository import Gtk

            Gtk.main_quit()
            return False

        GLib.timeout_add(900, grab)

    from gi.repository import Gtk

    try:
        Gtk.main()
    finally:
        drop_lock()
    return 0


if __name__ == "__main__":
    sys.exit(main())
