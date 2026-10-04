#!/usr/bin/env python3
"""Prepare and once-score new authored styles on two preselected saved decoders."""
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
PARENT_RUNNER='scripts/ops/autoencoder/benchmark_formula_checkpoint_continuation.py'
BUILDER=AUTO+'authored_modality_holdout_v3.py'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,formalized=False,roundtrip_ok=False,
    checkpoint_promoted=False,convergence_proven=False,lake_executed=False,native_validation_executed=False,
    source_semantics_verified=False,training_executed=False,selection_performed=False,downloads_performed=False,
    historical_linguistic_teacher_modified=False)
ENDPOINTS={str(d):dict(run=f'{d}-continue-lr001-1729',role='selected') for d in (384,768)}
FIXED=dict(schema='fresh-normative-style-observation-plan/v1',dimensions=[384,768],endpoints=ENDPOINTS,
    samples=48,clause_occurrences=180,unique_sources=216,seed=20261006,encoder_batch_size=4,generation_batch_size=8,
    context_tokens=512,max_target_tokens=512,temperature=0,vocabulary_size=32,
    new_templates=['actor_normative_status','norm_noun_subject','gerund_normative_subject'],
    models_selected_before_source_generation=True,source_only_generation=True,greedy_passes_per_model=1,
    all_predictions_before_reference_load=True,holdout_used_for_selection=False,preprocessing_refitted=False,
    distribution='authored_normative_paraphrases_with_fixed_lexicon;not_statutory_evidence',
    max_seconds_preparation=1400,max_seconds_encoder=600,max_seconds_evaluation=300,**FALSE)

def require(value,message):
    if not value:raise ValueError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path));require(wanted is not None and(expected is None or expected==wanted),'unbound input: '+str(path))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==wanted,'changed input: '+str(path));return json.loads(raw)

def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),'fresh observation recipe differs')

def source_inventory(args,manifest):
    allowed=dict(manifest['producer_pins']);allowed.update({str((args.extension_root/r).resolve()):h for r,h in manifest['extensions'].items()})
    result={}
    for name,module in list(sys.modules.items()):
        if name!='ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):continue
        path=getattr(module,'__file__',None)
        if path:
            path=str(Path(path).resolve());actual=sha(path)
            require(allowed.get(path)==actual,'unknown or changed producer: '+path);result[path]=actual
    return result

def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'fresh seal differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'owned source changed')
    root=Path(manifest['parent_extension_root']);parent=bound_json(manifest,manifest['parent_manifest']);bound_json(manifest,manifest['parent_plan'])
    require(sha(root/PARENT_RUNNER)==parent['extensions'][PARENT_RUNNER],'parent runner changed')
    spec=importlib.util.spec_from_file_location('_fresh_normative_parent',root/PARENT_RUNNER);owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args));previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan']);previous.extension_root=root
    ctx=owner.load_context(previous);ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    runs={}
    for width,choice in ENDPOINTS.items():
        run=bound_json(manifest,manifest['saved_summaries'][width]);require(run['arm']==choice['run'] and run['dimension']==int(width) and run['budget_completed'] is True,'preselected endpoint differs')
        ref=run['states']['selected'];require(sha(ref['path'])==ref['sha256'] and manifest['inputs'].get(str(Path(ref['path']).resolve()))==ref['sha256'],'unbound preselected state')
        runs[width]=run
    ctx.update(fresh_manifest=manifest,fresh_plan=plan,fresh_parent=owner,fresh_runs=runs,
        fresh_manifest_sha256=sha(args.manifest),fresh_plan_sha256=sha(args.plan))
    source_inventory(args,manifest);return ctx

def load_producers(args,ctx):
    manifest=ctx['fresh_manifest'];h=ctx['helpers'];owners={};package=sys.modules[PREFIX[:-1]]
    for name in ('authored_scalar_holdout','gte_multilingual_profile','source_embeddings_768',
                 'source_embeddings_768_complete','dimension_source_inputs','legal_native_conditioning',
                 'fresh_scalar_source_inputs','fresh_scalar_source_inputs_single'):
        ref=manifest['helpers'][name];path=Path(ref['path']);canonical=PREFIX+name
        require(sha(path)==ref['sha256'],'prepared source helper changed')
        if canonical in sys.modules:
            module=sys.modules[canonical];require(sha(module.__file__)==ref['sha256'],'different already-imported helper')
        else:
            module=h.extension(path.parents[4],str(path.relative_to(path.parents[4])),canonical,{str(path.relative_to(path.parents[4])):ref['sha256']})
        setattr(package,name,module);owners[name]=module
    # The verified384 producer is not part of the older S snapshot.
    ref=manifest['helpers']['autoencoder_embedding_runtime'];canonical='ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime'
    if canonical not in sys.modules:
        path=Path(ref['path']);spec=importlib.util.spec_from_file_location(canonical,path);module=importlib.util.module_from_spec(spec)
        require(sha(path)==ref['sha256'],'embedding runtime changed');sys.modules[canonical]=module;spec.loader.exec_module(module)
    else:require(sha(sys.modules[canonical].__file__)==ref['sha256'],'different embedding runtime')
    builder=h.extension(args.extension_root,BUILDER,PREFIX+'authored_modality_holdout_v3',manifest['extensions']);owners['builder']=builder
    source_inventory(args,manifest);return owners

