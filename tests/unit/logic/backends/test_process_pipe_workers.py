"""Authored native-pipe regressions for an isolated, source-pinned candidate.

Import origins are admitted by the external candidate harness. These tests run
only short authored Python children; they never invoke a solver, model, database
or network client. Controlled pipe stalls are always released in fixture cleanup.
"""
from __future__ import annotations

import array
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import termios
import threading

import pytest

from ipfs_datasets_py.logic.backends import process as module


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux native pipe/FD qualification"
)

_REAL_THREAD = threading.Thread
_REAL_POPEN = subprocess.Popen
_WATCHDOG_SECONDS = 6.0
_SHORT_CHILD = (
    "import sys; "
    "sys.stdout.buffer.write(b'authored stdout\\n'); sys.stdout.flush(); "
    "sys.stderr.buffer.write(b'authored stderr\\n'); sys.stderr.flush()"
)
_NONREADING_CHILD = (
    "import sys,time; "
    "sys.stdout.write('authored child ready\\n'); sys.stdout.flush(); time.sleep(30)"
)
_READING_CHILD = (
    "import sys; data=sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(b'authored stdout\\n'); sys.stdout.flush(); "
    "sys.stderr.buffer.write(b'authored stderr\\n'); sys.stderr.flush()"
)
_CLOSED_STDIN_CHILD = (
    "import sys; sys.stdin.close(); "
    "sys.stdout.write('authored child closed stdin\\n'); sys.stdout.flush()"
)


def _fd_targets():
    """Compare identities/targets, not only reusable FD numbers."""
    result = {}
    for name in os.listdir("/proc/self/fd"):
        try:
            result[int(name)] = os.readlink("/proc/self/fd/" + name)
        except FileNotFoundError:
            pass  # The enumeration's own FD has already closed.
    return result


class _Pipe:
    """Transparent real-pipe wrapper with independently releasable faults."""

    def __init__(self, stream, case, role, mode):
        self.stream = stream
        self.case = case
        self.role = role
        self.mode = mode
        self.lock = threading.RLock()
        self.reads = 0

    @property
    def closed(self):
        return self.stream.closed

    def fileno(self):
        return self.stream.fileno()

    def fail(self, operation):
        error = self.case.fault_exception
        if error is None:
            error = OSError(f"authored {self.role} {operation} failure")
        self.case.raised_faults.append(error)
        self.case.fault_observed.set()
        raise error

    def read(self, size=-1):
        with self.lock:
            self.reads += 1
            if self.mode == "read_error" and self.reads == 2:
                self.fail("read")
            data = self.stream.read(size)
            if self.mode == "live_reader" and self.reads == 1:
                # The native child has exited and real output was read. Hold
                # only this test-owned worker, including its buffered lock.
                self.case.fault_observed.set()
                self.case.release.wait()
            return data

    def write(self, data):
        with self.lock:
            self.case.write_entered.set()
            if self.mode == "live_writer":
                self.case.fault_observed.set()
                self.case.release.wait()
            if self.mode == "write_error":
                self.fail("write")
            try:
                return self.stream.write(data)
            except BrokenPipeError as error:
                self.case.broken_pipes.append(error)
                raise
            finally:
                self.case.write_returned.set()

    def flush(self):
        with self.lock:
            if self.mode == "flush_error":
                self.fail("flush")
            try:
                return self.stream.flush()
            except BrokenPipeError as error:
                self.case.broken_pipes.append(error)
                raise

    def close(self):
        with self.lock:
            was_closed = self.stream.closed
            try:
                result = self.stream.close()
            except BrokenPipeError as error:
                self.case.broken_pipes.append(error)
                raise
            if self.mode == "close_error" and not was_closed:
                # A close operation may report an error after releasing its
                # descriptor. Prove the real FD is closed before faulting.
                assert self.stream.closed
                self.fail("close")
            return result


