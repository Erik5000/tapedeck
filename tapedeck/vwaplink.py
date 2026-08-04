"""Read-only bridge to an external vwap-scanner feed (JSON).

This module is a strictly read-only consumer: the only filesystem access is
``Path(path).read_text()`` in ``load_vwap`` — nothing here ever writes to
the scanner's files. Any failure (missing file, malformed JSON, unknown
schema, malformed fields within an otherwise valid feed) degrades to
``None`` with a stderr warning so the dashboard run always survives.

Distances are recomputed locally. The feed stores level *values*; VWAP levels
move slowly while price moves every tick, so recomputing against tapedeck's
live price keeps last night's scan useful all day and guarantees the numbers
on the page agree with the price rendered beside them. ``direction`` is the
one field carried verbatim — it is a bar-over-bar classification the scanner
derives from its own prior close, and tapedeck has no equivalent basis for it.
"""

import json
import sys
from datetime import date
from pathlib import Path

SCHEMA = 1
STALE_DAYS = 7
DEFAULT_ALERT_PCT = 2.0

_LEVEL_KEYS = ("name", "kind", "value", "sigma", "direction")


def load_vwap(path):
    """Read + validate a vwap-scanner feed. Returns None (and warns) on any failure."""
    try:
        feed = json.loads(Path(path).read_text())
    except Exception as exc:
        print(f"warning: vwap feed not readable ({exc}) — levels omitted", file=sys.stderr)
        return None
    if not isinstance(feed, dict):
        print(f"warning: vwap feed schema {type(feed).__name__!r} != {SCHEMA} — levels omitted", file=sys.stderr)
        return None
    schema = feed.get("schema")
    if schema != SCHEMA:
        print(f"warning: vwap feed schema {schema!r} != {SCHEMA} — levels omitted", file=sys.stderr)
        return None
    return feed


def vwap_freshness(feed, today):
    """Age the feed's `generated` stamp against `today` (a datetime.date)."""
    if not feed:
        return None
    stamp = feed.get("generated")
    generated, age = None, None
    if stamp:
        try:
            generated = date.fromisoformat(str(stamp)[:10])
            age = (today - generated).days
        except (ValueError, TypeError):
            generated = None
    return {"generated": generated.isoformat() if generated else None,
            "age_days": age,
            "stale": age is not None and age > STALE_DAYS}


def attach_vwap(rows, feed, alert_pct):
    """Set ``row["vwap"]`` on every row, in place (None where unavailable).

    ``alert_pct`` is tapedeck's own proximity band and defines ``in_range``
    everywhere in the dashboard — deliberately tighter than the feed's
    ``threshold_pct``, which only describes what the scan put in the file.
    """
    tickers = (feed or {}).get("tickers") or {}
    if not isinstance(tickers, dict):
        tickers = {}
    for row in rows:
        entry = tickers.get(row.get("ticker"))
        if not isinstance(entry, dict):
            entry = None
        try:
            row["vwap"] = _for_row(entry, row.get("price"), alert_pct)
        except Exception as exc:
            print(f"warning: vwap row for {row.get('ticker')!r} malformed ({exc}) — omitted", file=sys.stderr)
            row["vwap"] = None


def _for_row(entry, price, alert_pct):
    if not entry or price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    levels = []
    raw_levels = entry.get("levels")
    if not isinstance(raw_levels, list):
        raw_levels = []
    for raw in raw_levels:
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        try:
            if value is None:
                continue
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        sigma = raw.get("sigma")
        try:
            sigma = float(sigma) if sigma is not None else None
        except (TypeError, ValueError):
            sigma = None
        pct_distance = (price - value) / value * 100
        levels.append({**{k: raw.get(k) for k in _LEVEL_KEYS},
                       "value": value,
                       "sigma": sigma,
                       "pct_distance": pct_distance,
                       "in_range": abs(pct_distance) <= alert_pct,
                       "z_stretch": (price - value) / sigma if sigma else None})
    if not levels:
        return None
    levels.sort(key=lambda lvl: abs(lvl["pct_distance"]))
    features = entry.get("features")
    if not isinstance(features, dict):
        features = {}
    return {"score": entry.get("score"),
            "features": features,
            "levels": levels,
            "nearest": levels[0],
            "in_range_any": any(lvl["in_range"] for lvl in levels)}
