import os
import time
import unittest
from datetime import datetime, timedelta, timezone

from quotabar import live
from quotabar.aggregate import UsageAggregate, day_keys, summarize
from quotabar.parser import UsageEvent
from quotabar.tokens import TokenCounts

MILLION_INPUT = TokenCounts(input=1_000_000)
#: A fixed instant, so a day rolling over mid-test cannot change an assertion.
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def sample(days_ago=0, model="claude-opus-5", project="acme-web", session="s1", tokens=MILLION_INPUT,
           identity=None, at=None):
    moment = at or (NOW - timedelta(days=days_ago))
    return UsageEvent(
        id=identity or "{}-{}-{}".format(project, model, moment.timestamp()),
        timestamp=moment,
        model=model,
        project=project,
        session_id=session,
        tokens=tokens,
    )


class SummaryTests(unittest.TestCase):
    def test_summary_respects_the_day_window(self):
        aggregate = UsageAggregate()
        for days in (0, 3, 20):
            aggregate.add(sample(days_ago=days))

        self.assertAlmostEqual(summarize(aggregate, 1, NOW).cost, 5, places=3)
        self.assertAlmostEqual(summarize(aggregate, 7, NOW).cost, 10, places=3)
        self.assertAlmostEqual(summarize(aggregate, 30, NOW).cost, 15, places=3)

    def test_project_cost_is_prorated_by_tokens(self):
        aggregate = UsageAggregate()
        aggregate.add(sample(project="acme-web"))
        aggregate.add(sample(project="payments-api"))

        summary = summarize(aggregate, 1, NOW)
        self.assertEqual(len(summary.by_project), 2)
        self.assertAlmostEqual(summary.by_project[0].cost, 5, places=3)
        self.assertAlmostEqual(sum(item.cost for item in summary.by_project), summary.cost, places=6)

    def test_an_unpriced_model_contributes_tokens_but_no_cost(self):
        aggregate = UsageAggregate()
        aggregate.add(sample(model="claude-unreleased-9"))

        summary = summarize(aggregate, 1, NOW)
        self.assertEqual(summary.cost, 0)
        self.assertEqual(summary.tokens.total, 1_000_000)
        self.assertTrue(summary.by_model[0].unpriced)

    def test_daily_costs_cover_every_day_in_range(self):
        aggregate = UsageAggregate()
        aggregate.add(sample(days_ago=2))

        summary = summarize(aggregate, 7, NOW)
        self.assertEqual(len(summary.daily_costs), 7)
        self.assertEqual(summary.daily_costs[-1][1], 0)
        self.assertAlmostEqual(summary.daily_costs[4][1], 5, places=3)

    def test_cache_savings_roll_up_across_models(self):
        aggregate = UsageAggregate()
        aggregate.add(sample(tokens=TokenCounts(cache_read=1_000_000)))
        aggregate.add(sample(model="claude-haiku-4-5", tokens=TokenCounts(cache_read=1_000_000)))

        self.assertAlmostEqual(summarize(aggregate, 1).cache_savings, 4.5 + 0.9, places=3)

    def test_aggregate_survives_a_dict_round_trip(self):
        aggregate = UsageAggregate()
        aggregate.add(sample())
        revived = UsageAggregate.from_dict(aggregate.to_dict())
        self.assertEqual(revived.to_dict(), aggregate.to_dict())


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW

    def test_live_session_covers_only_the_running_session(self):
        events = [
            sample(session="s0", project="old", at=self.now - timedelta(minutes=10), identity="a"),
            sample(session="s1", at=self.now - timedelta(minutes=2), identity="b"),
            sample(session="s1", at=self.now - timedelta(minutes=1), identity="c"),
        ]
        session = live.current_session(events, self.now)

        self.assertIsNotNone(session)
        self.assertEqual(session.project, "acme-web")
        self.assertEqual(session.tokens.input, 2_000_000)
        self.assertAlmostEqual(session.cost, 10, places=3)
        self.assertAlmostEqual(session.duration.total_seconds(), 60, places=0)

    def test_no_live_session_when_the_last_event_is_old(self):
        events = [sample(at=self.now - timedelta(hours=1), identity="a")]
        self.assertIsNone(live.current_session(events, self.now))

    def test_no_live_session_without_events(self):
        self.assertIsNone(live.current_session([], self.now))

    def test_burn_rate_scales_the_window_to_an_hour(self):
        events = [sample(at=self.now - timedelta(seconds=100), identity="a")]
        rate = live.burn_rate(events, window=timedelta(minutes=30), now=self.now)
        self.assertAlmostEqual(rate, 10, places=3)

    def test_rolling_window_counts_only_events_inside_it(self):
        events = [
            sample(at=self.now - timedelta(hours=6), tokens=TokenCounts(input=100), identity="a"),
            sample(at=self.now - timedelta(hours=1), tokens=TokenCounts(input=200), identity="b"),
        ]
        counted = live.tokens_in_window(events, timedelta(hours=5), self.now)
        self.assertEqual(counted.total, 200)


if __name__ == "__main__":
    unittest.main()


class DayKeyTests(unittest.TestCase):
    """Day bucketing is local-calendar, and the sharp edge is a DST transition."""

    def setUp(self):
        self._previous_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Prague"
        time.tzset()

    def tearDown(self):
        if self._previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._previous_tz
        time.tzset()

    def test_day_keys_span_consecutive_local_days_across_a_dst_shift(self):
        # Local time 2026-03-30 00:30, just after Prague springs forward.
        now = datetime(2026, 3, 29, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(
            day_keys(4, now),
            ["2026-03-27", "2026-03-28", "2026-03-29", "2026-03-30"],
        )

    def test_spend_on_the_dst_day_still_counts_towards_the_week(self):
        now = datetime(2026, 3, 29, 22, 30, tzinfo=timezone.utc)
        aggregate = UsageAggregate()
        aggregate.add(sample(at=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)))

        self.assertAlmostEqual(summarize(aggregate, 7, now).cost, 5, places=3)

    def test_pruning_keeps_only_the_named_days(self):
        now = datetime(2026, 3, 29, 22, 30, tzinfo=timezone.utc)
        aggregate = UsageAggregate()
        aggregate.add(sample(at=now - timedelta(days=1)))
        aggregate.add(sample(at=now - timedelta(days=40)))

        self.assertTrue(aggregate.prune(day_keys(7, now)))
        self.assertEqual(len(aggregate.by_day_model), 1)
        self.assertFalse(aggregate.prune(day_keys(7, now)), "nothing left to remove")


class ProrationTests(unittest.TestCase):
    def test_a_project_whose_only_model_is_unpriced_is_charged_nothing(self):
        now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        aggregate = UsageAggregate()
        aggregate.add(sample(project="priced", model="claude-opus-5", at=now))
        aggregate.add(sample(project="free", model="claude-unreleased-9", at=now))

        summary = summarize(aggregate, 1, now)
        by_project = {slice_.name: slice_.cost for slice_ in summary.by_project}
        self.assertAlmostEqual(by_project["priced"], 5.0, places=3)
        self.assertAlmostEqual(by_project["free"], 0.0, places=3)
        self.assertAlmostEqual(sum(by_project.values()), summary.cost, places=6)
