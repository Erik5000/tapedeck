"""All network access for the Situation tab: trade.xyz / HyperCore and FRED.

Nothing else in tapedeck/situation/ touches the network. Every fetch fails
alone: a failed series is absent from the result and its reason is in
``errors``, so the legs that need it read "no data" and the run continues.

No API key, nothing to sign up for. FRED's ``fredgraph.csv`` is the Fed's
public file. The venue is the same endpoint ``hlfetch`` already uses, and the
calls go through ``hlfetch._post`` so one stub covers both in tests. Venue
calls run one at a time and retry on HTTP 429 with a growing wait. The venue
part has a time limit, ``VENUE_BUDGET_S``: once it is spent, the remaining
venue calls are skipped, so a slow venue cannot stop the page from being written.

Funding history is cached per market in ``<cache_dir>/<market>.csv``
(``:`` becomes ``_``), so a run fetches only the rows after the last cached
one. Without a cache folder every run fetches all ``FUNDING_DAYS`` days.
"""

import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

from .. import hlfetch
from .crowding import write_atomic
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
VENUE_BUDGET_S = 90     # seconds for all venue calls of one run


def _get(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


_sleep = time.sleep     # tests replace it so no test waits
_clock = time.monotonic  # tests replace it to drive the time limit


class OutOfTime(Exception):
    """The venue time limit is spent; the call was not sent."""

    def __init__(self):
        super().__init__("skipped: time limit")


def _venue_post(body, deadline=None):
    """``hlfetch._post`` that waits and retries on HTTP 429. The venue refuses
    bursts for a moment, so a 429 is transient. Any other error raises at once.

    With a ``deadline`` (a ``_clock`` value): past it, the call is not sent
    (``OutOfTime``), and a wait that would end past it is not taken — the 429
    raises instead."""
    if deadline is not None and _clock() >= deadline:
        raise OutOfTime()
    for delay in RETRY_DELAYS:
        try:
            return hlfetch._post(body)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or (deadline is not None and _clock() + delay > deadline):
                raise
        print(f"warning: situation · venue rate limited, waiting {delay} s", file=sys.stderr)
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

def fetch_venue_closes(markets, errors=None, now_ms=None, deadline=None):
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
                         "startTime": start_ms, "endTime": end_ms}}, deadline))
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


def fetch_contexts(dex, wanted, deadline=None):
    return parse_contexts(_venue_post({"type": "metaAndAssetCtxs", "dex": dex}, deadline),
                          wanted)


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


def fetch_funding(market, now_ms, days=FUNDING_DAYS, start_ms=None, deadline=None):
    """Hourly funding for ``days`` days, or from ``start_ms`` when given. The
    venue pages at 500 rows, so the next page starts one millisecond after the
    last row of the previous one."""
    start = now_ms - days * 86_400_000 if start_ms is None else start_ms
    rows = []
    for _ in range(FUNDING_MAX_PAGES):
        batch = _venue_post({"type": "fundingHistory", "coin": market, "startTime": start},
                            deadline)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < FUNDING_PAGE:
            break
        start = int(batch[-1]["time"]) + 1
    return parse_funding(rows)


def _to_ms(ts):
    return int(ts.value // 1_000_000)


def funding_cache_path(cache_dir, market):
    return Path(cache_dir) / (market.replace(":", "_") + ".csv")


def read_funding_cache(path):
    """The cached hourly funding Series, or None. A missing file is None; an
    unreadable one is None with a warning, and the next write rebuilds it."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        frame = pd.read_csv(p, dtype={"time_ms": "int64", "rate": "float64"},
                            float_precision="round_trip")
        if list(frame.columns) != ["time_ms", "rate"] or not len(frame):
            raise ValueError("not a funding cache")
        if not np.isfinite(frame["rate"].values).all():
            raise ValueError("non-finite rate")
    except Exception:
        print(f"warning: situation · {p.name} unreadable — rebuilt", file=sys.stderr)
        return None
    idx = pd.to_datetime(frame["time_ms"].values, unit="ms")
    s = pd.Series(frame["rate"].values, index=idx).sort_index()
    return s[~s.index.duplicated(keep="last")]


def write_funding_cache(path, s):
    lines = "".join(f"{t},{float(r)!r}\n" for t, r in zip(s.index.asi8 // 1_000_000, s.values))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_atomic(Path(path), "time_ms,rate\n" + lines)


def fetch_funding_cached(market, now_ms, cache_dir, errors, deadline=None):
    """Cached funding plus the rows after it, trimmed to ``FUNDING_DAYS``.

    A failed fetch returns the cached Series (the reason still goes into
    ``errors``); with no cache the market is absent (None).
    """
    cutoff = now_ms - FUNDING_DAYS * 86_400_000
    path = funding_cache_path(cache_dir, market) if cache_dir is not None else None
    cached = read_funding_cache(path) if path is not None else None
    start = None if cached is None else max(_to_ms(cached.index[-1]) + 1, cutoff)
    try:
        new = fetch_funding(market, now_ms, start_ms=start, deadline=deadline)
    except Exception as exc:
        errors[f"{market} funding"] = _reason(exc)
        new, failed = None, True
    else:
        failed = False
    parts = [x for x in (cached, new) if x is not None]
    if not parts:
        if not failed:
            errors[f"{market} funding"] = "no funding rows"
        return None
    s = pd.concat(parts).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s[s.index >= pd.to_datetime(cutoff, unit="ms")]
    if not len(s):
        errors.setdefault(f"{market} funding", "no funding rows")
        return None
    if path is not None and not failed:
        try:
            write_funding_cache(path, s)
        except OSError as exc:
            print(f"warning: situation · {path.name} not saved ({exc})", file=sys.stderr)
    return s


# ---------- everything ----------

def fetch_all(today, now_ms=None, cache_dir=None):
    """Every input the tab needs. Never raises. ``cache_dir`` holds the
    funding cache; without it funding is fetched in full and not saved.

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
        deadline = _clock() + VENUE_BUDGET_S

        out["closes"] = fetch_venue_closes(VENUE_MARKETS, errors=out["errors"], now_ms=now_ms,
                                           deadline=deadline)
        for market in VENUE_MARKETS:
            if market not in out["closes"]:
                out["errors"].setdefault(f"{market} candles", "no candles")

        for dex in _by_dex(VENUE_MARKETS):
            try:
                out["ctx"].update(fetch_contexts(dex, set(VENUE_MARKETS), deadline))
            except Exception as exc:
                out["errors"][f"{dex} context"] = _reason(exc)

        for market in FUNDING_MARKETS:
            s = fetch_funding_cached(market, now_ms, cache_dir, out["errors"], deadline)
            if s is not None:
                out["funding"][market] = s

        for sid, s, err in fred_future:
            if s is not None:
                out["fred"][sid] = s
            else:
                out["errors"][f"FRED {sid}"] = err

    for source, reason in out["errors"].items():
        print(f"warning: situation · {source}: {reason}", file=sys.stderr)
    return out
