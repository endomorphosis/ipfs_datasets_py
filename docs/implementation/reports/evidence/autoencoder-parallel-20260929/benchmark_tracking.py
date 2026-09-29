"""Same-process ABBA mechanical replay benchmark; not native qualification.

Reference dispatch is compiled from the captured pre-change function only and
injected for its measurement rows. Every row reconstructs fresh model state and
verifies every immutable checkpoint/patch byte through the unchanged resolver.
No model metrics, training, proofs, database mutations or downloads run here.
"""
import ast, gc, hashlib, json, os, time, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
for key,value in {'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI':'0','IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA':'0','IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE':'0','CUDA_VISIBLE_DEVICES':'','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}.items():os.environ[key]=value
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_state_version as tracking
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import _load_candidate
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
OLD=BASE.parent/'autoencoder-optimizer-20260929'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rss():return int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:')))*1024
before_path=BASE/'tracking-fastpath-scratch/modal_autoencoder_state_version.before.py'
original=before_path.read_bytes()
expected=read(BASE/'tracking-fastpath-scratch/before-sha256.json')
assert hashlib.sha256(original).hexdigest()==next(iter(expected.values()))
parsed=ast.parse(original)
function=next(node for node in parsed.body if isinstance(node,ast.FunctionDef) and node.name=='_tracked_value')
namespace=dict(vars(tracking))
exec(compile(ast.Module(body=[function],type_ignores=[]),str(before_path),'exec'),namespace)
reference=namespace['_tracked_value'];optimized=tracking._tracked_value
row=next(row for row in read(OLD/'scaled-audit.json')['rows'].values() if '22 days' in row['source_text'])
def cas(ref):return OLD/'scaled/artifacts'/ref['sha256'][:2]/ref['sha256']
qual=read(cas(row['qualification_receipt']))
refs=[{**ref,'path':str(cas(ref))} for ref in qual['checkpoint_artifacts']]
candidate=next(ref for ref in refs if ref['sha256']==qual['candidate_artifact']['sha256'])
deps=[ref for ref in refs if ref is not candidate]
manifest=_package_manifest(); artifacts_before={ref['sha256']:sha(Path(ref['path'])) for ref in refs}
assert all(a==b for a,b in artifacts_before.items())
rows=[]
try:
    for mode in ('warmup','reference','optimized','optimized','reference'):
        tracking._tracked_value=reference if mode=='reference' else optimized
        gc.collect();start_rss=rss();start=time.perf_counter()
        result=_load_candidate(candidate,deps)
        seconds=time.perf_counter()-start
        identity=result.state.state_identity_record().to_dict()
        assert identity==qual['candidate_state_identity']
        assert dict(result.materialized_checkpoint)==qual['materialized_checkpoint']
        rows.append({'mode':mode,'seconds':seconds,'rss_before':start_rss,'rss_loaded':rss(),
                     'state_identity':identity,'materialized_checkpoint':dict(result.materialized_checkpoint),
                     'depth':result.depth,'closure_count':len(result.artifacts)})
        del result;gc.collect()
finally:
    tracking._tracked_value=optimized
manifest_after=_package_manifest()
artifacts_after={ref['sha256']:sha(Path(ref['path'])) for ref in refs}
unchanged=manifest_after==manifest and artifacts_before==artifacts_after
means={name:sum(r['seconds'] for r in rows if r['mode']==name)/2 for name in ('reference','optimized')}
report={'schema':'same-process-tracking-replay-measurement/v1','rows':rows,'means_seconds':means,
    'ratio':means['optimized']/means['reference'],'source_manifest':manifest,
    'reference_source_sha256':hashlib.sha256(original).hexdigest(),'candidate':candidate,
    'source_and_artifacts_unchanged':unchanged,'passed':unchanged,'producer_after':manifest_after,'artifact_sha256':artifacts_before,'artifact_sha256_after':artifacts_after,
    'scope':'Mechanical ABBA comparison only: pre-change function temporarily injected for reference rows; optimized rows use canonical function. Fresh models, full bytes/hash/schema/patch validation on every row. Warmup excluded. OS cache uncontrolled. This is not native candidate qualification or a Lake admission.',
    'admitted':False}
destination=BASE/('tracking-replay-comparison.json' if unchanged else 'tracking-replay-aborted-2.json')
with destination.open('x') as stream:json.dump(report,stream,sort_keys=True,indent=2);stream.write('\n')
print(json.dumps({'means_seconds':means,'ratio':report['ratio'],'rows':[{k:r[k] for k in ('mode','seconds','rss_loaded')} for r in rows],'unchanged':unchanged}))
if not unchanged:raise SystemExit(1)
