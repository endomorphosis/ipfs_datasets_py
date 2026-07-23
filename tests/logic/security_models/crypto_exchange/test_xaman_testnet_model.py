"""Tests for PORTAL-CXTP-131 Xaman Testnet SecurityModelIR projection."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'project_xaman_testnet_security_model.py'
)
TESTNET_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'testnet'
MODEL_PATH = TESTNET_DIR / 'security-model-ir.json'
MODEL_CID_PATH = TESTNET_DIR / 'security-model-ir.cid'
TRACE_MAP_PATH = TESTNET_DIR / 'claim-trace-map.json'
ASSUMPTIONS_PATH = TESTNET_DIR / 'assumptions.json'
LIFECYCLE_EVIDENCE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'testnet-transaction-lifecycle-evidence.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_model_review.md'

HEX_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
SHA256_CID_RE = re.compile(r'^sha256:[0-9a-f]{64}$')

REQUIRED_COVERAGE_TAGS = {
    'network_binding',
    'account_provenance',
    'review_auth',
    'signing',
    'submission',
    'payload',
    'refusal',
    'replay',
    'expiry',
    'cancellation',
    'broadcast',
    'audit_boundaries',
}
REQUIRED_NOT_MODELED_CATEGORIES = {
    'payload',
    'signing',
    'network',
    'replay',
    'cancellation',
    'expiry',
    'broadcast',
    'refusal',
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _load_module():
    spec = importlib.util.spec_from_file_location('project_xaman_testnet_security_model', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Testnet model projection script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _iter_evidence_refs(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if {'kind', 'path', 'review_status'} <= set(value):
            yield value
        for item in value.values():
            yield from _iter_evidence_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_evidence_refs(item)


def _assert_source_location(location: Mapping[str, Any]) -> None:
    path = REPO_ROOT / str(location['path'])
    assert path.exists(), location
    assert isinstance(location['line_start'], int) and location['line_start'] > 0
    assert isinstance(location['line_end'], int) and location['line_end'] >= location['line_start']
    assert location['line_end'] <= len(path.read_text(encoding='utf-8').splitlines())


def test_projection_artifacts_are_regenerable_and_schema_valid() -> None:
    module = _load_module()
    generated = module.build_artifacts()
    model = _load_json(MODEL_PATH)
    trace_map = _load_json(TRACE_MAP_PATH)
    assumptions = _load_json(ASSUMPTIONS_PATH)

    assert generated['model'] == model
    assert generated['trace_map'] == trace_map
    assert generated['assumptions'] == assumptions
    assert MODEL_CID_PATH.read_text(encoding='utf-8').strip() == generated['model_cid']
    assert SHA256_CID_RE.fullmatch(generated['model_cid']) is not None

    validated = validate_ir(model)
    assert validated.schema_version == 'security-model-ir/xaman/v1'
    assert validated.model_id == 'xaman-app-testnet-transaction-lifecycle-security-model-ir'
    assert model['metadata']['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'
    assert model['metadata']['production_release_blocked'] is True
    for claim in model['claims']:
        assert claim['coverage_tags']
        assert claim['status'] in {
            'MODELED_WITH_TESTNET_SCOPE',
            'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY',
            'NOT_MODELED',
        }


def test_each_reviewed_event_maps_to_fact_claim_assumption_source_and_redaction_digest() -> None:
    model = _load_json(MODEL_PATH)
    trace_map = _load_json(TRACE_MAP_PATH)
    evidence = _load_json(LIFECYCLE_EVIDENCE_PATH)

    event_ids = {event['id'] for event in model['events']}
    claim_ids = {claim['id'] for claim in model['claims']}
    assumption_ids = {assumption['id'] for assumption in model['assumptions']}
    source_events = {event['action']: event for event in evidence['lifecycle_events']}
    mappings = {mapping['source_action']: mapping for mapping in trace_map['event_mappings']}

    assert set(mappings) == set(source_events)
    assert len(mappings) == 8
    assert {mapping['source_ordinal'] for mapping in mappings.values()} == set(range(1, 9))

    for action, source_event in source_events.items():
        mapping = mappings[action]
        assert mapping['mapping_status'] == 'MODELED'
        assert mapping['ambiguity_status'] == 'unambiguous'
        assert mapping['review_status'] == 'human_reviewed'
        assert mapping['redaction_digest'] == source_event['redaction_sha256']
        assert HEX_SHA256_RE.fullmatch(mapping['redaction_digest']) is not None
        assert mapping['typed_model_fact']['type'] == 'TESTNET_LIFECYCLE_EVENT'
        assert mapping['typed_model_fact']['event_id'] in event_ids
        assert set(mapping['claim_ids']) <= claim_ids
        assert set(mapping['assumption_ids']) <= assumption_ids
        assert mapping['claim_ids']
        assert mapping['assumption_ids']
        _assert_source_location(mapping['source_location'])
        assert mapping['source_location']['source_sha256'] == source_event['source_sha256']


def test_required_claim_coverage_and_not_modeled_boundaries_are_explicit() -> None:
    model = _load_json(MODEL_PATH)
    trace_map = _load_json(TRACE_MAP_PATH)
    claim_ids = {claim['id'] for claim in model['claims']}
    assumption_ids = {assumption['id'] for assumption in model['assumptions']}
    obligations = {obligation['claim_id']: obligation for obligation in model['proof_obligations']}
    solver_results = {result['claim_id']: result for result in model['solver_results']}

    assert set(trace_map['claim_coverage']) == REQUIRED_COVERAGE_TAGS
    for covered_claims in trace_map['claim_coverage'].values():
        assert covered_claims
        assert set(covered_claims) <= claim_ids

    records = trace_map['not_modeled_records']
    assert {record['category'] for record in records} == REQUIRED_NOT_MODELED_CATEGORIES
    assert model['metadata']['not_modeled_records'] == records
    for record in records:
        assert record['status'] == 'NOT_MODELED'
        assert record['claim_id'] in claim_ids
        assert record['assumption_id'] in assumption_ids
        assert HEX_SHA256_RE.fullmatch(record['redaction_digest']) is not None
        _assert_source_location(record['source_location'])
        if record['claim_id'] in {
            'xaman-testnet-claim:payload-intake-is-categorical-only',
            'xaman-testnet-claim:refusal-path-is-not-modeled',
            'xaman-testnet-claim:replay-controls-are-not-modeled',
            'xaman-testnet-claim:expiry-path-is-not-modeled',
            'xaman-testnet-claim:cancellation-path-is-not-modeled',
            'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
        }:
            assert obligations[record['claim_id']]['status'] == 'NOT_MODELED'
            assert solver_results[record['claim_id']]['result'] == 'not-modeled'

    gap_actions = {gap['source_action'] for gap in trace_map['coverage_gap_mappings']}
    assert gap_actions == {'decline', 'cancel', 'expiry'}
    assert all(gap['mapping_status'] == 'NOT_MODELED' for gap in trace_map['coverage_gap_mappings'])


def test_model_rejects_unreviewed_source_derived_facts_and_ambiguous_event_inputs() -> None:
    module = _load_module()
    lifecycle = module._load_json(module.LIFECYCLE_EVIDENCE_PATH)
    trial = module._load_json(module.TRIAL_REPORT_PATH)
    network = module._load_json(module.NETWORK_REPORT_PATH)
    device = module._load_json(module.DEVICE_REPORT_PATH)
    native = module._load_json(module.NATIVE_FIREBASE_REPORT_PATH)

    duplicate = deepcopy(lifecycle)
    duplicate['lifecycle_events'][1]['action'] = duplicate['lifecycle_events'][0]['action']
    with pytest.raises(ValueError, match='ambiguous duplicate lifecycle action'):
        module._validate_inputs(duplicate, trial, network, device, native)

    unreviewed = deepcopy(lifecycle)
    unreviewed['lifecycle_events'][0]['source_kind'] = 'heuristic_source_scan'
    with pytest.raises(ValueError, match='not reviewed_ui evidence'):
        module._validate_inputs(unreviewed, trial, network, device, native)

    raw_material = deepcopy(lifecycle)
    raw_material['lifecycle_events'][0]['raw_material_recorded'] = True
    with pytest.raises(ValueError, match='retained raw material'):
        module._validate_inputs(raw_material, trial, network, device, native)

    reordered = deepcopy(lifecycle)
    reordered['lifecycle_events'][0], reordered['lifecycle_events'][1] = (
        reordered['lifecycle_events'][1],
        reordered['lifecycle_events'][0],
    )
    with pytest.raises(ValueError, match='event order does not match reviewed trace'):
        module._validate_inputs(reordered, trial, network, device, native)

    wrong_ordinal = deepcopy(lifecycle)
    wrong_ordinal['lifecycle_events'][0]['ordinal'] = 99
    with pytest.raises(ValueError, match='event ordinals do not match reviewed trace'):
        module._validate_inputs(wrong_ordinal, trial, network, device, native)

    stale_trial_cid = deepcopy(trial)
    stale_trial_cid['artifact_cid'] = 'sha256:' + ('0' * 64)
    with pytest.raises(ValueError, match='trial report artifact_cid mismatch'):
        module._validate_inputs(lifecycle, stale_trial_cid, network, device, native)

    stale_lifecycle_binding = deepcopy(trial)
    stale_lifecycle_binding['evidence_inputs']['lifecycle_evidence_sha256'] = '0' * 64
    stale_lifecycle_binding['artifact_cid'] = module._artifact_cid_without_self(stale_lifecycle_binding)
    with pytest.raises(ValueError, match='trial lifecycle evidence sha256 mismatch'):
        module._validate_inputs(lifecycle, stale_lifecycle_binding, network, device, native)

    model = _load_json(MODEL_PATH)
    assert model['metadata']['ambiguity_policy']['unreviewed_source_derived_facts_rejected'] is True
    assert model['metadata']['ambiguity_policy']['duplicate_event_actions_rejected'] is True
    assert model['metadata']['ambiguity_policy']['raw_material_records_rejected'] is True
    for reference in _iter_evidence_refs(model):
        assert reference['kind'] == 'manual_review'
        assert reference['review_status'] == 'human_reviewed'


def test_assumptions_and_redaction_boundaries_remain_blocking() -> None:
    model = _load_json(MODEL_PATH)
    trace_map = _load_json(TRACE_MAP_PATH)
    assumptions = _load_json(ASSUMPTIONS_PATH)
    model_cid = MODEL_CID_PATH.read_text(encoding='utf-8').strip()

    assert assumptions['model_cid'] == model_cid
    assert trace_map['model_cid'] == model_cid
    assert assumptions['blocking_assumption_count'] == len(assumptions['assumptions'])
    assert all(assumption['status'] == 'BLOCKING' for assumption in assumptions['assumptions'])
    assert all(assumption['blocks_production_release'] is True for assumption in assumptions['assumptions'])
    assert {assumption['id'] for assumption in assumptions['assumptions']} == {
        assumption['id'] for assumption in model['assumptions']
    }

    boundary = model['metadata']['redaction_boundary']
    assert boundary['redaction_failure'] is False
    assert boundary['raw_payloads_recorded'] is False
    assert boundary['raw_request_bodies_recorded'] is False
    assert boundary['raw_server_info_response_recorded'] is False
    assert boundary['transaction_blobs_recorded'] is False
    assert boundary['credentials_recorded'] is False
    assert boundary['seeds_recorded'] is False
    assert model['metadata']['model_scope']['runtime_equivalence_status'] == 'not_proved'
    assert model['metadata']['model_scope']['production_usable'] is False


def test_review_document_describes_model_cid_outputs_and_boundaries() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-131' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json' in doc
    assert MODEL_CID_PATH.read_text(encoding='utf-8').strip() in doc
    assert 'NOT_MODELED' in doc
    assert 'payload, signing, network, replay, cancellation, expiry, broadcast, and refusal' in doc
