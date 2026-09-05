import threading
import unittest
from datetime import datetime, timedelta, timezone

from quotabar.limits import LimitWindow, LimitsSnapshot, SOURCE_API
from quotabar.scanner import ScanState
from quotabar.store import (
    CACHE_INTERVAL,
    LIMITS_INTERVAL,
    LIMITS_MAX_INTERVAL,
    LIMITS_MIN_INTERVAL,
    SPARKLINE_DAYS,
    UsageStore,
)


class StubScanner:
    root = "/nonexistent"

    def __init__(self, raises=False, changes=False):
        self.raises = raises
        self.changes = changes
        self.scans = 0
        self.size = 0

    def fingerprint(self):
        return (1, self.size, 0.0)

    def scan(self, state, now=None):
        self.scans += 1
        if self.raises:
            raise RuntimeError("bad log")
        # A changing scanner also moves the fingerprint, as a real one would.
        if self.changes:
            self.size += 1
        return self.changes


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


def filled(percent=21.0, resets_at=None, fetched_at=None):
    return LimitsSnapshot(
        LimitWindow(percent, resets_at),
        LimitWindow(4.0, resets_at),
        SOURCE_API,
        fetched_at or datetime.now(timezone.utc),
    )


class FakeClock:
    """A monotonic clock the test drives, so the polling schedule is observable."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def build(provider=None, scanner=None, cache=None, clock=None):
    return UsageStore(
        scanner=scanner or StubScanner(),
        cache=cache or StubCache(),
        limits_provider=provider or StubProvider(),
        clock=clock or FakeClock(),
    )


class LimitsScheduleTests(unittest.TestCase):
    def test_a_successful_fetch_keeps_the_normal_interval(self):
        store = build(StubProvider([filled()]))
        store.refresh_once()
        self.assertEqual(store._limits_interval, LIMITS_INTERVAL)
        self.assertEqual(store.snapshot.limits.five_hour.used_percent, 21.0)

    def test_after_a_failure_the_endpoint_is_not_hit_again_until_the_interval_passes(self):
        clock = FakeClock()
        provider = StubProvider([LimitsSnapshot()])
        store = build(provider, clock=clock)
        store.refresh_once()
        self.assertEqual(provider.calls, 1)

        clock.advance(LIMITS_INTERVAL)  # the failure doubled the interval
        store.refresh_once()
        self.assertEqual(provider.calls, 1, "still inside the backed-off interval")

        clock.advance(LIMITS_INTERVAL + 1)
        store.refresh_once()
        self.assertEqual(provider.calls, 2)

    def test_repeated_failures_back_off_and_cap(self):
        clock = FakeClock()
        store = build(StubProvider(), clock=clock)
        for _ in range(10):
            store.refresh_once()
            clock.advance(LIMITS_MAX_INTERVAL)
        self.assertEqual(store._limits_interval, LIMITS_MAX_INTERVAL)

    def test_backoff_resets_once_the_endpoint_answers_again(self):
        clock = FakeClock()
        store = build(StubProvider([LimitsSnapshot(), filled()]), clock=clock)
        store.refresh_once()
        self.assertGreater(store._limits_interval, LIMITS_INTERVAL)

        clock.advance(LIMITS_MAX_INTERVAL)
        store.refresh_once()
        self.assertEqual(store._limits_interval, LIMITS_INTERVAL)

    def test_the_last_good_reading_survives_a_failed_poll(self):
        clock = FakeClock()
        store = build(StubProvider([filled(), LimitsSnapshot()]), clock=clock)
        store.refresh_once()
        clock.advance(LIMITS_MAX_INTERVAL)
        store.refresh_once()
        self.assertTrue(store.snapshot.limits.has_data)
        self.assertEqual(store.snapshot.limits.five_hour.used_percent, 21.0)

    def test_refresh_now_forces_a_fetch_but_respects_the_floor(self):
        clock = FakeClock()
        provider = StubProvider([filled(), filled()])
        store = build(provider, clock=clock)
        store.refresh_once()

        store.refresh_now(include_limits=True)
        clock.advance(LIMITS_MIN_INTERVAL / 2)
        store.refresh_once()
        self.assertEqual(provider.calls, 1, "the one-minute floor still applies")

        clock.advance(LIMITS_MIN_INTERVAL)
        store.refresh_once()
        self.assertEqual(provider.calls, 2)

    def test_opening_the_menu_does_not_force_a_quota_fetch(self):
        clock = FakeClock()
        provider = StubProvider([filled(), filled()])
        store = build(provider, clock=clock)
        store.refresh_once()

        store.refresh_now()
        clock.advance(LIMITS_MIN_INTERVAL * 2)
        store.refresh_once()
        self.assertEqual(provider.calls, 1, "only the scan is forced, not the endpoint")


class ProjectionTests(unittest.TestCase):
    """The published snapshot must carry the arrival time the panel draws."""

    def test_two_readings_of_a_moving_window_produce_an_eta(self):
        now = datetime.now(timezone.utc)
        reset = now + timedelta(hours=4)
        clock = FakeClock()
        provider = StubProvider([
            filled(percent=10.0, resets_at=reset, fetched_at=now - timedelta(minutes=30)),
            filled(percent=40.0, resets_at=reset, fetched_at=now),
        ])
        store = build(provider, clock=clock)

        store.refresh_once()
        self.assertIsNone(store.snapshot.five_hour_eta, "one reading says nothing")

        clock.advance(LIMITS_INTERVAL + 1)
        store.refresh_once()

        eta = store.snapshot.five_hour_eta
        self.assertIsNotNone(eta, "60%/h against 60 points left lands an hour out")
        self.assertLess(eta, reset)

    def test_a_still_window_produces_no_eta(self):
        now = datetime.now(timezone.utc)
        reset = now + timedelta(hours=4)
        clock = FakeClock()
        provider = StubProvider([
            filled(percent=10.0, resets_at=reset, fetched_at=now - timedelta(minutes=30)),
            filled(percent=10.0, resets_at=reset, fetched_at=now),
        ])
        store = build(provider, clock=clock)

        store.refresh_once()
        clock.advance(LIMITS_INTERVAL + 1)
        store.refresh_once()

        self.assertIsNone(store.snapshot.five_hour_eta)


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
        store.refresh_once()
        self.assertFalse(store.snapshot.limits_are_stale())

        aged = LimitsSnapshot(
            LimitWindow(21.0), None, SOURCE_API,
            datetime.now(timezone.utc).replace(year=2020),
        )
        store._limits = aged
        store._publish()
        self.assertTrue(store.snapshot.limits_are_stale())


class CacheWriteTests(unittest.TestCase):
    """The cache is megabytes; a busy session must not rewrite it every tick."""

    def test_the_cache_is_written_at_most_once_an_interval(self):
        clock = FakeClock()
        cache = StubCache()
        store = build(scanner=StubScanner(changes=True), cache=cache, clock=clock)

        store.refresh_once()
        self.assertEqual(cache.saves, 1)

        clock.advance(CACHE_INTERVAL / 2)
        store.refresh_once()
        self.assertEqual(cache.saves, 1, "still inside the write interval")

        clock.advance(CACHE_INTERVAL)
        store.refresh_once()
        self.assertEqual(cache.saves, 2)

    def test_an_unchanged_scan_writes_nothing(self):
        cache = StubCache()
        store = build(scanner=StubScanner(changes=False), cache=cache)
        store.refresh_once()
        store.refresh_once()
        self.assertEqual(cache.saves, 0)

    def test_quitting_flushes_a_pending_write(self):
        clock = FakeClock()
        cache = StubCache()
        store = build(scanner=StubScanner(changes=True), cache=cache, clock=clock)
        store.refresh_once()

        clock.advance(1)
        store.refresh_once()
        self.assertEqual(cache.saves, 1, "throttled")

        store.stop()
        self.assertEqual(cache.saves, 2, "the pending state is flushed on quit")


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
