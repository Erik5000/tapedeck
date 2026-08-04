"""Self-contained HTML dashboard renderer. No CDN, no external assets
(except the on-demand TradingView chart panels)."""

import html as h
from datetime import date

# ---------- formatting ----------

def fmt_cap(v):
    if v is None:
        return "n/a"
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= div:
            num = f"{v / div:.1f}".rstrip("0").rstrip(".")
            return f"${num}{suffix}"
    return f"${v:,.0f}"


def fmt_pct(v, dec=2):
    return "n/a" if v is None else f"{v:+.{dec}f}%"


def fmt_price(v):
    return "n/a" if v is None else f"${v:,.2f}"


def fmt_num(v, dec=2):
    return "n/a" if v is None else f"{v:.{dec}f}"


def fmt_money(v):
    return "n/a" if v is None else f"{'+' if v > 0 else ''}${v:,.0f}".replace("$-", "-$")


def heat_alpha(v, cap):
    if not v:
        return 0.0
    return min(abs(v) / cap, 1.0) ** 0.6 * 0.42


# ---------- mini-viz (inline SVG) ----------

def spark_svg(points, positive, w=110, ht=26):
    if not points or len(points) < 2:
        return '<span class="na">n/a</span>'
    lo, hi = min(points), max(points)
    rng = (hi - lo) or 1.0
    pad, n = 2, len(points)
    xs = [pad + i * (w - 2 * pad) / (n - 1) for i in range(n)]
    ys = [ht - pad - (p - lo) * (ht - 2 * pad) / rng for p in points]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{pad},{ht - pad} {pts} {xs[-1]:.1f},{ht - pad}"
    cls = "up" if positive else "down"
    return (f'<svg class="spark {cls}" width="{w}" height="{ht}" viewBox="0 0 {w} {ht}" aria-hidden="true">'
            f'<polygon class="fill" points="{area}"></polygon>'
            f'<polyline class="line" points="{pts}"></polyline>'
            f'<circle class="dot" cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="2"></circle></svg>')


def rs_svg(values, w=66, ht=24):
    if not values:
        return '<span class="na">n/a</span>'
    peak = max(abs(v) for v in values) or 1.0
    mid = ht / 2
    slot = w / len(values)
    rects = []
    for i, v in enumerate(values):
        bar_h = max(abs(v) / peak * (mid - 1), 0.6)
        y = mid - bar_h if v >= 0 else mid
        cls = "up" if v >= 0 else "down"
        rects.append(f'<rect class="{cls}" x="{i * slot + 0.4:.1f}" y="{y:.1f}" '
                     f'width="{max(slot - 1.2, 0.8):.1f}" height="{bar_h:.1f}"></rect>')
    return (f'<svg class="rsbars" width="{w}" height="{ht}" viewBox="0 0 {w} {ht}" aria-hidden="true">'
            f'<line class="base" x1="0" y1="{mid}" x2="{w}" y2="{mid}"></line>{"".join(rects)}</svg>')


def offhigh_cell(v, max_off):
    if v is None:
        return '<span class="na">n/a</span>'
    depth = min(abs(v) / (max_off or 1.0), 1.0)
    return (f'<div class="offwrap"><div class="offtrack">'
            f'<div class="offbar" style="width:{depth * 100:.0f}%;opacity:{0.35 + 0.55 * depth:.2f}"></div></div>'
            f'<span class="num">{fmt_pct(v)}</span></div>')


# ---------- columns ----------

CORE, EXT, POS, VWAP = "", "c-ext", "c-pos", "c-vwap"

COLUMNS = [
    {"key": "ticker",   "label": "Ticker",     "cls": CORE, "align": "l"},
    {"key": "name",     "label": "Company",    "cls": CORE, "align": "l"},
    {"key": "price",    "label": "Price",      "cls": CORE, "align": "r"},
    {"key": "pct_1d",   "label": "% 1D",       "cls": CORE, "align": "r"},
    {"key": "market_cap", "label": "Mkt Cap",  "cls": CORE, "align": "r"},
    {"key": "ps",       "label": "P/S",        "cls": CORE, "align": "r"},
    {"key": "pe",       "label": "P/E",        "cls": CORE, "align": "r"},
    {"key": "pct_ytd",  "label": "% YTD",      "cls": CORE, "align": "r"},
    {"key": "spark",    "label": "1Y",         "cls": CORE, "align": "c"},
    {"key": "off_high", "label": "Δ 52w High", "cls": CORE, "align": "r"},
    {"key": "rs",       "label": "RS 1M",      "cls": CORE, "align": "c"},
    {"key": "sma20",    "label": "20SMA",      "cls": CORE, "align": "c"},
    {"key": "sma50",    "label": "50SMA",      "cls": CORE, "align": "c"},
    {"key": "sma200",   "label": "200SMA",     "cls": CORE, "align": "c"},
    {"key": "rs_1m",    "label": "RS1M %",     "cls": EXT,  "align": "r"},
    {"key": "rs_3m",    "label": "RS3M %",     "cls": EXT,  "align": "r"},
    {"key": "d20",      "label": "→20",        "cls": EXT,  "align": "r"},
    {"key": "d50",      "label": "→50",        "cls": EXT,  "align": "r"},
    {"key": "d200",     "label": "→200",       "cls": EXT,  "align": "r"},
    {"key": "rel_vol",  "label": "RVol",       "cls": EXT,  "align": "r"},
    {"key": "atr",      "label": "ATR%",       "cls": EXT,  "align": "r"},
    {"key": "earnings", "label": "Earnings",   "cls": EXT,  "align": "l"},
    {"key": "sector",   "label": "Sector",     "cls": EXT,  "align": "l"},
    {"key": "mkt_val",  "label": "Mkt Val",    "cls": POS,  "align": "r"},
    {"key": "weight",   "label": "Wt%",        "cls": POS,  "align": "r"},
    {"key": "day_pnl",  "label": "Day P&L",    "cls": POS,  "align": "r"},
    {"key": "open_pnl", "label": "Open P&L",   "cls": POS,  "align": "r"},
    {"key": "vwap_level", "label": "VWAP",     "cls": VWAP, "align": "l"},
    {"key": "vwap_dist",  "label": "→VWAP",    "cls": VWAP, "align": "r"},
    {"key": "vwap_z",     "label": "σ",        "cls": VWAP, "align": "r"},
    {"key": "vwap_score", "label": "Score",    "cls": VWAP, "align": "r"},
]


