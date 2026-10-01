"""The regime label: which part moved the 10Y. Pure.

FRED defines T10YIE as DGS10 − DFII10, so over any window
Δ nominal = Δ breakeven + Δ real yield. All three come from FRED, so the
split adds up exactly, and the label carries the FRED date.
"""

import pandas as pd

from .stats import clean

BARS = 20
THRESHOLD_BP = 10.0


def _no_label(note):
    """The same keys as a label, with every number None, so a reader of the
    feed never meets a missing key."""
    return {"label": None, "d10": None, "dbe": None, "dreal": None, "asof": None, "note": note}


def regime_label(dgs10, t10yie, dfii10, bars=BARS, threshold_bp=THRESHOLD_BP):
    """{"label", "d10", "dbe", "dreal", "asof", "note"}; changes in bp.

    The label is None, and the note says why, when an input is missing or the
    three share no more than ``bars`` days.
    """
    parts = [clean(s) for s in (dgs10, t10yie, dfii10)]
    if any(p is None for p in parts):
        return _no_label("needs DGS10, T10YIE and DFII10 from FRED")
    frame = pd.concat(parts, axis=1, join="inner")
    if len(frame) <= bars:
        return _no_label(f"warming up ({len(frame)}/{bars + 1})")
    # round(…, 6): (5.10 − 5.00) × 100 is 9.999999999999787 in floats.
    d10, dbe, dreal = (round(float(x) * 100, 6) for x in frame.iloc[-1] - frame.iloc[-1 - bars])
    if abs(d10) < threshold_bp:
        label = "Range-bound"
    elif d10 > 0:
        label = "Inflation-led sell-off" if dbe > dreal else "Real-rate-led sell-off"
    else:
        label = "Growth-scare rally" if dreal < dbe else "Disinflation rally"
    return {"label": label, "d10": d10, "dbe": dbe, "dreal": dreal,
            "asof": frame.index[-1].date().isoformat(), "note": None}
