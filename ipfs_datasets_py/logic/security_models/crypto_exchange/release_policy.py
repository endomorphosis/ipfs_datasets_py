"""Release-gate policy for crypto-exchange proof reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from .ir.schema import evidence_review_statuses
from .reports.proof_report import (
    PROOF_STATUS_DISPROVED,
    PROOF_STATUS_NOT_MODELED,
    PROOF_STATUS_PROVED,
    PROOF_STATUS_UNKNOWN,
    PROOF_STATUSES,
)

ReleaseGate = Literal['blocking', 'high', 'medium', 'informational']

REVIEWED_EVIDENCE_STATUSES = frozenset({'human_reviewed', 'trusted_fixture'})
FAIL_CLOSED_STATUSES = frozenset(
    {
        PROOF_STATUS_DISPROVED,
        PROOF_STATUS_UNKNOWN,
        PROOF_STATUS_NOT_MODELED,
    }
)


@dataclass(frozen=True, slots=True)
class ReleasePolicyEntry:
    """Policy row for one formal security claim."""

    claim_id: str
    domain: str
    release_gate: ReleaseGate
    accepted_statuses: frozenset[str]
    fail_closed_statuses: frozenset[str]
    required_assumptions: tuple[str, ...]
    requires_reviewed_evidence: bool
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'claim_id': self.claim_id,
            'domain': self.domain,
            'release_gate': self.release_gate,
            'accepted_statuses': sorted(self.accepted_statuses),
            'fail_closed_statuses': sorted(self.fail_closed_statuses),
            'required_assumptions': list(self.required_assumptions),
            'requires_reviewed_evidence': self.requires_reviewed_evidence,
            'rationale': self.rationale,
        }


def _claim_entry(
    *,
    claim_id: str,
    domain: str,
    release_gate: ReleaseGate,
    required_assumptions: tuple[str, ...],
    fail_closed_statuses: frozenset[str] = FAIL_CLOSED_STATUSES,
    requires_reviewed_evidence: bool = True,
    rationale: str,
) -> ReleasePolicyEntry:
    return ReleasePolicyEntry(
        claim_id=claim_id,
        domain=domain,
        release_gate=release_gate,
        accepted_statuses=frozenset({PROOF_STATUS_PROVED}),
        fail_closed_statuses=fail_closed_statuses,
        required_assumptions=required_assumptions,
        requires_reviewed_evidence=requires_reviewed_evidence,
        rationale=rationale,
    )


RELEASE_POLICY: tuple[ReleasePolicyEntry, ...] = (
    _claim_entry(
        claim_id='no_unauthorized_withdrawal',
        domain='withdrawals',
        release_gate='blocking',
        required_assumptions=('A3', 'A4', 'A5', 'A8'),
        rationale='A broadcast withdrawal without request, approval, nonce, reservation, and live wallet checks is a direct funds-loss condition.',
    ),
    _claim_entry(
        claim_id='no_over_reserved_internal_account',
        domain='ledger',
        release_gate='blocking',
        required_assumptions=('A4', 'A5'),
        rationale='Over-reservation means internal available balance can be spent more than once.',
    ),
    _claim_entry(
        claim_id='global_asset_conservation',
        domain='ledger',
        release_gate='blocking',
        required_assumptions=('A4', 'A10'),
        rationale='Customer liabilities exceeding custody plus pending settlement is a solvency failure.',
    ),
    _claim_entry(
        claim_id='no_deposit_before_finality',
        domain='deposits',
        release_gate='high',
        required_assumptions=('A6', 'A9'),
        rationale='Crediting deposits before finality exposes the exchange to reorg and false-credit losses.',
    ),
    _claim_entry(
        claim_id='no_signing_request_after_wallet_freeze',
        domain='hsm',
        release_gate='high',
        required_assumptions=('A3', 'A8'),
        rationale='A frozen wallet that can still request signatures defeats incident response controls.',
    ),
    _claim_entry(
        claim_id='capability_delegation_no_authority_increase',
        domain='capabilities',
        release_gate='high',
        required_assumptions=('A1', 'A7'),
        rationale='Delegation that amplifies authority can bypass administrative and custody controls.',
    ),
    _claim_entry(
        claim_id='revoked_capability_no_future_authorization',
        domain='capabilities',
        release_gate='high',
        required_assumptions=('A10',),
        rationale='Revoked capabilities authorizing later privileged actions breaks emergency revocation.',
    ),
    _claim_entry(
        claim_id='audit_event_exists_for_critical_transition',
        domain='audit',
        release_gate='medium',
        required_assumptions=('A10',),
        fail_closed_statuses=frozenset({PROOF_STATUS_DISPROVED}),
        requires_reviewed_evidence=False,
        rationale='Missing audit linkage is a release risk; a concrete disproof blocks release, while UNKNOWN or NOT_MODELED requires manual triage.',
    ),
)


def release_policy_entries() -> tuple[ReleasePolicyEntry, ...]:
    """Return the immutable default release policy."""

    return RELEASE_POLICY


def release_policy_for_claim(claim_id: str) -> ReleasePolicyEntry:
    """Return the policy row for *claim_id*."""

    for entry in RELEASE_POLICY:
        if entry.claim_id == claim_id:
            return entry
    raise KeyError(f'No release policy configured for claim: {claim_id}')


def _report_value(report: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(report, Mapping):
        return report.get(field_name, default)
    return getattr(report, field_name, default)


def _report_by_claim(reports: list[Any]) -> dict[str, Any]:
    by_claim: dict[str, Any] = {}
    for report in reports:
        claim_id = _report_value(report, 'claim_id')
        if isinstance(claim_id, str) and claim_id:
            by_claim[claim_id] = report
    return by_claim


def _gate_counts() -> dict[str, dict[str, int]]:
    return {
        gate: {
            'total': 0,
            'accepted': 0,
            'failed': 0,
            'attention': 0,
        }
        for gate in ('blocking', 'high', 'medium', 'informational')
    }


def evaluate_release_policy(
    reports: list[Any],
    *,
    require_reviewed_evidence: bool = True,
) -> dict[str, Any]:
    """Evaluate proof reports against the release-gate policy."""

    reports_by_claim = _report_by_claim(reports)
    gates = _gate_counts()
    failures: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []

    for entry in RELEASE_POLICY:
        gate_summary = gates[entry.release_gate]
        gate_summary['total'] += 1
        report = reports_by_claim.get(entry.claim_id)
        if report is None:
            reason = 'missing proof report'
            item = {
                'claim_id': entry.claim_id,
                'domain': entry.domain,
                'release_gate': entry.release_gate,
                'status': 'MISSING',
                'reasons': [reason],
            }
            if entry.release_gate in {'blocking', 'high'}:
                gate_summary['failed'] += 1
                failures.append(item)
            else:
                gate_summary['attention'] += 1
                attention.append(item)
            continue

        status = str(_report_value(report, 'status', '')).strip()
        reasons: list[str] = []
        accepted = status in entry.accepted_statuses
        failed = False
        needs_attention = False
        if accepted:
            pass
        elif status in entry.fail_closed_statuses:
            failed = True
            reasons.append(f'status {status} is fail-closed for {entry.release_gate} release gate')
        else:
            needs_attention = True
            reasons.append(f'status {status or "<empty>"} requires manual release triage')

        report_assumptions = set(str(item) for item in _report_value(report, 'assumptions', []) if str(item))
        missing_assumptions = sorted(set(entry.required_assumptions) - report_assumptions)
        if missing_assumptions:
            failed = True
            reasons.append(f'missing required assumption(s): {", ".join(missing_assumptions)}')

        evidence_refs = _report_value(report, 'evidence_refs', [])
        review_statuses = evidence_review_statuses(evidence_refs if isinstance(evidence_refs, list) else [])
        if (
            require_reviewed_evidence
            and entry.requires_reviewed_evidence
            and status == PROOF_STATUS_PROVED
            and not review_statuses.intersection(REVIEWED_EVIDENCE_STATUSES)
        ):
            failed = True
            reasons.append('proved claim lacks human_reviewed or trusted_fixture evidence')

        if failed:
            gate_summary['failed'] += 1
        elif accepted:
            gate_summary['accepted'] += 1
        elif needs_attention:
            gate_summary['attention'] += 1

        if reasons:
            item = {
                'claim_id': entry.claim_id,
                'domain': entry.domain,
                'release_gate': entry.release_gate,
                'status': status,
                'reasons': reasons,
            }
            if failed and entry.release_gate in {'blocking', 'high', 'medium'}:
                failures.append(item)
            else:
                attention.append(item)

    unknown_policy_reports = sorted(set(reports_by_claim) - {entry.claim_id for entry in RELEASE_POLICY})
    return {
        'release_ready': not failures,
        'require_reviewed_evidence': require_reviewed_evidence,
        'reviewed_evidence_statuses': sorted(REVIEWED_EVIDENCE_STATUSES),
        'policy': [entry.to_dict() for entry in RELEASE_POLICY],
        'gates': gates,
        'failures': failures,
        'attention': attention,
        'unknown_policy_reports': unknown_policy_reports,
    }
