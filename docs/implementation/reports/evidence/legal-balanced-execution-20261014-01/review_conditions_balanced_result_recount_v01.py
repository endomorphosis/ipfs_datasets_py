#!/usr/bin/env python3
"""Independent stdlib recount of the qualified, frozen F14 conditions-balanced result bundle, trained N10 parent and diagnostic N11.

Reads public evidence and authored reference JSON only after exact freeze/runtime
authentication. Checkpoints are hashed as opaque bytes. No saved scorer, model,
codec, resource observer, numerical package, network client or trainer is loaded.
"""
from pathlib import Path
import hashlib
import os
import sys
import json
import math
import re
import stat
import struct

ROOT = Path(__file__).resolve().parent
N6 = ROOT.parent / 'legal-temporal-adapter-20261013-01'
N7 = ROOT.parent / 'legal-temporal-attention-20261013-01'
N8 = ROOT.parent / 'legal-actor-boundary-20261013-01'
QUALIFICATION=ROOT/'result-recount-source-independent-review-v01.json'
INPUTS=ROOT/'result-recount-inputs-v01.json'
OUTPUT=ROOT/'conditions-balanced-independent-recount-v01.json'
FREEZE_PASSED=False
sys.dont_write_bytecode=True
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
OLD = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
FRESH = ('fresh_dev', 'fresh_test')
PANELS = OLD + FRESH
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8, 36, 36)))
OBSERVED = {}



def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def identity(path, expected=None):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and path.is_file() and not path.is_symlink(), 'Physical ordinary evidence required')
    require('private-runtime-snapshots' not in path.parts and 'resource-snapshots' not in path.parts
        and path.name not in {'resources-start.json','resources-final.json','disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json'}, 'Private or global body denied')
    before=path.stat();require(0<before.st_size<=32*1024*1024,'Bounded saved evidence required')
    data=path.read_bytes();after=path.stat()
    stable=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    require(stable(before)==stable(after) and len(data)==before.st_size,'Raw evidence changed')
    pin={'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    if expected:
        require(all(pin[k]==expected[k] for k in ('bytes','sha256')) and ('path' not in expected or pin['path']==expected['path']), 'Evidence identity differs')
    require(str(path) not in OBSERVED or OBSERVED[str(path)]==pin,'Previously consumed identity changed')
    OBSERVED[str(path)]=pin
    return pin


def read(path, expected=None):
    path=Path(path)
    require('checkpoint' not in path.name, 'Checkpoint JSON parse denied')
    require(FREEZE_PASSED or path in {QUALIFICATION,INPUTS,ROOT/'conditions-balanced-output-freeze-v01.json',ROOT/'conditions-balanced-ce-runtime-review-v01.json'},
            'No saved results, CE or reference reads before complete authenticated N10 freeze')
    captured=identity(path,expected);raw=path.read_bytes()
    require(len(raw)==captured['bytes'] and hashlib.sha256(raw).hexdigest()==captured['sha256'],'Consumed JSON differs')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'Duplicate JSON refused');result[key]=value
        return result
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'Nonfinite JSON refused');return value
    value=json.loads(raw,object_pairs_hook=pairs,parse_float=finite,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON refused')))
    identity(path,captured)
    return value


def audit(event,args):
    if event=='import' and args[0].split('.')[0] in {'torch','numpy','ipfs_datasets_py','transformers','sentence_transformers','huggingface_hub'}:
        raise ValueError('Model, scorer, numerical or SDK import denied')
    if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {'os.system','os.fork','fcntl.flock','os.mkdir','os.remove','os.rename','os.replace','os.unlink','os.kill','os.killpg'}:
        raise ValueError('Process, network, resource or shared operation denied')
    if event=='open' and isinstance(args[0],(str,bytes)):
        target=Path(os.fsdecode(args[0])).absolute();mode,flags=args[1:3]
        require('private-runtime-snapshots' not in target.parts and 'resource-snapshots' not in target.parts
            and target.name not in {'resources-start.json','resources-final.json','disk-reservations.json','ipfs-datasets-resource-scheduler-1000.json'},'Private or global open denied')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or target==OUTPUT and bool(flags&os.O_EXCL),'Only exclusive own recount write permitted')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'Only own recount freeze permitted')


def descriptor_read(value):
    return read(value['path'], value)


def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Finite scalar required')
    return struct.unpack('!f', struct.pack('!f', value))[0]


def bits(value):
    if type(value) is dict:
        return b''.join(bits(value[k]) for k in sorted(value))
    if type(value) is list:
        return b''.join(bits(v) for v in value)
    require(f32(value) == value, 'Exact saved binary32 required')
    return struct.pack('!f', value)


def choice(values):
    ranked = sorted(range(len(values)), key=lambda i: (-values[i], i))
    return None if f32(values[ranked[0]] - values[ranked[1]]) <= 1e-7 else ranked[0]


def coordinates(row):
    text = row['source_text']
    tokens = [{'text': m.group(), 'start': m.start(), 'end': m.end()} for m in re.finditer(r'\w+|[^\w\s]', text)]
    require(0 < len(tokens) <= 128, 'Complete bounded tokens required')
    starts = {t['start']: i for i, t in enumerate(tokens)}
    ends = {t['end']: i for i, t in enumerate(tokens)}
    rule = row['canonical_ir']['rules'][0]
    require(set(row['canonical_ir']) == {'rules'} and len(row['canonical_ir']['rules']) == 1
            and set(rule) == {'modality', *FIELDS}, 'Complete seven-field IR required')
    result = {}
    for field in FIELDS:
        atom = (rule[field][0] if rule[field] else '') if field in FIELDS[3:] else rule[field]
        if not atom:
            require(field in FIELDS[2:], 'Required actor/action empty')
            continue
        offsets = [m.start() for m in re.finditer('(?=' + re.escape(atom) + ')', text)]
        spans = [(starts[o], ends[o + len(atom)]) for o in offsets if o in starts and o + len(atom) in ends]
        require(len(spans) == 1, 'Unique aligned gold source atom required')
        result[field] = spans[0]
    require(all(b < c or d < a for i, (a, b) in enumerate(result.values())
                for c, d in list(result.values())[i + 1:]), 'Gold role spans overlap')
    return tokens, result


