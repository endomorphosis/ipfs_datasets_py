#!/usr/bin/env python3
"""Matched formula-sidecar training on real 8D, 384D and 768D source inputs.

Different source producers and reset source routes make this a comparison of
complete input/decoder systems, not an isolated dimensionality ablation. The
frozen identity projection is not a learned reconstruction accomplishment.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
ARMS=[dict(name='pooled',head_kind='pooled',order_augmentation=False,generated_boundary_weight=0.),
      dict(name='clauses',head_kind='clauses',order_augmentation=False,generated_boundary_weight=0.)]
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle'],
    ['context-only-shuffle','validation','context_only_shuffle'],
    ['context-reverse','validation','context_reverse'],['context-rotate','validation','context_rotate']]
FIXED=dict(schema='native-dimension-source-training-plan/v1',dimensions=[8,384,768],seed_order=[1729,2718],
    arms=ARMS,fit_count=12,source_seed=1729,epochs_per_source_stage=20,
    historical_linguistic_teacher_modified=False,source_routes_reset=True,
    identity_projection_frozen=True,identity_mse_is_not_learned_reconstruction=True,
    source_independent_donor_tensors_copied=True,dimension_only_ablation=False,
    same_representation_within_paired_arms=True,teacher_distillation_used=False,
    learning_rate=.001,batch_size=8,max_seconds_per_arm=180,validation_interval=4,
    expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
    expected_row_presentations_per_arm=2440,expected_count_presentations_per_arm=2440,
    expected_source_value_presentations_per_arm=25600,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    cardinality_weight=.25,source_value_weight=.25,count_exposure='balanced_all',strategy='semantic_fields',
    original_training_rows=48,exposed_validation_rows=48,unique_training_clause_count=113,
    unique_validation_clause_count=54,fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,
    temperature=0,selection_unchanged=True,full_vocabulary_retained=True,syntax_forced=False,closure_forced=False,
    production_promotion_allowed=False,generation_reference_count_access=False,postfit_controls=CONTROLS,
    max_seconds_per_postfit=30,max_seconds_per_numerical_evaluation=20,
    max_seconds_entire_run=2400,max_memory_bytes=536870912,
    no_downloads=True,encoder_executed_during_training=False,postfit_order_sources=0)


def require(value,message):
    if not value:raise ValueError(message)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),
        'fixed native-dimension comparison differs')

def jobs():
    return [(dimension,seed,deepcopy(arm)) for dimension in FIXED['dimensions']
        for seed in FIXED['seed_order'] for arm in ARMS]

def load_helper(root,pins,path,name):
    require(sha(root/path)==pins[path],'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'fixed inputs differ')
    for path,digest in manifest['inputs'].items():require(sha(path)==digest,'input changed: '+path)
    for key in ('dimension_inputs','parent_manifest','parent_plan'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'],'unbound manifest alias: '+key)
    prior=load_helper(args.extension_root,manifest['extensions'],
        'scripts/ops/autoencoder/benchmark_clause_context_source_training.py','_dimension_clause_runner')
    oldargs=SimpleNamespace(**vars(args));oldargs.manifest=Path(manifest['parent_manifest']);oldargs.plan=Path(manifest['parent_plan'])
    ctx=prior.load_context(oldargs)
    ctx.update(plan=plan,manifest=manifest,pins=manifest['extensions'],clause_runner=prior)
    for name in ('dimension_native_decoder_experiment',):
        ctx['owners'][name]=ctx['helpers'].extension(args.extension_root,AUTO+name+'.py',PREFIX+name,ctx['pins'])
    inputs=json.loads(Path(manifest['dimension_inputs']).read_bytes())
    require(inputs.get('complete') is True,'complete dimension source preparation required')
    require(ctx['core'].digest({k:v for k,v in inputs.items() if k!='inputs_sha256'})==inputs.get('inputs_sha256'),
        'dimension source input digest differs')
    ctx['dimension_inputs']=inputs;ctx['original_rows']=deepcopy(ctx['rows']);ctx['original_donor']=deepcopy(ctx['donor'])
    ctx['initial_generation_reference']=None
    return ctx


def transformed_rows(torch,rows,transform):
    return (torch.tensor([r['input'] for r in rows],dtype=torch.float32)
        -torch.tensor(transform['mean'],dtype=torch.float32))/transform['scale']


def prepare_dimension(ctx,dimension):
    import torch
    require(dimension in FIXED['dimensions'],'unregistered source dimension')
    # Keep numerical/source-owner objects shared; deepcopy is only for row metadata.
    lane=dict(ctx);lane['donor']=deepcopy(ctx['original_donor']);lane['dimension']=dimension
    data=ctx['dimension_inputs']['dimensions'][str(dimension)]
    rows={};contexts={};owner=ctx['owners']['clause_source_context'];core=ctx['core']
    for split in ('train','validation'):
        values=data[split];original=ctx['original_rows'][split]
        require(type(values) is list and len(values)==48 and [r['id'] for r in values]==[r['id'] for r in original],
            'native dimension row coverage/order differs')
        require(all(type(r) is dict and set(r)=={'id','source_text','input'} for r in values),'closed source-only rows required')
        rows[split]=[]
        for source,reference in zip(values,original):
            require(source['source_text']==reference['source_text'],'source changed across dimensions')
            core._vector(source['input'],dimension)
            rows[split].append(dict(source,target_ids=deepcopy(reference['target_ids'])))
        contexts[split]=owner.build_source_contexts([{k:r[k] for k in ('id','source_text')} for r in values],data['clause_cache'][split])
    require(not {core.digest(r['input']) for r in rows['train']} & {core.digest(r['input']) for r in rows['validation']},
        'native paragraph vector split overlap')
    binding=owner.validate_training_contexts(rows['train'],rows['validation'],contexts)
    require(binding['training']['dimension']==binding['validation']['dimension']==dimension
        and len(binding['training_clause_inventory'])==113 and len(binding['validation_clause_inventory'])==54,
        'native source clause inventory differs')
    with torch.inference_mode():
        matrix=torch.tensor([r['input'] for r in rows['train']],dtype=torch.float32)
        mean=matrix.mean(0);scale=max(float((matrix-mean).square().sum(1).mean().sqrt()),.01)
    transform=dict(mode='center_rms',mean=mean.tolist(),scale=scale,origin='training_only')
    lane.update(rows=rows,source_contexts=contexts,clause_binding=binding,clause_cache=data['clause_cache'])
    lane['donor']['input_transform']=transform
    raw,receipt=ctx['owners']['dimension_native_decoder_experiment'].bind_dimension_native_body(
        ctx['base_model'].body,dimension=dimension,source_seed=FIXED['source_seed'])
    lane['raw_initializer']=raw;lane['initializer_receipt']=receipt
    projected=ctx['owners']['projected_source_decoder_experiment']
    paragraph_features=[]
    with torch.inference_mode():
        input_values=transformed_rows(torch,rows['train'],transform);features=raw.project(input_values)
        require(torch.equal(features,input_values),'declared identity projection differs')
        for row,vector in zip(rows['train'],features.tolist()):
            paragraph_features.append(dict(id=row['id'],source_sha256=hashlib.sha256(row['source_text'].encode()).hexdigest(),features=vector))
    identity=dict(expected_training_ids=[r['id'] for r in rows['train']],
        forbidden_validation_ids=[r['id'] for r in rows['validation']],training_rows_sha256=core.digest(rows['train']))
    normalization=projected.fit_source_normalization(paragraph_features,kind='center_rms',**identity)
    counts=[dict(id=r['id'],source_sha256=r['source_sha256'],count=r['clause_count']) for r in ctx['references']['train']]
    count_prior=projected.fit_source_count_prior(counts,**identity)
    unique=owner.unique_training_clauses(rows['train'],rows['validation'],contexts)
    with torch.inference_mode():clause_features=raw.project(transformed_rows(torch,unique,transform)).tolist()
    clause_values=[dict(id=r['id'],source_sha256=r['source_sha256'],features=v) for r,v in zip(unique,clause_features)]
    clause_normalization=projected.fit_source_normalization(clause_values,kind='center_rms',
        expected_training_ids=[r['id'] for r in unique],
        forbidden_validation_ids=[r['id'] for r in binding['validation_clause_inventory']],
        training_rows_sha256=core.digest(rows['train']))
    clause_normalization['training_contexts_sha256']=core.digest(contexts['train'])
    clause_normalization['receipt_sha256']=core.digest({k:v for k,v in clause_normalization.items() if k!='receipt_sha256'})
    lane['preprocessing']=dict(normalizations={'center_rms':normalization},count_prior=count_prior)
    lane['clause_normalization']=clause_normalization
    lane['preparation']=dict(dimension=dimension,initializer=receipt,input_transform=transform,
        paragraph_normalization=normalization,clause_normalization=clause_normalization,count_prior=count_prior,
        paragraph_features=paragraph_features,clause_features=clause_values,source_binding=binding,
        representation=data['representation'],source_inputs_sha256=core.digest(data),
        projection_policy='frozen_identity_no_learned_reconstruction_claim',**FALSE)
    lane['lineage']=dict(ctx['lineage'],input_provenance_sha256=core.digest(data),
        teacher_lineage='source384_v2_source_independent_tensor_transfer',student_role='learned_formula_sidecar',
        student_lineage='native_dimension_formula_sidecar:'+str(dimension))
    return lane


def bind_candidate(ctx,recipe,seed):
    require(recipe in ARMS and seed in FIXED['seed_order'],'unplanned native candidate')
    persistent=ctx['adapter'].bind_persistent_model(ctx['raw_initializer'],dimension=ctx['dimension'],conditioning='every_step')
    base=ctx['owners']['projected_source_decoder_experiment'].bind_projected_source_model(persistent,
        codec=ctx['donor']['codec'],normalization_receipt=ctx['preprocessing']['normalizations']['center_rms'],
        count_prior_receipt=ctx['preprocessing']['count_prior'],guide_boundary=True,scalar_guidance=True)
    if recipe['head_kind']=='pooled':
        return ctx['owners']['shared_slot_source_decoder_experiment'].bind_shared_slot_source_model(base,head_seed=seed)
    return ctx['owners']['clause_source_decoder_experiment'].bind_clause_source_model(base,head_seed=seed,
        clause_normalization_receipt=ctx['clause_normalization'])


def validate_initial(ctx,model,seed):
    import torch
    baseline=bind_candidate(ctx,ARMS[0],seed);core=ctx['core'];candidate=ctx['clause_runner'].contextual(model)
    original=dict(baseline.named_parameters());mapped=set()
    for name,value in model.named_parameters():
        key=name.replace('clause_head.','body.source_value_head.',1) if name.startswith('clause_head.') else name
        require(key in original and torch.equal(value,original[key]) and value.requires_grad==original[key].requires_grad,
            'within-dimension initial parameters differ')
        mapped.add(key)
    omitted={'body.source_value_head.slot_embeddings'} if candidate else set()
    require(set(original)-mapped==omitted,'unregistered parameter omission')
    actual_buffers=dict(model.named_buffers())
    for name,value in baseline.named_buffers():
        require(name in actual_buffers and torch.equal(value,actual_buffers[name]),'initial inherited buffer differs')
    controls=[]
    for split in ('train','validation'):
        outputs=[]
        for offset in range(0,48,8):
            part=ctx['rows'][split][offset:offset+8];data=transformed_rows(torch,part,ctx['donor']['input_transform'])
            with torch.inference_mode():
                value=core._greedy(torch,model,data,512,len(ctx['donor']['codec']['target_vocabulary']),time.monotonic()+30,
                    **core._source_context_kwargs(torch,part,ctx['source_contexts'][split] if candidate else None,ctx['donor']['input_transform']))
            require(value is not None and torch.equal(value[0],data),'initial identity projection or generation differs')
            outputs.extend(dict(id=r['id'],token_ids=t,generation_status=s) for r,t,s in zip(part,value[1],value[2]))
        controls.append(dict(split=split,predictions=outputs))
    baseline_count=sum(p.numel() for p in baseline.parameters() if p.requires_grad)
    count=sum(p.numel() for p in model.parameters() if p.requires_grad)
    require(count-baseline_count==(-512 if candidate else 0),'paired native parameter delta differs')
    return dict(complete=True,dimension=ctx['dimension'],predictions=controls,
        baseline_trainable_parameters=baseline_count,trainable_parameters=count,
        initial_parameters_equal_after_head_rename=True,inherited_buffers_equal=True,omitted_parameter_names=sorted(omitted),
        identity_projection_verified=True,identity_projection_is_not_learned_reconstruction=True,**FALSE)


def save_state(ctx,model,recipe,role,selected,path):
    core=ctx['core'];state={name:value.tolist() for name,value in model.state_dict().items()};before=core.tensor_digest(model)
    record=dict(schema='private-native-dimension-source-state/v1',dimension=ctx['dimension'],recipe=recipe,role=role,
        architecture=model.describe(),initializer_receipt=ctx['initializer_receipt'],input_transform=ctx['donor']['input_transform'],
        lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],model_state=state,
        weights_sha256=core.digest(state),tensor_sha256=before,selected=selected,optimizer_resumable=False,**FALSE)
    ref=ctx['helpers'].save(path,record)
    saved=json.loads(Path(ref['path']).read_bytes())
    require(saved['weights_sha256']==core.digest(saved['model_state']),'persisted state differs')
    restored=ctx['clause_runner'].restored_tensors(ctx,saved['model_state'],model.state_dict())
    validate_wrapper_state(ctx,restored)
    model.load_state_dict(restored,strict=True)
    require(core.tensor_digest(model)==before,'typed state reload changed model')
    return dict(ref,tensor_sha256=before)


def validate_wrapper_state(ctx,state):
    prefix='body.body.body.'
    native={name[len(prefix):]:value for name,value in state.items() if name.startswith(prefix)}
    ctx['owners']['dimension_native_decoder_experiment'].validate_restored_state(
        ctx['raw_initializer'],ctx['initializer_receipt'],native)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True);args=parser.parse_args()
    started=time.monotonic();ctx=load_context(args);h=ctx['helpers'];core=ctx['core'];save=h.save
    before=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    reference=None;runs=[]
    for dimension in FIXED['dimensions']:
        lane=prepare_dimension(ctx,dimension)
        save(args.output/str(dimension)/'preprocessing.json',lane['preparation'])
        save(args.output/str(dimension)/'source-contexts.json',lane['source_contexts'])
        save(args.output/str(dimension)/'training-rows.json',lane['rows'])
        for seed in FIXED['seed_order']:
            for recipe in ARMS:
                require(time.monotonic()-started<FIXED['max_seconds_entire_run'],'comparison deadline exceeded')
                arm_started=time.monotonic();name=str(dimension)+'-'+recipe['name']+'-'+str(seed);folder=args.output/name
                lane['lineage']['student_lineage']='native_dimension_formula_sidecar:'+name
                model=bind_candidate(lane,recipe,seed);initial=validate_initial(lane,model,seed)
                if reference is None:reference=initial['predictions']
                require(initial['predictions']==reference,'source-neutral initial full generation differs across dimensions')
                save(folder/'initial-parity.json',initial)
                states={'initial':save_state(lane,model,recipe,'initial',False,folder/'initial-state.json')}
                fit_started=time.monotonic();value=ctx['clause_runner'].train_candidate(lane,model,seed,recipe)
                fit_seconds=time.monotonic()-fit_started;report=value['report'];save(folder/'training.json',report)
                require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==340
                    and report['row_presentations']==2440 and report['valid_target_token_presentations']==225840
                    and report['source_value_presentations']==25600 and report['count_training_row_presentations']==2440
                    and report['count_training_presentations_by_class']==FIXED['expected_balanced_count_presentations'],
                    'incomplete native training exposure')
                postfit={}
                for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                    ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                    require(state is not None,'complete selected/final state required')
                    validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
                    expected_digest=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                    require(core.tensor_digest(model)==expected_digest,'training report state hash differs')
                    states[role]=save_state(lane,model,recipe,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                    postfit[role]={}
                    for label,split,control in CONTROLS:
                        panel=ctx['clause_runner'].evaluate(lane,model,split,control)
                        if label=='validation':require(panel['predictions']==predictions,'saved state generation differs')
                        save(folder/role/('evaluation-'+label+'.json'),panel)
                        postfit[role][label]=ctx['prior'].compact_panel(panel,retain_predictions=True)
                record=dict(arm=name,dimension=dimension,seed=seed,recipe=recipe,training=report,states=states,
                    postfit=postfit,initial_parity=initial,training_call_elapsed_seconds=fit_seconds,
                    elapsed_seconds=time.monotonic()-arm_started,budget_completed=True,
                    trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
                    identity_projection_is_not_learned_reconstruction=True,**FALSE)
                save(folder/'summary.json',record);runs.append(record)
                print(json.dumps(dict(arm=name,steps=340,selected_epoch=report['selected_epoch'],
                    final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    for path,digest in ctx['manifest']['inputs'].items():require(sha(path)==digest,'sealed input changed')
    for relative,digest in ctx['pins'].items():require(sha(args.extension_root/relative)==digest,'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'],'plan changed')
    require(time.monotonic()-started<FIXED['max_seconds_entire_run'],'comparison deadline exceeded')
    save(args.output/'summary.json',dict(schema='native-dimension-source-training-comparison/v1',complete=len(runs)==12,
        runs=runs,training_executed=True,dimensions_actually_trained=[8,384,768],source_dependencies=after,
        initial_generation_equal_across_all_arms=True,source_independent_transfer=True,historical_linguistic_teacher_modified=False,
        identity_projection_is_not_learned_reconstruction=True,dimension_only_ablation=False,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':main()
