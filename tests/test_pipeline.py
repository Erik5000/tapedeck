from datetime import date

import pandas as pd
import pytest

from bloom import pipeline

TODAY = date(2026, 7, 31)


def make_hist(n=260, start=100.0, end=200.0):
    idx = pd.bdate_range(end="2026-07-31", periods=n)
    step = (end - start) / (n - 1)
    close = pd.Series([start + step * i for i in range(n)], index=idx)
    return pd.DataFrame({
        "Open": close,
        "High": close + 2,
        "Low": close - 2,
        "Close": close,
        "Volume": pd.Series([1e6] * n, index=idx),
    })


def fixture_inputs():
    hists = {"NVDA": make_hist(end=200.0), "AMD": make_hist(end=150.0)}
    bench = make_hist(end=110.0)["Close"]
    infos = {
        "NVDA": {"name": "NVIDIA Corporation", "market_cap": 4.7e12, "ps": 18.6,
                 "pe": 29.0, "sector": "Technology", "earnings_date": "2026-08-26"},
        "AMD": {},
    }
    holdings = [
        {"ticker": "NVDA", "name": None, "group": "semis", "shares": 10.0, "cost_basis": 100.0},
        {"ticker": "AMD", "name": "AMD", "group": "semis", "shares": None, "cost_basis": None},
    ]
    return hists, bench, infos, holdings


def test_build_rows_basic_fields():
    hists, bench, infos, holdings = fixture_inputs()
    rows, summary = pipeline.build_rows(hists, bench, infos, holdings, TODAY)
    nvda = rows[0]
    assert nvda["ticker"] == "NVDA"
    assert nvda["name"] == "NVIDIA Corporation"  # falls back to info name
    assert nvda["price"] == pytest.approx(200.0)
    assert nvda["market_cap"] == pytest.approx(4.7e12)
    assert nvda["sma"]["200"]["above"] is True
    assert nvda["earnings_date"] == "2026-08-26"
    assert len(nvda["spark"]) > 10
    assert nvda["rs_rank"] == 1  # NVDA outperforms AMD vs bench


def test_build_rows_preserves_config_order():
    hists, bench, infos, holdings = fixture_inputs()
    rows, _ = pipeline.build_rows(hists, bench, infos, holdings, TODAY)
    assert [r["ticker"] for r in rows] == ["NVDA", "AMD"]


def test_build_rows_position_and_summary():
    hists, bench, infos, holdings = fixture_inputs()
    rows, summary = pipeline.build_rows(hists, bench, infos, holdings, TODAY)
    pos = rows[0]["position"]
    assert pos["market_value"] == pytest.approx(2000.0)
    assert pos["open_pnl"] == pytest.approx(1000.0)
    assert pos["weight_pct"] == pytest.approx(100.0)
    assert rows[1]["position"] is None
    assert summary["total_value"] == pytest.approx(2000.0)


def test_tv_symbol_exchange_mapping():
    assert pipeline.tv_symbol("NVDA", "NMS") == "NASDAQ:NVDA"
    assert pipeline.tv_symbol("BE", "NYQ") == "NYSE:BE"
    assert pipeline.tv_symbol("SPY", "PCX") == "AMEX:SPY"
    assert pipeline.tv_symbol("FOO", None) == "FOO"
    assert pipeline.tv_symbol("FOO", "WEIRD") == "FOO"
    assert pipeline.tv_symbol("NVDA", "NMS", override="BATS:NVDA") == "BATS:NVDA"


def test_build_rows_sets_tv_symbol():
    hists, bench, infos, holdings = fixture_inputs()
    infos["NVDA"]["exchange"] = "NMS"
    holdings[1]["tv_symbol"] = "NYSE:AMD"  # config override wins
    rows, _ = pipeline.build_rows(hists, bench, infos, holdings, TODAY)
    assert rows[0]["tv_symbol"] == "NASDAQ:NVDA"
    assert rows[1]["tv_symbol"] == "NYSE:AMD"


def test_build_rows_tv_overrides_snapshot_fields():
    hists, bench, infos, holdings = fixture_inputs()
    holdings[0]["name"] = "My NVDA"  # explicit config name must survive
    tv = {"NVDA": {"name": "NVIDIA Corporation", "price": 210.0, "pct_1d": 5.0,
                   "ps": 19.9, "pct_ytd": 2.74, "tv_symbol": "NASDAQ:NVDA",
                   "sector": "Electronic Technology"}}
    rows, _ = pipeline.build_rows(hists, bench, infos, holdings, TODAY, tv=tv)
    nvda = rows[0]
    assert nvda["price"] == pytest.approx(210.0)
    assert nvda["pct_1d"] == pytest.approx(5.0)
    assert nvda["ps"] == pytest.approx(19.9)
    assert nvda["name"] == "My NVDA"
    assert nvda["sector"] == "Electronic Technology"
    assert nvda["spark"]  # history-derived fields untouched
    # position uses the TV price against history prev close
    assert nvda["position"]["market_value"] == pytest.approx(2100.0)


def test_build_rows_tv_symbol_override_precedence():
    hists, bench, infos, holdings = fixture_inputs()
    holdings[0]["tv_symbol"] = "BATS:NVDA"
    tv = {"NVDA": {"tv_symbol": "NASDAQ:NVDA"}}
    rows, _ = pipeline.build_rows(hists, bench, infos, holdings, TODAY, tv=tv)
    assert rows[0]["tv_symbol"] == "BATS:NVDA"


def test_build_rows_missing_history_degrades():
    hists, bench, infos, holdings = fixture_inputs()
    del hists["AMD"]
    rows, _ = pipeline.build_rows(hists, bench, infos, holdings, TODAY)
    amd = rows[1]
    assert amd["price"] is None
    assert amd["spark"] == []
    assert amd["sma"] == {}
    assert amd["position"] is None
