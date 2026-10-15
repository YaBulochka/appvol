"""Unit tests for configuration parsing and writing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from appvol.config import Config, dumps, load, parse, save


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


class ConfigWriteTests(unittest.TestCase):
    """The daemon writes the file when the window changes the global step."""

    def test_a_configuration_round_trips(self) -> None:
        config = Config(step=2.5, max_volume=120.0, osd=False, profile_idle_timeout=60.0)
        self.assertEqual(parse(dumps(config)), config)

    def test_every_key_is_written(self) -> None:
        text = dumps(Config())
        self.assertIn("step = 5", text)
        self.assertIn("max_volume = 100", text)
        self.assertIn("osd = true", text)
        self.assertIn("profile_idle_timeout = 300", text)

    def test_the_kwin_script_survives(self) -> None:
        config = Config(kwin_script="/opt/appvol/appvol.js")
        self.assertEqual(parse(dumps(config)), config)

    def test_save_replaces_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "appvol" / "config.toml"
            save(Config(step=3.0), path)
            self.assertEqual(load(path).step, 3.0)
            save(Config(step=7.0), path)
            self.assertEqual(load(path).step, 7.0)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_a_missing_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "config.toml"
            save(Config(), path)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
