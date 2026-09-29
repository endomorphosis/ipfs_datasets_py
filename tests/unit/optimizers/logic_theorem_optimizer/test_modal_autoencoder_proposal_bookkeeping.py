"""Exact sparse proposal bookkeeping and common-deadline regressions.

Controlled models below never invoke native targets, Lean or external encoders.
"""
from collections import Counter
from dataclasses import replace
import math
import random
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_transaction import (
    ModalAutoencoderStateTransaction, StateTransactionClosedError, StateTransactionConflictError,
)


def legacy_norm(transaction, rate):
    """Previous snapshot/flatten implementation, retained only as a test oracle."""
    before, after = {}, {}
    for row in transaction.iter_row_deltas():
        if row.component not in ma.LEGAL_IR_TRAINABLE_HEAD_FIELDS:
            continue
        for exists, value, destination in ((row.before_exists, row.before_value, before),
                                           (row.after_exists, row.after_value, after)):
            if exists:
                for path, number in ma._flatten_numeric_head_values(value).items():
                    destination.setdefault(row.component, {})[(str(row.key), *path)] = number
    return ma._legal_ir_trainable_flat_delta_norm_report({
        field: (before.get(field, {}), after.get(field, {}))
        for field in ma.LEGAL_IR_TRAINABLE_HEAD_FIELDS}, learning_rate=rate)


def test_discard_restores_exact_state_identity_without_capturing(monkeypatch):
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"old": [1.,2.], "keep": [3.]}, applied_todo_ids=['old'])
    identity = state.state_identity_record(); stats = state.identity_stats
    keep = state.feature_embedding_weights['keep']
    transaction = state.transaction().begin()
    state.feature_embedding_weights['old'][0] = 9.
    state.feature_embedding_weights['new'] = [4.,5.]
    state.applied_todo_ids.append('new')
    monkeypatch.setattr(transaction, 'capture_patch', lambda: pytest.fail('discard must not capture'))
    transaction.discard()
    assert state.feature_embedding_weights == {'old':[1.,2.], 'keep':[3.]}
    assert state.feature_embedding_weights['keep'] is keep
    assert state.applied_todo_ids == ['old']
    assert state.state_identity_record() == identity and state.identity_stats == stats
    assert transaction.patch is None and transaction.rolled_back and not transaction.active
    with pytest.raises(StateTransactionClosedError): transaction.discard()


def test_saved_candidate_is_isolated_from_discard_and_later_mutation():
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={'x':[1.,2.]})
    transaction = state.transaction().begin()
    state.feature_embedding_weights['x'][0] = 7.
    candidate = transaction.capture_patch()
    transaction.discard()
    assert candidate.rows[0].after_value == [7.,2.]
    with state.transaction(): state.feature_embedding_weights['x'][1] = 8.
    assert candidate.rows[0].before_value == [1.,2.]
    assert candidate.rows[0].after_value == [7.,2.]
    candidate.rows[0].after_value[0] = 99.
    assert state.feature_embedding_weights['x'] == [1.,8.]


def test_public_row_delta_snapshots_retain_no_aliases():
    state = ma.ModalAutoencoderTrainingState(decompiler_plan_embedding_weights={'x':[1.,2.]})
    transaction = state.transaction().begin()
    state.decompiler_plan_embedding_weights['x'][0] = 3.
    rows = tuple(transaction.iter_row_deltas())
    state.decompiler_plan_embedding_weights['x'][1] = 4.
    assert rows[0].after_value == [3.,2.]
    rows[0].before_value[0] = 99.
    transaction.discard()
    assert state.decompiler_plan_embedding_weights['x'] == [1.,2.]


