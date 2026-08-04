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
