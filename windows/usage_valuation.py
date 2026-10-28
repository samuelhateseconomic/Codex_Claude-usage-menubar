"""Exact event valuation and fee comparison, independent of readers and renderers.

USD/rates use Decimal. One half-even quantization at 12 USD fractional digits
per accepted event; aggregation sums those values without another quantization.
"""
from dataclasses import dataclass, field
from decimal import Decimal, Context, InvalidOperation, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import re
from types import MappingProxyType

from usage_observations import CanonicalEvent
from usage_records import Record, Tokens

LEGACY_POLICY_VERSION = "decimal12-event-tier-compat-v1"
POLICY_VERSION = "decimal12-below-threshold-v1"
LEGACY_CONTEXT = "event_context_compatibility"
BELOW_THRESHOLD = "below_threshold_assumed"
MAX_TOKENS = 2**63 - 1
MAX_RATE = Decimal("1000000000")  # USD per million; fees share this limit.
MAX_MONEY = Decimal("999999999999999999999999.999999999999")
QUANTUM = Decimal("0.000000000001")
ARITHMETIC = Context(prec=80, rounding=ROUND_HALF_EVEN)
DEFAULT_PLAN_FEES = MappingProxyType({"Codex": Decimal("20.00"), "Claude": Decimal("20.00")})


