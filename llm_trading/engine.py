"""Completed-bar event loop. Strategy sees immutable past-only snapshots."""
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Callable
import math
from zoneinfo import ZoneInfo
from .data import Dataset, completed, validate
from .types import Context, Decision, ExecutionConfig, RiskConfig, Strategy
from .execution import costed_fill, validate_execution
from .portfolio import Portfolio
from .risk import RiskEngine, validate_risk
from .actions import Dividend, validate_dividends
from .data import utc


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float
    seed: int
    periods_per_year: float
    daily_timezone: str
    risk: RiskConfig
    execution: ExecutionConfig
    dividends: tuple[Dividend, ...] = ()
    trade_start: datetime | None = None


@dataclass
class Result:
    decisions: list[dict]
    orders: list[dict]
    trades: list[dict]
    equity_curve: list[dict]
    dataset_fingerprint: str
    corporate_actions: list[dict] = field(default_factory=list)


def audit_value(value):
    """Preserve rejected nonfinite numeric inputs as explicit JSON-safe evidence."""
    if isinstance(value,float) and not math.isfinite(value):
        return "NONFINITE:"+str(value)
    if isinstance(value,dict):
        return {k:audit_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [audit_value(v) for v in value]
    return value


def run(data: Dataset, strategy: Strategy, config: BacktestConfig,
        higher_data: Dataset | None = None, feature_fn: Callable | None = None) -> Result:
    validate_execution(config.execution)
    validate_risk(config.risk)
    if not all(isinstance(x, (int,float)) and not isinstance(x,bool) and math.isfinite(x) and x > 0
               for x in (config.initial_cash,config.periods_per_year)):
        raise ValueError("positive initial_cash and periods_per_year required")
    if type(config.seed) is not int:
        raise ValueError("explicit integer seed required")
    ZoneInfo(config.daily_timezone)
    validate_dividends(config.dividends,data)
    trade_start=utc(config.trade_start) if config.trade_start is not None else data.bars[0].open_time
    if not any(b.open_time>=trade_start for b in data.bars):
        raise ValueError('trade_start leaves no scored bars')
    dividend_opens={e.ex_time:e for e in config.dividends}
    # No manually constructed Dataset can bypass its validation boundary.
    checked = validate(data.bars,data.policy)
    if checked.fingerprint != data.fingerprint:
        raise ValueError("dataset fingerprint mismatch")
    if higher_data:
        if higher_data.policy.asset != data.policy.asset:
            raise ValueError("higher-timeframe asset must match decision asset")
        higher_checked = validate(higher_data.bars,higher_data.policy)
        if higher_checked.fingerprint != higher_data.fingerprint:
            raise ValueError("higher dataset fingerprint mismatch")
    portfolio = Portfolio(config.initial_cash, config.daily_timezone)
    risk = RiskEngine(config.risk, config.execution)
    result = Result([], [], [], [], data.fingerprint)
    pending = None
    forced = None

    def close_position(reference, at, index, reason, bounded=False, decision_id=None):
        p = portfolio.position
        fill = costed_fill(reference,p.size,-p.side,config.execution)
        result.orders.append({"order_id":len(result.orders)+1, "decision_id":decision_id,
                              "signal_timestamp":(data.bars[index-1].close_time.isoformat()
                                                   if reason in {"daily_loss","max_drawdown","time_stop"} and index else None),
                              "fill_timestamp":at.isoformat(), "action":"CLOSE", "size":fill.size,
                              "fill_price":fill.price,"reason":reason,"costs":asdict(fill)})
        result.trades.append(portfolio.exit(fill,at,index,reason,bounded))

    for i,b in enumerate(data.bars):
        if b.open_time<trade_start:
            continue
        event=dividend_opens.get(b.open_time)
        if event:
            record=portfolio.accrue_dividend(event)
            if record:
                result.corporate_actions.append(record)
        # Payments available before this open were settled at the prior close.
        # A payment time in an overnight gap settles at this first later open.
        result.corporate_actions.extend(portfolio.pay_dividends(b.open_time))
        opening_account = portfolio.mark(b.open,b.open_time)
        opening_kill = risk.observe(opening_account,portfolio.day,portfolio.daily_start)
        forced = opening_kill or forced
        # Resting stops honor overnight gaps before market decisions can cancel them.
        p = portfolio.position
        if p and ((p.side==1 and b.open <= p.stop) or (p.side==-1 and b.open >= p.stop)):
            close_position(b.open,b.open_time,i,"stop_gap")
        elif p and p.target is not None and ((p.side==1 and b.open >= p.target) or
                                             (p.side==-1 and b.open <= p.target)):
            close_position(b.open,b.open_time,i,"target_gap")
        if forced and portfolio.position:
            close_position(b.open,b.open_time,i,forced)
        forced = None
        if pending:
            d, record = pending
            a = portfolio.mark(b.open,b.open_time)
            risk.observe(a,portfolio.day,portfolio.daily_start)
            evaluation = risk.evaluate(d,a,b.open)
            record["execution_risk_result"] = asdict(evaluation)
            if evaluation.allowed and d.action in {"LONG","SHORT"}:
                fill = costed_fill(b.open,evaluation.size,1 if d.action=="LONG" else -1,config.execution)
                portfolio.enter(fill,d,data.bars[i-1].close_time,b.open_time,i)
                result.orders.append({"order_id":len(result.orders)+1,"decision_id":record["decision_id"],
                                      "signal_timestamp":record["decision_timestamp"],
                                      "fill_timestamp":b.open_time.isoformat(),"action":d.action,
                                      "size":fill.size,"fill_price":fill.price,"reason":"entry","costs":asdict(fill)})
                record["order_status"] = "filled"
            elif evaluation.allowed and d.action=="CLOSE":
                close_position(b.open,b.open_time,i,"model_or_strategy_close",decision_id=record["decision_id"])
                record["order_status"] = "filled"
            else:
                record["order_status"] = "rejected_at_execution"
            pending = None
        # Mark actual fill costs before intrabar stop evaluation.
        # New tight stops can be immediately marketable after adverse entry costs.
        # The only attainable reference then is this open, not the stop beyond it.
        p = portfolio.position
        if p and ((p.side==1 and b.open <= p.stop) or (p.side==-1 and b.open >= p.stop)):
            close_position(b.open,b.open_time,i,"stop_gap")
        a = portfolio.mark(b.open,b.open_time)
        kill = risk.observe(a,portfolio.day,portfolio.daily_start)
        if kill and portfolio.position:
            close_position(b.open,b.open_time,i,kill)
        p = portfolio.position
        if p:
            stop_hit = b.low <= p.stop if p.side==1 else b.high >= p.stop
            target_hit = p.target is not None and (b.high >= p.target if p.side==1 else b.low <= p.target)
            if stop_hit and target_hit and config.execution.ambiguity_policy=="reject":
                raise ValueError("ambiguous stop/target bar; finer data required")
            if stop_hit or target_hit:
                close_position(p.stop if stop_hit else p.target,b.close_time,i,
                               "stop" if stop_hit else "target",True)
        result.corporate_actions.extend(portfolio.pay_dividends(b.close_time))
        a = portfolio.mark(b.close,b.close_time)
        kill = risk.observe(a,portfolio.day,portfolio.daily_start)
        if kill and portfolio.position:
            forced = kill
        p = portfolio.position
        if p and p.horizon and i - p.entry_bar + 1 >= p.horizon:
            forced = forced or "time_stop"
        if p and p.trailing_pct:
            trailing = b.close * (1-p.side*p.trailing_pct/100)
            p.stop = max(p.stop,trailing) if p.side==1 else min(p.stop,trailing)
        visible = data.bars[:i+1]
        higher = completed(higher_data.bars,b.close_time) if higher_data else ()
        features = tuple(sorted((feature_fn(visible,higher) if feature_fn else {}).items()))
        context = Context(b.close_time,visible,higher,a,features)
        decision = strategy.decide(context)
        evaluation = risk.evaluate(decision,a,b.close)
        record = {"decision_id":i+1,"decision_timestamp":b.close_time.isoformat(),
                  "visible_data_end":visible[-1].close_time.isoformat(),
                  "higher_visible_end":higher[-1].close_time.isoformat() if higher else None,
                  "feature_snapshot":dict(features),"account_snapshot":asdict(a),
                  "decision":audit_value(asdict(decision)) if isinstance(decision,Decision) else {"action":"INVALID","raw_type":type(decision).__name__},
                  "risk_result":asdict(evaluation),
                  "risk_rejection_reason":None if evaluation.allowed else evaluation.reason,
                  "order_status":"pending" if evaluation.allowed and isinstance(decision,Decision) and decision.action!="HOLD" else "no_order"}
        result.decisions.append(record)
        if evaluation.allowed and isinstance(decision,Decision) and decision.action!="HOLD":
            pending = (decision,record)
        result.equity_curve.append({"timestamp":b.close_time.isoformat(),**asdict(a),
                                    "position_bar_fraction":1.0 if p else
                                    (1.0 if any(t["exit_timestamp"]==b.close_time.isoformat() and
                                                t["intrabar_timestamp_is_bound"] for t in result.trades[-1:]) else 0.0)})
    if pending:
        pending[1]["order_status"] = "expired_end_of_data"
    return result
