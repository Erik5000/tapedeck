import pandas as pd
import pytest

from bloom import metrics


def bseries(values, end="2026-07-31"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series([float(v) for v in values], index=idx)


# --- daily / YTD / 1Y changes ---

def test_pct_1d():
    assert metrics.pct_1d(bseries([100, 110])) == pytest.approx(10.0)


def test_pct_1d_insufficient_data():
    assert metrics.pct_1d(bseries([100])) is None


def test_pct_ytd_uses_last_close_of_prior_year():
    idx = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-07-31"])
    close = pd.Series([90.0, 100.0, 105.0, 120.0], index=idx)
    assert metrics.pct_ytd(close) == pytest.approx(20.0)


def test_pct_ytd_without_prior_year_uses_first_close():
    idx = pd.to_datetime(["2026-01-05", "2026-07-31"])
    close = pd.Series([100.0, 120.0], index=idx)
    assert metrics.pct_ytd(close) == pytest.approx(20.0)


def test_pct_1y_first_to_last():
    assert metrics.pct_1y(bseries([80, 90, 100])) == pytest.approx(25.0)


# --- SMA state and crosses ---

def test_sma_state_above():
    close = bseries(range(1, 31))  # 1..30
    state = metrics.sma_state(close, 20)
    assert state["sma"] == pytest.approx(20.5)  # mean of 11..30
    assert state["above"] is True
    assert state["dist_pct"] == pytest.approx((30 / 20.5 - 1) * 100)


def test_sma_state_insufficient_data():
    assert metrics.sma_state(bseries(range(10)), 20) is None


def test_sma_cross_reclaimed():
    close = bseries([100.0] * 23 + [90.0, 101.0])
    assert metrics.sma_cross(close, 20) == "reclaimed"


def test_sma_cross_none_when_steady():
    assert metrics.sma_cross(bseries(range(1, 31)), 20) is None


# --- 52-week high / low ---

def test_pct_off_52w_high():
    close = bseries([180, 190, 150])
    high = bseries([200, 195, 155])
    assert metrics.pct_off_52w_high(close, high) == pytest.approx(-25.0)


def test_new_52w_extreme_high():
    high = bseries([100, 120, 130])
    low = bseries([90, 110, 120])
    assert metrics.new_52w_extreme(high, low) == "high"


def test_new_52w_extreme_none():
    high = bseries([100, 120, 110])
    low = bseries([90, 105, 100])
    assert metrics.new_52w_extreme(high, low) is None


# --- relative strength vs benchmark ---

def _linear(start, stop, n):
    step = (stop - start) / (n - 1)
    return [start + step * i for i in range(n)]


def test_rs_pct_return_differential():
    stock = bseries(_linear(100, 110, 22))
    bench = bseries(_linear(100, 102, 22))
    assert metrics.rs_pct(stock, bench, 21) == pytest.approx(8.0)


def test_rs_series_starts_at_zero_ends_at_ratio():
    stock = bseries(_linear(100, 110, 22))
    bench = bseries(_linear(100, 102, 22))
    series = metrics.rs_series(stock, bench, days=21)
    assert len(series) == 21
    assert series[-1] == pytest.approx((1.10 / 1.02 - 1) * 100, rel=1e-3)


# --- volatility / volume ---

def test_atr_pct_constant_range():
    close = bseries([100.0] * 20)
    high = close + 2
    low = close - 2
    assert metrics.atr_pct(high, low, close, window=14) == pytest.approx(4.0)


def test_rel_volume():
    vol = bseries([100.0] * 20 + [200.0])
    assert metrics.rel_volume(vol, window=20) == pytest.approx(2.0)


# --- sparkline downsampling ---

def test_sparkline_downsamples_and_keeps_endpoints():
    close = bseries(range(252))
    points = metrics.sparkline(close, points=60)
    assert len(points) <= 60
    assert points[0] == 0.0
    assert points[-1] == 251.0


# --- gaps ---

def test_gap_pct_open_vs_prior_close():
    open_ = bseries([100, 106])
    close = bseries([100, 108])
    assert metrics.gap_pct(open_, close) == pytest.approx(6.0)


# --- positions ---

def test_position_metrics():
    pos = metrics.position_metrics(price=110, prev_close=100, shares=10, cost_basis=50)
    assert pos["market_value"] == pytest.approx(1100)
    assert pos["day_pnl"] == pytest.approx(100)
    assert pos["open_pnl"] == pytest.approx(600)
    assert pos["open_pnl_pct"] == pytest.approx(120.0)


def test_portfolio_summary():
    positions = [
        {"market_value": 1000.0, "day_pnl": 50.0, "open_pnl": 100.0},
        {"market_value": 3000.0, "day_pnl": -30.0, "open_pnl": 500.0},
    ]
    summary = metrics.portfolio_summary(positions)
    assert summary["total_value"] == pytest.approx(4000)
    assert summary["day_pnl"] == pytest.approx(20)
    assert summary["day_pnl_pct"] == pytest.approx(20 / 3980 * 100)
    assert summary["open_pnl"] == pytest.approx(600)
    assert summary["weights"] == [pytest.approx(25.0), pytest.approx(75.0)]


def test_portfolio_summary_empty():
    assert metrics.portfolio_summary([]) is None


# --- cross-sectional ranks ---

def test_ranks_descending_none_safe():
    assert metrics.ranks([5.0, None, 10.0, -1.0]) == [2, None, 1, 3]
