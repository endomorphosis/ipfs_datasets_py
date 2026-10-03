from pathlib import Path
import cProfile
import hashlib
import io
import json
import pstats
import time
import sys
import functools
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor

out=Path('/home/barberb/lift_coding/artifacts/source-observation-performance-20261003')
retained=Path('/home/barberb/lift_coding/artifacts/terminal-source384-context-20261003/bottle-canary-02')
state=retained/'state/source384-context'
profile=cProfile.Profile()
record=dict(schema='source-observation-profile@1',database_read_only=True,
    deadline_seconds=90,memory_mb=4096,source_root=str(retained/'app'),
    owner_sha256=hashlib.sha256(Path(__import__('ipfs_datasets_py.logic.software_contracts.codebase_ir',fromlist=['x']).__file__).read_bytes()).hexdigest())
label='observe-before'
from ipfs_datasets_py.logic.software_contracts import content
record['content_sha256']=hashlib.sha256(Path(content.__file__).read_bytes()).hexdigest()
record['production_memo_capacity']=content._CID_MEMO_MAXSIZE
if len(sys.argv)>1 and sys.argv[1]=='production':
    label='observe-production-8192'
elif len(sys.argv)>1:
    from ipfs_datasets_py.logic.software_contracts import content
    capacity=int(sys.argv[1]);label='observe-diagnostic-'+str(capacity)
    content._memo_encode_digest=functools.lru_cache(maxsize=capacity)(content._memo_encode_digest.__wrapped__)
    content._memo_validate_cid=functools.lru_cache(maxsize=capacity)(content._memo_validate_cid.__wrapped__)
    record['diagnostic_memo_capacity_override']=capacity
with duckdb.connect(str(state/'source.duckdb'),read_only=True,config={'threads':1,'memory_limit':'512MB'}) as cx:
    # Diagnostic-only attach avoids the constructor's unconditional CREATE DDL
    # on this already published, read-only database. Lookup code is unchanged.
    store=DuckDBASTStore();store._connection=cx
    record['diagnostic_skip_existing_schema_installation']=True
    cas=ImmutableCAS(state/'source-artifacts')
    index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
    rows=cx.execute('SELECT repository_id FROM codebase_control.heads').fetchall()
    assert len(rows)==1
    head=index.current(rows[0][0]);record['head']=head.to_dict()
    started=time.monotonic()
    try:
        profile.enable()
        observed=index.observe_current(retained/'app',expected_head=head,timeout_seconds=90,memory_mb=4096)
        record.update(status='passed',source_files=len(observed.manifest.snapshot.entries))
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__,error=str(exc))
    finally:
        profile.disable();record['elapsed_seconds']=time.monotonic()-started
        record['encode_memo']=content._memo_encode_digest.cache_info()._asdict()
        record['validate_memo']=content._memo_validate_cid.cache_info()._asdict()
        profile.dump_stats(out/(label+'.prof'))
        report=io.StringIO();pstats.Stats(profile,stream=report).sort_stats('cumulative').print_stats(65)
        (out/(label+'-profile.txt')).write_text(report.getvalue())
        (out/(label+'.json')).write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
print(json.dumps(record,sort_keys=True))
