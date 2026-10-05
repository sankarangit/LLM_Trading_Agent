"""Yahoo historical adapter: preserve chart bytes, map independent session times.

Raw source OHLC is exported without dividend back-adjustment or data repair.
Calendar normalization never fills gaps or guesses a daily candle's availability.
"""
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from .data import Bar,DataPolicy,DataQualityError,utc,validate
from .storage import write_csv,write_json


CORPORATE_POLICY=("Yahoo chart source OHLC; auto_adjust=False, back_adjust=False, "
                  "repair=False; Adj Close unused; source-native split conventions "
                  "retained; dividends/splits saved in raw chart. No dividend cash "
                  "or share-count adjustments applied. Research treatment requires decision.")


@dataclass(frozen=True)
class Session:
    open_time: datetime
    close_time: datetime


@dataclass(frozen=True)
class Chart:
    raw: bytes
    meta: dict
    timestamps: tuple[datetime,...]
    quotes: tuple[dict,...]
    events: dict


@dataclass(frozen=True)
class Normalized:
    bars: tuple[Bar,...]
    expected: tuple[tuple[datetime,datetime],...]
    exclusions: tuple[dict,...]


def epoch_datetime(seconds):
    # Windows C runtime fromtimestamp rejects negative epochs used by period=max.
    return datetime(1970,1,1,tzinfo=timezone.utc)+timedelta(seconds=seconds)


def calendar_for(meta):
    name={"PCX":"XNYS","NMS":"XNAS","NGM":"XNAS","NCM":"XNAS"}.get(meta.get("exchangeName"))
    if name is None or meta.get("exchangeTimezoneName")!="America/New_York":
        raise ValueError(f"unrecognized ETF exchange/timezone: {meta.get('exchangeName')}")
    return name


def parse_chart(raw: bytes,asset: str,interval: str) -> Chart:
    payload=json.loads(raw)
    chart=payload.get("chart",{})
    if chart.get("error") or not chart.get("result") or len(chart["result"])!=1:
        raise ValueError(f"Yahoo chart error/empty result: {chart.get('error')}")
    result=chart["result"][0]
    meta=result.get("meta",{})
    if meta.get("symbol")!=asset:
        raise ValueError("Yahoo asset mismatch")
    allowed={"1h","60m"} if interval=="1h" else {interval}
    if meta.get("dataGranularity") not in allowed:
        raise ValueError("Yahoo interval mismatch")
    ZoneInfo(meta["exchangeTimezoneName"])
    timestamps=result.get("timestamp",[])
    if not timestamps:
        raise ValueError("Yahoo chart has no bars")
    quote=result.get("indicators",{}).get("quote",[])
    if len(quote)!=1:
        raise ValueError("expected exactly one Yahoo OHLCV block")
    fields=("open","high","low","close","volume")
    if any(len(quote[0].get(k,[]))!=len(timestamps) for k in fields):
        raise ValueError("Yahoo OHLCV/timestamp length mismatch")
    times=tuple(epoch_datetime(t) for t in timestamps)
    rows=tuple({k:quote[0][k][i] for k in fields} for i in range(len(times)))
    return Chart(raw,meta,times,rows,result.get("events",{}))


def schedule_intervals(sessions,interval,start,end):
    start,end=utc(start),utc(end)
    if interval not in {"1h","1d"}:
        raise ValueError("Yahoo adapter currently supports 1h and 1d")
    result=[]
    previous=None
    for s in sessions:
        a,z=utc(s.open_time),utc(s.close_time)
        if a>=z or (previous and a<previous):
            raise ValueError("invalid/overlapping calendar sessions")
        previous=z
        cursor=a
        while cursor<z:
            close=z if interval=="1d" else min(cursor+timedelta(hours=1),z)
            if cursor>=start and close<=end:
                result.append((cursor,close))
            cursor=close
    return tuple(result)


