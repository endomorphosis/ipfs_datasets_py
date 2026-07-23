#!/usr/bin/env python3
"""Guard appended CXTP solver and production-unblocker tasks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA_VERSION = 'appended-cxtp-task-retention/v1'
TASK_ID = 'PORTAL-CXTP-096'
DEFAULT_TASKBOARD = Path('docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md')
DEFAULT_OUT = Path('security_ir_artifacts/recovery/appended-task-retention-report.json')
APPENDED_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(90, 98)]
REQUIRED_FIELDS = ['Status', 'Completion', 'Priority', 'Track', 'Depends on', 'Outputs', 'Validation', 'Acceptance']
VALID_STATUSES = {'todo', 'ready', 'waiting', 'blocked', 'completed'}
TASK_RE = re.compile(r'^## (PORTAL-CXTP-\d{3})\s+(.+?)\s*$', re.MULTILINE)
FIELD_RE = re.compile(r'^- ([A-Za-z][A-Za-z ]+):[ \t]*(.*?)[ \t]*$', re.MULTILINE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _write_json(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_taskboard(text: str) -> dict[str, dict[str, Any]]:
    matches = list(TASK_RE.finditer(text))
    tasks: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        tasks[match.group(1)] = {
            'task_id': match.group(1),
            'title': match.group(2).strip(),
            'fields': {field: value for field, value in FIELD_RE.findall(block)},
        }
    return tasks


def build_report(
    *,
    repo_root: Path | str | None = None,
    taskboard_path: Path | str = DEFAULT_TASKBOARD,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    taskboard_abs = Path(taskboard_path)
    if not taskboard_abs.is_absolute():
        taskboard_abs = root / taskboard_abs

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    text = taskboard_abs.read_text(encoding='utf-8') if taskboard_abs.is_file() else ''
    tasks = parse_taskboard(text)

    if not taskboard_abs.is_file():
        blockers.append({'code': 'TASKBOARD_FILE_MISSING', 'path': _relative(root, taskboard_abs)})

    retained: list[dict[str, Any]] = []
    for task_id in APPENDED_TASK_IDS:
        task = tasks.get(task_id)
        if task is None:
            blockers.append({'code': 'APPENDED_TASK_MISSING', 'task_id': task_id})
            continue
        fields = task['fields']
        missing_fields = [field for field in REQUIRED_FIELDS if not str(fields.get(field, '')).strip()]
        if missing_fields:
            blockers.append({'code': 'APPENDED_TASK_METADATA_MISSING', 'task_id': task_id, 'fields': missing_fields})
        status = str(fields.get('Status', '')).strip()
        if status not in VALID_STATUSES:
            blockers.append({'code': 'APPENDED_TASK_INVALID_STATUS', 'task_id': task_id, 'status': status})
        if status == 'completed' and not str(fields.get('Completion evidence', '')).strip():
            blockers.append({'code': 'APPENDED_TASK_COMPLETED_WITHOUT_EVIDENCE', 'task_id': task_id})
        retained.append(
            {
                'task_id': task_id,
                'title': task['title'],
                'status': status,
                'priority': fields.get('Priority'),
                'track': fields.get('Track'),
                'depends_on': [item.strip() for item in str(fields.get('Depends on', '')).split(',') if item.strip()],
                'has_outputs': bool(str(fields.get('Outputs', '')).strip()),
                'has_validation': bool(str(fields.get('Validation', '')).strip()),
                'has_acceptance': bool(str(fields.get('Acceptance', '')).strip()),
                'has_completion_evidence': bool(str(fields.get('Completion evidence', '')).strip()),
            }
        )

    # Dependency guards that keep appended lanes chained to the unblocker/reporting tasks.
    dependency_expectations = {
        'PORTAL-CXTP-090': {'PORTAL-CXTP-086'},
        'PORTAL-CXTP-091': {'PORTAL-CXTP-086'},
        'PORTAL-CXTP-092': {'PORTAL-CXTP-086'},
        'PORTAL-CXTP-093': {'PORTAL-CXTP-086'},
        'PORTAL-CXTP-094': {'PORTAL-CXTP-085'},
        'PORTAL-CXTP-095': {'PORTAL-CXTP-094'},
        'PORTAL-CXTP-097': {'PORTAL-CXTP-096'},
    }
    for task_info in retained:
        expected = dependency_expectations.get(task_info['task_id'], set())
        actual = set(task_info['depends_on'])
        missing = sorted(expected - actual)
        if missing:
            blockers.append(
                {
                    'code': 'APPENDED_TASK_REQUIRED_DEPENDENCY_MISSING',
                    'task_id': task_info['task_id'],
                    'missing_dependencies': missing,
                }
            )

    if len(retained) != len(APPENDED_TASK_IDS):
        warnings.append(
            {
                'code': 'APPENDED_TASK_RETAINED_COUNT_MISMATCH',
                'expected_count': len(APPENDED_TASK_IDS),
                'retained_count': len(retained),
            }
        )

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'taskboard': {
            'path': _relative(root, taskboard_abs),
            'exists': taskboard_abs.is_file(),
        },
        'required_task_ids': APPENDED_TASK_IDS,
        'retained_tasks': retained,
        'retained_count': len(retained),
        'blockers': blockers,
        'warnings': warnings,
        'blocker_count': len(blockers),
        'warning_count': len(warnings),
        'overall_status': 'blocked' if blockers else 'ready',
        'security_decision': 'BLOCK_APPENDED_TASK_RETENTION' if blockers else 'APPENDED_TASK_RETENTION_READY',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Check appended CXTP task retention.')
    parser.add_argument('--taskboard', default=str(DEFAULT_TASKBOARD))
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    parser.add_argument('--repo-root', default='.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    report = build_report(repo_root=root, taskboard_path=args.taskboard)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    _write_json(report, out_path)
    print(
        json.dumps(
            {
                'overall_status': report['overall_status'],
                'blocker_count': report['blocker_count'],
                'retained_count': report['retained_count'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 1 if report['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
