"""Sealed runner and tiny real training contracts; no corpus qualification."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('_ordered_recurrent_runner_tests',ROOT/'scripts/ops/autoencoder/benchmark_ordered_clause_recurrent_training.py')
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,allow_nan=False))


@pytest.mark.parametrize('field,value',[
    ('dimensions',[8,384]),('fit_count',18),('fresh_initialization',False),
    ('validation_pairs_added_to_training',True),('teacher_distillation_used',True),
    ('selection_unchanged',False),('fixed_encoder_context_tokens',8192),('fixed_decoder_output_limit',1024),
    ('temperature',.1),('action_contrastive_temperature',0),('syntax_forced',True),('closure_forced',True),
    ('full_vocabulary_retained',False),('baseline_replay_required',False),('expected_optimizer_steps_per_arm',339),
    ('expected_source_value_presentations_per_arm',0),('no_downloads',False),('production_promotion_allowed',True),
    ('additional_candidate_control','source-shuffle'),('recurrent_parameter_delta',0),
    ('source_segmentation_availability_is_an_inference_feature',False)])
def test_changed_budget_context_or_authority_is_rejected(field,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[field]=value
    with pytest.raises(ValueError,match='fixed ordered-clause-recurrent'):subject.validate_plan(plan)


def test_exact_registered_jobs_and_loss_generation_separation():
    jobs=subject.jobs()
    assert [(d,s,a['name']) for d,s,a in jobs]==[(d,s,a) for d in (8,384,768)
        for s in (1729,2718) for a in ('action-contrastive','recurrent-clause')]
    assert len(jobs)==12 and len(subject.CONTROLS)==8
    assert 2*sum(8+int(a['recurrent']) for _,_,a in jobs)==204
    assert all(a['action_contrastive_weight']==.05 and a['head_kind']=='clauses'
        and a['factorized'] and not a['order_augmentation'] and a['generated_boundary_weight']==0 for _,_,a in jobs)
    jobs[0][2]['action_contrastive_weight']=.5
    assert subject.jobs()[0][2]['action_contrastive_weight']==.05
    assert subject.FIXED['temperature']==0 and subject.FIXED['action_contrastive_temperature']==.1
    assert all(v is False for v in subject.FALSE.values())


def context_fixture(tmp_path,monkeypatch):
    parent_manifest=tmp_path/'parent-manifest.json';parent_plan=tmp_path/'parent-plan.json'
    write(parent_manifest,{});write(parent_plan,{})
    paths={}
    for d in (8,384,768):
        for seed in (1729,2718):
            name=f'{d}-action-contrastive-{seed}';path=tmp_path/(name+'.json')
            write(path,dict(arm=name,budget_completed=True));paths[name]=str(path)
    inputs={str(p):subject.sha(p) for p in [parent_manifest,parent_plan,*map(Path,paths.values())]}
    plan=tmp_path/'plan.json';write(plan,dict(subject.FIXED,input_sha256=inputs))
    manifest=tmp_path/'manifest.json';write(manifest,dict(inputs=inputs,plan_sha256=subject.sha(plan),extensions={},
        parent_manifest=str(parent_manifest),parent_plan=str(parent_plan),baseline_summaries=paths))
    calls=[];ctx=dict(owners={},helpers=SimpleNamespace(extension=lambda *a:calls.append(('extension',a)) or object()))
    native=SimpleNamespace(load_context=lambda args:calls.append(('parent',args)) or ctx)
    monkeypatch.setattr(subject,'load_helper',lambda *a:native)
    args=SimpleNamespace(manifest=manifest,plan=plan,extension_root=tmp_path,dependency_root=tmp_path,output=tmp_path/'output',phase='training')
    return args,calls,paths


def test_context_binds_six_immutable_baselines_and_new_owner(tmp_path,monkeypatch):
    args,calls,paths=context_fixture(tmp_path,monkeypatch);ctx=subject.load_context(args)
    assert calls[0][0]=='parent' and calls[0][1].manifest.name=='parent-manifest.json'
    assert set(ctx['baseline_runs'])==set(paths)
    assert set(ctx['owners'])=={'action_factorized_clause_decoder_experiment','action_contrastive_decoder_training','ordered_clause_recurrent_decoder_experiment'}


@pytest.mark.parametrize('mutation',['changed_bytes','unbound_alias','missing_seed','wrong_arm','incomplete'])
def test_bad_baseline_bindings_refused(tmp_path,monkeypatch,mutation):
    args,calls,paths=context_fixture(tmp_path,monkeypatch);manifest=json.loads(args.manifest.read_bytes())
    key=next(iter(paths));path=Path(paths[key])
    if mutation=='changed_bytes':write(path,dict(arm=key,budget_completed=False))
    elif mutation=='unbound_alias':manifest['baseline_summaries'][key]=str(tmp_path/'outside.json')
    elif mutation=='missing_seed':manifest['baseline_summaries'].pop(key)
    else:
        write(path,dict(arm='incorrect' if mutation=='wrong_arm' else key,budget_completed=mutation!='incomplete'))
        manifest['inputs'][str(path)]=subject.sha(path)
        plan=json.loads(args.plan.read_bytes());plan['input_sha256']=manifest['inputs'];write(args.plan,plan)
        manifest['plan_sha256']=subject.sha(args.plan)
    write(args.manifest,manifest)
    with pytest.raises(ValueError):subject.load_context(args)
    if mutation in ('changed_bytes','unbound_alias','missing_seed'):assert calls==[]


def replay():
    report=dict(elapsed_seconds=1.,selected_weights_sha256='selected',last_complete_attempt_weights_sha256='final',
        history=[dict(accepted=False,selected_epoch=0)],action_contrastive_weight=.05,
        action_contrastive_inventory=dict(training_rows_sha256='source'),config=dict(max_seconds=180))
    panels={role:{label:dict(predictions=[dict(id='v1',token_ids=[1,2])]) for label,_,_ in subject.CONTROLS}
        for role in ('selected','last-attempt')}
    ctx=dict(core=core,dimension=8,baseline_runs={'8-action-contrastive-1729':dict(training=deepcopy(report),postfit=deepcopy(panels))})
    return ctx,report,panels


def test_baseline_replay_excludes_only_elapsed_time():
    ctx,report,panels=replay();report['elapsed_seconds']=999
    assert subject.validate_baseline(ctx,report,panels,1729)['complete']
    report['action_contrastive_weight']=.1
    with pytest.raises(ValueError,match='baseline replay differs'):subject.validate_baseline(ctx,report,panels,1729)


@pytest.mark.parametrize('field',['selected_weights_sha256','last_complete_attempt_weights_sha256','history','action_contrastive_inventory','config'])
def test_changed_training_states_labels_or_gate_history_not_a_replay(field):
    ctx,report,panels=replay();report[field]='changed'
    with pytest.raises(ValueError,match='baseline replay differs'):subject.validate_baseline(ctx,report,panels,1729)


@pytest.mark.parametrize('role',['selected','last-attempt'])
def test_each_context_control_must_replay_exactly(role):
    ctx,report,panels=replay();panels[role]['context-rotate']['predictions'][0]['token_ids']=[1,5,2]
    with pytest.raises(ValueError,match='control predictions'):subject.validate_baseline(ctx,report,panels,1729)


def test_main_retains_both_roles_and_explicit_residual_off_control(tmp_path,monkeypatch):
    """Exercise artifact wiring without fitting or loading any real model."""
    args=['runner','--dependency-root',str(tmp_path),'--extension-root',str(tmp_path),
        '--manifest',str(tmp_path/'manifest.json'),'--plan',str(tmp_path/'plan.json'),'--output',str(tmp_path/'out'),'--phase','training']
    write(tmp_path/'plan.json',{});write(tmp_path/'manifest.json',{})
    monkeypatch.setattr(sys,'argv',args);monkeypatch.setitem(subject.FIXED,'dimensions',[8]);monkeypatch.setitem(subject.FIXED,'seed_order',[1729])
    class FakeModel:
        off=False
        def parameters(self):return []
        def load_state_dict(self,state,strict=True):assert strict
    records=[]
    def save(path,value):
        write(path,value);return dict(path=str(path),sha256=subject.sha(path))
    def panel(ctx,model,split,control):
        records.append((model.off,split,control))
        return dict(predictions=[dict(id='v',token_ids=[3],eos_reached=True)],report=dict(metrics=dict(count=1)),
            execution=dict(kind=control,context_passed_to_model=True,training_performed=False,selection_performed=False),
            source_fidelity=dict(metrics=dict(ordered_exact=0)),source_count={},source_values={},timing={},scalar_mode='raw')
    def compact(p,retain_predictions=False):
        return dict(predictions=p['predictions'],source_fidelity=p['source_fidelity'],numerical=p['report'])
    def off(model):
        result=FakeModel();result.off=True;return result
    ctx=dict(helpers=SimpleNamespace(save=save,inventory=lambda *a:{}),core=SimpleNamespace(tensor_digest=lambda m:'same'),
        pins={},manifest=dict(inputs={},plan_sha256=subject.sha(tmp_path/'plan.json')),plan={},tree={},lineage={},
        rows={'train':[],'validation':[]},source_contexts={},preparation={},
        owners={'ordered_clause_recurrent_decoder_experiment':SimpleNamespace(bind_residual_off_model=off)},
        clause_runner=SimpleNamespace(evaluate=panel),prior=SimpleNamespace(compact_panel=compact))
    ctx['native_runner']=SimpleNamespace(prepare_dimension=lambda c,d:c,
        validate_wrapper_state=lambda c,s:None,save_state=lambda c,m,r,role,selected,path:save(path,dict(role=role,selected=selected)))
    report=dict(stopped_reason='epochs_completed',optimizer_steps=340,row_presentations=2440,valid_target_token_presentations=225840,
        source_value_presentations=25600,count_training_row_presentations=2440,count_training_presentations_by_class=subject.FIXED['expected_balanced_count_presentations'],
        selected_weights_sha256='same',last_complete_attempt_weights_sha256='same',last_complete_attempt_is_selected=False,
        selected_epoch=0,last_complete_attempt=dict(fidelity=dict(metrics=dict(ordered_exact=0))))
    prediction=[dict(id='v',token_ids=[3],eos_reached=True)]
    monkeypatch.setattr(subject,'load_context',lambda args:ctx);monkeypatch.setattr(subject,'bind_candidate',lambda *a:FakeModel())
    monkeypatch.setattr(subject,'validate_initial',lambda *a:dict(complete=True))
    monkeypatch.setattr(subject,'train_candidate',lambda *a:dict(report=deepcopy(report),state_dict={},last_complete_attempt_state_dict={},predictions=prediction,last_complete_attempt_predictions=prediction))
    monkeypatch.setattr(subject,'validate_baseline',lambda *a:dict(complete=True))
    monkeypatch.setattr(subject,'recurrent_residual_diagnostic',lambda *a:dict(source_only=True,actual_prefix_routes_observed=False))
    subject.main()
    result=json.loads((tmp_path/'out/summary.json').read_bytes())
    assert len(result['runs'])==2 and all(not result[k] for k in subject.FALSE)
    assert len(records)==34 and records.count((True,'validation','conditioned'))==2
    for item in result['runs']:
        path=Path(item['summary_path']);assert subject.sha(path)==item['summary_sha256'];run=json.loads(path.read_bytes())
        assert 'training' not in run and subject.sha(run['training_ref']['path'])==run['training_ref']['sha256']
        for role,panels in run['postfit'].items():
            assert len(panels)==(9 if run['recipe']['recurrent'] else 8)
            for label,value in panels.items():
                assert subject.sha(value['path'])==value['sha256']
                raw=json.loads(Path(value['path']).read_bytes())
                assert raw['execution']['context_passed_to_model']
                if label=='recurrent-residual-off':
                    assert raw['execution']['kind']=='recurrent_residual_off' and raw['execution']['recurrent_residual_disabled']
                    assert not raw['execution']['selection_performed'] and not raw['execution']['training_performed']


def real_fixture(monkeypatch):
    """Reuse authenticated tiny cohorts with the declared16-wide recurrent body."""
    torch=pytest.importorskip('torch')
    from . import test_action_contrastive_decoder_training as fixtures
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as conditioning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
    original=fixtures.sources;_,train,tune,options,contexts=original(duplicate=False)
    raw=numerical._model(dict(dimension=8),options['codec'],dict(seed=2026,projection_width=2,hidden_size=8,token_embedding_dim=16))
    for name,p in raw.named_parameters():
        if name.startswith(('projection_down.','projection_up.')):p.requires_grad_(False)
    persistent=conditioning.bind_persistent_model(raw,dimension=8,conditioning='every_step')
    with monkeypatch.context() as patch:
        patch.setattr(fixtures,'sources',lambda **kw:(persistent,train,tune,options,contexts))
        donor,train,tune,options,contexts=fixtures.actual_fixture()
    return recurrent.bind_ordered_clause_recurrent_model(donor,codec=options['codec']),donor,train,tune,options,contexts


@pytest.fixture
def one_cpu():
    torch=pytest.importorskip('torch');old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def test_real_new_schema_trains_recurrent_route_with_unchanged_contrastive_loss(monkeypatch,one_cpu):
    torch=pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model,_,train,tune,options,contexts=real_fixture(monkeypatch);before=core.tensor_digest(model)
    result=trainer.train(model,train,tune,source_contexts=contexts,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',action_contrastive_weight=.05,**options)
    report=result['report'];assert report['optimizer_steps']==report['action_contrastive_active_updates']==2
    assert report['selection']=='per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert report['generation_temperature']==0 and report['action_contrastive_temperature']==.1
    assert report['source_value_presentations']==24 and core.tensor_digest(model)==before
    for update in report['committed_updates']:
        loss=update['action_contrastive'];assert set(loss['row_ids'])=={r['id'] for r in train}
        expected=update['weighted_token_ce']+report['config']['reconstruction_weight']*update['raw_reconstruction_mse']+.25*update['count_ce']+.25*update['source_value_ce']+.05*loss['loss']
        assert update['objective']==pytest.approx(expected,abs=1e-6)
        assert not loss['used_for_selection'] and not loss['validation_rows_used']
    initial=model.state_dict();last=result['last_complete_attempt_state_dict']
    route=[name for name in last if name not in dict(model.named_buffers()) and 'clause_to_embedding' in name]
    assert len(route)==1 and not torch.equal(initial[route[0]],last[route[0]])
    for name in report['frozen_parameter_names']:
        assert torch.equal(initial[name],last[name])


def test_new_schema_rejects_context_cohort_mutation(monkeypatch,one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    model,_,train,tune,options,contexts=real_fixture(monkeypatch)
    mutated=deepcopy(contexts);key=train[0]['id'];mutated['train'][key]['segments'][0]['vector'][0]=.5
    with pytest.raises(ValueError):
        trainer.train(model,train,tune,source_contexts=mutated,source_value_weight=.25,cardinality_weight=.25,action_contrastive_weight=.05,**options)


def test_residual_off_is_explicit_contextual_inference_control_not_trainable_schema(monkeypatch,one_cpu):
    from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    spec=importlib.util.spec_from_file_location('_context_runner_control',ROOT/'scripts/ops/autoencoder/benchmark_clause_context_source_training.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    model,_,_,_,options,_=real_fixture(monkeypatch);off=recurrent.bind_residual_off_model(model)
    assert off.describe()['schema']=='ordered-clause-recurrent-residual-off-control/v1'
    assert runner.contextual(model) and runner.contextual(off)
    with pytest.raises(ValueError):trainer._head_specification(off,options['codec'],.25)


@pytest.mark.parametrize('control',['conditioned','zero_condition','residual_off','context_only_shuffle'])
def test_potential_residual_capture_is_source_only_and_preserves_model(monkeypatch,one_cpu,control):
    torch=pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_controls as controls
    from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
    model,_,train,tune,options,contexts=real_fixture(monkeypatch)
    with torch.no_grad():model.clause_to_embedding.weight.fill_(.125)
    if control=='residual_off':model=recurrent.bind_residual_off_model(model)
    model.train();next(iter(model.children())).eval()
    # The observation API must not interpret targets or reference formulas.
    rows=deepcopy(tune)
    for row in rows:row['target_ids']={'poison':'not tokens'}
    def transform(torch,rows,config):
        return (torch.tensor([r['input'] for r in rows],dtype=torch.float32)-torch.tensor(config['mean']))/config['scale']
    ctx=dict(core=core,rows={'validation':rows},source_contexts={'validation':contexts['validation']},
        owners={'clause_source_controls':controls,'ordered_clause_recurrent_decoder_experiment':recurrent},
        donor={'input_transform':options['input_transform']},native_runner=SimpleNamespace(transformed_rows=transform))
    for p in model.parameters():
        if p.requires_grad:p.grad=torch.ones_like(p)
    before=core.tensor_digest(model);modes={k:v.training for k,v in model.named_modules()}
    grads={k:None if p.grad is None else p.grad.clone() for k,p in model.named_parameters()}
    rng=torch.random.get_rng_state().clone();row_hash=core.digest(rows);context_hash=core.digest(contexts)
    actual_control='conditioned' if control=='residual_off' else control
    result=subject.recurrent_residual_diagnostic(ctx,model,'validation',actual_control)
    assert result['source_only'] and not result['reference_documents_passed_to_model']
    assert not result['actual_prefix_routes_observed'] and len(result['rows'])==3
    assert result['residual_disabled']==(control=='residual_off')
    assert result['all_source_routes_removed']==(control=='zero_condition')
    values=torch.tensor([r['potential_residuals'] for r in result['rows']])
    assert tuple(values.shape)==(3,8,16) and bool(torch.isfinite(values).all())
    if control in ('residual_off','zero_condition'):assert torch.count_nonzero(values)==0
    else:assert torch.count_nonzero(values)>0
    assert core.tensor_digest(model)==before and {k:v.training for k,v in model.named_modules()}==modes
    assert torch.equal(rng,torch.random.get_rng_state())
    assert core.digest(rows)==row_hash and core.digest(contexts)==context_hash
    for name,p in model.named_parameters():
        assert (p.grad is None and grads[name] is None) or torch.equal(p.grad,grads[name])
