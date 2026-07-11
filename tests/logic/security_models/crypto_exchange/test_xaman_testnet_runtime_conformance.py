"""Tests for PORTAL-CXTP-150 Xaman Testnet runtime conformance."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_runtime_conformance import (
    CLAIM_TRACE_MAP_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    REQUIRED_RUNTIME_CATEGORIES,
    REPORT_SCHEMA_VERSION,
    RUNTIME_CONFORMANCE_DOC_PATH,
    RUNTIME_CONFORMANCE_REPORT_PATH,
    RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
    SOLVER_PORTFOLIO_REPORT_PATH,
    TASK_ID,
    TRACE_MAP_SCHEMA_VERSION,
    TRANSACTION_TRIAL_PATH,
    RuntimeConformanceError,
    build_runtime_conformance_report,
    build_runtime_conformance_trace_map,
    render_runtime_conformance_markdown,
    validate_runtime_conformance_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding='utf-8'))


def _build() -> tuple[dict, dict, str]:
    model_payload = _load_json(MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    claim_trace_map = _load_json(CLAIM_TRACE_MAP_PATH)
    transaction_trial = _load_json(TRANSACTION_TRIAL_PATH)
    trace_map = build_runtime_conformance_trace_map(
        model_payload=model_payload,
        model_cid=model_cid,
        claim_trace_map=claim_trace_map,
        transaction_trial=transaction_trial,
        repo_root=REPO_ROOT,
    )
    report = build_runtime_conformance_report(
        model_payload=model_payload,
        model_cid=model_cid,
        claim_trace_map=claim_trace_map,
        transaction_trial=transaction_trial,
        public_build_reproduction=_load_json(PUBLIC_BUILD_REPRODUCTION_PATH),
        public_build_environment=_load_json(PUBLIC_BUILD_ENVIRONMENT_PATH),
        solver_portfolio_report=_load_json(SOLVER_PORTFOLIO_REPORT_PATH),
        fuzz_counterexample_manifest=_load_json(FUZZ_COUNTEREXAMPLE_MANIFEST_PATH),
        trace_map=trace_map,
        repo_root=REPO_ROOT,
    )
    markdown = render_runtime_conformance_markdown(report, trace_map)
    return trace_map, report, markdown


def test_runtime_conformance_artifacts_are_regenerable() -> None:
    generated_trace_map, generated_report, generated_doc = _build()
    checked_trace_map = _load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH)
    checked_report = _load_json(RUNTIME_CONFORMANCE_REPORT_PATH)
    checked_doc = (REPO_ROOT / RUNTIME_CONFORMANCE_DOC_PATH).read_text(encoding='utf-8')

    assert generated_trace_map == checked_trace_map
    assert generated_report == checked_report
    assert generated_doc == checked_doc
    assert checked_trace_map['schema_version'] == TRACE_MAP_SCHEMA_VERSION
    assert checked_report['schema_version'] == REPORT_SCHEMA_VERSION
    assert checked_trace_map['task_id'] == TASK_ID
    assert checked_report['task_id'] == TASK_ID
    assert checked_trace_map['model']['cid'] == PINNED_MODEL_CID
    assert checked_report['model']['cid'] == PINNED_MODEL_CID
    validate_runtime_conformance_artifacts(
        report=checked_report,
        trace_map=checked_trace_map,
        model_cid=PINNED_MODEL_CID,
    )


def test_required_runtime_categories_are_bound_to_claims_and_model_cid() -> None:
    report = _load_json(RUNTIME_CONFORMANCE_REPORT_PATH)
    trace_map = _load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH)

    assert tuple(binding['category_id'] for binding in report['runtime_categories']) == REQUIRED_RUNTIME_CATEGORIES
    assert tuple(binding['category_id'] for binding in trace_map['category_bindings']) == REQUIRED_RUNTIME_CATEGORIES
    for binding in report['runtime_categories']:
        assert binding['model_cid_bound'] is True
        assert binding['claim_ids']
        assert all(claim_id.startswith('xaman-testnet-claim:') for claim_id in binding['claim_ids'])
        assert binding['assumption_ids']
        assert binding['raw_material_retained'] is False
        assert binding['conformance_status'] in {
            'observed',
            'observed_with_blocking_boundary',
            'blocked_missing_path',
            'blocked_missing_evidence',
        }


def test_missing_cancellation_expiry_and_replay_paths_remain_assurance_blocks() -> None:
    report = _load_json(RUNTIME_CONFORMANCE_REPORT_PATH)
    by_category = {binding['category_id']: binding for binding in report['runtime_categories']}

    assert by_category['cancellation']['conformance_status'] == 'blocked_missing_path'
    assert by_category['expiry']['conformance_status'] == 'blocked_missing_path'
    assert by_category['replay']['conformance_status'] == 'blocked_missing_path'
    assert report['overall_status'] == 'blocked_testnet_runtime_conformance'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_RUNTIME_CONFORMANCE_GAPS'
    assert report['production_release_blocked'] is True
    block_categories = {
        block.get('category_id')
        for block in report['assurance_blocks']
        if block['code'].startswith('RUNTIME_CATEGORY_')
    }
    assert {'cancellation', 'expiry', 'replay'} <= block_categories


def test_observed_runtime_categories_cover_fresh_emulator_network_account_review_auth_submit_reconnect() -> None:
    report = _load_json(RUNTIME_CONFORMANCE_REPORT_PATH)
    by_category = {binding['category_id']: binding for binding in report['runtime_categories']}

    for category in {
        'fresh_emulator',
        'testnet_only_network',
        'fresh_account',
        'review',
        'authentication',
        'reconnect',
        'network_change',
    }:
        assert by_category[category]['conformance_status'] == 'observed'
    assert by_category['signing_decision']['conformance_status'] == 'observed_with_blocking_boundary'
    assert by_category['submit_attempt']['conformance_status'] == 'observed_with_blocking_boundary'
    assert by_category['submit_result']['conformance_status'] == 'observed_with_blocking_boundary'
    assert report['freshness'] == {
        'fresh_account_observed': True,
        'fresh_emulator_observed': True,
        'testnet_only_network_observed': True,
    }


def test_sensitive_material_is_not_retained() -> None:
    report = _load_json(RUNTIME_CONFORMANCE_REPORT_PATH)
    trace_map = _load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH)

    assert report['redaction_boundary']['all_sensitive_material_excluded'] is True
    for key in {
        'seeds_retained',
        'addresses_retained',
        'payloads_retained',
        'transaction_material_retained',
        'credentials_retained',
        'endpoint_values_retained',
        'request_response_bodies_retained',
    }:
        assert report['redaction_boundary'][key] is False
    serialized = json.dumps({'report': report, 'trace_map': trace_map}, sort_keys=True)
    assert 'wss://' not in serialized
    assert 'https://' not in serialized
    assert '"TransactionType"' not in serialized
    assert 'signed_blob' not in serialized


def test_validation_rejects_removed_required_category() -> None:
    report = deepcopy(_load_json(RUNTIME_CONFORMANCE_REPORT_PATH))
    trace_map = deepcopy(_load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH))
    report['runtime_categories'] = [
        binding for binding in report['runtime_categories'] if binding['category_id'] != 'replay'
    ]

    with pytest.raises(RuntimeConformanceError, match='category order or coverage mismatch'):
        validate_runtime_conformance_artifacts(
            report=report,
            trace_map=trace_map,
            model_cid=PINNED_MODEL_CID,
        )


def test_validation_rejects_raw_endpoint_reintroduction() -> None:
    report = deepcopy(_load_json(RUNTIME_CONFORMANCE_REPORT_PATH))
    trace_map = deepcopy(_load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH))
    report['runtime_categories'][0]['forbidden_value'] = 'wss://s.altnet.rippletest.net:51233'

    with pytest.raises(RuntimeConformanceError, match='forbidden sensitive material'):
        validate_runtime_conformance_artifacts(
            report=report,
            trace_map=trace_map,
            model_cid=PINNED_MODEL_CID,
        )


def test_documentation_records_runtime_conformance_scope_and_blocks() -> None:
    doc = (REPO_ROOT / RUNTIME_CONFORMANCE_DOC_PATH).read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert RUNTIME_CONFORMANCE_REPORT_PATH in doc
    assert RUNTIME_CONFORMANCE_TRACE_MAP_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'not a production or vendor-release security decision' in doc
    assert 'cancellation' in doc
    assert 'expiry' in doc
    assert 'replay' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_RUNTIME_CONFORMANCE_GAPS' in doc
