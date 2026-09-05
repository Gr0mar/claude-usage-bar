"""USD list prices per million tokens, keyed by model-ID prefix.

Only models with published rates are listed. An unknown model still has its tokens
counted; its cost is reported as unpriced rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .tokens import TokenCounts


@dataclass(frozen=True)
class ModelRates:
    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


def _rates(input_price: float, output_price: float, cache_read: Optional[float] = None) -> ModelRates:
    """Standard derivation: cache reads 0.1x input, 5-minute writes 1.25x, 1-hour writes 2x."""
    return ModelRates(
        input=input_price,
        output=output_price,
        cache_read=input_price * 0.1 if cache_read is None else cache_read,
        cache_write_5m=input_price * 1.25,
        cache_write_1h=input_price * 2.0,
    )


# Longest matching prefix wins, so claude-fable-5-1 never falls into claude-fable-5.
TABLE = {
    "claude-fable-5-1": _rates(10, 50, cache_read=0.25),
    "claude-mythos-5-1": _rates(10, 50, cache_read=0.25),
    "claude-fable-5": _rates(10, 50),
    "claude-mythos-5": _rates(10, 50),
    "claude-opus-5": _rates(5, 25),
    "claude-opus-4-8": _rates(5, 25),
    "claude-opus-4-7": _rates(5, 25),
    "claude-opus-4-6": _rates(5, 25),
    "claude-sonnet-5": _rates(2, 10),
    "claude-sonnet-4-6": _rates(3, 15),
    "claude-haiku-4-5": _rates(1, 5),
}

_PER_TOKEN = 1_000_000.0


def rates(model: str) -> Optional[ModelRates]:
    matches = [prefix for prefix in TABLE if model.startswith(prefix)]
    if not matches:
        return None
    return TABLE[max(matches, key=len)]


def cost(tokens: TokenCounts, model: str) -> Optional[float]:
    """List-price cost, or None when the model has no published rates."""
    rate = rates(model)
    if rate is None:
        return None
    return (
        tokens.input * rate.input
        + tokens.output * rate.output
        + tokens.cache_read * rate.cache_read
        + tokens.cache_write_5m * rate.cache_write_5m
        + tokens.cache_write_1h * rate.cache_write_1h
    ) / _PER_TOKEN


def cache_savings(tokens: TokenCounts, model: str) -> Optional[float]:
    """What the cache reads would have cost at full input price, minus what they did cost."""
    rate = rates(model)
    if rate is None:
        return None
    return tokens.cache_read * (rate.input - rate.cache_read) / _PER_TOKEN


def display_name(model: str) -> str:
    """claude-opus-5 -> Opus 5."""
    trimmed = model[len("claude-"):] if model.startswith("claude-") else model
    parts = trimmed.split("-")
    if not parts or not parts[0]:
        return model
    # Dated snapshots (claude-haiku-4-5-20251001) name the same model as the bare ID.
    if len(parts) > 1 and len(parts[-1]) == 8 and parts[-1].isdigit():
        parts = parts[:-1]
    version = ".".join(parts[1:])
    family = parts[0].capitalize()
    return f"{family} {version}" if version else family
