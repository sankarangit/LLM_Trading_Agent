from datetime import datetime,timedelta,timezone
from dataclasses import replace
import json
import pytest
from llm_trading.yahoo import Session, parse_chart, normalize, schedule_intervals, export_asset
from llm_trading.data import DataQualityError,completed,load_csv,load_schedule,validate,DataPolicy


def dt(text):
    return datetime.fromisoformat(text)


def sessions():
    return (Session(dt("2024-11-27T14:30:00+00:00"),dt("2024-11-27T21:00:00+00:00")),
            Session(dt("2024-11-29T14:30:00+00:00"),dt("2024-11-29T18:00:00+00:00")))


def chart(times,interval="1h",values=None,asset="SPY"):
    if values is None:
        values=[{"open":100,"high":101,"low":99,"close":100,"volume":1000} for _ in times]
    body={"chart":{"error":None,"result":[{"meta":{"symbol":asset,"exchangeName":"PCX",
          "exchangeTimezoneName":"America/New_York","dataGranularity":interval,
          "firstTradeDate":int(dt("2024-11-27T14:30:00+00:00").timestamp())},
          "timestamp":[int(t.timestamp()) for t in times],
          "indicators":{"quote":[{key:[row[key] for row in values] for key in values[0]}]},
          "events":{"dividends":{"123":{"amount":1,"date":123}}}}]}}
    return parse_chart(json.dumps(body).encode(),asset,interval)


def test_independent_schedule_has_early_close_and_no_holiday_bars():
    ss=sessions()
    interval=schedule_intervals(ss,"1h",ss[0].open_time,ss[-1].close_time)
    assert len(interval)==11
    assert interval[6]==(dt("2024-11-27T20:30:00+00:00"),dt("2024-11-27T21:00:00+00:00"))
    assert interval[-1]==(dt("2024-11-29T17:30:00+00:00"),dt("2024-11-29T18:00:00+00:00"))
    assert all(a.day!=28 for a,z in interval)


def test_hourly_normalization_detects_missing_bar_without_filling_it():
    ss=sessions()
    expected=schedule_intervals(ss,"1h",ss[0].open_time,ss[-1].close_time)
    times=[a for a,z in expected]
    c=chart(times[:3]+times[4:])
    n=normalize(c,"1h",ss,ss[0].open_time,ss[-1].close_time,ss[-1].close_time)
    with pytest.raises(DataQualityError) as exc:
        validate(n.bars,DataPolicy("Yahoo Finance","SPY","1h","source OHLC; adjustment pending",True,n.expected))
    assert len(exc.value.report["missing_bars"])==1
    assert len(n.bars)==10


def test_daily_date_label_only_becomes_visible_at_actual_session_close():
    ss=sessions()
    c=chart([dt("2024-11-27T00:00:00-05:00"),dt("2024-11-29T00:00:00-05:00")],"1d")
    n=normalize(c,"1d",ss,ss[0].open_time,ss[-1].close_time,ss[-1].close_time)
    assert n.bars[0].open_time==ss[0].open_time
    assert n.bars[0].close_time==ss[0].close_time
    assert completed(n.bars,dt("2024-11-27T20:59:00+00:00"))==()
    assert completed(n.bars,ss[0].close_time)==(n.bars[0],)
    assert completed(n.bars,dt("2024-11-29T17:59:00+00:00"))==(n.bars[0],)


def test_incomplete_hour_and_daily_bars_are_explicitly_excluded():
    ss=sessions()[-1:]
    now=dt("2024-11-29T17:45:00+00:00")
    c=chart([ss[0].open_time+timedelta(hours=i) for i in range(4)])
    n=normalize(c,"1h",ss,ss[0].open_time,now,now)
    assert len(n.bars)==3
    assert len(n.expected)==3
    assert n.exclusions[0]["reason"]=="incomplete_bar"
    daily=normalize(chart([ss[0].open_time],"1d"),"1d",ss,ss[0].open_time,now,now)
    assert daily.bars==()
    assert daily.exclusions[0]["reason"]=="incomplete_bar"


def test_bad_volume_nulls_and_invalid_prices_are_not_repaired():
    ss=sessions()[-1:]
    c=chart([ss[0].open_time],values=[{"open":100,"high":101,"low":99,"close":None,"volume":None}])
    n=normalize(c,"1h",ss,ss[0].open_time,ss[0].open_time+timedelta(hours=1),ss[0].close_time)
    with pytest.raises(DataQualityError):
        validate(n.bars,DataPolicy("Yahoo Finance","SPY","1h","source OHLC; adjustment pending",True,n.expected))
    assert n.bars[0].volume is None


def test_unexpected_holiday_timestamp_is_reported_not_silently_dropped():
    ss=sessions()
    c=chart([dt("2024-11-28T14:30:00+00:00")])
    with pytest.raises(ValueError,match="outside.*session"):
        normalize(c,"1h",ss,ss[0].open_time,ss[-1].close_time,ss[-1].close_time)


