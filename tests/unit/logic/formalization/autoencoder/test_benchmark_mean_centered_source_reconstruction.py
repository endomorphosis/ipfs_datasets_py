"""Phase provenance, raw numerical replay, and complete source-only controls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('mean_centered_benchmark_test',
    ROOT/'scripts/ops/autoencoder/benchmark_mean_centered_source_reconstruction.py')
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.fixture(autouse=True)
def one_cpu():
    torch=pytest.importorskip('torch');old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('phase',['diagnostic','training'])
@pytest.mark.parametrize('key,value',[
    ('representation_dimension',768),('fixed_encoder_context_tokens',1024),
    ('fixed_decoder_output_limit',1024),('temperature',1),('no_downloads',False),
    ('selection_unchanged',False),('generation_reference_count_access',True),
    ('generation_reference_prefix_access',True),('scalar_mean_fit_split','validation'),
    ('scalar_auxiliary_readout','centered_classifier'),('native_qualification',True),
    ('diagnostic_efficacy_used_to_select_training',True),
])
def test_fixed_phases_reject_changed_geometry_targets_or_efficacy_selection(phase,key,value):
    plan=deepcopy(driver.DIAGNOSTIC_FIXED if phase=='diagnostic' else driver.TRAINING_FIXED)
    driver.validate_plan(plan,phase);plan[key]=value
    with pytest.raises(ValueError,match='fixed mean-centered'):driver.validate_plan(plan,phase)


def test_catalog_has_exact_eight_last_states_six_panels_each_and_four_training_fits(tmp_path):
    catalog=driver.expected_catalog(tmp_path)
    assert len(catalog)==8 and [row['name'] for row in catalog]==driver.PRIOR_ARMS
    assert len(catalog)*len(driver.MODES)*2==driver.DIAGNOSTIC_FIXED['expected_panels']==48
    assert all(row['role']=='last-attempt' and set(row['archived_evaluations'])=={'train','validation'} for row in catalog)
    assert len(driver.ARMS)*len(driver.TRAINING_FIXED['seed_order'])==4
    assert {r['scalar_mode'] for r in driver.ARMS}=={'raw','mean_centered'}
    assert all(r['guide_boundary'] and r['normalization']=='center_rms' for r in driver.ARMS)
    assert len(driver.CONTROLS)==5


@pytest.mark.parametrize('key,value',[('expected_optimizer_steps_per_arm',341),
    ('expected_count_presentations_per_arm',2441),('expected_source_value_presentations_per_candidate',25000),
    ('count_prior_total_concentration',32),('postfit_controls',[]),('raw_training_replay_parity_required',False),
    ('initial_greedy_invariance_required',False)])
def test_training_recipe_requires_exact_unchanged_budget_and_raw_controls(key,value):
    plan=deepcopy(driver.TRAINING_FIXED);plan[key]=value
    with pytest.raises(ValueError):driver.validate_plan(plan,'training')


def test_helper_pin_is_verified_before_any_execution(tmp_path):
    path=tmp_path/'owner.py';marker=tmp_path/'executed'
    path.write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
    with pytest.raises(ValueError):driver.load_helper(tmp_path,{'owner.py':'wrong'},'owner.py','bad_owner')
    assert not marker.exists()


def prerequisite_fixture(tmp_path):
    paths={name:str(tmp_path/(name+'.json')) for name in ['diagnostic_summary','diagnostic_plan','diagnostic_manifest','diagnostic_audit']}
    summary=dict(schema='mean-centered-source-diagnostic-comparison/v1',complete=True,raw_replay_parity=True,
        training_executed=False,panels=[{'ordered_exact':0}]*48,**driver.FALSE)
    for name,data in [('diagnostic_summary',summary),('diagnostic_plan',driver.DIAGNOSTIC_FIXED),('diagnostic_manifest',{'frozen':True})]:
        Path(paths[name]).write_text(json.dumps(data))
    pins={path:hashlib.sha256(Path(path).read_bytes()).hexdigest() for name,path in paths.items() if name!='diagnostic_audit'}
    audit=dict(schema='mean-centered-source-diagnostic-audit/v1',phase='diagnostics',passed=True,
        complete=True,failed_check_count=0,finding_count=0,findings=[],
        diagnostic_summary_sha256=pins[paths['diagnostic_summary']],plan_sha256=pins[paths['diagnostic_plan']],
        manifest_sha256=pins[paths['diagnostic_manifest']],
        artifacts={paths['diagnostic_summary']:dict(sha256=pins[paths['diagnostic_summary']],bytes=Path(paths['diagnostic_summary']).stat().st_size)})
    Path(paths['diagnostic_audit']).write_text(json.dumps(audit))
    pins[paths['diagnostic_audit']]=hashlib.sha256(Path(paths['diagnostic_audit']).read_bytes()).hexdigest()
    manifest=dict(paths,inputs=pins)
    def read_bound(path,manifest,published=None):
        raw=Path(path).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==manifest['inputs'][path]
        return json.loads(raw)
    return manifest,audit,SimpleNamespace(read_bound=read_bound)


def test_training_prerequisite_accepts_integrity_even_with_zero_diagnostic_reconstruction(tmp_path):
    manifest,_,reader=prerequisite_fixture(tmp_path)
    receipt=driver.diagnostic_prerequisite(manifest,reader)
    assert receipt['complete'] and receipt['training_arms_fixed_before_diagnostic']
    assert 'no efficacy selection' in receipt['acceptance_scope']


@pytest.mark.parametrize('field,value',[('passed',False),('failed_check_count',1),('finding_count',1),
    ('findings',['bad']),('diagnostic_summary_sha256','f'*64),('plan_sha256','f'*64),
    ('manifest_sha256','f'*64),('schema','other-audit/v1'),('phase','training')])
def test_training_prerequisite_refuses_unbound_or_failed_integrity_audit(tmp_path,field,value):
    manifest,audit,reader=prerequisite_fixture(tmp_path);audit[field]=value
    path=Path(manifest['diagnostic_audit']);path.write_text(json.dumps(audit))
    manifest['inputs'][str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):driver.diagnostic_prerequisite(manifest,reader)


def raw_fixture():
    rows=[dict(id='row',input=[1.],source_text='source',target_ids=[1,3,2])]
    codec={'target_vocabulary':['<pad>','<bos>','<eos>','x']};transform={'mean':[0.],'scale':1.}
    report=dict(complete=True,input_dimension=384,max_target_tokens=512,batch_size=8,
        generation_temperature=0,generation_target_access=False,optimizer_steps=0,weight_selection_performed=False,
        validation_rows_sha256=digest(rows),codec_sha256=digest(codec),input_transform_sha256=digest(transform),
        metrics={'eos_count':1,'token_cross_entropy':.1})
    value=dict(report=report,predictions=[dict(id='row',token_ids=[3],eos_reached=True)],
        source_fidelity={'metrics':{'ordered_exact':0},'by_length':{'1':0},'by_facet':{'actor':0}},
        source_count={'correct':1},source_values={'correct':2})
    return value,deepcopy(value),rows,SimpleNamespace(digest=digest),codec,transform


def test_fixed_raw_replay_checks_tokens_and_all_metrics_not_only_a_summary_flag():
    value,archived,*args=raw_fixture()
    assert driver.validate_raw_replay(value,archived,*args)['predictions_equal']
    value['predictions'][0]['token_ids']=[2]
    with pytest.raises(ValueError,match='greedy predictions'):driver.validate_raw_replay(value,archived,*args)


@pytest.mark.parametrize('field',['numerical','fidelity','raw_head','count','target_access'])
def test_raw_replay_rejects_numeric_or_recipe_drift(field):
    value,archived,*args=raw_fixture()
    if field=='numerical':value['report']['metrics']['token_cross_entropy']=.11
    elif field=='fidelity':value['source_fidelity']['by_facet']['actor']=1
    elif field=='raw_head':value['source_values']['correct']=3
    elif field=='count':value['source_count']['correct']=0
    else:archived['report']['generation_target_access']=True
    with pytest.raises(ValueError):driver.validate_raw_replay(value,archived,*args)


def synthetic_training():
    from .test_benchmark_projected_source_reconstruction import synthetic_training_model
    return synthetic_training_model()


def test_raw_wrapper_fresh_training_reproduces_actual_prior_tensors_losses_and_selection():
    torch,owner,trainer,base,train,tune,options=synthetic_training()
    from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as wrapper
    old=trainer.train(base,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    model=wrapper.bind_mean_centered_source_model(base,scalar_mode='raw',
        training_feature_mean_receipt=base.describe()['normalization'])
    new=trainer.train(model,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    digests={}
    for role,key in [('selected','state_dict'),('last-attempt','last_complete_attempt_state_dict')]:
        model.load_state_dict(new[key],strict=True);digests[role]=owner.core.tensor_digest(model.body)
    # Match the actual archived initializer inventory: it has no target score or
    # reconstructed-input vector, unlike the complete numerical evaluator.
    greedy_fields=('id','token_ids','eos_reached','generation_status')
    initial=[{key:row[key] for key in greedy_fields} for row in old['predictions']]
    assert set(old['predictions'][0])==set(greedy_fields)|{'exact_target','reconstructed_input'}
    assert initial!=old['predictions']
    prior=dict(arm='synthetic',training=old['report'],initial_greedy_invariance={'predictions':{'validation':initial}})
    postfit={'selected':{'validation':{'predictions':new['predictions']}}}
    archived_selected={'predictions':old['predictions']}
    checked=driver.validate_training_parity(new['report'],prior,digests,postfit,owner.core,
        archived_selected=archived_selected)
    assert checked['complete'] and checked['numerical_updates_exact']
    assert checked['selected_full_numerical_predictions_exact']
    assert checked['initial_greedy_prediction_fields']==sorted(greedy_fields)
    assert old['last_complete_attempt_predictions']==new['last_complete_attempt_predictions']
    altered=deepcopy(new['report']);altered['committed_updates'][0]['token_ce']+=1e-6
    with pytest.raises(ValueError,match='committed_updates'):
        driver.validate_training_parity(altered,prior,digests,postfit,owner.core,
            archived_selected=archived_selected)
    for field in ('id','token_ids','eos_reached','generation_status','exact_target','reconstructed_input'):
        changed=deepcopy(postfit);row=changed['selected']['validation']['predictions'][0]
        if field=='id':row[field]+='-changed'
        elif field=='token_ids':row[field][0]+=1
        elif field in ('eos_reached','exact_target'):row[field]=not row[field]
        elif field=='generation_status':row[field]='changed'
        else:row[field][0]+=1e-6
        with pytest.raises(ValueError,match='raw selected'):
            driver.validate_training_parity(new['report'],prior,digests,changed,owner.core,
                archived_selected=archived_selected)
    changed=deepcopy(prior)
    changed['initial_greedy_invariance']['predictions']['validation'][0]['exact_target']=False
    with pytest.raises(ValueError,match='envelope'):
        driver.validate_training_parity(new['report'],changed,digests,postfit,owner.core,
            archived_selected=archived_selected)


@pytest.mark.parametrize('mode',['raw','off','mean_centered'])
def test_applied_scalar_readout_is_source_only_separate_from_unchanged_auxiliary(mode):
    torch,owner,trainer,base,train,tune,options=synthetic_training()
    from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as wrapper
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as exposure
    with torch.no_grad():base.source_value_head.bias.fill_(.2);base.source_value_head.weight.fill_(.1)
    model=wrapper.bind_mean_centered_source_model(base,scalar_mode=mode,
        training_feature_mean_receipt=base.describe()['normalization'])
    ctx=dict(core=owner.core,donor={'codec':options['codec'],'input_transform':options['input_transform']},
        owners={'long_span_count_exposure_training':exposure})
    result=driver.guidance_diagnostic(ctx,model,tune,time.monotonic()+5)
    assert len(result['rows'])==len(tune) and result['source_only']
    assert not result['reference_documents_passed_to_model'] and not result['metric_used_for_selection']
    projected=model.project(exposure._source_batch(torch,tune,options['input_transform']))
    expected=model.source_value_guidance_logits(projected).tolist()
    assert [row['applied_logits'] for row in result['rows']]==expected
    if mode=='off':assert not torch.tensor(expected).count_nonzero()
    with pytest.raises(ValueError,match='deadline exceeded'):
        driver.guidance_diagnostic(ctx,model,tune,time.monotonic()-1)


@pytest.mark.parametrize('mode',['raw','mean_centered'])
def test_full_postfit_evaluation_keeps_targets_out_of_generation_and_exports_both_readouts(mode):
    torch,owner,trainer,base,train,tune,options=synthetic_training()
    from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as wrapper
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as exposure
    from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as scalar
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as scorer
    old=driver.load_helper(ROOT,{'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py':
        hashlib.sha256((ROOT/'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py').read_bytes()).hexdigest()},
        'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py','mean_eval_prior')
    model=wrapper.bind_mean_centered_source_model(base,scalar_mode=mode,
        training_feature_mean_receipt=base.describe()['normalization'])
    ctx=dict(core=owner.core,old=old,plan=driver.TRAINING_FIXED,rows={'validation':tune},
        references={'validation':options['validation_references']},donor={'codec':options['codec'],
        'input_transform':options['input_transform']},lineage=options['lineage'],scorer=scorer,
        validate_rule=options['validate_rule'],validator_id=options['validator_id'],
        preprocessing={'count_prior':base.describe()['count_prior']},owners={
        'mean_centered_source_decoder_experiment':wrapper,'long_span_count_exposure_training':exposure,
        'source_value_decoder_experiment':scalar,'long_span_source_value_training':trainer})
    value=driver.evaluate(ctx,model,'validation','conditioned')
    assert not value['report']['generation_target_access'] and value['scalar_mode']==mode
    assert value['source_values']['present_values']==12 and len(value['scalar_guidance']['rows'])==2
    zero=driver.evaluate(ctx,model,'validation','zero_condition')
    if mode=='mean_centered':assert not torch.tensor(zero['scalar_guidance']['rows'][0]['applied_logits']).count_nonzero()
    assert zero['execution']['kind']=='zero_condition' and not zero['execution']['training_performed']
