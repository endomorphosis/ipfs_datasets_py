"""Availability and construction helpers for hammer ATP/ITP routes."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ipfs_datasets_py.logic.hammers.process_lifecycle import (
    ProcessKind,
    ProcessLimits,
    get_process_supervisor,
)

from .hammer import HammerBackendRunner, SubprocessHammerBackendRunner
from .hammer import (
    HammerBackendResult,
    HammerBackendStatus,
    HammerTranslation,
)


HAMMER_BACKEND_HEALTH_SCHEMA_VERSION = "legal-ir-hammer-backend-health-v1"

ExecutableResolver = Callable[[str], Optional[str]]
InstallerRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


class PythonZ3HammerBackendRunner:
    """Run SMT-LIB through the native Python Z3 binding.

    DGX Spark hosts are aarch64, while an unrelated executable on ``PATH`` may
    target x86-64.  The Python wheel is already architecture checked by the
    interpreter, so this route is both faster and more portable than spawning
    a solver binary.
    """

    name = "z3_python"
    problem_format = "smt-lib"

    def run(
        self, translation: HammerTranslation, timeout_seconds: float
    ) -> HammerBackendResult:
        start = time.time()
        try:
            import z3

            solver = z3.Solver()
            solver.set(timeout=max(1, int(float(timeout_seconds) * 1000)))
            solver.from_string(translation.problem)
            result = solver.check()
            reason = str(solver.reason_unknown() or "") if result == z3.unknown else ""
            if result == z3.unsat:
                status = HammerBackendStatus.PROVED
                proved = True
            elif result == z3.sat:
                status = HammerBackendStatus.DISPROVED
                proved = False
            elif "timeout" in reason.lower():
                status = HammerBackendStatus.TIMEOUT
                proved = False
            else:
                status = HammerBackendStatus.UNKNOWN
                proved = False
            return HammerBackendResult(
                backend=self.name,
                status=status,
                proved=proved,
                elapsed_seconds=time.time() - start,
                translation_format=translation.target_format,
                proof_trace="z3-python:unsat" if proved else "",
                raw_output=str(result),
                error=reason,
                timed_out=status is HammerBackendStatus.TIMEOUT,
                metadata={"runtime": "python-z3"},
            )
        except Exception as exc:
            return HammerBackendResult(
                backend=self.name,
                status=HammerBackendStatus.ERROR,
                proved=False,
                elapsed_seconds=time.time() - start,
                translation_format=translation.target_format,
                error=f"{type(exc).__name__}: {str(exc)[:500]}",
                metadata={"runtime": "python-z3"},
            )


@dataclass(frozen=True)
class HammerBackendSpec:
    """Static launch metadata for one hammer route."""

    name: str
    executable: str
    route_type: str
    problem_format: str = ""
    args: Sequence[str] = field(default_factory=tuple)
    suffix: str = ".p"
    version_args: Sequence[str] = field(default_factory=lambda: ("--version",))
    install_command: Sequence[str] = field(default_factory=tuple)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["args"] = list(self.args)
        payload["version_args"] = list(self.version_args)
        payload["install_command"] = list(self.install_command)
        return payload


@dataclass(frozen=True)
class HammerBackendHealth:
    """Deterministic health record suitable for daemon summaries."""

    name: str
    route_type: str
    executable: str
    available: bool
    resolved_path: str = ""
    problem_format: str = ""
    installer_available: bool = False
    install_command: Sequence[str] = field(default_factory=tuple)
    version_output: str = ""
    check_error: str = ""
    elapsed_seconds: float = 0.0
    schema_version: str = HAMMER_BACKEND_HEALTH_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": bool(self.available),
            "check_error": self.check_error,
            "elapsed_seconds": round(float(self.elapsed_seconds), 12),
            "executable": self.executable,
            "install_command": list(self.install_command),
            "installer_available": bool(self.installer_available),
            "name": self.name,
            "problem_format": self.problem_format,
            "resolved_path": self.resolved_path,
            "route_type": self.route_type,
            "schema_version": self.schema_version,
            "version_output": self.version_output,
        }


def default_hammer_backend_specs() -> List[HammerBackendSpec]:
    """Return known local hammer routes.

    ATP/SMT routes are runnable hammer backends. Lean, Coq, and Isabelle are
    checker/reconstruction routes and are exposed here for the same daemon
    health summary.
    """

    return [
        HammerBackendSpec(
            name="z3",
            executable="z3",
            route_type="smt",
            problem_format="smt-lib",
            suffix=".smt2",
            install_command=("python", "-m", "pip", "install", "z3-solver"),
            notes="SMT-LIB backend.",
        ),
        HammerBackendSpec(
            name="cvc5",
            executable="cvc5",
            route_type="smt",
            problem_format="smt-lib",
            args=("--lang", "smt2"),
            suffix=".smt2",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--cvc5",
            ),
            notes=(
                "SMT-LIB backend; uses a checksummed native platform release or "
                "IPFS_DATASETS_PY_CVC5_EXECUTABLE."
            ),
        ),
        HammerBackendSpec(
            name="vampire",
            executable="vampire",
            route_type="atp",
            problem_format="tptp-fof",
            args=(
                "--time_limit",
                "10",
                "--proof",
                "tptp",
                "--input_syntax",
                "tptp",
            ),
            suffix=".p",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--vampire",
            ),
            notes="TPTP FOF backend using a checksummed platform release.",
        ),
        HammerBackendSpec(
            name="e_prover",
            executable="eprover",
            route_type="atp",
            problem_format="tptp-fof",
            args=("--auto", "--proof-object"),
            suffix=".p",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--eprover",
            ),
            notes="TPTP FOF backend built from a checksummed source release.",
        ),
        HammerBackendSpec(
            name="lean",
            executable="lean",
            route_type="itp_checker",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--lean",
            ),
            notes="Native Lean reconstruction checker.",
        ),
        HammerBackendSpec(
            name="coq",
            executable="coqc",
            route_type="itp_checker",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--coq",
            ),
            notes="Native Coq reconstruction checker.",
        ),
        HammerBackendSpec(
            name="isabelle",
            executable="isabelle",
            route_type="itp_checker",
            install_command=(
                "python",
                "-m",
                "scripts.setup.ipfs_prover_installer",
                "--yes",
                "--isabelle",
            ),
            notes="Official checksummed Isabelle reconstruction bundle.",
        ),
    ]


def hammer_backend_specs_by_name() -> Dict[str, HammerBackendSpec]:
    return {spec.name: spec for spec in default_hammer_backend_specs()}


def _resolve_executable(executable: str, resolver: ExecutableResolver) -> str:
    candidate = str(executable or "").strip()
    if not candidate:
        return ""
    if Path(candidate).is_file():
        return candidate
    if resolver is shutil.which:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            find_executable,
        )

        return str(find_executable(candidate) or "")
    resolved = resolver(candidate)
    return str(resolved or "")


def check_hammer_backend_availability(
    spec: HammerBackendSpec | str,
    *,
    resolver: ExecutableResolver = shutil.which,
    include_version: bool = False,
    timeout_seconds: float = 2.0,
) -> HammerBackendHealth:
    """Probe one backend route without raising on missing binaries."""

    specs = hammer_backend_specs_by_name()
    resolved_spec = specs.get(spec, None) if isinstance(spec, str) else spec
    if resolved_spec is None:
        resolved_spec = HammerBackendSpec(
            name=str(spec),
            executable=str(spec),
            route_type="unknown",
        )
    start = time.time()
    resolved_path = ""
    version_output = ""
    error = ""
    try:
        resolved_path = _resolve_executable(resolved_spec.executable, resolver)
        if resolved_path and include_version and resolved_spec.version_args:
            kind = (
                ProcessKind.SMT
                if resolved_spec.problem_format.lower().startswith("smt")
                else ProcessKind.LEAN
                if resolved_spec.name == "lean"
                else ProcessKind.ATP
            )
            completed = get_process_supervisor().run(
                [resolved_path, *resolved_spec.version_args],
                kind=kind,
                limits=ProcessLimits(
                    wall_time_seconds=max(0.001, float(timeout_seconds))
                ),
            )
            if completed.error:
                error = completed.error
            elif completed.timed_out:
                error = f"timed out after {timeout_seconds}s"
            version_output = "\n".join(
                part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
            )[:1000]
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
    return HammerBackendHealth(
        name=resolved_spec.name,
        route_type=resolved_spec.route_type,
        executable=resolved_spec.executable,
        available=bool(resolved_path) and not error,
        resolved_path=resolved_path,
        problem_format=resolved_spec.problem_format,
        installer_available=bool(resolved_spec.install_command),
        install_command=tuple(resolved_spec.install_command),
        version_output=version_output,
        check_error=error,
        elapsed_seconds=time.time() - start,
    )


def check_hammer_backend_health(
    backend_names: Optional[Iterable[str]] = None,
    *,
    resolver: ExecutableResolver = shutil.which,
    include_version: bool = False,
    timeout_seconds: float = 2.0,
) -> List[HammerBackendHealth]:
    specs = hammer_backend_specs_by_name()
    names = list(backend_names or specs.keys())
    return [
        check_hammer_backend_availability(
            specs.get(name, name),
            resolver=resolver,
            include_version=include_version,
            timeout_seconds=timeout_seconds,
        )
        for name in names
    ]


def hammer_backend_health_summary(
    health: Sequence[HammerBackendHealth],
) -> Dict[str, Any]:
    """Return compact aggregate health for daemon summaries."""

    records = [item.to_dict() for item in health]
    available = [item.name for item in health if item.available]
    unavailable = [item.name for item in health if not item.available]
    return {
        "available_count": len(available),
        "available_routes": available,
        "records": records,
        "schema_version": HAMMER_BACKEND_HEALTH_SCHEMA_VERSION,
        "unavailable_count": len(unavailable),
        "unavailable_routes": unavailable,
    }


def backend_health_for_runners(
    backends: Sequence[HammerBackendRunner],
    *,
    resolver: ExecutableResolver = shutil.which,
) -> List[HammerBackendHealth]:
    """Summarize concrete runner objects used by a HammerPipeline."""

    specs = hammer_backend_specs_by_name()
    health: List[HammerBackendHealth] = []
    for backend in backends:
        name = str(getattr(backend, "name", "unknown") or "unknown")
        executable = str(getattr(backend, "executable", "") or "")
        if executable:
            spec = specs.get(
                name,
                HammerBackendSpec(
                    name=name,
                    executable=executable,
                    route_type="atp",
                    problem_format=str(getattr(backend, "problem_format", "") or ""),
                ),
            )
            health.append(
                check_hammer_backend_availability(
                    spec,
                    resolver=resolver,
                    include_version=resolver is shutil.which,
                )
            )
            continue
        health.append(
            HammerBackendHealth(
                name=name,
                route_type="runtime_runner",
                executable="",
                available=True,
                problem_format=str(getattr(backend, "problem_format", "") or ""),
            )
        )
    return health


def default_hammer_backend_runners(
    backend_names: Optional[Iterable[str]] = None,
) -> List[HammerBackendRunner]:
    """Return native Python SMT routes followed by fail-closed subprocess routes."""

    names = list(backend_names or ("z3", "cvc5", "vampire", "e_prover"))
    runners: List[HammerBackendRunner] = []
    subprocess_names = list(names)
    if "z3" in names:
        try:
            import z3  # noqa: F401

            runners.append(PythonZ3HammerBackendRunner())
            subprocess_names = [name for name in subprocess_names if name != "z3"]
        except Exception:
            pass
    runners.extend(default_hammer_subprocess_backends(subprocess_names))
    return runners


def _managed_executable_resolver(prover_name: str) -> ExecutableResolver:
    """Resolve and, if needed, install one backend once per pipeline."""

    state: Dict[str, Any] = {"attempted": False, "path": None}
    lock = threading.Lock()

    def resolve(_executable: str) -> Optional[str]:
        if state["attempted"]:
            return state["path"]
        with lock:
            if not state["attempted"]:
                from ipfs_datasets_py.logic.external_provers.lazy_installer import (
                    ensure_prover_executable,
                )

                state["path"] = ensure_prover_executable(
                    prover_name,
                    reason=f"Hammer {prover_name} proof route",
                )
                state["attempted"] = True
        return state["path"]

    return resolve


def default_hammer_subprocess_backends(
    backend_names: Optional[Iterable[str]] = None,
) -> List[SubprocessHammerBackendRunner]:
    """Construct subprocess runners for ATP/SMT routes.

    Missing executables are intentionally not filtered out here. The runner
    returns an UNAVAILABLE backend result, which keeps hparam and daemon runs
    fail-closed but nonfatal.
    """

    specs = hammer_backend_specs_by_name()
    names = list(backend_names or ("z3", "cvc5", "vampire", "e_prover"))
    runners: List[SubprocessHammerBackendRunner] = []
    for name in names:
        spec = specs.get(name)
        if spec is None or spec.route_type not in {"atp", "smt"}:
            continue
        runners.append(
            SubprocessHammerBackendRunner(
                name=spec.name,
                executable=spec.executable,
                problem_format=spec.problem_format,
                args=spec.args,
                suffix=spec.suffix,
                executable_resolver=_managed_executable_resolver(spec.name),
            )
        )
    return runners


def lazy_install_hammer_backend(
    name: str,
    *,
    runner: Optional[InstallerRunner] = None,
    timeout_seconds: float = 300.0,
) -> HammerBackendHealth:
    """Run a registered install hook on explicit request, then re-probe.

    This helper never runs during health checks. Callers must opt into it, which
    keeps tests and daemon summaries side-effect free.
    """

    specs = hammer_backend_specs_by_name()
    spec = specs.get(name)
    if spec is None:
        return check_hammer_backend_availability(name)
    if not spec.install_command:
        return check_hammer_backend_availability(spec)
    if runner is None:
        def _run(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
            result = get_process_supervisor().run(
                list(command),
                kind=ProcessKind.TOOLCHAIN,
                limits=ProcessLimits(wall_time_seconds=max(0.001, float(timeout))),
            )
            return subprocess.CompletedProcess(
                list(command), result.returncode or 0, result.stdout, result.stderr
            )

        runner = _run
    try:
        runner(
            list(spec.install_command),
            max(0.001, float(timeout_seconds)),
        )
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        pass
    return check_hammer_backend_availability(spec)


__all__ = [
    "HAMMER_BACKEND_HEALTH_SCHEMA_VERSION",
    "HammerBackendHealth",
    "HammerBackendSpec",
    "backend_health_for_runners",
    "check_hammer_backend_availability",
    "check_hammer_backend_health",
    "default_hammer_backend_specs",
    "default_hammer_backend_runners",
    "default_hammer_subprocess_backends",
    "hammer_backend_health_summary",
    "hammer_backend_specs_by_name",
    "lazy_install_hammer_backend",
    "PythonZ3HammerBackendRunner",
]