def test_closing_quote_is_only_excluded_if_zero_volume_and_flat_ohlc():
    ss=sessions()[-1:]
    c=chart([ss[0].open_time,ss[0].close_time],values=[
        {"open":100,"high":101,"low":99,"close":100,"volume":1000},
        {"open":100,"high":100,"low":100,"close":100,"volume":0}])
    n=normalize(c,"1h",ss,ss[0].open_time,ss[0].close_time,ss[0].close_time)
    assert len(n.bars)==1
    assert n.exclusions[0]["reason"]=="zero_duration_closing_quote"


def test_duplicate_rows_survive_normalization_and_fail_validation():
    ss=sessions()[-1:]
    n=normalize(chart([ss[0].open_time]*2),"1h",ss,ss[0].open_time,
                ss[0].open_time+timedelta(hours=1),ss[0].close_time)
    with pytest.raises(DataQualityError):
        validate(n.bars,DataPolicy("Yahoo Finance","SPY","1h","source OHLC",True,n.expected))


@pytest.mark.parametrize("body",[
    b'{"chart":{"error":{"code":"Not Found"},"result":null}}',
    b'{"chart":{"error":null,"result":[]}}',
])
def test_provider_errors_cannot_become_empty_successful_datasets(body):
    with pytest.raises(ValueError):
        parse_chart(body,"SPY","1h")


def test_asset_and_interval_mismatch_fail():
    c=chart([sessions()[0].open_time])
    with pytest.raises(ValueError,match="asset"):
        parse_chart(c.raw,"QQQ","1h")
    with pytest.raises(ValueError,match="interval"):
        parse_chart(c.raw,"SPY","1d")


def test_artifacts_preserve_raw_data_and_generate_no_cost_assumptions(tmp_path):
    ss=sessions()
    expected=schedule_intervals(ss,"1h",ss[0].open_time,ss[-1].close_time)
    hour=chart([a for a,z in expected])
    daily=chart([s.open_time for s in ss],"1d")
    dest=export_asset(tmp_path,"SPY",hour,daily,ss,ss[0].open_time,
                      ss[-1].close_time,ss[-1].close_time,calendar_name="XNYS")
    assert (dest/"hourly_raw.json").read_bytes()==hour.raw
    assert (dest/"daily_raw.json").read_bytes()==daily.raw
    report=json.loads((dest/"quality.json").read_text())
    assert report["hourly"]["missing_bars"]==[]
    config=json.loads((dest/"research.json").read_text())
    assert config["data"]["asset"]=="SPY"
    assert config["higher_data"]["timeframe"]=="1d"
    assert config["backtest"]["initial_cash"] is None
    assert config["backtest"]["execution"]["commission_bps_per_side"] is None
    assert len(load_csv(dest/"hourly.csv"))==11
    assert len(load_schedule(dest/"hourly_schedule.csv"))==11
    assert json.loads((dest/"manifest.json").read_text())["raw_hashes"]["hourly_raw.json"]
    with pytest.raises(FileExistsError):
        export_asset(tmp_path,"SPY",hour,daily,ss,ss[0].open_time,
                     ss[-1].close_time,ss[-1].close_time,calendar_name="XNYS")


def test_download_cli_uses_explicit_assets_and_output_directory(tmp_path,monkeypatch,capsys):
    from llm_trading.cli import main
    requested=[]
    def fake_download(root,assets):
        requested.append((root,tuple(assets)))
        return tmp_path/"batch"
    monkeypatch.setattr("llm_trading.yahoo.download_yahoo",fake_download)
    status=main(["download-yahoo","--assets","SPY","QQQ","GLD","--output-root",str(tmp_path)])
    assert status==0
    assert requested==[(str(tmp_path),("SPY","QQQ","GLD"))]
    assert json.loads(capsys.readouterr().out)["download_path"]==str(tmp_path/"batch")


def test_max_daily_request_negative_epoch_is_portable_on_windows():
    from llm_trading.yahoo import epoch_datetime
    assert epoch_datetime(-1)==dt("1969-12-31T23:59:59+00:00")


def test_nasdaq_yahoo_exchange_codes_resolve_to_nasdaq_calendar():
    from llm_trading.yahoo import calendar_for
    assert calendar_for({"exchangeName":"NGM","exchangeTimezoneName":"America/New_York"})=="XNAS"
    assert calendar_for({"exchangeName":"NMS","exchangeTimezoneName":"America/New_York"})=="XNAS"
    with pytest.raises(ValueError,match="unrecognized"):
        calendar_for({"exchangeName":"UNKNOWN","exchangeTimezoneName":"America/New_York"})


def test_provider_bars_after_early_close_are_excluded_and_audited():
    ss=sessions()[-1:]
    # Yahoo may send real after-hours bars despite includePrePost=False.
    c=chart([ss[0].open_time,ss[0].close_time,ss[0].close_time+timedelta(hours=1)])
    n=normalize(c,"1h",ss,ss[0].open_time,ss[0].close_time+timedelta(hours=3),
                ss[0].close_time+timedelta(hours=3))
    assert len(n.bars)==1
    assert len(n.exclusions)==2
    assert all(e["reason"]=="outside_regular_session" for e in n.exclusions)
    assert len(n.expected)==4
