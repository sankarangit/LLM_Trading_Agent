"""Consistent close-sampled metrics. Undefined ratios are JSON null."""
from datetime import datetime
import math
from statistics import mean, stdev


def safe_power(base, exponent):
    if base <= 0:
        return None
    try:
        value = base ** exponent - 1
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def calculate(equity_curve, trades, orders, initial_cash, periods_per_year, start_time=None):
    if not equity_curve or initial_cash <= 0 or periods_per_year <= 0:
        raise ValueError("nonempty curve and positive capital/annualization required")
    values = [initial_cash] + [r["equity"] for r in equity_curve]
    if any(not math.isfinite(v) for v in values):
        raise ValueError("nonfinite equity")
    returns = [now/prev - 1 for prev,now in zip(values,values[1:]) if prev > 0]
    valid_returns = len(returns)==len(equity_curve)
    vol = stdev(returns) if valid_returns and len(returns)>1 else None
    downside = math.sqrt(mean([min(0,r)**2 for r in returns])) if valid_returns else None
    sharpe = mean(returns)/vol*math.sqrt(periods_per_year) if vol else None
    sortino = mean(returns)/downside*math.sqrt(periods_per_year) if downside else None
    peak, max_dd = initial_cash, 0.0
    for v in values:
        peak = max(peak,v)
        max_dd = max(max_dd,1-v/peak)
    net_return = values[-1]/initial_cash-1
    annualized = safe_power(values[-1]/initial_cash,periods_per_year/len(equity_curve))
    cagr = None
    if start_time is not None:
        start = datetime.fromisoformat(start_time) if isinstance(start_time,str) else start_time
        end = datetime.fromisoformat(equity_curve[-1]["timestamp"])
        years = (end-start).total_seconds()/(365.2425*86400)
        cagr = safe_power(values[-1]/initial_cash,1/years) if years>0 else None
    wins=[t["net_pnl"] for t in trades if t["net_pnl"]>0]
    losses=[t["net_pnl"] for t in trades if t["net_pnl"]<0]
    commission=sum(o["costs"]["commission"] for o in orders)
    spread=sum(o["costs"]["spread_cost"] for o in orders)
    slip=sum(o["costs"]["slippage_cost"] for o in orders)
    rounding=sum(o["costs"]["rounding_cost"] for o in orders)
    costs=commission+spread+slip+rounding
    m = {"total_return":net_return,"gross_total_return":(values[-1]+costs)/initial_cash-1,
         "annualized_return":annualized,"cagr":cagr,
         "annualized_volatility":vol*math.sqrt(periods_per_year) if vol is not None else None,
         "sharpe":sharpe,"sortino":sortino,"max_drawdown":max_dd,
         "calmar":annualized/max_dd if annualized is not None and max_dd else None,
         "number_of_trades":len(trades),"win_rate":len(wins)/len(trades) if trades else None,
         "average_win":mean(wins) if wins else None,"average_loss":mean(losses) if losses else None,
         "payoff_ratio":mean(wins)/abs(mean(losses)) if wins and losses else None,
         "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,
         "expectancy_per_trade":mean([t["net_pnl"] for t in trades]) if trades else None,
         "average_holding_bars":mean([t["holding_bars"] for t in trades]) if trades else None,
         "turnover":sum(o["size"]*o["costs"]["reference_price"] for o in orders)/initial_cash,
         "market_exposure":mean([r["position_bar_fraction"] for r in equity_curve]),
         "commission":commission,"spread_cost":spread,"slippage_cost":slip,
         "rounding_cost":rounding,"total_transaction_cost":costs,
         "open_position_count":1 if equity_curve[-1].get("position_size",0)>0 else 0,
         "risk_free_rate":0.0,"annualization_periods":periods_per_year,
         "metric_sampling":"completed decision-bar closes; initial capital included",
         "market_exposure_definition":"fraction of bars with any position (OHLC upper bound)"}
    return {k:(v if not isinstance(v,float) or math.isfinite(v) else None) for k,v in m.items()}
