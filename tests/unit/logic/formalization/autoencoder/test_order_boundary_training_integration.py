"""Trainer integration controls; synthetic losses confer no fidelity or admission."""
from copy import deepcopy
import types

import pytest

torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_long_span_source_value_training import prepared
from .test_long_span_cardinality_training import evaluated


@pytest.fixture(autouse=True)
def one_cpu():
    prior=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(prior)


def fit(model,train,tune,options,**extra):
    return subject.train(model,train,tune,cardinality_weight=.25,source_value_weight=.25,
        count_exposure='balanced_all',**options,**extra)


@pytest.mark.parametrize('bad',[True,-.1,1.1,float('nan'),float('inf'),'0.25',None])
def test_generated_boundary_weight_rejected_before_private_copy(monkeypatch,bad):
    model,_,train,tune,options=prepared()
    monkeypatch.setattr(subject,'deepcopy',lambda _:pytest.fail('copied before weight validation'))
    with pytest.raises(ValueError,match='generated-boundary weight'):
        fit(model,train,tune,options,generated_boundary_weight=bad)


@pytest.mark.parametrize('bad',[{},[],False,{'preparation':{}},{'preparation':{},'embedding_observations':{},'validation':[]}])
def test_augmentation_envelope_is_closed(monkeypatch,bad):
    model,_,train,tune,options=prepared()
    monkeypatch.setattr(subject,'deepcopy',lambda _:pytest.fail('copied before input validation'))
    with pytest.raises(ValueError,match='closed order-augmentation'):
        fit(model,train,tune,options,order_augmentation=bad)


def fake_boundary(monkeypatch,*,empty=False,expired=False):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as boundary
    seen=[]
    def collect(model,rows,**kw):
        assert all(set(row)=={'id','input'} for row in rows)
        assert kw['max_sites_per_row']==2 and 'training_counts_by_id' not in kw
        seen.append(deepcopy(rows))
        if expired:raise TimeoutError('synthetic collection deadline')
        return {'rows':rows}
    def loss(t,model,col,counts,**kw):
        assert t is torch and all(row['id'] in counts for row in col['rows'])
        assert all(type(n) is int and 1<=n<=32 for n in counts.values())
        # A differentiable synthetic scalar isolates the trainer's optional seam.
        parameter=next(p for p in model.parameters() if p.requires_grad)
        value=parameter.square().mean()+.125
        return dict(loss=None if empty else value,receipt=dict(synthetic=True,
            row_ids=[r['id'] for r in col['rows']],counts={r['id']:counts[r['id']] for r in col['rows']},
            loss=None if empty else float(value.detach())))
    monkeypatch.setattr(boundary,'collect_source_boundary_prefixes',collect)
    monkeypatch.setattr(boundary,'generated_boundary_loss',loss)
    return seen


def test_disabled_boundary_never_collects_or_attaches_new_report(monkeypatch):
    model,_,train,tune,options=prepared()
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as boundary
    monkeypatch.setattr(boundary,'collect_source_boundary_prefixes',lambda *a,**k:pytest.fail('disabled rollout'))
    result=fit(model,train,tune,options,generated_boundary_weight=0.)
    assert 'generated_boundary_weight' not in result['report']
    assert all('generated_boundary' not in u for u in result['report']['committed_updates'])


def test_boundary_adds_training_loss_once_without_mutating_caller(monkeypatch):
    model,_,train,tune,options=prepared();before=core.tensor_digest(model)
    saved=deepcopy((train,tune,options));seen=fake_boundary(monkeypatch)
    result=fit(model,train,tune,options,generated_boundary_weight=.25)
    assert core.tensor_digest(model)==before and (train,tune,options)==saved
    report=result['report']; assert len(seen)==report['optimizer_steps']==2
    training_counts={r['id']:r['clause_count'] for r in options['training_references']}
    for update,rows in zip(report['committed_updates'],seen):
        assert update['decoder_row_ids']==[r['id'] for r in rows]
        assert update['generated_boundary']['counts']=={r['id']:training_counts[r['id']] for r in rows}
        expected=update['weighted_token_ce']+.25*update['count_ce']+.25*update['source_value_ce']
        expected+=report['config']['reconstruction_weight']*update['raw_reconstruction_mse']
        expected+=.25*update['generated_boundary']['loss']
        assert update['objective']==pytest.approx(expected,abs=1e-6)
    assert report['generated_boundary_used_for_selection'] is False
    assert all(report[k] is False for k in subject.FALSE)


def test_zero_observed_sites_preserve_exact_ordinary_updates(monkeypatch):
    model,_,train,tune,options=prepared()
    plain=fit(model,train,tune,options)
    fake_boundary(monkeypatch,empty=True)
    extra=fit(model,train,tune,options,generated_boundary_weight=.25)
    for role in ('state_dict','last_complete_attempt_state_dict'):
        assert all(torch.equal(v,extra[role][k]) for k,v in plain[role].items())
    assert plain['predictions']==extra['predictions']
    assert plain['last_complete_attempt_predictions']==extra['last_complete_attempt_predictions']
    assert all(u['generated_boundary']['loss'] is None for u in extra['report']['committed_updates'])


def test_boundary_deadline_cannot_commit_partial_update(monkeypatch):
    model,_,train,tune,options=prepared();fake_boundary(monkeypatch,expired=True)
    result=fit(model,train,tune,options,generated_boundary_weight=.25)
    assert result['report']['optimizer_steps']==0
    assert result['report']['stopped_reason']=='deadline_during_generated_boundary'
    assert result['report']['committed_updates']==[]
    assert result['report']['selected_epoch']==0
    assert all(torch.equal(v,model.state_dict()[k]) for k,v in result['state_dict'].items())


def test_boundary_training_cannot_override_generated_fidelity_regression(monkeypatch):
    model,_,train,tune,options=prepared();fake_boundary(monkeypatch)
    observations=[evaluated(options,ce=2.),evaluated(options,ce=.1,
        mutate=lambda target:target['rules'][0].update(actor='agency'))]
    for item in observations:item['source_values']=dict(cross_entropy=.01,predictions=[])
    observed=iter(observations);monkeypatch.setattr(subject,'_evaluate',lambda *a:next(observed))
    options['curriculum']=options['curriculum'][:1]
    options['curriculum'][0]['training_ids']=[r['id'] for r in train]
    result=fit(model,train,tune,options,generated_boundary_weight=.25)
    assert result['report']['selected_epoch']==0
    assert any('actor' in reason for reason in result['report']['history'][0]['rejection_reasons'])