def ranked(scores,role):
    n=len(scores['tokens'])
    require(1<=n<=128 and len(scores['start_logits'][role])==len(scores['end_logits'][role])==n,'Complete saved pointer vectors required')
    return sorted(((f32(scores['start_logits'][role][left]+scores['end_logits'][role][right]),left,right)
        for left in range(n) for right in range(left,n)),key=lambda item:(-item[0],item[1],item[2]))


def actor_coverage(src,scores,gold):
    spans=ranked(scores,'actor');coordinate=gold['actor']
    index=next(i for i,item in enumerate(spans) if item[1:]==coordinate);gold_score=spans[index][0]
    result=dict(id=src['id'],stable_rank=index+1,gold_score_float32=gold_score,full_domain_spans=len(spans),
        higher_score_spans=sum(item[0]>gold_score for item in spans),equal_score_spans=sum(item[0]==gold_score for item in spans),
        tied_within_guard_spans=sum(abs(f32(item[0]-gold_score))<=1e-7 for item in spans),coordinates=list(coordinate))
    for top in (1,8,16):
        result['in_top'+str(top)]=index<top
        result['top'+str(top)+'_boundary_tied_within_guard']=len(spans)>top and f32(spans[top-1][0]-spans[top][0])<=1e-7
    mode=choice(scores['modality_logits']);target=src['canonical_ir']['rules'][0]
    result['fixed_modality_correct']=mode is not None and ('O','P','F')[mode]==target['modality']
    present={}
    for role in FIELDS[2:]:
        winner=choice(scores['presence_logits'][role]);present[role]=winner is not None and (winner==1) is (role in gold)
    result['fixed_presence_correct']=present
    result['all_fixed_head_decisions_correct']=bool(result['fixed_modality_correct'] and all(present.values()))
    retained={role:next(i for i,item in enumerate(ranked(scores,role)) if item[1:]==span)<8 for role,span in gold.items()}
    result['gold_present_role_top8_coverage']=retained
    result['all_gold_present_role_spans_in_top8']=all(retained.values());result['gold_nonoverlap_compatible']=True
    result['full_gold_assignment_survives_retained_domain']=bool(result['all_fixed_head_decisions_correct'] and all(retained.values()))
    # Independently enumerate the complete row-major target-dependent domain.
    domain=[]
    for left in range(len(scores['tokens'])):
        for right in range(left,len(scores['tokens'])):
            if (left,right)==coordinate:continue
            if any(not (right<a or b<left) for role,(a,b) in gold.items() if role!='actor'):continue
            domain.append((left,right))
    best=None;ties=0
    for left,right in domain:
        score=f32(scores['start_logits']['actor'][left]+scores['end_logits']['actor'][right])
        if best is None or score>best[0]:best=(score,left,right);ties=1
        elif score==best[0]:ties+=1
    margin=None if best is None else f32(gold_score-best[0])
    hinge=0. if best is None else max(0.,f32(f32(1.+best[0])-gold_score))
    result['filtered_hard_negative']=dict(compatible_wrong_domain_spans=len(domain),compatible_wrong_domain_sha256=digest(domain),
        gold_score_float32=gold_score,chosen_wrong_coordinates=None if best is None else list(best[1:]),
        chosen_wrong_score_float32=None if best is None else best[0],chosen_wrong_exact_tie_count=ties,
        gold_minus_wrong_margin_float32=margin,margin_at_least_one=False if margin is None else margin>=1.,
        hinge_float32=hinge,hinge_active=hinge>0.,empty_domain=best is None,
        scope='Post-freeze gold-dependent filtered training-domain diagnostic; not inference candidate coverage.')
    return result


