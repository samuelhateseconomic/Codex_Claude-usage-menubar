from dataclasses import asdict, replace
from decimal import Decimal, localcontext
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_valuation as val
import usage_reports as reports
from usage_records import Record, Tokens
from usage_observations import CanonicalEvent, SourceRef
from usage_time import resolve_range

NOW = 1792785600
D = Decimal


def record(model="fixture-codex-model", tokens=None, provider="Codex"):
    return Record(provider, NOW - 1, "synthetic", "synthetic-project", model,
                  tokens or Tokens(10000, 1830000, 1000000), reasoning_tokens=1260000 if tokens is None else None)


def canonical(item, context=None, quality=()):
    return CanonicalEvent("synthetic-conversation", "epoch", "event",
                          "claude_message" if item.provider == "Claude" else "codex_cumulative_delta", item,
                          (SourceRef("synthetic-source", 1, "generation"),), quality,
                          request_context_tokens=context,
                          request_context_source="fixture request input" if context is not None else "not recorded")


def fixture_catalog():
    return val.build_catalog({"fixture-codex-model": val.Price("2", "10", "0.1"),
                              "fixture-claude-model": val.Price("4", "20", "0.2", "5", "8")})


def fixture_events():
    return (canonical(record()), canonical(record("fixture-claude-model", Tokens(10000,20000,30000,5000,0), "Claude")))


