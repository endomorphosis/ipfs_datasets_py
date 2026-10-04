"""Common Crypto IR security rules and obligation descriptors (CRYPTOIR-G310).

This module owns the **security claim and obligation rule pack** surface:

* :class:`SecurityRule` — versioned rule descriptor with full preconditions
* :class:`ProofObligation` — named obligation (never a universal "secure")
* :class:`RuleApplicability` — explicit apply / refuse result
* :class:`ViolationWitness` — structured counterexample shape

A rule is **admissible only when the frontend proves** it supplies every
semantic dependency (coverage dimensions + required fact ids).  Inappropriate
rules (wrong chain, missing semantics, unsupported dimensions) do not silently
apply: they return an explicit :class:`RuleApplicability` status and the
configured unsupported fallback outcome.

Chain-specific instantiations live in :mod:`.chain_rules`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.canonical import canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .contract_semantics import (
    ContractSemanticModel,
    CoverageStatus,
    ProofObligationDependency,
    assert_obligation_admissible,
)
from .identity import crypto_ir_identity
from .model import CryptoIRValidationError
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from .verdicts import AnalysisOutcome


CRYPTO_IR_SECURITY_RULES_DOMAIN: Final[str] = "crypto-ir.security-rules"
CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION

# Descriptor pack revision for the common catalog (independent of kernel schema).
SECURITY_RULE_PACK_VERSION: Final[str] = "1.0.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")

# Forbidden universal-security collapse language (case-insensitive match on
# whole-token phrases after normalization).
_UNIVERSAL_SECURE_RE = re.compile(
    r"(?i)(?:\bis\s+secure\b|\bfully\s+secure\b|\buniversally\s+secure\b|"
    r"\bsecure\s+contract\b|\bno\s+vulnerabilities\b|\bhacked[-\s]?proof\b)"
)


class ObligationCategory(str, Enum):
    """Closed vocabulary of named security obligation families.

    Categories are claim *kinds*, not proof outcomes.  Each rule binds one
    category to an exact obligation statement.
    """

    AUTHORIZATION = "authorization"
    VALUE_CONSERVATION = "value_conservation"
    MINT_BURN_TRANSFER = "mint_burn_transfer"
    ALLOWANCE = "allowance"
    REPLAY = "replay"
    CALLBACK_REENTRANCY = "callback_reentrancy"
    CPI = "cpi"
    ARITHMETIC = "arithmetic"
    UPGRADE = "upgrade"
    ORACLE_FRESHNESS = "oracle_freshness"
    INTENT_EFFECT_EQUALITY = "intent_effect_equality"
    TIMELOCK = "timelock"
    RESOURCE_BOUNDS = "resource_bounds"


class FormalTargetKind(str, Enum):
    """Reviewed formal-target families a rule may lower into.

    Selection here does not execute a prover; formalization (CRYPTOIR-G320)
    owns soundness-scoped lowerings.
    """

    SMT_LIB = "smt_lib"
    FOL = "fol"
    DATALOG = "datalog"
    TEMPORAL = "temporal"
    PROPOSITIONAL = "propositional"
    MONITOR = "monitor"
    DETERMINISTIC = "deterministic"


class ApplicabilityStatus(str, Enum):
    """Whether a rule may generate a live proof obligation for a model."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    MISSING_SEMANTIC = "missing_semantic"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class UnsupportedFallback(str, Enum):
    """Explicit non-proof outcome when a rule cannot apply.

    Maps to :class:`~.verdicts.AnalysisOutcome` values that never claim proof.
    """

    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"
    STALE = "stale"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CryptoIRValidationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CryptoIRValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CryptoIRValidationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CryptoIRValidationError(f"{name} is not a stable identifier")
    return normalized


