"""Causal, scale-free statistical snapshots using only supplied completed bars."""
from dataclasses import dataclass
import math
from statistics import mean, stdev, variance


@dataclass(frozen=True)
class FeatureConfig:
    window: int = 24
    short_window: int = 8
    variance_ratio_horizon: int = 4
    volume: bool = True
    regime: bool = True
    enabled: tuple[str, ...] | None = None
    trend_r2_threshold: float = 0.30
    high_vol_percentile: float = 0.75
    transition_band: float = 0.05


# Definitions travel with exported experiments. None means unavailable/undefined;
# it is never replaced by zero or a population-wide fitted statistic.
FEATURE_CATALOGUE = {
    **{f"return_{h}": {"definition":f"close(T)/close(T-{h})-1", "minimum_bars":h+1,
                          "window":h, "normalization":"ratio"} for h in (1,2,4,8,24)},
    "return_zscore":{"definition":"(latest log return - mean window returns)/sample std", "minimum":"window+1"},
    "return_percentile":{"definition":"(count less + 0.5*count equal)/window of log returns", "minimum":"window+1"},
    "realized_volatility":{"definition":"sample std of window log returns; per-bar", "minimum":"window+1"},
    "realized_vol_percentile":{"definition":"midrank current rolling vol vs latest window rolling vols", "minimum":"2*window"},
    "downside_volatility":{"definition":"sqrt(mean(min(log_return,0)^2))", "minimum":"window+1"},
    "upside_downside_ratio":{"definition":"sqrt(mean(max(log_return,0)^2))/downside_volatility", "minimum":"window+1"},
    "return_skew":{"definition":"population centered third moment / population std^3", "minimum":"window+1"},
    "return_kurtosis":{"definition":"population centered fourth moment / population variance^2 - 3", "minimum":"window+1"},
    "trend_slope":{"definition":"OLS slope of log closes on integer bar index", "minimum":"window"},
    "trend_slope_normalized":{"definition":"OLS log-price slope / window realized volatility", "minimum":"window+1"},
    "trend_tstat":{"definition":"OLS slope / sqrt((SSE/(window-2))/Sxx)", "minimum":"window"},
    "trend_r_squared":{"definition":"1-SSE/SST; constant prices defined as 0", "minimum":"window"},
    "trend_agreement":{"definition":"mean sign of available 1/2/4/8/24 bar returns", "minimum":25},
    "momentum_acceleration":{"definition":"latest 4-bar return minus preceding 4-bar return", "minimum":9},
    "price_zscore":{"definition":"(latest log close - window mean log close)/sample std log close", "minimum":"window"},
    "distance_mean_vol":{"definition":"(latest log close - window mean log close)/window return volatility", "minimum":"window+1"},
    "autocorrelation":{"definition":"Pearson correlation of consecutive window log returns", "minimum":"window+1"},
    "variance_ratio":{"definition":"sample var overlapping k-bar log returns / (k*sample var 1-bar returns)", "minimum":"window+k"},
    "half_life_bars":{"definition":"-log(2)/OLS coefficient in delta(log price) ~ lag(log price); only negative coefficients", "minimum":"window"},
    "short_long_vol_ratio":{"definition":"sample std short_window log returns / sample std window log returns", "minimum":"window+1"},
    "range_percentile":{"definition":"midrank latest (high-low)/close vs window ranges", "minimum":"window"},
    "relative_volume":{"definition":"latest volume / window mean volume", "minimum":"window"},
    "volume_zscore":{"definition":"(latest volume - window mean)/window sample std", "minimum":"window"},
    "volume_acceleration":{"definition":"latest volume / preceding volume - 1", "minimum":2},
    "range_volume_anomaly":{"definition":"latest relative range / relative volume", "minimum":"window"},
    "regime":{"definition":"R2 and causal volatility percentile with configurable transition band", "minimum":"2*window"},
    "higher_return_1":{"definition":"latest completed higher close / preceding completed higher close - 1", "minimum":"2 higher bars"},
}
for _definition in FEATURE_CATALOGUE.values():
    _definition.setdefault("window","config.window unless explicitly specified")
    _definition.setdefault("normalization","scale-free")
    _definition["nan_policy"]="None until minimum observations; None for undefined denominator"
    _definition["anti_leakage"]="completed prefix only; future-perturbation and scale-invariance tests"


def ratio(a,b):
    return a/b if b is not None and abs(b)>1e-12 else None


def rank(values):
    current=values[-1]
    return (sum(v<current for v in values)+0.5*sum(v==current for v in values))/len(values)


def correlation(a,b):
    ma,mb=mean(a),mean(b)
    denom=math.sqrt(sum((v-ma)**2 for v in a)*sum((v-mb)**2 for v in b))
    return ratio(sum((x-ma)*(y-mb) for x,y in zip(a,b)),denom)


def regression(y):
    n=len(y)
    center=(n-1)/2
    avg=mean(y)
    xx=sum((i-center)**2 for i in range(n))
    slope=sum((i-center)*(v-avg) for i,v in enumerate(y))/xx
    residual=sum((v-avg-slope*(i-center))**2 for i,v in enumerate(y))
    total=sum((v-avg)**2 for v in y)
    se=math.sqrt(residual/(n-2)/xx)
    return slope, ratio(slope,se), max(0,min(1,1-residual/total)) if total>1e-24 else 0


