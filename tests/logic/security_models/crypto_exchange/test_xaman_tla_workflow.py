"""Tests for PORTAL-CXTP-140 reconciled Xaman TLA workflow evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    CHECKED_INVARIANTS,
    COVERED_CLAIM_IDS,
    REQUIRED_APALACHE_VERSION,
    SCHEMA_VERSION,
    SCOPE_STATEMENT,
    TASK_ID,
    TLA_ARTIFACT_PATH,
    build_xaman_tla_workflow_report,
    generated_tla_source,
)


ROOT = Path(__file__).resolve().parents[4]
TLA_PATH = ROOT / TLA_ARTIFACT_PATH
REPORT_PATH = ROOT / APALACHE_REPORT_PATH
DOC_PATH = ROOT / 'docs/security_verification/xaman_tla_workflow.md'
MODEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
MODEL_CID_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
LIFECYCLE_FACTS_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json'


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def _sha256(payload: str) -> str:
    return 'sha256:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def test_checked_tla_source_is_exact_generator_output() -> None:
    body = TLA_PATH.read_text(encoding='utf-8')

    assert body == generated_tla_source()
    assert '---- MODULE XamanSigning ----' in body
    assert f'Scope statement: {SCOPE_STATEMENT}' in body
    assert 'Spec == Init /\\ [][Next]_vars' in body
    assert '/\\ digestChecked' in body
    assert '/\\ authPassed' in body
    assert '/\\ vaultOpened' in body
    assert '/\\ networkBound' in body
    for invariant in CHECKED_INVARIANTS:
        assert invariant in body


def test_xaman_apalache_report_binds_source_sha_and_0583_output() -> None:
    report = _json(REPORT_PATH)
    body = TLA_PATH.read_text(encoding='utf-8')
    tla_sha = _sha256(body)

    assert report['schema_version'] == SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['depends_on'] == ['PORTAL-CXTP-071', 'PORTAL-CXTP-091']
    assert report['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert report['scope']['statement'] == SCOPE_STATEMENT
    assert report['source_binding']['checked_source_sha256'] == tla_sha
    assert report['source_binding']['generator_sha256'] == tla_sha
    assert report['source_binding']['generator_matches_checked_source'] is True
    assert report['source_binding']['mismatch_is_blocker'] is True
    assert report['tla_model']['path'] == TLA_ARTIFACT_PATH
    assert report['tla_model']['sha256'] == tla_sha
    assert report['tla_model']['checked_invariants'] == list(CHECKED_INVARIANTS)
    assert report['artifact_cid'] == _cid_without(report, 'artifact_cid')

    assert report['apalache']['available'] is True
    assert report['apalache']['version'] == REQUIRED_APALACHE_VERSION
    assert report['apalache']['version_output'] == REQUIRED_APALACHE_VERSION
    assert report['apalache']['scope_statement'] == SCOPE_STATEMENT
    assert {run['invariant'] for run in report['apalache']['runs']} == set(CHECKED_INVARIANTS)
    for run in report['apalache']['runs']:
        assert run['status'] == 'pass'
        assert run['exit_code'] == 0
        assert run['input_tla_sha256'] == tla_sha
        assert run['apalache_version'] == REQUIRED_APALACHE_VERSION
        assert '--no-deadlock' in run['command']
        markers = run['output_evidence']['normalized_markers']
        assert '# APALACHE version: 0.58.3 | build: f4ac7ff' in markers
        assert 'The outcome is: NoError' in markers
        assert 'EXITCODE: OK' in markers
        assert run['output_evidence']['scope_statement'] == SCOPE_STATEMENT

    assert report['overall_status'] == 'checked_bounded_model_only'
    assert report['security_decision'] == 'ACCEPT_BOUNDED_MODEL_EVIDENCE_ONLY'
    assert report['blockers'] == []


def test_xaman_tla_report_covers_expected_security_claims() -> None:
    report = _json(REPORT_PATH)
    claims = _json(ROOT / 'security_ir_artifacts/corpora/xaman-app/security-claims.json')['claims']
    claim_ids = {claim['id'] for claim in claims}

    assert report['covered_claim_ids'] == list(COVERED_CLAIM_IDS)
    assert set(report['covered_claim_ids']) <= claim_ids
    assert report['missing_claim_ids'] == []


def test_report_builder_regenerates_checked_report_and_blocks_source_mismatch() -> None:
    model = _json(MODEL_PATH)
    model_cid = MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    lifecycle_facts = _json(LIFECYCLE_FACTS_PATH)
    report = _json(REPORT_PATH)
    tla_source = TLA_PATH.read_text(encoding='utf-8')

    regenerated = build_xaman_tla_workflow_report(
        model_payload=model,
        model_cid=model_cid,
        lifecycle_facts=lifecycle_facts,
        tla_source=tla_source,
        apalache_executable=report['apalache']['executable'],
        apalache_version=report['apalache']['version_output'],
        apalache_runs=report['apalache']['runs'],
    )
    assert regenerated == report

    mismatched = build_xaman_tla_workflow_report(
        model_payload=model,
        model_cid=model_cid,
        lifecycle_facts=lifecycle_facts,
        tla_source=tla_source + '\\* drift\\n',
        apalache_executable=report['apalache']['executable'],
        apalache_version=report['apalache']['version_output'],
        apalache_runs=report['apalache']['runs'],
    )
    blocker_codes = {blocker['code'] for blocker in mismatched['blockers']}
    assert 'TLA_GENERATOR_SOURCE_MISMATCH' in blocker_codes
    assert 'APALACHE_RUN_SOURCE_SHA_MISMATCH' in blocker_codes
    assert mismatched['overall_status'] == 'blocked_reconciliation'
    assert mismatched['security_decision'] == 'BLOCK_TLA_APALACHE_RECONCILIATION'
    assert mismatched['summary']['checked_property_count'] == 0
    assert mismatched['summary']['blocked_property_count'] == len(CHECKED_INVARIANTS)


def test_xaman_tla_documentation_records_bounded_scope_and_mismatch_blocker() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert TLA_ARTIFACT_PATH in doc
    assert APALACHE_REPORT_PATH in doc
    assert REQUIRED_APALACHE_VERSION in doc
    assert SCOPE_STATEMENT in doc
    assert 'TLA_GENERATOR_SOURCE_MISMATCH' in doc
    assert 'ACCEPT_BOUNDED_MODEL_EVIDENCE_ONLY' in doc
