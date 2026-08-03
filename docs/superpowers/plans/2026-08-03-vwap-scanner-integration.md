# VWAP Scanner Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface `vwap-scanner`'s computed VWAP levels in the tapedeck dashboard through a read-only JSON handoff.

**Architecture:** Two loose-coupled CLIs, JSON in both directions. tapedeck's existing `output/tapedeck-latest.json` becomes the scanner's universe (`--universe-from`); the scanner writes `vwap-latest.json` (`--json-out`); tapedeck reads it read-only through a new `tapedeck/vwaplink.py`, a direct sibling of the existing `vaultlink.py`. Neither repo imports the other.

**Tech Stack:** Python 3.9, pandas, pytest. tapedeck renders self-contained HTML from `tapedeck/render.py` (no framework, no build step).

**Spec:** `docs/superpowers/specs/2026-08-03-vwap-scanner-integration-design.md`

## Global Constraints

- **Two repos.** Tasks 1–2 are in `/Users/erik/Developer/trading/vwap-scanner`. Tasks 3–8 are in `/Users/erik/Developer/trading/tapedeck`. Commit in the repo the task names — never stage across both.
- **tapedeck test command:** `.venv/bin/python3 -m pytest tests/ -q` (97 tests pass today).
- **vwap-scanner test command:** `venv/bin/python -m pytest -q`.
- **`vwaplink.py` is strictly read-only.** Its only filesystem access is a single `Path(path).read_text()`. It must never write, create, or delete anything.
- **Every failure degrades, never raises.** Missing file, malformed JSON, wrong schema, absent ticker → omit that surface with a stderr warning; the dashboard run always completes. This is the contract `vaultlink.py` already follows — match it.
- **Contract version is `schema: 1`.** Any other value is treated as unreadable.
- **`STALE_DAYS = 7`**, measured in calendar days from `generated`.
- **Default `vwap_alert_pct` is `2.0`.**
- **Never render a missing value as `0`.** A ticker with no VWAP data at all renders an empty `<td>`; an individual missing sub-value renders `n/a`, which is what `fmt_pct`/`fmt_num`/`fmt_price` already return for `None` (`render.py:19-30`) and is the page's existing convention.
- **`tests/test_render.py` has no `_rows()` helper.** Build rows with the existing `sample_row(**overrides)` / `empty_row(**overrides)` and lists with `wl(name, title, rows, benchmark="SPY")`. `TODAY` is `date(2026, 7, 31)`.
- **Toggle buttons use `class="tbtn"`** (`render.py:527`), not `tgl`.
- `direction` is carried from the scan verbatim and never recomputed.

---

### Task 1: Scanner reads a tapedeck feed as its universe

**Repo:** `/Users/erik/Developer/trading/vwap-scanner`

**Files:**
- Create: `src/universe_feed.py`
- Modify: `scanner.py` (add `universe` param to `run_scan` at line 271; add `--universe-from` flag in `main()` at line 704)
- Test: `tests/test_universe_feed.py`

**Interfaces:**
- Produces: `universe_from_feed(path: str) -> pd.DataFrame` with columns `ticker, exchange, region, api_symbol, tv_symbol` — the exact column shape `run_scan` already iterates over at `scanner.py:333`.
- Produces: `run_scan(..., universe: pd.DataFrame = None)` — when passed, skips `build_universe()` entirely.

**Why this task exists:** the scanner's universe is S&P 500 + NDX. Watchlist names like IREN, WYFI and CRDO are not in it and would otherwise never be scanned.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_feed.py`:

```python
import json
import pytest
from src.universe_feed import universe_from_feed

FEED = {
    "date": "2026-08-03",
    "lists": [
        {"name": "a", "rows": [
            {"ticker": "CRDO", "tv_symbol": "NASDAQ:CRDO"},
            {"ticker": "BE", "tv_symbol": "NYSE:BE"},
        ]},
        {"name": "b", "rows": [
            {"ticker": "CRDO", "tv_symbol": "NASDAQ:CRDO"},   # duplicate across lists
            {"ticker": "SPY"},                                 # no tv_symbol
        ]},
    ],
}


def _write(tmp_path, obj):
    p = tmp_path / "tapedeck-latest.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_dedupes_across_lists_and_preserves_order(tmp_path):
    df = universe_from_feed(_write(tmp_path, FEED))
    assert list(df["ticker"]) == ["CRDO", "BE", "SPY"]


def test_parses_exchange_from_tv_symbol(tmp_path):
    df = universe_from_feed(_write(tmp_path, FEED))
    by_ticker = df.set_index("ticker")
    assert by_ticker.loc["CRDO", "exchange"] == "NASDAQ"
    assert by_ticker.loc["BE", "exchange"] == "NYSE"


def test_missing_tv_symbol_leaves_exchange_none(tmp_path):
    df = universe_from_feed(_write(tmp_path, FEED))
    row = df.set_index("ticker").loc["SPY"]
    assert row["exchange"] is None
    assert row["tv_symbol"] == "SPY"


def test_every_row_is_region_us(tmp_path):
    df = universe_from_feed(_write(tmp_path, FEED))
    assert set(df["region"]) == {"US"}


def test_empty_feed_raises(tmp_path):
    with pytest.raises(ValueError, match="no tickers"):
        universe_from_feed(_write(tmp_path, {"lists": []}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_universe_feed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.universe_feed'`

- [ ] **Step 3: Write the implementation**

Create `src/universe_feed.py`:

```python
"""Build a scan universe from a tapedeck feed (output/tapedeck-latest.json).

Read-only: the only filesystem access is reading the feed. Lets the scanner
cover watchlist names that are not in the S&P 500 / NDX universe.
"""

import json
from pathlib import Path

import pandas as pd


def universe_from_feed(path: str) -> pd.DataFrame:
    """Union of every list's tickers, in first-seen order, as a scan universe.

    The feed carries ``tv_symbol`` (e.g. "NASDAQ:CRDO"), so the exchange comes
    from the file rather than the cached exchange map.
    """
    data = json.loads(Path(path).read_text())
    rows, seen = [], set()
    for lst in data.get("lists") or []:
        for r in lst.get("rows") or []:
            ticker = str(r.get("ticker") or "").upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            tv_symbol = r.get("tv_symbol") or ticker
            exchange = tv_symbol.split(":")[0] if ":" in tv_symbol else None
            rows.append({"ticker": ticker, "exchange": exchange, "region": "US",
                         "api_symbol": ticker, "tv_symbol": tv_symbol})
    if not rows:
        raise ValueError(f"no tickers in feed {path}")
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_universe_feed.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the `universe` parameter to `run_scan`**

In `scanner.py`, add the parameter to the `run_scan` signature (line 271):

```python
def run_scan(
    config: dict,
    cache: Cache,
    vwap_configs: list[dict],
    tickers: list[str] = None,
    output_dir: str = None,
    regions: list[str] = None,
    crypto_vwap_configs: list[dict] = None,
    indicator_settings: dict = None,
    crypto_indicator_settings: dict = None,
    universe: pd.DataFrame = None,
) -> dict:
```

Then replace the universe-selection block (the `if tickers:` / `else:` at roughly lines 314–331) with a three-way choice — `universe` wins, then `tickers`, then the built universe:

```python
    if universe is not None:
        logger.info(f"Scanning {len(universe)} tickers from supplied universe")
    elif tickers:
        # For manually specified tickers, create simple records (US assumed)
        universe = pd.DataFrame({
            "ticker": tickers,
            "exchange": [None] * len(tickers),
            "region": ["US"] * len(tickers),
            "api_symbol": tickers,
            "tv_symbol": tickers,  # Will be filled in by export function
        })
        logger.info(f"Scanning specified tickers: {tickers}")
    else:
        universe = build_universe(config, cache, regions=regions)
        if universe.empty:
            logger.error("No tickers in universe")
            return {"status": "error", "reason": "no_tickers"}
        region_str = " + ".join(regions) if regions else "US"
        logger.info(f"Scanning {len(universe)} tickers from {region_str} universe")
