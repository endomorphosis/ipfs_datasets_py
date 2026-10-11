"""Prepare bounded saved-prediction/native fixtures; execute no models or external tools."""
from pathlib import Path
from copy import deepcopy
import json,hashlib,os,sys
from bootstrap_inert import install,ROOT
F=Path(__file__).resolve().parent;H=F.parent/'legal-structured-training-20261011-01'
R=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01/structured-probability-20261011-01/results')
J=F.parent/'legal-joint-readout-20261011-01';N=F.parent/'legal-native-cache-20261011-01';OUT=F/'prepared-pilot-v01'
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink() and p.resolve()==p
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def read(p):return adapter.parse_json_bytes(Path(p).read_bytes())
def write(name,v):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as s:json.dump(v,s,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False);s.write('\n');s.flush();os.fsync(s.fileno())
 return pin(p)
def audit(event,values):
 if event.startswith('socket.') or event in {'subprocess.Popen','os.system'}:raise AssertionError('preparation cannot use network/processes')
def must_refuse(name,call,needle=None):
 try:call()
 except ValueError as error:
  if needle:assert needle in str(error),(name,str(error))
  return {'case':name,'refused':True,'reason':str(error),'model_calls':0,'backend_calls':0}
 raise AssertionError('expected refusal: '+name)
install();sys.addaudithook(audit)
from ipfs_datasets_py.logic.legal_ir import saved_span_family_adapter as adapter
from ipfs_datasets_py.logic.legal_ir import statutory_declaration_preflight as preflight
from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate
assert not OUT.exists();OUT.mkdir()
inputs=read(F/'authored-development-source-only-v02.json');hypotheses=read(F/'authored-development-cue-declarations-v02.json');raw_path=Path(inputs['parent_saved_inference_report']['path']);assert pin(raw_path)==inputs['parent_saved_inference_report'];raw=read(raw_path)
state_path=R/'source_only-1729-ce0-checkpoint.json';state=json.loads(state_path.read_bytes());assert state['historical_parent']['config']['latent_dimension']==384 and state['historical_parent']['config']['latent_enabled'] is False;state_digest=hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest();assert state_digest==raw['checkpoint_sha256']==inputs['checkpoint_canonical_sha256'];del state
raw_digest=adapter.digest(raw);requests=[];outcomes=[];positive=[]
for source,hypothesis in zip(inputs['rows'],hypotheses['rows'],strict=True):
 assert source['id']==hypothesis['id'];pos=hypothesis['position'];assert raw['rows'][pos]['id']==source['id']
 def pending():return adapter.prepare_pending(source,raw,expected_report_sha256=raw_digest,expected_checkpoint_sha256=state_digest,row_id=source['id'])
 if hypothesis['expected_bounded_profile_outcome']=='temporal_refused':
  outcomes.append({'id':source['id'],'original_position':pos,**must_refuse('temporal_profile_refusal',pending,'temporal')});continue
 packet=pending();seal=adapter.digest(packet);assert adapter.validate_pending(packet,expected_packet_sha256=seal)
 declaration=adapter.declaration_skeleton(packet);occ=declaration['occurrence'];occ.update(occurrence_id=hypothesis['occurrence_id'],start_char=hypothesis['start_char'],end_char=hypothesis['end_char'],source_text=source['source_text'],modality_anchor=deepcopy(hypothesis['modality_span']))
 interpretation=declaration['interpretation'];interpretation.update(activation_scope=bridge.ACTIVATION_SCOPE,exception_scope=bridge.EXCEPTION_SCOPE)
 for facet in ('conditions','exceptions'):
  supplied=hypothesis['qualifier_interpretations'][facet];assert [v['literal'] for v in supplied]==[v['literal'] for v in interpretation['rules'][0][facet]];interpretation['rules'][0][facet]=deepcopy(supplied)
 result=adapter.prepare_family(packet,declaration,expected_packet_sha256=seal);assert adapter.validate_family(result,packet,declaration,expected_packet_sha256=seal)
 assert result['canonical_ir']==raw['rows'][pos]['decoder_row']['canonical_ir'] and all(result[k] is False for k in adapter.FALSE)
 request=deepcopy(result['request']);request['family']=result['native_parser_profile'];requests.append(request);positive.append((packet,declaration,result))
 pins=[write(f'development/{pos:02d}-'+n,v) for n,v in [('pending.json',packet),('declaration.json',declaration),('native-output.json',result)]]
 outcomes.append({'id':source['id'],'original_position':pos,'native_syntax_checked':True,'expected':hypothesis['expected_bounded_profile_outcome'],'outputs':pins,'semantic_accuracy':None,'admitted':False})
