"""Frozen-catalog pricing explanations with independent exact expectations."""
from dataclasses import replace
from decimal import Decimal as D, localcontext
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_valuation import record, canonical
from usage_records import Tokens
from usage_valuation import Price, build_catalog, value_event
from usage_pricing_explanation import explain_event, explain_values, CATEGORY_NAMES


class PricingExplanationTests(unittest.TestCase):
    def test_five_categories_exact_cache_writes_and_reasoning_subset(self):
        catalog = build_catalog({'fixture': Price('4','20','.2','5','8')})
        event = canonical(replace(record('fixture',Tokens(10000,20000,30000,5000,7000)),reasoning_tokens=19000))
        value = value_event(event,catalog)
        detail = explain_event(value,catalog)
        self.assertEqual(detail.state,'available')
        self.assertEqual([c.category for c in detail.categories],list(CATEGORY_NAMES))
        self.assertEqual([c.rate_usd_per_million for c in detail.categories],list(map(D,['4','20','.2','5','8'])))
        self.assertEqual([c.unrounded_usd for c in detail.categories],list(map(D,['.04','.4','.006','.025','.056'])))
        self.assertEqual(value.amount_usd,D('.527000000000'))
        self.assertEqual(sum(c.unrounded_usd for c in detail.categories)+detail.rounding_adjustment_usd,value.amount_usd)
        self.assertEqual(explain_values([value],catalog).groups[0].reasoning_tokens,19000)
        self.assertEqual(sum(c.tokens for c in detail.categories),72000)  # No extra reasoning charge.

    def test_half_even_event_rounding_and_group_adjustment_are_not_re_rounded(self):
        catalog = build_catalog({'fixture': Price('.0000005','0','0')})
        values = [value_event(canonical(record('fixture',Tokens(1,0,0))),catalog) for _ in range(3)]
        detail = explain_event(values[0],catalog)
        self.assertEqual(detail.categories[0].unrounded_usd,D('.0000000000005'))
        self.assertEqual(values[0].amount_usd,D('0'))
        self.assertEqual(detail.rounding_adjustment_usd,D('-.0000000000005'))
        group = explain_values(values,catalog).groups[0]
        self.assertEqual(group.summary.amount_usd,D('0'))
        self.assertEqual(group.explanation.rounding_adjustment_usd,D('-.0000000000015'))
        self.assertEqual(sum(c.unrounded_usd for c in group.explanation.categories)+group.explanation.rounding_adjustment_usd,D('0'))

    def test_missing_or_wrong_catalog_provenance_never_uses_current_rates(self):
        old = build_catalog({'fixture': Price('2','10','.1')})
        new = build_catalog({'fixture': Price('100','100','100')})
        value = value_event(canonical(record('fixture',Tokens(100,20,30))),old)
        for catalog in [None,new]:
            explanation = explain_event(value,catalog)
            self.assertEqual(explanation.reason,'pricing_provenance_unavailable')
            self.assertEqual(explanation.categories,())
        for field in ['rate_id','matched_model','source','catalog_version','override_version','policy_version','tier']:
            broken = replace(value,**{field:'missing-evidence'})
            self.assertEqual(explain_event(broken,old).state,'unavailable',field)
        self.assertEqual(explain_event(replace(value,amount_usd=D('99')),old).reason,'valuation_evidence_mismatch')
        self.assertEqual(explain_event(value,old).categories[0].rate_usd_per_million,D('2'))

    def test_tiers_context_assumptions_dated_mapping_and_mixed_models(self):
        catalog = build_catalog({'fixture': Price('2','10','.1',threshold=100,high=('4','15','.2')),
                                 'other': Price('1','1','1')})
        base = record('fixture-20261023',Tokens(100,20,30))
        low = value_event(canonical(base,context=100),catalog)
        high = value_event(canonical(base,context=101),catalog)
        assumed = value_event(canonical(base),catalog)
        other = value_event(canonical(record('other',Tokens(10,0,0))),catalog)
        self.assertEqual(low.model_mapping,'dated_snapshot')
        self.assertEqual(high.tier,'high_context')
        self.assertEqual(explain_event(low,catalog).categories[0].rate_usd_per_million,D('2'))
        self.assertEqual(explain_event(high,catalog).categories[0].rate_usd_per_million,D('4'))
        self.assertIn('event_input_tier_compatibility',assumed.assumptions)
        breakdown = explain_values([low,high,assumed,other],catalog)
        self.assertEqual(breakdown.group_count,4)
        self.assertEqual(breakdown.shown_record_count,4)
        self.assertEqual(sum(g.summary.amount_usd for g in breakdown.groups),low.amount_usd+high.amount_usd+assumed.amount_usd+other.amount_usd)

    def test_unpriced_missing_write_rate_and_explicit_zero_are_distinct(self):
        catalog = build_catalog({'fixture': Price('2','10','.1'),'free': Price(0,0,0,0,0)})
        unknown = value_event(canonical(record('unknown',Tokens(10,0,0))),catalog)
        missing = value_event(canonical(record('fixture',Tokens(10,20,30,5,0))),catalog)
        zero = value_event(canonical(record('free',Tokens(10,20,30,5,7))),catalog)
        self.assertEqual(explain_event(unknown,catalog).reason,'model_rate_unavailable')
        detail = explain_event(missing,catalog)
        self.assertEqual(detail.state,'available')  # Known partial rates, event remains unpriced.
        self.assertIsNone(detail.categories[3].rate_usd_per_million)
        self.assertIsNone(detail.categories[3].unrounded_usd)
        self.assertEqual(detail.categories[4].unrounded_usd,D(0))  # No inactive-category charge.
        self.assertIsNone(detail.rounding_adjustment_usd)
        self.assertIsNone(missing.amount_usd)
        self.assertEqual(zero.amount_usd,D(0))
        self.assertTrue(all(c.rate_usd_per_million == D(0) for c in explain_event(zero,catalog).categories))

    def test_bounded_groups_empty_and_precision_independent_of_decimal_context(self):
        catalog = build_catalog({f'model-{i}':Price(str(i),'0','0') for i in range(12)})
        values = [value_event(canonical(record(f'model-{i}',Tokens(100,0,0))),catalog) for i in range(12)]
        with localcontext() as ctx:
            ctx.prec = 4
            breakdown = explain_values(values+values[:2],catalog)
        self.assertEqual((breakdown.group_count,len(breakdown.groups),breakdown.total_record_count,breakdown.shown_record_count),(12,8,14,10))
        self.assertEqual(explain_values([],catalog).groups,())
        self.assertEqual(explain_values([],catalog).group_count,0)


if __name__ == '__main__': unittest.main()