def bounded_decimal(value):
    """Accept legacy numeric inputs through decimal text, never binary arithmetic."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Rates and fees must be finite nonnegative decimal amounts.")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError("Decimal amount exceeds supported bounds.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid decimal amount.") from None
    if not number.is_finite() or number < 0 or number > MAX_RATE:
        raise ValueError("Rates and fees must be between zero and 1000000000.")
    if not number:
        return Decimal(0)
    digits = number.as_tuple().digits
    exponent = number.as_tuple().exponent
    if len(digits) > 64:
        raise ValueError("Decimal amount exceeds supported precision.")
    trailing = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing += 1
    if exponent + trailing < -12:
        raise ValueError("Rates and fees support at most 12 fractional decimal digits.")
    return number


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TOKENS:
        raise ValueError("Token quantities must be nonnegative signed-64-bit integers.")
    return value


def _money(value):
    if not value.is_finite() or abs(value) > MAX_MONEY:
        raise ValueError("USD amount exceeds the supported money bound.")
    return value


def _decimal_text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cached: Decimal
    write5m: Decimal | None = None
    write1h: Decimal | None = None
    threshold: int | None = None
    high: tuple[Decimal, Decimal, Decimal] | None = None

    def __post_init__(self):
        for name in ("input", "output", "cached", "write5m", "write1h"):
            value = getattr(self, name)
            if value is None and name in ("write5m", "write1h"):
                continue
            object.__setattr__(self, name, bounded_decimal(value))
        if (self.threshold is None) != (self.high is None):
            raise ValueError("Tiered rates require both a threshold and high-context rates.")
        if self.threshold is not None:
            if not _count(self.threshold) or not isinstance(self.high, (tuple, list)) or len(self.high) != 3:
                raise ValueError("Invalid context tier definition.")
            object.__setattr__(self, "high", tuple(bounded_decimal(v) for v in self.high))

    def payload(self):
        return [*(_decimal_text(getattr(self, k)) if getattr(self, k) is not None else None for k in ("input", "output", "cached", "write5m", "write1h")),
                self.threshold, [_decimal_text(v) for v in self.high] if self.high else None]


# Standard USD per million tokens. No subscription price or quota conversion.
# Snapshot of LiteLLM's public price registry, checked 2026-10-23 Pacific.
# https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
PRICE_SOURCE = "https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json"
PRICE_DATE = "2026-10-23"
MODEL_PRICE_SOURCES = {
    "gpt-6.1-sol": "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
    "claude-opus-5-5": "https://platform.claude.com/docs/en/models/opus-5-5/overview",
}


PRICES = {
    # Official model pages verified 2026-10-23. Standard USD per 1M tokens.
    "gpt-6.1-sol": Price("2", "10", "0.1", threshold=272000, high=("4", "15", "0.2")),
    "claude-opus-5-5": Price("4", "20", "0.2", "5", "8"),
    "gpt-5": Price("1.25", "10", "0.125"),
    "gpt-5-codex": Price("1.25", "10", "0.125"),
    "gpt-5.1": Price("1.25", "10", "0.125"),
    "gpt-5.1-codex": Price("1.25", "10", "0.125"),
    "gpt-5.1-codex-max": Price("1.25", "10", "0.125"),
    "gpt-5.1-codex-mini": Price("0.25", "2", "0.025"),
    "gpt-5.2": Price("1.75", "14", "0.175"),
    "gpt-5.2-codex": Price("1.75", "14", "0.175"),
    "gpt-5.3-codex": Price("1.75", "14", "0.175"),
    "gpt-5.4": Price("2.5", "15", "0.25", threshold=272000, high=("5", "22.5", "0.5")),
    "claude-opus-4-6": Price("5", "25", "0.5", "6.25", "10"),
    "claude-opus-4-5": Price("5", "25", "0.5", "6.25", "10"),
    "claude-sonnet-4-6": Price("3", "15", "0.3", "3.75", "6"),
    "claude-sonnet-4-5": Price("3", "15", "0.3", "3.75", "6"),
    "claude-haiku-4-5": Price("1", "5", "0.1", "1.25", "2"),
}

@dataclass(frozen=True)
class RateSelection:
    model: str
    price: Price
    source: str
    checked_date: str | None
    custom: bool
    rate_id: str
    mapping: str


@dataclass(frozen=True)
class RateCatalog:
    entries: tuple[tuple[str, Price, str, str | None, bool], ...]
    override_version: str
    context_policy: str = BELOW_THRESHOLD
    catalog_version: str = field(init=False)
    version: str = field(init=False)

    @property
    def policy_version(self):
        return POLICY_VERSION if self.context_policy == BELOW_THRESHOLD else LEGACY_POLICY_VERSION

    def __post_init__(self):
        if self.context_policy not in (BELOW_THRESHOLD, LEGACY_CONTEXT):
            raise ValueError("Unsupported request-context valuation policy.")
        object.__setattr__(self, "entries", tuple(tuple(entry) for entry in self.entries))
        payload = [(name, price.payload(), source, date, custom) for name, price, source, date, custom in self.entries]
        catalog_version = "rates-v1:" + _digest(payload)
        object.__setattr__(self, "catalog_version", catalog_version)
        object.__setattr__(self, "version", "pricing-v1:" + _digest([catalog_version, self.override_version, self.policy_version]))
        object.__setattr__(self, '_selections', MappingProxyType({
            name:RateSelection(name,price,source,checked,custom,
                'rate-v1:'+_digest([name,price.payload(),source,checked,custom]),'exact')
            for name,price,source,checked,custom in self.entries}))

    def __deepcopy__(self,memo):
        # All catalog facts and derived selections are immutable. Keep the
        # private lookup index outside dataclass/asdict and stored wire fields.
        memo[id(self)]=self
        return self

    def lookup(self, model):
        selected=self._selections.get(model)
        if selected is not None:return selected
        key=re.sub(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", "", model)
        selected=self._selections.get(key)
        if selected is None:
            return None
        return RateSelection(selected.model,selected.price,selected.source,selected.checked_date,
                             selected.custom,selected.rate_id,'dated_snapshot')


def _catalog(overrides, context_policy=BELOW_THRESHOLD):
    merged = dict(PRICES)
    for name, price in overrides.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(price, Price):
            raise ValueError("Overrides require exact model names and validated Price values.")
        merged[name] = price
    override_version = "overrides-v1:" + _digest([(name, price.payload()) for name, price in sorted(overrides.items())])
    entries = tuple((name, price, "custom configuration" if name in overrides else MODEL_PRICE_SOURCES.get(name, PRICE_SOURCE),
                     None if name in overrides else PRICE_DATE, name in overrides) for name, price in sorted(merged.items()))
    return RateCatalog(entries, override_version, context_policy)


DEFAULT_CATALOG = _catalog({})


def build_catalog(overrides=None, *, context_policy=BELOW_THRESHOLD):
    return _catalog(dict(overrides or {}), context_policy) if overrides or context_policy != BELOW_THRESHOLD else DEFAULT_CATALOG


def price_for(model, overrides=None):
    selection = build_catalog(overrides).lookup(model)
    return selection.price if selection else None


def validate_record(record):
    for name in ("input", "output", "cached", "write5m", "write1h"):
        _count(getattr(record.tokens, name))
    _count(record.tokens.total)
    if record.reasoning_tokens is not None:
        if _count(record.reasoning_tokens) > record.tokens.output:
            raise ValueError("Reasoning must be a subset of output.")


@dataclass(frozen=True)
class EventValuation:
    record: Record
    event_id: str | None
    amount_usd: Decimal | None
    state: str
    unpriced_reason: str | None
    pricing_version: str
    catalog_version: str
    override_version: str
    policy_version: str
    requested_model: str
    matched_model: str | None
    model_mapping: str | None
    rate_id: str | None
    source: str | None
    checked_date: str | None
    custom: bool
    tier: str | None
    request_context_tokens: int | None
    request_context_source: str
    assumptions: tuple[str, ...]


def applied_rates(price, tier):
    """The five selected category rates; tier selection remains event evidence."""
    if tier not in ("standard", "high_context") or (tier == "high_context" and price.high is None):
        raise ValueError("Unsupported applied price tier.")
    leading = price.high if tier == "high_context" else (price.input, price.output, price.cached)
    return (*leading, price.write5m, price.write1h)


def value_event(event, catalog=DEFAULT_CATALOG):
    canonical = isinstance(event, CanonicalEvent)
    record = event.record if canonical else event
    validate_record(record)
    context = event.request_context_tokens if canonical else None
    context_source = event.request_context_source if canonical else "not recorded"
    if context is not None:
        _count(context)
        if not context_source or context_source == "not recorded":
            raise ValueError("Request-context size requires an evidence source.")
    selected = catalog.lookup(record.model)
    amount, tier, assumptions = None, None, []
    unpriced_reason = "model_rate_unavailable" if selected is None else None
    if canonical and "legacy_cache_ttl_assumed" in event.quality:
        assumptions.append("legacy_cache_ttl_assumed")
    if selected:
        price = selected.price
        tier = "standard"
        if price.threshold is not None:
            if catalog.context_policy == BELOW_THRESHOLD:
                assumptions.append("below_threshold_context_assumed")
                if context is not None and context > price.threshold:
                    assumptions.append("recorded_context_exceeds_assumed_threshold")
            else:
                tier_context = context
                if tier_context is None:
                    tier_context = record.tokens.input + record.tokens.cached
                    assumptions.append("event_input_tier_compatibility")
                if tier_context > price.threshold:
                    tier = "high_context"
        inp, out, cached, _, _ = applied_rates(price, tier)
        tokens = record.tokens
        if (tokens.write5m and price.write5m is None) or (tokens.write1h and price.write1h is None):
            unpriced_reason = "cache_write_rate_unavailable"
        else:
            with localcontext(ARITHMETIC):
                amount = _money(((tokens.input * inp + tokens.output * out + tokens.cached * cached
                                 + tokens.write5m * (price.write5m or Decimal(0))
                                 + tokens.write1h * (price.write1h or Decimal(0)))
                                / Decimal(1000000)).quantize(QUANTUM, rounding=ROUND_HALF_EVEN))
    return EventValuation(record, event.event_id if canonical else None, amount,
                          "priced" if amount is not None else "unpriced", unpriced_reason, catalog.version, catalog.catalog_version, catalog.override_version, catalog.policy_version,
                          record.model, selected.model if selected else None, selected.mapping if selected else None,
                          selected.rate_id if selected else None, selected.source if selected else None,
                          selected.checked_date if selected else None, selected.custom if selected else False,
                          tier, context, context_source, tuple(assumptions))


@dataclass(frozen=True)
class ValueSummary:
    state: str
    amount_usd: Decimal | None
    tokens: Tokens
    priced_records: int
    unpriced_records: int
    priced_tokens: int
    unpriced_tokens: int
    assumed_records: int
    assumptions: tuple[str, ...]
    pricing_version: str | None


def aggregate_values(valuations):
    values = tuple(valuations)
    versions = {value.pricing_version for value in values}
    if len(versions) > 1:
        raise ValueError("Cannot aggregate different pricing versions.")
    tokens, amount = Tokens(), Decimal("0.000000000000")
    priced = unpriced = priced_tokens = unpriced_tokens = assumed = 0
    assumptions = set()
    with localcontext(ARITHMETIC):
        for value in values:
            tokens += value.record.tokens
            _count(tokens.total)
            assumptions.update(value.assumptions)
            assumed += bool(value.assumptions)
            if value.amount_usd is None:
                unpriced += 1
                unpriced_tokens += value.record.tokens.total
            else:
                priced += 1
                priced_tokens += value.record.tokens.total
                amount = _money(amount + value.amount_usd)
    state = "empty" if not values else "unpriced" if not priced else "partial" if unpriced else "complete"
    return ValueSummary(state, amount if priced else None, tokens, priced, unpriced, priced_tokens,
                        unpriced_tokens, assumed, tuple(sorted(assumptions)), next(iter(versions), None))


def money_text(amount, precision=4, signed=False):
    if not 0 <= precision <= 12:
        raise ValueError("Unsupported USD display precision.")
    with localcontext(ARITHMETIC):
        rounded = amount.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN)
        if amount and not rounded:
            return ("-" if amount < 0 else "+" if signed else "") + f"<${Decimal(1).scaleb(-precision):.{precision}f}"
        prefix = "-" if rounded < 0 else "+" if signed else ""
        return prefix + f"${abs(rounded):,.{precision}f}"


def value_text(summary, precision=4):
    if summary.state == "empty":
        return "Unavailable (no usage records)"
    if summary.state == "unpriced":
        return "Unavailable (all usage unpriced)"
    result = money_text(summary.amount_usd, precision)
    if summary.state == "partial":
        result += " + unpriced usage"
    if "event_input_tier_compatibility" in summary.assumptions:
        result += " (request-context tier assumed)"
    if "below_threshold_context_assumed" in summary.assumptions:
        result += " (Below-threshold context assumed)"
    if "recorded_context_exceeds_assumed_threshold" in summary.assumptions:
        result += " (recorded context conflicts with scenario)"
    if "legacy_cache_ttl_assumed" in summary.assumptions:
        result += " (cache-write TTL assumed)"
    return result


@dataclass(frozen=True)
class ComparisonScope:
    providers: tuple[str, ...]
    period: str
    calendar_month_to_date: bool
    filtered: bool = False


@dataclass(frozen=True)
class PlanComparison:
    provider: str
    available: bool
    reason: str | None
    pricing_state: str
    value_usd: Decimal | None
    fee_usd: Decimal | None
    difference_usd: Decimal | None
    qualifications: tuple[str, ...]


def compare_plans(valuations, scope, fees=None, qualifications=None):
    if not scope.providers or len(set(scope.providers)) != len(scope.providers):
        raise ValueError("Comparison requires a nonempty distinct provider selection.")
    if any(p not in DEFAULT_PLAN_FEES for p in scope.providers):
        raise ValueError("Unsupported comparison provider.")
    fees = DEFAULT_PLAN_FEES if fees is None else fees
    fees = {p: bounded_decimal(fees[p]) if fees.get(p) is not None else None for p in scope.providers}
    entries = tuple(v for v in valuations if v.record.provider in scope.providers)
    qualifications = qualifications or {}
    reason = ("not_month_to_date" if scope.period != "month" else "filtered_query" if scope.filtered else
              "range_not_calendar_month_to_date" if not scope.calendar_month_to_date else None)
    results = []
    for provider in scope.providers:
        summary = aggregate_values(v for v in entries if v.record.provider == provider)
        fee = fees[provider]
        unavailable = reason or ("no_usage_records" if summary.state == "empty" else
                                 "fee_not_configured" if fee is None else "all_usage_unpriced" if summary.state == "unpriced" else None)
        flags = {"local_unmatched_accounts", "full_month_fee", "api_equivalent_estimate", *qualifications.get(provider, ()), *summary.assumptions}
        if summary.state == "partial":
            flags.add("priced_usage_only")
        with localcontext(ARITHMETIC):
            difference = _money(summary.amount_usd - fee) if unavailable is None else None
        results.append(PlanComparison(provider, unavailable is None, unavailable, summary.state,
                                      summary.amount_usd, fee, difference, tuple(sorted(flags))))
    combined_summary = aggregate_values(entries)
    combined_reason = reason or ("selected_provider_unavailable" if any(not r.available for r in results) else None)
    combined_fee = combined_difference = None
    if combined_reason is None:
        with localcontext(ARITHMETIC):
            combined_fee = _money(sum((r.fee_usd for r in results), Decimal(0)))
            combined_difference = _money(combined_summary.amount_usd - combined_fee)
    flags = tuple(sorted({flag for result in results for flag in result.qualifications}))
    combined = PlanComparison("Combined", combined_reason is None, combined_reason, combined_summary.state,
                              combined_summary.amount_usd, combined_fee, combined_difference, flags)
    return tuple(results), combined


def rate_text(rate):
    return "unconfigured" if rate is None else _decimal_text(rate)