assert len(requests)==9 and len(outcomes)==12 and sum(v.get('refused',False) for v in outcomes)==3
negative=[];packet,declaration,result=positive[0];seal=adapter.digest(packet)
bad=deepcopy(declaration);bad['occurrence']['modality_anchor']['end_char']+=1
negative.append(must_refuse('wrong_modality_literal',lambda:adapter.prepare_family(packet,bad,expected_packet_sha256=seal),'interval'))
bad=deepcopy(declaration);span=packet['facet_geometry']['actor'];bad['occurrence']['modality_anchor']={k:span[k] for k in ('start_char','end_char','source_text')};bad['occurrence']['modality_anchor']['canonical_value']='O'
negative.append(must_refuse('cue_overlaps_actor',lambda:adapter.prepare_family(packet,bad,expected_packet_sha256=seal),'overlaps'))
bad_result=deepcopy(result);bad_result['canonical_ir']['rules'][0]['modality']='P'
negative.append(must_refuse('changed_output_after_resealing',lambda:adapter.validate_family(bad_result,packet,declaration,expected_packet_sha256=seal),'replay'))
for family in ('tdfol','dcec','fol','deontic_fol'):
 negative.append(must_refuse('unsupported_sealed_family_'+family,lambda family=family:adapter.prepare_family(packet,declaration,expected_packet_sha256=seal,family=family)))
qpacket,qdeclaration,_=positive[3];bad=deepcopy(qdeclaration);bad['interpretation']['rules'][0]['conditions'][0]['expression']=None
negative.append(must_refuse('unfilled_qualifier_expression',lambda:adapter.prepare_family(qpacket,bad,expected_packet_sha256=adapter.digest(qpacket))))
compiler=gate.prepare_source_family_legal(requests,toolchain='leanprover/lean4:v4.34.1');gate.validate_preparation(compiler);manifest=compiler.to_dict();assert manifest['all_candidates_supported'] and manifest['target']=='legal' and manifest['backend_executed'] is False
write('native-requests.json',requests);write('native-preparation-manifest.json',manifest)
for name,body in compiler.files:
 p=OUT/'native-prepared'/name;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as s:s.write(body)
blocked_requests=deepcopy(requests)+[dict(deepcopy(requests[0]),family='fol')];blocked=gate.prepare_source_family_legal(blocked_requests,toolchain='leanprover/lean4:v4.34.1');gate.validate_preparation(blocked);bm=blocked.to_dict();assert bm['status']=='blocked' and not bm['all_candidates_supported'] and bm['backend_executed'] is False and set(dict(blocked.files))=={'source-family-inputs.json'}
write('all_or_none_unsupported_batch.json',bm)
# Actual exposed statutory candidates receive unfilled declarations only.
real=read(F/'statutory-source-only-inputs.json');real_raw_path=R/'source_only-1729-ce0-law-none.json';joint_path=R/'source_only-1729-ce0-law-none-joint.json';real_raw=read(real_raw_path);joint=read(joint_path);assert real_raw['checkpoint_sha256']==state_digest;dispositions=[]
for lane in ('raw','joint'):
 for pos,source in enumerate(real['rows']):
  options={'joint_report':joint,'expected_joint_report_sha256':adapter.digest(joint)} if lane=='joint' else {}
  base={'id':source['id'],'position':pos,'lane':lane,'original_saved_status':(joint['rows'][pos]['result']['status'] if lane=='joint' else real_raw['rows'][pos]['decoder_row']['status']),'semantic_accuracy':None,'admitted':False,'declaration_filled':False,'compiler_executed':False}
  try:
   p=adapter.prepare_pending(source,real_raw,expected_report_sha256=adapter.digest(real_raw),expected_checkpoint_sha256=state_digest,row_id=source['id'],**options);blank=adapter.declaration_skeleton(p)
   assert blank['occurrence']['occurrence_id'] is None and blank['occurrence']['modality_anchor']['start_char'] is None
   rejection=must_refuse('real_blank_declaration',lambda:adapter.prepare_family(p,blank,expected_packet_sha256=adapter.digest(p)))
   base.update(status='pending_caller_declaration',blank_native_refusal=rejection,outputs=[write(f'statutory/{lane}-{pos:02d}-pending.json',p),write(f'statutory/{lane}-{pos:02d}-blank-declaration.json',blank)])
  except adapter.SavedSpanFamilyError as error:base.update(status='saved_proposal_or_profile_refused',reason=str(error))
  dispositions.append(base)
