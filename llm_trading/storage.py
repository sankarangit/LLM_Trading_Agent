"""Create-once historical runs with config, input snapshots and artifact hashes."""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import csv
import json
import subprocess
import uuid
import zipfile
from .data import canonical
from .metrics import calculate


def write_json(path, value):
    Path(path).write_text(json.dumps(value,indent=2,sort_keys=True,
                                    default=lambda v:v.isoformat(),allow_nan=False),encoding="utf-8")


def write_csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k:canonical(v) if isinstance(v,(dict,list,tuple)) else v
                             for k,v in r.items()})


def git_commit():
    process=subprocess.run(["git","rev-parse","HEAD"],cwd=Path(__file__).parent,
                           capture_output=True,text=True,check=False)
    return process.stdout.strip() if process.returncode==0 else None


def source_files():
    root=Path(__file__).resolve().parents[1]
    paths=sorted((root/"llm_trading").glob("*.py"))+[root/"main.py",root/"pyproject.toml"]
    paths+=sorted((root/'prompts').glob('*.txt'))
    return {p.relative_to(root).as_posix():p.read_bytes() for p in paths}


def source_fingerprint(files=None):
    files=source_files() if files is None else files
    return sha256(canonical({k:sha256(v).hexdigest() for k,v in files.items()}).encode()).hexdigest()


