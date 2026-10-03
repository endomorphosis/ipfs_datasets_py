from pathlib import Path
import hashlib, importlib, json, shutil, subprocess, xml.etree.ElementTree as ET
D=Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002'); A=Path('/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002')
ART=Path('/home/barberb/lift_coding/artifacts/codebase-peer-transport-20261002'); RUN=ART/'native-06'; FIX=RUN/'temp/peer-native0'
OUT=D/'docs/software_contracts/evidence/codebase-peer-transport-20261002'; OUT.mkdir(parents=True,exist_ok=False)
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def save(name,value):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def copy(source,name):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(Path(source).read_bytes())
def check_xml(path,count):
 r=ET.parse(path).getroot(); rows=r.findall('.//testcase'); assert len(rows)==count
 assert not r.findall('.//failure') and not r.findall('.//error') and not r.findall('.//skipped')
 return [r.attrib['name'] for r in rows]
actual=check_xml(RUN/'tests.xml',13);neighbor=check_xml(RUN/'neighbor.xml',19)
x=json.loads((FIX/'qualification.json').read_text());assert all(c['passed'] for c in x['controls'])
from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport as transport
from ipfs_datasets_py.logic.software_contracts import codebase_peer_dispatched_federation as peer
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
cas=ImmutableCAS(FIX/'cas'); policy=cas.get(x['round']['policy_cid']);assert policy['implementation']==peer._pins()
expected={}
def gather(value):
 if isinstance(value,dict):
  for key,val in value.items():
   if key.startswith('ipfs_') and isinstance(val,str) and len(val)==64:
    assert key not in expected or expected[key]==val;expected[key]=val
   else:gather(val)
 elif isinstance(value,list):
  for val in value:gather(val)
gather(policy['implementation'])
expected[peer.__name__]=policy['implementation']['owner_sha256']
rows=[]
for name,digest in sorted(expected.items()):
 path=Path(importlib.import_module(name).__file__).resolve(); raw=path.read_bytes();assert sha(raw)==digest
 repo,base=('datasets',D) if path.is_relative_to(D) else ('accelerate',A)
 assert path.is_relative_to(base);rel=path.relative_to(base).as_posix()
 copy(path,'sources/'+repo+'/'+rel);rows.append(dict(module=name,repository=repo,path=rel,sha256=digest,bytes=len(raw)))
# Include exact tests separately; they are not model/transport producers.
for repo,base,rel in [('datasets',D,'tests/integration/logic/software_contracts/test_codebase_peer_federation.py'),('accelerate',A,'test/unit/test_codebase_federated_dispatch.py')]:
 raw=(base/rel).read_bytes();copy(base/rel,'sources/'+repo+'/'+rel);rows.append(dict(repository=repo,path=rel,sha256=sha(raw),bytes=len(raw),test_only=True))
for name in ('tests.log','tests.xml','neighbor.log','neighbor.xml'):copy(RUN/name,'native-06/'+name)
copy(FIX/'qualification.json','native-06/qualification.json')
for attempt in ('native-01','native-02','native-03','native-04','native-05'):
 for name in ('tests.log','tests.xml'):copy(ART/attempt/name,'historical/'+attempt+'/'+name)
cas_rows=[]
for path in sorted((FIX/'cas').rglob('*')):
 if path.is_file():
  if path.is_relative_to(FIX/'cas/source'):cas.get_bytes(path.name)
  else:cas.get(path.name)
  copy(path,'native-06/cas/'+path.relative_to(FIX/'cas').as_posix());cas_rows.append(dict(cid=path.name,sha256=sha(path.read_bytes()),bytes=path.stat().st_size))
for path in sorted((FIX/'models').rglob('*')):
 if path.is_file():
  assert sha(path.read_bytes())==path.name;copy(path,'native-06/models/'+path.relative_to(FIX/'models').as_posix())
