"""Strict explicit-interval OHLCV schema and supplied-calendar validation."""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import csv
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass(frozen=True)
class DataPolicy:
    source: str
    asset: str
    timeframe: str
    corporate_actions: str
    volume_supported: bool
    expected_intervals: tuple[tuple[datetime, datetime], ...]


@dataclass(frozen=True)
class Dataset:
    bars: tuple[Bar, ...]
    policy: DataPolicy
    fingerprint: str
    report: dict


class DataQualityError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(json.dumps(report, default=str))


def utc(t: datetime) -> datetime:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return t.astimezone(timezone.utc)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
                      allow_nan=False)


def validate(rows, policy: DataPolicy) -> Dataset:
    """Reject material errors; never sort, deduplicate, fill gaps or invent volume."""
    errors, normalized = [], []
    if not isinstance(policy.volume_supported,bool):
        errors.append("volume_supported must be an explicit boolean")
    if not all(isinstance(v, str) and v.strip() for v in
               (policy.source, policy.asset, policy.timeframe, policy.corporate_actions)):
        errors.append("source, asset, timeframe and corporate-action policy required")
    for i, b in enumerate(rows):
        try:
            b = replace(b, open_time=utc(b.open_time), close_time=utc(b.close_time))
        except (ValueError, TypeError) as exc:
            errors.append(f"bar {i}: {exc}")
            continue
        if b.open_time >= b.close_time:
            errors.append(f"bar {i}: open_time must precede close_time")
        values = (b.open, b.high, b.low, b.close)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v) and v > 0 for v in values):
            errors.append(f"bar {i}: nonfinite/nonpositive OHLC")
        elif not (b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high):
            errors.append(f"bar {i}: invalid OHLC relationship")
        if b.volume is None:
            if policy.volume_supported:
                errors.append(f"bar {i}: missing supported volume")
        elif not isinstance(b.volume, (int, float)) or isinstance(b.volume, bool) or not math.isfinite(b.volume) or b.volume < 0:
            errors.append(f"bar {i}: invalid volume")
        elif not policy.volume_supported:
            errors.append(f"bar {i}: volume supplied despite unsupported-volume policy")
        if normalized and (b.open_time < normalized[-1].close_time or
                           b.close_time <= normalized[-1].close_time):
            errors.append(f"bar {i}: unsorted, duplicate or overlapping interval")
        normalized.append(b)
    expected = []
    for i, interval in enumerate(policy.expected_intervals):
        try:
            a, z = map(utc, interval)
            if a >= z or (expected and a < expected[-1][1]):
                raise ValueError("invalid/overlapping expected schedule")
            expected.append((a, z))
        except (ValueError, TypeError) as exc:
            errors.append(f"expected interval {i}: {exc}")
    if not expected:
        errors.append("explicit expected schedule required")
    if not normalized:
        errors.append("empty dataset")
    actual = {(b.open_time, b.close_time) for b in normalized}
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    if missing:
        errors.append("missing expected bars")
    if unexpected:
        errors.append("bars outside supplied calendar")
    report = {"bar_count": len(normalized), "errors": errors,
              "missing_bars": [[a.isoformat(), z.isoformat()] for a, z in missing],
              "unexpected_bars": [[a.isoformat(), z.isoformat()] for a, z in unexpected],
              "volume_supported": policy.volume_supported,
              "timezone": "UTC", "source": policy.source,
              "corporate_actions": policy.corporate_actions}
    if errors:
        raise DataQualityError(report)
    policy = replace(policy, expected_intervals=tuple(expected))
    # Normalize number serialization so CSV round trips preserve the fingerprint.
    normalized = tuple(replace(b, open=float(b.open), high=float(b.high),
                               low=float(b.low), close=float(b.close),
                               volume=None if b.volume is None else float(b.volume)) for b in normalized)
    fingerprint = sha256(canonical({"bars": [asdict(b) for b in normalized],
                                    "policy": asdict(policy)}).encode()).hexdigest()
    return Dataset(normalized, policy, fingerprint, report)


def load_csv(path: str | Path) -> tuple[Bar, ...]:
    """timestamp is an optional alias that must equal explicit close_time."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"open_time", "close_time", "open", "high", "low", "close", "volume"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"CSV requires columns {sorted(required)}")
        for i, r in enumerate(reader, 2):
            try:
                end = datetime.fromisoformat(r["close_time"])
                if r.get("timestamp") and utc(datetime.fromisoformat(r["timestamp"])) != utc(end):
                    raise ValueError("timestamp must equal close_time")
                rows.append(Bar(datetime.fromisoformat(r["open_time"]), end,
                                *(float(r[k]) for k in ("open", "high", "low", "close")),
                                None if r["volume"].strip().lower() in {"", "null", "none"} else float(r["volume"])))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"CSV row {i}: {exc}") from exc
    return tuple(rows)


def load_schedule(path: str | Path) -> tuple[tuple[datetime, datetime], ...]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"open_time", "close_time"} <= set(reader.fieldnames or []):
            raise ValueError("schedule CSV requires open_time,close_time")
        return tuple((datetime.fromisoformat(r["open_time"]),
                      datetime.fromisoformat(r["close_time"])) for r in reader)


def completed(bars: tuple[Bar, ...], at: datetime) -> tuple[Bar, ...]:
    """Higher-timeframe visibility is controlled by actual close, not date label."""
    return tuple(b for b in bars if b.close_time <= at)
