"""Authoritative deterministic sizing; confidence never changes allocation."""
from dataclasses import dataclass
import math
from .execution import costed_fill, floor_quantity
from .types import AccountSnapshot, Decision, ExecutionConfig, RiskConfig


@dataclass(frozen=True)
class RiskResult:
    allowed: bool
    reason: str
    size: float = 0.0


def positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def validate_risk(c: RiskConfig):
    for name in ("max_risk_per_trade_pct", "max_daily_loss_pct",
                 "max_portfolio_drawdown_pct", "max_gross_exposure_pct"):
        if not positive(getattr(c, name)) or getattr(c, name) > 100:
            raise ValueError(f"{name} must be in (0,100]")
    if c.max_positions != 1:
        raise ValueError("V1 single-instrument engine supports max_positions=1")
    if not isinstance(c.allow_short, bool):
        raise ValueError("allow_short must be boolean")


class RiskEngine:
    def __init__(self, config: RiskConfig, execution: ExecutionConfig):
        validate_risk(config)
        self.config, self.execution = config, execution
        self.dd_killed = False
        self.daily_killed = False
        self.day = None

    def observe(self, account: AccountSnapshot, day, daily_start: float) -> str | None:
        if day != self.day:
            self.daily_killed = False
            self.day = day
        c = self.config
        if account.drawdown * 100 >= c.max_portfolio_drawdown_pct or account.equity <= 0:
            self.dd_killed = True
        if account.daily_pnl <= -daily_start * c.max_daily_loss_pct / 100:
            self.daily_killed = True
        return "max_drawdown" if self.dd_killed else "daily_loss" if self.daily_killed else None

    def evaluate(self, d: Decision, a: AccountSnapshot, reference_price: float) -> RiskResult:
        if not isinstance(d, Decision) or not isinstance(d.action,str) or d.action not in {"LONG", "SHORT", "HOLD", "CLOSE"}:
            return RiskResult(False, "invalid_action")
        if d.action == "HOLD":
            return RiskResult(True, "hold")
        if d.action == "CLOSE":
            return RiskResult(a.position_size > 0, "close" if a.position_size else "no_position", a.position_size)
        if self.dd_killed:
            return RiskResult(False, "max_drawdown")
        if self.daily_killed:
            return RiskResult(False, "daily_loss")
        if a.position_size:
            return RiskResult(False, "position_already_open")
        if d.action == "SHORT" and not self.config.allow_short:
            return RiskResult(False, "short_disabled")
        if not positive(d.stop_distance_pct) or d.stop_distance_pct >= 100:
            return RiskResult(False, "missing_stop_distance")
        if d.target_r_multiple is not None and not positive(d.target_r_multiple):
            return RiskResult(False, "invalid_target")
        if d.horizon_bars is not None and (type(d.horizon_bars) is not int or d.horizon_bars < 1):
            return RiskResult(False, "invalid_horizon")
        if d.trailing_stop_pct is not None and (not positive(d.trailing_stop_pct) or d.trailing_stop_pct >= 100):
            return RiskResult(False, "invalid_trailing_stop")
        if not positive(reference_price) or not positive(a.equity):
            return RiskResult(False, "insufficient_data_or_equity")
        side = 1 if d.action == "LONG" else -1
        entry = costed_fill(reference_price, 1, side, self.execution)
        stop = entry.price * (1 - side * d.stop_distance_pct / 100)
        if d.target_r_multiple and side == -1 and entry.price * (1 - d.stop_distance_pct / 100 * d.target_r_multiple) <= 0:
            return RiskResult(False, "invalid_target")
        # Friction-crossed stops are immediately executable at the raw open.
        stop_reference = min(stop,reference_price) if side==1 else max(stop,reference_price)
        closing = costed_fill(stop_reference, 1, -side, self.execution)
        loss_per_unit = side * (entry.price - closing.price) + entry.commission + closing.commission
        risk_size = a.equity * self.config.max_risk_per_trade_pct / 100 / loss_per_unit
        exposure_size = a.equity * self.config.max_gross_exposure_pct / 100 / max(reference_price, entry.price)
        # Long purchases cannot use commission cash that does not exist.
        cash_size = a.cash / (entry.price + entry.commission) if side == 1 else math.inf
        size = floor_quantity(min(risk_size, exposure_size, cash_size), self.execution.quantity_increment)
        return RiskResult(size > 0, "approved" if size > 0 else "below_minimum_quantity", size)
