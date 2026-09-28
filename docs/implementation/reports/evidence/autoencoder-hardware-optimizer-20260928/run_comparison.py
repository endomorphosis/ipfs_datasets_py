"""Same-code native fresh/reused-worker comparison under the real supervisor."""
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path.cwd().resolve()
BASE=ROOT/'workspace/test-logs/federal-corpus-audits/autoencoder-hardware-optimizer-20260928'
def write(path,value):
    with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    spec=importlib.util.spec_from_file_location('comparison_cli',ROOT/'scripts/ops/legal_ir/run_incremental_autoencoders.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_incremental_training import assignment
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    sources=cli._pin()
    manifest=_package_manifest()
    artifact={'sha256':cli.PINNED_SHA,'bytes':cli.PINNED.stat().st_size}
    assert sha(cli.PINNED)==cli.PINNED_SHA
    # Read-only registry-shaped adapter only for deterministic input placement.
    # The actual runs below always use the real DuckDB/Quack owner.
    class PlacementOnly:
        def register_variant(self,*args):pass
        def stage_artifact(self,path,*args):assert Path(path)==cli.PINNED;return artifact
        def register_version(self,*args):return {'version_id':'placement-only'}
        def artifact_path(self,*args):return cli.PINNED
    possible=[]
    for n in range(20,45):
        if n==30:continue
        row=asdict(SampleRecord.from_dict({'title':'qualification-fixture','section':str(n),'text':f'The officer shall retain the file for at least {n} days.','embedding_model':'mock:stable-sha256'}))
        rid=hashlib.sha256(cli._json(row).encode()).hexdigest()
        possible.append({'record_id':rid,'sample':row,'provenance':{'kind':'synthetic_numeric_fixture'}})
    validation=cli.local_records(BASE/'validation.jsonl')
    templates=cli.make_templates(PlacementOnly(),possible,state_directory=BASE/'placement-only',checkpoint=cli.PINNED,source_hashes=sources,max_seconds=120.0,validation_records=validation)
    selected={0:[],1:[]}
    for row,template in zip(possible,templates):
        lane=assignment(template,1,2)['lane_index']
        if len(selected[lane])<2:selected[lane].append(row)
    rows=selected[0]+selected[1]
    assert len(rows)==4
    (BASE/'input.jsonl').write_text(''.join(json.dumps(r['sample'],sort_keys=True)+'\n' for r in rows))
    write(BASE/'native-binding.json',{'producer_manifest':manifest,'core_sources':sources,'orchestration':cli.orchestration_hashes(),'checkpoint':artifact,'input_sha256':sha(BASE/'input.jsonl'),'validation_sha256':sha(BASE/'validation.jsonl'),'selected_lane_samples':{str(k):[x['sample'] for x in v] for k,v in selected.items()},'admitted':False})
    runs=[]
    for label,fresh in [('fresh',True),('reused',False)]:
        assert _package_manifest()==manifest
        argv=[sys.executable,'scripts/ops/legal_ir/run_incremental_autoencoders.py','--execution-mode','training','--state-directory',str(BASE/label),'--input-jsonl',str(BASE/'input.jsonl'),'--validation-jsonl',str(BASE/'validation.jsonl'),'--workers','2','--max-batches','4','--max-training-rounds','1','--max-seconds','120','--lake-timeout-seconds','60','--cycle-timeout','420','--storage-bytes','500000000']
        if fresh:argv.append('--fresh-training-workers')
        started=time.monotonic()
        with (BASE/(label+'.log')).open('xb') as f:
            result=subprocess.run(argv,cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},stdout=f,stderr=subprocess.STDOUT,timeout=480)
        runs.append({'label':label,'argv':argv,'returncode':result.returncode,'wall_seconds':time.monotonic()-started,'log':label+'.log','source_unchanged':_package_manifest()==manifest})
        write(BASE/(label+'-command.json'),runs[-1])
        print(json.dumps(runs[-1]),flush=True)
        if result.returncode or not runs[-1]['source_unchanged']:raise RuntimeError('native comparison failed; see retained log')
    assert sha(cli.PINNED)==cli.PINNED_SHA
    write(BASE/'executed-commands.json',{'runs':runs,'checkpoint_unchanged':True,'producer_manifest_unchanged':_package_manifest()==manifest,'admitted':False})

if __name__=='__main__':main()
