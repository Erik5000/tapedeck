# VWAP scanner integration — design

Date: 2026-08-03
Repos: `tapedeck` (primary), `vwap-scanner` (sibling, two new flags)

## Problem

The TradingView chart panels in tapedeck show price action but no levels. The
sibling `vwap-scanner` project already computes a rich set of VWAP levels
(rolling 12M/6M/3M/1M, anchored decade/yearly/quarterly/monthly, ATH- and
ATL-anchored, fib), per-symbol features (volume z-score, Kaufman efficiency
ratio) and a composite setup score — but its output never reaches the
dashboard where the watchlists actually live.

## Constraint: this cannot go on the TradingView panels

TradingView's free embed widget has no drawing API — custom horizontal lines
cannot be injected — and its built-in `VWAP` study is session-anchored, which
is not the same object as a 12M-rolling or decade-anchored VWAP. Pine Script is
unsupported in every embeddable TradingView product, including the licensed
Charting Library.

Therefore VWAP levels render in tapedeck's own UI. The TradingView panels are
unchanged by this work.

## Architecture

Two loose-coupled CLIs with JSON in both directions. This mirrors the pattern
already established in tapedeck: market truth flows out via `feed.py`,
externally-managed state flows in read-only via `vaultlink.py`.

```
tapedeck.py ──► output/tapedeck-latest.json ──► vwap-scanner --universe-from
                                                       │
tapedeck.py ◄── vwaplink.py ◄── vwap-latest.json ◄─────┘   (--json-out)
```

Neither repo imports the other. The scanner keeps its own data source
(Twelve Data, ~20y history, split-only adjustment matching TradingView's
default chart mode), so decade anchors and ATH/ATL-anchored levels remain
computable — they would not be if tapedeck computed levels itself from its
1-year dividend-adjusted Yahoo pull.

### Trigger

Manual two-step. The user runs `vwap-scanner` when fresh levels are wanted;
tapedeck reads whatever `vwap-latest.json` is present and stamps its age.
tapedeck never shells out to the scanner, never blocks on a rate-limited scan,
and never writes to the scanner's files.

## Changes: vwap-scanner

Two new flags. No existing behaviour changes.

- `--universe-from PATH` — take the ticker list from a tapedeck feed rather
  than building the S&P 500 + NDX universe. This is what causes watchlist
  names outside the index universe (IREN, WYFI, CRDO) to be scanned at all.
  The tapedeck feed carries `tv_symbol` per row, so exchange resolution comes
  from the file rather than the exchange map.
- `--json-out PATH` — write the structured contract below, alongside the
  existing `.txt` report output.

## Contract: vwap-latest.json

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

`threshold_pct` records the proximity band the scan was built at, so tapedeck
knows what is and is not present in the file.

### Distances are recomputed locally

The contract stores level **values**. tapedeck recomputes `pct_distance`,
`in_range` and `z_stretch` against its own live price on every run, and drops
the scanner's `pct_distance` on read.

Rationale: VWAP levels move slowly, price moves every tick. Recomputing keeps
a scan from last night useful all through today, and guarantees the distances
on the page agree with the price rendered beside them.

This is basis-consistent. Dividend adjustment shifts historical bars, not
today's print, so tapedeck's live TradingView-screener price compares
correctly against a split-adjusted VWAP level.

`direction` (reclaim / reject / above / below) is **not** recomputed — it is a
bar-over-bar classification the scanner derives from its own prior close, and
tapedeck has no equivalent basis for it. It therefore ages with the feed:
where a recomputed distance is always current, a displayed direction describes
the scan date. The ladder labels it accordingly.

## Changes: tapedeck

### `tapedeck/vwaplink.py` (new)

A direct sibling of `vaultlink.py`. Strictly read-only: the only filesystem
access is a single `Path(path).read_text()`. Any failure — missing file,
malformed JSON, unknown `schema` — degrades to `None` with a stderr warning
and the run continues.

Responsibilities: read, validate schema, compute feed age, recompute
per-ticker distances against live prices.

### `tapedeck/config.py`

New optional per-watchlist keys, parsed exactly as `cockpit:` is today:

- `vwap: /path/to/vwap-latest.json` — enables the feature for that list.
- `vwap_alert_pct: 2.0` — proximity band that earns an Alerts entry.

Per-list rather than global so Market Pulse can stay clean while FMFB Book and
Situational Awareness use it.

### Staleness

`vwaplink` stamps the feed's age; tapedeck renders it as a chip. Age is
measured in **calendar days** from `generated` — no market-calendar dependency
is introduced for a cosmetic threshold. Beyond that threshold (default 7 days)
levels render dimmed but remain visible — a
two-week-old 12M VWAP is still approximately right, and hiding it silently is
worse than showing it greyed.

## UI surfaces

Four surfaces, all reading one `vwaplink` payload.

1. **Alerts** — in-range hits join the existing Alerts block:
   `CRDO — 1.2% below 6M VWAP · reclaiming`. Gated at `vwap_alert_pct`
   (default 2.0), not at the scan's 5% threshold: 5% across 59 names would
   drown the section. The full 5% set still populates columns and ladder.
2. **New "VWAP" toggle**, alongside Extended and Positions. Columns: nearest
   level name, signed %distance with heat, z-stretch, score — all sortable, so
   the book can be ranked by setup quality. Kept out of Extended, which is
   already seven columns and would show empty cells for lists with no `vwap:`.
3. **Levels ladder in the expanded row**, above the TradingView charts: every
   level for that ticker sorted by |distance| — name, kind, value, %distance,
   direction, σ-stretch — in-range rows highlighted.
4. **Row marker** on the main row when a ticker is in-range of any level, so
   candidates surface while scanning with the toggle off.

### Degradation

A ticker absent from the feed — not covered by the scan, or added to the
watchlist afterwards — gets blank cells, no marker and no alert. Never a zero
or an `n/a` that could be misread as a real reading.

## Out of scope

VWAP aggregates in the Baskets table. A separate feature; revisit after this
one has been used.

## Testing

Mirrors the existing suite's approach.

- `tests/test_vwaplink.py` (new) — parse, missing file, malformed JSON, schema
  mismatch, staleness thresholds, and the local distance-recompute math.
- `tests/test_render.py` — one addition per surface, including the
  absent-ticker degradation path.
- `tests/test_config.py` — the two new keys, including absence.
- vwap-scanner side — `--universe-from` (including tickers outside the index
  universe) and `--json-out` contract shape.
