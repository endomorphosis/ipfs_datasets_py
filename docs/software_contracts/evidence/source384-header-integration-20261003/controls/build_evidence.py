"""Copy a closed, source-free qualification allowlist; no task/model/DB payloads."""
from pathlib import Path
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET

B=Path(__file__).resolve().parent
D=B.parents[1]/'.worktrees/ir-release-datasets-20261002'
E=D/'docs/software_contracts/evidence/source384-header-integration-20261003'
assert not E.exists()
E.mkdir(parents=True)

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def copy(src,rel):
    dst=E/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)

pins=json.loads((B/'draft-pins.json').read_text())
for rel,sha in pins.items():
    source=D/Path(rel).relative_to('proposed')
    assert digest(source)==sha
    copy(source,'final-sources/'+str(source.relative_to(D)))
for stem in ('controls-01','actual-02'):
    tree=ET.parse(B/(stem+'.xml'));cases=tree.findall('.//testcase')
    assert len(cases)==22 and not tree.findall('.//failure') and not tree.findall('.//error') and not tree.findall('.//skipped')
    for ext in ('.xml','.log','-command.json','-exit.json'):copy(B/(stem+ext),'controls/'+stem+ext)
for name in ('run_proposed_tests.py','run_actual_tests.py','draft-pins.json','build_evidence.py'):
    copy(B/name,'controls/'+name)
source_pins={str(p.relative_to(D)):digest(p) for p in (
    D/'ipfs_datasets_py/logic/software_contracts/codebase_header_context.py',
    D/'tests/integration/logic/software_contracts/test_codebase_header_context.py',
    D/'docs/software_contracts/CAPTURED_HEADER_CONTEXT.md')}
qualification=dict(schema='captured-header-integration-qualification@1',
    baseline_git_head='0d6ed4b7d3dfd1935c60a3db414dafb0ad15ffef',
    final_source_pins=source_pins,
    primary={'control_prefix':'controls/actual-02','passed':22,'failed':0,'errors':0,'skipped':0,
             'pytest_seconds':33.29,'process_seconds':35.12026071600121,'on_disk_owner':True,'import_override':False},
    preceding={'control_prefix':'controls/controls-01','passed':22,'pytest_seconds':32.60,
               'new_module_only_bootstrap':True,'same_final_source_bytes':True},
    distinct_test_count=22,
    reviewed_protocol_required=True,
    public_fixture={'sha256':'761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba',
        'provenance':'Existing permitted public-bottle.py in A evidence/terminal-source384-context-20261003/canaries',
        'payload_included':False,'modeled_helpers':2,'deterministic_formula_count':12,'smt_obligation_count':6},
    counters={'model_loads':0,'learned_formula_count':0,'provider_calls':0,'solver_calls':0,'training_steps':0},
    scope={'native_duckdb_cas_catalog':True,'complete_modules':True,'native_source_observations':True,
        'isolated_authored_native_scheduler':True,'injected_host_telemetry':True,'actual_host_pressure_qualification':False,
        'source384_consumer_wired':False,'supervisor_wired':False,'lake_build_run':False,'checkpoint_changed':False,
        'source_executed':False,'source_semantics_verified':False,'proof_authority':False,'current_source_verified':False,
        'new_benchmark_score':False},
    limits={'paths':128,'selected_python_bytes':4194304,'per_module_bytes':2000000,'report_bytes':8388608,
        'default_timeout_seconds':90,'default_memory_mb':512,'cooperative_deadline':True},
    covered=['complete module source maps','unsupported module inventory','cold CAS/catalog reopen',
        'historical replay versus live source drift','receipt/protocol/head/producer tampering',
        'changed captured bodies and report bounds','native catalog advancement during report publication',
        'cancellation and deadline refusal with lease cleanup','native resource refusal as error','exact public Bottle fixture'],
    limits_of_evidence=['Deterministic formulas are conditional models, not learned reconstruction or solved obligations.',
        'Current wrapper records observations at the call; it confers no lasting currentness authority.',
        'Only authored isolated scheduler telemetry is exercised; no full-supervisor resource or benchmark claim.',
        'Earlier syntax-only draft and authoring-shell metadata error are retained locally, not counted as tests.'])
(E/'qualification.json').write_text(json.dumps(qualification,indent=2)+'\n')
(E/'README.md').write_text('''# Captured header adapter qualification

The actual on-disk new D adapter and integration test passed **22/22 controls in
33.29 seconds**, with no skips. The preceding off-tree run passed the same 22
cases in 32.60 seconds using a bootstrap for only the new module. These runs are
22 distinct controls, not 44. Both use the same final source and test bytes.

The exact public Bottle fixture and the authored module each produce two
modeled helpers, 12 deterministic formulas and six SMT obligations. Model loads,
learned formulas, provider calls, solver calls and training steps are zero. No
Lean compilation, solver discharge, source execution, whole-program proof,
checkpoint modification or benchmark score is claimed. The adapter is not yet
wired into Source384 or the supervisor.

Tests use real native DuckDB/CAS/catalog/source-observation owners with an
explicit isolated native scheduler and injected healthy/refusing telemetry.
This qualifies contract handling, not host-default resource admission. Tampering,
source drift, changed catalog head during publication, cancellation, deadline and
native resource failures retain refusal semantics. Unsupported modules remain
visible rather than being silently omitted.

See `qualification.json` for exact generation/claim boundaries and source pins.
`controls/actual-02-*` identifies the actual on-disk run; `controls/controls-01-*`
is the preceding off-tree generation. Control command paths and runner-relative
locations describe the original development machine; the copied runners are
provenance, not relocation-ready installers. A fresh checkout can run the test
normally with `python -m pytest tests/integration/logic/software_contracts/test_codebase_header_context.py`;
set `IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE` to the exact permitted public fixture to
include that optional case. Its expected SHA is pinned in the test and receipt.

The package contains only an explicit file allowlist: producer/test snapshots,
small commands/results/logs, bootstrap scripts and metadata. It contains no raw
benchmark source, model weights, database, CAS tree, authentication data or
runtime archive. The public Bottle source is represented only by its hash and
existing evidence provenance. See the maintained
[usage document](../../CAPTURED_HEADER_CONTEXT.md) for the three API contracts.
''')
manifest={'schema':'captured-header-integration-evidence@1','files':[
    {'path':str(p.relative_to(E)),'bytes':p.stat().st_size,'sha256':digest(p)}
    for p in sorted(E.rglob('*')) if p.is_file()]}
(E/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'manifest_sha256':digest(E/'manifest.json'),'members':len(manifest['files']),
                  'member_bytes':sum(row['bytes'] for row in manifest['files'])},indent=2))
scope=sorted(list(source_pins)+[str(p.relative_to(D)) for p in E.rglob('*') if p.is_file()])
(B/'commit-scope.json').write_text(json.dumps({'repository':str(D),'files':[
    {'path':rel,'sha256':digest(D/rel),'bytes':(D/rel).stat().st_size} for rel in scope]},indent=2)+'\n')
