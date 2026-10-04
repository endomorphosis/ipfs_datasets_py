#!/usr/bin/env python3
"""Independent atom-boundary loss, source-retention and qualification checks.

Original-parent gates are distinct from warm-start initialization. The latter
is an unqualified research checkpoint. Fresh references are not selection data.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
import random
import sys
from concurrent.futures import ProcessPoolExecutor,as_completed
import multiprocessing
import argparse

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import summarize_legal_heading_boundary_experiment as heading

require,digest,read_ref,ref,write,sha=(getattr(heading,k) for k in ('require','digest','read_ref','ref','write','sha'))
boundary,clauses=heading.boundary,heading.clauses
prior,retained,previous=heading.prior,heading.retained,heading.previous
boundary_qualification=heading.boundary_qualification
scope_metrics=heading.scope_metrics
audited_scope_metric=heading.audited_scope_metric
verify_frozen_scope_outputs=heading.verify_frozen_scope_outputs
CLAUSE_PARENTS=heading.CLAUSE_PARENTS
SealedReadGuard=heading.SealedReadGuard
FALSE=heading.FALSE
DOCUMENT_COUNTS={'atom_fresh':192,'prior_heading_fresh':192,'root_condition_fresh_documents':96}
HEAD_NAMES=('parent',*('continuation','atom_rehearsal','distill'),'warm_start','continuation_final400','atom_rehearsal_final400','distill_final400')
SCHEMA='legal-atom-boundary-independent-qualification/v1'
ARMS=('continuation','atom_rehearsal','distill')
STAGES=(100,200,400)
SEED=1730
ORIGINAL_PARENT_SHA='e741578ac017e163588c6b49a16f6bca9dd0a37e71a0c345a3c9706814c3cf99'
WARM_PARENT_SHA='63879904bdce7edb2717ca9a2d1a05569b5c2c6332d27bfcb250b9ed64ae3fba'
METRIC_KEYS={'count','supported','unsupported','raw_supported_correct','raw_unsupported_accepted','raw_boundary_exact','supported_exact','unsupported_accepted'}


def atom_role_masks(row,annotation):
    """Bind all-token interior masks to exact canonical TRAIN atom occurrences."""
    tokens=boundary.tokenize(row['source_text']);require(type(row['supported']) is bool,'explicit supported TRAIN profile required')
    if not row['supported']:
        require(annotation is None,'unsupported source has no flat atom supervision')
        return [False]*len(tokens),[False]*len(tokens)
    keys={'candidate_id','source_sha256','inter_clause_end_token_indices','atom_interior_negative_token_indices','atom_spans','provenance'}
    require(type(annotation) is dict and set(annotation)==keys and annotation['candidate_id']==row['candidate_id'] and annotation['source_sha256']==row['source_sha256']==boundary.text_sha(row['source_text']),'closed source-bound TRAIN atom annotation required')
    require(annotation['provenance']=='pinned_supported_train_atoms_and_inter_clause_endpoints/v1','direct authored atom/endpoint provenance required')
    endpoints={c['char_end'] for c in row['clauses']};positive=[i for i,t in enumerate(tokens) if t['char_end'] in endpoints]
    require(len(positive)==len(endpoints)==len(row['clauses']) and positive[-1]==len(tokens)-1,'complete token-aligned TRAIN endpoints required')
    expected=[]
    for clause in row['clauses']:
        left,right=clause['char_start'],clause['char_end'];text=row['source_text'][left:right];rule=clause['rule']
        for kind,values in (('actor',[rule['actor']]),('temporal',rule['temporal']),('exceptions',rule['exceptions'])):
            require(type(values) is list and len(values)<=1,'flat zero-or-one canonical atom per field required')
            for literal in values:
                require(type(literal) is str and literal,'nonempty canonical atom literal required')
                matches=[m.span() for m in re.finditer(re.escape(literal),text)]
                require(len(matches)==1,'canonical TRAIN atom must have one unambiguous exact occurrence per clause')
                start,end=matches[0];expected.append({'kind':kind,'char_start':left+start,'char_end':left+end})
    expected.sort(key=lambda s:(s['char_start'],s['char_end'],s['kind']))
    require(all(a['char_end']<=b['char_start'] for a,b in zip(expected,expected[1:])),'canonical atom role intervals overlap')
    require(annotation['atom_spans']==expected and all(set(s)=={'kind','char_start','char_end'} and type(s['char_start']) is type(s['char_end']) is int for s in annotation['atom_spans']),'atom masks changed role, literal, scope or authoritative source coordinates')
    interior=[i for i,t in enumerate(tokens) if i not in positive and any(s['char_start']<=t['char_start']<t['char_end']<=s['char_end'] for s in expected)]
    transition=positive[:-1]
    require(annotation['inter_clause_end_token_indices']==transition and annotation['atom_interior_negative_token_indices']==interior,'inter-clause/ALL-interior-token coverage differs from source atoms')
    return [i in transition for i in range(len(tokens))],[i in interior for i in range(len(tokens))]


def teacher_kl_oracle(torch,logits,labels,valid_mask,supported,teacher_logits):
    """Bernoulli exponential-family identity, independently of runtime logsigmoid."""
    require(logits.ndim==2 and logits.shape==labels.shape==valid_mask.shape==teacher_logits.shape and supported.ndim==1 and len(supported)==len(logits),'complete candidate/teacher token shapes required')
    require(logits.is_floating_point() and teacher_logits.dtype==logits.dtype and teacher_logits.device==logits.device and bool(torch.isfinite(logits).all()) and bool(torch.isfinite(teacher_logits).all()),'finite same-type candidate/teacher logits required')
    require(bool(torch.isfinite(labels).all()) and bool(((labels==0)|(labels==1)).all()) and valid_mask.dtype==torch.bool and supported.dtype in (torch.bool,torch.long) and bool(((supported==0)|(supported==1)).all()),'binary TRAIN labels and exact validity required')
    teacher=teacher_logits.detach();eligible=valid_mask&supported.bool()[:,None]
    correct=eligible&((teacher>=0)==labels.bool());positive=correct&labels.bool();negative=correct&~labels.bool()
    # KL(Ber(sigmoid(t)) || Ber(sigmoid(s))) = p(t)*(t-s)+A(s)-A(t).
    partition=lambda x:torch.logsumexp(torch.stack((torch.zeros_like(x),x)),dim=0)
    token_kl=torch.sigmoid(teacher)*(teacher-logits)+partition(logits)-partition(teacher)
    counts=[int(positive.sum()),int(negative.sum())];sums=[token_kl[positive].sum(),token_kl[negative].sum()]
    zero=logits.sum()*0.;means=[value/count if count else zero for value,count in zip(sums,counts,strict=True)]
    available=sum(n>0 for n in counts);kl=sum(means)/available if available else zero
    return kl,{'teacher_correct_count':sum(counts),'teacher_correct_positive_count':counts[0],'teacher_correct_negative_count':counts[1],
        'teacher_available_class_count':available,'teacher_positive_kl_sum':sums[0],'teacher_negative_kl_sum':sums[1],
        'teacher_positive_kl_mean':means[0],'teacher_negative_kl_mean':means[1],'teacher_kl':kl,
        'teacher_correct_mask':correct,'teacher_positive_mask':positive,'teacher_negative_mask':negative,
        'teacher_empty_mask':available==0}


def atom_loss_oracle(torch,logits,labels,valid_mask,supported,positive_mask,negative_mask,transition_mask,atom_mask,*,teacher_logits,arm):
    require(arm in ARMS,'declared atom-boundary arm required')
    common,parts=heading.boundary_loss_oracle(torch,logits,labels,valid_mask,supported,positive_mask,negative_mask,'rehearsal')
    require(transition_mask.shape==atom_mask.shape==logits.shape and transition_mask.dtype==atom_mask.dtype==torch.bool,'complete boolean transition/atom masks required')
    lengths=valid_mask.sum(1);positions=torch.arange(logits.shape[1],device=logits.device)[None,:]
    require(torch.equal(valid_mask,positions<lengths[:,None]),'contiguous real-token validity required')
    expected_transition=positive_mask&(positions!=lengths[:,None]-1)
    require(torch.equal(transition_mask,expected_transition),'all and only nonterminal clause ends enter atom positives')
    eligible=valid_mask&supported.bool()[:,None]
    require(not bool((atom_mask&(~eligible|labels.bool())).any()) and bool(atom_mask.any()) and bool(transition_mask.any()),'both atom roles required without unsupported, padding or gold-end negatives')
    partition=lambda x:torch.logsumexp(torch.stack((torch.zeros_like(x),x)),dim=0)
    transition=partition(-logits[transition_mask]);interior=partition(logits[atom_mask]);auxiliary=.5*(transition.mean()+interior.mean())
    kl,teacher_parts=teacher_kl_oracle(torch,logits,labels,valid_mask,supported,teacher_logits)
    atom_weight=0. if arm=='continuation' else .5;teacher_weight=.25 if arm=='distill' else 0.
    total=common+atom_weight*auxiliary+teacher_weight*kl
    return total,{**parts,'heading_objective':common,'atom_positive_count':int(transition_mask.sum()),'atom_negative_count':int(atom_mask.sum()),
        'atom_positive_bce_sum':transition.sum(),'atom_negative_bce_sum':interior.sum(),
        'atom_positive_bce_mean':transition.mean(),'atom_negative_bce_mean':interior.mean(),'balanced_atom_bce':auxiliary,
        'atom_auxiliary_weight':atom_weight,'weighted_atom_bce':atom_weight*auxiliary,**teacher_parts,
        'teacher_kl_weight':teacher_weight,'weighted_teacher_kl':teacher_weight*kl,'total_loss':total}


def verify_loss_receipt(record,rows,heading_roles,atom_roles,*,teacher_logits,arm,loss):
    """Actual-batch teacher provenance is supplied by a separate frozen forward."""
    import torch
    require(len(rows)==12 and all(r['supported'] is True for r in rows),'exact twelve supported TRAIN sources required')
    lengths=[len(boundary.tokenize(r['source_text'])) for r in rows];width=max(lengths)
    labels=[];positive=[];editorial=[];transition=[];interior=[];valid=[]
    for row,length in zip(rows,lengths,strict=True):
        y,p,e=heading.training_role_masks(row,heading_roles[row['candidate_id']]);t,a=atom_role_masks(row,atom_roles[row['candidate_id']]);pad=width-length
        labels.append(y+[0.]*pad);positive.append(p+[False]*pad);editorial.append(e+[False]*pad)
        transition.append(t+[False]*pad);interior.append(a+[False]*pad);valid.append([True]*length+[False]*pad)
    expected={'labels':labels,'valid_mask':valid,'supported':[True]*12,'positive_mask':positive,'negative_mask':editorial,'transition_mask':transition,'atom_mask':interior}
    for key,wanted in expected.items():
        require(record[key]==wanted,'receipt role mask/label differs from authoritative TRAIN sources: '+key)
        if key!='labels':
            values=record[key] if key=='supported' else [v for row in record[key] for v in row]
            require(all(type(v) is bool for v in values),'exact boolean receipt masks required')
    logits=record['candidate_logits'];saved=record['objective_components']
    require(len(logits)==12 and len(teacher_logits)==12 and all(len(row)==width and all(type(v) in (int,float) and math.isfinite(v) for v in row) for values in (logits,teacher_logits) for row in values),'finite complete candidate/original-parent logits required')
    require(saved['teacher_token_logits']==teacher_logits and saved['teacher_token_logits_sha256']==digest(teacher_logits),'saved teacher does not match independently recomputed original-parent TRAIN batch')
    x=torch.tensor(logits,dtype=torch.float64);y=torch.tensor(labels,dtype=torch.float64);v=torch.tensor(valid);s=torch.ones(12,dtype=torch.bool)
    p,e,t,a=[torch.tensor(value) for value in (positive,editorial,transition,interior)];teacher=torch.tensor(teacher_logits,dtype=torch.float64)
    total,oracle=atom_loss_oracle(torch,x,y,v,s,p,e,t,a,teacher_logits=teacher,arm=arm)
    def close(value,wanted,key):
        require(type(value) in (int,float) and math.isfinite(value) and math.isclose(value,float(wanted),rel_tol=2e-5,abs_tol=3e-6),'independent atom/teacher objective arithmetic differs: '+key)
    for key,wanted in oracle.items():
        if torch.is_tensor(wanted) and wanted.ndim>0:require(saved[key]==wanted.tolist(),'teacher correctness mask differs: '+key)
        elif type(wanted) in (int,bool):require(type(saved[key]) is type(wanted) and saved[key]==wanted,'objective count/flag differs: '+key)
        else:close(saved[key],wanted,key)
    exact={'supported_documents':12,'unsupported_documents':0,'padding_token_count':sum(width-n for n in lengths),'excluded_unsupported_token_count':0,
        'positive_weight':12.,'unsupported_token_supervision':False,'teacher_logits_detached':True,'teacher_kl_temperature':1.,
        'teacher_kl_positive_weighted':False,'teacher_class_average':'available_gold_classes',
        'eligible_mask_sha256':digest(valid),'positive_mask_sha256':digest(positive),'negative_mask_sha256':digest(editorial),
        'transition_mask_sha256':digest(transition),'atom_mask_sha256':digest(interior)}
    require(all(type(saved[k]) is type(wanted) and saved[k]==wanted for k,wanted in exact.items()),'source-role/teacher provenance or objective protocol differs')
    close(record['total_loss'],total,'record_total');close(loss,total,'loss_trace')
    return True


def matched_batches(supported_replay,supported_heading,atom_pairs,*,steps=400):
    require(type(steps) is int and 1<=steps<=400 and supported_replay and supported_heading and atom_pairs,'bounded complete matched schedule required')
    require(all(r['supported'] is True for r in supported_replay+supported_heading),'unsupported source cannot enter endpoint training')
    require(all(set(pair)=={'pair_id','forward_id','rotated_id','local_clause_body_sha256'} and pair['forward_id']!=pair['rotated_id'] for pair in atom_pairs),'complete declared rotation-pair inventory required')
    all_ids=[r['candidate_id'] for r in supported_replay+supported_heading]+[pair[k] for pair in atom_pairs for k in ('forward_id','rotated_id')]
    require(len(all_ids)==len(set(all_ids)),'source memberships across sampling pools must be disjoint')
    def stream(values,seed):
        rng=random.Random(seed)
        while True:
            order=list(range(len(values)));rng.shuffle(order)
            for i in order:yield values[i]
    replay=stream(supported_replay,1730);heading_pool=stream(supported_heading,1731);paired=stream(atom_pairs,1732);receipts=[]
    for step in range(1,steps+1):
        left=[next(replay) for _ in range(4)];middle=[next(heading_pool) for _ in range(4)];pairs=[next(paired) for _ in range(2)]
        receipts.append({'steps':step,'common_replay_ids':[r['candidate_id'] for r in left],'heading_ids':[r['candidate_id'] for r in middle],
            'atom_pair_ids':[pair['pair_id'] for pair in pairs],'atom_ids':[pair[k] for pair in pairs for k in ('forward_id','rotated_id')],
            'supported_count':12,'unsupported_count':0})
    return receipts


def validate_metric(metric):
    require(type(metric) is dict and set(metric)==METRIC_KEYS and all(type(v) is int and v>=0 for v in metric.values()),'closed nonnegative integer boundary metrics required')
    require(metric['count']==metric['supported']+metric['unsupported'] and all(metric[k]<=metric['supported'] for k in ('raw_supported_correct','raw_boundary_exact','supported_exact')) and all(metric[k]<=metric['unsupported'] for k in ('raw_unsupported_accepted','unsupported_accepted')),'complete metric denominators required')
    require(metric['supported_exact']<=min(metric['raw_boundary_exact'],metric['raw_supported_correct']) and metric['unsupported_accepted']<=metric['raw_unsupported_accepted'],'delivered boundary result cannot exceed raw endpoint/scope eligibility')


def churn_from_scored_rows(parent_rows,candidate_rows):
    """Complete source partitions; counts cannot conceal exchanged failures."""
    a={r['id']:r for r in parent_rows};b={r['id']:r for r in candidate_rows}
    require(len(a)==len(parent_rows)==len(b)==len(candidate_rows) and set(a)==set(b),'unique identical source inventory required for churn')
    for identity,old in a.items():
        new=b[identity]
        require(type(old['supported']) is type(new['supported']) is bool and old['supported']==new['supported'] and old['source_sha256']==new['source_sha256'],'churn source hash or reference class changed')
        for row in (old,new):
            require(all(type(row[k]) is bool for k in ('raw_interval_exact','delivered_interval_exact')),'explicit supported exactness flags required')
            require((row['status']=='segmented') is (row['delivered_intervals'] is not None),'churn accepted status/source plan disagreement')
            require(not row['delivered_interval_exact'] or row['supported'] and row['raw_interval_exact'] and row['delivered_intervals'] is not None,'delivered exactness is inconsistent')
            require(row['supported'] or not row['raw_interval_exact'] and not row['delivered_interval_exact'],'unsupported source cannot have invented flat endpoint gold')
    supported={k for k,v in a.items() if v['supported']};unsupported=set(a)-supported
    result={'count':len(a),'supported_ids':sorted(supported),'unsupported_ids':sorted(unsupported)}
    for key,field in (('raw_supported','raw_interval_exact'),('delivered_supported','delivered_interval_exact')):
        old={k for k in supported if a[k][field]};new={k for k in supported if b[k][field]}
        result[key]={'parent_exact':len(old),'candidate_exact':len(new),'won_ids':sorted(new-old),'lost_ids':sorted(old-new),
            'retained_exact_ids':sorted(old&new),'retained_inexact_ids':sorted(supported-(old|new)),'net_change':len(new)-len(old)}
    old={k for k in unsupported if a[k]['delivered_intervals'] is not None};new={k for k in unsupported if b[k]['delivered_intervals'] is not None}
    result['unsupported']={'parent_accepted_ids':sorted(old),'candidate_accepted_ids':sorted(new),'newly_accepted_ids':sorted(new-old),
        'newly_rejected_ids':sorted(old-new),'retained_accepted_ids':sorted(old&new),'retained_rejected_ids':sorted(unsupported-(old|new)),
        'no_new_acceptances':new<=old,'count_change':len(new)-len(old)}
    return result


def boundary_source_churn(parent_generation,candidate_generation,sources,targets):
    heading.verify_frozen_scope_outputs(parent_generation,candidate_generation)
    parent=heading.scope_metrics(parent_generation,sources,targets);candidate=heading.scope_metrics(candidate_generation,sources,targets)
    return {'parent_metrics':parent['metrics'],'candidate_metrics':candidate['metrics'],
        'churn':churn_from_scored_rows(parent['details']['rows'],candidate['details']['rows']),
        'all_source_scope_outputs_exact':True}


def validate_churn(churn,parent,candidate):
    validate_metric(parent);validate_metric(candidate)
    require(all(candidate[k]==parent[k] for k in ('count','supported','unsupported')),'candidate source/class denominator changed')
    supported=set(churn['supported_ids']);unsupported=set(churn['unsupported_ids'])
    require(len(supported)==len(churn['supported_ids'])==parent['supported'] and len(unsupported)==len(churn['unsupported_ids'])==parent['unsupported'] and not supported&unsupported and churn['count']==parent['count'],'source churn membership differs from metric denominator')
    for name,field in (('raw_supported','raw_boundary_exact'),('delivered_supported','supported_exact')):
        part=churn[name];keys=('won_ids','lost_ids','retained_exact_ids','retained_inexact_ids');groups=[set(part[k]) for k in keys]
        require(all(len(g)==len(part[k]) for k,g in zip(keys,groups,strict=True)) and sum(map(len,groups))==len(supported) and set.union(*groups)==supported,'supported churn partitions missing, duplicated or overlapping')
        won,lost,retained,_=groups
        require(part['parent_exact']==parent[field]==len(lost)+len(retained) and part['candidate_exact']==candidate[field]==len(won)+len(retained) and part['net_change']==candidate[field]-parent[field]==len(won)-len(lost),'supported count retention and source churn disagree')
    part=churn['unsupported'];old=set(part['parent_accepted_ids']);new=set(part['candidate_accepted_ids'])
    require(old<=unsupported and new<=unsupported and len(old)==len(part['parent_accepted_ids'])==parent['unsupported_accepted'] and len(new)==len(part['candidate_accepted_ids'])==candidate['unsupported_accepted'],'unsupported accepted identities differ from complete boundary metrics')
    for key,wanted in (('newly_accepted_ids',new-old),('newly_rejected_ids',old-new),('retained_accepted_ids',old&new),('retained_rejected_ids',unsupported-(old|new))):
        require(part[key]==sorted(wanted),'unsupported per-source churn receipt differs')
    require(part['no_new_acceptances'] is (new<=old) and part['count_change']==len(new)-len(old),'unsupported subset/count claim differs')


def boundary_choice(stages,parent_metrics,*,new_panel='atom_new'):
    require([s['steps'] for s in stages]==list(STAGES) and new_panel in parent_metrics,'complete declared stages and new tuning panel required')
    for metric in parent_metrics.values():validate_metric(metric)
    eligible=[]
    for stage in stages:
        require(set(stage['metrics'])==set(stage['churn'])==set(parent_metrics) and type(stage['raw_scope_logits_unchanged']) is bool,'every admitted source panel and exact scope flag required')
        valid=stage['raw_scope_logits_unchanged']
        for panel,parent in parent_metrics.items():
            value=stage['metrics'][panel];churn=stage['churn'][panel];validate_churn(churn,parent,value)
            valid &= value['raw_boundary_exact']>=parent['raw_boundary_exact'] and value['supported_exact']>=parent['supported_exact'] and value['unsupported_accepted']<=parent['unsupported_accepted'] and churn['unsupported']['no_new_acceptances'] and all(value[k]==parent[k] for k in ('raw_supported_correct','raw_unsupported_accepted'))
        valid &= stage['metrics'][new_panel]['raw_boundary_exact']>parent_metrics[new_panel]['raw_boundary_exact']
        if valid:eligible.append(stage)
    def rank(stage):
        metrics=stage['metrics'];return (metrics[new_panel]['raw_boundary_exact'],metrics[new_panel]['supported_exact'],sum(m['raw_boundary_exact'] for p,m in metrics.items() if p!=new_panel),-stage['steps'])
    return max(eligible,key=rank) if eligible else None


def runner_churn(churn):
    return {'parent_unsupported_ids':churn['unsupported']['parent_accepted_ids'],'candidate_unsupported_ids':churn['unsupported']['candidate_accepted_ids'],
        'new_unsupported_ids':churn['unsupported']['newly_accepted_ids'],'removed_unsupported_ids':churn['unsupported']['newly_rejected_ids'],
        'supported_raw_wins':churn['raw_supported']['won_ids'],'supported_raw_losses':churn['raw_supported']['lost_ids'],
        'supported_delivered_wins':churn['delivered_supported']['won_ids'],'supported_delivered_losses':churn['delivered_supported']['lost_ids']}


def verify_rotation_pairs(rows,pairs):
    require(len(rows)==144 and len(pairs)==72 and len({r['candidate_id'] for r in rows})==144 and all(r['supported'] is True for r in rows),'all144 supported rotation sources required')
    lookup={r['candidate_id']:r for r in rows};seen=set();identities=set()
    for pair in pairs:
        require(set(pair)=={'pair_id','forward_id','rotated_id','local_clause_body_sha256'} and pair['pair_id'] not in identities,'closed unique rotation pair required');identities.add(pair['pair_id'])
        ids=[pair['forward_id'],pair['rotated_id']];require(len(set(ids))==2 and all(i in lookup and i not in seen for i in ids),'complete disjoint rotation pair members required')
        forward,rotated=[lookup[i] for i in ids];bodies=[];rules=[]
        for row in (forward,rotated):
            texts=[row['source_text'][c['char_start']:c['char_end']] for c in row['clauses']]
            require(all(text.endswith('.') for text in texts),'declared TRAIN clause terminal punctuation required')
            bodies.append([boundary.text_sha(text[:-1]) for text in texts]);rules.append([c['rule'] for c in row['clauses']])
        require(bodies[0]==pair['local_clause_body_sha256'] and bodies[1]==bodies[0][-1:]+bodies[0][:-1] and rules[1]==rules[0][-1:]+rules[0][:-1],'rotation changed a local source body or canonical rule')
        seen.update(ids)
    require(seen==set(lookup),'rotation inventory dropped sources')
    return {'pairs':72,'documents':144,'same_local_bodies_last_first_rotation':True}


def verify_fitting(inputs):
    from scripts.ops.legal_ir import run_legal_heading_boundary_experiment as old_runner
    manifest=inputs['manifest'];old=read_ref(manifest['inputs']['prior_heading_corpus'])
    prior_generation=read_ref(inputs['config']['prior_generation']);old_plan=read_ref(prior_generation['plan']);old_inputs=old_runner.read_config(old_plan['config']['path'])
    require(old_inputs['manifest']==old and inputs['replay']==old_inputs['replay'] and inputs['new_train']==old_inputs['new_train'],'complete1152 historical TRAIN source/order commitment differs')
    inherited=heading.verify_fitting(old_inputs)
    require(manifest['replay_references']==old['replay_references'] and all(manifest['artifacts'][k]==old['artifacts'][k] for k in ('new_training_targets','training_pairs','training_sources')),'historical TRAIN pins changed')
    expected={**old['retention_target_references'],'prior_heading_tuning':old['artifacts']['tuning_targets'],'prior_heading_fresh':old['artifacts']['fresh_targets']}
    require(manifest['retention_target_references']==expected and len(expected)==21 and all(inputs['tuning'][p]==read_ref(pin) for p,pin in expected.items()),'all21 previous exposed panels must remain admitted retention')
    require(inputs['atom_train']==read_ref(manifest['artifacts']['atom_training_targets']) and inputs['atom_training_pairs']==read_ref(manifest['artifacts']['atom_training_pairs']),'new144 authored TRAIN/pair pins differ')
    pair_audit=verify_rotation_pairs(inputs['atom_train'],inputs['atom_training_pairs'])
    require(inputs['supported_replay']==old_inputs['supported_replay'] and inputs['supported_heading']==old_inputs['supported_heading'] and inputs['boundary_training']==old_inputs['boundary_training']+inputs['atom_train'],'exact864 supported sources required')
    require(inputs['training_token_roles'][:720]==old_inputs['training_token_roles'] and len(inputs['training_token_roles'])==len(inputs['training_atom_roles'])==864,'full source-role masks or historical mask prefix changed')
    ledger=read_ref(manifest['artifacts']['training_annotation_ledger']);annotations={r['candidate_id']:r for r in ledger['document_rows']}
    require(len(annotations)==len(ledger['document_rows'])==144 and set(annotations)=={r['candidate_id'] for r in inputs['atom_train']} and all(a['panel']=='train' and a['supported'] is True for a in annotations.values()),'new annotation ledger must contain TRAIN144 only')
    for row,roles,atoms in zip(inputs['boundary_training'],inputs['training_token_roles'],inputs['training_atom_roles'],strict=True):
        heading.training_role_masks(row,roles);atom_role_masks(row,atoms)
        if row['candidate_id'] in annotations:
            annotation=annotations[row['candidate_id']];require(annotation['source_sha256']==row['source_sha256'],'TRAIN annotation source mismatch')
            expected_spans=[];expected_notes=[]
            for occurrence in annotation['local_clause_coordinates']:
                for kind in ('actor','temporal','exceptions'):
                    span=occurrence['facet_spans'][kind]
                    if span is not None:expected_spans.append({'kind':kind,'char_start':span[0],'char_end':span[1]})
                for note in occurrence['editorial_context']:
                    require(note['author_stipulated_role']=='nonoperative_editorial_context' and row['source_text'][note['start_char']:note['end_char']]==note['source_text'],'exact authored editorial TRAIN context required')
                    expected_notes.append({'char_start':note['start_char'],'char_end':note['end_char']})
            require(atoms['atom_spans']==sorted(expected_spans,key=lambda s:(s['char_start'],s['char_end'],s['kind'])) and roles['editorial_heading_spans']==sorted(expected_notes,key=lambda s:(s['char_start'],s['char_end'])),'new source masks disagree with insertion-time annotations')
    full=inputs['replay']+inputs['new_train']+inputs['atom_train'];hashes={r['source_sha256'] for r in full}
    require(len(full)==len(hashes)==1296 and sum(r['supported'] for r in full)==864 and all(not hashes&{r['source_sha256'] for r in rows} for rows in inputs['sources'].values()),'complete TRAIN denominators or source isolation changed')
    heading.verify_scope_pairs(inputs['tuning']['atom_new'],read_ref(manifest['artifacts']['tuning_pairs']),48)
    return {'historical_audit':inherited,'training_documents':1296,'supported_supervised_documents':864,'unsupported_excluded_documents':432,'new_rotation_pairs':pair_audit,'prior_admitted_retention_panels':21,'training_mask_source_ancestry_verified':True,'fit_evaluation_overlap':0}


def teacher_batch_audit(inputs,batches):
    import torch
    torch.set_num_threads(1);_,teacher=boundary.restore(inputs['parent']);teacher.eval()
    for parameter in teacher.parameters():parameter.requires_grad_(False)
    before=digest({k:v.tolist() for k,v in teacher.state_dict().items()});require(before==digest(inputs['parent']['model_state']),'exact original-parent teacher state required')
    rows={r['candidate_id']:r for r in inputs['boundary_training']};outputs=[]
    with torch.no_grad():
        for batch in batches:
            values=[rows[i] for i in batch['common_replay_ids']+batch['heading_ids']+batch['atom_ids']]
            ids,features,lengths,*_=boundary.tensor_batch(torch,values,labels=True);logits,_=teacher(ids,features,lengths);outputs.append(logits.tolist())
    require(digest({k:v.tolist() for k,v in teacher.state_dict().items()})==before and all(p.grad is None for p in teacher.parameters()),'independent original teacher changed state or received gradients')
    return outputs,{'checkpoint':inputs['config']['boundary_parent'],'exact_batch_source_evaluations':4800,'batches':400,'batch_size':12,'state_sha256_before':before,'state_sha256_after':before,'gradients_absent':True,'teacher_outputs_sha256':digest(outputs),'saved_prediction_replay':False}


def verify_initialization(inputs,initial,arm,manifest):
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    warm=inputs['warm'];original=inputs['parent'];warm_ref=inputs['config']['warm_start']
    reconstructed=runtime.build_checkpoint(warm,arm=arm,seed=1730,training_manifest_sha256=digest(manifest),tuning_manifest_sha256=digest(inputs['tuning']),parent_file_sha256=warm_ref['sha256'])
    require(initial==reconstructed and initial['model_state']==warm['model_state'] and initial['parent_checkpoint']==warm and warm['parent_checkpoint']==original,'warm complete state/original teacher lineage differs')
    require(initial['parent_file_sha256']==WARM_PARENT_SHA and initial['original_parent_file_sha256']==ORIGINAL_PARENT_SHA and initial['additional_optimizer_steps']==0 and initial['optimizer_steps']==1200 and initial['optimizer_resumption_supported'] is False,'warm1200/original800/fresh-Adam lineage differs')
    return True


def initial_warm_parity(initial,warm_generations,sources):
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    decoder=runtime.decoder(initial);payloads={}
    for panel,rows in sources.items():
        expected=deepcopy(warm_generations[panel])
        for report in expected['reports']:report['checkpoint_sha256']=digest(initial)
        actual=clauses.decode_all(decoder,rows);require(actual==expected,'initial atom output differs from exact warm predecessor: '+panel);payloads[panel]=digest(actual)
    require(digest({k:v.tolist() for k,v in decoder.network.state_dict().items()})==digest(initial['model_state']),'initial inference changed state')
    return {'source_evaluations':sum(map(len,sources.values())),'panel_output_sha256':payloads,'all_numeric_and_final_outputs_equal_warm_start':True,'only_metadata_difference':'reports[].checkpoint_sha256','saved_output_replay':False,'new_fresh_reference_access':False}


def verify_training(inputs,frozen):
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    plan=read_ref(frozen['plan']);selection=read_ref(frozen['selections']);parent=inputs['parent'];original_ref=inputs['config']['boundary_parent'];warm_ref=inputs['config']['warm_start']
    require(original_ref['sha256']==ORIGINAL_PARENT_SHA and warm_ref['sha256']==WARM_PARENT_SHA and parent['optimizer_steps']==800 and inputs['warm']['optimizer_steps']==1200,'fixed original and warm parents required')
    expected={'arms':list(ARMS),'seed':1730,'stages':list(STAGES),'steps_per_arm':400,'trainable_parameter_counts':{a:1057 for a in ARMS},'learning_rate':.004,'positive_token_weight':12.,'optimizer':'fresh_Adam','editorial_rehearsal_weight_by_arm':{a:.5 for a in ARMS},'atom_rehearsal_weight_by_arm':{'continuation':0.,'atom_rehearsal':.5,'distill':.5},'teacher_kl_weight_by_arm':{'continuation':0.,'atom_rehearsal':0.,'distill':.25},'gradient_clip_norm':5.,'trial_wall_limit_seconds':1200,'identical_batches_all_arms':True,'common_supported_replay_rows':4,'supported_heading_rows_per_batch':4,'atom_pairs_per_batch':2,'supported_atom_rows_per_batch':4,'training_inventory_count':1296,'supported_training_count':864,'unsupported_excluded_from_fitting':432,'new_training_count':144,'supported_replay_count':528,'supported_heading_count':192,'supported_atom_count':144,'per_source_unsupported_acceptance_subset_required':True,'teacher_class_average':'available_gold_classes','teacher_kl_temperature':1.}
    require(all(type(plan[k]) is type(v) and plan[k]==v for k,v in expected.items()),'preregistered matched atom/teacher protocol differs')
    require(plan['teacher']==original_ref and plan['warm_start']==warm_ref and plan['scope_threshold_and_surface_policy_unchanged'] is True and plan['clause_predictions_used_for_selection'] is plan['new_fresh_targets_opened'] is False,'original teacher/warm initialization or inference policy differs')
    require(plan['postselection_challenge_diagnostic_slots']==['warm_start',*[a+'_final400' for a in ARMS]] and plan['full_training_diagnostic_slots']==['parent','warm_start',*[a+'_final400' for a in ARMS]] and plan['challenge_diagnostics_used_for_selection'] is plan['training_fit_diagnostics_used_for_selection'] is False,'prospective diagnostic slots cannot be selected with fresh references')
    require(len(inputs['tuning'])==22 and sum(map(len,inputs['tuning'].values()))==2448 and len(inputs['sources'])==23 and sum(map(len,inputs['sources'].values()))==2640,'all admitted/fresh-source panels required')
    for field,values in (('training_source_inventory_sha256',inputs['replay']+inputs['new_train']+inputs['atom_train']),('training_token_roles_sha256',inputs['training_token_roles']),('training_atom_roles_sha256',inputs['training_atom_roles'])):require(plan[field]==digest(values),'fitting source-role commitment differs: '+field)
    require(plan['tuning_counts']=={k:len(v) for k,v in inputs['tuning'].items()} and plan['source_counts']=={k:len(v) for k,v in inputs['sources'].items()},'complete panel counts differ')
    require(selection['plan']==frozen['plan'] and selection['executed_optimizer_updates']==1200 and selection['all_training_and_selection_complete'] is selection['choice_fixed_before_fresh_reference_release'] is True and selection['new_fresh_targets_opened'] is selection['clause_predictions_used_for_selection'] is False,'complete pre-reference matched selection freeze required')
    require([m['name'] for m in frozen['models']]==list(HEAD_NAMES) and read_ref(frozen['heads'])==frozen['models'],'all eight selected/fallback/diagnostic heads required')
    require(frozen['models'][0]=={'name':'parent','arm':'parent','checkpoint':original_ref,'selected_steps':0,'selection':'unchanged_parent_control','diagnostic_only':False} and frozen['models'][4]=={'name':'warm_start','arm':'warm_start','checkpoint':warm_ref,'selected_steps':0,'selection':'fixed_warm_start_diagnostic','diagnostic_only':True},'original-parent control/warm diagnostic attribution differs')
    jobs=[];baselines={};baseline_generations={}
    for name,key,pin in (('parent','parent_tuning',original_ref),('warm_start','warm_tuning',warm_ref)):
        value=read_ref(selection[key]);require(set(value['generation'])==set(value['metrics'])==set(inputs['tuning']),'baseline tuning panels incomplete');baselines[name]={};baseline_generations[name]=value['generation']
        for panel,targets in inputs['tuning'].items():
            baselines[name][panel]=heading.audited_scope_metric(value['generation'][panel],inputs['sources'][panel],targets,value['metrics'][panel])
            if name=='warm_start':heading.verify_frozen_scope_outputs(baseline_generations['parent'][panel],value['generation'][panel])
            jobs.append({'kind':'boundary','name':name+'-reference/'+panel,'checkpoint':pin,'sources':inputs['sources'][panel],'generation':selection[key],'scope_panel':panel,'stage':True})
    parent_metrics=baselines['parent'];batches=matched_batches(inputs['supported_replay'],inputs['supported_heading'],inputs['atom_training_pairs']);teacher_outputs,teacher_audit=teacher_batch_audit(inputs,batches)
    rows={r['candidate_id']:r for r in inputs['boundary_training']};headroles={r['candidate_id']:r for r in inputs['training_token_roles']};atomroles={r['candidate_id']:r for r in inputs['training_atom_roles']}
    require(len(rows)==len(headroles)==len(atomroles)==864 and set(rows)==set(headroles)==set(atomroles),'all864 TRAIN role memberships required')
    trials=selection['trials'];require([t['name'] for t in trials]==list(ARMS),'three matched objective trials required')
    audits=[];initials={};stage_maps={};teacher_masks=None
    for trial in trials:
        arm=trial['arm'];require(trial['name']==arm and trial['seed']==1730 and trial['parent']==original_ref and trial['warm_start']==warm_ref and trial['executed_steps']==400,'trial parent/warm/source attribution differs')
        training=read_ref(trial['training']);manifest=training['manifest'];wanted={'arm':arm,'seed':1730,'plan':frozen['plan'],'steps':400,'supported_replay_sha256':digest(inputs['supported_replay']),'supported_heading_sha256':digest(inputs['supported_heading']),'training_token_roles_sha256':digest(inputs['training_token_roles']),'training_atom_roles_sha256':digest(inputs['training_atom_roles']),'atom_training_sha256':digest(inputs['atom_train']),'atom_training_pairs_sha256':digest(inputs['atom_training_pairs'])}
        require(manifest==wanted,'matched TRAIN manifest differs');initial=read_ref(trial['initial_checkpoint']);verify_initialization(inputs,initial,arm,manifest);initials[arm]=initial;names=initial['trainable_parameters']
        require(training['optimizer_updates']==400 and len(training['losses'])==len(training['loss_receipts'])==len(training['batch_receipts'])==400 and training['batch_receipts']==batches and training['batch_receipts_sha256']==digest(batches),'all400 matched12row receipts required')
        require(set(training['trainable_parameters'])==set(names) and training['trainable_parameter_count']==1057 and training['optimizer_parameter_steps']=={k:400 for k in names},'complete residual Adam parameter counter inventory differs')
        require(training['initial_complete_model_state_sha256']==digest(initial['model_state']) and training['initial_predictions_equal_warm_start'] is training['initial_optimizer_state_empty'] is True and training['optimizer_resumed'] is training['optimizer_trajectory_independently_replayed'] is False and training['trial_wall_limit_seconds']==1200 and 0<training['wall_seconds']<=1200,'warm bitcopy/fresh Adam/wall limit differs')
        masks=[]
        for step,(loss,record,batch,teacher_logits) in enumerate(zip(training['losses'],training['loss_receipts'],batches,teacher_outputs,strict=True),1):
            require(record['steps']==step and record['total_loss']==loss and record['gradient_clip_norm']==5. and type(record['gradient_norm_before_clipping']) in (int,float) and math.isfinite(record['gradient_norm_before_clipping']) and record['gradient_norm_before_clipping']>=0 and record['finite_updated_parameters'] is True,'finite loss/update/gradient receipt differs')
            values=[rows[i] for i in batch['common_replay_ids']+batch['heading_ids']+batch['atom_ids']]
            verify_loss_receipt(record,values,headroles,atomroles,teacher_logits=teacher_logits,arm=arm,loss=loss);masks.append(record['objective_components']['teacher_correct_mask'])
        if teacher_masks is None:teacher_masks=masks
        require(masks==teacher_masks and training['teacher_outputs_sha256']==digest(teacher_outputs) and training['teacher_correct_masks_sha256']==digest(masks) and training['teacher_state_sha256_before']==training['teacher_state_sha256_after']==teacher_audit['state_sha256_before'] and training['teacher_gradients_absent'] is True,'frozen original teacher masks/outputs/state differ across arms')
        require([s['steps'] for s in trial['stages']]==list(STAGES),'all100/200/400 stage checkpoints required');normalized=[];stage_audits=[];stage_maps[arm]={}
        for stage in trial['stages']:
            checkpoint=read_ref(stage['checkpoint']);runtime.restore(checkpoint)
            require(checkpoint['additional_optimizer_steps']==stage['steps'] and checkpoint['optimizer_steps']==1200+stage['steps'],'new/cumulative optimizer counters differ')
            require({k:v for k,v in checkpoint.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')}=={k:v for k,v in initial.items() if k not in ('model_state','additional_optimizer_steps','optimizer_steps')},'immutable warm/teacher provenance changed')
            tensors=heading.verify_frozen_states(parent,initial,checkpoint,'rehearsal',names)
            require(stage['frozen_base_state_sha256']==initial['frozen_parent_state_sha256'] and stage['raw_scope_logits_unchanged'] is True,'original frozen state/scope receipt differs')
            saved=read_ref(stage['tuning']);require(saved['metrics']==stage['metrics'] and saved['source_churn']==stage['source_churn'] and set(saved['generation'])==set(inputs['tuning']),'complete stage metrics/source churn required')
            metrics={};changes={};failures=[]
            for panel,targets in inputs['tuning'].items():
                independent=boundary_source_churn(baseline_generations['parent'][panel],saved['generation'][panel],inputs['sources'][panel],targets)
                metrics[panel]=heading.audited_scope_metric(saved['generation'][panel],inputs['sources'][panel],targets,saved['metrics'][panel]);changes[panel]=independent['churn']
                require(stage['source_churn'][panel]==runner_churn(changes[panel]),'independent supported/unsupported per-source churn differs')
                jobs.append({'kind':'boundary','name':f'{arm}/stage-{stage["steps"]}/'+panel,'checkpoint':stage['checkpoint'],'sources':inputs['sources'][panel],'generation':stage['tuning'],'scope_panel':panel,'stage':True})
            for panel in sorted(metrics):
                m,p=metrics[panel],parent_metrics[panel];validate_churn(changes[panel],p,m)
                if changes[panel]['unsupported']['newly_accepted_ids']:failures.append(panel+':new_unsupported_sources_accepted')
                if m['raw_supported_correct']!=p['raw_supported_correct']:failures.append(panel+':raw_supported_scope_correct_changed')
                if m['raw_unsupported_accepted']!=p['raw_unsupported_accepted']:failures.append(panel+':raw_unsupported_accepted_changed')
                if m['raw_boundary_exact']<p['raw_boundary_exact']:failures.append(panel+':raw_boundary_document_exact_regressed')
                if m['supported_exact']<p['supported_exact']:failures.append(panel+':exact_supported_segmentation_regressed')
                if m['unsupported_accepted']>p['unsupported_accepted']:failures.append(panel+':final_unsupported_accepted_increased')
            if metrics['atom_new']['raw_boundary_exact']<=parent_metrics['atom_new']['raw_boundary_exact']:failures.append('atom_new:no_strict_raw_boundary_improvement')
            require(stage['eligible'] is (not failures) and stage['failures']==failures,'independent source-subset/count gates differ')
            normalized.append({'steps':stage['steps'],'metrics':metrics,'churn':changes,'raw_scope_logits_unchanged':True});stage_maps[arm][stage['steps']]=metrics
            stage_audits.append({'steps':stage['steps'],'checkpoint':stage['checkpoint'],'tuning':metrics,'source_churn':changes,'eligible':not failures,'failures':failures,'tensor_audit':tensors})
        selected=boundary_choice(normalized,parent_metrics);steps=selected['steps'] if selected else 0;pin=next(s['checkpoint'] for s in trial['stages'] if s['steps']==steps) if selected else original_ref;status='candidate' if selected else 'parent_fallback_no_eligible_boundary_stage'
        require(trial['selected_steps']==steps and trial['checkpoint']==pin and trial['selection']==status,'independent stage choice differs')
        require(next(h for h in frozen['models'] if h['name']==arm)=={**{k:trial[k] for k in ('name','arm','checkpoint','selected_steps','selection')},'diagnostic_only':False},'selected/fallback head attribution differs')
        require(next(h for h in frozen['models'] if h['name']==arm+'_final400')=={'name':arm+'_final400','arm':arm,'checkpoint':trial['stages'][-1]['checkpoint'],'selected_steps':400,'selection':'postselection_final400_diagnostic','diagnostic_only':True},'predeclared diagnostic stage attribution differs')
        audits.append({'name':arm,'parent':original_ref,'warm_start':warm_ref,'initial_checkpoint':trial['initial_checkpoint'],'training':trial['training'],'stages':stage_audits,'selection':status,'selected_steps':steps,'checkpoint':pin,'executed_updates':400,'batch_sha256':digest(batches)})
    require(all(initial['model_state']==inputs['warm']['model_state'] for initial in initials.values()),'arms started with unequal warm states')
    candidates=[a for a in audits if a['selection']=='candidate']
    def rank(a):
        m=stage_maps[a['name']][a['selected_steps']];return (m['atom_new']['raw_boundary_exact'],m['atom_new']['supported_exact'],sum(v['raw_boundary_exact'] for p,v in m.items() if p!='atom_new'),-a['selected_steps'],-ARMS.index(a['name']))
    primary=max(candidates,key=rank)['name'] if candidates else 'parent'
    require(selection['primary_boundary_choice']==frozen['primary_boundary_choice']==primary and frozen['choice_fixed_before_fresh_reference_release'] is True,'pre-reference primary choice differs')
    warm_generations={p:read_ref(pin) for p,pin in frozen['files']['warm_start'].items()};initial_audits={arm:initial_warm_parity(initial,warm_generations,inputs['sources']) for arm,initial in initials.items()}
    return jobs,{'trials':audits,'parent_tuning':parent_metrics,'warm_tuning':baselines['warm_start'],'original_teacher_audit':teacher_audit,'primary_boundary_choice':primary,'initial_warm_parity':initial_audits,'initial_source_evaluations':sum(a['source_evaluations'] for a in initial_audits.values()),'independent_teacher_source_evaluations':4800,'optimizer_trajectory_replayed':False}


def verify_inventory(inputs,frozen):
    require(frozen['all_training_selection_and_generation_complete'] is True and frozen['executed_optimizer_updates']==1200 and frozen['new_fresh_targets_opened'] is frozen['clause_predictions_used_for_selection'] is False and frozen['all_source_raw_scope_logits_unchanged'] is frozen['no_joint_stage_search'] is True,'complete source-only fixed-factor generation required')
    require(frozen['clause_models']==inputs['config']['clause_models'] and len(frozen['clause_models'])==2,'two fixed clause models required')
    require(frozen['selected_boundary_slots']==4 and frozen['diagnostic_boundary_slots']==4 and frozen['challenge_diagnostics_used_for_selection'] is False,'predeclared final400 diagnostic slots cannot enter selection')
    models={m['name']:m for m in frozen['clause_models']};heads={h['name']:h for h in frozen['models']}
    require(set(models)=={'parent_continuation','parent_grounding'} and set(heads)==set(frozen['files'])==set(HEAD_NAMES),'fixed clause and eight boundary inference slots required')
    for model in models.values():
        kind,wanted=CLAUSE_PARENTS[model['architecture']]
        require(model['name']=='parent_'+model['architecture'] and model['decoder_kind']==kind and model['checkpoint']['sha256']==wanted,'existing preselected clause parent changed')
        read_ref(model['checkpoint'],parse=False)
    require(set(frozen['sources'])==set(inputs['sources']) and all(read_ref(pin)==inputs['sources'][panel] for panel,pin in frozen['sources'].items()),'source-only frozen input rows differ')
    expected={m+'__boundary_'+h for m in models for h in heads}
    require(len(frozen['pipelines'])==16 and {p['name'] for p in frozen['pipelines']}==set(frozen['document_files'])==expected,'all sixteen fixed-clause/boundary pipeline slots required')
    require(set(frozen['document_sources'])==set(DOCUMENT_COUNTS) and all(frozen['document_sources'][p]==frozen['sources'][p] and len(inputs['sources'][p])==n for p,n in DOCUMENT_COUNTS.items()),'full new/exposed document panel inventory differs')
    for pipeline in frozen['pipelines']:
        model=models[pipeline['source_model_name']];head=heads[pipeline['boundary_head']]
        require(pipeline['name']==model['name']+'__boundary_'+head['name'] and pipeline['boundary_checkpoint']==head['checkpoint'] and pipeline['boundary_selection']==head['selection'] and pipeline['boundary_selected_steps']==head['selected_steps'] and pipeline['diagnostic_only'] is head['diagnostic_only'] and pipeline['clause_training_executed'] is False and all(pipeline[k]==model[k] for k in ('architecture','decoder_kind','checkpoint')) and set(frozen['document_files'][pipeline['name']])==set(DOCUMENT_COUNTS),'pipeline factor attribution or panel coverage differs')
    parent={p:read_ref(pin) for p,pin in frozen['files']['parent'].items()}
    for head,panels in frozen['files'].items():
        require(set(panels)==set(inputs['sources']),'selected boundary source panels missing')
        for panel,pin in panels.items():verify_frozen_scope_outputs(parent[panel],read_ref(pin))
    return {'boundary_slots':8,'selected_or_parent_slots':4,'fixed_warm_or_final400_diagnostic_slots':4,'fixed_clause_models':2,'document_pipeline_slots':16,'fresh_source_documents':192,'fresh_supported_documents':96,'fresh_unsupported_documents':96,'boundary_inference_source_rows':21120,'pipeline_documents':7680,'clause_training_updates':0}


def audit_training_diagnostics(inputs,frozen):
    require(set(frozen['training_diagnostics'])=={'parent','warm_start',*[a+'_final400' for a in ARMS]},'all five preregistered full TRAIN diagnostic slots required')
    selection=read_ref(frozen['selections']);expected={'parent':inputs['config']['boundary_parent'],'warm_start':inputs['config']['warm_start'],**{t['name']+'_final400':t['stages'][-1]['checkpoint'] for t in selection['trials']}}
    panels={'historical_replay':inputs['replay'],'new_training':inputs['new_train'],'atom_training':inputs['atom_train']};jobs=[];scores={};parent=None
    for name in ('parent','warm_start',*[a+'_final400' for a in ARMS]):
        pin=frozen['training_diagnostics'][name];saved=read_ref(pin)
        require(saved['checkpoint']==expected[name] and saved['training_fit_used_for_selection'] is saved['heldout_accuracy'] is False and set(saved['generation'])==set(saved['metrics'])==set(panels),'TRAIN diagnostic lineage/panels/selection attribution differs')
        if parent is None:parent=saved['generation']
        scores[name]={}
        for panel,targets in panels.items():
            sources=clauses.source_rows(targets);verify_frozen_scope_outputs(parent[panel],saved['generation'][panel])
            scores[name][panel]=audited_scope_metric(saved['generation'][panel],sources,targets,saved['metrics'][panel])
            jobs.append({'kind':'boundary','name':'TRAIN/'+name+'/'+panel,'checkpoint':expected[name],'sources':sources,'generation':pin,'scope_panel':panel,'training_diagnostic':True})
    return jobs,{'saved_source_rows':6480,'models':scores,'training_fit_used_for_selection':False,'heldout_accuracy':False}


_WORKER_GUARD=None


def init_worker(sealed):
    global _WORKER_GUARD
    _WORKER_GUARD=SealedReadGuard(sealed);sys.addaudithook(_WORKER_GUARD.event)


def replay_group(group):
    import torch
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
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


def historical_annotation_inputs(inputs):
    parent=read_ref(inputs['manifest']['inputs']['prior_heading_corpus'])
    bundle=heading.historical_annotation_inputs({'manifest':parent})
    bundle['historical_manifests']['prior_heading']=parent
    bundle['prior_annotation_ledgers']['prior_heading']={'reference':parent['artifacts']['annotation_ledger'],'ledger':read_ref(parent['artifacts']['annotation_ledger'])}
    texts=set(bundle['historical_source_inventory']['source_texts'])
    for name,key in (('prior_heading_tuning','tuning_targets'),('prior_heading_fresh','fresh_targets')):
        pin=parent['artifacts'][key];rows=read_ref(pin);bundle['historical_documents'][name]={'reference':pin,'rows':rows};texts.update(r['source_text'] for r in rows)
    bundle['historical_source_inventory']['source_texts']=sorted(texts)
    return bundle


def atom_endpoint_diagnostics(generation,sources,targets,annotation_rows):
    lookup={r['candidate_id']:r for r in generation['rows']};gold={r['candidate_id']:r for r in targets};annotations={r['candidate_id']:r for r in annotation_rows}
    require(len(lookup)==len(generation['rows'])==len(gold)==len(targets)==len(sources) and set(lookup)==set(gold)=={r['candidate_id'] for r in sources} and set(gold)<=set(annotations),'complete atom endpoint source/reference membership required')
    rows=[]
    for source in sources:
        identity=source['candidate_id'];prediction=lookup[identity];target=gold[identity];annotation=annotations[identity];tokens=boundary.tokenize(source['source_text'])
        require(source['source_sha256']==prediction['source_sha256']==target['source_sha256']==annotation['source_sha256']==boundary.text_sha(source['source_text']),'atom endpoint source commitment differs')
        logits=prediction['boundary_logits'];require(len(logits)==len(tokens) and all(type(v) in (int,float) and math.isfinite(v) for v in logits),'complete finite token logits required')
        predicted={i for i,value in enumerate(logits) if value>=0};require(sorted(predicted)==prediction['boundary_token_indices'],'raw endpoint threshold differs')
        row={'id':identity,'supported':target['supported'],'structure':annotation['factors']['child_structure'],'scope_supported':prediction['raw_learned_scope_supported'],'predicted_end_count':len(predicted)}
        if target['supported']:
            ends={c['char_end'] for c in target['clauses']};wanted={i for i,t in enumerate(tokens) if t['char_end'] in ends};require(len(wanted)==len(ends) and max(wanted)==len(tokens)-1,'complete exact endpoint gold required')
            transition=wanted-{len(tokens)-1};atom_tokens={kind:set() for kind in ('actor','temporal','exceptions')};editorial=set()
            for occurrence in annotation['local_clause_coordinates']:
                for kind,indices in atom_tokens.items():
                    span=occurrence['facet_spans'][kind]
                    if span is not None:indices.update(i for i,t in enumerate(tokens) if i not in wanted and span[0]<=t['char_start']<t['char_end']<=span[1])
                for note in occurrence['editorial_context']:
                    editorial.update(i for i,t in enumerate(tokens) if i not in wanted and re.fullmatch(r'[^\w\s]',t['text']) and note['start_char']<=t['char_start']<t['char_end']<=note['end_char'])
            all_atoms=set.union(*atom_tokens.values())
            require(sum(map(len,atom_tokens.values()))==len(all_atoms) and not all_atoms&editorial,'authored atom/editorial token role overlap')
            row.update(valid_tokens=len(tokens),gold_end_count=len(wanted),true_positive=len(wanted&predicted),false_positive=len(predicted-wanted),false_negative=len(wanted-predicted),
                inter_clause_gold_ends=len(transition),inter_clause_missed_ends=len(transition-predicted),terminal_gold_ends=1,terminal_missed_ends=int(len(tokens)-1 not in predicted),
                atom_interior_tokens=len(all_atoms),atom_false_ends=len(all_atoms&predicted),editorial_negative_tokens=len(editorial),editorial_false_ends=len(editorial&predicted),raw_endpoint_exact=predicted==wanted,
                by_atom={kind:{'tokens':len(indices),'false_ends':len(indices&predicted)} for kind,indices in atom_tokens.items()})
        else:row.update(token_gold_available=False,endpoint_error_scored=False)
        rows.append(row)
    supported=[r for r in rows if r['supported']];keys=('valid_tokens','gold_end_count','true_positive','false_positive','false_negative','inter_clause_gold_ends','inter_clause_missed_ends','terminal_gold_ends','terminal_missed_ends','atom_interior_tokens','atom_false_ends','editorial_negative_tokens','editorial_false_ends')
    return {'metrics':{'documents':len(rows),'supported_documents':len(supported),'unsupported_without_endpoint_gold':len(rows)-len(supported),**{k:sum(r[k] for r in supported) for k in keys},'raw_endpoint_exact':sum(r['raw_endpoint_exact'] for r in supported),'raw_endpoints_scored_even_when_scope_abstains':True},
        'by_atom':{kind:{key:sum(r['by_atom'][kind][key] for r in supported) for key in ('tokens','false_ends')} for kind in ('actor','temporal','exceptions')},'rows':rows}


def annotation_dependencies(module):
    result=[];seen=set()
    def visit(value):
        path=getattr(value,'__file__',None)
        if path is None or path in seen:return
        seen.add(path);result.append(value)
        for name in ('heading','adapter','previous'):visit(getattr(value,name,None))
    visit(module)
    return result


def churn_summary(value):
    return {'documents':value['count'],'supported':len(value['supported_ids']),'unsupported':len(value['unsupported_ids']),
        'raw_supported':{key:(len(v) if key.endswith('_ids') else v) for key,v in value['raw_supported'].items()},
        'delivered_supported':{key:(len(v) if key.endswith('_ids') else v) for key,v in value['delivered_supported'].items()},
        'unsupported_decisions':{key:(len(v) if key.endswith('_ids') else v) for key,v in value['unsupported'].items()}}


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import run_legal_atom_boundary_experiment as runner
    from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as corpus
    from scripts.ops.legal_ir import summarize_legal_atom_boundary_annotations as annotations
    from scripts.ops.legal_ir import summarize_legal_scope_preservation_experiment as preservation
    from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as runtime
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU qualification workers required')
    folder,output=Path(args.run_directory).resolve(),Path(args.output).resolve()
    frozen_ref=ref(folder/'generation-frozen.json');frozen=read_ref(frozen_ref)
    require(frozen['schema']==runner.SCHEMA,'declared completed scope adapter generation required')
    plan=read_ref(frozen['plan']);config=read_ref(plan['config']);manifest=read_ref(config['atom_corpus_manifest'])
    evidence_refs={key:manifest['artifacts'][key] for key in ('fresh_targets','fresh_pairs','annotation_ledger','exposure_audit')}
    sealed=list(evidence_refs.values());guard=SealedReadGuard(sealed);sys.addaudithook(guard.event)
    inputs=runner.read_config(plan['config']['path']);inventory=verify_inventory(inputs,frozen)
    pins=dict(plan['producer_pins']);require(all(sha(path)==wanted for path,wanted in pins.items()),'original fitting producer drift before qualification')
    for module in (sys.modules[__name__],heading,prior,runner,corpus,annotations,preservation,runtime,runtime.heading,boundary,clauses,retained,retained.prior,retained.calendar,retained.calendar_summary,retained.compose,boundary_qualification,previous,gate):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    for module in annotation_dependencies(annotations):pins[str(Path(module.__file__).resolve())]=sha(module.__file__)
    require(all(sha(path)==wanted for path,wanted in pins.items()),'frozen producer source drift')
    output.mkdir(parents=True,exist_ok=False)
    qualification_plan=write(output/'qualification-plan.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'producer_pins':pins,'sealed_references':evidence_refs,'fresh_document_build_slots':16,'native_build_panel':'atom_fresh','new_reference_files_opened':False,'old_fresh_reference_panels_admitted_as_retention':True,'clause_training_executed':False})
    fitting=verify_fitting(inputs);jobs,training=verify_training(inputs,frozen)
    training_jobs,diagnostics=audit_training_diagnostics(inputs,frozen);jobs+=training_jobs
    require(training['initial_source_evaluations']==7920,'all three initial checkpoints must be checked on all2640source rows')
    training_ref=write(output/'training-and-selection-audit.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'selections':frozen['selections'],'fitting':fitting,**training,'full_training_diagnostics':diagnostics,'executed_boundary_updates':1200,'clause_training_updates':0,'source_semantics_verified':False})
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
    require(sum(len(j['sources']) for j in jobs)==62208 and sum(len(j['sources']) for j in jobs if j.get('training_diagnostic'))==6480,'complete saved output/diagnostic replay denominator differs')
    groups=prior.group_replay_jobs(jobs);replays=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn'),initializer=init_worker,initargs=(sealed,)) as pool:
        for future in as_completed([pool.submit(replay_group,g) for g in groups]):replays.extend(future.result())
    require(len(replays)==len(jobs) and sum(r['rows'] for r in replays)==62208,'full saved numerical replay incomplete')
    for a in frozen['models']:
        for b in frozen['models']:
            if a['checkpoint']==b['checkpoint']:
                require(boundary_outputs[a['name']]==boundary_outputs[b['name']],'same-checkpoint head slots changed outputs')
                require(all(documents[m['name']+'__boundary_'+a['name']]==documents[m['name']+'__boundary_'+b['name']] for m in frozen['clause_models']),'same-checkpoint pipeline slots changed outputs')
    replay_ref=write(output/'replay-frozen.json',{'schema':SCHEMA,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'panels':sorted(replays,key=lambda r:r['name']),'saved_output_rows':62208,'boundary_rows':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_rows':sum(r['rows'] for r in replays if r['kind']=='document'),'training_diagnostic_rows':6480,'additional_initial_parity_rows':7920,'grouped_checkpoint_loads':len(groups),'prediction_memoization_used':False,'new_reference_files_opened':False,'old_fresh_retention_references_admitted':True})
    selections={}
    for model in frozen['pipelines']:
        name=model['name'];selected=document_selection(documents[name]['atom_fresh']['rows'],inputs['sources']['atom_fresh'],toolchain=args.toolchain)
        require(selected['source_count']==len(selected['rows'])+len(selected['excluded'])==192,'native source-only selection dropped documents')
        selections[name]=selected
    selection_ref=write(output/'build-selection-frozen.json',{'schema':SCHEMA,'document':selections,'replay':replay_ref,'document_source_slots':3072,'document_panel':'atom_fresh','canonical_references_used_for_selection':False,'new_reference_files_opened':False,'clause_training_executed':False})
    builds={'document':{}}
    for name,selected in selections.items():
        builds['document'][name]=retained.build_batches(selected['rows'],output/'builds'/name,args)
        print({'phase':'built','model':name,'supported_for_lowering':len(selected['rows'])},flush=True)
    builds_ref=write(output/'builds-frozen.json',{'schema':SCHEMA,**builds,'selections':selection_ref,'replay':replay_ref,'new_reference_files_opened':False,'reference_derived_layout_evidence_opened':False,'old_fresh_retention_references_admitted':True})
    read_ref(frozen['selections'],parse=False);require(not guard.events,'sealed fresh reference access attempted before build freeze')
    guard.released=True;print({'phase':'references_released_after_build_freeze','builds':builds_ref},flush=True)
    evidence={key:read_ref(pin) for key,pin in evidence_refs.items()};targets={**inputs['tuning'],'atom_fresh':evidence['fresh_targets']}
    require(set(targets)==set(inputs['sources']) and clauses.source_rows(targets['atom_fresh'])==inputs['sources']['atom_fresh'],'complete fresh/admitted reference binding differs')
    audit_inputs={**inputs,'replay':{k:read_ref(v) for k,v in manifest['replay_references'].items()},'training_pairs':read_ref(manifest['artifacts']['training_pairs']),'training_annotation_ledger':read_ref(manifest['artifacts']['training_annotation_ledger']),'tuning_pairs':read_ref(manifest['artifacts']['tuning_pairs'])}
    exposure_ref=write(output/'authored-exposure-audit.json',annotations.audit_atom_annotations(audit_inputs,evidence['fresh_targets'],evidence['fresh_pairs'],evidence['annotation_ledger'],evidence['exposure_audit'],**historical_annotation_inputs(inputs)))
    boundary_metrics={name:{panel:scope_metrics(value,inputs['sources'][panel],targets[panel]) for panel,value in panels.items()} for name,panels in boundary_outputs.items()}
    document_metrics={};pipeline_reports=[]
    for model in frozen['pipelines']:
        name=model['name'];document_metrics[name]={}
        for panel,generation in documents[name].items():
            b=boundary_metrics[model['boundary_head']][panel]['details']
            if panel=='atom_fresh':
                metric=boundary_qualification.pipeline_funnel(generation,b,inputs['sources'][panel],targets[panel],selections[name],builds['document'][name])
            else:
                measured=retained.score_documents(generation,inputs['sources'][panel],targets[panel]);reference={r['candidate_id']:r for r in targets[panel]};bs={r['id']:r for r in b['rows']}
                rows=[boundary_qualification.attribution.pipeline_record(r,reference[r['candidate_id']],bs[r['candidate_id']]) for r in generation['rows']]
                metric={'metrics':{k:v for k,v in measured.items() if k!='rows'},'rows':rows,'attribution':boundary_qualification.attribution.pipeline_counts(rows),'native_build_not_executed_on_this_panel':True,'explicitly_admitted_retention_panel':True}
            document_metrics[name][panel]=metric
        pipeline_reports.append({**model,'panels':{p:{k:v for k,v in m.items() if k!='rows'} for p,m in document_metrics[name].items()}})
    endpoint_metrics={head:{panel:atom_endpoint_diagnostics(value,inputs['sources'][panel],targets[panel],evidence['annotation_ledger']['document_rows']) for panel,value in panels.items() if panel in ('atom_new','atom_fresh')} for head,panels in boundary_outputs.items()}
    churn_metrics={head:{panel:churn_from_scored_rows(boundary_metrics['parent'][panel]['details']['rows'],value['details']['rows']) for panel,value in panels.items()} for head,panels in boundary_metrics.items()}
    details_ref=write(output/'scored-details.json',{'boundary':boundary_metrics,'document':document_metrics,'endpoints':endpoint_metrics,'source_churn':churn_metrics})
    require(all(sha(p)==wanted for p,wanted in pins.items()) and runner.read_config(plan['config']['path'])==inputs,'producer or fitting/source closure drift')
    for pin in (frozen_ref,frozen['plan'],frozen['selections'],frozen['heads'],*sealed):read_ref(pin,parse=False)
    opens_ref=write(output/'phase-open-audit.json',{'schema':SCHEMA,'sealed_paths':sorted(guard.paths),'events':guard.events,'before_build_freeze_attempts':sum(not r['after_build_freeze'] for r in guard.events),'build_freeze':builds_ref,'all_new_reference_reads_after_build_freeze':True,'replay_workers_had_same_four_file_OS_open_denial':True,'old_fresh_references_were_admitted_retention':True})
    result={'schema':SCHEMA,'qualification_plan':qualification_plan,'generation_freeze':frozen_ref,'training_and_selection_audit':training_ref,'replay':replay_ref,'builds':builds_ref,'details':details_ref,'authored_exposure_audit':exposure_ref,'phase_open_audit':opens_ref,'posthoc_evidence':evidence_refs,'models':frozen['models'],'clause_models':frozen['clause_models'],'pipelines':pipeline_reports,'boundary_metrics':{h:{p:v['metrics'] for p,v in panels.items()} for h,panels in boundary_metrics.items()},'endpoint_diagnostics':{h:{p:{k:v for k,v in value.items() if k!='rows'} for p,value in panels.items()} for h,panels in endpoint_metrics.items()},'source_churn':{h:{p:churn_summary(v) for p,v in panels.items()} for h,panels in churn_metrics.items()},'independent_teacher_source_evaluations':4800,'producer_pins':pins,'primary_boundary_choice':frozen['primary_boundary_choice'],'parent_fallbacks':[m['name'] for m in frozen['models'] if m['selection'].startswith('parent_fallback')],'diagnostic_heads':[m['name'] for m in frozen['models'] if m.get('diagnostic_only')],'diagnostic_final400_heads':[m['name'] for m in frozen['models'] if m['name'].endswith('_final400')],'diagnostic_fresh_scores_used_for_selection':False,'executed_optimizer_updates':1200,'clause_optimizer_updates':0,'inventory':inventory,'boundary_source_documents_replayed':sum(r['rows'] for r in replays if r['kind']=='boundary'),'document_inference_rows_replayed':sum(r['rows'] for r in replays if r['kind']=='document'),'clause_occurrences_replayed':sum(r.get('clause_occurrences_replayed',0) for r in replays),'additional_initial_parity_source_evaluations':7920,'actual_lake_build_invocations':sum(b['backend_executed'] for rows in builds['document'].values() for b in rows),'build_attempts':sum(len(rows) for rows in builds['document'].values()),'native_fresh_document_build_slots':16,'document_build_panel':'atom_fresh','fresh_reference_files_opened_after_replay_and_build_freezes':True,'reference_derived_novelty_evidence_opened_after_build_freeze':True,'test_results_used_for_selection_or_gate_revision':False,'scope':'One fixed-seed matched three-arm400-update comparison initialized from the same unqualified heading checkpoint. Only residual token-boundary parameters train. Original encoder, boundary/scope heads and clause decoders stay fixed; original-parent per-source guard acceptance subset and count gates remain frozen. Old fresh panels are now exposed retention. Authored flat-scope reference exactness and native compilation do not establish statutory semantic fidelity or supported nested-logic translation.',**FALSE}
    write(output/'summary.json',result);print({'complete':str(output/'summary.json'),'primary_boundary_choice':result['primary_boundary_choice'],'fresh_scope':{k:v['atom_fresh'] for k,v in result['boundary_metrics'].items()}},flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--lake-executable',required=True);parser.add_argument('--toolchain',default='leanprover/lean4:v4.34.1');parser.add_argument('--workers',type=int,default=3)
    run(parser.parse_args())
