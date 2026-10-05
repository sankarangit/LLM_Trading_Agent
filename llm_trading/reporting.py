"""Self-contained engineering benchmark reports; research conclusions deferred."""
import csv
import html
import json
from pathlib import Path
from .storage import load_saved


def formatted(value):
    if value is None:
        return "undefined"
    return f"{value:.6g}" if isinstance(value,(float,int)) else html.escape(str(value))


def table(rows, fields):
    return "<table><thead><tr>"+"".join("<th>"+html.escape(f)+"</th>" for f in fields)+"</tr></thead><tbody>"+"".join(
        "<tr>"+"".join("<td>"+formatted(r.get(f))+"</td>" for f in fields)+"</tr>" for r in rows)+"</tbody></table>"


def line_svg(values,label):
    if not values:
        return ""
    lo,hi=min(values),max(values)
    points=" ".join(f"{30+i*740/max(1,len(values)-1):.2f},{220-(v-lo)*190/max(1e-12,hi-lo):.2f}" for i,v in enumerate(values))
    return f'<svg role="img" aria-label="{html.escape(label,quote=True)}" viewBox="0 0 800 250"><rect width="800" height="250" fill="#f5f7fa"/><polyline points="{points}" fill="none" stroke="#197b8d" stroke-width="2"/><text x="30" y="245">{html.escape(label)}: {lo:.6g} to {hi:.6g}</text></svg>'


def page(title,body):
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>'+html.escape(title)+'</title><style>body{font:15px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#192b40}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{border:1px solid #ced6df;padding:8px;text-align:left}th{background:#edf3f7}pre{overflow:auto;background:#f5f7fa;padding:16px}svg{width:100%;max-height:300px}.notice{border-left:4px solid #bc7400;padding:12px;background:#fff8e9}</style><body><h1>'+html.escape(title)+'</h1>'+body+'</body></html>')


def single_report(run_path,output_path=None):
    run_path=Path(run_path)
    saved=load_saved(run_path)
    with (run_path/"equity_curve.csv").open(newline="",encoding="utf-8") as f:
        curve=list(csv.DictReader(f))
    equity=[saved["config"]["backtest"]["initial_cash"]]+[float(r["equity"]) for r in curve]
    peak=equity[0]
    dd=[]
    for v in equity:
        peak=max(peak,v)
        dd.append(1-v/peak)
    body='<p class="notice">Engineering output. No LLM evaluation, walk-forward validation or untouched holdout has been performed. Synthetic fixtures are not evidence of trading value.</p>'
    if saved['metadata'].get('llm_summary'):
        body='<p class="notice">LLM pilot_only: limited development decisions. Full paired comparison, walk-forward and untouched holdout remain pending. No alpha conclusion is supported.</p>'
        body+='<h2>LLM usage and spending</h2><pre>'+html.escape(json.dumps(saved['metadata']['llm_summary'],indent=2))+'</pre>'
    body+='<h2>Configuration and provenance</h2><pre>'+html.escape(json.dumps(saved,indent=2))+'</pre>'
    body+='<h2>Data quality</h2><pre>'+html.escape((run_path/"data_quality.json").read_text(encoding="utf-8"))+'</pre>'
    body+='<h2>Equity</h2>'+line_svg(equity,"close-sampled equity")
    body+='<h2>Drawdown</h2>'+line_svg(dd,"close-sampled drawdown")
    body+='<h2>Metrics</h2>'+table([{"metric":k,"value":v} for k,v in saved["metrics"].items()],["metric","value"])
    body+='<h2>Stats-only vs Stats+LLM</h2><p>Pending Phase 4-7 and approved historical data, model configuration and holdout. No alpha conclusion is supported.</p>'
    dest=Path(output_path) if output_path else run_path/"report.html"
    with dest.open("x",encoding="utf-8") as f:
        f.write(page("Historical deterministic run",body))
    return dest


def benchmark_report(comparison,path):
    fields=["strategy","total_return","sharpe","sortino","max_drawdown","calmar",
            "profit_factor","turnover","number_of_trades","total_transaction_cost"]
    rows=[{"strategy":r["strategy"],**r["metrics"]} for r in comparison["deterministic"]]
    body='<p class="notice">Deterministic benchmark gate. LLM evaluation and research acceptance gates remain pending. This report does not establish alpha.</p>'
    body+='<h2>Identical engine and costs</h2>'+table(rows,fields)
    body+='<h2>Random agent distribution</h2><p>'+str(len(comparison["random_agents"]))+' explicit, independent seeds.</p>'
    body+=table([comparison["random_distribution"]],list(comparison["random_distribution"]))
    body+=line_svg(sorted(r["metrics"]["total_return"] for r in comparison["random_agents"]),"sorted seeded random net returns (empirical distribution)")
    body+='<h2>Stats-only vs Stats+LLM</h2><p>Stats-only: statistical_regime. Stats+LLM: NOT RUN. Historical benchmark validation must precede model evaluation.</p>'
    body+='<h2>Source</h2><pre>'+html.escape(json.dumps(comparison["provenance"],indent=2,
                                               default=lambda value:value.isoformat(),allow_nan=False))+'</pre>'
    with Path(path).open("x",encoding="utf-8") as f:
        f.write(page("Deterministic benchmark comparison",body))
