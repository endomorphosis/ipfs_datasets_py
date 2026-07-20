"""Tests for the conditional self-hosted resolver protocol lane."""

from __future__ import annotations

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_resolution_protocol import (
    REQUIRED_LEMMAS,
    XAMAN_SELF_HOSTED_RESOLUTION_PV,
    XAMAN_SELF_HOSTED_RESOLUTION_SPTHY,
    build_resolution_protocol_report,
)


def _pass_run() -> dict[str, object]:
    return {'status': 'pass', 'exit_code': 0, 'stdout': 'verified', 'stderr': ''}


def test_conditional_model_has_single_use_and_terminal_path_lemmas() -> None:
    for lemma in REQUIRED_LEMMAS:
        assert f'lemma {lemma}' in XAMAN_SELF_HOSTED_RESOLUTION_SPTHY
    assert 'linear Open state' in XAMAN_SELF_HOSTED_RESOLUTION_SPTHY
    assert 'cannot establish vendor single-use' in XAMAN_SELF_HOSTED_RESOLUTION_PV


def test_report_stays_production_blocked_when_conditional_model_passes() -> None:
    report = build_resolution_protocol_report(
        tamarin_executable='/tools/tamarin-prover',
        tamarin_run=_pass_run(),
        proverif_executable='/tools/proverif',
        proverif_run=_pass_run(),
    )

    assert report['overall_status'] == 'checked_conditional_self_hosted_model'
    assert report['production_release_blocked'] is True
    assert report['model_scope']['vendor_backend_modeled'] is False
    assert 'vendor_backend_single_use' in report['coverage']['not_proved']


def test_report_fails_closed_when_a_required_solver_is_not_run() -> None:
    report = build_resolution_protocol_report(
        tamarin_executable='/tools/tamarin-prover',
        tamarin_run=_pass_run(),
        proverif_executable='/tools/proverif',
        proverif_run=None,
    )

    assert report['overall_status'] == 'blocked_self_hosted_resolution_solver_lane'
    assert report['security_decision'] == 'BLOCK_SELF_HOSTED_RESOLUTION_MODEL'
