"""Fixed-recipe, target-free replay and source-control boundary regressions."""
from copy import deepcopy
import hashlib
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location('projected_source_benchmark_test',
    ROOT/'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py')
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.fixture(autouse=True)
def one_cpu():
    torch=pytest.importorskip('torch')
    previous=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.mark.parametrize('key,value',[
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('selection_unchanged',False),('projection_frozen',False),('source_value_max_rules',16),
    ('source_value_full_vocabulary',False),('generation_reference_count_access',True),
    ('generation_reference_prefix_access',True),('expected_optimizer_steps_per_arm',341),
    ('temperature',1),('expected_source_value_presentations_per_candidate',24960),
    ('expected_optimizer_steps_per_arm',True),('seed_order',[1729]),
    ('postfit_controls',driver.CONTROLS[:-1]),('native_qualification',True),
    ('count_prior_alpha_per_class',1.),('count_prior_total_concentration',32.),
    ('normalization_fit_split','validation'),('count_prior_fit_split','validation'),
    ('normalization_scale','per_coordinate'),('count_prior_classes',[1,2,4,8]),
    ('initial_greedy_invariance_required',False),('inherited_decoder_and_count_trainable',False),
])
def test_plan_refuses_changes_to_recipe_exposure_or_semantics(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='unsupported fixed'):
        driver.validate_plan(plan)


def test_exact_eight_fit_factorial_and_fixed_prior():
    combinations={(arm['normalization'],arm['guide_boundary']) for arm in driver.ARMS}
    assert combinations=={('none',False),('none',True),('center_rms',False),('center_rms',True)}
    assert len(driver.ARMS)*len(driver.FIXED['seed_order'])==8
    assert all(a['source_value_weight']==a['cardinality_weight']==.25 for a in driver.ARMS)
    assert driver.FIXED['count_prior_alpha_per_class']*32==driver.FIXED['count_prior_total_concentration']==1.
    assert len(driver.CONTROLS)==5
    plan=deepcopy(driver.FIXED);plan['arms'][0]['count_exposure']='current_stage'
    with pytest.raises(ValueError):driver.validate_plan(plan)


def source_rows():
    rows=[];references=[]
    for length in (1,2,4,8):
        for index in range(12):
            identity=f'row-{length}-{index:02}'
            rows.append(dict(id=identity,input=[float(length),float(index)],
                source_text='original '+identity,target_ids=[1,length,index,2]))
            references.append(dict(id=identity,clause_count=length,target={'original':identity}))
    return rows,references


def test_cross_length_is_bijection_target_preserving_and_input_independent():
    rows,refs=source_rows();original=deepcopy((rows,refs))
    changed,receipt=driver.cross_length_shuffle(rows,refs)
    assert (rows,refs)==original
    counts={r['id']:r['clause_count'] for r in refs};by_id={r['id']:r for r in rows}
    assignment=receipt['source_assignment']
    assert set(assignment)==set(assignment.values())==set(by_id)
    assert receipt['kind']=='source_shuffle' and receipt['shuffle_policy']=='cross_length'
    for old,new in zip(rows,changed):
        assert counts[old['id']]!=counts[assignment[old['id']]]
        assert new['input']==by_id[assignment[old['id']]]['input']
        assert {k:v for k,v in new.items() if k!='input'}=={k:v for k,v in old.items() if k!='input'}
    changed[0]['input'][0]=-1;changed[0]['target_ids'][0]=-1
    assert (rows,refs)==original


@pytest.mark.parametrize('problem',['duplicate_rows','duplicate_refs','missing','singleton_length','equal_vectors','boolean_count'])
def test_cross_length_refuses_ineffective_or_unbalanced_controls(problem):
    rows,refs=source_rows()
    if problem=='duplicate_rows':rows[-1]=deepcopy(rows[0])
    elif problem=='duplicate_refs':refs[-1]=deepcopy(refs[0])
    elif problem=='missing':refs.pop()
    elif problem=='singleton_length':refs[0]['clause_count']=3
    elif problem=='equal_vectors':
        for row in rows:row['input']=[0.,0.]
    elif problem=='boolean_count':refs[0]['clause_count']=True
    with pytest.raises(ValueError):driver.cross_length_shuffle(rows,refs)


def test_control_scope_distinguishes_length_labels_and_no_count_generalization_claim():
    assert driver.control_scope('source_shuffle')['shuffle_preserves_reference_clause_count']
    assert not driver.control_scope('cross_length_shuffle')['shuffle_preserves_reference_clause_count']
    for kind in ('conditioned','source_shuffle','cross_length_shuffle','zero_condition'):
        assert not driver.control_scope(kind)['independent_count_generalization_test']
    with pytest.raises(ValueError):driver.control_scope('oracle')


