"""Assemble render-ready row dicts from fetched data. Pure given inputs."""

from . import metrics

SMA_WINDOWS = (20, 50, 200)

# Yahoo exchange code → TradingView exchange prefix
_TV_EXCHANGE = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
                "NYQ": "NYSE", "ASE": "AMEX", "PCX": "AMEX"}


def tv_symbol(ticker, exchange, override=None):
    if override:
        return override
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
        "tv_symbol": tv_symbol(holding["ticker"], info.get("exchange"), holding.get("tv_symbol")),
        "price": None, "pct_1d": None, "pct_ytd": None, "pct_1y": None,
        "spark": [], "pct_off_high": None, "new_52w": None,
        "rs_1m": None, "rs_3m": None, "rs_bars": [], "rs_rank": None,
        "sma": {}, "sma_cross": {}, "gap_pct": None,
        "rel_vol": None, "atr_pct": None,
        "position": None,
    }


# snapshot fields the TradingView screener may override (history-derived
# series — spark, RS, SMA state, gaps — always stay Yahoo-based)
_TV_OVERRIDE_KEYS = ("name", "sector", "price", "pct_1d", "market_cap", "pe", "ps",
                     "pct_ytd", "pct_off_high", "atr_pct", "rel_vol", "earnings_date",
                     "tv_symbol")


def build_rows(hists, bench_close, infos, holdings, today, tv=None):
    rows = []
    for holding in holdings:
        ticker = holding["ticker"]
        row = _empty_row(holding, infos.get(ticker) or {})
        hist = hists.get(ticker)
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

        tv_data = (tv or {}).get(ticker) or {}
        for key in _TV_OVERRIDE_KEYS:
            if tv_data.get(key) is not None:
                row[key] = tv_data[key]
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