assert len(dispositions)==16
# Replay actual empty human review data through the new consistency owner.
packet_path=J/'statutory-source-review-packet.json';review_packet=read(packet_path);recording=read(H/'statutory-review-pending-recording.json');bindings=read(N/'source-artifact-pins.json');provenance=pin(N/'source-view-provenance.json');bindings[provenance['sha256']]=provenance
used={}
def resolver(ref):
 value=bindings[ref['sha256']];assert value['bytes']==ref['bytes'] and pin(value['path'])==value;used[value['path']]=value;return Path(value['path'])
expected=preflight.digest(review_packet);pf=preflight.preflight_declarations(review_packet,[],expected_packet_sha256=expected,artifact_resolver=resolver,recording=recording);replay=preflight.validate_preflight(pf,review_packet,[],expected_packet_sha256=expected,artifact_resolver=resolver,recording=recording)
assert pf['status']=='pending' and pf['item_count']==8 and pf['submission_count']==pf['declaration_count']==pf['gold_labels_created']==0 and all(v==0 for v in pf['admission_masks'].values())
write('actual-statutory-preflight.json',pf);write('actual-statutory-preflight-replay.json',replay)
loaded={}
for name,module in list(sys.modules.items()):
 if name.startswith('ipfs_datasets_py.') and getattr(module,'__file__',None):
  p=Path(module.__file__).resolve()
  if p.is_file():assert ROOT.resolve() in p.parents,(name,p);loaded[name]=pin(p)
input_pins=[pin(F/n) for n in ('authored-development-source-only-v02.json','authored-development-cue-declarations-v02.json','statutory-source-only-inputs.json','prepare_formal_output_pilot.py','bootstrap_inert.py')]+[pin(raw_path),pin(state_path),pin(real_raw_path),pin(joint_path),pin(packet_path),pin(H/'statutory-review-pending-recording.json'),*used.values()]
outputs=[pin(p) for p in sorted(OUT.rglob('*')) if p.is_file()]
summary={'schema':'saved-span-native-preparation-pilot/v1','passed':True,'findings':[],'scope':'Exposed synthetic engineering interpretations; exposed statutory proposals remain unadmitted/pending','development_requested':12,'native_requests_predeclared':9,'temporal_refused':3,'full_parent_report_rows':96,'development_outcomes':outcomes,'negative_controls':negative,'all_or_none_mixed_family_batch_blocked':True,'statutory_dispositions':dispositions,'statutory_original_rows':8,'statutory_lanes':2,'actual_review_items':8,'actual_human_submissions':0,'actual_semantic_labels':0,'semantic_accuracy':None,'model_calls':0,'encoder_calls':0,'optimizer_updates':0,'compiler_executed':False,'training_or_eval_admission':False,'source_only_dimension':384,'source_only_latent_enabled':False,'checkpoint_canonical_sha256':state_digest,'input_pins':input_pins,'loaded_producer_pins':loaded,'output_pins':outputs,'existing_native_gate_limits_unchanged':{'timeout_seconds':60,'Lean_threads':2,'sampled_tree_RSS_bytes':2147483648,'max_workspace_bytes':134217728,'max_output_bytes':262144,'max_input_bytes':8388608}}
write('preparation-summary.json',summary);print('Prepared9 native requests,3 temporal refusals,16 preserved law dispositions and empty8-item review; no compiler/model calls')
