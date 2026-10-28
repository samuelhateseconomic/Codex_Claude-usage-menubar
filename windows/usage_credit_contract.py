"""Allowlisted headless credit export. This is not a new dashboard HTTP response."""
from usage_credits import APP_UNIT, APP_UNIT_USD, CREDIT_POLICY
from usage_api_contract import money, utc

CONTRACT_VERSION = 'usage-credit-summary-v1'


def summary_data(value, reasoning):
    tokens = value.tokens
    return {'state': value.state, 'unit': value.unit, 'amount': money(value.amount),
        'tokens': {'total': str(tokens.total), 'input': str(tokens.input + tokens.cached + tokens.write5m + tokens.write1h),
                   'uncached_input': str(tokens.input), 'cached_input': str(tokens.cached),
                   'cache_write_5m': str(tokens.write5m), 'cache_write_1h': str(tokens.write1h),
                   'output': str(tokens.output), 'reasoning': None if reasoning.known_tokens is None else str(reasoning.known_tokens)},
        'reasoning_coverage': {'known_records': reasoning.known_records, 'unknown_records': reasoning.unknown_records},
        'priced_records': value.priced_records, 'unpriced_records': value.unpriced_records,
        'priced_tokens': str(value.priced_tokens), 'unpriced_tokens': str(value.unpriced_tokens),
        'assumed_records': value.assumed_records, 'assumptions': list(value.assumptions),
        'unpriced_reasons': dict(value.reasons)}


def credit_result_data(result):
    """No paths, conversation IDs, event graph, raw metadata or credentials."""
    usage, context = result.usage, result.usage.context
    providers = {group.key[0]: group for group in usage.groups_for('provider')}
    return {'contract_version': CONTRACT_VERSION, 'query_context_id': result.context_id,
        'scope': context.scope, 'basis': 'estimated_api_value' if result.unit == APP_UNIT else 'estimated_paid_credit_equivalent',
        'unit_definition_usd': money(APP_UNIT_USD) if result.unit == APP_UNIT else None,
        'policy_version': CREDIT_POLICY, 'credit_valuation_version': result.version,
        'credit_catalog_version': None if result.catalog is None else result.catalog.version,
        'usd_pricing_version': usage.catalog.version, 'usd_policy_version': usage.catalog.policy_version,
        'usd_speed_basis': 'standard_api_list_price_equivalent_not_observed_speed',
        'context_policy': usage.catalog.context_policy, 'speed_assumption': result.speed_assumption,
        'timezone_source': 'frozen_context',
        'period': context.period, 'timezone': context.timezone, 'captured_at': utc(context.captured_at),
        'ranges': [{'provider': p.lower(), 'start': utc(r.start), 'end': utc(r.end), 'boundary': r.boundary_policy}
                   for p, r in context.ranges],
        'summary': summary_data(result.total, usage.total.reasoning),
        'providers': [{'provider': group.key[0].lower(),
                       'summary': summary_data(group.summary, providers[group.key[0]].summary.reasoning)}
                      for group in result.groups_for('provider')],
        'source_health': [{'provider': source.provider.lower(), 'state': source.state,
            'scan_issues': sum(source.issue_counts.values()), 'accounting_issues': len(source.accounting_issues)}
            for source in usage.sources],
        'rate_snapshot': [] if result.catalog is None else [rate.payload() for rate in result.catalog.entries],
        'qualifications': ['estimate_not_actual_spend_or_allowance', 'local_coverage_not_complete_account_usage',
                           'token_only_estimate_excludes_unrecorded_non_token_charges'],
        'usd_comparison': {'available': usage.combined_comparison.available,
            'reason': usage.combined_comparison.reason, 'value_usd': money(usage.combined_comparison.value_usd),
            'fee_usd': money(usage.combined_comparison.fee_usd),
            'difference_usd': money(usage.combined_comparison.difference_usd)}}