def _td(content, col, v=None, extra_cls="", style=""):
    cls = " ".join(c for c in (col["cls"], f'a-{col["align"]}', extra_cls) if c)
    attrs = f' class="{cls}"'
    if v is not None:
        attrs += f' data-v="{h.escape(str(v))}"'
    if style:
        attrs += f' style="{style}"'
    return f"<td{attrs}>{content}</td>"


def _sma_arrow(row, window, col):
    state = (row.get("sma") or {}).get(window)
    if not state:
        return _td('<span class="na">·</span>', col, v="")
    up = state["above"]
    arrow = "▲" if up else "▼"
    title = f'{window}SMA {fmt_price(state["sma"])} · dist {fmt_pct(state["dist_pct"])}'
    return _td(f'<span class="tri {"up" if up else "down"}" title="{h.escape(title)}">{arrow}</span>',
               col, v=round(state["dist_pct"], 2))


def _earnings_cell(row, col, today):
    iso = row.get("earnings_date")
    if not iso:
        return _td('<span class="na">n/a</span>', col, v="")
    d = date.fromisoformat(iso)
    label = d.strftime("%b %d")
    days = (d - today).days
    soon = 0 <= days <= 7
    content = f'<span class="{"earn-soon" if soon else ""}">{label}{f" ⚠{days}d" if soon else ""}</span>'
    return _td(content, col, v=iso)


def _pnl_cell(v, col, pct=None):
    if v is None:
        return _td('<span class="na">–</span>', col, v="")
    cls = "up" if v > 0 else ("down" if v < 0 else "")
    suffix = f' <span class="sub">({fmt_pct(pct, 1)})</span>' if pct is not None else ""
    return _td(f'<span class="num {cls}">{fmt_money(v)}</span>{suffix}', col, v=round(v, 2))


