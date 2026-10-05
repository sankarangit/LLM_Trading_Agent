"""Validated LLM decisions through the existing deterministic strategy boundary."""
from copy import deepcopy
from base64 import b64encode
from dataclasses import asdict
import time
import uuid
from .data import canonical
from .types import Decision
from .baselines import validate_strategy
from .blindfold import build_payload,load_prompt
from .llm_contract import DECISION_SCHEMA,validate_output,ProviderFailure,ConfigurationError
from .llm_budget import maximum_charge,usage_charge
from .llm_cache import request_hash

def parsed_response(raw):
    try:
        if not isinstance(raw,dict) or not isinstance(raw.get('choices'),list):
            raise ValueError('malformed provider decision')
        choice=raw['choices'][0]
        if not isinstance(choice,dict): raise ValueError('malformed provider choice')
        message=choice['message']
        if not isinstance(message,dict): raise ValueError('malformed provider message')
        if choice['finish_reason']!='stop' or message.get('refusal'):
            raise ValueError('refused or incomplete model output')
        return validate_output(message['content'])
    except (KeyError,IndexError,TypeError) as exc:
        raise ValueError('malformed provider decision') from exc

def decision_for(parsed,config):
    if parsed is None: return Decision('HOLD',reason='LLM output unavailable or invalid')
    if parsed['action'] in {'LONG','SHORT'}:
        return Decision(parsed['action'],stop_distance_pct=config.stop_distance_pct,
                        reason=parsed['reason'])
    return Decision(parsed['action'],reason=parsed['reason'])

class LLMStrategy:
    def __init__(self,config,strategy_config,initial_cash,provider,budget,cache,prompt_path,
                 audit_sink=None,decision_limit=None):
        validate_strategy(strategy_config)
        if strategy_config.stop_distance_pct!=3:
            raise ConfigurationError('LLM requires the approved 3% stop')
        if strategy_config.stop_mode!='fixed_pct' or any(x is not None for x in
                (strategy_config.horizon_bars,strategy_config.target_r_multiple,strategy_config.trailing_stop_pct)):
            raise ConfigurationError('LLM requires approved fixed stop and disabled target/time/trailing exits')
        self.config,self.strategy_config,self.initial_cash=config,strategy_config,initial_cash
        self.provider,self.budget,self.cache=provider,budget,cache
        self.prompt,self.prompt_hash=load_prompt(prompt_path)
        self.audit,self.journal=[],[]
        self.audit_sink=audit_sink
        self.decision_limit=decision_limit

    def decide(self,context):
        if self.decision_limit is not None and len(self.audit)>=self.decision_limit:
            return Decision('HOLD',reason='pilot decision cutoff; pending execution only')
        payload=build_payload(context,self.initial_cash,self.config.variant,tuple(self.journal))
        request={'model':self.config.model,'temperature':self.config.temperature,
            'max_completion_tokens':self.config.max_output_tokens,
            'messages':[{'role':'system','content':self.prompt},{'role':'user','content':canonical(payload)}],
            'response_format':{'type':'json_schema','json_schema':{
                'name':'trading_decision_v1','strict':True,'schema':DECISION_SCHEMA}}}
        record={'decision_id':len(context.bars),'prompt_version':'system-v1',
            'prompt_hash':self.prompt_hash,'model_id':self.config.model,
            'model_parameters':asdict(self.config),'feature_snapshot':payload['market'].get('features',{}),
            'account_context':payload['account'],'request':request,'raw_response':None,
            'parsed':None,'errors':[],'retries':0,'cache_hit':False,'usage':None,
            'latency_seconds':0,'generation_cost_usd':None,'new_spend_usd':'0'}
        # Replay has no budget/cache/environment dependency and preserves the
        # original audit exactly, including failures and historical latency.
        if getattr(self.provider,'is_replay',False):
            saved=self.provider.record(request,record['decision_id'])
            self.audit.append(deepcopy(saved))
            parsed=saved['parsed']
            self._remember(parsed)
            return decision_for(parsed,self.strategy_config)
        raw=self.cache.get(request)
        parsed=None
        if raw is not None:
            record['cache_hit']=True
        else:
            reservation=self.budget.reserve(uuid.uuid4().hex+':'+request_hash(request),maximum_charge(request))
            record['reservation_id']=reservation
            record['new_spend_usd']=str(maximum_charge(request))
            # Durable evidence before a potentially charged external side effect.
            if self.audit_sink: self.audit_sink('request',deepcopy(record))
            start=time.monotonic()
            try:
                response=self.provider.complete(request)
                raw=response.raw
                if response.raw_body is not None:
                    record['raw_response_base64']=b64encode(response.raw_body).decode('ascii')
                record['latency_seconds']=response.latency_seconds
            except ConfigurationError as exc:
                if exc.raw_body is not None: record['raw_response_base64']=b64encode(exc.raw_body).decode('ascii')
                record['errors']=['provider_configuration_error']
                record['latency_seconds']=time.monotonic()-start
                if self.audit_sink: self.audit_sink('response',deepcopy(record))
                raise
            except (ProviderFailure,OSError) as exc:
                if getattr(exc,'raw_body',None) is not None:
                    record['raw_response_base64']=b64encode(exc.raw_body).decode('ascii')
                record['errors']=['provider_failure_charge_uncertain']
                record['latency_seconds']=time.monotonic()-start
        if raw is not None:
            record['raw_response']=raw
            record['returned_model']=raw.get('model')
            record['usage']=raw.get('usage')
            if not record['cache_hit']:
                # Record raw response before settlement so crashes cannot erase
                # the only copy of a paid decision/usage.
                if self.audit_sink: self.audit_sink('raw',deepcopy(record))
                try:
                    charge=self.budget.settle(record['reservation_id'],record['usage'])
                    record['new_spend_usd']=str(charge)
                except ValueError:
                    record['errors'].append('invalid_usage_reservation_retained_or_budget_blocked')
                    if self.audit_sink: self.audit_sink('response',deepcopy(record))
                    raise
                self.cache.put(request,raw)
            try:
                record['generation_cost_usd']=str(usage_charge(record['usage']))
                parsed=parsed_response(raw)
            except ValueError:
                record['errors'].append('invalid_or_refused_model_output')
        record['parsed']=parsed
        self.audit.append(record)
        if self.audit_sink: self.audit_sink('response',deepcopy(record))
        self._remember(parsed)
        return decision_for(parsed,self.strategy_config)

    def _remember(self,parsed):
        self.journal.append({'step':len(self.audit)-1,'action':parsed['action'] if parsed else 'HOLD',
                            'confidence':parsed['confidence'] if parsed else 0})
        self.journal=self.journal[-self.config.journal_limit:]
