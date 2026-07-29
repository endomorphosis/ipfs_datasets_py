import importlib.util
import json
from pathlib import Path
import os
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'install_optional_theorem_solvers.py'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'optional_solver_installation.md'


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location('install_optional_theorem_solvers', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_executable(directory: Path, name: str, output: str) -> None:
    path = directory / name
    path.write_text(f'#!/usr/bin/env sh\necho "{output}"\n', encoding='utf-8')
    path.chmod(path.stat().st_mode | 0o111)


def test_optional_solver_installer_reports_all_expected_lanes_with_plan_only_mode(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env='')

    assert report['schema_version'] == 'optional-theorem-solver-install-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-086'
    assert report['installer_mode'] == 'plan_only'
    assert {lane['name'] for lane in report['lanes']} == {'apalache', 'tamarin', 'proverif', 'lean', 'coq'}
    assert report['proof_acceptance_blocked'] is False
    assert report['security_decision'] == 'OPTIONAL_SOLVER_LANES_EXPLICITLY_BLOCKED_OR_READY'
    assert all(lane['install_plan']['commands'] for lane in report['lanes'])


def test_optional_solver_installer_blocks_missing_optional_lanes(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env='')
    lanes = {lane['name']: lane for lane in report['lanes']}

    assert lanes['apalache']['status'] == 'blocked_optional_lane'
    assert lanes['tamarin']['proof_acceptance_policy'] == 'do_not_accept_reports_for_missing_solver_lane'
    assert report['overall_status'] == 'ready_with_blocked_optional_lanes'
    assert report['missing_or_degraded_lane_count'] == 5


def test_optional_solver_installer_marks_lean_ready_only_when_lean_and_lake_exist(tmp_path: Path) -> None:
    module = _load_module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _fake_executable(bin_dir, 'lean', 'Lean version 4.31.0')
    _fake_executable(bin_dir, 'lake', 'Lake version 5.0.0')

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env=str(bin_dir))
    lean = {lane['name']: lane for lane in report['lanes']}['lean']

    assert lean['status'] == 'ready'
    assert {item['name'] for item in lean['executables']} == {'lean', 'lake'}
    assert all(item['status'] == 'present' for item in lean['executables'])
    assert lean['proof_acceptance_policy'] == 'may_accept_reports_after_lane_specific_validation'


def test_optional_solver_installer_marks_lean_degraded_when_lake_missing(tmp_path: Path) -> None:
    module = _load_module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _fake_executable(bin_dir, 'lean', 'Lean version 4.31.0')

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env=str(bin_dir))
    lean = {lane['name']: lane for lane in report['lanes']}['lean']

    assert lean['status'] == 'degraded_optional_lane'
    assert lean['proof_acceptance_policy'] == 'do_not_accept_reports_until_all_required_tools_are_present'


def test_optional_solver_installer_cli_writes_report(tmp_path: Path) -> None:
    module = _load_module()
    out = tmp_path / 'optional-solver-install-report.json'

    rc = module.main(['--repo-root', str(REPO_ROOT), '--out', str(out)])

    assert rc == 0
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['schema_version'] == 'optional-theorem-solver-install-report/v1'
    assert report['lanes']


def test_optional_solver_installation_doc_covers_blocked_lanes_and_commands() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-086' in doc
    assert 'Apalache' in doc
    assert 'Tamarin' in doc
    assert 'ProVerif' in doc
    assert 'Lean' in doc
    assert 'Coq' in doc
    assert 'blocked_optional_lane' in doc
    assert 'plan_only' in doc
