from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_records import Record, Tokens
from usage_service import query_usage, build_usage_result, SourceQuality, QueryContext, UsageFilters
from usage_time import resolve_range
from usage_ingestion import ScanIssue
from usage_reconciliation import AccountingIssue
from usage_reports import render_text_report, save_report
from usage_terminal import render_terminal, cell_width, token_label
from usage_valuation import build_catalog, Price

NOW=datetime(2026,10,24,18,tzinfo=timezone.utc).timestamp()


def fixture(extra=()):
    context=QueryContext(tuple((p,resolve_range('month',NOW,timezone='UTC')) for p in ('Codex','Claude')),NOW,'month','UTC')
    records=(Record('Codex',NOW-3,'private-session-one','C:/private-parent/測試','known',Tokens(10000,1830000,1000000),reasoning_tokens=1260000),
             Record('Claude',NOW-2,'private-session-two','C:/private-parent/測試','known-claude',Tokens(10000,20000,30000,5000)),*extra)
    catalog=build_catalog({'known':Price('2','10','.1'),'known-claude':Price('4','20','.2','5','8')})
    return build_usage_result(records,context,catalog,sources=(SourceQuality('Codex','complete'),SourceQuality('Claude','complete')))


class TerminalTests(unittest.TestCase):
    def test_default_summary_is_one_screen_and_preserves_exact_authority(self):
        result=fixture()
        before=repr(result)
        text=render_terminal(result)
        self.assertTrue(20<=len(text.splitlines())<=30,len(text.splitlines()))
        self.assertTrue(all(cell_width(line)<=80 for line in text.splitlines()))
        for value in ('$18.8910','2.91M','-$1.58','-$19.53','-$21.11','Monthly plan $20.00','unmatched accounts','reasoning','Cache reads reuse','--details','--audit','+0000'):
            self.assertIn(value,text)
        for hidden in ('private-session','private-parent','RATES -','MODEL + EFFORT'):
            self.assertNotIn(hidden,text)
        self.assertEqual(repr(result),before)
        self.assertEqual(result.total.tokens.total,2905000)
        self.assertEqual(result.total.value.amount_usd,Decimal('18.891'))

    def test_all_group_pages_reconcile_and_keep_full_summary_context(self):
        result=fixture((Record('Codex',NOW-1,'third','other','unknown',Tokens(7)),))
        with patch('usage_service.query_usage',side_effect=AssertionError('no rescan')):
            for dimension in ('provider','model','model_effort','effort','project','conversation','day'):
                groups=result.groups_for(dimension,'value_desc')
                for page in range(1,len(groups)+1):
                    text=render_terminal(result,dimension=dimension,page=page,page_size=1)
                    self.assertIn(f'page {page}/{len(groups)}',text)
                    self.assertIn('Recorded tokens: 2.91M',text)
                    self.assertIn('$18.8910',text)
                    self.assertIn('headline covers all matched groups',text)
        self.assertIn('known-claude',render_terminal(result,dimension='model',page=2,page_size=1))
        self.assertIn('unknown',render_terminal(result,dimension='model',page=3,page_size=1))
        self.assertIn('Unavailable (all usage unpriced)',render_terminal(result,dimension='model',page=3,page_size=1))
        self.assertEqual(render_terminal(result),render_text_report(result,view='summary'))

    def test_empty_unpriced_partial_and_zero_remain_distinct(self):
        result=fixture()
        empty=build_usage_result([],result.context,result.catalog,sources=(SourceQuality('Codex','failed'),SourceQuality('Claude','empty')))
        text=render_terminal(empty)
        self.assertIn('Unavailable (no usage records)',text)
        self.assertIn('Codex source: failed',text)
        self.assertIn('Difference unavailable',text)
        unknown=replace(result.details[0].record,model='unpriced')
        unpriced=build_usage_result([unknown],result.context,result.catalog)
        self.assertIn('Unavailable (all usage unpriced)',render_terminal(unpriced))
        self.assertNotIn('$0.0000',render_terminal(unpriced))
        partial=fixture((unknown,))
        text=render_terminal(partial)
        self.assertIn('priced subtotal only',text)
        self.assertIn('Differences use priced usage only',text)
        zero=build_usage_result([result.details[0].record],result.context,build_catalog({'known':Price(0,0,0)}))
        self.assertIn('Estimated API value: $0.0000',render_terminal(zero))
        self.assertIn('Pricing coverage: complete',render_terminal(zero))

    def test_source_counter_price_assumptions_are_separate_and_notes_do_not_spill(self):
        result=fixture()
        result=replace(result,sources=(SourceQuality('Codex','partial',(ScanIssue('fixture','PRIVATE RAW NOTICE'),),
            (AccountingIssue('fixture','PRIVATE RAW NOTICE',()),)),SourceQuality('Claude','complete')),
            notices=('PRIVATE RAW NOTICE',))
        text=render_terminal(result)
        self.assertIn('Codex source: partial | scan issues 1 | counter issues 1',text)
        self.assertIn('Pricing coverage: complete',text)
        self.assertIn('Tier/TTL assumptions:',text)
        self.assertNotIn('PRIVATE RAW NOTICE',text)
        self.assertIn('PRIVATE RAW NOTICE',render_text_report(result))

    def test_unicode_controls_and_long_metadata_wrap_without_mutating_identity(self):
        result=fixture()
        record=replace(result.details[0].record,project='C:/private-parent/'+'測試e\u0301'*70+'\x1b[2J\u202e')
        result=build_usage_result([record],result.context,result.catalog)
        original=repr(result)
        for width in (40,60,80,120):
            text=render_terminal(result,dimension='project',width=width)
            self.assertTrue(all(cell_width(line)<=width for line in text.splitlines()))
            self.assertNotIn('\x1b',text)
            self.assertNotIn('\u202e',text)
            self.assertNotIn('private-parent',text)
            self.assertIn('\\u001b',text.replace('\n',''))
        full=render_terminal(result,dimension='project',include_metadata=True)
        self.assertIn('private-parent',full)
        self.assertEqual(repr(result),original)

    def test_compact_token_units_are_decimal_and_do_not_change_counts(self):
        with localcontext() as context:
            context.prec=1
            for count,expected in ((0,'0'),(999999,'999,999'),(1000000,'1M'),(1234567,'1.23M'),(2905000,'2.91M'),
                (999999999,'1B'),(1234567890,'1.23B'),(2**63-1,'9223372036.85B')):
                self.assertEqual(token_label(count),expected)

    def test_provider_unavailable_fee_unknown_filter_and_period_guards(self):
        result=fixture()
        null_fee=build_usage_result([d.record for d in result.details],result.context,result.catalog,fees={'Codex':None,'Claude':Decimal(0)})
        text=render_terminal(null_fee)
        self.assertIn('monthly fee not configured',' '.join(text.split()))
        self.assertIn('Monthly plan $0.00',text)
        self.assertIn('one or more selected providers unavailable',' '.join(text.split()))
        for period in ('today','week','session'):
            text=render_terminal(query_usage(period,now=NOW,demo=True))
            self.assertIn('Plan comparison unavailable',text)
            self.assertNotIn('Difference -',text)
        context=replace(result.context,filters=UsageFilters(models=('known',)))
        filtered=build_usage_result([d.record for d in result.details],context,result.catalog)
        self.assertIn('metadata-filtered query',render_terminal(filtered))

    def test_rendering_validates_modes_pages_and_preserves_legacy_audit(self):
        result=fixture()
        for kwargs in ({'width':39},{'width':161},{'dimension':'invalid'},{'page':0},{'page_size':51},{'page':99,'dimension':'model'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                render_terminal(result,**kwargs)
        audit=render_text_report(result)
        self.assertIn('2,905,000',audit)
        self.assertIn('RATES - USD PER MILLION TOKENS',audit)
        self.assertEqual(audit,render_text_report(result,view='audit'))
        with tempfile.TemporaryDirectory() as folder:
            output=save_report(result,Path(folder)/'summary.txt',format='text',text_view='summary')
            self.assertEqual(output.read_text(encoding='utf-8'),render_terminal(result))
            generated=Path(folder)/'generated'
            with patch('usage_reports.generated_directory',return_value=generated), self.assertRaises(ValueError):
                save_report(result,format='text',text_view='details',page=99)
            self.assertFalse(generated.exists())

    def test_cli_summary_detail_paging_audit_width_and_failures_are_real_commands(self):
        script=Path(__file__).resolve().parents[1]/'usage_tray.py'
        with tempfile.TemporaryDirectory() as folder:
            environment=dict(os.environ,LOCALAPPDATA=folder)
            def cli(*args):
                return subprocess.run([sys.executable,str(script),'--report','month','--demo',*args],env=environment,capture_output=True,text=True,encoding='utf-8',timeout=10)
            summary=cli()
            self.assertEqual(summary.returncode,0,summary.stderr)
            self.assertLessEqual(len(summary.stdout.splitlines()),30)
            self.assertNotIn('MODEL + EFFORT',summary.stdout)
            first=cli('--details','model','--page-size','1')
            second=cli('--details','model','--page-size','1','--page','2')
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertEqual(second.returncode,0,second.stderr)
            self.assertIn('1. Claude / claude-sonnet-4-6',first.stdout)
            self.assertIn('2. Codex / gpt-5.4',second.stdout)
            self.assertIn('$0.2658',first.stdout)
            self.assertIn('$0.2658',second.stdout)
            narrow=cli('--width','40','--details','conversation')
            self.assertEqual(narrow.returncode,0,narrow.stderr)
            self.assertTrue(all(cell_width(line)<=40 for line in narrow.stdout.splitlines()))
            self.assertNotIn('demo-conversation',narrow.stdout)
            self.assertIn('RATES - USD PER MILLION TOKENS',cli('--audit').stdout)
            for args in (('--details','model','--page','99'),('--page','1'),('--width','39'),('--audit','--details','model'),('--details','model','--report-format','html')):
                result=cli(*args)
                self.assertNotEqual(result.returncode,0,args)
            self.assertEqual(cli().returncode,0)


if __name__=='__main__':
    unittest.main()
