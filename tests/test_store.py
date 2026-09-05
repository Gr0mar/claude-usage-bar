import threading
import unittest
from datetime import datetime, timezone

from claude_usage_bar.limits import LimitWindow, LimitsSnapshot, SOURCE_API
from claude_usage_bar.scanner import ScanState
from claude_usage_bar.store import (
    LIMITS_INTERVAL,
    LIMITS_MAX_INTERVAL,
    LIMITS_MIN_INTERVAL,
    SPARKLINE_DAYS,
    UsageStore,
)


class StubScanner:
    root = "/nonexistent"

    def __init__(self, raises=False):
        self.raises = raises
        self.scans = 0
        self.size = 0

    def fingerprint(self):
        return (1, self.size, 0.0)

    def scan(self, state, now=None):
        self.scans += 1
        if self.raises:
            raise RuntimeError("bad log")
        return False


class StubCache:
    def __init__(self):
        self.saves = 0
        self.cleared = 0

    def load(self):
        return ScanState()

    def save(self, state):
        self.saves += 1

    def clear(self):
        self.cleared += 1


class StubProvider:
    def __init__(self, snapshots=(), raises=False):
        self.snapshots = list(snapshots)
        self.raises = raises
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if self.raises:
            raise RuntimeError("network on fire")
        return self.snapshots.pop(0) if self.snapshots else LimitsSnapshot()


def filled():
    return LimitsSnapshot(LimitWindow(21.0), LimitWindow(4.0), SOURCE_API, datetime.now(timezone.utc))


def build(provider=None, scanner=None, cache=None):
    return UsageStore(
        scanner=scanner or StubScanner(),
        cache=cache or StubCache(),
        limits_provider=provider or StubProvider(),
    )


class LimitsScheduleTests(unittest.TestCase):
    def test_a_successful_fetch_keeps_the_normal_interval(self):
        store = build(StubProvider([filled()]))
        store._fetch_limits_if_due()
        self.assertEqual(store._limits_interval, LIMITS_INTERVAL)
        store._publish()
        self.assertEqual(store.snapshot.limits.five_hour.used_percent, 21.0)

    def test_after_a_failure_the_endpoint_is_not_hit_again_until_the_interval_passes(self):
        provider = StubProvider([LimitsSnapshot()])
        store = build(provider)
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 1)

        # Half of the (already doubled) interval: still too soon.
        store._limits_checked_at -= store._limits_interval / 2
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 1)

        store._limits_checked_at -= store._limits_interval
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 2)

    def test_repeated_failures_back_off_and_cap(self):
        store = build(StubProvider())
        store._fetch_limits_if_due()
        for _ in range(10):
            store._limits_checked_at -= LIMITS_MAX_INTERVAL
            store._fetch_limits_if_due()
        self.assertEqual(store._limits_interval, LIMITS_MAX_INTERVAL)

    def test_backoff_resets_once_the_endpoint_answers_again(self):
        store = build(StubProvider([LimitsSnapshot(), filled()]))
        store._fetch_limits_if_due()
        self.assertGreater(store._limits_interval, LIMITS_INTERVAL)

        store._limits_checked_at -= LIMITS_MAX_INTERVAL
        store._fetch_limits_if_due()
        self.assertEqual(store._limits_interval, LIMITS_INTERVAL)

    def test_the_last_good_reading_survives_a_failed_poll(self):
        store = build(StubProvider([filled(), LimitsSnapshot()]))
        store._fetch_limits_if_due()
        store._limits_checked_at -= LIMITS_MAX_INTERVAL
        store._fetch_limits_if_due()
        store._publish()
        self.assertTrue(store.snapshot.limits.has_data)
        self.assertEqual(store.snapshot.limits.five_hour.used_percent, 21.0)

    def test_refresh_now_forces_a_fetch_but_respects_the_floor(self):
        provider = StubProvider([filled(), filled()])
        store = build(provider)
        store._fetch_limits_if_due()

        store.refresh_now(include_limits=True)
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 1, "the one-minute floor still applies")

        store._limits_checked_at -= LIMITS_MIN_INTERVAL
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 2)

    def test_opening_the_menu_does_not_force_a_quota_fetch(self):
        provider = StubProvider([filled(), filled()])
        store = build(provider)
        store._fetch_limits_if_due()

        store.refresh_now()
        store._limits_checked_at -= LIMITS_MIN_INTERVAL
        store._fetch_limits_if_due()
        self.assertEqual(provider.calls, 1, "only the scan is forced, not the endpoint")


class SnapshotTests(unittest.TestCase):
    def test_the_snapshot_carries_a_full_sparkline(self):
        store = build()
        self.assertEqual(len(store.snapshot.sparkline), SPARKLINE_DAYS)

    def test_setting_a_range_republishes_immediately(self):
        store = build()
        seen = []
        store._on_update = lambda: seen.append(store.snapshot.range_days)
        store.set_range(7)
        self.assertEqual(store.snapshot.range_days, 7)
        self.assertEqual(seen, [7])

    def test_a_stale_quota_reading_is_marked_stale(self):
        store = build(StubProvider([filled()]))
        store._fetch_limits_if_due()
        store._publish()
        self.assertFalse(store.snapshot.limits_are_stale())

        aged = LimitsSnapshot(
            LimitWindow(21.0), None, SOURCE_API,
            datetime.now(timezone.utc).replace(year=2020),
        )
        store._limits = aged
        store._publish()
        self.assertTrue(store.snapshot.limits_are_stale())


class LoopTests(unittest.TestCase):
    def run_one_tick(self, store):
        store.refresh_once()

    def test_a_provider_that_raises_does_not_kill_the_loop(self):
        store = build(StubProvider(raises=True))
        self.run_one_tick(store)
        self.assertIsNotNone(store.snapshot.error)

    def test_a_scanner_that_raises_does_not_kill_the_loop(self):
        scanner = StubScanner(raises=True)
        store = build(scanner=scanner)
        self.run_one_tick(store)
        self.assertIsNotNone(store.snapshot.error)
        self.assertFalse(store.snapshot.scanning, "the spinner must not stick on")

    def test_a_recovered_tick_clears_the_error(self):
        scanner = StubScanner(raises=True)
        store = build(scanner=scanner)
        self.run_one_tick(store)
        self.assertIsNotNone(store.snapshot.error)

        scanner.raises = False
        self.run_one_tick(store)
        self.assertIsNone(store.snapshot.error)

    def test_rescanning_from_scratch_clears_the_cache_and_rereads(self):
        cache = StubCache()
        scanner = StubScanner()
        store = build(scanner=scanner, cache=cache)
        store.rescan_from_scratch()
        self.run_one_tick(store)

        self.assertEqual(cache.cleared, 1)
        self.assertEqual(scanner.scans, 1)
        self.assertEqual(store.snapshot.summary.cost, 0)

    def test_start_publishes_updates_and_stop_ends_the_thread(self):
        store = build()
        updates = threading.Event()
        store.start(updates.set)
        self.assertTrue(updates.wait(timeout=2.0), "the loop published nothing")

        store.stop()
        self.assertEqual(
            [thread for thread in threading.enumerate() if thread.name == "usage-scan"],
            [],
            "the scan thread outlived stop()",
        )


if __name__ == "__main__":
    unittest.main()
