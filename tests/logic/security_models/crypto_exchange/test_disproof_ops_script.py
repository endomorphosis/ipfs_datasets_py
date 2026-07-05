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
    assert scenarios['post_freeze_signing_gap']['matched_claims'] == [
        'no_signing_request_after_wallet_freeze'
    ]
    assert scenarios['delegation_authority_escalation']['matched_claims'] == [
        'capability_delegation_no_authority_increase'
    ]
    assert scenarios['revocation_enforcement_gap']['matched_claims'] == [
        'revoked_capability_no_future_authorization'
    ]
    assert scenarios['missing_audit_transition']['matched_claims'] == [
        'audit_event_exists_for_critical_transition'
    ]

    fuzzed = [name for name in scenarios if name.startswith('fuzz:')]
    assert len(fuzzed) == 2
    assert payload['summary']['scenario_failures'] == 0
