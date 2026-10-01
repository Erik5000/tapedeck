# Situation Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first "Situation" tab to tapedeck that reads bonds and oil together (rates regime, oil pass-through, venue crowding, four alerts), with the oil-tracker method.

**Architecture:** A new package `tapedeck/situation/`. `sources.py` is the only module with network access (trade.xyz through `hlfetch._post`, FRED through `fredgraph.csv`). Pure modules turn the inputs into legs, a regime label, crowding rows, alerts and confidence. `build_situation()` returns one dict; `render_multi(..., situation=)` shows it as the first tab, and `write_feed()` writes `output/situation-latest.json`. `tapedeck.py` calls it on every run unless `--no-situation`.

**Tech Stack:** Python 3.9, pandas 2.3, numpy 2.0, stdlib `urllib`, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-01-situation-tab-design.md`

## Global Constraints

- Python **3.9** (the repo `.venv`): no `X | None` annotations, no `match`, no parenthesised context managers.
- No new dependency. Network calls use stdlib `urllib` only.
- No Yahoo and no API key. The only sources are trade.xyz (`https://api.hyperliquid.xyz/info`, called through `hlfetch._post`) and FRED (`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`).
- Only `tapedeck/situation/sources.py` touches the network.
- Suppress, never fake: a leg without enough history shows "warming up (n/N)", a leg without data shows "no data". Neither shows a number.
- z-score window: **252 bars**. State words from |z|: under 1 `normal`; 1 to 2 `high` / `low`; over 2 `extreme high` / `extreme low`.
- Yield join: levels, only with at least **5** shared days and a mean absolute difference of **5 bp** or less. Brent join: daily % returns, never levels.
- Stale after **4** calendar days; `THREEFYTP10` after **10**.
- Alert thresholds are named constants in `tapedeck/situation/alerts.py`.
- `situation-latest.json` has `schema: 1`. New keys may be added; existing keys never change meaning.
- A failure in the Situation tab never stops the run. The page renders without the tab.
- Run tests with `.venv/bin/python3 -m pytest` from the repo root.
- Work on branch `situation-tab`. Commit messages are plain imperative sentences (see `git log`), and end with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.

## Review Focus

- **FRED data on a Tuesday after a Monday holiday** is 4 days old and must read fresh; 5 days must read stale. Test: `test_age_four_days_is_fresh_and_five_is_stale` (Task 4).
- **A half-written line in `situation-history.jsonl`** (a run stopped during the write) must be skipped with a warning, and the next run must rewrite the file cleanly. Test: `test_unreadable_line_is_skipped_with_a_warning` (Task 7).
- **NaN or infinity anywhere in the dict** must still give strict JSON in `situation-latest.json`, because other tools read it. Test: `test_feed_is_strict_json_even_with_nan` (Task 9).
- **A venue market that is delisted** (it disappears from candles and contexts) must blank only its own legs. Test: `test_a_delisted_market_only_blanks_its_own_legs` (Task 9).
- **A watchlist file named `situation.yaml`** must not clash with the tab: the tab name is `_situation`, and `_` files are never watchlists. Test: `test_a_watchlist_named_situation_does_not_clash` (Task 10).

## File map

| File | Responsibility |
|---|---|
| `tapedeck/situation/__init__.py` | `build_situation`, `write_feed` (Task 9; a docstring only until then) |
| `tapedeck/situation/stats.py` | `finite`, `clean`, `zscore`, `change`, `state_word`, `age_days` |
| `tapedeck/situation/sources.py` | All network access: FRED, venue candles, contexts, funding |
| `tapedeck/situation/series.py` | The two join rules, `prepare` |
| `tapedeck/situation/legs.py` | `make_leg`, `is_thin`, `build_rates_legs` |
| `tapedeck/situation/regime.py` | `regime_label` |
| `tapedeck/situation/oillink.py` | `compound`, beta, gap, `build_oil_legs` |
| `tapedeck/situation/crowding.py` | Funding stats, duration side, OI history file, `build_crowding` |
| `tapedeck/situation/alerts.py` | `build_alerts` |
| `tapedeck/situation/confidence.py` | `panel_confidence` |
| `tapedeck/situation/render.py` | `render_situation`, `TAB_NAME`, `TAB_TITLE` |
| `tapedeck/render.py` | `render_multi(..., situation=None)`, 3 CSS rules |
| `tapedeck.py` | `--no-situation`, the call, the feed write |
| `tests/conftest.py` | Blocks the network for every test |
| `tests/test_situation_*.py` | One test file per module |

## The leg dict (shared by Tasks 4, 6, 8, 9, 10)

```python
{"id": str, "label": str, "panel": "rates" | "oil", "unit": "%" | "bp" | "$" | "bp/1%",
 "higher": str,               # what a higher value means
 "src": "V" | "F" | "V+F" | None,
 "value": float | None, "chg20": float | None, "chg_unit": "bp" | "%" | "$",
 "z": float | None, "state": str | None, "age_days": int | None,
 "status": "ok" | "warming" | "stale" | "no_data",
 "n": int, "need": int,       # z basis length / bars needed (need 0 = leg has no z)
 "thin": bool, "note": str | None}
# be10 only: "chg_z": float | None (z of its 20-bar change series)
```

## The crowding row dict (shared by Tasks 7, 8, 9, 10)

```python
{"market": str, "panel": "rates" | "oil", "oi": float | None,
 "oi_chg_20d": float | None, "oi_days": int, "oi_need": 20,
 "funding_ann": float | None, "funding_z": float | None,
 "funding_days": int, "funding_need": 60,
 "side": "long duration crowded" | "short duration crowded" | None,
 "thin": bool, "status": "ok" | "warming" | "no_data", "note": str | None}
```

---
### Task 1: Stats helpers and the package

**Files:**
- Create: `tapedeck/situation/__init__.py`
- Create: `tapedeck/situation/stats.py`
- Test: `tests/test_situation_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `finite(x) -> float|None`, `clean(series) -> Series|None`, `zscore(series, window=252, center=True) -> float|None`, `change(series, bars=20) -> float|None`, `state_word(z) -> str|None`, `age_days(series, today) -> int|None`, constant `Z_WINDOW = 252`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_stats.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import stats


def days(values, end="2026-09-30"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_finite_refuses_bool_none_text_nan_and_inf():
    assert stats.finite(True) is None
    assert stats.finite(None) is None
    assert stats.finite("abc") is None
    assert stats.finite(float("nan")) is None
    assert stats.finite(float("inf")) is None
    assert stats.finite("5.25") == 5.25


def test_clean_drops_nan_and_inf_and_sorts():
    s = pd.Series([3.0, np.nan, np.inf, 1.0],
                  index=pd.to_datetime(["2026-09-04", "2026-09-03", "2026-09-02", "2026-09-01"]))
    out = stats.clean(s)
    assert list(out.values) == [1.0, 3.0]
    assert stats.clean(pd.Series([np.nan])) is None
    assert stats.clean(None) is None


def test_zscore_needs_a_full_window():
    assert stats.zscore(days(range(251))) is None
    assert stats.zscore(days(range(252))) is not None


def test_zscore_of_a_flat_series_is_none_not_infinite():
    assert stats.zscore(days([2.0] * 300)) is None


def test_zscore_uses_only_the_last_window():
    values = [1000.0] * 50 + list(np.linspace(0, 1, 252))
    z = stats.zscore(days(values))
    tail = pd.Series(np.linspace(0, 1, 252))
    assert z == pytest.approx((1.0 - tail.mean()) / tail.std(ddof=1))


def test_zscore_without_centre_divides_by_the_spread_only():
    values = list(np.linspace(-1, 1, 252))
    z = stats.zscore(days(values), center=False)
    assert z == pytest.approx(1.0 / pd.Series(values).std(ddof=1))


def test_change_over_twenty_bars():
    assert stats.change(days(range(30)), 20) == 20.0
    assert stats.change(days(range(20)), 20) is None


@pytest.mark.parametrize("z,word", [
    (0.99, "normal"), (-0.99, "normal"), (1.0, "high"), (2.0, "high"),
    (2.01, "extreme high"), (-1.5, "low"), (-2.5, "extreme low"), (None, None)])
def test_state_word_bands(z, word):
    assert stats.state_word(z) == word


def test_age_days_counts_calendar_days():
    assert stats.age_days(days([1.0], end="2026-09-25"), date(2026, 9, 29)) == 4
    assert stats.age_days(None, date(2026, 9, 29)) is None
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapedeck.situation'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/stats.py`:

```python
"""Small numeric helpers for the Situation tab. Pure — no IO, no network.

Every function returns None rather than a number it cannot stand behind: a
short series, a flat series or a non-finite value gives None, and the caller
shows "warming up" or "no data". Nothing here invents a default.
"""

import math

import numpy as np
import pandas as pd

Z_WINDOW = 252


def finite(x):
    """``x`` as a finite float, or None. Refuses bool (``float(True)`` would
    pass as 1.0), None, text that is not a number, NaN and infinity."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clean(series):
    """A float Series without NaN or infinity, sorted by date, or None if
    nothing is left."""
    if series is None:
        return None
    s = pd.to_numeric(pd.Series(series), errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan).dropna().astype(float).sort_index()
    return s if len(s) else None


def zscore(series, window=Z_WINDOW, center=True):
    """z of the last value against the last ``window`` values, the last one
    included. None when there are fewer than ``window`` values or the spread
    is zero.

    With ``center=False`` the last value is divided by the spread without
    subtracting the mean. The be_gap leg uses this: its gap is already a
    distance from "what the beta predicts", so zero is its natural centre.
    """
    s = clean(series)
    if s is None or len(s) < window:
        return None
    tail = s.iloc[-window:]
    sd = float(tail.std(ddof=1))
    if not math.isfinite(sd) or sd == 0:
        return None
    last = float(tail.iloc[-1])
    return finite((last - float(tail.mean())) / sd if center else last / sd)


def change(series, bars=20):
    """Last value minus the value ``bars`` bars back, or None."""
    s = clean(series)
    if s is None or len(s) <= bars:
        return None
    return finite(float(s.iloc[-1]) - float(s.iloc[-1 - bars]))


def state_word(z):
    """|z| under 1: normal. 1 to 2: high / low. Over 2: extreme high / low."""
    if z is None:
        return None
    side = "high" if z > 0 else "low"
    if abs(z) < 1:
        return "normal"
    return side if abs(z) <= 2 else f"extreme {side}"


def age_days(series, today):
    """Calendar days from the last value to ``today``, or None."""
    s = clean(series)
    if s is None:
        return None
    return (today - s.index[-1].date()).days
```

`tapedeck/situation/__init__.py` (Task 9 replaces it):

```python
"""Situation tab: bonds and oil. See docs/superpowers/specs/2026-10-01-situation-tab-design.md."""
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_stats.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/__init__.py tapedeck/situation/stats.py tests/test_situation_stats.py
git commit -m "Add stats helpers for the Situation tab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sources and the network guard

**Files:**
- Create: `tapedeck/situation/sources.py`
- Create: `tests/conftest.py`
- Test: `tests/test_situation_sources.py`

**Interfaces:**
- Consumes: `stats.finite`; `hlfetch._post(body, timeout)`, `hlfetch.fetch_history(tickers, dex=...)` (existing).
- Produces: `fetch_all(today, now_ms=None) -> {"fred": {id: Series}, "closes": {market: Series}, "ctx": {market: {mark, oracle, funding, oi, volume_24h}}, "funding": {market: Series}, "errors": {source: reason}}`; `_get(url, timeout)` (stubbed by tests); constants `FRED_IDS`, `VENUE_MARKETS`, `FUNDING_MARKETS`; `parse_fred_csv`, `parse_contexts`, `parse_funding`, `fetch_fred`, `fetch_funding`, `fetch_venue_closes`.

Write `tests/conftest.py` in Step 1 together with the test file. Every CLI run will build the Situation tab, and the CLI tests stub only the watchlist fetches. Without this guard they would call FRED and the venue.

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:

```python
"""Suite-wide guard: no test reaches the network.

Every CLI run builds the Situation tab, which fetches from FRED and the venue.
The CLI tests stub the watchlist fetches but not these, so without this guard
they would make real calls. A test that exercises the fetch code replaces
these stubs with its own (a later monkeypatch.setattr wins).
"""

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    from tapedeck import hlfetch
    from tapedeck.situation import sources

    def blocked(*args, **kwargs):
        raise RuntimeError("network blocked in tests")

    monkeypatch.setattr(hlfetch, "_post", blocked)
    monkeypatch.setattr(sources, "_get", blocked)
```

`tests/test_situation_sources.py`:

```python
"""Every test stubs ``sources._get`` (FRED) and ``hlfetch._post`` (venue).
tests/conftest.py blocks both by default, so a missed stub fails loudly."""

from datetime import date

import pytest

from tapedeck import hlfetch
from tapedeck.situation import sources

TODAY = date(2026, 10, 1)
NOW_MS = 1_790_000_000_000


def test_parse_fred_csv_new_header_and_missing_dots():
    text = "observation_date,T10YIE\n2026-09-28,2.35\n2026-09-29,.\n2026-09-30,2.36\n"
    s = sources.parse_fred_csv(text)
    assert list(s.values) == [2.35, 2.36]
    assert s.index[-1].date() == date(2026, 9, 30)


def test_parse_fred_csv_old_header_and_empty_cell():
    s = sources.parse_fred_csv("DATE,DGS10\n2026-09-29,4.12\n2026-09-30,\n")
    assert list(s.values) == [4.12]


