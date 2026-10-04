"""Independent validation of proof-gap candidates (``ProofCandidateValidator@1``).

FVT-G034 / FVT-025: validate each candidate and candidate set with:

* parse / type checks;
* exact tree / goal / assumptions / tool / policy / bounds bindings;
* consistency / non-vacuity / non-circularity;
* solver / model-checker / kernel replay (injectable, hermetic);
* deletion / core minimality; and
* truthful authority / unknown / unavailable results.

Program invariants:

* providers may *propose* evidence, but this deterministic validator alone sets
  validation status (``CandidateValidation``);
* no unvalidated or stale candidate may discharge a graph node;
* accepted candidates bind exact tree/goal/assumptions/tool/policy/bounds;
* deletion of a selected premise must break the proof for small minimal cases,
  or the validation receipt must explicitly limit its guarantee (``BOUNDED`` /
  minimality not applicable);
* multi-provider disagreement is **quarantined**, never silently majority-voted
  into acceptance; and
* validation records never claim proof or goal completion
  (``CandidateValidation`` forbids both flags).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    CANDIDATE_VALIDATION_SCHEMA,
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    CandidateValidation,
    HoleKind,
    HoleStatus,
    ProofHole,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    ValidationRecipe,
    ValidationVerdict,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

PROOF_CANDIDATE_VALIDATOR_INTERFACE: Final = "ProofCandidateValidator@1"
CANDIDATE_VALIDATION_ENGINE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-validation-engine@1"
)
VALIDATION_BINDING_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/validation-binding@1"
)
VALIDATION_REQUEST_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/validation-request@1"
)
VALIDATION_CHECK_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/validation-check@1"
)
MINIMALITY_REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/minimality-report@1"
)
REPLAY_OUTCOME_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/replay-outcome@1"
)
DISAGREEMENT_RECORD_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/disagreement-record@1"
)
CANDIDATE_VALIDATION_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-validation-result@1"
)
CANDIDATE_SET_VALIDATION_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/"
    "candidate-set-validation-result@1"
)
VALIDATOR_ALGORITHM_VERSION: Final = "proof-candidate-validator/1.0.0"

DEFAULT_BOUNDS: Final = ResourceBounds(
    wall_time_ms=30_000,
    memory_bytes=256 * 1024 * 1024,
    max_steps=64,
    max_depth=16,
    max_nodes=128,
    max_candidates=32,
    model_token_limit=0,
    network_allowed=False,
)

# Authorities that validation may promote to (never theorem/attestation without
# kernel/attestor evidence — hermetic default caps at satisfiability/model_check).
_ACCEPTED_AUTHORITY_CAP: Final = AuthorityCeiling.SATISFIABILITY
_BOUNDED_AUTHORITY_CAP: Final = AuthorityCeiling.BOUNDED

_TOKEN_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.:\-]*")

_VACUOUS_STATEMENTS: Final[frozenset[str]] = frozenset(
    {
        "",
        "true",
        "True",
        "TRUE",
        "⊤",
        "top",
        "1",
        "tt",
        "yes",
        "always",
        "tautology",
    }
)

_CONTRADICTION_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "false",
        "False",
        "FALSE",
        "⊥",
        "bot",
        "bottom",
        "contradiction",
        "0",
        "ff",
        "never",
        "unsat",
    }
)

# Candidate statuses that are already terminal / non-admissible for discharge.
_TERMINAL_CANDIDATE_STATUSES: Final[frozenset[CandidateStatus]] = frozenset(
    {
        CandidateStatus.REJECTED,
        CandidateStatus.SUPERSEDED,
    }
)

# Hole statuses that must never be discharged by a candidate.
_NON_DISCHARGEABLE_HOLE_STATUSES: Final[frozenset[HoleStatus]] = frozenset(
    {
        HoleStatus.UNSUPPORTED,
        HoleStatus.UNAVAILABLE,
        HoleStatus.FALSE,
        HoleStatus.DISCHARGED,  # already closed — re-validation only
    }
)

_NON_PROOF_HOLE_KINDS: Final[frozenset[HoleKind]] = frozenset(
    {
        HoleKind.UNSUPPORTED_SEMANTICS,
        HoleKind.UNAVAILABLE_TOOL,
        HoleKind.UNAVAILABLE_RECONSTRUCTION,
        HoleKind.REQUIRED_IMPLEMENTATION_CHANGE,
    }
)

# Closed check-stage vocabulary (order is the pipeline order).
PIPELINE_STAGES: Final[tuple[str, ...]] = (
    "parse_type",
    "exact_binding",
    "stale_freshness",
    "consistency",
    "non_vacuity",
    "non_circularity",
    "replay",
    "minimality",
    "authority",
    "discharge_gate",
)


# ---------------------------------------------------------------------------
# Errors and closed vocabularies
# ---------------------------------------------------------------------------


class CandidateValidationError(ValueError):
    """Raised when validation inputs are malformed or unsafe."""


class ValidationCheckStatus(StrEnum):
    """Outcome of a single validation stage."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    QUARANTINED = "quarantined"


class ReplayBackendKind(StrEnum):
    """Kinds of independent replay checkers."""

    SOLVER = "solver"
    MODEL_CHECKER = "model_checker"
    KERNEL = "kernel"
    ORACLE = "oracle"
    SYNTHETIC = "synthetic"


class ReplayStatus(StrEnum):
    """Truthful outcome of a replay attempt."""

    HOLDS = "holds"
    FAILS = "fails"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    TIMEOUT = "timeout"
    BOUNDED = "bounded"


class MinimalityKind(StrEnum):
    """How minimality was established (matches ``CandidateValidation.minimality``)."""

    UNKNOWN = "unknown"
    BOUNDED = "bounded"
    LOCAL = "local"
    SUBSET = "subset"
    NOT_APPLICABLE = "not_applicable"


