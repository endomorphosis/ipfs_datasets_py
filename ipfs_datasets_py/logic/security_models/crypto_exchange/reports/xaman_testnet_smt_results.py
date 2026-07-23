"""Final Z3/CVC5 claim-set result report for the frozen Xaman Testnet model."""

from __future__ import annotations

from typing import Any, Mapping

from ..compilers.to_smtlib import XAMAN_CRITICAL_SEVERITIES
from ..ir.cid import calculate_artifact_cid
from ..ir.schema import SecurityModelIR, validate_ir
from .xaman_testnet_smt_worker import (
    CVC5_RUNNER_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_WORKER_LOCK_PATH,
    TRACE_MAP_PATH,
    stable_sha256_model_cid,
)


SCHEMA_VERSION = 'xaman-testnet-z3-cvc5-differential-report/v1'
COUNTEREXAMPLE_SCHEMA_VERSION = 'xaman-testnet-smt-counterexample/v1'
COUNTEREXAMPLE_MANIFEST_SCHEMA_VERSION = 'xaman-testnet-smt-counterexample-manifest/v1'
TASK_ID = 'PORTAL-CXTP-133'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
PROOF_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json'
COUNTEREXAMPLE_DIR = 'security_ir_artifacts/corpora/xaman-app/testnet/counterexamples'
COUNTEREXAMPLE_MANIFEST_PATH = f'{COUNTEREXAMPLE_DIR}/manifest.json'
REQUIRED_SMT_LANES = ('z3', 'cvc5')


