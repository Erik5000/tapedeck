"""Tests for the single-slot job runner.

Every job here is a `python -c` one-liner — no network, no real scan.
"""

import subprocess
import sys
import threading
import time

import pytest

from tapedeck.jobs import JobBusy, JobRunner


def py(code):
    return [sys.executable, "-c", code]


def wait_done(runner, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        snap = runner.snapshot()
        if snap and snap["state"] != "running":
            return snap
        time.sleep(0.02)
    raise AssertionError(f"job never finished: {runner.snapshot()}")


def test_snapshot_is_none_before_any_job():
    assert JobRunner().snapshot() is None
    assert JobRunner().running() is False


def test_successful_job_ends_ok_with_returncode_zero():
    runner = JobRunner()
    runner.start("refresh", py("pass"))
    snap = wait_done(runner)
    assert snap["state"] == "ok"
    assert snap["returncode"] == 0
    assert snap["kind"] == "refresh"
    assert snap["ended"]


def test_failing_job_ends_failed_and_keeps_the_exit_code():
    runner = JobRunner()
    runner.start("refresh", py("import sys; sys.exit(3)"))
    snap = wait_done(runner)
    assert snap["state"] == "failed"
    assert snap["returncode"] == 3


def test_stderr_lines_are_captured_and_last_line_wins():
    runner = JobRunner()
    runner.start("refresh", py(
        "import sys; print('step one', file=sys.stderr); print('step two', file=sys.stderr)"))
    snap = wait_done(runner)
    assert snap["last_line"] == "step two"
    assert runner.lines() == ["step one", "step two"]


def test_stdout_is_discarded_so_it_cannot_masquerade_as_progress():
    runner = JobRunner()
    runner.start("refresh", py("print('this goes nowhere')"))
    snap = wait_done(runner)
    assert snap["last_line"] == ""
    assert runner.lines() == []


def test_second_start_while_running_raises_jobbusy():
    """The 409 path: two clicks must not spawn two scans."""
    runner = JobRunner()
    # Sleeps rather than reading stdin: pytest may hand the child a closed
    # stdin, which would end the job instantly and make this race.
    runner.start("refresh", py("import time; time.sleep(30)"))
    assert runner.running() is True

    with pytest.raises(JobBusy):
        runner.start("vwap", py("pass"))

    runner.terminate()
    wait_done(runner)


def test_a_new_job_may_start_once_the_previous_one_finished():
    runner = JobRunner()
    runner.start("refresh", py("pass"))
    wait_done(runner)
    runner.start("vwap", py("pass"))
    assert wait_done(runner)["kind"] == "vwap"


def test_terminate_stops_a_live_job():
    runner = JobRunner()
    runner.start("vwap", py("import time; time.sleep(30)"))
    runner.terminate(grace=2.0)
    snap = wait_done(runner)
    assert snap["state"] == "failed"
    assert snap["returncode"] != 0


def test_terminate_is_a_noop_when_nothing_is_running():
    runner = JobRunner()
    runner.terminate()  # never started
    runner.start("refresh", py("pass"))
    wait_done(runner)
    runner.terminate()  # already finished


def test_timeout_kills_a_silently_wedged_job():
    """The job prints nothing and never exits — the watchdog is the only way out."""
    runner = JobRunner()
    runner.start("vwap", py("import time; time.sleep(30)"), timeout=0.5)
    snap = wait_done(runner)
    assert snap["state"] == "timeout"
    assert "timed out" in snap["last_line"]


def test_lines_are_bounded():
    runner = JobRunner()
    runner.start("refresh", py(
        "import sys\n"
        "for i in range(500): print('line %d' % i, file=sys.stderr)"))
    snap = wait_done(runner)
    assert len(runner.lines()) == 200
    assert snap["last_line"] == "line 499"


def test_concurrent_starts_only_one_wins():
    """Hammer start() from several threads; exactly one may take the slot."""
    runner = JobRunner()
    started, busy = [], []
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        try:
            runner.start("refresh", py("import time; time.sleep(30)"))
            started.append(1)
        except JobBusy:
            busy.append(1)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(started) == 1
    assert len(busy) == 3
    runner.terminate()
    wait_done(runner)


def test_job_runs_in_the_requested_directory(tmp_path):
    runner = JobRunner()
    runner.start("refresh",
                 py("import os, sys; print(os.getcwd(), file=sys.stderr)"),
                 cwd=tmp_path)
    snap = wait_done(runner)
    assert snap["last_line"].endswith(tmp_path.name)


def test_missing_executable_raises_rather_than_silently_idling():
    """A bad command must fail loudly at start(), not leave a phantom job."""
    runner = JobRunner()
    with pytest.raises((FileNotFoundError, subprocess.SubprocessError, OSError)):
        runner.start("vwap", ["/nonexistent/python", "-c", "pass"])
    assert runner.running() is False
