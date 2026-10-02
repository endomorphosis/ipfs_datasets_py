"""Closed public evidence package; no native databases or scheduler capabilities."""
from pathlib import Path
import hashlib,json,subprocess,xml.etree.ElementTree as ET
ROOT=Path('/home/barberb/lift_coding/artifacts/codebase-obligation-portfolio-native-20261002')
RUN=ROOT/'native-02'
REPOS={'datasets':Path('/tmp/ir-release-datasets-20261001'),'accelerate':Path('/tmp/ir-release-accelerate-20261001')}
DEST=REPOS['datasets']/'docs/software_contracts/evidence/codebase-obligation-portfolio-exact-path-20261002'
assert not DEST.exists()
DEST.mkdir(parents=True)
def sha(data):return hashlib.sha256(data).hexdigest()
def put(path,data):
 target=DEST/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
def value(path,item):put(path,(json.dumps(item,indent=2,sort_keys=True)+'\n').encode())
result=json.loads((RUN/'run-result.json').read_text())
assert result['pytest_exit_code']==0 and all(result[k] is True for k in ('source_pins_unchanged','all_loaded_sources_match_tested_commits','tools_unchanged','portfolio_producers_unchanged'))
xml=ET.parse(RUN/'tests.xml');cases=xml.findall('.//testcase')
assert len(cases)==20 and not any(xml.findall('.//'+k) for k in ('failure','error','skipped'))
for name in ('tests.log','tests.xml','invocation.json','run-result.json','module-source-before.json','module-source-after.json','tools-before.json','tools-after.json','portfolio-producer-before.json','portfolio-producer-after.json','working-source-deltas.json','exact-source-snapshots.json'):
 put(Path('native-02')/name,(RUN/name).read_bytes())
put(Path('run_native_working.py'),(ROOT/'run_native_working.py').read_bytes())
assert sha((ROOT/'run_native_working.py').read_bytes())==json.loads((RUN/'invocation.json').read_text())['runner_sha256']
source_rows=json.loads((RUN/'module-source-after.json').read_text())
for row in source_rows:
 data=subprocess.check_output(['git','-C',str(REPOS[row['repository']]),'show',result['commits'][row['repository']]+':'+row['path']])
 assert len(data)==row['bytes'] and sha(data)==row['sha256'] and row['matches_tested_commit']
 put(Path('tested-sources')/row['repository']/row['path'],data)
deltas=json.loads((RUN/'working-source-deltas.json').read_text())
loaded={(row['repository'],row['path']) for row in source_rows}
for row in deltas:
 data=(RUN/'source-snapshots'/row['repository']/row['path']).read_bytes()
 assert sha(data)==row['sha256']
 put(Path('working-tree-context')/row['repository']/row['path'],data)
 row['imported_by_this_suite']=(row['repository'],row['path']) in loaded
assert not any(row['imported_by_this_suite'] for row in deltas)
records=[];case_copies=[]
for case in sorted((RUN/'native-temp').iterdir()):
 if not case.is_dir() or case.is_symlink() or not (case/'repository').is_dir():continue
 selected=[]
 for name in ('native-two-unit-result.json','last-result.json'):
  if (case/name).is_file():
   record=json.loads((case/name).read_text());selected.append(case/name)
   records.append(dict(case=case.name,path='native-02/cases/'+case.name+'/'+name,status=record['status'],
    final_source_validation=record['final_source_validation'],selected_paths=record['selected_paths'],
    units=[dict(path=u['path'],mathematical_status=u['mathematical_status'],native_attempts={k:v['status'] for k,v in u['native_attempts'].items()},
      finite=u['finite_attempt']['status'],bridge=u['bridge_attempt']['status']) for u in record['units']]))
 for name in ('main.py','second.py','README.txt'):selected.append(case/'repository'/name)
 for family in ('source','structured'):
  for path in sorted((case/'cas'/family).glob('*/*')):
   assert path.is_file() and not path.is_symlink() and path.name.startswith(('bafk','bagu'))
   selected.append(path)
 for path in selected:
  assert path.is_file() and not path.is_symlink()
  put(Path('native-02/cases')/case.name/path.relative_to(case),path.read_bytes())
 case_copies.append(dict(case=case.name,files=len(selected),scope='Authored fixture input files, complete immutable source/structured CAS, and explicit result JSON only. Git internals, DuckDB files, locks and private capabilities excluded.'))
