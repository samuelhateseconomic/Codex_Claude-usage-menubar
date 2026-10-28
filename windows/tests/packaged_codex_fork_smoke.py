"""Actual executable: repair cached fork attribution, append and restart offline."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from packaged_hub_release import PackagedHost, counter
from packaged_local_hub_smoke import require, synthetic_workspace
from usage_config import Settings, effective_settings, save_settings
from usage_index import UsageIndex
from usage_observations import extract_codex
from usage_valuation import Price


def check(executable):
    with synthetic_workspace(Path(__file__).resolve().parents[1]/'build') as root:
        host=PackagedHost(executable,root)
        logs=root/'sources';empty=root/'empty';logs.mkdir();empty.mkdir();host.app.mkdir(parents=True)
        stamp=datetime.now(timezone.utc)
        parent={'type':'session_meta','timestamp':stamp.isoformat(),'payload':{'id':'portfolio-parent','cwd':'C:/fixture'}}
        outer={'type':'session_meta','timestamp':stamp.isoformat(),'payload':{'id':'research-child','cwd':'C:/fixture',
               'forked_from_id':'portfolio-parent','instructions':'PRIVATE_FORK_REPLAY_SENTINEL'}}
        context={'type':'turn_context','payload':{'model':'fork-fixture'}}
        def write(path,entries):path.write_text('\n'.join(map(json.dumps,entries))+'\n',encoding='utf-8')
        write(logs/'parent.jsonl',[parent,context,*[counter(n,stamp) for n in (100,200,300)]])
        write(logs/'child.jsonl',[outer,parent,context,*[counter(n,stamp) for n in (100,150)]])
        save_settings(effective_settings(Settings(),codex_roots=[logs],claude_roots=[empty],timezone='UTC',
                      prices={'fork-fixture':Price(2,10,'.1')}),host.config)
        # Seed the previous parser's cached attribution. No product migration or
        # destructive rebuild is used: the executable must reparse stable bytes.
        def old_parser(entries,*args,**kwargs):
            entries=list(entries)
            if entries and entries[0][1].get('payload',{}).get('forked_from_id'):entries=entries[1:]
            return extract_codex(entries,*args,**kwargs)
        with patch('usage_ingestion.extract_codex',side_effect=old_parser),patch('usage_index.PARSER_CACHE_VERSION','observations-v1:project-context-2'):
            UsageIndex(host.index,config_path=host.config).import_settings()
        try:
            host.start();host.ready();overview=host.query()
            require(overview['data']['summary']['tokens']['total_tokens']=='350','Packaged cache reparse failed.')
            require(overview['data']['summary']['conversation_count']==2,'Packaged child identity merged with parent.')
            require(Decimal(overview['data']['summary']['value']['amount_usd'])==Decimal('.0007'),'Packaged valuation differs.')
            ctx=overview['query_context_id'];listing=host.query('/usage/conversations',ctx)
            require({r['label']:r['summary']['tokens']['total_tokens'] for r in listing['data']['items']}==
                    {'portfolio-parent':'300','research-child':'50'},'Packaged conversations do not reconcile.')
            for row in listing['data']['items']:
                require(host.query('/conversations/'+row['id'],ctx)['data']['summary']==row['summary'],'Packaged detail differs.')
            with (logs/'parent.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(counter(400,stamp))+'\n')
            host.api('POST','/index/refresh',{},expected=202);host.ready()
            require(host.query()['data']['summary']['tokens']['total_tokens']=='450','Packaged append failed.')
            host.close();host.start();host.ready()
            require(host.query()['data']['summary']['tokens']['total_tokens']=='450','Packaged restart changed usage.')
        finally:host.close()
        report=root/'terminal.txt';diagnostic=root/'operation.json'
        require(host.invoke('--report','month','--audit','--output',report,'--diagnostic-output',diagnostic)==0,'Packaged terminal failed.')
        require(json.loads(diagnostic.read_text())['counts']['conversations']==2,'Terminal attribution differs.')
        require('450' in report.read_text(encoding='utf-8') and 'PRIVATE_FORK_REPLAY_SENTINEL' not in report.read_text(encoding='utf-8'),'Terminal total/privacy differs.')
    print('Packaged Codex fork: PASS (old cache reparse, 350 tokens / USD0.0007, separate parent/child/detail, append 450, restart and terminal)')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--exe',required=True,type=Path)
    check(parser.parse_args().exe.resolve(strict=True))
