import unittest
from datetime import datetime, timedelta, timezone

from quotabar.projection import MIN_RATE_PER_HOUR, WindowTracker

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
RESET = NOW + timedelta(hours=4)


def feed(tracker, readings, resets_at=RESET):
    for minutes, percent in readings:
        tracker.observe(percent, resets_at, NOW + timedelta(minutes=minutes))


class RateTests(unittest.TestCase):
    def test_a_single_reading_says_nothing(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10)])
        self.assertIsNone(tracker.rate_per_hour(NOW))

    def test_readings_too_close_together_say_nothing(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (4, 14)])
        self.assertIsNone(tracker.rate_per_hour(NOW + timedelta(minutes=4)))

    def test_the_slope_is_percent_per_hour(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])
        self.assertAlmostEqual(tracker.rate_per_hour(NOW + timedelta(minutes=30)), 30.0, places=3)

    def test_a_barely_moving_window_has_no_usable_rate(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (60, 10 + MIN_RATE_PER_HOUR / 2)])
        self.assertIsNone(tracker.rate_per_hour(NOW + timedelta(minutes=60)))

    def test_stale_readings_are_ignored(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])
        self.assertIsNone(tracker.rate_per_hour(NOW + timedelta(hours=5)))

    def test_a_new_window_starts_the_history_over(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])
        tracker.observe(3.0, RESET + timedelta(hours=5), NOW + timedelta(minutes=31))
        self.assertEqual([sample.percent for sample in tracker.samples], [3.0])

    def test_a_window_that_drops_without_a_new_reset_time_starts_over(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 40), (30, 60), (35, 2)])
        self.assertEqual([sample.percent for sample in tracker.samples], [2])

    def test_repeated_identical_readings_are_not_stored_twice(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (10, 10), (20, 10)])
        self.assertEqual(len(tracker.samples), 1)


class ExhaustionTests(unittest.TestCase):
    def test_the_arrival_time_follows_the_measured_rate(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])
        now = NOW + timedelta(minutes=30)

        # 30%/h with 75 points left is two and a half hours.
        eta = tracker.exhausted_at(25, RESET, now)
        self.assertIsNotNone(eta)
        self.assertAlmostEqual((eta - now).total_seconds() / 3600.0, 2.5, places=2)

    def test_no_arrival_time_when_the_window_resets_first(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 13)])
        now = NOW + timedelta(minutes=30)
        # 6%/h against 87 points left runs well past the reset.
        self.assertIsNone(tracker.exhausted_at(13, RESET, now))

    def test_no_arrival_time_for_a_full_window(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 90), (30, 100)])
        self.assertIsNone(tracker.exhausted_at(100, RESET, NOW + timedelta(minutes=30)))

    def test_no_arrival_time_without_a_rate(self):
        self.assertIsNone(WindowTracker().exhausted_at(20, RESET, NOW))



class IdleTests(unittest.TestCase):
    """A window that stops moving must stop predicting."""

    def test_the_rate_dilutes_while_the_window_sits_idle(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])

        at_the_end_of_the_burst = tracker.rate_per_hour(NOW + timedelta(minutes=30))
        an_hour_later = tracker.rate_per_hour(NOW + timedelta(minutes=90))

        self.assertAlmostEqual(at_the_end_of_the_burst, 30.0, places=3)
        # 15 points over 84 minutes: the span runs to now less the grace period.
        self.assertAlmostEqual(an_hour_later, 10.714, places=3)

    def test_the_prediction_disappears_once_the_rate_falls_below_the_floor(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])
        self.assertIsNotNone(tracker.exhausted_at(25, RESET, NOW + timedelta(minutes=30)))

        # Long enough idle that 15 points spread over the span is under 1%/h.
        idle = NOW + timedelta(hours=16)
        self.assertIsNone(tracker.rate_per_hour(idle))
        self.assertIsNone(tracker.exhausted_at(25, RESET + timedelta(days=1), idle))

    def test_a_burst_after_idling_measures_the_new_pace(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (120, 12), (150, 40)])
        # From the first surviving reading inside the two-hour memory to now.
        rate = tracker.rate_per_hour(NOW + timedelta(minutes=150))
        # 28 points between the two surviving readings, half an hour apart.
        self.assertAlmostEqual(rate, 56.0, places=3)


class StabilityTests(unittest.TestCase):
    """The prediction must not move on its own between quota readings."""

    def test_the_rate_holds_steady_until_a_reading_is_overdue(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])

        at_the_reading = tracker.rate_per_hour(NOW + timedelta(minutes=30))
        five_minutes_later = tracker.rate_per_hour(NOW + timedelta(minutes=35))

        self.assertAlmostEqual(at_the_reading, 30.0, places=3)
        self.assertAlmostEqual(five_minutes_later, 30.0, places=3)

    def test_the_predicted_time_does_not_creep_between_readings(self):
        tracker = WindowTracker()
        feed(tracker, [(0, 10), (30, 25)])

        first = tracker.exhausted_at(25, RESET, NOW + timedelta(minutes=30))
        later = tracker.exhausted_at(25, RESET, NOW + timedelta(minutes=35))

        self.assertIsNotNone(first)
        self.assertEqual(first, later, "the same data must predict the same moment")


if __name__ == "__main__":
    unittest.main()
