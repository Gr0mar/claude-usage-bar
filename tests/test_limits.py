import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from claude_usage_bar.limits import (
    SOURCE_STATUSLINE,
    SOURCE_UNAVAILABLE,
    ChainedLimitsProvider,
    LimitWindow,
    LimitsSnapshot,
    OAuthLimitsProvider,
    StatuslineLimitsProvider,
    decode_windows,
    read_access_token,
)


class EmptyProvider:
    def fetch(self):
        return LimitsSnapshot()


class FilledProvider:
    def fetch(self):
        return LimitsSnapshot(LimitWindow(12.0), None, SOURCE_STATUSLINE, datetime.now(timezone.utc))


class DecoderTests(unittest.TestCase):
    def test_reads_the_usage_endpoint_shape(self):
        # Shape observed live: percentages plus ISO 8601 reset timestamps.
        payload = {
            "five_hour": {"utilization": 21.0, "resets_at": "2026-09-05T17:29:59.977965+00:00"},
            "seven_day": {"utilization": 4.0, "resets_at": "2026-09-07T17:59:59.977996+00:00"},
        }
        five_hour, seven_day = decode_windows(payload)
        self.assertEqual(five_hour.used_percent, 21.0)
        self.assertEqual(seven_day.used_percent, 4.0)
        self.assertEqual(five_hour.resets_at.year, 2026)
        self.assertEqual(five_hour.resets_at.hour, 17)

    def test_reads_the_statusline_shape(self):
        payload = {"rate_limits": {
            "five_hour": {"used_percentage": 42.5, "resets_at": 1788647895},
            "seven_day": {"used_percentage": 70, "resets_at": 1789647895},
        }}
        five_hour, seven_day = decode_windows(payload)
        self.assertEqual(five_hour.used_percent, 42.5)
        self.assertEqual(seven_day.used_percent, 70)
        self.assertEqual(five_hour.resets_at, datetime.fromtimestamp(1788647895, tz=timezone.utc))

    def test_finds_windows_nested_anywhere(self):
        payload = {"data": {"unifiedWindows": {"fiveHour": {"utilization": 8, "resetsAt": 1788647895}}}}
        five_hour, seven_day = decode_windows(payload)
        self.assertEqual(five_hour.used_percent, 8)
        self.assertIsNone(seven_day)

    def test_ignores_payloads_without_windows(self):
        self.assertEqual(decode_windows({"account": {"plan": "max"}}), (None, None))
        self.assertEqual(decode_windows({"five_hour": {"utilization": None}}), (None, None))
        self.assertEqual(decode_windows([]), (None, None))

    def test_a_numeric_value_is_read_as_a_percentage_not_a_fraction(self):
        # Both payloads this app consumes report 0-100; pinning that here so a future
        # fraction-shaped source is caught by a failing test rather than by a 0% badge.
        five_hour, _ = decode_windows({"five_hour": {"utilization": 21.0}})
        self.assertEqual(five_hour.used_percent, 21.0)

        low, _ = decode_windows({"five_hour": {"utilization": 0.21}})
        self.assertEqual(low.used_percent, 0.21)

    def test_a_string_percentage_is_rejected_rather_than_guessed(self):
        self.assertEqual(decode_windows({"five_hour": {"utilization": "21.0"}}), (None, None))

    def test_a_boolean_is_not_mistaken_for_a_number(self):
        self.assertEqual(decode_windows({"five_hour": {"utilization": True}}), (None, None))

    def test_percentages_are_clamped(self):
        self.assertEqual(LimitWindow(140).used_percent, 100)
        self.assertEqual(LimitWindow(-5).used_percent, 0)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump({"rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": 1}}}, file)

    def tearDown(self):
        os.remove(self.path)

    def test_statusline_provider_reads_a_fresh_file(self):
        snapshot = StatuslineLimitsProvider(self.path, timedelta(hours=1)).fetch()
        self.assertEqual(snapshot.source, SOURCE_STATUSLINE)
        self.assertEqual(snapshot.five_hour.used_percent, 10)

    def test_statusline_provider_ignores_a_file_older_than_the_window(self):
        age = datetime.now(timezone.utc).timestamp() - timedelta(hours=7).total_seconds()
        os.utime(self.path, (age, age))
        snapshot = StatuslineLimitsProvider(self.path).fetch()
        self.assertEqual(snapshot.source, SOURCE_UNAVAILABLE)

    def test_statusline_provider_accepts_a_file_inside_the_window(self):
        age = datetime.now(timezone.utc).timestamp() - timedelta(hours=5).total_seconds()
        os.utime(self.path, (age, age))
        snapshot = StatuslineLimitsProvider(self.path).fetch()
        self.assertEqual(snapshot.source, SOURCE_STATUSLINE)

    def test_statusline_provider_tolerates_a_missing_file(self):
        snapshot = StatuslineLimitsProvider("/nonexistent/limits.json").fetch()
        self.assertEqual(snapshot.source, SOURCE_UNAVAILABLE)
        self.assertFalse(snapshot.has_data)

    def test_the_chain_falls_through_to_the_next_provider(self):
        snapshot = ChainedLimitsProvider([EmptyProvider(), FilledProvider()]).fetch()
        self.assertEqual(snapshot.source, SOURCE_STATUSLINE)
        self.assertEqual(snapshot.five_hour.used_percent, 12)

    def test_the_chain_reports_unavailable_when_nothing_answers(self):
        self.assertFalse(ChainedLimitsProvider([EmptyProvider()]).fetch().has_data)


class FakeResult:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class TokenTests(unittest.TestCase):
    """The keychain is not touched: a stub runner stands in for /usr/bin/security."""

    @staticmethod
    def runner_returning(payload):
        return lambda *args, **kwargs: FakeResult(json.dumps(payload))

    def test_a_live_token_is_returned(self):
        future_ms = (datetime.now(timezone.utc) + timedelta(days=1)).timestamp() * 1000
        runner = self.runner_returning({"claudeAiOauth": {"accessToken": "t", "expiresAt": future_ms}})
        self.assertEqual(read_access_token(runner), "t")

    def test_an_expired_token_is_not_used(self):
        # expiresAt is milliseconds; reading it as seconds would make every token look live.
        past_ms = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
        runner = self.runner_returning({"claudeAiOauth": {"accessToken": "t", "expiresAt": past_ms}})
        self.assertIsNone(read_access_token(runner))

    def test_a_token_without_an_expiry_is_tried_anyway(self):
        runner = self.runner_returning({"claudeAiOauth": {"accessToken": "t"}})
        self.assertEqual(read_access_token(runner), "t")

    def test_a_failed_or_empty_lookup_yields_nothing(self):
        cases = {
            "no keychain item": lambda *a, **k: FakeResult("", returncode=1),
            "not json": lambda *a, **k: FakeResult("not json"),
            "no oauth section": self.runner_returning({"mcpOAuth": {}}),
            "security missing": self.fail_runner,
        }
        for label, runner in cases.items():
            with self.subTest(label):
                self.assertIsNone(read_access_token(runner))

    @staticmethod
    def fail_runner(*args, **kwargs):
        raise OSError("security not found")

    def test_the_provider_makes_no_request_without_a_token(self):
        provider = OAuthLimitsProvider(token_reader=lambda: None)
        self.assertEqual(provider.fetch().source, SOURCE_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
