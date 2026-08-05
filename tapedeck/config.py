"""Load, validate and scaffold watchlist yaml files."""

import re
import shutil
from pathlib import Path

import yaml

from . import hlfetch

# Where a list's prices come from. "yahoo" is the default and covers every
# list that existed before trade.xyz support; "hyperliquid" reads XYZ markets
# on HyperCore, which carry short 24/7 history and no fundamentals.
SOURCES = ("yahoo", "hyperliquid")
DEFAULT_SOURCE = "yahoo"

_TEMPLATE = """\
title: {title}
# order: 3              # optional tab position (lists without order go last)
benchmark: SPY
# source: hyperliquid   # optional: prices from trade.xyz instead of Yahoo
#                       # (short history, no fundamentals; benchmark defaults to SP500)
# cockpit: /path/to/COCKPIT.md   # optional: render a read-only status panel parsed from this markdown file
# anti_basket: other-list        # optional: aggregate that watchlist as an "anti-basket" row in the basket table
# vwap: /path/to/vwap-latest.json  # optional: VWAP levels from a vwap-scanner --json-out feed
# vwap_alert_pct: 2.0              # optional: proximity band (%) that earns an Alerts entry

holdings:
  - ticker: NVDA
  # per entry, all optional:
  #   name: NVIDIA            # display name
  #   group: semis            # tag shown under the ticker
  #   shares: 10              # position size -> P&L columns + summary tiles
  #   cost_basis: 118.5       # avg entry -> open P&L
  #   tv_symbol: NASDAQ:NVDA  # TradingView chart symbol override
"""


def _ref_of(entry):
    """The holding's reference symbol. Yahoo symbols are case-sensitive in
    their suffixes (285A.T, ^GSPC, GC=F, EURUSD=X), so this only strips —
    unlike `ticker`, which is uppercased."""
    value = entry.get("ref")
    if value is None:
        value = entry.get("equity")      # the field's former name
    value = str(value).strip() if value is not None else ""
    return value or None


def load_config(path):
    raw = yaml.safe_load(Path(path).read_text()) or {}
    source = str(raw.get("source") or DEFAULT_SOURCE).strip().lower()
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r} — expected one of {', '.join(sorted(SOURCES))}")
    dex = str(raw.get("dex") or hlfetch.DEFAULT_DEX).strip()
    holdings_raw = raw.get("holdings") or []
    if not holdings_raw:
        raise ValueError("portfolio config needs at least one entry under 'holdings'")
    holdings, seen = [], set()
    for entry in holdings_raw:
        ticker = (entry or {}).get("ticker")
        if not ticker:
            raise ValueError(f"holding missing 'ticker': {entry!r}")
        ticker = str(ticker).upper()
        if ticker in seen:
            raise ValueError(f"duplicate ticker: {ticker}")
        seen.add(ticker)
        holdings.append({
            "ticker": ticker,
            # The fetch key namespaces the source, so NVDA can be a Yahoo row
            # in one list and a trade.xyz perp in another within the same run.
            "key": ticker if source == "yahoo" else hlfetch.qualify(ticker, dex),
            "source": source,
            "dex": dex,
            # A Yahoo-resolvable symbol for the same underlying: 285A.T for
            # KIOXIA, GC=F for GOLD, ^GSPC for SP500. It supplies fundamentals
            # and the year-scale metrics the primary source can't support, and
            # is looked up under this key and nowhere else — the venue's GOLD
            # is bullion while NYSE GOLD is Barrick, and its CL is WTI crude
            # while NYSE CL is Colgate-Palmolive, so matching on the bare
            # symbol would hand crude oil an earnings date.
            # `equity:` is the older name for the same field.
            "ref": _ref_of(entry),
            "name": entry.get("name"),
            "group": entry.get("group"),
            "shares": float(entry["shares"]) if entry.get("shares") is not None else None,
            "cost_basis": float(entry["cost_basis"]) if entry.get("cost_basis") is not None else None,
            "tv_symbol": entry.get("tv_symbol"),
        })
    vwap_alert_pct = raw.get("vwap_alert_pct")
    vwap_alert_pct = 2.0 if vwap_alert_pct is None else float(vwap_alert_pct)
    if vwap_alert_pct < 0:
        raise ValueError(f"vwap_alert_pct must be >= 0, got {vwap_alert_pct!r}")
    default_bench = "SPY" if source == "yahoo" else "SP500"
    return {"benchmark": str(raw.get("benchmark") or default_bench).upper(),
            "source": source, "dex": dex,
            "title": raw.get("title"), "order": raw.get("order"), "holdings": holdings,
            "cockpit": str(raw["cockpit"]) if raw.get("cockpit") else None,
            "anti_basket": str(raw["anti_basket"]).strip() if raw.get("anti_basket") else None,
            "vwap": str(raw["vwap"]) if raw.get("vwap") else None,
            "vwap_alert_pct": vwap_alert_pct}


def load_watchlists(directory):
    """Load every *.yaml in the directory as a watchlist (files starting with _ are skipped)."""
    directory = Path(directory)
    paths = sorted(p for p in directory.glob("*.yaml") if not p.name.startswith("_"))
    watchlists = []
    for path in paths:
        cfg = load_config(path)
        title = cfg["title"] or path.stem.replace("-", " ").replace("_", " ").title()
        watchlists.append({"name": path.stem, "title": title, "order": cfg["order"],
                           "source": cfg["source"], "dex": cfg["dex"],
                           "benchmark": cfg["benchmark"], "holdings": cfg["holdings"],
                           "cockpit": cfg["cockpit"], "anti_basket": cfg["anti_basket"],
                           "vwap": cfg["vwap"], "vwap_alert_pct": cfg["vwap_alert_pct"]})
    if not watchlists:
        raise ValueError(f"no watchlists found in {directory} — add a .yaml file with a 'holdings' list")
    watchlists.sort(key=lambda w: (w["order"] is None, w["order"] if w["order"] is not None else 0, w["name"]))
    return watchlists


def new_watchlist(directory, name, title=None):
    """Scaffold watchlists/<slug>.yaml from the template. Returns the path."""
    slug = re.sub(r"[\s_]+", "-", str(name).strip().lower())
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError(f"invalid watchlist name {name!r} — use letters, digits, spaces or dashes")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.yaml"
    if path.exists():
        raise ValueError(f"{path} already exists")
    path.write_text(_TEMPLATE.format(title=title or slug.replace("-", " ").title()))
    return path


def seed_watchlists(directory, examples_dir):
    """First-run bootstrap: copy example lists into an empty watchlists dir.
    Returns the names copied ([] if the dir already has lists)."""
    directory = Path(directory)
    if any(p for p in directory.glob("*.yaml") if not p.name.startswith("_")):
        return []
    directory.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(Path(examples_dir).glob("*.yaml")):
        shutil.copy(src, directory / src.name)
        copied.append(src.stem)
    return copied
