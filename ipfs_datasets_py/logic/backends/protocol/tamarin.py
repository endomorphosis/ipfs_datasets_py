"""Canonical Tamarin protocol backend (``TamarinBackend@1``).

Generalizes reviewed supervisor/domain protocol models into a deterministic
Tamarin compiler, bounded runner, result parser, and attack-trace receipt
layer.  The adapter reuses the shared process lifecycle and typed
:class:`~ipfs_datasets_py.logic.backends.results.ProtocolResult` surface
without editing installers, public API, or supervisor routing.

Fail-closed rules
-----------------
* compilers disclose the Dolev-Yao/symbolic-model ceiling, equational theory,
  and claim support before any tool is invoked;
* tool version and Maude dependency identity bind every receipt;
* attack traces normalize into a replayable structure or the result is
  non-conclusive;
* disagreement and inconclusive multi-claim outcomes are quarantined;
* missing tools yield an explicit ``UNAVAILABLE`` protocol result and never
  ``SECURE``.
"""

from __future__ import annotations

import re
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
from ...software_verification.protocol import (
    AdversaryKind,
    EquationalTheory,
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

TAMARIN_BACKEND_VERSION: Final = "TamarinBackend@1"
TAMARIN_COMPILER_VERSION: Final = "tamarin-compiler/v1"
TAMARIN_RECEIPT_VERSION: Final = "tamarin-protocol-receipt/v1"
TAMARIN_SOURCE_BINDING_VERSION: Final = "tamarin-source-binding/v1"
TAMARIN_ATTACK_TRACE_VERSION: Final = "tamarin-attack-trace/v1"
TAMARIN_CEILING_VERSION: Final = "symbolic-model-ceiling/v1"
TAMARIN_TOOLCHAIN_VERSION: Final = "tamarin-toolchain-binding/v1"
TAMARIN_QUARANTINE_VERSION: Final = "protocol-result-quarantine/v1"

DEFAULT_MAX_DIAGNOSTIC_CHARS: Final = 512
DEFAULT_MAX_DIAGNOSTICS: Final = 32
DEFAULT_MAX_SOURCE_BYTES: Final = 1_048_576

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LEMMA_LINE = re.compile(
    r"(?im)^\s*(?:lemma|//\s*lemma)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:"
)
_VERIFIED = re.compile(
    r"(?im)^\s*(?:lemma\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)\n]*\)\s*)?:"
    r"\s*(verified|falsified|analysis incomplete|timeout|partial)\b"
)
_ATTACK_STEP = re.compile(
    r"(?im)^\s*(?:#?\d+[:.)\]]\s*)?(?:rule|action|step|event)\s+"
    r"([A-Za-z_][A-Za-z0-9_'.]*)(?:\s*\((.*?)\))?"
)
_SAFE_IDENT = re.compile(r"[^A-Za-z0-9_]+")

# Closed claim support for the symbolic multiset-rewriting ceiling.
TAMARIN_SUPPORTED_CLAIMS: Final = frozenset(
    {
        ProtocolClaimKind.SECRECY,
        ProtocolClaimKind.REACHABILITY,
        ProtocolClaimKind.AUTHENTICATION,
        ProtocolClaimKind.CORRESPONDENCE,
    }
)

# Equational theories the compiler can lower into Tamarin builtins.
TAMARIN_SUPPORTED_THEORIES: Final = frozenset(
    {
        EquationalTheory.FREE,
        EquationalTheory.PAIRING,
        EquationalTheory.SYMMETRIC_ENCRYPTION,
        EquationalTheory.ASYMMETRIC_ENCRYPTION,
        EquationalTheory.SIGNATURES,
        EquationalTheory.HASHING,
    }
)

_THEORY_TO_BUILTIN: Final = {
    EquationalTheory.PAIRING: "pairing",
    EquationalTheory.SYMMETRIC_ENCRYPTION: "symmetric-encryption",
    EquationalTheory.ASYMMETRIC_ENCRYPTION: "asymmetric-encryption",
    EquationalTheory.SIGNATURES: "signing",
    EquationalTheory.HASHING: "hashing",
}


class TamarinBackendError(ValueError):
    """Raised when a Tamarin request, compile step, or receipt is invalid."""


class QuarantineReason(StrEnum):
    """Why multi-claim or partial outcomes are withheld from SECURE/ATTACK."""

    DISAGREEMENT = "disagreement"
    INCONCLUSIVE = "inconclusive"
    MALFORMED_OUTPUT = "malformed_output"
    UNSUPPORTED_CLAIM = "unsupported_claim"


class ClaimVerdict(StrEnum):
    """Normalized per-claim Tamarin lemma outcome."""

    VERIFIED = "verified"
    FALSIFIED = "falsified"
    INCOMPLETE = "incomplete"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class SymbolicModelCeiling:
    """Static Dolev-Yao / perfect-cryptography ceiling for Tamarin."""

    SCHEMA_VERSION: Final = TAMARIN_CEILING_VERSION
    ADVERSARY_MODEL: Final = "dolev_yao"
    COMPUTATIONAL_SOUNDNESS: Final = False
    BITSTRING_LEVEL: Final = False
    PERFECT_CRYPTOGRAPHY: Final = True
    DESCRIPTION: Final = (
        "Symbolic Dolev-Yao adversary under a perfect cryptography assumption; "
        "no computational reduction or bitstring-level attacker is established."
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
                item.value for item in TAMARIN_SUPPORTED_CLAIMS
            ),
            "supported_equational_theories": sorted(
                item.value for item in TAMARIN_SUPPORTED_THEORIES
            ),
            "tool": "tamarin-prover",
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
        raise TamarinBackendError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _DIGEST.fullmatch(result):
        raise TamarinBackendError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _frozen(value: Mapping[str, Any] | FrozenMap, field_name: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise TamarinBackendError(
            f"{field_name} must contain immutable JSON-compatible data"
        ) from error


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise TamarinBackendError(f"{field_name} must be one of {choices}") from error


def content_digest(content: str) -> str:
    if not isinstance(content, str) or "\x00" in content:
        raise TamarinBackendError("content must be text without NUL bytes")
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


def _term_to_spthy(term: ProtocolTerm, names: Mapping[str, str]) -> str:
    if term.symbol_id:
        return names.get(term.symbol_id, _safe_ident(term.symbol_id, prefix="sym"))
    if term.function_id:
        fname = names.get(term.function_id, _safe_ident(term.function_id, prefix="f"))
        args = ", ".join(_term_to_spthy(arg, names) for arg in term.arguments)
        return f"{fname}({args})" if args else f"{fname}()"
    literal = term.literal or "unit"
    return f"'{_safe_ident(literal, prefix='lit')}'"


@dataclass(frozen=True, slots=True)
class TamarinSourceBinding:
    """Identity of the exact Tamarin source submitted for one request."""

    request_digest: str
    source_digest: str
    source_format: str = "spthy"
    schema_version: str = TAMARIN_SOURCE_BINDING_VERSION

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
        if self.schema_version != TAMARIN_SOURCE_BINDING_VERSION:
            raise TamarinBackendError(
                f"unsupported Tamarin source binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, request: BackendRequest, source: str, source_format: str) -> TamarinSourceBinding:
        if not isinstance(request, BackendRequest):
            raise TamarinBackendError("request must be a BackendRequest")
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
    """Named dependency (e.g. Maude) pinned into a protocol receipt."""

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
            raise TamarinBackendError("required must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_id": self.dependency_id,
            "name": self.name,
            "required": self.required,
            "schema_version": self.schema_version,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class TamarinToolchainBinding:
    """Tool version and Maude dependency binding for one run."""

    tool_id: str
    executable: str
    tool_version: str
    dependencies: tuple[ToolDependencyBinding, ...]
    schema_version: str = TAMARIN_TOOLCHAIN_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        object.__setattr__(self, "executable", _text(self.executable, "executable"))
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version")
        )
        deps = tuple(self.dependencies)
        if any(not isinstance(item, ToolDependencyBinding) for item in deps):
            raise TamarinBackendError("dependencies must be ToolDependencyBinding values")
        object.__setattr__(self, "dependencies", deps)
        if self.schema_version != TAMARIN_TOOLCHAIN_VERSION:
            raise TamarinBackendError(
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
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int) or self.step_index < 0:
            raise TamarinBackendError("step_index must be a non-negative integer")
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
    trace_format: str = "tamarin-trace"
    schema_version: str = TAMARIN_ATTACK_TRACE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        steps = tuple(self.steps)
        if any(not isinstance(item, AttackTraceStep) for item in steps):
            raise TamarinBackendError("steps must be AttackTraceStep values")
        if not steps:
            raise TamarinBackendError("attack traces require at least one step")
        indices = [item.step_index for item in steps]
        if indices != list(range(len(steps))):
            raise TamarinBackendError("attack trace steps must be densely indexed from 0")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "raw_digest", _digest(self.raw_digest, "raw_digest"))
        object.__setattr__(
            self, "trace_format", _text(self.trace_format, "trace_format")
        )
        if self.schema_version != TAMARIN_ATTACK_TRACE_VERSION:
            raise TamarinBackendError(
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
        """Deterministic replay tokens for the normalized attack path."""

        return tuple(step.replay_token() for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["trace_id"] = self.trace_id
        return payload


@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    """Parsed outcome for one lemma/claim."""

    claim_id: str
    lemma_name: str
    verdict: ClaimVerdict
    attack_trace: NormalizedAttackTrace | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "lemma_name", _text(self.lemma_name, "lemma_name"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, ClaimVerdict, "verdict")
        )
        if self.attack_trace is not None and not isinstance(
            self.attack_trace, NormalizedAttackTrace
        ):
            raise TamarinBackendError("attack_trace must be NormalizedAttackTrace")
        if (
            self.verdict is ClaimVerdict.FALSIFIED
            and self.attack_trace is None
        ):
            # Allowed at parse time; backend may quarantine if no trace.
            pass
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_trace": (
                self.attack_trace.to_dict() if self.attack_trace is not None else None
            ),
            "claim_id": self.claim_id,
            "lemma_name": self.lemma_name,
            "reason": self.reason,
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class ResultQuarantine:
    """Explicit quarantine of non-authoritative protocol outcomes."""

    reason: QuarantineReason
    detail: str
    claim_ids: tuple[str, ...] = ()
    schema_version: str = TAMARIN_QUARANTINE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _enum(self.reason, QuarantineReason, "reason")
        )
        object.__setattr__(self, "detail", _text(self.detail, "detail"))
        claims = tuple(_text(item, "claim_ids item") for item in self.claim_ids)
        if len(claims) != len(set(claims)):
            raise TamarinBackendError("claim_ids must not contain duplicates")
        object.__setattr__(self, "claim_ids", claims)
        if self.schema_version != TAMARIN_QUARANTINE_VERSION:
            raise TamarinBackendError(
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
class TamarinCompileResult:
    """Deterministic compile output with ceiling disclosure."""

    source: str
    source_format: str
    source_digest: str
    ceiling: FrozenMap
    claim_lemmas: FrozenMap
    equational_theories: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    protocol_document_id: str = ""
    schema_version: str = TAMARIN_COMPILER_VERSION

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
            self, "claim_lemmas", _frozen(self.claim_lemmas, "claim_lemmas")
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
        if self.schema_version != TAMARIN_COMPILER_VERSION:
            raise TamarinBackendError(
                f"unsupported compiler schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ceiling": self.ceiling.to_dict(),
            "claim_lemmas": self.claim_lemmas.to_dict(),
            "equational_theories": list(self.equational_theories),
            "protocol_document_id": self.protocol_document_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_format": self.source_format,
            "unsupported_claims": list(self.unsupported_claims),
        }


@dataclass(frozen=True, slots=True)
class TamarinProtocolReceipt:
    """Auditable receipt binding compile, toolchain, and claim outcomes."""

    request_digest: str
    source_binding: TamarinSourceBinding
    toolchain: TamarinToolchainBinding
    ceiling: FrozenMap
    compile_digest: str
    claim_outcomes: tuple[ClaimOutcome, ...]
    quarantine: ResultQuarantine | None
    accepted: bool
    diagnostics: tuple[str, ...] = ()
    schema_version: str = TAMARIN_RECEIPT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, TamarinSourceBinding):
            raise TamarinBackendError("source_binding must be TamarinSourceBinding")
        if self.request_digest != self.source_binding.request_digest:
            raise TamarinBackendError("receipt request does not match source binding")
        if not isinstance(self.toolchain, TamarinToolchainBinding):
            raise TamarinBackendError("toolchain must be TamarinToolchainBinding")
        object.__setattr__(self, "ceiling", _frozen(self.ceiling, "ceiling"))
        object.__setattr__(
            self, "compile_digest", _digest(self.compile_digest, "compile_digest")
        )
        outcomes = tuple(self.claim_outcomes)
        if any(not isinstance(item, ClaimOutcome) for item in outcomes):
            raise TamarinBackendError("claim_outcomes must be ClaimOutcome values")
        object.__setattr__(self, "claim_outcomes", outcomes)
        if self.quarantine is not None and not isinstance(
            self.quarantine, ResultQuarantine
        ):
            raise TamarinBackendError("quarantine must be ResultQuarantine")
        if not isinstance(self.accepted, bool):
            raise TamarinBackendError("accepted must be a boolean")
        if self.accepted and self.quarantine is not None:
            raise TamarinBackendError("accepted receipts cannot be quarantined")
        object.__setattr__(
            self, "diagnostics", bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != TAMARIN_RECEIPT_VERSION:
            raise TamarinBackendError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )

    @property
    def receipt_id(self) -> str:
        return f"tamarin-protocol-receipt:{stable_digest(self._payload())}"

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
class TamarinBackendOutcome:
    """Normalized protocol result plus receipt for one request."""

    request_digest: str
    source_binding: TamarinSourceBinding
    result: TypedBackendResult
    receipt: TamarinProtocolReceipt
    compile_result: TamarinCompileResult
    interface_version: str = TAMARIN_BACKEND_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        if not isinstance(self.source_binding, TamarinSourceBinding):
            raise TamarinBackendError("source_binding must be TamarinSourceBinding")
        if not isinstance(self.result, TypedBackendResult):
            raise TamarinBackendError("result must be a TypedBackendResult")
        if not isinstance(self.receipt, TamarinProtocolReceipt):
            raise TamarinBackendError("receipt must be a TamarinProtocolReceipt")
        if not isinstance(self.compile_result, TamarinCompileResult):
            raise TamarinBackendError("compile_result must be a TamarinCompileResult")
        if self.request_digest != self.source_binding.request_digest:
            raise TamarinBackendError("outcome request does not match source binding")
        if self.request_digest != self.receipt.request_digest:
            raise TamarinBackendError("outcome request does not match receipt")
        if self.interface_version != TAMARIN_BACKEND_VERSION:
            raise TamarinBackendError(
                f"unsupported Tamarin interface: {self.interface_version!r}"
            )
        if (
            self.result.status is ResultStatus.SECURE
            and not self.receipt.accepted
        ):
            raise TamarinBackendError("SECURE results require an accepted receipt")
        if self.result.authority is not ResultAuthority.PROTOCOL:
            raise TamarinBackendError(
                "Tamarin outcomes must carry protocol authority"
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
        raise TamarinBackendError(
            "Tamarin source must be non-empty text without NUL bytes"
        )
    if len(value.encode("utf-8")) > DEFAULT_MAX_SOURCE_BYTES:
        raise TamarinBackendError("Tamarin source exceeds the canonical byte bound")
    return value


def parse_attack_trace(
    raw_output: str,
    *,
    claim_id: str,
    raw_digest: str | None = None,
) -> NormalizedAttackTrace | None:
    """Normalize Tamarin-style attack steps; return None when none are present."""

    if not isinstance(raw_output, str) or not raw_output.strip():
        return None
    steps: list[AttackTraceStep] = []
    for match in _ATTACK_STEP.finditer(raw_output):
        label = match.group(1)
        terms_raw = match.group(2) or ""
        terms = tuple(
            part.strip()
            for part in terms_raw.split(",")
            if part.strip() and "\x00" not in part
        )
        steps.append(
            AttackTraceStep(
                step_index=len(steps),
                action="rule",
                label=_safe_ident(label, prefix="step"),
                terms=terms[:16],
            )
        )
    if not steps:
        # Fallback: retain a single replayable marker when falsified without detail.
        if re.search(r"(?i)\bfalsified\b", raw_output):
            steps.append(
                AttackTraceStep(
                    step_index=0,
                    action="marker",
                    label="falsified",
                    terms=(),
                )
            )
        else:
            return None
    return NormalizedAttackTrace(
        claim_id=claim_id,
        steps=tuple(steps),
        raw_digest=raw_digest or content_digest(raw_output),
        trace_format="tamarin-trace",
    )


def parse_tamarin_claim_outcomes(
    stdout: str,
    stderr: str,
    *,
    claim_lemmas: Mapping[str, str],
) -> tuple[ClaimOutcome, ...]:
    """Parse per-lemma verified/falsified lines into claim outcomes."""

    combined = f"{stdout}\n{stderr}"
    verdicts: dict[str, ClaimVerdict] = {}
    for match in _VERIFIED.finditer(combined):
        name = match.group(1)
        token = match.group(2).lower()
        if token == "verified":
            verdicts[name] = ClaimVerdict.VERIFIED
        elif token == "falsified":
            verdicts[name] = ClaimVerdict.FALSIFIED
        elif token == "timeout":
            verdicts[name] = ClaimVerdict.TIMEOUT
        else:
            verdicts[name] = ClaimVerdict.INCOMPLETE

    raw_digest = content_digest(combined)
    inverse = {lemma: claim for claim, lemma in claim_lemmas.items()}
    outcomes: list[ClaimOutcome] = []
    seen_claims: set[str] = set()

    for lemma_name, verdict in verdicts.items():
        claim_id = inverse.get(lemma_name, lemma_name)
        attack = None
        if verdict is ClaimVerdict.FALSIFIED:
            attack = parse_attack_trace(
                combined, claim_id=claim_id, raw_digest=raw_digest
            )
        outcomes.append(
            ClaimOutcome(
                claim_id=claim_id,
                lemma_name=lemma_name,
                verdict=verdict,
                attack_trace=attack,
            )
        )
        seen_claims.add(claim_id)

    # Preserve declared claims that never appeared in the tool output.
    for claim_id, lemma_name in claim_lemmas.items():
        if claim_id in seen_claims:
            continue
        outcomes.append(
            ClaimOutcome(
                claim_id=claim_id,
                lemma_name=lemma_name,
                verdict=ClaimVerdict.UNKNOWN,
                reason="lemma outcome missing from Tamarin output",
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
                detail="Tamarin produced no claim outcomes",
            ),
            False,
        )

    verified = [item for item in outcomes if item.verdict is ClaimVerdict.VERIFIED]
    falsified = [item for item in outcomes if item.verdict is ClaimVerdict.FALSIFIED]
    incomplete = [
        item
        for item in outcomes
        if item.verdict
        in {
            ClaimVerdict.INCOMPLETE,
            ClaimVerdict.TIMEOUT,
            ClaimVerdict.UNKNOWN,
        }
    ]

    if falsified and verified:
        return (
            ResultStatus.UNKNOWN,
            ResultQuarantine(
                reason=QuarantineReason.DISAGREEMENT,
                detail=(
                    "Tamarin reported both verified and falsified claims; "
                    "the batch is quarantined rather than promoted"
                ),
                claim_ids=tuple(
                    item.claim_id for item in (*verified, *falsified)
                ),
            ),
            False,
        )

    if falsified:
        missing_trace = [
            item for item in falsified if item.attack_trace is None
        ]
        if missing_trace:
            return (
                ResultStatus.UNKNOWN,
                ResultQuarantine(
                    reason=QuarantineReason.MALFORMED_OUTPUT,
                    detail=(
                        "falsified claims lack a normalizable attack trace; "
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
                detail="one or more claims remain incomplete, timed out, or unknown",
                claim_ids=tuple(item.claim_id for item in incomplete),
            ),
            False,
        )

    if verified and len(verified) == len(outcomes):
        return ResultStatus.SECURE, None, True

    return (
        ResultStatus.UNKNOWN,
        ResultQuarantine(
            reason=QuarantineReason.INCONCLUSIVE,
            detail="unable to classify Tamarin claim outcomes",
            claim_ids=tuple(item.claim_id for item in outcomes),
        ),
        False,
    )


class TamarinCompiler:
    """Deterministic ProtocolIR → Tamarin ``.spthy`` compiler."""

    interface_version: Final = TAMARIN_COMPILER_VERSION

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
        return kind in TAMARIN_SUPPORTED_CLAIMS

    def supports_theory(self, theory: EquationalTheory | str) -> bool:
        theory = (
            theory
            if isinstance(theory, EquationalTheory)
            else EquationalTheory(theory)
        )
        return theory in TAMARIN_SUPPORTED_THEORIES

    def compile_source(self, source: str, *, source_format: str = "spthy") -> TamarinCompileResult:
        text = _source_text(source)
        lemmas = {
            name: name for name in _LEMMA_LINE.findall(text)
        }
        ceiling = SymbolicModelCeiling.disclose(
            equational_theories=(EquationalTheory.FREE.value,),
            claim_kinds=tuple(lemmas),
        )
        # Extract builtins line if present for equational theory disclosure.
        builtins_match = re.search(
            r"(?im)^\s*builtins\s*:\s*([^\n]+)$", text
        )
        theories = [EquationalTheory.FREE.value]
        if builtins_match:
            for token in builtins_match.group(1).split(","):
                token = token.strip().lower()
                for theory, builtin in _THEORY_TO_BUILTIN.items():
                    if token == builtin:
                        theories.append(theory.value)
        ceiling = SymbolicModelCeiling.disclose(
            equational_theories=tuple(dict.fromkeys(theories)),
            claim_kinds=tuple(lemmas),
        )
        return TamarinCompileResult(
            source=text,
            source_format=_text(source_format, "source_format").lower(),
            source_digest=content_digest(text),
            ceiling=FrozenMap(ceiling),
            claim_lemmas=FrozenMap(lemmas),
            equational_theories=tuple(dict.fromkeys(theories)),
            unsupported_claims=(),
        )

    def compile_protocol(self, protocol: ProtocolIR) -> TamarinCompileResult:
        if not isinstance(protocol, ProtocolIR):
            raise TamarinBackendError("protocol must be a ProtocolIR")

        unsupported = tuple(
            claim.claim_id
            for claim in protocol.claims
            if claim.kind not in TAMARIN_SUPPORTED_CLAIMS
        )
        theories = list(protocol.equational_theories)
        for theory in theories:
            if theory not in TAMARIN_SUPPORTED_THEORIES:
                raise TamarinBackendError(
                    f"unsupported equational theory for Tamarin: {theory.value}"
                )

        names: dict[str, str] = {}
        for sort in protocol.sorts:
            names[sort.sort_id] = _safe_ident(sort.name, prefix="Sort")
        for role in protocol.roles:
            names[role.role_id] = _safe_ident(role.name, prefix="Role")
        for variable in protocol.variables:
            names[variable.variable_id] = _safe_ident(variable.name, prefix="v")
        for fresh in protocol.fresh_names:
            names[fresh.name_id] = f"~{_safe_ident(fresh.name, prefix='n')}"
        for key in protocol.keys:
            names[key.key_id] = _safe_ident(key.name, prefix="k")
        for function in protocol.functions:
            names[function.function_id] = _safe_ident(function.name, prefix="f")
        for event in protocol.events:
            names[event.event_id] = _safe_ident(event.name, prefix="Ev")

        builtins = [
            _THEORY_TO_BUILTIN[theory]
            for theory in theories
            if theory in _THEORY_TO_BUILTIN
        ]
        theory_name = _safe_ident(
            protocol.metadata.to_dict().get("protocol", "CompiledProtocol")
            if protocol.metadata
            else "CompiledProtocol",
            prefix="Theory",
        )
        lines: list[str] = [
            f"theory {theory_name}",
            "begin",
            "",
            f"/* interface: {TAMARIN_BACKEND_VERSION} */",
            f"/* compiler: {TAMARIN_COMPILER_VERSION} */",
            "/* symbolic-model-ceiling: Dolev-Yao / perfect cryptography */",
            f"/* equational_theories: {', '.join(t.value for t in theories)} */",
            f"/* adversary: {protocol.adversary.kind.value} */",
            f"/* protocol_document_id: {protocol.document_id} */",
            "",
        ]
        if builtins:
            lines.append(f"builtins: {', '.join(dict.fromkeys(builtins))}")
            lines.append("")

        # Functions not covered by builtins.
        for function in protocol.functions:
            if function.theory is EquationalTheory.FREE or function.theory not in _THEORY_TO_BUILTIN:
                arity = len(function.parameter_sorts)
                fname = names[function.function_id]
                lines.append(f"functions: {fname}/{arity}")
        if protocol.functions:
            lines.append("")

        # Fresh names as free public names only when not private ~names in rules.
        for role in protocol.roles:
            role_name = names[role.role_id]
            lines.append(f"/* role {role_name} */")
            lines.append(
                f"rule Create_{role_name}:\n"
                f"  [ Fr(~id_{role_name}) ]\n"
                f"  --[ Create_{role_name}(~id_{role_name}) ]->\n"
                f"  [ St_{role_name}(~id_{role_name}) ]"
            )
            lines.append("")

        for event in protocol.events:
            event_name = names[event.event_id]
            args = ", ".join(
                _term_to_spthy(term, names) for term in event.parameters
            ) or "~unit"
            role_name = names.get(event.role_id, "Role")
            lines.append(
                f"rule Event_{event_name}:\n"
                f"  [ St_{role_name}(~id) ]\n"
                f"  --[ {event_name}({args}) ]->\n"
                f"  [ St_{role_name}(~id) ]"
            )
            lines.append("")

        claim_lemmas: dict[str, str] = {}
        for claim in protocol.claims:
            if claim.kind not in TAMARIN_SUPPORTED_CLAIMS:
                continue
            lemma = _safe_ident(claim.claim_id.replace(":", "_"), prefix="lemma")
            claim_lemmas[claim.claim_id] = lemma
            body = self._claim_formula(claim, names)
            lines.append(f"lemma {lemma}:")
            lines.append(f'  "{body}"')
            lines.append("")

        lines.append("end")
        lines.append("")
        source = "\n".join(lines)
        ceiling = self.disclose_ceiling(protocol)
        return TamarinCompileResult(
            source=source,
            source_format="spthy",
            source_digest=content_digest(source),
            ceiling=FrozenMap(ceiling),
            claim_lemmas=FrozenMap(claim_lemmas),
            equational_theories=tuple(item.value for item in theories),
            unsupported_claims=unsupported,
            protocol_document_id=protocol.document_id,
        )

    def _claim_formula(self, claim: ProtocolClaim, names: Mapping[str, str]) -> str:
        if claim.kind is ProtocolClaimKind.SECRECY:
            secrets = " & ".join(
                f"not (Ex #i. K({_term_to_spthy(term, names)}) @ i)"
                for term in claim.secret_terms
            )
            return secrets or "All #i. True"
        if claim.kind is ProtocolClaimKind.REACHABILITY:
            events = " & ".join(
                f"(Ex #i. {names.get(event_id, _safe_ident(event_id))}() @ i)"
                for event_id in claim.reachable_event_ids
            )
            return f"exists-trace\n    \"{events}\"" if events else "exists-trace\n    \"True\""
        if claim.kind in {
            ProtocolClaimKind.AUTHENTICATION,
            ProtocolClaimKind.CORRESPONDENCE,
        }:
            antecedent = claim.antecedent_event_ids[0]
            consequent = claim.consequent_event_ids[0]
            a_name = names.get(antecedent, _safe_ident(antecedent))
            c_name = names.get(consequent, _safe_ident(consequent))
            if claim.correspondence.value == "injective":
                return (
                    f"All x #i. {a_name}(x) @ i ==> "
                    f"(Ex #j. {c_name}(x) @ j & #j < #i) & "
                    f"(All #k. {a_name}(x) @ k ==> #i = #k)"
                )
            return (
                f"All x #i. {a_name}(x) @ i ==> "
                f"(Ex #j. {c_name}(x) @ j & #j < #i)"
            )
        raise TamarinBackendError(
            f"claim kind {claim.kind.value} is outside the Tamarin compiler ceiling"
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


class TamarinBackend:
    """Canonical Tamarin protocol backend implementing ``TamarinBackend@1``."""

    interface_version: Final = TAMARIN_BACKEND_VERSION
    backend_id: Final = "tamarin"
    aliases: Final = frozenset(
        {
            "tamarin-prover",
            "tamarin_prover",
            "protocol-tamarin",
        }
    )
    accepted_source_formats: Final = frozenset(
        {
            "spthy",
            "tamarin",
            "tamarin-source",
            "protocol-ir",
            "protocol_ir",
            "protocol",
        }
    )

    def __init__(
        self,
        *,
        backend_version: str = "tamarin-prover",
        executable: str = "tamarin-prover",
        maude_executable: str = "maude",
        maude_version: str = "",
        runner: BoundedToolRunner | None = None,
        version_probe: Callable[[], str] | None = None,
        maude_probe: Callable[[], str] | None = None,
        available_probe: Callable[[], bool] | None = None,
        compiler: TamarinCompiler | None = None,
        logic_families: Sequence[str] = (
            "cryptographic_protocol",
            "protocol",
            "protocol_logic",
            "tamarin",
            "software_verification",
        ),
    ) -> None:
        self.backend_version = _text(backend_version, "backend_version")
        self.executable = _text(executable, "executable")
        self.maude_executable = _text(maude_executable, "maude_executable")
        self.maude_version = _text(maude_version, "maude_version", optional=True)
        self._runner = runner or BoundedToolRunner()
        if not isinstance(self._runner, BoundedToolRunner):
            raise TamarinBackendError("runner must be a BoundedToolRunner")
        if version_probe is not None and not callable(version_probe):
            raise TamarinBackendError("version_probe must be callable")
        if maude_probe is not None and not callable(maude_probe):
            raise TamarinBackendError("maude_probe must be callable")
        if available_probe is not None and not callable(available_probe):
            raise TamarinBackendError("available_probe must be callable")
        self._version_probe = version_probe
        self._maude_probe = maude_probe
        self._available_probe = available_probe
        self._compiler = compiler or TamarinCompiler()
        if not isinstance(self._compiler, TamarinCompiler):
            raise TamarinBackendError("compiler must be a TamarinCompiler")
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

    def probe_toolchain(self) -> TamarinToolchainBinding:
        tool_version = self.backend_version
        if self._version_probe is not None:
            probed = self._version_probe()
            if probed:
                tool_version = _text(str(probed).splitlines()[0], "tool_version")
        maude_version = self.maude_version
        if self._maude_probe is not None:
            probed_maude = self._maude_probe()
            if probed_maude:
                maude_version = _text(
                    str(probed_maude).splitlines()[0], "maude_version", optional=True
                )
        return TamarinToolchainBinding(
            tool_id="tamarin-prover",
            executable=self.executable,
            tool_version=tool_version,
            dependencies=(
                ToolDependencyBinding(
                    dependency_id="dep:maude",
                    name="maude",
                    version=maude_version or "unspecified",
                    required=True,
                ),
            ),
        )

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise TamarinBackendError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise TamarinBackendError(
                f"request targets {request.requested_backend_id!r}, not {self.backend_id!r}"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise TamarinBackendError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.THEOREM_PROOF:
            raise TamarinBackendError(
                "Tamarin backend answers theorem_proof queries for protocol claims"
            )

    def _compile_request(self, request: BackendRequest) -> TamarinCompileResult:
        payload = request.payload.to_dict()
        encoding = str(
            payload.get("encoding")
            or payload.get("source_format")
            or "protocol-ir"
        ).strip().lower()
        if encoding not in self.accepted_source_formats:
            raise TamarinBackendError(
                f"request encoding {encoding!r} is not a supported Tamarin format"
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
            payload.get("spthy")
            or payload.get("source")
            or payload.get("tamarin")
            or payload.get("model")
        )
        if isinstance(source, str) and source.strip():
            return self._compiler.compile_source(
                source,
                source_format="spthy" if encoding in {"protocol-ir", "protocol_ir", "protocol"} else encoding,
            )
        raise TamarinBackendError(
            "Tamarin request payload requires protocol_ir or spthy/source text"
        )

    def _tool_request(self, source: str, bounds: ExecutionBounds) -> ToolRunRequest:
        max_workspace_bytes = max(
            bounds.max_output_bytes * 2,
            len(source.encode("utf-8")) + bounds.max_output_bytes + 1024,
        )
        return ToolRunRequest(
            argv=(
                self.executable,
                "--prove",
                "{workspace}/protocol.spthy",
            ),
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(
                timeout_seconds=bounds.timeout_ms / 1000,
                cpu_seconds=bounds.timeout_ms / 1000,
                memory_bytes=bounds.max_memory_bytes,
                max_output_bytes=bounds.max_output_bytes,
                max_input_bytes=bounds.max_output_bytes,
                max_workspace_bytes=max_workspace_bytes,
            ),
            input_files={"protocol.spthy": source},
        )

    def _build_result(
        self,
        *,
        request: BackendRequest,
        binding: TamarinSourceBinding,
        status: ResultStatus,
        usage: ResourceUsage,
        receipt: TamarinProtocolReceipt,
        compile_result: TamarinCompileResult,
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
                "adapter_interface": TAMARIN_BACKEND_VERSION,
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
    ) -> TamarinBackendOutcome:
        self._validate_request(request)
        compile_result = self._compile_request(request)
        binding = TamarinSourceBinding.bind(
            request, compile_result.source, compile_result.source_format
        )
        toolchain = self.probe_toolchain()
        usage = ResourceUsage()

        if compile_result.unsupported_claims:
            quarantine = ResultQuarantine(
                reason=QuarantineReason.UNSUPPORTED_CLAIM,
                detail=(
                    "protocol contains claims outside the Tamarin symbolic ceiling: "
                    + ", ".join(compile_result.unsupported_claims)
                ),
                claim_ids=compile_result.unsupported_claims,
            )
            receipt = TamarinProtocolReceipt(
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
            return TamarinBackendOutcome(
                request_digest=request.digest,
                source_binding=binding,
                result=result,
                receipt=receipt,
                compile_result=compile_result,
            )

        if not self.is_available():
            reason = (
                f"Tamarin executable {self.executable!r} is not available; "
                "Maude-backed symbolic protocol analysis cannot run"
            )
            receipt = TamarinProtocolReceipt(
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
            return TamarinBackendOutcome(
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
            reason = process.error or "Tamarin became unavailable during execution"
            status = ResultStatus.UNAVAILABLE
            outcomes: tuple[ClaimOutcome, ...] = ()
            quarantine = None
            accepted = False
        elif process.cancelled:
            reason = process.error or "Tamarin execution was cancelled"
            status = ResultStatus.ERROR
            outcomes = ()
            quarantine = None
            accepted = False
        elif process.timed_out:
            reason = process.error or "Tamarin exceeded its wall-clock bound"
            status = ResultStatus.TIMEOUT
            outcomes = ()
            quarantine = ResultQuarantine(
                reason=QuarantineReason.INCONCLUSIVE,
                detail=reason,
            )
            accepted = False
        elif process.resource_exhausted or process.output_truncated:
            reason = process.error or "Tamarin exceeded a resource or output bound"
            status = ResultStatus.ERROR
            outcomes = ()
            quarantine = None
            accepted = False
        else:
            outcomes = parse_tamarin_claim_outcomes(
                process.stdout,
                process.stderr,
                claim_lemmas=compile_result.claim_lemmas.to_dict(),
            )
            status, quarantine, accepted = classify_claim_outcomes(outcomes)
            reason = process.error or ""
            if process.returncode not in (0, None) and status is ResultStatus.SECURE:
                # Non-zero exit with all-verified is treated as inconclusive.
                status = ResultStatus.UNKNOWN
                accepted = False
                quarantine = ResultQuarantine(
                    reason=QuarantineReason.INCONCLUSIVE,
                    detail=(
                        f"Tamarin exited with status {process.returncode} despite "
                        "verified lemmas; quarantined"
                    ),
                )
                reason = quarantine.detail

        diagnostics = bound_diagnostics(
            [
                *( [process.error] if process.error else [] ),
                *( [reason] if reason else [] ),
                *(
                    [quarantine.detail]
                    if quarantine is not None
                    else []
                ),
            ]
        )
        receipt = TamarinProtocolReceipt(
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
        return TamarinBackendOutcome(
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
    "QuarantineReason",
    "ResultQuarantine",
    "SymbolicModelCeiling",
    "TAMARIN_BACKEND_VERSION",
    "TamarinBackend",
    "TamarinBackendError",
    "TamarinBackendOutcome",
    "TamarinCompileResult",
    "TamarinCompiler",
    "TamarinProtocolReceipt",
    "TamarinSourceBinding",
    "TamarinToolchainBinding",
    "ToolDependencyBinding",
    "bound_diagnostics",
    "classify_claim_outcomes",
    "content_digest",
    "parse_attack_trace",
    "parse_tamarin_claim_outcomes",
    "sanitize_diagnostic",
]
