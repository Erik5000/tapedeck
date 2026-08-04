"""Integration coverage for the CLI wiring added in task 4: vwap/vwap_alert_pct
must reach every row, and attach_vwap must run before build_alerts so Task 5's
alert rules (which read row["vwap"]) actually see data.

`tapedeck.py` (the script at repo root) is loaded via importlib because the
name `tapedeck` is already claimed by the `tapedeck/` package — a normal
`import tapedeck` would resolve to the package, not this script. No network
calls are made: `fetch.fetch_universe` and `pipeline.build_rows` are stubbed,
and `--source yahoo` skips the TradingView screener entirely.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location("tapedeck_cli_under_test", ROOT_DIR / "tapedeck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_feed(tmp_path):
    p = tmp_path / "vwap-latest.json"
    p.write_text(json.dumps({
        "schema": 1,
        "generated": "2026-08-03",
        "tickers": {
            "NVDA": {"score": 55.0, "levels": [
                {"name": "anchor", "kind": "anchored", "value": 100.0,
                 "sigma": None, "direction": "na"},
            ]},
        },
    }))
    return p


def _stub_no_network(monkeypatch, price=101.0):
    """Stub fetch + build_rows so no network call happens and rows are fully
    formed (using the real _empty_row helper) except for the vwap key, which
    is left for attach_vwap to set."""
    from tapedeck import fetch as fetch_mod, pipeline as pipeline_mod

    monkeypatch.setattr(fetch_mod, "fetch_universe", lambda *a, **k: ({}, {}, {}))

    def fake_build_rows(hists, bench_close, infos, holdings, today, tv=None):
        rows = []
        for h in holdings:
            row = pipeline_mod._empty_row(h, infos.get(h["ticker"]) or {})
            row["price"] = price
            rows.append(row)
        return rows, None

    monkeypatch.setattr(pipeline_mod, "build_rows", fake_build_rows)


def test_directory_mode_attaches_vwap_before_alerts(tmp_path, monkeypatch):
    from tapedeck import alerts as alerts_mod

    _stub_no_network(monkeypatch)
    feed_path = _write_feed(tmp_path)

    wl_dir = tmp_path / "watchlists"
    wl_dir.mkdir()
    (wl_dir / "book.yaml").write_text(
        f"vwap: {feed_path}\nvwap_alert_pct: 1.5\nholdings:\n  - ticker: NVDA\n")
    (tmp_path / "output").mkdir()

    seen = []
    real_build_alerts = alerts_mod.build_alerts

    def spy_build_alerts(rows, today):
        seen.append([row.get("vwap") for row in rows])
        return real_build_alerts(rows, today)

    monkeypatch.setattr(alerts_mod, "build_alerts", spy_build_alerts)

    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["tapedeck.py", "--no-open", "--source", "yahoo"])

    cli.main()

    assert len(seen) == 1, "build_alerts should run once, for the one watchlist"
    [vwap_seen_by_alerts] = seen
    # attach_vwap must have already populated row["vwap"] by the time
    # build_alerts sees the rows -- this is the ordering requirement.
    assert vwap_seen_by_alerts[0] is not None
    assert vwap_seen_by_alerts[0]["nearest"]["value"] == 100.0
    # price 101 vs level 100 is within the configured 1.5% band
    assert vwap_seen_by_alerts[0]["in_range_any"] is True


def test_directory_mode_vwap_alert_pct_zero_reaches_attach_vwap_unchanged(tmp_path, monkeypatch):
    """vwap_alert_pct: 0 is a legal, meaningful value ("alert only on an exact
    touch"). Regression coverage for config.py's `vwap_alert_pct = raw.get(...)
    ` followed by an explicit `is None` check rather than `or 2.0`, which
    would have silently turned 0 into the 2.0 default. This asserts the exact
    float 0.0 reaches vwaplink.attach_vwap, and that the resulting in_range
    computation reflects a zero band (not the 2.0 default -- which would also
    mark this row in-range and mask the bug)."""
    from tapedeck import vwaplink as vwaplink_mod

    _stub_no_network(monkeypatch)
    # price 101 vs level 100 -> pct_distance = 1.0%: in range for the 2.0
    # default, but NOT in range for a true 0% band -- this distinguishes the
    # bug (silently keeps 2.0) from the fix (uses 0.0).
    feed_path = _write_feed(tmp_path)

    wl_dir = tmp_path / "watchlists"
    wl_dir.mkdir()
    (wl_dir / "book.yaml").write_text(
        f"vwap: {feed_path}\nvwap_alert_pct: 0\nholdings:\n  - ticker: NVDA\n")
    (tmp_path / "output").mkdir()

    captured_pct = []
    real_attach_vwap = vwaplink_mod.attach_vwap

    def spy_attach_vwap(rows, feed, alert_pct):
        captured_pct.append(alert_pct)
        return real_attach_vwap(rows, feed, alert_pct)

    monkeypatch.setattr(vwaplink_mod, "attach_vwap", spy_attach_vwap)

    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["tapedeck.py", "--no-open", "--source", "yahoo"])

    cli.main()

    assert captured_pct == [0.0]


def test_directory_mode_missing_vwap_key_degrades_to_none(tmp_path, monkeypatch):
    """A watchlist with no vwap: key at all must still work (default None feed,
    default 2.0 alert_pct) -- this is the pre-feature behavior this task must
    not break."""
    from tapedeck import alerts as alerts_mod

    _stub_no_network(monkeypatch)

    wl_dir = tmp_path / "watchlists"
    wl_dir.mkdir()
    (wl_dir / "book.yaml").write_text("holdings:\n  - ticker: NVDA\n")
    (tmp_path / "output").mkdir()

    seen = []
    real_build_alerts = alerts_mod.build_alerts

    def spy_build_alerts(rows, today):
        seen.append([row.get("vwap") for row in rows])
        return real_build_alerts(rows, today)

    monkeypatch.setattr(alerts_mod, "build_alerts", spy_build_alerts)

    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["tapedeck.py", "--no-open", "--source", "yahoo"])

    cli.main()  # must not raise

    assert seen == [[None]]
    assert (tmp_path / "output" / f"tapedeck-{__import__('datetime').date.today().isoformat()}.html").exists()


def test_single_config_mode_carries_vwap_keys(tmp_path, monkeypatch):
    """The separate --config code path builds its own watchlist dict literal;
    it must carry the vwap/vwap_alert_pct keys too or it KeyErrors."""
    _stub_no_network(monkeypatch)
    feed_path = _write_feed(tmp_path)

    cfg_path = tmp_path / "solo.yaml"
    cfg_path.write_text(f"vwap: {feed_path}\nvwap_alert_pct: 4\nholdings:\n  - ticker: NVDA\n")
    (tmp_path / "output").mkdir()

    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv",
                         ["tapedeck.py", "--config", str(cfg_path), "--no-open", "--source", "yahoo"])

    cli.main()  # must not raise KeyError: 'vwap'

    feed_json = json.loads((tmp_path / "output" / "tapedeck-latest.json").read_text())
    assert feed_json["lists"][0]["name"] == "solo"


# ---------- --serve ----------
#
# `--serve` must not fetch anything: it shows the run already on disk and lets
# the page trigger new ones. A fetch here would make launching the app hit the
# network before the window even appears.

def test_serve_flag_starts_the_server_without_fetching(monkeypatch, tmp_path):
    cli = _load_cli()
    calls = {}

    class FakeServer:
        server_address = ("127.0.0.1", 7360)
        state = type("S", (), {"jobs": type("J", (), {"terminate": lambda self, grace=0: None})()})()

        def serve_forever(self):
            calls["served"] = True

        def server_close(self):
            calls["closed"] = True

    from tapedeck import server as server_mod
    def fake_make_server(host, port):
        calls["bound"] = (host, port)
        return FakeServer()

    monkeypatch.setattr(server_mod, "make_server", fake_make_server)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **k: calls.setdefault("opened", a[0]))

    # serve() is called directly here — it never reaches the fetch/pipeline path
    # at all, which is the point: launching the app must not hit the network.
    assert cli.serve(7360, open_browser=True) == 0
    assert calls["bound"] == ("127.0.0.1", 7360)
    assert calls["served"] is True
    assert calls["closed"] is True
    assert calls["opened"][:1] == ["open"]


def test_serve_respects_no_open(monkeypatch):
    cli = _load_cli()
    opened = []

    class FakeServer:
        server_address = ("127.0.0.1", 7360)
        state = type("S", (), {"jobs": type("J", (), {"terminate": lambda self, grace=0: None})()})()
        serve_forever = lambda self: None
        server_close = lambda self: None

    from tapedeck import server as server_mod
    monkeypatch.setattr(server_mod, "make_server", lambda host, port: FakeServer())
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: opened.append(a))

    cli.serve(7360, open_browser=False)
    assert opened == []


def test_serve_stops_cleanly_on_ctrl_c(monkeypatch):
    """Ctrl-C must not leave a job running behind the server."""
    cli = _load_cli()
    terminated = []

    class Jobs:
        def terminate(self, grace=0):
            terminated.append(grace)

    class FakeServer:
        server_address = ("127.0.0.1", 7360)
        state = type("S", (), {"jobs": Jobs()})()

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    from tapedeck import server as server_mod
    monkeypatch.setattr(server_mod, "make_server", lambda host, port: FakeServer())
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)

    assert cli.serve(7360, open_browser=False) == 0
    assert terminated, "a live job must be terminated when the server stops"


def test_serve_port_defaults_to_the_shared_constant():
    """The app, the CLI and the docs must agree on one port."""
    from tapedeck.server import DEFAULT_PORT
    assert DEFAULT_PORT == 7360

