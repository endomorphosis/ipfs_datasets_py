"""Explicit support-preserving proposals; controlled tests, no proof claims."""
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_adaptive_optimizer import (
    DEFAULT_PROJECTION_CANDIDATE_ORDER, normalize_projection_candidate_update_order,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch, replay_patch

NONVIEW = (
    'compiler_quality_embedding_weights', 'logic_signature_embedding_weights',
    'round_trip_signal_embedding_weights', 'decompiler_plan_embedding_weights',
    'predicate_argument_embedding_weights', 'family_embedding_weights',
    'semantic_slot_embedding_weights', 'family_semantic_slot_embedding_weights',
    'feature_embedding_weights',
)
VIEW = ('semantic_slot_legal_ir_view_embedding_weights', 'family_semantic_slot_legal_ir_view_embedding_weights',
        'legal_ir_view_embedding_weights', 'family_legal_ir_view_embedding_weights')


def configured(monkeypatch):
    model = ma.AdaptiveModalAutoencoder(compute_device='python', embedding_head_update_normalization=1.0)
    sample = SimpleNamespace(sample_id='train', embedding_vector=[1., -.5], normalized_text='training')
    monkeypatch.setattr(ma, '_observed_family_distribution', lambda sample: {'deontic': 1.})
    for name in ('_compiler_quality_slot_distribution_for', '_logic_signature_distribution_for',
                 '_round_trip_signal_distribution_for', '_decompiler_plan_distribution_for',
                 '_predicate_argument_distribution_for', '_semantic_slot_distribution_for',
                 '_target_family_semantic_slot_distribution_for_sample'):
        monkeypatch.setattr(model, name, lambda sample: {'slot': 1.})
    views = {f'view{i}': 1/6 for i in range(6)}
    monkeypatch.setattr(model, '_target_semantic_slot_legal_ir_view_distribution_for_sample',
                        lambda sample: {f'slot||{key}': value for key, value in views.items()})
    monkeypatch.setattr(model, '_target_family_semantic_slot_legal_ir_view_distribution_for_sample',
                        lambda sample: {f'deontic||slot||{key}': value for key, value in views.items()})
    monkeypatch.setattr(model, '_legal_ir_view_target_distribution_for_sample', lambda sample: views)
    monkeypatch.setattr(model, '_target_family_legal_ir_view_distribution_for_sample',
                        lambda sample: {f'deontic||{key}': value for key, value in views.items()})
    monkeypatch.setattr(model, '_feature_keys_for', lambda sample: ['f1', 'f2'])
    monkeypatch.setattr(model, '_feature_update_groups_for', lambda sample, step: [(['f1', 'f2'], step/2)])
    monkeypatch.setattr(model, '_decoded_for', lambda sample, **kw: [0., 0.])
    # Isolate the exact dependency being tested: support and dedicated IR logits,
    # while avoiding unrelated synthetic sample feature extraction.
    monkeypatch.setattr(model, '_legal_ir_view_feature_keys_for', lambda sample: [])
    monkeypatch.setattr(model, '_learned_feature_activity_count', lambda *args: 1)
    return model, sample


@pytest.mark.parametrize('structural',[False,True])
def test_nonview_surviving_heads_equal_full_arithmetic_and_normalization(monkeypatch,structural):
    full, sample = configured(monkeypatch)
    nonview, _ = configured(monkeypatch)
    assert full._active_embedding_update_head_count(sample) == 13
    full._nudge_decoded_embedding(sample, learning_rate=.175, update_sample_memory=False)
    nonview._nudge_decoded_embedding(sample, learning_rate=.175, update_sample_memory=False,
                                    include_legal_ir_view_heads=False, include_combinatorial_heads=not structural)
    for name in NONVIEW[:6] if structural else NONVIEW:
        assert getattr(nonview.state, name) == getattr(full.state, name)
        assert getattr(nonview.state, name)
    for name in VIEW:
        assert getattr(full.state, name)
        assert getattr(nonview.state, name) == {}
    if structural:
        assert all(getattr(nonview.state,name)=={} for name in NONVIEW[6:])
    assert nonview.state.decoded_embeddings == {} and nonview.state.family_logits == {}
    assert nonview.state.legal_ir_view_logits == {} and nonview.state.feature_legal_ir_view_logits == {}
    assert nonview.state.compiler_quality_embedding_weights['slot'] == pytest.approx([.175 * value / 13 for value in nonview._embedding_training_error(sample.embedding_vector, [0.,0.])])


@pytest.mark.parametrize('structural',[False,True])
def test_nonview_preserves_reference_dependent_ir_support_and_losses(monkeypatch,structural):
    model, sample = configured(monkeypatch)
    four = {f'view{i}': .25 for i in range(4)}
    six = {f'view{i}': 1/6 for i in range(6)}
    before = [model._legal_ir_view_distribution(sample, target, use_sample_memory=False) for target in (four, six)]
    model._nudge_decoded_embedding(sample, learning_rate=.175, update_sample_memory=False, include_legal_ir_view_heads=False, include_combinatorial_heads=not structural)
    assert model._legal_ir_view_family_candidates() == ()
    after = [model._legal_ir_view_distribution(sample, target, use_sample_memory=False) for target in (four, six)]
    assert after == before
    model._nudge_decoded_embedding(sample, learning_rate=.175, update_sample_memory=False)
    assert len(model._legal_ir_view_family_candidates()) == 6
    expanded = model._legal_ir_view_distribution(sample, four, use_sample_memory=False)
    assert ma.cross_entropy_distribution_loss(expanded, four) > ma.cross_entropy_distribution_loss(before[0], four)


@pytest.mark.parametrize('operator',['decoded_embedding_nonview','decoded_embedding_structural'])
def test_actual_batch_patch_is_nonzero_memory_free_and_replayable(monkeypatch,operator):
    model, sample = configured(monkeypatch)
    initial = model.state.state_identity_record().digest
    tx = model.state.transaction().begin()
    model._apply_projection_update_batch([sample], update_targets=(operator,),
        learning_rate=.175, l2_regularization=0., update_backend='python_sparse_batch')
    patch = tx.capture_patch()
    assert {row.component for row in patch.rows} == set(NONVIEW[:6] if operator=="decoded_embedding_structural" else NONVIEW)
    assert all(row.after_exists and any(row.after_value) for row in patch.rows)
    tx.commit()
    result = model.state.state_identity_record().digest
    encoded = encode_patch(patch, base_state_identity=initial, result_state_identity=result,
                           base_version_id='controlled-empty-parent', sequence=0)
    replay = ma.ModalAutoencoderTrainingState()
    replay_patch(replay, encoded, expected_base_version_id='controlled-empty-parent', expected_sequence=0)
    assert replay.to_json() == model.state.to_json()
    assert result != initial


@pytest.mark.parametrize('order', [[], '', 'decoded_embedding_nonview', ['unknown'], ['family_logits']*2,
                                   [True], [1], {}, set(['family_logits'])])
def test_explicit_candidate_order_rejects_invalid_shape(order):
    with pytest.raises(ValueError, match='nonempty unique'):
        normalize_projection_candidate_update_order(order)
    with pytest.raises(worker.TrainingJobValidationError, match='nonempty unique'):
        worker.TrainingConfig(projection_candidate_update_order=order)


def test_worker_explicit_order_is_bound_and_default_identity_shape_unchanged(tmp_path):
    config = worker.TrainingConfig()
    assert 'projection_candidate_update_order' not in config.to_dict()
    assert 'projection_candidate_update_order' not in config.projection_kwargs()
    one = worker.TrainingConfig(projection_candidate_update_order=['decoded_embedding_nonview', 'combined'])
    two = replace(one, projection_candidate_update_order=('combined', 'decoded_embedding_nonview'))
    assert one.projection_kwargs()['projection_candidate_update_order'] == ('decoded_embedding_nonview', 'combined')
    parent = tmp_path/'parent.json'; parent.write_text(ma.ModalAutoencoderTrainingState().to_json())
    blob=parent.read_bytes()
    raw = dict(job_id='test',run_id='test',base_version_id='empty',
               base_checkpoint={'path':str(parent),'sha256':hashlib.sha256(blob).hexdigest(),'bytes':len(blob)},
               output_directory=str(tmp_path/'out'),code_identity='test',dataset_snapshot_id='d',split_snapshot_id='s',
               samples=[{'title':'5','section':'1','text':'The agency shall retain records.'}])
    default=worker.TrainingJobSpec.from_dict(raw)
    assert worker.TrainingJobSpec.from_dict(default.to_dict()).canonical_sha256 == default.canonical_sha256
    a=worker.TrainingJobSpec.from_dict({**raw,'training_config':one.to_dict()})
    b=worker.TrainingJobSpec.from_dict({**raw,'training_config':two.to_dict()})
    assert len({a.canonical_sha256,b.canonical_sha256,default.canonical_sha256}) == 3
    assert worker.TrainingJobSpec.from_dict(json.loads(json.dumps(a.to_dict()))).canonical_sha256 == a.canonical_sha256


def search_fixture(monkeypatch, *, regress=False, timeout=False):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    train=[SimpleNamespace(sample_id='train',normalized_text='training',embedding_vector=[1.])]
    tune=[SimpleNamespace(sample_id='tune',normalized_text='tuning',embedding_vector=[-1.])]
    calls={'updates':[], 'time':0.}
    monkeypatch.setattr(ma.time,'time',lambda:calls['time'])
    monkeypatch.setattr(ma.time,'perf_counter',lambda:calls['time'])
    monkeypatch.setattr(model,'_select_hard_examples_for_projection',lambda rows,**kw:list(rows))
    def evaluate(rows, **kw):
        assert calls['time'] < 60
        x=model.state.feature_embedding_weights.get('weight',[0.])[0]
        value=(1-x)**2
        return ma.AutoencoderEvaluation(len(rows),1.,0.,value,1.,0.,0.,{},cross_entropy_excess_loss=1.,
            legal_ir_losses={'legal_ir_multiview_total_loss':x if regress else 0.})
    def nudge(rows, *, update_targets,learning_rate,**kw):
        assert rows==train
        calls['updates'].append(tuple(update_targets))
        model.state.feature_embedding_weights['weight']=[learning_rate]
        if timeout: calls['time']=61.
        return {key:{} for key in ('gradient_norms_by_family','gradient_norms_by_head','head_family_gradient_norms',
            'head_family_update_norms','update_norms_by_family','update_norms_by_head')}
    monkeypatch.setattr(model,'evaluate',evaluate)
    monkeypatch.setattr(model,'_apply_projection_update_batch',nudge)
    monkeypatch.setattr(model,'decoder_preprojection_metrics',lambda rows,**kw:{'controlled_diagnostic':True})
    return model,train,tune,calls


def search(f, **kw):
    model,train,tune,calls=f
    return model.train_generalizable_projection(train,validation_samples=tune,epochs=1,max_seconds=60,
        max_line_search_attempts=2,legal_ir_bridge_names=('deontic_norms',),legal_ir_evaluate_provers=False,
        projection_update_backend='python_sparse_batch',**kw)


def test_default_candidate_order_and_explicit_family_cap(monkeypatch):
    original=search_fixture(monkeypatch)
    original_report=search(original)
    assert tuple(row['update'] for row in original_report['epoch_reports'][0]['candidate_reports']) == DEFAULT_PROJECTION_CANDIDATE_ORDER
    assert 'decoder_preprojection_observation' not in original_report
    explicit=search_fixture(monkeypatch)
    result=search(explicit,projection_candidate_update_order=('decoded_embedding_nonview','combined'),projection_max_update_families=1)
    assert set(explicit[3]['updates']) == {('decoded_embedding_nonview',)}
    assert result['projection_update_families']['family_cap_policy']=='take_prefix_after_explicit_order_selection'
    assert result['decoder_preprojection_observation']['changes_acceptance'] is False


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
@pytest.mark.parametrize('failure',['regress','timeout'])
@pytest.mark.parametrize('operator',['decoded_embedding_nonview','decoded_embedding_structural'])
def test_opt_in_keeps_guards_and_exact_rollback(monkeypatch,mode,failure,operator):
    f=search_fixture(monkeypatch,**{failure:True})
    before=f[0].state.to_json()
    report=search(f,projection_optimizer_mode=mode,projection_candidate_update_order=(operator,))
    assert report['accepted_epochs']==0
    assert f[0].state.to_json()==before
    assert report['epoch_reports'][0]['committed_objective_delta']==0


@pytest.mark.parametrize('operator',['decoded_embedding_nonview','decoded_embedding_structural'])
def test_nonview_rejects_regularization_before_evaluation(monkeypatch,operator):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    monkeypatch.setattr(model,'evaluate',lambda *a,**kw:pytest.fail('invalid order must fail before evaluation'))
    with pytest.raises(ValueError,match='zero l2_regularization'):
        model.train_generalizable_projection([],projection_candidate_update_order=[operator],l2_regularization=.1)
    with pytest.raises(worker.TrainingJobValidationError,match='zero l2_regularization'):
        worker.TrainingConfig(projection_candidate_update_order=[operator],l2_regularization=.1)


def test_raw_projection_metrics_are_separate_bounded_and_read_only(monkeypatch):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    sample=SimpleNamespace(sample_id='control',embedding_vector=[1.,0.])
    calls=[]
    def decoded(sample,**kw):
        calls.append(kw)
        return [.5,.5]
    monkeypatch.setattr(model,'_decoded_for',decoded)
    before=model.state.to_json()
    report=model.decoder_preprojection_metrics([sample])
    assert calls==[{'use_sample_memory':False,'apply_reconstruction_projection':False}]
    assert report['reconstruction_loss_mean']==.25 and report['used_for_acceptance'] is False
    assert report['complete'] and report['finite'] and model.state.to_json()==before
    report=model.decoder_preprojection_metrics([sample],stop_requested=lambda:True)
    assert report['observed_sample_count']==0 and report['reconstruction_loss_mean'] is None
    assert not report['complete'] and len(calls)==1


def test_actual_decoder_raw_branch_reveals_target_projection_without_changing_metric(monkeypatch):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    sample=SimpleNamespace(sample_id='controlled',embedding_vector=[1.,0.])
    monkeypatch.setattr(model,'_base_decoded_for',lambda sample:[1.,0.])
    names=('_compiler_quality_embedding_adjustment','_logic_signature_embedding_adjustment',
           '_round_trip_signal_embedding_adjustment','_decompiler_plan_embedding_adjustment',
           '_predicate_argument_embedding_adjustment','_family_embedding_adjustment',
           '_semantic_slot_embedding_adjustment','_family_semantic_slot_embedding_adjustment',
           '_semantic_slot_legal_ir_view_embedding_adjustment','_family_semantic_slot_legal_ir_view_embedding_adjustment',
           '_family_legal_ir_view_embedding_adjustment','_legal_ir_view_embedding_adjustment','_legacy_embedding_tail_adjustment')
    for name in names: monkeypatch.setattr(model,name,lambda sample,**kw:[0.,0.])
    monkeypatch.setattr(model,'_feature_embedding_adjustment',lambda sample,**kw:[.5,.5])
    assert model._decoded_for(sample,use_sample_memory=False)==[1.,0.]
    assert model._decoded_for(sample,use_sample_memory=False,apply_reconstruction_projection=False)==[1.5,.5]
    diagnostic=model.decoder_preprojection_metrics([sample])
    assert diagnostic['reconstruction_loss_mean']==.25 and diagnostic['used_for_acceptance'] is False


def test_structural_order_is_explicit_in_worker_job_policy():
    config=worker.TrainingConfig(projection_candidate_update_order=['decoded_embedding_structural'])
    assert config.projection_kwargs()['projection_candidate_update_order']==('decoded_embedding_structural',)
    assert worker.TrainingConfig.from_dict(config.to_dict())==config


@pytest.mark.parametrize('operator',['decoded_embedding_nonview','decoded_embedding_structural'])
@pytest.mark.parametrize('backend,device',[('cuda_resident','python'),(' CUDA_RESIDENT ','python'),('auto','torch_cuda')])
def test_new_operators_reject_unsupported_cuda_before_evaluation(monkeypatch,operator,backend,device):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    # Simulate backend selection; do not import/use CUDA or allocate a device.
    monkeypatch.setattr(model,'compute_backend',device)
    monkeypatch.setattr(model,'evaluate',lambda *args,**kw:pytest.fail('unsupported backend evaluated'))
    before=model.state.to_json()
    with pytest.raises(ValueError,match='do not support cuda_resident'):
        model.train_generalizable_projection([],projection_candidate_update_order=[operator],
                                             projection_update_backend=backend)
    assert model.state.to_json()==before


@pytest.mark.parametrize('operator',['decoded_embedding_nonview','decoded_embedding_structural'])
def test_direct_new_operator_batch_rejects_unsupported_cuda_transactionally(operator):
    model=ma.AdaptiveModalAutoencoder(compute_device='python')
    before=model.state.state_identity_record()
    with pytest.raises(ValueError,match='do not support cuda_resident'):
        model._apply_projection_update_batch([],update_targets=[operator],learning_rate=.175,
                                            l2_regularization=0.,update_backend='cuda_resident')
    assert model.state.state_identity_record()==before
    assert model.state._active_state_transaction is None
