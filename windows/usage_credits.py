"""Exact, offline credit equivalents. No provider balances or allowance inference.

App units normalize already rounded authoritative USD events without rounding
again. Native units use an independent rate snapshot and round half-even once
per event to 12 places. These are application precision rules, not provider bills.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from functools import lru_cache
import hashlib
import json
import re

from usage_observations import CanonicalEvent
from usage_records import Record, Tokens
from usage_valuation import (ARITHMETIC, MAX_MONEY, QUANTUM,
                             bounded_decimal, validate_record, EventValuation)

APP_UNIT = 'app_api_value_credit'
NATIVE_UNIT = 'codex_credit'
APP_UNIT_USD = Decimal('0.01')
CREDIT_POLICY = 'credits-event12-v1'
with localcontext(ARITHMETIC):
    MAX_APP_CREDITS = MAX_MONEY / APP_UNIT_USD
MAX_NATIVE_CREDITS = MAX_MONEY
SOURCE = 'https://learn.chatgpt.com/docs/pricing'
SPEED_SOURCE = 'https://learn.chatgpt.com/docs/agent-configuration/speed'
CHECKED_DATE = '2026-10-26'


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _text(value, limit=500):
    if not isinstance(value, str):
        raise ValueError('Credit metadata must be bounded text.')
    return _checked_text(value,limit)


@lru_cache(maxsize=1024)
def _checked_text(value,limit):
    # Bounded immutable metadata validation, never query results or money.
    if not value or len(value)>limit or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Credit metadata must be bounded text.')
    return value


def _amount(value, unit):
    bound = MAX_APP_CREDITS if unit == APP_UNIT else MAX_NATIVE_CREDITS
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or value > bound:
        raise ValueError('Credit amount exceeds supported decimal bounds.')
    with localcontext(ARITHMETIC):
        quantum = Decimal('0.0000000001') if unit == APP_UNIT else QUANTUM
        if value.quantize(quantum) != value:
            raise ValueError('Credit amount exceeds supported precision.')
    return value


@dataclass(frozen=True)
class CreditRate:
    model: str
    input: Decimal
    cached: Decimal
    output: Decimal
    speeds: tuple[tuple[str, Decimal], ...] = (('standard', Decimal(1)),)
    source: str = SOURCE
    checked_date: str = CHECKED_DATE
    effective_from: str | None = None  # None means current-rate counterfactual.
    effective_until: str | None = None
    speed_source: str = SPEED_SOURCE
    billing_scope: str = 'purchased_credits_or_enterprise_payg'

    def __post_init__(self):
        if not isinstance(self.model, str) or re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,199}', self.model) is None:
            raise ValueError('Native credit rates require exact model identifiers.')
        for name in ('input', 'cached', 'output'):
            object.__setattr__(self, name, bounded_decimal(getattr(self, name)))
        speeds = tuple((name, bounded_decimal(factor)) for name, factor in self.speeds)
        if (not speeds or len({name for name, _ in speeds}) != len(speeds)
                or any(name not in ('standard', 'fast', 'ultrafast') or factor < 1 for name, factor in speeds)
                or dict(speeds).get('standard') != Decimal(1)):
            raise ValueError('Invalid native speed rate policy.')
        object.__setattr__(self, 'speeds', tuple(sorted(speeds)))
        for name in ('source', 'speed_source', 'billing_scope'):
            _text(getattr(self, name))
        if self.billing_scope != 'purchased_credits_or_enterprise_payg':
            raise ValueError('Unsupported native billing scope.')
        for name in ('checked_date', 'effective_from', 'effective_until'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
                raise ValueError('Credit dates require ISO calendar dates.')
        if self.checked_date is None or (self.effective_until is not None and (
                self.effective_from is None or self.effective_until <= self.effective_from)):
            raise ValueError('Invalid credit rate effective interval.')

    def payload(self):
        return {'model': self.model, 'input': format(self.input, 'f'), 'cached': format(self.cached, 'f'),
                'output': format(self.output, 'f'), 'speeds': [[name, format(factor, 'f')] for name, factor in self.speeds],
                'source': self.source, 'speed_source': self.speed_source, 'checked_date': self.checked_date,
                'effective_from': self.effective_from, 'effective_until': self.effective_until,
                'billing_scope': self.billing_scope}

    @property
    def rate_id(self):
        return 'credit-rate-v1:' + _digest(self.payload())


@dataclass(frozen=True)
class CreditCatalog:
    entries: tuple[CreditRate, ...]
    version: str = field(init=False)

    def __post_init__(self):
        entries = tuple(self.entries)
        if (len(entries) > 1000 or any(not isinstance(entry, CreditRate) for entry in entries)
                or len({entry.model for entry in entries}) != len(entries)):
            raise ValueError('Credit catalog requires distinct typed exact-model entries.')
        entries = tuple(sorted(entries, key=lambda entry: entry.model))
        object.__setattr__(self, 'entries', entries)
        object.__setattr__(self, 'version', 'credit-catalog-v1:' + _digest([entry.payload() for entry in entries]))

    def lookup(self, model):
        # No fuzzy families, dated stripping or aliases inherited from USD.
        return next((entry for entry in self.entries if entry.model == model), None)


# Official text-model rates checked 2026-10-26. Older USD models stay uncovered.
# No historical effective date is established by today's public table.
DEFAULT_CREDIT_CATALOG = CreditCatalog(tuple(
    CreditRate(model, inp, cached, out, (('standard', Decimal(1)), ('fast', Decimal(2)),
               *((('ultrafast', Decimal(6)),) if model in ('gpt-6-astra', 'gpt-6.1-sol') else ())))
    for model, inp, cached, out in (
        ('gpt-6-astra', '250', '25', '1250'),
        ('gpt-6.1-sol', '50', '2.5', '250'),
        ('gpt-6.1-terra', '25', '1.25', '125'),
        ('gpt-6-sol', '50', '5', '250'),
        ('gpt-6-luna', '2.5', '.25', '12.5'))))


def valuation_version(unit, *, usd_pricing_version=None, catalog=DEFAULT_CREDIT_CATALOG, speed_assumption=None):
    if unit == APP_UNIT:
        _text(usd_pricing_version, 200)
        if speed_assumption is not None or catalog is not DEFAULT_CREDIT_CATALOG:
            raise ValueError('App credits inherit USD pricing, not a native credit policy.')
        data = [CREDIT_POLICY, APP_UNIT, '0.01', usd_pricing_version]
    elif unit == NATIVE_UNIT:
        if not isinstance(catalog, CreditCatalog) or speed_assumption not in (None, 'standard', 'fast', 'ultrafast'):
            raise ValueError('Unsupported native credit policy.')
        data = [CREDIT_POLICY, NATIVE_UNIT, catalog.version, speed_assumption]
    else:
        raise ValueError('Unsupported credit unit.')
    return 'credit-valuation-v1:' + _digest(data)


@dataclass(frozen=True)
class CreditEvidence:
    """Explicit allowlisted per-event evidence, never inferred from current settings."""
    speed: str | None = None
    speed_source: str | None = None
    billing_source: str = 'unknown'
    billing_source_provenance: str | None = None

    def __post_init__(self):
        if self.speed not in (None, 'standard', 'fast', 'ultrafast'):
            raise ValueError('Unsupported recorded speed.')
        if (self.speed is None) != (self.speed_source is None):
            raise ValueError('Recorded speed requires provenance.')
        if self.speed_source is not None:
            _text(self.speed_source, 200)
        if self.billing_source not in ('unknown', 'api_key', 'purchased_credits_or_enterprise_payg', 'included_plan'):
            raise ValueError('Unsupported recorded billing scope.')
        if (self.billing_source == 'unknown') != (self.billing_source_provenance is None):
            raise ValueError('Recorded billing source requires provenance.')
        if self.billing_source_provenance is not None:
            _text(self.billing_source_provenance, 200)


@dataclass(frozen=True)
class CreditValuation:
    record: Record
    event_id: str | None
    unit: str
    amount: Decimal | None
    version: str
    unpriced_reason: str | None
    assumptions: tuple[str, ...]
    usd_pricing_version: str | None = None
    rate: CreditRate | None = None
    speed: str | None = None
    evidence: CreditEvidence | None = None
    rounding_adjustment: Decimal | None = None

    def __post_init__(self):
        if not isinstance(self.record, Record):
            raise ValueError('Credit valuation requires accepted typed token facts.')
        validate_record(self.record)
        if self.unit not in (APP_UNIT, NATIVE_UNIT):
            raise ValueError('Unsupported credit unit.')
        if (self.amount is None) != (self.unpriced_reason is not None):
            raise ValueError('Unavailable credit valuation requires a reason.')
        if self.amount is not None:
            _amount(self.amount, self.unit)
        _text(self.version, 200)
        for code in (*self.assumptions, *((self.unpriced_reason,) if self.unpriced_reason else ())):
            if not isinstance(code, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,100}', code) is None:
                raise ValueError('Credit qualifications require bounded reason codes.')
        object.__setattr__(self, 'assumptions', tuple(sorted(set(self.assumptions))))


def app_credit_amount(amount):
    """Exact linear projection of committed event amounts or their exact sum."""
    if amount is None:
        return None
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0 or amount > MAX_MONEY or amount.as_tuple().exponent < -12:
        raise ValueError('Invalid authoritative USD amount.')
    with localcontext(ARITHMETIC):
        return amount / APP_UNIT_USD


def normalize_value(value):
    """Convert one accepted authoritative USD valuation, preserving its coverage."""
    # Reuse existing bound/version validation before conversion, including zero/null.
    if (not isinstance(value, EventValuation) or value.state not in ('priced', 'unpriced')
            or (value.amount_usd is None) != (value.state == 'unpriced')):
        raise ValueError('App credits require a consistent authoritative USD valuation.')
    try:
        return _normalized_value(value)
    except TypeError:
        # Preserve validation of unsupported/unhashable programmatic inputs.
        return _normalize_value(value)


@lru_cache(maxsize=4096)
def _normalized_value(value):
    return _normalize_value(value)


def _normalize_value(value):
    # app_credit_amount validates USD bounds/precision; CreditValuation below
    # validates every token category and reasoning subset. Constructing a second
    # one-record USD summary here repeated both operations for no new evidence.
    _text(value.pricing_version,200)
    amount = None
    if value.amount_usd is not None:
        amount = app_credit_amount(value.amount_usd)
    version = valuation_version(APP_UNIT, usd_pricing_version=value.pricing_version)
    return CreditValuation(value.record, value.event_id, APP_UNIT, amount, version,
        value.unpriced_reason if amount is None else None, value.assumptions, value.pricing_version,
        rounding_adjustment=Decimal(0) if amount is not None else None)


def value_native(event, catalog=DEFAULT_CREDIT_CATALOG, *, evidence=None, speed_assumption=None):
    """Paid-credit equivalent; unknown speed is strict unless a scenario is explicit."""
    version = valuation_version(NATIVE_UNIT, catalog=catalog, speed_assumption=speed_assumption)
    evidence = CreditEvidence() if evidence is None else evidence
    if not isinstance(evidence, CreditEvidence):
        raise ValueError('Native valuation requires typed evidence.')
    canonical = isinstance(event, CanonicalEvent)
    record = event.record if canonical else event
    validate_record(record)
    rate = catalog.lookup(record.model) if record.provider == 'Codex' else None
    flags = set()
    if evidence.billing_source != 'purchased_credits_or_enterprise_payg':
        flags.add('hypothetical_paid_credit_equivalent')
    if evidence.billing_source == 'unknown':
        flags.add('billing_source_unknown')
    if canonical and 'legacy_cache_ttl_assumed' in event.quality:
        flags.add('legacy_cache_ttl_assumed')
    speed = evidence.speed or speed_assumption
    if evidence.speed is None and speed_assumption is not None:
        flags.add('speed_' + speed_assumption + '_assumed')
    reason = 'provider_credit_rate_unavailable' if record.provider != 'Codex' else 'model_credit_rate_unavailable' if rate is None else None
    if rate is not None:
        if rate.effective_from is None:
            flags.add('current_rate_counterfactual')
        else:
            day = datetime.fromtimestamp(record.timestamp, timezone.utc).date().isoformat()
            if day < rate.effective_from or (rate.effective_until is not None and day >= rate.effective_until):
                reason = 'historical_credit_rate_unavailable'
        if record.tokens.write5m or record.tokens.write1h:
            reason = 'credit_cache_write_mapping_unavailable'
        elif speed is None:
            reason = reason or 'speed_not_recorded'
        elif speed not in dict(rate.speeds):
            reason = reason or 'speed_credit_rate_unavailable'
    amount = adjustment = None
    if reason is None:
        with localcontext(ARITHMETIC):
            t = record.tokens
            raw = (t.input * rate.input + t.cached * rate.cached + t.output * rate.output) * dict(rate.speeds)[speed] / Decimal(1000000)
            amount = _amount(raw.quantize(QUANTUM), NATIVE_UNIT)
            adjustment = amount - raw
    return CreditValuation(record, event.event_id if canonical else None, NATIVE_UNIT, amount,
                           version, reason, tuple(flags), rate=rate, speed=speed, evidence=evidence,
                           rounding_adjustment=adjustment)


@dataclass(frozen=True)
class CreditSummary:
    unit: str
    version: str
    state: str
    amount: Decimal | None
    tokens: Tokens
    priced_records: int
    unpriced_records: int
    priced_tokens: int
    unpriced_tokens: int
    assumed_records: int
    assumptions: tuple[str, ...]
    reasons: tuple[tuple[str, int], ...]


def aggregate_credits(values, *, unit, version):
    if unit not in (APP_UNIT, NATIVE_UNIT):
        raise ValueError('Unsupported credit summary unit.')
    tokens, amount = Tokens(), Decimal(0)
    covered = uncovered = priced_tokens = unpriced_tokens = assumed = 0
    flags, reasons = set(), {}
    with localcontext(ARITHMETIC):
        for value in values:
            if not isinstance(value, CreditValuation) or value.unit != unit or value.version != version:
                raise ValueError('Cannot aggregate mixed credit units or policy versions.')
            tokens += value.record.tokens
            flags.update(value.assumptions)
            assumed += bool(value.assumptions)
            if value.amount is None:
                uncovered += 1
                unpriced_tokens += value.record.tokens.total
                reasons[value.unpriced_reason] = reasons.get(value.unpriced_reason, 0) + 1
            else:
                covered += 1
                priced_tokens += value.record.tokens.total
                amount += value.amount
        # Every frozen CreditValuation already has nonnegative, bounded facts
        # and amount. Sums are monotone, so final overflow validation is exactly
        # equivalent to checking every prefix; precision 80 makes summation exact.
        validate_record(Record('Codex', 0, '', '', '', tokens))
        _amount(amount,unit)
    state = 'empty' if not covered + uncovered else 'unpriced' if not covered else 'partial' if uncovered else 'complete'
    return CreditSummary(unit, version, state, amount if covered else None, tokens,
        covered, uncovered, priced_tokens, unpriced_tokens, assumed, tuple(sorted(flags)), tuple(sorted(reasons.items())))


def credit_text(summary, precision=2):
    if type(precision) is not int or not 0 <= precision <= 12:
        raise ValueError('Unsupported credit display precision.')
    if summary.amount is None:
        return 'Unavailable (' + ('no usage records' if summary.state == 'empty' else 'uncovered usage') + ')'
    with localcontext(ARITHMETIC):
        quantum = Decimal(1).scaleb(-precision)
        rounded = summary.amount.quantize(quantum)
        text = f'<{quantum:.{precision}f}' if summary.amount and not rounded else f'{rounded:,.{precision}f}'
    return text + (' + uncovered usage' if summary.state == 'partial' else '')
