from pathlib import Path
import hashlib,json,os,subprocess,time
out=Path(__file__).resolve().parent
root=out.parents[3]
original=root/'workspace/decoder-e2e-20261001/native-20261001T0130/intent_ir/first/registered/candidate.json'
old=json.loads((out/'initial-harness-report.json').read_text())
assert hashlib.sha256(original.read_bytes()).hexdigest()==old['registry_artifact']['sha256']
env=os.environ.copy();env.update(PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1')
started=time.monotonic();r=subprocess.run(old['command'],capture_output=True,text=True,env=env,timeout=30)
checks={'nonzero_exit':r.returncode!=0,'checksum_error_reached':'artifact bytes or digest mismatch' in r.stderr,'no_output_or_training':not(out/'must-not-exist').exists(),'original_candidate_unchanged':hashlib.sha256(original.read_bytes()).hexdigest()==old['registry_artifact']['sha256'],'not_directory_binding_error':'artifact_root differs' not in r.stderr}
report={**old,'returncode':r.returncode,'wall_seconds':time.monotonic()-started,'checks':checks,'all_checks_passed':all(checks.values()),'stderr':r.stderr,'harness_correction':'Initial harness expected the wrong error string. This is a fresh subprocess read of the same independently copied corrupt artifact; no additional training or corruption.'}
(out/'verification.stdout.log').write_text(r.stdout);(out/'verification.stderr.log').write_text(r.stderr)
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'all_checks_passed':report['all_checks_passed'],'checks':checks}));assert report['all_checks_passed']
