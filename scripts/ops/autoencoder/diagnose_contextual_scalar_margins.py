#!/usr/bin/env python3
"""Observe actual-prefix scalar decisions of authenticated saved formula sidecars.

One unchanged greedy pass per panel; references are supplied only after collection
and archived generation parity. This diagnostic never trains or selects weights.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
PUBLISHED_COMMIT='8e751fb9e7fff73647fcef834d7db81d4620caf8'
PUBLISHED_ARCHIVE_SHA256='c64296732d874ca3179e0b17a94aa522eca1dc63e1af81cd9cab7757f4ffb87b'
ARMS=['source-head-lr10','joint-replay-zero','joint-replay-fields']
SPLITS=[('train','training','training'),('validation','exposed_development','validation')]
FALSE=dict(training_executed=False,encoder_executed=False,downloads_performed=False,qualified=False,
 admitted=False,proof_authority=False,source_semantics_verified=False,checkpoint_promoted=False,
 convergence_proven=False,fresh_holdout=False,lake_executed=False,native_validation_executed=False,
 formalized=False,roundtrip_ok=False)
FIXED=dict(schema='contextual-scalar-margin-diagnostic-plan/v1',dimensions=[8,384,768],seed_order=[1729,2718],
 arms=ARMS,state_role='last-attempt',state_count=18,panel_count=36,samples_per_panel=48,batch_size=8,
 splits=['training','exposed_development'],fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,
 temperature=0,vocabulary_size=32,greedy_passes_per_panel=1,model_copies_during_observation=0,
 extra_forward_passes_for_decomposition=0,optimizer_steps=0,new_targets_created=False,
 generation_reference_access=False,posthoc_reference_scoring=True,archived_generation_parity_required=True,
 preserve_weights=True,preserve_historical_teacher=True,selection_unchanged=True,
 max_seconds_per_panel=30,max_seconds_entire_run=600,max_trace_memory_bytes=134217728,
 source_preparation='reconstruct_authenticated_training_only_transform_and_compare_archived_artifacts',
 published_commit=PUBLISHED_COMMIT,published_archive_sha256=PUBLISHED_ARCHIVE_SHA256,
 workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
 comparison_scope='saved_final_states_on_existing_training_and_exposed_development_sources',**FALSE)


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed scalar diagnostic plan differs')


def jobs():
    return [(dimension,seed,arm) for dimension in FIXED['dimensions']
        for seed in FIXED['seed_order'] for arm in ARMS]


def load_helper(root,pins,path,name):
    require(sha(root/path)==pins[path],'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted==expected),'unbound artifact alias: '+str(path))
    require(sha(path)==wanted,'sealed artifact differs: '+str(path))
    return json.loads(path.read_bytes())


def publication_entry(public,path):
    name=str(Path(path).resolve())
    member=public.get('original_artifact_archive_paths',{}).get(name)
    if member is not None:return public['members'][member]
    member=public.get('post_archive_artifact_paths',{}).get(name)
    if member is not None:return public['publication_support'][member]
    if name in public.get('referenced_artifacts',{}):return public['referenced_artifacts'][name]
    raise ValueError('artifact is absent from published evidence: '+name)


def published_json(manifest,public,path,expected=None):
    entry=publication_entry(public,path)
    require(Path(path).stat().st_size==entry['bytes'] and (expected is None or expected==entry['sha256']),
        'published artifact identity differs: '+str(path))
    return bound_json(manifest,path,entry['sha256'])


def authenticate_publication(args,manifest):
    require(manifest['published_commit']==PUBLISHED_COMMIT,'unregistered predecessor commit')
    repository=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=args.manifest.parent,text=True).strip())
    values=[]
    for key in ('publication_manifest','publication_results'):
        path=Path(manifest[key]).resolve();value=bound_json(manifest,path)
        blob=subprocess.check_output(['git','show',PUBLISHED_COMMIT+':'+str(path.relative_to(repository))],cwd=repository)
        require(hashlib.sha256(blob).hexdigest()==sha(path),'published Git metadata differs: '+key);values.append(value)
    public,results=values
    require(public['archive']==results['archive'] and public['archive']['sha256']==PUBLISHED_ARCHIVE_SHA256,
        'published archive identity differs')
    h=hashlib.sha256();offset=0
    for index,part in enumerate(public['archive_parts'],1):
        require(part['filename']=='evidence.tar.xz.part-'+str(index).zfill(3) and part['offset_bytes']==offset,
            'published archive part order differs')
        path=Path(manifest['publication_manifest']).parent/part['filename']
        require(path.stat().st_size==part['bytes'] and sha(path)==part['sha256'],'published archive part differs')
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1048576),b''):h.update(block);offset+=len(block)
    require(dict(sha256=h.hexdigest(),bytes=offset)==public['archive'],'published logical archive differs')
    return public


def load_observer_extensions(ctx,extension_root,pins):
    # The original package search path intentionally remains on the frozen
    # dependency tree. Explicitly load these extension-only dependencies in
    # order; adding the live package tree to __path__ would break provenance.
    for name in ('contextual_generated_boundary_training','generated_field_training',
                 'generated_scalar_observation'):
        ctx['owners'][name]=ctx['helpers'].extension(
            extension_root,AUTO+name+'.py',PREFIX+name,pins)
    return ctx['owners']['generated_scalar_observation']


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'sealed diagnostic inputs differ')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed: '+path)
    for path,wanted in manifest['extensions'].items():require(sha(args.extension_root/path)==wanted,'frozen extension differs: '+path)
    public=authenticate_publication(args,manifest)
    parent=published_json(manifest,public,manifest['parent_manifest'])
    parent_plan=published_json(manifest,public,manifest['parent_plan'])
    require(parent['plan_sha256']==sha(manifest['parent_plan']),'original parent plan binding differs')
    for path,wanted in parent['extensions'].items():
        require(manifest['extensions'].get(path)==wanted and public['validated_producer_source_sha256'][path]==wanted,
            'saved model producer changed: '+path)
    previous=load_helper(args.extension_root,parent['extensions'],
        'scripts/ops/autoencoder/benchmark_generated_replay_consistency.py','_scalar_previous_runner')
    previous.validate_plan(parent_plan)
    native=load_helper(args.extension_root,parent['extensions'],
        'scripts/ops/autoencoder/benchmark_native_dimension_source_training.py','_scalar_native_runner')
    # The retained native loader supplies original rows/targets and initializer.
    # Avoid loading six unnecessary predecessor training histories in the R4 loader.
    published_json(manifest,public,parent['parent_manifest']);published_json(manifest,public,parent['parent_plan'])
    oldargs=SimpleNamespace(**vars(args));oldargs.manifest=Path(parent['parent_manifest']);oldargs.plan=Path(parent['parent_plan'])
    ctx=native.load_context(oldargs);h=ctx['helpers']
    for name in ('action_factorized_clause_decoder_experiment','ordered_clause_recurrent_decoder_experiment'):
        ctx['owners'][name]=h.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,parent['extensions'])
    observer=load_observer_extensions(ctx,args.extension_root,manifest['extensions'])
    expected={f'{d}-{arm}-{seed}' for d,seed,arm in jobs()}
    require(set(manifest['saved_summaries'])==expected,'exact eighteen saved summaries required')
    ctx.update(plan=plan,manifest=manifest,pins=manifest['extensions'],public=public,
        native_runner=native,previous_runner=previous,observer=observer,parent_manifest=parent)
    return ctx


def generation_predictions(rows):
    require(type(rows) is list,'prediction list required')
    result=[]
    for row in rows:
        require(type(row) is dict and all(k in row for k in ('id','token_ids','generation_status','eos_reached')),
            'complete saved generation envelope required')
        result.append({k:deepcopy(row[k]) for k in ('id','token_ids','generation_status','eos_reached')})
    return result


def check_preparation(ctx,lane,folder):
    for name,value in [('preprocessing.json',lane['preparation']),('source-contexts.json',lane['source_contexts']),('training-rows.json',lane['rows'])]:
        expected=published_json(ctx['manifest'],ctx['public'],folder/name)
        require(value==expected,'reconstructed source preparation differs: '+name)


def restore_final(ctx,lane,run):
    require(run['budget_completed'] is True and run['dimension']==lane['dimension'] and run['seed'] in FIXED['seed_order'],
        'complete registered saved run required')
    recipes={r['name']:r for r in ctx['previous_runner'].ARMS}
    require(run['recipe']==recipes[run['recipe']['name']],'saved recipe differs')
    ref=run['states']['last-attempt'];state=published_json(ctx['manifest'],ctx['public'],ref['path'],ref['sha256'])
    require(state['schema']=='private-native-dimension-source-state/v1' and state['role']=='last-attempt'
        and state['dimension']==run['dimension'] and state['recipe']==run['recipe']
        and state['codec']==lane['donor']['codec'] and state['input_transform']==lane['donor']['input_transform']
        and state['weights_sha256']==ctx['core'].digest(state['model_state'])
        and state['tensor_sha256']==ref['tensor_sha256'],'saved state metadata or weights differ')
    model=ctx['previous_runner'].bind_candidate(lane,run['recipe'],run['seed'])
    require(model.describe()==state['architecture'],'saved decoder architecture differs')
    restored=ctx['clause_runner'].restored_tensors(lane,state['model_state'],model.state_dict())
    ctx['native_runner'].validate_wrapper_state(lane,restored);model.load_state_dict(restored,strict=True)
    require(ctx['core'].tensor_digest(model)==state['tensor_sha256'],'strict restored tensor digest differs')
    return model,state


def observe_panel(ctx,lane,model,split,scope,expected,deadline):
    require((split,scope) in [(a,b) for a,b,_ in SPLITS],'unregistered observation split')
    require(time.monotonic()<deadline,'diagnostic panel deadline exceeded')
    rows=lane['rows'][split];contexts=lane['source_contexts'][split]
    require(len(rows)==FIXED['samples_per_panel'],'exact archived panel coverage required')
    before=ctx['core'].tensor_digest(model);started=time.monotonic()
    sources=[{k:r[k] for k in ('id','input','source_text')} for r in rows]
    trace=ctx['observer'].collect_source_scalar_trace(model,sources,codec=lane['donor']['codec'],
        input_transform=lane['donor']['input_transform'],source_contexts=contexts,max_target_tokens=512,
        batch_size=8,deadline=deadline,max_memory_bytes=FIXED['max_trace_memory_bytes'])
    require(trace.get('complete') is True and trace.get('model_tensor_sha256')==before,
        'complete trace for this saved model required')
    require(ctx['core'].tensor_digest(model)==before,'observer changed saved model')
    require(generation_predictions(trace['predictions'])==generation_predictions(expected['predictions']),
        'observed generation differs from archived predictions')
    require(time.monotonic()<deadline,'diagnostic panel deadline exceeded before reference scoring')
    score=ctx['observer'].score_scalar_trace(trace,rows,lane['references'][split],split=scope,
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],source_contexts=contexts,
        validate_rule=lane['validate_rule'],deadline=deadline)
    require(ctx['core'].tensor_digest(model)==before,'posthoc scoring changed saved model')
    require(time.monotonic()<deadline,'diagnostic panel deadline exceeded after scoring')
    return dict(trace=trace,score=score,model_tensor_sha256=before,generation_predictions_exact=True,
        generation_parity_fields=['id','token_ids','generation_status','eos_reached'],
        reference_scoring_after_completed_collection=True,split=scope,sample_count=len(rows),
        elapsed_seconds=time.monotonic()-started,greedy_passes=1,optimizer_steps=0,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['diagnostic'],required=True);args=parser.parse_args()
    started=time.monotonic();deadline=started+FIXED['max_seconds_entire_run'];ctx=load_context(args)
    h=ctx['helpers'];before=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);args.output.mkdir(parents=True)
    h.save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    records=[];runs={name:published_json(ctx['manifest'],ctx['public'],path) for name,path in ctx['manifest']['saved_summaries'].items()}
    for dimension in FIXED['dimensions']:
        require(time.monotonic()<deadline,'entire diagnostic deadline exceeded')
        lane=ctx['native_runner'].prepare_dimension(ctx,dimension)
        first=Path(ctx['manifest']['saved_summaries'][f'{dimension}-{ARMS[0]}-{FIXED["seed_order"][0]}'])
        check_preparation(ctx,lane,first.parent.parent/str(dimension))
        for seed in FIXED['seed_order']:
            for arm in ARMS:
                name=f'{dimension}-{arm}-{seed}';run=runs[name]
                require(run['arm']==name and run['dimension']==dimension and run['seed']==seed,'saved run identity differs')
                model,state=restore_final(ctx,lane,run)
                for split,scope,label in SPLITS:
                    require(time.monotonic()<deadline,'entire diagnostic deadline exceeded')
                    ref=run['postfit']['last-attempt'][label]
                    expected=published_json(ctx['manifest'],ctx['public'],ref['path'],ref['sha256'])
                    result=observe_panel(ctx,lane,model,split,scope,expected,min(deadline,time.monotonic()+30))
                    trace_ref=h.save(args.output/name/('trace-'+scope+'.json'),result.pop('trace'))
                    score=result.pop('score');score_ref=h.save(args.output/name/('score-'+scope+'.json'),score)
                    entry=dict(result,arm=name,dimension=dimension,seed=seed,state_ref=run['states']['last-attempt'],
                        archived_panel_ref=ref,trace_ref=trace_ref,score_ref=score_ref,
                        per_field=score['per_field'],
                        scoring_scope='posthoc_only; training and exposed development kept separate')
                    index=h.save(args.output/name/('summary-'+scope+'.json'),entry);records.append(dict(entry,summary_ref=index))
                    print(json.dumps(dict(arm=name,split=scope,complete=True,elapsed_seconds=result['elapsed_seconds'])),flush=True)
                del model,state
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    for scoped,wanted in after.items():
        kind,relative=scoped.split(':',1)
        require(kind in ('dependency','extension'),'unknown loaded source scope')
        if relative in ctx['public']['validated_producer_source_sha256']:
            require(wanted==ctx['public']['validated_producer_source_sha256'][relative],'inherited loaded producer differs')
        else:require(kind=='extension' and ctx['pins'].get(relative)==wanted,'unsealed observation producer')
    for path,wanted in ctx['manifest']['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for path,wanted in ctx['pins'].items():require(sha(args.extension_root/path)==wanted,'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'] and time.monotonic()<deadline,'plan changed or entire deadline exceeded')
    require(len(records)==36,'incomplete diagnostic panel inventory')
    h.save(args.output/'summary.json',dict(schema='contextual-scalar-margin-diagnostic-results/v1',complete=True,
        panels=records,state_count=18,panel_count=36,source_dependencies=after,
        all_archived_generation_predictions_equal=True,all_saved_weights_preserved=True,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,inference_executed=True,source_encoder_executed=False,
        greedy_passes=36,optimizer_steps=0,no_new_validation_targets=True,**FALSE))


if __name__=='__main__':main()
