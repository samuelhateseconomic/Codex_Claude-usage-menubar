"""Plan B backend gates: disjoint facts, exact units, explicit scenarios and offline reuse."""
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal, localcontext
from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_credits as credits
import usage_valuation as usd
import usage_index as index
import usage_index_codec as codec
from usage_credit_contract import credit_result_data
from usage_reports import render_text_report
from usage_terminal import render_credit_summary
from usage_pricing_explanation import explain_event
from usage_service import build_usage_result, UsageFilters, DIMENSIONS
from usage_records import Tokens
import test_valuation as vf
import test_service as sf
import test_index as ix

D = Decimal
ROOT = Path(__file__).resolve().parents[1]


def native_catalog(**kwargs):
    return credits.CreditCatalog((credits.CreditRate('fixture-codex-model', '50', '2.5', '250',
        (('standard', D(1)), ('fast', D(2))), **kwargs),))


class ContextPolicyTests(unittest.TestCase):
    def test_default_context_scenario_changes_value_not_facts_and_discloses_conflict(self):
        event = vf.canonical(vf.record('gpt-6.1-sol', Tokens(280000, 1000)), context=280000)
        facts = asdict(event)
        new = usd.value_event(event)
        old_catalog = usd.build_catalog(context_policy=usd.LEGACY_CONTEXT)
        old = usd.value_event(event, old_catalog)
        self.assertEqual((new.amount_usd, old.amount_usd), (D('.570'), D('1.135')))
        self.assertEqual(asdict(event), facts)
        self.assertEqual(new.request_context_tokens, 280000)
        self.assertEqual(new.tier, 'standard')
        self.assertIn('below_threshold_context_assumed', new.assumptions)
        self.assertIn('recorded_context_exceeds_assumed_threshold', new.assumptions)
        self.assertNotIn('event_input_tier_compatibility', new.assumptions)
        self.assertIn('Below-threshold context assumed', usd.value_text(usd.aggregate_values((new,))))
        self.assertNotEqual(old.pricing_version, new.pricing_version)
        self.assertEqual(explain_event(old, old_catalog).categories[0].rate_usd_per_million, D(4))
        self.assertEqual(explain_event(new, usd.DEFAULT_CATALOG).categories[0].rate_usd_per_million, D(2))
        legacy_result = build_usage_result((event,), sf.context(), old_catalog)
        self.assertIn('policy ' + usd.LEGACY_POLICY_VERSION, render_text_report(legacy_result))

    def test_unknown_request_size_does_not_become_aggregate_context_or_observed_zero(self):
        event = vf.canonical(vf.record('gpt-6.1-sol', Tokens(280000, 1000)))
        value = usd.value_event(event)
        self.assertEqual(value.amount_usd, D('.570'))
        self.assertIsNone(value.request_context_tokens)
        self.assertEqual(value.request_context_source, 'not recorded')
        self.assertEqual(value.assumptions, ('below_threshold_context_assumed',))
        self.assertEqual(credits.normalize_value(value).amount, D('57'))

    def test_legacy_catalog_payload_roundtrips_byte_identically_and_mixed_policy_rejected(self):
        old = usd.build_catalog(context_policy=usd.LEGACY_CONTEXT)
        payload = codec.catalog_data(old)
        self.assertEqual(payload['policy_version'], 'decimal12-event-tier-compat-v1')
        restored = codec.catalog_from(json.loads(json.dumps(payload)))
        self.assertEqual(restored.version, old.version)
        self.assertEqual(codec.catalog_data(restored), payload)
        new = codec.catalog_from(codec.catalog_data(usd.DEFAULT_CATALOG))
        self.assertEqual(new.context_policy, usd.BELOW_THRESHOLD)
        item = vf.record('gpt-6.1-sol', Tokens(280000, 1000))
        with self.assertRaises(ValueError):
            usd.aggregate_values((usd.value_event(item, old), usd.value_event(item, new)))
        with self.assertRaises(ValueError):
            codec.catalog_from({**payload, 'policy_version': 'unknown'})


