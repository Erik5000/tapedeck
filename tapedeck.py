#!/usr/bin/env python3
"""TAPEDECK — situational-awareness watchlist dashboard.

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


def serve(port, open_browser=True):
    """Serve the last dashboard with a Refresh button, until Ctrl-C.

    Doesn't fetch anything itself — it shows whatever run is already on disk and
    lets the page trigger new ones. This is the same server TAPEDECK.app spawns,
    which makes it the way to test the app's backend without building the app.
    """
    from tapedeck import server as server_mod

    httpd = server_mod.make_server("127.0.0.1", port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"TAPEDECK · serving {url} (ctrl-c to stop)", file=sys.stderr)
    if open_browser:
        subprocess.run(["open", url], check=False)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nTAPEDECK · stopped", file=sys.stderr)
    finally:
        httpd.state.jobs.terminate(grace=2.0)
        httpd.server_close()
    return 0


def main():
    # stdlib-only module, so this stays cheap enough to import before argparse
    from tapedeck.server import DEFAULT_PORT

    parser = argparse.ArgumentParser(description="TAPEDECK watchlist dashboard")
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
    parser.add_argument("--serve", action="store_true",
                        help="serve the last dashboard at http://127.0.0.1:PORT with a "
                             "Refresh button (this is what TAPEDECK.app runs)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"port for --serve (default {DEFAULT_PORT})")
    args = parser.parse_args()

    warnings.filterwarnings("ignore")  # urllib3/LibreSSL noise on macOS system Python

    from tapedeck import alerts as alerts_mod
    from tapedeck import config, feed, fetch, hlfetch, metrics, pipeline, render, snapshot, tvscan, vaultlink, vwaplink

    if args.new_list:
        path = config.new_watchlist(ROOT / "watchlists", args.new_list)
        print(f"created {path}\nedit the tickers, then run tapedeck.py — it appears as a new tab")
        return

    if args.serve:
        return serve(args.port or DEFAULT_PORT, open_browser=not args.no_open)

    if args.config:
        cfg = config.load_config(args.config)
        stem = Path(args.config).stem
        if cfg["anti_basket"]:
            print("note: anti_basket is ignored in --config single-list mode", file=sys.stderr)
        watchlists = [{"name": stem,
                       "title": cfg["title"] or stem.replace("-", " ").replace("_", " ").title(),
                       "source": cfg["source"], "dex": cfg["dex"],
                       "benchmark": cfg["benchmark"], "holdings": cfg["holdings"],
                       "cockpit": cfg["cockpit"], "anti_basket": None,
                       "vwap": cfg["vwap"], "vwap_alert_pct": cfg["vwap_alert_pct"]}]
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

    def source_of(wl):
        return wl.get("source") or "yahoo"

    def dex_of(wl):
        return wl.get("dex") or hlfetch.DEFAULT_DEX

    def bench_key(wl):
        """The benchmark under the same namespace as the list's own holdings."""
        return (wl["benchmark"] if source_of(wl) == "yahoo"
                else hlfetch.qualify(wl["benchmark"], dex_of(wl)))

    # The screener matches bare US names: a Yahoo holding's own ticker, and for
    # a venue holding only the equity it explicitly declares. Namespaced keys
    # drive the fetches, so one ticker can sit on two sources at once.
    all_tickers = list(dict.fromkeys(
        (h["ticker"] if source_of(w) == "yahoo" else h.get("equity"))
        for w in watchlists for h in w["holdings"]
        if source_of(w) == "yahoo" or h.get("equity")))
    all_keys = list(dict.fromkeys(
        h["key"] if h.get("key") else h["ticker"] for w in watchlists for h in w["holdings"]))
    today = date.today()

    tv = None
    if args.source == "auto":
        try:
            tv = tvscan.fetch_scan(all_tickers)
            print(f"TAPEDECK · tradingview screener: {len(tv)}/{len(all_tickers)} tickers", file=sys.stderr)
        except Exception as exc:
            print(f"warning: tradingview screener failed ({exc}) — using Yahoo fundamentals", file=sys.stderr)

    yahoo_lists = [w for w in watchlists if source_of(w) == "yahoo"]
    hl_lists = [w for w in watchlists if source_of(w) == "hyperliquid"]
    hists, bench_closes, infos = {}, {}, {}

    if yahoo_lists:
        y_tickers = list(dict.fromkeys(h["ticker"] for w in yahoo_lists for h in w["holdings"]))
        y_bench = list(dict.fromkeys(w["benchmark"] for w in yahoo_lists))
        info_tickers = None if tv is None else [t for t in y_tickers if t not in tv]
        print(f"TAPEDECK · fetching history: {len(y_tickers)} tickers + {'/'.join(y_bench)} "
              f"across {len(yahoo_lists)} watchlist(s) …", file=sys.stderr)
        y_hists, y_bench_closes, y_infos = fetch.fetch_universe(
            y_tickers, y_bench, info_tickers=info_tickers)
        hists.update(y_hists)
        bench_closes.update(y_bench_closes)
        infos.update(y_infos)

    by_dex = {}
    for wl in hl_lists:
        tickers, benches = by_dex.setdefault(dex_of(wl), ([], []))
        tickers.extend(h["ticker"] for h in wl["holdings"])
        benches.append(wl["benchmark"])
    for dex, (tickers, benches) in by_dex.items():
        tickers = list(dict.fromkeys(tickers))
        benches = list(dict.fromkeys(benches))
        print(f"TAPEDECK · fetching {dex} history: {len(tickers)} markets + "
              f"{'/'.join(benches)} …", file=sys.stderr)
        h_hists, h_bench_closes, _ = hlfetch.fetch_universe(tickers, benches, dex=dex)
        hists.update(h_hists)
        bench_closes.update(h_bench_closes)

    missing = [k for k in all_keys if k not in hists]
    if missing:
        print(f"warning: no price history for {', '.join(missing)} (rows degrade)", file=sys.stderr)

    out_dir = ROOT / "output"
    rendered_lists = []
    for wl in watchlists:
        bench_close = bench_closes.get(bench_key(wl))
        if bench_close is None:
            print(f"warning: no benchmark history for {wl['benchmark']} ({wl['name']}) — RS shows n/a",
                  file=sys.stderr)
        rows, summary = pipeline.build_rows(hists, bench_close, infos, wl["holdings"], today, tv=tv)
        vwap_feed = vwaplink.load_vwap(wl["vwap"]) if wl.get("vwap") else None
        vwaplink.attach_vwap(rows, vwap_feed, wl["vwap_alert_pct"])
        alert_list = alerts_mod.build_alerts(rows, today) + alerts_mod.build_vwap_alerts(rows)
        snap_dir = out_dir / "snapshots" / wl["name"]
        prev = snapshot.find_previous(snap_dir) if snap_dir.exists() else None
        diff = snapshot.diff_snapshots(prev, rows) if prev else None
        snapshot.save_snapshot(rows, snap_dir, today.isoformat())
        cockpit = vaultlink.load_cockpit(wl["cockpit"]) if wl.get("cockpit") else None
        rendered_lists.append({"name": wl["name"], "title": wl["title"], "benchmark": wl["benchmark"],
                               "rows": rows, "summary": summary, "alerts": alert_list, "diff": diff,
                               "cockpit": cockpit,
                               "cockpit_fresh": vaultlink.cockpit_freshness(cockpit, today),
                               "vwap_fresh": vwaplink.vwap_freshness(vwap_feed, today),
                               "vwap_alert_pct": wl["vwap_alert_pct"]})

    # cross-list composition: baskets need every list's rows (the anti-basket is a sibling list)
    by_name = {r["name"]: r for r in rendered_lists}
    for wl, rendered in zip(watchlists, rendered_lists):
        baskets = metrics.group_aggregates(rendered["rows"])
        anti = wl.get("anti_basket")
        if anti and anti in by_name:
            if by_name[anti]["benchmark"] != rendered["benchmark"]:
                print(f"warning: anti_basket '{anti}' uses benchmark {by_name[anti]['benchmark']} "
                      f"— RS not directly comparable to {rendered['benchmark']}", file=sys.stderr)
            baskets.append(metrics.basket_aggregate(by_name[anti]["rows"], "anti-basket"))
        elif anti:
            print(f"warning: anti_basket '{anti}' not loaded (add it or drop --list) — skipping",
                  file=sys.stderr)
        rendered["baskets"] = baskets

    data_date = max((h.index[-1].date() for h in hists.values()), default=None)
    html = render.render_multi(rendered_lists, today,
                               data_date=data_date.isoformat() if data_date else None)
    out_path = out_dir / f"tapedeck-{today.isoformat()}.html"
    out_path.write_text(html)
    print(f"wrote {out_path}", file=sys.stderr)

    feed_obj = feed.build_feed(rendered_lists, today=today,
                               data_date=data_date.isoformat() if data_date else None)
    feed_path = out_dir / "tapedeck-latest.json"
    feed_path.write_text(json.dumps(feed_obj, indent=1, default=str))
    print(f"wrote {feed_path}", file=sys.stderr)

    if args.png:
        export_png(out_path, out_dir / f"tapedeck-{today.isoformat()}.png")
    if args.as_json:
        print(json.dumps(feed_obj, indent=1, default=str))
    if not args.no_open:
        subprocess.run(["open", str(out_path)], check=False)


if __name__ == "__main__":
    main()
