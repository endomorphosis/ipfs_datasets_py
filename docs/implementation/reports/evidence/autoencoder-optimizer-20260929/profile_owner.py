"""Profile the existing supervised route; instrumentation only, not a speed baseline."""
import contextlib,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path.cwd().resolve();BASE=ROOT/'workspace/test-logs/federal-corpus-audits/autoencoder-optimizer-20260929'
PREV=BASE.parent/'autoencoder-hardware-optimizer-20260928'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 with p.open('x') as f:json.dump(x,f,sort_keys=True,indent=2);f.write('\n')
def main():
 spec=importlib.util.spec_from_file_location('profile_cli',ROOT/'scripts/ops/legal_ir/run_incremental_autoencoders.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
 for name in ['input.jsonl','validation.jsonl']:
  if not (BASE/name).exists():shutil.copyfile(PREV/name,BASE/name)
 ledger=ROOT/'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
 if not (BASE/'ledger-before.json').exists():shutil.copyfile(ledger,BASE/'ledger-before.json')
 manifest=_package_manifest();write(BASE/'owner-profile-binding.json',{'producer_manifest':manifest,'core_sources':cli._pin(),'orchestration':cli.orchestration_hashes(),'checkpoint_sha256':sha(cli.PINNED),'admitted':False})
 original=subprocess.Popen
 def profiled(args,*a,**kw):
  if isinstance(args,list) and '--_cycle' in args and str(Path(cli.__file__).resolve()) in args:
   args=[args[0],'-m','cProfile','-o',str(BASE/'owner.pstats'),*args[1:]]
  return original(args,*a,**kw)
 subprocess.Popen=profiled
 argv=['--execution-mode','training','--state-directory',str(BASE/'owner-profile'),'--input-jsonl',str(BASE/'input.jsonl'),'--validation-jsonl',str(BASE/'validation.jsonl'),'--workers','2','--max-batches','4','--max-training-rounds','1','--max-seconds','120','--lake-timeout-seconds','60','--cycle-timeout','420','--storage-bytes','500000000']
 start=time.monotonic()
 with (BASE/'owner-profile.log').open('x') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
  result=cli.main(argv)
 report={'argv':argv,'returncode':result,'wall_seconds':time.monotonic()-start,'instrumentation':'cProfile child owner; timing not comparable to unprofiled runs','source_unchanged':_package_manifest()==manifest,'checkpoint_unchanged':sha(cli.PINNED)==cli.PINNED_SHA,'admitted':False}
 write(BASE/'owner-profile-command.json',report);print(json.dumps(report),flush=True)
 assert result==0 and report['source_unchanged'] and report['checkpoint_unchanged']
if __name__=='__main__':main()
