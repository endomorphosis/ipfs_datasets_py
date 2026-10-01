import concurrent.futures, hashlib, importlib.util, json, os, pathlib, subprocess, sys, time
ROOT=pathlib.Path.cwd();OUT=ROOT/'workspace/decoder-e2e-20261001/native-20261001T0130/all-projections';OUT.mkdir()
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()
p=ROOT/'tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py';spec=importlib.util.spec_from_file_location('_all_projection_fixtures',p);fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
ENV=dict(os.environ,PYTHONPATH=str(ROOT),CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE='0')
def save(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
source_paths=[ROOT/'scripts/ops/autoencoder/train_native_formula.py',p]+sorted((ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer').glob('*formula*.py'))+[ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/name for name in ['autoencoder_runtime_registry.py','autoencoder_schema_lake.py','autoencoder_decoded_schema.py']]
source_before={str(p.relative_to(ROOT)):sha(p) for p in source_paths}
def run(domain):
 directory=OUT/domain;directory.mkdir();train,tune,_=fixtures._corpus(domain)
 selected=[r['projection_id'] for r in train[0]['projections'] if r['logic_family'] is not None and r['expression'] not in (None,[],{})]
 excluded=[{'projection_id':r['projection_id'],'logic_family':r['logic_family'],'reason':'no logic family' if r['logic_family'] is None else 'empty expression','expression':r['expression']} for r in train[0]['projections'] if r['projection_id'] not in selected]
 save(directory/'corpus.json',{'training_targets':train,'tuning_targets':tune,'projection_ids':selected})
 command=[sys.executable,str(ROOT/'scripts/ops/autoencoder/train_native_formula.py'),'--domain',domain,'--corpus',str(directory/'corpus.json'),'--registry',str(directory/'control.duckdb'),'--artifact-root',str(directory/'artifacts'),'--output',str(directory/'trained'),'--max-seconds','60','--lake-timeout-seconds','60','--epochs','35','--latent-width','8','--learning-rate','.04','--batch-size','1','--seed','1729']
 start=time.perf_counter();r=subprocess.run(['/usr/bin/time','-v','-o',str(directory/'resources.txt'),*command],cwd=ROOT,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 (directory/'stdout.log').write_text(r.stdout);(directory/'stderr.log').write_text(r.stderr)
 result={'domain':domain,'command':command,'returncode':r.returncode,'wall_seconds':time.perf_counter()-start,'selected_projection_ids':selected,'excluded_projections':excluded,'stderr_tail':r.stderr[-4000:]}
 for filename in ['training.json','schema-validation.json']:
  if (directory/'trained'/filename).exists():result[filename]=json.loads((directory/'trained'/filename).read_text())
 for line in reversed(r.stdout.splitlines()):
  try:result['last_json']=json.loads(line);break
  except json.JSONDecodeError:pass
 save(directory/'report.json',result);return result
start=time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,['intent_ir','security_ir','ui_ux_ir']))
after={str(p.relative_to(ROOT)):sha(p) for p in source_paths}
report={'schema':'all-nonempty-projection-native-cli-e2e/v1','domains':results,'wall_seconds':time.perf_counter()-start,'source_hashes_before':source_before,'source_hashes_after':after,'source_files_unchanged':source_before==after,'corpus_scope':'Authored repeated structures under disjoint source IDs, diagnostic only; all nonempty logic_family projections from each fixture selected','concurrency':3,'per_process_torch_threads':1,'device':'cpu','dtype':'float64','scope':'Three independent diagnostic registries, not shared or fleet training','admitted':False,'qualified':False,'publication_performed':False,'downloads_performed':False}
save(OUT/'report.json',report)
for r in results:print(json.dumps({'domain':r['domain'],'selected':r['selected_projection_ids'],'returncode':r['returncode'],'wall_seconds':r['wall_seconds'],'schema_complete':r.get('schema-validation.json',{}).get('schema_checks_complete'),'schema_pass_count':r.get('schema-validation.json',{}).get('schema_pass_count'),'stderr':r['stderr_tail']}))