@pytest.mark.parametrize("text", ["", "garbage", "DATE,DGS10\n", "<html>error</html>"])
def test_parse_fred_csv_unusable_text_is_none(text):
    assert sources.parse_fred_csv(text) is None


def test_fetch_fred_asks_for_four_years(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_get",
                        lambda url, timeout=30: seen.append(url) or "DATE,X\n2026-09-30,1\n")
    sources.fetch_fred("DGS10", TODAY)
    assert "id=DGS10" in seen[0] and "cosd=2022-10-02" in seen[0]


def test_parse_contexts_picks_wanted_markets_and_casts_strings():
    resp = [{"universe": [{"name": "para:10Y"}, {"name": "para:BTCD"}, "junk"]},
            [{"markPx": "5.31", "oraclePx": "5.32", "funding": "0.0000012",
              "openInterest": "444153.8", "dayNtlVlm": "762557.9"},
             {"markPx": "1"}, {"markPx": "2"}]]
    out = sources.parse_contexts(resp, {"para:10Y"})
    assert out == {"para:10Y": {"mark": 5.31, "oracle": 5.32, "funding": 0.0000012,
                                "oi": 444153.8, "volume_24h": 762557.9}}


def test_parse_contexts_malformed_response_is_empty():
    assert sources.parse_contexts(None, {"para:10Y"}) == {}
    assert sources.parse_contexts({"universe": []}, {"para:10Y"}) == {}


def test_fetch_funding_pages_until_a_short_page(monkeypatch):
    calls = []
    page1 = [{"time": NOW_MS - 1000 * (600 - i), "fundingRate": "0.00001"} for i in range(500)]
    page2 = [{"time": NOW_MS - 10, "fundingRate": "0.00002"}]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        calls.append(body)
        return page1 if len(calls) == 1 else page2

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    s = sources.fetch_funding("para:10Y", NOW_MS)
    assert len(s) == 501
    assert calls[1]["startTime"] == page1[-1]["time"] + 1
    assert calls[0]["coin"] == "para:10Y"


def test_parse_funding_skips_bad_rows():
    rows = [{"time": NOW_MS, "fundingRate": "0.00001"}, {"time": "x"}, {"fundingRate": "1"},
            {"time": NOW_MS + 1, "fundingRate": "nan"}]
    assert len(sources.parse_funding(rows)) == 1
    assert sources.parse_funding([]) is None


def _venue_stub(contexts_ok=True):
    candle = [{"t": 1790726400000, "o": "1", "h": "1", "l": "1", "c": "5.3", "v": "1"}]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        if body["type"] == "candleSnapshot":
            return candle if body["req"]["coin"] != "para:30Y" else []
        if body["type"] == "metaAndAssetCtxs":
            if not contexts_ok:
                raise TimeoutError("venue timeout")
            return [{"universe": [{"name": "para:10Y"}]}, [{"markPx": "5.3", "openInterest": "1"}]]
        if body["type"] == "fundingHistory":
            return [{"time": NOW_MS, "fundingRate": "0.00001"}]
        raise AssertionError(body)
    return fake_post


def test_fetch_all_collects_each_source_and_records_failures(monkeypatch, capsys):
    def fake_get(url, timeout=30):
        if "id=DGS30" in url:
            raise TimeoutError("timed out")
        return "DATE,X\n2026-09-30,1.5\n"

    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(hlfetch, "_post", _venue_stub())
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert "DGS10" in out["fred"] and "DGS30" not in out["fred"]
    assert out["errors"]["FRED DGS30"] == "timed out"
    assert "para:10Y" in out["closes"] and "para:30Y" not in out["closes"]
    assert out["errors"]["para:30Y candles"] == "no candles"
    assert out["ctx"]["para:10Y"]["mark"] == 5.3
    assert set(out["funding"]) == set(sources.FUNDING_MARKETS)
    assert "FRED DGS30" in capsys.readouterr().err


def test_fetch_all_context_failure_is_one_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url, timeout=30: "DATE,X\n2026-09-30,1\n")
    monkeypatch.setattr(hlfetch, "_post", _venue_stub(contexts_ok=False))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert out["ctx"] == {}
    assert out["errors"]["para context"] == "venue timeout"


def test_fetch_all_with_the_network_blocked_returns_empty_and_never_raises():
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert out["fred"] == {} and out["closes"] == {} and out["ctx"] == {} and out["funding"] == {}
    assert len(out["errors"]) > 0
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_sources.py -q`
Expected: FAIL — `ImportError` (no `sources` module; `tests/conftest.py` imports it too, so every test errors)

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/sources.py`:

```python
"""All network access for the Situation tab: trade.xyz / HyperCore and FRED.

Nothing else in tapedeck/situation/ touches the network. Every fetch fails
alone: a failed series is absent from the result and its reason is in
``errors``, so the legs that need it read "no data" and the run continues.

No API key, nothing to sign up for. FRED's ``fredgraph.csv`` is the Fed's
public file. The venue is the same endpoint ``hlfetch`` already uses, and the
calls go through ``hlfetch._post`` so one stub covers both in tests.
"""

import sys
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


def _get(url, timeout=TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


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

def fetch_venue_closes(markets):
    """{qualified market: daily Close Series}. A market that fails is absent —
    ``hlfetch.fetch_history`` already degrades per market."""
    closes = {}
    for dex, tickers in _by_dex(markets).items():
        for key, frame in hlfetch.fetch_history(tickers, dex=dex).items():
            closes[key] = frame["Close"]
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
    return parse_contexts(hlfetch._post({"type": "metaAndAssetCtxs", "dex": dex}), wanted)


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
        batch = hlfetch._post({"type": "fundingHistory", "coin": market, "startTime": start})
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
            return sid, None, str(exc) or type(exc).__name__

    def funding_one(market):
        try:
            s = fetch_funding(market, now_ms)
            return market, s, None if s is not None else "no funding rows"
        except Exception as exc:
            return market, None, str(exc) or type(exc).__name__

    with ThreadPoolExecutor(max_workers=8) as pool:
        fred_results = list(pool.map(fred_one, FRED_IDS))
        funding_results = list(pool.map(funding_one, FUNDING_MARKETS))
    for sid, s, err in fred_results:
        if s is not None:
            out["fred"][sid] = s
        else:
            out["errors"][f"FRED {sid}"] = err
    for market, s, err in funding_results:
        if s is not None:
            out["funding"][market] = s
        else:
            out["errors"][f"{market} funding"] = err

    try:
        out["closes"] = fetch_venue_closes(VENUE_MARKETS)
    except Exception as exc:
        out["errors"]["venue candles"] = str(exc) or type(exc).__name__
    for market in VENUE_MARKETS:
        if market not in out["closes"]:
            out["errors"].setdefault(f"{market} candles", "no candles")

    for dex in _by_dex(VENUE_MARKETS):
        try:
            out["ctx"].update(fetch_contexts(dex, set(VENUE_MARKETS)))
        except Exception as exc:
            out["errors"][f"{dex} context"] = str(exc) or type(exc).__name__

    for source, reason in out["errors"].items():
        print(f"warning: situation · {source}: {reason}", file=sys.stderr)
    return out
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_sources.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/sources.py tests/conftest.py tests/test_situation_sources.py
git commit -m "Add the Situation sources: trade.xyz and FRED, and block the network in tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: History joins

**Files:**
- Create: `tapedeck/situation/series.py`
- Test: `tests/test_situation_series.py`

**Interfaces:**
- Consumes: `stats.clean`; the `fetch_all` dict from Task 2.
- Produces: `by_day(series)`, `join_levels(fred, venue) -> {"series", "live", "src", "joined", "note"}`, `join_returns(fred_level, venue_level) -> Series|None` (daily %), `prepare(src) -> {"y2"|"y10"|"y30": join_levels result, "brent": {"returns", "level", "src"}, "wti": Series|None}`; constants `JOIN_TOL = 0.05`, `JOIN_MIN_OVERLAP = 5`, `YIELD_PAIRS`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_series.py`:

```python
import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import series


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


FRED = days(np.linspace(4.0, 5.0, 300))                    # ends 2026-09-30


def venue_like(offset, n=20, end="2026-10-01"):
    """Venue yields that track FRED plus ``offset`` (percent), one bar past it."""
    idx = pd.bdate_range(end=end, periods=n)
    base = FRED.reindex(idx).ffill().fillna(5.0)
    return pd.Series(base.values + offset, index=idx)


def test_join_levels_joins_when_within_five_bp():
    venue = venue_like(0.04)
    out = series.join_levels(FRED, venue)
    assert out["joined"] and out["src"] == "V+F" and out["note"] is None
    s = out["series"]
    assert s.index[-1] == venue.index[-1]
    assert (s[s.index < venue.index[0]] == FRED[FRED.index < venue.index[0]]).all()
    assert out["live"] == venue.iloc[-1]


def test_join_levels_refuses_over_five_bp():
    venue = venue_like(0.06)
    out = series.join_levels(FRED, venue)
    assert not out["joined"] and out["src"] == "F"
    assert out["series"].index[-1] == FRED.index[-1]
    assert out["live"] == venue.iloc[-1]
    assert "6.0 bp apart" in out["note"]


def test_join_levels_refuses_with_fewer_than_five_shared_days():
    venue = venue_like(0.0, n=5)                  # 4 shared days + 1 day past FRED
    out = series.join_levels(FRED, venue)
    assert not out["joined"]
    assert "only 4 shared days" in out["note"]


def test_join_levels_one_side_missing():
    assert series.join_levels(FRED, None)["src"] == "F"
    assert series.join_levels(None, venue_like(0.0))["src"] == "V"
    assert series.join_levels(None, None)["series"] is None


def test_join_returns_has_no_jump_at_the_join():
    spot = days([80.0] * 250 + [80.0 * 1.01 ** i for i in range(1, 51)])
    idx = pd.bdate_range(start=spot.index[260], periods=60)
    perp = pd.Series(90.0 * 1.01 ** np.arange(60), index=idx)   # $10 above spot
    r = series.join_returns(spot, perp)
    assert r.max() == pytest.approx(1.0)                         # never the $10 gap
    assert r.index.is_monotonic_increasing and not r.index.duplicated().any()
    assert idx[0] not in r.index                                 # first venue day has no return


def test_prepare_shapes_the_inputs():
    src = {"fred": {"DGS10": FRED, "DCOILBRENTEU": days([80.0, 81.0, 82.0])},
           "closes": {"para:10Y": venue_like(0.0), "xyz:CL": days([90.0, 91.0])}}
    prep = series.prepare(src)
    assert prep["y10"]["joined"]
    assert prep["y2"]["series"] is None
    assert prep["brent"]["src"] == "F" and len(prep["brent"]["returns"]) == 2
    assert list(prep["wti"].values) == [90.0, 91.0]
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_series.py -q`
Expected: FAIL — `ImportError: cannot import name 'series'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/series.py`:

