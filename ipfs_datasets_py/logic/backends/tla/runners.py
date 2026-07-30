"""Bounded TLC and Apalache runners for generated TLA+ artifacts.

``TLCBackend@1`` and ``ApalacheBackend@1`` are distinct model-check surfaces:

* TLC may check temporal liveness/PROPERTY clauses under fairness assumptions.
* Apalache is a finite-trace symbolic checker: safety/invariants only, with an
  explicit length bound and no liveness claims.

Both runners:

* require an explicit JVM-hosted executable (or an injected probe/runner);
* return ``unavailable`` when the tool or JVM is absent — never a silent pass;
* parse counterexamples and support deterministic replay against source maps;
* emit :class:`ModelCheckResult` with bounded authority only.

The shared :class:`TLAModelCheckerBackend` base implements the common lifecycle
while keeping capability and bound disclosures tool-specific.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from ...families.models import EvidenceAuthority
from ...ir_core.claims import FrozenMap, stable_digest
from ...ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolProbe,
    ToolRunLimits,
    ToolRunRequest,
    ToolRunResult,
    ToolRuntime,
)
from ..results import (
    ModelCheckResult,
    ResultAuthority,
    ResultStatus,
)
from .compiler import (
    GeneratedTLAArtifacts,
    TLA_BACKEND_VERSION,
    TLACompiler,
    TLACompilerError,
    TLASourceMapEntry,
)

TLC_BACKEND_VERSION: Final = "TLCBackend@1"
APALACHE_BACKEND_VERSION: Final = "ApalacheBackend@1"
TLA_MODEL_CHECK_RECEIPT_VERSION: Final = "tla-model-check-receipt/v1"
TLA_COUNTEREXAMPLE_VERSION: Final = "tla-counterexample/v1"
TLA_CAPABILITY_VERSION: Final = "tla-model-checker-capability/v1"

DEFAULT_VERSION_TIMEOUT_SECONDS: Final = 3.0
DEFAULT_MAX_OUTPUT_BYTES: Final = 2 * 1024 * 1024

_TLC_SUCCESS_MARKERS: Final = (
    "model checking completed. no error has been found",
    "model checking completed",
    "no error has been found",
)
_APALACHE_SUCCESS_MARKERS: Final = (
    "checker reports no error",
    "no error up to computation length",
    "verification result: pass",
    "result: pass",
)
_COUNTEREXAMPLE_MARKERS: Final = (
    "counterexample",
    "is violated",
    "temporal properties were violated",
    "checker reports an error",
    "checker has found an error",
    "found an invariant violation",
    "error trace",
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class TLARunnerError(ValueError):
    """Raised when a model-checker request or receipt violates the contract."""


class ModelCheckerTool(StrEnum):
    """Supported external state-model checkers."""

    TLC = "tlc"
    APALACHE = "apalache"


class ModelCheckOutcomeStatus(StrEnum):
    """Operational classification of one bounded checker execution."""

    PASSED = "passed"
    COUNTEREXAMPLE = "counterexample"
    UNKNOWN = "unknown"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    MALFORMED = "malformed"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or (not optional and not value.strip()):
        if optional and isinstance(value, str):
            return value
        raise TLARunnerError(f"{field_name} must be a string")
    if "\x00" in value:
        raise TLARunnerError(f"{field_name} must not contain NUL bytes")
    return value if optional else value.strip()


def _digest(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    candidate = text.removeprefix("sha256:")
    if not _DIGEST.fullmatch(candidate):
        if len(candidate) == 64 and all(
            ch in "0123456789abcdef" for ch in candidate
        ):
            return candidate
        raise TLARunnerError(f"{field_name} must be a lowercase SHA-256 digest")
    return candidate


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise TLARunnerError(f"{field_name} must be one of {choices}") from error


@dataclass(frozen=True, slots=True)
class ModelCheckerCapability:
    """Explicit, tool-specific capability and bound disclosure."""

    tool: ModelCheckerTool
    backend_version: str
    checks_safety: bool
    checks_liveness: bool
    checks_fairness: bool
    requires_jvm: bool
    finite_trace_only: bool
    max_declared_steps: int
    executable_candidates: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = TLA_CAPABILITY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool", _enum(self.tool, ModelCheckerTool, "tool"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        for name in (
            "checks_safety",
            "checks_liveness",
            "checks_fairness",
            "requires_jvm",
            "finite_trace_only",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TLARunnerError(f"{name} must be a boolean")
        if (
            isinstance(self.max_declared_steps, bool)
            or not isinstance(self.max_declared_steps, int)
            or self.max_declared_steps < 1
        ):
            raise TLARunnerError("max_declared_steps must be a positive integer")
        object.__setattr__(
            self,
            "executable_candidates",
            tuple(_text(item, "executable candidate") for item in self.executable_candidates),
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(_text(item, "limitation") for item in self.limitations),
        )
        if self.schema_version != TLA_CAPABILITY_VERSION:
            raise TLARunnerError(
                f"unsupported capability schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_version": self.backend_version,
            "checks_fairness": self.checks_fairness,
            "checks_liveness": self.checks_liveness,
            "checks_safety": self.checks_safety,
            "executable_candidates": list(self.executable_candidates),
            "finite_trace_only": self.finite_trace_only,
            "limitations": list(self.limitations),
            "max_declared_steps": self.max_declared_steps,
            "requires_jvm": self.requires_jvm,
            "schema_version": self.schema_version,
            "tool": self.tool.value,
        }


TLC_CAPABILITY: Final = ModelCheckerCapability(
    tool=ModelCheckerTool.TLC,
    backend_version=TLC_BACKEND_VERSION,
    checks_safety=True,
    checks_liveness=True,
    checks_fairness=True,
    requires_jvm=True,
    finite_trace_only=False,
    max_declared_steps=10_000,
    executable_candidates=("tlc", "tlc2", "tla2tools"),
    limitations=(
        "TLC explores a finite state graph under the declared MaxSteps and domain bounds.",
        "Liveness/PROPERTY checks are available but remain bounded by fairness assumptions "
        "and the finite state space; they are not unbounded proofs.",
        "A successful TLC run never grants theorem authority.",
    ),
)

APALACHE_CAPABILITY: Final = ModelCheckerCapability(
    tool=ModelCheckerTool.APALACHE,
    backend_version=APALACHE_BACKEND_VERSION,
    checks_safety=True,
    checks_liveness=False,
    checks_fairness=False,
    requires_jvm=True,
    finite_trace_only=True,
    max_declared_steps=200,
    executable_candidates=("apalache-mc", "apalache"),
    limitations=(
        "Apalache checks safety/invariants over finite traces of length --length only.",
        "Temporal liveness and fairness operators are not checked and must not be claimed.",
        "A successful Apalache run is bounded_checked evidence, never an unbounded proof.",
    ),
)


@dataclass(frozen=True, slots=True)
class CounterexampleState:
    """One parsed state from a TLC/Apalache counterexample trace."""

    index: int
    label: str
    assignments: Mapping[str, str]
    raw: str
    schema_version: str = TLA_COUNTEREXAMPLE_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 1:
            raise TLARunnerError("counterexample state index must be a positive integer")
        object.__setattr__(self, "label", _text(self.label, "label", optional=True))
        if not isinstance(self.assignments, Mapping):
            raise TLARunnerError("assignments must be a mapping")
        normalized = {
            _text(key, "assignment key"): str(value)
            for key, value in self.assignments.items()
        }
        object.__setattr__(self, "assignments", FrozenMap(normalized).to_dict())
        object.__setattr__(self, "raw", _text(self.raw, "raw", optional=True))
        if self.schema_version != TLA_COUNTEREXAMPLE_VERSION:
            raise TLARunnerError(
                f"unsupported counterexample schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": dict(self.assignments),
            "index": self.index,
            "label": self.label,
            "raw": self.raw,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CounterexampleTrace:
    """Parsed counterexample with optional source-map replay notes."""

    states: tuple[CounterexampleState, ...] = ()
    raw: str = ""
    source: str = "stdout_stderr"
    replayed: bool = False
    replay_notes: tuple[str, ...] = ()
    schema_version: str = TLA_COUNTEREXAMPLE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "raw", _text(self.raw, "raw", optional=True))
        object.__setattr__(self, "source", _text(self.source, "source"))
        if not isinstance(self.replayed, bool):
            raise TLARunnerError("replayed must be a boolean")
        object.__setattr__(
            self,
            "replay_notes",
            tuple(_text(item, "replay note") for item in self.replay_notes),
        )
        if self.schema_version != TLA_COUNTEREXAMPLE_VERSION:
            raise TLARunnerError(
                f"unsupported counterexample schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "replay_notes": list(self.replay_notes),
            "replayed": self.replayed,
            "schema_version": self.schema_version,
            "source": self.source,
            "states": [item.to_dict() for item in self.states],
        }


@dataclass(frozen=True, slots=True)
class ModelCheckReceipt:
    """Self-contained receipt for one exact bounded checker execution."""

    tool: ModelCheckerTool
    status: ModelCheckOutcomeStatus
    artifact_digest: str
    model_digest: str
    configuration_digest: str
    configuration_text: str
    executable: str
    tool_version: str
    command: tuple[str, ...]
    checked_safety_properties: tuple[str, ...]
    checked_liveness_properties: tuple[str, ...]
    fairness_limitations: tuple[str, ...]
    capability: ModelCheckerCapability
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_ms: int
    timeout_seconds: float
    output_truncated: bool
    reason: str
    counterexample: CounterexampleTrace | None = None
    jvm_available: bool = True
    schema_version: str = TLA_MODEL_CHECK_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool", _enum(self.tool, ModelCheckerTool, "tool"))
        object.__setattr__(
            self, "status", _enum(self.status, ModelCheckOutcomeStatus, "status")
        )
        object.__setattr__(
            self, "artifact_digest", _digest(self.artifact_digest, "artifact_digest")
        )
        object.__setattr__(
            self, "model_digest", _digest(self.model_digest, "model_digest")
        )
        object.__setattr__(
            self,
            "configuration_digest",
            _digest(self.configuration_digest, "configuration_digest"),
        )
        object.__setattr__(
            self,
            "configuration_text",
            _text(self.configuration_text, "configuration_text", optional=True),
        )
        object.__setattr__(
            self, "executable", _text(self.executable, "executable", optional=True)
        )
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version", optional=True)
        )
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        object.__setattr__(
            self,
            "checked_safety_properties",
            tuple(self.checked_safety_properties),
        )
        object.__setattr__(
            self,
            "checked_liveness_properties",
            tuple(self.checked_liveness_properties),
        )
        object.__setattr__(
            self,
            "fairness_limitations",
            tuple(self.fairness_limitations),
        )
        if not isinstance(self.capability, ModelCheckerCapability):
            raise TLARunnerError("capability must be ModelCheckerCapability")
        if self.tool is ModelCheckerTool.APALACHE and self.checked_liveness_properties:
            raise TLARunnerError(
                "Apalache receipt cannot claim temporal liveness properties were checked"
            )
        if self.status is ModelCheckOutcomeStatus.UNAVAILABLE and (
            self.checked_safety_properties or self.checked_liveness_properties
        ):
            raise TLARunnerError(
                "unavailable checker cannot claim properties were checked"
            )
        if (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, int)
            or self.elapsed_ms < 0
        ):
            raise TLARunnerError("elapsed_ms must be a non-negative integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise TLARunnerError("timeout_seconds must be a positive number")
        if not isinstance(self.output_truncated, bool):
            raise TLARunnerError("output_truncated must be a boolean")
        if not isinstance(self.jvm_available, bool):
            raise TLARunnerError("jvm_available must be a boolean")
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "stdout", _text(self.stdout, "stdout", optional=True)
        )
        object.__setattr__(
            self, "stderr", _text(self.stderr, "stderr", optional=True)
        )
        if self.counterexample is not None and not isinstance(
            self.counterexample, CounterexampleTrace
        ):
            raise TLARunnerError("counterexample must be a CounterexampleTrace")
        if self.schema_version != TLA_MODEL_CHECK_RECEIPT_VERSION:
            raise TLARunnerError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )

    @property
    def bounded(self) -> bool:
        return True

    @property
    def unbounded_proof(self) -> bool:
        return False

    @property
    def receipt_id(self) -> str:
        return f"tla-model-check-receipt:{stable_digest(self.to_dict(include_id=False))}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "artifact_digest": self.artifact_digest,
            "bounded": True,
            "capability": self.capability.to_dict(),
            "checked_liveness_properties": list(self.checked_liveness_properties),
            "checked_safety_properties": list(self.checked_safety_properties),
            "command": list(self.command),
            "configuration_digest": self.configuration_digest,
            "configuration_text": self.configuration_text,
            "counterexample": (
                self.counterexample.to_dict() if self.counterexample is not None else None
            ),
            "elapsed_ms": self.elapsed_ms,
            "executable": self.executable,
            "fairness_limitations": list(self.fairness_limitations),
            "jvm_available": self.jvm_available,
            "model_digest": self.model_digest,
            "output_truncated": self.output_truncated,
            "reason": self.reason,
            "returncode": self.returncode,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "stderr": self.stderr,
            "stdout": self.stdout,
            "timeout_seconds": self.timeout_seconds,
            "tool": self.tool.value,
            "tool_version": self.tool_version,
            "unbounded_proof": False,
        }
        if include_id:
            payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class ModelCheckOutcome:
    """Normalized model-check result plus the exact receipt."""

    request_digest: str
    result: ModelCheckResult
    receipt: ModelCheckReceipt
    artifacts: GeneratedTLAArtifacts | None = None
    interface_version: str = TLA_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.result, ModelCheckResult):
            raise TLARunnerError("result must be a ModelCheckResult")
        if not isinstance(self.receipt, ModelCheckReceipt):
            raise TLARunnerError("receipt must be a ModelCheckReceipt")
        if self.artifacts is not None and not isinstance(
            self.artifacts, GeneratedTLAArtifacts
        ):
            raise TLARunnerError("artifacts must be GeneratedTLAArtifacts")
        if self.interface_version not in {
            TLA_BACKEND_VERSION,
            TLC_BACKEND_VERSION,
            APALACHE_BACKEND_VERSION,
        }:
            raise TLARunnerError(
                f"unsupported interface version: {self.interface_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": (
                self.artifacts.to_dict(include_text=False)
                if self.artifacts is not None
                else None
            ),
            "interface_version": self.interface_version,
            "receipt": self.receipt.to_dict(),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
        }


ExecutableFinder = Callable[[str], str | None]
JvmProbe = Callable[[], bool]


def parse_counterexample_trace(output: str) -> CounterexampleTrace:
    """Parse TLC/Apalache state blocks while retaining the exact raw trace."""

    text = str(output or "")
    pattern = re.compile(
        r"(?ms)^State\s+(\d+):\s*([^\n]*)\n(.*?)(?=^State\s+\d+:|\Z)"
    )
    states: list[CounterexampleState] = []
    for match in pattern.finditer(text):
        body = match.group(3).rstrip()
        assignments: dict[str, str] = {}
        for assignment in re.finditer(
            r"(?m)^\s*/?\\?\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$",
            body,
        ):
            assignments[assignment.group(1)] = assignment.group(2)
        raw = match.group(0).rstrip()
        states.append(
            CounterexampleState(
                index=int(match.group(1)),
                label=match.group(2).strip().removeprefix("<").removesuffix(">"),
                assignments=assignments,
                raw=raw,
            )
        )
    return CounterexampleTrace(states=tuple(states), raw=text)


def replay_counterexample(
    trace: CounterexampleTrace,
    source_map: Sequence[TLASourceMapEntry],
) -> CounterexampleTrace:
    """Replay a parsed counterexample against the compiler source map.

    Replay is structural: each assignment key is matched to a mapped TLA
    symbol.  Missing symbols become notes; no silent success is invented.
    """

    mapped_symbols = {entry.tla_symbol for entry in source_map}
    notes: list[str] = []
    if not trace.states:
        notes.append("counterexample contained no parseable State blocks")
    for state in trace.states:
        unknown = sorted(set(state.assignments) - mapped_symbols - {"step"})
        if unknown:
            notes.append(
                f"state {state.index}: unmapped assignment keys: {', '.join(unknown)}"
            )
        known = sorted(set(state.assignments) & mapped_symbols)
        if known:
            notes.append(
                f"state {state.index}: replayed mapped symbols: {', '.join(known)}"
            )
    return CounterexampleTrace(
        states=trace.states,
        raw=trace.raw,
        source=trace.source,
        replayed=True,
        replay_notes=tuple(notes),
    )


class TLAModelCheckerBackend:
    """Shared lifecycle for TLC and Apalache bounded model checking."""

    tool: ModelCheckerTool
    backend_id: str
    backend_version: str
    capability: ModelCheckerCapability

    def __init__(
        self,
        *,
        runner: BoundedToolRunner | None = None,
        which: ExecutableFinder = shutil.which,
        jvm_probe: JvmProbe | None = None,
        compiler: TLACompiler | None = None,
        executable: str | None = None,
    ) -> None:
        self._runner = runner or BoundedToolRunner()
        self._which = which
        self._jvm_probe = jvm_probe or (lambda: self._which("java") is not None)
        self._compiler = compiler or TLACompiler()
        self._executable = executable

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            logic_families=(
                "state_transition",
                "temporal",
                "tla_plus",
                "software_verification",
            ),
            query_kinds=(QueryKind.SATISFIABILITY,),
            deterministic=True,
        )

    def model_checker_capability(self) -> ModelCheckerCapability:
        return self.capability

    def is_available(self) -> bool:
        if self.capability.requires_jvm and not self._jvm_probe():
            return False
        return self.resolve_executable() != ""

    def resolve_executable(self) -> str:
        if self._executable:
            return str(self._executable)
        for candidate in self.capability.executable_candidates:
            path = self._which(candidate)
            if path:
                return path
        return ""

    def probe(self) -> ToolProbe:
        executable = self.resolve_executable()
        jvm_ok = self._jvm_probe() if self.capability.requires_jvm else True
        available = bool(executable) and jvm_ok
        reason = ""
        if not jvm_ok:
            reason = "JVM (java) is unavailable"
        elif not executable:
            reason = (
                f"{self.tool.value} executable unavailable; looked for "
                + ", ".join(self.capability.executable_candidates)
            )
        return ToolProbe(
            runtime=ToolRuntime.JVM,
            requested_executable=self.capability.executable_candidates[0],
            available=available,
            executable_path=executable if available else "",
            reason=reason,
        )

    def compile_and_check(
        self,
        document: object,
        *,
        request: BackendRequest | None = None,
        module_name: str = "StateModel",
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        artifacts = self._compiler.compile(document, module_name=module_name)
        return self.check(
            artifacts,
            request=request,
            cancellation=cancellation,
        )

    def check(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        request: BackendRequest | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        if not isinstance(artifacts, GeneratedTLAArtifacts):
            raise TLARunnerError("artifacts must be GeneratedTLAArtifacts")
        request_digest = (
            request.digest
            if request is not None
            else artifacts.artifact_digest
        )
        bounds = (
            request.bounds
            if request is not None
            else ExecutionBounds(
                timeout_ms=30_000,
                max_steps=artifacts.bounds.max_steps,
            )
        )
        probe = self.probe()
        if not probe.available:
            receipt = self._unavailable_receipt(
                artifacts, probe=probe, bounds=bounds
            )
            result = self._result_from_receipt(
                receipt, request=request, bounds=bounds
            )
            return ModelCheckOutcome(
                request_digest=request_digest,
                result=result,
                receipt=receipt,
                artifacts=artifacts,
                interface_version=self.backend_version,
            )

        executable = probe.executable_path
        timeout_seconds = max(0.001, bounds.timeout_ms / 1000.0)
        config_text = artifacts.configuration_for(self.tool.value)
        config_name = (
            f"{artifacts.module_name}.cfg"
            if self.tool is ModelCheckerTool.TLC
            else "apalache.cfg"
        )
        tla_name = f"{artifacts.module_name}.tla"
        # Relative paths are resolved against the private workspace cwd.  The
        # bounded runner only expands ``{workspace}`` as a whole argument or
        # argument prefix, so Apalache's ``--config=...`` form uses a relative path.
        if self.tool is ModelCheckerTool.TLC:
            argv = (
                executable,
                "-config",
                config_name,
                tla_name,
            )
        else:
            argv = (
                executable,
                "check",
                f"--config={config_name}",
                f"--length={artifacts.bounds.max_steps}",
                "--inv=Safety",
                "--no-deadlock",
                tla_name,
            )

        limits = ToolRunLimits(
            timeout_seconds=timeout_seconds,
            max_output_bytes=min(bounds.max_output_bytes, DEFAULT_MAX_OUTPUT_BYTES),
            max_input_bytes=max(
                len(artifacts.model_text.encode("utf-8")),
                len(config_text.encode("utf-8")),
                4096,
            ),
        )
        tool_request = ToolRunRequest(
            argv=argv,
            runtime=ToolRuntime.JVM,
            limits=limits,
            input_files={
                tla_name: artifacts.model_text,
                config_name: config_text,
            },
            output_paths=(
                "counterexample.tla",
                "violation.tla",
                "example.tla",
            ),
        )
        process = self._runner.run(tool_request, cancellation=cancellation)
        version = self._tool_version(executable)
        combined = "\n".join(
            part for part in (process.stdout, process.stderr) if part
        )
        status, reason = self._classify(process, combined)
        counterexample: CounterexampleTrace | None = None
        if status is ModelCheckOutcomeStatus.COUNTEREXAMPLE:
            supplemental = self._counterexample_from_outputs(process.output_files)
            trace_text = supplemental or combined
            counterexample = parse_counterexample_trace(trace_text)
            if supplemental:
                counterexample = CounterexampleTrace(
                    states=counterexample.states,
                    raw=counterexample.raw,
                    source="checker_counterexample_file",
                )
            counterexample = replay_counterexample(
                counterexample, artifacts.source_map
            )

        safety = (
            tuple(artifacts.safety_properties)
            if status
            not in {
                ModelCheckOutcomeStatus.UNAVAILABLE,
                ModelCheckOutcomeStatus.ERROR,
                ModelCheckOutcomeStatus.MALFORMED,
            }
            or status is ModelCheckOutcomeStatus.PASSED
            or status is ModelCheckOutcomeStatus.COUNTEREXAMPLE
            or status is ModelCheckOutcomeStatus.TIMED_OUT
            or status is ModelCheckOutcomeStatus.UNKNOWN
            else ()
        )
        # Only claim properties for conclusive or attempted checks with a tool.
        if status is ModelCheckOutcomeStatus.UNAVAILABLE:
            safety = ()
            liveness: tuple[str, ...] = ()
        else:
            liveness = (
                tuple(artifacts.liveness_properties)
                if self.tool is ModelCheckerTool.TLC
                else ()
            )
            if status in {
                ModelCheckOutcomeStatus.ERROR,
                ModelCheckOutcomeStatus.MALFORMED,
            }:
                # Still record the declared properties that were requested.
                pass

        receipt = ModelCheckReceipt(
            tool=self.tool,
            status=status,
            artifact_digest=artifacts.artifact_digest,
            model_digest=artifacts.model_digest,
            configuration_digest=(
                artifacts.tlc_config_digest
                if self.tool is ModelCheckerTool.TLC
                else artifacts.apalache_config_digest
            ),
            configuration_text=config_text,
            executable=executable,
            tool_version=version,
            command=tuple(str(arg) for arg in argv),
            checked_safety_properties=safety if status is not ModelCheckOutcomeStatus.UNAVAILABLE else (),
            checked_liveness_properties=liveness,
            fairness_limitations=tuple(artifacts.fairness_limitations)
            + tuple(self.capability.limitations),
            capability=self.capability,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            elapsed_ms=max(0, round(process.elapsed_seconds * 1000)),
            timeout_seconds=timeout_seconds,
            output_truncated=process.output_truncated,
            reason=reason,
            counterexample=counterexample,
            jvm_available=True,
        )
        result = self._result_from_receipt(receipt, request=request, bounds=bounds)
        return ModelCheckOutcome(
            request_digest=request_digest,
            result=result,
            receipt=receipt,
            artifacts=artifacts,
            interface_version=self.backend_version,
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        if not isinstance(request, BackendRequest):
            raise TLARunnerError("request must be a BackendRequest")
        payload = request.payload.to_dict()
        if "artifacts" in payload or "model_text" in payload:
            artifacts = self._artifacts_from_payload(payload)
            return self.check(
                artifacts, request=request, cancellation=cancellation
            )
        if "document" in payload:
            return self.compile_and_check(
                payload["document"],
                request=request,
                module_name=str(payload.get("module_name", "StateModel")),
                cancellation=cancellation,
            )
        if "source" in payload or "tla" in payload:
            source = str(payload.get("tla") or payload.get("source") or "")
            module_name = str(payload.get("module_name", "StateModel"))
            artifacts = GeneratedTLAArtifacts(
                module_name=module_name,
                model_text=source if source.endswith("\n") else source + "\n",
                tlc_config_text=str(
                    payload.get("tlc_config")
                    or "SPECIFICATION Spec\nINVARIANT Safety\n"
                ),
                apalache_config_text=str(
                    payload.get("apalache_config")
                    or "INIT Init\nNEXT Next\nINVARIANT Safety\n"
                ),
                source_map=(),
                losses=(),
                bounds=self._compiler.bounds,
                source_document_id=str(
                    payload.get("source_document_id") or request.claim_digest
                ),
                source_kind="raw_tla",
                safety_properties=("Safety",),
                liveness_properties=(),
                fairness_limitations=(
                    "Raw TLA source was supplied without a compiler source map.",
                ),
            )
            return self.check(
                artifacts, request=request, cancellation=cancellation
            )
        raise TLARunnerError(
            "request payload must include document, artifacts, or TLA source"
        )

    def _artifacts_from_payload(
        self, payload: Mapping[str, Any]
    ) -> GeneratedTLAArtifacts:
        if "artifacts" in payload and isinstance(payload["artifacts"], Mapping):
            data = dict(payload["artifacts"])
        else:
            data = dict(payload)
        model_text = str(data.get("model_text") or "")
        if not model_text:
            raise TLARunnerError("artifacts payload requires model_text")
        return GeneratedTLAArtifacts(
            module_name=str(data.get("module_name", "StateModel")),
            model_text=model_text if model_text.endswith("\n") else model_text + "\n",
            tlc_config_text=str(
                data.get("tlc_config_text")
                or "SPECIFICATION Spec\nINVARIANT Safety\n"
            ),
            apalache_config_text=str(
                data.get("apalache_config_text")
                or "INIT Init\nNEXT Next\nINVARIANT Safety\n"
            ),
            source_map=(),
            losses=(),
            bounds=self._compiler.bounds,
            source_document_id=str(data.get("source_document_id", "raw")),
            source_kind=str(data.get("source_kind", "payload")),
            safety_properties=tuple(data.get("safety_properties") or ("Safety",)),
            liveness_properties=tuple(data.get("liveness_properties") or ()),
            fairness_limitations=tuple(data.get("fairness_limitations") or ()),
        )

    def _unavailable_receipt(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        probe: ToolProbe,
        bounds: ExecutionBounds,
    ) -> ModelCheckReceipt:
        jvm_ok = self._jvm_probe() if self.capability.requires_jvm else True
        reason = probe.reason or (
            f"{self.tool.value} executable unavailable; no model check ran"
        )
        if not jvm_ok:
            reason = (
                f"JVM/tools unavailable for {self.tool.value}; no model check ran"
            )
        config_text = artifacts.configuration_for(self.tool.value)
        return ModelCheckReceipt(
            tool=self.tool,
            status=ModelCheckOutcomeStatus.UNAVAILABLE,
            artifact_digest=artifacts.artifact_digest,
            model_digest=artifacts.model_digest,
            configuration_digest=(
                artifacts.tlc_config_digest
                if self.tool is ModelCheckerTool.TLC
                else artifacts.apalache_config_digest
            ),
            configuration_text=config_text,
            executable="",
            tool_version="",
            command=(),
            checked_safety_properties=(),
            checked_liveness_properties=(),
            fairness_limitations=tuple(artifacts.fairness_limitations)
            + tuple(self.capability.limitations),
            capability=self.capability,
            returncode=None,
            stdout="",
            stderr="",
            elapsed_ms=0,
            timeout_seconds=max(0.001, bounds.timeout_ms / 1000.0),
            output_truncated=False,
            reason=reason,
            counterexample=None,
            jvm_available=jvm_ok,
        )

    def _tool_version(self, executable: str) -> str:
        if not executable:
            return ""
        if self.tool is ModelCheckerTool.TLC:
            argv = (executable, "-help")
        else:
            argv = (executable, "version")
        request = ToolRunRequest(
            argv=argv,
            runtime=ToolRuntime.JVM,
            limits=ToolRunLimits(
                timeout_seconds=DEFAULT_VERSION_TIMEOUT_SECONDS,
                max_output_bytes=64 * 1024,
            ),
        )
        try:
            result = self._runner.run(request)
        except Exception as exc:  # fail closed
            return f"unavailable: {type(exc).__name__}: {exc}"
        if result.unavailable or result.timed_out:
            return "unavailable"
        text = (result.stdout or result.stderr).strip()
        return text[:512] if text else "unknown"

    def _classify(
        self, process: ToolRunResult, combined: str
    ) -> tuple[ModelCheckOutcomeStatus, str]:
        lower = combined.lower()
        if process.unavailable:
            return (
                ModelCheckOutcomeStatus.UNAVAILABLE,
                process.error or f"{self.tool.value} executable unavailable",
            )
        if process.timed_out:
            return (
                ModelCheckOutcomeStatus.TIMED_OUT,
                "bounded model check timed out before completing exploration",
            )
        if process.cancelled:
            return (
                ModelCheckOutcomeStatus.ERROR,
                "bounded model check was cancelled",
            )
        if process.error and process.returncode is None and not process.stdout:
            return (
                ModelCheckOutcomeStatus.ERROR,
                f"bounded model checker failed: {process.error}",
            )
        if any(marker in lower for marker in _COUNTEREXAMPLE_MARKERS):
            return (
                ModelCheckOutcomeStatus.COUNTEREXAMPLE,
                "bounded model checker reported a counterexample",
            )
        if process.output_truncated or process.resource_exhausted:
            return (
                ModelCheckOutcomeStatus.UNKNOWN,
                "bounded checker output was truncated or resource-exhausted; "
                "success cannot be established",
            )
        success_markers = (
            _TLC_SUCCESS_MARKERS
            if self.tool is ModelCheckerTool.TLC
            else _APALACHE_SUCCESS_MARKERS
        )
        if process.returncode == 0 and any(
            marker in lower for marker in success_markers
        ):
            return (
                ModelCheckOutcomeStatus.PASSED,
                "bounded model check passed within the explicitly recorded explored bounds",
            )
        if process.returncode not in (0, None):
            return (
                ModelCheckOutcomeStatus.ERROR,
                f"bounded model checker exited with code {process.returncode}",
            )
        if not combined.strip():
            return (
                ModelCheckOutcomeStatus.MALFORMED,
                "checker produced no reviewed success or counterexample markers",
            )
        return (
            ModelCheckOutcomeStatus.UNKNOWN,
            "checker output did not contain a reviewed success or counterexample marker",
        )

    @staticmethod
    def _counterexample_from_outputs(outputs: Mapping[str, bytes]) -> str:
        for name in sorted(outputs):
            lowered = name.lower()
            if any(
                token in lowered
                for token in ("counterexample", "violation", "example")
            ):
                try:
                    return outputs[name].decode("utf-8", errors="replace")
                except Exception:
                    continue
        return ""

    def _result_from_receipt(
        self,
        receipt: ModelCheckReceipt,
        *,
        request: BackendRequest | None,
        bounds: ExecutionBounds,
    ) -> ModelCheckResult:
        status_map = {
            ModelCheckOutcomeStatus.PASSED: ResultStatus.SATISFIED,
            ModelCheckOutcomeStatus.COUNTEREXAMPLE: ResultStatus.VIOLATED,
            ModelCheckOutcomeStatus.TIMED_OUT: ResultStatus.TIMEOUT,
            ModelCheckOutcomeStatus.UNAVAILABLE: ResultStatus.UNAVAILABLE,
            ModelCheckOutcomeStatus.ERROR: ResultStatus.ERROR,
            ModelCheckOutcomeStatus.MALFORMED: ResultStatus.MALFORMED,
            ModelCheckOutcomeStatus.UNKNOWN: ResultStatus.UNKNOWN,
        }
        status = status_map[receipt.status]
        witness: dict[str, Any] = {
            "bounded": True,
            "unbounded_proof": False,
            "tool": receipt.tool.value,
            "capability": receipt.capability.to_dict(),
            "checked_safety_properties": list(receipt.checked_safety_properties),
            "checked_liveness_properties": list(receipt.checked_liveness_properties),
            "fairness_limitations": list(receipt.fairness_limitations),
            "artifact_digest": receipt.artifact_digest,
            "model_digest": receipt.model_digest,
            "configuration_digest": receipt.configuration_digest,
            "receipt_id": receipt.receipt_id,
        }
        if receipt.counterexample is not None:
            witness["counterexample"] = receipt.counterexample.to_dict()
        result_id = (
            f"result:{self.backend_id}:"
            f"{(request.digest if request is not None else receipt.artifact_digest)[:24]}"
        )
        return ModelCheckResult(
            result_id=result_id,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            authority=ResultAuthority.MODEL_CHECK,
            status=status,
            assumptions=(
                tuple(request.assumption_ids)
                if request is not None
                else ("assumption:bounded-model-check",)
            ),
            bounds=bounds,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            usage=ResourceUsage(
                elapsed_ms=receipt.elapsed_ms,
                output_bytes=len(receipt.stdout.encode("utf-8"))
                + len(receipt.stderr.encode("utf-8")),
            ),
            witness=FrozenMap(witness),
            diagnostics=tuple(
                item
                for item in (
                    receipt.reason,
                    *(
                        receipt.counterexample.replay_notes
                        if receipt.counterexample is not None
                        else ()
                    ),
                )
                if item
            ),
            reason=receipt.reason,
            metadata=FrozenMap(
                {
                    "jvm_available": receipt.jvm_available,
                    "tool_version": receipt.tool_version,
                    "executable": receipt.executable,
                }
            ),
        )


class TLCBackend(TLAModelCheckerBackend):
    """Bounded TLC model-check backend (``TLCBackend@1``)."""

    tool = ModelCheckerTool.TLC
    backend_id = "tlc"
    backend_version = TLC_BACKEND_VERSION
    capability = TLC_CAPABILITY


class ApalacheBackend(TLAModelCheckerBackend):
    """Bounded Apalache model-check backend (``ApalacheBackend@1``)."""

    tool = ModelCheckerTool.APALACHE
    backend_id = "apalache"
    backend_version = APALACHE_BACKEND_VERSION
    capability = APALACHE_CAPABILITY


class TLABackend:
    """Facade over TLA translation plus optional TLC/Apalache execution.

    Implements the ``TLABackend@1`` surface used by capability matrices while
    keeping the compiler and the two checkers independently addressable.
    """

    interface_version: Final = TLA_BACKEND_VERSION

    def __init__(
        self,
        *,
        compiler: TLACompiler | None = None,
        tlc: TLCBackend | None = None,
        apalache: ApalacheBackend | None = None,
        runner: BoundedToolRunner | None = None,
        which: ExecutableFinder = shutil.which,
        jvm_probe: JvmProbe | None = None,
    ) -> None:
        self.compiler = compiler or TLACompiler()
        shared_runner = runner
        self.tlc = tlc or TLCBackend(
            runner=shared_runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self.compiler,
        )
        self.apalache = apalache or ApalacheBackend(
            runner=shared_runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self.compiler,
        )

    def compile(self, document: object, **kwargs: Any) -> GeneratedTLAArtifacts:
        return self.compiler.compile(document, **kwargs)

    def check(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        tool: ModelCheckerTool | str = ModelCheckerTool.TLC,
        request: BackendRequest | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        selected = _enum(tool, ModelCheckerTool, "tool")
        backend = self.tlc if selected is ModelCheckerTool.TLC else self.apalache
        return backend.check(
            artifacts, request=request, cancellation=cancellation
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "interface_version": self.interface_version,
            "compiler": TLA_BACKEND_VERSION,
            "tlc": self.tlc.model_checker_capability().to_dict(),
            "apalache": self.apalache.model_checker_capability().to_dict(),
        }


__all__ = [
    "APALACHE_BACKEND_VERSION",
    "APALACHE_CAPABILITY",
    "ApalacheBackend",
    "CounterexampleState",
    "CounterexampleTrace",
    "ModelCheckOutcome",
    "ModelCheckOutcomeStatus",
    "ModelCheckReceipt",
    "ModelCheckerCapability",
    "ModelCheckerTool",
    "TLC_BACKEND_VERSION",
    "TLC_CAPABILITY",
    "TLCBackend",
    "TLABackend",
    "TLAModelCheckerBackend",
    "TLARunnerError",
    "parse_counterexample_trace",
    "replay_counterexample",
]
