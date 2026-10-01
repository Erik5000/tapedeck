import pandas as pd
import pytest

from tapedeck.situation import regime


def move(start, end, n=21):
    """A series that goes from ``start`` to ``end`` over the last 20 bars."""
    idx = pd.bdate_range(end="2026-09-30", periods=n)
    return pd.Series([start] * (n - 1) + [end], index=idx, dtype=float)


def label(dbe_bp, dreal_bp):
    be, real = 2.30, 2.00
    be_end, real_end = be + dbe_bp / 100, real + dreal_bp / 100
    return regime.regime_label(move(be + real, be_end + real_end), move(be, be_end),
                               move(real, real_end))


@pytest.mark.parametrize("dbe,dreal,expected", [
    (3, 2, "Range-bound"),
    (20, 5, "Inflation-led sell-off"),
    (5, 20, "Real-rate-led sell-off"),
    (-5, -20, "Growth-scare rally"),
    (-20, -5, "Disinflation rally"),
])
def test_the_five_labels(dbe, dreal, expected):
    assert label(dbe, dreal)["label"] == expected


def test_exactly_ten_bp_is_a_move_not_a_range():
    assert label(5, 5)["label"] == "Real-rate-led sell-off"       # +10, equal parts
    assert label(-5, -5)["label"] == "Disinflation rally"          # −10, equal parts


def test_the_split_adds_up_and_carries_the_fred_date():
    out = label(7, 24)
    assert (out["d10"], out["dbe"], out["dreal"]) == (31.0, 7.0, 24.0)
    assert out["asof"] == "2026-09-30"


def test_missing_input_gives_no_label_and_a_reason():
    out = regime.regime_label(move(4, 5), None, move(2, 2))
    assert out["label"] is None and "DFII10" in out["note"]


def test_too_few_shared_days_is_warming():
    out = regime.regime_label(move(4, 5, n=10), move(2, 2, n=10), move(2, 3, n=10))
    assert out["label"] is None and out["note"] == "warming up (10/21)"
