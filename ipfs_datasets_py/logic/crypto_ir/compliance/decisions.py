"""Explainable compliance decision composition (CRYPTOIR-G440).

Combines direct-list, party/ownership, bounded-flow, freshness, license, and
uncertainty results deterministically into ``ALLOW``, ``DENY``, ``REVIEW``,
``INCONCLUSIVE``, ``STALE``, or ``ERROR`` outcomes.

This module owns decision composition only.  It does not:

* acquire sanctions lists or flow graphs;
* mint designations from heuristics or graph distance;
* authorize, sign, or broadcast transactions; or
* claim a legal certification.

A :class:`ComplianceDecision` records *both* the selected outcome and the
evidentiary boundary of that outcome (bound counterparties, list/graph/
entity/ownership/license/policy revisions, path evidence, bounds, freshness,
uncertainty, reasons, and expiry).  Heuristic evidence may request ``REVIEW``
but never creates designation authority and never alone produces ``ALLOW``.
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

from .models import (
    CRYPTO_IR_COMPLIANCE_DOMAIN,
    ComplianceModelError,
    SanctionsPolicyOutcome,
    _digest,
    _identifier,
    _instant,
    _known,
    _mapping,
    _text,
)


COMPLIANCE_DECISION_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-decision@1.0.0"
)
POLICY_COMBINER_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.policy-combiner@1.0.0"
)

# Fail-closed severity: higher always wins when combining factors so a
# permissive outcome cannot downgrade a harder one.
_OUTCOME_SEVERITY: Final[Mapping[SanctionsPolicyOutcome, int]] = {
    SanctionsPolicyOutcome.ALLOW: 0,
    SanctionsPolicyOutcome.REVIEW: 1,
    SanctionsPolicyOutcome.INCONCLUSIVE: 2,
    SanctionsPolicyOutcome.STALE: 3,
    SanctionsPolicyOutcome.ERROR: 4,
    SanctionsPolicyOutcome.DENY: 5,
}

# Default precedence order (index is tie-break when severities equal).
# Later entries win ties so ERROR/DENY beat softer outcomes at equal rank.
_DEFAULT_PRECEDENCE: Final[tuple[SanctionsPolicyOutcome, ...]] = (
    SanctionsPolicyOutcome.ALLOW,
    SanctionsPolicyOutcome.REVIEW,
    SanctionsPolicyOutcome.INCONCLUSIVE,
    SanctionsPolicyOutcome.STALE,
    SanctionsPolicyOutcome.ERROR,
    SanctionsPolicyOutcome.DENY,
)

# Evidence channels that cannot mint designation authority.
_NON_DESIGNATING_CHANNELS: Final[frozenset[str]] = frozenset(
    {
        "bounded_flow",
        "heuristic",
        "freshness",
        "uncertainty",
        "license",
    }
)

# Match levels that never create designation authority.
_HEURISTIC_LEVELS: Final[frozenset[SanctionsMatchLevel]] = frozenset(
    {
        SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
    }
)


class DecisionError(ComplianceModelError):
    """Raised when decision inputs, combination, or bindings are malformed."""


class EvidenceChannel(str, Enum):
    """Closed set of factor channels fed into the policy combiner."""

    DIRECT_LIST = "direct_list"
    PARTY_OWNERSHIP = "party_ownership"
    BOUNDED_FLOW = "bounded_flow"
    FRESHNESS = "freshness"
    LICENSE = "license"
    UNCERTAINTY = "uncertainty"
    HEURISTIC = "heuristic"


class AuthorityClaim(str, Enum):
    """What a factor is allowed to claim about authority elevation."""

    NONE = "none"
    DESIGNATION = "designation"
    ALLOW = "allow"
    REVIEW_ONLY = "review_only"


def _enum(enum_type: type[Any], value: Any, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"unsupported {name}: {value!r}") from exc


def _outcome(value: Any, name: str = "outcome") -> SanctionsPolicyOutcome:
    return _enum(SanctionsPolicyOutcome, value, name)


def _ids(values: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise DecisionError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if not allow_empty and not result:
        raise DecisionError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise DecisionError(f"{name} values must be unique")
    return result


def _texts(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise DecisionError(f"{name} must be a sequence")
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise DecisionError(f"{name} values must be unique")
    return result


def outcome_severity(outcome: SanctionsPolicyOutcome | str) -> int:
    """Return the fail-closed severity rank for a screening outcome."""

    return _OUTCOME_SEVERITY[_outcome(outcome)]


# ---------------------------------------------------------------------------
# Decision reasons and policy factors
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionReason:
    """One explainable reason contributing to a compliance decision.

    Reasons bind a stable code, the evidence channel, optional match level,
    evidence/path identifiers, and free-form notes.  They never elevate
    authority by themselves.
    """

    reason_id: str
    code: str
    channel: EvidenceChannel
    outcome: SanctionsPolicyOutcome
    match_level: SanctionsMatchLevel | None = None
    evidence_ids: tuple[str, ...] = ()
    path_ids: tuple[str, ...] = ()
    counterparty_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    machine_detail: str = ""
    human_detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason_id", _identifier(self.reason_id, "reason_id")
        )
        object.__setattr__(self, "code", _identifier(self.code, "code"))
        object.__setattr__(
            self, "channel", _enum(EvidenceChannel, self.channel, "channel")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome))
        if self.match_level is not None:
            object.__setattr__(
                self,
                "match_level",
                _enum(SanctionsMatchLevel, self.match_level, "match_level"),
            )
        object.__setattr__(
            self, "evidence_ids", _ids(self.evidence_ids, "evidence_ids")
        )
        object.__setattr__(self, "path_ids", _ids(self.path_ids, "path_ids"))
        object.__setattr__(
            self, "counterparty_ids", _ids(self.counterparty_ids, "counterparty_ids")
        )
        object.__setattr__(self, "notes", _texts(self.notes, "notes"))
        object.__setattr__(
            self,
            "machine_detail",
            _text(self.machine_detail, "machine_detail", allow_empty=True),
        )
        object.__setattr__(
            self,
            "human_detail",
            _text(self.human_detail, "human_detail", allow_empty=True),
        )

    @property
    def is_heuristic(self) -> bool:
        if self.channel is EvidenceChannel.HEURISTIC:
            return True
        return self.match_level in _HEURISTIC_LEVELS

    @property
    def may_declare_designation(self) -> bool:
        """Heuristic / bounded-flow channels never declare designation."""

        if self.channel.value in _NON_DESIGNATING_CHANNELS:
            return False
        if self.is_heuristic:
            return False
        return self.channel in (
            EvidenceChannel.DIRECT_LIST,
            EvidenceChannel.PARTY_OWNERSHIP,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.value,
            "code": self.code,
            "counterparty_ids": list(self.counterparty_ids),
            "evidence_ids": list(self.evidence_ids),
            "human_detail": self.human_detail,
            "is_heuristic": self.is_heuristic,
            "machine_detail": self.machine_detail,
            "match_level": (
                None if self.match_level is None else self.match_level.value
            ),
            "may_declare_designation": self.may_declare_designation,
            "notes": list(self.notes),
            "outcome": self.outcome.value,
            "path_ids": list(self.path_ids),
            "reason_id": self.reason_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DecisionReason":
        value = _mapping(value, "DecisionReason")
        fields = frozenset(
            {
                "reason_id",
                "code",
                "channel",
                "outcome",
                "match_level",
                "evidence_ids",
                "path_ids",
                "counterparty_ids",
                "notes",
                "machine_detail",
                "human_detail",
                "is_heuristic",
                "may_declare_designation",
            }
        )
        _known(value, fields, "DecisionReason")
        match_level = value.get("match_level")
        return cls(
            reason_id=value.get("reason_id", ""),
            code=value.get("code", ""),
            channel=value.get("channel", ""),
            outcome=value.get("outcome", ""),
            match_level=None if match_level in (None, "") else match_level,
            evidence_ids=tuple(value.get("evidence_ids", ())),
            path_ids=tuple(value.get("path_ids", ())),
            counterparty_ids=tuple(value.get("counterparty_ids", ())),
            notes=tuple(value.get("notes", ())),
            machine_detail=value.get("machine_detail", ""),
            human_detail=value.get("human_detail", ""),
        )


@dataclass(frozen=True, slots=True)
class PolicyFactor:
    """One channel result fed into deterministic policy combination.

    Factors carry an outcome, optional reasons, and an explicit authority
    claim.  Construction refuses illegal claims (e.g. heuristic → ALLOW or
    designation).
    """

    factor_id: str
    channel: EvidenceChannel
    outcome: SanctionsPolicyOutcome
    reasons: tuple[DecisionReason, ...] = ()
    authority_claim: AuthorityClaim = AuthorityClaim.NONE
    uncertainty: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "factor_id", _identifier(self.factor_id, "factor_id")
        )
        object.__setattr__(
            self, "channel", _enum(EvidenceChannel, self.channel, "channel")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome))
        reasons = tuple(
            item
            if isinstance(item, DecisionReason)
            else DecisionReason.from_dict(_mapping(item, "reasons"))
            for item in self.reasons
        )
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(
            self,
            "authority_claim",
            _enum(AuthorityClaim, self.authority_claim, "authority_claim"),
        )
        if type(self.uncertainty) is not bool:
            raise DecisionError("uncertainty must be a boolean")
        if not isinstance(self.attributes, Mapping):
            raise DecisionError("attributes must be a mapping")
        object.__setattr__(self, "attributes", dict(self.attributes))
        self._assert_authority_bounds()

    def _assert_authority_bounds(self) -> None:
        """Heuristic / non-designating channels cannot elevate authority."""

        heuristic = self.channel is EvidenceChannel.HEURISTIC or any(
            r.is_heuristic for r in self.reasons
        )
        if heuristic:
            if self.authority_claim is AuthorityClaim.DESIGNATION:
                raise DecisionError(
                    "heuristic evidence cannot claim designation authority"
                )
            if self.authority_claim is AuthorityClaim.ALLOW:
                raise DecisionError(
                    "heuristic evidence cannot claim allow authority"
                )
            if self.outcome is SanctionsPolicyOutcome.ALLOW and not any(
                r.channel is not EvidenceChannel.HEURISTIC and not r.is_heuristic
                for r in self.reasons
            ):
                # Pure heuristic factor may not alone yield ALLOW.
                if not self.reasons or all(r.is_heuristic for r in self.reasons):
                    raise DecisionError(
                        "heuristic evidence cannot alone produce ALLOW"
                    )
            if self.authority_claim is AuthorityClaim.NONE:
                object.__setattr__(
                    self, "authority_claim", AuthorityClaim.REVIEW_ONLY
                )
        if (
            self.channel.value in _NON_DESIGNATING_CHANNELS
            and self.authority_claim is AuthorityClaim.DESIGNATION
        ):
            raise DecisionError(
                f"channel {self.channel.value} cannot claim designation authority"
            )

    @property
    def is_heuristic(self) -> bool:
        return self.channel is EvidenceChannel.HEURISTIC or any(
            r.is_heuristic for r in self.reasons
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(dict(self.attributes)),
            "authority_claim": self.authority_claim.value,
            "channel": self.channel.value,
            "factor_id": self.factor_id,
            "is_heuristic": self.is_heuristic,
            "outcome": self.outcome.value,
            "reasons": [item.to_dict() for item in self.reasons],
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyFactor":
        value = _mapping(value, "PolicyFactor")
        fields = frozenset(
            {
                "factor_id",
                "channel",
                "outcome",
                "reasons",
                "authority_claim",
                "uncertainty",
                "attributes",
                "is_heuristic",
            }
        )
        _known(value, fields, "PolicyFactor")
        return cls(
            factor_id=value.get("factor_id", ""),
            channel=value.get("channel", ""),
            outcome=value.get("outcome", ""),
            reasons=tuple(
                DecisionReason.from_dict(item)
                for item in value.get("reasons", ())
            ),
            authority_claim=value.get("authority_claim", AuthorityClaim.NONE.value),
            uncertainty=bool(value.get("uncertainty", False)),
            attributes=value.get("attributes", {}),
        )


# ---------------------------------------------------------------------------
# Policy combiner
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyCombiner:
    """Deterministic combination of policy factors with fail-closed precedence.

    Precedence prevents permissive downgrade: the selected outcome is always
    at least as severe as every contributing factor under the configured
    severity lattice.  Tie-breaks use the explicit ``outcome_precedence``
    ordering (later = higher priority when severities are equal).
    """

    combiner_id: str
    revision: str
    outcome_precedence: tuple[SanctionsPolicyOutcome, ...] = _DEFAULT_PRECEDENCE
    refuse_permissive_downgrade: bool = True
    schema_version: str = POLICY_COMBINER_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "combiner_id", _identifier(self.combiner_id, "combiner_id")
        )
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        precedence = tuple(
            _outcome(item, "outcome_precedence") for item in self.outcome_precedence
        )
        if len(precedence) != len(set(precedence)):
            raise DecisionError("outcome_precedence values must be unique")
        if set(precedence) != set(SanctionsPolicyOutcome):
            raise DecisionError(
                "outcome_precedence must list every SanctionsPolicyOutcome exactly once"
            )
        object.__setattr__(self, "outcome_precedence", precedence)
        if type(self.refuse_permissive_downgrade) is not bool:
            raise DecisionError("refuse_permissive_downgrade must be a boolean")
        if self.schema_version != POLICY_COMBINER_SCHEMA_VERSION:
            raise DecisionError(
                f"unsupported policy combiner schema: {self.schema_version}"
            )

    @property
    def rules_digest(self) -> str:
        payload = {
            "combiner_id": self.combiner_id,
            "outcome_precedence": [o.value for o in self.outcome_precedence],
            "refuse_permissive_downgrade": self.refuse_permissive_downgrade,
            "revision": self.revision,
            "schema_version": self.schema_version,
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"

    def rank(self, outcome: SanctionsPolicyOutcome | str) -> tuple[int, int]:
        """Return ``(severity, precedence_index)`` for comparison."""

        value = _outcome(outcome)
        return (
            _OUTCOME_SEVERITY[value],
            list(self.outcome_precedence).index(value),
        )

    def combine(
        self, factors: Sequence[PolicyFactor]
    ) -> tuple[SanctionsPolicyOutcome, tuple[PolicyFactor, ...]]:
        """Combine factors deterministically.

        Returns the selected outcome and the ordered factors that contributed
        (all factors are retained for explanation; selection uses severity).
        Empty factors yield ``ALLOW`` only as a no-hit default — callers that
        require positive evidence must supply uncertainty factors instead.
        """

        normalized = tuple(
            item
            if isinstance(item, PolicyFactor)
            else PolicyFactor.from_dict(_mapping(item, "factors"))
            for item in factors
        )
        if not normalized:
            return SanctionsPolicyOutcome.ALLOW, ()

        # Pure-heuristic ALLOW is already refused at factor construction;
        # re-check combination cannot elevate heuristic-only to ALLOW.
        outcomes = [factor.outcome for factor in normalized]
        selected = max(outcomes, key=lambda o: self.rank(o))

        if self.refuse_permissive_downgrade:
            for factor in normalized:
                if self.rank(factor.outcome) > self.rank(selected):
                    raise DecisionError(
                        "permissive downgrade refused: "
                        f"{selected.value} would weaken {factor.outcome.value}"
                    )

        # Heuristic-only inputs cannot alone produce ALLOW after combination.
        non_heuristic = [
            f for f in normalized if not f.is_heuristic
        ]
        if selected is SanctionsPolicyOutcome.ALLOW and not non_heuristic:
            # Only heuristic factors present — force REVIEW.
            selected = SanctionsPolicyOutcome.REVIEW

        # Uncertainty without a harder hit fails closed to INCONCLUSIVE
        # when any factor marks uncertainty and selected would be ALLOW.
        if selected is SanctionsPolicyOutcome.ALLOW and any(
            f.uncertainty for f in normalized
        ):
            selected = SanctionsPolicyOutcome.INCONCLUSIVE

        return selected, normalized

    def assert_no_downgrade(
        self,
        prior: SanctionsPolicyOutcome | str,
        proposed: SanctionsPolicyOutcome | str,
    ) -> None:
        """Refuse replacing a harder prior outcome with a softer proposed one."""

        prior_o = _outcome(prior, "prior")
        proposed_o = _outcome(proposed, "proposed")
        if self.rank(proposed_o) < self.rank(prior_o):
            raise DecisionError(
                f"permissive downgrade refused: cannot replace {prior_o.value} "
                f"with {proposed_o.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "combiner_id": self.combiner_id,
            "outcome_precedence": [o.value for o in self.outcome_precedence],
            "refuse_permissive_downgrade": self.refuse_permissive_downgrade,
            "revision": self.revision,
            "rules_digest": self.rules_digest,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyCombiner":
        value = _mapping(value, "PolicyCombiner")
        fields = frozenset(
            {
                "combiner_id",
                "revision",
                "outcome_precedence",
                "refuse_permissive_downgrade",
                "schema_version",
                "rules_digest",
            }
        )
        _known(value, fields, "PolicyCombiner")
        return cls(
            combiner_id=value.get("combiner_id", ""),
            revision=value.get("revision", ""),
            outcome_precedence=tuple(
                value.get(
                    "outcome_precedence",
                    [o.value for o in _DEFAULT_PRECEDENCE],
                )
            ),
            refuse_permissive_downgrade=bool(
                value.get("refuse_permissive_downgrade", True)
            ),
            schema_version=value.get(
                "schema_version", POLICY_COMBINER_SCHEMA_VERSION
            ),
        )

    @classmethod
    def default(cls) -> "PolicyCombiner":
        """Standard fail-closed combiner for compliance decisions."""

        return cls(
            combiner_id="policy-combiner:default",
            revision="revision:1",
            outcome_precedence=_DEFAULT_PRECEDENCE,
            refuse_permissive_downgrade=True,
        )


# ---------------------------------------------------------------------------
# Evidence bindings and compliance decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceBindings:
    """Exact revisions and counterparties a decision is bound to.

    These fields define the *evidentiary boundary*: the decision is valid only
    for the listed counterparties under the listed list/graph/entity/
    ownership/license/policy revisions, path evidence, bounds, freshness, and
    expiry.  Substitution of any bound id invalidates the decision.
    """

    counterparty_ids: tuple[str, ...] = ()
    list_snapshot_id: str = ""
    list_revision: str = ""
    graph_snapshot_id: str = ""
    graph_digest: str = ""
    entity_ids: tuple[str, ...] = ()
    ownership_evidence_ids: tuple[str, ...] = ()
    license_ids: tuple[str, ...] = ()
    policy_id: str = ""
    policy_revision: str = ""
    policy_rules_digest: str = ""
    path_ids: tuple[str, ...] = ()
    bound_max_depth: int | None = None
    bound_max_nodes: int | None = None
    bound_max_edges: int | None = None
    freshness_checked_at: str = ""
    max_snapshot_age_seconds: int | None = None
    snapshot_age_seconds: int | None = None
    uncertainty_codes: tuple[str, ...] = ()
    effective_at: str = ""
    expires_at: str = ""
    subject_party_id: str = ""
    request_id: str = ""
    activity_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "counterparty_ids", _ids(self.counterparty_ids, "counterparty_ids")
        )
        for name in (
            "list_snapshot_id",
            "list_revision",
            "graph_snapshot_id",
            "graph_digest",
            "policy_id",
            "policy_revision",
            "subject_party_id",
            "request_id",
            "activity_id",
        ):
            raw = getattr(self, name)
            object.__setattr__(
                self,
                name,
                _text(raw, name, allow_empty=True) if raw else "",
            )
        if self.policy_rules_digest:
            object.__setattr__(
                self,
                "policy_rules_digest",
                _digest(self.policy_rules_digest, "policy_rules_digest"),
            )
        else:
            object.__setattr__(self, "policy_rules_digest", "")
        for name in (
            "entity_ids",
            "ownership_evidence_ids",
            "license_ids",
            "path_ids",
            "uncertainty_codes",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        for name in (
            "bound_max_depth",
            "bound_max_nodes",
            "bound_max_edges",
            "max_snapshot_age_seconds",
            "snapshot_age_seconds",
        ):
            value = getattr(self, name)
            if value is not None:
                if type(value) is not int or isinstance(value, bool) or value < 0:
                    raise DecisionError(f"{name} must be a non-negative int or None")
        for name in ("freshness_checked_at", "effective_at", "expires_at"):
            raw = getattr(self, name)
            object.__setattr__(
                self,
                name,
                _instant(raw, name, allow_empty=True) if raw else "",
            )
        if self.effective_at and self.expires_at:
            from .models import _parse_instant

            if _parse_instant(self.expires_at) <= _parse_instant(self.effective_at):
                raise DecisionError("expires_at must be later than effective_at")

    @property
    def is_fresh(self) -> bool:
        """True when age is within the configured maximum (if both set)."""

        if (
            self.max_snapshot_age_seconds is None
            or self.snapshot_age_seconds is None
        ):
            return True
        return self.snapshot_age_seconds <= self.max_snapshot_age_seconds

    @property
    def has_uncertainty(self) -> bool:
        return bool(self.uncertainty_codes)

    def binding_digest(self) -> str:
        """Canonical digest of the evidentiary boundary bindings."""

        digest = hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()
        return f"sha256:{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "bound_max_depth": self.bound_max_depth,
            "bound_max_edges": self.bound_max_edges,
            "bound_max_nodes": self.bound_max_nodes,
            "counterparty_ids": list(self.counterparty_ids),
            "effective_at": self.effective_at,
            "entity_ids": list(self.entity_ids),
            "expires_at": self.expires_at,
            "freshness_checked_at": self.freshness_checked_at,
            "graph_digest": self.graph_digest,
            "graph_snapshot_id": self.graph_snapshot_id,
            "has_uncertainty": self.has_uncertainty,
            "is_fresh": self.is_fresh,
            "license_ids": list(self.license_ids),
            "list_revision": self.list_revision,
            "list_snapshot_id": self.list_snapshot_id,
            "max_snapshot_age_seconds": self.max_snapshot_age_seconds,
            "ownership_evidence_ids": list(self.ownership_evidence_ids),
            "path_ids": list(self.path_ids),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "policy_rules_digest": self.policy_rules_digest,
            "request_id": self.request_id,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "subject_party_id": self.subject_party_id,
            "uncertainty_codes": list(self.uncertainty_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceBindings":
        value = _mapping(value, "EvidenceBindings")
        fields = frozenset(
            {
                "counterparty_ids",
                "list_snapshot_id",
                "list_revision",
                "graph_snapshot_id",
                "graph_digest",
                "entity_ids",
                "ownership_evidence_ids",
                "license_ids",
                "policy_id",
                "policy_revision",
                "policy_rules_digest",
                "path_ids",
                "bound_max_depth",
                "bound_max_nodes",
                "bound_max_edges",
                "freshness_checked_at",
                "max_snapshot_age_seconds",
                "snapshot_age_seconds",
                "uncertainty_codes",
                "effective_at",
                "expires_at",
                "subject_party_id",
                "request_id",
                "activity_id",
                "is_fresh",
                "has_uncertainty",
            }
        )
        _known(value, fields, "EvidenceBindings")
        return cls(
            counterparty_ids=tuple(value.get("counterparty_ids", ())),
            list_snapshot_id=value.get("list_snapshot_id", ""),
            list_revision=value.get("list_revision", ""),
            graph_snapshot_id=value.get("graph_snapshot_id", ""),
            graph_digest=value.get("graph_digest", ""),
            entity_ids=tuple(value.get("entity_ids", ())),
            ownership_evidence_ids=tuple(value.get("ownership_evidence_ids", ())),
            license_ids=tuple(value.get("license_ids", ())),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            policy_rules_digest=value.get("policy_rules_digest", ""),
            path_ids=tuple(value.get("path_ids", ())),
            bound_max_depth=value.get("bound_max_depth"),
            bound_max_nodes=value.get("bound_max_nodes"),
            bound_max_edges=value.get("bound_max_edges"),
            freshness_checked_at=value.get("freshness_checked_at", ""),
            max_snapshot_age_seconds=value.get("max_snapshot_age_seconds"),
            snapshot_age_seconds=value.get("snapshot_age_seconds"),
            uncertainty_codes=tuple(value.get("uncertainty_codes", ())),
            effective_at=value.get("effective_at", ""),
            expires_at=value.get("expires_at", ""),
            subject_party_id=value.get("subject_party_id", ""),
            request_id=value.get("request_id", ""),
            activity_id=value.get("activity_id", ""),
        )


@dataclass(frozen=True, slots=True)
class ComplianceDecision:
    """Explainable compliance decision with an explicit evidentiary boundary.

    A decision is a *result*, not transaction authorization and not a legal
    certification.  Only a current ``ALLOW`` under separate guard capability
    may permit automated use; this record alone never authorizes signing.
    """

    decision_id: str
    outcome: SanctionsPolicyOutcome
    reasons: tuple[DecisionReason, ...]
    factors: tuple[PolicyFactor, ...]
    bindings: EvidenceBindings
    combiner_id: str
    combiner_revision: str
    combiner_rules_digest: str
    declares_designation: bool = False
    heuristic_only: bool = False
    schema_version: str = COMPLIANCE_DECISION_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(self, "outcome", _outcome(self.outcome))
        reasons = tuple(
            item
            if isinstance(item, DecisionReason)
            else DecisionReason.from_dict(_mapping(item, "reasons"))
            for item in self.reasons
        )
        object.__setattr__(self, "reasons", reasons)
        factors = tuple(
            item
            if isinstance(item, PolicyFactor)
            else PolicyFactor.from_dict(_mapping(item, "factors"))
            for item in self.factors
        )
        object.__setattr__(self, "factors", factors)
        if not isinstance(self.bindings, EvidenceBindings):
            object.__setattr__(
                self,
                "bindings",
                EvidenceBindings.from_dict(_mapping(self.bindings, "bindings")),
            )
        for name in ("combiner_id", "combiner_revision"):
            object.__setattr__(
                self, name, _identifier(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "combiner_rules_digest",
            _digest(self.combiner_rules_digest, "combiner_rules_digest"),
        )
        for name in ("declares_designation", "heuristic_only"):
            if type(getattr(self, name)) is not bool:
                raise DecisionError(f"{name} must be a boolean")
        if self.schema_version != COMPLIANCE_DECISION_SCHEMA_VERSION:
            raise DecisionError(
                f"unsupported compliance decision schema: {self.schema_version}"
            )
        # Structural authority invariants.
        if self.declares_designation:
            raise DecisionError(
                "compliance decision composition never declares designation; "
                "designation authority remains with list evidence only"
            )
        if self.heuristic_only and self.outcome is SanctionsPolicyOutcome.ALLOW:
            raise DecisionError(
                "heuristic-only decisions cannot produce ALLOW"
            )
        if (
            self.heuristic_only
            and self.outcome is SanctionsPolicyOutcome.DENY
            and all(r.is_heuristic for r in self.reasons)
        ):
            # Pure heuristic cannot hard-deny as designation; REVIEW only.
            raise DecisionError(
                "heuristic-only evidence cannot alone produce DENY "
                "(use REVIEW for prioritization)"
            )

    @property
    def is_legal_certification(self) -> bool:
        """Screening/composition is never a legal certification."""

        return False

    def can_authorize_transaction(self) -> bool:
        """A compliance decision cannot cross into transaction authorization."""

        return False

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.code for r in self.reasons))

    @property
    def evidentiary_boundary_digest(self) -> str:
        return self.bindings.binding_digest()

    def _digest_payload(self) -> dict[str, Any]:
        """Stable payload used for content digests (no derived digest fields)."""

        return {
            "bindings": self.bindings.to_dict(),
            "can_authorize_transaction": self.can_authorize_transaction(),
            "combiner_id": self.combiner_id,
            "combiner_revision": self.combiner_revision,
            "combiner_rules_digest": self.combiner_rules_digest,
            "declares_designation": self.declares_designation,
            "decision_id": self.decision_id,
            "evidentiary_boundary_digest": self.evidentiary_boundary_digest,
            "factors": [item.to_dict() for item in self.factors],
            "heuristic_only": self.heuristic_only,
            "is_legal_certification": self.is_legal_certification,
            "outcome": self.outcome.value,
            "reason_codes": list(self.reason_codes),
            "reasons": [item.to_dict() for item in self.reasons],
            "schema_version": self.schema_version,
        }

    @property
    def content_digest(self) -> str:
        """Canonical content digest over the decision payload."""

        payload = self._digest_payload()
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.decision",
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self._digest_payload()
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceDecision":
        value = _mapping(value, "ComplianceDecision")
        fields = frozenset(
            {
                "decision_id",
                "outcome",
                "reasons",
                "factors",
                "bindings",
                "combiner_id",
                "combiner_revision",
                "combiner_rules_digest",
                "declares_designation",
                "heuristic_only",
                "schema_version",
                "content_digest",
                "evidentiary_boundary_digest",
                "reason_codes",
                "is_legal_certification",
                "can_authorize_transaction",
            }
        )
        _known(value, fields, "ComplianceDecision")
        return cls(
            decision_id=value.get("decision_id", ""),
            outcome=value.get("outcome", ""),
            reasons=tuple(
                DecisionReason.from_dict(item) for item in value.get("reasons", ())
            ),
            factors=tuple(
                PolicyFactor.from_dict(item) for item in value.get("factors", ())
            ),
            bindings=EvidenceBindings.from_dict(value.get("bindings", {})),
            combiner_id=value.get("combiner_id", ""),
            combiner_revision=value.get("combiner_revision", ""),
            combiner_rules_digest=value.get("combiner_rules_digest", ""),
            declares_designation=bool(value.get("declares_designation", False)),
            heuristic_only=bool(value.get("heuristic_only", False)),
            schema_version=value.get(
                "schema_version", COMPLIANCE_DECISION_SCHEMA_VERSION
            ),
        )


def _decision_id(
    *,
    request_id: str,
    combiner: PolicyCombiner,
    outcome: SanctionsPolicyOutcome,
    binding_digest: str,
) -> str:
    material = "\x00".join(
        (
            request_id or "request:none",
            combiner.combiner_id,
            combiner.revision,
            combiner.rules_digest,
            outcome.value,
            binding_digest,
        )
    ).encode("utf-8")
    return f"compliance-decision:{hashlib.sha256(material).hexdigest()}"


def emit_compliance_decision(
    factors: Sequence[PolicyFactor],
    bindings: EvidenceBindings,
    *,
    combiner: PolicyCombiner | None = None,
    force_stale: bool = False,
    force_error: bool = False,
) -> ComplianceDecision:
    """Combine factors into an explainable, boundary-bound compliance decision.

    Freshness: when bindings report stale evidence, the outcome is forced to
    ``STALE`` (or kept if already harder).  Uncertainty codes without a harder
    hit yield ``INCONCLUSIVE``.  Heuristic-only inputs never produce ``ALLOW``
    or designation.
    """

    if not isinstance(bindings, EvidenceBindings):
        raise DecisionError("bindings must be EvidenceBindings")
    combiner = combiner if combiner is not None else PolicyCombiner.default()
    if not isinstance(combiner, PolicyCombiner):
        raise DecisionError("combiner must be a PolicyCombiner")

    selected, normalized = combiner.combine(factors)
    reasons = tuple(r for factor in normalized for r in factor.reasons)
    heuristic_only = bool(normalized) and all(f.is_heuristic for f in normalized)

    if force_error:
        selected = SanctionsPolicyOutcome.ERROR
        reasons = reasons + (
            DecisionReason(
                reason_id="reason:forced-error",
                code="evaluation_error",
                channel=EvidenceChannel.UNCERTAINTY,
                outcome=SanctionsPolicyOutcome.ERROR,
                human_detail="Evaluation did not complete safely.",
                machine_detail="force_error=true",
            ),
        )
    elif force_stale or not bindings.is_fresh:
        if combiner.rank(SanctionsPolicyOutcome.STALE) >= combiner.rank(selected):
            selected = SanctionsPolicyOutcome.STALE
        reasons = reasons + (
            DecisionReason(
                reason_id="reason:stale-evidence",
                code="stale_evidence",
                channel=EvidenceChannel.FRESHNESS,
                outcome=SanctionsPolicyOutcome.STALE,
                human_detail="Critical evidence exceeded maximum accepted age.",
                machine_detail=(
                    f"snapshot_age_seconds={bindings.snapshot_age_seconds};"
                    f"max={bindings.max_snapshot_age_seconds}"
                ),
            ),
        )
    elif bindings.has_uncertainty and selected is SanctionsPolicyOutcome.ALLOW:
        selected = SanctionsPolicyOutcome.INCONCLUSIVE
        reasons = reasons + (
            DecisionReason(
                reason_id="reason:uncertainty",
                code="uncertainty_present",
                channel=EvidenceChannel.UNCERTAINTY,
                outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
                notes=bindings.uncertainty_codes,
                human_detail="Uncertainty prevents an automated allow.",
                machine_detail="uncertainty_codes="
                + ",".join(bindings.uncertainty_codes),
            ),
        )

    if heuristic_only and selected is SanctionsPolicyOutcome.ALLOW:
        selected = SanctionsPolicyOutcome.REVIEW
    if heuristic_only and selected is SanctionsPolicyOutcome.DENY:
        selected = SanctionsPolicyOutcome.REVIEW
        reasons = reasons + (
            DecisionReason(
                reason_id="reason:heuristic-no-deny",
                code="heuristic_review_only",
                channel=EvidenceChannel.HEURISTIC,
                outcome=SanctionsPolicyOutcome.REVIEW,
                human_detail=(
                    "Heuristic evidence requested review; it cannot alone deny "
                    "or designate."
                ),
                machine_detail="heuristic_only_deny_downgraded_to_review",
            ),
        )

    decision_id = _decision_id(
        request_id=bindings.request_id,
        combiner=combiner,
        outcome=selected,
        binding_digest=bindings.binding_digest(),
    )
    return ComplianceDecision(
        decision_id=decision_id,
        outcome=selected,
        reasons=reasons,
        factors=normalized,
        bindings=bindings,
        combiner_id=combiner.combiner_id,
        combiner_revision=combiner.revision,
        combiner_rules_digest=combiner.rules_digest,
        declares_designation=False,
        heuristic_only=heuristic_only,
    )


def factor_from_sanctions_outcome(
    *,
    factor_id: str,
    channel: EvidenceChannel | str,
    outcome: SanctionsPolicyOutcome | str,
    reason_code: str,
    match_level: SanctionsMatchLevel | str | None = None,
    evidence_ids: Sequence[str] = (),
    path_ids: Sequence[str] = (),
    counterparty_ids: Sequence[str] = (),
    human_detail: str = "",
    machine_detail: str = "",
    uncertainty: bool = False,
    authority_claim: AuthorityClaim | str = AuthorityClaim.NONE,
) -> PolicyFactor:
    """Convenience constructor for a single-reason policy factor."""

    channel_e = _enum(EvidenceChannel, channel, "channel")
    outcome_e = _outcome(outcome)
    level = (
        None
        if match_level in (None, "")
        else _enum(SanctionsMatchLevel, match_level, "match_level")
    )
    reason = DecisionReason(
        reason_id=f"reason:{factor_id}",
        code=reason_code,
        channel=channel_e,
        outcome=outcome_e,
        match_level=level,
        evidence_ids=tuple(evidence_ids),
        path_ids=tuple(path_ids),
        counterparty_ids=tuple(counterparty_ids),
        human_detail=human_detail,
        machine_detail=machine_detail,
    )
    return PolicyFactor(
        factor_id=factor_id,
        channel=channel_e,
        outcome=outcome_e,
        reasons=(reason,),
        authority_claim=authority_claim,
        uncertainty=uncertainty,
    )


__all__ = [
    "COMPLIANCE_DECISION_SCHEMA_VERSION",
    "POLICY_COMBINER_SCHEMA_VERSION",
    "AuthorityClaim",
    "ComplianceDecision",
    "DecisionError",
    "DecisionReason",
    "EvidenceBindings",
    "EvidenceChannel",
    "PolicyCombiner",
    "PolicyFactor",
    "emit_compliance_decision",
    "factor_from_sanctions_outcome",
    "outcome_severity",
]
