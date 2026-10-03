#!/usr/bin/env python3
"""Fixed-budget ordered clause-context decoder comparison.

The shared model and all source-fidelity selection gates are unchanged. Optional
training supervision never enters source-only generation or native admission.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle']]
ARMS=[dict(name='baseline',head_kind='pooled',order_augmentation=False,generated_boundary_weight=0.),
      dict(name='clauses',head_kind='clauses',order_augmentation=False,generated_boundary_weight=0.)]
EXTRA_CONTROLS=[['context-only-shuffle','validation','context_only_shuffle'],
    ['context-reverse','validation','context_reverse'],['context-rotate','validation','context_rotate']]
ALL_CONTROLS=CONTROLS+EXTRA_CONTROLS

FIXED=dict(schema='clause-context-source-training-plan/v1',representation_dimension=384,
    seed_order=[1729,2718],arms=ARMS,head='shared_per_clause_tanh',hidden_width=64,
    candidate_hidden_formula='tanh(W*normalized_projected_clause+b)',
    candidate_training_parameter_delta=-512,clause_normalization_policy='unique_training_sources_first_occurrence',
    unique_training_clause_count=113,unique_validation_clause_count=54,
    richer_source_input_comparison=True,parameter_only_comparison=False,
    order_augmentation_enabled=False,generated_boundary_loss_enabled=False,
    epochs_per_source_stage=20,expected_optimizer_steps_per_arm=340,
    expected_training_token_presentations_per_arm=225840,expected_count_presentations_per_arm=2440,
    expected_source_value_presentations_per_candidate=25600,expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,
    learning_rate=.001,max_seconds_per_arm=180,validation_interval=4,source_value_weight=.25,
    cardinality_weight=.25,count_exposure='balanced_all',strategy='semantic_fields',
    order_extra_decoder_presentations=0,
    source_only_generation=True,generation_reference_count_access=False,generation_reference_prefix_access=False,
    full_vocabulary_retained=True,syntax_forced=False,closure_forced=False,
    original_training_rows=48,exposed_validation_rows=48,
    no_downloads=True,encoder_executed=False,verified_cached_embeddings=True,
    selection_unchanged=True,baseline_training_replay_required=True,native_qualification=False,
    production_promotion_allowed=False,postfit_controls=ALL_CONTROLS,max_seconds_per_postfit=30,
    max_seconds_per_numerical_evaluation=20,max_seconds_entire_run=2400,
    max_memory_bytes=536870912,postfit_order_sources=108,postfit_boundary_traces=False)


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),'fixed training recipe differs')


def load_helper(root,pins,path,name):
    require(sha(root/path)==pins.get(path),'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());pins=manifest['extensions']
    plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(plan.get('input_sha256')==manifest['inputs'],'training input bindings differ')
    replay=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/decoder_fidelity_replay.py','_order_training_replay')
    ctx=replay.load_context(args,validate_plan=validate_plan);h=ctx['helpers']
    shared=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_shared_slot_source_reconstruction.py','_order_training_shared')
    prior=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_mean_centered_source_reconstruction.py','_order_training_prior')
    old=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py','_order_training_projected')
    diagnostic=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_order_boundaries.py','_order_training_diagnostic')
    names=['decoder_cardinality_experiment','long_span_cardinality_training','long_span_count_exposure_training',
        'source_value_decoder_experiment','projected_source_decoder_experiment','mean_centered_source_decoder_experiment',
        'shared_slot_source_decoder_experiment','clause_source_context','clause_source_decoder_experiment',
        'clause_source_controls','order_source_diagnostic','boundary_source_diagnostic',
        'order_training_augmentation','generated_boundary_training','long_span_source_value_training']
    owners={name:h.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins) for name in names}
    exposure=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py','_order_training_exposure')
    public=json.loads(Path(manifest['shared_public_manifest']).read_bytes())
    result=json.loads(Path(manifest['shared_public_results']).read_bytes())
    require(public['schema']=='decoder-shared-slot-source-archive/v1' and result['schema']=='decoder-shared-slot-source-results/v1'
        and public['archive']==result['archive'],'shared predecessor publication differs')
    read=lambda path,pub:diagnostic.read_published(path,manifest,pub)
    summary=read(manifest['shared_summary'],public)
    require(summary['complete'] is True and summary['raw_training_replay_parity'] is True,'complete prior fits required')
    for key in ('donor','paragraphs','embeddings','curriculum','curriculum_inputs'):read(manifest[key],public)
    preprocessing=read(manifest['parent_preprocessing'],public)
    opub=json.loads(Path(manifest['order_public_manifest']).read_bytes())
    ores=json.loads(Path(manifest['order_public_results']).read_bytes())
    require(opub['schema']=='decoder-order-boundary-archive/v1' and ores['schema']=='decoder-order-boundary-results/v1'
        and opub['archive']==ores['archive'] and ores['training_executed'] is False,'published diagnostic differs')
    preparation=read(manifest['order_preparation'],opub)
    require(preparation==owners['order_source_diagnostic'].build_order_variants(ctx['corpus'],
        json.loads(Path(manifest['curriculum_inputs']).read_bytes()),codec=ctx['donor']['codec']),
        'source permutations differ from original training components')
    encoded=read(manifest['order_embeddings'],opub)
    require(encoded['producer']['asset_manifest']==ctx['embeddings']['producer']['asset_manifest']
        and encoded['producer']['actual_forward_tokens_checked'] is True and encoded['producer']['encoder_context_tokens']==512,
        'verified complete prior encoder observations required')
    ctx.update(manifest=manifest,owners=owners,shared=shared,prior=prior,old=old,diagnostic=diagnostic,exposure=exposure,
        preprocessing=preprocessing,prior_runs={r['arm']:r for r in summary['runs']},
        order_preparation=preparation,order_embeddings=encoded,public=public)
    cpub=json.loads(Path(manifest['clause_public_manifest']).read_bytes())
    cres=json.loads(Path(manifest['clause_public_results']).read_bytes())
    require(cpub['archive']==cres['archive'],'clause prerequisite archive differs')
    cached={split:read(manifest['clause_cache_'+split],cpub) for split in ('train','validation')}
    inventory=read(manifest['clause_inventory'],cpub)
    read(manifest['clause_metadata'],cpub)
    source_cache={split:[{k:row[k] for k in ('id','source_text','input')} for row in rows]
        for split,rows in cached.items()}
    owner=owners['clause_source_context']
    contexts=owner.prepare_source_contexts(ctx['rows']['train'],ctx['rows']['validation'],
        cache_rows=source_cache,clause_inventory=inventory)
    binding=owner.validate_training_contexts(ctx['rows']['train'],ctx['rows']['validation'],contexts)
    require(len(binding['training_clause_inventory'])==113 and len(binding['validation_clause_inventory'])==54,
        'fixed clause inventory differs')
    ctx.update(source_contexts=contexts,clause_cache=source_cache,clause_inventory=inventory,clause_binding=binding)
    ctx['clause_normalization']=fit_clause_normalization(ctx)
    return ctx


def validate_baseline(report,prior,postfit,core):
    old=prior['training']
    require(set(report)==set(old),'baseline report inventory differs')
    fields=sorted(set(old)-{'elapsed_seconds','config'})
    for field in fields:require(core.digest(report[field])==core.digest(old[field]),'baseline replay differs: '+field)
    require({k:v for k,v in report['config'].items() if k!='max_seconds'}==
        {k:v for k,v in old['config'].items() if k!='max_seconds'}
        and report['config']['max_seconds']==180 and old['config']['max_seconds']==90,'baseline optimizer config differs')
    for role in ('selected','last-attempt'):
        for label,_,_ in CONTROLS:
            require(postfit[role][label]['predictions']==prior['postfit'][role][label]['predictions'],
                'baseline full source-control predictions differ')
    return dict(complete=True,compared_training_fields=fields,all_tensors_and_predictions_equal=True,
        prior_timeout_seconds=90,current_timeout_seconds=180,timing_equality_claimed=False,
        scope='same shared model, optimizer trajectory, selection and five controls; only wall headroom differs')


def train_candidate(ctx,model,seed,recipe):
    augmentation=(dict(preparation=ctx['order_preparation'],embedding_observations=ctx['order_embeddings'])
        if recipe['order_augmentation'] else None)
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        order_augmentation=augmentation,generated_boundary_weight=recipe['generated_boundary_weight'],
        **({} if recipe['head_kind']=='pooled' else {'source_contexts':ctx['source_contexts']}),
        config=dict(seed=seed,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.))



def fit_clause_normalization(ctx):
    import torch
    owner=ctx['owners']['clause_source_context'];core=ctx['core']
    rows=owner.unique_training_clauses(ctx['rows']['train'],ctx['rows']['validation'],ctx['source_contexts'])
    base=ctx['prior'].fresh_base(ctx,'center_rms',True);before=core.tensor_digest(base)
    with torch.inference_mode():
        transform=ctx['donor']['input_transform']
        data=(torch.tensor([r['input'] for r in rows],dtype=torch.float32)
            -torch.tensor(transform['mean'],dtype=torch.float32))/transform['scale']
        features=base.project(data).tolist()
    require(core.tensor_digest(base)==before,'clause preprocessing changed donor')
    values=[dict(id=row['id'],source_sha256=row['source_sha256'],features=vector) for row,vector in zip(rows,features)]
    receipt=ctx['owners']['projected_source_decoder_experiment'].fit_source_normalization(values,kind='center_rms',
        expected_training_ids=[r['id'] for r in rows],
        forbidden_validation_ids=[r['id'] for r in ctx['clause_binding']['validation_clause_inventory']],
        training_rows_sha256=core.digest(ctx['rows']['train']))
    receipt['training_contexts_sha256']=core.digest(ctx['source_contexts']['train'])
    receipt['receipt_sha256']=core.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
    ctx['clause_projection_features']=values
    return receipt


def bind_candidate(ctx,recipe,seed):
    require(recipe in ARMS and seed in FIXED['seed_order'],'unplanned clause candidate')
    base=ctx['prior'].fresh_base(ctx,'center_rms',True)
    if recipe['head_kind']=='pooled':
        return ctx['owners']['shared_slot_source_decoder_experiment'].bind_shared_slot_source_model(base,head_seed=seed)
    return ctx['owners']['clause_source_decoder_experiment'].bind_clause_source_model(base,head_seed=seed,
        clause_normalization_receipt=ctx['clause_normalization'])


def restored_tensors(ctx,state,template):
    """Restore float parameters and only the explicitly authenticated integer buffers."""
    import torch
    require(type(state) is dict and set(state)==set(template),'persisted state inventory differs')
    restored={}
    for name,value in template.items():
        if value.dtype==torch.float32:
            restored[name]=ctx['numerical']._tensor(state[name],value,name)
        else:
            require(name=='head_initialization_seed'
                and value.dtype==torch.long and value.device.type=='cpu' and tuple(value.shape)==()
                and type(state[name]) is int and state[name]==int(value),
                'persisted integer architecture buffer differs')
            restored[name]=torch.tensor(state[name],dtype=torch.long)
    return restored


def validate_initial(ctx,model,seed,expected):
    import torch
    baseline=bind_candidate(ctx,ARMS[0],seed);core=ctx['core']
    require(core.tensor_digest(baseline)==expected['training']['initial_weights_sha256'],
        'original shared initialization differs')
    original_parameters=dict(baseline.named_parameters());original_buffers=dict(baseline.named_buffers())
    mapped=set()
    for name,value in model.named_parameters():
        key=name.replace('clause_head.','body.source_value_head.',1) if name.startswith('clause_head.') else name
        require(key in original_parameters and torch.equal(value,original_parameters[key])
            and value.requires_grad==original_parameters[key].requires_grad,
            'initial inherited/head parameter values or trainability differ: '+name)
        mapped.add(key)
    expected_omitted={'body.source_value_head.slot_embeddings'} if contextual(model) else set()
    require(set(original_parameters)-mapped==expected_omitted,'unexpected omitted source parameters')
    for name,value in original_buffers.items():
        require(name in dict(model.named_buffers()) and torch.equal(value,dict(model.named_buffers())[name]),
            'initial inherited buffer differs: '+name)
    controls=[]
    for split in ('train','validation'):
        rows=ctx['rows'][split];reference=[];observed=[]
        transform=ctx['donor']['input_transform'];size=len(ctx['donor']['codec']['target_vocabulary'])
        for offset in range(0,len(rows),8):
            part=rows[offset:offset+8]
            data=ctx['owners']['long_span_count_exposure_training']._source_batch(torch,part,transform)
            with torch.inference_mode():
                a=core._greedy(torch,baseline,data,512,size,time.monotonic()+30)
                kw=({} if model.describe()['schema']!='clause-source-decoder-development/v1' else
                    core._source_context_kwargs(torch,part,ctx['source_contexts'][split],transform))
                b=core._greedy(torch,model,data,512,size,time.monotonic()+30,**kw)
            require(a is not None and b is not None and torch.equal(a[0],b[0]) and a[1:]==b[1:],
                'initial complete source generation differs')
            reference.extend([dict(id=row['id'],token_ids=tokens,status=status) for row,tokens,status in zip(part,a[1],a[2])])
            observed.extend([dict(id=row['id'],token_ids=tokens,status=status) for row,tokens,status in zip(part,b[1],b[2])])
        controls.append(dict(split=split,reference=reference,observed=observed))
    baseline_count=sum(p.numel() for p in baseline.parameters() if p.requires_grad)
    candidate_count=sum(p.numel() for p in model.parameters() if p.requires_grad)
    delta=-512 if model.describe()['schema']=='clause-source-decoder-development/v1' else 0
    require(candidate_count-baseline_count==delta,'unregistered parameter count change')
    return dict(complete=True,initial_greedy_predictions_equal=True,controls=controls,
        parameter_values_equal_after_head_renaming=True,inherited_buffers_equal=True,
        omitted_parameter_names=sorted(expected_omitted),
        baseline_tensor_sha256=core.tensor_digest(baseline),candidate_tensor_sha256=core.tensor_digest(model),
        baseline_trainable_parameter_count=baseline_count,candidate_trainable_parameter_count=candidate_count,
        parameter_delta=delta,**FALSE)


def save_state(ctx,model,recipe,role,selected,path):
    core=ctx['core'];digest=core.tensor_digest(model);state={key:value.tolist() for key,value in model.state_dict().items()}
    receipt=ctx['helpers'].save(path,dict(schema='private-clause-context-source-state/v1',recipe=recipe,
        architecture=model.describe(),lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],model_state=state,
        weights_sha256=core.digest(state),tensor_sha256=digest,role=role,selected=selected,optimizer_resumable=False,**FALSE))
    saved=json.loads(Path(receipt['path']).read_bytes())
    require(core.digest(saved['model_state'])==saved['weights_sha256'],'saved state differs')
    model.load_state_dict(restored_tensors(ctx,saved['model_state'],model.state_dict()),strict=True)
    require(core.tensor_digest(model)==digest,'persisted typed state differs')
    return dict(receipt,tensor_sha256=digest)


def contextual(model):
    return model.describe().get('schema') in (
        'clause-source-decoder-development/v1',
        'action-factorized-clause-source-decoder-development/v1')


def guidance_diagnostic(ctx,model,rows,contexts,deadline):
    import torch
    started=time.monotonic();core=ctx['core'];before=core.tensor_digest(model)
    modes={name:part.training for name,part in model.named_modules()};records=[]
    try:
        model.eval()
        with torch.inference_mode():
            for offset in range(0,len(rows),8):
                require(time.monotonic()<deadline,'context guidance deadline exceeded')
                part=rows[offset:offset+8];transform=ctx['donor']['input_transform']
                data=ctx['owners']['long_span_count_exposure_training']._source_batch(torch,part,transform)
                projected=model.project(data)
                logits=model.source_value_guidance_logits(projected,
                    **core._source_context_kwargs(torch,part,contexts,transform))
                require(tuple(logits.shape)==(len(part),8,4,len(ctx['donor']['codec']['target_vocabulary']))
                    and bool(torch.isfinite(logits).all()),'invalid context guidance logits')
                for row,scores,guess in zip(part,logits.tolist(),logits.argmax(-1).tolist()):
                    records.append(dict(id=row['id'],applied_logits=scores,predicted_token_ids=guess))
    finally:
        for name,part in model.named_modules():part.training=modes[name]
    require(core.tensor_digest(model)==before,'context guidance changed model')
    require(time.monotonic()<deadline,'context guidance deadline exceeded')
    return dict(schema='applied-clause-scalar-guidance-diagnostic/v1',rows=records,
        source_only=True,reference_documents_passed_to_model=False,target_tokens_passed_to_model=False,
        metric_used_for_selection=False,elapsed_seconds=time.monotonic()-started,**FALSE)


def evaluate(ctx,model,split,control):
    import torch
    use_context=contextual(model)
    if not use_context and control in {c[2] for c in CONTROLS}:
        return ctx['shared'].evaluate(ctx,model,split,control)
    started=time.monotonic();core=ctx['core'];owners=ctx['owners'];original=ctx['rows'][split]
    rows,contexts,execution=owners['clause_source_controls'].prepare_control(original,ctx['source_contexts'][split],
        'conditioned' if control=='zero_condition' else control)
    if control=='zero_condition':
        require(use_context,'context zero-control requires contextual model')
        owner=('action_factorized_clause_decoder_experiment'
            if model.describe().get('schema')=='action-factorized-clause-source-decoder-development/v1'
            else 'clause_source_decoder_experiment')
        model=owners[owner].bind_zero_condition_model(model)
        execution.update(kind='zero_condition',control=dict(kind='zero_condition',
            source_assignment={r['id']:r['id'] for r in original}),
            normalized_clause_values_and_padding_mask_removed=True)
    supplied=contexts if use_context else None
    deadline=started+ctx['plan']['max_seconds_per_postfit']
    value=core.evaluate_model(model,rows,codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],
        lineage=ctx['lineage'],max_target_tokens=512,max_seconds=min(20,deadline-time.monotonic()),batch_size=8,
        **({} if supplied is None else {'source_contexts':supplied}))
    require(value['report']['complete'],'incomplete contextual postfit evaluation')
    value['source_fidelity']=ctx['scorer'].score_predictions(ctx['references'][split],value['predictions'],
        codec=ctx['donor']['codec'],validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],
        output_limit=512,control=execution['control'])
    value['source_count']=owners['long_span_count_exposure_training']._count_evaluation(torch,model,rows,
        ctx['references'][split],ctx['donor']['input_transform'],dict(batch_size=8),deadline)
    require(value['source_count'] is not None,'incomplete count readout')
    # Bind labels against ORIGINAL sources before applying controlled input changes.
    labels=owners['source_value_decoder_experiment'].reference_source_values(original,ctx['references'][split],
        ctx['donor']['codec'],validate_rule=ctx['validate_rule'])
    value['source_values']=owners['long_span_source_value_training']._source_value_evaluation(torch,model,rows,labels,
        ctx['donor']['input_transform'],dict(batch_size=8),ctx['donor']['codec'],deadline,
        **({} if supplied is None else {'source_contexts':supplied}))
    require(value['source_values'] is not None,'incomplete scalar readout')
    value['scalar_guidance']=guidance_diagnostic(ctx,model,rows,supplied,deadline)
    value['hypothetical_boundary_diagnostics']=ctx['old'].boundary_diagnostics(value['source_count'],ctx['preprocessing']['count_prior'])
    value['execution']=dict(execution,training_performed=False,selection_performed=False,
        context_passed_to_model=use_context,source_contexts_sha256=None if supplied is None else core.digest(supplied))
    value['scalar_auxiliary_readout_scope']='present reference slots only; raw source head, not generated formula fidelity'
    value['scalar_mode']='raw'
    require(time.monotonic()<deadline,'context postfit deadline exceeded')
    value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-started,
        numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
        scope='control construction, numerical generation/CE, fidelity/count/scalar readouts; excludes writes')
    return value


def greedy_source_panel(ctx,model,rows,contexts):
    import torch
    core=ctx['core'];started=time.monotonic();deadline=started+120
    require(type(rows) is list and 1<=len(rows)<=108
        and all(type(r) is dict and set(r)=={'id','input','source_text'} for r in rows),
        'closed source-only order panel required')
    ctx['owners']['clause_source_context'].validate_contexts(rows,contexts)
    use_context=contextual(model);working=deepcopy(model).eval();before=core.tensor_digest(model)
    rng=torch.get_rng_state().clone();predictions=[];projected_rows={};logits_rows={};counts={}
    transform=ctx['donor']['input_transform'];size=len(ctx['donor']['codec']['target_vocabulary'])
    with torch.inference_mode():
        for offset in range(0,len(rows),8):
            part=rows[offset:offset+8]
            data=ctx['owners']['long_span_count_exposure_training']._source_batch(torch,part,transform)
            kw=core._source_context_kwargs(torch,part,contexts if use_context else None,transform)
            observed=core._greedy(torch,working,data,512,size,deadline,**kw)
            require(observed is not None,'context order diagnostic deadline exceeded')
            projected,generated,statuses=observed
            head=working.source_value_logits(projected,**kw).tolist();count=working.count_logits(projected).tolist()
            for row,vector,values,count_values,tokens,status in zip(part,projected.tolist(),head,count,generated,statuses):
                predictions.append(dict(id=row['id'],token_ids=tokens,eos_reached=status=='eos',generation_status=status))
                projected_rows[row['id']]=vector;logits_rows[row['id']]=values;counts[row['id']]=count_values
    require(core.tensor_digest(model)==before and core.tensor_digest(working)==before,'order diagnostic changed model')
    require(torch.equal(torch.get_rng_state(),rng),'order diagnostic changed RNG')
    require(time.monotonic()<deadline,'context order diagnostic deadline exceeded')
    elapsed=time.monotonic()-started
    return dict(schema='clause-context-order-observations/v1',predictions=predictions,
        projected_vectors=projected_rows,scalar_logits=logits_rows,count_logits=counts,
        model_tensor_sha256=before,rows=len(rows),elapsed_seconds=elapsed,wall_seconds_per_span=elapsed/len(rows),
        context_passed_to_model=use_context,source_contexts_sha256=core.digest(contexts),
        timing_scope='copy, source-only generation, source heads and identity checks; no encoder, CE or reference scoring',**FALSE)


def postfit_mechanisms(ctx,model,folder):
    save=ctx['helpers'].save;order=ctx['owners']['order_source_diagnostic'];prep=ctx['order_preparation']
    vectors={r['input_id']:r['vector'] for r in ctx['order_embeddings']['observations']['main']}
    rows=[dict(id=r['id'],input=vectors[r['id']],source_text=r['source_text']) for r in prep['rows']]
    contexts=ctx['owners']['clause_source_context'].build_source_contexts(
        [{k:r[k] for k in ('id','source_text')} for r in rows],ctx['clause_cache']['train'])
    observed=greedy_source_panel(ctx,model,rows,contexts);save(folder/'order-observations.json',observed)
    pairs=dict(projection=order.paired_vector_metrics(prep,observed['projected_vectors'],space='decoder_projection'),
        scalars=order.paired_scalar_metrics(prep,observed['scalar_logits'],codec=ctx['donor']['codec']),
        generated=order.paired_prediction_metrics(prep,{r['id']:r for r in observed['predictions']},codec=ctx['donor']['codec']))
    save(folder/'order-pairs.json',pairs)
    return dict(order_rows=108,order_wall_seconds_per_span=observed['wall_seconds_per_span'],
        structural_head_permutation_equivariance=contextual(model),
        structural_equivariance_is_not_learned_order_recovery=True,boundary_trace_executed=False,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True)
    args=parser.parse_args();started=time.monotonic();ctx=load_context(args);h=ctx['helpers'];core=ctx['core'];save=h.save
    before=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    save(args.output/'preprocessing-replay.json',ctx['prior'].validate_preprocessing(ctx))
    selector=ctx['owners']['order_training_augmentation'].prepare(ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],preparation=ctx['order_preparation'],
        embedding_observations=ctx['order_embeddings'],codec=ctx['donor']['codec'])
    save(args.output/'augmentation-preflight.json',selector.snapshot())
    save(args.output/'source-contexts.json',ctx['source_contexts'])
    save(args.output/'clause-preprocessing.json',dict(normalization=ctx['clause_normalization'],
        binding=ctx['clause_binding'],projected_features=ctx['clause_projection_features'],**FALSE))
    runs=[]
    for seed in FIXED['seed_order']:
        for recipe in ARMS:
            require(time.monotonic()-started<2400,'training comparison deadline exceeded')
            arm_started=time.monotonic()
            name=recipe['name']+'-'+str(seed);folder=args.output/name
            model=bind_candidate(ctx,recipe,seed)
            expected=ctx['prior_runs']['shared-'+str(seed)]
            ctx['lineage']=deepcopy(expected['training']['lineage'])
            if recipe['name']!='baseline':ctx['lineage']['student_lineage']='clause_context_source_v1:'+name
            initial=save_state(ctx,model,recipe,'initial',False,folder/'initial-state.json')
            initial_parity=validate_initial(ctx,model,seed,expected)
            save(folder/'initial-parity.json',initial_parity)
            fit_started=time.monotonic();value=train_candidate(ctx,model,seed,recipe);fit_seconds=time.monotonic()-fit_started
            report=value['report'];save(folder/'training.json',report)
            require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==340
                and report['row_presentations']==2440
                and report['valid_target_token_presentations']==225840 and report['source_value_presentations']==25600
                and report['count_training_row_presentations']==2440
                and report['count_training_presentations_by_class']==FIXED['expected_balanced_count_presentations'],
                'incomplete or changed training exposure')
            postfit={};states={};post_started=time.monotonic()
            for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                require(state is not None,'complete selected/final state required');model.load_state_dict(state,strict=True)
                expected_digest=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(core.tensor_digest(model)==expected_digest,'trained state differs')
                states[role]=save_state(ctx,model,recipe,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                postfit[role]={}
                for label,split,control in ALL_CONTROLS:
                    panel=evaluate(ctx,model,split,control)
                    if label=='validation':require(panel['predictions']==predictions,'persisted generation differs')
                    save(folder/role/('evaluation-'+label+'.json'),panel)
                    postfit[role][label]=ctx['prior'].compact_panel(panel,retain_predictions=True)
            parity=validate_baseline(report,expected,postfit,core) if recipe['name']=='baseline' else None
            mechanisms=postfit_mechanisms(ctx,model,folder/'last-attempt')
            require(core.tensor_digest(model)==report['last_complete_attempt_weights_sha256'],'postfit diagnostics changed state')
            record=dict(arm=name,seed=seed,recipe=recipe,training=report,initial_state=initial,states=states,
                postfit=postfit,baseline_replay=parity,initial_parity=initial_parity,mechanisms=mechanisms,budget_completed=True,
                training_call_elapsed_seconds=fit_seconds,postfit_elapsed_seconds=time.monotonic()-post_started,
                elapsed_seconds=time.monotonic()-arm_started,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),**FALSE)
            save(folder/'summary.json',record);runs.append(record)
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                last_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    h.validate_manifest_inputs(ctx['manifest'])
    for relative,digest in ctx['pins'].items():require(sha(args.extension_root/relative)==digest,'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'],'training plan changed')
    require(time.monotonic()-started<2400,'training comparison deadline exceeded')
    save(args.output/'summary.json',dict(schema='clause-context-source-training-comparison/v1',complete=len(runs)==4,runs=runs,
        training_executed=True,dimensions_actually_trained=[384],baseline_replay_parity=all(r['baseline_replay']['complete'] for r in runs if r['recipe']['name']=='baseline'),
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,verified_cached_embeddings=True,downloads_performed=False,**FALSE))


if __name__=='__main__':main()