```python
"""History joins: FRED supplies the years the young venue markets lack. Pure.

Two rules, one per kind of series (spec: "History join rules"):

* Yields join on **levels**, but only when the venue and FRED agree.
* Brent joins on **daily % returns**, never on levels: the perp is a futures
  price and FRED Brent is spot, so the two levels differ by the curve spread.
"""

import pandas as pd

from .stats import clean

JOIN_TOL = 0.05          # 5 bp, in the percent units both sources use
JOIN_MIN_OVERLAP = 5
YIELD_PAIRS = {"y2": ("DGS2", "para:2Y"), "y10": ("DGS10", "para:10Y"),
               "y30": ("DGS30", "para:30Y")}


def by_day(series):
    """``clean`` plus one value per calendar day, on a midnight index."""
    s = clean(series)
    if s is None:
        return None
    s = s.copy()
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s[~s.index.duplicated(keep="last")]


def join_levels(fred, venue, tol=JOIN_TOL, min_overlap=JOIN_MIN_OVERLAP):
    """Join a FRED yield history to a venue yield series.

    Returns {"series", "live", "src", "joined", "note"}:

    * They agree (at least ``min_overlap`` shared days, mean |difference| at
      most ``tol``): FRED before the first venue day, then the venue. src V+F.
    * They disagree, or share too few days: the history is FRED only and
      ``live`` is the venue's last value. src F, and the note says why.
    * One side is missing: the other side alone. src F or V.
    """
    f, v = by_day(fred), by_day(venue)
    if f is None and v is None:
        return {"series": None, "live": None, "src": None, "joined": False, "note": "no data"}
    if v is None:
        return {"series": f, "live": float(f.iloc[-1]), "src": "F", "joined": False,
                "note": "venue: no data"}
    if f is None:
        return {"series": v, "live": float(v.iloc[-1]), "src": "V", "joined": False,
                "note": "FRED: no data"}
    shared = f.index.intersection(v.index)
    if len(shared) >= min_overlap:
        gap = float((f.loc[shared] - v.loc[shared]).abs().mean())
        if round(gap, 9) <= tol:
            joined = pd.concat([f[f.index < v.index[0]], v])
            return {"series": joined, "live": float(v.iloc[-1]), "src": "V+F",
                    "joined": True, "note": None}
        why = f"{gap * 100:.1f} bp apart"
    else:
        why = f"only {len(shared)} shared days"
    return {"series": f, "live": float(v.iloc[-1]), "src": "F", "joined": False,
            "note": f"venue ≠ FRED ({why}), not joined: value is venue, z is FRED"}


def join_returns(fred_level, venue_level):
    """Daily % returns: FRED before the first venue day, then the venue.

    The first venue return is measured venue-to-venue, so no return spans the
    two sources and the join never shows a false jump.
    """
    f, v = by_day(fred_level), by_day(venue_level)
    parts = []
    if f is not None:
        fr = f.pct_change().dropna() * 100
        if v is not None:
            fr = fr[fr.index < v.index[0]]
        parts.append(fr)
    if v is not None:
        parts.append(v.pct_change().dropna() * 100)
    parts = [p for p in parts if len(p)]
    if not parts:
        return None
    out = pd.concat(parts).sort_index()
    return out[~out.index.duplicated(keep="last")]


def prepare(src):
    """The joined inputs the legs read.

    {"y2"|"y10"|"y30": join_levels result,
     "brent": {"returns", "level", "src"},
     "wti": venue CL closes or None}
    """
    fred, closes = src.get("fred") or {}, src.get("closes") or {}
    prep = {key: join_levels(fred.get(fid), closes.get(market))
            for key, (fid, market) in YIELD_PAIRS.items()}
    brent_v, brent_f = by_day(closes.get("xyz:BRENTOIL")), by_day(fred.get("DCOILBRENTEU"))
    tags = [t for t, s in (("V", brent_v), ("F", brent_f)) if s is not None]
    prep["brent"] = {"returns": join_returns(brent_f, brent_v),
                     "level": brent_v if brent_v is not None else brent_f,
                     "src": "+".join(tags) or None}
    prep["wti"] = by_day(closes.get("xyz:CL"))
    return prep
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_series.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/series.py tests/test_situation_series.py
git commit -m "Join FRED history to the young venue markets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Leg builder and the rates legs

**Files:**
- Create: `tapedeck/situation/legs.py`
- Test: `tests/test_situation_legs.py`

**Interfaces:**
- Consumes: `stats.*`; `series.prepare` output.
- Produces: `make_leg(leg_id, label, panel, unit, higher, series, today, *, src, value=_AUTO, chg20=_AUTO, chg_mult=100.0, chg_unit="bp", z_series=_AUTO, center=True, with_z=True, min_bars=252, stale_days=4, thin=False, note=None) -> leg dict`; `is_thin(ctx) -> bool`; `build_rates_legs(prep, src, today) -> [leg]` in `RATE_LEGS` order; constants `RATE_LEGS`, `YIELD_MARKET`, `CURVES`, `STALE_DAYS`.

The direction tests pin what a higher value means for every leg. Keep them: a sign flip is the bug that still produces a plausible number.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_legs.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import legs, series

TODAY = date(2026, 9, 30)


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


def rising(start, stop, n=300, end="2026-09-30"):
    """A rising series with a little noise, so the last value is the high."""
    noise = np.random.default_rng(7).normal(0, 0.001, n)
    return days(np.linspace(start, stop, n) + noise, end=end)


def make(series_, **kw):
    return legs.make_leg("x", "X", "rates", "%", "higher", series_, TODAY, src="F", **kw)


# ---------- make_leg ----------

def test_no_series_is_no_data_with_a_note():
    leg = make(None)
    assert leg["status"] == "no_data" and leg["value"] is None and leg["z"] is None
    assert leg["note"] == "no data"


def test_short_series_is_warming_and_has_no_z():
    leg = make(days(np.linspace(1, 2, 100)))
    assert leg["status"] == "warming" and leg["z"] is None
    assert (leg["n"], leg["need"]) == (100, 252)
    assert leg["value"] == 2.0


def test_full_series_gives_value_change_z_and_state():
    leg = make(days(np.linspace(1, 2, 300)))
    assert leg["status"] == "ok"
    assert leg["chg20"] == pytest.approx((1 / 299) * 20 * 100)
    assert leg["z"] > 1 and leg["state"] in ("high", "extreme high")


def test_age_four_days_is_fresh_and_five_is_stale():
    # Friday data read on Tuesday after a Monday holiday is 4 days old: fresh.
    tuesday = date(2026, 9, 29)
    friday, thursday = days(np.linspace(1, 2, 300), end="2026-09-25"), days(np.linspace(1, 2, 300), end="2026-09-24")
    assert legs.make_leg("x", "X", "rates", "%", "h", friday, tuesday, src="F")["status"] == "ok"
    assert legs.make_leg("x", "X", "rates", "%", "h", thursday, tuesday, src="F")["status"] == "stale"


def test_explicit_value_and_z_series_are_used():
    leg = make(days([1.0] * 300), value=9.0, chg20=None, z_series=days(np.linspace(0, 1, 300)))
    assert leg["value"] == 9.0 and leg["chg20"] is None and leg["z"] > 0


def test_with_z_false_never_warms():
    leg = make(days([1.0, 2.0]), with_z=False)
    assert leg["status"] == "ok" and leg["need"] == 0


@pytest.mark.parametrize("ctx,thin", [
    (None, False), ({"volume_24h": 99_999.0}, True), ({"volume_24h": 1e6}, False),
    ({"volume_24h": 1e6, "mark": 5.04, "oracle": 5.0}, True),
    ({"volume_24h": 1e6, "mark": 5.02, "oracle": 5.0}, False)])
def test_is_thin(ctx, thin):
    assert legs.is_thin(ctx) is thin


# ---------- direction: one test per leg ----------

HIGHER = {
    "y2": "higher yield", "y10": "higher yield", "y30": "higher yield",
    "curve_2s10s": "steeper", "curve_10s30s": "steeper",
    "be10": "more priced inflation", "be5y5y": "more priced long-run inflation",
    "real10": "tighter money", "term_premium": "more pay for duration risk",
    "rate_vol": "more rate volatility", "credit": "more credit stress",
}


def test_every_rate_leg_states_its_direction():
    assert {k: v[3] for k, v in legs.RATE_LEGS.items()} == HIGHER


def rising_src():
    """Every input rising; the long end rises fastest, and y10's swings grow."""
    y10 = rising(4.0, 5.0)
    swing = np.sin(np.arange(300)) * np.linspace(0.001, 0.05, 300)
    fred = {"DGS2": rising(4.0, 4.2), "DGS10": y10 + swing, "DGS30": rising(4.0, 6.0),
            "T10YIE": rising(2.0, 2.5), "T5YIFR": rising(2.0, 2.5), "DFII10": rising(1.5, 2.5),
            "THREEFYTP10": rising(0.2, 1.0), "BAMLH0A0HYM2": rising(3.0, 5.0)}
    return {"fred": fred, "closes": {}, "ctx": {}}


@pytest.mark.parametrize("leg_id", [k for k in legs.RATE_LEGS if k != "rate_vol"])
def test_rising_input_gives_positive_z(leg_id):
    src = rising_src()
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built[leg_id]["z"] > 0, leg_id


def test_growing_swings_give_positive_rate_vol_z():
    src = rising_src()
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["rate_vol"]["status"] == "ok" and built["rate_vol"]["z"] > 0


# ---------- build_rates_legs ----------

def test_rates_legs_come_in_display_order_with_sources():
    src = rising_src()
    built = legs.build_rates_legs(series.prepare(src), src, TODAY)
    assert [leg["id"] for leg in built] == list(legs.RATE_LEGS)
    by_id = {leg["id"]: leg for leg in built}
    assert by_id["be10"]["src"] == "F" and by_id["y10"]["src"] == "F"
    assert by_id["curve_2s10s"]["unit"] == "bp"
    assert "chg_z" in by_id["be10"]


def test_no_inputs_give_no_data_legs_not_a_crash():
    src = {"fred": {}, "closes": {}, "ctx": {}}
    built = legs.build_rates_legs(series.prepare(src), src, TODAY)
    assert {leg["status"] for leg in built} == {"no_data"}
    assert {leg["id"]: leg for leg in built}["be10"]["chg_z"] is None


def test_term_premium_stays_fresh_for_ten_days():
    src = {"fred": {"THREEFYTP10": rising(0.2, 1.0, end="2026-09-22")}, "closes": {}, "ctx": {}}
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["term_premium"]["status"] == "ok"


def test_thin_venue_market_marks_its_leg():
    src = rising_src()
    src["ctx"] = {"para:30Y": {"volume_24h": 22_000.0}}
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["y30"]["thin"] and built["curve_10s30s"]["thin"]
    assert not built["y10"]["thin"]
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_legs.py -q`
Expected: FAIL — `ImportError: cannot import name 'legs'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/legs.py`:

```python
"""The legs as data, and the one function that turns a series into a leg row.

Every leg states what a higher value means. The z-score is always taken on
the value in its natural orientation, so "higher z" and "higher means" never
disagree. tests/test_situation_legs.py pins each direction — a sign flip is
the bug that still produces a plausible number (oil-tracker brief §2.1). Pure.
"""

import math

from . import stats
from .stats import clean

MIN_BARS = stats.Z_WINDOW
STALE_DAYS = 4
THIN_VOLUME = 100_000          # $ per 24h
THIN_MARK_GAP = 0.005          # |mark − oracle| / oracle

# id -> (label, panel, unit, higher means). Order is display order.
RATE_LEGS = {
    "y2": ("2Y", "rates", "%", "higher yield"),
    "y10": ("10Y", "rates", "%", "higher yield"),
    "y30": ("30Y", "rates", "%", "higher yield"),
    "curve_2s10s": ("2s10s", "rates", "bp", "steeper"),
    "curve_10s30s": ("10s30s", "rates", "bp", "steeper"),
    "be10": ("BE 10Y", "rates", "%", "more priced inflation"),
    "be5y5y": ("BE 5y5y", "rates", "%", "more priced long-run inflation"),
    "real10": ("Real 10Y", "rates", "%", "tighter money"),
    "term_premium": ("Term prem", "rates", "%", "more pay for duration risk"),
    "rate_vol": ("Rate vol", "rates", "bp", "more rate volatility"),
    "credit": ("HY spread", "rates", "%", "more credit stress"),
}
FRED_LEGS = (("be10", "T10YIE"), ("be5y5y", "T5YIFR"), ("real10", "DFII10"),
             ("term_premium", "THREEFYTP10"), ("credit", "BAMLH0A0HYM2"))
STALE_OVERRIDE = {"term_premium": 10}     # THREEFYTP10 publishes ~1 week late
YIELD_MARKET = {"y2": "para:2Y", "y10": "para:10Y", "y30": "para:30Y"}
CURVES = (("curve_2s10s", "y10", "y2"), ("curve_10s30s", "y30", "y10"))

_AUTO = object()


def is_thin(ctx):
    """A venue market too thin to trust fully: 24h volume under $100k, or the
    mark more than 0.5% from the oracle. Unknown context is not thin — a leg
    without data is scored as "no data" on its own."""
    if not ctx:
        return False
    vol = ctx.get("volume_24h")
    if vol is not None and vol < THIN_VOLUME:
        return True
    mark, oracle = ctx.get("mark"), ctx.get("oracle")
    if mark is not None and oracle:
        return abs(mark - oracle) / oracle > THIN_MARK_GAP
    return False


def make_leg(leg_id, label, panel, unit, higher, series, today, *, src, value=_AUTO,
             chg20=_AUTO, chg_mult=100.0, chg_unit="bp", z_series=_AUTO, center=True,
             with_z=True, min_bars=MIN_BARS, stale_days=STALE_DAYS, thin=False, note=None):
    """One leg row. ``series`` is the level series: it gives the data age, and
    by default the value, the 20-bar change (× ``chg_mult``) and the z basis.

    status: "no_data" (no series), "warming" (z basis shorter than
    ``min_bars``), "stale" (older than ``stale_days``), else "ok". A warming
    leg has z None — never a default.
    """
    s = clean(series)
    leg = {"id": leg_id, "label": label, "panel": panel, "unit": unit, "higher": higher,
           "src": src, "value": None, "chg20": None, "chg_unit": chg_unit, "z": None,
           "state": None, "age_days": None, "status": "no_data", "n": 0,
           "need": min_bars if with_z else 0, "thin": bool(thin), "note": note}
    if s is None:
        leg["note"] = note or "no data"
        return leg
    leg["value"] = float(s.iloc[-1]) if value is _AUTO else stats.finite(value)
    if chg20 is _AUTO:
        c = stats.change(s, 20)
        chg20 = None if c is None else c * chg_mult
    leg["chg20"] = stats.finite(chg20)
    leg["age_days"] = stats.age_days(s, today)
    status = "ok"
    if with_z:
        zs = s if z_series is _AUTO else clean(z_series)
        leg["n"] = 0 if zs is None else len(zs)
        if leg["n"] < min_bars:
            status = "warming"
        else:
            leg["z"] = stats.zscore(zs, min_bars, center=center)
            leg["state"] = stats.state_word(leg["z"])
    if leg["age_days"] is not None and leg["age_days"] > stale_days:
        status = "stale"
    leg["status"] = status
    return leg


def _rate_leg(leg_id, series, today, **kw):
    label, panel, unit, higher = RATE_LEGS[leg_id]
    kw.setdefault("stale_days", STALE_OVERRIDE.get(leg_id, STALE_DAYS))
    return make_leg(leg_id, label, panel, unit, higher, series, today, **kw)


def _thin(ctx, *markets):
    return any(is_thin((ctx or {}).get(m)) for m in markets)


def build_rates_legs(prep, src, today):
    """Panel A legs, in display order. ``prep`` comes from series.prepare."""
    fred, ctx = src.get("fred") or {}, src.get("ctx") or {}
    legs = []
    for leg_id, market in YIELD_MARKET.items():
        j = prep[leg_id]
        legs.append(_rate_leg(leg_id, j["series"], today, src=j["src"], value=j["live"],
                              thin=_thin(ctx, market), note=j["note"]))

    for leg_id, long_end, short_end in CURVES:
        a, b = prep[long_end], prep[short_end]
        curve = None
        if a["series"] is not None and b["series"] is not None:
            curve = (a["series"] - b["series"]).dropna() * 100
        tag = a["src"] if a["src"] == b["src"] else "V+F"
        legs.append(_rate_leg(leg_id, curve, today, src=tag if curve is not None else None,
                              chg_mult=1.0,
                              thin=_thin(ctx, YIELD_MARKET[long_end], YIELD_MARKET[short_end])))

    for leg_id, fid in FRED_LEGS:
        s = fred.get(fid)
        leg = _rate_leg(leg_id, s, today, src="F" if s is not None else None)
        if leg_id == "be10":
            cs = clean(s)
            leg["chg_z"] = None if cs is None else stats.zscore((cs - cs.shift(20)).dropna())
        legs.append(leg)

    y10 = clean(prep["y10"]["series"])
    vol = None
    if y10 is not None:
        vol = ((y10.diff() * 100).rolling(20).std() * math.sqrt(252)).dropna()
    legs.append(_rate_leg("rate_vol", vol, today, src=prep["y10"]["src"], chg_mult=1.0,
                          thin=_thin(ctx, "para:10Y")))

    order = list(RATE_LEGS)
    return sorted(legs, key=lambda leg: order.index(leg["id"]))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_legs.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/legs.py tests/test_situation_legs.py
git commit -m "Add the leg builder and the rates legs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Regime label

**Files:**
- Create: `tapedeck/situation/regime.py`
- Test: `tests/test_situation_regime.py`

**Interfaces:**
- Consumes: `stats.clean`.
- Produces: `regime_label(dgs10, t10yie, dfii10, bars=20, threshold_bp=10.0) -> {"label": str|None, "d10", "dbe", "dreal" (bp), "asof": "YYYY-MM-DD", "note": str|None}`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_regime.py`:

