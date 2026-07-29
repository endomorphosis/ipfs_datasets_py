from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy'
REPORT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_protocol_model.md'
MODEL_CID_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
CLAIMS_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-claims.json'


EXPECTED_LEMMAS = {
    'sign_requires_digest_check',
    'sign_requires_user_approval',
    'sign_requires_auth_and_vault',
    'broadcast_requires_signature',
    'rejected_payload_not_broadcast',
    'nonce_consumed_at_most_once',
}

EXPECTED_CLAIMS = {
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking',
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:backend-payload-service-is-trusted-not-proved',
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_tamarin_model_contains_payload_protocol_events_and_lemmas() -> None:
    body = MODEL_PATH.read_text(encoding='utf-8')

    assert 'theory XamanPayloadProtocol' in body
    assert 'builtins: hashing, signing' in body
    for event in [
        'PayloadIssued',
        'PayloadReceived',
        'DigestChecked',
        'UserReviewed',
        'UserApproved',
        'AuthPassed',
        'VaultOpened',
        'PayloadSigned',
        'PayloadBroadcast',
        'PayloadRejected',
        'NonceConsumed',
    ]:
        assert event in body
    for lemma in EXPECTED_LEMMAS:
        assert f'lemma {lemma}' in body


def test_xaman_protocol_report_binds_model_and_blocks_missing_solvers() -> None:
    report = _json(REPORT_PATH)
    body = MODEL_PATH.read_text(encoding='utf-8')
    model_hash = 'sha256:' + hashlib.sha256(body.encode('utf-8')).hexdigest()

    assert report['task_id'] == 'PORTAL-CXTP-072'
    assert report['schema_version'] == 'xaman-protocol-projection-report/v1'
    assert report['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert report['protocol_model']['path'] == (
        'security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy'
    )
    assert report['protocol_model']['sha256'] == model_hash
    assert set(report['protocol_model']['lemmas']) == EXPECTED_LEMMAS
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_PROTOCOL_SOLVERS_UNAVAILABLE'
    assert report['production_release_blocked_by_protocol_lane'] is True
    assert report['model_check']['run_status'] == 'not-run'
    assert report['blockers']
    assert report['artifact_cid'].startswith('sha256:')


def test_xaman_protocol_report_covers_expected_claims() -> None:
    report = _json(REPORT_PATH)
    claims = _json(CLAIMS_PATH)['claims']
    claim_ids = {claim['id'] for claim in claims}

    assert set(report['covered_claim_ids']) == EXPECTED_CLAIMS
    assert set(report['covered_claim_ids']) <= claim_ids


def test_xaman_protocol_documentation_tracks_solver_gap() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-072' in doc
    assert 'xaman_payload_protocol.spthy' in doc
    assert 'sign_requires_auth_and_vault' in doc
    assert 'blocked_optional_lane' in doc
    assert 'BLOCK_PROTOCOL_SOLVERS_UNAVAILABLE' in doc
