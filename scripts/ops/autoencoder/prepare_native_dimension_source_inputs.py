#!/usr/bin/env python3
"""Prepare exact local 8D/384D/768D sources without targets in producer input."""
import argparse
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

from importlib.util import spec_from_file_location,module_from_spec
import hashlib

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)

FIXED=dict(schema='native-dimension-source-preparation-plan/v1',dimensions=[8,384,768],
    max_tokens=512,max_seconds=600,batch_size=4,weight_downloads=False,source_only=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preparation'],required=True);args=parser.parse_args();started=time.monotonic()
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());pins=manifest['extensions']
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'preparation plan differs')
    require(all(type(plan.get(k)) is type(v) and json.dumps(plan[k],sort_keys=True,allow_nan=False)
        ==json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),'preparation bounds differ')
    for path,digest in manifest['inputs'].items():require(sha(path)==digest,'preparation input changed: '+path)
    for key in ('parent_manifest','parent_plan','native768_report','asset_manifest'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'],'unbound preparation alias: '+key)
    rel='scripts/ops/autoencoder/benchmark_clause_context_source_training.py'
    require(sha(args.extension_root/rel)==pins[rel],'preparation replay helper differs')
    spec=spec_from_file_location('_dimension_preparation_prior',args.extension_root/rel);prior=module_from_spec(spec);spec.loader.exec_module(prior)
    older=SimpleNamespace(**vars(args));older.manifest=Path(manifest['parent_manifest']);older.plan=Path(manifest['parent_plan'])
    ctx=prior.load_context(older);h=ctx['helpers'];package=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder')
    package.__path__.insert(0,str(args.extension_root/'ipfs_datasets_py/logic/formalization/autoencoder'))
    owner=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.dimension_source_inputs')
    before=h.inventory(args.dependency_root,args.extension_root,pins);save=h.save;args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,tree_pin=ctx['tree'],qualified=False,admitted=False))
    source_rows={split:[{k:r[k] for k in ('id','source_text','input')} for r in ctx['rows'][split]] for split in ('train','validation')}
    source_plan=owner.plan_sources(source_rows,ctx['source_contexts'],manifest['native768_report'],
        expected_native_report_sha256=manifest['inputs'][manifest['native768_report']])
    save(args.output/'source-plan.json',source_plan)
    require(source_plan['unique_sources']==239 and source_plan['missing768_sources']==72 and source_plan['cached768_sources']==167,
        'registered exact-source cache coverage differs')
    eight=owner.produce_historical8(source_plan);save(args.output/'historical8-production.json',eight)
    produced=owner.produce_missing768(source_plan,manifest_path=manifest['asset_manifest'],
        expected_manifest_sha256=manifest['inputs'][manifest['asset_manifest']],
        model_directory=manifest['model_directory'],code_directory=manifest['code_directory'],batch_size=4,max_seconds=600)
    save(args.output/'bounded768-production.json',produced)
    values=owner.assemble_inputs(source_plan,eight,produced);ref=save(args.output/'dimension-inputs.json',values)
    after=h.inventory(args.dependency_root,args.extension_root,pins)
    require(all(after.get(k)==v for k,v in before.items()),'preparation producer changed')
    for path,digest in manifest['inputs'].items():require(sha(path)==digest,'preparation input changed')
    for rel,digest in pins.items():require(sha(args.extension_root/rel)==digest,'preparation frozen source changed')
    save(args.output/'summary.json',dict(schema='native-dimension-source-preparation/v1',complete=True,
        dimension_inputs=ref,dimensions=[8,384,768],unique_sources=239,paragraphs=96,
        unique_clauses=167,encoder_rows_executed=72,historical_feature_rows_executed=239,
        cache_scope='384paragraphs_and_clauses_warm;167native768clauses_warm;72new_native768paragraphs',
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,workers=1,device='cpu',
        max_tokens=512,training_executed=False,weights_downloaded=False,historical_teacher_changed=False,
        qualified=False,admitted=False,lake_executed=False,formalized=False,roundtrip_ok=False))
    print(json.dumps(dict(complete=True,dimension_inputs=ref,elapsed_seconds=time.monotonic()-started)),flush=True)

if __name__=='__main__':main()
