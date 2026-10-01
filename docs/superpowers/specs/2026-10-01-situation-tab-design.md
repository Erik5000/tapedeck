# Situation tab: bonds and oil — design

Date: 2026-10-01
Repo: `tapedeck` (branch `situation-tab`, from `page-and-sources`)
Scope: Parts 1 and 3 of 4 (rates base + regime read, oil link). Part 2 (stress
alarm) and Part 4 (rates for my trades) get their own specs later.

## Problem

Tapedeck shows watchlists. Nothing on the page reads bonds as bonds, and
nothing links the oil move to the rates move. Today Brent is near $100, the
10Y is near 5.3% and rate volatility is high. The user wants one glance view
that answers four questions:

1. Which regime are rates in, and what drives the move?
2. Do bonds price the oil move, or do they ignore it?
3. Is an oil rally physical demand, or leveraged perp longs?
4. Is one side of duration crowded?

## The method: from oil-tracker

The paused `oil-tracker` project gives the method. This design copies the
method, not the code or the database:

- A small set of **legs**. Each leg has a fixed, documented "higher means"
  direction. A test fixes each direction (`oil-tracker` brief §2.1).
- **z-scores over 252 trading days** on stored level series (§2.2).
- **Suppress, never fake.** A leg without enough history shows "warming up
  (n/N)". A leg without data shows "no data" and the reason. It never shows a
  default number (§2.3, §2.4).
- **Confidence is a separate number** from the reading (§8).

`financial-models/risk_appetite` gives one lesson: credit, curve and bond
volatility have no stable edge as a direction signal. This tab is a monitor
and an alarm. It does not forecast.

## Data sources

No Yahoo. No API key. No sign-up.

- **V — trade.xyz / HyperCore** (`https://api.hyperliquid.xyz/info`). The live
  source for every market it lists: daily candles, mark, oracle, funding,
  open interest (OI), 24h volume, and hourly funding history.
- **F — FRED CSV** (`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`).
  The Fed's public file, with no key. Used only for series that no venue lists,
  and for older history.

### Venue markets (checked 2026-10-01)

| Market | First bar | 24h volume | Price unit |
|---|---|---|---|
| `para:2Y` | 2026-09-24 | $0.30M | yield, % |
| `para:10Y` | 2026-08-12 | $0.76M | yield, % |
| `para:30Y` | 2026-09-24 | $0.02M | yield, % |
| `mkts:USBOND` | 2026-08-26 | $4.2M | bond price |
| `xyz:TLT` | 2026-09-17 | $2.6M | ETF price |
| `xyz:BRENTOIL` | 2026-03-04 | ~$160M | $/bbl, front futures |
| `xyz:CL` | 2026-01-06 | ~$150M | $/bbl, front futures |

A long position in a **yield** perp (`para:*`) gains when yields rise. That is
a **short duration** position. A long position in `USBOND` or `TLT` is a
**long duration** position. The crowding leg reports every market in duration
terms, so the two kinds read the same way.

### FRED series

| ID | Meaning | Stale after |
|---|---|---|
| `DGS2`, `DGS10`, `DGS30` | Treasury yields, history for the venue yields | 4 days |
| `T10YIE`, `T5YIE` | 10Y and 5Y breakeven inflation | 4 days |
| `T5YIFR` | 5y5y forward inflation expectation | 4 days |
| `DFII10` | 10Y real yield (TIPS) | 4 days |
| `THREEFYTP10` | 10Y term premium (Kim-Wright) | 10 days |
| `BAMLH0A0HYM2` | US high-yield spread | 4 days |
| `DCOILBRENTEU` | Brent spot, history for the Brent perp | 4 days |

"Stale after" counts calendar days from the last observation to today.
`THREEFYTP10` publishes about one week late, so it has a longer limit.

## History join rules

The venue markets are young. The z-scores need 252 trading days. FRED supplies
the older history under two rules.

**Yields (`DGS2/10/30` + `para:2Y/10Y/30Y`): join on levels, with a check.**
Both are yields in percent. Take the days where both have a value. If there
are at least 5 such days and the mean absolute difference is 5 bp or less,
the joined series is FRED before the first venue day and the venue from that
day. If not, the z-score uses FRED only, the row shows the venue level as the
live value, and the row says "venue ≠ FRED, not joined".

**Brent (`DCOILBRENTEU` + `xyz:BRENTOIL`): join on daily % returns, never on
levels.** The perp is a futures price and FRED is spot. The two levels differ
by the curve spread, so a level join would put a false jump in the series.
The joined series is a return series. The row shows the perp level.

Venue bars on Saturday and Sunday are dropped, as `hlfetch` already does. A
z-score window is 252 weekday bars.

## Legs

All z-scores: 252-bar window. A leg needs at least 252 bars, or it shows
"warming up (n/252)". The exceptions are stated in the row.

### Panel A: Rates regime

