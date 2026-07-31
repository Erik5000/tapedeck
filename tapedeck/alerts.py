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