```

- [ ] **Step 6: Add the CLI flag**

In `main()` in `scanner.py`, alongside the other `parser.add_argument` calls (near line 743):

```python
    parser.add_argument(
        "--universe-from",
        metavar="PATH",
        help="Scan the tickers in a tapedeck feed (output/tapedeck-latest.json) "
             "instead of the S&P 500 / NDX universe",
    )
```

Add the import at the top of `scanner.py` with the other `src` imports:

```python
from src.universe_feed import universe_from_feed
```

Then in the `else:` branch that calls `run_scan` (near line 800), build and pass the universe:

```python
        scan_universe = universe_from_feed(args.universe_from) if args.universe_from else None
        run_scan(config, cache, vwap_configs, output_dir=args.output, regions=args.regions,
                 crypto_vwap_configs=crypto_vwap_configs,
                 indicator_settings=indicator_settings,
                 crypto_indicator_settings=crypto_indicator_settings,
                 universe=scan_universe)
```

Keep every existing keyword argument in that call exactly as it is — only `universe=scan_universe` is new.

- [ ] **Step 7: Run the full scanner suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS — all pre-existing tests plus the 5 new ones. `--universe-from` is opt-in, so no existing behaviour changes.

- [ ] **Step 8: Commit**

```bash
git add src/universe_feed.py tests/test_universe_feed.py scanner.py
git commit -m "feat: scan a tapedeck feed's tickers via --universe-from"
```

---

### Task 2: Scanner writes the JSON contract

**Repo:** `/Users/erik/Developer/trading/vwap-scanner`

**Files:**
- Create: `src/json_feed.py`
- Modify: `scanner.py` (collect every analysis in `run_scan`; add `--json-out` flag)
- Test: `tests/test_json_feed.py`

**Interfaces:**
- Consumes: `run_scan`'s `results` dict from Task 1.
- Produces: `build_json_feed(analyses: list[dict], threshold_pct: float, generated: str) -> dict` — the `schema: 1` contract tapedeck's `vwaplink.load_vwap` reads in Task 3.
- Produces: `results["analyses"]` in `run_scan` — every non-`None` analysis, not just in-range hits.

**Why `results["hits"]` is not enough:** `run_scan` appends to `hits` only when `analysis["alerts"]` is non-empty (`scanner.py:361`). The dashboard's levels ladder shows *every* level for a ticker regardless of proximity, so the JSON feed needs every analysis.

**Contract shape** — note that `pct_distance`, `in_range` and `z_stretch` are deliberately **dropped**: tapedeck recomputes them against its own live price.

```json
{ "schema": 1,
  "generated": "2026-08-03T18:22:00+02:00",
  "threshold_pct": 5.0,
  "tickers": {
    "CRDO": { "price": 197.88, "score": 0.72,
      "features": { "volume_z": 1.4, "regime_er": 0.31 },
      "levels": [ { "name": "6M", "kind": "rolling", "value": 195.50,
                    "sigma": 8.1, "direction": "reclaim" } ] } } }
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_json_feed.py`:

```python
from src.json_feed import build_json_feed

ANALYSIS = {
    "ticker": "CRDO",
    "current_price": 197.88,
    "score": 0.72,
    "features": {"volume_z": 1.4, "regime_er": 0.31},
    "vwaps": {
        "6M": {"value": 195.50, "pct_distance": 1.22, "in_range": True, "kind": "rolling",
               "sigma": 8.1, "z_stretch": 0.29, "direction": "reclaim"},
        "decade": {"value": 90.0, "pct_distance": 119.9, "in_range": False, "kind": "anchored",
                   "sigma": None, "z_stretch": None, "direction": "above"},
    },
    "alerts": ["6M"],
}


def _feed(analyses=(ANALYSIS,)):
    return build_json_feed(list(analyses), 5.0, "2026-08-03T18:22:00+02:00")


def test_header_fields():
    feed = _feed()
    assert feed["schema"] == 1
    assert feed["generated"] == "2026-08-03T18:22:00+02:00"
    assert feed["threshold_pct"] == 5.0


def test_ticker_payload():
    entry = _feed()["tickers"]["CRDO"]
    assert entry["price"] == 197.88
    assert entry["score"] == 0.72
    assert entry["features"] == {"volume_z": 1.4, "regime_er": 0.31}


def test_includes_every_level_not_just_in_range():
    levels = _feed()["tickers"]["CRDO"]["levels"]
    assert {lvl["name"] for lvl in levels} == {"6M", "decade"}


def test_drops_recomputable_fields():
    level = _feed()["tickers"]["CRDO"]["levels"][0]
    assert set(level) == {"name", "kind", "value", "sigma", "direction"}


def test_carries_direction_verbatim():
    by_name = {lvl["name"]: lvl for lvl in _feed()["tickers"]["CRDO"]["levels"]}
    assert by_name["6M"]["direction"] == "reclaim"
    assert by_name["decade"]["direction"] == "above"


def test_analysis_without_score_or_features_is_fine():
    bare = {"ticker": "BE", "current_price": 202.0,
            "vwaps": {"1M": {"value": 200.0, "kind": "rolling", "sigma": None,
                             "direction": "above"}},
            "alerts": []}
    entry = build_json_feed([bare], 5.0, "2026-08-03T18:22:00+02:00")["tickers"]["BE"]
    assert entry["score"] is None
    assert entry["features"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_json_feed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.json_feed'`

- [ ] **Step 3: Write the implementation**

Create `src/json_feed.py`:

```python
"""Structured JSON output of a scan, for external consumers (e.g. tapedeck).

Pure dict transforms — no IO. Level *values* are exported; per-level
``pct_distance``/``in_range``/``z_stretch`` are deliberately omitted because
consumers recompute them against their own live price (levels move slowly,
price moves every tick).
"""

SCHEMA = 1

_LEVEL_KEYS = ("kind", "value", "sigma", "direction")


def build_json_feed(analyses: list, threshold_pct: float, generated: str) -> dict:
    """Shape a list of ``analyze_ticker`` results into the schema-1 contract."""
    tickers = {}
    for a in analyses:
        levels = [dict(name=name, **{k: lvl.get(k) for k in _LEVEL_KEYS})
                  for name, lvl in (a.get("vwaps") or {}).items()]
        tickers[a["ticker"]] = {
            "price": a.get("current_price"),
            "score": a.get("score"),
            "features": a.get("features") or {},
            "levels": levels,
        }
    return {"schema": SCHEMA, "generated": generated,
            "threshold_pct": threshold_pct, "tickers": tickers}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_json_feed.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Collect every analysis in `run_scan`**

In `scanner.py`, add `"analyses": []` to the `results` dict literal in `run_scan` (near line 337):

```python
    results = {
        "status": "completed",
        "scanned": 0,
        "alerts_triggered": 0,
        "stale": 0,
        "no_data": 0,
        "errors": 0,
        "hits": [],
        "analyses": [],
    }
```

Then in the per-ticker loop, record every successful analysis. Replace the existing block (near line 357):

```python
            results["scanned"] += 1

            if analysis and analysis["alerts"]:
                results["alerts_triggered"] += 1
                results["hits"].append(analysis)
```

with:

```python
            results["scanned"] += 1

            if analysis:
                results["analyses"].append(analysis)
                if analysis["alerts"]:
                    results["alerts_triggered"] += 1
                    results["hits"].append(analysis)
```

- [ ] **Step 6: Add the `--json-out` flag**

Add the import at the top of `scanner.py` with the other `src` imports:

```python
from src.json_feed import build_json_feed
```

Add these imports too if they are not already present at the top of the file:

```python
import json
from datetime import datetime
```

Add the argument in `main()` beside `--universe-from`:

```python
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help="Write the structured scan contract (schema 1) to PATH, for tapedeck",
    )
