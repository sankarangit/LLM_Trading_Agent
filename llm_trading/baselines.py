"""B0-B4 deterministic controls and independent seeded random policies."""
from dataclasses import dataclass
import math
import random
from .types import Decision


@dataclass(frozen=True)
class StrategyConfig:
    stop_distance_pct: float
    momentum_threshold: float
    reversion_entry_z: float
    reversion_exit_z: float
    horizon_bars: int | None = None
    target_r_multiple: float | None = None
    trailing_stop_pct: float | None = None
    stop_mode: str = "fixed_pct"
    volatility_stop_multiple: float | None = None
    momentum_horizon: int = 8
    allow_short: bool = True


def validate_strategy(c):
    if c.momentum_horizon not in {1,2,4,8,24} or not isinstance(c.allow_short,bool):
        raise ValueError('supported momentum horizon and boolean allow_short required')
    if not 0<c.stop_distance_pct<100 or not math.isfinite(c.stop_distance_pct):
        raise ValueError("stop_distance_pct must lie in (0,100)")
    if not math.isfinite(c.momentum_threshold) or c.momentum_threshold<0:
        raise ValueError("nonnegative momentum_threshold required")
    if not all(math.isfinite(x) for x in (c.reversion_entry_z,c.reversion_exit_z)) or not 0<=c.reversion_exit_z<c.reversion_entry_z:
        raise ValueError("0<=reversion_exit_z<reversion_entry_z required")
    if c.horizon_bars is not None and (type(c.horizon_bars) is not int or c.horizon_bars<1):
        raise ValueError("positive integer horizon required")
    if c.stop_mode not in {"fixed_pct","realized_volatility"}:
        raise ValueError("stop_mode must be fixed_pct or realized_volatility")
    if c.stop_mode=="realized_volatility" and (c.volatility_stop_multiple is None or
            not math.isfinite(c.volatility_stop_multiple) or c.volatility_stop_multiple<=0):
        raise ValueError("positive volatility_stop_multiple required")


class Baseline:
    def __init__(self, name, config, seed):
        validate_strategy(config)
        self.name,self.config=name,config
        self.rng=random.Random(seed)
        self.buy_hold_requested=False

    def entry(self, action, reason, features=None):
        c=self.config
        stop=c.stop_distance_pct
        if c.stop_mode=="realized_volatility":
            rv=(features or {}).get("realized_volatility")
            if rv is None or rv<=0:
                return Decision("HOLD",reason="insufficient volatility for deterministic stop")
            stop=100*rv*c.volatility_stop_multiple
        return Decision(action,stop,c.target_r_multiple,c.horizon_bars,
                        reason,c.trailing_stop_pct)

    def align(self, desired, current, reason, features=None):
        if desired=='SHORT' and not self.config.allow_short:
            desired='FLAT'
        if desired==current:
            return Decision("HOLD",reason=reason)
        if current!="FLAT":
            return Decision("CLOSE",reason=reason)
        if desired=="FLAT":
            return Decision("HOLD",reason=reason)
        return self.entry(desired,reason,features)

    def decide(self, context):
        current=context.account.position
        features=dict(context.features)
        c=self.config
        if self.name=="buy_hold":
            # B0 obeys the same stops and kill switches; no silent re-entry after exit.
            if self.buy_hold_requested or current!="FLAT":
                return Decision("HOLD",reason="passive benchmark")
            request=self.entry("LONG","passive benchmark under shared risk constraints",features)
            self.buy_hold_requested=request.action=="LONG"
            return request
        if self.name=="random":
            action=self.rng.choice(("LONG","SHORT","HOLD","CLOSE") if c.allow_short else ("LONG","HOLD","CLOSE"))
            return self.entry(action,"seeded uniform random action",features) if action in {"LONG","SHORT"} else Decision(action,reason="seeded uniform random action")
        if self.name=="momentum":
            value=features.get(f"return_{c.momentum_horizon}")
            if value is None:
                return Decision("HOLD",reason="momentum warmup/missing feature")
            desired="LONG" if value>c.momentum_threshold else "SHORT" if value<-c.momentum_threshold else "FLAT"
            return self.align(desired,current,f"{c.momentum_horizon}-bar momentum threshold",features)
        if self.name=="mean_reversion":
            return self.reversion(features,current)
        regime=features.get("regime")
        if regime is None:
            return Decision("HOLD",reason="regime warmup/missing feature")
        if regime=="TRANSITION":
            return self.align("FLAT",current,"transition regime",features)
        if regime.endswith("RANGE"):
            return self.reversion(features,current)
        value=features.get(f"return_{c.momentum_horizon}")
        if value is None:
            return Decision("HOLD",reason="missing momentum in trend regime")
        desired="LONG" if value>c.momentum_threshold else "SHORT" if value<-c.momentum_threshold else "FLAT"
        return self.align(desired,current,f"statistical trend regime with {c.momentum_horizon}-bar momentum",features)

    def reversion(self, features, current):
        z=features.get("price_zscore")
        if z is None:
            return Decision("HOLD",reason="mean-reversion warmup/missing feature")
        if current!="FLAT":
            if abs(z)<=self.config.reversion_exit_z or (current=="LONG" and z>0) or (current=="SHORT" and z<0):
                return Decision("CLOSE",reason="statistical invalidation or reversion to mean")
            return Decision("HOLD",reason="waiting for mean reversion")
        desired="LONG" if z<-self.config.reversion_entry_z else "SHORT" if z>self.config.reversion_entry_z else "FLAT"
        return self.align(desired,current,"log-price z-score entry",features)


def build_strategy(name, config, seed):
    if name not in {"buy_hold","random","momentum","mean_reversion","statistical_regime"}:
        raise ValueError(f"unsupported strategy: {name}")
    if type(seed) is not int:
        raise ValueError("integer strategy seed required")
    return Baseline(name,config,seed)
