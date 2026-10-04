#!/usr/bin/env python3
"""Independent qualification of readout freezing and correct-parent scope KL.

The four-arm comparison keeps the attention graph, encoder, token boundaries,
clause models and source order fixed. Teacher masking uses admitted TRAIN labels.
Fresh references open only after exact replay and native build commitments.
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
SCHEMA='legal-scope-preservation-independent-qualification/v1'
ARMS=('control','freeze_readout','distill','freeze_distill')
STAGES=(100,200,400)
FROZEN_READOUT={'freeze_readout','freeze_distill'}
DISTILLED={'distill','freeze_distill'}
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
    require(arm in ARMS and set(initial['model_state'])==set(candidate['model_state']),'complete preservation tensor inventory required')
    a,b=initial['model_state'],candidate['model_state'];base=parent['model_state']
    require(set(base)<=set(a),'scope preservation omitted pretrained tensors')
    for key in base:
        require(a[key]==base[key],'initial pretrained tensor changed: '+key)
        if not key.startswith('scope.') or arm in FROZEN_READOUT:
            require(b[key]==base[key],'scope fitting changed frozen pretrained tensor: '+key)
    expected={'attention_hidden.weight','attention_hidden.bias','attention_score.weight','attention_score.bias','scope_residual.weight','scope_residual.bias'}
    if arm not in FROZEN_READOUT:expected|={'scope.weight','scope.bias'}
    require(set(trainable_names)==expected and set(trainable_names)<=set(a),'closed preservation training inventory required')
    require(all(b[k]==a[k] for k in a if k not in expected),'frozen pretrained readout/encoder tensor changed')
    changed=[k for k in sorted(a) if a[k]!=b[k]]
    require(changed and set(changed)<=expected,'candidate must change only authorized scope tensors')
    def count(value):
        if isinstance(value,list):return sum(count(v) for v in value)
        require(type(value) in (int,float) and math.isfinite(value),'nonfinite scope tensor');return 1
    total=sum(count(b[k]) for k in expected)
    require(total==(1187 if arm in FROZEN_READOUT else 1317),'preservation trainable parameter count differs')
    return {'trainable_parameters':total,'changed_scope_tensors':changed,'all_frozen_encoder_and_readout_tensors_exact':True,'parent_readout_frozen':arm in FROZEN_READOUT}


def preservation_loss_oracle(torch,logits,labels,teacher_logits,arm):
    """Explicit unweighted mean KL over exactly parent-correct TRAIN rows.

    Both the teacher distribution and correctness mask are detached. Ties follow
    ordinary argmax (class0). This checks logged arithmetic and gradients, not
    the optimizer trajectory that produced the candidate logits.
    """
    require(arm in ARMS and teacher_logits.shape==logits.shape,'matched teacher/candidate logits required')
    ce,parts=scope_loss_oracle(torch,logits,labels)
    teacher=teacher_logits.detach();mask=[int(teacher[i].argmax())==int(label) for i,label in enumerate(labels)]
    terms=[]
    for i,correct in enumerate(mask):
        if not correct:continue
        log_parent=teacher[i]-torch.logsumexp(teacher[i],0)
        log_candidate=logits[i]-torch.logsumexp(logits[i],0)
        terms.append(sum(torch.exp(log_parent[j])*(log_parent[j]-log_candidate[j]) for j in range(2)))
    kl_sum=torch.stack(terms).sum() if terms else logits.sum()*0
    kl=kl_sum/len(terms) if terms else kl_sum
    weight=1. if arm in DISTILLED else 0.
    return ce+weight*kl,{**parts,'cross_entropy':ce,'teacher_correct_mask':mask,'teacher_correct_count':len(terms),'teacher_kl_sum':kl_sum,'teacher_kl':kl,'distillation_weight':weight,'weighted_distillation':weight*kl}


def teacher_batch_audit(inputs,expected_batches):
    """One independent parent forward per distinct recorded batch; no labels to model."""
    import torch
    torch.set_num_threads(1)
    decoder=boundary.ClauseBoundaryDecoder(inputs['parent']);network=decoder.network
    network.eval();before=digest({k:v.detach().cpu().tolist() for k,v in network.state_dict().items()})
    lookup={r['candidate_id']:r for r in inputs['replay']+inputs['new_train']}
    require(len(lookup)==1152,'teacher must use the exact1152 fitting records')
    results=[]
    for batch in expected_batches:
        identities=batch['common_replay_ids']+batch['extra_ids'];records=[lookup[k] for k in identities]
        labels=[int(r['supported']) for r in records]
        ids,features,lengths=boundary.tensor_batch(torch,clauses.source_rows(records))[:3]
        with torch.no_grad():logits=network(ids,features,lengths)[1]
        values=logits.detach().cpu().tolist();mask=[int(v.argmax())==label for v,label in zip(logits,labels,strict=True)]
        results.append({'steps':batch['steps'],'ids':identities,'labels':labels,'teacher_logits':values,'teacher_correct_mask':mask,'teacher_correct_count':sum(mask)})
    require(before==digest(inputs['parent']['model_state'])==digest({k:v.detach().cpu().tolist() for k,v in network.state_dict().items()}),'independent teacher forward changed frozen parent')
    require(all(p.grad is None for p in network.parameters()),'teacher audit accumulated gradients')
    return results,{'source_evaluations':4800,'batch_forwards':400,'checkpoint':inputs['config']['boundary_parent'],'model_state_before_sha256':before,'model_state_after_sha256':before,'training_inventory_sha256':digest(inputs['replay']+inputs['new_train']),'batches_sha256':digest(results),'teacher_labels_only_from_frozen_TRAIN':True,'optimizer_trajectory_replayed':False}


def verify_objective_receipt(parts,teacher_record,expected_teacher,exposure,loss,arm):
    import torch
    labels=expected_teacher['labels'];teacher_values=expected_teacher['teacher_logits'];mask=expected_teacher['teacher_correct_mask']
    require(type(teacher_record['teacher_correct_mask']) is list and len(teacher_record['teacher_correct_mask'])==12 and all(type(v) is bool for v in teacher_record['teacher_correct_mask']) and all(type(v) is int and v in (0,1) for v in teacher_record['scope_labels']),'teacher labels and correctness mask require exact integer/bool types')
    require(teacher_record=={'steps':exposure['steps'],'teacher_logits':teacher_values,'teacher_correct_mask':mask,'scope_labels':labels},'teacher source/logits/mask differ from independent exact-batch parent inference')
    objective=parts['objective_components'];candidate=parts['candidate_logits']
    require(type(candidate) is list and len(candidate)==12 and all(type(row) is list and len(row)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in candidate),'finite complete12x2 candidate logits required')
    actual,oracle=preservation_loss_oracle(torch,torch.tensor(candidate,dtype=torch.float64),labels,torch.tensor(teacher_values,dtype=torch.float64),arm)
    def close(x,y,name):
        require(type(x) in (float,int) and math.isfinite(x) and math.isclose(x,float(y),rel_tol=2e-5,abs_tol=2e-6),'independent objective receipt differs: '+name)
    for key in ('unsupported_count','supported_count','weighted_denominator'):
        require(type(parts[key]) is int and parts[key]==objective[key]==oracle[key],'independent class count/denominator differs: '+key)
    for key in ('unsupported_nll_sum','supported_nll_sum'):
        close(parts[key],oracle[key],key);close(objective[key],oracle[key],key)
    close(objective['cross_entropy'],oracle['cross_entropy'],'cross_entropy')
    require(all(type(v) is bool for v in objective['teacher_correct_mask']),'objective correctness mask must use exact booleans')
    require(objective['teacher_correct_mask']==mask and objective['teacher_scope_logits']==teacher_values and objective['teacher_scope_logits_sha256']==digest(teacher_values),'bound teacher outputs or mask differ')
    for key,value in {'teacher_correct_count':sum(mask),'teacher_correct_unsupported_count':sum(c and y==0 for c,y in zip(mask,labels,strict=True)),'teacher_correct_supported_count':sum(c and y==1 for c,y in zip(mask,labels,strict=True))}.items():
        require(type(objective[key]) is int and objective[key]==value,'teacher correctness count differs: '+key)
    require(objective['teacher_kl_weight']==(1. if arm in DISTILLED else 0.) and objective['teacher_kl_temperature']==1. and objective['teacher_logits_detached'] is True and objective['teacher_kl_class_weighted'] is False,'declared parent KL direction/normalization/temperature coefficient differs')
    close(objective['teacher_kl'],oracle['teacher_kl'],'teacher_kl')
    close(objective['weighted_teacher_kl'],oracle['weighted_distillation'],'weighted_teacher_kl')
    close(objective['total_loss'],actual,'objective_total');close(parts['total_loss'],actual,'recorded_total');close(loss,actual,'loss_trace')
    verify_scope_loss_receipt(parts,exposure,objective['cross_entropy'])
    return True


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
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    reconstructed=runtime.build_checkpoint(parent,arm=arm,seed=1730,training_manifest_sha256=digest(manifest),tuning_manifest_sha256=digest(tuning),parent_file_sha256=parent_ref['sha256'])
    require(initial==reconstructed and initial['parent_checkpoint']==parent and initial['parent_file_sha256']==PARENT_SHA and initial['parent_checkpoint_sha256']==digest(parent),'exact independent scope initialization/parent reconstruction differs')
    require(initial['additional_optimizer_steps']==0 and initial['optimizer_steps']==parent['optimizer_steps']==800 and initial['optimizer_resumption_supported'] is False,'fresh additional optimizer counter differs')
    require(all(v==0 for row in initial['model_state']['scope_residual.weight'] for v in row) and all(v==0 for v in initial['model_state']['scope_residual.bias']),'initial adapter residual must be exactly zero')
    return True


def initial_parent_parity(initial,parent_generations,sources):
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    decoder=runtime.decoder(initial);rows=0;payloads={}
    for panel,source_rows in sources.items():
        expected=deepcopy(parent_generations[panel])
        for report in expected['reports']:report['checkpoint_sha256']=digest(initial)
        actual=clauses.decode_all(decoder,source_rows)
        require(actual==expected,'full initial adapter output differs from parent beyond declared checkpoint provenance: '+panel)
        payloads[panel]=digest(actual);rows+=len(source_rows)
    require(digest({k:v.detach().cpu().tolist() for k,v in decoder.network.state_dict().items()})==digest(initial['model_state']),'initial parity inference changed model weights')
    return {'source_evaluations':rows,'panel_output_sha256':payloads,'all_numeric_and_final_outputs_equal_parent':True,'only_metadata_difference':'reports[].checkpoint_sha256','saved_output_replay':False,'new_fresh_reference_access':False}


def primary_scope_choice(audits,stage_maps):
    require(len(audits)==4 and [a['name'] for a in audits]==list(ARMS),'all four preservation policy slots required')
    candidates=[a for a in audits if a['selection']=='candidate']
    def ranking(a):
        m=stage_maps[a['name']][a['selected_steps']]
        return (m['scope_new']['raw_supported_correct'],m['scope_new']['supported_exact'],sum(v['supported_exact'] for p,v in m.items() if p!='scope_new'),-a['selected_steps'],-ARMS.index(a['name']))
    return max(candidates,key=ranking)['name'] if candidates else 'parent'


def verify_training(inputs,frozen):
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    plan=read_ref(frozen['plan']);selection=read_ref(frozen['selections']);parent=inputs['parent'];parent_ref=inputs['config']['boundary_parent']
    require(parent_ref['sha256']==PARENT_SHA and parent['optimizer_steps']==800,'fixed expanded1730 parent required')
    expected_plan={'arms':list(ARMS),'seed':1730,'stages':list(STAGES),'steps_per_arm':400,'trainable_parameter_counts':{a:1187 if a in FROZEN_READOUT else 1317 for a in ARMS},'learning_rate':.004,'scope_class_weights':[3.,1.],'optimizer':'fresh_Adam','gradient_clip_norm':5.,'trial_wall_limit_seconds':1200,'identical_batches_all_arms':True,'common_replay_rows':6,'contrast_pairs_per_batch':3,'scope_threshold_and_surface_policy_unchanged':True,'clause_predictions_used_for_selection':False,'new_fresh_targets_opened':False,'replay_count':768,'new_training_count':384}
    require(all(type(plan[k]) is type(v) and plan[k]==v for k,v in expected_plan.items()),'frozen matched architecture protocol differs')
    require(plan['distillation_weight_by_arm']=={a:1. if a in DISTILLED else 0. for a in ARMS} and plan['distillation_temperature']==1. and plan['teacher']==parent_ref and plan['teacher_mask']=='parent_raw_argmax_equals_training_scope_label' and plan['distillation_reduction']=='mean_KL_parent_to_candidate_over_correct_teacher_rows_zero_if_empty' and plan['all_arms_compute_identical_teacher_forwards_and_KL'] is True,'frozen correct-parent-only KL protocol differs')
    require(len(inputs['replay'])==768 and len(inputs['new_train'])==384 and len(inputs['tuning'])==18 and sum(len(v) for v in inputs['tuning'].values())==1872 and len(inputs['sources'])==19 and sum(len(v) for v in inputs['sources'].values())==2064,'complete18tuning/19source inventory required')
    require(plan['tuning_counts']=={k:len(v) for k,v in inputs['tuning'].items()} and plan['source_counts']=={k:len(v) for k,v in inputs['sources'].items()} and plan['training_source_inventory_sha256']==digest(inputs['replay']+inputs['new_train']),'source/training manifest binding differs')
    pair_audit=verify_scope_pairs(inputs['new_train'],inputs['training_pairs'],192)
    verify_opaque_sources(clauses.source_rows(inputs['new_train']));verify_opaque_sources(inputs['sources']['scope_new']);opaque=verify_opaque_sources(inputs['sources']['scope_fresh'])
    require(selection['plan']==frozen['plan'] and selection['executed_optimizer_updates']==1600 and selection['all_training_and_selection_complete'] is True and selection['new_fresh_targets_opened'] is selection['clause_predictions_used_for_selection'] is False and selection['choice_fixed_before_fresh_reference_release'] is True,'complete source-only independent scope selection freeze required')
    require([m['name'] for m in frozen['models']]==['parent',*ARMS] and read_ref(frozen['heads'])==frozen['models'],'all five parent/candidate/fallback scope slots required')
    require(frozen['models'][0]=={'name':'parent','arm':'parent','checkpoint':parent_ref,'selected_steps':0,'selection':'unchanged_parent_control'},'unchanged parent head differs')
    pt=read_ref(selection['parent_tuning']);parent_metrics={};jobs=[]
    require(set(pt['generation'])==set(pt['metrics'])==set(inputs['tuning']),'complete parent tuning panels required')
    for panel,targets in inputs['tuning'].items():
        parent_metrics[panel]=audited_scope_metric(pt['generation'][panel],inputs['sources'][panel],targets,pt['metrics'][panel])
        jobs.append({'kind':'boundary','name':'parent-reference/'+panel,'checkpoint':parent_ref,'sources':inputs['sources'][panel],'generation':selection['parent_tuning'],'scope_panel':panel,'stage':True})
    trials=selection['trials'];require([t['name'] for t in trials]==list(ARMS),'all four matched preservation trials required')
    expected_batches=matched_batches(inputs['replay'],inputs['new_train'],inputs['training_pairs']);teacher_batches,teacher_audit=teacher_batch_audit(inputs,expected_batches);initial_states=[];audits=[];initials={};stage_maps={}
    for trial in trials:
        arm=trial['arm'];require(trial['name']==arm and trial['seed']==1730 and trial['parent']==parent_ref and trial['executed_steps']==400,'trial attribution differs')
        training=read_ref(trial['training']);manifest=training['manifest']
        require(manifest=={'arm':arm,'seed':1730,'plan':frozen['plan'],'steps':400,'replay_sha256':digest(inputs['replay']),'new_training_sha256':digest(inputs['new_train']),'training_pairs_sha256':digest(inputs['training_pairs'])},'training manifest differs')
        initial=read_ref(trial['initial_checkpoint']);verify_initialization(parent,initial,arm,manifest,inputs['tuning'],parent_ref)
        initial_states.append(initial['model_state']);initials[arm]=initial
        names=initial['trainable_parameters'];require(training['optimizer_updates']==400 and len(training['losses'])==len(training['loss_receipts'])==len(training['batch_receipts'])==400 and training['batch_receipts']==expected_batches and training['batch_receipts_sha256']==digest(expected_batches),'all400 matched12row update receipts required')
        require(set(training['trainable_parameters'])==set(names) and training['trainable_parameter_count']==initial['trainable_parameter_count'] and training['optimizer_parameter_steps']=={k:400 for k in names},'complete trainable Adam counter inventory differs')
        require(training['initial_complete_model_state_sha256']==digest(initial['model_state']) and training['initial_predictions_equal_parent'] is training['initial_optimizer_state_empty'] is True and training['optimizer_resumed'] is training['optimizer_trajectory_independently_replayed'] is False and training['trial_wall_limit_seconds']==1200 and 0<training['wall_seconds']<=1200,'initial state/fresh Adam/wall receipts differ')
        require(len(training['teacher_receipts'])==400 and training['teacher_receipts_sha256']==digest(training['teacher_receipts']) and training['teacher_state_sha256_before']==training['teacher_state_sha256_after']==digest(parent['model_state']) and training['teacher_gradients_absent'] is True,'frozen TRAIN teacher receipts/state differ')
        for step,(loss,parts,exposure,teacher_record,teacher_expected) in enumerate(zip(training['losses'],training['loss_receipts'],expected_batches,training['teacher_receipts'],teacher_batches,strict=True),1):
            require(parts['steps']==step and parts['total_loss']==loss and parts['gradient_clip_norm']==5. and type(parts['gradient_norm_before_clipping']) in (float,int) and math.isfinite(parts['gradient_norm_before_clipping']) and parts['gradient_norm_before_clipping']>=0 and parts['finite_updated_parameters'] is True,'finite update/gradient receipt differs')
            verify_objective_receipt(parts,teacher_record,teacher_expected,exposure,loss,arm)
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
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status,'independent preservation stage selection differs')
        require(next(h for h in frozen['models'] if h['name']==arm)=={k:trial[k] for k in ('name','arm','checkpoint','selected_steps','selection')},'selected/fallback head slot attribution differs')
        audits.append({'name':arm,'parent':parent_ref,'initial_checkpoint':trial['initial_checkpoint'],'training':trial['training'],'stages':stages,'selection':status,'selected_steps':steps,'checkpoint':pin,'executed_updates':400,'batch_sha256':digest(expected_batches)})
    require(all(state==initial_states[0] for state in initial_states),'architecture arms did not start from identical complete model tensors')
    primary=primary_scope_choice(audits,stage_maps)
    require(selection['primary_scope_choice']==frozen['primary_scope_choice']==primary and frozen['choice_fixed_before_fresh_reference_release'] is True,'pre-reference primary scope choice differs')
    parent_generations={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    initial_audits={arm:initial_parent_parity(initial,parent_generations,inputs['sources']) for arm,initial in initials.items()}
    return jobs,{'trials':audits,'parent_tuning':parent_metrics,'training_pairs':pair_audit,'opaque_fresh_sources':opaque,'teacher_audit':teacher_audit,'primary_scope_choice':primary,'initial_parent_parity':initial_audits,'initial_source_evaluations':sum(a['source_evaluations'] for a in initial_audits.values()),'optimizer_trajectory_replayed':False}

DOCUMENT_COUNTS={'scope_fresh':192,'prior_adapter_fresh':192,'root_condition_fresh_documents':96}
CLAUSE_PARENTS={'continuation':('facet_retention','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
    'grounding':('temporal_presence','4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea')}


def verify_fitting(inputs):
    from scripts.ops.legal_ir import run_legal_scope_adapter_experiment as old_runner
    manifest=inputs['manifest'];adapter=read_ref(manifest['inputs']['prior_adapter_corpus']);old_config=read_ref(manifest['inputs']['prior_adapter_config'])
    require(old_config['scope_corpus_manifest']==manifest['inputs']['prior_adapter_corpus'],'prior adapter configuration/corpus ancestry differs')
    expected_retention={**adapter['retention_target_references'],**old_config['additional_tuning_refs'],'prior_adapter_tuning':adapter['artifacts']['tuning_targets'],'prior_adapter_fresh':adapter['artifacts']['fresh_targets']}
    require(manifest['replay_references']==adapter['replay_references'] and inputs['replay']==[r for pin in adapter['replay_references'].values() for r in read_ref(pin)],'historical768 replay membership/order changed across preservation factors')
    require(manifest['retention_target_references']==expected_retention,'all prior tuning and exposed adapter challenge retention references required')
    artifacts=manifest['artifacts']
    require(all(artifacts[k]==adapter['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')),'preservation may not replace any384 paired training rows or pair membership')
    require(inputs['new_train']==read_ref(artifacts['new_training_targets']) and inputs['training_pairs']==read_ref(artifacts['training_pairs']) and inputs['tuning']['scope_new']==read_ref(artifacts['tuning_targets']),'fitting/tuning payload references differ')
    tuning_pairs=read_ref(artifacts['tuning_pairs']);pair_audit=verify_scope_pairs(inputs['tuning']['scope_new'],tuning_pairs,48)
    old_inputs=old_runner.read_config(manifest['inputs']['prior_adapter_config']['path'])
    require(inputs['replay']==old_inputs['replay'] and inputs['new_train']==old_inputs['new_train'] and inputs['training_pairs']==old_inputs['training_pairs'],'prior complete1152 ordered training rows and192 contrast pairs must remain identical')
    panels={digest(rows) for rows in inputs['tuning'].values()}
    require(all(digest(rows) in panels for rows in old_inputs['tuning'].values()),'prior adapter tuning panel was dropped or changed')
    require(inputs['tuning']['prior_adapter_fresh']==read_ref(adapter['artifacts']['fresh_targets']),'prior fresh adapter challenge must be explicitly admitted retention')
    fit={r['source_sha256'] for r in inputs['replay']+inputs['new_train']}
    require(len(fit)==1152 and all(not fit&{r['source_sha256'] for r in rows} for rows in inputs['sources'].values()),'fitting source leaks into evaluation')
    return {'historical_replay_rows':768,'unchanged_paired_training_rows':384,'training_pairs':192,'new_tuning_pairs':pair_audit['pairs'],'prior_tuning_panels_retained':len(old_inputs['tuning']),'previous_fresh_panels_are_admitted_retention':True,'fit_evaluation_source_overlap':0,'all_training_content_and_order_unchanged_from_prior_adapter':True}


def verify_inventory(inputs,frozen):
    require(frozen['all_training_selection_and_generation_complete'] is True and frozen['executed_optimizer_updates']==1600 and frozen['new_fresh_targets_opened'] is frozen['clause_predictions_used_for_selection'] is False and frozen['all_source_raw_token_logits_unchanged'] is frozen['no_joint_stage_search'] is True,'complete source-only fixed-factor generation required')
    require(frozen['clause_models']==inputs['config']['clause_models'] and len(frozen['clause_models'])==2,'two fixed clause models required')
    models={m['name']:m for m in frozen['clause_models']};heads={h['name']:h for h in frozen['models']}
    require(set(models)=={'parent_continuation','parent_grounding'} and set(heads)==set(frozen['files'])=={'parent',*ARMS},'fixed clause and five boundary slots required')
    for model in models.values():
        kind,wanted=CLAUSE_PARENTS[model['architecture']]
        require(model['name']=='parent_'+model['architecture'] and model['decoder_kind']==kind and model['checkpoint']['sha256']==wanted,'existing preselected clause parent changed')
        read_ref(model['checkpoint'],parse=False)
    require(set(frozen['sources'])==set(inputs['sources']) and all(read_ref(pin)==inputs['sources'][panel] for panel,pin in frozen['sources'].items()),'source-only frozen input rows differ')
    expected={m+'__scope_'+h for m in models for h in heads}
    require(len(frozen['pipelines'])==10 and {p['name'] for p in frozen['pipelines']}==set(frozen['document_files'])==expected,'all ten fixed-clause/scope pipeline slots required')
    require(set(frozen['document_sources'])==set(DOCUMENT_COUNTS) and all(frozen['document_sources'][p]==frozen['sources'][p] and len(inputs['sources'][p])==n for p,n in DOCUMENT_COUNTS.items()),'full new/exposed document panel inventory differs')
    for pipeline in frozen['pipelines']:
        model=models[pipeline['source_model_name']];head=heads[pipeline['boundary_head']]
        require(pipeline['name']==model['name']+'__scope_'+head['name'] and pipeline['boundary_checkpoint']==head['checkpoint'] and pipeline['boundary_selection']==head['selection'] and pipeline['boundary_selected_steps']==head['selected_steps'] and pipeline['clause_training_executed'] is False and all(pipeline[k]==model[k] for k in ('architecture','decoder_kind','checkpoint')) and set(frozen['document_files'][pipeline['name']])==set(DOCUMENT_COUNTS),'pipeline factor attribution or panel coverage differs')
    parent={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    for head,panels in frozen['files'].items():
        require(set(panels)==set(inputs['sources']),'selected boundary source panels missing')
        for panel,pin in panels.items():verify_frozen_token_outputs(parent[panel],read_ref(pin))
    return {'boundary_slots':5,'fixed_clause_models':2,'document_pipeline_slots':10,'fresh_source_documents':192,'fresh_supported_documents':96,'fresh_unsupported_documents':96,'selected_boundary_source_rows':10320,'selected_pipeline_documents':4800,'clause_training_updates':0}


def audit_training_diagnostics(inputs,frozen):
    require(set(frozen['training_diagnostics'])=={'parent',*[a+'_final400' for a in ARMS]},'all five preregistered full TRAIN diagnostic slots required')
    selection=read_ref(frozen['selections']);expected={'parent':inputs['config']['boundary_parent'],**{t['name']+'_final400':t['stages'][-1]['checkpoint'] for t in selection['trials']}}
    panels={'historical_replay':inputs['replay'],'new_training':inputs['new_train']};jobs=[];scores={};parent=None
    for name in ('parent',*[a+'_final400' for a in ARMS]):
        pin=frozen['training_diagnostics'][name];saved=read_ref(pin)
        require(saved['checkpoint']==expected[name] and saved['training_fit_used_for_selection'] is saved['heldout_accuracy'] is False and set(saved['generation'])==set(saved['metrics'])==set(panels),'TRAIN diagnostic lineage/panels/selection attribution differs')
        if parent is None:parent=saved['generation']
        scores[name]={}
        for panel,targets in panels.items():
            sources=clauses.source_rows(targets);verify_frozen_token_outputs(parent[panel],saved['generation'][panel])
            scores[name][panel]=audited_scope_metric(saved['generation'][panel],sources,targets,saved['metrics'][panel])
            jobs.append({'kind':'boundary','name':'TRAIN/'+name+'/'+panel,'checkpoint':expected[name],'sources':sources,'generation':pin,'scope_panel':panel,'training_diagnostic':True})
    return jobs,{'saved_source_rows':5760,'models':scores,'training_fit_used_for_selection':False,'heldout_accuracy':False}


_WORKER_GUARD=None

def init_worker(sealed):
    global _WORKER_GUARD
    _WORKER_GUARD=SealedReadGuard(sealed);sys.addaudithook(_WORKER_GUARD.event)


def replay_group(group):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
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
    manifest=inputs['manifest'];adapter=read_ref(manifest['inputs']['prior_adapter_corpus']);adapter_config=read_ref(manifest['inputs']['prior_adapter_config'])
    scope=read_ref(adapter['inputs']['prior_scope_corpus']);cm=read_ref(adapter['inputs']['prior_condition_corpus'])
    refs={**scope['replay_references'],'prior_scope':scope['artifacts']['new_training_targets'],**scope['retention_target_references'],
        'prior_scope_tuning':scope['artifacts']['tuning_targets'],'prior_scope_exposed_fresh':scope['artifacts']['fresh_targets'],
        'condition_document_tuning':cm['artifacts']['document_tuning_targets'],'condition_exposed_documents':cm['artifacts']['document_challenge_targets'],
        **{name:adapter['artifacts'][key] for name,key in (('prior_adapter_train','new_training_targets'),('prior_adapter_tuning','tuning_targets'),('prior_adapter_fresh','fresh_targets'))}}
    documents={name:{'reference':pin,'rows':read_ref(pin)} for name,pin in refs.items()}
    _,_,excluded,_,source_refs,real_count=condition.historical_inputs(cm['inputs']['prior_corpus']['path'])
    for key in ('new_tuning','challenge_targets','document_tuning_targets','document_challenge_targets'):excluded.update(r['source_text'] for r in read_ref(cm['artifacts'][key]))
    for item in documents.values():excluded.update(r['source_text'] for r in item['rows'])
    return {'historical_documents':documents,'prior_annotation_ledgers':{name:{'reference':m['artifacts']['annotation_ledger'],'ledger':read_ref(m['artifacts']['annotation_ledger'])} for name,m in (('prior_scope',scope),('prior_adapter',adapter))},
        'historical_manifests':{'prior_scope':scope,'prior_condition':cm,'prior_adapter':adapter,'prior_adapter_config':adapter_config},
        'prior_training_pairs':{'reference':adapter['artifacts']['training_pairs'],'rows':read_ref(adapter['artifacts']['training_pairs'])},
        'historical_source_inventory':{'source_texts':sorted(excluded),'prior_source_references':source_refs,'condition_single_references':{k:cm['artifacts'][k] for k in ('new_tuning','challenge_targets')},'real_exposed_views':real_count}}



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
    from scripts.ops.legal_ir import run_legal_scope_preservation_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_scope_preservation_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_scope_preservation_annotations as annotations
    from ipfs_datasets_py.logic.autoformal import legal_clause_scope_preservation as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU qualification workers required')
    folder,output=Path(args.run_directory).resolve(),Path(args.output).resolve()
    frozen_ref=ref(folder/'generation-frozen.json');frozen=read_ref(frozen_ref)
    require(frozen['schema']==runner.SCHEMA,'declared completed scope preservation generation required')
    plan=read_ref(frozen['plan']);config=read_ref(plan['config']);manifest=read_ref(config['scope_corpus_manifest'])
    evidence_refs={key:manifest['artifacts'][key] for key in ('fresh_targets','fresh_pairs','annotation_ledger','exposure_audit')}
    sealed=list(evidence_refs.values());guard=SealedReadGuard(sealed);sys.addaudithook(guard.event)
    inputs=runner.read_config(plan['config']['path']);inventory=verify_inventory(inputs,frozen)
    pins=dict(plan['producer_pins']);require(all(sha(path)==wanted for path,wanted in pins.items()),'original fitting producer pins changed before qualification')
    for module in (sys.modules[__name__],prior,runner,corpus,annotations,annotations.adapter,annotations.adapter.previous,runtime,runtime.adapter,boundary,clauses,retained,retained.prior,retained.calendar,retained.calendar_summary,retained.compose,boundary_qualification,previous,gate):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    require(all(sha(path)==wanted for path,wanted in pins.items()),'frozen producer source drift')
    output.mkdir(parents=True,exist_ok=False)
    qualification_plan=write(output/'qualification-plan.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'producer_pins':pins,'sealed_references':evidence_refs,'fresh_document_build_slots':10,'native_build_panel':'scope_fresh','new_reference_files_opened':False,'old_fresh_reference_panels_admitted_as_retention':True,'clause_training_executed':False})
    fitting=verify_fitting(inputs);jobs,training=verify_training(inputs,frozen)
    training_jobs,diagnostics=audit_training_diagnostics(inputs,frozen);jobs+=training_jobs
    require(training['initial_source_evaluations']==8256,'all four initial checkpoints must be checked on all2064source rows')
    training_ref=write(output/'training-and-selection-audit.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'selections':frozen['selections'],'fitting':fitting,**training,'full_training_diagnostics':diagnostics,'executed_scope_updates':1600,'clause_training_updates':0,'source_semantics_verified':False})
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
    require(sum(len(j['sources']) for j in jobs)==45216 and sum(len(j['sources']) for j in jobs if j.get('training_diagnostic'))==5760,'complete saved output/diagnostic replay denominator differs')
    groups=prior.group_replay_jobs(jobs);replays=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn'),initializer=init_worker,initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group,g) for g in groups]):replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==45216,'full saved numerical replay incomplete')
    for a in frozen['models']:
        for b in frozen['models']:
            if a['checkpoint']==b['checkpoint']:
                require(boundary_outputs[a['name']]==boundary_outputs[b['name']],'same-checkpoint head slots changed outputs')
                require(all(documents[m['name']+'__scope_'+a['name']]==documents[m['name']+'__scope_'+b['name']] for m in frozen['clause_models']),'same-checkpoint pipeline slots changed outputs')
    replay_ref=write(output/'replay-frozen.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'panels':sorted(replays,key=lambda r:r['name']),'saved_output_rows':45216,'boundary_rows':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_rows':sum(r['rows'] for r in replays if r['kind']=='document'),'training_diagnostic_rows':5760,'additional_initial_parity_rows':8256,'additional_teacher_source_evaluations':4800,'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,'new_reference_files_opened':False,'old_fresh_retention_references_admitted':True})
    selections={}
    for model in frozen['pipelines']:
        name=model['name'];selected=document_selection(documents[name]['scope_fresh']['rows'],inputs['sources']['scope_fresh'],toolchain=args.toolchain)
        require(selected['source_count']==len(selected['rows'])+len(selected['excluded'])==192,'native source-only selection dropped documents')
        selections[name]=selected
    selection_ref=write(output/'build-selection-frozen.json',{'schema':SCHEMA,'document':selections,'replay':replay_ref,'document_source_slots':1920,'document_panel':'scope_fresh','canonical_references_used_for_selection':False,'new_reference_files_opened':False,'clause_training_executed':False})
    builds={'document':{}}
    for name,selected in selections.items():
        builds['document'][name]=retained.build_batches(selected['rows'],output/'builds'/name,args)
        print({'phase':'built','model':name,'supported_for_lowering':len(selected['rows'])},flush=True)
    builds_ref=write(output/'builds-frozen.json',{'schema':SCHEMA,**builds,'selections':selection_ref,'replay':replay_ref,'new_reference_files_opened':False,'reference_derived_layout_evidence_opened':False,'old_fresh_retention_references_admitted':True})
    read_ref(frozen['selections'],parse=False);require(not guard.events,'sealed fresh reference access attempted before build freeze')
    guard.released=True;print({'phase':'references_released_after_build_freeze','builds':builds_ref},flush=True)
    evidence={key:read_ref(pin) for key,pin in evidence_refs.items()};targets={**inputs['tuning'],'scope_fresh':evidence['fresh_targets']}
    require(set(targets)==set(inputs['sources']) and clauses.source_rows(targets['scope_fresh'])==inputs['sources']['scope_fresh'],'complete fresh/admitted reference binding differs')
    audit_inputs={**inputs,'replay':{k:read_ref(pin) for k,pin in manifest['replay_references'].items()},'tuning_pairs':read_ref(manifest['artifacts']['tuning_pairs'])}
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
    result={'schema':SCHEMA,'qualification_plan':qualification_plan,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'replay':replay_ref,'builds':builds_ref,'details':details_ref,'authored_exposure_audit':exposure_ref,'phase_open_audit':opens_ref,'posthoc_evidence':evidence_refs,'models':frozen['models'],'clause_models':frozen['clause_models'],'pipelines':pipeline_reports,'boundary_metrics':{h:{p:v['metrics'] for p,v in panels.items()} for h,panels in boundary_metrics.items()},'producer_pins':pins,'primary_scope_choice':frozen['primary_scope_choice'],'parent_fallbacks':[m['name'] for m in frozen['models'] if m['selection'].startswith('parent_fallback')],'executed_optimizer_updates':1600,'clause_optimizer_updates':0,'inventory':inventory,'boundary_source_documents_replayed':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='document'),'clause_occurrences_replayed':sum(r.get('clause_occurrences_replayed',0) for r in replays),'additional_initial_parity_source_evaluations':8256,'additional_teacher_source_evaluations':4800,'actual_lake_build_invocations':sum(b['backend_executed'] for rows in builds['document'].values() for b in rows),'build_attempts':sum(len(rows) for rows in builds['document'].values()),'native_fresh_document_build_slots':10,'document_build_panel':'scope_fresh','fresh_reference_files_opened_after_replay_and_build_freezes':True,'reference_derived_novelty_evidence_opened_after_build_freeze':True,'test_results_used_for_selection_or_gate_revision':False,'scope':'One fixed-seed2x2 readout-freezing/correct-parent-distillation comparison with identical400-update source schedules. Scope-only readouts train on immutable token representations; selected policies are compared with the unchanged parent and two fixed clause decoders. Old fresh panels are now exposed retention. Authored flat-scope reference exactness and native compilation do not establish statutory semantic fidelity or supported nested-logic translation.',**FALSE}
    write(output/'summary.json',result);print({'complete':str(output/'summary.json'),'primary_scope_choice':result['primary_scope_choice'],'fresh_scope':{k:v['scope_fresh'] for k,v in result['boundary_metrics'].items()}},flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--lake-executable',required=True);parser.add_argument('--toolchain',default='leanprover/lean4:v4.34.1');parser.add_argument('--workers',type=int,default=3)
    run(parser.parse_args())