def test_borrowed_internal_rows_are_filtered_and_owner_checked(monkeypatch):
    state = ma.ModalAutoencoderTrainingState()
    transaction = state.transaction().begin()
    state.feature_embedding_weights['irrelevant'] = [1.] * 384
    state.legal_ir_view_logits['deontic'] = .5
    monkeypatch.setattr(transaction, 'capture_patch', lambda: pytest.fail('borrowed access copied'))
    assert [row.component for row in transaction._iter_borrowed_row_deltas({'legal_ir_view_logits'})] == ['legal_ir_view_logits']
    errors=[]
    def other_thread():
        try: list(transaction._iter_borrowed_row_deltas({'legal_ir_view_logits'}))
        except BaseException as error: errors.append(error)
    thread=threading.Thread(target=other_thread); thread.start(); thread.join(2)
    assert len(errors)==1 and isinstance(errors[0], StateTransactionConflictError)
    transaction.discard()
    with pytest.raises(StateTransactionClosedError): list(transaction._iter_borrowed_row_deltas({'legal_ir_view_logits'}))


@pytest.mark.parametrize('seed', range(12))
def test_streaming_norm_equals_legacy_report_exactly(seed, monkeypatch):
    rng=random.Random(seed)
    state=ma.ModalAutoencoderTrainingState(
        decompiler_plan_embedding_weights={f'r{i}':[rng.uniform(-1e3,1e3) for _ in range(24)] for i in range(5)},
        feature_legal_ir_view_logits={f'f{i}':{key:rng.uniform(-4,4) for key in ('2','10','deontic','cec')} for i in range(4)})
    tx=state.transaction().begin()
    state.decompiler_plan_embedding_weights['r0'][0] += .25
    state.decompiler_plan_embedding_weights['r1'] = [rng.random() for _ in range(17)]
    del state.decompiler_plan_embedding_weights['r2']
    state.decompiler_plan_embedding_weights['insert'] = [rng.random() for _ in range(24)]
    state.feature_legal_ir_view_logits['f0']['cec'] = rng.random()
    state.feature_legal_ir_view_logits['new'] = {'deontic':-2.,'frame_logic':.125}
    state.feature_embedding_weights['not-in-norm'] = [rng.random() for _ in range(384)]
    expected=legacy_norm(tx, .175)
    monkeypatch.setattr(tx,'capture_patch',lambda:pytest.fail('norm copied patch'))
    monkeypatch.setattr(ma,'_flatten_numeric_head_values',lambda value:pytest.fail('ordinary norm flattened coordinates'))
    assert ma.legal_ir_trainable_head_transaction_delta_norm_report(tx,state,learning_rate=.175)==expected
    tx.discard()


def test_norm_preserves_stringified_key_collision_and_leaf_merge_semantics():
    state=ma.ModalAutoencoderTrainingState(feature_legal_ir_view_logits={
        1:{'deontic':1.,'old':3.}, '1':{'cec':2.}, 'mixed':{1:{'a':1.,'b':2.},'1':{'a':3.,'c':4.}}})
    tx=state.transaction().begin()
    state.feature_legal_ir_view_logits[1]['deontic']=2.
    state.feature_legal_ir_view_logits['1']['cec']=5.
    state.feature_legal_ir_view_logits['mixed'][1]['b']=8.
    assert ma.legal_ir_trainable_head_transaction_delta_norm_report(tx,state,learning_rate=.5)==legacy_norm(tx,.5)
    tx.discard()


def test_norm_preserves_nonfinite_and_nonnumeric_leaf_behavior():
    state=ma.ModalAutoencoderTrainingState(feature_legal_ir_view_logits={'x':{'a':1.,'ignored':True}})
    tx=state.transaction().begin()
    state.feature_legal_ir_view_logits['x']={'a':float('nan'),'b':float('inf'),'valid':2.,'ignored':'text'}
    expected=legacy_norm(tx,.25)
    assert ma.legal_ir_trainable_head_transaction_delta_norm_report(tx,state,learning_rate=.25)==expected
    assert expected['finite'] is False and expected['scalar_update_counts_by_head']=={'feature_legal_ir_view_logits':1}
    tx.discard()


def test_norm_preserves_whole_component_replacement_scope():
    state=ma.ModalAutoencoderTrainingState(legal_ir_view_logits={'deontic':1.})
    tx=state.transaction().begin();state.legal_ir_view_logits={'deontic':2.}
    assert ma.legal_ir_trainable_head_transaction_delta_norm_report(tx,state,learning_rate=.5)==legacy_norm(tx,.5)
    tx.discard()


