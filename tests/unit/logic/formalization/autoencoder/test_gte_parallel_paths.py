"""Synthetic local workers test dispatch; no model runtime or training executes."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

import pytest


_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/gte_parallel_paths.py"
_SPEC = importlib.util.spec_from_file_location("gte_parallel_paths_under_test", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def jobs(tmp_path, code="print('worker ready')"):
    return [{"lane_id": lane, "dimension": dimension,
             "runtime_id": "test-runtime:" + lane, "representation_id": "test-representation:" + lane,
             "checkpoint_sha256": str(index + 1) * 64,
             "state_directory": str(tmp_path / lane / "state"),
             "output_directory": str(tmp_path / lane / "output"),
             "command": [sys.executable, "-c", code]}
            for index, (lane, dimension) in enumerate(subject.LANE_DIMENSIONS.items())]


def test_three_workers_reach_barrier_and_preserve_independent_identities(tmp_path):
    paths = jobs(tmp_path)
    # The read-only barrier observes each worker's own private output sentinel.
    # A sequential dispatcher cannot pass this barrier before its first timeout.
    ready = [str(Path(job["output_directory"]) / "ready") for job in paths]
    code = """import json,os,time
from pathlib import Path
Path(os.environ['GTE_PATH_OUTPUT_DIRECTORY'],'ready').write_text('ready')
deadline=time.monotonic()+5
while not all(Path(path).exists() for path in READY):
    if time.monotonic()>deadline: raise SystemExit(9)
    time.sleep(.01)
