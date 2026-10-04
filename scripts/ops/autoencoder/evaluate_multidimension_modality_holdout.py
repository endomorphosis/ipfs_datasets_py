#!/usr/bin/env python3
"""Postfit-only evaluation of six cached-input fits on exposed R6 paragraphs.

All twelve source-only predictions are saved before reference JSON is opened.
This cohort was used in earlier experiments and is not a fresh holdout.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

TRAINING_RUNNER='scripts/ops/autoencoder/benchmark_multidimension_modality_training.py'
ARMS=['source-head-lr10','aux-used113']
ROLES=['selected','last-attempt']
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,fresh_authored_holdout=False,
    lake_executed=False,native_validation_executed=False,formalized=False,roundtrip_ok=False)
FIXED=dict(schema='multidimension-modality-exposed-evaluation-plan/v1',dimensions=[8,384,768],seed_order=[1729],
    arms=ARMS,roles=ROLES,panel_count=12,rows_per_panel=48,source_clause_occurrences_per_panel=180,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,
    all_predictions_before_reference_load=True,greedy_passes_per_row=1,source_only_generation=True,
    teacher_forced_full_vocabulary_size=32,teacher_forced_reference_prefixes=True,greedy_repeated_for_scoring=False,
    historical_linguistic_teacher_modified=False,training_executed=False,encoder_executed=False,
    used_for_selection=False,previously_exposed=True,fresh_holdout=False,transforms_fitted_on_evaluation=False,
    saved_training_preprocessing_exact=True,max_seconds_per_panel=30,max_seconds_entire_run=600,
    workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,no_downloads=True)


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or expected==wanted),'unbound artifact: '+str(path))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==wanted,'sealed artifact differs: '+str(path))
    return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed exposed evaluation differs')


def jobs():
    return [(d,1729,a) for d in FIXED['dimensions'] for a in ARMS]


def validate_saved_runs(manifest,summary):
    expected=[f'{d}-{arm}-{seed}' for d,seed,arm in jobs()]
    require(summary.get('schema')=='multidimension-modality-training-comparison/v1' and summary.get('complete') is True
        and summary.get('phase')=='training' and summary.get('training_executed') is True
        and summary.get('dimensions_actually_trained')==[8,384,768]
        and summary.get('all_three_original_baselines_replayed') is True,'complete three-width training required')
    records=summary.get('runs');require(type(records) is list and [r.get('arm') for r in records]==expected
        and set(manifest['saved_summaries'])==set(expected),'exact six saved runs required')
    runs={}
    for record,(dimension,seed,arm) in zip(records,jobs()):
        name=record['arm'];require(Path(record['summary_path']).resolve()==Path(manifest['saved_summaries'][name]).resolve(),'saved summary alias differs')
        run=bound_json(manifest,record['summary_path'],record['summary_sha256'])
        require(run.get('arm')==name and run.get('dimension')==dimension and run.get('seed')==seed
            and run.get('recipe',{}).get('name')==arm and run.get('budget_completed') is True,'saved run identity differs')
        training=bound_json(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
        require(training.get('stopped_reason')=='epochs_completed' and training.get('optimizer_steps')==340,'incomplete fit cannot enter postfit comparison')
        for role in ROLES:
            ref=run['states'][role]
            require(manifest['inputs'].get(str(Path(ref['path']).resolve()))==ref['sha256'] and sha(ref['path'])==ref['sha256'],'saved state is unbound')
        runs[name]=run
    return runs


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'evaluation seal differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input differs')
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'evaluator source differs')
    parent=bound_json(manifest,manifest['training_manifest']);bound_json(manifest,manifest['training_plan'])
    require(sha(manifest['training_plan'])==parent['plan_sha256'],'training plan differs')
    root=Path(manifest['training_extension_root']);path=root/TRAINING_RUNNER
    for relative,wanted in parent['extensions'].items():require(sha(root/relative)==wanted,'training runner source differs')
    spec=importlib.util.spec_from_file_location('_exposed_multidimension_training_runner',path)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    previous=SimpleNamespace(**vars(args));previous.manifest=Path(manifest['training_manifest'])
    previous.plan=Path(manifest['training_plan']);previous.extension_root=root
    original=runner.load_context(previous)
    require(all(Path(manifest[key]).resolve()==Path(original['manifest'][old]).resolve() for key,old in
        [('source_inputs','exposed_source_inputs'),('references','exposed_references'),('holdout_receipt','exposed_holdout_receipt')]),
        'evaluation must use the exact previously exposed R6 artifacts')
    require(manifest['comparison_seal']==original['parent_manifest']['plan_sha256'],'original R6 comparison seal differs')
    require(len({str(Path(manifest[k]).resolve()) for k in ('source_inputs','references','holdout_receipt')})==3,'source and labels must remain separate')
    source=bound_json(manifest,manifest['source_inputs']);original['exposed_evaluator']._source_only(source)
    require(source.get('schema')=='fresh-scalar-source-inputs/v1' and source.get('complete') is True
        and set(source.get('dimensions',{}))=={'8','384','768'} and source.get('inputs_sha256')==original['core'].digest(
            {k:v for k,v in source.items() if k!='inputs_sha256'}),'complete source-only cache required')
    order=[[{k:r[k] for k in ('id','source_text')} for r in source['dimensions'][str(d)]['rows']] for d in FIXED['dimensions']]
    require(order[0]==order[1]==order[2],'exposed source order differs across widths')
    runs=validate_saved_runs(manifest,bound_json(manifest,manifest['training_summary']))
    ctx=dict(original,manifest=manifest,plan=plan,training_runner=runner,saved_runs=runs,fresh_inputs=source,
        original_context=original,evaluation_extensions=manifest['extensions'])
    return ctx


def load_exposed_references(ctx,records):
    expected={(f'{d}-{a}-{s}',role) for d,s,a in jobs() for role in ROLES}
    require(type(records) is list and len(records)==12 and {(r['arm'],r['role']) for r in records}==expected,
        'all12 predictions required before reference load')
    rows=ctx['fresh_inputs']['dimensions']['8']['rows'];identities=[r['id'] for r in rows]
    for record in records:
        ref=record['predictions_ref'];raw=Path(ref['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'persisted exposed prediction changed')
        value=json.loads(raw)
        require(value.get('complete') is True and [r.get('id') for r in value.get('predictions',[])]==identities
            and value.get('model_tensor_sha256')==record['state_ref']['tensor_sha256']
            and value.get('generation_reference_access') is False and value.get('greedy_passes_per_row')==1,
            'incomplete source-only prediction')
    manifest=ctx['manifest'];refs=bound_json(manifest,manifest['references']);receipt=bound_json(manifest,manifest['holdout_receipt']);digest=ctx['core'].digest
    require(type(refs) is list and len(refs)==48 and receipt.get('complete') is True
        and receipt.get('schema')=='authored-scalar-holdout/v1'
        and receipt.get('receipt_sha256')==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        and receipt.get('references_sha256')==digest(refs)
        and receipt.get('source_rows_sha256')==digest([{k:r[k] for k in ('id','source_text')} for r in rows])
        and receipt.get('sealed_comparison_sha256')==manifest['comparison_seal']
        and receipt.get('codec_sha256')==digest(ctx['donor']['codec']),'original R6 reference authentication differs')
    require([r['id'] for r in refs]==identities,'exposed reference identities differ')
    vocabulary=ctx['donor']['codec']['target_vocabulary'];require(len(vocabulary)==32,'unchanged full vocabulary required')
    for reference,source in zip(refs,rows):
        ids=reference['target_ids']
        require(reference['source_text']==source['source_text'] and reference['source_sha256']==hashlib.sha256(source['source_text'].encode()).hexdigest()
            and reference.get('split')=='fresh_authored_holdout' and reference.get('codec_sha256')==digest(ctx['donor']['codec'])
            and reference.get('target_sha256')==digest(reference['target']),'original reference provenance differs')
        require(type(ids) is list and 3<=len(ids)<=512 and ids[0]==1 and ids[-1]==2
            and all(type(t) is int and 3<=t<32 for t in ids[1:-1])
            and json.loads(''.join(vocabulary[t] for t in ids[1:-1]))==reference['target'],'complete unchanged targets required')
    return refs,receipt


def execute(args):
    started=time.monotonic();deadline=started+FIXED['max_seconds_entire_run'];ctx=load_context(args)
    original=ctx['original_context'];owner=ctx['exposed_evaluator'];save=ctx['helpers'].save
    inventory=lambda:original['comparison_owner'].source_inventory(original['comparison_parent_args'],original)
    before=inventory();args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(manifest=ctx['manifest'],plan=ctx['plan'],**FALSE))
    records=[]
    for dimension in FIXED['dimensions']:
        lane=owner.prepare_lane(ctx,dimension)
        for arm in ARMS:
            run=ctx['saved_runs'][f'{dimension}-{arm}-1729']
            for role in ROLES:
                require(time.monotonic()<deadline,'evaluation deadline exceeded')
                model,state=owner.restore_state(ctx,lane,run,role)
                panel=owner.generate_panel(ctx,lane,model,min(deadline,time.monotonic()+30))
                panel.update(schema='multidimension-modality-exposed-predictions/v1',previously_exposed=True,used_for_selection=False,**FALSE)
                ref=save(args.output/run['arm']/(role+'-predictions.json'),panel)
                records.append(dict(arm=run['arm'],dimension=dimension,seed=1729,role=role,state_ref=run['states'][role],
                    predictions_ref=ref,generation_seconds=panel['elapsed_seconds']))
                del model,state,panel
    save(args.output/'predictions-complete.json',dict(complete=True,panels=records,reference_json_loaded=False,
        all_predictions_persisted_before_reference_load=True,previously_exposed=True,**FALSE))
    refs,receipt=load_exposed_references(ctx,records);results=[]
    for dimension in FIXED['dimensions']:
        lane=owner.prepare_lane(ctx,dimension)
        for record in [r for r in records if r['dimension']==dimension]:
            require(time.monotonic()<deadline,'evaluation deadline exceeded')
            run=ctx['saved_runs'][record['arm']];model,state=owner.restore_state(ctx,lane,run,record['role'])
            ref=record['predictions_ref'];raw=Path(ref['path']).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'saved prediction changed before scoring')
            prediction=json.loads(raw)
            score=owner.score_panel(ctx,lane,model,prediction,refs,
                min(deadline,time.monotonic()+30-record['generation_seconds']))
            score.update(schema='multidimension-modality-exposed-score/v1',previously_exposed=True,used_for_selection=False,**FALSE)
            score_ref=save(args.output/record['arm']/(record['role']+'-score.json'),score)
            results.append(dict(record,score_ref=score_ref,scoring_seconds=score['elapsed_seconds'],
                ordered_exact=score['fidelity']['metrics']['ordered_exact'],syntax_valid=score['fidelity']['metrics']['syntax_valid'],
                teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
            del model,state,prediction,score
    after=inventory();require(all(after.get(k)==v for k,v in before.items()),'loaded source changed')
    for path,wanted in ctx['manifest']['inputs'].items():require(sha(path)==wanted,'sealed evaluation input changed')
    for relative,wanted in ctx['evaluation_extensions'].items():require(sha(args.extension_root/relative)==wanted,'evaluator source changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'] and time.monotonic()<deadline,'plan changed or deadline exceeded')
    summary=dict(schema='multidimension-modality-exposed-evaluation/v1',complete=len(results)==12,panels=results,
        references_sha256=ctx['core'].digest(refs),original_holdout_receipt_sha256=ctx['core'].digest(receipt),
        all_predictions_persisted_before_reference_load=True,encoder_executed=False,training_executed=False,
        downloads_performed=False,previously_exposed=True,used_for_selection=False,source_dependencies=after,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,**FALSE)
    save(args.output/'summary.json',summary);return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['evaluation'],required=True)
    execute(parser.parse_args())


if __name__=='__main__':main()
