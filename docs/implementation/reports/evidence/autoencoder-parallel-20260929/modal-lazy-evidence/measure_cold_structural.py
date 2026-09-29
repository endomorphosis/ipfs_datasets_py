"""Cold subprocess structural-target import observation; no model/proof calls."""
import hashlib,json,os,pathlib,subprocess,sys,time
root=pathlib.Path('/home/barberb/lift_coding/external/ipfs_datasets')
source_paths=['ipfs_datasets_py/logic/modal/__init__.py','ipfs_datasets_py/logic/modal/decompiler_repairs.py','ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py']
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
before={p:sha(root/p) for p in source_paths}
code='''
import hashlib,json,pathlib,sys,time
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import build_decompiler_structural_learning_target
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
sample=build_us_code_sample(title='qualification-fixture',section='20',text='The officer shall retain the file for at least 20 days.')
assert 'ipfs_datasets_py.logic.modal' not in sys.modules
start=time.perf_counter();first=build_decompiler_structural_learning_target(sample,source_text=sample.text);first_seconds=time.perf_counter()-start
start=time.perf_counter();second=build_decompiler_structural_learning_target(sample,source_text=sample.text);second_seconds=time.perf_counter()-start
assert first==second
import ipfs_datasets_py.logic.modal as modal
from ipfs_datasets_py.logic.modal import decompiler_repairs
root=pathlib.Path('/home/barberb/lift_coding/external/ipfs_datasets').resolve()
paths={name:str(pathlib.Path(module.__file__).resolve()) for name,module in [('modal',modal),('decompiler_repairs',decompiler_repairs)]}
assert all(root in pathlib.Path(p).parents for p in paths.values())
print(json.dumps({'cold_structural_seconds':first_seconds,'warm_structural_seconds':second_seconds,'identical_payload':first==second,'payload_sha256':hashlib.sha256(json.dumps(first,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'formula_target_count':len(first['formula_targets']),'torch_imported':'torch' in sys.modules,'symai_imported':'symai' in sys.modules,'modal_modules_loaded':[name for name in sys.modules if name.startswith('ipfs_datasets_py.logic.modal.')],'paths':paths}))
'''
start=time.perf_counter();result=subprocess.run([sys.executable,'-c',code],cwd=root,env={**os.environ,'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1','IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI':'0'},text=True,capture_output=True,timeout=60);wall=time.perf_counter()-start
if result.returncode:raise RuntimeError(result.stdout+result.stderr)
observation=json.loads(result.stdout.splitlines()[-1]);after={p:sha(root/p) for p in source_paths};assert before==after
output={'scope':'Fresh subprocess, no prewarm; read-only structural-target import observation, not a bridge-on evaluation, training, or Lake admission.','source_sha256':before,'source_unchanged':True,'subprocess_wall_seconds':wall,'observation':observation,'admitted':False,'formalized':False}
p=pathlib.Path('/tmp/modal-lazy-exports-20260929/cold-import-measurement.json');p.write_text(json.dumps(output,sort_keys=True,indent=2)+'\n');print(json.dumps(output,sort_keys=True))
