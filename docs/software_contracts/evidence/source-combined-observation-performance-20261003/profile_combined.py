"""Diagnostic stage timers; native sources, assets, resources and 90s boundary."""
from pathlib import Path
import ast, hashlib, inspect, json, os, subprocess, sys, time, traceback
BASE=Path('/home/barberb/lift_coding/artifacts/source-combined-observation-performance-20261003')
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
A=Path('/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002')
sys.path[:0]=[str(A),str(D)]
out=BASE/sys.argv[1];out.mkdir();app=out/'app';app.mkdir()
sha=lambda body:hashlib.sha256(body).hexdigest()
original=Path('/home/barberb/lift_coding/artifacts/terminal_bench_supervisor/full-integration-20260929/terminal-full-preflight-host-01')
source_receipt=(original/'state/original-image.json').read_bytes()
allowed=json.loads(source_receipt)['sources'];source_hashes={}
for name,meta in allowed.items():
 body=(original/'app'/name).read_bytes();assert sha(body)==meta['sha256']
 target=app/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body);target.chmod(0o755 if meta['executable'] else 0o644);source_hashes[name]=sha(body)
preparation_owner=A/'benchmarks/agent_supervisor/container_coding/terminal_indexed_preparation.py'
smoke=next(ast.literal_eval(node.value) for node in ast.parse(preparation_owner.read_text()).body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='PUBLIC_SMOKE' for target in node.targets))
instruction=Path('/home/barberb/lift_coding/artifacts/source384-docker-publication-20261003/docker-01/public-instruction.md').read_bytes()
for name,body in [('.supervisor-instruction.md',instruction),('.supervisor-public-smoke.py',smoke.encode())]:
 (app/name).write_bytes(body);source_hashes[name]=sha(body)
for args in [('init','-q'),('add','.'),('-c','user.name=Qualification','-c','user.email=qualification@localhost','commit','-qm','Captured public source with native public inputs')]:
 subprocess.run(['git','-C',str(app),*args],check=True,capture_output=True)
record=dict(schema='source-combined-observation-profile@1',diagnostic=True,lightweight_stage_timers=True,source_files=len(source_hashes),source_hashes=source_hashes,source_receipt_sha256=sha(source_receipt),public_preparation_owner_sha256=sha(preparation_owner.read_bytes()),script_sha256=sha(Path(__file__).read_bytes()),deadline_seconds=90,parent_memory_mb=6144,parent_cpu_slots=3,native_child_memory_mb=4096,provider_calls=0,training_steps=0,neural_inference=False,full_context_qualification=False,stage_timers={},phases={})
timings=record['stage_timers'];phases=record['phases']
def timed(cls,name):
 descriptor=inspect.getattr_static(cls,name);original_method=getattr(cls,name)
 def wrapped(*args,**kwargs):
  start=time.monotonic()
  try:return original_method(*args,**kwargs)
  finally:
   row=timings.setdefault(cls.__name__+'.'+name,dict(calls=0,seconds=0.));row['calls']+=1;row['seconds']+=time.monotonic()-start
 if isinstance(descriptor,staticmethod):setattr(cls,name,staticmethod(wrapped))
 elif isinstance(descriptor,classmethod):
  def classwrapped(_cls,*args,**kwargs):return wrapped(*args,**kwargs)
  setattr(cls,name,classmethod(classwrapped))
 else:setattr(cls,name,wrapped)
def phase(name,call):
 start=time.monotonic()
 try:return call()
 finally:phases[name]=time.monotonic()-start;print(json.dumps(dict(phase=name,seconds=phases[name])),flush=True)
begun=time.monotonic()
from ipfs_accelerate_py.agent_supervisor.runtime import source384_repository_context as owner
phases['consumer_import']=time.monotonic()-begun
start=time.monotonic()
try:
 begun=time.monotonic()
 from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex,CodebaseScanLimits
 from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
 from ipfs_datasets_py.logic.software_contracts.codebase_source_384 import register_shared_parent
 from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
 from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
 from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
 from ipfs_datasets_py.logic.software_contracts import content
 phases['operation_imports']=time.monotonic()-begun
 for cls,name in [(RepositoryScanner,'scan_snapshot'),(CodebaseCatalog,'_validate_candidate'),(DuckDBASTStore,'apply_batch'),(DuckDBASTStore,'_persist_projection'),(DuckDBASTStore,'_rebuild'),(DuckDBASTStore,'_load'),(RepositoryCodebaseIndex,'load'),(RepositoryCodebaseIndex,'load_ast_artifact')]:timed(cls,name)
 record['producer']=owner._pins()
 output=out/'state';output.mkdir()
 def remaining():
  left=90-(time.monotonic()-start)
  if left<=0:raise TimeoutError('combined diagnostic deadline expired')
  return left
 source_hashes=phase('source_population_validation',lambda:owner._sources(app,source_hashes))
 config_path=Path('/home/barberb/lift_coding/artifacts/terminal-source384-context-20261003/bottle-canary-02/source384-config.json')
 with acquire_codebase_resources(timeout_seconds=min(30,remaining()),memory_mb=6144,cpu_slots=3,child_process_slots=3) as lease, owner._owners(output) as (index,registry):
  phases['owners_and_admission_cumulative']=time.monotonic()-start
  config=phase('config_asset_validation',lambda:owner.load_source384_config(config_path))
  record['selected_checkpoint_sha256']=config['checkpoint_sha256'];record['embedding_revision']=config['embedding_revision']
  head=phase('prepare_current',lambda:index.prepare_current(app,repository_id='public-combined-qualification',operation_id='initial',expected_head=None,limits=CodebaseScanLimits(max_entries=len(source_hashes),max_file_bytes=1024**2),exclusions=['.runtime'],parent_lease=lease,timeout_seconds=remaining(),memory_mb=4096).head)
  record['head']=head.to_dict()
  inventory=phase('consumer_inventory',lambda:owner._inventory(index,head,source_hashes))
  version=phase('register_shared_parent',lambda:register_shared_parent(registry,checkpoint_path=config['checkpoint_path'],expected_sha256=config['checkpoint_sha256']))
  record['version_id']=version
  observation=phase('first_observe_current',lambda:index.observe_current(app,expected_head=head,parent_lease=lease,timeout_seconds=remaining(),memory_mb=4096))
  record['coverage']=observation.manifest.coverage
  remaining();record['status']='passed'
except Exception as exc:
 record.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
finally:
 record['seconds']=time.monotonic()-start
 if 'content' in globals():
  record['encode_cache']=content._memo_encode_digest.cache_info()._asdict();record['validation_cache']=content._memo_validate_cid.cache_info()._asdict()
 (out/'receipt.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
 print(json.dumps(record,sort_keys=True),flush=True)
