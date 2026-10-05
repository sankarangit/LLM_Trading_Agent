from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import json
import pytest
from llm_trading.metrics import calculate
from llm_trading.storage import save_run, load_saved
from test_engine import cfg, dataset, Scripted
from llm_trading.engine import run
from llm_trading.types import Decision


def test_hand_calculated_return_and_drawdown_include_initial_capital():
    t=datetime(2020,1,1,tzinfo=timezone.utc)
    curve=[{"timestamp":(t+timedelta(days=i+1)).isoformat(),"equity":eq,
            "transaction_costs":0,"exposure":0,"position_bar_fraction":0}
           for i,eq in enumerate([110,88,100])]
    m=calculate(curve,[],[],100,365)
    assert m["total_return"]==0
    assert m["max_drawdown"]==pytest.approx(0.2)
    assert m["number_of_trades"]==0
    assert m["win_rate"] is None
    assert m["profit_factor"] is None
    assert m["annualized_volatility"]>0
    assert m["gross_total_return"]==0


def test_flat_curve_has_null_risk_ratios_and_zero_return():
    d=dataset([(100,100)]*4)
    r=run(d,Scripted({}),cfg())
    m=calculate(r.equity_curve,r.trades,r.orders,10000,8760)
    assert m["total_return"]==0
    assert m["sharpe"] is None
    assert m["sortino"] is None
    assert m["calmar"] is None
    assert m["market_exposure"]==0
    json.dumps(m,allow_nan=False)


def test_trade_metrics_reconcile_and_turnover_uses_actual_notional():
    d=dataset([(100,100),(100,110),(110,110)])
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}),cfg())
    m=calculate(r.equity_curve,r.trades,r.orders,10000,8760)
    assert m["total_return"]==pytest.approx(0.01)
    assert m["win_rate"]==1
    assert m["average_win"]==100
    assert m["expectancy_per_trade"]==100
    assert m["turnover"]==pytest.approx(0.21)
    assert m["average_holding_bars"]==1


def test_run_artifacts_are_immutable_and_reproduce_results(tmp_path):
    d=dataset([(100,100),(100,110),(110,110)])
    c=cfg()
    s={"name":"scripted-test","actions":{"0":"LONG","1":"CLOSE"},"stop_distance_pct":5}
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=5),1:Decision("CLOSE")}),c)
    dest=save_run(tmp_path,r,d,c,s)
    assert (dest/"config.json").exists()
    assert (dest/"decisions.jsonl").exists()
    assert (dest/"orders.csv").exists()
    loaded=load_saved(dest)
    assert loaded["metadata"]["dataset_fingerprint"]==d.fingerprint
    assert loaded["metrics"]["total_return"]==pytest.approx(0.01)
    assert loaded["metadata"]["artifact_hashes"]["trades.csv"]
    assert loaded["metadata"]["source_fingerprint"]
    assert (dest/"source.zip").exists()
    import zipfile
    with zipfile.ZipFile(dest/"source.zip") as source:
        assert "llm_trading/engine.py" in source.namelist()
        assert "main.py" in source.namelist()
    assert json.loads((dest/"config.json").read_text())["backtest"]==json.loads(json.dumps(asdict(c)))
    with pytest.raises(FileExistsError):
        save_run(tmp_path,r,d,c,s,run_id=dest.name)
    (dest/"trades.csv").write_text("tampered")
    with pytest.raises(ValueError,match="integrity"):
        load_saved(dest)
