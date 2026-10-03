from pathlib import Path
import hashlib,json,sys,time
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002');sys.path.insert(0,str(D))
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest,CODEBASE_IR_SCHEMA
base=Path('/home/barberb/lift_coding/artifacts/source-combined-observation-performance-20261003');state=base/'before-01'
receipt=json.loads((state/'receipt.json').read_text());cid=receipt['head']['manifest_cid'];cas=ImmutableCAS(state/'state/source-artifacts')
r=dict(schema='manifest-load-components@1',diagnostic=True,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),manifest_cid=cid,rounds=[],provider_calls=0,training_steps=0,neural_inference=False)
for _ in range(2):
 row={};t=time.monotonic();value=cas.get(cid,expected_schema=CODEBASE_IR_SCHEMA);row['fresh_cas_get_seconds']=time.monotonic()-t
 t=time.monotonic();manifest=CodebaseIRManifest.from_dict(value);row['from_dict_seconds']=time.monotonic()-t
 t=time.monotonic();assert manifest.cid==cid;row['canonical_manifest_identity_seconds']=time.monotonic()-t
 r['rounds'].append(row)
(base/'manifest-components.json').write_text(json.dumps(r,sort_keys=True,indent=2)+'\n');print(json.dumps(r))
