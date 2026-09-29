"""Bound source variants explicitly; run the unchanged native qualification route."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path.cwd().resolve();BASE=ROOT/'workspace/test-logs/federal-corpus-audits/autoencoder-search-20260929'
POOL=ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_native_pool.py'
CLI=ROOT/'scripts/ops/legal_ir/run_incremental_autoencoders.py'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,sort_keys=True,indent=2);f.write('\n')
def run(label,parallel,refinement,shared,qualification_parallel=0):
 spec=importlib.util.spec_from_file_location('native_comparison_cli',CLI);cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
 sources=cli._pin();manifest=_package_manifest()
 argv=[sys.executable,str(CLI),'--execution-mode','training','--state-directory',str(BASE/label),'--input-jsonl',str(BASE/'input.jsonl'),'--validation-jsonl',str(BASE/'validation.jsonl'),'--workers','32','--parallel-workers',str(parallel),'--max-batches','8','--memory-mb','12288','--max-training-rounds','1','--max-seconds','120','--lake-timeout-seconds','60','--cycle-timeout','420','--storage-bytes','750000000']
 argv+=['--parallel-qualification-workers',str(qualification_parallel)]
 if refinement:argv+=['--composed-refinement-attempts',str(refinement)]
 if shared:
  handoff=json.loads((BASE/'shared-targets'/'receipt.json').read_text())
  argv+=handoff['runner_arguments']
 write(BASE/(label+'-binding.json'),{'producer_manifest':manifest,'core_sources':sources,'orchestration':cli.orchestration_hashes(),'checkpoint':{'sha256':cli.PINNED_SHA,'bytes':cli.PINNED.stat().st_size},'input_sha256':sha(BASE/'input.jsonl'),'validation_sha256':sha(BASE/'validation.jsonl'),'measurement_label':label,'admitted':False})
 start=time.monotonic()
 with (BASE/(label+'.log')).open('x') as f:r=subprocess.run(argv,cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT),'CUDA_VISIBLE_DEVICES':'','IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE':'0'},stdout=f,stderr=subprocess.STDOUT)
 report={'argv':argv,'returncode':r.returncode,'wall_seconds':time.monotonic()-start,'source_unchanged':_package_manifest()==manifest,'checkpoint_unchanged':sha(cli.PINNED)==cli.PINNED_SHA,'parallel_workers':parallel,'qualification_parallel_workers':qualification_parallel,'refinement_attempt_limit':refinement,'shared_targets':shared,'admitted':False}
 write(BASE/(label+'-command.json'),report);print(json.dumps(report),flush=True)
 assert r.returncode==0 and report['source_unchanged'] and report['checkpoint_unchanged']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['run']);p.add_argument('--label');p.add_argument('--parallel',type=int,default=2);p.add_argument('--refinement',type=int,default=0);p.add_argument('--qualification-parallel',type=int,choices=range(33),default=0);p.add_argument('--shared',action='store_true');a=p.parse_args()
 run(a.label,a.parallel,a.refinement,a.shared,a.qualification_parallel)
