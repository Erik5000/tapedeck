"""Every test stubs ``sources._get`` (FRED) and ``hlfetch._post`` (venue).
tests/conftest.py blocks both by default, so a missed stub fails loudly."""

from datetime import date

import pytest

from tapedeck import hlfetch
from tapedeck.situation import sources

TODAY = date(2026, 10, 1)
NOW_MS = 1_790_000_000_000


def test_parse_fred_csv_new_header_and_missing_dots():
    text = "observation_date,T10YIE\n2026-09-28,2.35\n2026-09-29,.\n2026-09-30,2.36\n"
    s = sources.parse_fred_csv(text)
    assert list(s.values) == [2.35, 2.36]
    assert s.index[-1].date() == date(2026, 9, 30)


def test_parse_fred_csv_old_header_and_empty_cell():
    s = sources.parse_fred_csv("DATE,DGS10\n2026-09-29,4.12\n2026-09-30,\n")
    assert list(s.values) == [4.12]


@pytest.mark.parametrize("text", ["", "garbage", "DATE,DGS10\n", "<html>error</html>"])
def test_parse_fred_csv_unusable_text_is_none(text):
    assert sources.parse_fred_csv(text) is None


def test_fetch_fred_asks_for_four_years(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_get",
                        lambda url, timeout=30: seen.append(url) or "DATE,X\n2026-09-30,1\n")
    sources.fetch_fred("DGS10", TODAY)
    assert "id=DGS10" in seen[0] and "cosd=2022-10-02" in seen[0]


def test_parse_contexts_picks_wanted_markets_and_casts_strings():
    resp = [{"universe": [{"name": "para:10Y"}, {"name": "para:BTCD"}, "junk"]},
            [{"markPx": "5.31", "oraclePx": "5.32", "funding": "0.0000012",
              "openInterest": "444153.8", "dayNtlVlm": "762557.9"},
             {"markPx": "1"}, {"markPx": "2"}]]
    out = sources.parse_contexts(resp, {"para:10Y"})
    assert out == {"para:10Y": {"mark": 5.31, "oracle": 5.32, "funding": 0.0000012,
                                "oi": 444153.8, "volume_24h": 762557.9}}


def test_parse_contexts_malformed_response_is_empty():
    assert sources.parse_contexts(None, {"para:10Y"}) == {}
    assert sources.parse_contexts({"universe": []}, {"para:10Y"}) == {}


def test_fetch_funding_pages_until_a_short_page(monkeypatch):
    calls = []
    page1 = [{"time": NOW_MS - 1000 * (600 - i), "fundingRate": "0.00001"} for i in range(500)]
    page2 = [{"time": NOW_MS - 10, "fundingRate": "0.00002"}]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        calls.append(body)
        return page1 if len(calls) == 1 else page2

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    s = sources.fetch_funding("para:10Y", NOW_MS)
    assert len(s) == 501
    assert calls[1]["startTime"] == page1[-1]["time"] + 1
    assert calls[0]["coin"] == "para:10Y"


def test_parse_funding_skips_bad_rows():
    rows = [{"time": NOW_MS, "fundingRate": "0.00001"}, {"time": "x"}, {"fundingRate": "1"},
            {"time": NOW_MS + 1, "fundingRate": "nan"}]
    assert len(sources.parse_funding(rows)) == 1
    assert sources.parse_funding([]) is None


def _venue_stub(contexts_ok=True):
    candle = [{"t": 1790726400000, "o": "1", "h": "1", "l": "1", "c": "5.3", "v": "1"}]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        if body["type"] == "candleSnapshot":
            return candle if body["req"]["coin"] != "para:30Y" else []
        if body["type"] == "metaAndAssetCtxs":
            if not contexts_ok:
                raise TimeoutError("venue timeout")
            return [{"universe": [{"name": "para:10Y"}]}, [{"markPx": "5.3", "openInterest": "1"}]]
        if body["type"] == "fundingHistory":
            return [{"time": NOW_MS, "fundingRate": "0.00001"}]
        raise AssertionError(body)
    return fake_post


def test_fetch_all_collects_each_source_and_records_failures(monkeypatch, capsys):
    def fake_get(url, timeout=30):
        if "id=DGS30" in url:
            raise TimeoutError("timed out")
        return "DATE,X\n2026-09-30,1.5\n"

    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(hlfetch, "_post", _venue_stub())
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert "DGS10" in out["fred"] and "DGS30" not in out["fred"]
    assert out["errors"]["FRED DGS30"] == "timed out"
    assert "para:10Y" in out["closes"] and "para:30Y" not in out["closes"]
    assert out["errors"]["para:30Y candles"] == "no candles"
    assert out["ctx"]["para:10Y"]["mark"] == 5.3
    assert set(out["funding"]) == set(sources.FUNDING_MARKETS)
    assert "FRED DGS30" in capsys.readouterr().err


def test_fetch_all_context_failure_is_one_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(sources, "_get", lambda url, timeout=30: "DATE,X\n2026-09-30,1\n")
    monkeypatch.setattr(hlfetch, "_post", _venue_stub(contexts_ok=False))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert out["ctx"] == {}
    assert out["errors"]["para context"] == "venue timeout"


def test_fetch_all_with_the_network_blocked_returns_empty_and_never_raises():
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert out["fred"] == {} and out["closes"] == {} and out["ctx"] == {} and out["funding"] == {}
    assert len(out["errors"]) > 0
