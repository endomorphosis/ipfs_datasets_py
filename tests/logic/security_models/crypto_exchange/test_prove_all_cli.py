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
        '--emit-counterexamples-dir',
        str(counterexamples_dir),
        '--out',
        str(report_path),
    ]) == 0
    payload = json.loads(report_path.read_text(encoding='utf-8'))
    assert 'proof_receipts' in payload
    assert (counterexamples_dir / 'claim:test.json').exists()



def test_cli_strict_validation_rejects_invalid_model(tmp_path: Path) -> None:
    model_path = tmp_path / 'invalid.json'
    payload = example_minimal_exchange_model().to_dict()
    payload['accounts'][0]['wallet_id'] = 'wallet:missing'
    model_path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(SystemExit) as exc_info:
        main(['--model', str(model_path), '--strict-validation'])
    assert exc_info.value.code != 0
