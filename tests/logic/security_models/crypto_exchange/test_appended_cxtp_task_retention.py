import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'check_appended_cxtp_tasks.py'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'appended_task_retention_runbook.md'
TASKBOARD_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'crypto_exchange_theorem_prover_taskboard.todo.md'


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location('check_appended_cxtp_tasks', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task(task_id: str, status: str = 'todo', depends: str = 'PORTAL-CXTP-086', evidence: bool = False) -> str:
    evidence_line = '- Completion evidence: pytest\n' if evidence else ''
    return f"""## {task_id} Synthetic appended task

- Status: {status}
- Completion: manual
{evidence_line}- Priority: P1
- Track: solver
- Depends on: {depends}
- Outputs: artifact-{task_id}.json
- Validation: pytest
- Acceptance: Retain task metadata.
"""


def _full_board() -> str:
    chunks = []
    for number in range(90, 98):
        task_id = f'PORTAL-CXTP-{number:03d}'
        depends = 'PORTAL-CXTP-086'
        if task_id == 'PORTAL-CXTP-094':
            depends = 'PORTAL-CXTP-085'
        elif task_id == 'PORTAL-CXTP-095':
            depends = 'PORTAL-CXTP-094'
        elif task_id == 'PORTAL-CXTP-096':
            depends = 'PORTAL-CXTP-087'
        elif task_id == 'PORTAL-CXTP-097':
            depends = 'PORTAL-CXTP-096'
        chunks.append(_task(task_id, depends=depends))
    return '# Synthetic board\n\n' + '\n'.join(chunks)


def test_appended_cxtp_task_retention_current_taskboard_passes() -> None:
    module = _load_module()

    report = module.build_report(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD_PATH,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['schema_version'] == 'appended-cxtp-task-retention/v1'
    assert report['overall_status'] == 'ready'
    assert report['retained_count'] == 8
    assert {task['task_id'] for task in report['retained_tasks']} == set(module.APPENDED_TASK_IDS)


def test_appended_cxtp_task_retention_blocks_missing_task(tmp_path: Path) -> None:
    module = _load_module()
    board = tmp_path / 'board.todo.md'
    board.write_text(_full_board().replace('## PORTAL-CXTP-097 Synthetic appended task', '## PORTAL-CXTP-198 Other task'), encoding='utf-8')

    report = module.build_report(repo_root=tmp_path, taskboard_path=board)

    assert report['overall_status'] == 'blocked'
    assert any(blocker['code'] == 'APPENDED_TASK_MISSING' for blocker in report['blockers'])


def test_appended_cxtp_task_retention_blocks_missing_metadata(tmp_path: Path) -> None:
    module = _load_module()
    board = tmp_path / 'board.todo.md'
    board.write_text(_full_board().replace('- Validation: pytest\n', '', 1), encoding='utf-8')

    report = module.build_report(repo_root=tmp_path, taskboard_path=board)

    assert any(blocker['code'] == 'APPENDED_TASK_METADATA_MISSING' for blocker in report['blockers'])


def test_appended_cxtp_task_retention_blocks_completed_without_evidence(tmp_path: Path) -> None:
    module = _load_module()
    board = tmp_path / 'board.todo.md'
    board.write_text(_full_board().replace('- Status: todo', '- Status: completed', 1), encoding='utf-8')

    report = module.build_report(repo_root=tmp_path, taskboard_path=board)

    assert any(
        blocker['code'] == 'APPENDED_TASK_COMPLETED_WITHOUT_EVIDENCE'
        for blocker in report['blockers']
    )


def test_appended_cxtp_task_retention_blocks_required_dependency_removal(tmp_path: Path) -> None:
    module = _load_module()
    board = tmp_path / 'board.todo.md'
    board.write_text(_full_board().replace('- Depends on: PORTAL-CXTP-096', '- Depends on: PORTAL-CXTP-090'), encoding='utf-8')

    report = module.build_report(repo_root=tmp_path, taskboard_path=board)

    assert any(
        blocker['code'] == 'APPENDED_TASK_REQUIRED_DEPENDENCY_MISSING'
        and blocker['task_id'] == 'PORTAL-CXTP-097'
        for blocker in report['blockers']
    )


def test_appended_cxtp_task_retention_cli_writes_report(tmp_path: Path) -> None:
    module = _load_module()
    board = tmp_path / 'board.todo.md'
    out = tmp_path / 'report.json'
    board.write_text(_full_board(), encoding='utf-8')

    rc = module.main(['--repo-root', str(tmp_path), '--taskboard', str(board), '--out', str(out)])

    assert rc == 0
    report = json.loads(out.read_text(encoding='utf-8'))
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'APPENDED_TASK_RETENTION_READY'


def test_appended_cxtp_task_retention_runbook_covers_policy() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-096' in doc
    assert 'PORTAL-CXTP-090' in doc
    assert 'PORTAL-CXTP-097' in doc
    assert 'check_appended_cxtp_tasks.py' in doc
