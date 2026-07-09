import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_disproof_suite import (
    SCHEMA_VERSION,
    TASK_ID,
    build_xaman_disproof_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
DISPROOF_VECTORS_PATH = CORPUS_DIR / 'disproof-vectors.json'
COUNTEREXAMPLE_REPORT_PATH = CORPUS_DIR / 'counterexample-report.json'

REQUIRED_MUTATION_CLASSES = {
    'mutated_assumption',
    'auth_precondition_removed',
    'stale_evidence',
    'wrong_network',
    'replay_payload',
    'downgraded_solver',
    'unsupported_xrpl_semantics',
    'backend_trust_failure',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def test_xaman_disproof_artifacts_are_generated_from_current_model() -> None:
    model = _load_json(MODEL_PATH)
    model_cid = MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    expected_vectors, expected_report = build_xaman_disproof_artifacts(
        model,
        model_cid=model_cid,
    )

    checked_in_vectors = _load_json(DISPROOF_VECTORS_PATH)
    checked_in_report = _load_json(COUNTEREXAMPLE_REPORT_PATH)

    assert checked_in_vectors == expected_vectors
    assert checked_in_report == expected_report
    assert checked_in_vectors['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in_vectors)
    )
    assert checked_in_report['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in_report)
    )


def test_xaman_disproof_vectors_cover_required_mutation_classes() -> None:
    model = _load_json(MODEL_PATH)
    vectors = _load_json(DISPROOF_VECTORS_PATH)

    claim_ids = {claim['id'] for claim in model['claims']}
    assumption_ids = {assumption['id'] for assumption in model['assumptions']}
    classes = {vector['mutation_class'] for vector in vectors['vectors']}

    assert vectors['schema_version'] == SCHEMA_VERSION
    assert vectors['task_id'] == TASK_ID
    assert vectors['model_id'] == model['model_id']
    assert vectors['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert classes == REQUIRED_MUTATION_CLASSES
    assert vectors['summary']['vector_count'] == len(REQUIRED_MUTATION_CLASSES)
    assert vectors['summary']['counterexample_count'] == 6
    assert vectors['summary']['explicitly_blocked_count'] == 2

    for vector in vectors['vectors']:
        assert vector['claim_id'] in claim_ids
        assert set(vector['related_assumptions']) <= assumption_ids
        assert set(vector['blocking_assumptions']) <= assumption_ids
        assert vector['proof_or_trace_cid'] == calculate_artifact_cid(
            {
                key: value
                for key, value in vector.items()
                if key not in {'proof_or_trace_cid', 'vector_cid'}
            }
        )
        assert vector['vector_cid'] == vector['proof_or_trace_cid']
        assert vector['baseline_tactic']
        assert vector['evidence_refs']


def test_xaman_counterexample_report_finds_or_blocks_expected_scenarios() -> None:
    report = _load_json(COUNTEREXAMPLE_REPORT_PATH)
    vectors = _load_json(DISPROOF_VECTORS_PATH)
    vectors_by_scenario = {
        vector['scenario_id']: vector
        for vector in vectors['vectors']
    }

    assert report['schema_version'] == 'xaman-counterexample-report/v1'
    assert report['task_id'] == TASK_ID
    assert report['summary']['scenario_failures'] == 0
    assert report['summary']['counterexample_count'] == 6
    assert report['summary']['explicitly_blocked_count'] == 2
    assert report['vectors_artifact_cid'] == vectors['artifact_cid']

    for scenario in report['scenarios']:
        vector = vectors_by_scenario[scenario['scenario_id']]
        assert scenario['status'] == vector['status']
        assert scenario['proof_or_trace_cid'] == vector['proof_or_trace_cid']
        assert scenario['counterexample_found'] or scenario['explicitly_blocked']
        if scenario['status'] == 'DISPROVED':
            assert scenario['counterexample_found'] is True
            assert scenario['explicitly_blocked'] is False
            counterexample = vector['counterexample']
            assert isinstance(counterexample, dict)
            assert counterexample['trace']
            assert counterexample['violating_event_ids']
            assert counterexample['mutation_class'] == vector['mutation_class']
        elif scenario['status'] == 'EXPLICITLY_BLOCKED':
            assert scenario['counterexample_found'] is False
            assert scenario['explicitly_blocked'] is True
            blocked_reason = vector['blocked_reason']
            assert isinstance(blocked_reason, dict)
            assert set(blocked_reason['expected_blockers']) <= set(
                blocked_reason['claim_blocking_assumptions']
            )
        else:  # pragma: no cover
            raise AssertionError(f'unexpected status {scenario["status"]}')


def test_xaman_disproof_vectors_encode_specific_acceptance_cases() -> None:
    vectors = _load_json(DISPROOF_VECTORS_PATH)
    by_class = {
        vector['mutation_class']: vector
        for vector in vectors['vectors']
    }

    assumption = by_class['mutated_assumption']
    assert assumption['mutation']['assumption_id'] == (
        'xaman-security:assumption:native-vault-cryptographic-confidentiality'
    )
    assert assumption['status'] == 'DISPROVED'

    auth = by_class['auth_precondition_removed']
    assert 'fresh_passcode_or_biometric_authorization' in auth['mutation'][
        'removed_preconditions'
    ]
    assert auth['counterexample']['trace'][-1]['auth_success_seen'] is False

    stale = by_class['stale_evidence']
    assert stale['mutation']['to'] < stale['mutation']['release_window_date']

    wrong_network = by_class['wrong_network']
    assert wrong_network['mutation']['payload_force_network'] != wrong_network[
        'mutation'
    ]['active_app_network']

    replay = by_class['replay_payload']
    replay_trace = replay['counterexample']['trace']
    assert replay_trace[0]['payload_uuid'] == replay_trace[1]['payload_uuid']

    solver = by_class['downgraded_solver']
    assert solver['status'] == 'EXPLICITLY_BLOCKED'
    assert solver['mutation']['removed_solver'] == 'cvc5'

    xrpl = by_class['unsupported_xrpl_semantics']
    assert xrpl['status'] == 'EXPLICITLY_BLOCKED'
    assert {'TrustSet', 'SignerListSet'} <= set(xrpl['mutation']['transaction_types'])

    backend = by_class['backend_trust_failure']
    assert backend['status'] == 'DISPROVED'
    assert backend['mutation']['backend_authorized'] is False
