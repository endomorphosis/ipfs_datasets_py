"""Detached recipe controls with synthetic traces/clearance metadata only; never run producer mains."""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parent;RUNNER=ROOT/'run_conditions_balanced_v01.py';PRIOR=ROOT.parent/'legal-head-repair-20261014-01'
SOURCE_STATE='c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
CELL='conditions-balanced-ce';ATTEMPT='conditions-balanced-20261014-'+CELL+'-01'
def require(value,message):
    if not value:raise ValueError(message)
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(raw(value)).hexdigest()
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def f32(value):return struct.unpack('!f',struct.pack('!f',value))[0]
def functions(p):return {n.name:n for n in ast.parse(p.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
def namespace():
 owners=functions(RUNNER);nodes=[owners[name] for name in ['qualify_capacity_clearance','qualify_conditions_trace']]
 require(not any(isinstance(n,(ast.Import,ast.ImportFrom)) for owner in nodes for n in ast.walk(owner)),'No selected imports')
 ns=dict(require=require,F=ROOT,CELL=CELL,ATTEMPT=ATTEMPT,SOURCE_STATE_SHA=SOURCE_STATE,math=math,struct=struct,digest=digest)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(RUNNER)+'#independent','exec'),ns);return ns

def clearance(*,full_fit):
 claims=44381777216;request=200000000;cap=145000000000
 observed=cap-claims-request-request-1000000 if full_fit else cap-claims-request-1000000
 free=claims+request+request+1000000
 value=dict(schema='conditions-balanced-capacity-clearance/v1',cell=CELL,attempt_name=ATTEMPT,passed=full_fit,
 ledger_record_count=538,record_status_counts=dict(released=437,retained=101),prior_record_body_hash_map_sha256='b3c68c6a50aa564532be42134e3d803a2ee25ecf48ff1f55034dcaa6ce032df3',all538_prior_record_bodies_unchanged=True,all_ten_resource_producer_pins_unchanged=True,
 observed_apparent_bytes=observed,outstanding_full_reservations_bytes=claims,additional_requested_bytes=request,future_own_output_bound_bytes=request,native_charged_bytes=observed+claims+request,full_run_charged_bound_bytes=observed+claims+2*request,limit_bytes=cap,minimum_filesystem_free_bytes=free,required_filesystem_free_bound_bytes=claims+2*request,full_run_apparent_headroom_bytes=cap-observed-claims-2*request,full_run_physical_headroom_bytes=free-claims-2*request,native_capacity_fits=True,full_run_capacity_fits=full_fit,findings=[] if full_fit else ['conservative full-run storage headroom refused before any claim or model'])
 for key,name in dict(observer='review_conditions_balanced_capacity_clearance_v01.py',source_qualification='capacity-clearance-source-independent-review-v01.json',input_manifest='capacity-clearance-inputs-v01.json',resource_contract='resource-protocol-contract-v01.json',baseline='resource-baseline-v01.json').items():value[key]=dict(path=str(ROOT/name),bytes=1,sha256='a'*64)
 value['baseline'].update(bytes=77889,sha256='9fd03480b85fb3b9a9164a4b4e87b4807bf8c65419a1037edccbb1b04723775f')
 for key in ['existing_baseline_modified','new_baseline_created','model_started','reservation_acquired','shared_state_modified','private_record_bodies_published','continuous_coverage_claimed','admission_guaranteed','future_output_bound_is_an_additional_claim','cap_or_claim_budget_changed']:value[key]=False
 for key in ['resource_API_calls','global_endpoint_body_reads','checkpoint_JSON_parses']:value[key]=0
 return value

