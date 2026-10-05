"""Development boundary: warmup is causal; holdout is unavailable to scoring."""
from dataclasses import replace
from datetime import datetime
from .data import utc, validate


def select_window(data, window):
    start,end,holdout=(utc(datetime.fromisoformat(window[k])) for k in ('start','end','holdout_start'))
    if end>holdout or start>=holdout:
        raise ValueError('holdout access is blocked for development research')
    if start>=end:
        raise ValueError('research start must precede end')
    n=window['warmup_bars']
    if type(n) is not int or n<0:
        raise ValueError('nonnegative warmup_bars required')
    eligible=[i for i,b in enumerate(data.bars) if start<=b.open_time<holdout and b.close_time<=end]
    if not eligible:
        raise ValueError('research window has no complete bars')
    first,last=eligible[0],eligible[-1]
    rows=data.bars[max(0,first-n):last+1]
    schedule=tuple(p for p in data.policy.expected_intervals if rows[0].open_time<=p[0] and p[1]<=rows[-1].close_time)
    return validate(rows,replace(data.policy,expected_intervals=schedule)),start
