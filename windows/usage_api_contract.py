"""V1 wire primitives, safe errors and a small validator for our JSON Schema vocabulary."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
import uuid

from usage_index_codec import count

CONTRACT_VERSION = 'usage-hub-v1'
TOKEN_NAMES = ('uncached_input_tokens','output_tokens','cache_read_tokens','cache_write_5m_tokens','cache_write_1h_tokens')
PROVIDERS = {'codex':'Codex','claude':'Claude'}
MAX_URL = 16384
MAX_BODY = 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024


class ApiError(ValueError):
    def __init__(self, status, code, message, field=None):
        self.status, self.code, self.message, self.field = status, code, message, field
        super().__init__(message)


def invalid(field=None):
    if field not in {'provider','period','timezone','q','selected_day','sort','page_size','cursor','query_context_id','base_query_context_id','dataset_id','project_id','model','effort','empty_selection','root_ids','providers','changes','plan_fees_usd','rate_overrides','enabled_root_ids','job_id'}:
        field=None
    return ApiError(422, 'invalid_input', 'Invalid or unsupported input; check the documented field bounds.', field)


def utc(value):
    return None if value is None else datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def money(value):
    return None if value is None else format(value, 'f')


def tokens(value, reasoning=None):
    return {**{name:str(count(getattr(value,key))) for name,key in zip(TOKEN_NAMES,('input','output','cached','write5m','write1h'))},
            'total_tokens':str(count(value.total)), 'reasoning_tokens':None if reasoning is None else str(count(reasoning))}


def app_credits(amount):
    from usage_credits import APP_UNIT, APP_UNIT_USD, app_credit_amount
    return {'unit': APP_UNIT, 'amount': money(app_credit_amount(amount)), 'usd_per_credit': money(APP_UNIT_USD)}


def summary(value, *, projected=False):
    v=value.value
    data = {'tokens':tokens(value.tokens,value.reasoning.known_tokens),
        'reasoning':{'known_records':value.reasoning.known_records,'unknown_records':value.reasoning.unknown_records},
        'record_count':value.record_count,'conversation_count':value.conversation_count,'project_count':value.project_count,
        'value':{'state':v.state,'amount_usd':money(v.amount_usd),'priced_records':v.priced_records,'unpriced_records':v.unpriced_records,
                 'priced_tokens':str(v.priced_tokens),'unpriced_tokens':str(v.unpriced_tokens),
                 'assumed_records':v.assumed_records,'assumptions':list(v.assumptions)}}
    if projected: data['app_credits'] = app_credits(v.amount_usd)
    return data


def pricing_explanation(value, explanation):
    return {'state':explanation.state,'reason':explanation.reason,'currency':'USD','rate_unit_tokens':'1000000',
        'requested_model':value.requested_model,'matched_model':value.matched_model,'model_mapping':value.model_mapping,
        'rate_id':value.rate_id,'tier':value.tier,'source':value.source,'checked_date':value.checked_date,'custom':value.custom,
        'pricing_version':value.pricing_version,'catalog_version':value.catalog_version,'override_version':value.override_version,
        'policy_version':value.policy_version,'assumptions':list(value.assumptions),
        'categories':[{'category':c.category,'tokens':str(c.tokens),'rate_usd_per_million':money(c.rate_usd_per_million),
                       'unrounded_usd':money(c.unrounded_usd)} for c in explanation.categories],
        'rounding_adjustment_usd':money(explanation.rounding_adjustment_usd)}


def pricing_breakdown(value):
    return {'group_count':value.group_count,'total_record_count':value.total_record_count,
        'shown_record_count':value.shown_record_count,'truncated':value.shown_record_count < value.total_record_count,
        'groups':[{'record_count':g.summary.priced_records + g.summary.unpriced_records,
                   'tokens':tokens(g.summary.tokens,g.reasoning_tokens),'pricing_state':g.summary.state,'amount_usd':money(g.summary.amount_usd),
                   'explanation':pricing_explanation(g.representative,g.explanation)} for g in value.groups]}


def comparison(value):
    return {'provider':value.provider.lower(),'available':value.available,'reason':value.reason,
            'pricing_state':value.pricing_state,'value_usd':money(value.value_usd),'fee_usd':money(value.fee_usd),
            'difference_usd':money(value.difference_usd),'qualifications':list(value.qualifications)}


def envelope(dataset, mode, now, kind, data, request_id=None):
    return {'contract_version':CONTRACT_VERSION,'dataset_id':dataset,'mode':mode,'generated_at':utc(now),
            'request_id':request_id or uuid.uuid4().hex,'kind':kind,'data':data}


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise invalid(key)
            result[key]=value
        return result
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_float=Decimal,
                          parse_constant=lambda _: (_ for _ in ()).throw(invalid()))
    except (ValueError,UnicodeError,RecursionError):
        raise invalid() from None


def validate_schema(value, schema, root=None):
    """Validate exactly the vocabulary used by the checked-in contract, not arbitrary schemas."""
    root=schema if root is None else root
    if '$ref' in schema:
        target=root
        for key in schema['$ref'].removeprefix('#/').split('/'): target=target[key]
        return validate_schema(value,target,root)
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try: validate_schema(value,choice,root);return
            except ValueError: pass
        raise ValueError('Schema union mismatch.')
    kind=schema.get('type')
    valid={'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),
           'string':lambda:isinstance(value,str),'integer':lambda:type(value) is int,
           'number':lambda:type(value) in (int,float),'boolean':lambda:type(value) is bool,'null':lambda:value is None}
    if kind and (kind not in valid or not valid[kind]()): raise ValueError('Schema type mismatch.')
    if 'const' in schema and (value!=schema['const'] or (type(value) is bool)!=(type(schema['const']) is bool)): raise ValueError('Schema constant mismatch.')
    if 'enum' in schema and value not in schema['enum']: raise ValueError('Schema enum mismatch.')
    if isinstance(value,str):
        if not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',32767): raise ValueError('Schema text bounds.')
        if 'pattern' in schema and re.fullmatch(schema['pattern'],value) is None: raise ValueError('Schema pattern mismatch.')
    if type(value) in (int,float):
        if not schema.get('minimum',float('-inf'))<=value<=schema.get('maximum',float('inf')): raise ValueError('Schema numeric bounds.')
    if isinstance(value,list):
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',100000): raise ValueError('Schema array bounds.')
        for item in value: validate_schema(item,schema.get('items',{}),root)
    if isinstance(value,dict):
        properties=schema.get('properties',{})
        if set(schema.get('required',()))-value.keys(): raise ValueError('Schema required field.')
        if schema.get('additionalProperties') is False and value.keys()-properties.keys(): raise ValueError('Schema extra field.')
        for key,item in value.items():
            spec=properties.get(key,schema.get('additionalProperties',{}))
            if isinstance(spec,dict): validate_schema(item,spec,root)
