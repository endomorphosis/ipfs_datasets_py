"""Tests for PORTAL-CXTP-135 Xaman Testnet protocol solver lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_protocol import (
    ASSUMPTIONS_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    NOT_MODELED_CLAIM_IDS,
    PROTOCOL_CLAIM_IDS,
    PROTOCOL_REPORT_PATH,
    PROVERIF_ARTIFACT_PATH,
    REQUIRED_EVENTS,
    REQUIRED_LEMMAS,
    SCHEMA_VERSION,
    TAMARIN_ARTIFACT_PATH,
    TASK_ID,
    TRACE_MAP_PATH,
    XAMAN_TESTNET_PAYLOAD_PV,
    build_xaman_testnet_protocol_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
TAMARIN_PATH = REPO_ROOT / TAMARIN_ARTIFACT_PATH
PROVERIF_PATH = REPO_ROOT / PROVERIF_ARTIFACT_PATH
REPORT_PATH = REPO_ROOT / PROTOCOL_REPORT_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_protocol_verification.md'
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def test_xaman_testnet_tamarin_model_contains_remote_payload_events_and_lemmas() -> None:
    body = TAMARIN_PATH.read_text(encoding='utf-8')

    assert 'theory XamanTestnetPayload' in body
    assert 'PORTAL-CXTP-135' in body
    assert 'builtins: hashing, signing' in body
    assert 'NOT_MODELED in protocol-report.json' in body
    for event in REQUIRED_EVENTS:
        assert event in body
    for lemma in REQUIRED_LEMMAS:
        assert f'lemma {lemma}' in body

    assert PROVERIF_PATH.read_text(encoding='utf-8') == XAMAN_TESTNET_PAYLOAD_PV
    assert 'does not\n  model native signing' in XAMAN_TESTNET_PAYLOAD_PV


def test_protocol_report_is_bound_to_pinned_testnet_model_and_tamarin_source() -> None:
    report = _load_json(REPORT_PATH)
    source = TAMARIN_PATH.read_text(encoding='utf-8')
    source_sha = 'sha256:' + hashlib.sha256(source.encode('utf-8')).hexdigest()

    assert report['schema_version'] == SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['model']['cid'] == PINNED_MODEL_CID
    assert report['model']['cid'] == (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assert report['tamarin_model']['path'] == TAMARIN_ARTIFACT_PATH
    assert report['tamarin_model']['theory'] == 'XamanTestnetPayload'
    assert report['tamarin_model']['sha256'] == source_sha
    assert report['tamarin_model']['lemmas'] == list(REQUIRED_LEMMAS)
    assert report['proverif_model']['path'] == PROVERIF_ARTIFACT_PATH
    assert report['proverif_model']['exists'] is True
    assert report['proverif_model']['sha256'] == (
        'sha256:' + hashlib.sha256(PROVERIF_PATH.read_bytes()).hexdigest()
    )
    assert report['missing_claim_ids'] == []
    assert report['report_cid'] == _cid_without(report, 'report_cid')


def test_protocol_claim_coverage_preserves_not_modeled_semantics() -> None:
    report = _load_json(REPORT_PATH)

    coverage = {item['claim_id']: item for item in report['claim_coverage']}
    assert set(coverage) == set(PROTOCOL_CLAIM_IDS)
    assert set(report['coverage_decision']['covered_claim_ids']) == set(PROTOCOL_CLAIM_IDS)
    assert set(report['coverage_decision']['not_modeled_claim_ids']) == set(NOT_MODELED_CLAIM_IDS)
    for claim_id in NOT_MODELED_CLAIM_IDS:
        assert coverage[claim_id]['protocol_status'] == 'NOT_MODELED'
        assert coverage[claim_id]['modeled_by_lemmas'] == []

    unsupported = report['unsupported_protocol_semantics']
    assert unsupported
    assert {item['status'] for item in unsupported} == {'NOT_MODELED'}
    assert {
        'payload',
        'signing',
        'network',
        'replay',
        'cancellation',
        'expiry',
        'broadcast',
        'refusal',
    } <= {item['category'] for item in unsupported}


def test_attack_traces_are_retained_as_blocking_counterevidence() -> None:
    report = _load_json(REPORT_PATH)
    attack_traces = report['attack_trace_retention']

    assert 'preserve_attack_traces' in attack_traces['policy']
    assert len(attack_traces['disproof_vectors']) == len(PROTOCOL_CLAIM_IDS)
    assert {item['status'] for item in attack_traces['disproof_vectors']} == {'UNKNOWN'}
    assert len(attack_traces['fuzz_counterexamples']) == report['inputs']['fuzz_counterexamples']['counterexample_count']
    assert 'attack-replay-duplicate-resolution.json' in '\n'.join(attack_traces['fuzz_counterexamples'])
    assert 'attack-forged-broadcast-finality.json' in '\n'.join(attack_traces['fuzz_counterexamples'])


def test_required_protocol_solver_lane_executes_but_unresolved_assumptions_stay_blocking() -> None:
    report = _load_json(REPORT_PATH)
    blocker_codes = {blocker['code'] for blocker in report['blockers']}

    assert report['coverage_decision']['decision'] == 'required'
    assert report['coverage_decision']['unavailable_protocol_solver_blocks_testnet_assurance'] is True
    assert report['solver_lanes']['tamarin']['required'] is True
    assert report['solver_lanes']['proverif']['required'] is True
    assert report['solver_lanes']['tamarin']['status'] == 'passed'
    assert report['solver_lanes']['proverif']['status'] == 'passed'
    assert report['solver_lanes']['tamarin']['run']['exit_code'] == 0
    assert report['solver_lanes']['proverif']['run']['exit_code'] == 0
    assert blocker_codes == set()
    assert report['overall_status'] == 'checked_with_unresolved_threat_model_gaps'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_PROTOCOL_ASSUMPTIONS'
    assert report['testnet_assurance_blocked'] is True
    assert report['production_release_blocked'] is True


def test_report_builder_is_regenerable_and_fail_closed_when_solvers_are_missing() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    assumptions = _load_json(REPO_ROOT / ASSUMPTIONS_PATH)
    fuzz_manifest = _load_json(REPO_ROOT / FUZZ_COUNTEREXAMPLE_MANIFEST_PATH)
    report = _load_json(REPORT_PATH)
    tamarin_source = TAMARIN_PATH.read_text(encoding='utf-8')

    regenerated = build_xaman_testnet_protocol_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        tamarin_source=tamarin_source,
        tamarin_executable=report['solver_lanes']['tamarin']['executable'],
        tamarin_version=report['solver_lanes']['tamarin']['version'],
        tamarin_run=report['solver_lanes']['tamarin']['run'],
        proverif_executable=report['solver_lanes']['proverif']['executable'],
        proverif_version=report['solver_lanes']['proverif']['version'],
        proverif_model_source=PROVERIF_PATH.read_text(encoding='utf-8'),
        proverif_run=report['solver_lanes']['proverif']['run'],
        fuzz_counterexample_manifest=fuzz_manifest,
    )
    assert regenerated == report

    missing_solvers = build_xaman_testnet_protocol_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        tamarin_source=tamarin_source,
        tamarin_executable=None,
        proverif_executable=None,
        proverif_model_source=PROVERIF_PATH.read_text(encoding='utf-8'),
        fuzz_counterexample_manifest=fuzz_manifest,
    )
    missing_codes = {blocker['code'] for blocker in missing_solvers['blockers']}
    assert 'TAMARIN_EXECUTABLE_MISSING' in missing_codes
    assert 'PROVERIF_EXECUTABLE_MISSING' in missing_codes
    assert missing_solvers['overall_status'] == 'blocked_required_lane_unavailable'
    assert missing_solvers['testnet_assurance_blocked'] is True


def test_protocol_documentation_records_required_lane_and_current_blocker() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-135' in doc
    assert TAMARIN_ARTIFACT_PATH in doc
    assert PROTOCOL_REPORT_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'Tamarin and ProVerif are required.' in doc
    assert 'NOT_MODELED' in doc
    assert 'preserve attack traces' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_PROTOCOL_ASSUMPTIONS' in doc
