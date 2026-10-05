from dataclasses import replace
from datetime import timedelta
import json
import pytest
from test_engine import dataset, cfg, Scripted
from llm_trading.engine import run
from llm_trading.blindfold import build_payload

def context(data=None):
    s=Scripted({})
    run(data or dataset([(100,100),(110,110)]),s,cfg())
    return s.seen[-1]

def test_prices_account_and_feature_strings_cannot_identify_asset():
    c=replace(context(),features=(('return_1',.1),('regime','SPY 2024'),('ticker','SPY')))
    with pytest.raises(ValueError): build_payload(c,10000,'stats_llm',())
    p=build_payload(replace(c,features=(('return_1',.1),('ticker','SPY'))),10000,'stats_llm',())
    assert p['market']['indexed_closes']==[100.0,110.0]
    assert p['market']['offsets']==[-1,0]
    assert p['market']['features']=={'return_1':.1}
    assert p['account']['equity_fraction']==1
    text=json.dumps(p)
    assert not any(x in text for x in ('TEST','SPY','2020','entry_price','position_size','timestamp'))

def test_capital_and_price_scaling_preserve_payload():
    a=context()
    b=context(dataset([(1000,1000),(1100,1100)]))
    b=replace(b,account=replace(b.account,cash=20000,equity=20000,peak_equity=20000))
    assert build_payload(a,10000,'stats_llm',())==build_payload(b,20000,'stats_llm',())

def test_future_bars_and_incomplete_higher_context_rejected():
    c=context()
    future=replace(c.bars[-1],close_time=c.timestamp+timedelta(days=1))
    with pytest.raises(ValueError): build_payload(replace(c,bars=c.bars+(future,)),10000,'stats_llm',())
    with pytest.raises(ValueError): build_payload(replace(c,higher_bars=(future,)),10000,'stats_llm',())
    s1,s2=Scripted({}),Scripted({})
    run(dataset([(100,100),(110,110),(120,120)]),s1,cfg())
    run(dataset([(100,100),(110,110),(900,900)]),s2,cfg())
    assert build_payload(s1.seen[1],10000,'stats_llm',())==build_payload(s2.seen[1],10000,'stats_llm',())

def test_journal_is_bounded_prior_allowlisted_fields_only():
    c=context(dataset([(100,100)]*31))
    journal=tuple({'step':i,'action':'HOLD','confidence':.5,'reason':'SPY 2024-01-01'} for i in range(30))
    p=build_payload(c,10000,'stats_llm_journal',journal)
    assert len(p['journal'])==20
    assert p['journal'][-1]=={'offset':-1,'action':'HOLD','confidence':.5}
    assert 'SPY' not in json.dumps(p)
    assert build_payload(c,10000,'stats_llm',journal)['journal']==[]
    assert 'features' not in build_payload(c,10000,'llm_only',())['market']
    with pytest.raises(ValueError): build_payload(c,10000,'stats_llm_journal',({'step':-1,'action':'HOLD','confidence':.5},))
    with pytest.raises(ValueError): build_payload(c,10000,'stats_llm_journal',({'step':31,'action':'HOLD','confidence':.5},))
