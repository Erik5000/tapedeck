#!/usr/bin/env python3
"""Regenerate watchlists/tradexyz-universe.yaml from the live trade.xyz market list.

The venue lists and delists: 17 of its 105 markets are already gone. A
hand-written universe file rots, so this reads the current set from the
Hyperliquid `xyz` dex and reports the drift.

    scripts/sync_tradexyz.py            # report only
    scripts/sync_tradexyz.py --write    # rewrite the watchlist

Names and groups come from CATALOG below, transcribed from trade.xyz's own
specification index (docs.trade.xyz/consolidated-resources/specification-index).
A market the API reports but CATALOG doesn't know is still written out — under
`group: unclassified`, with a warning — because dropping a tradable market
silently is worse than one row with a bare ticker.

Note the venue's API symbols differ from its docs in three places: the docs say
SKHYNIX / SAMSUNG / WTIOIL where the API says SKHX / SMSN / CL. The API wins —
it's what candleSnapshot answers to.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tapedeck import hlfetch  # noqa: E402

# symbol -> (display name, group, Yahoo reference symbol or None)
#
# The third field names a Yahoo-resolvable instrument for the same underlying.
# It supplies the fundamentals a US-only screener has nothing for (285A.T for
# KIOXIA, 005930.KS for SMSN) and the year-scale history these young markets
# cannot have (GC=F for GOLD, ^GSPC for SP500).
#
# It is never the bare venue symbol by coincidence: NYSE GOLD is Barrick, not
# bullion, and NYSE CL is Colgate-Palmolive, not WTI crude. None means nothing
# public exists — pre-IPO, private, or a venue-only synthetic — and an empty
# cell beats a wrong one.
CATALOG = {
    # --- indices ---
    "SP500": ('S&P 500', 'index', '^GSPC'),
    "XYZ100": ('XYZ 100 (largest non-financial US)', 'index', None),
    "JP225": ('Japan 225', 'index', '^N225'),
    "KR200": ('Korea 200', 'index', '^KS200'),
    # --- commodities ---
    "GOLD": ('Gold (troy oz)', 'metals', 'GC=F'),
    "SILVER": ('Silver (troy oz)', 'metals', 'SI=F'),
    "PLATINUM": ('Platinum (troy oz)', 'metals', 'PL=F'),
    "PALLADIUM": ('Palladium (troy oz)', 'metals', 'PA=F'),
    "COPPER": ('Copper (lb)', 'metals', 'HG=F'),
    "BRENTOIL": ('Brent Crude', 'energy', 'BZ=F'),
    "CL": ('WTI Crude', 'energy', 'CL=F'),
    "NATGAS": ('Henry Hub Natural Gas', 'energy', 'NG=F'),
    # --- fx ---
    "EUR": ('EUR/USD', 'fx', 'EURUSD=X'),
    "GBP": ('GBP/USD', 'fx', 'GBPUSD=X'),
    "JPY": ('USD/JPY', 'fx', 'JPY=X'),
    # --- etfs ---
    "SMH": ('VanEck Semiconductor ETF', 'etf', 'SMH'),
    "XLE": ('Energy Select Sector SPDR', 'etf', 'XLE'),
    "URNM": ('Sprott Uranium Miners ETF', 'etf', 'URNM'),
    "DRAM": ('Roundhill Memory ETF', 'etf', 'DRAM'),
    "EWY": ('iShares MSCI Korea', 'etf', 'EWY'),
    "EWJ": ('iShares MSCI Japan', 'etf', 'EWJ'),
    "EWT": ('iShares MSCI Taiwan', 'etf', 'EWT'),
    "EWZ": ('iShares MSCI Brazil', 'etf', 'EWZ'),
    # --- memory / storage ---
    "MU": ('Micron Technology', 'memory', 'MU'),
    "SNDK": ('Sandisk', 'memory', 'SNDK'),
    "WDC": ('Western Digital', 'memory', 'WDC'),
    "SKHX": ('SK hynix (KRX)', 'memory', '000660.KS'),
    "SKHY": ('SK Hynix ADS (pre-IPO)', 'memory', '000660.KS'),
    "KIOXIA": ('Kioxia Holdings', 'memory', '285A.T'),
    "CXMT": ('ChangXin Technology (pre-IPO)', 'memory', None),
    "SMSN": ('Samsung Electronics', 'memory', '005930.KS'),
    "GIGADEV": ('GigaDevice Semiconductor', 'memory', '603986.SS'),
    # --- semis ---
    "NVDA": ('NVIDIA', 'semis', 'NVDA'),
    "AMD": ('Advanced Micro Devices', 'semis', 'AMD'),
    "AVGO": ('Broadcom', 'semis', 'AVGO'),
    "MRVL": ('Marvell Technology', 'semis', 'MRVL'),
    "INTC": ('Intel', 'semis', 'INTC'),
    "TSM": ('TSMC ADS', 'semis', 'TSM'),
    "ASML": ('ASML Holding ADR', 'semis', 'ASML'),
    "AMAT": ('Applied Materials', 'semis', 'AMAT'),
    "QCOM": ('Qualcomm', 'semis', 'QCOM'),
    "ARM": ('Arm Holdings ADS', 'semis', 'ARM'),
    "CBRS": ('Cerebras Systems (pre-IPO)', 'semis', None),
    # --- ai infrastructure & models ---
    "CRWV": ('CoreWeave', 'ai-infra', 'CRWV'),
    "NBIS": ('Nebius Group', 'ai-infra', 'NBIS'),
    "ORCL": ('Oracle', 'ai-infra', 'ORCL'),
    "DELL": ('Dell Technologies', 'ai-infra', 'DELL'),
    "IBM": ('IBM', 'ai-infra', 'IBM'),
    "NOW": ('ServiceNow', 'ai-infra', 'NOW'),
    "PLTR": ('Palantir Technologies', 'ai-infra', 'PLTR'),
    "ZHIPU": ('Zhipu AI (Knowledge Atlas)', 'ai-infra', None),
    "MINIMAX": ('MiniMax Group', 'ai-infra', None),
    "BIRD": ('NewBird AI', 'ai-infra', None),
    "SHAZ": ('SharonAI Holdings', 'ai-infra', None),
    "BOT": ('RoboStrategy', 'ai-infra', None),
    "QNT": ('Quantinuum (pre-IPO)', 'ai-infra', None),
    # --- megacap ---
    "AAPL": ('Apple', 'megacap', 'AAPL'),
    "MSFT": ('Microsoft', 'megacap', 'MSFT'),
    "AMZN": ('Amazon', 'megacap', 'AMZN'),
    "GOOGL": ('Alphabet A', 'megacap', 'GOOGL'),
    "META": ('Meta Platforms', 'megacap', 'META'),
    "TSLA": ('Tesla', 'megacap', 'TSLA'),
    "NFLX": ('Netflix', 'megacap', 'NFLX'),
    "COST": ('Costco', 'megacap', 'COST'),
    "LLY": ('Eli Lilly', 'megacap', 'LLY'),
    "BABA": ('Alibaba ADS', 'megacap', 'BABA'),
    # --- crypto-linked equities ---
    "COIN": ('Coinbase Global', 'crypto-equity', 'COIN'),
    "MSTR": ('Strategy (MicroStrategy)', 'crypto-equity', 'MSTR'),
    "STRC": ('Strategy Series A Preferred', 'crypto-equity', 'STRC'),
    "CRCL": ('Circle Internet Group', 'crypto-equity', 'CRCL'),
    "HOOD": ('Robinhood Markets', 'crypto-equity', 'HOOD'),
    "PURRDAT": ('Hyperliquid Strategies', 'crypto-equity', None),
    "GME": ('GameStop', 'crypto-equity', 'GME'),
    # --- everything else ---
    "SPCX": ('SpaceX (pre-IPO)', 'other', None),
    "RKLB": ('Rocket Lab', 'other', 'RKLB'),
    "BE": ('Bloom Energy', 'other', 'BE'),
    "USAR": ('USA Rare Earth', 'other', 'USAR'),
    "LITE": ('Lumentum Holdings', 'other', 'LITE'),
    "NOK": ('Nokia', 'other', 'NOK'),
    "BB": ('BlackBerry', 'other', 'BB'),
    "BX": ('Blackstone', 'other', 'BX'),
    "DKNG": ('DraftKings', 'other', 'DKNG'),
    "EBAY": ('eBay', 'other', 'EBAY'),
    "HIMS": ('Hims & Hers Health', 'other', 'HIMS'),
    "RIVN": ('Rivian Automotive', 'other', 'RIVN'),
    "ZM": ('Zoom Communications', 'other', 'ZM'),
    "SOFTBANK": ('SoftBank Group', 'other', '9984.T'),
    "HYUNDAI": ('Hyundai Motor', 'other', '005380.KS'),
}

GROUP_ORDER = ("index", "metals", "energy", "fx", "etf", "memory", "semis",
               "ai-infra", "megacap", "crypto-equity", "other", "unclassified")

HEADER = """\
# trade.xyz tradable universe -- every live market on the XYZ dex.
#
# GENERATED by scripts/sync_tradexyz.py -- re-run it after the venue lists or
# delists a market. Hand edits to the holdings will be overwritten; put your own
# positions in a separate list instead.
#
# Prices come from the venue itself (source: hyperliquid), not Yahoo, so the
# numbers match what you actually trade, and charts show the perp
# (HIP3XYZ:<SYMBOL>USDC.P, derived automatically).
#
# `ref:` names a Yahoo instrument for the same underlying. It fills what the
# venue cannot: the fundamentals a US-only screener has nothing for (285A.T for
# KIOXIA, 005930.KS for SMSN) and the year-scale metrics -- %YTD, %1Y, delta to
# the 52w high, 200SMA -- that a market listed six months ago has no history
# for. Those cells are marked "from <ref>" on hover, and stop being borrowed
# once the venue has enough bars of its own. Price, %1D, gaps, RS and the
# 20/50SMA always stay native to the contract.
#
# Markets with no ref have no public equivalent at all (pre-IPO, private, or a
# venue-only synthetic); their fundamentals stay blank rather than wrong.
title: trade.xyz Universe
order: 0.6              # just after the trade.xyz Book
source: hyperliquid
benchmark: SP500

