"""Detached stdlib recipe controls; no production main or numerical imports."""
import ast
import builtins
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import re
import struct
from types import SimpleNamespace

F=Path(__file__).resolve().parent
RUNNER=F/'run_actor_refinement_v02.py'
MODEL=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_refinement.py'
TEST=F/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_refinement_contracts.py'
OUTPUT=F/'recipe-independent-detached-controls-v02.json'

def require(value,message):
    if not value:raise ValueError(message)
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def detach(path,names,scope):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in nodes}==set(names),'exact detached definitions')
    require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'detached imports denied')
    scope['__builtins__']=dict(vars(builtins),__import__=lambda *a,**k:(_ for _ in ()).throw(ValueError('imports denied')))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#detached','exec'),scope)

def main():
    ns=dict(__file__=str(TEST),SOURCE=MODEL,ast=ast,builtins=builtins,copy=copy,hashlib=hashlib,json=json,math=math,Path=Path,random=random,re=re,struct=struct,SimpleNamespace=SimpleNamespace)
    detach(TEST,{'require','raw','digest','deny','selected','namespace','fixture','moments','feature_entry'},ns)
    actor_ns=ns['namespace']();parent,rows,cp=ns['fixture'](actor_ns)
    actor=SimpleNamespace(**{k:actor_ns[k] for k in ('TRAINABLE_PARAMETER_NAMES','_validate_policy','_partition','_validate_objective_entry','_validate_freeze_entry','_validate_feature_entry')})
    scope=dict(require=require,digest=digest,canonical=canonical,hashlib=hashlib,math=math,struct=struct,CELL='actor-refinement-ce',SOURCE_SHA='34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd',SOURCE_STATE_SHA='b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9',importlib=SimpleNamespace(import_module=lambda name:actor))
    detach(RUNNER,{'qualify_actor_trace','completion','binary','compare_captures','merged_training_capture'},scope)
    helper=dict(hashlib=hashlib)
    detach(TEST.with_name('test_legal_span_actor_features_contracts.py'),{'objective_diagnostics'},helper)
    policy=actor_ns['_policy']('actor-refinement-ce');before=actor_ns['_branch_digests'](cp['model_state']);initial=copy.deepcopy(before)
    batches=[];objectives=[];freezes=[];features=[];progress=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0)
    records=actor_ns['_training_records'](rows)
    for step in range(1,33):
        indices=actor_ns['targeted']._batch_indices(168,progress,12,1729);progress=actor_ns['targeted']._advance_progress(progress,len(indices),168)
        batch=dict(optimizer_step=step,indices=indices,ids=[rows[i]['id'] for i in indices],loss=1.75)
        rec=[records[i] for i in indices];base=helper['objective_diagnostics'](actor_ns,rec,enabled=False)
        details=dict(base_objective=base,total_loss=1.75,batch_denominator=12,rows=[dict(id=r['id'],training_index=i,token_count=3,actor_gold_coordinates=[0,0],actor_present=True) for i,r in zip(indices,rec,strict=True)],evaluation_references_used=False,teacher_forcing=True)
        objective={k:copy.deepcopy(batch[k]) for k in ('optimizer_step','indices','ids')};objective['details']=details
        after=copy.deepcopy(before)
        for key in ('actor_head_state_sha256','actor_attention_query_sha256','actor_context_gate_sha256'):after[key]=digest([step,key])
        freeze=dict(optimizer_step=step,indices=indices,ids=list(batch['ids']),source_frozen36_state_sha256=cp['source_frozen36_state_sha256'],frozen_before=before['frozen_nonactor36_state_sha256'],frozen_after=after['frozen_nonactor36_state_sha256'],inactive_before=before['inactive_actor_head_rows_sha256'],inactive_after=after['inactive_actor_head_rows_sha256'],frozen_head_sample_sha256='f'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,inactive_gradients_zero=True,inactive_moments_zero=True,changed_parameter_names=list(actor.TRAINABLE_PARAMETER_NAMES),completed_returned_update=True,branch_digests_before=copy.deepcopy(before),branch_digests_after=copy.deepcopy(after))
        feature,_=ns['feature_entry']();feature.update(optimizer_step=step,indices=indices,ids=list(batch['ids']),trained_start_requirements_checked=step==1)
        for label,key in (('query','actor_attention_query_sha256'),('gate','actor_context_gate_sha256')):feature[label+'_before_sha256']=before[key];feature[label+'_after_sha256']=after[key]
        batches.append(batch);objectives.append(objective);freezes.append(freeze);features.append(feature);before=after
    report=dict(training_policy=policy,parameter_partition=actor._partition(),optimizer_parameter_order=list(actor.TRAINABLE_PARAMETER_NAMES),stored_trainable_scalar_count=908,active_trainable_scalar_count=258,source_conditions_presence_checkpoint_sha256=scope['SOURCE_SHA'],source_conditions_presence_model_state_sha256=scope['SOURCE_STATE_SHA'],source_conditions_presence_optimizer_steps=32,training_call_initial_model_state_sha256=scope['SOURCE_STATE_SHA'],initial_model_state_sha256=scope['SOURCE_STATE_SHA'],continuation_optimizer_steps_total=32,source_frozen36_state_sha256=cp['source_frozen36_state_sha256'],frozen_parent36_sha256_initial=cp['source_frozen36_state_sha256'],frozen_parent36_sha256_final=cp['source_frozen36_state_sha256'],frozen_parameters_sha256_initial=cp['source_frozen36_state_sha256'],frozen_parameters_sha256_final=cp['source_frozen36_state_sha256'],inactive_head_rows_sha256_initial=initial['inactive_actor_head_rows_sha256'],inactive_head_rows_sha256_final=initial['inactive_actor_head_rows_sha256'],batch_trace=dict(batches=batches,training_count=168,training_manifest_sha256=digest(rows)),training_call_initial_branch_digests=initial,initial_branch_digests=initial,final_branch_digests=before,changed_parameter_names=list(actor.TRAINABLE_PARAMETER_NAMES),feature_learning=dict(query_changed_updates=32,gate_changed_updates=32,query_nonzero_gradient_updates=32,gate_nonzero_gradient_updates=32,context_nonzero_gradient_updates=32,residual_nonzero_gradient_updates=32),forward_accounting=dict(training_model_forward_calls=32,training_actor_features_model_calls=32,training_modality_encoder_calls=32,training_conditions_presence_head_calls=32,training_span_encoder_calls=64,training_source_row_occurrences=384,actual_model_counter_deltas=dict.fromkeys(('source_model_forwards','actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'),32),tuning_model_forward_calls=0,teacher_model_forward_calls=0))
    for kind,values in (('objective',objectives),('freeze',freezes),('feature',features)):
        report[kind+'_trace']=dict(schema='completed-actor-refinement-adapter-'+kind+'-trace/v1',completed_updates=32,batches=values,batches_sha256=digest(values),independent_numerical_kernel_trace=False)
    report['objective_trace']['evaluation_references_used']=False
    scope['qualify_actor_trace'](report)
    passed=['complete32_trained_first_query_changes_nonzero_gradients_and_moments_accepted']
    def refuses(label,mutation):
        bad=copy.deepcopy(report);mutation(bad)
        # Rehash rows to check semantic validators, rather than merely stale hashes.
        for kind in ('objective','freeze','feature'):bad[kind+'_trace']['batches_sha256']=digest(bad[kind+'_trace']['batches'])
        try:scope['qualify_actor_trace'](bad)
        except (ValueError,KeyError,TypeError):passed.append(label)
        else:raise AssertionError('mutation was accepted: '+label)
    refuses('wrong_N11_donor_rejected',lambda r:r.update(source_conditions_presence_checkpoint_sha256='e'*64))
    refuses('reset_initial_trained_state_rejected',lambda r:r.update(training_call_initial_model_state_sha256='e'*64))
    refuses('ranking_ON_rejected',lambda r:r['training_policy']['objective_policy'].update(actor_ranking_enabled=True))
    refuses('frozen_learned_conditions_change_rejected',lambda r:r['freeze_trace']['batches'][0]['branch_digests_after'].update(conditions_presence_state_sha256='e'*64))
    refuses('inactive_actor_change_rejected',lambda r:r['freeze_trace']['batches'][0].update(inactive_after='e'*64))
    refuses('feature_freshzero_assumption_rejected',lambda r:r['feature_trace']['batches'][0].update(fresh_zero_initialization_assumed=True))
    refuses('feature_freeze_query_join_mismatch_rejected',lambda r:r['feature_trace']['batches'][0].update(query_before_sha256='e'*64))
    refuses('nonfinite_feature_gradient_rejected',lambda r:r['feature_trace']['batches'][0].update(query_gradient_l2=-1.))
    refuses('interupdate_chain_change_rejected',lambda r:r['freeze_trace']['batches'][1]['branch_digests_before'].update(actor_head_state_sha256='e'*64))
    refuses('31_completed_updates_rejected',lambda r:r['feature_trace'].update(completed_updates=31))
    refuses('feature_learning_aggregate_mismatch_rejected',lambda r:r['feature_learning'].update(query_changed_updates=31))
    refuses('extra_training_forward_rejected',lambda r:r['forward_accounting'].update(training_model_forward_calls=33))
    # Completion must join source-frozen36 to the actual validated checkpoint.
    valid=copy.deepcopy(report);valid.update(optimizer_steps=32,stopped_reason='step_limit',batch_losses=[b['loss'] for b in batches])
    checkpoint=dict(progress=progress,training_policy=policy,source_frozen36_state_sha256=cp['source_frozen36_state_sha256']);valid['checkpoint_sha256']=digest(checkpoint)
    schedule=dict(final_progress=progress,batch_indices=[b['indices'] for b in batches],batch_ids=[b['ids'] for b in batches])
    scope['completion'](valid,checkpoint,schedule,rows);passed.append('completion_joins_checkpoint_subset_and_exact32_schedule')
    bad_checkpoint=copy.deepcopy(checkpoint);bad_checkpoint['source_frozen36_state_sha256']='e'*64;bad=copy.deepcopy(valid);bad['checkpoint_sha256']=digest(bad_checkpoint)
    try:scope['completion'](bad,bad_checkpoint,schedule,rows)
    except ValueError:passed.append('checkpoint_source_frozen36_mismatch_rejected')
    else:raise AssertionError('subset mismatch accepted')
    # Actual protected projection includes every presence pair and five nonactor pointers.
    score=dict(tokens=[dict(text='a',start=0,end=1)],modality_logits=[1.,0.,-0.],presence_logits=dict.fromkeys(('object','conditions','exceptions','temporal'),[1.,-0.]),start_logits=dict.fromkeys(('actor','action','object','conditions','exceptions','temporal'),[1.]),end_logits=dict.fromkeys(('actor','action','object','conditions','exceptions','temporal'),[2.]))
    source=dict(id='one',source_text='a');sha=hashlib.sha256(b'a').hexdigest();raw=dict(occurrences=[dict(id='one',source_sha256=sha,scores=score)],inference=dict(rows=[dict(status='decoded')]))
    docs={'before':raw,'after':copy.deepcopy(raw)};scope['read']=lambda path,expected:docs[path]
    before_pin=dict(raw=dict(path='before'));after_pin=dict(raw=dict(path='after'))
    docs['after']['occurrences'][0]['scores']['start_logits']['actor']=[3.]
    scope['compare_captures']([source],before_pin,after_pin,full=False);passed.append('protected_projection_allows_only_actor_pointer_change')
    for label,mutation in (('conditions_pair_bitflip_rejected',lambda s:s['presence_logits'].update(conditions=[2.,-0.])),('nonactor_pointer_bitflip_rejected',lambda s:s['end_logits'].update(temporal=[3.])),('signedzero_protected_bitflip_rejected',lambda s:s['modality_logits'].__setitem__(2,0.))):
        docs['after']=copy.deepcopy(raw);mutation(docs['after']['occurrences'][0]['scores'])
        try:scope['compare_captures']([source],before_pin,after_pin,full=False)
        except ValueError:passed.append(label)
        else:raise AssertionError('projection mutation accepted: '+label)
    value=dict(schema='actor-refinement-recipe-independent-detached-controls/v1',passed=True,findings=[],control_count=len(passed),controls=passed,source_artifacts={str(p):pin(p) for p in (Path(__file__).resolve(),RUNNER,MODEL,TEST)},numerical_imports=0,model_calls=0,production_main_calls=0,actual_checkpoint_or_reference_or_private_body_parses=0)
    with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))

if __name__=='__main__':main()
