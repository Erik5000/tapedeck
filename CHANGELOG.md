# TAPEDECK Changelog

## 2026-07-31 — Renamed BLOOM → TAPEDECK
- GitHub repo renamed to `Erik5000/tapedeck` (old `bloom` URL redirects);
  package `bloom/` → `tapedeck/`, CLI `tapedeck.py`, all branding, favicon 📼,
  output files now `output/tapedeck-DATE.html`.
- Historical entries below keep their original text with paths updated.

## 2026-07-31 — Public repo prep + --new scaffold
- `--new "name"` scaffolds a ready-to-edit watchlist yaml
  (`config.new_watchlist`); first run auto-seeds `watchlists/` from the
  committed `examples/` (`config.seed_watchlists`). 4 new tests (72 total).
- Privacy hardening for open-sourcing: `watchlists/` (personal lists +
  positions) and `output/` (snapshots) fully gitignored; the two public example
  lists moved to `examples/`; reference image excluded (attribution link in
  README instead). MIT LICENSE added.
- WHY: publish the tool publicly without ever risking personal watchlists or
  position data in git.

## 2026-07-31 — Multiple watchlists with in-page tabs
- `watchlists/*.yaml` — each file is one watchlist (`title:`, `order:`,
  `benchmark:`, `holdings:`); `portfolio.yaml` migrated to
  `watchlists/situational-awareness.yaml`, starter `market-pulse.yaml` added.
- One run fetches the union of all tickers in a single TV-scan + single Yahoo
  batch, then renders one HTML page with a tab per list; last-viewed tab is
  remembered. Per-list alerts, delta panels, snapshots
  (`output/snapshots/<list>/`), positions and benchmarks.
- `--list name[,name]` runs a subset; `--config file.yaml` still renders a
  single file. `render.render_multi()` supersedes single-list `render_page()`
  (kept as wrapper). Sorting/toggles/chart-expansion rescoped per table.
- 5 new tests (68 total).
- WHY: Erik wants his own lists beyond the public Situational Awareness book,
  and to browse them without re-running anything.

## 2026-07-31 — TradingView screener as primary snapshot source
- New `tapedeck/tvscan.py`: one POST to TradingView's public screener endpoint
  fetches price, %1D, market cap, P/S, P/E, %YTD, 52w high, RVol, ATR, sector,
  earnings date and the TV chart symbol for all tickers at once.
- `pipeline.build_rows(tv=...)` merges screener values over Yahoo ones
  (config `name:`/`tv_symbol:` still win); history-derived series (sparklines,
  SMA states/crosses, RS, snapshots) stay Yahoo-based.
- Yahoo `.info` calls now run only for tickers the screener missed → run is
  ~10s faster; automatic full fallback to Yahoo if the endpoint fails, or
  `--source yahoo` to force it. 7 new tests (63 total).
- WHY: numbers now match what Erik sees on TradingView (the reference image's
  YTD column now matches digit-for-digit), fixes Yahoo's TSM P/S + SMH gaps.

## 2026-07-31 — TradingView chart expansion
- Every table row is now clickable: expands an inline panel with three live
  TradingView Advanced Chart widgets — 12H / 4H / 1H candles, Europe/Berlin
  timezone, theme-matched (open charts rebuild on theme toggle).
- Charts lazy-load from TradingView's CDN on first expand only; the rest of the
  dashboard stays self-contained/offline-capable. Sorting keeps each detail row
  glued to its ticker row.
- TV symbols auto-derived from Yahoo exchange codes (NMS→NASDAQ, NYQ→NYSE,
  PCX→AMEX, …) in `tapedeck/pipeline.py:tv_symbol`; per-ticker `tv_symbol:`
  override supported in `portfolio.yaml`. 4 new tests (56 total).
- WHY: Erik wants to jump from the scan table straight into his execution
  timeframes without leaving the page.

## 2026-07-31 — Initial build
- Built the full tool from scratch: `tapedeck.py` CLI + `tapedeck/` package
  (`config`, `fetch`, `metrics`, `pipeline`, `alerts`, `snapshot`, `render`),
  `portfolio.yaml` pre-filled with the 25 tickers from the reference image
  (`input/Situational Awareness Holdings.jpeg`).
- One command fetches 1y daily history + fundamentals via yfinance (no API key)
  and writes a self-contained interactive HTML dashboard to `output/`:
  heat columns (%1D, %YTD, P/S), 1Y sparklines, Δ52w-high drawdown bars,
  RS-vs-SPY mini bars + rank, SMA arrows, sortable columns, Extended/Positions
  column sets, light/dark theme.
- Additions beyond the reference: alerts panel (52w extremes, SMA crosses,
  gaps ≥5%, earnings ≤7d), run-over-run delta via JSON snapshots
  (`output/snapshots/`), optional position tracking (shares/cost_basis in
  config → P&L columns + summary tiles), `--png` export (headless Chrome),
  `--json` output for future morning-stack integration.
- 52 pytest tests over the pure modules (metrics/alerts/snapshot/config/
  pipeline/render). Chart palette validated with the dataviz checker in both
  modes (green/red = status pair, sign always printed; amber valuation heat).
- WHY: turn the static X screenshot into a daily refreshable tool.
