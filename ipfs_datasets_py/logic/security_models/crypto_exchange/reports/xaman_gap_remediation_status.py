"""Summarize source-bounded Xaman gap remediation status."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-182'
SCHEMA_VERSION = 'xaman-gap-remediation-status/v1'

LOCAL_REMEDIATION_BY_CLASSIFICATION = {
    'BOUNDARY_MODEL_MUTATION': 'remediated_as_boundary_counterexample_retained',
    'MODEL_MUTATION_CONTROL_TEST': 'remediated_as_negative_control_retained',
    'PROOF_CONSUMER_CONTROL_MUTATION': 'remediated_as_fail_closed_consumer_guard',
    'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION': 'remediated_by_source_bounded_runtime_evidence',
    'SOURCE_SUPPORTED_COVERAGE_GAP': 'remediated_as_proof_ineligible_source_gap',
    'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS': 'remediated_by_self_hosted_runtime_evidence_without_production_promotion',
}


def _entries(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    entries = payload.get('entries')
    if not isinstance(entries, list):
        raise ValueError('gap remediation manifest is missing entries')
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _require_expected_inputs(
    *,
    gap_manifest: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
) -> None:
    if gap_manifest.get('schema_version') != 'xaman-gap-remediation-workflow-manifest/v1':
        raise ValueError('unexpected gap remediation manifest schema')
    if solver_portfolio_report.get('schema_version') != 'xaman-testnet-solver-portfolio-report/v1':
        raise ValueError('unexpected solver portfolio report schema')
    if fuzz_report.get('schema_version') != 'xaman-testnet-fuzz-report/v1':
        raise ValueError('unexpected fuzz report schema')


def build_gap_remediation_status(
    *,
    gap_manifest: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    fuzz_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic status artifact for all locally actionable gaps."""

    _require_expected_inputs(
        gap_manifest=gap_manifest,
        solver_portfolio_report=solver_portfolio_report,
        fuzz_report=fuzz_report,
    )

    status_entries: list[dict[str, Any]] = []
    blocked_entries: list[dict[str, Any]] = []
    local_remediated_count = 0
    ready_entries = 0
    blocked_count = 0
    classification_counts: Counter[str] = Counter()
    remediation_counts: Counter[str] = Counter()

    for entry in _entries(gap_manifest):
        entry_id = str(entry.get('entry_id') or '')
        classification = str(entry.get('classification') or 'UNCLASSIFIED')
        execution_state = str(entry.get('execution_state') or 'unknown')
        claim_id = entry.get('claim_id')
        classification_counts[classification] += 1

        if execution_state == 'ready':
            ready_entries += 1
            local_status = LOCAL_REMEDIATION_BY_CLASSIFICATION.get(
                classification,
                'ready_but_unclassified_fail_closed',
            )
            local_remediated_count += 1
            remediation_counts[local_status] += 1
            status_entries.append(
                {
                    'entry_id': entry_id,
                    'claim_id': claim_id,
                    'classification': classification,
                    'execution_state': execution_state,
                    'local_remediation_status': local_status,
                    'evidence': entry.get('evidence', {}),
                    'proof_promotion_allowed': False,
                    'production_promotion_allowed': False,
                    'next_task_ids': list(entry.get('next_task_ids', [])),
                }
            )
        else:
            blocked_count += 1
            blocked_entries.append(
                {
                    'entry_id': entry_id,
                    'claim_id': claim_id,
                    'classification': classification,
                    'execution_state': execution_state,
                    'blocked_by': list(entry.get('blocked_by', [])),
                    'next_actions': list(entry.get('next_actions', [])),
                    'proof_promotion_allowed': False,
                    'production_promotion_allowed': False,
                    'next_task_ids': list(entry.get('next_task_ids', [])),
                }
            )

    solver_summary = solver_portfolio_report.get('summary')
    if not isinstance(solver_summary, Mapping):
        solver_summary = {}
    fuzz_summary = fuzz_report.get('summary')
    if not isinstance(fuzz_summary, Mapping):
        fuzz_summary = {}

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_from_task_ids': ['PORTAL-CXTP-147', 'PORTAL-CXTP-148', 'PORTAL-CXTP-172'],
        'overall_status': (
            'source_bounded_remediation_complete_with_external_blockers'
            if blocked_count
            else 'source_bounded_remediation_complete'
        ),
        'security_decision': (
            'LOCAL_GAPS_REMEDIATED_PRODUCTION_STILL_BLOCKED'
            if blocked_count
            else 'LOCAL_GAPS_REMEDIATED_READY_FOR_REVIEW'
        ),
        'production_release_blocked': True,
        'testnet_assurance_promotion_allowed': False,
        'solver_portfolio_security_decision': solver_portfolio_report.get('security_decision'),
        'fuzz_security_decision': fuzz_summary.get('security_decision'),
        'summary': {
            'entry_count': ready_entries + blocked_count,
            'local_remediated_count': local_remediated_count,
            'external_blocked_count': blocked_count,
            'ready_count': ready_entries,
            'classification_counts': dict(sorted(classification_counts.items())),
            'local_remediation_status_counts': dict(sorted(remediation_counts.items())),
            'solver_fail_closed_claim_count': solver_summary.get('fail_closed_claim_count'),
            'solver_proved_claim_count': solver_summary.get('proved_claim_count'),
            'fuzz_counterexample_count': fuzz_summary.get('counterexample_count'),
            'fuzz_total_case_count': fuzz_summary.get('total_case_count'),
        },
        'locally_remediated_entries': sorted(status_entries, key=lambda item: str(item['entry_id'])),
        'blocked_entries': sorted(blocked_entries, key=lambda item: str(item['entry_id'])),
    }
    report['artifact_cid'] = calculate_artifact_cid(report)
    return report
