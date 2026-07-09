"""Tests for PORTAL-CXTP-087 taskboard preflight wiring."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'preflight_crypto_exchange_taskboard.py'
)
TASKBOARD_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'crypto_exchange_theorem_prover_taskboard.todo.md'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'taskboard_preflight_ci.md'
WORKFLOW_PATH = REPO_ROOT / '.github' / 'workflows' / 'crypto-exchange-security-verification.yml'


def _load_script_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location('preflight_crypto_exchange_taskboard', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load taskboard preflight module')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _policy_payload(*, unknown_secure: bool = False) -> dict:
    outcomes = [
        {
            'outcome': 'prove',
            'secure_for_blocking_claims': True,
            'production_release_effect': 'eligible-for-acceptance',
        }
    ]
    for outcome in sorted(
        {
            'disprove',
            'unknown',
            'not-modeled',
            'stale-evidence',
            'missing-solver',
            'blocked-production',
        }
    ):
        outcomes.append(
            {
                'outcome': outcome,
                'secure_for_blocking_claims': bool(unknown_secure and outcome == 'unknown'),
                'production_release_effect': 'blocked-production',
            }
        )
    return {
        'default_consumer_rule': (
            'Only outcome prove may be consumed as secure for a blocking claim; '
            'every non-proved blocking claim is non-secure and blocks production.'
        ),
        'outcomes': outcomes,
        'proof_boundary': {
            'non_secure_blocking_outcomes': [
                'blocked-production',
                'disprove',
                'missing-solver',
                'not-modeled',
                'stale-evidence',
                'unknown',
            ]
        },
    }


def _valid_taskboard() -> str:
    return """# Crypto Exchange Theorem-Prover Security Plan And Taskboard

## PORTAL-CXTP-100 Completed fixture task

- Status: completed
- Completion: manual
- Priority: P0
- Track: quality
- Depends on:
- Outputs: docs/security_verification/completed.md
- Validation: test -f docs/security_verification/completed.md
- Acceptance: Completed task has its reviewed artifact.

## PORTAL-CXTP-101 Collect production fixture evidence