payload={name:value for name,value in os.environ.items() if name.startswith('GTE_PATH_')}
Path(os.environ['GTE_PATH_STATE_DIRECTORY'],'marker.json').write_text(json.dumps(payload))
print(json.dumps(payload))
""".replace("READY", repr(ready))
    for job in paths:
        job["command"][-1] = code
    report = subject.run_parallel_paths(paths, timeout_seconds=6)
    assert report["status"] == "success"
    for job, lane in zip(paths, report["lanes"]):
        assert lane["status"] == "succeeded"
        marker = json.loads((Path(job["state_directory"]) / "marker.json").read_text())
        assert marker["GTE_PATH_LANE"] == job["lane_id"]
        assert marker["GTE_PATH_DIMENSION"] == str(job["dimension"])
        assert marker["GTE_PATH_RUNTIME"] == job["runtime_id"]
        assert marker["GTE_PATH_REPRESENTATION"] == job["representation_id"]
        assert marker["GTE_PATH_CHECKPOINT_SHA256"] == job["checkpoint_sha256"]
        assert marker["GTE_PATH_STATE_DIRECTORY"] == job["state_directory"]
        assert marker["GTE_PATH_OUTPUT_DIRECTORY"] == job["output_directory"]
        assert lane["worker_checkpoint_verified"] is False
    assert report["proof_authority"] is False
    assert report["model_numerics_verified"] is False
    assert report["resource_admission_enforced"] is False


def test_nonzero_worker_does_not_stop_others_and_logs_are_bounded(tmp_path):
    paths = jobs(tmp_path)
    paths[0]["command"][-1] = "import sys; print('failed worker'); print('failure detail',file=sys.stderr); sys.exit(7)"
    paths[1]["command"][-1] = "print('x' * 100000)"
    report = subject.run_parallel_paths(paths)
    assert report["status"] == "partial"
    failed, noisy, other = report["lanes"]
    assert failed["status"] == "failed" and failed["exit_code"] == 7
    assert "failure detail" in failed["stderr"]
    assert noisy["status"] == other["status"] == "succeeded"
    assert noisy["stdout_truncated"] is True
    assert len(noisy["stdout"].encode()) <= subject.MAX_REPORT_LOG_BYTES


def test_missing_768_backend_is_explicit_and_creates_no_directory(tmp_path):
    paths = jobs(tmp_path)
    paths[2].update(command=None, checkpoint_sha256=None)
    report = subject.run_parallel_paths(paths)
    assert report["status"] == "partial"
    unavailable = report["lanes"][2]
    assert unavailable["status"] == "unavailable"
    assert unavailable["process_launched"] is False
    assert unavailable["checkpoint_sha256"] is None
    assert not Path(paths[2]["output_directory"]).exists()
    assert not Path(paths[2]["state_directory"]).exists()


def test_all_unavailable_does_not_report_success(tmp_path):
    paths = jobs(tmp_path)
    for job in paths:
        job.update(command=None, checkpoint_sha256=None)
    report = subject.run_parallel_paths(paths)
    assert report["status"] == "failed"
    assert all(lane["status"] == "unavailable" for lane in report["lanes"])


def test_capacity_one_runs_independent_workers_sequentially_and_resumes_private_state(tmp_path):
    paths = jobs(tmp_path)
    order = [str(Path(job["state_directory"]) / "done") for job in paths]
    for index, job in enumerate(paths):
        job["command"][-1] = (
            "from pathlib import Path; "
            + f"assert all(Path(p).exists() for p in {order[:index]!r}); "
            + f"Path({order[index]!r}).write_text('done')"
        )
        Path(job["state_directory"]).mkdir(parents=True)
        (Path(job["state_directory"]) / "existing").write_text("resume")
    assert subject.run_parallel_paths(paths, max_parallel=1)["status"] == "success"
    assert all((Path(job["state_directory"]) / "existing").read_text() == "resume" for job in paths)


def test_same_lane_state_may_be_inside_its_fresh_output(tmp_path):
    paths = jobs(tmp_path)[:1]
    paths[0]["state_directory"] = str(Path(paths[0]["output_directory"]) / "state")
    report = subject.run_parallel_paths(paths)
    assert report["status"] == "success"
    assert Path(paths[0]["state_directory"]).is_dir()


@pytest.mark.parametrize("change", ["shared_state", "nested_output", "state_output_same", "duplicate_lane", "wrong_dimension", "bad_hash", "shell_string", "extra_field"])
def test_invalid_job_declarations_stop_before_launch_or_mutation(tmp_path, change):
    paths = jobs(tmp_path)
    if change == "shared_state": paths[1]["state_directory"] = paths[0]["state_directory"]
    elif change == "nested_output": paths[1]["output_directory"] = str(Path(paths[0]["state_directory"]) / "nested")
    elif change == "state_output_same": paths[0]["output_directory"] = paths[0]["state_directory"]
    elif change == "duplicate_lane": paths[1]["lane_id"] = paths[0]["lane_id"]
    elif change == "wrong_dimension": paths[2]["dimension"] = 786
    elif change == "bad_hash": paths[0]["checkpoint_sha256"] = None
    elif change == "shell_string": paths[0]["command"] = "echo worker"
    elif change == "extra_field": paths[0]["teacher_gate"] = True
    with pytest.raises(ValueError):
        subject.run_parallel_paths(paths)
    assert list(tmp_path.iterdir()) == []


def test_existing_output_and_symlink_alias_are_rejected(tmp_path):
    paths = jobs(tmp_path)
    Path(paths[0]["output_directory"]).mkdir(parents=True)
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_parallel_paths(paths)
    paths = jobs(tmp_path / "separate")
    state = Path(paths[0]["state_directory"])
    state.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(state, target_is_directory=True)
    paths[1]["state_directory"] = str(alias)
    with pytest.raises(ValueError, match="collide"):
        subject.run_parallel_paths(paths)


@pytest.mark.parametrize("capacity", [0, 4, True, 1.5, None])
def test_max_parallel_validation(tmp_path, capacity):
    with pytest.raises(ValueError, match="max_parallel"):
        subject.run_parallel_paths(jobs(tmp_path), max_parallel=capacity)


@pytest.mark.parametrize("timeout", [0, -1, float('inf'), float('nan'), True, "1"])
def test_timeout_validation(tmp_path, timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        subject.run_parallel_paths(jobs(tmp_path), timeout_seconds=timeout)


def test_timeout_terminates_worker_before_any_delayed_write(tmp_path):
    paths = jobs(tmp_path)
    delayed = Path(paths[0]["state_directory"]) / "delayed"
    paths[0]["command"][-1] = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    report = subject.run_parallel_paths(paths, timeout_seconds=.15)
    assert report["status"] == "partial"
    assert report["lanes"][0]["status"] == "timed_out"
    assert report["lanes"][0]["exit_code"] is not None
    time.sleep(.8)
    assert not delayed.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_timeout_also_terminates_worker_descendants(tmp_path):
    paths = jobs(tmp_path)[:1]
    delayed = Path(paths[0]["state_directory"]) / "descendant-delayed"
    descendant = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    paths[0]["command"][-1] = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{descendant!r}]); time.sleep(5)"
    report = subject.run_parallel_paths(paths, timeout_seconds=.15)
    assert report["status"] == "failed"
    assert report["lanes"][0]["status"] == "timed_out"
    time.sleep(.8)
    assert not delayed.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
@pytest.mark.parametrize("exit_code", [0, 7])
def test_completed_worker_descendants_cannot_keep_writing(tmp_path, exit_code):
    paths = jobs(tmp_path)[:1]
    delayed = Path(paths[0]["state_directory"]) / "completed-descendant-delayed"
    descendant = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    paths[0]["command"][-1] = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{descendant!r}]); raise SystemExit({exit_code})"
    report = subject.run_parallel_paths(paths)
    assert report["lanes"][0]["exit_code"] == exit_code
    assert report["lanes"][0]["status"] == ("succeeded" if exit_code == 0 else "failed")
    time.sleep(.8)
    assert not delayed.exists()


def test_interrupt_immediately_after_start_keeps_worker_owned_for_cleanup(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    delayed = Path(paths[0]["state_directory"]) / "launch-interrupted-delayed"
    paths[0]["command"][-1] = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    original_start = subject._start
    def start_then_interrupt(job, register):
        original_start(job, register)
        raise KeyboardInterrupt
    monkeypatch.setattr(subject, "_start", start_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        subject.run_parallel_paths(paths)
    time.sleep(.8)
    assert not delayed.exists()


def test_sigint_inside_popen_constructor_is_replayed_after_owned_cleanup(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    delayed = Path(paths[0]["state_directory"]) / "constructor-interrupted-delayed"
    paths[0]["command"][-1] = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    original_popen = subject.subprocess.Popen
    launched = []
    def construct_then_signal(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        launched.append(process)
        os.kill(os.getpid(), signal.SIGINT)
        return process
    monkeypatch.setattr(subject.subprocess, "Popen", construct_then_signal)
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        with pytest.raises(KeyboardInterrupt):
            subject.run_parallel_paths(paths)
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        assert launched and launched[0].poll() is not None
        time.sleep(.8)
        assert not delayed.exists()
    finally:
        signal.signal(signal.SIGINT, previous)


def test_sigint_deferral_restores_and_replays_custom_handler(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    original_popen = subject.subprocess.Popen
    seen = []
    def handler(signum, frame):
        seen.append(signum)
    def construct_then_signal(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGINT)
        assert seen == []
        return process
    monkeypatch.setattr(subject.subprocess, "Popen", construct_then_signal)
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handler)
    try:
        assert subject.run_parallel_paths(paths)["status"] == "success"
        assert seen == [signal.SIGINT]
        assert signal.getsignal(signal.SIGINT) is handler
    finally:
        signal.signal(signal.SIGINT, previous)


def test_ignored_sigint_disposition_is_preserved_during_construction(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    original_popen = subject.subprocess.Popen
    def construct_then_signal(*args, **kwargs):
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        process = original_popen(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGINT)
        return process
    monkeypatch.setattr(subject.subprocess, "Popen", construct_then_signal)
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        assert subject.run_parallel_paths(paths)["status"] == "success"
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGINT, previous)


def test_custom_sigint_handler_exception_is_not_changed_into_launch_failure(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    original_popen = subject.subprocess.Popen
    launched = []
    def handler(signum, frame):
        raise ValueError("original custom handler error")
    def construct_then_signal(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        launched.append(process)
        os.kill(os.getpid(), signal.SIGINT)
        return process
    monkeypatch.setattr(subject.subprocess, "Popen", construct_then_signal)
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handler)
    try:
        with pytest.raises(ValueError, match="original custom handler error"):
            subject.run_parallel_paths(paths)
        assert launched[0].poll() is not None
        assert signal.getsignal(signal.SIGINT) is handler
    finally:
        signal.signal(signal.SIGINT, previous)


def test_runnable_dispatch_from_background_thread_rejects_before_mutation(tmp_path):
    paths = jobs(tmp_path)
    errors = []
    def dispatch():
        try:
            subject.run_parallel_paths(paths)
        except ValueError as error:
            errors.append(str(error))
    thread = threading.Thread(target=dispatch)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors and "main thread" in errors[0]
    assert list(tmp_path.iterdir()) == []


def test_interrupt_cleans_active_worker_before_reraising(tmp_path, monkeypatch):
    paths = jobs(tmp_path)[:1]
    delayed = Path(paths[0]["state_directory"]) / "interrupted-delayed"
    paths[0]["command"][-1] = f"import time; from pathlib import Path; time.sleep(.8); Path({str(delayed)!r}).write_text('leaked')"
    original_sleep = subject.time.sleep
    def interrupt(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(subject.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        subject.run_parallel_paths(paths)
    original_sleep(.8)
    assert not delayed.exists()


def test_missing_executable_is_lane_failure_and_other_lanes_continue(tmp_path):
    paths = jobs(tmp_path)
    paths[0]["command"] = [str(tmp_path / "missing-worker")]
    report = subject.run_parallel_paths(paths)
    assert report["status"] == "partial"
    assert report["lanes"][0]["reason"] == "worker_launch_failed"
    assert report["lanes"][0]["process_launched"] is False
    assert all(lane["status"] == "succeeded" for lane in report["lanes"][1:])
