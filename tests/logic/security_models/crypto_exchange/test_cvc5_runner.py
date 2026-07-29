import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import _normalize_provers, main
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.cvc5_runner import CVC5Runner


def test_cvc5_runner_returns_cli_proof_or_fail_closed_unknown_report() -> None:
    claim = default_claims()[0]
    report = CVC5Runner().run_claim(claim, example_minimal_exchange_model())

    assert report.prover == 'cvc5'
    if CVC5Runner.executable_path() is None:
        assert report.status == 'UNKNOWN'
        assert report.solver_result == 'unavailable'
        assert report.reason_unknown is not None
        assert 'cvc5 executable not found' in report.reason_unknown
    else:
        assert report.status == 'PROVED'
        assert report.solver_result == 'unsat'
    assert report.verify_report_cids()


def test_normalize_provers_accepts_registered_cvc5() -> None:
    assert _normalize_provers(['z3', 'cvc5']) == ['z3', 'cvc5']


def test_cvc5_only_cli_fails_unknown_critical(tmp_path: Path) -> None:
    if CVC5Runner.executable_path() is not None:
        pytest.skip('installed cvc5 now discharges the example claims')
    report_path = tmp_path / 'cvc5-reports.json'

    assert main([
        '--example',
        '--provers',
        'cvc5',
        '--fail-on',
        'unknown-critical',
        '--out',
        str(report_path),
    ]) == 1

    payload = json.loads(report_path.read_text(encoding='utf-8'))
    assert all(report['prover'] == 'cvc5' for report in payload['reports'])
    assert all(report['status'] == 'UNKNOWN' for report in payload['reports'])
    assert payload['coverage']['blocking_unknown'] > 0


def test_require_prover_agreement_fails_closed_for_cvc5(tmp_path: Path) -> None:
    pytest.importorskip('z3')
    if CVC5Runner.executable_path() is not None:
        pytest.skip('installed cvc5 now agrees with z3 for the example claims')
    report_path = tmp_path / 'agreement.json'

    assert main([
        '--example',
        '--provers',
        'z3,cvc5',
        '--require-prover-agreement',
        '--out',
        str(report_path),
    ]) == 1

    payload = json.loads(report_path.read_text(encoding='utf-8'))
    agreement = payload['prover_agreement']
    assert agreement['release_ready'] is False
    assert agreement['selected_provers'] == ['z3', 'cvc5']
    critical_claims = [claim for claim in agreement['claims'] if claim['critical']]
    assert critical_claims
    assert all(claim['statuses']['cvc5'] == 'UNKNOWN' for claim in critical_claims)
    assert any(claim['statuses']['z3'] == 'PROVED' for claim in critical_claims)
    assert all(claim['critical_failure'] is True for claim in critical_claims)
