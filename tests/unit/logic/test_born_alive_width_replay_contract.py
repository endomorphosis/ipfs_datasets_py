"""Only reviewed pending widths may use an independently executed replay."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('born_alive_width_contract_test', ROOT / 'scripts/ops/legal_ir/legal_ir_supervisor_contract.py')
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


def blocks(text):
    return {m[1]: chunk for chunk in re.split(r'(?=^## )', text, flags=re.M)
            if (m := re.match(r'## (LIRAE-[A-Z0-9-]+)\b', chunk))}


@pytest.fixture(autouse=True)
def exact_input_pins(monkeypatch):
    monkeypatch.setattr(contract, 'width_required_file_pins', lambda dimension: [{'path': '/reviewed/input-' + str(dimension), 'bytes': 123, 'sha256': 'a' * 64}])


@pytest.fixture
def board(tmp_path):
    tasks = [{'task_id': task_id, 'retained_metadata': {'title': task_id, 'opaque': [False, None]}}
             for task_id in ['LIRAE-WIDTH-384', 'LIRAE-WIDTH-768', 'LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096', 'LIRAE-CONST-AM01']]
    path = tmp_path / contract.PLAN
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'tasks': tasks}))
    (tmp_path / contract.BOARD).write_text('# Tasks\n\n' + ''.join('## ' + task['task_id'] + ' original\n\n- status: ' + ('completed' if contract.kind(task['task_id']) == 'constitution' else 'todo') + '\n- acceptance: Keep original acceptance\n\n' for task in tasks))
    source = tmp_path / contract.CONSTITUTION
    source.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / contract.CONSTITUTION, source)
    contract.enrich(tmp_path)
    return tmp_path


def test_pending_only_width_routing_preserves_all_other_contracts_and_is_idempotent(board):
    path, text_path = board / contract.PLAN, board / contract.BOARD
    before = json.loads(path.read_bytes())
    old_blocks = blocks(text_path.read_text())
    assert contract.enrich(board, enable_local_width_replay=True)['local_width_replay_enabled_count'] == 2
    after = json.loads(path.read_bytes())
    current_blocks = blocks(text_path.read_text())
    assert len(before['tasks']) == len(after['tasks']) == len(current_blocks)
    for old, new in zip(before['tasks'], after['tasks'], strict=True):
        task_id = old['task_id']
        if task_id not in contract.LOCAL_WIDTH_TASKS:
            assert new == old
            assert current_blocks[task_id] == old_blocks[task_id]
        else:
            assert new['local_width_replay'] is True
            assert new['retained_metadata'] == old['retained_metadata']
            assert '- status: todo\n' in current_blocks[task_id]
            assert new['validation_commands'][0] == old['validation_commands'][0]
    snapshot = path.read_bytes(), text_path.read_bytes()
    contract.enrich(board, enable_local_width_replay=True)
    assert snapshot == (path.read_bytes(), text_path.read_bytes())
    assert contract.check_board(board)['task_count'] == len(before['tasks'])


def test_completed_384_and_missing_8_4096_are_never_rerouted(board):
    path = board / contract.BOARD
    chunks = blocks(path.read_text())
    old = chunks['LIRAE-WIDTH-384']
    path.write_text(path.read_text().replace(old, old.replace('- status: todo', '- status: completed')))
    old_plan = json.loads((board / contract.PLAN).read_bytes())
    old_chunks = blocks(path.read_text())
    assert contract.enrich(board, enable_local_width_replay=True)['local_width_replay_enabled_count'] == 1
    new_plan = json.loads((board / contract.PLAN).read_bytes())
    new_chunks = blocks(path.read_text())
    for before, after in zip(old_plan['tasks'], new_plan['tasks'], strict=True):
        if before['task_id'] != 'LIRAE-WIDTH-768':
            assert before == after
            assert old_chunks[before['task_id']] == new_chunks[before['task_id']]
    for task_id in ['LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096']:
        assert contract.task_contract({'task_id': task_id})['required_validation_executables'] == [contract.WIDTH_REPLAY_EXECUTABLE]


@pytest.mark.parametrize('dimension', [384, 768])
def test_exact_dimension_capability_binary_authority_and_scope(dimension):
    task_id = 'LIRAE-WIDTH-' + str(dimension)
    prior = contract.task_contract({'task_id': task_id})
    current = contract.task_contract({'task_id': task_id, 'local_width_replay': True, 'predicted_files': ['unrelated.py']})
    directory = contract.directory(task_id).as_posix()
    assert current['allowed_paths'] == [directory]
    assert current['outputs'] == [directory + '/' + name for name in ['receipt.json', 'observation.json', 'checkpoint.zip']]
    assert current['required_validation_executables'] == ['python3']
    assert current['required_validation_file_pins'] == [{'path': '/reviewed/input-' + str(dimension), 'bytes': 123, 'sha256': 'a' * 64}]
    assert current['provider_role'] == 'deterministic-only' and current['context_budget_tokens'] == 0
    assert current['validation_commands'][0] == prior['validation_commands'][0]
    assert current['validation_commands'][1].endswith(' && ' + prior['validation_commands'][1])
    envelope = current['proposal_artifact_envelope']
    assert envelope['schema'].endswith('@3') and envelope['binary_paths'] == [directory + '/checkpoint.zip']
    assert envelope['max_patch_bytes'] == 16_000_000 and envelope['max_output_bytes'] == 24_000_000
    assert 'allow_binary' not in envelope


@pytest.mark.parametrize('task_id', ['LIRAE-WIDTH-08', 'LIRAE-WIDTH-4096', 'LIRAE-CONST-AM01', 'LIRAE-USC-T04'])
def test_unreviewed_dimensions_or_families_cannot_select_local_width_route(task_id):
    with pytest.raises(contract.ContractError, match='requires reviewed384/768'):
        contract.task_contract({'task_id': task_id, 'local_width_replay': True})


def observation(dimension):
    return {'dimension': dimension, 'source_hashes': contract.SAMPLE_HASHES,
            'profile_id': 'selected-profile-fixture', 'checkpoint_sha256': contract.sha(b'ZIP'),
            'training_executed': False, 'status': 'observed', 'admitted': False, 'formalized': False,
            'metrics': {'cosine_similarity': 1.0, 'reconstruction_loss': 0.0},
            'corpus_default': dimension == 384, 'token_ceiling': 512,
            'role': 'donor', 'encoder_executed': False,
            'development_result': {'successful': 0, 'total': 12},
            'measurement_scope': 'identity_by_construction_not_learned_reconstruction',
            'quality_qualified': False, 'source_semantics_verified': False,
            'statutory_fidelity_qualified': False, 'learned_reconstruction_demonstrated': False}


def gate_case(root, dimension=384, verdict='True'):
    path = root / contract.WIDTH_REPLAYER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def verify_observation(root, task_id, observation, checkpoint_archive_bytes, *, output_directory):\n"
                    "    assert checkpoint_archive_bytes == b'ZIP'\n"
                    "    assert output_directory.is_dir()\n"
                    "    (root / 'verified-marker').write_text(task_id)\n"
                    "    return {'verified': " + verdict + "}\n")
    row = observation(dimension)
    return 'LIRAE-WIDTH-' + str(dimension), {'evidence': {'dimension': dimension}}, {'observation': json.dumps(row).encode(), 'checkpoint': b'ZIP'}


def test_reviewed_gate_actually_calls_independent_verifier_and_uses_private_scratch(tmp_path):
    task_id, receipt, data = gate_case(tmp_path)
    contract.validate_width(task_id, receipt, data, root=tmp_path, replay_enabled=True)
    assert (tmp_path / 'verified-marker').read_text() == task_id


def test_independent_verifier_rejection_cannot_be_replaced_by_plausible_metrics(tmp_path):
    task_id, receipt, data = gate_case(tmp_path, verdict='False')
    with pytest.raises(contract.ContractError, match='independent width replay verification failed'):
        contract.validate_width(task_id, receipt, data, root=tmp_path, replay_enabled=True)
    assert (tmp_path / 'verified-marker').exists()


@pytest.mark.parametrize('dimension', [8, 4096, 384, 768])
def test_unenabled_plan_and_8_4096_stay_failclosed_without_invoking_replayer(tmp_path, dimension):
    task_id, receipt, data = gate_case(tmp_path, dimension)
    with pytest.raises(contract.WidthReplayUnavailable):
        contract.validate_width(task_id, receipt, data, root=tmp_path, replay_enabled=dimension in (8, 4096))
    assert not (tmp_path / 'verified-marker').exists()


@pytest.mark.parametrize('field', ['quality_qualified', 'source_semantics_verified', 'statutory_fidelity_qualified', 'learned_reconstruction_demonstrated'])
def test_identity_projection_diagnostics_cannot_assert_quality_or_fidelity(tmp_path, field):
    task_id, receipt, data = gate_case(tmp_path)
    row = json.loads(data['observation'])
    row[field] = True
    data['observation'] = json.dumps(row).encode()
    with pytest.raises(contract.ContractError, match='cannot assert quality or fidelity'):
        contract.validate_width(task_id, receipt, data, root=tmp_path, replay_enabled=True)
    assert not (tmp_path / 'verified-marker').exists()


def test_projection_measurement_scope_cannot_be_renamed_learned_reconstruction(tmp_path):
    task_id, receipt, data = gate_case(tmp_path)
    row = json.loads(data['observation'])
    row['measurement_scope'] = 'learned_semantic_reconstruction'
    data['observation'] = json.dumps(row).encode()
    with pytest.raises(contract.ContractError, match='measurement scope required'):
        contract.validate_width(task_id, receipt, data, root=tmp_path, replay_enabled=True)


def test_file_pin_metadata_is_exact_json_and_check_board_rejects_stale_digest(board):
    contract.enrich(board, enable_local_width_replay=True)
    chunks = blocks((board / contract.BOARD).read_text())
    field = next(line.removeprefix('- required validation file pins: ') for line in chunks['LIRAE-WIDTH-384'].splitlines() if line.startswith('- required validation file pins: '))
    assert json.loads(field) == [{'path': '/reviewed/input-384', 'bytes': 123, 'sha256': 'a' * 64}]
    path = board / contract.BOARD
    path.write_text(path.read_text().replace('a' * 64, 'b' * 64, 1))
    with pytest.raises(contract.ContractError, match='stale required file pins'):
        contract.check_board(board)


@pytest.mark.parametrize('flag', [True, False, 'true', 1])
def test_actual_receipt_dispatch_requires_exact_plan_opt_in(tmp_path, flag):
    task_id, receipt, data = gate_case(tmp_path)
    plan = tmp_path / contract.PLAN
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({'tasks': [{'task_id': task_id, 'local_width_replay': flag}]}))
    directory = tmp_path / contract.directory(task_id)
    directory.mkdir(parents=True)
    entries = []
    for label, filename in [('observation', 'observation.json'), ('checkpoint', 'checkpoint.zip')]:
        (directory / filename).write_bytes(data[label])
        entries.append({'kind': label, 'path': (contract.directory(task_id) / filename).as_posix(), 'sha256': contract.sha(data[label])})
    receipt.update(schema=contract.SCHEMA, task_id=task_id, task_kind='width', status='inventory',
                   authority={'admitted': False, 'formalized': False}, artifacts=entries)
    (directory / 'receipt.json').write_text(json.dumps(receipt))
    if flag is True:
        assert contract.validate(tmp_path, task_id)['validated'] is True
        assert (tmp_path / 'verified-marker').exists()
    else:
        with pytest.raises(contract.WidthReplayUnavailable):
            contract.validate(tmp_path, task_id)
        assert not (tmp_path / 'verified-marker').exists()
