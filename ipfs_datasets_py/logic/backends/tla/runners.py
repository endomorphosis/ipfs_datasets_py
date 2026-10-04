"""Bounded TLC and Apalache runners for generated TLA+ artifacts.

``TLCBackend@1`` and ``ApalacheBackend@1`` are distinct model-check surfaces:

* TLC may check temporal liveness/PROPERTY clauses under fairness assumptions.
* Apalache is a finite-trace symbolic checker: safety/invariants only, with an
  explicit length bound and no liveness claims.

Both runners:

* require an explicit JVM-hosted executable (or an injected probe/runner);
* return ``unavailable`` when the tool or JVM is absent — never a silent pass;
* parse counterexamples and validate structural source-symbol mapping;
* emit :class:`ModelCheckResult` with bounded authority only.

The shared :class:`TLAModelCheckerBackend` base implements the common lifecycle
while keeping capability and bound disclosures tool-specific.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
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
    _is_cancelled,
)
from ..results import (
    ModelCheckResult,
    ResultAuthority,
    ResultStatus,
)
from ..resource_admission import ResourceAdmittedToolRunner
from ..smt.operation_budget import (
    _Signals,
    current_proof_operation,
    proof_operation_scope,
    validate_operation_timeout_ms,
)
from .compiler import (
    GeneratedTLAArtifacts,
    TLA_BACKEND_VERSION,
    TLACompiler,
    TLACompilerError,
    TLASourceMapEntry,
    _decode_tla_artifact_payload,
)

TLC_BACKEND_VERSION: Final = "TLCBackend@1"
APALACHE_BACKEND_VERSION: Final = "ApalacheBackend@1"
TLA_MODEL_CHECK_RECEIPT_VERSION: Final = "tla-model-check-receipt/v1"
TLA_COUNTEREXAMPLE_VERSION: Final = "tla-counterexample/v1"
TLA_CAPABILITY_VERSION: Final = "tla-model-checker-capability/v1"

DEFAULT_VERSION_TIMEOUT_SECONDS: Final = 3.0
DEFAULT_MAX_OUTPUT_BYTES: Final = 2 * 1024 * 1024
JVM_ADDRESS_SPACE_FLOOR_BYTES: Final = 4 * 1024 * 1024 * 1024
_APALACHE_MIN_RESIDENT_BYTES: Final = 256 * 1024 * 1024
_APALACHE_MAX_FILE_BYTES: Final = 64 * 1024 * 1024
_APALACHE_MAX_WORKSPACE_BYTES: Final = 128 * 1024 * 1024
_APALACHE_CHILD_PROCESS_SLOTS: Final = 3
_APALACHE_RUNTIME_CONFIG_NAME: Final = "apalache-runtime.json"
_APALACHE_RUN_DIRECTORY: Final = "apalache-run"

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

_MODEL_CHECK_CONTROL = ContextVar("tla_model_check_control", default=None)


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


class _ModelCheckControl:
    """Per-call cooperative stop state; native flags also latch a failed phase."""

    def __init__(self, started: float, timeout_seconds: float, cancellation) -> None:
        self.started = started
        self.deadline = started + timeout_seconds
        self.cancellation = cancellation
        self.operation = current_proof_operation()
        if self.operation is not None:
            self.deadline = min(self.deadline, self.operation.deadline)
        self.failure = None

    def reject(self, status: ModelCheckOutcomeStatus, reason: str):
        if self.failure is None:
            self.failure = (status, reason)
        return self.failure

    def observe(self):
        if self.operation is not None:
            self.operation.checkpoint("TLA model-check boundary")
        if self.failure is None:
            if _is_cancelled(self.cancellation):
                self.reject(ModelCheckOutcomeStatus.ERROR, "bounded model check was cancelled")
            elif time.monotonic() >= self.deadline:
                self.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check deadline expired")
        return self.failure


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


def _production_executable_finder(name: str) -> str | None:
    """Resolve managed prover launchers before ambient PATH."""

    from ...external_provers.lazy_installer import find_executable

    return find_executable(name)


_TRACE_PARSE_FAILURE: Final = "counterexample parse incomplete: "
_TRACE_STRUCTURAL_SCOPE: Final = (
    "structural source-symbol mapping only; transitions and invariants were not evaluated"
)
_TRACE_MAX_STATES: Final = 512
_TRACE_MAX_CHARACTERS: Final = 262_144
_TRACE_MAX_NESTING: Final = 128
_TRACE_TOKEN = re.compile(
    r'"(?:\\[^\n]|[^"\\\n])*"|/\\|<<|>>|\|->|:>|@@|'
    r'-?\d+|[A-Za-z_][A-Za-z0-9_]*|[=,{}\[\]()]'
)


def _mask_trace_comments(text: str) -> tuple[str, tuple[str, ...]]:
    """Hide comments without shifting offsets or inspecting strings as code."""
    masked = list(text)
    position = depth = 0
    quoted = False
    errors: list[str] = []
    while position < len(text):
        if depth:
            if text.startswith("(*", position):
                depth += 1
                if depth == _TRACE_MAX_NESTING + 1:
                    errors.append(_TRACE_PARSE_FAILURE + "comment nesting exceeds supported limit")
                width = 2
            elif text.startswith("*)", position):
                depth -= 1
                width = 2
            else:
                width = 1
            for index in range(position, position + width):
                if masked[index] not in "\r\n":
                    masked[index] = " "
            position += width
        elif quoted:
            if text[position] == "\\":
                position += 2
            else:
                if text[position] == '"':
                    quoted = False
                position += 1
        elif text[position] == '"':
            quoted = True
            position += 1
        elif text.startswith("(*", position):
            depth = 1
            masked[position:position + 2] = "  "
            position += 2
        elif text.startswith("\\*", position):
            end = text.find("\n", position)
            end = len(text) if end < 0 else end
            masked[position:end] = " " * (end - position)
            position = end
        else:
            position += 1
    if depth:
        errors.append(_TRACE_PARSE_FAILURE + "unterminated block comment")
    if quoted:
        errors.append(_TRACE_PARSE_FAILURE + "unterminated quoted string")
    return "".join(masked), tuple(errors)


def _trace_assignments(body: str, original: str | None = None) -> tuple[dict[str, str], str]:
    """Read a bounded literal-value subset, not arbitrary TLA expressions.

    Strings, integers/model values, sets, tuples, records and finite function
    values may span lines. Unsupported syntax is retained in raw evidence and
    prevents structural replay; it is never evaluated as TLA or Python.
    """
    tokens: list[tuple[str, int, int]] = []
    offset = 0
    while offset < len(body):
        if body[offset].isspace():
            offset += 1
            continue
        match = _TRACE_TOKEN.match(body, offset)
        if match is None:
            return {}, "unsupported or unfinished assignment syntax"
        tokens.append((match.group(), offset, match.end()))
        offset = match.end()
    position = 0
    assignments: dict[str, str] = {}

    def peek() -> str:
        return tokens[position][0] if position < len(tokens) else ""

    def take(expected: str | None = None) -> str:
        nonlocal position
        token = peek()
        if not token or (expected is not None and token != expected):
            raise ValueError("missing value or unmatched value delimiter")
        position += 1
        return token

    def value(depth: int = 0) -> None:
        if depth > _TRACE_MAX_NESTING:
            raise ValueError("assignment nesting exceeds supported limit")
        token = take()
        if token in {"{", "<<", "["}:
            closing = {"{": "}", "<<": ">>", "[": "]"}[token]
            if peek() == closing:
                take(closing)
                return
            while True:
                if token == "[":
                    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*|"(?:\\.|[^"\\])*"', take()):
                        raise ValueError("unsupported record field")
                    take("|->")
                value(depth + 1)
                if peek() != ",":
                    break
                take(",")
            take(closing)
        elif token == "(":
            value(depth + 1)
            if peek() == ":>":
                take(":>")
                value(depth + 1)
                while peek() == "@@":
                    take("@@")
                    value(depth + 1)
                    take(":>")
                    value(depth + 1)
            take(")")
        elif not re.fullmatch(r'-?\d+|[A-Za-z_][A-Za-z0-9_]*|"(?:\\[^\n]|[^"\\\n])*"', token):
            raise ValueError("unsupported assignment value")

    try:
        while position < len(tokens):
            if peek() == "/\\":
                take()
            elif assignments and "\n" not in body[tokens[position - 1][2]:tokens[position][1]]:
                raise ValueError("missing assignment separator")
            name = take()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("invalid assignment name")
            take("=")
            if position == len(tokens):
                raise ValueError("assignment has no value")
            first = tokens[position][1]
            value()
            if name in assignments:
                raise ValueError(f"duplicate assignment: {name}")
            assignments[name] = (body if original is None else original)[first:tokens[position - 1][2]]
        if not assignments:
            raise ValueError("state has no assignments")
    except ValueError as error:
        return assignments, str(error)
    return assignments, ""


def parse_counterexample_trace(output: str) -> CounterexampleTrace:
    """Parse conservative TLC blocks and Apalache StateN definitions.

    Apalache's zero-based labels remain in ``label``/``raw``; positive ordinal
    indexes satisfy the existing wire schema. Parse failures are explicit notes
    and forbid replay, even when a valid prefix can still be displayed.
    """
    text = str(output or "")
    notes: list[str] = []
    if len(text) > _TRACE_MAX_CHARACTERS:
        return CounterexampleTrace(raw=text, replay_notes=(
            _TRACE_PARSE_FAILURE + "trace exceeds supported character limit",))
    header = re.compile(r"(?m)^State(?:(?:[ \t]+(?P<tlc>\d+):[ \t]*(?P<label>[^\n]*))|"
                        r"(?P<apalache>\d+)[ \t]*==(?!=)[ \t]*(?P<inline>[^\n]*))")
    masked, comment_errors = _mask_trace_comments(text)
    notes.extend(comment_errors)
    matches = list(header.finditer(masked))
    module_headers = list(re.finditer(r"(?m)^-{4,}[ \t]+MODULE[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]+-{4,}[ \t]*$", masked))
    module_markers = list(re.finditer(r"(?m)^-{4,}[ \t]+MODULE\b", masked))
    if module_markers:
        footers = list(re.finditer(r"(?m)^={4,}[ \t]*$", masked))
        if (len(module_headers) != 1 or len(module_markers) != 1 or len(footers) != 1
                or footers[0].start() < module_headers[0].end()):
            notes.append(_TRACE_PARSE_FAILURE + "module wrapper is malformed or missing its terminator")
        elif any(not module_headers[0].end() <= item.start() < footers[0].start() for item in matches):
            notes.append(_TRACE_PARSE_FAILURE + "state definition lies outside the module wrapper")
    if len(matches) > _TRACE_MAX_STATES:
        return CounterexampleTrace(raw=text, replay_notes=(
            _TRACE_PARSE_FAILURE + "trace exceeds supported state limit",))
    # A malformed State header must not disappear between otherwise valid ones.
    starts = {match.start() for match in matches}
    for candidate in re.finditer(r"(?m)^State[^\n]*(?::|==|=)[^\n]*", masked):
        if candidate.start() not in starts:
            notes.append(_TRACE_PARSE_FAILURE + "unrecognized State header")
            break
    styles: set[str] = set()
    states: list[CounterexampleState] = []
    for ordinal, match in enumerate(matches, 1):
        apalache = match.group("apalache") is not None
        style = "apalache" if apalache else "tlc"
        styles.add(style)
        digits = match.group(style)
        if len(digits) > 9:
            notes.append(_TRACE_PARSE_FAILURE + "state number exceeds supported range")
            continue
        number = int(digits)
        expected = ordinal - 1 if apalache else ordinal
        if number != expected:
            notes.append(_TRACE_PARSE_FAILURE + "state numbering is duplicate, missing or reordered")
        stop = matches[ordinal].start() if ordinal < len(matches) else len(text)
        body_start = match.start("inline") if apalache else match.end()
        body = masked[body_start:stop]
        # Apalache metadata and subsequent operators are not state assignments.
        # TLC's known completion summaries likewise terminate the last state.
        boundary = (r"(?m)^[ \t]*(?:={4,}|[A-Za-z_][A-Za-z0-9_]*[ \t]*==)"
                    if apalache else
                    r"(?m)^(?:Finished in |\d+ states generated|The depth of |"
                    r"The average outdegree |Progress\(|Model checking completed\.|"
                    r"Error: |Back to state |State \d+: Stuttering)")
        ending = re.search(boundary, body)
        if ending is not None:
            stop = body_start + ending.start()
            body = masked[body_start:stop]
        assignments, failure = _trace_assignments(body, text[body_start:stop])
        if failure:
            notes.append(_TRACE_PARSE_FAILURE + f"state {ordinal}: {failure}")
        if number < 1 and not apalache:
            notes.append(_TRACE_PARSE_FAILURE + "TLC state index must be positive")
            continue
        states.append(CounterexampleState(
            index=ordinal if apalache else number,
            label=f"State{digits}" if apalache else text[match.start("label"):match.end("label")].strip().removeprefix("<").removesuffix(">"),
            assignments=assignments, raw=text[match.start():stop].rstrip(),
        ))
    if len(styles) > 1:
        notes.append(_TRACE_PARSE_FAILURE + "mixed TLC and Apalache state formats")
    if not states:
        notes.append(_TRACE_PARSE_FAILURE + "counterexample contained no parseable State blocks")
    return CounterexampleTrace(states=tuple(states), raw=text,
        replay_notes=tuple(dict.fromkeys(notes))[:64])


def _counterexample_structure_errors(trace: CounterexampleTrace) -> tuple[str, ...]:
    """Revalidate raw/state consistency, including caller-supplied legacy flags."""
    parsed = parse_counterexample_trace(trace.raw)
    errors = list(parsed.replay_notes)
    if not trace.states or len(trace.states) > _TRACE_MAX_STATES:
        errors.append("counterexample requires complete nonempty states within supported limits")
    elif any(not isinstance(state, CounterexampleState) for state in trace.states):
        errors.append("counterexample contains an invalid state record")
    elif [state.to_dict() for state in trace.states] != [state.to_dict() for state in parsed.states]:
        errors.append("counterexample states do not match the retained raw trace")
    errors.extend(note for note in trace.replay_notes if note.startswith(_TRACE_PARSE_FAILURE))
    return tuple(dict.fromkeys(errors))


def replay_counterexample(
    trace: CounterexampleTrace,
    source_map: Sequence[TLASourceMapEntry],
) -> CounterexampleTrace:
    """Validate complete structural source-symbol mapping, not TLA semantics.

    The legacy ``replayed`` flag means assignments map to source variables. It
    does not evaluate Init/Next, invariants, fairness or any transition relation.
    """
    notes = list(_counterexample_structure_errors(trace))
    valid = not notes
    variables: dict[str, set[str]] = {}
    for entry in source_map:
        if entry.role == "variable":
            variables.setdefault(entry.tla_symbol, set()).add(entry.source_id)
    expected = set(variables) - {"step"}
    if not expected:
        valid = False
        notes.append("counterexample has no mapped source variables")
    for state in trace.states:
        if not isinstance(state, CounterexampleState):
            valid = False
            continue
        keys = set(state.assignments)
        unknown = sorted(keys - set(variables) - {"step"})
        missing = sorted(expected - keys)
        known = sorted(keys & set(variables))
        if unknown or missing or not known or not keys:
            valid = False
            if unknown:
                notes.append(f"state {state.index}: unmapped assignment keys: {', '.join(unknown)}")
            if missing:
                notes.append(f"state {state.index}: missing mapped assignment keys: {', '.join(missing)}")
            if not known:
                notes.append(f"state {state.index}: no mapped source assignments")
        if known and len(trace.states) <= 48:
            notes.append(f"state {state.index}: replayed mapped symbols: {', '.join(known)}")
            sources = sorted({source for name in known for source in variables[name]})
            notes.append(f"state {state.index}: source IDs: {', '.join(sources)}")
    if len(trace.states) > 48:
        notes.append(f"source-symbol mapping examined all {len(trace.states)} states; per-state success notes omitted")
    notes.append(_TRACE_STRUCTURAL_SCOPE)
    # Bound descriptive detail separately from validation. Every state/map was
    # checked above; abbreviated human notes neither certify nor invalidate it.
    if len(notes) > 128 or any(len(note) > 512 for note in notes):
        notes = [note if len(note) <= 512 else note[:480] + " ... [detail abbreviated]"
                 for note in notes[:126]] + [
            "structural replay note detail abbreviated; validation covered all states and mappings",
            _TRACE_STRUCTURAL_SCOPE]
    return CounterexampleTrace(states=trace.states, raw=trace.raw,
        source=trace.source, replayed=valid, replay_notes=tuple(dict.fromkeys(notes)))


class TLAModelCheckerBackend:
    """Shared lifecycle for TLC and Apalache bounded model checking.

    Check and version subprocesses share a wall deadline and cancellation signal.
    The requested memory bound guards sampled Linux process-tree RSS; a separate
    finite address-space allowance accommodates JVM reservations. Managed
    Apalache runs configure the reviewed launcher heap and in-process Z3 profile,
    reserving three process slots for launcher helpers. A requested RSS budget
    below 256 MiB is refused; larger budgets may still be insufficient for a
    model. Plain injected runners retain their caller-owned profile. Arbitrary
    custom launchers remain caller-trusted; admission is not a hard thread or
    process-count limit. Constructor JVM validation
    has a separate support-probe budget unless an enclosing proof operation
    supplies a tighter deadline. Compilation and optional installation are
    cooperative Python work, checked at their boundaries, not preempted.
    Resource-owning adapters can
    inject a validated ``jvm_probe`` and disable ``lazy_install`` to keep setup
    outside their execution lease. Final publication rejects late conclusions.
    """

    tool: ModelCheckerTool
    backend_id: str
    backend_version: str
    capability: ModelCheckerCapability

    def __init__(
        self,
        *,
        runner: BoundedToolRunner | None = None,
        which: ExecutableFinder | None = None,
        jvm_probe: JvmProbe | None = None,
        compiler: TLACompiler | None = None,
        executable: str | None = None,
        java_executable: str | None = None,
        lazy_install: bool = True,
    ) -> None:
        self._runner = runner if runner is not None else (
            ResourceAdmittedToolRunner(child_process_slots=(
                _APALACHE_CHILD_PROCESS_SLOTS if self.tool is ModelCheckerTool.APALACHE else 1))
        )
        self._managed_resource_runner = isinstance(self._runner, ResourceAdmittedToolRunner)
        self._managed_apalache_runner = (
            self.tool is ModelCheckerTool.APALACHE and self._managed_resource_runner
        )
        if (self._managed_apalache_runner
                and self._runner.child_process_slots < _APALACHE_CHILD_PROCESS_SLOTS):
            raise TLARunnerError("managed Apalache runner requires at least 3 child_process_slots")
        self._which = which or _production_executable_finder
        self._lazy_install = bool(lazy_install and which is None)
        self._compiler = compiler or TLACompiler()
        self._executable = executable
        self._java_executable = ""
        if java_executable is not None or jvm_probe is None:
            from ..installers.state_model import (
                APALACHE_MIN_JAVA_MAJOR,
                TLC_MIN_JAVA_MAJOR,
                probe_java_runtime,
            )

            minimum = (
                TLC_MIN_JAVA_MAJOR
                if self.tool is ModelCheckerTool.TLC
                else APALACHE_MIN_JAVA_MAJOR
            )
            runtime = probe_java_runtime(
                java_executable=java_executable,
                minimum_major=minimum,
            )
            self._java_executable = runtime.executable or ""
            self._jvm_probe = lambda: runtime.usable
        else:
            # Explicit dependency injection remains available for deterministic
            # runner tests; production construction always uses the validated
            # branch above.
            self._jvm_probe = jvm_probe

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

    def resolve_executable(self, *, allow_install: bool = False) -> str:
        if self._executable:
            return str(self._executable)
        for candidate in self.capability.executable_candidates:
            path = self._which(candidate)
            if path:
                return path
        if allow_install and self._lazy_install and self._jvm_probe():
            from ...external_provers.lazy_installer import ensure_prover_executable

            installed = ensure_prover_executable(
                self.tool.value,
                reason=f"{self.backend_id} model-check execution requested",
                java_executable=self._java_executable or None,
            )
            if installed:
                return installed
        return ""

    def _probe(self, *, allow_install: bool) -> ToolProbe:
        executable = self.resolve_executable(allow_install=allow_install)
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

    def probe(self) -> ToolProbe:
        """Read-only capability probe; installation is reserved for execution."""

        return self._probe(allow_install=False)

    def _java_environment(self) -> dict[str, str]:
        if not self._java_executable:
            return {}
        java_dir = str(Path(self._java_executable).resolve().parent)
        return {
            "PATH": os.pathsep.join(
                part for part in (java_dir, os.environ.get("PATH", "")) if part
            )
        }

    def _execution_environment(self, bounds: ExecutionBounds) -> dict[str, str]:
        environment = self._java_environment()
        if not self._managed_apalache_runner:
            return environment
        # The reviewed launcher otherwise selects a 4-GiB heap and G1 GC.
        # Leave half the requested RSS budget for native Z3 and JVM overhead;
        # this profile is not a promise that every model fits that budget.
        heap_mib = bounds.max_memory_bytes // (2 * 1024 * 1024)
        environment["JVM_ARGS"] = " ".join((
            "-Xms16m", f"-Xmx{heap_mib}m", "-Xss1m",
            f"-XX:ActiveProcessorCount={self._runner.cpu_slots}",
            "-XX:MaxMetaspaceSize=128m", "-XX:ReservedCodeCacheSize=64m",
            "-XX:-UsePerfData", "-Duser.home=.",
        ))
        environment["JVM_GC_ARGS"] = "-XX:+UseSerialGC"
        # Default runners already omit these variables. An explicitly admitted
        # runner can carry a custom base environment, whose JVM overrides must
        # not widen the owned heap/worker profile. Do not mutate that runner.
        for name in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
            if name in self._runner._base_environment:
                environment[name] = ""
        return environment

    def _profile_refusal(self, bounds: ExecutionBounds) -> str | None:
        if self._managed_apalache_runner and bounds.max_memory_bytes < _APALACHE_MIN_RESIDENT_BYTES:
            return "managed Apalache requires a requested RSS budget of at least 256 MiB; budget was not increased"
        return None

    def _profile_limits(self, limits: ToolRunLimits) -> ToolRunLimits:
        if not self._managed_apalache_runner:
            return limits
        # Packaged Z3 JNI extracts a roughly 31-MiB shared library into the
        # private Java temporary directory. Keep extraction and model outputs
        # bounded there rather than disabling the file/workspace guards.
        return replace(limits, max_file_bytes=_APALACHE_MAX_FILE_BYTES,
            max_workspace_bytes=_APALACHE_MAX_WORKSPACE_BYTES)

    def compile_and_check(
        self,
        document: object,
        *,
        request: BackendRequest | None = None,
        module_name: str = "StateModel",
        cancellation: CancellationSignal | None = None,
        operation_timeout_ms: int | None = None,
    ) -> ModelCheckOutcome:
        """Compile and check under one cooperative aggregate operation budget."""
        validate_operation_timeout_ms(operation_timeout_ms)
        timeout = operation_timeout_ms if operation_timeout_ms is not None else (
            request.bounds.timeout_ms if request is not None else 30_000)
        with proof_operation_scope(timeout_ms=timeout, cancellation=cancellation) as operation:
            artifacts = self._compiler.compile(document, module_name=module_name)
            operation.checkpoint("after TLA compilation")
            return self.check(artifacts, request=request, cancellation=cancellation)

    def check(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        request: BackendRequest | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        if not isinstance(artifacts, GeneratedTLAArtifacts):
            raise TLARunnerError("artifacts must be GeneratedTLAArtifacts")
        started = time.monotonic()
        bounds = (request.bounds if request is not None else ExecutionBounds(
            timeout_ms=30_000, max_steps=artifacts.bounds.max_steps))
        control = _ModelCheckControl(started, bounds.timeout_ms / 1000.0, cancellation)
        # Preserve standalone injected-runner signal identity. An enclosing
        # operation additionally supplies a latched, bool-only native signal.
        if control.operation is not None:
            cancellation = _Signals(control.operation, cancellation)
        token = _MODEL_CHECK_CONTROL.set(control)
        try:
            outcome = self._check(artifacts, request=request, cancellation=cancellation)
            failure = control.observe()
            if failure is None:
                return outcome
            # Parsing, source-map replay and construction are cooperative Python
            # work. Their late result must not publish a conclusion or witness.
            status, reason = failure
            receipt = replace(outcome.receipt, status=status, reason=reason,
                counterexample=None,
                checked_safety_properties=(
                    () if status is ModelCheckOutcomeStatus.UNAVAILABLE else outcome.receipt.checked_safety_properties),
                checked_liveness_properties=(
                    () if status is ModelCheckOutcomeStatus.UNAVAILABLE else outcome.receipt.checked_liveness_properties),
                elapsed_ms=max(0, round((time.monotonic() - started) * 1000)))
            return ModelCheckOutcome(request_digest=outcome.request_digest,
                result=self._result_from_receipt(receipt, request=request, bounds=bounds),
                receipt=receipt, artifacts=outcome.artifacts, interface_version=outcome.interface_version)
        finally:
            _MODEL_CHECK_CONTROL.reset(token)

    def _check(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        request: BackendRequest | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> ModelCheckOutcome:
        control = _MODEL_CHECK_CONTROL.get()
        if control is None:
            raise TLARunnerError("model-check execution requires its local lifecycle control")
        started = control.started
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
        timeout_seconds = bounds.timeout_ms / 1000.0
        deadline = control.deadline

        def interrupted() -> ModelCheckOutcome | None:
            failure = control.observe()
            if failure is None:
                return None
            status, reason = failure
            receipt = replace(
                self._unavailable_receipt(
                    artifacts,
                    probe=ToolProbe(
                        runtime=ToolRuntime.JVM,
                        requested_executable=self.capability.executable_candidates[0],
                        available=False,
                        reason=reason,
                    ),
                    bounds=bounds,
                    jvm_available=False,
                ),
                status=status,
                reason=reason,
                elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
            )
            return ModelCheckOutcome(
                request_digest=request_digest,
                result=self._result_from_receipt(receipt, request=request, bounds=bounds),
                receipt=receipt,
                artifacts=artifacts,
                interface_version=self.backend_version,
            )

        stopped = interrupted()
        if stopped is not None:
            return stopped
        refusal = self._profile_refusal(bounds)
        if refusal is not None:
            control.reject(ModelCheckOutcomeStatus.UNKNOWN, refusal)
        stopped = interrupted()
        if stopped is not None:
            return stopped
        probe = self._probe(allow_install=True)
        stopped = interrupted()
        if stopped is not None:
            return stopped
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
        config_text = artifacts.configuration_for(self.tool.value)
        config_name = (
            f"{artifacts.module_name}.cfg"
            if self.tool is ModelCheckerTool.TLC
            else "apalache.cfg"
        )
        tla_name = f"{artifacts.module_name}.tla"
        input_files = {tla_name: artifacts.model_text, config_name: config_text}
        output_paths = ("counterexample.tla", "violation.tla", "example.tla")
        if self._managed_apalache_runner:
            # Apalache's application configuration is separate from the TLA
            # model configuration. An owned empty file blocks ancestor config
            # discovery; private user.home also excludes the host user config.
            input_files[_APALACHE_RUNTIME_CONFIG_NAME] = "{}\n"
            output_paths = tuple(f"{_APALACHE_RUN_DIRECTORY}/{name}" for name in output_paths)
        # Relative paths are resolved against the private workspace cwd.  The
        # bounded runner only expands ``{workspace}`` as a whole argument or
        # argument prefix, so Apalache's ``--config=...`` form uses a relative path.
        if self.tool is ModelCheckerTool.TLC:
            argv = (
                executable,
                *(("-workers", str(self._runner.cpu_slots)) if self._managed_resource_runner else ()),
                "-config",
                config_name,
                tla_name,
            )
        else:
            argv = (
                executable,
                "check",
                *((f"--config-file={_APALACHE_RUNTIME_CONFIG_NAME}",
                   f"--run-dir={_APALACHE_RUN_DIRECTORY}",
                   "--out-dir=apalache-out", "--smt-solver=z3")
                  if self._managed_apalache_runner else ()),
                f"--config={config_name}",
                f"--length={artifacts.bounds.max_steps}",
                "--inv=Safety",
                "--no-deadlock",
                tla_name,
            )

        limits = self._profile_limits(self._execution_limits(
            bounds,
            timeout_seconds=max(0.000001, deadline - time.monotonic()),
            max_input_bytes=max(
                sum(len(value.encode("utf-8")) for value in input_files.values()),
                4096,
            ),
        ))
        tool_request = ToolRunRequest(
            argv=argv,
            runtime=ToolRuntime.JVM,
            limits=limits,
            input_files=input_files,
            output_paths=output_paths,
            environment=self._execution_environment(bounds),
        )
        stopped = interrupted()
        if stopped is not None:
            return stopped
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            control.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check deadline expired before process start")
            return interrupted()
        tool_request = replace(tool_request, limits=replace(tool_request.limits,
            timeout_seconds=min(tool_request.limits.timeout_seconds, remaining),
            cpu_seconds=min(tool_request.limits.cpu_seconds, remaining)))
        stopped = interrupted()
        if stopped is not None:
            return stopped
        process = self._runner.run(tool_request, cancellation=cancellation)
        failure = self._lifecycle_failure(process)
        if failure is not None:
            control.reject(*failure)
        if (len(process.stdout.encode("utf-8")) + len(process.stderr.encode("utf-8"))
                > tool_request.limits.max_output_bytes):
            control.reject(ModelCheckOutcomeStatus.UNKNOWN,
                "bounded checker combined output exceeded its accepted budget")
        remaining = deadline - time.monotonic()
        version = "unavailable"
        if control.observe() is None and remaining > 0:
            version = self._tool_version(
                executable, bounds=bounds, timeout_seconds=remaining,
                cancellation=cancellation,
            )
        combined = "\n".join(
            part for part in (process.stdout, process.stderr) if part
        )
        status, reason = self._classify(process, combined)
        failure = control.observe()
        if failure is not None:
            status, reason = failure
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
                    replay_notes=counterexample.replay_notes,
                )
            counterexample = replay_counterexample(
                counterexample, artifacts.source_map
            )
        failure = control.observe()
        if failure is not None:
            status, reason = failure
            counterexample = None

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
            elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
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
        operation_timeout_ms: int | None = None,
    ) -> ModelCheckOutcome:
        if not isinstance(request, BackendRequest):
            raise TLARunnerError("request must be a BackendRequest")
        validate_operation_timeout_ms(operation_timeout_ms)
        timeout = request.bounds.timeout_ms if operation_timeout_ms is None else operation_timeout_ms
        with proof_operation_scope(timeout_ms=timeout, cancellation=cancellation):
            return self._run_request(request, cancellation=cancellation,
                                     operation_timeout_ms=timeout)

    def _run_request(
        self, request: BackendRequest, *, cancellation=None, operation_timeout_ms=None,
    ) -> ModelCheckOutcome:
        payload = request.payload.to_dict()
        current_proof_operation().checkpoint("after TLA request normalization")
        if "artifacts" in payload or "model_text" in payload:
            artifacts = self._artifacts_from_payload(payload)
            return self.check(
                artifacts, request=request, cancellation=cancellation
            )
        if "document" in payload:
            compile_and_check = self.compile_and_check
            options = ({"operation_timeout_ms": operation_timeout_ms}
                if getattr(compile_and_check, "__func__", None) is TLAModelCheckerBackend.compile_and_check else {})
            return compile_and_check(
                payload["document"],
                request=request,
                module_name=str(payload.get("module_name", "StateModel")),
                cancellation=cancellation,
                **options,
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
        data = payload["artifacts"] if "artifacts" in payload else payload
        try:
            return _decode_tla_artifact_payload(data, default_bounds=self._compiler.bounds)
        except TLACompilerError as error:
            raise TLARunnerError(f"invalid artifacts payload: {error}") from error

    def _unavailable_receipt(
        self,
        artifacts: GeneratedTLAArtifacts,
        *,
        probe: ToolProbe,
        bounds: ExecutionBounds,
        jvm_available: bool | None = None,
    ) -> ModelCheckReceipt:
        jvm_ok = (
            self._jvm_probe() if self.capability.requires_jvm else True
        ) if jvm_available is None else jvm_available
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

    @staticmethod
    def _execution_limits(
        bounds: ExecutionBounds, *, timeout_seconds: float,
        max_input_bytes: int = 4096, version_probe: bool = False,
    ) -> ToolRunLimits:
        # RLIMIT_AS is virtual address space, not resident memory. Giving a JVM
        # only the RSS budget prevents it from reserving its heap/class space.
        # RSS is sampled by BoundedToolRunner and may overshoot between samples;
        # it is not a kernel-enforced aggregate cgroup memory ceiling.
        return ToolRunLimits(
            timeout_seconds=timeout_seconds,
            cpu_seconds=timeout_seconds,
            memory_bytes=max(JVM_ADDRESS_SPACE_FLOOR_BYTES, 4 * bounds.max_memory_bytes),
            resident_memory_bytes=bounds.max_memory_bytes,
            max_output_bytes=min(
                bounds.max_output_bytes,
                64 * 1024 if version_probe else DEFAULT_MAX_OUTPUT_BYTES,
            ),
            max_input_bytes=max_input_bytes,
            max_workspace_bytes=max(16 * 1024 * 1024, max_input_bytes),
        )

    def _tool_version(
        self, executable: str, *, bounds: ExecutionBounds | None = None,
        timeout_seconds: float = DEFAULT_VERSION_TIMEOUT_SECONDS,
        cancellation: CancellationSignal | None = None,
    ) -> str:
        if not executable or timeout_seconds <= 0:
            return ""
        version_started = time.monotonic()
        version_timeout = min(DEFAULT_VERSION_TIMEOUT_SECONDS, timeout_seconds)
        version_deadline = version_started + version_timeout
        control = _MODEL_CHECK_CONTROL.get() or _ModelCheckControl(
            version_started, version_timeout, cancellation)
        if control.observe() is not None:
            return "unavailable"
        selected_bounds = bounds or ExecutionBounds()
        refusal = self._profile_refusal(selected_bounds)
        if refusal is not None:
            control.reject(ModelCheckOutcomeStatus.UNKNOWN, refusal)
            return "unavailable"
        if self.tool is ModelCheckerTool.TLC:
            argv = (executable, "-help")
        else:
            argv = (executable, "version")
        request = ToolRunRequest(
            argv=argv,
            runtime=ToolRuntime.JVM,
            limits=self._profile_limits(self._execution_limits(
                selected_bounds,
                timeout_seconds=version_timeout,
                version_probe=True,
            )),
            environment=self._execution_environment(selected_bounds),
        )
        if control.observe() is not None:
            return "unavailable"
        if time.monotonic() >= version_deadline:
            control.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check version probe deadline expired")
            return "unavailable"
        remaining = min(version_deadline, control.deadline) - time.monotonic()
        if remaining <= 0:
            control.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check version probe deadline expired")
            return "unavailable"
        request = replace(request, limits=replace(request.limits,
            timeout_seconds=min(request.limits.timeout_seconds, remaining),
            cpu_seconds=min(request.limits.cpu_seconds, remaining)))
        if control.observe() is not None:
            return "unavailable"
        if time.monotonic() >= version_deadline:
            control.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check version probe deadline expired")
            return "unavailable"
        try:
            result = self._runner.run(request, cancellation=cancellation)
        except Exception as exc:  # fail closed
            control.reject(ModelCheckOutcomeStatus.ERROR,
                f"model-check version probe failed: {type(exc).__name__}")
            return f"unavailable: {type(exc).__name__}: {exc}"
        failure = self._lifecycle_failure(result)
        if failure is not None:
            control.reject(failure[0], "model-check version probe: " + failure[1])
        if (len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
                > request.limits.max_output_bytes):
            control.reject(ModelCheckOutcomeStatus.UNKNOWN,
                "model-check version probe combined output exceeded its accepted budget")
        if time.monotonic() >= version_deadline:
            control.reject(ModelCheckOutcomeStatus.TIMED_OUT, "model-check version probe deadline expired")
        if control.observe() is not None:
            return "unavailable"
        # TLC's help banner normally exits with code 1; this is descriptive
        # tool metadata, not an independent successful model-check result.
        if result.returncode not in ((0, 1) if self.tool is ModelCheckerTool.TLC else (0,)):
            return "unavailable"
        text = (result.stdout or result.stderr).strip()
        if control.observe() is not None:
            return "unavailable"
        return text[:512] if text else "unknown"

    def _lifecycle_failure(
        self, process: ToolRunResult,
    ) -> tuple[ModelCheckOutcomeStatus, str] | None:
        """Operational failure takes precedence over all semantic markers.

        A complete model counterexample can use a positive nonzero exit code
        (TLC invariant violations use 12). Missing or signal exits, incomplete
        cleanup and failed resource observations cannot establish a conclusion.
        """
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
        if process.output_truncated or process.resource_exhausted or process.workspace_limit_exceeded:
            return (
                ModelCheckOutcomeStatus.UNKNOWN,
                "bounded checker output was truncated or resource-exhausted; "
                "success cannot be established",
            )
        if process.error:
            return (
                ModelCheckOutcomeStatus.ERROR,
                f"bounded model checker failed: {process.error}",
            )
        if process.process_tree_terminated or not process.workspace_cleaned:
            return (
                ModelCheckOutcomeStatus.ERROR,
                "bounded model checker execution or workspace cleanup was incomplete",
            )
        if type(process.returncode) is not int or process.returncode < 0:
            return (
                ModelCheckOutcomeStatus.ERROR,
                "bounded model checker did not finish with a complete process exit",
            )
        return None

    def _classify(
        self, process: ToolRunResult, combined: str
    ) -> tuple[ModelCheckOutcomeStatus, str]:
        failure = self._lifecycle_failure(process)
        if failure is not None:
            return failure
        lower = combined.lower()
        if any(marker in lower for marker in _COUNTEREXAMPLE_MARKERS):
            return (
                ModelCheckOutcomeStatus.COUNTEREXAMPLE,
                "bounded model checker reported a counterexample",
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
        which: ExecutableFinder | None = None,
        jvm_probe: JvmProbe | None = None,
        java_executable: str | None = None,
        lazy_install: bool = True,
    ) -> None:
        self.compiler = compiler or TLACompiler()
        shared_runner = runner
        self.tlc = tlc or TLCBackend(
            runner=shared_runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self.compiler,
            java_executable=java_executable,
            lazy_install=lazy_install,
        )
        self.apalache = apalache or ApalacheBackend(
            runner=shared_runner,
            which=which,
            jvm_probe=jvm_probe,
            compiler=self.compiler,
            java_executable=java_executable,
            lazy_install=lazy_install,
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
