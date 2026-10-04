"""Fixed-policy replay, typed persistence, and real tiny shared-head training."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[5]
REL='scripts/ops/autoencoder/benchmark_shared_slot_source_reconstruction.py'
SPEC=importlib.util.spec_from_file_location('shared_slot_benchmark_test',ROOT/REL)
driver=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(driver)


@pytest.fixture(autouse=True)
def one_cpu():
    torch=pytest.importorskip('torch');previous=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def synthetic():
    from .test_benchmark_projected_source_reconstruction import synthetic_training_model
    from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as shared
    from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as centered
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    torch,owner,trainer,base,train,tune,options=synthetic_training_model()
    return torch,owner,trainer,shared,centered,numerical,base,train,tune,options


@pytest.mark.parametrize('key,value',[
    ('representation_dimension',768),('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('source_value_full_vocabulary',False),('generation_reference_count_access',True),
    ('generation_reference_prefix_access',True),('source_segment_offsets_used',True),
    ('selection_unchanged',False),('temperature',1),('shared_slot_hidden_width',128),
    ('source_component_metadata_used_for_generation',True),('expected_optimizer_steps_per_arm',341),
    ('expected_source_value_presentations_per_candidate',25604),('teacher_distillation_used',True),
    ('native_qualification',True),('projection_frozen',False),('no_downloads',False),
    ('cached_source_order_recoverability_claimed',True),('scalar_generation_guidance','reference_tokens')])
def test_plan_rejects_geometry_exposure_or_authority_change(key,value):
    plan=deepcopy(driver.FIXED);driver.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed shared-slot'):driver.validate_plan(plan)


def test_four_predeclared_fits_have_original_complete_controls_and_seed_policy():
    assert len(driver.ARMS)*len(driver.FIXED['seed_order'])==4
    assert [x['head_kind'] for x in driver.ARMS]==['independent_affine','shared_slot_tanh']
    assert all(x['scalar_mode']=='raw' and x['guide_boundary'] and x['normalization']=='center_rms' for x in driver.ARMS)
    assert len(driver.CONTROLS)==5 and len(driver.CONTROLS)*2*4==40
    changed=deepcopy(driver.FIXED);changed['postfit_controls']=changed['postfit_controls'][:-1]
    with pytest.raises(ValueError):driver.validate_plan(changed)


@pytest.mark.parametrize('alteration',['missing','extra','changed','bad_digest','empty'])
def test_plan_input_inventory_must_exactly_bind_manifest(alteration):
    values={'/inputs/source.json':'a'*64,'/inputs/embedding.json':'b'*64}
    plan={'input_sha256':deepcopy(values)};manifest={'inputs':deepcopy(values)}
    driver.validate_input_bindings(plan,manifest)
    if alteration=='missing':plan['input_sha256'].pop('/inputs/source.json')
    elif alteration=='extra':plan['input_sha256']['/inputs/target.json']='c'*64
    elif alteration=='changed':manifest['inputs']['/inputs/source.json']='d'*64
    elif alteration=='bad_digest':plan['input_sha256']['/inputs/source.json']=manifest['inputs']['/inputs/source.json']='bad'
    else:plan['input_sha256']=manifest['inputs']={}
    with pytest.raises(ValueError,match='input hash inventory'):driver.validate_input_bindings(plan,manifest)


def test_raw_controls_authenticate_both_full_selected_and_final_panels_before_training(tmp_path):
    summary=tmp_path/'summary.json';paths=driver.selected_evaluation_paths(summary)
    manifest={'parent_summary':str(summary),'prior_selected_evaluations':paths,
        'state_catalog':[dict(name=name,archived_evaluations={'validation':str(tmp_path/name/'last-attempt/evaluation-validation.json')}) for name in paths]}
    seen=[]
    def bound(path,actual,public):
        assert actual is manifest and public=={'frozen':True};seen.append(path);return {'path':path}
    ctx={'manifest':manifest,'archives':SimpleNamespace(read_bound=bound),'public':{'frozen':True}}
    result=driver.authenticate_raw_controls(ctx)
    assert len(seen)==4 and all(set(v)=={'selected','last-attempt'} for v in result.values())
    manifest['prior_selected_evaluations']={};seen.clear()
    with pytest.raises(ValueError,match='exact two'):driver.authenticate_raw_controls(ctx)
    assert seen==[]


def test_candidate_dispatch_preserves_raw_replay_wrapper_and_uses_explicit_shared_seed():
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    prior=SimpleNamespace(fresh_base=lambda ctx,kind,boundary:base,
        wrap=lambda ctx,value,mode:centered.bind_mean_centered_source_model(value,scalar_mode=mode))
    ctx={'prior':prior,'owners':{'shared_slot_source_decoder_experiment':shared}}
    raw=driver.bind_candidate(ctx,driver.ARMS[0],1729)
    model=driver.bind_candidate(ctx,driver.ARMS[1],2718)
    assert raw.describe()['schema']==centered.SCHEMA and raw.describe()['scalar_mode']=='raw'
    assert owner.core.tensor_digest(raw.body)==owner.core.tensor_digest(base)
    assert model.describe()['schema']==shared.SCHEMA and int(model.head_initialization_seed)==2718
    bad=deepcopy(driver.ARMS[1]);bad['hidden_width']=32
    with pytest.raises(ValueError,match='unplanned'):driver.bind_candidate(ctx,bad,1729)


def test_actual_shared_training_updates_readout_and_hidden_geometry_with_unchanged_exposure():
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    model=shared.bind_shared_slot_source_model(base,head_seed=1729);before=owner.core.tensor_digest(model)
    result=trainer.train(model,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    report=result['report'];state=result['last_complete_attempt_state_dict']
    assert owner.core.tensor_digest(model)==before
    assert report['optimizer_steps']==2 and report['source_value_presentations']==16
    assert report['row_presentations']==report['count_training_row_presentations']==3
    assert report['source_value_head']['schema']==shared.SCHEMA
    for name in ('field_readout.weight','source_projection.weight','slot_embeddings'):
        key='body.source_value_head.'+name
        assert not torch.equal(state[key],model.state_dict()[key])
    for name,p in model.named_parameters():
        if not p.requires_grad:assert torch.equal(state[name],p)
    assert not report['qualified'] and not report['lake_executed']
    persisted=json.loads(json.dumps({k:v.tolist() for k,v in state.items()}))
    model.load_state_dict(driver.restored_tensors({'numerical':numerical},persisted,model.state_dict()),strict=True)
    assert model.head_initialization_seed.dtype==torch.long
    assert owner.core.tensor_digest(model)==report['last_complete_attempt_weights_sha256']
    assert trainer._head_specification(model,options['codec'],.25)==model.describe()


@pytest.mark.parametrize('seed',[True,1729.,1729.5,[1729],1730])
def test_typed_state_reload_rejects_changed_or_lossy_seed_without_mutating_model(seed):
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    model=shared.bind_shared_slot_source_model(base,head_seed=1729);before=owner.core.tensor_digest(model)
    state={k:v.tolist() for k,v in model.state_dict().items()};state['head_initialization_seed']=seed
    with pytest.raises(ValueError,match='integer initialization seed'):
        driver.restored_tensors({'numerical':numerical},state,model.state_dict())
    assert owner.core.tensor_digest(model)==before


def test_typed_state_reload_rejects_unknown_dtype_or_inventory():
    torch=pytest.importorskip('torch');ctx={'numerical':SimpleNamespace(_tensor=lambda v,t,n:torch.tensor(v,dtype=torch.float32))}
    with pytest.raises(ValueError,match='inventory'):driver.restored_tensors(ctx,{}, {'x':torch.zeros(1)})
    with pytest.raises(ValueError,match='integer initialization seed'):
        driver.restored_tensors(ctx,{'x':1},{'x':torch.tensor(1,dtype=torch.long)})


@pytest.mark.parametrize('kind',['independent','shared'])
def test_initial_capture_binds_actual_parameters_and_preserves_runtime_state(tmp_path,kind):
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    model=(shared.bind_shared_slot_source_model(base,head_seed=1729) if kind=='shared'
        else centered.bind_mean_centered_source_model(base,scalar_mode='raw'))
    model.train();parameter=next(p for p in model.parameters() if p.requires_grad)
    parameter.grad=torch.ones_like(parameter);grad=parameter.grad.clone()
    before=owner.core.tensor_digest(model);rng=torch.get_rng_state().clone()
    def save(path,value):
        raw=json.dumps(value,sort_keys=True,allow_nan=False).encode();path.write_bytes(raw)
        return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    ctx={'core':owner.core,'helpers':SimpleNamespace(save=save),'lineage':options['lineage'],
        'donor':{'codec':options['codec']}}
    artifact=driver.capture_initial_state(ctx,model,driver.ARMS[kind=='shared'],tmp_path)
    state=json.loads(Path(artifact['path']).read_bytes())
    assert state['role']=='initial' and not state['selected'] and not state['qualified']
    assert state['architecture']==model.describe() and state['model_state']=={k:v.tolist() for k,v in model.state_dict().items()}
    assert artifact['tensor_sha256']==before==state['tensor_sha256']
    assert artifact['sha256']==hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest()
    assert state['underlying_body_tensor_sha256']==owner.core.tensor_digest(model.body)
    assert owner.core.tensor_digest(model)==before and torch.equal(parameter.grad,grad)
    assert torch.equal(torch.get_rng_state(),rng) and model.training
    model.load_state_dict(driver.restored_tensors({'numerical':numerical},state['model_state'],model.state_dict()),strict=True)
    assert owner.core.tensor_digest(model)==before
    if kind=='shared':assert type(state['model_state']['head_initialization_seed']) is int


@pytest.mark.parametrize('field',['training_rows_sha256','training_inventory','expected_training_ids','forbidden_validation_ids'])
def test_shared_schema_keeps_actual_train_validation_cohort_guard(field):
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    model=shared.bind_shared_slot_source_model(base,head_seed=1729)
    # Make a self-consistent but false receipt, with matching buffers; the model
    # specification validates internally, but the trainer must bind actual rows.
    description=model.describe();norm=description['normalization'];prior=description['count_prior']
    if field=='training_rows_sha256':replacement='1'*64
    elif field=='training_inventory':
        replacement=deepcopy(norm[field]);replacement[0]['source_sha256']='2'*64
    elif field=='expected_training_ids':replacement=list(reversed(norm[field]))
    else:replacement=['unrelated-validation-id']
    for receipt in (norm,prior):
        receipt[field]=replacement
        receipt['receipt_sha256']=owner.core.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
    # The true parent builder is used so normalization/prior cross-checks remain
    # active; no fake describe bypass substitutes for the training-cohort guard.
    newbase=owner.bind_projected_source_model(base.body,codec=options['codec'],normalization_receipt=norm,
        count_prior_receipt=prior,guide_boundary=True)
    wrong=shared.bind_shared_slot_source_model(newbase,head_seed=1729)
    with pytest.raises(ValueError,match='cohort differs'):
        trainer.train(wrong,train,tune,source_value_weight=.25,cardinality_weight=.25,
            count_exposure='balanced_all',strategy='semantic_fields',**options)


def test_shared_full_postfit_and_zero_control_use_source_only_outputs_and_keep_priors():
    torch,owner,trainer,shared,centered,numerical,base,train,tune,options=synthetic()
    from ipfs_datasets_py.logic.formalization.autoencoder import long_span_count_exposure_training as exposure
    from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as scalar
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as scorer
    def helper(file,name):
        path='scripts/ops/autoencoder/'+file
        return driver.load_helper(ROOT,{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest()},path,name)
    prior=helper('benchmark_mean_centered_source_reconstruction.py','shared_test_prior')
    old=helper('benchmark_projected_source_reconstruction.py','shared_test_old')
    model=shared.bind_shared_slot_source_model(base,head_seed=1729)
    with torch.no_grad():model.body.source_value_head.field_readout.bias.fill_(.2)
    ctx=dict(core=owner.core,prior=prior,old=old,plan=driver.FIXED,rows={'validation':tune},
        references={'validation':options['validation_references']},donor={'codec':options['codec'],
        'input_transform':options['input_transform']},lineage=options['lineage'],scorer=scorer,
        validate_rule=options['validate_rule'],validator_id=options['validator_id'],
        preprocessing={'count_prior':base.describe()['count_prior']},owners={
        'mean_centered_source_decoder_experiment':centered,'shared_slot_source_decoder_experiment':shared,
        'long_span_count_exposure_training':exposure,'source_value_decoder_experiment':scalar,
        'long_span_source_value_training':trainer})
    for control in ('conditioned','zero_condition'):
        result=driver.evaluate(ctx,model,'validation',control)
        assert not result['report']['generation_target_access']
        assert result['source_values']['present_values']==12
        assert result['scalar_guidance']['source_only'] and not result['scalar_guidance']['target_tokens_passed_to_model']
        assert torch.tensor(result['scalar_guidance']['rows'][0]['applied_logits']).count_nonzero()>0
    assert ctx['owners']['mean_centered_source_decoder_experiment'] is centered


def test_training_adapter_passes_original_objective_optimizer_budget_and_gate_inputs():
    seen={}
    def train(model,trainrows,tunerows,**kwargs):seen.update(kwargs);return {'sentinel':True}
    ctx={'owners':{'long_span_source_value_training':SimpleNamespace(train=train)},'rows':{'train':['train'],'validation':['validation']},
        'references':{'train':['train-reference'],'validation':['validation-reference']},'donor':{'codec':{},'input_transform':{}},
        'lineage':{},'validate_rule':object(),'validator_id':'original','stages':['stages']}
    assert driver.train_candidate(ctx,object(),2718)=={'sentinel':True}
    assert seen['config']==dict(seed=2718,max_seconds=90,max_target_tokens=512,batch_size=8,learning_rate=.001,
        max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.)
    assert seen['strategy']=='semantic_fields' and seen['source_value_weight']==seen['cardinality_weight']==.25
    assert seen['count_exposure']=='balanced_all' and seen['validate_rule'] is ctx['validate_rule']
