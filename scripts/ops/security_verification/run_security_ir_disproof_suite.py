#!/usr/bin/env python3
"""Exercise bounded disproof tactics against security IR models."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
from typing import Callable

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import (  # noqa: E402,E501
    default_claims,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import (  # noqa: E402,E501
    SourceCodeExtractor,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import (  # noqa: E402,E501
    example_minimal_exchange_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (  # noqa: E402,E501
    SecurityModelIR,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.z3_runner import (  # noqa: E402,E501
    Z3Runner,
)

Mutator = Callable[[SecurityModelIR], None]


def _safe_file_stem(value: str) -> str:
    return ''.join(
        char if char.isalnum() or char in {'-', '_'} else '-'
        for char in value
    ).strip('-') or 'counterexample'


def _load_model(
    *,
    example: bool,
    model_path: str | None,
    source_path: str | None,
    source_model_id: str | None,
) -> SecurityModelIR:
    if source_path:
        return validate_ir(
            SourceCodeExtractor().extract_ir_from_path(
                source_path,
                model_id=source_model_id,
            )
        )
    if example or not model_path:
        return example_minimal_exchange_model()
    payload = json.loads(Path(model_path).read_text(encoding='utf-8'))
    return validate_ir(SecurityModelIR.from_dict(payload))


def _set_policy(model: SecurityModelIR, name: str, enabled: bool) -> None:
    for policy in model.policies:
        if policy.get('name') == name:
            policy['enabled'] = enabled
            return
    model.policies.append(
        {
            'id': f'policy:{name}',
            'name': name,
            'enabled': enabled,
        }
    )


def _ensure_event(
    model: SecurityModelIR,
    event_name: str,
    **payload: object,
) -> dict[str, object]:
    for event in model.events:
        if event.get('event') == event_name:
            event.update(payload)
            return event
    event = {'event': event_name, **payload}
    model.events.append(event)
    return event


def _seed_disproof_model(
    base_model: SecurityModelIR,
    *,
    scenario_name: str,
) -> SecurityModelIR:
    seeded = deepcopy(base_model)
    default_model = example_minimal_exchange_model()
    for field_name in (
        'wallets',
        'accounts',
        'roles',
        'principals',
        'capabilities',
        'policies',
        'events',
        'state_machines',
        'assumptions',
        'prover_targets',
    ):
        if not getattr(seeded, field_name):
            setattr(
                seeded,
                field_name,
                deepcopy(getattr(default_model, field_name)),
            )
    if not seeded.metadata:
        seeded.metadata = deepcopy(default_model.metadata)
    else:
        seeded.metadata.setdefault(
            'runtime_trace',
            deepcopy(default_model.metadata.get('runtime_trace', [])),
        )
        seeded.metadata.setdefault(
            'withdrawal_scenario',
            deepcopy(default_model.metadata.get('withdrawal_scenario', {})),
        )
        seeded.metadata.setdefault(
            'proof_dependency_modes',
            deepcopy(default_model.metadata.get('proof_dependency_modes', {})),
        )
    seeded.model_id = f'{seeded.model_id}::{scenario_name}'
    return seeded


def _mutate_unauthorized_withdrawal(model: SecurityModelIR) -> None:
    _set_policy(model, 'authorization_required', False)
    _ensure_event(
        model,
        'withdrawal_broadcast',
        authorized=False,
        critical=True,
    )


def _mutate_double_spend(model: SecurityModelIR) -> None:
    _set_policy(model, 'atomic_reservation', False)
    model.accounts[0]['balance'] = 5
    model.accounts[0]['reservation_requests'] = [4, 4]


def _mutate_deposit_before_finality(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'deposit_observed',
        deposit_id='deposit:counterexample',
        txid='tx:counterexample',
        confirmations=0,
    )
    _ensure_event(
        model,
        'deposit_credited',
        deposit_id='deposit:counterexample',
        txid='tx:counterexample',
        confirmations=0,
        finality_threshold=6,
        after_finality=False,
    )


def _mutate_signing_after_freeze(model: SecurityModelIR) -> None:
    freeze_event = _ensure_event(
        model,
        'wallet_frozen',
        wallet_id='wallet:user_alice',
    )
    signing_event = {
        'event': 'signing_request',
        'wallet_id': freeze_event['wallet_id'],
    }
    model.events.append(signing_event)
    runtime_trace = list(model.metadata.get('runtime_trace', []))
    runtime_trace.append(
        {
            'event': 'wallet_frozen',
            'wallet_id': freeze_event['wallet_id'],
        }
    )
    runtime_trace.append(signing_event)
    model.metadata['runtime_trace'] = runtime_trace


def _mutate_delegation_escalation(model: SecurityModelIR) -> None:
    capability = model.capabilities[0]
    capability['delegator_authority'] = 1
    capability['delegated_authority'] = 3


def _mutate_revocation_gap(model: SecurityModelIR) -> None:
    capability = model.capabilities[0]
    capability['revoked_before_action'] = True
    capability['privileged_action_attempted'] = True
    _ensure_event(
        model,
        'capability_revoked',
        capability_id=capability['id'],
    )


def _mutate_missing_audit(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'withdrawal_broadcast',
        principal='principal:exchange_signer',
        critical=True,
    )
    model.events = [
        event for event in model.events if event.get('event') != 'audit_logged'
    ]


def _mutate_multi_asset_conservation_gap(model: SecurityModelIR) -> None:
    if not any(asset.get('id') == 'asset:eth' for asset in model.assets):
        model.assets.append({'id': 'asset:eth', 'symbol': 'ETH', 'decimals': 18})
    ledger_totals = model.metadata.setdefault('ledger_totals', {})
    for bucket_name in (
        'customer_liabilities',
        'custody_assets',
        'pending_settlements',
        'known_losses',
    ):
        ledger_totals.setdefault(bucket_name, {})
    ledger_totals['customer_liabilities']['asset:eth'] = 10
    ledger_totals['custody_assets']['asset:eth'] = 3
    ledger_totals['pending_settlements']['asset:eth'] = 0
    ledger_totals['known_losses']['asset:eth'] = 0


def _mutate_multi_chain_conservation_gap(model: SecurityModelIR) -> None:
    if not any(asset.get('id') == 'asset:usdc' for asset in model.assets):
        model.assets.append({'id': 'asset:usdc', 'symbol': 'USDC', 'decimals': 6})
    ledger_totals = model.metadata.setdefault('ledger_totals', {})
    for bucket_name in (
        'customer_liabilities',
        'custody_assets',
        'pending_settlements',
        'known_losses',
    ):
        ledger_totals.setdefault(bucket_name, {})
    ledger_totals['customer_liabilities']['asset:usdc'] = 1_000
    ledger_totals['custody_assets']['asset:usdc'] = 250
    ledger_totals['pending_settlements']['asset:usdc'] = 50
    ledger_totals['known_losses']['asset:usdc'] = 0
    model.metadata['chain_ledger_totals'] = {
        'chain:ethereum': {
            'asset:usdc': {
                'customer_liabilities': 500,
                'custody_assets': 250,
                'pending_settlements': 0,
                'known_losses': 0,
            },
        },
        'chain:polygon': {
            'asset:usdc': {
                'customer_liabilities': 500,
                'custody_assets': 0,
                'pending_settlements': 50,
                'known_losses': 0,
            },
        },
    }


def _mutate_reorg_after_deposit_credit(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'deposit_observed',
        deposit_id='deposit:reorged',
        txid='tx:reorged',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=0,
        timestamp=20,
    )
    _ensure_event(
        model,
        'deposit_finalized',
        deposit_id='deposit:reorged',
        txid='tx:reorged',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=6,
        finality_threshold=6,
        timestamp=21,
    )
    _ensure_event(
        model,
        'chain_reorg_detected',
        deposit_id='deposit:reorged',
        txid='tx:reorged',
        asset_id='asset:btc',
        chain_id='chain:btc',
        timestamp=22,
    )
    _ensure_event(
        model,
        'deposit_credited',
        deposit_id='deposit:reorged',
        txid='tx:reorged',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=6,
        finality_threshold=6,
        after_finality=True,
        timestamp=23,
    )


def _mutate_partial_rollback_deposit_gap(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'deposit_observed',
        deposit_id='deposit:partial-rollback',
        txid='tx:partial-rollback',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=3,
        timestamp=50,
    )
    _ensure_event(
        model,
        'deposit_credited',
        deposit_id='deposit:partial-rollback',
        txid='tx:partial-rollback',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=3,
        finality_threshold=6,
        after_finality=False,
        timestamp=51,
    )
    _ensure_event(
        model,
        'chain_reorg_detected',
        deposit_id='deposit:partial-rollback',
        txid='tx:partial-rollback',
        asset_id='asset:btc',
        chain_id='chain:btc',
        rollback_depth=2,
        timestamp=52,
    )
    _ensure_event(
        model,
        'deposit_finalized',
        deposit_id='deposit:partial-rollback',
        txid='tx:partial-rollback',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=6,
        finality_threshold=6,
        timestamp=53,
    )


def _mutate_nonce_reuse_without_reservation(model: SecurityModelIR) -> None:
    withdrawal_id = 'withdrawal:nonce-reuse'
    _ensure_event(
        model,
        'wallet_unfrozen',
        wallet_id='wallet:user_alice',
        timestamp=29,
    )
    _ensure_event(
        model,
        'withdrawal_requested',
        withdrawal_id=withdrawal_id,
        principal='principal:alice',
        wallet_id='wallet:user_alice',
        nonce='nonce:1',
        amount=1,
        asset_id='asset:btc',
        timestamp=30,
    )
    _ensure_event(
        model,
        'withdrawal_approved',
        withdrawal_id=withdrawal_id,
        principal='principal:exchange_signer',
        wallet_id='wallet:user_alice',
        nonce='nonce:1',
        amount=1,
        asset_id='asset:btc',
        timestamp=31,
    )
    _ensure_event(
        model,
        'balance_reserved',
        withdrawal_id=withdrawal_id,
        wallet_id='wallet:user_alice',
        amount=1,
        asset_id='asset:btc',
        timestamp=31.5,
    )
    _ensure_event(
        model,
        'withdrawal_broadcast',
        withdrawal_id=withdrawal_id,
        principal='principal:exchange_signer',
        wallet_id='wallet:user_alice',
        nonce='nonce:1',
        amount=1,
        asset_id='asset:btc',
        authorized=True,
        nonce_fresh=False,
        sufficient_balance=True,
        wallet_not_frozen=True,
        critical=True,
        timestamp=32,
    )


def _mutate_mempool_replacement_gap(model: SecurityModelIR) -> None:
    withdrawal_id = 'withdrawal:mempool-replacement'
    _ensure_event(
        model,
        'wallet_unfrozen',
        wallet_id='wallet:user_alice',
        timestamp=59,
    )
    _ensure_event(
        model,
        'withdrawal_requested',
        withdrawal_id=withdrawal_id,
        principal='principal:alice',
        wallet_id='wallet:user_alice',
        nonce='nonce:replacement',
        amount=1,
        asset_id='asset:btc',
        timestamp=60,
    )
    _ensure_event(
        model,
        'withdrawal_approved',
        withdrawal_id=withdrawal_id,
        principal='principal:exchange_signer',
        wallet_id='wallet:user_alice',
        nonce='nonce:replacement',
        amount=1,
        asset_id='asset:btc',
        timestamp=61,
    )
    _ensure_event(
        model,
        'nonce_reserved',
        withdrawal_id=withdrawal_id,
        nonce='nonce:replacement',
        timestamp=61.2,
    )
    _ensure_event(
        model,
        'balance_reserved',
        withdrawal_id=withdrawal_id,
        wallet_id='wallet:user_alice',
        amount=1,
        asset_id='asset:btc',
        timestamp=61.4,
    )
    _ensure_event(
        model,
        'withdrawal_broadcast',
        withdrawal_id=withdrawal_id,
        principal='principal:exchange_signer',
        wallet_id='wallet:user_alice',
        nonce='nonce:replacement',
        amount=3,
        asset_id='asset:btc',
        txid='tx:mempool-replacement:higher-amount',
        replacement_of='tx:mempool-replacement:approved',
        authorized=True,
        nonce_fresh=True,
        sufficient_balance=False,
        wallet_not_frozen=True,
        critical=True,
        timestamp=62,
    )


def _mutate_admin_quorum_delegation_gap(model: SecurityModelIR) -> None:
    model.capabilities.append(
        {
            'id': 'cap:admin:quorum-bypass',
            'principal': 'principal:exchange_signer',
            'resource_id': 'wallet:exchange_hot',
            'delegator_authority': 2,
            'delegated_authority': 2,
            'parent_actions': ['view_balance'],
            'delegated_actions': ['withdraw', 'freeze_wallet'],
            'parent_resources': ['wallet:exchange_hot'],
            'delegated_resources': ['wallet:exchange_hot'],
            'parent_expiry': 100,
            'expiry': 100,
            'allow_expiry_extension': False,
            'caveats_relax_authority': False,
            'revoked_before_action': False,
            'expired': False,
            'privileged_action_attempted': True,
        }
    )


def _mutate_stale_rpc_finality_gap(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'deposit_observed',
        deposit_id='deposit:stale-rpc',
        txid='tx:stale-rpc',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=1,
        timestamp=40,
    )
    _ensure_event(
        model,
        'deposit_finalized',
        deposit_id='deposit:stale-rpc',
        txid='tx:stale-rpc',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=1,
        finality_threshold=6,
        timestamp=41,
    )
    _ensure_event(
        model,
        'deposit_credited',
        deposit_id='deposit:stale-rpc',
        txid='tx:stale-rpc',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=1,
        finality_threshold=6,
        after_finality=True,
        rpc_observation='stale',
        timestamp=42,
    )


def _mutate_rpc_censorship_finality_gap(model: SecurityModelIR) -> None:
    _ensure_event(
        model,
        'deposit_observed',
        deposit_id='deposit:rpc-censored',
        txid='tx:rpc-censored',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=0,
        rpc_observation='censored',
        timestamp=70,
    )
    _ensure_event(
        model,
        'deposit_credited',
        deposit_id='deposit:rpc-censored',
        txid='tx:rpc-censored',
        asset_id='asset:btc',
        chain_id='chain:btc',
        account_id='account:alice_btc',
        confirmations=0,
        finality_threshold=6,
        after_finality=False,
        rpc_observation='censored',
        timestamp=71,
    )


SCENARIO_REGISTRY: dict[str, dict[str, object]] = {
    'admin_quorum_delegation_gap': {
        'expected_claims': ['capability_delegation_no_authority_increase'],
        'mutator': _mutate_admin_quorum_delegation_gap,
    },
    'unauthorized_withdrawal_policy_gap': {
        'expected_claims': ['no_unauthorized_withdrawal'],
        'mutator': _mutate_unauthorized_withdrawal,
    },
    'double_spend_reservation_gap': {
        'expected_claims': ['no_over_reserved_internal_account'],
        'mutator': _mutate_double_spend,
    },
    'deposit_before_finality_gap': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_deposit_before_finality,
    },
    'multi_asset_conservation_gap': {
        'expected_claims': ['global_asset_conservation'],
        'mutator': _mutate_multi_asset_conservation_gap,
    },
    'multi_chain_conservation_gap': {
        'expected_claims': ['global_asset_conservation'],
        'mutator': _mutate_multi_chain_conservation_gap,
    },
    'mempool_replacement_gap': {
        'expected_claims': ['no_unauthorized_withdrawal'],
        'mutator': _mutate_mempool_replacement_gap,
    },
    'nonce_reuse_without_reservation': {
        'expected_claims': ['no_unauthorized_withdrawal'],
        'mutator': _mutate_nonce_reuse_without_reservation,
    },
    'partial_rollback_deposit_gap': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_partial_rollback_deposit_gap,
    },
    'post_freeze_signing_gap': {
        'expected_claims': ['no_signing_request_after_wallet_freeze'],
        'mutator': _mutate_signing_after_freeze,
    },
    'reorg_after_deposit_credit': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_reorg_after_deposit_credit,
    },
    'delegation_authority_escalation': {
        'expected_claims': ['capability_delegation_no_authority_increase'],
        'mutator': _mutate_delegation_escalation,
    },
    'revocation_enforcement_gap': {
        'expected_claims': ['revoked_capability_no_future_authorization'],
        'mutator': _mutate_revocation_gap,
    },
    'stale_rpc_finality_gap': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_stale_rpc_finality_gap,
    },
    'rpc_censorship_finality_gap': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_rpc_censorship_finality_gap,
    },
    'missing_audit_transition': {
        'expected_claims': ['audit_event_exists_for_critical_transition'],
        'mutator': _mutate_missing_audit,
    },
}


def _render_scenario(
    *,
    base_model: SecurityModelIR,
    scenario_name: str,
    mutator_names: list[str],
    runner: Z3Runner,
) -> tuple[dict[str, object], bool]:
    scenario_model = _seed_disproof_model(
        base_model,
        scenario_name=scenario_name,
    )
    expected_claims: set[str] = set()
    for mutator_name in mutator_names:
        scenario = SCENARIO_REGISTRY[mutator_name]
        expected_claims.update(scenario['expected_claims'])
        mutator = scenario['mutator']
        assert callable(mutator)
        mutator(scenario_model)
    reports = [
        runner.run_claim(claim, scenario_model) for claim in default_claims()
    ]
    disproved_claims = sorted(
        report.claim_id for report in reports if report.status == 'DISPROVED'
    )
    matched_claims = sorted(expected_claims.intersection(disproved_claims))
    payload = {
        'name': scenario_name,
        'mutators': mutator_names,
        'model_id': scenario_model.model_id,
        'expected_claims': sorted(expected_claims),
        'disproved_claims': disproved_claims,
        'matched_claims': matched_claims,
        'reports': [report.to_dict() for report in reports],
    }
    return payload, matched_claims == sorted(expected_claims)


def _fuzzed_mutator_names(seed: int, rounds: int) -> list[list[str]]:
    rng = random.Random(seed)
    available = sorted(SCENARIO_REGISTRY)
    fuzzed: list[list[str]] = []
    for _ in range(rounds):
        if len(available) == 1:
            width = 1
        else:
            width = rng.randint(1, min(2, len(available)))
        fuzzed.append(sorted(rng.sample(available, k=width)))
    return fuzzed


def _counterexample_vectors(scenario: dict[str, object]) -> list[dict[str, object]]:
    vectors: list[dict[str, object]] = []
    reports = scenario.get('reports', [])
    if not isinstance(reports, list):
        return vectors
    for report in reports:
        if not isinstance(report, dict):
            continue
        if report.get('status') != 'DISPROVED':
            continue
        counterexample = report.get('counterexample')
        if not isinstance(counterexample, dict):
            continue
        vectors.append(
            {
                'schema_version': 'crypto-exchange-counterexample-vector/v1',
                'scenario': scenario.get('name', ''),
                'mutators': scenario.get('mutators', []),
                'model_id': scenario.get('model_id', ''),
                'expected_claims': scenario.get('expected_claims', []),
                'matched_claims': scenario.get('matched_claims', []),
                'claim_id': report.get('claim_id', ''),
                'status': report.get('status', ''),
                'risk': report.get('risk', ''),
                'solver_name': report.get('solver_name', ''),
                'solver_result': report.get('solver_result', ''),
                'proof_or_trace_cid': report.get('proof_or_trace_cid', ''),
                'counterexample': counterexample,
            }
        )
    return vectors


def _emit_counterexample_vectors(
    scenarios: list[dict[str, object]],
    target_dir: str,
) -> int:
    directory = Path(target_dir)
    directory.mkdir(parents=True, exist_ok=True)
    vector_count = 0
    for scenario in scenarios:
        scenario_name = str(scenario.get('name', 'scenario'))
        for vector in _counterexample_vectors(scenario):
            claim_id = str(vector.get('claim_id', 'claim'))
            output_path = directory / (
                f'{_safe_file_stem(scenario_name)}'
                f'--{_safe_file_stem(claim_id)}.json'
            )
            output_path.write_text(
                json.dumps(vector, indent=2, sort_keys=True) + '\n',
                encoding='utf-8',
            )
            vector_count += 1
    return vector_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--example',
        action='store_true',
        help='Use the built-in example model',
    )
    parser.add_argument(
        '--model',
        help='Path to a canonical security model JSON file',
    )
    parser.add_argument(
        '--source-path',
        help=(
            'Supported source file or directory to autoformalize before '
            'attack generation'
        ),
    )
    parser.add_argument(
        '--source-model-id',
        help='Optional model_id override when using --source-path',
    )
    parser.add_argument(
        '--out',
        help='Optional output path; stdout is used when omitted',
    )
    parser.add_argument(
        '--emit-counterexamples-dir',
        help='Directory to emit compact counterexample vectors as JSON files',
    )
    parser.add_argument(
        '--strategy',
        action='append',
        choices=sorted(SCENARIO_REGISTRY),
        help=(
            'Repeatable named disproof strategy; defaults to all registered '
            'strategies once'
        ),
    )
    parser.add_argument(
        '--fuzz-rounds',
        type=int,
        default=0,
        help='Add deterministic bounded mutation-fuzz rounds',
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=0,
        help='Seed for deterministic fuzzed mutation selection',
    )
    args = parser.parse_args(argv)
    selected_inputs = (
        args.example,
        args.model,
        args.source_path,
    )
    if sum(bool(value) for value in selected_inputs) > 1:
        parser.error(
            'choose only one input: --example, --model, or --source-path'
        )
    if args.fuzz_rounds < 0:
        parser.error('--fuzz-rounds must be non-negative')

    if not Z3Runner.is_available():
        print(
            'error: z3-solver is required for the disproof suite',
            file=sys.stderr,
        )
        return 2

    base_model = _load_model(
        example=args.example,
        model_path=args.model,
        source_path=args.source_path,
        source_model_id=args.source_model_id,
    )
    runner = Z3Runner()

    scenario_specs: list[tuple[str, list[str]]] = [
        (strategy_name, [strategy_name])
        for strategy_name in (args.strategy or sorted(SCENARIO_REGISTRY))
    ]
    for index, fuzzed_mutators in enumerate(
        _fuzzed_mutator_names(args.seed, args.fuzz_rounds)
    ):
        scenario_specs.append(
            (f'fuzz:{index}:{"+".join(fuzzed_mutators)}', fuzzed_mutators)
        )

    rendered_scenarios: list[dict[str, object]] = []
    success = True
    for scenario_name, mutator_names in scenario_specs:
        scenario_payload, scenario_ok = _render_scenario(
            base_model=base_model,
            scenario_name=scenario_name,
            mutator_names=mutator_names,
            runner=runner,
        )
        rendered_scenarios.append(scenario_payload)
        success = success and scenario_ok

    vector_count = 0
    if args.emit_counterexamples_dir:
        vector_count = _emit_counterexample_vectors(
            rendered_scenarios,
            args.emit_counterexamples_dir,
        )

    payload = {
        'model_id': base_model.model_id,
        'seed': args.seed,
        'scenarios': rendered_scenarios,
        'summary': {
            'scenario_count': len(rendered_scenarios),
            'scenario_failures': sum(
                1
                for item in rendered_scenarios
                if item['expected_claims'] != item['matched_claims']
            ),
            'total_disproved_claims': sum(
                len(item['disproved_claims']) for item in rendered_scenarios
            ),
            'counterexample_vector_count': vector_count,
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(rendered + '\n', encoding='utf-8')
    else:
        print(rendered)
    return 0 if success else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
