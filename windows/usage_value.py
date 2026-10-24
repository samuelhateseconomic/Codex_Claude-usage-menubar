"""Exact shared valuation adapter for the dashboard preview.

Uses authoritative core valuation and summaries; no provider polling or GUI imports.
"""
from dataclasses import dataclass
from decimal import Decimal
from usage_records import Record, Tokens
from usage_service import summarize_values
from usage_valuation import build_catalog, value_event


def estimate_exact(record: Record, overrides: dict | None = None) -> Decimal | None:
    """Compatibility projection of the authoritative event valuation."""
    return value_event(record, build_catalog(overrides)).amount_usd


@dataclass(frozen=True)
class UsageSummary:
    tokens: Tokens
    amount: Decimal | None
    state: str
    record_count: int
    unpriced_records: int
    unpriced_tokens: int
    reasoning_tokens: int | None
    reasoning_records: int


def summarize_records(records, prices=None) -> UsageSummary:
    """Project the shared headless summary into the existing demo DTO shape.

    No pricing, token, reasoning or coverage arithmetic belongs in this adapter.
    The real-data query/index/API contract remains a separate gated session.
    """
    catalog = build_catalog(prices)
    summary = summarize_values(value_event(record, catalog) for record in records)
    value, reasoning = summary.value, summary.reasoning
    return UsageSummary(value.tokens, value.amount_usd, value.state, summary.record_count,
                        value.unpriced_records, value.unpriced_tokens,
                        reasoning.known_tokens, reasoning.known_records)
