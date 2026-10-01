import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tapedeck import situation
from tapedeck.situation import confidence

TODAY = date(2026, 10, 1)


def days(values, end="2026-09-30"):
    return pd.Series(values, index=pd.bdate_range(end=end, periods=len(values)), dtype=float)


def full_src():
    rng = np.random.default_rng(11)
    n = 400
    walk = lambda start, step: days(start + rng.normal(0, step, n).cumsum())
    fred = {"DGS2": walk(4.5, 0.03), "DGS10": walk(4.8, 0.04), "DGS30": walk(5.2, 0.04),
            "T10YIE": walk(2.3, 0.02), "T5YIE": walk(2.4, 0.02), "T5YIFR": walk(2.3, 0.02),
            "DFII10": walk(2.5, 0.03), "THREEFYTP10": walk(0.8, 0.02),
            "BAMLH0A0HYM2": walk(3.0, 0.03), "DCOILBRENTEU": walk(90.0, 1.0)}
    venue_idx = pd.bdate_range(end="2026-10-01", periods=40)
    closes = {"para:10Y": pd.Series(fred["DGS10"].reindex(venue_idx).ffill().values, index=venue_idx),
              "xyz:BRENTOIL": pd.Series(np.linspace(95, 100, 40), index=venue_idx),
              "xyz:CL": pd.Series(np.linspace(88, 92, 40), index=venue_idx)}
    ctx = {"para:10Y": {"mark": 5.3, "oracle": 5.3, "oi": 100.0, "volume_24h": 1e6},
           "xyz:BRENTOIL": {"mark": 100.0, "oracle": 100.0, "oi": 50.0, "volume_24h": 1e8}}
    return {"fred": fred, "closes": closes, "ctx": ctx, "funding": {},
            "errors": {"para:30Y candles": "no candles"}}


def test_build_situation_shape(tmp_path):
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: full_src())
    assert sit["schema"] == 1 and sit["date"] == "2026-10-01"
    assert sit["fred_asof"] == "2026-09-30" and sit["venue_asof"] == "2026-10-01"
    assert sit["regime"]["label"] is not None
    assert len(sit["alerts"]) == 4
    assert {l["panel"] for l in sit["legs"]} == {"rates", "oil"}
    assert 0 < sit["confidence"]["rates"] <= 100 and 0 < sit["confidence"]["oil"] <= 100
    assert sit["errors"] == {"para:30Y candles": "no candles"}
    assert (tmp_path / situation.HISTORY_NAME).exists()


def test_a_delisted_market_only_blanks_its_own_legs(tmp_path):
    src = full_src()
    del src["closes"]["xyz:CL"]
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: src)
    by_id = {l["id"]: l for l in sit["legs"]}
    assert by_id["wti"]["status"] == "no_data" and by_id["brent_wti"]["status"] == "no_data"
    assert by_id["brent"]["status"] == "ok" and by_id["y10"]["status"] != "no_data"


def test_everything_down_still_builds(tmp_path):
    empty = {"fred": {}, "closes": {}, "ctx": {}, "funding": {}, "errors": {"all": "down"}}
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: empty)
    assert sit["regime"]["label"] is None
    assert {a["state"] for a in sit["alerts"]} == {"disabled"}
    assert sit["confidence"] == {"rates": 0, "oil": 0}


def test_feed_is_strict_json_even_with_nan(tmp_path):
    sit = {"schema": 1, "legs": [{"z": float("nan"), "value": float("inf"), "n": np.int64(3)}]}
    path = situation.write_feed(sit, tmp_path / "out")
    data = json.loads(path.read_text())
    assert data["legs"][0]["z"] is None and data["legs"][0]["value"] is None
    assert "NaN" not in path.read_text()


def test_feed_round_trips_a_real_build(tmp_path):
    sit = situation.build_situation(TODAY, tmp_path, fetch=lambda today: full_src())
    data = json.loads(situation.write_feed(sit, tmp_path).read_text())
    assert data["regime"] == sit["regime"]


@pytest.mark.parametrize("items,expected", [
    ([], None),
    ([{"status": "ok"}, {"status": "ok"}], 100),
    ([{"status": "ok"}, {"status": "warming"}], 75),
    ([{"status": "ok", "thin": True}, {"status": "no_data"}], 25),
    ([{"status": "stale"}], 50)])
def test_panel_confidence(items, expected):
    assert confidence.panel_confidence(items) == expected