```python
import pandas as pd
import pytest

from tapedeck.situation import regime


def move(start, end, n=21):
    """A series that goes from ``start`` to ``end`` over the last 20 bars."""
    idx = pd.bdate_range(end="2026-09-30", periods=n)
    return pd.Series([start] * (n - 1) + [end], index=idx, dtype=float)


def label(dbe_bp, dreal_bp):
    be, real = 2.30, 2.00
    be_end, real_end = be + dbe_bp / 100, real + dreal_bp / 100
    return regime.regime_label(move(be + real, be_end + real_end), move(be, be_end),
                               move(real, real_end))


@pytest.mark.parametrize("dbe,dreal,expected", [
    (3, 2, "Range-bound"),
    (20, 5, "Inflation-led sell-off"),
    (5, 20, "Real-rate-led sell-off"),
    (-5, -20, "Growth-scare rally"),
    (-20, -5, "Disinflation rally"),
])
def test_the_five_labels(dbe, dreal, expected):
    assert label(dbe, dreal)["label"] == expected


def test_exactly_ten_bp_is_a_move_not_a_range():
    assert label(5, 5)["label"] == "Real-rate-led sell-off"       # +10, equal parts
    assert label(-5, -5)["label"] == "Disinflation rally"          # −10, equal parts


def test_the_split_adds_up_and_carries_the_fred_date():
    out = label(7, 24)
    assert (out["d10"], out["dbe"], out["dreal"]) == (31.0, 7.0, 24.0)
    assert out["asof"] == "2026-09-30"


def test_missing_input_gives_no_label_and_a_reason():
    out = regime.regime_label(move(4, 5), None, move(2, 2))
    assert out["label"] is None and "DFII10" in out["note"]


def test_too_few_shared_days_is_warming():
    out = regime.regime_label(move(4, 5, n=10), move(2, 2, n=10), move(2, 3, n=10))
    assert out["label"] is None and out["note"] == "warming up (10/21)"
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_regime.py -q`
Expected: FAIL — `ImportError: cannot import name 'regime'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/regime.py`:

```python
"""The regime label: which part moved the 10Y. Pure.

FRED defines T10YIE as DGS10 − DFII10, so over any window
Δ nominal = Δ breakeven + Δ real yield. All three come from FRED, so the
split adds up exactly, and the label carries the FRED date.
"""

import pandas as pd

from .stats import clean

BARS = 20
THRESHOLD_BP = 10.0


def regime_label(dgs10, t10yie, dfii10, bars=BARS, threshold_bp=THRESHOLD_BP):
    """{"label", "d10", "dbe", "dreal", "asof", "note"}; changes in bp.

    The label is None, and the note says why, when an input is missing or the
    three share no more than ``bars`` days.
    """
    parts = [clean(s) for s in (dgs10, t10yie, dfii10)]
    if any(p is None for p in parts):
        return {"label": None, "note": "needs DGS10, T10YIE and DFII10 from FRED"}
    frame = pd.concat(parts, axis=1, join="inner")
    if len(frame) <= bars:
        return {"label": None, "note": f"warming up ({len(frame)}/{bars + 1})"}
    # round(…, 6): (5.10 − 5.00) × 100 is 9.999999999999787 in floats.
    d10, dbe, dreal = (round(float(x) * 100, 6) for x in frame.iloc[-1] - frame.iloc[-1 - bars])
    if abs(d10) < threshold_bp:
        label = "Range-bound"
    elif d10 > 0:
        label = "Inflation-led sell-off" if dbe > dreal else "Real-rate-led sell-off"
    else:
        label = "Growth-scare rally" if dreal < dbe else "Disinflation rally"
    return {"label": label, "d10": d10, "dbe": dbe, "dreal": dreal,
            "asof": frame.index[-1].date().isoformat(), "note": None}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_regime.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/regime.py tests/test_situation_regime.py
git commit -m "Add the rates regime label

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Oil link

**Files:**
- Create: `tapedeck/situation/oillink.py`
- Test: `tests/test_situation_oillink.py`

**Interfaces:**
- Consumes: `legs.make_leg`, `legs.is_thin`, `stats.clean`, `series.prepare` output.
- Produces: `compound(returns, bars=20)`, `be_beta_series(be5, brent_ret, bars=60)`, `be_gap_series(be5, brent_ret, beta, bars=20)`, `build_oil_legs(prep, src, today) -> [leg]` with ids `brent`, `wti`, `brent_wti`, `be_beta`, `be_gap` in that order.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_oillink.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import oillink, series

TODAY = date(2026, 9, 30)
N = 400


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


RNG = np.random.default_rng(3)
RET = days(RNG.normal(0, 1.5, N))                       # daily Brent % returns


def be_from(ret, beta, extra=None):
    """A 5Y breakeven (%) whose daily bp move is beta × Brent return (+ extra bp)."""
    dbe = beta * ret + (0 if extra is None else extra)
    return 2.0 + dbe.cumsum() / 100


def test_compound_twenty_bars_of_one_percent():
    out = oillink.compound(days([1.0] * 21))
    assert out.iloc[-1] == pytest.approx((1.01 ** 20 - 1) * 100)
    assert oillink.compound(None) is None


def test_beta_recovers_a_known_pass_through():
    beta = oillink.be_beta_series(be_from(RET, 2.0), RET)
    assert beta.iloc[-1] == pytest.approx(2.0)


def test_beta_needs_sixty_shared_bars():
    assert oillink.be_beta_series(be_from(RET[:59], 2.0), RET[:59]) is None


def test_gap_is_zero_when_breakevens_follow_the_beta():
    be = be_from(RET, 2.0)
    gap = oillink.be_gap_series(be, RET, oillink.be_beta_series(be, RET))
    # Compounded Brent returns vs summed bp moves leave a few bp of residue,
    # far below the 50+ bp of a real stall (next test).
    assert gap.abs().max() < 5.0


def test_gap_is_negative_when_breakevens_stall_in_an_oil_rally():
    ret = RET.copy()
    ret.iloc[-20:] = 2.0                                  # Brent +2%/day for 20 days
    be = be_from(ret, 2.0)
    be.iloc[-20:] = be.iloc[-21]                          # breakevens flat
    gap = oillink.be_gap_series(be, ret, oillink.be_beta_series(be_from(RET, 2.0), RET))
    assert gap.iloc[-1] < -50


def src_with(brent_ret=RET, be_beta=2.0):
    spot = days(80 * (1 + brent_ret / 100).cumprod())
    venue_idx = spot.index[-60:]
    perp = pd.Series(spot.loc[venue_idx].values * 1.05, index=venue_idx)   # same % moves
    cl = pd.Series(perp.values - 7.0, index=venue_idx)
    return {"fred": {"T5YIE": be_from(brent_ret, be_beta), "DCOILBRENTEU": spot},
            "closes": {"xyz:BRENTOIL": perp, "xyz:CL": cl}, "ctx": {}}


def test_oil_legs_in_display_order_with_units():
    src = src_with()
    built = oillink.build_oil_legs(series.prepare(src), src, TODAY)
    assert [l["id"] for l in built] == ["brent", "wti", "brent_wti", "be_beta", "be_gap"]
    by_id = {l["id"]: l for l in built}
    assert by_id["brent"]["src"] == "V+F" and by_id["brent"]["chg_unit"] == "%"
    assert by_id["brent"]["status"] == "ok" and by_id["brent"]["z"] is not None
    assert by_id["wti"]["status"] == "warming"            # venue-only history
    assert by_id["brent_wti"]["value"] == pytest.approx(7.0)
    assert by_id["be_beta"]["value"] == pytest.approx(2.0, rel=0.05)
    assert by_id["be_beta"]["z"] is None and by_id["be_beta"]["status"] == "ok"


def test_brent_rally_gives_positive_brent_z():
    ret = RET.copy()
    ret.iloc[-20:] = 2.0
    src = src_with(ret)
    by_id = {l["id"]: l for l in oillink.build_oil_legs(series.prepare(src), src, TODAY)}
    assert by_id["brent"]["z"] > 1


def test_no_inputs_give_no_data_legs():
    src = {"fred": {}, "closes": {}, "ctx": {}}
    built = oillink.build_oil_legs(series.prepare(src), src, TODAY)
    assert {l["status"] for l in built} == {"no_data"}
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_oillink.py -q`
Expected: FAIL — `ImportError: cannot import name 'oillink'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/oillink.py`:

```python
"""Panel B: oil against rates. Pure.

be_beta: how many bp the 5Y breakeven moves per 1% Brent move, over 60 bars.
be_gap: the 20-bar breakeven move that the beta did not predict. A negative
gap while Brent rallies means bonds do not price the oil move.
"""

import pandas as pd

from .legs import is_thin, make_leg
from .stats import clean

BETA_BARS = 60
GAP_BARS = 20


def compound(returns, bars=GAP_BARS):
    """Rolling ``bars``-bar compounded % return from daily % returns, or None."""
    r = clean(returns)
    if r is None:
        return None
    level = (1 + r / 100).cumprod()
    out = ((level / level.shift(bars) - 1) * 100).dropna()
    return out if len(out) else None


def be_beta_series(be5, brent_ret, bars=BETA_BARS):
    """Rolling OLS beta of daily Δbreakeven (bp) on daily Brent return (%)."""
    be, r = clean(be5), clean(brent_ret)
    if be is None or r is None:
        return None
    frame = pd.concat([be.diff() * 100, r], axis=1, join="inner").dropna()
    if len(frame) < bars:
        return None
    frame.columns = ["dbe", "ret"]
    beta = frame["dbe"].rolling(bars).cov(frame["ret"]) / frame["ret"].rolling(bars).var()
    return clean(beta)


def be_gap_series(be5, brent_ret, beta, bars=GAP_BARS):
    """20-bar Δbreakeven (bp) minus beta × 20-bar Brent return. Each day uses
    the beta of that day."""
    be, b, r20 = clean(be5), clean(beta), compound(brent_ret, bars)
    if be is None or b is None or r20 is None:
        return None
    frame = pd.concat([(be - be.shift(bars)) * 100, b, r20], axis=1, join="inner").dropna()
    if not len(frame):
        return None
    frame.columns = ["dbe20", "beta", "r20"]
    return clean(frame["dbe20"] - frame["beta"] * frame["r20"])


def build_oil_legs(prep, src, today):
    """Panel B legs, in display order. ``prep`` comes from series.prepare."""
    fred, ctx, closes = src.get("fred") or {}, src.get("ctx") or {}, src.get("closes") or {}
    brent = prep["brent"]
    brent_thin = is_thin(ctx.get("xyz:BRENTOIL"))

    def last(s):
        return None if s is None else float(s.iloc[-1])

    r20 = compound(brent["returns"])
    out = [make_leg("brent", "Brent", "oil", "$", "stronger oil rally", brent["level"], today,
                    src=brent["src"], chg20=last(r20), chg_unit="%", z_series=r20,
                    thin=brent_thin)]

    wti = prep["wti"]
    wti_r20 = compound(None if wti is None else wti.pct_change().dropna() * 100)
    out.append(make_leg("wti", "WTI", "oil", "$", "stronger oil rally", wti, today,
                        src="V" if wti is not None else None, chg20=last(wti_r20),
                        chg_unit="%", z_series=wti_r20, thin=is_thin(ctx.get("xyz:CL"))))

    b_v, w_v = clean(closes.get("xyz:BRENTOIL")), clean(closes.get("xyz:CL"))
    spread = None
    if b_v is not None and w_v is not None:
        spread = clean((b_v - w_v).dropna())
    out.append(make_leg("brent_wti", "Brent−WTI", "oil", "$", "wider Brent premium", spread,
                        today, src="V" if spread is not None else None, chg_mult=1.0,
                        chg_unit="$", thin=brent_thin or is_thin(ctx.get("xyz:CL"))))

    be5 = fred.get("T5YIE")
    beta = be_beta_series(be5, brent["returns"])
    out.append(make_leg("be_beta", "BE beta", "oil", "bp/1%", "more pass-through", beta, today,
                        src="V+F" if beta is not None else None, chg20=None, with_z=False,
                        thin=brent_thin))
    gap = be_gap_series(be5, brent["returns"], beta)
    out.append(make_leg("be_gap", "BE gap", "oil", "bp", "breakevens ahead of oil", gap, today,
                        src="V+F" if gap is not None else None, chg20=None, center=False,
                        thin=brent_thin))
    return out
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_oillink.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/oillink.py tests/test_situation_oillink.py
git commit -m "Add the oil link: Brent, WTI, pass-through beta and gap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Crowding and the OI history file

**Files:**
- Create: `tapedeck/situation/crowding.py`
- Test: `tests/test_situation_crowding.py`

**Interfaces:**
- Consumes: `stats.*`, `legs.is_thin`.
- Produces: `funding_stats(hourly) -> {"funding_ann", "funding_z", "funding_days"}`, `duration_side(market, funding_ann) -> str|None`, `load_history(path) -> [dict]`, `update_history(path, today, oi_by_market) -> [dict]`, `oi_change(history, market, today, days=20) -> (float|None, int)`, `build_crowding(ctx, funding, history, today) -> [crowding row]` in `CROWD_MARKETS` order; constants `OI_DAYS = 20`, `FUNDING_MIN_DAYS = 60`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_crowding.py`:

```python
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import crowding

TODAY = date(2026, 10, 1)


def hourly(rate, days=90, end="2026-09-30 23:00"):
    """``days`` whole calendar days of hourly funding; ``rate`` is a constant
    or a function of the row count."""
    idx = pd.date_range(end=end, periods=days * 24, freq="h")
    values = rate(len(idx)) if callable(rate) else rate
    return pd.Series(values, index=idx, dtype=float)


def test_funding_annualises_the_last_seven_days():
    out = crowding.funding_stats(hourly(0.00001))
    assert out["funding_ann"] == pytest.approx(0.00001 * 24 * 365 * 100)
    assert out["funding_days"] == 90


def test_funding_z_needs_sixty_days():
    assert crowding.funding_stats(hourly(lambda n: np.linspace(0, 1e-5, n), days=59))["funding_z"] is None
    assert crowding.funding_stats(hourly(lambda n: np.linspace(0, 1e-5, n), days=61))["funding_z"] > 1


def test_no_funding_is_none_not_zero():
    assert crowding.funding_stats(None) == {"funding_ann": None, "funding_z": None, "funding_days": 0}


@pytest.mark.parametrize("market,funding,side", [
    ("para:10Y", 5.0, "short duration crowded"),     # longs pay on a yield perp
    ("para:10Y", -5.0, "long duration crowded"),
    ("mkts:USBOND", 5.0, "long duration crowded"),   # longs pay on a bond
    ("xyz:TLT", -5.0, "short duration crowded"),
    ("xyz:BRENTOIL", 5.0, None),
    ("para:10Y", 0.0, None), ("para:10Y", None, None)])
def test_duration_side(market, funding, side):
    assert crowding.duration_side(market, funding) == side


def test_second_run_on_the_same_day_replaces_the_line(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY, {"para:10Y": 100.0})
    hist = crowding.update_history(path, TODAY, {"para:10Y": 120.0})
    assert hist == [{"date": "2026-10-01", "oi": {"para:10Y": 120.0}}]
    assert len(path.read_text().splitlines()) == 1


def test_no_oi_today_writes_no_line_but_keeps_history(tmp_path):
    path = tmp_path / "situation-history.jsonl"
    crowding.update_history(path, TODAY - timedelta(days=1), {"para:10Y": 100.0})
    hist = crowding.update_history(path, TODAY, {})
    assert [r["date"] for r in hist] == ["2026-09-30"]


def test_unreadable_line_is_skipped_with_a_warning(tmp_path, capsys):
    path = tmp_path / "situation-history.jsonl"
    path.write_text('{"date": "2026-09-30", "oi": {"para:10Y": 100.0}}\n{"date": "2026-10\n')
    hist = crowding.load_history(path)
    assert [r["date"] for r in hist] == ["2026-09-30"]
    assert "line 2 unreadable" in capsys.readouterr().err
    crowding.update_history(path, TODAY, {"para:10Y": 110.0})
    assert len(crowding.load_history(path)) == 2


def history(pairs):
    return [{"date": d.isoformat(), "oi": {"para:10Y": v}} for d, v in pairs]


def test_oi_change_against_twenty_days_back():
    hist = history([(TODAY - timedelta(days=20), 100.0), (TODAY, 125.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY) == (pytest.approx(25.0), 20)


def test_oi_change_warming_reports_days():
    hist = history([(TODAY - timedelta(days=3), 100.0), (TODAY, 125.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY) == (None, 3)
    assert crowding.oi_change([], "para:10Y", TODAY) == (None, 0)


def test_a_gap_in_days_uses_the_newest_line_before_the_cutoff():
    hist = history([(TODAY - timedelta(days=30), 80.0), (TODAY - timedelta(days=24), 100.0),
                    (TODAY - timedelta(days=5), 110.0), (TODAY, 120.0)])
    assert crowding.oi_change(hist, "para:10Y", TODAY)[0] == pytest.approx(20.0)


def test_build_crowding_statuses():
    ctx = {"para:10Y": {"oi": 125.0, "volume_24h": 1e6},
           "xyz:BRENTOIL": {"oi": 10.0, "volume_24h": 1e8}}
    funding = {"para:10Y": hourly(lambda n: np.linspace(0, 1e-5, n)),
               "xyz:BRENTOIL": hourly(0.00001, days=10)}
    hist = history([(TODAY - timedelta(days=20), 100.0), (TODAY, 125.0)])
    rows = {r["market"]: r for r in crowding.build_crowding(ctx, funding, hist, TODAY)}
    assert [r for r in rows] == [m for m, _ in crowding.CROWD_MARKETS]
    assert rows["para:10Y"]["status"] == "ok" and rows["para:10Y"]["panel"] == "rates"
    assert rows["para:10Y"]["side"] == "short duration crowded"
    assert rows["xyz:BRENTOIL"]["status"] == "warming"
    assert rows["xyz:BRENTOIL"]["note"] == "warming up: OI 0/20 days, funding 10/60 days"
    assert rows["xyz:CL"]["status"] == "no_data"
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_crowding.py -q`
Expected: FAIL — `ImportError: cannot import name 'crowding'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/crowding.py`:

```python
"""Venue positioning: funding and open interest (OI).

Pure except for the history file. The venue publishes funding history but no
OI history, so each run stores today's OI, one line per day, in
output/situation-history.jsonl. A second run on the same day replaces that
day's line, so "20 days" always means 20 days.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import stats
from .legs import is_thin
from .stats import clean

HOURS_PER_YEAR = 24 * 365
FUNDING_RECENT_DAYS = 7
FUNDING_MIN_DAYS = 60
OI_DAYS = 20
# +1: a long position is long duration (a bond price). −1: a long position is
# short duration (a yield perp gains when yields rise). Absent: not rates.
DURATION_SIGN = {"para:10Y": -1, "mkts:USBOND": 1, "xyz:TLT": 1}
CROWD_MARKETS = (("xyz:BRENTOIL", "oil"), ("xyz:CL", "oil"),
                 ("para:10Y", "rates"), ("mkts:USBOND", "rates"), ("xyz:TLT", "rates"))


def funding_stats(hourly, recent_days=FUNDING_RECENT_DAYS, min_days=FUNDING_MIN_DAYS):
    """{"funding_ann": %/yr over the last 7 days, "funding_z": z of daily mean
    funding over all fetched days (None under 60 days), "funding_days": n}."""
    s = clean(hourly)
    if s is None:
        return {"funding_ann": None, "funding_z": None, "funding_days": 0}
    recent = s[s.index > s.index[-1] - pd.Timedelta(days=recent_days)]
    ann = stats.finite(float(recent.mean()) * HOURS_PER_YEAR * 100)
    daily = s.resample("D").mean().dropna()
    n = len(daily)
    z = stats.zscore(daily, window=n) if n >= min_days else None
    return {"funding_ann": ann, "funding_z": z, "funding_days": n}


def duration_side(market, funding_ann):
    """Which side of duration pays funding, or None for a non-rates market.

    Positive funding: longs pay, so longs are crowded. A long yield perp is
    short duration; a long bond is long duration.
    """
    sign = DURATION_SIGN.get(market)
    if sign is None or not funding_ann:
        return None
    longs_crowded = funding_ann > 0
    long_duration = longs_crowded if sign > 0 else not longs_crowded
    return "long duration crowded" if long_duration else "short duration crowded"


def load_history(path):
    """[{"date": "YYYY-MM-DD", "oi": {market: float}}] sorted by date.

    A missing file is an empty history. An unreadable line — for example one
    half-written by a run that was stopped — is skipped with a warning.
    """
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            date.fromisoformat(rec["date"])
            oi = {m: float(v) for m, v in (rec.get("oi") or {}).items()
                  if stats.finite(v) is not None}
        except Exception:
            print(f"warning: {p.name} line {i} unreadable — skipped", file=sys.stderr)
            continue
        out.append({"date": rec["date"], "oi": oi})
    return sorted(out, key=lambda r: r["date"])


def update_history(path, today, oi_by_market):
    """Write today's OI (replacing any line for today) and return the history.
    No OI today (venue down) writes no line for today."""
    stamp = today.isoformat()
    hist = [r for r in load_history(path) if r["date"] != stamp]
    oi = {m: float(v) for m, v in (oi_by_market or {}).items() if stats.finite(v) is not None}
    if oi:
        hist.append({"date": stamp, "oi": oi})
        hist.sort(key=lambda r: r["date"])
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in hist))
    return hist


def oi_change(history, market, today, days=OI_DAYS):
    """(% change of today's OI against the newest line at least ``days`` days
    old, days of history for this market capped at ``days``).

    The second number is the n of "warming up (n/20 days)". A gap of missing
    days does not matter: the reference is the newest line on or before the
    cutoff, whatever day that is.
    """
    rows = [(date.fromisoformat(r["date"]), r["oi"].get(market)) for r in history]
    rows = [(d, v) for d, v in rows if v is not None]
    if not rows:
        return None, 0
    span = min((today - rows[0][0]).days, days)
    old = [v for d, v in rows if d <= today - timedelta(days=days)]
    now = [v for d, v in rows if d == today]
    if not old or not now or not old[-1]:
        return None, span
    return stats.finite((now[-1] / old[-1] - 1) * 100), span


def build_crowding(ctx, funding, history, today):
    """One row per CROWD_MARKETS market, with status and note like a leg."""
    rows = []
    for market, panel in CROWD_MARKETS:
        c = (ctx or {}).get(market)
        f = funding_stats((funding or {}).get(market))
        oi_chg, oi_days = oi_change(history, market, today)
        row = {"market": market, "panel": panel, "oi": (c or {}).get("oi"),
               "oi_chg_20d": oi_chg, "oi_days": oi_days, "oi_need": OI_DAYS,
               "funding_need": FUNDING_MIN_DAYS,
               "side": duration_side(market, f["funding_ann"]), "thin": is_thin(c)}
        row.update(f)
        if c is None and f["funding_ann"] is None:
            row["status"], row["note"] = "no_data", "no data"
        elif oi_chg is None or f["funding_z"] is None:
            parts = []
            if oi_chg is None:
                parts.append(f"OI {oi_days}/{OI_DAYS} days")
            if f["funding_z"] is None:
                parts.append(f"funding {f['funding_days']}/{FUNDING_MIN_DAYS} days")
            row["status"], row["note"] = "warming", "warming up: " + ", ".join(parts)
        else:
            row["status"], row["note"] = "ok", None
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_crowding.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/crowding.py tests/test_situation_crowding.py
git commit -m "Add venue crowding and the daily OI history

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Alerts

**Files:**
- Create: `tapedeck/situation/alerts.py`
- Test: `tests/test_situation_alerts.py`

**Interfaces:**
- Consumes: leg dicts (ids `brent`, `be_gap`, `be10` with `chg_z`) and crowding rows (Tasks 4, 6, 7).
- Produces: `build_alerts(legs, crowding) -> [{"id", "label", "state": "fired"|"quiet"|"disabled", "detail", "note"}]`, fired first; ids `bonds_ignore_oil`, `inflation_no_oil`, `leveraged_oil_rally`, `crowded_duration`; constant `LEVERAGE_NOTE`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_alerts.py`:

