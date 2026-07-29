"""Contract tests for the shared bounded external-tool lifecycle."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest
from ipfs_datasets_py.logic.backends.process import (
    BOUNDED_TOOL_RUNNER_VERSION,
    BoundedToolRunner,
    CancellationToken,
    ProcessInvocation,
    RawProcessResult,
    SubprocessExecutor,
    ToolProcessError,
    ToolRunLimits,
    ToolRunRequest,
    ToolRuntime,
)

PYTHON = sys.executable


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[ProcessInvocation] = []

    def execute(self, invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        self.calls.append(invocation)
        source = invocation.cwd / "input" / "claim.txt"
        if source.exists():
            (invocation.cwd / "result.txt").write_text(
                source.read_text(encoding="utf-8").upper(),
                encoding="utf-8",
            )
        return RawProcessResult(
            returncode=0,
            stdout=b"proved\n",
            elapsed_seconds=0.125,
            pid=42,
        )


def _runner(tmp_path: Path, executor=None) -> BoundedToolRunner:
    return BoundedToolRunner(
        executor=executor,
        workspace_root=tmp_path / "runs",
        base_environment={"PATH": os.environ.get("PATH", os.defpath)},
    )


def test_injected_executor_observes_isolated_workspace_and_declared_outputs(
    tmp_path: Path,
) -> None:
    fake = FakeExecutor()
    runner = _runner(tmp_path, fake)
    request = ToolRunRequest(
        argv=("fake-native", "{workspace}/input/claim.txt"),
        input_files={"input/claim.txt": "p -> p"},
        output_paths=("result.txt",),
    )

    result = runner.run(request)

    assert result.ok
    assert result.interface_version == BOUNDED_TOOL_RUNNER_VERSION
    assert result.stdout == "proved\n"
    assert result.outputs == {"result.txt": b"P -> P"}
    assert fake.calls[0].argv[1] == str(
        fake.calls[0].cwd / "input" / "claim.txt"
    )
    assert fake.calls[0].environment["HOME"] == str(fake.calls[0].cwd)
    assert fake.calls[0].environment["TMPDIR"] == str(fake.calls[0].cwd)
    assert not fake.calls[0].cwd.exists()
    assert result.workspace_cleaned


@pytest.mark.parametrize(
    "runtime",
    [
        ToolRuntime.NATIVE,
        ToolRuntime.JVM,
        ToolRuntime.OCAML,
        ToolRuntime.OPAM,
        ToolRuntime.WASM,
    ],
)
def test_runtime_families_share_one_injected_contract(
    tmp_path: Path, runtime: ToolRuntime
) -> None:
    fake = FakeExecutor()
    result = _runner(tmp_path, fake).run(
        ToolRunRequest(argv=("fake-host", "--version"), runtime=runtime)
    )
    assert result.ok
    assert result.runtime is runtime
    assert fake.calls[0].runtime is runtime


def test_argv_is_not_a_shell_string_and_metacharacters_are_literal(
    tmp_path: Path,
) -> None:
    with pytest.raises(ToolProcessError, match="never a shell string"):
        ToolRunRequest(argv="solver; touch escaped")  # type: ignore[arg-type]

    marker = tmp_path / "must-not-exist"
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                "import sys; print(sys.argv[1])",
                f"; touch {marker}",
            )
        )
    )
    assert result.ok
    assert result.stdout.strip() == f"; touch {marker}"
    assert not marker.exists()


@pytest.mark.parametrize(
    "path",
    ["../escape", "/absolute", "nested/../../escape", r"windows\\escape"],
)
def test_workspace_paths_reject_escape_and_nonportable_forms(
    tmp_path: Path, path: str
) -> None:
    with pytest.raises(ToolProcessError):
        _runner(tmp_path, FakeExecutor()).run(
            ToolRunRequest(argv=("fake",), input_files={path: "x"})
        )


def test_path_count_length_and_input_bytes_are_bounded(tmp_path: Path) -> None:
    limits = ToolRunLimits(
        max_path_bytes=8,
        max_input_bytes=4,
        max_workspace_bytes=4,
        max_output_files=1,
    )
    runner = _runner(tmp_path, FakeExecutor())
    with pytest.raises(ToolProcessError, match="path exceeds"):
        runner.run(
            ToolRunRequest(
                argv=("fake",),
                limits=limits,
                input_files={"too-long-name": b"x"},
            )
        )
    with pytest.raises(ToolProcessError, match="input files exceed"):
        runner.run(
            ToolRunRequest(
                argv=("fake",), limits=limits, input_files={"a": b"12345"}
            )
        )
    with pytest.raises(ToolProcessError, match="too many"):
        runner.run(
            ToolRunRequest(
                argv=("fake",),
                limits=limits,
                output_paths=("a", "b"),
            )
        )


def test_stdout_stderr_and_declared_files_are_truncated_without_deadlock(
    tmp_path: Path,
) -> None:
    limits = ToolRunLimits(
        timeout_seconds=3,
        max_output_bytes=32,
        max_input_bytes=128,
        max_workspace_bytes=1024,
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                (
                    "import pathlib,sys;"
                    "sys.stdout.write('o'*100000);"
                    "sys.stderr.write('e'*100000);"
                    "pathlib.Path('large.txt').write_bytes(b'x'*100)"
                ),
            ),
            limits=limits,
            output_paths=("large.txt",),
        )
    )
    assert result.returncode == 0
    assert len(result.stdout.encode()) == 32
    assert len(result.stderr.encode()) == 32
    assert result.output_files["large.txt"] == b"x" * 32
    assert result.output_truncated


def test_sensitive_argv_environment_output_and_errors_are_redacted(
    tmp_path: Path,
) -> None:
    secret = "super-private-token"

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        assert invocation.environment["API_TOKEN"] == secret
        (invocation.cwd / "receipt.txt").write_text(
            f"receipt contains {secret}", encoding="utf-8"
        )
        return RawProcessResult(
            returncode=2,
            stdout=f"received {secret}",
            stderr=f"failed with {secret}",
            error=f"tool rejected {secret}",
        )

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake", "--token", secret, f"--password={secret}"),
            environment={"API_TOKEN": secret},
            output_paths=("receipt.txt",),
        )
    )
    serialized = repr(result.to_dict())
    assert secret not in serialized
    assert result.command == (
        "fake",
        "--token",
        "<redacted>",
        "--password=<redacted>",
    )
    assert result.stdout == "received <redacted>"
    assert result.stderr == "failed with <redacted>"
    assert result.error == "tool rejected <redacted>"
    assert result.output_files["receipt.txt"] == b"receipt contains <redacted>"


def test_redaction_cannot_expand_results_past_output_bound(tmp_path: Path) -> None:
    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        (invocation.cwd / "receipt").write_bytes(b"x" * 32)
        return RawProcessResult(
            returncode=0,
            stdout="x" * 32,
            stderr="x" * 32,
            error="x" * 32,
        )

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake",),
            limits=ToolRunLimits(max_output_bytes=32),
            output_paths=("receipt",),
            secrets=("x",),
        )
    )
    assert len(result.stdout.encode()) <= 32
    assert len(result.stderr.encode()) <= 32
    assert len(result.error.encode()) <= 32
    assert len(result.output_files["receipt"]) <= 32
    assert result.output_truncated
    assert b"x" not in result.output_files["receipt"]


def test_environment_is_minimal_and_workspace_values_cannot_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNRELATED_PARENT_SECRET", "do-not-inherit")
    fake = FakeExecutor()
    _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake",),
            environment={"HOME": "/outside", "SAFE_SETTING": "yes"},
        )
    )
    environment = fake.calls[0].environment
    assert "UNRELATED_PARENT_SECRET" not in environment
    assert environment["HOME"] == str(fake.calls[0].cwd)
    assert environment["SAFE_SETTING"] == "yes"


def test_precancelled_request_never_invokes_executor_or_creates_workspace(
    tmp_path: Path,
) -> None:
    fake = FakeExecutor()
    token = CancellationToken()
    token.cancel()
    result = _runner(tmp_path, fake).run(
        ToolRunRequest(argv=("fake",)), cancellation=token
    )
    assert result.cancelled
    assert result.termination_reason == "cancelled"
    assert fake.calls == []
    assert not (tmp_path / "runs").exists()


def test_timeout_terminates_process_group(tmp_path: Path) -> None:
    limits = ToolRunLimits(
        timeout_seconds=0.15,
        termination_grace_seconds=0.1,
        max_output_bytes=128,
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(PYTHON, "-c", "import time; time.sleep(60)"),
            limits=limits,
        )
    )
    assert result.timed_out
    assert result.termination_reason == "timeout"
    assert result.process_tree_terminated
    assert result.returncode is not None


@pytest.mark.skipif(os.name != "posix", reason="process-group assertion is POSIX")
def test_timeout_terminates_descendant_that_ignores_sigterm(tmp_path: Path) -> None:
    code = (
        "import signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(60)']);"
        "print(p.pid,flush=True);time.sleep(60)"
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(PYTHON, "-c", code),
            limits=ToolRunLimits(
                timeout_seconds=0.2,
                termination_grace_seconds=0.05,
                max_output_bytes=128,
            ),
        )
    )
    child_pid = int(result.stdout.strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
            process_stat = Path(f"/proc/{child_pid}/stat")
            if process_stat.exists() and ") Z " in process_stat.read_text():
                break
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"descendant {child_pid} survived process-tree cleanup")
    assert result.timed_out
    assert result.process_tree_terminated


def test_live_cancellation_terminates_process(tmp_path: Path) -> None:
    token = CancellationToken()
    runner = _runner(tmp_path)
    holder = {}

    def invoke() -> None:
        holder["result"] = runner.run(
            ToolRunRequest(
                argv=(PYTHON, "-c", "import time; time.sleep(60)"),
                limits=ToolRunLimits(timeout_seconds=5),
            ),
            cancellation=token,
        )

    thread = threading.Thread(target=invoke)
    thread.start()
    time.sleep(0.1)
    token.cancel()
    thread.join(timeout=3)
    assert not thread.is_alive()
    result = holder["result"]
    assert result.cancelled
    assert result.process_tree_terminated


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc").is_dir(),
    reason="descendant group inspection requires Linux /proc",
)
def test_successful_leader_cannot_leave_a_background_descendant(
    tmp_path: Path,
) -> None:
    code = (
        "import subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print(p.pid,flush=True)"
    )
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(PYTHON, "-c", code),
            limits=ToolRunLimits(
                timeout_seconds=2,
                termination_grace_seconds=0.05,
                max_output_bytes=128,
            ),
        )
    )
    child_pid = int(result.stdout.strip())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
            process_stat = Path(f"/proc/{child_pid}/stat")
            if process_stat.exists() and ") Z " in process_stat.read_text():
                break
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"background descendant {child_pid} survived cleanup")
    assert result.returncode == 0
    assert result.process_tree_terminated


def test_workspace_cleanup_occurs_when_executor_raises(tmp_path: Path) -> None:
    workspace = None

    def fail(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        nonlocal workspace
        workspace = invocation.cwd
        raise RuntimeError("synthetic failure")

    result = _runner(tmp_path, fail).run(ToolRunRequest(argv=("fake",)))
    assert result.termination_reason == "error"
    assert "synthetic failure" in result.error
    assert workspace is not None and not workspace.exists()


def test_output_symlinks_are_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"secret")

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        try:
            (invocation.cwd / "result").symlink_to(outside)
        except OSError:
            pytest.skip("symlinks are unavailable")
        return RawProcessResult(returncode=0)

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(argv=("fake",), output_paths=("result",))
    )
    assert result.output_files == {}


def test_probe_only_uses_path_discovery_and_does_not_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "probe-tool"
    executable.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    executable.chmod(0o755)
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("probe must not start a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    runner = BoundedToolRunner(base_environment={"PATH": str(tmp_path)})
    probe = runner.probe("probe-tool", runtime=ToolRuntime.WASM)
    assert probe.available
    assert probe.executable_path == str(executable.resolve())
    assert runner.is_available("probe-tool")
    assert not called
    assert list(tmp_path.iterdir()) == [executable]


def test_import_has_no_process_install_or_workspace_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ipfs_datasets_py.logic.backends.process as process_module

    def forbidden(*args, **kwargs):
        raise AssertionError("module import must not perform an external action")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    before = set(tmp_path.iterdir())
    # Execute the source as a fresh module without mutating the live module's
    # class identities (which an in-place reload deliberately invalidates).
    isolated = ModuleType("isolated_bounded_process")
    isolated.__file__ = process_module.__file__
    isolated.__package__ = process_module.__package__
    sys.modules[isolated.__name__] = isolated
    try:
        source = Path(process_module.__file__).read_text(encoding="utf-8")
        exec(compile(source, process_module.__file__, "exec"), isolated.__dict__)
    finally:
        sys.modules.pop(isolated.__name__, None)
    assert set(tmp_path.iterdir()) == before


def test_limits_validate_memory_time_and_workspace_relationship() -> None:
    with pytest.raises(ToolProcessError, match="timeout_seconds"):
        ToolRunLimits(timeout_seconds=0)
    with pytest.raises(ToolProcessError, match="memory_bytes"):
        ToolRunLimits(memory_bytes=0)
    with pytest.raises(ToolProcessError, match="at least"):
        ToolRunLimits(max_input_bytes=10, max_workspace_bytes=9)


def test_callable_fake_and_sequence_convenience_are_supported(tmp_path: Path) -> None:
    calls = []

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        calls.append(invocation)
        return RawProcessResult(returncode=0, stdout="deterministic")

    result = _runner(tmp_path, fake).run(
        ("fake-jvm", "-jar", "checker.jar"),
        runtime=ToolRuntime.JVM,
    )
    assert result.ok
    assert result.stdout == "deterministic"
    assert calls[0].runtime is ToolRuntime.JVM


def test_subprocess_executor_is_explicitly_injectable(tmp_path: Path) -> None:
    runner = _runner(tmp_path, SubprocessExecutor())
    result = runner.run(
        ToolRunRequest(argv=(PYTHON, "-c", "print('explicit')"))
    )
    assert result.ok
    assert result.stdout.strip() == "explicit"
