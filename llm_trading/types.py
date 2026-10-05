"""Contracts shared by deterministic strategies and the future LLM interface."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from .data import Bar


@dataclass(frozen=True)
class Decision:
    action: str
    stop_distance_pct: float | None = None
    target_r_multiple: float | None = None
    horizon_bars: int | None = None
    reason: str = ""
    trailing_stop_pct: float | None = None


@dataclass(frozen=True)
class RiskConfig:
    max_risk_per_trade_pct: float = 0.50
    max_daily_loss_pct: float = 1.50
    max_portfolio_drawdown_pct: float = 10.00
    max_gross_exposure_pct: float = 100.00
    max_positions: int = 1
    allow_short: bool = True


@dataclass(frozen=True)
class ExecutionConfig:
    commission_bps_per_side: float
    slippage_bps_per_side: float
    spread_bps: float
    minimum_tick: float
    quantity_increment: float
    ambiguity_policy: str = "stop_first"


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    position: str
    entry_price: float | None
    position_size: float
    exposure: float
    peak_equity: float
    drawdown: float
    daily_pnl: float
    transaction_costs: float
    dividend_receivable: float = 0.0


@dataclass(frozen=True)
class Context:
    timestamp: datetime
    bars: tuple[Bar, ...]
    higher_bars: tuple[Bar, ...]
    account: AccountSnapshot
    features: tuple[tuple[str, object], ...] = ()


class Strategy(Protocol):
    def decide(self, context: Context) -> Decision: ...
