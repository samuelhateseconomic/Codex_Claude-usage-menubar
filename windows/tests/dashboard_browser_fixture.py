"""Controlled synthetic publication served by the actual production HTTP handler.

No personal roots, credentials or provider adapters. Stdin controls exist only
in this acceptance process, never in the production HTTP API.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from test_api import ApiFixture
from test_index import counter, claude
from usage_hub import create_server
from usage_valuation import Price
from usage_api_contract import utc


def main():
    f=ApiFixture();f.setUp()
    now=datetime(2026,10,27,14,30,tzinfo=timezone.utc).timestamp()
    f.service.clock=f.query.clock=lambda:now
    prices={'gpt-6.1-sol':Price(2,10,'.1'),'claude-opus-5-5':Price(4,20,'.2',5,8)}
    f.change_settings(prices=prices)
    first=counter(15000,5,day='2026-10-18',cached=10000,output=500)
    second=counter(30000,10,day='2026-10-18',cached=20000,output=1000)
    for e,n in [(first,150),(second,300)]:e['payload']['info']['total_token_usage']['reasoning_output_tokens']=n
    f.write(events=[first,second],model='gpt-6.1-sol',project='C:/synthetic/usage-hub')
    f.write('b.jsonl',[counter(40000,10,day='2026-10-23',cached=20000,output=2000)],model='gpt-6.1-sol',session='codex-2',project='C:/synthetic/usage-hub')
    f.write('c.jsonl',[counter(50000,10,day='2026-10-26',cached=20000,output=3000)],model='gpt-6.1-sol',session='codex-3',project=r'C:\Windows\Synthetic fixture\Long parent folder for portfolio research\Another folder with a deliberately long name\Techna_Internet')
    c=claude(project='C:/synthetic/usage-hub');c['message']['model']='claude-opus-5-5'
    (f.claude/'a.jsonl').write_text(json.dumps(c)+'\n',encoding='utf-8')
    # A known non-primary record verifies it survives storage but is excluded.
    f.write('other.jsonl',[counter(999999,10)],model='fixture-model',session='excluded-model')
    f.store.import_settings();f.jobs.start()
    def limits(mode='normal'):
        for provider,remaining in [('codex',62),('claude',28)]:
            windows=[{'label':'5-hour window','used_percent':100-remaining,'remaining_percent':remaining,'resets_at':utc(now+8280),'duration_minutes':300},
                     {'label':'Weekly window','used_percent':20,'remaining_percent':80,'resets_at':utc(now+86400),'duration_minutes':10080}]
            if mode=='weekly':windows=windows[1:]
            if mode=='boundaries':windows=[dict(windows[0],remaining_percent=n,used_percent=100-n) for n in (0,50,100)]
            f.service.limits.cached[provider]={'provider':provider,'scope':'active_cli_account','state':'stale' if mode=='stale' else 'available','phase':'disabled','category':'cached',
                'last_attempt_at':utc(now),'last_success_at':utc(now),'next_eligible_at':None,'snapshot':{'blocked':False,'windows':windows}}
    limits()
    server=create_server(f.service,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    print(json.dumps({'origin':'http://127.0.0.1:'+str(server.server_port),'launch':server.sessions.issue()}),flush=True)
    try:
        for line in sys.stdin:
            command=line.strip()
            if command=='quit':break
            if command=='launch':response={'launch':server.sessions.issue()}
            elif command.startswith('limits:'):limits(command.split(':')[1]);response={'ok':True}
            elif command=='publish':
                f.write('new.jsonl',[counter(100,10,day='2026-10-27')],model='gpt-6.1-sol',session='new-publication');f.store.import_settings();response={'ok':True}
            elif command=='many':
                for i in range(65):f.write(f'project-{i}.jsonl',[counter(100+i,10)],model='gpt-6.1-sol',session=f'project-{i}',project=f'C:/synthetic/p{i}')
                f.store.import_settings();response={'ok':True}
            elif command in ('partial','zero','restore'):
                changes={'claude-opus-5-5':Price(4,20,'.2')} if command=='partial' else {'gpt-6.1-sol':Price(0,0,0)} if command=='zero' else prices
                f.change_settings(prices=changes);f.store.reprice();response={'ok':True}
            else:response={'ok':False}
            print(json.dumps(response),flush=True)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3);f.doCleanups()


if __name__=='__main__':main()