```

Add the `json_out` parameter to `run_scan`'s signature, after `universe`:

```python
    universe: pd.DataFrame = None,
    json_out: str = None,
```

And write the file at the end of `run_scan`, immediately before `return results` — after the existing `if output_dir:` block:

```python
    if json_out:
        generated = datetime.now().astimezone().isoformat(timespec="seconds")
        feed = build_json_feed(results["analyses"], threshold_pct, generated)
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(feed, indent=2))
        tmp.replace(path)          # atomic: a reader never sees a half-written feed
        logger.info(f"JSON feed written to: {path} ({len(feed['tickers'])} tickers)")
```

If `Path` is not already imported in `scanner.py`, add `from pathlib import Path`.

Finally pass it through from `main()` — extend the same `run_scan(...)` call edited in Task 1:

```python
                 universe=scan_universe, json_out=args.json_out)
```

- [ ] **Step 7: Run the full scanner suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS — all pre-existing tests plus the 11 new ones across Tasks 1–2.

- [ ] **Step 8: Verify end-to-end against the real feed**

Run:
```bash
venv/bin/python scanner.py --universe-from ../tapedeck/output/tapedeck-latest.json \
  --json-out ../tapedeck/output/vwap-latest.json --rolling 1M 3M
```

Expected: the scan runs over the ~59 watchlist tickers and writes `../tapedeck/output/vwap-latest.json`.

**This is rate-limited to ~8s per uncached US ticker** — a cold run over 59 tickers takes roughly 8 minutes. That is expected; let it finish. Subsequent runs reuse the price cache and complete in seconds.

Then confirm the shape:
```bash
venv/bin/python -c "import json; d=json.load(open('../tapedeck/output/vwap-latest.json')); print(d['schema'], len(d['tickers'])); print(list(d['tickers'].items())[0])"
```
Expected: `1 <n>` followed by one ticker entry with `price`, `score`, `features`, `levels`.

- [ ] **Step 9: Commit**

```bash
git add src/json_feed.py tests/test_json_feed.py scanner.py
git commit -m "feat: write structured scan contract via --json-out"
```

---

### Task 3: `vwaplink.py` — read, validate, recompute

**Repo:** `/Users/erik/Developer/trading/tapedeck`

**Files:**
- Create: `tapedeck/vwaplink.py`
- Test: `tests/test_vwaplink.py`

**Interfaces:**
- Consumes: the `schema: 1` contract from Task 2.
- Produces, for Tasks 4–7:
  - `load_vwap(path) -> dict | None`
  - `vwap_freshness(feed, today) -> dict | None` → `{"generated": "2026-08-03", "age_days": int|None, "stale": bool}`
  - `attach_vwap(rows, feed, alert_pct) -> None` — mutates each row in place, setting `row["vwap"]` to a dict or `None`.

**`row["vwap"]` shape** (this is what every render surface reads):

```python
{"score": 0.72,
 "features": {"volume_z": 1.4},
 "levels": [{"name": "6M", "kind": "rolling", "value": 195.5, "sigma": 8.1,
             "direction": "reclaim", "pct_distance": 1.22, "in_range": True,
             "z_stretch": 0.29}],   # sorted by abs(pct_distance), nearest first
 "nearest": {...},                  # levels[0], or None if no levels survived
 "in_range_any": True}
```

**Two thresholds, do not conflate them:** the feed's `threshold_pct` (5.0) describes what the scanner put *in the file*. `alert_pct` (2.0) is tapedeck's own tighter band and is what `in_range` means everywhere in the dashboard — the Alerts entry, the row marker and the ladder highlight all agree because they all read this one flag.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vwaplink.py`:

