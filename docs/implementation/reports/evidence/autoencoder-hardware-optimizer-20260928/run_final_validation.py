"""Validate final defaults; this changes selection data, not qualification gates."""
import hashlib,importlib.util,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path.cwd().resolve()
BASE=ROOT/'workspace/test-logs/federal-corpus-audits/autoencoder-hardware-optimizer-20260928'
def write(path,value):
 with path.open('x') as f: json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 spec=importlib.util.spec_from_file_location('final_cli',ROOT/'scripts/ops/legal_ir/run_incremental_autoencoders.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
 sources=cli._pin();manifest=_package_manifest()
 write(BASE/'final-native-binding.json',{'producer_manifest':manifest,'core_sources':sources,'orchestration':cli.orchestration_hashes(),'checkpoint':{'sha256':cli.PINNED_SHA,'bytes':cli.PINNED.stat().st_size},'input_sha256':sha(BASE/'input.jsonl'),'validation_sha256':sha(BASE/'validation.jsonl'),'admitted':False})
 argv=[sys.executable,'scripts/ops/legal_ir/run_incremental_autoencoders.py','--execution-mode','training','--state-directory',str(BASE/'tuning-validation'),'--input-jsonl',str(BASE/'input.jsonl'),'--validation-jsonl',str(BASE/'validation.jsonl'),'--workers','2','--max-batches','4','--max-training-rounds','1','--max-seconds','120','--lake-timeout-seconds','60','--cycle-timeout','420','--storage-bytes','500000000']
 start=time.monotonic()
 with (BASE/'tuning-validation.log').open('xb') as f:
  result=subprocess.run(argv,cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},stdout=f,stderr=subprocess.STDOUT,timeout=480)
 report={'argv':argv,'returncode':result.returncode,'wall_seconds':time.monotonic()-start,'source_unchanged':_package_manifest()==manifest,'checkpoint_unchanged':sha(cli.PINNED)==cli.PINNED_SHA,'selection_role':'disjoint_repeated_tuning_not_independent_canary','reuse_opt_in':False,'admitted':False}
 write(BASE/'final-command.json',report);print(json.dumps(report),flush=True)
 assert result.returncode==0 and report['source_unchanged'] and report['checkpoint_unchanged']
if __name__=='__main__':main()
