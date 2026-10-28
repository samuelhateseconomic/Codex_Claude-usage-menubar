"""Explicit, bounded metadata storage projections. Never serialize provider payloads."""
from decimal import Decimal, localcontext
from datetime import datetime, timezone
import json
import math

from usage_observations import Counter, Counters, Observation, SourceRef, CanonicalEvent
from usage_records import Record, Tokens
from usage_valuation import (Price, RateCatalog, EventValuation, ARITHMETIC, MAX_TOKENS,
                             MAX_MONEY, POLICY_VERSION, LEGACY_POLICY_VERSION,
                             BELOW_THRESHOLD, LEGACY_CONTEXT, validate_record)

COUNTS = ('input', 'output', 'cached', 'write5m', 'write1h')
COUNTER_FIELDS = (*COUNTS, 'legacy_write', 'reasoning')
OBS_TEXT = ('provider', 'conversation_id', 'timestamp_state', 'kind', 'project', 'project_kind',
            'model', 'effort', 'effort_source', 'turn_id', 'message_id', 'request_id',
            'fork_parent_id', 'parser_version')
RECORD_TEXT = ('provider', 'session', 'project', 'model', 'effort', 'effort_source', 'turn_id')
EVENT_TEXT = ('conversation_key', 'epoch_anchor', 'event_anchor', 'source_kind',
              'request_context_source', 'reconciliation_version')
VALUE_TEXT = ('event_id', 'state', 'unpriced_reason', 'pricing_version', 'catalog_version',
              'override_version', 'policy_version', 'requested_model', 'matched_model',
              'model_mapping', 'rate_id', 'source', 'checked_date', 'tier', 'request_context_source')


def dumps(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def loads(value):
    return json.loads(value)


def text(value):
    if value is not None and (not isinstance(value, str) or len(value) > 32767):
        raise ValueError('Index metadata must be bounded text, never nested source content.')
    return value


def count(value, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not int or not 0 <= value <= MAX_TOKENS:
        raise ValueError('Index token quantity exceeds signed-64-bit bounds.')
    return value


def instant(value):
    """Lossless representation of the existing finite binary UTC epoch contract."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Index time must be a finite UTC epoch.')
    datetime.fromtimestamp(value, timezone.utc)  # Reject unsupported calendar bounds.
    return float(value).hex()


def epoch(value):
    return None if value is None else float.fromhex(value)


def micros(value):
    # Indexed projection only. Shared-service float boundaries remain authoritative.
    with localcontext(ARITHMETIC):
        return int(Decimal(str(value)) * 1000000)


def ref_data(ref):
    return None if ref is None else [text(ref.source_id), count(ref.line), text(ref.generation)]


def ref_from(value):
    return None if value is None else SourceRef(*value)


def counters_data(counters):
    if counters.state not in ('valid', 'missing', 'invalid') or counters.cache_details_state not in ('valid', 'missing', 'invalid'):
        raise ValueError('Invalid counter state.')
    return {'state': counters.state, 'cache_details_state': counters.cache_details_state,
            **{key: [count(getattr(counters, key).value, True), getattr(counters, key).state] for key in COUNTER_FIELDS}}


def counters_from(data):
    return Counters(data['state'], **{key: Counter(*data[key]) for key in COUNTER_FIELDS},
                    cache_details_state=data['cache_details_state'])


def observation_data(observation):
    if not isinstance(observation, Observation):
        raise ValueError('Index accepts typed observations only.')
    data = {key: text(getattr(observation, key)) for key in OBS_TEXT}
    if type(observation.effort_is_explicit) is not bool:
        raise ValueError('Invalid explicit-effort state.')
    data.update(source=ref_data(observation.source), timestamp=instant(observation.timestamp),
                session_created_at=instant(observation.session_created_at),
                effort_is_explicit=observation.effort_is_explicit,
                context_source=ref_data(observation.context_source), session_source=ref_data(observation.session_source),
                context_window=[count(observation.context_window.value, True), observation.context_window.state],
                issues=[text(code) for code in observation.issues])
    for key in ('cumulative', 'last_usage', 'message_usage'):
        data[key] = counters_data(getattr(observation, key))
    return data


def observation_from(data):
    return Observation(**{key: data[key] for key in OBS_TEXT},
        source=ref_from(data['source']), timestamp=epoch(data['timestamp']),
        session_created_at=epoch(data['session_created_at']), effort_is_explicit=data['effort_is_explicit'],
        context_source=ref_from(data['context_source']), session_source=ref_from(data['session_source']),
        context_window=Counter(*data['context_window']), issues=tuple(data['issues']),
        **{key: counters_from(data[key]) for key in ('cumulative', 'last_usage', 'message_usage')})


def record_data(record):
    validate_record(record)
    return {**{key: text(getattr(record, key)) for key in RECORD_TEXT},
            'timestamp': instant(record.timestamp), 'tokens': [getattr(record.tokens, key) for key in COUNTS],
            'reasoning_tokens': record.reasoning_tokens}


def record_from(data):
    record = Record(**{key: data[key] for key in RECORD_TEXT}, timestamp=epoch(data['timestamp']),
                    tokens=Tokens(*data['tokens']), reasoning_tokens=data['reasoning_tokens'])
    validate_record(record)
    return record


def event_data(event):
    return {**{key: text(getattr(event, key)) for key in EVENT_TEXT}, 'record': record_data(event.record),
            'sources': [ref_data(ref) for ref in event.sources], 'quality': [text(code) for code in event.quality],
            'request_context_tokens': count(event.request_context_tokens, True)}


def event_from(data):
    return CanonicalEvent(**{key: data[key] for key in EVENT_TEXT}, record=record_from(data['record']),
                          sources=tuple(ref_from(ref) for ref in data['sources']), quality=tuple(data['quality']),
                          request_context_tokens=data['request_context_tokens'])


def catalog_data(catalog):
    return {'override_version': text(catalog.override_version), 'policy_version': catalog.policy_version,
            'entries': [[text(name), price.payload(), text(source), text(date), custom]
                        for name, price, source, date, custom in catalog.entries]}


def catalog_from(data):
    if data['policy_version'] not in (POLICY_VERSION, LEGACY_POLICY_VERSION):
        raise ValueError('Unsupported persisted valuation policy; explicit reindex required.')
    return RateCatalog(tuple((name, Price(*rates[:5], threshold=rates[5], high=rates[6]), source, date, custom)
                             for name, rates, source, date, custom in data['entries']), data['override_version'],
                       BELOW_THRESHOLD if data['policy_version'] == POLICY_VERSION else LEGACY_CONTEXT)


def value_data(value):
    amount = value.amount_usd
    if amount is not None and (not amount.is_finite() or amount < 0 or amount > MAX_MONEY
                               or amount.as_tuple().exponent != -12):
        raise ValueError('Invalid persisted event money.')
    return {**{key: text(getattr(value, key)) for key in VALUE_TEXT},
            'amount_usd': None if amount is None else format(amount, 'f'), 'custom': value.custom,
            'request_context_tokens': count(value.request_context_tokens, True),
            'assumptions': [text(code) for code in value.assumptions]}


def value_from(data, record):
    value = EventValuation(record=record, **{key: data[key] for key in VALUE_TEXT},
                           amount_usd=None if data['amount_usd'] is None else Decimal(data['amount_usd']),
                           custom=data['custom'], request_context_tokens=data['request_context_tokens'],
                           assumptions=tuple(data['assumptions']))
    value_data(value)
    if (value.amount_usd is None) != (value.state == 'unpriced') or value.state not in ('priced', 'unpriced'):
        raise ValueError('Invalid persisted price coverage.')
    return value
