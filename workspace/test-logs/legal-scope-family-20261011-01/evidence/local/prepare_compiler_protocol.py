"""Freeze completed inert preparations and the unchanged native compiler envelope."""
from pathlib import Path
import hashlib,json,os,ast
F=Path(__file__).resolve().parent;PREP=F/'prepared-native-views-v02'
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):return json.loads(Path(p).read_bytes())
s=read(PREP/'preparation-summary.json');assert s['passed'] and s['native_requests_predeclared']==12
m=read(PREP/'native-preparation-manifest.json');assert m['status']=='prepared' and m['target']=='legal' and not m['backend_executed']
t=read(F/'selected-inert-tests-observation-v01.json');assert t['final_errors']==t['final_failures']==0 and t['final_passed']>417
review_names=['native-views-independent-review-v01.json','scope-binding-independent-review-v01.json','preparation-helper-independent-review-v02.json','preparation-result-independent-review-v01.json']
for n in review_names:
 v=read(F/n);assert v['passed'] and v['findings']==[],n
paths=[F/'prepare_compiler_protocol.py',F/'run_native_build.py',F/'bootstrap_inert.py',F/'run_inert_tests.py',F/'selected-inert-tests-observation-v01.json',F/'preparation-execution-v01.log',PREP/'preparation-summary.json',*[F/n for n in review_names],F/'saved-native-views-build-v01.json',F/'statutory-scope-binding-build-v01.json']
paths += [Path(v['path']) for v in s['input_pins']]+[Path(v['path']) for v in s['loaded_producer_pins'].values()]+[Path(v['path']) for v in s['output_pins']]+[Path(v['path']) for v in t['selected_tests']]
paths += [Path(v[k]['path']) for v in t['attempts'] for k in ('log_pin','xml_pin')]
lake=Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake');lean=lake.parent/'lean';prlimit=Path('/usr/bin/prlimit').resolve(strict=True)
for p in (lake,lean,prlimit):assert p.read_bytes()[:4]==b'\x7fELF'
paths += [lake,lean,prlimit]
ast.parse((F/'run_native_build.py').read_text())
v={'schema':'saved-span-native-compiler-execution/v1','scope':'Compile12native parser views of9previously exposed authored predictions; no new inference, registered-family qualification or statutory adjudication',
'bound_file_pins':[pin(p) for p in sorted(set(paths))],'request_file':str(PREP/'native-requests.json'),'prepared_manifest_file':str(PREP/'native-preparation-manifest.json'),'regenerated_file_sha256':m['file_sha256'],
'toolchain':'leanprover/lean4:v4.34.1','lake_executable':str(lake),'lean_executable':str(lean),'prlimit_executable':str(prlimit),'output_directory':str(F/'native-build-v01'),'command':[str(lake),'build','legal'],
'expected_modules':['LegalSourceFamily.Prelude',*[x['module'] for x in m['candidates']],'LegalSourceFamily'],
'declared_denominators':{'development_rows':12,'profiles':2,'attempts':24,'native_requests':12,'tdfol_requests':9,'dcec_requests':3,'temporal_refusals':6,'dcec_qualifier_refusals':6,'full_original_report_rows':96,'statutory_rows':8,'statutory_saved_lanes':2,'real_review_items_pending':8,'human_submissions':0,'semantic_labels':0},
'existing_gate_limits_unchanged':{'timeout_seconds':60,'cpu_seconds':60,'Lean_threads':2,'sampled_tree_rss_bytes':2147483648,'max_output_bytes':262144,'max_input_bytes':8388608,'max_workspace_bytes':134217728},
'existing_version_probe_limits':{'per_probe_timeout_seconds':5,'per_probe_max_output_bytes':16384,'default_workspace_bytes':16777216},
'resource_scope':'Separate pre-existing native compiler gate; no numerical admission or prior guardian cap change',
'sampled_rss_guard_is_not_kernel_aggregate_quota':True,'sampled_workspace_guard_is_not_filesystem_quota':True,'python_network_calls_prohibited':True,'kernel_network_namespace_claimed':False,'generated_project_package_dependencies':[],
'native_internal_child_network_calls_not_audited_by_python':True,'native_ELF_avoids_elan_downloads':True,'model_calls':0,'encoder_calls':0,'optimizer_updates':0,'checkpoint_tensors_opened':False,
'training_or_eval_admission':False,'source_semantics_verified':False,'registry_family_qualified':False,'all_logic_families_supported':False,'unsupported_mixed_batch_already_blocked':True,'requires_independent_protocol_and_driver_review':True}
assert len(v['expected_modules'])==14
with (F/'compiler-execution-protocol-v01.json').open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
print('Protocol frozen; no compiler execution')