- Status: blocked
- Completion: manual
- Priority: P0
- Track: ops
- Blocked reason: Requires production source evidence not present in this repository.
- Depends on: PORTAL-CXTP-100
- Outputs: security_ir_artifacts/production/source-inventory.json
- Validation: test -f security_ir_artifacts/production/source-inventory.json
- Acceptance: Keep production release blocked until source evidence is present.
"""


def _make_repo(tmp_path: Path, *, unknown_secure: bool = False, taskboard: str | None = None) -> Path:
    _write(tmp_path / 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md', taskboard or _valid_taskboard())
    _write(tmp_path / 'docs/security_verification/completed.md', 'reviewed\n')
    _write(tmp_path / 'ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py', '\n')
    _write(
        tmp_path / 'security_ir_artifacts/recovery/artifact-retention-baseline.json',
        json.dumps(
            {
                'schema_version': 'crypto-exchange-artifact-retention/v1',
                'task_id': 'PORTAL-CXTP-057',
                'groups': [
                    {
                        'name': 'taskboard',
                        'entries': [
                            {
                                'path': 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
                            }
                        ],
                    },
                    {
                        'name': 'source_files',
                        'entries': [
                            {
                                'path': 'ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py',
                            }
                        ],
                    },
                ],
            }
        ),
    )
    _write(
        tmp_path / 'security_ir_artifacts/policies/security-decision-policy.json',
        json.dumps(_policy_payload(unknown_secure=unknown_secure)),
    )
    return tmp_path


def test_live_taskboard_parser_finds_portal_cxtp_087() -> None:
    module = _load_script_module()
    tasks = module.parse_taskboard(TASKBOARD_PATH.read_text(encoding='utf-8'))
    by_id = {task.task_id: task for task in tasks}

    assert 'PORTAL-CXTP-087' in by_id
    task = by_id['PORTAL-CXTP-087']
    assert task.status == 'todo'
    assert task.metadata['track'] == 'quality'
    assert 'scripts/ops/security_verification/preflight_crypto_exchange_taskboard.py' in task.outputs


def test_preflight_passes_integrity_but_keeps_blocked_production_release(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path)

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'pass'
    assert report['supervisor_preflight_gate'] == 'allowed'
    assert report['production_release_acceptable'] is False
    assert report['production_release_decision'] == 'blocked-production'
    assert report['summary']['blocked_production_task_count'] == 1
    assert report['blockers'] == []


def test_no_parseable_tasks_blocks(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path, taskboard='# no supervisor tasks here\n')

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    assert any(blocker['code'] == 'TASKBOARD_NO_PARSEABLE_TASKS' for blocker in report['blockers'])


def test_missing_source_file_from_retention_baseline_blocks(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path)
    (repo / 'ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py').unlink()

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    blocker = next(blocker for blocker in report['blockers'] if blocker['code'] == 'RETAINED_ARTIFACT_MISSING')
    assert blocker['group'] == 'source_files'


def test_completed_task_missing_output_blocks(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path)
    (repo / 'docs/security_verification/completed.md').unlink()

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    blocker = next(blocker for blocker in report['blockers'] if blocker['code'] == 'COMPLETED_TASK_OUTPUT_MISSING')
    assert blocker['task_id'] == 'PORTAL-CXTP-100'
    assert blocker['paths'] == ['docs/security_verification/completed.md']


def test_blocked_status_without_reason_blocks(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = _valid_taskboard().replace(
        '- Blocked reason: Requires production source evidence not present in this repository.\n',
        '',
    )
    repo = _make_repo(tmp_path, taskboard=taskboard)

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    assert any(blocker['code'] == 'BLOCKED_TASK_MISSING_REASON' for blocker in report['blockers'])


def test_release_policy_cannot_mark_non_prove_outcome_secure(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path, unknown_secure=True)

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    blocker = next(
        blocker
        for blocker in report['blockers']
        if blocker['code'] == 'RELEASE_POLICY_NON_PROVE_OUTCOME_MARKED_SECURE'
    )
    assert blocker['outcome'] == 'unknown'


def test_blocked_production_task_cannot_be_marked_release_acceptable(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = _valid_taskboard().replace(
        '- Blocked reason: Requires production source evidence not present in this repository.\n',
        '- Blocked reason: Requires production source evidence not present in this repository.\n'
        '- Production release acceptable: true\n',
    )
    repo = _make_repo(tmp_path, taskboard=taskboard)

    report = module.run_preflight(repo_root=repo)

    assert report['overall_status'] == 'blocked'
    assert any(
        blocker['code'] == 'PRODUCTION_BLOCKER_MARKED_RELEASE_ACCEPTABLE'
        and blocker['task_id'] == 'PORTAL-CXTP-101'
        for blocker in report['blockers']
    )


def test_main_returns_nonzero_and_writes_report_for_blocked_preflight(tmp_path: Path) -> None:
    module = _load_script_module()
    repo = _make_repo(tmp_path)
    (repo / 'docs/security_verification/completed.md').unlink()
    out_path = tmp_path / 'report.json'

    rc = module.main(['--repo-root', repo.as_posix(), '--out', out_path.as_posix()])

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 2
    assert report['overall_status'] == 'blocked'
    assert report['ci_gate'] == 'fail'


def test_expected_ci_and_docs_outputs_are_wired() -> None:
    assert SCRIPT_PATH.is_file()
    assert DOC_PATH.is_file()
    assert WORKFLOW_PATH.is_file()

    workflow = WORKFLOW_PATH.read_text(encoding='utf-8')
    assert 'preflight_crypto_exchange_taskboard.py' in workflow
    assert 'test_taskboard_preflight.py' in workflow
    assert 'taskboard-preflight-report.json' in workflow

    doc = DOC_PATH.read_text(encoding='utf-8')
    assert 'PORTAL-CXTP-087' in doc
    assert 'production_release_acceptable' in doc
