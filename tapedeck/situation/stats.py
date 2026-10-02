"""Small numeric helpers for the Situation tab. Pure — no IO, no network.

Every function returns None rather than a number it cannot stand behind: a
short series, a flat series or a non-finite value gives None, and the caller
shows "warming up" or "no data". Nothing here invents a default.
"""

import math

import numpy as np
import pandas as pd

Z_WINDOW = 252


def finite(x):
    """``x`` as a finite float, or None. Refuses bool (``float(True)`` would
    pass as 1.0), None, text that is not a number, NaN and infinity."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clean(series):
    """A float Series without NaN or infinity, sorted by date, or None if
    nothing is left."""
    if series is None:
        return None
    s = pd.to_numeric(pd.Series(series), errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan).dropna().astype(float).sort_index()
    return s if len(s) else None


def zscore(series, window=Z_WINDOW, center=True):
    """z of the last value against the last ``window`` values, the last one
    included. None when there are fewer than ``window`` values or the spread
    is zero.

    With ``center=False`` the last value is divided by the spread without
    subtracting the mean. The be_gap leg uses this: its gap is already a
    distance from "what the beta predicts", so zero is its natural centre.
    """
    s = clean(series)
    if s is None or len(s) < window:
        return None
    tail = s.iloc[-window:]
    sd = float(tail.std(ddof=1))
    if not math.isfinite(sd) or sd == 0:
        return None
    last = float(tail.iloc[-1])
    return finite((last - float(tail.mean())) / sd if center else last / sd)


def change(series, bars=20):
    """Last value minus the value ``bars`` bars back, or None."""
    s = clean(series)
    if s is None or len(s) <= bars:
        return None
    return finite(float(s.iloc[-1]) - float(s.iloc[-1 - bars]))


def state_word(z):
    """|z| under 1: normal. 1 to 2: high / low. Over 2: extreme high / low."""
    if z is None:
        return None
    side = "high" if z > 0 else "low"
    if abs(z) < 1:
        return "normal"
    return side if abs(z) <= 2 else f"extreme {side}"


def age_days(series, today):
    """Calendar days from the last value to ``today``, or None."""
    s = clean(series)
    if s is None:
        return None
    return (today - s.index[-1].date()).days
