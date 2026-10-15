"""Unit tests for configuration parsing."""

from __future__ import annotations

import unittest

from appvol.config import Config, parse


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(parse(""), Config())

    def test_values(self) -> None:
        config = parse('step = 2.5\nmax_volume = 150\nosd = false\n')
        self.assertEqual(config.step, 2.5)
        self.assertEqual(config.max_volume, 150.0)
        self.assertFalse(config.osd)

    def test_invalid_step_falls_back(self) -> None:
        self.assertEqual(parse('step = "loud"').step, Config().step)
        self.assertEqual(parse("step = -1").step, Config().step)

    def test_max_volume_is_clamped(self) -> None:
        self.assertEqual(parse("max_volume = 400").max_volume, 150.0)

    def test_invalid_osd_falls_back(self) -> None:
        self.assertTrue(parse('osd = "yes"').osd)

    def test_profile_idle_timeout(self) -> None:
        self.assertEqual(Config().profile_idle_timeout, 300.0)
        self.assertEqual(parse("profile_idle_timeout = 60").profile_idle_timeout, 60.0)

    def test_a_zero_timeout_disables_the_return_to_active(self) -> None:
        self.assertEqual(parse("profile_idle_timeout = 0").profile_idle_timeout, 0.0)
        self.assertEqual(parse("profile_idle_timeout = -5").profile_idle_timeout, 0.0)

    def test_invalid_profile_idle_timeout_falls_back(self) -> None:
        self.assertEqual(parse('profile_idle_timeout = "soon"').profile_idle_timeout, 300.0)

    def test_broken_toml_falls_back(self) -> None:
        self.assertEqual(parse("step = "), Config())

    def test_fractions(self) -> None:
        config = parse("step = 5\nmax_volume = 120\n")
        self.assertAlmostEqual(config.step_fraction, 0.05)
        self.assertAlmostEqual(config.max_volume_fraction, 1.2)


if __name__ == "__main__":
    unittest.main()
