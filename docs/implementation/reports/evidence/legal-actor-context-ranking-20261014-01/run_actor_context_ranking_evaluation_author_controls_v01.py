"""Run only stdlib source/synthetic controls. Never invoke evaluator mains."""
import sys,os,json,hashlib,importlib.util,unittest,importlib.abc
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/(sys.argv[1] if len(sys.argv)==2 else 'actor-context-ranking-evaluation-author-controls-v01.json')
assert OUTPUT.parent==ROOT and OUTPUT.name.startswith('actor-context-ranking-evaluation-author-controls-') and not OUTPUT.exists()
sys.dont_write_bytecode=True
class DenyNumerical(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'torch','numpy','pandas','scipy','tensorflow','jax','ipfs_datasets_py','huggingface_hub'}:
   raise ImportError('Production/numerical/SDK imports forbidden in detached controls')
sys.meta_path.insert(0,DenyNumerical())
allowed_json={ROOT/'evaluation-contract-v01.json',ROOT/'evaluation-port-plan-v01.json',ROOT/'postfreeze-comparator-inputs-v01.json'}
json_reads=set();writes=[]
def audit(event,args):
 if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {'os.system','os.fork','os.remove','os.rename','os.replace','os.unlink','fcntl.flock','os.kill','os.killpg'}:
  raise AssertionError('No process/network/resource mutation during source controls')
 if event=='open' and isinstance(args[0],(str,bytes)):
  p=Path(os.fsdecode(args[0])).absolute();mode,flags=args[1:3]
  writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
  writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if writing:
   assert p==OUTPUT and isinstance(flags,int) and bool(flags&os.O_EXCL);writes.append(str(p))
  else:
   assert not {'private-runtime-snapshots','resource-snapshots'}&set(p.parts)
   if p.suffix=='.json':
    assert p in allowed_json, 'Saved-result/reference/checkpoint JSON body refused: '+str(p)
    json_reads.add(str(p))
 if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
  assert event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444
sys.addaudithook(audit)
class Result(unittest.TextTestResult):
 def __init__(self,*a,**kw):super().__init__(*a,**kw);self.passed_names=[];self.subtest_checks=0
 def addSuccess(self,test):super().addSuccess(test);self.passed_names.append(test.id())
 def addSubTest(self,test,subtest,err):self.subtest_checks+=1;super().addSubTest(test,subtest,err)
suite=unittest.TestSuite();sources=[]
for name in ['test_actor_context_ranking_analyzer_detached_v01.py','test_actor_context_ranking_recount_detached_v01.py']:
 p=ROOT/name;raw=p.read_bytes();sources.append(dict(path=str(p),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
 spec=importlib.util.spec_from_file_location(p.stem,p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
result=unittest.TextTestRunner(verbosity=1,resultclass=Result).run(suite)
artifact_names=['analyze_actor_context_ranking_v01.py','review_actor_context_ranking_result_recount_v01.py',
 'derive_actor_context_ranking_evaluation_v01.py','derive_actor_context_ranking_evaluation_controls_v01.py',
 'run_actor_context_ranking_evaluation_author_controls_v01.py','evaluation-contract-v01.json','evaluation-port-plan-v01.json','postfreeze-comparator-inputs-v01.json']
artifacts={}
for name in artifact_names:
 p=ROOT/name;raw=p.read_bytes();artifacts[str(p)]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
for p in sources:artifacts[p['path']]={k:p[k] for k in ('bytes','sha256')}
value=dict(schema='actor-context-ranking-evaluation-author-controls/v1',status='SOURCE_ONLY_CANDIDATE_UNQUALIFIED',
 passed=result.wasSuccessful(),findings=[dict(test=str(t),traceback=trace) for t,trace in result.errors+result.failures],
 tests_run=result.testsRun,passed_test_methods=len(result.passed_names),subtest_checks=result.subtest_checks,passed_names=result.passed_names,
 same_author_as_analyzer_and_recounter=True,independent_source_qualification=False,actual_freeze_available=False,
 actual_scoring_calls=0,evaluator_main_calls=0,model_calls=0,numerical_imports=0,SDK_calls=0,resource_API_calls=0,
 checkpoint_JSON_parses=0,saved_head_or_reference_body_reads=0,permitted_public_metadata_JSON_reads=sorted(json_reads),artifacts=artifacts)
raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
with OUTPUT.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
os.chmod(OUTPUT,0o444)
print(json.dumps(dict(path=str(OUTPUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),passed=result.wasSuccessful(),tests=result.testsRun)))
raise SystemExit(0 if result.wasSuccessful() else 1)
