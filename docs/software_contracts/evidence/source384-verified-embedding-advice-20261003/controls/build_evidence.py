from pathlib import Path
import hashlib,json,shutil,xml.etree.ElementTree as ET
W=Path('/home/barberb/lift_coding');B=Path(__file__).resolve().parent;D=W/'.worktrees/ir-release-datasets-20261002';P=D/'docs/software_contracts/evidence/source384-verified-embedding-advice-20261003'
assert not P.exists();P.mkdir(parents=True)
def copy(src,dest):
 dest=P/dest;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
controls=[p for p in B.iterdir() if p.is_file() and (p.name.startswith(('controls-01','actual-02','native-03','native-process')) or p.name in ('run_controls.py','run_actual_controls.py','run_source_native.py','configured_client_plugin.py','native-launch.json','application.json','candidate.patch','pins.json','independent-review.json','build_evidence.py'))]
for p in controls:copy(p,'controls/'+p.name)
copy(B/'bootstrap/sitecustomize.py','controls/bootstrap/sitecustomize.py')
paths=[Path(v) for v in ('ipfs_datasets_py/logic/software_contracts/codebase_source_units_384.py','ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py','tests/unit/optimizers/logic_theorem_optimizer/test_verified_embedding_advice.py','tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_embedding_runtime.py','tests/integration/logic/software_contracts/test_codebase_source_units_384.py')]
for p in paths:copy(D/p,Path('final-sources')/p)
results={}
for name,expected in [('controls-01',40),('actual-02',40),('native-03',7)]:
 root=ET.parse(B/(name+'.xml')).getroot();suites=list(root.iter('testsuite'));v={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','errors','failures','skipped')};assert v==dict(tests=expected,errors=0,failures=0,skipped=0);results[name]=v
before=json.loads((B/'native-03-configured-client-before.json').read_text());after=json.loads((B/'native-03-configured-client-after.json').read_text());assert before['selected_config']==after['selected_config'];assert not before['thresholds_changed'] and not before['new_ledger']
qual=dict(schema='verified-embedding-advice-qualification@1',status='component_qualified_native_container_pending',source_pins={str(p):sha(D/p) for p in paths},distinct_current_tests=47,results=results,
 no_model_weight_changes=True,checkpoint_architecture_unchanged=True,default_release_verified_pages=False,source384_explicit_policy='verified_snapshot_dontneed_best_effort@1',embedding_verifier_source_explicitly_pinned=True,
 validity='All nine asset byte counts, digests, regular held descriptor identities checked before any advice. Hint failures are best effort; native TimeoutError propagates. No asset body read after advice in this verifier call.',
 checkpoint=dict(sha256='2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5',gte_revision='17e1f347d17fe144873b1201da91788898c639cd',native_fixture='five source functions; four decoded unverified candidates and one token deferral; one model load; reopened-registry replay does not infer'),
 host_native_profile=dict(mode=before['mode'],config=before['selected_config'],sampler='collect_proof_host_resources',policy_changed=False,new_ledger=False,host_default_startup_qualified=False),
 claims=dict(model_provider_calls=0,training=False,proof_authority=False,admission_success_in_container=False,freed_bytes_measured=False,benchmark_score=False),
 limitations=['40 earlier overlay controls are repeated by the current actual40, not 40 additional tests.','Advice can partially succeed before a later syscall fails; it is not transactional and advises no memory guarantee.','Required full asset reads total67691071 bytes; the pages actually reloaded/reclaimed are not measured.','The existing host ledger has16CPU and99688MiB memory with24922MiB headroom, unlike the earlier4CPU fixture environment; this configured client reused its current values unchanged.','Source384 producer and requested-policy key changed; previous inference receipts are not rewritten or automatically upgraded. Numerical checkpoint architecture/weights are unchanged.'])
(P/'qualification.json').write_text(json.dumps(qual,indent=2,sort_keys=True)+'\n')
(P/'README.md').write_text('''# Verified embedding file advice, 2026-10-03

The shared cached-GTE verifier accepts an explicit `release_verified_pages=False` option. Default callers keep ordinary verification. Source384 opts in and records `verified_snapshot_dontneed_best_effort@1` in its inference key, alongside an explicit hash of the verifier source.

The opt-in holds the nine asset descriptors until every pinned byte count, SHA-256 and descriptor identity passes. It then requests `POSIX_FADV_DONTNEED` on those same descriptors and closes them without another body read. Unsupported advice is best effort. Native `TimeoutError` is propagated, and all held descriptors are closed on failures. In-cache Hugging Face blob links remain supported; external targets are rejected.

Current on-disk qualification is **47 distinct passing tests**: 23 authored advice/context controls plus17 existing embedding-runtime controls, and7 native Source384 source-map/checkpoint/inference/cold-replay controls. The earlier40 overlay controls are retained separately and are not additional coverage. The native fixture used the unchanged real checkpoint/GTE assets, produced four unverified candidates and one token deferral from five functions, and replayed after reopening the registry without inference. Existing source mutation and tampered map/output checks remain active.

The native test process selected the existing shared ledger through its canonical configured-client API:16 CPU slots,99688MiB memory,24922MiB headroom and the native resource sampler. It did not reset the ledger, change thresholds, or qualify default host startup. These values differ from older qualification environments. The before/after source-free receipts preserve the actual profile.

This component evidence does **not** demonstrate memory reclamation, Docker admission, a complete supervisor run or benchmark reward. The verifier necessarily reads67691071 bytes; actual cache refill and freed memory were not measured. Advice may partly succeed before a later hint fails. No weights, benchmark source, database, private credentials or raw scheduler capabilities are included. The source hashes and requested policy deliberately produce new Source384 inference keys; old receipts remain historical. Numerical checkpoint architecture and weights are unchanged.

The source review was completed before the native7 run and accurately records that run as pending at review time. `qualification.json`, final XML and commands record its subsequent success. All advice experiments retain the original native resource and time bounds.
''')
rows=[dict(path=str(p.relative_to(P)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(P.rglob('*')) if p.is_file()]
(P/'manifest.json').write_text(json.dumps(dict(schema='verified-embedding-advice-evidence@1',files=rows),indent=2,sort_keys=True)+'\n')
print(json.dumps(dict(path=str(P),manifest_sha256=sha(P/'manifest.json'),members=len(rows),bytes=sum(r['bytes'] for r in rows)),indent=2))