def test_streamed_list_order_is_lexical_not_numeric():
    vector=list(range(14))
    assert [path for path,value in ma._iter_numeric_head_values_sorted(vector)] == sorted((str(i),) for i in range(14))
    assert list(ma._iter_numeric_head_values_sorted(vector)) == sorted(ma._flatten_numeric_head_values(vector).items())


def fixture(monkeypatch, *, update=None, evaluate_loss=None):
    state=ma.ModalAutoencoderTrainingState(legal_ir_view_logits={'x':0.})
    model=ma.AdaptiveModalAutoencoder(state=state,compute_device='python')
    training=[SimpleNamespace(sample_id='train',normalized_text='training',embedding_vector=[1.])]
    tuning=[SimpleNamespace(sample_id='tune',normalized_text='tuning',embedding_vector=[-1.])]
    calls={'time':0.,'updates':0,'evaluation_times':[]}
    monkeypatch.setattr(ma.time,'time',lambda:calls['time'])
    monkeypatch.setattr(ma.time,'perf_counter',lambda:calls['time'])
    monkeypatch.setattr(model,'_select_hard_examples_for_projection',lambda values,**kwargs:list(values))
    def evaluate(rows,**kwargs):
        calls['evaluation_times'].append(calls['time'])
        x=state.legal_ir_view_logits['x']
        value=evaluate_loss(x) if evaluate_loss else (1.-x)**2
        return ma.AutoencoderEvaluation(len(rows),1.,0.,value,1.,0.,0.,{},cross_entropy_excess_loss=1.)
    def nudge(rows,*,learning_rate,**kwargs):
        calls['updates']+=1
        state.legal_ir_view_logits['x']+=learning_rate
        if update: update(calls,state)
        return {name:{} for name in ('gradient_norms_by_family','gradient_norms_by_head',
            'head_family_gradient_norms','head_family_update_norms','update_norms_by_family','update_norms_by_head')}
    monkeypatch.setattr(model,'evaluate',evaluate);monkeypatch.setattr(model,'_apply_projection_update_batch',nudge)
    return model,training,tuning,calls


def run(f, mode, **kwargs):
    model,training,tuning,_=f
    options=dict(validation_samples=tuning,legal_ir_bridge_names=('deontic_norms',),legal_ir_evaluate_provers=False,
        epochs=1,max_seconds=60,max_line_search_attempts=2,projection_max_update_families=1,
        projection_update_backend='python_sparse_batch',projection_optimizer_mode=mode)
    options.update(kwargs)
    return model.train_generalizable_projection(training,**options)


def attempts(report):
    return [trial for epoch in report['epoch_reports'] for candidate in epoch['candidate_reports']
            for trial in candidate.get('attempt_reports',[candidate])]


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_common_deadline_skips_holdout_after_long_update(monkeypatch,mode):
    f=fixture(monkeypatch,update=lambda calls,state:calls.update(time=61.))
    initial=f[0].state.state_identity_record()
    report=run(f,mode)
    assert report['accepted_epochs']==0 and report['stopped_reason']=='projection_timeout'
    assert all(t<60 for t in f[3]['evaluation_times'])
    assert attempts(report)[0]['holdout_evaluated'] is False
    assert attempts(report)[0]['objective_delta'] is None
    assert f[0].state.state_identity_record()==initial
    assert report['epoch_reports'][0]['committed_objective_delta']==0.


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_common_deadline_rechecked_after_candidate_application(monkeypatch,mode):
    f=fixture(monkeypatch);initial=f[0].state.state_identity_record()
    original=ModalAutoencoderStateTransaction.apply_patch
    def slow_apply(tx,patch):
        original(tx,patch)
        if tx.label.startswith('projection-evaluate:'): f[3]['time']=61.
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'apply_patch',slow_apply)
    report=run(f,mode)
    assert report['accepted_epochs']==0 and report['stopped_reason']=='projection_timeout'
    assert len(f[3]['evaluation_times'])==2
    assert attempts(report)[0]['holdout_evaluated'] is False
    assert f[0].state.state_identity_record()==initial


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_timeout_preserves_earlier_guarded_candidate(monkeypatch,mode):
    def slow_second(calls,state):
        if calls['updates']==2: calls['time']=61.
    f=fixture(monkeypatch,update=slow_second)
    report=run(f,mode,projection_max_update_families=2)
    assert report['accepted_epochs']==1 and f[0].state.legal_ir_view_logits['x']==.175
    assert all(t<60 for t in f[3]['evaluation_times'])
    assert report['epoch_reports'][0]['committed_objective_delta']>0.
    assert f[0].state._active_state_transaction is None


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_rejected_attempt_captures_once_and_evaluation_discard_never_captures(monkeypatch,mode):
    f=fixture(monkeypatch,evaluate_loss=lambda x:1.)
    counts=Counter();original=ModalAutoencoderStateTransaction.capture_patch
    def capture(tx): counts[tx.label.split(':')[0]]+=1;return original(tx)
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',capture)
    report=run(f,mode)
    assert report['accepted_epochs']==0
    assert counts['projection-attempt']==len(attempts(report))==2
    assert counts['projection-evaluate']==0


