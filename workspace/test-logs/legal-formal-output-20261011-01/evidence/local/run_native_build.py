"""Execute only the independently reviewed, pinned native compiler pilot."""
from pathlib import Path
import hashlib,json,os,sys
from bootstrap_inert import install,ROOT
F=Path(__file__).resolve().parent
P=F/'compiler-execution-protocol-v01.json'
REVIEW=F/'compiler-protocol-independent-review-v01.json'
def pin(path):
 p=Path(path);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def read(path):return json.loads(Path(path).read_bytes())
plan=read(P);review=read(REVIEW)
assert review['passed'] is True and review['findings']==[]
assert review['protocol_pin']==pin(P) and review['driver_pin']==pin(__file__)
assert plan['schema']=='saved-span-native-compiler-execution/v1'
assert not Path(plan['output_directory']).exists()
for value in plan['bound_file_pins']:assert pin(value['path'])==value
LAKE=plan['lake_executable'];LEAN=plan['lean_executable'];PRLIMIT=plan['prlimit_executable']
allowed=[
 [PRLIMIT,'--core=0:0','--fsize=16777216:16777216','--',LAKE,'--version'],
 [PRLIMIT,'--core=0:0','--fsize=16777216:16777216','--',LEAN,'--version'],
 [PRLIMIT,'--core=0:0','--fsize=134217728:134217728','--cpu=60:60','--',LAKE,'build','legal'],
]
observed=[]
def audit(event,values):
 if event.startswith('socket.') or event=='os.system':raise AssertionError('Python network/system use prohibited')
 if event=='subprocess.Popen':
  executable,argv,cwd,environment=values
  assert len(observed)<3 and executable==PRLIMIT and list(argv)==allowed[len(observed)]
  assert type(environment) is dict and environment.get('HOME') and environment.get('TMPDIR')
  assert Path(cwd).is_dir()
  observed.append({'executable':executable,'argv':list(argv),'cwd':str(cwd)})
install();sys.addaudithook(audit)
from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate
requests=read(plan['request_file'])
prepared=gate.prepare_source_family_legal(requests,toolchain=plan['toolchain'])
gate.validate_preparation(prepared)
assert prepared.to_dict()==read(plan['prepared_manifest_file'])
assert {name:hashlib.sha256(body.encode()).hexdigest() for name,body in prepared.files}==plan['regenerated_file_sha256']
result=gate.build_source_family_legal(requests,toolchain=plan['toolchain'],lake_executable=LAKE,
 timeout_seconds=60,output_directory=plan['output_directory']).to_dict()
for value in plan['bound_file_pins']:assert pin(value['path'])==value
assert len(observed)==3 and result['command']==[LAKE,'build','legal']
assert result['producer_pins']==prepared.to_dict()['producer_pins']
assert result['expected_modules']==plan['expected_modules']
assert result['binary_sha256']=={LAKE:pin(LAKE)['sha256'],LEAN:pin(LEAN)['sha256']}
for k in ('admitted','formalized','source_semantics_verified','proof_authority','all_logic_families_supported','cross_family_equivalence_verified'):assert result[k] is False
passed=bool(result['build_passed'] and result['returncode']==0 and result['manifest_coverage_passed']
 and result['compiled_modules']==plan['expected_modules'] and result['binary_pins_match']
 and not any(result[k] for k in ('timed_out','output_truncated','workspace_limit_exceeded','resource_exhausted','unavailable','cancelled'))
 and result['workspace_cleaned'])
summary={'schema':'saved-span-native-compiler-pilot-result/v1','passed':passed,'findings':[] if passed else ['native compiler gate did not fully pass'],
 'protocol_pin':pin(P),'driver_pin':pin(__file__),'independent_review_pin':pin(REVIEW),
 'development_requests':9,'development_temporal_refusals':3,'compiled_modules':len(result['compiled_modules']),
 'expected_modules':11,'command':result['command'],'returncode':result['returncode'],
 'semantic_accuracy':None,'actual_statutory_semantic_labels':0,'training_or_eval_admission':False,
 'model_calls':0,'encoder_calls':0,'optimizer_updates':0,'observed_native_process_calls':observed,
 'receipt_pin':pin(Path(plan['output_directory'])/'source-family-receipt.json'),
 'output_pins':[pin(p) for p in sorted(Path(plan['output_directory']).rglob('*')) if p.is_file()],
 'python_network_calls_allowed':False,'kernel_network_namespace_claimed':False,
 'sampled_rss_guard_is_not_kernel_aggregate_quota':True,'old_numerical_guardian_caps_unchanged':True}
with (F/'native-build-result-v01.json').open('x') as stream:
 json.dump(summary,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps({k:summary[k] for k in ('passed','development_requests','compiled_modules','expected_modules','returncode','model_calls','semantic_accuracy')}))
assert passed
