import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'run_security_ir_disproof_suite.py'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'run_security_ir_disproof_suite',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load disproof suite script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disproof_suite_finds_expected_counterexamples_and_fuzzed_mutations(
    tmp_path: Path,
) -> None:
    """GIVEN the example model WHEN the disproof suite runs.

    THEN expected counterexamples are reported.
    """

    module = _load_script_module()
    output_path = tmp_path / 'disproof-report.json'
    vectors_dir = tmp_path / 'counterexamples'

    assert (
        module.main(
            [
                '--example',
                '--fuzz-rounds',
                '2',
                '--seed',
                '7',
                '--out',
                str(output_path),
                '--emit-counterexamples-dir',
                str(vectors_dir),
            ]
        )
        == 0
    )

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    scenarios = {
        scenario['name']: scenario
        for scenario in payload['scenarios']
    }

    assert (
        scenarios['unauthorized_withdrawal_policy_gap']['matched_claims']
        == [
            'no_unauthorized_withdrawal'
        ]
    )
    assert (
        scenarios['double_spend_reservation_gap']['matched_claims']
        == [
            'no_over_reserved_internal_account'
        ]
    )
    assert scenarios['deposit_before_finality_gap']['matched_claims'] == [
        'no_deposit_before_finality'
    ]
    assert scenarios['multi_asset_conservation_gap']['matched_claims'] == [
        'global_asset_conservation'
    ]
    assert scenarios['multi_chain_conservation_gap']['matched_claims'] == [
        'global_asset_conservation'
    ]
    assert scenarios['mempool_replacement_gap']['matched_claims'] == [
        'no_unauthorized_withdrawal'
    ]
    assert scenarios['nonce_reuse_without_reservation']['matched_claims'] == [
        'no_unauthorized_withdrawal'
    ]
    assert scenarios['partial_rollback_deposit_gap']['matched_claims'] == [
        'no_deposit_before_finality'
    ]
    assert scenarios['post_freeze_signing_gap']['matched_claims'] == [
        'no_signing_request_after_wallet_freeze'
    ]
    assert scenarios['reorg_after_deposit_credit']['matched_claims'] == [
        'no_deposit_before_finality'
    ]
    assert scenarios['delegation_authority_escalation']['matched_claims'] == [
        'capability_delegation_no_authority_increase'
    ]
    assert scenarios['admin_quorum_delegation_gap']['matched_claims'] == [
        'capability_delegation_no_authority_increase'
    ]
    assert scenarios['revocation_enforcement_gap']['matched_claims'] == [
        'revoked_capability_no_future_authorization'
    ]
    assert scenarios['stale_rpc_finality_gap']['matched_claims'] == [
        'no_deposit_before_finality'
    ]
    assert scenarios['rpc_censorship_finality_gap']['matched_claims'] == [
        'no_deposit_before_finality'
    ]
    assert scenarios['missing_audit_transition']['matched_claims'] == [
        'audit_event_exists_for_critical_transition'
    ]

    fuzzed = [name for name in scenarios if name.startswith('fuzz:')]
    assert len(fuzzed) == 2
    assert payload['summary']['scenario_count'] == 18
    assert payload['summary']['scenario_failures'] == 0
    expected_vector_count = sum(
        1
        for scenario in payload['scenarios']
        for report in scenario['reports']
        if report['status'] == 'DISPROVED' and report['counterexample']
    )
    vector_paths = sorted(vectors_dir.glob('*.json'))
    assert len(vector_paths) == expected_vector_count
    assert payload['summary']['counterexample_vector_count'] == expected_vector_count

    vectors = [
        json.loads(path.read_text(encoding='utf-8'))
        for path in vector_paths
    ]
    vector_keys = {
        (vector['scenario'], vector['claim_id'])
        for vector in vectors
    }
    assert (
        'mempool_replacement_gap',
        'no_unauthorized_withdrawal',
    ) in vector_keys
    assert (
        'partial_rollback_deposit_gap',
        'no_deposit_before_finality',
    ) in vector_keys
    assert all(vector['status'] == 'DISPROVED' for vector in vectors)
    assert all(isinstance(vector['counterexample'], dict) for vector in vectors)
