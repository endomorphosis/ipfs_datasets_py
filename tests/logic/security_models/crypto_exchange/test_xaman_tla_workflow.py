from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
TLA_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla'
REPORT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_tla_workflow.md'
MODEL_CID_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
CLAIMS_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-claims.json'


EXPECTED_INVARIANTS = {
    'NoSignWithoutDigest',
    'NoSignWithoutAuthentication',
    'NoSignWithoutVault',
    'NoSignWithoutNetworkBinding',
    'NoBroadcastWithoutSignature',
    'NoBroadcastAfterReject',
    'SigningGateInvariant',
}

EXPECTED_CLAIMS = {
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:software-custody-requires-vault-authentication',
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:network-binding-prevents-wrong-network-signing',
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_tla_model_contains_signing_gate_workflow() -> None:
    body = TLA_PATH.read_text(encoding='utf-8')

    assert '---- MODULE XamanSigning ----' in body
    assert 'Spec == Init /\\ [][Next]_vars' in body
    assert 'Sign ==' in body
    assert '/\\ digestChecked' in body
    assert '/\\ authPassed' in body
    assert '/\\ vaultOpened' in body
    assert '/\\ networkBound' in body
    assert 'Broadcast ==' in body
    assert 'Reject ==' in body
    for invariant in EXPECTED_INVARIANTS:
        assert invariant in body


def test_xaman_apalache_report_binds_model_and_blocks_missing_solver() -> None:
    report = _json(REPORT_PATH)
    body = TLA_PATH.read_text(encoding='utf-8')
    tla_cid = 'sha256:' + hashlib.sha256(body.encode('utf-8')).hexdigest()

    assert report['task_id'] == 'PORTAL-CXTP-071'
    assert report['schema_version'] == 'xaman-tla-apalache-report/v1'
    assert report['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert report['tla_model']['path'] == 'security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla'
    assert report['tla_model']['sha256'] == tla_cid
    assert set(report['tla_model']['invariants']) == EXPECTED_INVARIANTS
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_TLA_APALACHE_MISSING_SOLVER'
    assert report['production_release_blocked_by_tla_lane'] is True
    assert report['apalache']['run_status'].startswith('not-run')
    assert report['blockers']
    assert report['artifact_cid'].startswith('sha256:')


def test_xaman_tla_report_covers_expected_security_claims() -> None:
    report = _json(REPORT_PATH)
    claims = _json(CLAIMS_PATH)['claims']
    claim_ids = {claim['id'] for claim in claims}

    assert set(report['covered_claim_ids']) == EXPECTED_CLAIMS
    assert set(report['covered_claim_ids']) <= claim_ids


def test_xaman_tla_documentation_tracks_solver_gap() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-071' in doc
    assert 'XamanSigning.tla' in doc
    assert 'SigningGateInvariant' in doc
    assert 'blocked_optional_lane' in doc
    assert 'BLOCK_TLA_APALACHE_MISSING_SOLVER' in doc
