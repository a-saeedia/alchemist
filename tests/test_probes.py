"""Probe tests: API path, DB fallback, and failure tolerance."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from octimer.probes import Probe, Snapshot  # noqa: E402


def make_cli(tmpdir: str, body: str, exit_code: int = 0) -> str:
    path = os.path.join(tmpdir, "fake-opencode")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n")
        fh.write(body + "\n")
        fh.write(f"exit {exit_code}\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class ApiPath(unittest.TestCase):
    def test_reports_running_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = make_cli(
                tmp,
                """printf '%s' '{"data":{"ses_b":{"type":"running"},"ses_a":{"type":"running"}}}'""",
            )
            p = Probe(cli=cli, home=tmp, db=os.path.join(tmp, "none.db"))
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "api")
            self.assertTrue(snap.busy)
            self.assertEqual(snap.ids, ("ses_a", "ses_b"))
            self.assertEqual(snap.count, 2)

    def test_empty_data_is_idle_not_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = make_cli(tmp, """printf '%s' '{"data":{}}'""")
            # fresh wal so the db fallback would say busy -- the API must win
            db = os.path.join(tmp, "opencode.db")
            open(db + "-wal", "w").close()
            p = Probe(cli=cli, home=tmp, db=db)
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "api")
            self.assertFalse(snap.busy)

    def test_cache_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = make_cli(tmp, """printf '%s' '{"data":{"ses_a":{}}}'""")
            p = Probe(cli=cli, home=tmp, db=os.path.join(tmp, "none.db"), ttl=60)
            first = p.snapshot(force=True)
            second = p.snapshot()
            self.assertIs(first, second)


class DbFallback(unittest.TestCase):
    def test_fresh_wal_means_busy(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "opencode.db")
            open(db + "-wal", "w").close()
            p = Probe(cli=None, home=tmp, db=db, fallback_quiet=8)
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "db")
            self.assertTrue(snap.busy)

    def test_stale_wal_means_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "opencode.db")
            open(db, "w").close()
            open(db + "-wal", "w").close()
            old = time.time() - 120
            os.utime(db + "-wal", (old, old))
            os.utime(db, (old, old))
            p = Probe(cli=None, home=tmp, db=db, fallback_quiet=8)
            snap = p.snapshot(force=True)
            self.assertFalse(snap.busy)

    def test_missing_db_is_idle_and_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Probe(cli=None, home=tmp, db=os.path.join(tmp, "nope.db"))
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "none")
            self.assertFalse(snap.busy)
            self.assertIsNone(p.wal_age())

    def test_cli_failure_falls_back_to_wal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = make_cli(tmp, "echo boom >&2", exit_code=3)
            db = os.path.join(tmp, "opencode.db")
            open(db + "-wal", "w").close()
            p = Probe(cli=cli, home=tmp, db=db, fallback_quiet=8)
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "db")
            self.assertTrue(snap.busy)
            self.assertIn("boom", snap.detail)

    def test_garbage_output_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = make_cli(tmp, "printf 'not json'")
            db = os.path.join(tmp, "opencode.db")
            open(db, "w").close()
            open(db + "-wal", "w").close()
            old = time.time() - 90
            os.utime(db + "-wal", (old, old))
            os.utime(db, (old, old))
            p = Probe(cli=cli, home=tmp, db=db, fallback_quiet=8)
            snap = p.snapshot(force=True)
            self.assertEqual(snap.source, "db")
            self.assertFalse(snap.busy)


class SnapshotShape(unittest.TestCase):
    def test_count(self):
        self.assertEqual(Snapshot(busy=True, ids=("a", "b", "c")).count, 3)
        self.assertEqual(Snapshot(busy=False).count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
