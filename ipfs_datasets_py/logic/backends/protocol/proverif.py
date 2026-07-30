"""Canonical ProVerif protocol backend (``ProVerifBackend@1``).

Generalizes reviewed supervisor/domain protocol models into a deterministic
ProVerif compiler, bounded runner, result parser, and attack-trace receipt
layer.  The adapter reuses the shared process lifecycle and typed
:class:`~ipfs_datasets_py.logic.backends.results.ProtocolResult` surface
without editing installers, public API, or supervisor routing.

Fail-closed rules
-----------------
* compilers disclose the Dolev-Yao/symbolic-model ceiling, equational theory,
  and claim support before any tool is invoked;
* tool version and opam dependency identity bind every receipt;
* attack traces normalize into a replayable structure or the result is
  non-conclusive;
* disagreement and inconclusive multi-claim outcomes are quarantined;
* missing tools yield an explicit ``UNAVAILABLE`` protocol result and never
  ``SECURE``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
from ...software_verification.protocol import (
    AdversaryKind,
    EquationalTheory,
    FunctionKind,
    ProtocolClaim,
    ProtocolClaimKind,
    ProtocolIR,
    ProtocolTerm,
)
from ..process import (
    BoundedToolRunner,
    CancellationSignal,
    ToolRunLimits,
    ToolRunRequest,
    ToolRunResult,
    ToolRuntime,
)
from ..results import (
    ProtocolResult,
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)

PROVERIF_BACKEND_VERSION: Final = "ProVerifBackend@1"
PROVERIF_COMPILER_VERSION: Final = "proverif-compiler/v1"
PROVERIF_RECEIPT_VERSION: Final = "proverif-protocol-receipt/v1"
PROVERIF_SOURCE_BINDING_VERSION: Final = "proverif-source-binding/v1"
PROVERIF_ATTACK_TRACE_VERSION: Final = "proverif-attack-trace/v1"
PROVERIF_CEILING_VERSION: Final = "symbolic-model-ceiling/v1"
PROVERIF_TOOLCHAIN_VERSION: Final = "proverif-toolchain-binding/v1"
PROVERIF_QUARANTINE_VERSION: Final = "protocol-result-quarantine/v1"

DEFAULT_MAX_DIAGNOSTIC_CHARS: Final = 512
DEFAULT_MAX_DIAGNOSTICS: Final = 32
DEFAULT_MAX_SOURCE_BYTES: Final = 1_048_576

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_QUERY_LINE = re.compile(
    r"(?im)^\s*query\s+(.+?)\s*\.\s*$"
)
_RESULT_LINE = re.compile(
    r"(?im)^\s*RESULT\s+(.+?)\s+is\s+(true|false|cannot be proved)\s*\.?\s*$"
)
_ATTACK_STEP = re.compile(
    r"(?im)^\s*(?:->|=>|\*)?\s*(?:out|in|event|new|let|phase)\s*"
    r"\(?([A-Za-z_][A-Za-z0-9_']*)\)?(?:\s*\((.*?)\))?"
)
_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_]+")

PROVERIF_SUPPORTED_CLAIMS: Final = frozenset(
    {
        ProtocolClaimKind.SECRECY,
        ProtocolClaimKind.REACHABILITY,
        ProtocolClaimKind.AUTHENTICATION,
        ProtocolClaimKind.CORRESPONDENCE,
        ProtocolClaimKind.EQUIVALENCE,
    }
)

PROVERIF_SUPPORTED_THEORIES: Final = frozenset(
    {
        EquationalTheory.FREE,
        EquationalTheory.PAIRING,
        EquationalTheory.SYMMETRIC_ENCRYPTION,
        EquationalTheory.ASYMMETRIC_ENCRYPTION,
        EquationalTheory.SIGNATURES,
        EquationalTheory.HASHING,
    }
)


class ProVerifBackendError(ValueError):
    """Raised when a ProVerif request, compile step, or receipt is invalid."""


class QuarantineReason(StrEnum):
    """Why multi-claim or partial outcomes are withheld from SECURE/ATTACK."""

    DISAGREEMENT = "disagreement"
    INCONCLUSIVE = "inconclusive"
    MALFORMED_OUTPUT = "malformed_output"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class ClaimVerdict(StrEnum):
    """Normalized per-query ProVerif outcome."""

    TRUE = "true"
    FALSE = "false"
    CANNOT_PROVE = "cannot_prove"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"


class SymbolicModelCeiling:
    """Static Dolev-Yao / perfect-cryptography ceiling for ProVerif."""

    SCHEMA_VERSION: Final = PROVERIF_CEILING_VERSION
    ADVERSARY_MODEL: Final = "dolev_yao"
    COMPUTATIONAL_SOUNDNESS: Final = False
    BITSTRING_LEVEL: Final = False
    PERFECT_CRYPTOGRAPHY: Final = True
    DESCRIPTION: Final = (
        "Symbolic Dolev-Yao adversary under a perfect cryptography assumption; "
        "applied pi-calculus processes; no computational reduction is established."
    )

    @classmethod
    def disclose(
        cls,
        *,
        equational_theories: Sequence[str],
        claim_kinds: Sequence[str],
        adversary_kind: str = AdversaryKind.DOLEV_YAO.value,
    ) -> dict[str, Any]:
        return {
            "adversary_kind": adversary_kind,
            "adversary_model": cls.ADVERSARY_MODEL,
            "bitstring_level": cls.BITSTRING_LEVEL,
            "claim_support": sorted(claim_kinds),
            "computational_soundness": cls.COMPUTATIONAL_SOUNDNESS,
            "description": cls.DESCRIPTION,
            "equational_theories": sorted(equational_theories),
            "perfect_cryptography": cls.PERFECT_CRYPTOGRAPHY,
            "schema_version": cls.SCHEMA_VERSION,
            "supported_claim_kinds": sorted(
                item.value for item in PROVERIF_SUPPORTED_CLAIMS
            ),
            "supported_equational_theories": sorted(
                item.value for item in PROVERIF_SUPPORTED_THEORIES
            ),
            "tool": "proverif",
        }


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise ProVerifBackendError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise ProVerifBackendError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _frozen(value: Mapping[str, Any] | FrozenMap, field_name: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise ProVerifBackendError(
            f"{field_name} must contain immutable JSON-compatible data"
        ) from error


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ProVerifBackendError(f"{field_name} must be one of {choices}") from error


def content_digest(content: str) -> str:
    if not isinstance(content, str) or "\x00" in content:
        raise ProVerifBackendError("content must be text without NUL bytes")
    return stable_digest({"content": content})


def sanitize_diagnostic(
    value: object,
    *,
    max_chars: int = DEFAULT_MAX_DIAGNOSTIC_CHARS,
) -> str:
    if not isinstance(value, str):
        value = str(value)
    cleaned = _CONTROL.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return "empty-diagnostic"
    if len(cleaned) > max_chars:
        return cleaned[: max(0, max_chars - 3)] + "..."
    return cleaned


def bound_diagnostics(
    values: Sequence[object],
    *,
    max_items: int = DEFAULT_MAX_DIAGNOSTICS,
    max_chars: int = DEFAULT_MAX_DIAGNOSTIC_CHARS,
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = sanitize_diagnostic(raw, max_chars=max_chars)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= max_items:
            break
    return tuple(result)


def _safe_ident(value: str, *, prefix: str = "id") -> str:
    cleaned = _SAFE_IDENT.sub("_", value.strip())
    cleaned = cleaned.strip("_") or prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:96]


def _term_to_pv(term: ProtocolTerm, names: Mapping[str, str]) -> str:
    if term.symbol_id:
        return names.get(term.symbol_id, _safe_ident(term.symbol_id, prefix="sym"))
    if term.function_id:
        fname = names.get(term.function_id, _safe_ident(term.function_id, prefix="f"))
        args = ", ".join(_term_to_pv(arg, names) for arg in term.arguments)
        return f"{fname}({args})" if args else f"{fname}()"
    literal = term.literal or "unit"
    return f'"{_safe_ident(literal, prefix="lit")}"'


@dataclass(frozen=True, slots=True)
class ProVerifSourceBinding:
    """Identity of the exact ProVerif source submitted for one request."""

    request_digest: str
    source_digest: str
    source_format: str = "pv"
    schema_version: str = PROVERIF_SOURCE_BINDING_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        if self.schema_version != PROVERIF_SOURCE_BINDING_VERSION:
            raise ProVerifBackendError(
                f"unsupported ProVerif source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls, request: BackendRequest, source: str, source_format: str
    ) -> ProVerifSourceBinding:
        if not isinstance(request, BackendRequest):
            raise ProVerifBackendError("request must be a BackendRequest")
        normalized = _source_text(source)
        fmt = _text(source_format, "source_format").lower()
        return cls(
            request_digest=request.digest,
            source_digest=content_digest(normalized),
            source_format=fmt,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
        }


@dataclass(frozen=True, slots=True)
class ToolDependencyBinding:
    """Named dependency (e.g. opam package) pinned into a protocol receipt."""

    dependency_id: str
    name: str
    version: str = ""
    required: bool = True
    schema_version: str = "tool-dependency-binding/v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dependency_id", _text(self.dependency_id, "dependency_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "version", _text(self.version, "version", optional=True)
        )
        if not isinstance(self.required, bool):
            raise ProVerifBackendError("required must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "name": self.name,
            "required": self.required,
            "schema_version": self.schema_version,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class ProVerifToolchainBinding:
    """Tool version and opam dependency binding for one run."""

    tool_id: str
    executable: str
    tool_version: str
    dependencies: tuple[ToolDependencyBinding, ...]
    schema_version: str = PROVERIF_TOOLCHAIN_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        object.__setattr__(self, "executable", _text(self.executable, "executable"))
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version")
        )
        deps = tuple(self.dependencies)
        if any(not isinstance(item, ToolDependencyBinding) for item in deps):
            raise ProVerifBackendError(
                "dependencies must be ToolDependencyBinding values"
            )
        object.__setattr__(self, "dependencies", deps)
        if self.schema_version != PROVERIF_TOOLCHAIN_VERSION:
            raise ProVerifBackendError(
                f"unsupported toolchain schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependencies": [item.to_dict() for item in self.dependencies],
            "executable": self.executable,
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
        }


@dataclass(frozen=True, slots=True)
class AttackTraceStep:
    """One normalized, replayable step of a symbolic attack."""

    step_index: int
    action: str
    label: str
    terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.step_index, bool)
            or not isinstance(self.step_index, int)
            or self.step_index < 0
        ):
            raise ProVerifBackendError("step_index must be a non-negative integer")
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        terms = tuple(_text(item, "terms item") for item in self.terms)
        object.__setattr__(self, "terms", terms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "label": self.label,
            "step_index": self.step_index,
            "terms": list(self.terms),
        }

    def replay_token(self) -> str:
        terms = ",".join(self.terms)
        return f"{self.step_index}:{self.action}:{self.label}:{terms}"


@dataclass(frozen=True, slots=True)
class NormalizedAttackTrace:
    """Normalized attack witness bound to a claim and raw output digest."""

    claim_id: str
    steps: tuple[AttackTraceStep, ...]
    raw_digest: str
    trace_format: str = "proverif-trace"
    schema_version: str = PROVERIF_ATTACK_TRACE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        steps = tuple(self.steps)
        if any(not isinstance(item, AttackTraceStep) for item in steps):
            raise ProVerifBackendError("steps must be AttackTraceStep values")
        if not steps:
            raise ProVerifBackendError("attack traces require at least one step")
        indices = [item.step_index for item in steps]
        if indices != list(range(len(steps))):
            raise ProVerifBackendError(
                "attack trace steps must be densely indexed from 0"
            )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "raw_digest", _digest(self.raw_digest, "raw_digest"))
        object.__setattr__(
            self, "trace_format", _text(self.trace_format, "trace_format")
        )
        if self.schema_version != PROVERIF_ATTACK_TRACE_VERSION:
            raise ProVerifBackendError(
                f"unsupported attack trace schema: {self.schema_version!r}"
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "raw_digest": self.raw_digest,
            "replay": list(self.replay()),
            "schema_version": self.schema_version,
            "steps": [item.to_dict() for item in self.steps],
            "trace_format": self.trace_format,
        }

    @property
    def trace_id(self) -> str:
        return f"attack-trace:{stable_digest(self._identity_payload())}"

    def replay(self) -> tuple[str, ...]:
        return tuple(step.replay_token() for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["trace_id"] = self.trace_id
        return payload


@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """Parsed outcome for one query/claim."""

    claim_id: str
    query_text: str
    verdict: ClaimVerdict
    attack_trace: NormalizedAttackTrace | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "query_text", _text(self.query_text, "query_text"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, ClaimVerdict, "verdict")
        )
        if self.attack_trace is not None and not isinstance(
            self.attack_trace, NormalizedAttackTrace
        ):
            raise ProVerifBackendError("attack_trace must be NormalizedAttackTrace")
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_trace": (
                self.attack_trace.to_dict() if self.attack_trace is not None else None
            ),
            "claim_id": self.claim_id,
            "query_text": self.query_text,
            "reason": self.reason,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class ResultQuarantine:
    """Explicit quarantine of non-authoritative protocol outcomes."""

    reason: QuarantineReason
    detail: str
    claim_ids: tuple[str, ...] = ()
    schema_version: str = PROVERIF_QUARANTINE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _enum(self.reason, QuarantineReason, "reason")
        )
        object.__setattr__(self, "detail", _text(self.detail, "detail"))
        claims = tuple(_text(item, "claim_ids item") for item in self.claim_ids)
        if len(claims) != len(set(claims)):
            raise ProVerifBackendError("claim_ids must not contain duplicates")
        object.__setattr__(self, "claim_ids", claims)
        if self.schema_version != PROVERIF_QUARANTINE_VERSION:
            raise ProVerifBackendError(
                f"unsupported quarantine schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_ids": list(self.claim_ids),
            "detail": self.detail,
            "reason": self.reason.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProVerifCompileResult:
    """Deterministic compile output with ceiling disclosure."""

    source: str
    source_format: str
    source_digest: str
    ceiling: FrozenMap
    claim_queries: FrozenMap
    equational_theories: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    protocol_document_id: str = ""
    schema_version: str = PROVERIF_COMPILER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _source_text(self.source))
        object.__setattr__(
            self, "source_format", _text(self.source_format, "source_format")
        )
        object.__setattr__(
            self, "source_digest", _digest(self.source_digest, "source_digest")
        )
        object.__setattr__(self, "ceiling", _frozen(self.ceiling, "ceiling"))
        object.__setattr__(
            self, "claim_queries", _frozen(self.claim_queries, "claim_queries")
        )
        theories = tuple(
            _text(item, "equational_theories item") for item in self.equational_theories
        )
        object.__setattr__(self, "equational_theories", theories)
        unsupported = tuple(
            _text(item, "unsupported_claims item") for item in self.unsupported_claims
        )
        object.__setattr__(self, "unsupported_claims", unsupported)
        object.__setattr__(
            self,
            "protocol_document_id",
            _text(self.protocol_document_id, "protocol_document_id", optional=True),
        )
        if self.schema_version != PROVERIF_COMPILER_VERSION:
            raise ProVerifBackendError(
                f"unsupported compiler schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceiling": self.ceiling.to_dict(),
            "claim_queries": self.claim_queries.to_dict(),
            "equational_theories": list(self.equational_theories),
            "protocol_document_id": self.protocol_document_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
            "unsupported_claims": list(self.unsupported_claims),
        }


@dataclass(frozen=True, slots=True)
class ProVerifProtocolReceipt:
    """Auditable receipt binding compile, toolchain, and claim outcomes."""

    request_digest: str
    source_binding: ProVerifSourceBinding
    toolchain: ProVerifToolchainBinding
    ceiling: FrozenMap
    compile_digest: str
    claim_outcomes: tuple[ClaimOutcome, ...]
    quarantine: ResultQuarantine | None
    accepted: bool
    diagnostics: tuple[str, ...] = ()
    schema_version: str = PROVERIF_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, ProVerifSourceBinding):
            raise ProVerifBackendError("source_binding must be ProVerifSourceBinding")
        if self.request_digest != self.source_binding.request_digest:
            raise ProVerifBackendError("receipt request does not match source binding")
        if not isinstance(self.toolchain, ProVerifToolchainBinding):
            raise ProVerifBackendError("toolchain must be ProVerifToolchainBinding")
        object.__setattr__(self, "ceiling", _frozen(self.ceiling, "ceiling"))
        object.__setattr__(
            self, "compile_digest", _digest(self.compile_digest, "compile_digest")
        )
        outcomes = tuple(self.claim_outcomes)
        if any(not isinstance(item, ClaimOutcome) for item in outcomes):
            raise ProVerifBackendError("claim_outcomes must be ClaimOutcome values")
        object.__setattr__(self, "claim_outcomes", outcomes)
        if self.quarantine is not None and not isinstance(
            self.quarantine, ResultQuarantine
        ):
            raise ProVerifBackendError("quarantine must be ResultQuarantine")
        if not isinstance(self.accepted, bool):
            raise ProVerifBackendError("accepted must be a boolean")
        if self.accepted and self.quarantine is not None:
            raise ProVerifBackendError("accepted receipts cannot be quarantined")
        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != PROVERIF_RECEIPT_VERSION:
            raise ProVerifBackendError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )

    @property
    def receipt_id(self) -> str:
        return f"proverif-protocol-receipt:{stable_digest(self._payload())}"

    def _payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "ceiling": self.ceiling.to_dict(),
            "claim_outcomes": [item.to_dict() for item in self.claim_outcomes],
            "compile_digest": self.compile_digest,
            "diagnostics": list(self.diagnostics),
            "quarantine": (
                self.quarantine.to_dict() if self.quarantine is not None else None
            ),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "source_binding": self.source_binding.to_dict(),
            "toolchain": self.toolchain.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["receipt_id"] = self.receipt_id
        return payload


@dataclass(frozen=True, slots=True)
class ProVerifBackendOutcome:
    """Normalized protocol result plus receipt for one request."""

    request_digest: str
    source_binding: ProVerifSourceBinding
    result: TypedBackendResult
    receipt: ProVerifProtocolReceipt
    compile_result: ProVerifCompileResult
    interface_version: str = PROVERIF_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, ProVerifSourceBinding):
            raise ProVerifBackendError("source_binding must be ProVerifSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise ProVerifBackendError("result must be a TypedBackendResult")
        if not isinstance(self.receipt, ProVerifProtocolReceipt):
            raise ProVerifBackendError("receipt must be a ProVerifProtocolReceipt")
        if not isinstance(self.compile_result, ProVerifCompileResult):
            raise ProVerifBackendError("compile_result must be a ProVerifCompileResult")
        if self.request_digest != self.source_binding.request_digest:
            raise ProVerifBackendError("outcome request does not match source binding")
        if self.request_digest != self.receipt.request_digest:
            raise ProVerifBackendError("outcome request does not match receipt")
        if self.interface_version != PROVERIF_BACKEND_VERSION:
            raise ProVerifBackendError(
                f"unsupported ProVerif interface: {self.interface_version!r}"
            )
        if (
            self.result.status is ResultStatus.SECURE
            and not self.receipt.accepted
        ):
            raise ProVerifBackendError("SECURE results require an accepted receipt")
        if self.result.authority is not ResultAuthority.PROTOCOL:
            raise ProVerifBackendError(
                "ProVerif outcomes must carry protocol authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "compile_result": self.compile_result.to_dict(),
            "interface_version": self.interface_version,
            "receipt": self.receipt.to_dict(),
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "source_binding": self.source_binding.to_dict(),
        }


def _source_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProVerifBackendError(
            "ProVerif source must be non-empty text without NUL bytes"
        )
    if len(value.encode("utf-8")) > DEFAULT_MAX_SOURCE_BYTES:
        raise ProVerifBackendError("ProVerif source exceeds the canonical byte bound")
    return value


def parse_attack_trace(
    raw_output: str,
    *,
    claim_id: str,
    raw_digest: str | None = None,
) -> NormalizedAttackTrace | None:
    """Normalize ProVerif-style attack steps; return None when none are present."""

    if not isinstance(raw_output, str) or not raw_output.strip():
        return None
    steps: list[AttackTraceStep] = []
    for match in _ATTACK_STEP.finditer(raw_output):
        label = match.group(1) or "step"
        terms_raw = match.group(2) or ""
        terms = tuple(
            part.strip()
            for part in terms_raw.split(",")
            if part.strip() and "\x00" not in part
        )
        steps.append(
            AttackTraceStep(
                step_index=len(steps),
                action="process",
                label=_safe_ident(label, prefix="step"),
                terms=terms[:16],
            )
        )
    if not steps:
        if re.search(r"(?i)\bis\s+false\b", raw_output):
            steps.append(
                AttackTraceStep(
                    step_index=0,
                    action="marker",
                    label="false",
                    terms=(),
                )
            )
        else:
            return None
    return NormalizedAttackTrace(
        claim_id=claim_id,
        steps=tuple(steps),
        raw_digest=raw_digest or content_digest(raw_output),
        trace_format="proverif-trace",
    )


def _normalize_query_key(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def parse_proverif_claim_outcomes(
    stdout: str,
    stderr: str,
    *,
    claim_queries: Mapping[str, str],
) -> tuple[ClaimOutcome, ...]:
    """Parse RESULT lines into claim outcomes."""

    combined = f"{stdout}\n{stderr}"
    raw_digest = content_digest(combined)
    results: list[tuple[str, ClaimVerdict]] = []
    for match in _RESULT_LINE.finditer(combined):
        query = match.group(1).strip()
        token = match.group(2).lower()
        if token == "true":
            verdict = ClaimVerdict.TRUE
        elif token == "false":
            verdict = ClaimVerdict.FALSE
        else:
            verdict = ClaimVerdict.CANNOT_PROVE
        results.append((query, verdict))

    inverse = {
        _normalize_query_key(query): claim_id
        for claim_id, query in claim_queries.items()
    }
    outcomes: list[ClaimOutcome] = []
    seen_claims: set[str] = set()

    for query, verdict in results:
        claim_id = inverse.get(_normalize_query_key(query), query)
        attack = None
        if verdict is ClaimVerdict.FALSE:
            attack = parse_attack_trace(
                combined, claim_id=claim_id, raw_digest=raw_digest
            )
        outcomes.append(
            ClaimOutcome(
                claim_id=claim_id,
                query_text=query,
                verdict=verdict,
                attack_trace=attack,
            )
        )
        seen_claims.add(claim_id)

    for claim_id, query in claim_queries.items():
        if claim_id in seen_claims:
            continue
        outcomes.append(
            ClaimOutcome(
                claim_id=claim_id,
                query_text=query,
                verdict=ClaimVerdict.UNKNOWN,
                reason="query outcome missing from ProVerif output",
            )
        )
    return tuple(outcomes)


def classify_claim_outcomes(
    outcomes: Sequence[ClaimOutcome],
) -> tuple[ResultStatus, ResultQuarantine | None, bool]:
    """Map multi-claim outcomes to a protocol status, quarantine, and acceptance."""

    if not outcomes:
        return (
            ResultStatus.UNKNOWN,
            ResultQuarantine(
                reason=QuarantineReason.INCONCLUSIVE,
                detail="ProVerif produced no claim outcomes",
            ),
            False,
        )

    true_hits = [item for item in outcomes if item.verdict is ClaimVerdict.TRUE]
    false_hits = [item for item in outcomes if item.verdict is ClaimVerdict.FALSE]
    incomplete = [
        item
        for item in outcomes
        if item.verdict
        in {
            ClaimVerdict.CANNOT_PROVE,
            ClaimVerdict.UNKNOWN,
            ClaimVerdict.TIMEOUT,
        }
    ]

    if false_hits and true_hits:
        return (
            ResultStatus.UNKNOWN,
            ResultQuarantine(
                reason=QuarantineReason.DISAGREEMENT,
                detail=(
                    "ProVerif reported both true and false claims; "
                    "the batch is quarantined rather than promoted"
                ),
                claim_ids=tuple(item.claim_id for item in (*true_hits, *false_hits)),
            ),
            False,
        )

    if false_hits:
        missing_trace = [item for item in false_hits if item.attack_trace is None]
        if missing_trace:
            return (
                ResultStatus.UNKNOWN,
                ResultQuarantine(
                    reason=QuarantineReason.MALFORMED_OUTPUT,
                    detail=(
                        "false claims lack a normalizable attack trace; "
                        "results are quarantined"
                    ),
                    claim_ids=tuple(item.claim_id for item in missing_trace),
                ),
                False,
            )
        if incomplete:
            return (
                ResultStatus.UNKNOWN,
                ResultQuarantine(
                    reason=QuarantineReason.INCONCLUSIVE,
                    detail=(
                        "attack found for some claims while others remain "
                        "inconclusive; quarantined"
                    ),
                    claim_ids=tuple(item.claim_id for item in incomplete),
                ),
                False,
            )
        return ResultStatus.ATTACK_FOUND, None, False

    if incomplete:
        return (
            ResultStatus.UNKNOWN,
            ResultQuarantine(
                reason=QuarantineReason.INCONCLUSIVE,
                detail="one or more claims remain unproved, unknown, or timed out",
                claim_ids=tuple(item.claim_id for item in incomplete),
            ),
            False,
        )

    if true_hits and len(true_hits) == len(outcomes):
        return ResultStatus.SECURE, None, True

    return (
        ResultStatus.UNKNOWN,
        ResultQuarantine(
            reason=QuarantineReason.INCONCLUSIVE,
            detail="unable to classify ProVerif claim outcomes",
            claim_ids=tuple(item.claim_id for item in outcomes),
        ),
        False,
    )


class ProVerifCompiler:
    """Deterministic ProtocolIR → ProVerif ``.pv`` compiler."""

    interface_version: Final = PROVERIF_COMPILER_VERSION

    def disclose_ceiling(
        self,
        protocol: ProtocolIR | None = None,
        *,
        equational_theories: Sequence[str] | None = None,
        claim_kinds: Sequence[str] | None = None,
        adversary_kind: str = AdversaryKind.DOLEV_YAO.value,
    ) -> dict[str, Any]:
        if protocol is not None:
            equational_theories = [
                item.value for item in protocol.equational_theories
            ]
            claim_kinds = [item.kind.value for item in protocol.claims]
            adversary_kind = protocol.adversary.kind.value
        return SymbolicModelCeiling.disclose(
            equational_theories=equational_theories or (EquationalTheory.FREE.value,),
            claim_kinds=claim_kinds or (),
            adversary_kind=adversary_kind,
        )

    def supports_claim(self, kind: ProtocolClaimKind | str) -> bool:
        kind = kind if isinstance(kind, ProtocolClaimKind) else ProtocolClaimKind(kind)
        return kind in PROVERIF_SUPPORTED_CLAIMS

    def supports_theory(self, theory: EquationalTheory | str) -> bool:
        theory = (
            theory
            if isinstance(theory, EquationalTheory)
            else EquationalTheory(theory)
        )
        return theory in PROVERIF_SUPPORTED_THEORIES

    def compile_source(
        self, source: str, *, source_format: str = "pv"
    ) -> ProVerifCompileResult:
        text = _source_text(source)
        queries = {
            f"query:{index}": match.group(1).strip()
            for index, match in enumerate(_QUERY_LINE.finditer(text))
        }
        # Prefer claim: labels in comments: (* claim:secrecy *)
        labeled: dict[str, str] = {}
        for match in re.finditer(
            r"(?is)\(\*\s*claim:([A-Za-z0-9_.:/-]+)\s*\*\)\s*query\s+(.+?)\s*\.",
            text,
        ):
            labeled[match.group(1).strip()] = match.group(2).strip()
        if labeled:
            queries = labeled

        theories = [EquationalTheory.FREE.value]
        if re.search(r"(?i)\bfun\s+senc\b|\bfun\s+sdec\b", text):
            theories.append(EquationalTheory.SYMMETRIC_ENCRYPTION.value)
        if re.search(r"(?i)\bfun\s+aenc\b|\bfun\s+adec\b", text):
            theories.append(EquationalTheory.ASYMMETRIC_ENCRYPTION.value)
        if re.search(r"(?i)\bfun\s+sign\b|\bfun\s+checksign\b", text):
            theories.append(EquationalTheory.SIGNATURES.value)
        if re.search(r"(?i)\bfun\s+h\b|\bfun\s+hash\b", text):
            theories.append(EquationalTheory.HASHING.value)
        if re.search(r"(?i)\bfun\s+pair\b", text):
            theories.append(EquationalTheory.PAIRING.value)

        ceiling = SymbolicModelCeiling.disclose(
            equational_theories=tuple(dict.fromkeys(theories)),
            claim_kinds=tuple(queries),
        )
        return ProVerifCompileResult(
            source=text,
            source_format=_text(source_format, "source_format").lower(),
            source_digest=content_digest(text),
            ceiling=FrozenMap(ceiling),
            claim_queries=FrozenMap(queries),
            equational_theories=tuple(dict.fromkeys(theories)),
            unsupported_claims=(),
        )

    def compile_protocol(self, protocol: ProtocolIR) -> ProVerifCompileResult:
        if not isinstance(protocol, ProtocolIR):
            raise ProVerifBackendError("protocol must be a ProtocolIR")

        unsupported = tuple(
            claim.claim_id
            for claim in protocol.claims
            if claim.kind not in PROVERIF_SUPPORTED_CLAIMS
        )
        theories = list(protocol.equational_theories)
        for theory in theories:
            if theory not in PROVERIF_SUPPORTED_THEORIES:
                raise ProVerifBackendError(
                    f"unsupported equational theory for ProVerif: {theory.value}"
                )

        names: dict[str, str] = {}
        for sort in protocol.sorts:
            names[sort.sort_id] = _safe_ident(sort.name, prefix="t")
        for role in protocol.roles:
            names[role.role_id] = _safe_ident(role.name, prefix="role")
        for variable in protocol.variables:
            names[variable.variable_id] = _safe_ident(variable.name, prefix="v")
        for fresh in protocol.fresh_names:
            names[fresh.name_id] = _safe_ident(fresh.name, prefix="n")
        for key in protocol.keys:
            names[key.key_id] = _safe_ident(key.name, prefix="k")
        for function in protocol.functions:
            names[function.function_id] = _safe_ident(function.name, prefix="f")
        for event in protocol.events:
            names[event.event_id] = _safe_ident(event.name, prefix="ev")

        lines: list[str] = [
            "(*",
            f"  interface: {PROVERIF_BACKEND_VERSION}",
            f"  compiler: {PROVERIF_COMPILER_VERSION}",
            "  symbolic-model-ceiling: Dolev-Yao / perfect cryptography",
            f"  equational_theories: {', '.join(t.value for t in theories)}",
            f"  adversary: {protocol.adversary.kind.value}",
            f"  protocol_document_id: {protocol.document_id}",
            "*)",
            "",
            "free c: channel.",
            "",
        ]

        # Theory-specific constructors / destructors.
        if EquationalTheory.PAIRING in theories:
            lines.extend(
                [
                    "fun pair(bitstring, bitstring): bitstring.",
                    "reduc forall x: bitstring, y: bitstring; fst(pair(x, y)) = x.",
                    "reduc forall x: bitstring, y: bitstring; snd(pair(x, y)) = y.",
                    "",
                ]
            )
        if EquationalTheory.SYMMETRIC_ENCRYPTION in theories:
            lines.extend(
                [
                    "fun senc(bitstring, bitstring): bitstring.",
                    "reduc forall m: bitstring, k: bitstring; sdec(senc(m, k), k) = m.",
                    "",
                ]
            )
        if EquationalTheory.ASYMMETRIC_ENCRYPTION in theories:
            lines.extend(
                [
                    "fun pk(bitstring): bitstring.",
                    "fun aenc(bitstring, bitstring): bitstring.",
                    "reduc forall m: bitstring, k: bitstring; adec(aenc(m, pk(k)), k) = m.",
                    "",
                ]
            )
        if EquationalTheory.SIGNATURES in theories:
            lines.extend(
                [
                    "fun spk(bitstring): bitstring.",
                    "fun sign(bitstring, bitstring): bitstring.",
                    "reduc forall m: bitstring, k: bitstring; checksign(sign(m, k), spk(k)) = m.",
                    "",
                ]
            )
        if EquationalTheory.HASHING in theories:
            lines.extend(["fun h(bitstring): bitstring.", ""])

        for function in protocol.functions:
            if function.theory is not EquationalTheory.FREE:
                continue
            fname = names[function.function_id]
            arity = len(function.parameter_sorts)
            args = ", ".join(["bitstring"] * arity) if arity else ""
            if function.kind is FunctionKind.CONSTRUCTOR:
                lines.append(f"fun {fname}({args}): bitstring.")
            else:
                lines.append(
                    f"reduc forall {', '.join(f'x{i}: bitstring' for i in range(max(arity, 1)))}; "
                    f"{fname}({', '.join(f'x{i}' for i in range(max(arity, 1)))}) = x0."
                )
        if protocol.functions:
            lines.append("")

        for event in protocol.events:
            event_name = names[event.event_id]
            arity = len(event.parameters)
            args = ", ".join(["bitstring"] * arity) if arity else "bitstring"
            lines.append(f"event {event_name}({args}).")
        if protocol.events:
            lines.append("")

        claim_queries: dict[str, str] = {}
        for claim in protocol.claims:
            if claim.kind not in PROVERIF_SUPPORTED_CLAIMS:
                continue
            query = self._claim_query(claim, names)
            claim_queries[claim.claim_id] = query
            lines.append(f"(* claim:{claim.claim_id} *)")
            lines.append(f"query {query}.")
            lines.append("")

        # Minimal process skeleton: public channel and event emissions.
        lines.append("process")
        process_parts: list[str] = []
        for fresh in protocol.fresh_names:
            process_parts.append(f"new {names[fresh.name_id]}: bitstring")
        for event in protocol.events:
            event_name = names[event.event_id]
            args = ", ".join(
                _term_to_pv(term, names) for term in event.parameters
            ) or "empty"
            if args == "empty":
                process_parts.append(f"new empty: bitstring; event {event_name}(empty)")
            else:
                process_parts.append(f"event {event_name}({args})")
        if not process_parts:
            process_parts.append("0")
        lines.append("  " + ";\n  ".join(process_parts) + ".")
        lines.append("")

        source = "\n".join(lines)
        ceiling = self.disclose_ceiling(protocol)
        return ProVerifCompileResult(
            source=source,
            source_format="pv",
            source_digest=content_digest(source),
            ceiling=FrozenMap(ceiling),
            claim_queries=FrozenMap(claim_queries),
            equational_theories=tuple(item.value for item in theories),
            unsupported_claims=unsupported,
            protocol_document_id=protocol.document_id,
        )

    def _claim_query(self, claim: ProtocolClaim, names: Mapping[str, str]) -> str:
        if claim.kind is ProtocolClaimKind.SECRECY:
            secrets = " & ".join(
                f"attacker({_term_to_pv(term, names)})"
                for term in claim.secret_terms
            )
            # Secrecy is phrased as the attacker query that should be false.
            return secrets or "attacker(dummy)"
        if claim.kind is ProtocolClaimKind.REACHABILITY:
            events = " & ".join(
                f"event({names.get(event_id, _safe_ident(event_id))}(x))"
                for event_id in claim.reachable_event_ids
            )
            return f"event({events})" if " & " not in events else events
        if claim.kind in {
            ProtocolClaimKind.AUTHENTICATION,
            ProtocolClaimKind.CORRESPONDENCE,
        }:
            antecedent = claim.antecedent_event_ids[0]
            consequent = claim.consequent_event_ids[0]
            a_name = names.get(antecedent, _safe_ident(antecedent))
            c_name = names.get(consequent, _safe_ident(consequent))
            inj = "inj-" if claim.correspondence.value == "injective" else ""
            return (
                f"{inj}event({a_name}(x)) ==> {inj}event({c_name}(x))"
            )
        if claim.kind is ProtocolClaimKind.EQUIVALENCE:
            left = _term_to_pv(claim.left_terms[0], names)
            right = _term_to_pv(claim.right_terms[0], names)
            return f"choice[{left}, {right}]"
        raise ProVerifBackendError(
            f"claim kind {claim.kind.value} is outside the ProVerif compiler ceiling"
        )


def _usage_from_process(process: ToolRunResult) -> ResourceUsage:
    output_bytes = len(process.stdout.encode("utf-8")) + len(
        process.stderr.encode("utf-8")
    )
    return ResourceUsage(
        elapsed_ms=max(0, round(process.elapsed_seconds * 1000)),
        output_bytes=output_bytes,
    )


def _result_id(backend_id: str, request: BackendRequest) -> str:
    return f"result:{backend_id}:{request.digest[:24]}"


class ProVerifBackend:
    """Canonical ProVerif protocol backend implementing ``ProVerifBackend@1``."""

    interface_version: Final = PROVERIF_BACKEND_VERSION
    backend_id: Final = "proverif"
    aliases: Final = frozenset(
        {
            "proverif-prover",
            "protocol-proverif",
        }
    )
    accepted_source_formats: Final = frozenset(
        {
            "pv",
            "proverif",
            "proverif-source",
            "protocol-ir",
            "protocol_ir",
            "protocol",
        }
    )

    def __init__(
        self,
        *,
        backend_version: str = "proverif",
        executable: str = "proverif",
        opam_package: str = "proverif",
        opam_version: str = "",
        runner: BoundedToolRunner | None = None,
        version_probe: Callable[[], str] | None = None,
        opam_probe: Callable[[], str] | None = None,
        available_probe: Callable[[], bool] | None = None,
        compiler: ProVerifCompiler | None = None,
        logic_families: Sequence[str] = (
            "cryptographic_protocol",
            "protocol",
            "protocol_logic",
            "proverif",
            "software_verification",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self.opam_package = _text(opam_package, "opam_package")
        self.opam_version = _text(opam_version, "opam_version", optional=True)
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise ProVerifBackendError("runner must be a BoundedToolRunner")
        if version_probe is not None and not callable(version_probe):
            raise ProVerifBackendError("version_probe must be callable")
        if opam_probe is not None and not callable(opam_probe):
            raise ProVerifBackendError("opam_probe must be callable")
        if available_probe is not None and not callable(available_probe):
            raise ProVerifBackendError("available_probe must be callable")
        self._version_probe = version_probe
        self._opam_probe = opam_probe
        self._available_probe = available_probe
        self._compiler = compiler or ProVerifCompiler()
        if not isinstance(self._compiler, ProVerifCompiler):
            raise ProVerifBackendError("compiler must be a ProVerifCompiler")
        self.capabilities = BackendCapabilities(
            logic_families=tuple(logic_families),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        if self._available_probe is not None:
            return bool(self._available_probe())
        return self._runner.is_available(self.executable)

    def disclose_ceiling(
        self,
        protocol: ProtocolIR | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._compiler.disclose_ceiling(protocol, **kwargs)

    def probe_toolchain(self) -> ProVerifToolchainBinding:
        tool_version = self.backend_version
        if self._version_probe is not None:
            probed = self._version_probe()
            if probed:
                tool_version = _text(str(probed).splitlines()[0], "tool_version")
        opam_version = self.opam_version
        if self._opam_probe is not None:
            probed_opam = self._opam_probe()
            if probed_opam:
                opam_version = _text(
                    str(probed_opam).splitlines()[0], "opam_version", optional=True
                )
        return ProVerifToolchainBinding(
            tool_id="proverif",
            executable=self.executable,
            tool_version=tool_version,
            dependencies=(
                ToolDependencyBinding(
                    dependency_id="dep:opam:proverif",
                    name=f"opam:{self.opam_package}",
                    version=opam_version or "unspecified",
                    required=True,
                ),
            ),
        )

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise ProVerifBackendError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise ProVerifBackendError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise ProVerifBackendError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.THEOREM_PROOF:
            raise ProVerifBackendError(
                "ProVerif backend answers theorem_proof queries for protocol claims"
            )

    def _compile_request(self, request: BackendRequest) -> ProVerifCompileResult:
        payload = request.payload.to_dict()
        encoding = str(
            payload.get("encoding")
            or payload.get("source_format")
            or "protocol-ir"
        ).strip().lower()
        if encoding not in self.accepted_source_formats:
            raise ProVerifBackendError(
                f"request encoding {encoding!r} is not a supported ProVerif format"
            )

        raw_protocol = (
            payload.get("protocol_ir")
            or payload.get("protocol")
            or payload.get("ir")
        )
        if isinstance(raw_protocol, Mapping):
            protocol = ProtocolIR.from_dict(raw_protocol)
            return self._compiler.compile_protocol(protocol)
        if isinstance(raw_protocol, ProtocolIR):
            return self._compiler.compile_protocol(raw_protocol)

        source = (
            payload.get("pv")
            or payload.get("source")
            or payload.get("proverif")
            or payload.get("model")
        )
        if isinstance(source, str) and source.strip():
            return self._compiler.compile_source(
                source,
                source_format=(
                    "pv"
                    if encoding in {"protocol-ir", "protocol_ir", "protocol"}
                    else encoding
                ),
            )
        raise ProVerifBackendError(
            "ProVerif request payload requires protocol_ir or pv/source text"
        )

    def _tool_request(self, source: str, bounds: ExecutionBounds) -> ToolRunRequest:
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(source.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=(self.executable, "{workspace}/protocol.pv"),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"protocol.pv": source},
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: ProVerifSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: ProVerifProtocolReceipt,
        compile_result: ProVerifCompileResult,
        reason: str = "",
        diagnostics: Sequence[str] = (),
    ) -> ProtocolResult:
        witness: dict[str, Any] = {
            "receipt_id": receipt.receipt_id,
            "ceiling": receipt.ceiling.to_dict(),
            "toolchain": receipt.toolchain.to_dict(),
            "claim_outcomes": [item.to_dict() for item in receipt.claim_outcomes],
            "compile": compile_result.to_dict(),
        }
        if receipt.quarantine is not None:
            witness["quarantine"] = receipt.quarantine.to_dict()
        attacks = [
            item.attack_trace.to_dict()
            for item in receipt.claim_outcomes
            if item.attack_trace is not None
        ]
        if attacks:
            witness["attack_traces"] = attacks
            witness["attack_trace_replay"] = [
                list(item.attack_trace.replay())
                for item in receipt.claim_outcomes
                if item.attack_trace is not None
            ]
        return ProtocolResult(
            result_id=_result_id(self.backend_id, request),
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            authority=ResultAuthority.PROTOCOL,
            status=status,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            translation_ceiling=(
                EvidenceAuthority.BOUNDED
                if status in {ResultStatus.SECURE, ResultStatus.ATTACK_FOUND}
                else EvidenceAuthority.NONE
            ),
            usage=usage,
            witness=witness,
            diagnostics=bound_diagnostics(diagnostics),
            reason=sanitize_diagnostic(reason) if reason else "",
            metadata={
                "adapter_interface": PROVERIF_BACKEND_VERSION,
                "protocol_receipt": receipt.to_dict(),
                "source_binding": binding.to_dict(),
                "symbolic_model_ceiling": receipt.ceiling.to_dict(),
            },
        )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: CancellationSignal | Any | None = None,
    ) -> ProVerifBackendOutcome:
        self._validate_request(request)
        compile_result = self._compile_request(request)
        binding = ProVerifSourceBinding.bind(
            request, compile_result.source, compile_result.source_format
        )
        toolchain = self.probe_toolchain()
        usage = ResourceUsage()

        if compile_result.unsupported_claims:
            quarantine = ResultQuarantine(
                reason=QuarantineReason.UNSUPPORTED_CLAIM,
                detail=(
                    "protocol contains claims outside the ProVerif symbolic ceiling: "
                    + ", ".join(compile_result.unsupported_claims)
                ),
                claim_ids=compile_result.unsupported_claims,
            )
            receipt = ProVerifProtocolReceipt(
                request_digest=request.digest,
                source_binding=binding,
                toolchain=toolchain,
                ceiling=compile_result.ceiling,
                compile_digest=compile_result.source_digest,
                claim_outcomes=(),
                quarantine=quarantine,
                accepted=False,
                diagnostics=(quarantine.detail,),
            )
            result = self._build_result(
                request=request,
                binding=binding,
                status=ResultStatus.UNSUPPORTED,
                usage=usage,
                receipt=receipt,
                compile_result=compile_result,
                reason=quarantine.detail,
                diagnostics=receipt.diagnostics,
            )
            return ProVerifBackendOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                compile_result=compile_result,
            )

        if not self.is_available():
            reason = (
                f"ProVerif executable {self.executable!r} is not available; "
                "opam-backed symbolic protocol analysis cannot run"
            )
            receipt = ProVerifProtocolReceipt(
                request_digest=request.digest,
                source_binding=binding,
                toolchain=toolchain,
                ceiling=compile_result.ceiling,
                compile_digest=compile_result.source_digest,
                claim_outcomes=(),
                quarantine=None,
                accepted=False,
                diagnostics=(reason,),
            )
            result = self._build_result(
                request=request,
                binding=binding,
                status=ResultStatus.UNAVAILABLE,
                usage=usage,
                receipt=receipt,
                compile_result=compile_result,
                reason=reason,
                diagnostics=receipt.diagnostics,
            )
            return ProVerifBackendOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                compile_result=compile_result,
            )

        process = self._runner.run(
            self._tool_request(compile_result.source, request.bounds),
            cancellation=cancellation,
        )
        usage = _usage_from_process(process)

        if process.unavailable:
            reason = process.error or "ProVerif became unavailable during execution"
            status = ResultStatus.UNAVAILABLE
            outcomes: tuple[ClaimOutcome, ...] = ()
            quarantine = None
            accepted = False
        elif process.cancelled:
            reason = process.error or "ProVerif execution was cancelled"
            status = ResultStatus.ERROR
            outcomes = ()
            quarantine = None
            accepted = False
        elif process.timed_out:
            reason = process.error or "ProVerif exceeded its wall-clock bound"
            status = ResultStatus.TIMEOUT
            outcomes = ()
            quarantine = ResultQuarantine(
                reason=QuarantineReason.INCONCLUSIVE,
                detail=reason,
            )
            accepted = False
        elif process.resource_exhausted or process.output_truncated:
            reason = process.error or "ProVerif exceeded a resource or output bound"
            status = ResultStatus.ERROR
            outcomes = ()
            quarantine = None
            accepted = False
        else:
            outcomes = parse_proverif_claim_outcomes(
                process.stdout,
                process.stderr,
                claim_queries=compile_result.claim_queries.to_dict(),
            )
            status, quarantine, accepted = classify_claim_outcomes(outcomes)
            reason = process.error or ""
            if process.returncode not in (0, None) and status is ResultStatus.SECURE:
                status = ResultStatus.UNKNOWN
                accepted = False
                quarantine = ResultQuarantine(
                    reason=QuarantineReason.INCONCLUSIVE,
                    detail=(
                        f"ProVerif exited with status {process.returncode} despite "
                        "true queries; quarantined"
                    ),
                )
                reason = quarantine.detail

        diagnostics = bound_diagnostics(
            [
                *([process.error] if process.error else []),
                *([reason] if reason else []),
                *([quarantine.detail] if quarantine is not None else []),
            ]
        )
        receipt = ProVerifProtocolReceipt(
            request_digest=request.digest,
            source_binding=binding,
            toolchain=toolchain,
            ceiling=compile_result.ceiling,
            compile_digest=compile_result.source_digest,
            claim_outcomes=outcomes,
            quarantine=quarantine,
            accepted=accepted,
            diagnostics=diagnostics,
        )
        result = self._build_result(
            request=request,
            binding=binding,
            status=status,
            usage=usage,
            receipt=receipt,
            compile_result=compile_result,
            reason=reason,
            diagnostics=diagnostics,
        )
        return ProVerifBackendOutcome(
            request_digest=request.digest,
            source_binding=binding,
            result=result,
            receipt=receipt,
            compile_result=compile_result,
        )


__all__ = [
    "AttackTraceStep",
    "ClaimOutcome",
    "ClaimVerdict",
    "NormalizedAttackTrace",
    "PROVERIF_BACKEND_VERSION",
    "ProVerifBackend",
    "ProVerifBackendError",
    "ProVerifBackendOutcome",
    "ProVerifCompileResult",
    "ProVerifCompiler",
    "ProVerifProtocolReceipt",
    "ProVerifSourceBinding",
    "ProVerifToolchainBinding",
    "QuarantineReason",
    "ResultQuarantine",
    "SymbolicModelCeiling",
    "ToolDependencyBinding",
    "bound_diagnostics",
    "classify_claim_outcomes",
    "content_digest",
    "parse_attack_trace",
    "parse_proverif_claim_outcomes",
    "sanitize_diagnostic",
]
