import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
    calculate_model_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_assurance_packet import (
    COUNTEREXAMPLE_REPORT_PATH,
    DISPROOF_VECTORS_PATH,
    ENVIRONMENT_PROBE_PATH,
    FAIL_CLOSED_DECISION,
    MODEL_PATH,
    PROOF_CONSUMER_REPORT_PATH,
    PROTOCOL_REPORT_PATH,
    RUNTIME_TRACE_REPORT_PATH,
    SCHEMA_VERSION,
    SECURITY_CLAIMS_PATH,
    SMTLIB_MANIFEST_PATH,
    SMT_DIFFERENTIAL_PATH,
    SOURCE_COVERAGE_PATH,
    SOURCE_MANIFEST_PATH,
    TASK_ID,
    TLA_REPORT_PATH,
    build_xaman_assurance_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
PACKET_PATH = CORPUS_DIR / 'assurance-packet.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
ASSURANCE_DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_assurance_packet.md'
RELEASE_DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_release_decision.md'

EXPECTED_ARTIFACT_PATHS = {
    MODEL_PATH,
    SOURCE_MANIFEST_PATH,
    SOURCE_COVERAGE_PATH,
    ENVIRONMENT_PROBE_PATH,
    SECURITY_CLAIMS_PATH,
    SMTLIB_MANIFEST_PATH,
    SMT_DIFFERENTIAL_PATH,
    DISPROOF_VECTORS_PATH,
    COUNTEREXAMPLE_REPORT_PATH,
    TLA_REPORT_PATH,
    PROTOCOL_REPORT_PATH,
    PROOF_CONSUMER_REPORT_PATH,
    RUNTIME_TRACE_REPORT_PATH,
}


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / path).read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def _expected_packet() -> dict[str, Any]:
    return build_xaman_assurance_packet(
        model_payload=_load_json(MODEL_PATH),
        model_cid=MODEL_CID_PATH.read_text(encoding='utf-8').strip(),
        source_manifest=_load_json(SOURCE_MANIFEST_PATH),
        source_coverage=_load_json(SOURCE_COVERAGE_PATH),
        environment_probe=_load_json(ENVIRONMENT_PROBE_PATH),
        security_claims=_load_json(SECURITY_CLAIMS_PATH),
        smtlib_manifest=_load_json(SMTLIB_MANIFEST_PATH),
        differential_report=_load_json(SMT_DIFFERENTIAL_PATH),
        disproof_vectors=_load_json(DISPROOF_VECTORS_PATH),
        counterexample_report=_load_json(COUNTEREXAMPLE_REPORT_PATH),
        tla_report=_load_json(TLA_REPORT_PATH),
        protocol_report=_load_json(PROTOCOL_REPORT_PATH),
        proof_consumer_report=_load_json(PROOF_CONSUMER_REPORT_PATH),
        runtime_trace_report=_load_json(RUNTIME_TRACE_REPORT_PATH),
    )


