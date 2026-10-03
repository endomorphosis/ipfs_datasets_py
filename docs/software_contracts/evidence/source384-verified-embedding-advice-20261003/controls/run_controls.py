from pathlib import Path
import hashlib,json,os,subprocess,sys,time
B=Path(__file__).resolve().parent;W=B.parents[1];D=W/'.worktrees/ir-release-datasets-20261002'
env=os.environ.copy();env.update(PYTHONPATH=':'.join(map(str,(B/'bootstrap',D,Path('/home/barberb/.local/lib/python3.12/site-packages'),Path('/usr/local/lib/python3.12/dist-packages'),Path('/usr/lib/python3/dist-packages')))),PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
args=[sys.executable,'-m','pytest','-q',str(B/'tests/test_verified_embedding_advice.py'),str(D/'tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_embedding_runtime.py'),'--junitxml='+str(B/'controls-01.xml')]
files=[*sorted((B/'proposed').rglob('*.py')),B/'tests/test_verified_embedding_advice.py',B/'bootstrap/sitecustomize.py',Path(__file__),D/'tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_embedding_runtime.py']
pins={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(B/'controls-01-command.json').write_text(json.dumps(dict(argv=args,cwd=str(D),env={k:env[k] for k in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE','PYTEST_DISABLE_PLUGIN_AUTOLOAD','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','CUDA_VISIBLE_DEVICES','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE')},pins=pins,scope='authored small assets and existing diagnostic tensors; no model weights or inference'),indent=2)+'\n')
start=time.monotonic()
with (B/'controls-01.log').open('w') as log:r=subprocess.run(args,cwd=D,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
(B/'controls-01-exit.json').write_text(json.dumps(dict(exit_code=r.returncode,seconds=time.monotonic()-start,pins_after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),indent=2)+'\n')
print(r.returncode);print((B/'controls-01.log').read_text()[-5000:]);raise SystemExit(r.returncode)
