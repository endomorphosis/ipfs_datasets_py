"""Detached summary/parity and concrete-reviewer boundary controls, no actual main."""
import ast
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

F=Path(__file__).resolve().parent
FREEZER=F/'freeze_actor_refinement_outputs_v02.py'
REVIEWER=F/'review_actor_refinement_training_plan_v02.py'
OUTPUT=F/'runtime-freeze-independent-detached-controls-v02.json'
def require(v,m):
    if not v:raise ValueError(m)
def pin(p):
    b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def detach(path,names,scope):
    nodes=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes}==set(names),'exact detached functions')
    require(not any(isinstance(c,(ast.Import,ast.ImportFrom)) for n in nodes for c in ast.walk(n)),'no detached imports')
    scope['__builtins__']=dict(vars(builtins),__import__=lambda *a,**k:(_ for _ in ()).throw(ValueError('imports denied')))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path)+'#detached','exec'),scope)
def main():
    panels=('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law','fresh_dev','fresh_test');counts=dict(zip(panels,(96,36,36,72,72,72,8,36,36),strict=True));prefix='ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    names=('legal_span_formula','legal_span_continuation','legal_span_targeted_loss','legal_span_split_features','legal_span_actor_boundary','legal_span_actor_features','legal_span_conditions_presence','legal_span_actor_refinement')
    owners={prefix+n:dict(path='/synthetic/'+n,bytes=1,sha256='a'*64) for n in names}
    owners.update({'synthetic-owner-'+str(i):dict(path='/synthetic/other-'+str(i),bytes=1,sha256='b'*64) for i in range(8)})
    helper=SimpleNamespace(NoEncoder=lambda:object(),bootstrap=lambda path:None);retained=SimpleNamespace(helpers=lambda:helper);legacy=SimpleNamespace(prior_runner=lambda:retained)
    r=SimpleNamespace(require=require,PANELS=panels,FRESH_PANELS=panels[-2:],COUNTS=counts,CELL='actor-refinement-ce',ATTEMPT='actor-refinement-20261014-actor-refinement-ce-01',SOURCE_SHA='c'*64,SOURCE_STATE_SHA='d'*64,legacy_runner=lambda:legacy,qualify_actor_trace=lambda report:None)
    ns=dict(r=r,sys=SimpleNamespace(meta_path=[]),Path=Path);detach(FREEZER,{'expected_names','qualify_training_summary','qualify_gates'},ns)
    require(len(ns['expected_names']())==62 and len({x for x in ns['expected_names']() if x.startswith('parent-')})==6,'exact62/six copied parent files')
    refs={n:dict(raw=dict(path='/synthetic/'+n+'-raw',bytes=2,sha256='e'*64),joint=dict(path='/synthetic/'+n+'-joint',bytes=2,sha256='f'*64)) for n in (*panels,'training168')}
    plan=dict(package_root='/synthetic/package',expected_loaded_owner_count=16,source_owner_pins=owners,training_manifest_sha256='1'*64,source_reference_panels=refs)
    batches=[dict(indices=list(range(12)),ids=['s'+str(i) for i in range(12)],loss=1.) for _ in range(32)]
    summary=dict(schema='actor-refinement-cell-results/v1',status='completed',cell=r.CELL,attempt_name=r.ATTEMPT,actual_new_updates=32,successful_output_file_count=62,actual_external_encoder_calls=0,latent_enabled=False,opening_owners=owners,closing_owners=owners,checkpoint=dict(sha256='2'*64),final_model_state_sha256='3'*64,source_checkpoint=dict(sha256=r.SOURCE_SHA),source_model_state_sha256=r.SOURCE_STATE_SHA,source_optimizer_steps=32,fresh_Adam=True,inherited_optimizer_moments=False,candidate_training_capture_call_sizes=[128,40],parent_training_capture_call_sizes=[128,40],prepared_schedule=dict(batch_indices=[b['indices'] for b in batches],batch_ids=[b['ids'] for b in batches]))
    summary.update(total_inference_source_forwards=1280,actual_training_model_forwards=32,total_actual_model_forwards=1312,training_batch_source_occurrences=384,total_model_source_occurrences=1664,candidate_conditions_presence_inference_calls=1280,actual_conditions_presence_head_calls=1312,reused_parent_capture_file_count=6,reused_parent_capture_rows=240,new_parent_control_forwards=0,candidate_diagnostic_source_forwards=928,candidate_training_capture_source_forwards=336,dormant_control_source_forwards=16,parent_extra_source_forwards=0,feature_paths_per_source_forward=3)
    summary['reused_parent_captures']={label:refs[p] for label,p in (('parent-training168','training168'),('parent-fresh_dev','fresh_dev'),('parent-fresh_test','fresh_test'))}
    report=dict(schema='bounded-actor-refinement-adapter-training/v1',optimizer_steps=32,stopped_reason='step_limit',training_policy=dict(objective=r.CELL),optimizer_parameter_order=['actor_start.weight','actor_start.bias','actor_end.weight','actor_end.bias','actor_attention.query','actor_context.gate'],checkpoint_sha256='2'*64,final_model_state_sha256='3'*64,source_conditions_presence_checkpoint_sha256=r.SOURCE_SHA,source_conditions_presence_model_state_sha256=r.SOURCE_STATE_SHA,source_conditions_presence_optimizer_steps=32,batch_trace=dict(completed_updates=32,training_count=168,training_manifest_sha256='1'*64,batches=batches),batch_losses=[1.]*32)
    ns['qualify_training_summary'](plan,summary,report);passed=['exact62_geometry_with_six_saved_parent_files','valid_trained_N11_actor6_summary_1280plus32_1664']
    def refuse_summary(label,mutate):
        s,t=copy.deepcopy(summary),copy.deepcopy(report);mutate(s,t)
        try:ns['qualify_training_summary'](plan,s,t)
        except (ValueError,KeyError):passed.append(label)
        else:raise AssertionError(label)
    refuse_summary('old1552_forward_count_rejected',lambda s,t:s.update(total_actual_model_forwards=1552))
    refuse_summary('new_parent_control_forward_rejected',lambda s,t:s.update(new_parent_control_forwards=1))
    refuse_summary('15_loaded_source_closure_rejected',lambda s,t:s.update(opening_owners=dict(list(s['opening_owners'].items())[:-1])))
    refuse_summary('wrong_objective_rejected',lambda s,t:t['training_policy'].update(objective='conditions-presence-ce'))
    refuse_summary('reused_capture_custody_change_rejected',lambda s,t:s['reused_parent_captures'].update({'parent-fresh_dev':refs['fresh_test']}))
    refuse_summary('different_donor_state_rejected',lambda s,t:t.update(source_conditions_presence_model_state_sha256='4'*64))
    initial=dict(schema='actor-refinement-initial-parent-parity/v1',source_rows=632,all_compared_components_bit_equal=True,optimizer_updates_before_gate=0,rows={p:[None]*(168 if p=='training168' else counts[p]) for p in (*panels,'training168')})
    final=dict(schema='actor-refinement-frozen-head-retention/v1',source_rows=632,all_compared_components_bit_equal=True,compared_all_boundaries=False,compared_conditions_presence=True,compared_nonactor_boundaries=True,compared_actor_boundaries=False,compared_other_three_presence=True,compared_modality=True,rows=copy.deepcopy(initial['rows']))
    ns['qualify_gates'](initial,final);passed.append('all632_initial_and_final_conditions_nonactor_projection_required')
    for label,mutate in (('conditions_not_protected_rejected',lambda i,f:f.update(compared_conditions_presence=False)),('631_coverage_rejected',lambda i,f:f['rows']['law'].pop()),('update_before_initial_parity_rejected',lambda i,f:i.update(optimizer_updates_before_gate=1))):
        i,f=copy.deepcopy(initial),copy.deepcopy(final);mutate(i,f)
        try:ns['qualify_gates'](i,f)
        except ValueError:passed.append(label)
        else:raise AssertionError(label)
    audit_ns=dict(os=os,Path=Path,OUTPUT=F/'actor-refinement-ce-training-review-v01.json');detach(REVIEWER,{'require','audit'},audit_ns)
    for event,args in (('import',('torch',)),('import',('ipfs_datasets_py',)),('socket.connect',()),('fcntl.flock',()),('open',('/tmp/disk-reservations.json','r',os.O_RDONLY)),('open',('/tmp/unowned-review.json','x',os.O_WRONLY|os.O_CREAT|os.O_EXCL))):
        try:audit_ns['audit'](event,args)
        except ValueError:passed.append('concrete_reviewer_refuses_'+event+'_'+str(args[0] if args else ''))
        else:raise AssertionError('unsafe audit operation allowed')
    audit_ns['audit']('open',(str(audit_ns['OUTPUT']),'x',os.O_WRONLY|os.O_CREAT|os.O_EXCL));passed.append('concrete_reviewer_only_exclusive_owned_output_allowed')
    result=dict(schema='actor-refinement-freezer-independent-detached-controls/v1',passed=True,findings=[],controls=passed,control_count=len(passed),source_artifacts={str(p):pin(p) for p in (Path(__file__).resolve(),FREEZER,REVIEWER)},scope='Freezer summary/gate validators detached with inert bootstrap/actor trace stub; runner full32 trace independently checked in separate19controls; reviewer audit receives synthetic events only',actual_model_calls=0,numerical_imports=0,production_main_calls=0,actual_checkpoint_or_reference_or_private_body_reads=0)
    with OUTPUT.open('x') as out:json.dump(result,out,sort_keys=True,indent=2);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))
if __name__=='__main__':main()