def normalize(chart,interval,sessions,requested_start,requested_end,observed_at):
    cutoff=min(utc(requested_end),utc(observed_at))
    start=utc(requested_start)
    zone=ZoneInfo(chart.meta["exchangeTimezoneName"])
    by_date={s.open_time.astimezone(zone).date():s for s in sessions}
    rows,excluded=[],[]
    for stamp,quote in zip(chart.timestamps,chart.quotes):
        day=stamp.astimezone(zone).date()
        s=by_date.get(day)
        if s is None:
            raise ValueError(f"Yahoo bar {stamp.isoformat()} outside supplied calendar session")
        if interval=="1d":
            a,z=utc(s.open_time),utc(s.close_time)
        elif interval=="1h":
            a=stamp
            if a==s.close_time and quote["volume"]==0 and quote["open"] is not None and len(
                    {quote[k] for k in ("open","high","low","close")})==1:
                excluded.append({"source_timestamp":stamp.isoformat(),"reason":"zero_duration_closing_quote"})
                continue
            if not s.open_time<=a<s.close_time:
                excluded.append({"source_timestamp":stamp.isoformat(),"reason":"outside_regular_session"})
                continue
            if (a-s.open_time).total_seconds()%3600!=0:
                raise ValueError(f"Yahoo bar {stamp.isoformat()} outside calendar session hourly grid")
            z=min(a+timedelta(hours=1),s.close_time)
        else:
            raise ValueError("unsupported interval")
        if z>cutoff:
            excluded.append({"source_timestamp":stamp.isoformat(),"reason":"incomplete_bar"})
            continue
        if a<start:
            excluded.append({"source_timestamp":stamp.isoformat(),"reason":"before_requested_window"})
            continue
        rows.append(Bar(a,z,*(quote[k] for k in ("open","high","low","close","volume"))))
    return Normalized(tuple(rows),schedule_intervals(sessions,interval,start,cutoff),tuple(excluded))


def calendar_sessions(name,start,end):
    """Source-independent exchange rules, including holidays, DST and early closes."""
    import exchange_calendars as xc
    calendar=xc.get_calendar(name,start=start,end=end)
    return tuple(Session(row["open"].to_pydatetime(),row["close"].to_pydatetime())
                 for _,row in calendar.schedule.loc[str(start):str(end)].iterrows())


def export_asset(root,asset,hourly,daily,sessions,requested_start,requested_end,
                 observed_at,calendar_name,daily_start=None):
    if asset not in {"SPY","QQQ","GLD"}:
        raise ValueError("approved download universe is SPY, QQQ, GLD")
    if any(c.meta["symbol"]!=asset for c in (hourly,daily)):
        raise ValueError("asset mismatch in source charts")
    dest=Path(root)/asset
    dest.mkdir(parents=True,exist_ok=False)
    (dest/"INCOMPLETE").write_text("source conversion/validation in progress",encoding="utf-8")
    (dest/"hourly_raw.json").write_bytes(hourly.raw)
    (dest/"daily_raw.json").write_bytes(daily.raw)
    day_start=utc(daily_start or requested_start)
    normalized={"hourly":normalize(hourly,"1h",sessions,requested_start,requested_end,observed_at),
                "daily":normalize(daily,"1d",sessions,day_start,requested_end,observed_at)}
    reports,fingerprints={},{}
    for name,n in normalized.items():
        write_csv(dest/f"{name}.csv",[asdict(b) for b in n.bars],
                  ["open_time","close_time","open","high","low","close","volume"])
        write_csv(dest/f"{name}_schedule.csv",[{"open_time":a,"close_time":z} for a,z in n.expected],
                  ["open_time","close_time"])
        policy=DataPolicy("Yahoo Finance chart via yfinance",asset,"1h" if name=="hourly" else "1d",
                          CORPORATE_POLICY,True,n.expected)
        try:
            data=validate(n.bars,policy)
            reports[name]=data.report
            fingerprints[name]=data.fingerprint
        except DataQualityError as exc:
            reports[name]=exc.report
            fingerprints[name]=None
        reports[name]["excluded_source_records"]=list(n.exclusions)
        reports[name]["completed_bar_cutoff"]=utc(observed_at).isoformat()
    write_json(dest/"quality.json",reports)
    valid=all(not r["errors"] for r in reports.values())
    template=json.loads((Path(__file__).resolve().parents[1]/"config/base.json").read_text(encoding="utf-8"))
    def config_data(name,timeframe):
        return {"path":f"{name}.csv","schedule_path":f"{name}_schedule.csv",
                "source":"Yahoo Finance chart via yfinance","asset":asset,"timeframe":timeframe,
                "corporate_actions":CORPORATE_POLICY,"volume_supported":True}
    template["data"]=config_data("hourly","1h")
    template["higher_data"]=config_data("daily","1d")
    template["backtest"]["daily_timezone"]=hourly.meta["exchangeTimezoneName"]
    template["output_root"]=str(Path(__file__).resolve().parents[1]/"runs")
    write_json(dest/"research.json",template)
    manifest={"asset":asset,"provider":"Yahoo Finance","calendar":calendar_name,
              "session_policy":"regular session only, no extended-hours bars",
              "requested_hourly_start":utc(requested_start),"requested_daily_start":day_start,
              "requested_end":utc(requested_end),"download_observed_at":utc(observed_at),
              "corporate_actions":CORPORATE_POLICY,"price_adjustment_research_gate":"pending decision",
              "dataset_fingerprints":fingerprints,"validation_status":"valid" if valid else "invalid",
              "raw_hashes":{name:sha256((dest/name).read_bytes()).hexdigest() for name in
                            ("hourly_raw.json","daily_raw.json")},
              "artifact_hashes":{p.name:sha256(p.read_bytes()).hexdigest() for p in dest.iterdir()
                                 if p.name!="INCOMPLETE"},
              "hourly_meta":hourly.meta,"daily_meta":daily.meta,
              "configuration_gate":"capital, costs, sizing/thresholds, adjustments and test split unresolved"}
    write_json(dest/"manifest.json",manifest)
    (dest/"INCOMPLETE").unlink()
    if not valid:
        raise DataQualityError({"asset":asset,"reports":reports,"artifact_path":str(dest)})
    return dest


