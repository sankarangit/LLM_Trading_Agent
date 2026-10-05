from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import pytest
from llm_trading.data import Bar, DataPolicy, completed, validate
from llm_trading.features import FeatureConfig, snapshot, FEATURE_CATALOGUE
from test_engine import dataset, Scripted, cfg
from llm_trading.engine import run


def history():
    return dataset([(100+i*.2+math.sin(i),100+i*.2+math.sin(i)) for i in range(90)]).bars


def test_features_unchanged_when_future_prices_and_volume_change():
    rows=history()
    mutated=rows[:50]+tuple(replace(b,open=b.open*10,high=b.high*10,low=b.low*10,
                                   close=b.close*10,volume=b.volume*100) for b in rows[50:])
    for n in (1,5,24,30,50):
        assert snapshot(rows[:n],(),FeatureConfig())==snapshot(mutated[:n],(),FeatureConfig())


def test_scale_invariance_of_statistical_price_features():
    rows=history()
    scaled=tuple(replace(b,open=b.open*10,high=b.high*10,low=b.low*10,close=b.close*10) for b in rows)
    a,b=snapshot(rows,(),FeatureConfig()),snapshot(scaled,(),FeatureConfig())
    for key,value in a.items():
        if isinstance(value,float):
            assert b[key]==pytest.approx(value,rel=1e-7,abs=1e-8),key
        else:
            assert b[key]==value,key


def test_hand_calculated_returns_and_warmup_are_explicit():
    rows=dataset([(100,100),(110,110),(121,121)]).bars
    s=snapshot(rows,(),FeatureConfig())
    assert s["return_1"]==pytest.approx(.1)
    assert s["return_2"]==pytest.approx(.21)
    assert s["return_4"] is None
    assert s["trend_tstat"] is None
    assert s["volume_zscore"] is None
    assert set(s)<=set(FEATURE_CATALOGUE)


def test_zero_variance_never_produces_nan_or_inf():
    rows=dataset([(100,100)]*90).bars
    s=snapshot(rows,(),FeatureConfig())
    assert s["realized_volatility"]==0
    assert s["price_zscore"] is None
    assert s["trend_tstat"] is None
    assert s["autocorrelation"] is None
    assert s["regime"]=="LOW_VOL_RANGE"
    assert all(not isinstance(v,float) or math.isfinite(v) for v in s.values())


def test_volume_unsupported_is_null_and_volume_disabled_is_removed():
    rows=tuple(replace(b,volume=None) for b in history())
    assert snapshot(rows,(),FeatureConfig())["volume_zscore"] is None
    assert snapshot(rows,(),FeatureConfig())["relative_volume"] is None
    s=snapshot(rows,(),replace(FeatureConfig(),volume=False))
    assert "volume_zscore" not in s
    assert "relative_volume" not in s


def test_incomplete_daily_bar_is_never_visible_to_intraday_strategy():
    intraday=dataset([(100,100)]*30)
    t=intraday.bars[0].open_time
    daily=(Bar(t,t+timedelta(days=1),100,105,95,101,24000),
           Bar(t+timedelta(days=1),t+timedelta(days=2),101,500,1,499,24000))
    higher=validate(daily,DataPolicy("synthetic-test","TEST","1d","not_applicable",True,
                    tuple((b.open_time,b.close_time) for b in daily)))
    s=Scripted({})
    run(intraday,s,cfg(),higher,lambda rows,h:snapshot(rows,h,FeatureConfig()))
    assert s.seen[22].higher_bars==()
    assert s.seen[23].higher_bars==(daily[0],)
    assert s.seen[-1].higher_bars==(daily[0],)
    assert dict(s.seen[-1].features)["higher_return_1"] is None
    assert completed(daily,t+timedelta(hours=23))==()


def test_trend_regression_hand_calculation_and_past_only_rank():
    rows=dataset([(100*math.exp(i*.001),100*math.exp(i*.001)) for i in range(40)]).bars
    s=snapshot(rows,(),FeatureConfig())
    assert s["trend_r_squared"]==pytest.approx(1)
    assert s["trend_slope"]==pytest.approx(.001)
    # Exact trend has no residual variance: no fabricated infinite t statistic.
    assert s["trend_tstat"] is None


def test_feature_toggles_and_invalid_windows():
    c=replace(FeatureConfig(),regime=False,enabled=("return_1","price_zscore"))
    assert set(snapshot(history(),(),c))=={"return_1","price_zscore"}
    with pytest.raises(ValueError):
        snapshot(history(),(),replace(FeatureConfig(),window=2))
    with pytest.raises(ValueError):
        snapshot(history(),(),replace(FeatureConfig(),enabled=("future_return",)))
