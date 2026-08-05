from datetime import date

import pandas as pd
import pytest

from tapedeck import pipeline

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


# ---------- namespaced fetch keys ----------

def test_rows_look_up_history_by_key_not_ticker():
    """A venue holding's history lives under xyz:NVDA while the row still
    displays NVDA — looking up by ticker would silently produce an empty row."""
    hists = {"xyz:NVDA": make_hist(end=200.0)}
    holdings = [{"ticker": "NVDA", "key": "xyz:NVDA", "source": "hyperliquid",
                 "name": None, "group": None, "shares": None, "cost_basis": None,
                 "tv_symbol": None}]
    rows, _ = pipeline.build_rows(hists, None, {}, holdings, TODAY)
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["price"] == pytest.approx(200.0)


def test_the_same_ticker_on_two_sources_gets_its_own_prices():
    """The whole reason keys are namespaced: NVDA in a Yahoo list and NVDA on
    trade.xyz are two different instruments in one run."""
    hists = {"NVDA": make_hist(end=200.0), "xyz:NVDA": make_hist(end=333.0)}
    base = {"name": None, "group": None, "shares": None, "cost_basis": None, "tv_symbol": None}
    yahoo, = pipeline.build_rows(
        hists, None, {}, [dict(base, ticker="NVDA", key="NVDA", source="yahoo")], TODAY)[0]
    venue, = pipeline.build_rows(
        hists, None, {}, [dict(base, ticker="NVDA", key="xyz:NVDA",
                               source="hyperliquid")], TODAY)[0]
    assert yahoo["price"] == pytest.approx(200.0)
    assert venue["price"] == pytest.approx(333.0)


def test_holdings_without_a_key_still_resolve_by_ticker():
    """Back-compat for callers that build holdings by hand (tests, --config)."""
    hists = {"NVDA": make_hist(end=200.0)}
    holdings = [{"ticker": "NVDA", "name": None, "group": None, "shares": None,
                 "cost_basis": None, "tv_symbol": None}]
    rows, _ = pipeline.build_rows(hists, None, {}, holdings, TODAY)
    assert rows[0]["price"] == pytest.approx(200.0)


def test_venue_rows_take_fundamentals_from_tradingview_but_never_prices():
    """A venue row's price is a 24/7 perp mark. Letting the screener's spot
    close overwrite it would put two different instruments in one row."""
    hists = {"xyz:NVDA": make_hist(end=200.0)}
    tv = {"NVDA": {"price": 999.0, "pct_1d": 42.0, "market_cap": 4.7e12,
                   "sector": "Technology", "earnings_date": "2026-08-26"}}
    holdings = [{"ticker": "NVDA", "key": "xyz:NVDA", "source": "hyperliquid",
                 "equity": "NVDA", "name": None, "group": None, "shares": None,
                 "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["price"] == pytest.approx(200.0)        # venue, not 999
    assert row["pct_1d"] != pytest.approx(42.0)
    assert row["market_cap"] == 4.7e12                 # fundamentals do come through
    assert row["sector"] == "Technology"
    assert row["earnings_date"] == "2026-08-26"        # keeps earnings alerts working


def test_venue_market_without_a_declared_equity_takes_no_fundamentals():
    """The venue's GOLD is bullion; NYSE GOLD is Barrick Mining. Its CL is WTI
    crude; NYSE CL is Colgate-Palmolive. Matching on the bare symbol handed
    crude oil a market cap and an earnings date, which then fired an earnings
    alert for a barrel of oil."""
    hists = {"xyz:CL": make_hist(end=75.0)}
    tv = {"CL": {"market_cap": 7.2e10, "sector": "Consumer Defensive",
                 "earnings_date": "2026-08-07", "name": "Colgate-Palmolive"}}
    holdings = [{"ticker": "CL", "key": "xyz:CL", "source": "hyperliquid",
                 "equity": None, "name": "WTI Crude", "group": "energy",
                 "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["market_cap"] is None
    assert row["sector"] is None
    assert row["earnings_date"] is None
    assert row["name"] == "WTI Crude"                  # the watchlist's own name wins
    assert row["price"] == pytest.approx(75.0)


def test_venue_equity_lookup_is_independent_of_the_venue_symbol():
    """SKHX on the venue is SK hynix; the fundamentals key need not match."""
    hists = {"xyz:SKHX": make_hist(end=1170.0)}
    tv = {"SKHX": {"market_cap": 1.0, "sector": "WRONG"},
          "000660.KS": {"market_cap": 9.9e11, "sector": "Technology"}}
    holdings = [{"ticker": "SKHX", "key": "xyz:SKHX", "source": "hyperliquid",
                 "equity": "000660.KS", "name": None, "group": None,
                 "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["market_cap"] == 9.9e11
    assert row["sector"] == "Technology"


def test_yahoo_rows_still_take_prices_from_tradingview():
    """The screener override is the documented default for Yahoo lists."""
    hists = {"NVDA": make_hist(end=200.0)}
    tv = {"NVDA": {"price": 999.0, "market_cap": 1.0}}
    holdings = [{"ticker": "NVDA", "key": "NVDA", "source": "yahoo", "name": None,
                 "group": None, "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["price"] == 999.0