def prior_inventory(manifest):
    require(set(manifest['prior_sources'])=={'raw_train','raw_validation','raw_test','raw_canary','paragraph_train','paragraph_validation','exposed_r6','exposed_r8'},'complete known prior inventories required')
    result={}
    for name,descriptor in manifest['prior_sources'].items():
        require(set(descriptor)=={'path','keys'},'closed source descriptor required');rows=bound_json(manifest,descriptor['path'])
        for key in descriptor['keys']:rows=rows[key]
        require(type(rows) is list and rows,'prior inventory empty')
        result[name]=[{k:r[k] for k in ('id','source_text')} for r in rows]
    return result

def produce_or_reuse(producer,plan,dimension,assets,output,manifest):
    prior=manifest.get('completed_384_production')
    if dimension==384 and prior is not None:
        require(type(prior) is dict and set(prior)=={'path','sha256'},'closed completed384 source report required')
        report=bound_json(manifest,prior['path'],prior['sha256'])
        require(producer._validate_report(producer._plan(plan),report)==384,'completed384 report/source plan differs')
        # Preserve the original native observation and source artifact identities;
        # this is a validated retained vector cache, never a new encoder forward.
        return report
    return producer.produce_width(plan,dimension=dimension,asset_config=assets[str(dimension)],
        source_artifact_directory=output/f'source{dimension}-artifacts' if dimension==384 else None,
        batch_size=4,max_seconds=600)


def prepare(args,ctx):
    owners=load_producers(args,ctx);manifest=ctx['fresh_manifest'];h=ctx['helpers'];parent=bound_json(manifest,manifest['training_paragraphs'])
    training=[{k:r[k] for k in ('id','source_text','target')} for r in parent['train']]
    actual={r['id']:r['target'] for r in ctx['references']['train']}
    require(training==[dict(id=r['id'],source_text=r['source_text'],target=actual[r['id']]) for r in ctx['rows']['train']],'training pair strata differ')
    cohort=owners['builder'].build_holdout(training_rows=training,prior_sources_by_dataset=prior_inventory(manifest),family_roles=ctx['fresh_plan']['family_roles'],
        codec=ctx['donor']['codec'],sealed_comparison_sha256=manifest['comparison_seal'],seed=FIXED['seed'],validate_rule=ctx['validate_rule'])
    source_ref=h.save(args.output/'source-rows.json',cohort['source_rows']);reference_ref=h.save(args.output/'references.json',cohort['references'])
    receipt_ref=h.save(args.output/'holdout-receipt.json',cohort['receipt']);producer=owners['fresh_scalar_source_inputs']
    plan=producer.source_plan(cohort['source_rows'],expected_source_rows_sha256=cohort['receipt']['source_rows_sha256'],sealed_comparison_sha256=manifest['comparison_seal'])
    h.save(args.output/'source-plan.json',plan);assets=bound_json(manifest,manifest['asset_config']);outputs={}
    for dimension in FIXED['dimensions']:
        report=produce_or_reuse(producer,plan,dimension,assets,args.output,manifest)
        production=h.save(args.output/f'production-{dimension}.json',report)
        inputs=owners['fresh_scalar_source_inputs_single'].assemble(plan,report,dimension=dimension)
        outputs[str(dimension)]=dict(native_forward_executed_in_this_attempt=not(dimension==384 and manifest.get('completed_384_production') is not None),source_inputs=h.save(args.output/f'dimension-inputs-{dimension}.json',inputs),production=production)
        print(json.dumps(dict(dimension=dimension,source_rows=48,unique_sources=216,complete=True)),flush=True)
    return dict(dimensions=outputs,source_rows=source_ref,references=reference_ref,holdout_receipt=receipt_ref,encoder_executed=True)

def prepare_lane(ctx,dimension):
    lane=ctx['native_runner'].prepare_dimension(ctx,dimension);manifest=ctx['fresh_manifest']
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        require(bound_json(manifest,Path(manifest['saved_results'])/str(dimension)/(name+'.json'))==value,'saved normalizer/cohort changed')
    data=bound_json(manifest,manifest['source_inputs'][str(dimension)]);core=ctx['core']
    require(data['schema']=='fresh-scalar-source-inputs-single/v1' and data['complete'] is True and data['dimension']==dimension
        and data['inputs_sha256']==core.digest({k:v for k,v in data.items() if k!='inputs_sha256'}),'fresh source cache differs')
    rows=data['rows'];require(len(rows)==48 and all(set(r)=={'id','source_text','input'} for r in rows),'closed fresh source rows required')
    owner=ctx['owners']['clause_source_context'];contexts=owner.build_source_contexts([{k:r[k] for k in ('id','source_text')} for r in rows],data['clause_cache'])
    require(contexts==data['source_contexts'] and owner.validate_contexts(rows,contexts)['dimension']==dimension,'fresh source contexts differ')
    lane.update(fresh_rows=rows,fresh_contexts=contexts,continuation_manifest=manifest);return lane

