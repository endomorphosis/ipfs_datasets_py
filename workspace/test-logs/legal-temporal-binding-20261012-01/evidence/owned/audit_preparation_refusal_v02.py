"""Read-only refinement of exact retry02 preparation refusal; no numeric import."""
import ast
from datetime import datetime,timezone
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys
F=Path(__file__).resolve().parent
OUT=F/'training-preparation-refusal-audit-v02.json'
A=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261012-02')
RUNNER_SHA='0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'
RUNTIME_SHA='b1d5d6b8453f97e5428391faeaa46e46a11baf21cc061b4f78b38079fe966346'
sys.dont_write_bytecode=True
class DenyModels(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:raise AssertionError('Numeric import denied')
  return None
sys.meta_path.insert(0,DenyModels())
def hook(event,args):
 if event.startswith(('subprocess.','socket.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock'}:raise AssertionError('Read-only observer denied side effect')
 if event=='open':
  path,mode,flags=args;w=isinstance(mode,str) and any(c in mode for c in 'wax+')
  w|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if w and (not isinstance(path,(str,bytes,os.PathLike)) or Path(os.fsdecode(path)).absolute()!=OUT):raise AssertionError('Only exclusive refinement receipt allowed')
sys.addaudithook(hook)
def require(x,m):
 if not x:raise ValueError(m)
def pin(p):
 p=Path(p);require(p.is_file() and not p.is_symlink(),'ordinary artifact required');s=p.stat();b=p.read_bytes();t=p.stat()
 require((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns),'artifact changed')
 return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_bytes())
def main():
 runtime_path=F/'training-runtime-resource-audit-v02.json';runner=F/'run_temporal_contrast_pilot.py'
 require(pin(runner)['sha256']==RUNNER_SHA and pin(runtime_path)['sha256']==RUNTIME_SHA,'exact frozen producer/runtime required')
 runtime=read(runtime_path);pre=read(A/'pre-admission.json');failure=read(A/'results/child-failure.json');primary=read(A/'failure-primary.json')
 require(pre['runner']==pin(runner),'actual pre-admission source differs')
 for rel,expected in runtime['artifacts'].items():require(pin(A/rel)==expected,'failure artifact changed')
 require(runtime['passed'] and runtime['outcome']=='failed_or_refused' and runtime['failed_before_model_gate'] is False,'actual post-gate failure required')
 require(primary['model_started'] is True and runtime['recorded_returned_prefix_updates']==0
  and runtime['in_progress_or_unreported_partial_updates_unknown'] is False,'gate/update evidence differs')
 require(failure['stage']=='preparation' and failure['completed_updates']==0 and failure['saved_states']==[]
  and failure['in_progress_arm_updates_unknown'] is False and failure['error_type']=='ValueError'
  and failure['detail']=='unfrozen package producer: ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator','exact child preparation failure required')
 require({x.name for x in (A/'results').iterdir()}=={'child-failure.json'},'results inventory differs')
 log=(A/'child.log').read_text()
 for text in ('line 527, in main','opening_owners = owner_origins(plan)','line 145, in owner_origins','unfrozen package producer: ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator'):
  require(text in log,'exact recorded failing frame differs')
 tree=ast.parse(runner.read_text());main_node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
 assignments={target.id:node.lineno for node in ast.walk(main_node) if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name)}
 torch_lines=[n.lineno for n in ast.walk(main_node) if isinstance(n,ast.Import) and any(a.name=='torch' for a in n.names)]
 require(assignments['opening_owners']==527 and assignments['data']==528 and assignments['historical']==531
  and torch_lines==[556],'frozen runner stage ordering differs')
 require(assignments['opening_owners']<assignments['data']<assignments['historical']<torch_lines[0],'failure not before later numerical preparation')
 result=dict(schema='temporal-binding-preparation-refusal-refinement/v1',passed=True,findings=[],
  observed_at_utc=datetime.now(timezone.utc).isoformat(),helper=pin(Path(__file__)),runtime_audit=pin(runtime_path),
  runner=pin(runner),physical_attempt=str(A),gate_permission_was_opened=True,failed_before_model_gate=False,
  failed_before_numerical_import=True,numerical_import_classification_scope='Before the explicit runner main import torch; full third-party optional import graph not qualified',
  exact_failure_stage='preparation_owner_origin_check',failure_runner_line=527,data_JSON_parsing_line=528,
  historical_checkpoint_JSON_parsing_line=531,explicit_runner_torch_import_line=556,
  actual_completed_optimizer_updates=0,unknown_in_progress_arm_updates=False,saved_model_states=[],
  model_call_assessment='Zero calls to runner numerical/model functions inferred from exact source order, failure trace and returned preparation state; no independent numerical-call trace',
  historical_checkpoint_bytes_already_hashed_by_opening_pin_checks=True,historical_checkpoint_parsing_or_restore_reached=False,
  sampled_model_phase_RSS_not_used_as_model_call_evidence=True,all_prior512_preserved=runtime['all_prior_512_record_bodies_unchanged'],
  artifacts=runtime['artifacts'],observer_model_calls=0,observer_optimizer_updates=0,observer_claim_changes=0,observer_locks=0)
 for rel,expected in runtime['artifacts'].items():require(pin(A/rel)==expected,'failure artifact changed during refinement')
 require(pin(runner)['sha256']==RUNNER_SHA and pin(runtime_path)['sha256']==RUNTIME_SHA,'producer/runtime changed during refinement')
 with OUT.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
 print(json.dumps(pin(OUT),sort_keys=True))
if __name__=='__main__':main()
