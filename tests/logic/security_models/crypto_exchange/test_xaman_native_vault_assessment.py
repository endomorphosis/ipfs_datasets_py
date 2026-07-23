"""Tests for the source-bound native-vault rekey solver lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_assessment import (
    CHECKS,
    REKEY_RECOVERY_SMTLIB,
    REQUIRED_SOURCE_MARKERS,
    build_native_vault_assessment,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json'
SMTLIB_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-recovery.smt2'
DOC_PATH = REPO_ROOT / 'docs/security_verification/xaman_native_vault_public_source_assessment.md'


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture_source(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for rel_path, markers in REQUIRED_SOURCE_MARKERS.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = ('\n'.join(markers) + '\n').encode('utf-8')
        path.write_bytes(payload)
        files.append({'path': rel_path, 'sha256': _sha256(payload)})
    return {
        'source': {'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa'},
        'reproducibility': {'aggregate_sha256': 'fixture-manifest'},
        'files': files,
    }


def _passing_solver_lane() -> dict[str, object]:
    expected = [check['expected_result'] for check in CHECKS]
    return {
        name: {'status': 'pass', 'results': expected, 'version': 'fixture'}
        for name in ('z3', 'cvc5')
    }


def test_assessment_binds_source_digests_and_preserves_runtime_boundary(tmp_path: Path) -> None:
    report = build_native_vault_assessment(
        source_root=tmp_path,
        manifest=_fixture_source(tmp_path),
        solver_lane=_passing_solver_lane(),
    )

    assert report['overall_status'] == 'checked_source_bounded_with_runtime_boundaries'
    assert report['security_decision'] == 'SOURCE_BOUNDED_NATIVE_VAULT_REKEY_MODEL_CHECKED'
    assert report['production_release_blocked'] is True
    assert report['formal_rekey_model']['status'] == 'checked'
    assert {item['id'] for item in report['source_supported_facts']} >= {
        'xaman-native-vault:fact:android-v2-vault-cipher-uses-pbkdf2-and-aes-gcm',
        'xaman-native-vault:fact:ios-v2-vault-cipher-and-device-only-keychain',
        'xaman-native-vault:fact:rekey-uses-an-old-key-recovery-vault-before-primary-delete',
    }
    assert report['source_supported_rekey_condition']['is_confirmed_vulnerability'] is False
    assert report['source_supported_rekey_condition']['status'] == 'REQUIRES_RUNTIME_FAULT_INJECTION'


def test_checked_in_artifacts_preserve_solver_results_and_self_cid() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    body = dict(report)
    artifact_cid = body.pop('artifact_cid')

    assert artifact_cid == calculate_artifact_cid(body)
    assert report['scope']['source_commit'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert report['formal_rekey_model']['status'] == 'checked'
    for solver in ('z3', 'cvc5'):
        result = report['formal_rekey_model']['solvers'][solver]
        assert result['status'] == 'pass'
        assert result['results'] == [check['expected_result'] for check in CHECKS]
    assert SMTLIB_PATH.read_text(encoding='utf-8') == REKEY_RECOVERY_SMTLIB


def test_documentation_does_not_promote_the_native_vault_result_to_production() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-162' in doc
    assert 'Z3' in doc and 'CVC5' in doc
    assert 'not a production' in doc.lower()
    assert 'fault injection' in doc.lower()
