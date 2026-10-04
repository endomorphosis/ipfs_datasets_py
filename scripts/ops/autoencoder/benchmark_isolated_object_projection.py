#!/usr/bin/env python3
"""Fresh paired 8D formula-sidecar experiment; historical linguistic teacher untouched."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
PARENT_RUNNER='scripts/ops/autoencoder/benchmark_multidimension_modality_training.py'
MODEL=AUTO+'isolated_object_clause_decoder_experiment.py'
TRAINER=AUTO+'long_span_source_value_training.py'
BOUNDARY=AUTO+'contextual_generated_boundary_training.py'
ACTION=AUTO+'action_contrastive_decoder_training.py'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,fresh_authored_holdout=False,
    lake_executed=False,native_validation_executed=False,formalized=False,roundtrip_ok=False)
ARMS=[dict(name='source-head-lr10',object_separated=False),dict(name='isolated-object',object_separated=True)]
FIXED=dict(schema='isolated-object-pair-plan/v1',dimensions=[8],seed=1729,arms=ARMS,fit_count=2,
    fresh_initialization=True,optimizer_steps=340,row_presentations=2440,target_token_presentations=225840,
    count_presentations=2440,source_value_presentations=25600,balanced_counts={'1':610,'2':610,'4':610,'8':610},
    learning_rate=.001,non_action_learning_rate_multiplier=10.,cardinality_weight=.25,source_value_weight=.25,
    action_contrastive_weight=.05,generated_boundary_weight=.05,boundary_site_policy='first_last',
    additional_object_parameters=576,extra_training_data=False,extra_objective=False,
    baseline_retry=False,candidate_retry=True,replay_atol=2e-5,replay_rtol=2e-5,
    retry_reason='strict_original_batch_geometry_fallback_only;no_tolerance_change',
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,
    selection_unchanged=True,historical_linguistic_teacher_modified=False,normalization_refitted=False,
    max_seconds_per_fit=180,max_seconds_entire_run=900,max_seconds_per_panel=30,
    workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
    encoder_executed=False,downloads_performed=False,memory_bytes_per_fit=1073741824,
    postfit_control_count_per_endpoint=9,endpoint_roles=['selected','last-attempt'])


def require(value,message):
    if not value: raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();raw=path.read_bytes();wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or expected==wanted) and hashlib.sha256(raw).hexdigest()==wanted,'unbound or changed input: '+str(path))
    return json.loads(raw)


def validate_plan(plan):
    require(all(type(plan.get(k)) is type(v) and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed isolated-object plan differs')


def package_inventory():
    result={}
    for name,module in list(sys.modules.items()):
        if name!='ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):continue
        path=getattr(module,'__file__',None)
        if path:
            path=Path(path).resolve();require(path.suffix=='.py' and path.is_file(),'package source not Python file')
            result[str(path)]=sha(path)
    return result


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'plan seal differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'input changed')
    for rel,wanted in manifest['extensions'].items():require(sha(args.extension_root/rel)==wanted,'extension changed')
    parent=bound_json(manifest,manifest['parent_manifest']);bound_json(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root']).resolve()
    require(sha(root/PARENT_RUNNER)==parent['extensions'][PARENT_RUNNER],'parent runner changed')
    spec=importlib.util.spec_from_file_location('_isolated_object_r9',root/PARENT_RUNNER)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args));previous.extension_root=root
    previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=owner.load_context(previous)
    # Historical inventory verifies every old import against its declared frozen roots.
    ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    old_inventory=package_inventory();overlays=[];package=sys.modules[PREFIX[:-1]]
    for rel in (BOUNDARY,ACTION):
        name=PREFIX+Path(rel).stem;old=sys.modules.get(name)
        require(old is not None,'required prior helper absent: '+name)
        oldpath=Path(old.__file__).resolve();require(str(oldpath) in old_inventory,'unbound old helper')
        require(manifest['inputs'].get(str(oldpath))==sha(oldpath),'old helper not frozen in input closure')
        attribute=getattr(package,Path(rel).stem,None)
        require(attribute is None or attribute is old,'foreign prior helper attribute')
        alias=PREFIX+'_before_isolated_object_'+Path(rel).stem;require(alias not in sys.modules,'prior alias collision')
        sys.modules[alias]=old;del sys.modules[name]
        new=ctx['helpers'].extension(args.extension_root,rel,name,manifest['extensions'])
        setattr(package,Path(rel).stem,new);ctx['owners'][Path(rel).stem]=new
        overlays.append(dict(canonical=name,previous_path=str(oldpath),previous_sha256=old_inventory[str(oldpath)],
            retained_alias=alias,new_path=str(args.extension_root/rel),new_sha256=manifest['extensions'][rel]))
    model=ctx['helpers'].extension(args.extension_root,MODEL,PREFIX+'isolated_object_clause_decoder_experiment',manifest['extensions'])
    setattr(package,'isolated_object_clause_decoder_experiment',model)
    trainer=ctx['helpers'].extension(args.extension_root,TRAINER,PREFIX+'_isolated_object_training_owner',manifest['extensions'])
    ctx['owners']['long_span_source_value_training']=trainer
    baseline=bound_json(manifest,manifest['baseline_summary'])
    require(baseline['arm']=='8-source-head-lr10-1729' and baseline['dimension']==8 and baseline['budget_completed'],'baseline identity differs')
    ctx.update(object_owner=model,object_manifest=manifest,object_plan=plan,object_parent=owner,
        object_old_inventory=old_inventory,object_overlays=overlays,object_baseline=baseline,
        object_manifest_sha256=sha(args.manifest))
    return ctx


def source_inventory(args,ctx):
    result=package_inventory();permitted=dict(ctx['object_old_inventory'])
    permitted.update({str((args.extension_root/r).resolve()):h for r,h in ctx['object_manifest']['extensions'].items()})
    for path,wanted in result.items():require(permitted.get(path)==wanted,'unregistered or drifted package source: '+path)
    return result


def prepare_lane(ctx):
    lane=ctx['native_runner'].prepare_dimension(ctx,8)
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        require(bound_json(ctx['object_manifest'],Path(ctx['object_manifest']['parent_results'])/'8'/(name+'.json'))==value,'preprocessing/context/cohort changed')
    require(sum(((len(s['training_ids'])+7)//8)*s['epochs'] for s in lane['stages'])==340,'curriculum changed')
    return lane


def bind_model(lane,arm):
    old=lane['object_parent'].bind_candidate(lane,lane['object_parent'].ARMS[0],1729)
    return lane['object_owner'].bind_isolated_object_model(old,codec=lane['donor']['codec']) if arm['object_separated'] else old


def initial_parity(lane,model,arm):
    import torch
    baseline=lane['object_parent'].bind_candidate(lane,lane['object_parent'].ARMS[0],1729)
    old=baseline.state_dict();new=model.state_dict();extra=set(new)-set(old)
    require(extra==(set(lane['object_owner'].EXTRA_NAMES) if arm['object_separated'] else set()),'initial parameter inventory changed')
    require(all(torch.equal(v,new[n]) for n,v in old.items()),'inherited initial weights changed')
    panel=[]
    for split in ('train','validation'):
        preds=[]
        for offset in range(0,48,8):
            rows=lane['rows'][split][offset:offset+8];data=lane['native_runner'].transformed_rows(torch,rows,lane['donor']['input_transform'])
            kwargs=lane['core']._source_context_kwargs(torch,rows,lane['source_contexts'][split],lane['donor']['input_transform'])
            with torch.inference_mode():
                a=lane['core']._greedy(torch,baseline,data,512,32,time.monotonic()+30,**kwargs)
                b=lane['core']._greedy(torch,model,data,512,32,time.monotonic()+30,**kwargs)
            require(a is not None and b is not None and torch.equal(a[0],b[0]) and a[1:]==b[1:],'initial greedy parity differs')
            preds.extend(dict(id=r['id'],token_ids=t,generation_status=s) for r,t,s in zip(rows,b[1],b[2]))
        panel.append(dict(split=split,predictions=preds))
    require(panel==lane['object_baseline']['initial_parity']['predictions'],'archived initial predictions differ')
    return dict(complete=True,predictions=panel,initial_inherited_tensors_exact=True,
        parameter_delta=sum(p.numel() for p in model.parameters())-sum(p.numel() for p in baseline.parameters()),**FALSE)


def train_candidate(lane,model,arm):
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',non_action_learning_rate_multiplier=10.,
        config=dict(seed=1729,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,max_memory_bytes=1073741824),
        **({'generated_boundary_retry_on_mismatch':True} if arm['object_separated'] else {}))


def validate_report(report,arm):
    for field,wanted in [('optimizer_steps',340),('row_presentations',2440),('valid_target_token_presentations',225840),
        ('count_training_row_presentations',2440),('source_value_presentations',25600),('count_training_presentations_by_class',FIXED['balanced_counts'])]:
        require(report[field]==wanted,'unmatched training exposure: '+field)
    require(report['stopped_reason']=='epochs_completed' and report['selection']=='per_length_nonregression_then_fidelity_progress_then_reference_ce','budget or selection changed')
    require(all(report[k] is False for k in ('qualified','admitted','proof_authority','convergence_proven','lake_executed')),'unexpected authority')
    require(not any(k.startswith('auxiliary_source_modality_') or k.startswith('generated_source_margin_') for k in report),'unexpected auxiliary objective')
    if arm['object_separated']:
        require(report['isolated_object_additional_parameters']==576 and report['isolated_object_existing_loss_reductions_unchanged']
            and not report['isolated_object_auxiliary_objective_added'],'object branch policy changed')
        require(report['generated_boundary_retry_tolerance_changed'] is False,'boundary tolerance changed')


def evaluate_new(lane,model,split,control):
    import torch
    started=time.monotonic();deadline=started+30;owners=lane['owners'];core=lane['core'];original=lane['rows'][split]
    rows,contexts,execution=owners['clause_source_controls'].prepare_control(original,lane['source_contexts'][split],
        'conditioned' if control in ('zero_condition','recurrent_residual_off') else control)
    working=model
    if control in ('zero_condition','recurrent_residual_off'):
        working=lane['object_owner'].bind_inference_control(model,codec=lane['donor']['codec'],zero_condition=control=='zero_condition')
        execution.update(kind=control)
    value=core.evaluate_model(working,rows,codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],
        lineage=lane['lineage'],max_target_tokens=512,max_seconds=20,batch_size=8,source_contexts=contexts)
    require(value['report']['complete'],'incomplete postfit')
    value['source_fidelity']=lane['scorer'].score_predictions(lane['references'][split],value['predictions'],codec=lane['donor']['codec'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],output_limit=512,control=execution['control'])
    value['source_count']=owners['long_span_count_exposure_training']._count_evaluation(torch,working,rows,lane['references'][split],
        lane['donor']['input_transform'],dict(batch_size=8),deadline)
    labels=owners['source_value_decoder_experiment'].reference_source_values(original,lane['references'][split],lane['donor']['codec'],validate_rule=lane['validate_rule'])
    value['source_values']=owners['long_span_source_value_training']._source_value_evaluation(torch,working,rows,labels,
        lane['donor']['input_transform'],dict(batch_size=8),lane['donor']['codec'],deadline,source_contexts=contexts)
    require(value['source_count'] is not None and value['source_values'] is not None,'incomplete count/scalar readout')
    value['scalar_guidance']=lane['clause_runner'].guidance_diagnostic(lane,working,rows,contexts,deadline)
    value['execution']=dict(execution,training_performed=False,selection_performed=False,context_passed_to_model=True,source_contexts_sha256=core.digest(contexts))
    value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-started,scope='generation, reference CE, fidelity, count/scalar readouts; excludes writes')
    require(time.monotonic()<deadline,'postfit deadline exceeded')
    return value


def comparable(report):
    value=deepcopy(report);value.pop('elapsed_seconds')
    for update in value['committed_updates']:
        receipt=update['generated_boundary'];receipt.pop('elapsed_seconds');receipt.pop('collection_sha256');receipt['generation'].pop('elapsed_seconds')
    return value


def execute(args):
    started=time.monotonic();ctx=load_context(args);before=source_inventory(args,ctx);lane=prepare_lane(ctx);save=ctx['helpers'].save
    args.output.mkdir(parents=True);save(args.output/'sealed-recipe.json',dict(plan=ctx['object_plan'],manifest=ctx['object_manifest'],overlays=ctx['object_overlays'],**FALSE))
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:save(args.output/'8'/(name+'.json'),value)
    runs=[]
    for arm in ARMS:
        require(time.monotonic()-started<900,'whole run deadline exceeded');name='8-'+arm['name']+'-1729';folder=args.output/name
        lane['lineage']['student_lineage']=('isolated_object_formula_sidecar:' if arm['object_separated'] else 'source_head_learning_rate_formula_sidecar:')+name
        model=bind_model(lane,arm);parity=initial_parity(lane,model,arm);save(folder/'initial-parity.json',parity)
        if args.phase=='preflight':runs.append(dict(arm=name,initial_parity=parity));continue
        state_recipe=arm if arm['object_separated'] else lane['object_parent'].ARMS[0]
        states={'initial':lane['native_runner'].save_state(lane,model,state_recipe,'initial',False,folder/'initial-state.json')}
        fit_start=time.monotonic();value=train_candidate(lane,model,arm);fit_seconds=time.monotonic()-fit_start
        report=value['report'];report_ref=save(folder/'training.json',report);validate_report(report,arm);panels={}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            require(state is not None,'complete endpoint missing');lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected,'endpoint tensor digest differs')
            states[role]=lane['native_runner'].save_state(lane,model,state_recipe,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            if not arm['object_separated']:
                lane['object_parent'].evaluate_original_panels(lane,model,predictions,folder/role)
            panels[role]={}
            for label,split,control in [*lane['object_parent'].CONTROLS,['recurrent-residual-off','validation','recurrent_residual_off']]:
                path=folder/role/('evaluation-'+label+'.json')
                if arm['object_separated']:
                    panel=evaluate_new(lane,model,split,control);save(path,panel)
                else:panel=json.loads(path.read_bytes())
                if label=='validation':require(panel['predictions']==predictions,'saved endpoint predictions differ')
                panels[role][label]=dict(path=str(path),sha256=sha(path),fidelity=panel['source_fidelity'])
        replay=None
        if not arm['object_separated']:
            previous=lane['object_baseline'];old=bound_json(ctx['object_manifest'],previous['training_ref']['path'],previous['training_ref']['sha256'])
            require(comparable(report)==comparable(old),'historical baseline report did not replay')
            for role in ('initial','selected','last-attempt'):require(states[role]['tensor_sha256']==previous['states'][role]['tensor_sha256'],'historical baseline state differs')
            for role,parts in panels.items():
                for label,ref in parts.items():
                    actual=json.loads(Path(ref['path']).read_bytes());reference=bound_json(ctx['object_manifest'],previous['postfit'][role][label]['path'],previous['postfit'][role][label]['sha256'])
                    require(actual['predictions']==reference['predictions'],'historical control predictions differ')
            replay=dict(complete=True,states_exact=True,reports_exact_except_four_timing_paths=True,all_nine_controls_predictions_exact=True)
        record=dict(arm=name,dimension=8,seed=1729,recipe=arm,states=states,initial_parity=parity,training_ref=report_ref,postfit=panels,
            baseline_replay=replay,budget_completed=True,training_call_elapsed_seconds=fit_seconds,**FALSE)
        ref=save(folder/'summary.json',record);runs.append(dict(arm=name,summary_path=ref['path'],summary_sha256=ref['sha256']))
        print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
            final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
        del model,value,report,panels
    after=source_inventory(args,ctx);require(all(after.get(p)==h for p,h in before.items()),'loaded source changed')
    for path,wanted in ctx['object_manifest']['inputs'].items():require(sha(path)==wanted,'input changed after training')
    require(sha(args.plan)==ctx['object_manifest']['plan_sha256'] and sha(args.manifest)==ctx['object_manifest_sha256'],'plan or manifest changed')
    require(time.monotonic()-started<900,'whole run deadline exceeded')
    summary=dict(schema='isolated-object-pair-results/v1',complete=len(runs)==2,phase=args.phase,runs=runs,source_dependencies=after,
        source_overlays=ctx['object_overlays'],elapsed_seconds=time.monotonic()-started,training_executed=args.phase=='training',
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,**FALSE)
    save(args.output/'summary.json',summary);return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training','preflight'],required=True);execute(parser.parse_args())

if __name__=='__main__':main()
