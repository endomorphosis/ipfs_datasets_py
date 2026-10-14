"""Parent-only F14 execution analysis of a qualified, durable62-output conditions-balanced run.

No model/encoder, production module import, numerical library, checkpoint JSON,
private resource body, resource API, subprocess, network or Git is used. Only
explicitly pinned pure saved-score/selector/scorer definitions are detached.
Existing authored references remain outside model plans and are opened only
after the complete62-output freeze. All panels are exposed diagnostics.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
from types import SimpleNamespace



ROOT = Path(__file__).resolve().parent
N10 = ROOT.parent / 'legal-actor-features-20261013-01'
N11 = ROOT.parent / 'legal-head-repair-20261014-01'
N9 = ROOT.parent / 'legal-actor-ranking-20261013-01'
N8 = ROOT.parent / 'legal-actor-boundary-20261013-01'
N7 = ROOT.parent / 'legal-temporal-attention-20261013-01'
N6 = ROOT.parent / 'legal-temporal-adapter-20261013-01'
N2 = ROOT.parent / 'legal-targeted-loss-20261012-01'
T = ROOT.parent / 'legal-temporal-binding-20261012-01'
FIELDS = ('actor','action','object','conditions','exceptions','temporal')
ALL_FIELDS = ('modality',*FIELDS)
OLD_PANELS = ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law')
FRESH_PANELS = ('fresh_dev','fresh_test')
PANELS = OLD_PANELS + FRESH_PANELS
COUNTS = dict(zip(PANELS,(96,36,36,72,72,72,8,36,36),strict=True))
MODALITIES = ('O','P','F')
SOURCE_SHA = 'b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3'
SOURCE_STATE = 'c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
FALSE = dict(qualified=False,admitted=False,formalized=False,proof_authority=False,
             semantic_correctness_verified=False,promotion_performed=False)
EXPECTED,OBSERVED = {},{}
FREEZE_PASSED = False
FIXED = {
 N7/'evaluation-contract-v01.json':(3537,'c6d843b39cc7e99209e4e7fd3a59e4b87e001aef5d9cbaac6e7e132034287409'),
 N7/'temporal-attention-ce-plan-v02.json':(45849,'1dc68107c10019276a12681cf74e6efe3c1d117151a657b0c1fe70af643ae60f'),
 N6/'evaluation-contract-v01.json':(27955,'07a55d285882cac62207fb7008bbca55746c86a56c7aa3cd4a96374fdd6bf87e'),
 N6/'two-cell-output-freeze-v01.json':(33740,'a074501402f7c5f8e1dcbded4daa326989a5449507af1b1464ab5aef56978728'),
 N6/'training-source-export-v01.json':(4675279,'ea377724beeffcfc7e8565b03ed207a90cdf3a1955f4ba7d0bfea460ba94c3a9'),
 N2/'analyze_targeted_results_v01.py':(66275,'4274d682da303954689bbb318750a91a49b407961f26d718104e1890a0ae4d0f'),
 T/'run_temporal_contrast_pilot.py':(42637,'0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'),
 N8/'n7-training168-full-ir-modality-audit-v01.json':(933868,'9cff6f563e42537c1a626d50f0ef4ba56f9b423c564ec0b045dbd1df42b0c535'),
 ROOT/'evaluation-contract-v01.json':(15724,'cdd58af7b0b0abbb5e8523e23682a53f26ef28bf30e4b0f9090c4a88aeacf837'),
}


def require(value, message):
    if not value:
        raise ValueError(message)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def pin(path, expected=None):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not private(path), 'Physical public absolute input required')
    for part in (*reversed(path.parents), path):
        item = part.lstat()
        require(not stat.S_ISLNK(item.st_mode), 'Symlink input rejected')
        require(stat.S_ISREG(item.st_mode) if part == path else stat.S_ISDIR(item.st_mode), 'Ordinary input required')
    before = path.stat()
    hashed, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            hashed.update(block)
            size += len(block)
    after = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(after) and size == before.st_size, 'Input drift during hashing')
    actual = dict(bytes=size, sha256=hashed.hexdigest())
    if expected is not None:
        wanted = {k: expected[k] for k in ('bytes', 'sha256')}
        require(actual == wanted and ('path' not in expected or expected['path'] == str(path)), 'Input pin mismatch')
        require(str(path) not in EXPECTED or EXPECTED[str(path)] == wanted, 'Conflicting expected identity')
        EXPECTED[str(path)] = wanted
    require(str(path) not in OBSERVED or OBSERVED[str(path)] == actual, 'Input changed since opening')
    OBSERVED[str(path)] = actual
    return dict(path=str(path), **actual)

def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'private-runtime-snapshots' not in path.parts,
            'Checkpoint and private body parsing prohibited')
    captured = pin(path, expected)
    require(captured['bytes'] <= 16 * 1024 * 1024, 'Bounded JSON required')
    raw = path.read_bytes()
    require(len(raw) == captured['bytes'] and hashlib.sha256(raw).hexdigest() == captured['sha256'], 'Consumed bytes drift')
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    def finite(item):
        if type(item) is float:
            require(math.isfinite(item), 'Finite JSON floats required')
        elif type(item) is list:
            for child in item:
                finite(child)
        elif type(item) is dict:
            for child in item.values():
                finite(child)
    finite(value)
    pin(path, captured)
    return value

def detached(path, names, namespace):
    path = Path(path)
    require(str(path) in EXPECTED, 'Pinned source required before pure AST extraction')
    captured = pin(path, EXPECTED[str(path)])
    require(captured['bytes'] < 1024 * 1024, 'Bounded source required')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == captured['sha256'], 'Consumed source drift')
    nodes = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    require(len(nodes) == len(names) and {n.name for n in nodes} == set(names), 'Exact pure predicate set required')
    require(not any(n.decorator_list for n in nodes), 'Decorators prohibited')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    pin(path, captured)
    return namespace

def source_projection(rows):
    return [{k: row[k] for k in ('id', 'source_text', 'latent')} for row in rows]

def structural_validity(rows, raw, chosen, gold_coordinates):
    counts = {view: dict(decoded_or_selected=0, copied_single_rule_structurally_valid=0, invalid=0, abstained=0)
              for view in ('greedy', 'joint')}
    for source, g, j in zip(rows, raw['inference']['rows'], chosen, strict=True):
        for view, record, success in (('greedy', g, 'decoded'), ('joint', j['result'], 'selected')):
            value = counts[view]
            if record['status'] != success:
                require(record['canonical_ir'] is None, 'Abstention with nonnull canonical IR')
                value['abstained'] += 1
                continue
            value['decoded_or_selected'] += 1
            try:
                gold_coordinates(dict(source_text=source['source_text'], canonical_ir=record['canonical_ir']))
            except (ValueError, KeyError, TypeError):
                value['invalid'] += 1
            else:
                value['copied_single_rule_structurally_valid'] += 1
    return counts

def private(path):
    p=Path(path)
    return ('private-runtime-snapshots' in p.parts or 'disk-reservations' in p.parts
            or p.name in {'resources-start.json','resources-final.json','resources-final-failure.json',
                          'scheduler.json','scheduler-state.json','resource-ledger.json','reservations.json','disk-reservations.json'}
            or p.name.startswith('ipfs-datasets-resource-scheduler-'))

def fixed(path):
    size,sha=FIXED[Path(path)]
    return {'path':str(path),'bytes':size,'sha256':sha}

def descriptor(value):
    require(type(value) is dict and set(value) == {'path','bytes','sha256'}
            and type(value['path']) is str and Path(value['path']).is_absolute()
            and type(value['bytes']) is int and 0 <= value['bytes'] <= 200000000
            and type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['sha256'])
            and not private(value['path']), 'Closed bounded public raw descriptor required')
    return value

def f32(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite scalar required')
    value=struct.unpack('!f',struct.pack('!f',value))[0]
    require(math.isfinite(value),'Finite binary32 required')
    return value

def binary(value):
    if type(value) is dict:
        return b''.join(binary(value[k]) for k in sorted(value))
    if type(value) is list:
        return b''.join(binary(v) for v in value)
    require(type(value) in (int,float) and f32(value) == value,'Exact saved binary32 required')
    return struct.pack('!f',value)

def guarded_choice(values):
    require(type(values) is list and len(values) >= 2,'Decision logits required')
    order=sorted(range(len(values)),key=lambda i:(-values[i],i))
    margin=f32(values[order[0]]-values[order[1]])
    return (None if margin <= 1e-7 else order[0]),margin

def expected_names():
    names={'summary.json','cell-checkpoint.json','cell-training.json','data-schedule-before-models.json',
           'initial-parent-head-parity.json','trained-frozen-head-retention.json'}
    for state in ('baseline','trained'):
        names.update(f'{state}-{p}-{kind}.json' for p in PANELS for kind in ('raw','joint'))
    for label in ('parent-training168','initial-training168','trained-training168',
                  'parent-fresh_dev','parent-fresh_test'):
        names.update(label+'-'+kind+'.json' for kind in ('raw','joint'))
    for phase in ('initial','trained'):
        names.add(phase+'-parity.json')
        names.update(phase+'-parity-'+name+'.json' for name in
                     ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    require(len(names) == 62,'Exact62-file geometry differs')
    return names

def validate_freeze(freeze,freeze_path,*,metadata_root=ROOT,schema='actor-features-output-freeze/v1'):
    require(freeze.get('schema') == schema
            and freeze.get('all_outputs_frozen') is True
            and freeze.get('authorizes_authored_eval_scoring') is True
            and freeze.get('statutory_reference_scoring_authorized') is False
            and freeze.get('actual_returned_optimizer_updates') == 32
            and freeze.get('default_promotion') is False and freeze.get('semantic_accuracy') is None,
            'Qualified durable62-output parent-scoring freeze required')
    summary=descriptor(freeze['summary']);root=Path(summary['path']).parent
    require(root.is_absolute() and root.resolve() == root and not root.is_symlink()
            and len(freeze['results']) == 62
            and set(freeze['results']) == {str(root/name) for name in expected_names()},'Exact frozen62 path set required')
    require({p.name for p in root.iterdir()} == expected_names(),'Result directory contains an extra or missing entry')
    for path,identity in freeze['results'].items():
        p=Path(path)
        require(p.is_file() and not p.is_symlink() and p.stat().st_mode & 0o222 == 0,'Frozen ordinary result file required')
        pin(p,{'path':path,**identity})
    require(summary == {'path':summary['path'],**freeze['results'][summary['path']]},'Frozen summary pin differs')
    require(Path(freeze_path).parent == metadata_root,'Owned metadata freeze required')
    return root

def bind(value,freeze,root,name):
    value=descriptor(value)
    require(value['path'] == str(root/name) and value == {'path':value['path'],**freeze['results'][value['path']]},
            'Summary descriptor differs from exact frozen output')
    require('checkpoint' not in name,'Checkpoint JSON must remain opaque')
    return read(value['path'],value)

def references(plan):
    require(FREEZE_PASSED,'No reference reads before durable complete freeze')
    data=read(N6/'training-source-export-v01.json',fixed(N6/'training-source-export-v01.json'))
    require(plan['data_export'] == fixed(N6/'training-source-export-v01.json'),'Exact retained168 training/source export required')
    old=read(N6/'two-cell-output-freeze-v01.json',fixed(N6/'two-cell-output-freeze-v01.json'))
    n6contract=read(N6/'evaluation-contract-v01.json',fixed(N6/'evaluation-contract-v01.json'))
    fullpin=descriptor(old['reference_source_export'])
    require(n6contract['raw_artifact_pins'][fullpin['path']] == {k:fullpin[k] for k in ('bytes','sha256')},
            'Retained parent reference export authentication differs')
    full=read(fullpin['path'],fullpin)
    oldpacket=read(old['reference_packet']['path'],old['reference_packet'])
    populations=deepcopy(full['diagnostic_populations']);metadata=deepcopy(full['diagnostic_metadata'])
    populations['authored_eval']=[r['model_example'] for r in oldpacket['geometry_review_packet']['authored_eval']]
    metadata['authored_eval']=[{k:r[k] for k in ('id','class_name','group_id','pair_id','pair_variant')}
                              for r in oldpacket['geometry_review_packet']['authored_eval']]
    require({p:source_projection(populations[p]) for p in OLD_PANELS} == data['diagnostic_sources'],
            'Old392 source/reference joins differ')
    contract=read(N7/'evaluation-contract-v01.json',fixed(N7/'evaluation-contract-v01.json'))
    packet=read(contract['fresh_reference_packet']['path'],contract['fresh_reference_packet'])
    review=read(contract['fresh_reference_review']['path'],contract['fresh_reference_review'])
    fresh=read(contract['fresh_source_export']['path'],contract['fresh_source_export'])
    require(plan['fresh_source_export'] == contract['fresh_source_export']
            and review['passed'] is True and review['findings'] == [] and review['rows'] == 72
            and review['semantic_accuracy'] is None and review['independent_statutory_gold'] is False
            and review['artifacts'][contract['fresh_reference_packet']['path']] == contract['fresh_reference_packet']
            and packet['source_export'] == contract['fresh_source_export'],'Exposed fresh72 authenticated reference join differs')
    reference_paths={fullpin['path'],old['reference_packet']['path'],contract['fresh_reference_packet']['path'],
                     contract['fresh_reference_review']['path']}
    require(not reference_paths & set(plan['artifacts'])
            and reference_paths <= set(plan['forbidden_reference_paths']), 'Evaluation references entered model plan closure')
    for panel in FRESH_PANELS:
        populations[panel]=[dict(r,latent=[0.]*384) for r in packet['populations'][panel]]
        metadata[panel]=[]
        for row,meta in zip(populations[panel],packet['metadata'][panel],strict=True):
            require(row['id'] == meta['id'] and meta['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
                    and meta['modality'] == row['canonical_ir']['rules'][0]['modality']
                    and meta['main_action_temporal_present'] is bool(row['canonical_ir']['rules'][0]['temporal']),
                    'Exposed fresh authored label/source metadata differs')
            metadata[panel].append(dict(id=row['id'],class_name=meta['lexical_construction'],group_id=meta['broad_group'],
                pair_id=meta['pair_id'],pair_variant='temporal_present' if meta['main_action_temporal_present'] else 'temporal_absent'))
        require(source_projection(populations[panel]) == fresh['populations'][panel],'Fresh source-only/reference joins differ')
    training=data['training_rows']
    require(len(training) == 168 and training == full['training_populations']['mixed']
            and data['training_metadata'] == full['training_metadata']['mixed'],'Exact retained168 gold required')
    for panel in PANELS:
        require(len(populations[panel]) == COUNTS[panel],'Exact exposed panel count differs')
    require(all('canonical_ir' not in r for r in populations['law']),'Statutory8 reference gold prohibited')
    allrows=training+sum((populations[p] for p in PANELS),[])
    require(len(allrows) == len({r['id'] for r in allrows}) == len({r['source_text'] for r in allrows}) == 632,
            'Distinct complete632 source scope differs')
    return data,populations,metadata

def validate_joint(value,raw,rows,joint):
    require(value['schema'] in {'conditions-balanced-joint-panel/v1','conditions-presence-joint-panel/v1','actor-features-joint-panel/v1','actor-ranking-joint-panel/v1','actor-boundary-joint-panel/v1','split-feature-joint-panel/v1'}
            and value['top_k'] == 8 and value['max_search_nodes'] == 50000
            and len(value['rows']) == len(rows),'Saved bounded joint geometry differs')
    for source,occ,row in zip(rows,raw['occurrences'],value['rows'],strict=True):
        require(source['id'] == row['id'] and row['result'] == joint['select_joint_spans'](
            source['source_text'],occ['scores'],top_k=8,max_search_nodes=50000),'Saved pure joint replay differs')
    return value['rows']

def span_ranking(scores,field):
    starts,ends=scores['start_logits'][field],scores['end_logits'][field]
    require(len(starts) == len(ends) == len(scores['tokens']) and 1 <= len(starts) <= 128,'Complete bounded span vectors required')
    candidates=[(f32(starts[left]+ends[right]),left,right) for left in range(len(starts)) for right in range(left,len(ends))]
    candidates.sort(key=lambda row:(-row[0],row[1],row[2]))
    return candidates

def span_coverage(scores,field,coordinates):
    candidates=span_ranking(scores,field)
    matches=[i for i,row in enumerate(candidates) if row[1:] == tuple(coordinates)]
    require(len(matches) == 1,'Unique valid gold span in full domain required')
    index=matches[0];score=candidates[index][0]
    result={'stable_rank':index+1,'gold_score_float32':score,'full_domain_spans':len(candidates),
            'higher_score_spans':sum(row[0] > score for row in candidates),
            'equal_score_spans':sum(row[0] == score for row in candidates),
            'tied_within_guard_spans':sum(abs(f32(row[0]-score)) <= 1e-7 for row in candidates),
            'coordinates':list(coordinates)}
    for top in (1,8,16):
        result['in_top'+str(top)]=index < top
        result['top'+str(top)+'_boundary_tied_within_guard']=(len(candidates) > top
            and f32(candidates[top-1][0]-candidates[top][0]) <= 1e-7)
    return result

def hard_negative(scores,coordinates,targeted):
    """Reuse qualified training-domain predicate on frozen saved logits only."""
    domain=targeted['_actor_domain'](len(scores['tokens']),coordinates['actor'],
                                     {f:v for f,v in coordinates.items() if f != 'actor'})
    starts,ends=scores['start_logits']['actor'],scores['end_logits']['actor']
    left,right=coordinates['actor'];gold=f32(starts[left]+ends[right])
    choices=[(f32(starts[left]+ends[right]),left,right) for left,right in domain]
    wrong=max(choices,key=lambda row:row[0]) if choices else None
    hinge=0. if wrong is None else max(0.,f32(f32(1.+wrong[0])-gold))
    return {'compatible_wrong_domain_spans':len(domain),'compatible_wrong_domain_sha256':digest(domain),
        'gold_score_float32':gold,'chosen_wrong_coordinates':None if wrong is None else list(wrong[1:]),
        'chosen_wrong_score_float32':None if wrong is None else wrong[0],
        'chosen_wrong_exact_tie_count':0 if wrong is None else sum(r[0] == wrong[0] for r in choices),
        'gold_minus_wrong_margin_float32':None if wrong is None else f32(gold-wrong[0]),
        'margin_at_least_one':False if wrong is None else f32(gold-wrong[0]) >= 1.,
        'hinge_float32':hinge,'hinge_active':hinge > 0.,'empty_domain':wrong is None,
        'scope':'Post-freeze gold-dependent filtered training-domain diagnostic; not inference candidate coverage.'}

def gold_coverage(row,scores,gold_coordinates,joint,targeted):
    tokens,coordinates=gold_coordinates(row)
    require(tokens == scores['tokens'],'Gold/source complete token geometry differs')
    target=row['canonical_ir']['rules'][0]
    actor=span_coverage(scores,'actor',coordinates['actor'])
    require(span_ranking(scores,'actor') == joint['_rank_spans'](scores,'actor')[0],
            'Independent full actor ranking differs from qualified selector')
    choice,margin=guarded_choice(scores['modality_logits'])
    modality=choice is not None and MODALITIES[choice] == target['modality']
    fixed_correct=modality;presence={}
    for field in FIELDS[2:]:
        winner,unused=guarded_choice(scores['presence_logits'][field])
        presence[field]=winner is not None and (winner == 1) is (field in coordinates)
        fixed_correct &= presence[field]
    roles={field:span_coverage(scores,field,span)['in_top8'] for field,span in coordinates.items()}
    return {'id':row['id'],**actor,'fixed_modality_correct':modality,'fixed_presence_correct':presence,
            'all_fixed_head_decisions_correct':bool(fixed_correct),'gold_present_role_top8_coverage':roles,
            'all_gold_present_role_spans_in_top8':all(roles.values()),'gold_nonoverlap_compatible':True,
            'full_gold_assignment_survives_retained_domain':bool(fixed_correct and all(roles.values())),
            'filtered_hard_negative':hard_negative(scores,coordinates,targeted)}

def independent_score_checks(rows,raw,joint_rows,score):
    require(len(score['rows']) == len(rows),'Full score row scope differs')
    records=[]
    for src,g,j,reported in zip(rows,raw['inference']['rows'],joint_rows,score['rows'],strict=True):
        reference=src['canonical_ir'];target=reference['rules'][0]
        require(set(reference) == {'rules'} and len(reference['rules']) == 1 and set(target) == set(ALL_FIELDS),
                'Closed full seven-field authored IR required')
        for route,pred,status,selected in [('raw',g['canonical_ir'],g['status'],'decoded'),
                                          ('joint',j['result']['canonical_ir'],j['result']['status'],'selected')]:
            require((status == selected) is (pred is not None),'Saved status/IR agreement differs')
            if pred is not None:
                require(set(pred) == {'rules'} and len(pred['rules']) == 1
                        and set(pred['rules'][0]) == set(ALL_FIELDS),'Closed selected seven-field IR required')
            rule=None if pred is None else pred['rules'][0]
            flags={f:rule is not None and rule[f] == target[f] for f in ALL_FIELDS}
            exact=pred == reference
            require(exact == all(flags.values()) and reported[route+'_exact_ir'] is exact,
                    'Whole-IR equality (including modality) differs from qualified scorer')
            role_key='role_exact' if route == 'raw' else 'joint_role_exact'
            modal_key='modality_exact' if route == 'raw' else 'joint_modality_exact'
            require(reported[role_key] == {f:flags[f] for f in FIELDS}
                    and reported[modal_key] is flags['modality'],'Independent role/modality check differs')
        records.append(reported)
    require(score['raw_exact_ir'] == sum(r['raw_exact_ir'] for r in records)
            and score['joint_exact_ir'] == sum(r['joint_exact_ir'] for r in records),'Independent exact totals differ')

def modality_summary(rows,raw,chosen):
    confusion={view:{gold:{pred:0 for pred in (*MODALITIES,'abstained')} for gold in MODALITIES}
               for view in ('head','greedy','joint')}
    permission={view:dict(P_to_P=0,P_to_O=0,P_to_F=0,P_abstentions=0) for view in confusion}
    for src,occ,g,j in zip(rows,raw['occurrences'],raw['inference']['rows'],chosen,strict=True):
        gold=src['canonical_ir']['rules'][0]['modality'];winner,unused=guarded_choice(occ['scores']['modality_logits'])
        values={'head':None if winner is None else MODALITIES[winner],
                'greedy':None if g['canonical_ir'] is None else g['canonical_ir']['rules'][0]['modality'],
                'joint':None if j['result']['canonical_ir'] is None else j['result']['canonical_ir']['rules'][0]['modality']}
        for view,mode in values.items():
            confusion[view][gold][mode or 'abstained']+=1
            if gold == 'P':
                permission[view]['P_to_'+mode if mode else 'P_abstentions']+=1
    return confusion,permission

def failure_overlap(records,route):
    roles='role_exact' if route == 'raw' else 'joint_role_exact'
    modality='modality_exact' if route == 'raw' else 'joint_modality_exact'
    patterns=Counter()
    for row in records:
        bad=[f for f in ALL_FIELDS if not (row[modality] if f == 'modality' else row[roles][f])]
        patterns[','.join(bad) or 'EXACT']+=1
    return {'modality_and_actor_nonmatch':sum(not r[modality] and not r[roles]['actor'] for r in records),
            'modality_without_actor_nonmatch':sum(not r[modality] and r[roles]['actor'] for r in records),
            'actor_without_modality_nonmatch':sum(r[modality] and not r[roles]['actor'] for r in records),
            'modality_only_full_IR_failure':sum(not r[modality] and all(r[roles].values()) for r in records),
            'mismatched_field_patterns':dict(patterns),
            'abstentions_included_as_nonmatches':True}

def coverage_summary(records):
    hinge=[r['filtered_hard_negative'] for r in records]
    margins=[r['gold_minus_wrong_margin_float32'] for r in hinge if not r['empty_domain']]
    return {'rows':len(records),'top1':sum(r['in_top1'] for r in records),'top8':sum(r['in_top8'] for r in records),
            'top16':sum(r['in_top16'] for r in records),'rank_min':min(r['stable_rank'] for r in records),
            'rank_max':max(r['stable_rank'] for r in records),'rank_sum':sum(r['stable_rank'] for r in records),
            'top8_boundary_tied_within_guard':sum(r['top8_boundary_tied_within_guard'] for r in records),
            'top16_boundary_tied_within_guard':sum(r['top16_boundary_tied_within_guard'] for r in records),
            'fixed_modality_correct':sum(r['fixed_modality_correct'] for r in records),
            'all_fixed_head_decisions_correct':sum(r['all_fixed_head_decisions_correct'] for r in records),
            'all_gold_present_role_spans_in_top8':sum(r['all_gold_present_role_spans_in_top8'] for r in records),
            'full_gold_assignment_survives_retained_domain':sum(r['full_gold_assignment_survives_retained_domain'] for r in records),
            'actor_not_in_top8_ids':[r['id'] for r in records if not r['in_top8']],
            'fixed_modality_incorrect_ids':[r['id'] for r in records if not r['fixed_modality_correct']],
            'fixed_presence_incorrect_ids':{f:[r['id'] for r in records if not r['fixed_presence_correct'][f]]
                for f in FIELDS[2:]},
            'fixed_head_blocker_ids':[r['id'] for r in records if not r['all_fixed_head_decisions_correct']],
            'fixed_blocker_and_actor_not_top8_ids':[r['id'] for r in records
                if not r['all_fixed_head_decisions_correct'] and not r['in_top8']],
            'present_role_top8':{f:{'present':sum(f in r['gold_present_role_top8_coverage'] for r in records),
                'retained':sum(r['gold_present_role_top8_coverage'].get(f,False) for r in records),
                'not_retained_ids':[r['id'] for r in records
                    if f in r['gold_present_role_top8_coverage'] and not r['gold_present_role_top8_coverage'][f]]}
                for f in FIELDS},
            'full_gold_assignment_not_retained_ids':[r['id'] for r in records if not r['full_gold_assignment_survives_retained_domain']],
            'filtered_hard_negative':{'rows':len(hinge),'nonempty_domain_count':len(margins),
                'empty_domain_count':sum(r['empty_domain'] for r in hinge),
                'hinge_active_count':sum(r['hinge_active'] for r in hinge),
                'hinge_inactive_count':sum(not r['hinge_active'] for r in hinge),
                'hinge_sum':math.fsum(r['hinge_float32'] for r in hinge),
                'hinge_mean':math.fsum(r['hinge_float32'] for r in hinge)/len(hinge),
                'minimum_gold_minus_wrong_margin':min(margins) if margins else None,
                'mean_gold_minus_wrong_margin':math.fsum(margins)/len(margins) if margins else None,
                'margin_at_least_one_count':sum(r['margin_at_least_one'] for r in hinge)},
            'full_rank_records_sha256':digest(records),
            'scope':'Reference-dependent post-freeze diagnostic; no gold inserted into selector or model.'}

def panel_score(panel,state,rows,metadata,raw,chosen,scorer,namespace,joint):
    envelope={'panel':panel,'state':state,'row_count':len(rows),'semantic_accuracy':None,
              'reference_scored':panel != 'law','exposed_diagnostic_only':True,'used_for_selection_or_promotion':False}
    if panel == 'law':
        envelope.update(raw_exact_ir=None,joint_exact_ir=None,raw_actor_exact=None,joint_actor_exact=None,
            modality_exact=None,joint_modality_exact=None,temporal_presence_correct=None,
            raw_abstentions=sum(r['status'] != 'decoded' for r in raw['inference']['rows']),
            joint_abstentions=sum(r['result']['status'] != 'selected' for r in chosen),
            scoring_status='UNSCORED_UNREVIEWED_STATUTORY8')
        return envelope,None,None
    score=scorer['score_panel'](rows,metadata,raw,chosen)
    independent_score_checks(rows,raw,chosen,score)
    envelope.update({key:value for key,value in score.items() if key not in
        {'rows','schema','reference_scope','semantic_accuracy','used_for_updates_or_selection','pairwise_consistency',*FALSE}})
    envelope['joint_abstentions']=sum(r['result']['status'] != 'selected' for r in chosen)
    envelope['raw_actor_exact']=score['role_exact_counts']['actor']
    envelope['joint_actor_exact']=score['joint_role_exact_counts']['actor']
    envelope['modality_confusion'],envelope['permission_outcomes']=modality_summary(rows,raw,chosen)
    envelope['optional_presence_confusion']=optional_presence_confusion(rows,raw,chosen)
    envelope['failure_overlap']={route:failure_overlap(score['rows'],route) for route in ('raw','joint')}
    envelope['scoring_status']='TRAINING_AUTHORED_ENGINEERING_ONLY' if panel == 'training168' else 'EXPOSED_AUTHORED_ENGINEERING_DIAGNOSTIC_ONLY'
    selected={'raw':{r['id'] for r,g in zip(rows,raw['inference']['rows'],strict=True) if g['status'] == 'decoded'},
              'joint':{r['id'] for r,j in zip(rows,chosen,strict=True) if j['result']['status'] == 'selected'}}
    envelope['selected_only_failure_overlap']={route:failure_overlap(
        [r for r in score['rows'] if r['id'] in selected[route]],route) for route in ('raw','joint')}
    for value in envelope['selected_only_failure_overlap'].values():
        value['abstentions_included_as_nonmatches']=False
    envelope['abstention_reasons']={
        'raw':dict(Counter(r.get('reason') or 'UNSPECIFIED' for r in raw['inference']['rows'] if r['status'] != 'decoded')),
        'joint':dict(Counter(r['result'].get('reason') or 'UNSPECIFIED' for r in chosen if r['result']['status'] != 'selected'))}
    envelope['abstention_ids']={'raw':[r['id'] for r,g in zip(rows,raw['inference']['rows'],strict=True)
                                      if g['status'] != 'decoded'],
        'joint':[r['id'] for r,j in zip(rows,chosen,strict=True) if j['result']['status'] != 'selected']}
    coverage=[gold_coverage(row,occ['scores'],namespace['gold_coordinates'],joint,namespace['targeted_pure'])
              for row,occ in zip(rows,raw['occurrences'],strict=True)]
    envelope['actor_gold_coverage']=coverage_summary(coverage)
    envelope['source_id_scope_sha256']=digest([r['id'] for r in rows])
    envelope['pair_consistency_counts']={key:sum(r[key] for r in score['pairwise_consistency'])
        for key in ('comparisons','raw_both_exact','joint_both_exact','temporal_both_correct')}
    if panel in FRESH_PANELS:
        groups={}
        for group in sorted({r['group_id'] for r in metadata}):
            indices=[i for i,row in enumerate(metadata) if row['group_id'] == group]
            subset=[score['rows'][i] for i in indices]
            groups[group]={'rows':len(indices),'raw_exact_ir':sum(r['raw_exact_ir'] for r in subset),
                'joint_exact_ir':sum(r['joint_exact_ir'] for r in subset),
                'raw_actor_exact':sum(r['role_exact']['actor'] for r in subset),
                'joint_actor_exact':sum(r['joint_role_exact']['actor'] for r in subset),
                'modality_exact':sum(r['modality_exact'] for r in subset),
                'joint_modality_exact':sum(r['joint_modality_exact'] for r in subset),
                'temporal_presence_correct':sum(r['temporal_presence_correct'] for r in subset)}
        envelope['fresh_exposed_construction_groups']=groups
    return envelope,score['rows'],coverage

def paired_changes(before,after):
    require([r['id'] for r in before] == [r['id'] for r in after],'Exact paired score row IDs required')
    result={}
    for route,roles,modal in [('raw','role_exact','modality_exact'),('joint','joint_role_exact','joint_modality_exact')]:
        getters={'full_IR':lambda r:r[route+'_exact_ir'],'modality':lambda r:r[modal],
                 **{field:(lambda r,f=field:r[roles][f]) for field in FIELDS}}
        result[route]={}
        for metric,getter in getters.items():
            gain=[a['id'] for a,b in zip(before,after,strict=True) if not getter(a) and getter(b)]
            loss=[a['id'] for a,b in zip(before,after,strict=True) if getter(a) and not getter(b)]
            result[route][metric]={'before_correct':sum(getter(r) for r in before),'after_correct':sum(getter(r) for r in after),
                                   'gains':len(gain),'losses':len(loss),'gain_ids':gain,'loss_ids':loss}
    return result

def decoded_coupling(before,after,before_joint,after_joint):
    result={}
    for route,old,new in [('raw',before['inference']['rows'],after['inference']['rows']),
                          ('joint',[r['result'] for r in before_joint],[r['result'] for r in after_joint])]:
        status=[];changed={field:[] for field in ALL_FIELDS};selected_changed={field:[] for field in ALL_FIELDS}
        for occ,a,b in zip(before['occurrences'],old,new,strict=True):
            if a['status'] != b['status']:
                status.append(occ['id'])
            left=None if a['canonical_ir'] is None else a['canonical_ir']['rules'][0]
            right=None if b['canonical_ir'] is None else b['canonical_ir']['rules'][0]
            for field in ALL_FIELDS:
                if (None if left is None else left[field]) != (None if right is None else right[field]):
                    changed[field].append(occ['id'])
                    if left is not None and right is not None:
                        selected_changed[field].append(occ['id'])
        require(not selected_changed['modality'],'Protected selected modality changed')
        result[route]={'status_changed_ids':status,
            'field_value_changes_including_abstention':{f:{'count':len(ids),'ids':ids} for f,ids in changed.items()},
            'field_value_changes_when_both_selected':{f:{'count':len(ids),'ids':ids} for f,ids in selected_changed.items()}}
    return result

def require_map_pin(mapping,value):
    value=descriptor(value)
    require(value['path'] in mapping and all(mapping[value['path']][k] == value[k] for k in ('bytes','sha256')),
            'Qualified source map is missing exact consumed descriptor')


def validate_capture_base(raw,rows,greedy,joint,*,candidate=False,summary=None,report=None,state=None,latent='none'):
    n=len(rows);inference=raw['inference']
    require(len(raw['occurrences']) == len(inference['rows']) == n and raw['actual_source_forwards'] == n
            and raw['extra_capture_forwards'] == 0 and raw['target_access'] is raw['teacher_forcing'] is False
            and raw['model_weights_unchanged'] is raw['original_greedy_observations_verified'] is True
            and raw['ambient_CPU_RNG_preserved'] is True
            and all(raw.get(k) is False for k in FALSE),'Complete target-free saved capture required')
    require(inference['target_access'] is inference['teacher_forcing'] is inference['training_executed'] is False
            and all(inference.get(k) is False for k in FALSE),'Saved inference authority/target boundary differs')
    if candidate:
        require(raw['schema'] == {'ce':'actor-adapter-target-free-head-capture/v1','hinge':'actor-ranking-adapter-target-free-head-capture/v1',True:'actor-features-adapter-target-free-head-capture/v1'}[candidate]
                and inference['schema'] == {'ce':'bounded-actor-boundary-adapter-inference/v1','hinge':'bounded-actor-ranking-adapter-inference/v1',True:'bounded-actor-features-adapter-inference/v1'}[candidate]
                and inference['checkpoint_sha256'] == (summary['initial_checkpoint_sha256'] if state == 'initial' else summary['checkpoint']['sha256'])
                and inference['model_state_sha256'] == (summary['initial_model_state_sha256'] if state == 'initial' else summary['final_model_state_sha256'])
                and inference['source_split_checkpoint_sha256'] == SOURCE_SHA
                and inference['source_split_model_state_sha256'] == SOURCE_STATE
                and inference['latent_ablation'] == latent,'Actor candidate lineage/control differs')
        require(inference['branch_digests'] == report['initial_branch_digests' if state == 'initial' else 'final_branch_digests']
                and inference['training_policy'] == report['training_policy']
                and inference['training_policy_sha256'] == digest(report['training_policy']),
                'Actor capture/report branch or policy join differs')
        for key in ('source_model_forwards','modality_encoder_forwards','span_encoder_forwards',
                    'original_presence_head_forwards','original_start_head_forwards','original_end_head_forwards',
                    'actor_start_head_forwards','actor_end_head_forwards'):
            require(raw[key] == inference[key] == n,'Complete same-forward actor capture accounting differs')
        if candidate is True:
            for key in ('actor_attention_pool_forwards','actor_context_feature_forwards'):
                require(raw[key] == inference[key] == n,'Complete same-forward actor feature accounting differs')
    for source,occ,g in zip(rows,raw['occurrences'],inference['rows'],strict=True):
        sha=hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(occ['id'] == source['id'] and occ['source_sha256'] == g['source_sha256'] == sha,
                'Saved source ID/SHA joins differ')
        require(g['latent_sha256'] == digest(source['latent']) and g['latent_input_enabled'] is False
                and g['source_input_conditioned'] is True and g['sample_memory_used'] is False
                and g['target_access'] is g['teacher_forcing'] is g['training_executed'] is False
                and all(g.get(k) is False for k in FALSE),'Source-only latent-off greedy envelope differs')
        joint['_validated'](source['source_text'],occ['scores'])
        greedy['_verify_greedy'](source['source_text'],occ['scores'],g)
    require(inference['decoded_count'] == sum(r['status'] == 'decoded' for r in inference['rows']),
            'Saved decoded count differs')


def pure_predicates(plan):
    namespace=dict(globals(),HELPER=T/'run_temporal_contrast_pilot.py',
                   HELPER_SHA=FIXED[T/'run_temporal_contrast_pilot.py'][1])
    for path in (N2/'analyze_targeted_results_v01.py',T/'run_temporal_contrast_pilot.py'):
        pin(path,fixed(path))
    for item in plan['source_owner_pins'].values():
        descriptor(item);pin(item['path'],item)
    detached(N2/'analyze_targeted_results_v01.py',{'tokenize','strict_rule','gold_coordinates','scorers'},namespace)
    greedy,joint,scorer=namespace['scorers'](plan['source_owner_pins'])
    matches=[item for item in plan['source_owner_pins'].values()
             if Path(item['path']).name == 'legal_span_targeted_loss.py']
    require(len(matches) == 1 and matches[0]['bytes'] == 49658
            and matches[0]['sha256'] == 'f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b',
            'Unchanged qualified targeted hinge source required')
    targeted=dict(globals(),copy=SimpleNamespace(deepcopy=deepcopy),SPAN_FIELDS=FIELDS,
        MAX_SOURCE_TOKENS=128,MAX_NEW_STEPS=32,MAX_SECONDS=32,
        LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
        POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
        span=SimpleNamespace(_SHA=re.compile('[0-9a-f]{64}')))
    detached(matches[0]['path'],{'_require','_raw','checkpoint_digest','_policy','_validate_policy',
        '_f32','_span_coordinates','_actor_domain','_validate_objective_diagnostics'},targeted)
    namespace['targeted_pure']=targeted
    return namespace,greedy,joint,scorer



def projection(scores, full=True):
    """Freeze every head except the single authorized conditions presence pair."""
    return dict(modality_logits=scores['modality_logits'],
        presence_logits={k:v for k,v in scores['presence_logits'].items() if full or k != 'conditions'},
        start_logits=scores['start_logits'],end_logits=scores['end_logits'])


def compare_saved(rows, before, after, *, full, before_joint=None, after_joint=None):
    require(len(rows) == len(before['occurrences']) == len(after['occurrences']), 'Complete parity scope differs')
    records=[]
    for src,left,right in zip(rows,before['occurrences'],after['occurrences'],strict=True):
        require(src['id'] == left['id'] == right['id'] and left['source_sha256'] == right['source_sha256'], 'Parity source joins differ')
        require(binary(projection(left['scores'],full)) == binary(projection(right['scores'],full)), 'Required frozen head binary32 differs')
        records.append(dict(id=src['id'],source_sha256=left['source_sha256']))
    if full:
        require(canonical(before['inference']['rows']) == canonical(after['inference']['rows']) or
                [{k:r.get(k) for k in ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')} for r in before['inference']['rows']]
                == [{k:r.get(k) for k in ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')} for r in after['inference']['rows']],
                'Initial greedy decisions differ')
        if before_joint is not None:
            require([r['result'] for r in before_joint] == [r['result'] for r in after_joint], 'Initial joint decisions differ')
    return records


def optional_presence_confusion(rows, raw, chosen):
    """Head ambiguity and selected-output abstention never count as absent roles."""
    fields=FIELDS[2:]; result={view:{field:{key:[] for key in ('TP','TN','FP','FN','abstained_or_ambiguous')}
        for field in fields} for view in ('head','raw','joint')}
    denominators={field:dict(gold_present=0,gold_absent=0) for field in fields}
    excluded={view:{field:dict(gold_present=[],gold_absent=[]) for field in fields} for view in result}
    for source,occ,g,j in zip(rows,raw['occurrences'],raw['inference']['rows'],chosen,strict=True):
        require(source['id'] == occ['id'] == j['id'], 'Presence source ID join differs')
        target=source['canonical_ir']['rules'][0]
        for field in fields:
            truth=bool(target[field]);label='gold_present' if truth else 'gold_absent';denominators[field][label]+=1
            winner,_=guarded_choice(occ['scores']['presence_logits'][field])
            predictions=dict(head=None if winner is None else winner == 1,
                raw=None if g['status'] != 'decoded' else bool(g['canonical_ir']['rules'][0][field]),
                joint=None if j['result']['status'] != 'selected' else bool(j['result']['canonical_ir']['rules'][0][field]))
            for view,pred in predictions.items():
                bucket='abstained_or_ambiguous' if pred is None else 'TP' if truth and pred else 'FN' if truth else 'FP' if pred else 'TN'
                result[view][field][bucket].append(source['id'])
                if pred is None: excluded[view][field][label].append(source['id'])
    compact=lambda ids:dict(count=len(ids),ids=ids)
    return dict(denominators=denominators,views={v:{f:{k:compact(ids) for k,ids in buckets.items()} for f,buckets in fields.items()} for v,fields in result.items()},
        excluded_by_gold={v:{f:{k:compact(ids) for k,ids in values.items()} for f,values in fields.items()} for v,fields in excluded.items()},
        abstentions_excluded_from_TP_TN_FP_FN=True,independent_primary_recount_required=True,
        scope='Post-freeze exposed authored presence only; ambiguity and abstention excluded from all confusion cells.')


def conditions_presence_changes(before, after):
    """Expose each head/raw/joint transition, including abstention with gold split."""
    result={}
    for view in ('head','raw','joint'):
        left=before['views'][view]['conditions'];right=after['views'][view]['conditions']
        allids=[i for b in left.values() for i in b['ids']]
        require(set(allids) == {i for b in right.values() for i in b['ids']}, 'Presence paired ID scope differs')
        changes={a+'_to_'+b:[] for a in left for b in right}
        for identifier in allids:
            a=next(k for k,v in left.items() if identifier in v['ids']);b=next(k for k,v in right.items() if identifier in v['ids'])
            changes[a+'_to_'+b].append(identifier)
        result[view]={key:dict(count=len(ids),ids=ids) for key,ids in changes.items()}
    return result


def training_metadata(report, rows, namespace):
    names=['conditions_presence.weight','conditions_presence.bias'];part=report['parameter_partition']
    authenticated_class_counts=dict(absent=sum(not bool(r['canonical_ir']['rules'][0]['conditions']) for r in rows),present=sum(bool(r['canonical_ir']['rules'][0]['conditions']) for r in rows))
    require(len(rows) == 168 and authenticated_class_counts == dict(absent=96,present=72), 'Authenticated168 training-only class counts differ')
    require(report['schema'] == 'bounded-conditions-balanced-adapter-training/v1'
        and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
        and report['conditions_training_count'] == len(rows) == 168
        and report['training_conditions_class_counts'] == dict(absent=96,present=72) and report['stopped_reason'] == 'step_limit'
        and report['optimizer_parameter_order'] == part['trainable_parameter_names'] == part['optimizer_parameter_order'] == names
        and len(part['model_parameter_names']) == 42 and len(part['frozen_parameter_names']) == 40
        and report['stored_trainable_scalar_count'] == part['stored_trainable_scalar_count'] == 520
        and report['active_trainable_scalar_count'] == part['active_trainable_scalar_count'] == 130
        and part['inactive_stored_scalar_count'] == 390 and part['active_head_rows'] == [2,3]
        and part['inactive_head_rows'] == [0,1,4,5,6,7]
        and report['frozen_parent40_sha256_initial'] == report['frozen_parent40_sha256_final'] == SOURCE_STATE
        and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final']
        and set(report['changed_parameter_names']) <= set(names), 'Conditions42/40/2 and520/130/390 partition differs')
    policy=report['training_policy'];objective=policy['objective_policy'];opt=policy['optimizer']
    require(policy['schema'] == 'bounded-conditions-balanced-adapter-policy/v1'
        and policy['objective'] == 'conditions-balanced-ce' and policy['parameter_partition'] == part
        and objective == dict(conditions_pair_cross_entropy=True,mean_all_batch_rows=True,actor_ranking_enabled=False,
            training_row_reweighting=True,source_order='unchanged_targeted_seed1729_epoch_permutation',batch_order_seed=1729,batch_size=12,
            class_balance=dict(class_order=['absent','present'],counts=dict(absent=96,present=72),weights_rational=[[7,8],[7,6]],weights=[7/8,7/6],weight_rule='training_count/(2*class_count)',counts_source='authenticated_training168_conditions_presence_only',normalization='fixed_batch_row_count'))
        and opt == dict(name='Adam',learning_rate=.001,betas=[.9,.999],eps=1e-8,weight_decay=0.,foreach=False,gradient_clip_norm=5.)
        and policy['inherited_optimizer_moments'] is policy['latent_enabled'] is policy['evaluation_references_used'] is False,
        'Fixed conditions CE-only policy differs')
    batches=report['batch_trace']['batches'];objectives=report['objective_trace'];freezes=report['freeze_trace']
    for value,kind in [(objectives,'objective'),(freezes,'freeze')]:
        require(value['schema'] == 'completed-conditions-balanced-adapter-'+kind+'-trace/v1'
            and value['completed_updates'] == len(value['batches']) == 32
            and value['batches_sha256'] == digest(value['batches']) and value['independent_numerical_kernel_trace'] is False,
            'Complete source-bound32trace required')
    require(len(batches) == 32 and objectives['evaluation_references_used'] is False
        and report['batch_trace']['training_manifest_sha256'] == digest(rows)
        and [b['indices'] for b in batches] == namespace['summary']['prepared_schedule']['batch_indices']
        and [b['ids'] for b in batches] == namespace['summary']['prepared_schedule']['batch_ids'], 'Complete32 CE batches and unchanged authenticated source schedule required')
    f=report['forward_accounting']
    require(f['training_model_forward_calls'] == 32 and f['training_source_row_occurrences'] == 384
        and all(n == 32 for n in f['actual_model_counter_deltas'].values())
        and f['training_span_encoder_calls'] == 64 and f['training_modality_encoder_calls'] == 32
        and f['training_conditions_presence_head_calls'] == 32
        and f['tuning_model_forward_calls'] == f['teacher_model_forward_calls'] == report['tuning']['rows_evaluated'] == 0,
        '32batch384occurrence/threefrozenfeature-route accounting differs')
    sources=[v for v in namespace['plan']['source_owner_pins'].values() if Path(v['path']).name == 'legal_span_conditions_balanced.py']
    require(len(sources) == 1, 'One exact source-bound presence trainer required')
    validator=dict(_require=require,SOURCE_ACTOR_FEATURES_MODEL_SHA256=SOURCE_STATE,
        TRAINABLE_PARAMETER_NAMES=tuple(names),span=SimpleNamespace(_SHA=re.compile('[0-9a-f]{64}')))
    detached(sources[0]['path'],{'_validate_freeze_entry'},validator)
    count=0;previous=None
    for step,(batch,entry,freeze) in enumerate(zip(batches,objectives['batches'],freezes['batches'],strict=True),1):
        require(batch['optimizer_step'] == entry['optimizer_step'] == step
            and all(entry[k] == batch[k] for k in ('indices','ids'))
            and len(batch['indices']) == len(batch['ids']) == 12, 'CE batch/step/source order differs')
        validator['_validate_freeze_entry'](freeze,batch)
        require(previous is None or freeze['branch_digests_before'] == previous, 'Returned branch digest chain differs')
        if step == 1: require(freeze['branch_digests_before'] == report['initial_branch_digests'], 'Initial branch join differs')
        previous=freeze['branch_digests_after'];d=entry['details']
        require(set(d) == {'conditions_cross_entropy_unweighted','conditions_cross_entropy_balanced','total_loss','batch_denominator','batch_class_counts','batch_weight_sum','rows','teacher_forcing','evaluation_references_used','actor_hinge_applied'}
            and d['teacher_forcing'] is True and d['evaluation_references_used'] is d['actor_hinge_applied'] is False
            and d['conditions_cross_entropy_balanced'] == d['total_loss'] == batch['loss']
            and type(d['total_loss']) is float and math.isfinite(d['total_loss']) and d['total_loss'] >= 0
            and type(d['conditions_cross_entropy_unweighted']) is float and math.isfinite(d['conditions_cross_entropy_unweighted'])
            and d['batch_denominator'] == len(d['rows']) == 12, 'Closed all-row weighted pair CE details differ')
        weights=[];unweighted=[];weighted=[];class_counts=dict(absent=0,present=0)
        for index,identifier,item in zip(batch['indices'],batch['ids'],d['rows'],strict=True):
            require(type(index) is int and 0 <= index < 168 and rows[index]['id'] == identifier == item['id']
                and item['training_index'] == index and type(item['conditions_present']) is bool
                and item['conditions_present'] is bool(rows[index]['canonical_ir']['rules'][0]['conditions'])
                and type(item['conditions_logits']) is list and len(item['conditions_logits']) == 2
                and all(type(x) in (int,float) and math.isfinite(x) for x in item['conditions_logits']),
                'Training conditions target/source/pair domain differs')
            require(set(item) == {'id','training_index','conditions_present','conditions_logits','class_weight','unweighted_cross_entropy','weighted_cross_entropy'}, 'Closed weighted source row required')
            label='present' if item['conditions_present'] else 'absent';class_counts[label]+=1
            w=f32(7/6 if item['conditions_present'] else 7/8);loss=item['unweighted_cross_entropy'];product=item['weighted_cross_entropy']
            require(type(item['class_weight']) is float and item['class_weight'] == w
                and type(loss) is float and math.isfinite(loss) and loss >= 0
                and type(product) is float and product == f32(loss*w), 'Training-derived float32 class weight/product differs')
            logits=item['conditions_logits'];maximum=max(logits);target=1 if item['conditions_present'] else 0
            nll=math.log(math.fsum(math.exp(v-maximum) for v in logits))+(maximum-logits[target])
            require(abs(loss-nll) <= 2e-6*max(1.,abs(nll)), 'Unweighted row CE differs from source logits/label')
            weights.append(w);unweighted.append(loss);weighted.append(product);count+=1
        close=lambda a,b: abs(a-b) <= 2e-6*max(1.,abs(b))
        require(d['batch_class_counts'] == class_counts and close(d['batch_weight_sum'],math.fsum(weights))
            and close(d['conditions_cross_entropy_unweighted'],math.fsum(unweighted)/12)
            and close(d['conditions_cross_entropy_balanced'],math.fsum(weighted)/12),
            'Fixed12row weighted and separate unweighted means differ; weight sum is diagnostic only')
    require(count == 384 and previous == report['final_branch_digests'], 'Completed384/final branch join differs')
    return dict(updates=32,training_rows=168,training_source_occurrences=384,model_tensors=42,frozen_parent_tensors=40,
        new_Adam_tensors=2,stored_trainable_scalars=520,active_trainable_scalars=130,inactive_copied_scalars=390,
        source_bound_freeze_validator_reused=True,all32_source_label_joins_checked=True,actor_ranking_enabled=False,
        class_weights_rational=[[7,8],[7,6]],normalization='fixed_batch_row_count',unweighted_CE_separately_validated=True,
        numerical_kernel_gradient_replay_claimed=False,checkpoint_JSON_parsed=False)


def validate_capture(raw, rows, greedy, joint, *, candidate=False, summary=None, report=None, state=None, latent='none'):
    validate_capture_base(raw,rows,greedy,joint)
    if not candidate: return
    inference=raw['inference'];n=len(rows)
    require(raw['schema'] == 'conditions-balanced-adapter-target-free-head-capture/v1'
        and inference['schema'] == 'bounded-conditions-balanced-adapter-inference/v1'
        and inference['checkpoint_sha256'] == (summary['initial_checkpoint_sha256'] if state == 'initial' else summary['checkpoint']['sha256'])
        and inference['model_state_sha256'] == (summary['initial_model_state_sha256'] if state == 'initial' else summary['final_model_state_sha256'])
        and inference['source_actor_features_checkpoint_sha256'] == SOURCE_SHA
        and inference['source_actor_features_model_state_sha256'] == SOURCE_STATE
        and inference['latent_ablation'] == latent and inference['feature_paths_per_source_forward'] == 3
        and inference['branch_digests'] == report['initial_branch_digests' if state == 'initial' else 'final_branch_digests']
        and inference['training_policy'] == report['training_policy'], 'Exact candidate lineage/policy differs')
    for key in ('source_model_forwards','frozen_actor_features_model_forwards','frozen_modality_encoder_forwards',
                'frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'):
        require(raw[key] == inference[key] == n, 'Exact candidate same-forward module accounting differs')



def scientific_acceptance(contract, summaries, records):
    """Preregistered descriptive success; technical completion remains independent."""
    panels=tuple(p for p in (*PANELS,'training168') if p != 'law')
    lookup={(x['state'],x['panel']):x for x in summaries}
    result=dict(required_gain_ids_missing={},complete_IR_loss_ids_vs_N10={},complete_IR_loss_ids_vs_N11={},
        new_conditions_head_FP_ids_vs_N10={},new_conditions_head_FN_ids_vs_N10={},
        new_positive_head_ambiguity_ids_vs_N10={},N11_added_FN_target_ids={},unrecovered_N11_added_FN_ids={})
    success=True
    for panel in panels:
        before=lookup['parent',panel]['optional_presence_confusion'];after=lookup['trained',panel]['optional_presence_confusion']
        diagnostic=lookup['frozen_N11',panel]['optional_presence_confusion']
        for metric,key in [('FP','new_conditions_head_FP_ids_vs_N10'),('FN','new_conditions_head_FN_ids_vs_N10')]:
            ids=sorted(set(after['views']['head']['conditions'][metric]['ids'])-set(before['views']['head']['conditions'][metric]['ids']))
            result[key][panel]=ids;success &= not ids
        ids=sorted(set(after['excluded_by_gold']['head']['conditions']['gold_present']['ids'])-
                   set(before['excluded_by_gold']['head']['conditions']['gold_present']['ids']))
        result['new_positive_head_ambiguity_ids_vs_N10'][panel]=ids;success &= not ids
        targets=sorted(set(diagnostic['views']['head']['conditions']['FN']['ids'])-set(before['views']['head']['conditions']['FN']['ids']))
        result['N11_added_FN_target_ids'][panel]=targets
        lost=sorted(set(targets)-set(after['views']['head']['conditions']['TP']['ids']))
        result['unrecovered_N11_added_FN_ids'][panel]=lost;success &= not lost
        for state,key in [('parent','complete_IR_loss_ids_vs_N10'),('frozen_N11','complete_IR_loss_ids_vs_N11')]:
            result[key][panel]={}
            for route in ['raw','joint']:
                left,right=records[state,panel],records['trained',panel]
                require([r['id'] for r in left] == [r['id'] for r in right], 'Success predicate paired source IDs differ')
                ids=[a['id'] for a,b in zip(left,right,strict=True) if a[route+'_exact_ir'] and not b[route+'_exact_ir']]
                result[key][panel][route]=ids;success &= not ids
        required=contract['strict_scientific_success']['preserve_N11_complete_IR_gain_ids'].get(panel,[])
        result['required_gain_ids_missing'][panel]={}
        for route in ['raw','joint']:
            exact={row['id'] for row in records['trained',panel] if row[route+'_exact_ir']}
            missing=sorted(set(required)-exact);result['required_gain_ids_missing'][panel][route]=missing;success &= not missing
    expected=contract['strict_scientific_success']['recover_N11_added_FN_ids']['expected_panel_counts']
    counts={p:len(ids) for p,ids in result['N11_added_FN_target_ids'].items() if ids}
    require(counts == expected and sum(counts.values()) == 4, 'Frozen N11 added-FN target scope differs from preregistration')
    result.update(scientific_success=bool(success),technical_pass=True,expected_four_N11_added_FN_targets_verified=True,
        default_promotion=False,used_for_hyperparameter_or_checkpoint_selection=False,
        scope='Conjunctive preregistered exposed-diagnostic result; no blind generalization or promotion authority.')
    return result

def main(args):
    global FREEZE_PASSED
    output=Path(args.output);require(output.is_absolute() and output.parent == ROOT and not output.exists(), 'Exclusive owned analysis output required')
    own=pin(Path(__file__).resolve());approval_pin=pin(ROOT/'analyzer-source-independent-review-v02.json')
    approval=read(approval_pin['path'],approval_pin)
    require(approval['schema'] == 'conditions-balanced-analyzer-source-independent-review/v1'
        and approval['passed'] is True and approval['findings'] == [] and approval['analyzer'] == own,
        'Exact independently qualified analyzer required')
    require_map_pin(approval['artifacts'],own)
    freeze_pin=descriptor(dict(path=str(Path(args.freeze)),bytes=args.freeze_bytes,sha256=args.freeze_sha256))
    require(freeze_pin['path'] == str(ROOT/'conditions-balanced-output-freeze-v01.json'), 'Exact qualified presence freeze required')
    freeze=read(freeze_pin['path'],freeze_pin)
    result_root=validate_freeze(freeze,freeze_pin['path'],schema='conditions-balanced-output-freeze/v1')
    runtime_pin=descriptor(freeze['runtime_review']);runtime=read(runtime_pin['path'],runtime_pin)
    require(runtime_pin['path'] == str(ROOT/'conditions-balanced-ce-runtime-review-v01.json')
        and runtime['schema'] == 'conditions-balanced-runtime-independent-review/v1'
        and runtime['passed'] is True and runtime['findings'] == [] and runtime['outputs'] == freeze['results'],
        'Complete qualified runtime/output closure required')
    require_map_pin(approval['artifacts'],runtime['observer'])
    plan_pin=descriptor(freeze['plan']);require_map_pin(approval['artifacts'],plan_pin);plan=read(plan_pin['path'],plan_pin)
    require(plan_pin['path'] == str(ROOT/'conditions-balanced-ce-plan-v01.json')
        and plan['schema'] == 'conditions-balanced-cell-plan/v1' and plan['cell'] == 'conditions-balanced-ce'
        and plan['source_checkpoint']['sha256'] == SOURCE_SHA and plan['source_model_state_sha256'] == SOURCE_STATE
        and plan['evaluation_contract'] == freeze['evaluation_contract'] == fixed(ROOT/'evaluation-contract-v01.json')
        and plan['latent_enabled'] is plan['default_promotion'] is False and runtime['plan'] == plan_pin,
        'Exact trained N10 source-only conditions plan required')
    require((runtime['actual_returned_optimizer_updates'],runtime['actual_training_source_occurrences'],
        runtime['actual_inference_source_forwards'],runtime['actual_model_forwards'],runtime['actual_total_source_occurrences'])
        == (32,384,1280,1312,1664), 'Actual new source/forward accounting differs')
    summary=bind(freeze['summary'],freeze,result_root,'summary.json')
    require(summary['schema'] == 'conditions-balanced-cell-results/v1' and summary['status'] == 'completed'
        and summary['cell'] == 'conditions-balanced-ce' and summary['opening_owners'] == summary['closing_owners']
        and all(v == plan['source_owner_pins'].get(k) for k,v in summary['opening_owners'].items())
        and len(plan['source_owner_pins']) == 39, 'Completed source-bound39-owner summary required')
    FREEZE_PASSED=True
    contract=read(ROOT/'evaluation-contract-v01.json',fixed(ROOT/'evaluation-contract-v01.json'))
    require(contract['schema'] == 'conditions-balanced-evaluation-contract/v1' and contract['law8_unscored'] is True
        and contract['expected_panel_count'] == 40 and contract['expected_authored_score_sets'] == 36,
        'Closed exposed-diagnostic contract differs')
    for path,value in approval['artifacts'].items():pin(path,value)
    namespace,greedy,joint,scorer=pure_predicates(plan);namespace['plan']=plan;namespace['summary']=summary
    data,populations,metadata=references(plan);rows=data['training_rows']
    report=bind(summary['training'],freeze,result_root,'cell-training.json');training=training_metadata(report,rows,namespace)
    parent_contract=contract['completed_frozen_parent']
    parent_review=read(parent_contract['independent_review']['path'],parent_contract['independent_review'])
    parent_freeze=read(parent_contract['freeze']['path'],parent_contract['freeze'])
    require(parent_review['schema'] == 'actor-features-result-independent-review/v1' and parent_review['passed'] is True
        and parent_review['findings'] == [] and parent_review['freeze'] == parent_contract['freeze']
        and parent_review['plan'] == parent_contract['plan'] and parent_contract['new_control_forwards'] == parent_contract['new_control_updates'] == 0,
        'Exact trained N10 frozen comparator qualification required')
    parent_root=validate_freeze(parent_freeze,parent_contract['freeze']['path'],metadata_root=N10,schema='actor-features-output-freeze/v1')
    parent_summary=bind(parent_freeze['summary'],parent_freeze,parent_root,'summary.json')
    require(parent_summary['checkpoint']['sha256'] == SOURCE_SHA and parent_summary['final_model_state_sha256'] == SOURCE_STATE,
        'Frozen comparator is not trained N10 parent')
    actual={};new_inference=0
    def pair(descriptors, source_rows, label, state):
        nonlocal new_inference
        require(descriptors['row_count'] == len(source_rows), 'Capture source scope differs')
        raw=bind(descriptors['raw'],freeze,result_root,label+'-raw.json')
        validate_capture(raw,source_rows,greedy,joint,candidate=True,summary=summary,report=report,state=state)
        chosen=validate_joint(bind(descriptors['joint'],freeze,result_root,label+'-joint.json'),raw,source_rows,joint)
        new_inference+=len(source_rows);return raw,chosen
    for state,key,prefix in [('initial','baseline_panels','baseline-'),('trained','diagnostics','trained-')]:
        require(set(summary[key]) == set(PANELS), 'Complete candidate panel set differs')
        for panel in PANELS:actual[state,panel]=pair(summary[key][panel],source_projection(populations[panel]),prefix+panel,state)
        key,label=('initial_training_capture','initial-training168') if state == 'initial' else ('final_training_capture','trained-training168')
        actual[state,'training168']=pair(summary[key],rows,label,state)
    diagnostic=contract['completed_frozen_N11']
    diagnostic_review=read(diagnostic['independent_review']['path'],diagnostic['independent_review'])
    diagnostic_freeze=read(diagnostic['freeze']['path'],diagnostic['freeze'])
    require(diagnostic_review['schema'] == 'conditions-presence-result-independent-review/v1'
        and diagnostic_review['passed'] is True and diagnostic_review['findings'] == []
        and diagnostic_review['freeze'] == diagnostic['freeze'] and diagnostic_review['plan'] == diagnostic['plan']
        and diagnostic['new_control_forwards'] == diagnostic['new_control_updates'] == 0,
        'Exact frozen N11 diagnostic qualification required')
    diagnostic_root=validate_freeze(diagnostic_freeze,diagnostic['freeze']['path'],metadata_root=N11,schema='conditions-presence-output-freeze/v1')
    diagnostic_summary=bind(diagnostic_freeze['summary'],diagnostic_freeze,diagnostic_root,'summary.json')
    require(diagnostic_summary['cell'] == 'conditions-presence-ce' and diagnostic_summary['actual_new_updates'] == 32
        and diagnostic_summary['source_checkpoint']['sha256'] == SOURCE_SHA, 'Frozen N11 comparator must share N10 donor')
    for panel in (*PANELS,'training168'):
        sr=rows if panel == 'training168' else source_projection(populations[panel])
        descriptors=diagnostic_summary['final_training_capture'] if panel == 'training168' else diagnostic_summary['diagnostics'][panel]
        label='trained-training168' if panel == 'training168' else 'trained-'+panel
        raw=bind(descriptors['raw'],diagnostic_freeze,diagnostic_root,label+'-raw.json');validate_capture(raw,sr,greedy,joint)
        chosen=validate_joint(bind(descriptors['joint'],diagnostic_freeze,diagnostic_root,label+'-joint.json'),raw,sr,joint)
        require(raw['inference']['checkpoint_sha256'] == diagnostic_summary['checkpoint']['sha256'], 'Frozen N11 saved capture checkpoint differs')
        actual['frozen_N11',panel]=raw,chosen
    copied={}
    for panel in (*PANELS,'training168'):
        source_rows=rows if panel == 'training168' else source_projection(populations[panel])
        descriptors=parent_summary['final_training_capture'] if panel == 'training168' else parent_summary['diagnostics'][panel]
        label='trained-training168' if panel == 'training168' else 'trained-'+panel
        raw=bind(descriptors['raw'],parent_freeze,parent_root,label+'-raw.json')
        validate_capture(raw,source_rows,greedy,joint)
        chosen=validate_joint(bind(descriptors['joint'],parent_freeze,parent_root,label+'-joint.json'),raw,source_rows,joint)
        require(raw['inference']['checkpoint_sha256'] == SOURCE_SHA, 'Frozen parent capture checkpoint differs')
        actual['parent',panel]=raw,chosen
        if panel in (*FRESH_PANELS,'training168'):
            ownpair=summary['parent_training_capture'] if panel == 'training168' else summary['parent_fresh_panels'][panel]
            ownlabel='parent-training168' if panel == 'training168' else 'parent-'+panel
            for view in ('raw','joint'):
                ownvalue=bind(ownpair[view],freeze,result_root,ownlabel+'-'+view+'.json')
                require({k:ownpair[view][k] for k in ('bytes','sha256')} == {k:descriptors[view][k] for k in ('bytes','sha256')},
                    'Opaque copied parent capture bytes differ from authenticated frozen source')
                copied[ownlabel+'-'+view]=dict(source=descriptors[view],copy=ownpair[view],new_forward_calls=0)
    require(len(copied) == 6, 'Exactly six parent copies required')
    initial={};protected={};changed={}
    for panel in (*PANELS,'training168'):
        sr=rows if panel == 'training168' else source_projection(populations[panel]);parent,first,last=(actual[s,panel] for s in ('parent','initial','trained'))
        initial[panel]=compare_saved(sr,parent[0],first[0],full=True,before_joint=parent[1],after_joint=first[1])
        protected[panel]=compare_saved(sr,parent[0],last[0],full=False)
        compare_saved(sr,actual['frozen_N11',panel][0],last[0],full=False)
        changed[panel]=[a['id'] for a,b in zip(parent[0]['occurrences'],last[0]['occurrences'],strict=True)
            if binary(a['scores']['presence_logits']['conditions']) != binary(b['scores']['presence_logits']['conditions'])]
    require(sum(map(len,initial.values())) == sum(map(len,protected.values())) == 632, 'Full632 parity/retention scope differs')
    dormant=[]
    for phase,key in [('initial','initial_parity'),('trained','trained_parity')]:
        receipt=bind(summary[key],freeze,result_root,phase+'-parity.json');first=None
        require(receipt['passed'] is True and receipt['actual_encoder_calls'] == 0
            and receipt['genuine_latent_semantics_tested'] is False and len(receipt['controls']) == 4,
            'Dormant control scope differs')
        for item in receipt['controls']:
            sr=deepcopy(source_projection(populations['fresh_tune'][:2]))
            for i,row in enumerate(sr):row['latent']=[0. if item['name'] == 'zeros' else .25 if i == 0 else -.25]*384
            if item['name'] == 'rotated_placeholders':sr[0]['latent'],sr[1]['latent']=sr[1]['latent'],sr[0]['latent']
            raw=bind(item['report'],freeze,result_root,phase+'-parity-'+item['name']+'.json')
            validate_capture(raw,sr,greedy,joint,candidate=True,summary=summary,report=report,state=phase,latent=item['control'])
            value=[dict(heads=binary(projection(o['scores'])).hex(),status=g['status'],canonical_ir=g['canonical_ir']) for o,g in zip(raw['occurrences'],raw['inference']['rows'],strict=True)]
            require(first is None or value == first, 'Dormant placeholders altered head/readout');first=value;new_inference+=2
        dormant.append(dict(phase=phase,controls=4,rows_each=2,invariant=True,genuine_latent_semantics_tested=False))
    require(new_inference == 1280, 'Exactly1280 new inference source occurrences required')
    summaries=[];scores={};coverage={}
    for state in ('parent','initial','trained','frozen_N11'):
        for panel in (*PANELS,'training168'):
            src=rows if panel == 'training168' else populations[panel];meta=data['training_metadata'] if panel == 'training168' else metadata.get(panel)
            raw,chosen=actual[state,panel];compact,records,cov=panel_score(panel,state,src,meta,raw,chosen,scorer,namespace,joint)
            summaries.append(compact)
            if records is not None:scores[state,panel]=records;coverage[state,panel]=cov
    require(len(summaries) == 40 and len(scores) == 36, 'Exact40/36 evaluation scope differs')
    paired={};parentpaired={};N11paired={};coupling={};presence_changes={};rank_equal={}
    for panel in (*[p for p in PANELS if p != 'law'],'training168'):
        paired[panel]=paired_changes(scores['initial',panel],scores['trained',panel])
        parentpaired[panel]=paired_changes(scores['parent',panel],scores['trained',panel])
        N11paired[panel]=paired_changes(scores['frozen_N11',panel],scores['trained',panel])
        coupling[panel]=decoded_coupling(actual['parent',panel][0],actual['trained',panel][0],actual['parent',panel][1],actual['trained',panel][1])
        left=next(x for x in summaries if x['state'] == 'parent' and x['panel'] == panel)
        right=next(x for x in summaries if x['state'] == 'trained' and x['panel'] == panel)
        presence_changes[panel]=conditions_presence_changes(left['optional_presence_confusion'],right['optional_presence_confusion'])
        rank_equal[panel]=[]
        for a,b in zip(coverage['parent',panel],coverage['trained',panel],strict=True):
            keys=('id','stable_rank','in_top8','in_top16')
            require(all(a[k] == b[k] for k in keys), 'Frozen actor rank/topK changed')
            rank_equal[panel].append(a['id'])
    permissions={}
    for state in ('parent','initial','trained','frozen_N11'):
        src=populations['old_tune'];raw,chosen=actual[state,'old_tune'];ids=[r['id'] for r in src if r['canonical_ir']['rules'][0]['modality'] == 'P']
        require(len(ids) == 32, 'Exactly32 gold permissions required')
        for source,g,j in zip(src,raw['inference']['rows'],chosen,strict=True):
            if source['id'] in ids:
                require(g['status'] == 'decoded' and j['result']['status'] == 'selected'
                    and g['canonical_ir']['rules'][0]['modality'] == j['result']['canonical_ir']['rules'][0]['modality'] == 'P',
                    'A required legacy gold permission changed or abstained')
        permissions[state]=dict(count=32,ids=ids,raw_P_to_P=32,joint_P_to_P=32,losses=0,abstentions=0)
    scientific=scientific_acceptance(contract,summaries,scores)
    for path,expected in list(OBSERVED.items()):pin(path,expected)
    result=dict(schema='conditions-balanced-exposed-result-analysis/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        analyzer=own,independent_source_review=approval_pin,freeze=freeze_pin,runtime_review=runtime_pin,plan=plan_pin,
        evaluation_contract=fixed(ROOT/'evaluation-contract-v01.json'),panel_count=40,authored_score_sets=36,paired_panel_count=9,
        panel_summaries=summaries,paired_initial_to_trained=paired,paired_frozen_parent_to_trained=parentpaired,
        paired_frozen_N11_to_trained=N11paired,scientific_acceptance=scientific,scientific_success=scientific['scientific_success'],
        new_N11_control_forwards=0,new_N11_control_updates=0,
        conditions_presence_changes=presence_changes,decoded_other_role_coupling=coupling,training_metadata=training,
        initial_full_head_parity=dict(rows=632,all_binary32_components_equal=True),
        final_protected_head_retention=dict(rows=632,all_required_binary32_components_equal=True,excluded_components_only=['presence_logits.conditions'],conditions_vector_changed_ids=changed),
        actor_rank_unchanged_ids=rank_equal,all32_permission_retention=permissions,optional_presence_confusion_primary=True,
        copied_parent_captures=copied,copied_parent_capture_rows=240,copied_parent_new_forwards=0,
        dormant_controls=dormant,actual_new_inference_forwards=1280,actual_new_model_forwards=1312,
        training_source_occurrences=384,total_new_source_occurrences=1664,new_parent_control_updates=0,new_parent_control_forwards=0,
        external_embedding_encoder_calls=0,frozen_feature_paths_per_candidate_forward=3,
        statutory8_unscored=True,all_panels_previously_exposed_diagnostics=True,full_IR_includes_modality=True,
        default_promotion=False,semantic_accuracy=None,Lake_executed=False,broader_logic_families_qualified=False,
        genuine_latent_semantics_qualified=False,checkpoint_JSON_parses=0,model_or_encoder_calls=0,
        private_body_reads=0,resource_API_calls=0,network_calls=0,Git_mutations=0,input_pins=OBSERVED)
    with output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    output.chmod(0o444);print(pin(output))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',required=True);parser.add_argument('--freeze-bytes',required=True,type=int)
    parser.add_argument('--freeze-sha256',required=True);parser.add_argument('--output',required=True)
    main(parser.parse_args())
