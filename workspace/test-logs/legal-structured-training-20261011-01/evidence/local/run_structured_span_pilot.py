"""One guarded equal-step CE/structured continuation experiment.

Authored TRAIN/TUNE only. Exposed law8 is source-only and diagnostic. No encoder,
teacher, challenge/OOV targets, model selection, Lean or default promotion.
Each fitted checkpoint/report is durably saved before any later diagnostics.
"""
from contextlib import ExitStack
import argparse
import ctypes.util
import importlib
import importlib.abc
import json
import math
import os
from pathlib import Path
import sys
import time
from types import ModuleType
from unittest.mock import patch

from prepare_structured_span_pilot import canonical, digest, pin, read, write

STATE={'created_output':None,'stage':'preparation','completed_updates':0,'saved_states':[],
    'in_progress_arm_updates_unknown':False,
    'update_counter_scope':'returned completed or soft-deadline arm reports only; exceptions inside an arm do not establish its update count'}

def require(value,message):
    if not value: raise ValueError(message)

def bootstrap(root):
    sys.path.insert(0,str(root))
    for name in ('ipfs_datasets_py','ipfs_datasets_py.logic','ipfs_datasets_py.logic.legal_ir',
        'ipfs_datasets_py.logic.formalization','ipfs_datasets_py.logic.formalization.autoencoder',
        'ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer','ipfs_datasets_py.utils'):
        module=ModuleType(name);module.__path__=[str(root.joinpath(*name.split('.')))];sys.modules[name]=module

def owner_origins(plan):
    observed=[]
    for name,expected in {**plan['source_owner_pins'],**plan['additional_owner_pins']}.items():
        if name in sys.modules:
            module=sys.modules[name]
            require(Path(module.__file__).resolve()==Path(expected['path']) and pin(module.__file__)==expected,
                'listed imported source owner origin or bytes differ: '+name)
            observed.append(name)
    require(all(name in observed for name in plan['additional_owner_pins']),'required objective/worker/readout owner missing')
    return observed

class NoEncoder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'transformers','sentence_transformers'}:
            raise AssertionError('encoder/teacher import forbidden: '+fullname)
        return None

def probes(torch,span,objective):
    def record(text):
        return dict(tokens=span.tokenize_source(text),latent=[0.]*384,
            labels=dict(modality=0,presence=[True,True,False,False,False,False],
                spans=[[0,0],[1,1],[-100,-100],[-100,-100],[-100,-100],[-100,-100]]))
    def output(records):
        n=len(records); width=max(len(r['tokens']) for r in records)
        return {k:torch.zeros(shape,dtype=torch.float32,requires_grad=True) for k,shape in {
            'modality':(n,3),'presence':(n,4,2),'start':(n,6,width),'end':(n,6,width)}.items()}
    rows=[record('A B')];heads=output(rows)
    ce0=objective.objective_from_output(torch,heads,rows,structure_weight=0.)
    old=span._loss(torch,lambda *args:heads,rows)
    require(torch.equal(old,ce0['ce']) and ce0['total'] is ce0['ce'],'exact same-output CE mismatch')
    old_grad=torch.autograd.grad(old,tuple(heads.values()),retain_graph=True)
    new_grad=torch.autograd.grad(ce0['total'],tuple(heads.values()),retain_graph=True)
    require(all(torch.equal(a,b) for a,b in zip(old_grad,new_grad,strict=True)),'CE gradient parity differs')
    structured=objective.objective_from_output(torch,heads,rows,structure_weight=.1)
    require(abs(float(structured['validity'])-math.log(4/3))<1e-10 and
        abs(float(structured['overlap'])-7/9)<1e-10,'uniformN2 probability oracle differs')
    structured['total'].backward()
    require(all(h.grad is not None and bool(torch.isfinite(h.grad).all()) for h in heads.values()),'probe missing/nonfinite gradient')
    padded_rows=[record('A B'),record('A B C')];padded=output(padded_rows)
    with torch.no_grad():
        padded['start'][0,:,2]=100000.;padded['end'][0,:,2]=-100000.
    padding=objective.objective_from_output(torch,padded,padded_rows,structure_weight=.1)
    a,b=structured['row_diagnostics'][0],padding['row_diagnostics'][0]
    require(a==b,'actual-token structural padding invariance differs')
    return dict(schema='structured-span-numerical-probes/v1',passed=True,findings=[],
        same_output_CE_bit_exact=True,same_output_CE_gradients_bit_exact=True,
        validity=float(structured['validity']),overlap=float(structured['overlap']),
        expected_validity=math.log(4/3),expected_overlap=7/9,finite_all_head_gradients=True,
        structural_padding_invariance=True,actual_model_forwards=0,actual_optimizer_updates=0,
        authority='synthetic numerical oracle only',qualified=False)

