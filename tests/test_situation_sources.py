"""Every test stubs ``sources._get`` (FRED) and ``hlfetch._post`` (venue).
tests/conftest.py blocks both by default, so a missed stub fails loudly."""

import urllib.error
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


# ---------- 429 retry ----------

def _http(code):
    return urllib.error.HTTPError("https://x", code, "err", hdrs=None, fp=None)


@pytest.fixture
def waits(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_sleep", seen.append)
    return seen


def test_venue_post_retries_once_after_a_429(monkeypatch, waits):
    answers = [_http(429), "ok"]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    assert sources._venue_post({"type": "x"}) == "ok"
    assert waits == [1]


def test_venue_post_gives_up_after_five_attempts(monkeypatch, waits):
    calls = []

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        calls.append(body)
        raise _http(429)

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    with pytest.raises(urllib.error.HTTPError) as err:
        sources._venue_post({"type": "x"})
    assert err.value.code == 429
    assert len(calls) == 5 and waits == [1, 2, 4, 8]


@pytest.mark.parametrize("exc", [_http(500), TimeoutError("slow")], ids=["http500", "timeout"])
def test_venue_post_raises_other_errors_at_once(monkeypatch, waits, exc):
    def fake_post(body, timeout=hlfetch.TIMEOUT):
        raise exc

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    with pytest.raises(type(exc)):
        sources._venue_post({"type": "x"})
    assert waits == []


def _candle_stub(limited_once=(), limited_always=()):
    candle = [{"t": 1790726400000, "o": "1", "h": "1", "l": "1", "c": "5.3", "v": "1"}]
    hits = {}

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        coin = body["req"]["coin"]
        hits[coin] = hits.get(coin, 0) + 1
        if coin in limited_always or (coin in limited_once and hits[coin] == 1):
            raise _http(429)
        return candle
    return fake_post


def test_fetch_venue_closes_survives_one_429(monkeypatch, waits):
    monkeypatch.setattr(hlfetch, "_post", _candle_stub(limited_once={"para:2Y"}))
    closes = sources.fetch_venue_closes(["para:2Y", "para:10Y"])
    assert set(closes) == {"para:2Y", "para:10Y"}
    assert closes["para:2Y"].iloc[-1] == 5.3


def test_fetch_venue_closes_drops_only_the_market_that_stays_limited(monkeypatch, waits):
    monkeypatch.setattr(hlfetch, "_post", _candle_stub(limited_always={"xyz:CL"}))
    errors = {}
    closes = sources.fetch_venue_closes(["para:2Y", "xyz:CL", "mkts:USBOND"], errors=errors)
    assert set(closes) == {"para:2Y", "mkts:USBOND"}
    assert "rate limited" in errors["xyz:CL candles"]


def test_venue_calls_never_overlap(monkeypatch, waits):
    import threading
    import time
    active, peak, lock = [0], [0], threading.Lock()
    inner = _venue_stub()

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.002)
        with lock:
            active[0] -= 1
        return inner(body, timeout)

    monkeypatch.setattr(sources, "_get", lambda url, timeout=30: "DATE,X\n2026-09-30,1\n")
    monkeypatch.setattr(hlfetch, "_post", fake_post)
    sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert peak[0] == 1


def test_fetch_all_reports_a_rate_limited_market(monkeypatch, waits):
    inner = _venue_stub()

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        if body.get("coin") == "xyz:CL" or body.get("req", {}).get("coin") == "xyz:CL":
            raise _http(429)
        return inner(body, timeout)

    monkeypatch.setattr(sources, "_get", lambda url, timeout=30: "DATE,X\n2026-09-30,1\n")
    monkeypatch.setattr(hlfetch, "_post", fake_post)
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert "rate limited" in out["errors"]["xyz:CL candles"]
    assert "rate limited" in out["errors"]["xyz:CL funding"]
    assert "xyz:CL" not in out["closes"]


# ---------- funding cache ----------

HOUR = 3_600_000
DAY = 86_400_000


def _funding_stub(now_ms, seen, fail=False):
    """The venue stub, with hourly funding rows from ``startTime`` up to ``now_ms``."""
    inner = _venue_stub()

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        if body["type"] != "fundingHistory":
            return inner(body, timeout)
        seen.append((body["coin"], body["startTime"]))
        if fail:
            raise TimeoutError("venue timeout")
        first = -(-body["startTime"] // HOUR) * HOUR
        times = range(first, now_ms + 1, HOUR)[:sources.FUNDING_PAGE]
        return [{"time": t, "fundingRate": "0.00001"} for t in times]
    return fake_post


def _write_cache(path, times, rate=0.00002):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("time_ms,rate\n" + "".join(f"{t},{rate!r}\n" for t in times))


def _ms(ts):
    return int(ts.value // 1_000_000)


def test_first_run_writes_the_funding_cache(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, seen))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=tmp_path)
    assert ("xyz:CL", NOW_MS - sources.FUNDING_DAYS * DAY) in seen
    cache = tmp_path / "xyz_CL.csv"
    assert cache.read_text().splitlines()[0] == "time_ms,rate"
    cached = sources.read_funding_cache(cache)
    assert cached.equals(out["funding"]["xyz:CL"])
    assert len(cached) == sources.FUNDING_DAYS * 24
    assert sorted(f.name for f in tmp_path.iterdir()) == sorted(
        m.replace(":", "_") + ".csv" for m in sources.FUNDING_MARKETS)


