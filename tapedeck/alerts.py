"""Alert rules over computed row dicts. Pure — clock is injected."""

from datetime import date

from . import vwaplink

GAP_THRESHOLD_PCT = 5.0
EARNINGS_WINDOW_DAYS = 7


def build_alerts(rows, today):
    """Every alert carries a full `text` and a compact `short`.

    `short` is what the grouped panel prints once the ticker is already its own
    column and the severity icon already carries the direction — "reclaimed
    20SMA" under a green ▲ next to CRDO is three ways of saying the same thing.
    `text` stays the authoritative wording and is what the feed and the chip's
    tooltip use.
    """
    alerts = []
    for row in rows:
        ticker = row["ticker"]
        extreme = row.get("new_52w")
        if extreme == "high":
            alerts.append({"ticker": ticker, "kind": "52w_high", "text": "new 52w high",
                           "short": "new 52w high", "severity": "good"})
        elif extreme == "low":
            alerts.append({"ticker": ticker, "kind": "52w_low", "text": "new 52w low",
                           "short": "new 52w low", "severity": "bad"})

        for window, cross in (row.get("sma_cross") or {}).items():
            if cross == "reclaimed":
                alerts.append({"ticker": ticker, "kind": "sma_reclaimed", "text": f"reclaimed {window}SMA",
                               "short": f"{window}SMA", "severity": "good"})
            elif cross == "lost":
                alerts.append({"ticker": ticker, "kind": "sma_lost", "text": f"lost {window}SMA",
                               "short": f"{window}SMA", "severity": "bad"})

        gap = row.get("gap_pct")
        if gap is not None and abs(gap) >= GAP_THRESHOLD_PCT:
            direction = "up" if gap > 0 else "down"
            alerts.append({"ticker": ticker, "kind": "gap", "text": f"gapped {direction} {gap:+.1f}%",
                           "short": f"gap {gap:+.1f}%", "severity": "warn"})

        earnings = row.get("earnings_date")
        if earnings:
            days = (date.fromisoformat(earnings) - today).days
            if 0 <= days <= EARNINGS_WINDOW_DAYS:
                alerts.append({"ticker": ticker, "kind": "earnings", "text": f"earnings in {days}d",
                               "short": f"earnings {days}d", "severity": "warn"})
    return alerts


def group_alerts(alerts):
    """Collapse a flat alert list to one entry per ticker, busiest first.

    Returns [{"ticker", "alerts", "counts"}]. Ordering is total count
    descending, then bad-severity count descending, then first appearance —
    that last tie-break is what keeps an unchanged watchlist rendering in the
    same order run to run.

    Grouping happens here rather than in build_alerts because the flat list is
    a published contract: `lists[].alerts` in output/tapedeck-latest.json.
    """
    order, groups = {}, {}
    for alert in alerts:
        ticker = alert.get("ticker")
        if ticker not in groups:
            order[ticker] = len(order)
            groups[ticker] = []
        groups[ticker].append(alert)

    out = [{"ticker": ticker, "alerts": items,
            "counts": {sev: sum(1 for a in items if a.get("severity") == sev)
                       for sev in ("bad", "warn", "good")}}
           for ticker, items in groups.items()]
    out.sort(key=lambda g: (-len(g["alerts"]), -g["counts"]["bad"], order[g["ticker"]]))
    return out


_VWAP_SEVERITY = {"reclaim": "good", "reject": "bad", "support": "good", "resistance": "bad"}
_VWAP_DIRECTION = {"reclaim": "reclaiming", "reject": "rejecting",
                    "support": "acting as support", "resistance": "acting as resistance"}
assert set(_VWAP_SEVERITY) <= set(vwaplink.DIRECTIONS)
assert set(_VWAP_DIRECTION) <= set(vwaplink.DIRECTIONS)

# Level names are free text from the scanner feed, so the map handles the ones
# that exist today and the rule below covers anything it adds later.
_SHORT_LEVEL = {"Quarterly Anchored": "Q-Anch", "Yearly Anchored": "Y-Anch",
                "Decade Anchored": "10Y-Anch"}


def _short_level(name):
    if name in _SHORT_LEVEL:
        return _SHORT_LEVEL[name]
    return name.replace(" Rolling", "-Roll").replace(" Anchored", "-Anch")


def build_vwap_alerts(rows):
    """One alert per ticker sitting within its watchlist's VWAP proximity band.

    Only the nearest in-range level alerts: a name resting on three VWAPs at
    once is one situation, not three chips. `in_range` is set by vwaplink
    against the list's `vwap_alert_pct`, so this rule needs no threshold of
    its own.

    Defensive by design: any malformed or missing shape in `row["vwap"]`
    (absent key, None, non-dict, missing/empty `levels`, an `in_range_any`
    that doesn't line up with any individual level's `in_range`, an absent
    or unrecognised `direction`) degrades to "no alert for that row" rather
    than raising — this mirrors vwaplink's own degrade-never-raise contract.
    """
    out = []
    for row in rows:
        vwap = row.get("vwap")
        if not isinstance(vwap, dict) or not vwap.get("in_range_any"):
            continue
        levels = vwap.get("levels")
        if not isinstance(levels, list):
            continue
        level = next((lvl for lvl in levels if isinstance(lvl, dict) and lvl.get("in_range")), None)
        if not level:
            continue
        pct = level.get("pct_distance")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            continue
        side = "above" if pct >= 0 else "below"
        name = level.get("name") or "n/a"
        # A fib retracement/extension is a static price projection, not a VWAP
        # line — only append "VWAP" for kinds that actually are one.
        suffix = "" if level.get("kind") == "fib" else " VWAP"
        text = f'{abs(pct):.1f}% {side} {name}{suffix}'
        direction = _VWAP_DIRECTION.get(level.get("direction"))
        if direction:
            text += f" · {direction}"
        # The short form drops the side word and the direction phrase: the chip
        # sits under a ▲/▼ that already says which, next to its own ticker.
        out.append({"ticker": row.get("ticker"), "kind": "vwap", "text": text,
                    "short": f'{abs(pct):.1f}% {_short_level(name)}',
                    "severity": _VWAP_SEVERITY.get(level.get("direction"), "warn")})
    return out
