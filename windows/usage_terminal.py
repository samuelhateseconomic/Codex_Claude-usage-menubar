"""Compact and paged terminal projections of one immutable authoritative result."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
import unicodedata

from usage_privacy import display_text, metadata_label
from usage_service import DIMENSIONS
from usage_time import local_datetime
from usage_valuation import ARITHMETIC, PRICE_DATE, money_text


def token_label(value):
    """Display only: preserve thousands, abbreviate millions/billions exactly."""
    if value < 1_000_000:
        return f'{value:,}'
    with localcontext(ARITHMETIC):
        scale, suffix = (1_000_000_000, 'B') if value >= 1_000_000_000 else (1_000_000, 'M')
        number = (Decimal(value)/scale).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if number >= 1000 and suffix == 'M':
            number, suffix = (Decimal(value)/1_000_000_000).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'B'
        return format(number,'f').rstrip('0').rstrip('.') + suffix


def cell_width(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in value)


def wrap_line(value, width):
    # Controls/bidi are made visible before wrapping; source identity is untouched.
    value = display_text(value)
    lines, line = [], ''
    for word in value.split():
        candidate = line + (' ' if line else '') + word
        if cell_width(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ''
        for char in word:
            if line and cell_width(line + char) > width:
                lines.append(line)
                line = ''
            line += char
    return [*lines,line] if line else lines or ['']


def value_label(value):
    if value.state == 'empty':
        return 'Unavailable (no usage records)'
    if value.state == 'unpriced':
        return 'Unavailable (all usage unpriced)'
    return money_text(value.amount_usd,4) + (' (priced subtotal only)' if value.state == 'partial' else '')


REASONS = {
    'not_month_to_date':'choose calendar month to date',
    'filtered_query':'metadata-filtered query',
    'range_not_calendar_month_to_date':'range is not calendar month to date',
    'no_usage_records':'no local usage records',
    'fee_not_configured':'monthly fee not configured',
    'all_usage_unpriced':'all usage unpriced',
    'selected_provider_unavailable':'one or more selected providers unavailable',
}


def render_terminal(result, *, dimension=None, page=1, page_size=10, width=80, include_metadata=False):
    """No scans, provider requests, repricing or aggregation occur in this renderer."""
    if type(width) is not int or not 40 <= width <= 160:
        raise ValueError('Terminal width must be 40..160.')
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise ValueError('Use page >= 1 and page size 1..50.')
    if dimension is not None and dimension not in DIMENSIONS:
        raise ValueError('Unsupported detail grouping.')
    context, total = result.context, result.total
    tokens, value = total.tokens, total.value
    title = {'month':'Month to date','today':'Today','week':'Last 7 days (168 hours)',
             'session':'Session / last 5 hours'}[context.period]
    lines = ['USAGE TRAY - ESTIMATED API VALUE',
             title + ' | ' + ' + '.join(context.providers) + ' | USD',
             'DEMO: sample data; no local logs or accounts accessed.' if context.demo else
             'Local logs: all available unmatched accounts; coverage is limited.']
    starts = {r.start for _,r in context.ranges}
    end = local_datetime(context.captured_at,context.timezone).strftime('%Y-%m-%d %H:%M:%S %z')
    if len(starts)==1:
        start = local_datetime(next(iter(starts)),context.timezone).strftime('%Y-%m-%d %H:%M:%S %z')
        lines.append(f'Range: [{start}, {end}) {context.timezone}')
    else:
        for provider,r in context.ranges:
            start=local_datetime(r.start,context.timezone).strftime('%m-%d %H:%M:%S %z')
            lines.append(f'{provider}: [{start}, {end}) {context.timezone}')
    if context.period=='session':
        lines.append('Boundary: ' + '; '.join(dict.fromkeys(r.label for _,r in context.ranges)))
    lines += ['', 'Estimated API value: ' + value_label(value),
              f'Pricing coverage: {value.state}; unpriced tokens {token_label(value.unpriced_tokens)}',
              f'Recorded tokens: {token_label(tokens.total)} | {total.record_count:,} records | {total.conversation_count:,} conversations',
              f'Input {token_label(tokens.input)} | Output {token_label(tokens.output)} (includes reasoning)',
              f'Cache read {token_label(tokens.cached)} | Writes 5m {token_label(tokens.write5m)} / 1h {token_label(tokens.write1h)}',
              'Cache reads reuse input context; counted once, separate from output.']
    if value.state == 'empty':
        lines.append('No local records; this does not establish zero account usage.')
    reasoning = total.reasoning
    known = 'not recorded' if reasoning.known_tokens is None else token_label(reasoning.known_tokens)
    lines.append('Reasoning subset of output: ' + known + (f'; unknown for {reasoning.unknown_records:,} records' if reasoning.unknown_records else ''))
    lines.append('')
    if context.period == 'month' and not context.is_filtered:
        lines.append('Plan comparison: API value minus full monthly fee')
        for comparison in (*result.comparisons, *((result.combined_comparison,) if len(context.providers)>1 else ())):
            fee = 'unavailable' if comparison.fee_usd is None else money_text(comparison.fee_usd,2)
            if comparison.available:
                lines.append(f'{comparison.provider}: API {money_text(comparison.value_usd,4)} | Monthly plan {fee} | Difference {money_text(comparison.difference_usd,2,signed=True)}')
            else:
                lines.append(f'{comparison.provider}: Monthly plan {fee} | Difference unavailable ({REASONS.get(comparison.reason,"scope unavailable")})')
        if value.state == 'partial':
            lines.append('Differences use priced usage only; unpriced usage is excluded.')
        lines.append('Full calendar-month fees; estimates, not bills or realized savings.')
    else:
        reason = result.combined_comparison.reason
        lines.append('Plan comparison unavailable: ' + REASONS.get(reason,'choose unfiltered calendar month to date') + '.')
        lines.append('API-equivalent estimates are not actual subscription charges.')
    lines.append('')
    for source in result.sources:
        scan = sum(source.issue_counts.values())
        counter = len(source.accounting_issues)
        lines.append(f'{source.provider} source: {source.state} | scan issues {scan:,} | counter issues {counter:,}')
    lines += [f'Tier/TTL assumptions: {value.assumed_records:,} records; unknown effort: {result.missing_effort_records:,}.',
              'Captured at range end; live limits are separate (active CLI account).',
              f'Rates snapshot {PRICE_DATE}; app {result.app_version}. Exact counts/rates: --audit.']
    if dimension is not None:
        groups=result.groups_for(dimension,'value_desc')
        pages=max(1,(len(groups)+page_size-1)//page_size)
        if page>pages:
            raise ValueError('Detail page is outside the matched result.')
        first=(page-1)*page_size
        lines += ['', f'DETAILS: {dimension} | page {page}/{pages} | {len(groups):,} groups',
                  'Ranked by priced contribution; unpriced groups follow priced groups.',
                  'Partial values are priced subtotals; headline covers all matched groups.']
        if not groups:
            lines.append('No matched groups; this does not establish zero account usage.')
        for index,group in enumerate(groups[first:first+page_size],first+1):
            labels=[]
            for i,label in enumerate(group.key):
                if i and dimension in ('project','conversation'):
                    label=metadata_label(label,'project' if dimension=='project' else 'id',include_metadata)
                labels.append(label)
            t=group.summary.tokens
            lines += [f'{index}. ' + ' / '.join(labels),
                      value_label(group.summary.value) + f' | {token_label(t.total)} tokens | {group.summary.record_count:,} records',
                      f'Input {token_label(t.input)} / Output {token_label(t.output)} / Read {token_label(t.cached)} / Write 5m {token_label(t.write5m)} / 1h {token_label(t.write1h)}']
        lines.append('Full paths/IDs included; review before sharing.' if include_metadata else
                     'Reduced metadata; abbreviated labels are not anonymization.')
        lines.append('Navigation: --page N; change --details GROUP; omit --details for summary.')
    else:
        lines.append('Details: --details model|project|conversation|day; full report: --audit.')
    return '\n'.join(line for value in lines for line in wrap_line(value,width))+'\n'
