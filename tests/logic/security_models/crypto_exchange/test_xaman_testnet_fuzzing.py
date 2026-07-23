"""Tests for PORTAL-CXTP-138 Xaman Testnet fuzz campaigns."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_fuzzing import (
    CLAIMS,
    COUNTEREXAMPLE_DIR,
    FUZZ_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    TRACE_MAP_PATH,
    FuzzRejection,
    build_xaman_testnet_fuzz_report,
    counterexample_artifacts,
    parse_untrusted_ir,
    validate_attack_mutation,
    validate_trace_input,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / FUZZ_REPORT_PATH
COUNTEREXAMPLES_PATH = REPO_ROOT / COUNTEREXAMPLE_DIR
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_fuzzing.md'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _report() -> dict:
    return _load_json(REPORT_PATH)


def _campaign(report: dict, campaign_id: str) -> dict:
    return {
        campaign['campaign_id']: campaign
        for campaign in report['campaigns']
    }[campaign_id]


def test_fuzz_report_is_regenerable_and_bound_to_testnet_model() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    generated = build_xaman_testnet_fuzz_report(
        model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
    )
    report = _report()

    assert generated == report
    assert report['schema_version'] == 'xaman-testnet-fuzz-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-138'
    assert report['model']['path'] == MODEL_PATH
    assert report['model']['cid'] == model_cid
    assert report['trace_map']['model_cid'] == model_cid
    assert report['artifact_cid']


def test_acceptance_gates_pass_without_crashes_or_unexpected_acceptance() -> None:
    report = _report()

    assert report['summary']['overall_status'] == 'passed'
    assert report['summary']['security_decision'] == 'TESTNET_FUZZ_CAMPAIGNS_PASSED_BOUNDED_GENERATED_COVERAGE'
    assert report['acceptance_gates'] == {
        'expected_attack_mutation_targets': 'pass',
        'fuzzer_crash': 'pass',
        'malformed_security_ir_parser': 'pass',
        'redaction_breach': 'pass',
    }
    assert report['summary']['fuzzer_crash_count'] == 0
    assert report['summary']['malformed_ir_acceptance_count'] == 0
    assert report['summary']['redaction_breach_acceptance_count'] == 0
    assert report['summary']['missing_target_claim_trigger_count'] == 0
    assert all(campaign['status'] == 'passed' for campaign in report['campaigns'])
    assert all(
        case['crash'] is None and case['status'] == 'passed'
        for campaign in report['campaigns']
        for case in campaign['cases']
    )


def test_trace_campaign_rejects_ambiguity_redaction_breaches_and_scope_mutations() -> None:
    campaign = _campaign(_report(), 'trace-mutation-campaign')
    cases = {case['case_id']: case for case in campaign['cases']}

    assert cases['trace-seed-reviewed-valid']['result'] == 'accepted'
    for case_id in {
        'trace-duplicate-action',
        'trace-duplicate-ordinal',
        'trace-signing-before-auth',
        'trace-unreviewed-source-kind',
        'trace-raw-material-recorded',
        'trace-redaction-breach-field',
        'trace-missing-cancel-gap',
        'trace-wrong-network',
        'trace-imported-production-account',
        'trace-submit-result-outcome-changed',
    }:
        assert cases[case_id]['result'] == 'rejected'
        assert cases[case_id]['rejection_reason']


def test_malformed_security_ir_campaign_rejects_every_bad_parser_input() -> None:
    campaign = _campaign(_report(), 'malformed-security-ir-parser-campaign')
    cases = {case['case_id']: case for case in campaign['cases']}

    assert cases['ir-seed-valid']['result'] == 'accepted'
    malformed = {case_id: case for case_id, case in cases.items() if case_id != 'ir-seed-valid'}
    assert len(malformed) >= 10
    assert all(case['result'] == 'rejected' for case in malformed.values())
    assert all(case['rejection_reason'] for case in malformed.values())


def test_expected_attack_mutations_trigger_target_claims_and_counterexamples() -> None:
    report = _report()
    claim_ids = {claim['id'] for claim in _load_json(REPO_ROOT / MODEL_PATH)['claims']}

    assert report['summary']['counterexample_count'] == len(report['attack_mutations']) >= 10
    for mutation in report['attack_mutations']:
        assert mutation['status'] == 'passed'
        assert mutation['result'] == 'target_claim_triggered'
        assert mutation['target_claim_id'] in claim_ids
        assert mutation['target_claim_id'] in mutation['triggered_claim_ids']
        counterexample = _load_json(REPO_ROOT / mutation['counterexample_path'])
        assert counterexample['schema_version'] == 'xaman-testnet-fuzz-counterexample/v1'
        assert counterexample['target_claim_id'] == mutation['target_claim_id']
        assert counterexample['triggered_claim_ids'] == mutation['triggered_claim_ids']
        assert counterexample['raw_sensitive_material_recorded'] is False


def test_counterexample_directory_matches_report_manifest() -> None:
    report = _report()
    generated = counterexample_artifacts(report)

    assert COUNTEREXAMPLES_PATH.is_dir()
    for rel_path, expected in generated.items():
        assert _load_json(REPO_ROOT / rel_path) == expected
    manifest = _load_json(COUNTEREXAMPLES_PATH / 'manifest.json')
    assert manifest['counterexample_count'] == len(report['attack_mutations'])
    assert set(manifest['counterexamples']) == {
        mutation['counterexample_path']
        for mutation in report['attack_mutations']
    }


def test_fail_closed_oracles_reject_redaction_parser_and_target_claim_breaches() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    valid_trace = {
        'network_key': 'TESTNET',
        'network_id': 1,
        'fresh_account_boundary': {
            'fresh_account_created': True,
            'imported_account': False,
            'production_account': False,
            'account_material_recorded': False,
        },
        'coverage_gaps': [
            {'action': 'decline', 'reason_code': 'not_exercised_in_reviewed_trial'},
            {'action': 'cancel', 'reason_code': 'not_exercised_in_reviewed_trial'},
            {'action': 'expiry', 'reason_code': 'not_exercised_in_reviewed_trial'},
        ],
        'events': [
            {
                'ordinal': index,
                'action': action,
                'category': fields['category'],
                'outcome': fields['outcome'],
                'source_kind': 'reviewed_ui',
                'raw_material_recorded': False,
                'redaction_sha256': str(index) * 64,
            }
            for index, (action, fields) in enumerate(
                {
                    'payload_intake': {'category': 'payload_intake', 'outcome': 'accepted'},
                    'review': {'category': 'payload_review', 'outcome': 'reviewed'},
                    'auth_decision': {'category': 'auth_decision', 'outcome': 'authorized'},
                    'signing_decision': {'category': 'signing_decision', 'outcome': 'signed'},
                    'submit_attempt': {'category': 'submit_attempt', 'outcome': 'submitted'},
                    'submit_result': {'category': 'submit_result', 'outcome': 'succeeded'},
                    'reconnect': {'category': 'reconnect', 'outcome': 'reconnected'},
                    'network_switch': {'category': 'network_switch', 'outcome': 'switched_to_testnet'},
                }.items(),
                start=1,
            )
        ],
    }
    breached_trace = deepcopy(valid_trace)
    breached_trace['events'][0]['raw_payload_json'] = True
    with pytest.raises(FuzzRejection, match='redaction breach rejected'):
        validate_trace_input(breached_trace, model)

    malformed_ir = deepcopy(model)
    malformed_ir['proof_obligations'][0]['status'] = 'FORGED_PROOF'
    with pytest.raises(FuzzRejection, match='unsupported status'):
        parse_untrusted_ir(malformed_ir, model)

    wrong_target = {
        'target_claim_id': CLAIMS['network'],
        'mutation': {'payload_material_boundary_crossed': True},
    }
    with pytest.raises(FuzzRejection, match='did not trigger target claim'):
        validate_attack_mutation(wrong_target, model)


def test_partial_attack_selection_runs_selected_mutations_only_in_partial_mode() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    selected_ids = [
        'attack-raw-payload-material',
        'attack-review-bypass',
    ]

    report = build_xaman_testnet_fuzz_report(
        model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        selected_attack_mutation_ids=selected_ids,
        strict=False,
    )

    assert report['summary']['selected_attack_mutation_count'] == len(selected_ids)
    assert set(mutation['mutation_id'] for mutation in report['attack_mutations']) == set(selected_ids)
    assert report['coverage_statement']['coverage_mode'] == 'selected_attack_mutation_subset'
    assert report['coverage_statement']['strict'] is False
    assert report['adversarial_acceptance_gates']['registered_fuzz_domain_coverage'] == 'pass'
    assert report['summary']['overall_status'] == 'passed'


def test_partial_attack_selection_rejects_unknown_ids() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()

    with pytest.raises(ValueError, match='requested attack mutation IDs are not defined'):
        build_xaman_testnet_fuzz_report(
            model,
            model_cid=model_cid,
            trace_map_payload=trace_map,
            selected_attack_mutation_ids=['attack-does-not-exist'],
            strict=False,
        )


def test_partial_counterexample_artifacts_only_includes_selected_attacks() -> None:
    report = _report()
    selected = [report['attack_mutations'][0]['mutation_id'], report['attack_mutations'][1]['mutation_id']]
    artifacts = counterexample_artifacts(report, selected_attack_mutation_ids=selected)

    manifest = artifacts[f'{COUNTEREXAMPLE_DIR}/manifest.json']
    assert manifest['counterexample_count'] == 2
    assert set(manifest['counterexamples']) == {
        f'{COUNTEREXAMPLE_DIR}/{selected[0]}.json',
        f'{COUNTEREXAMPLE_DIR}/{selected[1]}.json',
    }
    for entry in selected:
        assert f'{COUNTEREXAMPLE_DIR}/{entry}.json' in artifacts


def test_documentation_states_bounded_coverage_not_all_wallet_inputs() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-138' in doc
    assert 'fuzz-report.json' in doc
    assert 'counterexamples' in doc
    assert 'bounded generated' in doc
    assert 'not all possible wallet inputs' in doc
