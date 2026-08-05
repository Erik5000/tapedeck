import re
from datetime import date

from tapedeck import render

TODAY = date(2026, 7, 31)


def sample_row(**overrides):
    base = {
        "ticker": "NVDA", "name": "NVIDIA Corporation", "group": "semis",
        "sector": "Technology", "market_cap": 4.7e12, "ps": 18.6, "pe": 29.0,
        "earnings_date": "2026-08-26",
        "price": 195.04, "pct_1d": 2.65, "pct_ytd": 4.71, "pct_1y": 34.2,
        "spark": [100.0, 120.0, 195.04], "pct_off_high": -17.45, "new_52w": None,
        "rs_1m": -1.84, "rs_3m": 5.0, "rs_bars": [0.5, -0.2, 1.1], "rs_rank": 1,
        "sma": {"20": {"sma": 199.0, "above": False, "dist_pct": -2.0},
                "50": {"sma": 201.0, "above": False, "dist_pct": -3.0},
                "200": {"sma": 180.0, "above": True, "dist_pct": 8.4}},
        "sma_cross": {}, "gap_pct": 0.5, "rel_vol": 1.2, "atr_pct": 3.1,
        "position": None, "tv_symbol": "NASDAQ:NVDA",
    }
    base.update(overrides)
    return base


def empty_row(**overrides):
    row = {k: None for k in sample_row()}
    row.update({"ticker": "BW", "name": "Babcock & Wilcox <Enterprises>",
                "spark": [], "rs_bars": [], "sma": {}, "sma_cross": {}})
    row.update(overrides)
    return row


# --- formatting helpers ---

def test_fmt_cap():
    assert render.fmt_cap(4.7e12) == "$4.7T"
    assert render.fmt_cap(13.67e9) == "$13.7B"
    assert render.fmt_cap(641e6) == "$641M"
    assert render.fmt_cap(None) == "n/a"


def test_fmt_pct_signed():
    assert render.fmt_pct(2.649) == "+2.65%"
    assert render.fmt_pct(-0.16) == "-0.16%"
    assert render.fmt_pct(None) == "n/a"


def test_fmt_price():
    assert render.fmt_price(1279.957) == "$1,279.96"
    assert render.fmt_price(None) == "n/a"


def test_heat_alpha_clamped():
    assert render.heat_alpha(0.0, cap=10) == 0.0
    assert 0 < render.heat_alpha(5, cap=10) < render.heat_alpha(10, cap=10)
    assert render.heat_alpha(50, cap=10) == render.heat_alpha(10, cap=10)


# --- page invariants ---

def page(rows=None, summary=None, alerts=None, diff=None):
    return render.render_page(rows or [sample_row(), empty_row()], summary,
                              alerts or [], diff, TODAY, "SPY")


def test_page_renders_table_with_rows():
    html = page()
    assert "<table" in html
    assert "NVDA" in html
    assert "n/a" in html  # empty row degrades to n/a cells


def test_page_escapes_names():
    html = page()
    assert "Babcock &amp; Wilcox &lt;Enterprises&gt;" in html
    assert "<Enterprises>" not in html


def test_page_summary_tiles_only_with_positions():
    assert "Total Value" not in page(summary=None)
    summary = {"total_value": 48200.0, "day_pnl": 1120.0, "day_pnl_pct": 2.4,
               "open_pnl": 9300.0, "weights": [100.0]}
    assert "Total Value" in page(summary=summary)


def test_page_shows_alerts():
    alerts = [{"ticker": "NVDA", "kind": "52w_high", "text": "new 52w high", "severity": "good"}]
    assert "new 52w high" in page(alerts=alerts)


def test_page_rows_expand_to_tradingview_charts():
    html = page()
    assert html.count('class="detail"') == 2  # one hidden detail row per ticker
    assert 'data-symbol="NASDAQ:NVDA"' in html
    assert 'data-symbol="BW"' in html  # no tv_symbol → falls back to bare ticker
    # The label has to name the interval TradingView actually draws: it has no
    # 12-hour interval, so "720" silently rendered a daily chart under a 12H
    # heading.
    assert "D · NASDAQ:NVDA" in html and "4H · NASDAQ:NVDA" in html
    assert "12H" not in html
    assert 'data-tf="D"' in html and 'data-tf="240"' in html and 'data-tf="60"' in html
    assert 'data-tf="720"' not in html
    assert "s3.tradingview.com" in html


