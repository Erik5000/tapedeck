"""Alert rules over computed row dicts. Pure — clock is injected."""

from datetime import date

GAP_THRESHOLD_PCT = 5.0
EARNINGS_WINDOW_DAYS = 7


def build_alerts(rows, today):
    alerts = []
    for row in rows:
        ticker = row["ticker"]
        extreme = row.get("new_52w")
        if extreme == "high":
            alerts.append({"ticker": ticker, "kind": "52w_high", "text": "new 52w high", "severity": "good"})
        elif extreme == "low":
            alerts.append({"ticker": ticker, "kind": "52w_low", "text": "new 52w low", "severity": "bad"})

        for window, cross in (row.get("sma_cross") or {}).items():
            if cross == "reclaimed":
                alerts.append({"ticker": ticker, "kind": "sma_reclaimed", "text": f"reclaimed {window}SMA", "severity": "good"})
            elif cross == "lost":
                alerts.append({"ticker": ticker, "kind": "sma_lost", "text": f"lost {window}SMA", "severity": "bad"})

        gap = row.get("gap_pct")
        if gap is not None and abs(gap) >= GAP_THRESHOLD_PCT:
            direction = "up" if gap > 0 else "down"
            alerts.append({"ticker": ticker, "kind": "gap", "text": f"gapped {direction} {gap:+.1f}%", "severity": "warn"})

        earnings = row.get("earnings_date")
        if earnings:
            days = (date.fromisoformat(earnings) - today).days
            if 0 <= days <= EARNINGS_WINDOW_DAYS:
                alerts.append({"ticker": ticker, "kind": "earnings", "text": f"earnings in {days}d", "severity": "warn"})
    return alerts


_VWAP_SEVERITY = {"reclaim": "good", "reject": "bad", "support": "good", "resistance": "bad"}
_VWAP_DIRECTION = {"reclaim": "reclaiming", "reject": "rejecting",
                    "support": "acting as support", "resistance": "acting as resistance"}


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
        text = f'{abs(pct):.1f}% {side} {level.get("name")} VWAP'
        direction = _VWAP_DIRECTION.get(level.get("direction"))
        if direction:
            text += f" · {direction}"
        out.append({"ticker": row.get("ticker"), "kind": "vwap", "text": text,
                    "severity": _VWAP_SEVERITY.get(level.get("direction"), "warn")})
    return out