def _cell(row, col, ctx):
    key = col["key"]
    if key == "ticker":
        group = f'<span class="group">{h.escape(row["group"])}</span>' if row.get("group") else ""
        return _td(f'<span class="caret"></span><span class="tick">{h.escape(row["ticker"])}</span>{group}',
                   col, v=row["ticker"])
    if key == "name":
        return _td(f'<span class="cname">{h.escape(str(row["name"]))}</span>', col, v=str(row["name"]))
    if key == "price":
        return _td(f'<span class="num">{fmt_price(row["price"])}</span>', col, v=row["price"] or "")
    if key == "pct_1d":
        v = row["pct_1d"]
        alpha = heat_alpha(v, cap=10)
        cls = "heat-up" if (v or 0) >= 0 else "heat-down"
        return _td(f'<span class="num">{fmt_pct(v)}</span>', col, v="" if v is None else round(v, 2),
                   extra_cls=cls if v is not None else "", style=f"--a:{alpha:.2f}" if alpha else "")
    if key == "market_cap":
        return _td(f'<span class="num">{fmt_cap(row["market_cap"])}</span>', col, v=row["market_cap"] or "")
    if key == "ps":
        v = row["ps"]
        alpha = 0.0 if v is None else min(v / 30, 1.0) * 0.4
        return _td(f'<span class="num">{fmt_num(v)}</span>', col, v="" if v is None else round(v, 2),
                   extra_cls="heat-val" if v is not None else "", style=f"--a:{alpha:.2f}" if alpha else "")
    if key == "pe":
        return _td(f'<span class="num">{fmt_num(row["pe"])}</span>', col, v="" if row["pe"] is None else round(row["pe"], 2))
    if key == "pct_ytd":
        v = row["pct_ytd"]
        alpha = heat_alpha(v, cap=150)
        cls = "heat-up" if (v or 0) >= 0 else "heat-down"
        return _td(f'<span class="num">{fmt_pct(v)}</span>', col, v="" if v is None else round(v, 2),
                   extra_cls=cls if v is not None else "", style=f"--a:{alpha:.2f}" if alpha else "")
    if key == "spark":
        title = f'1Y {fmt_pct(row["pct_1y"])}'
        return _td(f'<span title="{h.escape(title)}">{spark_svg(row["spark"], (row["pct_1y"] or 0) >= 0)}</span>',
                   col, v="" if row["pct_1y"] is None else round(row["pct_1y"], 2))
    if key == "off_high":
        v = row["pct_off_high"]
        return _td(offhigh_cell(v, ctx["max_off"]), col, v="" if v is None else round(v, 2))
    if key == "rs":
        rank = row.get("rs_rank")
        badge = f'<span class="rank" title="RS 1M rank {rank}/{ctx["n"]}">#{rank}</span>' if rank else ""
        title = f'RS vs {ctx["bench"]} 1M {fmt_pct(row["rs_1m"])}'
        return _td(f'<span title="{h.escape(title)}">{rs_svg(row["rs_bars"])}</span>{badge}',
                   col, v="" if row["rs_1m"] is None else round(row["rs_1m"], 2))
    if key in ("sma20", "sma50", "sma200"):
        return _sma_arrow(row, key[3:], col)
    if key in ("rs_1m", "rs_3m"):
        v = row[key]
        cls = "up" if (v or 0) > 0 else ("down" if (v or 0) < 0 else "")
        return _td(f'<span class="num {cls}">{fmt_pct(v, 1)}</span>', col, v="" if v is None else round(v, 2))
    if key in ("d20", "d50", "d200"):
        state = (row.get("sma") or {}).get(key[1:])
        v = state["dist_pct"] if state else None
        cls = "up" if (v or 0) > 0 else ("down" if (v or 0) < 0 else "")
        return _td(f'<span class="num {cls}">{fmt_pct(v, 1)}</span>', col, v="" if v is None else round(v, 2))
    if key == "rel_vol":
        v = row["rel_vol"]
        hot = v is not None and v >= 2
        return _td(f'<span class="num{" earn-soon" if hot else ""}">{fmt_num(v, 1)}{"×" if v is not None else ""}</span>',
                   col, v="" if v is None else round(v, 2))
    if key == "atr":
        return _td(f'<span class="num">{fmt_num(row["atr_pct"], 1)}</span>', col,
                   v="" if row["atr_pct"] is None else round(row["atr_pct"], 2))
    if key == "earnings":
        return _earnings_cell(row, col, ctx["today"])
    if key == "sector":
        return _td(h.escape(row["sector"]) if row.get("sector") else '<span class="na">n/a</span>',
                   col, v=row.get("sector") or "")
    pos = row.get("position") or {}
    if key == "mkt_val":
        v = pos.get("market_value")
        return _td(f'<span class="num">{fmt_money(v) if v is not None else "–"}</span>', col, v=v or "")
    if key == "weight":
        v = pos.get("weight_pct")
        return _td(f'<span class="num">{fmt_num(v, 1) + "%" if v is not None else "–"}</span>', col, v=v or "")
    if key == "day_pnl":
        return _pnl_cell(pos.get("day_pnl"), col)
    if key == "open_pnl":
        return _pnl_cell(pos.get("open_pnl"), col, pct=pos.get("open_pnl_pct"))
    if key.startswith("vwap_"):
        vwap = row.get("vwap")
        if not vwap:
            return _td("", col)
        nearest = vwap["nearest"]
        if key == "vwap_level":
            name = nearest.get("name")
            cls = "good" if nearest["in_range"] else ""
            content = h.escape(name) if name else "n/a"
            return _td(content, col, v=name or "", extra_cls=cls)
        if key == "vwap_dist":
            pct = nearest["pct_distance"]
            style = f"background:rgba(56,161,105,{heat_alpha(pct, 5.0):.3f})" if nearest["in_range"] else ""
            return _td(fmt_pct(pct, 1), col, v=pct, style=style)
        if key == "vwap_z":
            return _td(fmt_num(nearest["z_stretch"], 2), col, v=nearest["z_stretch"])
        if key == "vwap_score":
            return _td(fmt_num(vwap["score"], 2), col, v=vwap["score"])
    raise KeyError(key)


TV_TIMEFRAMES = (("12H", "720"), ("4H", "240"), ("1H", "60"))


def _detail_row(row, ncols):
    symbol = row.get("tv_symbol") or row["ticker"]
    charts = "".join(
        f'<div class="tvchart"><div class="tvlabel">{label} · {h.escape(symbol)}</div>'
        f'<div class="tvbox" data-tf="{tf}"></div></div>'
        for label, tf in TV_TIMEFRAMES)
    return (f'<tr class="detail" data-for="{h.escape(row["ticker"])}" hidden>'
            f'<td colspan="{ncols}"><div class="tvpanel" data-symbol="{h.escape(symbol)}">'
            f'<div class="tvhint">Loading TradingView charts…</div>'
            f'<div class="tvcharts">{charts}</div></div></td></tr>')


# ---------- page sections ----------