def wl(name, title, rows, benchmark="SPY", vwap_alert_pct=2.0):
    return {"name": name, "title": title, "benchmark": benchmark,
            "rows": rows, "summary": None, "alerts": [], "diff": None,
            "vwap_alert_pct": vwap_alert_pct}


def test_render_multi_tabs_and_sections():
    html = render.render_multi(
        [wl("sa", "Situational Awareness", [sample_row()]),
         wl("pulse", "Market Pulse", [empty_row()], benchmark="QQQ")], TODAY)
    assert html.count('class="wl-section"') == 2
    assert html.count('class="wtab"') == 2
    assert "Situational Awareness" in html and "Market Pulse" in html
    assert 'data-wl="pulse"' in html
    assert "bench QQQ" in html


def test_render_multi_single_list_has_no_tabs():
    html = render.render_multi([wl("sa", "Situational Awareness", [sample_row()])], TODAY)
    assert html.count('class="wl-section"') == 1
    assert html.count('class="wtab"') == 0


# --- cockpit + basket panels ---

def cockpit_data():
    return {"regenerated": "2026-07-28", "regime": "higher-for-longer, low-stress",
            "freeze": "PARTIAL-LIFT", "triad_refreshed": "2026-07-31", "freeze_note": None,
            "sleeves": [{"position": "Interconnect <leaders>", "tickers": ["CRDO", "CIEN"],
                         "size": "1.25R", "fill_status": "STARTER-OK", "conf": 62}],
            "triad": [{"leg": "10Y breakeven", "reading": "2.21% (falling)",
                       "trigger": ">2% and rising", "status": "quiet"}],
            "open_decisions": [{"id": 5, "title": "Monthly thesis review"}]}


def test_cockpit_panel_renders_and_escapes():
    w = wl("book", "Book", [sample_row()])
    w["cockpit"] = cockpit_data()
    w["cockpit_fresh"] = {"regenerated": "2026-07-28", "age_days": 3,
                          "triad_refreshed": "2026-07-31", "triad_age_days": 0}
    html = render.render_multi([w], TODAY)
    assert "Cockpit" in html
    assert "PARTIAL-LIFT" in html
    assert "10Y breakeven" in html
    assert "#5 Monthly thesis review" in html
    assert "Interconnect &lt;leaders&gt;" in html
    assert "<leaders>" not in html
    assert "STARTER-OK" in html
    assert "(3d)" in html  # freshness age


def test_cockpit_panel_absent_without_cockpit():
    html = render.render_multi([wl("book", "Book", [sample_row()])], TODAY)
    assert "Cockpit" not in html


def basket(group, **over):
    base = {"group": group, "n": 3, "avg_pct_1d": 1.0, "med_rs_1m": 2.0,
            "med_rs_3m": 3.0, "breadth_sma50_pct": 66.7, "med_pct_off_high": -20.0}
    base.update(over)
    return base


def test_baskets_panel_renders_with_anti_row():
    w = wl("book", "Book", [sample_row()])
    w["baskets"] = [basket("t1"), basket("anti-basket", n=25, med_rs_1m=None)]
    html = render.render_multi([w], TODAY)
    assert "Baskets" in html
    assert "anti-basket" in html
    assert 'class="anti"' in html
    assert "+2.00%" in html  # t1 med RS 1M formatted
    assert "67%" in html     # breadth rounded


def test_baskets_panel_absent_with_single_basket():
    w = wl("book", "Book", [sample_row()])
    w["baskets"] = [basket("t1")]
    assert "Baskets" not in render.render_multi([w], TODAY)


def test_page_shows_diff_since():
    diff = {"since": "2026-07-30", "movers": [{"ticker": "NVDA", "change_pct": 2.1}],
            "sma_flips": [], "added": [], "removed": []}
    assert "2026-07-30" in page(diff=diff)


# --- vwap levels ---

def vwap_data(**overrides):
    level = {"name": "6M", "kind": "rolling", "value": 195.5, "sigma": 8.1,
             "direction": "reclaim", "pct_distance": 1.22,
             "in_range": True, "z_stretch": 0.29}
    data = {"score": 0.72, "features": {"volume_z": 1.4},
            "levels": [level], "nearest": level, "in_range_any": True}
    data.update(overrides)
    return data