class _NativeCase:
    def __init__(self, directory, monkeypatch, *, mode="ordinary", role="stdout",
                 fault_exception=None):
        self.directory = directory
        self.mode = mode
        self.role = role
        self.fault_exception = fault_exception
        self.release = threading.Event()
        self.fault_observed = threading.Event()
        self.write_entered = threading.Event()
        self.write_returned = threading.Event()
        self.processes = []
        self.actual_streams = []
        self.workers = []
        self.worker_failures = []
        self.raised_faults = []
        self.broken_pipes = []
        self.host = None
        self.result = None
        self.exception = None
        self.pipe_capacity = None
        self.pipe_was_full = False
        self.start_failure_observed = False

        case = self

        class TrackedThread(_REAL_THREAD):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                case.workers.append(self)

            def start(self):
                if case.mode == "writer_start_failure" and len(case.workers) == 3:
                    # Two readers have started; stdin is the third worker.
                    case.start_failure_observed = True
                    raise RuntimeError("authored writer start failure")
                return super().start()

        monkeypatch.setattr(module.threading, "Thread", TrackedThread)
        monkeypatch.setattr(
            threading, "excepthook", lambda args: case.worker_failures.append(args)
        )

    def spawn(self, argv, **kwargs):
        process = _REAL_POPEN(argv, **kwargs)
        self.processes.append(process)
        for role in ("stdout", "stderr", "stdin"):
            stream = getattr(process, role)
            if stream is None:
                continue
            self.actual_streams.append(stream)
            if role == "stdin":
                if self.mode == "blocked_stdin":
                    # Shrink only this authored pipe. The admitted payload
                    # exceeds measured capacity, forcing a native blocked write.
                    fcntl.fcntl(stream.fileno(), fcntl.F_SETPIPE_SZ, 4096)
                self.pipe_capacity = fcntl.fcntl(stream.fileno(), fcntl.F_GETPIPE_SZ)
            fault = self.mode if role == self.role else "ordinary"
            setattr(process, role, _Pipe(stream, self, role, fault))
        return process

    def full_stdin_pipe(self):
        if not self.processes or self.processes[0].stdin is None:
            return False
        stream = self.processes[0].stdin
        if stream.closed or not self.write_entered.is_set():
            return False
        pending = array.array("i", [0])
        fcntl.ioctl(stream.fileno(), termios.FIONREAD, pending, True)
        full = pending[0] >= self.pipe_capacity
        self.pipe_was_full = self.pipe_was_full or full
        return full and not self.write_returned.is_set()

    def run(self, *, stdin=None, source=_SHORT_CHILD, cancellation=None, timeout=2.0):
        limits = module.ToolRunLimits(
            timeout_seconds=timeout,
            termination_grace_seconds=0.08,
            max_input_bytes=262144,
            max_output_bytes=4096,
            max_workspace_bytes=262144,
            cpu_seconds=2,
            memory_bytes=256 * 1024**2,
        )
        executor = module.SubprocessExecutor(popen=self.spawn)
        runner = module.BoundedToolRunner(
            executor=executor, workspace_root=self.directory / "workspaces"
        )

        def invoke():
            try:
                self.result = runner.run(
                    module.ToolRunRequest(
                        argv=(sys.executable, "-c", source), stdin=stdin, limits=limits
                    ),
                    cancellation=cancellation,
                )
            except BaseException as error:
                self.exception = error

        # Keep a separately retained test watchdog. It is never substituted for
        # an owner worker and is released/joined before fixture completion.
        self.host = _REAL_THREAD(target=invoke, daemon=True)
        self.host.start()
        self.host.join(_WATCHDOG_SECONDS)
        assert not self.host.is_alive(), "owner did not return within test watchdog"
        if self.exception is not None:
            raise self.exception
        assert self.result is not None
        return self.result

    def assert_native_reaped(self):
        assert len(self.processes) == 1
        assert self.processes[0].poll() is not None
        if self.result is not None:
            assert self.result.workspace_cleaned
        assert not list((self.directory / "workspaces").iterdir())

    def assert_owner_workers_drained(self):
        assert self.workers
        assert all(not worker.is_alive() for worker in self.workers)
        assert all(stream.closed for stream in self.actual_streams)
        assert not self.worker_failures

    def cleanup(self):
        # Even baseline assertion failures release controlled pipe locks first.
        self.release.set()
        for process in self.processes:
            if process.poll() is None:
                process.kill()  # This owned Popen child has not been reaped.
            process.wait(timeout=2)
        if self.host is not None:
            self.host.join(3)
            assert not self.host.is_alive(), "test watchdog thread survived cleanup"
        for worker in self.workers:
            if worker.ident is not None:
                worker.join(3)
            assert not worker.is_alive(), "test-owned pipe worker survived release"
        for stream in self.actual_streams:
            if not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass
            assert stream.closed, "test-owned native pipe FD remained open"


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    candidate_root = Path(os.environ.get(
        "IR_LIFECYCLE_CANDIDATE_ROOT", str(Path(__file__).resolve().parents[4])
    )).resolve()
    expected_process = candidate_root / "ipfs_datasets_py/logic/backends/process.py"
    assert Path(module.__file__).resolve() == expected_process, \
        "native regressions require the harness-bound isolated candidate origin"
    before = _fd_targets()
    cases = []

    def make(**kwargs):
        assert not cases, "one exact-source invocation per fixture"
        case = _NativeCase(tmp_path, monkeypatch, **kwargs)
        cases.append(case)
        return case

    try:
        yield make
    finally:
        for case in cases:
            case.cleanup()
        assert _fd_targets() == before, "native regression left changed/open FD targets"


def _assert_pipe_failure(result, *, diagnostic):
    assert not result.ok, "native rc0 must not admit a failed/incomplete pipe worker"
    assert result.error, "pipe failure must remain visible in the owner result"
    assert diagnostic in result.error.lower()
    assert len(result.error.encode("utf-8")) <= 4096


def test_writer_start_failure_reaps_child_and_closes_all_pipe_handles(native_case):
    case = native_case(mode="writer_start_failure", role="stdin")
    result = case.run(stdin=b"authored bounded input", source=_NONREADING_CHILD)
    assert case.start_failure_observed
    assert len(case.workers) == 3
    assert not result.ok and "authored writer start failure" in result.error
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