holdings:
"""


def build_yaml(markets):
    """markets: live symbols from the API. Returns (yaml text, unknown symbols)."""
    unknown = sorted(m for m in markets if m not in CATALOG)
    by_group = {}
    for symbol in markets:
        name, group, equity = CATALOG.get(symbol, (None, "unclassified", None))
        by_group.setdefault(group, []).append((symbol, name, equity))

    width = max((len(s) for s in markets), default=8) + 2
    name_width = max((len(v[0]) for v in CATALOG.values() if v[0]), default=20) + 2
    out = [HEADER]
    for group in GROUP_ORDER:
        entries = sorted(by_group.get(group) or [])
        if not entries:
            continue
        out.append(f"  # ── {group} " + "─" * max(0, 56 - len(group)) + "\n")
        for symbol, name, equity in entries:
            fields = [f"ticker: {symbol + ',':<{width}}"]
            if name:
                fields.append(f"name: {name + ',':<{name_width}}")
            fields.append(f"group: {group}")
            if equity:
                fields.append(f", ref: {equity}")
            out.append("  - {" + "".join(fields) + "}\n")
        out.append("\n")
    return "".join(out).rstrip("\n") + "\n", unknown


def current_symbols(path):
    """Symbols already in the file, read without importing yaml semantics —
    this must work even if the file has been hand-broken."""
    if not path.exists():
        return set()
    found = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("- {ticker:"):
            found.add(line.split("ticker:", 1)[1].split(",", 1)[0].strip())
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="rewrite the watchlist file")
    ap.add_argument("--dex", default=hlfetch.DEFAULT_DEX)
    ap.add_argument("--out", default=str(ROOT / "watchlists" / "tradexyz-universe.yaml"))
    args = ap.parse_args()

    markets = hlfetch.list_markets(dex=args.dex)
    if not markets:
        sys.exit(f"error: {args.dex} returned no live markets — API down or dex renamed?")
    path = Path(args.out)
    existing = current_symbols(path)

    added = sorted(set(markets) - existing)
    removed = sorted(existing - set(markets))
    print(f"{len(markets)} live markets on {args.dex}")
    if added:
        print(f"  added since the file was written:   {', '.join(added)}")
    if removed:
        print(f"  delisted since the file was written: {', '.join(removed)}")
    if existing and not (added or removed):
        print("  no change")

    text, unknown = build_yaml(markets)
    if unknown:
        print(f"warning: not in CATALOG, written as unclassified: {', '.join(unknown)}",
              file=sys.stderr)
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path}")
    else:
        print("(dry run — pass --write to update the file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
