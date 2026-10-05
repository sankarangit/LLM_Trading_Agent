from dataclasses import replace
from datetime import timedelta
import pytest
from test_engine import dataset, cfg, Scripted
from llm_trading.engine import run
from llm_trading.types import Decision


def dividend(data, ex=2, pay=4, amount=2):
    from llm_trading.actions import Dividend
    return Dividend('TEST', data.bars[ex].open_time, data.bars[pay].close_time,
                    amount, 'synthetic payment schedule')


def test_dividend_receivable_retained_after_sale_cash_waits_for_payment():
    d=dataset([(100,100)]*2+[(98,98)]*3)
    c=replace(cfg(), dividends=(dividend(d),))
    r=run(d,Scripted({0:Decision('LONG',5),1:Decision('CLOSE')}),c)
    assert r.trades[0]['dividend_pnl']==20
    assert r.trades[0]['net_pnl']==0
    assert r.equity_curve[2]['cash']==9980
    assert r.equity_curve[2]['dividend_receivable']==20
    assert r.equity_curve[2]['equity']==10000
    assert r.equity_curve[4]['cash']==10000
    assert r.equity_curve[4]['dividend_receivable']==0
    assert [e['kind'] for e in r.corporate_actions]==['entitlement','payment']


def test_buy_on_ex_date_has_no_entitlement():
    d=dataset([(100,100)]*5)
    r=run(d,Scripted({1:Decision('LONG',5)}),replace(cfg(),dividends=(dividend(d),)))
    assert r.equity_curve[-1]['equity']==10000
    assert r.corporate_actions==[]


def test_receivable_cannot_fund_a_new_entry():
    d=dataset([(100,100)]*5)
    c=replace(cfg(),dividends=(dividend(d,amount=1000),))
    r=run(d,Scripted({0:Decision('LONG',5),2:Decision('CLOSE'),3:Decision('LONG',5)}),c)
    assert r.equity_curve[3]['dividend_receivable']==10000
    assert r.orders[-1]['size']*r.orders[-1]['fill_price']<=10000


def test_future_dividend_amount_cannot_change_prior_decision():
    d=dataset([(100,100)]*5)
    runs=[run(d,Scripted({0:Decision('LONG',5)}),replace(cfg(),dividends=(dividend(d,amount=a),))) for a in [1,100]]
    assert runs[0].decisions[:2]==runs[1].decisions[:2]


def test_short_owes_distribution_and_payment_does_not_double_count():
    d=dataset([(100,100)]*2+[(98,98)]*3)
    r=run(d,Scripted({0:Decision('SHORT',5),1:Decision('CLOSE')}),replace(cfg(),dividends=(dividend(d),)))
    assert r.trades[0]['dividend_pnl']==-20
    assert r.trades[0]['net_pnl']==0
    assert r.equity_curve[-1]['equity']==10000


@pytest.mark.parametrize('invalid',['duplicate','asset','amount','payment'])
def test_invalid_dividends_block_before_strategy_calls(invalid):
    d=dataset([(100,100)]*5); e=dividend(d)
    events=(e,e) if invalid=='duplicate' else (replace(e,**{
        'asset':{'asset':'OTHER'},'amount':{'amount':float('nan')},
        'payment':{'pay_time':e.ex_time-timedelta(seconds=1)}}[invalid]),)
    s=Scripted({})
    with pytest.raises(ValueError): run(d,s,replace(cfg(),dividends=events))
    assert not s.seen


def test_warmup_never_trades_scores_or_initializes_risk_peak():
    d=dataset([(1000,1000),(1000,1000),(100,100),(100,100)])
    s=Scripted({2:Decision('LONG',5)})
    r=run(d,s,replace(cfg(),trade_start=d.bars[2].open_time))
    assert len(s.seen)==2
    assert len(s.seen[0].bars)==3
    assert len(r.equity_curve)==2
    assert r.equity_curve[0]['equity']==10000
    assert r.orders[0]['fill_timestamp']==d.bars[3].open_time.isoformat()


def test_research_window_rejects_holdout_and_removes_future_bars():
    from llm_trading.research import select_window
    d=dataset([(100,100)]*5)
    window={'start':d.bars[2].open_time.isoformat(),'end':d.bars[3].close_time.isoformat(),
            'holdout_start':d.bars[4].open_time.isoformat(),'warmup_bars':2}
    selected,start=select_window(d,window)
    assert len(selected.bars)==4
    assert start==d.bars[2].open_time
    with pytest.raises(ValueError,match='holdout'):
        select_window(d,{**window,'end':d.bars[4].close_time.isoformat()})


