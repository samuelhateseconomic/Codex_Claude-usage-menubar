"""Bounded desktop projections over accepted, committed service results only."""
from collections import defaultdict
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from datetime import datetime
from zoneinfo import ZoneInfo

from usage_api_contract import summary, money, pricing_breakdown
from usage_credits import APP_UNIT, APP_UNIT_USD, CREDIT_POLICY, app_credit_amount
from usage_pricing_explanation import CATEGORY_NAMES, COUNTERS, explain_event, explain_values
from usage_service import summarize_details
from usage_valuation import ARITHMETIC

PROJECTION = 'app_api_value_v1'
PRIMARY_POLICY = 'desktop-primary-models-v1'
PRIMARY_MODELS = (('Codex', 'gpt-6.1-sol'), ('Claude', 'claude-opus-5-5'))
SLICE_LIMIT = 12


def descriptor(pairs, policy):
    return {'id': PROJECTION, 'unit': APP_UNIT, 'usd_per_credit': money(APP_UNIT_USD),
            'credit_policy': CREDIT_POLICY, 'primary_model_policy': PRIMARY_POLICY,
            'primary_models': [{'provider': p.lower(), 'model': m} for p, m in pairs],
            'valuation_policy': policy, 'basis': 'estimated_api_value_not_spend_or_allowance'}


def distributions(result, snapshot, dimension):
    if dimension == 'projects':
        identities = dict(snapshot.event_project_ids)
        labels = {row[0]: row[-1] for row in snapshot.projects}
    else:
        identities = {d.detail_id: d.record.provider.lower() + ':' + d.record.model for d in result.details}
        labels = {identities[d.detail_id]: d.record.model for d in result.details}
    buckets = defaultdict(list)
    for d in result.details:
        buckets[identities[d.detail_id]].append(d)
    rows = [(key, summarize_details(members, dict(snapshot.project_ids)), members) for key, members in buckets.items()]
    output = {}
    for metric in ('tokens', 'usd', 'app_credits'):
        def amount(s):
            return Decimal(s.tokens.total) if metric == 'tokens' else s.value.amount_usd
        total = amount(result.total)
        ordered = sorted(rows, key=lambda r: (amount(r[1]) is None, -(amount(r[1]) or Decimal(0)), r[0]))
        shown = [(key, labels[key], value, False) for key, value, _ in ordered[:SLICE_LIMIT - 1]]
        omitted = ordered[SLICE_LIMIT - 1:]
        if omitted:
            other = summarize_details([d for _, _, members in omitted for d in members], dict(snapshot.project_ids))
            shown.append((None, 'Other', other, True))
        slices = []
        with localcontext(ARITHMETIC):
            remaining = Decimal(100)
            positive = [i for i, (_, _, s, _) in enumerate(shown) if (amount(s) or 0) > 0]
            for i, (key, label, s, other) in enumerate(shown):
                share = None
                if total is not None and total > 0:
                    share = min(remaining, ((amount(s) or Decimal(0)) / total * 100).quantize(Decimal('.000001')))
                    if positive and i == positive[-1]: share = remaining
                    remaining -= share
                slices.append({'id': key, 'label': label, 'other': other,
                               'summary': summary(s, projected=True), 'percent': money(share)})
        output[metric] = {'denominator': 'all_recorded_tokens' if metric == 'tokens' else 'priced_subtotal',
                          'state': 'unavailable' if total is None else 'zero' if total == 0 else 'available',
                          'group_count': len(rows), 'slices': slices}
    return output


def methodology(result, snapshot, *, offset=0, limit=8):
    counts = [getattr(result.total.tokens, k) for k in COUNTERS]
    priced_counts = [0] * 5
    charges = [Decimal(0)] * 5
    rates = [set() for _ in COUNTERS]
    adjustment = Decimal(0)
    verified = True
    with localcontext(ARITHMETIC):
        for d in result.details:
            e = explain_event(d.valuation, snapshot.catalog)
            if e.state == 'available':
                for i, c in enumerate(e.categories): rates[i].add(c.rate_usd_per_million)
            else:
                for r in rates: r.add(None)
            if d.valuation.amount_usd is None: continue
            for i, counter in enumerate(COUNTERS): priced_counts[i] += getattr(d.record.tokens,counter)
            if e.state != 'available' or e.rounding_adjustment_usd is None:
                verified = False
                continue
            adjustment += e.rounding_adjustment_usd
            for i, c in enumerate(e.categories):
                charges[i] += c.unrounded_usd
    return {'input_tokens': str(result.total.tokens.input + result.total.tokens.cached + result.total.tokens.write5m + result.total.tokens.write1h),
            'categories': [{'category': name, 'tokens': str(counts[i]), 'priced_tokens': str(priced_counts[i]),
                            'rate_usd_per_million': money(next(iter(rates[i]))) if len(rates[i]) == 1 else None,
                            'mixed_rates': len(rates[i] - {None}) > 1,
                            'unrounded_priced_usd': money(charges[i]) if verified and result.total.value.amount_usd is not None else None}
                           for i, name in enumerate(CATEGORY_NAMES)],
            'rounding_adjustment_usd': money(adjustment) if verified and result.total.value.amount_usd is not None else None,
            'contribution_basis': 'priced_events_only',
            'pricing': pricing_breakdown(explain_values((d.valuation for d in result.details), snapshot.catalog, offset=offset, limit=limit))}


def daily_average(result):
    """Display-only means of authoritative whole-query facts, not valuations."""
    context=result.context
    start=min(r.start for _,r in context.ranges)
    end=max(r.end for _,r in context.ranges)
    zone=ZoneInfo(context.timezone)
    days=0 if end<=start else 1 if context.filters.selected_day else (
        datetime.fromtimestamp(end-0.000001,zone).date()-datetime.fromtimestamp(start,zone).date()).days+1
    def mean(value):
        if not days or not result.total.record_count or value is None:return None
        with localcontext(ARITHMETIC):
            return money((Decimal(value)/days).quantize(Decimal('.000000000000000001'),rounding=ROUND_HALF_EVEN))
    return {'calendar_days':days,'basis':'selected_calendar_days_including_empty',
            'rounding':'half_even_18_decimal_places','tokens_per_day':mean(result.total.tokens.total),
            'usd_per_day':mean(result.total.value.amount_usd),
            'app_credits_per_day':mean(app_credit_amount(result.total.value.amount_usd))}


def analysis(result, snapshot, *, offset=0, limit=8):
    # This reuses the authoritative credit service, including empty/partial and
    # event-before-aggregation semantics. No independent selection or repricing.
    credits = result.credits(publication_versions=snapshot.versions)
    return {'app_credit_amount': money(credits.total.amount),
            'daily_average': daily_average(result),
            'models': distributions(result, snapshot, 'models'),
            'projects': distributions(result, snapshot, 'projects'),
            'methodology': methodology(result, snapshot, offset=offset, limit=limit)}
