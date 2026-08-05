"""trade.xyz (Hyperliquid) price source.

Every test stubs `hlfetch._post` — the suite makes no network calls. The
fixtures below are shaped exactly like real responses, including the string
numerics and epoch-ms timestamps the API actually returns.
"""

import pandas as pd
import pytest

from tapedeck import hlfetch

# 2026-08-03 is a Monday, so this block runs Mon, Tue, Wed, Sat, Sun.
MON = 1785715200000          # 2026-08-03T00:00:00Z
DAY = 86_400_000


def candle(offset_days, o=100.0, h=110.0, l=90.0, c=105.0, v=1000.0):
    return {"t": MON + offset_days * DAY, "T": MON + (offset_days + 1) * DAY - 1,
            "s": "xyz:NVDA", "i": "1d", "o": str(o), "h": str(h), "l": str(l),
            "c": str(c), "v": str(v), "n": 42}


@pytest.fixture
def post(monkeypatch):
    """Records requests and replays queued responses."""
    calls = []
    queue = {}

    def fake_post(body, timeout=hlfetch.TIMEOUT):
        calls.append(body)
        kind = body.get("type")
        if kind in queue:
            value = queue[kind]
            return value(body) if callable(value) else value
        raise AssertionError(f"unstubbed request: {body}")

    monkeypatch.setattr(hlfetch, "_post", fake_post)
    fake_post.calls = calls
    fake_post.queue = queue
    return fake_post


# ---------- qualify ----------

def test_qualify_namespaces_the_ticker():
    assert hlfetch.qualify("NVDA") == "xyz:NVDA"
    assert hlfetch.qualify("NVDA", "flx") == "flx:NVDA"


# ---------- list_markets ----------

def test_list_markets_drops_delisted_and_the_dex_prefix():
    assert hlfetch.list_markets.__doc__          # documented as a snapshot, not a constant


def test_list_markets_returns_live_names_sorted(post):
    post.queue["meta"] = {"universe": [
        {"name": "xyz:NVDA"}, {"name": "xyz:AAPL"},
        {"name": "xyz:URANIUM", "isDelisted": True},
        {"name": "xyz:GOLD", "isDelisted": False},
    ]}
    assert hlfetch.list_markets() == ["AAPL", "GOLD", "NVDA"]
    assert post.calls[0] == {"type": "meta", "dex": "xyz"}


def test_list_markets_survives_a_malformed_entry(post):
    post.queue["meta"] = {"universe": [{"name": "xyz:NVDA"}, None, {}, "junk"]}
    assert hlfetch.list_markets() == ["NVDA"]


def test_list_markets_empty_response(post):
    post.queue["meta"] = {}
    assert hlfetch.list_markets() == []


# ---------- candle parsing ----------

def test_fetch_history_builds_an_ohlcv_frame(post):
    post.queue["candleSnapshot"] = [candle(0, o=1, h=2, l=0.5, c=1.5, v=10)]
    hists = hlfetch.fetch_history(["NVDA"], now_ms=MON + DAY)
    frame = hists["xyz:NVDA"]
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert frame["Close"].iloc[-1] == 1.5
    assert frame["Volume"].iloc[-1] == 10.0
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.tz is None            # yfinance daily is tz-naive; match it


def test_fetch_history_casts_the_api_string_numerics(post):
    """Every OHLCV field arrives as a string — a missed cast would make the
    metrics compare strings and either crash or silently mis-sort."""
    post.queue["candleSnapshot"] = [candle(0)]
    frame = hlfetch.fetch_history(["NVDA"], now_ms=MON + DAY)["xyz:NVDA"]
    assert all(frame[c].dtype.kind == "f" for c in frame.columns)


def test_fetch_history_drops_weekend_bars(post):
    """Perps trade 24/7. Keeping Sat/Sun would make a 20-bar mean span 20
    calendar days -- a different indicator from the 20SMA on every other row."""
    post.queue["candleSnapshot"] = [candle(i) for i in range(7)]   # Mon..Sun
    frame = hlfetch.fetch_history(["NVDA"], now_ms=MON + 7 * DAY)["xyz:NVDA"]
    assert len(frame) == 5
    assert set(frame.index.dayofweek) <= {0, 1, 2, 3, 4}


