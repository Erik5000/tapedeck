#!/usr/bin/env python3
"""BLOOM — situational-awareness watchlist dashboard.

Loads every watchlist in watchlists/*.yaml, fetches live data (TradingView
screener + Yahoo history), and writes one self-contained interactive HTML
dashboard with a tab per watchlist to output/.
"""

import argparse
import json
import subprocess
import sys
import warnings
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def export_png(html_path, png_path):
    chrome = next((p for p in CHROME_PATHS if Path(p).exists()), None)
    if not chrome:
        print("png: Chrome not found — skipping (install Google Chrome for --png)", file=sys.stderr)
        return False
    result = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", f"--screenshot={png_path}",
         "--window-size=2050,1500", "--hide-scrollbars", "--virtual-time-budget=2000",
         html_path.as_uri()],
        capture_output=True, timeout=60)
    ok = result.returncode == 0 and Path(png_path).exists()
    print(f"png: {'wrote ' + str(png_path) if ok else 'export failed'}", file=sys.stderr)
    return ok


def _slim_rows(rows):
    keep = ("ticker", "name", "group", "price", "pct_1d", "pct_ytd", "pct_off_high",
            "rs_1m", "rs_rank", "pe", "ps", "market_cap", "earnings_date", "gap_pct",
            "tv_symbol")
    slim_rows = []
    for r in rows:
        slim = {k: r.get(k) for k in keep}
        slim["sma_above"] = {w: s["above"] for w, s in (r.get("sma") or {}).items()}
        if r.get("position"):
            slim["position"] = r["position"]
        slim_rows.append(slim)
    return slim_rows


def slim_json(rendered_lists):
    return {"lists": [{
        "name": wl["name"], "title": wl["title"], "benchmark": wl["benchmark"],
        "rows": _slim_rows(wl["rows"]), "summary": wl["summary"],
        "alerts": wl["alerts"], "diff": wl["diff"],
    } for wl in rendered_lists]}


def main():
    parser = argparse.ArgumentParser(description="BLOOM watchlist dashboard")
    parser.add_argument("--new", dest="new_list", metavar="NAME", default=None,
                        help='scaffold a new watchlist (e.g. --new "my semis") and exit')
    parser.add_argument("--config", default=None,
                        help="single watchlist yaml (bypasses the watchlists/ directory)")
    parser.add_argument("--list", dest="only", default=None,
                        help="comma-separated watchlist names (filenames without .yaml) to include")
    parser.add_argument("--no-open", action="store_true", help="don't open the dashboard in the browser")
    parser.add_argument("--png", action="store_true", help="also export a PNG via headless Chrome")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="print machine-readable summary JSON to stdout")
    parser.add_argument("--source", choices=("auto", "yahoo"), default="auto",
                        help="auto = TradingView screener for snapshot fields with Yahoo "
                             "fallback (default); yahoo = Yahoo only")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")  # urllib3/LibreSSL noise on macOS system Python

    from bloom import alerts as alerts_mod
    from bloom import config, fetch, pipeline, render, snapshot, tvscan

    if args.new_list:
        path = config.new_watchlist(ROOT / "watchlists", args.new_list)
        print(f"created {path}\nedit the tickers, then run bloom.py — it appears as a new tab")
        return

    if args.config:
        cfg = config.load_config(args.config)
        stem = Path(args.config).stem
        watchlists = [{"name": stem,
                       "title": cfg["title"] or stem.replace("-", " ").replace("_", " ").title(),
                       "benchmark": cfg["benchmark"], "holdings": cfg["holdings"]}]
    else:
        seeded = config.seed_watchlists(ROOT / "watchlists", ROOT / "examples")
        if seeded:
            print(f"seeded watchlists/ from examples: {', '.join(seeded)}", file=sys.stderr)
        watchlists = config.load_watchlists(ROOT / "watchlists")
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        watchlists = [w for w in watchlists if w["name"] in wanted]
        if not watchlists:
            sys.exit(f"error: no watchlist matches --list {args.only}")

    all_tickers = list(dict.fromkeys(
        h["ticker"] for w in watchlists for h in w["holdings"]))
    benchmarks = list(dict.fromkeys(w["benchmark"] for w in watchlists))
    today = date.today()

    tv = None
    if args.source == "auto":
        try:
            tv = tvscan.fetch_scan(all_tickers)
            print(f"BLOOM · tradingview screener: {len(tv)}/{len(all_tickers)} tickers", file=sys.stderr)
        except Exception as exc:
            print(f"warning: tradingview screener failed ({exc}) — using Yahoo fundamentals", file=sys.stderr)

    info_tickers = None if tv is None else [t for t in all_tickers if t not in tv]
    print(f"BLOOM · fetching history: {len(all_tickers)} tickers + {'/'.join(benchmarks)} "
          f"across {len(watchlists)} watchlist(s) …", file=sys.stderr)
    hists, bench_closes, infos = fetch.fetch_universe(all_tickers, benchmarks, info_tickers=info_tickers)

    missing = [t for t in all_tickers if t not in hists]
    if missing:
        print(f"warning: no price history for {', '.join(missing)} (rows degrade)", file=sys.stderr)

    out_dir = ROOT / "output"
    rendered_lists = []
    for wl in watchlists:
        bench_close = bench_closes.get(wl["benchmark"])
        if bench_close is None:
            print(f"warning: no benchmark history for {wl['benchmark']} ({wl['name']}) — RS shows n/a",
                  file=sys.stderr)
        rows, summary = pipeline.build_rows(hists, bench_close, infos, wl["holdings"], today, tv=tv)
        alert_list = alerts_mod.build_alerts(rows, today)
        snap_dir = out_dir / "snapshots" / wl["name"]
        prev = snapshot.find_previous(snap_dir) if snap_dir.exists() else None
        diff = snapshot.diff_snapshots(prev, rows) if prev else None
        snapshot.save_snapshot(rows, snap_dir, today.isoformat())
        rendered_lists.append({"name": wl["name"], "title": wl["title"], "benchmark": wl["benchmark"],
                               "rows": rows, "summary": summary, "alerts": alert_list, "diff": diff})

    data_date = max((h.index[-1].date() for h in hists.values()), default=None)
    html = render.render_multi(rendered_lists, today,
                               data_date=data_date.isoformat() if data_date else None)
    out_path = out_dir / f"bloom-{today.isoformat()}.html"
    out_path.write_text(html)
    print(f"wrote {out_path}", file=sys.stderr)

    if args.png:
        export_png(out_path, out_dir / f"bloom-{today.isoformat()}.png")
    if args.as_json:
        print(json.dumps(slim_json(rendered_lists), indent=1, default=str))
    if not args.no_open:
        subprocess.run(["open", str(out_path)], check=False)


if __name__ == "__main__":
    main()
