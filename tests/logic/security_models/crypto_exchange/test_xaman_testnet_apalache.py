"""Tests for PORTAL-CXTP-134 Xaman Testnet Apalache concurrency lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_apalache import (
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    CHECKED_INVARIANTS,
    CONCURRENCY_ASSUMPTION_IDS,
    CONCURRENCY_CLAIM_IDS,
    MODEL_CID_PATH,
    MODEL_PATH,
    REQUIRED_OPERATORS,
    SCHEMA_VERSION,
    TASK_ID,
    TLA_ARTIFACT_PATH,
    TRACE_MAP_PATH,
    build_xaman_testnet_apalache_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
TLA_PATH = REPO_ROOT / TLA_ARTIFACT_PATH
REPORT_PATH = REPO_ROOT / APALACHE_REPORT_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_apalache.md'
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def test_xaman_testnet_tla_models_payload_resolution_concurrency() -> None:
    body = TLA_PATH.read_text(encoding='utf-8')

    assert '---- MODULE XamanTestnetPayload ----' in body
    assert 'PORTAL-CXTP-134' in body
    assert 'Clients == {"clientA", "clientB"}' in body
    assert '\\* @type: Str -> Str;' in body
    assert 'AcquireResolutionLock(c) ==' in body
    assert 'SignResolve(c) ==' in body
    assert 'DuplicateResolveBlocked(c) ==' in body
    assert 'ReplayBlocked(c) ==' in body
    assert 'Spec == Init /\\ [][Next]_Vars' in body
    for operator in REQUIRED_OPERATORS:
        assert operator in body
    for invariant in CHECKED_INVARIANTS:
        assert f'THEOREM Spec => []{invariant}' in body


def test_apalache_report_is_bound_to_pinned_testnet_model_and_tla_source() -> None:
    report = _load_json(REPORT_PATH)
    tla_source = TLA_PATH.read_text(encoding='utf-8').rstrip('\n')
    tla_sha = 'sha256:' + hashlib.sha256(tla_source.encode('utf-8')).hexdigest()

    assert report['schema_version'] == SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['model']['cid'] == PINNED_MODEL_CID
    assert report['model']['cid'] == (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assert report['tla_model']['path'] == TLA_ARTIFACT_PATH
    assert report['tla_model']['module_name'] == 'XamanTestnetPayload'
    assert report['tla_model']['sha256'] == tla_sha
    assert report['tla_model']['checked_invariants'] == list(CHECKED_INVARIANTS)
    assert report['missing_claim_ids'] == []
    assert report['missing_assumption_ids'] == []
    assert report['report_cid'] == _cid_without(report, 'report_cid')


def test_apalache_lane_checked_all_invariants_but_assurance_stays_blocked() -> None:
    report = _load_json(REPORT_PATH)

    assert report['apalache']['required'] is True
    assert report['apalache']['available'] is True
    assert report['apalache']['unavailable_blocks_testnet_assurance'] is True
    assert report['summary']['all_required_invariants_checked'] is True
    assert report['summary']['checked_invariant_count'] == len(CHECKED_INVARIANTS) == 7
    assert report['summary']['run_failure_count'] == 0
    assert {run['invariant'] for run in report['apalache']['runs']} == set(CHECKED_INVARIANTS)
    for run in report['apalache']['runs']:
        assert run['status'] == 'pass'
        assert run['exit_code'] == 0
        assert '--no-deadlock' in run['command']
        assert run['output_retained'] is False

    assert report['overall_status'] == 'checked_with_unresolved_threat_model_gaps'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_CONCURRENCY_ASSUMPTIONS'
    assert report['testnet_assurance_blocked'] is True
    assert report['production_release_blocked'] is True


def test_coverage_decision_makes_apalache_required_and_scoped() -> None:
    report = _load_json(REPORT_PATH)
    decision = report['coverage_decision']

    assert decision['decision'] == 'required'
    assert decision['unavailable_apalache_blocks_testnet_assurance'] is True
    assert set(decision['covered_claim_ids']) == set(CONCURRENCY_CLAIM_IDS)
    assert set(decision['required_by_assumption_ids']) == set(CONCURRENCY_ASSUMPTION_IDS)
    assert 'finite client-visible Testnet payload-resolution interleavings' == decision['claim_scope']
    assert 'backend atomic single-use implementation' in decision['not_modeled']
    assert report['summary']['unresolved_required_assumption_count'] == 2
    assert {
        assumption['id']
        for assumption in report['unresolved_required_assumptions']
    } == set(CONCURRENCY_ASSUMPTION_IDS)

    covered_claim_statuses = {item['claim_id']: item['status'] for item in report['claim_coverage']}
    assert covered_claim_statuses['xaman-testnet-claim:replay-controls-are-not-modeled'] == 'NOT_MODELED'
    assert (
        covered_claim_statuses['xaman-testnet-claim:submission-ui-attempt-and-result-are-observed']
        == 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY'
    )


def test_report_builder_is_regenerable_from_bound_inputs_and_fail_closed_when_solver_missing() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    assumptions = _load_json(REPO_ROOT / ASSUMPTIONS_PATH)
    report = _load_json(REPORT_PATH)
    tla_source = TLA_PATH.read_text(encoding='utf-8').rstrip('\n')

    regenerated = build_xaman_testnet_apalache_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        tla_source=tla_source,
        apalache_executable=report['apalache']['executable'],
        apalache_version=report['apalache']['version'],
        apalache_runs=report['apalache']['runs'],
    )
    assert regenerated == report

    missing_solver = build_xaman_testnet_apalache_report(
        model_payload=model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
        tla_source=tla_source,
        apalache_executable=None,
        apalache_version=None,
        apalache_runs=None,
    )
    assert missing_solver['apalache']['available'] is False
    assert missing_solver['coverage_decision']['unavailable_apalache_blocks_testnet_assurance'] is True
    assert missing_solver['overall_status'] == 'blocked_required_lane_unavailable'
    assert missing_solver['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_APALACHE_UNAVAILABLE'
    assert missing_solver['testnet_assurance_blocked'] is True


def test_documentation_records_required_concurrency_lane_and_current_blocker() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-134' in doc
    assert TLA_ARTIFACT_PATH in doc
    assert APALACHE_REPORT_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'Concurrency coverage is required.' in doc
    assert 'unavailable Apalache lane blocks the Testnet assurance verdict' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_CONCURRENCY_ASSUMPTIONS' in doc
