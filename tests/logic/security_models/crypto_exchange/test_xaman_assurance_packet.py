from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PACKET_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/assurance-packet.json'
MODEL_CID_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
ASSURANCE_DOC = ROOT / 'docs/security_verification/xaman_assurance_packet.md'
DECISION_DOC = ROOT / 'docs/security_verification/xaman_release_decision.md'


EXPECTED_ARTIFACT_KINDS = {
    'source_manifest',
    'source_coverage',
    'wallet_auth_facts',
    'payload_lifecycle_facts',
    'xrpl_transaction_facts',
    'security_claims',
    'security_model_ir',
    'smt_differential',
    'disproof_counterexamples',
    'tla_apalache_projection',
    'protocol_projection',
    'runtime_trace_report',
    'proof_consumer_kernel',
}

EXPECTED_BLOCKERS = {
    'UNRESOLVED_XAMAN_ASSUMPTIONS',
    'SMT_DIFFERENTIAL_BLOCKS_ALL_CLAIMS',
    'COUNTEREXAMPLES_FOUND',
    'DISPROOF_VECTORS_BLOCKED_BY_MISSING_EVIDENCE',
    'RUNTIME_EQUIVALENCE_MISSING_REAL_DEVICE_TRACES',
    'APALACHE_NOT_RUN',
    'PROTOCOL_SOLVERS_NOT_RUN',
    'PROOF_CONSUMER_NOT_PRODUCTION_INTEGRATED',
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_assurance_packet_is_bound_to_model_and_evidence_index() -> None:
    packet = _json(PACKET_PATH)

    assert packet['task_id'] == 'PORTAL-CXTP-075'
    assert packet['schema_version'] == 'xaman-assurance-packet/v1'
    assert packet['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert packet['artifact_cid'].startswith('sha256:')
    assert {artifact['kind'] for artifact in packet['evidence_artifacts']} == EXPECTED_ARTIFACT_KINDS
    assert all(artifact['sha256'].startswith('sha256:') for artifact in packet['evidence_artifacts'])
    assert all((ROOT / artifact['path']).is_file() for artifact in packet['evidence_artifacts'])


def test_xaman_assurance_packet_rejects_release_fail_closed() -> None:
    packet = _json(PACKET_PATH)

    assert packet['overall_status'] == 'blocked'
    assert packet['release_decision'] == 'reject_release'
    assert packet['security_decision'] == 'BLOCK_XAMAN_RELEASE_ASSURANCE_PACKET'
    assert packet['production_release_blocked'] is True
    assert packet['claim_summary']['claim_count'] == 10
    assert packet['claim_summary']['blocking_or_high_claim_count'] == 10
    assert packet['claim_summary']['proved_claim_count'] == 0
    assert packet['claim_summary']['blocked_claim_count'] == 10
    assert packet['blocker_count'] == len(EXPECTED_BLOCKERS)
    assert {blocker['code'] for blocker in packet['blockers']} == EXPECTED_BLOCKERS


def test_xaman_assurance_packet_preserves_lane_statuses() -> None:
    packet = _json(PACKET_PATH)
    lanes = packet['proof_lane_summary']

    assert lanes['smt_z3_cvc5']['blocked_claim_count'] == 10
    assert lanes['smt_z3_cvc5']['agreement_failure_count'] == 0
    assert lanes['disproof']['counterexample_found_count'] == 7
    assert lanes['disproof']['blocked_count'] == 2
    assert lanes['tla_apalache']['overall_status'] == 'blocked_optional_lane'
    assert lanes['protocol']['overall_status'] == 'blocked_optional_lane'
    assert lanes['runtime']['overall_status'] == 'blocked'
    assert lanes['proof_consumer']['overall_status'] == 'ready_lean_checked_coq_unavailable'


def test_xaman_assurance_packet_docs_match_release_decision() -> None:
    assurance_doc = ASSURANCE_DOC.read_text(encoding='utf-8')
    decision_doc = DECISION_DOC.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-075' in assurance_doc
    assert 'release_decision: reject_release' in assurance_doc
    assert 'BLOCK_XAMAN_RELEASE_ASSURANCE_PACKET' in assurance_doc
    assert 'Decision: reject release.' in decision_doc
    assert 'does not prove that Xaman is insecure in every possible deployment' in decision_doc
