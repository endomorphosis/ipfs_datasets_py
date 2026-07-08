from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import PythonASTExtractor
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir


def test_python_ast_extractor_autoformalizes_source_into_security_ir() -> None:
    """GIVEN security-relevant Python source WHEN autoformalized THEN a seed security IR is emitted."""

    source = '''
class Wallet:
    """Wallets must never sign after they are frozen."""


def approve_withdrawal(wallet, authorized, balance, audit_log):
    """Every withdrawal must be authorized before broadcast. Audit logs are required after approval."""
    if not authorized:
        raise PermissionError("authorization required")
    if balance <= 0:
        raise ValueError("balance required")
    if wallet.frozen:
        raise RuntimeError("wallet frozen")
    audit_log.emit("withdrawal_approved")
    return True
'''

    extractor = PythonASTExtractor()
    model = validate_ir(
        extractor.extract_ir_from_source(
            source,
            model_id='python-autoformalized-test-model',
            module_path='exchange/withdrawals.py',
        )
    )

    assert model.model_id == 'python-autoformalized-test-model'
    assert any(entity['name'] == 'Wallet' for entity in model.entities)
    assert any(policy['name'] == 'authorization_required' for policy in model.policies)
    assert any(policy['name'] == 'sufficient_balance_required' for policy in model.policies)
    assert any(policy['name'] == 'wallet_not_frozen_required' for policy in model.policies)
    assert any(policy['name'] == 'audit_required' for policy in model.policies)
    assert any(event['event'] == 'approve_withdrawal' for event in model.events)
    assert any(invariant['description'].startswith('Every withdrawal must be authorized') for invariant in model.invariants)
    assert model.metadata['autoformalization']['module_path'] == 'exchange/withdrawals.py'
    assert model.metadata['autoformalization']['source_digest']
    assert model.metadata['autoformalization']['review_status'] == 'heuristic'
    assert model.metadata['autoformalization']['evidence_refs']



def test_python_ast_extractor_aggregates_directory_inputs(tmp_path: Path) -> None:
    """GIVEN a Python codebase WHEN autoformalized from disk THEN module facts are aggregated into one IR."""

    first = tmp_path / 'withdrawals.py'
    first.write_text(
        '''
def approve_withdrawal(authorized):
    """Every withdrawal must be authorized before broadcast."""
    if not authorized:
        raise PermissionError("authorization required")
''',
        encoding='utf-8',
    )
    second = tmp_path / 'freeze.py'
    second.write_text(
        '''
class WalletGuardian:
    """Wallets cannot sign after freeze."""


def freeze_wallet(wallet):
    """Freeze actions must be authorized."""
    if not wallet.authorized:
        raise PermissionError("authorization required")
    return wallet
''',
        encoding='utf-8',
    )

    extractor = PythonASTExtractor()
    model = validate_ir(extractor.extract_ir_from_path(tmp_path, model_id='python-codebase-test-model'))

    assert model.model_id == 'python-codebase-test-model'
    assert any(entity['name'] == 'WalletGuardian' for entity in model.entities)
    assert any(event['event'] == 'approve_withdrawal' for event in model.events)
    assert any(invariant['description'].startswith('Wallets cannot sign after freeze') for invariant in model.invariants)
    assert sorted(model.metadata['autoformalization']['source_files']) == sorted([str(first), str(second)])
    assert sum(1 for policy in model.policies if policy['name'] == 'authorization_required') == 1
    authorization_policy = next(policy for policy in model.policies if policy['name'] == 'authorization_required')
    assert sorted(authorization_policy['sources']) == ['approve_withdrawal', 'freeze_wallet']
