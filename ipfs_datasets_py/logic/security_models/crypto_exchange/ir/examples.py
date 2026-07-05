"""Example security models for the crypto exchange verifier."""

from __future__ import annotations

from .schema import DEFAULT_THREAT_MODEL_ASSUMPTIONS, SecurityModelIR, make_evidence_ref



def _fixture_ref(line_start: int, line_end: int, notes: str) -> dict[str, object]:
    return make_evidence_ref(
        kind='test_fixture',
        path='ipfs_datasets_py/logic/security_models/crypto_exchange/ir/examples.py',
        line_start=line_start,
        line_end=line_end,
        review_status='trusted_fixture',
        notes=notes,
    )



def example_minimal_exchange_model() -> SecurityModelIR:
    """Return a minimal wallet/exchange model used by tests and the CLI."""

    return SecurityModelIR(
        schema_version='security-model-ir/v1',
        model_id='minimal-btc-exchange',
        entities=[
            {'id': 'entity:user_alice', 'kind': 'user', 'name': 'Alice'},
            {'id': 'entity:exchange', 'kind': 'exchange', 'name': 'Example Exchange'},
        ],
        assets=[
            {'id': 'asset:btc', 'symbol': 'BTC', 'decimals': 8},
        ],
        wallets=[
            {'id': 'wallet:user_alice', 'owner': 'principal:alice', 'asset': 'asset:btc', 'status': 'active'},
            {'id': 'wallet:exchange_hot', 'owner': 'principal:exchange_signer', 'asset': 'asset:btc', 'status': 'active'},
        ],
        accounts=[
            {
                'id': 'account:alice_btc',
                'owner': 'principal:alice',
                'wallet_id': 'wallet:user_alice',
                'asset_id': 'asset:btc',
                'balance': 5,
                'reservation_requests': [2, 2],
                'evidence_refs': [_fixture_ref(8, 129, 'Fixture account balance and reservations.')],
            },
        ],
        roles=[
            {'id': 'role:user', 'name': 'user'},
            {'id': 'role:signer', 'name': 'exchange_signer'},
            {'id': 'role:auditor', 'name': 'auditor'},
        ],
        principals=[
            {'id': 'principal:alice', 'role': 'role:user'},
            {'id': 'principal:exchange_signer', 'role': 'role:signer'},
            {'id': 'principal:auditor', 'role': 'role:auditor'},
        ],
        capabilities=[
            {
                'id': 'cap:withdraw:user_alice',
                'principal': 'principal:alice',
                'resource_id': 'wallet:user_alice',
                'delegator_authority': 3,
                'delegated_authority': 2,
                'parent_actions': ['withdraw', 'cancel'],
                'delegated_actions': ['withdraw'],
                'parent_resources': ['wallet:user_alice'],
                'delegated_resources': ['wallet:user_alice'],
                'parent_expiry': 100,
                'expiry': 90,
                'allow_expiry_extension': False,
                'caveats_relax_authority': False,
                'revoked_before_action': False,
                'expired': False,
                'privileged_action_attempted': False,
                'evidence_refs': [_fixture_ref(45, 54, 'Fixture capability chain.')],
            },
        ],
        policies=[
            {
                'id': 'policy:authorization_required',
                'name': 'authorization_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture authorization policy.')],
            },
            {
                'id': 'policy:fresh_nonce_required',
                'name': 'fresh_nonce_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture nonce freshness policy.')],
            },
            {
                'id': 'policy:sufficient_balance_required',
                'name': 'sufficient_balance_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture balance policy.')],
            },
            {
                'id': 'policy:wallet_not_frozen_required',
                'name': 'wallet_not_frozen_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture wallet freeze policy.')],
            },
            {
                'id': 'policy:atomic_reservation',
                'name': 'atomic_reservation',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture atomic reservation policy.')],
            },
            {
                'id': 'policy:delegation_monotonicity',
                'name': 'delegation_monotonicity',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture delegation monotonicity policy.')],
            },
            {
                'id': 'policy:revocation_enforced',
                'name': 'revocation_enforced',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture capability revocation policy.')],
            },
            {
                'id': 'policy:credit_after_finality_required',
                'name': 'credit_after_finality_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture deposit finality policy.')],
            },
            {
                'id': 'policy:audit_required',
                'name': 'audit_required',
                'enabled': True,
                'evidence_refs': [_fixture_ref(55, 65, 'Fixture audit policy.')],
            },
        ],
        events=[
            {
                'id': 'event:withdrawal_requested:1',
                'event': 'withdrawal_requested',
                'withdrawal_id': 'withdrawal:1',
                'principal': 'principal:alice',
                'wallet_id': 'wallet:user_alice',
                'authorized': True,
                'nonce_fresh': True,
                'sufficient_balance': True,
                'wallet_not_frozen': True,
                'timestamp': 1,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture withdrawal request trace.')],
            },
            {
                'id': 'event:withdrawal_approved:1',
                'event': 'withdrawal_approved',
                'withdrawal_id': 'withdrawal:1',
                'principal': 'principal:exchange_signer',
                'wallet_id': 'wallet:user_alice',
                'timestamp': 2,
                'max_seconds': 30,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture withdrawal approval trace.')],
            },
            {
                'id': 'event:withdrawal_broadcast:1',
                'event': 'withdrawal_broadcast',
                'withdrawal_id': 'withdrawal:1',
                'principal': 'principal:exchange_signer',
                'wallet_id': 'wallet:user_alice',
                'authorized': True,
                'nonce_fresh': True,
                'sufficient_balance': True,
                'wallet_not_frozen': True,
                'critical': True,
                'timestamp': 3,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture withdrawal broadcast trace.')],
            },
            {
                'id': 'event:deposit_observed:1',
                'event': 'deposit_observed',
                'deposit_id': 'deposit:1',
                'txid': 'tx:1',
                'confirmations': 0,
                'timestamp': 4,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture deposit observed trace.')],
            },
            {
                'id': 'event:deposit_finalized:1',
                'event': 'deposit_finalized',
                'deposit_id': 'deposit:1',
                'txid': 'tx:1',
                'confirmations': 6,
                'finality_threshold': 6,
                'timestamp': 5,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture deposit finalized trace.')],
            },
            {
                'id': 'event:deposit_credited:1',
                'event': 'deposit_credited',
                'deposit_id': 'deposit:1',
                'txid': 'tx:1',
                'confirmations': 6,
                'finality_threshold': 6,
                'after_finality': True,
                'timestamp': 6,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture deposit credited trace.')],
            },
            {
                'id': 'event:wallet_frozen:1',
                'event': 'wallet_frozen',
                'wallet_id': 'wallet:user_alice',
                'timestamp': 7,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture wallet freeze trace.')],
            },
            {
                'id': 'event:withdrawal_cancelled:1',
                'event': 'withdrawal_cancelled',
                'withdrawal_id': 'withdrawal:1',
                'wallet_id': 'wallet:user_alice',
                'timestamp': 8,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture withdrawal cancellation trace.')],
            },
            {
                'id': 'event:capability_revoked:1',
                'event': 'capability_revoked',
                'capability_id': 'cap:withdraw:user_alice',
                'timestamp': 9,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture capability revocation trace.')],
            },
            {
                'id': 'event:audit_logged:1',
                'event': 'audit_logged',
                'transition': 'withdrawal_broadcast',
                'timestamp': 10,
                'evidence_refs': [_fixture_ref(66, 77, 'Fixture audit trail trace.')],
            },
        ],
        state_machines=[
            {
                'id': 'sm:withdrawal',
                'states': ['requested', 'approved', 'broadcast', 'cancelled'],
                'current': 'broadcast',
                'nonce': 'nonce:1',
            },
            {
                'id': 'sm:deposit',
                'states': ['observed', 'finalized', 'credited'],
                'current': 'credited',
                'finality_threshold': 6,
            },
        ],
        invariants=[
            {
                'id': 'inv:no_unauthorized_withdrawal',
                'description': 'Every broadcast withdrawal is authorized.',
                'evidence_refs': [_fixture_ref(92, 96, 'Fixture withdrawal invariant.')],
            },
            {
                'id': 'inv:no_double_spend',
                'description': 'Reservations never exceed available internal balance.',
                'evidence_refs': [_fixture_ref(92, 96, 'Fixture reservation invariant.')],
            },
            {
                'id': 'inv:no_post_freeze_signing',
                'description': 'Frozen wallets cannot sign future requests.',
                'evidence_refs': [_fixture_ref(92, 96, 'Fixture freeze invariant.')],
            },
        ],
        assumptions=list(DEFAULT_THREAT_MODEL_ASSUMPTIONS),
        prover_targets=['z3'],
        metadata={
            'proof_dependency_modes': {
                'flogic': 'not-used',
                'zkp': 'not-used',
            },
            'threat_model': [
                {'id': 'T1', 'name': 'stolen_api_token'},
                {'id': 'T2', 'name': 'compromised_exchange_employee'},
                {'id': 'T3', 'name': 'replayed_withdrawal_request'},
                {'id': 'T4', 'name': 'stale_blockchain_rpc_data'},
                {'id': 'T5', 'name': 'chain_reorg_after_deposit_credit'},
                {'id': 'T6', 'name': 'race_condition_between_withdrawals'},
                {'id': 'T7', 'name': 'hot_wallet_key_compromise'},
                {'id': 'T8', 'name': 'malicious_dependency_or_build_artifact'},
                {'id': 'T9', 'name': 'prompt_injection_against_policy_compiler'},
                {'id': 'T10', 'name': 'simulated_proof_mode_used_in_production'},
            ],
            'runtime_trace': [
                {'event': 'withdrawal_requested', 'withdrawal_id': 'withdrawal:1', 'wallet_id': 'wallet:user_alice'},
                {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice'},
                {'event': 'withdrawal_cancelled', 'withdrawal_id': 'withdrawal:1', 'wallet_id': 'wallet:user_alice'},
            ],
            'ledger_totals': {
                'customer_liabilities': {'asset:btc': 5},
                'custody_assets': {'asset:btc': 5},
                'pending_settlements': {'asset:btc': 0},
                'known_losses': {'asset:btc': 0},
            },
        },
    )