def capture_session(folder):
    """Capture chart response bytes before yfinance transforms rows or adjustments.

    Cookies/crumbs and unrelated endpoint responses are never recorded.
    """
    from curl_cffi import requests
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    class CaptureSession(requests.Session):
        def __init__(self):
            super().__init__(impersonate="chrome")
            self.records=[]

        def get(self,url,**kwargs):
            response=super().get(url,**kwargs)
            if "/v8/finance/chart/" in str(url):
                number=len(self.records)+1
                filename=f"chart-{number:03d}.json"
                (folder/filename).write_bytes(response.content)
                params=kwargs.get("params") or {}
                allowed={k:params[k] for k in ("interval","range","period1","period2",
                         "includePrePost","events") if k in params}
                self.records.append({"file":filename,"url":str(url).split("?")[0],
                                     "params":allowed,"status":response.status_code,
                                     "sha256":sha256(response.content).hexdigest()})
            return response
    return CaptureSession()


def prepare_pair(root,asset,hourly,h_request,daily,d_request,observed_at):
    calendar_name=calendar_for(hourly.meta)
    if calendar_for(daily.meta)!=calendar_name:
        raise ValueError("hourly/daily exchange mismatch")
    start=epoch_datetime(h_request["params"]["period1"])
    end=epoch_datetime(h_request["params"]["period2"])
    d_start=max(epoch_datetime(d_request["params"]["period1"]),
                epoch_datetime(daily.meta["firstTradeDate"]))
    zone=ZoneInfo("America/New_York")
    ss=calendar_sessions(calendar_name,d_start.astimezone(zone).date(),observed_at.astimezone(zone).date())
    return export_asset(root,asset,hourly,daily,ss,start,end,observed_at,calendar_name,d_start)