```python
import json
from datetime import date

import pytest

from tapedeck import vwaplink

FEED = {
    "schema": 1,
    "generated": "2026-08-03T18:22:00+02:00",
    "threshold_pct": 5.0,
    "tickers": {
        "CRDO": {
            "price": 190.00,          # scan-time price; tapedeck must ignore this
            "score": 0.72,
            "features": {"volume_z": 1.4, "regime_er": 0.31},
            "levels": [
                {"name": "decade", "kind": "anchored", "value": 90.0,
                 "sigma": None, "direction": "above"},
                {"name": "6M", "kind": "rolling", "value": 195.50,
                 "sigma": 8.1, "direction": "reclaim"},
            ],
        },
    },
}


def _write(tmp_path, obj):
    p = tmp_path / "vwap-latest.json"
    p.write_text(json.dumps(obj))
    return str(p)


# ---------- load ----------

def test_load_returns_feed(tmp_path):
    assert vwaplink.load_vwap(_write(tmp_path, FEED))["schema"] == 1


def test_missing_file_returns_none(capsys):
    assert vwaplink.load_vwap("/nope/vwap-latest.json") is None
    assert "warning:" in capsys.readouterr().err


def test_malformed_json_returns_none(tmp_path, capsys):
    p = tmp_path / "vwap-latest.json"
    p.write_text("{not json")
    assert vwaplink.load_vwap(str(p)) is None
    assert "warning:" in capsys.readouterr().err


def test_unknown_schema_returns_none(tmp_path, capsys):
    assert vwaplink.load_vwap(_write(tmp_path, {**FEED, "schema": 2})) is None
    assert "schema" in capsys.readouterr().err


# ---------- freshness ----------

def test_freshness_age_in_calendar_days():
    fresh = vwaplink.vwap_freshness(FEED, date(2026, 8, 6))
    assert fresh["generated"] == "2026-08-03"
    assert fresh["age_days"] == 3
    assert fresh["stale"] is False


def test_freshness_marks_stale_past_threshold():
    fresh = vwaplink.vwap_freshness(FEED, date(2026, 8, 15))
    assert fresh["age_days"] == 12
    assert fresh["stale"] is True


def test_freshness_of_none_is_none():
    assert vwaplink.vwap_freshness(None, date(2026, 8, 3)) is None


def test_unparseable_generated_degrades_to_none_age():
    fresh = vwaplink.vwap_freshness({**FEED, "generated": "whenever"}, date(2026, 8, 3))
    assert fresh["age_days"] is None
    assert fresh["stale"] is False


# ---------- attach / recompute ----------

def test_recomputes_distance_against_live_price_not_scan_price():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    # (197.88 - 195.50) / 195.50 * 100 == 1.217...  — NOT computed from 190.00
    assert by_name["6M"]["pct_distance"] == pytest.approx(1.2174, abs=1e-3)


def test_levels_sorted_nearest_first():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert [lvl["name"] for lvl in rows[0]["vwap"]["levels"]] == ["6M", "decade"]
    assert rows[0]["vwap"]["nearest"]["name"] == "6M"


def test_in_range_uses_alert_pct_not_feed_threshold():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    assert by_name["6M"]["in_range"] is True        # 1.22% <= 2.0%
    assert by_name["decade"]["in_range"] is False   # 119% is in the file, not in range
    assert rows[0]["vwap"]["in_range_any"] is True


def test_tighter_alert_pct_excludes_the_level():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 1.0)
    assert rows[0]["vwap"]["in_range_any"] is False


def test_z_stretch_recomputed_and_none_without_sigma():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    assert by_name["6M"]["z_stretch"] == pytest.approx((197.88 - 195.50) / 8.1, abs=1e-4)
    assert by_name["decade"]["z_stretch"] is None


def test_direction_carried_verbatim():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"]["nearest"]["direction"] == "reclaim"


def test_score_and_features_carried():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"]["score"] == 0.72
    assert rows[0]["vwap"]["features"]["volume_z"] == 1.4


def test_ticker_absent_from_feed_gets_none():
    rows = [{"ticker": "NVDA", "price": 100.0}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_row_without_price_gets_none():
    rows = [{"ticker": "CRDO", "price": None}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_nonpositive_level_value_is_skipped():
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": None, "features": {},
        "levels": [{"name": "bad", "kind": "rolling", "value": 0,
                    "sigma": None, "direction": "above"}]}}}
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_attach_with_none_feed_sets_none_on_every_row():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, None, 2.0)
    assert rows[0]["vwap"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_vwaplink.py -q`
Expected: FAIL — `ImportError: cannot import name 'vwaplink'`

- [ ] **Step 3: Write the implementation**

Create `tapedeck/vwaplink.py`:

```python
"""Read-only bridge to an external vwap-scanner feed (JSON).

This module is a strictly read-only consumer: the only filesystem access is
``Path(path).read_text()`` in ``load_vwap`` — nothing here ever writes to the
scanner's files. Any failure (missing file, malformed JSON, unknown schema)
degrades to ``None`` with a stderr warning so the dashboard run always
survives.

Distances are recomputed locally. The feed stores level *values*; VWAP levels
move slowly while price moves every tick, so recomputing against tapedeck's
live price keeps last night's scan useful all day and guarantees the numbers
on the page agree with the price rendered beside them. ``direction`` is the
one field carried verbatim — it is a bar-over-bar classification the scanner
derives from its own prior close, and tapedeck has no equivalent basis for it.
"""

import json
import sys
from datetime import date
from pathlib import Path

SCHEMA = 1
STALE_DAYS = 7
DEFAULT_ALERT_PCT = 2.0

_LEVEL_KEYS = ("name", "kind", "value", "sigma", "direction")


def load_vwap(path):
    """Read + validate a vwap-scanner feed. Returns None (and warns) on any failure."""
    try:
        feed = json.loads(Path(path).read_text())
    except Exception as exc:
        print(f"warning: vwap feed not readable ({exc}) — levels omitted", file=sys.stderr)
        return None
    schema = feed.get("schema")
    if schema != SCHEMA:
        print(f"warning: vwap feed schema {schema!r} != {SCHEMA} — levels omitted", file=sys.stderr)
        return None
    return feed


def vwap_freshness(feed, today):
    """Age the feed's `generated` stamp against `today` (a datetime.date)."""
    if not feed:
        return None
    stamp = feed.get("generated")
    generated, age = None, None
    if stamp:
        try:
            generated = date.fromisoformat(str(stamp)[:10])
            age = (today - generated).days
        except ValueError:
            generated = None
    return {"generated": generated.isoformat() if generated else None,
            "age_days": age,
            "stale": age is not None and age > STALE_DAYS}


def attach_vwap(rows, feed, alert_pct):
    """Set ``row["vwap"]`` on every row, in place (None where unavailable).

    ``alert_pct`` is tapedeck's own proximity band and defines ``in_range``
    everywhere in the dashboard — deliberately tighter than the feed's
    ``threshold_pct``, which only describes what the scan put in the file.
    """
    tickers = (feed or {}).get("tickers") or {}
    for row in rows:
        row["vwap"] = _for_row(tickers.get(row["ticker"]), row.get("price"), alert_pct)


def _for_row(entry, price, alert_pct):
    if not entry or price is None:
        return None
    levels = []
    for raw in entry.get("levels") or []:
        value = raw.get("value")
        if value is None or value <= 0:
            continue
        sigma = raw.get("sigma")
        pct_distance = (price - value) / value * 100
        levels.append({**{k: raw.get(k) for k in _LEVEL_KEYS},
                       "pct_distance": pct_distance,
                       "in_range": abs(pct_distance) <= alert_pct,
                       "z_stretch": (price - value) / sigma if sigma else None})
    if not levels:
        return None
    levels.sort(key=lambda lvl: abs(lvl["pct_distance"]))
    return {"score": entry.get("score"),
            "features": entry.get("features") or {},
            "levels": levels,
            "nearest": levels[0],
            "in_range_any": any(lvl["in_range"] for lvl in levels)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_vwaplink.py -q`
