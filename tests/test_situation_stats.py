from datetime import date

import numpy as np
import pandas as pd
import pytest

from tapedeck.situation import stats


def days(values, end="2026-09-30"):
    idx = pd.bdate_range(end=end, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_finite_refuses_bool_none_text_nan_and_inf():
    assert stats.finite(True) is None
    assert stats.finite(None) is None
    assert stats.finite("abc") is None
    assert stats.finite(float("nan")) is None
    assert stats.finite(float("inf")) is None
    assert stats.finite("5.25") == 5.25


def test_clean_drops_nan_and_inf_and_sorts():
    s = pd.Series([3.0, np.nan, np.inf, 1.0],
                  index=pd.to_datetime(["2026-09-04", "2026-09-03", "2026-09-02", "2026-09-01"]))
    out = stats.clean(s)
    assert list(out.values) == [1.0, 3.0]
    assert stats.clean(pd.Series([np.nan])) is None
    assert stats.clean(None) is None


def test_zscore_needs_a_full_window():
    assert stats.zscore(days(range(251))) is None
    assert stats.zscore(days(range(252))) is not None


def test_zscore_of_a_flat_series_is_none_not_infinite():
    assert stats.zscore(days([2.0] * 300)) is None


def test_zscore_uses_only_the_last_window():
    values = [1000.0] * 50 + list(np.linspace(0, 1, 252))
    z = stats.zscore(days(values))
    tail = pd.Series(np.linspace(0, 1, 252))
    assert z == pytest.approx((1.0 - tail.mean()) / tail.std(ddof=1))


def test_zscore_without_centre_divides_by_the_spread_only():
    values = list(np.linspace(-1, 1, 252))
    z = stats.zscore(days(values), center=False)
    assert z == pytest.approx(1.0 / pd.Series(values).std(ddof=1))


def test_change_over_twenty_bars():
    assert stats.change(days(range(30)), 20) == 20.0
    assert stats.change(days(range(20)), 20) is None


@pytest.mark.parametrize("z,word", [
    (0.99, "normal"), (-0.99, "normal"), (1.0, "high"), (2.0, "high"),
    (2.01, "extreme high"), (-1.5, "low"), (-2.5, "extreme low"), (None, None)])
def test_state_word_bands(z, word):
    assert stats.state_word(z) == word


def test_age_days_counts_calendar_days():
    assert stats.age_days(days([1.0], end="2026-09-25"), date(2026, 9, 29)) == 4
    assert stats.age_days(None, date(2026, 9, 29)) is None
