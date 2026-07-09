#!/usr/bin/env python3
"""Fail-closed retention check for appended PORTAL-CXTP unblocker tasks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


SCHEMA_VERSION = 'crypto-exchange-appended-task-retention/v1'
TASK_ID = 'PORTAL-CXTP-096'
DEFAULT_TASKBOARD = Path('docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md')
DEFAULT_OUT = Path('security_ir_artifacts/recovery/appended-task-retention-report.json')

COMPLETED_STATUSES = {'complete', 'completed', 'done'}
EVIDENCE_FIELD_NAMES = {
    'completion evidence',
    'completed evidence',
    'completion proof',
    'evidence',
    'verification evidence',
}
PLACEHOLDER_EVIDENCE = {'', 'none', 'n/a', 'na', 'todo', 'pending', 'missing', 'tbd'}


@dataclass(frozen=True)
class AppendedTaskSpec:
    task_id: str
    title: str
    priority: str
    track: str
    dependencies: tuple[str, ...]
    outputs: tuple[str, ...]
    validations: tuple[str, ...]


REQUIRED_TASKS: tuple[AppendedTaskSpec, ...] = (
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-090',
        title='Remediate Lean optional proof-consumer solver lane',
        priority='P1',
        track='solver',
        dependencies=('PORTAL-CXTP-058', 'PORTAL-CXTP-086', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/lean_proof_consumer_solver_lane.md',
            'scripts/ops/security_verification/probe_lean_solver_lane.py',
            'security_ir_artifacts/environment/lean-solver-lane-report.json',
            'tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_lean_solver_lane.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_lean_solver_lane.py --out security_ir_artifacts/environment/lean-solver-lane-report.json',
        ),
    ),
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-091',
        title='Provision Apalache TLA model-checker lane',
        priority='P1',
        track='solver',
        dependencies=('PORTAL-CXTP-058', 'PORTAL-CXTP-086', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/apalache_tla_solver_lane.md',
            'scripts/ops/security_verification/probe_apalache_solver_lane.py',
            'security_ir_artifacts/environment/apalache-solver-lane-report.json',
            'tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_apalache_solver_lane.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_apalache_solver_lane.py --out security_ir_artifacts/environment/apalache-solver-lane-report.json',
        ),
    ),
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-092',
        title='Provision Tamarin and ProVerif protocol solver lanes',
        priority='P1',
        track='solver',
        dependencies=('PORTAL-CXTP-058', 'PORTAL-CXTP-086', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/protocol_solver_lanes.md',
            'scripts/ops/security_verification/probe_protocol_solver_lanes.py',
            'security_ir_artifacts/environment/protocol-solver-lane-report.json',
            'tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_protocol_solver_lanes.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_protocol_solver_lanes.py --out security_ir_artifacts/environment/protocol-solver-lane-report.json',
        ),
    ),
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-093',
        title='Provision Coq proof-kernel solver lane',
        priority='P1',
        track='solver',
        dependencies=('PORTAL-CXTP-058', 'PORTAL-CXTP-086', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/coq_proof_kernel_solver_lane.md',
            'scripts/ops/security_verification/probe_coq_solver_lane.py',
            'security_ir_artifacts/environment/coq-solver-lane-report.json',
            'tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_coq_solver_lane.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/probe_coq_solver_lane.py --out security_ir_artifacts/environment/coq-solver-lane-report.json',
        ),
    ),
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-094',
        title='Generate production evidence packets for each remaining blocker',
        priority='P0',
        track='ops',
        dependencies=('PORTAL-CXTP-077', 'PORTAL-CXTP-078', 'PORTAL-CXTP-085', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/production_blocker_evidence_packets.md',
            'scripts/ops/security_verification/generate_production_blocker_packets.py',
            'security_ir_artifacts/production/blocker-packets.json',
            'tests/logic/security_models/crypto_exchange/test_production_blocker_packets.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_packets.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/generate_production_blocker_packets.py --out security_ir_artifacts/production/blocker-packets.json',
        ),
    ),
    AppendedTaskSpec(
        task_id='PORTAL-CXTP-095',
        title='Build guarded production blocker status updater',
        priority='P0',
        track='ops',
        dependencies=('PORTAL-CXTP-085', 'PORTAL-CXTP-094', 'PORTAL-CXTP-096'),
        outputs=(
            'docs/security_verification/production_blocker_status_updater.md',
            'scripts/ops/security_verification/update_production_blocker_status.py',
            'security_ir_artifacts/production/blocker-status-update-report.json',
            'tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py',
        ),
        validations=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_production_blocker_status_updater.py -q',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/update_production_blocker_status.py --dry-run --packets security_ir_artifacts/production/blocker-packets.json --out security_ir_artifacts/production/blocker-status-update-report.json',
        ),
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(',') if part.strip()]


def _split_validation(value: str) -> list[str]:
    return [part.strip() for part in value.split(';') if part.strip()]


def _parse_taskboard(text: str) -> dict[str, dict[str, Any]]:
    heading_pattern = re.compile(r'^##\s+(PORTAL-CXTP-\d{3})\s+(.+?)\s*$', re.MULTILINE)
    matches = list(heading_pattern.finditer(text))
    tasks: dict[str, dict[str, Any]] = {}

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        fields: dict[str, list[str]] = {}
        for line in block.splitlines():
            field_match = re.match(r'^\s*-\s*([^:]+):\s*(.*?)\s*$', line)
            if not field_match:
                continue
            key = field_match.group(1).strip().lower()
            value = field_match.group(2).strip()
            fields.setdefault(key, []).append(value)

        task_id = match.group(1)
        tasks[task_id] = {
            'task_id': task_id,
            'title': match.group(2).strip(),
            'line_start': text.count('\n', 0, match.start()) + 1,
            'block': block,
            'fields': fields,
        }
    return tasks


def _field_value(task: dict[str, Any], key: str) -> str:
    values = task.get('fields', {}).get(key.lower(), [])
    return values[0] if values else ''


def _field_values(task: dict[str, Any], key: str) -> list[str]:
    return list(task.get('fields', {}).get(key.lower(), []))


def _completion_evidence(task: dict[str, Any]) -> list[str]:
    fields = task.get('fields', {})
    evidence: list[str] = []
    for key, values in fields.items():
        if key in EVIDENCE_FIELD_NAMES:
            evidence.extend(values)
    return evidence


def _has_substantial_completion_evidence(
    task: dict[str, Any],
    spec: AppendedTaskSpec,
    repo_root: Path,
) -> tuple[bool, list[dict[str, Any]]]:
    evidence_values = [value.strip() for value in _completion_evidence(task)]
    errors: list[dict[str, Any]] = []
    usable_evidence = [
        value
        for value in evidence_values
        if value.strip().lower() not in PLACEHOLDER_EVIDENCE
    ]
    if not usable_evidence:
        errors.append({'code': 'COMPLETION_EVIDENCE_FIELD_MISSING'})

    evidence_text = '\n'.join(usable_evidence)
    referenced_output = any(output in evidence_text for output in spec.outputs)
    referenced_validation = any(validation in evidence_text for validation in spec.validations)
    if usable_evidence and not referenced_output and not referenced_validation:
        errors.append(
            {
                'code': 'COMPLETION_EVIDENCE_DOES_NOT_REFERENCE_OUTPUT_OR_VALIDATION',
                'required_reference_examples': [spec.outputs[0], spec.validations[0]],
            }
        )

    missing_outputs = [output for output in spec.outputs if not (repo_root / output).is_file()]
    if missing_outputs:
        errors.append({'code': 'COMPLETED_TASK_OUTPUTS_MISSING', 'paths': missing_outputs})

    return not errors, errors


def _task_blockers(task: dict[str, Any], spec: AppendedTaskSpec, repo_root: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []

    if task.get('title') != spec.title:
        blockers.append(
            {
                'code': 'APPENDED_TASK_TITLE_CHANGED',
                'task_id': spec.task_id,
                'expected': spec.title,
                'actual': task.get('title'),
            }
        )

    for field, expected in (('priority', spec.priority), ('track', spec.track)):
        actual = _field_value(task, field)
        if actual != expected:
            blockers.append(
                {
                    'code': 'APPENDED_TASK_FIELD_CHANGED',
                    'task_id': spec.task_id,
                    'field': field,
                    'expected': expected,
                    'actual': actual,
                }
            )

    actual_dependencies = _split_csv(_field_value(task, 'depends on'))
    missing_dependencies = [dep for dep in spec.dependencies if dep not in actual_dependencies]
    if missing_dependencies:
        blockers.append(
            {
                'code': 'APPENDED_TASK_DEPENDENCIES_MISSING',
                'task_id': spec.task_id,
                'missing_dependencies': missing_dependencies,
                'actual_dependencies': actual_dependencies,
            }
        )

    actual_outputs = _split_csv(_field_value(task, 'outputs'))
    missing_outputs = [output for output in spec.outputs if output not in actual_outputs]
    if missing_outputs:
        blockers.append(
            {
                'code': 'APPENDED_TASK_OUTPUTS_MISSING',
                'task_id': spec.task_id,
                'missing_outputs': missing_outputs,
                'actual_outputs': actual_outputs,
            }
        )

    validation_values: list[str] = []
    for value in _field_values(task, 'validation'):
        validation_values.extend(_split_validation(value))
    missing_validations = [validation for validation in spec.validations if validation not in validation_values]
    if missing_validations:
        blockers.append(
            {
                'code': 'APPENDED_TASK_VALIDATION_COMMANDS_MISSING',
                'task_id': spec.task_id,
                'missing_validations': missing_validations,
                'actual_validations': validation_values,
            }
        )

    status = _field_value(task, 'status').strip().lower()
    if status in COMPLETED_STATUSES:
        evidence_ok, evidence_errors = _has_substantial_completion_evidence(task, spec, repo_root)
        if not evidence_ok:
            blockers.append(
                {
                    'code': 'APPENDED_TASK_COMPLETED_WITHOUT_EVIDENCE',
                    'task_id': spec.task_id,
                    'status': status,
                    'errors': evidence_errors,
                }
            )

    return blockers


def _restoration_instructions(blockers: Iterable[dict[str, Any]], taskboard: str) -> list[str]:
    affected_tasks = sorted(
        {
            str(blocker.get('task_id'))
            for blocker in blockers
            if blocker.get('task_id')
        }
    )
    instructions = [
        'Do not run appended solver or production unblocker tasks while this report is blocked.',
        f'Restore {taskboard} from reviewed durable history or the latest supervisor archive.',
        (
            'The protected appended range is PORTAL-CXTP-090 through PORTAL-CXTP-095; '
            'each task must keep its dependencies, outputs, and validation commands.'
        ),
        (
            'If a protected task is intentionally completed, add concrete completion evidence '
            'that references the produced output or validation command, and keep all declared '
            'outputs present in the checkout.'
        ),
        (
            'Rerun: PYTHONPATH=. /home/barberb/miniforge3/bin/python '
            'scripts/ops/security_verification/check_appended_cxtp_tasks.py '
            f'--taskboard {taskboard} --out {DEFAULT_OUT.as_posix()}'
        ),
    ]
    if affected_tasks:
        instructions.append(f'Affected protected task ids: {", ".join(affected_tasks)}')
    return instructions


def check_appended_tasks(
    taskboard_path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    taskboard = Path(taskboard_path) if taskboard_path is not None else DEFAULT_TASKBOARD
    if not taskboard.is_absolute():
        taskboard = root / taskboard
    taskboard_rel = _relative(taskboard, root)

    blockers: list[dict[str, Any]] = []
    task_results: list[dict[str, Any]] = []

    if not taskboard.is_file():
        blockers.append({'code': 'APPENDED_TASKBOARD_MISSING', 'path': taskboard_rel})
        parsed_tasks: dict[str, dict[str, Any]] = {}
    else:
        try:
            parsed_tasks = _parse_taskboard(taskboard.read_text(encoding='utf-8'))
        except UnicodeDecodeError as exc:
            parsed_tasks = {}
            blockers.append({'code': 'APPENDED_TASKBOARD_NOT_UTF8', 'path': taskboard_rel, 'error': str(exc)})

    for spec in REQUIRED_TASKS:
        task = parsed_tasks.get(spec.task_id)
        if task is None:
            blockers.append(
                {
                    'code': 'APPENDED_TASK_MISSING',
                    'task_id': spec.task_id,
                    'title': spec.title,
                    'required_range': 'PORTAL-CXTP-090..PORTAL-CXTP-095',
                }
            )
            task_results.append(
                {
                    'task_id': spec.task_id,
                    'title': spec.title,
                    'status': 'missing',
                    'present': False,
                    'blocker_count': 1,
                }
            )
            continue

        task_blockers = _task_blockers(task, spec, root)
        blockers.extend(task_blockers)
        task_results.append(
            {
                'task_id': spec.task_id,
                'title': task.get('title'),
                'line_start': task.get('line_start'),
                'status': _field_value(task, 'status') or '<missing>',
                'present': True,
                'priority': _field_value(task, 'priority') or '<missing>',
                'track': _field_value(task, 'track') or '<missing>',
                'dependency_count': len(_split_csv(_field_value(task, 'depends on'))),
                'output_count': len(_split_csv(_field_value(task, 'outputs'))),
                'validation_count': sum(
                    len(_split_validation(value)) for value in _field_values(task, 'validation')
                ),
                'completion_evidence_count': len(_completion_evidence(task)),
                'blocker_count': len(task_blockers),
                'status_detail': 'blocked' if task_blockers else 'pass',
            }
        )

    blocked = bool(blockers)
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'checked_at_utc': _utc_now(),
        'taskboard': taskboard_rel,
        'overall_status': 'blocked' if blocked else 'pass',
        'downstream_task_gate': 'blocked' if blocked else 'allowed',
        'proof_acceptance_blocked': blocked,
        'security_decision': (
            'BLOCK_APPENDED_CXTP_TASK_RETENTION'
            if blocked
            else 'APPENDED_CXTP_TASKS_RETAINED'
        ),
        'summary': {
            'protected_task_count': len(REQUIRED_TASKS),
            'present_task_count': sum(1 for result in task_results if result['present']),
            'blocker_count': len(blockers),
            'completed_task_count': sum(
                1
                for result in task_results
                if str(result.get('status', '')).strip().lower() in COMPLETED_STATUSES
            ),
        },
        'protected_range': {
            'first_task_id': 'PORTAL-CXTP-090',
            'last_task_id': 'PORTAL-CXTP-095',
            'required_reason': (
                'solver-lane and production-unblocker tasks were appended after the original '
                'taskboard and must survive supervisor cleanup'
            ),
        },
        'tasks': task_results,
        'blockers': blockers,
        'restoration_instructions': _restoration_instructions(blockers, taskboard_rel) if blocked else [],
        'runbook': 'docs/security_verification/appended_task_retention_runbook.md',
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Check retention of appended PORTAL-CXTP solver and production unblocker tasks.'
    )
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root to inspect')
    parser.add_argument(
        '--taskboard',
        default=DEFAULT_TASKBOARD.as_posix(),
        help='taskboard markdown file to inspect',
    )
    parser.add_argument(
        '--out',
        default=DEFAULT_OUT.as_posix(),
        help='JSON report path to write',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    report = check_appended_tasks(args.taskboard, repo_root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    write_json(report, out_path)
    print(json.dumps({'report': _relative(out_path, repo_root), 'status': report['overall_status']}))
    return 2 if report['proof_acceptance_blocked'] else 0


if __name__ == '__main__':
    sys.exit(main())