Expected: PASS (19 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: PASS — 97 pre-existing + 19 new = 116.

- [ ] **Step 6: Commit**

```bash
git add tapedeck/vwaplink.py tests/test_vwaplink.py
git commit -m "feat: read-only vwap-scanner feed bridge"
```

---

### Task 4: Config keys and CLI wiring

**Repo:** `/Users/erik/Developer/trading/tapedeck`

**Files:**
- Modify: `tapedeck/config.py` (template line 14; `load_config` return at lines 49–52; `load_watchlists` append at lines 63–65)
- Modify: `tapedeck.py` (import line 60; render loop lines 122–126)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `vwaplink.load_vwap`, `vwaplink.vwap_freshness`, `vwaplink.attach_vwap` from Task 3.
- Produces: `cfg["vwap"]` (str | None) and `cfg["vwap_alert_pct"]` (float) from `load_config`, both carried through `load_watchlists`.
- Produces: `rendered["vwap_fresh"]` on each entry of `rendered_lists`, and `row["vwap"]` on every row — read by Tasks 5–7.

After this task the data reaches the renderer but nothing is displayed yet. That is intentional: it keeps the wiring independently reviewable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_vwap_keys_default_to_none_and_2pct(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("holdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap"] is None
    assert cfg["vwap_alert_pct"] == 2.0


def test_vwap_keys_parsed(tmp_path):
    p = tmp_path / "wl.yaml"
    p.write_text("vwap: /tmp/vwap-latest.json\nvwap_alert_pct: 1.5\n"
                 "holdings:\n  - ticker: NVDA\n")
    cfg = config.load_config(p)
    assert cfg["vwap"] == "/tmp/vwap-latest.json"
    assert cfg["vwap_alert_pct"] == 1.5


def test_vwap_keys_reach_watchlists(tmp_path):
    (tmp_path / "a.yaml").write_text("vwap: /tmp/v.json\nvwap_alert_pct: 3\n"
                                     "holdings:\n  - ticker: NVDA\n")
    wl = config.load_watchlists(tmp_path)[0]
    assert wl["vwap"] == "/tmp/v.json"
    assert wl["vwap_alert_pct"] == 3.0
```

Check the top of `tests/test_config.py` for how it imports the module — match the existing import style (it will already import `config`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_config.py -q`
Expected: FAIL — `KeyError: 'vwap'`

- [ ] **Step 3: Add the keys to `load_config`**

In `tapedeck/config.py`, extend the return dict of `load_config` (currently lines 49–52):

```python
    return {"benchmark": str(raw.get("benchmark") or "SPY").upper(),
            "title": raw.get("title"), "order": raw.get("order"), "holdings": holdings,
            "cockpit": str(raw["cockpit"]) if raw.get("cockpit") else None,
            "anti_basket": str(raw["anti_basket"]).strip() if raw.get("anti_basket") else None,
            "vwap": str(raw["vwap"]) if raw.get("vwap") else None,
            "vwap_alert_pct": float(raw.get("vwap_alert_pct") or 2.0)}
```

Extend the `load_watchlists` append (currently lines 63–65):

```python
        watchlists.append({"name": path.stem, "title": title, "order": cfg["order"],
                           "benchmark": cfg["benchmark"], "holdings": cfg["holdings"],
                           "cockpit": cfg["cockpit"], "anti_basket": cfg["anti_basket"],
                           "vwap": cfg["vwap"], "vwap_alert_pct": cfg["vwap_alert_pct"]})
```

And document the keys in `_TEMPLATE`, after the `anti_basket` comment on line 14:

```python
# vwap: /path/to/vwap-latest.json  # optional: VWAP levels from a vwap-scanner --json-out feed
# vwap_alert_pct: 2.0              # optional: proximity band (%) that earns an Alerts entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Wire it into the CLI**

In `tapedeck.py`, add `vwaplink` to the package import on line 60:

```python
    from tapedeck import config, feed, fetch, metrics, pipeline, render, snapshot, tvscan, vaultlink, vwaplink
```

In the per-watchlist loop, load the feed and attach it to the rows **immediately after `build_rows`** — before `build_alerts`, which Task 5 will teach to read `row["vwap"]`. Replace the loop body's first two lines (lines 114–115):

```python
        rows, summary = pipeline.build_rows(hists, bench_close, infos, wl["holdings"], today, tv=tv)
        vwap_feed = vwaplink.load_vwap(wl["vwap"]) if wl.get("vwap") else None
        vwaplink.attach_vwap(rows, vwap_feed, wl.get("vwap_alert_pct") or vwaplink.DEFAULT_ALERT_PCT)
        alert_list = alerts_mod.build_alerts(rows, today)
```

Then extend the `rendered_lists.append(...)` call (lines 123–126) with the freshness stamp:

```python
        rendered_lists.append({"name": wl["name"], "title": wl["title"], "benchmark": wl["benchmark"],
                               "rows": rows, "summary": summary, "alerts": alert_list, "diff": diff,
                               "cockpit": cockpit,
                               "cockpit_fresh": vaultlink.cockpit_freshness(cockpit, today),
                               "vwap_fresh": vwaplink.vwap_freshness(vwap_feed, today)})
```

Note the single-config path at line 75 builds its own watchlist dict — add the two keys there as well so `--config` mode does not `KeyError`:

```python
                       "cockpit": cfg["cockpit"], "anti_basket": None,
                       "vwap": cfg["vwap"], "vwap_alert_pct": cfg["vwap_alert_pct"]}]
```

- [ ] **Step 6: Verify the wiring runs**

Run: `.venv/bin/python3 tapedeck.py --no-open --list market-pulse`
Expected: completes normally. No watchlist has a `vwap:` key yet, so no warning appears and nothing changes on the page.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: PASS (119)

- [ ] **Step 8: Commit**

```bash
git add tapedeck/config.py tapedeck.py tests/test_config.py
git commit -m "feat: vwap + vwap_alert_pct watchlist keys, wired to rows"
```

---

### Task 5: Alerts surface

**Repo:** `/Users/erik/Developer/trading/tapedeck`

**Files:**
- Modify: `tapedeck/alerts.py` (new function; `build_alerts` is untouched)
- Modify: `tapedeck.py` (extend `alert_list`)
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `row["vwap"]` from Task 3.
- Produces: `build_vwap_alerts(rows) -> list[dict]` — same alert shape the existing Alerts panel renders: `{"ticker", "kind", "text", "severity"}` with severity in `{"good", "bad", "warn"}` (see `render.py:283`).

A ticker contributes **at most one** alert — its nearest in-range level. A name sitting on three VWAPs at once is one situation, not three chips.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_alerts.py`:

```python
def _row(ticker, levels, in_range_any=True):
    return {"ticker": ticker,
            "vwap": {"score": None, "features": {}, "levels": levels,
                     "nearest": levels[0], "in_range_any": in_range_any}}


def test_in_range_level_produces_one_alert():
    rows = [_row("CRDO", [{"name": "6M", "kind": "rolling", "pct_distance": -1.2,
                           "in_range": True, "direction": "reclaim"}])]
    out = alerts.build_vwap_alerts(rows)
    assert len(out) == 1
    assert out[0]["ticker"] == "CRDO"
    assert out[0]["kind"] == "vwap"
    assert out[0]["text"] == "1.2% below 6M VWAP · reclaiming"


def test_above_level_reads_above():
    rows = [_row("BE", [{"name": "1M", "kind": "rolling", "pct_distance": 0.8,
                         "in_range": True, "direction": "reject"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.8% above 1M VWAP · rejecting"


def test_only_nearest_level_alerts():
    rows = [_row("FN", [
        {"name": "1M", "kind": "rolling", "pct_distance": 0.3, "in_range": True, "direction": "above"},
        {"name": "3M", "kind": "rolling", "pct_distance": 1.9, "in_range": True, "direction": "above"},
    ])]
    out = alerts.build_vwap_alerts(rows)
    assert len(out) == 1
    assert "1M" in out[0]["text"]


def test_reclaim_is_good_reject_is_bad_else_warn():
    def sev(direction):
        rows = [_row("X", [{"name": "1M", "kind": "rolling", "pct_distance": 0.1,
                            "in_range": True, "direction": direction}])]
        return alerts.build_vwap_alerts(rows)[0]["severity"]
    assert sev("reclaim") == "good"
    assert sev("reject") == "bad"
    assert sev("above") == "warn"


def test_out_of_range_produces_nothing():
    rows = [_row("CIEN", [{"name": "6M", "kind": "rolling", "pct_distance": 4.5,
                           "in_range": False, "direction": "above"}], in_range_any=False)]
    assert alerts.build_vwap_alerts(rows) == []


def test_row_without_vwap_produces_nothing():
    assert alerts.build_vwap_alerts([{"ticker": "NVDA", "vwap": None}]) == []
    assert alerts.build_vwap_alerts([{"ticker": "NVDA"}]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_alerts.py -q`
