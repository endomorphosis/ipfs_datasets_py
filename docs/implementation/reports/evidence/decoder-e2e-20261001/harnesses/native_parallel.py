import concurrent.futures, copy, hashlib, importlib.util, json, os, pathlib, subprocess, sys, time
ROOT=pathlib.Path.cwd(); OUT=ROOT/'workspace/decoder-e2e-20261001/native-20261001T0130'
sys.path.insert(0,str(ROOT))
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()
P=ROOT/'tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py'
spec=importlib.util.spec_from_file_location('_e2e_native_fixtures',P); fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_training as learner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_decoded_schema import validate_decoded_outputs
import torch
torch.set_num_threads(1)
ENV=dict(os.environ,PYTHONPATH=str(ROOT),CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE='0')
def save(path,value): path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
source_files=[ROOT/'scripts/ops/autoencoder/train_native_formula.py',P]+sorted((ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer').glob('*formula*.py'))+[ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'/name for name in ['autoencoder_runtime_registry.py','autoencoder_schema_lake.py','autoencoder_decoded_schema.py']]
source_before={str(p.relative_to(ROOT)):sha(p) for p in source_files}
start=time.perf_counter()
def run(command,directory,label):
    started=time.perf_counter(); result=subprocess.run(['/usr/bin/time','-v','-o',str(directory/(label+'.resources.txt')),*command],cwd=ROOT,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    (directory/(label+'.stdout.log')).write_text(result.stdout); (directory/(label+'.stderr.log')).write_text(result.stderr)
    record={'command':command,'returncode':result.returncode,'wall_seconds':time.perf_counter()-started,'stdout_file':str(directory/(label+'.stdout.log')),'stderr_file':str(directory/(label+'.stderr.log'))}
    for line in reversed(result.stdout.splitlines()):
        try: record['last_json']=json.loads(line);break
        except json.JSONDecodeError: pass
    record['stderr_tail']=result.stderr[-4000:]
    save(directory/(label+'.execution.json'),record);return record

def exercise(domain):
    directory=OUT/domain;directory.mkdir()
    train,tune,ids=fixture._corpus(domain)
    save(directory/'corpus.json',{'training_targets':train,'tuning_targets':tune,'projection_ids':ids})
    base=[sys.executable,str(ROOT/'scripts/ops/autoencoder/train_native_formula.py'),'--domain',domain,'--corpus',str(directory/'corpus.json'),'--registry',str(directory/'control.duckdb'),'--artifact-root',str(directory/'artifacts'),'--max-seconds','60','--lake-timeout-seconds','60']
    first=run(base+['--output',str(directory/'first'),'--epochs','35','--latent-width','8','--learning-rate','.04','--batch-size','1','--seed','1729'],directory,'first')
    out={'domain':domain,'first':first,'projection_ids':ids}
    if first['returncode']!=0:return out
    candidate=first['last_json']['candidate']; cp_path=directory/'first/checkpoint.json'; parent_sha=sha(cp_path)
    protected={str(p):sha(p) for p in (directory/'first').rglob('*') if p.is_file()}
    version=candidate['version_id']
    resumed=run(base+['--output',str(directory/'resumed'),'--parent-version',version,'--epochs','2'],directory,'resumed');out['resumed']=resumed
    mismatched=run(base+['--output',str(directory/'rejected-settings'),'--parent-version',version,'--epochs','1','--learning-rate','.02'],directory,'rejected-settings')
    zerowork=run(base+['--output',str(directory/'zero-deadline'),'--parent-version',version,'--epochs','1','--max-seconds','0'],directory,'zero-deadline')
    overwrite=run(base+['--output',str(directory/'first'),'--epochs','1'],directory,'rejected-overwrite')
    out.update(mismatched=mismatched,zero_deadline=zerowork,overwrite=overwrite)
    cp=learner.load_checkpoint(cp_path,expected_sha256=first['last_json']['checkpoint']['sha256'])
    unknown={'intent_ir':fixture.fixtures._intent,'security_ir':fixture.fixtures._security,'ui_ux_ir':fixture.fixtures._ui}[domain](30).to_dict()
    runtime=runtimes.open_runtime(domain,runtimes.NATIVE_FORMULA_VERSION,checkpoint=cp)
    oov=validate_decoded_outputs(runtime,[unknown],output_directory=directory/'oov',timeout_seconds=60)
    save(directory/'oov-schema-validation.json',oov)
    training=json.loads((directory/'first/training.json').read_text()); validation=json.loads((directory/'first/schema-validation.json').read_text())
    out.update(training=training,schema=validation,oov=oov,parent_file_sha256=parent_sha,parent_files_unchanged=all(pathlib.Path(p).is_file() and sha(pathlib.Path(p))==digest for p,digest in protected.items()))
    if resumed['returncode']==0:
        resumed_cp=learner.load_checkpoint(directory/'resumed/checkpoint.json',expected_sha256=resumed['last_json']['checkpoint']['sha256'])
        out.update(resumed_training=json.loads((directory/'resumed/training.json').read_text()),resumed_schema=json.loads((directory/'resumed/schema-validation.json').read_text()),numerical_parent_matches=resumed_cp['parent_checkpoint_sha256']==learner.checkpoint_digest(cp),saved_configuration_matches=cp['config']==resumed_cp['config'],steps_before=cp['latest']['progress']['optimizer_steps'],steps_after=resumed_cp['latest']['progress']['optimizer_steps'])
    out['checks']={
      'fresh_success':first['returncode']==0,'resume_success':resumed['returncode']==0,
      'mismatch_rejected_before_output':mismatched['returncode']!=0 and not (directory/'rejected-settings').exists() and 'immutable checkpoint' in mismatched['stderr_tail'],
      'zero_deadline_no_candidate':zerowork['returncode']==2 and zerowork.get('last_json',{}).get('status')=='no_optimizer_update' and not (directory/'zero-deadline/checkpoint.json').exists() and not (directory/'zero-deadline/registered').exists(),
      'overwrite_rejected':overwrite['returncode']!=0 and 'must be fresh' in overwrite['stderr_tail'],
      'parent_files_unchanged':out['parent_files_unchanged'],
      'oov_error_no_fallback':not oov['schema_checks_complete'] and oov['lake_build_count']==0 and oov['decoded_projection_count']==0 and oov['rows'][0]['status']=='inference_error' and 'unknown' in oov['rows'][0]['reason'],
      'actual_two_schema_builds':validation['lake_build_count']==validation['schema_pass_count']==2,
      'no_admission':not validation['admitted'] and not validation['qualified'],
      'numerical_parent_matches':out.get('numerical_parent_matches',False),'saved_configuration_matches':out.get('saved_configuration_matches',False),
      'resume_four_more_updates':out.get('steps_before')==70 and out.get('steps_after')==74}
    save(directory/'result.json',out);return out
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures={pool.submit(exercise,domain):domain for domain in ['intent_ir','security_ir','ui_ux_ir']}
    for future in concurrent.futures.as_completed(futures):
        try:result=future.result()
        except BaseException as exc:
            import traceback
            result={'domain':futures[future],'error':repr(exc),'traceback':traceback.format_exc()}
        results.append(result);print(json.dumps({'completed':result['domain'],'checks':result.get('checks'),'error':result.get('error')}),flush=True)
source_after={str(p.relative_to(ROOT)):sha(p) for p in source_files}
report={'schema':'native-formula-cli-end-to-end-diagnostic/v1','canonical_tree':str(ROOT),'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'wall_seconds':time.perf_counter()-start,'domains':results,'source_hashes_before':source_before,'source_hashes_after':source_after,'source_files_unchanged':source_before==source_after,'concurrency':3,'per_process_torch_threads':1,'device':'cpu','dtype':'float64','scope':'Three independent concurrent diagnostic registries; not shared-weight or fleet training','corpus_scope':'Two authored structures per domain repeated in tuning under disjoint source identifiers; no held-out generalization evidence','downloads_performed':False,'publication_performed':False,'admitted':False,'qualified':False}
report['all_checks_passed']=report['source_files_unchanged'] and len(results)==3 and all(result.get('checks') and all(result['checks'].values()) for result in results)
save(OUT/'report.json',report);print(json.dumps({'report':str(OUT/'report.json'),'all_checks_passed':report['all_checks_passed'],'wall_seconds':report['wall_seconds']}),flush=True)
