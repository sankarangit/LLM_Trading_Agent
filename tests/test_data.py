from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import pytest

from llm_trading.data import Bar, Dataset, DataQualityError, DataPolicy, validate


def bars():
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return tuple(Bar(t + timedelta(hours=i), t + timedelta(hours=i + 1),
                     100, 102, 98, 101, 1000) for i in range(3))


def policy(rows=None, **kwargs):
    rows = rows or bars()
    return DataPolicy(source="test-fixture", asset="TEST", timeframe="1h",
                      corporate_actions="not_applicable", volume_supported=True,
                      expected_intervals=tuple((b.open_time, b.close_time) for b in rows),
                      **kwargs)


def test_accepts_valid_data_and_records_fingerprint():
    data = validate(bars(), policy())
    assert isinstance(data, Dataset)
    assert data.report["bar_count"] == 3
    assert data.report["missing_bars"] == []
    assert len(data.fingerprint) == 64
    changed = list(bars())
    changed[0] = replace(changed[0], close=100.5)
    assert validate(changed, policy()).fingerprint != data.fingerprint
    assert validate(bars(), policy()).fingerprint == data.fingerprint


@pytest.mark.parametrize("field,value", [("close",103), ("low",101),
                                         ("open",0), ("high",math.inf),
                                         ("volume",-1), ("close",math.nan)])
def test_material_invalid_prices_fail(field, value):
    rows = list(bars())
    rows[1] = replace(rows[1], **{field: value})
    with pytest.raises(DataQualityError):
        validate(rows, policy())


def test_duplicates_unsorted_and_overlapping_fail():
    for rows in [bars() + (bars()[-1],), bars()[::-1],
                 (bars()[0], replace(bars()[1], open_time=bars()[0].open_time))]:
        with pytest.raises(DataQualityError):
            validate(rows, policy())


def test_missing_bar_is_reported_and_run_rejected():
    with pytest.raises(DataQualityError) as exc:
        validate((bars()[0], bars()[2]), policy())
    assert len(exc.value.report["missing_bars"]) == 1


def test_null_volume_is_explicit_and_never_fabricated():
    rows = tuple(replace(b, volume=None) for b in bars())
    data = validate(rows, replace(policy(), volume_supported=False))
    assert data.bars[0].volume is None
    with pytest.raises(DataQualityError):
        validate(rows, policy())


def test_naive_timestamps_fail_and_aware_times_normalize():
    rows = tuple(replace(b, open_time=b.open_time.replace(tzinfo=None)) for b in bars())
    with pytest.raises(DataQualityError):
        validate(rows, policy())
    zone = timezone(timedelta(hours=8))
    rows = tuple(replace(b, open_time=b.open_time.astimezone(zone),
                         close_time=b.close_time.astimezone(zone)) for b in bars())
    assert validate(rows, policy()).fingerprint == validate(bars(), policy()).fingerprint


def test_source_and_corporate_actions_required():
    with pytest.raises(DataQualityError):
        validate(bars(), replace(policy(), corporate_actions=""))
    with pytest.raises(DataQualityError):
        validate(bars(), replace(policy(), source=""))


def test_expected_schedule_is_required_and_unexpected_bars_fail():
    with pytest.raises(DataQualityError):
        validate(bars(), replace(policy(), expected_intervals=()))
    with pytest.raises(DataQualityError):
        validate(bars(), replace(policy(), expected_intervals=policy().expected_intervals[:2]))


def test_volume_support_must_be_an_explicit_boolean():
    for value in (None,"false",0,1):
        with pytest.raises(DataQualityError):
            validate(bars(),replace(policy(),volume_supported=value))