def trace():
 names=['conditions_presence.weight','conditions_presence.bias'];part=dict(model_parameter_names=['frozen'+str(i) for i in range(40)]+names,frozen_parameter_names=['frozen'+str(i) for i in range(40)],trainable_parameter_names=names,optimizer_parameter_order=names,stored_trainable_scalar_count=520,active_trainable_scalar_count=130,inactive_stored_scalar_count=390,active_head_rows=[2,3],inactive_head_rows=[0,1,4,5,6,7])
 policy=dict(objective=CELL,inherited_optimizer_moments=False,optimizer=dict(name='Adam',learning_rate=.001,betas=[.9,.999],eps=1e-8,weight_decay=0.,foreach=False,gradient_clip_norm=5.),objective_policy=dict(conditions_pair_cross_entropy=True,mean_all_batch_rows=True,actor_ranking_enabled=False,training_row_reweighting=True,class_balance=dict(class_order=['absent','present'],counts=dict(absent=96,present=72),weights_rational=[[7,8],[7,6]],weights=[7/8,7/6],weight_rule='training_count/(2*class_count)',counts_source='authenticated_training168_conditions_presence_only',normalization='fixed_batch_row_count'),source_order='unchanged_targeted_seed1729_epoch_permutation',batch_order_seed=1729,batch_size=12))
 keys=['modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256','span_path_state_sha256','dormant_latent_state_sha256','frozen_base34_state_sha256','actor_head_state_sha256','inactive_actor_head_rows_sha256','actor_attention_query_sha256','actor_context_gate_sha256','frozen_parent40_state_sha256','conditions_presence_state_sha256','inactive_conditions_presence_rows_sha256']
 branches=dict.fromkeys(keys,'1'*64);branches['frozen_parent40_state_sha256']=SOURCE_STATE;initial=dict(branches);batches=[];objectives=[];freezes=[]
 for step in range(1,33):
  indices=[((step-1)*12+i)%168 for i in range(12)];ids=['r'+str(i) for i in indices];rows=[]
  for i,(index,identifier) in enumerate(zip(indices,ids)):
   present=i>=6;weight=f32(7/6 if present else 7/8);cost=f32(math.log(2))
   rows.append(dict(id=identifier,training_index=index,conditions_present=present,conditions_logits=[0.,0.],class_weight=weight,unweighted_cross_entropy=cost,weighted_cross_entropy=f32(weight*cost)))
  balanced=f32(sum(r['weighted_cross_entropy'] for r in rows)/12);batch=dict(optimizer_step=step,indices=indices,ids=ids,loss=balanced);batches.append(batch)
  details=dict(total_loss=balanced,conditions_cross_entropy_balanced=balanced,conditions_cross_entropy_unweighted=f32(math.log(2)),batch_denominator=12,rows=rows,batch_class_counts=dict(absent=6,present=6),batch_weight_sum=f32(sum(r['class_weight'] for r in rows)),teacher_forcing=True,evaluation_references_used=False,actor_hinge_applied=False)
  common={k:batch[k] for k in ['optimizer_step','indices','ids']};objectives.append(dict(common,details=details));after=dict(branches);after['conditions_presence_state_sha256']=format(step,'064x')
  freezes.append(dict(common,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,inactive_moments_zero=True,completed_returned_update=True,frozen_before=SOURCE_STATE,frozen_after=SOURCE_STATE,inactive_before='1'*64,inactive_after='1'*64,changed_parameter_names=names,branch_digests_before=dict(branches),branch_digests_after=after));branches=after
 report=dict(training_conditions_class_counts=dict(absent=96,present=72),training_policy=policy,parameter_partition=part,frozen_parent40_sha256_initial=SOURCE_STATE,frozen_parent40_sha256_final=SOURCE_STATE,inactive_head_rows_sha256_initial='1'*64,inactive_head_rows_sha256_final='1'*64,batch_trace=dict(batches=batches),initial_branch_digests=initial,training_call_initial_branch_digests=initial,final_branch_digests=branches,forward_accounting=dict(training_model_forward_calls=32,training_frozen_actor_features_model_calls=32,training_modality_encoder_calls=32,training_conditions_presence_head_calls=32,training_span_encoder_calls=64,training_source_row_occurrences=384,actual_model_counter_deltas=dict.fromkeys(['source_model_forwards','frozen_actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'],32)))
 for kind,entries in [('objective',objectives),('freeze',freezes)]:report[kind+'_trace']=dict(schema='completed-conditions-balanced-adapter-'+kind+'-trace/v1',completed_updates=32,batches=entries,batches_sha256=digest(entries),independent_numerical_kernel_trace=False)
 return report

