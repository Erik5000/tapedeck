import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import series


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


FRED = days(np.linspace(4.0, 5.0, 300))                    # ends 2026-09-30


def venue_like(offset, n=20, end="2026-10-01"):
    """Venue yields that track FRED plus ``offset`` (percent), one bar past it."""
    idx = pd.bdate_range(end=end, periods=n)
    base = FRED.reindex(idx).ffill().fillna(5.0)
    return pd.Series(base.values + offset, index=idx)


def test_join_levels_joins_when_within_five_bp():
    venue = venue_like(0.04)
    out = series.join_levels(FRED, venue)
    assert out["joined"] and out["src"] == "V+F" and out["note"] is None
    s = out["series"]
    assert s.index[-1] == venue.index[-1]
    assert (s[s.index < venue.index[0]] == FRED[FRED.index < venue.index[0]]).all()
    assert out["live"] == venue.iloc[-1]


def test_join_levels_refuses_over_five_bp():
    venue = venue_like(0.06)
    out = series.join_levels(FRED, venue)
    assert not out["joined"] and out["src"] == "F"
    assert out["series"].index[-1] == FRED.index[-1]
    assert out["live"] == venue.iloc[-1]
    assert "6.0 bp apart" in out["note"]


def test_join_levels_refuses_with_fewer_than_five_shared_days():
    venue = venue_like(0.0, n=5)                  # 4 shared days + 1 day past FRED
    out = series.join_levels(FRED, venue)
    assert not out["joined"]
    assert "only 4 shared days" in out["note"]


def test_join_levels_one_side_missing():
    assert series.join_levels(FRED, None)["src"] == "F"
    assert series.join_levels(None, venue_like(0.0))["src"] == "V"
    assert series.join_levels(None, None)["series"] is None


def test_join_returns_has_no_jump_at_the_join():
    spot = days([80.0] * 250 + [80.0 * 1.01 ** i for i in range(1, 51)])
    idx = pd.bdate_range(start=spot.index[260], periods=60)
    perp = pd.Series(90.0 * 1.01 ** np.arange(60), index=idx)   # $10 above spot
    r = series.join_returns(spot, perp)
    assert r.max() == pytest.approx(1.0)                         # never the $10 gap
    assert r.index.is_monotonic_increasing and not r.index.duplicated().any()
    assert idx[0] not in r.index                                 # first venue day has no return


def test_prepare_shapes_the_inputs():
    src = {"fred": {"DGS10": FRED, "DCOILBRENTEU": days([80.0, 81.0, 82.0])},
           "closes": {"para:10Y": venue_like(0.0), "xyz:CL": days([90.0, 91.0])}}
    prep = series.prepare(src)
    assert prep["y10"]["joined"]
    assert prep["y2"]["series"] is None
    assert prep["brent"]["src"] == "F" and len(prep["brent"]["returns"]) == 2
    assert list(prep["wti"].values) == [90.0, 91.0]
