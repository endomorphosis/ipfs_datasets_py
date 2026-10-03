from pathlib import Path
import hashlib,json,shutil,subprocess,xml.etree.ElementTree as ET
B=Path('/home/barberb/lift_coding/artifacts/source-combined-observation-performance-20261003')
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
DEST=D/'docs/software_contracts/evidence/source-combined-observation-performance-20261003'
DEST.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def copy(src,name):
 target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
for name in ['profile_combined.py','profile_manifest.py','run_full_context.py','profile_full_context.py','manifest-components.json','manifest-components.log','memo-retention-diagnostic.json','clone-before-diagnostic.json','native-manifest-json-types.json','frozen-sources.json','independent-review-initial.json','independent-review-final.json','independent-review-equality.json']:
 copy(B/name,name)
for name in ['before-01','after-01','after-02','full-context-01','full-context-02','full-context-stages-03','full-context-04']:
 copy(B/(name+'.log'),name+'.log');copy(B/name/'receipt.json',name+'/receipt.json')
copy(B/'full-context-stages-03/stage-summary.json','full-context-stages-03/stage-summary.json')
for name in ['memo-01','targeted-02','memo-03','targeted-04','targeted-05','comparison-race-06']:
 for ext in ['log','xml']:copy(B/(name+'.'+ext),'tests/'+name+'.'+ext)
for name in ['baseline-sources','candidate64-sources','candidate128-sources','guarded-json-sources','final-sources','targeted-05-sources']:
 for p in sorted((B/name).rglob('*')):
  if p.is_file():copy(p,str(p.relative_to(B)))
for name in ['receipt.json','inference.json']:
 copy(B/'full-context-04/state'/name,'full-context-04/native/'+name)