@pytest.mark.parametrize("termination", ["timeout", "cancellation"])
def test_full_native_stdin_pipe_is_drained_after_termination(native_case, termination):
    case = native_case(mode="blocked_stdin", role="stdin")

    class FullPipeCancellation:
        def is_set(self):
            full = case.full_stdin_pipe()
            return termination == "cancellation" and full

    payload = b"authored-input-" * 8192
    result = case.run(
        stdin=payload, source=_NONREADING_CHILD,
        cancellation=FullPipeCancellation(), timeout=0.6,
    )
    assert case.pipe_capacity is not None and len(payload) > case.pipe_capacity
    assert case.pipe_was_full, "fixture never reached a genuinely full native stdin pipe"
    assert not result.ok
    assert (result.timed_out if termination == "timeout" else result.cancelled)
    assert result.process_tree_terminated
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


@pytest.mark.parametrize("role", ["stdout", "stderr"])
def test_native_reader_io_failure_cannot_return_success(native_case, role):
    case = native_case(mode="read_error", role=role)
    result = case.run()
    assert case.fault_observed.is_set(), "authored read fault was not exercised"
    assert result.returncode == 0, "the authored child itself must complete normally"
    _assert_pipe_failure(result, diagnostic=role)
    assert "oserror" in result.error.lower()
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


def test_live_normal_stdout_reader_refuses_success_before_test_release(native_case):
    case = native_case(mode="live_reader", role="stdout")
    result = case.run()
    assert case.fault_observed.is_set()
    assert any(worker.is_alive() for worker in case.workers)
    assert result.returncode == 0, "native exit alone must not qualify pipe completion"
    _assert_pipe_failure(result, diagnostic="stdout")
    assert result.stdout == "", "a live reader's mutable capture must not be snapshotted"
    case.assert_native_reaped()


def test_live_normal_stdin_writer_refuses_success_before_test_release(native_case):
    case = native_case(mode="live_writer", role="stdin")
    result = case.run(stdin=b"authored bounded input")
    assert case.fault_observed.is_set()
    assert not case.write_returned.is_set()
    assert any(worker.is_alive() for worker in case.workers)
    assert result.returncode == 0, "native exit alone must not qualify pipe completion"
    _assert_pipe_failure(result, diagnostic="stdin")
    case.assert_native_reaped()


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_native_stdin_io_failure_cannot_return_success(native_case, operation):
    case = native_case(mode=operation + "_error", role="stdin")
    result = case.run(stdin=b"authored bounded input", source=_READING_CHILD)
    assert case.fault_observed.is_set(), "authored stdin I/O fault was not exercised"
    assert case.raised_faults and isinstance(case.raised_faults[0], OSError)
    assert result.returncode == 0
    _assert_pipe_failure(result, diagnostic="stdin")
    assert "oserror" in result.error.lower()
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


@pytest.mark.parametrize("role", ["stdout", "stderr", "stdin"])
def test_pipe_close_error_refuses_success_after_real_descriptor_cleanup(native_case, role):
    case = native_case(mode="close_error", role=role)
    result = case.run(
        stdin=b"authored bounded input" if role == "stdin" else None,
        source=_READING_CHILD if role == "stdin" else _SHORT_CHILD,
    )
    assert case.fault_observed.is_set(), "authored close fault was not exercised"
    assert case.raised_faults and isinstance(case.raised_faults[0], OSError)
    assert result.returncode == 0
    _assert_pipe_failure(result, diagnostic=role)
    assert "oserror" in result.error.lower()
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("operation,role", [
    ("read", "stdout"), ("close", "stdout"),
    ("write", "stdin"), ("flush", "stdin"), ("close", "stdin"),
])
def test_worker_control_exception_preserves_original_instance(
    native_case, exception_type, operation, role,
):
    original = exception_type("authored worker control interruption")
    case = native_case(mode=operation + "_error", role=role, fault_exception=original)
    with pytest.raises(exception_type) as caught:
        case.run(
            stdin=b"authored bounded input" if role == "stdin" else None,
            source=_READING_CHILD if role == "stdin" else _SHORT_CHILD,
        )
    assert caught.value is original
    assert case.exception is original
    assert case.raised_faults == [original]
    assert case.fault_observed.is_set()
    assert case.processes[0].returncode == 0
    case.assert_native_reaped()
    case.assert_owner_workers_drained()


def test_genuine_child_closed_stdin_preserves_broken_pipe_compatibility(native_case):
    case = native_case(mode="genuine_broken_pipe", role="stdin")
    payload = b"authored-early-close-" * 8192
    result = case.run(stdin=payload, source=_CLOSED_STDIN_CHILD)
    assert case.pipe_capacity is not None and len(payload) > case.pipe_capacity
    assert case.broken_pipes, "the real child must cause a genuine native BrokenPipeError"
    assert all(isinstance(error, BrokenPipeError) for error in case.broken_pipes)
    assert not case.fault_observed.is_set(), "the positive case must not inject an I/O fault"
    assert result.returncode == 0 and result.ok
    assert not result.error
    assert result.stdout == "authored child closed stdin\n"
    case.assert_native_reaped()
    case.assert_owner_workers_drained()