def _summary_tiles(summary, rows):
    if not summary:
        return ""
    mover = max((r for r in rows if r["pct_1d"] is not None),
                key=lambda r: abs(r["pct_1d"]), default=None)
    day = summary["day_pnl"]
    open_pnl = summary["open_pnl"]
    tiles = [
        ("Total Value", f'{fmt_money(summary["total_value"]).lstrip("+")}', ""),
        ("Day P&L", f'{fmt_money(day)} <span class="sub">({fmt_pct(summary["day_pnl_pct"], 2)})</span>',
         "up" if day > 0 else ("down" if day < 0 else "")),
        ("Open P&L", fmt_money(open_pnl), "up" if open_pnl > 0 else ("down" if open_pnl < 0 else "")),
    ]
    if mover:
        tiles.append(("Biggest Mover", f'{h.escape(mover["ticker"])} <span class="num">{fmt_pct(mover["pct_1d"])}</span>',
                      "up" if mover["pct_1d"] >= 0 else "down"))
    html_tiles = "".join(
        f'<div class="tile"><div class="tlabel">{label}</div><div class="tvalue {cls}">{value}</div></div>'
        for label, value, cls in tiles)
    return f'<section class="tiles">{html_tiles}</section>'


_SEV_ICON = {"good": "▲", "bad": "▼", "warn": "⚠"}


def _alerts_html(alerts):
    if not alerts:
        return ""
    chips = "".join(
        f'<span class="chip {a["severity"]}">{_SEV_ICON.get(a["severity"], "•")} '
        f'<b>{h.escape(a["ticker"])}</b> {h.escape(a["text"])}</span>'
        for a in alerts)
    return f'<section class="panel"><span class="ptitle">Alerts</span>{chips}</section>'


def _diff_html(diff):
    if not diff:
        return ""
    chips = []
    for m in diff["movers"]:
        if abs(m["change_pct"]) < 0.05:
            continue
        cls = "good" if m["change_pct"] >= 0 else "bad"
        chips.append(f'<span class="chip {cls}"><b>{h.escape(m["ticker"])}</b> {fmt_pct(m["change_pct"])}</span>')
    for f in diff["sma_flips"]:
        cls = "good" if f["now"] == "above" else "bad"
        chips.append(f'<span class="chip {cls}"><b>{h.escape(f["ticker"])}</b> now {f["now"]} {f["window"]}SMA</span>')
    for t in diff["added"]:
        chips.append(f'<span class="chip"><b>{h.escape(t)}</b> added</span>')
    for t in diff["removed"]:
        chips.append(f'<span class="chip"><b>{h.escape(t)}</b> removed</span>')
    if not chips:
        chips.append('<span class="chip">no notable changes</span>')
    return (f'<section class="panel"><span class="ptitle">Since {h.escape(diff["since"])}</span>'
            f'{"".join(chips)}</section>')


def _cockpit_html(cockpit, fresh):
    """Read-only vault cockpit state panel. Empty string when no cockpit attached."""
    if not cockpit:
        return ""
    chips = []
    if cockpit.get("regime"):
        chips.append(f'<span class="chip"><b>REGIME</b> {h.escape(cockpit["regime"])}</span>')
    freeze = cockpit.get("freeze")
    if freeze:
        up = freeze.upper()
        cls = "good" if "LIFTED" in up else ("bad" if up.startswith(("FROZEN", "FULL", "ON")) else "warn")
        chips.append(f'<span class="chip {cls}"><b>FREEZE</b> {h.escape(freeze)}</span>')
    if fresh and fresh.get("regenerated"):
        age = fresh.get("age_days")
        cls = "warn" if age is not None and age > 9 else ""
        sub = f" ({age}d)" if age is not None else ""
        chips.append(f'<span class="chip {cls}">refreshed {h.escape(fresh["regenerated"])}{sub}</span>')
    for t in cockpit.get("triad") or []:
        status = (t.get("status") or "").lower()
        cls = "good" if "quiet" in status else ("warn" if "watch" in status else "bad")
        chips.append(f'<span class="chip {cls}"><b>{h.escape(t.get("leg") or "?")}</b> '
                     f'{h.escape(t.get("reading") or "")} · {h.escape(t.get("status") or "")}</span>')
    for d in cockpit.get("open_decisions") or []:
        chips.append(f'<span class="chip warn">#{d["id"]} {h.escape(d.get("title") or "")}</span>')

    table = ""
    if cockpit.get("sleeves"):
        body = []
        for s in cockpit["sleeves"]:
            fill = s.get("fill_status") or ""
            cls = "up" if fill.upper() == "STARTER-OK" else ("down" if fill.upper().startswith("FROZEN") else "")
            conf = s.get("conf")
            body.append(
                "<tr>"
                f'<td>{h.escape(s.get("position") or "")}</td>'
                f'<td>{h.escape(", ".join(s.get("tickers") or []))}</td>'
                f'<td class="a-r"><span class="num">{h.escape(s.get("size") or "")}</span></td>'
                f'<td class="{cls}">{h.escape(fill)}</td>'
                f'<td class="a-r"><span class="num">{conf if conf is not None else "n/a"}</span></td>'
                "</tr>")
        table = ('<table class="minitbl"><thead><tr><th>Sleeve</th><th>Tickers</th>'
                 '<th class="a-r">Size</th><th>Fill</th><th class="a-r">Conf</th></tr></thead>'
                 f'<tbody>{"".join(body)}</tbody></table>')
    return (f'<section class="panel pcol"><span class="ptitle">Cockpit</span>'
            f'<div class="chiprow">{"".join(chips)}</div>{table}</section>')


