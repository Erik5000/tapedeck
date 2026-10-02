from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import legs, series

TODAY = date(2026, 9, 30)


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


def rising(start, stop, n=300, end="2026-09-30"):
    """A rising series with a little noise, so the last value is the high."""
    noise = np.random.default_rng(7).normal(0, 0.001, n)
    return days(np.linspace(start, stop, n) + noise, end=end)


def make(series_, **kw):
    return legs.make_leg("x", "X", "rates", "%", "higher", series_, TODAY, src="F", **kw)


# ---------- make_leg ----------

def test_no_series_is_no_data_with_a_note():
    leg = make(None)
    assert leg["status"] == "no_data" and leg["value"] is None and leg["z"] is None
    assert leg["note"] == "no data"


def test_short_series_is_warming_and_has_no_z():
    leg = make(days(np.linspace(1, 2, 100)))
    assert leg["status"] == "warming" and leg["z"] is None
    assert (leg["n"], leg["need"]) == (100, 252)
    assert leg["value"] == 2.0


def test_full_series_gives_value_change_z_and_state():
    leg = make(days(np.linspace(1, 2, 300)))
    assert leg["status"] == "ok"
    assert leg["chg20"] == pytest.approx((1 / 299) * 20 * 100)
    assert leg["z"] > 1 and leg["state"] in ("high", "extreme high")


def test_age_four_days_is_fresh_and_five_is_stale():
    # Friday data read on Tuesday after a Monday holiday is 4 days old: fresh.
    tuesday = date(2026, 9, 29)
    friday, thursday = days(np.linspace(1, 2, 300), end="2026-09-25"), days(np.linspace(1, 2, 300), end="2026-09-24")
    assert legs.make_leg("x", "X", "rates", "%", "h", friday, tuesday, src="F")["status"] == "ok"
    assert legs.make_leg("x", "X", "rates", "%", "h", thursday, tuesday, src="F")["status"] == "stale"


def test_explicit_value_and_z_series_are_used():
    leg = make(days([1.0] * 300), value=9.0, chg20=None, z_series=days(np.linspace(0, 1, 300)))
    assert leg["value"] == 9.0 and leg["chg20"] is None and leg["z"] > 0


def test_with_z_false_never_warms():
    leg = make(days([1.0, 2.0]), with_z=False)
    assert leg["status"] == "ok" and leg["need"] == 0


@pytest.mark.parametrize("ctx,thin", [
    (None, False), ({"volume_24h": 99_999.0}, True), ({"volume_24h": 1e6}, False),
    ({"volume_24h": 1e6, "mark": 5.04, "oracle": 5.0}, True),
    ({"volume_24h": 1e6, "mark": 5.02, "oracle": 5.0}, False)])
def test_is_thin(ctx, thin):
    assert legs.is_thin(ctx) is thin


# ---------- direction: one test per leg ----------

HIGHER = {
    "y2": "higher yield", "y10": "higher yield", "y30": "higher yield",
    "curve_2s10s": "steeper", "curve_10s30s": "steeper",
    "be10": "more priced inflation", "be5y5y": "more priced long-run inflation",
    "real10": "tighter money", "term_premium": "more pay for duration risk",
    "rate_vol": "more rate volatility", "credit": "more credit stress",
}


def test_every_rate_leg_states_its_direction():
    assert {k: v[3] for k, v in legs.RATE_LEGS.items()} == HIGHER


def rising_src():
    """Every input rising; the long end rises fastest, and y10's swings grow."""
    y10 = rising(4.0, 5.0)
    swing = np.sin(np.arange(300)) * np.linspace(0.001, 0.05, 300)
    fred = {"DGS2": rising(4.0, 4.2), "DGS10": y10 + swing, "DGS30": rising(4.0, 6.0),
            "T10YIE": rising(2.0, 2.5), "T5YIFR": rising(2.0, 2.5), "DFII10": rising(1.5, 2.5),
            "THREEFYTP10": rising(0.2, 1.0), "BAMLH0A0HYM2": rising(3.0, 5.0)}
    return {"fred": fred, "closes": {}, "ctx": {}}


@pytest.mark.parametrize("leg_id", [k for k in legs.RATE_LEGS if k != "rate_vol"])
def test_rising_input_gives_positive_z(leg_id):
    src = rising_src()
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built[leg_id]["z"] > 0, leg_id


def test_growing_swings_give_positive_rate_vol_z():
    src = rising_src()
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["rate_vol"]["status"] == "ok" and built["rate_vol"]["z"] > 0


# ---------- build_rates_legs ----------

def test_rates_legs_come_in_display_order_with_sources():
    src = rising_src()
    built = legs.build_rates_legs(series.prepare(src), src, TODAY)
    assert [leg["id"] for leg in built] == list(legs.RATE_LEGS)
    by_id = {leg["id"]: leg for leg in built}
    assert by_id["be10"]["src"] == "F" and by_id["y10"]["src"] == "F"
    assert by_id["curve_2s10s"]["unit"] == "bp"
    assert "chg_z" in by_id["be10"]


def test_no_inputs_give_no_data_legs_not_a_crash():
    src = {"fred": {}, "closes": {}, "ctx": {}}
    built = legs.build_rates_legs(series.prepare(src), src, TODAY)
    assert {leg["status"] for leg in built} == {"no_data"}
    assert {leg["id"]: leg for leg in built}["be10"]["chg_z"] is None


def test_term_premium_stays_fresh_for_ten_days():
    src = {"fred": {"THREEFYTP10": rising(0.2, 1.0, end="2026-09-22")}, "closes": {}, "ctx": {}}
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["term_premium"]["status"] == "ok"


def test_thin_venue_market_marks_its_leg():
    src = rising_src()
    src["ctx"] = {"para:30Y": {"volume_24h": 22_000.0}}
    built = {leg["id"]: leg for leg in legs.build_rates_legs(series.prepare(src), src, TODAY)}
    assert built["y30"]["thin"] and built["curve_10s30s"]["thin"]
    assert not built["y10"]["thin"]
