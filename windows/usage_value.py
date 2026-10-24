"""Exact shared valuation adapter for the dashboard preview.

No parser, provider polling, or GUI imports. Core service adoption remains gated.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from usage_reports import Record, Tokens, price_for

def estimate_exact(record: Record, overrides: dict | None = None) -> Decimal | None:
    price = price_for(record.model, overrides)
    if price is None:
        return None
    tokens = record.tokens
    inp, out, cached = price.input, price.output, price.cached
    if price.threshold and tokens.input + tokens.cached > price.threshold and price.high:
        inp, out, cached = price.high
    with localcontext() as context:
        context.prec = 80
        return sum((Decimal(count) * Decimal(str(rate)) for count, rate in (
            (tokens.input, inp), (tokens.output, out), (tokens.cached, cached),
            (tokens.write5m, price.write5m), (tokens.write1h, price.write1h))), Decimal(0)) / Decimal(1_000_000)


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
    """One headless arithmetic path for preview summaries and drill-downs.

    S04/S05 must consolidate this seam with terminal/HTML valuation before
    enabling the real-data dashboard. Legacy reporting is unchanged here.
    """
    records = list(records)
    tokens, known, unknown, unpriced_tokens, reasoning = Tokens(), [], 0, 0, []
    for record in records:
        tokens += record.tokens
        value = estimate_exact(record, prices)
        if value is None:
            unknown += 1
            unpriced_tokens += record.tokens.total
        else:
            known.append(value)
        if record.reasoning_tokens is not None:
            reasoning.append(record.reasoning_tokens)
    state = "empty" if not records else "unpriced" if not known else "partial" if unknown else "complete"
    with localcontext() as context:
        context.prec = 80
        amount = sum(known, Decimal(0)) if known else None
    return UsageSummary(tokens, amount, state, len(records), unknown, unpriced_tokens,
                        sum(reasoning) if reasoning else None, len(reasoning))