def measured_tuning(torch,span,objective,runtime,examples):
    records,_,_=span._records(examples,384)
    keys=('ce','validity','overlap','structure','weighted_structure','total')
    sums={k:0. for k in keys}
    weights_before,moments_before=span._pack(runtime.model,runtime.optimizer)
    ambient=torch.get_rng_state().clone()
    with torch.no_grad():
        for at in range(0,len(records),12):
            batch=records[at:at+12]
            heads=runtime.model(*span._batch(torch,batch))
            components=objective.objective_from_output(torch,heads,batch,structure_weight=.1)
            for key in keys:sums[key]+=float(components[key])*len(batch)
    weights_after,moments_after=span._pack(runtime.model,runtime.optimizer)
    require(weights_before==weights_after and moments_before==moments_after and torch.equal(ambient,torch.get_rng_state()),
        'diagnostic loss forwards changed model/Adam/RNG')
    report=runtime.infer([{k:row[k] for k in ('id','source_text','latent')} for row in examples],capture_scores=False)
    matches=[row['decoder_row']['canonical_ir']==example['canonical_ir'] for row,example in zip(report['rows'],examples,strict=True)]
    return dict(schema='authored-tuning-common-objective-diagnostic/v1',rows=len(examples),
        losses={k:value/len(examples) for k,value in sums.items()},diagnostic_structure_weight=.1,
        exact_canonical_ir=sum(matches),expected_exact_ceiling=96,teacher_forcing_for_loss=True,
        greedy_inference_target_access=False,training_executed=False,used_for_selection=False,
        source_semantics_verified=False,semantic_accuracy=None,qualified=False),report

