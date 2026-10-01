"""Venue positioning: funding and open interest (OI).

Pure except for the history file. The venue publishes funding history but no
OI history, so each run stores today's OI, one line per day, in
output/situation-history.jsonl. A second run on the same day updates that
day's line, so "20 days" always means 20 days.
"""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import stats
from .legs import is_thin
from .stats import clean

HOURS_PER_YEAR = 24 * 365
FUNDING_RECENT_DAYS = 7
FUNDING_MIN_DAYS = 60
OI_DAYS = 20
# +1: a long position is long duration (a bond price). −1: a long position is
# short duration (a yield perp gains when yields rise). Absent: not rates.
DURATION_SIGN = {"para:10Y": -1, "mkts:USBOND": 1, "xyz:TLT": 1}
CROWD_MARKETS = (("xyz:BRENTOIL", "oil"), ("xyz:CL", "oil"),
                 ("para:10Y", "rates"), ("mkts:USBOND", "rates"), ("xyz:TLT", "rates"))


def funding_stats(hourly, recent_days=FUNDING_RECENT_DAYS, min_days=FUNDING_MIN_DAYS):
    """{"funding_ann": %/yr over the last 7 days, "funding_z": z of daily mean
    funding over all fetched whole days (None under 60 days), "funding_days": n}.

    The index is UTC. A day without its 23:00 row is not over yet; the mean of
    a few hours is noisy, so that day is left out of the daily series. It
    still counts in ``funding_ann``, which uses the hourly rows.
    """
    s = clean(hourly)
    if s is None:
        return {"funding_ann": None, "funding_z": None, "funding_days": 0}
    recent = s[s.index > s.index[-1] - pd.Timedelta(days=recent_days)]
    ann = stats.finite(float(recent.mean()) * HOURS_PER_YEAR * 100)
    whole = s if s.index[-1].hour == 23 else s[s.index < s.index[-1].normalize()]
    daily = whole.resample("D").mean().dropna()
    n = len(daily)
    z = stats.zscore(daily, window=n) if n >= min_days else None
    return {"funding_ann": ann, "funding_z": z, "funding_days": n}


def duration_side(market, funding_ann):
    """Which side of duration pays funding, or None for a non-rates market.

    Positive funding: longs pay, so longs are crowded. A long yield perp is
    short duration; a long bond is long duration.
    """
    sign = DURATION_SIGN.get(market)
    if sign is None or not funding_ann:
        return None
    longs_crowded = funding_ann > 0
    long_duration = longs_crowded if sign > 0 else not longs_crowded
    return "long duration crowded" if long_duration else "short duration crowded"


def load_history(path):
    """[{"date": "YYYY-MM-DD", "oi": {market: float}}] sorted by date.

    A missing file is an empty history. An unreadable line — for example one
    half-written by a run that was stopped — is skipped with a warning.
    """
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            date.fromisoformat(rec["date"])
            oi = {m: float(v) for m, v in (rec.get("oi") or {}).items()
                  if stats.finite(v) is not None}
        except Exception:
            print(f"warning: {p.name} line {i} unreadable — skipped", file=sys.stderr)
            continue
        out.append({"date": rec["date"], "oi": oi})
    return sorted(out, key=lambda r: r["date"])


def update_history(path, today, oi_by_market):
    """Merge today's OI into today's line and return the history.

    A market in the new OI overwrites today's saved value; a market missing
    from it keeps the saved value. The venue keeps no OI history, so a later
    run with less OI (one dex failed, or the venue is down) never erases a
    saved value. The file is written to a temp file, then replaced.
    """
    stamp = today.isoformat()
    hist = load_history(path)
    oi = {m: float(v) for m, v in (oi_by_market or {}).items() if stats.finite(v) is not None}
    if oi:
        saved = next((r["oi"] for r in hist if r["date"] == stamp), {})
        hist = [r for r in hist if r["date"] != stamp]
        hist.append({"date": stamp, "oi": {**saved, **oi}})
        hist.sort(key=lambda r: r["date"])
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(p, "".join(json.dumps(r, sort_keys=True) + "\n" for r in hist))
    return hist


def write_atomic(path, text):
    """Write ``text`` to a temp file in the same folder, then replace ``path``.
    A run stopped mid-write leaves the old file whole."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def oi_change(history, market, today, days=OI_DAYS):
    """(% change of today's OI against the newest line at least ``days`` days
    old, days of history for this market capped at ``days``).

    The second number is the n of "warming up (n/20 days)". A gap of missing
    days does not matter: the reference is the newest line on or before the
    cutoff, whatever day that is.
    """
    rows = [(date.fromisoformat(r["date"]), r["oi"].get(market)) for r in history]
    rows = [(d, v) for d, v in rows if v is not None]
    if not rows:
        return None, 0
    span = min((today - rows[0][0]).days, days)
    old = [v for d, v in rows if d <= today - timedelta(days=days)]
    now = [v for d, v in rows if d == today]
    if not old or not now or not old[-1]:
        return None, span
    return stats.finite((now[-1] / old[-1] - 1) * 100), span


def build_crowding(ctx, funding, history, today):
    """One row per CROWD_MARKETS market, with status and note like a leg."""
    rows = []
    for market, panel in CROWD_MARKETS:
        c = (ctx or {}).get(market)
        f = funding_stats((funding or {}).get(market))
        oi_chg, oi_days = oi_change(history, market, today)
        row = {"market": market, "panel": panel, "oi": (c or {}).get("oi"),
               "oi_chg_20d": oi_chg, "oi_days": oi_days, "oi_need": OI_DAYS,
               "funding_need": FUNDING_MIN_DAYS,
               "side": duration_side(market, f["funding_ann"]), "thin": is_thin(c)}
        row.update(f)
        if c is None and f["funding_ann"] is None:
            row["status"], row["note"] = "no_data", "no data"
        elif oi_chg is None or f["funding_z"] is None:
            parts = []
            if oi_chg is None:
                parts.append(f"OI {oi_days}/{OI_DAYS} days")
            if f["funding_z"] is None:
                parts.append(f"funding {f['funding_days']}/{FUNDING_MIN_DAYS} days")
            row["status"], row["note"] = "warming", "warming up: " + ", ".join(parts)
        else:
            row["status"], row["note"] = "ok", None
        rows.append(row)
    return rows