def _vwap_chip(fresh):
    """Age stamp for the VWAP feed. Empty string when no feed is attached."""
    if not fresh or not fresh.get("generated"):
        return ""
    age = fresh.get("age_days")
    cls = "warn" if fresh.get("stale") else ""
    sub = f" ({age}d)" if age is not None else ""
    return (f'<section class="panel"><span class="ptitle">VWAP</span>'
            f'<span class="chip {cls}">levels from {h.escape(fresh["generated"])}{sub}</span></section>')


def _baskets_html(baskets):
    """Cross-basket comparison table. Empty string below two baskets (nothing to compare)."""
    if len(baskets) < 2:
        return ""

    def pcell(v):
        if v is None:
            return '<td class="a-r"><span class="num">n/a</span></td>'
        cls = "up" if v >= 0 else "down"
        return f'<td class="a-r"><span class="num {cls}">{fmt_pct(v)}</span></td>'

    body = []
    for b in baskets:
        breadth = f'{b["breadth_sma50_pct"]:.0f}%' if b.get("breadth_sma50_pct") is not None else "n/a"
        off = fmt_pct(b.get("med_pct_off_high"), 1)
        anti = ' class="anti"' if b["group"] == "anti-basket" else ""
        body.append(
            f'<tr{anti}>'
            f'<td>{h.escape(b["group"])}</td>'
            f'<td class="a-r"><span class="num">{b["n"]}</span></td>'
            + pcell(b.get("avg_pct_1d")) + pcell(b.get("med_rs_1m")) + pcell(b.get("med_rs_3m"))
            + f'<td class="a-r"><span class="num">{breadth}</span></td>'
            + f'<td class="a-r"><span class="num">{off}</span></td>'
            "</tr>")
    return ('<section class="panel pcol"><span class="ptitle">Baskets</span>'
            '<table class="minitbl"><thead><tr><th>Basket</th><th class="a-r">N</th>'
            '<th class="a-r">Avg 1D</th><th class="a-r">Med RS 1M</th><th class="a-r">Med RS 3M</th>'
            '<th class="a-r">&gt;50SMA</th><th class="a-r">Med Δ52wH</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></section>')


def _averages_row(rows, has_pos, has_vwap):
    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    averages = {"pct_1d": fmt_pct(avg("pct_1d")), "ps": fmt_num(avg("ps")),
                "pe": fmt_num(avg("pe")), "pct_ytd": fmt_pct(avg("pct_ytd"))}
    cells = []
    for col in COLUMNS:
        if not has_pos and col["cls"] == POS:
            continue
        if not has_vwap and col["cls"] == VWAP:
            continue
        if col["key"] == "ticker":
            cells.append('<td class="a-l" colspan="2">Avg.</td>')
        elif col["key"] == "name":
            continue
        elif col["key"] in averages:
            cells.append(f'<td class="{col["cls"]} a-r"><span class="num">{averages[col["key"]]}</span></td>')
        else:
            cells.append(f'<td class="{col["cls"]}"></td>')
    return "<tr>" + "".join(cells) + "</tr>"


def _section_html(wl, today):
    rows_sorted = sorted(wl["rows"], key=lambda r: (r["pct_1d"] is None, -(r["pct_1d"] or 0)))
    has_pos = any(r.get("position") for r in rows_sorted)
    has_vwap = any(r.get("vwap") for r in rows_sorted)
    max_off = max((abs(r["pct_off_high"]) for r in rows_sorted if r["pct_off_high"] is not None), default=1.0)
    ctx = {"max_off": max_off, "today": today, "bench": wl["benchmark"], "n": len(rows_sorted)}

    cols = [c for c in COLUMNS
            if (has_pos or c["cls"] != POS) and (has_vwap or c["cls"] != VWAP)]
    head = "".join(
        f'<th class="{" ".join(x for x in (c["cls"], "a-" + c["align"], "sortable") if x)}" '
        f'data-key="{c["key"]}">{c["label"]}</th>'
        for c in cols)
    body = "\n".join(
        f'<tr class="mainrow" data-ticker="{h.escape(r["ticker"])}">'
        + "".join(_cell(r, c, ctx) for c in cols)
        + "</tr>\n" + _detail_row(r, len(cols))
        for r in rows_sorted)

    meta = (f'<div class="lmeta">{len(rows_sorted)} names · bench {h.escape(wl["benchmark"])}'
            f' · RS vs {h.escape(wl["benchmark"])}</div>')
    stale_cls = " vwap-stale" if (wl.get("vwap_fresh") or {}).get("stale") else ""
    section = (
        f'<section class="wl-section" data-wl="{h.escape(wl["name"])}">'
        + _summary_tiles(wl.get("summary"), rows_sorted)
        + _cockpit_html(wl.get("cockpit"), wl.get("cockpit_fresh"))
        + _baskets_html(wl.get("baskets") or [])
        + _vwap_chip(wl.get("vwap_fresh"))
        + _alerts_html(wl.get("alerts") or [])
        + _diff_html(wl.get("diff"))
        + meta
        + f'<div class="tablewrap"><table class="wltbl{stale_cls}">'
          f'<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody>'
          f'<tfoot>{_averages_row(rows_sorted, has_pos, has_vwap)}</tfoot></table></div>'
        + '</section>')
    return section, has_pos, has_vwap