def test_boundary_readout_is_prior_centered_shift_invariant_and_ignores_target_count():
    prior=[math.log((12+1/32)/49) if index in (0,1,3,7) else math.log((1/32)/49) for index in range(32)]
    values={'predictions':[dict(id='x',logits=prior,expected=8)]}
    receipt={'log_prior':prior,'receipt_sha256':'a'*64}
    result=driver.boundary_diagnostics(values,receipt)
    assert all(item['hypothetical_logit_correction']==0 for item in result['rows'][0]['boundaries'].values())
    values['predictions'][0].update(logits=[x+8 for x in prior],expected=1)
    shifted=driver.boundary_diagnostics(values,receipt)
    assert all(abs(item['hypothetical_logit_correction'])<1e-12 for item in shifted['rows'][0]['boundaries'].values())
    assert not result['observed_generation_boundaries'] and not result['reference_clause_count_used']


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),True])
def test_boundary_readout_rejects_nonfinite_and_boolean_scores(bad):
    prior=[0.]*32;values={'predictions':[dict(id='x',logits=[bad]+[0.]*31)]}
    with pytest.raises(ValueError):driver.boundary_diagnostics(values,{'log_prior':prior,'receipt_sha256':'a'*64})


def test_helper_authentication_precedes_execution(tmp_path):
    path=tmp_path/'helper.py';marker=tmp_path/'executed'
    path.write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
    with pytest.raises(ValueError):driver.load_helper(tmp_path,{'helper.py':'wrong'},'helper.py','bad_projected_helper')
    assert not marker.exists()
    driver.load_helper(tmp_path,{'helper.py':hashlib.sha256(path.read_bytes()).hexdigest()},'helper.py','good_projected_helper')
    assert marker.exists()


def test_initial_replay_uses_only_source_inputs_preserves_modes_and_detects_deadlines():
    torch=pytest.importorskip('torch')
    class Model:
        def __init__(self):self.training=True
        def named_modules(self):return [('',self)]
        def eval(self):self.training=False;return self
    model=Model();seen=[]
    def greedy(torch,actual,data,cap,size,deadline):
        seen.append(data.tolist());assert cap==512 and size==4 and not actual.training
        return data,[[3] for _ in data],['eos']*len(data)
    core=SimpleNamespace(tensor_digest=lambda model:'a'*64,_greedy=greedy)
    donor=dict(input_transform=dict(mean=[1.,1.],scale=2.),codec=dict(target_vocabulary=list('abcd')))
    # Deliberately omit target IDs and source text from the replay rows.
    rows={'train':[dict(id='train',input=[3.,5.])],'validation':[dict(id='validation',input=[5.,7.])]}
    result=driver.greedy_inventory(torch,core,model,rows,donor,max_seconds=3)
    assert seen==[[[1.,2.]],[[2.,3.]]] and model.training
    assert result['predictions']['train']==[dict(id='train',token_ids=[3],generation_status='eos',eos_reached=True)]
    assert not result['target_tokens_passed_to_model'] and not result['reference_documents_passed_to_model']
    core._greedy=lambda *args:None
    with pytest.raises(ValueError,match='deadline'):
        driver.greedy_inventory(torch,core,model,rows,donor,max_seconds=3)
    assert model.training


def synthetic_training_model(kind='center_rms',guided=True):
    torch=pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as model_owner
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
    from .test_long_span_cardinality_training import setup
    _,persistent,train,tune,options=setup()
    with torch.inference_mode():features=persistent.project(trainer._source_batch(torch,train,options['input_transform'])).tolist()
    rows=[dict(id=row['id'],source_sha256=hashlib.sha256(row['source_text'].encode()).hexdigest(),features=vector)
        for row,vector in zip(train,features)]
    identities=dict(expected_training_ids=[row['id'] for row in train],
        forbidden_validation_ids=[row['id'] for row in tune],training_rows_sha256=model_owner.core.digest(train))
    normalization=model_owner.fit_source_normalization(rows,kind=kind,**identities)
    counts=[dict(id=row['id'],source_sha256=row['source_sha256'],count=ref['clause_count'])
        for row,ref in zip(rows,options['training_references'])]
    prior=model_owner.fit_source_count_prior(counts,**identities)
    model=model_owner.bind_projected_source_model(persistent,codec=options['codec'],
        normalization_receipt=normalization,count_prior_receipt=prior,guide_boundary=guided)
    return torch,model_owner,trainer,model,train,tune,options


@pytest.mark.parametrize('kind,guided',[('none',False),('none',True),('center_rms',False),('center_rms',True)])
def test_new_schema_trains_jointly_with_original_objective_and_frozen_projection(kind,guided):
    torch,owner,trainer,model,train,tune,options=synthetic_training_model(kind,guided)
    old_threads=torch.get_num_threads();torch.set_num_threads(1)
    before=owner.core.tensor_digest(model)
    try:
        result=trainer.train(model,train,tune,source_value_weight=.25,cardinality_weight=.25,
            count_exposure='balanced_all',strategy='semantic_fields',**options)
    finally:torch.set_num_threads(old_threads)
    assert owner.core.tensor_digest(model)==before
    state=result['last_complete_attempt_state_dict'];report=result['report']
    assert state is not None and report['optimizer_steps']==2
    assert report['source_value_head']['schema']==owner.SCHEMA
    assert report['source_value_presentations']==16
    assert report['row_presentations']==report['count_training_row_presentations']==3
    assert torch.count_nonzero(state['source_value_head.weight'])>0
    assert torch.count_nonzero(state['count_head.weight'])>0
    assert any(not torch.equal(value,state[name]) for name,value in model.named_parameters()
        if name.startswith('body.') and value.requires_grad)
    for name,parameter in model.named_parameters():
        if not parameter.requires_grad:assert torch.equal(state[name],parameter),name
    for name,buffer in model.named_buffers():assert torch.equal(state[name],buffer),name
    for update in report['committed_updates']:
        expected=update['weighted_token_ce']+.25*update['count_ce']+.25*update['source_value_ce']
        expected+=report['config']['reconstruction_weight']*update['raw_reconstruction_mse']
        assert update['objective']==pytest.approx(expected,abs=1e-6)
    assert report['selection']=='per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert not report['source_value_metrics_used_for_selection'] and not report['count_metrics_used_for_selection']
    assert all(report[key] is False for key in trainer.FALSE)


