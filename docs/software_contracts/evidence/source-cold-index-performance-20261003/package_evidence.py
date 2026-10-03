from pathlib import Path
import json,hashlib,shutil,xml.etree.ElementTree as ET
BASE=Path('/home/barberb/lift_coding/artifacts/source-cold-index-performance-20261003')
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
DEST=D/'docs/software_contracts/evidence/source-cold-index-performance-20261003'
DEST.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def copy(src,relative):
 target=DEST/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
for name in ['before-01.log','diagnostic32768-01.log','diagnostic32768-stages-01.log','diagnostic32768-stages-02.log','production-stages-01.log','production-cold-observation.log','production-cold-observation.json','targeted-01.log','targeted-01.xml','targeted-02.log','targeted-02.xml','sql-column-parity.json','independent-review.json','profile_cold.py','profile_cold.before.py','profile_cold.diagnostic.py','profile_cold.stage-receipt-bug.py','profile_cold.stages.py','observe_cold.py']:
 copy(BASE/name,name)
for label in ['before-01','diagnostic32768-01','diagnostic32768-stages-02','production-stages-01']:
 copy(BASE/label/'receipt.json',label+'/receipt.json')
 for name in ('profile.txt','profile.prof'):
  if (BASE/label/name).exists():copy(BASE/label/name,label+'/'+name)
copy(BASE/'diagnostic32768-stages-01/read-only-recovery.json','diagnostic32768-stages-01/read-only-recovery.json')
for name in ('content.py','duckdb_ast_store.py'):
 copy(BASE/(name+'.before'),'before/ipfs_datasets_py/logic/software_contracts/'+name)
source_paths=['ipfs_datasets_py/logic/software_contracts/'+name+'.py' for name in ('content','duckdb_ast_store','codebase_ir','duckdb_ingest')]
source_paths += ['ipfs_datasets_py/duckdb_control/codebase_catalog.py']
test_paths=['tests/unit/logic/software_contracts/'+name+'.py' for name in ('test_content_memo','test_content_identity','test_duckdb_ast_store','test_duckdb_ast_store_persistence')]
test_paths += ['tests/unit/duckdb_control/test_codebase_catalog.py','tests/integration/logic/software_contracts/test_codebase_ir.py']
for path in source_paths+test_paths:copy(D/path,'sources/'+path)
freeze={path:sha(D/path) for path in source_paths+test_paths}
(BASE/'frozen-sources.json').write_text(json.dumps(freeze,indent=2,sort_keys=True)+'\n');copy(BASE/'frozen-sources.json','frozen-sources.json')
original=Path('/home/barberb/lift_coding/artifacts/terminal_bench_supervisor/full-integration-20260929/terminal-full-preflight-host-01/state/original-image.json')
copy(original,'public-input/original-image.json')
for name in ('public-inventory-static-audit.json','audit_public_inventory.py'):
 copy(Path('/home/barberb/lift_coding/artifacts/terminal-source384-context-20261003')/name,'public-input/'+name)
copy(Path('/home/barberb/lift_coding/artifacts/source384-docker-qualification-20261003/retry-12gib/docker-01/source384-probe.stdout'),'earlier-docker/source384-probe.stdout')
commands={'schema':'source-cold-index-commands@1','environment':dict(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1'),'profile_runs':[
 {'script':'profile_cold.before.py','arguments':['before-01'],'scope':'cProfile, original8192 production, failed90s before publication'},
 {'script':'profile_cold.diagnostic.py','arguments':['diagnostic32768-01','32768'],'scope':'cProfile, diagnostic cache monkeypatch, failed90s'},
 {'script':'profile_cold.stage-receipt-bug.py','arguments':['diagnostic32768-stages-01','32768','stages'],'scope':'diagnostic native work completed but timer receipt lost; no performance credit'},
 {'script':'profile_cold.stages.py','arguments':['diagnostic32768-stages-02','32768','stages'],'scope':'lightweight stage timers, diagnostic cache monkeypatch'},
 {'script':'profile_cold.py','arguments':['production-stages-01','production','stages'],'scope':'lightweight stage timers, unmodified production owners'},
 {'script':'observe_cold.py','arguments':[],'scope':'separate fresh process native current-source observation, unmodified production owners'}],
 'tests':{'argv':['python','-m','pytest','-q',*test_paths,'--junitxml=targeted-02.xml'],'additional_environment':{'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'},'earlier_collection_error':'targeted-01 named nonexistent test_content.py;0 tests ran; retained log/XML','passed':146,'seconds':42.60}}
