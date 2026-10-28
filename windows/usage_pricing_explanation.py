"""Exact explanation of persisted event valuations, never today's catalog.

Category charges are unrounded (at most 18 fractional USD digits). The signed
adjustment reconciles their sum with the existing 12-place, half-even event
amount. Group adjustments SUM event adjustments; groups are never re-rounded.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from functools import lru_cache

from usage_valuation import (ARITHMETIC, QUANTUM, applied_rates,
                             aggregate_values, EventValuation, ValueSummary)

CATEGORY_NAMES = ('uncached_input_tokens', 'output_tokens', 'cache_read_tokens',
                  'cache_write_5m_tokens', 'cache_write_1h_tokens')
COUNTERS = ('input', 'output', 'cached', 'write5m', 'write1h')
GROUP_LIMIT = 8


@dataclass(frozen=True)
class CategoryCharge:
    category: str
    tokens: int
    rate_usd_per_million: Decimal | None
    unrounded_usd: Decimal | None


@dataclass(frozen=True)
class PricingExplanation:
    state: str
    reason: str | None
    categories: tuple[CategoryCharge, ...] = ()
    rounding_adjustment_usd: Decimal | None = None


def explain_event(value, catalog):
    """Only expose rates proven to belong to this valuation's frozen catalog."""
    absent = lambda reason: PricingExplanation('unavailable', reason)
    if (catalog is None or value.pricing_version != catalog.version
            or value.catalog_version != catalog.catalog_version
            or value.override_version != catalog.override_version
            or value.policy_version != catalog.policy_version):
        return absent('pricing_provenance_unavailable')
    selected = catalog.lookup(value.requested_model)
    if selected is None:
        return absent('model_rate_unavailable')
    try:
        return _selected_explanation(value,selected)
    except TypeError:
        return _explain_selected(value,selected)


@lru_cache(maxsize=4096)
def _selected_explanation(value,selected):
    return _explain_selected(value,selected)


def _explain_selected(value,selected):
    absent = lambda reason: PricingExplanation('unavailable', reason)
    if (value.requested_model != value.record.model
            or (value.rate_id, value.matched_model, value.model_mapping, value.source,
                value.checked_date, value.custom) !=
               (selected.rate_id, selected.model, selected.mapping, selected.source,
                selected.checked_date, selected.custom)):
        return absent('pricing_provenance_unavailable')
    try:
        rates = applied_rates(selected.price, value.tier)
    except ValueError:
        return absent('pricing_provenance_unavailable')
    with localcontext(ARITHMETIC):
        categories = tuple(CategoryCharge(name, getattr(value.record.tokens, counter), rate,
            None if rate is None and getattr(value.record.tokens, counter) else
            Decimal(getattr(value.record.tokens, counter)) * (rate or Decimal(0)) / Decimal(1000000))
            for name, counter, rate in zip(CATEGORY_NAMES, COUNTERS, rates))
        raw = sum((c.unrounded_usd for c in categories if c.unrounded_usd is not None), Decimal(0))
        if value.amount_usd is not None:
            if any(c.unrounded_usd is None for c in categories) or raw.quantize(QUANTUM) != value.amount_usd:
                return absent('valuation_evidence_mismatch')
            adjustment = value.amount_usd - raw
        else:
            adjustment = None
    return PricingExplanation('available', None, categories, adjustment)


def provenance_key(value):
    return tuple(getattr(value, name) for name in (
        'requested_model', 'matched_model', 'model_mapping', 'rate_id', 'tier',
        'source', 'checked_date', 'custom', 'pricing_version', 'catalog_version',
        'override_version', 'policy_version', 'state', 'unpriced_reason', 'assumptions'))


@dataclass(frozen=True)
class PricingGroup:
    representative: EventValuation
    summary: ValueSummary
    explanation: PricingExplanation
    reasoning_tokens: int | None


@dataclass(frozen=True)
class PricingBreakdown:
    groups: tuple[PricingGroup, ...]
    group_count: int
    total_record_count: int
    shown_record_count: int


def explain_values(values, catalog, *, offset=0, limit=GROUP_LIMIT):
    """Bound displayed rate groups; all omitted events remain in the summary.

    First occurrence follows the service's deterministic event order. Existing
    frozen chronological event pagination exposes every group's event evidence.
    Never synthesize a blended rate for mixed models/tiers/provenance.
    """
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= GROUP_LIMIT:
        raise ValueError('Invalid pricing group page.')
    buckets = {}
    total = 0
    for value in values:
        total += 1
        key = provenance_key(value)
        if key not in buckets:
            buckets[key] = [] if offset <= len(buckets) < offset + limit else None
        if buckets[key] is not None:
            buckets[key].append(value)
    groups = []
    for members in buckets.values():
        if members is None:
            continue
        first = explain_event(members[0], catalog)
        combined = first
        counts = [0] * 5
        charges = [Decimal(0)] * 5
        adjustment = Decimal(0)
        # Retain only one event explanation at a time even for a large group.
        with localcontext(ARITHMETIC):
            for value in members:
                explanation = explain_event(value, catalog)
                if explanation.state != 'available':
                    combined = explanation
                    break
                for i, category in enumerate(explanation.categories):
                    counts[i] += category.tokens
                    charges[i] = None if charges[i] is None or category.unrounded_usd is None else charges[i] + category.unrounded_usd
                adjustment = None if adjustment is None or explanation.rounding_adjustment_usd is None else adjustment + explanation.rounding_adjustment_usd
            else:
                categories = tuple(replace(c, tokens=counts[i], unrounded_usd=charges[i])
                                   for i, c in enumerate(first.categories))
                combined = replace(first, categories=categories, rounding_adjustment_usd=adjustment)
        known = [value.record.reasoning_tokens for value in members if value.record.reasoning_tokens is not None]
        groups.append(PricingGroup(members[0], aggregate_values(members), combined, sum(known) if known else None))
    return PricingBreakdown(tuple(groups), len(buckets), total,
                            sum(g.summary.priced_records + g.summary.unpriced_records for g in groups))
