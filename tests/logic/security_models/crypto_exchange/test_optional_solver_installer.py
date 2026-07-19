import importlib.util
import json
from pathlib import Path
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

    assert report['schema_version'] == 'optional-theorem-solver-install-report/v2'
    assert report['task_id'] == 'PORTAL-CXTP-086'
    assert report['installer_mode'] == 'plan_only'
    assert {lane['name'] for lane in report['lanes']} == {
        'z3', 'cvc5', 'apalache', 'maude', 'tamarin', 'proverif', 'lean', 'rocq', 'symbolicai', 'ergoai',
        'leanstral',
    }
    assert report['proof_acceptance_blocked'] is False
    assert report['security_decision'] == 'OPTIONAL_SOLVER_LANES_EXPLICITLY_BLOCKED_OR_READY'
    installable = [lane for lane in report['lanes'] if lane['name'] != 'leanstral']
    advisory = {lane['name']: lane for lane in report['lanes']}['leanstral']
    assert all(lane['install_plan']['commands'] for lane in installable)
    assert advisory['install_plan']['commands'] == []
    assert advisory['install_plan']['mode'] == 'advisory'
    assert advisory['advisory_lane']['proof_authority'] is False


def test_optional_solver_installer_blocks_missing_optional_lanes(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env='')
    lanes = {lane['name']: lane for lane in report['lanes']}

    assert lanes['apalache']['status'] == 'blocked_optional_lane'
    assert lanes['tamarin']['proof_acceptance_policy'] == 'do_not_accept_reports_for_missing_solver_lane'
    assert lanes['leanstral']['status'] == 'degraded_optional_lane'
    assert report['overall_status'] == 'ready_with_blocked_optional_lanes'
    # Z3 and SymbolicAI are Python-only lanes in this test environment; the
    # remaining executable/advisory lanes must still be explicit gaps when
    # PATH and Leanstral configuration are empty.
    expected_missing = sum(1 for lane in report['lanes'] if lane['status'] != 'ready')
    assert report['missing_or_degraded_lane_count'] == expected_missing


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


def test_optional_solver_installer_marks_leanstral_ready_only_with_verified_lean_kernel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    report_path = tmp_path / 'security_ir_artifacts' / 'environment' / 'lean-solver-lane-report.json'
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                'overall_status': 'ready',
                'summary': {'lean_present': True, 'lake_present': True},
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setenv('IPFS_DATASETS_PY_LEANSTRAL_MODEL', 'labs-leanstral-2603')

    report = module.build_report(repo_root=tmp_path, solver_probe_path=tmp_path / 'missing.json', path_env='')
    leanstral = {lane['name']: lane for lane in report['lanes']}['leanstral']

    assert leanstral['status'] == 'ready'
    assert leanstral['proof_acceptance_policy'] == 'may_accept_reports_after_lane_specific_validation'
    assert leanstral['advisory_lane']['proof_authority'] is False
    assert leanstral['advisory_lane']['lean_kernel_ready'] is True


def test_optional_solver_installer_cli_writes_report(tmp_path: Path) -> None:
    module = _load_module()
    out = tmp_path / 'optional-solver-install-report.json'

    rc = module.main(['--repo-root', str(REPO_ROOT), '--out', str(out)])

    assert rc == 0
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['schema_version'] == 'optional-theorem-solver-install-report/v2'
    assert report['lanes']


def test_optional_solver_installer_runs_selected_managed_install_with_visible_events(tmp_path: Path) -> None:
    module = _load_module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()

    class FakeInstaller:
        @staticmethod
        def managed_solver_version_status() -> list[dict[str, object]]:
            return []

        @staticmethod
        def ensure_tamarin(**kwargs: object) -> bool:
            progress = kwargs['on_progress']
            assert callable(progress)
            progress('installing', 'downloading pinned Tamarin and Maude releases')
            _fake_executable(bin_dir, 'tamarin-prover', 'tamarin-prover 1.12.0')
            progress('installed', 'Tamarin runtime validation passed')
            return True

    report = module.build_report(
        repo_root=tmp_path,
        solver_probe_path=tmp_path / 'missing.json',
        path_env=str(bin_dir),
        install=True,
        selected_solvers=['tamarin'],
        installer=FakeInstaller(),
    )
    tamarin = {lane['name']: lane for lane in report['lanes']}['tamarin']

    assert report['installer_mode'] == 'install'
    assert report['install_failure_count'] == 0
    assert tamarin['status'] == 'ready'
    assert tamarin['installation']['ok'] is True
    assert [event['phase'] for event in tamarin['installation']['events']] == ['installing', 'installed']


def test_optional_solver_installation_doc_covers_blocked_lanes_and_commands() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-086' in doc
    assert 'Apalache' in doc
    assert 'Tamarin' in doc
    assert 'ProVerif' in doc
    assert 'Lean' in doc
    assert 'Rocq' in doc
    assert 'Leanstral' in doc
    assert 'blocked_optional_lane' in doc
    assert 'advisory' in doc
    assert '--install' in doc
