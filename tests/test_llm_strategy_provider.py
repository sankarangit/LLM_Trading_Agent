from dataclasses import replace
from decimal import Decimal
import json
import urllib.error
import pytest
from test_engine import dataset, cfg
from test_baselines_cli import strategy_config
from llm_trading.engine import run
from llm_trading.llm_contract import LLMConfig, ProviderResponse, ProviderFailure, ConfigurationError, BudgetExceeded
from llm_trading.llm_budget import BudgetLedger
from llm_trading.llm_cache import ResponseCache
from llm_trading.llm_strategy import LLMStrategy
from llm_trading.openai_provider import OpenAIProvider

def response(action='LONG',confidence=.72,content=None):
    return {'id':'test','object':'chat.completion','created':0,'model':'gpt-4o-mini-2024-07-18',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','refusal':None,
                'content':content or json.dumps({'action':action,'confidence':confidence,'horizon_bars':None,'reason':'Trend'})}}],
            'usage':{'prompt_tokens':2000,'completion_tokens':200,'total_tokens':2200}}

class Fake:
    def __init__(self,raw=None,error=None): self.raw=raw or response(); self.error=error; self.calls=[]
    def complete(self,request):
        self.calls.append(request)
        if self.error: raise self.error
        return ProviderResponse(self.raw,.01)

def agent(tmp_path,provider,**kw):
    from pathlib import Path
    return LLMStrategy(LLMConfig(),replace(strategy_config(),stop_distance_pct=3),10000,provider,
        BudgetLedger(tmp_path/'budget.sqlite',Decimal('10')),ResponseCache(tmp_path/'cache'),
        Path(__file__).parents[1]/'prompts/system-v1.txt',**kw)

def test_llm_signal_next_open_stop_and_confidence_not_position_size(tmp_path):
    out=[]
    for confidence in (.1,.99):
        s=agent(tmp_path/str(confidence),Fake(response(confidence=confidence)))
        r=run(dataset([(100,100),(110,110),(111,111)]),s,cfg())
        assert r.orders[0]['fill_price']==110
        assert r.orders[0]['fill_timestamp']==dataset([(100,100),(110,110)]).bars[1].open_time.isoformat()
        assert r.decisions[0]['decision']['stop_distance_pct']==3
        out.append(r.orders[0]['size'])
        assert s.audit[0]['parsed']['confidence']==confidence
        assert 'TEST' not in json.dumps(s.audit[0]['request'])
    assert out[0]==out[1]

@pytest.mark.parametrize('raw',[response(content='not json'),
    {**response(),'choices':[{'finish_reason':'length','message':{'content':'{}','refusal':None}}]},
    {**response(),'choices':[{'finish_reason':'stop','message':{'content':None,'refusal':'refused'}}]}])
def test_invalid_provider_output_yields_audited_hold(tmp_path,raw):
    s=agent(tmp_path,Fake(raw))
    r=run(dataset([(100,100)]),s,cfg())
    assert r.decisions[0]['decision']['action']=='HOLD'
    assert s.audit[0]['errors']
    assert Decimal(s.audit[0]['new_spend_usd'])==Decimal('0.00042')

def test_timeout_reserves_once_no_retries_and_authentication_aborts(tmp_path):
    fake=Fake(error=ProviderFailure('uncertain'))
    s=agent(tmp_path,fake)
    r=run(dataset([(100,100)]),s,cfg())
    assert r.decisions[0]['decision']['action']=='HOLD'
    assert len(fake.calls)==1
    assert s.budget.spent_and_reserved()==Decimal('.0195072')
    with pytest.raises(ConfigurationError):
        run(dataset([(100,100)]),agent(tmp_path/'auth',Fake(error=ConfigurationError('auth'))),cfg())

def test_exact_cache_hit_adds_no_paid_calls_and_short_rejected(tmp_path):
    fake=Fake(response(action='SHORT'))
    s=agent(tmp_path,fake)
    c=replace(cfg(),risk=replace(cfg().risk,allow_short=False))
    r=run(dataset([(100,100)]),s,c)
    assert not r.orders
    spent=s.budget.spent_and_reserved()
    second=agent(tmp_path,Fake(error=AssertionError('network forbidden')))
    run(dataset([(100,100)]),second,c)
    assert second.audit[0]['cache_hit'] is True
    assert second.audit[0]['new_spend_usd']=='0'
    assert second.budget.spent_and_reserved()==spent

def test_exhausted_budget_never_calls_provider(tmp_path):
    fake=Fake()
    s=agent(tmp_path,fake)
    s.budget.reserve('other',Decimal('10'))
    with pytest.raises(BudgetExceeded): run(dataset([(100,100)]),s,cfg())
    assert fake.calls==[]

def test_https_adapter_fixed_endpoint_schema_and_safe_http_errors():
    calls=[]
    def transport(request,timeout):
        calls.append((request,timeout))
        raise urllib.error.HTTPError(request.full_url,401,'secret-key',{},None)
    provider=OpenAIProvider('not-a-real-key',30,transport)
    with pytest.raises(ConfigurationError) as error: provider.complete({'model':'gpt-4o-mini'})
    assert 'not-a-real-key' not in str(error.value)
    assert 'secret-key' not in str(error.value)
    assert calls[0][0].full_url=='https://api.openai.com/v1/chat/completions'

@pytest.mark.parametrize('message',[None,[], 'malformed',42])
def test_malformed_message_container_produces_audited_hold(tmp_path,message):
    raw=response()
    raw['choices'][0]['message']=message
    s=agent(tmp_path,Fake(raw))
    result=run(dataset([(100,100)]),s,cfg())
    assert result.decisions[0]['decision']['action']=='HOLD'
    assert s.audit[0]['raw_response']==raw
    assert s.audit[0]['errors']

def test_unapproved_stop_rejected_before_paid_execution(tmp_path):
    from pathlib import Path
    with pytest.raises(ConfigurationError,match='3%'):
        LLMStrategy(LLMConfig(),strategy_config(),10000,Fake(),None,None,
                    Path(__file__).parents[1]/'prompts/system-v1.txt')

def test_quota_exhaustion_aborts_instead_of_scoring_hold():
    from io import BytesIO
    def transport(request,timeout):
        raise urllib.error.HTTPError(request.full_url,429,'quota',{},
            BytesIO(b'{"error":{"code":"insufficient_quota","type":"insufficient_quota"}}'))
    with pytest.raises(ConfigurationError,match='quota'):
        OpenAIProvider('not-real',30,transport).complete({'model':'gpt-4o-mini'})

def test_exact_malformed_response_bytes_survive_provider_failure_and_audit(tmp_path):
    from io import BytesIO
    body=b'{paid-but-malformed-json\xff'
    def transport(request,timeout): return BytesIO(body)
    provider=OpenAIProvider('not-real',30,transport)
    with pytest.raises(ProviderFailure) as error: provider.complete({'model':'gpt-4o-mini'})
    assert error.value.raw_body==body
    s=agent(tmp_path,provider)
    result=run(dataset([(100,100)]),s,cfg())
    assert result.decisions[0]['decision']['action']=='HOLD'
    from base64 import b64decode
    assert b64decode(s.audit[0]['raw_response_base64'])==body
