from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Callable

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.capability import (
    CapabilityDelegationMonotonicityClaim,
    RevokedCapabilityClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.deposit import (
    NoDepositCreditedBeforeFinalityClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.hsm import (
    NoSigningAfterWalletFreezeClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.ledger import (
    AuditEventExistsForCriticalTransitionClaim,
    GlobalAssetConservationClaim,
    NoOverReservedInternalAccountClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.withdrawal import (
    NoUnauthorizedWithdrawalClaim,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.compilers.to_smtlib import (
    SMTLIB_SCHEMA_VERSION,
    compile_claim_to_smtlib,
    emit_smtlib_artifacts,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_model_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import (
    example_minimal_exchange_model,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR


z3 = pytest.importorskip('z3')


ModelMutator = Callable[[SecurityModelIR], None]


def _solver_result(smtlib: str) -> str:
    solver = z3.Solver()
    solver.from_string(smtlib)
    return str(solver.check())


def _metadata_from_smtlib(smtlib: str) -> dict[str, object]:
    for line in smtlib.splitlines():
        if line.startswith('; cxtp.metadata: '):
            return json.loads(line.removeprefix('; cxtp.metadata: '))
    raise AssertionError('missing cxtp.metadata comment')


def _remove_withdrawal_approval(model: SecurityModelIR) -> None:
    model.events = [event for event in model.events if event.get('event') != 'withdrawal_approved']


def _over_reserve_account(model: SecurityModelIR) -> None:
    model.accounts[0]['reservation_requests'] = [4, 4]


def _break_global_conservation(model: SecurityModelIR) -> None:
    model.metadata['ledger_totals']['customer_liabilities']['asset:btc'] = 6


def _remove_deposit_finality(model: SecurityModelIR) -> None:
    model.events = [event for event in model.events if event.get('event') != 'deposit_finalized']


def _sign_after_freeze(model: SecurityModelIR) -> None:
    model.events.append(
        {
            'id': 'event:signing_request:after_freeze',
            'event': 'signing_request',
            'wallet_id': 'wallet:user_alice',
            'txid': 'tx:after-freeze',
            'approved_tx_bytes': '0xbeef',
            'timestamp': 11,
        }
    )


def _escalate_delegated_authority(model: SecurityModelIR) -> None:
    model.capabilities[0]['delegated_authority'] = 4


def _use_revoked_capability(model: SecurityModelIR) -> None:
    model.events.append(
        {
            'id': 'event:privileged_action:after_revoke',
            'event': 'privileged_action',
            'capability_id': 'cap:withdraw:user_alice',
            'timestamp': 11,
        }
    )


def _remove_audit_log(model: SecurityModelIR) -> None:
    model.events = [event for event in model.events if event.get('event') != 'audit_logged']


COUNTEREXAMPLE_FIXTURES: tuple[tuple[str, object, ModelMutator], ...] = (
    ('authorization', NoUnauthorizedWithdrawalClaim(), _remove_withdrawal_approval),
    ('ledger reservation', NoOverReservedInternalAccountClaim(), _over_reserve_account),
    ('global conservation', GlobalAssetConservationClaim(), _break_global_conservation),
    ('finality', NoDepositCreditedBeforeFinalityClaim(), _remove_deposit_finality),
    ('signing freeze', NoSigningAfterWalletFreezeClaim(), _sign_after_freeze),
    ('delegation', CapabilityDelegationMonotonicityClaim(), _escalate_delegated_authority),
    ('revocation', RevokedCapabilityClaim(), _use_revoked_capability),
    ('audit', AuditEventExistsForCriticalTransitionClaim(), _remove_audit_log),
)


def test_default_claims_serialize_to_deterministic_smtlib_unsat_violation_queries() -> None:
    model = example_minimal_exchange_model()
    model_cid = calculate_model_cid(model)

    for claim in default_claims():
        first = compile_claim_to_smtlib(claim, model)
        second = compile_claim_to_smtlib(claim, model)
        metadata = _metadata_from_smtlib(first.smtlib)

        assert first.smtlib == second.smtlib
        assert first.modeled is True
        assert first.model_cid == model_cid
        assert first.claim_id == claim.claim_id
        assert metadata['schema_version'] == SMTLIB_SCHEMA_VERSION
        assert metadata['query_kind'] == 'violation_satisfiability'
        assert metadata['model_cid'] == model_cid
        assert metadata['claim_id'] == claim.claim_id
        assert metadata['claim_version'] == claim.claim_version
        assert metadata['severity'] == claim.severity
        assert metadata['required_assumptions'] == claim.required_assumptions
        assert metadata['modeled'] is True
        assert metadata['assertion_count'] == len(claim.compile_to_z3(model).assertions)
        assert '(check-sat)' in first.smtlib
        assert _solver_result(first.smtlib) == 'unsat'


@pytest.mark.parametrize(('category', 'claim', 'mutator'), COUNTEREXAMPLE_FIXTURES)
def test_counterexample_fixtures_serialize_to_sat_violation_queries(
    category: str,
    claim: object,
    mutator: ModelMutator,
) -> None:
    model = deepcopy(example_minimal_exchange_model())
    mutator(model)

    artifact = compile_claim_to_smtlib(claim, model)
    metadata = _metadata_from_smtlib(artifact.smtlib)

    assert category
    assert artifact.modeled is True
    assert metadata['claim_id'] == artifact.claim_id
    compiler_artifact = metadata['compiler_artifact']
    violation_scope = (
        compiler_artifact.get('violations')
        or compiler_artifact.get('missing_audit')
        or compiler_artifact.get('violating_event_ids')
        or compiler_artifact.get('overdrawn_accounts')
    )
    assert violation_scope
    assert _solver_result(artifact.smtlib) == 'sat'


def test_not_modeled_claim_serializes_without_check_sat() -> None:
    model = deepcopy(example_minimal_exchange_model())
    model.events = []
    artifact = compile_claim_to_smtlib(NoUnauthorizedWithdrawalClaim(), model)
    metadata = _metadata_from_smtlib(artifact.smtlib)

    assert artifact.modeled is False
    assert artifact.not_modeled_reason == 'withdrawal broadcast events are not modeled'
    assert metadata['modeled'] is False
    assert metadata['not_modeled_reason'] == artifact.not_modeled_reason
    assert 'NOT_MODELED: withdrawal broadcast events are not modeled' in artifact.smtlib
    assert '(check-sat)' not in artifact.smtlib


def test_emit_smtlib_artifacts_writes_manifest_and_claim_files(tmp_path: Path) -> None:
    model = example_minimal_exchange_model()
    claims = default_claims()
    manifest = emit_smtlib_artifacts(model, tmp_path, claims)

    assert manifest['schema_version'] == SMTLIB_SCHEMA_VERSION
    assert manifest['model_cid'] == calculate_model_cid(model)
    assert manifest['artifact_count'] == len(claims)
    manifest_path = tmp_path / 'manifest.json'
    assert json.loads(manifest_path.read_text(encoding='utf-8')) == manifest

    paths = [tmp_path / entry['path'] for entry in manifest['artifacts']]
    assert all(path.exists() for path in paths)
    assert {path.suffix for path in paths} == {'.smt2'}
    for path in paths:
        smtlib = path.read_text(encoding='utf-8')
        assert '; cxtp.model_cid: ' in smtlib
        assert '; cxtp.claim_id: ' in smtlib
        assert _solver_result(smtlib) == 'unsat'
