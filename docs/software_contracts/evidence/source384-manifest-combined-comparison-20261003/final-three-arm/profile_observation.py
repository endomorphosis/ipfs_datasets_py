"""Bounded native observations on a fresh copy; no inference or allocator edits."""
from pathlib import Path
import argparse,functools,hashlib,importlib.abc,importlib.util,json,os,resource,shutil,signal,stat,sys,time,traceback,tracemalloc
args_parser=argparse.ArgumentParser()
args_parser.add_argument('--label',required=True)
args_parser.add_argument('--candidate-owner',type=Path)
args_parser.add_argument('--candidate-owner-sha256')
args_parser.add_argument('--candidate-cache',type=Path)
args_parser.add_argument('--candidate-cache-sha256')
args_parser.add_argument('--verify-import-only',action='store_true')
args_parser.add_argument('--replay-shape',choices=('same_connection',),required=True)
args=args_parser.parse_args()
if args.label not in ('baseline-01','byte-only-01','combined-01'):
 raise ValueError('closed comparison label required')
selected_args=(args.candidate_owner,args.candidate_owner_sha256,args.candidate_cache,args.candidate_cache_sha256)
if any(selected_args) and not all(selected_args):
 raise ValueError('both candidate module paths and SHA256 pins must be supplied together')
if (args.label != 'baseline-01') != bool(args.candidate_owner):
 raise ValueError('arm label must match explicit candidate selection')
observation_count=2
OWNER_NAME='ipfs_datasets_py.logic.software_contracts.codebase_ir'
CACHE_NAME='ipfs_datasets_py.logic.software_contracts.cache'
if any(name in sys.modules for name in (OWNER_NAME,CACHE_NAME)):
 raise ValueError('owners must not have been imported before selection')
selected_modules={OWNER_NAME:(args.candidate_owner,args.candidate_owner_sha256),
 CACHE_NAME:(args.candidate_cache,args.candidate_cache_sha256)} if args.candidate_owner else {}
class PinnedOwnerLoader(importlib.abc.Loader):
 def __init__(self,source,raw):self.source,self.raw=source,raw
 def create_module(self,spec):return None
 def exec_module(self,module):exec(compile(self.raw,str(self.source),'exec'),module.__dict__)
class PinnedOwnerFinder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname not in selected_modules:return None
  source,pin=selected_modules[fullname]
  mode=source.lstat().st_mode
  if not stat.S_ISREG(mode) or source.is_symlink() or source.resolve()!=source:
   raise ValueError('candidate must be a canonical regular source file')
  if source.stat().st_size>262144:raise ValueError('candidate source size bound exceeded')
  with source.open('rb') as stream:raw=stream.read(262145)
  if len(raw)>262144:raise ValueError('candidate source read bound exceeded')
  if hashlib.sha256(raw).hexdigest()!=pin:
   raise ValueError('candidate source hash changed')
  return importlib.util.spec_from_file_location(fullname,source,loader=PinnedOwnerLoader(source,raw))
owner_finder=PinnedOwnerFinder() if args.candidate_owner else None
if owner_finder:sys.meta_path.insert(0,owner_finder)
W=Path('/home/barberb/lift_coding');D=W/'.worktrees/ir-release-datasets-20261002'
sys.path.insert(0,str(D))
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog,CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_ir as owner
if owner_finder:
 sys.meta_path.remove(owner_finder)
 for name,(path,pin) in selected_modules.items():
  assert Path(sys.modules[name].__file__)==path
  assert hashlib.sha256(path.read_bytes()).hexdigest()==pin
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources

if args.verify_import_only:
 key=owner._manifest_producer_key()
 if key is None:raise ValueError('selected owner native producer guard refused')
 print(json.dumps(dict(schema='pinned-native-owner-import@1',owner_path=owner.__file__,
  owner_sha256=hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest(),
  cache_path=sys.modules[CACHE_NAME].__file__,
  cache_sha256=hashlib.sha256(Path(sys.modules[CACHE_NAME].__file__).read_bytes()).hexdigest(),
  owner_module=owner.__name__,native_producer_guard_recognized=True,
  overlay_selected=bool(owner_finder),native_observations=0,model_loads=0)))
 raise SystemExit(0)

B=Path(__file__).parent;retained=W/'artifacts/source-combined-observation-performance-20261003/full-context-04/state'
out=B/args.label;out.mkdir();source_db=retained/'source.duckdb';source_cas=retained/'source-artifacts'
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for raw in iter(lambda:stream.read(1024**2),b''):h.update(raw)
 return h.hexdigest()
