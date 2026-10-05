"""Identical feature/risk/execution benchmarking with 100+ seeded random agents."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import uuid
from pathlib import Path
from statistics import mean, median
from .baselines import build_strategy
from .features import snapshot, FEATURE_CATALOGUE
from .engine import run
from .storage import save_run, write_json, load_saved, write_csv
from .reporting import benchmark_report


def run_benchmarks(data,config,strategy_config,feature_config,output_root,random_agents=100,higher_data=None,
                   research_provenance=None,dividend_input_bytes=None):
    if strategy_config.allow_short!=config.risk.allow_short:
        raise ValueError('strategy and risk allow_short must agree')
    if type(random_agents) is not int or random_agents<100:
        raise ValueError("at least 100 seeded random agents required")
    batch=Path(output_root)/("benchmarks-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:12])
    batch.mkdir(parents=True,exist_ok=False)
    (batch/"INCOMPLETE").write_text("benchmark in progress",encoding="utf-8")
    # Cached causal snapshots are identical for every strategy, never fit on the future.
    cache={}
    def features(rows,higher):
        key=(len(rows),len(higher))
        if key not in cache:
            cache[key]=snapshot(rows,higher,feature_config)
        return cache[key]
    deterministic,randoms=[],[]
    def one(name,seed):
        c=replace(config,seed=seed)
        r=run(data,build_strategy(name,strategy_config,seed),c,higher_data,features)
        settings={"name":name,"parameters":asdict(strategy_config),"feature_config":asdict(feature_config)}
        dest=save_run(batch/"runs",r,data,c,settings,higher_data=higher_data,
                      research_provenance=research_provenance,dividend_input_bytes=dividend_input_bytes)
        return {"strategy":name,"seed":seed,"run_id":dest.name,"metrics":load_saved(dest)["metrics"]}
    for name in ("buy_hold","momentum","mean_reversion","statistical_regime"):
        deterministic.append(one(name,config.seed))
    for i in range(random_agents):
        randoms.append(one("random",config.seed+i))
    values=sorted(r["metrics"]["total_return"] for r in randoms)
    comparison={"deterministic":deterministic,"random_agents":randoms,
                "stats_only_run_id":deterministic[-1]["run_id"],"stats_plus_llm":"not_run",
                "random_distribution":{"minimum":min(values),"median":median(values),
                  "mean":mean(values),"maximum":max(values),"p05":values[int(.05*(len(values)-1))],
                  "p95":values[int(.95*(len(values)-1))]},
                "provenance":{"source":data.policy.source,"asset":data.policy.asset,
                  "dataset_fingerprint":data.fingerprint,"backtest":asdict(config),
                  "strategy_config":asdict(strategy_config),"feature_config":asdict(feature_config),
                  "higher_dataset_fingerprint":higher_data.fingerprint if higher_data else None,
                  "research_provenance":research_provenance},
                "research_status":"historical validation and LLM comparison pending"}
    write_json(batch/"comparison.json",comparison)
    write_json(batch/"feature_catalogue.json",FEATURE_CATALOGUE)
    write_csv(batch/"comparison.csv",[{"strategy":r["strategy"],"seed":r["seed"],"run_id":r["run_id"],**r["metrics"]} for r in deterministic+randoms])
    benchmark_report(comparison,batch/"report.html")
    (batch/"INCOMPLETE").unlink()
    return batch
