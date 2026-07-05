from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import SourceCodeExtractor
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir


def test_source_code_extractor_autoformalizes_typescript_into_security_ir() -> None:
    """GIVEN TypeScript security code WHEN autoformalized THEN a seed security IR is emitted."""

    source = '''
/** Wallets must never sign after they are frozen. */
export class WalletGuardian {}

/** Every withdrawal must be authorized before broadcast. Audit logs are required after approval. */
export function approveWithdrawal(authorized: boolean, balance: number, wallet: { frozen: boolean }, auditLog: { emit(event: string): void }): boolean {
  if (!authorized) {
    throw new Error("authorization required");
  }
  if (balance <= 0) {
    throw new Error("balance required");
  }
  if (wallet.frozen) {
    throw new Error("wallet frozen");
  }
  auditLog.emit("withdrawal_approved");
  return true;
}
'''

    extractor = SourceCodeExtractor()
    model = validate_ir(
        extractor.extract_ir_from_source(
            source,
            language='typescript',
            model_id='typescript-autoformalized-test-model',
            module_path='exchange/withdrawals.ts',
        )
    )

    assert model.model_id == 'typescript-autoformalized-test-model'
    assert any(entity['name'] == 'WalletGuardian' for entity in model.entities)
    assert any(policy['name'] == 'authorization_required' for policy in model.policies)
    assert any(policy['name'] == 'sufficient_balance_required' for policy in model.policies)
    assert any(policy['name'] == 'wallet_not_frozen_required' for policy in model.policies)
    assert any(policy['name'] == 'audit_required' for policy in model.policies)
    assert any(event['event'] == 'approveWithdrawal' for event in model.events)
    assert any(invariant['description'].startswith('Every withdrawal must be authorized') for invariant in model.invariants)
    assert model.metadata['autoformalization']['language'] == 'typescript'
    assert model.metadata['autoformalization']['module_path'] == 'exchange/withdrawals.ts'
    assert model.metadata['autoformalization']['source_digest']


def test_source_code_extractor_aggregates_popular_language_directory_inputs(tmp_path: Path) -> None:
    """GIVEN a mixed-language codebase WHEN autoformalized from disk THEN supported modules aggregate into one IR."""

    first = tmp_path / 'withdrawals.ts'
    first.write_text(
        '''
/** Every withdrawal must be authorized before broadcast. */
export function approveWithdrawal(authorized: boolean): boolean {
  if (!authorized) {
    throw new Error("authorization required");
  }
  return true;
}
''',
        encoding='utf-8',
    )
    second = tmp_path / 'freeze.go'
    second.write_text(
        '''
// Wallets cannot sign after freeze.
type WalletGuardian struct{}

// Freeze actions must be authorized.
func FreezeWallet(authorized bool) bool {
    if !authorized {
        panic("authorization required")
    }
    return true
}
''',
        encoding='utf-8',
    )

    extractor = SourceCodeExtractor()
    model = validate_ir(extractor.extract_ir_from_path(tmp_path, model_id='polyglot-codebase-test-model'))

    assert model.model_id == 'polyglot-codebase-test-model'
    assert any(entity['name'] == 'WalletGuardian' for entity in model.entities)
    assert any(event['event'] == 'approveWithdrawal' for event in model.events)
    assert any(event['event'] == 'FreezeWallet' for event in model.events)
    assert any(invariant['description'].startswith('Wallets cannot sign after freeze') for invariant in model.invariants)
    assert model.metadata['autoformalization']['languages'] == ['go', 'typescript']
    assert sorted(model.metadata['autoformalization']['source_files']) == sorted([str(first), str(second)])
    assert sum(1 for policy in model.policies if policy['name'] == 'authorization_required') == 1
    authorization_policy = next(policy for policy in model.policies if policy['name'] == 'authorization_required')
    assert sorted(authorization_policy['sources']) == ['FreezeWallet', 'approveWithdrawal']


@pytest.mark.parametrize(
    ('language', 'module_path', 'source', 'expected_event'),
    [
        (
            'javascript',
            'exchange/withdrawals.js',
            '''
/** Every withdrawal must be authorized before broadcast. */
export function approveWithdrawal(authorized) {
  if (!authorized) {
    throw new Error("authorization required");
  }
}
''',
            'approveWithdrawal',
        ),
        (
            'typescript',
            'exchange/withdrawals.ts',
            '''
/** Every withdrawal must be authorized before broadcast. */
export function approveWithdrawal(authorized: boolean): boolean {
  if (!authorized) {
    throw new Error("authorization required");
  }
  return true;
}
''',
            'approveWithdrawal',
        ),
        (
            'go',
            'exchange/withdrawals.go',
            '''
// Every withdrawal must be authorized before broadcast.
func ApproveWithdrawal(authorized bool) bool {
    if !authorized {
        panic("authorization required")
    }
    return true
}
''',
            'ApproveWithdrawal',
        ),
        (
            'java',
            'exchange/Withdrawals.java',
            '''
/** Every withdrawal must be authorized before broadcast. */
public class Withdrawals {
    public boolean approveWithdrawal(boolean authorized) {
        if (!authorized) {
            throw new IllegalStateException("authorization required");
        }
        return true;
    }
}
''',
            'approveWithdrawal',
        ),
        (
            'rust',
            'exchange/withdrawals.rs',
            '''
/// Every withdrawal must be authorized before broadcast.
pub fn approve_withdrawal(authorized: bool) -> bool {
    if !authorized {
        panic!("authorization required");
    }
    true
}
''',
            'approve_withdrawal',
        ),
    ],
)
def test_source_code_extractor_detects_authorization_policy_for_supported_languages(
    language: str,
    module_path: str,
    source: str,
    expected_event: str,
) -> None:
    """GIVEN a supported source language WHEN autoformalized THEN policy inference remains active."""

    extractor = SourceCodeExtractor()
    model = validate_ir(
        extractor.extract_ir_from_source(
            source,
            language=language,
            model_id=f'{language}-policy-test-model',
            module_path=module_path,
        )
    )

    authorization_policy = next(policy for policy in model.policies if policy['name'] == 'authorization_required')
    assert authorization_policy['sources'] == [expected_event]
    assert any(event['event'] == expected_event for event in model.events)