def test_momentum_recaptures_only_actual_carried_proposals(monkeypatch):
    f=fixture(monkeypatch);counts=Counter();original=ModalAutoencoderStateTransaction.capture_patch
    def capture(tx): counts[tx.label]+=1;return original(tx)
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',capture)
    report=run(f,'guarded_adaptive',projection_momentum=.5,epochs=3)
    per_attempt=[value for key,value in counts.items() if key.startswith('projection-attempt:')]
    assert per_attempt==[1,2,2]
    assert [trial['adaptive_optimizer']['momentum_applied'] for trial in attempts(report)]==[False,True,True]
    assert report['accepted_epochs']==3


def test_positive_objective_with_ir_regression_stays_rejected_and_commit_delta_zero(monkeypatch):
    f=fixture(monkeypatch)
    original=f[0].evaluate
    def evaluate(rows,**kwargs):
        result=original(rows,**kwargs)
        return replace(result,legal_ir_losses={'legal_ir_multiview_total_loss':
            .1 if f[0].state.legal_ir_view_logits['x'] else 0.})
    monkeypatch.setattr(f[0],'evaluate',evaluate)
    report=run(f,'fixed')
    epoch=report['epoch_reports'][0]
    assert report['accepted_epochs']==0 and epoch['objective_delta']>0
    assert epoch['objective_before']==epoch['objective_after']
    assert epoch['committed_objective_delta']==0.
    assert any(trial['pareto_regressions'] for trial in attempts(report))


@pytest.mark.parametrize('prescreen',['shadow','enforce'])
def test_deadline_prevents_prescreen_evaluation_after_update(monkeypatch,prescreen):
    f=fixture(monkeypatch,update=lambda calls,state:calls.update(time=61.))
    initial=f[0].state.state_identity_record()
    report=run(f,'fixed',projection_prescreen_mode=prescreen)
    assert report['accepted_epochs']==0 and report['stopped_reason']=='projection_timeout'
    assert all(t<60 for t in f[3]['evaluation_times'])
    trial=attempts(report)[0]
    assert trial['holdout_evaluated'] is False and trial['objective_delta'] is None
    assert trial['projection_prescreen']['evaluation_skipped_reason']=='projection_timeout'
    assert f[0].state.state_identity_record()==initial


@pytest.mark.parametrize('prescreen',['shadow','enforce'])
@pytest.mark.parametrize('mode',['guarded_adaptive','productive_adaptive'])
def test_adaptive_capture_boundary_cannot_interact_with_prescreen(monkeypatch,prescreen,mode):
    f=fixture(monkeypatch)
    with pytest.raises(ValueError,match='prescreen and deadband off'):
        run(f,mode,projection_prescreen_mode=prescreen)
    assert f[3]['updates']==0 and not f[3]['evaluation_times']