def test_second_run_asks_only_for_rows_after_the_last_cached_time(monkeypatch, tmp_path):
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, []))
    first = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=tmp_path)["funding"]["para:10Y"]
    later, seen = NOW_MS + 3 * HOUR, []
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(later, seen))
    second = sources.fetch_all(TODAY, now_ms=later, cache_dir=tmp_path)["funding"]["para:10Y"]
    assert ("para:10Y", _ms(first.index[-1]) + 1) in seen
    assert len([s for s in seen if s[0] == "para:10Y"]) == 1
    assert second.index[-1] > first.index[-1]
    assert sources.read_funding_cache(tmp_path / "para_10Y.csv").equals(second)


def test_the_cache_is_trimmed_to_funding_days(monkeypatch, tmp_path):
    old = [NOW_MS - 200 * DAY + i * HOUR for i in range(200 * 24)]
    _write_cache(tmp_path / "xyz_TLT.csv", old)
    seen = []
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, seen))
    s = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=tmp_path)["funding"]["xyz:TLT"]
    cutoff = NOW_MS - sources.FUNDING_DAYS * DAY
    assert _ms(s.index[0]) >= cutoff and _ms(s.index[-1]) <= NOW_MS
    assert _ms(sources.read_funding_cache(tmp_path / "xyz_TLT.csv").index[0]) >= cutoff
    assert ("xyz:TLT", old[-1] + 1) in seen


def test_a_failed_fetch_falls_back_to_the_cache_and_records_the_error(monkeypatch, tmp_path):
    times = [NOW_MS - DAY + i * HOUR for i in range(24)]
    _write_cache(tmp_path / "xyz_CL.csv", times)
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, [], fail=True))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=tmp_path)
    assert len(out["funding"]["xyz:CL"]) == 24
    assert out["funding"]["xyz:CL"].iloc[-1] == 0.00002
    assert out["errors"]["xyz:CL funding"] == "venue timeout"
    assert "para:10Y" not in out["funding"]          # no cache, failed fetch: absent


def test_an_unreadable_cache_is_rebuilt(monkeypatch, tmp_path, capsys):
    (tmp_path / "xyz_CL.csv").write_text("time_ms,rate\n12,abc\nnot,a,cache\n")
    seen = []
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, seen))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=tmp_path)
    assert "xyz_CL.csv unreadable" in capsys.readouterr().err
    assert ("xyz:CL", NOW_MS - sources.FUNDING_DAYS * DAY) in seen
    assert sources.read_funding_cache(tmp_path / "xyz_CL.csv").equals(out["funding"]["xyz:CL"])


def test_fetch_all_without_a_cache_dir_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, []))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert len(out["funding"]["xyz:CL"]) == sources.FUNDING_DAYS * 24
    assert list(tmp_path.iterdir()) == []



def test_a_cache_that_cannot_be_written_is_a_warning(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    monkeypatch.setattr(hlfetch, "_post", _funding_stub(NOW_MS, []))
    out = sources.fetch_all(TODAY, now_ms=NOW_MS, cache_dir=blocker)
    assert len(out["funding"]["xyz:CL"]) == sources.FUNDING_DAYS * 24
    assert "xyz_CL.csv not saved" in capsys.readouterr().err


# ---------- venue time limit ----------

def test_a_spent_budget_skips_the_remaining_venue_calls(monkeypatch):
    now, calls = [0.0], []
    inner = _venue_stub()

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        calls.append(body)
        now[0] += 50                      # each call takes 50 s
        return inner(body, timeout)

    monkeypatch.setattr(sources, "_clock", lambda: now[0])
    monkeypatch.setattr(hlfetch, "_post", fake_post)
    out = sources.fetch_all(TODAY, now_ms=NOW_MS)
    assert len(calls) == 2                # at 0 s and 50 s; at 100 s the 90 s budget is spent
    assert set(out["closes"]) == {"para:2Y", "para:10Y"}
    assert out["errors"]["para:30Y candles"] == "skipped: time limit"
    assert out["errors"]["xyz context"] == "skipped: time limit"
    assert out["errors"]["xyz:CL funding"] == "skipped: time limit"


def test_a_wait_that_would_cross_the_budget_is_not_taken(monkeypatch):
    now, waits = [0.0], []

    def fake_sleep(s):
        waits.append(s)
        now[0] += s

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        raise _http(429)

    monkeypatch.setattr(sources, "_clock", lambda: now[0])
    monkeypatch.setattr(sources, "_sleep", fake_sleep)
    monkeypatch.setattr(hlfetch, "_post", fake_post)
    with pytest.raises(urllib.error.HTTPError) as err:
        sources._venue_post({"type": "x"}, deadline=5)
    assert err.value.code == 429
    assert waits == [1, 2]                # the 4 s wait would end at 7 s, past 5 s


def test_a_429_wait_prints_one_line(monkeypatch, waits, capsys):
    answers = [_http(429), "ok"]

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    assert sources._venue_post({"type": "x"}) == "ok"
    assert capsys.readouterr().err == "warning: situation · venue rate limited, waiting 1 s\n"
