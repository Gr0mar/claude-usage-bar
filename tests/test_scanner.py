import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from claude_usage_bar.aggregate import summarize
from claude_usage_bar.scanner import LogScanner, ScanState, StateCache


def log_line(identity, tokens, timestamp="2026-09-05T10:00:00.000Z", cwd="/Users/x/code/acme-web"):
    return (
        '{"type":"assistant","timestamp":"%s","requestId":"req_%s","sessionId":"s1",'
        '"cwd":"%s","message":{"id":"msg_%s","model":"claude-opus-5",'
        '"usage":{"input_tokens":%d,"output_tokens":0}}}\n'
    ) % (timestamp, identity, cwd, identity, tokens)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="usage-bar-tests-")
        self.project_dir = os.path.join(self.root, "-Users-x-code-acme-web")
        os.makedirs(self.project_dir)
        self.log_path = os.path.join(self.project_dir, "session.jsonl")
        self.scanner = LogScanner(root=self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, text, mode="w"):
        with open(self.log_path, mode, encoding="utf-8") as handle:
            handle.write(text)
        # Coarse mtime resolution would otherwise hide a same-size rewrite.
        stat = os.stat(self.log_path)
        os.utime(self.log_path, (stat.st_atime, stat.st_mtime + 1))

    @staticmethod
    def input_tokens(state):
        return sum(
            models["claude-opus-5"].input
            for models in state.aggregate.by_day_model.values()
            if "claude-opus-5" in models
        )

    def test_reads_only_the_appended_bytes_on_a_second_pass(self):
        self.write(log_line("1", 1_000_000))
        state = ScanState()
        self.assertTrue(self.scanner.scan(state))
        self.assertEqual(self.input_tokens(state), 1_000_000)

        self.write(log_line("2", 500_000), mode="a")
        self.assertTrue(self.scanner.scan(state))
        self.assertEqual(self.input_tokens(state), 1_500_000)

    def test_a_response_split_across_scans_is_counted_once(self):
        # Claude Code writes one line per content block, each repeating the same
        # message id and the same complete usage object.
        block = log_line("1", 1_000_000)
        self.write(block)
        state = ScanState()
        self.scanner.scan(state)

        self.write(block, mode="a")
        self.scanner.scan(state)
        self.write(block, mode="a")
        self.scanner.scan(state)

        self.assertEqual(self.input_tokens(state), 1_000_000)

    def test_a_shrunken_log_does_not_recount_events_already_aggregated(self):
        self.write(log_line("1", 100_000) + log_line("2", 100_000) + log_line("3", 100_000))
        state = ScanState()
        self.scanner.scan(state)
        self.assertEqual(self.input_tokens(state), 300_000)

        # A rewind rewrites the file with only its first message.
        self.write(log_line("1", 100_000))
        self.scanner.scan(state)
        self.assertEqual(self.input_tokens(state), 300_000)

    def test_a_log_swapped_for_same_sized_content_is_reparsed(self):
        self.write(log_line("1", 100_000))
        state = ScanState()
        self.scanner.scan(state)

        self.write(log_line("2", 100_000))
        self.scanner.scan(state)
        self.assertEqual(self.input_tokens(state), 200_000)

    def test_a_half_written_trailing_line_is_picked_up_later(self):
        full = log_line("1", 1_000_000)
        self.write(full[:-20])
        state = ScanState()
        self.scanner.scan(state)
        self.assertTrue(state.aggregate.is_empty)

        self.write(full)
        self.scanner.scan(state)
        self.assertEqual(self.input_tokens(state), 1_000_000)

    def test_appends_after_multibyte_characters_read_from_the_right_offset(self):
        self.write(log_line("1", 1_000, cwd="/Users/x/Desktop/čeština-日本"))
        state = ScanState()
        self.scanner.scan(state)
        self.assertEqual(state.recent[0].project, "čeština-日本")

        self.write(log_line("2", 2_000), mode="a")
        self.scanner.scan(state)
        self.assertEqual(self.input_tokens(state), 3_000)

    def test_recent_events_are_trimmed_but_aggregates_are_not(self):
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(minutes=1)).isoformat()
        old = (now - timedelta(hours=48)).isoformat()
        self.write(log_line("old", 1_000, old) + log_line("new", 1_000, fresh))

        state = ScanState()
        self.scanner.scan(state, now=now)
        self.assertEqual(len(state.recent), 1)
        self.assertEqual(state.recent[0].id, "msg_new:req_new")
        self.assertEqual(len(state.aggregate.by_day_model), 2)

    def test_history_older_than_the_window_is_pruned(self):
        now = datetime.now(timezone.utc)
        ancient = (now - timedelta(days=200)).isoformat()
        self.write(log_line("ancient", 1_000, ancient) + log_line("recent", 1_000, now.isoformat()))

        state = ScanState()
        self.scanner.scan(state, now=now)
        self.assertEqual(len(state.aggregate.by_day_model), 1)

    def test_cursors_for_deleted_logs_are_forgotten(self):
        self.write(log_line("1", 1_000))
        state = ScanState()
        self.scanner.scan(state)
        self.assertEqual(len(state.cursors), 1)

        os.remove(self.log_path)
        self.scanner.scan(state)
        self.assertEqual(state.cursors, {})

    def test_scan_reports_whether_anything_changed(self):
        self.write(log_line("1", 1_000))
        state = ScanState()
        self.assertTrue(self.scanner.scan(state))
        self.assertFalse(self.scanner.scan(state), "a second pass over unchanged logs")

    def test_fingerprint_changes_when_a_log_grows(self):
        self.write(log_line("1", 1_000))
        first = self.scanner.fingerprint()
        self.write(log_line("2", 1_000), mode="a")
        self.assertNotEqual(first, self.scanner.fingerprint())


class StateCacheTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="usage-bar-cache-")
        self.path = os.path.join(self.root, "cache.json")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write_raw(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload))

    def test_state_survives_a_round_trip_and_still_prices_the_same(self):
        log_root = tempfile.mkdtemp(prefix="usage-bar-logs-")
        self.addCleanup(shutil.rmtree, log_root, True)
        project = os.path.join(log_root, "-Users-x-code-acme-web")
        os.makedirs(project)
        with open(os.path.join(project, "s.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(log_line("1", 1_000_000))

        state = ScanState()
        LogScanner(root=log_root).scan(state)

        cache = StateCache(path=self.path)
        cache.save(state)
        revived = cache.load()

        self.assertAlmostEqual(
            summarize(revived.aggregate, 30).cost, summarize(state.aggregate, 30).cost, places=6
        )
        self.assertEqual(revived.counted, state.counted)
        self.assertEqual(
            [slice_.name for slice_ in summarize(revived.aggregate, 30).by_project],
            [slice_.name for slice_ in summarize(state.aggregate, 30).by_project],
        )

    def test_a_missing_cache_file_loads_as_nothing(self):
        self.assertIsNone(StateCache(path=self.path).load())

    def test_a_cache_with_the_wrong_shape_loads_as_nothing(self):
        payloads = {
            "cursors is a list": {"version": 3, "cursors": ["x"]},
            "recent is a dict": {"version": 3, "recent": {"a": 1}},
            "null timestamp": {"version": 3, "recent": [{"id": "a", "timestamp": None,
                                                          "model": "m", "project": "p",
                                                          "session_id": "s", "tokens": {}}]},
            "not json": "{{{",
            "not an object": [1, 2, 3],
            "future version": {"version": 99, "cursors": {}},
        }
        for label, payload in payloads.items():
            with self.subTest(label):
                self.write_raw(payload)
                self.assertIsNone(StateCache(path=self.path).load())


if __name__ == "__main__":
    unittest.main()
