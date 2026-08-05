# TAPEDECK — Watchlist Dashboard

Self-contained multi-watchlist tracker inspired by the "Situational Awareness
Holdings" table by [Lin @speculator_io](https://x.com/speculator_io). One
command fetches live data for every watchlist and writes one interactive HTML
dashboard with a tab per list — no API key, nothing to sign up for.

Run it as a CLI, or as a Mac app in your Dock.

## The app

```bash
cd native && make install      # → ~/Applications/TAPEDECK.app
```

Its own Dock icon and window. Opening it starts a local server; quitting it
stops that server. The dashboard gains three buttons in its controls row:
**⟳ Refresh** (re-runs the fetch, ~20s), **◇ Rescan VWAP** (re-runs
[vwap-scanner](../vwap-scanner), ~8 min cold) and **✎ Lists** (the watchlist
editor). The two run buttons stream progress into a live status line and reload
the page when they finish; one job runs at a time. Launch is instant — it shows
the last run and only fetches when asked.

**✎ Lists** creates and edits watchlists without leaving the app: add and remove
tickers, set the title, benchmark, source, groups, shares and cost basis, then
**Save & Refresh** to fetch the new list straight away. Ticker input
autocompletes from the venue's live market list when a list's source is
trade.xyz. Two things worth knowing: a saved file is rewritten by the editor, so
**comments in it are lost** (the editor warns you first), and every save or
delete copies the previous version to `output/watchlist-backups/` first. Writes
are refused while a fetch is running, since that run is reading the same files.

Needs Xcode plus `brew install xcodegen librsvg` once. Build details, the
shutdown guarantees and the design notes are in [`native/README.md`](native/README.md).

Without the app, `tapedeck.py --serve` gives the same page and buttons at
`http://127.0.0.1:7360/`.

Note: the app serves over `http://127.0.0.1` where a plain run opens `file://`.
`localStorage` is scoped per origin, so the remembered tab and theme reset once
on first launch.

