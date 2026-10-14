"""Synthetic weighted-loss and acceptance fixtures; no model/data/reference imports."""
import ast
from copy import deepcopy
import hashlib,json,math,re,stat,struct
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
STATE='c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
FIELDS=('actor','action','object','conditions','exceptions','temporal')
PANELS=('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law','fresh_dev','fresh_test')

def compile_functions(path,names,env):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<detached-balanced-eval>','exec'),env)

def identity(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def main():
    analysis=F/'analyze_conditions_balanced_v01.py';recount=F/'review_conditions_balanced_result_recount_v01.py'
    env=dict(Path=Path,math=math,json=json,hashlib=hashlib,re=re,struct=struct,stat=stat,ast=ast,SimpleNamespace=SimpleNamespace,
        SOURCE_STATE=STATE,FIELDS=FIELDS,PANELS=PANELS,EXPECTED={},OBSERVED={})
    compile_functions(analysis,{'require','canonical','digest','private','pin','detached','f32','training_metadata'},env)
    second=dict(math=math,json=json,hashlib=hashlib,struct=struct)
    compile_functions(recount,{'require','digest','f32','recount_training'},second)
    f32=env['f32'];training=[dict(id='synthetic-'+str(i),canonical_ir=dict(rules=[dict(conditions=[] if i<96 else ['x'])])) for i in range(168)]
    indices=list(range(8))+list(range(96,100));ids=[training[i]['id'] for i in indices];names=['conditions_presence.weight','conditions_presence.bias']
    branches=dict.fromkeys(['modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256','span_path_state_sha256','dormant_latent_state_sha256','frozen_base34_state_sha256','actor_head_state_sha256','inactive_actor_head_rows_sha256','actor_attention_query_sha256','actor_context_gate_sha256','frozen_parent40_state_sha256','conditions_presence_state_sha256','inactive_conditions_presence_rows_sha256'],'a'*64)
    branches['frozen_parent40_state_sha256']=STATE;branches['inactive_conditions_presence_rows_sha256']='b'*64
    rows=[]
    for i in indices:
        truth=i>=96;logits=[0.,0.];ce=f32(math.log(2));weight=f32(7/6 if truth else 7/8)
        rows.append(dict(id=training[i]['id'],training_index=i,conditions_present=truth,conditions_logits=logits,class_weight=weight,unweighted_cross_entropy=ce,weighted_cross_entropy=f32(ce*weight)))
    weighted=f32(math.fsum(row['weighted_cross_entropy'] for row in rows)/12);unweighted=f32(math.fsum(row['unweighted_cross_entropy'] for row in rows)/12)
    details=dict(conditions_cross_entropy_unweighted=unweighted,conditions_cross_entropy_balanced=weighted,total_loss=weighted,batch_denominator=12,batch_class_counts=dict(absent=8,present=4),batch_weight_sum=f32(math.fsum(row['class_weight'] for row in rows)),rows=rows,teacher_forcing=True,evaluation_references_used=False,actor_hinge_applied=False)
    batches=[dict(optimizer_step=i,indices=indices,ids=ids,loss=weighted) for i in range(1,33)]
    objectives=[dict(**{k:b[k] for k in ['optimizer_step','indices','ids']},details=deepcopy(details)) for b in batches]
    freezes=[dict(**{k:b[k] for k in ['optimizer_step','indices','ids']},frozen_before=STATE,frozen_after=STATE,inactive_before='b'*64,inactive_after='b'*64,frozen_head_sample_sha256='c'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,inactive_moments_zero=True,changed_parameter_names=names,completed_returned_update=True,branch_digests_before=deepcopy(branches),branch_digests_after=deepcopy(branches)) for b in batches]
    partition=dict(model_parameter_names=list(range(42)),frozen_parameter_names=list(range(40)),trainable_parameter_names=names,optimizer_parameter_order=names,stored_trainable_scalar_count=520,active_trainable_scalar_count=130,inactive_stored_scalar_count=390,active_head_rows=[2,3],inactive_head_rows=[0,1,4,5,6,7])
    objective_policy=dict(conditions_pair_cross_entropy=True,mean_all_batch_rows=True,actor_ranking_enabled=False,training_row_reweighting=True,source_order='unchanged_targeted_seed1729_epoch_permutation',batch_order_seed=1729,batch_size=12,class_balance=dict(class_order=['absent','present'],counts=dict(absent=96,present=72),weights_rational=[[7,8],[7,6]],weights=[7/8,7/6],weight_rule='training_count/(2*class_count)',counts_source='authenticated_training168_conditions_presence_only',normalization='fixed_batch_row_count'))
    trace=lambda kind,rows:dict(schema='completed-conditions-balanced-adapter-'+kind+'-trace/v1',completed_updates=32,batches=rows,batches_sha256=env['digest'](rows),independent_numerical_kernel_trace=False,**({'evaluation_references_used':False} if kind=='objective' else {}))
    report=dict(schema='bounded-conditions-balanced-adapter-training/v1',optimizer_steps=32,continuation_optimizer_steps_total=32,conditions_training_count=168,training_conditions_class_counts=dict(absent=96,present=72),stopped_reason='step_limit',optimizer_parameter_order=names,parameter_partition=partition,stored_trainable_scalar_count=520,active_trainable_scalar_count=130,frozen_parent40_sha256_initial=STATE,frozen_parent40_sha256_final=STATE,inactive_head_rows_sha256_initial='b'*64,inactive_head_rows_sha256_final='b'*64,changed_parameter_names=names,training_policy=dict(schema='bounded-conditions-balanced-adapter-policy/v1',objective='conditions-balanced-ce',parameter_partition=partition,objective_policy=objective_policy,optimizer=dict(name='Adam',learning_rate=.001,betas=[.9,.999],eps=1e-8,weight_decay=0.,foreach=False,gradient_clip_norm=5.),inherited_optimizer_moments=False,latent_enabled=False,evaluation_references_used=False),batch_trace=dict(batches=batches,training_manifest_sha256=env['digest'](training)),objective_trace=trace('objective',objectives),freeze_trace=trace('freeze',freezes),initial_branch_digests=deepcopy(branches),final_branch_digests=deepcopy(branches),forward_accounting=dict(training_model_forward_calls=32,training_source_row_occurrences=384,actual_model_counter_deltas=dict(a=32,b=32),training_span_encoder_calls=64,training_modality_encoder_calls=32,training_conditions_presence_head_calls=32,tuning_model_forward_calls=0,teacher_model_forward_calls=0),tuning=dict(rows_evaluated=0))
    schedule=dict(batch_indices=[indices]*32,batch_ids=[ids]*32)
    namespace=dict(plan=dict(source_owner_pins={'model':dict(path=str(F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'))}),summary=dict(prepared_schedule=schedule))
    source=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'
    env['pin'](source,identity(source))
    def run(value):
        env['training_metadata'](value,training,namespace)
        second['recount_training'](value,training,schedule)
    run(report);cases=['Two independent weighted validators accept fixed12 mean with non12 weight sum']
    def wrong_normalization(r):
        for entry,batch in zip(r['objective_trace']['batches'],r['batch_trace']['batches'],strict=True):
            value=entry['details'];loss=f32(math.fsum(x['weighted_cross_entropy'] for x in value['rows'])/value['batch_weight_sum']);value['conditions_cross_entropy_balanced']=value['total_loss']=batch['loss']=loss
    mutations=[('Wrong batch-weight denominator',wrong_normalization),('Wrong rational training weight',lambda r:r['training_policy']['objective_policy']['class_balance'].__setitem__('weights_rational',[[1,1],[1,1]])),('Wrong actualfloat32 row weight',lambda r:r['objective_trace']['batches'][0]['details']['rows'][0].__setitem__('class_weight',1.)),('Wrong weighted float32 product',lambda r:r['objective_trace']['batches'][0]['details']['rows'][0].__setitem__('weighted_cross_entropy',0.)),('Wrong separate unweighted mean',lambda r:r['objective_trace']['batches'][0]['details'].__setitem__('conditions_cross_entropy_unweighted',0.)),('Wrong batch class counts',lambda r:r['objective_trace']['batches'][0]['details'].__setitem__('batch_class_counts',dict(absent=6,present=6)))]
    for label,mutate in mutations:
        bad=deepcopy(report);mutate(bad);bad['objective_trace']['batches_sha256']=env['digest'](bad['objective_trace']['batches'])
        for fn in [lambda:env['training_metadata'](bad,training,namespace),lambda:second['recount_training'](bad,training,schedule)]:
            try:fn()
            except ValueError:pass
            else:raise AssertionError(label)
        cases.append(label+' refused by both implementations')
    result=dict(schema='conditions-balanced-evaluation-author-controls/v1',passed=True,findings=[],case_count=len(cases),cases=cases,analyzer=identity(analysis),recount=identity(recount),controls_source=identity(Path(__file__).resolve()),model_source_hash_only=identity(F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'),actual_outputs_or_gold_read=0,checkpoint_JSON_parses=0,model_calls=0,numerical_imports=0,private_body_reads=0,resource_API_calls=0)
    output=F/'evaluation-author-controls-v01.json'
    with output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    output.chmod(0o444);print(json.dumps(identity(output)))

if __name__=='__main__':main()