def render_page(rows, summary, alerts, diff, today, benchmark, data_date=None):
    """Single-watchlist page (kept for --config single-file mode and tests)."""
    return render_multi([{"name": "main", "title": "Watchlist", "benchmark": benchmark,
                          "rows": rows, "summary": summary, "alerts": alerts, "diff": diff}],
                        today, data_date=data_date)


def render_multi(lists, today, data_date=None):
    sections, any_pos, any_vwap = [], False, False
    for wl in lists:
        section, has_pos, has_vwap = _section_html(wl, today)
        sections.append(section)
        any_pos = any_pos or has_pos
        any_vwap = any_vwap or has_vwap

    tabs_html = ""
    if len(lists) > 1:
        tabs_html = '<nav class="wltabs">' + "".join(
            f'<button class="wtab" data-wl="{h.escape(w["name"])}">{h.escape(w["title"])}</button>'
            for w in lists) + "</nav>"

    subtitle = lists[0]["title"] if len(lists) == 1 else f"{len(lists)} watchlists"
    pos_btn = '<button id="posbtn" class="tbtn">Positions</button>' if any_pos else ""
    vwap_btn = '<button id="vwapbtn" class="tbtn">VWAP</button>' if any_vwap else ""
    date_label = today.strftime("%B %d, %Y")
    data_note = f' · last close {data_date}' if data_date else ""
    sections_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TAPEDECK — Watchlists</title>
<link rel="icon" href='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">📼</text></svg>'>
<style>
:root {{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,.10);
  --up:#006300; --down:#d03b3b; --warn-ink:#7a5200;
  --up-rgb:12,163,12; --down-rgb:208,59,59; --val-rgb:237,161,0;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --up:#0ca30c; --down:#d03b3b; --warn-ink:#fab219;
    --up-rgb:12,163,12; --down-rgb:208,59,59; --val-rgb:201,133,0;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,.10);
  --up:#0ca30c; --down:#d03b3b; --warn-ink:#fab219;
  --up-rgb:12,163,12; --down-rgb:208,59,59; --val-rgb:201,133,0;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; padding:20px 24px 32px; background:var(--page); color:var(--ink);
  font:13px/1.45 ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}}