def vwap_page(vwap=None, fresh=None, second_row=True):
    rows = [sample_row(vwap=vwap if vwap is not None else vwap_data())]
    if second_row:
        rows.append(empty_row(vwap=None))
    section = wl("a", "A", rows)
    if fresh is not None:
        section["vwap_fresh"] = fresh
    return render.render_multi([section], TODAY)


def test_vwap_columns_render_nearest_level():
    html = vwap_page()
    assert 'data-key="vwap_level"' in html
    assert "6M" in html
    assert "0.72" in html


def test_vwap_toggle_button_present_when_a_list_has_vwap():
    html = vwap_page()
    assert 'id="vwapbtn"' in html


def test_no_vwap_columns_when_no_list_has_vwap():
    html = render.render_multi([wl("a", "A", [sample_row()])], TODAY)
    assert 'id="vwapbtn"' not in html
    assert 'data-key="vwap_level"' not in html


def test_ticker_without_vwap_renders_empty_cells_not_zero():
    html = vwap_page()
    assert '<td class="c-vwap a-r"></td>' in html


def test_feed_chip_rendered_with_age():
    html = vwap_page(fresh={"generated": "2026-07-20", "age_days": 14, "stale": True})
    assert "levels from 2026-07-20" in html
    assert "(14d)" in html
    assert 'class="wltbl vwap-stale"' in html


def test_fresh_feed_table_not_dimmed():
    html = vwap_page(fresh={"generated": "2026-08-03", "age_days": 0, "stale": False})
    assert 'class="wltbl"' in html


def test_no_chip_without_freshness():
    assert "levels from" not in vwap_page()


# --- vwap edge cases ---

def test_vwap_missing_zstretch_and_score_render_na_not_zero():
    data = vwap_data()
    data["nearest"] = {**data["nearest"], "z_stretch": None}
    data["score"] = None
    html = vwap_page(vwap=data, second_row=False)
    # the sigma (z) and score columns both degrade to a bare n/a td; neither is "0"
    assert html.count('<td class="c-vwap a-r">n/a</td>') == 2
    assert '<td class="c-vwap a-r">0</td>' not in html
    assert '<td class="c-vwap a-r">0.00</td>' not in html


def test_vwap_level_missing_name_renders_na():
    data = vwap_data()
    data["nearest"] = {**data["nearest"], "name": None}
    html = vwap_page(vwap=data, second_row=False)
    assert '<td class="c-vwap a-l good" data-v="">n/a</td>' in html


# --- vwap ladder + row marker ---

def test_ladder_lists_every_level_with_kind_and_value():
    far = {"name": "decade", "kind": "anchored", "value": 90.0, "sigma": None,
           "direction": "resistance", "pct_distance": 119.9, "in_range": False,
           "z_stretch": None}
    near = vwap_data()["levels"][0]
    html = vwap_page(vwap_data(levels=[near, far], nearest=near))
    assert 'class="vwapladder"' in html
    assert "decade" in html and "anchored" in html
    assert "$90.00" in html


def test_ladder_highlights_in_range_rows():
    assert 'class="lvl-hit"' in vwap_page()


def test_ladder_absent_when_ticker_has_no_vwap():
    html = render.render_multi([wl("a", "A", [sample_row()])], TODAY)
    assert 'class="vwapladder"' not in html


def test_ladder_labels_direction_as_scan_dated():
    assert "(at scan)" in vwap_page()


def test_main_row_marked_when_in_range():
    assert 'class="mainrow vwap-hit"' in vwap_page()


def test_main_row_unmarked_when_out_of_range():
    cold = {"name": "6M", "kind": "rolling", "value": 195.5, "sigma": 8.1,
            "direction": "support", "pct_distance": 4.4, "in_range": False,
            "z_stretch": 0.29}
    html = vwap_page(vwap_data(levels=[cold], nearest=cold, in_range_any=False))
    assert 'class="mainrow vwap-hit"' not in html
    assert 'class="lvl-hit"' not in html


def test_ladder_out_of_range_row_has_no_class_attribute():
    # An out-of-range ladder row must emit no class attribute at all,
    # not an empty class="" — the markup shape the brief calls out.
    far = {"name": "decade", "kind": "anchored", "value": 90.0, "sigma": None,
           "direction": "resistance", "pct_distance": 119.9, "in_range": False,
           "z_stretch": None}
    near = vwap_data()["levels"][0]
    html = vwap_page(vwap_data(levels=[near, far], nearest=near))
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert '<tr><td>decade</td>' in ladder
    assert 'class=""' not in ladder