class CreditArithmeticTests(unittest.TestCase):
    def test_exact_monotone_aggregation_keeps_late_money_token_and_unit_bounds(self):
        from usage_records import Record
        from usage_valuation import MAX_TOKENS
        record=Record('Codex',0,'','','model',Tokens(1))
        first=credits.CreditValuation(record,None,credits.NATIVE_UNIT,usd.MAX_MONEY,'synthetic-v1',None,())
        one=credits.CreditValuation(record,None,credits.NATIVE_UNIT,D(1),'synthetic-v1',None,())
        with self.assertRaises(ValueError):credits.aggregate_credits((first,one),unit=credits.NATIVE_UNIT,version='synthetic-v1')
        maximum=credits.CreditValuation(replace(record,tokens=Tokens(MAX_TOKENS)),None,credits.NATIVE_UNIT,D(0),'synthetic-v1',None,())
        with self.assertRaises(ValueError):credits.aggregate_credits((maximum,one),unit=credits.NATIVE_UNIT,version='synthetic-v1')
        wrong=replace(one,unit=credits.APP_UNIT)
        with self.assertRaises(ValueError):credits.aggregate_credits((one,wrong),unit=credits.NATIVE_UNIT,version='synthetic-v1')
        changed=replace(one,version='other-version')
        with self.assertRaises(ValueError):credits.aggregate_credits((one,changed),unit=credits.NATIVE_UNIT,version='synthetic-v1')

    def test_native_categories_reasoning_effort_and_evidenced_speed(self):
        event = vf.canonical(replace(vf.record(tokens=Tokens(1000000, 100000, 2000000)), reasoning_tokens=30000))
        facts = asdict(event)
        catalog = native_catalog()
        standard = credits.value_native(event, catalog, evidence=credits.CreditEvidence('standard', 'fixture event speed'))
        fast = credits.value_native(event, catalog, evidence=credits.CreditEvidence('fast', 'fixture event speed'))
        self.assertEqual((standard.amount, fast.amount), (D(80), D(160)))
        self.assertEqual(asdict(event), facts)
        changed_effort = replace(event, record=replace(event.record, effort='ultra', reasoning_tokens=None))
        self.assertEqual(credits.value_native(changed_effort, catalog, evidence=standard.evidence).amount, standard.amount)
        self.assertIn('hypothetical_paid_credit_equivalent', standard.assumptions)
        self.assertIn('current_rate_counterfactual', standard.assumptions)
        self.assertEqual(standard.rounding_adjustment, D(0))

    def test_official_snapshot_matches_independent_worked_values_and_exact_models(self):
        event = vf.record('gpt-6.1-sol', Tokens(10000, 1000, 20000))
        for speed, expected in [('standard', '.8'), ('fast', '1.6'), ('ultrafast', '4.8')]:
            value = credits.value_native(event, speed_assumption=speed)
            self.assertEqual(value.amount, D(expected))
            self.assertIn('speed_' + speed + '_assumed', value.assumptions)
        dated = replace(event, model='gpt-6.1-sol-20261026')
        self.assertIsNone(credits.value_native(dated, speed_assumption='standard').amount)
        self.assertIsNone(credits.value_native(replace(event, model='gpt-5.4'), speed_assumption='standard').amount)

    def test_unknown_speed_billing_and_unsupported_categories_remain_distinct(self):
        event = vf.record('gpt-6.1-sol', Tokens(10, 1, 20))
        self.assertEqual(credits.value_native(event).unpriced_reason, 'speed_not_recorded')
        assumed = credits.value_native(event, speed_assumption='standard')
        recorded = credits.value_native(event, evidence=credits.CreditEvidence('fast', 'event speed', 'api_key', 'event auth kind'), speed_assumption='standard')
        self.assertNotIn('speed_standard_assumed', recorded.assumptions)
        self.assertEqual(recorded.amount, assumed.amount * 2)
        self.assertIn('hypothetical_paid_credit_equivalent', recorded.assumptions)
        self.assertEqual(credits.value_native(replace(event, tokens=Tokens(10, 1, 20, 5)), speed_assumption='standard').unpriced_reason,
                         'credit_cache_write_mapping_unavailable')
        self.assertEqual(credits.value_native(replace(event, provider='Claude'), speed_assumption='standard').unpriced_reason,
                         'provider_credit_rate_unavailable')
        self.assertEqual(credits.value_native(replace(event, model='gpt-6-luna'), speed_assumption='ultrafast').unpriced_reason,
                         'speed_credit_rate_unavailable')
        with self.assertRaises(ValueError):
            credits.CreditEvidence('fast')
        with self.assertRaises(ValueError):
            credits.CreditEvidence(billing_source='included_plan')

    def test_effective_rates_use_utc_interval_and_current_card_is_not_backdated(self):
        event = vf.record(tokens=Tokens(1))
        current = credits.value_native(event, native_catalog(), speed_assumption='standard')
        self.assertIn('current_rate_counterfactual', current.assumptions)
        historical = native_catalog(effective_from='2026-10-01', effective_until='2026-10-24')
        self.assertIsNotNone(credits.value_native(event, historical, speed_assumption='standard').amount)
        expired = native_catalog(effective_from='2026-10-01', effective_until='2026-10-23')
        self.assertEqual(credits.value_native(event, expired, speed_assumption='standard').unpriced_reason,
                         'historical_credit_rate_unavailable')

    def test_app_normalization_is_exact_and_inherits_policy_coverage_and_override(self):
        event = vf.record(tokens=Tokens(1))
        source = usd.value_event(event, vf.fixture_catalog())
        source = replace(source, amount_usd=D('16.224690800000'), assumptions=('fixture_assumption',))
        native = credits.normalize_value(source)
        self.assertEqual(native.amount, D('1622.46908'))
        self.assertEqual(native.amount * credits.APP_UNIT_USD, source.amount_usd)
        self.assertEqual(native.assumptions, source.assumptions)
        self.assertEqual(native.usd_pricing_version, source.pricing_version)
        summary = credits.aggregate_credits((native,), unit=native.unit, version=native.version)
        self.assertEqual(credits.credit_text(summary), '1,622.47')
        tiny = credits.normalize_value(replace(source, amount_usd=D('.000000000001')))
        self.assertEqual(tiny.amount, D('.0000000001'))
        self.assertEqual(credits.credit_text(credits.aggregate_credits((tiny,), unit=tiny.unit, version=tiny.version)), '<0.01')
        unavailable = credits.normalize_value(usd.value_event(replace(event, model='unpriced')))
        self.assertIsNone(unavailable.amount)
        zero = credits.normalize_value(usd.value_event(event, usd.build_catalog({event.model: usd.Price(0, 0, 0)})))
        self.assertEqual(zero.amount, D(0))
        self.assertNotEqual(zero.version, native.version)

    def test_rounding_is_once_per_event_not_display_and_ambient_context_is_ignored(self):
        catalog = credits.CreditCatalog((credits.CreditRate('tiny', '.0000005', '0', '0'),))
        values = [credits.value_native(vf.record('tiny', Tokens(1)), catalog, speed_assumption='standard') for _ in range(3)]
        self.assertEqual([v.amount for v in values], [D('0.000000000000')] * 3)
        self.assertEqual(values[0].rounding_adjustment, D('-.0000000000005'))
        with localcontext() as ctx:
            ctx.prec = 2
            large = credits.normalize_value(replace(usd.value_event(vf.record(), vf.fixture_catalog()), amount_usd=usd.MAX_MONEY))
            self.assertEqual(large.amount, credits.MAX_APP_CREDITS)
            summary = credits.aggregate_credits((large,), unit=large.unit, version=large.version)
            self.assertEqual(summary.amount, credits.MAX_APP_CREDITS)
        with self.assertRaises(ValueError):
            credits.aggregate_credits((large, large), unit=large.unit, version=large.version)
        for rate in ('NaN', '-1', '1000000001', '.0000000000001', True):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                credits.CreditRate('bad', rate, 0, 0)

    def test_summary_empty_unpriced_partial_zero_and_mixed_units_versions(self):
        base = vf.record('gpt-6.1-sol', Tokens(100, 10, 50))
        yes = credits.value_native(base, speed_assumption='standard')
        no = credits.value_native(replace(base, model='unknown'), speed_assumption='standard')
        zero_catalog = credits.CreditCatalog((credits.CreditRate(base.model, 0, 0, 0),))
        zero = credits.value_native(base, zero_catalog, speed_assumption='standard')
        for values, state, amount in [((), 'empty', None), ((no,), 'unpriced', None),
                ((yes, no), 'partial', yes.amount), ((zero,), 'complete', D(0))]:
            version = values[0].version if values else yes.version
            summary = credits.aggregate_credits(values, unit=credits.NATIVE_UNIT, version=version)
            self.assertEqual((summary.state, summary.amount), (state, amount))
        for other in (zero, credits.normalize_value(usd.value_event(base))):
            with self.assertRaises(ValueError):
                credits.aggregate_credits((yes, other), unit=yes.unit, version=yes.version)
        with self.assertRaises(ValueError):
            replace(yes, amount=D('NaN'))


