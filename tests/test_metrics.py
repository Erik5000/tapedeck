import pandas as pd
import pytest

from tapedeck import metrics


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
    assert metrics.pct_1y(bseries([80.0] + [90.0] * 248 + [100.0])) == pytest.approx(25.0)


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
    close = bseries([180.0] * 249 + [150.0])
    high = bseries([200.0] * 249 + [155.0])
    assert metrics.pct_off_52w_high(close, high) == pytest.approx(-25.0)


def test_new_52w_extreme_high():
    high = bseries([100.0] * 249 + [130.0])
    low = bseries([90.0] * 249 + [120.0])
    assert metrics.new_52w_extreme(high, low) == "high"


def test_new_52w_extreme_none():
    high = bseries([100.0] * 248 + [120.0, 110.0])
    low = bseries([90.0] * 248 + [105.0, 100.0])
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


# --- basket aggregates ---

def _row(group=None, pct_1d=None, rs_1m=None, rs_3m=None, off_high=None, above50=None):
    sma = {} if above50 is None else {"50": {"above": above50}}
    return {"group": group, "pct_1d": pct_1d, "rs_1m": rs_1m, "rs_3m": rs_3m,
            "pct_off_high": off_high, "sma": sma}


def test_basket_aggregate_math():
    rows = [
        _row(pct_1d=1.0, rs_1m=2.0, rs_3m=10.0, off_high=-10.0, above50=True),
        _row(pct_1d=3.0, rs_1m=4.0, rs_3m=20.0, off_high=-20.0, above50=False),
        _row(pct_1d=None, rs_1m=6.0, rs_3m=None, off_high=-30.0, above50=True),
    ]
    b = metrics.basket_aggregate(rows, "t1")
    assert b["group"] == "t1"
    assert b["n"] == 3
    assert b["avg_pct_1d"] == pytest.approx(2.0)
    assert b["med_rs_1m"] == pytest.approx(4.0)
    assert b["med_rs_3m"] == pytest.approx(15.0)
    assert b["breadth_sma50_pct"] == pytest.approx(2 / 3 * 100)
    assert b["med_pct_off_high"] == pytest.approx(-20.0)


def test_basket_aggregate_all_missing_is_none():
    b = metrics.basket_aggregate([_row(), _row()], "x")
    assert b["n"] == 2
    assert b["avg_pct_1d"] is None
    assert b["med_rs_1m"] is None
    assert b["breadth_sma50_pct"] is None
    assert b["med_pct_off_high"] is None


def test_basket_breadth_denominator_excludes_missing_sma():
    rows = [_row(above50=True), _row()]  # second row has no 50SMA state at all
    assert metrics.basket_aggregate(rows, "x")["breadth_sma50_pct"] == pytest.approx(100.0)


def test_group_aggregates_first_appearance_order():
    rows = [_row(group="b", pct_1d=1.0), _row(group="a", pct_1d=2.0),
            _row(group="b", pct_1d=3.0), _row(group=None, pct_1d=9.0)]
    baskets = metrics.group_aggregates(rows)
    assert [b["group"] for b in baskets] == ["b", "a"]
    assert baskets[0]["n"] == 2
    assert baskets[0]["avg_pct_1d"] == pytest.approx(2.0)


# --- short-history guards ---
#
# trade.xyz markets carry as little as 80 daily bars. Without these guards an
# 80-bar maximum would render as a "new 52w high", which is a claim the data
# cannot support.

def test_52w_metrics_refuse_short_history():
    short = bseries(range(1, 101))            # 100 bars, monotonically rising
    assert metrics.new_52w_extreme(short, short) is None
    assert metrics.pct_off_52w_high(short, short) is None
    assert metrics.pct_1y(short) is None


def test_52w_metrics_answer_at_the_threshold():
    """The guard must not be so blunt that a real year of data goes silent."""
    n = metrics.MIN_52W_BARS
    rising = bseries(range(1, n + 1))
    assert metrics.new_52w_extreme(rising, rising) == "high"
    assert metrics.pct_off_52w_high(rising, rising) == pytest.approx(0.0)
    assert metrics.pct_1y(rising) is not None
    assert metrics.new_52w_extreme(bseries(range(1, n)), bseries(range(1, n))) is None


def test_short_history_still_yields_the_metrics_it_can_support():
    """Guarding the year-scale metrics must not blank the whole row — %1D, the
    20SMA and the sparkline are all honest on 100 bars."""
    short = bseries(range(1, 101))
    assert metrics.pct_1d(short) is not None
    assert metrics.sma_state(short, 20) is not None
    assert metrics.sma_state(short, 200) is None      # genuinely not computable
    assert metrics.sparkline(short)


def test_pct_ytd_is_none_when_the_series_starts_mid_year():
    """A market that listed in May has no year-to-date. Falling back to its
    first bar labelled the listing-to-date move as YTD — trade.xyz's SPCX
    reported -42.2% YTD off 80 bars that all began on 2026-05-17."""
    idx = pd.bdate_range(start="2026-05-18", periods=50)
    close = pd.Series([100.0] * 49 + [58.0], index=idx)
    assert metrics.pct_ytd(close) is None


def test_pct_ytd_still_falls_back_for_a_january_listing():
    """The fallback exists for a name that started trading in January, where
    'since the first close' really is year-to-date."""
    idx = pd.bdate_range(start="2026-01-05", periods=50)
    close = pd.Series([100.0] * 49 + [120.0], index=idx)
    assert metrics.pct_ytd(close) == pytest.approx(20.0)
