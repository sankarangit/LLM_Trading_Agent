from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest

from llm_trading.data import Bar, DataPolicy, validate
from llm_trading.engine import BacktestConfig, run
from llm_trading.types import Decision, RiskConfig, ExecutionConfig
from llm_trading.execution import costed_fill


def dataset(prices, ranges=None):
    """Explicit synthetic OHLC fixtures, never historical research data."""
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = tuple(Bar(t + timedelta(hours=i), t + timedelta(hours=i+1),
                     o, max(o,c)+1 if ranges is None else ranges[i][1],
                     min(o,c)-1 if ranges is None else ranges[i][0], c, 1000)
                 for i, (o,c) in enumerate(prices))
    p = DataPolicy("synthetic-test", "TEST", "1h", "not_applicable", True,
                   tuple((b.open_time,b.close_time) for b in rows))
    return validate(rows,p)


def cfg(**kwargs):
    base = BacktestConfig(initial_cash=10000, seed=42, periods_per_year=8760,
                          daily_timezone="UTC", risk=RiskConfig(),
                          execution=ExecutionConfig(0,0,0,0.01,1))
    return replace(base, **kwargs)


class Scripted:
    def __init__(self, decisions):
        self.decisions = decisions
        self.seen = []

    def decide(self, context):
        self.seen.append(context)
        return self.decisions.get(len(context.bars)-1, Decision("HOLD"))


@pytest.mark.parametrize("side,exit_price",[("LONG",110),("SHORT",90)])
def test_hand_calculated_long_short_pnl_and_next_open(side,exit_price):
    d = dataset([(100,100),(100,exit_price),(exit_price,exit_price)])
    agent = Scripted({0:Decision(side,stop_distance_pct=5),1:Decision("CLOSE")})
    result = run(d, agent, cfg())
    assert len(result.trades)==1
    trade=result.trades[0]
    assert trade["size"]==10
    assert trade["gross_pnl"]==pytest.approx(100)
    assert trade["net_pnl"]==pytest.approx(100)
    assert result.equity_curve[-1]["equity"]==pytest.approx(10100)
    assert trade["entry_timestamp"]==d.bars[1].open_time.isoformat()
    assert trade["signal_timestamp"]==d.bars[0].close_time.isoformat()
    assert trade["exit_timestamp"]==d.bars[2].open_time.isoformat()
    assert agent.seen[0].account.position_size==0
    assert len(agent.seen[0].bars)==1


def test_next_open_price_cannot_change_prior_decision_or_visible_account():
    a=dataset([(100,100),(100,100),(100,100)])
    b=dataset([(100,100),(900,900),(900,900)])
    agents=[Scripted({0:Decision("LONG",stop_distance_pct=5)}) for _ in range(2)]
    out=[run(d,s,cfg()) for d,s in zip((a,b),agents)]
    assert agents[0].seen[0]==agents[1].seen[0]
    # Fill-time revalidation may change size; finalized decision inputs may not.
    for field in ("decision", "risk_result", "account_snapshot", "feature_snapshot",
                  "decision_timestamp", "visible_data_end"):
        assert out[0].decisions[0][field]==out[1].decisions[0][field]
    assert out[1].orders[0]["size"] <= 11
    assert out[1].orders[0]["fill_price"]==900


def test_snapshot_is_immutable_and_does_not_expose_dataset():
    s=Scripted({})
    run(dataset([(100,100),(100,100)]),s,cfg())
    with pytest.raises((AttributeError,TypeError)):
        s.seen[0].account.equity=0
    assert not hasattr(s.seen[0],"dataset")


def test_adverse_costs_and_tick_rounding_are_on_each_side():
    c=ExecutionConfig(5,2,10,0.01,1)
    buy=costed_fill(100,10,1,c)
    sell=costed_fill(100,10,-1,c)
    assert buy.price==pytest.approx(100.07)
    assert sell.price==pytest.approx(99.93)
    assert buy.commission==pytest.approx(0.50035)
    assert sell.commission==pytest.approx(0.49965)
    assert buy.spread_cost==pytest.approx(0.5)
    assert buy.slippage_cost==pytest.approx(0.2)
    rounded=costed_fill(100.005,1,1,ExecutionConfig(0,0,0,0.01,1))
    assert rounded.price==100.01


def test_roundtrip_costs_reconcile_to_cash_and_gross():
    c=cfg(execution=ExecutionConfig(5,2,10,0.01,1))
    r=run(dataset([(100,100),(100,100),(100,100)]),
          Scripted({0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}),c)
    trade=r.trades[0]
    assert trade["gross_pnl"]==0
    total=trade["commission"]+trade["spread_cost"]+trade["slippage"]+trade["rounding_cost"]
    assert trade["net_pnl"]==pytest.approx(-total)
    assert r.equity_curve[-1]["equity"]==pytest.approx(10000-total)
    assert r.equity_curve[-1]["transaction_costs"]==pytest.approx(total)


