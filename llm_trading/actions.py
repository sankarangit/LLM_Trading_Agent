"""Immutable distribution inputs; entitlement and cash payment are distinct."""
from dataclasses import dataclass
from datetime import datetime
import math
from .data import utc


@dataclass(frozen=True)
class Dividend:
    asset: str
    ex_time: datetime
    pay_time: datetime
    amount: float
    source: str


def validate_dividends(events, data):
    keys=set()
    opens={b.open_time for b in data.bars}
    for e in events:
        if not isinstance(e,Dividend) or e.asset!=data.policy.asset:
            raise ValueError('dividend asset mismatch')
        ex,pay=utc(e.ex_time),utc(e.pay_time)
        if pay<ex or not isinstance(e.amount,(int,float)) or isinstance(e.amount,bool) or not math.isfinite(e.amount) or e.amount<=0 or not e.source.strip():
            raise ValueError('invalid dividend amount, dates or source')
        if ex in keys:
            raise ValueError('duplicate dividend ex-date')
        keys.add(ex)
        if data.bars[0].open_time<=ex<=data.bars[-1].close_time and ex not in opens:
            raise ValueError('dividend entitlement must occur at a scheduled open')


def restore_dividends(rows):
    return tuple(Dividend(**{**r,'ex_time':datetime.fromisoformat(r['ex_time']),
                            'pay_time':datetime.fromisoformat(r['pay_time'])}) for r in rows)


def reconcile_dates(expected, observed):
    missing=set(expected)-set(observed)
    unexpected=set(observed)-set(expected)
    if missing or unexpected:
        raise ValueError(f'dividend date coverage: missing={sorted(missing)}, unexpected={sorted(unexpected)}')
