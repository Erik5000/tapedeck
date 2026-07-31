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
