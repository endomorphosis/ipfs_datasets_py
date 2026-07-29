"""Xaman assurance packet aggregation.

The packet built here is intentionally a release decision artifact, not a new
proof.  It binds the current Xaman source corpus, model CID, solver state,
formal reports, disproof reports, runtime trace report, assumptions, and open
blockers into one fail-closed decision envelope.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid

SCHEMA_VERSION = 'xaman-assurance-packet/v1'
TASK_ID = 'PORTAL-CXTP-075'
FIXED_GENERATED_AT_UTC = '2026-07-08T22:00:00Z'

MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
SOURCE_MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
SOURCE_COVERAGE_PATH = 'security_ir_artifacts/corpora/xaman-app/source-coverage.json'
ENVIRONMENT_PROBE_PATH = 'security_ir_artifacts/corpora/xaman-app/environment-probe.json'
SECURITY_CLAIMS_PATH = 'security_ir_artifacts/corpora/xaman-app/security-claims.json'
SMTLIB_MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/smtlib/manifest.json'
SMT_DIFFERENTIAL_PATH = 'security_ir_artifacts/corpora/xaman-app/proof-reports/z3-cvc5-differential.json'
DISPROOF_VECTORS_PATH = 'security_ir_artifacts/corpora/xaman-app/disproof-vectors.json'
COUNTEREXAMPLE_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/counterexample-report.json'
TLA_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json'
PROTOCOL_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json'
PROOF_CONSUMER_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
RUNTIME_TRACE_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json'

DECISION_POLICY_PATH = 'docs/security_verification/production_release_decision_policy.md'
RELEASE_RUNBOOK_PATH = 'docs/security_verification/release_gate_runbook.md'

CRITICAL_GATES = {'blocking', 'high'}
FAIL_CLOSED_DECISION = 'blocked-production'
ASSUMPTION_BLOCKED_OUTCOME = 'stale-evidence'


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    for key in ('artifact_cid', 'report_cid'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return calculate_artifact_cid(payload)


def _packet_cid(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid(
        {
            key: value
            for key, value in payload.items()
            if key != 'artifact_cid'
        }
    )


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def _artifact_index_entry(path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    entry = {
        'path': path,
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'artifact_cid': _artifact_cid(payload),
    }
    model_cid = payload.get('model_cid')
    if isinstance(model_cid, str) and model_cid:
        entry['model_cid'] = model_cid
    return entry


def _source_summary(
    source_manifest: Mapping[str, Any],
    source_coverage: Mapping[str, Any],
) -> dict[str, Any]:
    source = source_manifest['source']
    reproducibility = source_manifest['reproducibility']
    return {
        'corpus': source_manifest['corpus'],
        'repo_url': source['repo_url'],
        'commit_sha': source['commit_sha'],
        'requested_ref': source['requested_ref'],
        'manifest': {
            'path': SOURCE_MANIFEST_PATH,
            'schema_version': source_manifest['schema_version'],
            'artifact_cid': _artifact_cid(source_manifest),
            'aggregate_sha256': reproducibility['aggregate_sha256'],
            'file_count': reproducibility['file_count'],
            'total_size_bytes': reproducibility['total_size_bytes'],
            'exact_commit_required': reproducibility['exact_commit_required'],
            'fail_closed': reproducibility['fail_closed'],
            'required_dependency_lockfiles': deepcopy(
                reproducibility['required_dependency_lockfiles']
            ),
            'required_license_files': deepcopy(reproducibility['required_license_files']),
            'required_security_disclosure_files': deepcopy(
                reproducibility['required_security_disclosure_files']
            ),
        },
        'coverage': {
            'path': SOURCE_COVERAGE_PATH,
            'schema_version': source_coverage['schema_version'],
            'artifact_cid': _artifact_cid(source_coverage),
            'coverage_summary': deepcopy(source_coverage['coverage_summary']),
        },
    }


def _assumption_summary(security_claims: Mapping[str, Any]) -> dict[str, Any]:
    assumptions = list(security_claims['assumptions'])
    status_counts: dict[str, int] = {}
    for assumption in assumptions:
        status = str(assumption['status'])
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        'path': SECURITY_CLAIMS_PATH,
        'total': len(assumptions),
        'status_counts': status_counts,
        'blocking_assumption_ids': [
            assumption['id']
            for assumption in assumptions
            if assumption['status'] == 'BLOCKING'
        ],
        'evidenced_assumption_ids': [
            assumption['id']
            for assumption in assumptions
            if assumption['status'] == 'EVIDENCED'
        ],
        'assumptions': [
            {
                'id': assumption['id'],
                'category': assumption['category'],
                'severity': assumption['severity'],
                'status': assumption['status'],
                'statement': assumption['statement'],
                'blocking_reason': assumption.get('blocking_reason'),
                'required_evidence_to_accept': deepcopy(
                    assumption.get('required_evidence_to_accept', [])
                ),
                'evidence': deepcopy(assumption.get('evidence', [])),
            }
            for assumption in assumptions
        ],
    }


def _claim_decisions(security_claims: Mapping[str, Any]) -> list[dict[str, Any]]:
    assumption_status = {
        assumption['id']: assumption['status']
        for assumption in security_claims['assumptions']
    }
    decisions = []
    for claim in security_claims['security_claims']:
        blocking_assumptions = [
            assumption_id
            for assumption_id in claim.get('blocking_assumption_ids', [])
            if assumption_status.get(assumption_id) == 'BLOCKING'
        ]
        critical = claim['release_gate'] in CRITICAL_GATES
        decisions.append(
            {
                'claim_id': claim['id'],
                'category': claim['category'],
                'release_gate': claim['release_gate'],
                'source_status': claim['status'],
                'consumer_outcome': (
                    ASSUMPTION_BLOCKED_OUTCOME
                    if blocking_assumptions
                    else FAIL_CLOSED_DECISION
                ),
                'secure_for_release': False,
                'release_effect': FAIL_CLOSED_DECISION if critical else 'not-release-critical',
                'blocking_assumption_ids': blocking_assumptions,
                'required_assumption_ids': deepcopy(claim.get('assumption_ids', [])),
                'evidence_fact_ids': deepcopy(claim.get('evidence_fact_ids', [])),
                'reason': (
                    'Claim is blocked by unaccepted assumptions and has no PROVED release packet.'
                    if blocking_assumptions
                    else 'Claim has no accepted PROVED release packet.'
                ),
            }
        )
    return decisions


def _solver_matrix(
    environment_probe: Mapping[str, Any],
    tla_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    matrix = []
    resolved = environment_probe['solver_paths']['resolved_executables']
    for solver_name in sorted(resolved):
        entry = resolved[solver_name]
        matrix.append(
            {
                'solver': solver_name,
                'source': ENVIRONMENT_PROBE_PATH,
                'status': entry['status'],
                'available': entry['status'] == 'present',
                'required': entry['required'],
                'version': entry.get('version'),
                'executable': entry.get('executable'),
                'release_effect': (
                    'available-for-configured-gate'
                    if entry['status'] == 'present'
                    else 'missing-solver'
                ),
            }
        )

    apalache = tla_report['apalache']
    matrix.append(
        {
            'solver': 'apalache',
            'source': TLA_REPORT_PATH,
            'status': apalache['status'],
            'available': apalache['available'],
            'required': True,
            'version': apalache.get('version'),
            'executable': apalache.get('executable'),
            'release_effect': 'missing-solver',
            'blocker': deepcopy(apalache.get('blocker')),
        }
    )

    for solver_name, solver in sorted(protocol_report['solvers'].items()):
        matrix.append(
            {
                'solver': solver['solver'],
                'source': PROTOCOL_REPORT_PATH,
                'status': solver['status'],
                'available': solver['available'],
                'required': True,
                'version': solver.get('version'),
                'executable': solver.get('executable'),
                'release_effect': 'missing-solver',
                'blocker': deepcopy(solver.get('blocker')),
                'report_key': solver_name,
            }
        )
    return matrix


def _proof_reports(
    smtlib_manifest: Mapping[str, Any],
    differential_report: Mapping[str, Any],
    tla_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    proof_consumer_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            'id': 'xaman-smt-z3-cvc5-differential',
            'path': SMT_DIFFERENTIAL_PATH,
            'smtlib_manifest_path': SMTLIB_MANIFEST_PATH,
            'schema_version': differential_report['schema_version'],
            'task_id': differential_report['task_id'],
            'model_cid': differential_report['model_cid'],
            'artifact_cid': _artifact_cid(differential_report),
            'smtlib_manifest_cid': differential_report['smtlib_manifest_cid'],
            'smtlib_artifact_count': len(smtlib_manifest['artifacts']),
            'selected_provers': deepcopy(differential_report['selected_provers']),
            'summary': deepcopy(differential_report['summary']),
            'release_effect': (
                'no-release-unblock'
                if not differential_report['summary']['release_ready']
                else 'eligible-for-acceptance'
            ),
        },
        {
            'id': 'xaman-tla-apalache-workflow',
            'path': TLA_REPORT_PATH,
            'schema_version': tla_report['schema_version'],
            'task_id': tla_report['task_id'],
            'model_cid': tla_report['model_cid'],
            'artifact_cid': _artifact_cid(tla_report),
            'summary': deepcopy(tla_report['summary']),
            'solver': deepcopy(tla_report['apalache']),
            'release_effect': 'missing-solver',
        },
        {
            'id': 'xaman-symbolic-protocol',
            'path': PROTOCOL_REPORT_PATH,
            'schema_version': protocol_report['schema_version'],
            'task_id': protocol_report['task_id'],
            'model_cid': protocol_report['model_cid'],
            'artifact_cid': _artifact_cid(protocol_report),
            'summary': deepcopy(protocol_report['summary']),
            'solvers': deepcopy(protocol_report['solvers']),
            'release_effect': 'missing-solver',
        },
        {
            'id': 'xaman-proof-consumer-invariants',
            'path': PROOF_CONSUMER_REPORT_PATH,
            'schema_version': proof_consumer_report['schema_version'],
            'task_id': proof_consumer_report['task_id'],
            'model_cid': proof_consumer_report['model_cid'],
            'artifact_cid': _artifact_cid(proof_consumer_report),
            'summary': deepcopy(proof_consumer_report['summary']),
            'accepted_verdict': deepcopy(proof_consumer_report['accepted_verdict']),
            'release_effect': proof_consumer_report['summary']['production_release_effect'],
        },
    ]


def _disproof_reports(
    disproof_vectors: Mapping[str, Any],
    counterexample_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            'id': 'xaman-disproof-vectors',
            'path': DISPROOF_VECTORS_PATH,
            'schema_version': disproof_vectors['schema_version'],
            'task_id': disproof_vectors['task_id'],
            'artifact_cid': _artifact_cid(disproof_vectors),
            'summary': deepcopy(disproof_vectors['summary']),
            'release_effect': 'counterexamples-preserved-and-blocked-cases-recorded',
        },
        {
            'id': 'xaman-counterexample-report',
            'path': COUNTEREXAMPLE_REPORT_PATH,
            'schema_version': counterexample_report['schema_version'],
            'task_id': counterexample_report['task_id'],
            'artifact_cid': _artifact_cid(counterexample_report),
            'summary': deepcopy(counterexample_report['summary']),
            'release_effect': (
                'disproof-gate-passed'
                if counterexample_report['summary']['scenario_failures'] == 0
                else FAIL_CLOSED_DECISION
            ),
        },
    ]


def _runtime_trace_summary(runtime_trace_report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'path': RUNTIME_TRACE_REPORT_PATH,
        'schema_version': runtime_trace_report['schema_version'],
        'task_id': runtime_trace_report['task_id'],
        'artifact_cid': _artifact_cid(runtime_trace_report),
        'trace_inputs': deepcopy(runtime_trace_report['trace_inputs']),
        'monitor_coverage': deepcopy(runtime_trace_report['monitor_coverage']),
        'blocking_runtime_equivalence': deepcopy(
            runtime_trace_report['blocking_runtime_equivalence']
        ),
        'runtime_trace_count': len(runtime_trace_report['runtime_traces']),
        'monitor_fact_count': len(runtime_trace_report['monitor_facts']),
        'trace_statuses': [
            {
                'id': trace['id'],
                'source_path': trace['source_path'],
                'device_class': trace['device_class'],
                'conformance_status': trace['conformance_status'],
                'event_categories': [
                    event['category']
                    for event in trace['events']
                ],
            }
            for trace in runtime_trace_report['runtime_traces']
        ],
        'release_effect': FAIL_CLOSED_DECISION,
    }


def _assumption_blockers(
    security_claims: Mapping[str, Any],
) -> list[dict[str, Any]]:
    claim_ids_by_assumption: dict[str, list[str]] = {}
    for claim in security_claims['security_claims']:
        for assumption_id in claim.get('blocking_assumption_ids', []):
            claim_ids_by_assumption.setdefault(assumption_id, []).append(claim['id'])

    blockers = []
    for assumption in security_claims['assumptions']:
        if assumption['status'] != 'BLOCKING':
            continue
        blockers.append(
            {
                'id': f'blocker:assumption:{_slug(assumption["id"])}',
                'type': 'blocking_assumption',
                'severity': assumption['severity'],
                'assumption_id': assumption['id'],
                'category': assumption['category'],
                'blocked_claim_ids': sorted(claim_ids_by_assumption.get(assumption['id'], [])),
                'reason': assumption.get('blocking_reason'),
                'required_evidence_to_close': deepcopy(
                    assumption.get('required_evidence_to_accept', [])
                ),
                'release_effect': FAIL_CLOSED_DECISION,
            }
        )
    return blockers


def _solver_blockers(
    tla_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers = []
    apalache = tla_report['apalache']
    if not apalache['available']:
        blockers.append(
            {
                'id': 'blocker:solver:apalache',
                'type': 'missing_solver',
                'severity': 'blocking',
                'solver': 'apalache',
                'source_report': TLA_REPORT_PATH,
                'blocked_property_count': tla_report['summary']['blocked_property_count'],
                'reason': apalache['blocker']['message'],
                'required_evidence_to_close': [apalache['blocker']['required_action']],
                'release_effect': FAIL_CLOSED_DECISION,
            }
        )
    for solver_key, solver in sorted(protocol_report['solvers'].items()):
        if solver['available']:
            continue
        blockers.append(
            {
                'id': f'blocker:solver:{_slug(solver["solver"])}',
                'type': 'missing_solver',
                'severity': 'blocking',
                'solver': solver['solver'],
                'source_report': PROTOCOL_REPORT_PATH,
                'blocked_property_count': protocol_report['summary']['blocked_property_count'],
                'reason': solver['blocker']['message'],
                'required_evidence_to_close': [solver['blocker']['required_action']],
                'release_effect': FAIL_CLOSED_DECISION,
                'report_key': solver_key,
            }
        )
    return blockers


def _runtime_blockers(runtime_trace_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocker = runtime_trace_report['blocking_runtime_equivalence']
    if blocker['status'] != 'BLOCKING':
        return []
    return [
        {
            'id': 'blocker:runtime:real-device-traces-absent',
            'type': 'runtime_equivalence_gap',
            'severity': 'blocking',
            'source_report': RUNTIME_TRACE_REPORT_PATH,
            'blocking_gap_ids': deepcopy(blocker['blocking_gap_ids']),
            'reason': 'Release-window real-device runtime traces are absent.',
            'required_evidence_to_close': deepcopy(blocker['required_evidence']),
            'release_effect': FAIL_CLOSED_DECISION,
        }
    ]


def _proof_blockers(
    security_claims: Mapping[str, Any],
    differential_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    critical_claim_ids = [
        claim['id']
        for claim in security_claims['security_claims']
        if claim['release_gate'] in CRITICAL_GATES
    ]
    if differential_report['summary']['proved'] == len(critical_claim_ids):
        return []
    return [
        {
            'id': 'blocker:proof:no-critical-claim-proved',
            'type': 'proof_gap',
            'severity': 'blocking',
            'source_report': SMT_DIFFERENTIAL_PATH,
            'blocked_claim_ids': critical_claim_ids,
            'reason': (
                f'{differential_report["summary"]["proved"]} of '
                f'{len(critical_claim_ids)} critical claims have a PROVED release outcome.'
            ),
            'required_evidence_to_close': [
                'Resolve blocking assumptions for each critical claim.',
                'Regenerate SMT/TLA/protocol proof reports with accepted solver output.',
                'Bind accepted proof reports to receipts or trusted signatures.',
            ],
            'release_effect': FAIL_CLOSED_DECISION,
        }
    ]


def _open_blockers(
    *,
    security_claims: Mapping[str, Any],
    differential_report: Mapping[str, Any],
    tla_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    runtime_trace_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers = []
    blockers.extend(_assumption_blockers(security_claims))
    blockers.extend(_proof_blockers(security_claims, differential_report))
    blockers.extend(_solver_blockers(tla_report, protocol_report))
    blockers.extend(_runtime_blockers(runtime_trace_report))
    return blockers


def _release_decision(
    *,
    claim_decisions: Sequence[Mapping[str, Any]],
    open_blockers: Sequence[Mapping[str, Any]],
    differential_report: Mapping[str, Any],
    counterexample_report: Mapping[str, Any],
    runtime_trace_report: Mapping[str, Any],
) -> dict[str, Any]:
    critical_claims = [
        decision
        for decision in claim_decisions
        if decision['release_gate'] in CRITICAL_GATES
    ]
    proved_critical_claims = [
        decision
        for decision in critical_claims
        if decision['consumer_outcome'] == 'prove' and decision['secure_for_release']
    ]
    return {
        'decision': FAIL_CLOSED_DECISION,
        'release_ready': False,
        'fail_closed': True,
        'policy': {
            'document_path': DECISION_POLICY_PATH,
            'runbook_path': RELEASE_RUNBOOK_PATH,
            'required_secure_outcome': 'prove',
            'non_prove_effect': FAIL_CLOSED_DECISION,
        },
        'critical_claim_count': len(critical_claims),
        'proved_critical_claim_count': len(proved_critical_claims),
        'open_blocker_count': len(open_blockers),
        'rationale': [
            (
                f'{len(proved_critical_claims)} of {len(critical_claims)} '
                'blocking/high Xaman claims have a PROVED release outcome.'
            ),
            (
                f'SMT differential release_ready is '
                f'{differential_report["summary"]["release_ready"]}.'
            ),
            (
                f'Disproof scenario_failures is '
                f'{counterexample_report["summary"]["scenario_failures"]}; '
                'counterexample and explicitly blocked vectors remain archived.'
            ),
            (
                'Runtime equivalence is BLOCKING because real-device release-window '
                f'traces count is {runtime_trace_report["trace_inputs"]["real_device_trace_count"]}.'
            ),
            'All non-prove, missing-solver, stale-evidence, and runtime-gap states fail closed.',
        ],
    }


def build_xaman_assurance_packet(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    source_manifest: Mapping[str, Any],
    source_coverage: Mapping[str, Any],
    environment_probe: Mapping[str, Any],
    security_claims: Mapping[str, Any],
    smtlib_manifest: Mapping[str, Any],
    differential_report: Mapping[str, Any],
    disproof_vectors: Mapping[str, Any],
    counterexample_report: Mapping[str, Any],
    tla_report: Mapping[str, Any],
    protocol_report: Mapping[str, Any],
    proof_consumer_report: Mapping[str, Any],
    runtime_trace_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic Xaman assurance packet and release decision."""

    claim_decisions = _claim_decisions(security_claims)
    open_blockers = _open_blockers(
        security_claims=security_claims,
        differential_report=differential_report,
        tla_report=tla_report,
        protocol_report=protocol_report,
        runtime_trace_report=runtime_trace_report,
    )
    packet = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': FIXED_GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'model_cid': model_cid,
            'model_id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'claim_count': len(model_payload['claims']),
            'assumption_count': len(model_payload['assumptions']),
            'proof_obligation_count': len(model_payload['proof_obligations']),
            'solver_result_count': len(model_payload['solver_results']),
        },
        'source': _source_summary(source_manifest, source_coverage),
        'environment_probe': {
            'path': ENVIRONMENT_PROBE_PATH,
            'schema_version': environment_probe['schema_version'],
            'task_id': environment_probe['task_id'],
            'artifact_cid': _artifact_cid(environment_probe),
            'generated_at_utc': environment_probe['generated_at_utc'],
            'overall_status': environment_probe['overall_status'],
            'security_decision': environment_probe['security_decision'],
            'proof_acceptance_blocked': environment_probe['proof_acceptance_blocked'],
            'solver_probe_path': environment_probe['solver_paths']['solver_probe_path'],
        },
        'artifact_index': [
            _artifact_index_entry(MODEL_PATH, model_payload),
            _artifact_index_entry(SOURCE_MANIFEST_PATH, source_manifest),
            _artifact_index_entry(SOURCE_COVERAGE_PATH, source_coverage),
            _artifact_index_entry(ENVIRONMENT_PROBE_PATH, environment_probe),
            _artifact_index_entry(SECURITY_CLAIMS_PATH, security_claims),
            _artifact_index_entry(SMTLIB_MANIFEST_PATH, smtlib_manifest),
            _artifact_index_entry(SMT_DIFFERENTIAL_PATH, differential_report),
            _artifact_index_entry(DISPROOF_VECTORS_PATH, disproof_vectors),
            _artifact_index_entry(COUNTEREXAMPLE_REPORT_PATH, counterexample_report),
            _artifact_index_entry(TLA_REPORT_PATH, tla_report),
            _artifact_index_entry(PROTOCOL_REPORT_PATH, protocol_report),
            _artifact_index_entry(PROOF_CONSUMER_REPORT_PATH, proof_consumer_report),
            _artifact_index_entry(RUNTIME_TRACE_REPORT_PATH, runtime_trace_report),
        ],
        'proof_reports': _proof_reports(
            smtlib_manifest,
            differential_report,
            tla_report,
            protocol_report,
            proof_consumer_report,
        ),
        'disproof_reports': _disproof_reports(disproof_vectors, counterexample_report),
        'solver_matrix': _solver_matrix(environment_probe, tla_report, protocol_report),
        'runtime_traces': _runtime_trace_summary(runtime_trace_report),
        'assumptions': _assumption_summary(security_claims),
        'claim_decisions': claim_decisions,
        'open_blockers': open_blockers,
        'release_decision': _release_decision(
            claim_decisions=claim_decisions,
            open_blockers=open_blockers,
            differential_report=differential_report,
            counterexample_report=counterexample_report,
            runtime_trace_report=runtime_trace_report,
        ),
    }
    packet['artifact_cid'] = _packet_cid(packet)
    return packet


__all__ = [
    'COUNTEREXAMPLE_REPORT_PATH',
    'DISPROOF_VECTORS_PATH',
    'ENVIRONMENT_PROBE_PATH',
    'FAIL_CLOSED_DECISION',
    'MODEL_CID_PATH',
    'MODEL_PATH',
    'PROOF_CONSUMER_REPORT_PATH',
    'PROTOCOL_REPORT_PATH',
    'RUNTIME_TRACE_REPORT_PATH',
    'SCHEMA_VERSION',
    'SECURITY_CLAIMS_PATH',
    'SMTLIB_MANIFEST_PATH',
    'SMT_DIFFERENTIAL_PATH',
    'SOURCE_COVERAGE_PATH',
    'SOURCE_MANIFEST_PATH',
    'TASK_ID',
    'TLA_REPORT_PATH',
    'build_xaman_assurance_packet',
]
