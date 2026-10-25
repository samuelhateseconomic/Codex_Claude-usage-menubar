"""Construct actual synthetic v1 responses for schema and semantic acceptance."""
import json
from usage_valuation import Price
from test_index import counter,claude


def responses(fixture):
    x=fixture
    item=counter(1010000,10,cached=1000000,output=1830000)
    item['payload']['info']['total_token_usage']['reasoning_output_tokens']=1260000
    x.write(events=[item]);(x.claude/'a.jsonl').write_text(json.dumps(claude())+'\n',encoding='utf-8');x.store.import_settings()
    overview=x.overview();params=x.frozen(overview)
    listing=x.query.read('/usage/conversations',params);identity=listing['data']['items'][0]['id']
    fixtures={'overview':overview,'conversations':listing,'projects':x.query.read('/usage/projects',params),
      'facets':x.query.read('/usage/facets',params),'conversation':x.query.read('/conversations/'+identity,params),
      'events':x.query.read('/conversations/'+identity+'/events',params),'status':x.service.read('/status',{}),
      'settings':x.service.read('/settings',{}),'limits':x.service.read('/limits',{})}
    for provider in ('codex','claude'):fixtures['overview_'+provider]=x.overview({'provider':[provider]})
    fixtures['empty']=x.overview({'q':['nothing-matches']})
    job,_=x.jobs.submit();fixtures['job_queued']=x.service.read('/jobs/'+job['id'],{});x.jobs.run_one();fixtures['job_succeeded']=x.service.read('/jobs/'+job['id'],{})
    fixtures['limits_refresh']=x.service.mutate('POST','/limits/refresh',{'providers':['codex','claude']})[1]
    settings=x.jobs.patch_settings({'expected_configuration_version':x.settings.version,'changes':{'plan_fees_usd':{'Codex':'20','Claude':'20'}}})
    fixtures['settings_saved']=x.service.respond('settings_saved',settings)
    x.write('unpriced.jsonl',[counter(10,10)],session='unpriced-session',model='unpriced-model');x.store.import_settings()
    fixtures['partial']=x.overview();fixtures['unpriced']=x.overview({'model':['unpriced-model']})
    unpriced_params=x.frozen(fixtures['unpriced'])
    unpriced_id=x.query.read('/usage/conversations',unpriced_params)['data']['items'][0]['id']
    fixtures['events_unpriced']=x.query.read('/conversations/'+unpriced_id+'/events',unpriced_params)
    # Earlier contexts are deliberately stale after import; open a fresh provider context.
    claude_params=x.frozen(x.overview({'provider':['claude']}))
    claude_id=x.query.read('/usage/conversations',claude_params)['data']['items'][0]['id']
    fixtures['events_claude']=x.query.read('/conversations/'+claude_id+'/events',claude_params)
    x.change_settings(prices={'fixture-model':Price(0,0,0),'fixture-claude':Price(0,0,0,0,0)})
    x.store.reprice();fixtures['priced_zero']=x.overview({'model':['fixture-model','fixture-claude']})
    fixtures['events_zero']=x.query.read('/conversations/'+identity+'/events',x.frozen(fixtures['priced_zero']))
    fixtures['invalid_input']={'error':{'code':'invalid_input','message':'Invalid or unsupported input; check the documented field bounds.','field_errors':{'provider':'Invalid value.'}},'request_id':'synthetic-request'}
    return fixtures