def test_momentum_24_and_long_only_negative_signal_exits():
    from llm_trading.baselines import StrategyConfig, build_strategy
    from llm_trading.types import Context
    d=dataset([(100,100)]*2)
    a=run(d,Scripted({0:Decision('LONG',5)}),cfg()).decisions[-1]['account_snapshot']
    from llm_trading.types import AccountSnapshot
    s=StrategyConfig(3,.01,2,.5,momentum_horizon=24,allow_short=False)
    agent=build_strategy('momentum',s,42)
    ctx=Context(d.bars[-1].close_time,d.bars,(),AccountSnapshot(**a),
                (('return_8',.05),('return_24',-.05)))
    assert agent.decide(ctx).action=='CLOSE'


def test_dividend_inputs_ledger_and_warmup_replay_are_immutable(tmp_path):
    from llm_trading.baselines import StrategyConfig,build_strategy
    from llm_trading.features import FeatureConfig,snapshot
    from llm_trading.storage import save_run,load_saved
    from llm_trading.cli import replay
    from dataclasses import asdict
    d=dataset([(100,100)]*7)
    c=replace(cfg(),dividends=(dividend(d,ex=3,pay=5),),trade_start=d.bars[1].open_time)
    s=StrategyConfig(5,.01,2,.5)
    f=FeatureConfig()
    r=run(d,build_strategy('buy_hold',s,c.seed),c,feature_fn=lambda rows,h:snapshot(rows,h,f))
    path=save_run(tmp_path,r,d,c,{'name':'buy_hold','parameters':asdict(s),'feature_config':asdict(f)})
    assert replay(path)['identical']
    saved=load_saved(path)
    assert 'corporate_actions.json' in saved['metadata']['artifact_hashes']
    provenance={'research_window':{'start':c.trade_start.isoformat()},
                'dividend_source_input':{'complete':True,'source_hashes':{'fixture':'recorded-hash'}}}
    path2=save_run(tmp_path,r,d,c,{'name':'buy_hold','parameters':asdict(s),'feature_config':asdict(f)},
                   research_provenance=provenance,dividend_input_bytes=b'{"complete": true}')
    assert load_saved(path2)['config']['research_provenance']==provenance
    assert (path2/'dividend_input.json').read_bytes()==b'{"complete": true}'
    assert 'dividend_input.json' in load_saved(path2)['metadata']['artifact_hashes']
    (path/'corporate_actions.json').write_text('[]')
    with pytest.raises(ValueError,match='integrity'):
        load_saved(path)


def test_research_preparation_rejects_incomplete_or_tampered_event_inputs(tmp_path):
    import json
    from hashlib import sha256
    from llm_trading.cli import prepare_research
    d=dataset([(100,100)]*5)
    window={'start':d.bars[1].open_time.isoformat(),'end':d.bars[3].close_time.isoformat(),
            'holdout_start':d.bars[4].open_time.isoformat(),'warmup_bars':1}
    p=tmp_path/'dividends.json'
    p.write_text(json.dumps({'complete':False,'events':[]}))
    raw={'research':window,'dividend_input':{'path':'dividends.json','sha256':sha256(p.read_bytes()).hexdigest()},'backtest':{}}
    with pytest.raises(ValueError,match='incomplete'):
        prepare_research(raw,d,None,tmp_path/'config.json')
    p.write_text('{}')
    with pytest.raises(ValueError,match='integrity'):
        prepare_research(raw,d,None,tmp_path/'config.json')


def test_payment_source_cannot_silently_omit_or_add_distribution_dates():
    from llm_trading.actions import reconcile_dates
    with pytest.raises(ValueError,match='missing'):
        reconcile_dates({'2010-06-18','2010-06-25'}, {'2010-06-18'})
    with pytest.raises(ValueError,match='unexpected'):
        reconcile_dates({'2010-06-18'}, {'2010-06-18','2010-06-25'})
    reconcile_dates({'2010-06-18'}, {'2010-06-18'})


def test_benchmark_report_serializes_approved_datetime_configuration(tmp_path):
    from llm_trading.reporting import benchmark_report
    from dataclasses import asdict
    d=dataset([(100,100)]*5)
    c=replace(cfg(),trade_start=d.bars[1].open_time,dividends=(dividend(d),))
    path=tmp_path/'report.html'
    comparison={'deterministic':[],'random_agents':[{'metrics':{'total_return':0}}],
                'random_distribution':{'median':0},'provenance':{'backtest':asdict(c)}}
    benchmark_report(comparison,path)
    assert d.bars[1].open_time.isoformat() in path.read_text()
