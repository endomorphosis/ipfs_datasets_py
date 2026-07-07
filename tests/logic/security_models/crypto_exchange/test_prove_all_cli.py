import json
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import main
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport



def _report(**overrides) -> ProofReport:
    model = example_minimal_exchange_model()
    payload = dict(
        claim_id='claim:test',
        claim_version='1.0',
        model_cid='cid:model',
        model_schema_version=model.schema_version,
        status='PROVED',
        prover='z3',
        solver_name='z3',
        solver_version='4.16.0',
        solver_result='unsat',
        proof_or_trace_cid='cid:proof',
        assumptions=['A4'],
        compiler_cid='cid:compiler',
        risk='blocking',
        signatures=[],
        evidence_refs=[],
        soundness_notes=[],
    )
    payload.update(overrides)
    return ProofReport(**payload)



def test_fail_on_disproof_returns_nonzero(monkeypatch) -> None:
    def _prove_claims_override(model, provers):
        return [_report(status='DISPROVED', solver_result='sat', proof_or_trace_cid='cid:trace', counterexample={'bad': True})]

    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        _prove_claims_override,
    )
    assert main(['--example', '--fail-on', 'disproof']) == 1


def test_fail_on_not_modeled_critical_returns_nonzero(monkeypatch) -> None:
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [_report(status='NOT_MODELED', solver_result='not-modeled')],
    )
    assert main(['--example', '--fail-on', 'not-modeled-critical']) == 1



def test_require_real_ergoai_rejects_simulated_dependency(monkeypatch) -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.metadata['proof_dependency_modes'] = {'flogic': 'simulated', 'zkp': 'not-used'}
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all._load_model',
        lambda args: model,
    )
    assert main(['--example', '--require-real-ergoai']) == 2



def test_forbid_simulated_zkp_rejects_simulated_dependency(monkeypatch) -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.metadata['proof_dependency_modes'] = {'flogic': 'not-used', 'zkp': 'simulated'}
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all._load_model',
        lambda args: model,
    )
    assert main(['--example', '--forbid-simulated-zkp']) == 2



def test_source_path_autoformalizes_code_before_proving(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / 'withdrawals.py'
    source_path.write_text(
        '''
def approve_withdrawal(authorized):
    """Every withdrawal must be authorized before broadcast."""
    if not authorized:
        raise PermissionError("authorization required")
    return True
''',
        encoding='utf-8',
    )

    seen = {}

    def _prove_claims_override(model, provers):
        seen['model'] = model
        seen['provers'] = list(provers)
        return []

    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        _prove_claims_override,
    )

    assert main(['--source-path', str(source_path), '--source-model-id', 'source-proof-model', '--provers', 'z3']) == 0
    assert seen['model'].model_id == 'source-proof-model'
    assert any(policy['name'] == 'authorization_required' for policy in seen['model'].policies)
    assert seen['provers'] == ['z3']



def test_cli_fails_on_heuristic_only_blocking_claim_when_requested(monkeypatch) -> None:
    heuristic_report = _report(
        evidence_refs=[{'kind': 'source_code', 'path': 'x.py', 'review_status': 'heuristic'}],
        soundness_notes=['heuristic only'],
    )
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [heuristic_report],
    )
    assert main(['--example', '--require-reviewed-evidence']) == 1



def test_cli_fails_on_missing_blocking_evidence_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [_report(evidence_refs=[])],
    )
    assert main(['--example', '--require-reviewed-evidence']) == 1



def test_cli_fails_on_machine_extracted_only_blocking_evidence_when_requested(monkeypatch) -> None:
    machine_report = _report(
        evidence_refs=[{'kind': 'source_code', 'path': 'x.py', 'review_status': 'machine_extracted'}],
        soundness_notes=['machine extracted only'],
    )
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [machine_report],
    )
    assert main(['--example', '--require-reviewed-evidence']) == 1



def test_cli_allows_trusted_fixture_blocking_evidence_when_requested(monkeypatch) -> None:
    trusted_report = _report(
        evidence_refs=[{'kind': 'test_fixture', 'path': 'fixture.py', 'review_status': 'trusted_fixture'}],
    )
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [trusted_report],
    )
    assert main(['--example', '--require-reviewed-evidence']) == 0



def test_cli_does_not_fail_non_blocking_claim_under_reviewed_evidence_policy(monkeypatch) -> None:
    non_blocking_report = _report(
        risk='medium',
        evidence_refs=[],
        soundness_notes=['no evidence attached'],
    )
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [non_blocking_report],
    )
    assert main(['--example', '--require-reviewed-evidence']) == 0



