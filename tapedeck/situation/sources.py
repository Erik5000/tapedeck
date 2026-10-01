"""All network access for the Situation tab: trade.xyz / HyperCore and FRED.

Nothing else in tapedeck/situation/ touches the network. Every fetch fails
alone: a failed series is absent from the result and its reason is in
``errors``, so the legs that need it read "no data" and the run continues.

No API key, nothing to sign up for. FRED's ``fredgraph.csv`` is the Fed's
public file. The venue is the same endpoint ``hlfetch`` already uses, and the
calls go through ``hlfetch._post`` so one stub covers both in tests. Venue
calls run one at a time and retry on HTTP 429 with a growing wait.
"""

import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO

import pandas as pd

from .. import hlfetch
from .stats import finite

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
FRED_IDS = ("DGS2", "DGS10", "DGS30", "T10YIE", "T5YIE", "T5YIFR", "DFII10",
            "THREEFYTP10", "BAMLH0A0HYM2", "DCOILBRENTEU")
FRED_YEARS = 4          # 252-bar z + 252-bar gap scale + 60-bar beta, with room
VENUE_MARKETS = ("para:2Y", "para:10Y", "para:30Y", "mkts:USBOND", "xyz:TLT",
                 "xyz:BRENTOIL", "xyz:CL")
FUNDING_MARKETS = ("xyz:BRENTOIL", "xyz:CL", "para:10Y", "mkts:USBOND", "xyz:TLT")
FUNDING_DAYS = 180
FUNDING_PAGE = 500      # the venue returns at most this many rows per call
FUNDING_MAX_PAGES = 20
TIMEOUT = 30
RETRY_DELAYS = (1, 2, 4, 8)   # seconds to wait after each HTTP 429


