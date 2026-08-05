"""Assemble render-ready row dicts from fetched data. Pure given inputs."""

from . import fx, metrics

SMA_WINDOWS = (20, 50, 200)

# Yahoo exchange code → TradingView exchange prefix
_TV_EXCHANGE = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
                "NYQ": "NYSE", "ASE": "AMEX", "PCX": "AMEX"}

# HIP-3 dex → TradingView exchange prefix. Only xyz is mapped because only xyz
# has been verified to exist there; an unmapped dex falls through to the bare
# ticker rather than inventing a prefix that would render "symbol doesn't exist".
_TV_HIP3 = {"xyz": "HIP3XYZ"}

# The venue's perp contracts are listed on TradingView as <SYMBOL>USDC.P, which
# is exactly the API symbol for 87 of the 88 live markets. SKHX is the one
# exception — TradingView follows trade.xyz's docs naming (SKHYNIX) where the
# API uses SKHX, the same split that already affects SMSN/SAMSUNG and CL/WTIOIL.
_TV_HIP3_ALIAS = {"SKHX": "SKHYNIX"}


def tv_symbol(ticker, exchange, override=None, source="yahoo", dex="xyz"):
    """The TradingView symbol for a row's chart panel.

    A venue holding charts the perp it actually trades, not a spot proxy — the
    bare ticker resolved to nothing (SOFTBANK), and the equity proxies that did
    resolve were delayed feeds of a different instrument.
    """
    if override:
        return override
    if source == "hyperliquid":
        prefix = _TV_HIP3.get(dex or "")
        if prefix:
            return f"{prefix}:{_TV_HIP3_ALIAS.get(ticker, ticker)}USDC.P"
        return ticker
    prefix = _TV_EXCHANGE.get(exchange or "")
    return f"{prefix}:{ticker}" if prefix else ticker


def _empty_row(holding, info):
    return {
        "ticker": holding["ticker"],
        "name": holding.get("name") or info.get("name") or holding["ticker"],
        "group": holding.get("group"),
        "sector": info.get("sector"),
        "market_cap": info.get("market_cap"),
        "ps": info.get("ps"),
        "pe": info.get("pe"),
        "earnings_date": info.get("earnings_date"),
        "tv_symbol": tv_symbol(holding["ticker"], info.get("exchange"),
                               holding.get("tv_symbol"),
                               source=holding.get("source") or "yahoo",
                               dex=holding.get("dex") or "xyz"),
        "price": None, "pct_1d": None, "pct_ytd": None, "pct_1y": None,
        "spark": [], "pct_off_high": None, "new_52w": None,
        "rs_1m": None, "rs_3m": None, "rs_bars": [], "rs_rank": None,
        "sma": {}, "sma_cross": {}, "gap_pct": None,
        "rel_vol": None, "atr_pct": None,
        "position": None,
        # field -> the reference symbol it came from, for the cell's marker.
        "borrowed": {},
    }


# snapshot fields the TradingView screener may override (history-derived
# series — spark, RS, SMA state, gaps — always stay history-based)
_TV_PRICE_KEYS = ("price", "pct_1d", "pct_ytd", "pct_off_high", "atr_pct", "rel_vol")
_TV_FUNDAMENTAL_KEYS = ("name", "sector", "market_cap", "pe", "ps", "earnings_date")
# tv_symbol is deliberately outside the fundamentals: the screener returns the
# equity's symbol, which on a venue row would replace the perp's chart with a
# delayed spot chart of a different instrument.
_TV_OVERRIDE_KEYS = _TV_PRICE_KEYS + _TV_FUNDAMENTAL_KEYS + ("tv_symbol",)


# Year-scale context a young series cannot support. When the primary source
# leaves these empty and the holding names a reference, they are computed from
# the reference's own history instead — entirely within that series, so a
# borrowed "12% off the 52-week high" is a true statement about the reference
# and never a comparison across two price scales.
#
# Deliberately NOT borrowed: price, %1D, gaps, RS and the 20/50SMA. A venue
# market has enough bars for those, and they describe the contract actually
# being traded. Borrowing them would make the SMA arrows disagree with the
# user's own chart.
_REF_METRIC_KEYS = ("pct_ytd", "pct_1y", "pct_off_high", "new_52w")
_REF_FUNDAMENTAL_KEYS = ("name", "sector", "market_cap", "pe", "ps", "earnings_date")


