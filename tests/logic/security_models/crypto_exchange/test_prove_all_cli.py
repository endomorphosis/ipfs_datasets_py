from copy import deepcopy
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import main
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.proof_report import ProofReport


def test_fail_on_disproof_returns_nonzero(monkeypatch) -> None:
    """GIVEN a blocking DISPROVED report WHEN fail-on disproof is requested THEN the CLI returns nonzero."""

    def _stub_prove_claims(model, provers):
        return [
            ProofReport(
                claim_id='claim:test',
                model_cid='cid:model',
                status='DISPROVED',
                prover='z3',
                proof_or_trace_cid='cid:trace',
                assumptions=['A4'],
                compiler_cid='cid:compiler',
                risk='blocking',
                signatures=[],
            )
        ]

    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        _stub_prove_claims,
    )
    assert main(['--example', '--fail-on', 'disproof']) == 1


def test_require_real_ergoai_rejects_simulated_dependency(monkeypatch) -> None:
    """GIVEN a simulated F-logic dependency WHEN real ErgoAI is required THEN the CLI rejects the run."""

    model = deepcopy(example_minimal_exchange_model())
    model.metadata['proof_dependency_modes'] = {'flogic': 'simulated', 'zkp': 'not-used'}
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all._load_model',
        lambda args: model,
    )
    assert main(['--example', '--require-real-ergoai']) == 2


def test_forbid_simulated_zkp_rejects_simulated_dependency(monkeypatch) -> None:
    """GIVEN a simulated ZKP dependency WHEN simulated ZKP is forbidden THEN the CLI rejects the run."""

    model = deepcopy(example_minimal_exchange_model())
    model.metadata['proof_dependency_modes'] = {'flogic': 'not-used', 'zkp': 'simulated'}
    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all._load_model',
        lambda args: model,
    )
    assert main(['--example', '--forbid-simulated-zkp']) == 2


def test_source_path_autoformalizes_code_before_proving(tmp_path: Path, monkeypatch) -> None:
    """GIVEN a supported source path WHEN passed to the CLI THEN it proves against the autoformalized model."""

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

    def _stub_prove_claims(model, provers):
        seen['model'] = model
        seen['provers'] = list(provers)
        return []

    monkeypatch.setattr(
        'ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all.prove_claims',
        _stub_prove_claims,
    )

    assert main(['--source-path', str(source_path), '--source-model-id', 'source-proof-model', '--provers', 'z3']) == 0
    assert seen['model'].model_id == 'source-proof-model'
    assert any(policy['name'] == 'authorization_required' for policy in seen['model'].policies)
    assert seen['provers'] == ['z3']
