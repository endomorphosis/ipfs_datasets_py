"""Shared, domain-neutral constraint and applicability contracts.

Interfaces:

* ``ConstraintArtifact@1`` — solver-neutral constraint bundle with identities,
  vocabulary, typed native views, statements, obligations, world policy,
  translations/reconstruction, coverage gaps, and diagnostics.
* ``ApplicabilityEvidence@1`` — hard-filter selectors and evidence that a
  constraint set applies to a concrete invocation context.
* ``SelectedPremiseSet@1`` — bounded, source-grounded premise selection receipt
  that never elevates ranking into applicability or truth.

This leaf deliberately imports no Legal/Security corpus rules, solvers,
retrievers, models, storage runtimes, package exports, or registries. Domain
adapters compose these contracts; they do not flatten logics or silently
concatenate modal, Datalog, temporal, Hoare, and SMT formulas.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final, Iterable

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    FrozenMap,
    ProofObligation,
    stable_digest,
)
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    DiagnosticReport,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AuthorityKind,
    AuthorityMismatchError,
    ResultAuthority,
)

from .samples import (
    FormalizationValidationError,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _sequence,
    _text,
    _unique_identifiers,
)
from .views import SymbolTable


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CONSTRAINT_ARTIFACT_INTERFACE: Final = "ConstraintArtifact@1"
APPLICABILITY_EVIDENCE_INTERFACE: Final = "ApplicabilityEvidence@1"
SELECTED_PREMISE_SET_INTERFACE: Final = "SelectedPremiseSet@1"

CONSTRAINT_ARTIFACT_SCHEMA_VERSION: Final = "constraint-artifact/v1"
APPLICABILITY_EVIDENCE_SCHEMA_VERSION: Final = "applicability-evidence/v1"
SELECTED_PREMISE_SET_SCHEMA_VERSION: Final = "selected-premise-set/v1"
CONSTRAINT_STATEMENT_SCHEMA_VERSION: Final = "constraint-statement/v1"
NATIVE_VIEW_BINDING_SCHEMA_VERSION: Final = "constraint-native-view/v1"
WORLD_POLICY_SCHEMA_VERSION: Final = "constraint-world-policy/v1"
APPLICABILITY_SELECTOR_SCHEMA_VERSION: Final = "applicability-selector/v1"
COVERAGE_GAP_SCHEMA_VERSION: Final = "constraint-coverage-gap/v1"
TRANSLATION_RECEIPT_SCHEMA_VERSION: Final = "constraint-translation/v1"
RECONSTRUCTION_RECEIPT_SCHEMA_VERSION: Final = "constraint-reconstruction/v1"
SELECTED_PREMISE_SCHEMA_VERSION: Final = "selected-premise/v1"

CONSTRAINT_IDENTITY_DOMAIN: Final = "constraint-artifact"
APPLICABILITY_IDENTITY_DOMAIN: Final = "applicability-evidence"
PREMISE_SET_IDENTITY_DOMAIN: Final = "selected-premise-set"

MAX_COLLECTION_ITEMS: Final = 1_024
MAX_STRING_CHARS: Final = 16_384

# Logic families that must never be silently concatenated into one formula.
# Cross-family work requires an explicit TranslationReceipt.
_CONCATENATION_SENSITIVE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "modal",
        "datalog",
        "temporal",
        "hoare",
        "smt",
        "first_order",
        "deontic",
        "threat_model",
        "policy",
    }
)

_KNOWN_LOGIC_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "unspecified",
        "first_order",
        "modal",
        "deontic",
        "datalog",
        "temporal",
        "hoare",
        "smt",
        "threat_model",
        "policy",
        "intent",
        "propositional",
        "higher_order",
        "linear",
        "separation",
    }
)


class ConstraintValidationError(FormalizationValidationError):
    """Raised when a constraint or applicability contract is malformed."""


class ConstraintRole(str, Enum):
    """Typed role of one constraint statement in an authorization view."""

    GRANT = "grant"
    PROHIBITION = "prohibition"
    OBLIGATION = "obligation"
    EXCEPTION = "exception"
    INVARIANT = "invariant"
    ASSUMPTION = "assumption"
    CLAIM = "claim"
    PREMISE = "premise"


class WorldPolicyKind(str, Enum):
    """Whether absence of a fact is treated as false or unknown."""

    CLOSED = "closed"
    OPEN = "open"


class ApplicabilityStatus(str, Enum):
    """Outcome of hard applicability filters (before ranking)."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"
    CONFLICT = "conflict"
    COVERAGE_GAP = "coverage_gap"
    UNSUPPORTED = "unsupported"


class CoverageGapKind(str, Enum):
    """Why corpus or evidence coverage is incomplete."""

    MISSING_JURISDICTION = "missing_jurisdiction"
    MISSING_AUTHORITY = "missing_authority"
    MISSING_TEMPORAL = "missing_temporal"
    MISSING_SUBJECT = "missing_subject"
    MISSING_RESOURCE = "missing_resource"
    MISSING_CAPABILITY = "missing_capability"
    MISSING_LOGIC = "missing_logic"
    MISSING_PREMISE = "missing_premise"
    MISSING_TRANSLATION = "missing_translation"
    MISSING_RECONSTRUCTION = "missing_reconstruction"
    UNKNOWN_SCHEMA = "unknown_schema"
    OTHER = "other"


