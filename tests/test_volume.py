"""Unit tests for the pure volume math."""

from __future__ import annotations

import unittest

from appvol.volume import DOWN, UP, absolute, changed, peak, percent, target_channels

STEP = 0.05
MAX = 1.0


class TargetChannelsTests(unittest.TestCase):
    def test_step_up_keeps_balance(self) -> None:
        result = target_channels([0.5, 0.25], UP, STEP, MAX)
        self.assertAlmostEqual(result[0], 0.55)
        self.assertAlmostEqual(result[1], 0.275)

    def test_step_up_is_relative_to_peak(self) -> None:
        self.assertEqual(target_channels([0.25, 0.25], UP, 0.05, MAX), [0.3, 0.3])

    def test_step_up_is_clamped_at_max(self) -> None:
        self.assertEqual(target_channels([0.98, 0.98], UP, STEP, MAX), [1.0, 1.0])

    def test_max_volume_can_exceed_one_hundred_percent(self) -> None:
        result = target_channels([1.4], UP, 0.05, 1.5)
        self.assertAlmostEqual(result[0], 1.45)

    def test_step_down_reaches_zero_and_stops(self) -> None:
        self.assertEqual(target_channels([0.03, 0.03], DOWN, STEP, MAX), [0.0, 0.0])
        self.assertEqual(target_channels([0.0, 0.0], DOWN, STEP, MAX), [0.0, 0.0])

    def test_all_silent_channels_lift_evenly(self) -> None:
        self.assertEqual(target_channels([0.0, 0.0], UP, 0.05, MAX), [0.05, 0.05])

    def test_step_down_from_balance(self) -> None:
        result = target_channels([0.5, 0.25], DOWN, 0.1, MAX)
        self.assertAlmostEqual(result[0], 0.4)
        self.assertAlmostEqual(result[1], 0.2)

    def test_unknown_direction_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            target_channels([0.5], "sideways", STEP, MAX)

    def test_empty_channels(self) -> None:
        self.assertEqual(target_channels([], UP, STEP, MAX), [])


class AbsoluteTests(unittest.TestCase):
    def test_absolute_moves_the_peak_and_keeps_the_balance(self) -> None:
        result = absolute([0.5, 0.25], 0.6, MAX)
        self.assertAlmostEqual(result[0], 0.6)
        self.assertAlmostEqual(result[1], 0.3)

    def test_absolute_is_clamped_at_max(self) -> None:
        self.assertEqual(absolute([0.5], 1.5, MAX), [1.0])

    def test_absolute_allows_more_than_one_hundred_percent(self) -> None:
        self.assertEqual(absolute([0.5], 1.2, 1.5), [1.2])

    def test_absolute_lifts_silent_channels_evenly(self) -> None:
        self.assertEqual(absolute([0.0, 0.0], 0.4, MAX), [0.4, 0.4])

    def test_absolute_to_zero_silences_everything(self) -> None:
        self.assertEqual(absolute([0.7, 0.3], 0.0, MAX), [0.0, 0.0])

    def test_absolute_rejects_a_negative_value(self) -> None:
        self.assertEqual(absolute([0.5], -1.0, MAX), [0.0])

    def test_absolute_empty_channels(self) -> None:
        self.assertEqual(absolute([], 0.5, MAX), [])


class HelpersTests(unittest.TestCase):
    def test_peak_and_percent(self) -> None:
        self.assertAlmostEqual(peak([0.25, 0.5]), 0.5)
        self.assertEqual(percent([0.25, 0.5]), 50)
        self.assertEqual(percent([]), 0)

    def test_changed_uses_epsilon(self) -> None:
        self.assertFalse(changed([0.5, 0.5], [0.5, 0.5]))
        self.assertTrue(changed([0.5], [0.6]))
        self.assertTrue(changed([0.5], [0.5, 0.5]))


if __name__ == "__main__":
    unittest.main()
