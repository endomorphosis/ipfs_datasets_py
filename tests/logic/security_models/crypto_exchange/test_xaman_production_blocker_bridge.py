import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_production_blocker_bridge import (
    PRODUCTION_EVIDENCE_DOMAINS,
    SCHEMA_VERSION,
    TASK_ID,
    VALIDATION_COMMAND,
    build_xaman_production_blocker_bridge,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
ASSURANCE_PACKET_PATH = CORPUS_DIR / 'assurance-packet.json'
BRIDGE_PATH = CORPUS_DIR / 'production-blocker-bridge.json'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_to_production_blocker_bridge.md'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _without_artifact_cid(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key != 'artifact_cid'
    }


def _expected_bridge() -> dict[str, Any]:
    return build_xaman_production_blocker_bridge(_load_json(ASSURANCE_PACKET_PATH))


def test_xaman_production_blocker_bridge_is_generated_from_assurance_packet() -> None:
    checked_in = _load_json(BRIDGE_PATH)
    expected = _expected_bridge()
    packet = _load_json(ASSURANCE_PACKET_PATH)

    assert checked_in == expected
    assert checked_in['schema_version'] == SCHEMA_VERSION
    assert checked_in['task_id'] == TASK_ID
    assert checked_in['artifact_cid'] == calculate_artifact_cid(
        _without_artifact_cid(checked_in)
    )
    assert checked_in['source_packet']['artifact_cid'] == packet['artifact_cid']
    assert checked_in['source_packet']['model_cid'] == packet['model']['model_cid']
    assert checked_in['source_packet']['commit_sha'] == packet['source']['commit_sha']
    assert checked_in['source_packet']['release_decision'] == 'blocked-production'


def test_bridge_distinguishes_source_corpus_evidence_from_deployed_app_evidence() -> None:
    bridge = _load_json(BRIDGE_PATH)
    source = bridge['evidence_scope']['source_corpus']
    deployed = bridge['evidence_scope']['deployed_app']

    assert source['status'] == 'available_for_review_context'
    assert source['accepted_for_deployed_app_release'] is False
    assert source['evidence_count'] == 8
    assert {
        item['scope']
        for item in source['evidence']
    } == {'source_corpus'}
    assert {
        item['evidence_type']
        for item in source['evidence']
    } == {
        'source_manifest',
        'source_coverage',
        'security_claims',
        'security_model',
        'proof_reports',
        'disproof_reports',
        'source_or_e2e_runtime_monitors',
        'proof_consumer_fixture',
    }

    runtime_item = next(
        item
        for item in source['evidence']
        if item['evidence_type'] == 'source_or_e2e_runtime_monitors'
    )
    assert runtime_item['real_device_trace_count'] == 0
    assert runtime_item['status'] == 'not-deployed-runtime-equivalent'

    assert deployed['scope'] == 'deployed_app'
    assert deployed['status'] == 'absent'
    assert deployed['accepted_evidence_count'] == 0
    assert deployed['accepted_evidence'] == []
    assert deployed['real_device_trace_count'] == 0
    assert deployed['production_release_ready'] is False
    assert {
        entry['domain']
        for entry in deployed['missing_evidence']
    } == set(PRODUCTION_EVIDENCE_DOMAINS)


def test_bridge_maps_every_assurance_packet_blocker_exactly_once() -> None:
    bridge = _load_json(BRIDGE_PATH)
    packet = _load_json(ASSURANCE_PACKET_PATH)
    bridge_blocker_ids = [
        mapping['source_packet_blocker_id']
        for mapping in bridge['blocker_mappings']
    ]
    packet_blocker_ids = [
        blocker['id']
        for blocker in packet['open_blockers']
    ]

    assert bridge_blocker_ids == packet_blocker_ids
    assert len(bridge_blocker_ids) == len(set(bridge_blocker_ids)) == 17
    assert bridge['summary']['open_blocker_count'] == 17
    assert bridge['summary']['source_packet_open_blocker_count'] == 17
    assert all(
        mapping['removal_status'] == 'blocked_missing_production_evidence'
        for mapping in bridge['blocker_mappings']
    )
    assert all(
        mapping['source_corpus_evidence_status'] == 'mapped-but-insufficient-for-production'
        for mapping in bridge['blocker_mappings']
    )
    assert all(
        mapping['deployed_app_evidence_status'] == 'missing'
        for mapping in bridge['blocker_mappings']
    )