Expected: FAIL — `AttributeError: module 'tapedeck.alerts' has no attribute 'build_vwap_alerts'`

- [ ] **Step 3: Write the implementation**

Append to `tapedeck/alerts.py`:

```python
_VWAP_SEVERITY = {"reclaim": "good", "reject": "bad"}
_VWAP_DIRECTION = {"reclaim": "reclaiming", "reject": "rejecting"}


def build_vwap_alerts(rows):
    """One alert per ticker sitting within its watchlist's VWAP proximity band.

    Only the nearest in-range level alerts: a name resting on three VWAPs at
    once is one situation, not three chips. `in_range` is set by vwaplink
    against the list's `vwap_alert_pct`, so this rule needs no threshold of
    its own.
    """
    out = []
    for row in rows:
        vwap = row.get("vwap")
        if not vwap or not vwap.get("in_range_any"):
            continue
        level = next((lvl for lvl in vwap["levels"] if lvl["in_range"]), None)
        if not level:
            continue
        side = "above" if level["pct_distance"] >= 0 else "below"
        text = f'{abs(level["pct_distance"]):.1f}% {side} {level["name"]} VWAP'
        direction = _VWAP_DIRECTION.get(level.get("direction"))
        if direction:
            text += f" · {direction}"
        out.append({"ticker": row["ticker"], "kind": "vwap", "text": text,
                    "severity": _VWAP_SEVERITY.get(level.get("direction"), "warn")})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_alerts.py -q`
Expected: PASS

- [ ] **Step 5: Wire into the CLI**

In `tapedeck.py`, Task 4 already placed `attach_vwap` before the alert line, so this is a one-line change. Replace:

```python
        alert_list = alerts_mod.build_alerts(rows, today)
```

with:

```python
        alert_list = alerts_mod.build_alerts(rows, today) + alerts_mod.build_vwap_alerts(rows)
```

Leave every other line in the loop exactly as it is.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: PASS (125)

- [ ] **Step 7: Commit**

```bash
git add tapedeck/alerts.py tapedeck.py tests/test_alerts.py
git commit -m "feat: VWAP proximity alerts"
```

---

### Task 6: VWAP columns and toggle

**Repo:** `/Users/erik/Developer/trading/tapedeck`

**Files:**
- Modify: `tapedeck/render.py` (`CORE, EXT, POS` line 88; `COLUMNS` lines 90–118; `_cell` line 162; `_section_html` line 418; the toggle buttons and `wireToggle` calls near line 680; CSS)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `row["vwap"]` from Task 3, `wl["vwap_fresh"]` from Task 4.
- Produces: the `c-vwap` column class and `show-vwap` table class, mirroring the existing `c-ext`/`show-ext` pair.

**Pattern to follow exactly:** columns are hidden by default via CSS on `.c-vwap`, and revealed when the table gains `show-vwap` — identical to how `c-ext`/`show-ext` works today. `wireToggle('vwapbtn', 'show-vwap')` mirrors `wireToggle('extbtn', 'show-ext')` at line 681.

**Note on `render.py`'s JS:** `render_multi` builds the page inside an f-string, so every literal `{` and `}` in JavaScript and CSS must be doubled (`{{`/`}}`). Copy the surrounding style.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`:

```python
# --- vwap levels ---

def vwap_data(**overrides):
    level = {"name": "6M", "kind": "rolling", "value": 195.5, "sigma": 8.1,
             "direction": "reclaim", "pct_distance": 1.22,
             "in_range": True, "z_stretch": 0.29}
    data = {"score": 0.72, "features": {"volume_z": 1.4},
            "levels": [level], "nearest": level, "in_range_any": True}
    data.update(overrides)
    return data


def vwap_page(vwap=None, fresh=None, second_row=True):
    rows = [sample_row(vwap=vwap if vwap is not None else vwap_data())]
    if second_row:
        rows.append(empty_row(vwap=None))
    section = wl("a", "A", rows)
    if fresh is not None:
        section["vwap_fresh"] = fresh
    return render.render_multi([section], TODAY)


def test_vwap_columns_render_nearest_level():
    html = vwap_page()
    assert "c-vwap" in html
    assert "6M" in html
    assert "0.72" in html


def test_vwap_toggle_button_present_when_a_list_has_vwap():
    html = vwap_page()
    assert 'id="vwapbtn"' in html
    assert "show-vwap" in html


def test_no_vwap_button_when_no_list_has_vwap():
    html = render.render_multi([wl("a", "A", [sample_row()])], TODAY)
    assert 'id="vwapbtn"' not in html
    assert "c-vwap" not in html


def test_ticker_without_vwap_renders_empty_cells_not_zero():
    html = vwap_page()
    assert '<td class="c-vwap a-r"></td>' in html


def test_feed_chip_rendered_with_age():
    html = vwap_page(fresh={"generated": "2026-07-20", "age_days": 14, "stale": True})
    assert "levels from 2026-07-20" in html
    assert "(14d)" in html
    assert "vwap-stale" in html


def test_no_chip_without_freshness():
    assert "levels from" not in vwap_page()
```

`sample_row(vwap=...)` works because `sample_row` merges `**overrides` into its base dict. `empty_row(vwap=None)` gives a second row with no VWAP data, which is what `test_ticker_without_vwap_renders_empty_cells_not_zero` checks.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_render.py -q`
Expected: FAIL — `assert 'c-vwap' in html`

- [ ] **Step 3: Add the column class and columns**

In `tapedeck/render.py`, extend line 88:

```python
CORE, EXT, POS, VWAP = "", "c-ext", "c-pos", "c-vwap"
```

Append these four entries to the end of the `COLUMNS` list (after the `open_pnl` entry):

```python
    {"key": "vwap_level", "label": "VWAP",     "cls": VWAP, "align": "l"},
    {"key": "vwap_dist",  "label": "→VWAP",    "cls": VWAP, "align": "r"},
    {"key": "vwap_z",     "label": "σ",        "cls": VWAP, "align": "r"},
    {"key": "vwap_score", "label": "Score",    "cls": VWAP, "align": "r"},
```

- [ ] **Step 4: Render the cells**

In `_cell` (line 162), add these branches before the final `raise KeyError(key)`. Match the surrounding style — `_td` handles the class and the `data-v` sort key:

```python
    if key.startswith("vwap_"):
        vwap = row.get("vwap")
        if not vwap:
            return _td("", col)
        nearest = vwap["nearest"]
        if key == "vwap_level":
            cls = "good" if nearest["in_range"] else ""
            return _td(h.escape(nearest["name"]), col, v=nearest["name"], extra_cls=cls)
        if key == "vwap_dist":
            pct = nearest["pct_distance"]
            style = f"background:rgba(56,161,105,{heat_alpha(pct, 5.0):.3f})" if nearest["in_range"] else ""
            return _td(fmt_pct(pct, 1), col, v=pct, style=style)
        if key == "vwap_z":
            return _td(fmt_num(nearest["z_stretch"], 2), col, v=nearest["z_stretch"])
        if key == "vwap_score":
            return _td(fmt_num(vwap["score"], 2), col, v=vwap["score"])
