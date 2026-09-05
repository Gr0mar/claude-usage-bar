import unittest
from datetime import datetime, timedelta, timezone

from claude_usage_bar import formatting as fmt
from claude_usage_bar.limits import LimitWindow, LimitsSnapshot


class FormattingTests(unittest.TestCase):
    def test_money_scales_precision_to_size(self):
        self.assertEqual(fmt.money(1234.5), "$1234")
        self.assertEqual(fmt.money(12.34), "$12.3")
        self.assertEqual(fmt.money(1.234), "$1.23")
        self.assertEqual(fmt.money(0.004), "<$0.01")
        self.assertEqual(fmt.money(0), "$0.00")

    def test_tokens_use_short_units(self):
        self.assertEqual(fmt.tokens(950), "950")
        self.assertEqual(fmt.tokens(12_300), "12.3k")
        self.assertEqual(fmt.tokens(4_500_000), "4.5M")
        self.assertEqual(fmt.tokens(2_100_000_000), "2.1B")

    def test_countdown_reads_as_a_sentence(self):
        now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fmt.countdown(now + timedelta(minutes=45), now), "resets in 45m")
        self.assertEqual(fmt.countdown(now + timedelta(hours=2, minutes=14), now), "resets in 2h 14m")
        self.assertEqual(fmt.countdown(now + timedelta(days=2, hours=1), now), "resets in 2d 1h")
        self.assertEqual(fmt.countdown(now - timedelta(minutes=1), now), "resetting")
        self.assertIsNone(fmt.countdown(None, now))

    def test_elapsed(self):
        self.assertEqual(fmt.elapsed(timedelta(minutes=8)), "8m")
        self.assertEqual(fmt.elapsed(timedelta(hours=1, minutes=5)), "1h 5m")


class MenuBarLabelTests(unittest.TestCase):
    QUOTA = LimitsSnapshot(LimitWindow(21.0), LimitWindow(4.0))
    NO_QUOTA = LimitsSnapshot()

    def test_quota_metrics_show_their_window(self):
        self.assertEqual(fmt.menu_bar_label("five_hour", self.QUOTA, 12.0), "21%")
        self.assertEqual(fmt.menu_bar_label("seven_day", self.QUOTA, 12.0), "4%")

    def test_the_label_falls_back_to_todays_cost_without_a_quota_window(self):
        # What every user sees while the usage endpoint is rate-limiting.
        self.assertEqual(fmt.menu_bar_label("five_hour", self.NO_QUOTA, 12.34), "$12.3")
        self.assertEqual(fmt.menu_bar_label("seven_day", self.NO_QUOTA, 12.34), "$12.3")

    def test_the_cost_metric_ignores_the_quota(self):
        self.assertEqual(fmt.menu_bar_label("today", self.QUOTA, 12.34), "$12.3")

    def test_the_icon_only_metric_has_no_text(self):
        self.assertEqual(fmt.menu_bar_label("icon", self.QUOTA, 12.34), "")


if __name__ == "__main__":
    unittest.main()
