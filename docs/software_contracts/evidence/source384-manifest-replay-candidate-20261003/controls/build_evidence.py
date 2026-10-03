from pathlib import Path
import hashlib,json,shutil,xml.etree.ElementTree as ET
B=Path(__file__).resolve().parent;W=B.parents[1];D=W/'.worktrees/ir-release-datasets-20261002'
P=D/'docs/software_contracts/evidence/source384-manifest-replay-candidate-20261003'
P.mkdir(parents=True,exist_ok=True)
def copy(src,dst):
 src=Path(src);dst=P/dst;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
for label in ('controls-01','controls-02','controls-03'):
 for suffix in ('-command.json','-exit.json','.log','.xml'):
  copy(B/(label+suffix),'controls/'+label+suffix)
for name in ('run_controls.py','run_controls_02.py','run_source_controls_03.py','configured_client_plugin.py','build_evidence.py'):
 copy(B/name,'controls/'+name)
for p in (B/'sources').rglob('*.py'):
 if p.name.startswith('test_'):copy(p,Path('before-test-import-fix')/p.relative_to(B/'sources'))
pins=json.loads((B/'source-pins.json').read_text())
for relative in pins:copy(D/relative,Path('final-sources')/relative)
final={relative:hashlib.sha256((D/relative).read_bytes()).hexdigest() for relative in pins}
(P/'final-source-pins.json').write_text(json.dumps(final,indent=2)+'\n')
copy(B.parent/'source384-manifest-combined-replay-20261003/independent-review.json','reviews/off-tree-source-review.json')
copy(B.parent/'source384-manifest-combined-replay-20261003/qualification.json','references/off-tree-qualification.json')
copy(B.parent/'source384-manifest-combined-replay-20261003/controls-01-runtime-diagnosis.json','references/off-tree-runtime-diagnosis.json')
for name in ('controls-02-scheduler-diagnosis.json','controls-03-configured-client-before.json','controls-03-configured-client-after.json'):
 copy(B/name,'controls/'+name)
rows={};runs=[]
for label in ('controls-02','controls-03'):
 r=ET.parse(B/(label+'.xml')).getroot();cases=r.findall('.//testcase')
 for c in cases:
  rows[(c.get('classname').rsplit('.',1)[-1],c.get('name'))]=not any(c.find(k) is not None for k in ('failure','error','skipped'))
 end=json.loads((B/(label+'-exit.json')).read_text());assert end['pins_unchanged']
 runs.append(dict(label=label,tests=len(cases),passed=sum(not any(c.find(k) is not None for k in ('failure','error','skipped')) for c in cases),process_seconds=end['seconds'],exit_code=end['exit_code']))
assert len(rows)==273 and all(rows.values())
comparison=D/'docs/software_contracts/evidence/source384-manifest-combined-comparison-20261003/manifest.json'
q=dict(schema='source384-manifest-replay-local-candidate@1',status='actual_source_configured_client_controls_passed_pending_full_pipeline',distinct_controls=273,final_unresolved_failures=0,skips=0,runs=runs,actual_sources=True,overlay=False,native_producer_recognized=True,source_pins=final,retained_failures=[dict(label='controls-01',collected_test_errors=2,tests_executed=0,reason='Two authored tests used bare sibling fixture imports. The off-tree runner supplied that directory on sys.path; native repository importlib pytest mode did not. Only these two imports were changed to the package-qualified test path before controls-02; runtime owners were unchanged.'),dict(label='controls-02',passed=266,fixture_errors=7,reason='The existing shared ledger had an active foreign daemon with4CPU/9830MiB policy, while host-default startup requested16CPU/99688MiB. Native configuration fencing correctly refused. Retry selected the exact existing profile via canonical get_global_resource_scheduler(config), at the consumer dependency in an external test plugin, and passed all7 cases on the same ledger with native sampler. No state reset, new ledger, capacity/headroom/pressure change, or daemon modification occurred.')],scope='Canonical public CAS/CID/cache/manifest/source/catalog controls plus actual offline384D checkpoint inference/publication/cold replay, and six source-report lifetime controls.',actual_inference_fixture=dict(model_loads=1,decoded_unverified_candidates=4,token_deferred_units=1,provider_calls=0,training_steps=0,source_executed=False,proof_authority=False,admission='configured_client_existing_shared_profile',host_default_startup_qualified=False),comparison_package=dict(path=str(comparison.relative_to(D)),manifest_sha256=hashlib.sha256(comparison.read_bytes()).hexdigest()),limitations=['Local unpublished candidate qualification; no new Docker or full-supervisor run is qualified by this package.','Configured-client actual inference shares the existing native ledger/policy and does not qualify host-default startup under the foreign active profile.','Source-only three-arm measurement lowers accounted memo bytes and warm allocation spikes, but does not show lower anonymous RSS at the second observation return.','Source/report lifetime cleanup is a separate owner change; source-only timing did not exercise its full consumer path.','Checks preserve current source/head/SQL/AST/read/registry fences, scheduler reservations, deadlines, immutable expected source/model identities, and candidate non-authority.'])
(P/'qualification.json').write_text(json.dumps(q,indent=2,sort_keys=True)+'\n')
print(json.dumps(dict(member_count=len([p for p in P.rglob('*') if p.is_file()]),qualification_sha256=hashlib.sha256((P/'qualification.json').read_bytes()).hexdigest())))