def _version(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _VERSION_RE.fullmatch(normalized):
        raise CryptoIRValidationError(f"{name} must be a semver-like version string")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CryptoIRValidationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CryptoIRValidationError(
            f"unknown {name} field(s): {', '.join(unknown)}"
        )


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (ProvenanceValidationError, CryptoIRProvenanceError, TypeError, ValueError) as exc:
        raise CryptoIRValidationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CryptoIRValidationError(f"unsupported {name}: {value!r}") from exc


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def _unique_texts(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise CryptoIRValidationError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise CryptoIRValidationError(f"{name} values must be unique")
    return result


def assert_not_universal_secure(statement: str, *, field: str = "statement") -> str:
    """Reject obligation language that collapses into universal 'secure'."""

    text = _text(statement, field)
    if _UNIVERSAL_SECURE_RE.search(text):
        raise CryptoIRValidationError(
            f"{field} must name an exact obligation and must not collapse "
            "into a universal 'secure' claim"
        )
    return text


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViolationWitness:
    """Structured shape of a disproof / counterexample for one obligation.

    A witness names the facts that would demonstrate a violation.  It is a
    *template* on the rule and a *filled* record when analysis produces one.
    """

    witness_id: str
    description: str
    fact_ids: tuple[str, ...] = ()
    path_summary: str = ""
    effect_ids: tuple[str, ...] = ()
    control_edge_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "witness_id", _identifier(self.witness_id, "witness_id")
        )
        object.__setattr__(
            self, "description", assert_not_universal_secure(self.description, field="description")
        )
        object.__setattr__(self, "fact_ids", _unique_ids(self.fact_ids, "fact_ids"))
        object.__setattr__(
            self,
            "path_summary",
            _text(self.path_summary, "path_summary", allow_empty=True),
        )
        object.__setattr__(
            self, "effect_ids", _unique_ids(self.effect_ids, "effect_ids")
        )
        object.__setattr__(
            self,
            "control_edge_ids",
            _unique_ids(self.control_edge_ids, "control_edge_ids"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "control_edge_ids": list(self.control_edge_ids),
            "description": self.description,
            "effect_ids": list(self.effect_ids),
            "fact_ids": list(self.fact_ids),
            "path_summary": self.path_summary,
            "witness_id": self.witness_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ViolationWitness":
        value = _as_mapping(value, "ViolationWitness")
        _known_fields(
            value,
            frozenset(
                {
                    "witness_id",
                    "description",
                    "fact_ids",
                    "path_summary",
                    "effect_ids",
                    "control_edge_ids",
                    "attributes",
                }
            ),
            "ViolationWitness",
        )
        return cls(
            witness_id=value.get("witness_id", ""),
            description=value.get("description", ""),
            fact_ids=tuple(value.get("fact_ids", ())),
            path_summary=value.get("path_summary", ""),
            effect_ids=tuple(value.get("effect_ids", ())),
            control_edge_ids=tuple(value.get("control_edge_ids", ())),
            attributes=value.get("attributes", {}),
        )

    def with_facts(
        self,
        fact_ids: Sequence[str],
        *,
        effect_ids: Sequence[str] | None = None,
        control_edge_ids: Sequence[str] | None = None,
        path_summary: str | None = None,
    ) -> "ViolationWitness":
        """Return a filled witness bound to concrete model facts."""

        return ViolationWitness(
            witness_id=self.witness_id,
            description=self.description,
            fact_ids=tuple(fact_ids),
            path_summary=self.path_summary if path_summary is None else path_summary,
            effect_ids=(
                self.effect_ids if effect_ids is None else tuple(effect_ids)
            ),
            control_edge_ids=(
                self.control_edge_ids
                if control_edge_ids is None
                else tuple(control_edge_ids)
            ),
            attributes=dict(self.attributes),
        )


@dataclass(frozen=True, slots=True)
class ProofObligation:
    """A named security obligation with exact formal and evidence targets.

    Security conclusions must cite one or more of these obligations.  The
    ``statement`` field is the claim language and must never collapse into
    universal 'secure'.
    """

    obligation_id: str
    category: ObligationCategory
    statement: str
    formal_target: str
    formal_target_kind: FormalTargetKind
    required_fact_ids: tuple[str, ...]
    required_semantic_dimensions: tuple[str, ...]
    trusted_assumption_ids: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    violation_witness: ViolationWitness | None = None
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "category", _enum(ObligationCategory, self.category, "category")
        )
        object.__setattr__(
            self, "statement", assert_not_universal_secure(self.statement)
        )
        object.__setattr__(
            self, "formal_target", _text(self.formal_target, "formal_target")
        )
        object.__setattr__(
            self,
            "formal_target_kind",
            _enum(FormalTargetKind, self.formal_target_kind, "formal_target_kind"),
        )
        object.__setattr__(
            self,
            "required_fact_ids",
            _unique_ids(self.required_fact_ids, "required_fact_ids"),
        )
        if not self.required_fact_ids:
            raise CryptoIRValidationError(
                "proof obligation must declare at least one required fact"
            )
        object.__setattr__(
            self,
            "required_semantic_dimensions",
            _unique_texts(
                self.required_semantic_dimensions, "required_semantic_dimensions"
            ),
        )
        if not self.required_semantic_dimensions:
            raise CryptoIRValidationError(
                "proof obligation must declare at least one semantic dimension"
            )
        object.__setattr__(
            self,
            "trusted_assumption_ids",
            _unique_ids(self.trusted_assumption_ids, "trusted_assumption_ids"),
        )
        object.__setattr__(
            self,
            "required_evidence",
            _unique_texts(self.required_evidence, "required_evidence"),
        )
        if self.violation_witness is not None and not isinstance(
            self.violation_witness, ViolationWitness
        ):
            if isinstance(self.violation_witness, Mapping):
                object.__setattr__(
                    self,
                    "violation_witness",
                    ViolationWitness.from_dict(self.violation_witness),
                )
            else:
                raise CryptoIRValidationError(
                    "violation_witness must be ViolationWitness or mapping"
                )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        if self.summary:
            assert_not_universal_secure(self.summary, field="summary")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dependency(self) -> ProofObligationDependency:
        """Project to the contract-semantics admissibility dependency view."""

        return ProofObligationDependency(
            obligation_id=self.obligation_id,
            required_fact_ids=self.required_fact_ids,
            summary=self.summary or self.statement,
            attributes={
                "category": self.category.value
                if isinstance(self.category, ObligationCategory)
                else self.category,
                "formal_target": self.formal_target,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "category": (
                self.category.value
                if isinstance(self.category, ObligationCategory)
                else self.category
            ),
            "formal_target": self.formal_target,
            "formal_target_kind": (
                self.formal_target_kind.value
                if isinstance(self.formal_target_kind, FormalTargetKind)
                else self.formal_target_kind
            ),
            "obligation_id": self.obligation_id,
            "required_evidence": list(self.required_evidence),
            "required_fact_ids": list(self.required_fact_ids),
            "required_semantic_dimensions": list(self.required_semantic_dimensions),
            "schema_version": self.schema_version,
            "statement": self.statement,
            "summary": self.summary,
            "trusted_assumption_ids": list(self.trusted_assumption_ids),
            "violation_witness": (
                self.violation_witness.to_dict()
                if self.violation_witness is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofObligation":
        value = _as_mapping(value, "ProofObligation")
        _known_fields(
            value,
            frozenset(
                {
                    "obligation_id",
                    "category",
                    "statement",
                    "formal_target",
                    "formal_target_kind",
                    "required_fact_ids",
                    "required_semantic_dimensions",
                    "trusted_assumption_ids",
                    "required_evidence",
                    "violation_witness",
                    "summary",
                    "attributes",
                    "schema_version",
                }
            ),
            "ProofObligation",
        )
        witness = value.get("violation_witness")
        return cls(
            obligation_id=value.get("obligation_id", ""),
            category=value.get("category", ObligationCategory.AUTHORIZATION),
            statement=value.get("statement", ""),
            formal_target=value.get("formal_target", ""),
            formal_target_kind=value.get(
                "formal_target_kind", FormalTargetKind.DETERMINISTIC
            ),
            required_fact_ids=tuple(value.get("required_fact_ids", ())),
            required_semantic_dimensions=tuple(
                value.get("required_semantic_dimensions", ())
            ),
            trusted_assumption_ids=tuple(value.get("trusted_assumption_ids", ())),
            required_evidence=tuple(value.get("required_evidence", ())),
            violation_witness=witness,
            summary=value.get("summary", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SECURITY_RULES_DOMAIN}.obligation",
        )


@dataclass(frozen=True, slots=True)
class RuleApplicability:
    """Result of testing whether a rule may apply to a semantic model.

    Inappropriate rules never silently apply: status is never upgraded without
    explicit caller action.
    """

    rule_id: str
    status: ApplicabilityStatus
    reason: str
    missing_semantic_dimensions: tuple[str, ...] = ()
    missing_fact_ids: tuple[str, ...] = ()
    unsupported_codes: tuple[str, ...] = ()
    matched_chain_namespaces: tuple[str, ...] = ()
    fallback_outcome: AnalysisOutcome | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(
            self, "status", _enum(ApplicabilityStatus, self.status, "status")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "missing_semantic_dimensions",
            _unique_texts(
                self.missing_semantic_dimensions, "missing_semantic_dimensions"
            ),
        )
        object.__setattr__(
            self,
            "missing_fact_ids",
            _unique_ids(self.missing_fact_ids, "missing_fact_ids"),
        )
        object.__setattr__(
            self,
            "unsupported_codes",
            _unique_texts(self.unsupported_codes, "unsupported_codes"),
        )
        object.__setattr__(
            self,
            "matched_chain_namespaces",
            _unique_texts(
                self.matched_chain_namespaces, "matched_chain_namespaces"
            ),
        )
        if self.fallback_outcome is not None:
            object.__setattr__(
                self,
                "fallback_outcome",
                _enum(AnalysisOutcome, self.fallback_outcome, "fallback_outcome"),
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    @property
    def is_applicable(self) -> bool:
        return self.status is ApplicabilityStatus.APPLICABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "fallback_outcome": (
                self.fallback_outcome.value
                if isinstance(self.fallback_outcome, AnalysisOutcome)
                else self.fallback_outcome
            ),
            "matched_chain_namespaces": list(self.matched_chain_namespaces),
            "missing_fact_ids": list(self.missing_fact_ids),
            "missing_semantic_dimensions": list(self.missing_semantic_dimensions),
            "reason": self.reason,
            "rule_id": self.rule_id,
            "status": (
                self.status.value
                if isinstance(self.status, ApplicabilityStatus)
                else self.status
            ),
            "unsupported_codes": list(self.unsupported_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleApplicability":
        value = _as_mapping(value, "RuleApplicability")
        _known_fields(
            value,
            frozenset(
                {
                    "rule_id",
                    "status",
                    "reason",
                    "missing_semantic_dimensions",
                    "missing_fact_ids",
                    "unsupported_codes",
                    "matched_chain_namespaces",
                    "fallback_outcome",
                    "attributes",
                }
            ),
            "RuleApplicability",
        )
        return cls(
            rule_id=value.get("rule_id", ""),
            status=value.get("status", ApplicabilityStatus.INCONCLUSIVE),
            reason=value.get("reason", ""),
            missing_semantic_dimensions=tuple(
                value.get("missing_semantic_dimensions", ())
            ),
            missing_fact_ids=tuple(value.get("missing_fact_ids", ())),
            unsupported_codes=tuple(value.get("unsupported_codes", ())),
            matched_chain_namespaces=tuple(
                value.get("matched_chain_namespaces", ())
            ),
            fallback_outcome=value.get("fallback_outcome"),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SecurityRule:
    """Versioned security rule descriptor with full admissibility metadata.

    Every rule declares:

    * chain / semantic preconditions (``chain_namespaces``,
      ``semantic_preconditions``)
    * trusted assumptions (``trusted_assumptions``)
    * required evidence (``required_evidence``)
    * formal target (``formal_target`` / ``formal_target_kind``)
    * violation witness (``violation_witness``)
    * unsupported fallback (``unsupported_fallback``)

    Empty ``chain_namespaces`` means the rule is **common** (chain-neutral)
    and applies to any frontend that supplies the semantic dependencies.
    """

    rule_id: str
    version: str
    name: str
    category: ObligationCategory
    statement: str
    formal_target: str
    formal_target_kind: FormalTargetKind
    semantic_preconditions: tuple[str, ...]
    required_evidence: tuple[str, ...]
    violation_witness: ViolationWitness
    unsupported_fallback: UnsupportedFallback = UnsupportedFallback.UNSUPPORTED
    chain_namespaces: tuple[str, ...] = ()
    trusted_assumptions: tuple[str, ...] = ()
    fact_id_templates: tuple[str, ...] = ()
    summary: str = ""
    pack_version: str = SECURITY_RULE_PACK_VERSION
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "version", _version(self.version, "version"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "category", _enum(ObligationCategory, self.category, "category")
        )
        object.__setattr__(
            self, "statement", assert_not_universal_secure(self.statement)
        )
        object.__setattr__(
            self, "formal_target", _text(self.formal_target, "formal_target")
        )
        object.__setattr__(
            self,
            "formal_target_kind",
            _enum(FormalTargetKind, self.formal_target_kind, "formal_target_kind"),
        )
        object.__setattr__(
            self,
            "semantic_preconditions",
            _unique_texts(self.semantic_preconditions, "semantic_preconditions"),
        )
        if not self.semantic_preconditions:
            raise CryptoIRValidationError(
                "security rule must declare at least one semantic precondition"
            )
        object.__setattr__(
            self,
            "required_evidence",
            _unique_texts(self.required_evidence, "required_evidence"),
        )
        if not self.required_evidence:
            raise CryptoIRValidationError(
                "security rule must declare at least one required evidence term"
            )
        if not isinstance(self.violation_witness, ViolationWitness):
            if isinstance(self.violation_witness, Mapping):
                object.__setattr__(
                    self,
                    "violation_witness",
                    ViolationWitness.from_dict(self.violation_witness),
                )
            else:
                raise CryptoIRValidationError(
                    "violation_witness must be ViolationWitness or mapping"
                )
        object.__setattr__(
            self,
            "unsupported_fallback",
            _enum(
                UnsupportedFallback,
                self.unsupported_fallback,
                "unsupported_fallback",
            ),
        )
        object.__setattr__(
            self,
            "chain_namespaces",
            _unique_texts(self.chain_namespaces, "chain_namespaces"),
        )
        object.__setattr__(
            self,
            "trusted_assumptions",
            _unique_texts(self.trusted_assumptions, "trusted_assumptions"),
        )
        object.__setattr__(
            self,
            "fact_id_templates",
            _unique_texts(self.fact_id_templates, "fact_id_templates"),
        )
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", allow_empty=True)
        )
        if self.summary:
            assert_not_universal_secure(self.summary, field="summary")
        object.__setattr__(
            self, "pack_version", _version(self.pack_version, "pack_version")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def is_common(self) -> bool:
        """True when the rule is chain-neutral (no namespace restriction)."""

        return not self.chain_namespaces

    def supports_chain(self, chain_namespace: str) -> bool:
        """Return True when *chain_namespace* is in scope for this rule."""

        namespace = _text(chain_namespace, "chain_namespace")
        if self.is_common:
            return True
        return namespace in self.chain_namespaces

    def fallback_analysis_outcome(self) -> AnalysisOutcome:
        """Map unsupported fallback to a non-proof analysis outcome."""

        mapping = {
            UnsupportedFallback.UNSUPPORTED: AnalysisOutcome.UNSUPPORTED,
            UnsupportedFallback.INCONCLUSIVE: AnalysisOutcome.INCONCLUSIVE,
            UnsupportedFallback.UNKNOWN: AnalysisOutcome.UNKNOWN,
            UnsupportedFallback.STALE: AnalysisOutcome.STALE,
            UnsupportedFallback.ERROR: AnalysisOutcome.ERROR,
        }
        return mapping[self.unsupported_fallback]  # type: ignore[index]

    def bind_obligation(
        self,
        *,
        required_fact_ids: Sequence[str],
        trusted_assumption_ids: Sequence[str] | None = None,
        obligation_id: str | None = None,
    ) -> ProofObligation:
        """Instantiate a concrete obligation from this rule descriptor."""

        facts = _unique_ids(tuple(required_fact_ids), "required_fact_ids")
        if not facts:
            raise CryptoIRValidationError(
                "bound obligation must include at least one required fact id"
            )
        assumptions = (
            self.trusted_assumptions
            if trusted_assumption_ids is None
            else _unique_ids(tuple(trusted_assumption_ids), "trusted_assumption_ids")
        )
        return ProofObligation(
            obligation_id=obligation_id or f"obl:{self.rule_id}",
            category=self.category,
            statement=self.statement,
            formal_target=self.formal_target,
            formal_target_kind=self.formal_target_kind,
            required_fact_ids=facts,
            required_semantic_dimensions=self.semantic_preconditions,
            trusted_assumption_ids=assumptions,
            required_evidence=self.required_evidence,
            violation_witness=self.violation_witness,
            summary=self.summary or f"obligation from rule {self.rule_id}",
            attributes={
                "rule_id": self.rule_id,
                "rule_version": self.version,
                "pack_version": self.pack_version,
            },
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "category": (
                self.category.value
                if isinstance(self.category, ObligationCategory)
                else self.category
            ),
            "chain_namespaces": list(self.chain_namespaces),
            "fact_id_templates": list(self.fact_id_templates),
            "formal_target": self.formal_target,
            "formal_target_kind": (
                self.formal_target_kind.value
                if isinstance(self.formal_target_kind, FormalTargetKind)
                else self.formal_target_kind
            ),
            "name": self.name,
            "pack_version": self.pack_version,
            "required_evidence": list(self.required_evidence),
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
            "semantic_preconditions": list(self.semantic_preconditions),
            "statement": self.statement,
            "summary": self.summary,
            "trusted_assumptions": list(self.trusted_assumptions),
            "unsupported_fallback": (
                self.unsupported_fallback.value
                if isinstance(self.unsupported_fallback, UnsupportedFallback)
                else self.unsupported_fallback
            ),
            "version": self.version,
            "violation_witness": self.violation_witness.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityRule":
        value = _as_mapping(value, "SecurityRule")
        _known_fields(
            value,
            frozenset(
                {
                    "rule_id",
                    "version",
                    "name",
                    "category",
                    "statement",
                    "formal_target",
                    "formal_target_kind",
                    "semantic_preconditions",
                    "required_evidence",
                    "violation_witness",
                    "unsupported_fallback",
                    "chain_namespaces",
                    "trusted_assumptions",
                    "fact_id_templates",
                    "summary",
                    "pack_version",
                    "attributes",
                    "schema_version",
                }
            ),
            "SecurityRule",
        )
        return cls(
            rule_id=value.get("rule_id", ""),
            version=value.get("version", "1.0.0"),
            name=value.get("name", ""),
            category=value.get("category", ObligationCategory.AUTHORIZATION),
            statement=value.get("statement", ""),
            formal_target=value.get("formal_target", ""),
            formal_target_kind=value.get(
                "formal_target_kind", FormalTargetKind.DETERMINISTIC
            ),
            semantic_preconditions=tuple(value.get("semantic_preconditions", ())),
            required_evidence=tuple(value.get("required_evidence", ())),
            violation_witness=value.get("violation_witness", {}),
            unsupported_fallback=value.get(
                "unsupported_fallback", UnsupportedFallback.UNSUPPORTED
            ),
            chain_namespaces=tuple(value.get("chain_namespaces", ())),
            trusted_assumptions=tuple(value.get("trusted_assumptions", ())),
            fact_id_templates=tuple(value.get("fact_id_templates", ())),
            summary=value.get("summary", ""),
            pack_version=value.get("pack_version", SECURITY_RULE_PACK_VERSION),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION
            ),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SECURITY_RULES_DOMAIN}.rule",
        )


# ---------------------------------------------------------------------------
# Applicability evaluation
# ---------------------------------------------------------------------------


def _coverage_by_dimension(
    model: ContractSemanticModel,
) -> dict[str, list[Any]]:
    by_dim: dict[str, list[Any]] = {}
    for item in model.coverage:
        by_dim.setdefault(item.dimension, []).append(item)
    return by_dim


def _unsupported_for_dimensions(
    model: ContractSemanticModel, dimensions: Sequence[str]
) -> tuple[str, ...]:
    wanted = set(dimensions)
    codes: list[str] = []
    for item in model.unsupported:
        if item.dimension in wanted or (not item.dimension and wanted):
            codes.append(item.code)
    return tuple(sorted(set(codes)))


def evaluate_rule_applicability(
    rule: SecurityRule,
    model: ContractSemanticModel,
    *,
    chain_namespace: str | None = None,
    required_fact_ids: Sequence[str] | None = None,
) -> RuleApplicability:
    """Decide whether *rule* may apply to *model* without silent fallback.

    Order of checks (fail closed):

    1. chain namespace preconditions
    2. explicit unsupported semantics on required dimensions
    3. coverage status for each semantic precondition
    4. required fact ids (when provided) covered and not discarded
    """

    if not isinstance(rule, SecurityRule):
        raise CryptoIRValidationError("rule must be a SecurityRule")
    if not isinstance(model, ContractSemanticModel):
        raise CryptoIRValidationError("model must be a ContractSemanticModel")

    namespace = chain_namespace if chain_namespace is not None else model.chain_namespace
    namespace = _text(namespace, "chain_namespace")
    fallback = rule.fallback_analysis_outcome()

    if not rule.supports_chain(namespace):
        return RuleApplicability(
            rule_id=rule.rule_id,
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reason=(
                f"rule {rule.rule_id} does not apply to chain namespace "
                f"{namespace!r}; allowed={list(rule.chain_namespaces)}"
            ),
            matched_chain_namespaces=rule.chain_namespaces,
            fallback_outcome=fallback,
        )

    unsupported_codes = _unsupported_for_dimensions(
        model, rule.semantic_preconditions
    )
    if unsupported_codes:
        return RuleApplicability(
            rule_id=rule.rule_id,
            status=ApplicabilityStatus.UNSUPPORTED,
            reason=(
                f"rule {rule.rule_id} blocked by unsupported semantics: "
                f"{', '.join(unsupported_codes)}"
            ),
            unsupported_codes=unsupported_codes,
            matched_chain_namespaces=(namespace,),
            fallback_outcome=fallback,
        )

    by_dim = _coverage_by_dimension(model)
    missing_dims: list[str] = []
    partial_dims: list[str] = []
    for dim in rule.semantic_preconditions:
        entries = by_dim.get(dim, ())
        if not entries:
            missing_dims.append(dim)
            continue
        statuses = {item.status for item in entries}
        if CoverageStatus.UNSUPPORTED in statuses:
            return RuleApplicability(
                rule_id=rule.rule_id,
                status=ApplicabilityStatus.UNSUPPORTED,
                reason=(
                    f"rule {rule.rule_id} dimension {dim!r} marked unsupported "
                    "in coverage frontier"
                ),
                missing_semantic_dimensions=(dim,),
                matched_chain_namespaces=(namespace,),
                fallback_outcome=fallback,
            )
        if CoverageStatus.COVERED not in statuses:
            if CoverageStatus.PARTIAL in statuses:
                partial_dims.append(dim)
            else:
                missing_dims.append(dim)

    if missing_dims:
        return RuleApplicability(
            rule_id=rule.rule_id,
            status=ApplicabilityStatus.MISSING_SEMANTIC,
            reason=(
                f"rule {rule.rule_id} missing covered semantic dimensions: "
                f"{', '.join(missing_dims)}"
            ),
            missing_semantic_dimensions=tuple(missing_dims),
            matched_chain_namespaces=(namespace,),
            fallback_outcome=fallback,
        )

    if partial_dims and required_fact_ids is None:
        # Partial coverage without concrete fact binding is inconclusive —
        # never silently treat as applicable.
        return RuleApplicability(
            rule_id=rule.rule_id,
            status=ApplicabilityStatus.INCONCLUSIVE,
            reason=(
                f"rule {rule.rule_id} has only partial coverage for: "
                f"{', '.join(partial_dims)}; bind required_fact_ids to admit"
            ),
            missing_semantic_dimensions=tuple(partial_dims),
            matched_chain_namespaces=(namespace,),
            fallback_outcome=AnalysisOutcome.INCONCLUSIVE,
        )

    if required_fact_ids is not None:
        facts = _unique_ids(tuple(required_fact_ids), "required_fact_ids")
        covered = model.covered_fact_ids()
        discarded = model.discarded_fact_ids()
        missing = [fid for fid in facts if fid not in covered]
        on_discarded = [fid for fid in facts if fid in discarded]
        if on_discarded:
            return RuleApplicability(
                rule_id=rule.rule_id,
                status=ApplicabilityStatus.MISSING_SEMANTIC,
                reason=(
                    f"rule {rule.rule_id} depends on discarded facts: "
                    f"{', '.join(on_discarded)}"
                ),
                missing_fact_ids=tuple(on_discarded),
                matched_chain_namespaces=(namespace,),
                fallback_outcome=fallback,
            )
        if missing:
            return RuleApplicability(
                rule_id=rule.rule_id,
                status=ApplicabilityStatus.MISSING_SEMANTIC,
                reason=(
                    f"rule {rule.rule_id} depends on uncovered facts: "
                    f"{', '.join(missing)}"
                ),
                missing_fact_ids=tuple(missing),
                matched_chain_namespaces=(namespace,),
                fallback_outcome=fallback,
            )

    return RuleApplicability(
        rule_id=rule.rule_id,
        status=ApplicabilityStatus.APPLICABLE,
        reason=f"rule {rule.rule_id} is admissible for chain namespace {namespace!r}",
        matched_chain_namespaces=(namespace,),
    )


def admit_rule(
    rule: SecurityRule,
    model: ContractSemanticModel,
    *,
    chain_namespace: str | None = None,
    required_fact_ids: Sequence[str],
    trusted_assumption_ids: Sequence[str] | None = None,
    obligation_id: str | None = None,
) -> ProofObligation:
    """Admit *rule* only when every semantic dependency is supplied.

    Raises :class:`CryptoIRValidationError` when applicability is not
    ``APPLICABLE`` or when the projected obligation fails
    :func:`~.contract_semantics.assert_obligation_admissible`.
    """

    applicability = evaluate_rule_applicability(
        rule,
        model,
        chain_namespace=chain_namespace,
        required_fact_ids=required_fact_ids,
    )
    if not applicability.is_applicable:
        raise CryptoIRValidationError(
            f"rule {rule.rule_id} is not admissible "
            f"({applicability.status.value}): {applicability.reason}"
        )
    obligation = rule.bind_obligation(
        required_fact_ids=required_fact_ids,
        trusted_assumption_ids=trusted_assumption_ids,
        obligation_id=obligation_id,
    )
    assert_obligation_admissible(model, obligation.to_dependency())
    return obligation


def name_security_conclusions(
    obligations: Sequence[ProofObligation],
    outcomes: Mapping[str, AnalysisOutcome | str],
) -> tuple[dict[str, Any], ...]:
    """Build security conclusions that name exact obligations.

    Never returns a universal ``secure`` claim.  Each entry binds one
    obligation id to its analysis outcome.
    """

    if isinstance(obligations, (str, bytes, bytearray)) or not isinstance(
        obligations, Sequence
    ):
        raise CryptoIRValidationError("obligations must be a sequence")
    if not isinstance(outcomes, Mapping):
        raise CryptoIRValidationError("outcomes must be a mapping")

    conclusions: list[dict[str, Any]] = []
    for obligation in obligations:
        if not isinstance(obligation, ProofObligation):
            raise CryptoIRValidationError(
                "obligations items must be ProofObligation instances"
            )
        raw = outcomes.get(obligation.obligation_id)
        if raw is None:
            raise CryptoIRValidationError(
                f"missing outcome for obligation {obligation.obligation_id!r}"
            )
        outcome = (
            raw
            if isinstance(raw, AnalysisOutcome)
            else _enum(AnalysisOutcome, raw, "outcome")
        )
        conclusions.append(
            {
                "category": obligation.category.value,
                "formal_target": obligation.formal_target,
                "obligation_id": obligation.obligation_id,
                "outcome": outcome.value,
                "rule_id": obligation.attributes.get("rule_id", ""),
                "statement": obligation.statement,
            }
        )
    # Deterministic order by obligation_id.
    return tuple(sorted(conclusions, key=lambda item: item["obligation_id"]))


# ---------------------------------------------------------------------------
# Common (chain-neutral) rule catalog
# ---------------------------------------------------------------------------


def _witness(
    witness_id: str,
    description: str,
    *,
    path_summary: str = "",
) -> ViolationWitness:
    return ViolationWitness(
        witness_id=witness_id,
        description=description,
        path_summary=path_summary,
    )


def _common_rule(
    *,
    rule_id: str,
    name: str,
    category: ObligationCategory,
    statement: str,
    formal_target: str,
    formal_target_kind: FormalTargetKind,
    semantic_preconditions: Sequence[str],
    required_evidence: Sequence[str],
    witness: ViolationWitness,
    trusted_assumptions: Sequence[str] = (),
    unsupported_fallback: UnsupportedFallback = UnsupportedFallback.UNSUPPORTED,
    fact_id_templates: Sequence[str] = (),
    summary: str = "",
) -> SecurityRule:
    return SecurityRule(
        rule_id=rule_id,
        version="1.0.0",
        name=name,
        category=category,
        statement=statement,
        formal_target=formal_target,
        formal_target_kind=formal_target_kind,
        semantic_preconditions=tuple(semantic_preconditions),
        required_evidence=tuple(required_evidence),
        violation_witness=witness,
        unsupported_fallback=unsupported_fallback,
        chain_namespaces=(),
        trusted_assumptions=tuple(trusted_assumptions),
        fact_id_templates=tuple(fact_id_templates),
        summary=summary,
        pack_version=SECURITY_RULE_PACK_VERSION,
    )


def common_security_rules() -> tuple[SecurityRule, ...]:
    """Return the versioned common (chain-neutral) security rule pack."""

    return (
        _common_rule(
            rule_id="common.authorization.least_privilege",
            name="Authorization and least privilege",
            category=ObligationCategory.AUTHORIZATION,
            statement=(
                "Only principals with an explicit privilege grant may execute "
                "privileged control edges or asset effects."
            ),
            formal_target="forall privileged_action a. authorized(principal(a), a)",
            formal_target_kind=FormalTargetKind.FOL,
            semantic_preconditions=("control_flow", "privileges"),
            required_evidence=(
                "privilege_set",
                "principal_binding",
                "control_edge_privileges",
            ),
            witness=_witness(
                "wit:auth-escalation",
                "A privileged edge or effect executes without a matching "
                "principal privilege grant.",
                path_summary="unauthorized privileged control edge",
            ),
            trusted_assumptions=("auth.privilege_model_complete",),
            fact_id_templates=("edge:*", "principal:*"),
            summary="Named least-privilege authorization obligation",
        ),
        _common_rule(
            rule_id="common.value.conservation",
            name="Value conservation",
            category=ObligationCategory.VALUE_CONSERVATION,
            statement=(
                "For each exact asset in scope, sum of mint/burn/transfer/spend "
                "effects conserves balance modulo declared fees and explicit "
                "mint/burn authorities."
            ),
            formal_target=(
                "sum(inflows) - sum(outflows) = mint - burn - fees "
                "for each asset identity"
            ),
            formal_target_kind=FormalTargetKind.SMT_LIB,
            semantic_preconditions=("asset_effects",),
            required_evidence=(
                "ordered_asset_effects",
                "exact_amounts",
                "asset_identity",
            ),
            witness=_witness(
                "wit:value-leak",
                "An ordered effect sequence creates or destroys value for an "
                "exact asset without a declared mint/burn authority.",
                path_summary="non-conserving effect sequence",
            ),
            trusted_assumptions=("value.fee_schedule_declared",),
            fact_id_templates=("effect:*",),
            summary="Named value-conservation obligation over exact assets",
        ),
        _common_rule(
            rule_id="common.token.mint_burn_transfer",
            name="Authorized mint, burn, and transfer",
            category=ObligationCategory.MINT_BURN_TRANSFER,
            statement=(
                "Mint, burn, and transfer effects occur only through declared "
                "authorities and match the bound intent parameters."
            ),
            formal_target=(
                "mint/burn/transfer effect e implies authorized(e) and "
                "matches_intent(e)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            semantic_preconditions=("asset_effects", "privileges"),
            required_evidence=(
                "effect_kind",
                "authority_principal",
                "exact_amount",
            ),
            witness=_witness(
                "wit:unauthorized-mint",
                "A mint, burn, or transfer effect lacks declared authority or "
                "diverges from intent parameters.",
            ),
            fact_id_templates=("effect:*", "principal:*"),
        ),
        _common_rule(
            rule_id="common.token.allowance",
            name="Allowance integrity",
            category=ObligationCategory.ALLOWANCE,
            statement=(
                "Allowance grants and spends are bounded by the recorded "
                "approval amount and cannot exceed remaining allowance."
            ),
            formal_target="allowance_spend(e) => amount(e) <= remaining_allowance(e)",
            formal_target_kind=FormalTargetKind.SMT_LIB,
            semantic_preconditions=("asset_effects",),
            required_evidence=(
                "approve_effect",
                "allowance_spend_effect",
                "exact_amounts",
            ),
            witness=_witness(
                "wit:allowance-overflow",
                "An allowance spend exceeds the remaining approved amount.",
            ),
            fact_id_templates=("effect:*",),
        ),
        _common_rule(
            rule_id="common.replay.domain_binding",
            name="Replay resistance and domain binding",
            category=ObligationCategory.REPLAY,
            statement=(
                "Signed or proof-bound actions are bound to chain, domain, "
                "nonce/sequence, and cannot be accepted twice in the same "
                "replay domain."
            ),
            formal_target=(
                "accept(action) once per (chain, domain, nonce_or_nullifier)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            semantic_preconditions=("replay_domain", "identity_binding"),
            required_evidence=(
                "chain_identity",
                "domain_separator",
                "nonce_or_nullifier",
            ),
            witness=_witness(
                "wit:replay",
                "The same action is accepted twice in one replay domain or "
                "across an unbound domain/chain pair.",
            ),
            trusted_assumptions=("replay.domain_separator_stable",),
            fact_id_templates=("epoch:*", "binding:*"),
        ),
        _common_rule(
            rule_id="common.callback.reentrancy",
            name="Callback and reentrancy safety",
            category=ObligationCategory.CALLBACK_REENTRANCY,
            statement=(
                "Reentrant control edges cannot observe intermediate state that "
                "violates declared invariants between external call and state "
                "commit."
            ),
            formal_target=(
                "no reentrant_call observes mutable state before invariant restore"
            ),
            formal_target_kind=FormalTargetKind.TEMPORAL,
            semantic_preconditions=("control_flow", "state_invariants"),
            required_evidence=(
                "reentrant_control_edges",
                "state_invariants",
                "effect_order",
            ),
            witness=_witness(
                "wit:reentrancy",
                "A reentrant call path mutates or reads state that breaks a "
                "declared invariant before the outer frame commits.",
                path_summary="reentrant_call before invariant restore",
            ),
            fact_id_templates=("edge:*", "inv:*"),
        ),
        _common_rule(
            rule_id="common.cpi.privilege_boundary",
            name="CPI / cross-program privilege boundary",
            category=ObligationCategory.CPI,
            statement=(
                "Cross-program or inner invocations preserve declared signer, "
                "writable, and owner constraints; privileges do not escalate "
                "across the CPI boundary."
            ),
            formal_target=(
                "cpi_edge e implies privileges(e)subseteq declared_callee_grants(e)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            semantic_preconditions=("control_flow", "privileges"),
            required_evidence=(
                "cpi_edges",
                "account_privileges",
                "owner_checks",
            ),
            witness=_witness(
                "wit:cpi-escalation",
                "A CPI or inner instruction edge grants writable/signer power "
                "beyond declared callee constraints.",
                path_summary="cpi privilege escalation",
            ),
            fact_id_templates=("edge:*",),
        ),
        _common_rule(
            rule_id="common.arithmetic.bounds",
            name="Arithmetic, precision, and overflow bounds",
            category=ObligationCategory.ARITHMETIC,
            statement=(
                "Arithmetic on exact amounts stays within declared overflow, "
                "rounding, and precision bounds for each asset."
            ),
            formal_target=(
                "all amount expressions evaluate without overflow and within "
                "declared rounding mode"
            ),
            formal_target_kind=FormalTargetKind.SMT_LIB,
            semantic_preconditions=("asset_effects", "arithmetic_model"),
            required_evidence=(
                "exact_amounts",
                "decimals",
                "overflow_policy",
            ),
            witness=_witness(
                "wit:arithmetic-overflow",
                "An amount computation overflows, underflows, or violates the "
                "declared rounding/precision policy.",
            ),
            fact_id_templates=("effect:*",),
        ),
        _common_rule(
            rule_id="common.upgrade.authority",
            name="Upgrade and proxy authority invariants",
            category=ObligationCategory.UPGRADE,
            statement=(
                "Code or implementation epochs change only under the declared "
                "upgrade authority and within the declared upgrade policy."
            ),
            formal_target=(
                "code_epoch_change implies authorized_upgrade(authority, policy)"
            ),
            formal_target_kind=FormalTargetKind.FOL,
            semantic_preconditions=("code_epoch", "upgrade_authority"),
            required_evidence=(
                "code_epoch",
                "upgrade_authority",
                "proxy_binding",
            ),
            witness=_witness(
                "wit:upgrade-capture",
                "A code or proxy epoch changes without the declared upgrade "
                "authority or outside the upgrade policy.",
            ),
            trusted_assumptions=("upgrade.authority_not_compromised",),
            fact_id_templates=("epoch:*",),
        ),
        _common_rule(
            rule_id="common.oracle.freshness",
            name="Oracle freshness and manipulation bounds",
            category=ObligationCategory.ORACLE_FRESHNESS,
            statement=(
                "Price or oracle inputs used by effects are within the declared "
                "freshness window and manipulation bounds."
            ),
            formal_target=(
                "oracle_read r used by effect e implies fresh(r, window) and "
                "within_bounds(r)"
            ),
            formal_target_kind=FormalTargetKind.SMT_LIB,
            semantic_preconditions=("oracle_inputs", "asset_effects"),
            required_evidence=(
                "oracle_observation",
                "freshness_window",
                "manipulation_bounds",
            ),
            witness=_witness(
                "wit:stale-oracle",
                "An effect consumes an oracle input outside the freshness "
                "window or beyond manipulation bounds.",
            ),
            trusted_assumptions=("oracle.feed_integrity",),
            unsupported_fallback=UnsupportedFallback.INCONCLUSIVE,
            fact_id_templates=("oracle:*", "effect:*"),
        ),
        _common_rule(
            rule_id="common.intent.effect_equality",
            name="Intent and effect equality",
            category=ObligationCategory.INTENT_EFFECT_EQUALITY,
            statement=(
                "Observed or simulated effects equal the displayed user intent "
                "for asset, amount, counterparty, and call parameters."
            ),
            formal_target="effects(candidate) = expected_effects(intent)",
            formal_target_kind=FormalTargetKind.DETERMINISTIC,
            semantic_preconditions=("asset_effects", "intent_binding"),
            required_evidence=(
                "unsigned_intent",
                "ordered_effects",
                "expected_effects",
            ),
            witness=_witness(
                "wit:intent-mismatch",
                "Simulated or observed effects diverge from the displayed "
                "unsigned intent parameters.",
            ),
            fact_id_templates=("effect:*", "intent:*"),
        ),
        _common_rule(
            rule_id="common.timelock.workflow",
            name="Timelock, expiry, and finality workflow safety",
            category=ObligationCategory.TIMELOCK,
            statement=(
                "Timelocked or expiry-gated transitions fire only when the "
                "declared time/finality conditions hold."
            ),
            formal_target=(
                "transition t enabled iff timelock_satisfied(t) and "
                "not_expired(t)"
            ),
            formal_target_kind=FormalTargetKind.TEMPORAL,
            semantic_preconditions=("workflow_time", "control_flow"),
            required_evidence=(
                "timelock_condition",
                "validity_window",
                "finality_status",
            ),
            witness=_witness(
                "wit:timelock-bypass",
                "A transition executes before its timelock matures or after "
                "expiry/finality conditions fail.",
            ),
            fact_id_templates=("edge:*", "epoch:*"),
        ),
        _common_rule(
            rule_id="common.resource.bounds",
            name="Resource and denial-of-service bounds",
            category=ObligationCategory.RESOURCE_BOUNDS,
            statement=(
                "Execution respects declared gas, compute unit, stack, account, "
                "and size resource bounds; unbounded loops or allocations are "
                "rejected."
            ),
            formal_target=(
                "resource_usage(path) <= declared_bounds(path) for all paths"
            ),
            formal_target_kind=FormalTargetKind.MONITOR,
            semantic_preconditions=("resource_model", "control_flow"),
            required_evidence=(
                "resource_bounds",
                "control_graph",
                "loop_bounds",
            ),
            witness=_witness(
                "wit:resource-exhaustion",
                "A control path exceeds declared gas/compute/stack/size bounds "
                "or contains an unbounded resource consumer.",
            ),
            unsupported_fallback=UnsupportedFallback.INCONCLUSIVE,
            fact_id_templates=("edge:*", "bound:*"),
        ),
    )


def common_rule_by_id(rule_id: str) -> SecurityRule:
    """Return a common rule by id or fail closed."""

    rid = _identifier(rule_id, "rule_id")
    for rule in common_security_rules():
        if rule.rule_id == rid:
            return rule
    raise CryptoIRValidationError(f"unknown common security rule: {rid}")


def common_rules_by_category(
    category: ObligationCategory | str,
) -> tuple[SecurityRule, ...]:
    """Return common rules in *category*."""

    cat = _enum(ObligationCategory, category, "category")
    return tuple(rule for rule in common_security_rules() if rule.category is cat)


def iter_rule_ids(rules: Iterable[SecurityRule]) -> tuple[str, ...]:
    """Deterministic sorted rule ids for catalogs and tests."""

    return tuple(sorted({rule.rule_id for rule in rules}))


__all__ = [
    "CRYPTO_IR_SECURITY_RULES_DOMAIN",
    "CRYPTO_IR_SECURITY_RULES_SCHEMA_VERSION",
    "SECURITY_RULE_PACK_VERSION",
    "ApplicabilityStatus",
    "FormalTargetKind",
    "ObligationCategory",
    "ProofObligation",
    "RuleApplicability",
    "SecurityRule",
    "UnsupportedFallback",
    "ViolationWitness",
    "admit_rule",
    "assert_not_universal_secure",
    "common_rule_by_id",
    "common_rules_by_category",
    "common_security_rules",
    "evaluate_rule_applicability",
    "iter_rule_ids",
    "name_security_conclusions",
]
