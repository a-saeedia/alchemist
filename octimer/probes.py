"""opencode activity probe.

Two independent signals, cheapest first:

1. ``opencode api GET /api/session/active`` -- authoritative. The shared
   background service reports which sessions currently own a foreground drain
   (i.e. an agent turn is actually running, including during long tool calls).
   Takes ~100 ms, so it is safe to call every couple of seconds.
2. SQLite WAL mtime on ``~/.local/share/opencode/opencode.db`` -- degraded
   fallback used only when the CLI/API is unavailable (standalone servers,
   old versions). Any commit during a turn bumps it.

``busy`` means "some agent is working"; everything else (waiting for the user,
permission prompt, finished turn) is idle and therefore "finished" for the
purposes of shutting the box down.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass


@dataclass
class Snapshot:
    busy: bool
    ids: tuple = ()
    source: str = "api"     # api | db | none
    detail: str = ""
    at: float = 0.0

    @property
    def count(self) -> int:
        return len(self.ids)


AUTO = object()  # sentinel: discover the CLI, as opposed to "no CLI"


def _default_cli() -> str | None:
    for c in (
        os.environ.get("OCTIMER_OPENCODE"),
        shutil.which("opencode"),
        os.path.expanduser("~/.opencode/bin/opencode"),
    ):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _default_db() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "opencode", "opencode.db")


class Probe:
    """Cached, failure-tolerant view of opencode activity."""

    def __init__(
        self,
        cli=AUTO,
        home: str | None = None,
        db: str | None = None,
        ttl: float = 1.5,
        fallback_quiet: float = 8.0,
        timeout: float = 5.0,
    ) -> None:
        self.cli = _default_cli() if cli is AUTO else cli
        self.home = home or os.path.expanduser("~")
        self.db = db or _default_db()
        self.ttl = ttl
        self.fallback_quiet = fallback_quiet
        self.timeout = timeout
        self._last: Snapshot | None = None
        self._api_error = ""

    # ------------------------------------------------------------------ api
    def _via_api(self) -> Snapshot | None:
        if not self.cli:
            return None
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        try:
            p = subprocess.run(
                [self.cli, "api", "GET", "/api/session/active"],
                cwd=self.home,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._api_error = f"cli error: {exc}"[:120]
            return None
        if p.returncode != 0:
            err = p.stderr.decode("utf-8", "replace").strip().splitlines()
            self._api_error = (err[-1] if err else f"exit {p.returncode}")[:120]
            return None
        try:
            payload = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            self._api_error = "unparsable api output"
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            self._api_error = "unexpected api shape"
            return None
        self._api_error = ""
        ids = tuple(sorted(data.keys()))
        return Snapshot(busy=bool(ids), ids=ids, source="api", detail="api")

    # ------------------------------------------------------------------- db
    def wal_age(self) -> float | None:
        ages = []
        for path in (self.db + "-wal", self.db):
            try:
                ages.append(time.time() - os.stat(path).st_mtime)
            except OSError:
                continue
        return min(ages) if ages else None

    def _via_db(self) -> Snapshot:
        age = self.wal_age()
        if age is None:
            return Snapshot(busy=False, source="none", detail="no db")
        return Snapshot(
            busy=age < self.fallback_quiet,
            source="db",
            detail=f"wal {age:.0f}s",
        )

    # -------------------------------------------------------------- public
    def snapshot(self, force: bool = False) -> Snapshot:
        now = time.time()
        if (
            not force
            and self._last is not None
            and now - self._last.at < self.ttl
        ):
            return self._last

        snap = self._via_api()
        if snap is None:
            snap = self._via_db()
            if self._api_error:
                snap.detail = f"{snap.detail} / {self._api_error}"
        snap.at = now
        self._last = snap
        return snap
