"""Replay the real empty review through scope bindings; invent no declarations."""
from pathlib import Path
import hashlib,json,os,sys
from bootstrap_inert import install,ROOT,PACKAGES
F=Path(__file__).resolve().parent;J=F.parent/'legal-joint-readout-20261011-01';N=F.parent/'legal-native-cache-20261011-01';H=F.parent/'legal-structured-training-20261011-01';OUT=F/'actual-scope-pilot-v01'
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):return binding.parse_json_bytes(Path(p).read_bytes())
def write(n,v):
 p=OUT/n
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 return pin(p)
def audit(e,a):
 if e.startswith('socket.') or e in {'subprocess.Popen','os.system'}:raise AssertionError('No network/processes in scope replay')
install();sys.addaudithook(audit)
from ipfs_datasets_py.logic.legal_ir import statutory_scope_declaration_binding as binding
assert not OUT.exists()
packet_path=J/'statutory-source-review-packet.json';assert pin(packet_path)['sha256']=='bf42fb6a854d0a5b8f77e09b1bfd6e1fad4a6bf47323dd246826774b9bf6dc06'
packet=read(packet_path);expected=binding.digest(packet);assert expected=='73fbfd8731ea3b11ec8a49a4f8b21ba2f80a0f34009d744c301540417d559054'
recording_path=H/'statutory-review-pending-recording.json';recording=read(recording_path)
refs=read(N/'source-artifact-pins.json');provenance=pin(N/'source-view-provenance.json');refs[provenance['sha256']]=provenance
used={}
def resolver(ref):
 v=refs[ref['sha256']];assert ref['bytes']==v['bytes'] and pin(v['path'])==v;used[v['path']]=v;return Path(v['path'])
opts={'expected_packet_sha256':expected,'artifact_resolver':resolver,'recording':recording}
guide=binding.prepare_binding_slots(packet,[],**opts)
result=binding.bind_scope_declarations(packet,[],[],**opts)
replay=binding.validate_binding(result,packet,[],[],**opts)
assert guide['item_count']==result['item_count']==8 and guide['submission_count']==result['submission_count']==result['sidecar_count']==result['declaration_count']==0
assert result['status']=='pending' and all(v==0 for v in result['admission_masks'].values())
assert all(result[k] is False for k in binding._false())
assert all(not r['reviewed_declarations'] and r['recording_status']=='pending' and all(v==0 for v in r['admission_masks'].values()) for r in result['items'])
limited=[r for r in result['items'] if r['request_profile_limits']]
assert len(limited)==3 and sorted(r['complete_context_characters'] for r in limited)==[21347,28500,71688]
assert all(r['scope_request'] is None and 'complete_raw_context_character_limit' in r['request_profile_limits'] for r in limited)
assert all(s['unsubmitted_binding_slot']['scope_declaration'] is None and all(s['unsubmitted_binding_slot'][k] is None for k in binding.MAP_FIELDS) for s in guide['items'])
inputs=[pin(p) for p in (packet_path,recording_path,N/'source-artifact-pins.json',N/'source-view-provenance.json',F/'bootstrap_inert.py',Path(__file__))]+list(used.values())
loaded={};namespaces={}
for name,m in list(sys.modules.items()):
 if name.startswith('ipfs_datasets_py') and getattr(m,'__file__',None):
  p=Path(m.__file__).resolve()
  if p.is_file():
   assert ROOT.resolve() in p.parents
   (namespaces if name in PACKAGES else loaded)[name]=pin(p)
OUT.mkdir()
write('binding-guide.json',guide);write('binding-result.json',result);write('binding-replay.json',replay)
summary={'schema':'actual-empty-statutory-scope-pilot/v1','passed':True,'findings':[],'item_count':8,'human_submissions':0,'scope_sidecars':0,'semantic_labels':0,'training_masks':result['admission_masks'],'profile_limited_items':3,'complete_context_character_counts':[r['complete_context_characters'] for r in result['items']],
'profile_limit_dispositions':[{'item_id':r['item_id'],'complete_context_characters':r['complete_context_characters'],'limits':r['request_profile_limits'],'context_truncated':False} for r in limited],
'input_pins':inputs,'loaded_producer_pins':loaded,'namespace_file_endpoints_not_executed':namespaces,'output_pins':[pin(p) for p in sorted(OUT.iterdir())],
'model_calls':0,'encoder_calls':0,'optimizer_updates':0,'compiler_calls':0,'actual_training_or_evaluation_admission':False,'declared_consistency_is_legal_correctness':False,'formal_targets_created':0,'source_semantics_verified':False,'actual_human_review_invented':False}
write('scope-pilot-summary.json',summary)
print('Eight actual items remain pending; three complete contexts profile-limited; zero new reviews, scopes or targets')
