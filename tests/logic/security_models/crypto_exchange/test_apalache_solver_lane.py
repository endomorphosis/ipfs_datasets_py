from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_apalache_solver_lane.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/apalache-solver-lane-report.json'
TLA_MODEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla'
TLA_REPORT_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json'
DOC_PATH = ROOT / 'docs/security_verification/apalache_tla_solver_lane.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_apalache_solver_lane', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _fake_executable(directory: Path, name: str, output: str = 'apalache fixture') -> Path:
    executable = directory / name
    executable.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "{output}"\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_apalache_solver_lane_probe_blocks_when_solver_is_missing() -> None:
    module = _module()

    report = module.build_apalache_solver_lane_report(repo_root=ROOT)

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['task_id'] == 'PORTAL-CXTP-091'
    assert report['schema_version'] == 'crypto-exchange-apalache-solver-lane-report/v1'
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_APALACHE_SOLVER_LANE_UNAVAILABLE'
    assert 'APALACHE_EXECUTABLE_MISSING' in codes
    assert report['summary']['tla_model_present'] is True
    assert report['summary']['model_check_passed'] is False
    assert report['production_release_blocked_by_apalache_lane'] is True
    assert report['artifact_cid'].startswith('sha256:')


def test_apalache_solver_lane_can_report_ready_with_fake_checker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _fake_executable(bin_dir, 'apalache-mc', 'apalache version fixture')
    monkeypatch.setenv('PATH', bin_dir.as_posix())

    report = module.build_apalache_solver_lane_report(
        repo_root=ROOT,
        tla_model_path=TLA_MODEL_PATH,
        tla_report_path=TLA_REPORT_PATH,
        run_model_check=True,
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'APALACHE_SOLVER_LANE_READY'
    assert report['summary']['apalache_present'] is True
    assert report['summary']['model_check_run'] is True
    assert report['summary']['model_check_passed'] is True
    assert report['blockers'] == []


def test_apalache_solver_lane_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'apalache-solver-lane-report.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-091'
    assert payload['overall_status'] in {'ready', 'blocked_optional_lane'}


def test_persisted_apalache_solver_lane_report_is_fail_closed() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-091'
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_APALACHE_SOLVER_LANE_UNAVAILABLE'
    assert report['summary']['blocker_count'] >= 1
    assert report['summary']['tla_model_present'] is True
    assert report['model_check']['status'] == 'not-run'
    assert report['xaman_tla_report']['overall_status'] == 'blocked_optional_lane'


def test_apalache_solver_lane_documentation_includes_remediation_and_scope() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-091' in doc
    assert 'blocked_optional_lane' in doc
    assert 'SigningGateInvariant' in doc
    assert 'cs install apalache' in doc
    assert 'not a proof' in doc
