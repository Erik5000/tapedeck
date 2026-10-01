import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import crowding

TODAY = date(2026, 10, 1)


def hourly(rate, days=90, end="2026-09-30 23:00"):
    """``days`` whole calendar days of hourly funding; ``rate`` is a constant
    or a function of the row count."""
    idx = pd.date_range(end=end, periods=days * 24, freq="h")
    values = rate(len(idx)) if callable(rate) else rate
    return pd.Series(values, index=idx, dtype=float)


def test_funding_annualises_the_last_seven_days():
    out = crowding.funding_stats(hourly(0.00001))
    assert out["funding_ann"] == pytest.approx(0.00001 * 24 * 365 * 100)
    assert out["funding_days"] == 90


def test_funding_z_needs_sixty_days():
    assert crowding.funding_stats(hourly(lambda n: np.linspace(0, 1e-5, n), days=59))["funding_z"] is None
    assert crowding.funding_stats(hourly(lambda n: np.linspace(0, 1e-5, n), days=61))["funding_z"] > 1


def test_funding_z_drops_the_incomplete_last_day():
    base = hourly(lambda n: np.linspace(0, 1e-5, n), days=90)
    early_today = pd.Series(-1e-3, index=pd.date_range("2026-10-01 00:00", periods=6, freq="h"))
    s = pd.concat([base, early_today])
    out = crowding.funding_stats(s)
    assert out["funding_z"] == crowding.funding_stats(base)["funding_z"]
    assert out["funding_days"] == 90
    recent = s[s.index > s.index[-1] - pd.Timedelta(days=7)]     # funding_ann keeps today's hours
    assert out["funding_ann"] == pytest.approx(recent.mean() * 24 * 365 * 100)


def test_no_funding_is_none_not_zero():
    assert crowding.funding_stats(None) == {"funding_ann": None, "funding_z": None, "funding_days": 0}


@pytest.mark.parametrize("market,funding,side", [
    ("para:10Y", 5.0, "short duration crowded"),     # longs pay on a yield perp
    ("para:10Y", -5.0, "long duration crowded"),
    ("mkts:USBOND", 5.0, "long duration crowded"),   # longs pay on a bond
    ("xyz:TLT", -5.0, "short duration crowded"),
    ("xyz:BRENTOIL", 5.0, None),
    ("para:10Y", 0.0, None), ("para:10Y", None, None)])
def test_duration_side(market, funding, side):
    assert crowding.duration_side(market, funding) == side


def test_second_run_on_the_same_day_replaces_the_line(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY, {"para:10Y": 100.0})
    hist = crowding.update_history(path, TODAY, {"para:10Y": 120.0})
    assert hist == [{"date": "2026-10-01", "oi": {"para:10Y": 120.0}}]
    assert len(path.read_text().splitlines()) == 1


def test_no_oi_today_writes_no_line_but_keeps_history(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY - timedelta(days=1), {"para:10Y": 100.0})
    hist = crowding.update_history(path, TODAY, {})
    assert [r["date"] for r in hist] == ["2026-09-30"]


def test_unreadable_line_is_skipped_with_a_warning(tmp_path, capsys):
    path = tmp_path / "situation-history.jsonl"
    path.write_text('{"date": "2026-09-30", "oi": {"para:10Y": 100.0}}\n{"date": "2026-10\n')
    hist = crowding.load_history(path)
    assert [r["date"] for r in hist] == ["2026-09-30"]
    assert "line 2 unreadable" in capsys.readouterr().err
    crowding.update_history(path, TODAY, {"para:10Y": 110.0})
    capsys.readouterr()     # the update reads the bad line one last time
    assert len(path.read_text().splitlines()) == 2
    assert len(crowding.load_history(path)) == 2
    assert capsys.readouterr().err == ""


def test_a_partial_second_run_keeps_the_first_runs_values(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY, {"para:10Y": 100.0, "xyz:CL": 50.0})
    hist = crowding.update_history(path, TODAY, {"para:10Y": 120.0})
    assert hist == [{"date": "2026-10-01", "oi": {"para:10Y": 120.0, "xyz:CL": 50.0}}]
    assert crowding.load_history(path) == hist


def test_an_empty_second_run_keeps_todays_line(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY, {"para:10Y": 100.0})
    hist = crowding.update_history(path, TODAY, {})
    assert hist == [{"date": "2026-10-01", "oi": {"para:10Y": 100.0}}]
    assert crowding.load_history(path) == hist


def test_update_history_leaves_no_temp_file(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY, {"para:10Y": 100.0})
    assert [f.name for f in tmp_path.iterdir()] == ["situation-history.jsonl"]


def history(pairs):
    return [{"date": d.isoformat(), "oi": {"para:10Y": v}} for d, v in pairs]


def test_oi_change_against_twenty_days_back():
    hist = history([(TODAY - timedelta(days=20), 100.0), (TODAY, 125.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY) == (pytest.approx(25.0), 20)


def test_oi_change_warming_reports_days():
    hist = history([(TODAY - timedelta(days=3), 100.0), (TODAY, 125.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY) == (None, 3)
    assert crowding.oi_change([], "para:10Y", TODAY) == (None, 0)


def test_a_gap_in_days_uses_the_newest_line_before_the_cutoff():
    hist = history([(TODAY - timedelta(days=30), 80.0), (TODAY - timedelta(days=24), 100.0),
                    (TODAY - timedelta(days=5), 110.0), (TODAY, 120.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY)[0] == pytest.approx(20.0)


def test_build_crowding_statuses():
    ctx = {"para:10Y": {"oi": 125.0, "volume_24h": 1e6},
           "xyz:BRENTOIL": {"oi": 10.0, "volume_24h": 1e8}}
    funding = {"para:10Y": hourly(lambda n: np.linspace(0, 1e-5, n)),
               "xyz:BRENTOIL": hourly(0.00001, days=10)}
    hist = history([(TODAY - timedelta(days=20), 100.0), (TODAY, 125.0)])
    rows = {r["market"]: r for r in crowding.build_crowding(ctx, funding, hist, TODAY)}
    assert [r for r in rows] == [m for m, _ in crowding.CROWD_MARKETS]
    assert rows["para:10Y"]["status"] == "ok" and rows["para:10Y"]["panel"] == "rates"
    assert rows["para:10Y"]["side"] == "short duration crowded"
    assert rows["xyz:BRENTOIL"]["status"] == "warming"
    assert rows["xyz:BRENTOIL"]["note"] == "warming up: OI 0/20 days, funding 10/60 days"
    assert rows["xyz:CL"]["status"] == "no_data"