@pytest.mark.parametrize('field,value',[
    ('feature_kind','inherited_conditioning'),('feature_dimension',384),('max_rules',7),
    ('source_fields',['action','actor','modality','object']),('vocabulary_size',1),('codec_sha256','0'*64),
    ('guidance',1),('guide_boundary',1),('count_features','hidden'),('count_classes',[1,2,4,8]),
    ('projection_frozen',False),('normalization_statistics_frozen',False),('count_prior_frozen',False),
    ('output_support','masked'),('source_value_target_access_during_generation',True),
    ('source_reference_count_access',True),('syntax_forced',True),('closure_forced',True),
])
def test_new_schema_specification_rejects_semantic_or_geometry_drift(field,value,monkeypatch):
    _,_,trainer,model,_,_,options=synthetic_training_model()
    description=model.describe();description[field]=value
    monkeypatch.setattr(model,'describe',lambda:description)
    with pytest.raises(ValueError,match='authenticated projected-source'):
        trainer._head_specification(model,options['codec'],.25)


def test_new_schema_specification_validates_receipt_bytes_and_copies(monkeypatch):
    _,owner,trainer,model,_,_,options=synthetic_training_model()
    description=trainer._head_specification(model,options['codec'],.25)
    description['normalization']['mean'][0]+=1
    assert model.describe()['normalization']['mean']!=description['normalization']['mean']
    monkeypatch.setattr(model,'describe',lambda:description)
    with pytest.raises(ValueError,match='receipt digest'):
        trainer._head_specification(model,options['codec'],.25)


def test_postfit_source_labels_work_after_json_state_serialization_and_reload():
    import json
    import time
    torch,owner,trainer,model,train,tune,options=synthetic_training_model()
    from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as scalar_owner
    state_values=json.loads(json.dumps({name:value.tolist() for name,value in model.state_dict().items()}))
    restored={name:torch.tensor(state_values[name],dtype=value.dtype) for name,value in model.state_dict().items()}
    model.load_state_dict(restored,strict=True)
    result=driver.source_value_diagnostic(torch,model,tune,options['validation_references'],options['codec'],
        options['input_transform'],time.monotonic()+5,scalar_owner=scalar_owner,trainer=trainer,
        validate_rule=options['validate_rule'])
    assert result['rows']==2 and result['present_values']==12
    assert not result['used_for_selection'] and not result['references_passed_to_model']
    assert result['predictions'][0]['expected_token_ids'][1]==[-1]*4
    with pytest.raises(ValueError,match='incomplete source-value readout'):
        driver.source_value_diagnostic(torch,model,tune,options['validation_references'],options['codec'],
            options['input_transform'],time.monotonic()-1,scalar_owner=scalar_owner,trainer=trainer,
            validate_rule=options['validate_rule'])


@pytest.mark.parametrize('mutation',['row_digest','source_hash','training_id','validation_id'])
def test_training_rejects_internally_valid_but_different_preprocessing_cohort(mutation,monkeypatch):
    _,owner,trainer,model,train,tune,options=synthetic_training_model()
    description=model.describe()
    for name in ('normalization','count_prior'):
        receipt=description[name]
        if mutation=='row_digest':receipt['training_rows_sha256']='f'*64
        elif mutation=='source_hash':receipt['training_inventory'][0]['source_sha256']='f'*64
        elif mutation=='training_id':
            receipt['training_inventory'][0]['id']='different-training-id'
            receipt['expected_training_ids'][0]='different-training-id'
        else:receipt['forbidden_validation_ids'][0]='different-validation-id'
        receipt['receipt_sha256']=owner.core.digest({key:value for key,value in receipt.items() if key!='receipt_sha256'})
    # Internally consistent receipts are still inadequate without actual-row binding.
    owner._checked_receipts(description['normalization'],description['count_prior'],model.dimension)
    monkeypatch.setattr(model,'describe',lambda:description)
    with pytest.raises(ValueError,match='cohort differs from actual'):
        trainer.train(model,train,tune,source_value_weight=.25,cardinality_weight=.25,
            count_exposure='balanced_all',strategy='semantic_fields',**options)
