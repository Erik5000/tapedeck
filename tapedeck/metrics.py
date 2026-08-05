"""Pure metric computations on price history. No network access."""

import statistics

import pandas as pd


# A year of trading days, minus slack for holidays and the odd missing bar.
# Below this, a "52-week" figure is a claim the data cannot support — the
# trade.xyz markets carry as few as 80 bars, and an 80-bar maximum is not a
# 52-week high. These metrics return None instead, and the page shows n/a.
MIN_52W_BARS = 240


def _clean(series):
    if series is None:
        return None
    s = series.dropna()
    return s if len(s) else None


# --- daily / YTD / 1Y changes ---

def pct_1d(close):
    s = _clean(close)
    if s is None or len(s) < 2:
        return None
    return float((s.iloc[-1] / s.iloc[-2] - 1) * 100)


def pct_ytd(close):
    """Change since the prior year's last close.

    Without a prior-year bar the first bar of the series stands in, but only if
    it falls in January — for a market that started trading in May, "since the
    first bar" is not year-to-date and saying so would overstate the move by
    however much the year had already done.
    """
    s = _clean(close)
    if s is None or len(s) < 2:
        return None
    year = s.index[-1].year
    prior = s[s.index.year < year]
    if len(prior):
        base = prior.iloc[-1]
    elif s.index[0].month == 1:
        base = s.iloc[0]
    else:
        return None
    return float((s.iloc[-1] / base - 1) * 100)


def pct_1y(close):
    s = _clean(close)
    if s is None or len(s) < MIN_52W_BARS:
        return None
    return float((s.iloc[-1] / s.iloc[0] - 1) * 100)


# --- SMA state and crosses ---

def sma_state(close, window):
    s = _clean(close)
    if s is None or len(s) < window:
        return None
    sma = float(s.iloc[-window:].mean())
    price = float(s.iloc[-1])
    return {"sma": sma, "above": price > sma, "dist_pct": (price / sma - 1) * 100}


def sma_cross(close, window):
    s = _clean(close)
    if s is None or len(s) < window + 1:
        return None
    above_now = s.iloc[-1] > s.iloc[-window:].mean()
    above_prev = s.iloc[-2] > s.iloc[-window - 1:-1].mean()
    if above_now and not above_prev:
        return "reclaimed"
    if above_prev and not above_now:
        return "lost"
    return None


# --- 52-week high / low ---

def pct_off_52w_high(close, high):
    c, h = _clean(close), _clean(high)
    if c is None or h is None or len(h) < MIN_52W_BARS:
        return None
    return float((c.iloc[-1] / h.max() - 1) * 100)


def new_52w_extreme(high, low):
    h, l = _clean(high), _clean(low)
    if h is None or l is None or min(len(h), len(l)) < MIN_52W_BARS:
        return None
    if h.iloc[-1] >= h.iloc[:-1].max():
        return "high"
    if l.iloc[-1] <= l.iloc[:-1].min():
        return "low"
    return None


# --- relative strength vs benchmark ---

def _aligned(a, b):
    df = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    return df["a"], df["b"]


def rs_pct(close, bench_close, days):
    a, b = _clean(close), _clean(bench_close)
    if a is None or b is None:
        return None
    a, b = _aligned(a, b)
    if len(a) < days + 1:
        return None
    ret_stock = a.iloc[-1] / a.iloc[-days - 1] - 1
    ret_bench = b.iloc[-1] / b.iloc[-days - 1] - 1
    return float((ret_stock - ret_bench) * 100)


def rs_series(close, bench_close, days=21):
    a, b = _clean(close), _clean(bench_close)
    if a is None or b is None:
        return []
    a, b = _aligned(a, b)
    n = min(days + 1, len(a))
    if n < 2:
        return []
    a, b = a.iloc[-n:], b.iloc[-n:]
    ratio = (a / a.iloc[0]) / (b / b.iloc[0])
    return [float(v) for v in ((ratio - 1) * 100).iloc[1:]]


# --- volatility / volume ---

def atr_pct(high, low, close, window=14):
    h, l, c = _clean(high), _clean(low), _clean(close)
    if h is None or l is None or c is None or min(len(h), len(l), len(c)) < window + 1:
        return None
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    return float(tr.iloc[-window:].mean() / c.iloc[-1] * 100)


def rel_volume(volume, window=20):
    v = _clean(volume)
    if v is None or len(v) < window + 1:
        return None
    avg = v.iloc[-window - 1:-1].mean()
    if not avg:
        return None
    return float(v.iloc[-1] / avg)


# --- sparkline downsampling ---

def sparkline(close, points=60):
    s = _clean(close)
    if s is None:
        return []
    if len(s) <= points:
        return [float(v) for v in s]
    idx = sorted({round(i * (len(s) - 1) / (points - 1)) for i in range(points)})
    return [float(s.iloc[i]) for i in idx]


# --- gaps ---

def gap_pct(open_, close):
    o, c = _clean(open_), _clean(close)
    if o is None or c is None or len(c) < 2:
        return None
    return float((o.iloc[-1] / c.iloc[-2] - 1) * 100)


# --- positions ---

def position_metrics(price, prev_close, shares, cost_basis):
    market_value = price * shares
    day_pnl = (price - prev_close) * shares if prev_close is not None else None
    open_pnl = open_pnl_pct = None
    if cost_basis:
        open_pnl = (price - cost_basis) * shares
        open_pnl_pct = (price / cost_basis - 1) * 100
    return {
        "market_value": market_value,
        "day_pnl": day_pnl,
        "open_pnl": open_pnl,
        "open_pnl_pct": open_pnl_pct,
    }


def portfolio_summary(positions):
    if not positions:
        return None
    total = sum(p["market_value"] for p in positions)
    day = sum(p.get("day_pnl") or 0 for p in positions)
    open_pnl = sum(p.get("open_pnl") or 0 for p in positions)
    prev_total = total - day
    return {
        "total_value": total,
        "day_pnl": day,
        "day_pnl_pct": (day / prev_total * 100) if prev_total else None,
        "open_pnl": open_pnl,
        "weights": [(p["market_value"] / total * 100) if total else 0.0 for p in positions],
    }


# --- cross-sectional ranks ---

def ranks(values):
    present = sorted(
        ((v, i) for i, v in enumerate(values) if v is not None),
        key=lambda t: -t[0],
    )
    out = [None] * len(values)
    for rank, (_, i) in enumerate(present, start=1):
        out[i] = rank
    return out


# --- basket aggregates ---

def basket_aggregate(rows, label):
    """Aggregate row dicts into one basket summary. Pure; tolerates missing fields."""
    def med(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return float(statistics.median(vals)) if vals else None

    pct = [r["pct_1d"] for r in rows if r.get("pct_1d") is not None]
    above = [r["sma"]["50"]["above"] for r in rows if (r.get("sma") or {}).get("50")]
    return {
        "group": label,
        "n": len(rows),
        "avg_pct_1d": sum(pct) / len(pct) if pct else None,
        "med_rs_1m": med("rs_1m"),
        "med_rs_3m": med("rs_3m"),
        "breadth_sma50_pct": sum(above) / len(above) * 100 if above else None,
        "med_pct_off_high": med("pct_off_high"),
    }


def group_aggregates(rows):
    """One basket per distinct group, in first-appearance order. Ungrouped rows are skipped."""
    groups = dict.fromkeys(r["group"] for r in rows if r.get("group"))
    return [basket_aggregate([r for r in rows if r.get("group") == g], g) for g in groups]