def snapshot(bars, higher_bars=(), config=FeatureConfig()):
    c=config
    if type(c.window) is not int or c.window<4 or type(c.short_window) is not int or not 2<=c.short_window<=c.window:
        raise ValueError("window>=4 and 2<=short_window<=window required")
    if type(c.variance_ratio_horizon) is not int or not 2<=c.variance_ratio_horizon<=c.window:
        raise ValueError("variance_ratio_horizon must lie in [2,window]")
    if not (0<c.trend_r2_threshold<1 and 0<c.high_vol_percentile<1 and 0<=c.transition_band<1):
        raise ValueError("invalid regime thresholds")
    if c.enabled is not None and not set(c.enabled)<=set(FEATURE_CATALOGUE):
        raise ValueError("unknown feature name")
    s={name:None for name in FEATURE_CATALOGUE}
    closes=[b.close for b in bars]
    n=len(closes)
    logs=[math.log(v) for v in closes]
    rets=[b-a for a,b in zip(logs,logs[1:])]
    w=c.window
    for h in (1,2,4,8,24):
        if n>h:
            s[f"return_{h}"]=closes[-1]/closes[-1-h]-1
    if n>=9:
        s["momentum_acceleration"]=(closes[-1]/closes[-5]-1)-(closes[-5]/closes[-9]-1)
    if n>=25:
        s["trend_agreement"]=mean([1 if s[f"return_{h}"]>0 else -1 if s[f"return_{h}"]<0 else 0 for h in (1,2,4,8,24)])
    if n>=w:
        y=logs[-w:]
        slope,tstat,r2=regression(y)
        s.update(trend_slope=slope,trend_tstat=tstat,trend_r_squared=r2,
                 price_zscore=ratio(y[-1]-mean(y),stdev(y)))
        ranges=[(b.high-b.low)/b.close for b in bars[-w:]]
        s["range_percentile"]=rank(ranges)
        lag=y[:-1]
        dy=[b-a for a,b in zip(y,y[1:])]
        beta=ratio(sum((a-mean(lag))*(b-mean(dy)) for a,b in zip(lag,dy)),
                   sum((a-mean(lag))**2 for a in lag))
        s["half_life_bars"]=-math.log(2)/beta if beta is not None and beta<-1e-12 else None
        if c.volume:
            vols=[b.volume for b in bars[-w:]]
            if all(v is not None for v in vols):
                s["relative_volume"]=ratio(vols[-1],mean(vols))
                s["volume_zscore"]=ratio(vols[-1]-mean(vols),stdev(vols))
                s["range_volume_anomaly"]=ratio(ranges[-1]/mean(ranges) if mean(ranges) else 0,s["relative_volume"])
    if len(rets)>=w:
        r=rets[-w:]
        rv=stdev(r)
        avg=mean(r)
        popvar=mean([(v-avg)**2 for v in r])
        down=math.sqrt(mean([min(v,0)**2 for v in r]))
        s.update(realized_volatility=rv,return_zscore=ratio(r[-1]-avg,rv),
                 return_percentile=rank(r),downside_volatility=down,
                 upside_downside_ratio=ratio(math.sqrt(mean([max(v,0)**2 for v in r])),down),
                 return_skew=ratio(mean([(v-avg)**3 for v in r]),popvar**1.5),
                 return_kurtosis=(mean([(v-avg)**4 for v in r])/popvar**2-3) if popvar>1e-24 else None,
                 autocorrelation=correlation(r[:-1],r[1:]),
                 short_long_vol_ratio=ratio(stdev(r[-c.short_window:]),rv),
                 trend_slope_normalized=ratio(s["trend_slope"],rv),
                 distance_mean_vol=ratio(logs[-1]-mean(logs[-w:]),rv))
    if len(rets)>=2*w-1:
        vols=[stdev(rets[i-w:i]) for i in range(len(rets)-w+1,len(rets)+1)]
        s["realized_vol_percentile"]=rank(vols)
        if c.regime:
            r2=s["trend_r_squared"]
            if abs(r2-c.trend_r2_threshold)<=c.transition_band:
                s["regime"]="TRANSITION"
            else:
                vol="HIGH_VOL" if s["realized_vol_percentile"]>=c.high_vol_percentile else "LOW_VOL"
                s["regime"]=vol+("_TREND" if r2>c.trend_r2_threshold else "_RANGE")
    k=c.variance_ratio_horizon
    if len(rets)>=w+k-1:
        aggregated=[sum(rets[i-k:i]) for i in range(len(rets)-w+1,len(rets)+1)]
        s["variance_ratio"]=ratio(variance(aggregated),k*variance(rets[-w:]))
    if c.volume and n>=2 and bars[-1].volume is not None and bars[-2].volume is not None:
        value=ratio(bars[-1].volume,bars[-2].volume)
        s["volume_acceleration"]=value-1 if value is not None else None
    if len(higher_bars)>=2:
        s["higher_return_1"]=higher_bars[-1].close/higher_bars[-2].close-1
    if not c.volume:
        for key in ("relative_volume","volume_zscore","volume_acceleration","range_volume_anomaly"):
            s.pop(key)
    if not c.regime:
        s.pop("regime")
    if c.enabled is not None:
        s={k:v for k,v in s.items() if k in c.enabled}
    return {k:(v if not isinstance(v,float) or math.isfinite(v) else None) for k,v in s.items()}