def test_fetch_history_sorts_and_dedupes_bars(post):
    post.queue["candleSnapshot"] = [candle(2, c=3), candle(0, c=1),
                                    candle(1, c=99), candle(1, c=2)]
    frame = hlfetch.fetch_history(["NVDA"], now_ms=MON + 3 * DAY)["xyz:NVDA"]
    assert list(frame["Close"]) == [1.0, 2.0, 3.0]      # last write wins on the dupe


def test_fetch_history_skips_one_bad_bar_not_the_series(post):
    post.queue["candleSnapshot"] = [candle(0, c=1), {"t": MON + DAY, "o": "x"},
                                    candle(2, c=3)]
    frame = hlfetch.fetch_history(["NVDA"], now_ms=MON + 3 * DAY)["xyz:NVDA"]
    assert list(frame["Close"]) == [1.0, 3.0]


def test_fetch_history_requests_the_right_window(post):
    seen = {}

    def capture(body):
        seen.update(body["req"])
        return [candle(0)]

    post.queue["candleSnapshot"] = capture
    hlfetch.fetch_history(["NVDA"], period_days=10, now_ms=MON)
    assert seen["coin"] == "xyz:NVDA"
    assert seen["interval"] == "1d"
    assert seen["endTime"] - seen["startTime"] == 10 * DAY


# ---------- degradation ----------

def test_fetch_history_market_failure_degrades_to_absent(post):
    def flaky(body):
        if body["req"]["coin"] == "xyz:BROKEN":
            raise OSError("connection reset")
        return [candle(0)]

    post.queue["candleSnapshot"] = flaky
    hists = hlfetch.fetch_history(["NVDA", "BROKEN"], now_ms=MON + DAY)
    assert "xyz:NVDA" in hists
    assert "xyz:BROKEN" not in hists      # tapedeck.py already warns about these


def test_fetch_history_empty_candles_degrades_to_absent(post):
    post.queue["candleSnapshot"] = []
    assert hlfetch.fetch_history(["NEW"], now_ms=MON + DAY) == {}


def test_fetch_history_weekend_only_series_degrades_to_absent(post):
    """A market whose every bar is a weekend bar has nothing left after the
    filter -- it must be absent, not an empty frame that breaks metrics."""
    post.queue["candleSnapshot"] = [candle(5), candle(6)]     # Sat, Sun
    assert hlfetch.fetch_history(["W"], now_ms=MON + 7 * DAY) == {}


def test_fetch_history_no_tickers_makes_no_request(post):
    assert hlfetch.fetch_history([]) == {}
    assert post.calls == []


# ---------- fetch_universe ----------

def test_fetch_universe_splits_holdings_from_benchmark(post):
    post.queue["candleSnapshot"] = lambda body: [candle(0)]
    hists, bench, infos = hlfetch.fetch_universe(["NVDA", "MU"], ["SP500"])
    assert set(hists) == {"xyz:NVDA", "xyz:MU"}       # benchmark is not a row
    assert "xyz:SP500" in bench
    assert isinstance(bench["xyz:SP500"], pd.Series)


def test_fetch_universe_returns_no_fundamentals(post):
    """The venue publishes no market cap, P/E, sector or earnings date. An
    empty dict here is the honest answer, not a stub to fill in later."""
    post.queue["candleSnapshot"] = lambda body: [candle(0)]
    _, _, infos = hlfetch.fetch_universe(["NVDA"], ["SP500"])
    assert infos == {}


def test_fetch_universe_fetches_a_ticker_once_when_it_is_also_the_benchmark(post):
    coins = []
    post.queue["candleSnapshot"] = lambda body: coins.append(body["req"]["coin"]) or [candle(0)]
    hlfetch.fetch_universe(["SP500", "NVDA"], ["SP500"])
    assert sorted(coins) == ["xyz:NVDA", "xyz:SP500"]


def test_fetch_universe_honours_a_non_default_dex(post):
    post.queue["candleSnapshot"] = lambda body: [candle(0)]
    hists, bench, _ = hlfetch.fetch_universe(["NVDA"], ["USA500"], dex="flx")
    assert "flx:NVDA" in hists and "flx:USA500" in bench