assert len(case_copies)==8 and len(records)==6
positive=next(r for r in records if r['status']=='proved' and len(r['units'])==2)
assert all(u['mathematical_status']=='proved' and u['finite']=='proved' and u['bridge']=='proved' and set(u['native_attempts'].values())=={'proved'} for u in positive['units'])
qualification=dict(schema='codebase-obligation-portfolio-native-qualification/v1',status='qualified_selected_profile',
 qualified=True,criterion='RPI-024 selected captured integer-offset profile; root owns backlog/dependency closure',
 baseline_source_commits=result['commits'],working_source_context=deltas,working_context_scope='These captured deltas were present but not imported by this suite. They are not qualified by this portfolio result; exact-path behavior is qualified separately.',backend_count=6,recorded_family_ids=['lean4','rocq','isabelle_hol','smt_lia','tla_plus'],tests=dict(total=20,passed=20,failed=0,errors=0,skipped=0,pure_controls=12,native_controls=8,
   pytest_seconds=63.78,wall_seconds=result['elapsed_seconds'],test_cases=[dict(name=c.attrib['name'],seconds=float(c.attrib['time'])) for c in cases]),
 native_host=dict(default_shared_authority=True,telemetry_injected=False,policies_weakened=False,maximum_parallel=2,
   concurrent_other_qualifications=True,throughput_comparison=False),
 source_pins=dict(imported_source_records=len(source_rows),unique_loaded_files=len({(r['repository'],r['path']) for r in source_rows}),all_match_tested_commits=True,before_after_unchanged=True,tool_pins_unchanged=True,portfolio_producers_unchanged=True),
 result_records=records,case_artifacts=case_copies,
 fault_injection='Exactly one control alters an actual completed CVC5 verdict to exercise disagreement quarantine. Its other native family attempts remain real. Cancellation and unavailable-kernel controls are explicitly requested conditions, not host telemetry injection.',
 semantic_scope='Captured standalone integer-offset mathematical models; Lean/Rocq/Isabelle kernel checks, Z3/CVC5 candidates, finite TLC stuttering invariant, explicit one-way Lean finite restriction bridge. No arbitrary Python-runtime equivalence, unrestricted logic-family equivalence, task completion, or durable proof-cache promotion.',
 limitations=['Exact builtin integer/scalar/source-capture assumptions remain explicit in retained bundles.',
  'TLC is finite and does not establish liveness; the bridge preserves only its stated restriction.',
  'Direct selected executable/runtime-artifact bytes are pinned; ambient shared libraries and transitive theorem imports remain trusted.',
  'Resource enforcement is sampled rather than a cgroup hard limit. Native receipt is captured before its enclosing pytest fixture exits, and is not a post-exit parent-release receipt.',
  'No holdout/training/model/official Terminal-Bench score or performance comparison is produced.'],
 historical_evidence='../codebase-obligation-portfolio-20261002/qualification.json')
value(Path('qualification.json'),qualification)
readme='''# Native portfolio compatibility after exact-path integration\n\nAll 20 current cases passed again (12 pure, 8 native; zero skips) under the unchanged default shared host scheduler. The joined case checked two independent integer-offset source units with Lean, Rocq, Isabelle, Z3, CVC5 and TLC, then checked the required one-way Lean finite restriction proofs and final source identity.\n\nThe adversarial cases retained unavailable-kernel `unknown`, actual counterexample `refuted`, source-change `invalidated`, optional cancellation, explicit unsupported inventory, wrong-parent refusal, and disagreement `quarantined`. The disagreement test deliberately changes one completed CVC5 verdict; this fault injection is separate from the actual other backend receipts.\n\nThe six native backends emit five distinct family IDs: `lean4`, `rocq`, `isabelle_hol`, `smt_lia` (both Z3 and CVC5), and `tla_plus`.

The qualification covers the declared mathematical integer model and bounded TLC stuttering invariant. It does not prove arbitrary Python runtime behavior, unrestricted logic-family equivalence, task completion, or cache promotion. Native tool launchers and selected artifacts are pinned; ambient libraries and transitive theorem imports remain trusted. Resource enforcement is sampled. Other native qualifications ran concurrently, so the 63.78-second suite time is not a throughput comparison.\n\n`qualification.json` joins the final test population, six result records, exact tested Git commits, 115 distinct imported source snapshots (116 source records, including the explicit test-file binding), and before/after tool/producer checks. Eight case directories preserve authored input files and complete immutable source/structured CAS. Native databases, Git internals, locks and private scheduler capabilities are excluded. Resource receipts were taken inside each fixture before its parent context exited; they are not post-exit release attestations.\n\nEight exact working-tree changes (including cache exact-path selection and the training diagnostic batch fix) are preserved separately under `working-tree-context`. None is imported by this suite; all 115 actually loaded source files still match the baseline commits. This run qualifies fresh portfolio compatibility, not the behavior of those unexecuted changes. Their native tests are separate.

The earlier component smokes and host-refused attempts remain unchanged in [historical evidence](../codebase-obligation-portfolio-20261002/qualification.json). Their missing wrapper pins are not retroactively repaired. The previous successful [native-01 package](../codebase-obligation-portfolio-native-20261002/qualification.json) is also unchanged. The two runs repeat the same 20 cases, so they are not 40 distinct tests.\n'''
put(Path('README.md'),readme.encode())
put(Path('package_evidence.py'),Path(__file__).read_bytes())
files=[]
for path in sorted(DEST.rglob('*')):
 if path.is_file():
  data=path.read_bytes();files.append(dict(path=path.relative_to(DEST).as_posix(),bytes=len(data),sha256=sha(data)))
value(Path('manifest.json'),dict(schema='closed-evidence-files/v1',files=files,total_bytes=sum(f['bytes'] for f in files),
 exclusions=['Native database/WAL/lock files','Git administrative state','Private profile/lifecycle/scheduler capabilities','Unselected artifact directories']))
attrs=REPOS['datasets']/'.gitattributes';line='docs/software_contracts/evidence/codebase-obligation-portfolio-exact-path-20261002/** -whitespace'
text=attrs.read_text()
if line not in text.splitlines():attrs.write_text(text+('' if text.endswith('\n') else '\n')+line+'\n')
print(json.dumps(dict(destination=str(DEST),manifest_sha256=sha((DEST/'manifest.json').read_bytes()),files=len(files),bytes=sum(f['bytes'] for f in files)),indent=2))
