"""Offline CLI. Missing research choices fail explicitly rather than fabricate data."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
import sys
from .data import DataPolicy, load_csv, load_schedule, validate, canonical
from .types import RiskConfig, ExecutionConfig
from .engine import BacktestConfig, run
from .features import FeatureConfig, snapshot
from .baselines import StrategyConfig, build_strategy
from .benchmarks import run_benchmarks
from .storage import save_run, load_saved, source_fingerprint
from .metrics import calculate
from .reporting import single_report


def require(obj,key):
    v=obj.get(key)
    if v is None or v=="":
        raise ValueError(f"configure '{key}' explicitly")
    return v


def load_config(path):
    path=Path(path).resolve()
    raw=json.loads(path.read_text(encoding="utf-8"))
    data_cfg=require(raw,"data")
    def data_from(dc):
        policy=DataPolicy(require(dc,"source"),require(dc,"asset"),require(dc,"timeframe"),
                          require(dc,"corporate_actions"),require(dc,"volume_supported"),
                          load_schedule(path.parent/require(dc,"schedule_path")))
        if not isinstance(policy.volume_supported,bool):
            raise ValueError("volume_supported must be boolean")
        return validate(load_csv(path.parent/require(dc,"path")),policy)
    data=data_from(data_cfg)
    higher=data_from(raw["higher_data"]) if raw.get("higher_data") else None
    return raw,data,higher,path


def parse_backtest(raw):
    b=dict(require(raw,"backtest"))
    b["risk"]=RiskConfig(**require(b,"risk"))
    b["execution"]=ExecutionConfig(**require(b,"execution"))
    from .actions import restore_dividends
    if b.get('dividends'):
        b['dividends']=restore_dividends(b['dividends'])
    if b.get('trade_start'):
        b['trade_start']=datetime.fromisoformat(b['trade_start'])
    return BacktestConfig(**b)


def parse_features(raw):
    f=dict(require(raw,"features"))
    if f.get("enabled") is not None:
        f["enabled"]=tuple(f["enabled"])
    return FeatureConfig(**f)


def prepare_research(raw,data,higher,path):
    """Resolve immutable accounting input and exclude all out-of-window bars."""
    if not raw.get('research'):
        return raw,data,higher
    from hashlib import sha256
    from .research import select_window
    from .data import utc
    data,start=select_window(data,raw['research'])
    if higher is not None:
        raise ValueError('research higher timeframe requires explicit window handling')
    input_cfg=require(raw,'dividend_input')
    event_path=path.parent/require(input_cfg,'path')
    content=event_path.read_bytes()
    if sha256(content).hexdigest()!=require(input_cfg,'sha256'):
        raise ValueError('dividend input integrity failure')
    events=json.loads(content)
    if events.get('complete') is not True:
        raise ValueError('dividend payment-date coverage is incomplete')
    if events.get('asset')!=data.policy.asset:
        raise ValueError('dividend input asset mismatch')
    if (utc(datetime.fromisoformat(events['coverage_start']))>start or
            utc(datetime.fromisoformat(events['coverage_end']))<utc(datetime.fromisoformat(raw['research']['end']))):
        raise ValueError('dividend input does not cover the research window')
    from .actions import restore_dividends,validate_dividends
    event_rows=events['events']
    validate_dividends(restore_dividends(event_rows),data)
    provenance={'research_window':raw['research'],'configuration':raw,
                'dividend_source_input':events}
    raw={**raw,'backtest':{**raw['backtest'],'dividends':event_rows,'trade_start':start.isoformat()},
         '_research_provenance':provenance,'_dividend_input_bytes':content}
    return raw,data,None


def restore_policy(raw):
    raw=dict(raw)
    raw["expected_intervals"]=tuple(tuple(datetime.fromisoformat(t) for t in pair) for pair in raw["expected_intervals"])
    return DataPolicy(**raw)


def replay(path):
    path=Path(path)
    saved=load_saved(path)
    if source_fingerprint()!=saved["metadata"].get("source_fingerprint"):
        raise ValueError("source code differs from saved run; restore archived source.zip to replay")
    settings=saved["config"]
    data=validate(load_csv(path/"data.csv"),restore_policy(settings["data_policy"]))
    if data.fingerprint!=saved["metadata"]["dataset_fingerprint"]:
        raise ValueError("replay dataset fingerprint mismatch")
    higher=validate(load_csv(path/"higher_data.csv"),restore_policy(settings["higher_data_policy"])) if settings.get("higher_data_policy") else None
    c=parse_backtest(settings)
    s=settings["strategy"]
    f=parse_features({"features":s["feature_config"]})
    replay_provider=None
    if s['name'] in ('llm_only','stats_llm','stats_llm_journal'):
        from .llm_runs import replay_strategy
        strategy,replay_provider=replay_strategy(path,s,c.initial_cash)
    else:
        strategy=build_strategy(s['name'],StrategyConfig(**s['parameters']),c.seed)
    result=run(data,strategy,c,higher,
               lambda rows,h:snapshot(rows,h,f))
    if replay_provider: replay_provider.assert_exhausted()
    with (path/"decisions.jsonl").open(encoding="utf-8") as source:
        original=[json.loads(line) for line in source]
    start=next(b.open_time for b in data.bars if c.trade_start is None or b.open_time>=c.trade_start)
    metrics=calculate(result.equity_curve,result.trades,result.orders,c.initial_cash,c.periods_per_year,start)
    if canonical(result.decisions)!=canonical(original) or canonical(metrics)!=canonical(saved["metrics"]):
        raise ValueError("replay differs from saved decisions/metrics")
    if canonical(result.corporate_actions)!=canonical(json.loads((path/'corporate_actions.json').read_text(encoding='utf-8'))):
        raise ValueError('replay corporate actions differ')
    # Decisions include position/cost snapshots; trade equivalence is checked separately.
    import csv
    with (path/"trades.csv").open(newline="",encoding="utf-8") as source:
        original_trades=list(csv.DictReader(source))
    if len(original_trades)!=len(result.trades):
        raise ValueError("replay trade count differs")
    for old,new in zip(original_trades,result.trades):
        if any(old[k]!=("" if v is None else str(v)) for k,v in new.items()):
            raise ValueError("replay trades differ")
    return {"identical":True,"run_id":saved["metadata"]["run_id"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description="Historical-only deterministic research; no live execution.")
    subs=parser.add_subparsers(dest="command",required=True)
    for cmd in ("validate-data","backtest"):
        p=subs.add_parser(cmd)
        p.add_argument("--config",required=True)
        if cmd=="backtest":
            p.add_argument("--experiment",required=True,choices=["baselines","buy_hold","momentum","mean_reversion","statistical_regime","random","llm_only","stats_llm","stats_llm_journal"])
            p.add_argument('--allow-api',action='store_true',help='Explicitly permit the budget-controlled LLM pilot')
            p.add_argument('--pilot-decisions',type=int,help='Initial LLM pilot: 1-20 decisions per asset')
    p=subs.add_parser('llm-budget',help='Inspect the shared initial $10 API ledger')
    for cmd in ("replay","report"):
        p=subs.add_parser(cmd)
        p.add_argument("--run-path",required=True)
    p=subs.add_parser("download-yahoo",help="Download and validate historical ETF data only")
    p.add_argument("--assets",nargs="+",required=True,choices=["SPY","QQQ","GLD"])
    p.add_argument("--output-root",default="data/yahoo")
    p=subs.add_parser("prepare-yahoo",help="Revalidate captured Yahoo responses without downloading")
    p.add_argument("--batch-path",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='llm-budget':
            from decimal import Decimal
            from .llm_budget import BudgetLedger
            ledger=Path(__file__).resolve().parents[1]/'data/cache/llm-budget.sqlite'
            output=BudgetLedger(ledger,Decimal('10')).status() if ledger.exists() else {
                'cap_usd':'10','spent_and_reserved_usd':'0','remaining_usd':'10','blocked':False,'states':{}}
        elif args.command=="download-yahoo":
            from .yahoo import download_yahoo
            output={"download_path":str(download_yahoo(args.output_root,args.assets).resolve())}
        elif args.command=="prepare-yahoo":
            from .yahoo import prepare_captured_batch
            output={"prepared_path":str(prepare_captured_batch(args.batch_path).resolve())}
        elif args.command=="replay":
            output=replay(args.run_path)
        elif args.command=="report":
            output={"report_path":str(single_report(args.run_path).resolve())}
        else:
            raw,data,higher,path=load_config(args.config)
            if args.command=="validate-data":
                output={**data.report,"dataset_fingerprint":data.fingerprint}
            else:
                if args.experiment in ('llm_only','stats_llm','stats_llm_journal'):
                    from .llm_runs import run_llm_experiment
                    dest=run_llm_experiment(raw,data,higher,path,args.experiment,args.allow_api,args.pilot_decisions)
                    print(json.dumps({'run_path':str(dest.resolve()),'research_status':'pilot_only'},indent=2))
                    return 0
                raw,data,higher=prepare_research(raw,data,higher,path)
                c=parse_backtest(raw)
                f=parse_features(raw)
                s=StrategyConfig(**require(raw,"strategy"))
                if s.allow_short!=c.risk.allow_short:
                    raise ValueError('strategy and risk allow_short must agree')
                root=path.parent/require(raw,"output_root")
                if args.experiment=="baselines":
                    dest=run_benchmarks(data,c,s,f,root,require(raw,"random_agents"),higher,
                                       raw.get('_research_provenance'),raw.get('_dividend_input_bytes'))
                    output={"benchmark_path":str(dest.resolve())}
                else:
                    r=run(data,build_strategy(args.experiment,s,c.seed),c,higher,
                          lambda rows,h:snapshot(rows,h,f))
                    dest=save_run(root,r,data,c,{"name":args.experiment,"parameters":asdict(s),
                                               "feature_config":asdict(f)},higher_data=higher,
                                  research_provenance=raw.get('_research_provenance'),
                                  dividend_input_bytes=raw.get('_dividend_input_bytes'))
                    output={"run_path":str(dest.resolve())}
        print(json.dumps(output,indent=2,allow_nan=False))
        return 0
    except (ValueError,TypeError,KeyError,OSError,ImportError) as exc:
        print(json.dumps({"error":str(exc)}),file=sys.stderr)
        return 2
