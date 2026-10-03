from pathlib import Path
import collections,hashlib,json,os,subprocess,sys,time
B=Path(__file__).resolve().parent
D=B.parents[1]/'.worktrees/ir-release-datasets-20261002'
from ipfs_datasets_py.logic.software_contracts import codebase_ir as owner,cache,codebase_source_units_384 as units
assert Path(owner.__file__).resolve()==D/'ipfs_datasets_py/logic/software_contracts/codebase_ir.py'
assert Path(cache.__file__).resolve()==D/'ipfs_datasets_py/logic/software_contracts/cache.py'
assert owner._manifest_producer_key() is not None
assert str(B.parent/'source384-manifest-combined-replay-20261003') not in os.environ.get('PYTHONPATH','')
import importlib.metadata as metadata
versions={n:metadata.version(n) for n in ('torch','numpy','transformers','sentence-transformers','tokenizers')}
import pytest
u=D/'tests/unit/logic/software_contracts'; i=D/'tests/integration/logic/software_contracts'
args=['-q',*[str(p) for p in (u/'test_codebase_manifest_compaction.py',u/'test_cache.py',u/'test_content_identity.py',u/'test_codebase_manifest_memo.py',u/'test_codebase_manifest_byte_replay.py',D/'tests/unit/duckdb_control/test_codebase_catalog.py',u/'test_codebase_ir_untrusted_previous.py',i/'test_codebase_ir.py',i/'test_codebase_scan_policy.py',i/'test_codebase_source_units_384.py',i/'test_codebase_source384_publication.py',u/'test_codebase_source_units_lifetime.py')], '--junitxml='+str(B/'controls-01.xml')]
paths=[Path(owner.__file__),Path(cache.__file__),Path(units.__file__),Path(__file__),*(Path(v) for v in args if v.endswith('.py'))]
pins={str(p.relative_to(D)) if p.is_relative_to(D) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
env={k:os.environ.get(k) for k in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','NUMEXPR_MAX_THREADS','CUDA_VISIBLE_DEVICES','TOKENIZERS_PARALLELISM','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','CODEBASE384_CHECKPOINT','CODEBASE384_EMBEDDING_SNAPSHOT','CODEBASE384_LAKE')}
(B/'controls-01-command.json').write_text(json.dumps(dict(command=[sys.executable,str(Path(__file__))],cwd=str(Path.cwd()),pytest_args=args,environment=env,versions=versions,pins=pins,actual_on_disk_sources=True,overlay_used=False,native_producer_recognized=True),indent=2)+'\n')
start=time.monotonic();code=int(pytest.main(args))
post={str(p.relative_to(D)) if p.is_relative_to(D) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(B/'controls-01-exit.json').write_text(json.dumps(dict(exit_code=code,seconds=time.monotonic()-start,pins_after=post,pins_unchanged=post==pins),indent=2)+'\n')
raise SystemExit(code)