```

`fmt_num(None, 2)` and `fmt_pct(None, 1)` return `"n/a"` (`render.py:19-30`) — correct and intended here. A level with no `sigma` shows `n/a` in the σ column, exactly as the P/E column already does for an ETF. Only the *whole row has no VWAP data* case renders an empty cell.

- [ ] **Step 5: Hide the columns unless a list has VWAP data**

In `_section_html` (line 418), the `cols` filter currently drops position columns when no row has a position. Extend it the same way:

```python
    has_pos = any(r.get("position") for r in rows_sorted)
    has_vwap = any(r.get("vwap") for r in rows_sorted)
    ...
    cols = [c for c in COLUMNS
            if (has_pos or c["cls"] != POS) and (has_vwap or c["cls"] != VWAP)]
```

`_section_html` currently ends `return section, has_pos`. Change it to `return section, has_pos, has_vwap`, and update the accumulator loop at the top of `render_multi` (lines 459–464) to match:

```python
def render_multi(lists, today, data_date=None):
    sections, any_pos, any_vwap = [], False, False
    for wl in lists:
        section, has_pos, has_vwap = _section_html(wl, today)
        sections.append(section)
        any_pos = any_pos or has_pos
        any_vwap = any_vwap or has_vwap
```

`render_page` (line 452) delegates to `render_multi` and does not unpack this tuple, so it needs no change.

- [ ] **Step 6: Add the toggle button, freshness chip and CSS**

`render_multi` builds `pos_btn` at line 473 and interpolates it into the button bar at lines 620–622. Add a third button the same way. Beside line 473:

```python
    vwap_btn = '<button id="vwapbtn" class="tbtn">VWAP</button>' if any_vwap else ""
```

and in the button bar, between `{pos_btn}` and the theme button:

```html
  <button id="extbtn" class="tbtn">Extended</button>
  {pos_btn}
  {vwap_btn}
  <button id="themebtn" class="tbtn">Theme: auto</button>
```

Add the freshness chip inside `_section_html`, immediately before `_alerts_html(...)` in the section concatenation:

```python
        + _vwap_chip(wl.get("vwap_fresh"))
```

And define it beside `_cockpit_html`:

```python
def _vwap_chip(fresh):
    """Age stamp for the VWAP feed. Empty string when no feed is attached."""
    if not fresh or not fresh.get("generated"):
        return ""
    age = fresh.get("age_days")
    cls = "warn" if fresh.get("stale") else ""
    sub = f" ({age}d)" if age is not None else ""
    return (f'<section class="panel"><span class="ptitle">VWAP</span>'
            f'<span class="chip {cls}">levels from {h.escape(fresh["generated"])}{sub}</span></section>')
```

In the CSS block, beside the existing `.c-ext` rule, add:

```css
.c-vwap {{ display: none; }}
table.show-vwap .c-vwap {{ display: table-cell; }}
.vwap-stale {{ opacity: .55; }}
```

In the JS block, beside `wireToggle('posbtn', 'show-pos');`:

```javascript
  wireToggle('vwapbtn', 'show-vwap');
```

Finally, dim the values when the feed is stale. `_section_html` currently opens the table with `f'<div class="tablewrap"><table class="wltbl">'`. Make the class list conditional:

```python
    stale_cls = " vwap-stale" if (wl.get("vwap_fresh") or {}).get("stale") else ""
```

and use it in that markup:

```python
          f'<div class="tablewrap"><table class="wltbl{stale_cls}">'
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_render.py -q`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: PASS (131)

- [ ] **Step 9: Commit**

```bash
git add tapedeck/render.py tests/test_render.py
git commit -m "feat: VWAP columns behind a toggle, with feed freshness chip"
```

---

### Task 7: Row marker and levels ladder

**Repo:** `/Users/erik/Developer/trading/tapedeck`

**Files:**
- Modify: `tapedeck/render.py` (`_detail_row` line 247; the `mainrow` `<tr>` in `_section_html` line 429; CSS)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `row["vwap"]` from Task 3.
- Produces: no new interface — these are the last two display surfaces.

The ladder goes **above** the TradingView charts inside the existing detail row, so an expanded ticker reads levels-then-charts.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render.py`, reusing `vwap_data()` and `vwap_page()` from Task 6:

```python
def test_ladder_lists_every_level_with_kind_and_value():
    far = {"name": "decade", "kind": "anchored", "value": 90.0, "sigma": None,
           "direction": "above", "pct_distance": 119.9, "in_range": False,
           "z_stretch": None}
    near = vwap_data()["levels"][0]
    html = vwap_page(vwap_data(levels=[near, far], nearest=near))
    assert "vwapladder" in html
    assert "decade" in html and "anchored" in html
    assert "$90.00" in html


def test_ladder_highlights_in_range_rows():
    assert "lvl-hit" in vwap_page()


def test_ladder_absent_when_ticker_has_no_vwap():
    html = render.render_multi([wl("a", "A", [sample_row()])], TODAY)
    assert "vwapladder" not in html


def test_ladder_labels_direction_as_scan_dated():
    assert "(at scan)" in vwap_page()


def test_main_row_marked_when_in_range():
    assert "vwap-hit" in vwap_page()


def test_main_row_unmarked_when_out_of_range():
    cold = {"name": "6M", "kind": "rolling", "value": 195.5, "sigma": 8.1,
            "direction": "above", "pct_distance": 4.4, "in_range": False,
            "z_stretch": 0.29}
    html = vwap_page(vwap_data(levels=[cold], nearest=cold, in_range_any=False))
    assert "vwap-hit" not in html
    assert "lvl-hit" not in html
```

