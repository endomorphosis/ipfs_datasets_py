"""Example security models for the crypto exchange verifier."""

from __future__ import annotations

from .schema import DEFAULT_THREAT_MODEL_ASSUMPTIONS, SecurityModelIR


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
                'asset': 'asset:btc',
                'balance': 5,
                'reservation_requests': [2, 2],
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
                'delegator_authority': 3,
                'delegated_authority': 2,
                'revoked_before_action': False,
                'privileged_action_attempted': True,
            },
        ],
        policies=[
            {'id': 'policy:authorization_required', 'name': 'authorization_required', 'enabled': True},
            {'id': 'policy:fresh_nonce_required', 'name': 'fresh_nonce_required', 'enabled': True},
            {'id': 'policy:sufficient_balance_required', 'name': 'sufficient_balance_required', 'enabled': True},
            {'id': 'policy:wallet_not_frozen_required', 'name': 'wallet_not_frozen_required', 'enabled': True},
            {'id': 'policy:atomic_reservation', 'name': 'atomic_reservation', 'enabled': True},
            {'id': 'policy:delegation_monotonicity', 'name': 'delegation_monotonicity', 'enabled': True},
            {'id': 'policy:revocation_enforced', 'name': 'revocation_enforced', 'enabled': True},
            {'id': 'policy:credit_after_finality_required', 'name': 'credit_after_finality_required', 'enabled': True},
            {'id': 'policy:audit_required', 'name': 'audit_required', 'enabled': True},
        ],
        events=[
            {'event': 'withdrawal_requested', 'principal': 'principal:alice', 'wallet_id': 'wallet:user_alice', 'authorized': True, 'nonce_fresh': True, 'sufficient_balance': True},
            {'event': 'withdrawal_approved', 'principal': 'principal:exchange_signer'},
            {'event': 'withdrawal_broadcast', 'principal': 'principal:exchange_signer', 'authorized': True, 'critical': True},
            {'event': 'deposit_observed', 'txid': 'tx:1', 'confirmations': 0},
            {'event': 'deposit_finalized', 'txid': 'tx:1', 'confirmations': 6},
            {'event': 'deposit_credited', 'txid': 'tx:1', 'after_finality': True},
            {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice'},
            {'event': 'withdrawal_cancelled', 'wallet_id': 'wallet:user_alice'},
            {'event': 'capability_revoked', 'capability_id': 'cap:withdraw:user_alice'},
            {'event': 'audit_logged', 'transition': 'withdrawal_broadcast'},
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
            {'id': 'inv:no_unauthorized_withdrawal', 'description': 'Every broadcast withdrawal is authorized.'},
            {'id': 'inv:no_double_spend', 'description': 'Reservations never exceed available internal balance.'},
            {'id': 'inv:no_post_freeze_signing', 'description': 'Frozen wallets cannot sign future requests.'},
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
                {'event': 'withdrawal_requested', 'wallet_id': 'wallet:user_alice'},
                {'event': 'wallet_frozen', 'wallet_id': 'wallet:user_alice'},
                {'event': 'withdrawal_cancelled', 'wallet_id': 'wallet:user_alice'},
            ],
            'withdrawal_scenario': {
                'authorized': True,
                'broadcast': True,
                'nonce_fresh': True,
                'sufficient_balance': True,
                'wallet_not_frozen': True,
            },
        },
    )
