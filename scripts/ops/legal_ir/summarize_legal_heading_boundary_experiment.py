#!/usr/bin/env python3
"""Independent qualification of a residual token-boundary learning.

The two-loss comparison keeps the encoder, scope decisions, clause models,
source order, residual architecture and selection gates fixed. Fresh references are opened
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

FALSE=prior.FALSE
SCHEMA='legal-heading-boundary-independent-qualification/v1'
ARMS=('control','rehearsal')
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


def matched_batches(supported_replay,supported_heading,*,steps=400):
    require(type(steps) is int and 1<=steps<=400,'bounded declared schedule required')
    require(all(r['supported'] is True for r in supported_replay+supported_heading),'unsupported records cannot enter boundary fitting')
    require(len({r['candidate_id'] for r in supported_replay+supported_heading})==len(supported_replay)+len(supported_heading),'disjoint supported training pool identities required')
    def stream(values,seed):
        rng=random.Random(seed)
        while True:
            order=list(range(len(values)));rng.shuffle(order)
            for i in order:yield values[i]
    replay=stream(supported_replay,1730);heading=stream(supported_heading,1731);result=[]
    for step in range(1,steps+1):
        left=[next(replay) for _ in range(6)];right=[next(heading) for _ in range(6)]
        result.append({'steps':step,'common_replay_ids':[r['candidate_id'] for r in left],'extra_ids':[r['candidate_id'] for r in right],'supported_count':12,'unsupported_count':0})
    return result


def training_role_masks(row,annotation):
    """Reconstruct masks from admitted exact spans, independently of model logits."""
    tokens=boundary.tokenize(row['source_text']);supported=row['supported']
    require(type(supported) is bool,'explicit supported profile label required')
    if not supported:
        require(annotation is None,'unsupported documents have no flat endpoint annotation')
        return [0.]*len(tokens),[False]*len(tokens),[False]*len(tokens)
    keys={'candidate_id','source_sha256','true_end_token_indices','editorial_hard_negative_token_indices','editorial_heading_spans','provenance'}
    require(type(annotation) is dict and set(annotation)==keys and annotation['candidate_id']==row['candidate_id'] and annotation['source_sha256']==row['source_sha256']==boundary.text_sha(row['source_text']),'source-bound closed TRAIN token-role annotation required')
    require(annotation['provenance']=='pinned_train_endpoints_and_optional_editorial_spans/v1','explicit admitted source-role provenance required')
    ends={c['char_end'] for c in row['clauses']};positive=[i for i,t in enumerate(tokens) if t['char_end'] in ends]
    require(len(positive)==len(ends)==len(row['clauses']) and positive[-1]==len(tokens)-1,'complete exact supported occurrence endpoints required')
    spans=annotation['editorial_heading_spans'];last=0
    for span in spans:
        require(set(span)=={'char_start','char_end'} and type(span['char_start']) is type(span['char_end']) is int and last<=span['char_start']<span['char_end']<=len(row['source_text']),'ordered exact editorial TRAIN intervals required');last=span['char_end']
    negative=[i for i,t in enumerate(tokens) if i not in positive and re.fullmatch(r'[^\w\s]',t['text']) and any(a['char_start']<=t['char_start']<t['char_end']<=a['char_end'] for a in spans)]
    require(annotation['true_end_token_indices']==positive and annotation['editorial_hard_negative_token_indices']==negative,'authored endpoint/punctuation masks differ from exact source coordinates')
    return [float(i in positive) for i in range(len(tokens))],[i in positive for i in range(len(tokens))],[i in negative for i in range(len(tokens))]


def boundary_loss_oracle(torch,logits,labels,valid_mask,supported,positive_mask,negative_mask,arm):
    require(arm in ARMS and logits.ndim==2 and labels.shape==valid_mask.shape==positive_mask.shape==negative_mask.shape==logits.shape and len(supported)==len(logits),'declared binary endpoint shapes required')
    eligible=valid_mask & supported.bool()[:,None]
    require(torch.equal(positive_mask,eligible & labels.bool()) and not bool((negative_mask & (~eligible | labels.bool())).any()),'unsupported, padded or mislabeled token enters auxiliary supervision')
    require(bool(positive_mask.any()) and bool(negative_mask.any()),'both endpoint and editorial classes required')
    positive=[];ordinary_negative=[];editorial_negative=[]
    for i in range(len(logits)):
        for j in range(logits.shape[1]):
            if not bool(eligible[i,j]):continue
            x=logits[i,j]
            # Binary log partition written directly, without runtime BCE helper.
            if bool(labels[i,j]):positive.append(torch.logsumexp(torch.stack((torch.zeros_like(x),-x)),0))
            else:
                term=torch.logsumexp(torch.stack((torch.zeros_like(x),x)),0);ordinary_negative.append(term)
                if bool(negative_mask[i,j]):editorial_negative.append(term)
    pos=torch.stack(positive).sum();neg=torch.stack(ordinary_negative).sum();editorial=torch.stack(editorial_negative).sum()
    denominator=int(eligible.sum());base=(12.*pos+neg)/denominator
    auxiliary=.5*(pos/len(positive)+editorial/len(editorial_negative));weight=.5 if arm=='rehearsal' else 0.
    return base+weight*auxiliary,{'eligible_token_count':denominator,'positive_token_count':len(positive),'ordinary_negative_token_count':len(ordinary_negative),'base_positive_bce_sum':pos,'base_negative_bce_sum':neg,'base_bce':base,'auxiliary_positive_count':len(positive),'auxiliary_negative_count':len(editorial_negative),'auxiliary_positive_bce_sum':pos,'auxiliary_negative_bce_sum':editorial,'auxiliary_positive_mean':pos/len(positive),'auxiliary_negative_mean':editorial/len(editorial_negative),'balanced_auxiliary_bce':auxiliary,'auxiliary_weight':weight,'weighted_auxiliary_bce':weight*auxiliary}


def verify_frozen_states(parent,initial,candidate,arm,trainable_names):
    names={'boundary_hidden.weight','boundary_hidden.bias','boundary_residual.weight','boundary_residual.bias'}
    require(arm in ARMS and set(trainable_names)==names,'closed1057 parameter boundary residual inventory required')
    a,b=initial['model_state'],candidate['model_state'];base=parent['model_state']
    require(set(a)==set(b)==set(base)|names and all(a[k]==b[k]==v for k,v in base.items()),'original parent encoder, boundary or scope tensors changed')
    changed=[k for k in sorted(names) if a[k]!=b[k]];require(changed,'boundary residual stage did not change any trainable tensor')
    def count(v):
        if isinstance(v,list):return sum(count(x) for x in v)
        require(type(v) in (int,float) and math.isfinite(v),'finite residual tensor required');return 1
    require(sum(count(b[k]) for k in names)==1057,'exact1057 residual parameters required')
    return {'trainable_parameters':1057,'changed_residual_tensors':changed,'all_original_parent_tensors_exact':True}


def verify_frozen_scope_outputs(parent,child):
    require(len(parent['rows'])==len(child['rows']),'fixed-scope source inventory differs')
    keys=('candidate_id','source_sha256','scope_logits','scope_supported_probability','raw_learned_scope_supported')
    for a,b in zip(parent['rows'],child['rows'],strict=True):
        require(all(a[k]==b[k] for k in keys),'boundary residual changed frozen raw scope output')
    return len(child['rows'])


def boundary_choice(stages,parent_metrics):
    require([s['steps'] for s in stages]==list(STAGES),'all100/200/400 stages required')
    def validate(metrics):
        for panel,m in metrics.items():
            require(set(m)=={'count','supported','unsupported','raw_supported_correct','raw_unsupported_accepted','raw_boundary_exact','supported_exact','unsupported_accepted'} and all(type(v) is int and v>=0 for v in m.values()),'closed nonnegative integer boundary metrics required')
            require(m['count']==m['supported']+m['unsupported'] and all(m[k]<=m['supported'] for k in ('raw_supported_correct','raw_boundary_exact','supported_exact')) and all(m[k]<=m['unsupported'] for k in ('raw_unsupported_accepted','unsupported_accepted')) and m['supported_exact']<=min(m['raw_supported_correct'],m['raw_boundary_exact']) and m['unsupported_accepted']<=m['raw_unsupported_accepted'],'boundary metric denominator or stage inclusion differs')
            require(all(m[k]==parent_metrics[panel][k] for k in ('count','supported','unsupported')),'candidate boundary metric denominator changed')
    validate(parent_metrics)
    eligible=[]
    for stage in stages:
        metrics=stage['metrics'];require(set(metrics)==set(parent_metrics) and 'heading_new' in metrics,'all admitted boundary panels required')
        validate(metrics);require(type(stage['raw_scope_logits_unchanged']) is bool,'explicit exact scope-invariance flag required')
        if stage['raw_scope_logits_unchanged'] and metrics['heading_new']['raw_boundary_exact']>parent_metrics['heading_new']['raw_boundary_exact'] and all(m['raw_boundary_exact']>=parent_metrics[p]['raw_boundary_exact'] and m['supported_exact']>=parent_metrics[p]['supported_exact'] and m['unsupported_accepted']<=parent_metrics[p]['unsupported_accepted'] and m['raw_supported_correct']==parent_metrics[p]['raw_supported_correct'] and m['raw_unsupported_accepted']==parent_metrics[p]['raw_unsupported_accepted'] for p,m in metrics.items()):eligible.append(stage)
    def rank(stage):
        m=stage['metrics'];return (m['heading_new']['raw_boundary_exact'],m['heading_new']['supported_exact'],sum(v['raw_boundary_exact'] for p,v in m.items() if p!='heading_new'),-stage['steps'])
    return max(eligible,key=rank) if eligible else None


def verify_loss_receipt(record,batch,rows_by_id,roles_by_id,loss,arm):
    import torch
    rows=[rows_by_id[k] for k in batch['common_replay_ids']+batch['extra_ids']]
    lengths=[len(boundary.tokenize(r['source_text'])) for r in rows];width=max(lengths)
    labels=[];positive=[];negative=[];valid=[]
    for row,length in zip(rows,lengths,strict=True):
        y,p,n=training_role_masks(row,roles_by_id.get(row['candidate_id']));pad=width-length
        labels.append(y+[0.]*pad);positive.append(p+[False]*pad);negative.append(n+[False]*pad);valid.append([True]*length+[False]*pad)
    supported=[r['supported'] for r in rows]
    require(record['steps']==batch['steps'] and record['labels']==labels and record['valid_mask']==valid and record['supported']==supported and record['positive_mask']==positive and record['negative_mask']==negative,'loss receipt labels/masks differ from exact admitted TRAIN source coordinates')
    for name in ('valid_mask','positive_mask','negative_mask'):
        require(all(type(v) is bool for row in record[name] for v in row),'exact boolean token masks required')
    require(all(type(v) is bool for v in record['supported']),'exact boolean supported labels required')
    logits=record['candidate_logits'];require(len(logits)==12 and all(len(row)==width and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in logits),'finite complete12row token logits required')
    x=torch.tensor(logits,dtype=torch.float64);y=torch.tensor(labels,dtype=torch.float64);v=torch.tensor(valid);sup=torch.tensor(supported);pos=torch.tensor(positive);neg=torch.tensor(negative)
    expected,parts=boundary_loss_oracle(torch,x,y,v,sup,pos,neg,arm);saved=record['objective_components']
    def close(actual,wanted,key):
        require(type(actual) in (int,float) and math.isfinite(actual) and math.isclose(actual,float(wanted),rel_tol=2e-5,abs_tol=2e-6),'independent endpoint loss arithmetic differs: '+key)
    for key,wanted in parts.items():
        if type(wanted) is int:require(type(saved[key]) is int and saved[key]==wanted,'token loss count differs: '+key)
        else:close(saved[key],wanted,key)
    for key,wanted in {'supported_documents':sum(supported),'unsupported_documents':len(rows)-sum(supported),'padding_token_count':sum(width-n for n in lengths),'excluded_unsupported_token_count':sum(n for n,ok in zip(lengths,supported,strict=True) if not ok)}.items():
        require(type(saved[key]) is int and saved[key]==wanted,'boundary loss supervision denominator differs: '+key)
    require(saved['positive_weight']==12. and saved['unsupported_token_supervision'] is False and saved['eligible_mask_sha256']==digest((v&sup[:,None]).tolist()) and saved['positive_mask_sha256']==digest(positive) and saved['negative_mask_sha256']==digest(negative),'declared role mask or loss weighting changed')
    close(saved['total_loss'],expected,'component_total');close(record['total_loss'],expected,'record_total');close(loss,expected,'loss_trace')
    return True


def verify_initialization(parent,initial,arm,manifest,tuning,parent_ref):
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    reconstructed=runtime.build_checkpoint(parent,arm=arm,seed=1730,training_manifest_sha256=digest(manifest),tuning_manifest_sha256=digest(tuning),parent_file_sha256=parent_ref['sha256'])
    require(initial==reconstructed and initial['parent_checkpoint']==parent and initial['parent_file_sha256']==PARENT_SHA and initial['parent_checkpoint_sha256']==digest(parent),'exact independent scope initialization/parent reconstruction differs')
    require(initial['additional_optimizer_steps']==0 and initial['optimizer_steps']==parent['optimizer_steps']==800 and initial['optimizer_resumption_supported'] is False,'fresh additional optimizer counter differs')
    require(all(v==0 for row in initial['model_state']['boundary_residual.weight'] for v in row) and all(v==0 for v in initial['model_state']['boundary_residual.bias']),'initial adapter residual must be exactly zero')
    return True


def initial_parent_parity(initial,parent_generations,sources):
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
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
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    plan=read_ref(frozen['plan']);selection=read_ref(frozen['selections']);parent=inputs['parent'];parent_ref=inputs['config']['boundary_parent']
    require(parent_ref['sha256']==PARENT_SHA and parent['optimizer_steps']==800,'fixed expanded1730 parent required')
    expected_plan={'arms':list(ARMS),'seed':1730,'stages':list(STAGES),'steps_per_arm':400,'trainable_parameter_counts':{'control':1057,'rehearsal':1057},'learning_rate':.004,'positive_token_weight':12.,'editorial_rehearsal_weight_by_arm':{'control':0.,'rehearsal':.5},'optimizer':'fresh_Adam','gradient_clip_norm':5.,'trial_wall_limit_seconds':1200,'identical_batches_all_arms':True,'common_supported_replay_rows':6,'supported_heading_rows_per_batch':6,'scope_threshold_and_surface_policy_unchanged':True,'clause_predictions_used_for_selection':False,'new_fresh_targets_opened':False,'training_inventory_count':1152,'supported_training_count':720,'unsupported_excluded_from_fitting':432,'new_training_count':0,'supported_replay_count':528,'supported_heading_count':192}
    require(all(type(plan[k]) is type(v) and plan[k]==v for k,v in expected_plan.items()),'frozen matched architecture protocol differs')
    require(plan['postselection_challenge_diagnostic_slots']==['control_final400','rehearsal_final400'] and plan['full_training_diagnostic_slots']==['parent','control_final400','rehearsal_final400'] and plan['challenge_diagnostics_used_for_selection'] is plan['training_fit_diagnostics_used_for_selection'] is False and plan['component_eligibility_is_not_deployment_qualification'] is True,'prospective diagnostic inference cannot be used for replacement selection')
    require(len(inputs['replay'])==768 and len(inputs['new_train'])==384 and len(inputs['tuning'])==20 and sum(len(v) for v in inputs['tuning'].values())==2160 and len(inputs['sources'])==21 and sum(len(v) for v in inputs['sources'].values())==2352,'complete planned training/tuning/source inventory required')
    require(plan['tuning_counts']=={k:len(v) for k,v in inputs['tuning'].items()} and plan['source_counts']=={k:len(v) for k,v in inputs['sources'].items()} and plan['training_source_inventory_sha256']==digest(inputs['replay']+inputs['new_train']),'source/training manifest binding differs')
    role_audit={'supervised_documents':len(inputs['boundary_training']),'excluded_unsupported_documents':432,'training_token_roles_sha256':digest(inputs['training_token_roles'])};require(plan['training_token_roles_sha256']==role_audit['training_token_roles_sha256'],'source-role mask commitment differs')
    verify_opaque_sources(clauses.source_rows(inputs['new_train']));verify_opaque_sources(inputs['sources']['heading_new']);opaque=verify_opaque_sources(inputs['sources']['heading_fresh'])
    require(selection['plan']==frozen['plan'] and selection['executed_optimizer_updates']==800 and selection['all_training_and_selection_complete'] is True and selection['new_fresh_targets_opened'] is selection['clause_predictions_used_for_selection'] is False and selection['choice_fixed_before_fresh_reference_release'] is True,'complete source-only independent scope selection freeze required')
    require([m['name'] for m in frozen['models']]==['parent','control','rehearsal','control_final400','rehearsal_final400'] and read_ref(frozen['heads'])==frozen['models'],'all five selected/control/diagnostic boundary slots required')
    require(frozen['models'][0]=={'name':'parent','arm':'parent','checkpoint':parent_ref,'selected_steps':0,'selection':'unchanged_parent_control','diagnostic_only':False},'unchanged parent head differs')
    pt=read_ref(selection['parent_tuning']);parent_metrics={};jobs=[]
    require(set(pt['generation'])==set(pt['metrics'])==set(inputs['tuning']),'complete parent tuning panels required')
    for panel,targets in inputs['tuning'].items():
        parent_metrics[panel]=audited_scope_metric(pt['generation'][panel],inputs['sources'][panel],targets,pt['metrics'][panel])
        jobs.append({'kind':'boundary','name':'parent-reference/'+panel,'checkpoint':parent_ref,'sources':inputs['sources'][panel],'generation':selection['parent_tuning'],'scope_panel':panel,'stage':True})
    trials=selection['trials'];require([t['name'] for t in trials]==list(ARMS),'both matched architecture trials required')
    expected_batches=matched_batches(inputs['supported_replay'],inputs['supported_heading']);initial_states=[];audits=[];initials={};stage_maps={};rows_by_id={r['candidate_id']:r for r in inputs['boundary_training']};roles_by_id={r['candidate_id']:r for r in inputs['training_token_roles']};require(len(rows_by_id)==len(roles_by_id)==720 and set(rows_by_id)==set(roles_by_id),'all720 supervised source-role bindings required')
    for trial in trials:
        arm=trial['arm'];require(trial['name']==arm and trial['seed']==1730 and trial['parent']==parent_ref and trial['executed_steps']==400,'trial attribution differs')
        training=read_ref(trial['training']);manifest=training['manifest']
        require(manifest=={'arm':arm,'seed':1730,'plan':frozen['plan'],'steps':400,'supported_replay_sha256':digest(inputs['supported_replay']),'supported_heading_sha256':digest(inputs['supported_heading']),'training_token_roles_sha256':digest(inputs['training_token_roles'])},'training manifest differs')
        initial=read_ref(trial['initial_checkpoint']);verify_initialization(parent,initial,arm,manifest,inputs['tuning'],parent_ref)
        initial_states.append(initial['model_state']);initials[arm]=initial
        names=initial['trainable_parameters'];require(training['optimizer_updates']==400 and len(training['losses'])==len(training['loss_receipts'])==len(training['batch_receipts'])==400 and training['batch_receipts']==expected_batches and training['batch_receipts_sha256']==digest(expected_batches),'all400 matched12row update receipts required')
        require(set(training['trainable_parameters'])==set(names) and training['trainable_parameter_count']==initial['trainable_parameter_count'] and training['optimizer_parameter_steps']=={k:400 for k in names},'complete trainable Adam counter inventory differs')
        require(training['initial_complete_model_state_sha256']==digest(initial['model_state']) and training['initial_predictions_equal_parent'] is training['initial_optimizer_state_empty'] is True and training['optimizer_resumed'] is training['optimizer_trajectory_independently_replayed'] is False and training['trial_wall_limit_seconds']==1200 and 0<training['wall_seconds']<=1200,'initial state/fresh Adam/wall receipts differ')
        for step,(loss,parts,exposure) in enumerate(zip(training['losses'],training['loss_receipts'],expected_batches,strict=True),1):
            require(parts['steps']==step and parts['total_loss']==loss and parts['gradient_clip_norm']==5. and type(parts['gradient_norm_before_clipping']) in (float,int) and math.isfinite(parts['gradient_norm_before_clipping']) and parts['gradient_norm_before_clipping']>=0 and parts['finite_updated_parameters'] is True,'finite update/gradient receipt differs')
            verify_loss_receipt(parts,exposure,rows_by_id,roles_by_id,loss,arm)
        require([s['steps'] for s in trial['stages']]==list(STAGES),'all100/200/400 stages required')
        normalized=[];stages=[];stage_maps[arm]={}
        for stage in trial['stages']:
            checkpoint=read_ref(stage['checkpoint']);runtime.restore(checkpoint)
            require(checkpoint['additional_optimizer_steps']==stage['steps'] and checkpoint['optimizer_steps']==800+stage['steps'],'stage cumulative/new optimizer counters differ')
            require({k:v for k,v in checkpoint.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')}=={k:v for k,v in initial.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')},'immutable stage provenance changed')
            tensor_audit=verify_frozen_states(parent,initial,checkpoint,arm,names)
            require(stage['frozen_base_state_sha256']==initial['frozen_parent_state_sha256'] and stage['raw_scope_logits_unchanged'] is True,'frozen token-state receipt differs')
            saved=read_ref(stage['tuning']);require(saved['metrics']==stage['metrics'] and set(saved['generation'])==set(inputs['tuning']),'complete stage tuning outputs required')
            metrics={}
            for panel,targets in inputs['tuning'].items():
                verify_frozen_scope_outputs(pt['generation'][panel],saved['generation'][panel])
                metrics[panel]=audited_scope_metric(saved['generation'][panel],inputs['sources'][panel],targets,saved['metrics'][panel])
                jobs.append({'kind':'boundary','name':f'{arm}/stage-{stage["steps"]}/'+panel,'checkpoint':stage['checkpoint'],'sources':inputs['sources'][panel],'generation':stage['tuning'],'scope_panel':panel,'stage':True})
            failures=[]
            for panel in sorted(metrics):
                m,p=metrics[panel],parent_metrics[panel]
                if m['raw_supported_correct']!=p['raw_supported_correct']:failures.append(panel+':raw_supported_scope_correct_changed')
                if m['raw_unsupported_accepted']!=p['raw_unsupported_accepted']:failures.append(panel+':raw_unsupported_accepted_changed')
                if m['raw_boundary_exact']<p['raw_boundary_exact']:failures.append(panel+':raw_boundary_document_exact_regressed')
                if m['supported_exact']<p['supported_exact']:failures.append(panel+':exact_supported_segmentation_regressed')
                if m['unsupported_accepted']>p['unsupported_accepted']:failures.append(panel+':final_unsupported_accepted_increased')
            if metrics['heading_new']['raw_boundary_exact']<=parent_metrics['heading_new']['raw_boundary_exact']:failures.append('heading_new:no_strict_raw_boundary_improvement')
            require(stage['eligible'] is (not failures) and stage['failures']==failures,'independent strict raw/final scope gates differ')
            normalized.append({'steps':stage['steps'],'metrics':metrics,'raw_scope_logits_unchanged':True});stage_maps[arm][stage['steps']]=metrics
            stages.append({'steps':stage['steps'],'checkpoint':stage['checkpoint'],'tuning':metrics,'eligible':not failures,'failures':failures,'tensor_audit':tensor_audit})
        chosen=boundary_choice(normalized,parent_metrics);steps=chosen['steps'] if chosen else 0;pin=next(s['checkpoint'] for s in trial['stages'] if s['steps']==steps) if chosen else parent_ref
        status='candidate' if chosen else 'parent_fallback_no_eligible_boundary_stage'
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status,'independent adapter/control selection differs')
        require(next(h for h in frozen['models'] if h['name']==arm)=={**{k:trial[k] for k in ('name','arm','checkpoint','selected_steps','selection')},'diagnostic_only':False},'selected/fallback head slot attribution differs')
        require(next(h for h in frozen['models'] if h['name']==arm+'_final400')=={'name':arm+'_final400','arm':arm,'checkpoint':trial['stages'][-1]['checkpoint'],'selected_steps':400,'selection':'postselection_final400_diagnostic','diagnostic_only':True},'predeclared final400 diagnostic attribution differs')
        audits.append({'name':arm,'parent':parent_ref,'initial_checkpoint':trial['initial_checkpoint'],'training':trial['training'],'stages':stages,'selection':status,'selected_steps':steps,'checkpoint':pin,'executed_updates':400,'batch_sha256':digest(expected_batches)})
    require(initial_states[0]==initial_states[1],'architecture arms did not start from identical complete model tensors')
    candidates=[a for a in audits if a['selection']=='candidate']
    def ranking(a):
        m=stage_maps[a['name']][a['selected_steps']]
        return (m['heading_new']['raw_boundary_exact'],m['heading_new']['supported_exact'],sum(v['raw_boundary_exact'] for p,v in m.items() if p!='heading_new'),-a['selected_steps'],a['name']=='control')
    primary=max(candidates,key=ranking)['name'] if candidates else 'parent'
    require(selection['primary_boundary_choice']==frozen['primary_boundary_choice']==primary and frozen['choice_fixed_before_fresh_reference_release'] is True,'pre-reference primary scope choice differs')
    parent_generations={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    initial_audits={arm:initial_parent_parity(initial,parent_generations,inputs['sources']) for arm,initial in initials.items()}
    return jobs,{'trials':audits,'parent_tuning':parent_metrics,'training_roles':role_audit,'opaque_fresh_sources':opaque,'primary_boundary_choice':primary,'initial_parent_parity':initial_audits,'initial_source_evaluations':sum(a['source_evaluations'] for a in initial_audits.values()),'optimizer_trajectory_replayed':False}

DOCUMENT_COUNTS={'heading_fresh':192,'prior_preservation_fresh':192,'root_condition_fresh_documents':96}
CLAUSE_PARENTS={'continuation':('facet_retention','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding':('temporal_presence','4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea')}


def verify_fitting(inputs):
    from scripts.ops.legal_ir import run_legal_scope_preservation_experiment as old_runner
    manifest=inputs['manifest'];old=read_ref(manifest['inputs']['prior_preservation_corpus'])
    require(manifest['replay_references']==old['replay_references'] and inputs['replay']==[r for pin in old['replay_references'].values() for r in read_ref(pin)],'historical768 TRAIN membership/order differs')
    refs={**old['retention_target_references'],'prior_preservation_tuning':old['artifacts']['tuning_targets'],'prior_preservation_fresh':old['artifacts']['fresh_targets']}
    require(manifest['retention_target_references']==refs and len(refs)==19,'all19 prior admitted retention panels required')
    require(all(manifest['artifacts'][k]==old['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')),'prior384 heading TRAIN content/pair/source pins changed')
    require(inputs['new_train']==read_ref(old['artifacts']['new_training_targets']),'prior heading TRAIN payload changed')
    prior_generation=read_ref(inputs['config']['prior_generation']);prior_plan=read_ref(prior_generation['plan']);old_inputs=old_runner.read_config(prior_plan['config']['path'])
    require(inputs['replay']==old_inputs['replay'] and inputs['new_train']==old_inputs['new_train'],'complete1152 TRAIN order/content must stay fixed')
    panels={digest(v) for v in inputs['tuning'].values()}
    require(all(digest(v) in panels for v in old_inputs['tuning'].values()),'prior admitted tuning panel dropped')
    require(inputs['tuning']['prior_preservation_fresh']==read_ref(old['artifacts']['fresh_targets']),'last challenge must be explicitly admitted retention')
    require(inputs['supported_replay']==[r for r in inputs['replay'] if r['supported']] and len(inputs['supported_replay'])==528 and inputs['supported_heading']==[r for r in inputs['new_train'] if r['supported']] and len(inputs['supported_heading'])==192 and inputs['boundary_training']==inputs['supported_replay']+inputs['supported_heading'],'exact720 supported-only supervision required')
    adapter=read_ref(old['inputs']['prior_adapter_corpus']);scope=read_ref(adapter['inputs']['prior_scope_corpus'])
    require(manifest['training_annotation_references']=={name:m['artifacts']['annotation_ledger'] for name,m in (('prior_scope',scope),('prior_adapter',adapter))},'TRAIN editorial evidence ancestry differs')
    annotations={}
    for pin in manifest['training_annotation_references'].values():
        for a in read_ref(pin)['document_rows']:
            require(a['candidate_id'] not in annotations,'duplicate admitted source annotation');annotations[a['candidate_id']]=a
    roles=inputs['training_token_roles'];require(roles==read_ref(manifest['artifacts']['training_token_roles']) and len(roles)==720 and len({r['candidate_id'] for r in roles})==720,'complete720 frozen TRAIN role records required')
    for row,role in zip(inputs['boundary_training'],roles,strict=True):
        training_role_masks(row,role);expected=[]
        a=annotations.get(row['candidate_id'])
        if a is not None:
            require(a['source_sha256']==row['source_sha256'] and a['supported'] is True,'admitted TRAIN annotation source/class mismatch')
            for occurrence in a['local_clause_coordinates']:
                for note in occurrence['editorial_context']:
                    left,right=note['start_char'],note['end_char']
                    require(note['author_stipulated_role']=='nonoperative_editorial_context' and row['source_text'][left:right]==note['source_text'] and occurrence['char_start']<=left<right<=occurrence['char_end'],'source-local authored editorial provenance differs')
                    expected.append({'char_start':left,'char_end':right})
        require(role['editorial_heading_spans']==sorted(expected,key=lambda x:(x['char_start'],x['char_end'])),'TRAIN heading spans were inflated or changed from pinned admitted annotations')
    hashes={r['source_sha256'] for r in inputs['replay']+inputs['new_train']}
    require(len(hashes)==1152 and all(not hashes&{r['source_sha256'] for r in rows} for rows in inputs['sources'].values()),'TRAIN/evaluation source overlap')
    pairs=read_ref(manifest['artifacts']['tuning_pairs']);verify_scope_pairs(inputs['tuning']['heading_new'],pairs,48)
    return {'unchanged_training_documents':1152,'supported_supervised_documents':720,'unsupported_excluded_documents':432,'prior_tuning_panels_retained':18,'training_roles_independently_bound_to_original_annotations':True,'new_tuning_pairs':48,'fit_evaluation_overlap':0}


def verify_inventory(inputs,frozen):
    require(frozen['all_training_selection_and_generation_complete'] is True and frozen['executed_optimizer_updates']==800 and frozen['new_fresh_targets_opened'] is frozen['clause_predictions_used_for_selection'] is False and frozen['all_source_raw_scope_logits_unchanged'] is frozen['no_joint_stage_search'] is True,'complete source-only fixed-factor generation required')
    require(frozen['clause_models']==inputs['config']['clause_models'] and len(frozen['clause_models'])==2,'two fixed clause models required')
    require(frozen['selected_boundary_slots']==3 and frozen['diagnostic_boundary_slots']==2 and frozen['challenge_diagnostics_used_for_selection'] is False,'predeclared final400 diagnostic slots cannot enter selection')
    models={m['name']:m for m in frozen['clause_models']};heads={h['name']:h for h in frozen['models']}
    require(set(models)=={'parent_continuation','parent_grounding'} and set(heads)==set(frozen['files'])=={'parent','control','rehearsal','control_final400','rehearsal_final400'},'fixed clause and five boundary inference slots required')
    for model in models.values():
        kind,wanted=CLAUSE_PARENTS[model['architecture']]
        require(model['name']=='parent_'+model['architecture'] and model['decoder_kind']==kind and model['checkpoint']['sha256']==wanted,'existing preselected clause parent changed')
        read_ref(model['checkpoint'],parse=False)
    require(set(frozen['sources'])==set(inputs['sources']) and all(read_ref(pin)==inputs['sources'][panel] for panel,pin in frozen['sources'].items()),'source-only frozen input rows differ')
    expected={m+'__boundary_'+h for m in models for h in heads}
    require(len(frozen['pipelines'])==10 and {p['name'] for p in frozen['pipelines']}==set(frozen['document_files'])==expected,'all ten fixed-clause/boundary pipeline slots required')
    require(set(frozen['document_sources'])==set(DOCUMENT_COUNTS) and all(frozen['document_sources'][p]==frozen['sources'][p] and len(inputs['sources'][p])==n for p,n in DOCUMENT_COUNTS.items()),'full new/exposed document panel inventory differs')
    for pipeline in frozen['pipelines']:
        model=models[pipeline['source_model_name']];head=heads[pipeline['boundary_head']]
        require(pipeline['name']==model['name']+'__boundary_'+head['name'] and pipeline['boundary_checkpoint']==head['checkpoint'] and pipeline['boundary_selection']==head['selection'] and pipeline['boundary_selected_steps']==head['selected_steps'] and pipeline['diagnostic_only'] is head['diagnostic_only'] and pipeline['clause_training_executed'] is False and all(pipeline[k]==model[k] for k in ('architecture','decoder_kind','checkpoint')) and set(frozen['document_files'][pipeline['name']])==set(DOCUMENT_COUNTS),'pipeline factor attribution or panel coverage differs')
    parent={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    for head,panels in frozen['files'].items():
        require(set(panels)==set(inputs['sources']),'selected boundary source panels missing')
        for panel,pin in panels.items():verify_frozen_scope_outputs(parent[panel],read_ref(pin))
    return {'boundary_slots':5,'selected_or_parent_slots':3,'fixed_final400_diagnostic_slots':2,'fixed_clause_models':2,'document_pipeline_slots':10,'fresh_source_documents':192,'fresh_supported_documents':96,'fresh_unsupported_documents':96,'boundary_inference_source_rows':11760,'pipeline_documents':4800,'clause_training_updates':0}


def audit_training_diagnostics(inputs,frozen):
    require(set(frozen['training_diagnostics'])=={'parent','control_final400','rehearsal_final400'},'all three preregistered full TRAIN diagnostic slots required')
    selection=read_ref(frozen['selections']);expected={'parent':inputs['config']['boundary_parent'],**{t['name']+'_final400':t['stages'][-1]['checkpoint'] for t in selection['trials']}}
    panels={'historical_replay':inputs['replay'],'new_training':inputs['new_train']};jobs=[];scores={};parent=None
    for name in ('parent','control_final400','rehearsal_final400'):
        pin=frozen['training_diagnostics'][name];saved=read_ref(pin)
        require(saved['checkpoint']==expected[name] and saved['training_fit_used_for_selection'] is saved['heldout_accuracy'] is False and set(saved['generation'])==set(saved['metrics'])==set(panels),'TRAIN diagnostic lineage/panels/selection attribution differs')
        if parent is None:parent=saved['generation']
        scores[name]={}
        for panel,targets in panels.items():
            sources=clauses.source_rows(targets);verify_frozen_scope_outputs(parent[panel],saved['generation'][panel])
            scores[name][panel]=audited_scope_metric(saved['generation'][panel],sources,targets,saved['metrics'][panel])
            jobs.append({'kind':'boundary','name':'TRAIN/'+name+'/'+panel,'checkpoint':expected[name],'sources':sources,'generation':pin,'scope_panel':panel,'training_diagnostic':True})
    return jobs,{'saved_source_rows':3456,'models':scores,'training_fit_used_for_selection':False,'heldout_accuracy':False}


_WORKER_GUARD=None

def init_worker(sealed):
    global _WORKER_GUARD
    _WORKER_GUARD=SealedReadGuard(sealed);sys.addaudithook(_WORKER_GUARD.event)


def replay_group(group):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
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
    from scripts.ops.legal_ir import summarize_legal_scope_preservation_experiment as preservation
    parent=read_ref(inputs['manifest']['inputs']['prior_preservation_corpus'])
    bundle=preservation.historical_annotation_inputs({'manifest':parent})
    bundle['historical_manifests']['prior_preservation']=parent
    bundle['prior_annotation_ledgers']['prior_preservation']={'reference':parent['artifacts']['annotation_ledger'],'ledger':read_ref(parent['artifacts']['annotation_ledger'])}
    texts=set(bundle['historical_source_inventory']['source_texts'])
    for name,key in (('prior_preservation_tuning','tuning_targets'),('prior_preservation_fresh','fresh_targets')):
        pin=parent['artifacts'][key];rows=read_ref(pin);bundle['historical_documents'][name]={'reference':pin,'rows':rows};texts.update(r['source_text'] for r in rows)
    bundle['historical_source_inventory']['source_texts']=sorted(texts)
    return bundle



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

def endpoint_diagnostics(generation,sources,targets,annotation_rows):
    predicted={r['candidate_id']:r for r in generation['rows']};gold={r['candidate_id']:r for r in targets};notes={a['candidate_id']:a for a in annotation_rows}
    require(len(predicted)==len(gold)==len(sources) and set(predicted)==set(gold)=={r['candidate_id'] for r in sources} and set(gold)<=set(notes),'complete endpoint diagnostics source/reference/annotation join required')
    rows=[]
    for source in sources:
        identity=source['candidate_id'];r=gold[identity];p=predicted[identity];a=notes[identity];tokens=boundary.tokenize(source['source_text'])
        require(p['source_sha256']==r['source_sha256']==a['source_sha256']==source['source_sha256']==boundary.text_sha(source['source_text']),'endpoint source commitment differs')
        logits=p['boundary_logits'];require(len(logits)==len(tokens) and all(type(v) in (float,int) and math.isfinite(v) for v in logits),'all source-token logits required')
        ends={i for i,x in enumerate(logits) if x>=0};require(sorted(ends)==p['boundary_token_indices'],'raw endpoint threshold differs')
        row={'id':identity,'supported':r['supported'],'heading':a['factors']['heading'],'predicted_end_count':len(ends),'scope_supported':p['raw_learned_scope_supported']}
        if r['supported']:
            offsets={c['char_end'] for c in r['clauses']};wanted={i for i,t in enumerate(tokens) if t['char_end'] in offsets}
            require(len(wanted)==len(offsets),'reference endpoint missing from token coordinates')
            spans=[n for c in a['local_clause_coordinates'] for n in c['editorial_context']]
            editorial={i for i,t in enumerate(tokens) if i not in wanted and re.fullmatch(r'[^\w\s]',t['text']) and any(n['start_char']<=t['char_start']<t['char_end']<=n['end_char'] for n in spans)}
            row.update(valid_tokens=len(tokens),gold_end_count=len(wanted),true_positive=len(ends&wanted),false_positive=len(ends-wanted),false_negative=len(wanted-ends),editorial_negative_tokens=len(editorial),editorial_false_ends=len(ends&editorial),raw_endpoint_exact=ends==wanted)
        else:row.update(token_gold_available=False,endpoint_error_scored=False)
        rows.append(row)
    supported=[r for r in rows if r['supported']];keys=('valid_tokens','gold_end_count','true_positive','false_positive','false_negative','editorial_negative_tokens','editorial_false_ends')
    return {'metrics':{'documents':len(rows),'supported_documents':len(supported),'unsupported_without_endpoint_gold':len(rows)-len(supported),**{k:sum(r[k] for r in supported) for k in keys},'raw_endpoint_exact':sum(r['raw_endpoint_exact'] for r in supported),'raw_endpoints_scored_even_when_scope_abstains':True},'by_heading':{family:{'supported_documents':len(part),'raw_endpoint_exact':sum(r['raw_endpoint_exact'] for r in part),'editorial_false_ends':sum(r['editorial_false_ends'] for r in part),'editorial_negative_tokens':sum(r['editorial_negative_tokens'] for r in part)} for family in sorted({r['heading'] for r in supported}) for part in [[r for r in supported if r['heading']==family]]},'rows':rows}


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_heading_boundary_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_heading_boundary_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_heading_boundary_annotations as annotations
    from scripts.ops.legal_ir import summarize_legal_scope_preservation_experiment as preservation
    from ipfs_datasets_py.logic.autoformal import legal_clause_heading_boundary as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU qualification workers required')
    folder,output=Path(args.run_directory).resolve(),Path(args.output).resolve()
    frozen_ref=ref(folder/'generation-frozen.json');frozen=read_ref(frozen_ref)
    require(frozen['schema']==runner.SCHEMA,'declared completed scope adapter generation required')
    plan=read_ref(frozen['plan']);config=read_ref(plan['config']);manifest=read_ref(config['heading_corpus_manifest'])
    evidence_refs={key:manifest['artifacts'][key] for key in ('fresh_targets','fresh_pairs','annotation_ledger','exposure_audit')}
    sealed=list(evidence_refs.values());guard=SealedReadGuard(sealed);sys.addaudithook(guard.event)
    inputs=runner.read_config(plan['config']['path']);inventory=verify_inventory(inputs,frozen)
    pins=dict(plan['producer_pins']);require(all(sha(path)==wanted for path,wanted in pins.items()),'original fitting producer drift before qualification')
    for module in (sys.modules[__name__],prior,runner,corpus,annotations,annotations.adapter,annotations.adapter.previous,preservation,runtime,boundary,clauses,retained,retained.prior,retained.calendar,retained.calendar_summary,retained.compose,boundary_qualification,previous,gate):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    require(all(sha(path)==wanted for path,wanted in pins.items()),'frozen producer source drift')
    output.mkdir(parents=True,exist_ok=False)
    qualification_plan=write(output/'qualification-plan.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'producer_pins':pins,'sealed_references':evidence_refs,'fresh_document_build_slots':10,'native_build_panel':'heading_fresh','new_reference_files_opened':False,'old_fresh_reference_panels_admitted_as_retention':True,'clause_training_executed':False})
    fitting=verify_fitting(inputs);jobs,training=verify_training(inputs,frozen)
    training_jobs,diagnostics=audit_training_diagnostics(inputs,frozen);jobs+=training_jobs
    require(training['initial_source_evaluations']==4704,'both initial checkpoints must be checked on all2352source rows')
    training_ref=write(output/'training-and-selection-audit.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'selections':frozen['selections'],'fitting':fitting,**training,'full_training_diagnostics':diagnostics,'executed_boundary_updates':800,'clause_training_updates':0,'source_semantics_verified':False})
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
    require(sum(len(j['sources']) for j in jobs)==35136 and sum(len(j['sources']) for j in jobs if j.get('training_diagnostic'))==3456,'complete saved output/diagnostic replay denominator differs')
    groups=prior.group_replay_jobs(jobs);replays=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn'),initializer=init_worker,initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group,g) for g in groups]):replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==35136,'full saved numerical replay incomplete')
    for a in frozen['models']:
        for b in frozen['models']:
            if a['checkpoint']==b['checkpoint']:
                require(boundary_outputs[a['name']]==boundary_outputs[b['name']],'same-checkpoint head slots changed outputs')
                require(all(documents[m['name']+'__boundary_'+a['name']]==documents[m['name']+'__boundary_'+b['name']] for m in frozen['clause_models']),'same-checkpoint pipeline slots changed outputs')
    replay_ref=write(output/'replay-frozen.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'panels':sorted(replays,key=lambda r:r['name']),'saved_output_rows':35136,'boundary_rows':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_rows':sum(r['rows'] for r in replays if r['kind']=='document'),'training_diagnostic_rows':3456,'additional_initial_parity_rows':4704,'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,'new_reference_files_opened':False,'old_fresh_retention_references_admitted':True})
    selections={}
    for model in frozen['pipelines']:
        name=model['name'];selected=document_selection(documents[name]['heading_fresh']['rows'],inputs['sources']['heading_fresh'],toolchain=args.toolchain)
        require(selected['source_count']==len(selected['rows'])+len(selected['excluded'])==192,'native source-only selection dropped documents')
        selections[name]=selected
    selection_ref=write(output/'build-selection-frozen.json',{'schema':SCHEMA,'document':selections,'replay':replay_ref,'document_source_slots':1920,'document_panel':'heading_fresh','canonical_references_used_for_selection':False,'new_reference_files_opened':False,'clause_training_executed':False})
    builds={'document':{}}
    for name,selected in selections.items():
        builds['document'][name]=retained.build_batches(selected['rows'],output/'builds'/name,args)
        print({'phase':'built','model':name,'supported_for_lowering':len(selected['rows'])},flush=True)
    builds_ref=write(output/'builds-frozen.json',{'schema':SCHEMA,**builds,'selections':selection_ref,'replay':replay_ref,'new_reference_files_opened':False,'reference_derived_layout_evidence_opened':False,'old_fresh_retention_references_admitted':True})
    read_ref(frozen['selections'],parse=False);require(not guard.events,'sealed fresh reference access attempted before build freeze')
    guard.released=True;print({'phase':'references_released_after_build_freeze','builds':builds_ref},flush=True)
    evidence={key:read_ref(pin) for key,pin in evidence_refs.items()};targets={**inputs['tuning'],'heading_fresh':evidence['fresh_targets']}
    require(set(targets)==set(inputs['sources']) and clauses.source_rows(targets['heading_fresh'])==inputs['sources']['heading_fresh'],'complete fresh/admitted reference binding differs')
    audit_inputs={**inputs,'replay':{k:read_ref(v) for k,v in manifest['replay_references'].items()},'training_pairs':read_ref(manifest['artifacts']['training_pairs']),'tuning_pairs':read_ref(manifest['artifacts']['tuning_pairs'])}
    exposure_ref=write(output/'authored-exposure-audit.json',annotations.audit_heading_annotations(audit_inputs,evidence['fresh_targets'],evidence['fresh_pairs'],evidence['annotation_ledger'],evidence['exposure_audit'],**historical_annotation_inputs(inputs)))
    boundary_metrics={name:{panel:scope_metrics(value,inputs['sources'][panel],targets[panel]) for panel,value in panels.items()} for name,panels in boundary_outputs.items()}
    document_metrics={};pipeline_reports=[]
    for model in frozen['pipelines']:
        name=model['name'];document_metrics[name]={}
        for panel,generation in documents[name].items():
            b=boundary_metrics[model['boundary_head']][panel]['details']
            if panel=='heading_fresh':
                metric=boundary_qualification.pipeline_funnel(generation,b,inputs['sources'][panel],targets[panel],selections[name],builds['document'][name])
            else:
                measured=retained.score_documents(generation,inputs['sources'][panel],targets[panel]);reference={r['candidate_id']:r for r in targets[panel]};bs={r['id']:r for r in b['rows']}
                rows=[boundary_qualification.attribution.pipeline_record(r,reference[r['candidate_id']],bs[r['candidate_id']]) for r in generation['rows']]
                metric={'metrics':{k:v for k,v in measured.items() if k!='rows'},'rows':rows,'attribution':boundary_qualification.attribution.pipeline_counts(rows),'native_build_not_executed_on_this_panel':True,'explicitly_admitted_retention_panel':True}
            document_metrics[name][panel]=metric
        pipeline_reports.append({**model,'panels':{p:{k:v for k,v in m.items() if k!='rows'} for p,m in document_metrics[name].items()}})
    endpoint_metrics={head:{panel:endpoint_diagnostics(value,inputs['sources'][panel],targets[panel],evidence['annotation_ledger']['document_rows']) for panel,value in panels.items() if panel in ('heading_new','heading_fresh')} for head,panels in boundary_outputs.items()}
    details_ref=write(output/'scored-details.json',{'boundary':boundary_metrics,'document':document_metrics,'endpoints':endpoint_metrics})
    require(all(sha(p)==wanted for p,wanted in pins.items()) and runner.read_config(plan['config']['path'])==inputs,'producer or fitting/source closure drift')
    for pin in (frozen_ref,frozen['plan'],frozen['selections'],frozen['heads'],*sealed):read_ref(pin,parse=False)
    opens_ref=write(output/'phase-open-audit.json',{'schema':SCHEMA,'sealed_paths':sorted(guard.paths),'events':guard.events,'before_build_freeze_attempts':sum(not r['after_build_freeze'] for r in guard.events),'build_freeze':builds_ref,'all_new_reference_reads_after_build_freeze':True,'replay_workers_had_same_four_file_OS_open_denial':True,'old_fresh_references_were_admitted_retention':True})
    result={'schema':SCHEMA,'qualification_plan':qualification_plan,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'replay':replay_ref,'builds':builds_ref,'details':details_ref,'authored_exposure_audit':exposure_ref,'phase_open_audit':opens_ref,'posthoc_evidence':evidence_refs,'models':frozen['models'],'clause_models':frozen['clause_models'],'pipelines':pipeline_reports,'boundary_metrics':{h:{p:v['metrics'] for p,v in panels.items()} for h,panels in boundary_metrics.items()},'endpoint_diagnostics':{h:{p:{k:v for k,v in value.items() if k!='rows'} for p,value in panels.items()} for h,panels in endpoint_metrics.items()},'producer_pins':pins,'primary_boundary_choice':frozen['primary_boundary_choice'],'parent_fallbacks':[m['name'] for m in frozen['models'] if m['selection'].startswith('parent_fallback')],'diagnostic_final400_heads':[m['name'] for m in frozen['models'] if m.get('diagnostic_only')],'diagnostic_fresh_scores_used_for_selection':False,'executed_optimizer_updates':800,'clause_optimizer_updates':0,'inventory':inventory,'boundary_source_documents_replayed':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='document'),'clause_occurrences_replayed':sum(r.get('clause_occurrences_replayed',0) for r in replays),'additional_initial_parity_source_evaluations':4704,'actual_lake_build_invocations':sum(b['backend_executed'] for rows in builds['document'].values() for b in rows),'build_attempts':sum(len(rows) for rows in builds['document'].values()),'native_fresh_document_build_slots':10,'document_build_panel':'heading_fresh','fresh_reference_files_opened_after_replay_and_build_freezes':True,'reference_derived_novelty_evidence_opened_after_build_freeze':True,'test_results_used_for_selection_or_gate_revision':False,'scope':'One fixed-seed matched boundary-loss comparison with identical400-update source schedules and residual architecture. Only token-boundary residual parameters train; original encoder, boundary/scope heads and clause decoders stay fixed. Old fresh panels are now exposed retention. Authored flat-scope reference exactness and native compilation do not establish statutory semantic fidelity or supported nested-logic translation.',**FALSE}
    write(output/'summary.json',result);print({'complete':str(output/'summary.json'),'primary_boundary_choice':result['primary_boundary_choice'],'fresh_scope':{k:v['heading_fresh'] for k,v in result['boundary_metrics'].items()}},flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--lake-executable',required=True);parser.add_argument('--toolchain',default='leanprover/lean4:v4.34.1');parser.add_argument('--workers',type=int,default=3)
    run(parser.parse_args())
