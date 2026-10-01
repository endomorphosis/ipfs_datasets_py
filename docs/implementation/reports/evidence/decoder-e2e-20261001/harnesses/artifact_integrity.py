from pathlib import Path
import json,hashlib,os,subprocess,sys,time
import torch
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.native_formula_checkpoint import register_candidate
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.native_formula_training import validate_training_result
root=Path.cwd();out=root/'workspace/decoder-e2e-20261001/control/artifact-integrity'
original=root/'workspace/decoder-e2e-20261001/native-20261001T0130/intent_ir/first/registered/candidate.json'
original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
saved=json.loads(original.read_text());training={'checkpoint':saved['checkpoint'],'report':saved['report']}
torch.set_num_threads(1);validate_training_result(training)
with AutoencoderRegistry(out/'control.duckdb',out/'artifacts') as registry:
 receipt=register_candidate(registry,training,out/'copied-candidate')
 artifact=registry.artifact_path(receipt['artifact'])
 exact=artifact.read_bytes()
 assert hashlib.sha256(exact).hexdigest()==receipt['artifact']['sha256']
# Corrupt only the fresh diagnostic registry's artifact, not the original parent.
artifact.write_bytes(exact+b' ')
cmd=[sys.executable,str(root/'scripts/ops/autoencoder/train_native_formula.py'),'--domain','intent_ir','--corpus',str(original.parents[2]/'corpus.json'),'--registry',str(out/'control.duckdb'),'--artifact-root',str(out/'artifacts'),'--output',str(out/'must-not-exist'),'--parent-version',receipt['version_id'],'--epochs','1','--max-seconds','60']
# original: intent_ir/first/registered/candidate.json -> parents[2] is intent_ir.
env=os.environ.copy();env.update(PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1')
started=time.monotonic();r=subprocess.run(cmd,text=True,capture_output=True,env=env,timeout=30)
(out/'stdout.log').write_text(r.stdout);(out/'stderr.log').write_text(r.stderr)
checks={'nonzero_exit':r.returncode!=0,'checksum_error_reached':'artifact bytes or digest mismatch' in r.stderr,'no_output_or_training':not(out/'must-not-exist').exists(),'original_candidate_unchanged':hashlib.sha256(original.read_bytes()).hexdigest()==original_sha,'not_directory_binding_error':'artifact_root differs' not in r.stderr}
report={'schema':'actual-checkpoint-corruption-e2e/v1','command':cmd,'returncode':r.returncode,'wall_seconds':time.monotonic()-started,'checks':checks,'all_checks_passed':all(checks.values()),'registry_artifact':receipt['artifact'],'stderr':r.stderr,'scope':'fresh_independent_diagnostic_registry_with_matching_durable_root_only_copied_artifact_corrupted','admitted':False,'qualified':False}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));assert report['all_checks_passed']