def archive_inputs(dest,data,config,strategy_config,higher_data=None,
                   research_provenance=None,dividend_input_bytes=None):
    dest=Path(dest)
    snapshot={'backtest':asdict(config),'data_policy':asdict(data.policy),
        'strategy':strategy_config,'higher_data_policy':asdict(higher_data.policy) if higher_data else None,
        'research_provenance':research_provenance}
    sources=source_files()
    if (dest/'input_hashes.json').exists():
        hashes=json.loads((dest/'input_hashes.json').read_text(encoding='utf-8'))
        if any(not (dest/name).is_file() or sha256((dest/name).read_bytes()).hexdigest()!=digest for name,digest in hashes.items()):
            raise ValueError('prearchived input integrity failure')
        if canonical(json.loads((dest/'config.json').read_text(encoding='utf-8')))!=canonical(snapshot):
            raise ValueError('prearchived config differs')
        with zipfile.ZipFile(dest/'source.zip') as archive:
            if {name:archive.read(name) for name in archive.namelist()}!=sources:
                raise ValueError('source changed during LLM run')
        return snapshot,sources
    write_json(dest/'config.json',snapshot)
    if dividend_input_bytes is not None:
        with (dest/'dividend_input.json').open('xb') as out: out.write(dividend_input_bytes)
    with zipfile.ZipFile(dest/'source.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,content in sources.items(): archive.writestr(zipfile.ZipInfo(name),content)
    write_csv(dest/'data.csv',[asdict(b) for b in data.bars])
    if higher_data: write_csv(dest/'higher_data.csv',[asdict(b) for b in higher_data.bars])
    write_json(dest/'data_quality.json',data.report)
    write_json(dest/'input_hashes.json',{p.name:sha256(p.read_bytes()).hexdigest()
        for p in dest.iterdir() if p.is_file() and p.name!='INCOMPLETE'})
    return snapshot,sources


def save_run(root, result, data, config, strategy_config, run_id=None, higher_data=None,
             research_provenance=None, dividend_input_bytes=None, llm_artifacts=None,
             prepared_run_path=None):
    run_id=run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:12]
    if Path(run_id).name!=run_id or run_id in {".",".."}:
        raise ValueError("run_id must be a directory name")
    dest=Path(root)/run_id
    if prepared_run_path is None:
        dest.mkdir(parents=True,exist_ok=False)
        (dest/"INCOMPLETE").write_text("Do not consume until metadata is finalized.",encoding="utf-8")
    elif (dest.resolve()!=Path(prepared_run_path).resolve() or
          not (dest/'INCOMPLETE').exists() or (dest/'metadata.json').exists()):
        raise ValueError('invalid precreated incomplete run path')
    snapshot,sources=archive_inputs(dest,data,config,strategy_config,higher_data,
                                   research_provenance,dividend_input_bytes)
    with (dest/"decisions.jsonl").open("w",encoding="utf-8") as f:
        for row in result.decisions:
            f.write(canonical(row)+"\n")
    write_csv(dest/"orders.csv",result.orders,["order_id","decision_id","signal_timestamp",
              "fill_timestamp","action","size","fill_price","reason","costs"])
    write_csv(dest/"trades.csv",result.trades,["trade_id","signal_timestamp","entry_timestamp",
              "entry_price","entry_reference_price","side","size","stop","target",
              "exit_timestamp","exit_price","exit_reference_price","exit_reason","gross_pnl",
              "commission","spread_cost","slippage","rounding_cost","net_pnl","holding_bars","holding_seconds",
              "intrabar_timestamp_is_bound","dividend_pnl"])
    write_json(dest/"corporate_actions.json",result.corporate_actions)
    write_csv(dest/"equity_curve.csv",result.equity_curve)
    write_json(dest/"features.json",[{"timestamp":d["decision_timestamp"],
                                     **d["feature_snapshot"]} for d in result.decisions])
    metrics=calculate(result.equity_curve,result.trades,result.orders,config.initial_cash,
                      config.periods_per_year,next(b.open_time for b in data.bars
                                                   if config.trade_start is None or b.open_time>=config.trade_start))
    write_json(dest/"metrics.json",metrics)
    if llm_artifacts is not None:
        with (dest/'llm_audit.jsonl').open('x',encoding='utf-8') as f:
            for record in llm_artifacts['audit']: f.write(canonical(record)+'\n')
        if (dest/'prompt.txt').exists():
            if (dest/'prompt.txt').read_bytes()!=llm_artifacts['prompt'].encode('utf-8'):
                raise ValueError('prearchived prompt differs')
        else:
            with (dest/'prompt.txt').open('xb') as f: f.write(llm_artifacts['prompt'].encode('utf-8'))
    hashes={p.relative_to(dest).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in dest.rglob('*') if p.is_file() and p.name!='INCOMPLETE'}
    metadata={"run_id":run_id,"created_at":datetime.now(timezone.utc).isoformat(),
              "git_commit":git_commit(),"dataset_fingerprint":data.fingerprint,
              "higher_dataset_fingerprint":higher_data.fingerprint if higher_data else None,
              "asset":data.policy.asset,"timeframe":data.policy.timeframe,
              "period":[data.bars[0].open_time.isoformat(),data.bars[-1].close_time.isoformat()],
              "random_seed":config.seed,"prompt_hash":None,"model_id":None,
              "model_parameters":None,"config_hash":sha256(canonical(snapshot).encode()).hexdigest(),
              "artifact_hashes":hashes,"engine_version":"0.1.0", "mode":"historical_only"}
    metadata["source_fingerprint"]=source_fingerprint(sources)
    if llm_artifacts is not None:
        metadata.update(llm_artifacts['metadata'])
    write_json(dest/"metadata.json",metadata)
    (dest/"INCOMPLETE").unlink()
    return dest


def load_saved(path):
    path=Path(path)
    if (path/"INCOMPLETE").exists():
        raise ValueError("incomplete run")
    meta=json.loads((path/"metadata.json").read_text(encoding="utf-8"))
    for name, digest in meta["artifact_hashes"].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or (path/relative).resolve().is_relative_to(path.resolve()) is False:
            raise ValueError("invalid artifact path")
        artifact=path/name
        if not artifact.exists() or sha256(artifact.read_bytes()).hexdigest()!=digest:
            raise ValueError(f"artifact integrity failure: {name}")
    return {"metadata":meta,"config":json.loads((path/"config.json").read_text(encoding="utf-8")),
            "metrics":json.loads((path/"metrics.json").read_text(encoding="utf-8"))}
