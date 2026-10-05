import json
import pytest
from llm_trading.llm_contract import LLMConfig, validate_output, DECISION_SCHEMA

GOOD = {'action':'LONG','confidence':0.72,'horizon_bars':None,'reason':'Positive trend.'}

def test_valid_output_and_schema_boundaries():
    assert validate_output(json.dumps(GOOD)) == GOOD
    assert DECISION_SCHEMA['additionalProperties'] is False

@pytest.mark.parametrize('change',[
    {'action':'BUY'}, {'confidence':True}, {'confidence':-0.01},
    {'confidence':1.01}, {'confidence':float('nan')},
    {'confidence':float('inf')}, {'horizon_bars':4}, {'reason':'x'*401},
    {'reason':None}, {'size':100}, {'confidence':10**309},
])
def test_untrusted_output_cannot_change_risk_or_escape_schema(change):
    with pytest.raises(ValueError):
        validate_output(json.dumps({**GOOD,**change}))

@pytest.mark.parametrize('text',['{}','[]','not json',
    '{"action":"HOLD","action":"LONG","confidence":0.5,"horizon_bars":null,"reason":"x"}'])
def test_incomplete_or_duplicate_json_rejected(text):
    with pytest.raises(ValueError): validate_output(text)

def test_unsupported_configuration_rejected_before_provider_call():
    with pytest.raises(ValueError): LLMConfig(model='other')
    with pytest.raises(ValueError): LLMConfig(max_output_tokens=10000)
    with pytest.raises(ValueError): LLMConfig(variant='unknown')
