"""Explicit historical pilot orchestration and zero-network archived replay."""
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import json
import os
import uuid
from .data import canonical,validate
from .llm_contract import LLMConfig,ConfigurationError
from .llm_strategy import LLMStrategy,parsed_response
from .llm_budget import BudgetLedger
from .llm_cache import ResponseCache
from .openai_provider import OpenAIProvider
from .baselines import StrategyConfig
from .features import snapshot
from .engine import run
from .storage import save_run,write_json,archive_inputs

PROJECT=Path(__file__).resolve().parents[1]

def provider_from_environment(settings):
    return OpenAIProvider(os.environ.get('OPENAI_API_KEY',''),settings.timeout_seconds)

class ReplayProvider:
    is_replay=True
    def __init__(self,records: list[dict]): self.records=records; self.index=0
    def record(self,request,decision_id):
        if self.index>=len(self.records): raise ValueError('archived LLM responses exhausted')
        row=self.records[self.index]
        if canonical(row['request'])!=canonical(request) or row['decision_id']!=decision_id:
            raise ValueError('replay LLM request differs from archive')
        if row['parsed'] is not None and parsed_response(row['raw_response'])!=row['parsed']:
            raise ValueError('replay parsed decision differs from raw output')
        self.index+=1
        return row
    def assert_exhausted(self):
        if self.index!=len(self.records): raise ValueError('unused archived LLM responses')

def pilot_window(data,c,n):
    scored=[i for i,b in enumerate(data.bars) if c.trade_start is None or b.open_time>=c.trade_start]
    if len(scored)<n+1: raise ValueError('pilot requires N decisions plus a next eligible execution bar')
    last=scored[n]
    rows=data.bars[:last+1]
    policy=replace(data.policy,expected_intervals=tuple(p for p in data.policy.expected_intervals
        if rows[0].open_time<=p[0] and p[1]<=rows[-1].close_time))
    events=tuple(e for e in c.dividends if e.ex_time<=rows[-1].close_time)
    return validate(rows,policy),replace(c,dividends=events)

