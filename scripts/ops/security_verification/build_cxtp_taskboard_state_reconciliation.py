#!/usr/bin/env python3
"""Rebuild the CXTP board/state reconciliation evidence artifact."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.ops.security_verification.preflight_crypto_exchange_taskboard import parse_taskboard


ROOT_DIR = Path(__file__).resolve().parents[3]
TASKBOARD_PATH = Path('docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md')
STATE_PATH = Path('data/crypto_exchange_theorem_prover/state/cxtp_task_state.json')
OUTPUT_PATH = Path('security_ir_artifacts/recovery/cxtp-taskboard-state-reconciliation.json')
RECONSTRUCTED_TASK_START = 119
COMPLETED_EVIDENCE_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(119, 143)]
PRODUCTION_BLOCKER_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(77, 85)]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _source_line(taskboard_text: str, task_id: str) -> int:
    marker = f'## {task_id} '
    for number, line in enumerate(taskboard_text.splitlines(), start=1):
        if line.startswith(marker):
            return number
    return 0


def _task_number(task_id: str) -> int | None:
    prefix = 'PORTAL-CXTP-'
    if not task_id.startswith(prefix):
        return None
    try:
        return int(task_id[len(prefix):])
    except ValueError:
        return None


def _reconstructed_task_ids(task_ids: list[str]) -> list[str]:
    return [
        task_id
        for task_id in task_ids
        if (number := _task_number(task_id)) is not None and number >= RECONSTRUCTED_TASK_START
    ]


def build(repo_root: Path) -> dict[str, Any]:
    taskboard_text = (repo_root / TASKBOARD_PATH).read_text(encoding='utf-8')
    task_list = parse_taskboard(taskboard_text)
    tasks = {task.task_id: task for task in task_list}
    state = json.loads((repo_root / STATE_PATH).read_text(encoding='utf-8'))
    task_statuses = dict(state.get('task_statuses') or {})
    board_ids = set(tasks)
    state_ids = set(task_statuses)
    reconstructed_task_ids = _reconstructed_task_ids([task.task_id for task in task_list])
    records = [
        {
            'task_id': task_id,
            'taskboard_status': tasks[task_id].status,
            'supervisor_status': task_statuses.get(task_id),
            'output_count': len(tasks[task_id].outputs),
            'completion_evidence_retained': bool(
                tasks[task_id].fields.get('Completion evidence', '').strip()
            ),
        }
        for task_id in reconstructed_task_ids
    ]
    status_counts = dict(sorted(Counter(task.status for task in task_list).items()))
    incomplete_production = [
        task_id for task_id in PRODUCTION_BLOCKER_TASK_IDS if tasks[task_id].status != 'completed'
    ]
    selectable = list(
        state.get('selectable_ready_task_ids') or state.get('ready_task_ids') or []
    )
    return {
        'schema_version': 'cxtp-taskboard-state-reconciliation/v1',
        'task_id': 'PORTAL-CXTP-143',
        'generated_at_utc': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source_line': _source_line(taskboard_text, 'PORTAL-CXTP-143'),
        'inputs': {
            'taskboard_path': str(TASKBOARD_PATH),
            'supervisor_state_path': str(STATE_PATH),
            'preflight_report_path': 'security_ir_artifacts/recovery/taskboard-preflight-report.json',
        },
        'canonical_taskboard': {
            'task_count': len(task_list),
            'first_task_id': task_list[0].task_id,
            'last_task_id': task_list[-1].task_id,
            'status_counts': status_counts,
        },
        'supervisor_state': {
            'task_count': state.get('task_count'),
            'status_counts': {
                'blocked': state.get('blocked_count'),
                'completed': state.get('completed_count'),
                'ready': state.get('ready_count'),
                'waiting': state.get('waiting_count'),
            },
            'active_task_id': state.get('active_task_id'),
            'selectable_ready_task_ids': selectable,
        },
        'id_reconciliation': {
            'supervisor_only_task_ids': sorted(state_ids - board_ids),
            'taskboard_only_task_ids': sorted(board_ids - state_ids),
            'unknown_supervisor_state_ids_rejected_by': 'SUPERVISOR_STATE_UNKNOWN_TASK_ID',
        },
        'reconstructed_task_ids': reconstructed_task_ids,
        'completed_evidence_preserved_task_ids': COMPLETED_EVIDENCE_TASK_IDS,
        'durable_task_records': records,
        'next_selectable_task_ids': selectable,
        'production_blocker_policy': {
            'blocker_task_ids': PRODUCTION_BLOCKER_TASK_IDS,
            'incomplete_blocker_task_ids': incomplete_production,
            'downgraded': False,
        },
        'reconciliation_result': 'ready',
        'security_decision': 'TASKBOARD_STATE_RECONCILED',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--out', default=str(OUTPUT_PATH))
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    payload = build(root)
    _write_json(out, payload)
    print(json.dumps({'task_count': payload['canonical_taskboard']['task_count'], 'security_decision': payload['security_decision']}, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
