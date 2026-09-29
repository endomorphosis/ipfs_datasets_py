"""Reconstruct the exact before-suite producer map without rewriting its guard failure."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
BASE=Path(__file__).resolve().parent
old_path=BASE.parent/'autoencoder-optimizer-20260929/shared-preparation-before.json'
old=json.loads(old_path.read_bytes())['package_python_files']
current_path=BASE/'package-current.json';current=json.loads(current_path.read_bytes())
owned=('logic/modal/__init__.py','logic/autoformal/family_qualification.py','optimizers/logic_theorem_optimizer/autoencoder_capacity.py','optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py','optimizers/logic_theorem_optimizer/autoencoder_inference.py','optimizers/logic_theorem_optimizer/modal_autoencoder_state_version.py')
external=('huggingface/autoformal_span_cache.py','logic/autoformal/entity_cache.py','logic/autoformal/lean_units.py','logic/autoformal/span_cache.py')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
manifest=lambda files:{'sha256':sha(json.dumps(files,sort_keys=True,separators=(',',':')).encode()),'file_count':len(files)}
readiness=json.loads((BASE/'readiness.json').read_bytes());baseline=json.loads((BASE/'baseline-binding.json').read_bytes());optimized=json.loads((BASE/'optimized-binding.json').read_bytes())
reconstructed=dict(old)
for name in (*owned,'logic/autoformal/lean_units.py'):reconstructed[name]=current[name]
assert manifest(old)==baseline['producer_manifest']
assert manifest(reconstructed)==readiness['source_manifest']
assert manifest(current)==optimized['producer_manifest']
changed={name:{'before':reconstructed.get(name),'after':current.get(name)} for name in sorted(set(reconstructed)|set(current)) if reconstructed.get(name)!=current.get(name)}
assert set(changed)==set(external)-{'logic/autoformal/lean_units.py'}
assert all(sha((ROOT/'ipfs_datasets_py'/name).read_bytes())==reconstructed[name]==current[name] for name in owned)
path=BASE/'package-readiness-before-reconstructed.json';path.write_text(json.dumps(reconstructed,sort_keys=True,indent=2)+'\n')
def ref(path):raw=path.read_bytes();return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}
report={'schema':'readiness-producer-drift-audit/v1','reconstruction_verified':True,
 'baseline_manifest':manifest(old),'readiness_before_manifest':manifest(reconstructed),'optimized_manifest':manifest(current),
 'mapping_inputs':{'historical_source_map':ref(old_path),'owned_after_and_external_after_source_map':ref(current_path),'reconstructed_readiness_before':ref(path)},
 'owned_package_files_unchanged_during_readiness':{name:current[name] for name in owned},
 'external_change_before_readiness':{'logic/autoformal/lean_units.py':{'baseline':old['logic/autoformal/lean_units.py'],'readiness_before':reconstructed['logic/autoformal/lean_units.py']}},
 'concurrent_external_producer_changes_during_readiness':changed,
 'baseline_to_optimized_external_changes':{name:{'baseline':old[name],'optimized':current[name]} for name in external},
 'readiness_receipt':ref(BASE/'readiness.json'),'test_exit_code':readiness['returncode'],'source_unchanged':readiness['source_unchanged'],
 'qualification':'Test execution passed, but the full producer guard failed. This audit documents and preserves that failure; it does not relabel the suite as a stable-source validation.',
 'native_comparison_limitation':'Baseline and optimized runs each have their own immutable producer bindings. Their cross-run difference includes six intended package changes and four external source changes; exact result parity remains auditable, but elapsed differences cannot be attributed solely to the intended changes. Optimized-to-auto comparison requires identical complete producer manifests.',
 'admitted':False}
(BASE/'readiness-provenance-audit.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
print(json.dumps({'reconstructed_sha256':manifest(reconstructed)['sha256'],'changed_during_suite':list(changed),'owned_unchanged':True,'failed_readiness_guard_preserved':True}))
