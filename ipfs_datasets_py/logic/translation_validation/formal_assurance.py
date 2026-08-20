"""FACP-049: Translation receipts and deontic safety refinement.

Bind every translation among intent, legal, security, policy, solver, proof,
runtime decision, and explanation to an explicit ``TranslationReceipt``.
Enforce a deontic safety-refinement order in which:

* prohibitions remain prohibited;
* obligations remain or strengthen;
* permissions never broaden;
* unsupported or lossy constructs name their exact loss.

Only proved or solver-validated rewrite rules may enter proof-producing
e-graph extraction. Heuristic rewrites are recorded but never admitted into
proof extraction. Adversarial round trips (negation, exception, temporal
overlap, conflict, jurisdiction) always carry an explicit disposition.

This module owns the translation-validation surface for the formal-assurance
control plane. It reuses existing compiler/decompiler/e-graph interfaces by
opaque CID and interface identifiers — it does not introduce a second
compiler API. Cold import is hermetic: no network, installer, or process
mutation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Optional

# ---------------------------------------------------------------------------
# FACP evidence envelope
# ---------------------------------------------------------------------------

TASK_ID: Final[str] = "FACP-049"
GOAL_ID: Final[str] = "FACP-G630"
BUNDLE: Final[str] = "facp/translation/validation"
EVIDENCE_TRANSLATION_RECEIPT: Final[str] = "facp/translation-receipt@1"
EVIDENCE_DEONTIC_REFINEMENT: Final[str] = "facp/deontic-refinement@1"
EVIDENCE_REWRITE_TRUST: Final[str] = "facp/rewrite-trust@1"
INTERFACE: Final[str] = "FormalAssuranceTranslationReceipt@1"
SCHEMA: Final[str] = "facp/translation-receipt@1"
DEONTIC_REFINEMENT_SCHEMA: Final[str] = "facp/deontic-refinement@1"
REWRITE_TRUST_SCHEMA: Final[str] = "facp/rewrite-trust@1"
ROUNDTRIP_SCHEMA: Final[str] = "facp/adversarial-roundtrip@1"
ANALYZER_VERSION: Final[str] = "translation-validation/v1"

# Existing Datasets semantic / e-graph interfaces referenced by opaque ID.
CANONICAL_COMPILER_INTERFACE: Final[str] = "CanonicalStructuredTextCompiler@1"
CANONICAL_DECOMPILER_INTERFACE: Final[str] = "CanonicalStructuredTextDecompiler@1"
EGRAPH_REWRITE_INTERFACE: Final[str] = "ProofProducingEGraphExtraction@1"
LOGIC_TRANSLATION_RECEIPT_INTERFACE: Final[str] = "LogicTranslationReceipt@1"

UNSAFE_PROMOTION: Final[bool] = False
CLAIM_EQUIVALENCE_WITHOUT_CRITERIA: Final[bool] = False
ADMIT_HEURISTIC_INTO_PROOF_EXTRACTION: Final[bool] = False
SILENT_DROP_FORBIDDEN: Final[bool] = True

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,511}$")
_MAX_ITEMS: Final[int] = 4096


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TranslationValidationError(ValueError):
    """Malformed or contradictory translation-validation input."""


class SafetyRefinementError(TranslationValidationError):
    """Target is not a deontic safety refinement of source."""


class RewriteTrustError(TranslationValidationError):
    """Rewrite trust / proof-extraction admission failure."""


class RoundTripError(TranslationValidationError):
    """Adversarial round-trip evaluation failure."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PreservationClass(str, Enum):
    """Semantic relationship claimed between source and target."""

    EXACT = "exact"
    EQUISATISFIABLE = "equisatisfiable"
    SAFETY_REFINEMENT = "safety_refinement"
    CONSERVATIVE = "conservative"
    BOUNDED = "bounded"
    APPROXIMATE = "approximate"
    HEURISTIC = "heuristic"
    LOSSY = "lossy"


class EqualityCriteriaKind(str, Enum):
    """Criteria under which equivalence or refinement may be claimed."""

    EXACT = "exact"
    EQUISATISFIABLE = "equisatisfiable"
    OBSERVATIONAL = "observational"
    SAFETY_REFINEMENT = "safety_refinement"
    NONE = "none"


class LossHandling(str, Enum):
    """How an unsupported or lossy construct was handled."""

    REJECTED = "rejected"
    ABSTRACTED = "abstracted"
    APPROXIMATED = "approximated"
    OMITTED = "omitted"


class DeonticModality(str, Enum):
    """Closed deontic modality vocabulary for safety refinement."""

    PROHIBITION = "prohibition"
    OBLIGATION = "obligation"
    PERMISSION = "permission"


class RewriteTrustClass(str, Enum):
    """Trust class of a normalization rewrite rule."""

    PROVED = "proved"
    SOLVER_VALIDATED = "solver_validated"
    HEURISTIC = "heuristic"


class AdversarialCaseKind(str, Enum):
    """Adversarial round-trip case families required by TVC."""

    NEGATION = "negation"
    EXCEPTION = "exception"
    TEMPORAL_OVERLAP = "temporal_overlap"
    CONFLICT = "conflict"
    JURISDICTION = "jurisdiction"


class RoundTripDisposition(str, Enum):
    """Explicit disposition of an adversarial round trip — never silent."""

    PRESERVED = "preserved"
    NAMED_LOSS = "named_loss"
    REJECTED = "rejected"
    CONFLICT_RECORDED = "conflict_recorded"
    UNSUPPORTED = "unsupported"


class SafetyViolationKind(str, Enum):
    """Named reasons a target fails deontic safety refinement."""

    PROHIBITION_REMOVED = "prohibition_removed"
    PROHIBITION_WEAKENED_TO_PERMISSION = "prohibition_weakened_to_permission"
    PROHIBITION_WEAKENED_TO_OBLIGATION = "prohibition_weakened_to_obligation"
    OBLIGATION_REMOVED = "obligation_removed"
    OBLIGATION_WEAKENED_TO_PERMISSION = "obligation_weakened_to_permission"
    PERMISSION_BROADENED = "permission_broadened"
    CONDITION_BROADENED = "condition_broadened"
    EXCEPTION_DROPPED = "exception_dropped"
    TEMPORAL_SCOPE_BROADENED = "temporal_scope_broadened"
    JURISDICTION_BROADENED = "jurisdiction_broadened"
    SILENT_LOSS = "silent_loss"


# Modalities ranked by restrictiveness for strengthening checks.
# Higher = more restrictive (safer under refinement when replacing weaker).
_MODALITY_RESTRICTIVENESS: Final[Mapping[DeonticModality, int]] = MappingProxyType(
    {
        DeonticModality.PERMISSION: 0,
        DeonticModality.OBLIGATION: 1,
        DeonticModality.PROHIBITION: 2,
    }
)

_PROOF_EXTRACTION_TRUST: Final[frozenset[RewriteTrustClass]] = frozenset(
    {RewriteTrustClass.PROVED, RewriteTrustClass.SOLVER_VALIDATED}
)

_EQUIVALENCE_PRESERVATION: Final[frozenset[PreservationClass]] = frozenset(
    {
        PreservationClass.EXACT,
        PreservationClass.EQUISATISFIABLE,
    }
)


# ---------------------------------------------------------------------------
# Canonical helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        qualifier = "an empty or " if optional else "a "
        raise TranslationValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise TranslationValidationError(f"{label} must be a stable identifier")
    return result


def _optional_identifier(value: object, label: str) -> str:
    if value is None or value == "":
        return ""
    return _identifier(value, label)


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise TranslationValidationError(f"{label} must be one of {choices}") from error


