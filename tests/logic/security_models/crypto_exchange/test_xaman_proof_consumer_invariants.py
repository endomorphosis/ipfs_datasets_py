from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
KERNEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean'
REPORT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_proof_consumer_invariants.md'
MODEL_CID_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'


EXPECTED_THEOREMS = {
    'reject_disproved_status',
    'reject_unknown_status',
    'reject_not_modeled_status',
    'reject_uncleared_assumptions',
    'reject_unreviewed_evidence',
    'reject_solver_disagreement',
    'reject_counterexample',
    'reject_report_cid_mismatch',
    'reject_missing_trust_anchor',
    'reject_stale_assumptions',
    'reject_unsupported_prover',
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_receipt_kernel_contains_expected_invariants_without_placeholders() -> None:
    body = KERNEL_PATH.read_text(encoding='utf-8')

    assert 'def canAccept' in body
    assert 'def bindingMatches' in body
    assert 'ProofStatus.proved' in body
    assert 'ProofStatus.disproved' in body
    assert 'ProofStatus.unknown' in body
    assert 'ProofStatus.notModeled' in body
    assert 'sorry' not in body
    assert 'admit' not in body
    for theorem in EXPECTED_THEOREMS:
        assert f'theorem {theorem}' in body


def test_xaman_receipt_kernel_compiles_with_lean() -> None:
    lean = shutil.which('lean')
    assert lean is not None, 'Lean is required for PORTAL-CXTP-073 validation'

    completed = subprocess.run(
        [lean, str(KERNEL_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_xaman_proof_consumer_report_binds_kernel_and_fail_closed_policy() -> None:
    report = _json(REPORT_PATH)
    kernel_body = KERNEL_PATH.read_text(encoding='utf-8')
    kernel_cid = 'sha256:' + hashlib.sha256(kernel_body.encode('utf-8')).hexdigest()

    assert report['task_id'] == 'PORTAL-CXTP-073'
    assert report['schema_version'] == 'xaman-proof-consumer-report/v1'
    assert report['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert report['kernel']['path'] == 'security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean'
    assert report['kernel']['artifact_cid'] == kernel_cid
    assert report['kernel']['contains_sorry'] is False
    assert report['kernel']['contains_admit'] is False
    assert set(report['kernel']['theorems']) == EXPECTED_THEOREMS
    assert report['lean']['status'] == 'compiled'
    assert report['lean']['compile']['returncode'] == 0
    assert report['coq']['status'] == 'unavailable'
    assert report['overall_status'] == 'ready_lean_checked_coq_unavailable'
    assert report['production_release_blocked'] is True
    assert report['security_decision'] == (
        'LEAN_PROOF_CONSUMER_KERNEL_CHECKED_RELEASE_STILL_BLOCKED_BY_INTEGRATION_AND_ASSUMPTIONS'
    )

    policy = report['invariant_policy']
    assert policy['accepted_statuses'] == ['PROVED']
    assert set(policy['rejected_statuses']) == {'DISPROVED', 'UNKNOWN', 'NOT_MODELED'}
    assert policy['claim_id_match_required'] is True
    assert policy['model_cid_match_required'] is True
    assert policy['report_cid_match_required'] is True
    assert policy['trusted_signature_or_canonical_cid_required'] is True
    assert policy['assumptions_cleared_required'] is True
    assert policy['accepted_assumptions_current_required'] is True
    assert policy['evidence_review_required'] is True
    assert policy['solver_agreement_required'] is True
    assert policy['no_counterexample_required'] is True
    assert policy['supported_prover_required'] is True


def test_xaman_proof_consumer_documentation_tracks_release_semantics() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-073' in doc
    assert 'XamanReceipt.lean' in doc
    assert 'DISPROVED' in doc
    assert 'UNKNOWN' in doc
    assert 'NOT_MODELED' in doc
    assert 'Coq as unavailable' in doc
    assert 'does not prove the Xaman app secure' in doc
