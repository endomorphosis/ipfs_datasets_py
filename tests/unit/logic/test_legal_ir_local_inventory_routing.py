"""A routing update must preserve completed authority and existing acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'scripts/ops/legal_ir/legal_ir_supervisor_contract.py'
SPEC = importlib.util.spec_from_file_location('local_inventory_routing_owner', SOURCE)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
LIVE = ROOT


def blocks(text):
    result = {}
    for block in re.split(r'(?=^## )', text, flags=re.MULTILINE):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', block)
        if match:
            result[match[1]] = block
    return result


@pytest.fixture
def board(tmp_path):
    for relative in [contract.PLAN, contract.BOARD, contract.CONSTITUTION]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LIVE / relative, target)
    # Exercise the historical conversion API on an isolated pre-programme board.
    # The adopted139 snapshot intentionally refuses enrichment in production.
    plan_path = tmp_path / contract.PLAN
    plan = json.loads(plan_path.read_text())
    plan.pop('programme_engineering', None)
    plan['tasks'] = [task for task in plan['tasks'] if task.get('programme_engineering') is None]
    pending = next(task['task_id'] for task in plan['tasks']
                   if contract.kind(task['task_id']) == 'uscode' and not task.get('local_inventory'))
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    chunks = []
    for chunk in re.split(r'(?=^## )', (tmp_path / contract.BOARD).read_text(), flags=re.MULTILINE):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if match and match[1] in contract.PROGRAMME_ENGINEERING_SPECS:
            continue
        if match and match[1] == pending:
            chunk = re.sub(r'(?mi)^- status:.*$', '- status: todo', chunk)
        chunks.append(chunk)
    (tmp_path / contract.BOARD).write_text(''.join(chunks).rstrip() + '\n')
    return tmp_path


def test_enable_preserves_every_completed_and_unrelated_contract(board):
    original_blocks = blocks((board / contract.BOARD).read_text())
    original_plan = json.loads((board / contract.PLAN).read_text())
    statuses = {key: re.findall(r'(?mi)^- status: (.*)$', value)[-1]
                for key, value in original_blocks.items()}
    selected = {key for key, value in statuses.items()
                if value.lower() in {'todo', 'ready'} and contract.kind(key) == 'uscode'}
    result = contract.enrich(board, enable_local_inventory=True)
    assert result['local_inventory_enabled_count'] == len(selected)
    after = blocks((board / contract.BOARD).read_text())
    assert set(after) == set(original_blocks)
    for key in set(after) - selected:
        assert after[key] == original_blocks[key], key
    updated_plan = json.loads((board / contract.PLAN).read_text())
    assert len(updated_plan['tasks']) == len(original_plan['tasks'])
    for before, current in zip(original_plan['tasks'], updated_plan['tasks'], strict=True):
        if before['task_id'] not in selected:
            assert current == before
    for key in selected:
        assert re.findall(r'(?mi)^- status: (.*)$', after[key])[-1] == statuses[key]
        assert '- provider role: deterministic-only\n' in after[key]
    assert contract.check_board(board)['task_count'] == len(original_plan['tasks'])
    # Re-running a reviewed conversion does not alter canonical task metadata.
    prior_board = (board / contract.BOARD).read_bytes()
    prior_plan = (board / contract.PLAN).read_bytes()
    contract.enrich(board, enable_local_inventory=True)
    assert (board / contract.BOARD).read_bytes() == prior_board
    assert (board / contract.PLAN).read_bytes() == prior_plan


def test_a_completed_local_task_keeps_its_original_local_contract(board):
    contract.enrich(board, enable_local_inventory=True)
    chunks = blocks((board / contract.BOARD).read_text())
    task_id = next(key for key, value in chunks.items() if '- provider role: deterministic-only' in value)
    old = chunks[task_id]
    completed = re.sub(r'(?mi)^- status: (.*)$', '- status: completed', old)
    text = (board / contract.BOARD).read_text().replace(old, completed)
    (board / contract.BOARD).write_text(text)
    plan = json.loads((board / contract.PLAN).read_text())
    prior_task = copy.deepcopy(next(task for task in plan['tasks'] if task['task_id'] == task_id))
    contract.enrich(board, enable_local_inventory=True)
    assert blocks((board / contract.BOARD).read_text())[task_id] == completed
    plan = json.loads((board / contract.PLAN).read_text())
    assert next(task for task in plan['tasks'] if task['task_id'] == task_id) == prior_task
    assert contract.check_board(board)['board_contract_valid']


def test_route_keeps_independent_tests_checker_and_exact_binary_authority():
    task = {'task_id': 'LIRAE-USC-T26-P01', 'predicted_files': ['foreign.py']}
    baseline = contract.task_contract(task)
    local = contract.task_contract({**task, 'local_inventory': True})
    assert local['validation_commands'][0] == baseline['validation_commands'][0]
    assert local['validation_commands'][1].endswith(' && ' + baseline['validation_commands'][1])
    assert local['allowed_paths'] == [contract.directory(task['task_id']).as_posix()]
    assert local['provider_role'] == 'deterministic-only'
    assert local['context_budget_tokens'] == 0
    envelope = local['proposal_artifact_envelope']
    assert envelope['schema'].endswith('@3')
    assert envelope['binary_paths'] == local['outputs'][1:]
    assert all(path.endswith('.zip') for path in envelope['binary_paths'])
    assert 'allow_binary' not in envelope
    assert envelope['max_patch_bytes'] == 16_000_000
    assert envelope['max_output_bytes'] == 24_000_000


@pytest.mark.parametrize('task_id', ['LIRAE-WIDTH-4096', 'LIRAE-METHOD-01', 'LIRAE-CONST-AM27'])
def test_other_families_cannot_use_uscode_local_route(task_id):
    with pytest.raises(contract.ContractError, match='US Code shard'):
        contract.task_contract({'task_id': task_id, 'local_inventory': True})
