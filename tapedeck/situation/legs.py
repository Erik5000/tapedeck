"""The legs as data, and the one function that turns a series into a leg row.

Every leg states what a higher value means. The z-score is always taken on
the value in its natural orientation, so "higher z" and "higher means" never
disagree. tests/test_situation_legs.py pins each direction — a sign flip is
the bug that still produces a plausible number (oil-tracker brief §2.1). Pure.
"""

import math

from . import stats
from .stats import clean

MIN_BARS = stats.Z_WINDOW
STALE_DAYS = 4
THIN_VOLUME = 100_000          # $ per 24h
THIN_MARK_GAP = 0.005          # |mark − oracle| / oracle

# id -> (label, panel, unit, higher means). Order is display order.
RATE_LEGS = {
    "y2": ("2Y", "rates", "%", "higher yield"),
    "y10": ("10Y", "rates", "%", "higher yield"),
    "y30": ("30Y", "rates", "%", "higher yield"),
    "curve_2s10s": ("2s10s", "rates", "bp", "steeper"),
    "curve_10s30s": ("10s30s", "rates", "bp", "steeper"),
    "be10": ("BE 10Y", "rates", "%", "more priced inflation"),
    "be5y5y": ("BE 5y5y", "rates", "%", "more priced long-run inflation"),
    "real10": ("Real 10Y", "rates", "%", "tighter money"),
    "term_premium": ("Term prem", "rates", "%", "more pay for duration risk"),
    "rate_vol": ("Rate vol", "rates", "bp", "more rate volatility"),
    "credit": ("HY spread", "rates", "%", "more credit stress"),
}
FRED_LEGS = (("be10", "T10YIE"), ("be5y5y", "T5YIFR"), ("real10", "DFII10"),
             ("term_premium", "THREEFYTP10"), ("credit", "BAMLH0A0HYM2"))
STALE_OVERRIDE = {"term_premium": 10}     # THREEFYTP10 publishes ~1 week late
YIELD_MARKET = {"y2": "para:2Y", "y10": "para:10Y", "y30": "para:30Y"}
CURVES = (("curve_2s10s", "y10", "y2"), ("curve_10s30s", "y30", "y10"))

_AUTO = object()


def is_thin(ctx):
    """A venue market too thin to trust fully: 24h volume under $100k, or the
    mark more than 0.5% from the oracle. Unknown context is not thin — a leg
    without data is scored as "no data" on its own."""
    if not ctx:
        return False
    vol = ctx.get("volume_24h")
    if vol is not None and vol < THIN_VOLUME:
        return True
    mark, oracle = ctx.get("mark"), ctx.get("oracle")
    if mark is not None and oracle:
        return abs(mark - oracle) / oracle > THIN_MARK_GAP
    return False


def make_leg(leg_id, label, panel, unit, higher, series, today, *, src, value=_AUTO,
             chg20=_AUTO, chg_mult=100.0, chg_unit="bp", z_series=_AUTO, center=True,
             with_z=True, min_bars=MIN_BARS, stale_days=STALE_DAYS, thin=False, note=None):
    """One leg row. ``series`` is the level series: it gives the data age, and
    by default the value, the 20-bar change (× ``chg_mult``) and the z basis.

    status: "no_data" (no series), "warming" (z basis shorter than
    ``min_bars``), "stale" (older than ``stale_days``), else "ok". A warming
    leg has z None — never a default.
    """
    s = clean(series)
    leg = {"id": leg_id, "label": label, "panel": panel, "unit": unit, "higher": higher,
           "src": src, "value": None, "chg20": None, "chg_unit": chg_unit, "z": None,
           "state": None, "age_days": None, "status": "no_data", "n": 0,
           "need": min_bars if with_z else 0, "thin": bool(thin), "note": note}
    if s is None:
        leg["note"] = note or "no data"
        return leg
    leg["value"] = float(s.iloc[-1]) if value is _AUTO else stats.finite(value)
    if chg20 is _AUTO:
        c = stats.change(s, 20)
        chg20 = None if c is None else c * chg_mult
    leg["chg20"] = stats.finite(chg20)
    leg["age_days"] = stats.age_days(s, today)
    status = "ok"
    if with_z:
        zs = s if z_series is _AUTO else clean(z_series)
        leg["n"] = 0 if zs is None else len(zs)
        if leg["n"] < min_bars:
            status = "warming"
        else:
            leg["z"] = stats.zscore(zs, min_bars, center=center)
            leg["state"] = stats.state_word(leg["z"])
    if leg["age_days"] is not None and leg["age_days"] > stale_days:
        status = "stale"
    leg["status"] = status
    return leg


def _rate_leg(leg_id, series, today, **kw):
    label, panel, unit, higher = RATE_LEGS[leg_id]
    kw.setdefault("stale_days", STALE_OVERRIDE.get(leg_id, STALE_DAYS))
    return make_leg(leg_id, label, panel, unit, higher, series, today, **kw)


def _thin(ctx, *markets):
    return any(is_thin((ctx or {}).get(m)) for m in markets)


def build_rates_legs(prep, src, today):
    """Panel A legs, in display order. ``prep`` comes from series.prepare."""
    fred, ctx = src.get("fred") or {}, src.get("ctx") or {}
    legs = []
    for leg_id, market in YIELD_MARKET.items():
        j = prep[leg_id]
        legs.append(_rate_leg(leg_id, j["series"], today, src=j["src"], value=j["live"],
                              thin=_thin(ctx, market), note=j["note"]))

    for leg_id, long_end, short_end in CURVES:
        a, b = prep[long_end], prep[short_end]
        curve = None
        if a["series"] is not None and b["series"] is not None:
            curve = (a["series"] - b["series"]).dropna() * 100
        tag = a["src"] if a["src"] == b["src"] else "V+F"
        legs.append(_rate_leg(leg_id, curve, today, src=tag if curve is not None else None,
                              chg_mult=1.0,
                              thin=_thin(ctx, YIELD_MARKET[long_end], YIELD_MARKET[short_end])))

    for leg_id, fid in FRED_LEGS:
        s = fred.get(fid)
        leg = _rate_leg(leg_id, s, today, src="F" if s is not None else None)
        if leg_id == "be10":
            cs = clean(s)
            leg["chg_z"] = None if cs is None else stats.zscore((cs - cs.shift(20)).dropna())
        legs.append(leg)

    y10 = clean(prep["y10"]["series"])
    vol = None
    if y10 is not None:
        vol = ((y10.diff() * 100).rolling(20).std() * math.sqrt(252)).dropna()
    legs.append(_rate_leg("rate_vol", vol, today, src=prep["y10"]["src"], chg_mult=1.0,
                          thin=_thin(ctx, "para:10Y")))

    order = list(RATE_LEGS)
    return sorted(legs, key=lambda leg: order.index(leg["id"]))
