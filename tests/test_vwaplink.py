import json
from datetime import date

import pytest

from tapedeck import vwaplink

FEED = {
    "schema": 1,
    "generated": "2026-08-03T18:22:00+02:00",
    "threshold_pct": 5.0,
    "tickers": {
        "CRDO": {
            "price": 190.00,          # scan-time price; tapedeck must ignore this
            "score": 0.72,
            "features": {"volume_z": 1.4, "regime_er": 0.31},
            "levels": [
                {"name": "decade", "kind": "anchored", "value": 90.0,
                 "sigma": None, "direction": "above"},
                {"name": "6M", "kind": "rolling", "value": 195.50,
                 "sigma": 8.1, "direction": "reclaim"},
            ],
        },
    },
}


def _write(tmp_path, obj):
    p = tmp_path / "vwap-latest.json"
    p.write_text(json.dumps(obj))
    return str(p)


# ---------- load ----------

def test_load_returns_feed(tmp_path):
    assert vwaplink.load_vwap(_write(tmp_path, FEED))["schema"] == 1


def test_missing_file_returns_none(capsys):
    assert vwaplink.load_vwap("/nope/vwap-latest.json") is None
    assert "warning:" in capsys.readouterr().err


def test_malformed_json_returns_none(tmp_path, capsys):
    p = tmp_path / "vwap-latest.json"
    p.write_text("{not json")
    assert vwaplink.load_vwap(str(p)) is None
    assert "warning:" in capsys.readouterr().err


def test_unknown_schema_returns_none(tmp_path, capsys):
    assert vwaplink.load_vwap(_write(tmp_path, {**FEED, "schema": 2})) is None
    assert "schema" in capsys.readouterr().err


# ---------- freshness ----------

def test_freshness_age_in_calendar_days():
    fresh = vwaplink.vwap_freshness(FEED, date(2026, 8, 6))
    assert fresh["generated"] == "2026-08-03"
    assert fresh["age_days"] == 3
    assert fresh["stale"] is False


def test_freshness_marks_stale_past_threshold():
    fresh = vwaplink.vwap_freshness(FEED, date(2026, 8, 15))
    assert fresh["age_days"] == 12
    assert fresh["stale"] is True


def test_freshness_of_none_is_none():
    assert vwaplink.vwap_freshness(None, date(2026, 8, 3)) is None


def test_unparseable_generated_degrades_to_none_age():
    fresh = vwaplink.vwap_freshness({**FEED, "generated": "whenever"}, date(2026, 8, 3))
    assert fresh["age_days"] is None
    assert fresh["stale"] is False


# ---------- attach / recompute ----------

def test_recomputes_distance_against_live_price_not_scan_price():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    # (197.88 - 195.50) / 195.50 * 100 == 1.217...  — NOT computed from 190.00
    assert by_name["6M"]["pct_distance"] == pytest.approx(1.2174, abs=1e-3)


def test_levels_sorted_nearest_first():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert [lvl["name"] for lvl in rows[0]["vwap"]["levels"]] == ["6M", "decade"]
    assert rows[0]["vwap"]["nearest"]["name"] == "6M"


def test_in_range_uses_alert_pct_not_feed_threshold():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    assert by_name["6M"]["in_range"] is True        # 1.22% <= 2.0%
    assert by_name["decade"]["in_range"] is False   # 119% is in the file, not in range
    assert rows[0]["vwap"]["in_range_any"] is True


def test_tighter_alert_pct_excludes_the_level():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 1.0)
    assert rows[0]["vwap"]["in_range_any"] is False


def test_z_stretch_recomputed_and_none_without_sigma():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    by_name = {lvl["name"]: lvl for lvl in rows[0]["vwap"]["levels"]}
    assert by_name["6M"]["z_stretch"] == pytest.approx((197.88 - 195.50) / 8.1, abs=1e-4)
    assert by_name["decade"]["z_stretch"] is None


def test_direction_carried_verbatim():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"]["nearest"]["direction"] == "reclaim"


def test_score_and_features_carried():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"]["score"] == 0.72
    assert rows[0]["vwap"]["features"]["volume_z"] == 1.4


def test_ticker_absent_from_feed_gets_none():
    rows = [{"ticker": "NVDA", "price": 100.0}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_row_without_price_gets_none():
    rows = [{"ticker": "CRDO", "price": None}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_nonpositive_level_value_is_skipped():
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": None, "features": {},
        "levels": [{"name": "bad", "kind": "rolling", "value": 0,
                    "sigma": None, "direction": "above"}]}}}
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_attach_with_none_feed_sets_none_on_every_row():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, None, 2.0)
    assert rows[0]["vwap"] is None


# ---------- hardening: untrusted external input from a different repo ----------

def test_load_top_level_json_not_an_object_returns_none(tmp_path, capsys):
    p = tmp_path / "vwap-latest.json"
    p.write_text(json.dumps([1, 2, 3]))
    assert vwaplink.load_vwap(str(p)) is None
    assert "warning:" in capsys.readouterr().err


