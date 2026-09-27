from pathlib import Path
import os,sys,resource,json,time,socket
HERE=Path(__file__).resolve().parent
ROOT=HERE/'test-source'
(HERE/'test-runtime').mkdir(exist_ok=True)
DATASETS=Path('/home/barberb/lift_coding/external/ipfs_datasets')
for key in ('GIT_INDEX_FILE','GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES'):
 os.environ.pop(key,None)
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
 os.environ[key]='1'
os.environ.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',IPFS_ACCELERATE_AGENT_ORCHESTRATION_DIR=str(HERE/'test-runtime/orchestration'),AUTONOMY_RECOVERY_LEASE_PATH=str(HERE/'test-runtime/recovery.json'))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
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
started=time.monotonic()
args=['-q','--continue-on-collection-errors','--noconftest','--import-mode=importlib','-p','no:cacheprovider','-c',str(HERE/'pytest-empty.ini'),'--rootdir='+str(ROOT),'-o','tmp_path_retention_policy=failed','--basetemp='+str(HERE/'test-runtime/fixtures'),'--junitxml='+str(HERE/'focused-tests.xml'),'--tb=short']
args += [str(ROOT/'test/api'/name) for name in ['test_agent_supervisor_control_plane_migrations.py','test_agent_supervisor_tasks_index_upgrade.py','test_agent_supervisor_goal_claim_integrity.py','test_intent_receipt_cas_supplement.py']]
exit_code=int(pytest.main(args,plugins=[Fixtures()]))
origins=[]
for name,mod in sorted(sys.modules.items()):
 if name=='ipfs_accelerate_py' or name.startswith('ipfs_accelerate_py.'):
  path=getattr(mod,'__file__',None)
  if path:
   resolved=Path(path).resolve();assert resolved.is_relative_to(ROOT), (name,path)
   origins.append({'module':name,'path':str(resolved)})
receipt={'exit_code':exit_code,'elapsed_seconds':time.monotonic()-started,'origins':origins,'full_suite':False,'native_execution':False,'admitted':False}
(HERE/'focused-tests-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
raise SystemExit(exit_code)
