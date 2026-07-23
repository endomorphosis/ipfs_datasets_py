"""Tests for fail-closed interpretation of Xaman counterexamples and fuzzing."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_counterexample_triage import (
    build_counterexample_triage,
    build_gap_remediation_matrix,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
COUNTEREXAMPLE_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/counterexample-report.json'
FUZZ_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json'
TRANSACTION_COVERAGE_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json'
NATIVE_VAULT_STATE_FUZZ_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json'
TRIAGE_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/counterexample-triage.json'
DOC_PATH = REPO_ROOT / 'docs/security_verification/xaman_counterexample_triage.md'
GAP_REMEDIATION_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json'


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_triage_is_regenerable_and_does_not_mislabel_mutations_as_exploits() -> None:
    generated = build_counterexample_triage(
        counterexample_report=_load(COUNTEREXAMPLE_PATH),
        fuzz_report=_load(FUZZ_PATH),
        transaction_coverage=_load(TRANSACTION_COVERAGE_PATH),
        native_vault_state_fuzz=_load(NATIVE_VAULT_STATE_FUZZ_PATH),
    )
    checked_in = _load(TRIAGE_PATH)

    assert generated == checked_in
    assert checked_in['overall_status'] == 'triaged_fail_closed'
    assert checked_in['security_decision'] == 'COUNTEREXAMPLES_TRIAGED_WITHOUT_PRODUCT_DEFECT_CLAIM'
    assert checked_in['interpretation_policy']['fuzz_target_claim_trigger_is_not_product_exploit'] is True
    assert checked_in['interpretation_policy']['source_bounded_runtime_obligation_is_not_product_exploit'] is True
    assert all(entry['confirmed_vulnerability'] is False for entry in checked_in['entries'])
    body = dict(checked_in)
    artifact_cid = body.pop('artifact_cid')
    assert artifact_cid == calculate_artifact_cid(body)


def test_triage_retains_source_coverage_gaps_and_runtime_boundaries() -> None:
    report = _load(TRIAGE_PATH)
    entries = {entry['id']: entry for entry in report['entries']}

    assert entries['xaman-disproof:unsupported-xrpl-semantics']['classification'] == 'SOURCE_SUPPORTED_COVERAGE_GAP'
    assert entries['attack-trustset-transaction-type']['classification'] == 'SOURCE_SUPPORTED_COVERAGE_GAP'
    assert entries['attack-replay-duplicate-resolution']['classification'] == 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS'
    assert entries['attack-cancel-after-submit-race']['classification'] == 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS'
    assert entries['attack-review-bypass']['classification'] == 'BOUNDARY_MODEL_MUTATION'
    assert entries['xaman-native-vault:condition:replacement-write-failure-leaves-old-key-recovery']['classification'] == 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION'
    assert entries['xaman-native-vault:condition:cleanup-failure-retains-old-key-recovery']['classification'] == 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION'
    assert report['summary']['source_bounded_runtime_test_obligation_count'] == 3
    assert set(report['summary']['required_proof_ineligible_transaction_classes']) >= {
        'OfferCreate',
        'SignerListSet',
        'TrustSet',
    }
    assert report['summary']['classification_counts'].get('UNCLASSIFIED_FAIL_CLOSED', 0) == 0


def test_documentation_explains_the_interpretation_boundary() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-164' in doc
    assert 'not a product exploit' in doc.lower()
    assert 'SOURCE_SUPPORTED_COVERAGE_GAP' in doc
    assert 'UNMODELED_RUNTIME_OR_BACKEND_SEMANTICS' in doc


def test_gap_remediation_matrix_is_ranked_and_deterministic() -> None:
    report = build_gap_remediation_matrix(triage_report=_load(TRIAGE_PATH))

    assert report['schema_version'] == 'xaman-gap-remediation-matrix/v1'
    assert report['task_id'] == 'PORTAL-CXTP-170'
    assert report['overall_status'] == 'remediation_required'
    assert report['security_decision'] == 'COUNTEREXAMPLES_REMEDIATION_PLAN_REQUIRED'
    assert report['summary']['entry_count'] == 37
    assert report['summary']['required_task_count'] == len(report['required_task_ids'])
    assert report['summary']['highest_priority_classification'] == 'MODEL_MUTATION_CONTROL_TEST'

    priorities = [item['priority'] for item in report['matrix']]
    assert priorities == sorted(priorities), 'matrix must be sorted by priority'
    source_supported_tx = set(report['source_supported_transaction_classes'])
    assert source_supported_tx == {'OfferCreate', 'SignerListSet', 'TrustSet', 'multisign'}

    assert {'PORTAL-CXTP-069', 'PORTAL-CXTP-070', 'PORTAL-CXTP-075'} <= set(report['required_task_ids'])
    assert 'xaman-disproof:unsupported-xrpl-semantics' in {item['entry_id'] for item in report['matrix']}
    assert report['artifact_cid'] == calculate_artifact_cid({key: value for key, value in report.items() if key != 'artifact_cid'})


def test_gap_remediation_matrix_file_is_checksummable_when_checkedin() -> None:
    assert GAP_REMEDIATION_PATH.exists(), 'gap-remediation-matrix.json must be generated and checked in'
    checked_in = _load(GAP_REMEDIATION_PATH)
    generated = build_gap_remediation_matrix(triage_report=_load(TRIAGE_PATH))

    assert generated == checked_in
    body = dict(generated)
    artifact_cid = body.pop('artifact_cid')
    assert artifact_cid == calculate_artifact_cid(body)