def prepare_captured_batch(batch_path):
    """Offline recovery/revalidation; never overwrite or re-download source responses."""
    from uuid import uuid4
    batch=Path(batch_path).resolve()
    summary=json.loads((batch/"download_manifest.json").read_text(encoding="utf-8"))
    records=json.loads((batch/"response_manifest.json").read_text(encoding="utf-8"))
    observed_at=datetime.fromisoformat(summary["created_at"])
    assets=summary.get("requested_assets") or list(dict.fromkeys([*summary["assets"],*summary["errors"]]))
    root=batch/("prepared-"+uuid4().hex[:8])
    root.mkdir(exist_ok=False)
    results,errors={},{}
    for asset in assets:
        try:
            charts,requests={},{}
            for interval in ("1h","1d"):
                matches=[r for r in records if r["status"]==200 and r["url"].endswith("/"+asset)
                         and r["params"].get("interval")==interval and "period1" in r["params"]]
                if not matches:
                    raise ValueError(f"missing captured {asset}/{interval} maximum history")
                record=matches[-1]
                if Path(record["file"]).name!=record["file"]:
                    raise ValueError("invalid captured response path")
                raw=(batch/"responses"/record["file"]).read_bytes()
                if sha256(raw).hexdigest()!=record["sha256"]:
                    raise ValueError("raw response integrity mismatch")
                charts[interval]=parse_chart(raw,asset,interval)
                requests[interval]=record
            dest=prepare_pair(root,asset,charts["1h"],requests["1h"],charts["1d"],requests["1d"],observed_at)
            results[asset]={"path":str(dest),"config":str(dest/"research.json")}
            print(json.dumps({"asset":asset,"status":"prepared_and_validated","path":str(dest)}),flush=True)
        except Exception as exc:
            errors[asset]=str(exc)
            print(json.dumps({"asset":asset,"status":"failed","error":str(exc)}),flush=True)
    write_json(root/"preparation_manifest.json",{"source_batch":str(batch),"assets":results,
               "errors":errors,"prepared_at":datetime.now(timezone.utc),"source_observed_at":observed_at})
    if errors:
        raise ValueError(f"source validation failed for {list(errors)}; see {root/'preparation_manifest.json'}")
    return root


def download_yahoo(output_root,assets=("SPY","QQQ","GLD")):
    """Download only; no strategy evaluation, holdout scoring or broker connection."""
    import yfinance as yf
    import exchange_calendars as xc
    from uuid import uuid4
    if not assets or len(set(assets))!=len(assets) or not set(assets)<={"SPY","QQQ","GLD"}:
        raise ValueError("unique approved assets SPY, QQQ, GLD required")
    now=datetime.now(timezone.utc)
    batch=Path(output_root)/(now.strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:8])
    batch.mkdir(parents=True,exist_ok=False)
    # All library caches are project-local, isolated per download batch.
    yf.set_tz_cache_location(str(batch/"provider-cache"))
    session=capture_session(batch/"responses")
    results,errors={},{}
    def history(asset,interval):
        before=len(session.records)
        ticker=yf.Ticker(asset,session=session)
        ticker.history(period="max",interval=interval,auto_adjust=False,back_adjust=False,
                       repair=False,keepna=True,actions=True,prepost=False,rounding=False,
                       timeout=20,raise_errors=True)
        candidates=[r for r in session.records[before:] if r["status"]==200 and
                    r["url"].endswith("/"+asset) and r["params"].get("interval")==interval]
        for record in reversed(candidates):
            try:
                chart=parse_chart((batch/"responses"/record["file"]).read_bytes(),asset,interval)
                return chart,record
            except ValueError:
                continue
        raise ValueError(f"no captured raw {asset}/{interval} source response")
    for asset in assets:
        try:
            hourly,h_request=history(asset,"1h")
            daily,d_request=history(asset,"1d")
            dest=prepare_pair(batch,asset,hourly,h_request,daily,d_request,now)
            results[asset]={"path":str(dest.resolve()),"config":str((dest/"research.json").resolve())}
            print(json.dumps({"asset":asset,"status":"downloaded_and_validated","path":str(dest)}),flush=True)
        except Exception as exc:
            errors[asset]=str(exc)
            print(json.dumps({"asset":asset,"status":"failed","error":str(exc)}),flush=True)
    session.close()
    write_json(batch/"response_manifest.json",session.records)
    summary={"batch_path":str(batch.resolve()),"created_at":now,"assets":results,"errors":errors,
             "requested_assets":list(assets),
             "package_versions":{"yfinance":yf.__version__,"exchange_calendars":xc.__version__,
                                  "tzdata":importlib.metadata.version("tzdata")},
             "benchmark_status":"not_run; requires user research assumptions",
             "final_holdout_status":"not_selected_or_scored"}
    write_json(batch/"download_manifest.json",summary)
    if errors:
        raise ValueError(f"Yahoo download failed validation for {list(errors)}; see {batch/'download_manifest.json'}")
    return batch