## Setup & run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python3 tapedeck.py                 # all watchlists → output/tapedeck-DATE.html → browser
.venv/bin/python3 tapedeck.py --new "my semis"  # scaffold a new watchlist file
.venv/bin/python3 tapedeck.py --list my-semis # only some lists (comma-separated names)
.venv/bin/python3 tapedeck.py --png           # also export PNG (headless Chrome)
.venv/bin/python3 tapedeck.py --json          # machine-readable summary to stdout
# every run also writes the same feed to output/tapedeck-latest.json (stable path)
.venv/bin/python3 tapedeck.py --no-open       # don't open the browser
.venv/bin/python3 tapedeck.py --serve         # serve the last run at :7360 with Refresh buttons
```

The first run seeds `watchlists/` from `examples/` (the public Situational
Awareness book + an index/sector Market Pulse list) so it works out of the box.

## Watchlists

Your lists live in `watchlists/*.yaml` — one file per watchlist (files starting
with `_` are ignored). **The whole directory is gitignored**: your personal
lists, positions and cost basis never end up in the repo. **Create a new list**
with `tapedeck.py --new "name"` (or copy any yaml) — it appears as a tab on the
next run. The page remembers which tab you had open.

```yaml
title: My Semis        # tab label (default: prettified filename)
order: 3               # tab position (lists without order go last, alphabetical)
benchmark: SPY         # RS reference for this list (SP500 when source is trade.xyz)
source: yahoo          # or hyperliquid — see "Price sources" below
cockpit: /path/to/COCKPIT.md   # optional: read-only status panel parsed from this markdown file
anti_basket: other-list        # optional: aggregate that list as an "anti-basket" row in the Baskets table
vwap: /path/to/vwap-latest.json   # optional: VWAP levels from a vwap-scanner --json-out feed
vwap_alert_pct: 2.0               # optional: proximity band (%) that earns an alert (default 2.0)
holdings:
  - ticker: NVDA
    name: NVIDIA       # optional display name
    group: semis       # optional tag under the ticker
    shares: 10         # optional → position columns + summary tiles
    cost_basis: 118.5  # optional → open P&L
    tv_symbol: NASDAQ:NVDA  # optional TradingView override for the chart panel
```

All lists on a source are fetched in ONE batch (union of tickers), so more lists
barely cost time. Each list keeps its own alerts, since-last-run delta,
snapshots (`output/snapshots/<list>/`), positions and benchmark.

**Create a list from the app** with **✎ Lists**, or from the terminal with
`tapedeck.py --new "name"`.

### Price sources

`source: yahoo` (the default) is the whole story for normal watchlists.
`source: hyperliquid` reads [trade.xyz](https://trade.xyz) instead — XYZ markets
on HyperCore — so a list of perps shows the marks you actually trade rather than
a spot proxy. Holdings use the venue's own symbols (`GOLD`, `COPPER`, `SKHX`,
`SPCX`), and `dex: xyz` is the default namespace.

Two honest limitations, both visible on the page as `n/a` rather than papered
over:

- **The markets are young** (listed between late 2025 and mid 2026), so 52w
  high/low, %YTD, %1Y and the 200SMA stay blank until enough history accrues.
  Bars are 24/7 and weekend bars are dropped, so the SMA windows keep their
  trading-day meaning.
- **The venue publishes no fundamentals.** Market cap, P/E, P/S, sector and
  earnings come from the TradingView screener, and only under an explicit
  `equity:` on the holding — the venue's `GOLD` is bullion while NYSE `GOLD` is
  Barrick, and its `CL` is WTI crude while NYSE `CL` is Colgate-Palmolive, so
  matching on the bare symbol would be wrong in a way that fires real alerts.

Charts show the perp itself: trade.xyz lists its markets on TradingView as
`HIP3XYZ:<SYMBOL>USDC.P`, and tapedeck derives that automatically, so no
`tv_symbol:` is needed and no delayed equity proxy stands in for the contract.

`scripts/sync_tradexyz.py --write` regenerates a watchlist of every live market
from the venue's API, and reports what has been listed or delisted since.

## What's on the page

- **Cockpit** (only with `cockpit:`) — read-only panel parsed from an external
  markdown status file: regime/freeze chips, monitored legs, open decisions and
  a sleeve table. The file is never written to; if it's missing or its format
  drifts, the panel degrades to omission and the run continues.
- **VWAP** (only with `vwap:`) — VWAP and VWAP-adjacent levels from a
  [vwap-scanner](../vwap-scanner) run: rolling and anchored VWAP lines,
  ATH/ATL-anchored VWAPs, and static fib retracement/extension projections
  (on a live scan, roughly a third fib and 15% ATH/ATL-anchored — not a
  minor case). Proximity alerts (`kind: "vwap"` in the Alerts panel and in
  the `output/tapedeck-latest.json` feed), four columns behind the VWAP
  toggle (the level-name column isn't sortable — it mixes numeric-prefixed
  names like "1M Rolling" with non-numeric ones like "Fib 0.618"), a green
  edge on rows in range (heat-scaled to the list's own `vwap_alert_pct`),
  and a full levels ladder in the expanded row. A fib level's alert/ladder
  text never carries a trailing "VWAP" — a fib projection isn't a VWAP line.
  Distances are recomputed against the live price on every run, so an
  overnight scan stays accurate through the day; the `direction` column is
  dated to the scan. Refresh the feed with
  `vwap-scanner --universe-from output/tapedeck-latest.json --json-out output/vwap-latest.json`.
- **Baskets** (with 2+ `group:` tags, or `anti_basket:`) — one aggregate row per
  group: avg %1D, median RS 1M/3M, breadth above 50SMA, median Δ52w-high; the
  `anti_basket:` list appears as a bottom comparison row (`anti-basket` is a
  reserved group name).
- **Alerts** — new 52w high/low, 20/50/200 SMA crosses (vs yesterday), gaps ≥5%,
  earnings ≤7 days, plus VWAP proximity (`kind: "vwap"`) when `vwap:` is set —
  on a live watchlist this can be roughly half of all alerts, so a downstream
  consumer of `output/tapedeck-latest.json`'s `alerts` array should expect it.
  One row per ticker, busiest names first, so a name's VWAP chip sits with its
  SMA ones; chips print a short label and carry the full sentence on hover. The
  grouping is a render-time view — the feed's `alerts` array stays flat and in
  watchlist order
- **Since last run** — price moves, SMA state flips, added/removed tickers vs the previous snapshot (`output/snapshots/`)
- **Table (Core)** — price, %1D and %YTD heat, market cap, P/S (amber heat) / P/E, 1Y sparkline, Δ 52w-high drawdown bar, RS-vs-benchmark 1M mini bars + cross-sectional rank, SMA arrows
- **Extended toggle** — RS 1M/3M %, % distance to each SMA, relative volume, ATR%, next earnings, sector
- **Positions toggle** — appears when any holding has `shares`
- **Click any row** — expands live TradingView charts for that ticker: 12H / 4H / 1H
  candles (Berlin time). Charts load on demand from TradingView's CDN, so this is
  the one feature that needs internet; the rest of the page works offline.
  Symbols are auto-mapped (NASDAQ/NYSE/AMEX) from Yahoo's exchange code —
  override per ticker with `tv_symbol:` in the watchlist yaml if one resolves wrong.
- Click any column header to sort. Hover cells for detail. Theme: auto/light/dark
  (open charts rebuild to match the theme).

## Data sources

- **Snapshot fields** (price, %1D, market cap, P/S, P/E, %YTD, Δ52w-high, RVol,
  ATR%, sector, earnings date, TV symbol): **TradingView screener** — the public
  endpoint behind tradingview.com's stock screener. One POST for all tickers,
  matches the numbers you see on TradingView. Unofficial/undocumented endpoint:
  if it ever breaks, the run automatically falls back to Yahoo fundamentals
  (or force that with `--source yahoo`).
- **Historical series** (sparklines, SMA states + crosses, RS bars/rank,
  gap/52w-extreme alerts, snapshots): Yahoo Finance via `yfinance` — 1y daily
  OHLCV, one batch download. TradingView doesn't expose history without
  login-based hacks, so this stays on Yahoo.
- **Chart panels:** TradingView's free Advanced Chart embed (live/delayed per
  TradingView's exchange rules).
- Free, no API keys anywhere.

## Conventions

- YTD is vs the prior year's last close. 1D is last close vs previous close
  (pre-market runs show yesterday's session).
- RS = ticker return minus benchmark return over 21/63 sessions, in percentage points.
- Prices are Yahoo Finance daily closes, dividend/split-adjusted.

## Known data quirks (sources, not bugs)

- ETFs (SMH) have no fundamentals → n/a.
- Fresh listings show n/a for 200SMA until enough history exists.
- Micro-cap valuation ratios can be wild on any source (TV showed WYFI P/S >1000).
- With the TV source, price/%1D update intraday while sparklines/SMAs are daily
  closes — during a session the arrow states lag the live price by design.

## Layout

`tapedeck.py` (CLI) → `tapedeck/fetch.py` (all network) → `tapedeck/pipeline.py` +
`tapedeck/metrics.py` (pure computation) → `tapedeck/alerts.py` / `tapedeck/snapshot.py` /
`tapedeck/vaultlink.py` (read-only external status file) / `tapedeck/vwaplink.py`
(read-only vwap-scanner feed) → `tapedeck/render.py`
(self-contained HTML) + `tapedeck/feed.py` (JSON feed).

The app sits alongside that, not inside it: `tapedeck/server.py` serves the
already-rendered HTML with `tapedeck/appshell.js` injected, and runs refreshes
through `tapedeck/jobs.py` as subprocesses — so the buttons run exactly the
commands you'd run by hand, and the render path above is untouched.
`native/` is the Swift shell around it.

Tests: `.venv/bin/python3 -m pytest tests/`.
