from datetime import date

from tapedeck import alerts

TODAY = date(2026, 7, 31)


def row(**overrides):
    base = {
        "ticker": "TST",
        "new_52w": None,
        "sma_cross": {},
        "gap_pct": 0.0,
        "earnings_date": None,
    }
    base.update(overrides)
    return base


def kinds(result):
    return [(a["ticker"], a["kind"]) for a in result]


def test_new_52w_high_alert():
    result = alerts.build_alerts([row(ticker="NVDA", new_52w="high")], TODAY)
    assert ("NVDA", "52w_high") in kinds(result)


def test_sma_cross_alert():
    result = alerts.build_alerts([row(ticker="HIVE", sma_cross={"50": "lost"})], TODAY)
    assert ("HIVE", "sma_lost") in kinds(result)
    assert "50" in [a["text"] for a in result][0]


def test_gap_alert_fires_above_5pct():
    result = alerts.build_alerts([row(ticker="IREN", gap_pct=6.2)], TODAY)
    assert ("IREN", "gap") in kinds(result)


def test_gap_alert_quiet_below_5pct():
    result = alerts.build_alerts([row(ticker="IREN", gap_pct=3.0)], TODAY)
    assert result == []


def test_earnings_within_7_days():
    result = alerts.build_alerts([row(ticker="AMD", earnings_date="2026-08-03")], TODAY)
    assert ("AMD", "earnings") in kinds(result)
    assert "3d" in result[0]["text"]


def test_earnings_beyond_7_days_quiet():
    result = alerts.build_alerts([row(ticker="AMD", earnings_date="2026-08-15")], TODAY)
    assert result == []


def test_earnings_in_past_quiet():
    result = alerts.build_alerts([row(ticker="AMD", earnings_date="2026-07-20")], TODAY)
    assert result == []


def _row(ticker, levels, in_range_any=True):
    return {"ticker": ticker,
            "vwap": {"score": None, "features": {}, "levels": levels,
                     "nearest": levels[0], "in_range_any": in_range_any}}


def test_in_range_level_produces_one_alert():
    rows = [_row("CRDO", [{"name": "6M", "kind": "rolling", "pct_distance": -1.2,
                           "in_range": True, "direction": "reclaim"}])]
    out = alerts.build_vwap_alerts(rows)
    assert len(out) == 1
    assert out[0]["ticker"] == "CRDO"
    assert out[0]["kind"] == "vwap"
    assert out[0]["text"] == "1.2% below 6M VWAP · reclaiming"


