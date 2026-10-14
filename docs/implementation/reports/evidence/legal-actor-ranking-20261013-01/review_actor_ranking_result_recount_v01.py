#!/usr/bin/env python3
"""Independent stdlib recount of the qualified, frozen N9 ranking result bundle and completed N8 CE reference.

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
OUTPUT=ROOT/'actor-ranking-independent-recount-v01.json'
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
    require(FREEZE_PASSED or path in {QUALIFICATION,INPUTS,ROOT/'actor-ranking-output-freeze-v01.json',ROOT/'actor-ranking-hinge-runtime-review-v01.json'},
            'No saved results, CE or reference reads before complete authenticated N9 freeze')
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


def projection(scores, actor=True):
    return {k: scores[k] if k in ('modality_logits', 'presence_logits') else
            {role: v for role, v in scores[k].items() if actor or role != 'actor'}
            for k in ('modality_logits', 'presence_logits', 'start_logits', 'end_logits')}


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


def paired_coverage(before,after):
    require([row['id'] for row in before]==[row['id'] for row in after],'Ordered paired coverage IDs required')
    result={key:[] for key in ('rank_improved_ids','rank_worsened_ids','rank_unchanged_ids')}
    for key in ('in_top1','in_top8','in_top16','full_gold_assignment_survives_retained_domain'):
        result[key+'_gained_ids']=[];result[key+'_lost_ids']=[]
    hard=dict(margin_changes=dict(improved=[],equal=[],worsened=[]),inactive_gained_ids=[],inactive_lost_ids=[],margin_at_least_one_gained_ids=[],margin_at_least_one_lost_ids=[])
    for left,right in zip(before,after,strict=True):
        key='rank_improved_ids' if right['stable_rank']<left['stable_rank'] else 'rank_worsened_ids' if right['stable_rank']>left['stable_rank'] else 'rank_unchanged_ids'
        result[key].append(left['id'])
        for field in ('in_top1','in_top8','in_top16','full_gold_assignment_survives_retained_domain'):
            if right[field] and not left[field]:result[field+'_gained_ids'].append(left['id'])
            if left[field] and not right[field]:result[field+'_lost_ids'].append(left['id'])
        a,b=left['filtered_hard_negative'],right['filtered_hard_negative']
        require(a['compatible_wrong_domain_spans']==b['compatible_wrong_domain_spans'] and a['compatible_wrong_domain_sha256']==b['compatible_wrong_domain_sha256'],'Paired gold-dependent domain differs')
        x,y=a['gold_minus_wrong_margin_float32'],b['gold_minus_wrong_margin_float32'];require((x is None)==(y is None),'Paired empty-domain status differs')
        if x is not None:hard['margin_changes']['improved' if y>x else 'worsened' if y<x else 'equal'].append(left['id'])
        if a['hinge_active'] and not b['hinge_active']:hard['inactive_gained_ids'].append(left['id'])
        if not a['hinge_active'] and b['hinge_active']:hard['inactive_lost_ids'].append(left['id'])
        if not a['margin_at_least_one'] and b['margin_at_least_one']:hard['margin_at_least_one_gained_ids'].append(left['id'])
        if a['margin_at_least_one'] and not b['margin_at_least_one']:hard['margin_at_least_one_lost_ids'].append(left['id'])
    result['filtered_hard_negative']=hard
    a,b=coverage_summary(before),coverage_summary(after)
    result['diagnostic_gain_flags']=dict(actor_rank_gain=b['top1']>a['top1'] or b['rank_sum']<a['rank_sum'],
        filtered_hinge_margin_gain=b['filtered_hard_negative']['margin_at_least_one_count']>a['filtered_hard_negative']['margin_at_least_one_count'] or b['filtered_hard_negative']['hinge_sum']<a['filtered_hard_negative']['hinge_sum'],
        top8_regression_present=bool(result['in_top8_lost_ids']),top16_regression_present=bool(result['in_top16_lost_ids']),used_for_selection_or_promotion=False)
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


def main():
    global FREEZE_PASSED
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'No arguments and exclusive recount output required')
    sys.addaudithook(audit)
    own=identity(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-ranking-result-recount-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['observer']==own,
        'Exact independent recount source qualification required')
    inputs=read(INPUTS)
    require(type(inputs) is dict and set(inputs)=={'schema','passed','findings','freeze','analysis'}
        and inputs['schema']=='actor-ranking-result-recount-inputs/v1' and inputs['passed'] is True and inputs['findings']==[]
        and inputs['freeze']['path']==str(ROOT/'actor-ranking-output-freeze-v01.json')
        and inputs['analysis']['path']==str(ROOT/'actor-ranking-result-analysis-v01.json'),'Exact root-approved recount inputs required')
    freeze=descriptor_read(inputs['freeze'])
    require(freeze['runtime_review']['path']==str(ROOT/'actor-ranking-hinge-runtime-review-v01.json'),'Exact N9 runtime producer required')
    runtime=descriptor_read(freeze['runtime_review'])
    require(runtime['schema']=='actor-ranking-runtime-independent-review/v1' and runtime['plan']==freeze['plan'],'N9 runtime/plan association differs')
    authenticate_freeze(freeze,runtime,'actor-ranking-output-freeze/v1')
    FREEZE_PASSED=True
    analysis=descriptor_read(inputs['analysis'])
    require(analysis['schema']=='actor-ranking-exposed-result-analysis/v1' and analysis['passed'] is True and analysis['findings']==[]
        and analysis['freeze']==inputs['freeze'] and analysis['runtime_review']==freeze['runtime_review'] and analysis['plan']==freeze['plan']
        and analysis['panel_count']==33 and analysis['authored_score_sets']==30 and analysis['paired_panel_count']==9,
        'Exact completed analyzer33/30/9 input joins required')
    plan = descriptor_read(freeze['plan'])
    summary = descriptor_read(freeze['summary'])
    report = descriptor_read(summary['training'])
    contract9=descriptor_read(plan['evaluation_contract'])
    require(plan['schema']=='actor-ranking-cell-plan/v1' and plan['cell']=='actor-ranking-hinge'
        and plan['source_checkpoint']['sha256']=='95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035'
        and plan['evaluation_contract']['bytes']==16689 and plan['evaluation_contract']['sha256']=='cdb22f6cf6e6d8fdb42a6bcaf5b7330c6c2f16e4d570785df5c446debd225bcb'
        and report['training_policy']['objective']=='actor-ranking-hinge'
        and report['training_policy']['objective_policy']['actor_ranking_enabled'] is True
        and report['training_policy']['objective_policy']['actor_hinge_coefficient']==.25
        and report['training_policy']['objective_policy']['actor_hinge_margin']==1.,'Exact N4-source rankingON recipe required')
    data = descriptor_read(plan['data_export'])
    n6freeze = read(N6 / 'two-cell-output-freeze-v01.json', {'bytes': 33740, 'sha256': 'a074501402f7c5f8e1dcbded4daa326989a5449507af1b1464ab5aef56978728'})
    n6contract = read(N6 / 'evaluation-contract-v01.json', {'bytes': 27955, 'sha256': '07a55d285882cac62207fb7008bbca55746c86a56c7aa3cd4a96374fdd6bf87e'})
    fullpin = n6freeze['reference_source_export']
    require(n6contract['raw_artifact_pins'][fullpin['path']] == {k: fullpin[k] for k in ('bytes', 'sha256')}, 'Old gold export authentication differs')
    full = descriptor_read(fullpin)
    oldpacket = descriptor_read(n6freeze['reference_packet'])
    populations = full['diagnostic_populations']
    populations['authored_eval'] = [r['model_example'] for r in oldpacket['geometry_review_packet']['authored_eval']]
    contract = read(N7 / 'evaluation-contract-v01.json', {'bytes': 3537, 'sha256': 'c6d843b39cc7e99209e4e7fd3a59e4b87e001aef5d9cbaac6e7e132034287409'})
    fresh = descriptor_read(contract['fresh_reference_packet'])
    for p in FRESH:
        populations[p] = fresh['populations'][p]
    populations['training168'] = data['training_rows']
    require(populations['training168'] == full['training_populations']['mixed'], 'Training168 reference differs')
    require(all('canonical_ir' not in r for r in populations['law']), 'Statutory gold prohibited')
    require(all(len(populations[p]) == COUNTS[p] for p in PANELS), 'Panel counts differ')
    all_sources = populations['training168'] + sum((populations[p] for p in PANELS), [])
    require(len(all_sources) == len({r['id'] for r in all_sources}) == len({r['source_text'] for r in all_sources}) == 632, 'Distinct632 sources required')
    reference_paths = {fullpin['path'], n6freeze['reference_packet']['path'], contract['fresh_reference_packet']['path']}
    require(reference_paths <= set(plan['forbidden_reference_paths']) and not reference_paths & set(plan['artifacts']), 'Evaluation gold entered model plan')
    captures = {}
    for state, key in (('initial', 'baseline_panels'), ('trained', 'diagnostics')):
        for p in PANELS:
            captures[state, p] = summary[key][p]
    for state, key in (('initial', 'initial_training_capture'), ('parent', 'parent_training_capture'), ('trained', 'final_training_capture')):
        captures[state, 'training168'] = summary[key]
    for p in FRESH:
        captures['parent', p] = summary['parent_fresh_panels'][p]
    for p in OLD:
        captures['parent', p] = plan['source_reference_panels'][p]
    ce_reference=contract9['completed_frozen_CE']
    require(ce_reference['new_control_updates']==0,'Completed CE reference cannot authorize new control updates')
    ce_freeze=descriptor_read(ce_reference['freeze']);ce_runtime=descriptor_read(ce_freeze['runtime_review'])
    authenticate_freeze(ce_freeze,ce_runtime,'actor-boundary-output-freeze/v1')
    ce_plan=descriptor_read(ce_reference['plan']);ce_summary=descriptor_read(ce_freeze['summary'])
    require(ce_plan['data_export']==plan['data_export'] and ce_plan['source_checkpoint']==plan['source_checkpoint']
        and ce_summary['status']=='completed' and ce_summary['actual_new_updates']==32,'Frozen CE common parent/training data differs')
    ce_report=descriptor_read(ce_summary['training'])
    require(ce_report['optimizer_steps']==32 and ce_report['training_policy']['objective_policy']['actor_ranking_enabled'] is False
        and [{k:b[k] for k in ('optimizer_step','indices','ids')} for b in ce_report['batch_trace']['batches']]
        == [{k:b[k] for k in ('optimizer_step','indices','ids')} for b in report['batch_trace']['batches']], 'Completed frozen CE OFF policy/batch schedule differs')
    for panel in (*PANELS,'training168'):
        captures['frozen_CE',panel]=ce_summary['final_training_capture'] if panel=='training168' else ce_summary['diagnostics'][panel]
    loaded, panels, records, coverage = {}, [], {}, {}
    inference_rows = 0
    for (state, panel), descriptors in captures.items():
        rows = populations[panel]
        raw, chosen = descriptor_read(descriptors['raw']), descriptor_read(descriptors['joint'])['rows']
        require(len(rows) == len(raw['occurrences']) == len(raw['inference']['rows']) == len(chosen), 'Capture row scope differs')
        require(raw['actual_source_forwards'] == len(rows) and raw['extra_capture_forwards'] == 0
                and raw['target_access'] is raw['teacher_forcing'] is False, 'Target-free actual source count differs')
        if state != 'frozen_CE' and (state != 'parent' or panel not in OLD):
            inference_rows += len(rows)
        loaded[state, panel] = raw, chosen
        rr, cov = [], []
        for src, occ, greedy, joint in zip(rows, raw['occurrences'], raw['inference']['rows'], chosen, strict=True):
            sha = hashlib.sha256(src['source_text'].encode()).hexdigest()
            require(src['id'] == occ['id'] == joint['id'] and occ['source_sha256'] == greedy['source_sha256'] == sha, 'Saved source identity differs')
            scores = occ['scores']
            tokens = [{'text': m.group(), 'start': m.start(), 'end': m.end()} for m in re.finditer(r'\w+|[^\w\s]', src['source_text'])]
            require(tokens == scores['tokens'] and 0 < len(tokens) <= 128, 'Independent complete tokenization differs')
            bits(projection(scores))
            if panel == 'law':
                continue
            tokens, gold = coordinates(src)
            target = src['canonical_ir']['rules'][0]
            flags = {'id': src['id']}
            for route, pred, success in (('raw', greedy, 'decoded'), ('joint', joint['result'], 'selected')):
                ir = pred['canonical_ir']
                require((pred['status'] == success) is (ir is not None), 'Status/IR association differs')
                if ir is not None:
                    require(set(ir) == {'rules'} and len(ir['rules']) == 1 and set(ir['rules'][0]) == {'modality', *FIELDS}, 'Closed prediction IR differs')
                flags[route] = {'full_IR': ir == src['canonical_ir'], **{f: ir is not None and ir['rules'][0][f] == target[f] for f in ('modality', *FIELDS)}}
                require(flags[route]['full_IR'] == all(flags[route][f] for f in ('modality', *FIELDS)), 'Full IR omitted a field')
            rr.append(flags)
            cov.append(actor_coverage(src,scores,gold))
        if state == 'parent' and panel in OLD:
            continue
        item = {'state': state, 'panel': panel, 'rows': len(rows), 'reference_scored': panel != 'law'}
        if panel != 'law':
            records[state, panel], coverage[state, panel] = rr, cov
            item.update({route: {metric: sum(r[route][metric] for r in rr) for metric in ('full_IR', 'modality', *FIELDS)} for route in ('raw', 'joint')})
            item['actor_gold_coverage']=coverage_summary(cov)
        panels.append(item)
    parity, changed = {}, {}
    for p in (*PANELS, 'training168'):
        parent, first, last = (loaded[s, p][0] for s in ('parent', 'initial', 'trained'))
        for a, b, c in zip(parent['occurrences'], first['occurrences'], last['occurrences'], strict=True):
            require(a['id'] == b['id'] == c['id'] and bits(projection(a['scores'])) == bits(projection(b['scores'])), 'Initial full head binary32 parity differs')
            require(bits(projection(b['scores'], False)) == bits(projection(c['scores'], False)), 'Final protected head binary32 retention differs')
        parity[p] = len(first['occurrences'])
        changed[p] = [a['id'] for a, b in zip(first['occurrences'], last['occurrences'], strict=True)
                      if bits({'start': a['scores']['start_logits']['actor'], 'end': a['scores']['end_logits']['actor']}) != bits({'start': b['scores']['start_logits']['actor'], 'end': b['scores']['end_logits']['actor']})]
    require(sum(parity.values()) == 632, 'Parity632 scope differs')
    for phase, key in (('initial', 'initial_parity'), ('trained', 'trained_parity')):
        receipt = descriptor_read(summary[key])
        require(receipt['passed'] is True and receipt['actual_encoder_calls'] == 0 and receipt['genuine_latent_semantics_tested'] is False, 'Dormant control scope differs')
        old = None
        for control in receipt['controls']:
            raw = descriptor_read(control['report'])
            current = [(occ['scores']['tokens'], bits(projection(occ['scores'])).hex(), row['canonical_ir'], row['status']) for occ, row in zip(raw['occurrences'], raw['inference']['rows'], strict=True)]
            require(len(current) == raw['actual_source_forwards'] == 2 and (old is None or current == old), 'Dormant complete readout invariance differs')
            old = current
            inference_rows += 2
    require(inference_rows == runtime['actual_inference_source_forwards'] == 1520, 'Effective inference count differs')
    require(summary['candidate_training_capture_call_sizes'] == summary['parent_training_capture_call_sizes'] == [128, 40], 'Both training capture chunk limits differ')
    require(runtime['actual_returned_optimizer_updates'] == report['optimizer_steps'] == 32 and runtime['actual_model_forwards'] == 1552
            and runtime['actual_training_source_occurrences'] == 384 and runtime['actual_total_source_occurrences'] == 1904, 'Effective update/forward/source counts differ')
    partition = report['parameter_partition']
    require(len(partition['model_parameter_names']) == 38 and len(partition['frozen_parameter_names']) == 34
            and partition['active_trainable_scalar_count'] == 130 and partition['inactive_stored_scalar_count'] == 650
            and report['frozen_base34_sha256_initial'] == report['frozen_base34_sha256_final']
            and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final'], '38/34/4 parameter/freeze partition differs')
    for name in ('objective_trace', 'freeze_trace'):
        trace = report[name]
        require(trace['completed_updates'] == len(trace['batches']) == 32 and trace['batches_sha256'] == digest(trace['batches']), '32 completed trace/hash association differs')
        require([b['indices'] for b in trace['batches']] == summary['prepared_schedule']['batch_indices'], 'Actual trace/recipe batch association differs')
    for batch in report['freeze_trace']['batches']:
        require(all(batch[k] is True for k in ('completed_returned_update', 'frozen_gradients_none', 'inactive_gradients_zero', 'inactive_moments_zero', 'trainable_gradients_finite_nonNone'))
                and batch['frozen_before'] == batch['frozen_after'] and batch['inactive_before'] == batch['inactive_after'], 'Saved per-update freeze/gradient/moment evidence differs')
    require(len(panels)==33 and len(records)==len(coverage)==30,'Independent33/30 panel scope differs')
    reported={(row['state'],row['panel']):row for row in analysis['panel_summaries']}
    require(len(reported)==33 and set(reported)=={(row['state'],row['panel']) for row in panels},'Analyzer panel identity scope differs')
    for item in panels:
        expected=reported[item['state'],item['panel']]
        require(expected['row_count']==item['rows'] and expected['reference_scored']==item['reference_scored'],'Analyzer panel count/reference flag differs')
        if not item['reference_scored']:
            require(expected['raw_exact_ir'] is expected['joint_exact_ir'] is None,'Statutory8 must remain unscored')
            continue
        for route in ('raw','joint'):
            require(expected[route+'_exact_ir']==item[route]['full_IR'],'Independent complete seven-field IR total differs')
            modal='modality_exact' if route=='raw' else 'joint_modality_exact'
            roles='role_exact_counts' if route=='raw' else 'joint_role_exact_counts'
            require(expected[modal]==item[route]['modality'] and expected[roles]=={field:item[route][field] for field in FIELDS},'Independent modality/role totals differ')
        require(expected['actor_gold_coverage']==item['actor_gold_coverage'],'Independent full actor rank/topK/filtered-hinge coverage differs')
    paired={};ce_paired={};rank_paired={};ce_rank_paired={}
    for panel in (*[panel for panel in PANELS if panel!='law'],'training168'):
        paired[panel]=paired_score(records['initial',panel],records['trained',panel])
        ce_paired[panel]=paired_score(records['frozen_CE',panel],records['trained',panel])
        rank_paired[panel]=paired_coverage(coverage['initial',panel],coverage['trained',panel])
        ce_rank_paired[panel]=paired_coverage(coverage['frozen_CE',panel],coverage['trained',panel])
    require(len(paired)==len(ce_paired)==len(rank_paired)==len(ce_rank_paired)==9,'Both nine-panel paired scopes required')
    require(analysis['paired_initial_to_trained']==paired and analysis['paired_frozen_CE_to_N9']==ce_paired,
            'Independent paired completeIR/modality/all-role gains and regressions differ')
    require(analysis['actor_gold_coverage_changes']==rank_paired and analysis['actor_coverage_frozen_CE_to_N9']==ce_rank_paired,
            'Independent paired actor rank/topK/margins/filtered-hinge changes differ')
    for panel in (*PANELS,'training168'):
        ce,last=loaded['frozen_CE',panel][0],loaded['trained',panel][0]
        require(len(ce['occurrences'])==len(last['occurrences']),'CE/N9 protected comparison row scope differs')
        for left,right in zip(ce['occurrences'],last['occurrences'],strict=True):
            require(left['id']==right['id'] and bits(projection(left['scores'],False))==bits(projection(right['scores'],False)),
                    'Completed CE/N9 protected head binary32 differs')
    focus = []
    for i, src in enumerate(populations['training168']):
        a, b = records['initial', 'training168'][i], records['trained', 'training168'][i]
        if not all(a[r]['full_IR'] and b[r]['full_IR'] for r in ('raw', 'joint')):
            focus.append({'id': src['id'], 'gold_rule': src['canonical_ir']['rules'][0], 'before': a, 'after': b,
                'initial_actor_rank': coverage['initial', 'training168'][i]['stable_rank'], 'trained_actor_rank': coverage['trained', 'training168'][i]['stable_rank'],
                'frozen_CE_score_flags':records['frozen_CE','training168'][i], 'frozen_CE_actor_rank':coverage['frozen_CE','training168'][i]['stable_rank'],
                'initial_raw': loaded['initial', 'training168'][0]['inference']['rows'][i]['canonical_ir'],
                'trained_raw': loaded['trained', 'training168'][0]['inference']['rows'][i]['canonical_ir'],
                'initial_joint': loaded['initial', 'training168'][1][i]['result']['canonical_ir'],
                'trained_joint': loaded['trained', 'training168'][1][i]['result']['canonical_ir']})
    for path,expected in list(OBSERVED.items()):identity(path,expected)
    own = identity(__file__)
    result = {'schema': 'actor-ranking-independent-recount/v1', 'passed': True, 'findings': [], 'recount_source': own, 'source_qualification':identity(QUALIFICATION), 'input_manifest':identity(INPUTS),
              'freeze':inputs['freeze'],'analysis':inputs['analysis'],'runtime_review':freeze['runtime_review'], 'plan':freeze['plan'],
              'panel_count':33,'authored_score_sets':30,'paired_panel_count':9,
              'all_analyzer_panel_metrics_recounted':True,'full_IR_includes_modality':True,
              'panels': panels, 'paired': paired,'paired_frozen_CE_to_N9':ce_paired,
              'actor_gold_coverage_changes':rank_paired,'actor_coverage_frozen_CE_to_N9':ce_rank_paired,
              'completed_frozen_CE_new_control_updates':0,'frozen_CE_N9_protected632_equal':True, 'training_failure_review': focus, 'protected_head_rows': parity, 'actor_changed_ids': changed,
              'inference_source_forwards': inference_rows, 'model_forwards': 1552, 'training_updates': 32, 'training_source_occurrences': 384,
              'total_source_occurrences': 1904, 'original34_frozen': True, 'inactive_gradient_and_Adam_moments_zero_all32_updates': True,
              'checkpoint_JSON_parses': 0, 'model_or_encoder_calls': 0, 'semantic_accuracy': None, 'statutory8_unscored': True,
              'latent_enabled': False, 'configured_dimension': 384, 'default_promotion': False, 'artifacts': OBSERVED}
    out = OUTPUT
    with out.open('x') as handle:
        json.dump(result, handle, indent=2, sort_keys=True, ensure_ascii=False,allow_nan=False)
        handle.write('\n')
    out.chmod(0o444)
    print(json.dumps(identity(out)))
    for p in panels:
        if p['panel'] == 'training168':
            print(json.dumps(p))


if __name__ == '__main__':
    main()