class ExactValuationTests(unittest.TestCase):
    def test_integration_fixture_exact_categories_values_and_fees(self):
        catalog = fixture_catalog()
        events = fixture_events()
        values = tuple(val.value_event(e, catalog) for e in events)
        self.assertEqual([v.amount_usd for v in values], [D("18.420000000000"), D("0.471000000000")])
        self.assertEqual([v.record.tokens.total for v in values], [2840000, 65000])
        summary = val.aggregate_values(values)
        self.assertEqual(summary.tokens.total, 2905000)
        self.assertEqual(summary.amount_usd, D("18.891000000000"))
        self.assertEqual(summary.state, "complete")
        self.assertEqual(summary.assumptions, ())  # Synthetic fixture has no tier rule.
        rows, combined = val.compare_plans(values, val.ComparisonScope(("Codex","Claude"),"month",True))
        self.assertEqual([r.difference_usd for r in rows], [D("-1.580000000000"),D("-19.529000000000")])
        self.assertEqual(combined.difference_usd,D("-21.109000000000"))
        self.assertEqual(combined.fee_usd,D("40.00"))
        self.assertNotIn("savings", " ".join(combined.qualifications))

    def test_empty_unpriced_partial_and_legitimate_priced_zero(self):
        catalog = fixture_catalog()
        known = val.value_event(fixture_events()[0],catalog)
        unknown = val.value_event(record("future-model",Tokens(500)),catalog)
        self.assertIsNone(unknown.amount_usd)
        self.assertEqual(unknown.state,"unpriced")
        self.assertIsNone(unknown.rate_id)
        for entries, state, amount in [((),"empty",None),((unknown,),"unpriced",None),
                                       ((known,unknown),"partial",D("18.42"))]:
            summary = val.aggregate_values(entries)
            self.assertEqual((summary.state,summary.amount_usd),(state,amount))
        partial = val.aggregate_values([known,unknown])
        self.assertEqual((partial.priced_records,partial.unpriced_records,partial.unpriced_tokens),(1,1,500))
        zero = val.value_event(record(),val.build_catalog({"fixture-codex-model":val.Price(0,0,0)}))
        summary = val.aggregate_values([zero])
        self.assertEqual((summary.state,summary.amount_usd),("complete",D("0.000000000000")))
        self.assertEqual(val.value_text(summary),"$0.0000")
        self.assertNotEqual(val.value_text(val.aggregate_values([])),val.value_text(val.aggregate_values([unknown])))

    def test_round_half_even_once_per_event_before_aggregation(self):
        catalog=val.build_catalog({"tiny":val.Price("0.0000005",0,0)})
        one=val.value_event(record("tiny",Tokens(1)),catalog)
        two=val.value_event(record("tiny",Tokens(2)),catalog)
        three=val.value_event(record("tiny",Tokens(3)),catalog)
        self.assertEqual(one.amount_usd,D("0.000000000000"))
        self.assertEqual(two.amount_usd,D("0.000000000001"))
        self.assertEqual(three.amount_usd,D("0.000000000002"))
        self.assertEqual(val.aggregate_values([one,one]).amount_usd,D(0))
        self.assertNotEqual(val.aggregate_values([one,one]).amount_usd,two.amount_usd)
        self.assertEqual(val.aggregate_values([two]*1000).amount_usd,D("0.000000001000"))
        self.assertEqual(val.value_text(val.aggregate_values([two])),"<$0.0001")

    def test_large_counts_beyond_float_safe_integer_are_exact(self):
        count=2**53+1
        value=val.value_event(record("large",Tokens(count)),val.build_catalog({"large":val.Price("1.000000000001",0,0)}))
        # Exact components: 9007199254.740993 + 0.009007199254740993.
        self.assertEqual(value.amount_usd,D("9007199254.750000199255"))
        summary=val.aggregate_values([value])
        self.assertEqual(summary.tokens.total,count)
        self.assertEqual(summary.priced_tokens,count)
        self.assertEqual(val.value_event(record("max",Tokens(val.MAX_TOKENS)),val.build_catalog({"max":val.Price(1000000000,0,0)})).amount_usd,
                         D("9223372036854775807000.000000000000"))

    def test_bounds_reject_invalid_rates_counts_and_aggregate_overflow(self):
        for value in (True,-1,"NaN","Infinity","0.0000000000001","1000000000.000000000001",{},"1"*129):
            with self.subTest(rate=value),self.assertRaises(ValueError):
                val.Price(value,0,0)
        for value in (True,-1,1.5,val.MAX_TOKENS+1):
            with self.subTest(count=value),self.assertRaises(ValueError):
                val.value_event(record("unknown",Tokens(value)))
        with self.assertRaises(ValueError):
            val.value_event(record("unknown",Tokens(val.MAX_TOKENS,1)))
        maximum=val.value_event(record("gpt-5",Tokens(val.MAX_TOKENS)))
        with self.assertRaises(ValueError):
            val.aggregate_values([maximum,maximum])
        self.assertEqual(val.bounded_decimal("1000000000"),D("1000000000"))
        self.assertEqual(val.bounded_decimal("0E-999999"),D(0))

    def test_arithmetic_does_not_depend_on_callers_decimal_context(self):
        with localcontext() as ctx:
            ctx.prec=4
            values=[val.value_event(e,fixture_catalog()) for e in fixture_events()]
            summary=val.aggregate_values(values)
            rows,combined=val.compare_plans(values,val.ComparisonScope(("Codex","Claude"),"month",True))
            self.assertEqual(summary.amount_usd,D("18.891000000000"))
            self.assertEqual(combined.difference_usd,D("-21.109000000000"))
            self.assertEqual(val.money_text(summary.amount_usd),"$18.8910")

    def test_rates_provenance_snapshot_mapping_and_overrides_are_versioned(self):
        catalog=val.build_catalog({"fixture-codex-model":val.Price("2.00","10.0",".100")})
        same=val.build_catalog({"fixture-codex-model":val.Price(2,10,"0.1")})
        self.assertEqual(catalog.version,same.version)
        first=val.value_event(record(),catalog)
        self.assertTrue(first.custom)
        self.assertEqual(first.source,"custom configuration")
        self.assertIsNone(first.checked_date)
        self.assertEqual(first.policy_version,val.POLICY_VERSION)
        self.assertTrue(first.override_version and first.catalog_version and first.rate_id)
        dated=val.value_event(record("gpt-5.4-20261001",Tokens(1)))
        self.assertEqual(dated.matched_model,"gpt-5.4")
        self.assertEqual(dated.model_mapping,"dated_snapshot")
        self.assertEqual(dated.checked_date,"2026-10-23")
        self.assertEqual(dated.source,val.PRICE_SOURCE)
        self.assertFalse(dated.custom)
        for model in ("gpt-5.4-something","codex-auto-review","future-model"):
            self.assertEqual(val.value_event(record(model,Tokens(1))).state,"unpriced")
        overridden=val.value_event(record("gpt-5.4-20261001",Tokens(1)),val.build_catalog({"gpt-5.4-20261001":val.Price(9,9,9)}))
        self.assertEqual(overridden.model_mapping,"exact")
        self.assertTrue(overridden.custom)

    def test_repricing_changes_valuation_but_never_canonical_facts_or_ids(self):
        event=fixture_events()[0]
        before=asdict(event)
        first=val.value_event(event,fixture_catalog())
        second=val.value_event(event,val.build_catalog({"fixture-codex-model":val.Price(4,20,"0.2")}))
        self.assertEqual(asdict(event),before)
        self.assertEqual((first.event_id,first.record),(second.event_id,second.record))
        self.assertEqual(second.amount_usd,first.amount_usd*2)
        self.assertNotEqual(first.pricing_version,second.pricing_version)
        self.assertNotEqual(first.rate_id,second.rate_id)
        with self.assertRaises(ValueError):
            val.aggregate_values([first,second])

    def test_tier_threshold_and_missing_context_are_separate_from_price_coverage(self):
        catalog = val.build_catalog(context_policy=val.LEGACY_CONTEXT)
        for count,tier in [(271999,"standard"),(272000,"standard"),(272001,"high_context")]:
            value=val.value_event(canonical(record("gpt-5.4",Tokens(10,1)),count), catalog)
            self.assertEqual(value.tier,tier)
            self.assertEqual(value.assumptions,())
            self.assertEqual(value.request_context_source,"fixture request input")
        known=val.value_event(canonical(record("gpt-5.4",Tokens(500000,100)),100), catalog)
        assumed=val.value_event(canonical(record("gpt-5.4",Tokens(500000,100))), catalog)
        self.assertEqual(known.tier,"standard")
        self.assertEqual(assumed.tier,"high_context")
        self.assertIsNone(assumed.request_context_tokens)
        self.assertEqual(assumed.assumptions,("event_input_tier_compatibility",))
        self.assertEqual(val.aggregate_values([assumed]).state,"complete")
        self.assertIn("tier assumed",val.value_text(val.aggregate_values([assumed])))
        self.assertGreater(assumed.amount_usd,known.amount_usd)

    def test_events_are_never_merged_into_a_synthetic_context_tier(self):
        catalog = val.build_catalog(context_policy=val.LEGACY_CONTEXT)
        item=record("gpt-5.4",Tokens(200000,1000))
        values=[val.value_event(item, catalog) for _ in range(2)]
        self.assertEqual(val.aggregate_values(values).amount_usd,D("1.030000000000"))
        self.assertNotEqual(val.aggregate_values(values).amount_usd,
                            val.value_event(record("gpt-5.4",Tokens(400000,2000)), catalog).amount_usd)

    def test_reasoning_and_effort_do_not_add_tokens_or_multiplier(self):
        event=fixture_events()[0]
        with_reason=val.value_event(event,fixture_catalog())
        other=replace(event,record=replace(event.record,reasoning_tokens=None,effort="ultra",effort_source="fixture"))
        without=val.value_event(other,fixture_catalog())
        self.assertEqual(with_reason.amount_usd,without.amount_usd)
        self.assertEqual(with_reason.record.tokens.total,without.record.tokens.total)
        legacy=val.value_event(replace(event,quality=("legacy_cache_ttl_assumed",)),fixture_catalog())
        self.assertIn("legacy_cache_ttl_assumed",legacy.assumptions)

    def test_legacy_float_projection_matches_only_within_its_display_precision(self):
        for model,price in val.PRICES.items():
            for tokens in (Tokens(1,1,1),Tokens(10000,1000,189000),Tokens(250000,1000,30000)):
                rec=record(model,tokens)
                # The current policy explicitly assumes below-threshold context.
                rates=(price.input,price.output,price.cached)
                legacy=(tokens.input*float(rates[0])+tokens.output*float(rates[1])+tokens.cached*float(rates[2])
                        +tokens.write5m*float(price.write5m or 0)+tokens.write1h*float(price.write1h or 0))/1000000
                self.assertLessEqual(abs(D(str(legacy))-val.value_event(rec).amount_usd),D("0.000000000001"))
                self.assertEqual(reports.estimate(rec),float(val.value_event(rec).amount_usd))

    def test_missing_write_rate_is_unpriced_but_explicit_zero_is_priced(self):
        item=record("custom",Tokens(100,20,30,5,0),"Claude")
        unknown=val.value_event(item,val.build_catalog({"custom":val.Price(4,20,"0.2")}))
        zero=val.value_event(item,val.build_catalog({"custom":val.Price(4,20,"0.2",0,0)}))
        self.assertEqual(unknown.state,"unpriced")
        self.assertEqual(unknown.unpriced_reason,"cache_write_rate_unavailable")
        self.assertIsNone(unknown.amount_usd)
        self.assertTrue(unknown.rate_id)
        self.assertEqual(zero.state,"priced")
        self.assertEqual(zero.amount_usd,D("0.000806000000"))
        self.assertNotEqual(unknown.pricing_version,zero.pricing_version)
        # Missing prices for unused categories do not block the other token categories.
        unused=val.value_event(replace(item,tokens=Tokens(100,20,30)),val.build_catalog({"custom":val.Price(4,20,"0.2")}))
        self.assertEqual(unused.state,"priced")

    def test_headless_valuation_import_has_no_reader_provider_or_gui(self):
        script="import sys; import usage_valuation; assert not {'usage_ingestion','usage_reports','usage_core','usage_tray','PIL','pystray'} & sys.modules.keys()"
        result=subprocess.run([sys.executable,"-c",script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class ComparisonTests(unittest.TestCase):
    def values(self):
        return tuple(val.value_event(e,fixture_catalog()) for e in fixture_events())

    def test_selected_provider_and_signed_positive_negative_zero_differences(self):
        for providers, expected in [(("Codex",),D("-1.58")),(("Claude",),D("-19.529")),(("Codex","Claude"),D("-21.109"))]:
            rows,combined=val.compare_plans(self.values(),val.ComparisonScope(providers,"month",True))
            self.assertEqual(tuple(r.provider for r in rows),providers)
            self.assertEqual(combined.difference_usd,expected)
        for fee,expected in [("0",D("18.42")),("18.42",D(0)),("20",D("-1.58"))]:
            rows,_=val.compare_plans(self.values(),val.ComparisonScope(("Codex",),"month",True),{"Codex":fee})
            self.assertEqual(rows[0].difference_usd,expected)
        self.assertEqual(val.money_text(D("18.42"),2,signed=True),"+$18.42")
        self.assertEqual(val.money_text(D("-1.58"),2,signed=True),"-$1.58")

    def test_scoped_comparisons_are_unavailable_for_filters_and_incorrect_ranges(self):
        for scope,reason in [(val.ComparisonScope(("Codex",),"today",False),"not_month_to_date"),
                             (val.ComparisonScope(("Codex",),"month",True,True),"filtered_query"),
                             (val.ComparisonScope(("Codex",),"month",False),"range_not_calendar_month_to_date")]:
            rows,combined=val.compare_plans(self.values(),scope)
            self.assertEqual(rows[0].reason,reason)
            self.assertEqual(combined.reason,reason)
            self.assertIsNone(combined.difference_usd)

    def test_no_missing_provider_is_silently_dropped_from_combined(self):
        values=self.values()
        scope=val.ComparisonScope(("Codex","Claude"),"month",True)
        for entries,fees,reason in [(values[:1],None,"no_usage_records"),
                                   (values,{"Codex":"20"},"fee_not_configured"),
                                   (values[:1]+(val.value_event(record("unknown",Tokens(10),"Claude")),),None,"all_usage_unpriced")]:
            # Keep all entries in one catalog/version even when one model is unpriced.
            entries=tuple(val.value_event(v.record,fixture_catalog()) for v in entries)
            rows,combined=val.compare_plans(entries,scope,fees)
            self.assertEqual(rows[1].reason,reason)
            self.assertFalse(combined.available)
            self.assertEqual(combined.reason,"selected_provider_unavailable")
            self.assertIsNone(combined.difference_usd)
            self.assertIsNone(combined.fee_usd)

    def test_partial_pricing_and_ingestion_flags_do_not_change_coverage_state(self):
        catalog=fixture_catalog()
        values=self.values()+(val.value_event(record("unknown",Tokens(10)),catalog),)
        rows,combined=val.compare_plans(values,val.ComparisonScope(("Codex","Claude"),"month",True),
                                        qualifications={"Codex":("ingestion_partial","accounting_issues_present")})
        self.assertEqual(rows[0].pricing_state,"partial")
        self.assertEqual(combined.difference_usd,D("-21.109"))
        self.assertIn("priced_usage_only",combined.qualifications)
        self.assertIn("ingestion_partial",combined.qualifications)
        complete=val.aggregate_values(values[:2])
        self.assertEqual(complete.state,"complete")


class ReportValuationTests(unittest.TestCase):
    def report(self):
        events=fixture_events()
        return reports.Report([e.record for e in events],{p:reports.period_bounds("month",NOW) for p in ("Codex","Claude")},NOW,
                              prices={"fixture-codex-model":val.Price(2,10,"0.1"),"fixture-claude-model":val.Price(4,20,"0.2",5,8)},
                              period="month",events=events)

    def test_both_renderers_use_decimal_authority_without_legacy_float_estimator(self):
        from unittest.mock import patch
        report=self.report()
        with patch.object(reports,"estimate",side_effect=AssertionError("legacy float path")):
            for render in (reports.render_text_report,reports.render_report):
                text=render(report)
                self.assertIn("$18.8910",text)
                self.assertIn("-$21.11",text)
                self.assertIn("Pricing coverage: complete",text)
                self.assertIn(report.catalog.version,text)
                self.assertNotIn("Estimated savings so far",text)
        self.assertEqual(report.summarize_value().amount_usd,D("18.891"))
        self.assertEqual(report.comparisons()[1].difference_usd,D("-21.109"))

    def test_canonical_context_survives_report_adapter_and_repricing(self):
        event=canonical(record("gpt-5.4",Tokens(500000,100)),100)
        report=reports.Report([event.record],{"Codex":reports.period_bounds("month",NOW)},NOW,events=(event,),period="month")
        value=report.valuation_view()[id(event.record)]
        self.assertEqual(value.tier,"standard")
        self.assertEqual(value.assumptions,("below_threshold_context_assumed",))
        self.assertEqual(value.event_id,event.event_id)
        repriced=replace(report,prices={"gpt-5.4":val.Price(2,10,0)})
        self.assertEqual(repriced.events,report.events)
        self.assertNotEqual(repriced.catalog.version,report.catalog.version)
        self.assertEqual(report.valuation_view()[id(event.record)],value)

    def test_catalog_is_a_frozen_snapshot_even_if_override_dict_mutates(self):
        overrides={"fixture-codex-model":val.Price(2,10,"0.1")}
        report=reports.Report([record()],{"Codex":reports.period_bounds("month",NOW)},NOW,prices=overrides,period="month")
        before=report.summarize_value()
        overrides["fixture-codex-model"]=val.Price(9,9,9)
        report.prices["fixture-codex-model"]=val.Price(8,8,8)
        self.assertEqual(report.summarize_value(),before)
        self.assertIn("input $2",reports.render_text_report(report))

    def test_json_loads_decimal_strings_and_fractional_numbers_without_binary_loss(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"prices.json"
            path.write_text('{"precise":{"input":0.123456789012,"output":"0.000000000001","cached":0}}',encoding="utf-8")
            rates=reports.load_prices(path)
            self.assertEqual(rates["precise"].input,D("0.123456789012"))
            self.assertEqual(rates["precise"].output,D("0.000000000001"))
            for invalid in ('NaN','Infinity','true','-1','0.0000000000001','1000000001'):
                path.write_text('{"model":{"input":'+invalid+',"output":0,"cached":0}}',encoding="utf-8")
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                    reports.load_prices(path)

    def test_scope_adapter_validates_calendar_range_and_exposes_filter_reason(self):
        report=self.report()
        report.filtered=True
        self.assertEqual(reports.plan_comparison(report),[])
        self.assertEqual(report.comparisons()[1].reason,"filtered_query")
        report.filtered=False
        report.ranges={p:replace(r,start=r.start+1) for p,r in report.ranges.items()}
        self.assertEqual(report.comparisons()[1].reason,"range_not_calendar_month_to_date")

    def test_real_reader_never_treats_model_capacity_as_request_context(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            entries=[{"type":"session_meta","payload":{"id":"synthetic","cwd":"synthetic-project"}},
                     {"type":"turn_context","payload":{"model":"gpt-5.4"}},
                     {"type":"event_msg","timestamp":datetime.fromtimestamp(NOW-1,timezone.utc).isoformat(),
                      "payload":{"type":"token_count","info":{"model_context_window":1000000,
                       "total_token_usage":{"input_tokens":100,"output_tokens":10,"cached_input_tokens":0}}}}]
            (root/"fixture.jsonl").write_text("\n".join(json.dumps(e) for e in entries)+"\n",encoding="utf-8")
            report=reports.collect_report("month",providers=["Codex"],roots={"Codex":[root]},now=NOW)
            event,=report.events
            value=report.valuation_view()[id(event.record)]
            self.assertIsNone(value.request_context_tokens)
            self.assertEqual(value.tier,"standard")
            self.assertEqual(value.assumptions,("below_threshold_context_assumed",))
            self.assertIn("Below-threshold context assumed",reports.render_text_report(report))
            self.assertIn("Below-threshold context assumed",reports.render_report(report))

    def test_real_claude_legacy_ttl_assumption_survives_report_projection(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            entry={"type":"assistant","timestamp":datetime.fromtimestamp(NOW-1,timezone.utc).isoformat(),"sessionId":"c",
                   "message":{"id":"m","model":"claude-sonnet-4-6","usage":{"input_tokens":10,"output_tokens":1,
                    "cache_read_input_tokens":0,"cache_creation_input_tokens":5}}}
            (root/"fixture.jsonl").write_text(json.dumps(entry)+"\n",encoding="utf-8")
            report=reports.collect_report("month",providers=["Claude"],roots={"Claude":[root]},now=NOW)
            summary=report.summarize_value()
            self.assertEqual(summary.state,"complete")
            self.assertIn("legacy_cache_ttl_assumed",summary.assumptions)
            self.assertIn("cache-write TTL assumed",reports.render_text_report(report))

    def test_cli_fee_text_keeps_exact_fraction_and_rejects_excess_scale(self):
        from unittest.mock import patch
        import usage_tray
        with patch.object(sys,"argv",["usage_tray.py","--demo","--codex-plan-usd","20.000000000001"]), \
             patch.object(usage_tray,"run_tray") as tray:
            self.assertEqual(usage_tray.main(),0)
            self.assertEqual(tray.call_args.args[4]["Codex"],D("20.000000000001"))
            self.assertEqual(tray.call_args.args[4]["Claude"],D("20.00"))
        script=Path(usage_tray.__file__)
        for fee in ("20.0000000000001","1000000000.000000000001"):
            result=subprocess.run([sys.executable,str(script),"--report","month","--demo","--codex-plan-usd",fee],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn("Monthly plan prices must be",result.stderr)
            self.assertNotIn("Traceback",result.stderr)

    def test_missing_category_rate_is_visible_in_both_renderers(self):
        item=record("custom",Tokens(100,20,30,5,0),"Claude")
        report=reports.Report([item],{"Claude":reports.period_bounds("month",NOW)},NOW,
                              prices={"custom":val.Price(4,20,"0.2")},period="month")
        for render in (reports.render_text_report,reports.render_report):
            text=render(report)
            self.assertIn("Unavailable (all usage unpriced)",text)
            self.assertIn("unconfigured",text)
            self.assertNotIn("$0.0000",text)


if __name__=="__main__":
    unittest.main()