def cas_pins(root):return {str(p.relative_to(root)):dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(root.rglob('*')) if p.is_file()}
def dump(name,value):
 (out/name).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
receipt=json.loads((retained/'receipt.json').read_text());head=CodebaseHead.from_dict(receipt['source_head']);repository=Path(receipt['repository'])
producer={name:digest(D/name) for name in (
 'ipfs_datasets_py/logic/software_contracts/codebase_ir.py',
 'ipfs_datasets_py/logic/software_contracts/cache.py',
 'ipfs_datasets_py/logic/software_contracts/duckdb_ast_store.py',
 'ipfs_datasets_py/logic/software_contracts/duckdb_ingest.py',
 'ipfs_datasets_py/logic/software_contracts/content.py',
 'ipfs_datasets_py/duckdb_control/codebase_catalog.py')}
before=dict(source_db_sha256=digest(source_db),cas=cas_pins(source_cas),source_hashes={n:digest(repository/n) for n in receipt['source_hashes']})
assert before['source_hashes']==receipt['source_hashes']
assert not source_db.with_suffix('.duckdb.wal').exists()
shutil.copy2(source_db,out/'source.duckdb')
assert digest(out/'source.duckdb')==before['source_db_sha256']
# Catalog records the absolute immutable CAS root; preserve that binding and
# call only read APIs, with complete before/after body hashes.
traced=False
if traced:tracemalloc.start(1)
record=dict(schema='native-manifest-combined-comparison@1',arm=args.label,owner_module=OWNER_NAME,owner_path=str(Path(owner.__file__)),owner_sha256=digest(Path(owner.__file__)),overlay_selected=bool(owner_finder),diagnostic_only=True,provider_calls=0,model_loads=0,training_steps=0,
 original_state=str(retained),repository=str(repository),head=head.to_dict(),source_files=len(before['source_hashes']),
 cas_bytes=sum(row['bytes'] for row in before['cas'].values()),threads=1,memory_limit='512MB',native_observation_seconds=90,observation_count=observation_count,reopen_source_owners_after_first=(observation_count==3),replay_shape=args.replay_shape,
 tracemalloc=traced,gc_collect_called=False,malloc_trim_called=False,scheduler_policy_changed=False,producer_before=producer,
 script_sha256=digest(Path(__file__)),duckdb_version=duckdb.__version__,retained_before=before,rounds=[])
record['selected_producer_before']={name:dict(path=sys.modules[name].__file__,sha256=digest(Path(sys.modules[name].__file__)))
 for name in (OWNER_NAME,CACHE_NAME)}
stream=(out/'events.jsonl').open('x',buffering=1);begun=time.monotonic();cx=None;events=0;restores=[]
def snapshot(stage,phase):
 global events
 if events>=600:raise ValueError('allocation event count bound exceeded')
 def bounded(path):
  with Path(path).open('rb') as f:raw=f.read(32769)
  if len(raw)>32768:raise ValueError('bounded proc record required')
  return raw.decode()
 status={}
 for line in bounded('/proc/self/status').splitlines():
  if line.startswith(('VmRSS:','RssAnon:','RssFile:','VmHWM:','VmSize:')):
   k,v=line.split(':',1);status[k]=int(v.split()[0])*1024
 smaps={}
 for line in bounded('/proc/self/smaps_rollup').splitlines():
  if line.startswith(('Rss:','Pss:','Pss_Anon:','Pss_File:','Private_Dirty:','Private_Clean:','Anonymous:')):
   k,v=line.split(':',1);smaps[k]=int(v.split()[0])*1024
 sql=[]
 if cx is not None:
  sql=[dict(tag=r[0],memory_usage_bytes=r[1],temporary_storage_bytes=r[2]) for r in cx.execute('SELECT * FROM duckdb_memory()').fetchall()]
 memos=dict(owner._MANIFEST_MEMO_STATS,entries=len(owner._MANIFEST_MEMO),retained_bytes=owner._MANIFEST_MEMO_SIZE)
 value=dict(stage=stage,phase=phase,elapsed_seconds=time.monotonic()-begun,process=status,smaps=smaps,
  duckdb_memory=sql,manifest_memo=memos,allocated_python_blocks=sys.getallocatedblocks())
 if traced:value['tracemalloc']=dict(zip(('current','peak'),tracemalloc.get_traced_memory()))
 raw=json.dumps(value,sort_keys=True,allow_nan=False)+'\n'
 if len(raw.encode())>32768:raise ValueError('allocation event bytes bound exceeded')
 stream.write(raw);events+=1