original=Path('/home/barberb/lift_coding/artifacts/terminal_bench_supervisor/full-integration-20260929/terminal-full-preflight-host-01')
copy(original/'state/original-image.json','public-input/original-image.json')
copy(original/'app/LICENSE','public-input/BOTTLE-LICENSE')
copy(Path('/home/barberb/lift_coding/artifacts/source384-docker-publication-20261003/docker-01/public-instruction.md'),'public-input/instruction.md')
copy(Path('/home/barberb/lift_coding/artifacts/source384-docker-publication-20261003/docker-01/source384-probe.stdout'),'earlier-docker/source384-probe.stdout')
extra=B/'independent-review-final-followup.json'
if extra.exists():copy(extra,extra.name)
r=json.loads((B/'full-context-04/receipt.json').read_text())
commands=dict(schema='source-combined-observation-commands@1',
 environment=dict(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false',PYTHONDONTWRITEBYTECODE='1'),
 stage_diagnostics=[dict(script='profile_combined.py',argument=name) for name in ['before-01','after-01','after-02']],
 full_native=[dict(script='run_full_context.py',argument=name) for name in ['full-context-01','full-context-02','full-context-04']],
 full_diagnostic=dict(script='profile_full_context.py',argument='full-context-stages-03'),
 tests=dict(final_suite=dict(paths=['tests/unit/logic/software_contracts/test_codebase_manifest_memo.py','tests/integration/logic/software_contracts/test_codebase_current.py','tests/integration/logic/software_contracts/test_codebase_ir.py','tests/unit/duckdb_control/test_codebase_catalog.py','tests/unit/logic/software_contracts/test_codebase_ir_untrusted_previous.py'],passed=113,seconds=30.48,xml='tests/targeted-05.xml',memo_test_source='targeted-05-sources/tests/unit/logic/software_contracts/test_codebase_manifest_memo.py'),
 appended_control=dict(path='tests/unit/logic/software_contracts/test_codebase_manifest_memo.py',selection='native_comparison_refuses_producer_drift',passed=1,deselected=38,seconds=0.20,xml='tests/comparison-race-06.xml',source='final-sources/tests/unit/logic/software_contracts/test_codebase_manifest_memo.py')),
 limits=dict(deadline_seconds=90,parent_memory_mb=6144,parent_cpu_slots=3,native_child_memory_mb=4096,duckdb_threads=1,duckdb_memory='512MB',memo_entries=4,memo_retained_representation_bytes=134217728),
 authority=dict(benchmark_result=False,proof_established=False,source_semantics_verified=False,provider_calls=0,training_steps=0))
(DEST/'commands.json').write_text(json.dumps(commands,sort_keys=True,indent=2)+'\n')
(DEST/'README.md').write_text('''# Exact manifest reconstruction reuse and complete Source384 preparation

This package retains the diagnosis, implementation controls, and one successful
local native preparation of the original public Bottle repository. It is not a
Docker qualification or a benchmark score.

## Final native result and its limits

`full-context-04/native/receipt.json` records completed Source384 preparation at
**89.963117 seconds** with the existing **90-second cooperative deadline**.
The outer diagnostic wrapper returned after **90.041305 seconds**, including
cleanup/accounting after the final native deadline check. This is a very thin
margin, not a hard wall-time or peak-memory guarantee. No comfortable scheduling
margin or general speedup is claimed.

The fresh private state captured all **220 permitted files**: the 218 original
public inputs plus the native public instruction and smoke-check sources.
The native worker loaded the real pinned parent once, executed inference, and
completed all four source observations and immutable model/output replay checks.
Coverage inventories 31 Python files and 944 functions: 128 selected units,
127 decoded unverified candidates, one GTE-token deferral, 737 selection-budget
deferrals, and 79 unsupported normalizations. All 127 candidates have
`fail_open_source_contract_unsupported` status. They do not establish correct
formalization, behavioral properties, or proof authority. No provider call,
training, checkpoint promotion, task execution, or official verifier occurred.

The exact native inference output is retained with the context receipt; its
SHA-256 is fd092064dea096ce8ed25fa7a8da64e025982ca8df76a2cdb20deb108841df26.
The private model/CAS databases and checkpoint weights remain outside this
package. Original source distribution is represented by its complete hash
inventory; the public Bottle license accompanies source excerpts in inference.

## What changed

The CodebaseIR owner retains only a pure reconstruction of exact canonical
manifest bytes. Both callers still read, bound, canonicalize and verify their
current CAS object before using it. Current heads, active SQL projections,
source bytes, AST artifacts, model assets, deadlines and authority outcomes are
never memoized. The fixed LRU admits at most four entries and 128 MiB of
accounted retained representation, including serialized keys, owned records
and mapping backing storage. Oversized valid inputs decode uncached. This is
not a process RSS or transient allocation bound.

The key binds the complete serialized manifest, current source/schema/callable
producer identities and live CID registrations. Native bindings are captured
before first use and checked again before returning a hit or admitting a miss.
Custom or unknown producers/registrations use the original uncached behavior.
Private dataclass records are never returned: every caller receives detached
records, including nested symbols, edges, artifacts and snapshot entries.
Only named metadata/signature/annotation/normalized-AST fields may share their
recursively verified immutable JSON containers. Mutable structures and record
objects are excluded from those shared subtrees; to_dict remains detached.

At the existing post-artifact-read catalog boundary, a guarded, recursive,
exact-type comparison may affirm equality without repeatedly serializing
the full semantic graph. It distinguishes bool from int and checks exact
record/container/scalar types. Only the explicitly nonserialized SnapshotEntry
capture bytes and acquisition witness are omitted. Every different, unknown or
custom representation retains the original decoded-to_dict versus current
candidate-to_dict comparison. The candidate is checked after the fresh read,
so mutation during that read remains a rejection.

## Tests and retained generations

The final runtime passed 113 controls in 30.48 seconds, followed by one newly
appended comparison-time producer-drift control in 0.20 seconds. These are
**114 distinct controls across two invocations**, not one 114-test invocation.
The preceding memo-test snapshot is SHA-verified and retained separately;
the final test source only appends the last control. Coverage includes fresh
CAS corruption/removal, cold-process replay, source/head/SQL drift, cancellation
and rollback, byte/entry eviction, oversized uncached parity, exact producer
aliases/defaults/helper changes, live registration races, forced caller-record
mutation, immutable JSON sharing, concurrent replay, type-sensitive comparison,
and candidate mutation during the artifact read.

The initial 15-pass preliminary suite is historical only; its exact source
generation is not reconstructed here. The 94- and 108-pass suites belong to
their retained predecessor source snapshots. The intermediate memo-03 run had four bad test expectations: custom
class aliases can validly reconstruct through the uncached compatibility path;
the requirement is cache bypass, not automatic rejection. All four expectations
were corrected. Its 4-failure/30-pass log/XML remain visible.

The initial full-public Docker run passed publication but expired before the
first inference observation. Its trace is preserved separately. Local
`before-01` ran publication, configuration validation, parent registration and
the first observation in 64.297 seconds; it did not run neural inference.
Two manifest loads accounted for 12.680 seconds. The first 64-MiB memo candidate
did not retain the roughly 89-MB typed representation of the 14.7-MB serialized
manifest, and did not improve that diagnostic. The 128-MiB predecessor
`after-02` completed the same partial diagnostic in 55.507 seconds, with two
loads accounting for 2.659 seconds. These are local component observations,
not a general scaling or full-methodology speed claim.

The first full native attempt expired after 90.192 seconds during its last
source observation. The guarded JSON-sharing successor likewise expired after
90.124 seconds. A lightweight full-phase diagnostic then expired after 90.179
seconds: publication took 50.247 seconds, including 15.996 seconds of catalog
candidate validation; the native worker took 12.198 seconds; each complete
observation took roughly 5.2–5.6 seconds. The final typed comparison targets the
measured duplicate catalog serialization, and the final full native run above
is the separate current-producer result. Every earlier failure remains a
failure. The subsequent Docker result must be evaluated independently.

## Reproduction and evidence

The scripts use isolated private state, the exact permitted public source
population, the selected local parent checkpoint and pinned cached GTE assets.
They contain no download, model training, paid/provider call, or fixture
replacement. Reproduction requires those original inputs and local assets.
`frozen-sources.json` pins final runtime and test snapshots. Earlier snapshots,
commands, logs, XML, timing receipts, reviews, and the complete final native
inference are closed by `manifest.json`.
''')
copy(Path(__file__),'package_evidence.py')
members=[dict(path=p.relative_to(DEST).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(DEST.rglob('*')) if p.is_file()]
manifest=dict(schema='source-combined-observation-performance-evidence@1',files=members,bytes=sum(x['bytes'] for x in members))
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(directory=str(DEST),members=len(members),bytes=manifest['bytes'],manifest_sha256=sha(DEST/'manifest.json')),indent=2))

