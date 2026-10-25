"""Fee publication gates: synthetic inputs only; exact values survive restart."""
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from test_api import ApiFixture, claude
from usage_config import load_settings
from usage_valuation import Price


class SettingsPublicationGates(ApiFixture):
    def setUp(self):
        super().setUp()
        event = claude()
        event['message']['usage'] = {'input_tokens': 1000000, 'output_tokens': 0,
                                     'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        (self.claude / 'fee.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')
        self.change_settings(prices={'fixture-model': Price(2, 10, '.1'),
                                     'fixture-claude': Price('16.2246908', 0, 0, 0, 0)})
        self.store.import_settings()

    def comparison(self):
        return next(row for row in self.overview()['data']['comparisons'] if row['provider'] == 'claude')

    def save_fee(self):
        return self.jobs.patch_settings({'expected_configuration_version': load_settings(self.config).version,
            'changes': {'plan_fees_usd': {'Codex': '20.00', 'Claude': '100'}}})

    def test_exact_fee_comparison_publication_and_fresh_process_restart(self):
        before = self.overview()
        facts = self.rows('SELECT id,payload FROM events ORDER BY id')
        self.assertEqual(self.comparison()['difference_usd'], '-3.775309200000')
        saved = self.save_fee()
        self.assertTrue(saved['pending'])
        self.assertEqual(self.comparison()['fee_usd'], '20.00')
        self.jobs.run_one()
        after = self.overview()
        self.assertEqual(self.comparison()['difference_usd'], '-83.775309200000')
        self.assertEqual(self.comparison()['value_usd'], '16.224690800000')
        self.assertEqual(before['data']['summary'], after['data']['summary'])
        self.assertEqual(facts, self.rows('SELECT id,payload FROM events ORDER BY id'))
        self.assertEqual(dict(load_settings(self.config).plan_fees_usd), {'Codex': Decimal('20.00'), 'Claude': Decimal('100')})
        # A new process reopens the same index/configuration, rather than reusing
        # an in-memory Settings instance or an API result cache.
        code = """import json,sys
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from usage_index import UsageIndex
from test_index import context
x=UsageIndex(sys.argv[3],config_path=sys.argv[4])
r=x.query(context()).result
print(json.dumps({'fees':{c.provider:str(c.fee_usd) for c in r.comparisons},'claude_difference':str(next(c for c in r.comparisons if c.provider=='Claude').difference_usd),'tokens':str(r.total.tokens.total)}))
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', code, str(root), str(root/'tests'), str(self.path), str(self.config)],
                                capture_output=True, text=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        restarted = json.loads(result.stdout)
        self.assertEqual(restarted['fees'], {'Codex': '20.00', 'Claude': '100'})
        self.assertEqual(restarted['claude_difference'], '-83.775309200000')
        self.assertEqual(restarted['tokens'], after['data']['summary']['tokens']['total_tokens'])

    def test_failed_application_retains_old_comparison_and_same_save_can_retry(self):
        saved = self.save_fee()
        with patch.object(self.store, 'reprice', side_effect=OSError('CONTROLLED_TEST_FAILURE')):
            self.jobs.run_one()
        self.assertEqual(self.jobs.get(saved['jobs'][0]['id'])['status'], 'failed')
        self.assertTrue(self.store.status()['configuration_pending'])
        self.assertEqual(self.comparison()['fee_usd'], '20.00')
        self.assertEqual(dict(load_settings(self.config).plan_fees_usd)['Claude'], Decimal('100'))
        retried = self.save_fee()
        self.assertNotEqual(retried['jobs'][0]['id'], saved['jobs'][0]['id'])
        self.jobs.run_one()
        self.assertFalse(self.store.status()['configuration_pending'])
        self.assertEqual(self.comparison()['difference_usd'], '-83.775309200000')
