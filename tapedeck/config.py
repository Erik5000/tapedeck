"""Load, validate and scaffold watchlist yaml files."""

import re
import shutil
from pathlib import Path

import yaml

_TEMPLATE = """\
title: {title}
# order: 3              # optional tab position (lists without order go last)
benchmark: SPY
# cockpit: /path/to/COCKPIT.md   # optional: render a read-only status panel parsed from this markdown file
# anti_basket: other-list        # optional: aggregate that watchlist as an "anti-basket" row in the basket table

holdings:
  - ticker: NVDA
  # per entry, all optional:
  #   name: NVIDIA            # display name
  #   group: semis            # tag shown under the ticker
  #   shares: 10              # position size -> P&L columns + summary tiles
  #   cost_basis: 118.5       # avg entry -> open P&L
  #   tv_symbol: NASDAQ:NVDA  # TradingView chart symbol override
"""


def load_config(path):
    raw = yaml.safe_load(Path(path).read_text()) or {}
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
            "name": entry.get("name"),
            "group": entry.get("group"),
            "shares": float(entry["shares"]) if entry.get("shares") is not None else None,
            "cost_basis": float(entry["cost_basis"]) if entry.get("cost_basis") is not None else None,
            "tv_symbol": entry.get("tv_symbol"),
        })
    return {"benchmark": str(raw.get("benchmark") or "SPY").upper(),
            "title": raw.get("title"), "order": raw.get("order"), "holdings": holdings,
            "cockpit": str(raw["cockpit"]) if raw.get("cockpit") else None,
            "anti_basket": str(raw["anti_basket"]).strip() if raw.get("anti_basket") else None}


def load_watchlists(directory):
    """Load every *.yaml in the directory as a watchlist (files starting with _ are skipped)."""
    directory = Path(directory)
    paths = sorted(p for p in directory.glob("*.yaml") if not p.name.startswith("_"))
    watchlists = []
    for path in paths:
        cfg = load_config(path)
        title = cfg["title"] or path.stem.replace("-", " ").replace("_", " ").title()
        watchlists.append({"name": path.stem, "title": title, "order": cfg["order"],
                           "benchmark": cfg["benchmark"], "holdings": cfg["holdings"],
                           "cockpit": cfg["cockpit"], "anti_basket": cfg["anti_basket"]})
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
