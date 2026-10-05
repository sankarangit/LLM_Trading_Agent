"""Regression coverage for the fresh Windows virtualenv and temp ownership."""
from dataclasses import replace
from pathlib import Path
import pytest
from test_engine import dataset, cfg, Scripted
from llm_trading.engine import run
from llm_trading.types import Decision


def test_named_daily_timezone_resets_at_local_midnight_on_windows():
    d=dataset([(100,100),(100,98),(98,98),(98,98),(98,98)])
    r=run(d,Scripted({0:Decision("LONG",stop_distance_pct=5)}),
          replace(cfg(),daily_timezone="America/New_York"))
    assert r.equity_curve[1]["daily_pnl"]==-20
    assert r.equity_curve[3]["daily_pnl"]==-20
    # 05:00 UTC is 00:00 New York in January.
    assert r.equity_curve[4]["daily_pnl"]==0


def test_default_test_artifacts_use_project_local_isolated_directory(tmp_path,pytestconfig):
    project=Path(__file__).resolve().parents[1]
    base=Path(pytestconfig.option.basetemp).resolve() if pytestconfig.option.basetemp else None
    assert base is not None, "shared OS pytest temp root must not be used by default"
    if base.parent!=project/".test-tmp":
        pytest.skip("Caller supplied an explicit --basetemp; default placement is inapplicable")
    assert base.parent==project/".test-tmp"
    assert tmp_path.is_relative_to(base)
    marker=tmp_path/"write-probe.txt"
    marker.write_text("writable",encoding="utf-8")
    assert marker.read_text(encoding="utf-8")=="writable"