class DischargeEligibility(StrEnum):
    """Whether a validation result may discharge a graph node."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    BOUNDED = "bounded"
    QUARANTINED = "quarantined"
    STALE = "stale"


class QuarantineReason(StrEnum):
    """Why a candidate or set was quarantined."""

    PROVIDER_DISAGREEMENT = "provider_disagreement"
    AUTHORITY_DISAGREEMENT = "authority_disagreement"
    REPLAY_DISAGREEMENT = "replay_disagreement"
    STALE_CANDIDATE = "stale_candidate"
    UNVALIDATED = "unvalidated"
    MALFORMED = "malformed"
    NONE = "none"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise CandidateValidationError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise CandidateValidationError(f"{label} must not contain NUL")
    if not optional and not text:
        raise CandidateValidationError(f"{label} is required")
    if len(text) > maximum:
        raise CandidateValidationError(
            f"{label} exceeds maximum length of {maximum}"
        )
    return text


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip())
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise CandidateValidationError(
                f"{label} must be one of: {allowed}"
            ) from error
    raise CandidateValidationError(f"{label} must be a {enum_type.__name__}")


def _string_tuple(
    values: Sequence[str] | None,
    label: str,
    *,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: tuple[str, ...] = ()
    elif isinstance(values, str):
        items = (_text(values, label, maximum=512),)
    elif isinstance(values, Sequence) and not isinstance(
        values, (bytes, bytearray, memoryview)
    ):
        items = tuple(
            _text(item, f"{label}[{index}]", maximum=512)
            for index, item in enumerate(values)
        )
    else:
        raise CandidateValidationError(f"{label} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    if not preserve_order:
        result = sorted(result)
    if required and not result:
        raise CandidateValidationError(f"{label} must not be empty")
    return tuple(result)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateValidationError(
            f"{label} must be a non-negative integer"
        )
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CandidateValidationError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CandidateValidationError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CandidateValidationError(f"{label} keys must be strings")
    return {str(k): value[k] for k in sorted(value)}


def _bounds(value: object, label: str = "bounds") -> ResourceBounds:
    if value is None:
        return DEFAULT_BOUNDS
    if isinstance(value, ResourceBounds):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceBounds.from_dict(value)
        except TacticianContractError as error:
            raise CandidateValidationError(f"{label}: {error}") from error
    raise CandidateValidationError(f"{label} must be a ResourceBounds")


def _proof_hole(value: object, label: str = "hole") -> ProofHole:
    if isinstance(value, ProofHole):
        return value
    if isinstance(value, Mapping):
        try:
            return ProofHole.from_dict(value)
        except TacticianContractError as error:
            raise CandidateValidationError(f"{label}: {error}") from error
    raise CandidateValidationError(f"{label} must be a ProofHole")


def _candidate_step(
    value: object, label: str = "candidate"
) -> CandidateProofStep:
    if isinstance(value, CandidateProofStep):
        return value
    if isinstance(value, Mapping):
        try:
            return CandidateProofStep.from_dict(value)
        except TacticianContractError as error:
            raise CandidateValidationError(f"{label}: {error}") from error
    raise CandidateValidationError(f"{label} must be a CandidateProofStep")


def _source_binding(value: object, label: str = "source") -> SourceSpanBinding:
    if isinstance(value, SourceSpanBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpanBinding.from_dict(value)
        except TacticianContractError as error:
            raise CandidateValidationError(f"{label}: {error}") from error
    raise CandidateValidationError(f"{label} must be a SourceSpanBinding")


def _recipe(value: object, label: str = "recipe") -> ValidationRecipe | None:
    if value is None:
        return None
    if isinstance(value, ValidationRecipe):
        return value
    if isinstance(value, Mapping):
        try:
            return ValidationRecipe.from_dict(value)
        except TacticianContractError as error:
            raise CandidateValidationError(f"{label}: {error}") from error
    raise CandidateValidationError(f"{label} must be a ValidationRecipe")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _normalize_statement(statement: str) -> str:
    return " ".join(statement.strip().split())


def _statement_tokens(statement: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in _TOKEN_RE.findall(statement)
        if len(token) > 1
    )


def _is_negation_of(a: str, b: str) -> bool:
    na = _normalize_statement(a).lower()
    nb = _normalize_statement(b).lower()
    if not na or not nb or na == nb:
        return False
    prefixes = ("not ", "¬", "~", "!")
    for prefix in prefixes:
        if na == f"{prefix}{nb}" or nb == f"{prefix}{na}":
            return True
        stripped_a = na.removeprefix(prefix).strip("() ")
        stripped_b = nb.removeprefix(prefix).strip("() ")
        if stripped_a == nb or stripped_b == na:
            return True
    return False


def is_vacuous_statement(statement: str) -> bool:
    """True when *statement* is tautological / vacuous."""

    normalized = _normalize_statement(statement)
    if normalized in _VACUOUS_STATEMENTS:
        return True
    lower = normalized.lower()
    if lower in {s.lower() for s in _VACUOUS_STATEMENTS}:
        return True
    stripped = lower.strip("()[]{} ")
    return stripped in {s.lower() for s in _VACUOUS_STATEMENTS if s}


def is_contradiction_statement(statement: str) -> bool:
    """True when *statement* is an explicit contradiction."""

    normalized = _normalize_statement(statement)
    if normalized in _CONTRADICTION_MARKERS:
        return True
    lower = normalized.lower()
    stripped = lower.strip("()[]{} ")
    return stripped in {s.lower() for s in _CONTRADICTION_MARKERS if s}


def cap_validation_authority(
    authority: AuthorityCeiling | str,
    *,
    verdict: ValidationVerdict | str = ValidationVerdict.ACCEPTED,
) -> AuthorityCeiling:
    """Cap advertised authority by verdict; never invent theorem-level claims."""

    resolved = _enum(authority, AuthorityCeiling, "authority")
    verdict_resolved = _enum(verdict, ValidationVerdict, "verdict")
    if verdict_resolved is ValidationVerdict.ACCEPTED:
        # Accept may reach satisfiability when solver/kernel holds; never higher
        # without a dedicated attestation/kernel path (out of scope for @1).
        elevated = {
            AuthorityCeiling.SATISFIABILITY,
            AuthorityCeiling.MODEL_CHECK,
            AuthorityCeiling.BOUNDED,
            AuthorityCeiling.MONITOR,
            AuthorityCeiling.CANDIDATE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.NONE,
        }
        if resolved in elevated:
            return resolved
        # Cap reconstruction/attestation/theorem down unless already satisfiability.
        return _ACCEPTED_AUTHORITY_CAP
    if verdict_resolved is ValidationVerdict.BOUNDED:
        if resolved in {
            AuthorityCeiling.BOUNDED,
            AuthorityCeiling.CANDIDATE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.NONE,
            AuthorityCeiling.SATISFIABILITY,
        }:
            return (
                AuthorityCeiling.BOUNDED
                if resolved
                in {
                    AuthorityCeiling.SATISFIABILITY,
                    AuthorityCeiling.BOUNDED,
                }
                else resolved
            )
        return _BOUNDED_AUTHORITY_CAP
    # Rejected / unknown / unavailable → no elevated authority
    if resolved in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }:
        return resolved
    return AuthorityCeiling.CANDIDATE


def may_discharge_graph_node(
    *,
    verdict: ValidationVerdict | str,
    eligibility: DischargeEligibility | str,
    validated: bool,
    stale: bool,
    quarantined: bool,
) -> bool:
    """True only when a candidate is independently validated and eligible.

    Unvalidated, stale, or quarantined candidates **never** discharge a node.
    """

    verdict_r = _enum(verdict, ValidationVerdict, "verdict")
    eligibility_r = _enum(eligibility, DischargeEligibility, "eligibility")
    if not validated or stale or quarantined:
        return False
    if eligibility_r not in {
        DischargeEligibility.ELIGIBLE,
        DischargeEligibility.BOUNDED,
    }:
        return False
    return verdict_r in {
        ValidationVerdict.ACCEPTED,
        ValidationVerdict.BOUNDED,
    }


# ---------------------------------------------------------------------------
# Binding context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationBinding:
    """Exact tree/goal/assumptions/tool/policy/bounds binding for validation.

    A candidate is only accepted when these bindings match the candidate's
    source identity and the hole under validation.
    """

    SCHEMA: ClassVar[str] = VALIDATION_BINDING_SCHEMA

    tree_id: str
    formal_goal_id: str
    assumption_ids: tuple[str, ...] = ()
    tool_id: str = ""
    policy_id: str = ""
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    snapshot_id: str = ""
    graph_node_id: str = ""
    source: SourceSpanBinding = field(default_factory=SourceSpanBinding)
    known_facts: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    premise_ids: tuple[str, ...] = ()
    selected_premise_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tree_id", _text(self.tree_id, "tree_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _string_tuple(self.assumption_ids, "assumption_ids"),
        )
        object.__setattr__(
            self,
            "tool_id",
            _text(self.tool_id, "tool_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "policy_id",
            _text(self.policy_id, "policy_id", optional=True, maximum=256),
        )
        object.__setattr__(self, "bounds", _bounds(self.bounds, "bounds"))
        object.__setattr__(
            self,
            "snapshot_id",
            _text(
                self.snapshot_id, "snapshot_id", optional=True, maximum=256
            ),
        )
        object.__setattr__(
            self,
            "graph_node_id",
            _text(
                self.graph_node_id,
                "graph_node_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self, "source", _source_binding(self.source, "source")
        )
        object.__setattr__(
            self,
            "known_facts",
            _string_tuple(
                self.known_facts, "known_facts", preserve_order=True
            ),
        )
        object.__setattr__(
            self,
            "axioms",
            _string_tuple(self.axioms, "axioms", preserve_order=True),
        )
        object.__setattr__(
            self,
            "premise_ids",
            _string_tuple(self.premise_ids, "premise_ids", preserve_order=True),
        )
        object.__setattr__(
            self,
            "selected_premise_ids",
            _string_tuple(
                self.selected_premise_ids,
                "selected_premise_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def all_known_statements(self) -> tuple[str, ...]:
        return tuple(list(self.known_facts) + list(self.axioms))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "tree_id": self.tree_id,
            "formal_goal_id": self.formal_goal_id,
            "assumption_ids": list(self.assumption_ids),
            "tool_id": self.tool_id,
            "policy_id": self.policy_id,
            "bounds": self.bounds.to_dict(),
            "snapshot_id": self.snapshot_id,
            "graph_node_id": self.graph_node_id,
            "source": self.source.to_dict(),
            "known_facts": list(self.known_facts),
            "axioms": list(self.axioms),
            "premise_ids": list(self.premise_ids),
            "selected_premise_ids": list(self.selected_premise_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationBinding":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError("binding payload must be an object")
        bounds_raw = payload.get("bounds")
        return cls(
            tree_id=payload.get("tree_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            tool_id=payload.get("tool_id", ""),
            policy_id=payload.get("policy_id", ""),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else bounds_raw
            ),
            snapshot_id=payload.get("snapshot_id", ""),
            graph_node_id=payload.get("graph_node_id", ""),
            source=payload.get("source") or {},
            known_facts=tuple(payload.get("known_facts") or ()),
            axioms=tuple(payload.get("axioms") or ()),
            premise_ids=tuple(payload.get("premise_ids") or ()),
            selected_premise_ids=tuple(
                payload.get("selected_premise_ids") or ()
            ),
            metadata=payload.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Replay backend protocol and outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """Truthful result of a solver / model-checker / kernel replay."""

    SCHEMA: ClassVar[str] = REPLAY_OUTCOME_SCHEMA

    status: ReplayStatus
    backend_kind: ReplayBackendKind
    provider_id: str = ""
    provider_version: str = ""
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    evidence_ids: tuple[str, ...] = ()
    core_premise_ids: tuple[str, ...] = ()
    detail: str = ""
    duration_ms: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, ReplayStatus, "status")
        )
        object.__setattr__(
            self,
            "backend_kind",
            _enum(self.backend_kind, ReplayBackendKind, "backend_kind"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "provider_version",
            _text(
                self.provider_version,
                "provider_version",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, AuthorityCeiling, "authority"),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self,
            "core_premise_ids",
            _string_tuple(
                self.core_premise_ids, "core_premise_ids", preserve_order=True
            ),
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=4096),
        )
        object.__setattr__(
            self,
            "duration_ms",
            _nonnegative_int(self.duration_ms, "duration_ms"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "status": self.status.value,
            "backend_kind": self.backend_kind.value,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "authority": self.authority.value,
            "evidence_ids": list(self.evidence_ids),
            "core_premise_ids": list(self.core_premise_ids),
            "detail": self.detail,
            "duration_ms": self.duration_ms,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReplayOutcome":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError("replay outcome must be an object")
        return cls(
            status=payload.get("status", ReplayStatus.UNKNOWN),
            backend_kind=payload.get(
                "backend_kind", ReplayBackendKind.SYNTHETIC
            ),
            provider_id=payload.get("provider_id", ""),
            provider_version=payload.get("provider_version", ""),
            authority=payload.get("authority", AuthorityCeiling.CANDIDATE),
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
            core_premise_ids=tuple(payload.get("core_premise_ids") or ()),
            detail=payload.get("detail", ""),
            duration_ms=int(payload.get("duration_ms") or 0),
            metadata=payload.get("metadata") or {},
        )


@runtime_checkable
class ProofReplayBackend(Protocol):
    """Injectable independent checker used for solver/kernel replay."""

    provider_id: str
    backend_kind: ReplayBackendKind

    def replay(
        self,
        candidate: CandidateProofStep,
        *,
        hole: ProofHole,
        binding: ValidationBinding,
        bounds: ResourceBounds,
        drop_premise_ids: Sequence[str] = (),
    ) -> ReplayOutcome:
        """Replay the candidate obligation; may omit premises for minimality."""
        ...


@dataclass(frozen=True, slots=True)
class StaticReplayBackend:
    """Deterministic in-process replay backend for hermetic tests.

    ``holds_for`` maps candidate_id → whether the full premise set holds.
    ``critical_premises`` maps candidate_id → premise ids that are necessary
    (deletion of any listed premise makes the obligation fail).
    """

    provider_id: str = "provider:static-replay"
    provider_version: str = "1.0.0"
    backend_kind: ReplayBackendKind = ReplayBackendKind.SOLVER
    authority: AuthorityCeiling = AuthorityCeiling.SATISFIABILITY
    holds_for: Mapping[str, bool] = field(default_factory=dict)
    critical_premises: Mapping[str, Sequence[str]] = field(default_factory=dict)
    default_holds: bool = True
    force_status: ReplayStatus | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", maximum=256),
        )
        object.__setattr__(
            self,
            "provider_version",
            _text(
                self.provider_version,
                "provider_version",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(
            self,
            "backend_kind",
            _enum(self.backend_kind, ReplayBackendKind, "backend_kind"),
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, AuthorityCeiling, "authority"),
        )
        if not isinstance(self.holds_for, Mapping):
            raise CandidateValidationError("holds_for must be a mapping")
        normalized_holds = {
            _text(k, "holds_for key", maximum=256): bool(v)
            for k, v in self.holds_for.items()
        }
        object.__setattr__(self, "holds_for", normalized_holds)
        if not isinstance(self.critical_premises, Mapping):
            raise CandidateValidationError("critical_premises must be a mapping")
        normalized_crit: dict[str, tuple[str, ...]] = {}
        for key, values in self.critical_premises.items():
            k = _text(key, "critical_premises key", maximum=256)
            if isinstance(values, str):
                vals = (values,)
            elif isinstance(values, Sequence):
                vals = tuple(
                    _text(v, f"critical_premises[{k}]", maximum=256)
                    for v in values
                )
            else:
                raise CandidateValidationError(
                    f"critical_premises[{k}] must be a sequence"
                )
            normalized_crit[k] = vals
        object.__setattr__(self, "critical_premises", normalized_crit)
        object.__setattr__(
            self, "default_holds", _bool(self.default_holds, "default_holds")
        )
        if self.force_status is not None:
            object.__setattr__(
                self,
                "force_status",
                _enum(self.force_status, ReplayStatus, "force_status"),
            )

    def replay(
        self,
        candidate: CandidateProofStep,
        *,
        hole: ProofHole,
        binding: ValidationBinding,
        bounds: ResourceBounds,
        drop_premise_ids: Sequence[str] = (),
    ) -> ReplayOutcome:
        del hole, bounds  # binding drives premise set; hole already checked
        if self.force_status is not None:
            return ReplayOutcome(
                status=self.force_status,
                backend_kind=self.backend_kind,
                provider_id=self.provider_id,
                provider_version=self.provider_version,
                authority=self.authority,
                detail=f"forced status {self.force_status.value}",
            )

        holds = self.holds_for.get(candidate.candidate_id, self.default_holds)
        critical = tuple(
            self.critical_premises.get(candidate.candidate_id, ())
        )
        dropped = {
            _text(p, "drop_premise_ids", maximum=256)
            for p in (drop_premise_ids or ())
            if p
        }
        if dropped and any(p in dropped for p in critical):
            holds = False
        # If binding.selected_premise_ids empty and we drop from premise_ids
        # that include critical ones, same rule applies.
        if dropped and not critical:
            # Without declared critical set, treat any deletion as unknown
            # minimality rather than inventing a break.
            if drop_premise_ids:
                return ReplayOutcome(
                    status=ReplayStatus.UNKNOWN,
                    backend_kind=self.backend_kind,
                    provider_id=self.provider_id,
                    provider_version=self.provider_version,
                    authority=AuthorityCeiling.BOUNDED,
                    detail="no critical premises declared; deletion effect unknown",
                    metadata={"dropped": sorted(dropped)},
                )

        status = ReplayStatus.HOLDS if holds else ReplayStatus.FAILS
        evidence = (
            (f"evidence:{self.provider_id}:{candidate.candidate_id}",)
            if holds
            else ()
        )
        return ReplayOutcome(
            status=status,
            backend_kind=self.backend_kind,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            authority=self.authority if holds else AuthorityCeiling.CANDIDATE,
            evidence_ids=evidence,
            core_premise_ids=critical if holds else (),
            detail=(
                "obligation holds under full premise set"
                if holds and not dropped
                else (
                    "obligation fails after premise deletion"
                    if not holds and dropped
                    else (
                        "obligation fails under full premise set"
                        if not holds
                        else "obligation holds after non-critical deletion"
                    )
                )
            ),
            metadata={
                "dropped": sorted(dropped),
                "tree_id": binding.tree_id,
            },
        )


@dataclass(frozen=True, slots=True)
class UnavailableReplayBackend:
    """Backend that always reports honest unavailability."""

    provider_id: str = "provider:unavailable"
    backend_kind: ReplayBackendKind = ReplayBackendKind.SOLVER

    def replay(
        self,
        candidate: CandidateProofStep,
        *,
        hole: ProofHole,
        binding: ValidationBinding,
        bounds: ResourceBounds,
        drop_premise_ids: Sequence[str] = (),
    ) -> ReplayOutcome:
        del hole, binding, bounds, drop_premise_ids
        return ReplayOutcome(
            status=ReplayStatus.UNAVAILABLE,
            backend_kind=self.backend_kind,
            provider_id=self.provider_id,
            authority=AuthorityCeiling.NONE,
            detail=f"backend {self.provider_id} unavailable for {candidate.candidate_id}",
        )


# ---------------------------------------------------------------------------
# Checks, minimality, disagreement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    """One named validation stage result."""

    SCHEMA: ClassVar[str] = VALIDATION_CHECK_SCHEMA

    stage: str
    status: ValidationCheckStatus
    detail: str = ""
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stage", _text(self.stage, "stage", maximum=128)
        )
        object.__setattr__(
            self, "status", _enum(self.status, ValidationCheckStatus, "status")
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=4096),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "stage": self.stage,
            "status": self.status.value,
            "detail": self.detail,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationCheck":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError("check payload must be an object")
        return cls(
            stage=payload.get("stage", ""),
            status=payload.get("status", ValidationCheckStatus.UNKNOWN),
            detail=payload.get("detail", ""),
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class MinimalityReport:
    """Deletion / core minimality assessment for selected premises."""

    SCHEMA: ClassVar[str] = MINIMALITY_REPORT_SCHEMA

    kind: MinimalityKind
    checked: bool
    deletion_breaks_proof: bool = False
    redundant_premise_ids: tuple[str, ...] = ()
    critical_premise_ids: tuple[str, ...] = ()
    guarantee_limited: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, MinimalityKind, "kind")
        )
        object.__setattr__(
            self, "checked", _bool(self.checked, "checked")
        )
        object.__setattr__(
            self,
            "deletion_breaks_proof",
            _bool(self.deletion_breaks_proof, "deletion_breaks_proof"),
        )
        object.__setattr__(
            self,
            "redundant_premise_ids",
            _string_tuple(
                self.redundant_premise_ids, "redundant_premise_ids"
            ),
        )
        object.__setattr__(
            self,
            "critical_premise_ids",
            _string_tuple(
                self.critical_premise_ids, "critical_premise_ids"
            ),
        )
        object.__setattr__(
            self,
            "guarantee_limited",
            _bool(self.guarantee_limited, "guarantee_limited"),
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=4096),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "kind": self.kind.value,
            "checked": self.checked,
            "deletion_breaks_proof": self.deletion_breaks_proof,
            "redundant_premise_ids": list(self.redundant_premise_ids),
            "critical_premise_ids": list(self.critical_premise_ids),
            "guarantee_limited": self.guarantee_limited,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MinimalityReport":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError(
                "minimality report payload must be an object"
            )
        return cls(
            kind=payload.get("kind", MinimalityKind.UNKNOWN),
            checked=bool(payload.get("checked", False)),
            deletion_breaks_proof=bool(
                payload.get("deletion_breaks_proof", False)
            ),
            redundant_premise_ids=tuple(
                payload.get("redundant_premise_ids") or ()
            ),
            critical_premise_ids=tuple(
                payload.get("critical_premise_ids") or ()
            ),
            guarantee_limited=bool(payload.get("guarantee_limited", False)),
            detail=payload.get("detail", ""),
        )


@dataclass(frozen=True, slots=True)
class DisagreementRecord:
    """Quarantined multi-provider / multi-backend disagreement."""

    SCHEMA: ClassVar[str] = DISAGREEMENT_RECORD_SCHEMA

    disagreement_id: str
    reason: QuarantineReason
    candidate_id: str
    provider_ids: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disagreement_id",
            _text(self.disagreement_id, "disagreement_id", maximum=256),
        )
        object.__setattr__(
            self, "reason", _enum(self.reason, QuarantineReason, "reason")
        )
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", maximum=256),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids"),
        )
        object.__setattr__(
            self,
            "outcomes",
            _string_tuple(self.outcomes, "outcomes", preserve_order=True),
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=4096),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "disagreement_id": self.disagreement_id,
            "reason": self.reason.value,
            "candidate_id": self.candidate_id,
            "provider_ids": list(self.provider_ids),
            "outcomes": list(self.outcomes),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DisagreementRecord":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError(
                "disagreement payload must be an object"
            )
        return cls(
            disagreement_id=payload.get("disagreement_id", ""),
            reason=payload.get("reason", QuarantineReason.NONE),
            candidate_id=payload.get("candidate_id", ""),
            provider_ids=tuple(payload.get("provider_ids") or ()),
            outcomes=tuple(payload.get("outcomes") or ()),
            detail=payload.get("detail", ""),
        )


# ---------------------------------------------------------------------------
# Request / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """Inputs for independent candidate validation."""

    SCHEMA: ClassVar[str] = VALIDATION_REQUEST_SCHEMA

    candidate: CandidateProofStep
    hole: ProofHole
    binding: ValidationBinding
    recipe: ValidationRecipe | None = None
    expected_candidate_content_id: str = ""
    expected_hole_content_id: str = ""
    proposed_provider_verdicts: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate", _candidate_step(self.candidate, "candidate")
        )
        object.__setattr__(self, "hole", _proof_hole(self.hole, "hole"))
        binding = self.binding
        if isinstance(binding, Mapping):
            binding = ValidationBinding.from_dict(binding)
        elif not isinstance(binding, ValidationBinding):
            raise CandidateValidationError(
                "binding must be a ValidationBinding"
            )
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "recipe", _recipe(self.recipe, "recipe"))
        object.__setattr__(
            self,
            "expected_candidate_content_id",
            _text(
                self.expected_candidate_content_id,
                "expected_candidate_content_id",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(
            self,
            "expected_hole_content_id",
            _text(
                self.expected_hole_content_id,
                "expected_hole_content_id",
                optional=True,
                maximum=128,
            ),
        )
        if not isinstance(self.proposed_provider_verdicts, Mapping):
            raise CandidateValidationError(
                "proposed_provider_verdicts must be a mapping"
            )
        normalized: dict[str, str] = {}
        for key, value in self.proposed_provider_verdicts.items():
            k = _text(key, "proposed_provider_verdicts key", maximum=256)
            v = _text(
                value,
                f"proposed_provider_verdicts[{k}]",
                maximum=64,
            )
            normalized[k] = v
        object.__setattr__(self, "proposed_provider_verdicts", normalized)
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "candidate": self.candidate.to_dict(),
            "hole": self.hole.to_dict(),
            "binding": self.binding.to_dict(),
            "recipe": None if self.recipe is None else self.recipe.to_dict(),
            "expected_candidate_content_id": self.expected_candidate_content_id,
            "expected_hole_content_id": self.expected_hole_content_id,
            "proposed_provider_verdicts": dict(self.proposed_provider_verdicts),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValidationRequest":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError("request payload must be an object")
        binding_raw = payload.get("binding")
        recipe_raw = payload.get("recipe")
        return cls(
            candidate=payload.get("candidate") or {},
            hole=payload.get("hole") or {},
            binding=(
                ValidationBinding.from_dict(binding_raw)
                if isinstance(binding_raw, Mapping)
                else binding_raw
            ),
            recipe=(
                ValidationRecipe.from_dict(recipe_raw)
                if isinstance(recipe_raw, Mapping)
                else recipe_raw
            ),
            expected_candidate_content_id=payload.get(
                "expected_candidate_content_id", ""
            ),
            expected_hole_content_id=payload.get(
                "expected_hole_content_id", ""
            ),
            proposed_provider_verdicts=payload.get(
                "proposed_provider_verdicts"
            )
            or {},
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CandidateValidationResult:
    """Full independent validation outcome for one candidate.

    The embedded :class:`CandidateValidation` is the only status surface
    providers may not write; this result additionally records checks,
    minimality, replay, quarantine, and discharge eligibility.
    """

    SCHEMA: ClassVar[str] = CANDIDATE_VALIDATION_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_CANDIDATE_VALIDATOR_INTERFACE

    result_id: str
    validation: CandidateValidation
    checks: tuple[ValidationCheck, ...] = ()
    minimality_report: MinimalityReport | None = None
    replay_outcomes: tuple[ReplayOutcome, ...] = ()
    discharge_eligibility: DischargeEligibility = DischargeEligibility.INELIGIBLE
    validated: bool = False
    stale: bool = False
    quarantined: bool = False
    disagreement: DisagreementRecord | None = None
    binding_content_id: str = ""
    algorithm_version: str = VALIDATOR_ALGORITHM_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result_id", _text(self.result_id, "result_id", maximum=256)
        )
        validation = self.validation
        if isinstance(validation, Mapping):
            try:
                validation = CandidateValidation.from_dict(validation)
            except TacticianContractError as error:
                raise CandidateValidationError(
                    f"validation: {error}"
                ) from error
        elif not isinstance(validation, CandidateValidation):
            raise CandidateValidationError(
                "validation must be a CandidateValidation"
            )
        object.__setattr__(self, "validation", validation)
        checks: list[ValidationCheck] = []
        for index, raw in enumerate(self.checks or ()):
            if isinstance(raw, ValidationCheck):
                checks.append(raw)
            elif isinstance(raw, Mapping):
                checks.append(ValidationCheck.from_dict(raw))
            else:
                raise CandidateValidationError(
                    f"checks[{index}] must be a ValidationCheck"
                )
        object.__setattr__(self, "checks", tuple(checks))
        report = self.minimality_report
        if report is None:
            pass
        elif isinstance(report, Mapping):
            report = MinimalityReport.from_dict(report)
        elif not isinstance(report, MinimalityReport):
            raise CandidateValidationError(
                "minimality_report must be a MinimalityReport"
            )
        object.__setattr__(self, "minimality_report", report)
        outcomes: list[ReplayOutcome] = []
        for index, raw in enumerate(self.replay_outcomes or ()):
            if isinstance(raw, ReplayOutcome):
                outcomes.append(raw)
            elif isinstance(raw, Mapping):
                outcomes.append(ReplayOutcome.from_dict(raw))
            else:
                raise CandidateValidationError(
                    f"replay_outcomes[{index}] must be a ReplayOutcome"
                )
        object.__setattr__(self, "replay_outcomes", tuple(outcomes))
        object.__setattr__(
            self,
            "discharge_eligibility",
            _enum(
                self.discharge_eligibility,
                DischargeEligibility,
                "discharge_eligibility",
            ),
        )
        object.__setattr__(
            self, "validated", _bool(self.validated, "validated")
        )
        object.__setattr__(self, "stale", _bool(self.stale, "stale"))
        object.__setattr__(
            self, "quarantined", _bool(self.quarantined, "quarantined")
        )
        disagreement = self.disagreement
        if disagreement is None:
            pass
        elif isinstance(disagreement, Mapping):
            disagreement = DisagreementRecord.from_dict(disagreement)
        elif not isinstance(disagreement, DisagreementRecord):
            raise CandidateValidationError(
                "disagreement must be a DisagreementRecord"
            )
        object.__setattr__(self, "disagreement", disagreement)
        object.__setattr__(
            self,
            "binding_content_id",
            _text(
                self.binding_content_id,
                "binding_content_id",
                optional=True,
                maximum=128,
            ),
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(
                self.algorithm_version or VALIDATOR_ALGORITHM_VERSION,
                "algorithm_version",
                maximum=128,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if _bool(self.proof_claimed, "proof_claimed") or _bool(
            self.completion_claimed, "completion_claimed"
        ):
            raise CandidateValidationError(
                "CandidateValidationResult cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def may_discharge(self) -> bool:
        return may_discharge_graph_node(
            verdict=self.validation.verdict,
            eligibility=self.discharge_eligibility,
            validated=self.validated,
            stale=self.stale,
            quarantined=self.quarantined,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "result_id": self.result_id,
            "validation": self.validation.to_dict(),
            "checks": [c.to_dict() for c in self.checks],
            "minimality_report": (
                None
                if self.minimality_report is None
                else self.minimality_report.to_dict()
            ),
            "replay_outcomes": [o.to_dict() for o in self.replay_outcomes],
            "discharge_eligibility": self.discharge_eligibility.value,
            "validated": self.validated,
            "stale": self.stale,
            "quarantined": self.quarantined,
            "disagreement": (
                None
                if self.disagreement is None
                else self.disagreement.to_dict()
            ),
            "binding_content_id": self.binding_content_id,
            "algorithm_version": self.algorithm_version,
            "may_discharge": self.may_discharge,
            "metadata": dict(self.metadata),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "CandidateValidationResult":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError("result payload must be an object")
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise CandidateValidationError(
                "CandidateValidationResult cannot claim proof or completion"
            )
        validation_raw = payload.get("validation")
        report_raw = payload.get("minimality_report")
        disagreement_raw = payload.get("disagreement")
        return cls(
            result_id=payload.get("result_id", ""),
            validation=(
                CandidateValidation.from_dict(validation_raw)
                if isinstance(validation_raw, Mapping)
                else validation_raw
            ),
            checks=tuple(payload.get("checks") or ()),
            minimality_report=(
                MinimalityReport.from_dict(report_raw)
                if isinstance(report_raw, Mapping)
                else report_raw
            ),
            replay_outcomes=tuple(payload.get("replay_outcomes") or ()),
            discharge_eligibility=payload.get(
                "discharge_eligibility", DischargeEligibility.INELIGIBLE
            ),
            validated=bool(payload.get("validated", False)),
            stale=bool(payload.get("stale", False)),
            quarantined=bool(payload.get("quarantined", False)),
            disagreement=(
                DisagreementRecord.from_dict(disagreement_raw)
                if isinstance(disagreement_raw, Mapping)
                else disagreement_raw
            ),
            binding_content_id=payload.get("binding_content_id", ""),
            algorithm_version=payload.get(
                "algorithm_version", VALIDATOR_ALGORITHM_VERSION
            ),
            metadata=payload.get("metadata") or {},
            proof_claimed=False,
            completion_claimed=False,
        )


@dataclass(frozen=True, slots=True)
class CandidateSetValidationResult:
    """Validation of a candidate set with quarantine of disagreement."""

    SCHEMA: ClassVar[str] = CANDIDATE_SET_VALIDATION_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_CANDIDATE_VALIDATOR_INTERFACE

    set_result_id: str
    results: tuple[CandidateValidationResult, ...] = ()
    accepted_candidate_ids: tuple[str, ...] = ()
    rejected_candidate_ids: tuple[str, ...] = ()
    quarantined_candidate_ids: tuple[str, ...] = ()
    dischargeable_candidate_ids: tuple[str, ...] = ()
    disagreements: tuple[DisagreementRecord, ...] = ()
    algorithm_version: str = VALIDATOR_ALGORITHM_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "set_result_id",
            _text(self.set_result_id, "set_result_id", maximum=256),
        )
        results: list[CandidateValidationResult] = []
        for index, raw in enumerate(self.results or ()):
            if isinstance(raw, CandidateValidationResult):
                results.append(raw)
            elif isinstance(raw, Mapping):
                results.append(CandidateValidationResult.from_dict(raw))
            else:
                raise CandidateValidationError(
                    f"results[{index}] must be a CandidateValidationResult"
                )
        object.__setattr__(self, "results", tuple(results))
        object.__setattr__(
            self,
            "accepted_candidate_ids",
            _string_tuple(
                self.accepted_candidate_ids, "accepted_candidate_ids"
            ),
        )
        object.__setattr__(
            self,
            "rejected_candidate_ids",
            _string_tuple(
                self.rejected_candidate_ids, "rejected_candidate_ids"
            ),
        )
        object.__setattr__(
            self,
            "quarantined_candidate_ids",
            _string_tuple(
                self.quarantined_candidate_ids, "quarantined_candidate_ids"
            ),
        )
        object.__setattr__(
            self,
            "dischargeable_candidate_ids",
            _string_tuple(
                self.dischargeable_candidate_ids,
                "dischargeable_candidate_ids",
            ),
        )
        disagreements: list[DisagreementRecord] = []
        for index, raw in enumerate(self.disagreements or ()):
            if isinstance(raw, DisagreementRecord):
                disagreements.append(raw)
            elif isinstance(raw, Mapping):
                disagreements.append(DisagreementRecord.from_dict(raw))
            else:
                raise CandidateValidationError(
                    f"disagreements[{index}] must be a DisagreementRecord"
                )
        object.__setattr__(self, "disagreements", tuple(disagreements))
        object.__setattr__(
            self,
            "algorithm_version",
            _text(
                self.algorithm_version or VALIDATOR_ALGORITHM_VERSION,
                "algorithm_version",
                maximum=128,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        if _bool(self.proof_claimed, "proof_claimed") or _bool(
            self.completion_claimed, "completion_claimed"
        ):
            raise CandidateValidationError(
                "CandidateSetValidationResult cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "set_result_id": self.set_result_id,
            "results": [r.to_dict() for r in self.results],
            "accepted_candidate_ids": list(self.accepted_candidate_ids),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "quarantined_candidate_ids": list(self.quarantined_candidate_ids),
            "dischargeable_candidate_ids": list(
                self.dischargeable_candidate_ids
            ),
            "disagreements": [d.to_dict() for d in self.disagreements],
            "algorithm_version": self.algorithm_version,
            "metadata": dict(self.metadata),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "CandidateSetValidationResult":
        if not isinstance(payload, Mapping):
            raise CandidateValidationError(
                "set result payload must be an object"
            )
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise CandidateValidationError(
                "CandidateSetValidationResult cannot claim proof or completion"
            )
        return cls(
            set_result_id=payload.get("set_result_id", ""),
            results=tuple(payload.get("results") or ()),
            accepted_candidate_ids=tuple(
                payload.get("accepted_candidate_ids") or ()
            ),
            rejected_candidate_ids=tuple(
                payload.get("rejected_candidate_ids") or ()
            ),
            quarantined_candidate_ids=tuple(
                payload.get("quarantined_candidate_ids") or ()
            ),
            dischargeable_candidate_ids=tuple(
                payload.get("dischargeable_candidate_ids") or ()
            ),
            disagreements=tuple(payload.get("disagreements") or ()),
            algorithm_version=payload.get(
                "algorithm_version", VALIDATOR_ALGORITHM_VERSION
            ),
            metadata=payload.get("metadata") or {},
            proof_claimed=False,
            completion_claimed=False,
        )


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _check_parse_type(
    candidate: CandidateProofStep,
    hole: ProofHole,
) -> ValidationCheck:
    """Structural / type validity of the candidate against the hole."""

    if not candidate.candidate_id or not candidate.hole_id:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail="candidate_id and hole_id are required",
        )
    if candidate.hole_id != hole.hole_id:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail=(
                f"candidate targets hole {candidate.hole_id!r} but request "
                f"supplies {hole.hole_id!r}"
            ),
        )
    if candidate.status in _TERMINAL_CANDIDATE_STATUSES:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail=f"candidate status {candidate.status.value} is terminal",
        )
    if candidate.proof_claimed or candidate.completion_claimed:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail="candidate must not claim proof or completion",
        )
    if candidate.authority not in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail="candidate authority exceeds candidate ceiling",
        )
    if not candidate.statement.strip():
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail="candidate statement is empty",
        )
    if hole.status in _NON_DISCHARGEABLE_HOLE_STATUSES and hole.status is not HoleStatus.DISCHARGED:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail=f"hole status {hole.status.value} is non-dischargeable",
        )
    if hole.kind in _NON_PROOF_HOLE_KINDS:
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail=f"hole kind {hole.kind.value} is a non-proof diagnostic",
        )
    # Statement must be parseable as non-empty identifier-bearing text.
    if not _statement_tokens(candidate.statement) and not any(
        ch.isalnum() for ch in candidate.statement
    ):
        return ValidationCheck(
            stage="parse_type",
            status=ValidationCheckStatus.FAIL,
            detail="candidate statement has no parseable tokens",
        )
    return ValidationCheck(
        stage="parse_type",
        status=ValidationCheckStatus.PASS,
        detail="candidate parses and types against hole",
    )


def _check_exact_binding(
    candidate: CandidateProofStep,
    hole: ProofHole,
    binding: ValidationBinding,
    recipe: ValidationRecipe | None,
) -> ValidationCheck:
    """Require exact tree/goal/assumptions/tool/policy/bounds bindings."""

    problems: list[str] = []

    # Tree binding: candidate source, hole source, and request binding.
    if not binding.tree_id:
        problems.append("binding.tree_id is required")
    cand_tree = candidate.source.tree_id
    hole_tree = hole.source.tree_id
    if cand_tree and cand_tree != binding.tree_id:
        problems.append(
            f"candidate tree_id {cand_tree!r} != binding {binding.tree_id!r}"
        )
    if hole_tree and hole_tree != binding.tree_id:
        problems.append(
            f"hole tree_id {hole_tree!r} != binding {binding.tree_id!r}"
        )

    # Goal binding
    if not binding.formal_goal_id:
        problems.append("binding.formal_goal_id is required")
    if hole.formal_goal_id and hole.formal_goal_id != binding.formal_goal_id:
        problems.append(
            f"hole formal_goal_id {hole.formal_goal_id!r} != binding "
            f"{binding.formal_goal_id!r}"
        )

    # Snapshot / source scope when declared
    if binding.snapshot_id:
        if (
            candidate.source.snapshot_id
            and candidate.source.snapshot_id != binding.snapshot_id
        ):
            problems.append(
                f"candidate snapshot {candidate.source.snapshot_id!r} != "
                f"binding {binding.snapshot_id!r}"
            )
        if (
            hole.source.snapshot_id
            and hole.source.snapshot_id != binding.snapshot_id
        ):
            problems.append(
                f"hole snapshot {hole.source.snapshot_id!r} != binding "
                f"{binding.snapshot_id!r}"
            )

    # Assumption ids: candidate new assumptions must be subset of binding
    # (or explicitly listed — binding may declare the full open set).
    if candidate.new_assumption_ids and binding.assumption_ids:
        extra = set(candidate.new_assumption_ids) - set(binding.assumption_ids)
        if extra:
            problems.append(
                f"candidate assumptions not bound: {sorted(extra)}"
            )

    # Tool binding from recipe / binding / candidate providers
    tool = binding.tool_id
    if recipe is not None and recipe.provider_ids:
        if tool and tool not in recipe.provider_ids:
            # tool_id may be a logical tool name; also accept membership in
            # candidate providers when it matches recipe.
            if tool not in candidate.provider_ids:
                problems.append(
                    f"tool_id {tool!r} not in recipe providers "
                    f"{list(recipe.provider_ids)}"
                )
        # When tool is empty, bind first recipe provider as expected tool
        # without failing — exactness means "if declared, must match".
    if tool and candidate.provider_ids and tool not in candidate.provider_ids:
        # Allow tool_id to be a family name not listed on the candidate
        # only when recipe is absent; when recipe present, already checked.
        if recipe is None:
            problems.append(
                f"tool_id {tool!r} not among candidate providers "
                f"{list(candidate.provider_ids)}"
            )

    # Policy: if policy_id declared, bounds.network_allowed and extras must
    # not violate a fail-closed offline policy (default).
    if binding.policy_id:
        if (
            "offline" in binding.policy_id.lower()
            or "hermetic" in binding.policy_id.lower()
        ):
            if binding.bounds.network_allowed:
                problems.append(
                    "hermetic/offline policy forbids network_allowed bounds"
                )
            if candidate.provenance.get("network_allowed") is True:
                problems.append(
                    "hermetic/offline policy forbids networked candidate"
                )

    # Bounds: hole bounds must not exceed binding bounds when both set.
    hb = hole.bounds
    bb = binding.bounds
    if hb.wall_time_ms and bb.wall_time_ms and hb.wall_time_ms > bb.wall_time_ms:
        problems.append(
            f"hole wall_time_ms {hb.wall_time_ms} exceeds binding "
            f"{bb.wall_time_ms}"
        )
    if (
        hb.max_candidates
        and bb.max_candidates
        and hb.max_candidates > bb.max_candidates
    ):
        problems.append(
            f"hole max_candidates {hb.max_candidates} exceeds binding "
            f"{bb.max_candidates}"
        )
    if bb.network_allowed is False and hb.network_allowed is True:
        problems.append("hole allows network but binding forbids it")

    # Source span: if binding source has refs, candidate/hole should overlap
    if binding.source.source_ref_ids:
        cand_refs = set(candidate.source.source_ref_ids)
        hole_refs = set(hole.source.source_ref_ids)
        bind_refs = set(binding.source.source_ref_ids)
        if cand_refs and cand_refs.isdisjoint(bind_refs):
            problems.append("candidate source_ref_ids disjoint from binding")
        if hole_refs and hole_refs.isdisjoint(bind_refs):
            problems.append("hole source_ref_ids disjoint from binding")

    if problems:
        return ValidationCheck(
            stage="exact_binding",
            status=ValidationCheckStatus.FAIL,
            detail="; ".join(problems),
        )
    return ValidationCheck(
        stage="exact_binding",
        status=ValidationCheckStatus.PASS,
        detail=(
            f"bound tree={binding.tree_id} goal={binding.formal_goal_id} "
            f"tool={binding.tool_id or 'unset'} "
            f"policy={binding.policy_id or 'unset'}"
        ),
    )


def _check_stale(
    candidate: CandidateProofStep,
    hole: ProofHole,
    *,
    expected_candidate_content_id: str,
    expected_hole_content_id: str,
) -> ValidationCheck:
    """Reject stale candidates whose content identity no longer matches."""

    if expected_candidate_content_id:
        actual = candidate.content_id
        if actual != expected_candidate_content_id:
            return ValidationCheck(
                stage="stale_freshness",
                status=ValidationCheckStatus.FAIL,
                detail=(
                    f"stale candidate: content_id {actual} != expected "
                    f"{expected_candidate_content_id}"
                ),
            )
    if expected_hole_content_id:
        actual = hole.content_id
        if actual != expected_hole_content_id:
            return ValidationCheck(
                stage="stale_freshness",
                status=ValidationCheckStatus.FAIL,
                detail=(
                    f"stale hole: content_id {actual} != expected "
                    f"{expected_hole_content_id}"
                ),
            )
    # Superseded candidates are always stale for discharge purposes.
    if candidate.status is CandidateStatus.SUPERSEDED:
        return ValidationCheck(
            stage="stale_freshness",
            status=ValidationCheckStatus.FAIL,
            detail="candidate status is superseded (stale)",
        )
    return ValidationCheck(
        stage="stale_freshness",
        status=ValidationCheckStatus.PASS,
        detail="candidate and hole content identities are current",
    )


def _check_consistency(
    candidate: CandidateProofStep,
    binding: ValidationBinding,
) -> ValidationCheck:
    statement = candidate.statement
    if is_contradiction_statement(statement):
        return ValidationCheck(
            stage="consistency",
            status=ValidationCheckStatus.FAIL,
            detail="candidate statement is an explicit contradiction",
        )
    for known in binding.all_known_statements():
        if _is_negation_of(statement, known):
            return ValidationCheck(
                stage="consistency",
                status=ValidationCheckStatus.FAIL,
                detail=f"inconsistent with known statement {known!r}",
            )
    return ValidationCheck(
        stage="consistency",
        status=ValidationCheckStatus.PASS,
        detail="candidate is consistent with bound theory facts/axioms",
    )


def _check_non_vacuity(candidate: CandidateProofStep) -> ValidationCheck:
    if is_vacuous_statement(candidate.statement):
        return ValidationCheck(
            stage="non_vacuity",
            status=ValidationCheckStatus.FAIL,
            detail="vacuous/tautological candidate rejected",
        )
    return ValidationCheck(
        stage="non_vacuity",
        status=ValidationCheckStatus.PASS,
        detail="candidate is non-vacuous",
    )


def _check_non_circularity(
    candidate: CandidateProofStep,
    hole: ProofHole,
    binding: ValidationBinding,
) -> ValidationCheck:
    ns = _normalize_statement(candidate.statement).lower()
    # Circular: restates open hole obligation as sole content for fact holes
    if hole.statement:
        hole_norm = _normalize_statement(hole.statement).lower()
        if hole_norm and ns == hole_norm:
            if hole.kind in {
                HoleKind.MISSING_SOURCE_FACT,
                HoleKind.MISSING_EVIDENCE,
                HoleKind.OTHER,
            }:
                return ValidationCheck(
                    stage="non_circularity",
                    status=ValidationCheckStatus.FAIL,
                    detail="candidate restates the open obligation (circular)",
                )
    # Circular: assumes the formal goal itself
    goal = binding.formal_goal_id.strip().lower()
    if goal and (
        ns == goal
        or ns == f"assume {goal}"
        or ns == f"goal:{goal}"
        or ns in {"goal", "the goal", "target", "end_goal", "formal_goal"}
    ):
        return ValidationCheck(
            stage="non_circularity",
            status=ValidationCheckStatus.FAIL,
            detail="candidate is a goal-entailing circular assumption",
        )
    # Self-dependency via provenance dependency list
    deps = candidate.provenance.get("dependency_ids")
    if isinstance(deps, Sequence) and not isinstance(deps, (str, bytes)):
        if candidate.candidate_id in deps:
            return ValidationCheck(
                stage="non_circularity",
                status=ValidationCheckStatus.FAIL,
                detail="candidate lists itself as a dependency (circular)",
            )
        if hole.hole_id in deps and candidate.hole_id == hole.hole_id:
            # Depending only on the same hole without external support is circular
            if set(deps) <= {hole.hole_id, candidate.candidate_id}:
                return ValidationCheck(
                    stage="non_circularity",
                    status=ValidationCheckStatus.FAIL,
                    detail="candidate depends only on its target hole",
                )
    return ValidationCheck(
        stage="non_circularity",
        status=ValidationCheckStatus.PASS,
        detail="candidate is non-circular under bound goal/hole",
    )


def _run_replay(
    backends: Sequence[ProofReplayBackend],
    candidate: CandidateProofStep,
    *,
    hole: ProofHole,
    binding: ValidationBinding,
    bounds: ResourceBounds,
    drop_premise_ids: Sequence[str] = (),
) -> tuple[ValidationCheck, tuple[ReplayOutcome, ...]]:
    if not backends:
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.UNAVAILABLE,
                detail="no replay backend registered; authority remains unknown",
            ),
            (),
        )

    outcomes: list[ReplayOutcome] = []
    for backend in backends:
        try:
            outcome = backend.replay(
                candidate,
                hole=hole,
                binding=binding,
                bounds=bounds,
                drop_premise_ids=drop_premise_ids,
            )
        except Exception as error:  # pragma: no cover - defensive
            outcomes.append(
                ReplayOutcome(
                    status=ReplayStatus.ERROR,
                    backend_kind=getattr(
                        backend, "backend_kind", ReplayBackendKind.SYNTHETIC
                    ),
                    provider_id=getattr(backend, "provider_id", "provider:error"),
                    detail=str(error)[:512],
                )
            )
            continue
        if not isinstance(outcome, ReplayOutcome):
            if isinstance(outcome, Mapping):
                outcome = ReplayOutcome.from_dict(outcome)
            else:
                outcomes.append(
                    ReplayOutcome(
                        status=ReplayStatus.ERROR,
                        backend_kind=ReplayBackendKind.SYNTHETIC,
                        provider_id=getattr(
                            backend, "provider_id", "provider:error"
                        ),
                        detail="backend returned non-ReplayOutcome",
                    )
                )
                continue
        outcomes.append(outcome)

    statuses = {o.status for o in outcomes}
    if ReplayStatus.HOLDS in statuses and ReplayStatus.FAILS in statuses:
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.QUARANTINED,
                detail="backends disagree on holds vs fails; quarantined",
                evidence_ids=tuple(
                    eid for o in outcomes for eid in o.evidence_ids
                ),
            ),
            tuple(outcomes),
        )
    if all(o.status is ReplayStatus.UNAVAILABLE for o in outcomes):
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.UNAVAILABLE,
                detail="all replay backends unavailable",
            ),
            tuple(outcomes),
        )
    if any(o.status is ReplayStatus.HOLDS for o in outcomes) and not any(
        o.status is ReplayStatus.FAILS for o in outcomes
    ):
        evidence = tuple(eid for o in outcomes for eid in o.evidence_ids)
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.PASS,
                detail="replay holds under at least one backend",
                evidence_ids=evidence,
            ),
            tuple(outcomes),
        )
    if any(o.status is ReplayStatus.FAILS for o in outcomes):
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.FAIL,
                detail="replay fails under independent checker",
            ),
            tuple(outcomes),
        )
    if any(o.status is ReplayStatus.BOUNDED for o in outcomes):
        return (
            ValidationCheck(
                stage="replay",
                status=ValidationCheckStatus.PASS,
                detail="replay holds only under declared bounds",
                evidence_ids=tuple(
                    eid for o in outcomes for eid in o.evidence_ids
                ),
            ),
            tuple(outcomes),
        )
    # UNKNOWN / TIMEOUT / ERROR → honest unknown
    return (
        ValidationCheck(
            stage="replay",
            status=ValidationCheckStatus.UNKNOWN,
            detail="replay returned unknown/timeout/error; not accepted as proof",
        ),
        tuple(outcomes),
    )


def _check_minimality(
    backends: Sequence[ProofReplayBackend],
    candidate: CandidateProofStep,
    *,
    hole: ProofHole,
    binding: ValidationBinding,
    bounds: ResourceBounds,
    full_outcomes: Sequence[ReplayOutcome],
) -> tuple[ValidationCheck, MinimalityReport]:
    """Deletion minimality: dropping a selected premise should break the proof.

    For small premise sets we test each selected premise.  If no selected
    premises are declared, or backends cannot assess deletion, the receipt
    explicitly limits its guarantee (``BOUNDED`` / ``not_applicable``).
    """

    selected = list(binding.selected_premise_ids) or list(binding.premise_ids)
    # Also consider candidate-local premise ids from provenance.
    prov_premises = candidate.provenance.get("premise_ids")
    if isinstance(prov_premises, Sequence) and not isinstance(
        prov_premises, (str, bytes)
    ):
        for item in prov_premises:
            if isinstance(item, str) and item and item not in selected:
                selected.append(item)

    if not backends:
        report = MinimalityReport(
            kind=MinimalityKind.NOT_APPLICABLE,
            checked=False,
            guarantee_limited=True,
            detail="no backend to assess deletion minimality; guarantee limited",
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.SKIP,
                detail=report.detail,
            ),
            report,
        )

    # Only meaningful if full replay held.
    full_holds = any(o.status is ReplayStatus.HOLDS for o in full_outcomes)
    if not full_holds:
        report = MinimalityReport(
            kind=MinimalityKind.NOT_APPLICABLE,
            checked=False,
            guarantee_limited=True,
            detail="full replay did not hold; minimality not assessed",
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.SKIP,
                detail=report.detail,
            ),
            report,
        )

    if not selected:
        report = MinimalityReport(
            kind=MinimalityKind.BOUNDED,
            checked=False,
            guarantee_limited=True,
            detail=(
                "no selected premises declared; minimality guarantee explicitly "
                "limited to bounded acceptance"
            ),
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.PASS,
                detail=report.detail,
            ),
            report,
        )

    # Small cases only (resource-bounded).
    max_checks = min(len(selected), max(1, bounds.max_steps or 8), 8)
    critical: list[str] = []
    redundant: list[str] = []
    unknown = False
    for premise_id in selected[:max_checks]:
        check, deletion_outcomes = _run_replay(
            backends,
            candidate,
            hole=hole,
            binding=binding,
            bounds=bounds,
            drop_premise_ids=(premise_id,),
        )
        del check
        if any(o.status is ReplayStatus.FAILS for o in deletion_outcomes):
            critical.append(premise_id)
        elif any(o.status is ReplayStatus.HOLDS for o in deletion_outcomes):
            redundant.append(premise_id)
        else:
            unknown = True

    if critical and not redundant and not unknown:
        report = MinimalityReport(
            kind=MinimalityKind.LOCAL,
            checked=True,
            deletion_breaks_proof=True,
            critical_premise_ids=tuple(critical),
            redundant_premise_ids=(),
            guarantee_limited=False,
            detail=(
                "deletion of each checked selected premise breaks the proof "
                f"(local core: {critical})"
            ),
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.PASS,
                detail=report.detail,
            ),
            report,
        )

    if critical:
        # Partial core: some critical, some redundant/unknown → subset/bounded
        kind = MinimalityKind.SUBSET if not unknown else MinimalityKind.BOUNDED
        report = MinimalityReport(
            kind=kind,
            checked=True,
            deletion_breaks_proof=True,
            critical_premise_ids=tuple(critical),
            redundant_premise_ids=tuple(redundant),
            guarantee_limited=bool(unknown or redundant),
            detail=(
                f"critical={critical}; redundant={redundant}; "
                f"unknown={unknown}; guarantee_limited={bool(unknown or redundant)}"
            ),
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.PASS,
                detail=report.detail,
            ),
            report,
        )

    if redundant and not critical:
        # Deletion does not break proof → not minimal; fail closed for ACCEPT
        # but allow BOUNDED with limited guarantee.
        report = MinimalityReport(
            kind=MinimalityKind.BOUNDED,
            checked=True,
            deletion_breaks_proof=False,
            critical_premise_ids=(),
            redundant_premise_ids=tuple(redundant),
            guarantee_limited=True,
            detail=(
                "selected premises are redundant under deletion; "
                "acceptance guarantee limited"
            ),
        )
        return (
            ValidationCheck(
                stage="minimality",
                status=ValidationCheckStatus.PASS,
                detail=report.detail,
            ),
            report,
        )

    report = MinimalityReport(
        kind=MinimalityKind.UNKNOWN,
        checked=True,
        deletion_breaks_proof=False,
        guarantee_limited=True,
        detail="deletion effects unknown; guarantee explicitly limited",
    )
    return (
        ValidationCheck(
            stage="minimality",
            status=ValidationCheckStatus.UNKNOWN,
            detail=report.detail,
        ),
        report,
    )


def _detect_provider_disagreement(
    candidate: CandidateProofStep,
    proposed_provider_verdicts: Mapping[str, str],
    replay_outcomes: Sequence[ReplayOutcome],
) -> DisagreementRecord | None:
    """Quarantine when providers or backends disagree on accept/reject."""

    # Provider-proposed verdicts (advisory only — never authoritative alone).
    if proposed_provider_verdicts:
        normalized = {
            k: v.strip().lower()
            for k, v in proposed_provider_verdicts.items()
            if v
        }
        accept_like = {
            "accepted",
            "accept",
            "holds",
            "pass",
            "true",
            "ok",
        }
        reject_like = {
            "rejected",
            "reject",
            "fails",
            "fail",
            "false",
            "error",
        }
        has_accept = any(v in accept_like for v in normalized.values())
        has_reject = any(v in reject_like for v in normalized.values())
        if has_accept and has_reject:
            return DisagreementRecord(
                disagreement_id=_stable_id(
                    "disagree",
                    candidate.candidate_id,
                    "provider",
                    *sorted(normalized),
                ),
                reason=QuarantineReason.PROVIDER_DISAGREEMENT,
                candidate_id=candidate.candidate_id,
                provider_ids=tuple(sorted(normalized)),
                outcomes=tuple(
                    f"{k}:{v}" for k, v in sorted(normalized.items())
                ),
                detail="proposed provider verdicts disagree; quarantined",
            )

    # Replay backend disagreement already handled at check level; record it.
    statuses = {o.status for o in replay_outcomes}
    if ReplayStatus.HOLDS in statuses and ReplayStatus.FAILS in statuses:
        return DisagreementRecord(
            disagreement_id=_stable_id(
                "disagree",
                candidate.candidate_id,
                "replay",
                *[o.provider_id for o in replay_outcomes],
            ),
            reason=QuarantineReason.REPLAY_DISAGREEMENT,
            candidate_id=candidate.candidate_id,
            provider_ids=tuple(
                sorted({o.provider_id for o in replay_outcomes if o.provider_id})
            ),
            outcomes=tuple(
                f"{o.provider_id}:{o.status.value}" for o in replay_outcomes
            ),
            detail="independent replay backends disagree; quarantined",
        )
    return None


def _decide_verdict(
    checks: Sequence[ValidationCheck],
    *,
    minimality: MinimalityReport | None,
    replay_outcomes: Sequence[ReplayOutcome],
    quarantined: bool,
    stale: bool,
) -> tuple[
    ValidationVerdict,
    AuthorityCeiling,
    DischargeEligibility,
    str,
    bool,
]:
    """Deterministic verdict synthesis from stage results.

    Returns (verdict, authority, eligibility, minimality_label, validated).
    """

    by_stage = {c.stage: c for c in checks}

    if quarantined:
        return (
            ValidationVerdict.INCONCLUSIVE,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.QUARANTINED,
            minimality.kind.value if minimality else "unknown",
            True,  # independently assessed (quarantined is a validation outcome)
        )
    if stale:
        return (
            ValidationVerdict.REJECTED,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.STALE,
            minimality.kind.value if minimality else "unknown",
            True,
        )

    # Hard fail stages
    hard = (
        "parse_type",
        "exact_binding",
        "consistency",
        "non_vacuity",
        "non_circularity",
    )
    for stage in hard:
        check = by_stage.get(stage)
        if check is not None and check.status is ValidationCheckStatus.FAIL:
            return (
                ValidationVerdict.REJECTED,
                AuthorityCeiling.CANDIDATE,
                DischargeEligibility.INELIGIBLE,
                minimality.kind.value if minimality else "unknown",
                True,
            )

    stale_check = by_stage.get("stale_freshness")
    if (
        stale_check is not None
        and stale_check.status is ValidationCheckStatus.FAIL
    ):
        return (
            ValidationVerdict.REJECTED,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.STALE,
            minimality.kind.value if minimality else "unknown",
            True,
        )

    replay = by_stage.get("replay")
    if replay is None:
        return (
            ValidationVerdict.UNKNOWN,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.INELIGIBLE,
            minimality.kind.value if minimality else "unknown",
            True,
        )

    if replay.status is ValidationCheckStatus.FAIL:
        return (
            ValidationVerdict.REJECTED,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.INELIGIBLE,
            minimality.kind.value if minimality else "unknown",
            True,
        )
    if replay.status is ValidationCheckStatus.QUARANTINED:
        return (
            ValidationVerdict.INCONCLUSIVE,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.QUARANTINED,
            minimality.kind.value if minimality else "unknown",
            True,
        )
    if replay.status is ValidationCheckStatus.UNAVAILABLE:
        return (
            ValidationVerdict.UNAVAILABLE,
            AuthorityCeiling.NONE,
            DischargeEligibility.INELIGIBLE,
            minimality.kind.value if minimality else "not_applicable",
            True,
        )
    if replay.status is ValidationCheckStatus.UNKNOWN:
        return (
            ValidationVerdict.UNKNOWN,
            AuthorityCeiling.CANDIDATE,
            DischargeEligibility.INELIGIBLE,
            minimality.kind.value if minimality else "unknown",
            True,
        )

    # Replay passed (holds or bounded).
    holds_outcomes = [
        o for o in replay_outcomes if o.status is ReplayStatus.HOLDS
    ]
    bounded_outcomes = [
        o for o in replay_outcomes if o.status is ReplayStatus.BOUNDED
    ]
    authority = AuthorityCeiling.BOUNDED
    if holds_outcomes:
        # Prefer highest non-forbidden authority from holding backends.
        for outcome in holds_outcomes:
            authority = outcome.authority
            break
        authority = cap_validation_authority(
            authority, verdict=ValidationVerdict.ACCEPTED
        )
    elif bounded_outcomes:
        authority = cap_validation_authority(
            AuthorityCeiling.BOUNDED, verdict=ValidationVerdict.BOUNDED
        )

    guarantee_limited = bool(
        minimality is not None and minimality.guarantee_limited
    )
    if (
        minimality is not None
        and minimality.checked
        and minimality.deletion_breaks_proof
        and not guarantee_limited
        and holds_outcomes
    ):
        return (
            ValidationVerdict.ACCEPTED,
            authority,
            DischargeEligibility.ELIGIBLE,
            minimality.kind.value,
            True,
        )

    # Replay holds but minimality limited or not fully established → BOUNDED
    if holds_outcomes or bounded_outcomes:
        return (
            ValidationVerdict.BOUNDED,
            cap_validation_authority(
                AuthorityCeiling.BOUNDED, verdict=ValidationVerdict.BOUNDED
            ),
            DischargeEligibility.BOUNDED,
            (
                minimality.kind.value
                if minimality is not None
                else MinimalityKind.BOUNDED.value
            ),
            True,
        )

    return (
        ValidationVerdict.INCONCLUSIVE,
        AuthorityCeiling.CANDIDATE,
        DischargeEligibility.INELIGIBLE,
        minimality.kind.value if minimality else "unknown",
        True,
    )


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofCandidateValidator:
    """Deterministic independent validator for proof-gap candidates.

    Interface: ``ProofCandidateValidator@1``

    Providers may propose evidence and advisory verdicts, but only this
    engine writes :class:`CandidateValidation` status.  Unvalidated and
    stale candidates never discharge graph nodes.
    """

    INTERFACE: ClassVar[str] = PROOF_CANDIDATE_VALIDATOR_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = VALIDATOR_ALGORITHM_VERSION

    backends: tuple[ProofReplayBackend, ...] = ()
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    require_replay_for_accept: bool = True
    validator_id: str = "validator:proof-candidate"

    def __post_init__(self) -> None:
        normalized: list[Any] = []
        for index, backend in enumerate(self.backends or ()):
            if not hasattr(backend, "replay"):
                raise CandidateValidationError(
                    f"backends[{index}] must provide replay(...)"
                )
            normalized.append(backend)
        object.__setattr__(self, "backends", tuple(normalized))
        object.__setattr__(self, "bounds", _bounds(self.bounds, "bounds"))
        object.__setattr__(
            self,
            "require_replay_for_accept",
            _bool(
                self.require_replay_for_accept, "require_replay_for_accept"
            ),
        )
        object.__setattr__(
            self,
            "validator_id",
            _text(self.validator_id, "validator_id", maximum=256),
        )

    def validate(
        self,
        request: ValidationRequest | Mapping[str, Any],
        *,
        bounds: ResourceBounds | Mapping[str, Any] | None = None,
    ) -> CandidateValidationResult:
        """Validate a single candidate under exact bindings."""

        if isinstance(request, Mapping):
            request = ValidationRequest.from_dict(request)
        elif not isinstance(request, ValidationRequest):
            raise CandidateValidationError(
                "request must be a ValidationRequest"
            )

        active_bounds = _bounds(
            bounds if bounds is not None else self.bounds, "bounds"
        )
        # Prefer recipe bounds when tighter.
        recipe = request.recipe or request.hole.validation_recipe
        if recipe is not None and recipe.bounds.wall_time_ms:
            if (
                not active_bounds.wall_time_ms
                or recipe.bounds.wall_time_ms < active_bounds.wall_time_ms
            ):
                active_bounds = recipe.bounds

        candidate = request.candidate
        hole = request.hole
        binding = request.binding

        checks: list[ValidationCheck] = []

        # 1. Parse / type
        checks.append(_check_parse_type(candidate, hole))
        if checks[-1].status is ValidationCheckStatus.FAIL:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=None,
                forced_stale=False,
                forced_quarantine=False,
            )

        # 2. Exact binding
        checks.append(
            _check_exact_binding(candidate, hole, binding, recipe)
        )
        if checks[-1].status is ValidationCheckStatus.FAIL:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=None,
                forced_stale=False,
                forced_quarantine=False,
            )

        # 3. Stale / freshness
        stale_check = _check_stale(
            candidate,
            hole,
            expected_candidate_content_id=request.expected_candidate_content_id,
            expected_hole_content_id=request.expected_hole_content_id,
        )
        checks.append(stale_check)
        stale = stale_check.status is ValidationCheckStatus.FAIL
        if stale:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=DisagreementRecord(
                    disagreement_id=_stable_id(
                        "disagree", candidate.candidate_id, "stale"
                    ),
                    reason=QuarantineReason.STALE_CANDIDATE,
                    candidate_id=candidate.candidate_id,
                    detail=stale_check.detail,
                ),
                forced_stale=True,
                forced_quarantine=False,
            )

        # 4. Consistency
        checks.append(_check_consistency(candidate, binding))
        if checks[-1].status is ValidationCheckStatus.FAIL:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=None,
                forced_stale=False,
                forced_quarantine=False,
            )

        # 5. Non-vacuity
        checks.append(_check_non_vacuity(candidate))
        if checks[-1].status is ValidationCheckStatus.FAIL:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=None,
                forced_stale=False,
                forced_quarantine=False,
            )

        # 6. Non-circularity
        checks.append(_check_non_circularity(candidate, hole, binding))
        if checks[-1].status is ValidationCheckStatus.FAIL:
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=None,
                replay_outcomes=(),
                disagreement=None,
                forced_stale=False,
                forced_quarantine=False,
            )

        # 7. Replay
        replay_check, replay_outcomes = _run_replay(
            self.backends,
            candidate,
            hole=hole,
            binding=binding,
            bounds=active_bounds,
        )
        checks.append(replay_check)

        # Provider / backend disagreement → quarantine
        disagreement = _detect_provider_disagreement(
            candidate,
            request.proposed_provider_verdicts,
            replay_outcomes,
        )
        if disagreement is not None or (
            replay_check.status is ValidationCheckStatus.QUARANTINED
        ):
            if disagreement is None:
                disagreement = DisagreementRecord(
                    disagreement_id=_stable_id(
                        "disagree", candidate.candidate_id, "replay"
                    ),
                    reason=QuarantineReason.REPLAY_DISAGREEMENT,
                    candidate_id=candidate.candidate_id,
                    detail=replay_check.detail,
                )
            checks.append(
                ValidationCheck(
                    stage="authority",
                    status=ValidationCheckStatus.QUARANTINED,
                    detail="authority withheld due to disagreement",
                )
            )
            checks.append(
                ValidationCheck(
                    stage="discharge_gate",
                    status=ValidationCheckStatus.FAIL,
                    detail="quarantined candidates cannot discharge graph nodes",
                )
            )
            return self._finalize(
                candidate=candidate,
                hole=hole,
                binding=binding,
                recipe=recipe,
                checks=checks,
                minimality=MinimalityReport(
                    kind=MinimalityKind.UNKNOWN,
                    checked=False,
                    guarantee_limited=True,
                    detail="minimality skipped due to quarantine",
                ),
                replay_outcomes=replay_outcomes,
                disagreement=disagreement,
                forced_stale=False,
                forced_quarantine=True,
            )

        # 8. Minimality (only when replay is usable)
        minimality_check, minimality = _check_minimality(
            self.backends,
            candidate,
            hole=hole,
            binding=binding,
            bounds=active_bounds,
            full_outcomes=replay_outcomes,
        )
        checks.append(minimality_check)

        # 9–10. Authority + discharge decided in finalize via _decide_verdict
        return self._finalize(
            candidate=candidate,
            hole=hole,
            binding=binding,
            recipe=recipe,
            checks=checks,
            minimality=minimality,
            replay_outcomes=replay_outcomes,
            disagreement=None,
            forced_stale=False,
            forced_quarantine=False,
        )

    def validate_set(
        self,
        requests: Sequence[ValidationRequest | Mapping[str, Any]],
        *,
        bounds: ResourceBounds | Mapping[str, Any] | None = None,
    ) -> CandidateSetValidationResult:
        """Validate a candidate set; quarantine multi-candidate disagreement.

        When two candidates target the same hole with conflicting independent
        verdicts (accepted vs rejected), both are quarantined for that hole.
        """

        if requests is None:
            raise CandidateValidationError("requests is required")
        if not isinstance(requests, Sequence) or isinstance(
            requests, (str, bytes, bytearray, memoryview)
        ):
            raise CandidateValidationError(
                "requests must be a sequence of ValidationRequest"
            )

        results: list[CandidateValidationResult] = []
        for index, raw in enumerate(requests):
            if isinstance(raw, Mapping):
                req = ValidationRequest.from_dict(raw)
            elif isinstance(raw, ValidationRequest):
                req = raw
            else:
                raise CandidateValidationError(
                    f"requests[{index}] must be a ValidationRequest"
                )
            results.append(self.validate(req, bounds=bounds))

        # Cross-candidate disagreement on same hole: accept vs reject
        by_hole: dict[str, list[CandidateValidationResult]] = {}
        for result in results:
            by_hole.setdefault(result.validation.hole_id, []).append(result)

        disagreements: list[DisagreementRecord] = []
        quarantined_ids: set[str] = set()
        adjusted: list[CandidateValidationResult] = []

        for hole_id, group in sorted(by_hole.items()):
            verdicts = {item.validation.verdict for item in group}
            conflict = (
                ValidationVerdict.ACCEPTED in verdicts
                or ValidationVerdict.BOUNDED in verdicts
            ) and ValidationVerdict.REJECTED in verdicts
            if conflict and len(group) > 1:
                for item in group:
                    if item.validation.verdict in {
                        ValidationVerdict.ACCEPTED,
                        ValidationVerdict.BOUNDED,
                        ValidationVerdict.REJECTED,
                    }:
                        quarantined_ids.add(item.validation.candidate_id)
                        record = DisagreementRecord(
                            disagreement_id=_stable_id(
                                "disagree",
                                hole_id,
                                item.validation.candidate_id,
                                "set",
                            ),
                            reason=QuarantineReason.AUTHORITY_DISAGREEMENT,
                            candidate_id=item.validation.candidate_id,
                            provider_ids=tuple(
                                sorted(
                                    {
                                        r.validation.provider_id
                                        for r in group
                                        if r.validation.provider_id
                                    }
                                )
                            ),
                            outcomes=tuple(
                                f"{r.validation.candidate_id}:"
                                f"{r.validation.verdict.value}"
                                for r in group
                            ),
                            detail=(
                                f"candidate set disagrees on hole {hole_id}; "
                                "quarantined"
                            ),
                        )
                        disagreements.append(record)
                        # Rewrite result as quarantined / inconclusive
                        adjusted.append(
                            self._requarantine_result(item, record)
                        )
                    else:
                        adjusted.append(item)
            else:
                adjusted.extend(group)

        # Preserve original order
        by_id = {r.validation.candidate_id: r for r in adjusted}
        ordered = [
            by_id.get(r.validation.candidate_id, r) for r in results
        ]

        accepted = tuple(
            r.validation.candidate_id
            for r in ordered
            if r.validation.verdict
            in {ValidationVerdict.ACCEPTED, ValidationVerdict.BOUNDED}
            and not r.quarantined
        )
        rejected = tuple(
            r.validation.candidate_id
            for r in ordered
            if r.validation.verdict is ValidationVerdict.REJECTED
            and not r.quarantined
        )
        quarantined = tuple(
            r.validation.candidate_id for r in ordered if r.quarantined
        )
        dischargeable = tuple(
            r.validation.candidate_id for r in ordered if r.may_discharge
        )

        set_id = (
            "setval:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "candidate_ids": [
                            r.validation.candidate_id for r in ordered
                        ],
                        "algorithm": self.ALGORITHM_VERSION,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        return CandidateSetValidationResult(
            set_result_id=set_id,
            results=tuple(ordered),
            accepted_candidate_ids=accepted,
            rejected_candidate_ids=rejected,
            quarantined_candidate_ids=quarantined,
            dischargeable_candidate_ids=dischargeable,
            disagreements=tuple(disagreements),
            algorithm_version=self.ALGORITHM_VERSION,
            metadata={
                "request_count": len(ordered),
                "validator_id": self.validator_id,
            },
            proof_claimed=False,
            completion_claimed=False,
        )

    def _requarantine_result(
        self,
        result: CandidateValidationResult,
        disagreement: DisagreementRecord,
    ) -> CandidateValidationResult:
        """Rewrite an otherwise-final result as quarantined (set-level)."""

        validation = result.validation
        try:
            new_validation = CandidateValidation(
                validation_id=validation.validation_id,
                candidate_id=validation.candidate_id,
                hole_id=validation.hole_id,
                verdict=ValidationVerdict.INCONCLUSIVE,
                tree_id=validation.tree_id,
                provider_id=validation.provider_id,
                provider_version=validation.provider_version,
                authority=AuthorityCeiling.CANDIDATE,
                recipe=validation.recipe,
                assumption_ids=validation.assumption_ids,
                evidence_ids=validation.evidence_ids,
                minimality="unknown",
                translation_receipt_id=validation.translation_receipt_id,
                proof_claimed=False,
                completion_claimed=False,
            )
        except TacticianContractError as error:
            raise CandidateValidationError(str(error)) from error

        checks = list(result.checks) + [
            ValidationCheck(
                stage="discharge_gate",
                status=ValidationCheckStatus.QUARANTINED,
                detail=disagreement.detail,
            )
        ]
        return CandidateValidationResult(
            result_id=result.result_id,
            validation=new_validation,
            checks=tuple(checks),
            minimality_report=result.minimality_report,
            replay_outcomes=result.replay_outcomes,
            discharge_eligibility=DischargeEligibility.QUARANTINED,
            validated=True,
            stale=result.stale,
            quarantined=True,
            disagreement=disagreement,
            binding_content_id=result.binding_content_id,
            algorithm_version=self.ALGORITHM_VERSION,
            metadata={
                **dict(result.metadata),
                "set_quarantined": True,
            },
            proof_claimed=False,
            completion_claimed=False,
        )

    def _finalize(
        self,
        *,
        candidate: CandidateProofStep,
        hole: ProofHole,
        binding: ValidationBinding,
        recipe: ValidationRecipe | None,
        checks: Sequence[ValidationCheck],
        minimality: MinimalityReport | None,
        replay_outcomes: Sequence[ReplayOutcome],
        disagreement: DisagreementRecord | None,
        forced_stale: bool,
        forced_quarantine: bool,
    ) -> CandidateValidationResult:
        verdict, authority, eligibility, minimality_label, validated = (
            _decide_verdict(
                checks,
                minimality=minimality,
                replay_outcomes=replay_outcomes,
                quarantined=forced_quarantine,
                stale=forced_stale,
            )
        )

        # Authority stage check
        authority_check = ValidationCheck(
            stage="authority",
            status=(
                ValidationCheckStatus.QUARANTINED
                if forced_quarantine
                else (
                    ValidationCheckStatus.PASS
                    if verdict
                    in {
                        ValidationVerdict.ACCEPTED,
                        ValidationVerdict.BOUNDED,
                    }
                    else (
                        ValidationCheckStatus.FAIL
                        if verdict is ValidationVerdict.REJECTED
                        else ValidationCheckStatus.UNKNOWN
                    )
                )
            ),
            detail=(
                f"verdict={verdict.value} authority={authority.value} "
                f"(validator-only status; providers are non-authoritative)"
            ),
        )
        discharge_ok = may_discharge_graph_node(
            verdict=verdict,
            eligibility=eligibility,
            validated=validated,
            stale=forced_stale,
            quarantined=forced_quarantine,
        )
        discharge_check = ValidationCheck(
            stage="discharge_gate",
            status=(
                ValidationCheckStatus.PASS
                if discharge_ok
                else ValidationCheckStatus.FAIL
            ),
            detail=(
                "eligible to discharge bound graph node"
                if discharge_ok
                else (
                    "not eligible to discharge: "
                    f"verdict={verdict.value} eligibility={eligibility.value} "
                    f"stale={forced_stale} quarantined={forced_quarantine}"
                )
            ),
        )
        all_checks = tuple(checks) + (authority_check, discharge_check)

        # Collect evidence ids
        evidence_ids: list[str] = []
        for outcome in replay_outcomes:
            evidence_ids.extend(outcome.evidence_ids)
        for check in all_checks:
            evidence_ids.extend(check.evidence_ids)
        # stable unique
        seen_e: set[str] = set()
        unique_evidence: list[str] = []
        for eid in evidence_ids:
            if eid and eid not in seen_e:
                seen_e.add(eid)
                unique_evidence.append(eid)

        provider_id = self.validator_id
        provider_version = self.ALGORITHM_VERSION
        if replay_outcomes:
            # Prefer holding backend identity for audit, still validator sets status
            for outcome in replay_outcomes:
                if outcome.status is ReplayStatus.HOLDS and outcome.provider_id:
                    provider_id = outcome.provider_id
                    provider_version = (
                        outcome.provider_version or provider_version
                    )
                    break

        validation_id = _stable_id(
            "val",
            candidate.candidate_id,
            hole.hole_id,
            binding.content_id,
            verdict.value,
        )
        try:
            validation = CandidateValidation(
                validation_id=validation_id,
                candidate_id=candidate.candidate_id,
                hole_id=hole.hole_id,
                verdict=verdict,
                tree_id=binding.tree_id,
                provider_id=provider_id,
                provider_version=provider_version,
                authority=authority,
                recipe=recipe,
                assumption_ids=binding.assumption_ids,
                evidence_ids=tuple(unique_evidence),
                minimality=minimality_label,
                proof_claimed=False,
                completion_claimed=False,
            )
        except TacticianContractError as error:
            raise CandidateValidationError(
                f"failed to build CandidateValidation: {error}"
            ) from error

        result_id = _stable_id(
            "vresult", validation_id, self.ALGORITHM_VERSION
        )
        return CandidateValidationResult(
            result_id=result_id,
            validation=validation,
            checks=all_checks,
            minimality_report=minimality,
            replay_outcomes=tuple(replay_outcomes),
            discharge_eligibility=eligibility,
            validated=validated,
            stale=forced_stale,
            quarantined=forced_quarantine,
            disagreement=disagreement,
            binding_content_id=binding.content_id,
            algorithm_version=self.ALGORITHM_VERSION,
            metadata={
                "validator_id": self.validator_id,
                "graph_node_id": binding.graph_node_id,
                "formal_goal_id": binding.formal_goal_id,
                "pipeline_stages": list(PIPELINE_STAGES),
            },
            proof_claimed=False,
            completion_claimed=False,
        )


def validate_candidate(
    candidate: CandidateProofStep | Mapping[str, Any],
    hole: ProofHole | Mapping[str, Any],
    binding: ValidationBinding | Mapping[str, Any],
    *,
    backends: Sequence[ProofReplayBackend] = (),
    recipe: ValidationRecipe | Mapping[str, Any] | None = None,
    expected_candidate_content_id: str = "",
    expected_hole_content_id: str = "",
    proposed_provider_verdicts: Mapping[str, str] | None = None,
    bounds: ResourceBounds | Mapping[str, Any] | None = None,
) -> CandidateValidationResult:
    """Convenience entry point for ``ProofCandidateValidator@1``."""

    return ProofCandidateValidator(
        backends=tuple(backends),
        bounds=_bounds(bounds, "bounds") if bounds is not None else DEFAULT_BOUNDS,
    ).validate(
        ValidationRequest(
            candidate=candidate,  # type: ignore[arg-type]
            hole=hole,  # type: ignore[arg-type]
            binding=binding,  # type: ignore[arg-type]
            recipe=recipe,  # type: ignore[arg-type]
            expected_candidate_content_id=expected_candidate_content_id,
            expected_hole_content_id=expected_hole_content_id,
            proposed_provider_verdicts=proposed_provider_verdicts or {},
        ),
        bounds=bounds,
    )


def validate_candidate_set(
    requests: Sequence[ValidationRequest | Mapping[str, Any]],
    *,
    backends: Sequence[ProofReplayBackend] = (),
    bounds: ResourceBounds | Mapping[str, Any] | None = None,
) -> CandidateSetValidationResult:
    """Convenience entry for multi-candidate validation with quarantine."""

    return ProofCandidateValidator(
        backends=tuple(backends),
        bounds=_bounds(bounds, "bounds") if bounds is not None else DEFAULT_BOUNDS,
    ).validate_set(requests, bounds=bounds)


def default_pipeline_stages() -> tuple[str, ...]:
    """Return the closed validation pipeline stage vocabulary."""

    return PIPELINE_STAGES


__all__ = [
    "PROOF_CANDIDATE_VALIDATOR_INTERFACE",
    "CANDIDATE_VALIDATION_ENGINE_SCHEMA",
    "VALIDATION_BINDING_SCHEMA",
    "VALIDATION_REQUEST_SCHEMA",
    "VALIDATION_CHECK_SCHEMA",
    "MINIMALITY_REPORT_SCHEMA",
    "REPLAY_OUTCOME_SCHEMA",
    "DISAGREEMENT_RECORD_SCHEMA",
    "CANDIDATE_VALIDATION_RESULT_SCHEMA",
    "CANDIDATE_SET_VALIDATION_RESULT_SCHEMA",
    "CANDIDATE_VALIDATION_SCHEMA",
    "VALIDATOR_ALGORITHM_VERSION",
    "DEFAULT_BOUNDS",
    "PIPELINE_STAGES",
    "CandidateValidationError",
    "ValidationCheckStatus",
    "ReplayBackendKind",
    "ReplayStatus",
    "MinimalityKind",
    "DischargeEligibility",
    "QuarantineReason",
    "ValidationBinding",
    "ReplayOutcome",
    "ProofReplayBackend",
    "StaticReplayBackend",
    "UnavailableReplayBackend",
    "ValidationCheck",
    "MinimalityReport",
    "DisagreementRecord",
    "ValidationRequest",
    "CandidateValidationResult",
    "CandidateSetValidationResult",
    "ProofCandidateValidator",
    "validate_candidate",
    "validate_candidate_set",
    "default_pipeline_stages",
    "is_vacuous_statement",
    "is_contradiction_statement",
    "cap_validation_authority",
    "may_discharge_graph_node",
]
