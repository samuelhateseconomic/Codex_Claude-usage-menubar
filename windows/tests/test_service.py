from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal, localcontext
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_service as service
import usage_reports as reports
import usage_valuation as valuation
from usage_ingestion import ScanIssue
from usage_reconciliation import AccountingIssue
from usage_records import Record, Tokens
from usage_time import resolve_range
from usage_observations import CanonicalEvent, SourceRef

NOW = datetime(2026, 10, 23, 20, tzinfo=timezone.utc).timestamp()
D = Decimal


def context(providers=("Codex", "Claude"), **kwargs):
    return service.QueryContext(tuple((p, resolve_range("month", NOW, timezone="UTC")) for p in providers),
                                NOW, "month", "UTC", **kwargs)


def fixture():
    codex = Record("Codex", NOW-2, "same-session", "same-project", "fixture-codex",
                   Tokens(10000,1830000,1000000), "high", "explicit", "t",1260000)
    claude = Record("Claude", NOW-1, "same-session", "same-project", "fixture-claude",
                    Tokens(10000,20000,30000,5000,0), "unknown")
    return tuple(CanonicalEvent("conversation", "epoch", "event",
                "codex_cumulative_delta" if r.provider == "Codex" else "claude_message",
                r, (SourceRef("synthetic",1,"gen"),)) for r in (codex,claude))


def catalog():
    return valuation.build_catalog({"fixture-codex": valuation.Price(2,10,"0.1"),
                                    "fixture-claude": valuation.Price(4,20,"0.2",5,8)})