| Leg | Value | z on | Higher means |
|---|---|---|---|
| `y2`, `y10`, `y30` | joined yield, % | level | higher yield |
| `curve_2s10s` | y10 − y2, bp | level | steeper |
| `curve_10s30s` | y30 − y10, bp | level | steeper |
| `be10` | `T10YIE`, % | level | more priced inflation |
| `be5y5y` | `T5YIFR`, % | level | more priced long-run inflation |
| `real10` | `DFII10`, % | level | tighter money |
| `term_premium` | `THREEFYTP10`, % | level | more pay for duration risk |
| `rate_vol` | stdev of daily Δy10 over 20 bars, bp/day × √252 | level | more rate volatility |
| `credit` | `BAMLH0A0HYM2`, % | level | more credit stress |
| `bond_crowding` | see Crowding | — | — |

Each row shows: value, 20-bar change, z, state word, source tag (V, F or
V+F), data age.

**State word** from |z|: under 1 = `normal`; 1 to 2 = `high` or `low`; over
2 = `extreme high` or `extreme low`.

### The regime label

FRED defines `T10YIE` as `DGS10 − DFII10`. So over 20 bars:

```
Δ10Y nominal = Δ breakeven + Δ real yield
```

The label uses FRED for all three numbers, so the sum is exact. It is dated
with the FRED date.

| Condition | Label |
|---|---|
| \|Δ10Y\| < 10 bp | `Range-bound` |
| Δ10Y ≥ +10 bp and Δbreakeven > Δreal | `Inflation-led sell-off` |
| Δ10Y ≥ +10 bp and Δreal ≥ Δbreakeven | `Real-rate-led sell-off` |
| Δ10Y ≤ −10 bp and Δreal < Δbreakeven | `Growth-scare rally` |
| Δ10Y ≤ −10 bp and Δbreakeven ≤ Δreal | `Disinflation rally` |

The label line also shows the split, for example
`10Y +31bp/20d = real +24 · BE +7`.

### Panel B: Oil ↔ Rates

| Leg | Value | z on | Higher means |
|---|---|---|---|
| `brent` | `xyz:BRENTOIL` level; 20-bar % return | 20-bar return (joined returns) | stronger oil rally |
| `wti` | `xyz:CL` level; 20-bar % return | 20-bar return, venue only | stronger oil rally |
| `brent_wti` | BRENTOIL − CL, $/bbl | level, venue only | wider Brent premium |
| `be_beta` | 60-bar OLS beta of daily Δ`T5YIE` (bp) on daily Brent % return | — | more pass-through |
| `be_gap` | 20-bar Δ`T5YIE` − beta × 20-bar Brent return, bp. Each day uses the beta of that day. | gap / stdev of the gap series over 252 bars | breakevens ahead of oil |
| `oil_crowding` | see Crowding | — | — |

`wti` and `brent_wti` have venue history only (from 2026-01-06). Until they
have 252 bars, they show the value and the 20-bar change, and the z says
"warming up (n/252)".

### Crowding

For `xyz:BRENTOIL`, `xyz:CL`, `para:10Y`, `mkts:USBOND` and `xyz:TLT`:

| Field | Definition |
|---|---|
| `funding_ann` | mean hourly funding over the last 7 days × 24 × 365, % |
| `funding_z` | z of daily mean funding over the fetched 180 days (less if the market is younger); needs at least 60 days |
| `oi` | current OI, from the venue context |
| `oi_chg_20d` | % change of OI against the stored value 20 days back |
| `duration_side` | for rates markets: which side of duration pays funding (`long duration crowded` / `short duration crowded`) |

The venue gives no OI history. Each run writes one line per day to
`output/situation-history.jsonl` with the date and the OI per market. A second
run on the same day replaces that day's line. `oi_chg_20d` shows "warming up
(n/20 days)" until a line from 20 days back exists.

## Alerts

Thresholds are named constants in `situation/alerts.py`.

| Alert | Fires when | Needs |
|---|---|---|
| **Bonds ignore oil** | `brent` z > +1 and `be_gap` z < −1 | FRED + venue; works on day 1 |
| **Inflation scare without oil** | `be10` 20-bar change z > +1 and Brent 20-bar return ≤ 0 | FRED + venue; works on day 1 |
| **Leveraged oil rally** | `brent` z > +1 and BRENTOIL `funding_z` > +1 and `oi_chg_20d` > +10% | OI history |
| **Crowded duration** | \|`funding_z`\| > 2 on `para:10Y` or `mkts:USBOND`, and that market's `oi_chg_20d` > +10% | OI history |

The `be10` 20-bar change z is the z of the 20-bar change series over 252 bars.

An alert whose inputs are missing or warming up is **disabled**. It shows in
grey with the reason, for example `Leveraged oil rally — needs OI history
(3/20 days)`. It never fires on part of its inputs.

*Leveraged oil rally* replaces the oil-tracker *paper-only rally*. The venue
has no oil curve (no contract months), so this alert reads perp leverage, not
backwardation. The panel says so in one line under the alert.

## Confidence

One number from 0 to 100 per panel: `round(100 × mean(leg scores))`.

