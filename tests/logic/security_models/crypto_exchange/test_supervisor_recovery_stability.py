import importlib.util
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'restore_crypto_exchange_security_tree.py'
)
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'recovery' / 'supervisor-stability-report.json'


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'restore_crypto_exchange_security_tree',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load supervisor recovery stability script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ['git', *args],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _minimal_taskboard() -> str:
    return """# Crypto Exchange Theorem-Prover Security Plan And Taskboard

## PORTAL-CXTP-088 Stabilize recovered tree across supervisor commit cleanup

- Status: todo
- Depends on: PORTAL-CXTP-056, PORTAL-CXTP-057, PORTAL-CXTP-058
- Outputs: docs/security_verification/supervisor_recovery_stability_runbook.md, scripts/ops/security_verification/restore_crypto_exchange_security_tree.py, security_ir_artifacts/recovery/supervisor-stability-report.json, tests/logic/security_models/crypto_exchange/test_supervisor_recovery_stability.py
"""


def test_live_checkout_supervisor_stability_report_passes(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'supervisor-stability-report.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--verify-only',
            '--report',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-supervisor-recovery-stability/v1'
    assert report['task_id'] == 'PORTAL-CXTP-088'
    assert report['overall_status'] == 'pass'
    assert report['downstream_task_gate'] == 'allowed'
    assert report['proof_acceptance_blocked'] is False
    assert report['blockers'] == []

    groups = {group['name']: group for group in report['groups']}
    assert {
        'taskboard',
        'source_files',
        'xaman_artifacts',
        'retention_baseline',
        'solver_probe',
        'stability_controls',
    }.issubset(groups)
    assert groups['taskboard']['present_count'] == 1
    assert groups['source_files']['present_count'] >= 10
    assert REPORT_PATH.as_posix().endswith('security_ir_artifacts/recovery/supervisor-stability-report.json')


def test_restore_recovers_missing_taskboard_and_source_from_durable_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(
        module,
        'STATIC_REQUIRED_PATHS',
        {
            'taskboard': (
                'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
            ),
        },
    )
    monkeypatch.setattr(module, 'ESSENTIAL_TEST_PATHS', ())
    taskboard = tmp_path / 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md'
    source = tmp_path / 'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py'
    _write(taskboard, _minimal_taskboard())
    _write(source, 'SCHEMA_VERSION = "fixture"\n')

    _git(tmp_path, 'init')
    _git(tmp_path, 'config', 'user.email', 'security@example.invalid')
    _git(tmp_path, 'config', 'user.name', 'Security Test')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-m', 'durable fixture')

    taskboard.unlink()
    source.unlink()

    report = module.verify_or_restore(
        tmp_path,
        verify_only=False,
        durable_refs=('HEAD',),
    )

    assert report['overall_status'] == 'pass'
    assert report['downstream_task_gate'] == 'allowed'
    assert sorted(item['path'] for item in report['restored_artifacts']) == [
        'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
        'ipfs_datasets_py/logic/security_models/crypto_exchange/ir/schema.py',
    ]
    assert taskboard.read_text(encoding='utf-8') == _minimal_taskboard()
    assert source.read_text(encoding='utf-8') == 'SCHEMA_VERSION = "fixture"\n'


def test_verify_only_fails_closed_when_required_artifact_is_missing(tmp_path: Path) -> None:
    module = _load_script_module()
    report = module.verify_or_restore(
        tmp_path,
        verify_only=True,
        durable_refs=('missing-ref',),
    )

    assert report['overall_status'] == 'blocked'
    assert report['downstream_task_gate'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    assert report['security_decision'] == 'BLOCK_DOWNSTREAM_CRYPTO_EXCHANGE_SECURITY_TREE_UNSTABLE'
    assert report['restoration_instructions']
    assert any(
        blocker['code'] == 'REQUIRED_STABILITY_ARTIFACT_MISSING'
        and blocker['path'] == 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md'
        and blocker['durable_recovery_available'] is False
        for blocker in report['blockers']
    )
