"""Destructive actions + the guards around them."""

from __future__ import annotations

import os
import shutil
import subprocess

LABELS = {
    "shutdown": "Shut down",
    "suspend": "Suspend",
    "lock": "Lock screen",
    "notify": "Notify only",
}

ARGV = {
    "shutdown": ["systemctl", "--no-block", "poweroff"],
    "suspend": ["systemctl", "--no-block", "suspend"],
    "lock": ["loginctl", "lock-sessions"],
    "notify": None,
}

POLKIT_ACTION = {
    "shutdown": "org.freedesktop.login1.power-off",
    "suspend": "org.freedesktop.login1.suspend",
    "lock": "org.freedesktop.login1.lock-sessions",
}


def label(action: str) -> str:
    return LABELS.get(action, action)


def dry_run() -> bool:
    return os.environ.get("OCTIMER_DRY_RUN", "") not in ("", "0", "false", "no")


def polkit_allows(action: str) -> tuple[bool, str]:
    """Ask polkit whether this process may perform the action right now."""
    act = POLKIT_ACTION.get(action)
    if not act:
        return True, "no permission needed"
    if dry_run():
        return True, "dry-run"
    if not shutil.which("pkcheck"):
        return True, "pkcheck missing (assuming allowed)"
    try:
        p = subprocess.run(
            ["pkcheck", "--action-id", act, "--process", str(os.getpid())],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"pkcheck failed: {exc}"
    if p.returncode == 0:
        return True, "allowed"
    return False, (p.stderr.decode("utf-8", "replace").strip() or f"exit {p.returncode}")[:200]


def execute(action: str, log=None) -> tuple[bool, str]:
    """Run the action. Returns (ok, message). Never raises."""
    say = log or (lambda msg: None)
    if action == "notify":
        return True, "notify only"
    argv = ARGV.get(action)
    if not argv:
        return False, f"unknown action {action!r}"
    if dry_run():
        say(f"dry-run: would run {' '.join(argv)}")
        return True, f"dry-run: {' '.join(argv)}"
    ok, msg = polkit_allows(action)
    if not ok:
        say(f"polkit refused {action}: {msg}")
        return False, msg
    try:
        # Detach: the compositor kills us mid-teardown otherwise.
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"{action} failed: {exc}")
        return False, str(exc)
    say(f"issued: {' '.join(argv)}")
    return True, " ".join(argv)