class PremiseSelectionMethod(str, Enum):
    """How premises were bounded; ranking never establishes truth."""

    EXPLICIT = "explicit"
    HARD_FILTER = "hard_filter"
    DETERMINISTIC_RANK = "deterministic_rank"
    ADVISORY_RANK = "advisory_rank"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConstraintValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _bounded_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConstraintValidationError(f"{field_name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise ConstraintValidationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if allow_empty and value and value != value.strip():
        raise ConstraintValidationError(
            f"{field_name} must not have surrounding whitespace"
        )
    if len(value) > MAX_STRING_CHARS:
        raise ConstraintValidationError(
            f"{field_name} exceeds maximum length of {MAX_STRING_CHARS}"
        )
    return value


def _optional_identifier(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, field_name)


def _digest_or_empty(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    text = _text(value, field_name)
    if not _DIGEST_RE.fullmatch(text):
        raise ConstraintValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return text


def _require_digest(value: Any, field_name: str) -> str:
    text = _text(value, field_name)
    if not _DIGEST_RE.fullmatch(text):
        raise ConstraintValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return text


def _enum_value(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        raise ConstraintValidationError(
            f"unknown {field_name}: {value!r}"
        ) from exc


def _logic_family(value: Any, field_name: str = "logic_family") -> str:
    family = _identifier(value, field_name)
    if family not in _KNOWN_LOGIC_FAMILIES:
        raise ConstraintValidationError(
            f"unknown logic family: {family!r}"
        )
    return family


def _frozen_map(value: Any, field_name: str) -> FrozenMap:
    if isinstance(value, FrozenMap):
        return value
    return FrozenMap(_mapping(value, field_name))


def _bounded_sequence(value: Any, field_name: str) -> Sequence[Any]:
    seq = _sequence(value, field_name)
    if len(seq) > MAX_COLLECTION_ITEMS:
        raise ConstraintValidationError(
            f"{field_name} exceeds maximum of {MAX_COLLECTION_ITEMS} items"
        )
    return seq


def _reject_mutable_collection(value: Any, field_name: str) -> None:
    """Fail closed when a caller passes a live mutable container as a field.

    After construction all collections are tuples/FrozenMap.  This check is
    applied at construction boundaries so list/dict identity is not retained.
    """

    if isinstance(value, list):
        # Lists are accepted only as construction input; callers must not
        # expect shared mutation.  We still reject set/dict subclass tricks
        # that are not JSON-compatible mappings handled by FrozenMap.
        return
    if isinstance(value, set):
        raise ConstraintValidationError(
            f"{field_name} must not be a mutable set; use a sequence"
        )


def reject_result_authority_substitution(
    claimed: ResultAuthority | AuthorityKind | str,
    required: ResultAuthority | AuthorityKind | str,
) -> None:
    """Reject using one result-authority kind as if it were another.

    Satisfiability, monitoring, evidence readiness, and policy approval are
    never substitutable for theorem proof (or each other).
    """

    def _kind(value: ResultAuthority | AuthorityKind | str) -> AuthorityKind:
        if isinstance(value, ResultAuthority):
            return value.kind
        if isinstance(value, AuthorityKind):
            return value
        try:
            return AuthorityKind(str(value))
        except (TypeError, ValueError) as exc:
            raise ConstraintValidationError(
                f"unknown result authority kind: {value!r}"
            ) from exc

    claimed_kind = _kind(claimed)
    required_kind = _kind(required)
    if claimed_kind is not required_kind:
        raise AuthorityMismatchError(
            f"{claimed_kind.value} authority cannot be used as "
            f"{required_kind.value}; result-authority substitution is forbidden"
        )


def forbid_silent_logic_concatenation(
    logic_families: Iterable[str],
    *,
    context: str = "constraint statement",
) -> None:
    """Reject silent modal/Datalog/temporal/Hoare/SMT concatenation.

    Multiple native *views* may coexist on one artifact.  A single statement,
    formula, or reconstructed body may not mix distinct concatenation-sensitive
    logic families without an explicit translation receipt.
    """

    families = {
        _logic_family(item, "logic_family")
        for item in logic_families
        if item not in (None, "", "unspecified")
    }
    sensitive = families & _CONCATENATION_SENSITIVE_FAMILIES
    if len(sensitive) > 1:
        raise ConstraintValidationError(
            f"silent logic concatenation forbidden in {context}: "
            + ", ".join(sorted(sensitive))
            + "; emit separate native views and an explicit TranslationReceipt"
        )


# ---------------------------------------------------------------------------
# Leaf records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorldPolicy:
    """Open/closed-world evaluation policy bound into constraint artifacts."""

    kind: WorldPolicyKind
    default_on_unknown: str = "indeterminate"
    allow_negation_as_failure: bool = False
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = WORLD_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum_value(self.kind, WorldPolicyKind, "kind")
        )
        object.__setattr__(
            self,
            "default_on_unknown",
            _identifier(self.default_on_unknown, "default_on_unknown"),
        )
        if not isinstance(self.allow_negation_as_failure, bool):
            raise ConstraintValidationError(
                "allow_negation_as_failure must be a bool"
            )
        if (
            self.kind is WorldPolicyKind.OPEN
            and self.allow_negation_as_failure
        ):
            raise ConstraintValidationError(
                "open-world policy cannot enable negation-as-failure"
            )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != WORLD_POLICY_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported world policy schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_negation_as_failure": self.allow_negation_as_failure,
            "default_on_unknown": self.default_on_unknown,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorldPolicy":
        value = _mapping(value, "world policy")
        _reject_unknown(
            value,
            frozenset(
                {
                    "allow_negation_as_failure",
                    "default_on_unknown",
                    "kind",
                    "metadata",
                    "schema_version",
                }
            ),
            "world policy",
        )
        return cls(
            kind=value.get("kind", WorldPolicyKind.CLOSED.value),
            default_on_unknown=value.get("default_on_unknown", "indeterminate"),
            allow_negation_as_failure=bool(
                value.get("allow_negation_as_failure", False)
            ),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", WORLD_POLICY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class NativeViewBinding:
    """One typed native formal view without cross-logic flattening."""

    view_id: str
    logic_family: str
    formula_ids: tuple[str, ...] = ()
    statement_ids: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    description: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = NATIVE_VIEW_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_id", _identifier(self.view_id, "view_id"))
        object.__setattr__(
            self, "logic_family", _logic_family(self.logic_family)
        )
        object.__setattr__(
            self,
            "formula_ids",
            _unique_identifiers(
                _bounded_sequence(self.formula_ids, "formula_ids"),
                "formula_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "statement_ids",
            _unique_identifiers(
                _bounded_sequence(self.statement_ids, "statement_ids"),
                "statement_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "capabilities",
            _unique_identifiers(
                _bounded_sequence(self.capabilities, "capabilities"),
                "capabilities",
                sort=True,
            ),
        )
        if not isinstance(self.description, str):
            raise ConstraintValidationError("description must be a string")
        if len(self.description) > MAX_STRING_CHARS:
            raise ConstraintValidationError("description exceeds maximum length")
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != NATIVE_VIEW_BINDING_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported native view schema: {self.schema_version!r}"
            )
        # A native view binds exactly one logic family — never a blend.
        forbid_silent_logic_concatenation(
            (self.logic_family,),
            context=f"native view {self.view_id!r}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "description": self.description,
            "formula_ids": list(self.formula_ids),
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "statement_ids": list(self.statement_ids),
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativeViewBinding":
        value = _mapping(value, "native view")
        _reject_unknown(
            value,
            frozenset(
                {
                    "capabilities",
                    "description",
                    "formula_ids",
                    "logic_family",
                    "metadata",
                    "schema_version",
                    "statement_ids",
                    "view_id",
                }
            ),
            "native view",
        )
        return cls(
            view_id=value.get("view_id", ""),
            logic_family=value.get("logic_family", ""),
            formula_ids=tuple(
                _sequence(value.get("formula_ids", ()), "formula_ids")
            ),
            statement_ids=tuple(
                _sequence(value.get("statement_ids", ()), "statement_ids")
            ),
            capabilities=tuple(
                _sequence(value.get("capabilities", ()), "capabilities")
            ),
            description=value.get("description", ""),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", NATIVE_VIEW_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ConstraintStatement:
    """One typed, source-grounded constraint in a single logic family."""

    statement_id: str
    role: ConstraintRole
    logic_family: str
    expression: FrozenMap
    symbol_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    view_id: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = CONSTRAINT_STATEMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "statement_id", _identifier(self.statement_id, "statement_id")
        )
        object.__setattr__(
            self, "role", _enum_value(self.role, ConstraintRole, "role")
        )
        object.__setattr__(
            self, "logic_family", _logic_family(self.logic_family)
        )
        expression = (
            self.expression
            if isinstance(self.expression, FrozenMap)
            else FrozenMap(_mapping(self.expression, "expression"))
        )
        object.__setattr__(self, "expression", expression)
        # Reject expressions that smuggle multiple logic tags.
        embedded = expression.to_dict().get("logic_families")
        if embedded is not None:
            if not isinstance(embedded, list):
                raise ConstraintValidationError(
                    "expression.logic_families must be a list when present"
                )
            forbid_silent_logic_concatenation(
                [*embedded, self.logic_family],
                context=f"statement {self.statement_id!r}",
            )
        object.__setattr__(
            self,
            "symbol_ids",
            _unique_identifiers(
                _bounded_sequence(self.symbol_ids, "symbol_ids"),
                "symbol_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(
                _bounded_sequence(self.source_ref_ids, "source_ref_ids"),
                "source_ref_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "span_ids",
            _unique_identifiers(
                _bounded_sequence(self.span_ids, "span_ids"),
                "span_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_identifiers(
                _bounded_sequence(self.assumption_ids, "assumption_ids"),
                "assumption_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self, "view_id", _optional_identifier(self.view_id, "view_id")
        )
        if not self.source_ref_ids and not self.span_ids:
            raise ConstraintValidationError(
                f"statement {self.statement_id!r} must be source-grounded"
            )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CONSTRAINT_STATEMENT_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported constraint statement schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return f"sha256:{stable_digest(self.to_dict())}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "expression": self.expression.to_dict(),
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "role": self.role.value,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement_id": self.statement_id,
            "symbol_ids": list(self.symbol_ids),
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConstraintStatement":
        value = _mapping(value, "constraint statement")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "expression",
                    "logic_family",
                    "metadata",
                    "role",
                    "schema_version",
                    "source_ref_ids",
                    "span_ids",
                    "statement_id",
                    "symbol_ids",
                    "view_id",
                }
            ),
            "constraint statement",
        )
        return cls(
            statement_id=value.get("statement_id", ""),
            role=value.get("role", ""),
            logic_family=value.get("logic_family", ""),
            expression=_frozen_map(value.get("expression", {}), "expression"),
            symbol_ids=tuple(
                _sequence(value.get("symbol_ids", ()), "symbol_ids")
            ),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            assumption_ids=tuple(
                _sequence(value.get("assumption_ids", ()), "assumption_ids")
            ),
            view_id=value.get("view_id", ""),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", CONSTRAINT_STATEMENT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ApplicabilitySelector:
    """One hard-filter dimension used before ranking or premise selection."""

    selector_id: str
    dimension: str
    value: str
    match_kind: str = "exact"
    required: bool = True
    source_ref_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = APPLICABILITY_SELECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "selector_id", _identifier(self.selector_id, "selector_id")
        )
        object.__setattr__(
            self, "dimension", _identifier(self.dimension, "dimension")
        )
        object.__setattr__(
            self, "value", _bounded_text(self.value, "value")
        )
        object.__setattr__(
            self, "match_kind", _identifier(self.match_kind, "match_kind")
        )
        if not isinstance(self.required, bool):
            raise ConstraintValidationError("required must be a bool")
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(
                _bounded_sequence(self.source_ref_ids, "source_ref_ids"),
                "source_ref_ids",
                sort=True,
            ),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != APPLICABILITY_SELECTOR_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported applicability selector schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "match_kind": self.match_kind,
            "metadata": self.metadata.to_dict(),
            "required": self.required,
            "schema_version": self.schema_version,
            "selector_id": self.selector_id,
            "source_ref_ids": list(self.source_ref_ids),
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicabilitySelector":
        value = _mapping(value, "applicability selector")
        _reject_unknown(
            value,
            frozenset(
                {
                    "dimension",
                    "match_kind",
                    "metadata",
                    "required",
                    "schema_version",
                    "selector_id",
                    "source_ref_ids",
                    "value",
                }
            ),
            "applicability selector",
        )
        return cls(
            selector_id=value.get("selector_id", ""),
            dimension=value.get("dimension", ""),
            value=value.get("value", ""),
            match_kind=value.get("match_kind", "exact"),
            required=bool(value.get("required", True)),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", APPLICABILITY_SELECTOR_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """Explicit declaration that evidence or corpus coverage is incomplete."""

    gap_id: str
    kind: CoverageGapKind
    description: str
    subject_ids: tuple[str, ...] = ()
    related_selector_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = COVERAGE_GAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _identifier(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "kind", _enum_value(self.kind, CoverageGapKind, "kind")
        )
        object.__setattr__(
            self, "description", _bounded_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "subject_ids",
            _unique_identifiers(
                _bounded_sequence(self.subject_ids, "subject_ids"),
                "subject_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "related_selector_ids",
            _unique_identifiers(
                _bounded_sequence(
                    self.related_selector_ids, "related_selector_ids"
                ),
                "related_selector_ids",
                sort=True,
            ),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != COVERAGE_GAP_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported coverage gap schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "gap_id": self.gap_id,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "related_selector_ids": list(self.related_selector_ids),
            "schema_version": self.schema_version,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        value = _mapping(value, "coverage gap")
        _reject_unknown(
            value,
            frozenset(
                {
                    "description",
                    "gap_id",
                    "kind",
                    "metadata",
                    "related_selector_ids",
                    "schema_version",
                    "subject_ids",
                }
            ),
            "coverage gap",
        )
        return cls(
            gap_id=value.get("gap_id", ""),
            kind=value.get("kind", CoverageGapKind.OTHER.value),
            description=value.get("description", ""),
            subject_ids=tuple(
                _sequence(value.get("subject_ids", ()), "subject_ids")
            ),
            related_selector_ids=tuple(
                _sequence(
                    value.get("related_selector_ids", ()), "related_selector_ids"
                )
            ),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", COVERAGE_GAP_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TranslationReceipt:
    """Explicit, typed translation between two native logic families.

    Translation is never silent: source and target families must differ, and
    reconstruction of the target remains a separate receipt.
    """

    translation_id: str
    source_logic_family: str
    target_logic_family: str
    source_view_id: str
    target_view_id: str
    source_statement_ids: tuple[str, ...] = ()
    target_statement_ids: tuple[str, ...] = ()
    translator_id: str = ""
    translator_version: str = ""
    lossy: bool = False
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TRANSLATION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_id",
            _identifier(self.translation_id, "translation_id"),
        )
        object.__setattr__(
            self,
            "source_logic_family",
            _logic_family(self.source_logic_family, "source_logic_family"),
        )
        object.__setattr__(
            self,
            "target_logic_family",
            _logic_family(self.target_logic_family, "target_logic_family"),
        )
        if self.source_logic_family == self.target_logic_family:
            raise ConstraintValidationError(
                "translation must change logic family; identical families are "
                "not a translation"
            )
        object.__setattr__(
            self,
            "source_view_id",
            _identifier(self.source_view_id, "source_view_id"),
        )
        object.__setattr__(
            self,
            "target_view_id",
            _identifier(self.target_view_id, "target_view_id"),
        )
        if self.source_view_id == self.target_view_id:
            raise ConstraintValidationError(
                "translation source and target views must differ"
            )
        object.__setattr__(
            self,
            "source_statement_ids",
            _unique_identifiers(
                _bounded_sequence(
                    self.source_statement_ids, "source_statement_ids"
                ),
                "source_statement_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "target_statement_ids",
            _unique_identifiers(
                _bounded_sequence(
                    self.target_statement_ids, "target_statement_ids"
                ),
                "target_statement_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "translator_id",
            _optional_identifier(self.translator_id, "translator_id"),
        )
        object.__setattr__(
            self,
            "translator_version",
            _optional_identifier(self.translator_version, "translator_version"),
        )
        if not isinstance(self.lossy, bool):
            raise ConstraintValidationError("lossy must be a bool")
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != TRANSLATION_RECEIPT_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported translation schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lossy": self.lossy,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "source_logic_family": self.source_logic_family,
            "source_statement_ids": list(self.source_statement_ids),
            "source_view_id": self.source_view_id,
            "target_logic_family": self.target_logic_family,
            "target_statement_ids": list(self.target_statement_ids),
            "target_view_id": self.target_view_id,
            "translation_id": self.translation_id,
            "translator_id": self.translator_id,
            "translator_version": self.translator_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationReceipt":
        value = _mapping(value, "translation receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "lossy",
                    "metadata",
                    "schema_version",
                    "source_logic_family",
                    "source_statement_ids",
                    "source_view_id",
                    "target_logic_family",
                    "target_statement_ids",
                    "target_view_id",
                    "translation_id",
                    "translator_id",
                    "translator_version",
                }
            ),
            "translation receipt",
        )
        return cls(
            translation_id=value.get("translation_id", ""),
            source_logic_family=value.get("source_logic_family", ""),
            target_logic_family=value.get("target_logic_family", ""),
            source_view_id=value.get("source_view_id", ""),
            target_view_id=value.get("target_view_id", ""),
            source_statement_ids=tuple(
                _sequence(
                    value.get("source_statement_ids", ()), "source_statement_ids"
                )
            ),
            target_statement_ids=tuple(
                _sequence(
                    value.get("target_statement_ids", ()), "target_statement_ids"
                )
            ),
            translator_id=value.get("translator_id", ""),
            translator_version=value.get("translator_version", ""),
            lossy=bool(value.get("lossy", False)),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", TRANSLATION_RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ReconstructionReceipt:
    """Receipt that a target formula was reconstructed under a known logic."""

    reconstruction_id: str
    logic_family: str
    view_id: str
    statement_ids: tuple[str, ...] = ()
    reconstructor_id: str = ""
    reconstructor_version: str = ""
    source_digest: str = ""
    reconstructed_digest: str = ""
    faithful: bool = True
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = RECONSTRUCTION_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reconstruction_id",
            _identifier(self.reconstruction_id, "reconstruction_id"),
        )
        object.__setattr__(
            self, "logic_family", _logic_family(self.logic_family)
        )
        object.__setattr__(self, "view_id", _identifier(self.view_id, "view_id"))
        object.__setattr__(
            self,
            "statement_ids",
            _unique_identifiers(
                _bounded_sequence(self.statement_ids, "statement_ids"),
                "statement_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "reconstructor_id",
            _optional_identifier(self.reconstructor_id, "reconstructor_id"),
        )
        object.__setattr__(
            self,
            "reconstructor_version",
            _optional_identifier(
                self.reconstructor_version, "reconstructor_version"
            ),
        )
        object.__setattr__(
            self,
            "source_digest",
            _digest_or_empty(self.source_digest, "source_digest"),
        )
        object.__setattr__(
            self,
            "reconstructed_digest",
            _digest_or_empty(self.reconstructed_digest, "reconstructed_digest"),
        )
        if not isinstance(self.faithful, bool):
            raise ConstraintValidationError("faithful must be a bool")
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RECONSTRUCTION_RECEIPT_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported reconstruction schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "faithful": self.faithful,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "reconstructed_digest": self.reconstructed_digest,
            "reconstruction_id": self.reconstruction_id,
            "reconstructor_id": self.reconstructor_id,
            "reconstructor_version": self.reconstructor_version,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "statement_ids": list(self.statement_ids),
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReconstructionReceipt":
        value = _mapping(value, "reconstruction receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "faithful",
                    "logic_family",
                    "metadata",
                    "reconstructed_digest",
                    "reconstruction_id",
                    "reconstructor_id",
                    "reconstructor_version",
                    "schema_version",
                    "source_digest",
                    "statement_ids",
                    "view_id",
                }
            ),
            "reconstruction receipt",
        )
        return cls(
            reconstruction_id=value.get("reconstruction_id", ""),
            logic_family=value.get("logic_family", ""),
            view_id=value.get("view_id", ""),
            statement_ids=tuple(
                _sequence(value.get("statement_ids", ()), "statement_ids")
            ),
            reconstructor_id=value.get("reconstructor_id", ""),
            reconstructor_version=value.get("reconstructor_version", ""),
            source_digest=value.get("source_digest", ""),
            reconstructed_digest=value.get("reconstructed_digest", ""),
            faithful=bool(value.get("faithful", True)),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SelectedPremise:
    """One source-grounded premise retained after hard filters and ranking."""

    premise_id: str
    statement: str
    source_ref_ids: tuple[str, ...]
    logic_family: str = "unspecified"
    rank: int = 0
    score: float | None = None
    selection_method: PremiseSelectionMethod = PremiseSelectionMethod.EXPLICIT
    assumption_id: str = ""
    statement_id: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SELECTED_PREMISE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "premise_id", _identifier(self.premise_id, "premise_id")
        )
        object.__setattr__(
            self, "statement", _bounded_text(self.statement, "statement")
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(
                _bounded_sequence(self.source_ref_ids, "source_ref_ids"),
                "source_ref_ids",
                sort=True,
            ),
        )
        if not self.source_ref_ids:
            raise ConstraintValidationError(
                f"premise {self.premise_id!r} is ungrounded: "
                "source_ref_ids must be non-empty"
            )
        object.__setattr__(
            self, "logic_family", _logic_family(self.logic_family)
        )
        if not isinstance(self.rank, int) or isinstance(self.rank, bool):
            raise ConstraintValidationError("rank must be an int")
        if self.rank < 0:
            raise ConstraintValidationError("rank must be non-negative")
        if self.score is not None:
            if not isinstance(self.score, (int, float)) or isinstance(
                self.score, bool
            ):
                raise ConstraintValidationError("score must be a finite number")
            score = float(self.score)
            if score != score or score in (float("inf"), float("-inf")):
                raise ConstraintValidationError("score must be finite")
            object.__setattr__(self, "score", score)
        object.__setattr__(
            self,
            "selection_method",
            _enum_value(
                self.selection_method,
                PremiseSelectionMethod,
                "selection_method",
            ),
        )
        object.__setattr__(
            self,
            "assumption_id",
            _optional_identifier(self.assumption_id, "assumption_id"),
        )
        object.__setattr__(
            self,
            "statement_id",
            _optional_identifier(self.statement_id, "statement_id"),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SELECTED_PREMISE_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported selected premise schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "premise_id": self.premise_id,
            "rank": self.rank,
            "schema_version": self.schema_version,
            "score": self.score,
            "selection_method": self.selection_method.value,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
            "statement_id": self.statement_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SelectedPremise":
        value = _mapping(value, "selected premise")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_id",
                    "logic_family",
                    "metadata",
                    "premise_id",
                    "rank",
                    "schema_version",
                    "score",
                    "selection_method",
                    "source_ref_ids",
                    "statement",
                    "statement_id",
                }
            ),
            "selected premise",
        )
        return cls(
            premise_id=value.get("premise_id", ""),
            statement=value.get("statement", ""),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            logic_family=value.get("logic_family", "unspecified"),
            rank=int(value.get("rank", 0)),
            score=value.get("score", None),
            selection_method=value.get(
                "selection_method", PremiseSelectionMethod.EXPLICIT.value
            ),
            assumption_id=value.get("assumption_id", ""),
            statement_id=value.get("statement_id", ""),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", SELECTED_PREMISE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Primary interfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectedPremiseSet:
    """``SelectedPremiseSet@1`` — bounded premise selection receipt.

    Ranking and scores are diagnostic only.  They never establish
    applicability, authority, or theorem truth.
    """

    INTERFACE: ClassVar[str] = SELECTED_PREMISE_SET_INTERFACE

    set_id: str
    premises: tuple[SelectedPremise, ...]
    selection_method: PremiseSelectionMethod = PremiseSelectionMethod.EXPLICIT
    considered_count: int = 0
    filtered_count: int = 0
    budget: int = 0
    config_id: str = ""
    query_digest: str = ""
    notes: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SELECTED_PREMISE_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "set_id", _identifier(self.set_id, "set_id"))
        _reject_mutable_collection(self.premises, "premises")
        premises = tuple(
            item
            if isinstance(item, SelectedPremise)
            else SelectedPremise.from_dict(_mapping(item, "premise"))
            for item in _bounded_sequence(self.premises, "premises")
        )
        premise_ids = [item.premise_id for item in premises]
        if len(premise_ids) != len(set(premise_ids)):
            raise ConstraintValidationError(
                "selected premise IDs must be unique"
            )
        object.__setattr__(
            self,
            "premises",
            tuple(sorted(premises, key=lambda item: (item.rank, item.premise_id))),
        )
        object.__setattr__(
            self,
            "selection_method",
            _enum_value(
                self.selection_method,
                PremiseSelectionMethod,
                "selection_method",
            ),
        )
        for name in ("considered_count", "filtered_count", "budget"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ConstraintValidationError(
                    f"{name} must be a non-negative int"
                )
        if self.budget and len(self.premises) > self.budget:
            raise ConstraintValidationError(
                "selected premises exceed declared budget"
            )
        if self.considered_count and self.considered_count < len(self.premises):
            raise ConstraintValidationError(
                "considered_count must be at least the number of selected premises"
            )
        object.__setattr__(
            self, "config_id", _optional_identifier(self.config_id, "config_id")
        )
        object.__setattr__(
            self,
            "query_digest",
            _digest_or_empty(self.query_digest, "query_digest"),
        )
        if not isinstance(self.notes, str):
            raise ConstraintValidationError("notes must be a string")
        if len(self.notes) > MAX_STRING_CHARS:
            raise ConstraintValidationError("notes exceeds maximum length")
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != SELECTED_PREMISE_SET_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported selected premise set schema: {self.schema_version!r}"
            )

    def premise(self, premise_id: str) -> SelectedPremise:
        for item in self.premises:
            if item.premise_id == premise_id:
                return item
        raise KeyError(premise_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "config_id": self.config_id,
            "considered_count": self.considered_count,
            "filtered_count": self.filtered_count,
            "interface": self.INTERFACE,
            "metadata": self.metadata.to_dict(),
            "notes": self.notes,
            "premises": [item.to_dict() for item in self.premises],
            "query_digest": self.query_digest,
            "schema_version": self.schema_version,
            "selection_method": self.selection_method.value,
            "set_id": self.set_id,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        payload = {key: value for key, value in self.to_dict().items()}
        return canonical_identity(
            payload,
            domain=PREMISE_SET_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_semantics={
                "/premises": "ordered",
                "/premises/*/source_ref_ids": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SelectedPremiseSet":
        value = _mapping(value, "selected premise set")
        _reject_unknown(
            value,
            frozenset(
                {
                    "budget",
                    "config_id",
                    "considered_count",
                    "filtered_count",
                    "interface",
                    "metadata",
                    "notes",
                    "premises",
                    "query_digest",
                    "schema_version",
                    "selection_method",
                    "set_id",
                }
            ),
            "selected premise set",
        )
        interface = value.get("interface", SELECTED_PREMISE_SET_INTERFACE)
        if interface != SELECTED_PREMISE_SET_INTERFACE:
            raise ConstraintValidationError(
                f"unknown selected premise set interface: {interface!r}"
            )
        return cls(
            set_id=value.get("set_id", ""),
            premises=tuple(
                SelectedPremise.from_dict(_mapping(item, "premise"))
                for item in _sequence(value.get("premises", ()), "premises")
            ),
            selection_method=value.get(
                "selection_method", PremiseSelectionMethod.EXPLICIT.value
            ),
            considered_count=int(value.get("considered_count", 0)),
            filtered_count=int(value.get("filtered_count", 0)),
            budget=int(value.get("budget", 0)),
            config_id=value.get("config_id", ""),
            query_digest=value.get("query_digest", ""),
            notes=value.get("notes", ""),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", SELECTED_PREMISE_SET_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "SelectedPremiseSet":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ConstraintValidationError(
                "selected premise set must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "selected premise set"))


@dataclass(frozen=True, slots=True)
class ApplicabilityEvidence:
    """``ApplicabilityEvidence@1`` — hard-filter applicability receipt.

    Ranking alone never produces ``APPLICABLE``.  Coverage gaps and conflicts
    remain explicit.
    """

    INTERFACE: ClassVar[str] = APPLICABILITY_EVIDENCE_INTERFACE

    evidence_id: str
    status: ApplicabilityStatus
    selectors: tuple[ApplicabilitySelector, ...]
    matched_selector_ids: tuple[str, ...] = ()
    rejected_selector_ids: tuple[str, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    constraint_artifact_id: str = ""
    constraint_artifact_digest: str = ""
    invocation_digest: str = ""
    world_policy: WorldPolicy | None = None
    required_authority: AuthorityKind | None = None
    notes: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = APPLICABILITY_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self,
            "status",
            _enum_value(self.status, ApplicabilityStatus, "status"),
        )
        _reject_mutable_collection(self.selectors, "selectors")
        selectors = tuple(
            item
            if isinstance(item, ApplicabilitySelector)
            else ApplicabilitySelector.from_dict(_mapping(item, "selector"))
            for item in _bounded_sequence(self.selectors, "selectors")
        )
        selector_ids = [item.selector_id for item in selectors]
        if len(selector_ids) != len(set(selector_ids)):
            raise ConstraintValidationError(
                "applicability selector IDs must be unique"
            )
        object.__setattr__(
            self,
            "selectors",
            tuple(sorted(selectors, key=lambda item: item.selector_id)),
        )
        known = {item.selector_id for item in self.selectors}
        object.__setattr__(
            self,
            "matched_selector_ids",
            _unique_identifiers(
                _bounded_sequence(
                    self.matched_selector_ids, "matched_selector_ids"
                ),
                "matched_selector_ids",
                sort=True,
            ),
        )
        object.__setattr__(
            self,
            "rejected_selector_ids",
            _unique_identifiers(
                _bounded_sequence(
                    self.rejected_selector_ids, "rejected_selector_ids"
                ),
                "rejected_selector_ids",
                sort=True,
            ),
        )
        unknown_matched = set(self.matched_selector_ids) - known
        if unknown_matched:
            raise ConstraintValidationError(
                "matched_selector_ids reference unknown selectors: "
                + ", ".join(sorted(unknown_matched))
            )
        unknown_rejected = set(self.rejected_selector_ids) - known
        if unknown_rejected:
            raise ConstraintValidationError(
                "rejected_selector_ids reference unknown selectors: "
                + ", ".join(sorted(unknown_rejected))
            )
        overlap = set(self.matched_selector_ids) & set(self.rejected_selector_ids)
        if overlap:
            raise ConstraintValidationError(
                "selector IDs cannot be both matched and rejected: "
                + ", ".join(sorted(overlap))
            )
        gaps = tuple(
            item
            if isinstance(item, CoverageGap)
            else CoverageGap.from_dict(_mapping(item, "coverage gap"))
            for item in _bounded_sequence(self.coverage_gaps, "coverage_gaps")
        )
        gap_ids = [item.gap_id for item in gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise ConstraintValidationError("coverage gap IDs must be unique")
        object.__setattr__(
            self,
            "coverage_gaps",
            tuple(sorted(gaps, key=lambda item: item.gap_id)),
        )
        for gap in self.coverage_gaps:
            unknown = set(gap.related_selector_ids) - known
            if unknown:
                raise ConstraintValidationError(
                    f"coverage gap {gap.gap_id!r} references unknown selectors: "
                    + ", ".join(sorted(unknown))
                )
        object.__setattr__(
            self,
            "constraint_artifact_id",
            _optional_identifier(
                self.constraint_artifact_id, "constraint_artifact_id"
            ),
        )
        object.__setattr__(
            self,
            "constraint_artifact_digest",
            _digest_or_empty(
                self.constraint_artifact_digest, "constraint_artifact_digest"
            ),
        )
        object.__setattr__(
            self,
            "invocation_digest",
            _digest_or_empty(self.invocation_digest, "invocation_digest"),
        )
        if self.world_policy is not None and not isinstance(
            self.world_policy, WorldPolicy
        ):
            if isinstance(self.world_policy, Mapping):
                object.__setattr__(
                    self,
                    "world_policy",
                    WorldPolicy.from_dict(self.world_policy),
                )
            else:
                raise ConstraintValidationError(
                    "world_policy must be a WorldPolicy or mapping"
                )
        if self.required_authority is not None:
            object.__setattr__(
                self,
                "required_authority",
                _enum_value(
                    self.required_authority,
                    AuthorityKind,
                    "required_authority",
                ),
            )
        if not isinstance(self.notes, str):
            raise ConstraintValidationError("notes must be a string")
        if len(self.notes) > MAX_STRING_CHARS:
            raise ConstraintValidationError("notes exceeds maximum length")
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != APPLICABILITY_EVIDENCE_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported applicability evidence schema: {self.schema_version!r}"
            )
        # Fail-closed consistency rules.
        if self.status is ApplicabilityStatus.APPLICABLE:
            if self.rejected_selector_ids:
                raise ConstraintValidationError(
                    "APPLICABLE evidence cannot retain rejected selectors"
                )
            if self.coverage_gaps:
                raise ConstraintValidationError(
                    "APPLICABLE evidence cannot retain coverage gaps"
                )
            required = {
                item.selector_id for item in self.selectors if item.required
            }
            if required - set(self.matched_selector_ids):
                raise ConstraintValidationError(
                    "APPLICABLE evidence must match all required selectors"
                )
        if self.status is ApplicabilityStatus.COVERAGE_GAP and not self.coverage_gaps:
            raise ConstraintValidationError(
                "COVERAGE_GAP status requires at least one coverage gap"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_artifact_digest": self.constraint_artifact_digest,
            "constraint_artifact_id": self.constraint_artifact_id,
            "coverage_gaps": [item.to_dict() for item in self.coverage_gaps],
            "evidence_id": self.evidence_id,
            "interface": self.INTERFACE,
            "invocation_digest": self.invocation_digest,
            "matched_selector_ids": list(self.matched_selector_ids),
            "metadata": self.metadata.to_dict(),
            "notes": self.notes,
            "rejected_selector_ids": list(self.rejected_selector_ids),
            "required_authority": (
                self.required_authority.value
                if self.required_authority is not None
                else ""
            ),
            "schema_version": self.schema_version,
            "selectors": [item.to_dict() for item in self.selectors],
            "status": self.status.value,
            "world_policy": (
                self.world_policy.to_dict()
                if self.world_policy is not None
                else None
            ),
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=APPLICABILITY_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_semantics={
                "/selectors": "set-like",
                "/matched_selector_ids": "set-like",
                "/rejected_selector_ids": "set-like",
                "/coverage_gaps": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    def require_authority(self, claimed: ResultAuthority | AuthorityKind | str) -> None:
        """Reject result-authority substitution against the required kind."""

        if self.required_authority is None:
            return
        reject_result_authority_substitution(claimed, self.required_authority)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicabilityEvidence":
        value = _mapping(value, "applicability evidence")
        _reject_unknown(
            value,
            frozenset(
                {
                    "constraint_artifact_digest",
                    "constraint_artifact_id",
                    "coverage_gaps",
                    "evidence_id",
                    "interface",
                    "invocation_digest",
                    "matched_selector_ids",
                    "metadata",
                    "notes",
                    "rejected_selector_ids",
                    "required_authority",
                    "schema_version",
                    "selectors",
                    "status",
                    "world_policy",
                }
            ),
            "applicability evidence",
        )
        interface = value.get("interface", APPLICABILITY_EVIDENCE_INTERFACE)
        if interface != APPLICABILITY_EVIDENCE_INTERFACE:
            raise ConstraintValidationError(
                f"unknown applicability evidence interface: {interface!r}"
            )
        authority = value.get("required_authority", "")
        world = value.get("world_policy", None)
        return cls(
            evidence_id=value.get("evidence_id", ""),
            status=value.get("status", ""),
            selectors=tuple(
                ApplicabilitySelector.from_dict(_mapping(item, "selector"))
                for item in _sequence(value.get("selectors", ()), "selectors")
            ),
            matched_selector_ids=tuple(
                _sequence(
                    value.get("matched_selector_ids", ()), "matched_selector_ids"
                )
            ),
            rejected_selector_ids=tuple(
                _sequence(
                    value.get("rejected_selector_ids", ()),
                    "rejected_selector_ids",
                )
            ),
            coverage_gaps=tuple(
                CoverageGap.from_dict(_mapping(item, "coverage gap"))
                for item in _sequence(
                    value.get("coverage_gaps", ()), "coverage_gaps"
                )
            ),
            constraint_artifact_id=value.get("constraint_artifact_id", ""),
            constraint_artifact_digest=value.get(
                "constraint_artifact_digest", ""
            ),
            invocation_digest=value.get("invocation_digest", ""),
            world_policy=(
                WorldPolicy.from_dict(_mapping(world, "world_policy"))
                if world is not None
                else None
            ),
            required_authority=authority or None,
            notes=value.get("notes", ""),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", APPLICABILITY_EVIDENCE_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "ApplicabilityEvidence":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ConstraintValidationError(
                "applicability evidence must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "applicability evidence"))


@dataclass(frozen=True, slots=True)
class ConstraintArtifact:
    """``ConstraintArtifact@1`` — domain-neutral constraint bundle.

    Binds domain, logic, source, corpus, and configuration identities to typed
    native views, vocabulary, statements, applicability, world policy, premise
    selection, translations/reconstruction, coverage gaps, diagnostics, and
    stable obligations without flattening logics.
    """

    INTERFACE: ClassVar[str] = CONSTRAINT_ARTIFACT_INTERFACE

    artifact_id: str
    domain: str
    logic_family: str
    source_id: str
    corpus_id: str
    config_id: str
    declaration_id: str
    declaration_digest: str
    vocabulary: SymbolTable
    native_views: tuple[NativeViewBinding, ...]
    statements: tuple[ConstraintStatement, ...]
    world_policy: WorldPolicy
    assumptions: tuple[Assumption, ...] = ()
    proof_obligations: tuple[ProofObligation, ...] = ()
    applicability_selectors: tuple[ApplicabilitySelector, ...] = ()
    applicability_evidence: ApplicabilityEvidence | None = None
    selected_premises: SelectedPremiseSet | None = None
    translations: tuple[TranslationReceipt, ...] = ()
    reconstructions: tuple[ReconstructionReceipt, ...] = ()
    coverage_gaps: tuple[CoverageGap, ...] = ()
    diagnostics: DiagnosticReport | None = None
    adapter_id: str = ""
    compiler_id: str = ""
    ontology_id: str = ""
    policy_id: str = ""
    producer_id: str = ""
    required_authority: AuthorityKind | None = None
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = CONSTRAINT_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(self, "domain", _identifier(self.domain, "domain"))
        object.__setattr__(
            self, "logic_family", _logic_family(self.logic_family)
        )
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "corpus_id", _identifier(self.corpus_id, "corpus_id")
        )
        object.__setattr__(
            self, "config_id", _identifier(self.config_id, "config_id")
        )
        object.__setattr__(
            self,
            "declaration_id",
            _identifier(self.declaration_id, "declaration_id"),
        )
        object.__setattr__(
            self,
            "declaration_digest",
            _require_digest(self.declaration_digest, "declaration_digest"),
        )
        if not isinstance(self.vocabulary, SymbolTable):
            if isinstance(self.vocabulary, Mapping):
                object.__setattr__(
                    self,
                    "vocabulary",
                    SymbolTable.from_dict(self.vocabulary),
                )
            else:
                raise ConstraintValidationError(
                    "vocabulary must be a SymbolTable"
                )
        _reject_mutable_collection(self.native_views, "native_views")
        views = tuple(
            item
            if isinstance(item, NativeViewBinding)
            else NativeViewBinding.from_dict(_mapping(item, "native view"))
            for item in _bounded_sequence(self.native_views, "native_views")
        )
        view_ids = [item.view_id for item in views]
        if len(view_ids) != len(set(view_ids)):
            raise ConstraintValidationError("native view IDs must be unique")
        if not views:
            raise ConstraintValidationError(
                "constraint artifact requires at least one native view"
            )
        object.__setattr__(
            self,
            "native_views",
            tuple(sorted(views, key=lambda item: item.view_id)),
        )
        statements = tuple(
            item
            if isinstance(item, ConstraintStatement)
            else ConstraintStatement.from_dict(_mapping(item, "statement"))
            for item in _bounded_sequence(self.statements, "statements")
        )
        statement_ids = [item.statement_id for item in statements]
        if len(statement_ids) != len(set(statement_ids)):
            raise ConstraintValidationError("statement IDs must be unique")
        object.__setattr__(
            self,
            "statements",
            tuple(sorted(statements, key=lambda item: item.statement_id)),
        )
        if not isinstance(self.world_policy, WorldPolicy):
            if isinstance(self.world_policy, Mapping):
                object.__setattr__(
                    self,
                    "world_policy",
                    WorldPolicy.from_dict(self.world_policy),
                )
            else:
                raise ConstraintValidationError(
                    "world_policy must be a WorldPolicy"
                )
        assumptions = tuple(
            item
            if isinstance(item, Assumption)
            else Assumption.from_dict(_mapping(item, "assumption"))
            for item in _bounded_sequence(self.assumptions, "assumptions")
        )
        assumption_ids = [item.assumption_id for item in assumptions]
        if len(assumption_ids) != len(set(assumption_ids)):
            raise ConstraintValidationError("assumption IDs must be unique")
        object.__setattr__(
            self,
            "assumptions",
            tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
        )
        obligations = tuple(
            item
            if isinstance(item, ProofObligation)
            else ProofObligation.from_dict(_mapping(item, "proof obligation"))
            for item in _bounded_sequence(
                self.proof_obligations, "proof_obligations"
            )
        )
        obligation_ids = [item.obligation_id for item in obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ConstraintValidationError(
                "proof obligation IDs must be unique"
            )
        # Stable obligation ordering by ID (canonical).
        object.__setattr__(
            self,
            "proof_obligations",
            tuple(sorted(obligations, key=lambda item: item.obligation_id)),
        )
        selectors = tuple(
            item
            if isinstance(item, ApplicabilitySelector)
            else ApplicabilitySelector.from_dict(_mapping(item, "selector"))
            for item in _bounded_sequence(
                self.applicability_selectors, "applicability_selectors"
            )
        )
        selector_ids = [item.selector_id for item in selectors]
        if len(selector_ids) != len(set(selector_ids)):
            raise ConstraintValidationError(
                "applicability selector IDs must be unique"
            )
        object.__setattr__(
            self,
            "applicability_selectors",
            tuple(sorted(selectors, key=lambda item: item.selector_id)),
        )
        if self.applicability_evidence is not None:
            if isinstance(self.applicability_evidence, Mapping):
                object.__setattr__(
                    self,
                    "applicability_evidence",
                    ApplicabilityEvidence.from_dict(self.applicability_evidence),
                )
            elif not isinstance(self.applicability_evidence, ApplicabilityEvidence):
                raise ConstraintValidationError(
                    "applicability_evidence must be ApplicabilityEvidence"
                )
        if self.selected_premises is not None:
            if isinstance(self.selected_premises, Mapping):
                object.__setattr__(
                    self,
                    "selected_premises",
                    SelectedPremiseSet.from_dict(self.selected_premises),
                )
            elif not isinstance(self.selected_premises, SelectedPremiseSet):
                raise ConstraintValidationError(
                    "selected_premises must be a SelectedPremiseSet"
                )
        translations = tuple(
            item
            if isinstance(item, TranslationReceipt)
            else TranslationReceipt.from_dict(_mapping(item, "translation"))
            for item in _bounded_sequence(self.translations, "translations")
        )
        translation_ids = [item.translation_id for item in translations]
        if len(translation_ids) != len(set(translation_ids)):
            raise ConstraintValidationError("translation IDs must be unique")
        object.__setattr__(
            self,
            "translations",
            tuple(sorted(translations, key=lambda item: item.translation_id)),
        )
        reconstructions = tuple(
            item
            if isinstance(item, ReconstructionReceipt)
            else ReconstructionReceipt.from_dict(
                _mapping(item, "reconstruction")
            )
            for item in _bounded_sequence(
                self.reconstructions, "reconstructions"
            )
        )
        reconstruction_ids = [item.reconstruction_id for item in reconstructions]
        if len(reconstruction_ids) != len(set(reconstruction_ids)):
            raise ConstraintValidationError("reconstruction IDs must be unique")
        object.__setattr__(
            self,
            "reconstructions",
            tuple(
                sorted(reconstructions, key=lambda item: item.reconstruction_id)
            ),
        )
        gaps = tuple(
            item
            if isinstance(item, CoverageGap)
            else CoverageGap.from_dict(_mapping(item, "coverage gap"))
            for item in _bounded_sequence(self.coverage_gaps, "coverage_gaps")
        )
        gap_ids = [item.gap_id for item in gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise ConstraintValidationError("coverage gap IDs must be unique")
        object.__setattr__(
            self,
            "coverage_gaps",
            tuple(sorted(gaps, key=lambda item: item.gap_id)),
        )
        if self.diagnostics is not None and not isinstance(
            self.diagnostics, DiagnosticReport
        ):
            if isinstance(self.diagnostics, Mapping):
                object.__setattr__(
                    self,
                    "diagnostics",
                    DiagnosticReport.from_dict(self.diagnostics),
                )
            else:
                raise ConstraintValidationError(
                    "diagnostics must be a DiagnosticReport"
                )
        for name in (
            "adapter_id",
            "compiler_id",
            "ontology_id",
            "policy_id",
            "producer_id",
        ):
            object.__setattr__(
                self, name, _optional_identifier(getattr(self, name), name)
            )
        if self.required_authority is not None:
            object.__setattr__(
                self,
                "required_authority",
                _enum_value(
                    self.required_authority,
                    AuthorityKind,
                    "required_authority",
                ),
            )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        self.validate()

    def validate(self) -> "ConstraintArtifact":
        """Cross-reference and fail-closed integrity checks."""

        if self.schema_version != CONSTRAINT_ARTIFACT_SCHEMA_VERSION:
            raise ConstraintValidationError(
                f"unsupported constraint artifact schema: {self.schema_version!r}"
            )

        known_views = {item.view_id: item for item in self.native_views}
        known_statements = {item.statement_id: item for item in self.statements}
        known_symbols = set(self.vocabulary.symbol_ids)
        known_assumptions = {item.assumption_id for item in self.assumptions}
        known_selectors = {
            item.selector_id for item in self.applicability_selectors
        }

        for statement in self.statements:
            unknown_symbols = set(statement.symbol_ids) - known_symbols
            if unknown_symbols:
                raise ConstraintValidationError(
                    f"statement {statement.statement_id!r} references unknown "
                    f"vocabulary symbols: {', '.join(sorted(unknown_symbols))}"
                )
            unknown_assumptions = set(statement.assumption_ids) - known_assumptions
            if unknown_assumptions:
                raise ConstraintValidationError(
                    f"statement {statement.statement_id!r} references unknown "
                    f"assumptions: {', '.join(sorted(unknown_assumptions))}"
                )
            if statement.view_id and statement.view_id not in known_views:
                raise ConstraintValidationError(
                    f"statement {statement.statement_id!r} references unknown "
                    f"view {statement.view_id!r}"
                )
            if statement.view_id:
                view = known_views[statement.view_id]
                if view.logic_family != statement.logic_family:
                    raise ConstraintValidationError(
                        f"statement {statement.statement_id!r} logic_family "
                        f"{statement.logic_family!r} disagrees with native view "
                        f"{view.view_id!r} ({view.logic_family!r})"
                    )

        for view in self.native_views:
            unknown = set(view.statement_ids) - set(known_statements)
            if unknown:
                raise ConstraintValidationError(
                    f"native view {view.view_id!r} references unknown "
                    f"statements: {', '.join(sorted(unknown))}"
                )
            for statement_id in view.statement_ids:
                statement = known_statements[statement_id]
                if statement.logic_family != view.logic_family:
                    raise ConstraintValidationError(
                        f"native view {view.view_id!r} cannot bind statement "
                        f"{statement_id!r} from logic family "
                        f"{statement.logic_family!r}"
                    )

        # Multiple native views may coexist; each is single-family.  Never
        # allow one statement expression to smuggle a cross-family blend
        # without a translation receipt covering those families.
        for translation in self.translations:
            if translation.source_view_id not in known_views:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} references "
                    f"unknown source view {translation.source_view_id!r}"
                )
            if translation.target_view_id not in known_views:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} references "
                    f"unknown target view {translation.target_view_id!r}"
                )
            source_view = known_views[translation.source_view_id]
            target_view = known_views[translation.target_view_id]
            if source_view.logic_family != translation.source_logic_family:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} source logic "
                    "disagrees with source view"
                )
            if target_view.logic_family != translation.target_logic_family:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} target logic "
                    "disagrees with target view"
                )
            unknown_src = set(translation.source_statement_ids) - set(
                known_statements
            )
            if unknown_src:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} references "
                    f"unknown source statements: {', '.join(sorted(unknown_src))}"
                )
            unknown_tgt = set(translation.target_statement_ids) - set(
                known_statements
            )
            if unknown_tgt:
                raise ConstraintValidationError(
                    f"translation {translation.translation_id!r} references "
                    f"unknown target statements: {', '.join(sorted(unknown_tgt))}"
                )

        for reconstruction in self.reconstructions:
            if reconstruction.view_id not in known_views:
                raise ConstraintValidationError(
                    f"reconstruction {reconstruction.reconstruction_id!r} "
                    f"references unknown view {reconstruction.view_id!r}"
                )
            view = known_views[reconstruction.view_id]
            if view.logic_family != reconstruction.logic_family:
                raise ConstraintValidationError(
                    f"reconstruction {reconstruction.reconstruction_id!r} "
                    "logic disagrees with view"
                )
            unknown = set(reconstruction.statement_ids) - set(known_statements)
            if unknown:
                raise ConstraintValidationError(
                    f"reconstruction {reconstruction.reconstruction_id!r} "
                    f"references unknown statements: {', '.join(sorted(unknown))}"
                )

        for obligation in self.proof_obligations:
            unknown = set(obligation.assumption_ids) - known_assumptions
            if unknown:
                raise ConstraintValidationError(
                    f"obligation {obligation.obligation_id!r} references "
                    f"unknown assumptions: {', '.join(sorted(unknown))}"
                )
            try:
                _logic_family(obligation.logic_family, "obligation.logic_family")
            except ConstraintValidationError as exc:
                raise ConstraintValidationError(
                    f"obligation {obligation.obligation_id!r} has "
                    f"unknown logic family: {obligation.logic_family!r}"
                ) from exc

        if self.applicability_evidence is not None:
            evidence = self.applicability_evidence
            if (
                evidence.constraint_artifact_id
                and evidence.constraint_artifact_id != self.artifact_id
            ):
                raise ConstraintValidationError(
                    "applicability evidence constraint_artifact_id disagrees "
                    "with artifact_id"
                )
            # Evidence selectors should be a subset of declared selectors when
            # the artifact declares any.
            if known_selectors:
                evidence_selector_ids = {
                    item.selector_id for item in evidence.selectors
                }
                unknown = evidence_selector_ids - known_selectors
                if unknown:
                    raise ConstraintValidationError(
                        "applicability evidence selectors not declared on "
                        "artifact: " + ", ".join(sorted(unknown))
                    )

        if self.selected_premises is not None:
            for premise in self.selected_premises.premises:
                if (
                    premise.assumption_id
                    and premise.assumption_id not in known_assumptions
                ):
                    raise ConstraintValidationError(
                        f"selected premise {premise.premise_id!r} references "
                        f"unknown assumption {premise.assumption_id!r}"
                    )
                if (
                    premise.statement_id
                    and premise.statement_id not in known_statements
                ):
                    raise ConstraintValidationError(
                        f"selected premise {premise.premise_id!r} references "
                        f"unknown statement {premise.statement_id!r}"
                    )

        for gap in self.coverage_gaps:
            unknown = set(gap.related_selector_ids) - known_selectors
            if unknown and known_selectors:
                raise ConstraintValidationError(
                    f"coverage gap {gap.gap_id!r} references unknown "
                    f"selectors: {', '.join(sorted(unknown))}"
                )

        return self

    def obligation_digests(self) -> dict[str, str]:
        """Stable digests for each proof obligation (ID → digest)."""

        return {
            item.obligation_id: item.digest for item in self.proof_obligations
        }

    def require_authority(
        self, claimed: ResultAuthority | AuthorityKind | str
    ) -> None:
        """Reject result-authority substitution against the required kind."""

        if self.required_authority is None:
            return
        reject_result_authority_substitution(claimed, self.required_authority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "applicability_evidence": (
                self.applicability_evidence.to_dict()
                if self.applicability_evidence is not None
                else None
            ),
            "applicability_selectors": [
                item.to_dict() for item in self.applicability_selectors
            ],
            "artifact_id": self.artifact_id,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "compiler_id": self.compiler_id,
            "config_id": self.config_id,
            "corpus_id": self.corpus_id,
            "coverage_gaps": [item.to_dict() for item in self.coverage_gaps],
            "declaration_digest": self.declaration_digest,
            "declaration_id": self.declaration_id,
            "diagnostics": (
                self.diagnostics.to_dict()
                if self.diagnostics is not None
                else None
            ),
            "domain": self.domain,
            "interface": self.INTERFACE,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "native_views": [item.to_dict() for item in self.native_views],
            "ontology_id": self.ontology_id,
            "policy_id": self.policy_id,
            "producer_id": self.producer_id,
            "proof_obligations": [
                item.to_dict() for item in self.proof_obligations
            ],
            "reconstructions": [
                item.to_dict() for item in self.reconstructions
            ],
            "required_authority": (
                self.required_authority.value
                if self.required_authority is not None
                else ""
            ),
            "schema_version": self.schema_version,
            "selected_premises": (
                self.selected_premises.to_dict()
                if self.selected_premises is not None
                else None
            ),
            "source_id": self.source_id,
            "statements": [item.to_dict() for item in self.statements],
            "translations": [item.to_dict() for item in self.translations],
            "vocabulary": self.vocabulary.to_dict(),
            "world_policy": self.world_policy.to_dict(),
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain=CONSTRAINT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
            collection_semantics={
                "/native_views": "set-like",
                "/statements": "set-like",
                "/assumptions": "set-like",
                "/proof_obligations": "set-like",
                "/applicability_selectors": "set-like",
                "/translations": "set-like",
                "/reconstructions": "set-like",
                "/coverage_gaps": "set-like",
                "/vocabulary/symbols": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    @property
    def cid(self) -> str:
        return self.identity.cid

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConstraintArtifact":
        value = _mapping(value, "constraint artifact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adapter_id",
                    "applicability_evidence",
                    "applicability_selectors",
                    "artifact_id",
                    "assumptions",
                    "compiler_id",
                    "config_id",
                    "corpus_id",
                    "coverage_gaps",
                    "declaration_digest",
                    "declaration_id",
                    "diagnostics",
                    "domain",
                    "interface",
                    "logic_family",
                    "metadata",
                    "native_views",
                    "ontology_id",
                    "policy_id",
                    "producer_id",
                    "proof_obligations",
                    "reconstructions",
                    "required_authority",
                    "schema_version",
                    "selected_premises",
                    "source_id",
                    "statements",
                    "translations",
                    "vocabulary",
                    "world_policy",
                }
            ),
            "constraint artifact",
        )
        interface = value.get("interface", CONSTRAINT_ARTIFACT_INTERFACE)
        if interface != CONSTRAINT_ARTIFACT_INTERFACE:
            raise ConstraintValidationError(
                f"unknown constraint artifact interface: {interface!r}"
            )
        evidence = value.get("applicability_evidence")
        premises = value.get("selected_premises")
        diagnostics = value.get("diagnostics")
        authority = value.get("required_authority", "")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            domain=value.get("domain", ""),
            logic_family=value.get("logic_family", ""),
            source_id=value.get("source_id", ""),
            corpus_id=value.get("corpus_id", ""),
            config_id=value.get("config_id", ""),
            declaration_id=value.get("declaration_id", ""),
            declaration_digest=value.get("declaration_digest", ""),
            vocabulary=SymbolTable.from_dict(
                _mapping(value.get("vocabulary", {}), "vocabulary")
            ),
            native_views=tuple(
                NativeViewBinding.from_dict(_mapping(item, "native view"))
                for item in _sequence(
                    value.get("native_views", ()), "native_views"
                )
            ),
            statements=tuple(
                ConstraintStatement.from_dict(_mapping(item, "statement"))
                for item in _sequence(value.get("statements", ()), "statements")
            ),
            world_policy=WorldPolicy.from_dict(
                _mapping(value.get("world_policy", {}), "world_policy")
            ),
            assumptions=tuple(
                Assumption.from_dict(_mapping(item, "assumption"))
                for item in _sequence(value.get("assumptions", ()), "assumptions")
            ),
            proof_obligations=tuple(
                ProofObligation.from_dict(_mapping(item, "proof obligation"))
                for item in _sequence(
                    value.get("proof_obligations", ()), "proof_obligations"
                )
            ),
            applicability_selectors=tuple(
                ApplicabilitySelector.from_dict(_mapping(item, "selector"))
                for item in _sequence(
                    value.get("applicability_selectors", ()),
                    "applicability_selectors",
                )
            ),
            applicability_evidence=(
                ApplicabilityEvidence.from_dict(_mapping(evidence, "evidence"))
                if evidence is not None
                else None
            ),
            selected_premises=(
                SelectedPremiseSet.from_dict(_mapping(premises, "premises"))
                if premises is not None
                else None
            ),
            translations=tuple(
                TranslationReceipt.from_dict(_mapping(item, "translation"))
                for item in _sequence(
                    value.get("translations", ()), "translations"
                )
            ),
            reconstructions=tuple(
                ReconstructionReceipt.from_dict(
                    _mapping(item, "reconstruction")
                )
                for item in _sequence(
                    value.get("reconstructions", ()), "reconstructions"
                )
            ),
            coverage_gaps=tuple(
                CoverageGap.from_dict(_mapping(item, "coverage gap"))
                for item in _sequence(
                    value.get("coverage_gaps", ()), "coverage_gaps"
                )
            ),
            diagnostics=(
                DiagnosticReport.from_dict(_mapping(diagnostics, "diagnostics"))
                if diagnostics is not None
                else None
            ),
            adapter_id=value.get("adapter_id", ""),
            compiler_id=value.get("compiler_id", ""),
            ontology_id=value.get("ontology_id", ""),
            policy_id=value.get("policy_id", ""),
            producer_id=value.get("producer_id", ""),
            required_authority=authority or None,
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get(
                "schema_version", CONSTRAINT_ARTIFACT_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "ConstraintArtifact":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ConstraintValidationError(
                "constraint artifact must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "constraint artifact"))


__all__ = [
    "APPLICABILITY_EVIDENCE_INTERFACE",
    "APPLICABILITY_EVIDENCE_SCHEMA_VERSION",
    "CONSTRAINT_ARTIFACT_INTERFACE",
    "CONSTRAINT_ARTIFACT_SCHEMA_VERSION",
    "SELECTED_PREMISE_SET_INTERFACE",
    "SELECTED_PREMISE_SET_SCHEMA_VERSION",
    "ApplicabilityEvidence",
    "ApplicabilitySelector",
    "ApplicabilityStatus",
    "ConstraintArtifact",
    "ConstraintRole",
    "ConstraintStatement",
    "ConstraintValidationError",
    "CoverageGap",
    "CoverageGapKind",
    "NativeViewBinding",
    "PremiseSelectionMethod",
    "ReconstructionReceipt",
    "SelectedPremise",
    "SelectedPremiseSet",
    "TranslationReceipt",
    "WorldPolicy",
    "WorldPolicyKind",
    "forbid_silent_logic_concatenation",
    "reject_result_authority_substitution",
]
