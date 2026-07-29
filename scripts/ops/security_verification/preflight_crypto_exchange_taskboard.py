#!/usr/bin/env python3
"""Preflight checks for the crypto-exchange theorem-prover taskboard."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = 'crypto-exchange-taskboard-preflight/v1'
TASK_ID = 'PORTAL-CXTP-087'
DEFAULT_TASKBOARD = Path('docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md')
DEFAULT_STATE = Path('data/crypto_exchange_theorem_prover/state/cxtp_task_state.json')
DEFAULT_OUT = Path('security_ir_artifacts/recovery/taskboard-preflight-report.json')
PRODUCTION_BLOCKER_TASKS = {f'PORTAL-CXTP-{number:03d}' for number in range(77, 85)}
VALID_STATUSES = {'todo', 'ready', 'waiting', 'blocked', 'completed'}
TASK_RE = re.compile(r'^## (PORTAL-CXTP-\d{3})\s+(.+?)\s*$', re.MULTILINE)
FIELD_RE = re.compile(r'^- ([A-Za-z][A-Za-z ]+):\s*(.*?)\s*$', re.MULTILINE)


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    fields: dict[str, str]

    @property
    def status(self) -> str:
        return self.fields.get('Status', '').strip()

    @property
    def outputs(self) -> list[str]:
        raw = self.fields.get('Outputs', '').strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(',') if item.strip()]

    @property
    def completion_evidence(self) -> str:
        return self.fields.get('Completion evidence', '').strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def parse_taskboard(text: str) -> list[Task]:
    matches = list(TASK_RE.finditer(text))
    tasks: list[Task] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        fields = {field: value for field, value in FIELD_RE.findall(block)}
        tasks.append(Task(task_id=match.group(1), title=match.group(2).strip(), fields=fields))
    return tasks


def _path_exists(root: Path, value: str) -> bool:
    # Output fields in this taskboard are file paths.  Keep this intentionally
    # conservative; commands and URLs belong in Validation or evidence fields.
    if '://' in value:
        return True
    return (root / value).exists()


def _production_report_paths(root: Path) -> list[Path]:
    return [
        root / 'security_ir_artifacts/production/evidence-bundle-report.json',
        root / 'security_ir_artifacts/production/blocker-status-update-report.json',
    ]


def build_report(
    *,
    repo_root: Path | str | None = None,
    taskboard_path: Path | str = DEFAULT_TASKBOARD,
    state_path: Path | str = DEFAULT_STATE,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    taskboard_abs = Path(taskboard_path)
    state_abs = Path(state_path)
    if not taskboard_abs.is_absolute():
        taskboard_abs = root / taskboard_abs
    if not state_abs.is_absolute():
        state_abs = root / state_abs

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    taskboard_text = taskboard_abs.read_text(encoding='utf-8') if taskboard_abs.is_file() else ''
    tasks = parse_taskboard(taskboard_text)
    task_by_id = {task.task_id: task for task in tasks}

    if not taskboard_abs.is_file():
        blockers.append({'code': 'TASKBOARD_FILE_MISSING', 'path': _relative(root, taskboard_abs)})
    if not tasks:
        blockers.append({'code': 'TASKBOARD_HAS_NO_PARSEABLE_TASKS', 'path': _relative(root, taskboard_abs)})
    duplicate_ids = sorted({task.task_id for task in tasks if [item.task_id for item in tasks].count(task.task_id) > 1})
    for duplicate_id in duplicate_ids:
        blockers.append({'code': 'TASKBOARD_DUPLICATE_TASK_ID', 'task_id': duplicate_id})

    for task in tasks:
        if task.status not in VALID_STATUSES:
            blockers.append({'code': 'TASKBOARD_INVALID_STATUS', 'task_id': task.task_id, 'status': task.status})
        if task.status == 'completed' and not task.completion_evidence:
            warnings.append({'code': 'COMPLETED_TASK_MISSING_COMPLETION_EVIDENCE', 'task_id': task.task_id})
        if task.status == 'completed':
            for output in task.outputs:
                if not _path_exists(root, output):
                    blockers.append(
                        {
                            'code': 'COMPLETED_TASK_OUTPUT_MISSING',
                            'task_id': task.task_id,
                            'path': output,
                        }
                    )

    state = _load_json(state_abs)
    if state is None:
        warnings.append({'code': 'SUPERVISOR_STATE_MISSING_OR_MALFORMED', 'path': _relative(root, state_abs)})
    else:
        if state.get('task_count') != len(tasks):
            blockers.append(
                {
                    'code': 'SUPERVISOR_STATE_TASK_COUNT_MISMATCH',
                    'taskboard_count': len(tasks),
                    'state_count': state.get('task_count'),
                }
            )
        state_statuses = state.get('task_statuses')
        if isinstance(state_statuses, Mapping):
            for task_id, state_status in state_statuses.items():
                task = task_by_id.get(str(task_id))
                if task is None:
                    blockers.append({'code': 'SUPERVISOR_STATE_UNKNOWN_TASK_ID', 'task_id': task_id})
                elif task.status == 'completed' and state_status != 'completed':
                    blockers.append(
                        {
                            'code': 'SUPERVISOR_STATE_STATUS_CONTRADICTS_TASKBOARD',
                            'task_id': task_id,
                            'taskboard_status': task.status,
                            'state_status': state_status,
                        }
                    )
                elif state_status == 'completed' and task.status != 'completed':
                    blockers.append(
                        {
                            'code': 'SUPERVISOR_STATE_COMPLETED_STATUS_CONTRADICTS_TASKBOARD',
                            'task_id': task_id,
                            'taskboard_status': task.status,
                            'state_status': state_status,
                        }
                    )
        completed_ids = set(state.get('completed_task_ids') or [])
        for task_id in completed_ids:
            if task_by_id.get(str(task_id)) and task_by_id[str(task_id)].status != 'completed':
                blockers.append(
                    {
                        'code': 'SUPERVISOR_COMPLETED_ID_NOT_COMPLETED_IN_TASKBOARD',
                        'task_id': task_id,
                        'taskboard_status': task_by_id[str(task_id)].status,
                    }
                )

    incomplete_production_blockers = sorted(
        task_id
        for task_id in PRODUCTION_BLOCKER_TASKS
        if task_by_id.get(task_id) is None or task_by_id[task_id].status != 'completed'
    )
    production_reports: list[dict[str, Any]] = []
    for report_path in _production_report_paths(root):
        report_payload = _load_json(report_path)
        summary: dict[str, Any] = {
            'path': _relative(root, report_path),
            'exists': report_path.is_file(),
            'overall_status': report_payload.get('overall_status') if report_payload else None,
            'production_release_blocked': (
                report_payload.get('production_release_blocked') if report_payload else None
            ),
            'security_decision': report_payload.get('security_decision') if report_payload else None,
        }
        production_reports.append(summary)
        if report_payload and incomplete_production_blockers:
            decision = str(report_payload.get('security_decision') or '')
            release_blocked = report_payload.get('production_release_blocked')
            if release_blocked is False or (decision and not decision.startswith('BLOCK')):
                blockers.append(
                    {
                        'code': 'PRODUCTION_BLOCKERS_TREATED_AS_RELEASE_ACCEPTABLE',
                        'report': _relative(root, report_path),
                        'incomplete_production_blockers': incomplete_production_blockers,
                        'security_decision': decision,
                        'production_release_blocked': release_blocked,
                    }
                )

    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'taskboard': {
            'path': _relative(root, taskboard_abs),
            'exists': taskboard_abs.is_file(),
            'task_count': len(tasks),
            'status_counts': status_counts,
        },
        'supervisor_state': {
            'path': _relative(root, state_abs),
            'exists': state_abs.is_file(),
            'task_count': state.get('task_count') if state else None,
            'active_task_id': state.get('active_task_id') if state else None,
        },
        'production_blocker_policy': {
            'required_blocker_tasks': sorted(PRODUCTION_BLOCKER_TASKS),
            'incomplete_production_blockers': incomplete_production_blockers,
            'production_reports': production_reports,
        },
        'blockers': blockers,
        'warnings': warnings,
        'blocker_count': len(blockers),
        'warning_count': len(warnings),
        'overall_status': 'blocked' if blockers else 'ready',
        'security_decision': 'BLOCK_TASKBOARD_PREFLIGHT' if blockers else 'TASKBOARD_PREFLIGHT_READY',
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Preflight crypto-exchange theorem-prover taskboard integrity.')
    parser.add_argument('--taskboard', default=str(DEFAULT_TASKBOARD))
    parser.add_argument('--state', default=str(DEFAULT_STATE))
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    parser.add_argument('--repo-root', default='.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    report = build_report(repo_root=root, taskboard_path=args.taskboard, state_path=args.state)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    _write_json(report, out_path)
    print(
        json.dumps(
            {
                'overall_status': report['overall_status'],
                'blocker_count': report['blocker_count'],
                'warning_count': report['warning_count'],
                'task_count': report['taskboard']['task_count'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 1 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
