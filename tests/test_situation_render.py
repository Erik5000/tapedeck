import re
from datetime import date

from tapedeck import render
from tapedeck.situation import render as sit_render

TODAY = date(2026, 10, 1)


def leg(leg_id, panel, **kw):
    base = {"id": leg_id, "label": leg_id.upper(), "panel": panel, "unit": "%", "higher": "x",
            "src": "F", "value": 5.3161, "chg20": 31.0, "chg_unit": "bp", "z": 1.8,
            "state": "high", "age_days": 1, "status": "ok", "n": 300, "need": 252,
            "thin": False, "note": None}
    base.update(kw)
    return base


def crowd(market, panel, **kw):
    base = {"market": market, "panel": panel, "funding_ann": -2.2, "funding_z": -0.8,
            "funding_days": 90, "funding_need": 60, "oi": 1373816.0, "oi_chg_20d": None,
            "oi_days": 3, "oi_need": 20, "side": None, "thin": False, "status": "warming",
            "note": "warming up: OI 3/20 days"}
    base.update(kw)
    return base


def sit(**kw):
    base = {
        "schema": 1, "date": "2026-10-01", "fred_asof": "2026-09-30", "venue_asof": "2026-10-01",
        "regime": {"label": "Real-rate-led sell-off", "d10": 31.0, "dbe": 7.0, "dreal": 24.0,
                   "asof": "2026-09-30", "note": None},
        "alerts": [
            {"id": "bonds_ignore_oil", "label": "Bonds ignore oil", "state": "fired",
             "detail": "Brent z +2.1 · BE gap z -1.3", "note": None},
            {"id": "leveraged_oil_rally", "label": "Leveraged oil rally", "state": "disabled",
             "detail": "needs OI history (3/20 days)", "note": "Reads perp leverage, not the futures curve."}],
        "confidence": {"rates": 82, "oil": 64},
        "legs": [leg("y10", "rates"),
                 leg("be10", "rates", z=None, status="warming", n=100, state=None),
                 leg("credit", "rates", value=None, chg20=None, z=None, status="no_data",
                     state=None, n=0, note="no data", age_days=None),
                 leg("brent", "oil", unit="$", value=100.53, chg20=12.0, chg_unit="%", z=2.1,
                     state="extreme high"),
                 leg("be_beta", "oil", unit="bp/1%", value=0.04, chg20=None, z=None, state=None,
                     need=0, n=0)],
        "crowding": [crowd("xyz:BRENTOIL", "oil"),
                     crowd("para:10Y", "rates", funding_ann=1.1, oi_chg_20d=12.0, status="ok",
                           side="short duration crowded", note=None),
                     crowd("xyz:CL", "oil", status="no_data")],
        "errors": {"FRED DGS30": "timed out"},
    }
    base.update(kw)
    return base


def test_strip_shows_label_split_alerts_and_confidence():
    out = sit_render.render_situation(sit())
    assert "Real-rate-led sell-off" in out
    assert "10Y +31bp/20d = real +24 · BE +7" in out
    assert '<span class="chip warn"' in out and "● Bonds ignore oil" in out
    assert '<span class="chip off"' in out
    assert "○ Leveraged oil rally — needs OI history (3/20 days)" in out
    assert "Reads perp leverage" in out
    assert "Rates 82" in out and "Oil↔Rates 64" in out
    assert "FRED to 2026-09-30" in out


def test_fired_alert_is_listed_before_disabled():
    out = sit_render.render_situation(sit())
    assert out.index("Bonds ignore oil") < out.index("Leveraged oil rally")


def test_legs_format_by_unit():
    out = sit_render.render_situation(sit())
    assert ">5.32%<" in out and ">+31bp<" in out and ">+1.8<" in out
    assert ">100.53<" in out and ">+12.0%<" in out


def test_warming_and_no_data_render_as_text_never_a_number():
    out = sit_render.render_situation(sit())
    be10 = re.search(r"<tr><td>BE10</td>.*?</tr>", out).group(0)
    assert "warming up (100/252)" in be10
    credit = re.search(r'<tr><td title="no data">CREDIT</td>.*?</tr>', out).group(0)
    assert "no data" in credit and re.search(r">\s*-?\d", credit.replace("0d", "")) is None


def test_a_leg_without_z_shows_a_dash_not_warming():
    out = sit_render.render_situation(sit())
    beta = re.search(r"<tr><td>BE_BETA</td>.*?</tr>", out).group(0)
    assert "warming" not in beta and ">0.04<" in beta


def test_crowding_rows():
    out = sit_render.render_situation(sit())
    assert "warming up (3/20 days)" in out and "short duration crowded" in out
    assert "1,373,816" in out and "+12.0%" in out
    assert re.search(r"xyz:CL</td><td[^>]*>no data", out)


def test_source_errors_are_listed():
    assert "FRED DGS30: timed out" in sit_render.render_situation(sit())


def test_no_regime_label_says_why():
    out = sit_render.render_situation(sit(regime={
        "label": None, "d10": None, "dbe": None, "dreal": None, "asof": None,
        "note": "warming up (10/21)"}))
    assert "no label — warming up (10/21)" in out


def test_text_is_escaped():
    out = sit_render.render_situation(sit(errors={"<x>": "<script>"}))
    assert "<script>" not in out and "&lt;script&gt;" in out


# ---------- the page ----------

def wl(name):
    return {"name": name, "title": name.title(), "benchmark": "SPY", "rows": [],
            "summary": None, "alerts": [], "diff": None}


def test_situation_is_the_first_tab():
    page = render.render_multi([wl("semis")], TODAY, situation=sit())
    tabs = re.findall(r'<button class="wtab" data-wl="([^"]+)"', page)
    assert tabs == ["_situation", "semis"]
    assert page.index('data-wl="_situation"') < page.index('class="wl-section" data-wl="semis"')


def test_a_watchlist_named_situation_does_not_clash():
    page = render.render_multi([wl("situation")], TODAY, situation=sit())
    assert re.findall(r'<button class="wtab" data-wl="([^"]+)"', page) == ["_situation", "situation"]


def test_without_situation_the_page_is_unchanged():
    assert render.render_multi([wl("semis")], TODAY) == \
        render.render_multi([wl("semis")], TODAY, situation=None)
    assert "_situation" not in render.render_multi([wl("semis")], TODAY)
