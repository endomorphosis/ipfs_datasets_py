"""Tests for PORTAL-CXTP-139 Xaman XRPL Testnet assurance verdict."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_assurance_verdict import (
    ALLOWED_VERDICTS,
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    BUNDLE_PATH,
    BUNDLE_SCHEMA_VERSION,
    CLAIM_TRACE_MAP_PATH,
    COQ_DECISION_PATH,
    FUZZ_REPORT_PATH,
    LEAN_REPORT_PATH,
    LEANSTRAL_AUDIT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROTOCOL_REPORT_PATH,
    SMT_REPORT_PATH,
    TASK_ID,
    VERDICT_DOC_PATH,
    VERDICT_PATH,
    VERDICT_SCHEMA_VERSION,
    build_xaman_testnet_assurance_bundle,
    build_xaman_testnet_assurance_verdict,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_json(path: str | Path) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid(
        {
            item_key: item_value
            for item_key, item_value in payload.items()
            if item_key != key
        }
    )


def test_testnet_assurance_bundle_is_regenerable_and_bound_to_evidence() -> None:
    bundle = _load_json(BUNDLE_PATH)
    regenerated = build_xaman_testnet_assurance_bundle(
        model_payload=_load_json(MODEL_PATH),
        model_cid=(REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip(),
        assumptions_payload=_load_json(ASSUMPTIONS_PATH),
        claim_trace_map=_load_json(CLAIM_TRACE_MAP_PATH),
        smt_report=_load_json(SMT_REPORT_PATH),
        apalache_report=_load_json(APALACHE_REPORT_PATH),
        protocol_report=_load_json(PROTOCOL_REPORT_PATH),
        lean_report=_load_json(LEAN_REPORT_PATH),
        coq_decision=_load_json(COQ_DECISION_PATH),
        fuzz_report=_load_json(FUZZ_REPORT_PATH),
        leanstral_audit=_load_json(LEANSTRAL_AUDIT_PATH),
    )

    assert regenerated == bundle
    assert bundle['schema_version'] == BUNDLE_SCHEMA_VERSION
    assert bundle['task_id'] == TASK_ID
    assert bundle['model']['cid'] == (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assert bundle['scope']['production_security_result'] is False
    assert bundle['decision_vocabulary'] == list(ALLOWED_VERDICTS)
    assert bundle['artifact_cid'] == _cid_without(bundle, 'artifact_cid')
    assert all((REPO_ROOT / artifact['path']).is_file() for artifact in bundle['evidence_artifacts'])


def test_testnet_verdict_uses_only_allowed_vocabulary_and_is_not_production_security() -> None:
    bundle = _load_json(BUNDLE_PATH)
    verdict = _load_json(VERDICT_PATH)
    regenerated = build_xaman_testnet_assurance_verdict(bundle)

    assert regenerated == verdict
    assert verdict['schema_version'] == VERDICT_SCHEMA_VERSION
    assert verdict['task_id'] == TASK_ID
    assert verdict['verdict'] in ALLOWED_VERDICTS
    assert verdict['verdict'] == 'TESTNET_SCOPE_NOT_SECURE'
    assert verdict['not_a_production_security_result'] is True
    assert 'does not approve' in verdict['production_security_statement']
    assert verdict['bundle']['artifact_cid'] == bundle['artifact_cid']
    assert verdict['artifact_cid'] == _cid_without(verdict, 'artifact_cid')


def test_verdict_preserves_precise_blockers_and_owner_actions_to_advance() -> None:
    bundle = _load_json(BUNDLE_PATH)
    verdict = _load_json(VERDICT_PATH)
    blocker_codes = {blocker['code'] for blocker in bundle['blockers']}

    assert {
        'SMT_COUNTEREXAMPLES_FOUND',
        'BLOCKING_TESTNET_ASSUMPTIONS',
        'UNRESOLVED_CONCURRENCY_ASSUMPTIONS',
        'NOT_MODELED_TESTNET_CLAIMS',
        'PRODUCTION_SECURITY_RESULT_EXCLUDED',
    } == blocker_codes
    assert bundle['claim_summary']['smt_result_counts'] == {'COUNTEREXAMPLE': 12}
    assert len(bundle['blocking_assumptions']) == 14
    assert bundle['lane_summary']['protocol']['blocker_codes'] == []
    action_text = json.dumps(verdict['precise_evidence_or_owner_action_required_to_advance'])
    assert 'production runtime network trace' in action_text
    assert 'reviewed cancel trace' in action_text
    assert 'backend atomic single-use evidence' in action_text
    assert 'Z3/CVC5 no longer emit counterexamples' in verdict['next_decision_rule']


def test_verdict_document_records_scope_result_and_advancement_requirements() -> None:
    doc = (REPO_ROOT / VERDICT_DOC_PATH).read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-139' in doc
    assert 'TESTNET_SCOPE_NOT_SECURE' in doc
    assert 'not a production-security result' in doc
    assert BUNDLE_PATH in doc
    assert VERDICT_PATH in doc
    assert 'BLOCK_TESTNET_ASSURANCE_COUNTEREXAMPLES' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_PROTOCOL_ASSUMPTIONS' in doc
    assert 'Allowed verdict values remain exactly' in doc