| Leg condition | Score |
|---|---|
| fresh, full history | 1.0 |
| stale, or warming up | 0.5 |
| no data | 0.0 |

A leg from a venue market gets half its score if 24h volume is under $100k, or
if |mark − oracle| / oracle is over 0.5%. Today `para:30Y` is under the volume
limit.

## Page layout

Situation is the first tab. The current tab memory in `localStorage` keeps
working.

```
SITUATION                                   data 2026-10-01 · FRED to 09-30
┌ REGIME  Real-rate-led sell-off   10Y +31bp/20d = real +24 · BE +7 ┐
│ ALERTS  ● Bonds ignore oil   ○ Leveraged oil rally (OI 3/20 days)  │
│ CONF    Rates 82   Oil↔Rates 64                                    │
└────────────────────────────────────────────────────────────────────┘
┌ RATES REGIME ─────────────┐ ┌ OIL ↔ RATES ─────────────┐
│ leg  src level Δ20d z st  │ │ leg  src level Δ20d z st │
└───────────────────────────┘ └──────────────────────────┘
┌ CROWDING (venue) ──────────────────────────────────────┐
│ market  funding/yr  z  OI  OI Δ20d  side               │
└────────────────────────────────────────────────────────┘
```

- The top strip is the glance view: label and split, alerts (fired first,
  disabled in grey with the reason), and the confidence of each panel.
- The two panels use the existing panel grid. In a narrow window they stack.
- The page uses the existing color tokens and light/dark themes.

## Architecture

New package `tapedeck/situation/`. Only `sources.py` touches the network.

| File | Does |
|---|---|
| `sources.py` | Venue candles (reuses `hlfetch`), venue context per dex (`xyz`, `para`, `mkts`), funding history (paged, 180 days), FRED CSV. Parallel fetch. |
| `series.py` | The two join rules. |
| `legs.py` | The legs as data: id, value function, z basis, "higher means", minimum bars. |
| `regime.py` | The regime label. |
| `oillink.py` | `be_beta`, `be_gap`, `brent_wti`. |
| `crowding.py` | Funding, OI change, duration side; reads and writes the history file. |
| `alerts.py` | The four alerts and their thresholds. |
| `confidence.py` | Panel confidence. |
| `render.py` | HTML for the tab. |
| `__init__.py` | `build_situation(today, out_dir) -> dict`. |

### Data flow

```
tapedeck.py ── watchlists (as today)
     └─ build_situation(today, out_dir)
          sources ─► series ─► legs / regime / oillink / crowding
                                   └─► alerts ─► confidence ─► dict
     ├─ render.render_multi(lists, ..., situation=dict)  → Situation tab first
     ├─ output/situation-latest.json   (schema 1)
     └─ output/situation-history.jsonl (one line per day, OI)
```

- `tapedeck.py` calls `build_situation()` on every run. `--no-situation` skips
  it. **⟳ Refresh** in the app runs `tapedeck.py`, so it updates the tab with
  no server change.
- `render_multi()` takes `situation=None`. With `None`, the page is as today.
- `situation-latest.json` has `schema: 1`, `date`, `regime`, `alerts`,
  `confidence`, `legs`, `crowding`. New keys may be added later. Existing keys
  never change meaning, the same rule as `feed.py`.

### Errors

- Each source fails alone. A failed fetch gives "no data" and the reason for
  the legs that need it, and a warning on stderr. The run continues, as with
  `vwaplink`.
- If `build_situation()` itself raises, `tapedeck.py` prints the error, the
  page renders without the tab, and the run continues.
- Non-finite and boolean values from either source are refused, with the same
  guard as `vwaplink._finite_number`.

## Tests

pytest with fixed data. No test touches the network.

- **Join rules:** a join under 5 bp; a refusal over 5 bp; a refusal with fewer
  than 5 shared days; Brent joined on returns, with no jump at the join.
- **Regime:** all five labels, plus the edges at exactly ±10 bp and
  Δbreakeven = Δreal.
- **Directions:** one test per leg fixes its "higher means" direction.
- **Duration side:** a long-funded `para:10Y` reads short duration crowded; a
  long-funded `USBOND` reads long duration crowded.
- **Alerts:** for each alert, one fixture that fires it, one that does not,
  and one with a missing input that disables it.
- **Suppression:** "warming up" and "no data" render as text, never as a
  number.
- **History file:** a second run on the same day replaces the line; a gap in
  days does not break `oi_chg_20d`.
- **Render:** the tab HTML contains the label, the alert states and the
  confidence; `situation=None` gives the page as today.
- **Failure:** a source that raises gives "no data" legs and the run
  completes.

## Out of scope

- Part 2, the stress alarm (speed of the long-end move, a stress score).
- Part 4, the rate sensitivity of each watchlist holding.
- An oil curve leg (M1−M2). The venue lists no contract months. It can come
  back if `oil-tracker` runs on real data and exports a feed.
- Push notifications for alerts.
- Intraday updates. The tab updates on each run.
