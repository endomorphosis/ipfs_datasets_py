import importlib.util
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'check_appended_cxtp_tasks.py'
)
TASKBOARD_PATH = (
    REPO_ROOT
    / 'docs'
    / 'security_verification'
    / 'crypto_exchange_theorem_prover_taskboard.todo.md'
)
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'recovery' / 'appended-task-retention-report.json'


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'check_appended_cxtp_tasks',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load appended task checker')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _task_block(
    *,
    task_id: str,
    title: str,
    priority: str,
    track: str,
    dependencies: tuple[str, ...],
    outputs: tuple[str, ...],
    validations: tuple[str, ...],
    status: str = 'todo',
    evidence: str | None = None,
) -> str:
    lines = [
        f'## {task_id} {title}',
        '',
        f'- Status: {status}',
        '- Completion: manual',
        f'- Priority: {priority}',
        f'- Track: {track}',
        f'- Depends on: {", ".join(dependencies)}',
        f'- Outputs: {", ".join(outputs)}',
        f'- Validation: {"; ".join(validations)}',
        '- Acceptance: fixture acceptance text.',
    ]
    if evidence is not None:
        lines.append(f'- Completion evidence: {evidence}')
    return '\n'.join(lines) + '\n'


def _full_taskboard(module) -> str:
    blocks = [
        _task_block(
            task_id=spec.task_id,
            title=spec.title,
            priority=spec.priority,
            track=spec.track,
            dependencies=spec.dependencies,
            outputs=spec.outputs,
            validations=spec.validations,
        )
        for spec in module.REQUIRED_TASKS
    ]
    return '# Fixture Taskboard\n\n' + '\n'.join(blocks)


def test_live_appended_task_retention_report_passes(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'appended-task-retention-report.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--taskboard',
            TASKBOARD_PATH.as_posix(),
            '--out',
            out_path.as_posix(),
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-appended-task-retention/v1'
    assert report['task_id'] == 'PORTAL-CXTP-096'
    assert report['overall_status'] == 'pass'
    assert report['downstream_task_gate'] == 'allowed'
    assert report['proof_acceptance_blocked'] is False
    assert report['summary']['protected_task_count'] == 6
    assert report['summary']['present_task_count'] == 6
    assert report['blockers'] == []
    assert REPORT_PATH.as_posix().endswith(
        'security_ir_artifacts/recovery/appended-task-retention-report.json'
    )


def test_missing_appended_task_fails_closed(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = tmp_path / 'taskboard.md'
    spec_blocks = []
    for spec in module.REQUIRED_TASKS:
        if spec.task_id == 'PORTAL-CXTP-092':
            continue
        spec_blocks.append(
            _task_block(
                task_id=spec.task_id,
                title=spec.title,
                priority=spec.priority,
                track=spec.track,
                dependencies=spec.dependencies,
                outputs=spec.outputs,
                validations=spec.validations,
            )
        )
    taskboard.write_text('# Fixture Taskboard\n\n' + '\n'.join(spec_blocks), encoding='utf-8')

    report = module.check_appended_tasks(taskboard, tmp_path)

    assert report['overall_status'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    assert report['security_decision'] == 'BLOCK_APPENDED_CXTP_TASK_RETENTION'
    assert any(
        blocker['code'] == 'APPENDED_TASK_MISSING'
        and blocker['task_id'] == 'PORTAL-CXTP-092'
        for blocker in report['blockers']
    )


def test_lost_dependency_and_validation_command_fail_closed(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = tmp_path / 'taskboard.md'
    text = _full_taskboard(module)
    spec = module.REQUIRED_TASKS[0]
    text = text.replace(
        f'- Depends on: {", ".join(spec.dependencies)}',
        '- Depends on: PORTAL-CXTP-058, PORTAL-CXTP-086',
        1,
    )
    text = text.replace(
        f'- Validation: {"; ".join(spec.validations)}',
        f'- Validation: {spec.validations[0]}',
        1,
    )
    taskboard.write_text(text, encoding='utf-8')

    report = module.check_appended_tasks(taskboard, tmp_path)

    assert report['overall_status'] == 'blocked'
    blockers = [
        blocker
        for blocker in report['blockers']
        if blocker.get('task_id') == 'PORTAL-CXTP-090'
    ]
    assert any(
        blocker['code'] == 'APPENDED_TASK_DEPENDENCIES_MISSING'
        and blocker['missing_dependencies'] == ['PORTAL-CXTP-096']
        for blocker in blockers
    )
    assert any(
        blocker['code'] == 'APPENDED_TASK_VALIDATION_COMMANDS_MISSING'
        and spec.validations[1] in blocker['missing_validations']
        for blocker in blockers
    )


def test_completed_appended_task_without_evidence_fails_closed(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = tmp_path / 'taskboard.md'
    text = _full_taskboard(module).replace('- Status: todo', '- Status: completed', 1)
    taskboard.write_text(text, encoding='utf-8')

    report = module.check_appended_tasks(taskboard, tmp_path)

    assert report['overall_status'] == 'blocked'
    blocker = next(
        blocker
        for blocker in report['blockers']
        if blocker['code'] == 'APPENDED_TASK_COMPLETED_WITHOUT_EVIDENCE'
    )
    assert blocker['task_id'] == 'PORTAL-CXTP-090'
    error_codes = {error['code'] for error in blocker['errors']}
    assert 'COMPLETION_EVIDENCE_FIELD_MISSING' in error_codes
    assert 'COMPLETED_TASK_OUTPUTS_MISSING' in error_codes


def test_completed_appended_task_with_outputs_and_evidence_passes(tmp_path: Path) -> None:
    module = _load_script_module()
    taskboard = tmp_path / 'taskboard.md'
    spec = module.REQUIRED_TASKS[0]
    for output in spec.outputs:
        path = tmp_path / output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture output\n', encoding='utf-8')

    blocks = [
        _task_block(
            task_id=spec.task_id,
            title=spec.title,
            priority=spec.priority,
            track=spec.track,
            dependencies=spec.dependencies,
            outputs=spec.outputs,
            validations=spec.validations,
            status='completed',
            evidence=f'Validated with {spec.validations[0]} and wrote {spec.outputs[0]}.',
        )
        if spec.task_id == 'PORTAL-CXTP-090'
        else _task_block(
            task_id=spec.task_id,
            title=spec.title,
            priority=spec.priority,
            track=spec.track,
            dependencies=spec.dependencies,
            outputs=spec.outputs,
            validations=spec.validations,
        )
        for spec in module.REQUIRED_TASKS
    ]
    taskboard.write_text('# Fixture Taskboard\n\n' + '\n'.join(blocks), encoding='utf-8')

    report = module.check_appended_tasks(taskboard, tmp_path)

    assert report['overall_status'] == 'pass'
    assert report['proof_acceptance_blocked'] is False