def test_ladder_and_row_marker_classes_have_matching_css_rules():
    # Same guard as the "good" chip regression from the prior task: a class
    # emitted with no stylesheet rule targeting it is silently invisible.
    html = vwap_page()
    assert 'class="vwapladder"' in html and ".vwapladder {" in html
    assert 'class="lvl-hit"' in html and "tr.lvl-hit {" in html
    assert 'class="mainrow vwap-hit"' in html and "tr.mainrow.vwap-hit " in html


def test_ladder_survives_malformed_level_fields():
    # Upstream feed can hand back a level with name/kind/sigma/direction/z_stretch
    # all None — must degrade to n/a-ish output, never raise on h.escape(None).
    broken = {"name": None, "kind": None, "value": 100.0, "sigma": None,
              "direction": None, "pct_distance": 0.5, "in_range": True,
              "z_stretch": None}
    html = vwap_page(vwap_data(levels=[broken], nearest=broken))
    assert "$100.00" in html
    assert 'class="vwapladder"' in html


def test_ladder_direction_renders_each_real_value():
    # The real feed's vocabulary (states + events); "above"/"below" never occur.
    expected = {"support": "support", "resistance": "resistance",
                "reclaim": "reclaimed", "reject": "rejected"}
    for direction, word in expected.items():
        lvl = {**vwap_data()["levels"][0], "direction": direction}
        html = vwap_page(vwap_data(levels=[lvl], nearest=lvl), second_row=False)
        ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
        assert f"<td>{word}</td></tr>" in ladder, direction


def test_ladder_direction_na_renders_empty_cell():
    lvl = {**vwap_data()["levels"][0], "direction": "na"}
    html = vwap_page(vwap_data(levels=[lvl], nearest=lvl), second_row=False)
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert "<td></td></tr>" in ladder
    assert "na</td>" not in ladder


def test_ladder_direction_unrecognised_value_renders_empty_cell():
    lvl = {**vwap_data()["levels"][0], "direction": "newthing"}
    html = vwap_page(vwap_data(levels=[lvl], nearest=lvl), second_row=False)
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert "<td></td></tr>" in ladder
    assert "newthing" not in ladder


def test_ladder_kind_displays_ath_atl_anchored_friendly():
    ath = {**vwap_data()["levels"][0], "kind": "ath_anchored"}
    html = vwap_page(vwap_data(levels=[ath], nearest=ath), second_row=False)
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert '<td class="lvl-kind">ATH-anchored</td>' in ladder
    assert "ath_anchored" not in ladder

    atl = {**vwap_data()["levels"][0], "kind": "atl_anchored"}
    html = vwap_page(vwap_data(levels=[atl], nearest=atl), second_row=False)
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert '<td class="lvl-kind">ATL-anchored</td>' in ladder
    assert "atl_anchored" not in ladder


def test_ladder_kind_unrecognised_value_passes_through_not_blank():
    # Opposite failure mode from an unmapped `direction`: an unknown future
    # `kind` must still display verbatim, not blank the cell.
    lvl = {**vwap_data()["levels"][0], "kind": "newkind"}
    html = vwap_page(vwap_data(levels=[lvl], nearest=lvl), second_row=False)
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert '<td class="lvl-kind">newkind</td>' in ladder


def test_vwap_dist_heat_cap_matches_list_alert_pct():
    # heat_alpha's cap must track the list's own vwap_alert_pct (the actual
    # in-range threshold), not a fixed constant unrelated to it.
    data = vwap_data()
    pct = data["levels"][0]["pct_distance"]  # 1.22
    for alert_pct in (2.0, 4.0):
        section = wl("a", "A", [sample_row(vwap=data)], vwap_alert_pct=alert_pct)
        html = render.render_multi([section], TODAY)
        expected_alpha = render.heat_alpha(pct, alert_pct)
        assert f"rgba(56,161,105,{expected_alpha:.3f})" in html


def test_vwap_level_column_not_sortable():
    html = vwap_page()
    # The column mixes numeric-prefixed ("1M Rolling") and non-numeric
    # ("Fib 0.618") names, so a parseFloat-based sort is meaningless.
    m = re.search(r'<th class="([^"]*)" data-key="vwap_level">', html)
    assert m is not None
    assert "sortable" not in m.group(1).split()


