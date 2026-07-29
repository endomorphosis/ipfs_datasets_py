"""Pure, offline evaluation of versioned sanctions policy inputs.

This module performs deterministic screening against an injected snapshot.  It
does not acquire lists, resolve names fuzzily, sign transactions, report to an
authority, or claim a legal conclusion.  A screening ``ALLOW`` means only that
the supplied subject was screened under the exact policy and snapshot recorded
in the decision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from ..identity import crypto_ir_identity
from ..provenance import AuthorityKind
from ..schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ..verdicts import SanctionsMatchLevel
from .models import (
    CRYPTO_IR_COMPLIANCE_DOMAIN,
    AssociationEvidence,
    ComplianceModelError,
    DesignationRecord,
    DigitalCurrencyIdentifier,
    LicenseDisposition,
    LicenseRecord,
    OwnershipEvidence,
    SanctionsMatch,
    SanctionsPolicy,
    SanctionsPolicyOutcome,
    SanctionsSnapshot,
    _digest,
    _identifier,
    _instant,
    _known,
    _mapping,
    _parse_instant,
    _tuple,
)


SANCTIONS_SCREENING_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.sanctions-screening@1.0.0"
)


@dataclass(frozen=True, slots=True)
class SanctionsScreeningRequest:
    """All bounded evidence supplied to one deterministic screening operation."""

    request_id: str
    subject_party_id: str
    at_time: str
    activity_id: str
    snapshot: SanctionsSnapshot
    identifiers: tuple[DigitalCurrencyIdentifier, ...] = ()
    asserted_party_ids: tuple[str, ...] = ()
    ownership_evidence: tuple[OwnershipEvidence, ...] = ()
    association_evidence: tuple[AssociationEvidence, ...] = ()
    licenses: tuple[LicenseRecord, ...] = ()
    production_enforcement: bool = False

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "subject_party_id",
            _identifier(self.subject_party_id, "subject_party_id"),
        )
        object.__setattr__(self, "at_time", _instant(self.at_time, "at_time"))
        object.__setattr__(
            self, "activity_id", _identifier(self.activity_id, "activity_id")
        )
        if not isinstance(self.snapshot, SanctionsSnapshot):
            object.__setattr__(
                self,
                "snapshot",
                SanctionsSnapshot.from_dict(_mapping(self.snapshot, "snapshot")),
            )
        object.__setattr__(
            self,
            "identifiers",
            _tuple(self.identifiers, DigitalCurrencyIdentifier, "identifiers"),
        )
        party_ids = tuple(
            _identifier(item, "asserted_party_ids") for item in self.asserted_party_ids
        )
        if len(party_ids) != len(set(party_ids)):
            raise ComplianceModelError("asserted_party_ids must be unique")
        object.__setattr__(self, "asserted_party_ids", party_ids)
        object.__setattr__(
            self,
            "ownership_evidence",
            _tuple(
                self.ownership_evidence, OwnershipEvidence, "ownership_evidence"
            ),
        )
        object.__setattr__(
            self,
            "association_evidence",
            _tuple(
                self.association_evidence,
                AssociationEvidence,
                "association_evidence",
            ),
        )
        object.__setattr__(
            self, "licenses", _tuple(self.licenses, LicenseRecord, "licenses")
        )
        if type(self.production_enforcement) is not bool:
            raise ComplianceModelError("production_enforcement must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asserted_party_ids": list(self.asserted_party_ids),
            "association_evidence": [
                item.to_dict() for item in self.association_evidence
            ],
            "at_time": self.at_time,
            "activity_id": self.activity_id,
            "identifiers": [item.to_dict() for item in self.identifiers],
            "licenses": [item.to_dict() for item in self.licenses],
            "ownership_evidence": [
                item.to_dict() for item in self.ownership_evidence
            ],
            "production_enforcement": self.production_enforcement,
            "request_id": self.request_id,
            "snapshot": self.snapshot.to_dict(),
            "subject_party_id": self.subject_party_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsScreeningRequest":
        value = _mapping(value, "SanctionsScreeningRequest")
        fields = frozenset(
            {
                "request_id",
                "subject_party_id",
                "at_time",
                "activity_id",
                "snapshot",
                "identifiers",
                "asserted_party_ids",
                "ownership_evidence",
                "association_evidence",
                "licenses",
                "production_enforcement",
            }
        )
        _known(value, fields, "SanctionsScreeningRequest")
        return cls(
            request_id=value.get("request_id", ""),
            subject_party_id=value.get("subject_party_id", ""),
            at_time=value.get("at_time", ""),
            activity_id=value.get("activity_id", ""),
            snapshot=SanctionsSnapshot.from_dict(value.get("snapshot", {})),
            identifiers=_tuple(
                value.get("identifiers", ()),
                DigitalCurrencyIdentifier,
                "identifiers",
            ),
            asserted_party_ids=tuple(value.get("asserted_party_ids", ())),
            ownership_evidence=_tuple(
                value.get("ownership_evidence", ()),
                OwnershipEvidence,
                "ownership_evidence",
            ),
            association_evidence=_tuple(
                value.get("association_evidence", ()),
                AssociationEvidence,
                "association_evidence",
            ),
            licenses=_tuple(value.get("licenses", ()), LicenseRecord, "licenses"),
            production_enforcement=value.get("production_enforcement", False),
        )


@dataclass(frozen=True, slots=True)
class SanctionsDecision:
    """Explainable policy result bound to an exact policy and snapshot revision."""

    decision_id: str
    request_id: str
    subject_party_id: str
    outcome: SanctionsPolicyOutcome
    policy_id: str
    policy_revision: str
    policy_rules_digest: str
    snapshot_id: str
    snapshot_revision: str
    matched_levels: tuple[SanctionsMatchLevel, ...]
    matches: tuple[SanctionsMatch, ...]
    reason_codes: tuple[str, ...]
    applicable_license_ids: tuple[str, ...]
    legal_policy_authority_present: bool
    production_policy_enforceable: bool
    schema_version: str = SANCTIONS_SCREENING_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "request_id",
            "subject_party_id",
            "policy_id",
            "policy_revision",
            "snapshot_id",
            "snapshot_revision",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "outcome",
            (
                self.outcome
                if isinstance(self.outcome, SanctionsPolicyOutcome)
                else SanctionsPolicyOutcome(self.outcome)
            ),
        )
        object.__setattr__(
            self,
            "policy_rules_digest",
            _digest(self.policy_rules_digest, "policy_rules_digest"),
        )
        levels = tuple(
            item if isinstance(item, SanctionsMatchLevel) else SanctionsMatchLevel(item)
            for item in self.matched_levels
        )
        if len(levels) != len(set(levels)):
            raise ComplianceModelError("matched_levels must be unique")
        object.__setattr__(self, "matched_levels", levels)
        object.__setattr__(
            self, "matches", _tuple(self.matches, SanctionsMatch, "matches")
        )
        for name in ("reason_codes", "applicable_license_ids"):
            values = tuple(_identifier(item, name) for item in getattr(self, name))
            if len(values) != len(set(values)):
                raise ComplianceModelError(f"{name} must be unique")
            object.__setattr__(self, name, values)
        for name in (
            "legal_policy_authority_present",
            "production_policy_enforceable",
        ):
            if type(getattr(self, name)) is not bool:
                raise ComplianceModelError(f"{name} must be a boolean")
        if (
            self.production_policy_enforceable
            and not self.legal_policy_authority_present
        ):
            raise ComplianceModelError(
                "production enforcement requires legal policy authority"
            )
        if self.schema_version != SANCTIONS_SCREENING_SCHEMA_VERSION:
            raise ComplianceModelError(
                f"unsupported screening schema: {self.schema_version}"
            )

    @property
    def is_legal_certification(self) -> bool:
        """Screening is never represented as a legal certification."""

        return False

    def can_authorize_transaction(self) -> bool:
        """A screening decision cannot cross into transaction authorization."""

        return False

    @property
    def identity(self):
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
            domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.screening-decision",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable_license_ids": list(self.applicable_license_ids),
            "decision_id": self.decision_id,
            "legal_policy_authority_present": (
                self.legal_policy_authority_present
            ),
            "matched_levels": [item.value for item in self.matched_levels],
            "matches": [item.to_dict() for item in self.matches],
            "outcome": self.outcome.value,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "policy_rules_digest": self.policy_rules_digest,
            "production_policy_enforceable": self.production_policy_enforceable,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "snapshot_revision": self.snapshot_revision,
            "subject_party_id": self.subject_party_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsDecision":
        value = _mapping(value, "SanctionsDecision")
        fields = frozenset(
            {
                "decision_id",
                "request_id",
                "subject_party_id",
                "outcome",
                "policy_id",
                "policy_revision",
                "policy_rules_digest",
                "snapshot_id",
                "snapshot_revision",
                "matched_levels",
                "matches",
                "reason_codes",
                "applicable_license_ids",
                "legal_policy_authority_present",
                "production_policy_enforceable",
                "schema_version",
            }
        )
        _known(value, fields, "SanctionsDecision")
        return cls(
            decision_id=value.get("decision_id", ""),
            request_id=value.get("request_id", ""),
            subject_party_id=value.get("subject_party_id", ""),
            outcome=value.get("outcome", ""),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            policy_rules_digest=value.get("policy_rules_digest", ""),
            snapshot_id=value.get("snapshot_id", ""),
            snapshot_revision=value.get("snapshot_revision", ""),
            matched_levels=tuple(value.get("matched_levels", ())),
            matches=_tuple(value.get("matches", ()), SanctionsMatch, "matches"),
            reason_codes=tuple(value.get("reason_codes", ())),
            applicable_license_ids=tuple(
                value.get("applicable_license_ids", ())
            ),
            legal_policy_authority_present=value.get(
                "legal_policy_authority_present"
            ),
            production_policy_enforceable=value.get(
                "production_policy_enforceable"
            ),
            schema_version=value.get(
                "schema_version", SANCTIONS_SCREENING_SCHEMA_VERSION
            ),
        )


def _match_id(level: SanctionsMatchLevel, *parts: str) -> str:
    material = "\x00".join((level.value, *parts)).encode("utf-8")
    return f"match:{hashlib.sha256(material).hexdigest()}"


def _active_designations(
    policy: SanctionsPolicy,
    snapshot: SanctionsSnapshot,
    at_time: str,
) -> tuple[DesignationRecord, ...]:
    return tuple(
        designation
        for designation in snapshot.designations
        if designation.is_effective_at(at_time)
        and bool(set(designation.program_ids) & set(policy.program_ids))
        and policy.jurisdiction_code in designation.jurisdiction_codes
    )


def _snapshot_matches(
    request: SanctionsScreeningRequest,
    designations: Sequence[DesignationRecord],
) -> list[SanctionsMatch]:
    matches: list[SanctionsMatch] = []
    supplied = {item.comparison_key: item for item in request.identifiers}
    for designation in designations:
        for listed in designation.identifiers:
            if listed.comparison_key in supplied:
                matches.append(
                    SanctionsMatch(
                        match_id=_match_id(
                            SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
                            listed.identifier_id,
                            designation.designation_id,
                        ),
                        level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
                        subject_party_id=request.subject_party_id,
                        snapshot_id=request.snapshot.snapshot_id,
                        designation_ids=(designation.designation_id,),
                        identifier_id=listed.identifier_id,
                    )
                )
        if designation.party_id in request.asserted_party_ids:
            matches.append(
                SanctionsMatch(
                    match_id=_match_id(
                        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
                        designation.party_id,
                        designation.designation_id,
                    ),
                    level=SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
                    subject_party_id=request.subject_party_id,
                    snapshot_id=request.snapshot.snapshot_id,
                    designation_ids=(designation.designation_id,),
                )
            )
    return matches


def _ownership_matches(
    policy: SanctionsPolicy,
    request: SanctionsScreeningRequest,
    designations: Sequence[DesignationRecord],
) -> tuple[list[SanctionsMatch], bool]:
    matches: list[SanctionsMatch] = []
    incomplete = False
    active_ids = {item.designation_id for item in designations}
    for evidence in request.ownership_evidence:
        if evidence.subject_party_id != request.subject_party_id:
            continue
        relevant_ids = tuple(
            sorted(
                {
                    designation_id
                    for interest in evidence.interests
                    for designation_id in interest.designation_ids
                    if designation_id in active_ids
                }
            )
        )
        if not evidence.complete or not evidence.is_effective_at(request.at_time):
            incomplete = True
            continue
        relevant_total = sum(
            interest.ownership_basis_points
            for interest in evidence.interests
            if set(interest.designation_ids) & active_ids
        )
        if (
            relevant_ids
            and relevant_total >= policy.ownership_threshold_basis_points
        ):
            matches.append(
                SanctionsMatch(
                    match_id=_match_id(
                        SanctionsMatchLevel.OWNED_ENTITY, evidence.evidence_id
                    ),
                    level=SanctionsMatchLevel.OWNED_ENTITY,
                    subject_party_id=request.subject_party_id,
                    snapshot_id=request.snapshot.snapshot_id,
                    designation_ids=relevant_ids,
                    ownership_evidence_id=evidence.evidence_id,
                )
            )
    return matches, incomplete


def _association_matches(
    request: SanctionsScreeningRequest,
    designations: Sequence[DesignationRecord],
) -> tuple[list[SanctionsMatch], bool]:
    matches: list[SanctionsMatch] = []
    incomplete = False
    by_party: dict[str, list[str]] = {}
    for designation in designations:
        by_party.setdefault(designation.party_id, []).append(
            designation.designation_id
        )
    for evidence in request.association_evidence:
        if evidence.subject_party_id != request.subject_party_id:
            continue
        designation_ids = tuple(sorted(by_party.get(evidence.target_party_id, ())))
        if not designation_ids:
            continue
        if not evidence.complete:
            incomplete = True
            continue
        matches.append(
            SanctionsMatch(
                match_id=_match_id(evidence.match_level, evidence.evidence_id),
                level=evidence.match_level,
                subject_party_id=request.subject_party_id,
                snapshot_id=request.snapshot.snapshot_id,
                designation_ids=designation_ids,
                association_evidence_id=evidence.evidence_id,
            )
        )
    return matches, incomplete


def _applicable_licenses(
    policy: SanctionsPolicy,
    request: SanctionsScreeningRequest,
    designations: Sequence[DesignationRecord],
) -> tuple[LicenseRecord, ...]:
    program_ids = sorted(
        {
            program_id
            for designation in designations
            for program_id in designation.program_ids
            if program_id in policy.program_ids
        }
    )
    return tuple(
        license_record
        for license_record in request.licenses
        if license_record.authority_id in policy.authority_ids
        and license_record.is_applicable(
            subject_party_id=request.subject_party_id,
            program_ids=program_ids,
            jurisdiction_code=policy.jurisdiction_code,
            activity_id=request.activity_id,
            at_time=request.at_time,
        )
    )


def _decision(
    *,
    policy: SanctionsPolicy,
    request: SanctionsScreeningRequest,
    outcome: SanctionsPolicyOutcome,
    matches: Sequence[SanctionsMatch] = (),
    reasons: Sequence[str],
    licenses: Sequence[LicenseRecord] = (),
    authority_present: bool,
    production_enforceable: bool,
) -> SanctionsDecision:
    material = "\x00".join(
        (
            request.request_id,
            policy.policy_id,
            policy.revision,
            request.snapshot.snapshot_id,
        )
    ).encode("utf-8")
    decision_id = f"decision:{hashlib.sha256(material).hexdigest()}"
    levels = tuple(
        sorted({item.level for item in matches}, key=lambda item: item.value)
    )
    unique_reasons = tuple(dict.fromkeys(reasons))
    return SanctionsDecision(
        decision_id=decision_id,
        request_id=request.request_id,
        subject_party_id=request.subject_party_id,
        outcome=outcome,
        policy_id=policy.policy_id,
        policy_revision=policy.revision,
        policy_rules_digest=policy.rules_digest,
        snapshot_id=request.snapshot.snapshot_id,
        snapshot_revision=request.snapshot.revision,
        matched_levels=levels,
        matches=tuple(matches),
        reason_codes=unique_reasons,
        applicable_license_ids=tuple(item.license_id for item in licenses),
        legal_policy_authority_present=authority_present,
        production_policy_enforceable=production_enforceable,
    )


def evaluate_sanctions_policy(
    policy: SanctionsPolicy,
    request: SanctionsScreeningRequest,
) -> SanctionsDecision:
    """Evaluate a request without elevating screening into legal certification.

    Production evaluation fails closed before applying rules unless a legal
    owner approved the exact policy id, revision, rules digest, and time
    window.  The selected outcome and its precedence are policy inputs.
    """

    if not isinstance(policy, SanctionsPolicy):
        raise ComplianceModelError("policy must be a SanctionsPolicy")
    if not isinstance(request, SanctionsScreeningRequest):
        raise ComplianceModelError("request must be a SanctionsScreeningRequest")

    snapshot = request.snapshot
    authority_present = bool(
        policy.approval
        and policy.approval.rules_digest == policy.rules_digest
        and policy.approval.is_effective_at(request.at_time)
    )
    production_enforceable = policy.approved_for_production_at(request.at_time)

    if request.production_enforcement and not production_enforceable:
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            reasons=("missing_legal_policy_authority",),
            authority_present=authority_present,
            production_enforceable=False,
        )
    if not policy.is_effective_at(request.at_time):
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.STALE,
            reasons=("policy_not_effective",),
            authority_present=authority_present,
            production_enforceable=False,
        )
    if (
        snapshot.authority.authority_id not in policy.authority_ids
        or snapshot.sanctions_list.list_id not in policy.list_ids
    ):
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.ERROR,
            reasons=("snapshot_outside_policy_scope",),
            authority_present=authority_present,
            production_enforceable=production_enforceable,
        )
    if not snapshot.complete:
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            reasons=("incomplete_snapshot",),
            authority_present=authority_present,
            production_enforceable=production_enforceable,
        )

    at_time = _parse_instant(request.at_time)
    effective_at = _parse_instant(snapshot.effective_at)
    retrieved_at = _parse_instant(snapshot.retrieved_at)
    if at_time < effective_at or at_time < retrieved_at:
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            reasons=("snapshot_not_yet_effective",),
            authority_present=authority_present,
            production_enforceable=production_enforceable,
        )
    age_seconds = int((at_time - retrieved_at).total_seconds())
    if age_seconds > policy.maximum_snapshot_age_seconds:
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.STALE,
            reasons=("stale_snapshot",),
            authority_present=authority_present,
            production_enforceable=production_enforceable,
        )

    designations = _active_designations(policy, snapshot, request.at_time)
    matches = _snapshot_matches(request, designations)
    ownership_matches, ownership_incomplete = _ownership_matches(
        policy, request, designations
    )
    association_matches, association_incomplete = _association_matches(
        request, designations
    )
    matches.extend(ownership_matches)
    matches.extend(association_matches)
    if ownership_incomplete or association_incomplete:
        reasons = []
        if ownership_incomplete:
            reasons.append("incomplete_ownership_evidence")
        if association_incomplete:
            reasons.append("incomplete_association_evidence")
        return _decision(
            policy=policy,
            request=request,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
            matches=matches,
            reasons=reasons,
            authority_present=authority_present,
            production_enforceable=production_enforceable,
        )

    levels = {item.level for item in matches}
    if not levels:
        levels = {SanctionsMatchLevel.NO_MATCH}
    applied_rules = [policy.rule_for(level) for level in levels]
    outcomes = [rule.outcome for rule in applied_rules]
    reasons = [rule.reason_code for rule in applied_rules]

    licenses = _applicable_licenses(policy, request, designations)
    if licenses and policy.license_disposition is not LicenseDisposition.IGNORE:
        outcomes.append(policy.license_outcome)
        reasons.append("applicable_scoped_license")

    precedence = {
        outcome: index for index, outcome in enumerate(policy.outcome_precedence)
    }
    outcome = max(outcomes, key=lambda item: precedence[item])
    return _decision(
        policy=policy,
        request=request,
        outcome=outcome,
        matches=matches,
        reasons=reasons,
        licenses=licenses,
        authority_present=authority_present,
        production_enforceable=production_enforceable,
    )


screen_sanctions = evaluate_sanctions_policy


__all__ = [
    "SANCTIONS_SCREENING_SCHEMA_VERSION",
    "SanctionsDecision",
    "SanctionsScreeningRequest",
    "evaluate_sanctions_policy",
    "screen_sanctions",
]
