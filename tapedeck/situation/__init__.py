"""Situation tab: bonds and oil, read with the oil-tracker method.

Design: docs/superpowers/specs/2026-10-01-situation-tab-design.md.
``build_situation`` is the one call tapedeck.py makes; ``write_feed`` writes
output/situation-latest.json. Only ``sources`` touches the network.
"""

import json
import math
from pathlib import Path

from . import alerts, confidence, crowding, legs, oillink, regime, series, sources

SCHEMA = 1
FEED_NAME = "situation-latest.json"
HISTORY_NAME = "situation-history.jsonl"


def _last_date(frames):
    dates = [s.index[-1].date() for s in frames if s is not None and len(s)]
    return max(dates).isoformat() if dates else None


def build_situation(today, out_dir, fetch=None):
    """Fetch, compute and return the tab's dict. ``fetch`` replaces
    ``sources.fetch_all`` in tests. Writes only the OI history file."""
    src = (fetch or sources.fetch_all)(today)
    prep = series.prepare(src)
    rate_legs = legs.build_rates_legs(prep, src, today)
    oil_legs = oillink.build_oil_legs(prep, src, today)
    oi_now = {m: c.get("oi") for m, c in (src.get("ctx") or {}).items()}
    history = crowding.update_history(Path(out_dir) / HISTORY_NAME, today, oi_now)
    crowd = crowding.build_crowding(src.get("ctx"), src.get("funding"), history, today)
    fred = src.get("fred") or {}
    all_legs = rate_legs + oil_legs

    def panel(name, panel_legs):
        return confidence.panel_confidence(
            panel_legs + [row for row in crowd if row["panel"] == name])

    return {
        "schema": SCHEMA,
        "date": today.isoformat(),
        "fred_asof": _last_date(fred.values()),
        "venue_asof": _last_date((src.get("closes") or {}).values()),
        "regime": regime.regime_label(fred.get("DGS10"), fred.get("T10YIE"), fred.get("DFII10")),
        "alerts": alerts.build_alerts(all_legs, crowd),
        "confidence": {"rates": panel("rates", rate_legs), "oil": panel("oil", oil_legs)},
        "legs": all_legs,
        "crowding": crowd,
        "errors": dict(src.get("errors") or {}),
    }


def _json_safe(obj):
    """NaN and infinity become null, so the file is strict JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def write_feed(sit, out_dir):
    """output/situation-latest.json. New keys may be added later; existing
    keys never change meaning — the same contract as feed.py."""
    path = Path(out_dir) / FEED_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(sit), indent=1, default=str, allow_nan=False))
    return path
