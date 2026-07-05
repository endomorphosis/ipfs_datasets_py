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


SCENARIO_REGISTRY: dict[str, dict[str, object]] = {
    'unauthorized_withdrawal_policy_gap': {
        'expected_claims': ['no_unauthorized_withdrawal'],
        'mutator': _mutate_unauthorized_withdrawal,
    },
    'double_spend_reservation_gap': {
        'expected_claims': ['no_double_spend_internal_balance'],
        'mutator': _mutate_double_spend,
    },
    'deposit_before_finality_gap': {
        'expected_claims': ['no_deposit_before_finality'],
        'mutator': _mutate_deposit_before_finality,
    },
    'post_freeze_signing_gap': {
        'expected_claims': ['no_signing_request_after_wallet_freeze'],
        'mutator': _mutate_signing_after_freeze,
    },
    'delegation_authority_escalation': {
        'expected_claims': ['capability_delegation_no_authority_increase'],
        'mutator': _mutate_delegation_escalation,
    },
    'revocation_enforcement_gap': {
        'expected_claims': ['revoked_capability_no_future_authorization'],
        'mutator': _mutate_revocation_gap,
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
