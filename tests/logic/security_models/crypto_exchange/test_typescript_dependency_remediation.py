import importlib.util
import json
from pathlib import Path
import socket
import sys
from typing import Any, Mapping, Sequence

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'provision_required_typescript_toolchain.py'
)
CHECKED_IN_REPORT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'environment'
    / 'typescript-remediation-report.json'
)
CHECKED_IN_PROBE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'environment'
    / 'solver-dependency-probe.json'
)
POLICY_DOC_PATH = (
    REPO_ROOT
    / 'docs'
    / 'security_verification'
    / 'typescript_solver_dependency_remediation.md'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'provision_required_typescript_toolchain',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load typescript toolchain provisioning script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _npm_registry_reachable() -> bool:
    try:
        with socket.create_connection(('registry.npmjs.org', 443), timeout=2.0):
            return True
    except OSError:
        return False


class _FakeProbeModule:
    """Deterministic stand-in for probe_theorem_prover_environment.build_probe."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.build_probe_calls: list[dict[str, Any]] = []
        self.write_json_calls: list[dict[str, Any]] = []

    def build_probe(self, repo_root: Path, environ: Mapping[str, str]) -> dict[str, Any]:
        self.build_probe_calls.append({'repo_root': repo_root, 'environ': dict(environ)})
        return self.result

    def write_json(self, document: dict[str, Any], out_path: Path) -> None:
        self.write_json_calls.append({'document': document, 'out_path': out_path})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _fake_probe_result(blocked: bool) -> dict[str, Any]:
    return {
        'overall_status': 'blocked' if blocked else 'ready',
        'proof_acceptance_blocked': blocked,
        'summary': {
            'blocking_evidence_count': 1 if blocked else 0,
            'optional_capability_gap_count': 5,
        },
    }


def _fake_which_factory(available: Mapping[str, str]):
    def _which(candidate: str) -> str | None:
        return available.get(candidate)

    return _which


def _npm_install_runner_creating_tsc(toolchain_dir: Path, version: str = '5.6.3'):
    """A fake CommandRunner that mimics `npm install` provisioning a real tsc shim."""

    def _runner(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
        command_name = Path(command[0]).name
        if command_name == 'npm' and 'install' in command:
            bin_dir = toolchain_dir / 'node_modules' / '.bin'
            bin_dir.mkdir(parents=True, exist_ok=True)
            real_dir = toolchain_dir / 'node_modules' / 'typescript' / 'bin'
            real_dir.mkdir(parents=True, exist_ok=True)
            tsc_real = real_dir / 'tsc'
            tsc_real.write_text(
                f'#!/bin/sh\necho "Version {version}"\n',
                encoding='utf-8',
            )
            tsc_real.chmod(0o755)
            tsc_shim = bin_dir / 'tsc'
            if not tsc_shim.exists():
                tsc_shim.symlink_to(Path('..') / 'typescript' / 'bin' / 'tsc')
            return {'exit_code': 0, 'stdout': 'added 1 package', 'stderr': '', 'timed_out': False, 'error': None}
        if command_name == 'tsc' or (len(command) > 1 and command[-1] == '--version'):
            return {'exit_code': 0, 'stdout': f'Version {version}', 'stderr': '', 'timed_out': False, 'error': None}
        return {'exit_code': 1, 'stdout': '', 'stderr': 'unknown command', 'timed_out': False, 'error': None}

    return _runner


def test_resolve_tsc_prefers_explicit_tsc_exe_override(tmp_path: Path) -> None:
    module = _load_script_module()
    override = tmp_path / 'custom-tsc'
    override.write_text('#!/bin/sh\necho Version 9.9.9\n', encoding='utf-8')
    override.chmod(0o755)

    executable, resolved_by, searched = module.resolve_tsc(
        toolchain_dir=tmp_path / 'toolchain',
        environ={'TSC_EXE': override.as_posix()},
        which=_fake_which_factory({}),
    )

    assert executable == override.as_posix()
    assert resolved_by == 'TSC_EXE'
    assert override.as_posix() in searched


def test_resolve_tsc_finds_toolchain_dir_before_path_lookup(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'
    bin_dir = toolchain_dir / 'node_modules' / '.bin'
    bin_dir.mkdir(parents=True)
    tsc_path = bin_dir / 'tsc'
    tsc_path.write_text('#!/bin/sh\necho Version 5.6.3\n', encoding='utf-8')
    tsc_path.chmod(0o755)

    executable, resolved_by, _searched = module.resolve_tsc(
        toolchain_dir=toolchain_dir,
        environ={},
        which=_fake_which_factory({}),
    )

    assert executable == tsc_path.as_posix()
    assert resolved_by == 'toolchain_dir'


def test_resolve_tsc_missing_everywhere_returns_none(tmp_path: Path) -> None:
    module = _load_script_module()

    executable, resolved_by, searched = module.resolve_tsc(
        toolchain_dir=tmp_path / 'toolchain',
        environ={},
        which=_fake_which_factory({}),
    )

    assert executable is None
    assert resolved_by is None
    assert 'tsc' in searched


def test_provision_skips_install_when_tsc_already_present(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'
    bin_dir = toolchain_dir / 'node_modules' / '.bin'
    bin_dir.mkdir(parents=True)
    tsc_path = bin_dir / 'tsc'
    tsc_path.write_text('#!/bin/sh\necho Version 5.6.3\n', encoding='utf-8')
    tsc_path.chmod(0o755)

    def _version_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
        return {'exit_code': 0, 'stdout': 'Version 5.6.3', 'stderr': '', 'timed_out': False, 'error': None}

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=tmp_path / 'missing-probe.json',
        toolchain_dir=toolchain_dir,
        refresh_probe_out=None,
        environ={},
        runner=_version_runner,
        which=_fake_which_factory({}),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['remediation_status'] == 'skipped_already_present'
    assert report['typescript_status_after']['status'] == 'present'
    assert report['typescript_status_after']['blocking'] is False
    assert report['proof_acceptance_blocked'] is False
    assert report['overall_status'] == 'remediated'
    assert report['security_decision'] == 'TYPESCRIPT_DEPENDENCY_REMEDIATED'
    assert not any(action['action'] == 'npm_install' for action in report['remediation_actions'])


def test_provision_reports_failed_when_npm_is_unavailable(tmp_path: Path) -> None:
    module = _load_script_module()

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=tmp_path / 'missing-probe.json',
        toolchain_dir=tmp_path / 'toolchain',
        refresh_probe_out=None,
        environ={},
        runner=lambda command, timeout: {'exit_code': None, 'stdout': '', 'stderr': '', 'timed_out': False, 'error': 'file_not_found'},
        which=_fake_which_factory({}),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['remediation_status'] == 'failed_no_npm'
    assert report['typescript_status_after']['status'] == 'missing'
    assert report['proof_acceptance_blocked'] is True
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_PROOF_ACCEPTANCE_TYPESCRIPT_DEPENDENCY_UNAVAILABLE'


def test_provision_installs_and_resolves_tsc_when_npm_succeeds(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'

    baseline_probe = tmp_path / 'baseline-probe.json'
    baseline_probe.write_text(
        json.dumps(
            {
                'dependencies': [
                    {'name': 'typescript', 'status': 'missing', 'blocking': True, 'required': True},
                ]
            }
        ),
        encoding='utf-8',
    )

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=baseline_probe,
        toolchain_dir=toolchain_dir,
        refresh_probe_out=None,
        environ={},
        runner=_npm_install_runner_creating_tsc(toolchain_dir),
        which=_fake_which_factory({'npm': '/usr/bin/npm'}),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['typescript_status_before'] == {
        'name': 'typescript',
        'status': 'missing',
        'blocking': True,
        'required': True,
    }
    assert report['remediation_status'] == 'resolved'
    assert report['typescript_status_after']['status'] == 'present'
    assert report['typescript_status_after']['version'] == '5.6.3'
    assert report['proof_acceptance_blocked'] is False
    assert report['overall_status'] == 'remediated'
    assert report['security_decision'] == 'TYPESCRIPT_DEPENDENCY_REMEDIATED'

    install_actions = [action for action in report['remediation_actions'] if action['action'] == 'npm_install']
    assert len(install_actions) == 1
    assert install_actions[0]['status'] == 'ok'

    package_json_path = toolchain_dir / 'package.json'
    assert package_json_path.is_file()
    package_json = json.loads(package_json_path.read_text(encoding='utf-8'))
    assert package_json['devDependencies']['typescript'] == module.DEFAULT_TYPESCRIPT_VERSION


def test_provision_still_blocked_when_npm_install_fails(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'

    def _failing_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
        if 'install' in command:
            return {'exit_code': 1, 'stdout': '', 'stderr': 'network unreachable', 'timed_out': False, 'error': None}
        return {'exit_code': None, 'stdout': '', 'stderr': '', 'timed_out': False, 'error': 'file_not_found'}

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=tmp_path / 'missing-probe.json',
        toolchain_dir=toolchain_dir,
        refresh_probe_out=None,
        environ={},
        runner=_failing_runner,
        which=_fake_which_factory({'npm': '/usr/bin/npm'}),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['remediation_status'] == 'failed_install_error'
    assert report['typescript_status_after']['status'] == 'missing'
    assert report['proof_acceptance_blocked'] is True
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_PROOF_ACCEPTANCE_TYPESCRIPT_DEPENDENCY_UNAVAILABLE'


def test_provision_refreshes_probe_evidence_using_toolchain_path(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'
    refresh_out = tmp_path / 'refreshed-probe.json'
    fake_probe_module = _FakeProbeModule(_fake_probe_result(blocked=False))

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=tmp_path / 'missing-probe.json',
        toolchain_dir=toolchain_dir,
        refresh_probe_out=refresh_out,
        environ={'PATH': '/usr/bin'},
        runner=_npm_install_runner_creating_tsc(toolchain_dir),
        which=_fake_which_factory({'npm': '/usr/bin/npm'}),
        generated_at_utc='2026-07-08T00:00:00Z',
        probe_module=fake_probe_module,
    )

    assert report['refreshed_probe'] == {
        'path': 'refreshed-probe.json',
        'written': True,
        'overall_status': 'ready',
        'proof_acceptance_blocked': False,
        'blocking_evidence_count': 0,
        'optional_capability_gap_count': 5,
    }
    assert report['proof_acceptance_blocked'] is False
    assert refresh_out.is_file()

    assert len(fake_probe_module.build_probe_calls) == 1
    refreshed_env = fake_probe_module.build_probe_calls[0]['environ']
    assert str(toolchain_dir / 'node_modules' / '.bin') in refreshed_env['PATH']
    assert refreshed_env['PATH'].endswith('/usr/bin')


def test_provision_keeps_proof_acceptance_blocked_when_refreshed_probe_still_blocked(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'
    refresh_out = tmp_path / 'refreshed-probe.json'
    fake_probe_module = _FakeProbeModule(_fake_probe_result(blocked=True))

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=tmp_path / 'missing-probe.json',
        toolchain_dir=toolchain_dir,
        refresh_probe_out=refresh_out,
        environ={'PATH': '/usr/bin'},
        runner=_npm_install_runner_creating_tsc(toolchain_dir),
        which=_fake_which_factory({'npm': '/usr/bin/npm'}),
        generated_at_utc='2026-07-08T00:00:00Z',
        probe_module=fake_probe_module,
    )

    # Typescript itself resolved, but another required dependency is still
    # missing per the (fake) refreshed probe, so proof acceptance stays blocked.
    assert report['typescript_status_after']['blocking'] is False
    assert report['proof_acceptance_blocked'] is True
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_PROOF_ACCEPTANCE_OTHER_REQUIRED_DEPENDENCY_MISSING'


def test_cli_writes_remediation_report_json(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'toolchain'
    bin_dir = toolchain_dir / 'node_modules' / '.bin'
    bin_dir.mkdir(parents=True)
    tsc_path = bin_dir / 'tsc'
    tsc_path.write_text('#!/bin/sh\necho Version 5.6.3\n', encoding='utf-8')
    tsc_path.chmod(0o755)

    out_path = tmp_path / 'report.json'
    probe_path = tmp_path / 'probe.json'
    probe_path.write_text(json.dumps({'dependencies': []}), encoding='utf-8')

    rc = module.main(
        [
            '--repo-root',
            tmp_path.as_posix(),
            '--probe',
            probe_path.as_posix(),
            '--out',
            out_path.as_posix(),
            '--toolchain-dir',
            toolchain_dir.as_posix(),
            '--skip-refresh-probe',
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-typescript-dependency-remediation/v1'
    assert report['task_id'] == 'PORTAL-CXTP-089'
    assert report['remediation_status'] == 'skipped_already_present'
    assert report['refreshed_probe'] is None


@pytest.mark.skipif(
    __import__('shutil').which('npm') is None,
    reason='npm is not installed on this host',
)
@pytest.mark.skipif(not _npm_registry_reachable(), reason='npm registry is not reachable from this host')
def test_live_provisioning_installs_real_typescript_compiler(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain_dir = tmp_path / 'typescript_toolchain'
    probe_path = tmp_path / 'probe.json'
    probe_path.write_text(json.dumps({'dependencies': []}), encoding='utf-8')
    refresh_out = tmp_path / 'refreshed-probe.json'

    report = module.provision_typescript_toolchain(
        repo_root=tmp_path,
        probe_in_path=probe_path,
        toolchain_dir=toolchain_dir,
        refresh_probe_out=refresh_out,
        typescript_version=module.DEFAULT_TYPESCRIPT_VERSION,
        npm_timeout_seconds=180,
    )

    assert report['remediation_status'] in ('resolved', 'skipped_already_present')
    assert report['typescript_status_after']['status'] == 'present'
    assert report['typescript_status_after']['version'] == module.DEFAULT_TYPESCRIPT_VERSION
    assert report['typescript_status_after']['blocking'] is False
    tsc_path = module.toolchain_tsc_path(toolchain_dir)
    assert tsc_path.is_file()
    assert refresh_out.is_file()


def test_checked_in_remediation_report_has_required_schema_and_is_not_blocked() -> None:
    report = json.loads(CHECKED_IN_REPORT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'crypto-exchange-typescript-dependency-remediation/v1'
    assert report['task_id'] == 'PORTAL-CXTP-089'
    assert report['upstream_probe_task_id'] == 'PORTAL-CXTP-058'
    assert report['policy_document'] == 'docs/security_verification/typescript_solver_dependency_remediation.md'
    assert isinstance(report['proof_acceptance_blocked'], bool)
    assert report['typescript_status_after']['status'] in ('present', 'present_unverified', 'missing')
    if report['typescript_status_after']['status'] != 'present':
        assert report['proof_acceptance_blocked'] is True
    else:
        assert report['typescript_status_after']['blocking'] is False


def test_checked_in_solver_probe_reflects_typescript_after_remediation() -> None:
    probe = json.loads(CHECKED_IN_PROBE_PATH.read_text(encoding='utf-8'))
    dependencies = {dependency['name']: dependency for dependency in probe['dependencies']}
    typescript = dependencies['typescript']

    # PORTAL-CXTP-089 must not silently mark typescript present without a
    # successful `tsc --version` command result.
    if typescript['status'] == 'present':
        assert typescript['blocking'] is False
        assert typescript.get('command_result', {}).get('exit_code') == 0
    else:
        assert typescript['blocking'] is True
        assert probe['proof_acceptance_blocked'] is True


def test_policy_document_exists() -> None:
    assert POLICY_DOC_PATH.is_file()
    content = POLICY_DOC_PATH.read_text(encoding='utf-8')
    assert 'PORTAL-CXTP-089' in content
    assert 'tsc' in content