class SharedResultTests(unittest.TestCase):
    def result(self, entries=None, ctx=None, **kwargs):
        return service.build_usage_result(fixture() if entries is None else entries,
                                           context() if ctx is None else ctx,catalog(),**kwargs)

    def test_exact_fixture_totals_and_comparisons(self):
        result = self.result()
        self.assertEqual(result.total.tokens, Tokens(20000,1850000,1030000,5000,0))
        self.assertEqual(result.total.tokens.total,2905000)
        self.assertEqual(result.total.value.amount_usd,D("18.891000000000"))
        self.assertEqual((result.total.record_count,result.total.conversation_count,result.total.project_count),(2,2,1))
        self.assertEqual(result.total.reasoning,service.ReasoningSummary(1260000,1,1))
        self.assertEqual(result.combined_comparison.difference_usd,D("-21.109"))
        self.assertEqual([r.difference_usd for r in result.comparisons],[D("-1.58"),D("-19.529")])
        self.assertEqual(result.context.scope,"local_unmatched_accounts")
        self.assertEqual(result.generated_at,NOW)
        self.assertEqual(result.parser_version,"observations-v1")
        self.assertEqual(result.reconciliation_version,"reconciliation-v2")
        self.assertEqual(result.valuation_policy,valuation.POLICY_VERSION)

    def test_every_dimension_and_detail_reconciles_all_categories_values_and_coverage(self):
        base = fixture()
        unknown = replace(base[0].record,model="not-priced",session="other",tokens=Tokens(2,3,4,5,6),reasoning_tokens=None)
        result = self.result((*base,unknown))
        self.assertEqual(result.total.value.state,"partial")
        for dimension in service.DIMENSIONS:
            groups = result.groups_for(dimension)
            flattened = [id for g in groups for id in g.detail_ids]
            self.assertEqual(sorted(flattened),sorted(d.detail_id for d in result.details),dimension)
            total = Tokens()
            for group in groups:
                total += group.summary.tokens
                members = [d for d in result.details if d.detail_id in group.detail_ids]
                self.assertEqual(group.summary,service.summarize_values((d.valuation for d in members),(d.conversation_id for d in members)))
            self.assertEqual(total,result.total.tokens,dimension)
            self.assertEqual(sum((g.summary.value.amount_usd or D(0) for g in groups),D(0)),D("18.891"),dimension)
            self.assertEqual(sum(g.summary.value.unpriced_records for g in groups),1,dimension)
            self.assertEqual(sum(g.summary.value.unpriced_tokens for g in groups),20,dimension)
        self.assertEqual(result.unpriced_models,("not-priced",))

    def test_provider_queries_restore_both_and_keep_shared_project_count(self):
        expected = {("Codex",):(2840000,"18.42",1), ("Claude",):(65000,"0.471",1),
                    ("Codex","Claude"):(2905000,"18.891",2)}
        for providers, (tokens,amount,conversations) in expected.items():
            result = self.result(ctx=context(providers))
            self.assertEqual(result.total.tokens.total,tokens)
            self.assertEqual(result.total.value.amount_usd,D(amount))
            self.assertEqual(result.total.conversation_count,conversations)
            self.assertEqual(result.total.project_count,1)
            self.assertEqual(len(result.comparisons),len(providers))
        self.assertEqual(self.result().total.value.amount_usd,D("18.891"))

    def test_exact_metadata_filters_use_same_events_and_disable_fee_comparison(self):
        codex = fixture()[0].record
        for filters in [service.UsageFilters(models=(codex.model,)), service.UsageFilters(efforts=("high",)),
                        service.UsageFilters(conversations=(("Codex",codex.session),)),
                        service.UsageFilters(search="FIXTURE-CODEX")]:
            result = self.result(ctx=context(filters=filters))
            self.assertEqual(result.total.tokens.total,2840000)
            self.assertEqual(result.total.value.amount_usd,D("18.42"))
            self.assertEqual(result.combined_comparison.reason,"filtered_query")
            self.assertIsNone(result.combined_comparison.difference_usd)
            self.assertEqual(result.context.captured_at,NOW)
        # The same project string belongs to both providers, as an exact metadata filter.
        selected = self.result(ctx=context(filters=service.UsageFilters(projects=("same-project",))))
        self.assertEqual(selected.total.tokens.total,2905000)
        self.assertEqual(selected.combined_comparison.reason,"filtered_query")

    def test_conversation_drilldown_retains_range_and_contributing_model_effort_projects(self):
        event = fixture()[0]
        later = replace(event,event_anchor="later",record=replace(event.record,model="fixture-claude",effort="ultra",
                         project="second-project",timestamp=NOW-1,tokens=Tokens(10,20),reasoning_tokens=0))
        ctx = context(filters=service.UsageFilters(conversations=(("Codex","same-session"),)))
        result = self.result((*fixture(),later),ctx)
        group, = result.groups_for("conversation")
        self.assertEqual(group.summary.record_count,2)
        self.assertEqual(group.summary.tokens.total,2840030)
        self.assertEqual(group.summary.project_count,2)
        self.assertEqual({g.key[1] for g in result.groups_for("model")},{"fixture-codex","fixture-claude"})
        self.assertEqual({g.key[1] for g in result.groups_for("effort")},{"high","ultra"})
        self.assertEqual(result.context,ctx)

    def test_range_filter_applies_to_legacy_and_canonical_entries(self):
        first = fixture()[0]
        start = dict(context().ranges)["Codex"].start
        entries = [replace(first,event_anchor=str(i),record=replace(first.record,timestamp=t))
                   for i,t in enumerate((start-1,start,NOW-0.001,NOW,NOW+1))]
        for source in (entries,[e.record for e in entries]):
            result = self.result(source)
            self.assertEqual([d.record.timestamp for d in result.details],[start,NOW-0.001])
            self.assertEqual(result.total.tokens.total,5680000)

    def test_daily_groups_and_day_filter_use_named_local_boundaries(self):
        start = datetime(2026,10,24,7,tzinfo=timezone.utc).timestamp()
        end = start+3600
        zone = "America/Los_Angeles"
        ctx = service.QueryContext((("Claude",resolve_range("month",end,timezone=zone)),),end,"month",zone)
        base = fixture()[1].record
        result = self.result([replace(base,timestamp=start-1),replace(base,timestamp=start)],ctx)
        self.assertEqual([g.key for g in result.groups_for("day")],[("2026-10-23",),("2026-10-24",)])
        selected = self.result([d.record for d in result.details],replace(ctx,filters=service.UsageFilters(selected_day="2026-10-23")))
        self.assertEqual(selected.total.tokens.total,65000)
        self.assertEqual(selected.details[0].record.timestamp,start-1)
        self.assertEqual(selected.combined_comparison.reason,"filtered_query")

    def test_empty_unpriced_partial_and_zero_remain_distinct_from_source_quality(self):
        unknown = replace(fixture()[0].record,model="unknown",tokens=Tokens(10),reasoning_tokens=None)
        zero = replace(unknown,model="zero")
        cat = valuation.build_catalog({"zero":valuation.Price(0,0,0)})
        for entries,state,amount in [((),"empty",None),((unknown,),"unpriced",None),((zero,),"complete",D(0)),
                                      ((unknown,zero),"partial",D(0))]:
            result = service.build_usage_result(entries,context(("Codex",)),cat,
                      sources=(service.SourceQuality("Codex","failed",(ScanIssue("unreadable_file","Read failed."),)),))
            self.assertEqual(result.total.value.state,state)
            self.assertEqual(result.total.value.amount_usd,amount)
            self.assertEqual(result.sources[0].state,"failed")
            self.assertIsNone(result.sources[0].issues[0].excluded_tokens)

    def test_known_reasoning_zero_is_distinct_from_absence(self):
        base = fixture()[1].record
        for entries,expected in [([base],service.ReasoningSummary(None,0,1)),
                                 ([replace(base,reasoning_tokens=0)],service.ReasoningSummary(0,1,0)),
                                 ([base,replace(base,reasoning_tokens=0)],service.ReasoningSummary(0,1,1))]:
            result = self.result(entries)
            self.assertEqual(result.total.reasoning,expected)
            self.assertEqual(result.total.tokens.total,65000*len(entries))

    def test_immutable_result_does_not_follow_input_mutations(self):
        entries = list(fixture())
        fees = {"Codex":"20","Claude":"20"}
        notices = ["Static notice"]
        result = self.result(entries,fees=fees,notices=notices)
        before = asdict(result)
        entries.clear(); fees["Codex"]="0"; notices.append("Changed")
        self.assertEqual(asdict(result),before)
        for obj,attr,value in [(result,"generated_at",0),(result.context,"period","today"),
                               (result.total,"record_count",99),(result.details[0].record,"session","changed")]:
            with self.assertRaises(FrozenInstanceError):
                setattr(obj,attr,value)
        self.assertEqual(result.combined_comparison.difference_usd,D("-21.109"))

    def test_canonical_ids_provenance_and_fact_identity_survive_query_and_repricing(self):
        events = fixture()
        result = self.result()
        for detail in result.details:
            self.assertIn(detail.event,events)
            self.assertIs(detail.valuation.record,detail.event.record)
            self.assertEqual(detail.detail_id,detail.event.event_id)
            self.assertEqual(detail.valuation.event_id,detail.event.event_id)
        changed = service.build_usage_result(events,context(),valuation.build_catalog({"fixture-codex":valuation.Price(1,1,1)}))
        self.assertEqual([d.detail_id for d in result.details],[d.detail_id for d in changed.details])
        self.assertEqual(result.total.tokens,changed.total.tokens)
        self.assertNotEqual(result.catalog.version,changed.catalog.version)
        with self.assertRaisesRegex(ValueError,"Duplicate accepted event"):
            self.result((events[0],events[0]))

    def test_equal_time_order_and_groups_are_independent_of_input_order(self):
        records = [replace(e.record,timestamp=NOW-1) for e in fixture()]
        records += [replace(records[0],session="another"),records[0]]
        expected = self.result(records)
        for permutation in itertools.permutations(records):
            result = self.result(permutation)
            self.assertEqual(result,expected)
            self.assertEqual(len({d.detail_id for d in result.details}),4)

    def test_composite_group_keys_do_not_merge_colliding_display_labels(self):
        base = fixture()[0].record
        a = replace(base,model="a / b",effort="c")
        b = replace(base,model="a",effort="b / c")
        result = self.result([a,b])
        groups = result.groups_for("model_effort")
        self.assertEqual(len(groups),2)
        self.assertEqual(len({g.group_id for g in groups}),2)
        self.assertNotEqual(groups[0].key,groups[1].key)

    def test_full_canonical_conversation_identity_owns_groups_and_drilldowns(self):
        a = fixture()[0]
        # Simulate two weak source identities sharing a shortened display surrogate.
        b = replace(a,conversation_key="different-full-source-identity",event_anchor="other")
        result = self.result([a,b])
        self.assertEqual(result.total.conversation_count,2)
        groups = result.groups_for("conversation")
        self.assertEqual(len(groups),2)
        self.assertEqual(groups[0].key,groups[1].key)
        self.assertNotEqual(groups[0].group_id,groups[1].group_id)
        self.assertEqual(len({d.conversation_id for d in result.details}),2)
        chosen = result.details[0]
        selected = self.result([a,b],context(filters=service.UsageFilters(conversation_ids=(chosen.conversation_id,))))
        self.assertEqual(selected.total.conversation_count,1)
        self.assertEqual(len(selected.details),1)
        self.assertEqual(selected.details[0].detail_id,chosen.detail_id)
        self.assertEqual(selected.context.ranges,result.context.ranges)

    def test_exact_sorting_does_not_round_to_float_or_callers_decimal_context(self):
        # Adjacent 12-place event amounts at a scale where binary floats collapse.
        base = replace(fixture()[0].record,tokens=Tokens(1000000),reasoning_tokens=None)
        records = [replace(base,session="lower",model="lo"),replace(base,session="higher",model="hi"),
                   replace(base,session="unpriced",model="unknown"),replace(base,session="zero",model="zero")]
        cat = valuation.build_catalog({"lo":valuation.Price("100000000.000000000001",0,0),
               "hi":valuation.Price("100000000.000000000002",0,0),"zero":valuation.Price(0,0,0)})
        self.assertEqual(float(cat.lookup("lo").price.input),float(cat.lookup("hi").price.input))
        result = service.build_usage_result(records,context(("Codex",)),cat)
        with localcontext() as decimal_context:
            decimal_context.prec=3
            ranked = result.groups_for("conversation","value_desc")
        self.assertEqual([g.key[1] for g in ranked],["higher","lower","zero","unpriced"])
        # A display slice does not replace the full matched totals.
        self.assertEqual(len(ranked[:1]),1)
        self.assertEqual(result.total.record_count,4)
        self.assertEqual(result.total.value.amount_usd,D("200000000.000000000003"))

    def test_sort_ties_use_stable_group_id_and_latest_is_matched_activity(self):
        base = fixture()[0].record
        records = [replace(base,session="a",timestamp=NOW-100),replace(base,session="b",timestamp=NOW-1)]
        result = self.result(records)
        for sort in ("value_desc","tokens_desc"):
            rows = result.groups_for("conversation",sort)
            self.assertEqual([g.group_id for g in rows],sorted(g.group_id for g in rows))
        self.assertEqual(result.groups_for("conversation","last_activity_desc")[0].key[1],"b")
        for dimension,sort in [("not-a-view","key"),("project","float_cost")]:
            with self.assertRaises(ValueError):
                result.groups_for(dimension,sort)

    def test_context_and_filter_validation_and_literal_search(self):
        for providers in [(),("Codex","Codex"),("Other",)]:
            with self.assertRaises(ValueError): context(providers)
        for filters in [dict(search="x"*201),dict(selected_day="2026-99-01"),dict(selected_day="20261023"),
                        dict(conversations=(("Other","id"),))]:
            with self.assertRaises(ValueError): service.UsageFilters(**filters)
        ctx = context()
        for change in [dict(captured_at=float("nan")),dict(period="year"),
                       dict(ranges=(("Codex",replace(ctx.ranges[0][1],end=NOW+1)),))]:
            with self.assertRaises(ValueError): replace(ctx,**change)
        self.assertEqual(service.UsageFilters(models=["b","a","b"]).models,("a","b"))
        self.assertEqual(service.UsageFilters(search="  SAME-PROJECT  ").search,"same-project")
        self.assertEqual(self.result(ctx=context(filters=service.UsageFilters(search=".*"))).total.value.state,"empty")

    def test_result_renderers_do_not_value_group_or_summarize_again(self):
        result = self.result()
        before = asdict(result)
        with patch.object(service,"value_event",side_effect=AssertionError("reprice")), \
             patch.object(service,"summarize_values",side_effect=AssertionError("summarize")), \
             patch.object(reports,"aggregate_values",side_effect=AssertionError("renderer aggregate")), \
             patch.object(reports,"estimate",side_effect=AssertionError("float")), \
             patch.object(reports.Report,"query_result",side_effect=AssertionError("legacy adapter")):
            for render in (reports.render_text_report,reports.render_report):
                text = render(result)
                self.assertIn("2,905,000",text)
                self.assertIn("$18.8910",text)
                self.assertIn("-$21.11",text)
                self.assertIn(result.catalog.version,text)
        self.assertEqual(asdict(result),before)

    def test_legacy_adapter_snapshots_once_per_renderer_and_matches_direct_result(self):
        events = fixture()
        report = reports.Report([e.record for e in events],{p:(r.start,r.label) for p,r in context().ranges},NOW,
                      prices={"fixture-codex":valuation.Price(2,10,"0.1"),"fixture-claude":valuation.Price(4,20,"0.2",5,8)},
                      period="month",timezone="UTC",events=events)
        result = report.query_result()
        for render in (reports.render_text_report,reports.render_report):
            with patch.object(report,"query_result",wraps=report.query_result) as snapshot:
                self.assertEqual(render(report),render(result))
                self.assertEqual(snapshot.call_count,1)
        self.assertEqual(report.summarize_value(),result.total.value)
        self.assertEqual(report.comparisons(),(result.comparisons,result.combined_comparison))


