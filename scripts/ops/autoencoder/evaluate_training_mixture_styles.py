#!/usr/bin/env python3
"""Postfit regression on the already exposed v3 wording cohort, without selection.

All eight saved endpoints generate from authenticated source-only caches before
this observer parses the v3 references. Inherited setup reads older metadata;
this is not a claim that the process has never read any evaluation reference.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

TRAINER = 'scripts/ops/autoencoder/benchmark_training_paraphrase_mixture.py'
ARMS = ('original-only', 'half-paraphrases')
ROLES = ('selected', 'last-attempt')
FALSE = dict(qualified=False, admitted=False, proof_authority=False, formalized=False,
    roundtrip_ok=False, checkpoint_promoted=False, convergence_proven=False,
    lake_executed=False, fresh_holdout=False, source_semantics_verified=False,
    encoder_executed=False, training_executed=False, downloads_performed=False,
    used_for_selection=False)
FIXED = dict(schema='training-mixture-exposed-v3-plan/v1', dimensions=[384,768],
    arms=list(ARMS), roles=list(ROLES), panel_count=8, samples_per_panel=48,
    seed=1729, previously_exposed=True, all_predictions_before_reference_load=True,
    greedy_passes_per_model=1, context_tokens=512, output_tokens=512,
    temperature=0, vocabulary_size=32, batch_size=8, workers=1,
    max_seconds_per_panel=30, max_seconds_entire_run=600,
    distribution='previously_exposed_authored_modality_holdout_v3',
    comparison_seal='4e09fd75f40e410d1a53f7f13d01c034c1b0bcae5254a5f7f195754d7db16eac',
    bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
    cache_scope='warm authenticated source vectors; no encoder forward', **FALSE)


def require(value,message):
    if not value: raise ValueError(message)


def check_deadline(deadline):
    if time.monotonic()>=deadline:raise TimeoutError('shared style observation deadline')


def restore_before_deadline(owner,lane,run,role,deadline):
    check_deadline(deadline)
    model=owner.restore_endpoint(lane,run,role)
    check_deadline(deadline)
    return model


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def bound(manifest,path):
    path=Path(path).resolve();raw=path.read_bytes()
    require(manifest['inputs'].get(str(path))==hashlib.sha256(raw).hexdigest(),'unbound or changed observer input')
    return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and plan[k]==v
        for k,v in FIXED.items()),'fixed exposed-v3 observer recipe differs')


def verify_predictions(records, runs, lanes, digest):
    expected={(d,a,r) for d in FIXED['dimensions'] for a in ARMS for r in ROLES}
    require(type(records) is list and len(records)==8 and
        {(r['dimension'],r['arm'],r['role']) for r in records}==expected,
        'all eight durable endpoint predictions required before v3 references')
    for record in records:
        lane=lanes[record['dimension']];run=runs[(record['dimension'],record['arm'])]
        ref=record['predictions_ref'];raw=Path(ref['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'persisted v3 prediction changed')
        panel=json.loads(raw)
        require(record['state_ref']==run['states'][record['role']] and panel.get('complete') is True
            and panel.get('model_tensor_sha256')==record['state_ref']['tensor_sha256']
            and panel.get('source_rows_sha256')==digest(lane['fresh_rows'])
            and panel.get('source_contexts_sha256')==digest(lane['fresh_contexts'])
            and [r['id'] for r in panel.get('predictions',[])]==[r['id'] for r in lane['fresh_rows']]
            and panel.get('generation_reference_access') is False and panel.get('greedy_passes_per_row')==1
            and panel.get('generation_temperature')==0 and panel.get('max_target_tokens')==512,
            'incomplete or mismatched source-only v3 predictions')


def load_references(manifest, records, runs, lanes, codec, digest):
    verify_predictions(records,runs,lanes,digest)
    refs=bound(manifest,manifest['references']);receipt=bound(manifest,manifest['holdout_receipt'])
    source=[{k:r[k] for k in ('id','source_text')} for r in lanes[384]['fresh_rows']]
    require(source==[{k:r[k] for k in ('id','source_text')} for r in lanes[768]['fresh_rows']],
        'v3 source ordering differs by width')
    require(type(refs) is list and len(refs)==48 and len(codec['target_vocabulary'])==32
        and receipt.get('complete') is True and receipt.get('schema')=='authored-modality-holdout/v3'
        and receipt.get('receipt_sha256')==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        and receipt.get('references_sha256')==digest(refs) and receipt.get('source_rows_sha256')==digest(source)
        and receipt.get('codec_sha256')==digest(codec) and receipt.get('sealed_comparison_sha256')==FIXED['comparison_seal'],
        'authenticated v3 reference receipt required')
    for ref,row in zip(refs,source):
        ids=ref['target_ids']
        require(ref['id']==row['id'] and ref['source_text']==row['source_text']
            and ref['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest()
            and ref['target_sha256']==digest(ref['target']) and ref['codec_sha256']==digest(codec)
            and type(ids) is list and 3<=len(ids)<=512 and ids[0]==1 and ids[-1]==2
            and all(type(t) is int and 3<=t<32 for t in ids[1:-1])
            and json.loads(''.join(codec['target_vocabulary'][t] for t in ids[1:-1]))==ref['target'],
            'complete unchanged v3 source/target binding required')
    return refs,receipt


def execute(args):
    started=time.monotonic();deadline=started+FIXED['max_seconds_entire_run']
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    manifest_sha=sha(args.manifest)
    require(plan['input_sha256']==manifest['inputs'],'observer input seal differs')
    def recheck():
        require(time.monotonic()<deadline and sha(args.manifest)==manifest_sha
            and sha(args.plan)==manifest['plan_sha256'],'observer deadline or seal differs')
        for path,wanted in manifest['inputs'].items():
            check_deadline(deadline);require(sha(path)==wanted,'sealed observer input changed')
        for name,wanted in manifest['extensions'].items():
            check_deadline(deadline);require(sha(args.extension_root/name)==wanted,'frozen observer source changed')
        require(time.monotonic()<deadline,'observer deadline exceeded')
    recheck();require(not args.output.exists(),'fresh observer output required')
    parent=bound(manifest,manifest['training_manifest']);root=Path(manifest['training_extension_root'])
    require(sha(root/TRAINER)==parent['extensions'][TRAINER],'frozen training runner differs')
    spec=importlib.util.spec_from_file_location('_style_mixture_runner',root/TRAINER)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    previous=SimpleNamespace(**vars(args));previous.manifest=Path(manifest['training_manifest'])
    previous.plan=Path(manifest['training_plan']);previous.extension_root=root;previous.dimension=384
    ctx=runner.load_context(previous,deadline);before=runner.source_inventory(previous,ctx)
    runs={}
    for d in FIXED['dimensions']:
        terminal=manifest['training_terminals'][str(d)]
        require(bound(manifest,terminal['child_exit'])['returncode']==0
            and bound(manifest,terminal['resources_final'])['status']=='released','completed released training required')
        summary=bound(manifest,manifest['training_summaries'][str(d)])
        require(summary['complete'] is True and summary['phase']=='training' and summary['dimension']==d
            and len(summary['runs'])==2 and {r['arm'] for r in summary['runs']}==set(ARMS),'both complete arms required')
        for item in summary['runs']:
            run=bound(manifest,item['summary_path'])
            require(sha(item['summary_path'])==item['summary_sha256'] and run['dimension']==d
                and run['arm']==item['arm'] and run['budget_completed'] is True and run['seed']==1729
                and all(run[k] is False for k in ('qualified','admitted','checkpoint_promoted')),'training endpoint identity differs')
            for role in ROLES:
                ref=run['states'][role];require(manifest['inputs'].get(str(Path(ref['path']).resolve()))==ref['sha256'],
                    'endpoint must be bound before generation')
            runs[d,run['arm']]=run
    lanes={}
    for d in FIXED['dimensions']:
        check_deadline(deadline)
        lane=ctx['mixture_owner'].prepare_lane(ctx,d);lane['continuation_manifest']=manifest
        data=bound(manifest,manifest['source_inputs'][str(d)]);digest=ctx['core'].digest
        require(data['schema']=='fresh-scalar-source-inputs-single/v1' and data['complete'] is True
            and data['dimension']==d and data['inputs_sha256']==digest({k:v for k,v in data.items() if k!='inputs_sha256'}),
            'authenticated v3 source-only cache required')
        rows=data['rows'];require(len(rows)==48 and all(set(r)=={'id','source_text','input'} for r in rows),'closed v3 rows required')
        for row in rows:ctx['core']._vector(row['input'],d)
        owner=ctx['owners']['clause_source_context'];contexts=owner.build_source_contexts(
            [{k:r[k] for k in ('id','source_text')} for r in rows],data['clause_cache'])
        require(contexts==data['source_contexts'] and owner.validate_contexts(rows,contexts)['dimension']==d,'v3 contexts differ')
        lane.update(fresh_rows=rows,fresh_contexts=contexts);lanes[d]=lane
    args.output.mkdir(parents=True);save=ctx['helpers'].save;owner=ctx['exposed_evaluator'];records=[]
    save(args.output/'sealed-recipe.json',dict(manifest=manifest,plan=plan,**FALSE))
    for d in FIXED['dimensions']:
        for arm in ARMS:
            for role in ROLES:
                lane=lanes[d];run=runs[d,arm]
                model=restore_before_deadline(ctx['mixture_owner'],lane,run,role,deadline)
                panel=owner.generate_panel(ctx,lane,model,min(deadline,time.monotonic()+30))
                panel.update(previously_exposed=True,used_for_selection=False,fresh_holdout=False)
                ref=save(args.output/f'{d}-{arm}'/(role+'-predictions.json'),panel)
                check_deadline(deadline)
                records.append(dict(dimension=d,arm=arm,role=role,state_ref=run['states'][role],predictions_ref=ref,
                    generation_seconds=panel['elapsed_seconds']))
                del model,panel
    save(args.output/'predictions-complete.json',dict(complete=True,records=records,v3_reference_json_loaded=False,**FALSE))
    refs,receipt=load_references(manifest,records,runs,lanes,ctx['donor']['codec'],ctx['core'].digest)
    results=[]
    for record in records:
        lane=lanes[record['dimension']];run=runs[record['dimension'],record['arm']]
        model=restore_before_deadline(ctx['mixture_owner'],lane,run,record['role'],deadline)
        ref=record['predictions_ref'];require(sha(ref['path'])==ref['sha256'],'saved v3 prediction changed before scoring')
        prediction=json.loads(Path(ref['path']).read_bytes())
        score=owner.score_panel(ctx,lane,model,prediction,refs,min(deadline,time.monotonic()+30-record['generation_seconds']))
        score.update(previously_exposed=True,used_for_selection=False,fresh_holdout=False)
        scored=save(args.output/f'{record["dimension"]}-{record["arm"]}'/(record['role']+'-score.json'),score)
        check_deadline(deadline)
        results.append(dict(record,score_ref=scored,scoring_seconds=score['elapsed_seconds'],
            ordered_exact=score['fidelity']['metrics']['ordered_exact'],syntax_valid=score['fidelity']['metrics']['syntax_valid'],
            token_cross_entropy=score['teacher_forced']['token_cross_entropy']))
        del model,prediction,score
    after=runner.source_inventory(previous,ctx);require(all(after.get(k)==v for k,v in before.items()),'observer producer changed')
    recheck();save(args.output/'summary.json',dict(schema='training-mixture-exposed-v3-results/v1',complete=True,
        panels=results,source_dependencies=after,elapsed_seconds=time.monotonic()-started,previously_exposed=True,
        references_sha256=ctx['core'].digest(refs),holdout_receipt_sha256=ctx['core'].digest(receipt),
        all_predictions_persisted_before_reference_load=True,recipe=FIXED,**FALSE))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['evaluation'],required=True);execute(parser.parse_args())


if __name__=='__main__':main()
