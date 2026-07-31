"""Snapshot persistence and run-over-run diffing."""

import json
from pathlib import Path

_KEEP = ("ticker", "price", "pct_1d", "sma", "rs_1m", "pct_off_high")
_SMA_WINDOWS = ("20", "50", "200")


def save_snapshot(rows, directory, date_str):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    slim = [{k: r.get(k) for k in _KEEP if k in r} for r in rows]
    payload = {"date": date_str, "rows": slim}
    (directory / f"{date_str}.json").write_text(json.dumps(payload))
    return payload


def find_previous(directory):
    files = sorted(Path(directory).glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def diff_snapshots(prev, curr_rows, top=5):
    prev_rows = {r["ticker"]: r for r in prev["rows"]}
    movers, sma_flips, curr_tickers = [], [], []
    for row in curr_rows:
        ticker = row["ticker"]
        curr_tickers.append(ticker)
        old = prev_rows.get(ticker)
        if not old:
            continue
        if old.get("price") and row.get("price") is not None:
            change = (row["price"] / old["price"] - 1) * 100
            movers.append({"ticker": ticker, "change_pct": round(change, 2)})
        for window in _SMA_WINDOWS:
            was = ((old.get("sma") or {}).get(window) or {}).get("above")
            now = ((row.get("sma") or {}).get(window) or {}).get("above")
            if was is not None and now is not None and was != now:
                sma_flips.append({"ticker": ticker, "window": window, "now": "above" if now else "below"})
    movers.sort(key=lambda m: -abs(m["change_pct"]))
    return {
        "since": prev["date"],
        "movers": movers[:top],
        "sma_flips": sma_flips,
        "added": [t for t in curr_tickers if t not in prev_rows],
        "removed": [t for t in prev_rows if t not in curr_tickers],
    }
