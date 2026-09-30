"""Native UI/IDL corpus training, split boundaries, and exact local resume."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import ui_feature_training as ui

ROOT = Path(__file__).resolve().parents[4]


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def row():
    return _module(ROOT/'tests/unit/logic/formalization/autoencoder/test_ui_training_inputs.py',
                   'native_ui_input_fixtures').native_row


def _corpus(row):
    training = [row(1, group_id='train-a', split='train'), row(2, group_id='train-b', split='train')]
    tuning = [row(3, group_id='tune-a', split='validation'), row(4, group_id='tune-b', split='validation')]
    return training, tuning


def _bound_row_projection(source):
    from ipfs_datasets_py.logic.ui_ux_ir.runtime.idl_projection import project_idl_request, project_idl_result
    from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import (
        ActorContext, ActorKind, RuntimeMediationContext, PolicyNorm, PolicyVerdict, UIMediator,
    )
    prepared = ui.prepare_ui_rows([source], role='inference')[0]
    binding, event = prepared.document.action_bindings[0], prepared.document.events[0]
    context = RuntimeMediationContext(
        declaration_digest=prepared.target.digest, projection_id='projection:authored-fixture', state_version=0,
        actor=ActorContext('actor:fixture', ActorKind.SYSTEM, confirmation_granted=True),
        policy_norms=(PolicyNorm('policy:fixture', PolicyVerdict.ALLOW, binding_id=binding.binding_id),),
    )
    decision = UIMediator().mediate(binding, event, context)
    descriptor = source['interface']['descriptor']
    request = project_idl_request(decision, descriptor, {'record_id':'fixture-record'},
        expected_request_id=decision.invocation_request.request_id, expected_event_id=event.event_id,
        expected_declaration_digest=context.declaration_digest, expected_projection_id=context.projection_id,
        expected_state_version=context.state_version)
    result = project_idl_result(request, descriptor, request_id=request.invocation_request.request_id,
        request_sha256=request.sha256, interface_cid=source['interface']['claimed_interface_cid'],
        method_name='delete_record', result={'deleted':True})
    return prepared, request, result


def test_training_row_join_matches_mediated_request_and_result_schema(row):
    prepared, request, result = _bound_row_projection(row(1))
    view = next(p for p in prepared.target.to_dict()['projections'] if p['projection_id'].endswith(':interface_bindings'))
    assert view['expression']['interface_cid'] == request.invocation_request.mcp_idl_interface_cid
    assert result.to_dict()['schema_validated'] is True
    assert request.to_dict()['transport_executed'] is False
    assert result.to_dict()['backend_authenticated'] is False
    assert result.to_dict()['state_mutation_applied'] is False


def test_real_ui_train_resume_registry_reopen_and_inference(tmp_path, row):
    pytest.importorskip('torch')
    training, tuning = _corpus(row)
    with AutoencoderRegistry(tmp_path/'control.duckdb', tmp_path/'artifacts') as registry:
        first = ui.train_ui_feature_batch(registry, training, tuning, tmp_path/'first', epochs=1)
        parent = first['registration']['version_id']
        assert first['projection_ids'] == sorted(ui.DEFAULT_PROJECTIONS)
        assert first['training_target_count'] == first['tuning_target_count'] == 2
    with AutoencoderRegistry(tmp_path/'control.duckdb', tmp_path/'artifacts') as registry:
        original = registry.get_version(parent)
        before = registry.artifact_path(original['artifact']).read_bytes()
        new_rows = [row(5, group_id='train-c', split='train')]
        second = ui.train_ui_feature_batch(registry, new_rows, tuning, tmp_path/'resumed',
                                            parent_version_id=parent, epochs=1)
        child = second['registration']['version_id']
        assert registry.get_version(child)['parent_version_id'] == parent
        inferred = ui.infer_ui_feature_batch(registry, child, tuning, tmp_path/'inference')
        assert inferred['training_executed'] is False
        assert inferred['decoded_formulas_generated'] is False
        assert inferred['transport_executed'] is False
        assert all(inferred[key] is False for key in ui.features.FALSE)
        assert len(inferred['rows']) == 2
        assert registry.artifact_path(original['artifact']).read_bytes() == before
        saved = json.loads(registry.artifact_path(registry.get_version(child)['artifact']).read_bytes())
        assert saved['report']['ui_batch']['training_groups'] == ['train-a', 'train-b', 'train-c']
        assert len(saved['report']['ui_batch']['training_source_ids']) == 3
    assert json.loads((tmp_path/'resumed/source_rows.json').read_bytes())['training'] == new_rows


def test_ui_groups_must_be_disjoint_before_training(tmp_path, row, monkeypatch):
    training, tuning = _corpus(row)
    tuning[0]['provenance']['group_id'] = 'train-a'
    monkeypatch.setattr(ui.features, 'train_projection_features', lambda *a, **k: pytest.fail('optimizer should not run'))
    with pytest.raises(ValueError, match='group leakage'):
        ui.train_ui_feature_batch(None, training, tuning, tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()


def test_relabeling_group_cannot_leak_same_source_record(tmp_path, row, monkeypatch):
    training, tuning = _corpus(row)
    tuning[0]['provenance']['row_id'] = training[0]['provenance']['row_id']
    monkeypatch.setattr(ui.features, 'train_projection_features', lambda *a, **k: pytest.fail('optimizer should not run'))
    with pytest.raises(ValueError, match='source record leakage'):
        ui.train_ui_feature_batch(None, training, tuning, tmp_path/'not-created')
    assert not (tmp_path/'not-created').exists()


@pytest.mark.parametrize('role,split', [('training','test'),('training','test_website'),('tuning','test'),('tuning','train')])
def test_benchmark_split_cannot_be_implicitly_repurposed(row, role, split):
    with pytest.raises(ValueError, match='test/canary|unknown provenance split'):
        ui.prepare_ui_rows([row(1, split=split)], role=role)


def test_duplicate_source_identity_is_rejected(row):
    first = row(1)
    second = row(2)
    second['provenance']['row_id'] = first['provenance']['row_id']
    with pytest.raises(ValueError, match='duplicate source record'):
        ui.prepare_ui_rows([first, second], role='training')


def test_resume_rejects_changed_tuning_and_producer(tmp_path, row, monkeypatch):
    pytest.importorskip('torch')
    training, tuning = _corpus(row)
    with AutoencoderRegistry(tmp_path/'db', tmp_path/'artifacts') as registry:
        first = ui.train_ui_feature_batch(registry, training, tuning, tmp_path/'first', epochs=1)
        parent = first['registration']['version_id']
        changed = [row(6, group_id='tune-a', split='validation'), tuning[1]]
        with pytest.raises(ValueError, match='same tuning targets'):
            ui.train_ui_feature_batch(registry, training, changed, tmp_path/'bad', parent_version_id=parent)
        leaked = copy.deepcopy(tuning)
        leaked[0]['provenance']['row_id'] = training[0]['provenance']['row_id']
        with pytest.raises(ValueError, match='historical training/tuning source record leakage'):
            ui.train_ui_feature_batch(registry, [row(7)], leaked, tmp_path/'historical-leak',
                                      parent_version_id=parent)
        original = ui.producer_identity()
        changed_source = copy.deepcopy(original); changed_source['sha256'] = '0'*64
        monkeypatch.setattr(ui, 'producer_identity', lambda: changed_source)
        with pytest.raises(ValueError, match='producer changed'):
            ui.infer_ui_feature_batch(registry, parent, tuning, tmp_path/'bad-infer')


def test_jsonl_loader_bounds_duplicates_and_symlinks(tmp_path):
    path = tmp_path/'input.jsonl'
    path.write_text('{"x":1,"x":2}\n')
    with pytest.raises(ValueError, match='duplicate JSON'):
        ui.load_ui_training_jsonl(path)
    path.write_text('{}\n'*129)
    with pytest.raises(ValueError, match='row bound'):
        ui.load_ui_training_jsonl(path)
    path.write_text('{}\n')
    alias = tmp_path/'link'; alias.symlink_to(path)
    with pytest.raises(ValueError, match='regular local'):
        ui.load_ui_training_jsonl(alias)


def test_cli_plan_never_opens_registry_or_trains(tmp_path, row):
    cli = _module(ROOT/'scripts/ops/ui_ux_ir/run_ui_feature_training.py', 'ui_cli')
    training, tuning = _corpus(row)
    for name, rows in [('train',training),('tune',tuning)]:
        (tmp_path/name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    state = tmp_path/'state'
    plan = cli.main(['train','--input-jsonl',str(tmp_path/'train'),'--tuning-jsonl',str(tmp_path/'tune'),
                     '--state-directory',str(state),'--attempt-id','first','--plan'])
    assert plan['row_count'] == plan['tuning_count'] == 2
    assert plan['training_executed'] is False and plan['compiler_executed'] is False
    assert not state.exists()
    with pytest.raises(ValueError, match='optimizer'):
        cli.main(['infer','--input-jsonl',str(tmp_path/'tune'),'--state-directory',str(state),
                  '--attempt-id','infer','--parent-version-id','unused','--epochs','1','--plan'])
