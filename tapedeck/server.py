"""Local HTTP server for TAPEDECK.app.

Serves the most recent dashboard with a small app shell injected into it, and
exposes two buttons' worth of API: refresh the dashboard, rescan VWAP levels.
Both run as background jobs, one at a time.

Bound to 127.0.0.1 only. It is still worth guarding: both POSTs run local
commands, and this port sits open for as long as the app does.

Run standalone with `python -m tapedeck.server`, or let the native app spawn it.
"""

import json
import os
import re
import select
import sys
import threading
import time
from datetime import date
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import vwaplink
from .jobs import JobBusy, JobRunner

ROOT = Path(__file__).resolve().parent.parent
SERVICE = "tapedeck"
DEFAULT_PORT = 7360

REFRESH_TIMEOUT = 600      # a normal run is ~20s
VWAP_TIMEOUT = 1800        # a cold Twelve Data scan is ~8 min

_ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}
_DASH_RE = re.compile(r"^tapedeck-(\d{4}-\d{2}-\d{2})\.html$")
_SHELL_TAG = '<script src="/_app/shell.js" defer></script>'

NO_DASHBOARD_HTML = """<!doctype html><meta charset="utf-8">
<title>TAPEDECK</title>
<style>body{font:14px -apple-system,sans-serif;margin:8rem auto;max-width:32rem;
color:#3b3a36;text-align:center}code{background:#eee;padding:.15rem .4rem}</style>
<h1>TAPEDECK</h1>
<p>No dashboard has been generated yet.</p>
<p>Run <code>tapedeck.py</code> once, or press Refresh in the app.</p>
"""


# ---------- dashboard discovery ----------

def latest_dashboard(out_dir):
    """Newest output/tapedeck-DATE.html, by the date in the filename."""
    best = None
    for path in Path(out_dir).glob("tapedeck-*.html"):
        m = _DASH_RE.match(path.name)
        if m and (best is None or m.group(1) > best[0]):
            best = (m.group(1), path)
    return best


def inject_shell(html):
    """Add the app shell to a rendered dashboard, without touching anything else."""
    if _SHELL_TAG in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", f"{_SHELL_TAG}\n</body>", 1)
    return html + _SHELL_TAG


def _hostname(value):
    """'http://localhost:7360/x' | 'localhost:7360' | 'localhost' -> 'localhost'"""
    v = value.split("://", 1)[-1].split("/", 1)[0]
    if v.startswith("["):                      # bracketed IPv6 literal
        return v.split("]", 1)[0] + "]"
    return v.rsplit(":", 1)[0] if ":" in v else v


