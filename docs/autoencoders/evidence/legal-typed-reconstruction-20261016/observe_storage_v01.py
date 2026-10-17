from pathlib import Path
import hashlib,json,os,sys,time,types,datetime
phase=Path('/home/barberb/lift_coding/artifacts/legal-typed-reconstruction-20261016-01')
root=Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
guard_path=Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
raw=guard_path.read_bytes()
assert hashlib.sha256(raw).hexdigest()=='caef50be105d8280cd727ae0c14867644e223d83639454ff33f0df2df2e68854'
g=types.ModuleType('retained_storage_source_guard');g.__file__=str(guard_path)
exec(compile(raw,str(guard_path),'exec',dont_inherit=True,optimize=0),g.__dict__)
pins=json.loads((phase/'storage-observer-pins-v01.json').read_text())
g.code_guard(pins); g.no_forbidden_modules()
os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',IPFS_AUTO_INSTALL='false',IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0')
finder=g.PinnedProductFinder(root,pins);sys.meta_path.insert(0,finder);sys.path.insert(0,str(root))
fleet_path=root/'scripts/ops/legal_ir/run_autoencoder_fleet.py'
fleet_raw=g.snapshot(fleet_path,g.MAX_SOURCE_BYTES);assert g.sha(fleet_raw)==pins[str(fleet_path)]
fleet=types.ModuleType('existing_readonly_fleet_observer');fleet.__file__=str(fleet_path)
exec(compile(fleet_raw,str(fleet_path),'exec',dont_inherit=True,optimize=0),fleet.__dict__)
start=time.monotonic(); now=datetime.datetime.now(datetime.timezone.utc).isoformat()
ledger=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
result=fleet.storage_capacity(ledger,ledger.parent)
g.code_guard(pins);g.no_forbidden_modules();origins=g.product_origins(root,pins,finder)
assert not any(n.partition('.')[0] in {'numpy','pyarrow','multiformats','torch','huggingface_hub','datasets'} for n in sys.modules)
report={'schema':'legal-typed-reconstruction-storage-observation/v1','scope':'existing readonly nontransactional observer; no admission','started_at_utc':now,'elapsed_seconds':time.monotonic()-start,'entrypoint':'run_autoencoder_fleet.storage_capacity','observation':result,'ledger_mutated_by_this_observer':False,'native_reservation_acquired':False,'original_corpus_or_checkpoint_bodies_opened':False,'numerical_CID_or_SDK_imports':[],'source_sha256':pins,'loaded_product_origins':origins,'guard_helper_sha256':g.sha(raw)}
p=phase/'storage-observation-v01.json';p.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(result,sort_keys=True))