def wrap(cls,name):
 original=getattr(cls,name)
 @functools.wraps(original)
 def wrapped(*args,**kwargs):
  selected=name in ('load','current') or (len(args)>2 and str(args[2]).endswith('.py'))
  if selected:snapshot(name,'enter')
  try:result=original(*args,**kwargs)
  except BaseException:
   if selected:
    try:snapshot(name,'error')
    except BaseException:pass
   raise
  if selected:snapshot(name,'return')
  return result
 setattr(cls,name,wrapped);restores.append((cls,name,original))

def expire(*args):raise TimeoutError('bounded allocation diagnostic expired')
signal.signal(signal.SIGALRM,expire);signal.setitimer(signal.ITIMER_REAL,200)
try:
 snapshot('process','before_connection')
 cx=duckdb.connect(str(out/'source.duckdb'),config={'threads':1,'memory_limit':'512MB'})
 store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(source_cas)
 index=owner.RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
 assert index.current(head.repository_id)==head
 snapshot('owners','open')
 key=owner._manifest_producer_key();assert key is not None
 for name in ('load','lookup','load_ast_artifact','current'):wrap(owner.RepositoryCodebaseIndex,name)
 assert owner._manifest_producer_key()==key
 with acquire_codebase_resources(memory_mb=6144,cpu_slots=3,child_process_slots=3,timeout_seconds=30) as parent:
  for number in range(observation_count):
   snapshot('observation'+str(number),'enter');t=time.monotonic()
   observed=index.observe_current(repository,expected_head=head,parent_lease=parent,timeout_seconds=90,memory_mb=4096)
   assert observed.head==head
   snapshot('observation'+str(number),'returned');record['rounds'].append(dict(number=number,seconds=time.monotonic()-t))
   if number==observation_count-1:
    # Explicit output parity is measured after all observation-return samples,
    # so its serialization allocations do not contaminate those boundaries.
    from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes
    canonical_output=canonical_dag_json_bytes(observed.manifest.to_dict())
    record['returned_manifest_canonical_sha256']=hashlib.sha256(canonical_output).hexdigest()
    record['returned_manifest_canonical_bytes']=len(canonical_output)
    record['returned_manifest_cid']=observed.manifest.cid
    assert record['returned_manifest_cid']==head.manifest_cid
    del canonical_output;snapshot('canonical_output_parity','return')
   del observed;snapshot('observation'+str(number),'reference_deleted')
 assert owner._manifest_producer_key()==key
 record['status']='passed'
 record['native_producer_guard_recognized']=True
except BaseException as exc:
 record.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
finally:
 for cls,name,original in reversed(restores):setattr(cls,name,original)
 try:
  if cx is not None:
   try:snapshot('source_connection','before_close')
   except BaseException as exc:record.setdefault('diagnostic_errors',[]).append(dict(stage='before_close',error_type=type(exc).__name__))
   try:cx.close()
   finally:cx=None;signal.setitimer(signal.ITIMER_REAL,0)
   try:snapshot('source_connection','after_close')
   except BaseException as exc:record.setdefault('diagnostic_errors',[]).append(dict(stage='after_close',error_type=type(exc).__name__))
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);stream.close()
 record.update(seconds=time.monotonic()-begun,event_count=events,producer_after={n:digest(D/n) for n in producer})
 record['owner_unchanged']=digest(Path(owner.__file__))==record['owner_sha256']
 record['selected_producer_after']={name:dict(path=sys.modules[name].__file__,sha256=digest(Path(sys.modules[name].__file__)))
  for name in (OWNER_NAME,CACHE_NAME)}
 record['owner_unchanged']=record['owner_unchanged'] and record['selected_producer_after']==record['selected_producer_before']
 record['retained_unchanged']=digest(source_db)==before['source_db_sha256'] and cas_pins(source_cas)==before['cas'] and all(digest(repository/n)==h for n,h in before['source_hashes'].items())
 stream.close();record['events_sha256']=digest(out/'events.jsonl');dump('receipt.json',record)
 if traced:
  samples=tracemalloc.take_snapshot().statistics('lineno')[:40]
  dump('python-top-allocations.json',[dict(location=str(s.traceback),size_bytes=s.size,count=s.count) for s in samples]);tracemalloc.stop()
 print(json.dumps({k:record[k] for k in ('status','seconds','rounds','event_count','retained_unchanged')}))

raise SystemExit(0 if record.get('status')=='passed' and record.get('retained_unchanged') and record.get('owner_unchanged') else 1)
