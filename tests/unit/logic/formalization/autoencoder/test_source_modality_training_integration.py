"""Auxiliary source-bank wiring, transaction boundaries and unchanged defaults."""
from copy import deepcopy
import sys
from types import ModuleType, SimpleNamespace

import pytest

torch = pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_context_boundary_training_runner import fake_context_boundary
from .test_ordered_clause_recurrent_training_runner import real_fixture


@pytest.fixture(autouse=True)
def one_cpu():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def fit(model, train, tune, options, contexts, **extra):
    return subject.train(model, train, tune, source_contexts=contexts, source_value_weight=.25,
        cardinality_weight=.25, count_exposure='balanced_all', action_contrastive_weight=.05,
        non_action_learning_rate_multiplier=10., generated_boundary_weight=.05, **options, **extra)


def fake_auxiliary(monkeypatch, *, expire=None, clock=None):
    owner = ModuleType(package.__name__+'.source_modality_auxiliary_training')
    observed = dict(bindings=[], estimates=[], preparations=[], steps=[], gradients=[], models=[])

    def binding(bank, training_rows, validation_rows, *, source_contexts, codec, deadline):
        observed['bindings'].append((training_rows, validation_rows, source_contexts, codec))
        return dict(synthetic_binding=True)

    def estimate(bank, *, max_optimizer_steps):
        assert bank == {'synthetic_training_bank': True}
        observed['estimates'].append(max_optimizer_steps)
        return 16384

    def prepare(torch, model, bank, *, codec, input_transform, seed, deadline, max_optimizer_steps):
        assert bank == {'synthetic_training_bank': True}
        observed['preparations'].append((model, seed, max_optimizer_steps))
        if expire == 'preparation':
            raise TimeoutError('synthetic preparation deadline')
        return SimpleNamespace(receipt={'synthetic': True, 'seed': seed}, model=model)

    def loss(torch, model, cache, *, committed_step, deadline):
        assert cache.model is model
        observed['models'].append(model)
        observed['steps'].append(committed_step)
        if expire == 'loss':
            parameter = next(p for p in model.parameters() if p.requires_grad)
            parameter.grad = torch.ones_like(parameter)
            raise TimeoutError('synthetic auxiliary deadline')
        width = model.non_action_head.field_readout.out_features//3
        weight = model.non_action_head.field_readout.weight[width:2*width]
        value = (weight+1.).square().mean()+.125

        def hook(gradient):
            observed['gradients'].append(float(gradient))
            if expire == 'backward':
                clock[0] = 1e9
            return gradient

        value.register_hook(hook)
        return dict(loss=value, receipt=dict(synthetic=True, committed_step=committed_step,
            mean_cross_entropy=float(value.detach()), elapsed_seconds=0., rows=6))

    owner.validate_training_binding = binding
    owner.estimate_training_work_bytes = estimate
    owner.prepare_tensor_cache = prepare
    owner.modality_loss = loss
    monkeypatch.setitem(sys.modules, owner.__name__, owner)
    monkeypatch.setattr(package, 'source_modality_auxiliary_training', owner, raising=False)
    return observed


def same(left, right):
    for role in ('state_dict', 'last_complete_attempt_state_dict'):
        assert set(left[role]) == set(right[role])
        assert all(torch.equal(value, right[role][name]) for name, value in left[role].items())
    a,b = deepcopy(left['report']),deepcopy(right['report'])
    a.pop('elapsed_seconds');b.pop('elapsed_seconds')
    assert a == b
    assert left['predictions'] == right['predictions']
    assert left['last_complete_attempt_predictions'] == right['last_complete_attempt_predictions']


