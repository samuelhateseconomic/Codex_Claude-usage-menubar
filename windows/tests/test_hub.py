"""Dashboard query, exact value, and loopback boundary regressions."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import http.client
import json
from pathlib import Path
import sys
import subprocess
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_hub import Dataset, HubService, create_server, identifier, summary_dto
from usage_reports import Record, Tokens, Price
from usage_value import estimate_exact, summarize_records

NOW = datetime(2026, 10, 24, 2, tzinfo=timezone.utc).timestamp()


class HubTests(unittest.TestCase):
    def setUp(self):
        self.service = HubService(demo=True, clock=lambda: NOW)
        self.assertEqual(self.service.refresh()["state"], "complete")

    def test_reviewed_fixture_reconciles_through_provider_and_details(self):
        both = self.service.query({})
        self.assertEqual(both["summary"]["tokens"]["total_tokens"], "8920000")
        self.assertEqual(both["summary"]["value"]["amount_usd"], "49.506")
        self.assertEqual((both["summary"]["conversation_count"], both["summary"]["project_count"]), (12,4))
        for provider, tokens, value in (("codex","5900000","28.74"),("claude","3020000","20.766")):
            result = self.service.query({"provider":provider})
            self.assertEqual(result["summary"]["tokens"]["total_tokens"],tokens)
            self.assertEqual(Decimal(result["summary"]["value"]["amount_usd"]), Decimal(value))
        self.assertEqual(sum(int(day["tokens"]["total_tokens"]) for day in both["days"]),8920000)
        self.assertEqual(sum(Decimal(day["value"]["amount_usd"]) for day in both["days"]), Decimal('49.506'))
        conversations=both["conversations"]+self.service.query({"page":"2"})["conversations"]
        self.assertEqual(len({c['id'] for c in conversations}),12)
        for conversation in conversations:
            detail = self.service.query({"conversation":conversation["id"],"revision":both["usage_revision"]})
            self.assertEqual(detail["query_context_id"],both["query_context_id"])
            self.assertEqual(detail["detail"]["tokens"],conversation["tokens"])
            self.assertEqual(detail["detail"]["value"],conversation["value"])
        first = self.service.query({"conversation":identifier("Codex","demo-codex-01")})["detail"]
        self.assertEqual(first["tokens"]["total_tokens"],"2840000")
        self.assertEqual(first["value"]["amount_usd"],"18.42")
        self.assertEqual(first["reasoning_tokens"],"1260000")  # Already in output.

    def test_filters_empty_state_and_fee_scope(self):
        for key,value in (("q","usage-hub"),("project","usage-hub"),("model","gpt-6.1-sol"),
                          ("effort","high"),("day","2026-10-23")):
            result=self.service.query({key:value})
            self.assertEqual(result["comparisons"],[])
            self.assertGreater(result["summary"]["conversation_count"],0)
        empty=self.service.query({"q":"not-present"})
        self.assertEqual(empty["summary"]["value"]["state"],"empty")
        self.assertIsNone(empty["summary"]["value"]["amount_usd"])
        self.assertEqual(empty["summary"]["tokens"]["total_tokens"],"0")
        with self.assertRaises(KeyError):
            self.service.query({"provider":"claude","conversation":identifier("Codex","demo-codex-01")})
        with self.assertRaises(LookupError):
            self.service.query({"revision":"outdated"})
        with self.assertRaises(ValueError):
            self.service.query({"provider":"unrecognized"})
        with self.assertRaises(ValueError):
            self.service.query({"unexpected":"field"})

    def test_exact_money_large_tokens_and_value_states(self):
        record=Record("Codex", NOW-1,"session","project","custom",Tokens(190000,1000,5_000_000_000))
        prices={"custom":Price(.1,.2,.03)}
        self.assertEqual(estimate_exact(record,prices),Decimal('150.0192'))
        self.assertEqual(summary_dto([record],prices)["tokens"]["total_tokens"],"5000191000")
        self.assertEqual(summarize_records([],prices).state,"empty")
        self.assertEqual(summarize_records([record],{}).state,"unpriced")
        self.assertEqual(summarize_records([record],{"custom":Price(0,0,0)}).amount,Decimal(0))
        mixed=summarize_records([record,replace(record,model="unpriced")],prices)
        self.assertEqual(mixed.state,"partial")
        self.assertEqual(mixed.amount,Decimal('150.0192'))
        self.assertEqual(mixed.unpriced_tokens,5000191000)

    def test_captured_range_and_end_exclusion(self):
        record=self.service.dataset.records[0]
        self.service.dataset=Dataset('fixture',NOW,(replace(record,timestamp=NOW-1),replace(record,timestamp=NOW)),())
        result=self.service.query({"period":"today"})
        self.assertEqual(result["summary"]["record_count"],1)
        self.assertEqual(result["range"]["end_at"],NOW)
        # Oct 23 local midnight is 07:00 UTC, not host-local midnight.
        self.assertEqual(result["range"]["start_at"],datetime(2026,10,23,7,tzinfo=timezone.utc).timestamp())
        self.assertEqual(self.service.query({"period":"week"})["range"]["start_at"],NOW-168*3600)

    def test_failed_scan_retains_snapshot_and_never_switches_to_demo(self):
        self.service=HubService(demo=False,clock=lambda:NOW)
        self.service.dataset=Dataset('previous-real-fixture',NOW,(),())
        old=self.service.dataset
        self.service.last_scan=NOW-10
        with patch('usage_hub.read_codex',side_effect=OSError('PRIVATE-SENTINEL')):
            result=self.service.refresh()
        self.assertEqual(result,{"state":"failed","retained_previous":True})
        self.assertIs(self.service.dataset,old)
        dto=self.service.query({})
        self.assertEqual(dto["quality"],"stale")
        self.assertEqual(dto["dataset"],"real")
        self.assertNotIn('PRIVATE-SENTINEL',json.dumps(dto))

    def test_dst_day_boundaries_and_no_prompt_fields(self):
        # Nov 1 is a 25-hour local day; captured 23:30 is 24.5 elapsed hours.
        end=datetime(2026,11,2,7,30,tzinfo=timezone.utc).timestamp()
        self.service.dataset=replace(self.service.dataset,captured_at=end)
        result=self.service.query({"period":"today"})
        self.assertEqual(end-result["range"]["start_at"],24.5*3600)
        encoded=json.dumps(self.service.query({}))
        self.assertNotIn('"content"',encoded)
        self.assertNotIn('"credentials"',encoded)

    def test_cli_keeps_real_dashboard_gated_and_legacy_report_available(self):
        entry=Path(__file__).resolve().parents[1]/'usage_tray.py'
        result=subprocess.run([sys.executable,str(entry),'--dashboard'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2)
        self.assertIn('core gates',result.stderr)
        result=subprocess.run([sys.executable,str(entry),'--report','month','--demo'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0)
        self.assertIn('108,000',result.stdout)


class HubHTTPTests(unittest.TestCase):
    def setUp(self):
        self.service=HubService(demo=True,clock=lambda:NOW)
        self.service.refresh()
        self.server=create_server(self.service,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin=f'http://127.0.0.1:{self.server.server_port}'

    def request(self,path='/',headers=None,method='GET'):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        self.addCleanup(connection.close)
        connection.request(method,path,headers=headers or {})
        response=connection.getresponse()
        return response.status,dict(response.getheaders()),response.read()

    def session(self):
        status,headers,_=self.request()
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        return {'Cookie':headers['Set-Cookie'].split(';')[0],'X-Usage-Hub':'1'}

    def test_api_requires_session_custom_header_and_valid_origin_host(self):
        headers=self.session()
        self.assertEqual(self.request('/api/preview/query',headers)[0],200)
        for rejected in ({},{'X-Usage-Hub':'1'},{'Cookie':headers['Cookie']},
                         {**headers,'Origin':'https://hostile.example'},
                         {**headers,'Host':'hostile.example'},
                         {**headers,'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('/api/preview/query',rejected)[0],403)
        self.assertEqual(self.request('/api/preview/query?provider=codex&provider=claude',headers)[0],400)
        self.assertEqual(self.request('/api/preview/query?revision=stale',headers)[0],409)
        self.assertEqual(self.request('/api/preview/rescan',{},'POST')[0],403)
        self.assertEqual(self.request('/api/preview/rescan',headers,'POST')[0],200)

    def test_static_allowlist_and_assets_are_local_nonempty(self):
        for path in ('/app.js','/format.js','/style.css','/assets/overview.svg','/assets/explore.svg','/assets/limits.svg','/assets/settings.svg'):
            status,headers,body=self.request(path)
            self.assertEqual(status,200,path)
            self.assertGreater(len(body),100)
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        for path in ('/../usage_reports.py','/windows/usage_reports.py','/assets/../../AGENTS.md'):
            self.assertEqual(self.request(path)[0],404)


if __name__=='__main__':
    unittest.main()
