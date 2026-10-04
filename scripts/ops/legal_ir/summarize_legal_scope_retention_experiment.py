#!/usr/bin/env python3
"""Independent qualification of condition rehearsal and learned scope retention.

Clause and boundary stages are selected independently. Only fixed selected or
explicit fallback slots are crossed; compilation is not source-semantic proof.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import math
import multiprocessing
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import summarize_legal_temporal_presence_experiment as prior
require,digest,read_ref,ref,write,sha=(getattr(prior,k) for k in ('require','digest','read_ref','ref','write','sha'))
retained,previous,clauses,boundary=prior.retained,prior.previous,prior.clauses,prior.boundary
boundary_qualification,routing_audit=prior.boundary_qualification,prior.routing_audit
SealedReadGuard=prior.SealedReadGuard
single_error_metrics=prior.single_error_metrics
verify_pairs=prior.verify_pairs
verify_annotation=prior.verify_annotation
verify_annotation_pairs=prior.verify_annotation_pairs
validate_fresh_coordinates=prior.validate_fresh_coordinates
validate_occurrence_coordinates=prior.validate_occurrence_coordinates
document_clauses=prior.document_clauses
role_layout=prior.role_layout
group_replay_jobs=prior.group_replay_jobs
replay_with_decoder=prior.replay_with_decoder
TeacherEligibilityCache=prior.TeacherEligibilityCache
teacher_eligibility=prior.teacher_eligibility
FALSE=prior.FALSE
SCHEMA='legal-scope-retention-independent-qualification/v1'
ARCHITECTURES=('continuation','grounding')
SEEDS=(1730,)
CLAUSE_STAGES=(100,200)
SCOPE_STAGES=(100,200,400)


def clause_strata(generation,sources,targets):
    """Accepted facet equality and full-rule equality retain all abstentions."""
    references=previous.reference_rows(targets,sources)
    require(len(generation['rows'])==len(sources),'clause metric dropped source rows')
    counts=Counter();rows=[]
    for source,prediction,target in zip(sources,generation['rows'],references,strict=True):
        require(prediction['source_sha256']==source['source_sha256'] and prediction['status'] in ('decoded','abstained'),'clause source/status differs')
        canonical=target['canonical_ir'];require(len(canonical['rules'])==1,'single reference rule required')
        gold=canonical['rules'][0];accepted=prediction['status']=='decoded'
        if accepted:
            require(len(prediction['canonical_ir']['rules'])==1,'single decoded rule required')
            actual=prediction['canonical_ir']['rules'][0]
        else:actual=None
        exact=bool(accepted and prediction['canonical_ir']==canonical)
        modality=bool(accepted and actual['modality']==gold['modality'])
        row={'id':source['id'],'decoded':accepted,'exact':exact,'modality_exact':modality}
        counts['count']+=1;counts['decoded']+=accepted;counts['exact']+=exact;counts['modality_exact']+=modality
        counts[gold['modality']+'_count']+=1;counts[gold['modality']+'_rule_exact']+=exact
        for field,prefix in (('conditions','C'),('temporal','T')):
            label=prefix+('present' if gold[field] else 'absent')
            same=bool(accepted and actual[field]==gold[field])
            counts[label+'_count']+=1;counts[label+'_facet_exact']+=same;counts[label+'_rule_exact']+=exact
            row[label+'_facet_exact']=same;row[label+'_rule_exact']=exact
        rows.append(row)
    wanted=previous.score(generation['rows'],sources,references)
    require(counts['exact']==wanted['exact'] and counts['count']==wanted['count'],'independent full-rule score differs')
    keys=('count','decoded','exact','modality_exact',*(m+'_'+v for m in 'OPF' for v in ('count','rule_exact')),*(p+'_'+s for p in ('Cpresent','Cabsent','Tpresent','Tabsent') for s in ('count','facet_exact','rule_exact')))
    return {**{key:counts[key] for key in keys},'rows':rows,'abstentions_count_as_facet_and_rule_failures':True}


def verify_scope_logits(generation):
    """Check raw classifier decisions independently of all later rejection guards."""
    for row in generation['rows']:
        logits=row['scope_logits'];require(len(logits)==2 and all(type(v) in (float,int) and math.isfinite(v) for v in logits),'two finite raw scope logits required')
        raw=logits[1]>logits[0]
        require(type(row['raw_learned_scope_supported']) is bool and row['raw_learned_scope_supported'] is raw,'scope argmax or tie policy differs')
        peak=max(logits);prob=math.exp(logits[1]-peak)/sum(math.exp(v-peak) for v in logits)
        require(type(row['scope_supported_probability']) in (float,int) and math.isclose(row['scope_supported_probability'],prob,rel_tol=1e-6,abs_tol=1e-7),'scope probability/logits differ')
    return len(generation['rows'])


def scope_metrics(generation,sources,targets):
    verify_scope_logits(generation)
    scored=boundary_qualification.score_boundaries(generation,sources,targets)
    legacy=scored['legacy_counts']
    counts={'count':scored['documents'],'supported':scored['supported'],'unsupported':scored['unsupported'],
        'raw_supported_correct':scored['supported']-scored['supported_raw_scope_rejected'],
        'raw_unsupported_accepted':scored['unsupported_raw_scope_false_positive'],
        'supported_exact':scored['supported_delivered_interval_exact'],
        'unsupported_accepted':scored['unsupported_accepted_plan'],
        'raw_boundary_exact':scored['supported_raw_interval_exact']}
    require(counts['raw_supported_correct']==legacy.get('raw_supported_scope_correct',0)
        and counts['raw_unsupported_accepted']==counts['unsupported']-legacy.get('raw_unsupported_scope_correct',0),'independent scope metric contract differs')
    return {'metrics':counts,'details':scored}


def verify_frozen_boundary_tensors(parent,child,*,require_scope_change=True):
    for field in ('schema','profile','implementation_sha256','config','optimizer_resumption_supported'):
        require(child[field]==parent[field],'scope continuation changed boundary contract: '+field)
    a,b=parent['model_state'],child['model_state']
    require(set(a)==set(b) and {'scope.weight','scope.bias'}<=set(a),'complete boundary tensor inventory required')
    scope={'scope.weight','scope.bias'}
    require(all(a[key]==b[key] for key in a if key not in scope),'scope fitting changed frozen embedding/encoder/token-boundary weights')
    require(len(b['scope.weight'])==2 and all(len(row)==64 for row in b['scope.weight']) and len(b['scope.bias'])==2,'exact130 trainable scope parameters required')
    values=[v for row in b['scope.weight'] for v in row]+b['scope.bias']
    require(all(type(v) in (int,float) and math.isfinite(v) for v in values),'finite scope weights required')
    changed=[key for key in sorted(scope) if a[key]!=b[key]]
    require(not require_scope_change or changed,'scope stage did not change any trainable tensor')
    return {'trainable_parameters':130,'changed_scope_tensors':changed,'non_scope_tensors_bit_identical':True}


def verify_frozen_token_outputs(parent,child):
    require(len(parent['rows'])==len(child['rows']),'scope continuation dropped documents')
    keys=('candidate_id','source_sha256','boundary_logits','boundary_token_indices','predicted_rule_count')
    for a,b in zip(parent['rows'],child['rows'],strict=True):
        require(all(a[key]==b[key] for key in keys),'scope-only fitting changed raw token boundary outputs')
    return len(child['rows'])


def condition_row_terms(torch,output,record,index):
    """Independent gold-index log probabilities; no runtime loss helper used."""
    present=bool(record['labels']['presence'][3])
    presence=-output['presence'][index,1].log_softmax(0)[int(present)]
    endpoints=output['modality'][index].sum()*0
    if present:
        count=len(record['tokens']);start,end=record['labels']['spans'][3]
        require(type(start) is int and type(end) is int and 0<=start<=end<count,'condition gold endpoints escape source tokens')
        endpoints=sum(-output[key][index,3,:count].log_softmax(0)[gold] for key,gold in (('start',start),('end',end)))/2
    return present,presence,endpoints


def condition_auxiliary_oracle(torch,output,records):
    require(len(records)==4,'four rehearsal rows required')
    groups={False:[],True:[]};endpoints=[]
    for i,record in enumerate(records):
        present,presence,endpoint=condition_row_terms(torch,output,record,i)
        groups[present].append(presence)
        if present:endpoints.append(endpoint)
    require(len(groups[False])==len(groups[True])==2,'balanced2+2 condition supervision required')
    neg,pos=(torch.stack(groups[key]).mean() for key in (False,True))
    balanced=(neg+pos)/2;endpoint=torch.stack(endpoints).mean();total=(balanced+endpoint)/2
    return total,{'condition_positive_ce':pos,'condition_negative_ce':neg,'condition_balanced_presence_ce':balanced,
        'condition_present_endpoint_ce':endpoint,'condition_rehearsal_ce':total}


def expected_clause_batch(seed,step,pools,hard_ids):
    require(type(step) is int and 1<=step<=200,'declared1..200 clause update required')
    require(set(hard_ids)=={'positive','negative'} and all(len(ids)==len(set(ids))==64 for ids in hard_ids.values())
        and not set(hard_ids['positive'])&set(hard_ids['negative']),'two disjoint64-row hard pools required')
    main=prior.expected_batch(seed,step,pools);auxiliary=[]
    for label in ('positive','negative'):
        indices=[]
        for absolute in range(2*(step-1),2*step):
            epoch,offset=divmod(absolute,64);order=list(range(64))
            random.Random(f'condition-rehearsal/v1:{seed}:{label}:{epoch}').shuffle(order)
            indices.append(order[offset])
        main['indices_by_pool']['rehearsal_'+label]=indices
        auxiliary.extend(hard_ids[label][i] for i in indices)
    return {**main,'rehearsal_ids':auxiliary}


def audit_mining_and_teacher(parent,parent_kind,inputs,mining):
    """Reuse all4080 independent parent forwards for mining and teacher audit."""
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    rows=inputs['training'];records,_=mixed._splits(rows,[])
    require(len(rows)==len(records)==4080,'all4080 admitted training rows required for hard mining')
    model=mixed._model(torch,parent['model_config'])
    model.load_state_dict({key:torch.tensor(parent['model_state'][key],dtype=value.dtype) for key,value in model.state_dict().items()},strict=True)
    model.eval();model.requires_grad_(False);before=mixed._state_digest(model)
    cache=TeacherEligibilityCache();cache.model=model;cache.records={row['id']:row for row in records};cache.batch_counts={}
    scores=[]
    with torch.no_grad():
        for offset in range(0,len(records),48):
            batch=records[offset:offset+48];output=model(*mixed.span._batch(torch,batch))
            counts=teacher_eligibility(output,batch)
            for i,(record,source,eligibility) in enumerate(zip(batch,rows[offset:offset+48],counts,strict=True)):
                present,presence,endpoints=condition_row_terms(torch,output,record,i)
                require(present is bool(source['canonical_ir']['rules'][0]['conditions']),'mining condition label differs from exact admitted canonical row')
                a,b=float(presence),float(endpoints)
                scores.append({'id':record['id'],'source_sha256':boundary.text_sha(source['source_text']),
                    'condition_present':present,'condition_presence_ce':a,'condition_endpoint_ce':b,'condition_loss_sum':a+b})
                cache[record['id']]=eligibility
    require(mixed._state_digest(model)==before and all(p.grad is None for p in model.parameters()),'independent frozen mining teacher changed')
    verify_mining_manifest(parent,parent_kind,rows,mining,scores)
    return cache,{'parent_kind':parent_kind,'parent_checkpoint_sha256':digest(parent),'training_rows':4080,
        'source_evaluations':4080,'mining_batch_size':48,'selected_ids':mining['selected_ids'],
        'all_scores_recomputed':True,'teacher_eligibility_reuses_same_parent_forwards':True,
        'no_tuning_or_test_labels':True,'independent_scores_sha256':digest(scores)}


def verify_mining_manifest(parent,parent_kind,rows,mining,scores):
    fields={'schema','parent_kind','parent_checkpoint_sha256','training_manifest_sha256','mining_batch_size','score_rows',
        'selected_ids','selected_count_per_class','ranking','training_labels_only','tuning_or_test_used','model_state_unchanged'}
    require(set(mining)==fields and mining['schema']=='training-only-condition-hard-mining/v1'
        and mining['parent_kind']==parent_kind and mining['parent_checkpoint_sha256']==digest(parent)
        and mining['training_manifest_sha256']==digest(rows) and mining['mining_batch_size']==48
        and mining['selected_count_per_class']==64 and mining['training_labels_only'] is mining['model_state_unchanged'] is True
        and mining['tuning_or_test_used'] is False and mining['ranking']=='descending_presence_plus_present_mean_endpoint_CE_then_ascending_id/v1',
        'training-only exact-parent mining provenance differs')
    require(len(scores)==len(mining['score_rows'])==len(rows) and len({s['id'] for s in scores})==len(scores),'complete unique mining inventory required')
    for actual,saved,source in zip(scores,mining['score_rows'],rows,strict=True):
        require(set(saved)==set(actual) and saved['id']==actual['id']==source['id']
            and saved['source_sha256']==actual['source_sha256']==boundary.text_sha(source['source_text'])
            and type(saved['condition_present']) is bool and saved['condition_present'] is actual['condition_present']
            and actual['condition_present'] is bool(source['canonical_ir']['rules'][0]['conditions']), 'mined source or class label differs')
        for key in ('condition_presence_ce','condition_endpoint_ce','condition_loss_sum'):
            require(type(saved[key]) in (int,float) and math.isfinite(saved[key]) and saved[key]>=0
                and math.isclose(saved[key],actual[key],rel_tol=2e-6,abs_tol=2e-6),'independent hard-condition loss differs')
        require(saved['condition_loss_sum']==saved['condition_presence_ce']+saved['condition_endpoint_ce']
            and (saved['condition_present'] or saved['condition_endpoint_ce']==0),'hard-condition score arithmetic differs')
    selected=lambda values:{label:[s['id'] for s in sorted((s for s in values if s['condition_present'] is present),
        key=lambda s:(-s['condition_loss_sum'],s['id']))[:64]] for present,label in ((True,'positive'),(False,'negative'))}
    require(mining['selected_ids']==selected(scores)==selected(mining['score_rows'])
        and all(len(v)==64 for v in mining['selected_ids'].values()),'independent hard-pool ranking differs')
    return True


def retention_metrics(generation,sources,targets):
    flat=clause_strata(generation,sources,targets)
    return {'count':flat['count'],'fullrule_exact':flat['exact'],
        'modality_fullrule':{m:{'count':flat[m+'_count'],'exact':flat[m+'_rule_exact']} for m in 'OPF'},
        **{field:{label:{'count':flat[prefix+label+'_count'],'exact':flat[prefix+label+'_'+suffix]}
            for label in ('present','absent')} for field,prefix,suffix in (
                ('condition_facet','C','facet_exact'),('temporal_facet','T','facet_exact'),
                ('condition_fullrule','C','rule_exact'),('temporal_fullrule','T','rule_exact'))}}


def verify_scope_pairs(rows,pairs,expected):
    """Reconstruct outer attachments while preserving exact repeated local bodies."""
    lookup={r['candidate_id']:r for r in rows};used=set();cases=set()
    require(len(rows)==len(lookup)==2*expected and len(pairs)==expected,'complete scope contrast inventory required')
    keys={'pair_id','case_group','independent_id','nested_id','local_clause_body_sha256'}
    for pair in pairs:
        require(set(pair)==keys and pair['case_group'] not in cases,'closed unique scope contrast case required')
        a,b=pair['independent_id'],pair['nested_id']
        require(a!=b and a in lookup and b in lookup and not {a,b}&used,'duplicate or missing scope pair identity')
        positive,negative=lookup[a],lookup[b]
        require(positive['supported'] is True and negative['supported'] is False
            and negative['clauses']==[] and negative['unsupported_reason']=='nested_normative_exception', 'scope contrast cannot invent flat nested targets')
        bodies=[];offset=0
        for clause in positive['clauses']:
            left,right=clause['char_start'],clause['char_end']
            require(type(left) is int and type(right) is int and offset<=left<right<=len(positive['source_text'])
                and positive['source_text'][right-1] in '.;', 'invalid independent clause declaration')
            bodies.append(positive['source_text'][left:right-1]);offset=right
        require(len(bodies) in (2,3) and [boundary.text_sha(text) for text in bodies]==pair['local_clause_body_sha256'], 'local body hash or occurrence inventory differs')
        first_end=len(bodies[0]);second_start=None
        for cue in (' unless ',' except when ',' except where '):
            if negative['source_text'].startswith(bodies[0]+cue+bodies[1]+'.'):
                require(second_start is None,'ambiguous declared outer attachment');second_start=first_end+len(cue)
        require(second_start is not None,'nested source changed local meaning or attachment')
        tail=negative['source_text'][second_start+len(bodies[1])+1:]
        expected_tail=''
        for index in range(2,len(bodies)):
            previous_end=positive['clauses'][index-1]['char_end'];start=positive['clauses'][index]['char_start']
            expected_tail+=positive['source_text'][previous_end:start]+bodies[index]+'.'
        require(tail==expected_tail,'nested source dropped or changed a repeated/third local occurrence')
        for row in (positive,negative):
            require(row['source_sha256']==boundary.text_sha(row['source_text']) and not boundary.UNSUPPORTED.search(row['source_text']),
                'scope source hash differs or contrasts are solved by frozen surface guard')
        used.update((a,b));cases.add(pair['case_group'])
    require(used==set(lookup),'scope pairs dropped sources')
    return {'documents':2*expected,'pairs':expected,'cases':sorted(cases),'same_local_bodies_with_different_scope_labels':True}


def expected_scope_batches(replay,new_rows,pairs,arm,steps=400):
    require(arm in ('control','target') and type(steps) is int and 1<=steps<=400,'bounded scope training schedule required')
    def stream(values,seed):
        require(values,'nonempty scope sampler pool required');rng=random.Random(seed)
        while True:
            order=list(range(len(values)));rng.shuffle(order)
            for index in order:yield values[index]
    by_id={r['candidate_id']:r for r in new_rows}
    common=stream(replay,1730);positive=stream([r for r in replay if r['supported']],1731)
    negative=stream([r for r in replay if not r['supported']],1732);paired=stream(pairs,1733)
    receipts=[]
    for step in range(1,steps+1):
        left=[next(common) for _ in range(6)];selected=[]
        if arm=='control':right=[next(positive) for _ in range(3)]+[next(negative) for _ in range(3)]
        else:
            selected=[next(paired) for _ in range(3)]
            right=[by_id[p[key]] for p in selected for key in ('independent_id','nested_id')]
        require(sum(row['supported'] for row in right)==3,'three extra positives and three extra guards required')
        receipts.append({'steps':step,'common_replay_ids':[r['candidate_id'] for r in left],
            'extra_ids':[r['candidate_id'] for r in right],'pair_ids':[p['pair_id'] for p in selected],
            'supported_count':sum(r['supported'] for r in left+right),'unsupported_count':sum(not r['supported'] for r in left+right)})
    return receipts


def scope_choice(stages,parent_metrics):
    fields={'count','supported','unsupported','raw_supported_correct','raw_unsupported_accepted','supported_exact','unsupported_accepted','raw_boundary_exact'}
    require([s.get('steps') for s in stages]==list(SCOPE_STAGES) and 'scope_new' in parent_metrics,'complete three-stage scope inventory required')
    for metrics in [parent_metrics,*[s['metrics'] for s in stages]]:
        require(set(metrics)==set(parent_metrics),'scope selection dropped a declared retention panel')
        for panel,row in metrics.items():
            require(set(row)==fields and all(type(v) is int and v>=0 for v in row.values())
                and row['count']==row['supported']+row['unsupported']
                and all(row[key]<=row['supported'] for key in ('raw_supported_correct','supported_exact','raw_boundary_exact'))
                and all(row[key]<=row['unsupported'] for key in ('raw_unsupported_accepted','unsupported_accepted')),
                'bounded complete raw/final scope metric contract required')
            require(all(row[key]==parent_metrics[panel][key] for key in ('count','supported','unsupported')),'scope gate denominator differs')
    eligible=[]
    for stage in stages:
        require(set(stage)=={'steps','metrics','raw_token_logits_unchanged'} and type(stage['raw_token_logits_unchanged']) is bool,'closed scope tuning-only stage required')
        if stage['raw_token_logits_unchanged'] and all(
            row['raw_supported_correct']>=parent_metrics[panel]['raw_supported_correct']
            and row['supported_exact']>=parent_metrics[panel]['supported_exact']
            and row['raw_unsupported_accepted']==row['unsupported_accepted']==0 for panel,row in stage['metrics'].items()):eligible.append(stage)
    return max(eligible,key=lambda s:(s['metrics']['scope_new']['raw_supported_correct'],s['metrics']['scope_new']['supported_exact'],
        sum(row['supported_exact'] for panel,row in s['metrics'].items() if panel!='scope_new'),-s['steps'])) if eligible else None


def audited_scope_metric(generation,sources,targets,saved):
    independent=scope_metrics(generation,sources,targets)
    expected=clauses.evaluate(generation,targets)
    expected['raw_unsupported_accepted']=expected.get('unsupported_documents',0)-expected.get('raw_unsupported_scope_correct',0)
    expected['raw_supported_rejected']=expected.get('supported_documents',0)-expected.get('raw_supported_scope_correct',0)
    require(saved==expected,'saved complete scope metric payload differs')
    for key,value in independent['details']['legacy_counts'].items():
        require(saved.get(key,0)==value,'independent raw/final boundary count differs: '+key)
    return independent['metrics']


def verify_scope_training(inputs,frozen):
    plan=read_ref(frozen['plan']);selection=read_ref(frozen['selections']);parent=inputs['parent']
    require(frozen['all_training_selection_and_generation_complete'] is True and frozen['executed_optimizer_updates']==800
        and frozen['new_fresh_targets_opened'] is frozen['clause_predictions_used_for_selection'] is False,'complete independent scope generation freeze required')
    require(plan['arms']==['control','target'] and plan['seed']==1730 and plan['stages']==list(SCOPE_STAGES)
        and plan['steps_per_arm']==400 and plan['trainable_parameters']==['scope.bias','scope.weight']
        and plan['trainable_parameter_count']==130 and plan['learning_rate']==.004
        and plan['scope_class_weights']==[3.,1.] and plan['gradient_clip_norm']==5.
        and plan['trial_wall_limit_seconds']==900 and plan['optimizer']=='fresh_Adam'
        and plan['common_replay_rows']==6 and plan['clause_predictions_used_for_selection'] is False
        and plan['scope_threshold_and_surface_policy_unchanged'] is True
        and plan['new_fresh_targets_opened'] is False,'frozen scope-only training protocol differs')
    require(len(inputs['replay'])==576 and len(inputs['new_train'])==192 and len(inputs['tuning'])==13
        and sum(len(rows) for rows in inputs['tuning'].values())==1200 and len(inputs['sources'])==15
        and sum(len(rows) for rows in inputs['sources'].values())==1488,'complete scope source/tuning inventories required')
    require(plan['tuning_counts']=={p:len(rows) for p,rows in inputs['tuning'].items()}
        and plan['source_counts']=={p:len(rows) for p,rows in inputs['sources'].items()}
        and plan['training_source_inventory_sha256']==digest(inputs['replay']+inputs['new_train']),'scope inventory/manifest commitment differs')
    pair_audit=verify_scope_pairs(inputs['new_train'],inputs['training_pairs'],96)
    require(selection['executed_optimizer_updates']==800 and selection['all_training_and_selection_complete'] is True
        and selection['new_fresh_targets_opened'] is selection['clause_predictions_used_for_selection'] is False
        and selection['plan']==frozen['plan'],'scope selection freeze differs')
    models=frozen['models'];require(read_ref(frozen['heads'])==models and [m['name'] for m in models]==['parent','control','target']
        and set(frozen['files'])=={'parent','control','target'} and set(frozen['sources'])==set(inputs['sources']),'complete three scope policy slots required')
    by_name={m['name']:m for m in models};parent_ref=inputs['config']['boundary_parent']
    require(by_name['parent']=={'name':'parent','arm':'parent','checkpoint':parent_ref,'selected_steps':0,'selection':'unchanged_parent_control'},'unchanged expanded boundary parent differs')
    require(all(read_ref(frozen['sources'][panel])==rows for panel,rows in inputs['sources'].items()),'scope frozen source input differs')
    saved_parent=read_ref(selection['parent_tuning']);require(set(saved_parent['generation'])==set(saved_parent['metrics'])==set(inputs['tuning']),'parent scope tuning panel inventory differs')
    jobs=[];parent_metrics={}
    for panel,targets in inputs['tuning'].items():
        parent_metrics[panel]=audited_scope_metric(saved_parent['generation'][panel],inputs['sources'][panel],targets,saved_parent['metrics'][panel])
        require(saved_parent['generation'][panel]==read_ref(frozen['files']['parent'][panel]),'parent tuning and selected scope outputs differ')
        jobs.append({'kind':'boundary','name':'scope-parent-reference/'+panel,'checkpoint':parent_ref,'sources':inputs['sources'][panel],
            'generation':selection['parent_tuning'],'scope_panel':panel,'stage':True})
    trials=selection['trials'];require([t['name'] for t in trials]==['control','target'],'both matched scope training arms required')
    audits=[];traces={}
    non_scope={k:v for k,v in parent['model_state'].items() if not k.startswith('scope.')}
    for trial in trials:
        arm=trial['arm'];report=read_ref(trial['training']);manifest=report['manifest']
        require(trial['name']==arm and trial['seed']==1730 and trial['parent']==parent_ref and trial['executed_steps']==400
            and report['optimizer_updates']==len(report['losses'])==len(report['batch_receipts'])==400,'complete400-update scope trial required')
        require(report['trainable_parameters']==['scope.bias','scope.weight']
            and report['initial_complete_model_state_sha256']==digest(parent['model_state'])
            and report['initial_optimizer_state_empty'] is True and report['optimizer_resumed'] is False
            and report['trial_wall_limit_seconds']==900 and 0<report['wall_seconds']<900
            and report['non_scope_state_sha256_before']==report['non_scope_state_sha256_after']==digest(non_scope)
            and report['optimizer_trajectory_independently_replayed'] is False,'scope initialization, frozen weights, fresh Adam or wall budget differs')
        expected_manifest={'arm':arm,'seed':1730,'plan':frozen['plan'],'steps':400,'only_scope_parameters':['scope.bias','scope.weight'],
            'replay_sha256':digest(inputs['replay']),'new_training_sha256':digest(inputs['new_train']) if arm=='target' else None}
        require(manifest==expected_manifest and all(type(v) in (float,int) and math.isfinite(v) and v>=0 for v in report['losses']), 'scope training manifest or finite loss receipt differs')
        expected=expected_scope_batches(inputs['replay'],inputs['new_train'],inputs['training_pairs'],arm)
        require(report['batch_receipts']==expected,'independent scope training schedule differs');traces[arm]=expected
        require([s['steps'] for s in trial['stages']]==list(SCOPE_STAGES),'all scope stages required')
        stages=[];stage_audits=[]
        for stage in trial['stages']:
            checkpoint=read_ref(stage['checkpoint']);weights=verify_frozen_boundary_tensors(parent,checkpoint)
            require(checkpoint['optimizer_steps']==parent['optimizer_steps']+stage['steps']
                and checkpoint['training_manifest_sha256']==digest(manifest) and checkpoint['tuning_manifest_sha256']==digest(inputs['tuning'])
                and stage['frozen_non_scope_state_sha256']==digest(non_scope),'scope checkpoint update/manifest lineage differs')
            saved=read_ref(stage['tuning']);require(set(saved['generation'])==set(saved['metrics'])==set(inputs['tuning']) and stage['metrics']==saved['metrics'],'complete scope stage tuning payload required')
            normalized={};failures=[]
            for panel,targets in inputs['tuning'].items():
                normalized[panel]=audited_scope_metric(saved['generation'][panel],inputs['sources'][panel],targets,saved['metrics'][panel])
                verify_frozen_token_outputs(saved_parent['generation'][panel],saved['generation'][panel])
                jobs.append({'kind':'boundary','name':f'scope-{arm}/stage-{stage["steps"]}/'+panel,'checkpoint':stage['checkpoint'],
                    'sources':inputs['sources'][panel],'generation':stage['tuning'],'scope_panel':panel,'stage':True})
            for panel in sorted(normalized):
                score,baseline=normalized[panel],parent_metrics[panel]
                for key,recorded in (('raw_supported_correct','raw_supported_scope_correct'),('supported_exact','exact_supported_segmentation')):
                    if score[key]<baseline[key]:failures.append(panel+':'+recorded+'_regressed')
                if score['raw_unsupported_accepted']:failures.append(panel+':raw_unsupported_accepted')
                if score['unsupported_accepted']:failures.append(panel+':final_unsupported_accepted')
            require(stage['raw_token_logits_unchanged'] is True and stage['failures']==failures and stage['eligible'] is (not failures),'independent raw scope eligibility/failure list differs')
            stages.append({'steps':stage['steps'],'metrics':normalized,'raw_token_logits_unchanged':True})
            stage_audits.append({'steps':stage['steps'],'checkpoint':stage['checkpoint'],'tuning':stage['tuning'],'metrics':normalized,
                'eligible':not failures,'failures':failures,'weights':weights})
        choice=scope_choice(stages,parent_metrics);steps=choice['steps'] if choice else 0
        pin=next(s['checkpoint'] for s in trial['stages'] if s['steps']==steps) if choice else parent_ref
        status='candidate' if choice else 'parent_fallback_no_eligible_scope_stage'
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status
            and by_name[arm]=={key:trial[key] for key in ('name','arm','checkpoint','selected_steps','selection')},'independent scope candidate/fallback selection differs')
        audits.append({'name':arm,'training':trial['training'],'stages':stage_audits,'selection':status,'selected_steps':steps,
            'checkpoint':pin,'executed_updates':400,'optimizer_trajectory_replayed':False})
    require([r['common_replay_ids'] for r in traces['control']]==[r['common_replay_ids'] for r in traces['target']],'scope arms changed common replay order')
    for model in models:
        name=model['name'];require(set(frozen['files'][name])==set(inputs['sources']),'selected scope source panel omitted')
        for panel,sources in inputs['sources'].items():
            pin=frozen['files'][name][panel];generation=read_ref(pin)
            verify_frozen_token_outputs(read_ref(frozen['files']['parent'][panel]),generation);verify_scope_logits(generation)
            jobs.append({'kind':'boundary','name':f'scope-selected-{name}/'+panel,'checkpoint':model['checkpoint'],
                'sources':sources,'generation':pin})
    return jobs,{'parent':parent_ref,'training_pairs':pair_audit,'trials':audits,'parent_tuning':parent_metrics,
        'executed_updates':800,'scope_only_trainable_parameters':130,'tuning_source_rows_replayed':8400,
        'selected_source_rows_replayed':4464,'clause_outputs_used_for_selection':False,'optimizer_trajectory_replayed':False}


def verify_training_report(report, preceding, checkpoint, inputs, eligibility):
    start, finish = preceding['progress']['optimizer_steps'], checkpoint['progress']['optimizer_steps']
    config, model_config = checkpoint['training_config'], checkpoint['model_config']
    objective = config['objective']; enabled = model_config['trigger_enabled']; weight = .25
    require(objective in OBJECTIVES, 'matched objective required')
    updates=finish-start
    require((start,finish) in ((0,100),(100,200)), 'complete declared stage chain required')
    require(updates == report['optimizer_steps'] and report['new_optimizer_steps_total'] == finish
        and report['training_executed'] is True and report['stopped_reason'] == 'step_limit'
        and report['tuning_used_for_fit'] is False and report['objective'] == objective,
        'complete fixed declared-update training stage with fitting-only labels required')
    require(report['checkpoint_sha256'] == digest(checkpoint)
        and report['frozen_parent_checkpoint_sha256'] == checkpoint['frozen_parent_checkpoint_sha256']
        and report['frozen_parent_optimizer_steps'] == checkpoint['frozen_parent_optimizer_steps']
        and report['frozen_parent_kind']==checkpoint['frozen_parent_kind']
        and report['hard_mining_sha256']==checkpoint['hard_mining_sha256'],
        'training report checkpoint or facet800 parent binding differs')
    require(len(report['batch_losses']) == len(report['batch_loss_components']) == len(report['batch_exposures']) == updates
        and report['domain_exposures'] == {'earlier': 3*updates, 'new': 9*updates} and report['pair_exposures'] == 3*updates,
        'complete3+3+3pair stage exposures required')
    require(type(report['elapsed_seconds']) in (int, float) and math.isfinite(report['elapsed_seconds']) and report['elapsed_seconds'] > 0
        and math.isfinite(report['gradient_norm_max']) and report['gradient_norm_max'] >= 0,
        'finite training timing and gradient receipts required')
    pools=prior.training_pools(inputs)
    require(report['rehearsal_exposures']=={'positive':2*updates,'negative':2*updates},'complete auxiliary exposures required')
    numerical = ('semantic', 'trigger', 'actor', 'semantic_earlier', 'semantic_new', 'actor_earlier', 'actor_new',
        'js_modality', 'js_presence', 'js_endpoints', 'base_ce', 'consistency_js', 'weighted_consistency', 'total', 'base_objective','teacher_presence_kl','teacher_endpoint_kl','teacher_kl','span_overlap','weighted_teacher','weighted_overlap','common_objective','condition_positive_ce','condition_negative_ce','condition_balanced_presence_ce','condition_present_endpoint_ce','condition_rehearsal_ce','weighted_condition_rehearsal')
    require(report['teacher_training_labels_only'] is report['teacher_state_unchanged'] is report['teacher_gradients_disabled'] is True, 'teacher was not frozen or used unadmitted labels')
    exact_batch_checks=[]
    def close(a, b): return math.isclose(a, b, rel_tol=2e-5, abs_tol=2e-6)
    for step, (exposure, parts, loss) in enumerate(zip(report['batch_exposures'], report['batch_loss_components'], report['batch_losses']), start + 1):
        require(exposure == expected_clause_batch(config['seed'], step, pools, checkpoint['hard_mining']['selected_ids']), 'independent objective-neutral paired minibatch order differs')
        require(parts['domain_rows'] == {'earlier': 3, 'new': 9} and parts['supervised_trigger_rows'] == 9
            and parts['trigger_loss_rows'] == (9 if enabled else 0) and parts['pair_count'] == 3
            and parts['consistency_weight'] == weight, 'domain, trigger mask or paired loss counts differ')
        require(all(type(parts[k]) in (int, float) and math.isfinite(parts[k]) and parts[k] >= -2e-6 for k in numerical)
            and type(loss) in (float, int) and math.isfinite(loss) and loss >= -2e-6, 'finite bounded loss components required')
        require(all(parts[k] <= math.log(2) + 2e-6 for k in ('js_modality', 'js_presence', 'js_endpoints', 'consistency_js')),
                'Jensen-Shannon divergence exceeds probability bound')
        require(close(parts['semantic'], (parts['semantic_earlier'] + parts['semantic_new']) / 2)
            and close(parts['actor'], (parts['actor_earlier'] + parts['actor_new']) / 2)
            and close(parts['base_ce'], parts['semantic'] + model_config['trigger_loss_weight'] * parts['trigger'] + model_config['actor_loss_weight'] * parts['actor'])
            and close(parts['consistency_js'], sum(parts[k] for k in ('js_modality', 'js_presence', 'js_endpoints')) / 3)
            and close(parts['weighted_consistency'], weight * parts['consistency_js'])
            and close(parts['base_objective'], parts['base_ce'] + parts['weighted_consistency']) and close(loss, parts['total']),
            'independent CE/three-component JS/weighted total accounting differs')
        teacher_weight, overlap_weight = .5,.1
        condition_weight=.5 if objective=='condition_rehearsal' else 0.
        expected_counts = {key:sum(eligibility[identity][key] for identity in exposure['ids'][:6])
            for key in ('teacher_presence_terms','teacher_endpoint_terms')}
        expected_counts['overlap_facet_pairs']=sum(eligibility[identity]['overlap_facet_pairs'] for identity in exposure['ids'])
        if any(parts[key]!=expected_counts[key] for key in ('teacher_presence_terms','teacher_endpoint_terms')) and isinstance(eligibility,TeacherEligibilityCache):
            original={key:expected_counts[key] for key in ('teacher_presence_terms','teacher_endpoint_terms')}
            exact=eligibility.exact_batch_counts(exposure['ids']);expected_counts.update(exact)
            exact_batch_checks.append({'step':step,'cached':original,'exact_batch':exact})
        require(all(parts[key]==value for key,value in expected_counts.items()), 'independent teacher-label eligibility or gold-present overlap counts differ')
        require(parts['teacher_weight']==teacher_weight and parts['overlap_weight']==overlap_weight
            and -2e-6 <= parts['span_overlap'] <= 1+2e-6
            and close(parts['teacher_kl'],(parts['teacher_presence_kl']+parts['teacher_endpoint_kl'])/2)
            and close(parts['weighted_teacher'],teacher_weight*parts['teacher_kl'])
            and close(parts['weighted_overlap'],overlap_weight*parts['span_overlap'])
            and close(parts['common_objective'],parts['base_objective']+parts['weighted_teacher']+parts['weighted_overlap'])
            and parts['condition_weight']==condition_weight and parts['condition_positive_rows']==2
            and parts['condition_negative_rows']==2 and parts['rehearsal_rows']==4
            and close(parts['condition_balanced_presence_ce'],(parts['condition_positive_ce']+parts['condition_negative_ce'])/2)
            and close(parts['condition_rehearsal_ce'],(parts['condition_balanced_presence_ce']+parts['condition_present_endpoint_ce'])/2)
            and close(parts['weighted_condition_rehearsal'],condition_weight*parts['condition_rehearsal_ce'])
            and close(parts['total'],parts['common_objective']+parts['weighted_condition_rehearsal']),
            'matched loss intervention arithmetic or bounded overlap differs')
        if not enabled:
            require(all(parts[k] == 0 for k in ('actor', 'trigger', 'actor_earlier', 'actor_new')), 'disabled auxiliary losses must be zero')
    gradients = report['auxiliary_gradient_norm_max']
    require(set(gradients) == {'trigger_boundary', 'trigger_modality', 'actor_boundary'}
        and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in gradients.values()), 'finite auxiliary gradient inventory required')
    if not enabled:
        require(all(v == 0 for v in gradients.values()), 'disabled auxiliary gradients must remain zero')
        for name, value in preceding['model_state'].items():
            if name.startswith(('trigger_boundary.', 'trigger_modality.', 'actor_boundary.')):
                require(checkpoint['model_state'][name] == value, 'disabled auxiliary parameters changed')
    changed = [name for name, value in checkpoint['model_state'].items() if value != preceding['model_state'][name]]
    require(changed and len(report['changed_parameter_names']) == len(changed)
        and sorted(report['changed_parameter_names']) == sorted(changed), 'changed model tensor inventory differs')
    return {'additional_steps_before': start, 'additional_steps_after': finish, 'optimizer_updates': updates,
        'domain_exposures': report['domain_exposures'], 'pair_exposures': 3*updates,
        'batch_trace_sha256': digest(report['batch_exposures']), 'same_semantics_pairs_only': True,
        'independent_schedule_and_loss_accounting_verified': True, 'exact_batch_teacher_rechecks':exact_batch_checks, 'optimizer_trajectory_replayed': False}


OBJECTIVES=('base','condition_rehearsal')
POLICIES=('parent',*OBJECTIVES)
TUNING=(*prior.TUNING,'condition')
SINGLE_COUNTS={**{k:v for k,v in prior.SINGLE_COUNTS.items() if k.startswith('tuning_')},'tuning_condition':96,'retention_facet':192,'retention_temporal':192,'fresh':192,'real_exposed':86}
DOCUMENT_COUNTS={p:96 for p in ('fresh_documents','retention_facet_documents','retention_temporal_documents')}
DOCUMENT_TUNING=(*prior.DOCUMENT_TUNING,'condition_document_tuning','retention_facet_documents','retention_temporal_documents')
DOCUMENT_PREFIX={**prior.DOCUMENT_PREFIX,'condition_document_tuning':'condition_','retention_facet_documents':'retention_facet_','retention_temporal_documents':'retention_temporal_'}


def validate_nested(value,count):
    require(set(value)=={'count','fullrule_exact','modality_fullrule','condition_facet','temporal_facet','condition_fullrule','temporal_fullrule'} and value['count']==count and type(value['fullrule_exact']) is int and 0<=value['fullrule_exact']<=count,'closed nested full-rule metrics required')
    for kind in ('modality_fullrule','condition_facet','temporal_facet','condition_fullrule','temporal_fullrule'):
        labels=('O','P','F') if kind=='modality_fullrule' else ('present','absent')
        require(set(value[kind])==set(labels),'complete metric strata required')
        for cell in value[kind].values():require(set(cell)=={'count','exact'} and cell['count']==count//len(labels) and type(cell['exact']) is int and 0<=cell['exact']<=cell['count'],'bounded complete metric stratum required')
        if kind.endswith('fullrule'):require(sum(c['exact'] for c in value[kind].values())==value['fullrule_exact'],'full-rule strata must partition exact total')


def clause_eligible(stage,parent):
    bounds={**prior.OLD_BOUNDS,**prior.NEW_BOUNDS,**{k:24 for k in prior.GUARDS},'condition':96,
        **{prefix+k:limit for prefix in ('condition_','retention_facet_','retention_temporal_') for k,limit in (('document_parent',72),('document_expanded',72),('guard_parent',24),('guard_expanded',24))}}
    for value in (stage,parent):
        require(set(value)==set(bounds)|{'retention_metrics','condition_metrics'} and all(type(value[k]) is int and 0<=value[k]<=n for k,n in bounds.items()),'closed complete clause gate metric inventory required')
        require(value['new_positive']+value['new_negative']==value['new'],'old temporal class partition differs')
        require(set(value['retention_metrics'])=={'facet','temporal'},'both exposed retention panels required')
        for panel in ('facet','temporal'):validate_nested(value['retention_metrics'][panel],192)
        validate_nested(value['condition_metrics'],96)
        require(value['condition']==value['condition_metrics']['fullrule_exact'],'new condition metric partition differs')
    eligible=all(stage[k]>=parent[k]-1 for k in prior.OLD_BOUNDS) and all(stage[k]>=parent[k] for k in prior.NEW_BOUNDS) and all(stage[k]==0 for k in prior.GUARDS)
    for panel in ('facet','temporal'):
        a,b=stage['retention_metrics'][panel],parent['retention_metrics'][panel]
        eligible &= a['fullrule_exact']>=b['fullrule_exact'] and all(a[k][label]['exact']>=b[k][label]['exact'] for k in ('modality_fullrule','condition_facet','temporal_facet') for label in a[k])
        for policy in ('parent','expanded'):
            prefix='retention_'+panel+'_'
            eligible &= stage[prefix+'document_'+policy]>=parent[prefix+'document_'+policy] and stage[prefix+'guard_'+policy]<=parent[prefix+'guard_'+policy]
    a,b=stage['condition_metrics'],parent['condition_metrics']
    eligible &= a['fullrule_exact']>=b['fullrule_exact'] and all(a[k][label]['exact']>=b[k][label]['exact'] for k in ('condition_fullrule','temporal_fullrule') for label in a[k])
    eligible &= all(stage['condition_document_'+p]>=parent['condition_document_'+p] and stage['condition_guard_'+p]==0 for p in ('parent','expanded'))
    return bool(eligible)


def clause_ranking(row):
    return (row['condition'],sum(row['retention_metrics'][p]['condition_facet']['present']['exact'] for p in ('facet','temporal')),sum(row['retention_metrics'][p]['fullrule_exact'] for p in ('facet','temporal')),row['new'],2*row['role']+row['facet'],row['new_document_expanded'],row['new_document_parent'],row['temporal'],row['prior_facet_document_expanded'],row['prior_facet_document_parent'],row['document_expanded'],row['document_parent'],row['earlier'],-row['steps'])


def clause_choice(stages,parent):
    require([s['steps'] for s in stages]==[100,200],'both ordered clause stages required')
    eligible=[s for s in stages if clause_eligible({k:v for k,v in s.items() if k!='steps'},parent)]
    return max(eligible,key=clause_ranking) if eligible else None


def tuning_audit(fields,item,inputs,frozen,label):
    jobs,normalized=[],{}
    for panel in TUNING:
        key='tuning_'+panel;reference=fields[key];saved=read_ref(reference);sources=inputs['sources'][key]
        metric=previous.score(saved['generation']['rows'],sources,inputs['tuning'][panel])
        require(saved['metrics']==metric and fields[key+'_exact']==metric['exact'],'independent single tuning count differs')
        normalized[{'prior_role':'role','prior_facet':'facet'}.get(panel,panel)]=metric['exact']
        strata=prior.temporal_strata(saved['generation'],sources,inputs['tuning'][panel]) if panel=='new' else {}
        require(saved['temporal_class_metrics']==strata,'temporal class receipt differs')
        nested=retention_metrics(saved['generation'],sources,inputs['tuning'][panel]) if panel=='condition' else None
        require(saved['scope_metrics']==nested,'condition scoped tuning receipt differs')
        if panel=='condition':require(fields['condition_metrics']==nested,'condition stage counts differ');normalized['condition_metrics']=nested
        if panel=='new':
            for name,key2 in (('Tpresent','positive'),('Tabsent','negative')):
                require(fields['tuning_new_'+name+'_exact']==strata[name]['exact'],'stage temporal class count differs');normalized['new_'+key2]=strata[name]['exact']
        jobs.append({'kind':'single','name':label+'/'+key,'model':item,'sources':sources,'generation':reference,'stage':True})
    normalized['retention_metrics']={}
    for panel in ('facet','temporal'):
        key='retention_'+panel;saved=read_ref(fields[key]);sources=inputs['sources'][key];targets=inputs['retention_targets'][panel]
        metric=previous.score(saved['generation']['rows'],sources,targets);nested=retention_metrics(saved['generation'],sources,targets)
        require(saved['metrics']==metric and saved['scope_metrics']==fields['retention_metrics'][panel]==nested,'exposed retention metric differs')
        normalized['retention_metrics'][panel]=nested
        jobs.append({'kind':'single','name':label+'/'+key,'model':item,'sources':sources,'generation':fields[key],'stage':True})
    for panel,prefix in DOCUMENT_PREFIX.items():
        for policy in ('parent','expanded'):
            reference=fields[panel+'_'+policy];saved=read_ref(reference);sources=inputs['document_sources'][panel]
            metric=retained.score_documents(saved['generation'],sources,inputs[panel])
            require(saved['metrics']==metric and fields['tuning_'+prefix+'document_'+policy+'_exact']==metric['exact'] and fields['tuning_'+prefix+'document_'+policy+'_unsupported_accepted']==metric['unsupported_accepted'],'joint document tuning metric differs')
            normalized[prefix+'document_'+policy]=metric['exact'];normalized[prefix+'guard_'+policy]=metric['unsupported_accepted']
            head='parent' if policy=='parent' else 'expanded-1730'
            jobs.append({'kind':'document','name':label+'/'+panel+'_'+policy,'model':item,'sources':sources,'generation':reference,'boundary':frozen['boundaries'][head][panel],'stage':True})
    reference=fields['training_new'];saved=read_ref(reference);metric=previous.score(saved['generation']['rows'],inputs['training_sources'],inputs['new_train'])
    require(saved['metrics']==metric and fields['training_new_exact']==metric['exact'] and metric['count']==192 and saved['diagnostic_only'] is True and saved['checkpoint_selection_uses_this_metric'] is False and saved['previously_authored_training_rows'] is True and saved['new_training_rows_added']==0,'old TRAIN diagnostic differs')
    jobs.append({'kind':'single','name':label+'/training_new','model':item,'sources':inputs['training_sources'],'generation':reference,'stage':True,'training_diagnostic':True})
    return jobs,normalized


def verify_training(inputs,frozen,selection):
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    require(selection['executed_optimizer_updates']==800 and selection['fresh_targets_opened'] is False and selection['exposed_panels_admitted_as_retention'] is True,'complete declared clause fit required')
    trials=selection['trials'];models={m['name']:m for m in frozen['models']}
    require(len(trials)==4 and {(t['objective'],t['architecture'],t['seed']) for t in trials}=={(o,a,1730) for o in OBJECTIVES for a in ARCHITECTURES},'all four matched clause trials required')
    parent_tuning=read_ref(selection['parent_tuning']);jobs,audits,parents,caches,mining_audits=[],[],{},{},{}
    tuning=[r for p in TUNING for r in inputs['tuning'][p]]+[r for p in ('facet','temporal') for r in inputs['retention_targets'][p]]
    pairs=[[p['left_id'],p['right_id']] for p in inputs['training_pairs']]
    require(inputs['runtime_pairs']==pairs and len(tuning)==1176,'exact fitting pairs and admitted tuning inventory required')
    require(set(parent_tuning)=={f'parent_{a}-1730' for a in ARCHITECTURES},'two fixed parent tuning references required')
    for name in sorted(parent_tuning):
        model=models[name];item=inputs['parents'][(model['architecture'],1730)];parent=read_ref(item['checkpoint'])
        require(model['checkpoint']==model['parent']==item['checkpoint'] and model['decoder_kind']==item['decoder_kind'],'pretest parent binding differs')
        local,parents[name]=tuning_audit(parent_tuning[name],model,inputs,frozen,'clause-parent-'+name);jobs+=local
        caches[name],mining_audits[name]=audit_mining_and_teacher(parent,item['decoder_kind'],inputs,inputs['hard_mining'][(model['architecture'],1730)])
    traces=[]
    for trial in trials:
        name,architecture,objective=trial['name'],trial['architecture'],trial['objective'];parent_name=f'parent_{architecture}-1730';parent_model=models[parent_name];parent_ref=parent_model['checkpoint'];parent=read_ref(parent_ref);kind=parent_model['decoder_kind'];hard=inputs['hard_mining'][(architecture,1730)]
        require(trial==models[name] and trial['executed_steps']==200 and trial['seed']==1730 and trial['enabled'] is (architecture=='grounding') and trial['parent']==parent_ref and trial['parent_kind']==kind and trial['fresh_targets_opened'] is False and trial['exposed_retention_targets_opened'] is True and trial['trial_wall_limit_seconds']==600 and 0<trial['trial_wall_seconds']<=600,'clause trial identity/budget differs')
        require({k:v for k,v in trial.items() if k!='selection_record'}==read_ref(trial['selection_record']) and trial['parent_tuning']==parent_tuning[parent_name],'selection receipt/parent tuning differs')
        initial=runtime.load_checkpoint(trial['initial_checkpoint']['path'],expected_sha256=trial['initial_checkpoint']['sha256'])
        reconstructed=runtime.build_checkpoint(parent,inputs['training'],tuning,pairs,hard,parent_kind=kind,objective=objective,seed=1730,learning_rate=.00025,batch_size=12)
        require(initial==reconstructed and initial['model_state']==parent['model_state'] and initial['optimizer_state']=={'schema':'adam-default-betas-eps/v1','parameters':{}} and initial['progress']['optimizer_steps']==0,'independent exact initial state/fresh Adam reconstruction differs')
        init=read_ref(trial['initialization'])
        require(init['parent']==parent_ref and init['initial']==trial['initial_checkpoint'] and init['parent_kind']==kind and init['hard_mining_sha256']==digest(hard) and init['initial_model_state_sha256']==init['parent_model_state_sha256']==trial['initial_model_state_sha256']==digest(parent['model_state']) and init['parent_tuning']==parent_tuning[parent_name] and init['all_initial_tensors_equal'] is init['all_tuning_numerical_predictions_equal'] is init['optimizer_reset'] is True and init['historical_optimizer_resumed'] is False,'initialization provenance differs')
        for key in [*('tuning_'+p for p in TUNING),'retention_facet','retention_temporal','training_new']:
            a,b=read_ref(init['parent_tuning'][key]),read_ref(init['tuning'][key])
            require(a['generation']['rows']==b['generation']['rows'] and a['metrics']==b['metrics'],'initial numerical clause outputs differ')
            require(all(r['checkpoint_sha256']==digest(initial) for r in b['generation']['reports']),'initial checkpoint metadata differs')
        for panel in DOCUMENT_TUNING:
            for policy in ('parent','expanded'):
                a,b=(read_ref(init[k][panel+'_'+policy]) for k in ('parent_tuning','tuning'))
                require(runner.document_signature(a['generation'])==runner.document_signature(b['generation']) and a['metrics']==b['metrics'],'initial document outputs differ')
        require([s['steps'] for s in trial['stages']]==[100,200],'complete candidate stage chain required')
        preceding=initial;normalized=[];stage_audits=[];exposures=[]
        for stage in trial['stages']:
            checkpoint=runtime.load_checkpoint(stage['checkpoint']['path'],expected_sha256=stage['checkpoint']['sha256'])
            require(stage['previous_checkpoint_sha256']==checkpoint['parent_checkpoint_sha256']==digest(preceding) and checkpoint['progress']['optimizer_steps']==stage['steps'],'stage chain differs')
            for field in ('schema','lineage_id','implementation','frozen_parent_kind','frozen_parent_checkpoint','frozen_parent_checkpoint_sha256','frozen_parent_optimizer_steps','hard_mining','hard_mining_sha256','model_config','training_config','initial_model_state_sha256','training_manifest_sha256','tuning_manifest_sha256','pair_manifest_sha256','training_count','tuning_count','pool_counts'):
                require(checkpoint[field]==initial[field],'frozen checkpoint field changed: '+field)
            report=read_ref(stage['training_report']);audit=verify_training_report(report,preceding,checkpoint,inputs,caches[parent_name]);exposures+=report['batch_exposures']
            local,scores=tuning_audit(stage,{**trial,'checkpoint':stage['checkpoint'],'decoder_kind':'scope_retention'},inputs,frozen,name+'/stage-'+str(stage['steps']));jobs+=local
            eligible=clause_eligible(scores,parents[parent_name]);require(stage['eligible'] is eligible,'independent clause gate differs')
            normalized.append({'steps':stage['steps'],**scores});stage_audits.append({**audit,'checkpoint':stage['checkpoint'],'training_report':stage['training_report'],'tuning':scores,'eligible':eligible});preceding=checkpoint
        chosen=clause_choice(normalized,parents[parent_name]);steps=chosen['steps'] if chosen else 0;pin=next(s['checkpoint'] for s in trial['stages'] if s['steps']==steps) if chosen else parent_ref;status='candidate' if chosen else 'parent_fallback_no_acceptable_replacement'
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status and trial['decoder_kind']==('scope_retention' if chosen else kind),'independent clause selection/fallback differs')
        fields=next(s for s in trial['stages'] if s['steps']==steps) if chosen else parent_tuning[parent_name]
        for key in [*('tuning_'+p for p in TUNING),'retention_facet','retention_temporal']:
            require(read_ref(fields[key])['generation']==read_ref(frozen['files'][name][key]),'selected clause outputs differ from frozen selection')
        pools=prior.training_pools(inputs);coverage={k:{'pool_entries':len(v),'draws':sum(len(e['indices_by_pool'][k]) for e in exposures),'unique_entries_seen':len({i for e in exposures for i in e['indices_by_pool'][k]})} for k,v in pools.items()}
        traces.append({'objective':objective,'architecture':architecture,'seed':1730,'parent':parent_ref,'batch_count':200,'batch_exposures_sha256':digest(exposures),'actual_pool_coverage':coverage,'rehearsal_unique_ids':len({i for e in exposures for i in e['rehearsal_ids']}),'rehearsal_draws':800,'same_architecture_no_update_control':True,'same_batch_order_as_other_objective':True})
        audits.append({'name':name,'objective':objective,'architecture':architecture,'parent':parent_ref,'parent_kind':kind,'stages':stage_audits,'parent_tuning':parents[parent_name],'selection':status,'selected_steps':steps,'checkpoint':pin,'executed_optimizer_updates':200,'optimizer_trajectory_replayed':False})
    for architecture in ARCHITECTURES:
        pair=[t for t in traces if t['architecture']==architecture];require(len(pair)==2 and pair[0]['batch_exposures_sha256']==pair[1]['batch_exposures_sha256'],'matched complete main+rehearsal schedules differ')
    require(selection['trial_update_audit']==traces,'frozen full update audit differs')
    return jobs,{'trials':audits,'mining':mining_audits,'independent_mining_and_teacher_source_evaluations':8160,'optimizer_trajectory_replayed':False}


def verify_fitting(inputs):
    from scripts.ops.legal_ir import run_legal_temporal_presence_experiment as old_runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    old=old_runner.load_config(inputs['config']['prior_temporal_experiment_config']['path'])
    for key in ('training','runtime_pairs','training_pairs','replay','new_train','training_sources','tuning_pairs','boundary_heads','real_source_manifest'):
        require(inputs[key]==old[key],'previous fitting inventory changed: '+key)
    require(all(inputs['tuning'][p]==old['tuning'][p] for p in prior.TUNING),'old admitted tuning changed')
    artifacts=inputs['manifest']['artifacts']
    require(inputs['tuning']['condition']==read_ref(artifacts['new_tuning']) and inputs['condition_tuning_pairs']==read_ref(artifacts['tuning_pairs']),'condition tuning binding differs')
    a=verify_pairs(inputs['new_train'],inputs['training_pairs']);b=verify_pairs(inputs['tuning']['condition'],inputs['condition_tuning_pairs'])
    parsed,tune=mixed._splits(inputs['training'],[r for p in TUNING for r in inputs['tuning'][p]]+[r for p in ('facet','temporal') for r in inputs['retention_targets'][p]])
    require(len(parsed)==4080 and len(tune)==1176 and a['pairs']==96 and b['pairs']==48,'complete training/tuning coordinate counts differ')
    fit={r['source_text'] for r in inputs['training']}
    require(not fit&{r['source_text'] for rows in inputs['sources'].values() for r in rows},'training/source evaluation overlap')
    return {'training_rows':4080,'new_training_rows':0,'admitted_single_tuning_and_retention_rows':1176,'condition_tuning_pairs':48,'historical_training_unchanged':True,'old_fresh_panels_explicitly_admitted_as_retention':True,'real_source_supervision_rows':0}


def verify_protocol(plan,inputs,frozen):
    expected={'objectives':list(OBJECTIVES),'architectures':list(ARCHITECTURES),'seeds':[1730],'additional_stage_steps':[100,200],
        'additional_updates_per_trial':200,'total_optimizer_updates':800,'learning_rate':.00025,'optimizer':'Adam','optimizer_reset':True,
        'historical_optimizer_resumed':False,'batch_size':12,'auxiliary_batch_size':4,'consistency_weight':.25,'teacher_weight':.5,'overlap_weight':.1,'condition_weight':.5,
        'matched_main_and_rehearsal_inputs':True,'hard_examples_per_class':64,'inference_changed':False,'joint_boundary_stage_search':False,
        'threads_per_worker':1,'trial_wall_limit_seconds':600,'training_diagnostic_count':192,'training_diagnostics_used_for_selection':False,
        'training_inventory_count':4080,'new_training_rows':0,'single_counts':SINGLE_COUNTS,'document_counts':{p:96 for p in (*DOCUMENT_TUNING,'fresh_documents')},
        'final_document_counts':DOCUMENT_COUNTS,'boundary_heads':inputs['boundary_heads'],'fresh_targets_opened':False,'exposed_panels_admitted_as_retention':True}
    require(all(type(plan[k]) is type(v) and plan[k]==v for k,v in expected.items()) and 1<=plan['workers']<=3,'prospective clause protocol differs')
    require(plan['mining']==inputs['config']['hard_mining_manifest'] and plan['selection_contract']==inputs['config']['study_design'],'prospective manifest pins differ')
    for reference in (plan['mining'],plan['selection_contract']):read_ref(reference,parse=False)
    require(frozen['executed_optimizer_updates']==800 and frozen['fresh_targets_opened'] is False and frozen['all_training_selection_and_generation_complete'] is True,'complete source-only clause freeze required')


def verify_inventory(joint,clause,scope,inputs):
    expected={f'{o}_{a}-1730' for o in POLICIES for a in ARCHITECTURES}
    require(joint['models']==clause['models'] and joint['files']==clause['files'] and joint['sources']==clause['sources'] and read_ref(clause['heads'])==clause['models'],'joint changed selected clause inventory')
    models={m['name']:m for m in joint['models']};heads={h['name']:h for h in scope['models']}
    require(len(models)==6 and set(models)==set(joint['files'])==expected and set(heads)=={'parent','control','target'},'six clause/three scope slots required')
    for name,model in models.items():
        require(model['name']==f"{model['objective']}_{model['architecture']}-1730" and model['enabled'] is (model['architecture']=='grounding') and set(joint['files'][name])==set(SINGLE_COUNTS),'clause model/source panel attribution differs')
        if model['objective']=='parent':require(model['selection']=='unchanged_parent' and model['selected_steps']==model['executed_steps']==0,'no-update parent attribution differs')
    expected_pipelines={m+'__scope_'+h for m in models for h in heads}
    require(len(joint['pipelines'])==18 and {p['name'] for p in joint['pipelines']}==set(joint['document_files'])==expected_pipelines and read_ref(joint['pipeline_heads'])==joint['pipelines'],'complete18 independently selected factor crossing required')
    mapping={'fresh_documents':'root_condition_fresh_documents','retention_facet_documents':'facet_exposed_fresh_document_clauses','retention_temporal_documents':'temporal_document_challenge_targets'}
    require(set(joint['boundaries'])==set(heads),'three crossed boundary slots required')
    for head,panels in joint['boundaries'].items():
        require(set(panels)==set(DOCUMENT_COUNTS),'crossed document panel inventory differs')
        for panel,pin in panels.items():require(pin==scope['files'][head][mapping[panel]] and read_ref(scope['sources'][mapping[panel]])==inputs['document_sources'][panel],'crossed fixed boundary source/reference differs')
    for pipeline in joint['pipelines']:
        model=models[pipeline['source_model_name']];head=heads[pipeline['boundary_head']]
        require(pipeline['name']==model['name']+'__scope_'+head['name'] and pipeline['boundary_checkpoint']==head['checkpoint'] and pipeline['boundary_selection']==head['selection'] and pipeline['boundary_selected_steps']==head['selected_steps'] and set(joint['document_files'][pipeline['name']])==set(DOCUMENT_COUNTS) and all(pipeline[k]==model[k] for k in ('checkpoint','decoder_kind','architecture','objective','seed','enabled','selection','selected_steps')),'crossed checkpoint/policy attribution differs')
    return {'single_model_slots':6,'document_pipeline_slots':18,'selected_boundary_slots':3,'selected_single_rows':8724,'selected_pipeline_documents':5184,'scope_fresh_source_rows':192,'scope_fresh_policy_slots':576}


def verify_identifier_receipt(pin,scope_ref,scope):
    from copy import deepcopy
    value=read_ref(pin);require(value['schema']=='legal-scope-identifier-invariance/v1' and value['generation_freeze']==scope_ref and value['source_rows_per_slot']==192 and value['head_slots']==3 and value['additional_source_evaluations']==576 and value['all_numeric_and_final_outputs_invariant'] is True and value['new_reference_targets_opened'] is value['new_reference_ledger_opened'] is False,'complete pre-reference ID invariance receipt required')
    sources=read_ref(value['original_sources']);opaque=read_ref(value['opaque_sources']);rng=random.Random(864139)
    expected_sources=[{**s,'candidate_id':'opaque-'+f'{rng.getrandbits(128):032x}'} for s in sources]
    require(value['original_sources']==scope['sources']['scope_fresh'] and len(sources)==192 and opaque==expected_sources,'independent source-neutral opaque identity schedule differs')
    require(read_ref(value['identifier_map'])==[{'original_id':a['candidate_id'],'opaque_id':b['candidate_id'],'source_sha256':a['source_sha256']} for a,b in zip(sources,opaque,strict=True)],'ID mapping commitment differs')
    require([h['name'] for h in value['heads']]==['parent','control','target'],'all three ID probe slots required')
    for h,model in zip(value['heads'],scope['models'],strict=True):
        require(h['checkpoint']==model['checkpoint'] and h['original_generation']==scope['files'][h['name']]['scope_fresh'],'ID probe checkpoint/source generation differs')
        original=read_ref(h['original_generation']);wanted=deepcopy(original);actual=read_ref(h['renamed_generation'])
        for row,source in zip(wanted['rows'],opaque,strict=True):
            row['candidate_id']=source['candidate_id']
            if row['plan'] is not None:
                plan=row['plan'];retained.compose.validate_source_plan(plan,expected_plan_sha256=plan['plan_sha256'])
                clauses_=[{k:c[k] for k in ('clause_id','char_start','char_end','scope')} for c in plan['clauses']]
                row['plan']=retained.compose.prepare_source_plan(source,clauses_)
        cursor=0
        for report in wanted['reports']:
            n=len(report['rows']);report['rows']=deepcopy(wanted['rows'][cursor:cursor+n]);cursor+=n
        require(cursor==192 and actual==wanted and h['rows']==192 and h['actual_output_sha256']==h['expected_output_sha256']==digest(actual) and h['original_output_sha256']==digest(original),'complete independent identity-only output rebinding differs')
        require(h['model_state_sha256_before']==h['model_state_sha256_after']==digest(read_ref(h['checkpoint'])['model_state']),'ID probe frozen model state differs')
    for producer in value['producer_files']:read_ref(producer,parse=False)
    return {'receipt':pin,'additional_source_evaluations':576,'all_outputs_equal_after_identity_only_rebinding':True,'original_source_ids_expose_authored_scope_class':True,'fresh_reference_file_sealing_does_not_establish_label_free_source_metadata':True}


_WORKER_GUARD=None

def init_replay_worker(sealed):
    global _WORKER_GUARD
    _WORKER_GUARD=SealedReadGuard(sealed);sys.addaudithook(_WORKER_GUARD.event)


def replay_group(group):
    import torch
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as runner
    torch.set_num_threads(1)
    decoder=boundary.ClauseBoundaryDecoder(read_ref(group['checkpoint'])) if group['decoder_kind']=='boundary' else runner.load_decoder(group['checkpoint'],group['decoder_kind'])
    results=[]
    for job in group['jobs']:
        if 'scope_panel' in job:
            expected=read_ref(job['generation'])['generation'][job['scope_panel']];actual=clauses.decode_all(decoder,job['sources'])
            require(actual==expected,'independent full scope stage replay differs: '+job['name'])
            result={'kind':'boundary','name':job['name'],'rows':len(job['sources']),'generation':job['generation'],'scope_panel':job['scope_panel'],'checkpoint':job['checkpoint'],'boundary':None,'source_inputs_sha256':digest(job['sources']),'recorded_generation_sha256':digest(actual),'exact_recorded_payload_replay':True,'clause_occurrences_replayed':0,'copied_facets_verified':0,'stage_tuning':True,'training_diagnostic':False,'recomputed_for_this_saved_panel':True,'target_access':False}
        else:result=replay_with_decoder(job,decoder)
        require(_WORKER_GUARD is not None and not _WORKER_GUARD.events,'worker lacked pre-reference read guard or attempted sealed access')
        results.append(result);print({'phase':'replayed','name':job['name'],'rows':len(job['sources'])},flush=True)
    return results


def verify_annotation(row,label,panel):
    import hashlib
    text=row['source_text'];rule=row['canonical_ir']['rules'][0]
    require(label['panel']==panel and label['id']==row['id'] and label['source_sha256']==hashlib.sha256(text.encode()).hexdigest()
        and label['facet_spans']==row['facet_spans'] and label['trigger_span']==row['trigger_span']
        and label['annotation_authority']=='authored_controlled_example_not_statutory_gold','annotation source or authority differs')
    require(label['presence_mask']==sum(1<<i for i,f in enumerate(('conditions','exceptions','temporal')) if rule[f]),'annotation optional presence mask differs')
    intervals=sorted((s[0],s[1],f) for f,s in {**row['facet_spans'],'trigger':row['trigger_span']}.items() if s is not None)
    cursor=0
    for start,end,field in intervals:
        require(type(start) is int and type(end) is int and cursor<=start<end<=len(text),'facet/trigger overlap or invalid interval')
        if field!='trigger':
            value=rule[field];value=value[0] if isinstance(value,list) else value
            require(text[start:end]==value,'facet literal does not match exact source interval')
        cursor=end
    template=role_layout(row)
    require(label['role_masked_layout']==template,'independent modal-normalized layout differs')
    for note in label['editorial_context']:
        start,end=note['start_char'],note['end_char']
        require(0<=start<end<=len(text) and text[start:end]==note['source_text'] and note['author_stipulated_role']=='nonoperative_editorial_context'
            and all(end<=a or start>=b for a,b,_ in intervals),'editorial context overlaps operative facet')
    return {'role_masked_layout':template,'case_group':label['case_group']}

def verify_condition_annotation(row,annotation):
    import re
    prior.verify_temporal_annotation(row,annotation)
    span=row['facet_spans']['conditions'];present=bool(row['canonical_ir']['rules'][0]['conditions'])
    require((span is not None)==present,'condition annotation presence differs')
    cue=None;placement='absent'
    if present:
        match=re.search(r'\b(provided\s+that|when|if)\s*$',row['source_text'][:span[0]],re.I)
        require(match is not None,'condition cue missing before its exact source interval');cue=' '.join(match.group(1).lower().split())
        left=span[0];placement='before_actor' if left<row['facet_spans']['actor'][0] else 'between_actor_and_modal' if left<row['trigger_span'][0] else 'between_modal_and_action' if left<row['facet_spans']['action'][0] else 'after_object'
        require(row['source_text'][slice(*span)]==row['canonical_ir']['rules'][0]['conditions'][0],'condition literal/span differs')
    expected={'condition_present':present,'condition_placement':placement,'condition_cue':cue}
    require(all(type(annotation[k]) is type(v) and annotation[k]==v for k,v in expected.items()),'condition role/placement annotation differs')
    return expected


def historical_pool_rows(metadata):
    rows=read_ref(metadata['reference']);representation=metadata['representation']
    if representation=='document_clauses':rows=retained.document_audit_clauses(rows)
    elif representation=='earlier_single_targets':
        sources={r['id']:r for r in read_ref(metadata['source_reference'])['splits']['challenge']};converted=[]
        for row in rows['targets']:
            fields={}
            for field in ('actor','action','object','conditions','exceptions','temporal'):
                value=row['source_spans'][field];fields[field]=(value[0] if value else None) if field in ('conditions','exceptions','temporal') else value or None
            converted.append({'id':row['id'],'source_text':sources[row['id']]['source_text'],'facet_spans':fields,'canonical_ir':row['canonical_ir']})
        rows=converted
    else:require(representation in ('annotated_single','grounding_single'),'unknown historical representation')
    return [r for r in rows if r['domain']==metadata['filter_domain']] if 'filter_domain' in metadata else rows


def audit_exposure(inputs,single_targets,document_targets,evidence):
    import re
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    exposure,ledger=evidence['exposure_audit'],evidence['annotation_ledger']
    require(exposure['schema']=='authored-condition-rehearsal-exposure/v1' and ledger['schema']=='authored-condition-rehearsal-annotations/v1','condition exposure schema differs')
    panels={'tuning':inputs['tuning']['condition'],'fresh':single_targets['fresh']};pairs={'tuning':inputs['condition_tuning_pairs'],'fresh':evidence['challenge_pairs']}
    annotations={a['id']:a for a in ledger['single_rows']}
    require(len(annotations)==len(ledger['single_rows'])==288 and set(annotations)=={r['id'] for rows in panels.values() for r in rows},'complete288 condition single annotations required')
    normalize=lambda text:' '.join(re.findall(r'\w+|[^\w\s]',text.casefold()))
    seen_sources,seen_meanings,seen_cases=set(),set(),set();audits={}
    for panel,rows in panels.items():
        audit=verify_pairs(rows,pairs[panel]);labels=[annotations[r['id']] for r in rows]
        verify_annotation_pairs(pairs[panel],labels);validate_fresh_coordinates(inputs,rows)
        for row in rows:
            verify_annotation(row,annotations[row['id']],panel);verify_condition_annotation(row,annotations[row['id']])
        require(Counter((r['canonical_ir']['rules'][0]['modality'],annotations[r['id']]['presence_mask']) for r in rows)=={(m,mask):len(rows)//24 for m in 'OPF' for mask in range(8)},'all modality/mask combinations required')
        expected_families={f:48 for f in corpus.FAMILIES[:2]} if panel=='tuning' else {f:48 for f in corpus.FAMILIES}
        require(Counter(a['family'] for a in labels)==expected_families,'declared per-panel condition families differ')
        expected_placements={'absent':48,'between_modal_and_action':12,'after_object':24,'before_actor':12} if panel=='tuning' else {'absent':96,**{p:24 for p in ('before_actor','between_actor_and_modal','between_modal_and_action','after_object')}}
        require(Counter(a['condition_placement'] for a in labels)==expected_placements,'declared per-panel condition placements differ')
        texts={normalize(r['source_text']) for r in rows};meanings={digest(r['canonical_ir']) for r in rows};cases=set(audit['case_groups'])
        require(len(texts)==len(rows) and len(meanings)==len(cases)==len(rows)//2 and not(texts&seen_sources or meanings&seen_meanings or cases&seen_cases),'condition source/meaning/case crosses authored splits')
        seen_sources|=texts;seen_meanings|=meanings;seen_cases|=cases
        audits[panel]={'rows':len(rows),'meaning_groups':len(meanings),'families':dict(Counter(a['family'] for a in labels)),'condition_present':sum(a['condition_present'] for a in labels),'temporal_present':sum(a['temporal_present'] for a in labels)}
    da={a['candidate_id']:a for a in ledger['document_rows']};docpanels={'document_tuning':inputs['condition_document_tuning'],'document_fresh':document_targets['fresh_documents']}
    require(len(da)==len(ledger['document_rows'])==192 and set(da)=={r['candidate_id'] for rows in docpanels.values() for r in rows},'all192 condition document annotations required')
    docclauses={}
    for panel,rows in docpanels.items():
        require(Counter(r['supported'] for r in rows)=={True:72,False:24} and Counter(len(r['clauses']) for r in rows if r['supported'])=={1:24,2:24,3:24} and sum(r['repeated_rule_occurrences'] for r in rows)==12,'document support/occurrence denominator differs')
        require(all(da[r['candidate_id']]['panel']==panel for r in rows),'document panel differs')
        dc=document_clauses(rows,ledger['document_rows']);docclauses[panel]=dc;require(len(dc)==144,'144 supported clause occurrences required')
        for local,coord in zip(dc,[c for r in rows for c in da[r['candidate_id']]['clause_coordinates']],strict=True):verify_condition_annotation(local,coord)
        validate_occurrence_coordinates(inputs,dc)
        texts={normalize(r['source_text']) for r in [*rows,*dc]};meanings={digest(r['canonical_ir']) for r in dc};cases={da[r['candidate_id']]['case_group'] for r in rows}
        require(len(cases)==96 and not(texts&seen_sources or meanings&seen_meanings or cases&seen_cases),'document source/meaning/case crosses panel')
        seen_sources|=texts;seen_meanings|=meanings;seen_cases|=cases
        audits[panel]={'rows':96,'supported':72,'guards':24,'occurrences':144,'repeated_rule_documents':12}
    _,_,excluded,expected_refs,source_refs,real_count=corpus.historical_inputs(inputs['manifest']['inputs']['prior_corpus']['path'])
    artifacts=inputs['manifest']['artifacts'];historical_refs=dict(expected_refs)
    expected_refs.update(condition_tuning={'reference':artifacts['new_tuning'],'representation':'annotated_single'},condition_document_tuning={'reference':artifacts['document_tuning_targets'],'representation':'document_clauses'})
    require(exposure['known_pool_references']==expected_refs,'historical pool ancestry differs')
    pools={name:historical_pool_rows(meta) for name,meta in expected_refs.items()};layouts={name:{role_layout(r) for r in rows} for name,rows in pools.items()}
    require(exposure['known_pool_counts']=={k:len(v) for k,v in pools.items()} and exposure['known_role_masked_layouts']=={k:sorted(v) for k,v in layouts.items()},'independent role layout inventory differs')
    layout_counts={}
    for kind,rows in (('single_rows',panels['fresh']),('document_clause_rows',docclauses['document_fresh'])):
        wanted=[]
        for row in rows:
            layout=role_layout(row);matches=sorted(k for k,v in layouts.items() if layout in v)
            wanted.append({'id':row['id'],'source_sha256':boundary.text_sha(row['source_text']),'role_masked_layout':layout,'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination'})
        require(exposure[kind]==wanted,'fresh role exposure payload differs');layout_counts[kind]=dict(Counter(r['layout_status'] for r in wanted))
    historical_meanings={digest(r['canonical_ir']) for name in historical_refs for r in pools[name] if 'canonical_ir' in r}
    known={normalize(t) for t in excluded};split=exposure['split_audit']
    require(not known&seen_sources and not historical_meanings&seen_meanings and exposure['new_overlap_count']==exposure['historical_meaning_overlap']==0 and exposure['prior_source_inputs']==source_refs and exposure['real_exposed_views']==real_count==86,'historical exclusion differs')
    require(split==inputs['manifest']['split_audit'] and split['unique_sources_including_document_clauses']==len(seen_sources) and split['case_groups']==len(seen_cases) and all(split[k]==0 for k in ('source_overlap','meaning_overlap','case_overlap','added_fitting_rows')),'independent split audit differs')
    return {'panels':audits,'layout_counts':layout_counts,'known_unique_normalized_sources':len(known),'source_overlap':0,'meaning_overlap':0,'new_fitting_rows':0,'independent_statutory_gold_count':0,'universal_layout_novelty_claimed':False}


def verify_candidate_choice(pin,joint,clause,scope,training,scope_audit):
    value=read_ref(pin)
    require(value['choice_frozen_before_fresh_reference_release'] is True and value['fresh_results_used_for_choice'] is False and value['clause_generation']==joint['clause_generation'] and value['boundary_generation']==joint['boundary_generation'],'pre-reference candidate choice binding differs')
    require(len(value['choices'])==2 and {r['architecture'] for r in value['choices']}==set(ARCHITECTURES),'two primary clause choices required')
    models={m['name']:m for m in clause['models']}
    for choice in value['choices']:
        eligible=[t for t in training['trials'] if t['architecture']==choice['architecture'] and t['selection']=='candidate']
        if eligible:
            best=sorted(eligible,key=lambda t:t['name'])[0]
            for t in sorted(eligible,key=lambda t:t['name']):
                rank=lambda v:clause_ranking({'steps':v['selected_steps'],**next(s['tuning'] for s in v['stages'] if s['additional_steps_after']==v['selected_steps'])})
                if rank(t)>rank(best):best=t
            wanted=models[best['name']]
        else:wanted=models['parent_'+choice['architecture']+'-1730']
        require(all(choice[k]==wanted[k] for k in ('name','architecture','checkpoint','decoder_kind','selected_steps','selection')),'primary clause choice differs from admitted tuning ranking')
    eligible=[m for m in scope['models'] if m['selection']=='candidate']
    if not eligible:require(value['boundary_choice']==scope['models'][0],'boundary fallback choice differs')
    else:
        trials={t['name']:t for t in read_ref(scope['selections'])['trials']}
        def rank(m):
            scores=next(s['metrics'] for s in trials[m['name']]['stages'] if s['steps']==m['selected_steps'])
            return (scores['scope_new']['raw_supported_scope_correct'],scores['scope_new']['exact_supported_segmentation'],sum(s['exact_supported_segmentation'] for p,s in scores.items() if p!='scope_new'),-m['selected_steps'])
        best=max(sorted(eligible,key=lambda m:m['name']),key=rank);require(value['boundary_choice']==best,'primary scope choice differs')
    return value


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as runner
    from scripts.ops.legal_ir import run_legal_scope_retention_experiment as scope_runner
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_scope_retention_annotations as scope_annotations
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three replay workers required')
    folder,output=Path(args.run_directory).resolve(),Path(args.output).resolve()
    frozen_ref=ref(folder/'generation-frozen.json');frozen=read_ref(frozen_ref)
    require(frozen['schema']==runner.JOINT_SCHEMA and frozen['all_training_selection_and_generation_complete'] is True and frozen['no_joint_stage_search'] is True and frozen['fresh_targets_opened'] is False,'complete independent selected-factor source generation freeze required')
    clause_ref,scope_ref=frozen['clause_generation'],frozen['boundary_generation'];clause,scope=read_ref(clause_ref),read_ref(scope_ref)
    plan,scope_plan=read_ref(clause['plan']),read_ref(scope['plan']);config=read_ref(plan['config']);scope_config=read_ref(scope_plan['config'])
    manifest=read_ref(config['condition_corpus_manifest']);scope_manifest=read_ref(scope_config['scope_corpus_manifest'])
    single_target_refs={'fresh':manifest['artifacts']['challenge_targets']};document_target_refs={'fresh_documents':manifest['artifacts']['document_challenge_targets']}
    evidence_refs={k:manifest['artifacts'][k] for k in ('annotation_ledger','exposure_audit','challenge_pairs')}
    scope_evidence_refs={k:scope_manifest['artifacts'][k] for k in ('fresh_targets','fresh_pairs','annotation_ledger','exposure_audit')}
    sealed=[*single_target_refs.values(),*document_target_refs.values(),*evidence_refs.values(),*scope_evidence_refs.values()]
    guard=SealedReadGuard(sealed);sys.addaudithook(guard.event)
    inputs=runner.load_config(plan['config']['path']);scope_inputs=scope_runner.read_config(scope_plan['config']['path'])
    require(read_ref(clause['sources'])==inputs['sources'] and read_ref(clause['document_sources'])==inputs['document_sources'] and read_ref(frozen['document_sources'])=={p:inputs['document_sources'][p] for p in DOCUMENT_COUNTS},'frozen source inventories differ')
    verify_protocol(plan,inputs,clause);inventory=verify_inventory(frozen,clause,scope,inputs)
    pins=dict(plan['producer_pins']);pins.update(scope_plan['producer_pins'])
    for module in (sys.modules[__name__],prior,runner,scope_runner,corpus,scope_annotations,runtime,retained,retained.prior,retained.calendar,retained.calendar_summary,retained.compose,boundary_qualification,clauses,boundary,previous,gate):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    require(all(sha(p)==h for p,h in pins.items()),'producer source drift')
    candidate_choice_ref=ref(args.candidate_choice);read_ref(candidate_choice_ref,parse=False)
    output.mkdir(parents=True,exist_ok=False)
    qualification_plan=write(output/'qualification-plan.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'clause_generation':clause_ref,'boundary_generation':scope_ref,'producer_pins':pins,'experimental_candidate_choice_before_reference_release':candidate_choice_ref,'routing_summary':ref(args.routing_summary),'identifier_invariance':ref(args.identifier_invariance),'sealed_references':sealed,'native_build_single_panel':'fresh','native_build_document_panel':'fresh_documents','fresh_single_build_slots':6,'fresh_document_build_slots':18,'fresh_reference_files_opened':False,'old_fresh_panels_are_admitted_retention':True})
    fitting=verify_fitting(inputs)
    jobs,training=verify_training(inputs,clause,read_ref(clause['selections']))
    scope_jobs,scope_audit=verify_scope_training(scope_inputs,scope);jobs+=scope_jobs
    identifier_audit=verify_identifier_receipt(ref(args.identifier_invariance),scope_ref,scope)
    idguard_ref=ref(Path(args.identifier_invariance).parent/'open-guard.json');idguard=read_ref(idguard_ref)
    require(idguard['receipt']==ref(args.identifier_invariance) and idguard['completed'] is True and idguard['new_sealed_files_opened'] is False and idguard['sealed_open_attempts']==[] and set(idguard['blocked_paths'])==guard.paths,'ID probe lacked complete sealed reference denial')
    identifier_audit['phase_open_audit']=idguard_ref
    verify_candidate_choice(candidate_choice_ref,frozen,clause,scope,training,scope_audit)
    training_ref=write(output/'training-and-selection-audit.json',{'schema':SCHEMA,'clause_selections':clause['selections'],'boundary_selections':scope['selections'],'fitting':fitting,**training,'scope_training':scope_audit,'identifier_invariance':identifier_audit,'clause_optimizer_updates':800,'boundary_optimizer_updates':800,'optimizer_trajectory_replayed':False,**FALSE})
    for name,head in inputs['boundary_heads'].items():
        for panel,pin in clause['boundaries'][name].items():jobs.append({'kind':'boundary','name':'clause-fixed-'+name+'/'+panel,'checkpoint':head['checkpoint'],'sources':inputs['document_sources'][panel],'generation':pin})
    singles,documents={},{}
    for model in frozen['models']:
        name=model['name'];singles[name]={}
        for panel,pin in frozen['files'][name].items():
            singles[name][panel]=read_ref(pin);require(len(singles[name][panel]['rows'])==SINGLE_COUNTS[panel],'selected single denominator differs')
            jobs.append({'kind':'single','name':name+'/'+panel,'model':model,'sources':inputs['sources'][panel],'generation':pin})
    for pipeline in frozen['pipelines']:
        name=pipeline['name'];documents[name]={}
        for panel,pin in frozen['document_files'][name].items():
            documents[name][panel]=read_ref(pin);require(len(documents[name][panel]['rows'])==96,'selected pipeline denominator differs')
            jobs.append({'kind':'document','name':name+'/'+panel,'model':pipeline,'sources':inputs['document_sources'][panel],'generation':pin,'boundary':frozen['boundaries'][pipeline['boundary_head']][panel]})
    require(sum(len(j['sources']) for j in jobs)==53124,'full saved output replay denominator differs')
    replays=[];groups=group_replay_jobs(jobs)
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn'),initializer=init_replay_worker,initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group,g) for g in groups]):replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==53124,'full saved payload replay missing')
    for i,left in enumerate(frozen['models']):
        for right in frozen['models'][i+1:]:
            if left['checkpoint']==right['checkpoint'] and left['decoder_kind']==right['decoder_kind']:
                require(singles[left['name']]==singles[right['name']],'same-checkpoint selected clause outputs differ')
                require(all(documents[left['name']+'__scope_'+p]==documents[right['name']+'__scope_'+p] for p in ('parent','control','target')),'duplicate clause policy outputs differ')
    # Reuse the frozen reference-free diagnostic contract with the current parent-generation pin.
    real_inputs={**inputs,'config':{**inputs['config'],'prior_facet_generation':inputs['config']['prior_temporal_generation']}}
    real_ref=write(output/'real-source-diagnostics.json',prior.real_diagnostics(real_inputs,frozen,singles,args.routing_summary))
    replay_ref=write(output/'replay-frozen.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'real_source_diagnostics':real_ref,'panels':sorted(replays,key=lambda r:r['name']),'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,'training_diagnostic_rows':sum(r['rows'] for r in replays if r['training_diagnostic']),**{kind+'_rows':sum(r['rows'] for r in replays if r['kind']==kind) for kind in ('single','document','boundary')},'saved_output_rows':53124,'additional_mining_and_teacher_rows':8160,'additional_identifier_probe_rows':576,'fresh_reference_files_opened':False,'old_fresh_retention_references_admitted':True,'reference_derived_fresh_layout_evidence_opened':False,**FALSE})
    single_selections, document_selections = {}, {}
    for model in frozen['models']:
        name = model['name']; sources = inputs['sources']['fresh']; predictions = singles[name]['fresh']['rows']
        selected = retained.calendar.select_candidates(sources, predictions, toolchain=args.toolchain, policy=retained.calendar.POLICY)
        lookup = {s['id']: (s, p) for s, p in zip(sources, predictions)}
        for entry in selected['rows']:
            retained.calendar_summary.verify_entry(*lookup[entry['candidate']['candidate_id']], entry)
        require(selected['source_count'] == len(selected['rows']) + len(selected['excluded']) == 192, 'fresh build selection dropped sources')
        single_selections[name] = selected
    build_document_panel = 'fresh_documents'
    for pipeline in frozen['pipelines']:
        name = pipeline['name']
        document_selections[name] = retained.document_selection(documents[name][build_document_panel]['rows'],
            inputs['document_sources'][build_document_panel], toolchain=args.toolchain)
    build_selection_ref = write(output / 'build-selection-frozen.json', {'schema': SCHEMA,
        'single': single_selections, 'document': document_selections, 'replay': replay_ref,
        'single_source_slots': 1152, 'document_source_slots': 1728,
        'document_panel': build_document_panel, 'document_panel_is_exposed_regression': False,
        'canonical_references_used_for_selection': False, 'fresh_targets_opened': False,
        'interpretation_policy': retained.calendar.POLICY})
    builds = {'single': {}, 'document': {}}
    for kind, selections in (('single', single_selections), ('document', document_selections)):
        for name, selected in selections.items():
            builds[kind][name] = retained.build_batches(selected['rows'], output / 'builds' / kind / name, args)
            print({'phase': 'built', 'kind': kind, 'model': name, 'supported_for_lowering': len(selected['rows'])}, flush=True)
    builds_ref = write(output / 'builds-frozen.json', {'schema': SCHEMA, **builds, 'selections': build_selection_ref,
        'replay': replay_ref, 'fresh_reference_files_opened': False, 'old_fresh_retention_references_admitted': True,
        'reference_derived_layout_evidence_opened': False, **FALSE})
    verify_candidate_choice(candidate_choice_ref,frozen,clause,scope,training,scope_audit)
    require(not guard.events,'sealed fresh reference read attempted before build freeze')
    guard.released=True
    print({'phase':'references_released_after_build_freeze','builds':builds_ref},flush=True)
    single_targets={'tuning_'+p:inputs['tuning'][p] for p in TUNING}
    single_targets.update({'retention_'+p:inputs['retention_targets'][p] for p in ('facet','temporal')})
    single_targets['fresh']=previous.reference_rows(read_ref(single_target_refs['fresh']),inputs['sources']['fresh'])
    document_targets={p:inputs[p] for p in DOCUMENT_TUNING};document_targets['fresh_documents']=read_ref(document_target_refs['fresh_documents'])
    require(clauses.source_rows(document_targets['fresh_documents'])==inputs['document_sources']['fresh_documents'],'fresh document source binding differs')
    evidence={k:read_ref(pin) for k,pin in evidence_refs.items()};scope_evidence={k:read_ref(pin) for k,pin in scope_evidence_refs.items()}
    exposure_ref=write(output/'authored-exposure-audit.json',audit_exposure(inputs,single_targets,document_targets,evidence))
    scoped_inputs={**scope_inputs,'tuning_pairs':read_ref(scope_manifest['artifacts']['tuning_pairs'])}
    scope_exposure_ref=write(output/'scope-exposure-audit.json',scope_annotations.audit_scope_annotations(scoped_inputs,scope_evidence['fresh_targets'],scope_evidence['fresh_pairs'],scope_evidence['annotation_ledger'],scope_evidence['exposure_audit']))
    scope_targets={**scope_inputs['tuning'],'scope_fresh':scope_evidence['fresh_targets'],'root_condition_fresh_documents':document_targets['fresh_documents']}
    require(set(scope_targets)==set(scope_inputs['sources']),'all scope reference/source panels required')
    scope_metrics_all={name:{panel:scope_metrics(read_ref(pin),scope_inputs['sources'][panel],scope_targets[panel]) for panel,pin in panels.items()} for name,panels in scope['files'].items()}
    boundary_metrics={name:{panel:boundary_qualification.score_boundaries(read_ref(pin),inputs['document_sources'][panel],document_targets[panel]) for panel,pin in panels.items()} for name,panels in frozen['boundaries'].items()}
    single_metrics,document_metrics,model_reports,pipeline_reports={},{},[],[]
    for model in frozen['models']:
        name=model['name'];single_metrics[name]={panel:single_error_metrics(value,inputs['sources'][panel],single_targets[panel],enabled=model['enabled']) for panel,value in singles[name].items() if panel!='real_exposed'}
        for panel in ('fresh','retention_facet','retention_temporal','tuning_condition'):
            single_metrics[name][panel]['condition_temporal_strata']=clause_strata(singles[name][panel],inputs['sources'][panel],single_targets[panel])
        exact={r['id']:r['exact'] for r in single_metrics[name]['fresh']['rows']}
        metric=retained.prior.build_accounting(single_selections[name],builds['single'][name],exact)
        model_reports.append({**model,'single_metrics':{p:{k:v for k,v in result.items() if k not in ('rows','error_rows','condition_temporal_strata')} for p,result in single_metrics[name].items()},'single_builds':metric,'real_source_diagnostics':real_ref})
    for pipeline in frozen['pipelines']:
        name=pipeline['name'];document_metrics[name]={}
        for panel,generation in documents[name].items():
            b=boundary_metrics[pipeline['boundary_head']][panel]
            if panel==build_document_panel:
                metric=boundary_qualification.pipeline_funnel(generation,b,inputs['document_sources'][panel],document_targets[panel],document_selections[name],builds['document'][name])
            else:
                measured=retained.score_documents(generation,inputs['document_sources'][panel],document_targets[panel]);references={r['candidate_id']:r for r in document_targets[panel]};bs={r['id']:r for r in b['rows']}
                rows=[boundary_qualification.attribution.pipeline_record(r,references[r['candidate_id']],bs[r['candidate_id']]) for r in generation['rows']]
                metric={'metrics':{k:v for k,v in measured.items() if k!='rows'},'rows':rows,'attribution':boundary_qualification.attribution.pipeline_counts(rows),'native_build_not_executed_on_this_panel':True,'explicitly_admitted_retention_panel':True}
            document_metrics[name][panel]=metric
        pipeline_reports.append({**pipeline,'panels':{panel:{k:v for k,v in value.items() if k!='rows'} for panel,value in document_metrics[name].items()}})
    single_totals={m['arm']:{'panels':{p:{k:m['single_metrics'][p][k] for k in ('count','decoded','abstained','exact')} for p in SINGLE_COUNTS if p!='real_exposed'},'builds':{k:m['single_builds'][k] for k in ('count','built','built_exact','built_reference_mismatch','build_invocations')}} for m in model_reports}
    document_totals={p['arm']:{'panels':{panel:{k:p['panels'][panel]['metrics'][k] for k in ('count','supported','unsupported','composed','abstained','exact','decision_exact','canonical_rule_list_exact','occurrence_boundaries_exact','unsupported_accepted')} for panel in DOCUMENT_COUNTS},'builds':p['panels']['fresh_documents']['builds']} for p in pipeline_reports}
    details_ref=write(output/'scored-details.json',{'single':single_metrics,'document':document_metrics,'boundary':boundary_metrics,'scope':scope_metrics_all})
    require(all(sha(path)==wanted for path,wanted in pins.items()),'qualifier/producer source drift')
    require(runner.load_config(plan['config']['path'])==inputs and scope_runner.read_config(scope_plan['config']['path'])==scope_inputs,'frozen input closure changed')
    for pin in (frozen_ref,clause_ref,scope_ref,*sealed,candidate_choice_ref):read_ref(pin,parse=False)
    opens_ref=write(output/'phase-open-audit.json',{'schema':SCHEMA,'sealed_paths':sorted(guard.paths),'events':guard.events,'before_build_freeze_attempts':sum(not r['after_build_freeze'] for r in guard.events),'build_freeze':builds_ref,'all_new_reference_reads_after_build_freeze':True,'replay_workers_had_same_nine_file_OS_open_denial':True,'old_fresh_references_were_admitted_retention':True,'source_identifier_label_exposure_disclosed':True})
    result={'schema':SCHEMA,'qualification_plan':qualification_plan,'generation_freeze':frozen_ref,'clause_generation':clause_ref,'boundary_generation':scope_ref,'training_and_selection_audit':training_ref,'replay':replay_ref,'builds':builds_ref,'details':details_ref,'authored_exposure_audit':exposure_ref,'scope_exposure_audit':scope_exposure_ref,'phase_open_audit':opens_ref,'real_source_diagnostics':real_ref,'identifier_invariance':identifier_audit,'experimental_candidate_choice_before_reference_release':candidate_choice_ref,'reference_single':single_target_refs,'reference_documents':document_target_refs,'posthoc_evidence':evidence_refs,'scope_posthoc_evidence':scope_evidence_refs,'models':model_reports,'pipelines':pipeline_reports,'single_totals':single_totals,'document_totals':document_totals,'scope_fresh_metrics':{name:panels['scope_fresh']['metrics'] for name,panels in scope_metrics_all.items()},'producer_pins':pins,'parent_fallbacks':clause['parent_fallbacks'],'boundary_fallbacks':[m['name'] for m in scope['models'] if m['selection'].startswith('parent_fallback')],'executed_optimizer_updates':800,'boundary_optimizer_updates':800,'inventory':inventory,'single_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='single'),'document_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='document'),'boundary_source_documents_replayed':sum(r['rows'] for r in replays if r['kind']=='boundary'),'clause_occurrences_replayed':sum(r.get('clause_occurrences_replayed',0) for r in replays),'independent_mining_and_teacher_source_evaluations':8160,'additional_identifier_probe_evaluations':576,'actual_lake_build_invocations':sum(b['backend_executed'] for selections in builds.values() for batches in selections.values() for b in batches),'build_attempts':sum(len(batches) for selections in builds.values() for batches in selections.values()),'native_single_build_slots':6,'native_fresh_document_build_slots':18,'document_build_panel':'fresh_documents','new_document_holdout_available':True,'fresh_reference_files_opened_after_replay_and_build_freezes':True,'reference_derived_novelty_evidence_opened_after_build_freeze':True,'test_results_used_for_selection_or_gate_revision':False,'real_reference_accuracy_available':False,'scope':'Two independently selected factors; matched clause objectives and scope objectives; fixed selected/fallback6x3 crossing. One fixed seed, no seed replication. Former fresh panels are admitted retention. Scope source IDs expose authored classes;576 opaque-ID probes preserve complete outputs but do not establish blind metadata. Scope heading-family training covers dash headings only. Authored exactness, native compilation and unmeasured statutory fidelity are separate.',**FALSE}
    write(output/'summary.json',result);print({'complete':str(output/'summary.json'),'single_totals':single_totals,'document_totals':document_totals},flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--routing-summary',required=True);parser.add_argument('--candidate-choice',required=True)
    parser.add_argument('--identifier-invariance',required=True);parser.add_argument('--lake-executable',required=True)
    parser.add_argument('--toolchain',default='leanprover/lean4:v4.34.1');parser.add_argument('--workers',type=int,default=3)
    run(parser.parse_args())
