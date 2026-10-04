"""Explicit compliance rules for sanctions, ownership, counterparties, and risk.

CRYPTOIR-G430 owns the rule surface that exposure traversal and formalization
consume.  Rules are versioned, explainable, and never elevate bounded-indirect
exposure or heuristics into designation authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.crypto_ir.identity import crypto_ir_identity
from ipfs_datasets_py.logic.crypto_ir.provenance import AuthorityKind
from ipfs_datasets_py.logic.crypto_ir.schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ipfs_datasets_py.logic.crypto_ir.verdicts import SanctionsMatchLevel
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.provenance import thaw_json

from .exposure import (
    BoundedExposure,
    ExposureVerdict,
)
from .models import (
    CRYPTO_IR_COMPLIANCE_DOMAIN,
    AssociationEvidence,
    ComplianceModelError,
    OwnershipEvidence,
    SanctionsPolicyOutcome,
    SanctionsSnapshot,
    _digest,
    _identifier,
    _instant,
    _known,
    _mapping,
    _text,
)


COMPLIANCE_RULE_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-rule@1.0.0"
)
COMPLIANCE_RULE_SET_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-rule-set@1.0.0"
)


class ComplianceRuleError(ComplianceModelError):
    """Raised when a compliance rule or evaluation input is malformed."""


class ComplianceRuleKind(str, Enum):
    """Closed set of executable compliance rule families."""

    SANCTIONS_EXACT = "sanctions_exact"
    OWNERSHIP = "ownership"
    DIRECT_COUNTERPARTY = "direct_counterparty"
    BOUNDED_INDIRECT_EXPOSURE = "bounded_indirect_exposure"
    FRESHNESS = "freshness"
    RISK_POLICY = "risk_policy"
    COMPLETENESS = "completeness"
    HEURISTIC_SIGNAL = "heuristic_signal"


class CompliancePredicate(str, Enum):
    """Named predicates rules may assert; mirrors plan §7.4."""

    LISTED_IDENTIFIER = "ListedIdentifier"
    DESIGNATED_PARTY = "DesignatedParty"
    OWNED_AT_LEAST = "OwnedAtLeast"
    DIRECT_COUNTERPARTY = "DirectCounterparty"
    OBSERVED_FLOW = "ObservedFlow"
    BOUNDED_EXPOSURE = "BoundedExposure"
    EVIDENCE_FRESH = "EvidenceFresh"
    REQUIRES_REVIEW = "RequiresReview"
    FORBIDDEN = "Forbidden"
    COMPLETENESS_FRONTIER = "CompletenessFrontier"


def _enum(enum_type: type[Any], value: Any, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ComplianceRuleError(f"unsupported {name}: {value!r}") from exc


def _outcome(value: Any, name: str = "outcome") -> SanctionsPolicyOutcome:
    return _enum(SanctionsPolicyOutcome, value, name)


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ComplianceRuleError(f"{name} must be a non-negative int")
    return value


def _ids(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ComplianceRuleError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise ComplianceRuleError(f"{name} values must be unique")
    return result


# Predicates that must never be used to mint designation authority.
_NON_DESIGNATING_KINDS: Final[frozenset[ComplianceRuleKind]] = frozenset(
    {
        ComplianceRuleKind.BOUNDED_INDIRECT_EXPOSURE,
        ComplianceRuleKind.HEURISTIC_SIGNAL,
        ComplianceRuleKind.RISK_POLICY,
        ComplianceRuleKind.COMPLETENESS,
        ComplianceRuleKind.FRESHNESS,
    }
)


@dataclass(frozen=True, slots=True)
class ComplianceRule:
    """One explicit, versioned compliance rule.

    ``elevates_to_designation`` is always False for indirect and heuristic
    kinds; construction refuses any attempt to set it True for those families.
    """

    rule_id: str
    kind: ComplianceRuleKind
    predicate: CompliancePredicate
    outcome: SanctionsPolicyOutcome
    reason_code: str
    match_level: SanctionsMatchLevel | None = None
    priority: int = 100
    enabled: bool = True
    description: str = ""
    max_snapshot_age_seconds: int | None = None
    ownership_threshold_basis_points: int | None = None
    requires_completeness: bool = False
    elevates_to_designation: bool = False
    program_ids: tuple[str, ...] = ()
    jurisdiction_codes: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COMPLIANCE_RULE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "kind", _enum(ComplianceRuleKind, self.kind, "kind"))
        object.__setattr__(
            self, "predicate", _enum(CompliancePredicate, self.predicate, "predicate")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome, "outcome"))
        object.__setattr__(
            self, "reason_code", _identifier(self.reason_code, "reason_code")
        )
        if self.match_level is not None:
            object.__setattr__(
                self,
                "match_level",
                _enum(SanctionsMatchLevel, self.match_level, "match_level"),
            )
        object.__setattr__(self, "priority", _non_negative_int(self.priority, "priority"))
        if type(self.enabled) is not bool:
            raise ComplianceRuleError("enabled must be a boolean")
        object.__setattr__(
            self, "description", _text(self.description, "description", allow_empty=True)
        )
        if self.max_snapshot_age_seconds is not None:
            object.__setattr__(
                self,
                "max_snapshot_age_seconds",
                _non_negative_int(
                    self.max_snapshot_age_seconds, "max_snapshot_age_seconds"
                ),
            )
        if self.ownership_threshold_basis_points is not None:
            value = _non_negative_int(
                self.ownership_threshold_basis_points,
                "ownership_threshold_basis_points",
            )
            if value > 10_000:
                raise ComplianceRuleError(
                    "ownership_threshold_basis_points must be in 0..10000"
                )
            object.__setattr__(self, "ownership_threshold_basis_points", value)
        if type(self.requires_completeness) is not bool:
            raise ComplianceRuleError("requires_completeness must be a boolean")
        if type(self.elevates_to_designation) is not bool:
            raise ComplianceRuleError("elevates_to_designation must be a boolean")
        if self.kind in _NON_DESIGNATING_KINDS and self.elevates_to_designation:
            raise ComplianceRuleError(
                f"{self.kind.value} rules must never elevate to designation"
            )
        # Direct sanctions exact may hard-deny but still does not *create* a
        # designation — it applies an existing list fact.
        if self.elevates_to_designation:
            raise ComplianceRuleError(
                "compliance rules never mint designation authority"
            )
        object.__setattr__(self, "program_ids", _ids(self.program_ids, "program_ids"))
        object.__setattr__(
            self, "jurisdiction_codes", _ids(self.jurisdiction_codes, "jurisdiction_codes")
        )
        if not isinstance(self.attributes, Mapping):
            raise ComplianceRuleError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))
        if self.schema_version != COMPLIANCE_RULE_SCHEMA_VERSION:
            raise ComplianceRuleError(
                f"unsupported rule schema: {self.schema_version}"
            )
        self._assert_kind_predicate_coherence()

    def _assert_kind_predicate_coherence(self) -> None:
        expected: Mapping[ComplianceRuleKind, frozenset[CompliancePredicate]] = {
            ComplianceRuleKind.SANCTIONS_EXACT: frozenset(
                {
                    CompliancePredicate.LISTED_IDENTIFIER,
                    CompliancePredicate.DESIGNATED_PARTY,
                    CompliancePredicate.FORBIDDEN,
                }
            ),
            ComplianceRuleKind.OWNERSHIP: frozenset(
                {CompliancePredicate.OWNED_AT_LEAST, CompliancePredicate.FORBIDDEN}
            ),
            ComplianceRuleKind.DIRECT_COUNTERPARTY: frozenset(
                {
                    CompliancePredicate.DIRECT_COUNTERPARTY,
                    CompliancePredicate.OBSERVED_FLOW,
                    CompliancePredicate.FORBIDDEN,
                    CompliancePredicate.REQUIRES_REVIEW,
                }
            ),
            ComplianceRuleKind.BOUNDED_INDIRECT_EXPOSURE: frozenset(
                {
                    CompliancePredicate.BOUNDED_EXPOSURE,
                    CompliancePredicate.REQUIRES_REVIEW,
                    CompliancePredicate.FORBIDDEN,
                }
            ),
            ComplianceRuleKind.FRESHNESS: frozenset(
                {CompliancePredicate.EVIDENCE_FRESH}
            ),
            ComplianceRuleKind.RISK_POLICY: frozenset(
                {
                    CompliancePredicate.REQUIRES_REVIEW,
                    CompliancePredicate.FORBIDDEN,
                    CompliancePredicate.BOUNDED_EXPOSURE,
                }
            ),
            ComplianceRuleKind.COMPLETENESS: frozenset(
                {CompliancePredicate.COMPLETENESS_FRONTIER}
            ),
            ComplianceRuleKind.HEURISTIC_SIGNAL: frozenset(
                {CompliancePredicate.REQUIRES_REVIEW}
            ),
        }
        allowed = expected[self.kind]
        if self.predicate not in allowed:
            raise ComplianceRuleError(
                f"predicate {self.predicate.value} incompatible with kind "
                f"{self.kind.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(dict(self.attributes)),
            "description": self.description,
            "elevates_to_designation": self.elevates_to_designation,
            "enabled": self.enabled,
            "jurisdiction_codes": list(self.jurisdiction_codes),
            "kind": self.kind.value,
            "match_level": None if self.match_level is None else self.match_level.value,
            "max_snapshot_age_seconds": self.max_snapshot_age_seconds,
            "outcome": self.outcome.value,
            "ownership_threshold_basis_points": self.ownership_threshold_basis_points,
            "predicate": self.predicate.value,
            "priority": self.priority,
            "program_ids": list(self.program_ids),
            "reason_code": self.reason_code,
            "requires_completeness": self.requires_completeness,
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceRule":
        value = _mapping(value, "ComplianceRule")
        fields = frozenset(
            {
                "rule_id",
                "kind",
                "predicate",
                "outcome",
                "reason_code",
                "match_level",
                "priority",
                "enabled",
                "description",
                "max_snapshot_age_seconds",
                "ownership_threshold_basis_points",
                "requires_completeness",
                "elevates_to_designation",
                "program_ids",
                "jurisdiction_codes",
                "attributes",
                "schema_version",
            }
        )
        _known(value, fields, "ComplianceRule")
        match_level = value.get("match_level")
        return cls(
            rule_id=value.get("rule_id", ""),
            kind=value.get("kind", ""),
            predicate=value.get("predicate", ""),
            outcome=value.get("outcome", ""),
            reason_code=value.get("reason_code", ""),
            match_level=None if match_level in (None, "") else match_level,
            priority=value.get("priority", 100),
            enabled=bool(value.get("enabled", True)),
            description=value.get("description", ""),
            max_snapshot_age_seconds=value.get("max_snapshot_age_seconds"),
            ownership_threshold_basis_points=value.get(
                "ownership_threshold_basis_points"
            ),
            requires_completeness=bool(value.get("requires_completeness", False)),
            elevates_to_designation=bool(value.get("elevates_to_designation", False)),
            program_ids=tuple(value.get("program_ids", ())),
            jurisdiction_codes=tuple(value.get("jurisdiction_codes", ())),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", COMPLIANCE_RULE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class RuleHit:
    """Explainable firing of one rule against supplied evidence."""

    rule_id: str
    kind: ComplianceRuleKind
    predicate: CompliancePredicate
    outcome: SanctionsPolicyOutcome
    reason_code: str
    match_level: SanctionsMatchLevel | None = None
    evidence_ids: tuple[str, ...] = ()
    path_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "kind", _enum(ComplianceRuleKind, self.kind, "kind"))
        object.__setattr__(
            self, "predicate", _enum(CompliancePredicate, self.predicate, "predicate")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome))
        object.__setattr__(
            self, "reason_code", _identifier(self.reason_code, "reason_code")
        )
        if self.match_level is not None:
            object.__setattr__(
                self,
                "match_level",
                _enum(SanctionsMatchLevel, self.match_level, "match_level"),
            )
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "path_ids", _ids(self.path_ids, "path_ids"))
        object.__setattr__(
            self, "notes", tuple(_text(n, "notes") for n in self.notes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ids": list(self.evidence_ids),
            "kind": self.kind.value,
            "match_level": None if self.match_level is None else self.match_level.value,
            "notes": list(self.notes),
            "outcome": self.outcome.value,
            "path_ids": list(self.path_ids),
            "predicate": self.predicate.value,
            "reason_code": self.reason_code,
            "rule_id": self.rule_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuleHit":
        value = _mapping(value, "RuleHit")
        match_level = value.get("match_level")
        return cls(
            rule_id=value.get("rule_id", ""),
            kind=value.get("kind", ""),
            predicate=value.get("predicate", ""),
            outcome=value.get("outcome", ""),
            reason_code=value.get("reason_code", ""),
            match_level=None if match_level in (None, "") else match_level,
            evidence_ids=tuple(value.get("evidence_ids", ())),
            path_ids=tuple(value.get("path_ids", ())),
            notes=tuple(value.get("notes", ())),
        )


# Severity for combining outcomes (higher wins for fail-closed combination).
_OUTCOME_SEVERITY: Final[Mapping[SanctionsPolicyOutcome, int]] = {
    SanctionsPolicyOutcome.ALLOW: 0,
    SanctionsPolicyOutcome.REVIEW: 1,
    SanctionsPolicyOutcome.INCONCLUSIVE: 2,
    SanctionsPolicyOutcome.STALE: 3,
    SanctionsPolicyOutcome.ERROR: 4,
    SanctionsPolicyOutcome.DENY: 5,
}


@dataclass(frozen=True, slots=True)
class ComplianceRuleSet:
    """Ordered collection of compliance rules with a canonical rules digest."""

    rule_set_id: str
    revision: str
    rules: tuple[ComplianceRule, ...]
    outcome_precedence: tuple[SanctionsPolicyOutcome, ...] = (
        SanctionsPolicyOutcome.ALLOW,
        SanctionsPolicyOutcome.REVIEW,
        SanctionsPolicyOutcome.INCONCLUSIVE,
        SanctionsPolicyOutcome.STALE,
        SanctionsPolicyOutcome.ERROR,
        SanctionsPolicyOutcome.DENY,
    )
    schema_version: str = COMPLIANCE_RULE_SET_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rule_set_id", _identifier(self.rule_set_id, "rule_set_id")
        )
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        rules = tuple(
            item
            if isinstance(item, ComplianceRule)
            else ComplianceRule.from_dict(_mapping(item, "rules"))
            for item in self.rules
        )
        if not rules:
            raise ComplianceRuleError("rules must not be empty")
        rule_ids = [r.rule_id for r in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ComplianceRuleError("rule_id values must be unique")
        object.__setattr__(self, "rules", rules)
        precedence = tuple(
            _outcome(item, "outcome_precedence") for item in self.outcome_precedence
        )
        if len(precedence) != len(set(precedence)):
            raise ComplianceRuleError("outcome_precedence values must be unique")
        if set(precedence) != set(SanctionsPolicyOutcome):
            raise ComplianceRuleError(
                "outcome_precedence must list every SanctionsPolicyOutcome"
            )
        object.__setattr__(self, "outcome_precedence", precedence)
        if self.schema_version != COMPLIANCE_RULE_SET_SCHEMA_VERSION:
            raise ComplianceRuleError(
                f"unsupported rule set schema: {self.schema_version}"
            )

    @property
    def rules_digest(self) -> str:
        payload = {
            "outcome_precedence": [o.value for o in self.outcome_precedence],
            "revision": self.revision,
            "rule_set_id": self.rule_set_id,
            "rules": [r.to_dict() for r in self.rules],
            "schema_version": self.schema_version,
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.rule-set",
        )

    def enabled_rules(self) -> tuple[ComplianceRule, ...]:
        return tuple(
            sorted(
                (r for r in self.rules if r.enabled),
                key=lambda r: (r.priority, r.rule_id),
            )
        )

    def combine_outcomes(
        self, outcomes: Sequence[SanctionsPolicyOutcome]
    ) -> SanctionsPolicyOutcome:
        if not outcomes:
            return SanctionsPolicyOutcome.ALLOW
        # Prefer severity; break ties by later position in outcome_precedence.
        rank = {outcome: index for index, outcome in enumerate(self.outcome_precedence)}
        return max(
            outcomes,
            key=lambda o: (_OUTCOME_SEVERITY.get(o, 0), rank.get(o, 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_precedence": [o.value for o in self.outcome_precedence],
            "revision": self.revision,
            "rule_set_id": self.rule_set_id,
            "rules": [r.to_dict() for r in self.rules],
            "rules_digest": self.rules_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceRuleSet":
        value = _mapping(value, "ComplianceRuleSet")
        fields = frozenset(
            {
                "rule_set_id",
                "revision",
                "rules",
                "outcome_precedence",
                "schema_version",
                "rules_digest",
            }
        )
        _known(value, fields, "ComplianceRuleSet")
        return cls(
            rule_set_id=value.get("rule_set_id", ""),
            revision=value.get("revision", ""),
            rules=tuple(
                ComplianceRule.from_dict(item) for item in value.get("rules", ())
            ),
            outcome_precedence=tuple(
                value.get(
                    "outcome_precedence",
                    (
                        SanctionsPolicyOutcome.ALLOW.value,
                        SanctionsPolicyOutcome.REVIEW.value,
                        SanctionsPolicyOutcome.INCONCLUSIVE.value,
                        SanctionsPolicyOutcome.STALE.value,
                        SanctionsPolicyOutcome.ERROR.value,
                        SanctionsPolicyOutcome.DENY.value,
                    ),
                )
            ),
            schema_version=value.get(
                "schema_version", COMPLIANCE_RULE_SET_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class RuleEvaluationResult:
    """Deterministic evaluation of a rule set against exposure and evidence."""

    result_id: str
    rule_set_id: str
    rule_set_revision: str
    rules_digest: str
    outcome: SanctionsPolicyOutcome
    hits: tuple[RuleHit, ...]
    reason_codes: tuple[str, ...]
    declares_designation: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "rule_set_id",
            "rule_set_revision",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "rules_digest", _digest(self.rules_digest, "rules_digest")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome))
        hits = tuple(
            item if isinstance(item, RuleHit) else RuleHit.from_dict(_mapping(item, "hits"))
            for item in self.hits
        )
        object.__setattr__(self, "hits", hits)
        codes = tuple(_identifier(c, "reason_codes") for c in self.reason_codes)
        if len(codes) != len(set(codes)):
            raise ComplianceRuleError("reason_codes must be unique")
        object.__setattr__(self, "reason_codes", codes)
        if type(self.declares_designation) is not bool:
            raise ComplianceRuleError("declares_designation must be a boolean")
        if self.declares_designation:
            raise ComplianceRuleError(
                "rule evaluation must never declare designation"
            )
        if not isinstance(self.attributes, Mapping):
            raise ComplianceRuleError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(dict(self.attributes)),
            "declares_designation": self.declares_designation,
            "hits": [h.to_dict() for h in self.hits],
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "result_id": self.result_id,
            "rule_set_id": self.rule_set_id,
            "rule_set_revision": self.rule_set_revision,
            "rules_digest": self.rules_digest,
        }


def default_compliance_rules(
    *,
    indirect_outcome: SanctionsPolicyOutcome = SanctionsPolicyOutcome.REVIEW,
    max_snapshot_age_seconds: int = 86_400,
    ownership_threshold_basis_points: int = 5_000,
) -> tuple[ComplianceRule, ...]:
    """Reviewed baseline rules for tests and offline fixtures.

    Not a legal policy.  Production deployments must supply jurisdiction-
    specific rules and approvals.
    """

    if indirect_outcome not in (
        SanctionsPolicyOutcome.REVIEW,
        SanctionsPolicyOutcome.DENY,
    ):
        raise ComplianceRuleError("indirect_outcome must be REVIEW or DENY")
    return (
        ComplianceRule(
            rule_id="rule:sanctions-exact-identifier",
            kind=ComplianceRuleKind.SANCTIONS_EXACT,
            predicate=CompliancePredicate.LISTED_IDENTIFIER,
            outcome=SanctionsPolicyOutcome.DENY,
            reason_code="exact_listed_identifier",
            match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
            priority=10,
            description="Applicable exact listed digital-currency identifier hard-denies.",
        ),
        ComplianceRule(
            rule_id="rule:sanctions-exact-party",
            kind=ComplianceRuleKind.SANCTIONS_EXACT,
            predicate=CompliancePredicate.DESIGNATED_PARTY,
            outcome=SanctionsPolicyOutcome.DENY,
            reason_code="named_designated_party",
            match_level=SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
            priority=20,
            description="Named designated party under effective list facts hard-denies.",
        ),
        ComplianceRule(
            rule_id="rule:ownership-threshold",
            kind=ComplianceRuleKind.OWNERSHIP,
            predicate=CompliancePredicate.OWNED_AT_LEAST,
            outcome=SanctionsPolicyOutcome.DENY,
            reason_code="owned_entity_threshold_met",
            match_level=SanctionsMatchLevel.OWNED_ENTITY,
            priority=30,
            ownership_threshold_basis_points=ownership_threshold_basis_points,
            description="Evidence-backed ownership at or above policy threshold.",
        ),
        ComplianceRule(
            rule_id="rule:direct-counterparty",
            kind=ComplianceRuleKind.DIRECT_COUNTERPARTY,
            predicate=CompliancePredicate.DIRECT_COUNTERPARTY,
            outcome=SanctionsPolicyOutcome.DENY,
            reason_code="direct_counterparty_hit",
            match_level=SanctionsMatchLevel.DIRECT_ASSOCIATION,
            priority=40,
            description="Direct transaction counterparty of a listed target.",
        ),
        ComplianceRule(
            rule_id="rule:bounded-indirect-exposure",
            kind=ComplianceRuleKind.BOUNDED_INDIRECT_EXPOSURE,
            predicate=CompliancePredicate.BOUNDED_EXPOSURE,
            outcome=indirect_outcome,
            reason_code="bounded_indirect_exposure",
            match_level=SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
            priority=50,
            description=(
                "Bounded-indirect path under path policy; never a designation."
            ),
            elevates_to_designation=False,
        ),
        ComplianceRule(
            rule_id="rule:freshness",
            kind=ComplianceRuleKind.FRESHNESS,
            predicate=CompliancePredicate.EVIDENCE_FRESH,
            outcome=SanctionsPolicyOutcome.STALE,
            reason_code="evidence_stale",
            priority=5,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            description="Stale list or graph evidence fails closed.",
        ),
        ComplianceRule(
            rule_id="rule:completeness-frontier",
            kind=ComplianceRuleKind.COMPLETENESS,
            predicate=CompliancePredicate.COMPLETENESS_FRONTIER,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            reason_code="incomplete_frontier",
            priority=6,
            requires_completeness=True,
            description="Incomplete graph/list coverage cannot prove absence.",
        ),
        ComplianceRule(
            rule_id="rule:heuristic-signal",
            kind=ComplianceRuleKind.HEURISTIC_SIGNAL,
            predicate=CompliancePredicate.REQUIRES_REVIEW,
            outcome=SanctionsPolicyOutcome.REVIEW,
            reason_code="heuristic_association",
            match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
            priority=90,
            description="Heuristic signals prioritize review only.",
        ),
    )


def evaluate_compliance_rules(
    rule_set: ComplianceRuleSet,
    *,
    exposure: BoundedExposure | None = None,
    snapshot: SanctionsSnapshot | None = None,
    ownership_evidence: Sequence[OwnershipEvidence] = (),
    association_evidence: Sequence[AssociationEvidence] = (),
    at_time: str = "",
    snapshot_age_seconds: int | None = None,
    heuristic_signal: bool = False,
) -> RuleEvaluationResult:
    """Evaluate enabled rules against exposure and injected evidence.

    Pure and side-effect free.  Does not acquire lists, sign, broadcast, or
    claim a legal certification.
    """

    if not isinstance(rule_set, ComplianceRuleSet):
        raise ComplianceRuleError("rule_set must be a ComplianceRuleSet")
    if at_time:
        at_time = _instant(at_time, "at_time")
    hits: list[RuleHit] = []

    for rule in rule_set.enabled_rules():
        if rule.kind is ComplianceRuleKind.FRESHNESS:
            max_age = rule.max_snapshot_age_seconds
            if (
                max_age is not None
                and snapshot_age_seconds is not None
                and snapshot_age_seconds > max_age
            ):
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=rule.predicate,
                        outcome=rule.outcome,
                        reason_code=rule.reason_code,
                        notes=(f"age_seconds={snapshot_age_seconds}",),
                    )
                )
            continue

        if rule.kind is ComplianceRuleKind.COMPLETENESS:
            if exposure is None:
                continue
            if exposure.verdict is ExposureVerdict.INCOMPLETE_FRONTIER or (
                rule.requires_completeness
                and exposure.frontier is not None
                and not exposure.frontier.supports_absence_claim
                and not exposure.paths
            ):
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=rule.predicate,
                        outcome=rule.outcome,
                        reason_code=rule.reason_code,
                        notes=(
                            f"frontier={exposure.frontier.status.value if exposure.frontier else 'none'}",
                        ),
                    )
                )
            if exposure.truncated:
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=rule.predicate,
                        outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
                        reason_code="search_truncated",
                        notes=tuple(exposure.truncation_reasons),
                    )
                )
            continue

        if rule.kind is ComplianceRuleKind.SANCTIONS_EXACT:
            if exposure is not None and exposure.has_direct_hit:
                # depth-0 self-list or depth-1 direct path.
                direct_paths = tuple(
                    p.path_id
                    for p in exposure.paths
                    if p.is_direct or p.depth == 0
                )
                if rule.predicate in (
                    CompliancePredicate.LISTED_IDENTIFIER,
                    CompliancePredicate.FORBIDDEN,
                ):
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=rule.match_level,
                            path_ids=direct_paths,
                        )
                    )
            if (
                snapshot is not None
                and rule.predicate is CompliancePredicate.DESIGNATED_PARTY
            ):
                # Party-level evaluation requires association evidence of named party;
                # exact identifier paths are handled above.
                continue
            continue

        if rule.kind is ComplianceRuleKind.DIRECT_COUNTERPARTY:
            if exposure is not None:
                direct_paths = tuple(
                    p.path_id for p in exposure.paths if p.is_direct and p.depth == 1
                )
                if direct_paths:
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=rule.match_level,
                            path_ids=direct_paths,
                        )
                    )
            for evidence in association_evidence:
                if evidence.match_level is SanctionsMatchLevel.DIRECT_ASSOCIATION:
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=SanctionsMatchLevel.DIRECT_ASSOCIATION,
                            evidence_ids=(evidence.evidence_id,),
                        )
                    )
            continue

        if rule.kind is ComplianceRuleKind.BOUNDED_INDIRECT_EXPOSURE:
            if exposure is not None and exposure.has_indirect_exposure:
                indirect_paths = tuple(
                    p.path_id for p in exposure.paths if p.is_indirect
                )
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=rule.predicate,
                        outcome=rule.outcome,
                        reason_code=rule.reason_code,
                        match_level=SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
                        path_ids=indirect_paths,
                        notes=("does_not_declare_designation",),
                    )
                )
            for evidence in association_evidence:
                if (
                    evidence.match_level
                    is SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE
                ):
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
                            evidence_ids=(evidence.evidence_id,),
                            notes=("does_not_declare_designation",),
                        )
                    )
            continue

        if rule.kind is ComplianceRuleKind.OWNERSHIP:
            threshold = rule.ownership_threshold_basis_points
            if threshold is None:
                continue
            for evidence in ownership_evidence:
                if not evidence.complete:
                    continue
                if at_time and not evidence.is_effective_at(at_time):
                    continue
                total = sum(
                    interest.ownership_basis_points for interest in evidence.interests
                )
                if total >= threshold:
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=SanctionsMatchLevel.OWNED_ENTITY,
                            evidence_ids=(evidence.evidence_id,),
                            notes=(f"basis_points={total}",),
                        )
                    )
            continue

        if rule.kind is ComplianceRuleKind.HEURISTIC_SIGNAL:
            if heuristic_signal:
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=rule.predicate,
                        outcome=rule.outcome,
                        reason_code=rule.reason_code,
                        match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
                        notes=("heuristic_only",),
                    )
                )
            for evidence in association_evidence:
                if evidence.match_level is SanctionsMatchLevel.HEURISTIC_ASSOCIATION:
                    hits.append(
                        RuleHit(
                            rule_id=rule.rule_id,
                            kind=rule.kind,
                            predicate=rule.predicate,
                            outcome=rule.outcome,
                            reason_code=rule.reason_code,
                            match_level=SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
                            evidence_ids=(evidence.evidence_id,),
                            notes=("heuristic_only",),
                        )
                    )
            continue

        if rule.kind is ComplianceRuleKind.RISK_POLICY:
            if exposure is not None and exposure.verdict is ExposureVerdict.TRUNCATED:
                hits.append(
                    RuleHit(
                        rule_id=rule.rule_id,
                        kind=rule.kind,
                        predicate=CompliancePredicate.REQUIRES_REVIEW,
                        outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
                        reason_code="risk_policy_truncated",
                        notes=tuple(exposure.truncation_reasons),
                    )
                )
            continue

    outcomes = [hit.outcome for hit in hits]
    combined = rule_set.combine_outcomes(outcomes)
    material = "\x00".join(
        (
            rule_set.rule_set_id,
            rule_set.revision,
            rule_set.rules_digest,
            *(h.rule_id for h in hits),
            combined.value,
        )
    ).encode("utf-8")
    result_id = f"rule-eval:{hashlib.sha256(material).hexdigest()[:40]}"
    reason_codes = tuple(dict.fromkeys(h.reason_code for h in hits))
    return RuleEvaluationResult(
        result_id=result_id,
        rule_set_id=rule_set.rule_set_id,
        rule_set_revision=rule_set.revision,
        rules_digest=rule_set.rules_digest,
        outcome=combined,
        hits=tuple(hits),
        reason_codes=reason_codes,
        declares_designation=False,
        attributes={
            "hit_count": len(hits),
            "never_elevates_indirect_to_designation": True,
        },
    )


__all__ = [
    "COMPLIANCE_RULE_SCHEMA_VERSION",
    "COMPLIANCE_RULE_SET_SCHEMA_VERSION",
    "CompliancePredicate",
    "ComplianceRule",
    "ComplianceRuleError",
    "ComplianceRuleKind",
    "ComplianceRuleSet",
    "RuleEvaluationResult",
    "RuleHit",
    "default_compliance_rules",
    "evaluate_compliance_rules",
]
