"""Human and machine explanations for compliance decisions (CRYPTOIR-G440).

Explanations cover two distinct surfaces:

1. **Decision** — which outcome was selected and why (reason codes, channels,
   match levels, contributing factors).
2. **Evidentiary boundary** — the exact counterparties, list/graph/entity/
   ownership/license/policy revisions, path evidence, bounds, freshness,
   uncertainty, and expiry the decision is valid for, and what it does *not*
   claim beyond that boundary.

Explanations never elevate authority: they do not designate, authorize, sign,
or certify legality.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .decisions import (
    ComplianceDecision,
    DecisionError,
    DecisionReason,
    EvidenceBindings,
    EvidenceChannel,
    PolicyFactor,
    SanctionsPolicyOutcome,
)
from .models import _known, _mapping, _text


COMPLIANCE_EXPLAIN_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.compliance-explain@1.0.0"
)

_OUTCOME_HUMAN: Final[Mapping[SanctionsPolicyOutcome, str]] = {
    SanctionsPolicyOutcome.ALLOW: (
        "No disqualifying compliance hit under the bound evidence and policy."
    ),
    SanctionsPolicyOutcome.REVIEW: (
        "Configured risk, license, or ambiguity requires human review."
    ),
    SanctionsPolicyOutcome.DENY: (
        "A hard compliance prohibition matched under the bound policy."
    ),
    SanctionsPolicyOutcome.INCONCLUSIVE: (
        "Required evidence, completeness, or capability is missing."
    ),
    SanctionsPolicyOutcome.STALE: (
        "Critical evidence or policy inputs exceeded freshness limits."
    ),
    SanctionsPolicyOutcome.ERROR: (
        "Evaluation did not complete safely; automation must fail closed."
    ),
}

_CHANNEL_HUMAN: Final[Mapping[EvidenceChannel, str]] = {
    EvidenceChannel.DIRECT_LIST: "direct list / exact identifier match",
    EvidenceChannel.PARTY_OWNERSHIP: "party or ownership evidence",
    EvidenceChannel.BOUNDED_FLOW: "bounded-flow exposure path",
    EvidenceChannel.FRESHNESS: "freshness / staleness check",
    EvidenceChannel.LICENSE: "scoped license or exception",
    EvidenceChannel.UNCERTAINTY: "uncertainty or incomplete evidence",
    EvidenceChannel.HEURISTIC: "heuristic association (review prioritization only)",
}


@dataclass(frozen=True, slots=True)
class EvidentiaryBoundaryExplanation:
    """Structured description of what a decision is and is not evidence for."""

    scope_summary: str
    bound_fields: Mapping[str, Any]
    claims: tuple[str, ...]
    non_claims: tuple[str, ...]
    substitution_invalidates: tuple[str, ...]
    schema_version: str = COMPLIANCE_EXPLAIN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_fields": dict(self.bound_fields),
            "claims": list(self.claims),
            "non_claims": list(self.non_claims),
            "schema_version": self.schema_version,
            "scope_summary": self.scope_summary,
            "substitution_invalidates": list(self.substitution_invalidates),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidentiaryBoundaryExplanation":
        value = _mapping(value, "EvidentiaryBoundaryExplanation")
        _known(
            value,
            frozenset(
                {
                    "scope_summary",
                    "bound_fields",
                    "claims",
                    "non_claims",
                    "substitution_invalidates",
                    "schema_version",
                }
            ),
            "EvidentiaryBoundaryExplanation",
        )
        return cls(
            scope_summary=value.get("scope_summary", ""),
            bound_fields=dict(value.get("bound_fields", {})),
            claims=tuple(value.get("claims", ())),
            non_claims=tuple(value.get("non_claims", ())),
            substitution_invalidates=tuple(
                value.get("substitution_invalidates", ())
            ),
            schema_version=value.get(
                "schema_version", COMPLIANCE_EXPLAIN_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ComplianceExplanation:
    """Paired human/machine explanation of a decision and its boundary."""

    decision_id: str
    outcome: SanctionsPolicyOutcome
    human_summary: str
    machine_summary: str
    reason_summaries: tuple[str, ...]
    channel_summaries: tuple[str, ...]
    boundary: EvidentiaryBoundaryExplanation
    blocks_automation: bool
    schema_version: str = COMPLIANCE_EXPLAIN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_automation": self.blocks_automation,
            "boundary": self.boundary.to_dict(),
            "channel_summaries": list(self.channel_summaries),
            "decision_id": self.decision_id,
            "human_summary": self.human_summary,
            "machine_summary": self.machine_summary,
            "outcome": self.outcome.value,
            "reason_summaries": list(self.reason_summaries),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComplianceExplanation":
        value = _mapping(value, "ComplianceExplanation")
        _known(
            value,
            frozenset(
                {
                    "decision_id",
                    "outcome",
                    "human_summary",
                    "machine_summary",
                    "reason_summaries",
                    "channel_summaries",
                    "boundary",
                    "blocks_automation",
                    "schema_version",
                }
            ),
            "ComplianceExplanation",
        )
        outcome = value.get("outcome", "")
        if not isinstance(outcome, SanctionsPolicyOutcome):
            outcome = SanctionsPolicyOutcome(outcome)
        return cls(
            decision_id=value.get("decision_id", ""),
            outcome=outcome,
            human_summary=value.get("human_summary", ""),
            machine_summary=value.get("machine_summary", ""),
            reason_summaries=tuple(value.get("reason_summaries", ())),
            channel_summaries=tuple(value.get("channel_summaries", ())),
            boundary=EvidentiaryBoundaryExplanation.from_dict(
                value.get("boundary", {})
            ),
            blocks_automation=bool(value.get("blocks_automation", True)),
            schema_version=value.get(
                "schema_version", COMPLIANCE_EXPLAIN_SCHEMA_VERSION
            ),
        )


def _reason_human(reason: DecisionReason) -> str:
    channel = _CHANNEL_HUMAN.get(reason.channel, reason.channel.value)
    detail = reason.human_detail or reason.code
    parts = [f"[{reason.code}] via {channel}: {detail}"]
    if reason.match_level is not None:
        parts.append(f"match_level={reason.match_level.value}")
    if reason.evidence_ids:
        parts.append("evidence=" + ",".join(reason.evidence_ids))
    if reason.path_ids:
        parts.append("paths=" + ",".join(reason.path_ids))
    if reason.is_heuristic:
        parts.append("(heuristic; no designation authority)")
    return "; ".join(parts)


def _reason_machine(reason: DecisionReason) -> str:
    payload = {
        "code": reason.code,
        "channel": reason.channel.value,
        "outcome": reason.outcome.value,
        "match_level": (
            None if reason.match_level is None else reason.match_level.value
        ),
        "evidence_ids": list(reason.evidence_ids),
        "path_ids": list(reason.path_ids),
        "counterparty_ids": list(reason.counterparty_ids),
        "is_heuristic": reason.is_heuristic,
        "may_declare_designation": reason.may_declare_designation,
        "machine_detail": reason.machine_detail,
        "notes": list(reason.notes),
    }
    # Compact stable key=value form for logs/receipts.
    items = []
    for key, value in sorted(payload.items()):
        items.append(f"{key}={value!r}")
    return " ".join(items)


def explain_evidentiary_boundary(
    bindings: EvidenceBindings,
    *,
    outcome: SanctionsPolicyOutcome | str | None = None,
    heuristic_only: bool = False,
    declares_designation: bool = False,
) -> EvidentiaryBoundaryExplanation:
    """Explain the evidentiary boundary of a decision (or bare bindings)."""

    if not isinstance(bindings, EvidenceBindings):
        raise DecisionError("bindings must be EvidenceBindings")
    if declares_designation:
        raise DecisionError(
            "explanations must not assert designation from composition"
        )

    bound_fields = {
        "activity_id": bindings.activity_id,
        "bound_max_depth": bindings.bound_max_depth,
        "bound_max_edges": bindings.bound_max_edges,
        "bound_max_nodes": bindings.bound_max_nodes,
        "counterparty_ids": list(bindings.counterparty_ids),
        "effective_at": bindings.effective_at,
        "entity_ids": list(bindings.entity_ids),
        "expires_at": bindings.expires_at,
        "freshness_checked_at": bindings.freshness_checked_at,
        "graph_digest": bindings.graph_digest,
        "graph_snapshot_id": bindings.graph_snapshot_id,
        "license_ids": list(bindings.license_ids),
        "list_revision": bindings.list_revision,
        "list_snapshot_id": bindings.list_snapshot_id,
        "max_snapshot_age_seconds": bindings.max_snapshot_age_seconds,
        "ownership_evidence_ids": list(bindings.ownership_evidence_ids),
        "path_ids": list(bindings.path_ids),
        "policy_id": bindings.policy_id,
        "policy_revision": bindings.policy_revision,
        "policy_rules_digest": bindings.policy_rules_digest,
        "request_id": bindings.request_id,
        "snapshot_age_seconds": bindings.snapshot_age_seconds,
        "subject_party_id": bindings.subject_party_id,
        "uncertainty_codes": list(bindings.uncertainty_codes),
        "binding_digest": bindings.binding_digest(),
        "is_fresh": bindings.is_fresh,
    }

    counterparties = (
        ", ".join(bindings.counterparty_ids)
        if bindings.counterparty_ids
        else "(none bound)"
    )
    list_ref = (
        f"{bindings.list_snapshot_id}@{bindings.list_revision}"
        if bindings.list_snapshot_id or bindings.list_revision
        else "(no list revision bound)"
    )
    graph_ref = (
        f"{bindings.graph_snapshot_id}"
        if bindings.graph_snapshot_id
        else "(no graph snapshot bound)"
    )
    policy_ref = (
        f"{bindings.policy_id}@{bindings.policy_revision}"
        if bindings.policy_id or bindings.policy_revision
        else "(no policy revision bound)"
    )
    scope_summary = (
        f"Decision is valid only for counterparties [{counterparties}] under "
        f"list {list_ref}, graph {graph_ref}, policy {policy_ref}, "
        f"effective_at={bindings.effective_at or 'unspecified'}, "
        f"expires_at={bindings.expires_at or 'unspecified'}."
    )

    claims = [
        "Outcome applies only to the bound counterparties and activity.",
        "List, graph, ownership, license, and policy revisions are fixed in the binding.",
        "Path evidence and exposure bounds (if present) limit any flow-based finding.",
        "Freshness is evaluated at the recorded check time against max age.",
    ]
    if outcome is not None:
        claims.append(f"Selected outcome under these bounds: {_text(str(getattr(outcome, 'value', outcome)), 'outcome')}.")
    if heuristic_only:
        claims.append(
            "All contributing factors were heuristic; outcome is review prioritization only."
        )

    non_claims = [
        "Does not declare any person or address a designated blocked party beyond list evidence.",
        "Does not authorize, sign, or broadcast a transaction.",
        "Does not certify legal compliance or constitute legal advice.",
        "Does not prove global absence of connection outside the bound graph/list/path bounds.",
        "Does not elevate heuristic, GraphRAG, or cluster signals into designation authority.",
        "Does not remain valid after expiry or after substitution of any bound revision.",
    ]
    if bindings.has_uncertainty:
        non_claims.append(
            "Does not resolve uncertainty codes: "
            + ", ".join(bindings.uncertainty_codes)
            + "."
        )
    if not bindings.is_fresh:
        non_claims.append(
            "Does not treat stale evidence as current for automated ALLOW."
        )

    substitution_invalidates = [
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
        "effective_at",
        "expires_at",
        "subject_party_id",
        "activity_id",
    ]

    return EvidentiaryBoundaryExplanation(
        scope_summary=scope_summary,
        bound_fields=bound_fields,
        claims=tuple(claims),
        non_claims=tuple(non_claims),
        substitution_invalidates=tuple(substitution_invalidates),
    )


def explain_decision(decision: ComplianceDecision) -> ComplianceExplanation:
    """Build human and machine explanations for a compliance decision.

    Returns both the decision rationale and the evidentiary boundary so
    consumers can audit *what* was decided and *under which evidence* only.
    """

    if not isinstance(decision, ComplianceDecision):
        raise DecisionError("decision must be a ComplianceDecision")

    outcome = decision.outcome
    human_outcome = _OUTCOME_HUMAN.get(outcome, outcome.value)
    reason_summaries = tuple(_reason_human(r) for r in decision.reasons)
    if not reason_summaries:
        reason_summaries = ("[no_match] no contributing reasons recorded",)

    channels = tuple(
        dict.fromkeys(
            _CHANNEL_HUMAN.get(r.channel, r.channel.value) for r in decision.reasons
        )
    )
    if not channels:
        channels = ("(no channels)",)

    human_parts = [
        f"Outcome {outcome.value.upper()}: {human_outcome}",
        "Reasons: " + " | ".join(reason_summaries),
    ]
    if decision.heuristic_only:
        human_parts.append(
            "Heuristic-only inputs: may request review; cannot designate or alone allow."
        )
    human_parts.append(
        "Evidentiary boundary: " + decision.bindings.binding_digest()
    )
    human_summary = " ".join(human_parts)

    machine_parts = [
        f"outcome={outcome.value}",
        f"decision_id={decision.decision_id}",
        f"heuristic_only={decision.heuristic_only}",
        f"declares_designation={decision.declares_designation}",
        f"reason_codes={list(decision.reason_codes)}",
        f"binding_digest={decision.evidentiary_boundary_digest}",
        f"content_digest={decision.content_digest}",
        f"combiner={decision.combiner_id}@{decision.combiner_revision}",
    ]
    for reason in decision.reasons:
        machine_parts.append("reason{" + _reason_machine(reason) + "}")
    machine_summary = "; ".join(machine_parts)

    boundary = explain_evidentiary_boundary(
        decision.bindings,
        outcome=outcome,
        heuristic_only=decision.heuristic_only,
        declares_designation=decision.declares_designation,
    )
    blocks = outcome is not SanctionsPolicyOutcome.ALLOW

    return ComplianceExplanation(
        decision_id=decision.decision_id,
        outcome=outcome,
        human_summary=human_summary,
        machine_summary=machine_summary,
        reason_summaries=reason_summaries,
        channel_summaries=channels,
        boundary=boundary,
        blocks_automation=blocks,
    )


def explain_factors(factors: Sequence[PolicyFactor]) -> tuple[str, ...]:
    """Short human summaries of raw factors before combination."""

    summaries: list[str] = []
    for factor in factors:
        if not isinstance(factor, PolicyFactor):
            raise DecisionError("factors must be PolicyFactor instances")
        channel = _CHANNEL_HUMAN.get(factor.channel, factor.channel.value)
        summaries.append(
            f"{factor.factor_id}: {channel} → {factor.outcome.value}"
            + (" (heuristic)" if factor.is_heuristic else "")
            + (" (uncertain)" if factor.uncertainty else "")
        )
    return tuple(summaries)


__all__ = [
    "COMPLIANCE_EXPLAIN_SCHEMA_VERSION",
    "ComplianceExplanation",
    "EvidentiaryBoundaryExplanation",
    "explain_decision",
    "explain_evidentiary_boundary",
    "explain_factors",
]
