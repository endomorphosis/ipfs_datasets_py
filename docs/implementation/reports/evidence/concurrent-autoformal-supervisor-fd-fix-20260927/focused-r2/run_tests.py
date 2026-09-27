from pathlib import Path
import os,sys,resource,json,time,socket,hashlib
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'test-source'
FIXTURE=Path(json.loads((HERE/'fixture-ownership.json').read_text())['path'])
DATASETS=Path('/home/barberb/lift_coding/external/ipfs_datasets')
for key in ('GIT_INDEX_FILE','GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES'):
 os.environ.pop(key,None)
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
 os.environ[key]='1'
os.environ.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+os.pathsep+str(DATASETS),CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR=str(FIXTURE/'orchestration'),AUTONOMY_RECOVERY_LEASE_PATH=str(FIXTURE/'recovery.json'),TMPDIR=str(FIXTURE))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:2]))
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT),str(DATASETS)]
def network_denied(*args,**kwargs):raise RuntimeError('network denied in focused offline unit tests')
socket.socket.connect=network_denied
socket.socket.connect_ex=network_denied
import pytest
class Fixtures:
 @pytest.fixture(autouse=True)
 def isolated_state(self,tmp_path,monkeypatch):
  monkeypatch.setenv('IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR',str(tmp_path/'orchestration'))
  monkeypatch.setenv('AUTONOMY_RECOVERY_LEASE_PATH',str(tmp_path/'recovery.json'))
selection={
 'test_agent_supervisor_project_dependency_preflight.py':[
  'test_dependency_probe_output_is_bounded_while_child_is_running',
  'test_dependency_probe_uses_inherited_sealed_fd_when_parent_is_non_dumpable',
  'test_dependency_probe_reads_source_from_sealed_memfd_zip'],
 'test_agent_supervisor_validation_scheduler.py':[
  'test_validation_runtime_seals_nested_python_launcher_and_cleans_descriptor',
  'test_validation_runner_uses_only_inherited_sealed_fds_when_parent_is_non_dumpable',
  'test_daemon_routes_reviewed_python_m_ruff_spellings_to_sealed_binary',
  'test_daemon_rejects_noncanonical_combined_python_ruff_option',
  'test_nested_child_cannot_replace_sealed_ruff_through_environment',
  'test_daemon_classifies_child_launcher_exec_denial_as_infrastructure']}
manifest=json.loads((HERE/'manifest.json').read_text())
for item in manifest['files']:
 assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['after_sha256']
started=time.monotonic()
args=['-q','--noconftest','--import-mode=importlib','-p','no:cacheprovider','-c',str(HERE/'pytest-empty.ini'),'--rootdir='+str(ROOT),'-o','tmp_path_retention_policy=failed','--basetemp='+str(FIXTURE/'fixtures'),'--junitxml='+str(HERE/'focused-tests.xml'),'--tb=short']
args += [str(HERE/'test_preflight_existing_regressions.py' if name=='test_agent_supervisor_project_dependency_preflight.py' else ROOT/'test/api'/name)+'::'+case for name,cases in selection.items() for case in cases]
exit_code=int(pytest.main(args,plugins=[Fixtures()]))
origins=[]
for name,mod in sorted(sys.modules.items()):
 if name=='ipfs_accelerate_py' or name.startswith('ipfs_accelerate_py.'):
  path=getattr(mod,'__file__',None)
  if path:
   resolved=Path(path).resolve();assert resolved.is_relative_to(ROOT), (name,path)
   origins.append({'module':name,'path':str(resolved)})
for item in manifest['files']:
 assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['after_sha256']
receipt={'exit_code':exit_code,'elapsed_seconds':time.monotonic()-started,'selection':selection,'origins':origins,'full_suite':False,'native_execution':False,'admitted':False,'product_source_unchanged_during_tests':True}
(HERE/'focused-tests-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
raise SystemExit(exit_code)
