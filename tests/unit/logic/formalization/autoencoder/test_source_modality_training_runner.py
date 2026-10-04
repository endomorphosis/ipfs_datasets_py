"""Bound six fits and keep auxiliary source labels out of exposed evaluation."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_source_modality_training.py'
SPEC=importlib.util.spec_from_file_location('_source_modality_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.mark.parametrize('index,kind,weight',[(0,None,0.),(1,'used113',.05),(2,'full180',.05)])
def test_only_registered_bank_and_weight_reach_the_trainer(index,kind,weight):
    calls=[]
    ctx=dict(owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['train refs'],'validation':['dev refs']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='validator',validator_id='id',stages=[],
        source_contexts={},modality_banks={'used113':{'id':'113'},'full180':{'id':'180'}})
    subject.train_candidate(ctx,'model',1729,subject.ARMS[index]); args,kw=calls[0]
    assert args==('model',['train'],['dev'])
    assert kw['training_references']==['train refs'] and kw['validation_references']==['dev refs']
    if kind is None:
        assert 'auxiliary_source_modality_bank' not in kw and 'auxiliary_source_modality_weight' not in kw
        assert 'generated_boundary_retry_on_mismatch' not in kw
    else:
        assert kw['auxiliary_source_modality_bank'] is ctx['modality_banks'][kind]
        assert kw['auxiliary_source_modality_weight']==weight
        assert kw['generated_boundary_retry_on_mismatch'] is True
    assert kw['generated_source_margin_weight']==0. and kw['generated_source_margin_replay'] is False
    assert kw['generated_boundary_weight']==.05 and kw['action_contrastive_weight']==.05
    assert kw['source_value_weight']==kw['cardinality_weight']==.25
    assert kw['non_action_learning_rate_multiplier']==10.
    assert kw['config']==dict(seed=1729,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
        max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,max_memory_bytes=1073741824)


def test_two_seeds_and_only384_with_equal_auxiliary_work():
    jobs=subject.jobs()
    assert len(jobs)==6
    assert [(d,s,r['name']) for d,s,r in jobs]==[(384,s,a['name']) for s in (1729,2718) for a in subject.ARMS]
    assert jobs[0][2] is not subject.ARMS[0]
    control,candidate=deepcopy(subject.ARMS[1:]);control.pop('name');candidate.pop('name')
    assert control.pop('bank_kind')=='used113' and candidate.pop('bank_kind')=='full180'
    assert control==candidate
    assert subject.FIXED['auxiliary_positive_presentations_per_fit']==340*6
    assert len(subject.CONTROLS)==8 and subject.FIXED['additional_candidate_control']=='recurrent-residual-off'


@pytest.mark.parametrize('key,value',[
    ('dimensions',[8,384,768]),('fit_count',18),('seed_order',[1729]),('auxiliary_batch_size',12),
    ('auxiliary_positive_presentations_per_fit',4080),('full_vocabulary_retained',False),
    ('auxiliary_full_vocabulary_size',3),('clause_normalization_refitted',True),
    ('generated_source_margin_weight',.01),('generated_source_margin_replay',True),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('temperature',1),
    ('production_promotion_allowed',True),('selection_unchanged',False),
    ('max_seconds_entire_run',1501),('all_exposed_predictions_before_reference_load',False),
    ('exposed_r6_role','fresh_holdout'),('boundary_replay_atol',1e-4),('boundary_replay_rtol',1e-4),
    ('boundary_retry_limit_per_original_batch',2),('baseline_boundary_retry_flag_omitted',False),
    ('boundary_replay_reference_prefixes_used',True)])
def test_fixed_recipe_rejects_semantic_exposure_and_budget_changes(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed source-modality'):subject.validate_plan(plan)


def test_baseline_binding_delegates_to_exact_original_architecture():
    calls=[];old={'name':'source-head-lr10','recurrent':True}
    ctx={'prior_margin':SimpleNamespace(ARMS=[old],bind_candidate=lambda *args:calls.append(args) or 'model')}
    for recipe in subject.ARMS:
        assert subject.bind_candidate(ctx,recipe,2718)=='model'
        assert calls[-1]==(ctx,old,2718)
    with pytest.raises(ValueError):subject.bind_candidate(ctx,subject.ARMS[0],123)


def test_bound_json_authenticates_exact_parsed_bytes(tmp_path):
    path=tmp_path/'input.json';path.write_text('{"x":1}')
    manifest={'inputs':{str(path):subject.sha(path)}}
    assert subject.bound_json(manifest,path)=={'x':1}
    path.write_text('{"x":2}')
    with pytest.raises(ValueError,match='sealed artifact differs'):subject.bound_json(manifest,path)
    with pytest.raises(ValueError,match='unbound artifact'):subject.bound_json(manifest,path,'wrong')


def test_source_inventory_keeps_old_and_new_trainer_hashes_distinct(tmp_path,monkeypatch):
    dep=tmp_path/'dependency';old=tmp_path/'parent';new=tmp_path/'new'
    relative=subject.TRAINER
    for root,text in ((old,'old trainer'),(new,'new trainer')):
        (root/relative).parent.mkdir(parents=True);(root/relative).write_text(text)
    modules={subject.PREFIX+'long_span_source_value_training':SimpleNamespace(__file__=str(old/relative)),
        subject.PREFIX+'_source_modality_training_owner':SimpleNamespace(__file__=str(new/relative))}
    monkeypatch.setattr(subject.sys,'modules',modules)
    ctx=dict(manifest={'parent_extension_root':str(old)},parent_manifest={'extensions':{relative:subject.sha(old/relative)}},
        pins={relative:subject.sha(new/relative)})
    got=subject.source_inventory(SimpleNamespace(dependency_root=dep,extension_root=new),ctx)
    assert got=={'parent_extension:'+relative:subject.sha(old/relative),'extension:'+relative:subject.sha(new/relative)}
    (old/relative).write_text('drift')
    with pytest.raises(ValueError,match='unregistered'):subject.source_inventory(SimpleNamespace(dependency_root=dep,extension_root=new),ctx)


def test_source_inventory_rejects_editable_install_or_unpinned_alias(tmp_path,monkeypatch):
    drift=tmp_path/'drift.py';drift.write_text('drift')
    monkeypatch.setattr(subject.sys,'modules',{subject.PREFIX+'drift':SimpleNamespace(__file__=str(drift))})
    ctx=dict(manifest={'parent_extension_root':str(tmp_path/'parent')},parent_manifest={'extensions':{}},pins={})
    with pytest.raises(ValueError,match='outside isolated roots'):
        subject.source_inventory(SimpleNamespace(dependency_root=tmp_path/'dep',extension_root=tmp_path/'new'),ctx)


def test_real_extension_import_closure_preserves_old_canonical_trainer(tmp_path,monkeypatch):
    """Import-only cold package test: no package path overlay or model load."""
    package='_isolated_modality_extension_test';prefix=package+'.'
    baseline=tmp_path/'native';baseline.mkdir();old=tmp_path/'old';new=tmp_path/'new'
    parent=ModuleType(package);parent.__path__=[str(baseline)]
    monkeypatch.setitem(sys.modules,package,parent);monkeypatch.setattr(subject,'PREFIX',prefix)
    prior_trainer=ModuleType(prefix+'long_span_source_value_training')
    monkeypatch.setitem(sys.modules,prior_trainer.__name__,prior_trainer)
    def forbidden(*args,**kwargs):
        raise AssertionError('imports must not construct a model or execute tensors')
    dependencies={
        'decoder_distillation_experiment':{'_require':subject.require,'digest':digest,'_torch':forbidden},
        'decoder_source_fidelity':{}, 'clause_source_context':{},
        'source_value_decoder_experiment':{'SOURCE_FIELDS':('actor','action','modality','object')},
        'long_span_count_exposure_training':dict(FALSE={},reference_weights=forbidden,_summary=forbidden,
            _count_labels=forbidden,_count_logits=forbidden,_BalancedCountSelector=forbidden,_source_batch=forbidden)}
    for name,attrs in dependencies.items():
        module=ModuleType(prefix+name);module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules,prefix+name,module);setattr(parent,name,module)
    old_pins={};new_pins={}
    for root,pins,relative in ((old,old_pins,subject.AUTO+'authored_scalar_holdout.py'),
            (new,new_pins,subject.HELPER),(new,new_pins,subject.TRAINER)):
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((PATH.parents[3]/relative).read_bytes());pins[relative]=subject.sha(target)
    spec=importlib.util.spec_from_file_location('_modality_real_extension_loader',PATH.with_name('benchmark_decoder_source_fidelity.py'))
    loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
    ctx={'helpers':loader,'owners':{}}
    names=['source_modality_auxiliary_training','authored_scalar_holdout','_source_modality_training_owner']
    try:
        with pytest.raises(ImportError,match='authored_scalar_holdout'):
            loader.extension(new,subject.HELPER,prefix+'source_modality_auxiliary_training',new_pins)
        sys.modules.pop(prefix+'source_modality_auxiliary_training')
        subject.load_intervention_extensions(ctx,old,new,old_pins,new_pins)
        assert ctx['owners']['source_modality_auxiliary_training'].authored is ctx['owners']['authored_scalar_holdout']
        assert ctx['owners']['long_span_source_value_training'].__name__==prefix+'_source_modality_training_owner'
        assert sys.modules[prefix+'long_span_source_value_training'] is prior_trainer
        assert parent.__path__==[str(baseline)]
        assert Path(ctx['owners']['long_span_source_value_training'].__file__)==new/subject.TRAINER
        assert Path(ctx['owners']['authored_scalar_holdout'].__file__)==old/subject.AUTO/'authored_scalar_holdout.py'
    finally:
        for name in names:sys.modules.pop(prefix+name,None)


def test_revised_boundary_is_registered_before_historical_consumers():
    calls=[]
    def extension(root,path,name,pins):
        calls.append((root,path,name,pins));return name
    ctx={'helpers':SimpleNamespace(extension=extension),'owners':{}}
    old=Path('/frozen-parent');new=Path('/frozen-revised');oldpins={'old':1};newpins={'new':2}
    subject.load_boundary_extensions(ctx,old,new,oldpins,newpins)
    assert calls==[(new,subject.AUTO+'contextual_generated_boundary_training.py',
        subject.PREFIX+'contextual_generated_boundary_training',newpins),
        (old,subject.AUTO+'generated_field_training.py',subject.PREFIX+'generated_field_training',oldpins),
        (old,subject.AUTO+'generated_source_margin_training.py',subject.PREFIX+'generated_source_margin_training',oldpins)]


@pytest.mark.parametrize('observed',['initial','changed'])
def test_failed_fit_is_retained_without_fabricated_progress_or_error_secrets(tmp_path,monkeypatch,observed):
    saved=[];failure=ValueError('a diagnostic message that must not be copied')
    def train(*args,**kwargs):raise failure
    monkeypatch.setattr(subject,'train_candidate',train)
    ctx={'core':SimpleNamespace(tensor_digest=lambda _:observed),
        'helpers':SimpleNamespace(save=lambda path,value:saved.append((path,value)))}
    with pytest.raises(ValueError) as caught:
        subject.fit_and_record(ctx,'model',1729,subject.ARMS[1],tmp_path,'initial')
    assert caught.value is failure and len(saved)==1
    path,receipt=saved[0]
    assert path==tmp_path/'training-failure.json'
    assert receipt['exception_type']=='ValueError' and receipt['exception_message_omitted'] is True
    assert str(failure) not in json.dumps(receipt)
    assert receipt['completed_optimizer_steps'] is None
    assert receipt['completed_training_report_available'] is receipt['private_training_state_available'] is False
    assert receipt['caller_tensor_unchanged']==(observed=='initial')
    assert receipt['qualified'] is receipt['admitted'] is False


def test_successful_fit_wrapper_preserves_result_and_saves_no_failure(tmp_path,monkeypatch):
    value={'original':'result'};saved=[]
    monkeypatch.setattr(subject,'train_candidate',lambda *a,**k:value)
    ctx={'helpers':SimpleNamespace(save=lambda *args:saved.append(args))}
    actual,seconds=subject.fit_and_record(ctx,'model',1729,subject.ARMS[0],tmp_path,'initial')
    assert actual is value and seconds>=0 and saved==[]


def boundary_receipt_fixture(*,retried=False,active=True):
    row=dict(id='first',batch_offset=0,selected_sites=[dict(position=1)] if active else [],
        replay_prefix_tokens=2 if active else 0)
    inactive=dict(id='inactive',batch_offset=0,selected_sites=[],replay_prefix_tokens=0)
    attempts=[];events=[]
    if active:
        for kind in (('bulk','incremental_retry') if retried else ('bulk',)):
            failed=retried and kind=='bulk';is_retry=kind=='incremental_retry'
            logits=[float(failed)]+[0.]*31
            attempts.append(dict(kind=kind,original_batch_offset=0,
                row_ids=['first','inactive'] if is_retry else ['first'],active_row_ids=['first'],
                prefix_lengths=[2],prefix_steps=2,physical_row_tokens=4 if is_retry else 2,
                forward_calls=2 if is_retry else 1,before_component_cross_entropy=True,
                original_batch_membership_preserved=is_retry,collected_prefix_checked=is_retry,
                elapsed_seconds=.01,selected_logits=[dict(id='first',position=1,logits=logits)],
                mismatches=[dict(id='first',position=1,vocabulary_indices=[0])] if failed else [],
                parity_passed=not failed,used_for_loss=not failed))
        events=[dict(id='first',position=1,replay_logits=[0.]*32)]
    return dict(schema='contextual-generated-source-boundary-loss/v2',retry_enabled=True,
        replay_strategy='bulk_then_original_batch_incremental_retry_on_logit_mismatch',
        retry_limit_per_original_batch=1,replay_logits_atol=2e-5,replay_logits_rtol=2e-5,
        replay_logits_match_collection=True,full_vocabulary_cross_entropy=True,vocabulary_size=32,
        reference_counts_used_only_in_loss=True,target_prefixes_used=False,
        student_generated_prefix_replay=True,additional_optimizer_steps=0,selection_policy='first_last',
        site_cap_per_row=2,one_gradient_replay_per_active_row=True,
        bulk_grouping='active_rows_within_original_collection_batch',successful_bulk_ce_gather='original_advanced_indexing',
        generation=dict(max_target_tokens=512,batch_size=8,source_only=True,reference_count_access=False,
            site_policy_access=False,complete_rollout_before_site_selection=True,rows=[row,inactive]),
        rows=2,active_rows=int(active),selected_sites=int(active),events=events,replay_attempts=attempts,
        bulk_replay_batch_count=int(active),discarded_bulk_batch_count=int(retried and active),
        incremental_retry_batch_count=int(retried and active),incremental_retry_forward_steps=2 if retried and active else 0,
        bulk_attempted_row_tokens=2 if active else 0,retry_attempted_row_tokens=4 if retried and active else 0,
        physical_replay_forward_calls=3 if retried and active else int(active),
        physical_replay_row_tokens=6 if retried and active else 2 if active else 0,
        replay_batch_count=int(active),rows_replayed_once=not(retried and active),replay_prefix_tokens=2 if active else 0)


@pytest.mark.parametrize('active,retried',[(False,False),(True,False),(True,True)])
def test_strict_retry_receipt_accepts_no_sites_bulk_success_and_causal_retry(active,retried):
    receipt=boundary_receipt_fixture(active=active,retried=retried);before=deepcopy(receipt)
    subject.validate_boundary_retry_receipt(receipt)
    assert receipt==before


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema='contextual-generated-source-boundary-loss/v1'),
    lambda r:r.update(replay_logits_atol=3e-5),lambda r:r.update(replay_logits_rtol=3e-5),
    lambda r:r.update(retry_limit_per_original_batch=2),lambda r:r.update(target_prefixes_used=True),
    lambda r:r.update(one_gradient_replay_per_active_row=False),
    lambda r:r['generation'].update(source_only=False),
    lambda r:r['generation'].update(reference_count_access=True),
    lambda r:r['generation']['rows'][1].update(batch_offset=8),
    lambda r:r['replay_attempts'][0].update(used_for_loss=True),
    lambda r:r['replay_attempts'][0].update(parity_passed=True),
    lambda r:r['replay_attempts'][1].update(row_ids=['first']),
    lambda r:r['replay_attempts'][1].update(original_batch_membership_preserved=False),
    lambda r:r['replay_attempts'][1].update(collected_prefix_checked=False),
    lambda r:r['replay_attempts'][1].update(before_component_cross_entropy=False),
    lambda r:r['replay_attempts'][1].update(forward_calls=1),
    lambda r:r['replay_attempts'][1].update(physical_row_tokens=2),
    lambda r:r['replay_attempts'][1].update(mismatches=[dict(id='first',position=1,vocabulary_indices=[0])],
        parity_passed=False,used_for_loss=False),
    lambda r:r['replay_attempts'][1]['selected_logits'][0]['logits'].pop(),
    lambda r:r['replay_attempts'][1].update(elapsed_seconds=float('nan')),
    lambda r:r['replay_attempts'].append(deepcopy(r['replay_attempts'][1])),
    lambda r:r.update(physical_replay_row_tokens=2),lambda r:r.update(physical_replay_forward_calls=2),
    lambda r:r.update(rows_replayed_once=True),lambda r:r.update(replay_prefix_tokens=4),
    lambda r:r['events'][0].update(replay_logits=[1.]+[0.]*31),
])
def test_strict_retry_rejects_relaxation_discarded_graph_or_hidden_physical_work(change):
    receipt=boundary_receipt_fixture(retried=True);change(receipt)
    with pytest.raises(ValueError):subject.validate_boundary_retry_receipt(receipt)


def report_fixture(index=1):
    recipe=subject.ARMS[index];kind=recipe['bank_kind']
    rows=[dict(id=str(i),source_sha256='sha'+str(i),modality_token_id=t)
        for i,t in enumerate([4,4,5,5,3,3])]
    bank=dict(bank_sha256='bank',bank_kind=kind,rows=rows,selected_rows=113 if kind=='used113' else 180)
    source_rows={split:[dict(id=split,source_text=split,input=[1.])] for split in ('train','validation')}
    used={str(i):'vector'+str(i) for i in range(113)}
    contexts={'train':{'train':{'segments':[dict(source_sha256=k,embedding_sha256=v) for k,v in used.items()]}},'validation':{}}
    ctx=dict(modality_banks={kind:bank},core=SimpleNamespace(digest=digest),donor={'codec':{},'input_transform':{}},
        rows=source_rows,source_contexts=contexts)
    cache=dict(bank_sha256='bank',bank_kind=kind,dimension=384,selected_rows=bank['selected_rows'],batch_size=6,
        seed=1729,full_vocabulary_size=32,input_transform_sha256=digest({}),codec_sha256=digest({}),
        normalization_fitted=False,encoder_executed=False)
    binding=dict(schema='source-modality-training-binding/v1',bank_sha256='bank',bank_kind=kind,dimension=384,
        codec_sha256=digest({}),training_rows_sha256=digest(source_rows['train']),validation_rows_sha256=digest(source_rows['validation']),
        training_paragraph_sources_sha256=digest([dict(id='train',source_text='train')]),
        training_contexts_sha256=digest(contexts['train']),validation_contexts_sha256=digest(contexts['validation']),
        actual_training_clause_vectors_sha256=digest(used),actual_training_unique_clauses=113,
        selected_bank_rows=bank['selected_rows'],externally_declared_extra_training_sources=bank['selected_rows']-113,
        validation_labels_accessed=False,training_reference_labels_accessed=False)
    receipt=dict(schema='training-source-modality-auxiliary/v1',bank_sha256='bank',bank_kind=kind,
        sampler_seed=1729,batch_size=6,loss_field='modality',source_slot=0,full_vocabulary_size=32,
        source_head_forward_calls=1,recurrent_forward_calls=0,count_forward_calls=0,encoder_forward_calls=0,
        labels_passed_to_model=False,validation_labels_used=False,normalization_fitted=False,sampler_state_advanced=False,
        strata=[dict(modality=s[0],wording_style=int(s[-1])) for s in subject.FIXED['auxiliary_strata']],
        indices=list(range(6)),row_ids=[r['id'] for r in rows],source_sha256=[r['source_sha256'] for r in rows],
        target_token_ids=[r['modality_token_id'] for r in rows],full_vocabulary_logits=[[0.]*32 for _ in rows],
        per_row_cross_entropy=[3.]*6,mean_cross_entropy=3.)
    report=dict(stopped_reason='epochs_completed',optimizer_steps=340,row_presentations=2440,
        valid_target_token_presentations=225840,source_value_presentations=25600,count_training_row_presentations=2440,
        count_training_presentations_by_class=deepcopy(subject.FIXED['expected_balanced_count_presentations']),config={'seed':1729},
        auxiliary_source_modality_weight=.05,auxiliary_source_modality_used_for_selection=False,
        generated_boundary_retry_on_mismatch=True,
        generated_boundary_retry_policy='bulk_then_original_batch_incremental_retry_on_logit_mismatch',
        generated_boundary_retry_limit_per_original_batch=1,generated_boundary_retry_tolerance_changed=False,
        generated_boundary_retry_max_updates_estimated=340,
        auxiliary_source_modality_committed_updates=340,auxiliary_source_modality_presentations=2040,
        auxiliary_source_modality_presentations_per_stratum=340,auxiliary_source_modality_strata_count=6,
        auxiliary_source_modality_presentations_per_class={'O':680,'P':680,'F':680},
        auxiliary_source_modality_training_only=True,auxiliary_source_modality_normalization_refitted=False,
        auxiliary_source_modality_encoder_executed=False,auxiliary_source_modality_zero_weight_graph_attached=False,
        auxiliary_source_modality_bank_receipt=cache,auxiliary_source_modality_binding_receipt=binding,
        committed_updates=[dict(generated_boundary=boundary_receipt_fixture(active=False),auxiliary_source_modality=dict(
            weight=.05,zero_based_committed_step=i,base_objective=1.,weighted_loss=.15,
            receipt=dict(deepcopy(receipt),committed_step=i))) for i in range(340)])
    return ctx,report,recipe


@pytest.mark.parametrize('index',[1,2])
def test_auxiliary_report_requires_complete_matched_full_vocabulary_work(index):
    ctx,report,recipe=report_fixture(index);before=deepcopy(report)
    subject.validate_auxiliary_report(ctx,report,recipe)
    assert report==before


@pytest.mark.parametrize('change',[
    lambda r:r.update(optimizer_steps=339),lambda r:r.update(source_value_presentations=25599),
    lambda r:r.update(generated_source_margin_weight=.01),
    lambda r:r.update(generated_boundary_retry_on_mismatch=False),
    lambda r:r.update(generated_boundary_retry_tolerance_changed=True),
    lambda r:r.update(generated_boundary_retry_limit_per_original_batch=2),
    lambda r:r.update(generated_boundary_retry_max_updates_estimated=1000),
    lambda r:r.update(auxiliary_source_modality_weight=.25),
    lambda r:r.update(auxiliary_source_modality_presentations=4080),
    lambda r:r.update(auxiliary_source_modality_normalization_refitted=True),
    lambda r:r.update(auxiliary_source_modality_training_only=False),
    lambda r:r.update(auxiliary_source_modality_used_for_selection=True),
    lambda r:r.update(auxiliary_source_modality_zero_weight_graph_attached=True),
    lambda r:r['auxiliary_source_modality_bank_receipt'].update(bank_sha256='other'),
    lambda r:r['auxiliary_source_modality_bank_receipt'].update(selected_rows=180),
    lambda r:r['auxiliary_source_modality_binding_receipt'].update(actual_training_unique_clauses=180),
    lambda r:r['auxiliary_source_modality_binding_receipt'].update(training_contexts_sha256='stale'),
    lambda r:r['auxiliary_source_modality_binding_receipt'].update(validation_labels_accessed=True),
    lambda r:r['committed_updates'].pop(),
    lambda r:r['committed_updates'][0].pop('generated_boundary'),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality'].update(zero_based_committed_step=True),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality'].update(weighted_loss=float('nan')),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(validation_labels_used=True),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(recurrent_forward_calls=1),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(full_vocabulary_size=3),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(committed_step=1),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt']['strata'].reverse(),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(row_ids=['dev']*6),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt'].update(target_token_ids=[3]*6),
    lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt']['full_vocabulary_logits'][0].pop(),
])
def test_report_rejects_mislabeled_or_omitted_auxiliary_work(change):
    ctx,report,recipe=report_fixture();change(report)
    with pytest.raises(ValueError):subject.validate_auxiliary_report(ctx,report,recipe)


def test_baseline_report_has_no_auxiliary_work_or_metadata():
    ctx,report,_=report_fixture()
    report={k:v for k,v in report.items() if not k.startswith(('auxiliary_source_modality_','generated_boundary_retry_'))}
    report['committed_updates']=[{} for _ in range(340)]
    subject.validate_auxiliary_report(ctx,report,subject.ARMS[0])
    report['committed_updates'][0]['auxiliary_source_modality']={}
    with pytest.raises(ValueError,match='baseline unexpectedly'):subject.validate_auxiliary_report(ctx,report,subject.ARMS[0])


def test_original_forbidden_data_is_reduced_to_source_only():
    text='Example.'
    raw={'rows':[dict(id='id',source_text=text,source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        split='test',embedding=[.5]*384,target={'never':'used'},target_ids=[1,2])]}
    assert subject.source_only_original_rows(raw,'test')==[dict(id='id',source_text=text,input=[.5]*384)]
    with pytest.raises(ValueError,match='split/source'):subject.source_only_original_rows(raw,'train')


def test_bank_preparation_uses_training_targets_and_source_only_forbidden_inventory(monkeypatch):
    def original(split):
        text=split+' source'
        return {'rows':[dict(id=split,source_text=text,split=split,embedding=[1.],
            source_sha256=hashlib.sha256(text.encode()).hexdigest(),target={'forbidden target':split})]}
    raw={name:original(name) for name in ('train','validation','test','canary')};raw['cache']=[{'prepared':'training'}]
    inputs=dict(original_training='train',prepared_training='cache',
        forbidden={name:name for name in ('validation','test','canary')})
    manifest=dict(auxiliary_sources=inputs,exposed_source_inputs='exposed',
        inputs={str(Path(name).resolve()):'hash-'+name for name in (*raw,'exposed')})
    sources=[{'only':'training sources'}];references=[{'only':'training targets'}];calls=[]
    def adapt(rows,cache,**kwargs):
        assert rows is raw['train']['rows'] and cache is raw['cache']
        return dict(source_rows=sources,references=references,receipt={'authenticated':True})
    def prepare(a,b,**kwargs):
        calls.append((a,b,kwargs));return dict(bank_kind=kwargs['bank_kind'])
    owner=SimpleNamespace(adapt_original_training_bank=adapt,prepare_bank=prepare)
    ctx=dict(manifest=manifest,owners={'source_modality_auxiliary_training':owner},core=SimpleNamespace(digest=digest))
    lane=dict(donor={'codec':{}},validate_rule='validator',rows={
        'train':[dict(id='paragraph',source_text='training paragraph',target_ids=['training'])],
        'validation':[dict(id='development',source_text='development source',input=[2.],target_ids=['never passed'])]},
        clause_cache={'validation':[dict(id='clause',source_text='clause source',input=[3.],target_ids=['never passed'])]})
    exposed=dict(rows=[dict(id='exposed',source_text='exposed paragraph',input=[4.])],
        clause_cache=[dict(id='exposed clause',source_text='exposed clause',input=[5.])])
    monkeypatch.setattr(subject,'bound_json',lambda manifest,path:raw[path])
    result=subject.prepare_banks(ctx,lane,exposed,123.)
    assert result['prepared_once'] is True and len(calls)==2
    assert [call[2]['bank_kind'] for call in calls]==['used113','full180']
    for a,b,kwargs in calls:
        assert a is sources and b is references
        assert kwargs['paragraph_training_rows']==[dict(id='paragraph',source_text='training paragraph')]
        forbidden=kwargs['forbidden_rows_by_split']
        assert set(forbidden)=={'validation','test','canary','exposed_holdout'}
        assert [len(forbidden[k]) for k in ('validation','test','canary','exposed_holdout')]==[3,1,1,2]
        assert all(set(row)=={'id','source_text','input'} for values in forbidden.values() for row in values)
        assert kwargs['input_sha256']['references']==digest(references)
    assert lane['modality_banks']=={'used113':{'bank_kind':'used113'},'full180':{'bank_kind':'full180'}}


def test_bank_preparation_requires_all_forbidden_original_splits_before_adapter(monkeypatch):
    calls=[];owner=SimpleNamespace(adapt_original_training_bank=lambda *a,**k:calls.append(a))
    ctx={'manifest':{'auxiliary_sources':dict(original_training='train',prepared_training='cache',forbidden={'validation':'val'})},
        'owners':{'source_modality_auxiliary_training':owner}}
    with pytest.raises(ValueError,match='forbidden splits'):subject.prepare_banks(ctx,{}, {},123.)
    assert calls==[]


def test_no_exposed_reference_access_until_all_twelve_predictions_exist(monkeypatch):
    accesses=[]
    monkeypatch.setattr(subject,'bound_json',lambda *a:accesses.append(a))
    with pytest.raises(ValueError,match='all12'):
        subject.load_exposed_references({},[])
    assert accesses==[]


def prediction_fixture(tmp_path):
    records=[];rows=[dict(id=str(i),source_text='source'+str(i),input=[0.]*384) for i in range(48)]
    for d,seed,arm in subject.jobs():
        for role in subject.ROLES:
            name=f'{d}-{arm["name"]}-{seed}';path=tmp_path/(name+'-'+role+'.json')
            value=dict(complete=True,predictions=[dict(id=r['id']) for r in rows],
                model_tensor_sha256='state',generation_reference_access=False)
            path.write_text(json.dumps(value));records.append(dict(arm=name,role=role,
                state_ref={'tensor_sha256':'state'},predictions_ref=dict(path=str(path),sha256=subject.sha(path))))
    return {'fresh_rows':rows},records


@pytest.mark.parametrize('key,value',[('complete',False),('generation_reference_access',True),
    ('model_tensor_sha256','different'),('predictions',[])])
def test_bad_persisted_panel_stops_before_any_exposed_labels(tmp_path,monkeypatch,key,value):
    ctx,records=prediction_fixture(tmp_path);ref=records[-1]['predictions_ref'];path=Path(ref['path'])
    data=json.loads(path.read_text());data[key]=value;path.write_text(json.dumps(data));ref['sha256']=subject.sha(path)
    accesses=[];monkeypatch.setattr(subject,'bound_json',lambda *a:accesses.append(a))
    with pytest.raises(ValueError,match='incomplete exposed'):subject.load_exposed_references(ctx,records)
    assert accesses==[]


def test_mutated_prediction_bytes_stop_before_labels(tmp_path,monkeypatch):
    ctx,records=prediction_fixture(tmp_path);Path(records[0]['predictions_ref']['path']).write_text('{}')
    accesses=[];monkeypatch.setattr(subject,'bound_json',lambda *a:accesses.append(a))
    with pytest.raises(ValueError,match='prediction changed'):subject.load_exposed_references(ctx,records)
    assert accesses==[]


def test_old_holdout_is_never_claimed_fresh():
    assert subject.FALSE['fresh_holdout'] is subject.FALSE['fresh_authored_holdout'] is False
    assert 'previously_exposed' in subject.FIXED['exposed_r6_role']
    assert subject.FIXED['exposed_r6_panel_count']==12
