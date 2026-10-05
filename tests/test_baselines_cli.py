from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path
import pytest
from llm_trading.baselines import StrategyConfig, build_strategy
from llm_trading.benchmarks import run_benchmarks
from llm_trading.engine import run
from llm_trading.features import FeatureConfig, snapshot
from llm_trading.storage import load_saved, write_csv
from test_engine import dataset, cfg


def strategy_config(**kwargs):
    return StrategyConfig(stop_distance_pct=5,momentum_threshold=.002,
                          reversion_entry_z=1.0,reversion_exit_z=.25,**kwargs)


def test_all_required_baselines_run_through_same_accounting_and_snapshots():
    d=dataset([(100+i,100+i) for i in range(70)])
    results={}
    for name in ("buy_hold","random","momentum","mean_reversion","statistical_regime"):
        s=build_strategy(name,strategy_config(),42)
        r=run(d,s,cfg(),feature_fn=lambda rows,h:snapshot(rows,h,FeatureConfig()))
        assert len(r.decisions)==70
        assert all(o["fill_timestamp"]>=o["signal_timestamp"] for o in r.orders if o["signal_timestamp"])
        results[name]=r
    features=[r.decisions[-1]["feature_snapshot"] for r in results.values()]
    assert all(f==features[0] for f in features)
    assert results["momentum"].orders[0]["action"]=="LONG"
    # First decision closes at 100, next open is 101: 50/5.05 floors to 9.
    assert results["buy_hold"].orders[0]["size"]==9
    assert results["mean_reversion"].orders[0]["action"]=="SHORT"
    assert results["statistical_regime"].orders[0]["action"]=="LONG"


def test_seeded_random_reproducibility_and_seed_sensitivity():
    d=dataset([(100+i*.1,100+i*.1) for i in range(70)])
    a=run(d,build_strategy("random",strategy_config(),42),cfg())
    b=run(d,build_strategy("random",strategy_config(),42),cfg())
    c=run(d,build_strategy("random",strategy_config(),43),replace(cfg(),seed=43))
    assert a.decisions==b.decisions
    assert a.trades==b.trades
    assert a.decisions!=c.decisions


def test_hundred_random_agents_and_benchmark_report_are_auditable(tmp_path):
    d=dataset([(100+i*.1,100+i*.1) for i in range(55)])
    batch=run_benchmarks(d,cfg(),strategy_config(),FeatureConfig(),tmp_path,100)
    comparison=json.loads((batch/"comparison.json").read_text())
    assert len(comparison["random_agents"])==100
    assert len({a["seed"] for a in comparison["random_agents"]})==100
    assert len(comparison["deterministic"])==4
    assert comparison["stats_only_run_id"] in [r["run_id"] for r in comparison["deterministic"]]
    assert comparison["stats_plus_llm"]=="not_run"
    assert "LLM" in (batch/"report.html").read_text()
    for row in comparison["random_agents"]+comparison["deterministic"]:
        saved=load_saved(batch/"runs"/row["run_id"])
        assert saved["metadata"]["dataset_fingerprint"]==d.fingerprint
        assert saved["config"]["backtest"]["execution"]==json.loads(
            (batch/"runs"/comparison["stats_only_run_id"]/"config.json").read_text())["backtest"]["execution"]


def test_less_than_hundred_random_agents_is_rejected(tmp_path):
    with pytest.raises(ValueError,match="100"):
        run_benchmarks(dataset([(100,100)]*3),cfg(),strategy_config(),FeatureConfig(),tmp_path,99)


def cli_config(tmp_path):
    d=dataset([(100+i*.1,100+i*.1) for i in range(55)])
    from dataclasses import asdict
    write_csv(tmp_path/"data.csv",[asdict(b) for b in d.bars])
    write_csv(tmp_path/"schedule.csv",[{"open_time":b.open_time,"close_time":b.close_time} for b in d.bars])
    content={"data":{"path":"data.csv","schedule_path":"schedule.csv","source":"synthetic-test",
                     "asset":"TEST","timeframe":"1h","corporate_actions":"not_applicable","volume_supported":True},
             "backtest":asdict(cfg()),"features":asdict(FeatureConfig()),
             "strategy":asdict(strategy_config()),"random_agents":100,"output_root":"output"}
    p=tmp_path/"config.json"
    p.write_text(json.dumps(content))
    return p


def test_cli_validation_backtest_replay_and_safe_report(tmp_path):
    p=cli_config(tmp_path)
    cwd=Path(__file__).parents[1]
    def call(*args):
        return subprocess.run([sys.executable,str(cwd/"main.py"),*args],capture_output=True,text=True,cwd=cwd)
    v=call("validate-data","--config",str(p))
    assert v.returncode==0,v.stderr
    assert json.loads(v.stdout)["bar_count"]==55
    b=call("backtest","--config",str(p),"--experiment","momentum")
    assert b.returncode==0,b.stderr
    saved=Path(json.loads(b.stdout)["run_path"])
    r=call("replay","--run-path",str(saved))
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)["identical"] is True
    report=call("report","--run-path",str(saved))
    assert report.returncode==0,report.stderr
    assert (saved/"report.html").exists()
    assert load_saved(saved)
    assert call("walk-forward","--config",str(p)).returncode!=0
    assert call("backtest","--config",str(p),"--experiment","stats_plus_llm_v1").returncode!=0


def test_cli_requires_real_configuration_instead_of_fabricating_inputs(tmp_path):
    p=tmp_path/"unconfigured.json"
    p.write_text('{"data":{"path":null}}')
    cwd=Path(__file__).parents[1]
    r=subprocess.run([sys.executable,str(cwd/"main.py"),"validate-data","--config",str(p)],
                      capture_output=True,text=True)
    assert r.returncode!=0
    assert "error" in r.stderr.lower()


def test_replay_refuses_source_changes_even_when_run_data_is_intact(tmp_path,monkeypatch):
    from llm_trading.cli import replay
    from llm_trading.storage import save_run
    from dataclasses import asdict
    d=dataset([(100,100)]*3)
    s=strategy_config()
    f=FeatureConfig()
    r=run(d,build_strategy("momentum",s,42),cfg(),
          feature_fn=lambda rows,h:snapshot(rows,h,f))
    saved=save_run(tmp_path,r,d,cfg(),{"name":"momentum","parameters":asdict(s),"feature_config":asdict(f)})
    monkeypatch.setattr("llm_trading.cli.source_fingerprint",lambda:"changed-code")
    with pytest.raises(ValueError,match="source code differs"):
        replay(saved)