def main(args):
    started=time.monotonic();plan=read(args.plan)
    require(plan['schema']=='structured-source-span-four-arm-plan/v1' and len(plan['arms'])==4
        and plan['total_new_updates_requested']==128 and plan['weights']==[0.,.1]
        and plan['training_count']==1152 and plan['tuning_count']==96
        and plan['controls']==['none','zero','disabled','rotate']
        and plan['encoder_execution_planned'] is False and plan['semantic_gold'] is False,
        'exact four-arm plan required')
    require(plan['runner_path']==str(Path(__file__).resolve()),'runner path differs')
    for path,expected in plan['artifacts'].items():
        require({k:pin(path)[k] for k in ('bytes','sha256')}==expected,'opening artifact bytes differ: '+path)
    out=Path(args.output);require(out.is_absolute() and out.resolve()==out and not out.exists(),'fresh output required')
    out.mkdir(mode=0o700);STATE['created_output']=str(out)
    forbidden=set(plan['forbidden_reference_paths'])
    def audit(event,values):
        if event.startswith(('subprocess.','os.exec','os.spawn','socket.')) or event=='os.system':
            raise AssertionError('network/process event forbidden: '+event)
        if event=='open' and isinstance(values[0],(str,bytes)):
            require(str(Path(os.fsdecode(values[0])).absolute()) not in forbidden,'forbidden target/corpus access')
    sys.addaudithook(audit);sys.meta_path.insert(0,NoEncoder());bootstrap(Path(plan['package_root']))
    worker=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.structured_span_continuation')
    span=importlib.import_module('ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula')
    objective=importlib.import_module('ipfs_datasets_py.logic.legal_ir.structured_span_objective')
    joint=importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    opening_imported_owners=owner_origins(plan)
    exports=read(plan['train_tune_export']['path']);TRAIN=exports['populations']['train'];TUNE=exports['populations']['tuning']
    law=read(plan['law_diagnostic_export']['path'])['rows'];require(len(law)==8,'eight exposed occurrences required')
    prepared=[];schedules=[]
    def initial(arm):
        return worker.prepare_checkpoint(read(arm['parent_file_pin']['path']),TRAIN,TUNE,
            structure_weight=arm['structure_weight'],expected_parent_sha256=arm['parent_canonical_sha256'],
            expected_training_sha256=exports['manifests']['train'],expected_tuning_sha256=exports['manifests']['tuning'])
    for arm in plan['arms']:
        checkpoint=initial(arm); schedule=worker.next_batch_ids(checkpoint,TRAIN,steps=32);schedules.append(schedule)
        prepared.append(dict(name=arm['name'],initial_checkpoint_sha256=worker.digest(checkpoint),
            initial_model_state_sha256=checkpoint['initial_model_state_sha256'],
            initial_optimizer_state_sha256=checkpoint['initial_optimizer_state_sha256'],
            progress=checkpoint['progress'],objective=checkpoint['objective'],batch_ids=schedule,batch_ids_sha256=digest(schedule)))
    del checkpoint
    require(all(s==schedules[0] for s in schedules),'equal ordered schedule differs')
    write(out/'all-arm-plans-before-opening.json',prepared)
    fix=plan['ctypes_dl_resolution'];queries=[]
    for key in ('library_pin','ctypes_util_pin','cuda_pathfinder_pin'):require(pin(fix[key]['path'])==fix[key],'libdl pin differs')
    require(ctypes.util.__file__==fix['ctypes_util_pin']['path'],'ctypes origin differs')
    with ExitStack() as stack:
        def find_dl(name):
            require(name=='dl' and pin(fix['library_pin']['path'])==fix['library_pin'],'unlisted/different lib query')
            queries.append(name);return fix['library_pin']['path']
        stack.enter_context(patch.object(ctypes.util,'find_library',find_dl))
        import torch
        torch.set_num_threads(1);torch.set_num_interop_threads(1)
        require(torch.__version__=='2.13.0+cu130','retained Torch version differs')
        write(out/'numerical-probes.json',probes(torch,span,objective))
        baselines=[]
        for arm in plan['arms'][::2]:
            checkpoint=initial(arm);runtime=worker.open_checkpoint(checkpoint)
            diagnostic,report=measured_tuning(torch,span,objective,runtime,TUNE)
            baselines.append(dict(name=arm['name'].rsplit('-',1)[0],diagnostic=diagnostic,
                authored_greedy=write(out/(arm['name']+'-baseline-tuning-greedy.json'),report)))
            del runtime,checkpoint
        write(out/'baseline-tuning.json',baselines)
        results=[]
        for arm in plan['arms']:
            STATE.update(stage='training',arm=arm['name'],in_progress_arm_updates_unknown=True);checkpoint=initial(arm)
            trained=worker.train_decoder(checkpoint,TRAIN,TUNE,max_steps=32,max_seconds=plan['training_seconds_per_arm'])
            STATE['in_progress_arm_updates_unknown']=False
            STATE['completed_updates']+=trained['report']['actual_new_updates']
            checkpoint_pin=worker.save_checkpoint(trained['checkpoint'],out/(arm['name']+'-checkpoint.json'))
            checkpoint_pin.pop('schema');STATE['saved_states'].append(checkpoint_pin)
            training_pin=write(out/(arm['name']+'-training.json'),trained['report'])
            require(trained['report']['complete'] and trained['report']['actual_new_updates']==32,
                'bounded fit stopped short; retain actual states, no equal-step claim')
            require(trained['report']['batch_ids']==schedules[0],'actual batch schedule differs')
            STATE['stage']='postfit_diagnostics';runtime=worker.open_checkpoint(trained['checkpoint'])
            diagnostic,tuning_report=measured_tuning(torch,span,objective,runtime,TUNE)
            tuning_pin=write(out/(arm['name']+'-tuning-greedy.json'),tuning_report)
            controls=[]
            for control in plan['controls']:
                report=runtime.infer(law,control=control,capture_scores=True)
                raw_pin=write(out/(arm['name']+'-law-'+control+'.json'),report)
                joint_rows=[]
                for incoming,row in zip(law,report['rows'],strict=True):
                    require(incoming['id']==row['id'],'law score/source join differs')
                    result=None if row['scores'] is None else joint.select_joint_spans(incoming['source_text'],row['scores'],top_k=8,max_search_nodes=50000)
                    joint_rows.append(dict(id=row['id'],result=result))
                joint_pin=write(out/(arm['name']+'-law-'+control+'-joint.json'),dict(
                    schema='structured-span-exposed-law-joint-diagnostic/v1',rows=joint_rows,top_k=8,max_search_nodes=50000,
                    learned_presence_and_modality_fixed=True,raw_greedy_preserved=True,semantic_accuracy=None,
                    qualified=False,used_for_updates_or_selection=False))
                controls.append(dict(control=control,raw_inference=raw_pin,joint=joint_pin))
            results.append(dict(name=arm['name'],checkpoint=checkpoint_pin,training=training_pin,
                tuning_diagnostic=diagnostic,tuning_greedy=tuning_pin,law_controls=controls))
            del runtime,trained,checkpoint
        require(STATE['completed_updates']==128,'actual total update count differs')
    for path,expected in plan['artifacts'].items():
        require({k:pin(path)[k] for k in ('bytes','sha256')}==expected,'closing artifact bytes differ: '+path)
    closing_imported_owners=owner_origins(plan)
    summary=dict(schema='structured-span-four-arm-results/v1',status='completed',arms=results,baseline_tuning=baselines,
        actual_new_updates=STATE['completed_updates'],actual_encoder_calls=0,equal_step_count=32,equal_batch_schedule=True,
        original_artifacts_byte_exact=True,source_semantics_verified=False,semantic_accuracy=None,
        independent_semantic_holdout=False,authored_tuning_previously_exposed=True,law_previously_exposed=True,
        legal_fidelity_qualified=False,checkpoint_selection_executed=False,default_promotion=False,
        trained_dimensions=[384],eight_dimensional_trained=False,seven_sixty_eight_trained=False,
        logic_family_scope=plan['logic_family_scope'],Lake_executed=False,
        ctypes_dl_resolution=dict(profile=fix,queries=queries,subprocess_fallback_executed=False),
        full_third_party_import_graph_qualified=False,elapsed_seconds=time.monotonic()-started,
        listed_imported_owner_origins_checked_at_entry_and_exit=True,
        opening_imported_owners=opening_imported_owners,closing_imported_owners=closing_imported_owners,
        retained_owner_files_not_imported=[name for name in plan['source_owner_pins'] if name not in closing_imported_owners],
        resource_scope='historical guardian unchanged: 2CPU/1536MiB/1child/200MB/300s')
    write(out/'summary.json',summary);print(json.dumps(dict(status='completed',actual_new_updates=128,actual_encoder_calls=0)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    try:main(p.parse_args())
    except Exception as error:
        if STATE['created_output']:
            write(Path(STATE['created_output'])/'child-failure.json',dict(**STATE,error_type=type(error).__name__,detail=str(error),
                qualified=False,semantic_accuracy=None,original_states_preserved=True))
        raise
