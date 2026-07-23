import importlib.util
import json
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'probe_theorem_prover_environment.py'
)
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'environment'
    / 'solver-dependency-probe.json'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'probe_theorem_prover_environment',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load solver dependency probe')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, object]:
    executable = Path(command[0]).name
    outputs = {
        'python': 'Python 3.11.9',
        'python3': 'Python 3.11.9',
        'node': 'v22.0.0',
        'npm': '10.8.0',
        'tsc': 'Version 5.5.4',
        'z3': 'Z3 version 4.13.0 - 64 bit',
        'cvc5': 'This is cvc5 version 1.1.2',
    }
    return {
        'exit_code': 0,
        'stdout': outputs.get(executable, f'{executable} version 1.0.0'),
        'stderr': '',
        'timed_out': False,
        'error': None,
    }


def test_build_probe_marks_required_missing_as_blocking_and_optional_missing_as_gap() -> None:
    module = _load_script_module()
    available = {
        'node': '/usr/bin/node',
        'npm': '/usr/bin/npm',
        'tsc': '/usr/bin/tsc',
        'z3': '/usr/bin/z3',
    }

    report = module.build_probe(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        which=lambda candidate: available.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['schema_version'] == 'crypto-exchange-solver-dependency-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-058'
    assert report['overall_status'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    assert report['security_decision'] == 'BLOCK_PROOF_ACCEPTANCE_MISSING_SOLVER_DEPENDENCY'

    blockers = {blocker['component']: blocker for blocker in report['blocking_evidence']}
    assert blockers['cvc5']['code'] == 'REQUIRED_DEPENDENCY_MISSING'

    gaps = {gap['component']: gap for gap in report['optional_capability_gaps']}
    assert {
        'apalache',
        'tamarin',
        'proverif',
        'lean',
        'coq',
    }.issubset(gaps)
    assert gaps['apalache']['code'] == 'OPTIONAL_DEPENDENCY_MISSING'
    assert all('do not claim this prover coverage' in gap['impact'] for gap in gaps.values())


def test_build_probe_is_ready_with_only_optional_capability_gaps() -> None:
    module = _load_script_module()
    available = {
        'node': '/usr/bin/node',
        'npm': '/usr/bin/npm',
        'tsc': '/usr/bin/tsc',
        'z3': '/usr/bin/z3',
        'cvc5': '/usr/bin/cvc5',
    }

    report = module.build_probe(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        which=lambda candidate: available.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'ready'
    assert report['proof_acceptance_blocked'] is False
    assert report['blocking_evidence'] == []
    assert report['security_decision'] == 'SOLVER_DEPENDENCY_ENVIRONMENT_READY_WITH_CAPABILITY_GAPS'
    assert report['summary']['present_required_dependency_count'] == report['summary'][
        'required_dependency_count'
    ]


def test_required_environment_variables_are_blocking_evidence() -> None:
    module = _load_script_module()
    available = {
        'node': '/usr/bin/node',
        'npm': '/usr/bin/npm',
        'tsc': '/usr/bin/tsc',
        'z3': '/usr/bin/z3',
        'cvc5': '/usr/bin/cvc5',
    }

    report = module.build_probe(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin'},
        runner=_fake_runner,
        which=lambda candidate: available.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {
        blocker['code']: blocker['component']
        for blocker in report['blocking_evidence']
        if blocker['code'] == 'REQUIRED_ENV_VAR_MISSING'
    } == {'REQUIRED_ENV_VAR_MISSING': 'PYTHONPATH'}
    env_vars = {entry['name']: entry for entry in report['environment_variables']}
    assert env_vars['PATH']['present'] is True
    assert env_vars['PYTHONPATH']['present'] is False


def test_cli_writes_probe_report_even_when_environment_is_blocked(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'probe.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--out',
            out_path.as_posix(),
            '--timeout-seconds',
            '2',
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-solver-dependency-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-058'
    assert {'python', 'node', 'npm', 'typescript', 'z3', 'cvc5'}.issubset(
        {dependency['name'] for dependency in report['dependencies']}
    )
    assert {'PATH', 'PYTHONPATH'}.issubset(
        {env_var['name'] for env_var in report['environment_variables']}
    )


def test_checked_in_probe_artifact_has_required_schema_and_components() -> None:
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'crypto-exchange-solver-dependency-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-058'
    assert report['policy_document'] == 'docs/security_verification/solver_dependency_bootstrap.md'
    assert isinstance(report['proof_acceptance_blocked'], bool)
    assert isinstance(report['blocking_evidence'], list)
    assert isinstance(report['optional_capability_gaps'], list)

    dependencies = {dependency['name']: dependency for dependency in report['dependencies']}
    for required in ('python', 'node', 'npm', 'typescript', 'z3', 'cvc5'):
        assert dependencies[required]['required'] is True
    for optional in ('apalache', 'tamarin', 'proverif', 'lean', 'coq'):
        assert dependencies[optional]['required'] is False

    env_vars = {entry['name']: entry for entry in report['environment_variables']}
    assert env_vars['PATH']['required'] is True
    assert env_vars['PYTHONPATH']['required'] is True
