"""Tests for source-bound native-vault state fuzzing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_state_fuzz import (
    CHECKS,
    REKEY_STATE_SMTLIB,
    SOURCE_MARKERS,
    build_native_vault_state_fuzz_report,
    run_bounded_state_fuzz_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json'
SMTLIB_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz.smt2'
DOC_PATH = REPO_ROOT / 'docs/security_verification/xaman_native_vault_state_fuzz.md'


def _fixture_source(root: Path) -> dict[str, object]:
    files = []
    for path, markers in SOURCE_MARKERS.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = ('\n'.join(markers) + '\n').encode('utf-8')
        target.write_bytes(raw)
        files.append({'path': path, 'sha256': hashlib.sha256(raw).hexdigest()})
    return {
        'source': {'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa'},
        'reproducibility': {'aggregate_sha256': 'fixture'},
        'files': files,
    }


def _passing_lane() -> dict[str, object]:
    expected = [result for _, result in CHECKS]
    return {name: {'status': 'pass', 'results': expected} for name in ('z3', 'cvc5')}


def test_campaign_exhaustively_covers_single_and_bounded_batch_fault_locations() -> None:
    cases = run_bounded_state_fuzz_campaign()

    assert len(cases) == 14
    assert all(case['all_data_recoverable'] for case in cases)
    assert {case['classification'] for case in cases} >= {
        'SUCCESS_CLEANUP_COMPLETE',
        'RECOVERY_ONLY_RUNTIME_OBLIGATION',
        'DUAL_OLD_NEW_ACCESS_RUNTIME_OBLIGATION',
    }
    assert sum(case['requires_runtime_fault_injection'] for case in cases) == 6
    by_id = {case['case_id']: case for case in cases}
    assert by_id['batch_rekey_two_vaults-05']['primary_state_counts'] == {
        'old_key': 1,
        'new_key': 1,
        'absent': 0,
    }
    assert by_id['batch_rekey_two_vaults-06']['primary_state_counts'] == {
        'old_key': 1,
        'new_key': 0,
        'absent': 1,
    }
    assert by_id['batch_rekey_two_vaults-06']['old_key_recovery_vault_count'] == 2


def test_report_binds_source_and_marks_cleanup_witness_as_runtime_obligation(tmp_path: Path) -> None:
    report = build_native_vault_state_fuzz_report(
        source_root=tmp_path,
        manifest=_fixture_source(tmp_path),
        assessment={
            'task_id': 'PORTAL-CXTP-162',
            'artifact_cid': 'bafkreievagwxl36mhedzpbbvo567xvnwaqm322uvtxgyopvhhtxwwjtg34',
            'scope': {'source_commit': '942f43876265a7af44f233288ad2b1d00841d5fa'},
        },
        solver_lane=_passing_lane(),
    )

    assert report['overall_status'] == 'checked_source_bounded_with_runtime_obligations'
    assert report['bounded_fuzz_campaign']['all_data_recoverable_in_model'] is True
    assert all(not condition['confirmed_vulnerability'] for condition in report['source_supported_conditions'])
    assert report['formal_state_model']['solvers']['z3']['results'] == [result for _, result in CHECKS]


def test_checked_in_report_is_content_addressed_and_does_not_claim_production() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))

    assert report['artifact_cid'] == calculate_artifact_cid({key: value for key, value in report.items() if key != 'artifact_cid'})
    assert report['scope']['vendor_release_equivalent'] is False
    assert report['scope']['production_security_result'] is False
    assert SMTLIB_PATH.read_text(encoding='utf-8') == REKEY_STATE_SMTLIB
    assert 'not a vulnerability' in DOC_PATH.read_text(encoding='utf-8').lower()
