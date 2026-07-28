"""Side-effect-free intent authorization service (LIG-035).

Interface: ``IntentAuthorizationService@1``

Composes the public gate / corpus / composer / portfolio / receipt leaves into
one deterministic source-to-decision API.  Evaluation is pure with respect to
the corpus and environment:

* never executes source content or tools;
* never installs backends;
* never mutates a proof corpus;
* never authorizes simulated evidence under production profiles;
* never derives a capability from a non-allow decision; and
* never converts exceptions into allow.

Offline unit tests inject normalizers, intent lowerers, evidence selectors,
verifiers, portfolio solvers, and clocks through
:class:`OfflineAuthorizationDependencies`.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ..intent_ir.invocation.model import (
    InvocationEnvelopeValidationError,
    InvocationIntentEnvelope,
    validate_invocation_envelope,
)
from ..ir_core.claims import FrozenMap, stable_digest
from .compose import (
    ActionScope,
    AuthorizationDecision,
    AuthorizationDecisionPolicy,
    AuthorizationQueryBundle,
    AuthorizationQueryComposer,
    ComposeError,
    InternalDecisionStatus,
    compose_authorization_query,
    evaluate_authorization_decision,
    map_internal_to_wire,
)
from .portfolio import (
    AuthorizationPortfolio,
    JobSolver,
    PortfolioAttemptRecord,
    PortfolioError,
    PortfolioRunResult,
)
from .profiles import (
    AdmissibilityProfile,
    AdmissibilityProfileId,
    resolve_profile_fail_closed,
)
from .reasons import AdmissibilityStatus
from .receipt import (
    AuthorizationCapability,
    BoundContext,
    BoundRoots,
    CapabilityDerivationError,
    DecisionReceipt,
    ReceiptError,
    build_decision_receipt,
    derive_capability,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

INTENT_AUTHORIZATION_SERVICE_INTERFACE: Final = "IntentAuthorizationService@1"
INTENT_AUTHORIZATION_SERVICE_SCHEMA_VERSION: Final = (
    "intent-authorization-service/v1"
)
AUTHORIZATION_BUDGET_SCHEMA_VERSION: Final = "authorization-budget/v1"
AUTHORIZATION_TRACE_SCHEMA_VERSION: Final = "authorization-service-trace/v1"
AUTHORIZATION_RESULT_SCHEMA_VERSION: Final = "authorization-service-result/v1"
INTENT_LOWER_RESULT_SCHEMA_VERSION: Final = "intent-lower-result/v1"
EVIDENCE_SELECTION_SCHEMA_VERSION: Final = "authorization-evidence-selection/v1"

DEFAULT_PRODUCER_ID: Final = "producer:intent-authorization-service-v1"
DEFAULT_RECEIPT_TTL_SECONDS: Final = 600
DEFAULT_CAPABILITY_TTL_SECONDS: Final = 120

MAX_DIAGNOSTICS: Final = 1_024
MAX_IDENTIFIER_CHARS: Final = 256
MAX_REASON_CHARS: Final = 512

# Stage vocabulary preserved on every evaluation trace.
class AuthorizationStage(str, Enum):
    """Ordered pipeline stages recorded on the service trace."""

    VALIDATE = "validate"
    NORMALIZE = "normalize"
    LOWER = "lower"
    EVIDENCE = "evidence"
    COMPOSE = "compose"
    PORTFOLIO = "portfolio"
    DECIDE = "decide"
    RECEIPT = "receipt"
    CAPABILITY = "capability"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorizationServiceError(ValueError):
    """Raised when the authorization service fails closed."""


class AuthorizationCancelled(AuthorizationServiceError):
    """Raised (or mapped) when evaluation is cancelled mid-pipeline."""


class AuthorizationBudgetError(AuthorizationServiceError):
    """Raised when a budget is invalid or a forbidden side effect is requested."""


class AuthorizationRootError(AuthorizationServiceError):
    """Raised when policy / corpus / revocation roots fail validation."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise AuthorizationServiceError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise AuthorizationServiceError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise AuthorizationServiceError(f"{name} must not have surrounding whitespace")
    if len(value) > MAX_REASON_CHARS * 8 and name.endswith(
        ("_id", "root", "ref", "cid")
    ):
        raise AuthorizationServiceError(f"{name} exceeds maximum length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, allow_empty=False)
    if len(text) > MAX_IDENTIFIER_CHARS:
        raise AuthorizationServiceError(f"{name} exceeds maximum length")
    return text


def _optional_identifier(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, name)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorizationServiceError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AuthorizationServiceError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _unique_sorted(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise AuthorizationServiceError(f"{name} must be a sequence of strings")
    items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise AuthorizationServiceError(f"{name} must be unique")
    return tuple(sorted(items))


def _positive_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorizationServiceError(f"{name} must be an integer")
    if value < minimum:
        raise AuthorizationServiceError(f"{name} must be >= {minimum}")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise AuthorizationServiceError(f"{name} must be a bool")
    return value


def _bare_digest(value: str) -> str:
    """Normalize sha256 digests to bare lowercase hex (64 chars)."""

    text = value.strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        # Fall back to a stable digest of the original string so bound context
        # always has a valid digest field (request digests from envelopes may
        # already be bare or tagged).
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return text


def _ensure_bare_digest(value: str, *, fallback_seed: str = "") -> str:
    text = (value or "").strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
        return text
    seed = fallback_seed or value or "empty"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_iso8601(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _add_seconds_iso(base: str, seconds: int) -> str:
    dt = _parse_iso8601(base)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        (dt + timedelta(seconds=seconds))
        .astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _unique_diagnostics(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
        if len(ordered) >= MAX_DIAGNOSTICS:
            break
    return tuple(ordered)


# ---------------------------------------------------------------------------
# Budget and cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationBudget:
    """Resource and safety bounds for one authorization evaluation.

    Forbidden side-effect flags must remain false.  Setting any of
    ``allow_network``, ``allow_install``, ``allow_corpus_mutation``, or
    ``allow_tool_execution`` to true fails closed at validation time.
    """

    max_candidates: int = 64
    selection_budget: int = 16
    max_solver_attempts: int = 32
    timeout_ms: int = 30_000
    max_bytes: int = 8_000_000
    max_graph_depth: int = 8
    receipt_ttl_seconds: int = DEFAULT_RECEIPT_TTL_SECONDS
    capability_ttl_seconds: int = DEFAULT_CAPABILITY_TTL_SECONDS
    allow_network: bool = False
    allow_install: bool = False
    allow_corpus_mutation: bool = False
    allow_tool_execution: bool = False
    # When true, simulated evidence cannot authorize (production default).
    production_mode: bool = True
    schema_version: str = AUTHORIZATION_BUDGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_candidates",
            _positive_int(self.max_candidates, "max_candidates", minimum=1),
        )
        object.__setattr__(
            self,
            "selection_budget",
            _positive_int(self.selection_budget, "selection_budget", minimum=1),
        )
        object.__setattr__(
            self,
            "max_solver_attempts",
            _positive_int(
                self.max_solver_attempts, "max_solver_attempts", minimum=0
            ),
        )
        object.__setattr__(
            self,
            "timeout_ms",
            _positive_int(self.timeout_ms, "timeout_ms", minimum=1),
        )
        object.__setattr__(
            self,
            "max_bytes",
            _positive_int(self.max_bytes, "max_bytes", minimum=1),
        )
        object.__setattr__(
            self,
            "max_graph_depth",
            _positive_int(self.max_graph_depth, "max_graph_depth", minimum=1),
        )
        object.__setattr__(
            self,
            "receipt_ttl_seconds",
            _positive_int(
                self.receipt_ttl_seconds, "receipt_ttl_seconds", minimum=1
            ),
        )
        object.__setattr__(
            self,
            "capability_ttl_seconds",
            _positive_int(
                self.capability_ttl_seconds, "capability_ttl_seconds", minimum=1
            ),
        )
        for flag in (
            "allow_network",
            "allow_install",
            "allow_corpus_mutation",
            "allow_tool_execution",
            "production_mode",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != AUTHORIZATION_BUDGET_SCHEMA_VERSION:
            raise AuthorizationBudgetError(
                f"unsupported budget schema: {self.schema_version!r}"
            )

    def validate_side_effect_flags(self) -> None:
        """Fail closed if the budget requests a forbidden side effect."""

        if self.allow_network:
            raise AuthorizationBudgetError(
                "authorization budget forbids network (allow_network must be false)"
            )
        if self.allow_install:
            raise AuthorizationBudgetError(
                "authorization budget forbids backend installation "
                "(allow_install must be false)"
            )
        if self.allow_corpus_mutation:
            raise AuthorizationBudgetError(
                "authorization budget forbids corpus mutation "
                "(allow_corpus_mutation must be false)"
            )
        if self.allow_tool_execution:
            raise AuthorizationBudgetError(
                "authorization budget forbids tool/content execution "
                "(allow_tool_execution must be false)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_corpus_mutation": self.allow_corpus_mutation,
            "allow_install": self.allow_install,
            "allow_network": self.allow_network,
            "allow_tool_execution": self.allow_tool_execution,
            "capability_ttl_seconds": self.capability_ttl_seconds,
            "max_bytes": self.max_bytes,
            "max_candidates": self.max_candidates,
            "max_graph_depth": self.max_graph_depth,
            "max_solver_attempts": self.max_solver_attempts,
            "production_mode": self.production_mode,
            "receipt_ttl_seconds": self.receipt_ttl_seconds,
            "schema_version": self.schema_version,
            "selection_budget": self.selection_budget,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "AuthorizationBudget":
        if value is None:
            return cls()
        value = _mapping(value, "authorization budget")
        _reject_unknown(
            value,
            frozenset(
                {
                    "allow_corpus_mutation",
                    "allow_install",
                    "allow_network",
                    "allow_tool_execution",
                    "capability_ttl_seconds",
                    "max_bytes",
                    "max_candidates",
                    "max_graph_depth",
                    "max_solver_attempts",
                    "production_mode",
                    "receipt_ttl_seconds",
                    "schema_version",
                    "selection_budget",
                    "timeout_ms",
                }
            ),
            "authorization budget",
        )
        return cls(
            max_candidates=int(value.get("max_candidates", 64)),
            selection_budget=int(value.get("selection_budget", 16)),
            max_solver_attempts=int(value.get("max_solver_attempts", 32)),
            timeout_ms=int(value.get("timeout_ms", 30_000)),
            max_bytes=int(value.get("max_bytes", 8_000_000)),
            max_graph_depth=int(value.get("max_graph_depth", 8)),
            receipt_ttl_seconds=int(
                value.get("receipt_ttl_seconds", DEFAULT_RECEIPT_TTL_SECONDS)
            ),
            capability_ttl_seconds=int(
                value.get(
                    "capability_ttl_seconds", DEFAULT_CAPABILITY_TTL_SECONDS
                )
            ),
            allow_network=bool(value.get("allow_network", False)),
            allow_install=bool(value.get("allow_install", False)),
            allow_corpus_mutation=bool(
                value.get("allow_corpus_mutation", False)
            ),
            allow_tool_execution=bool(
                value.get("allow_tool_execution", False)
            ),
            production_mode=bool(value.get("production_mode", True)),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_BUDGET_SCHEMA_VERSION
            ),
        )


@dataclass
class CancellationToken:
    """Cooperative cancellation token for long-running evaluations.

    Checking a cancelled token raises :class:`AuthorizationCancelled`.  The
    service maps cancellation to a non-allow decision and never promotes it
    to allow.
    """

    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "cancelled") -> None:
        self.cancelled = True
        self.reason = reason or "cancelled"

    def check(self, stage: str = "") -> None:
        if self.cancelled:
            label = self.reason or "cancelled"
            if stage:
                raise AuthorizationCancelled(
                    f"authorization cancelled at stage {stage}: {label}"
                )
            raise AuthorizationCancelled(f"authorization cancelled: {label}")

    def to_dict(self) -> dict[str, Any]:
        return {"cancelled": self.cancelled, "reason": self.reason}


# ---------------------------------------------------------------------------
# Intent lowering and evidence selection results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentLowerResult:
    """Result of lowering a canonical invocation into Intent formal inputs.

    Lowering is pure: adapters must not execute skill/prompt/tool content.
    """

    intent_cid: str
    intent_document_id: str = ""
    formalization_artifact_id: str = ""
    actions: tuple[ActionScope, ...] = ()
    native_views: tuple[Any, ...] = ()
    cross_view_links: tuple[Any, ...] = ()
    constraint_artifacts: tuple[Any, ...] = ()
    assumptions: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    schema_version: str = INTENT_LOWER_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_cid", _text(self.intent_cid, "intent_cid")
        )
        object.__setattr__(
            self,
            "intent_document_id",
            _optional_identifier(
                self.intent_document_id, "intent_document_id"
            ),
        )
        object.__setattr__(
            self,
            "formalization_artifact_id",
            _optional_identifier(
                self.formalization_artifact_id, "formalization_artifact_id"
            ),
        )
        actions = tuple(
            item
            if isinstance(item, ActionScope)
            else ActionScope.from_dict(_mapping(item, "action"))
            for item in self.actions
        )
        object.__setattr__(self, "actions", actions)
        object.__setattr__(
            self,
            "assumptions",
            _unique_sorted(self.assumptions, "assumptions"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_diagnostics(tuple(self.diagnostics)),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != INTENT_LOWER_RESULT_SCHEMA_VERSION:
            raise AuthorizationServiceError(
                f"unsupported intent-lower schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "assumptions": list(self.assumptions),
            "diagnostics": list(self.diagnostics),
            "formalization_artifact_id": self.formalization_artifact_id,
            "intent_cid": self.intent_cid,
            "intent_document_id": self.intent_document_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EvidenceSelectionResult:
    """Hard-filtered, selected, and verified evidence for one evaluation.

    Simulated evidence rejected under production mode is recorded on
    ``simulated_rejected`` and never contributes to selected CIDs used for
    allow decisions.
    """

    legal_evidence_cids: tuple[str, ...] = ()
    security_evidence_cids: tuple[str, ...] = ()
    intent_evidence_cids: tuple[str, ...] = ()
    selected_evidence_cids: tuple[str, ...] = ()
    rejected_cids: tuple[str, ...] = ()
    simulated_rejected: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    verification_passed: bool = True
    audit_digest: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = EVIDENCE_SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "legal_evidence_cids",
            _unique_sorted(self.legal_evidence_cids, "legal_evidence_cids"),
        )
        object.__setattr__(
            self,
            "security_evidence_cids",
            _unique_sorted(
                self.security_evidence_cids, "security_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "intent_evidence_cids",
            _unique_sorted(self.intent_evidence_cids, "intent_evidence_cids"),
        )
        object.__setattr__(
            self,
            "selected_evidence_cids",
            _unique_sorted(
                self.selected_evidence_cids, "selected_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "rejected_cids",
            _unique_sorted(self.rejected_cids, "rejected_cids"),
        )
        object.__setattr__(
            self,
            "simulated_rejected",
            _unique_sorted(self.simulated_rejected, "simulated_rejected"),
        )
        object.__setattr__(
            self, "gaps", _unique_sorted(self.gaps, "gaps")
        )
        object.__setattr__(
            self,
            "verification_passed",
            _bool(self.verification_passed, "verification_passed"),
        )
        object.__setattr__(
            self,
            "audit_digest",
            _optional_text(self.audit_digest, "audit_digest"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_diagnostics(tuple(self.diagnostics)),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != EVIDENCE_SELECTION_SCHEMA_VERSION:
            raise AuthorizationServiceError(
                f"unsupported evidence-selection schema: {self.schema_version!r}"
            )

    @property
    def all_selected(self) -> tuple[str, ...]:
        if self.selected_evidence_cids:
            return self.selected_evidence_cids
        return tuple(
            sorted(
                set(self.legal_evidence_cids)
                | set(self.security_evidence_cids)
                | set(self.intent_evidence_cids)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_digest": self.audit_digest,
            "diagnostics": list(self.diagnostics),
            "gaps": list(self.gaps),
            "intent_evidence_cids": list(self.intent_evidence_cids),
            "legal_evidence_cids": list(self.legal_evidence_cids),
            "rejected_cids": list(self.rejected_cids),
            "schema_version": self.schema_version,
            "security_evidence_cids": list(self.security_evidence_cids),
            "selected_evidence_cids": list(self.selected_evidence_cids),
            "simulated_rejected": list(self.simulated_rejected),
            "verification_passed": self.verification_passed,
        }


# ---------------------------------------------------------------------------
# Offline injectable dependencies
# ---------------------------------------------------------------------------


@runtime_checkable
class IntentLowerer(Protocol):
    """Pure Intent lowering adapter (envelope → formal inputs)."""

    def __call__(
        self, envelope: InvocationIntentEnvelope
    ) -> IntentLowerResult | Mapping[str, Any]: ...


@runtime_checkable
class EvidenceSelector(Protocol):
    """Hard-filter / select evidence under exact roots (offline injectable)."""

    def __call__(
        self,
        envelope: InvocationIntentEnvelope,
        *,
        roots: BoundRoots,
        budget: AuthorizationBudget,
        profile: AdmissibilityProfile,
        intent: IntentLowerResult,
    ) -> EvidenceSelectionResult | Mapping[str, Any]: ...


@runtime_checkable
class EvidenceVerifier(Protocol):
    """Independent verification of selected evidence (offline injectable)."""

    def __call__(
        self,
        selection: EvidenceSelectionResult,
        *,
        roots: BoundRoots,
        budget: AuthorizationBudget,
        profile: AdmissibilityProfile,
    ) -> EvidenceSelectionResult | Mapping[str, Any]: ...


@runtime_checkable
class EnvelopeNormalizer(Protocol):
    """Normalize a non-canonical source into an InvocationIntentEnvelope."""

    def __call__(
        self, source: Any
    ) -> InvocationIntentEnvelope | Mapping[str, Any]: ...


@dataclass
class OfflineAuthorizationDependencies:
    """Injected offline dependencies for deterministic unit / replay tests.

    None of these callables may execute tools, install packages, or mutate a
    live corpus.  Side-effect attempts should be recorded on
    ``side_effect_log`` by fakes so tests can assert the service never
    requests them.
    """

    normalizer: EnvelopeNormalizer | None = None
    intent_lowerer: IntentLowerer | None = None
    evidence_selector: EvidenceSelector | None = None
    evidence_verifier: EvidenceVerifier | None = None
    portfolio_solver: JobSolver | None = None
    precomputed_attempts: Sequence[PortfolioAttemptRecord | Mapping[str, Any]] | None = (
        None
    )
    portfolio: AuthorizationPortfolio | None = None
    decision_policy: AuthorizationDecisionPolicy | None = None
    composer: AuthorizationQueryComposer | None = None
    which: Callable[[str], str | None] | None = None
    version_probe: Callable[[str], str] | None = None
    clock: Callable[[], str] | None = None
    # Mutable observation log for adversarial side-effect tests.
    side_effect_log: list[str] = field(default_factory=list)
    # Optional explicit pre-selected evidence (skips selector).
    preselected_evidence: EvidenceSelectionResult | Mapping[str, Any] | None = None
    # Optional explicit lowered intent (skips lowerer when provided).
    pre_lowered_intent: IntentLowerResult | Mapping[str, Any] | None = None

    def record_side_effect(self, label: str) -> None:
        self.side_effect_log.append(label)

    def now(self) -> str:
        if self.clock is not None:
            return self.clock()
        return _utc_now_iso()


# ---------------------------------------------------------------------------
# Trace and service result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationServiceTrace:
    """Deterministic evaluation trace and diagnostics for one request."""

    stages: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    stage_details: FrozenMap = field(default_factory=FrozenMap)
    cancelled: bool = False
    exception_type: str = ""
    exception_message: str = ""
    elapsed_ms: int = 0
    schema_version: str = AUTHORIZATION_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stages", tuple(str(item) for item in self.stages)
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_diagnostics(tuple(self.diagnostics)),
        )
        object.__setattr__(
            self,
            "stage_details",
            self.stage_details
            if isinstance(self.stage_details, FrozenMap)
            else FrozenMap(self.stage_details),
        )
        object.__setattr__(
            self, "cancelled", _bool(self.cancelled, "cancelled")
        )
        object.__setattr__(
            self,
            "exception_type",
            _optional_text(self.exception_type, "exception_type"),
        )
        object.__setattr__(
            self,
            "exception_message",
            _optional_text(self.exception_message, "exception_message"),
        )
        object.__setattr__(
            self,
            "elapsed_ms",
            _positive_int(self.elapsed_ms, "elapsed_ms", minimum=0),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != AUTHORIZATION_TRACE_SCHEMA_VERSION:
            raise AuthorizationServiceError(
                f"unsupported trace schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": self.cancelled,
            "diagnostics": list(self.diagnostics),
            "elapsed_ms": self.elapsed_ms,
            "exception_message": self.exception_message,
            "exception_type": self.exception_type,
            "schema_version": self.schema_version,
            "stage_details": self.stage_details.to_dict(),
            "stages": list(self.stages),
        }


@dataclass(frozen=True, slots=True)
class AuthorizationServiceResult:
    """Typed result of :meth:`IntentAuthorizationService.evaluate`.

    Compatibility status is the legacy wire ``AdmissibilityStatus``; the
    richer internal decision lives on ``decision`` and ``status``.
    """

    status: InternalDecisionStatus
    wire_status: AdmissibilityStatus
    reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    decision: AuthorizationDecision | None = None
    receipt: DecisionReceipt | None = None
    capability: AuthorizationCapability | None = None
    envelope: InvocationIntentEnvelope | None = None
    bundle: AuthorizationQueryBundle | None = None
    portfolio_run: PortfolioRunResult | None = None
    evidence: EvidenceSelectionResult | None = None
    intent_lower: IntentLowerResult | None = None
    roots: BoundRoots | None = None
    context: BoundContext | None = None
    trace: AuthorizationServiceTrace = field(
        default_factory=AuthorizationServiceTrace
    )
    profile_id: str = ""
    producer_id: str = DEFAULT_PRODUCER_ID
    interface: str = INTENT_AUTHORIZATION_SERVICE_INTERFACE
    schema_version: str = AUTHORIZATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        status = self.status
        if not isinstance(status, InternalDecisionStatus):
            status = InternalDecisionStatus(status)
        object.__setattr__(self, "status", status)
        wire = self.wire_status
        if not isinstance(wire, AdmissibilityStatus):
            wire = AdmissibilityStatus(wire)
        expected = map_internal_to_wire(status)
        if wire is not expected:
            raise AuthorizationServiceError(
                f"wire_status {wire.value!r} inconsistent with status "
                f"{status.value!r} (expected {expected.value!r})"
            )
        object.__setattr__(self, "wire_status", wire)
        object.__setattr__(
            self, "reasons", _unique_sorted(self.reasons, "reasons")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "profile_id",
            _optional_text(self.profile_id, "profile_id"),
        )
        object.__setattr__(
            self,
            "producer_id",
            _text(self.producer_id, "producer_id"),
        )
        if self.interface != INTENT_AUTHORIZATION_SERVICE_INTERFACE:
            raise AuthorizationServiceError(
                f"unsupported service interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_RESULT_SCHEMA_VERSION:
            raise AuthorizationServiceError(
                f"unsupported service result schema: {self.schema_version!r}"
            )
        # Hard safety: never claim allow when capability is present for non-allow.
        if self.capability is not None and not self.is_allow:
            raise AuthorizationServiceError(
                "capability present on non-allow result (fail closed)"
            )
        if self.status is InternalDecisionStatus.ALLOW and self.decision is not None:
            if not self.decision.is_allow:
                raise AuthorizationServiceError(
                    "result status allow but decision is not allow"
                )

    @property
    def is_allow(self) -> bool:
        return self.status is InternalDecisionStatus.ALLOW

    @property
    def is_deny(self) -> bool:
        return self.status is InternalDecisionStatus.DENY

    @property
    def compatibility_status(self) -> AdmissibilityStatus:
        """Legacy allow / reject / abstain wire status."""

        return self.wire_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle": None if self.bundle is None else self.bundle.to_dict(),
            "capability": (
                None if self.capability is None else self.capability.to_dict()
            ),
            "context": None if self.context is None else self.context.to_dict(),
            "decision": (
                None if self.decision is None else self.decision.to_dict()
            ),
            "envelope": (
                None if self.envelope is None else self.envelope.to_dict()
            ),
            "evidence": (
                None if self.evidence is None else self.evidence.to_dict()
            ),
            "intent_lower": (
                None
                if self.intent_lower is None
                else self.intent_lower.to_dict()
            ),
            "interface": self.interface,
            "portfolio_run": (
                None
                if self.portfolio_run is None
                else self.portfolio_run.to_dict()
            ),
            "producer_id": self.producer_id,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "roots": None if self.roots is None else self.roots.to_dict(),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "trace": self.trace.to_dict(),
            "wire_status": self.wire_status.value,
        }


# ---------------------------------------------------------------------------
# Mutable trace builder (internal)
# ---------------------------------------------------------------------------


class _TraceBuilder:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self.diagnostics: list[str] = []
        self.details: dict[str, Any] = {}
        self.cancelled = False
        self.exception_type = ""
        self.exception_message = ""
        self.started = time.monotonic()

    def stage(self, stage: AuthorizationStage | str, **detail: Any) -> None:
        name = stage.value if isinstance(stage, AuthorizationStage) else str(stage)
        self.stages.append(name)
        if detail:
            self.details[name] = dict(detail)
        self.diagnostics.append(f"auth.service.stage:{name}")

    def note(self, *messages: str) -> None:
        for message in messages:
            if message:
                self.diagnostics.append(message)

    def fail(self, exc: BaseException) -> None:
        self.exception_type = type(exc).__name__
        self.exception_message = str(exc) or type(exc).__name__
        self.stage(AuthorizationStage.ERROR, exception_type=self.exception_type)

    def build(self) -> AuthorizationServiceTrace:
        elapsed = int((time.monotonic() - self.started) * 1000)
        return AuthorizationServiceTrace(
            stages=tuple(self.stages),
            diagnostics=_unique_diagnostics(self.diagnostics),
            stage_details=FrozenMap(self.details),
            cancelled=self.cancelled,
            exception_type=self.exception_type,
            exception_message=self.exception_message,
            elapsed_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Root / context / action helpers
# ---------------------------------------------------------------------------


def _resolve_roots(
    *,
    envelope: InvocationIntentEnvelope,
    policy_ref: str = "",
    legal_corpus_ref: str = "",
    security_corpus_ref: str = "",
    intent_corpus_ref: str = "",
    revocation_root: str = "",
    circuit_roots: Sequence[str] = (),
    vk_roots: Sequence[str] = (),
) -> BoundRoots:
    """Validate and bind exact policy / corpus / revocation roots."""

    policy = _optional_text(policy_ref, "policy_ref") or envelope.policy.policy_root
    if not policy:
        raise AuthorizationRootError(
            "policy_root is required (policy_ref or envelope.policy.policy_root)"
        )

    corpus: list[str] = []
    for ref in (
        legal_corpus_ref,
        security_corpus_ref,
        intent_corpus_ref,
    ):
        text = _optional_text(ref, "corpus_ref")
        if text:
            corpus.append(text)
    if not corpus:
        corpus.extend(envelope.policy.corpus_roots)
    if not corpus:
        raise AuthorizationRootError(
            "at least one corpus root is required "
            "(legal/security/intent refs or envelope.policy.corpus_roots)"
        )

    rev = (
        _optional_text(revocation_root, "revocation_root")
        or envelope.policy.revocation_root
    )
    # Empty revocation is allowed only when explicitly empty on both sides;
    # production profiles still bind the empty string (fail-closed consumers
    # revalidate at dispatch).
    return BoundRoots(
        policy_root=policy,
        corpus_roots=tuple(corpus),
        revocation_root=rev,
        circuit_roots=tuple(circuit_roots),
        vk_roots=tuple(vk_roots),
    )


def bound_context_from_envelope(
    envelope: InvocationIntentEnvelope,
    *,
    environment: Mapping[str, Any] | None = None,
) -> BoundContext:
    """Project a validated envelope into a receipt :class:`BoundContext`."""

    env_digest = ""
    env_id = ""
    if environment:
        env_id = _optional_identifier(
            environment.get("environment_id", ""), "environment_id"
        )
        raw_digest = environment.get("environment_digest") or environment.get(
            "snapshot_digest", ""
        )
        if raw_digest:
            env_digest = _ensure_bare_digest(str(raw_digest))
        else:
            env_digest = stable_digest(dict(environment))
    else:
        env_id = envelope.environment.environment_id
        raw = envelope.environment.snapshot_digest
        if raw:
            env_digest = _ensure_bare_digest(raw)
        elif envelope.environment.environment_id or envelope.environment.facts:
            env_digest = stable_digest(envelope.environment.to_dict())

    effects = tuple(entry.value for entry in envelope.scope.effects)
    if not effects:
        # Fall back to action values as effect placeholders when only actions
        # are declared — still exact-bound.
        effects = tuple(entry.value for entry in envelope.scope.actions)
    resources = tuple(entry.value for entry in envelope.scope.resources)
    capabilities = tuple(entry.value for entry in envelope.scope.capabilities)
    delegation_ids = tuple(link.link_id for link in envelope.delegation)
    delegation_digest = ""
    if envelope.delegation:
        delegation_digest = stable_digest(
            [link.to_dict() for link in envelope.delegation]
        )

    return BoundContext(
        request_digest=_ensure_bare_digest(
            envelope.digest, fallback_seed=envelope.envelope_id
        ),
        arguments_digest=_ensure_bare_digest(
            envelope.arguments.commitment,
            fallback_seed=envelope.envelope_id + ":args",
        ),
        actor_id=envelope.actor.actor_id,
        audience_id=envelope.audience.audience_id,
        tool_id=envelope.tool.tool_id,
        tool_version=envelope.tool.tool_version,
        effect_ids=effects,
        environment_digest=env_digest,
        environment_id=env_id,
        delegation_ids=delegation_ids,
        delegation_digest=delegation_digest,
        resource_ids=resources,
        capability_ids=capabilities,
        nonce=envelope.nonce,
        metadata=FrozenMap(
            {
                "envelope_id": envelope.envelope_id,
                "tenant_id": envelope.tenant_id,
                "trace_id": envelope.trace_id,
            }
        ),
    )


def action_scopes_from_envelope(
    envelope: InvocationIntentEnvelope,
    *,
    logic_family: str = "first_order",
    domain: str = "intent",
) -> tuple[ActionScope, ...]:
    """Derive authorization action scopes from the envelope scope."""

    resources = tuple(entry.value for entry in envelope.scope.resources)
    capabilities = tuple(entry.value for entry in envelope.scope.capabilities)
    effects = list(envelope.scope.effects)
    actions = list(envelope.scope.actions)

    scopes: list[ActionScope] = []
    if actions:
        for index, action in enumerate(actions):
            effect_value = ""
            if index < len(effects):
                effect_value = effects[index].value
            elif len(effects) == 1:
                effect_value = effects[0].value
            scopes.append(
                ActionScope(
                    action_id=action.value,
                    effect_id=effect_value,
                    resource_ids=resources,
                    capability_ids=capabilities,
                    domain=domain,
                    logic_family=logic_family,
                    statement=action.description
                    or f"Authorize {action.value}",
                )
            )
    elif effects:
        for effect in effects:
            scopes.append(
                ActionScope(
                    action_id=effect.value,
                    effect_id=effect.value,
                    resource_ids=resources,
                    capability_ids=capabilities,
                    domain=domain,
                    logic_family=logic_family,
                    statement=effect.description
                    or f"Authorize {effect.value}",
                )
            )
    else:
        # Fail closed: no declared action/effect is not an implicit allow.
        raise AuthorizationServiceError(
            "invocation envelope declares no actions or effects to authorize"
        )
    return tuple(scopes)


def _coerce_envelope(
    invocation: Any,
    *,
    normalizer: EnvelopeNormalizer | None,
    deps: OfflineAuthorizationDependencies,
) -> InvocationIntentEnvelope:
    if isinstance(invocation, InvocationIntentEnvelope):
        return validate_invocation_envelope(invocation)

    if isinstance(invocation, Mapping):
        # Treat as envelope document when it looks canonical.
        if "envelope_id" in invocation or "schema_version" in invocation:
            return validate_invocation_envelope(
                InvocationIntentEnvelope.from_dict(invocation)
            )
        if normalizer is None and deps.normalizer is None:
            raise AuthorizationServiceError(
                "non-canonical invocation mapping requires an injected normalizer"
            )
        active = normalizer or deps.normalizer
        assert active is not None
        result = active(invocation)
        if isinstance(result, InvocationIntentEnvelope):
            return validate_invocation_envelope(result)
        if isinstance(result, Mapping):
            return validate_invocation_envelope(
                InvocationIntentEnvelope.from_dict(result)
            )
        raise AuthorizationServiceError(
            "normalizer must return InvocationIntentEnvelope or mapping"
        )

    # Raw source object — requires normalizer; never execute content.
    active = normalizer or deps.normalizer
    if active is None:
        raise AuthorizationServiceError(
            "raw invocation requires an injected offline normalizer; "
            "the service never executes source content"
        )
    result = active(invocation)
    if isinstance(result, InvocationIntentEnvelope):
        return validate_invocation_envelope(result)
    if isinstance(result, Mapping):
        return validate_invocation_envelope(
            InvocationIntentEnvelope.from_dict(result)
        )
    raise AuthorizationServiceError(
        "normalizer must return InvocationIntentEnvelope or mapping"
    )


def _coerce_intent_lower(value: Any) -> IntentLowerResult:
    if isinstance(value, IntentLowerResult):
        return value
    if isinstance(value, Mapping):
        return IntentLowerResult(
            intent_cid=value.get("intent_cid", ""),
            intent_document_id=value.get("intent_document_id", ""),
            formalization_artifact_id=value.get(
                "formalization_artifact_id", ""
            ),
            actions=tuple(value.get("actions", ())),
            native_views=tuple(value.get("native_views", ())),
            cross_view_links=tuple(value.get("cross_view_links", ())),
            constraint_artifacts=tuple(
                value.get("constraint_artifacts", ())
            ),
            assumptions=tuple(value.get("assumptions", ())),
            diagnostics=tuple(value.get("diagnostics", ())),
            schema_version=value.get(
                "schema_version", INTENT_LOWER_RESULT_SCHEMA_VERSION
            ),
        )
    raise AuthorizationServiceError(
        "intent lowerer must return IntentLowerResult or mapping"
    )


def _coerce_evidence(value: Any) -> EvidenceSelectionResult:
    if isinstance(value, EvidenceSelectionResult):
        return value
    if isinstance(value, Mapping):
        return EvidenceSelectionResult(
            legal_evidence_cids=tuple(value.get("legal_evidence_cids", ())),
            security_evidence_cids=tuple(
                value.get("security_evidence_cids", ())
            ),
            intent_evidence_cids=tuple(value.get("intent_evidence_cids", ())),
            selected_evidence_cids=tuple(
                value.get("selected_evidence_cids", ())
            ),
            rejected_cids=tuple(value.get("rejected_cids", ())),
            simulated_rejected=tuple(value.get("simulated_rejected", ())),
            gaps=tuple(value.get("gaps", ())),
            verification_passed=bool(
                value.get("verification_passed", True)
            ),
            audit_digest=value.get("audit_digest", ""),
            diagnostics=tuple(value.get("diagnostics", ())),
            schema_version=value.get(
                "schema_version", EVIDENCE_SELECTION_SCHEMA_VERSION
            ),
        )
    raise AuthorizationServiceError(
        "evidence selector/verifier must return EvidenceSelectionResult or mapping"
    )


def _default_lower(
    envelope: InvocationIntentEnvelope,
) -> IntentLowerResult:
    """Default pure lowerer: project envelope scopes without executing content."""

    intent_cid = (
        envelope.source.formalization_artifact_id
        or envelope.source.intent_document_id
        or envelope.source.content_cid
        or f"intent:{envelope.envelope_id}"
    )
    actions = action_scopes_from_envelope(envelope)
    assumptions = tuple(
        assumption.assumption_id
        if hasattr(assumption, "assumption_id")
        else str(assumption)
        for assumption in envelope.assumptions
    )
    return IntentLowerResult(
        intent_cid=intent_cid,
        intent_document_id=envelope.source.intent_document_id,
        formalization_artifact_id=envelope.source.formalization_artifact_id,
        actions=actions,
        assumptions=assumptions,
        diagnostics=("auth.service.default_lower",),
    )


def _default_evidence(
    *,
    envelope: InvocationIntentEnvelope,
    roots: BoundRoots,
    budget: AuthorizationBudget,
    profile: AdmissibilityProfile,
    intent: IntentLowerResult,
    deps: OfflineAuthorizationDependencies,
) -> EvidenceSelectionResult:
    """Default evidence path for offline tests with injectables only.

    Without a selector the service records a coverage gap and does not allow.
    Preselected evidence from deps is accepted after production simulation
    filtering.
    """

    if deps.preselected_evidence is not None:
        selection = _coerce_evidence(deps.preselected_evidence)
    elif deps.evidence_selector is not None:
        selection = _coerce_evidence(
            deps.evidence_selector(
                envelope,
                roots=roots,
                budget=budget,
                profile=profile,
                intent=intent,
            )
        )
    else:
        selection = EvidenceSelectionResult(
            verification_passed=False,
            gaps=("no_evidence_selector_or_preselection",),
            diagnostics=("auth.service.evidence.missing_selector",),
        )

    # Production profiles must not accept simulated evidence for authority.
    if budget.production_mode or not profile.accept_simulated_zkp:
        if selection.simulated_rejected:
            # Already recorded.
            pass
        # Strip any CID marked simulated in diagnostics metadata via gaps.
        if "simulated" in selection.gaps or selection.simulated_rejected:
            filtered_selected = tuple(
                cid
                for cid in selection.selected_evidence_cids
                if cid not in selection.simulated_rejected
            )
            filtered_legal = tuple(
                cid
                for cid in selection.legal_evidence_cids
                if cid not in selection.simulated_rejected
            )
            filtered_security = tuple(
                cid
                for cid in selection.security_evidence_cids
                if cid not in selection.simulated_rejected
            )
            selection = EvidenceSelectionResult(
                legal_evidence_cids=filtered_legal,
                security_evidence_cids=filtered_security,
                intent_evidence_cids=tuple(
                    cid
                    for cid in selection.intent_evidence_cids
                    if cid not in selection.simulated_rejected
                ),
                selected_evidence_cids=filtered_selected,
                rejected_cids=tuple(
                    sorted(
                        set(selection.rejected_cids)
                        | set(selection.simulated_rejected)
                    )
                ),
                simulated_rejected=selection.simulated_rejected,
                gaps=tuple(
                    sorted(set(selection.gaps) | {"simulated_rejected_production"})
                ),
                verification_passed=selection.verification_passed
                and not selection.simulated_rejected,
                audit_digest=selection.audit_digest,
                diagnostics=tuple(selection.diagnostics)
                + ("auth.service.evidence.simulated_rejected_production",),
            )

    if deps.evidence_verifier is not None:
        selection = _coerce_evidence(
            deps.evidence_verifier(
                selection,
                roots=roots,
                budget=budget,
                profile=profile,
            )
        )
    return selection


def _error_decision(
    *,
    status: InternalDecisionStatus,
    reasons: Sequence[str],
    reason_codes: Sequence[str],
    profile_id: str,
    selected_evidence_cids: Sequence[str] = (),
    residual: Sequence[str] = (),
    diagnostics: Sequence[str] = (),
    bundle_digest: str = "",
    policy_digest: str = "",
) -> AuthorizationDecision:
    """Build a fail-closed decision without proof authority."""

    digest_seed = bundle_digest or ("0" * 64)
    if len(digest_seed) != 64:
        digest_seed = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()
    policy_seed = policy_digest or digest_seed
    if len(policy_seed) != 64:
        policy_seed = hashlib.sha256(policy_seed.encode("utf-8")).hexdigest()
    return AuthorizationDecision(
        status=status,
        wire_status=map_internal_to_wire(status),
        reasons=tuple(reasons),
        reason_codes=tuple(reason_codes),
        job_results=(),
        bundle_digest=digest_seed,
        policy_digest=policy_seed,
        profile_id=profile_id or "legal-strict",
        selected_evidence_cids=tuple(selected_evidence_cids),
        residual_obligations=tuple(residual),
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentAuthorizationService:
    """``IntentAuthorizationService@1`` — exact-context authorization API.

    Compose public leaves only.  No dispatch, no backend install, no corpus
    mutation, and no content execution.
    """

    producer_id: str = DEFAULT_PRODUCER_ID
    interface: str = INTENT_AUTHORIZATION_SERVICE_INTERFACE
    schema_version: str = INTENT_AUTHORIZATION_SERVICE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "producer_id", _text(self.producer_id, "producer_id")
        )
        if self.interface != INTENT_AUTHORIZATION_SERVICE_INTERFACE:
            raise AuthorizationServiceError(
                f"unsupported service interface: {self.interface!r}"
            )
        if self.schema_version != INTENT_AUTHORIZATION_SERVICE_SCHEMA_VERSION:
            raise AuthorizationServiceError(
                f"unsupported service schema: {self.schema_version!r}"
            )

    def evaluate(
        self,
        invocation: Any = None,
        *,
        policy_ref: str = "",
        legal_corpus_ref: str = "",
        security_corpus_ref: str = "",
        intent_corpus_ref: str = "",
        environment: Mapping[str, Any] | None = None,
        budget: AuthorizationBudget | Mapping[str, Any] | None = None,
        profile: AdmissibilityProfile
        | AdmissibilityProfileId
        | str
        | None = None,
        deps: OfflineAuthorizationDependencies | None = None,
        cancellation: CancellationToken | None = None,
        derive_capability_on_allow: bool = False,
        normalizer: EnvelopeNormalizer | None = None,
        revocation_root: str = "",
        circuit_roots: Sequence[str] = (),
        vk_roots: Sequence[str] = (),
        include_during_post: bool = True,
        include_translation_reconstruction: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuthorizationServiceResult:
        """Evaluate a canonical (or normalized) invocation offline.

        Parameters mirror the plan sketch::

            IntentAuthorizationService.evaluate(
                invocation=envelope,
                policy_ref=...,
                legal_corpus_ref=...,
                security_corpus_ref=...,
                intent_corpus_ref=...,
                environment=...,
                budget=...,
            )

        Exceptions and cancellations never become allow.  Capability derivation
        is attempted only when ``derive_capability_on_allow`` is true **and**
        the final decision is allow.
        """

        deps = deps or OfflineAuthorizationDependencies()
        token = cancellation or CancellationToken()
        trace = _TraceBuilder()
        envelope: InvocationIntentEnvelope | None = None
        roots: BoundRoots | None = None
        context: BoundContext | None = None
        intent_lower: IntentLowerResult | None = None
        evidence: EvidenceSelectionResult | None = None
        bundle: AuthorizationQueryBundle | None = None
        portfolio_run: PortfolioRunResult | None = None
        decision: AuthorizationDecision | None = None
        receipt: DecisionReceipt | None = None
        capability: AuthorizationCapability | None = None
        profile_obj: AdmissibilityProfile | None = None
        profile_id = ""
        reasons: list[str] = []
        reason_codes: list[str] = []
        status = InternalDecisionStatus.ERROR

        try:
            # ---- validate budget / flags ---------------------------------
            token.check(AuthorizationStage.VALIDATE.value)
            trace.stage(AuthorizationStage.VALIDATE)
            if budget is None:
                budget_obj = AuthorizationBudget()
            elif isinstance(budget, AuthorizationBudget):
                budget_obj = budget
            else:
                budget_obj = AuthorizationBudget.from_dict(
                    _mapping(budget, "budget")
                )
            budget_obj.validate_side_effect_flags()
            trace.note("auth.service.budget.validated")

            # ---- normalize / accept envelope -----------------------------
            token.check(AuthorizationStage.NORMALIZE.value)
            trace.stage(AuthorizationStage.NORMALIZE)
            if invocation is None:
                raise AuthorizationServiceError(
                    "invocation is required (envelope, mapping, or normalizable source)"
                )
            envelope = _coerce_envelope(
                invocation, normalizer=normalizer, deps=deps
            )
            # Never execute tools/content — envelope is data only.
            trace.note(
                "auth.service.normalize.accepted",
                f"auth.service.envelope:{envelope.envelope_id}",
            )

            # ---- profile -------------------------------------------------
            requested_profile = (
                profile
                if profile is not None
                else (envelope.policy.policy_profile or None)
            )
            resolution = resolve_profile_fail_closed(requested_profile)
            if not resolution.ok or resolution.profile is None:
                raise AuthorizationServiceError(
                    f"profile resolution failed closed: {requested_profile!r}"
                )
            profile_obj = resolution.profile
            profile_id = profile_obj.profile_id.value
            if budget_obj.production_mode and profile_obj.accept_simulated_zkp:
                # Production evaluation under a sim-accepting profile still
                # refuses to authorize simulated evidence (stricter of the two).
                trace.note(
                    "auth.service.production_mode.overrides_simulated_acceptance"
                )

            # ---- roots ---------------------------------------------------
            roots = _resolve_roots(
                envelope=envelope,
                policy_ref=policy_ref,
                legal_corpus_ref=legal_corpus_ref,
                security_corpus_ref=security_corpus_ref,
                intent_corpus_ref=intent_corpus_ref,
                revocation_root=revocation_root,
                circuit_roots=circuit_roots,
                vk_roots=vk_roots,
            )
            context = bound_context_from_envelope(
                envelope, environment=environment
            )
            trace.note(
                "auth.service.roots.bound",
                f"auth.service.policy_root:{roots.policy_root}",
            )

            # ---- lower Intent --------------------------------------------
            token.check(AuthorizationStage.LOWER.value)
            trace.stage(AuthorizationStage.LOWER)
            if deps.pre_lowered_intent is not None:
                intent_lower = _coerce_intent_lower(deps.pre_lowered_intent)
            elif deps.intent_lowerer is not None:
                intent_lower = _coerce_intent_lower(
                    deps.intent_lowerer(envelope)
                )
            else:
                intent_lower = _default_lower(envelope)
            if not intent_lower.actions:
                raise AuthorizationServiceError(
                    "intent lowering produced no action scopes"
                )
            trace.note(
                "auth.service.lower.complete",
                f"auth.service.intent_cid:{intent_lower.intent_cid}",
            )

            # ---- hard-filter / select / verify evidence ------------------
            token.check(AuthorizationStage.EVIDENCE.value)
            trace.stage(AuthorizationStage.EVIDENCE)
            evidence = _default_evidence(
                envelope=envelope,
                roots=roots,
                budget=budget_obj,
                profile=profile_obj,
                intent=intent_lower,
                deps=deps,
            )
            # Production: simulated evidence never authorizes.
            if evidence.simulated_rejected and (
                budget_obj.production_mode or not profile_obj.accept_simulated_zkp
            ):
                trace.note("auth.service.evidence.simulated_not_authoritative")
            if not evidence.verification_passed:
                status = InternalDecisionStatus.INDETERMINATE
                reasons.append("evidence verification failed or incomplete")
                reason_codes.append("evidence.verification_failed")
                decision = _error_decision(
                    status=status,
                    reasons=reasons,
                    reason_codes=reason_codes,
                    profile_id=profile_id,
                    selected_evidence_cids=evidence.all_selected,
                    diagnostics=evidence.diagnostics,
                    policy_digest=roots.digest,
                )
            elif evidence.gaps and not evidence.all_selected:
                status = InternalDecisionStatus.INDETERMINATE
                reasons.append(
                    "evidence coverage gaps: " + ",".join(evidence.gaps)
                )
                reason_codes.append("evidence.coverage_gap")
                decision = _error_decision(
                    status=status,
                    reasons=reasons,
                    reason_codes=reason_codes,
                    profile_id=profile_id,
                    diagnostics=evidence.diagnostics + evidence.gaps,
                    policy_digest=roots.digest,
                )
            else:
                # ---- compose proof jobs ----------------------------------
                token.check(AuthorizationStage.COMPOSE.value)
                trace.stage(AuthorizationStage.COMPOSE)
                composer = deps.composer or AuthorizationQueryComposer()
                corpus_root = roots.corpus_roots[0] if roots.corpus_roots else ""
                bundle = composer.compose(
                    intent_lower.actions,
                    profile=profile_obj,
                    invocation_digest=context.request_digest,
                    intent_cid=intent_lower.intent_cid,
                    corpus_root=corpus_root,
                    revocation_root=roots.revocation_root,
                    policy_root=roots.policy_root,
                    legal_evidence_cids=evidence.legal_evidence_cids,
                    security_evidence_cids=evidence.security_evidence_cids,
                    native_views=intent_lower.native_views,
                    cross_view_links=intent_lower.cross_view_links,
                    constraint_artifacts=intent_lower.constraint_artifacts,
                    assumptions=intent_lower.assumptions,
                    include_during_post=include_during_post,
                    include_translation_reconstruction=(
                        include_translation_reconstruction
                    ),
                    metadata=metadata or {},
                )
                trace.note(
                    "auth.service.compose.complete",
                    f"auth.service.bundle:{bundle.bundle_id}",
                    f"auth.service.job_count:{len(bundle.jobs)}",
                )

                # ---- run native proof portfolio --------------------------
                token.check(AuthorizationStage.PORTFOLIO.value)
                trace.stage(AuthorizationStage.PORTFOLIO)
                portfolio = deps.portfolio or AuthorizationPortfolio(
                    decision_policy=deps.decision_policy
                )
                # Never install backends: only PATH probe injectables / fakes.
                portfolio_run = portfolio.run(
                    bundle,
                    solver=deps.portfolio_solver,
                    precomputed_attempts=deps.precomputed_attempts,
                    which=deps.which,
                    version_probe=deps.version_probe,
                    decide=True,
                )
                trace.note(
                    "auth.service.portfolio.complete",
                    f"auth.service.run:{portfolio_run.run_id}",
                )

                # ---- select / map decision -------------------------------
                token.check(AuthorizationStage.DECIDE.value)
                trace.stage(AuthorizationStage.DECIDE)
                if portfolio_run.decision is not None:
                    decision = portfolio_run.decision
                else:
                    policy = (
                        deps.decision_policy
                        or AuthorizationDecisionPolicy.for_profile(profile_id)
                    )
                    decision = evaluate_authorization_decision(
                        bundle, portfolio_run.job_results, policy=policy
                    )
                # Attach evidence CIDs if decision lacked them.
                if not decision.selected_evidence_cids and evidence.all_selected:
                    decision = AuthorizationDecision(
                        status=decision.status,
                        wire_status=decision.wire_status,
                        reasons=decision.reasons,
                        reason_codes=decision.reason_codes,
                        job_results=decision.job_results,
                        bundle_digest=decision.bundle_digest,
                        policy_digest=decision.policy_digest,
                        profile_id=decision.profile_id,
                        selected_evidence_cids=evidence.all_selected,
                        residual_obligations=decision.residual_obligations,
                        diagnostics=decision.diagnostics
                        + ("auth.service.evidence.bound",),
                        metadata=decision.metadata,
                    )
                status = decision.status
                reasons = list(decision.reasons)
                reason_codes = list(decision.reason_codes)
                trace.note(
                    f"auth.service.decision:{status.value}",
                    f"auth.service.wire:{decision.wire_status.value}",
                )

            # ---- build receipt -------------------------------------------
            token.check(AuthorizationStage.RECEIPT.value)
            trace.stage(AuthorizationStage.RECEIPT)
            assert decision is not None
            assert roots is not None
            assert context is not None
            assert profile_obj is not None
            issued_at = deps.now()
            deadline = envelope.deadline if envelope is not None else issued_at
            try:
                # Cap expiry at min(deadline, issued+ttl) without exceeding deadline.
                ttl_expiry = _add_seconds_iso(
                    issued_at, budget_obj.receipt_ttl_seconds
                )
                expiry = min(deadline, ttl_expiry)
            except (TypeError, ValueError):
                expiry = deadline or issued_at

            attempt_digests: tuple[str, ...] = ()
            if portfolio_run is not None:
                attempt_digests = tuple(
                    item.digest for item in portfolio_run.attempts
                )
            obligation_ids: tuple[str, ...] = ()
            if bundle is not None:
                obligation_ids = tuple(
                    sorted({job.job_id for job in bundle.jobs})
                )

            receipt_id = (
                "receipt:"
                + stable_digest(
                    {
                        "context": context.digest,
                        "decision": decision.digest,
                        "roots": roots.digest,
                        "issued_at": issued_at,
                    }
                )[:24]
            )
            receipt = build_decision_receipt(
                receipt_id=receipt_id,
                context=context,
                roots=roots,
                outcome=decision.status,
                decision=decision,
                profile_id=profile_id,
                issued_at=issued_at,
                deadline=deadline,
                expiry=expiry,
                producer_id=self.producer_id,
                obligation_ids=obligation_ids,
                attempt_digests=attempt_digests,
                selected_evidence_cids=decision.selected_evidence_cids
                or (evidence.all_selected if evidence else ()),
                metadata={
                    "service_interface": self.interface,
                    "service_schema": self.schema_version,
                    **(dict(metadata) if metadata else {}),
                },
            )
            receipt.verify_integrity()
            trace.note(
                "auth.service.receipt.built",
                f"auth.service.receipt_id:{receipt.receipt_id}",
            )

            # ---- optional capability (allow only) ------------------------
            if derive_capability_on_allow:
                token.check(AuthorizationStage.CAPABILITY.value)
                trace.stage(AuthorizationStage.CAPABILITY)
                if receipt.permits_capability_derivation:
                    cap_expiry = min(
                        receipt.expiry,
                        _add_seconds_iso(
                            issued_at, budget_obj.capability_ttl_seconds
                        ),
                    )
                    capability = derive_capability(
                        receipt,
                        capability_id="capability:"
                        + stable_digest(
                            {
                                "receipt": receipt.content_digest,
                                "audience": receipt.audience_id,
                            }
                        )[:24],
                        issued_at=issued_at,
                        expiry=cap_expiry,
                        producer_id=self.producer_id,
                    )
                    capability.verify_integrity()
                    trace.note("auth.service.capability.derived")
                else:
                    # Explicitly refuse derivation for non-allow.
                    trace.note(
                        "auth.service.capability.skipped_non_allow",
                        f"auth.service.outcome:{receipt.outcome.value}",
                    )
                    capability = None

            # Final safety: never allow if production simulated evidence leaked.
            if (
                status is InternalDecisionStatus.ALLOW
                and evidence is not None
                and evidence.simulated_rejected
                and budget_obj.production_mode
            ):
                status = InternalDecisionStatus.INDETERMINATE
                reasons = list(reasons) + [
                    "simulated evidence cannot authorize in production"
                ]
                reason_codes = list(reason_codes) + [
                    "evidence.simulated_production"
                ]
                decision = _error_decision(
                    status=status,
                    reasons=reasons,
                    reason_codes=reason_codes,
                    profile_id=profile_id,
                    selected_evidence_cids=(),
                    diagnostics=("auth.service.simulated_block",),
                    policy_digest=roots.digest,
                    bundle_digest=decision.bundle_digest if decision else "",
                )
                capability = None
                receipt = build_decision_receipt(
                    receipt_id=receipt.receipt_id + ":sim-block",
                    context=context,
                    roots=roots,
                    outcome=decision.status,
                    decision=decision,
                    profile_id=profile_id,
                    issued_at=issued_at,
                    deadline=deadline,
                    expiry=expiry,
                    producer_id=self.producer_id,
                )

            trace.stage(AuthorizationStage.COMPLETE)
            return AuthorizationServiceResult(
                status=status,
                wire_status=map_internal_to_wire(status),
                reasons=tuple(reasons),
                reason_codes=tuple(reason_codes),
                decision=decision,
                receipt=receipt,
                capability=capability,
                envelope=envelope,
                bundle=bundle,
                portfolio_run=portfolio_run,
                evidence=evidence,
                intent_lower=intent_lower,
                roots=roots,
                context=context,
                trace=trace.build(),
                profile_id=profile_id,
                producer_id=self.producer_id,
            )

        except AuthorizationCancelled as exc:
            trace.cancelled = True
            trace.fail(exc)
            status = InternalDecisionStatus.INDETERMINATE
            reasons = [str(exc) or "cancelled"]
            reason_codes = ["service.cancelled"]
            return self._fail_closed_result(
                status=status,
                reasons=reasons,
                reason_codes=reason_codes,
                trace=trace,
                envelope=envelope,
                roots=roots,
                context=context,
                evidence=evidence,
                intent_lower=intent_lower,
                bundle=bundle,
                portfolio_run=portfolio_run,
                profile_id=profile_id,
                deps=deps,
            )
        except Exception as exc:  # noqa: BLE001 — fail closed, never allow
            # Includes AuthorizationServiceError, ComposeError, PortfolioError,
            # ReceiptError, InvocationEnvelopeValidationError, etc.
            trace.fail(exc)
            status = InternalDecisionStatus.ERROR
            reasons = [str(exc) or type(exc).__name__]
            reason_codes = [f"service.exception:{type(exc).__name__}"]
            # Never convert exceptions into allow.
            return self._fail_closed_result(
                status=status,
                reasons=reasons,
                reason_codes=reason_codes,
                trace=trace,
                envelope=envelope,
                roots=roots,
                context=context,
                evidence=evidence,
                intent_lower=intent_lower,
                bundle=bundle,
                portfolio_run=portfolio_run,
                profile_id=profile_id,
                deps=deps,
            )

    def _fail_closed_result(
        self,
        *,
        status: InternalDecisionStatus,
        reasons: Sequence[str],
        reason_codes: Sequence[str],
        trace: _TraceBuilder,
        envelope: InvocationIntentEnvelope | None,
        roots: BoundRoots | None,
        context: BoundContext | None,
        evidence: EvidenceSelectionResult | None,
        intent_lower: IntentLowerResult | None,
        bundle: AuthorizationQueryBundle | None,
        portfolio_run: PortfolioRunResult | None,
        profile_id: str,
        deps: OfflineAuthorizationDependencies,
    ) -> AuthorizationServiceResult:
        """Build a non-allow result with best-effort receipt; never allow."""

        assert status is not InternalDecisionStatus.ALLOW
        wire = map_internal_to_wire(status)
        decision: AuthorizationDecision | None = None
        receipt: DecisionReceipt | None = None
        try:
            policy_digest = roots.digest if roots is not None else ("f" * 64)
            bundle_digest = (
                bundle.digest if bundle is not None else ("e" * 64)
            )
            decision = _error_decision(
                status=status,
                reasons=reasons,
                reason_codes=reason_codes,
                profile_id=profile_id or "legal-strict",
                selected_evidence_cids=(
                    evidence.all_selected if evidence is not None else ()
                ),
                diagnostics=tuple(trace.diagnostics[-8:]),
                bundle_digest=bundle_digest
                if len(bundle_digest) == 64
                else hashlib.sha256(bundle_digest.encode()).hexdigest(),
                policy_digest=policy_digest
                if len(policy_digest) == 64
                else hashlib.sha256(policy_digest.encode()).hexdigest(),
            )
            if roots is not None and context is not None:
                issued_at = deps.now()
                deadline = (
                    envelope.deadline
                    if envelope is not None
                    else _add_seconds_iso(issued_at, 60)
                )
                receipt = build_decision_receipt(
                    receipt_id="receipt:fail-closed:"
                    + stable_digest(
                        {
                            "reasons": list(reasons),
                            "status": status.value,
                            "context": context.digest,
                        }
                    )[:20],
                    context=context,
                    roots=roots,
                    outcome=decision.status,
                    decision=decision,
                    profile_id=profile_id or "legal-strict",
                    issued_at=issued_at,
                    deadline=deadline,
                    expiry=deadline,
                    producer_id=self.producer_id,
                )
        except Exception as build_exc:  # noqa: BLE001
            trace.note(
                f"auth.service.fail_closed.receipt_error:{type(build_exc).__name__}"
            )
            decision = None
            receipt = None

        return AuthorizationServiceResult(
            status=status,
            wire_status=wire,
            reasons=tuple(reasons),
            reason_codes=tuple(reason_codes),
            decision=decision,
            receipt=receipt,
            capability=None,  # never derive on non-allow / exception path
            envelope=envelope,
            bundle=bundle,
            portfolio_run=portfolio_run,
            evidence=evidence,
            intent_lower=intent_lower,
            roots=roots,
            context=context,
            trace=trace.build(),
            profile_id=profile_id,
            producer_id=self.producer_id,
        )


def evaluate_authorization(
    invocation: Any = None,
    **kwargs: Any,
) -> AuthorizationServiceResult:
    """Module-level helper: run the default intent authorization service."""

    return IntentAuthorizationService().evaluate(invocation, **kwargs)


__all__ = [
    "AUTHORIZATION_BUDGET_SCHEMA_VERSION",
    "AUTHORIZATION_RESULT_SCHEMA_VERSION",
    "AUTHORIZATION_TRACE_SCHEMA_VERSION",
    "AuthorizationBudget",
    "AuthorizationBudgetError",
    "AuthorizationCancelled",
    "AuthorizationRootError",
    "AuthorizationServiceError",
    "AuthorizationServiceResult",
    "AuthorizationServiceTrace",
    "AuthorizationStage",
    "CancellationToken",
    "DEFAULT_PRODUCER_ID",
    "EVIDENCE_SELECTION_SCHEMA_VERSION",
    "EvidenceSelectionResult",
    "EvidenceSelector",
    "EvidenceVerifier",
    "EnvelopeNormalizer",
    "INTENT_AUTHORIZATION_SERVICE_INTERFACE",
    "INTENT_AUTHORIZATION_SERVICE_SCHEMA_VERSION",
    "INTENT_LOWER_RESULT_SCHEMA_VERSION",
    "IntentAuthorizationService",
    "IntentLowerResult",
    "IntentLowerer",
    "OfflineAuthorizationDependencies",
    "action_scopes_from_envelope",
    "bound_context_from_envelope",
    "evaluate_authorization",
]