.wrap {{ max-width:2000px; margin:0 auto; }}
header {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:10px; }}
h1 {{ font-size:22px; margin:0; letter-spacing:.5px; }}
h1 .brand {{ font-weight:800; }}
.subtitle {{ color:var(--ink2); }}
.hdate {{ margin-left:auto; color:var(--muted); }}
.wltabs {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
.wtab {{
  font:inherit; font-size:13px; color:var(--ink2); background:var(--surface);
  border:1px solid var(--border); border-radius:8px; padding:5px 14px; cursor:pointer;
}}
.wtab.on {{ color:var(--ink); border-color:var(--ink2); font-weight:800; }}
.controls {{ display:flex; gap:8px; align-items:center; margin:0 0 10px; }}
.tbtn {{
  font:inherit; font-size:12px; color:var(--ink2); background:var(--surface);
  border:1px solid var(--border); border-radius:6px; padding:3px 10px; cursor:pointer;
}}
.tbtn.on {{ color:var(--ink); border-color:var(--ink2); font-weight:700; }}
.hint {{ color:var(--muted); font-size:11px; margin-left:auto; }}
.lmeta {{ color:var(--muted); font-size:11px; margin:0 0 6px 2px; }}
.tiles {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
.tile {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:8px 14px; min-width:150px; }}
.tlabel {{ font-size:11px; color:var(--muted); }}
.tvalue {{ font-size:17px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tvalue .sub {{ font-size:12px; font-weight:400; color:var(--ink2); }}
.panel {{ background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:6px 10px; margin-bottom:10px; display:flex; gap:6px; flex-wrap:wrap; align-items:center; }}
.ptitle {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; margin-right:4px; }}
.chip {{ font-size:12px; border:1px solid var(--border); border-radius:99px; padding:1px 9px; white-space:nowrap; }}
.chip.good {{ color:var(--up); background:rgba(var(--up-rgb),.08); }}
.chip.bad {{ color:var(--down); background:rgba(var(--down-rgb),.08); }}
.chip.warn {{ color:var(--warn-ink); background:rgba(var(--val-rgb),.12); }}
.panel.pcol {{ display:block; }}
.panel.pcol .chiprow {{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin:4px 0 4px; }}
.minitbl {{ border-collapse:collapse; font-size:12px; font-variant-numeric:tabular-nums; margin:2px 0; }}
.minitbl thead th {{ position:static; cursor:default; font-size:10px; color:var(--muted); text-align:left; }}
.minitbl th.a-r, .minitbl td.a-r {{ text-align:right; }}
.minitbl td {{ padding:2px 9px; }}
.minitbl tr.anti td {{ border-top:2px solid var(--border); }}
.tablewrap {{ overflow-x:auto; background:var(--surface); border:1px solid var(--border); border-radius:10px; }}
table.wltbl {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
th, td {{ padding:4px 9px; white-space:nowrap; }}
thead th {{
  position:sticky; top:0; background:var(--surface); z-index:2;
  font-size:11px; color:var(--ink2); font-weight:700; text-align:right;
  border-bottom:1px solid var(--grid); cursor:pointer; user-select:none;
}}
thead th.a-l {{ text-align:left; }} thead th.a-c {{ text-align:center; }}
thead th:hover {{ color:var(--ink); }}
th.s-desc::after {{ content:" ▾"; }} th.s-asc::after {{ content:" ▴"; }}
tbody td {{ border-bottom:1px solid var(--grid); }}
tbody tr:last-child td {{ border-bottom:none; }}
tbody tr.mainrow:hover td {{ background:rgba(137,135,129,.08); }}
tfoot td {{ border-top:1px solid var(--grid); color:var(--ink2); font-size:12px; padding:5px 9px; }}
.a-r {{ text-align:right; }} .a-c {{ text-align:center; }} .a-l {{ text-align:left; }}
.num {{ font-variant-numeric:tabular-nums; }}
.na {{ color:var(--muted); }}
.sub {{ color:var(--ink2); font-size:11px; }}
.tick {{ font-weight:800; }}
.group {{ display:block; font-size:9px; color:var(--muted); line-height:1; }}
.cname {{ color:var(--ink2); max-width:230px; overflow:hidden; text-overflow:ellipsis; display:inline-block; vertical-align:bottom; }}
.up {{ color:var(--up); }} .down {{ color:var(--down); }}
.heat-up {{ background:rgba(var(--up-rgb), var(--a,0)); }}
.heat-down {{ background:rgba(var(--down-rgb), var(--a,0)); }}
.heat-val {{ background:rgba(var(--val-rgb), var(--a,0)); }}
.earn-soon {{ color:var(--warn-ink); font-weight:700; }}
.tri {{ font-size:11px; }}
.rank {{ font-size:10px; color:var(--ink2); border:1px solid var(--border); border-radius:4px; padding:0 3px; margin-left:4px; vertical-align:middle; }}
.spark .line {{ fill:none; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }}
.spark.up .line {{ stroke:var(--up); }} .spark.down .line {{ stroke:var(--down); }}
.spark.up .fill {{ fill:var(--up); opacity:.08; }} .spark.down .fill {{ fill:var(--down); opacity:.08; }}
.spark.up .dot {{ fill:var(--up); }} .spark.down .dot {{ fill:var(--down); }}
.rsbars rect.up {{ fill:var(--up); opacity:.75; }}
.rsbars rect.down {{ fill:var(--down); opacity:.75; }}
.rsbars .base {{ stroke:var(--grid); stroke-width:1; }}
.offwrap {{ display:flex; align-items:center; gap:7px; justify-content:flex-end; }}
.offtrack {{ width:64px; height:9px; background:rgba(137,135,129,.12); border-radius:2px; overflow:hidden; }}
.offbar {{ height:100%; background:var(--down); border-radius:2px 0 0 2px; }}
tr.mainrow {{ cursor:pointer; }}
tr.mainrow.open td {{ background:rgba(137,135,129,.10); }}
.caret {{ display:inline-block; width:11px; color:var(--muted); font-size:9px; }}
.caret::before {{ content:"▸"; }}
tr.mainrow.open .caret::before {{ content:"▾"; }}
tr.detail > td {{ padding:0; background:var(--page); border-bottom:1px solid var(--grid); }}
.tvpanel {{ padding:10px 12px 14px; }}
.tvhint {{ color:var(--muted); font-size:12px; padding:4px 0 8px; }}
.tvcharts {{ display:flex; gap:10px; flex-wrap:wrap; }}
.tvchart {{ flex:1 1 380px; min-width:340px; }}
.tvlabel {{ font-size:11px; color:var(--muted); margin-bottom:4px; }}
.tvbox {{ height:440px; }}
footer {{ margin-top:10px; color:var(--muted); font-size:11px; display:flex; gap:14px; flex-wrap:wrap; }}
footer .leg {{ white-space:nowrap; }}
@media print {{ .controls, .hint, .wltabs {{ display:none; }} }}
table.wltbl:not(.show-ext) .c-ext {{ display:none; }}
table.wltbl:not(.show-pos) .c-pos {{ display:none; }}
table.wltbl:not(.show-vwap) .c-vwap {{ display:none; }}
.vwap-stale {{ opacity: .55; }}
.c-vwap.good {{ color:var(--up); background:rgba(var(--up-rgb),.08); }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1><span class="brand">TAPEDECK</span></h1>
  <span class="subtitle">{h.escape(subtitle)}</span>
  <span class="hdate">{date_label}{data_note}</span>
</header>
{tabs_html}
<div class="controls">
  <button id="extbtn" class="tbtn">Extended</button>
  {pos_btn}
  {vwap_btn}
  <button id="themebtn" class="tbtn">Theme: auto</button>
  <span class="hint">click a row for charts · click a column header to sort · hover cells for detail</span>
</div>
{sections_html}
<footer>
  <span class="leg"><span class="up">▲ green = up / above</span> · <span class="down">▼ red = down / below</span> (sign always printed)</span>
  <span class="leg">YTD per TradingView · data: TradingView screener + Yahoo daily history</span>
  <span class="leg">inspired by @speculator_io · generated by tapedeck</span>
</footer>
</div>
<script>
(function() {{
  document.querySelectorAll('th.sortable').forEach(function(th) {{
    th.addEventListener('click', function() {{
      var table = th.closest('table');
      var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
      var dir = th.dataset.dir === 'desc' ? 'asc' : 'desc';
      table.querySelectorAll('th.sortable').forEach(function(x) {{
        delete x.dataset.dir; x.classList.remove('s-asc', 's-desc');
      }});
      th.dataset.dir = dir;
      th.classList.add(dir === 'desc' ? 's-desc' : 's-asc');
      var tbody = table.tBodies[0];
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr.mainrow'));
      function val(r) {{
        var v = r.cells[idx].dataset.v;
        if (v === undefined || v === '') return null;
        var n = parseFloat(v);
        return isNaN(n) ? v : n;
      }}
      rows.sort(function(a, b) {{
        var va = val(a), vb = val(b);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        if (typeof va === 'string' || typeof vb === 'string') {{
          return dir === 'desc' ? String(vb).localeCompare(String(va)) : String(va).localeCompare(String(vb));
        }}
        return dir === 'desc' ? vb - va : va - vb;
      }});
      rows.forEach(function(r) {{
        tbody.appendChild(r);
        var det = tbody.querySelector('tr.detail[data-for="' + r.dataset.ticker + '"]');
        if (det) tbody.appendChild(det);
      }});
    }});
  }});

  function wireToggle(id, cls) {{
    var btn = document.getElementById(id);
    if (!btn) return;
    btn.addEventListener('click', function() {{
      var on = btn.classList.toggle('on');
      document.querySelectorAll('table.wltbl').forEach(function(t) {{
        t.classList.toggle(cls, on);
      }});
    }});
  }}
  wireToggle('extbtn', 'show-ext');
  wireToggle('posbtn', 'show-pos');
  wireToggle('vwapbtn', 'show-vwap');

  // --- watchlist tabs ---
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.wtab'));
  var wlSections = Array.prototype.slice.call(document.querySelectorAll('.wl-section'));
  function showWl(name) {{
    wlSections.forEach(function(s) {{ s.style.display = (s.dataset.wl === name) ? '' : 'none'; }});
    tabs.forEach(function(b) {{ b.classList.toggle('on', b.dataset.wl === name); }});
    localStorage.setItem('tapedeck-wl', name);
  }}
  if (tabs.length) {{
    tabs.forEach(function(b) {{
      b.addEventListener('click', function() {{ showWl(b.dataset.wl); }});
    }});
    var names = wlSections.map(function(s) {{ return s.dataset.wl; }});
    var savedWl = localStorage.getItem('tapedeck-wl');
    showWl(names.indexOf(savedWl) >= 0 ? savedWl : names[0]);
  }}

  // --- expandable TradingView chart rows (lazy: script + widgets load on first expand) ---
  var tvScript = null;
  function ensureTv() {{
    if (!tvScript) {{
      tvScript = new Promise(function(resolve, reject) {{
        var s = document.createElement('script');
        s.src = 'https://s3.tradingview.com/tv.js';
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      }});
    }}
    return tvScript;
  }}
  function isDark() {{
    var t = document.documentElement.dataset.theme;
    if (t) return t === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }}
  var tvUid = 0;
  function buildCharts(panel) {{
    if (panel.dataset.built) return;
    panel.dataset.built = '1';
    var hint = panel.querySelector('.tvhint');
    ensureTv().then(function() {{
      if (hint) hint.remove();
      panel.querySelectorAll('.tvbox').forEach(function(box) {{
        box.id = 'tvbox_' + (++tvUid);
        new TradingView.widget({{
          container_id: box.id,
          autosize: true,
          symbol: panel.dataset.symbol,
          interval: box.dataset.tf,
          timezone: 'Europe/Berlin',
          theme: isDark() ? 'dark' : 'light',
          style: '1',
          locale: 'en',
          hide_side_toolbar: true,
          allow_symbol_change: false,
          withdateranges: false,
          save_image: false
        }});
      }});
    }}).catch(function() {{
      if (hint) hint.textContent = 'TradingView charts unavailable (no internet connection?)';
    }});
  }}
  document.querySelectorAll('tr.mainrow').forEach(function(tr) {{
    tr.addEventListener('click', function() {{
      if (String(window.getSelection())) return;  // don't toggle while selecting text
      var det = tr.closest('tbody').querySelector('tr.detail[data-for="' + tr.dataset.ticker + '"]');
      if (!det) return;
      det.hidden = !det.hidden;
      tr.classList.toggle('open', !det.hidden);
      if (!det.hidden) buildCharts(det.querySelector('.tvpanel'));
    }});
  }});

  var themebtn = document.getElementById('themebtn');
  var modes = ['auto', 'light', 'dark'];
  var saved = localStorage.getItem('tapedeck-theme') || 'auto';
  function applyTheme(mode) {{
    if (mode === 'auto') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = mode;
    themebtn.textContent = 'Theme: ' + mode;
    document.querySelectorAll('.tvpanel[data-built]').forEach(function(panel) {{
      delete panel.dataset.built;
      panel.querySelectorAll('.tvbox').forEach(function(box) {{ box.innerHTML = ''; }});
      var det = panel.closest('tr.detail');
      if (det && !det.hidden) buildCharts(panel);
    }});
  }}
  applyTheme(saved);
  themebtn.addEventListener('click', function() {{
    saved = modes[(modes.indexOf(saved) + 1) % modes.length];
    localStorage.setItem('tapedeck-theme', saved);
    applyTheme(saved);
  }});
}})();
</script>
</body>
</html>
"""
