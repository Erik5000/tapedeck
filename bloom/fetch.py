"""All network access: yfinance batch history + per-ticker fundamentals."""

from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf


def fetch_history(tickers, period="1y"):
    df = yf.download(list(tickers), period=period, interval="1d",
                     group_by="ticker", auto_adjust=True, progress=False, threads=True)
    if df is None or df.empty:
        return {}
    if not isinstance(df.columns, pd.MultiIndex):
        sub = df.dropna(how="all")
        return {tickers[0]: sub} if len(sub) else {}
    hists = {}
    for ticker in tickers:
        if ticker not in df.columns.get_level_values(0):
            continue
        sub = df[ticker].dropna(how="all")
        if len(sub):
            hists[ticker] = sub
    return hists


def _info_one(ticker):
    out = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        out = {
            "name": info.get("longName") or info.get("shortName"),
            "market_cap": info.get("marketCap"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "pe": info.get("trailingPE"),
            "sector": info.get("sector"),
            "exchange": info.get("exchange"),
            "earnings_date": None,
        }
        cal = t.calendar or {}
        dates = cal.get("Earnings Date") or []
        if dates:
            out["earnings_date"] = min(dates).isoformat()
    except Exception:
        pass  # per-ticker failure degrades to n/a, never kills the run
    return out


def fetch_info(tickers, max_workers=8):
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = pool.map(_info_one, tickers)
    return dict(zip(tickers, results))


def fetch_universe(tickers, benchmarks, period="1y", info_tickers=None):
    """One batch fetch for all watchlists: union of tickers + benchmarks."""
    tickers = list(dict.fromkeys(tickers))
    wanted = list(dict.fromkeys(list(tickers) + list(benchmarks)))
    all_hists = fetch_history(wanted, period=period)
    bench_closes = {b: all_hists[b]["Close"] for b in benchmarks if b in all_hists}
    hists = {t: hist for t, hist in all_hists.items() if t in set(tickers)}
    info_list = tickers if info_tickers is None else [t for t in tickers if t in set(info_tickers)]
    infos = fetch_info(info_list) if info_list else {}
    return hists, bench_closes, infos