def run_llm_experiment(raw,data,higher,config_path,variant,paid,pilot_decisions,offline_provider=None):
    if not paid: raise ConfigurationError('LLM requests require explicit --allow-api')
    if type(pilot_decisions) is not int or not 1<=pilot_decisions<=20:
        raise ConfigurationError('initial launch requires --pilot-decisions between 1 and 20; full pass gated after pilot review')
    # Fixture scope relaxation is available only through explicit offline
    # injection, never through a free-text label on a paid CLI configuration.
    offline=offline_provider is not None
    if offline and (isinstance(offline_provider,OpenAIProvider) or data.policy.source!='synthetic-test'):
        raise ConfigurationError('offline fixture provider requires synthetic test data')
    if not offline:
        window=raw.get('research') or {}
        expected={'start':'2005-01-01T00:00:00-05:00','end':'2014-12-31T23:59:59-05:00',
                  'holdout_start':'2024-01-01T00:00:00-05:00','holdout_end':'2025-12-31T23:59:59-05:00'}
        if (data.policy.asset not in ('SPY','GLD') or data.policy.timeframe!='1d'
            or data.policy.source=='synthetic-test' or window.get('role')!='development'
            or any(window.get(key)!=value for key,value in expected.items())):
            raise ConfigurationError('initial pilot requires the approved development dates, daily SPY/GLD and protected holdout')
    from .cli import prepare_research,parse_backtest,parse_features,require
    path=Path(config_path)
    raw,data,higher=prepare_research(raw,data,higher,path)
    settings=dict(require(raw,'llm'))
    cap=Decimal(str(require(settings,'budget_cap_usd')))
    if cap!=Decimal('10'): raise ConfigurationError('approved shared API cap is $10')
    config=LLMConfig(**{k:settings[k] for k in ('model','temperature','max_output_tokens','timeout_seconds','journal_limit')},variant=variant)
    c=parse_backtest(raw)
    f=parse_features(raw)
    s=StrategyConfig(**raw['strategy'])
    if s.allow_short!=c.risk.allow_short: raise ConfigurationError('strategy/risk short permissions differ')
    data,c=pilot_window(data,c,pilot_decisions)
    # Missing credentials fail before allocating a scored run or spending ledger.
    provider=offline_provider if offline else provider_from_environment(config)
    budget_path=(path.parent/require(settings,'budget_path')).resolve()
    cache_path=(path.parent/require(settings,'cache_path')).resolve()
    if (budget_path!=PROJECT/'data/cache/llm-budget.sqlite'
            or cache_path!=PROJECT/'data/cache/llm'):
        raise ConfigurationError('all initial assets must share the approved project budget/cache paths')
    budget=BudgetLedger(budget_path,cap)
    cache=ResponseCache(cache_path)
    run_id='llm-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    root=path.parent/require(raw,'output_root')
    dest=root/run_id
    dest.mkdir(parents=True,exist_ok=False)
    (dest/'INCOMPLETE').write_text('LLM pilot pending; interrupted runs cannot be scored.',encoding='utf-8')
    audit_dir=dest/'request_audit'
    audit_dir.mkdir()
    prompt_path=PROJECT/'prompts/system-v1.txt'
    sequence=0
    def sink(stage,record):
        nonlocal sequence
        sequence+=1
        with (audit_dir/f'{sequence:06d}-{stage}.json').open('x',encoding='utf-8') as out:
            out.write(canonical(record))
            out.flush()
            os.fsync(out.fileno())
    write_json(dest/'launch.json',{'llm':asdict(config),'pilot_decisions':pilot_decisions,
        'budget_path':str(budget_path),'research_status':'pilot_only'})
    strategy=LLMStrategy(config,s,c.initial_cash,provider,budget,cache,prompt_path,
                         audit_sink=sink,decision_limit=pilot_decisions)
    strategy_settings={'name':variant,'parameters':asdict(s),'feature_config':asdict(f),
                       'llm':asdict(config),'decision_limit':pilot_decisions}
    with (dest/'prompt.txt').open('xb') as out: out.write(strategy.prompt.encode('utf-8'))
    archive_inputs(dest,data,c,strategy_settings,higher,
                   raw.get('_research_provenance'),raw.get('_dividend_input_bytes'))
    try:
        result=run(data,strategy,c,higher,lambda rows,h:snapshot(rows,h,f))
        summary={'request_count':len(strategy.audit),'cache_hits':sum(r['cache_hit'] for r in strategy.audit),
            'failures':sum(bool(r['errors']) for r in strategy.audit),
            'new_spend_usd':str(sum((Decimal(r['new_spend_usd']) for r in strategy.audit),Decimal(0))),
            'generation_cost_usd':str(sum((Decimal(r['generation_cost_usd'] or '0') for r in strategy.audit),Decimal(0))),
            'prompt_tokens':sum((r['usage'] or {}).get('prompt_tokens',0) for r in strategy.audit),
            'completion_tokens':sum((r['usage'] or {}).get('completion_tokens',0) for r in strategy.audit),
            'budget':budget.status()}
        artifacts={'audit':strategy.audit,'prompt':strategy.prompt,'metadata':{
            'prompt_hash':strategy.prompt_hash,'model_id':config.model,'model_parameters':asdict(config),
            'research_status':'pilot_only','pilot_decisions':pilot_decisions,'llm_summary':summary}}
        return save_run(root,result,data,c,strategy_settings,
            run_id=run_id,higher_data=higher,research_provenance=raw.get('_research_provenance'),
            dividend_input_bytes=raw.get('_dividend_input_bytes'),llm_artifacts=artifacts,prepared_run_path=dest)
    except BaseException:
        with (dest/'failure.json').open('x',encoding='utf-8') as out:
            out.write(canonical({'status':'incomplete','reason':'LLM pilot interrupted; inspect request audit and budget reservations'}))
        raise

def replay_strategy(path,settings,initial_cash):
    records=[json.loads(line) for line in (Path(path)/'llm_audit.jsonl').read_text(encoding='utf-8').splitlines()]
    provider=ReplayProvider(records)
    strategy=LLMStrategy(LLMConfig(**settings['llm']),StrategyConfig(**settings['parameters']),
        initial_cash,provider,None,None,Path(path)/'prompt.txt',decision_limit=settings['decision_limit'])
    return strategy,provider
