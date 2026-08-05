"""Price history from trade.xyz — XYZ markets on HyperCore (Hyperliquid).

Mirrors fetch.py's contract exactly ({key: OHLCV DataFrame} on a DatetimeIndex)
so pipeline and metrics need no knowledge of where a row's prices came from.

Two properties of this venue shape everything here:

  * **History is short.** These markets listed between late 2025 and mid 2026,
    so most carry well under a year of bars. Metrics that need a year degrade
    to n/a — see the minimum-bar guards in metrics.py. Nothing here pads or
    extrapolates.
  * **Bars are 24/7.** Perps trade through the weekend, so a raw 20-bar mean
    would span 20 calendar days ≈ 14 trading days — a different indicator from
    the 20SMA everywhere else on the page. Weekend bars are dropped so the SMA
    windows keep their trading-day meaning.

The venue publishes no fundamentals at all: no market cap, P/E, P/S, sector or
earnings date. Those columns come from the TradingView screener where the
market's symbol happens to also be a US ticker, and read n/a otherwise.

Stdlib only — no API key, nothing to sign up for, same as the rest of tapedeck.
"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

API_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_DEX = "xyz"
HISTORY_DAYS = 400          # ~285 weekday bars once weekends are dropped
TIMEOUT = 30


def qualify(ticker, dex=DEFAULT_DEX):
    """'NVDA' -> 'xyz:NVDA' — the venue's own asset name, and the key tapedeck
    uses internally so the same ticker can appear on two sources at once."""
    return f"{dex}:{ticker}"


def _post(body, timeout=TIMEOUT):
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def list_markets(dex=DEFAULT_DEX):
    """Live (non-delisted) market names on the dex, unqualified and sorted.

    The venue delists: 17 of 105 markets already are. A list built from this
    is a snapshot, not a constant.
    """
    meta = _post({"type": "meta", "dex": dex}) or {}
    names = []
    for asset in meta.get("universe") or []:
        if not isinstance(asset, dict) or asset.get("isDelisted"):
            continue
        name = str(asset.get("name") or "")
        names.append(name.split(":", 1)[1] if ":" in name else name)
    return sorted(n for n in names if n)


def _candles_to_frame(candles):
    """Venue candles -> the OHLCV frame the rest of tapedeck expects.

    Fields arrive as strings ({"t": 1785801600000, "o": "206.91", ...}) and `t`
    is the bar's opening time in epoch ms.
    """
    rows, index = [], []
    for c in candles or []:
        try:
            rows.append({"Open": float(c["o"]), "High": float(c["h"]),
                         "Low": float(c["l"]), "Close": float(c["c"]),
                         "Volume": float(c.get("v") or 0.0)})
            index.append(int(c["t"]))
        except (KeyError, TypeError, ValueError):
            continue          # one bad bar must not lose the whole series
    if not rows:
        return None
    idx = pd.to_datetime(pd.Index(index), unit="ms", utc=True).tz_localize(None)
    frame = pd.DataFrame(rows, index=idx).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame[frame.index.dayofweek < 5]     # drop Sat/Sun — see module docstring
    return frame if len(frame) else None


def _history_one(ticker, dex, start_ms, end_ms):
    key = qualify(ticker, dex)
    try:
        candles = _post({"type": "candleSnapshot",
                         "req": {"coin": key, "interval": "1d",
                                 "startTime": start_ms, "endTime": end_ms}})
        return key, _candles_to_frame(candles)
    except Exception:
        return key, None      # per-market failure degrades to n/a, never kills the run


def fetch_history(tickers, dex=DEFAULT_DEX, period_days=HISTORY_DAYS, now_ms=None,
                  max_workers=8):
    """{qualified key: DataFrame[Open,High,Low,Close,Volume]} on a DatetimeIndex.

    Markets that fail or return nothing are simply absent, exactly like
    fetch.fetch_history — tapedeck.py already warns about missing history.
    """
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return {}
    end_ms = int(pd.Timestamp.utcnow().timestamp() * 1000) if now_ms is None else int(now_ms)
    start_ms = end_ms - period_days * 86_400_000
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = pool.map(lambda t: _history_one(t, dex, start_ms, end_ms), tickers)
    return {key: frame for key, frame in results if frame is not None}


def fetch_universe(tickers, benchmarks, dex=DEFAULT_DEX, period_days=HISTORY_DAYS):
    """Same signature shape as fetch.fetch_universe, minus fundamentals.

    Returns (hists, bench_closes, infos) with infos always empty — the venue
    has none to give.
    """
    tickers = list(dict.fromkeys(tickers))
    benchmarks = list(dict.fromkeys(benchmarks))
    wanted = list(dict.fromkeys(tickers + benchmarks))
    all_hists = fetch_history(wanted, dex=dex, period_days=period_days)
    bench_closes = {qualify(b, dex): all_hists[qualify(b, dex)]["Close"]
                    for b in benchmarks if qualify(b, dex) in all_hists}
    keys = {qualify(t, dex) for t in tickers}
    hists = {k: v for k, v in all_hists.items() if k in keys}
    return hists, bench_closes, {}
