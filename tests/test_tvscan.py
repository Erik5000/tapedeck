import pytest

from tapedeck import tvscan


def entry(symbol, values):
    return {"s": symbol, "d": values}


def make_d(**overrides):
    base = {
        "name": "NVDA", "description": "NVIDIA Corporation", "exchange": "NASDAQ",
        "type": "stock", "close": 195.04, "change": 2.647, "market_cap_basic": 4.72e12,
        "price_earnings_ttm": 29.87, "price_sales_current": 18.28, "Perf.YTD": 2.74,
        "price_52_week_high": 236.54, "ATR": 7.507, "relative_volume_10d_calc": 1.02,
        "sector": "Electronic Technology", "earnings_release_next_date": 1787774400,
    }
    base.update(overrides)
    return [base[c] for c in tvscan.COLUMNS]


def test_parse_maps_fields():
    payload = {"data": [entry("NASDAQ:NVDA", make_d())]}
    out = tvscan.parse_scan(payload, ["NVDA"])
    nvda = out["NVDA"]
    assert nvda["tv_symbol"] == "NASDAQ:NVDA"
    assert nvda["name"] == "NVIDIA Corporation"
    assert nvda["price"] == pytest.approx(195.04)
    assert nvda["pct_1d"] == pytest.approx(2.647)
    assert nvda["ps"] == pytest.approx(18.28)
    assert nvda["pct_ytd"] == pytest.approx(2.74)
    assert nvda["pct_off_high"] == pytest.approx((195.04 / 236.54 - 1) * 100)
    assert nvda["atr_pct"] == pytest.approx(7.507 / 195.04 * 100)
    assert nvda["earnings_date"] == "2026-08-26"


def test_parse_prefers_primary_exchange():
    payload = {"data": [
        entry("OTC:NVDA", make_d(exchange="OTC", close=1.0)),
        entry("NASDAQ:NVDA", make_d()),
    ]}
    out = tvscan.parse_scan(payload, ["NVDA"])
    assert out["NVDA"]["tv_symbol"] == "NASDAQ:NVDA"
    assert out["NVDA"]["price"] == pytest.approx(195.04)


def test_parse_ignores_unrequested_tickers():
    payload = {"data": [entry("NASDAQ:NVDA", make_d()), entry("NASDAQ:AAPL", make_d(name="AAPL"))]}
    out = tvscan.parse_scan(payload, ["NVDA"])
    assert list(out) == ["NVDA"]


def test_parse_handles_etf_nulls():
    payload = {"data": [entry("NASDAQ:SMH", make_d(
        name="SMH", description="VanEck Semiconductor ETF", type="fund",
        market_cap_basic=None, price_earnings_ttm=None, price_sales_current=None,
        earnings_release_next_date=None))]}
    out = tvscan.parse_scan(payload, ["SMH"])
    smh = out["SMH"]
    assert smh["ps"] is None
    assert smh["earnings_date"] is None
    assert smh["pct_off_high"] is not None


def test_parse_empty_payload():
    assert tvscan.parse_scan({}, ["NVDA"]) == {}
