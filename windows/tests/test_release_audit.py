from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.local_history_audit import audit_local, project_audit, reconcile_summary
from usage_service import query_usage

NOW = datetime(2026,10,23,20,tzinfo=timezone.utc).timestamp()


class ReleaseAuditTests(unittest.TestCase):
    def test_projection_contains_no_internal_metadata_and_checks_every_partition(self):
        result=query_usage('month', now=NOW, demo=True)
        detail=result.details[0]
        record=replace(detail.record, project='PRIVATE-PROJECT', session='PRIVATE-SESSION', turn_id='PRIVATE-TURN')
        detail=replace(detail, valuation=replace(detail.valuation, record=record))
        result=replace(result, details=(detail,*result.details[1:]), notices=('PRIVATE-NOTICE',))
        output=project_audit(result,[],1.25)
        text=json.dumps(output)
        self.assertTrue(output['passed'])
        self.assertEqual(len(output['reconciliation']),9)
        self.assertEqual(output['tokens']['total'],'108000')
        self.assertEqual({(m['provider'],m['model']) for m in output['models']},
                         {('Codex','gpt-5.4'),('Claude','claude-sonnet-4-6')})
        for secret in ('PRIVATE-PROJECT','PRIVATE-SESSION','PRIVATE-TURN','PRIVATE-NOTICE','demo-conversation'):
            self.assertNotIn(secret,text)

    def test_reconciliation_rejects_wrong_total_and_broken_partition(self):
        result=query_usage('month',now=NOW,demo=True)
        broken=replace(result,total=replace(result.total,record_count=7))
        self.assertFalse(reconcile_summary(broken)['total_details'])
        groups=tuple((dimension, rows[:-1] if dimension=='provider' else rows) for dimension, rows in result.groups)
        self.assertFalse(reconcile_summary(replace(result,groups=groups))['provider'])

    def test_read_only_fixture_inventory_and_missing_root_quality(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'fixture.jsonl'
            raw=b'{"type":"assistant","timestamp":"2026-10-23T19:00:00Z","sessionId":"PRIVATE-ID","message":{"id":"PRIVATE-MESSAGE","model":"unknown-release-model","content":[{"text":"PRIVATE-TRANSCRIPT"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
            source.write_bytes(raw)
            with patch('usage_core.fetch_codex',side_effect=AssertionError('network forbidden')), patch('usage_core.fetch_claude',side_effect=AssertionError('network forbidden')):
                data=audit_local({'Codex':[root/'absent'],'Claude':[root]},NOW)
            self.assertEqual(source.read_bytes(),raw)
            self.assertEqual(list(root.iterdir()),[source])
            self.assertEqual(data['tokens']['total'],'12')
            self.assertEqual(data['unpriced_tokens'],'12')
            self.assertEqual(data['inventory'][1]['observed_bytes'],len(raw))
            self.assertTrue(data['passed'])
            self.assertEqual(data['providers'][0]['state'],'failed')
            for private in (str(root),'PRIVATE-ID','PRIVATE-MESSAGE','PRIVATE-TRANSCRIPT'):
                self.assertNotIn(private,json.dumps(data))

    def test_cli_requires_explicit_history_selection(self):
        script=Path(__file__).resolve().parents[1]/'tools/local_history_audit.py'
        result=subprocess.run([sys.executable,str(script)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertIn('--read-local-history',result.stderr)


if __name__=='__main__':
    unittest.main()
