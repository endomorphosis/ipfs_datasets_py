"""Unassigned source notes remain inventory, with native completion authority."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


helper = load('ancillary_materializer_test', ROOT / 'scripts/ops/legal_ir/materialize_legal_ir_inventory.py')
planner = load('ancillary_planner_test', ROOT / 'scripts/ops/legal_ir/plan_constitution_ancillary.py')


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    for relative in ['scripts/ops/legal_ir/legal_ir_supervisor_contract.py',
                     'scripts/ops/legal_ir/materialize_legal_ir_inventory.py',
                     'ipfs_datasets_py/logic/autoformal/constitution_inventory.py']:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    contract = helper.contract_owner(tmp_path)
    monkeypatch.setattr(planner, 'load_contract', lambda root: contract)
    source = tmp_path / contract.CONSTITUTION
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / contract.CONSTITUTION, source)
    tasks = []
    blocks = ['# Original board\n\n## Goal LIRAE-CONST\n\n- status: goal\n\n']
    for task_id in contract.CONSTITUTION_TASKS:
        record = {'task_id': task_id, 'title': 'Preserved ' + task_id,
                  'unchanged_metadata': {'opaque': [task_id, True]}}
        record.update(contract.task_contract(record))
        tasks.append(record)
        blocks.append('## ' + task_id + ' preserved\n\n- status: completed\n'
                      '- acceptance: Retain exact original criterion\n'
                      '- outputs: ' + ', '.join(record['outputs']) + '\n'
                      '- allowed paths: ' + ', '.join(record['allowed_paths']) + '\n'
                      '- validation: ' + '; '.join(record['validation_commands']) + '\n\n')
    plan = {'retained': {'scope': 'test'}, 'tasks': tasks}
    path = tmp_path / contract.PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(helper.raw(plan))
    (tmp_path / contract.BOARD).write_text(''.join(blocks))
    for task_id in contract.CONSTITUTION_TASKS:
        helper.materialize(tmp_path, task_id)
    contract.check_board(tmp_path)
    return tmp_path, contract


def add_and_materialize(seeded):
    root, contract = seeded
    planner.add_task(root)
    helper.materialize(root, contract.ANCILLARY_TASK)
    return root, contract


def artifact(root, contract, label):
    directory = root / contract.directory(contract.ANCILLARY_TASK)
    return directory / (label + '.json')


def replace_artifact(root, contract, label, value):
    path = artifact(root, contract, label)
    path.write_bytes(helper.raw(value))
    receipt_path = artifact(root, contract, 'receipt')
    receipt = json.loads(receipt_path.read_bytes())
    next(row for row in receipt['artifacts'] if row['kind'] == label)['sha256'] = contract.sha(path.read_bytes())
    receipt_path.write_bytes(helper.raw(receipt))


def test_source_complement_is_exact83_nonoperative_rows_and_original35_selectors_unchanged(seeded):
    root, contract = seeded
    text = (root / contract.CONSTITUTION).read_bytes()
    assert len(text) == 48617
    assert contract.sha(text) == '9dd8624bf0ef83dd135772f7c19aeef0496c3164d04d4bc0d6d8f1de91746e4b'
    inventory = contract.owner(root, 'constitution_inventory').inventory_constitution(text.decode())
    original = []
    for task_id in contract.CONSTITUTION_TASKS:
        unit = contract.selector(task_id)
        rows = contract.constitution_spans(inventory, task_id)
        assert rows == [row for row in inventory['spans'] if row['unit_id'] == unit or row['unit_id'].startswith(unit + '.')]
        original.extend(row['id'] for row in rows)
    ancillary = contract.constitution_spans(inventory, contract.ANCILLARY_TASK)
    assert len(original) == len(set(original)) == 153
    assert len(ancillary) == 83 and len(inventory['spans']) == 236
    assert not set(original) & {row['id'] for row in ancillary}
    assert set(original) | {row['id'] for row in ancillary} == {row['id'] for row in inventory['spans']}
    assert all(row['status'] == 'non_operative' and (row['unit_id'].startswith('note-') or row['unit_id'] == 'signature') for row in ancillary)
    assert sum(row['unit_id'] == 'signature' for row in ancillary) == 16


def test_append_preserves_every_prior_record_block_artifact_and_status_then_is_idempotent(seeded):
    root, contract = seeded
    plan_path, board_path = root / contract.PLAN, root / contract.BOARD
    old_plan, old_board = json.loads(plan_path.read_bytes()), board_path.read_bytes()
    old_artifacts = {str(path.relative_to(root)): path.read_bytes() for path in (root / contract.EVIDENCE).rglob('*.json')}
    result = planner.add_task(root)
    assert result == {'task_count': 36, 'added': True, 'preserved_existing_tasks': True,
                      'task_id': contract.ANCILLARY_TASK, 'source_span_count': 83}
    updated = json.loads(plan_path.read_bytes())
    assert updated['tasks'][:-1] == old_plan['tasks']
    for record in old_plan['tasks']:
        assert helper.raw(record).strip() in plan_path.read_bytes()
    assert {key: value for key, value in updated.items() if key != 'tasks'} == {key: value for key, value in old_plan.items() if key != 'tasks'}
    assert board_path.read_bytes().startswith(old_board)
    assert all((root / relative).read_bytes() == content for relative, content in old_artifacts.items())
    before = plan_path.read_bytes(), board_path.read_bytes()
    assert planner.add_task(root)['added'] is False
    assert before == (plan_path.read_bytes(), board_path.read_bytes())
    assert contract.check_board(root) == {'task_count': 36, 'board_contract_valid': True}


def test_route_has_only_three_task_outputs_and_two_independent_actual_commands(seeded):
    root, contract = seeded
    planner.add_task(root)
    task = json.loads((root / contract.PLAN).read_bytes())['tasks'][-1]
    directory = contract.directory(contract.ANCILLARY_TASK).as_posix()
    assert task['outputs'] == [directory + '/' + name for name in ['receipt.json', 'source.json', 'spans.json']]
    assert task['allowed_paths'] == [directory]
    assert task['provider_role'] == 'deterministic-only' and task['context_budget_tokens'] == 0
    assert len(task['validation_commands']) == 2
    assert '-m pytest ' in task['validation_commands'][0]
    assert 'test_constitution_inventory.py' in task['validation_commands'][0]
    assert 'test_constitution_article_1_inventory.py' in task['validation_commands'][0]
    assert task['validation_commands'][1].count(' && ') == 1
    assert task['validation_commands'][1].endswith('--check-task ' + contract.ANCILLARY_TASK)
    assert 'proposal_artifact_envelope' not in task
    with pytest.raises(contract.ContractError, match='requires the ancillary task'):
        contract.task_contract({'task_id': 'LIRAE-CONST-AM01', 'local_constitution_inventory': True})


def test_exact83_materialization_has_false_authority_and_small_deterministic_bytes(seeded):
    root, contract = add_and_materialize(seeded)
    assert contract.validate(root, contract.ANCILLARY_TASK)['validated'] is True
    directory = root / contract.directory(contract.ANCILLARY_TASK)
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}
    helper.materialize(root, contract.ANCILLARY_TASK)
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}
    assert set(before) == {'receipt.json', 'source.json', 'spans.json'}
    assert sum(len(content) for content, _ in before.values()) < 1_000_000
    spans = json.loads(artifact(root, contract, 'spans').read_bytes())
    assert len(spans) == 83
    assert all(row['admitted'] is row['formalized'] is row['roundtrip_ok'] is False for row in spans)
    assert all(row['status'] == 'non_operative' for row in spans)
    receipt = json.loads(artifact(root, contract, 'receipt').read_bytes())
    assert receipt['status'] == 'inventory' and receipt['evidence']['unit_id'] == 'ancillary'
    assert receipt['authority'] == {'admitted': False, 'formalized': False, 'roundtrip_ok': False}
    assert planner.coverage(root)['complete'] is False  # Files alone do not complete a native task.


@pytest.mark.parametrize('attack', ['missing', 'duplicate', 'extra', 'text', 'status', 'reason', 'source_hash', 'source_id', 'admitted', 'formalized', 'roundtrip_ok'])
def test_semantic_tampering_refused_even_with_recomputed_artifact_digest(seeded, attack):
    root, contract = add_and_materialize(seeded)
    rows = json.loads(artifact(root, contract, 'spans').read_bytes())
    if attack == 'missing':
        rows.pop()
    elif attack == 'duplicate':
        rows[-1] = deepcopy(rows[0])
    elif attack == 'extra':
        rows[-1]['id'] = 'invented.span-1'
    elif attack in {'admitted', 'formalized', 'roundtrip_ok'}:
        rows[0][attack] = True
    else:
        field = 'source_text_sha256' if attack == 'source_hash' else attack
        rows[0][field] = 'forged'
    replace_artifact(root, contract, 'spans', rows)
    with pytest.raises(contract.ContractError):
        contract.validate(root, contract.ANCILLARY_TASK)


def test_self_consistent_wrong_source_pin_still_refused(seeded):
    root, contract = add_and_materialize(seeded)
    source = json.loads(artifact(root, contract, 'source').read_bytes())
    source['text'] += '\nInvented legal source.'
    source['sha256'] = contract.sha(source['text'].encode())
    replace_artifact(root, contract, 'source', source)
    path = artifact(root, contract, 'receipt')
    receipt = json.loads(path.read_bytes())
    receipt['source']['sha256'] = source['sha256']
    path.write_bytes(helper.raw(receipt))
    with pytest.raises(contract.ContractError, match='retained input differs'):
        contract.validate(root, contract.ANCILLARY_TASK)


def test_aggregate_requires_native_completed_status_and_all236_authenticated_rows(seeded):
    root, contract = seeded
    before = planner.coverage(root)
    assert before['expected_span_count'] == 236 and before['covered_unique_spans'] == 153
    assert len(before['missing_span_ids']) == 83 and not before['complete']
    assert before['missing_span_ids'] == before['ancillary_span_ids']
    assert not before['extra_span_ids'] and not before['duplicate_span_ids']
    assert planner.main(['--check-coverage', '--root', str(root)]) == 1
    add_and_materialize(seeded)
    assert planner.coverage(root)['complete'] is False
    board = root / contract.BOARD
    text = board.read_text()
    heading = '## ' + contract.ANCILLARY_TASK
    start = text.index(heading)
    board.write_text(text[:start] + text[start:].replace('- status: todo', '- status: completed', 1))
    report = planner.coverage(root)
    assert report['complete'] is True and report['covered_unique_spans'] == 236
    assert len(report['completed_constitution_tasks']) == 36
    assert report['missing_span_ids'] == report['extra_span_ids'] == report['duplicate_span_ids'] == []
    assert planner.main(['--check-coverage', '--root', str(root)]) == 0
    path = root / contract.directory('LIRAE-CONST-A1') / 'spans.json'
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(contract.ContractError, match='hash/size differs'):
        planner.coverage(root)


@pytest.mark.parametrize('attack', ['unfinished', 'bad_original_receipt', 'duplicate_board'])
def test_append_refuses_unproven_original_gap_without_any_writes(seeded, attack):
    root, contract = seeded
    if attack == 'unfinished':
        board = root / contract.BOARD
        board.write_text(board.read_text().replace('- status: completed', '- status: todo', 1))
    elif attack == 'bad_original_receipt':
        path = root / contract.directory('LIRAE-CONST-A1') / 'spans.json'
        path.write_bytes(path.read_bytes() + b' ')
    else:
        board = root / contract.BOARD
        board.write_text(board.read_text() + '\n## LIRAE-CONST-A1 duplicate\n')
    paths = root / contract.PLAN, root / contract.BOARD
    before = tuple(path.read_bytes() for path in paths)
    with pytest.raises(contract.ContractError):
        planner.add_task(root)
    assert before == tuple(path.read_bytes() for path in paths)


def test_append_refuses_existing_conflicting_contract_without_mutation(seeded):
    root, contract = seeded
    planner.add_task(root)
    path = root / contract.PLAN
    plan = json.loads(path.read_bytes())
    plan['tasks'][-1]['title'] = 'Conflicting task identity'
    path.write_bytes(helper.raw(plan))
    before = path.read_bytes(), (root / contract.BOARD).read_bytes()
    with pytest.raises(contract.ContractError, match='existing ancillary contract differs'):
        planner.add_task(root)
    assert before == (path.read_bytes(), (root / contract.BOARD).read_bytes())


def test_consistently_renamed_ancillary_source_identity_is_refused(seeded):
    root, contract = add_and_materialize(seeded)
    source = json.loads(artifact(root, contract, 'source').read_bytes())
    source['source_id'] = 'invented-source-identity'
    replace_artifact(root, contract, 'source', source)
    spans = json.loads(artifact(root, contract, 'spans').read_bytes())
    for row in spans:
        row['source_id'] = source['source_id']
    replace_artifact(root, contract, 'spans', spans)
    receipt_path = artifact(root, contract, 'receipt')
    receipt = json.loads(receipt_path.read_bytes())
    receipt['source']['source_id'] = source['source_id']
    receipt_path.write_bytes(helper.raw(receipt))
    with pytest.raises(contract.ContractError, match='ancillary source identity differs'):
        contract.validate(root, contract.ANCILLARY_TASK)


def test_partial_board_write_failure_restores_both_originals(seeded, monkeypatch):
    root, contract = seeded
    paths = root / contract.PLAN, root / contract.BOARD
    before = tuple(path.read_bytes() for path in paths)
    original_write = Path.write_bytes
    failed = False
    def fail_once(path, data):
        nonlocal failed
        if path == paths[1] and not failed:
            failed = True
            original_write(path, b'partial board write')
            raise OSError('simulated full disk after partial write')
        return original_write(path, data)
    monkeypatch.setattr(Path, 'write_bytes', fail_once)
    with pytest.raises(OSError, match='simulated full disk'):
        planner.add_task(root)
    assert before == tuple(path.read_bytes() for path in paths)


@pytest.mark.parametrize('layout', ['compact', 'indented', 'crlf'])
def test_plan_append_preserves_all_existing_bytes_including_nested_tasks_key(seeded, layout):
    import difflib
    root, contract = seeded
    value = {'nested': {'tasks': ['untouched']}, 'tasks': [{'task_id': 'existing', 'text': 'Álpha'}], 'tail': True}
    old = json.dumps(value, indent=2 if layout != 'compact' else None, ensure_ascii=False)
    if layout == 'crlf':
        old = old.replace('\n', '\r\n')
    addition = {'task_id': contract.ANCILLARY_TASK, 'retained': False}
    new = planner.append_plan_task(old.encode(), addition, contract)
    expected = deepcopy(value)
    expected['tasks'].append(addition)
    assert json.loads(new) == expected
    operations = difflib.SequenceMatcher(None, old.encode(), new, autojunk=False).get_opcodes()
    assert all(operation[0] in {'equal', 'insert'} for operation in operations)
    assert sum(operation[0] == 'insert' for operation in operations) == 1