def main():
 ns=namespace();cases=[];c=clearance(full_fit=True);require(ns['qualify_capacity_clearance'](c,for_training=True) is True,'PASS refused');cases.append('Exact full-run capacity PASS accepted')
 refused=clearance(full_fit=False);require(ns['qualify_capacity_clearance'](refused,for_training=False) is False,'Metadata prep cannot preserve refusal')
 try:ns['qualify_capacity_clearance'](refused,for_training=True)
 except ValueError:pass
 else:raise AssertionError('Native-only capacity passed training')
 cases.append('Native capacity alone insufficient; explicit full-run refusal inspectable but training blocked')
 for key,value in [('future_own_output_bound_bytes',0),('ledger_record_count',537),('admission_guaranteed',True),('model_started',True),('limit_bytes',146000000000),('full_run_charged_bound_bytes',c['full_run_charged_bound_bytes']-1)]:
  bad=copy.deepcopy(c);bad[key]=value
  try:ns['qualify_capacity_clearance'](bad,for_training=True)
  except ValueError:pass
  else:raise AssertionError('Invalid clearance accepted '+key)
  cases.append('Capacity rejects altered '+key)
 report=trace();ns['qualify_conditions_trace'](report);cases.append('Complete32 weighted fixed12 traces/13branchchain/42geometry/384occurrences accepted')
 for label,change in [('rowweight',lambda r:r['objective_trace']['batches'][0]['details']['rows'][0].update(class_weight=f32(7/6))),('normalization',lambda r:r['training_policy']['objective_policy']['class_balance'].update(normalization='sum_class_weights')),('weightedmean',lambda r:r['objective_trace']['batches'][0]['details'].update(total_loss=f32(math.log(2)),conditions_cross_entropy_balanced=f32(math.log(2)))),('frozenquery',lambda r:r['freeze_trace']['batches'][0]['branch_digests_after'].update(actor_attention_query_sha256='f'*64)),('inactiveMoments',lambda r:r['freeze_trace']['batches'][0].update(inactive_moments_zero=False))]:
  bad=copy.deepcopy(report);change(bad)
  for kind in ['objective','freeze']:bad[kind+'_trace']['batches_sha256']=digest(bad[kind+'_trace']['batches'])
  if label=='weightedmean':bad['batch_trace']['batches'][0]['loss']=f32(math.log(2))
  try:ns['qualify_conditions_trace'](bad)
  except ValueError:pass
  else:raise AssertionError('Invalid weighted trace accepted '+label)
  cases.append('Trace rejects '+label+' even after tracehash refresh')
 # Source-only ordering proof; do not execute main or monkeypatch model/data calls.
 owner=functions(RUNNER)['main'];calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(owner) if isinstance(n,ast.Call)]
 clearance_line=min(line for line,name in calls if name=='qualify_capacity_clearance')
 require(all(clearance_line<line for line,name in calls if name in ['out.mkdir','helper.bootstrap','actor.build_checkpoint','actor.train_decoder']),'Capacity gate after model or mutation')
 torch_line=min(n.lineno for n in ast.walk(owner) if isinstance(n,ast.Import) and any(v.name=='torch' for v in n.names));require(clearance_line<torch_line,'Capacity after numerical import')
 cases.append('Full-run PASS lexically precedes outputdir/bootstrap/numerical import/build/train')
 return dict(schema='conditions-balanced-recipe-independent-controls/v1',passed=True,findings=[],case_count=len(cases),cases=cases,source=pin(RUNNER),controls=pin(Path(__file__).resolve()),actual_model_or_numerical_calls=0,actual_checkpoint_or_data_or_reference_or_private_body_reads=0,actual_producer_main_calls=0,scope='Detached AST-selected pure validators and synthetic metadata/traces; no actual source bootstrap, resource endpoints or model work.')

if __name__=='__main__':
 value=main();p=ROOT/'recipe-independent-controls-v01.json'
 with p.open('x') as stream:json.dump(value,stream,sort_keys=True,separators=(',',':'),allow_nan=False)
 p.chmod(0o444);print(pin(p))
