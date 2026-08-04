"""Single-slot background job runner.

One job runs at a time. A second start while one is live raises JobBusy — the
server turns that into a 409, so a double-click can't spawn two scans.

Jobs are subprocesses, not in-process calls: the commands we run (tapedeck.py,
vwap-scanner) already print their progress to stderr, so streaming that gives a
live status line for free, and a crash takes the child down rather than the
server.
"""

import subprocess
import threading
from collections import deque
from datetime import datetime

MAX_LINES = 200


class JobBusy(Exception):
    """Raised by start() when a job is already running."""


class JobRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._job = None
        self._lines = deque(maxlen=MAX_LINES)

    # ---------- state ----------

    def snapshot(self):
        """JSON-safe view of the current or most recent job (None if never run)."""
        with self._lock:
            return dict(self._job) if self._job else None

    def lines(self):
        with self._lock:
            return list(self._lines)

    def running(self):
        with self._lock:
            return bool(self._job and self._job["state"] == "running")

    # ---------- control ----------

    def start(self, kind, argv, cwd=None, timeout=600):
        """Spawn argv as the one live job. Raises JobBusy if one is already running."""
        with self._lock:
            if self._job and self._job["state"] == "running":
                raise JobBusy(f"{self._job['kind']} is already running")
            # Popen first: if the command is bad it raises here, and the slot
            # must stay free rather than holding a job that never runs.
            proc = subprocess.Popen(
                [str(a) for a in argv], cwd=str(cwd) if cwd else None,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, bufsize=1)
            self._lines.clear()
            self._job = {"kind": kind, "state": "running", "returncode": None,
                         "started": datetime.now().isoformat(timespec="seconds"),
                         "ended": None, "last_line": ""}
            self._proc = proc
        threading.Thread(target=self._pump, args=(proc, timeout), daemon=True).start()
        return self.snapshot()

    def _pump(self, proc, timeout):
        """Drain the child's stderr into last_line, then settle the final state."""
        # A timer, not a deadline checked per line: a job that wedges silently
        # produces no lines at all, which is exactly when the timeout matters.
        expired = threading.Event()

        def _expire():
            expired.set()
            _kill(proc, grace=2.0)

        watchdog = threading.Timer(timeout, _expire) if timeout else None
        if watchdog:
            watchdog.daemon = True
            watchdog.start()
        try:
            for raw in proc.stderr:
                line = raw.rstrip()
                if not line:
                    continue
                with self._lock:
                    self._lines.append(line)
                    if self._job:
                        self._job["last_line"] = line
            proc.wait()
        finally:
            if watchdog:
                watchdog.cancel()
        timed_out = expired.is_set()
        with self._lock:
            if not self._job:
                return
            self._job["returncode"] = proc.returncode
            self._job["ended"] = datetime.now().isoformat(timespec="seconds")
            if timed_out:
                self._job["state"] = "timeout"
                self._job["last_line"] = f"timed out after {timeout}s"
            else:
                self._job["state"] = "ok" if proc.returncode == 0 else "failed"

    def terminate(self, grace=5.0):
        """SIGTERM the live job, SIGKILL if it outlasts the grace period."""
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        _kill(proc, grace)


def _kill(proc, grace=5.0):
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
