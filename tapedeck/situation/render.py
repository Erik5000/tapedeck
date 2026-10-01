"""HTML for the Situation tab. Pure: the build_situation dict in, a string out.

The section reuses the page's own classes (panel, panelgrid, minitbl, chip),
so it follows the light/dark tokens and the narrow-window stacking for free.
"""

import html as h

# A watchlist file starting with "_" is ignored (config.load_watchlists), so no
# watchlist can ever take this tab name.
TAB_NAME = "_situation"
TAB_TITLE = "Situation"

_ICON = {"fired": "●", "quiet": "○", "disabled": "○"}
_CHIP = {"fired": "warn", "quiet": "", "disabled": "off"}
_DECIMALS = {"%": 2, "bp": 0, "$": 2, "bp/1%": 2}


def _value(leg):
    v = leg["value"]
    if v is None:
        return "—"
    text = f"{v:.{_DECIMALS.get(leg['unit'], 2)}f}"
    return text + ("%" if leg["unit"] == "%" else "")


def _chg(leg):
    c = leg["chg20"]
    if c is None:
        return "—"
    unit = leg["chg_unit"]
    return f"{c:+.1f}%" if unit == "%" else (f"{c:+.2f}" if unit == "$" else f"{c:+.0f}bp")


def _z(leg):
    if leg["status"] == "no_data":
        return "no data"
    if leg["need"] and leg["z"] is None and leg["n"] < leg["need"]:
        return f"warming up ({leg['n']}/{leg['need']})"
    return "—" if leg["z"] is None else f"{leg['z']:+.1f}"


def _state(leg):
    words = [w for w in (leg["state"], "stale" if leg["status"] == "stale" else None,
                         "thin" if leg["thin"] else None) if w]
    return " · ".join(words)


def _leg_row(leg):
    note = leg.get("note")
    title = f' title="{h.escape(note)}"' if note else ""
    mark = " *" if note and leg["status"] != "no_data" else ""
    age = "" if leg["age_days"] is None else f"{leg['age_days']}d"
    return (f'<tr><td{title}>{h.escape(leg["label"])}{mark}</td>'
            f'<td>{h.escape(leg["src"] or "")}</td>'
            f'<td class="a-r">{_value(leg)}</td><td class="a-r">{_chg(leg)}</td>'
            f'<td class="a-r">{_z(leg)}</td><td>{h.escape(_state(leg))}</td>'
            f'<td class="a-r">{age}</td></tr>')


def _legs_panel(title, legs):
    head = ('<tr><th>Leg</th><th>Src</th><th class="a-r">Value</th><th class="a-r">Δ20d</th>'
            '<th class="a-r">z</th><th>State</th><th class="a-r">Age</th></tr>')
    body = "".join(_leg_row(leg) for leg in legs)
    return (f'<section class="panel pcol"><span class="ptitle">{h.escape(title)}</span>'
            f'<table class="minitbl"><thead>{head}</thead><tbody>{body}</tbody></table></section>')


def _crowd_row(row):
    if row["status"] == "no_data":
        cells = '<td class="a-r" colspan="5">no data</td>'
    else:
        fa, fz, oi, chg = row["funding_ann"], row["funding_z"], row["oi"], row["oi_chg_20d"]
        fz_text = (f"{fz:+.1f}" if fz is not None
                   else f"warming up ({row['funding_days']}/{row['funding_need']})")
        chg_text = (f"{chg:+.1f}%" if chg is not None
                    else f"warming up ({row['oi_days']}/{row['oi_need']} days)")
        cells = (f'<td class="a-r">{"—" if fa is None else f"{fa:+.1f}%"}</td>'
                 f'<td class="a-r">{fz_text}</td>'
                 f'<td class="a-r">{"—" if oi is None else f"{oi:,.0f}"}</td>'
                 f'<td class="a-r">{chg_text}</td><td>{h.escape(row["side"] or "")}</td>')
    thin = " · thin" if row["thin"] else ""
    return f'<tr><td>{h.escape(row["market"])}{thin}</td>{cells}</tr>'


def _crowding_panel(rows):
    head = ('<tr><th>Market</th><th class="a-r">Funding/yr</th><th class="a-r">z</th>'
            '<th class="a-r">OI</th><th class="a-r">OI Δ20d</th><th>Side</th></tr>')
    body = "".join(_crowd_row(r) for r in rows)
    return ('<section class="panel pcol"><span class="ptitle">Crowding (venue)</span>'
            f'<table class="minitbl"><thead>{head}</thead><tbody>{body}</tbody></table></section>')


def _alert_chip(alert):
    text = f'{_ICON[alert["state"]]} {h.escape(alert["label"])}'
    if alert["state"] == "disabled":
        text += f' — {h.escape(alert["detail"] or "")}'
    return (f'<span class="chip {_CHIP[alert["state"]]}" '
            f'title="{h.escape(alert["detail"] or "")}">{text}</span>')


def _conf(v):
    return "—" if v is None else str(v)


def _strip(sit):
    reg = sit.get("regime") or {}
    if reg.get("label"):
        split = (f'10Y {reg["d10"]:+.0f}bp/20d = real {reg["dreal"]:+.0f} · '
                 f'BE {reg["dbe"]:+.0f} · FRED {h.escape(reg["asof"])}')
        reg_html = f'<b>{h.escape(reg["label"])}</b> <span class="sitmuted">{split}</span>'
    else:
        reg_html = f'<span class="sitmuted">no label — {h.escape(reg.get("note") or "no data")}</span>'
    chips = "".join(_alert_chip(a) for a in sit.get("alerts") or [])
    notes = "".join(f'<div class="sitmuted">{h.escape(a["label"])}: {h.escape(a["note"])}</div>'
                    for a in sit.get("alerts") or [] if a.get("note"))
    conf = sit.get("confidence") or {}
    dates = f'data {h.escape(sit.get("venue_asof") or "—")} · FRED to {h.escape(sit.get("fred_asof") or "—")}'
    return ('<section class="panel pcol sitstrip"><span class="ptitle">Situation</span>'
            f'<div class="sitmuted">{dates}</div>'
            f'<div>Regime {reg_html}</div>'
            f'<div class="chiprow">Alerts {chips}</div>{notes}'
            f'<div>Confidence: Rates {_conf(conf.get("rates"))} · '
            f'Oil↔Rates {_conf(conf.get("oil"))}</div></section>')


def render_situation(sit):
    legs = sit.get("legs") or []
    rates = [leg for leg in legs if leg["panel"] == "rates"]
    oil = [leg for leg in legs if leg["panel"] == "oil"]
    errors = sit.get("errors") or {}
    err_html = ""
    if errors:
        err_html = ('<div class="sitmuted">sources: '
                    + h.escape("; ".join(f"{k}: {v}" for k, v in errors.items())) + "</div>")
    return (f'<section class="wl-section" data-wl="{TAB_NAME}">'
            + _strip(sit)
            + '<div class="panelgrid">' + _legs_panel("Rates regime", rates)
            + _legs_panel("Oil ↔ Rates", oil) + "</div>"
            + _crowding_panel(sit.get("crowding") or [])
            + err_html
            + "</section>")