def test_fixed_capture_retains_historical_after_prescreen_state(monkeypatch):
    f=fixture(monkeypatch)
    f[0].state.legal_ir_view_logits['prescreen-marker']=0.
    original=f[0].evaluate
    def evaluator_with_marker(rows,**kwargs):
        if rows[0].sample_id=='train' and f[0].state.legal_ir_view_logits['x']>0.:
            f[0].state.legal_ir_view_logits['prescreen-marker']=1.
        return original(rows,**kwargs)
    monkeypatch.setattr(f[0],'evaluate',evaluator_with_marker)
    report=run(f,'fixed',projection_prescreen_mode='shadow')
    assert report['accepted_epochs']==1
    assert f[0].state.legal_ir_view_logits['prescreen-marker']==1.


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_expired_update_skips_all_proposal_bookkeeping(monkeypatch,mode):
    f=fixture(monkeypatch,update=lambda calls,state:calls.update(time=61.))
    initial=f[0].state.state_identity_record()
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',lambda tx:pytest.fail('late capture'))
    monkeypatch.setattr(ma.GuardedAdaptiveProjection,'prepare',lambda *args,**kwargs:pytest.fail('late adaptive prepare'))
    report=run(f,mode)
    trial=attempts(report)[0]
    assert trial['candidate_snapshot_available'] is False
    assert trial['candidate_preparation_stopped_stage']=='after_projection_update'
    assert trial['trainable_legal_ir_head_norms']['update_norms_by_head']=={}
    assert 'parameter_delta_norm' not in trial.get('adaptive_optimizer',{})
    assert report['accepted_epochs']==0 and f[0].state.state_identity_record()==initial


@pytest.mark.parametrize('mode',['fixed','guarded_adaptive','productive_adaptive'])
def test_expired_capture_skips_prepare_and_candidate_application(monkeypatch,mode):
    f=fixture(monkeypatch);initial=f[0].state.state_identity_record()
    captures=[];original=ModalAutoencoderStateTransaction.capture_patch
    def capture(tx):
        captures.append(tx.label);result=original(tx);f[3]['time']=61.;return result
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',capture)
    monkeypatch.setattr(ma.GuardedAdaptiveProjection,'prepare',lambda *a,**kw:pytest.fail('late prepare'))
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'apply_patch',lambda *a:pytest.fail('late candidate application'))
    report=run(f,mode)
    trial=attempts(report)[0]
    assert len(captures)==1 and trial['candidate_snapshot_available'] is False
    assert trial['candidate_preparation_stopped_stage']=='after_candidate_capture'
    assert trial['objective_delta'] is None and trial['holdout_evaluated'] is False
    assert report['accepted_epochs']==0 and f[0].state.state_identity_record()==initial


@pytest.mark.parametrize('mode',['guarded_adaptive','productive_adaptive'])
@pytest.mark.parametrize('boundary',['prepare','recapture'])
def test_expired_momentum_preparation_skips_remaining_copies_and_retains_prior_epoch(monkeypatch,mode,boundary):
    f=fixture(monkeypatch);captures=Counter()
    original_capture=ModalAutoencoderStateTransaction.capture_patch
    def capture(tx):
        captures[tx.label]+=1;patch=original_capture(tx)
        if boundary=='recapture' and tx.label.startswith('projection-attempt:2:') and captures[tx.label]==2:
            f[3]['time']=61.
        return patch
    original_prepare=ma.GuardedAdaptiveProjection.prepare
    def prepare(*args,**kwargs):
        report=original_prepare(*args,**kwargs)
        if boundary=='prepare' and report['momentum_applied']:f[3]['time']=61.
        return report
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',capture)
    monkeypatch.setattr(ma.GuardedAdaptiveProjection,'prepare',prepare)
    monkeypatch.setattr(ma,'parameter_step_report',lambda *a:pytest.fail('late carried-parameter norm'))
    report=run(f,mode,projection_momentum=.5,epochs=2)
    trial=attempts(report)[-1]
    assert report['accepted_epochs']==1 and report['stopped_reason']=='projection_timeout'
    assert f[0].state.legal_ir_view_logits['x']==({'guarded_adaptive':.175,'productive_adaptive':.35}[mode])
    assert trial['candidate_preparation_stopped_stage']==('after_adaptive_prepare' if boundary=='prepare' else 'after_momentum_capture')
    assert trial['candidate_snapshot_available'] is False and trial['holdout_evaluated'] is False
    adaptive=trial['adaptive_optimizer']
    assert adaptive['momentum_applied'] is True and adaptive['momentum_carry_norm']>0
    assert 'parameter_delta_norm' not in adaptive
    assert adaptive['parameter_step_report_skipped_reason']=='projection_timeout'
    assert [count for label,count in captures.items() if label.startswith('projection-attempt:2:')]==[1 if boundary=='prepare' else 2]
    assert f[0].state._active_state_transaction is None


