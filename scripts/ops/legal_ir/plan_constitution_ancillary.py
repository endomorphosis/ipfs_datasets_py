"""Append the missing Constitution inventory task, or audit retained coverage.

Run only at a supervisor maintenance boundary. Existing plan records, board
sections, artifacts and task statuses are preserved. Materialization and task
completion still run through the ordinary native queue.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]


def load_contract(root):
    spec = importlib.util.spec_from_file_location('ancillary_reviewed_contract', root / 'scripts/ops/legal_ir/legal_ir_supervisor_contract.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def board_blocks(text, contract):
    blocks = {}
    for chunk in re.split(r'(?=^## )', text, flags=re.MULTILINE):
        match = re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk)
        if match:
            contract.require(match[1] not in blocks, 'duplicate board task')
            blocks[match[1]] = chunk
    return blocks


def completed(block):
    statuses = re.findall(r'^- status:\s*([^\n]+)', block, flags=re.MULTILINE | re.IGNORECASE)
    return bool(statuses) and statuses[-1].strip().casefold() == 'completed'


def coverage(root):
    root = Path(root)
    contract = load_contract(root)
    plan = json.loads((root / contract.PLAN).read_bytes())
    ids = [row['task_id'] for row in plan['tasks']]
    contract.require(len(ids) == len(set(ids)), 'duplicate planned task')
    const_ids = {task_id for task_id in ids if contract.kind(task_id) == 'constitution'}
    original = set(contract.CONSTITUTION_TASKS)
    contract.require(const_ids in (original, original | {contract.ANCILLARY_TASK}), 'unexpected Constitution task set')
    source = (root / contract.CONSTITUTION).read_bytes()
    contract.require(contract.sha(source) == contract.CONSTITUTION_SHA256, 'retained Constitution input differs')
    inventory = contract.owner(root, 'constitution_inventory').inventory_constitution(source.decode())
    # Independently derive the selected83 from the exact retained source.
    ancillary = {row['id'] for row in contract.constitution_spans(inventory, contract.ANCILLARY_TASK)}
    expected = {row['id'] for row in inventory['spans']}
    contract.require(len(expected) == len(inventory['spans']) == 236, 'source inventory IDs differ')
    blocks = board_blocks((root / contract.BOARD).read_text(), contract)
    contract.require(set(blocks) == set(ids), 'board/plan task IDs differ')
    counts, checked = Counter(), []
    for task_id in sorted(const_ids):
        if not completed(blocks[task_id]):
            continue
        # Re-authenticate each receipt and source row; hashes alone do not count.
        contract.validate(root, task_id)
        receipt = json.loads((root / contract.directory(task_id) / 'receipt.json').read_bytes())
        data = contract.read_artifacts(root, task_id, receipt)
        counts.update(row['id'] for row in contract.payload(data, 'spans'))
        checked.append(task_id)
    missing, extra = sorted(expected - counts.keys()), sorted(counts.keys() - expected)
    duplicate = sorted(key for key, count in counts.items() if count != 1)
    return {'schema': 'legal-ir-constitution-coverage/v1',
            'source_sha256': contract.CONSTITUTION_SHA256, 'expected_span_count': len(expected),
            'completed_constitution_tasks': checked, 'covered_unique_spans': len(counts),
            'missing_span_ids': missing, 'extra_span_ids': extra, 'duplicate_span_ids': duplicate,
            'ancillary_span_ids': sorted(ancillary),
            'complete': not missing and not extra and not duplicate,
            'admitted': False, 'formalized': False, 'roundtrip_ok': False}


def task_record(contract):
    task_id = contract.ANCILLARY_TASK
    task = {'schema': 'ipfs_accelerate_py/agent-supervisor/derived-task-proposal@1',
            'task_id': task_id, 'task_cid': 'lir:task:' + task_id,
            'goal_id': 'LIRAE-CONST', 'goal_cid': 'lir:goal:LIRAE-CONST',
            'title': 'Retain unassigned Constitution notes and signature spans',
            'source_root': 'ipfs_datasets', 'residual_id': '', 'identity_key': task_id,
            'predicted_files': [], 'context_paths': [], 'predicted_symbols': [],
            'acceptance_criteria': ['Retain exactly 83 non-operative notes and signature spans from the pinned source inventory',
                                    'Preserve exact source span IDs, plaintext, status and reason',
                                    'admitted, formalized and roundtrip_ok remain false'],
            'dependencies': [], 'conflicts': [], 'evidence_refs': [],
            'resource_class': 'cpu-medium', 'token_class': 'medium',
            'rationale': 'Retain the 83 actual source inventory rows outside the original 35 unit selectors',
            'depth': 2, 'completion_authority': False, 'mutation_authority': False,
            'seed_board_edit': False, 'local_constitution_inventory': True}
    task.update(contract.task_contract(task))
    return task


def task_block(task):
    lines = ['## ' + task['task_id'] + ' ' + task['title'], '', '- status: todo',
             '- goal id: LIRAE-CONST', '- depends on: none',
             '- board namespace: legal-ir-autoencoder-v1',
             '- acceptance: ' + '; '.join(task['acceptance_criteria']),
             '- completion: manual', '- priority: P1', '- track: legal-ir',
             '- outputs: ' + ', '.join(task['outputs']),
             '- allowed paths: ' + ', '.join(task['allowed_paths']),
             '- receipt instructions: ' + task['receipt_instructions'],
             '- validation: ' + '; '.join(task['validation_commands']),
             '- provider role: ' + task['provider_role'],
             '- context budget tokens: ' + str(task['context_budget_tokens']), '']
    return '\n'.join(lines)


def append_plan_task(raw, task, contract):
    """Insert one array element without serializing any existing plan bytes."""
    text, decoder = raw.decode(), json.JSONDecoder()
    index = len(text) - len(text.lstrip())
    contract.require(text[index:index + 1] == '{', 'plan must be a JSON object')
    index += 1
    matches = []
    while True:
        while text[index].isspace():
            index += 1
        if text[index] == '}':
            break
        key, index = decoder.raw_decode(text, index)
        while text[index].isspace():
            index += 1
        contract.require(text[index] == ':', 'invalid plan object')
        index += 1
        while text[index].isspace():
            index += 1
        value, end = decoder.raw_decode(text, index)
        if key == 'tasks':
            contract.require(isinstance(value, list), 'plan tasks must be an array')
            matches.append((index, end, bool(value)))
        index = end
        while text[index].isspace():
            index += 1
        if text[index] == '}':
            break
        contract.require(text[index] == ',', 'invalid plan object separator')
        index += 1
    contract.require(len(matches) == 1, 'one top-level tasks array required')
    start, end, populated = matches[0]
    insertion = end - 1
    while insertion > start + 1 and text[insertion - 1].isspace():
        insertion -= 1
    record = '\n'.join('    ' + line for line in json.dumps(task, indent=2).splitlines())
    addition = (',' if populated else '') + '\n' + record
    return (text[:insertion] + addition + text[insertion:]).encode()


def add_task(root):
    root = Path(root)
    contract = load_contract(root)
    contract.check_board(root)
    plan_path, board_path = root / contract.PLAN, root / contract.BOARD
    old_plan, old_board = plan_path.read_bytes(), board_path.read_bytes()
    plan = json.loads(old_plan)
    text = old_board.decode()
    blocks = board_blocks(text, contract)
    task = task_record(contract)
    existing = [row for row in plan['tasks'] if row['task_id'] == contract.ANCILLARY_TASK]
    if existing:
        contract.require(existing == [task] and contract.ANCILLARY_TASK in blocks,
                         'existing ancillary contract differs')
        return {'task_count': len(plan['tasks']), 'added': False, 'preserved_existing_tasks': True}
    report = coverage(root)
    contract.require(set(report['completed_constitution_tasks']) == set(contract.CONSTITUTION_TASKS),
                     'original Constitution tasks must be completed and authenticated')
    contract.require(report['covered_unique_spans'] == 153 and not report['extra_span_ids']
                     and not report['duplicate_span_ids'] and report['missing_span_ids'] == report['ancillary_span_ids'],
                     'original coverage differs from the exact ancillary gap')
    plan['tasks'].append(task)
    # All original records and every original board byte remain unchanged.
    # The caller holds the native maintenance boundary and snapshots both
    # files for crash recovery. Ordinary write failures restore both originals.
    try:
        plan_path.write_bytes(append_plan_task(old_plan, task, contract))
        board_path.write_bytes((text + ('\n' if not text.endswith('\n\n') else '') + task_block(task)).encode())
    except BaseException:
        plan_path.write_bytes(old_plan)
        board_path.write_bytes(old_board)
        raise
    return {'task_count': len(plan['tasks']), 'added': True, 'preserved_existing_tasks': True,
            'task_id': contract.ANCILLARY_TASK, 'source_span_count': 83}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--add-task', action='store_true')
    modes.add_argument('--check-coverage', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = add_task(args.root) if args.add_task else coverage(args.root)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('Constitution coverage failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if args.add_task or result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
