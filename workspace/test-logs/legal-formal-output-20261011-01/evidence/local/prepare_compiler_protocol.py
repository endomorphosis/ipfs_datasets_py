"""Pin the completed inert preparation and unchanged native compiler envelope."""
from pathlib import Path
import hashlib,json,os,ast
F=Path(__file__).resolve().parent;D=F/'datasets';PREP=F/'prepared-pilot-v01'
def pin(path):
 p=Path(path);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def read(path):return json.loads(Path(path).read_bytes())
summary=read(PREP/'preparation-summary.json');assert summary['passed'] and summary['native_requests_predeclared']==9 and summary['temporal_refused']==3
manifest=read(PREP/'native-preparation-manifest.json');assert manifest['status']=='prepared' and manifest['target']=='legal' and manifest['backend_executed'] is False
tests=read(F/'selected-inert-tests-observation-v01.json');assert tests['final_passed']==417 and tests['final_skipped']==2 and tests['final_errors']==tests['final_failures']==0
review_names=['intake-independent-review-v01.json','family-adapter-independent-review-v01.json','statutory-preflight-independent-review-v01.json','development-fixture-independent-review-v02.json','inert-test-harness-independent-review-v01.json']
for name in review_names:
 value=read(F/name);assert value['passed'] is True and value['findings']==[],name
paths=[F/'prepare_compiler_protocol.py',F/'run_native_build.py',F/'bootstrap_inert.py',F/'run_inert_tests.py',F/'selected-inert-tests-observation-v01.json',F/'preparation-observation-v01.json',F/'preparation-execution-v01.log',PREP/'preparation-summary.json',*[F/n for n in review_names],F/'saved-span-family-adapter-build-v01.json',F/'statutory-declaration-preflight-build-v01.json']
paths += [Path(v['path']) for v in summary['input_pins']]+[Path(v['path']) for v in summary['loaded_producer_pins'].values()]+[Path(v['path']) for v in summary['output_pins']]+[Path(v['path']) for v in tests['selected_tests']]
paths += [Path(v[k]['path']) for v in tests['attempts'] for k in ('log_pin','xml_pin')]
lake=Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake');lean=lake.parent/'lean';prlimit=Path('/usr/bin/prlimit').resolve(strict=True)
for p in (lake,lean,prlimit):assert p.read_bytes()[:4]==b'\x7fELF'
paths += [lake,lean,prlimit]
ast.parse((F/'run_native_build.py').read_text())
value={'schema':'saved-span-native-compiler-execution/v1','scope':'Compile nine exposed authored saved-prediction interpretations only; no new inference or statutory adjudication',
 'bound_file_pins':[pin(p) for p in sorted(set(paths))],'request_file':str(PREP/'native-requests.json'),
 'prepared_manifest_file':str(PREP/'native-preparation-manifest.json'),'regenerated_file_sha256':manifest['file_sha256'],
 'toolchain':'leanprover/lean4:v4.34.1','lake_executable':str(lake),'lean_executable':str(lean),'prlimit_executable':str(prlimit),
 'output_directory':str(F/'native-build-v01'),'command':[str(lake),'build','legal'],
 'expected_modules':['LegalSourceFamily.Prelude',*[v['module'] for v in manifest['candidates']],'LegalSourceFamily'],
 'declared_denominators':{'development_requested':12,'native_requested':9,'temporal_refused':3,'full_original_report_rows':96,'statutory_rows':8,'statutory_saved_lanes':2,'real_review_items_pending':8,'human_submissions':0,'semantic_labels':0},
 'existing_gate_limits_unchanged':{'timeout_seconds':60,'cpu_seconds':60,'Lean_threads':2,'sampled_tree_rss_bytes':2147483648,'max_output_bytes':262144,'max_input_bytes':8388608,'max_workspace_bytes':134217728},
 'existing_version_probe_limits':{'per_probe_timeout_seconds':5,'per_probe_max_output_bytes':16384,'default_workspace_bytes':16777216},
 'resource_scope':'Separate pre-existing native compiler gate; no numerical admission or prior guardian cap change',
 'sampled_rss_guard_is_not_kernel_aggregate_quota':True,'sampled_workspace_guard_is_not_filesystem_quota':True,
 'python_network_calls_prohibited':True,'kernel_network_namespace_claimed':False,'generated_project_package_dependencies':[],
 'native_internal_child_network_calls_not_audited_by_python':True,'native_ELF_avoids_elan_downloads':True,
 'model_calls':0,'encoder_calls':0,'optimizer_updates':0,'checkpoint_tensors_opened':False,
 'training_or_eval_admission':False,'source_semantics_verified':False,'all_logic_families_supported':False,
 'unsupported_mixed_batch_already_blocked':True,'requires_independent_protocol_and_driver_review':True}
with (F/'compiler-execution-protocol-v01.json').open('x') as stream:
 json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print('Pinned protocol prepared without compiler execution')
