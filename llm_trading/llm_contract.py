"""Strict, provider-neutral LLM contracts. Confidence is audit evidence only."""
from dataclasses import dataclass
import json
import math
from typing import Protocol

VARIANTS = ('llm_only', 'stats_llm', 'stats_llm_journal')
DECISION_SCHEMA = {
    'type':'object', 'additionalProperties':False,
    'properties':{
        'action':{'type':'string','enum':['LONG','SHORT','HOLD','CLOSE']},
        'confidence':{'type':'number','minimum':0,'maximum':1},
        'horizon_bars':{'type':'null'},
        'reason':{'type':'string','maxLength':400},
    },
    'required':['action','confidence','horizon_bars','reason'],
}

@dataclass(frozen=True)
class LLMConfig:
    model: str = 'gpt-4o-mini'
    temperature: float = 0
    max_output_tokens: int = 512
    timeout_seconds: float = 30
    variant: str = 'stats_llm'
    journal_limit: int = 20

    def __post_init__(self):
        if (self.model != 'gpt-4o-mini' or type(self.temperature) not in (int,float)
            or self.temperature != 0 or type(self.max_output_tokens) is not int
            or self.max_output_tokens != 512 or self.timeout_seconds != 30
            or isinstance(self.timeout_seconds,bool) or self.variant not in VARIANTS
            or type(self.journal_limit) is not int or self.journal_limit != 20):
            raise ValueError('LLM configuration differs from approved experiment')

@dataclass(frozen=True)
class ProviderResponse:
    raw: dict
    latency_seconds: float
    raw_body: bytes | None = None

class Provider(Protocol):
    def complete(self, request: dict) -> ProviderResponse: ...

class ConfigurationError(ValueError):
    def __init__(self,message,raw_body=None):
        super().__init__(message)
        self.raw_body=raw_body
class ProviderFailure(OSError):
    def __init__(self,message,raw_body=None):
        super().__init__(message)
        self.raw_body=raw_body
class BudgetExceeded(ValueError): pass

def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def constant(value): raise ValueError('nonfinite JSON value')
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid JSON') from exc

def validate_output(text: str) -> dict:
    value=strict_json(text)
    if not isinstance(value,dict) or set(value)!=set(DECISION_SCHEMA['required']):
        raise ValueError('decision fields do not match schema')
    if value['action'] not in ('LONG','SHORT','HOLD','CLOSE'):
        raise ValueError('invalid action')
    confidence=value['confidence']
    if type(confidence) not in (int,float) or not 0<=confidence<=1 or not math.isfinite(confidence):
        raise ValueError('invalid confidence')
    if value['horizon_bars'] is not None:
        raise ValueError('time stops are disabled in the approved experiment')
    if not isinstance(value['reason'],str) or len(value['reason'])>400:
        raise ValueError('invalid reason')
    return value
