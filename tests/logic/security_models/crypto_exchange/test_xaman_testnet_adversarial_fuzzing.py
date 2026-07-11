"""Tests for PORTAL-CXTP-148 adversarial Testnet fuzzing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_fuzzing import (
    CAMPAIGN_MANIFEST_PATH,
    CLAIMS,
    COUNTEREXAMPLE_DIR,
    FUZZ_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    REGISTERED_FUZZ_DOMAIN_IDS,
    TRACE_MAP_PATH,
    FuzzRejection,
    build_campaign_manifest,
    build_xaman_testnet_fuzz_report,
    counterexample_artifacts,
    validate_attack_mutation,
    validate_registered_fuzz_domain,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
DOC_PATH = REPO_ROOT / 'docs/security_verification/xaman_testnet_adversarial_fuzzing.md'

ACCEPTANCE_DOMAINS = {
    'malformed_payload',
    'replayed_payload',
    'wrong_network',
    'account_import',
    'stale_downgraded_evidence',
    'auth_review_bypass',
    'cancellation_expiry_reconnect_race',
    'transaction_type_mutation',
    'solver_result_tampering',
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _report() -> dict:
    return _load_json(REPO_ROOT / FUZZ_REPORT_PATH)


def _counterexample_manifest() -> dict:
    return _load_json(REPO_ROOT / COUNTEREXAMPLE_DIR / 'manifest.json')


def test_adversarial_campaign_manifest_is_regenerable() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    report = build_xaman_testnet_fuzz_report(
        model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
    )
    generated = build_campaign_manifest(report)
    checked_in = _load_json(REPO_ROOT / CAMPAIGN_MANIFEST_PATH)

    assert generated == checked_in
    assert checked_in['schema_version'] == 'xaman-testnet-adversarial-fuzz-campaign-manifest/v1'
    assert checked_in['task_id'] == 'PORTAL-CXTP-148'
    assert checked_in['depends_on'] == ['PORTAL-CXTP-143', 'PORTAL-CXTP-145', 'PORTAL-CXTP-146']
    assert checked_in['summary']['overall_status'] == 'passed'
    assert checked_in['summary']['covered_registered_domain_count'] == len(ACCEPTANCE_DOMAINS)


def test_registered_fuzz_domains_cover_acceptance_input_spaces() -> None:
    manifest = _load_json(REPO_ROOT / CAMPAIGN_MANIFEST_PATH)

    assert REGISTERED_FUZZ_DOMAIN_IDS == ACCEPTANCE_DOMAINS
    assert manifest['domain_policy'] == {
        'registered_domain_count': len(ACCEPTANCE_DOMAINS),
        'reject_unregistered_domains_as': 'UNMODELED',
        'unregistered_domain_oracle': 'validate_registered_fuzz_domain',
    }

    domains = {domain['domain_id']: domain for domain in manifest['domains']}
    assert set(domains) == ACCEPTANCE_DOMAINS
    assert all(domain['case_count'] > 0 for domain in domains.values())
    assert all(domain['unmodeled_if_unregistered'] is True for domain in domains.values())

    coverage = manifest['acceptance_coverage']
    assert coverage['malformed_and_replayed_payloads'] == ['malformed_payload', 'replayed_payload']
    assert coverage['wrong_network'] == ['wrong_network']
    assert coverage['account_import_attempts'] == ['account_import']
    assert coverage['stale_or_downgraded_evidence'] == ['stale_downgraded_evidence']
    assert coverage['auth_review_bypass'] == ['auth_review_bypass']
    assert coverage['cancellation_expiry_reconnect_races'] == ['cancellation_expiry_reconnect_race']
    assert coverage['transaction_type_mutations'] == ['transaction_type_mutation']
    assert coverage['solver_result_tampering'] == ['solver_result_tampering']


def test_attack_mutations_cover_every_registered_domain_and_expected_cases() -> None:
    report = _report()
    mutations = {mutation['mutation_id']: mutation for mutation in report['attack_mutations']}

    assert report['summary']['counterexample_count'] == 25
    assert report['summary']['registered_fuzz_domain_count'] == len(ACCEPTANCE_DOMAINS)
    assert report['summary']['missing_registered_fuzz_domain_count'] == 0
    assert report['adversarial_acceptance_gates'] == {
        'counterexample_minimization': 'pass',
        'registered_fuzz_domain_coverage': 'pass',
        'unregistered_fuzz_domain_rejection': 'pass',
    }
    assert {mutation['fuzz_domain'] for mutation in mutations.values()} == ACCEPTANCE_DOMAINS

    expected_cases = {
        'attack-malformed-payload-shape',
        'attack-replay-duplicate-submit-result',
        'attack-stale-evidence-digest',
        'attack-downgraded-evidence-review',
        'attack-review-bypass',
        'attack-cancel-after-submit-race',
        'attack-expiry-after-auth-race',
        'attack-reconnect-before-submit-result-race',
        'attack-trustset-transaction-type',
        'attack-offercreate-transaction-type',
        'attack-signerlistset-transaction-type',
        'attack-path-payment-semantics-skipped',
        'attack-solver-result-upgrade',
        'attack-proof-obligation-status-forged',
    }
    assert expected_cases <= set(mutations)
    assert all(mutation['status'] == 'passed' for mutation in mutations.values())
    assert all(mutation['target_claim_id'] in mutation['triggered_claim_ids'] for mutation in mutations.values())


def test_every_counterexample_is_minimized_and_manifest_matches_generator() -> None:
    report = _report()
    generated = counterexample_artifacts(report)
    manifest = _counterexample_manifest()

    assert manifest == generated[f'{COUNTEREXAMPLE_DIR}/manifest.json']
    assert manifest['task_id'] == 'PORTAL-CXTP-148'
    assert manifest['counterexample_count'] == report['summary']['counterexample_count']
    assert manifest['minimization_policy'] == {
        'algorithm': 'deterministic-one-domain-delta-minimizer/v1',
        'every_counterexample_minimized': True,
        'reject_unregistered_fuzz_domains_as': 'UNMODELED',
    }
    assert set(manifest['fuzz_domains']) == ACCEPTANCE_DOMAINS

    for rel_path in manifest['counterexamples']:
        artifact = _load_json(REPO_ROOT / rel_path)
        assert artifact == generated[rel_path]
        assert artifact['task_id'] == 'PORTAL-CXTP-148'
        assert artifact['fuzz_domain'] in ACCEPTANCE_DOMAINS
        assert artifact['raw_sensitive_material_recorded'] is False
        assert artifact['minimization']['status'] == 'minimal'
        assert artifact['minimization']['raw_sensitive_material_recorded'] is False
        assert artifact['minimal_counterexample']['fuzz_domain'] == artifact['fuzz_domain']
        assert artifact['minimal_counterexample']['target_claim_id'] == artifact['target_claim_id']
        assert artifact['minimal_counterexample']['payload_sha256'] == artifact['payload_sha256']
        assert artifact['minimal_counterexample']['mutation_keys']


def test_unregistered_fuzz_domain_is_rejected_as_unmodeled() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)

    with pytest.raises(FuzzRejection, match='unregistered fuzz domain rejected as unmodeled'):
        validate_registered_fuzz_domain('native_backend_single_use_oracle')

    with pytest.raises(FuzzRejection, match='unregistered fuzz domain rejected as unmodeled'):
        validate_attack_mutation(
            {
                'mutation_id': 'attack-unregistered-domain',
                'fuzz_domain': 'native_backend_single_use_oracle',
                'target_claim_id': CLAIMS['payload'],
                'mutation': {'payload_material_boundary_crossed': True},
                'raw_material_retained': False,
                'uses_categorical_markers_only': True,
            },
            model,
        )


def test_documentation_records_adversarial_scope_and_outputs() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-148' in doc
    assert 'campaign-manifest.json' in doc
    assert 'counterexamples/manifest.json' in doc
    assert 'validate_registered_fuzz_domain' in doc
    assert 'UNMODELED' in doc
    for domain in ACCEPTANCE_DOMAINS:
        assert domain in doc