def coverage_summary(rows):
    ranks=[row['stable_rank'] for row in rows];hard=[row['filtered_hard_negative'] for row in rows]
    margins=[row['gold_minus_wrong_margin_float32'] for row in hard if not row['empty_domain']]
    result=dict(rows=len(rows),top1=sum(row['in_top1'] for row in rows),top8=sum(row['in_top8'] for row in rows),
        top16=sum(row['in_top16'] for row in rows),rank_min=min(ranks),rank_max=max(ranks),rank_sum=sum(ranks),
        top8_boundary_tied_within_guard=sum(row['top8_boundary_tied_within_guard'] for row in rows),
        top16_boundary_tied_within_guard=sum(row['top16_boundary_tied_within_guard'] for row in rows),
        fixed_modality_correct=sum(row['fixed_modality_correct'] for row in rows),
        all_fixed_head_decisions_correct=sum(row['all_fixed_head_decisions_correct'] for row in rows),
        all_gold_present_role_spans_in_top8=sum(row['all_gold_present_role_spans_in_top8'] for row in rows),
        full_gold_assignment_survives_retained_domain=sum(row['full_gold_assignment_survives_retained_domain'] for row in rows),
        actor_not_in_top8_ids=[row['id'] for row in rows if not row['in_top8']],
        fixed_modality_incorrect_ids=[row['id'] for row in rows if not row['fixed_modality_correct']],
        fixed_presence_incorrect_ids={role:[row['id'] for row in rows if not row['fixed_presence_correct'][role]] for role in FIELDS[2:]},
        fixed_head_blocker_ids=[row['id'] for row in rows if not row['all_fixed_head_decisions_correct']],
        fixed_blocker_and_actor_not_top8_ids=[row['id'] for row in rows if not row['all_fixed_head_decisions_correct'] and not row['in_top8']],
        present_role_top8={role:dict(present=sum(role in row['gold_present_role_top8_coverage'] for row in rows),
            retained=sum(row['gold_present_role_top8_coverage'].get(role,False) for row in rows),
            not_retained_ids=[row['id'] for row in rows if role in row['gold_present_role_top8_coverage'] and not row['gold_present_role_top8_coverage'][role]]) for role in FIELDS},
        full_gold_assignment_not_retained_ids=[row['id'] for row in rows if not row['full_gold_assignment_survives_retained_domain']],
        filtered_hard_negative=dict(rows=len(hard),nonempty_domain_count=len(margins),empty_domain_count=sum(row['empty_domain'] for row in hard),
            hinge_active_count=sum(row['hinge_active'] for row in hard),hinge_inactive_count=sum(not row['hinge_active'] for row in hard),
            hinge_sum=math.fsum(row['hinge_float32'] for row in hard),hinge_mean=math.fsum(row['hinge_float32'] for row in hard)/len(hard),
            minimum_gold_minus_wrong_margin=min(margins) if margins else None,mean_gold_minus_wrong_margin=math.fsum(margins)/len(margins) if margins else None,
            margin_at_least_one_count=sum(row['margin_at_least_one'] for row in hard)),full_rank_records_sha256=digest(rows),
        scope='Reference-dependent post-freeze diagnostic; no gold inserted into selector or model.')
    return result


def paired_score(before,after):
    require([row['id'] for row in before]==[row['id'] for row in after],'Ordered paired source IDs required')
    result={}
    for route in ('raw','joint'):
        result[route]={}
        for metric in ('full_IR','modality',*FIELDS):
            old=sum(row[route][metric] for row in before);new=sum(row[route][metric] for row in after);gain=[];loss=[]
            for left,right in zip(before,after,strict=True):
                if right[route][metric] and not left[route][metric]:gain.append(left['id'])
                if left[route][metric] and not right[route][metric]:loss.append(left['id'])
            result[route][metric]=dict(before_correct=old,after_correct=new,gains=len(gain),losses=len(loss),gain_ids=gain,loss_ids=loss)
    return result


def authenticate_freeze(freeze, runtime, schema):
    require(freeze['schema']==schema and runtime['passed'] is True and runtime['findings']==[]
        and freeze['all_outputs_frozen'] is True and freeze['authorizes_authored_eval_scoring'] is True
        and freeze['statutory_reference_scoring_authorized'] is False and freeze['actual_returned_optimizer_updates']==32
        and len(freeze['results'])==runtime['output_file_count']==62 and runtime['outputs']==freeze['results'],
        'Qualified complete freeze/runtime required before reference reads')
    root=Path(freeze['summary']['path']).parent
    names={'data-schedule-before-models.json','cell-checkpoint.json','cell-training.json','summary.json',
        'initial-parent-head-parity.json','trained-frozen-head-retention.json'}
    for stage in ('baseline','trained'):
        names.update(stage+'-'+panel+'-'+view+'.json' for panel in PANELS for view in ('raw','joint'))
    for label in ('initial-training168','parent-training168','trained-training168','parent-fresh_dev','parent-fresh_test'):
        names.update(label+'-'+view+'.json' for view in ('raw','joint'))
    for stage in ('initial','trained'):
        names.add(stage+'-parity.json');names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    require(len(names)==62 and set(freeze['results'])=={str(root/name) for name in names},'Exact complete62 flat output inventory required')
    for path,expected in freeze['results'].items():
        identity(path,expected);require(stat.S_IMODE(Path(path).stat().st_mode)==0o444,'Frozen output mode differs')
    require(freeze['summary']==dict(path=str(root/'summary.json'),**freeze['results'][str(root/'summary.json')]),'Frozen summary descriptor differs')
    return root


def projection(scores, full=True):
    value={'modality_logits':scores['modality_logits'],'presence_logits':dict(scores['presence_logits']),
        'start_logits':scores['start_logits'],'end_logits':scores['end_logits']}
    if not full:del value['presence_logits']['conditions']
    return value


def presence_recount(sources, observations, decisions):
    """Independently derive all four optional-role confusion matrices and exclusions."""
    matrix={route:{field:{name:[] for name in ['TP','TN','FP','FN','abstained_or_ambiguous']}
        for field in FIELDS[2:]} for route in ['head','raw','joint']}
    totals={field:{'gold_present':0,'gold_absent':0} for field in FIELDS[2:]}
    excluded={route:{field:{'gold_present':[],'gold_absent':[]} for field in FIELDS[2:]} for route in matrix}
    for i,source in enumerate(sources):
        identifier=source['id'];target=source['canonical_ir']['rules'][0];occ=observations['occurrences'][i]
        raw=observations['inference']['rows'][i];joint=decisions[i]['result']
        require(occ['id'] == decisions[i]['id'] == identifier, 'Presence reference/source IDs differ')
        for field in FIELDS[2:]:
            truth=bool(target[field]);goldkey='gold_present' if truth else 'gold_absent';totals[field][goldkey]+=1
            head=choice(occ['scores']['presence_logits'][field])
            values=[None if head is None else head == 1]
            for result,success in [(raw,'decoded'),(joint,'selected')]:
                values.append(bool(result['canonical_ir']['rules'][0][field]) if result['status'] == success else None)
            for route,prediction in zip(['head','raw','joint'],values,strict=True):
                if prediction is None:label='abstained_or_ambiguous';excluded[route][field][goldkey].append(identifier)
                elif truth:label='TP' if prediction else 'FN'
                else:label='FP' if prediction else 'TN'
                matrix[route][field][label].append(identifier)
    cell=lambda ids:dict(count=len(ids),ids=ids)
    return dict(denominators=totals,views={r:{f:{k:cell(ids) for k,ids in v.items()} for f,v in fields.items()} for r,fields in matrix.items()},
        excluded_by_gold={r:{f:{k:cell(ids) for k,ids in v.items()} for f,v in fields.items()} for r,fields in excluded.items()},
        abstentions_excluded_from_TP_TN_FP_FN=True,independent_primary_recount_required=True,
        scope='Post-freeze exposed authored presence only; ambiguity and abstention excluded from all confusion cells.')


