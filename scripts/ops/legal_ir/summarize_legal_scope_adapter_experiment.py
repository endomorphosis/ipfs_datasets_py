#!/usr/bin/env python3
"""Independent qualification of a scope-only token-sequence adapter.

The architecture comparison keeps the encoder, token boundaries, clause models,
source order, objective and selection gates fixed. Fresh references are opened
only after exact numerical replay and native source-only build commitments.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import math
import multiprocessing
from pathlib import Path
import random
import re
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import summarize_legal_scope_retention_experiment as prior
require,digest,read_ref,ref,write,sha=(getattr(prior,k) for k in ('require','digest','read_ref','ref','write','sha'))
retained,previous,clauses,boundary=prior.retained,prior.previous,prior.clauses,prior.boundary
boundary_qualification=prior.boundary_qualification
SealedReadGuard=prior.SealedReadGuard
scope_metrics=prior.scope_metrics
audited_scope_metric=prior.audited_scope_metric
verify_scope_pairs=prior.verify_scope_pairs
scope_choice=prior.scope_choice
verify_frozen_token_outputs=prior.verify_frozen_token_outputs
FALSE=prior.FALSE
SCHEMA='legal-scope-adapter-independent-qualification/v1'
ARMS=('control','adapter')
STAGES=(100,200,400)
SEED=1730
PARENT_SHA='e741578ac017e163588c6b49a16f6bca9dd0a37e71a0c345a3c9706814c3cf99'


def verify_opaque_sources(rows):
    require(type(rows) is list and len(rows)>0,'nonempty opaque source inventory required')
    seen=set()
    for row in rows:
        require(set(row)=={'candidate_id','source_text','source_sha256'} and row['source_sha256']==boundary.text_sha(row['source_text']),'closed source-only input and exact text digest required')
        require(row['candidate_id']=='scope-'+row['source_sha256'] and re.fullmatch(r'scope-[0-9a-f]{64}',row['candidate_id']) is not None,'source IDs must expose only the content digest, without class or side metadata')
        require(row['candidate_id'] not in seen,'duplicate opaque source ID');seen.add(row['candidate_id'])
    return {'source_rows':len(rows),'content_digest_only_ids':True,'labels_or_pair_membership_in_source_metadata':False}


def matched_batches(replay,new_rows,pairs,*,steps=400,seed=1730):
    require(type(steps) is int and 1<=steps<=400 and type(seed) is int,'bounded declared schedule required')
    require(len({r['candidate_id'] for r in replay})==len(replay) and len({r['candidate_id'] for r in new_rows})==len(new_rows),'unique replay and paired row inventories required')
    lookup={r['candidate_id']:r for r in new_rows}
    def stream(values,salt):
        rng=random.Random(salt)
        while True:
            order=list(range(len(values)));rng.shuffle(order)
            for i in order:yield values[i]
    common=stream(replay,seed);contrast=stream(pairs,seed+3);receipts=[]
    for step in range(1,steps+1):
        old=[next(common) for _ in range(6)];selected=[next(contrast) for _ in range(3)]
        extra=[lookup[p[k]] for p in selected for k in ('independent_id','nested_id')]
        require([r['supported'] for r in extra]==[True,False]*3,'paired auxiliary rows changed independent/nested class order')
        rows=old+extra
        receipts.append({'steps':step,'common_replay_ids':[r['candidate_id'] for r in old],
            'extra_ids':[r['candidate_id'] for r in extra],'pair_ids':[p['pair_id'] for p in selected],
            'supported_count':sum(r['supported'] for r in rows),'unsupported_count':sum(not r['supported'] for r in rows)})
    return receipts


def scope_loss_oracle(torch,logits,labels):
    """Explicit class-weighted NLL, including its true weighted denominator."""
    require(logits.ndim==2 and logits.shape[1]==2 and len(labels)==len(logits),'two-class scope output required')
    labels=[int(v) for v in labels]
    require(set(labels)<={0,1} and labels,'binary scope labels required')
    terms={0:[],1:[]}
    for i,target in enumerate(labels):terms[target].append(torch.logsumexp(logits[i],0)-logits[i,target])
    zero=logits.sum()*0
    sums={k:torch.stack(v).sum() if v else zero for k,v in terms.items()}
    denominator=3*len(terms[0])+len(terms[1]);loss=(3*sums[0]+sums[1])/denominator
    return loss,{'unsupported_count':len(terms[0]),'supported_count':len(terms[1]),
        'unsupported_nll_sum':sums[0],'supported_nll_sum':sums[1],'weighted_denominator':denominator}


def verify_scope_loss_receipt(parts,exposure,loss):
    require(parts['unsupported_count']==exposure['unsupported_count'] and parts['supported_count']==exposure['supported_count']
        and parts['unsupported_count']+parts['supported_count']==12,'weighted scope label denominator differs')
    denominator=3*parts['unsupported_count']+parts['supported_count']
    require(parts['weighted_denominator']==denominator,'scope CE must divide by class weights, not row count')
    values=[parts['unsupported_nll_sum'],parts['supported_nll_sum'],loss]
    require(all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in values),'finite nonnegative scope NLL required')
    wanted=(3*parts['unsupported_nll_sum']+parts['supported_nll_sum'])/denominator
    require(math.isclose(loss,wanted,rel_tol=2e-5,abs_tol=2e-6),'independent class-weighted scope loss differs')
    return True


def verify_frozen_states(parent,initial,candidate,arm,trainable_names):
    require(arm in ARMS and set(initial['model_state'])==set(candidate['model_state']),'complete adapter tensor inventory required')
    a,b=initial['model_state'],candidate['model_state'];base=parent['model_state']
    require(set(base)<=set(a),'adapter omitted pretrained tensors')
    for key in base:
        require(a[key]==base[key],'initial pretrained tensor changed: '+key)
        if not key.startswith('scope.'):
            require(b[key]==base[key],'scope fitting changed frozen pretrained encoder/token weights: '+key)
    expected={'scope.weight','scope.bias'}|({'attention_hidden.weight','attention_hidden.bias','attention_score.weight','attention_score.bias','scope_residual.weight','scope_residual.bias'} if arm=='adapter' else set())
    require(set(trainable_names)==expected and set(trainable_names)<=set(a),'closed scope readout training inventory required')
    require(all(b[k]==a[k] for k in a if k not in trainable_names),'frozen control or encoder tensor changed')
    changed=[k for k in sorted(a) if a[k]!=b[k]]
    require(changed and set(changed)<=set(trainable_names),'candidate must change only authorized scope tensors')
    def number_count(value):
        if isinstance(value,list):return sum(number_count(v) for v in value)
        require(type(value) in (int,float) and math.isfinite(value),'nonfinite scope tensor');return 1
    count=sum(number_count(b[k]) for k in trainable_names)
    require(count==(130 if arm=='control' else 1317),'scope architecture trainable parameter count differs')
    return {'trainable_parameters':count,'changed_scope_tensors':changed,'all_frozen_base_and_control_tensors_exact':True}


def attention_oracle(torch,network,values,lengths):
    """Per-row valid-token computation, independent of masked batched softmax."""
    pooled=[];weights=[]
    for row,length in zip(values,lengths,strict=True):
        length=int(length);require(0<length<=len(row),'valid attention length required')
        logits=[]
        for token in row[:length]:
            hidden=torch.tanh((network.attention_hidden.weight*token[None,:]).sum(-1)+network.attention_hidden.bias)
            logits.append((network.attention_score.weight[0]*hidden).sum()+network.attention_score.bias[0])
        logits=torch.stack(logits);positive=torch.exp(logits-logits.max());probability=positive/positive.sum()
        pooled.append(sum((p*token for p,token in zip(probability,row[:length],strict=True)),torch.zeros_like(row[0])))
        weights.append(torch.cat((probability,torch.zeros(len(row)-length,dtype=values.dtype,device=values.device))))
    return torch.stack(pooled),torch.stack(weights)


def verify_initialization(parent,initial,arm,manifest,tuning,parent_ref):
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
    reconstructed=runtime.build_checkpoint(parent,arm=arm,seed=1730,training_manifest_sha256=digest(manifest),tuning_manifest_sha256=digest(tuning),parent_file_sha256=parent_ref['sha256'])
    require(initial==reconstructed and initial['parent_checkpoint']==parent and initial['parent_file_sha256']==PARENT_SHA and initial['parent_checkpoint_sha256']==digest(parent),'exact independent scope initialization/parent reconstruction differs')
    require(initial['additional_optimizer_steps']==0 and initial['optimizer_steps']==parent['optimizer_steps']==800 and initial['optimizer_resumption_supported'] is False,'fresh additional optimizer counter differs')
    require(all(v==0 for row in initial['model_state']['scope_residual.weight'] for v in row) and all(v==0 for v in initial['model_state']['scope_residual.bias']),'initial adapter residual must be exactly zero')
    return True


def initial_parent_parity(initial,parent_generations,sources):
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
    decoder=runtime.decoder(initial);rows=0;payloads={}
    for panel,source_rows in sources.items():
        expected=deepcopy(parent_generations[panel])
        for report in expected['reports']:report['checkpoint_sha256']=digest(initial)
        actual=clauses.decode_all(decoder,source_rows)
        require(actual==expected,'full initial adapter output differs from parent beyond declared checkpoint provenance: '+panel)
        payloads[panel]=digest(actual);rows+=len(source_rows)
    require(digest({k:v.detach().cpu().tolist() for k,v in decoder.network.state_dict().items()})==digest(initial['model_state']),'initial parity inference changed model weights')
    return {'source_evaluations':rows,'panel_output_sha256':payloads,'all_numeric_and_final_outputs_equal_parent':True,'only_metadata_difference':'reports[].checkpoint_sha256','saved_output_replay':False,'new_fresh_reference_access':False}


def verify_training(inputs,frozen):
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
    plan=read_ref(frozen['plan']);selection=read_ref(frozen['selections']);parent=inputs['parent'];parent_ref=inputs['config']['boundary_parent']
    require(parent_ref['sha256']==PARENT_SHA and parent['optimizer_steps']==800,'fixed expanded1730 parent required')
    expected_plan={'arms':list(ARMS),'seed':1730,'stages':list(STAGES),'steps_per_arm':400,'trainable_parameter_counts':{'control':130,'adapter':1317},'learning_rate':.004,'scope_class_weights':[3.,1.],'optimizer':'fresh_Adam','gradient_clip_norm':5.,'trial_wall_limit_seconds':1200,'identical_batches_both_arms':True,'common_replay_rows':6,'contrast_pairs_per_batch':3,'scope_threshold_and_surface_policy_unchanged':True,'clause_predictions_used_for_selection':False,'new_fresh_targets_opened':False,'replay_count':768,'new_training_count':384}
    require(all(type(plan[k]) is type(v) and plan[k]==v for k,v in expected_plan.items()),'frozen matched architecture protocol differs')
    require(len(inputs['replay'])==768 and len(inputs['new_train'])==384 and len(inputs['tuning'])==16 and sum(len(v) for v in inputs['tuning'].values())==1584 and len(inputs['sources'])==17 and sum(len(v) for v in inputs['sources'].values())==1776,'complete planned training/tuning/source inventory required')
    require(plan['tuning_counts']=={k:len(v) for k,v in inputs['tuning'].items()} and plan['source_counts']=={k:len(v) for k,v in inputs['sources'].items()} and plan['training_source_inventory_sha256']==digest(inputs['replay']+inputs['new_train']),'source/training manifest binding differs')
    pair_audit=verify_scope_pairs(inputs['new_train'],inputs['training_pairs'],192)
    verify_opaque_sources(clauses.source_rows(inputs['new_train']));verify_opaque_sources(inputs['sources']['scope_new']);opaque=verify_opaque_sources(inputs['sources']['scope_fresh'])
    require(selection['plan']==frozen['plan'] and selection['executed_optimizer_updates']==800 and selection['all_training_and_selection_complete'] is True and selection['new_fresh_targets_opened'] is selection['clause_predictions_used_for_selection'] is False and selection['choice_fixed_before_fresh_reference_release'] is True,'complete source-only independent scope selection freeze required')
    require([m['name'] for m in frozen['models']]==['parent','control','adapter'] and read_ref(frozen['heads'])==frozen['models'],'all three parent/candidate/fallback scope slots required')
    require(frozen['models'][0]=={'name':'parent','arm':'parent','checkpoint':parent_ref,'selected_steps':0,'selection':'unchanged_parent_control'},'unchanged parent head differs')
    pt=read_ref(selection['parent_tuning']);parent_metrics={};jobs=[]
    require(set(pt['generation'])==set(pt['metrics'])==set(inputs['tuning']),'complete parent tuning panels required')
    for panel,targets in inputs['tuning'].items():
        parent_metrics[panel]=audited_scope_metric(pt['generation'][panel],inputs['sources'][panel],targets,pt['metrics'][panel])
        jobs.append({'kind':'boundary','name':'parent-reference/'+panel,'checkpoint':parent_ref,'sources':inputs['sources'][panel],'generation':selection['parent_tuning'],'scope_panel':panel,'stage':True})
    trials=selection['trials'];require([t['name'] for t in trials]==list(ARMS),'both matched architecture trials required')
    expected_batches=matched_batches(inputs['replay'],inputs['new_train'],inputs['training_pairs']);initial_states=[];audits=[];initials={};stage_maps={}
    for trial in trials:
        arm=trial['arm'];require(trial['name']==arm and trial['seed']==1730 and trial['parent']==parent_ref and trial['executed_steps']==400,'trial attribution differs')
        training=read_ref(trial['training']);manifest=training['manifest']
        require(manifest=={'arm':arm,'seed':1730,'plan':frozen['plan'],'steps':400,'replay_sha256':digest(inputs['replay']),'new_training_sha256':digest(inputs['new_train']),'training_pairs_sha256':digest(inputs['training_pairs'])},'training manifest differs')
        initial=read_ref(trial['initial_checkpoint']);verify_initialization(parent,initial,arm,manifest,inputs['tuning'],parent_ref)
        initial_states.append(initial['model_state']);initials[arm]=initial
        names=initial['trainable_parameters'];require(training['optimizer_updates']==400 and len(training['losses'])==len(training['loss_receipts'])==len(training['batch_receipts'])==400 and training['batch_receipts']==expected_batches and training['batch_receipts_sha256']==digest(expected_batches),'all400 matched12row update receipts required')
        require(set(training['trainable_parameters'])==set(names) and training['trainable_parameter_count']==initial['trainable_parameter_count'] and training['optimizer_parameter_steps']=={k:400 for k in names},'complete trainable Adam counter inventory differs')
        require(training['initial_complete_model_state_sha256']==digest(initial['model_state']) and training['initial_predictions_equal_parent'] is training['initial_optimizer_state_empty'] is True and training['optimizer_resumed'] is training['optimizer_trajectory_independently_replayed'] is False and training['trial_wall_limit_seconds']==1200 and 0<training['wall_seconds']<=1200,'initial state/fresh Adam/wall receipts differ')
        for step,(loss,parts,exposure) in enumerate(zip(training['losses'],training['loss_receipts'],expected_batches,strict=True),1):
            require(parts['steps']==step and parts['weighted_cross_entropy']==loss and parts['gradient_clip_norm']==5. and type(parts['gradient_norm_before_clipping']) in (float,int) and math.isfinite(parts['gradient_norm_before_clipping']) and parts['gradient_norm_before_clipping']>=0 and parts['finite_updated_parameters'] is True,'finite update/gradient receipt differs')
            verify_scope_loss_receipt(parts,exposure,loss)
        require([s['steps'] for s in trial['stages']]==list(STAGES),'all100/200/400 stages required')
        normalized=[];stages=[];stage_maps[arm]={}
        for stage in trial['stages']:
            checkpoint=read_ref(stage['checkpoint']);runtime.restore(checkpoint)
            require(checkpoint['additional_optimizer_steps']==stage['steps'] and checkpoint['optimizer_steps']==800+stage['steps'],'stage cumulative/new optimizer counters differ')
            require({k:v for k,v in checkpoint.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')}=={k:v for k,v in initial.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')},'immutable stage provenance changed')
            tensor_audit=verify_frozen_states(parent,initial,checkpoint,arm,names)
            require(stage['frozen_non_scope_state_sha256']==initial['frozen_non_scope_state_sha256'] and stage['raw_token_logits_unchanged'] is True,'frozen token-state receipt differs')
            saved=read_ref(stage['tuning']);require(saved['metrics']==stage['metrics'] and set(saved['generation'])==set(inputs['tuning']),'complete stage tuning outputs required')
            metrics={}
            for panel,targets in inputs['tuning'].items():
                verify_frozen_token_outputs(pt['generation'][panel],saved['generation'][panel])
                metrics[panel]=audited_scope_metric(saved['generation'][panel],inputs['sources'][panel],targets,saved['metrics'][panel])
                jobs.append({'kind':'boundary','name':f'{arm}/stage-{stage["steps"]}/'+panel,'checkpoint':stage['checkpoint'],'sources':inputs['sources'][panel],'generation':stage['tuning'],'scope_panel':panel,'stage':True})
            failures=[]
            for panel in sorted(metrics):
                m,p=metrics[panel],parent_metrics[panel]
                if m['raw_supported_correct']<p['raw_supported_correct']:failures.append(panel+':raw_supported_scope_correct_regressed')
                if m['supported_exact']<p['supported_exact']:failures.append(panel+':exact_supported_segmentation_regressed')
                if m['raw_unsupported_accepted']:failures.append(panel+':raw_unsupported_accepted')
                if m['unsupported_accepted']:failures.append(panel+':final_unsupported_accepted')
            require(stage['eligible'] is (not failures) and stage['failures']==failures,'independent strict raw/final scope gates differ')
            normalized.append({'steps':stage['steps'],'metrics':metrics,'raw_token_logits_unchanged':True});stage_maps[arm][stage['steps']]=metrics
            stages.append({'steps':stage['steps'],'checkpoint':stage['checkpoint'],'tuning':metrics,'eligible':not failures,'failures':failures,'tensor_audit':tensor_audit})
        chosen=scope_choice(normalized,parent_metrics);steps=chosen['steps'] if chosen else 0;pin=next(s['checkpoint'] for s in trial['stages'] if s['steps']==steps) if chosen else parent_ref
        status='candidate' if chosen else 'parent_fallback_no_eligible_scope_stage'
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status,'independent adapter/control selection differs')
        require(next(h for h in frozen['models'] if h['name']==arm)=={k:trial[k] for k in ('name','arm','checkpoint','selected_steps','selection')},'selected/fallback head slot attribution differs')
        audits.append({'name':arm,'parent':parent_ref,'initial_checkpoint':trial['initial_checkpoint'],'training':trial['training'],'stages':stages,'selection':status,'selected_steps':steps,'checkpoint':pin,'executed_updates':400,'batch_sha256':digest(expected_batches)})
    require(initial_states[0]==initial_states[1],'architecture arms did not start from identical complete model tensors')
    candidates=[a for a in audits if a['selection']=='candidate']
    def ranking(a):
        m=stage_maps[a['name']][a['selected_steps']]
        return (m['scope_new']['raw_supported_correct'],m['scope_new']['supported_exact'],sum(v['supported_exact'] for p,v in m.items() if p!='scope_new'),-a['selected_steps'],a['name']=='control')
    primary=max(candidates,key=ranking)['name'] if candidates else 'parent'
    require(selection['primary_scope_choice']==frozen['primary_scope_choice']==primary and frozen['choice_fixed_before_fresh_reference_release'] is True,'pre-reference primary scope choice differs')
    parent_generations={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    initial_audits={arm:initial_parent_parity(initial,parent_generations,inputs['sources']) for arm,initial in initials.items()}
    return jobs,{'trials':audits,'parent_tuning':parent_metrics,'training_pairs':pair_audit,'opaque_fresh_sources':opaque,'primary_scope_choice':primary,'initial_parent_parity':initial_audits,'initial_source_evaluations':sum(a['source_evaluations'] for a in initial_audits.values()),'optimizer_trajectory_replayed':False}

DOCUMENT_COUNTS={'scope_fresh':192,'prior_scope_fresh':192,'root_condition_fresh_documents':96}
CLAUSE_PARENTS={'continuation':('facet_retention','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding':('temporal_presence','4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea')}


def verify_fitting(inputs):
    from scripts.ops.legal_ir import run_legal_scope_retention_experiment as old_runner
    manifest=inputs['manifest'];old=read_ref(manifest['inputs']['prior_scope_corpus']);condition=read_ref(manifest['inputs']['prior_condition_corpus'])
    expected_replay={**old['replay_references'],'prior_scope':old['artifacts']['new_training_targets']}
    require(manifest['replay_references']==expected_replay and inputs['replay']==[r for pin in manifest['replay_references'].values() for r in read_ref(pin)],'historical768 replay membership/order differs')
    require(manifest['retention_target_references']==old['retention_target_references'],'historical retention references changed')
    artifacts=manifest['artifacts']
    require(inputs['new_train']==read_ref(artifacts['new_training_targets']) and inputs['training_pairs']==read_ref(artifacts['training_pairs']) and inputs['tuning']['scope_new']==read_ref(artifacts['tuning_targets']),'new fitting/tuning references changed')
    tuning_pairs=read_ref(artifacts['tuning_pairs']);pair_audit=verify_scope_pairs(inputs['tuning']['scope_new'],tuning_pairs,48)
    old_generation=read_ref(inputs['config']['prior_scope_generation']);old_plan=read_ref(old_generation['plan']);old_inputs=old_runner.read_config(old_plan['config']['path'])
    panels={digest(rows) for rows in inputs['tuning'].values()}
    require(all(digest(rows) in panels for rows in old_inputs['tuning'].values()),'prior scope tuning panel was dropped or changed')
    require(inputs['tuning']['prior_scope_fresh']==read_ref(old['artifacts']['fresh_targets']) and inputs['tuning']['root_condition_fresh_documents']==read_ref(condition['artifacts']['document_challenge_targets']),'old fresh panels must be explicitly admitted retention')
    fit={r['source_sha256'] for r in inputs['replay']+inputs['new_train']}
    require(len(fit)==1152 and all(not fit&{r['source_sha256'] for r in rows} for rows in inputs['sources'].values()),'fitting source leaks into evaluation')
    return {'historical_replay_rows':768,'new_training_rows':384,'new_training_pairs':192,'new_tuning_pairs':pair_audit['pairs'],'prior_tuning_panels_retained':len(old_inputs['tuning']),'previous_fresh_scope_and_condition_documents_are_admitted_retention':True,'fit_evaluation_source_overlap':0}


def verify_inventory(inputs,frozen):
    require(frozen['all_training_selection_and_generation_complete'] is True and frozen['executed_optimizer_updates']==800 and frozen['new_fresh_targets_opened'] is frozen['clause_predictions_used_for_selection'] is False and frozen['all_source_raw_token_logits_unchanged'] is frozen['no_joint_stage_search'] is True,'complete source-only fixed-factor generation required')
    require(frozen['clause_models']==inputs['config']['clause_models'] and len(frozen['clause_models'])==2,'two fixed clause models required')
    models={m['name']:m for m in frozen['clause_models']};heads={h['name']:h for h in frozen['models']}
    require(set(models)=={'parent_continuation','parent_grounding'} and set(heads)==set(frozen['files'])=={'parent','control','adapter'},'fixed clause and three boundary slots required')
    for model in models.values():
        kind,wanted=CLAUSE_PARENTS[model['architecture']]
        require(model['name']=='parent_'+model['architecture'] and model['decoder_kind']==kind and model['checkpoint']['sha256']==wanted,'existing preselected clause parent changed')
        read_ref(model['checkpoint'],parse=False)
    require(set(frozen['sources'])==set(inputs['sources']) and all(read_ref(pin)==inputs['sources'][panel] for panel,pin in frozen['sources'].items()),'source-only frozen input rows differ')
    expected={m+'__scope_'+h for m in models for h in heads}
    require(len(frozen['pipelines'])==6 and {p['name'] for p in frozen['pipelines']}==set(frozen['document_files'])==expected,'all six fixed-clause/scope pipeline slots required')
    require(set(frozen['document_sources'])==set(DOCUMENT_COUNTS) and all(frozen['document_sources'][p]==frozen['sources'][p] and len(inputs['sources'][p])==n for p,n in DOCUMENT_COUNTS.items()),'full new/exposed document panel inventory differs')
    for pipeline in frozen['pipelines']:
        model=models[pipeline['source_model_name']];head=heads[pipeline['boundary_head']]
        require(pipeline['name']==model['name']+'__scope_'+head['name'] and pipeline['boundary_checkpoint']==head['checkpoint'] and pipeline['boundary_selection']==head['selection'] and pipeline['boundary_selected_steps']==head['selected_steps'] and pipeline['clause_training_executed'] is False and all(pipeline[k]==model[k] for k in ('architecture','decoder_kind','checkpoint')) and set(frozen['document_files'][pipeline['name']])==set(DOCUMENT_COUNTS),'pipeline factor attribution or panel coverage differs')
    parent={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    for head,panels in frozen['files'].items():
        require(set(panels)==set(inputs['sources']),'selected boundary source panels missing')
        for panel,pin in panels.items():verify_frozen_token_outputs(parent[panel],read_ref(pin))
    return {'boundary_slots':3,'fixed_clause_models':2,'document_pipeline_slots':6,'fresh_source_documents':192,'fresh_supported_documents':96,'fresh_unsupported_documents':96,'selected_boundary_source_rows':5328,'selected_pipeline_documents':2880,'clause_training_updates':0}


def audit_training_diagnostics(inputs,frozen):
    require(set(frozen['training_diagnostics'])=={'parent','control_final400','adapter_final400'},'all three preregistered full TRAIN diagnostic slots required')
    selection=read_ref(frozen['selections']);expected={'parent':inputs['config']['boundary_parent'],**{t['name']+'_final400':t['stages'][-1]['checkpoint'] for t in selection['trials']}}
    panels={'historical_replay':inputs['replay'],'new_training':inputs['new_train']};jobs=[];scores={};parent=None
    for name in ('parent','control_final400','adapter_final400'):
        pin=frozen['training_diagnostics'][name];saved=read_ref(pin)
        require(saved['checkpoint']==expected[name] and saved['training_fit_used_for_selection'] is saved['heldout_accuracy'] is False and set(saved['generation'])==set(saved['metrics'])==set(panels),'TRAIN diagnostic lineage/panels/selection attribution differs')
        if parent is None:parent=saved['generation']
        scores[name]={}
        for panel,targets in panels.items():
            sources=clauses.source_rows(targets);verify_frozen_token_outputs(parent[panel],saved['generation'][panel])
            scores[name][panel]=audited_scope_metric(saved['generation'][panel],sources,targets,saved['metrics'][panel])
            jobs.append({'kind':'boundary','name':'TRAIN/'+name+'/'+panel,'checkpoint':expected[name],'sources':sources,'generation':pin,'scope_panel':panel,'training_diagnostic':True})
    return jobs,{'saved_source_rows':3456,'models':scores,'training_fit_used_for_selection':False,'heldout_accuracy':False}


_WORKER_GUARD=None

def init_worker(sealed):
    global _WORKER_GUARD
    _WORKER_GUARD=SealedReadGuard(sealed);sys.addaudithook(_WORKER_GUARD.event)


def replay_group(group):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as clause_runner
    torch.set_num_threads(1)
    decoder=runtime.decoder(read_ref(group['checkpoint'])) if group['decoder_kind']=='boundary' else clause_runner.load_decoder(group['checkpoint'],group['decoder_kind'])
    results=[]
    for job in group['jobs']:
        if job['kind']=='boundary':
            expected=read_ref(job['generation'])
            if 'scope_panel' in job:expected=expected['generation'][job['scope_panel']]
            actual=clauses.decode_all(decoder,job['sources']);require(actual==expected,'full numerical scope replay differs: '+job['name'])
            result={'kind':'boundary','name':job['name'],'rows':len(job['sources']),'generation':job['generation'],'scope_panel':job.get('scope_panel'),'checkpoint':job['checkpoint'],'source_inputs_sha256':digest(job['sources']),'recorded_generation_sha256':digest(actual),'exact_recorded_payload_replay':True,'clause_occurrences_replayed':0,'stage_tuning':job.get('stage',False),'training_diagnostic':job.get('training_diagnostic',False),'recomputed_for_this_saved_panel':True,'target_access':False}
        else:result=prior.replay_with_decoder(job,decoder)
        require(_WORKER_GUARD is not None and not _WORKER_GUARD.events,'replay worker lacked reference-file denial or attempted access')
        results.append(result);print({'phase':'replayed','name':job['name'],'rows':len(job['sources'])},flush=True)
    return results


def historical_annotation_inputs(inputs):
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as condition
    manifest=inputs['manifest'];scope=read_ref(manifest['inputs']['prior_scope_corpus']);cm=read_ref(manifest['inputs']['prior_condition_corpus'])
    refs={**scope['replay_references'],'prior_scope':scope['artifacts']['new_training_targets'],**scope['retention_target_references'],
        'prior_scope_tuning':scope['artifacts']['tuning_targets'],'prior_scope_exposed_fresh':scope['artifacts']['fresh_targets'],
        'condition_document_tuning':cm['artifacts']['document_tuning_targets'],'condition_exposed_documents':cm['artifacts']['document_challenge_targets']}
    documents={name:{'reference':pin,'rows':read_ref(pin)} for name,pin in refs.items()}
    _,_,excluded,_,source_refs,real_count=condition.historical_inputs(cm['inputs']['prior_corpus']['path'])
    for key in ('new_tuning','challenge_targets','document_tuning_targets','document_challenge_targets'):excluded.update(r['source_text'] for r in read_ref(cm['artifacts'][key]))
    for item in documents.values():excluded.update(r['source_text'] for r in item['rows'])
    return {'historical_documents':documents,'prior_scope_annotations':{'reference':scope['artifacts']['annotation_ledger'],'ledger':read_ref(scope['artifacts']['annotation_ledger'])},
        'historical_manifests':{'prior_scope':scope,'prior_condition':cm},'historical_source_inventory':{'source_texts':sorted(excluded),'prior_source_references':source_refs,'condition_single_references':{k:cm['artifacts'][k] for k in ('new_tuning','challenge_targets')},'real_exposed_views':real_count}}



def document_selection(records,sources,*,toolchain):
    """Apply the immutable96-document lowering audit to both halves of192."""
    require(len(records)==len(sources)==192 and len({r['candidate_id'] for r in records})==192 and {r['candidate_id'] for r in records}=={s['candidate_id'] for s in sources},'complete unique192-document native source selection required')
    lookup={r['candidate_id']:r for r in records};rows=[];excluded=[]
    for offset in (0,96):
        source_batch=sources[offset:offset+96]
        part=retained.document_selection([lookup[s['candidate_id']] for s in source_batch],source_batch,toolchain=toolchain)
        require(part['source_count']==96 and len(part['rows'])+len(part['excluded'])==96,'immutable lowering batch dropped sources')
        rows.extend(part['rows']);excluded.extend(part['excluded'])
    require(len(rows)+len(excluded)==192,'native selection dropped a complete source')
    return {'rows':rows,'excluded':excluded,'source_count':192}

def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_scope_adapter_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_scope_adapter_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_scope_adapter_annotations as annotations
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_adapter as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU qualification workers required')
    folder,output=Path(args.run_directory).resolve(),Path(args.output).resolve()
    frozen_ref=ref(folder/'generation-frozen.json');frozen=read_ref(frozen_ref)
    require(frozen['schema']==runner.SCHEMA,'declared completed scope adapter generation required')
    plan=read_ref(frozen['plan']);config=read_ref(plan['config']);manifest=read_ref(config['scope_corpus_manifest'])
    evidence_refs={key:manifest['artifacts'][key] for key in ('fresh_targets','fresh_pairs','annotation_ledger','exposure_audit')}
    sealed=list(evidence_refs.values());guard=SealedReadGuard(sealed);sys.addaudithook(guard.event)
    inputs=runner.read_config(plan['config']['path']);inventory=verify_inventory(inputs,frozen)
    pins=dict(plan['producer_pins'])
    for module in (sys.modules[__name__],prior,runner,corpus,annotations,runtime,boundary,clauses,retained,retained.prior,retained.calendar,retained.calendar_summary,retained.compose,boundary_qualification,previous,gate):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    require(all(sha(path)==wanted for path,wanted in pins.items()),'frozen producer source drift')
    output.mkdir(parents=True,exist_ok=False)
    qualification_plan=write(output/'qualification-plan.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'producer_pins':pins,'sealed_references':evidence_refs,'fresh_document_build_slots':6,'native_build_panel':'scope_fresh','new_reference_files_opened':False,'old_fresh_reference_panels_admitted_as_retention':True,'clause_training_executed':False})
    fitting=verify_fitting(inputs);jobs,training=verify_training(inputs,frozen)
    training_jobs,diagnostics=audit_training_diagnostics(inputs,frozen);jobs+=training_jobs
    require(training['initial_source_evaluations']==3552,'both initial checkpoints must be checked on all1776source rows')
    training_ref=write(output/'training-and-selection-audit.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'selections':frozen['selections'],'fitting':fitting,**training,'full_training_diagnostics':diagnostics,'executed_scope_updates':800,'clause_training_updates':0,'source_semantics_verified':False})
    boundary_outputs={}
    for head in frozen['models']:
        name=head['name'];boundary_outputs[name]={}
        for panel,pin in frozen['files'][name].items():
            boundary_outputs[name][panel]=read_ref(pin)
            require(len(boundary_outputs[name][panel]['rows'])==len(inputs['sources'][panel]),'selected boundary output dropped sources')
            jobs.append({'kind':'boundary','name':name+'/'+panel,'checkpoint':head['checkpoint'],'sources':inputs['sources'][panel],'generation':pin})
    documents={}
    for model in frozen['pipelines']:
        name=model['name'];documents[name]={}
        for panel,pin in frozen['document_files'][name].items():
            documents[name][panel]=read_ref(pin);require(len(documents[name][panel]['rows'])==DOCUMENT_COUNTS[panel],'pipeline source denominator differs')
            jobs.append({'kind':'document','name':name+'/'+panel,'model':model,'sources':inputs['sources'][panel],'generation':pin,'boundary':frozen['files'][model['boundary_head']][panel]})
    require(sum(len(j['sources']) for j in jobs)==22752 and sum(len(j['sources']) for j in jobs if j.get('training_diagnostic'))==3456,'complete saved output/diagnostic replay denominator differs')
    groups=prior.group_replay_jobs(jobs);replays=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn'),initializer=init_worker,initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group,g) for g in groups]):replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==22752,'full saved numerical replay incomplete')
    for a in frozen['models']:
        for b in frozen['models']:
            if a['checkpoint']==b['checkpoint']:
                require(boundary_outputs[a['name']]==boundary_outputs[b['name']],'same-checkpoint head slots changed outputs')
                require(all(documents[m['name']+'__scope_'+a['name']]==documents[m['name']+'__scope_'+b['name']] for m in frozen['clause_models']),'same-checkpoint pipeline slots changed outputs')
    replay_ref=write(output/'replay-frozen.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'panels':sorted(replays,key=lambda r:r['name']),'saved_output_rows':22752,'boundary_rows':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_rows':sum(r['rows'] for r in replays if r['kind']=='document'),'training_diagnostic_rows':3456,'additional_initial_parity_rows':3552,'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,'new_reference_files_opened':False,'old_fresh_retention_references_admitted':True})
    selections={}
    for model in frozen['pipelines']:
        name=model['name'];selected=document_selection(documents[name]['scope_fresh']['rows'],inputs['sources']['scope_fresh'],toolchain=args.toolchain)
        require(selected['source_count']==len(selected['rows'])+len(selected['excluded'])==192,'native source-only selection dropped documents')
        selections[name]=selected
    selection_ref=write(output/'build-selection-frozen.json',{'schema':SCHEMA,'document':selections,'replay':replay_ref,'document_source_slots':1152,'document_panel':'scope_fresh','canonical_references_used_for_selection':False,'new_reference_files_opened':False,'clause_training_executed':False})
    builds={'document':{}}
    for name,selected in selections.items():
        builds['document'][name]=retained.build_batches(selected['rows'],output/'builds'/name,args)
        print({'phase':'built','model':name,'supported_for_lowering':len(selected['rows'])},flush=True)
    builds_ref=write(output/'builds-frozen.json',{'schema':SCHEMA,**builds,'selections':selection_ref,'replay':replay_ref,'new_reference_files_opened':False,'reference_derived_layout_evidence_opened':False,'old_fresh_retention_references_admitted':True})
    read_ref(frozen['selections'],parse=False);require(not guard.events,'sealed fresh reference access attempted before build freeze')
    guard.released=True;print({'phase':'references_released_after_build_freeze','builds':builds_ref},flush=True)
    evidence={key:read_ref(pin) for key,pin in evidence_refs.items()};targets={**inputs['tuning'],'scope_fresh':evidence['fresh_targets']}
    require(set(targets)==set(inputs['sources']) and clauses.source_rows(targets['scope_fresh'])==inputs['sources']['scope_fresh'],'complete fresh/admitted reference binding differs')
    audit_inputs={**inputs,'tuning_pairs':read_ref(manifest['artifacts']['tuning_pairs'])}
    exposure_ref=write(output/'authored-exposure-audit.json',annotations.audit_scope_annotations(audit_inputs,evidence['fresh_targets'],evidence['fresh_pairs'],evidence['annotation_ledger'],evidence['exposure_audit'],**historical_annotation_inputs(inputs)))
    boundary_metrics={name:{panel:scope_metrics(value,inputs['sources'][panel],targets[panel]) for panel,value in panels.items()} for name,panels in boundary_outputs.items()}
    document_metrics={};pipeline_reports=[]
    for model in frozen['pipelines']:
        name=model['name'];document_metrics[name]={}
        for panel,generation in documents[name].items():
            b=boundary_metrics[model['boundary_head']][panel]['details']
            if panel=='scope_fresh':
                metric=boundary_qualification.pipeline_funnel(generation,b,inputs['sources'][panel],targets[panel],selections[name],builds['document'][name])
            else:
                measured=retained.score_documents(generation,inputs['sources'][panel],targets[panel]);reference={r['candidate_id']:r for r in targets[panel]};bs={r['id']:r for r in b['rows']}
                rows=[boundary_qualification.attribution.pipeline_record(r,reference[r['candidate_id']],bs[r['candidate_id']]) for r in generation['rows']]
                metric={'metrics':{k:v for k,v in measured.items() if k!='rows'},'rows':rows,'attribution':boundary_qualification.attribution.pipeline_counts(rows),'native_build_not_executed_on_this_panel':True,'explicitly_admitted_retention_panel':True}
            document_metrics[name][panel]=metric
        pipeline_reports.append({**model,'panels':{p:{k:v for k,v in m.items() if k!='rows'} for p,m in document_metrics[name].items()}})
    details_ref=write(output/'scored-details.json',{'boundary':boundary_metrics,'document':document_metrics})
    require(all(sha(p)==wanted for p,wanted in pins.items()) and runner.read_config(plan['config']['path'])==inputs,'producer or fitting/source closure drift')
    for pin in (frozen_ref,frozen['plan'],frozen['selections'],frozen['heads'],*sealed):read_ref(pin,parse=False)
    opens_ref=write(output/'phase-open-audit.json',{'schema':SCHEMA,'sealed_paths':sorted(guard.paths),'events':guard.events,'before_build_freeze_attempts':sum(not r['after_build_freeze'] for r in guard.events),'build_freeze':builds_ref,'all_new_reference_reads_after_build_freeze':True,'replay_workers_had_same_four_file_OS_open_denial':True,'old_fresh_references_were_admitted_retention':True})
    result={'schema':SCHEMA,'qualification_plan':qualification_plan,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'replay':replay_ref,'builds':builds_ref,'details':details_ref,'authored_exposure_audit':exposure_ref,'phase_open_audit':opens_ref,'posthoc_evidence':evidence_refs,'models':frozen['models'],'clause_models':frozen['clause_models'],'pipelines':pipeline_reports,'boundary_metrics':{h:{p:v['metrics'] for p,v in panels.items()} for h,panels in boundary_metrics.items()},'producer_pins':pins,'primary_scope_choice':frozen['primary_scope_choice'],'parent_fallbacks':[m['name'] for m in frozen['models'] if m['selection'].startswith('parent_fallback')],'executed_optimizer_updates':800,'clause_optimizer_updates':0,'inventory':inventory,'boundary_source_documents_replayed':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='document'),'clause_occurrences_replayed':sum(r.get('clause_occurrences_replayed',0) for r in replays),'additional_initial_parity_source_evaluations':3552,'actual_lake_build_invocations':sum(b['backend_executed'] for rows in builds['document'].values() for b in rows),'build_attempts':sum(len(rows) for rows in builds['document'].values()),'native_fresh_document_build_slots':6,'document_build_panel':'scope_fresh','fresh_reference_files_opened_after_replay_and_build_freezes':True,'reference_derived_novelty_evidence_opened_after_build_freeze':True,'test_results_used_for_selection_or_gate_revision':False,'scope':'One fixed-seed architecture comparison with identical400-update input schedules/objectives. Scope-only readouts train on immutable token representations; selected policies are compared with the unchanged parent and two fixed clause decoders. Old fresh panels are now exposed retention. Authored flat-scope reference exactness and native compilation do not establish statutory semantic fidelity or supported nested-logic translation.',**FALSE}
    write(output/'summary.json',result);print({'complete':str(output/'summary.json'),'primary_scope_choice':result['primary_scope_choice'],'fresh_scope':{k:v['scope_fresh'] for k,v in result['boundary_metrics'].items()}},flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--lake-executable',required=True);parser.add_argument('--toolchain',default='leanprover/lean4:v4.34.1');parser.add_argument('--workers',type=int,default=3)
    run(parser.parse_args())
