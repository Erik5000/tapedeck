"""Tests for the local server.

These bind a real socket on port 0 and speak HTTP over it, so the routing,
the guards and the status codes are exercised end to end.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tapedeck import server as srv


# ---------- harness ----------

@pytest.fixture
def repo(tmp_path):
    """A fake repo: output/ plus a stub tapedeck.py that just prints and exits."""
    (tmp_path / "output").mkdir()
    (tmp_path / "tapedeck.py").write_text(
        "import sys; print('stub ran', file=sys.stderr)\n")
    return tmp_path


@pytest.fixture
def state(repo):
    return srv.AppState(root=repo, vwap_scanner=repo / "no-such-scanner")


@pytest.fixture
def base(state):
    httpd = srv.make_server("127.0.0.1", 0, state)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def post(base, path, headers=None):
    req = urllib.request.Request(base + path, data=b"", method="POST",
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def write_dashboard(repo, stamp, body="<html><body>rows</body></html>"):
    (repo / "output" / f"tapedeck-{stamp}.html").write_text(body)


# ---------- dashboard discovery ----------

def test_latest_dashboard_picks_the_newest_date(repo):
    write_dashboard(repo, "2026-08-01")
    write_dashboard(repo, "2026-08-04")
    write_dashboard(repo, "2026-07-31")
    assert srv.latest_dashboard(repo / "output")[0] == "2026-08-04"


def test_latest_dashboard_ignores_unrelated_files(repo):
    (repo / "output" / "tapedeck-latest.json").write_text("{}")
    (repo / "output" / "tapedeck-notadate.html").write_text("x")
    assert srv.latest_dashboard(repo / "output") is None


def test_latest_dashboard_is_none_when_output_is_empty(repo):
    assert srv.latest_dashboard(repo / "output") is None


# ---------- injection ----------

def test_inject_shell_adds_the_tag_before_body_close():
    out = srv.inject_shell("<html><body>rows</body></html>")
    assert srv._SHELL_TAG in out
    assert out.index(srv._SHELL_TAG) < out.index("</body>")


def test_inject_shell_is_idempotent():
    once = srv.inject_shell("<html><body>x</body></html>")
    assert srv.inject_shell(once).count(srv._SHELL_TAG) == 1


def test_inject_shell_appends_when_there_is_no_body_tag():
    assert srv.inject_shell("bare").endswith(srv._SHELL_TAG)


def test_inject_shell_leaves_the_rest_of_the_page_alone():
    page = "<html><head><style>a{}</style></head><body><table>x</table></body></html>"
    assert srv.inject_shell(page).replace(srv._SHELL_TAG + "\n", "") == page


# ---------- routes ----------

def test_root_serves_the_newest_dashboard_with_the_shell_injected(base, repo):
    write_dashboard(repo, "2026-08-04", "<html><body>NEWEST</body></html>")
    write_dashboard(repo, "2026-08-01", "<html><body>OLDER</body></html>")
    status, body, headers = get(base, "/")
    assert status == 200
    assert "NEWEST" in body and "OLDER" not in body
    assert srv._SHELL_TAG in body
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_root_explains_itself_when_no_dashboard_exists_yet(base):
    status, body, _ = get(base, "/")
    assert status == 503
    assert "No dashboard" in body
    assert srv._SHELL_TAG in body       # so Refresh still works from that page


def test_shell_js_is_served(base):
    status, body, headers = get(base, "/_app/shell.js")
    assert status == 200
    assert headers["Content-Type"] == "application/javascript"
    assert "TAPEDECK" in body


def test_health_reports_identity_for_the_native_app(base, repo):
    status, body, _ = get(base, "/api/health")
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["service"] == "tapedeck"
    assert payload["repo_root"] == str(repo)
    assert payload["owner_pid"] is None


def test_health_carries_the_owner_pid_when_the_app_spawned_us(repo):
    state = srv.AppState(root=repo, owner_pid=4242)
    httpd = srv.make_server("127.0.0.1", 0, state)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        _, body, _ = get(f"http://127.0.0.1:{httpd.server_address[1]}", "/api/health")
        assert json.loads(body)["owner_pid"] == 4242
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_status_reports_the_dashboard_and_no_job_before_anything_runs(base, repo):
    write_dashboard(repo, "2026-08-04")
    (repo / "output" / "tapedeck-latest.json").write_text(
        json.dumps({"data_date": "2026-08-03"}))
    status, body, _ = get(base, "/api/status")
    assert status == 200
    payload = json.loads(body)
    assert payload["dashboard"]["date"] == "2026-08-04"
    assert payload["dashboard"]["data_date"] == "2026-08-03"
    assert payload["job"] is None
    assert payload["vwap"] is None
    assert payload["vwap_available"] is False


def test_status_survives_a_corrupt_feed_file(base, repo):
    write_dashboard(repo, "2026-08-04")
    (repo / "output" / "tapedeck-latest.json").write_text("{not json")
    status, body, _ = get(base, "/api/status")
    assert status == 200
    assert json.loads(body)["dashboard"]["data_date"] is None


def test_status_ages_a_real_vwap_feed(base, repo):
    (repo / "output" / "vwap-latest.json").write_text(json.dumps(
        {"schema": 1, "generated": "2026-08-01T18:00:00+02:00",
         "threshold_pct": 5.0, "tickers": {}}))
    _, body, _ = get(base, "/api/status")
    vwap = json.loads(body)["vwap"]
    assert vwap["generated"] == "2026-08-01"
    assert vwap["age_days"] >= 0


def test_unknown_routes_are_404_json(base):
    status, body, _ = get(base, "/nope")
    assert status == 404
    assert json.loads(body)["error"] == "not found"
    assert post(base, "/api/nope")[0] == 404


# ---------- guards ----------

def test_a_forged_host_header_is_refused(base):
    status, body, _ = get(base, "/api/health", headers={"Host": "evil.example.com"})
    assert status == 403
    assert "forbidden host" in body


def test_a_forged_host_header_is_refused_on_post_too(base):
    """The POSTs run local commands — the guard has to cover them, not just GET."""
    status, _ = post(base, "/api/refresh", headers={"Host": "evil.example.com"})
    assert status == 403


def test_localhost_and_the_loopback_ip_are_both_accepted(base):
    port = base.rsplit(":", 1)[1]
    for host in (f"localhost:{port}", f"127.0.0.1:{port}"):
        assert get(base, "/api/health", headers={"Host": host})[0] == 200


def test_hostname_parsing_handles_the_shapes_a_browser_sends():
    assert srv._hostname("http://localhost:7360/x") == "localhost"
    assert srv._hostname("127.0.0.1:7360") == "127.0.0.1"
    assert srv._hostname("localhost") == "localhost"
    assert srv._hostname("evil.example.com:80") == "evil.example.com"


def test_loopback_detection():
    assert srv._is_loopback("127.0.0.1")
    assert srv._is_loopback("127.1.2.3")
    assert srv._is_loopback("::1")
    assert not srv._is_loopback("192.168.1.20")
    assert not srv._is_loopback("")


# ---------- jobs ----------

def test_refresh_starts_a_job_and_reports_it(base, state):
    status, body = post(base, "/api/refresh")
    assert status == 202
    assert json.loads(body)["job"]["kind"] == "refresh"
    _wait_idle(state)
    assert state.jobs.snapshot()["state"] == "ok"
    assert state.jobs.snapshot()["last_line"] == "stub ran"


def test_a_second_refresh_while_one_runs_is_a_409(repo):
    """Two clicks must not spawn two runs."""
    state = srv.AppState(root=repo)
    state.refresh_argv = lambda: [sys.executable, "-c", "import time; time.sleep(30)"]
    httpd = srv.make_server("127.0.0.1", 0, state)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert post(base, "/api/refresh")[0] == 202
        status, body = post(base, "/api/refresh")
        assert status == 409
        assert "already running" in json.loads(body)["error"]
    finally:
        state.jobs.terminate(grace=2.0)
        httpd.shutdown()
        httpd.server_close()


def test_vwap_is_503_when_the_scanner_repo_is_missing(base, state):
    status, body = post(base, "/api/vwap")
    assert status == 503
    assert "vwap-scanner" in json.loads(body)["error"]
    assert state.jobs.snapshot() is None      # nothing was started


def test_vwap_command_targets_the_shared_feed_paths(repo, tmp_path):
    """The scan must write where the watchlists' `vwap:` key points."""
    scanner = tmp_path / "vwap-scanner"
    (scanner / "venv" / "bin").mkdir(parents=True)
    (scanner / "venv" / "bin" / "python3").write_text("#!/bin/sh\n")
    (scanner / "scanner.py").write_text("")
    state = srv.AppState(root=repo, vwap_scanner=scanner)

    assert state.vwap_available() is True
    argv = [str(a) for a in state.vwap_argv()]
    assert argv[1] == "scanner.py"
    assert argv[argv.index("--universe-from") + 1].endswith("output/tapedeck-latest.json")
    assert argv[argv.index("--json-out") + 1].endswith("output/vwap-latest.json")