Note `fmt_price` renders `$90.00`, not `90.00` (`render.py:23`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_render.py -q`
Expected: FAIL — `assert 'vwapladder' in html`

- [ ] **Step 3: Build the ladder**

In `tapedeck/render.py`, add beside `_detail_row`:

```python
_LADDER_DIRECTION = {"reclaim": "reclaimed", "reject": "rejected",
                     "above": "above", "below": "below"}


def _ladder_html(vwap):
    """All VWAP levels for one ticker, nearest first. Empty when none attached.

    `direction` is dated to the scan, not to now — vwaplink recomputes
    distances against the live price but cannot recompute a bar-over-bar
    classification, so the column says so.
    """
    if not vwap:
        return ""
    body = "".join(
        f'<tr class="{"lvl-hit" if lvl["in_range"] else ""}">'
        f'<td>{h.escape(lvl["name"])}</td>'
        f'<td class="lvl-kind">{h.escape(lvl.get("kind") or "")}</td>'
        f'<td class="a-r">{fmt_price(lvl["value"])}</td>'
        f'<td class="a-r">{fmt_pct(lvl["pct_distance"], 1)}</td>'
        f'<td class="a-r">{fmt_num(lvl["z_stretch"], 2)}</td>'
        f'<td>{h.escape(_LADDER_DIRECTION.get(lvl.get("direction"), ""))}</td>'
        f"</tr>"
        for lvl in vwap["levels"])
    return (f'<div class="vwapladder"><table>'
            f'<thead><tr><th>Level</th><th>Kind</th><th class="a-r">Value</th>'
            f'<th class="a-r">Dist</th><th class="a-r">σ</th>'
            f'<th>Direction <span class="lvl-note">(at scan)</span></th></tr></thead>'
            f"<tbody>{body}</tbody></table></div>")
```

- [ ] **Step 4: Put the ladder in the detail row**

Change `_detail_row` (line 247) to take the row's VWAP data and emit the ladder above the charts:

```python
def _detail_row(row, ncols):
    symbol = row.get("tv_symbol") or row["ticker"]
    charts = "".join(
        f'<div class="tvchart"><div class="tvlabel">{label} · {h.escape(symbol)}</div>'
        f'<div class="tvbox" data-tf="{tf}"></div></div>'
        for label, tf in TV_TIMEFRAMES)
    return (f'<tr class="detail" data-for="{h.escape(row["ticker"])}" hidden>'
            f'<td colspan="{ncols}">'
            + _ladder_html(row.get("vwap"))
            + f'<div class="tvpanel" data-symbol="{h.escape(symbol)}">'
              f'<div class="tvhint">Loading TradingView charts…</div>'
              f'<div class="tvcharts">{charts}</div></div></td></tr>')
```

- [ ] **Step 5: Mark the main row**

In `_section_html` (line 429), add the marker class to rows in range:

```python
    body = "\n".join(
        f'<tr class="mainrow{" vwap-hit" if (r.get("vwap") or {}).get("in_range_any") else ""}" '
        f'data-ticker="{h.escape(r["ticker"])}">'
        + "".join(_cell(r, c, ctx) for c in cols)
        + "</tr>\n" + _detail_row(r, len(cols))
        for r in rows_sorted)
```

- [ ] **Step 6: Add the CSS**

In the CSS block (remember to double every brace inside the f-string):

```css
.vwapladder {{ margin: 0 0 10px; overflow-x: auto; }}
.vwapladder table {{ border-collapse: collapse; font-size: 12px; }}
.vwapladder th, .vwapladder td {{ padding: 3px 10px; white-space: nowrap; }}
.vwapladder tr.lvl-hit {{ background: rgba(56,161,105,.14); font-weight: 600; }}
.lvl-kind, .lvl-note {{ opacity: .6; font-weight: 400; }}
tr.mainrow.vwap-hit td:first-child {{ box-shadow: inset 3px 0 0 #38a169; }}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_render.py -q`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python3 -m pytest tests/ -q`
Expected: PASS (137)

- [ ] **Step 9: Commit**

```bash
git add tapedeck/render.py tests/test_render.py
git commit -m "feat: VWAP row marker and levels ladder in the expanded row"
```

---

### Task 8: End-to-end verification and docs

**Repo:** both

**Files:**
- Modify: `watchlists/fmfb-book.yaml` (local only — this directory is gitignored, so nothing here is committed)
- Modify: `README.md`, `CHANGELOG.md` (tapedeck)
- Modify: `README.md` (vwap-scanner)

- [ ] **Step 1: Point a real watchlist at the feed**

Add to `watchlists/fmfb-book.yaml`:

```yaml
vwap: /Users/erik/Developer/trading/tapedeck/output/vwap-latest.json
vwap_alert_pct: 2.0
```

- [ ] **Step 2: Regenerate the feed and the page**

```bash
cd /Users/erik/Developer/trading/vwap-scanner && venv/bin/python scanner.py \
  --universe-from ../tapedeck/output/tapedeck-latest.json \
  --json-out ../tapedeck/output/vwap-latest.json
cd /Users/erik/Developer/trading/tapedeck && .venv/bin/python3 tapedeck.py --no-open
```

Expected: no warnings on stderr; both files written.

- [ ] **Step 3: Verify all four surfaces in the browser**

```bash
open output/tapedeck-$(date +%F).html
```

Confirm, on the FMFB Book tab:
1. A `VWAP` panel chip showing the feed date.
2. VWAP proximity entries in the Alerts panel.
3. A `VWAP` toggle button that reveals four columns.
4. A green left edge on rows in range.
5. Clicking a marked ticker shows the levels ladder above the charts, with in-range rows highlighted.

Confirm on the Market Pulse tab (no `vwap:` key): no VWAP chip, no toggle columns, no ladder — the page is unchanged.

**If a surface is missing, fix it before proceeding.** Do not mark this step complete on an unverified page.

- [ ] **Step 4: Verify graceful degradation**

```bash
mv output/vwap-latest.json output/vwap-latest.json.bak
.venv/bin/python3 tapedeck.py --no-open
mv output/vwap-latest.json.bak output/vwap-latest.json
```

Expected: one `warning: vwap feed not readable ...` line on stderr, the run completes, and the page renders exactly as it did before the feature existed.

- [ ] **Step 5: Update tapedeck docs**

In `README.md`, add to the watchlist yaml example block:

```yaml
vwap: /path/to/vwap-latest.json   # optional: VWAP levels from a vwap-scanner --json-out feed
vwap_alert_pct: 2.0               # optional: proximity band (%) that earns an alert (default 2.0)
```

Add a bullet to the "What's on the page" list, after the **Cockpit** entry:

```markdown
- **VWAP** (only with `vwap:`) — rolling and anchored VWAP levels from a
  [vwap-scanner](../vwap-scanner) run: proximity alerts, four sortable columns
  behind the VWAP toggle, a green edge on rows in range, and a full levels
  ladder in the expanded row. Distances are recomputed against the live price
  on every run, so an overnight scan stays accurate through the day; the
  `direction` column is dated to the scan. Refresh the feed with
  `vwap-scanner --universe-from output/tapedeck-latest.json --json-out output/vwap-latest.json`.
```

Add `tapedeck/vwaplink.py` to the Layout section beside `vaultlink.py`.

Add a CHANGELOG entry at the top, matching the existing style (what changed, then a WHY line).

- [ ] **Step 6: Update vwap-scanner docs**

In its `README.md`, add to the Usage block:

```bash
python scanner.py --universe-from ../tapedeck/output/tapedeck-latest.json \
                  --json-out ../tapedeck/output/vwap-latest.json
```

with a sentence noting `--universe-from` scans a tapedeck feed's tickers (covering names outside the S&P 500 / NDX universe) and `--json-out` writes the schema-1 contract tapedeck reads.

- [ ] **Step 7: Run both suites**

```bash
cd /Users/erik/Developer/trading/tapedeck && .venv/bin/python3 -m pytest tests/ -q
cd /Users/erik/Developer/trading/vwap-scanner && venv/bin/python -m pytest -q
```
Expected: both PASS.

- [ ] **Step 8: Commit (two commits, one per repo)**

```bash
cd /Users/erik/Developer/trading/tapedeck
git add README.md CHANGELOG.md
git commit -m "docs: VWAP levels integration"

cd /Users/erik/Developer/trading/vwap-scanner
git add README.md
git commit -m "docs: --universe-from and --json-out"
```
