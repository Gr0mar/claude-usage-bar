import unittest
from datetime import datetime, timedelta, timezone

from claude_usage_bar.alerts import QuotaAlerts

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
WINDOW = NOW + timedelta(hours=3)


class QuotaAlertTests(unittest.TestCase):
    def setUp(self):
        self.alerts = QuotaAlerts()

    def test_nothing_below_the_first_threshold(self):
        self.assertIsNone(self.alerts.check(79.0, WINDOW))

    def test_the_first_crossing_fires_once(self):
        first = self.alerts.check(81.0, WINDOW)
        self.assertIsNotNone(first)
        self.assertEqual(first.threshold, 80.0)
        self.assertIsNone(self.alerts.check(82.0, WINDOW), "same window, same threshold")

    def test_the_next_threshold_still_fires(self):
        self.alerts.check(81.0, WINDOW)
        second = self.alerts.check(96.0, WINDOW)
        self.assertIsNotNone(second)
        self.assertEqual(second.threshold, 95.0)

    def test_jumping_past_both_thresholds_notifies_once(self):
        alert = self.alerts.check(97.0, WINDOW)
        self.assertEqual(alert.threshold, 95.0)
        self.assertIsNone(self.alerts.check(98.0, WINDOW))

    def test_a_new_window_arms_the_thresholds_again(self):
        self.alerts.check(81.0, WINDOW)
        later = WINDOW + timedelta(hours=5)
        self.assertIsNotNone(self.alerts.check(81.0, later))

    def test_a_missing_reading_is_ignored(self):
        self.assertIsNone(self.alerts.check(None, WINDOW))

    def test_the_body_names_the_projected_time_when_there_is_one(self):
        alert = self.alerts.check(81.0, WINDOW, exhausted_at=NOW + timedelta(hours=1))
        self.assertIn("Full around", alert.body)

    def test_the_body_falls_back_to_the_reset_countdown(self):
        alert = self.alerts.check(81.0, WINDOW, now=NOW)
        self.assertIn("Resets in", alert.body)

    def test_disabled_alerts_stay_silent_but_still_track_the_window(self):
        alerts = QuotaAlerts(enabled=False)
        self.assertIsNone(alerts.check(81.0, WINDOW))

        alerts.enabled = True
        self.assertIsNone(alerts.check(82.0, WINDOW), "80 was passed while off")
        self.assertIsNotNone(alerts.check(96.0, WINDOW), "95 is new")


if __name__ == "__main__":
    unittest.main()