def test_vwap_available_is_false_without_the_scanner_venv(repo, tmp_path):
    scanner = tmp_path / "vwap-scanner"
    scanner.mkdir()
    (scanner / "scanner.py").write_text("")
    assert srv.AppState(root=repo, vwap_scanner=scanner).vwap_available() is False


def test_refresh_runs_the_repos_own_cli(repo):
    state = srv.AppState(root=repo)
    argv = [str(a) for a in state.refresh_argv()]
    assert argv[0] == sys.executable
    assert argv[1].endswith("tapedeck.py")
    assert "--no-open" in argv


def _wait_idle(state, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        snap = state.jobs.snapshot()
        if snap and snap["state"] != "running":
            return
        time.sleep(0.02)
    raise AssertionError("job never finished")


# ---------- parent-death watchdog ----------
#
# This is what makes "quitting the app stops the server" hold when the app is
# force-quit or crashes, i.e. when its own terminate handler never runs.

def _spawn_short_lived():
    import subprocess
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.4)"])


def _watch_until_death(pid, timeout=10, reap=None):
    """Watch `pid`, reaping it meanwhile if it happens to be our own child.

    An unreaped child lingers as a zombie, and os.kill(zombie, 0) still
    succeeds — so the polling fallback would never see it go. Doesn't arise in
    production: the watched parent is the app, which launchd reaps, not us.
    """
    fired = threading.Event()
    threading.Thread(target=srv.watch_parent, args=(pid, fired.set), daemon=True).start()
    if reap is not None:
        reap.wait()
    return fired.wait(timeout=timeout)


