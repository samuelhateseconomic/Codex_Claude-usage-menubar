"""Shared usage facts, independent of pricing, source parsing, and presentation."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Tokens:
    input: int = 0  # Uncached input only, for both providers.
    output: int = 0  # Includes reasoning; reasoning is never added twice.
    cached: int = 0
    write5m: int = 0
    write1h: int = 0

    @property
    def total(self):
        return self.input + self.output + self.cached + self.write5m + self.write1h

    def __add__(self, other):
        return Tokens(*(a + b for a, b in zip(asdict(self).values(), asdict(other).values())))


@dataclass(frozen=True)
class Record:
    provider: str
    timestamp: float
    session: str
    project: str
    model: str
    tokens: Tokens
    effort: str = "unknown"
    effort_source: str = "not recorded"
    turn_id: str | None = None
    reasoning_tokens: int | None = None  # A subset of output, never an extra charge.
