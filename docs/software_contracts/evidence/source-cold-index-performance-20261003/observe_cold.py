from pathlib import Path
import sys,json,time,hashlib
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002');sys.path.insert(0,str(D))
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import content
base=Path('/home/barberb/lift_coding/artifacts/source-cold-index-performance-20261003');state=base/'production-stages-01';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
record=dict(schema='full-public-cold-observation@1',fresh_process=True,neural_inference=False,provider_calls=0,training_steps=0,deadline_seconds=90,memory_mb=4096,duckdb_threads=1,duckdb_memory='512MB',production_memo_capacity=content._CID_MEMO_MAXSIZE,script_sha256=sha(Path(__file__)),producer={name:sha(D/('ipfs_datasets_py/logic/software_contracts/'+name+'.py')) for name in ('content','duckdb_ast_store','codebase_ir','duckdb_ingest')})
with duckdb.connect(str(state/'source.duckdb'),config={'threads':1,'memory_limit':'512MB'}) as cx:
 store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(state/'cas');index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas));head=index.current('public-cold-qualification')
 started=time.monotonic()
 try:
  actual=index.observe_current(state/'app',expected_head=head,timeout_seconds=90,memory_mb=4096)
  record.update(status='passed',head=head.to_dict(),source_files=len(actual.manifest.snapshot.entries),semantic_edges=len(actual.manifest.semantic_state.edges),semantic_symbols=len(actual.manifest.semantic_state.symbols),coverage=actual.manifest.coverage)
 except Exception as exc:record.update(status='failed',error_type=type(exc).__name__,error=str(exc))
 record['seconds']=time.monotonic()-started;record['encode_cache']=content._memo_encode_digest.cache_info()._asdict();record['validation_cache']=content._memo_validate_cid.cache_info()._asdict()
(base/'production-cold-observation.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n');print(json.dumps(record,sort_keys=True))
