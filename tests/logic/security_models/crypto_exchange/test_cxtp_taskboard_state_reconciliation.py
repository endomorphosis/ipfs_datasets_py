import importlib.util
from collections import Counter
import copy
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
TASKBOARD_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'crypto_exchange_theorem_prover_taskboard.todo.md'
STATE_PATH = REPO_ROOT / 'data' / 'crypto_exchange_theorem_prover' / 'state' / 'cxtp_task_state.json'
RECONCILIATION_PATH = (
    REPO_ROOT / 'security_ir_artifacts' / 'recovery' / 'cxtp-taskboard-state-reconciliation.json'
)
PREFLIGHT_SCRIPT_PATH = (
    REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'preflight_crypto_exchange_taskboard.py'
)

RECONSTRUCTED_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(119, 156)]
COMPLETED_EVIDENCE_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(119, 143)]
PRODUCTION_BLOCKER_TASK_IDS = [f'PORTAL-CXTP-{number:03d}' for number in range(77, 85)]


def _load_preflight_module() -> Any:
    spec = importlib.util.spec_from_file_location('preflight_crypto_exchange_taskboard', PREFLIGHT_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_board_tasks() -> dict[str, Any]:
    module = _load_preflight_module()
    tasks = module.parse_taskboard(TASKBOARD_PATH.read_text(encoding='utf-8'))
    return {task.task_id: task for task in tasks}


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        tasks = _load_board_tasks()
        status_counts = Counter(task.status for task in tasks.values())
        return {
            'task_count': len(tasks),
            'task_statuses': {task_id: task.status for task_id, task in tasks.items()},
            'task_artifacts': {
                task_id: tasks[task_id].outputs
                for task_id in COMPLETED_EVIDENCE_TASK_IDS
                if task_id in tasks
            },
            'blocked_count': status_counts['blocked'],
            'completed_count': status_counts['completed'],
            'ready_count': status_counts['ready'],
            'waiting_count': status_counts['waiting'],
            'selectable_ready_task_ids': [
                task_id for task_id, task in sorted(tasks.items()) if task.status == 'ready'
            ],
        }
    return json.loads(STATE_PATH.read_text(encoding='utf-8'))


def _load_reconciliation() -> dict[str, Any]:
    return json.loads(RECONCILIATION_PATH.read_text(encoding='utf-8'))


def test_reconciliation_artifact_matches_canonical_board_and_supervisor_state() -> None:
    tasks = _load_board_tasks()
    state = _load_state()
    artifact = _load_reconciliation()

    task_statuses = {task_id: task.status for task_id, task in tasks.items()}

    assert artifact['schema_version'] == 'cxtp-taskboard-state-reconciliation/v1'
    assert artifact['task_id'] == 'PORTAL-CXTP-143'
    assert artifact['reconciliation_result'] == 'ready'
    assert artifact['security_decision'] == 'TASKBOARD_STATE_RECONCILED'
    assert artifact['canonical_taskboard']['task_count'] == len(tasks) == state['task_count']
    assert artifact['supervisor_state']['task_count'] == state['task_count']
    assert artifact['canonical_taskboard']['status_counts'] == dict(sorted(Counter(task_statuses.values()).items()))
    assert artifact['supervisor_state']['status_counts'] == {
        'blocked': state['blocked_count'],
        'completed': state['completed_count'],
        'ready': state['ready_count'],
        'waiting': state['waiting_count'],
    }
    assert artifact['id_reconciliation']['supervisor_only_task_ids'] == []
    assert artifact['id_reconciliation']['taskboard_only_task_ids'] == []
    assert set(state['task_statuses']) == set(tasks)


def test_reconstructed_records_are_present_and_status_aligned() -> None:
    tasks = _load_board_tasks()
    state = _load_state()
    artifact = _load_reconciliation()
    records = {record['task_id']: record for record in artifact['durable_task_records']}

    assert artifact['reconstructed_task_ids'] == RECONSTRUCTED_TASK_IDS
    assert sorted(records) == RECONSTRUCTED_TASK_IDS

    for task_id in RECONSTRUCTED_TASK_IDS:
        task = tasks[task_id]
        record = records[task_id]
        assert record['taskboard_status'] == task.status
        assert record['supervisor_status'] == state['task_statuses'][task_id]
        assert record['taskboard_status'] == record['supervisor_status']
        assert record['output_count'] == len(task.outputs)


def test_completed_xaman_evidence_survived_reconciliation() -> None:
    tasks = _load_board_tasks()
    state = _load_state()
    artifact = _load_reconciliation()
    records = {record['task_id']: record for record in artifact['durable_task_records']}

    assert artifact['completed_evidence_preserved_task_ids'] == COMPLETED_EVIDENCE_TASK_IDS

    for task_id in COMPLETED_EVIDENCE_TASK_IDS:
        task = tasks[task_id]
        assert task.status == 'completed'
        assert state['task_statuses'][task_id] == 'completed'
        assert task.completion_evidence
        assert task.outputs == state['task_artifacts'][task_id]
        assert records[task_id]['completion_evidence_retained'] is True


def test_empty_depends_on_does_not_consume_outputs_field() -> None:
    tasks = _load_board_tasks()
    task = tasks['PORTAL-CXTP-143']

    assert task.fields['Depends on'] == ''
    assert task.outputs == [
        'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
        'security_ir_artifacts/recovery/cxtp-taskboard-state-reconciliation.json',
        'docs/security_verification/cxtp_taskboard_state_reconciliation.md',
        'tests/logic/security_models/crypto_exchange/test_cxtp_taskboard_state_reconciliation.py',
    ]


def test_unknown_supervisor_state_ids_are_rejected(tmp_path: Path) -> None:
    module = _load_preflight_module()
    state = copy.deepcopy(_load_state())
    state['task_statuses']['PORTAL-CXTP-999'] = 'ready'
    state['ready_task_ids'] = list(state.get('ready_task_ids', [])) + ['PORTAL-CXTP-999']
    unknown_state_path = tmp_path / 'state-with-unknown-id.json'
    unknown_state_path.write_text(json.dumps(state), encoding='utf-8')

    report = module.build_report(
        repo_root=REPO_ROOT,
        taskboard_path=TASKBOARD_PATH,
        state_path=unknown_state_path,
        generated_at_utc='2026-07-11T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert any(
        blocker['code'] == 'SUPERVISOR_STATE_UNKNOWN_TASK_ID'
        and blocker['task_id'] == 'PORTAL-CXTP-999'
        for blocker in report['blockers']
    )


def test_next_task_and_production_blockers_remain_fail_closed() -> None:
    tasks = _load_board_tasks()
    state = _load_state()
    artifact = _load_reconciliation()

    selectable = state.get('selectable_ready_task_ids', state.get('ready_task_ids', []))
    assert artifact['next_selectable_task_ids'] == selectable == []
    assert tasks['PORTAL-CXTP-143'].status == 'completed'

    assert artifact['production_blocker_policy']['downgraded'] is False
    assert artifact['production_blocker_policy']['blocker_task_ids'] == PRODUCTION_BLOCKER_TASK_IDS
    assert artifact['production_blocker_policy']['incomplete_blocker_task_ids'] == PRODUCTION_BLOCKER_TASK_IDS
    for task_id in PRODUCTION_BLOCKER_TASK_IDS:
        assert tasks[task_id].status == 'blocked'
