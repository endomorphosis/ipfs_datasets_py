from pathlib import Path
import os,sys,json,hashlib,time,shutil,subprocess,cProfile,pstats,io,traceback
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002');sys.path.insert(0,str(D))
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex,CodebaseScanLimits
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import content
BASE=Path('/home/barberb/lift_coding/artifacts/source-cold-index-performance-20261003')
label=sys.argv[1];out=BASE/label;out.mkdir();app=out/'app';app.mkdir()
original=Path('/home/barberb/lift_coding/artifacts/terminal_bench_supervisor/full-integration-20260929/terminal-full-preflight-host-01')
raw=(original/'state/original-image.json').read_bytes();allowed=json.loads(raw)['sources'];sha=lambda raw:hashlib.sha256(raw).hexdigest()
for name,meta in allowed.items():
 src=original/'app'/name;body=src.read_bytes();assert sha(body)==meta['sha256']
 dst=app/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(body);dst.chmod(0o755 if meta['executable'] else 0o644)
for args in [('init','-q'),('add','.'),('-c','user.name=Qualification','-c','user.email=qualification@localhost','commit','-qm','Captured public source')]:
 subprocess.run(['git','-C',str(app),*args],check=True,capture_output=True)
modules=['codebase_ir','duckdb_ast_store','duckdb_ingest','content']
record=dict(schema='full-public-cold-index-profile@1',label=label,instrumented=True,source_files=len(allowed),source_receipt_sha256=sha(raw),source_root=str(app),threads=1,duckdb_memory='512MB',deadline_seconds=90,memory_mb=4096,provider_calls=0,model_loads=0,training_steps=0,
 producer={name:sha((D/('ipfs_datasets_py/logic/software_contracts/'+name+'.py')).read_bytes()) for name in modules},script_sha256=sha(Path(__file__).read_bytes()))
profile=cProfile.Profile()
if len(sys.argv)>2:
 import functools
 capacity=int(sys.argv[2]);record['diagnostic_memo_capacity_override']=capacity
 content._memo_encode_digest=functools.lru_cache(maxsize=capacity)(content._memo_encode_digest.__wrapped__)
 content._memo_validate_cid=functools.lru_cache(maxsize=capacity)(content._memo_validate_cid.__wrapped__)
with duckdb.connect(str(out/'source.duckdb'),config={'threads':1,'memory_limit':'512MB'}) as cx:
 store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(out/'cas');index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
 start=time.monotonic()
 try:
  profile.enable()
  published=index.prepare_current(app,repository_id='public-cold-qualification',operation_id='initial',expected_head=None,limits=CodebaseScanLimits(max_entries=len(allowed),max_file_bytes=1024**2),exclusions=['.runtime'],timeout_seconds=90,memory_mb=4096)
  record.update(status='passed',head=published.head.to_dict())
 except Exception as exc:
  record.update(status='failed',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
 finally:
  profile.disable();record['seconds']=time.monotonic()-start
  record['encode_cache']=content._memo_encode_digest.cache_info()._asdict();record['validation_cache']=content._memo_validate_cid.cache_info()._asdict()
  record['head_count']=cx.execute('select count(*) from codebase_control.heads').fetchone()[0]
  record['ast_blobs_count']=cx.execute('select count(*) from ast_blobs').fetchone()[0]
  profile.dump_stats(out/'profile.prof');s=io.StringIO();pstats.Stats(profile,stream=s).sort_stats('cumulative').print_stats(90);(out/'profile.txt').write_text(s.getvalue())
  (out/'receipt.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
print(json.dumps(record,sort_keys=True))
