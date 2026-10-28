"""oc-vpn backend tests: parsing, profile rotation, status shapes.

No NetworkManager, no display, no network. Every nmcli call is faked.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocvpn import creds, nm  # noqa: E402


class Parsing(unittest.TestCase):
    def test_split_plain(self):
        self.assertEqual(nm._split("a:b:c"), ["a", "b", "c"])

    def test_split_keeps_escaped_colon_in_name(self):
        # NetworkManager escapes ':' inside a profile name as '\:'
        self.assertEqual(nm._split(r"NL\:Amsterdam:vpn:uuid-1"), ["NL:Amsterdam", "vpn", "uuid-1"])

    def test_split_keeps_escaped_backslash(self):
        self.assertEqual(nm._split(r"a\\b:vpn"), [r"a\b", "vpn"])

    def test_split_trims_trailing_newline(self):
        self.assertEqual(nm._split("x:y\n"), ["x", "y"])

    def test_quote_dict_value(self):
        self.assertEqual(nm.quote_dict_value("plain"), "plain")
        self.assertEqual(nm.quote_dict_value("a,b"), r"a\,b")
        self.assertEqual(nm.quote_dict_value("a\\b"), "a\\\\b")
        self.assertEqual(nm.quote_dict_value("p@ss w0rd!"), "p@ss w0rd!")


class Rotation(unittest.TestCase):
    NAMES = ["DE-UDP", "USA-Google-UDP", "TR-UDP"]

    def test_advances(self):
        self.assertEqual(nm.next_profile(self.NAMES, "DE-UDP"), "USA-Google-UDP")
        self.assertEqual(nm.next_profile(self.NAMES, "USA-Google-UDP"), "TR-UDP")

    def test_wraps_around(self):
        self.assertEqual(nm.next_profile(self.NAMES, "TR-UDP"), "DE-UDP")

    def test_unknown_current_starts_at_first(self):
        self.assertEqual(nm.next_profile(self.NAMES, ""), "DE-UDP")
        self.assertEqual(nm.next_profile(self.NAMES, "gone"), "DE-UDP")

    def test_empty(self):
        self.assertEqual(nm.next_profile([], "DE-UDP"), "")


def fake_run(table):
    """Build a stand-in for nm._run from {tuple(args): (rc, out, err)}."""

    def _run(args, timeout=20):
        key = tuple(args)
        if key in table:
            return table[key]
        for pattern, value in table.items():
            if pattern == "default":
                continue
            if all(p in key for p in pattern):
                return value
        return table.get("default", (0, "", ""))

    return _run


class Status(unittest.TestCase):
    def setUp(self):
        self._orig_run = nm._run
        self._orig_iface = nm.default_iface
        nm.default_iface = lambda: "tun0"

    def tearDown(self):
        nm._run = self._orig_run
        nm.default_iface = self._orig_iface

    def test_active_vpn(self):
        nm._run = fake_run(
            {
                ("-t", "-f", "NAME,TYPE,UUID", "connection", "show"): (
                    0,
                    "DE-UDP:vpn:u1\nUSA-UDP:vpn:u2\nPOCO M6:802-11-wireless:u3\n",
                    "",
                ),
                ("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"): (
                    0,
                    "DE-UDP:vpn:tun0\nPOCO M6:802-11-wireless:wlp4s0\n",
                    "",
                ),
                ("-g", "vpn.data", "connection", "show", "DE-UDP"): (
                    0,
                    "auth = SHA256, password-flags = 0, remote = x:443",
                    "",
                ),
            }
        )
        st = nm.status()
        self.assertTrue(st.connected)
        self.assertEqual(st.name, "DE-UDP")
        self.assertEqual(st.iface, "tun0")
        self.assertEqual(st.count, 2)
        self.assertTrue(st.has_login)
        self.assertFalse(st.external)

    def test_password_flags_1_means_no_login(self):
        nm._run = fake_run(
            {
                ("-t", "-f", "NAME,TYPE,UUID", "connection", "show"): (0, "DE-UDP:vpn:u1\n", ""),
                ("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"): (
                    0,
                    "DE-UDP:vpn:tun0\n",
                    "",
                ),
                ("-g", "vpn.data", "connection", "show", "DE-UDP"): (
                    0,
                    "auth = SHA256, password-flags = 1",
                    "",
                ),
            }
        )
        st = nm.status()
        self.assertTrue(st.connected)
        self.assertFalse(st.has_login)

    def test_manual_openvpn_is_external(self):
        nm._run = fake_run(
            {
                ("-t", "-f", "NAME,TYPE,UUID", "connection", "show"): (0, "DE-UDP:vpn:u1\n", ""),
                ("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"): (
                    0,
                    "POCO M6:802-11-wireless:wlp4s0\n",
                    "",
                ),
            }
        )
        st = nm.status()
        self.assertFalse(st.connected)
        self.assertTrue(st.external)
        self.assertEqual(st.iface, "tun0")

    def test_wireless_default_route_is_not_external(self):
        nm.default_iface = lambda: "wlp4s0"
        nm._run = fake_run(
            {
                ("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"): (
                    0,
                    "POCO M6:802-11-wireless:wlp4s0\n",
                    "",
                ),
            }
        )
        st = nm.status()
        self.assertFalse(st.connected)
        self.assertFalse(st.external)

    def test_labels(self):
        self.assertEqual(nm.Status().label, "disconnected")
        self.assertEqual(nm.Status(connected=True, name="DE-UDP").label, "DE-UDP")
        self.assertEqual(nm.Status(external=True, iface="tun0").label, "tun0 (manual)")


class VpnData(unittest.TestCase):
    def setUp(self):
        self._orig = nm._run

    def tearDown(self):
        nm._run = self._orig

    def test_parses_dictionary(self):
        nm._run = fake_run(
            {
                ("-g", "vpn.data", "connection", "show", "DE-UDP"): (
                    0,
                    "auth = SHA256, cipher = AES-256-CBC, remote = s1.example.com:443, "
                    "username = bnps209396, password-flags = 0",
                    "",
                )
            }
        )
        data = nm.vpn_data("DE-UDP")
        self.assertEqual(data["username"], "bnps209396")
        self.assertEqual(data["password-flags"], "0")
        self.assertEqual(data["remote"], "s1.example.com:443")

    def test_missing_profile(self):
        nm._run = fake_run({("default",): (1, "", "no such connection")})
        self.assertEqual(nm.vpn_data("nope"), {})


class CredentialResult(unittest.TestCase):
    def test_summary_all_saved(self):
        res = creds.Result(True, ["a", "b"], {})
        self.assertIn("2 profile", res.summary())

    def test_summary_partial(self):
        res = creds.Result(False, ["a"], {"b": "polkit denied"})
        out = res.summary()
        self.assertIn("1 saved", out)
        self.assertIn("b", out)

    def test_summary_nothing(self):
        self.assertEqual(creds.Result(False, [], {}).summary(), "nothing saved")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class RotationCandidates(unittest.TestCase):
    """Rotation must skip broken duplicates and same-host clones."""

    def setUp(self):
        self._orig = nm.vpn_data

    def tearDown(self):
        nm.vpn_data = self._orig

    def profile(self, remote: str, tls: bool = True) -> dict:
        data = {"remote": remote}
        if tls:
            data["ta"] = "/root/.cert/x.pem"
        return data

    def fake(self, mapping):
        nm.vpn_data = lambda n: mapping.get(n, self.profile(f"same-{n}"))

    def test_skips_profiles_without_tls_auth(self):
        self.fake(
            {
                "DE-UDP": self.profile("de"),
                "DE-UDP (1)": self.profile("de", tls=False),
                "Neth-TCP": self.profile("neth"),
            }
        )
        got = nm.rotate_candidates(["DE-UDP", "DE-UDP (1)", "Neth-TCP"], "DE-UDP", [])
        self.assertEqual(got, ["Neth-TCP"])

    def test_round_robin_past_the_current_server(self):
        self.fake({n: self.profile(n) for n in "ABC"})
        self.assertEqual(nm.rotate_candidates(list("ABC"), "A", []), ["B", "C"])

    def test_wraps_to_the_start(self):
        self.fake({n: self.profile(n) for n in "ABC"})
        self.assertEqual(nm.rotate_candidates(list("ABC"), "C", []), ["A", "B"])

    def test_not_connected_anchors_on_last_good_server(self):
        self.fake({n: self.profile(n) for n in "ABC"})
        self.assertEqual(nm.rotate_candidates(list("ABC"), "", ["B"]), ["C", "A"])

    def test_one_candidate_per_remote_host(self):
        self.fake(
            {
                "Neth-TCP": self.profile("neth"),
                "Neth-UDP": self.profile("neth"),
                "USA-TCP": self.profile("usa"),
            }
        )
        got = nm.rotate_candidates(["DE-UDP", "Neth-TCP", "Neth-UDP", "USA-TCP"], "DE-UDP", [])
        self.assertEqual(got, ["Neth-TCP", "USA-TCP"])

    def test_good_servers_are_tried_before_untested_ones(self):
        self.fake({n: self.profile(n) for n in "ABC"})
        self.assertEqual(nm.rotate_candidates(list("ABC"), "A", ["C"]), ["C", "B"])

    def test_everything_ta_less_falls_back_to_plain_order(self):
        self.fake({n: self.profile(n, tls=False) for n in "AB"})
        self.assertEqual(nm.rotate_candidates(["A", "B"], "A", []), ["B"])

    def test_single_profile_has_no_candidate(self):
        nm.has_tls_auth = lambda n: True
        self.assertEqual(nm.rotate_candidates(["A"], "A", []), [])


class RotateFlow(unittest.TestCase):
    def setUp(self):
        self._up, self._down = nm.up, nm.down
        self.calls = []

    def tearDown(self):
        nm.up, nm.down = self._up, self._down

    def test_switches_to_first_candidate(self):
        nm.down = lambda n, timeout=15: (self.calls.append(("down", n)), (True, "ok"))[1]
        nm.up = lambda n, timeout=20: (self.calls.append(("up", n)), (True, "connected"))[1]
        res = nm.rotate(["B", "C"], "A", attempts=2)
        self.assertTrue(res.ok)
        self.assertEqual(res.name, "B")
        self.assertEqual(self.calls, [("down", "A"), ("up", "B")])

    def test_tries_next_when_first_server_is_dead(self):
        def up(n, timeout=20):
            self.calls.append(("up", n))
            return (n == "C", "connected" if n == "C" else "server did not answer")

        nm.up = up
        nm.down = lambda n, timeout=15: (True, "ok")
        res = nm.rotate(["B", "C", "D"], "A", attempts=3)
        self.assertTrue(res.ok)
        self.assertEqual(res.name, "C")
        self.assertEqual([c for c in self.calls if c[0] == "up"], [("up", "B"), ("up", "C")])

    def test_restores_previous_when_everything_fails(self):
        def up(n, timeout=20):
            self.calls.append(("up", n))
            return (n == "A", "back")

        nm.up = up
        nm.down = lambda n, timeout=15: (True, "ok")
        res = nm.rotate(["B", "C"], "A", attempts=2)
        self.assertFalse(res.ok)
        self.assertEqual(res.name, "A")
        self.assertIn("back on A", res.message)

    def test_empty_candidate_list_is_a_noop(self):
        res = nm.rotate([], "A")
        self.assertFalse(res.ok)
        self.assertIn("no other server", res.message)


class UpMessages(unittest.TestCase):
    def setUp(self):
        self._orig = nm._run

    def tearDown(self):
        nm._run = self._orig

    def test_already_active_counts_as_success(self):
        nm._run = fake_run(
            {("--wait", "20", "connection", "up", "DE-UDP"): (
                4, "", "Error: Connection activation failed: Connection 'DE-UDP' is already active",
            )}
        )
        ok, _msg = nm.up("DE-UDP", timeout=20)
        self.assertTrue(ok)

    def test_missing_secrets_message(self):
        nm._run = fake_run(
            {("--wait", "20", "connection", "up", "X"): (
                10, "", "Error: Connection activation failed: no valid secrets",
            )}
        )
        ok, msg = nm.up("X", timeout=20)
        self.assertFalse(ok)
        self.assertIn("no saved login", msg)

    def test_timeout_message(self):
        nm._run = fake_run(
            {("--wait", "20", "connection", "up", "X"): (
                10, "", "Error: Timeout expired (20 seconds)",
            )}
        )
        ok, msg = nm.up("X", timeout=20)
        self.assertFalse(ok)
        self.assertIn("did not answer", msg)