def build_xaman_testnet_smt_results(
    model_payload: Mapping[str, Any],
    *,
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    proof_worker_lock: Mapping[str, Any],
    cvc5_runner_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the final frozen Testnet claim-set result report."""

    model = validate_ir(SecurityModelIR.from_untrusted_dict(dict(model_payload), strict=True))
    calculated_model_cid = stable_sha256_model_cid(model)
    if calculated_model_cid != model_cid:
        raise ValueError(f'Testnet model CID mismatch: expected {model_cid}, calculated {calculated_model_cid}')
    _assert_bound_input('assumptions', assumptions_payload.get('model_cid'), model_cid)
    _assert_bound_input('proof worker lock', proof_worker_lock.get('model', {}).get('cid'), model_cid)
    _assert_bound_input('CVC5 runner report', cvc5_runner_report.get('model', {}).get('cid'), model_cid)

    expected_claim_ids = [
        claim['id']
        for claim in model.claims
        if str(claim.get('severity', '')).strip().lower() in XAMAN_CRITICAL_SEVERITIES
    ]
    runner_claims = list(cvc5_runner_report.get('claims', []))
    runner_claim_ids = [claim.get('claim_id') for claim in runner_claims]
    if runner_claim_ids != expected_claim_ids:
        raise ValueError('CVC5 runner report claim scope does not match the frozen Testnet model')

    assumption_index = _assumption_index(assumptions_payload)
    result_claims = [
        _claim_result(claim, assumption_index=assumption_index)
        for claim in runner_claims
    ]
    summary = _summary(result_claims)
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model.model_id,
            'schema_version': model.schema_version,
            'cid': model_cid,
        },
        'inputs': {
            'security_model_ir': {
                'path': MODEL_PATH,
                'cid': model_cid,
                'artifact_cid': calculate_artifact_cid(model.to_dict()),
            },
            'assumptions': {
                'path': ASSUMPTIONS_PATH,
                'model_cid': assumptions_payload['model_cid'],
                'artifact_cid': calculate_artifact_cid(assumptions_payload),
                'blocking_assumption_count': assumptions_payload.get('blocking_assumption_count'),
            },
            'proof_worker_lock': {
                'path': PROOF_WORKER_LOCK_PATH,
                'lock_cid': proof_worker_lock.get('lock_cid'),
                'worker_id': proof_worker_lock.get('worker', {}).get('id'),
            },
            'cvc5_runner_report': {
                'path': CVC5_RUNNER_REPORT_PATH,
                'report_cid': cvc5_runner_report.get('report_cid'),
                'overall_status': cvc5_runner_report.get('overall_status'),
                'security_decision': cvc5_runner_report.get('security_decision'),
            },
            'claim_trace_map': {
                'path': TRACE_MAP_PATH,
                'required_by_predecessor_task': 'PORTAL-CXTP-131',
            },
        },
        'proof_policy': {
            'required_smt_lanes': list(REQUIRED_SMT_LANES),
            'proved_rule': (
                'A claim/model/assumption tuple is PROVED only when Z3 and CVC5 both '
                'return unsat for the locked query, agree, and have no solver, '
                'unsupported-theory, counterexample, or blocking-assumption witness.'
            ),
            'non_secure_rule': (
                'Any SAT counterexample, solver blocker, incomplete lane, or unresolved '
                'assumption remains a NON_SECURE_TESTNET_RESULT with an owner/action.'
            ),
        },
        'counterexamples': {
            'directory': COUNTEREXAMPLE_DIR,
            'manifest_path': COUNTEREXAMPLE_MANIFEST_PATH,
        },
        'summary': summary,
        'claims': result_claims,
        'production_release_blocked': True,
        'testnet_assurance_blocked': summary['non_secure_testnet_result_count'] > 0,
        'overall_status': summary['overall_status'],
        'security_decision': summary['security_decision'],
    }
    report['artifact_cid'] = _artifact_cid_without_self(report)
    return report


def counterexample_artifacts(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return deterministic counterexample/witness artifacts for non-proved claims."""

    artifacts: dict[str, dict[str, Any]] = {}
    manifest_paths: list[str] = []
    for claim in report.get('claims', []):
        if not isinstance(claim, Mapping) or claim.get('result') == 'PROVED':
            continue
        rel_path = str(claim['counterexample_path'])
        witness = _counterexample_payload(report, claim)
        artifacts[rel_path] = witness
        manifest_paths.append(rel_path)

    manifest: dict[str, Any] = {
        'schema_version': COUNTEREXAMPLE_MANIFEST_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model_cid': report['model']['cid'],
        'counterexample_count': len(manifest_paths),
        'counterexamples': sorted(manifest_paths),
    }
    manifest['artifact_cid'] = _artifact_cid_without_self(manifest)
    artifacts[COUNTEREXAMPLE_MANIFEST_PATH] = manifest
    return artifacts


def _claim_result(claim: Mapping[str, Any], *, assumption_index: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    z3_result = str(claim.get('solver_results', {}).get('z3', {}).get('solver_result'))
    cvc5_result = str(claim.get('solver_results', {}).get('cvc5', {}).get('solver_result'))
    solver_agreement = bool(claim.get('solver_agreement'))
    assumption_ids = list(claim.get('blocked_by_assumptions', []))
    solver_blockers = list(claim.get('solver_blockers', []))
    classification = str(claim.get('classification'))
    result = _result_for_claim(
        z3_result=z3_result,
        cvc5_result=cvc5_result,
        solver_agreement=solver_agreement,
        solver_blockers=solver_blockers,
        assumption_ids=assumption_ids,
        classification=classification,
        unsupported_theory=bool(claim.get('unsupported_theory')),
    )
    owner_actions = [_owner_action(assumption_id, assumption_index) for assumption_id in assumption_ids]
    if result == 'INCOMPLETE' and not owner_actions:
        owner_actions = [
            {
                'owner': 'solver-verification',
                'action': 'Re-run the locked Z3/CVC5 Testnet worker and resolve solver blockers before proof promotion.',
                'source': 'solver_blocker',
                'solver_blockers': solver_blockers or ['incomplete SMT lane'],
            }
        ]

    counterexample_path = None
    if result != 'PROVED':
        counterexample_path = f'{COUNTEREXAMPLE_DIR}/{_safe_filename(str(claim["claim_id"]))}.json'

    return {
        'claim_id': claim['claim_id'],
        'claim_version': claim['claim_version'],
        'severity': claim['severity'],
        'domain': claim.get('domain'),
        'result': result,
        'security_result': 'SECURE_TESTNET_CLAIM' if result == 'PROVED' else 'NON_SECURE_TESTNET_RESULT',
        'proof_promotion_allowed': result == 'PROVED',
        'worker_classification': classification,
        'worker_classification_reason': claim.get('classification_reason'),
        'solver_tuple': {
            'z3': z3_result,
            'cvc5': cvc5_result,
            'agreement': solver_agreement,
        },
        'solver_blockers': solver_blockers,
        'blocked_by_assumptions': assumption_ids,
        'unsupported_theory': bool(claim.get('unsupported_theory')),
        'owner_actions': owner_actions,
        'counterexample_path': counterexample_path,
        'smtlib_artifact': claim.get('smtlib_artifact'),
        'evidence_refs': list(claim.get('evidence_refs', [])),
        'soundness_notes': list(claim.get('soundness_notes', [])),
    }


def _result_for_claim(
    *,
    z3_result: str,
    cvc5_result: str,
    solver_agreement: bool,
    solver_blockers: list[str],
    assumption_ids: list[str],
    classification: str,
    unsupported_theory: bool,
) -> str:
    if (
        classification == 'proved_candidate'
        and z3_result == cvc5_result == 'unsat'
        and solver_agreement
        and not solver_blockers
        and not assumption_ids
        and not unsupported_theory
    ):
        return 'PROVED'
    if solver_blockers or unsupported_theory or not solver_agreement or z3_result not in {'sat', 'unsat'} or cvc5_result not in {'sat', 'unsat'}:
        return 'INCOMPLETE'
    return 'COUNTEREXAMPLE'


def _counterexample_payload(report: Mapping[str, Any], claim: Mapping[str, Any]) -> dict[str, Any]:
    kind = 'incomplete_solver_witness' if claim['result'] == 'INCOMPLETE' else 'blocking_acceptance_counterexample'
    payload: dict[str, Any] = {
        'schema_version': COUNTEREXAMPLE_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model_cid': report['model']['cid'],
        'claim_id': claim['claim_id'],
        'claim_version': claim['claim_version'],
        'severity': claim['severity'],
        'domain': claim.get('domain'),
        'counterexample_kind': kind,
        'result': claim['result'],
        'security_result': 'NON_SECURE_TESTNET_RESULT',
        'acceptance_decision': 'REJECT_PROOF_PROMOTION',
        'worker_classification': claim['worker_classification'],
        'worker_classification_reason': claim['worker_classification_reason'],
        'solver_tuple': claim['solver_tuple'],
        'solver_blockers': claim['solver_blockers'],
        'blocked_by_assumptions': claim['blocked_by_assumptions'],
        'owner_actions': claim['owner_actions'],
        'smtlib_artifact': claim['smtlib_artifact'],
        'raw_sensitive_material_recorded': False,
        'soundness_notes': claim['soundness_notes'],
    }
    payload['artifact_cid'] = _artifact_cid_without_self(payload)
    return payload


def _summary(claims: list[Mapping[str, Any]]) -> dict[str, Any]:
    proved_count = sum(claim['result'] == 'PROVED' for claim in claims)
    counterexample_count = sum(claim['result'] == 'COUNTEREXAMPLE' for claim in claims)
    incomplete_count = sum(claim['result'] == 'INCOMPLETE' for claim in claims)
    non_secure_count = counterexample_count + incomplete_count
    if incomplete_count:
        overall_status = 'non_secure_with_incomplete_claims'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_INCOMPLETE_SMT_CLAIMS'
    elif counterexample_count:
        overall_status = 'non_secure_with_counterexamples'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_COUNTEREXAMPLES'
    else:
        overall_status = 'proved'
        security_decision = 'TESTNET_CLAIM_SET_PROVED_BY_Z3_AND_CVC5'
    return {
        'claim_count': len(claims),
        'proved_count': proved_count,
        'counterexample_count': counterexample_count,
        'incomplete_count': incomplete_count,
        'non_secure_testnet_result_count': non_secure_count,
        'proof_promotion_allowed_count': proved_count,
        'z3_cvc5_agreement_failure_count': sum(not bool(claim['solver_tuple']['agreement']) for claim in claims),
        'solver_blocker_count': sum(bool(claim['solver_blockers']) for claim in claims),
        'unsupported_theory_count': sum(bool(claim['unsupported_theory']) for claim in claims),
        'owner_action_count': sum(len(claim['owner_actions']) for claim in claims),
        'overall_status': overall_status,
        'security_decision': security_decision,
    }


def _owner_action(assumption_id: str, assumption_index: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    assumption = assumption_index.get(assumption_id)
    if assumption is None:
        return {
            'assumption_id': assumption_id,
            'owner': 'formalization-review',
            'action': 'Resolve missing assumption metadata before proof promotion.',
            'status': 'MISSING_METADATA',
        }
    return {
        'assumption_id': assumption_id,
        'owner': assumption.get('owner'),
        'status': assumption.get('status'),
        'action': '; '.join(str(item) for item in assumption.get('required_evidence_to_clear', [])),
        'required_evidence_to_clear': list(assumption.get('required_evidence_to_clear', [])),
        'description': assumption.get('description'),
        'evidence_expires_at': assumption.get('evidence_expires_at'),
    }


def _assumption_index(assumptions_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        assumption['id']: assumption
        for assumption in assumptions_payload.get('assumptions', [])
        if isinstance(assumption, Mapping) and isinstance(assumption.get('id'), str)
    }


def _assert_bound_input(name: str, actual_cid: Any, expected_cid: str) -> None:
    if actual_cid != expected_cid:
        raise ValueError(f'{name} model CID does not match the frozen Testnet model CID')


def _artifact_cid_without_self(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _safe_filename(claim_id: str) -> str:
    safe = ''.join(character if character.isalnum() or character in {'-', '_'} else '_' for character in claim_id)
    return safe or 'claim'


__all__ = [
    'ASSUMPTIONS_PATH',
    'COUNTEREXAMPLE_DIR',
    'COUNTEREXAMPLE_MANIFEST_PATH',
    'COUNTEREXAMPLE_MANIFEST_SCHEMA_VERSION',
    'COUNTEREXAMPLE_SCHEMA_VERSION',
    'PROOF_REPORT_PATH',
    'REQUIRED_SMT_LANES',
    'SCHEMA_VERSION',
    'TASK_ID',
    'build_xaman_testnet_smt_results',
    'counterexample_artifacts',
]