def recount_training(report, training, schedule):
    positive=sum(1 for source in training if bool(source['canonical_ir']['rules'][0]['conditions']))
    require(len(training) == 168 and positive == 72 and len(training)-positive == 96, 'Independently counted training-only72positive96negative prior differs')
    require(report['schema'] == 'bounded-conditions-balanced-adapter-training/v1'
        and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
        and report['conditions_training_count'] == 168 and report['training_conditions_class_counts'] == dict(absent=96,present=72), '32 conditions balanced updates required')
    partition=report['parameter_partition'];names=['conditions_presence.weight','conditions_presence.bias']
    require(len(partition['model_parameter_names']) == 42 and len(partition['frozen_parameter_names']) == 40
        and partition['optimizer_parameter_order'] == report['optimizer_parameter_order'] == names
        and partition['stored_trainable_scalar_count'] == 520 and partition['active_trainable_scalar_count'] == 130
        and partition['inactive_stored_scalar_count'] == 390 and partition['active_head_rows'] == [2,3], 'Conditions partition differs')
    source='c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
    require(report['frozen_parent40_sha256_initial'] == report['frozen_parent40_sha256_final'] == source
        and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final'], 'Frozen40/inactive390 values differ')
    batches=report['batch_trace']['batches'];objective=report['objective_trace'];freeze=report['freeze_trace']
    for trace,kind in [(objective,'objective'),(freeze,'freeze')]:
        require(trace['schema'] == 'completed-conditions-balanced-adapter-'+kind+'-trace/v1'
            and trace['completed_updates'] == len(trace['batches']) == 32
            and trace['batches_sha256'] == digest(trace['batches']), 'Closed completed32trace digest differs')
    policy=report['training_policy']['objective_policy']
    require(policy['training_row_reweighting'] is True and policy['mean_all_batch_rows'] is True
        and policy['actor_ranking_enabled'] is False and policy['class_balance'] == dict(class_order=['absent','present'],counts=dict(absent=96,present=72),weights_rational=[[7,8],[7,6]],weights=[7/8,7/6],weight_rule='training_count/(2*class_count)',counts_source='authenticated_training168_conditions_presence_only',normalization='fixed_batch_row_count'), 'Fixed training-only class balance required')
    require(report['batch_trace']['training_manifest_sha256'] == digest(training)
        and [b['indices'] for b in batches] == schedule['batch_indices']
        and [b['ids'] for b in batches] == schedule['batch_ids'], 'Identical authenticated32source schedule required')
    occurrences=0;prior=None
    for step,(batch,entry,retention) in enumerate(zip(batches,objective['batches'],freeze['batches'],strict=True),1):
        require(batch['optimizer_step'] == step and all(entry[k] == retention[k] == batch[k] for k in ['optimizer_step','indices','ids'])
            and len(batch['indices']) == len(batch['ids']) == 12, 'Actual32batch source joins differ')
        require(retention['frozen_before'] == retention['frozen_after'] == source
            and retention['inactive_before'] == retention['inactive_after'] == report['inactive_head_rows_sha256_initial']
            and set(retention['changed_parameter_names']) <= set(names)
            and all(retention[k] is True for k in ['frozen_gradients_none','trainable_gradients_finite_nonNone','inactive_gradients_zero','inactive_moments_zero','completed_returned_update']),
            'Returned frozen/gradient/moment invariants differ')
        a,b=retention['branch_digests_before'],retention['branch_digests_after']
        require(set(a) == set(b) and all(a[k] == b[k] for k in a if k != 'conditions_presence_state_sha256')
            and (prior is None or prior == a), 'Only conditions presence may change and branch chain must join')
        if step == 1:require(a == report['initial_branch_digests'], 'Initial branch chain differs')
        prior=b;d=entry['details']
        require(d['conditions_cross_entropy_balanced'] == d['total_loss'] == batch['loss'] and math.isfinite(batch['loss'])
            and d['batch_denominator'] == len(d['rows']) == 12 and d['teacher_forcing'] is True
            and d['evaluation_references_used'] is d['actor_hinge_applied'] is False, 'All12 rows fixed-denominator balanced CE-only required')
        losses=[];weighted=[];weights=[];counts=dict(absent=0,present=0)
        for index,identifier,row in zip(batch['indices'],batch['ids'],d['rows'],strict=True):
            require(type(index) is int and 0 <= index < 168 and training[index]['id'] == identifier == row['id']
                and row['training_index'] == index and type(row['conditions_present']) is bool
                and row['conditions_present'] == bool(training[index]['canonical_ir']['rules'][0]['conditions'])
                and len(row['conditions_logits']) == 2 and all(math.isfinite(x) for x in row['conditions_logits']), '384 conditions targets differ')
            present=row['conditions_present'];counts['present' if present else 'absent']+=1
            expected=f32(7/6 if present else 7/8);value=row['unweighted_cross_entropy'];product=row['weighted_cross_entropy']
            require(row['class_weight'] == expected and type(value) is float and math.isfinite(value) and value >= 0
                and product == f32(expected*value), 'Actual float32 fixed class weight/product differs')
            values=row['conditions_logits'];target=1 if present else 0;delta=values[1-target]-values[target]
            independently_computed=max(0.,delta)+math.log1p(math.exp(-abs(delta)))
            require(abs(value-independently_computed) <= 2e-6*max(1.,abs(independently_computed)), 'Unweighted CE does not match source logits/label')
            losses.append(value);weights.append(expected);weighted.append(product);occurrences+=1
        near=lambda a,b: abs(a-b) <= 2e-6*max(1.,abs(b))
        require(d['batch_class_counts'] == counts and near(d['batch_weight_sum'],math.fsum(weights))
            and near(d['conditions_cross_entropy_unweighted'],math.fsum(losses)/12)
            and near(d['conditions_cross_entropy_balanced'],math.fsum(weighted)/12), 'Weighted denominator must remain12; unweighted mean separately validated')
    require(occurrences == 384 and prior == report['final_branch_digests'], 'Completed384/final model digest chain differs')
    return dict(updates=32,source_occurrences=384,frozen40=True,inactive390=True,source_target_joins=True,weights_rational=[[7,8],[7,6]],denominator='fixed12',unweighted_separately_recounted=True)



def independent_acceptance(contract, confusion, flags):
    panels=[p for p in (*PANELS,'training168') if p != 'law']
    output={key:{} for key in ['required_gain_ids_missing','complete_IR_loss_ids_vs_N10','complete_IR_loss_ids_vs_N11',
        'new_conditions_head_FP_ids_vs_N10','new_conditions_head_FN_ids_vs_N10','new_positive_head_ambiguity_ids_vs_N10',
        'N11_added_FN_target_ids','unrecovered_N11_added_FN_ids']}
    passed=True
    for panel in panels:
        original=confusion['parent',panel];candidate=confusion['trained',panel];diagnostic=confusion['frozen_N11',panel]
        for label,destination in [('FP','new_conditions_head_FP_ids_vs_N10'),('FN','new_conditions_head_FN_ids_vs_N10')]:
            old=set(original['views']['head']['conditions'][label]['ids'])
            introduced=[identifier for identifier in candidate['views']['head']['conditions'][label]['ids'] if identifier not in old]
            output[destination][panel]=sorted(introduced);passed=passed and not introduced
        old=set(original['excluded_by_gold']['head']['conditions']['gold_present']['ids'])
        introduced=sorted(set(candidate['excluded_by_gold']['head']['conditions']['gold_present']['ids'])-old)
        output['new_positive_head_ambiguity_ids_vs_N10'][panel]=introduced;passed=passed and not introduced
        targets=sorted(set(diagnostic['views']['head']['conditions']['FN']['ids'])-set(original['views']['head']['conditions']['FN']['ids']))
        output['N11_added_FN_target_ids'][panel]=targets
        missed=sorted(set(targets)-set(candidate['views']['head']['conditions']['TP']['ids']))
        output['unrecovered_N11_added_FN_ids'][panel]=missed;passed=passed and not missed
        for comparison,key in [('parent','complete_IR_loss_ids_vs_N10'),('frozen_N11','complete_IR_loss_ids_vs_N11')]:
            output[key][panel]={}
            for route in ['raw','joint']:
                old={row['id']:row[route]['full_IR'] for row in flags[comparison,panel]}
                new={row['id']:row[route]['full_IR'] for row in flags['trained',panel]}
                require(set(old) == set(new), 'Scientific paired source IDs differ')
                lost=[identifier for identifier,value in old.items() if value and not new[identifier]]
                output[key][panel][route]=lost;passed=passed and not lost
        required=contract['strict_scientific_success']['preserve_N11_complete_IR_gain_ids'].get(panel,[])
        output['required_gain_ids_missing'][panel]={}
        for route in ['raw','joint']:
            new={row['id'] for row in flags['trained',panel] if row[route]['full_IR']}
            missing=sorted(set(required)-new);output['required_gain_ids_missing'][panel][route]=missing;passed=passed and not missing
    counts={panel:len(ids) for panel,ids in output['N11_added_FN_target_ids'].items() if ids}
    require(counts == contract['strict_scientific_success']['recover_N11_added_FN_ids']['expected_panel_counts'] and sum(counts.values()) == 4,
        'Actual frozen N11 four-target metadata scope differs')
    output.update(scientific_success=bool(passed),technical_pass=True,expected_four_N11_added_FN_targets_verified=True,
        default_promotion=False,used_for_hyperparameter_or_checkpoint_selection=False,
        scope='Conjunctive preregistered exposed-diagnostic result; no blind generalization or promotion authority.')
    return output

def main():
    global FREEZE_PASSED
    require(sys.argv[1:] == [] and not os.path.lexists(OUTPUT), 'Exclusive argument-free recount required')
    sys.addaudithook(audit);own=identity(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema'] == 'conditions-balanced-result-recount-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings'] == [] and qualification['observer'] == own,
        'Exact independently qualified recounter required')
    inputs=read(INPUTS)
    require(set(inputs) == {'schema','passed','findings','freeze','analysis'} and inputs['passed'] is True and inputs['findings'] == []
        and inputs['schema'] == 'conditions-balanced-result-recount-inputs/v1'
        and inputs['freeze']['path'] == str(ROOT/'conditions-balanced-output-freeze-v01.json')
        and inputs['analysis']['path'] == str(ROOT/'conditions-balanced-result-analysis-v01.json'), 'Closed root recount inputs required')
    freeze=descriptor_read(inputs['freeze']);runtime=descriptor_read(freeze['runtime_review'])
    require(runtime['schema'] == 'conditions-balanced-runtime-independent-review/v1' and runtime['plan'] == freeze['plan'], 'Exact runtime/plan join required')
    authenticate_freeze(freeze,runtime,'conditions-balanced-output-freeze/v1');FREEZE_PASSED=True
    analysis=descriptor_read(inputs['analysis']);plan=descriptor_read(freeze['plan']);summary=descriptor_read(freeze['summary'])
    require(analysis['schema'] == 'conditions-balanced-exposed-result-analysis/v1' and analysis['passed'] is True
        and analysis['findings'] == [] and analysis['freeze'] == inputs['freeze'] and analysis['runtime_review'] == freeze['runtime_review']
        and analysis['plan'] == freeze['plan'] and (analysis['panel_count'],analysis['authored_score_sets'],analysis['paired_panel_count']) == (40,36,9),
        'Exact40/36/9 completed analysis joins required')
    contract11=descriptor_read(plan['evaluation_contract']);require(contract11['schema'] == 'conditions-balanced-evaluation-contract/v1', 'Exact contract required')
    require(plan['source_checkpoint'] == contract11['source_parent'] and plan['source_model_state_sha256'] == contract11['source_model_state_sha256'], 'Trained N10 common parent differs')
    data=descriptor_read(plan['data_export'])
    n6freeze=read(N6/'two-cell-output-freeze-v01.json',{'bytes':33740,'sha256':'a074501402f7c5f8e1dcbded4daa326989a5449507af1b1464ab5aef56978728'})
    n6contract=read(N6/'evaluation-contract-v01.json',{'bytes':27955,'sha256':'07a55d285882cac62207fb7008bbca55746c86a56c7aa3cd4a96374fdd6bf87e'})
    fullpin=n6freeze['reference_source_export'];require(n6contract['raw_artifact_pins'][fullpin['path']] == {k:fullpin[k] for k in ('bytes','sha256')}, 'Old reference custody differs')
    full=descriptor_read(fullpin);packet=descriptor_read(n6freeze['reference_packet']);populations=full['diagnostic_populations']
    populations['authored_eval']=[r['model_example'] for r in packet['geometry_review_packet']['authored_eval']]
    oldcontract=read(N7/'evaluation-contract-v01.json',{'bytes':3537,'sha256':'c6d843b39cc7e99209e4e7fd3a59e4b87e001aef5d9cbaac6e7e132034287409'})
    fresh=descriptor_read(oldcontract['fresh_reference_packet'])
    for panel in FRESH:populations[panel]=fresh['populations'][panel]
    populations['training168']=data['training_rows'];require(populations['training168'] == full['training_populations']['mixed'], 'Exact168 training reference differs')
    require(all('canonical_ir' not in r for r in populations['law']), 'Statutory gold prohibited')
    require(all(len(populations[p]) == COUNTS[p] for p in PANELS), 'Complete panel source counts differ')
    allsources=populations['training168']+sum((populations[p] for p in PANELS),[])
    require(len(allsources) == len({r['id'] for r in allsources}) == len({r['source_text'] for r in allsources}) == 632, 'Distinct632 source scope required')
    references={fullpin['path'],n6freeze['reference_packet']['path'],oldcontract['fresh_reference_packet']['path']}
    require(references <= set(plan['forbidden_reference_paths']) and not references & set(plan['artifacts']), 'Evaluation gold entered model plan')
    parent=contract11['completed_frozen_parent'];parentfreeze=descriptor_read(parent['freeze']);parentruntime=descriptor_read(parent['runtime_review'])
    authenticate_freeze(parentfreeze,parentruntime,'actor-features-output-freeze/v1');parentreview=descriptor_read(parent['independent_review'])
    require(parentreview['passed'] is True and parentreview['findings'] == [] and parentreview['freeze'] == parent['freeze']
        and parentreview['plan'] == parent['plan'] and parent['new_control_forwards'] == parent['new_control_updates'] == 0, 'Frozen parent qualification differs')
    parentsummary=descriptor_read(parentfreeze['summary']);require(parentsummary['checkpoint'] == plan['source_checkpoint'], 'Frozen trained parent checkpoint differs')
    diagnostic=contract11['completed_frozen_N11'];diagnosticfreeze=descriptor_read(diagnostic['freeze']);diagnosticruntime=descriptor_read(diagnostic['runtime_review'])
    authenticate_freeze(diagnosticfreeze,diagnosticruntime,'conditions-presence-output-freeze/v1');diagnosticreview=descriptor_read(diagnostic['independent_review'])
    require(diagnosticreview['passed'] is True and diagnosticreview['findings'] == [] and diagnosticreview['freeze'] == diagnostic['freeze']
        and diagnosticreview['plan'] == diagnostic['plan'] and diagnostic['new_control_forwards'] == diagnostic['new_control_updates'] == 0, 'N11 frozen diagnostic custody differs')
    diagnosticsummary=descriptor_read(diagnosticfreeze['summary']);require(diagnosticsummary['source_checkpoint'] == plan['source_checkpoint'], 'N11 must share same N10 donor')
    captures={}
    for state,key in [('initial','baseline_panels'),('trained','diagnostics')]:
        for panel in PANELS:captures[state,panel]=summary[key][panel]
        captures[state,'training168']=summary['initial_training_capture' if state == 'initial' else 'final_training_capture']
    for panel in PANELS:captures['parent',panel]=parentsummary['diagnostics'][panel]
    captures['parent','training168']=parentsummary['final_training_capture']
    for panel in PANELS:captures['frozen_N11',panel]=diagnosticsummary['diagnostics'][panel]
    captures['frozen_N11','training168']=diagnosticsummary['final_training_capture']
    loaded={};panels=[];records={};coverage={};confusions={};newinference=0
    for (state,panel),descriptors in captures.items():
        src=populations[panel];raw=descriptor_read(descriptors['raw']);chosen=descriptor_read(descriptors['joint'])['rows']
        require(len(src) == len(raw['occurrences']) == len(raw['inference']['rows']) == len(chosen), 'Complete capture source scope differs')
        if state not in ['parent','frozen_N11']:newinference+=len(src)
        loaded[state,panel]=raw,chosen;flags=[];cov=[]
        for source,occ,greedy,joint in zip(src,raw['occurrences'],raw['inference']['rows'],chosen,strict=True):
            sha=hashlib.sha256(source['source_text'].encode()).hexdigest();require(source['id'] == occ['id'] == joint['id'] and occ['source_sha256'] == greedy['source_sha256'] == sha, 'Saved source ID/SHA join differs')
            tokens=[dict(text=m.group(),start=m.start(),end=m.end()) for m in re.finditer(r'\w+|[^\w\s]',source['source_text'])]
            require(tokens == occ['scores']['tokens'] and 0 < len(tokens) <= 128, 'Independent tokenization differs');bits(projection(occ['scores']))
            if panel == 'law':continue
            _,gold=coordinates(source);target=source['canonical_ir']['rules'][0];row={'id':source['id']}
            for route,pred,success in [('raw',greedy,'decoded'),('joint',joint['result'],'selected')]:
                ir=pred['canonical_ir'];require((pred['status'] == success) is (ir is not None), 'Status/IR association differs')
                if ir is not None:require(set(ir) == {'rules'} and len(ir['rules']) == 1 and set(ir['rules'][0]) == {'modality',*FIELDS}, 'Closed sevenfield IR required')
                row[route]=dict(full_IR=ir == source['canonical_ir'],**{f:ir is not None and ir['rules'][0][f] == target[f] for f in ['modality',*FIELDS]})
                require(row[route]['full_IR'] == all(row[route][f] for f in ['modality',*FIELDS]), 'FullIR omitted a field')
            flags.append(row);cov.append(actor_coverage(source,occ['scores'],gold))
        item=dict(state=state,panel=panel,rows=len(src),reference_scored=panel != 'law')
        if panel != 'law':
            records[state,panel]=flags;coverage[state,panel]=cov;confusions[state,panel]=presence_recount(src,raw,chosen)
            item.update({route:{metric:sum(r[route][metric] for r in flags) for metric in ['full_IR','modality',*FIELDS]} for route in ['raw','joint']})
            item['actor_gold_coverage']=coverage_summary(cov);item['optional_presence_confusion']=confusions[state,panel]
        panels.append(item)
    require(len(panels) == 40 and len(records) == 36, 'Exact40/36 source scopes required')
    parity={};rank={};permissions={}
    for panel in (*PANELS,'training168'):
        a,b,c=(loaded[s,panel][0] for s in ['parent','initial','trained'])
        for left,first,last in zip(a['occurrences'],b['occurrences'],c['occurrences'],strict=True):
            require(left['id'] == first['id'] == last['id'] and bits(projection(left['scores'])) == bits(projection(first['scores'])), 'Initial632 full bits differ')
            require(bits(projection(left['scores'],False)) == bits(projection(last['scores'],False)), 'Final632 protected bits differ')
        for left,right in zip(loaded['frozen_N11',panel][0]['occurrences'],c['occurrences'],strict=True):
            require(left['id'] == right['id'] and bits(projection(left['scores'],False)) == bits(projection(right['scores'],False)), 'N11 diagnostic protected bits differ')
        parity[panel]=len(a['occurrences'])
        if panel != 'law':
            require([(r['id'],r['stable_rank'],r['in_top1'],r['in_top8'],r['in_top16']) for r in coverage['parent',panel]] == [(r['id'],r['stable_rank'],r['in_top1'],r['in_top8'],r['in_top16']) for r in coverage['trained',panel]], 'Frozen actor ranks/topK differ')
            rank[panel]=[r['id'] for r in coverage['trained',panel]]
    require(sum(parity.values()) == 632, 'Full632 parity scope required')
    for state in ['parent','initial','trained','frozen_N11']:
        raw,chosen=loaded[state,'old_tune'];ids=[]
        for source,g,j in zip(populations['old_tune'],raw['inference']['rows'],chosen,strict=True):
            if source['canonical_ir']['rules'][0]['modality'] == 'P':
                require(g['status'] == 'decoded' and j['result']['status'] == 'selected' and g['canonical_ir']['rules'][0]['modality'] == j['result']['canonical_ir']['rules'][0]['modality'] == 'P', 'Legacy permission lost or abstained');ids.append(source['id'])
        require(len(ids) == 32, 'Exactly32 gold permissions required');permissions[state]=dict(count=32,ids=ids,raw_P_to_P=32,joint_P_to_P=32,losses=0,abstentions=0)
    for phase,key in [('initial','initial_parity'),('trained','trained_parity')]:
        receipt=descriptor_read(summary[key]);first=None
        for control in receipt['controls']:
            raw=descriptor_read(control['report']);value=[(bits(projection(o['scores'])),g['canonical_ir'],g['status']) for o,g in zip(raw['occurrences'],raw['inference']['rows'],strict=True)]
            require(len(value) == 2 and (first is None or first == value), 'Dormant placeholders alter saved output');first=value;newinference+=2
    require(newinference == runtime['actual_inference_source_forwards'] == 1280 and runtime['actual_model_forwards'] == 1312 and runtime['actual_total_source_occurrences'] == 1664, 'Actual1312/1664 forward/source scope differs')
    report=descriptor_read(summary['training']);training=recount_training(report,populations['training168'],summary['prepared_schedule'])
    reported={(r['state'],r['panel']):r for r in analysis['panel_summaries']};require(set(reported) == set(captures), 'Analyzer40panel identity scope differs')
    for item in panels:
        e=reported[item['state'],item['panel']];require(e['row_count'] == item['rows'] and e['reference_scored'] == item['reference_scored'], 'Panel source counts differ')
        if not item['reference_scored']:
            require(e['raw_exact_ir'] is e['joint_exact_ir'] is None, 'Statutory rows scored');continue
        for route in ['raw','joint']:
            require(e[route+'_exact_ir'] == item[route]['full_IR'], 'FullIR count differs')
            modal='modality_exact' if route == 'raw' else 'joint_modality_exact';roles='role_exact_counts' if route == 'raw' else 'joint_role_exact_counts'
            require(e[modal] == item[route]['modality'] and e[roles] == {f:item[route][f] for f in FIELDS}, 'Modality/sixrole counts differ')
        require(e['actor_gold_coverage'] == item['actor_gold_coverage'], 'Actor rank/coverage recount differs')
        require(e['optional_presence_confusion'] == item['optional_presence_confusion'], 'PRIMARY optional presence head/raw/joint confusion/ambiguity/abstention recount differs')
    paired={};parentpaired={};N11paired={}
    for panel in [p for p in (*PANELS,'training168') if p != 'law']:
        paired[panel]=paired_score(records['initial',panel],records['trained',panel]);parentpaired[panel]=paired_score(records['parent',panel],records['trained',panel]);N11paired[panel]=paired_score(records['frozen_N11',panel],records['trained',panel])
    condition_transitions={}
    for panel in [p for p in (*PANELS,'training168') if p != 'law']:
        transitions={}
        for route in ['head','raw','joint']:
            before=confusions['parent',panel]['views'][route]['conditions'];after=confusions['trained',panel]['views'][route]['conditions']
            buckets={a+'_to_'+b:[] for a in before for b in after}
            for bucket in before:
                for identifier in before[bucket]['ids']:
                    target=next(k for k,v in after.items() if identifier in v['ids']);buckets[bucket+'_to_'+target].append(identifier)
            transitions[route]={k:dict(count=len(ids),ids=ids) for k,ids in buckets.items()}
        condition_transitions[panel]=transitions
    require(analysis['conditions_presence_changes'] == condition_transitions, 'Every conditions presence transition must independently recount')
    require(analysis['paired_initial_to_trained'] == paired and analysis['paired_frozen_parent_to_trained'] == parentpaired and analysis['paired_frozen_N11_to_trained'] == N11paired
        and analysis['all32_permission_retention'] == permissions and analysis['actor_rank_unchanged_ids'] == rank, 'Every paired gain/loss/permission/actor rank must match')
    for panel in (*FRESH,'training168'):
        ownpair=summary['parent_training_capture'] if panel == 'training168' else summary['parent_fresh_panels'][panel]
        priorpair=parentsummary['final_training_capture'] if panel == 'training168' else parentsummary['diagnostics'][panel]
        for view in ['raw','joint']:
            require({k:ownpair[view][k] for k in ['bytes','sha256']} == {k:priorpair[view][k] for k in ['bytes','sha256']}, 'Copied parent240rows must use exact frozen bytes')
    scientific=independent_acceptance(contract11,confusions,records)
    require(analysis['scientific_acceptance'] == scientific and analysis['scientific_success'] is scientific['scientific_success'], 'Independent strict success ID predicates disagree')
    for path,expected in list(OBSERVED.items()):identity(path,expected)
    result=dict(schema='conditions-balanced-independent-recount/v1',passed=True,findings=[],recount_source=own,source_qualification=identity(QUALIFICATION),input_manifest=identity(INPUTS),
        freeze=inputs['freeze'],analysis=inputs['analysis'],runtime_review=freeze['runtime_review'],plan=freeze['plan'],panel_count=40,authored_score_sets=36,paired_panel_count=9,
        panels=panels,paired_initial_to_trained=paired,paired_frozen_parent_to_trained=parentpaired,paired_frozen_N11_to_trained=N11paired,
        scientific_acceptance=scientific,scientific_success=scientific['scientific_success'],new_N11_forwards=0,new_N11_updates=0,all32_permission_retention=permissions,actor_rank_unchanged_ids=rank,
        optional_presence_confusion_all36_scopes_independently_recounted=True,all_primary_completeIR_modality_role_gain_loss_counts_recounted=True,
        all632_initial_and_protected_heads_bit_equal=True,all32_training_traces_recounted=True,training=training,
        actual_new_inference_forwards=1280,actual_new_model_forwards=1312,total_new_source_occurrences=1664,copied_parent_capture_rows=240,new_parent_forwards=0,new_parent_updates=0,
        external_embedding_encoder_calls=0,frozen_feature_paths_per_candidate_forward=3,statutory8_unscored=True,full_IR_includes_modality=True,
        default_promotion=False,semantic_accuracy=None,latent_enabled=False,model_or_encoder_calls=0,checkpoint_JSON_parses=0,private_body_reads=0,resource_API_calls=0,artifacts=OBSERVED)
    with OUTPUT.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    OUTPUT.chmod(0o444);print(identity(OUTPUT))


if __name__ == '__main__':main()