def _fill_from_ref(row, ref_hist, ref_info, ref_symbol, rates):
    """Fill the gaps a young primary series leaves, from the reference.

    Only ever fills — a value the primary produced is never replaced, so a
    market stops borrowing on its own once it has accrued enough history.
    """
    borrowed = row.setdefault("borrowed", {})

    for key in _REF_FUNDAMENTAL_KEYS:
        if row.get(key) is not None or ref_info.get(key) is None:
            continue
        value = ref_info[key]
        if key == "market_cap":
            value = fx.to_usd(value, ref_info.get("currency"), rates)
            if value is None:
                continue          # no rate: n/a beats a number in the wrong currency
        row[key] = value
        borrowed[key] = ref_symbol

    if ref_hist is None or not len(ref_hist):
        return
    close, high, low = ref_hist["Close"], ref_hist["High"], ref_hist["Low"]
    candidates = {
        "pct_ytd": lambda: metrics.pct_ytd(close),
        "pct_1y": lambda: metrics.pct_1y(close),
        "pct_off_high": lambda: metrics.pct_off_52w_high(close, high),
        "new_52w": lambda: metrics.new_52w_extreme(high, low),
    }
    for key in _REF_METRIC_KEYS:
        if row.get(key):          # spark is [] when absent, the rest are None
            continue
        value = candidates[key]()
        if value is None or value == []:
            continue
        row[key] = value
        borrowed[key] = ref_symbol

    # The column is headed "1Y", so a nine-month line drawn under it is the same
    # quiet mislabel the metric guards exist to prevent. pct_1y being borrowed
    # is exactly the signal that the native series is too short to be one.
    if "pct_1y" in borrowed:
        spark = metrics.sparkline(close)
        if spark:
            row["spark"] = spark
            borrowed["spark"] = ref_symbol

    # The 200SMA is the one window a venue series routinely cannot reach.
    if "200" not in row["sma"]:
        state = metrics.sma_state(close, 200)
        if state:
            row["sma"]["200"] = state
            borrowed["sma200"] = ref_symbol


def build_rows(hists, bench_close, infos, holdings, today, tv=None, rates=None):
    rates = rates or {}
    rows = []
    for holding in holdings:
        ticker = holding["ticker"]
        # Namespaced by source, so a Yahoo NVDA and a trade.xyz NVDA can both
        # be in flight in one run. Falls back for callers that predate it.
        key = holding.get("key") or ticker
        row = _empty_row(holding, infos.get(key) or {})
        hist = hists.get(key)
        prev_close = None
        if hist is not None and len(hist):
            close, high, low = hist["Close"], hist["High"], hist["Low"]
            clean_close = close.dropna()
            if len(clean_close):
                row["price"] = float(clean_close.iloc[-1])
            if len(clean_close) > 1:
                prev_close = float(clean_close.iloc[-2])
            row["pct_1d"] = metrics.pct_1d(close)
            row["pct_ytd"] = metrics.pct_ytd(close)
            row["pct_1y"] = metrics.pct_1y(close)
            row["spark"] = metrics.sparkline(close)
            row["pct_off_high"] = metrics.pct_off_52w_high(close, high)
            row["new_52w"] = metrics.new_52w_extreme(high, low)
            row["rs_1m"] = metrics.rs_pct(close, bench_close, 21)
            row["rs_3m"] = metrics.rs_pct(close, bench_close, 63)
            row["rs_bars"] = metrics.rs_series(close, bench_close, days=21)
            row["gap_pct"] = metrics.gap_pct(hist["Open"], close)
            row["rel_vol"] = metrics.rel_volume(hist["Volume"])
            row["atr_pct"] = metrics.atr_pct(high, low, close)
            for window in SMA_WINDOWS:
                state = metrics.sma_state(close, window)
                if state:
                    row["sma"][str(window)] = state
                cross = metrics.sma_cross(close, window)
                if cross:
                    row["sma_cross"][str(window)] = cross

        # A venue row takes only fundamentals from the screener, and only under
        # the equity it explicitly declares. Its prices are 24/7 perp marks —
        # overwriting them with a spot close would put two different instruments
        # in one row — and its symbol is the venue's, not a US ticker.
        ref_symbol = holding.get("ref")
        if holding.get("source", "yahoo") == "yahoo":
            tv_keys, tv_lookup = _TV_OVERRIDE_KEYS, ticker
        else:
            tv_keys, tv_lookup = _TV_FUNDAMENTAL_KEYS, ref_symbol
        tv_data = ((tv or {}).get(tv_lookup) or {}) if tv_lookup else {}
        for tv_key in tv_keys:
            if tv_data.get(tv_key) is not None:
                row[tv_key] = tv_data[tv_key]

        # The screener is US-only, so it has nothing for 285A.T or 005930.KS.
        # Yahoo does, and it also carries the year-scale history the venue's
        # young series can't provide.
        if ref_symbol and ref_symbol != key:
            _fill_from_ref(row, hists.get(ref_symbol), infos.get(ref_symbol) or {},
                           ref_symbol, rates)
        if holding.get("name"):
            row["name"] = holding["name"]
        if holding.get("tv_symbol"):
            row["tv_symbol"] = holding["tv_symbol"]

        if holding.get("shares") and row["price"] is not None:
            row["position"] = metrics.position_metrics(
                row["price"], prev_close, holding["shares"], holding.get("cost_basis"))
        rows.append(row)

    for row, rank in zip(rows, metrics.ranks([r["rs_1m"] for r in rows])):
        row["rs_rank"] = rank

    positioned = [r for r in rows if r["position"]]
    summary = metrics.portfolio_summary([r["position"] for r in positioned])
    if summary:
        for row, weight in zip(positioned, summary["weights"]):
            row["position"]["weight_pct"] = weight
    return rows, summary
