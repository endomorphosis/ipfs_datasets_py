#!/usr/bin/env python3
"""Prepare a sealed postfit-only authored cohort with local source encoders."""
import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time
import hashlib

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FIXED=dict(schema='source-margin-holdout-preparation-plan/v1',dimensions=[8,384,768],
    samples=48,clauses=180,unique_sources=216,seed=20261004,max_tokens=512,
    batch_size=4,max_seconds_per_width=600,max_seconds_entire_run=1400,
    source_only_encoder_inputs=True,weights_downloaded=False,training_executed=False,
    test_used_for_selection=False,temperature=0)


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and plan[k]==v
        for k,v in FIXED.items()),'fixed holdout preparation policy differs')


def bound_json(manifest,path):
    path=Path(path).resolve()
    require(manifest['inputs'].get(str(path))==sha(path),'unbound or changed preparation input')
    return json.loads(path.read_bytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preparation'],required=True)
    args=parser.parse_args();started=time.monotonic()
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes())
    validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],
        'sealed preparation plan differs')
    for path,digest in manifest['inputs'].items():require(sha(path)==digest,'preparation input changed: '+path)
    pins=manifest['extensions']
    for rel,digest in pins.items():require(sha(args.extension_root/rel)==digest,'frozen preparation source changed: '+rel)
    for key in ('parent_manifest','parent_plan','training_paragraphs','asset_config'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'],'unbound preparation alias: '+key)
    require(sha(manifest['parent_plan'])==manifest['comparison_seal'],'comparison recipe changed')
    rel='scripts/ops/autoencoder/benchmark_source_margin_training.py'
    spec=importlib.util.spec_from_file_location('_holdout_training_context',args.extension_root/rel)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    older=SimpleNamespace(**dict(vars(args),manifest=Path(manifest['parent_manifest']),plan=Path(manifest['parent_plan'])))
    ctx=runner.load_context(older);h=ctx['helpers']
    for name in ('dimension_source_inputs','legal_native_conditioning','source_embeddings_768',
                 'source_embeddings_768_complete','authored_scalar_holdout','fresh_scalar_source_inputs'):
        ctx['owners'][name]=h.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins)
    runtime='ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py'
    h.extension(args.extension_root,runtime,
        'ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime',pins)
    before=h.inventory(args.dependency_root,args.extension_root,pins)
    args.output.mkdir(parents=True,exist_ok=False)
    h.save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,tree_pin=ctx['tree']))
    paragraphs=bound_json(manifest,manifest['training_paragraphs'])
    training=[{k:r[k] for k in ('id','source_text','target')} for r in paragraphs['train']]
    require(len(training)==48,'exact original paragraph training inventory required')
    aligned={r['id']:r['target'] for r in ctx['references']['train']}
    require(training==[dict(id=r['id'],source_text=r['source_text'],target=aligned[r['id']])
        for r in ctx['rows']['train']],'holdout pair strata must use actual training references only')
    require(set(manifest['prior_sources'])=={'train','validation','test','canary'},'all prior split sources required')
    blacklists={split:[{k:r[k] for k in ('id','source_text')} for r in bound_json(manifest,path)['rows']]
        for split,path in manifest['prior_sources'].items()}
    owner=ctx['owners']['authored_scalar_holdout']
    cohort=owner.build_holdout(training_rows=training,prior_sources_by_split=blacklists,
        codec=ctx['donor']['codec'],sealed_comparison_sha256=manifest['comparison_seal'],
        seed=FIXED['seed'],validate_rule=ctx['validate_rule'])
    sources=h.save(args.output/'source-rows.json',cohort['source_rows'])
    refs=h.save(args.output/'references.json',cohort['references'])
    receipt=h.save(args.output/'holdout-receipt.json',cohort['receipt'])
    producer=ctx['owners']['fresh_scalar_source_inputs']
    source_plan=producer.source_plan(cohort['source_rows'],
        expected_source_rows_sha256=cohort['receipt']['source_rows_sha256'],
        sealed_comparison_sha256=manifest['comparison_seal'])
    h.save(args.output/'source-plan.json',source_plan)
    assets=bound_json(manifest,manifest['asset_config']);produced={}
    for dimension in FIXED['dimensions']:
        require(time.monotonic()-started<FIXED['max_seconds_entire_run'],'preparation deadline exceeded')
        report=producer.produce_width(source_plan,dimension=dimension,asset_config=assets[str(dimension)],
            source_artifact_directory=args.output/'source384-artifacts' if dimension==384 else None,
            batch_size=4,max_seconds=600)
        produced[str(dimension)]=report
        h.save(args.output/('production-'+str(dimension)+'.json'),report)
        print(json.dumps(dict(dimension=dimension,source_production_complete=True,
            elapsed_seconds=time.monotonic()-started)),flush=True)
    assembled=producer.assemble(source_plan,produced)
    result=h.save(args.output/'dimension-inputs.json',assembled)
    after=h.inventory(args.dependency_root,args.extension_root,pins)
    require(all(after.get(k)==v for k,v in before.items()),'loaded source producer changed')
    for path,digest in manifest['inputs'].items():require(sha(path)==digest,'sealed preparation input changed')
    for rel,digest in pins.items():require(sha(args.extension_root/rel)==digest,'frozen preparation source changed')
    require(sha(args.plan)==manifest['plan_sha256'],'sealed preparation plan changed')
    require(time.monotonic()-started<FIXED['max_seconds_entire_run'],'preparation deadline exceeded')
    h.save(args.output/'summary.json',dict(schema='source-margin-holdout-preparation/v1',complete=True,
        dimension_inputs=result,source_rows=sources,references=refs,holdout_receipt=receipt,
        comparison_seal=manifest['comparison_seal'],source_dependencies=after,
        elapsed_seconds=time.monotonic()-started,workers=1,device='cpu',batch_size=4,
        max_tokens=512,samples=48,unique_sources=216,encoder_cache='fresh exact source texts',
        training_executed=False,weights_downloaded=False,qualified=False,admitted=False,
        lake_executed=False,historical_linguistic_teacher_modified=False,formalized=False,roundtrip_ok=False))


if __name__=='__main__':main()