def test_xaman_assurance_packet_is_generated_from_current_evidence() -> None:
    checked_in = _load_json(PACKET_PATH)
    expected = _expected_packet()
    model_payload = _load_json(MODEL_PATH)

    assert checked_in == expected
    assert checked_in['schema_version'] == SCHEMA_VERSION
    assert checked_in['task_id'] == TASK_ID
    assert checked_in['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in)
    )
    assert checked_in['model']['model_cid'] == calculate_model_cid(model_payload)
    assert checked_in['model']['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert checked_in['model']['claim_count'] == 9
    assert checked_in['model']['assumption_count'] == 20


def test_xaman_assurance_packet_binds_manifest_commit_environment_and_artifacts() -> None:
    packet = _load_json(PACKET_PATH)
    manifest = _load_json(SOURCE_MANIFEST_PATH)
    environment = _load_json(ENVIRONMENT_PROBE_PATH)
    artifact_index = {
        entry['path']: entry
        for entry in packet['artifact_index']
    }

    assert packet['source']['repo_url'] == manifest['source']['repo_url']
    assert packet['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert packet['source']['commit_sha'] == manifest['source']['commit_sha']
    assert packet['source']['manifest']['aggregate_sha256'] == (
        manifest['reproducibility']['aggregate_sha256']
    )
    assert packet['source']['manifest']['file_count'] == 3444
    assert packet['environment_probe']['generated_at_utc'] == environment['generated_at_utc']
    assert packet['environment_probe']['overall_status'] == 'ready'
    assert packet['environment_probe']['proof_acceptance_blocked'] is False
    assert set(artifact_index) == EXPECTED_ARTIFACT_PATHS
    assert artifact_index[SMT_DIFFERENTIAL_PATH]['model_cid'] == packet['model']['model_cid']
    assert artifact_index[TLA_REPORT_PATH]['model_cid'] == packet['model']['model_cid']
    assert artifact_index[PROTOCOL_REPORT_PATH]['model_cid'] == packet['model']['model_cid']


def test_xaman_assurance_packet_bundles_proof_disproof_solver_and_runtime_reports() -> None:
    packet = _load_json(PACKET_PATH)
    proof_reports = {
        report['id']: report
        for report in packet['proof_reports']
    }
    disproof_reports = {
        report['id']: report
        for report in packet['disproof_reports']
    }
    solver_by_name = {
        entry['solver']: entry
        for entry in packet['solver_matrix']
    }

    assert set(proof_reports) == {
        'xaman-smt-z3-cvc5-differential',
        'xaman-tla-apalache-workflow',
        'xaman-symbolic-protocol',
        'xaman-proof-consumer-invariants',
    }
    assert proof_reports['xaman-smt-z3-cvc5-differential']['summary'] == {
        'agreements': 9,
        'blocked': 9,
        'claim_count': 9,
        'critical_claim_count': 9,
        'disagreements': 0,
        'disproved': 0,
        'proved': 0,
        'release_ready': False,
        'unknown': 0,
        'unsupported_theory_rejections': 0,
    }
    assert proof_reports['xaman-tla-apalache-workflow']['summary']['blocked_property_count'] == 10
    assert proof_reports['xaman-symbolic-protocol']['summary']['blocked_property_count'] == 9
    assert proof_reports['xaman-proof-consumer-invariants']['accepted_verdict']['accepted'] is True

    assert set(disproof_reports) == {
        'xaman-disproof-vectors',
        'xaman-counterexample-report',
    }
    assert disproof_reports['xaman-disproof-vectors']['summary']['counterexample_count'] == 6
    assert disproof_reports['xaman-counterexample-report']['summary']['scenario_failures'] == 0

    assert {'z3', 'cvc5', 'python', 'node', 'npm', 'typescript'} <= set(solver_by_name)
    assert solver_by_name['z3']['status'] == 'present'
    assert solver_by_name['cvc5']['status'] == 'present'
    assert solver_by_name['apalache']['release_effect'] == 'missing-solver'
    assert solver_by_name['proverif']['release_effect'] == 'missing-solver'
    assert solver_by_name['tamarin-prover']['release_effect'] == 'missing-solver'

    runtime = packet['runtime_traces']
    assert runtime['trace_inputs']['e2e_feature_count'] == 6
    assert runtime['trace_inputs']['real_device_trace_count'] == 0
    assert runtime['monitor_coverage']['missing_categories'] == []
    assert runtime['blocking_runtime_equivalence']['status'] == 'BLOCKING'
    assert runtime['release_effect'] == FAIL_CLOSED_DECISION


def test_xaman_assurance_packet_claims_assumptions_and_blockers_fail_closed() -> None:
    packet = _load_json(PACKET_PATH)
    assumption_summary = packet['assumptions']
    decisions = packet['claim_decisions']
    blockers = packet['open_blockers']
    blockers_by_type: dict[str, list[dict[str, Any]]] = {}
    for blocker in blockers:
        blockers_by_type.setdefault(blocker['type'], []).append(blocker)

    assert assumption_summary['total'] == 20
    assert assumption_summary['status_counts'] == {
        'BLOCKING': 12,
        'EVIDENCED': 8,
    }
    assert len(assumption_summary['blocking_assumption_ids']) == 12

    assert len(decisions) == 9
    assert all(decision['secure_for_release'] is False for decision in decisions)
    assert all(decision['consumer_outcome'] == 'stale-evidence' for decision in decisions)
    assert all(decision['release_effect'] == FAIL_CLOSED_DECISION for decision in decisions)
    assert {
        decision['release_gate']
        for decision in decisions
    } == {'blocking', 'high'}

    assert len(blockers_by_type['blocking_assumption']) == 12
    assert len(blockers_by_type['missing_solver']) == 3
    assert len(blockers_by_type['proof_gap']) == 1
    assert len(blockers_by_type['runtime_equivalence_gap']) == 1
    assert {
        blocker['solver']
        for blocker in blockers_by_type['missing_solver']
    } == {'apalache', 'proverif', 'tamarin-prover'}
    assert any(
        blocker['assumption_id'] == 'xaman-security:assumption:deployed-runtime-equivalence'
        for blocker in blockers_by_type['blocking_assumption']
    )


def test_xaman_assurance_packet_release_decision_is_blocked_production() -> None:
    packet = _load_json(PACKET_PATH)
    decision = packet['release_decision']

    assert decision['decision'] == FAIL_CLOSED_DECISION
    assert decision['release_ready'] is False
    assert decision['fail_closed'] is True
    assert decision['critical_claim_count'] == 9
    assert decision['proved_critical_claim_count'] == 0
    assert decision['open_blocker_count'] == len(packet['open_blockers']) == 17
    assert decision['policy']['required_secure_outcome'] == 'prove'
    assert decision['policy']['non_prove_effect'] == FAIL_CLOSED_DECISION
    assert any('0 of 9' in reason for reason in decision['rationale'])
    assert any('real-device' in reason for reason in decision['rationale'])


def test_xaman_assurance_packet_documents_artifacts_validation_and_decision() -> None:
    assurance_doc = ASSURANCE_DOC_PATH.read_text(encoding='utf-8')
    release_doc = RELEASE_DOC_PATH.read_text(encoding='utf-8')
    packet = _load_json(PACKET_PATH)

    for document in (assurance_doc, release_doc):
        assert 'PORTAL-CXTP-075' in document
        assert 'security_ir_artifacts/corpora/xaman-app/assurance-packet.json' in document
        assert packet['artifact_cid'] in document
        assert packet['model']['model_cid'] in document
        assert packet['source']['commit_sha'] in document
        assert packet['release_decision']['decision'] in document
        assert 'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_assurance_packet.py -q' in document

    assert 'solver matrix' in assurance_doc
    assert 'real-device' in release_doc
    assert 'blocked-production' in release_doc