def load_references(ctx,records):
    require(len(records)==2 and {r['dimension'] for r in records}=={384,768},'both complete predictions required before fresh labels')
    for r in records:
        ref=r['predictions_ref'];require(sha(ref['path'])==ref['sha256'],'persisted source-only prediction changed')
        p=json.loads(Path(ref['path']).read_bytes());require(p['complete'] is True and p['generation_reference_access'] is False and p['model_tensor_sha256']==r['state_ref']['tensor_sha256'],'incomplete source prediction')
    manifest=ctx['fresh_manifest'];refs=bound_json(manifest,manifest['references']);receipt=bound_json(manifest,manifest['holdout_receipt']);digest=ctx['core'].digest
    require(receipt['schema']=='authored-modality-holdout/v3' and receipt['complete'] is True and len(refs)==48
        and receipt['references_sha256']==digest(refs) and receipt['receipt_sha256']==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        and receipt['sealed_comparison_sha256']==manifest['comparison_seal'],'fresh references not authenticated')
    require(receipt['codec_sha256']==digest(ctx['donor']['codec']),'reference codec differs')
    for r in refs:
        ids=r['target_ids'];require(ids[0]==1 and ids[-1]==2 and len(ids)<=512 and all(type(t) is int and 3<=t<32 for t in ids[1:-1])
            and json.loads(''.join(ctx['donor']['codec']['target_vocabulary'][t] for t in ids[1:-1]))==r['target'],'complete32V references required')
    return refs,receipt

def evaluate(args,ctx):
    h=ctx['helpers'];owner=ctx['exposed_evaluator'];records=[]
    for dimension in FIXED['dimensions']:
        lane=prepare_lane(ctx,dimension);run=ctx['fresh_runs'][str(dimension)];ref=run['states']['selected']
        model=ctx['fresh_parent'].restore_model(lane,ref,run['recipe'],'selected')
        panel=owner.generate_panel(ctx,lane,model,time.monotonic()+30);panel.update(distribution=FIXED['distribution'],used_for_selection=False)
        record=dict(dimension=dimension,run=run['arm'],role='selected',state_ref=ref,predictions_ref=h.save(args.output/f'{dimension}-predictions.json',panel))
        records.append(record);del model,panel
    h.save(args.output/'predictions-complete.json',dict(complete=True,panels=records,reference_json_loaded=False,**FALSE))
    refs,receipt=load_references(ctx,records);scores=[]
    for record in records:
        dimension=record['dimension'];lane=prepare_lane(ctx,dimension);run=ctx['fresh_runs'][str(dimension)]
        require(receipt['source_rows_sha256']==ctx['core'].digest([{k:r[k] for k in ('id','source_text')} for r in lane['fresh_rows']]),'source/reference alignment differs')
        model=ctx['fresh_parent'].restore_model(lane,record['state_ref'],run['recipe'],'selected')
        prediction=json.loads(Path(record['predictions_ref']['path']).read_bytes())
        score=owner.score_panel(ctx,lane,model,prediction,refs,time.monotonic()+30)
        scores.append(dict(record,score_ref=h.save(args.output/f'{dimension}-score.json',score),ordered_exact=score['fidelity']['metrics']['ordered_exact'],
            syntax_valid=score['fidelity']['metrics']['syntax_valid'],teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
        del model,score
    return dict(panels=scores,encoder_executed=False,fresh_source_distribution=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--phase',choices=['preparation','evaluation'],required=True);args=p.parse_args();started=time.monotonic();ctx=load_context(args)
    args.output.mkdir(parents=True);h=ctx['helpers'];h.save(args.output/'sealed-recipe.json',dict(manifest=ctx['fresh_manifest'],plan=ctx['fresh_plan']))
    result=prepare(args,ctx) if args.phase=='preparation' else evaluate(args,ctx)
    manifest=ctx['fresh_manifest']
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'input changed during phase')
    for rel,wanted in manifest['extensions'].items():require(sha(args.extension_root/rel)==wanted,'owned source changed during phase')
    require(sha(args.manifest)==ctx['fresh_manifest_sha256'] and sha(args.plan)==ctx['fresh_plan_sha256'],'seal changed during phase')
    require(time.monotonic()-started<FIXED['max_seconds_'+args.phase],'phase deadline exceeded')
    h.save(args.output/'summary.json',dict(schema='fresh-normative-style-observation/v1',complete=True,phase=args.phase,
        elapsed_seconds=time.monotonic()-started,source_dependencies=source_inventory(args,manifest),**result,**FALSE))
if __name__=='__main__':main()