```python
import pytest

from tapedeck.situation import alerts


def leg(leg_id, **kw):
    base = {"id": leg_id, "z": None, "chg20": None}
    base.update(kw)
    return base


def crowd(market, funding_z=None, oi_chg=None, oi_days=20, side=None, status=None):
    if status is None:
        status = "ok" if funding_z is not None and oi_chg is not None else "warming"
    return {"market": market, "funding_z": funding_z, "oi_chg_20d": oi_chg, "oi_days": oi_days,
            "oi_need": 20, "funding_days": 90, "funding_need": 60, "side": side,
            "status": status}


def by_id(legs, crowding=()):
    return {a["id"]: a for a in alerts.build_alerts(legs, list(crowding))}


# ---------- bonds ignore oil ----------

def test_bonds_ignore_oil_fires():
    a = by_id([leg("brent", z=1.5), leg("be_gap", z=-1.2)])["bonds_ignore_oil"]
    assert a["state"] == "fired" and "Brent z +1.5" in a["detail"]


def test_bonds_ignore_oil_quiet_when_breakevens_follow():
    assert by_id([leg("brent", z=1.5), leg("be_gap", z=-0.5)])["bonds_ignore_oil"]["state"] == "quiet"


def test_bonds_ignore_oil_disabled_without_the_gap():
    a = by_id([leg("brent", z=1.5), leg("be_gap")])["bonds_ignore_oil"]
    assert a["state"] == "disabled" and "gap" in a["detail"]


# ---------- inflation scare without oil ----------

def test_inflation_scare_without_oil_fires_when_brent_is_flat():
    legs = [leg("be10", chg_z=1.4), leg("brent", z=0.1, chg20=0.0)]
    assert by_id(legs)["inflation_no_oil"]["state"] == "fired"


def test_inflation_scare_quiet_when_oil_is_up():
    legs = [leg("be10", chg_z=1.4), leg("brent", z=0.1, chg20=3.0)]
    assert by_id(legs)["inflation_no_oil"]["state"] == "quiet"


def test_inflation_scare_disabled_without_brent():
    assert by_id([leg("be10", chg_z=1.4)])["inflation_no_oil"]["state"] == "disabled"


# ---------- leveraged oil rally ----------

def test_leveraged_oil_rally_fires_and_carries_its_note():
    a = by_id([leg("brent", z=1.5)], [crowd("xyz:BRENTOIL", 1.2, 15.0)])["leveraged_oil_rally"]
    assert a["state"] == "fired" and a["note"] == alerts.LEVERAGE_NOTE


def test_leveraged_oil_rally_quiet_when_oi_falls():
    a = by_id([leg("brent", z=1.5)], [crowd("xyz:BRENTOIL", 1.2, -5.0)])["leveraged_oil_rally"]
    assert a["state"] == "quiet"


def test_leveraged_oil_rally_disabled_while_oi_history_grows():
    a = by_id([leg("brent", z=1.5)],
              [crowd("xyz:BRENTOIL", 1.2, None, oi_days=3)])["leveraged_oil_rally"]
    assert a["state"] == "disabled" and a["detail"] == "needs OI history (3/20 days)"


def test_leveraged_oil_rally_never_fires_on_funding_alone():
    a = by_id([leg("brent", z=3.0)], [crowd("xyz:BRENTOIL", 5.0, None)])["leveraged_oil_rally"]
    assert a["state"] == "disabled"


# ---------- crowded duration ----------

def test_crowded_duration_fires_with_the_side():
    a = by_id([], [crowd("para:10Y", 2.5, 12.0, side="short duration crowded"),
                   crowd("mkts:USBOND", 0.2, 1.0)])["crowded_duration"]
    assert a["state"] == "fired"
    assert "para:10Y" in a["detail"] and "short duration crowded" in a["detail"]
    assert "USBOND" not in a["detail"]


def test_crowded_duration_reads_negative_funding_too():
    a = by_id([], [crowd("mkts:USBOND", -2.5, 12.0, side="short duration crowded")])
    assert a["crowded_duration"]["state"] == "fired"


def test_crowded_duration_quiet():
    a = by_id([], [crowd("para:10Y", 1.0, 12.0)])["crowded_duration"]
    assert a["state"] == "quiet"


def test_crowded_duration_disabled_without_oi_history():
    a = by_id([], [crowd("para:10Y", 2.5, None, oi_days=5)])["crowded_duration"]
    assert a["state"] == "disabled" and a["detail"] == "needs OI history (5/20 days)"


def test_crowded_duration_disabled_without_venue_data():
    assert by_id([], [])["crowded_duration"]["detail"] == "no venue data"


# ---------- order ----------

def test_fired_alerts_come_first():
    out = alerts.build_alerts([leg("brent", z=1.5), leg("be_gap", z=-1.2)], [])
    states = [a["state"] for a in out]
    assert states == sorted(states, key=lambda s: {"fired": 0, "quiet": 1, "disabled": 2}[s])
    assert out[0]["id"] == "bonds_ignore_oil" and len(out) == 4
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_alerts.py -q`
Expected: FAIL — `ImportError: cannot import name 'alerts'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/alerts.py`:

```python
"""The four Situation alerts. Pure.

An alert whose inputs are missing or warming up is "disabled" and says why.
It never fires on part of its inputs. Fired alerts come first.
"""

Z_ON = 1.0                 # brent z, be10 change z
GAP_Z = -1.0               # be_gap z
FUNDING_Z = 1.0            # leveraged oil rally
CROWD_FUNDING_Z = 2.0      # crowded duration, either sign
OI_RISE_PCT = 10.0
DURATION_MARKETS = ("para:10Y", "mkts:USBOND")
LEVERAGE_NOTE = ("Reads perp leverage, not the futures curve: "
                 "the venue lists no contract months.")
_ORDER = {"fired": 0, "quiet": 1, "disabled": 2}


def _alert(alert_id, label, state, detail, note=None):
    return {"id": alert_id, "label": label, "state": state, "detail": detail, "note": note}


def _positioning_gap(row):
    """Why a crowding row cannot feed an alert yet, or None when it can."""
    if row is None or row["status"] == "no_data":
        return "no venue data"
    if row["oi_chg_20d"] is None:
        return f"needs OI history ({row['oi_days']}/{row['oi_need']} days)"
    if row["funding_z"] is None:
        return f"needs funding history ({row['funding_days']}/{row['funding_need']} days)"
    return None


def build_alerts(legs, crowding):
    by_leg = {leg["id"]: leg for leg in legs}
    by_market = {row["market"]: row for row in crowding}

    def get(leg_id, key):
        return (by_leg.get(leg_id) or {}).get(key)

    out = []
    brent_z, gap_z = get("brent", "z"), get("be_gap", "z")

    label = "Bonds ignore oil"
    if brent_z is None or gap_z is None:
        out.append(_alert("bonds_ignore_oil", label, "disabled",
                          "needs Brent z and breakeven gap z"))
    else:
        fired = brent_z > Z_ON and gap_z < GAP_Z
        out.append(_alert("bonds_ignore_oil", label, "fired" if fired else "quiet",
                          f"Brent z {brent_z:+.1f} · BE gap z {gap_z:+.1f}"))

    label = "Inflation scare without oil"
    be_chg_z, brent_chg = get("be10", "chg_z"), get("brent", "chg20")
    if be_chg_z is None or brent_chg is None:
        out.append(_alert("inflation_no_oil", label, "disabled",
                          "needs BE 10Y change z and Brent 20-day return"))
    else:
        fired = be_chg_z > Z_ON and brent_chg <= 0
        out.append(_alert("inflation_no_oil", label, "fired" if fired else "quiet",
                          f"BE 10Y Δ20d z {be_chg_z:+.1f} · Brent {brent_chg:+.1f}%/20d"))

    label = "Leveraged oil rally"
    row = by_market.get("xyz:BRENTOIL")
    why = _positioning_gap(row) or (None if brent_z is not None else "needs Brent z")
    if why:
        out.append(_alert("leveraged_oil_rally", label, "disabled", why, LEVERAGE_NOTE))
    else:
        fired = (brent_z > Z_ON and row["funding_z"] > FUNDING_Z
                 and row["oi_chg_20d"] > OI_RISE_PCT)
        out.append(_alert("leveraged_oil_rally", label, "fired" if fired else "quiet",
                          f"Brent z {brent_z:+.1f} · funding z {row['funding_z']:+.1f} · "
                          f"OI {row['oi_chg_20d']:+.0f}%/20d", LEVERAGE_NOTE))

    label = "Crowded duration"
    ready = [by_market[m] for m in DURATION_MARKETS
             if _positioning_gap(by_market.get(m)) is None]
    if not ready:
        out.append(_alert("crowded_duration", label, "disabled",
                          _positioning_gap(by_market.get(DURATION_MARKETS[0]))))
    else:
        hits = [r for r in ready
                if abs(r["funding_z"]) > CROWD_FUNDING_Z and r["oi_chg_20d"] > OI_RISE_PCT]
        shown = hits or ready
        detail = " · ".join(
            f"{r['market']} funding z {r['funding_z']:+.1f}, OI {r['oi_chg_20d']:+.0f}%"
            + (f", {r['side']}" if r in hits and r["side"] else "")
            for r in shown)
        out.append(_alert("crowded_duration", label, "fired" if hits else "quiet", detail))

    return sorted(out, key=lambda a: _ORDER[a["state"]])
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_alerts.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/alerts.py tests/test_situation_alerts.py
git commit -m "Add the four Situation alerts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Confidence, build_situation and the feed

**Files:**
- Create: `tapedeck/situation/confidence.py`
- Modify: `tapedeck/situation/__init__.py` (replace the docstring-only file)
- Test: `tests/test_situation_build.py`

**Interfaces:**
- Consumes: every module from Tasks 2–8.
- Produces: `confidence.panel_confidence(items) -> int|None`; `situation.build_situation(today, out_dir, fetch=None) -> dict` with keys `schema, date, fred_asof, venue_asof, regime, alerts, confidence {rates, oil}, legs, crowding, errors`; `situation.write_feed(sit, out_dir) -> Path`; constants `FEED_NAME`, `HISTORY_NAME`.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_build.py`:

```python
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tapedeck import situation
from tapedeck.situation import confidence

TODAY = date(2026, 10, 1)


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


def full_src():
    rng = np.random.default_rng(11)
    n = 400
    walk = lambda start, step: days(start + rng.normal(0, step, n).cumsum())
    fred = {"DGS2": walk(4.5, 0.03), "DGS10": walk(4.8, 0.04), "DGS30": walk(5.2, 0.04),
            "T10YIE": walk(2.3, 0.02), "T5YIE": walk(2.4, 0.02), "T5YIFR": walk(2.3, 0.02),
            "DFII10": walk(2.5, 0.03), "THREEFYTP10": walk(0.8, 0.02),
            "BAMLH0A0HYM2": walk(3.0, 0.03), "DCOILBRENTEU": walk(90.0, 1.0)}
    venue_idx = pd.bdate_range(end="2026-10-01", periods=40)
    closes = {"para:10Y": pd.Series(fred["DGS10"].reindex(venue_idx).ffill().values, index=venue_idx),
              "xyz:BRENTOIL": pd.Series(np.linspace(95, 100, 40), index=venue_idx),
              "xyz:CL": pd.Series(np.linspace(88, 92, 40), index=venue_idx)}
    ctx = {"para:10Y": {"mark": 5.3, "oracle": 5.3, "oi": 100.0, "volume_24h": 1e6},
           "xyz:BRENTOIL": {"mark": 100.0, "oracle": 100.0, "oi": 50.0, "volume_24h": 1e8}}
    return {"fred": fred, "closes": closes, "ctx": ctx, "funding": {},
            "errors": {"para:30Y candles": "no candles"}}


def test_build_situation_shape(tmp_path):
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: full_src())
    assert sit["schema"] == 1 and sit["date"] == "2026-10-01"
    assert sit["fred_asof"] == "2026-09-30" and sit["venue_asof"] == "2026-10-01"
    assert sit["regime"]["label"] is not None
    assert len(sit["alerts"]) == 4
    assert {l["panel"] for l in sit["legs"]} == {"rates", "oil"}
    assert 0 < sit["confidence"]["rates"] <= 100 and 0 < sit["confidence"]["oil"] <= 100
    assert sit["errors"] == {"para:30Y candles": "no candles"}
    assert (tmp_path / situation.HISTORY_NAME).exists()


def test_a_delisted_market_only_blanks_its_own_legs(tmp_path):
    src = full_src()
    del src["closes"]["xyz:CL"]
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: src)
    by_id = {l["id"]: l for l in sit["legs"]}
    assert by_id["wti"]["status"] == "no_data" and by_id["brent_wti"]["status"] == "no_data"
    assert by_id["brent"]["status"] == "ok" and by_id["y10"]["status"] != "no_data"


def test_everything_down_still_builds(tmp_path):
    empty = {"fred": {}, "closes": {}, "ctx": {}, "funding": {}, "errors": {"all": "down"}}
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: empty)
    assert sit["regime"]["label"] is None
    assert {a["state"] for a in sit["alerts"]} == {"disabled"}
    assert sit["confidence"] == {"rates": 0, "oil": 0}


def test_feed_is_strict_json_even_with_nan(tmp_path):
    sit = {"schema": 1, "legs": [{"z": float("nan"), "value": float("inf"), "n": np.int64(3)}]}
    path = situation.write_feed(sit, tmp_path / "out")
    data = json.loads(path.read_text())
    assert data["legs"][0]["z"] is None and data["legs"][0]["value"] is None
    assert "NaN" not in path.read_text()


def test_feed_round_trips_a_real_build(tmp_path):
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: full_src())
    data = json.loads(situation.write_feed(sit, tmp_path).read_text())
    assert data["regime"] == sit["regime"]


@pytest.mark.parametrize("items,expected", [
    ([], None),
    ([{"status": "ok"}, {"status": "ok"}], 100),
    ([{"status": "ok"}, {"status": "warming"}], 75),
    ([{"status": "ok", "thin": True}, {"status": "no_data"}], 25),
    ([{"status": "stale"}], 50)])
def test_panel_confidence(items, expected):
    assert confidence.panel_confidence(items) == expected
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_build.py -q`
Expected: FAIL — `ImportError: cannot import name 'confidence' from 'tapedeck.situation'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/confidence.py`:

```python
"""One confidence number per panel, 0 to 100. Pure.

Confidence is separate from the reading (oil-tracker brief §8): it says how
much of the panel stands on fresh, full, liquid data — not what the data says.
"""

STATUS_SCORE = {"ok": 1.0, "stale": 0.5, "warming": 0.5, "no_data": 0.0}


def item_score(item):
    """A leg or a crowding row. A thin venue market counts half."""
    score = STATUS_SCORE.get(item.get("status"), 0.0)
    return score * 0.5 if item.get("thin") else score


def panel_confidence(items):
    items = list(items)
    if not items:
        return None
    return int(round(100 * sum(item_score(i) for i in items) / len(items)))
```

`tapedeck/situation/__init__.py`:

```python
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
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_build.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/confidence.py tapedeck/situation/__init__.py tests/test_situation_build.py
git commit -m "Build the Situation dict and write its feed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The Situation tab HTML

**Files:**
- Create: `tapedeck/situation/render.py`
- Modify: `tapedeck/render.py` (imports at the top; `render_multi`; the `.chip.warn` CSS rule)
- Test: `tests/test_situation_render.py`

**Interfaces:**
- Consumes: the `build_situation` dict (Task 9 shape).
- Produces: `situation.render.render_situation(sit) -> str` (one `<section class="wl-section" data-wl="_situation">`), `TAB_NAME = "_situation"`, `TAB_TITLE = "Situation"`; `render.render_multi(lists, today, data_date=None, situation=None)`.

The existing tab script needs no change: it shows the saved tab, or the first section on a first visit. The section reuses `panel`, `panelgrid`, `minitbl` and `chip`, so light/dark and the narrow-window stacking work with no new layout code.

- [ ] **Step 1: Write the failing test**

`tests/test_situation_render.py`:

```python
import re
from datetime import date

from tapedeck import render
from tapedeck.situation import render as sit_render

TODAY = date(2026, 10, 1)


def leg(leg_id, panel, **kw):
    base = {"id": leg_id, "label": leg_id.upper(), "panel": panel, "unit": "%", "higher": "x",
            "src": "F", "value": 5.3161, "chg20": 31.0, "chg_unit": "bp", "z": 1.8,
            "state": "high", "age_days": 1, "status": "ok", "n": 300, "need": 252,
            "thin": False, "note": None}
    base.update(kw)
    return base


def crowd(market, panel, **kw):
    base = {"market": market, "panel": panel, "funding_ann": -2.2, "funding_z": -0.8,
            "funding_days": 90, "funding_need": 60, "oi": 1373816.0, "oi_chg_20d": None,
            "oi_days": 3, "oi_need": 20, "side": None, "thin": False, "status": "warming",
            "note": "warming up: OI 3/20 days"}
    base.update(kw)
    return base


def sit(**kw):
    base = {
        "schema": 1, "date": "2026-10-01", "fred_asof": "2026-09-30", "venue_asof": "2026-10-01",
        "regime": {"label": "Real-rate-led sell-off", "d10": 31.0, "dbe": 7.0, "dreal": 24.0,
                   "asof": "2026-09-30", "note": None},
        "alerts": [
            {"id": "bonds_ignore_oil", "label": "Bonds ignore oil", "state": "fired",
             "detail": "Brent z +2.1 · BE gap z -1.3", "note": None},
            {"id": "leveraged_oil_rally", "label": "Leveraged oil rally", "state": "disabled",
             "detail": "needs OI history (3/20 days)", "note": "Reads perp leverage, not the futures curve."}],
        "confidence": {"rates": 82, "oil": 64},
        "legs": [leg("y10", "rates"),
                 leg("be10", "rates", z=None, status="warming", n=100, state=None),
                 leg("credit", "rates", value=None, chg20=None, z=None, status="no_data",
                     state=None, n=0, note="no data", age_days=None),
                 leg("brent", "oil", unit="$", value=100.53, chg20=12.0, chg_unit="%", z=2.1,
                     state="extreme high"),
                 leg("be_beta", "oil", unit="bp/1%", value=0.04, chg20=None, z=None, state=None,
                     need=0, n=0)],
        "crowding": [crowd("xyz:BRENTOIL", "oil"),
                     crowd("para:10Y", "rates", funding_ann=1.1, oi_chg_20d=12.0, status="ok",
                           side="short duration crowded", note=None),
                     crowd("xyz:CL", "oil", status="no_data")],
        "errors": {"FRED DGS30": "timed out"},
    }
    base.update(kw)
    return base


def test_strip_shows_label_split_alerts_and_confidence():
    out = sit_render.render_situation(sit())
    assert "Real-rate-led sell-off" in out
    assert "10Y +31bp/20d = real +24 · BE +7" in out
    assert '<span class="chip warn"' in out and "● Bonds ignore oil" in out
    assert '<span class="chip off"' in out
    assert "○ Leveraged oil rally — needs OI history (3/20 days)" in out
    assert "Reads perp leverage" in out
    assert "Rates 82" in out and "Oil↔Rates 64" in out
    assert "FRED to 2026-09-30" in out


def test_fired_alert_is_listed_before_disabled():
    out = sit_render.render_situation(sit())
    assert out.index("Bonds ignore oil") < out.index("Leveraged oil rally")


def test_legs_format_by_unit():
    out = sit_render.render_situation(sit())
    assert ">5.32%<" in out and ">+31bp<" in out and ">+1.8<" in out
    assert ">100.53<" in out and ">+12.0%<" in out


def test_warming_and_no_data_render_as_text_never_a_number():
    out = sit_render.render_situation(sit())
    be10 = re.search(r"<tr><td>BE10</td>.*?</tr>", out).group(0)
    assert "warming up (100/252)" in be10
    credit = re.search(r'<tr><td title="no data">CREDIT</td>.*?</tr>', out).group(0)
    assert "no data" in credit and re.search(r">\s*-?\d", credit.replace("0d", "")) is None


def test_a_leg_without_z_shows_a_dash_not_warming():
    out = sit_render.render_situation(sit())
    beta = re.search(r"<tr><td>BE_BETA</td>.*?</tr>", out).group(0)
    assert "warming" not in beta and ">0.04<" in beta


def test_crowding_rows():
    out = sit_render.render_situation(sit())
    assert "warming up (3/20 days)" in out and "short duration crowded" in out
    assert "1,373,816" in out and "+12.0%" in out
    assert re.search(r"xyz:CL</td><td[^>]*>no data", out)


def test_source_errors_are_listed():
    assert "FRED DGS30: timed out" in sit_render.render_situation(sit())


def test_no_regime_label_says_why():
    out = sit_render.render_situation(sit(regime={"label": None, "note": "warming up (10/21)"}))
    assert "no label — warming up (10/21)" in out


def test_text_is_escaped():
    out = sit_render.render_situation(sit(errors={"<x>": "<script>"}))
    assert "<script>" not in out and "&lt;script&gt;" in out


# ---------- the page ----------

def wl(name):
    return {"name": name, "title": name.title(), "benchmark": "SPY", "rows": [],
            "summary": None, "alerts": [], "diff": None}


def test_situation_is_the_first_tab():
    page = render.render_multi([wl("semis")], TODAY, situation=sit())
    tabs = re.findall(r'<button class="wtab" data-wl="([^"]+)"', page)
    assert tabs == ["_situation", "semis"]
    assert page.index('data-wl="_situation"') < page.index('class="wl-section" data-wl="semis"')


def test_a_watchlist_named_situation_does_not_clash():
    page = render.render_multi([wl("situation")], TODAY, situation=sit())
    assert re.findall(r'<button class="wtab" data-wl="([^"]+)"', page) == ["_situation", "situation"]


def test_without_situation_the_page_is_unchanged():
    assert render.render_multi([wl("semis")], TODAY) == \
        render.render_multi([wl("semis")], TODAY, situation=None)
    assert "_situation" not in render.render_multi([wl("semis")], TODAY)
```

- [ ] **Step 2: Run the test to see it fail**

Run: `.venv/bin/python3 -m pytest tests/test_situation_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'render' from 'tapedeck.situation'`

- [ ] **Step 3: Write the implementation**

`tapedeck/situation/render.py`:

```python
"""HTML for the Situation tab. Pure: the build_situation dict in, a string out.

The section reuses the page's own classes (panel, panelgrid, minitbl, chip),
so it follows the light/dark tokens and the narrow-window stacking for free.
"""

import html as h

# A watchlist file starting with "_" is ignored (config.load_watchlists), so no
# watchlist can ever take this tab name.
TAB_NAME = "_situation"
TAB_TITLE = "Situation"

_ICON = {"fired": "●", "quiet": "○", "disabled": "○"}
_CHIP = {"fired": "warn", "quiet": "", "disabled": "off"}
_DECIMALS = {"%": 2, "bp": 0, "$": 2, "bp/1%": 2}


def _value(leg):
    v = leg["value"]
    if v is None:
        return "—"
    text = f"{v:.{_DECIMALS.get(leg['unit'], 2)}f}"
    return text + ("%" if leg["unit"] == "%" else "")


def _chg(leg):
    c = leg["chg20"]
    if c is None:
        return "—"
    unit = leg["chg_unit"]
    return f"{c:+.1f}%" if unit == "%" else (f"{c:+.2f}" if unit == "$" else f"{c:+.0f}bp")


def _z(leg):
    if leg["status"] == "no_data":
        return "no data"
    if leg["need"] and leg["z"] is None and leg["n"] < leg["need"]:
        return f"warming up ({leg['n']}/{leg['need']})"
    return "—" if leg["z"] is None else f"{leg['z']:+.1f}"


def _state(leg):
    words = [w for w in (leg["state"], "stale" if leg["status"] == "stale" else None,
                         "thin" if leg["thin"] else None) if w]
    return " · ".join(words)


def _leg_row(leg):
    note = leg.get("note")
    title = f' title="{h.escape(note)}"' if note else ""
    mark = " *" if note and leg["status"] != "no_data" else ""
    age = "" if leg["age_days"] is None else f"{leg['age_days']}d"
    return (f'<tr><td{title}>{h.escape(leg["label"])}{mark}</td>'
            f'<td>{h.escape(leg["src"] or "")}</td>'
            f'<td class="a-r">{_value(leg)}</td><td class="a-r">{_chg(leg)}</td>'
            f'<td class="a-r">{_z(leg)}</td><td>{h.escape(_state(leg))}</td>'
            f'<td class="a-r">{age}</td></tr>')


def _legs_panel(title, legs):
    head = ('<tr><th>Leg</th><th>Src</th><th class="a-r">Value</th><th class="a-r">Δ20d</th>'
            '<th class="a-r">z</th><th>State</th><th class="a-r">Age</th></tr>')
    body = "".join(_leg_row(leg) for leg in legs)
    return (f'<section class="panel pcol"><span class="ptitle">{h.escape(title)}</span>'
            f'<table class="minitbl"><thead>{head}</thead><tbody>{body}</tbody></table></section>')


def _crowd_row(row):
    if row["status"] == "no_data":
        cells = '<td class="a-r" colspan="5">no data</td>'
    else:
        fa, fz, oi, chg = row["funding_ann"], row["funding_z"], row["oi"], row["oi_chg_20d"]
        fz_text = (f"{fz:+.1f}" if fz is not None
                   else f"warming up ({row['funding_days']}/{row['funding_need']})")
        chg_text = (f"{chg:+.1f}%" if chg is not None
                    else f"warming up ({row['oi_days']}/{row['oi_need']} days)")
        cells = (f'<td class="a-r">{"—" if fa is None else f"{fa:+.1f}%"}</td>'
                 f'<td class="a-r">{fz_text}</td>'
                 f'<td class="a-r">{"—" if oi is None else f"{oi:,.0f}"}</td>'
                 f'<td class="a-r">{chg_text}</td><td>{h.escape(row["side"] or "")}</td>')
    thin = " · thin" if row["thin"] else ""
    return f'<tr><td>{h.escape(row["market"])}{thin}</td>{cells}</tr>'


def _crowding_panel(rows):
    head = ('<tr><th>Market</th><th class="a-r">Funding/yr</th><th class="a-r">z</th>'
            '<th class="a-r">OI</th><th class="a-r">OI Δ20d</th><th>Side</th></tr>')
    body = "".join(_crowd_row(r) for r in rows)
    return ('<section class="panel pcol"><span class="ptitle">Crowding (venue)</span>'
            f'<table class="minitbl"><thead>{head}</thead><tbody>{body}</tbody></table></section>')


def _alert_chip(alert):
    text = f'{_ICON[alert["state"]]} {h.escape(alert["label"])}'
    if alert["state"] == "disabled":
        text += f' — {h.escape(alert["detail"] or "")}'
    return (f'<span class="chip {_CHIP[alert["state"]]}" '
            f'title="{h.escape(alert["detail"] or "")}">{text}</span>')


def _conf(v):
    return "—" if v is None else str(v)


