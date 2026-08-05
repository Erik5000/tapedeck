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

# symbol -> (display name, group, US-listed equity or None)
#
# The third field is what a market's fundamentals are looked up under. It is
# set only where the venue symbol really is that US ticker. Bullion, crude, FX,
# indices, foreign listings and pre-IPO markets get None on purpose: NYSE GOLD
# is Barrick, not bullion, and NYSE CL is Colgate-Palmolive, not WTI crude —
# matching on the bare symbol would give crude oil an earnings date.
CATALOG = {
    # --- indices ---
    "SP500": ('S&P 500', 'index', None),
    "XYZ100": ('XYZ 100 (largest non-financial US)', 'index', None),
    "JP225": ('Japan 225', 'index', None),
    "KR200": ('Korea 200', 'index', None),
    # --- commodities ---
    "GOLD": ('Gold (troy oz)', 'metals', None),
    "SILVER": ('Silver (troy oz)', 'metals', None),
    "PLATINUM": ('Platinum (troy oz)', 'metals', None),
    "PALLADIUM": ('Palladium (troy oz)', 'metals', None),
    "COPPER": ('Copper (lb)', 'metals', None),
    "BRENTOIL": ('Brent Crude', 'energy', None),
    "CL": ('WTI Crude', 'energy', None),
    "NATGAS": ('Henry Hub Natural Gas', 'energy', None),
    # --- fx ---
    "EUR": ('EUR/USD', 'fx', None),
    "GBP": ('GBP/USD', 'fx', None),
    "JPY": ('USD/JPY', 'fx', None),
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
    "SKHX": ('SK hynix (KRX)', 'memory', None),
    "SKHY": ('SK Hynix ADS (pre-IPO)', 'memory', None),
    "KIOXIA": ('Kioxia Holdings', 'memory', None),
    "CXMT": ('ChangXin Technology (pre-IPO)', 'memory', None),
    "SMSN": ('Samsung Electronics', 'memory', None),
    "GIGADEV": ('GigaDevice Semiconductor', 'memory', None),
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
    "SOFTBANK": ('SoftBank Group', 'other', None),
    "HYUNDAI": ('Hyundai Motor', 'other', None),
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
# numbers match what you actually trade. Two consequences worth knowing:
#   * these markets listed between late 2025 and mid 2026, so 52w high/low,
#     %YTD, %1Y and the 200SMA read n/a until enough history accrues
#   * the venue publishes no fundamentals -- market cap, P/E, P/S, sector and
#     earnings come from the TradingView screener where a symbol is also a US
#     ticker, and are blank otherwise
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
                fields.append(f", equity: {equity}")
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
