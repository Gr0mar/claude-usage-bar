import unittest

from claude_usage_bar.parser import event_from_line, events_from_text


def log_line(model="claude-opus-5", message_id="msg_1", request_id="req_1", usage="", cwd='"/Users/x/code/acme-web"'):
    return (
        '{"type":"assistant","timestamp":"2026-09-05T10:00:00.000Z","requestId":"%s",'
        '"sessionId":"sess_1","cwd":%s,'
        '"message":{"id":"%s","model":"%s","usage":%s}}'
    ) % (request_id, cwd, message_id, model, usage)


class ParserTests(unittest.TestCase):
    def test_parses_a_billed_assistant_line(self):
        raw = log_line(usage=(
            '{"input_tokens":32,"output_tokens":493,"cache_read_input_tokens":591133,'
            '"cache_creation_input_tokens":582,'
            '"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":582}}'
        ))
        event = event_from_line(raw, "fallback")

        self.assertIsNotNone(event)
        self.assertEqual(event.model, "claude-opus-5")
        self.assertEqual(event.project, "acme-web")
        self.assertEqual(event.session_id, "sess_1")
        self.assertEqual(event.id, "msg_1:req_1")
        self.assertEqual(event.tokens.input, 32)
        self.assertEqual(event.tokens.output, 493)
        self.assertEqual(event.tokens.cache_read, 591_133)
        self.assertEqual(event.tokens.cache_write_1h, 582)
        self.assertEqual(event.tokens.cache_write_5m, 0)

    def test_falls_back_to_the_flat_cache_creation_field(self):
        event = event_from_line(
            log_line(usage='{"input_tokens":10,"output_tokens":10,"cache_creation_input_tokens":400}'),
            "fallback",
        )
        self.assertEqual(event.tokens.cache_write_5m, 400)
        self.assertEqual(event.tokens.cache_write_1h, 0)

    def test_skips_lines_that_were_never_billed(self):
        cases = {
            "user line": '{"type":"user","timestamp":"2026-09-05T10:00:00.000Z","message":{"role":"user"}}',
            "synthetic model": log_line(model="<synthetic>", usage='{"input_tokens":5,"output_tokens":5}'),
            "zero tokens": log_line(usage='{"input_tokens":0,"output_tokens":0}'),
            "garbage": "not json at all",
            "empty": "",
        }
        for label, raw in cases.items():
            with self.subTest(label):
                self.assertIsNone(event_from_line(raw, "x"))

    def test_uses_the_log_directory_name_when_cwd_is_missing(self):
        raw = (
            '{"type":"assistant","timestamp":"2026-09-05T10:00:00.000Z","requestId":"r",'
            '"message":{"id":"m","model":"claude-opus-5","usage":{"input_tokens":1,"output_tokens":1}}}'
        )
        self.assertEqual(event_from_line(raw, "fallback").project, "fallback")

    def test_parses_timestamps_without_fractional_seconds(self):
        raw = (
            '{"type":"assistant","timestamp":"2026-09-05T10:00:00Z","requestId":"r","cwd":"/a/b",'
            '"message":{"id":"m","model":"claude-opus-5","usage":{"input_tokens":1,"output_tokens":1}}}'
        )
        self.assertIsNotNone(event_from_line(raw, "x"))

    def test_drops_duplicate_identities_within_one_chunk(self):
        text = "\n".join([
            log_line(usage='{"input_tokens":1,"output_tokens":1}'),
            log_line(usage='{"input_tokens":1,"output_tokens":1}'),
            log_line(message_id="msg_2", request_id="req_2", usage='{"input_tokens":1,"output_tokens":1}'),
        ])
        self.assertEqual(len(events_from_text(text, "x")), 2)


if __name__ == "__main__":
    unittest.main()
