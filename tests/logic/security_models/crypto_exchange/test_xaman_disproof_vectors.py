import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
VECTORS_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'disproof-vectors.json'
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'counterexample-report.json'
IR_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'security-model-ir.json'
CID_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'security-model-ir.cid'


REQUIRED_TACTICS = {
    'assumption_mutation',
    'auth_precondition_removal',
    'stale_evidence',
    'wrong_network',
    'replay_payload',
    'downgraded_solver',
    'unsupported_xrpl_semantics',
    'backend_trust_failure',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_disproof_vectors_schema_and_model_binding() -> None:
    vectors = _load_json(VECTORS_PATH)
    cid = CID_PATH.read_text(encoding='utf-8').strip()

    assert vectors['schema_version'] == 'xaman-disproof-vectors/v1'
    assert vectors['task_id'] == 'PORTAL-CXTP-070'
    assert vectors['model']['path'] == 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
    assert vectors['model']['cid'] == cid
    assert vectors['security_decision'] == 'DISPROOF_SUITE_FAIL_CLOSED'


def test_xaman_disproof_vectors_cover_required_tactics_and_claims() -> None:
    vectors = _load_json(VECTORS_PATH)
    ir = _load_json(IR_PATH)
    claim_ids = {claim['id'] for claim in ir['claims']}

    entries = vectors['vectors']
    assert len(entries) >= 8
    assert REQUIRED_TACTICS <= {entry['tactic'] for entry in entries}
    assert all(entry['claim_id'] in claim_ids for entry in entries)
    assert all(entry['expected_outcome'] in {'counterexample_found', 'blocked_by_missing_evidence'} for entry in entries)


def test_xaman_counterexample_report_records_found_and_blocked_results() -> None:
    report = _load_json(REPORT_PATH)

    assert report['schema_version'] == 'xaman-counterexample-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-070'
    assert report['overall_status'] == 'blocked'
    assert report['production_release_blocked'] is True
    assert report['summary']['counterexample_found_count'] >= 4
    assert report['summary']['blocked_count'] >= 2


def test_xaman_counterexample_report_fail_closed_cases() -> None:
    report = _load_json(REPORT_PATH)
    by_id = {entry['vector_id']: entry for entry in report['results']}

    assert by_id['xaman-disproof:auth-precondition-removal']['result'] == 'counterexample_found'
    assert by_id['xaman-disproof:wrong-network-signing']['result'] == 'counterexample_found'
    assert by_id['xaman-disproof:backend-double-use']['result'] == 'blocked_by_missing_evidence'
    assert by_id['xaman-disproof:runtime-equivalence-missing']['result'] == 'blocked_by_missing_evidence'
    assert all(entry['release_policy'] == 'block' for entry in report['results'])


def test_xaman_counterexample_report_references_all_vectors() -> None:
    vectors = _load_json(VECTORS_PATH)
    report = _load_json(REPORT_PATH)

    vector_ids = {entry['id'] for entry in vectors['vectors']}
    result_ids = {entry['vector_id'] for entry in report['results']}
    assert vector_ids == result_ids