def test_watch_parent_fires_when_the_parent_exits():
    child = _spawn_short_lived()
    assert _watch_until_death(child.pid, reap=child) is True


def test_watch_parent_fires_immediately_for_an_already_dead_pid():
    """The registration race: the parent may already be gone when we start."""
    child = _spawn_short_lived()
    child.kill()
    child.wait()
    assert _watch_until_death(child.pid, timeout=5) is True


def test_watch_parent_falls_back_to_polling_without_kqueue(monkeypatch):
    def no_kqueue():
        raise OSError("kqueue unavailable")
    monkeypatch.setattr(srv.select, "kqueue", no_kqueue)

    child = _spawn_short_lived()
    assert _watch_until_death(child.pid, reap=child) is True


def test_watch_parent_does_not_fire_while_the_parent_lives():
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        fired = threading.Event()
        threading.Thread(target=srv.watch_parent, args=(child.pid, fired.set),
                         daemon=True).start()
        assert fired.wait(timeout=1.5) is False
    finally:
        child.kill()
        child.wait()


def test_alive_tracks_a_real_process():
    child = _spawn_short_lived()
    assert srv._alive(child.pid) is True
    child.kill()
    child.wait()
    assert srv._alive(child.pid) is False


# ---------- the injected shell ----------

def test_shell_js_parses():
    """Caught by eye otherwise — the shell is never imported by Python."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    shell = Path(srv.__file__).with_name("appshell.js")
    subprocess.run([node, "--check", str(shell)], check=True, capture_output=True)


def test_shell_js_drives_the_endpoints_this_server_exposes():
    """If a route is renamed, the buttons go dead silently — pin them together."""
    shell = Path(srv.__file__).with_name("appshell.js").read_text()
    for route in ("/api/refresh", "/api/vwap", "/api/status"):
        assert route in shell, f"{route} missing from the app shell"
    assert ".controls" in shell        # where the buttons are inserted
    assert "tbtn" in shell             # the page's own button class


# ---------- watchlist editor routes ----------

def req(base, method, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(base + path, data=data, method=method,
                              headers=headers or {})
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except ValueError:
            return e.code, {"raw": raw}


@pytest.fixture
def wl_repo(repo):
    d = repo / "watchlists"
    d.mkdir()
    (d / "book.yaml").write_text("title: My Book\nholdings:\n  - {ticker: NVDA}\n")
    return repo


@pytest.fixture
def wl_base(wl_repo):
    state = srv.AppState(root=wl_repo, vwap_scanner=wl_repo / "no-such-scanner")
    httpd = srv.make_server("127.0.0.1", 0, state)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.tstate = state
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state
    httpd.shutdown()
    httpd.server_close()


def test_list_watchlists(wl_base):
    base, _ = wl_base
    code, data = req(base, "GET", "/api/watchlists")
    assert code == 200
    assert [l["name"] for l in data["lists"]] == ["book"]
    assert data["lists"][0]["title"] == "My Book"


def test_read_one_watchlist(wl_base):
    base, _ = wl_base
    code, data = req(base, "GET", "/api/watchlists/book")
    assert code == 200
    assert data["name"] == "book"
    assert data["holdings"][0]["ticker"] == "NVDA"


def test_read_missing_watchlist_is_400(wl_base):
    base, _ = wl_base
    code, data = req(base, "GET", "/api/watchlists/ghost")
    assert code == 400
    assert "no watchlist" in data["error"]


def test_create_then_save_then_delete(wl_base):
    base, state = wl_base
    code, data = req(base, "POST", "/api/watchlists", {"name": "my semis"})
    assert code == 201
    assert data["name"] == "my-semis"

    model = dict(data, title="Renamed",
                 holdings=[{"ticker": "AMD", "group": "semis"},
                           {"ticker": "MU"}])
    code, saved = req(base, "PUT", "/api/watchlists/my-semis", model)
    assert code == 200
    assert saved["title"] == "Renamed"
    assert [h["ticker"] for h in saved["holdings"]] == ["AMD", "MU"]
    assert (state.wl_dir / "my-semis.yaml").exists()

    code, _ = req(base, "DELETE", "/api/watchlists/my-semis")
    assert code == 200
    assert not (state.wl_dir / "my-semis.yaml").exists()
    assert list((state.backup_dir).glob("my-semis-*.yaml"))


def test_create_duplicate_is_409(wl_base):
    base, _ = wl_base
    assert req(base, "POST", "/api/watchlists", {"name": "book"})[0] == 409


def test_create_bad_name_is_400(wl_base):
    base, _ = wl_base
    assert req(base, "POST", "/api/watchlists", {"name": "../evil"})[0] == 400


def test_save_that_would_not_load_is_400_and_leaves_the_file_alone(wl_base):
    base, state = wl_base
    before = (state.wl_dir / "book.yaml").read_text()
    code, data = req(base, "PUT", "/api/watchlists/book",
                     {"holdings": [{"ticker": "NVDA"}, {"ticker": "nvda"}]})
    assert code == 400
    assert "would not load" in data["error"]
    assert (state.wl_dir / "book.yaml").read_text() == before


def test_traversal_through_the_http_layer(wl_base, tmp_path):
    """The URL path is the one place a name arrives already percent-decoded."""
    base, _ = wl_base
    for path in ("/api/watchlists/..%2Fevil", "/api/watchlists/%2Fetc%2Fpasswd",
                 "/api/watchlists/..", "/api/watchlists/Book"):
        code, _ = req(base, "PUT", path, {"holdings": [{"ticker": "X"}]})
        assert code == 400, path


def test_writes_are_refused_while_a_job_runs(wl_base):
    """A refresh subprocess is reading these files; a half-written watchlist
    during a fetch is a bad failure mode."""
    base, state = wl_base
    state.jobs.start("refresh", [sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert req(base, "POST", "/api/watchlists", {"name": "later"})[0] == 409
        assert req(base, "PUT", "/api/watchlists/book",
                   {"holdings": [{"ticker": "AMD"}]})[0] == 409
        assert req(base, "DELETE", "/api/watchlists/book")[0] == 409
        # Reads stay available — the editor should still open mid-run.
        assert req(base, "GET", "/api/watchlists")[0] == 200
        assert req(base, "GET", "/api/watchlists/book")[0] == 200
    finally:
        state.jobs.terminate(grace=1.0)


def test_editor_routes_reject_a_forged_host(wl_base):
    base, _ = wl_base
    code, _ = req(base, "GET", "/api/watchlists", headers={"Host": "evil.example.com"})
    assert code == 403
    code, _ = req(base, "PUT", "/api/watchlists/book",
                  {"holdings": [{"ticker": "X"}]}, headers={"Host": "evil.example.com"})
    assert code == 403


def test_markets_route_is_cached_and_degrades(wl_base, monkeypatch):
    base, state = wl_base
    calls = []
    monkeypatch.setattr(srv.hlfetch, "list_markets",
                        lambda dex="xyz": calls.append(dex) or ["NVDA", "GOLD"])
    code, data = req(base, "GET", "/api/markets")
    assert code == 200
    assert data["markets"] == ["NVDA", "GOLD"]
    req(base, "GET", "/api/markets")
    assert len(calls) == 1          # second call served from cache

    def boom(dex="xyz"):
        raise OSError("offline")
    monkeypatch.setattr(srv.hlfetch, "list_markets", boom)
    state._markets.clear()
    code, data = req(base, "GET", "/api/markets")
    assert code == 200 and data["markets"] == []   # a picker still accepts typing


def test_unknown_put_and_delete_are_404(wl_base):
    base, _ = wl_base
    assert req(base, "PUT", "/api/nope", {})[0] == 404
    assert req(base, "DELETE", "/api/nope")[0] == 404