def _get(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


_sleep = time.sleep     # tests replace it so no test waits


def _venue_post(body):
    """``hlfetch._post`` that waits and retries on HTTP 429. The venue refuses
    bursts for a moment, so a 429 is transient. Any other error raises at once."""
    for delay in RETRY_DELAYS:
        try:
            return hlfetch._post(body)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
        _sleep(delay)
    return hlfetch._post(body)


def _reason(exc):
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return "rate limited (HTTP 429)"
    return str(exc) or type(exc).__name__


def _by_dex(markets):
    groups = {}
    for market in markets:
        dex, ticker = market.split(":", 1)
        groups.setdefault(dex, []).append(ticker)
    return groups


# ---------- FRED ----------

def parse_fred_csv(text):
    """FRED CSV -> float Series on a DatetimeIndex, or None.

    The first column is the date whatever its header says (FRED has used both
    ``DATE`` and ``observation_date``). A missing day arrives as ``.`` or an
    empty cell and is dropped.
    """
    try:
        frame = pd.read_csv(StringIO(text))
    except Exception:
        return None
    if frame.shape[1] < 2 or not len(frame):
        return None
    dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    s = pd.Series(values.values, index=pd.DatetimeIndex(dates)).dropna()
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s if len(s) else None


def fetch_fred(series_id, today):
    start = (today - timedelta(days=365 * FRED_YEARS)).isoformat()
    return parse_fred_csv(_get(FRED_URL.format(id=series_id, start=start)))


# ---------- venue ----------

def fetch_venue_closes(markets, errors=None, now_ms=None):
    """{qualified market: daily Close Series}, fetched one market at a time.
    A market that fails or has no bars is absent; its reason goes into
    ``errors`` when given. One market never drops another."""
    end_ms = int(pd.Timestamp.utcnow().timestamp() * 1000) if now_ms is None else int(now_ms)
    start_ms = end_ms - hlfetch.HISTORY_DAYS * 86_400_000
    closes = {}
    for market in markets:
        try:
            frame = hlfetch._candles_to_frame(_venue_post(
                {"type": "candleSnapshot",
                 "req": {"coin": market, "interval": "1d",
                         "startTime": start_ms, "endTime": end_ms}}))
        except Exception as exc:
            if errors is not None:
                errors[f"{market} candles"] = _reason(exc)
            continue
        if frame is not None:
            closes[market] = frame["Close"]
    return closes


def parse_contexts(resp, wanted):
    """``metaAndAssetCtxs`` response -> {market: {mark, oracle, funding, oi,
    volume_24h}} for the wanted markets. Fields arrive as strings."""
    out = {}
    try:
        meta, ctxs = resp
        universe = meta.get("universe") or []
    except Exception:
        return out
    for asset, ctx in zip(universe, ctxs or []):
        name = asset.get("name") if isinstance(asset, dict) else None
        if name not in wanted or not isinstance(ctx, dict):
            continue
        out[name] = {"mark": finite(ctx.get("markPx")),
                     "oracle": finite(ctx.get("oraclePx")),
                     "funding": finite(ctx.get("funding")),
                     "oi": finite(ctx.get("openInterest")),
                     "volume_24h": finite(ctx.get("dayNtlVlm"))}
    return out


def fetch_contexts(dex, wanted):
    return parse_contexts(_venue_post({"type": "metaAndAssetCtxs", "dex": dex}), wanted)


def parse_funding(rows):
    """``fundingHistory`` rows -> hourly funding rate Series, or None."""
    times, rates = [], []
    for row in rows or []:
        try:
            t, rate = int(row["time"]), finite(row["fundingRate"])
        except (KeyError, TypeError, ValueError):
            continue
        if rate is not None:
            times.append(t)
            rates.append(rate)
    if not times:
        return None
    idx = pd.to_datetime(pd.Index(times), unit="ms", utc=True).tz_localize(None)
    s = pd.Series(rates, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def fetch_funding(market, now_ms, days=FUNDING_DAYS):
    """Hourly funding for ``days`` days. The venue pages at 500 rows, so the
    next page starts one millisecond after the last row of the previous one."""
    start = now_ms - days * 86_400_000
    rows = []
    for _ in range(FUNDING_MAX_PAGES):
        batch = _venue_post({"type": "fundingHistory", "coin": market, "startTime": start})
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < FUNDING_PAGE:
            break
        start = int(batch[-1]["time"]) + 1
    return parse_funding(rows)


# ---------- everything ----------

def fetch_all(today, now_ms=None):
    """Every input the tab needs. Never raises.

    Returns {"fred": {id: Series}, "closes": {market: Series},
             "ctx": {market: dict}, "funding": {market: Series},
             "errors": {source: reason}}.
    """
    if now_ms is None:
        now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
    out = {"fred": {}, "closes": {}, "ctx": {}, "funding": {}, "errors": {}}

    def fred_one(sid):
        try:
            s = fetch_fred(sid, today)
            return sid, s, None if s is not None else "empty or unreadable CSV"
        except Exception as exc:
            return sid, None, _reason(exc)

    # FRED runs in a pool while the venue calls run in order in this thread.
    with ThreadPoolExecutor(max_workers=8) as pool:
        fred_future = pool.map(fred_one, FRED_IDS)

        out["closes"] = fetch_venue_closes(VENUE_MARKETS, errors=out["errors"], now_ms=now_ms)
        for market in VENUE_MARKETS:
            if market not in out["closes"]:
                out["errors"].setdefault(f"{market} candles", "no candles")

        for dex in _by_dex(VENUE_MARKETS):
            try:
                out["ctx"].update(fetch_contexts(dex, set(VENUE_MARKETS)))
            except Exception as exc:
                out["errors"][f"{dex} context"] = _reason(exc)

        for market in FUNDING_MARKETS:
            try:
                s = fetch_funding(market, now_ms)
            except Exception as exc:
                out["errors"][f"{market} funding"] = _reason(exc)
                continue
            if s is not None:
                out["funding"][market] = s
            else:
                out["errors"][f"{market} funding"] = "no funding rows"

        for sid, s, err in fred_future:
            if s is not None:
                out["fred"][sid] = s
            else:
                out["errors"][f"FRED {sid}"] = err

    for source, reason in out["errors"].items():
        print(f"warning: situation · {source}: {reason}", file=sys.stderr)
    return out