@pytest.mark.parametrize("side,gap,expected",[("LONG",80,80),("SHORT",120,120)])
def test_gap_through_stop_fills_at_gap_open(side,gap,expected):
    r=run(dataset([(100,100),(100,100),(gap,gap)]),
          Scripted({0:Decision(side,stop_distance_pct=5)}),cfg())
    assert r.trades[0]["exit_price"]==expected
    assert r.trades[0]["exit_reason"]=="stop_gap"


@pytest.mark.parametrize("side,expected",[("LONG",95),("SHORT",105)])
def test_stop_first_when_both_stop_and_target_touch(side,expected):
    r=run(dataset([(100,100),(100,100)],[(99,101),(90,110)]),
          Scripted({0:Decision(side,stop_distance_pct=5,target_r_multiple=1)}),cfg())
    assert r.trades[0]["exit_price"]==expected
    assert r.trades[0]["exit_reason"]=="stop"
    assert r.trades[0]["intrabar_timestamp_is_bound"] is True


def test_unfilled_last_decision_and_open_position_are_not_force_filled():
    r=run(dataset([(100,100),(100,110)]),
          Scripted({0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}),cfg())
    assert r.trades==[]
    assert r.equity_curve[-1]["equity"]==10100
    assert r.equity_curve[-1]["unrealized_pnl"]==100
    assert r.decisions[-1]["order_status"]=="expired_end_of_data"
    assert len(r.orders)==1


@pytest.mark.parametrize("decision,reason",[
    (Decision("BUY",stop_distance_pct=5),"invalid_action"),
    (Decision("LONG"),"missing_stop_distance"),
    (Decision("LONG",stop_distance_pct=-1),"missing_stop_distance"),
    (Decision("SHORT",stop_distance_pct=5),"short_disabled"),
    (Decision("LONG",stop_distance_pct=float("nan")),"missing_stop_distance"),
])
def test_risk_rejections_are_logged(decision,reason):
    r=run(dataset([(100,100),(100,100)]),Scripted({0:decision}),
          cfg(risk=replace(RiskConfig(),allow_short=False)))
    assert r.decisions[0]["risk_rejection_reason"]==reason
    assert r.orders==[]


def test_risk_and_exposure_size_are_enforced_after_open_gap():
    risk=replace(RiskConfig(),max_risk_per_trade_pct=50,max_gross_exposure_pct=10)
    r=run(dataset([(100,100),(1000,1000)]),
          Scripted({0:Decision("LONG",stop_distance_pct=5)}),cfg(risk=risk))
    assert r.orders[0]["size"]==1
    assert r.equity_curve[-1]["exposure"]<=1000


def test_no_repeat_or_implicit_reversal_orders():
    s=Scripted({0:Decision("LONG",stop_distance_pct=50),
                1:Decision("LONG",stop_distance_pct=50),
                2:Decision("SHORT",stop_distance_pct=50)})
    r=run(dataset([(100,100)]*4),s,cfg())
    assert len(r.orders)==1
    assert r.decisions[1]["risk_rejection_reason"]=="position_already_open"
    assert r.decisions[2]["risk_rejection_reason"]=="position_already_open"


@pytest.mark.parametrize("limit,exit_reason",[("daily","daily_loss"),("drawdown","max_drawdown")])
def test_kill_switch_exits_at_next_open_without_same_close_fill(limit,exit_reason):
    risk=replace(RiskConfig(),max_risk_per_trade_pct=50,
                 max_daily_loss_pct=2 if limit=="daily" else 90,
                 max_portfolio_drawdown_pct=10 if limit=="drawdown" else 90)
    r=run(dataset([(100,100),(100,80),(70,70),(70,70)]),
          Scripted({0:Decision("LONG",stop_distance_pct=50),2:Decision("LONG",stop_distance_pct=50)}),
          cfg(risk=risk))
    assert r.trades[0]["exit_price"]==70
    assert r.trades[0]["exit_reason"]==exit_reason
    assert r.decisions[2]["risk_rejection_reason"]==exit_reason
    assert len(r.orders)==2


def test_time_stop_is_at_next_open_after_horizon_completes():
    r=run(dataset([(100,100),(100,102),(103,103)]),
          Scripted({0:Decision("LONG",stop_distance_pct=5,horizon_bars=1)}),cfg())
    assert r.trades[0]["exit_price"]==103
    assert r.trades[0]["exit_reason"]=="time_stop"


def test_identical_input_seed_and_strategy_reproduce_trades():
    d=dataset([(100,100),(100,110),(110,110)])
    actions={0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}
    a=run(d,Scripted(actions),cfg())
    b=run(d,Scripted(actions),cfg())
    assert a.trades==b.trades
    assert a.decisions==b.decisions
    assert a.equity_curve==b.equity_curve


@pytest.mark.parametrize("kwargs",[{"initial_cash":0},{"periods_per_year":0},
                                    {"execution":ExecutionConfig(-1,0,0,0.01,1)},
                                    {"risk":replace(RiskConfig(),max_positions=2)}])
def test_invalid_configuration_fails_before_strategy_runs(kwargs):
    with pytest.raises(ValueError):
        run(dataset([(100,100)]),Scripted({}),cfg(**kwargs))