@pytest.mark.parametrize('prescreen',['shadow','enforce'])
def test_expired_prescreen_skips_snapshot_and_never_applies_missing_candidate(monkeypatch,prescreen):
    f=fixture(monkeypatch);initial=f[0].state.state_identity_record();original=f[0].evaluate
    def evaluate(rows,**kwargs):
        result=original(rows,**kwargs)
        if rows[0].sample_id=='train' and f[0].state.legal_ir_view_logits['x']>0.:
            f[0].state.legal_ir_view_logits['prescreen-touched']=1.
            f[3]['time']=61.
        return result
    monkeypatch.setattr(f[0],'evaluate',evaluate)
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',lambda *a:pytest.fail('late prescreen capture'))
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'apply_patch',lambda *a:pytest.fail('applied missing candidate'))
    report=run(f,'fixed',projection_prescreen_mode=prescreen,projection_prescreen_top_k=1)
    trial=attempts(report)[0]
    assert trial['candidate_preparation_stopped_stage']=='after_prescreen_evaluation'
    assert trial['acceptance_source']=='projection_timeout' and trial['objective_delta'] is None
    assert report['accepted_epochs']==0 and f[0].state.state_identity_record()==initial


@pytest.mark.parametrize('mode',['fixed','productive_adaptive'])
def test_same_head_earlier_winner_survives_later_snapshotless_timeout(monkeypatch,mode):
    f=fixture(monkeypatch,update=lambda calls,state:calls.update(time=61.) if calls['updates']==2 else None)
    captures=Counter();original=ModalAutoencoderStateTransaction.capture_patch
    def capture(tx):captures[tx.label]+=1;return original(tx)
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'capture_patch',capture)
    report=run(f,mode)
    assert report['accepted_epochs']==1 and f[0].state.legal_ir_view_logits['x']==.175
    assert attempts(report)[-1]['candidate_snapshot_available'] is False
    assert sum(count for label,count in captures.items() if label.startswith('projection-attempt:'))==1


def test_enforce_prescreen_does_not_relabel_snapshotless_timeout_as_rank_filter(monkeypatch):
    f=fixture(monkeypatch,update=lambda calls,state:calls.update(time=61.) if calls['updates']==2 else None)
    report=run(f,'fixed',projection_prescreen_mode='enforce',projection_prescreen_top_k=1)
    trial=attempts(report)[-1]
    assert trial['candidate_snapshot_available'] is False and trial['objective_delta'] is None
    assert trial['acceptance_source']=='projection_timeout'
    assert trial['projection_prescreen']['projection_timeout_filtered'] is True
    assert report['accepted_epochs']==0



def test_enforce_prescreen_retains_timeout_after_completed_snapshot_discard(monkeypatch):
    f=fixture(monkeypatch);initial=f[0].state.state_identity_record()
    original=ModalAutoencoderStateTransaction.discard
    def discard(tx):
        original(tx)
        if tx.label.startswith('projection-attempt:') and tx.label.endswith(':2'):
            f[3]['time']=61.
    monkeypatch.setattr(ModalAutoencoderStateTransaction,'discard',discard)
    report=run(f,'fixed',projection_prescreen_mode='enforce',projection_prescreen_top_k=1)
    trials=attempts(report)
    assert len(trials)==2 and trials[-1]['candidate_snapshot_available'] is True
    assert trials[-1]['candidate_preparation_stopped_stage'] is None
    # The selected deferred trial also has no measured holdout objective delta.
    for trial in trials:
        assert trial['acceptance_source']=='projection_timeout'
        assert trial['objective_delta'] is None and trial['holdout_evaluated'] is False
        assert trial['validation_evaluation_skipped_reason']=='projection_timeout'
    assert report['accepted_epochs']==0 and f[0].state.state_identity_record()==initial
