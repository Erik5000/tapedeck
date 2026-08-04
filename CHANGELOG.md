# TAPEDECK Changelog

## 2026-08-04 — TAPEDECK.app: a real macOS app

- **`native/` — a SwiftUI + WKWebView app** installed to `~/Applications` with
  `cd native && make install`. Its own Dock icon and window; opening it starts
  the local server, quitting it stops the server. Follows the convention
  already used by the sibling apps (`fundamental-terminals`, `trading-prep`,
  `tt`): XcodeGen project, repo path baked into `Info.plist` at build time,
  ad-hoc signed so macOS keeps the app's identity across rebuilds.
- **`tapedeck/server.py` — a local HTTP server** (stdlib only, no new
  dependency) serving the newest `output/tapedeck-DATE.html` at
  `http://127.0.0.1:7360/` with a small app shell injected before `</body>`.
  Also available without the app: `tapedeck.py --serve`.
- **Two buttons in the dashboard's own controls row**, styled by the page's
  existing CSS: `⟳ Refresh` re-runs `tapedeck.py` (~20s) and `◇ Rescan VWAP`
  re-runs `vwap-scanner` (~8 min cold). Both stream the run's stderr into a
  live status line and reload the page when it lands. One job at a time — a
  second click gets a 409 rather than a second scan.
- **The shutdown guarantee has two independent paths**, because ⌘Q alone
  doesn't cover force-quit: the clean path is SIGTERM→SIGKILL from
  `applicationWillTerminate`, and the backstop is the server's own kqueue
  watchdog on `--parent-pid`, which fires on `kill -9` and crashes alike
  (measured: server gone ~1s after the app is killed). SIGTERM in the server
  also terminates any running job, so quitting mid-scan doesn't orphan an
  8-minute fetch.
- **The app only ever stops a server it started.** One already serving this
  repo — `tapedeck.py --serve` in a terminal — is adopted, not double-spawned,
  and left running when the app quits.
- Both POST routes run local commands, so requests are refused unless the peer
  address is loopback (unspoofable) *and* the `Host` header is pinned to
  `127.0.0.1`/`localhost` (the DNS-rebinding half). Neither check alone covers
  both attacks.
- Note: the app serves over `http://127.0.0.1` where the file was previously
  opened over `file://`. `localStorage` is origin-scoped, so the remembered tab
  and theme reset once, on first launch.
- 50 new tests (199 → 249): job-runner state machine, server routes against a
  real socket, both watchdog paths, and the `--serve` wiring. The Swift shell
  has no test target, matching the sibling apps; its lifecycle was verified by
  hand (clean quit, force-quit, adoption, both buttons end to end).