def _strings(
    values: Sequence[str] | object,
    label: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationValidationError(f"{label} must be a sequence of strings")
    if len(values) > _MAX_ITEMS:
        raise TranslationValidationError(f"{label} exceeds item bound {_MAX_ITEMS}")
    validator = _identifier if identifiers else _text
    result = tuple(validator(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise TranslationValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationValidationError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _frozen_map(value: Mapping[str, Any] | None, label: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise TranslationValidationError(f"{label} must be an object with string keys")
    return MappingProxyType(dict(value))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_cid(namespace: str, payload: Any) -> str:
    """Return a deterministic content identity for ``namespace`` + payload."""

    envelope = {"namespace": _text(namespace, "namespace"), "payload": payload}
    digest = hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NamedLoss:
    """Exact named loss for an unsupported or lossy construct.

    Silent drops are forbidden: every lossy construct must carry a non-empty
    ``exact_loss`` that names what semantic content was discarded or altered.
    """

    loss_id: str
    construct_id: str
    construct_kind: str
    exact_loss: str
    handling: LossHandling
    source_ref_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "loss_id", _identifier(self.loss_id, "loss_id"))
        object.__setattr__(
            self, "construct_id", _identifier(self.construct_id, "construct_id")
        )
        object.__setattr__(
            self, "construct_kind", _identifier(self.construct_kind, "construct_kind")
        )
        exact = _text(self.exact_loss, "exact_loss")
        if not exact.strip():
            raise TranslationValidationError(
                "exact_loss must name the precise semantic content that was lost"
            )
        object.__setattr__(self, "exact_loss", exact)
        object.__setattr__(
            self, "handling", _enum(self.handling, LossHandling, "handling")
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _strings(self.source_ref_ids, "source_ref_ids", identifiers=True),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct_id": self.construct_id,
            "construct_kind": self.construct_kind,
            "exact_loss": self.exact_loss,
            "handling": self.handling.value,
            "loss_id": self.loss_id,
            "metadata": dict(self.metadata),
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NamedLoss":
        value = _mapping(value, "named loss")
        _reject_unknown(
            value,
            frozenset(
                {
                    "construct_id",
                    "construct_kind",
                    "exact_loss",
                    "handling",
                    "loss_id",
                    "metadata",
                    "source_ref_ids",
                }
            ),
            "named loss",
        )
        return cls(
            loss_id=value.get("loss_id", ""),
            construct_id=value.get("construct_id", ""),
            construct_kind=value.get("construct_kind", ""),
            exact_loss=value.get("exact_loss", ""),
            handling=value.get("handling", LossHandling.OMITTED.value),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            metadata=dict(value.get("metadata", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class EqualityCriteria:
    """Criteria under which a preservation/equivalence claim is meaningful."""

    criteria_id: str
    kind: EqualityCriteriaKind
    description: str = ""
    property_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "criteria_id", _identifier(self.criteria_id, "criteria_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, EqualityCriteriaKind, "kind")
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", optional=True),
        )
        object.__setattr__(
            self,
            "property_ids",
            _strings(self.property_ids, "property_ids", identifiers=True),
        )
        if self.kind is not EqualityCriteriaKind.NONE and not self.description:
            raise TranslationValidationError(
                "equality criteria other than 'none' require a description"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_id": self.criteria_id,
            "description": self.description,
            "kind": self.kind.value,
            "property_ids": list(self.property_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EqualityCriteria":
        value = _mapping(value, "equality criteria")
        _reject_unknown(
            value,
            frozenset({"criteria_id", "description", "kind", "property_ids"}),
            "equality criteria",
        )
        return cls(
            criteria_id=value.get("criteria_id", ""),
            kind=value.get("kind", EqualityCriteriaKind.NONE.value),
            description=value.get("description", ""),
            property_ids=tuple(value.get("property_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class DeonticNorm:
    """One deontic norm used for safety-refinement comparison."""

    norm_id: str
    modality: DeonticModality
    action: str
    actors: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal_scope: str = ""
    jurisdiction: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "norm_id", _identifier(self.norm_id, "norm_id"))
        object.__setattr__(
            self, "modality", _enum(self.modality, DeonticModality, "modality")
        )
        object.__setattr__(self, "action", _identifier(self.action, "action"))
        object.__setattr__(
            self, "actors", _strings(self.actors, "actors", identifiers=True)
        )
        object.__setattr__(
            self,
            "conditions",
            _strings(self.conditions, "conditions", identifiers=True),
        )
        object.__setattr__(
            self,
            "exceptions",
            _strings(self.exceptions, "exceptions", identifiers=True),
        )
        object.__setattr__(
            self,
            "temporal_scope",
            _optional_identifier(self.temporal_scope, "temporal_scope"),
        )
        object.__setattr__(
            self,
            "jurisdiction",
            _optional_identifier(self.jurisdiction, "jurisdiction"),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))

    @property
    def action_key(self) -> str:
        actors = ",".join(self.actors) if self.actors else "*"
        return f"{self.action}|{actors}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "actors": list(self.actors),
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "jurisdiction": self.jurisdiction,
            "metadata": dict(self.metadata),
            "modality": self.modality.value,
            "norm_id": self.norm_id,
            "temporal_scope": self.temporal_scope,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeonticNorm":
        value = _mapping(value, "deontic norm")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action",
                    "actors",
                    "conditions",
                    "exceptions",
                    "jurisdiction",
                    "metadata",
                    "modality",
                    "norm_id",
                    "temporal_scope",
                }
            ),
            "deontic norm",
        )
        return cls(
            norm_id=value.get("norm_id", ""),
            modality=value.get("modality", DeonticModality.PERMISSION.value),
            action=value.get("action", ""),
            actors=tuple(value.get("actors", ())),
            conditions=tuple(value.get("conditions", ())),
            exceptions=tuple(value.get("exceptions", ())),
            temporal_scope=value.get("temporal_scope", ""),
            jurisdiction=value.get("jurisdiction", ""),
            metadata=dict(value.get("metadata", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class SafetyViolation:
    """One named deontic safety-refinement violation."""

    kind: SafetyViolationKind
    source_norm_id: str
    target_norm_id: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, SafetyViolationKind, "kind")
        )
        object.__setattr__(
            self,
            "source_norm_id",
            _identifier(self.source_norm_id, "source_norm_id"),
        )
        object.__setattr__(
            self,
            "target_norm_id",
            _optional_identifier(self.target_norm_id, "target_norm_id"),
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "detail", optional=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "kind": self.kind.value,
            "source_norm_id": self.source_norm_id,
            "target_norm_id": self.target_norm_id,
        }


@dataclass(frozen=True, slots=True)
class SafetyRefinementResult:
    """Outcome of comparing source and target under deontic safety refinement."""

    is_safe: bool
    violations: tuple[SafetyViolation, ...] = ()
    schema_version: str = DEONTIC_REFINEMENT_SCHEMA
    evidence_id: str = EVIDENCE_DEONTIC_REFINEMENT
    result_cid: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.is_safe, bool):
            raise TranslationValidationError("is_safe must be a bool")
        violations = tuple(self.violations)
        if self.is_safe and violations:
            raise TranslationValidationError(
                "safe refinement results cannot carry violations"
            )
        if not self.is_safe and not violations:
            raise TranslationValidationError(
                "unsafe refinement results require at least one named violation"
            )
        object.__setattr__(self, "violations", violations)
        if self.schema_version != DEONTIC_REFINEMENT_SCHEMA:
            raise TranslationValidationError(
                f"unsupported deontic refinement schema {self.schema_version!r}"
            )
        payload = {
            "evidence_id": self.evidence_id,
            "is_safe": self.is_safe,
            "schema_version": self.schema_version,
            "violations": [item.to_dict() for item in self.violations],
        }
        computed = content_cid("facp.deontic-refinement", payload)
        if self.result_cid and self.result_cid != computed:
            raise TranslationValidationError(
                "result_cid does not match canonical refinement content"
            )
        object.__setattr__(self, "result_cid", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "is_safe": self.is_safe,
            "result_cid": self.result_cid,
            "schema_version": self.schema_version,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass(frozen=True, slots=True)
class RewriteRule:
    """One normalization rewrite with an explicit trust class."""

    rule_id: str
    trust_class: RewriteTrustClass
    left_pattern: str
    right_pattern: str
    proof_artifact_cid: str = ""
    solver_validation_cid: str = ""
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(
            self,
            "trust_class",
            _enum(self.trust_class, RewriteTrustClass, "trust_class"),
        )
        object.__setattr__(
            self, "left_pattern", _text(self.left_pattern, "left_pattern")
        )
        object.__setattr__(
            self, "right_pattern", _text(self.right_pattern, "right_pattern")
        )
        object.__setattr__(
            self,
            "proof_artifact_cid",
            _optional_identifier(self.proof_artifact_cid, "proof_artifact_cid"),
        )
        object.__setattr__(
            self,
            "solver_validation_cid",
            _optional_identifier(
                self.solver_validation_cid, "solver_validation_cid"
            ),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", optional=True),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        if (
            self.trust_class is RewriteTrustClass.PROVED
            and not self.proof_artifact_cid
        ):
            raise RewriteTrustError(
                "proved rewrites require proof_artifact_cid"
            )
        if (
            self.trust_class is RewriteTrustClass.SOLVER_VALIDATED
            and not self.solver_validation_cid
        ):
            raise RewriteTrustError(
                "solver-validated rewrites require solver_validation_cid"
            )
        if (
            self.trust_class is RewriteTrustClass.HEURISTIC
            and (self.proof_artifact_cid or self.solver_validation_cid)
        ):
            raise RewriteTrustError(
                "heuristic rewrites cannot carry proof or solver validation CIDs"
            )

    @property
    def admitted_for_proof_extraction(self) -> bool:
        return self.trust_class in _PROOF_EXTRACTION_TRUST

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "left_pattern": self.left_pattern,
            "metadata": dict(self.metadata),
            "proof_artifact_cid": self.proof_artifact_cid,
            "right_pattern": self.right_pattern,
            "rule_id": self.rule_id,
            "solver_validation_cid": self.solver_validation_cid,
            "trust_class": self.trust_class.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RewriteRule":
        value = _mapping(value, "rewrite rule")
        _reject_unknown(
            value,
            frozenset(
                {
                    "description",
                    "left_pattern",
                    "metadata",
                    "proof_artifact_cid",
                    "right_pattern",
                    "rule_id",
                    "solver_validation_cid",
                    "trust_class",
                }
            ),
            "rewrite rule",
        )
        return cls(
            rule_id=value.get("rule_id", ""),
            trust_class=value.get("trust_class", RewriteTrustClass.HEURISTIC.value),
            left_pattern=value.get("left_pattern", ""),
            right_pattern=value.get("right_pattern", ""),
            proof_artifact_cid=value.get("proof_artifact_cid", ""),
            solver_validation_cid=value.get("solver_validation_cid", ""),
            description=value.get("description", ""),
            metadata=dict(value.get("metadata", {}) or {}),
        )


@dataclass(frozen=True, slots=True)
class TrustedRewriteRegistry:
    """Registry distinguishing proved/solver-validated rewrites from heuristics.

    Only :attr:`RewriteTrustClass.PROVED` and
    :attr:`RewriteTrustClass.SOLVER_VALIDATED` rules may enter proof-producing
    e-graph extraction. Heuristic rules may be recorded for advisory use but
    are never admitted into proof extraction.
    """

    registry_id: str
    rules: tuple[RewriteRule, ...] = ()
    egraph_interface: str = EGRAPH_REWRITE_INTERFACE
    schema_version: str = REWRITE_TRUST_SCHEMA
    evidence_id: str = EVIDENCE_REWRITE_TRUST
    registry_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "registry_id", _identifier(self.registry_id, "registry_id")
        )
        object.__setattr__(
            self,
            "egraph_interface",
            _identifier(self.egraph_interface, "egraph_interface"),
        )
        rules = tuple(self.rules)
        if len(rules) > _MAX_ITEMS:
            raise RewriteTrustError(f"rules exceed item bound {_MAX_ITEMS}")
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise RewriteTrustError("rules must not contain duplicate rule_id values")
        object.__setattr__(self, "rules", rules)
        if self.schema_version != REWRITE_TRUST_SCHEMA:
            raise RewriteTrustError(
                f"unsupported rewrite trust schema {self.schema_version!r}"
            )
        payload = {
            "egraph_interface": self.egraph_interface,
            "evidence_id": self.evidence_id,
            "registry_id": self.registry_id,
            "rules": [rule.to_dict() for rule in self.rules],
            "schema_version": self.schema_version,
        }
        computed = content_cid("facp.rewrite-trust", payload)
        if self.registry_cid and self.registry_cid != computed:
            raise RewriteTrustError(
                "registry_cid does not match canonical registry content"
            )
        object.__setattr__(self, "registry_cid", computed)

    def rule(self, rule_id: str) -> RewriteRule:
        for item in self.rules:
            if item.rule_id == rule_id:
                return item
        raise RewriteTrustError(f"unknown rewrite rule {rule_id!r}")

    def proof_extraction_rules(self) -> tuple[RewriteRule, ...]:
        return tuple(
            rule for rule in self.rules if rule.admitted_for_proof_extraction
        )

    def heuristic_rules(self) -> tuple[RewriteRule, ...]:
        return tuple(
            rule
            for rule in self.rules
            if rule.trust_class is RewriteTrustClass.HEURISTIC
        )

    def is_admitted_for_proof_extraction(self, rule_id: str) -> bool:
        return self.rule(rule_id).admitted_for_proof_extraction

    def require_proof_extraction_admission(self, rule_id: str) -> RewriteRule:
        rule = self.rule(rule_id)
        if not rule.admitted_for_proof_extraction:
            raise RewriteTrustError(
                f"heuristic rewrite {rule_id!r} is not admitted into "
                "proof-producing e-graph extraction"
            )
        return rule

    def with_rule(self, rule: RewriteRule) -> "TrustedRewriteRegistry":
        if any(existing.rule_id == rule.rule_id for existing in self.rules):
            raise RewriteTrustError(f"rewrite rule {rule.rule_id!r} already registered")
        return TrustedRewriteRegistry(
            registry_id=self.registry_id,
            rules=self.rules + (rule,),
            egraph_interface=self.egraph_interface,
            schema_version=self.schema_version,
            evidence_id=self.evidence_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "egraph_interface": self.egraph_interface,
            "evidence_id": self.evidence_id,
            "registry_cid": self.registry_cid,
            "registry_id": self.registry_id,
            "rules": [rule.to_dict() for rule in self.rules],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustedRewriteRegistry":
        value = _mapping(value, "trusted rewrite registry")
        _reject_unknown(
            value,
            frozenset(
                {
                    "egraph_interface",
                    "evidence_id",
                    "registry_cid",
                    "registry_id",
                    "rules",
                    "schema_version",
                }
            ),
            "trusted rewrite registry",
        )
        rules_raw = value.get("rules", ())
        if isinstance(rules_raw, (str, bytes, bytearray)) or not isinstance(
            rules_raw, Sequence
        ):
            raise RewriteTrustError("rules must be a sequence")
        return cls(
            registry_id=value.get("registry_id", ""),
            rules=tuple(
                item
                if isinstance(item, RewriteRule)
                else RewriteRule.from_dict(item)
                for item in rules_raw
            ),
            egraph_interface=value.get(
                "egraph_interface", EGRAPH_REWRITE_INTERFACE
            ),
            schema_version=value.get("schema_version", REWRITE_TRUST_SCHEMA),
            evidence_id=value.get("evidence_id", EVIDENCE_REWRITE_TRUST),
            registry_cid=value.get("registry_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class AdversarialRoundTripResult:
    """Explicit disposition for one adversarial round-trip case."""

    case_id: str
    case_kind: AdversarialCaseKind
    disposition: RoundTripDisposition
    detail: str
    named_loss_ids: tuple[str, ...] = ()
    source_cid: str = ""
    target_cid: str = ""
    recompilation_cid: str = ""
    schema_version: str = ROUNDTRIP_SCHEMA
    result_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(
            self,
            "case_kind",
            _enum(self.case_kind, AdversarialCaseKind, "case_kind"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, RoundTripDisposition, "disposition"),
        )
        object.__setattr__(self, "detail", _text(self.detail, "detail"))
        object.__setattr__(
            self,
            "named_loss_ids",
            _strings(self.named_loss_ids, "named_loss_ids", identifiers=True),
        )
        object.__setattr__(
            self, "source_cid", _optional_identifier(self.source_cid, "source_cid")
        )
        object.__setattr__(
            self, "target_cid", _optional_identifier(self.target_cid, "target_cid")
        )
        object.__setattr__(
            self,
            "recompilation_cid",
            _optional_identifier(self.recompilation_cid, "recompilation_cid"),
        )
        if self.schema_version != ROUNDTRIP_SCHEMA:
            raise RoundTripError(
                f"unsupported round-trip schema {self.schema_version!r}"
            )
        if (
            self.disposition is RoundTripDisposition.NAMED_LOSS
            and not self.named_loss_ids
        ):
            raise RoundTripError(
                "named_loss disposition requires at least one named_loss_id"
            )
        if self.disposition is RoundTripDisposition.PRESERVED and self.named_loss_ids:
            raise RoundTripError(
                "preserved disposition cannot reference named losses"
            )
        payload = {
            "case_id": self.case_id,
            "case_kind": self.case_kind.value,
            "detail": self.detail,
            "disposition": self.disposition.value,
            "named_loss_ids": list(self.named_loss_ids),
            "recompilation_cid": self.recompilation_cid,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "target_cid": self.target_cid,
        }
        computed = content_cid("facp.adversarial-roundtrip", payload)
        if self.result_cid and self.result_cid != computed:
            raise RoundTripError(
                "result_cid does not match canonical round-trip content"
            )
        object.__setattr__(self, "result_cid", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_kind": self.case_kind.value,
            "detail": self.detail,
            "disposition": self.disposition.value,
            "named_loss_ids": list(self.named_loss_ids),
            "recompilation_cid": self.recompilation_cid,
            "result_cid": self.result_cid,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "target_cid": self.target_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdversarialRoundTripResult":
        value = _mapping(value, "adversarial round trip")
        _reject_unknown(
            value,
            frozenset(
                {
                    "case_id",
                    "case_kind",
                    "detail",
                    "disposition",
                    "named_loss_ids",
                    "recompilation_cid",
                    "result_cid",
                    "schema_version",
                    "source_cid",
                    "target_cid",
                }
            ),
            "adversarial round trip",
        )
        return cls(
            case_id=value.get("case_id", ""),
            case_kind=value.get("case_kind", AdversarialCaseKind.NEGATION.value),
            disposition=value.get(
                "disposition", RoundTripDisposition.UNSUPPORTED.value
            ),
            detail=value.get("detail", ""),
            named_loss_ids=tuple(value.get("named_loss_ids", ())),
            source_cid=value.get("source_cid", ""),
            target_cid=value.get("target_cid", ""),
            recompilation_cid=value.get("recompilation_cid", ""),
            schema_version=value.get("schema_version", ROUNDTRIP_SCHEMA),
            result_cid=value.get("result_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class TranslationReceipt:
    """Formal-assurance translation receipt with named loss and safety binding.

    Equivalence is never claimed without :class:`EqualityCriteria`. Lossy or
    unsupported constructs must each appear as a :class:`NamedLoss` with an
    exact loss description. Deontic safety refinement of source→target norms is
    recorded explicitly.
    """

    source_cid: str
    target_cid: str
    compiler_cid: str
    source_schema: str
    target_schema: str
    preservation_class: PreservationClass
    equality_criteria: EqualityCriteria
    assumptions: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    named_losses: tuple[NamedLoss, ...] = ()
    source_norms: tuple[DeonticNorm, ...] = ()
    target_norms: tuple[DeonticNorm, ...] = ()
    safety_refinement: Optional[SafetyRefinementResult] = None
    rewrite_registry_cid: str = ""
    adversarial_results: tuple[AdversarialRoundTripResult, ...] = ()
    decompiler_cid: str = ""
    recompilation_cid: str = ""
    comparison_cid: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA
    evidence_id: str = EVIDENCE_TRANSLATION_RECEIPT
    interface: str = INTERFACE
    receipt_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_cid", _identifier(self.source_cid, "source_cid")
        )
        object.__setattr__(
            self, "target_cid", _identifier(self.target_cid, "target_cid")
        )
        if self.source_cid == self.target_cid:
            raise TranslationValidationError(
                "source_cid and target_cid must differ"
            )
        object.__setattr__(
            self, "compiler_cid", _identifier(self.compiler_cid, "compiler_cid")
        )
        object.__setattr__(
            self, "source_schema", _identifier(self.source_schema, "source_schema")
        )
        object.__setattr__(
            self, "target_schema", _identifier(self.target_schema, "target_schema")
        )
        object.__setattr__(
            self,
            "preservation_class",
            _enum(self.preservation_class, PreservationClass, "preservation_class"),
        )
        criteria = self.equality_criteria
        if isinstance(criteria, Mapping):
            criteria = EqualityCriteria.from_dict(criteria)
        if not isinstance(criteria, EqualityCriteria):
            raise TranslationValidationError(
                "equality_criteria must be an EqualityCriteria"
            )
        object.__setattr__(self, "equality_criteria", criteria)
        object.__setattr__(
            self, "assumptions", _strings(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self,
            "obligations",
            _strings(self.obligations, "obligations", identifiers=True),
        )

        losses = _coerce_records(self.named_losses, NamedLoss, "named_losses")
        object.__setattr__(self, "named_losses", losses)
        source_norms = _coerce_records(
            self.source_norms, DeonticNorm, "source_norms"
        )
        target_norms = _coerce_records(
            self.target_norms, DeonticNorm, "target_norms"
        )
        object.__setattr__(self, "source_norms", source_norms)
        object.__setattr__(self, "target_norms", target_norms)

        safety = self.safety_refinement
        if isinstance(safety, Mapping):
            safety = SafetyRefinementResult(
                is_safe=bool(safety.get("is_safe", False)),
                violations=tuple(
                    item
                    if isinstance(item, SafetyViolation)
                    else SafetyViolation(
                        kind=item["kind"],
                        source_norm_id=item["source_norm_id"],
                        target_norm_id=item.get("target_norm_id", ""),
                        detail=item.get("detail", ""),
                    )
                    for item in safety.get("violations", ())
                ),
                schema_version=safety.get(
                    "schema_version", DEONTIC_REFINEMENT_SCHEMA
                ),
                evidence_id=safety.get(
                    "evidence_id", EVIDENCE_DEONTIC_REFINEMENT
                ),
                result_cid=safety.get("result_cid", ""),
            )
        if safety is not None and not isinstance(safety, SafetyRefinementResult):
            raise TranslationValidationError(
                "safety_refinement must be a SafetyRefinementResult or None"
            )
        object.__setattr__(self, "safety_refinement", safety)

        object.__setattr__(
            self,
            "rewrite_registry_cid",
            _optional_identifier(
                self.rewrite_registry_cid, "rewrite_registry_cid"
            ),
        )
        adversarial = _coerce_records(
            self.adversarial_results,
            AdversarialRoundTripResult,
            "adversarial_results",
        )
        object.__setattr__(self, "adversarial_results", adversarial)
        object.__setattr__(
            self,
            "decompiler_cid",
            _optional_identifier(self.decompiler_cid, "decompiler_cid"),
        )
        object.__setattr__(
            self,
            "recompilation_cid",
            _optional_identifier(self.recompilation_cid, "recompilation_cid"),
        )
        object.__setattr__(
            self,
            "comparison_cid",
            _optional_identifier(self.comparison_cid, "comparison_cid"),
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(
            self, "interface", _identifier(self.interface, "interface")
        )
        if self.interface != INTERFACE:
            raise TranslationValidationError(
                f"unsupported translation receipt interface {self.interface!r}"
            )
        if self.schema_version != SCHEMA:
            raise TranslationValidationError(
                f"unsupported translation receipt schema {self.schema_version!r}"
            )
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )

        self._validate_semantics()
        computed = content_cid("facp.translation-receipt", self.semantic_dict())
        if self.receipt_cid and self.receipt_cid != computed:
            raise TranslationValidationError(
                "receipt_cid does not match canonical receipt content"
            )
        object.__setattr__(self, "receipt_cid", computed)

    def _validate_semantics(self) -> None:
        # Equivalence never claimed without criteria.
        if self.preservation_class in _EQUIVALENCE_PRESERVATION:
            if self.equality_criteria.kind is EqualityCriteriaKind.NONE:
                raise TranslationValidationError(
                    "equivalence preservation requires equality criteria; "
                    "cannot claim equivalence without criteria"
                )
            if self.equality_criteria.kind.value != self.preservation_class.value:
                raise TranslationValidationError(
                    "equality criteria kind must match equivalence preservation class"
                )

        if self.preservation_class is PreservationClass.SAFETY_REFINEMENT:
            if (
                self.equality_criteria.kind
                is not EqualityCriteriaKind.SAFETY_REFINEMENT
            ):
                raise TranslationValidationError(
                    "safety_refinement preservation requires matching equality criteria"
                )
            if self.safety_refinement is None:
                raise TranslationValidationError(
                    "safety_refinement preservation requires a safety_refinement result"
                )
            if not self.safety_refinement.is_safe:
                raise TranslationValidationError(
                    "cannot claim safety_refinement preservation when refinement is unsafe"
                )

        if self.preservation_class is PreservationClass.LOSSY and not self.named_losses:
            raise TranslationValidationError(
                "lossy preservation requires at least one NamedLoss with exact_loss"
            )

        # Silent drop forbidden: lossy/omitted constructs must name exact loss.
        loss_construct_ids = {item.construct_id for item in self.named_losses}
        for loss in self.named_losses:
            if not loss.exact_loss:
                raise TranslationValidationError(
                    f"named loss {loss.loss_id} missing exact_loss"
                )
        del loss_construct_ids

        if self.source_norms or self.target_norms:
            if self.safety_refinement is None:
                raise TranslationValidationError(
                    "deontic norms require an explicit safety_refinement result"
                )

        # Adversarial results must always carry explicit dispositions (enforced
        # by AdversarialRoundTripResult); additionally every required case kind
        # that appears must be unique by case_id.
        case_ids = [item.case_id for item in self.adversarial_results]
        if len(case_ids) != len(set(case_ids)):
            raise TranslationValidationError(
                "adversarial_results must not contain duplicate case_id values"
            )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "adversarial_results": [
                item.to_dict() for item in self.adversarial_results
            ],
            "assumptions": list(self.assumptions),
            "comparison_cid": self.comparison_cid,
            "compiler_cid": self.compiler_cid,
            "decompiler_cid": self.decompiler_cid,
            "equality_criteria": self.equality_criteria.to_dict(),
            "evidence_id": self.evidence_id,
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "named_losses": [item.to_dict() for item in self.named_losses],
            "obligations": list(self.obligations),
            "preservation_class": self.preservation_class.value,
            "recompilation_cid": self.recompilation_cid,
            "rewrite_registry_cid": self.rewrite_registry_cid,
            "safety_refinement": (
                None
                if self.safety_refinement is None
                else self.safety_refinement.to_dict()
            ),
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "source_norms": [item.to_dict() for item in self.source_norms],
            "source_schema": self.source_schema,
            "target_cid": self.target_cid,
            "target_norms": [item.to_dict() for item in self.target_norms],
            "target_schema": self.target_schema,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["receipt_cid"] = self.receipt_cid
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationReceipt":
        value = _mapping(value, "translation receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adversarial_results",
                    "assumptions",
                    "comparison_cid",
                    "compiler_cid",
                    "decompiler_cid",
                    "equality_criteria",
                    "evidence_id",
                    "interface",
                    "metadata",
                    "named_losses",
                    "obligations",
                    "preservation_class",
                    "receipt_cid",
                    "recompilation_cid",
                    "rewrite_registry_cid",
                    "safety_refinement",
                    "schema_version",
                    "source_cid",
                    "source_norms",
                    "source_schema",
                    "target_cid",
                    "target_norms",
                    "target_schema",
                }
            ),
            "translation receipt",
        )
        safety_raw = value.get("safety_refinement")
        safety: Optional[SafetyRefinementResult]
        if safety_raw is None:
            safety = None
        elif isinstance(safety_raw, SafetyRefinementResult):
            safety = safety_raw
        else:
            safety_map = _mapping(safety_raw, "safety_refinement")
            safety = SafetyRefinementResult(
                is_safe=bool(safety_map.get("is_safe", False)),
                violations=tuple(
                    SafetyViolation(
                        kind=item["kind"],
                        source_norm_id=item["source_norm_id"],
                        target_norm_id=item.get("target_norm_id", ""),
                        detail=item.get("detail", ""),
                    )
                    for item in safety_map.get("violations", ())
                ),
                schema_version=safety_map.get(
                    "schema_version", DEONTIC_REFINEMENT_SCHEMA
                ),
                evidence_id=safety_map.get(
                    "evidence_id", EVIDENCE_DEONTIC_REFINEMENT
                ),
                result_cid=safety_map.get("result_cid", ""),
            )
        return cls(
            source_cid=value.get("source_cid", ""),
            target_cid=value.get("target_cid", ""),
            compiler_cid=value.get("compiler_cid", ""),
            source_schema=value.get("source_schema", ""),
            target_schema=value.get("target_schema", ""),
            preservation_class=value.get(
                "preservation_class", PreservationClass.HEURISTIC.value
            ),
            equality_criteria=value.get("equality_criteria", {}),  # type: ignore[arg-type]
            assumptions=tuple(value.get("assumptions", ())),
            obligations=tuple(value.get("obligations", ())),
            named_losses=tuple(value.get("named_losses", ())),
            source_norms=tuple(value.get("source_norms", ())),
            target_norms=tuple(value.get("target_norms", ())),
            safety_refinement=safety,
            rewrite_registry_cid=value.get("rewrite_registry_cid", ""),
            adversarial_results=tuple(value.get("adversarial_results", ())),
            decompiler_cid=value.get("decompiler_cid", ""),
            recompilation_cid=value.get("recompilation_cid", ""),
            comparison_cid=value.get("comparison_cid", ""),
            metadata=dict(value.get("metadata", {}) or {}),
            schema_version=value.get("schema_version", SCHEMA),
            evidence_id=value.get("evidence_id", EVIDENCE_TRANSLATION_RECEIPT),
            interface=value.get("interface", INTERFACE),
            receipt_cid=value.get("receipt_cid", ""),
        )


def _coerce_records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationValidationError(f"{label} must be a sequence")
    if len(values) > _MAX_ITEMS:
        raise TranslationValidationError(f"{label} exceeds item bound {_MAX_ITEMS}")
    result: list[Any] = []
    for item in values:
        if isinstance(item, record_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(record_type.from_dict(item))
        else:
            raise TranslationValidationError(
                f"{label} items must be {record_type.__name__} values"
            )
    ids_attr = {
        NamedLoss: "loss_id",
        DeonticNorm: "norm_id",
        AdversarialRoundTripResult: "case_id",
        RewriteRule: "rule_id",
    }.get(record_type)
    if ids_attr is not None:
        identities = [getattr(item, ids_attr) for item in result]
        if len(identities) != len(set(identities)):
            raise TranslationValidationError(
                f"{label} must not contain duplicate {ids_attr} values"
            )
    return tuple(result)


# ---------------------------------------------------------------------------
# Deontic safety refinement
# ---------------------------------------------------------------------------


def _index_norms(
    norms: Sequence[DeonticNorm],
) -> dict[str, list[DeonticNorm]]:
    indexed: dict[str, list[DeonticNorm]] = {}
    for norm in norms:
        indexed.setdefault(norm.action_key, []).append(norm)
    return indexed


def _permission_scope_broader(source: DeonticNorm, target: DeonticNorm) -> Optional[SafetyViolationKind]:
    """Return a violation kind if target permission is broader than source."""

    # Fewer conditions ⇒ weaker guard ⇒ broader permission.
    source_conditions = set(source.conditions)
    target_conditions = set(target.conditions)
    if not target_conditions.issuperset(source_conditions) and target_conditions != source_conditions:
        if not source_conditions.issubset(target_conditions):
            # Target dropped a guarding condition.
            if source_conditions - target_conditions:
                return SafetyViolationKind.CONDITION_BROADENED

    # More exceptions ⇒ more carve-outs ⇒ broader permission / weaker prohibition.
    source_exceptions = set(source.exceptions)
    target_exceptions = set(target.exceptions)
    if target_exceptions - source_exceptions:
        return SafetyViolationKind.EXCEPTION_DROPPED

    # Empty temporal/jurisdiction means unrestricted (broader).
    if source.temporal_scope and not target.temporal_scope:
        return SafetyViolationKind.TEMPORAL_SCOPE_BROADENED
    if (
        source.temporal_scope
        and target.temporal_scope
        and source.temporal_scope != target.temporal_scope
        and target.temporal_scope == "unbounded"
    ):
        return SafetyViolationKind.TEMPORAL_SCOPE_BROADENED

    if source.jurisdiction and not target.jurisdiction:
        return SafetyViolationKind.JURISDICTION_BROADENED
    if (
        source.jurisdiction
        and target.jurisdiction
        and source.jurisdiction != target.jurisdiction
        and target.jurisdiction in {"any", "unbounded", "global"}
    ):
        return SafetyViolationKind.JURISDICTION_BROADENED

    return None


def check_deontic_safety_refinement(
    source_norms: Sequence[DeonticNorm],
    target_norms: Sequence[DeonticNorm],
) -> SafetyRefinementResult:
    """Return whether ``target_norms`` safely refine ``source_norms``.

    Safety order:

    * every source prohibition remains a prohibition on the same action;
    * every source obligation remains an obligation (or strengthens to
      prohibition is *not* treated as obligation-preserving — obligations must
      remain obligations);
    * target permissions never broaden source permissions (no new actions,
      no weaker conditions/exceptions/time/jurisdiction).
    """

    source_norms = _coerce_records(source_norms, DeonticNorm, "source_norms")
    target_norms = _coerce_records(target_norms, DeonticNorm, "target_norms")
    target_index = _index_norms(target_norms)
    source_index = _index_norms(source_norms)
    violations: list[SafetyViolation] = []

    for source in source_norms:
        candidates = target_index.get(source.action_key, [])
        if source.modality is DeonticModality.PROHIBITION:
            matching = [
                item
                for item in candidates
                if item.modality is DeonticModality.PROHIBITION
            ]
            if not matching:
                weakened = [
                    item
                    for item in candidates
                    if item.modality is DeonticModality.PERMISSION
                ]
                obligated = [
                    item
                    for item in candidates
                    if item.modality is DeonticModality.OBLIGATION
                ]
                if weakened:
                    violations.append(
                        SafetyViolation(
                            kind=SafetyViolationKind.PROHIBITION_WEAKENED_TO_PERMISSION,
                            source_norm_id=source.norm_id,
                            target_norm_id=weakened[0].norm_id,
                            detail=(
                                f"prohibition on {source.action} broadened to permission"
                            ),
                        )
                    )
                elif obligated:
                    violations.append(
                        SafetyViolation(
                            kind=SafetyViolationKind.PROHIBITION_WEAKENED_TO_OBLIGATION,
                            source_norm_id=source.norm_id,
                            target_norm_id=obligated[0].norm_id,
                            detail=(
                                f"prohibition on {source.action} replaced by obligation"
                            ),
                        )
                    )
                else:
                    violations.append(
                        SafetyViolation(
                            kind=SafetyViolationKind.PROHIBITION_REMOVED,
                            source_norm_id=source.norm_id,
                            detail=f"prohibition on {source.action} removed",
                        )
                    )
            else:
                for target in matching:
                    broader = _permission_scope_broader(source, target)
                    # For prohibitions, more exceptions weakens the prohibition.
                    if broader is SafetyViolationKind.EXCEPTION_DROPPED:
                        violations.append(
                            SafetyViolation(
                                kind=SafetyViolationKind.EXCEPTION_DROPPED,
                                source_norm_id=source.norm_id,
                                target_norm_id=target.norm_id,
                                detail=(
                                    f"prohibition on {source.action} gained exceptions"
                                ),
                            )
                        )

        elif source.modality is DeonticModality.OBLIGATION:
            matching = [
                item
                for item in candidates
                if item.modality is DeonticModality.OBLIGATION
            ]
            if not matching:
                permitted = [
                    item
                    for item in candidates
                    if item.modality is DeonticModality.PERMISSION
                ]
                if permitted:
                    violations.append(
                        SafetyViolation(
                            kind=SafetyViolationKind.OBLIGATION_WEAKENED_TO_PERMISSION,
                            source_norm_id=source.norm_id,
                            target_norm_id=permitted[0].norm_id,
                            detail=(
                                f"obligation on {source.action} weakened to permission"
                            ),
                        )
                    )
                else:
                    violations.append(
                        SafetyViolation(
                            kind=SafetyViolationKind.OBLIGATION_REMOVED,
                            source_norm_id=source.norm_id,
                            detail=f"obligation on {source.action} removed",
                        )
                    )

        elif source.modality is DeonticModality.PERMISSION:
            matching = [
                item
                for item in candidates
                if item.modality is DeonticModality.PERMISSION
            ]
            for target in matching:
                broader = _permission_scope_broader(source, target)
                if broader is not None:
                    violations.append(
                        SafetyViolation(
                            kind=broader,
                            source_norm_id=source.norm_id,
                            target_norm_id=target.norm_id,
                            detail=(
                                f"permission on {source.action} broadened "
                                f"({broader.value})"
                            ),
                        )
                    )

    # Target must not introduce permissions absent from source (broadening).
    for target in target_norms:
        if target.modality is not DeonticModality.PERMISSION:
            continue
        source_candidates = source_index.get(target.action_key, [])
        source_permissions = [
            item
            for item in source_candidates
            if item.modality is DeonticModality.PERMISSION
        ]
        source_stronger = [
            item
            for item in source_candidates
            if _MODALITY_RESTRICTIVENESS[item.modality]
            > _MODALITY_RESTRICTIVENESS[DeonticModality.PERMISSION]
        ]
        # Introducing a permission where source had prohibition is broadening.
        source_prohibitions = [
            item
            for item in source_candidates
            if item.modality is DeonticModality.PROHIBITION
        ]
        if source_prohibitions:
            violations.append(
                SafetyViolation(
                    kind=SafetyViolationKind.PROHIBITION_WEAKENED_TO_PERMISSION,
                    source_norm_id=source_prohibitions[0].norm_id,
                    target_norm_id=target.norm_id,
                    detail=(
                        f"target permits {target.action} which source prohibits"
                    ),
                )
            )
            continue
        if not source_permissions and not source_stronger:
            # Brand-new permission not present in source.
            violations.append(
                SafetyViolation(
                    kind=SafetyViolationKind.PERMISSION_BROADENED,
                    source_norm_id=target.norm_id,
                    target_norm_id=target.norm_id,
                    detail=(
                        f"target introduces permission on {target.action} "
                        "absent from source"
                    ),
                )
            )

    if violations:
        # Deduplicate by (kind, source, target).
        seen: set[tuple[str, str, str]] = set()
        unique: list[SafetyViolation] = []
        for item in violations:
            key = (item.kind.value, item.source_norm_id, item.target_norm_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return SafetyRefinementResult(is_safe=False, violations=tuple(unique))
    return SafetyRefinementResult(is_safe=True, violations=())


def require_deontic_safety_refinement(
    source_norms: Sequence[DeonticNorm],
    target_norms: Sequence[DeonticNorm],
) -> SafetyRefinementResult:
    """Fail closed unless target is a deontic safety refinement of source."""

    result = check_deontic_safety_refinement(source_norms, target_norms)
    if not result.is_safe:
        kinds = ", ".join(sorted({item.kind.value for item in result.violations}))
        raise SafetyRefinementError(
            f"target is not a deontic safety refinement of source: {kinds}"
        )
    return result


# ---------------------------------------------------------------------------
# Rewrite trust helpers
# ---------------------------------------------------------------------------


def empty_rewrite_registry(registry_id: str = "rewrite-registry/default") -> TrustedRewriteRegistry:
    return TrustedRewriteRegistry(registry_id=registry_id, rules=())


def register_rewrite(
    registry: TrustedRewriteRegistry,
    rule: RewriteRule,
) -> TrustedRewriteRegistry:
    """Register a rewrite, preserving proved/heuristic distinction."""

    return registry.with_rule(rule)


def admit_rewrite_for_proof_extraction(
    registry: TrustedRewriteRegistry,
    rule_id: str,
) -> RewriteRule:
    """Admit a rewrite into proof-producing extraction or fail closed."""

    return registry.require_proof_extraction_admission(rule_id)


def distinguish_rewrite_trust(
    rules: Sequence[RewriteRule],
) -> dict[str, tuple[RewriteRule, ...]]:
    """Partition rules into proved, solver_validated, and heuristic classes."""

    proved: list[RewriteRule] = []
    solver_validated: list[RewriteRule] = []
    heuristic: list[RewriteRule] = []
    for rule in _coerce_records(rules, RewriteRule, "rules"):
        if rule.trust_class is RewriteTrustClass.PROVED:
            proved.append(rule)
        elif rule.trust_class is RewriteTrustClass.SOLVER_VALIDATED:
            solver_validated.append(rule)
        else:
            heuristic.append(rule)
    return {
        "proved": tuple(proved),
        "solver_validated": tuple(solver_validated),
        "heuristic": tuple(heuristic),
    }


# ---------------------------------------------------------------------------
# Adversarial round trips
# ---------------------------------------------------------------------------


REQUIRED_ADVERSARIAL_KINDS: Final[tuple[AdversarialCaseKind, ...]] = (
    AdversarialCaseKind.NEGATION,
    AdversarialCaseKind.EXCEPTION,
    AdversarialCaseKind.TEMPORAL_OVERLAP,
    AdversarialCaseKind.CONFLICT,
    AdversarialCaseKind.JURISDICTION,
)


def evaluate_adversarial_round_trip(
    *,
    case_id: str,
    case_kind: AdversarialCaseKind | str,
    source_norms: Sequence[DeonticNorm],
    target_norms: Sequence[DeonticNorm],
    named_losses: Sequence[NamedLoss] = (),
    source_cid: str = "",
    target_cid: str = "",
    recompilation_cid: str = "",
    rejected: bool = False,
    unsupported: bool = False,
) -> AdversarialRoundTripResult:
    """Evaluate one adversarial case and return an explicit disposition.

    Disposition priority (fail-closed, never silent):

    1. ``rejected`` → :attr:`RoundTripDisposition.REJECTED`
    2. ``unsupported`` → :attr:`RoundTripDisposition.UNSUPPORTED`
    3. safety-refinement conflict → :attr:`RoundTripDisposition.CONFLICT_RECORDED`
    4. named losses present → :attr:`RoundTripDisposition.NAMED_LOSS`
    5. otherwise → :attr:`RoundTripDisposition.PRESERVED`
    """

    kind = _enum(case_kind, AdversarialCaseKind, "case_kind")
    losses = _coerce_records(named_losses, NamedLoss, "named_losses")

    if rejected:
        return AdversarialRoundTripResult(
            case_id=case_id,
            case_kind=kind,
            disposition=RoundTripDisposition.REJECTED,
            detail=f"adversarial {kind.value} case rejected by translation gate",
            source_cid=source_cid,
            target_cid=target_cid,
            recompilation_cid=recompilation_cid,
        )
    if unsupported:
        return AdversarialRoundTripResult(
            case_id=case_id,
            case_kind=kind,
            disposition=RoundTripDisposition.UNSUPPORTED,
            detail=f"adversarial {kind.value} case unsupported by target family",
            named_loss_ids=tuple(item.loss_id for item in losses),
            source_cid=source_cid,
            target_cid=target_cid,
            recompilation_cid=recompilation_cid,
        )

    refinement = check_deontic_safety_refinement(source_norms, target_norms)
    if not refinement.is_safe:
        kinds = ", ".join(sorted({item.kind.value for item in refinement.violations}))
        return AdversarialRoundTripResult(
            case_id=case_id,
            case_kind=kind,
            disposition=RoundTripDisposition.CONFLICT_RECORDED,
            detail=f"adversarial {kind.value} case recorded safety conflict: {kinds}",
            source_cid=source_cid,
            target_cid=target_cid,
            recompilation_cid=recompilation_cid,
        )

    if losses:
        return AdversarialRoundTripResult(
            case_id=case_id,
            case_kind=kind,
            disposition=RoundTripDisposition.NAMED_LOSS,
            detail=(
                f"adversarial {kind.value} case preserved under named loss: "
                + "; ".join(item.exact_loss for item in losses)
            ),
            named_loss_ids=tuple(item.loss_id for item in losses),
            source_cid=source_cid,
            target_cid=target_cid,
            recompilation_cid=recompilation_cid,
        )

    return AdversarialRoundTripResult(
        case_id=case_id,
        case_kind=kind,
        disposition=RoundTripDisposition.PRESERVED,
        detail=f"adversarial {kind.value} case preserved under safety refinement",
        source_cid=source_cid,
        target_cid=target_cid,
        recompilation_cid=recompilation_cid,
    )


def require_explicit_adversarial_dispositions(
    results: Sequence[AdversarialRoundTripResult],
    *,
    require_all_kinds: bool = True,
) -> tuple[AdversarialRoundTripResult, ...]:
    """Fail closed unless every adversarial result has an explicit disposition.

    When ``require_all_kinds`` is true, all five TVC adversarial families must
    appear exactly once by kind.
    """

    results = _coerce_records(
        results, AdversarialRoundTripResult, "adversarial_results"
    )
    for item in results:
        if not isinstance(item.disposition, RoundTripDisposition):
            raise RoundTripError(
                f"adversarial case {item.case_id} missing explicit disposition"
            )
        if not item.detail:
            raise RoundTripError(
                f"adversarial case {item.case_id} disposition detail is empty"
            )
    if require_all_kinds:
        present = {item.case_kind for item in results}
        missing = [kind.value for kind in REQUIRED_ADVERSARIAL_KINDS if kind not in present]
        if missing:
            raise RoundTripError(
                "adversarial round trips missing required kinds: "
                + ", ".join(missing)
            )
    return results


# ---------------------------------------------------------------------------
# Receipt emission
# ---------------------------------------------------------------------------


def emit_translation_receipt(
    *,
    source_cid: str,
    target_cid: str,
    compiler_cid: str,
    source_schema: str,
    target_schema: str,
    preservation_class: PreservationClass | str,
    equality_criteria: EqualityCriteria | Mapping[str, Any],
    assumptions: Sequence[str] = (),
    obligations: Sequence[str] = (),
    named_losses: Sequence[NamedLoss | Mapping[str, Any]] = (),
    source_norms: Sequence[DeonticNorm | Mapping[str, Any]] = (),
    target_norms: Sequence[DeonticNorm | Mapping[str, Any]] = (),
    rewrite_registry: TrustedRewriteRegistry | None = None,
    adversarial_results: Sequence[
        AdversarialRoundTripResult | Mapping[str, Any]
    ] = (),
    decompiler_cid: str = "",
    recompilation_cid: str = "",
    comparison_cid: str = "",
    metadata: Mapping[str, Any] | None = None,
    enforce_safety: bool = True,
) -> TranslationReceipt:
    """Emit a fail-closed translation receipt with optional safety enforcement.

    When ``source_norms`` / ``target_norms`` are provided and ``enforce_safety``
    is true, unsafe refinements raise :class:`SafetyRefinementError` unless the
    preservation class is explicitly ``lossy`` / ``heuristic`` / ``approximate``
    *and* every dropped construct is named via ``named_losses``.
    """

    source_norm_records = _coerce_records(source_norms, DeonticNorm, "source_norms")
    target_norm_records = _coerce_records(target_norms, DeonticNorm, "target_norms")
    loss_records = _coerce_records(named_losses, NamedLoss, "named_losses")
    adversarial_records = _coerce_records(
        adversarial_results, AdversarialRoundTripResult, "adversarial_results"
    )

    safety: Optional[SafetyRefinementResult] = None
    if source_norm_records or target_norm_records:
        safety = check_deontic_safety_refinement(
            source_norm_records, target_norm_records
        )
        if enforce_safety and not safety.is_safe:
            # Allow explicit lossy/heuristic paths only when every violation is
            # covered by a NamedLoss that names the exact loss.
            preservation = _enum(
                preservation_class, PreservationClass, "preservation_class"
            )
            if preservation not in {
                PreservationClass.LOSSY,
                PreservationClass.HEURISTIC,
                PreservationClass.APPROXIMATE,
            }:
                raise SafetyRefinementError(
                    "unsafe deontic refinement cannot be emitted under "
                    f"{preservation.value} preservation; use lossy/heuristic "
                    "with NamedLoss or repair the target"
                )
            covered_actions = {
                item.construct_id for item in loss_records
            } | {item.exact_loss for item in loss_records}
            for violation in safety.violations:
                # Require that some named loss mentions the violation kind or
                # the source norm id.
                if not any(
                    violation.kind.value in item.exact_loss
                    or violation.source_norm_id in {
                        item.construct_id,
                        *item.source_ref_ids,
                    }
                    or violation.source_norm_id in covered_actions
                    for item in loss_records
                ):
                    raise SafetyRefinementError(
                        "unsafe refinement violation "
                        f"{violation.kind.value} for {violation.source_norm_id} "
                        "lacks a NamedLoss that names the exact loss"
                    )

    registry_cid = ""
    if rewrite_registry is not None:
        registry_cid = rewrite_registry.registry_cid

    return TranslationReceipt(
        source_cid=source_cid,
        target_cid=target_cid,
        compiler_cid=compiler_cid,
        source_schema=source_schema,
        target_schema=target_schema,
        preservation_class=preservation_class,  # type: ignore[arg-type]
        equality_criteria=equality_criteria,  # type: ignore[arg-type]
        assumptions=tuple(assumptions),
        obligations=tuple(obligations),
        named_losses=loss_records,
        source_norms=source_norm_records,
        target_norms=target_norm_records,
        safety_refinement=safety,
        rewrite_registry_cid=registry_cid,
        adversarial_results=adversarial_records,
        decompiler_cid=decompiler_cid,
        recompilation_cid=recompilation_cid,
        comparison_cid=comparison_cid,
        metadata=dict(metadata or {}),
    )


def loss_names_exact(receipt: TranslationReceipt) -> tuple[str, ...]:
    """Return the exact-loss strings bound by a receipt (fail if any blank)."""

    names: list[str] = []
    for item in receipt.named_losses:
        if not item.exact_loss.strip():
            raise TranslationValidationError(
                f"named loss {item.loss_id} does not name exact loss"
            )
        names.append(item.exact_loss)
    return tuple(names)


def assert_no_permission_broadening(receipt: TranslationReceipt) -> None:
    """Fail closed if receipt safety refinement reports permission broadening."""

    if receipt.safety_refinement is None:
        if receipt.source_norms or receipt.target_norms:
            raise SafetyRefinementError(
                "receipt with deontic norms lacks safety_refinement"
            )
        return
    if not receipt.safety_refinement.is_safe:
        broadening = [
            item
            for item in receipt.safety_refinement.violations
            if item.kind
            in {
                SafetyViolationKind.PERMISSION_BROADENED,
                SafetyViolationKind.PROHIBITION_REMOVED,
                SafetyViolationKind.PROHIBITION_WEAKENED_TO_PERMISSION,
                SafetyViolationKind.OBLIGATION_REMOVED,
                SafetyViolationKind.OBLIGATION_WEAKENED_TO_PERMISSION,
                SafetyViolationKind.CONDITION_BROADENED,
                SafetyViolationKind.EXCEPTION_DROPPED,
                SafetyViolationKind.TEMPORAL_SCOPE_BROADENED,
                SafetyViolationKind.JURISDICTION_BROADENED,
            }
        ]
        if broadening:
            kinds = ", ".join(sorted({item.kind.value for item in broadening}))
            raise SafetyRefinementError(
                f"receipt permits unsafe deontic widening: {kinds}"
            )


__all__ = [
    "ADMIT_HEURISTIC_INTO_PROOF_EXTRACTION",
    "ANALYZER_VERSION",
    "BUNDLE",
    "CANONICAL_COMPILER_INTERFACE",
    "CANONICAL_DECOMPILER_INTERFACE",
    "CLAIM_EQUIVALENCE_WITHOUT_CRITERIA",
    "DEONTIC_REFINEMENT_SCHEMA",
    "EGRAPH_REWRITE_INTERFACE",
    "EVIDENCE_DEONTIC_REFINEMENT",
    "EVIDENCE_REWRITE_TRUST",
    "EVIDENCE_TRANSLATION_RECEIPT",
    "GOAL_ID",
    "INTERFACE",
    "LOGIC_TRANSLATION_RECEIPT_INTERFACE",
    "REQUIRED_ADVERSARIAL_KINDS",
    "REWRITE_TRUST_SCHEMA",
    "ROUNDTRIP_SCHEMA",
    "SCHEMA",
    "SILENT_DROP_FORBIDDEN",
    "TASK_ID",
    "UNSAFE_PROMOTION",
    "AdversarialCaseKind",
    "AdversarialRoundTripResult",
    "DeonticModality",
    "DeonticNorm",
    "EqualityCriteria",
    "EqualityCriteriaKind",
    "LossHandling",
    "NamedLoss",
    "PreservationClass",
    "RewriteRule",
    "RewriteTrustClass",
    "RewriteTrustError",
    "RoundTripDisposition",
    "RoundTripError",
    "SafetyRefinementError",
    "SafetyRefinementResult",
    "SafetyViolation",
    "SafetyViolationKind",
    "TranslationReceipt",
    "TranslationValidationError",
    "TrustedRewriteRegistry",
    "admit_rewrite_for_proof_extraction",
    "assert_no_permission_broadening",
    "check_deontic_safety_refinement",
    "content_cid",
    "distinguish_rewrite_trust",
    "emit_translation_receipt",
    "empty_rewrite_registry",
    "evaluate_adversarial_round_trip",
    "loss_names_exact",
    "register_rewrite",
    "require_deontic_safety_refinement",
    "require_explicit_adversarial_dispositions",
]
