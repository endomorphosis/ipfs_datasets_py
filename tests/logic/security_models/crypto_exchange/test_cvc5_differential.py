from __future__ import annotations

import json
import stat
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.claims import default_claims
from ipfs_datasets_py.logic.security_models.crypto_exchange.claims.withdrawal import NoUnauthorizedWithdrawalClaim
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model
from ipfs_datasets_py.logic.security_models.crypto_exchange.prove_all import compare_prover_reports, main
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.cvc5_runner import CVC5Runner


def _fake_cvc5(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / 'cvc5'
    executable.write_text(
        '#!/usr/bin/env python3\n'
        'import sys\n'
        f'{body}\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_cvc5_runner_maps_unsat_violation_query_to_proved(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        "print('fake cvc5 1.0' if '--version' in sys.argv else 'unsat')",
    )

    report = CVC5Runner(executable=executable).run_claim(
        NoUnauthorizedWithdrawalClaim(),
        example_minimal_exchange_model(),
    )

    assert report.prover == 'cvc5'
    assert report.status == 'PROVED'
    assert report.solver_result == 'unsat'
    assert report.compiler_cid
    assert report.assertion_count is not None and report.assertion_count > 0
    assert report.verify_report_cids()


def test_cvc5_runner_maps_sat_violation_query_to_disproved(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        "print('fake cvc5 1.0' if '--version' in sys.argv else 'sat')",
    )
    model = deepcopy(example_minimal_exchange_model())
    model.events = [event for event in model.events if event.get('event') != 'withdrawal_approved']

    report = CVC5Runner(executable=executable).run_claim(NoUnauthorizedWithdrawalClaim(), model)

    assert report.status == 'DISPROVED'
    assert report.solver_result == 'sat'
    assert report.counterexample is not None
    assert report.counterexample['compiler_artifact']['violations']
    assert report.proof_or_trace_cid
    assert report.verify_report_cids()


def test_cvc5_runner_fails_closed_when_executable_is_missing(tmp_path: Path) -> None:
    missing = tmp_path / 'missing-cvc5'

    report = CVC5Runner(executable=missing).run_claim(
        NoUnauthorizedWithdrawalClaim(),
        example_minimal_exchange_model(),
    )

    assert report.status == 'UNKNOWN'
    assert report.solver_result == 'unavailable'
    assert report.reason_unknown is not None
    assert '/home/barberb/.local/bin/cvc5' in report.reason_unknown
    assert report.counterexample is not None
    assert report.counterexample['smtlib_artifact_cid'] == report.compiler_cid


def test_cvc5_runner_fails_closed_on_parser_error(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        (
            "if '--version' in sys.argv:\n"
            "    print('fake cvc5 1.0')\n"
            "else:\n"
            "    print('Parse Error: bad SMT-LIB', file=sys.stderr)\n"
            "    raise SystemExit(1)"
        ),
    )

    report = CVC5Runner(executable=executable).run_claim(
        NoUnauthorizedWithdrawalClaim(),
        example_minimal_exchange_model(),
    )

    assert report.status == 'UNKNOWN'
    assert report.solver_result == 'parser_error'
    assert report.reason_unknown is not None
    assert 'exited with code 1' in report.reason_unknown


def test_cvc5_runner_fails_closed_on_unsupported_theory(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        (
            "if '--version' in sys.argv:\n"
            "    print('fake cvc5 1.0')\n"
            "else:\n"
            "    print('unsupported theory combination', file=sys.stderr)\n"
            "    raise SystemExit(1)"
        ),
    )

    report = CVC5Runner(executable=executable).run_claim(
        NoUnauthorizedWithdrawalClaim(),
        example_minimal_exchange_model(),
    )

    assert report.status == 'UNKNOWN'
    assert report.solver_result == 'unsupported'
    assert report.counterexample is not None
    assert 'unsupported theory combination' in report.counterexample['cvc5_stderr']


def test_cvc5_runner_fails_closed_on_timeout(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        (
            "if '--version' in sys.argv:\n"
            "    print('fake cvc5 1.0')\n"
            "else:\n"
            "    import time\n"
            "    time.sleep(1)"
        ),
    )

    report = CVC5Runner(timeout_ms=10, executable=executable).run_claim(
        NoUnauthorizedWithdrawalClaim(),
        example_minimal_exchange_model(),
    )

    assert report.status == 'UNKNOWN'
    assert report.solver_result == 'timeout'
    assert report.reason_unknown == 'cvc5 timed out after 10 ms'


def test_cvc5_preserves_not_modeled_semantics(tmp_path: Path) -> None:
    executable = _fake_cvc5(
        tmp_path,
        "raise AssertionError('not-modeled claims must not invoke cvc5')",
    )
    model = deepcopy(example_minimal_exchange_model())
    model.events = []

    report = CVC5Runner(executable=executable).run_claim(NoUnauthorizedWithdrawalClaim(), model)

    assert report.status == 'NOT_MODELED'
    assert report.solver_result == 'not-modeled'
    assert report.reason_unknown == 'withdrawal broadcast events are not modeled'


def test_real_cvc5_agrees_with_z3_for_current_example_claims() -> None:
    pytest.importorskip('z3')
    if CVC5Runner.executable_path() is None:
        pytest.skip('cvc5 CLI is not installed')

    agreement = compare_prover_reports(example_minimal_exchange_model(), ['z3', 'cvc5'])

    assert agreement['release_ready'] is True
    assert agreement['critical_failures'] == 0
    assert agreement['selected_provers'] == ['z3', 'cvc5']
    assert len(agreement['claims']) == len(default_claims())
    assert all(claim['statuses']['z3'] == claim['statuses']['cvc5'] for claim in agreement['claims'])
    assert {claim['statuses']['cvc5'] for claim in agreement['claims']} == {'PROVED'}


def test_cli_require_prover_agreement_emits_successful_differential_report(tmp_path: Path) -> None:
    pytest.importorskip('z3')
    if CVC5Runner.executable_path() is None:
        pytest.skip('cvc5 CLI is not installed')
    report_path = tmp_path / 'cvc5-differential.json'

    exit_code = main([
        '--example',
        '--provers',
        'z3,cvc5',
        '--require-prover-agreement',
        '--out',
        str(report_path),
    ])

    assert exit_code == 0
    payload = json.loads(report_path.read_text(encoding='utf-8'))
    agreement = payload['prover_agreement']
    assert agreement['release_ready'] is True
    assert agreement['critical_failures'] == 0
    assert all(claim['statuses']['cvc5'] == 'PROVED' for claim in agreement['claims'])
    assert all(
        report['solver_result'] == 'unsat'
        for claim in agreement['claims']
        for report in claim['reports']
        if report['prover'] == 'cvc5'
    )
