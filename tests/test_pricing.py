import unittest

from quotabar import pricing
from quotabar.tokens import TokenCounts


class PricingTests(unittest.TestCase):
    def test_longest_model_prefix_wins(self):
        self.assertEqual(pricing.rates("claude-opus-5").input, 5)
        self.assertEqual(pricing.rates("claude-fable-5-1").cache_read, 0.25)
        self.assertEqual(pricing.rates("claude-fable-5").cache_read, 1.0)
        self.assertEqual(pricing.rates("claude-sonnet-4-6").input, 3)
        self.assertEqual(pricing.rates("claude-sonnet-5").output, 10)

    def test_dated_snapshots_use_the_base_model_rates(self):
        self.assertEqual(pricing.rates("claude-haiku-4-5-20251001").input, 1)

    def test_an_unknown_model_is_counted_but_never_priced(self):
        self.assertIsNone(pricing.rates("claude-unreleased-9"))
        self.assertIsNone(pricing.cost(TokenCounts(input=1_000_000), "claude-unreleased-9"))

    def test_cost_uses_every_token_class(self):
        tokens = TokenCounts(
            input=1_000_000, output=1_000_000,
            cache_write_5m=1_000_000, cache_write_1h=1_000_000, cache_read=1_000_000,
        )
        # 5 + 25 + 6.25 + 10 + 0.5
        self.assertAlmostEqual(pricing.cost(tokens, "claude-opus-5"), 46.75, places=4)

    def test_cache_savings_is_the_gap_to_full_input_price(self):
        savings = pricing.cache_savings(TokenCounts(cache_read=1_000_000), "claude-opus-5")
        self.assertAlmostEqual(savings, 4.5, places=4)

    def test_display_names_read_like_product_names(self):
        self.assertEqual(pricing.display_name("claude-opus-5"), "Opus 5")
        self.assertEqual(pricing.display_name("claude-sonnet-4-6"), "Sonnet 4.6")
        self.assertEqual(pricing.display_name("claude-haiku-4-5-20251001"), "Haiku 4.5")


if __name__ == "__main__":
    unittest.main()
