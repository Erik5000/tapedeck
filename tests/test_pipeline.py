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
                 "ref": "NVDA", "name": None, "group": None, "shares": None,
                 "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["price"] == pytest.approx(200.0)        # venue, not 999
    assert row["pct_1d"] != pytest.approx(42.0)
    assert row["market_cap"] == 4.7e12                 # fundamentals do come through
    assert row["sector"] == "Technology"
    assert row["earnings_date"] == "2026-08-26"        # keeps earnings alerts working


def test_venue_market_without_a_declared_ref_takes_no_fundamentals():
    """The venue's GOLD is bullion; NYSE GOLD is Barrick Mining. Its CL is WTI
    crude; NYSE CL is Colgate-Palmolive. Matching on the bare symbol handed
    crude oil a market cap and an earnings date, which then fired an earnings
    alert for a barrel of oil."""
    hists = {"xyz:CL": make_hist(end=75.0)}
    tv = {"CL": {"market_cap": 7.2e10, "sector": "Consumer Defensive",
                 "earnings_date": "2026-08-07", "name": "Colgate-Palmolive"}}
    holdings = [{"ticker": "CL", "key": "xyz:CL", "source": "hyperliquid",
                 "ref": None, "name": "WTI Crude", "group": "energy",
                 "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["market_cap"] is None
    assert row["sector"] is None
    assert row["earnings_date"] is None
    assert row["name"] == "WTI Crude"                  # the watchlist's own name wins
    assert row["price"] == pytest.approx(75.0)


def test_venue_ref_lookup_is_independent_of_the_venue_symbol():
    """SKHX on the venue is SK hynix; the fundamentals key need not match."""
    hists = {"xyz:SKHX": make_hist(end=1170.0)}
    tv = {"SKHX": {"market_cap": 1.0, "sector": "WRONG"},
          "000660.KS": {"market_cap": 9.9e11, "sector": "Technology"}}
    holdings = [{"ticker": "SKHX", "key": "xyz:SKHX", "source": "hyperliquid",
                 "ref": "000660.KS", "name": None, "group": None,
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


# ---------- TradingView chart symbols ----------

def test_venue_rows_chart_the_perp_not_a_proxy():
    """trade.xyz lists its markets on TradingView as HIP3XYZ:<SYM>USDC.P. The
    bare ticker resolved to nothing at all ("SOFTBANK" → symbol doesn't exist),
    and an equity proxy is a delayed feed of a different instrument."""
    assert pipeline.tv_symbol("NVDA", None, source="hyperliquid") == "HIP3XYZ:NVDAUSDC.P"
    assert pipeline.tv_symbol("GOLD", None, source="hyperliquid") == "HIP3XYZ:GOLDUSDC.P"
    assert pipeline.tv_symbol("SOFTBANK", None, source="hyperliquid") == "HIP3XYZ:SOFTBANKUSDC.P"


def test_venue_chart_symbol_handles_the_one_naming_mismatch():
    """TradingView follows trade.xyz's docs naming (SKHYNIX) where the API says
    SKHX — the same docs/API split that affects SMSN and CL."""
    assert pipeline.tv_symbol("SKHX", None, source="hyperliquid") == "HIP3XYZ:SKHYNIXUSDC.P"
    assert pipeline.tv_symbol("SKHY", None, source="hyperliquid") == "HIP3XYZ:SKHYUSDC.P"


def test_unknown_dex_does_not_invent_a_prefix():
    """Only xyz has been verified on TradingView. Guessing a prefix would put
    'symbol doesn't exist' in the panel instead of degrading quietly."""
    assert pipeline.tv_symbol("NVDA", None, source="hyperliquid", dex="flx") == "NVDA"


def test_explicit_tv_symbol_still_wins_for_a_venue_row():
    assert pipeline.tv_symbol("SKHX", None, override="KRX:000660",
                              source="hyperliquid") == "KRX:000660"


def test_yahoo_chart_symbols_are_unchanged():
    assert pipeline.tv_symbol("NVDA", "NMS") == "NASDAQ:NVDA"
    assert pipeline.tv_symbol("SPY", "PCX") == "AMEX:SPY"
    assert pipeline.tv_symbol("SAP.DE", "GER") == "SAP.DE"


def test_screener_cannot_replace_a_venue_rows_chart_symbol():
    """The screener returns the equity's symbol. On a venue row that would swap
    the perp chart for a delayed spot chart of a different instrument."""
    hists = {"xyz:NVDA": make_hist(end=200.0)}
    tv = {"NVDA": {"tv_symbol": "NASDAQ:NVDA", "market_cap": 4.7e12}}
    holdings = [{"ticker": "NVDA", "key": "xyz:NVDA", "source": "hyperliquid",
                 "dex": "xyz", "ref": "NVDA", "name": None, "group": None,
                 "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["tv_symbol"] == "HIP3XYZ:NVDAUSDC.P"
    assert row["market_cap"] == 4.7e12      # fundamentals still come through


def test_screener_still_supplies_tv_symbol_for_yahoo_rows():
    hists = {"NVDA": make_hist(end=200.0)}
    tv = {"NVDA": {"tv_symbol": "NASDAQ:NVDA"}}
    holdings = [{"ticker": "NVDA", "key": "NVDA", "source": "yahoo", "name": None,
                 "group": None, "shares": None, "cost_basis": None, "tv_symbol": None}]
    row, = pipeline.build_rows(hists, None, {}, holdings, TODAY, tv=tv)[0]
    assert row["tv_symbol"] == "NASDAQ:NVDA"


def test_every_live_venue_symbol_maps_to_a_known_tradingview_symbol():
    """Pins the shape against the 88 symbols enumerated from TradingView's
    HIP3XYZ exchange: <API symbol>USDC.P, with SKHX aliased to SKHYNIX.
    A new alias appearing upstream shows up here rather than as an empty chart.

    The list is a fixture, not a live call — the suite makes no network
    requests. Refresh it from TradingView's symbol search if the venue's
    naming changes.
    """
    sample = {
        "NVDA": "HIP3XYZ:NVDAUSDC.P", "GOLD": "HIP3XYZ:GOLDUSDC.P",
        "CL": "HIP3XYZ:CLUSDC.P", "SP500": "HIP3XYZ:SP500USDC.P",
        "XYZ100": "HIP3XYZ:XYZ100USDC.P", "BRENTOIL": "HIP3XYZ:BRENTOILUSDC.P",
        "SPCX": "HIP3XYZ:SPCXUSDC.P", "DRAM": "HIP3XYZ:DRAMUSDC.P",
        "SOFTBANK": "HIP3XYZ:SOFTBANKUSDC.P",   # the one that read "symbol doesn't exist"
        "SKHX": "HIP3XYZ:SKHYNIXUSDC.P", "SKHY": "HIP3XYZ:SKHYUSDC.P",
    }
    for symbol, expected in sample.items():
        assert pipeline.tv_symbol(symbol, None, source="hyperliquid") == expected, symbol


# ---------- reference instruments ----------
#
# A venue market is months old and its venue publishes no fundamentals. The
# reference is a Yahoo instrument for the same underlying (285A.T for KIOXIA,
# GC=F for GOLD) that fills what the primary source cannot.

def venue(ticker, ref, **over):
    base = {"ticker": ticker, "key": f"xyz:{ticker}", "source": "hyperliquid",
            "dex": "xyz", "ref": ref, "name": None, "group": None,
            "shares": None, "cost_basis": None, "tv_symbol": None}
    base.update(over)
    return base


def test_reference_fills_fundamentals_a_us_screener_cannot_see():
    """The TradingView screener is america-only, so it has nothing at all for
    285A.T — which is exactly why Kioxia's row was entirely n/a."""
    hists = {"xyz:KIOXIA": make_hist(n=90, end=345.0), "285A.T": make_hist(n=260)}
    infos = {"285A.T": {"name": "KIOXIA HOLDINGS", "market_cap": 29_715e9,
                        "currency": "JPY", "pe": 50.8, "sector": "Technology"}}
    row, = pipeline.build_rows(hists, None, infos, [venue("KIOXIA", "285A.T")],
                               TODAY, rates={"JPY=X": 158.0})[0]
    assert row["market_cap"] == pytest.approx(29_715e9 / 158.0)
    assert row["pe"] == 50.8
    assert row["sector"] == "Technology"
    assert row["borrowed"]["market_cap"] == "285A.T"


def test_reference_fills_the_year_scale_metrics_a_young_market_cannot():
    hists = {"xyz:GOLD": make_hist(n=90, end=4158.0), "GC=F": make_hist(n=260, end=4216.0)}
    row, = pipeline.build_rows(hists, None, {}, [venue("GOLD", "GC=F")], TODAY)[0]
    assert row["pct_1y"] is not None
    assert row["pct_off_high"] is not None
    assert row["sma"]["200"] is not None
    assert row["borrowed"]["pct_1y"] == "GC=F"
    assert row["borrowed"]["sma200"] == "GC=F"


def test_native_values_are_never_replaced_by_the_reference():
    """Only gaps are filled, so a market stops borrowing on its own once it has
    accrued history — and the price you trade is never overwritten."""
    hists = {"xyz:NVDA": make_hist(n=260, end=217.0), "NVDA": make_hist(n=260, end=999.0)}
    row, = pipeline.build_rows(hists, None, {}, [venue("NVDA", "NVDA")], TODAY)[0]
    assert row["price"] == pytest.approx(217.0)          # venue, not the reference
    assert "pct_1y" not in row["borrowed"]               # native series was long enough
    assert "pct_off_high" not in row["borrowed"]
    assert "sma200" not in row["borrowed"]


def test_price_and_short_horizon_metrics_are_never_borrowed():
    """These describe the contract being traded. Borrowing the 20/50SMA would
    make the arrows disagree with the user's own chart."""
    hists = {"xyz:SMSN": make_hist(n=120, end=170.0), "005930.KS": make_hist(n=260, end=246000.0)}
    row, = pipeline.build_rows(hists, None, {}, [venue("SMSN", "005930.KS")], TODAY)[0]
    assert row["price"] == pytest.approx(170.0)
    for key in ("price", "pct_1d", "gap_pct", "rs_1m", "rel_vol", "atr_pct"):
        assert key not in row["borrowed"], key
    assert "20" in row["sma"] and "50" in row["sma"]
    assert row["borrowed"].get("sma20") is None


def test_market_cap_is_dropped_when_no_rate_is_available():
    """n/a beats a KRW figure rendered in a dollar column."""
    hists = {"xyz:SMSN": make_hist(n=90), "005930.KS": make_hist(n=260)}
    infos = {"005930.KS": {"market_cap": 1_615_375e9, "currency": "KRW", "pe": 12.0}}
    row, = pipeline.build_rows(hists, None, infos, [venue("SMSN", "005930.KS")],
                               TODAY, rates={})[0]
    assert row["market_cap"] is None
    assert "market_cap" not in row["borrowed"]
    assert row["pe"] == 12.0            # ratios are currency-free, so they survive


def test_the_1y_sparkline_comes_from_the_reference_when_the_series_is_short():
    """The column is headed 1Y — a nine-month line under it is a quiet lie."""
    hists = {"xyz:SMSN": make_hist(n=120), "005930.KS": make_hist(n=260)}
    row, = pipeline.build_rows(hists, None, {}, [venue("SMSN", "005930.KS")], TODAY)[0]
    assert row["borrowed"]["spark"] == "005930.KS"


def test_a_market_with_no_reference_keeps_its_gaps():
    """SPCX is pre-IPO: there is nothing public to borrow, and an empty cell
    beats one filled from something else."""
    hists = {"xyz:SPCX": make_hist(n=80, end=111.0)}
    row, = pipeline.build_rows(hists, None, {}, [venue("SPCX", None)], TODAY)[0]
    assert row["price"] == pytest.approx(111.0)
    assert row["pct_1y"] is None and row["pct_off_high"] is None
    assert row["market_cap"] is None
    assert row["borrowed"] == {}


def test_a_missing_reference_history_degrades_quietly():
    hists = {"xyz:KIOXIA": make_hist(n=90)}
    infos = {"285A.T": {"market_cap": 1e12, "currency": "USD"}}
    row, = pipeline.build_rows(hists, None, infos, [venue("KIOXIA", "285A.T")], TODAY)[0]
    assert row["market_cap"] == pytest.approx(1e12)   # info still lands
    assert row["pct_1y"] is None                      # no history to borrow from