def _is_loopback(addr):
    host = (addr or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


# ---------- state shared with the handler ----------

class AppState:
    def __init__(self, root=ROOT, vwap_scanner=None, owner_pid=None):
        self.root = Path(root)
        self.out_dir = self.root / "output"
        self.jobs = JobRunner()
        self.owner_pid = owner_pid
        self._feed_cache = None
        self.vwap_scanner = Path(vwap_scanner) if vwap_scanner else self.root.parent / "vwap-scanner"

    # --- the two commands ---

    def scanner_python(self):
        """The vwap-scanner venv interpreter, or None if that repo isn't usable."""
        for rel in ("venv/bin/python3", ".venv/bin/python3"):
            candidate = self.vwap_scanner / rel
            if candidate.exists():
                return candidate
        return None

    def vwap_available(self):
        return bool(self.scanner_python() and (self.vwap_scanner / "scanner.py").exists())

    def refresh_argv(self):
        return [sys.executable, self.root / "tapedeck.py", "--no-open"]

    def vwap_argv(self):
        return [self.scanner_python(), "scanner.py",
                "--universe-from", self.out_dir / "tapedeck-latest.json",
                "--json-out", self.out_dir / "vwap-latest.json"]

    # --- what the UI polls ---

    def vwap_feed(self):
        """The VWAP feed, cached on mtime — /api/status polls once a second."""
        path = self.out_dir / "vwap-latest.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._feed_cache = None       # absent is normal; load_vwap would warn
            return None
        if not self._feed_cache or self._feed_cache[0] != mtime:
            self._feed_cache = (mtime, vwaplink.load_vwap(path))
        return self._feed_cache[1]

    def status(self):
        found = latest_dashboard(self.out_dir)
        dashboard = None
        if found:
            stamp, path = found
            dashboard = {"date": stamp, "data_date": _feed_data_date(self.out_dir),
                         "file": path.name}
        return {"dashboard": dashboard,
                "vwap": vwaplink.vwap_freshness(self.vwap_feed(), date.today()),
                "vwap_available": self.vwap_available(),
                "job": self.jobs.snapshot()}


def _feed_data_date(out_dir):
    """The data_date tapedeck last recorded, read from its own JSON feed."""
    try:
        return json.loads((Path(out_dir) / "tapedeck-latest.json").read_text()).get("data_date")
    except (OSError, ValueError):
        return None


# ---------- request handling ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "tapedeck"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, state=None, **kwargs):
        self.state = state
        super().__init__(*args, **kwargs)

    # --- plumbing ---

    def log_message(self, fmt, *args):
        pass  # the access log is noise in the app's stderr

    def _guard(self):
        """Loopback by peer address, and Host pinned. Neither check covers both attacks."""
        if not _is_loopback(self.client_address[0] if self.client_address else ""):
            self._send(403, "text/plain", b"forbidden: non-local client")
            return False
        if _hostname(self.headers.get("Host", "")) not in _ALLOWED_HOSTNAMES:
            self._send(403, "text/plain", b"forbidden host")
            return False
        return True

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj, default=str).encode())

    # --- routes ---

    def do_GET(self):
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._serve_dashboard()
        if path == "/_app/shell.js":
            return self._send(200, "application/javascript",
                              (Path(__file__).with_name("appshell.js")).read_bytes())
        if path == "/api/health":
            return self._json({"ok": True, "service": SERVICE, "pid": os.getpid(),
                               "repo_root": str(self.state.root),
                               "owner_pid": self.state.owner_pid})
        if path == "/api/status":
            return self._json(self.state.status())
        self._json({"error": "not found", "path": path}, code=404)

    def do_POST(self):
        # Drain first: on a keep-alive connection an unread body would be parsed
        # as the start of the next request.
        try:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        except (ValueError, OSError):
            pass
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/refresh":
            return self._start("refresh", self.state.refresh_argv(),
                               self.state.root, REFRESH_TIMEOUT)
        if path == "/api/vwap":
            if not self.state.vwap_available():
                return self._json({"error": "vwap-scanner not available",
                                   "looked_in": str(self.state.vwap_scanner)}, code=503)
            return self._start("vwap", self.state.vwap_argv(),
                               self.state.vwap_scanner, VWAP_TIMEOUT)
        self._json({"error": "not found", "path": path}, code=404)

    def _start(self, kind, argv, cwd, timeout):
        try:
            job = self.state.jobs.start(kind, argv, cwd=cwd, timeout=timeout)
        except JobBusy as exc:
            return self._json({"error": str(exc), "job": self.state.jobs.snapshot()}, code=409)
        except OSError as exc:
            return self._json({"error": f"could not start {kind}: {exc}"}, code=500)
        return self._json({"job": job}, code=202)

    def _serve_dashboard(self):
        found = latest_dashboard(self.state.out_dir)
        if not found:
            return self._send(503, "text/html; charset=utf-8",
                              inject_shell(NO_DASHBOARD_HTML).encode())
        html = found[1].read_text()
        self._send(200, "text/html; charset=utf-8", inject_shell(html).encode())


# ---------- lifecycle ----------

def make_server(host="127.0.0.1", port=DEFAULT_PORT, state=None):
    state = state or AppState()
    httpd = ThreadingHTTPServer((host, port), partial(Handler, state=state))
    httpd.daemon_threads = True
    httpd.state = state
    return httpd


def watch_parent(parent_pid, on_death):
    """Call on_death() as soon as parent_pid exits.

    kqueue EVFILT_PROC/NOTE_EXIT fires on SIGKILL, force-quit and crashes alike —
    the cases where the app's own terminate handler never runs. Darwin has no
    prctl(PR_SET_PDEATHSIG). The timeout plus the kill(pid, 0) recheck covers the
    race where the parent dies before we finish registering.
    """
    try:
        kq = select.kqueue()
        kq.control([select.kevent(parent_pid, filter=select.KQ_FILTER_PROC,
                                  flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                  fflags=select.KQ_NOTE_EXIT)], 0, 0)
        while True:
            if kq.control([], 1, 2.0):
                return on_death()
            if not _alive(parent_pid):
                return on_death()
    except Exception:
        while True:                       # kqueue unavailable, or already gone
            if not _alive(parent_pid):
                return on_death()
            time.sleep(1.0)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="TAPEDECK local server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--parent-pid", type=int, default=0, help="exit when this pid does")
    ap.add_argument("--grace", type=float, default=5.0)
    ap.add_argument("--vwap-scanner", default=None, help="path to the vwap-scanner repo")
    args = ap.parse_args(argv)

    state = AppState(vwap_scanner=args.vwap_scanner, owner_pid=args.parent_pid or None)
    httpd = make_server(args.host, args.port, state)
    print(f"[tapedeck] serving http://{args.host}:{args.port}/  repo={state.root} "
          f"parent={args.parent_pid or '-'}", flush=True)

    if args.parent_pid:
        def _die():
            print("[tapedeck] parent exited — shutting down", flush=True)
            state.jobs.terminate(grace=2.0)
            threading.Thread(target=httpd.shutdown, daemon=True).start()
            time.sleep(args.grace)
            os._exit(0)  # hard stop if the graceful path wedges

        threading.Thread(target=watch_parent, args=(args.parent_pid, _die),
                         daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.jobs.terminate(grace=2.0)
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