def test_bridge_lists_production_evidence_domains_for_every_remaining_blocker() -> None:
    bridge = _load_json(BRIDGE_PATH)
    valid_domains = set(PRODUCTION_EVIDENCE_DOMAINS)

    for mapping in bridge['blocker_mappings']:
        domains = set(mapping['required_production_evidence_domains'])
        assert domains
        assert domains <= valid_domains
        assert {req['domain'] for req in mapping['domain_requirements']} == domains
        assert all(req['status'] == 'missing' for req in mapping['domain_requirements'])
        assert all(
            req['source_packet_requirements']
            for req in mapping['domain_requirements']
        )

    by_domain = bridge['remaining_blockers_by_domain']
    assert set(by_domain) == valid_domains
    assert by_domain['human_review']['blocker_count'] == 17
    assert by_domain['production_source']['blocker_count'] >= 10
    assert by_domain['production_build']['blocker_count'] >= 5
    assert by_domain['production_runtime']['blocker_count'] >= 12
    assert by_domain['production_environment']['blocker_count'] >= 15
    assert bridge['summary']['domain_blocker_counts'] == {
        domain: by_domain[domain]['blocker_count']
        for domain in PRODUCTION_EVIDENCE_DOMAINS
    }


def test_bridge_preserves_specific_high_risk_blocker_closure_requirements() -> None:
    bridge = _load_json(BRIDGE_PATH)
    by_id = {
        mapping['source_packet_blocker_id']: mapping
        for mapping in bridge['blocker_mappings']
    }

    runtime = by_id['blocker:runtime:real-device-traces-absent']
    assert runtime['required_production_evidence_domains'] == [
        'production_build',
        'production_runtime',
        'production_environment',
        'human_review',
    ]
    assert any(
        'Release-window iOS and Android real-device traces' in requirement
        for requirement in runtime['required_evidence_to_close_from_packet']
    )

    deployed_runtime = by_id[
        'blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence'
    ]
    assert set(deployed_runtime['required_production_evidence_domains']) == set(
        PRODUCTION_EVIDENCE_DOMAINS
    )
    assert any(
        'Reproducible build or signed binary provenance' in requirement
        for requirement in deployed_runtime['required_evidence_to_close_from_packet']
    )

    apalache = by_id['blocker:solver:apalache']
    assert apalache['required_production_evidence_domains'] == [
        'production_environment',
        'human_review',
    ]
    assert apalache['category'] == 'apalache'


def test_bridge_maps_claims_to_remaining_packet_blockers() -> None:
    bridge = _load_json(BRIDGE_PATH)
    packet = _load_json(ASSURANCE_PACKET_PATH)

    assert len(bridge['claim_blocker_map']) == len(packet['claim_decisions']) == 9
    assert all(
        claim['secure_for_release'] is False
        for claim in bridge['claim_blocker_map']
    )
    assert all(
        claim['remaining_production_blocker_count'] >= 1
        for claim in bridge['claim_blocker_map']
    )
    runtime_claim = next(
        claim
        for claim in bridge['claim_blocker_map']
        if claim['claim_id'] == 'xaman-security:claim:reviewed-source-is-equivalent-to-deployed-runtime'
    )
    assert {
        'blocker:assumption:xaman-security-assumption-deployed-runtime-equivalence',
        'blocker:assumption:xaman-security-assumption-deployed-network-and-node-config-equivalence',
        'blocker:proof:no-critical-claim-proved',
    } <= set(runtime_claim['blocked_by_packet_blocker_ids'])


def test_bridge_policy_and_document_cover_validation_and_evidence_boundaries() -> None:
    bridge = _load_json(BRIDGE_PATH)
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert bridge['production_blocker_removal_policy']['decision'] == 'blocked-production'
    assert bridge['production_blocker_removal_policy']['may_remove_any_blocker'] is False
    assert bridge['summary']['deployed_app_accepted_evidence_count'] == 0
    assert bridge['validation']['command'] == VALIDATION_COMMAND

    assert 'PORTAL-CXTP-076' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json' in doc
    assert bridge['artifact_cid'] in doc
    assert bridge['source_packet']['artifact_cid'] in doc
    assert 'source-corpus evidence' in doc
    assert 'deployed-app evidence' in doc
    for domain in PRODUCTION_EVIDENCE_DOMAINS:
        assert domain in doc
    for mapping in bridge['blocker_mappings']:
        assert mapping['source_packet_blocker_id'] in doc
    assert VALIDATION_COMMAND in doc