def test_disabled_branch_does_not_import_prepare_or_attach_graph(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    fake_context_boundary(monkeypatch)
    monkeypatch.setitem(sys.modules, package.__name__+'.source_modality_auxiliary_training', None)
    implicit = fit(model,train,tune,options,contexts)
    explicit = fit(model,train,tune,options,contexts, auxiliary_source_modality_weight=0.,
        auxiliary_source_modality_bank=None, generated_boundary_retry_on_mismatch=False)
    same(implicit,explicit)
    assert not any(k.startswith('auxiliary_source_modality') for k in explicit['report'])
    assert 'generated_boundary_retry_on_mismatch' not in explicit['report']


@pytest.mark.parametrize('value', [None,0,1,'true'])
def test_retry_switch_requires_actual_boolean(monkeypatch,value):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='Boolean boundary retry'):
        fit(model,train,tune,options,contexts,generated_boundary_retry_on_mismatch=value)


def test_retry_is_explicitly_forwarded_only_to_boundary_loss(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    seen = fake_context_boundary(monkeypatch)
    result = fit(model,train,tune,options,contexts,generated_boundary_retry_on_mismatch=True)
    assert len(seen) == 2
    assert all(row['loss_kwargs']['retry_on_replay_mismatch'] is True for row in seen)
    report = result['report']
    assert report['generated_boundary_retry_on_mismatch'] is True
    assert report['generated_boundary_retry_tolerance_changed'] is False
    assert report['generated_boundary_retry_limit_per_original_batch'] == 1
    assert report['generated_boundary_retry_max_updates_estimated'] == 2
    assert report['optimizer_steps'] == 2
    assert all(report[k] is False for k in subject.FALSE)


@pytest.mark.parametrize('extra', [dict(generated_source_margin_weight=.01),dict(joint_generated_replay=True)])
def test_retry_rejects_another_owner_of_boundary_replay(monkeypatch,extra):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='standalone contextual all-trainable boundary path'):
        fit(model,train,tune,options,contexts,generated_boundary_retry_on_mismatch=True,**extra)


@pytest.mark.parametrize('weight', [True,None,-.1,1.01,float('inf'),float('nan'),'0.05'])
def test_invalid_weight_rejected_before_model_copy(monkeypatch,weight):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='auxiliary source-modality weight'):
        fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=weight)


@pytest.mark.parametrize('weight,bank', [(0.,{}),(.05,None),(.05,[]),(.05,'bank')])
def test_weight_and_bank_must_be_explicitly_paired(monkeypatch,weight,bank):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='bank and positive weight must be paired'):
        fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=weight,
            auxiliary_source_modality_bank=bank)


@pytest.mark.parametrize('extra', [dict(generated_source_margin_weight=.01),
    dict(generated_source_margin_replay=True),dict(joint_generated_replay=True),
    dict(generated_field_weight=.05)])
def test_auxiliary_trial_rejects_unmeasured_replay_combinations(monkeypatch,extra):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='original all-trainable boundary path'):
        fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
            auxiliary_source_modality_bank={'synthetic_training_bank':True},**extra)


def test_auxiliary_loss_is_added_once_to_normal_backward_and_commit(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    fake_context_boundary(monkeypatch)
    observed = fake_auxiliary(monkeypatch)
    before = core.tensor_digest(model)
    rng = torch.get_rng_state().clone()
    result = fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
        auxiliary_source_modality_bank={'synthetic_training_bank':True})
    report = result['report']
    assert report['optimizer_steps'] == 2
    assert observed['steps'] == [0,1]
    assert observed['gradients'] == pytest.approx([.05,.05])
    assert len(observed['preparations']) == 1
    assert observed['preparations'][0][0] is not model
    assert all(m is observed['preparations'][0][0] for m in observed['models'])
    assert observed['estimates'] == [2]
    assert observed['bindings'] == [(train,tune,contexts,options['codec'])]
    assert report['auxiliary_source_modality_binding_receipt'] == dict(synthetic_binding=True)
    assert report['auxiliary_source_modality_max_updates_estimated'] == 2
    assert report['auxiliary_source_modality_committed_updates'] == 2
    assert report['auxiliary_source_modality_presentations'] == 12
    assert report['auxiliary_source_modality_presentations_per_class'] == {'O':4,'P':4,'F':4}
    assert report['auxiliary_source_modality_presentations_per_stratum'] == 2
    assert report['auxiliary_source_modality_used_for_selection'] is False
    assert report['auxiliary_source_modality_normalization_refitted'] is False
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    for step,update in enumerate(report['committed_updates']):
        receipt = update['auxiliary_source_modality']
        assert receipt['zero_based_committed_step'] == step
        assert receipt['receipt']['committed_step'] == step
        assert receipt['weighted_loss'] == pytest.approx(.05*receipt['receipt']['mean_cross_entropy'])
        assert update['objective'] == pytest.approx(receipt['base_objective']+receipt['weighted_loss'],rel=2e-7)
    assert all(report[k] is False for k in subject.FALSE)
    assert core.tensor_digest(model) == before
    assert torch.equal(torch.get_rng_state(),rng)