def test_load_top_level_json_scalar_returns_none(tmp_path, capsys):
    p = tmp_path / "vwap-latest.json"
    p.write_text(json.dumps("just a string"))
    assert vwaplink.load_vwap(str(p)) is None
    assert "warning:" in capsys.readouterr().err


def test_tickers_not_a_dict_degrades_to_none(capsys):
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, {**FEED, "tickers": ["not", "a", "dict"]}, 2.0)
    assert rows[0]["vwap"] is None


def test_ticker_entry_not_a_dict_degrades_to_none():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": "unexpected string entry"}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_levels_not_a_list_degrades_to_none():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {}, "levels": "not a list"}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_level_entry_not_a_dict_is_skipped():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": ["not a dict", 42, None,
                    {"name": "ok", "kind": "rolling", "value": 195.5,
                     "sigma": 8.1, "direction": "reclaim"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"]["nearest"]["name"] == "ok"


def test_level_value_non_numeric_string_is_skipped():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [{"name": "bad", "kind": "rolling", "value": "not-a-number",
                    "sigma": None, "direction": "above"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_level_sigma_non_numeric_string_degrades_z_stretch_to_none():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [{"name": "6M", "kind": "rolling", "value": 195.5,
                    "sigma": "wide", "direction": "reclaim"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"]["nearest"]["z_stretch"] is None


def test_row_price_non_numeric_string_degrades_to_none():
    rows = [{"ticker": "CRDO", "price": "n/a"}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_features_not_a_dict_degrades_to_empty_dict():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": "not a dict",
        "levels": [{"name": "6M", "kind": "rolling", "value": 195.5,
                    "sigma": 8.1, "direction": "reclaim"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"]["features"] == {}


def test_row_missing_ticker_key_degrades_to_none():
    rows = [{"price": 197.88}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_freshness_generated_non_string_type_degrades_to_none_age():
    fresh = vwaplink.vwap_freshness({**FEED, "generated": 20260803}, date(2026, 8, 3))
    assert fresh["age_days"] is None
    assert fresh["stale"] is False


# ---------- review round 1: non-finite / bool / negative-sigma / future-dated feed ----------

def test_nan_level_value_is_excluded_and_does_not_poison_nearest(tmp_path):
    # A NaN level sits alongside a legitimate near level. json.loads accepts
    # the out-of-spec NaN token, nan <= 0 is False (all NaN comparisons are
    # false), so a naive `value <= 0` guard lets it through and a
    # comparison-based sort on a NaN key is undefined. The legitimate level
    # must win `nearest` and the NaN level must not appear in `levels` at all.
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [
            {"name": "poison", "kind": "rolling", "value": float("nan"),
             "sigma": None, "direction": "above"},
            {"name": "6M", "kind": "rolling", "value": 195.50,
             "sigma": 8.1, "direction": "reclaim"},
        ]}}}
    path = _write(tmp_path, feed)
    loaded = vwaplink.load_vwap(path)
    rows = [{"ticker": "CRDO", "price": 197.88}]
    vwaplink.attach_vwap(rows, loaded, 2.0)
    names = [lvl["name"] for lvl in rows[0]["vwap"]["levels"]]
    assert names == ["6M"]
    assert rows[0]["vwap"]["nearest"]["name"] == "6M"


def test_infinite_level_value_is_excluded():
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [{"name": "bad", "kind": "rolling", "value": float("inf"),
                    "sigma": None, "direction": "above"},
                   {"name": "6M", "kind": "rolling", "value": 195.50,
                    "sigma": 8.1, "direction": "reclaim"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert [lvl["name"] for lvl in rows[0]["vwap"]["levels"]] == ["6M"]


def test_non_finite_row_price_degrades_to_none():
    rows = [{"ticker": "CRDO", "price": float("nan")}]
    vwaplink.attach_vwap(rows, FEED, 2.0)
    assert rows[0]["vwap"] is None


def test_bool_level_value_is_rejected():
    # bool is an int subclass in Python, so float(True) == 1.0 would
    # otherwise silently pass as a legitimate level value.
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [{"name": "bad", "kind": "rolling", "value": True,
                    "sigma": None, "direction": "above"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    assert rows[0]["vwap"] is None


def test_negative_sigma_does_not_invert_z_stretch():
    # A negative sigma is not a valid standard deviation — the feed is
    # broken, so no z_stretch should be computed from it at all (not a
    # sign-inverted one).
    rows = [{"ticker": "CRDO", "price": 197.88}]
    feed = {**FEED, "tickers": {"CRDO": {
        "price": 190.0, "score": 0.5, "features": {},
        "levels": [{"name": "6M", "kind": "rolling", "value": 195.50,
                    "sigma": -8.1, "direction": "reclaim"}]}}}
    vwaplink.attach_vwap(rows, feed, 2.0)
    lvl = rows[0]["vwap"]["nearest"]
    assert lvl["z_stretch"] is None
    assert lvl["sigma"] is None


def test_freshness_future_dated_generated_clamps_age_to_zero():
    fresh = vwaplink.vwap_freshness({**FEED, "generated": "2026-08-10"}, date(2026, 8, 3))
    assert fresh["age_days"] == 0
    assert fresh["stale"] is False
