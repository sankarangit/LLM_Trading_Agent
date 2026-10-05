"""Signed cash accounting; reporting gross P&L uses uncosted reference prices."""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from .execution import Fill
from .types import AccountSnapshot, Decision


@dataclass
class Position:
    side: int
    size: float
    entry: Fill
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_bar: int
    stop: float
    target: float | None
    horizon: int | None
    trailing_pct: float | None
    trade_id: int
    dividend_pnl: float = 0.0


class Portfolio:
    def __init__(self, initial_cash: float, daily_timezone: str):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.realized_pnl = 0.0
        self.transaction_costs = 0.0
        self.peak_equity = initial_cash
        self.position: Position | None = None
        self.zone = ZoneInfo(daily_timezone)
        self.day = None
        self.daily_start = initial_cash
        self.trade_counter = 0
        self.receivables = []

    def accrue_dividend(self, event):
        p=self.position
        if not p:
            return None
        amount=p.side*p.size*event.amount
        p.dividend_pnl+=amount
        self.receivables.append((event.pay_time, amount, p.trade_id, event.ex_time))
        return {'kind':'entitlement','timestamp':event.ex_time.isoformat(),
                'pay_time':event.pay_time.isoformat(),'trade_id':p.trade_id,
                'amount_per_share':event.amount,'amount':amount,'source':event.source}

    def pay_dividends(self, at):
        paid=[]
        remaining=[]
        for pay,amount,trade_id,ex in self.receivables:
            if pay<=at:
                self.cash+=amount
                paid.append({'kind':'payment','timestamp':at.isoformat(),
                             'scheduled_pay_time':pay.isoformat(),'trade_id':trade_id,
                             'amount':amount,'ex_time':ex.isoformat()})
            else:
                remaining.append((pay,amount,trade_id,ex))
        self.receivables=remaining
        return paid

    def equity(self, price):
        p = self.position
        return self.cash + sum(r[1] for r in self.receivables) + (p.side * p.size * price if p else 0)

    def mark(self, price: float, at: datetime) -> AccountSnapshot:
        day = at.astimezone(self.zone).date()
        if day != self.day:
            # The previous mark (before overnight price change) starts the new day.
            self.day = day
            self.daily_start = getattr(self, "last_equity", self.initial_cash)
        eq = self.equity(price)
        self.last_equity = eq
        self.peak_equity = max(self.peak_equity, eq)
        p = self.position
        unrealized = p.side * p.size * (price - p.entry.price) + p.dividend_pnl if p else 0.0
        return AccountSnapshot(self.cash, eq, self.realized_pnl, unrealized,
                               "LONG" if p and p.side == 1 else "SHORT" if p else "FLAT",
                               p.entry.price if p else None, p.size if p else 0.0,
                               p.size * price if p else 0.0, self.peak_equity,
                               1 - eq / self.peak_equity,
                               eq - self.daily_start, self.transaction_costs,
                               sum(r[1] for r in self.receivables))

    def enter(self, fill: Fill, decision: Decision, signal: datetime, at: datetime, bar_index: int):
        if self.position:
            raise ValueError("position already open")
        self.cash -= fill.direction * fill.size * fill.price + fill.commission
        self.transaction_costs += fill.total_cost
        distance = fill.price * decision.stop_distance_pct / 100
        target = (fill.price + fill.direction * distance * decision.target_r_multiple
                  if decision.target_r_multiple else None)
        if target is not None and target <= 0:
            raise ValueError("nonpositive target")
        self.trade_counter += 1
        self.position = Position(fill.direction, fill.size, fill, signal, at, bar_index,
                                 fill.price - fill.direction * distance, target,
                                 decision.horizon_bars, decision.trailing_stop_pct,
                                 self.trade_counter)

    def exit(self, fill: Fill, at: datetime, bar_index: int, reason: str, bounded=False):
        p = self.position
        if p is None or fill.direction != -p.side or fill.size != p.size:
            raise ValueError("invalid closing fill")
        self.cash -= fill.direction * fill.size * fill.price + fill.commission
        self.transaction_costs += fill.total_cost
        gross = p.side * p.size * (fill.reference_price - p.entry.reference_price)
        commission = p.entry.commission + fill.commission
        spread = p.entry.spread_cost + fill.spread_cost
        slip = p.entry.slippage_cost + fill.slippage_cost
        rounding = p.entry.rounding_cost + fill.rounding_cost
        net = gross + p.dividend_pnl - commission - spread - slip - rounding
        self.realized_pnl += net
        trade = {"trade_id": p.trade_id, "signal_timestamp": p.signal_timestamp.isoformat(),
                 "entry_timestamp": p.entry_timestamp.isoformat(), "entry_price": p.entry.price,
                 "entry_reference_price": p.entry.reference_price,
                 "side": "LONG" if p.side == 1 else "SHORT", "size": p.size,
                 "stop": p.stop, "target": p.target, "exit_timestamp": at.isoformat(),
                 "exit_price": fill.price, "exit_reference_price": fill.reference_price,
                 "exit_reason": reason, "gross_pnl": gross, "commission": commission,
                 "spread_cost": spread, "slippage": slip, "rounding_cost": rounding,
                 "net_pnl": net, "holding_bars": bar_index - p.entry_bar + (1 if bounded else 0),
                 "dividend_pnl":p.dividend_pnl,
                 "holding_seconds": (at-p.entry_timestamp).total_seconds(),
                 "intrabar_timestamp_is_bound": bounded}
        self.position = None
        return trade