## 2026-08-04 — VWAP levels integration
- New optional watchlist keys `vwap: /path/to/vwap-latest.json` +
  `vwap_alert_pct` (default 2.0) — attaches VWAP and VWAP-adjacent levels
  (rolling, anchored, ATH/anchored, ATL-anchored, and static fib
  retracement/extension projections) from a [vwap-scanner](../vwap-scanner)
  `--json-out` feed (schema 1), read by new `tapedeck/vwaplink.py`. On a
  live 64-ticker/893-level scan the mix is roughly 36% fib and 15%
  ATH/ATL-anchored, so the fib/anchored kinds are not a minor case — a fib
  level is labeled distinctly from a true VWAP line (see the "fib
  mislabeling" fix below). Strictly read-only, same degrade-never-raise
  contract as `vaultlink.py`: a missing/malformed feed omits the levels with
  a single stderr warning and the run continues.
- Four new surfaces, all gated on `vwap:` being set (invisible otherwise):
  a `VWAP` freshness chip showing the feed date, proximity entries in the
  Alerts panel, four sortable columns behind a new VWAP toggle, a green left
  edge on rows within the alert band, and a full levels ladder in the
  expanded row with in-range levels highlighted.
- Per-level distances (`pct_distance`, `z_stretch`, `in_range`) are
  recomputed locally against tapedeck's live price on every run, so a
  feed generated the night before stays accurate through the session;
  `direction` is carried verbatim from the scan, since it's a bar-over-bar
  classification tapedeck has no basis to recompute, and the ladder marks it
  "(at scan)".
- Live end-to-end verified against a real Twelve Data-backed scan (66
  tickers, ~5.5 min cold) — confirmed the schema-1 JSON contract shape and
  all four surfaces on a real watchlist, plus graceful degradation with the
  feed file removed.
- New tests across this integration (initial build + the direction-vocabulary
  fix + this final fix wave): 199 total (up from 97 before it started).
- WHY: the FMFB book's thesis legs already live in tapedeck; VWAP proximity
  is a mean-reversion signal worth seeing on the same page as price, RS and
  the cockpit, without turning tapedeck into a second scanner.

## 2026-08-04 — VWAP integration final fix wave
- Fib levels were being suffixed " VWAP" in the proximity alert text (e.g.
  "0.4% above Fib 0.786 VWAP") — a fib retracement/extension is a static
  price projection, not a VWAP line. `alerts.py` now only appends " VWAP"
  when the level's `kind` isn't `fib`; a missing level `name` now renders
  `n/a` instead of the literal string `None`.
- The levels ladder was leaking the raw `kind` enum value verbatim
  (`ath_anchored`, `atl_anchored`) into the page. `render.py` now has a
  small display map (`ath_anchored` → "ATH-anchored", etc.) with a
  pass-through fallback, so an unrecognised future `kind` still displays
  rather than blanking.
- The proximity heat scale (`vwap_dist` column, the green background tint)
  used a fixed cap of 5.0 regardless of the list's own `vwap_alert_pct`
  (default 2.0) — the in-range band that heat is supposed to represent — so
  the strongest possible hit only ever reached ~55% intensity. The cap is
  now the list's own `vwap_alert_pct`.
- The VWAP-level column header sorted with `parseFloat`, so numeric-prefixed
  names ("1M Rolling") and non-numeric ones ("Fib 0.618") interleaved
  meaninglessly. That column is now marked non-sortable.
- The canonical `direction`/`kind` vocabularies (verified against a live
  vwap-scanner feed: `direction` ∈ {support, resistance, reclaim, reject,
  na}; `kind` ∈ {fib, rolling, anchored, atl_anchored, ath_anchored}) now
  live once in `tapedeck/vwaplink.py`; `alerts.py` and `render.py` import
  them and assert their own presentation maps are a subset, so a vocabulary
  drift fails a test instead of silently blanking a surface.
- Dead code: `vwaplink.DEFAULT_ALERT_PCT` (referenced nowhere — `config.py`
  is the single source of the 2.0 default) removed.
- `output/tapedeck-latest.json` — the stable feed contract external
  consumers (e.g. a morning-brief pipeline) read — now includes `kind:
  "vwap"` alerts (from `build_vwap_alerts`) alongside the existing alert
  kinds. On a live watchlist this was 16 of 31 alerts for one list, roughly
  doubling alert volume; a consumer parsing `alerts` by `kind` should expect
  it.
- 9 new tests (199 total) covering the above plus a `sigma == 0` → `None`
  z-stretch regression (reachable for sub-dollar names) and corrected
  `test_vwaplink.py`/`test_tapedeck_cli.py` fixtures — these previously
  hand-invented `direction: "above"` (never produced by the scanner),
  `score: 0.72` (the real contract is 0-100), and a flat `regime_er` key
  (the real shape nests `features.regime.{er,trend_up,label}`). Fixture
  values are now taken verbatim from a real 64-ticker/893-level scan.
- WHY: a whole-branch review found the plan's fixtures had invented feed
  vocabulary the live scanner never produces — the same class of bug already
  caught once for `direction` was still live for `score`/`features`, plus a
  handful of smaller display/consistency issues.

## 2026-07-31 — Cockpit panel, basket monitor, stable JSON feed
- New optional watchlist key `cockpit: /path/to/COCKPIT.md` — renders a
  read-only status panel (regime/freeze chips, triad legs, open decisions,
  sleeve mini-table) parsed each run from an external markdown file by new
  `tapedeck/vaultlink.py`. Strictly read-only: the app never writes to the
  file; missing/drifted files degrade to omission with a stderr warning.
- New optional key `anti_basket: other-list` + per-group aggregates
  (`metrics.basket_aggregate` / `group_aggregates`) — a Baskets mini-table
  per list: one row per `group:` (avg %1D, median RS 1M/3M, breadth >50SMA,
  median Δ52w-high) plus the named sibling watchlist as a synthetic
  `anti-basket` comparison row (that group name is reserved).
- Every run now writes `output/tapedeck-latest.json` (stable path, gitignored)
  with rows + baskets + cockpit state for external consumers; `--json` prints
  the same feed. New `tapedeck/feed.py` absorbs the old `slim_json`.
- 25 new tests (97 total).
- WHY: lets an external research pipeline and the dashboard read the same
  state — market truth flows out via the feed, externally-managed cockpit
  state flows in via the read-only panel.

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
