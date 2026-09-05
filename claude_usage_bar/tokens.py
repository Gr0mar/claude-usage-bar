"""Token counts, split the way pricing treats them."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0

    @property
    def total(self) -> int:
        """Everything the API billed for, cache reads included."""
        return (
            self.input
            + self.output
            + self.cache_write_5m
            + self.cache_write_1h
            + self.cache_read
        )

    def __add__(self, other: "TokenCounts") -> "TokenCounts":
        return TokenCounts(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_write_5m=self.cache_write_5m + other.cache_write_5m,
            cache_write_1h=self.cache_write_1h + other.cache_write_1h,
            cache_read=self.cache_read + other.cache_read,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "TokenCounts":
        return cls(**{key: int(raw.get(key, 0)) for key in cls.__dataclass_fields__})


ZERO = TokenCounts()
