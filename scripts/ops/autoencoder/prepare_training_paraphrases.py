#!/usr/bin/env python3
"""Guarded preparation of TRAIN paraphrases and verified384/768 source vectors.

The existing frozen setup authenticates assets and syntax tools. Its parent
metadata includes old references; only original TRAIN labels reach the builder,
and only closed source rows reach either encoder. No model scoring or fitting.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
PARENT = 'scripts/ops/autoencoder/observe_fresh_normative_style.py'
FIXED = dict(schema='training-paraphrases-preparation-plan/v1', dimensions=[384,768],
    role='train_augmentation', original_train_sources=180, original_train_rules=90,
    source_paragraphs=48, unique_clauses=180, unique_sources=216, seed=20261007,
    templates=['rule_gerund_by_actor','topicalized_actor_norm'], batch_size=4,
    context_tokens=512, output_tokens=512, temperature=0, workers=1,
    max_seconds_per_encoder=600, max_seconds_total=1400,
    training_executed=False, preprocessing_fitted=False, evaluation_scored=False,
    fresh_holdout_claimed=False, downloads_performed=False, qualified=False,
    admitted=False, lake_executed=False, bridge_names=[], legal_ir_evaluate_provers=False,
    metric_disk_cache_used=False, checkpoint_promoted=False)


def require(condition, message):
    if not condition: raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def read_bound(manifest,path):
    path=Path(path).resolve(); expected=manifest['inputs'].get(str(path))
    require(expected is not None and sha(path)==expected,'unbound or changed input: '+str(path))
    return json.loads(path.read_bytes())


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and plan[k]==v
        for k,v in FIXED.items()),'fixed TRAIN preparation recipe differs')


def source_inventory(args,manifest):
    allowed=dict(manifest['producer_pins'])
    allowed.update({str((args.extension_root/r).resolve()):v for r,v in manifest['extensions'].items()})
    found={}
    for name,module in list(sys.modules.items()):
        if name=='ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
            p=getattr(module,'__file__',None)
            if p:
                path=str(Path(p).resolve());value=sha(path)
                require(allowed.get(path)==value,'unbound resident source producer: '+path);found[path]=value
    return found


def prior_vectors(manifest,dimension):
    values=[]
    for descriptor in manifest['prior_vector_rows'][str(dimension)]:
        rows=read_bound(manifest,descriptor['path'])
        for key in descriptor['keys']:rows=rows[key]
        require(type(rows) is list and rows,'nonempty explicit prior vector inventory required')
        for row in rows:
            vector=row['input']; require(type(vector) is list and len(vector)==dimension,'prior vector width differs')
            values.append(tuple(vector))
    require(values,'prior vectors absent')
    return set(values),len(values)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preparation'],required=True);args=parser.parse_args()
    start=time.monotonic();manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'TRAIN preparation seal differs')
    manifest_hash=sha(args.manifest)
    def recheck():
        require(sha(args.manifest)==manifest_hash and sha(args.plan)==manifest['plan_sha256'],'plan/manifest changed')
        for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'bound input changed: '+path)
        for name,wanted in manifest['extensions'].items():require(sha(args.extension_root/name)==wanted,'owned frozen source changed')
        require(time.monotonic()-start<FIXED['max_seconds_total'],'TRAIN preparation phase deadline exceeded')
    recheck();require(not args.output.exists(),'fresh preparation output required');args.output.mkdir(parents=True)
    root=Path(manifest['parent_extension_root']);old=read_bound(manifest,manifest['parent_manifest'])
    require(sha(root/PARENT)==old['extensions'][PARENT],'frozen parent runner differs')
    spec=importlib.util.spec_from_file_location('_paraphrase_parent',root/PARENT)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args));previous.extension_root=root
    previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=owner.load_context(previous);owner.load_producers(previous,ctx)
    helpers=ctx['helpers'];save=helpers.save;owners={}
    for name in ('authored_training_paraphrases','training_paraphrase_source_inputs'):
        owners[name]=helpers.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,manifest['extensions'])
        setattr(sys.modules[PREFIX[:-1]],name,owners[name])
    before=source_inventory(args,manifest)
    bank=read_bound(manifest,manifest['training_bank'])
    training=[{k:r[k] for k in ('id','source_text','target_ids')} for r in bank]
    prior=owner.prior_inventory(ctx['fresh_manifest'])
    prior['original_train_bank']=[{k:r[k] for k in ('id','source_text')} for r in training]
    prior['exposed_v3']=read_bound(manifest,manifest['exposed_v3_sources'])
    save(args.output/'original-training-bank-used.json',training)
    save(args.output/'prior-source-inventories.json',prior)
    builder=owners['authored_training_paraphrases'];producer=owners['training_paraphrase_source_inputs']
    built=builder.build(training_bank=training,prior_sources_by_dataset=prior,codec=ctx['donor']['codec'],
        sealed_recipe_sha256=manifest['recipe_seal'],seed=FIXED['seed'],validate_rule=ctx['validate_rule'])
    source_ref=save(args.output/'source-rows.json',built['source_rows'])
    refs_ref=save(args.output/'training-references.json',built['references'])
    build_ref=save(args.output/'training-corpus-receipt.json',built['receipt'])
    source_plan=producer.source_plan(built['source_rows'],expected_source_rows_sha256=built['receipt']['source_rows_sha256'],sealed_recipe_sha256=manifest['recipe_seal'])
    save(args.output/'source-plan.json',source_plan)
    assets=read_bound(manifest,manifest['asset_config']);outputs={}
    for dimension in FIXED['dimensions']:
        recheck();old_vectors,old_rows=prior_vectors(manifest,dimension)
        report=producer.produce_width(source_plan,dimension=dimension,asset_config=assets[str(dimension)],
            source_artifact_directory=args.output/'source384-artifacts' if dimension==384 else None,
            batch_size=4,max_seconds=min(600,FIXED['max_seconds_total']-(time.monotonic()-start)))
        require(producer.validate_report(source_plan,report)==dimension,'production width differs')
        new_vectors=[tuple(r['vector']) for r in report['vectors']]
        require(len(set(new_vectors))==216 and not old_vectors.intersection(new_vectors),
            'new TRAIN vector identity overlaps prior or another source; no fallback')
        vectors={r['source_sha256']:r['vector'] for r in report['vectors']}
        rows=[dict(row,input=vectors[builder.base.text_sha(row['source_text'])]) for row in built['source_rows']]
        cache=[];seen=set()
        for row in built['source_rows']:
            for text in row['source_text'].split('\n\n'):
                key=builder.base.text_sha(text)
                if key not in seen:seen.add(key);cache.append(dict(id='clause:'+key,source_text=text,input=vectors[key]))
        clause_owner=ctx['owners']['clause_source_context']
        contexts=clause_owner.build_source_contexts(built['source_rows'],cache)
        require(clause_owner.validate_contexts(rows,contexts)['dimension']==dimension,'TRAIN contexts differ')
        payload=dict(schema='training-paraphrase-source-inputs/v1',complete=True,role='train_augmentation',dimension=dimension,
            rows=rows,clause_cache=cache,source_contexts=contexts,production_sha256=report['production_sha256'],
            source_plan_sha256=source_plan['plan_sha256'],targets_attached=False,preprocessing_fitted=False,
            qualified=False,admitted=False,checkpoint_promoted=False)
        payload['inputs_sha256']=builder.digest(payload)
        outputs[str(dimension)]=dict(production=save(args.output/f'production-{dimension}.json',report),
            source_inputs=save(args.output/f'dimension-inputs-{dimension}.json',payload),
            encoder_seconds=report['elapsed_seconds'],seconds_per_unique_source=report['elapsed_seconds']/216,
            prior_vector_rows=old_rows,prior_unique_vectors=len(old_vectors),vector_identity_overlap=0)
        print(json.dumps(dict(dimension=dimension,complete=True,unique_sources=216,seconds=report['elapsed_seconds'])),flush=True)
    after=source_inventory(args,manifest);require(all(after.get(k)==v for k,v in before.items()),'resident source changed')
    recheck()
    save(args.output/'summary.json',dict(**FIXED,complete=True,phase='preparation',outputs=outputs,
        encoder_executed=True,source_rows=source_ref,training_references=refs_ref,corpus_receipt=build_ref,
        source_dependencies=after,elapsed_seconds=time.monotonic()-start,
        cache_scope='new local forward outputs; OS page-cache warmth uncontrolled; metric disk cache off'))


if __name__=='__main__':main()