for path in sorted((FIX/'repo').glob('*.py')):copy(path,'native-06/fixture/'+path.name)
save('producer-sources.json',{'schema':'codebase-peer-native-source-pins/v1','sources':rows,'committed_bases':{key:subprocess.check_output(['git','-C',str(base),'rev-parse','HEAD'],text=True).strip() for key,base in [('datasets',D),('accelerate',A)]},'scope':'Exact working producer bytes, including additive uncommitted files, independently match native policy. Base Git commits alone do not include new files.'})
save('qualification.json',{'schema':'codebase-peer-native-qualification/v1','native_passed':13,'neighbor_passed':19,'distinct_controls':32,'native_test_names':actual,'neighbor_test_names':neighbor,'native_default_host':True,'telemetry_injected':False,'elapsed_native_seconds':67.30,'elapsed_neighbor_seconds':2.23,'earlier_nine_case_pass_seconds':62.98,'qualification':'two sequential local subprocess peers using canonical MCP++ frames and shared immutable CAS; exact native 8D federation replay','cas_objects':cas_rows,'authority':transport.FALSE,'source_policy_cid':x['round']['policy_cid'],'peer_record_cid':x['round']['artifact_cid'],'remaining':['remote/libp2p deployment','cross-host artifact transport','parallel remote fleet and device accounting','distributed 384D training','gradient collective backend/verifier','whole-round completion reply recovery without retained sidecar CID'],'no_external_publication':True,'private_exclusions':['native database files','scheduler state/lease keys','private peer configuration','model-registry authority records','Git administrative files']})
(OUT/'README.md').write_text('''# Native local peer transport qualification

The final unchanged production bytes passed **13 native cases in 67.30 seconds** and **19 neighboring TaskQueue dispatcher cases in 2.23 seconds** (32 distinct controls, no skips). The actual default host scheduler and sampler were used; no admission thresholds or telemetry were replaced. Other shared-host work may have run concurrently, so these timings are not a throughput comparison.

The fixture fits one existing 8D source feature parent over five authored source files, then completes a two-client round through two distinct local peer processes. The controller independently replays the native checkpoint/update contracts, exact FedAvg and optimizer reset, fixed canary/replay diagnostics and native registry completion. These are development diagnostics, not holdout generalization or a distributed 384D result.

The lost-response control performs a fresh fit in a distinct peer profile, discards the actual delivered response, restarts the peer, and verifies invocation counts **1 then 0**. A completed duplicate stays with the queue. An actual SIGKILL prevents completion; another returned peer result is refused after its queue claim becomes stale. Changed source, model, binary reference, profile, malformed framing and absent owner resource context are refused. Final checks find none of the observed peer processes or owned leases still active.

The source snapshot manifest joins the current bytes to the policy retained by the successful native run. It includes additive files that were not yet committed when tested. CAS objects are independently checked with the native CAS reader; four model artifacts are independently checked against their filename SHA-256. The archive excludes databases, lease tokens, private peer configuration and Git administration. Public process receipts retain only redacted diagnostics and lease identifiers. This is evidence of the recorded run, not a reusable live lease or proof capability.

Historical attempts remain separate: native-01 had an incorrect fixture Git boundary; native-02 exposed default scheduler relocation under private TMPDIR; native-03/04 diagnosed an inherited file-size limit below the unchanged numerical worker requirement. Those integration issues were fixed before native-05 (9 passing cases) and native-06 (the final 13-case matrix). Only final source snapshots are retained; historical logs are diagnostics, not qualification of final bytes.

This profile uses existing MCP++ framed initialize/tools-call over local subprocess stdio and a shared immutable CAS. Remote/libp2p deployment, cross-host artifact transfer, parallel remote peers, gradient collectives, GPU/hard aggregate enforcement and distributed 384D training remain unqualified. Completed whole-round retry requires the explicit returned sidecar CID; no missing process evidence is synthesized. Transport receipts carry no numerical, proof, model admission or promotion authority.
''')
copy(Path(__file__),'package_evidence.py')
files=[]
for path in sorted(OUT.rglob('*')):
 if path.is_file():files.append(dict(path=path.relative_to(OUT).as_posix(),bytes=path.stat().st_size,sha256=sha(path.read_bytes())))
save('manifest.json',{'schema':'codebase-peer-evidence-manifest/v1','files':files,'bytes':sum(x['bytes'] for x in files),'scope':'bounded public native/local peer qualification; no external publication or live authority'})
print(json.dumps(dict(directory=str(OUT),manifest_sha256=sha((OUT/'manifest.json').read_bytes()),members=len(files),bytes=sum(x['bytes'] for x in files))))
