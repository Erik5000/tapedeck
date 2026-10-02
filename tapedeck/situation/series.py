"""History joins: FRED supplies the years the young venue markets lack. Pure.

Two rules, one per kind of series (spec: "History join rules"):

* Yields join on **levels**, but only when the venue and FRED agree.
* Brent joins on **daily % returns**, never on levels: the perp is a futures
  price and FRED Brent is spot, so the two levels differ by the curve spread.
"""

import pandas as pd

from .stats import clean

JOIN_TOL = 0.05          # 5 bp, in the percent units both sources use
JOIN_MIN_OVERLAP = 5
YIELD_PAIRS = {"y2": ("DGS2", "para:2Y"), "y10": ("DGS10", "para:10Y"),
               "y30": ("DGS30", "para:30Y")}


def by_day(series):
    """``clean`` plus one value per calendar day, on a midnight index."""
    s = clean(series)
    if s is None:
        return None
    s = s.copy()
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s[~s.index.duplicated(keep="last")]


def join_levels(fred, venue, tol=JOIN_TOL, min_overlap=JOIN_MIN_OVERLAP):
    """Join a FRED yield history to a venue yield series.

    Returns {"series", "live", "src", "joined", "note"}:

    * They agree (at least ``min_overlap`` shared days, mean |difference| at
      most ``tol``): FRED before the first venue day, then the venue. src V+F.
    * They disagree, or share too few days: the history is FRED only and
      ``live`` is the venue's last value. src F, and the note says why.
    * One side is missing: the other side alone. src F or V.
    """
    f, v = by_day(fred), by_day(venue)
    if f is None and v is None:
        return {"series": None, "live": None, "src": None, "joined": False, "note": "no data"}
    if v is None:
        return {"series": f, "live": float(f.iloc[-1]), "src": "F", "joined": False,
                "note": "venue: no data"}
    if f is None:
        return {"series": v, "live": float(v.iloc[-1]), "src": "V", "joined": False,
                "note": "FRED: no data"}
    shared = f.index.intersection(v.index)
    if len(shared) >= min_overlap:
        gap = float((f.loc[shared] - v.loc[shared]).abs().mean())
        if round(gap, 9) <= tol:
            joined = pd.concat([f[f.index < v.index[0]], v])
            return {"series": joined, "live": float(v.iloc[-1]), "src": "V+F",
                    "joined": True, "note": None}
        why = f"{gap * 100:.1f} bp apart"
    else:
        why = f"only {len(shared)} shared days"
    return {"series": f, "live": float(v.iloc[-1]), "src": "F", "joined": False,
            "note": f"venue ≠ FRED ({why}), not joined: value is venue, z is FRED"}


def join_returns(fred_level, venue_level):
    """Daily % returns: FRED before the first venue day, then the venue.

    The first venue return is measured venue-to-venue, so no return spans the
    two sources and the join never shows a false jump.
    """
    f, v = by_day(fred_level), by_day(venue_level)
    parts = []
    if f is not None:
        fr = f.pct_change().dropna() * 100
        if v is not None:
            fr = fr[fr.index < v.index[0]]
        parts.append(fr)
    if v is not None:
        parts.append(v.pct_change().dropna() * 100)
    parts = [p for p in parts if len(p)]
    if not parts:
        return None
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated(keep="last")]


def prepare(src):
    """The joined inputs the legs read.

    {"y2"|"y10"|"y30": join_levels result,
     "brent": {"returns", "level", "src"},
     "wti": venue CL closes or None}
    """
    fred, closes = src.get("fred") or {}, src.get("closes") or {}
    prep = {key: join_levels(fred.get(fid), closes.get(market))
            for key, (fid, market) in YIELD_PAIRS.items()}
    brent_v, brent_f = by_day(closes.get("xyz:BRENTOIL")), by_day(fred.get("DCOILBRENTEU"))
    tags = [t for t, s in (("V", brent_v), ("F", brent_f)) if s is not None]
    prep["brent"] = {"returns": join_returns(brent_f, brent_v),
                     "level": brent_v if brent_v is not None else brent_f,
                     "src": "+".join(tags) or None}
    prep["wti"] = by_day(closes.get("xyz:CL"))
    return prep
