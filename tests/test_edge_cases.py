from dataclasses import replace
from datetime import timedelta
import json
import pytest
from llm_trading.data import Bar, DataPolicy, validate
from llm_trading.engine import run
from llm_trading.features import FeatureConfig,snapshot
from llm_trading.baselines import build_strategy
from llm_trading.storage import save_run
from llm_trading.metrics import calculate
from llm_trading.types import Decision,ExecutionConfig,RiskConfig
from test_engine import dataset,cfg,Scripted
from test_baselines_cli import strategy_config


def test_future_perturbation_cannot_change_rolling_scalers_or_prior_regime_decisions():
    before=[(100+i*.1,100+i*.1) for i in range(60)]
    a=dataset(before+[(106,106)]*5)
    b=dataset(before+[(1000,1000)]*5)
    rs=[run(d,build_strategy("statistical_regime",strategy_config(),42),cfg(),
            feature_fn=lambda rows,h:snapshot(rows,h,FeatureConfig())) for d in (a,b)]
    for left,right in zip(rs[0].decisions[:60],rs[1].decisions[:60]):
        for key in ("decision","feature_snapshot","account_snapshot","risk_result"):
            assert left[key]==right[key]


def test_trailing_stop_from_close_is_not_applied_retroactively_to_same_bar_low():
    # Entry stop 90. Entry bar low 91 is safe; close 110 schedules trail at 99.
    d=dataset([(100,100),(100,110),(98,98)],[(99,101),(91,111),(97,99)])
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=10,trailing_stop_pct=10)}),cfg())
    assert r.trades[0]["exit_price"]==98
    assert r.trades[0]["exit_reason"]=="stop_gap"
    assert r.trades[0]["exit_timestamp"]==d.bars[2].open_time.isoformat()


def test_ambiguous_bar_can_be_rejected_instead_of_assumed():
    c=cfg(execution=replace(cfg().execution,ambiguity_policy="reject"))
    with pytest.raises(ValueError,match="ambiguous"):
        run(dataset([(100,100),(100,100)],[(99,101),(90,110)]),
            Scripted({0:Decision("LONG",stop_distance_pct=5,target_r_multiple=1)}),c)


def test_daily_kill_resets_on_new_day_but_drawdown_kill_does_not():
    original=dataset([(100,100),(100,80),(80,80),(80,80),(80,80)])
    t=original.bars[0].open_time
    rows=tuple(replace(b,open_time=t+timedelta(hours=i if i<3 else 24+i-3),
                       close_time=t+timedelta(hours=i+1 if i<3 else 25+i-3)) for i,b in enumerate(original.bars))
    d=validate(rows,replace(original.policy,expected_intervals=tuple((b.open_time,b.close_time) for b in rows)))
    risk=replace(RiskConfig(),max_risk_per_trade_pct=50,max_daily_loss_pct=2,
                 max_portfolio_drawdown_pct=90)
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=50),3:Decision("LONG",stop_distance_pct=50)}),cfg(risk=risk))
    assert r.decisions[3]["risk_rejection_reason"] is None
    assert r.orders[-1]["action"]=="LONG"
    assert r.orders[-1]["fill_timestamp"]==d.bars[4].open_time.isoformat()
    risk=replace(risk,max_daily_loss_pct=90,max_portfolio_drawdown_pct=10)
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=50),3:Decision("LONG",stop_distance_pct=50)}),cfg(risk=risk))
    assert r.decisions[3]["risk_rejection_reason"]=="max_drawdown"


def test_holding_period_at_next_open_counts_only_completed_held_bars():
    d=dataset([(100,100),(100,110),(110,110)])
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}),cfg())
    assert r.trades[0]["holding_bars"]==1
    assert r.trades[0]["holding_seconds"]==3600


def test_invalid_nonfinite_decision_is_rejected_and_can_be_audited(tmp_path):
    d=dataset([(100,100)]*2)
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=float("nan"))}),cfg())
    path=save_run(tmp_path,r,d,cfg(),{"name":"invalid-fixture"})
    records=[json.loads(line) for line in (path/"decisions.jsonl").read_text().splitlines()]
    assert records[0]["risk_rejection_reason"]=="missing_stop_distance"
    assert records[0]["decision"]["stop_distance_pct"]=="NONFINITE:nan"


def test_higher_timeframe_asset_mismatch_is_rejected():
    d=dataset([(100,100)]*2)
    higher=validate(d.bars,replace(d.policy,asset="OTHER"))
    with pytest.raises(ValueError,match="asset"):
        run(d,Scripted({}),cfg(),higher)


def test_quantity_and_cash_limits_include_commission():
    d=dataset([(100,100)]*2)
    c=cfg(risk=replace(RiskConfig(),max_risk_per_trade_pct=100),
          execution=ExecutionConfig(100,0,0,.01,1))
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=50)}),c)
    assert r.orders[0]["size"]==99
    assert r.equity_curve[-1]["cash"]==1
    assert r.equity_curve[-1]["exposure"]==9900


def test_short_costs_reconcile_and_direction_does_not_improve_execution():
    d=dataset([(100,100)]*3)
    c=cfg(execution=ExecutionConfig(5,2,10,.01,1))
    r=run(d,Scripted({0:Decision("SHORT",stop_distance_pct=5),1:Decision("CLOSE")}),c)
    assert r.orders[0]["fill_price"]<100
    assert r.orders[1]["fill_price"]>100
    assert r.trades[0]["net_pnl"]<0
    assert r.equity_curve[-1]["equity"]==pytest.approx(10000+r.trades[0]["net_pnl"])


@pytest.mark.parametrize("side,expected_exit",[("LONG",99.93),("SHORT",100.07)])
def test_entry_friction_crossed_stop_fills_at_open_not_unreachable_stop(side,expected_exit):
    c=cfg(risk=replace(RiskConfig(),max_risk_per_trade_pct=.1),
          execution=ExecutionConfig(5,2,10,.01,1))
    d=dataset([(100,100)]*2,[(99.99,100.01)]*2)
    r=run(d,Scripted({0:Decision(side,stop_distance_pct=.01)}),c)
    assert r.trades[0]["exit_price"]==expected_exit
    assert r.trades[0]["exit_reason"]=="stop_gap"
    assert -r.trades[0]["net_pnl"]<=10


def test_explicit_volatility_stop_mode_uses_causal_features_and_waits_for_warmup():
    c=strategy_config(stop_mode="realized_volatility",volatility_stop_multiple=2)
    prices=[100,101,100,102,101,103,102,104,103,105]*6
    d=dataset([(p,p) for p in prices])
    r=run(d,build_strategy("momentum",c,42),cfg(),
          feature_fn=lambda rows,h:snapshot(rows,h,FeatureConfig()))
    assert all(record["decision"]["action"]=="HOLD" for record in r.decisions[:24])
    first=next(record for record in r.decisions if record["decision"]["action"] in {"LONG","SHORT"})
    assert first["decision"]["stop_distance_pct"]==pytest.approx(
        first["feature_snapshot"]["realized_volatility"]*200)
