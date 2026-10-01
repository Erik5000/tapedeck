from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import oillink, series

TODAY = date(2026, 9, 30)
N = 400


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


RNG = np.random.default_rng(3)
RET = days(RNG.normal(0, 1.5, N))                       # daily Brent % returns


def be_from(ret, beta, extra=None):
    """A 5Y breakeven (%) whose daily bp move is beta × Brent return (+ extra bp)."""
    dbe = beta * ret + (0 if extra is None else extra)
    return 2.0 + dbe.cumsum() / 100


def test_compound_twenty_bars_of_one_percent():
    out = oillink.compound(days([1.0] * 21))
    assert out.iloc[-1] == pytest.approx((1.01 ** 20 - 1) * 100)
    assert oillink.compound(None) is None


def test_beta_recovers_a_known_pass_through():
    beta = oillink.be_beta_series(be_from(RET, 2.0), RET)
    assert beta.iloc[-1] == pytest.approx(2.0)


def test_beta_needs_sixty_shared_bars():
    assert oillink.be_beta_series(be_from(RET[:59], 2.0), RET[:59]) is None


def test_gap_is_zero_when_breakevens_follow_the_beta():
    be = be_from(RET, 2.0)
    gap = oillink.be_gap_series(be, RET, oillink.be_beta_series(be, RET))
    # Compounded Brent returns vs summed bp moves leave a few bp of residue,
    # far below the 50+ bp of a real stall (next test).
    assert gap.abs().max() < 5.0


def test_gap_is_negative_when_breakevens_stall_in_an_oil_rally():
    ret = RET.copy()
    ret.iloc[-20:] = 2.0                                  # Brent +2%/day for 20 days
    be = be_from(ret, 2.0)
    be.iloc[-20:] = be.iloc[-21]                          # breakevens flat
    gap = oillink.be_gap_series(be, ret, oillink.be_beta_series(be_from(RET, 2.0), RET))
    assert gap.iloc[-1] < -50


def src_with(brent_ret=RET, be_beta=2.0):
    spot = days(80 * (1 + brent_ret / 100).cumprod())
    venue_idx = spot.index[-60:]
    perp = pd.Series(spot.loc[venue_idx].values * 1.05, index=venue_idx)   # same % moves
    cl = pd.Series(perp.values - 7.0, index=venue_idx)
    return {"fred": {"T5YIE": be_from(brent_ret, be_beta), "DCOILBRENTEU": spot},
            "closes": {"xyz:BRENTOIL": perp, "xyz:CL": cl}, "ctx": {}}


def test_oil_legs_in_display_order_with_units():
    src = src_with()
    built = oillink.build_oil_legs(series.prepare(src), src, TODAY)
    assert [l["id"] for l in built] == ["brent", "wti", "brent_wti", "be_beta", "be_gap"]
    by_id = {l["id"]: l for l in built}
    assert by_id["brent"]["src"] == "V+F" and by_id["brent"]["chg_unit"] == "%"
    assert by_id["brent"]["status"] == "ok" and by_id["brent"]["z"] is not None
    assert by_id["wti"]["status"] == "warming"            # venue-only history
    assert by_id["brent_wti"]["value"] == pytest.approx(7.0)
    assert by_id["be_beta"]["value"] == pytest.approx(2.0, rel=0.05)
    assert by_id["be_beta"]["z"] is None and by_id["be_beta"]["status"] == "ok"


def test_brent_rally_gives_positive_brent_z():
    ret = RET.copy()
    ret.iloc[-20:] = 2.0
    src = src_with(ret)
    by_id = {l["id"]: l for l in oillink.build_oil_legs(series.prepare(src), src, TODAY)}
    assert by_id["brent"]["z"] > 1


def test_no_inputs_give_no_data_legs():
    src = {"fred": {}, "closes": {}, "ctx": {}}
    built = oillink.build_oil_legs(series.prepare(src), src, TODAY)
    assert {l["status"] for l in built} == {"no_data"}