class OfflineCollectionTests(unittest.TestCase):
    def test_fresh_process_service_import_and_real_offline_query_have_no_gui_or_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            message = {"type":"assistant","timestamp":datetime.fromtimestamp(NOW-1,timezone.utc).isoformat(),
                       "sessionId":"fixture","cwd":"project","message":{"id":"m","model":"claude-sonnet-4-6",
                       "content":[{"text":"PRIVATE_SENTINEL"}],"usage":{"input_tokens":10,"output_tokens":20,
                       "cache_read_input_tokens":30,"cache_creation_input_tokens":0}}}
            (root/"usage.jsonl").write_text(json.dumps(message)+"\n",encoding="utf-8")
            script = """import socket,sys
from pathlib import Path
from unittest.mock import patch
import usage_service as s
with patch.object(socket,'socket',side_effect=AssertionError('network')), patch('subprocess.Popen',side_effect=AssertionError('provider subprocess')):
    r=s.query_usage('month',providers=('Claude',),roots={'Claude':[Path(sys.argv[1])]},now=float(sys.argv[2]),timezone='UTC')
    assert r.total.tokens.total==60, r.total
    assert r.sources[0].state=='complete', r.sources
    assert 'PRIVATE_SENTINEL' not in repr(r)
    assert not {'usage_core','usage_tray','usage_reports','PIL','pystray'} & sys.modules.keys()
"""
            result = subprocess.run([sys.executable,"-c",script,str(root),str(NOW)],cwd=Path(service.__file__).parent,
                                    capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_demo_is_explicit_and_never_scans_or_resolves_real_roots(self):
        with patch.object(service,"scan_observations",side_effect=AssertionError("scan")), \
             patch.object(service,"default_roots",side_effect=AssertionError("real roots")):
            result = service.query_usage("month",demo=True,now=NOW)
        self.assertEqual(result.context.scope,"demo")
        self.assertEqual(result.total.tokens.total,108000)
        self.assertEqual(result.total.value.amount_usd,D("0.2658"))
        self.assertEqual({s.state for s in result.sources},{"demo"})

    def test_one_clock_and_provider_specific_ranges_without_polling(self):
        class Window:
            duration_minutes=300
            def __init__(self,reset): self.resets_at=reset
        class Snapshot:
            def __init__(self,reset): self.windows=[Window(reset)]
        with patch.object(service.time,"time",side_effect=[NOW,AssertionError("second clock")]) as clock:
            result = service.query_usage("session",demo=True,timezone="UTC",
                       snapshots={"Codex":Snapshot(NOW+3600),"Claude":Snapshot(NOW+7200)})
            reports.render_text_report(result); reports.render_report(result)
        self.assertEqual(clock.call_count,1)
        self.assertEqual([r.start for _,r in result.context.ranges],[NOW-14400,NOW-10800])
        self.assertEqual({r.end for _,r in result.context.ranges},{NOW})

    def test_failed_empty_partial_sources_are_not_demo_or_price_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = service.query_usage("month",providers=("Claude",),roots={"Claude":[root/"missing"]},now=NOW)
            empty = service.query_usage("month",providers=("Claude",),roots={"Claude":[root]},now=NOW)
            (root/"usage.jsonl").write_text('{"incomplete":',encoding="utf-8")
            partial = service.query_usage("month",providers=("Claude",),roots={"Claude":[root]},now=NOW)
        self.assertEqual([r.sources[0].state for r in (missing,empty,partial)],["failed","empty","partial"])
        for result in (missing,empty,partial):
            self.assertEqual(result.total.value.state,"empty")
            self.assertEqual(result.context.scope,"local_unmatched_accounts")
            self.assertFalse(result.context.demo)
            self.assertEqual(result.combined_comparison.reason,"selected_provider_unavailable")
        self.assertEqual(missing.sources[0].issue_counts,{"missing_root":1})
        self.assertIsNone(missing.sources[0].issues[0].excluded_tokens)

    def test_accounting_issues_remain_distinct_from_ingestion_and_pricing(self):
        issue = AccountingIssue("counter_reset","Ambiguous reset excluded.",(SourceRef("opaque",1,"generation"),))
        source = service.SourceQuality("Codex","partial",(ScanIssue("incomplete_final_line","Tail deferred."),),(issue,))
        result = service.build_usage_result(fixture(),context(),catalog(),sources=(source,))
        self.assertEqual(result.total.value.state,"complete")
        self.assertEqual(result.sources[0].accounting_issues,(issue,))
        self.assertIn("accounting_issues_present",result.comparisons[0].qualifications)
        self.assertIn("ingestion_partial",result.comparisons[0].qualifications)
        self.assertIsNone(result.sources[0].accounting_issues[0].excluded_tokens)
        counts = result.sources[0].issue_counts
        counts.clear()
        self.assertEqual(result.sources[0].issue_counts,{"incomplete_final_line":1})


if __name__ == "__main__":
    unittest.main()