def test_bank_binding_failure_precedes_private_copy_and_cache(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    observed = fake_auxiliary(monkeypatch)
    owner = sys.modules[package.__name__+'.source_modality_auxiliary_training']
    def reject(*args,**kw):
        raise ValueError('actual cohort differs')
    owner.validate_training_binding = reject
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='actual cohort differs'):
        fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
            auxiliary_source_modality_bank={'synthetic_training_bank':True})
    assert observed['preparations'] == observed['estimates'] == []


def test_auxiliary_budget_rejected_before_private_copy_and_cache(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    observed = fake_auxiliary(monkeypatch)
    options['config']['max_memory_bytes'] = 1048576
    monkeypatch.setattr(subject,'deepcopy',lambda *a:pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError,match='trial tensor work exceeds budget'):
        fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
            auxiliary_source_modality_bank={'synthetic_training_bank':True})
    assert len(observed['bindings']) == 1 and observed['estimates'] == [2]
    assert observed['preparations'] == []


def test_expiry_after_clipping_discards_auxiliary_update(monkeypatch):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    fake_context_boundary(monkeypatch)
    clock = [0.]
    monkeypatch.setattr(subject.time,'monotonic',lambda:clock[0])
    observed = fake_auxiliary(monkeypatch)
    original_clip = torch.nn.utils.clip_grad_norm_
    def clip(*args,**kw):
        result = original_clip(*args,**kw)
        clock[0] = 1e9
        return result
    monkeypatch.setattr(torch.nn.utils,'clip_grad_norm_',clip)
    monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**kw:pytest.fail('step after deadline'))
    result = fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
        auxiliary_source_modality_bank={'synthetic_training_bank':True})
    assert result['report']['stopped_reason'] == 'deadline'
    assert result['report']['optimizer_steps'] == result['report']['auxiliary_source_modality_presentations'] == 0
    assert all(p.grad is None for m in observed['models'] for p in m.parameters())


@pytest.mark.parametrize('phase,reason', [('preparation','deadline_during_auxiliary_modality_preparation'),
    ('loss','deadline_during_auxiliary_modality'),('backward','deadline_after_auxiliary_modality_backward')])
def test_deadline_does_not_commit_auxiliary_exposure_or_optimizer_step(monkeypatch,phase,reason):
    model,_,train,tune,options,contexts = real_fixture(monkeypatch)
    fake_context_boundary(monkeypatch)
    clock = [0.]
    monkeypatch.setattr(subject.time,'monotonic',lambda:clock[0])
    observed = fake_auxiliary(monkeypatch,expire=phase,clock=clock)
    before = core.tensor_digest(model)
    monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**kw:pytest.fail('step after deadline'))
    result = fit(model,train,tune,options,contexts,auxiliary_source_modality_weight=.05,
        auxiliary_source_modality_bank={'synthetic_training_bank':True})
    report = result['report']
    assert report['stopped_reason'] == reason
    assert report['optimizer_steps'] == report['auxiliary_source_modality_committed_updates'] == 0
    assert report['auxiliary_source_modality_presentations'] == 0
    assert report['committed_updates'] == []
    assert observed['steps'] == ([] if phase=='preparation' else [0])
    assert all(p.grad is None for m in observed['models'] for p in m.parameters())
    assert core.tensor_digest(model) == before
