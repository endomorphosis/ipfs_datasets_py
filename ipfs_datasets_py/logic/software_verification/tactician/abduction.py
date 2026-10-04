"""Bounded missing-proof abduction (``MissingProofAbduction@1``).

FVT-G032 / FVT-023: find *weakest admissible* missing premises under a declared
finite theory and resource budget.  Abduction classifies candidates into:

* facts-to-prove;
* reviewable environment assumptions;
* invariants / contracts / lemmas to synthesize;
* unsupported semantics;
* unavailable authority; and
* required implementation changes.

Program invariants:

* candidates must be **relevant**, **consistent**, **source/scoped**,
  **non-circular**, **non-vacuous**, and **weak** under the declared theory
  and budget;
* arbitrary goal-entailing assumptions and contradictions are **rejected**;
* impossible targets return an unsat **core/witness** or honest **unknown**;
* generated premises are **never** inserted into the trusted assumption set
  — admission requires separate validation and policy (conflict policy);
* candidates never claim proof or completion authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------

MISSING_PROOF_ABDUCTION_INTERFACE: Final = "MissingProofAbduction@1"
ABDUCTION_REQUEST_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/abduction-request@1"
)
FINITE_THEORY_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/finite-theory@1"
)
ABDUCTION_CANDIDATE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/abduction-candidate@1"
)
ABDUCTION_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/abduction-result@1"
)
UNSAT_CORE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/abduction-unsat-core@1"
)
ABDUCTION_ALGORITHM_VERSION: Final = "missing-proof-abduction/1.0.0"

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

# Authority a generated abductive premise may advertise (never trusted).
_CANDIDATE_AUTHORITY_CAP: Final = AuthorityCeiling.CANDIDATE

_TOKEN_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.:\-]*")

# Vacuous / goal-entailing literals rejected under non-vacuity.
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


class AbductionError(ValueError):
    """Raised when abduction inputs are malformed or unsafe."""


class PremiseClass(StrEnum):
    """Classification of an abductive missing-premise candidate."""

    FACT_TO_PROVE = "fact_to_prove"
    ENVIRONMENT_ASSUMPTION = "environment_assumption"
    SYNTHESIZE_INVARIANT = "synthesize_invariant"
    SYNTHESIZE_CONTRACT = "synthesize_contract"
    SYNTHESIZE_LEMMA = "synthesize_lemma"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    UNAVAILABLE_AUTHORITY = "unavailable_authority"
    IMPLEMENTATION_CHANGE = "implementation_change"


class AbductionStatus(StrEnum):
    """Outcome of a bounded abductive search."""

    CANDIDATES = "candidates"
    PARTIAL = "partial"
    BOUNDED = "bounded"
    IMPOSSIBLE = "impossible"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    EMPTY = "empty"


class RejectionReason(StrEnum):
    """Why a candidate premise was rejected by admissibility filters."""

    IRRELEVANT = "irrelevant"
    INCONSISTENT = "inconsistent"
    UNSCOPED = "unscoped"
    CIRCULAR = "circular"
    VACUOUS = "vacuous"
    GOAL_ENTAILING = "goal_entailing"
    CONTRADICTION = "contradiction"
    TOO_STRONG = "too_strong"
    BUDGET = "budget"
    TRUSTED_INSERTION = "trusted_insertion"
    MALFORMED = "malformed"
    DUPLICATE = "duplicate"


class AdmissibilityFlag(StrEnum):
    """Boolean admissibility properties a candidate must satisfy."""

    RELEVANT = "relevant"
    CONSISTENT = "consistent"
    SOURCE_SCOPED = "source_scoped"
    NON_CIRCULAR = "non_circular"
    NON_VACUOUS = "non_vacuous"
    WEAK = "weak"


# Map hole kinds → default premise classification.
_HOLE_TO_PREMISE_CLASS: Final[Mapping[HoleKind, PremiseClass]] = {
    HoleKind.LOOP_INVARIANT: PremiseClass.SYNTHESIZE_INVARIANT,
    HoleKind.LOOP_VARIANT: PremiseClass.SYNTHESIZE_INVARIANT,
    HoleKind.STATE_INVARIANT: PremiseClass.SYNTHESIZE_INVARIANT,
    HoleKind.CALLEE_PRECONDITION: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.CALLEE_POSTCONDITION: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.EXCEPTIONAL_CONTRACT: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.FUNCTION_SUMMARY: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.FRAME: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.ALIAS: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.OWNERSHIP: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.SEPARATION: PremiseClass.SYNTHESIZE_CONTRACT,
    HoleKind.BRIDGE_LEMMA: PremiseClass.SYNTHESIZE_LEMMA,
    HoleKind.TRANSLATION_PRESERVATION: PremiseClass.SYNTHESIZE_LEMMA,
    HoleKind.REFINEMENT_MAPPING: PremiseClass.SYNTHESIZE_LEMMA,
    HoleKind.TEMPORAL_FAIRNESS: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.TEMPORAL_PROGRESS: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.RELY_GUARANTEE: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.LINEARIZATION: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.PROTOCOL_TRUST: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.PROTOCOL_FRESHNESS: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.PROTOCOL_SECRECY: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.PROTOCOL_AUTHENTICATION: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.INFORMATION_FLOW: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.OBSERVATION_POLICY: PremiseClass.ENVIRONMENT_ASSUMPTION,
    HoleKind.MISSING_SOURCE_FACT: PremiseClass.FACT_TO_PROVE,
    HoleKind.MISSING_EVIDENCE: PremiseClass.FACT_TO_PROVE,
    HoleKind.UNSUPPORTED_SEMANTICS: PremiseClass.UNSUPPORTED_SEMANTICS,
    HoleKind.UNAVAILABLE_TOOL: PremiseClass.UNAVAILABLE_AUTHORITY,
    HoleKind.UNAVAILABLE_RECONSTRUCTION: PremiseClass.UNAVAILABLE_AUTHORITY,
    HoleKind.REQUIRED_IMPLEMENTATION_CHANGE: PremiseClass.IMPLEMENTATION_CHANGE,
    HoleKind.OTHER: PremiseClass.FACT_TO_PROVE,
}

# Premise classes that are non-proof diagnostics (not admissible premises).
_NON_PROOF_PREMISE_CLASSES: Final[frozenset[PremiseClass]] = frozenset(
    {
        PremiseClass.UNSUPPORTED_SEMANTICS,
        PremiseClass.UNAVAILABLE_AUTHORITY,
        PremiseClass.IMPLEMENTATION_CHANGE,
    }
)

# Weakness rank base (higher = weaker / preferred under minimality).
_PREMISE_WEAKNESS_BASE: Final[Mapping[PremiseClass, int]] = {
    PremiseClass.FACT_TO_PROVE: 700_000,
    PremiseClass.SYNTHESIZE_LEMMA: 650_000,
    PremiseClass.SYNTHESIZE_INVARIANT: 600_000,
    PremiseClass.SYNTHESIZE_CONTRACT: 580_000,
    PremiseClass.ENVIRONMENT_ASSUMPTION: 400_000,  # costlier assumptions
    PremiseClass.UNSUPPORTED_SEMANTICS: 100_000,
    PremiseClass.UNAVAILABLE_AUTHORITY: 90_000,
    PremiseClass.IMPLEMENTATION_CHANGE: 50_000,
}


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
        raise AbductionError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise AbductionError(f"{label} must not contain NUL")
    if not optional and not text:
        raise AbductionError(f"{label} is required")
    if len(text) > maximum:
        raise AbductionError(f"{label} exceeds maximum length of {maximum}")
    return text


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip())
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise AbductionError(
                f"{label} must be one of: {allowed}"
            ) from error
    raise AbductionError(f"{label} must be a {enum_type.__name__}")


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
        raise AbductionError(f"{label} must be a sequence of strings")
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
        raise AbductionError(f"{label} must not be empty")
    return tuple(result)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AbductionError(f"{label} must be a non-negative integer")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AbductionError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AbductionError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise AbductionError(f"{label} keys must be strings")
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
            raise AbductionError(f"{label}: {error}") from error
    raise AbductionError(f"{label} must be a ResourceBounds")


def _proof_hole(value: object, label: str = "hole") -> ProofHole:
    if isinstance(value, ProofHole):
        return value
    if isinstance(value, Mapping):
        try:
            return ProofHole.from_dict(value)
        except TacticianContractError as error:
            raise AbductionError(f"{label}: {error}") from error
    raise AbductionError(f"{label} must be a ProofHole")


def _source_binding(value: object, label: str = "source") -> SourceSpanBinding:
    if isinstance(value, SourceSpanBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpanBinding.from_dict(value)
        except TacticianContractError as error:
            raise AbductionError(f"{label}: {error}") from error
    raise AbductionError(f"{label} must be a SourceSpanBinding")


def _assumption(value: object, label: str = "assumption") -> AssumptionBinding:
    if isinstance(value, AssumptionBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return AssumptionBinding.from_dict(value)
        except TacticianContractError as error:
            raise AbductionError(f"{label}: {error}") from error
    raise AbductionError(f"{label} must be an AssumptionBinding")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _normalize_statement(statement: str) -> str:
    """Normalize a logical statement for comparison (whitespace/case)."""

    text = " ".join(statement.strip().split())
    return text


def _statement_tokens(statement: str) -> frozenset[str]:
    """Extract identifier-like tokens from a statement for relevance."""

    return frozenset(
        token.lower()
        for token in _TOKEN_RE.findall(statement)
        if len(token) > 1
    )


def _is_negation_of(a: str, b: str) -> bool:
    """Heuristic check whether *a* is the negation of *b* (or vice versa)."""

    na = _normalize_statement(a).lower()
    nb = _normalize_statement(b).lower()
    if not na or not nb:
        return False
    if na == nb:
        return False
    prefixes = ("not ", "¬", "~", "!")
    for prefix in prefixes:
        if na == f"{prefix}{nb}" or nb == f"{prefix}{na}":
            return True
        # also "not(x)" style
        stripped_a = na.removeprefix(prefix).strip("() ")
        stripped_b = nb.removeprefix(prefix).strip("() ")
        if stripped_a == nb or stripped_b == na:
            return True
    return False


def classify_hole_kind(kind: HoleKind | str) -> PremiseClass:
    """Map a :class:`HoleKind` to the default abductive :class:`PremiseClass`."""

    resolved = _enum(kind, HoleKind, "kind")
    return _HOLE_TO_PREMISE_CLASS.get(resolved, PremiseClass.FACT_TO_PROVE)


def is_non_proof_premise_class(premise_class: PremiseClass | str) -> bool:
    """True when the class is a non-proof diagnostic (not an admissible premise)."""

    resolved = _enum(premise_class, PremiseClass, "premise_class")
    return resolved in _NON_PROOF_PREMISE_CLASSES


def cap_candidate_authority(
    authority: AuthorityCeiling | str,
) -> AuthorityCeiling:
    """Hard-cap authority for generated abductive premises at candidate."""

    resolved = _enum(authority, AuthorityCeiling, "authority")
    if resolved in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }:
        return resolved
    return _CANDIDATE_AUTHORITY_CAP


def is_vacuous_statement(statement: str) -> bool:
    """True when *statement* is a vacuous / tautological premise."""

    normalized = _normalize_statement(statement)
    if normalized in _VACUOUS_STATEMENTS:
        return True
    lower = normalized.lower()
    if lower in {s.lower() for s in _VACUOUS_STATEMENTS}:
        return True
    # Bare "true" after stripping punctuation
    stripped = lower.strip("()[]{} ")
    return stripped in {s.lower() for s in _VACUOUS_STATEMENTS if s}


def is_contradiction_statement(statement: str) -> bool:
    """True when *statement* is an explicit contradiction / falsehood."""

    normalized = _normalize_statement(statement)
    if normalized in _CONTRADICTION_MARKERS:
        return True
    lower = normalized.lower()
    stripped = lower.strip("()[]{} ")
    return stripped in {s.lower() for s in _CONTRADICTION_MARKERS if s}


def is_goal_entailing_assumption(
    statement: str,
    goal_statement: str,
    *,
    goal_ids: Sequence[str] = (),
) -> bool:
    """True when *statement* is an arbitrary assumption of the goal itself.

    Rejects premises that simply restate the target goal (or its identifier),
    which would vacuously "prove" the goal by assumption.
    """

    if not statement or not goal_statement:
        return False
    ns = _normalize_statement(statement).lower()
    ng = _normalize_statement(goal_statement).lower()
    if ns == ng:
        return True
    # "assume G" / "goal" / formal goal id as sole content
    if ns in {"goal", "the goal", "target", "end_goal", "formal_goal"}:
        return True
    for gid in goal_ids:
        g = gid.strip().lower()
        if g and (ns == g or ns == f"assume {g}" or ns == f"goal:{g}"):
            return True
    if ns.startswith("assume ") and ns[len("assume ") :].strip() == ng:
        return True
    if ns.startswith("assume(") and ng in ns:
        # assume(goal_statement)
        inner = ns[len("assume") :].strip("() ")
        if inner == ng:
            return True
    return False


# ---------------------------------------------------------------------------
# Finite theory and unsat core
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FiniteTheory:
    """Declared finite theory under which abduction is performed.

    Provides the closed set of known facts, axioms, trusted assumptions,
    symbols, and the target goal.  All reasoning is relative to this finite
    fragment and the resource budget — not an open-world theory.
    """

    SCHEMA: ClassVar[str] = FINITE_THEORY_SCHEMA

    theory_id: str
    goal_statement: str
    known_facts: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    trusted_assumptions: tuple[AssumptionBinding, ...] = ()
    symbols: tuple[str, ...] = ()
    goal_id: str = ""
    logic_family: str = "finite_fragment"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "theory_id", _text(self.theory_id, "theory_id", maximum=256)
        )
        object.__setattr__(
            self,
            "goal_statement",
            _text(self.goal_statement, "goal_statement", maximum=8192),
        )
        object.__setattr__(
            self,
            "known_facts",
            _string_tuple(self.known_facts, "known_facts", preserve_order=True),
        )
        object.__setattr__(
            self,
            "axioms",
            _string_tuple(self.axioms, "axioms", preserve_order=True),
        )
        assumptions: list[AssumptionBinding] = []
        for index, raw in enumerate(self.trusted_assumptions or ()):
            assumptions.append(_assumption(raw, f"trusted_assumptions[{index}]"))
            if assumptions[-1].assumption_class is AssumptionClass.HYPOTHETICAL:
                raise AbductionError(
                    "trusted_assumptions cannot include hypothetical class; "
                    "hypotheticals must remain reviewable candidates"
                )
        object.__setattr__(self, "trusted_assumptions", tuple(assumptions))
        object.__setattr__(
            self,
            "symbols",
            _string_tuple(self.symbols, "symbols", preserve_order=True),
        )
        object.__setattr__(
            self,
            "goal_id",
            _text(self.goal_id, "goal_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "logic_family",
            _text(
                self.logic_family or "finite_fragment",
                "logic_family",
                maximum=128,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def all_known_statements(self) -> tuple[str, ...]:
        """Flatten trusted/axiom/fact statements for consistency checks."""

        parts: list[str] = []
        parts.extend(self.known_facts)
        parts.extend(self.axioms)
        for assumption in self.trusted_assumptions:
            if assumption.statement:
                parts.append(assumption.statement)
        return tuple(parts)

    def symbol_set(self) -> frozenset[str]:
        """Closed symbol vocabulary of this theory (plus goal tokens)."""

        symbols = {s.lower() for s in self.symbols}
        for statement in self.all_known_statements():
            symbols |= {t for t in _statement_tokens(statement)}
        symbols |= {t for t in _statement_tokens(self.goal_statement)}
        return frozenset(symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "theory_id": self.theory_id,
            "goal_statement": self.goal_statement,
            "known_facts": list(self.known_facts),
            "axioms": list(self.axioms),
            "trusted_assumptions": [
                a.to_dict() for a in self.trusted_assumptions
            ],
            "symbols": list(self.symbols),
            "goal_id": self.goal_id,
            "logic_family": self.logic_family,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FiniteTheory":
        if not isinstance(payload, Mapping):
            raise AbductionError("theory payload must be an object")
        return cls(
            theory_id=payload.get("theory_id", ""),
            goal_statement=payload.get("goal_statement", ""),
            known_facts=tuple(payload.get("known_facts") or ()),
            axioms=tuple(payload.get("axioms") or ()),
            trusted_assumptions=tuple(
                payload.get("trusted_assumptions") or ()
            ),
            symbols=tuple(payload.get("symbols") or ()),
            goal_id=payload.get("goal_id", ""),
            logic_family=payload.get("logic_family", "finite_fragment"),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class UnsatCoreWitness:
    """Core/witness explaining why a target is impossible under the theory.

    Returned when abduction cannot find admissible premises because the
    goal is inconsistent with the declared finite theory.
    """

    SCHEMA: ClassVar[str] = UNSAT_CORE_SCHEMA

    core_id: str
    conflicting_statements: tuple[str, ...]
    explanation: str = ""
    goal_statement: str = ""
    witness_kind: str = "unsat_core"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "core_id", _text(self.core_id, "core_id", maximum=256)
        )
        object.__setattr__(
            self,
            "conflicting_statements",
            _string_tuple(
                self.conflicting_statements,
                "conflicting_statements",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "explanation",
            _text(
                self.explanation, "explanation", optional=True, maximum=4096
            ),
        )
        object.__setattr__(
            self,
            "goal_statement",
            _text(
                self.goal_statement,
                "goal_statement",
                optional=True,
                maximum=8192,
            ),
        )
        object.__setattr__(
            self,
            "witness_kind",
            _text(
                self.witness_kind or "unsat_core",
                "witness_kind",
                maximum=64,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "core_id": self.core_id,
            "conflicting_statements": list(self.conflicting_statements),
            "explanation": self.explanation,
            "goal_statement": self.goal_statement,
            "witness_kind": self.witness_kind,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UnsatCoreWitness":
        if not isinstance(payload, Mapping):
            raise AbductionError("unsat core payload must be an object")
        return cls(
            core_id=payload.get("core_id", ""),
            conflicting_statements=tuple(
                payload.get("conflicting_statements") or ()
            ),
            explanation=payload.get("explanation", ""),
            goal_statement=payload.get("goal_statement", ""),
            witness_kind=payload.get("witness_kind", "unsat_core"),
            metadata=payload.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Candidates and rejection records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RejectedPremise:
    """A rejected candidate premise with the reason it failed admissibility."""

    statement: str
    reason: RejectionReason
    hole_id: str = ""
    premise_class: PremiseClass | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "statement", optional=True, maximum=8192),
        )
        object.__setattr__(
            self, "reason", _enum(self.reason, RejectionReason, "reason")
        )
        object.__setattr__(
            self,
            "hole_id",
            _text(self.hole_id, "hole_id", optional=True, maximum=256),
        )
        if self.premise_class is not None:
            object.__setattr__(
                self,
                "premise_class",
                _enum(self.premise_class, PremiseClass, "premise_class"),
            )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "detail", optional=True, maximum=2048),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "reason": self.reason.value,
            "hole_id": self.hole_id,
            "premise_class": (
                self.premise_class.value if self.premise_class else None
            ),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RejectedPremise":
        return cls(
            statement=payload.get("statement", ""),
            reason=payload.get("reason", RejectionReason.MALFORMED),
            hole_id=payload.get("hole_id", ""),
            premise_class=payload.get("premise_class"),
            detail=payload.get("detail", ""),
        )


@dataclass(frozen=True, slots=True)
class AbductionCandidate:
    """One weak admissible missing-premise candidate.

    Never claims proof or completion.  Never belongs to the trusted assumption
    set until separate validation and policy admission (conflict policy).
    """

    SCHEMA: ClassVar[str] = ABDUCTION_CANDIDATE_SCHEMA

    candidate_id: str
    premise_class: PremiseClass
    statement: str
    hole_id: str
    source: SourceSpanBinding
    formal_goal_id: str = ""
    theory_id: str = ""
    authority: AuthorityCeiling = AuthorityCeiling.CANDIDATE
    assumption_class: AssumptionClass = AssumptionClass.HYPOTHETICAL
    reviewable: bool = True
    admitted_to_trusted: bool = False
    weakness_score_millionths: int = 0
    relevant: bool = True
    consistent: bool = True
    source_scoped: bool = True
    non_circular: bool = True
    non_vacuous: bool = True
    weak: bool = True
    dependency_ids: tuple[str, ...] = ()
    symbol_overlap: tuple[str, ...] = ()
    rationale: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", maximum=256),
        )
        object.__setattr__(
            self,
            "premise_class",
            _enum(self.premise_class, PremiseClass, "premise_class"),
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", maximum=8192)
        )
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "hole_id", maximum=256)
        )
        object.__setattr__(self, "source", _source_binding(self.source, "source"))
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(
                self.formal_goal_id,
                "formal_goal_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "theory_id",
            _text(self.theory_id, "theory_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "authority",
            cap_candidate_authority(
                _enum(self.authority, AuthorityCeiling, "authority")
            ),
        )
        object.__setattr__(
            self,
            "assumption_class",
            _enum(self.assumption_class, AssumptionClass, "assumption_class"),
        )
        # Generated premises must remain hypothetical / must-prove, never trusted.
        if self.assumption_class is AssumptionClass.TRUSTED:
            raise AbductionError(
                "AbductionCandidate cannot use TRUSTED assumption_class; "
                "generated premises require separate validation and policy "
                "admission before trusted insertion"
            )
        object.__setattr__(
            self, "reviewable", _bool(self.reviewable, "reviewable")
        )
        admitted = _bool(self.admitted_to_trusted, "admitted_to_trusted")
        if admitted:
            raise AbductionError(
                "AbductionCandidate cannot set admitted_to_trusted=True; "
                "never insert a generated premise into the trusted assumption "
                "set without separate validation and policy admission"
            )
        object.__setattr__(self, "admitted_to_trusted", False)
        object.__setattr__(
            self,
            "weakness_score_millionths",
            _nonnegative_int(
                self.weakness_score_millionths, "weakness_score_millionths"
            ),
        )
        for flag_name in (
            "relevant",
            "consistent",
            "source_scoped",
            "non_circular",
            "non_vacuous",
            "weak",
            "reviewable",
        ):
            # already handled reviewable above for reviewable
            if flag_name == "reviewable":
                continue
            object.__setattr__(
                self, flag_name, _bool(getattr(self, flag_name), flag_name)
            )
        object.__setattr__(
            self,
            "dependency_ids",
            _string_tuple(self.dependency_ids, "dependency_ids"),
        )
        object.__setattr__(
            self,
            "symbol_overlap",
            _string_tuple(self.symbol_overlap, "symbol_overlap"),
        )
        object.__setattr__(
            self,
            "rationale",
            _text(self.rationale, "rationale", optional=True, maximum=4096),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        proof = _bool(self.proof_claimed, "proof_claimed")
        completion = _bool(self.completion_claimed, "completion_claimed")
        if proof or completion:
            raise AbductionError(
                "AbductionCandidate cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)
        # Environment assumptions must remain reviewable.
        if (
            self.premise_class is PremiseClass.ENVIRONMENT_ASSUMPTION
            and not self.reviewable
        ):
            raise AbductionError(
                "environment_assumption candidates must remain reviewable"
            )

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def admissible(self) -> bool:
        """True when all admissibility flags hold and premise is proof-class."""

        if is_non_proof_premise_class(self.premise_class):
            return False
        return (
            self.relevant
            and self.consistent
            and self.source_scoped
            and self.non_circular
            and self.non_vacuous
            and self.weak
            and not self.admitted_to_trusted
            and not self.proof_claimed
            and not self.completion_claimed
        )

    def admissibility_flags(self) -> dict[str, bool]:
        return {
            AdmissibilityFlag.RELEVANT.value: self.relevant,
            AdmissibilityFlag.CONSISTENT.value: self.consistent,
            AdmissibilityFlag.SOURCE_SCOPED.value: self.source_scoped,
            AdmissibilityFlag.NON_CIRCULAR.value: self.non_circular,
            AdmissibilityFlag.NON_VACUOUS.value: self.non_vacuous,
            AdmissibilityFlag.WEAK.value: self.weak,
        }

    def to_assumption_binding(self) -> AssumptionBinding:
        """Project to a *hypothetical* reviewable assumption (never trusted)."""

        return AssumptionBinding(
            assumption_id=f"abduction:{self.candidate_id}",
            assumption_class=AssumptionClass.HYPOTHETICAL,
            kind=self.premise_class.value,
            statement=self.statement,
            source=self.source,
            authority=self.authority,
            reviewable=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "candidate_id": self.candidate_id,
            "premise_class": self.premise_class.value,
            "statement": self.statement,
            "hole_id": self.hole_id,
            "source": self.source.to_dict(),
            "formal_goal_id": self.formal_goal_id,
            "theory_id": self.theory_id,
            "authority": self.authority.value,
            "assumption_class": self.assumption_class.value,
            "reviewable": self.reviewable,
            "admitted_to_trusted": False,
            "weakness_score_millionths": self.weakness_score_millionths,
            "relevant": self.relevant,
            "consistent": self.consistent,
            "source_scoped": self.source_scoped,
            "non_circular": self.non_circular,
            "non_vacuous": self.non_vacuous,
            "weak": self.weak,
            "admissible": self.admissible,
            "dependency_ids": list(self.dependency_ids),
            "symbol_overlap": list(self.symbol_overlap),
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AbductionCandidate":
        if not isinstance(payload, Mapping):
            raise AbductionError("candidate payload must be an object")
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise AbductionError(
                "AbductionCandidate cannot claim proof or completion"
            )
        if payload.get("admitted_to_trusted") is True:
            raise AbductionError(
                "AbductionCandidate cannot set admitted_to_trusted=True"
            )
        return cls(
            candidate_id=payload.get("candidate_id", ""),
            premise_class=payload.get(
                "premise_class", PremiseClass.FACT_TO_PROVE
            ),
            statement=payload.get("statement", ""),
            hole_id=payload.get("hole_id", ""),
            source=payload.get("source") or {},
            formal_goal_id=payload.get("formal_goal_id", ""),
            theory_id=payload.get("theory_id", ""),
            authority=payload.get("authority", AuthorityCeiling.CANDIDATE),
            assumption_class=payload.get(
                "assumption_class", AssumptionClass.HYPOTHETICAL
            ),
            reviewable=bool(payload.get("reviewable", True)),
            admitted_to_trusted=bool(payload.get("admitted_to_trusted", False)),
            weakness_score_millionths=int(
                payload.get("weakness_score_millionths") or 0
            ),
            relevant=bool(payload.get("relevant", True)),
            consistent=bool(payload.get("consistent", True)),
            source_scoped=bool(payload.get("source_scoped", True)),
            non_circular=bool(payload.get("non_circular", True)),
            non_vacuous=bool(payload.get("non_vacuous", True)),
            weak=bool(payload.get("weak", True)),
            dependency_ids=tuple(payload.get("dependency_ids") or ()),
            symbol_overlap=tuple(payload.get("symbol_overlap") or ()),
            rationale=payload.get("rationale", ""),
            metadata=payload.get("metadata") or {},
            proof_claimed=bool(payload.get("proof_claimed", False)),
            completion_claimed=bool(payload.get("completion_claimed", False)),
        )


# ---------------------------------------------------------------------------
# Request / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AbductionRequest:
    """Inputs to a bounded missing-proof abduction search."""

    SCHEMA: ClassVar[str] = ABDUCTION_REQUEST_SCHEMA

    formal_goal_id: str
    theory: FiniteTheory
    holes: tuple[ProofHole, ...] = ()
    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    tree_id: str = ""
    proposed_premises: tuple[str, ...] = ()
    open_obligation_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        theory = self.theory
        if isinstance(theory, Mapping):
            theory = FiniteTheory.from_dict(theory)
        elif not isinstance(theory, FiniteTheory):
            raise AbductionError("theory must be a FiniteTheory")
        object.__setattr__(self, "theory", theory)
        holes: list[ProofHole] = []
        seen: set[str] = set()
        for index, raw in enumerate(self.holes or ()):
            hole = _proof_hole(raw, f"holes[{index}]")
            if hole.hole_id in seen:
                raise AbductionError(f"duplicate hole id {hole.hole_id!r}")
            seen.add(hole.hole_id)
            holes.append(hole)
        object.__setattr__(self, "holes", tuple(holes))
        object.__setattr__(self, "bounds", _bounds(self.bounds, "bounds"))
        object.__setattr__(
            self,
            "tree_id",
            _text(self.tree_id, "tree_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "proposed_premises",
            _string_tuple(
                self.proposed_premises, "proposed_premises", preserve_order=True
            ),
        )
        object.__setattr__(
            self,
            "open_obligation_ids",
            _string_tuple(self.open_obligation_ids, "open_obligation_ids"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "formal_goal_id": self.formal_goal_id,
            "theory": self.theory.to_dict(),
            "holes": [h.to_dict() for h in self.holes],
            "bounds": self.bounds.to_dict(),
            "tree_id": self.tree_id,
            "proposed_premises": list(self.proposed_premises),
            "open_obligation_ids": list(self.open_obligation_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AbductionRequest":
        if not isinstance(payload, Mapping):
            raise AbductionError("request payload must be an object")
        theory_raw = payload.get("theory")
        bounds_raw = payload.get("bounds")
        return cls(
            formal_goal_id=payload.get("formal_goal_id", ""),
            theory=(
                FiniteTheory.from_dict(theory_raw)
                if isinstance(theory_raw, Mapping)
                else theory_raw
            ),
            holes=tuple(payload.get("holes") or ()),
            bounds=(
                ResourceBounds.from_dict(bounds_raw)
                if isinstance(bounds_raw, Mapping)
                else bounds_raw
            ),
            tree_id=payload.get("tree_id", ""),
            proposed_premises=tuple(payload.get("proposed_premises") or ()),
            open_obligation_ids=tuple(
                payload.get("open_obligation_ids") or ()
            ),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class AbductionResult:
    """Result of bounded missing-proof abduction (``MissingProofAbduction@1``).

    Never claims proof or completion.  Admissible candidates remain proposals
    that require independent validation before any trusted use.
    """

    SCHEMA: ClassVar[str] = ABDUCTION_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = MISSING_PROOF_ABDUCTION_INTERFACE

    result_id: str
    formal_goal_id: str
    status: AbductionStatus
    candidates: tuple[AbductionCandidate, ...] = ()
    rejected: tuple[RejectedPremise, ...] = ()
    unsat_core: UnsatCoreWitness | None = None
    theory_id: str = ""
    steps_used: int = 0
    budget_exhausted: bool = False
    diagnostics: tuple[str, ...] = ()
    classified_by_class: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    algorithm_version: str = ABDUCTION_ALGORITHM_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proof_claimed: bool = False
    completion_claimed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result_id", _text(self.result_id, "result_id", maximum=256)
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(self.formal_goal_id, "formal_goal_id", maximum=256),
        )
        object.__setattr__(
            self, "status", _enum(self.status, AbductionStatus, "status")
        )
        candidates: list[AbductionCandidate] = []
        for index, raw in enumerate(self.candidates or ()):
            if isinstance(raw, AbductionCandidate):
                candidates.append(raw)
            elif isinstance(raw, Mapping):
                candidates.append(AbductionCandidate.from_dict(raw))
            else:
                raise AbductionError(
                    f"candidates[{index}] must be an AbductionCandidate"
                )
        object.__setattr__(self, "candidates", tuple(candidates))
        rejected: list[RejectedPremise] = []
        for index, raw in enumerate(self.rejected or ()):
            if isinstance(raw, RejectedPremise):
                rejected.append(raw)
            elif isinstance(raw, Mapping):
                rejected.append(RejectedPremise.from_dict(raw))
            else:
                raise AbductionError(
                    f"rejected[{index}] must be a RejectedPremise"
                )
        object.__setattr__(self, "rejected", tuple(rejected))
        core = self.unsat_core
        if core is None:
            pass
        elif isinstance(core, Mapping):
            core = UnsatCoreWitness.from_dict(core)
        elif not isinstance(core, UnsatCoreWitness):
            raise AbductionError("unsat_core must be an UnsatCoreWitness")
        object.__setattr__(self, "unsat_core", core)
        object.__setattr__(
            self,
            "theory_id",
            _text(self.theory_id, "theory_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "steps_used", _nonnegative_int(self.steps_used, "steps_used")
        )
        object.__setattr__(
            self,
            "budget_exhausted",
            _bool(self.budget_exhausted, "budget_exhausted"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _string_tuple(self.diagnostics, "diagnostics", preserve_order=True),
        )
        classified = self.classified_by_class or {}
        if not isinstance(classified, Mapping):
            raise AbductionError("classified_by_class must be a mapping")
        normalized_class: dict[str, tuple[str, ...]] = {}
        for key, values in classified.items():
            k = _text(key, "classified_by_class key", maximum=128)
            if isinstance(values, str):
                vals = (values,)
            elif isinstance(values, Sequence):
                vals = tuple(
                    _text(v, f"classified_by_class[{k}]", maximum=256)
                    for v in values
                )
            else:
                raise AbductionError(
                    f"classified_by_class[{k}] must be a sequence of ids"
                )
            normalized_class[k] = vals
        object.__setattr__(self, "classified_by_class", normalized_class)
        object.__setattr__(
            self,
            "algorithm_version",
            _text(
                self.algorithm_version or ABDUCTION_ALGORITHM_VERSION,
                "algorithm_version",
                maximum=128,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        proof = _bool(self.proof_claimed, "proof_claimed")
        completion = _bool(self.completion_claimed, "completion_claimed")
        if proof or completion:
            raise AbductionError(
                "AbductionResult cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def admissible_candidates(self) -> tuple[AbductionCandidate, ...]:
        return tuple(c for c in self.candidates if c.admissible)

    def candidates_of_class(
        self, premise_class: PremiseClass | str
    ) -> tuple[AbductionCandidate, ...]:
        resolved = _enum(premise_class, PremiseClass, "premise_class")
        return tuple(c for c in self.candidates if c.premise_class is resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "result_id": self.result_id,
            "formal_goal_id": self.formal_goal_id,
            "status": self.status.value,
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected": [r.to_dict() for r in self.rejected],
            "unsat_core": (
                None if self.unsat_core is None else self.unsat_core.to_dict()
            ),
            "theory_id": self.theory_id,
            "steps_used": self.steps_used,
            "budget_exhausted": self.budget_exhausted,
            "diagnostics": list(self.diagnostics),
            "classified_by_class": {
                k: list(v) for k, v in sorted(self.classified_by_class.items())
            },
            "algorithm_version": self.algorithm_version,
            "metadata": dict(self.metadata),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AbductionResult":
        if not isinstance(payload, Mapping):
            raise AbductionError("result payload must be an object")
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise AbductionError(
                "AbductionResult cannot claim proof or completion"
            )
        return cls(
            result_id=payload.get("result_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            status=payload.get("status", AbductionStatus.UNKNOWN),
            candidates=tuple(payload.get("candidates") or ()),
            rejected=tuple(payload.get("rejected") or ()),
            unsat_core=payload.get("unsat_core"),
            theory_id=payload.get("theory_id", ""),
            steps_used=int(payload.get("steps_used") or 0),
            budget_exhausted=bool(payload.get("budget_exhausted", False)),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            classified_by_class=payload.get("classified_by_class") or {},
            algorithm_version=payload.get(
                "algorithm_version", ABDUCTION_ALGORITHM_VERSION
            ),
            metadata=payload.get("metadata") or {},
            proof_claimed=bool(payload.get("proof_claimed", False)),
            completion_claimed=bool(payload.get("completion_claimed", False)),
        )


# ---------------------------------------------------------------------------
# Admissibility checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _AdmissibilityReport:
    relevant: bool
    consistent: bool
    source_scoped: bool
    non_circular: bool
    non_vacuous: bool
    weak: bool
    rejection: RejectionReason | None = None
    detail: str = ""
    symbol_overlap: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.relevant
            and self.consistent
            and self.source_scoped
            and self.non_circular
            and self.non_vacuous
            and self.weak
            and self.rejection is None
        )


def check_admissibility(
    statement: str,
    *,
    theory: FiniteTheory,
    hole: ProofHole | None = None,
    premise_class: PremiseClass = PremiseClass.FACT_TO_PROVE,
    stronger_than: Sequence[str] = (),
) -> _AdmissibilityReport:
    """Evaluate admissibility of a candidate premise under *theory*.

    Implements the acceptance filters: relevant, consistent, source/scoped,
    non-circular, non-vacuous, weak; rejects goal-entailing and contradictory
    premises.
    """

    normalized = _normalize_statement(statement)
    if not normalized:
        return _AdmissibilityReport(
            relevant=False,
            consistent=False,
            source_scoped=False,
            non_circular=False,
            non_vacuous=False,
            weak=False,
            rejection=RejectionReason.MALFORMED,
            detail="empty statement",
        )

    # Vacuous / tautology
    if is_vacuous_statement(normalized):
        return _AdmissibilityReport(
            relevant=False,
            consistent=True,
            source_scoped=True,
            non_circular=True,
            non_vacuous=False,
            weak=False,
            rejection=RejectionReason.VACUOUS,
            detail="vacuous/tautological premise rejected",
        )

    # Explicit contradiction as premise
    if is_contradiction_statement(normalized):
        return _AdmissibilityReport(
            relevant=False,
            consistent=False,
            source_scoped=True,
            non_circular=True,
            non_vacuous=True,
            weak=False,
            rejection=RejectionReason.CONTRADICTION,
            detail="contradiction premise rejected",
        )

    # Goal-entailing arbitrary assumption
    goal_ids = [theory.goal_id] if theory.goal_id else []
    if hole and hole.formal_goal_id:
        goal_ids.append(hole.formal_goal_id)
    if is_goal_entailing_assumption(
        normalized, theory.goal_statement, goal_ids=goal_ids
    ):
        return _AdmissibilityReport(
            relevant=False,
            consistent=True,
            source_scoped=True,
            non_circular=False,
            non_vacuous=False,
            weak=False,
            rejection=RejectionReason.GOAL_ENTAILING,
            detail="arbitrary goal-entailing assumption rejected",
        )

    # Consistency with known theory (negation of known facts / axioms)
    known = theory.all_known_statements()
    for known_stmt in known:
        if _is_negation_of(normalized, known_stmt):
            return _AdmissibilityReport(
                relevant=True,
                consistent=False,
                source_scoped=True,
                non_circular=True,
                non_vacuous=True,
                weak=False,
                rejection=RejectionReason.INCONSISTENT,
                detail=f"inconsistent with known statement {known_stmt!r}",
            )
        if _normalize_statement(known_stmt).lower() == normalized.lower() and (
            premise_class is PremiseClass.ENVIRONMENT_ASSUMPTION
        ):
            # Re-stating a known trusted fact as a new env assumption is vacuous.
            return _AdmissibilityReport(
                relevant=True,
                consistent=True,
                source_scoped=True,
                non_circular=True,
                non_vacuous=False,
                weak=False,
                rejection=RejectionReason.VACUOUS,
                detail="premise already present in theory",
            )

    # Circular: depends on itself / on the hole statement alone as proof
    if hole and hole.statement:
        hole_norm = _normalize_statement(hole.statement).lower()
        if hole_norm and normalized.lower() == hole_norm:
            # Synthesizing the hole statement itself as premise is circular
            # when the hole *is* the missing fact; allow for SYNTHESIZE_* classes
            # only when the statement is a proper strengthening candidate.
            if premise_class is PremiseClass.FACT_TO_PROVE:
                # restating the obligation is not an abductive premise
                return _AdmissibilityReport(
                    relevant=True,
                    consistent=True,
                    source_scoped=True,
                    non_circular=False,
                    non_vacuous=True,
                    weak=False,
                    rejection=RejectionReason.CIRCULAR,
                    detail="premise restates the open obligation (circular)",
                )

    # Relevance: share symbols with goal / hole / theory vocabulary
    stmt_tokens = _statement_tokens(normalized)
    theory_symbols = theory.symbol_set()
    hole_tokens: frozenset[str] = frozenset()
    if hole:
        hole_tokens = _statement_tokens(hole.statement) | _statement_tokens(
            hole.reason
        )
        hole_tokens |= frozenset(
            s.lower() for s in hole.source.ast_scope_ids if s
        )
    goal_tokens = _statement_tokens(theory.goal_statement)
    overlap = stmt_tokens & (theory_symbols | hole_tokens | goal_tokens)
    # Non-proof diagnostics are "relevant" by classification even without tokens.
    if is_non_proof_premise_class(premise_class):
        relevant = True
    elif not stmt_tokens:
        relevant = False
    elif not (theory_symbols or hole_tokens or goal_tokens):
        # Open theory with no symbols: accept any non-empty tokenized statement.
        relevant = bool(stmt_tokens)
    else:
        relevant = bool(overlap)
    if not relevant:
        return _AdmissibilityReport(
            relevant=False,
            consistent=True,
            source_scoped=True,
            non_circular=True,
            non_vacuous=True,
            weak=False,
            rejection=RejectionReason.IRRELEVANT,
            detail="no shared symbols with theory/goal/hole",
            symbol_overlap=(),
        )

    # Source scoping: candidate must bind to the hole's source when present.
    source_scoped = True
    if hole is not None:
        if not hole.source.tree_id and not hole.source.source_ref_ids:
            source_scoped = False
            return _AdmissibilityReport(
                relevant=True,
                consistent=True,
                source_scoped=False,
                non_circular=True,
                non_vacuous=True,
                weak=False,
                rejection=RejectionReason.UNSCOPED,
                detail="hole lacks source/scope binding",
                symbol_overlap=tuple(sorted(overlap)),
            )

    # Weakness: reject premises strictly stronger than known weaker alternatives
    # when a stronger_than catalogue is provided (syntactic superstring/superset).
    weak = True
    for weaker in stronger_than:
        w_norm = _normalize_statement(weaker)
        if not w_norm or w_norm.lower() == normalized.lower():
            continue
        w_tokens = _statement_tokens(w_norm)
        # If weaker tokens are a proper subset and statement contains weaker
        # as a conjunctive superstring, mark too strong.
        if (
            w_tokens
            and w_tokens < stmt_tokens
            and w_norm.lower() in normalized.lower()
        ):
            weak = False
            return _AdmissibilityReport(
                relevant=True,
                consistent=True,
                source_scoped=source_scoped,
                non_circular=True,
                non_vacuous=True,
                weak=False,
                rejection=RejectionReason.TOO_STRONG,
                detail=f"stronger than weaker alternative {w_norm!r}",
                symbol_overlap=tuple(sorted(overlap)),
            )

    return _AdmissibilityReport(
        relevant=True,
        consistent=True,
        source_scoped=source_scoped,
        non_circular=True,
        non_vacuous=True,
        weak=weak,
        rejection=None,
        detail="",
        symbol_overlap=tuple(sorted(overlap)),
    )


def detect_impossible_goal(
    theory: FiniteTheory,
) -> UnsatCoreWitness | None:
    """Return an unsat core when the goal contradicts the finite theory.

    Detects direct goal-vs-fact negation and explicit falsehood of the goal.
    """

    goal = theory.goal_statement
    if is_contradiction_statement(goal):
        return UnsatCoreWitness(
            core_id=_stable_id("core", theory.theory_id, "false-goal"),
            conflicting_statements=(goal,),
            explanation="goal statement is an explicit contradiction",
            goal_statement=goal,
            witness_kind="false_goal",
        )
    conflicts: list[str] = []
    for known in theory.all_known_statements():
        if _is_negation_of(goal, known):
            conflicts.append(known)
        # goal is literally "false" relative to a known true fact equal to goal
        # handled above
    if conflicts:
        return UnsatCoreWitness(
            core_id=_stable_id(
                "core", theory.theory_id, *sorted(conflicts)[:4]
            ),
            conflicting_statements=tuple(conflicts),
            explanation=(
                "goal is inconsistent with known facts/axioms/assumptions "
                "in the declared finite theory"
            ),
            goal_statement=goal,
            witness_kind="unsat_core",
        )
    # Known facts include both P and not P → theory itself is inconsistent
    known = list(theory.all_known_statements())
    for i, a in enumerate(known):
        for b in known[i + 1 :]:
            if _is_negation_of(a, b):
                return UnsatCoreWitness(
                    core_id=_stable_id("core", theory.theory_id, a, b),
                    conflicting_statements=(a, b),
                    explanation="finite theory is internally inconsistent",
                    goal_statement=goal,
                    witness_kind="theory_inconsistency",
                )
    return None


# ---------------------------------------------------------------------------
# Premise proposal generation from holes
# ---------------------------------------------------------------------------


def _default_statements_for_hole(hole: ProofHole) -> tuple[str, ...]:
    """Derive bounded abductive statement proposals from a typed hole."""

    premise_class = classify_hole_kind(hole.kind)
    base = hole.statement.strip() if hole.statement else ""
    reason = hole.reason.strip() if hole.reason else ""
    proposals: list[str] = []

    if premise_class is PremiseClass.SYNTHESIZE_INVARIANT:
        if base and not base.lower().startswith("missing"):
            proposals.append(base)
        else:
            proposals.append(
                f"invariant({hole.source.ast_scope_ids[0] if hole.source.ast_scope_ids else hole.hole_id})"
            )
        # Weaker template: local bound preservation
        proposals.append(
            f"preserves_local_bound({hole.hole_id})"
        )
    elif premise_class is PremiseClass.SYNTHESIZE_CONTRACT:
        if base and not base.lower().startswith("missing"):
            proposals.append(base)
        kind_label = hole.kind.value
        proposals.append(f"contract:{kind_label}({hole.hole_id})")
    elif premise_class is PremiseClass.SYNTHESIZE_LEMMA:
        if base and not base.lower().startswith("missing"):
            proposals.append(base)
        proposals.append(f"lemma_bridge({hole.hole_id})")
    elif premise_class is PremiseClass.ENVIRONMENT_ASSUMPTION:
        if base and not base.lower().startswith("missing"):
            proposals.append(base)
        proposals.append(f"env_assumption({hole.hole_id})")
    elif premise_class is PremiseClass.FACT_TO_PROVE:
        if base and not base.lower().startswith("missing"):
            proposals.append(f"prove({base})")
        else:
            # Use reason-derived fact label, not circular restatement of hole
            label = reason if reason else hole.hole_id
            proposals.append(f"prove_fact({label})")
    elif premise_class is PremiseClass.UNSUPPORTED_SEMANTICS:
        proposals.append(
            base or f"unsupported_semantics({hole.hole_id})"
        )
    elif premise_class is PremiseClass.UNAVAILABLE_AUTHORITY:
        proposals.append(
            base or f"unavailable_authority({hole.hole_id})"
        )
    elif premise_class is PremiseClass.IMPLEMENTATION_CHANGE:
        proposals.append(
            base or f"implementation_change({hole.hole_id})"
        )
    else:
        if base:
            proposals.append(base)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in proposals:
        key = _normalize_statement(p).lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return tuple(unique)


def _assumption_class_for(premise_class: PremiseClass) -> AssumptionClass:
    if premise_class is PremiseClass.ENVIRONMENT_ASSUMPTION:
        return AssumptionClass.HYPOTHETICAL
    if premise_class in {
        PremiseClass.FACT_TO_PROVE,
        PremiseClass.SYNTHESIZE_INVARIANT,
        PremiseClass.SYNTHESIZE_CONTRACT,
        PremiseClass.SYNTHESIZE_LEMMA,
    }:
        return AssumptionClass.MUST_PROVE
    return AssumptionClass.HYPOTHETICAL


def _weakness_score(
    premise_class: PremiseClass,
    statement: str,
    symbol_overlap: Sequence[str],
) -> int:
    base = _PREMISE_WEAKNESS_BASE.get(premise_class, 100_000)
    # Prefer fewer tokens (weaker / more minimal statements).
    tokens = _statement_tokens(statement)
    token_penalty = min(len(tokens) * 1_000, 50_000)
    overlap_bonus = min(len(symbol_overlap) * 500, 20_000)
    # Shorter statements score higher (weaker under syntactic measure).
    length_penalty = min(len(statement) * 10, 30_000)
    score = base + overlap_bonus - token_penalty - length_penalty
    return max(0, score)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MissingProofAbduction:
    """Bounded abductive search for weakest admissible missing premises.

    Interface: ``MissingProofAbduction@1``

    Owns classification and admissibility filtering of abductive candidates.
    Does **not** admit candidates into the trusted assumption set.
    """

    INTERFACE: ClassVar[str] = MISSING_PROOF_ABDUCTION_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = ABDUCTION_ALGORITHM_VERSION

    bounds: ResourceBounds = field(default_factory=lambda: DEFAULT_BOUNDS)
    max_candidates_per_hole: int = 8

    def __post_init__(self) -> None:
        object.__setattr__(self, "bounds", _bounds(self.bounds, "bounds"))
        object.__setattr__(
            self,
            "max_candidates_per_hole",
            _nonnegative_int(
                self.max_candidates_per_hole, "max_candidates_per_hole"
            ),
        )
        if self.max_candidates_per_hole == 0:
            limit = self.bounds.max_candidates or 8
            object.__setattr__(self, "max_candidates_per_hole", max(1, limit))

    def abduct(self, request: AbductionRequest | Mapping[str, Any]) -> AbductionResult:
        """Run bounded abductive search for *request*."""

        if isinstance(request, Mapping):
            request = AbductionRequest.from_dict(request)
        elif not isinstance(request, AbductionRequest):
            raise AbductionError("request must be an AbductionRequest")

        theory = request.theory
        bounds = _bounds(request.bounds, "bounds")
        max_steps = bounds.max_steps or self.bounds.max_steps or 64
        max_candidates = (
            bounds.max_candidates
            or self.bounds.max_candidates
            or self.max_candidates_per_hole
        )
        steps_used = 0
        budget_exhausted = False
        diagnostics: list[str] = []
        rejected: list[RejectedPremise] = []
        candidates: list[AbductionCandidate] = []
        seen_statements: set[str] = set()

        # Impossible goal → core/witness, no favorable premises.
        core = detect_impossible_goal(theory)
        if core is not None:
            result_id = _stable_id(
                "abduction", request.formal_goal_id, theory.theory_id, "impossible"
            )
            return AbductionResult(
                result_id=result_id,
                formal_goal_id=request.formal_goal_id,
                status=AbductionStatus.IMPOSSIBLE,
                candidates=(),
                rejected=(),
                unsat_core=core,
                theory_id=theory.theory_id,
                steps_used=1,
                budget_exhausted=False,
                diagnostics=(
                    "impossible target under declared finite theory; "
                    "returning unsat core/witness",
                ),
                classified_by_class={},
            )

        # Partition holes: non-proof diagnostics vs abductable
        non_proof_candidates: list[AbductionCandidate] = []
        abductable_holes: list[ProofHole] = []
        for hole in request.holes:
            steps_used += 1
            if steps_used > max_steps:
                budget_exhausted = True
                diagnostics.append("step budget exhausted during hole scan")
                break
            premise_class = classify_hole_kind(hole.kind)
            if hole.status in {
                HoleStatus.UNSUPPORTED,
                HoleStatus.UNAVAILABLE,
                HoleStatus.FALSE,
            } or is_non_proof_premise_class(premise_class):
                # Record diagnostic classification without admitting as premise
                stmt = (
                    hole.statement
                    or hole.reason
                    or f"{premise_class.value}({hole.hole_id})"
                )
                cand = AbductionCandidate(
                    candidate_id=_stable_id(
                        "abd", hole.hole_id, premise_class.value, stmt
                    ),
                    premise_class=premise_class,
                    statement=stmt,
                    hole_id=hole.hole_id,
                    source=hole.source,
                    formal_goal_id=request.formal_goal_id or hole.formal_goal_id,
                    theory_id=theory.theory_id,
                    authority=AuthorityCeiling.NONE,
                    assumption_class=AssumptionClass.HYPOTHETICAL,
                    reviewable=True,
                    weakness_score_millionths=_weakness_score(
                        premise_class, stmt, ()
                    ),
                    relevant=True,
                    consistent=True,
                    source_scoped=bool(
                        hole.source.tree_id or hole.source.source_ref_ids
                    ),
                    non_circular=True,
                    non_vacuous=True,
                    weak=True,
                    dependency_ids=hole.dependency_ids,
                    rationale=(
                        f"classified {premise_class.value} diagnostic from hole "
                        f"{hole.hole_id}"
                    ),
                    metadata={"diagnostic": True, "hole_kind": hole.kind.value},
                )
                non_proof_candidates.append(cand)
            else:
                abductable_holes.append(hole)

        # Generate and filter candidates per hole
        weaker_catalogue: list[str] = list(request.proposed_premises)
        for hole in abductable_holes:
            if budget_exhausted:
                break
            premise_class = classify_hole_kind(hole.kind)
            statements = list(_default_statements_for_hole(hole))
            # Caller-proposed premises applicable to all holes (filtered)
            statements.extend(request.proposed_premises)

            hole_candidate_count = 0
            for statement in statements:
                steps_used += 1
                if steps_used > max_steps:
                    budget_exhausted = True
                    diagnostics.append("step budget exhausted during abduction")
                    break
                if hole_candidate_count >= self.max_candidates_per_hole:
                    diagnostics.append(
                        f"per-hole candidate cap reached for {hole.hole_id}"
                    )
                    break
                if len(candidates) + len(non_proof_candidates) >= max_candidates:
                    budget_exhausted = True
                    diagnostics.append("max_candidates budget exhausted")
                    break

                key = _normalize_statement(statement).lower()
                if key in seen_statements:
                    rejected.append(
                        RejectedPremise(
                            statement=statement,
                            reason=RejectionReason.DUPLICATE,
                            hole_id=hole.hole_id,
                            premise_class=premise_class,
                        )
                    )
                    continue

                report = check_admissibility(
                    statement,
                    theory=theory,
                    hole=hole,
                    premise_class=premise_class,
                    stronger_than=weaker_catalogue,
                )
                if not report.ok:
                    rejected.append(
                        RejectedPremise(
                            statement=statement,
                            reason=report.rejection
                            or RejectionReason.MALFORMED,
                            hole_id=hole.hole_id,
                            premise_class=premise_class,
                            detail=report.detail,
                        )
                    )
                    continue

                seen_statements.add(key)
                weaker_catalogue.append(statement)
                score = _weakness_score(
                    premise_class, statement, report.symbol_overlap
                )
                cand = AbductionCandidate(
                    candidate_id=_stable_id(
                        "abd", hole.hole_id, premise_class.value, statement
                    ),
                    premise_class=premise_class,
                    statement=statement,
                    hole_id=hole.hole_id,
                    source=hole.source,
                    formal_goal_id=request.formal_goal_id or hole.formal_goal_id,
                    theory_id=theory.theory_id,
                    authority=AuthorityCeiling.CANDIDATE,
                    assumption_class=_assumption_class_for(premise_class),
                    reviewable=True,
                    weakness_score_millionths=score,
                    relevant=report.relevant,
                    consistent=report.consistent,
                    source_scoped=report.source_scoped,
                    non_circular=report.non_circular,
                    non_vacuous=report.non_vacuous,
                    weak=report.weak,
                    dependency_ids=hole.dependency_ids,
                    symbol_overlap=report.symbol_overlap,
                    rationale=(
                        f"weak admissible {premise_class.value} for hole "
                        f"{hole.hole_id}"
                    ),
                    metadata={
                        "hole_kind": hole.kind.value,
                        "admissibility": report.detail or "passed",
                    },
                )
                candidates.append(cand)
                hole_candidate_count += 1

        # Also evaluate free-standing proposed premises against a synthetic hole
        # when no holes were provided.
        if not request.holes and request.proposed_premises:
            for statement in request.proposed_premises:
                steps_used += 1
                if steps_used > max_steps:
                    budget_exhausted = True
                    break
                if len(candidates) >= max_candidates:
                    budget_exhausted = True
                    break
                key = _normalize_statement(statement).lower()
                if key in seen_statements:
                    continue
                # Build a minimal synthetic binding from theory symbols
                synthetic_source = SourceSpanBinding(
                    tree_id=request.tree_id or "tree:unknown",
                    source_ref_ids=("source:abduction",),
                    span_ids=("span:proposed",),
                )
                synthetic_hole = ProofHole(
                    hole_id="hole:proposed",
                    kind=HoleKind.MISSING_SOURCE_FACT,
                    reason="caller-proposed premise",
                    source=synthetic_source,
                    formal_goal_id=request.formal_goal_id,
                    statement="missing_source_fact",
                    status=HoleStatus.OPEN,
                )
                report = check_admissibility(
                    statement,
                    theory=theory,
                    hole=synthetic_hole,
                    premise_class=PremiseClass.FACT_TO_PROVE,
                    stronger_than=weaker_catalogue,
                )
                if not report.ok:
                    rejected.append(
                        RejectedPremise(
                            statement=statement,
                            reason=report.rejection
                            or RejectionReason.MALFORMED,
                            hole_id=synthetic_hole.hole_id,
                            premise_class=PremiseClass.FACT_TO_PROVE,
                            detail=report.detail,
                        )
                    )
                    continue
                seen_statements.add(key)
                candidates.append(
                    AbductionCandidate(
                        candidate_id=_stable_id(
                            "abd", "proposed", statement
                        ),
                        premise_class=PremiseClass.FACT_TO_PROVE,
                        statement=statement,
                        hole_id=synthetic_hole.hole_id,
                        source=synthetic_source,
                        formal_goal_id=request.formal_goal_id,
                        theory_id=theory.theory_id,
                        authority=AuthorityCeiling.CANDIDATE,
                        assumption_class=AssumptionClass.MUST_PROVE,
                        reviewable=True,
                        weakness_score_millionths=_weakness_score(
                            PremiseClass.FACT_TO_PROVE,
                            statement,
                            report.symbol_overlap,
                        ),
                        relevant=report.relevant,
                        consistent=report.consistent,
                        source_scoped=report.source_scoped,
                        non_circular=report.non_circular,
                        non_vacuous=report.non_vacuous,
                        weak=report.weak,
                        symbol_overlap=report.symbol_overlap,
                        rationale="caller-proposed admissible premise",
                    )
                )

        # Prefer weaker candidates first
        candidates.sort(
            key=lambda c: (
                -c.weakness_score_millionths,
                c.premise_class.value,
                c.candidate_id,
            )
        )
        all_candidates = tuple(candidates) + tuple(non_proof_candidates)

        # Classify index
        classified: dict[str, list[str]] = {}
        for cand in all_candidates:
            classified.setdefault(cand.premise_class.value, []).append(
                cand.candidate_id
            )
        classified_frozen = {k: tuple(v) for k, v in classified.items()}

        # Status selection
        has_admissible = any(c.admissible for c in candidates)
        has_non_proof = bool(non_proof_candidates)
        only_unsupported = has_non_proof and not has_admissible and not candidates

        if budget_exhausted and has_admissible:
            status = AbductionStatus.BOUNDED
        elif budget_exhausted and not has_admissible:
            status = AbductionStatus.BOUNDED
        elif only_unsupported:
            # Determine dominant non-proof class
            classes = {c.premise_class for c in non_proof_candidates}
            if classes == {PremiseClass.UNSUPPORTED_SEMANTICS}:
                status = AbductionStatus.UNSUPPORTED
            elif classes == {PremiseClass.UNAVAILABLE_AUTHORITY}:
                status = AbductionStatus.UNAVAILABLE
            elif PremiseClass.IMPLEMENTATION_CHANGE in classes and len(classes) == 1:
                status = AbductionStatus.UNSUPPORTED
            else:
                status = AbductionStatus.PARTIAL
        elif has_admissible and (
            rejected or non_proof_candidates or budget_exhausted
        ):
            status = AbductionStatus.PARTIAL if (
                rejected or non_proof_candidates
            ) else AbductionStatus.CANDIDATES
        elif has_admissible:
            status = AbductionStatus.CANDIDATES
        elif not request.holes and not request.proposed_premises:
            status = AbductionStatus.EMPTY
            diagnostics.append("no holes or proposed premises provided")
        elif rejected and not candidates:
            # All proposals rejected — honest unknown (not silent failure)
            status = AbductionStatus.UNKNOWN
            diagnostics.append(
                "all proposed premises rejected; returning honest unknown"
            )
        else:
            status = AbductionStatus.EMPTY

        result_id = _stable_id(
            "abduction",
            request.formal_goal_id,
            theory.theory_id,
            status.value,
            str(len(all_candidates)),
        )
        return AbductionResult(
            result_id=result_id,
            formal_goal_id=request.formal_goal_id,
            status=status,
            candidates=all_candidates,
            rejected=tuple(rejected),
            unsat_core=None,
            theory_id=theory.theory_id,
            steps_used=steps_used,
            budget_exhausted=budget_exhausted,
            diagnostics=tuple(diagnostics),
            classified_by_class=classified_frozen,
        )


def abduct_missing_premises(
    request: AbductionRequest | Mapping[str, Any],
    *,
    bounds: ResourceBounds | Mapping[str, Any] | None = None,
    max_candidates_per_hole: int = 8,
) -> AbductionResult:
    """Module-level convenience for :meth:`MissingProofAbduction.abduct`."""

    engine = MissingProofAbduction(
        bounds=_bounds(bounds, "bounds") if bounds is not None else DEFAULT_BOUNDS,
        max_candidates_per_hole=max_candidates_per_hole,
    )
    if isinstance(request, Mapping):
        req = AbductionRequest.from_dict(request)
    else:
        req = request
    if bounds is not None and isinstance(req, AbductionRequest):
        req = replace(req, bounds=_bounds(bounds, "bounds"))
    return engine.abduct(req)


def classify_premise_classes() -> tuple[PremiseClass, ...]:
    """Return the closed set of abductive premise classes."""

    return tuple(PremiseClass)


__all__ = [
    "ABDUCTION_ALGORITHM_VERSION",
    "ABDUCTION_CANDIDATE_SCHEMA",
    "ABDUCTION_REQUEST_SCHEMA",
    "ABDUCTION_RESULT_SCHEMA",
    "DEFAULT_BOUNDS",
    "FINITE_THEORY_SCHEMA",
    "MISSING_PROOF_ABDUCTION_INTERFACE",
    "UNSAT_CORE_SCHEMA",
    "AbductionCandidate",
    "AbductionError",
    "AbductionRequest",
    "AbductionResult",
    "AbductionStatus",
    "AdmissibilityFlag",
    "FiniteTheory",
    "MissingProofAbduction",
    "PremiseClass",
    "RejectedPremise",
    "RejectionReason",
    "UnsatCoreWitness",
    "abduct_missing_premises",
    "cap_candidate_authority",
    "check_admissibility",
    "classify_hole_kind",
    "classify_premise_classes",
    "detect_impossible_goal",
    "is_contradiction_statement",
    "is_goal_entailing_assumption",
    "is_non_proof_premise_class",
    "is_vacuous_statement",
]
