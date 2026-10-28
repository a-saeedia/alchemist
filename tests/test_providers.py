"""Provider discovery tests (no network, no real binaries)."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocvpn import providers  # noqa: E402


class Catalog(unittest.TestCase):
    def test_has_openvpn_and_wireguard(self):
        ids = {p.id for p in providers.PROVIDERS}
        self.assertIn("openvpn-nm", ids)
        self.assertIn("wireguard", ids)
        self.assertIn("protonvpn", ids)

    def test_all_free(self):
        for p in providers.PROVIDERS:
            self.assertTrue(p.free, p.id)

    def test_get_unknown(self):
        self.assertIsNone(providers.get("nope"))


class InstalledDetection(unittest.TestCase):
    def test_installed_by_binary(self):
        with mock.patch("shutil.which", return_value="/usr/bin/x"):
            p = providers.get("wireguard")
            # wireguard has binaries wg/wg-quick; which returns path for first
            self.assertTrue(providers.is_installed(p))

    def test_missing_binary_and_no_flatpak(self):
        with mock.patch("shutil.which", return_value=None), mock.patch(
            "subprocess.run",
            side_effect=FileNotFoundError,
        ):
            p = providers.get("riseup")
            self.assertFalse(providers.is_installed(p))

    def test_flatpak_detection(self):
        p = providers.get("nym")
        with mock.patch("shutil.which", return_value=None), mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="net.nymtech.NymVPN\n", stderr=""),
        ):
            self.assertTrue(providers.is_installed(p))


class Launch(unittest.TestCase):
    def test_unknown(self):
        ok, msg = providers.launch("nope")
        self.assertFalse(ok)

    def test_launch_missing(self):
        with mock.patch("ocvpn.providers.is_installed", return_value=False):
            ok, msg = providers.launch("protonvpn")
        self.assertFalse(ok)
        self.assertIn("not installed", msg)


class Summary(unittest.TestCase):
    def test_summary_shape(self):
        s = providers.summary()
        self.assertIn("total", s)
        self.assertIn("installed", s)
        self.assertIn("names", s)
        self.assertEqual(s["total"], len(providers.PROVIDERS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
