import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'preflight_crypto_exchange_taskboard.py'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'taskboard_preflight_ci.md'
WORKFLOW_PATH = REPO_ROOT / '.github' / 'workflows' / 'crypto-exchange-security-verification.yml'


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location('preflight_crypto_exchange_taskboard', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_board(root: Path, body: str) -> Path:
    path = root / 'taskboard.todo.md'
    path.write_text(body, encoding='utf-8')
    return path


def _write_state(root: Path, statuses: dict[str, str]) -> Path:
    path = root / 'state.json'
    path.write_text(
        json.dumps(
            {
                'task_count': len(statuses),
                'task_statuses': statuses,
                'completed_task_ids': [task_id for task_id, status in statuses.items() if status == 'completed'],
                'active_task_id': None,
            }
        ),
        encoding='utf-8',
    )
    return path


def _minimal_board(status: str = 'completed', output: str = 'artifact.txt') -> str:
    return f"""# Board

## PORTAL-CXTP-077 Production blocker task

- Status: {status}
- Completion: manual
- Completion evidence: pytest
- Priority: P0
- Track: ops
- Depends on: PORTAL-CXTP-056
- Outputs: {output}
- Validation: pytest
- Acceptance: test
"""


def test_taskboard_preflight_accepts_parseable_completed_task_with_existing_output(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / 'artifact.txt').write_text('ok', encoding='utf-8')
    board = _write_board(tmp_path, _minimal_board())
    state = _write_state(tmp_path, {'PORTAL-CXTP-077': 'completed'})

    report = module.build_report(
        repo_root=tmp_path,
        taskboard_path=board,
        state_path=state,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'ready'
    assert report['blocker_count'] == 0
    assert report['taskboard']['task_count'] == 1


def test_taskboard_preflight_blocks_empty_taskboard(tmp_path: Path) -> None:
    module = _load_module()
    board = _write_board(tmp_path, '# no tasks\n')
    state = _write_state(tmp_path, {})

    report = module.build_report(repo_root=tmp_path, taskboard_path=board, state_path=state)

    assert report['overall_status'] == 'blocked'
    assert any(blocker['code'] == 'TASKBOARD_HAS_NO_PARSEABLE_TASKS' for blocker in report['blockers'])


def test_taskboard_preflight_blocks_missing_completed_output(tmp_path: Path) -> None:
    module = _load_module()
    board = _write_board(tmp_path, _minimal_board(output='missing.txt'))
    state = _write_state(tmp_path, {'PORTAL-CXTP-077': 'completed'})

    report = module.build_report(repo_root=tmp_path, taskboard_path=board, state_path=state)

    assert any(blocker['code'] == 'COMPLETED_TASK_OUTPUT_MISSING' for blocker in report['blockers'])
    assert report['security_decision'] == 'BLOCK_TASKBOARD_PREFLIGHT'


def test_taskboard_preflight_blocks_supervisor_status_contradictions(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / 'artifact.txt').write_text('ok', encoding='utf-8')
    board = _write_board(tmp_path, _minimal_board(status='completed'))
    state = _write_state(tmp_path, {'PORTAL-CXTP-077': 'blocked'})

    report = module.build_report(repo_root=tmp_path, taskboard_path=board, state_path=state)

    assert any(
        blocker['code'] == 'SUPERVISOR_STATE_STATUS_CONTRADICTS_TASKBOARD'
        for blocker in report['blockers']
    )


def test_taskboard_preflight_blocks_release_acceptable_production_report_with_incomplete_blockers(
    tmp_path: Path,
) -> None:
    module = _load_module()
    board = _write_board(tmp_path, _minimal_board(status='todo'))
    state = _write_state(tmp_path, {'PORTAL-CXTP-077': 'todo'})
    report_dir = tmp_path / 'security_ir_artifacts' / 'production'
    report_dir.mkdir(parents=True)
    (report_dir / 'evidence-bundle-report.json').write_text(
        json.dumps(
            {
                'overall_status': 'ready',
                'production_release_blocked': False,
                'security_decision': 'PRODUCTION_RELEASE_ACCEPTABLE',
            }
        ),
        encoding='utf-8',
    )

    report = module.build_report(repo_root=tmp_path, taskboard_path=board, state_path=state)

    assert any(
        blocker['code'] == 'PRODUCTION_BLOCKERS_TREATED_AS_RELEASE_ACCEPTABLE'
        for blocker in report['blockers']
    )


def test_taskboard_preflight_cli_writes_report_and_returns_nonzero_for_blockers(tmp_path: Path) -> None:
    module = _load_module()
    board = _write_board(tmp_path, _minimal_board(output='missing.txt'))
    state = _write_state(tmp_path, {'PORTAL-CXTP-077': 'completed'})
    out = tmp_path / 'report.json'

    rc = module.main(['--repo-root', str(tmp_path), '--taskboard', str(board), '--state', str(state), '--out', str(out)])

    assert rc == 1
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['overall_status'] == 'blocked'


def test_taskboard_preflight_docs_and_workflow_are_wired() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')
    workflow = WORKFLOW_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-087' in doc
    assert 'preflight_crypto_exchange_taskboard.py' in doc
    assert 'preflight_crypto_exchange_taskboard.py' in workflow
    assert 'test_taskboard_preflight.py' in workflow