def test_cli_emits_proof_receipts_and_counterexamples(tmp_path: Path, monkeypatch) -> None:
    report_path = tmp_path / 'proof_report.json'
    counterexamples_dir = tmp_path / 'counterexamples'
    disproved_report = _report(status='DISPROVED', solver_result='sat', counterexample={'witness': 'bad'})
    proved_report = _report(claim_id='claim:proved')
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: [disproved_report, proved_report],
    )
    assert main([
        '--example',
        '--emit-proof-receipts',
        '--accepted-assumptions',
        'A4',
        '--emit-counterexamples-dir',
        str(counterexamples_dir),
        '--out',
        str(report_path),
    ]) == 0
    payload = json.loads(report_path.read_text(encoding='utf-8'))
    assert 'proof_receipts' in payload
    assert payload['coverage']['total_claims'] == 2
    assert (counterexamples_dir / 'claim:test.json').exists()


def test_cli_rejects_receipt_emission_without_explicit_or_unsafe_assumptions(tmp_path: Path) -> None:
    report_path = tmp_path / 'proof_report.json'
    with pytest.raises(SystemExit):
        main(['--example', '--emit-proof-receipts', '--out', str(report_path)])


def test_cli_coverage_thresholds_fail_when_modeled_or_proved_counts_are_too_low(monkeypatch) -> None:
    reports = [
        _report(claim_id='no_unauthorized_withdrawal'),
        _report(claim_id='global_asset_conservation', status='NOT_MODELED', solver_result='not-modeled'),
    ]
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: reports,
    )
    assert main(['--example', '--min-modeled-blocking-claims', '2']) == 1
    assert main(['--example', '--min-proved-blocking-claims', '2']) == 1



def test_cli_require_domain_fails_when_requested_domain_is_not_modeled(monkeypatch) -> None:
    reports = [
        _report(claim_id='no_unauthorized_withdrawal'),
        _report(claim_id='global_asset_conservation', status='NOT_MODELED', solver_result='not-modeled'),
    ]
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: reports,
    )
    assert main(['--example', '--require-domain', 'ledger']) == 1
    assert main(['--example', '--require-domain', 'withdrawals']) == 0



def test_cli_coverage_summary_includes_domain_details(tmp_path: Path, monkeypatch) -> None:
    report_path = tmp_path / 'coverage.json'
    reports = [
        _report(claim_id='no_unauthorized_withdrawal'),
        _report(claim_id='global_asset_conservation', status='NOT_MODELED', solver_result='not-modeled'),
        _report(claim_id='no_deposit_before_finality', risk='high'),
    ]
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        lambda model, provers: reports,
    )
    assert main(['--example', '--out', str(report_path)]) == 0
    payload = json.loads(report_path.read_text(encoding='utf-8'))
    assert payload['coverage']['domains_modeled']['withdrawals'] is True
    assert payload['coverage']['domains_modeled']['ledger'] is False
    assert payload['coverage']['domain_summary']['withdrawals']['claim_statuses']['no_unauthorized_withdrawal'] == 'PROVED'
    assert payload['coverage']['domain_summary']['ledger']['blocking_not_modeled'] == 1



def test_cli_strict_validation_rejects_invalid_model(tmp_path: Path) -> None:
    model_path = tmp_path / 'invalid.json'
    payload = example_minimal_exchange_model().to_dict()
    payload['accounts'][0]['wallet_id'] = 'wallet:missing'
    model_path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(SystemExit) as exc_info:
        main(['--model', str(model_path), '--strict-validation'])
    assert exc_info.value.code != 0


@pytest.mark.parametrize(
    'mutator',
    [
        lambda payload: payload.pop('events'),
        lambda payload: payload.__setitem__('metadata', 'not-a-dict'),
        lambda payload: payload['events'].__setitem__(0, 'not-a-dict'),
        lambda payload: payload.__setitem__('proover_targets', ['z3']),
    ],
)
def test_cli_strict_validation_rejects_invalid_raw_payloads(tmp_path: Path, mutator) -> None:
    model_path = tmp_path / 'invalid-raw.json'
    payload = example_minimal_exchange_model().to_dict()
    mutator(payload)
    model_path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(SystemExit) as exc_info:
        main(['--model', str(model_path), '--strict-validation'])
    assert exc_info.value.code != 0
