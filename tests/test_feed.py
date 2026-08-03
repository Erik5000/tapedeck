from datetime import date

from tapedeck import feed


def row(**over):
    base = {"ticker": "AMD", "name": "AMD", "group": "g1", "price": 100.0,
            "pct_1d": 1.0, "pct_ytd": 5.0, "pct_off_high": -10.0, "rs_1m": 2.0,
            "rs_rank": 1, "pe": None, "ps": None, "market_cap": None,
            "earnings_date": None, "gap_pct": None, "tv_symbol": "NASDAQ:AMD",
            "sma": {"50": {"sma": 90.0, "above": True, "dist_pct": 11.1}},
            "position": None, "spark": [1, 2, 3]}
    base.update(over)
    return base


def wl(**over):
    base = {"name": "book", "title": "Book", "benchmark": "SPY",
            "rows": [row()], "summary": None, "alerts": [], "diff": None}
    base.update(over)
    return base


def test_build_feed_shape_and_defaults():
    out = feed.build_feed([wl()], today=date(2026, 7, 31), data_date="2026-07-31")
    assert out["date"] == "2026-07-31"
    assert out["data_date"] == "2026-07-31"
    lst = out["lists"][0]
    assert lst["name"] == "book"
    assert lst["baskets"] == []          # always present
    assert lst["cockpit"] is None        # no cockpit attached
    slim = lst["rows"][0]
    assert slim["ticker"] == "AMD"
    assert slim["sma_above"] == {"50": True}
    assert "spark" not in slim           # heavy fields dropped
    assert "position" not in slim        # falsy position dropped


def test_build_feed_carries_baskets_and_cockpit():
    baskets = [{"group": "g1", "n": 1, "avg_pct_1d": 1.0, "med_rs_1m": 2.0,
                "med_rs_3m": None, "breadth_sma50_pct": 100.0, "med_pct_off_high": -10.0}]
    cockpit = {"regenerated": "2026-07-28", "regime": "higher-for-longer",
               "freeze": "PARTIAL-LIFT", "triad_refreshed": "2026-07-31",
               "freeze_note": None, "sleeves": [], "triad": [],
               "open_decisions": [{"id": 5, "title": "Monthly thesis review"}]}
    fresh = {"regenerated": "2026-07-28", "age_days": 3,
             "triad_refreshed": "2026-07-31", "triad_age_days": 0}
    out = feed.build_feed([wl(baskets=baskets, cockpit=cockpit, cockpit_fresh=fresh)])
    lst = out["lists"][0]
    assert lst["baskets"] == baskets
    assert lst["cockpit"]["freeze"] == "PARTIAL-LIFT"
    assert lst["cockpit"]["age_days"] == 3
    assert lst["cockpit"]["triad_age_days"] == 0
    assert lst["cockpit"]["open_decisions"][0]["id"] == 5


def test_slim_cockpit_none_safe():
    assert feed.slim_cockpit(None, None) is None
    slim = feed.slim_cockpit({"regenerated": None, "freeze": "ON"}, None)
    assert slim["freeze"] == "ON"
    assert slim["age_days"] is None