def test_other_vwap_columns_remain_sortable():
    html = vwap_page()
    m = re.search(r'<th class="([^"]*)" data-key="vwap_dist">', html)
    assert m is not None
    assert "sortable" in m.group(1).split()


def test_ladder_row_count_matches_level_count():
    near = vwap_data()["levels"][0]
    far = {"name": "decade", "kind": "anchored", "value": 90.0, "sigma": None,
           "direction": "resistance", "pct_distance": 119.9, "in_range": False,
           "z_stretch": None}
    html = vwap_page(vwap_data(levels=[near, far], nearest=near))
    ladder = re.search(r'<div class="vwapladder">.*?</div>', html, re.S).group(0)
    assert ladder.count("<tr") == 3  # 1 header row + 2 level rows


def test_ladder_appears_above_tv_panel_in_detail_row():
    html = vwap_page()
    ladder_idx = html.index('class="vwapladder"')
    tv_idx = html.index('class="tvpanel"')
    assert ladder_idx < tv_idx


def test_footer_column_count_unaffected_by_ladder():
    # The ladder lives inside the detail row's colspan, not a real column,
    # so header/footer <th>/<td> parity must be unaffected by its presence.
    html = vwap_page()
    thead = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
    tfoot = re.search(r"<tfoot>(.*?)</tfoot>", html, re.S).group(1)
    assert thead.count("<th") - 1 == tfoot.count("<td")


def test_feed_chip_generated_without_age_omits_day_suffix():
    html = vwap_page(fresh={"generated": "2026-07-20", "age_days": None, "stale": False})
    assert "levels from 2026-07-20</span>" in html
    assert "levels from 2026-07-20 (" not in html


def test_no_vwap_columns_when_every_row_lacks_vwap_data():
    section = wl("a", "A", [sample_row(vwap=None), empty_row(vwap=None)])
    html = render.render_multi([section], TODAY)
    assert 'id="vwapbtn"' not in html
    assert 'data-key="vwap_level"' not in html
    assert 'class="c-vwap' not in html


def test_page_renders_when_no_list_has_vwap_data():
    html = render.render_multi(
        [wl("a", "A", [sample_row()]), wl("b", "B", [empty_row()])], TODAY)
    assert 'id="vwapbtn"' not in html
    assert 'data-key="vwap_level"' not in html
    assert "NVDA" in html


def test_vwap_columns_only_render_on_list_with_data():
    w1 = wl("a", "A", [sample_row(vwap=vwap_data())])
    w2 = wl("b", "B", [sample_row(ticker="AAPL", name="Apple", vwap=None)])
    html = render.render_multi([w1, w2], TODAY)
    assert html.count('data-key="vwap_level"') == 1
    assert 'id="vwapbtn"' in html


def test_footer_column_count_matches_header_when_positions_present_but_no_vwap():
    pos = {"market_value": 1000.0, "weight_pct": 5.0, "day_pnl": 10.0,
           "open_pnl": 20.0, "open_pnl_pct": 2.0}
    html = render.render_multi([wl("a", "A", [sample_row(position=pos)])], TODAY)
    thead = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
    tfoot = re.search(r"<tfoot>(.*?)</tfoot>", html, re.S).group(1)
    assert "c-vwap" not in thead and "c-vwap" not in tfoot
    # ticker+name collapse into one colspan=2 <td> in the averages row, so the
    # footer has exactly one fewer <td> than the header has <th>
    assert thead.count("<th") - 1 == tfoot.count("<td")


def test_vwap_in_range_good_class_has_a_matching_css_rule():
    # Guards against a class that's emitted but never styled (and vice versa):
    # the markup must carry the "good" class on an in-range vwap_level cell,
    # AND the stylesheet must contain a rule that actually targets it.
    html = vwap_page()
    assert '<td class="c-vwap a-l good" data-v="6M">6M</td>' in html
    assert ".c-vwap.good {" in html


# ---------- panel grid + grouped alerts ----------

def _panelgrid_content(html):
    """Inner HTML of the panelgrid, found by <div> balance — the panels nest
    their own chiprow divs, so splitting on the first </div> would truncate."""
    start = html.index('<div class="panelgrid">')
    i, depth = start, 0
    while True:
        opened = html.find("<div", i + 1)
        closed = html.find("</div>", i + 1)
        assert closed != -1, "unbalanced panelgrid"
        if opened != -1 and opened < closed:
            depth += 1
            i = opened
        elif depth:
            depth -= 1
            i = closed
        else:
            return html[start:closed]