class CreditServiceTests(unittest.TestCase):
    def result(self, ctx=None):
        return build_usage_result(sf.fixture(), ctx or sf.context(), sf.catalog())

    def test_every_partition_and_detail_agree_with_usd_and_exact_facts(self):
        usage = self.result()
        result = usage.credits()
        self.assertEqual(result.total.amount, D('1889.1'))
        self.assertEqual(result.total.tokens, usage.total.tokens)
        for dimension in DIMENSIONS:
            self.assertEqual(sum(g.summary.amount for g in result.groups_for(dimension)), result.total.amount)
            self.assertEqual(sorted(key for g in result.groups_for(dimension) for key in g.detail_ids),
                             sorted(d.detail_id for d in result.details))
        self.assertEqual(sum(d.valuation.amount for d in result.details), result.total.amount)
        with self.assertRaises(FrozenInstanceError):
            result.total.amount = D(0)

    def test_filter_context_publication_and_policy_identity_are_isolated(self):
        usage = self.result()
        first = usage.credits(publication_versions=('dataset', 1))
        second = usage.credits(publication_versions=('dataset', 2))
        self.assertNotEqual(first.context_id, second.context_id)
        self.assertEqual(first.total, second.total)
        filtered = self.result(sf.context(filters=UsageFilters(models=('fixture-codex',)))).credits()
        self.assertEqual(filtered.total.amount, D('1842'))
        self.assertEqual(filtered.usage.combined_comparison.reason, 'filtered_query')
        native = usage.credits(unit=credits.NATIVE_UNIT, speed_assumption='standard')
        self.assertEqual(native.total.state, 'unpriced')
        self.assertNotEqual(native.context_id, first.context_id)
        with self.assertRaises(ValueError):
            usage.credits(evidence={'label': credits.CreditEvidence()})
        with self.assertRaises(ValueError):
            usage.credits(speed_assumption='standard')
        empty = build_usage_result((), sf.context()).credits()
        self.assertEqual(empty.total.state, 'empty')

    def test_native_query_reuses_full_identity_membership_and_preserves_evidence(self):
        events = tuple(replace(event, record=replace(event.record, model='gpt-6.1-sol'))
                       for event in sf.fixture())
        usage = build_usage_result(events, sf.context())
        evidence = {usage.details[0].detail_id: credits.CreditEvidence('fast', 'fixture per-event speed')}
        result = usage.credits(unit=credits.NATIVE_UNIT, evidence=evidence)
        self.assertEqual(result.total.state, 'partial')
        self.assertEqual(result.total.amount, D('921.000000000000'))
        self.assertEqual(result.total.unpriced_records, 1)
        for dimension in DIMENSIONS:
            with localcontext(usd.ARITHMETIC):
                self.assertEqual(sum((g.summary.amount or D(0) for g in result.groups_for(dimension))), result.total.amount)
        self.assertEqual(result.details[0].valuation.evidence, evidence[usage.details[0].detail_id])
        self.assertNotEqual(result.context_id, usage.credits(unit=credits.NATIVE_UNIT, speed_assumption='standard').context_id)

    def test_allowlisted_export_preserves_subsets_without_identifiers_or_false_fees(self):
        data = credit_result_data(self.result().credits())
        tokens = data['summary']['tokens']
        self.assertEqual(tokens['input'], '1055000')
        self.assertEqual(tokens['output'], '1850000')
        self.assertEqual(tokens['reasoning'], '1260000')
        self.assertEqual(data['summary']['reasoning_coverage'], {'known_records': 1, 'unknown_records': 1})
        self.assertEqual(data['usd_comparison']['difference_usd'], '-21.109000000000')
        serialized = json.dumps(data)
        self.assertNotIn('same-session', serialized)
        self.assertNotIn('same-project', serialized)
        self.assertNotIn('detail_ids', serialized)
        self.assertEqual(data['unit_definition_usd'], '0.01')
        text = render_credit_summary(self.result().credits())
        self.assertIn('Tokens: 2.91M', text)
        self.assertIn('Output: 1.85M', text)
        self.assertIn('1 records lack reasoning metadata', text)
        self.assertNotIn('same-session', text)
        self.assertNotIn('same-project', text)

    def test_direct_context_identity_includes_explicit_fees_source_health_and_token_facts(self):
        usage = self.result()
        before = usage.credits()
        changed_fee = build_usage_result(sf.fixture(), sf.context(), sf.catalog(),
                                        fees={'Codex': D(100), 'Claude': D(20)}).credits()
        self.assertEqual(changed_fee.total.amount, before.total.amount)
        self.assertNotEqual(changed_fee.context_id, before.context_id)
        stale = replace(usage, sources=tuple(replace(s, state='stale') for s in usage.sources)).credits()
        self.assertNotEqual(stale.context_id, before.context_id)
        event = sf.fixture()[0]
        one = replace(event, record=replace(event.record, tokens=Tokens(100), reasoning_tokens=None))
        two = replace(event, record=replace(event.record, tokens=Tokens(cached=2000), reasoning_tokens=None))
        left = build_usage_result((one,), sf.context(), sf.catalog()).credits()
        right = build_usage_result((two,), sf.context(), sf.catalog()).credits()
        self.assertEqual(left.total.amount, right.total.amount)
        self.assertEqual(left.details[0].detail_id, right.details[0].detail_id)
        self.assertNotEqual(left.context_id, right.context_id)
        changed_effort = replace(one, record=replace(one.record, effort='ultra'))
        grouped = build_usage_result((changed_effort,), sf.context(), sf.catalog()).credits()
        self.assertEqual(grouped.total.amount, left.total.amount)
        self.assertNotEqual(grouped.context_id, left.context_id)


