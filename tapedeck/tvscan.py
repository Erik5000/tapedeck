"""TradingView screener fetch — unofficial public endpoint, used as the primary
source for snapshot fields (price, valuations, YTD, 52w high, sector, earnings).
Yahoo remains the source for historical series and the fallback if this breaks."""

from datetime import datetime, timezone

import requests

SCAN_URL = "https://scanner.tradingview.com/america/scan"

COLUMNS = [
    "name", "description", "exchange", "type", "close", "change",
    "market_cap_basic", "price_earnings_ttm", "price_sales_current", "Perf.YTD",
    "price_52_week_high", "ATR", "relative_volume_10d_calc", "sector",
    "earnings_release_next_date",
]

_EXCHANGE_PRIORITY = {"NASDAQ": 0, "NYSE": 1, "AMEX": 2}


def fetch_scan(tickers, timeout=15):
    payload = {
        "filter": [{"left": "name", "operation": "in_range", "right": list(tickers)}],
        "markets": ["america"],
        "columns": COLUMNS,
    }
    resp = requests.post(SCAN_URL, json=payload, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh) tapedeck-dashboard"})
    resp.raise_for_status()
    return parse_scan(resp.json(), tickers)


def parse_scan(payload, requested):
    wanted = set(requested)
    best = {}
    for item in payload.get("data") or []:
        d = dict(zip(COLUMNS, item.get("d") or []))
        ticker = d.get("name")
        if ticker not in wanted:
            continue
        priority = _EXCHANGE_PRIORITY.get(d.get("exchange"), 9)
        if ticker in best and best[ticker]["_priority"] <= priority:
            continue
        close = d.get("close")
        high52 = d.get("price_52_week_high")
        atr = d.get("ATR")
        earnings_ts = d.get("earnings_release_next_date")
        best[ticker] = {
            "_priority": priority,
            "tv_symbol": item.get("s"),
            "name": d.get("description"),
            "sector": d.get("sector"),
            "price": close,
            "pct_1d": d.get("change"),
            "market_cap": d.get("market_cap_basic"),
            "pe": d.get("price_earnings_ttm"),
            "ps": d.get("price_sales_current"),
            "pct_ytd": d.get("Perf.YTD"),
            "pct_off_high": (close / high52 - 1) * 100 if close and high52 else None,
            "atr_pct": (atr / close * 100) if atr and close else None,
            "rel_vol": d.get("relative_volume_10d_calc"),
            "earnings_date": (datetime.fromtimestamp(earnings_ts, tz=timezone.utc).date().isoformat()
                              if earnings_ts else None),
        }
    for row in best.values():
        row.pop("_priority")
    return best