def test_cockpit_and_baskets_share_a_panel_grid():
    """Both mini-table panels tile into one grid so they sit side by side
    instead of each claiming a full 2000px row with 2/3 of it empty."""
    cockpit = {"regime": "higher-for-longer", "freeze": "PARTIAL-LIFT", "sleeves": [],
               "triad": [], "open_decisions": [], "regenerated": "2026-07-28"}
    baskets = [{"group": "semis", "n": 3, "avg_pct_1d": 1.0, "med_rs_1m": 0.5,
                "med_rs_3m": 1.5, "breadth_sma50_pct": 66.0, "med_pct_off_high": -10.0},
               {"group": "energy", "n": 2, "avg_pct_1d": -1.0, "med_rs_1m": -0.5,
                "med_rs_3m": -1.5, "breadth_sma50_pct": 0.0, "med_pct_off_high": -20.0}]
    html = render.render_multi(
        [dict(wl("sa", "SA", [sample_row()]), cockpit=cockpit, baskets=baskets)], TODAY)
    assert html.count('class="panelgrid"') == 1
    grid = _panelgrid_content(html)
    assert "Cockpit" in grid and "Baskets" in grid
    assert "Alerts" not in grid   # full-width panels stay outside the grid


def test_panel_grid_is_omitted_when_neither_panel_renders():
    """No stray empty wrapper on a plain list — most lists have neither panel."""
    html = render.render_multi([wl("sa", "SA", [sample_row()])], TODAY)
    assert "panelgrid" not in html.replace(".panelgrid {", "").replace(
        ".panelgrid > .panel {", "")


def test_panel_grid_class_has_a_matching_css_rule():
    # Same guard as the ladder classes: a class with no rule is silently inert,
    # and here that means the layout fix quietly not applying.
    cockpit = {"regime": "r", "freeze": None, "sleeves": [], "triad": [],
               "open_decisions": [], "regenerated": None}
    html = render.render_multi(
        [dict(wl("sa", "SA", [sample_row()]), cockpit=cockpit)], TODAY)
    assert 'class="panelgrid"' in html and ".panelgrid {" in html


def test_alerts_group_into_one_row_per_ticker():
    alerts = [
        {"ticker": "CRDO", "kind": "sma_reclaimed", "text": "reclaimed 20SMA",
         "short": "20SMA", "severity": "good"},
        {"ticker": "FN", "kind": "gap", "text": "gapped up +15.1%",
         "short": "gap +15.1%", "severity": "warn"},
        {"ticker": "CRDO", "kind": "vwap", "text": "0.2% above ATH Anchored VWAP",
         "short": "0.2% ATH-Anch", "severity": "bad"},
    ]
    html = page(alerts=alerts)
    assert html.count('class="arow"') == 2          # two tickers, not three chips
    assert html.count('class="atk"') == 2
    crdo = html.split('class="arow"')[1]
    assert "20SMA" in crdo and "0.2% ATH-Anch" in crdo   # both under one ticker


def test_alert_chip_prints_short_and_keeps_the_full_text_as_a_tooltip():
    """Nothing is lost by shortening — the sentence moves to the tooltip."""
    alerts = [{"ticker": "CRDO", "kind": "vwap", "severity": "bad",
               "text": "0.2% above ATH Anchored VWAP · acting as resistance",
               "short": "0.2% ATH-Anch"}]
    html = page(alerts=alerts)
    assert 'title="CRDO 0.2% above ATH Anchored VWAP · acting as resistance"' in html
    assert ">▼ 0.2% ATH-Anch</span>" in html


def test_alert_chip_falls_back_to_text_without_a_short_key():
    """The feed contract allows older//external alert dicts with no `short`."""
    html = page(alerts=[{"ticker": "NVDA", "kind": "52w_high",
                         "text": "new 52w high", "severity": "good"}])
    assert "new 52w high" in html


def test_alert_row_classes_have_matching_css_rules():
    html = page(alerts=[{"ticker": "NVDA", "kind": "gap", "text": "gapped up +6%",
                         "short": "gap +6%", "severity": "warn"}])
    assert 'class="arow"' in html and ".arow {" in html
    assert 'class="atk"' in html and ".atk {" in html


def test_footer_no_longer_credits_speculator_io():
    assert "speculator_io" not in page()
    assert "generated by tapedeck" in page()