def test_above_level_reads_above():
    rows = [_row("BE", [{"name": "1M", "kind": "rolling", "pct_distance": 0.8,
                         "in_range": True, "direction": "reject"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.8% above 1M VWAP · rejecting"


def test_support_level_reads_state_suffix():
    rows = [_row("AAPL", [{"name": "1M", "kind": "rolling", "pct_distance": -0.5,
                           "in_range": True, "direction": "support"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.5% below 1M VWAP · acting as support"


def test_resistance_level_reads_state_suffix():
    rows = [_row("AAPL", [{"name": "1M", "kind": "rolling", "pct_distance": 0.5,
                           "in_range": True, "direction": "resistance"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.5% above 1M VWAP · acting as resistance"


def test_only_nearest_level_alerts():
    rows = [_row("FN", [
        {"name": "1M", "kind": "rolling", "pct_distance": 0.3, "in_range": True, "direction": "support"},
        {"name": "3M", "kind": "rolling", "pct_distance": 1.9, "in_range": True, "direction": "resistance"},
    ])]
    out = alerts.build_vwap_alerts(rows)
    assert len(out) == 1
    assert "1M" in out[0]["text"]


def test_severity_mapping_for_all_real_directions():
    def sev(direction):
        rows = [_row("X", [{"name": "1M", "kind": "rolling", "pct_distance": 0.1,
                            "in_range": True, "direction": direction}])]
        return alerts.build_vwap_alerts(rows)[0]["severity"]
    assert sev("support") == "good"
    assert sev("resistance") == "bad"
    assert sev("reclaim") == "good"
    assert sev("reject") == "bad"
    assert sev("na") == "warn"


def test_na_direction_omits_suffix_and_warns():
    rows = [_row("AAPL", [{"name": "1M", "kind": "rolling", "pct_distance": 0.5,
                           "in_range": True, "direction": "na"}])]
    out = alerts.build_vwap_alerts(rows)
    assert out[0]["text"] == "0.5% above 1M VWAP"
    assert out[0]["severity"] == "warn"


def test_out_of_range_produces_nothing():
    rows = [_row("CIEN", [{"name": "6M", "kind": "rolling", "pct_distance": 4.5,
                           "in_range": False, "direction": "resistance"}], in_range_any=False)]
    assert alerts.build_vwap_alerts(rows) == []


def test_row_without_vwap_produces_nothing():
    assert alerts.build_vwap_alerts([{"ticker": "NVDA", "vwap": None}]) == []
    assert alerts.build_vwap_alerts([{"ticker": "NVDA"}]) == []


def test_missing_direction_omits_suffix_and_warns():
    rows = [_row("PLTR", [{"name": "1M", "kind": "rolling", "pct_distance": 0.5, "in_range": True}])]
    out = alerts.build_vwap_alerts(rows)
    assert out[0]["text"] == "0.5% above 1M VWAP"
    assert out[0]["severity"] == "warn"


def test_unrecognised_direction_omits_suffix_and_warns():
    rows = [_row("PLTR", [{"name": "1M", "kind": "rolling", "pct_distance": 0.5,
                           "in_range": True, "direction": "newthing"}])]
    out = alerts.build_vwap_alerts(rows)
    assert out[0]["text"] == "0.5% above 1M VWAP"
    assert out[0]["severity"] == "warn"


def test_fib_kind_omits_vwap_suffix():
    # A fib retracement/extension is a static price projection, not a VWAP
    # line — "Fib 0.786" must read on its own, not "Fib 0.786 VWAP".
    rows = [_row("CRDO", [{"name": "Fib 0.786", "kind": "fib", "pct_distance": 0.4,
                           "in_range": True, "direction": "support"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.4% above Fib 0.786 · acting as support"


def test_non_fib_kind_keeps_vwap_suffix():
    rows = [_row("CRDO", [{"name": "6M Rolling", "kind": "rolling", "pct_distance": 0.4,
                           "in_range": True, "direction": "support"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.4% above 6M Rolling VWAP · acting as support"


def test_missing_level_name_renders_na():
    rows = [_row("CRDO", [{"name": None, "kind": "rolling", "pct_distance": 0.4,
                           "in_range": True, "direction": "support"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.4% above n/a VWAP · acting as support"


def test_pct_distance_zero_reads_above():
    rows = [_row("ORCL", [{"name": "1M", "kind": "rolling", "pct_distance": 0.0,
                           "in_range": True, "direction": "support"}])]
    assert alerts.build_vwap_alerts(rows)[0]["text"] == "0.0% above 1M VWAP · acting as support"


def test_in_range_any_true_but_no_level_flagged_produces_nothing():
    """Inconsistent data: in_range_any says True but every level's in_range is False."""
    rows = [_row("MSTR", [{"name": "1M", "kind": "rolling", "pct_distance": 4.0,
                           "in_range": False, "direction": "resistance"}], in_range_any=True)]
    assert alerts.build_vwap_alerts(rows) == []


def test_empty_levels_list_produces_nothing():
    rows = [{"ticker": "SMCI", "vwap": {"score": None, "features": {}, "levels": [],
                                        "nearest": None, "in_range_any": True}}]
    assert alerts.build_vwap_alerts(rows) == []


def test_vwap_missing_levels_key_produces_nothing_no_error():
    rows = [{"ticker": "COIN", "vwap": {"score": None, "features": {}, "in_range_any": True}}]
    assert alerts.build_vwap_alerts(rows) == []


def test_vwap_not_a_dict_produces_nothing_no_error():
    rows = [{"ticker": "RIOT", "vwap": "garbage"}]
    assert alerts.build_vwap_alerts(rows) == []