def _strip(sit):
    reg = sit.get("regime") or {}
    if reg.get("label"):
        split = (f'10Y {reg["d10"]:+.0f}bp/20d = real {reg["dreal"]:+.0f} · '
                 f'BE {reg["dbe"]:+.0f} · FRED {h.escape(reg["asof"])}')
        reg_html = f'<b>{h.escape(reg["label"])}</b> <span class="sitmuted">{split}</span>'
    else:
        reg_html = f'<span class="sitmuted">no label — {h.escape(reg.get("note") or "no data")}</span>'
    chips = "".join(_alert_chip(a) for a in sit.get("alerts") or [])
    notes = "".join(f'<div class="sitmuted">{h.escape(a["label"])}: {h.escape(a["note"])}</div>'
                    for a in sit.get("alerts") or [] if a.get("note"))
    conf = sit.get("confidence") or {}
    dates = f'data {h.escape(sit.get("venue_asof") or "—")} · FRED to {h.escape(sit.get("fred_asof") or "—")}'
    return ('<section class="panel pcol sitstrip"><span class="ptitle">Situation</span>'
            f'<div class="sitmuted">{dates}</div>'
            f'<div>Regime {reg_html}</div>'
            f'<div class="chiprow">Alerts {chips}</div>{notes}'
            f'<div>Confidence: Rates {_conf(conf.get("rates"))} · '
            f'Oil↔Rates {_conf(conf.get("oil"))}</div></section>')


def render_situation(sit):
    legs = sit.get("legs") or []
    rates = [leg for leg in legs if leg["panel"] == "rates"]
    oil = [leg for leg in legs if leg["panel"] == "oil"]
    errors = sit.get("errors") or {}
    err_html = ""
    if errors:
        err_html = ('<div class="sitmuted">sources: '
                    + h.escape("; ".join(f"{k}: {v}" for k, v in errors.items())) + "</div>")
    return (f'<section class="wl-section" data-wl="{TAB_NAME}">'
            + _strip(sit)
            + '<div class="panelgrid">' + _legs_panel("Rates regime", rates)
            + _legs_panel("Oil ↔ Rates", oil) + "</div>"
            + _crowding_panel(sit.get("crowding") or [])
            + err_html
            + "</section>")
```

`tapedeck/render.py` — in the imports, find:

```python
from . import alerts as alerts_mod
from . import vwaplink
```

and replace it with:

```python
from . import alerts as alerts_mod
from . import vwaplink
from .situation import render as sit_render
```

`tapedeck/render.py` — find the start of `render_multi`:

```python
def render_multi(lists, today, data_date=None):
    sections, any_pos, any_vwap = [], False, False
    for wl in lists:
        section, has_pos, has_vwap = _section_html(wl, today)
        sections.append(section)
        any_pos = any_pos or has_pos
        any_vwap = any_vwap or has_vwap

    tabs_html = ""
    if len(lists) > 1:
        tabs_html = '<nav class="wltabs">' + "".join(
            f'<button class="wtab" data-wl="{h.escape(w["name"])}">{h.escape(w["title"])}</button>'
            for w in lists) + "</nav>"
```

and replace it with:

```python
def render_multi(lists, today, data_date=None, situation=None):
    """The page. ``situation`` (the build_situation dict) adds the Situation
    tab in first place; None leaves the page exactly as it was."""
    sections, any_pos, any_vwap = [], False, False
    for wl in lists:
        section, has_pos, has_vwap = _section_html(wl, today)
        sections.append(section)
        any_pos = any_pos or has_pos
        any_vwap = any_vwap or has_vwap

    tab_items = [(w["name"], w["title"]) for w in lists]
    if situation is not None:
        sections.insert(0, sit_render.render_situation(situation))
        tab_items.insert(0, (sit_render.TAB_NAME, sit_render.TAB_TITLE))

    tabs_html = ""
    if len(tab_items) > 1:
        tabs_html = '<nav class="wltabs">' + "".join(
            f'<button class="wtab" data-wl="{h.escape(name)}">{h.escape(title)}</button>'
            for name, title in tab_items) + "</nav>"
```

`tapedeck/render.py` — in the CSS (an f-string, so braces are doubled), find:

```css
.chip.warn {{ color:var(--warn-ink); background:rgba(var(--val-rgb),.12); }}
```

and replace it with:

```css
.chip.warn {{ color:var(--warn-ink); background:rgba(var(--val-rgb),.12); }}
.chip.off {{ color:var(--muted); }}
.sitmuted {{ color:var(--muted); font-size:12px; }}
.sitstrip > div {{ margin:3px 0; }}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest tests/test_situation_render.py -q`
Expected: all PASS.

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES (395+ existing tests, plus the new ones).

- [ ] **Step 5: Commit**

```bash
git add tapedeck/situation/render.py tapedeck/render.py tests/test_situation_render.py
git commit -m "Render the Situation tab as the first tab

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: CLI wiring and docs

**Files:**
- Modify: `tapedeck.py` (argument list; the block before `render.render_multi`)
- Modify: `tests/test_tapedeck_cli.py` (append at the end)
- Modify: `README.md` (the command list; a new section before `## What's on the page`)
- Modify: `CHANGELOG.md` (a new entry at the top)

**Interfaces:**
- Consumes: `situation.build_situation(today, out_dir)`, `situation.write_feed(sit, out_dir)` (Task 9); `render.render_multi(..., situation=)` (Task 10).
- Produces: the `--no-situation` flag; `output/situation-latest.json` on every run.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tapedeck_cli.py` (it already defines `_load_cli`, `_stub_no_network`, and imports `json` and `sys`):

```python
# ---------- Situation tab ----------
#
# tests/conftest.py blocks the network, so build_situation runs on empty
# sources here: every leg is "no data", and the run must still complete.

def _one_list(tmp_path):
    wl_dir = tmp_path / "watchlists"
    wl_dir.mkdir()
    (wl_dir / "book.yaml").write_text("holdings:\n  - ticker: NVDA\n")
    (tmp_path / "output").mkdir()


def _page(tmp_path):
    [page] = (tmp_path / "output").glob("tapedeck-*.html")
    return page.read_text()


def test_default_run_adds_the_situation_tab_and_feed(tmp_path, monkeypatch):
    _stub_no_network(monkeypatch)
    _one_list(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["tapedeck.py", "--no-open", "--source", "yahoo"])

    cli.main()

    assert 'data-wl="_situation"' in _page(tmp_path)
    feed = json.loads((tmp_path / "output" / "situation-latest.json").read_text())
    assert feed["schema"] == 1 and feed["errors"]


def test_no_situation_flag_skips_the_tab(tmp_path, monkeypatch):
    _stub_no_network(monkeypatch)
    _one_list(tmp_path)
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["tapedeck.py", "--no-open", "--source", "yahoo", "--no-situation"])

    cli.main()

    assert "_situation" not in _page(tmp_path)
    assert not (tmp_path / "output" / "situation-latest.json").exists()


def test_a_situation_crash_costs_the_tab_not_the_page(tmp_path, monkeypatch, capsys):
    from tapedeck import situation

    _stub_no_network(monkeypatch)
    _one_list(tmp_path)

    def boom(today, out_dir, fetch=None):
        raise ValueError("bad input")

    monkeypatch.setattr(situation, "build_situation", boom)
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["tapedeck.py", "--no-open", "--source", "yahoo"])

    cli.main()

    assert "_situation" not in _page(tmp_path)
    assert "situation tab failed (bad input)" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/bin/python3 -m pytest tests/test_tapedeck_cli.py -q`
Expected: 3 FAIL — `test_default_run_adds_the_situation_tab_and_feed` (AssertionError: no `_situation` in the page), `test_no_situation_flag_skips_the_tab` (SystemExit: unrecognized arguments: --no-situation), `test_a_situation_crash_costs_the_tab_not_the_page` (AssertionError: no warning on stderr).

- [ ] **Step 3: Wire the CLI**

`tapedeck.py` — find:

```python
    parser.add_argument("--port", type=int, default=None,
                        help=f"port for --serve (default {DEFAULT_PORT})")
```

and replace it with:

```python
    parser.add_argument("--port", type=int, default=None,
                        help=f"port for --serve (default {DEFAULT_PORT})")
    parser.add_argument("--no-situation", action="store_true",
                        help="skip the Situation tab (bonds and oil from trade.xyz + FRED)")
```

`tapedeck.py` — find:

```python
    data_date = max((h.index[-1].date() for h in hists.values()), default=None)
    html = render.render_multi(rendered_lists, today,
                               data_date=data_date.isoformat() if data_date else None)
```

and replace it with:

```python
    # The Situation tab never stops the run: a failure costs the tab, not the page.
    situation_obj = None
    if not args.no_situation:
        from tapedeck import situation
        print("TAPEDECK · building situation (trade.xyz + FRED) …", file=sys.stderr)
        try:
            situation_obj = situation.build_situation(today, out_dir)
            print(f"wrote {situation.write_feed(situation_obj, out_dir)}", file=sys.stderr)
        except Exception as exc:
            situation_obj = None
            print(f"warning: situation tab failed ({exc}) — page renders without it",
                  file=sys.stderr)

    data_date = max((h.index[-1].date() for h in hists.values()), default=None)
    html = render.render_multi(rendered_lists, today,
                               data_date=data_date.isoformat() if data_date else None,
                               situation=situation_obj)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python3 -m pytest -q`
Expected: the whole suite PASSES.

- [ ] **Step 5: Update the docs**

`README.md` — in the command block under `## Setup & run`, find:

```bash
.venv/bin/python3 tapedeck.py --serve         # serve the last run at :7360 with Refresh buttons
```

and replace it with:

```bash
.venv/bin/python3 tapedeck.py --serve         # serve the last run at :7360 with Refresh buttons
.venv/bin/python3 tapedeck.py --no-situation  # skip the Situation tab (bonds + oil)
```

`README.md` — insert this section directly before the line `## What's on the page`:

```markdown
## Situation tab

The first tab reads bonds and oil together. It answers four questions: which
regime rates are in, whether bonds price the oil move, whether an oil rally
runs on leveraged perp longs, and whether one side of duration is crowded.

- **Sources.** trade.xyz for every market it lists: the 2Y, 10Y and 30Y yield
  perps, USBOND, TLT, Brent and WTI, with their funding and open interest.
  FRED's public CSV for what no venue lists (breakevens, the real yield, the
  term premium, the high-yield spread) and for older history. No Yahoo, no key.
- **Legs.** Each row shows the value, the 20-day change, a z-score over 252
  days and a state word. A leg without enough history shows "warming up
  (n/252)". A leg without data shows "no data". Neither shows a number.
- **Regime label.** The 20-day move of the 10Y, split into breakeven and real
  yield. FRED defines `T10YIE = DGS10 − DFII10`, so the split adds up.
- **Alerts.** Bonds ignore oil · Inflation scare without oil · Leveraged oil
  rally · Crowded duration. The last two need 20 days of OI history. The venue
  has none, so tapedeck stores one line per day in
  `output/situation-history.jsonl`. Until then the two alerts show as
  disabled, with the reason.
- **Confidence.** One number per panel, from data age, missing legs, history
  length and venue liquidity.
- **Cost.** The tab adds about 25 seconds to a run, mostly for the funding
  history. `--no-situation` skips it. A failure in the tab never stops the run.
- **Feed.** `output/situation-latest.json` (`schema: 1`).

Design, legs and thresholds:
[`docs/superpowers/specs/2026-10-01-situation-tab-design.md`](docs/superpowers/specs/2026-10-01-situation-tab-design.md).
```

`CHANGELOG.md` — insert this entry directly after the first line (`# TAPEDECK Changelog`) and its blank line:

```markdown
## 2026-10-01 — Situation tab: bonds and oil

- **A Situation tab, first on the page.** It reads rates and oil with the
  oil-tracker method: legs with a stated direction, z-scores over 252 days, a
  separate confidence number, and "warming up" or "no data" instead of a fake
  value.
- **trade.xyz and FRED only.** Live prices, funding and open interest come
  from the venue (`para:2Y/10Y/30Y`, `mkts:USBOND`, `xyz:TLT`,
  `xyz:BRENTOIL`, `xyz:CL`). FRED's public CSV gives breakevens, the real
  yield, the term premium, the HY spread and older history. Yields join FRED
  on levels only within 5 bp. Brent joins on returns, because the perp is a
  futures price and FRED Brent is spot.
- **Four alerts:** Bonds ignore oil, Inflation scare without oil, Leveraged oil
  rally, Crowded duration. An alert without its inputs shows as disabled, with
  the reason. It never fires on part of its inputs.
- **New files:** `output/situation-latest.json` (`schema: 1`) and
  `output/situation-history.jsonl` (OI, one line per day).
- **`--no-situation`** skips the tab. A failure in the tab never stops the run.
- **Tests no longer reach the network.** `tests/conftest.py` blocks
  `hlfetch._post` and the FRED fetch for every test.
```

- [ ] **Step 6: Run it once on live data**

Run: `.venv/bin/python3 tapedeck.py --no-open`
Expected: stderr shows `TAPEDECK · building situation (trade.xyz + FRED) …` and `wrote …/output/situation-latest.json`; the run takes about 25 seconds longer than before. Open the newest `output/tapedeck-*.html`: the first tab is **Situation**, with a regime label, four alert chips (the two OI alerts grey: "needs OI history (0/20 days)"), and three panels. Run it a second time the same day: `output/situation-history.jsonl` still has one line.

- [ ] **Step 7: Commit**

```bash
git add tapedeck.py tests/test_tapedeck_cli.py README.md CHANGELOG.md
git commit -m "Show the Situation tab on every run, with --no-situation to skip it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
