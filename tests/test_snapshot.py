from bloom import snapshot


def rows(price_nvda=100.0, nvda_above_20=False):
    return [
        {
            "ticker": "NVDA",
            "price": price_nvda,
            "sma": {"20": {"above": nvda_above_20}, "50": {"above": True}, "200": {"above": True}},
        },
        {
            "ticker": "AMD",
            "price": 480.0,
            "sma": {"20": {"above": True}, "50": {"above": True}, "200": {"above": True}},
        },
    ]


def test_save_and_find_previous_roundtrip(tmp_path):
    snapshot.save_snapshot(rows(), tmp_path, "2026-07-30")
    loaded = snapshot.find_previous(tmp_path)
    assert loaded["date"] == "2026-07-30"
    assert loaded["rows"][0]["ticker"] == "NVDA"


def test_find_previous_returns_latest(tmp_path):
    snapshot.save_snapshot(rows(price_nvda=90.0), tmp_path, "2026-07-29")
    snapshot.save_snapshot(rows(price_nvda=100.0), tmp_path, "2026-07-30")
    assert snapshot.find_previous(tmp_path)["date"] == "2026-07-30"


def test_find_previous_empty_dir(tmp_path):
    assert snapshot.find_previous(tmp_path) is None


def test_diff_detects_movers_and_sma_flips(tmp_path):
    prev = {"date": "2026-07-30", "rows": rows(price_nvda=100.0, nvda_above_20=False)}
    curr = rows(price_nvda=110.0, nvda_above_20=True)
    diff = snapshot.diff_snapshots(prev, curr)
    assert diff["since"] == "2026-07-30"
    movers = {m["ticker"]: m["change_pct"] for m in diff["movers"]}
    assert movers["NVDA"] == 10.0
    assert {"ticker": "NVDA", "window": "20", "now": "above"} in diff["sma_flips"]


def test_diff_flags_new_tickers(tmp_path):
    prev = {"date": "2026-07-30", "rows": rows()}
    curr = rows() + [{"ticker": "TSM", "price": 400.0, "sma": {}}]
    diff = snapshot.diff_snapshots(prev, curr)
    assert diff["added"] == ["TSM"]
