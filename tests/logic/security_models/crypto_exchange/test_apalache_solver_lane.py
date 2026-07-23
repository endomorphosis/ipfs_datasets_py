"""Tests for PORTAL-CXTP-140 reconciled Apalache solver lane."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    APALACHE_SOLVER_LANE_REPORT_PATH,
    CHECKED_INVARIANTS,
    REQUIRED_APALACHE_VERSION,
    SCOPE_STATEMENT,
    TASK_ID,
    TLA_ARTIFACT_PATH,
    build_apalache_solver_lane_report,
)


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_apalache_solver_lane.py'
TLA_MODEL_PATH = ROOT / TLA_ARTIFACT_PATH
TLA_REPORT_PATH = ROOT / APALACHE_REPORT_PATH
REPORT_PATH = ROOT / APALACHE_SOLVER_LANE_REPORT_PATH
DOC_PATH = ROOT / 'docs/security_verification/apalache_tla_solver_lane.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_apalache_solver_lane', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def test_persisted_apalache_solver_lane_report_reuses_xaman_tla_evidence() -> None:
    lane = _json(REPORT_PATH)
    tla_report = _json(TLA_REPORT_PATH)
    tla_sha = tla_report['tla_model']['sha256']

    assert lane['task_id'] == TASK_ID
    assert lane['schema_version'] == 'crypto-exchange-apalache-solver-lane-report/v1'
    assert lane['depends_on'] == ['PORTAL-CXTP-071', 'PORTAL-CXTP-091']
    assert lane['scope']['statement'] == SCOPE_STATEMENT
    assert lane['tla_model']['path'] == TLA_ARTIFACT_PATH
    assert lane['tla_model']['sha256'] == tla_sha
    assert lane['tla_model']['generator_matches_checked_source'] is True
    assert lane['xaman_tla_report']['path'] == APALACHE_REPORT_PATH
    assert lane['xaman_tla_report']['reported_tla_sha256'] == tla_sha
    assert lane['xaman_tla_report']['source_matches_report'] is True
    assert lane['xaman_tla_report']['scope_statement'] == SCOPE_STATEMENT
    assert lane['artifact_cid'] == _cid_without(lane, 'artifact_cid')

    assert lane['selected_executable']['version'] == REQUIRED_APALACHE_VERSION
    assert lane['model_check']['version'] == REQUIRED_APALACHE_VERSION
    assert lane['model_check']['version_output'] == REQUIRED_APALACHE_VERSION
    assert lane['model_check']['checked_invariants'] == list(CHECKED_INVARIANTS)
    assert lane['model_check']['runs'] == tla_report['apalache']['runs']
    assert lane['summary']['model_check_passed'] is True
    assert lane['summary']['source_reconciled'] is True
    assert lane['summary']['report_source_bound'] is True
    assert lane['summary']['scope_statement'] == SCOPE_STATEMENT
    assert lane['overall_status'] == 'ready_bounded_model_only'
    assert lane['security_decision'] == 'APALACHE_0583_BOUNDED_MODEL_OUTPUT_BOUND'
    assert lane['blockers'] == []


def test_probe_builder_reports_ready_from_persisted_evidence() -> None:
    module = _module()

    report = module.build_apalache_solver_lane_report(
        repo_root=ROOT,
        tla_model_path=TLA_MODEL_PATH,
        tla_report_path=TLA_REPORT_PATH,
        run_model_check=False,
    )

    persisted = _json(REPORT_PATH)
    assert report['overall_status'] == persisted['overall_status']
    assert report['security_decision'] == persisted['security_decision']
    assert report['model_check']['runs'] == persisted['model_check']['runs']
    assert report['summary']['model_check_passed'] is True


def test_probe_cli_writes_reconciled_lane_report(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'apalache-solver-lane-report.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == TASK_ID
    assert payload['overall_status'] == 'ready_bounded_model_only'
    assert payload['security_decision'] == 'APALACHE_0583_BOUNDED_MODEL_OUTPUT_BOUND'


def test_lane_builder_blocks_when_checked_source_drifts_from_generator() -> None:
    tla_report = _json(TLA_REPORT_PATH)
    source = TLA_MODEL_PATH.read_text(encoding='utf-8')

    lane = build_apalache_solver_lane_report(
        repo_root=ROOT,
        tla_source=source + '\\* drift\\n',
        xaman_tla_report=tla_report,
        apalache_executable=tla_report['apalache']['executable'],
        apalache_version=tla_report['apalache']['version_output'],
        apalache_runs=tla_report['apalache']['runs'],
    )

    blocker_codes = {blocker['code'] for blocker in lane['blockers']}
    assert 'TLA_GENERATOR_SOURCE_MISMATCH' in blocker_codes
    assert 'XAMAN_TLA_REPORT_SOURCE_SHA_MISMATCH' in blocker_codes
    assert lane['overall_status'] == 'blocked_reconciliation'
    assert lane['security_decision'] == 'BLOCK_APALACHE_TLA_RECONCILIATION'
    assert lane['summary']['model_check_passed'] is False


def test_apalache_solver_lane_documentation_includes_evidence_and_scope() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert TLA_ARTIFACT_PATH in doc
    assert APALACHE_REPORT_PATH in doc
    assert REQUIRED_APALACHE_VERSION in doc
    assert SCOPE_STATEMENT in doc
    assert 'APALACHE_0583_BOUNDED_MODEL_OUTPUT_BOUND' in doc
    assert 'not a proof' in doc
