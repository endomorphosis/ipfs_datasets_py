"""Tests for PORTAL-CXTP-094 production blocker evidence packets."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import types


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'generate_production_blocker_evidence_packets.py'
)
BRIDGE_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'production-blocker-bridge.json'
SCHEMA_PATH = REPO_ROOT / 'security_ir_artifacts' / 'production' / 'evidence-bundle.schema.json'
ARTIFACT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'production' / 'blocker-evidence-packets.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'production_blocker_evidence_packets.md'


def _load_script_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        'generate_production_blocker_evidence_packets',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load evidence packet generator')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _expected_payload(module: types.ModuleType, *, force_fallback: bool = False) -> dict:
    if force_fallback:
        bridge = module.build_fallback_bridge()
        fallback_used = True
    else:
        bridge, fallback_used = module._load_bridge(BRIDGE_PATH.relative_to(REPO_ROOT))
    return module.build_production_blocker_evidence_packets(
        bridge,
        bridge_path=BRIDGE_PATH.relative_to(REPO_ROOT),
        schema_path=SCHEMA_PATH.relative_to(REPO_ROOT),
        bridge_missing_fallback_used=fallback_used,
    )


def test_checked_in_packet_artifact_matches_generator() -> None:
    module = _load_script_module()

    checked_in = _load_json(ARTIFACT_PATH)
    expected = _expected_payload(
        module,
        force_fallback=checked_in['source_bridge']['status'] == 'fallback-synthesized',
    )

    assert checked_in == expected
    assert checked_in['schema_version'] == module.SCHEMA_VERSION
    assert checked_in['task_id'] == module.TASK_ID
    assert checked_in['artifact_cid'] == module._artifact_cid(checked_in)
    assert checked_in['overall_status'] == 'blocked'
    assert checked_in['release_gate_effect'] == 'fail_closed'
    assert checked_in['production_release_effect'] == 'blocked-production'
    assert checked_in['proof_acceptance_blocked'] is True
    assert checked_in['may_remove_any_blocker'] is False


def test_emits_one_packet_per_remaining_blocker_with_required_domains() -> None:
    module = _load_script_module()
    payload = _load_json(ARTIFACT_PATH)
    if payload['source_bridge']['status'] == 'fallback-synthesized':
        bridge = module.build_fallback_bridge()
    else:
        bridge, _fallback_used = module._load_bridge(BRIDGE_PATH.relative_to(REPO_ROOT))
    bridge_ids = [
        mapping['source_packet_blocker_id']
        for mapping in bridge['blocker_mappings']
    ]

    packets = payload['packets']
    assert payload['evidence_request_packets'] == packets
    assert len(packets) == len(bridge_ids) == payload['summary']['remaining_blocker_count']
    assert [packet['source_packet_blocker_id'] for packet in packets] == bridge_ids
    assert len({packet['id'] for packet in packets}) == len(packets)
    assert len({packet['packet_cid'] for packet in packets}) == len(packets)
    assert payload['summary']['all_packets_require_human_review'] is True

    valid_domains = set(module.PRODUCTION_EVIDENCE_DOMAINS)
    for packet in packets:
        domains = packet['required_production_evidence_domains']
        assert domains
        assert set(domains) <= valid_domains
        assert 'human_review' in domains
        assert set(packet['expected_owners']) == set(domains)
        assert set(packet['freshness_windows_days']) == set(domains)
        assert packet['request_id'] == packet['id']
        assert packet['blocker_id'] == packet['source_packet_blocker_id']
        assert packet['production_blocker_id'] == packet['source_packet_blocker_id']
        assert packet['source_blocker_status'] == 'blocked_missing_production_evidence'
        assert packet['validator_command'] == module.VALIDATION_COMMAND
        assert packet['closure_policy']['may_close_from_this_packet'] is False
        assert packet['closure_policy']['unblocks'] == []
        assert {request['domain'] for request in packet['evidence_requests']} == set(domains)


def test_each_domain_request_lists_owner_freshness_validator_and_bundle_contract() -> None:
    module = _load_script_module()
    payload = _load_json(ARTIFACT_PATH)

    for packet in payload['packets']:
        for request in packet['evidence_requests']:
            domain = request['domain']
            assert request['status'] == 'requested'
            assert request['expected_owner'] == module.DOMAIN_OWNER[domain]
            assert request['freshness_window_days'] == module.DOMAIN_FRESHNESS_DAYS[domain]
            assert request['validator_command'] == module.VALIDATION_COMMAND
            assert request['evidence_bundle_category'] == module.DOMAIN_TO_BUNDLE_CATEGORY[domain]
            assert request['must_be_bound_to_deployed_release'] is True
            assert set(module.DOMAIN_REQUIRED_BUNDLE_FIELDS[domain]) <= set(
                request['required_bundle_fields']
            )
            assert len(request['required_evidence']) >= 3
            assert any('Blocker-specific evidence:' in item for item in request['required_evidence'])
            assert any('Xaman source-corpus-only evidence' in item for item in request['rejection_rules'])
            if domain == 'human_review':
                assert request['accepted_review_statuses'] == ['approved-owner-signoff']
            else:
                assert request['accepted_review_statuses'] == ['human_reviewed', 'trusted_fixture']


def test_packets_explain_why_xaman_source_corpus_alone_cannot_remove_blockers() -> None:
    payload = _load_json(ARTIFACT_PATH)

    assert payload['summary']['xaman_source_corpus_accepted_for_production_unblock'] is False
    assert payload['summary']['deployed_app_evidence_required'] is True
    for packet in payload['packets']:
        boundary = packet['xaman_source_corpus_boundary']
        why = boundary['why_xaman_source_corpus_alone_cannot_remove_blocker']
        assert boundary['status'] == 'insufficient-for-production-unblock'
        assert boundary['source_corpus_evidence_status'] == 'mapped-but-insufficient-for-production'
        assert boundary['deployed_app_evidence_status'] == 'missing'
        assert 'Xaman source-corpus evidence cannot remove' in why
        assert packet['source_packet_blocker_id'] in why
        assert 'deployed-app evidence' in why


def test_specific_high_risk_packets_preserve_closure_requirements() -> None:
    payload = _load_json(ARTIFACT_PATH)
    by_blocker = {
        packet['source_packet_blocker_id']: packet
        for packet in payload['packets']
    }

    runtime = by_blocker['blocker:runtime:real-device-traces-absent']
    assert runtime['required_production_evidence_domains'] == [
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ]
    assert any(
        'Release-window iOS and Android real-device traces' in item
        for item in runtime['source_packet_closure_requirements']
    )

    deployed_runtime = by_blocker[
        'blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence'
    ]
    assert set(deployed_runtime['required_production_evidence_domains']) == {
        'production_source',
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    }
    assert any(
        'Reproducible build or signed binary provenance' in item
        for item in deployed_runtime['source_packet_closure_requirements']
    )

    apalache = by_blocker['blocker:solver:apalache']
    assert apalache['category'] == 'apalache'
    assert apalache['required_production_evidence_domains'] == [
        'production_environment',
        'human_review',
    ]


def test_cli_writes_json_and_doc_outputs(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'packets.json'
    doc_path = tmp_path / 'packets.md'

    rc = module.main(
        [
            '--bridge',
            BRIDGE_PATH.relative_to(REPO_ROOT).as_posix(),
            '--schema',
            SCHEMA_PATH.relative_to(REPO_ROOT).as_posix(),
            '--out',
            out_path.as_posix(),
            '--doc-out',
            doc_path.as_posix(),
        ]
    )

    assert rc == 0
    payload = _load_json(out_path)
    doc = doc_path.read_text(encoding='utf-8')
    assert payload['schema_version'] == module.SCHEMA_VERSION
    assert payload['task_id'] == module.TASK_ID
    assert payload['summary']['packet_count'] == 17
    assert payload['artifact_cid'] == module._artifact_cid(payload)
    assert payload['artifact_cid'] in doc
    assert module.TASK_ID in doc
    assert 'security_ir_artifacts/production/blocker-evidence-packets.json' in doc
    assert module.GENERATOR_VALIDATION_COMMAND in doc
    assert module.VALIDATION_COMMAND in doc


def test_document_covers_every_packet_and_required_domain() -> None:
    module = _load_script_module()
    payload = _load_json(ARTIFACT_PATH)
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert module.TASK_ID in doc
    assert payload['artifact_cid'] in doc
    assert 'blocked-production' in doc
    assert 'fail closed' in doc or 'fail-closed' in doc
    assert 'source-corpus packet is review context only' in doc
    for domain in module.PRODUCTION_EVIDENCE_DOMAINS:
        assert domain in doc
    for packet in payload['packets']:
        assert packet['source_packet_blocker_id'] in doc
        assert packet['validator_command'] in doc