class CreditIndexTests(ix.IndexFixture):
    def test_old_policy_restart_reprice_and_readonly_query_keep_facts_and_publications(self):
        self.write(events=[ix.counter(280000, 10, output=1000)], model='gpt-6.1-sol')
        old_catalog = usd.build_catalog(dict(self.settings.rate_overrides), context_policy=usd.LEGACY_CONTEXT)
        with patch.object(index, 'build_catalog', return_value=old_catalog):
            self.store.import_settings()
        old_snapshot = self.store.read_snapshot()
        old = old_snapshot.query_credits(ix.context())
        self.assertEqual(old.total.amount, D('113.5'))
        event_rows = self.rows('SELECT id,payload FROM events ORDER BY id')
        observation_rows = self.rows('SELECT id,payload FROM observations ORDER BY id')
        old_catalog_payload = self.rows('SELECT payload FROM catalogs WHERE version=?', (old_snapshot.pricing_version,))
        self.store = index.UsageIndex(self.path, config_path=self.config)
        self.assertEqual(self.store.query(ix.context()).result.credits().total.amount, old.total.amount)
        self.store.reprice()
        fresh_snapshot = self.store.read_snapshot()
        fresh = fresh_snapshot.query_credits(ix.context())
        self.assertEqual(fresh.total.amount, D('57'))
        self.assertNotEqual(old.context_id, fresh.context_id)
        self.assertEqual(old_snapshot.query_credits(ix.context()), old)
        self.assertEqual(self.rows('SELECT id,payload FROM events ORDER BY id'), event_rows)
        self.assertEqual(self.rows('SELECT id,payload FROM observations ORDER BY id'), observation_rows)
        self.assertEqual(self.rows('SELECT payload FROM catalogs WHERE version=?', (old_snapshot.pricing_version,)), old_catalog_payload)
        before = self.rows('SELECT * FROM datasets')
        with patch.object(index, 'initialize', side_effect=AssertionError('query must not initialize')):
            reopened = index.UsageIndex.read_existing_snapshot(self.path)
        self.assertEqual(reopened.query_credits(ix.context()).total.amount, fresh.total.amount)
        self.assertEqual(self.rows('SELECT * FROM datasets'), before)
        self.store.import_settings()
        self.assertEqual(self.store.query(ix.context()).result.credits().total.amount, fresh.total.amount)

    def test_failed_reprice_retains_coherent_prior_values_and_tokens(self):
        self.write(events=[ix.counter(100, 10)])
        self.store.import_settings()
        before = self.store.read_snapshot().query_credits(ix.context())
        def fail(stage):
            if stage == 'valued':
                raise RuntimeError('fixture failure')
        with self.assertRaises(RuntimeError):
            self.store.reprice(fault=fail)
        after = self.store.read_snapshot().query_credits(ix.context())
        self.assertEqual(before.total, after.total)
        self.assertEqual(before.usage.details, after.usage.details)

    def test_cli_reads_committed_index_offline_and_validates_explicit_source_selection(self):
        self.write(events=[ix.counter(100, 10)], model='gpt-6.1-sol')
        self.store.import_settings()
        before = self.rows('SELECT * FROM runs')
        run = subprocess.run([sys.executable, str(ROOT/'usage_credit_cli.py'), '--index', str(self.path),
            '--format', 'json', '--timezone', 'UTC'], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(data['contract_version'], 'usage-credit-summary-v1')
        self.assertEqual(self.rows('SELECT * FROM runs'), before)
        self.assertNotIn(str(self.base), run.stdout)
        native = subprocess.run([sys.executable, str(ROOT/'usage_credit_cli.py'), '--index', str(self.path),
            '--format', 'json', '--timezone', 'UTC', '--provider', 'codex', '--unit', 'codex',
            '--native-speed-scenario', 'standard'], capture_output=True, text=True, timeout=15)
        self.assertEqual(native.returncode, 0, native.stderr)
        self.assertEqual(json.loads(native.stdout)['summary']['amount'], '0.005000000000')
        self.assertEqual(self.rows('SELECT * FROM runs'), before)
        invalid = subprocess.run([sys.executable, str(ROOT/'usage_credit_cli.py'), '--scan'], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(invalid.returncode, 0)
        missing = self.base/'missing.sqlite3'
        failed = subprocess.run([sys.executable, str(ROOT/'usage_credit_cli.py'), '--index', str(missing)], capture_output=True, text=True, timeout=15)
        self.assertEqual(failed.returncode, 1)
        self.assertFalse(missing.exists())
        self.assertNotIn(str(self.base), failed.stderr)
        config = subprocess.run([sys.executable, str(ROOT/'usage_credit_cli.py'), '--config', str(self.base/'missing.json')],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(config.returncode, 1)
        self.assertNotIn(str(self.base), config.stderr)


if __name__ == '__main__':
    unittest.main()