(DEST/'commands.json').write_text(json.dumps(commands,indent=2,sort_keys=True)+'\n')
(DEST/'README.md').write_text('''# Full public-source cold indexing: bounded CID reuse and SQL insertion

This package qualifies the changed indexing owners on the retained original
218-file public Bottle checkout. It does not run neural inference, an LLM,
training, a task worker, an official benchmark verifier, or a proof.

The earlier 5-CPU/12-GiB Docker run admitted native START but failed during
Source384 initial context after 137.489 seconds. Its unchanged 90-second
preparation deadline was detected at the AST transaction's before-commit hook.
That Docker failure remains a failure; the current local controls below do not
turn it into a successful container run.

## Current producer results

`production-stages-01/receipt.json` records native cold publication of all 218
files in **55.020 seconds**, under the original 90-second deadline, with one
committed source head and 30 canonical Python AST projections. There is no
cache override in that run. DuckDB uses one thread and a 512-MB buffer limit;
its cooperative resource request is 4,096 MiB. These are admission and buffer
settings, not a peak-RSS or hard elapsed-time guarantee.

`production-cold-observation.json` records a separate fresh-process native
current-source observation in **13.646 seconds**, also under 90 seconds. It
checks the same head, immutable source/AST artifacts, active SQL projections,
and live source. Coverage is 218 captured files, 30 AST-ok Python files,
188 unindexed non-Python files, zero opaque files, 1,225 semantic symbols, and
12,554 semantic edges. Formalized and checked properties both remain zero.

The final targeted suite passed **146 tests in 42.60 seconds**. It covers CID
reference parity, live registration changes, fresh body hashing, bounded
eviction, source/CAS corruption, canonical AST reconstruction, cold database
reopen, source/head publication fences, and transactional rollback. New cases
cross multiple real SQL chunks, fail after the second inserted chunk, fail at
before-commit, and exercise Unicode, NULL/bool values, SQL-looking source text,
and an oversized but already-valid singleton.

## Changed implementation and diagnosis

The fixed pure CID encoding and validation caches now retain at most 32,768
entries each. Source and graph bodies are not cached. All live registration
checks and body hashing remain; populations beyond the bound still evict.

Nine AST fact families now stream into fixed-column parameterized INSERTs of
at most 128 rows and a 256-KiB UTF-8 scalar-parameter target per statement.
A valid larger individual row remains a singleton, preserving the existing
payload contract. Source-derived text never becomes SQL syntax. Shared
revision/file upserts, blob publication, deletion and invalidation ordering,
canonical re-projection, transaction hooks, full rollback, and post-commit
counters are unchanged. `sql-column-parity.json` and the independent review
verify the old and new nine-family column/value/iterator expressions match.

The original 8,192-entry cache was smaller than the 12,554-edge graph. The
first cProfile run failed after 113.004 seconds at the first post-scan deadline
check. A diagnostic 32,768-entry override reduced repeated encoding, but the
heavily instrumented run still failed after 107.605 seconds before SQL writes.
Those profiling failures are not matched performance measurements against the
lightweight runs, and no speedup is inferred from them.

The successful cache-only lightweight diagnostic used an explicit monkeypatch:
51.402 seconds overall, including 10.156 seconds in per-projection SQL
persistence. Current production took 55.020 seconds overall, including 3.035
seconds in SQL persistence. Other work and ambient load differ; the overall
local runtime did not improve in this pair. The SQL phase reduction is a
component observation, not a general scaling or benchmark-speed result.

The first lightweight diagnostic committed a source head but its diagnostic
script tried to render disabled cProfile statistics before writing the timer
receipt. The error, exact script, and read-only recovery inventory are retained;
that attempt receives no timing credit. A corrected fresh attempt follows.
The first test command named a nonexistent file and ran zero tests; its log and
XML precede the corrected 146-pass run. No failed attempt is suppressed.

## Evidence scope and reproducibility

`public-input/original-image.json` names exactly the permitted 218 original
files. The static audit verifies their bytes, modes, UTF-8, function counts,
source-map bounds, and absence of native exclusions. No hidden verifier inputs
were read. The static audit is the earlier source generation pinned inside its
own report. Reproduction requires those original public source bytes and the
recorded local Python/DuckDB dependencies; this package contains their hash
inventory rather than another full benchmark distribution.

The scripts copy only listed public files to fresh isolated repositories and
use normal native owners. Current production has no cache monkeypatch, model
load, training, or provider call. Earlier source snapshots and instrumented
runs remain separate. The 90-second checks are cooperative: an active stage
may finish later, but cannot publish through an expired commit fence. The
full combined supervisor/Source384 context and a new Docker benchmark score
remain outside this component qualification.
''')
copy(Path(__file__),'package_evidence.py')
entries=[dict(path=p.relative_to(DEST).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(DEST.rglob('*')) if p.is_file()]
manifest={'schema':'source-cold-index-performance-evidence@1','files':entries,'bytes':sum(e['bytes'] for e in entries)}
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'directory':str(DEST),'members':len(entries),'bytes':manifest['bytes'],'manifest_sha256':sha(DEST/'manifest.json')},indent=2))
