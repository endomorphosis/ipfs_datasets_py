"""Parent-only N9 analysis of a qualified, durable62-output actor-ranking run.

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
SOURCE_SHA = '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035'
SOURCE_STATE = 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5'
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
 ROOT/'evaluation-contract-v02.json':(16689,'cdb22f6cf6e6d8fdb42a6bcaf5b7330c6c2f16e4d570785df5c446debd225bcb'),
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


def validate_freeze(freeze,freeze_path,*,metadata_root=ROOT,schema='actor-ranking-output-freeze/v1'):
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


def validate_capture(raw,rows,greedy,joint,*,candidate=False,summary=None,report=None,state=None,latent='none'):
    n=len(rows);inference=raw['inference']
    require(len(raw['occurrences']) == len(inference['rows']) == n and raw['actual_source_forwards'] == n
            and raw['extra_capture_forwards'] == 0 and raw['target_access'] is raw['teacher_forcing'] is False
            and raw['model_weights_unchanged'] is raw['original_greedy_observations_verified'] is True
            and raw['ambient_CPU_RNG_preserved'] is True
            and all(raw.get(k) is False for k in FALSE),'Complete target-free saved capture required')
    require(inference['target_access'] is inference['teacher_forcing'] is inference['training_executed'] is False
            and all(inference.get(k) is False for k in FALSE),'Saved inference authority/target boundary differs')
    if candidate:
        require(raw['schema'] == ('actor-adapter-target-free-head-capture/v1' if candidate == 'ce' else 'actor-ranking-adapter-target-free-head-capture/v1')
                and inference['schema'] == ('bounded-actor-boundary-adapter-inference/v1' if candidate == 'ce' else 'bounded-actor-ranking-adapter-inference/v1')
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


def validate_joint(value,raw,rows,joint):
    require(value['schema'] in {'actor-ranking-joint-panel/v1','actor-boundary-joint-panel/v1','split-feature-joint-panel/v1'}
            and value['top_k'] == 8 and value['max_search_nodes'] == 50000
            and len(value['rows']) == len(rows),'Saved bounded joint geometry differs')
    for source,occ,row in zip(rows,raw['occurrences'],value['rows'],strict=True):
        require(source['id'] == row['id'] and row['result'] == joint['select_joint_spans'](
            source['source_text'],occ['scores'],top_k=8,max_search_nodes=50000),'Saved pure joint replay differs')
    return value['rows']


def projection(scores,full):
    return {'modality_logits':scores['modality_logits'],'presence_logits':scores['presence_logits'],
            'start_logits':{f:v for f,v in scores['start_logits'].items() if full or f != 'actor'},
            'end_logits':{f:v for f,v in scores['end_logits'].items() if full or f != 'actor'}}


def compare_saved(rows,before,after,*,full,before_joint=None,after_joint=None):
    result=[]
    require(len(rows) == len(before['occurrences']) == len(after['occurrences']),'Complete parity scope required')
    for i,(source,a,b) in enumerate(zip(rows,before['occurrences'],after['occurrences'],strict=True)):
        sha=hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(source['id'] == a['id'] == b['id'] and a['source_sha256'] == b['source_sha256'] == sha
                and a['scores']['tokens'] == b['scores']['tokens'],'Parity source/token geometry differs')
        left,right=binary(projection(a['scores'],full)),binary(projection(b['scores'],full))
        require(left == right,'Required binary32 head parity failed')
        if full:
            keys=('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')
            require({k:before['inference']['rows'][i].get(k) for k in keys}
                    == {k:after['inference']['rows'][i].get(k) for k in keys}
                    and before_joint[i] == after_joint[i],'Initial parent complete readout parity differs')
        result.append(dict(id=source['id'],source_sha256=sha,binary32_sha256=hashlib.sha256(left).hexdigest()))
    return result


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


def coverage_changes(before,after):
    require([r['id'] for r in before] == [r['id'] for r in after],'Exact paired coverage IDs required')
    result={'rank_improved_ids':[a['id'] for a,b in zip(before,after,strict=True) if b['stable_rank'] < a['stable_rank']],
        'rank_worsened_ids':[a['id'] for a,b in zip(before,after,strict=True) if b['stable_rank'] > a['stable_rank']],
        'rank_unchanged_ids':[a['id'] for a,b in zip(before,after,strict=True) if b['stable_rank'] == a['stable_rank']]}
    for name in ('in_top1','in_top8','in_top16','full_gold_assignment_survives_retained_domain'):
        result[name+'_gained_ids']=[a['id'] for a,b in zip(before,after,strict=True) if not a[name] and b[name]]
        result[name+'_lost_ids']=[a['id'] for a,b in zip(before,after,strict=True) if a[name] and not b[name]]
    margins={'improved':[],'equal':[],'worsened':[]};hinge={'inactive_gained_ids':[],'inactive_lost_ids':[],
        'margin_at_least_one_gained_ids':[],'margin_at_least_one_lost_ids':[]}
    for a,b in zip(before,after,strict=True):
        left,right=a['filtered_hard_negative'],b['filtered_hard_negative']
        require(left['compatible_wrong_domain_spans'] == right['compatible_wrong_domain_spans']
                and left['compatible_wrong_domain_sha256'] == right['compatible_wrong_domain_sha256'],
                'Common gold-dependent hard-negative domain changed')
        lm,rm=left['gold_minus_wrong_margin_float32'],right['gold_minus_wrong_margin_float32']
        require((lm is None) is (rm is None),'Common empty-domain status changed')
        if lm is not None:
            margins['improved' if rm > lm else 'worsened' if rm < lm else 'equal'].append(a['id'])
        if left['hinge_active'] and not right['hinge_active']:
            hinge['inactive_gained_ids'].append(a['id'])
        if not left['hinge_active'] and right['hinge_active']:
            hinge['inactive_lost_ids'].append(a['id'])
        if not left['margin_at_least_one'] and right['margin_at_least_one']:
            hinge['margin_at_least_one_gained_ids'].append(a['id'])
        if left['margin_at_least_one'] and not right['margin_at_least_one']:
            hinge['margin_at_least_one_lost_ids'].append(a['id'])
    result['filtered_hard_negative']={'margin_changes':margins,**hinge}
    old,new=coverage_summary(before),coverage_summary(after)
    result['diagnostic_gain_flags']={
        'actor_rank_gain':new['top1'] > old['top1'] or new['rank_sum'] < old['rank_sum'],
        'filtered_hinge_margin_gain':new['filtered_hard_negative']['margin_at_least_one_count']
            > old['filtered_hard_negative']['margin_at_least_one_count']
            or new['filtered_hard_negative']['hinge_sum'] < old['filtered_hard_negative']['hinge_sum'],
        'top8_regression_present':bool(result['in_top8_lost_ids']),
        'top16_regression_present':bool(result['in_top16_lost_ids']),
        'used_for_selection_or_promotion':False}
    return result


def frozen_CE(contract,rows,training_meta,populations,metadata,greedy,joint,scorer,namespace,report):
    """Read completed CE reference only after qualified N9 durable output freeze."""
    require(FREEZE_PASSED,'Frozen CE result reads prohibited before complete N9 freeze')
    reference=contract['completed_frozen_CE']
    require(reference['new_control_updates'] == 0 and reference['equal_FLOPs_claimed'] is False,
            'Frozen CE must not authorize new control training')
    analysis=read(reference['analysis']['path'],reference['analysis'])
    review=read(reference['independent_review']['path'],reference['independent_review'])
    require(analysis['passed'] is review['passed'] is True and analysis['findings'] == review['findings'] == []
            and analysis['freeze'] == review['freeze'] == reference['freeze']
            and analysis['plan'] == review['plan'] == reference['plan']
            and review['analysis'] == reference['analysis'],'Qualified frozen CE result/reference joins differ')
    freeze=read(reference['freeze']['path'],reference['freeze'])
    root=validate_freeze(freeze,reference['freeze']['path'],metadata_root=N8,schema='actor-boundary-output-freeze/v1')
    old_plan=read(reference['plan']['path'],reference['plan'])
    require(old_plan['source_checkpoint']['sha256'] == SOURCE_SHA
            and old_plan['source_model_state_sha256'] == SOURCE_STATE
            and old_plan['data_export'] == fixed(N6/'training-source-export-v01.json'),
            'Frozen CE common N4 parent/training source differs')
    summary=bind(freeze['summary'],freeze,root,'summary.json')
    require(summary['cell'] == 'actor-boundary-ce' and summary['status'] == 'completed'
            and summary['actual_new_updates'] == 32,'Completed frozen CE summary differs')
    old_report=bind(summary['training'],freeze,root,'cell-training.json')
    require(old_report['optimizer_steps'] == 32 and old_report['actor_training_count'] == 168
            and old_report['training_policy']['objective_policy']['actor_ranking_enabled'] is False,
            'Completed frozen CE budget or OFF policy differs')
    old_batches,new_batches=old_report['batch_trace']['batches'],report['batch_trace']['batches']
    require(len(old_batches) == len(new_batches) == 32
            and [{k:b[k] for k in ('optimizer_step','indices','ids')} for b in old_batches]
            == [{k:b[k] for k in ('optimizer_step','indices','ids')} for b in new_batches],
            'N9/CE exact completed update order/source occurrences differ')
    actual={};summaries=[];scores={};coverage={}
    for panel in (*PANELS,'training168'):
        source_rows=rows if panel == 'training168' else populations[panel]
        value=summary['final_training_capture'] if panel == 'training168' else summary['diagnostics'][panel]
        label='trained-training168' if panel == 'training168' else 'trained-'+panel
        require(value['row_count'] == len(source_rows),'CE source row count differs')
        raw=bind(value['raw'],freeze,root,label+'-raw.json')
        validate_capture(raw,source_rows,greedy,joint,candidate='ce',summary=summary,report=old_report,state='trained')
        chosen=validate_joint(bind(value['joint'],freeze,root,label+'-joint.json'),raw,source_rows,joint)
        actual[panel]=raw,chosen
        meta=metadata.get(panel) if panel != 'training168' else training_meta
        compact,records,cov=panel_score(panel,'frozen_CE',source_rows,meta,raw,chosen,scorer,namespace,joint)
        expected=reference['trained_aggregate_reference'][panel]
        require(all(compact[k] == expected[k] for k in expected if k != 'actor_gold_coverage')
                and all(compact.get('actor_gold_coverage',{}).get(k) == v
                    for k,v in expected['actor_gold_coverage'].items()),'Frozen CE preregistered aggregate recount differs')
        summaries.append(compact)
        if records is not None:
            scores[panel]=records;coverage[panel]=cov
    return actual,summaries,scores,coverage,{'reference':reference['freeze'],'new_control_updates':0,
        'matched_completed_updates':32,'matched_training_occurrences':384,'exact_batch_order_and_IDs_equal':True,
        'equal_FLOPs_claimed':False,'all62_prior_outputs_rehashed':True,'prior_aggregate_metrics_recounted':True}


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


def runtime_counts(runtime,summary):
    require(runtime.get('schema') == 'actor-ranking-runtime-independent-review/v1'
            and runtime.get('passed') is True and runtime.get('findings') == []
            and runtime.get('actual_returned_optimizer_updates') == 32
            and runtime.get('actual_inference_source_forwards') == 1520
            and runtime.get('actual_model_forwards') == 1552
            and runtime.get('actual_training_source_occurrences') == 384
            and runtime.get('actual_total_source_occurrences') == 1904
            and runtime.get('initial_source_rows') == runtime.get('final_source_rows') == 632
            and runtime.get('default_promotion') is False and runtime.get('semantic_accuracy') is None,
            'Qualified completed32-update runtime/accounting differs')
    require(summary.get('actual_new_updates') == 32 and summary.get('reference_scoring_performed') is False
            and summary.get('diagnostic_reference_labels_in_child') is False
            and summary.get('initial_and_final_training_labels_scored_by_child') is False
            and summary.get('checkpoint_selection_executed') is False,'Model-child reference/selection boundary differs')
    return {'returned_optimizer_updates':32,'inference_source_forwards':1520,'training_batch_forwards':32,
            'total_model_forwards':1552,'training_source_occurrences':384,'total_source_occurrences':1904}


def training_metadata(report,rows,namespace):
    names=['actor_start.weight','actor_start.bias','actor_end.weight','actor_end.bias']
    require(report['schema'] == 'bounded-actor-ranking-adapter-training/v1'
            and report['optimizer_steps'] == report['continuation_optimizer_steps_total'] == 32
            and report['stopped_reason'] == 'step_limit' and report['actor_training_count'] == len(rows) == 168
            and report['optimizer_parameter_order'] == names
            and set(report['changed_parameter_names']) <= set(names)
            and report['frozen_base34_sha256_initial'] == report['frozen_base34_sha256_final']
            and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final'],
            'Qualified completed actor-only training metadata differs')
    for key in ('objective_trace','freeze_trace'):
        trace=report[key]
        require(trace['completed_updates'] == len(trace['batches']) == 32
                and trace['batches_sha256'] == digest(trace['batches']),'Completed32 trace identity differs')
    require(report['objective_trace']['evaluation_references_used'] is False
            and report['forward_accounting']['training_model_forward_calls'] == 32
            and report['forward_accounting']['training_source_row_occurrences'] == 384
            and report['forward_accounting']['tuning_model_forward_calls'] == 0
            and report['forward_accounting']['teacher_model_forward_calls'] == 0
            and report['tuning']['rows_evaluated'] == 0 and report['tuning']['used_for_fit_or_selection'] is False,
            'Training-only32/384 accounting or reference boundary differs')
    targeted=namespace['targeted_pure'];policy=report['training_policy']['objective_policy']
    targeted['_validate_policy'](policy)
    require(policy['actor_ranking_enabled'] is True and policy['presence_ce_weight'] == 1
            and policy['actor_hinge_coefficient'] == .25 and policy['actor_hinge_margin'] == 1.,
            'Fixed unchanged .25/margin1 ranking ON objective required')
    batches=report['batch_trace']['batches'];objectives=report['objective_trace']['batches'];hinges=[]
    require(len(batches) == len(objectives) == 32,'Complete32 objective/batch join required')
    for step,(batch,entry) in enumerate(zip(batches,objectives,strict=True),1):
        require(batch['optimizer_step'] == entry['optimizer_step'] == step
                and all(entry[k] == batch[k] for k in ('indices','ids')),'Actual completed objective/source order differs')
        details=entry['details'];diagnostics=targeted['_validate_objective_diagnostics'](details['base_objective'])
        require(diagnostics['actor_hinge_applied'] is True
                and diagnostics['total_loss'] == details['total_loss'] == batch['loss']
                and details['batch_denominator'] == len(batch['indices']) == len(diagnostics['rows']),
                'Existing hinge validator or actual batch loss/denominator join differs')
        for position,(index,identifier,trace) in enumerate(zip(batch['indices'],batch['ids'],diagnostics['rows'],strict=True)):
            row=rows[index];tokens,coordinates=namespace['gold_coordinates'](row)
            require(row['id'] == identifier == trace['id'] and trace['row_position'] == position
                    and trace['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
                    and trace['token_count'] == len(tokens)
                    and tuple(trace['gold_coordinates']) == tuple(coordinates['actor'])
                    and {f:tuple(v) for f,v in trace['present_gold_nonactor_coordinates'].items()}
                    == {f:tuple(v) for f,v in coordinates.items() if f != 'actor'},
                    'Actual objective training ID/source/gold domain authority differs')
            hinges.append(trace)
    require(len(hinges) == 384,'Exact384 completed objective row occurrences required')
    return {'updates':32,'training_rows':168,'training_source_occurrences':384,
            'new_parameter_order':names,'changed_parameter_names':report['changed_parameter_names'],
            'frozen_base34_initial_equals_final':True,'inactive_copied_rows_initial_equals_final':True,
            'existing_targeted_objective_validator_reused':True,'ranking_ON_coefficient':.25,'ranking_margin':1.,
            'completed_trace_hinge_active_occurrences':sum(r['hinge_active'] for r in hinges),
            'completed_trace_empty_domain_occurrences':sum(r['zero_domain_differentiable_zero'] for r in hinges),
            'completed_trace_hinge_sum':math.fsum(r['actor_hinge_value'] for r in hinges),
            'trace_scope':'384 repeated training occurrences before their corresponding updates; not final168 metric.',
            'source':'Qualified saved training metadata; checkpoint JSON remains opaque.'}


def main(args):
    global FREEZE_PASSED
    output=Path(args.output)
    require(output.is_absolute() and output.parent == ROOT and not output.exists(),'Exclusive owned result output required')
    own=pin(Path(__file__).resolve())
    approval_pin=pin(ROOT/'analyzer-source-independent-review-v03.json')
    approval=read(approval_pin['path'],approval_pin)
    require(approval.get('schema') == 'actor-ranking-analyzer-source-independent-review/v1'
            and approval.get('passed') is True and approval.get('findings') == []
            and approval.get('analyzer') == own,'Exact clean independently qualified analyzer source required')
    require_map_pin(approval['artifacts'],own)
    freeze_pin=descriptor({'path':str(Path(args.freeze)),'bytes':args.freeze_bytes,'sha256':args.freeze_sha256})
    require(freeze_pin['path'] == str(ROOT/'actor-ranking-output-freeze-v01.json'),'Exact qualified N9 freeze V01 required')
    freeze=read(freeze_pin['path'],freeze_pin)
    result_root=validate_freeze(freeze,freeze_pin['path'])
    runtime_pin=descriptor(freeze['runtime_review'])
    require(runtime_pin['path'] == str(ROOT/'actor-ranking-hinge-runtime-review-v01.json'),'Exact qualified N9 runtime V01 required')
    runtime=read(runtime_pin['path'],runtime_pin)
    require(Path(runtime['observer']['path']) == ROOT/'freeze_actor_ranking_outputs_v03.py','Exact reviewed runtime producer required')
    require_map_pin(approval['artifacts'],runtime['observer'])
    plan_pin=descriptor(freeze['plan'])
    require(plan_pin['path'] == str(ROOT/'actor-ranking-hinge-plan-v01.json'),'Exact N9 plan V01 required')
    require_map_pin(approval['artifacts'],plan_pin)
    plan=read(plan_pin['path'],plan_pin)
    require(plan.get('schema') == 'actor-ranking-cell-plan/v1' and plan.get('cell') == 'actor-ranking-hinge'
            and plan.get('evaluation_contract') == freeze['evaluation_contract'] == fixed(ROOT/'evaluation-contract-v02.json')
            and plan.get('source_checkpoint',{}).get('sha256') == SOURCE_SHA
            and plan.get('source_model_state_sha256') == SOURCE_STATE
            and plan.get('latent_enabled') is False and plan.get('default_promotion') is False,
            'Qualified actor-only N4-parent plan identity differs')
    summary=bind(freeze['summary'],freeze,result_root,'summary.json')
    require(summary.get('schema') == 'actor-ranking-cell-results/v1' and summary.get('cell') == 'actor-ranking-hinge'
            and summary.get('status') == 'completed' and summary.get('default_promotion') is False
            and all(summary.get(k) is False for k in FALSE)
            and summary['opening_owners'] == summary['closing_owners']
            and all(v == plan['source_owner_pins'].get(k) for k,v in summary['opening_owners'].items()),
            'Completed source-bound actor candidate envelope differs')
    counts=runtime_counts(runtime,summary)
    require(runtime.get('plan') == plan_pin and runtime.get('outputs') == freeze['results'],
            'Qualified runtime output/plan closure differs')
    FREEZE_PASSED=True
    for path,(size,sha) in FIXED.items():
        pin(path,{'path':str(path),'bytes':size,'sha256':sha})
    contract=read(ROOT/'evaluation-contract-v02.json',fixed(ROOT/'evaluation-contract-v02.json'))
    require(contract.get('schema') == 'actor-ranking-evaluation-contract/v1'
            and contract.get('references_parent_only') is contract.get('score_only_after_complete_frozen_bundle') is True
            and contract.get('all464_previously_exposed_engineering_diagnostics') is True
            and contract.get('N7_fresh72_previously_exposed') is contract.get('no_new_blind_generalization_claim') is True
            and contract.get('checkpoint_selection_executed') is False
            and contract.get('threshold_or_hyperparameters_fitted') is False
            and contract.get('default_promotion') is False and contract.get('semantic_accuracy') is None
            and contract.get('law8_unscored') is True and contract.get('required_frozen_output_count') == 62,
            'Preregistered exposed diagnostic scoring contract differs')
    for path,value in approval['artifacts'].items():
        pin(path,value)
    prior=read(N8/'n7-training168-full-ir-modality-audit-v01.json',fixed(N8/'n7-training168-full-ir-modality-audit-v01.json'))
    require(prior.get('passed') is True and prior.get('findings') == []
            and prior.get('prior_153_of_168_claim_wrong') is False
            and prior.get('complete_IR_metric_defect_found') is False
            and prior['metric_definitions']['modality_equality_included_in_raw_and_joint_full_ir'] is True,
            'Qualified N7 modality/full-IR audit differs')
    previous_plan=read(N7/'temporal-attention-ce-plan-v02.json',fixed(N7/'temporal-attention-ce-plan-v02.json'))
    require(plan['source_reference_panels'] == previous_plan['source_reference_panels'],
            'Common immutable N4 old392 raw/joint source references differ')
    namespace,greedy,joint,scorer=pure_predicates(plan)
    data,populations,metadata=references(plan)
    rows=data['training_rows'];sources={p:source_projection(populations[p]) for p in PANELS}
    report=bind(summary['training'],freeze,result_root,'cell-training.json')
    require_map_pin(runtime['artifacts'],summary['training'])
    training=training_metadata(report,rows,namespace)
    actual={};new_inference_rows=0
    def pair(value,source_rows,label,*,state=None):
        nonlocal new_inference_rows
        require(value['row_count'] == len(source_rows),'Pair source count differs')
        raw=bind(value['raw'],freeze,result_root,label+'-raw.json')
        validate_capture(raw,source_rows,greedy,joint,candidate=state is not None,summary=summary,report=report,state=state)
        chosen=validate_joint(bind(value['joint'],freeze,result_root,label+'-joint.json'),raw,source_rows,joint)
        new_inference_rows+=len(source_rows)
        return raw,chosen
    for state,key,prefix in [('initial','baseline_panels','baseline-'),('trained','diagnostics','trained-')]:
        require(set(summary[key]) == set(PANELS),'Complete exposed464 candidate panel set required')
        for panel in PANELS:
            actual[state,panel]=pair(summary[key][panel],sources[panel],prefix+panel,state=state)
    for state,key,label in [('initial','initial_training_capture','initial-training168'),
                            ('parent','parent_training_capture','parent-training168'),
                            ('trained','final_training_capture','trained-training168')]:
        actual[state,'training168']=pair(summary[key],rows,label,state=None if state == 'parent' else state)
    require(set(summary['parent_fresh_panels']) == set(FRESH_PANELS),'Parent fresh72 source capture scope differs')
    for panel in FRESH_PANELS:
        actual['parent',panel]=pair(summary['parent_fresh_panels'][panel],sources[panel],'parent-'+panel)
    for panel in OLD_PANELS:
        value=plan['source_reference_panels'][panel]
        raw=read(value['raw']['path'],value['raw'])
        validate_capture(raw,sources[panel],greedy,joint)
        chosen=validate_joint(read(value['joint']['path'],value['joint']),raw,sources[panel],joint)
        actual['parent',panel]=raw,chosen
    for panel in (*PANELS,'training168'):
        require(actual['parent',panel][0]['inference']['checkpoint_sha256'] == SOURCE_SHA,
                'Complete immutable N4 parent capture identity differs')
    initial={};protected={};actor_changed={}
    for panel in (*PANELS,'training168'):
        source_rows=rows if panel == 'training168' else sources[panel]
        parent,first,last=(actual[state,panel] for state in ('parent','initial','trained'))
        initial[panel]=compare_saved(source_rows,parent[0],first[0],full=True,before_joint=parent[1],after_joint=first[1])
        protected[panel]=compare_saved(source_rows,first[0],last[0],full=False)
        actor_changed[panel]=[a['id'] for a,b in zip(first[0]['occurrences'],last[0]['occurrences'],strict=True)
            if binary({'start':a['scores']['start_logits']['actor'],'end':a['scores']['end_logits']['actor']})
            != binary({'start':b['scores']['start_logits']['actor'],'end':b['scores']['end_logits']['actor']})]
    require(sum(map(len,initial.values())) == sum(map(len,protected.values())) == 632,'Complete632 actual parity recount differs')
    initial_receipt=bind({'path':str(result_root/'initial-parent-head-parity.json'),
                         **freeze['results'][str(result_root/'initial-parent-head-parity.json')]},freeze,result_root,'initial-parent-head-parity.json')
    final_receipt=bind({'path':str(result_root/'trained-frozen-head-retention.json'),
                       **freeze['results'][str(result_root/'trained-frozen-head-retention.json')]},freeze,result_root,'trained-frozen-head-retention.json')
    require(initial_receipt['schema'] == 'actor-ranking-initial-parent-parity/v1'
            and initial_receipt['source_rows'] == 632
            and initial_receipt['old392']['source_rows'] == 392
            and initial_receipt['old392']['rows'] == [dict(panel=p,**r,exact=True) for p in OLD_PANELS for r in initial[p]]
            and initial_receipt['new240'] == sum((initial[p] for p in (*FRESH_PANELS,'training168')),[])
            and initial_receipt['all_compared_components_bit_equal'] is True
            and initial_receipt['optimizer_updates_before_gate'] == 0,'Saved initial full632 gate differs from actual raw recount')
    require(final_receipt['schema'] == 'actor-ranking-frozen-head-retention/v1'
            and final_receipt['source_rows'] == 632 and final_receipt['rows'] == protected
            and final_receipt['all_compared_components_bit_equal'] is True
            and final_receipt['compared_actor_start_end'] is False
            and final_receipt['compared_all_presence'] is final_receipt['compared_modality'] is True
            and final_receipt['compared_other_five_role_boundaries'] is True,'Saved protected632 gate differs from actual raw recount')
    dormant=[]
    names=('zeros','alternate_placeholders','disabled','rotated_placeholders')
    for phase,key in [('initial','initial_parity'),('trained','trained_parity')]:
        receipt=bind(summary[key],freeze,result_root,phase+'-parity.json')
        require(receipt['passed'] is True and receipt['source_count'] == 2
                and receipt['genuine_latent_semantics_tested'] is False and receipt['actual_encoder_calls'] == 0
                and [r['name'] for r in receipt['controls']] == list(names),'Complete dormant control receipt differs')
        first=None
        for item in receipt['controls']:
            source_rows=deepcopy(sources['fresh_tune'][:2])
            for i,row in enumerate(source_rows):
                row['latent']=[0. if item['name'] == 'zeros' else .25 if i == 0 else -.25]*384
            if item['name'] == 'rotated_placeholders':
                source_rows[0]['latent'],source_rows[1]['latent']=source_rows[1]['latent'],source_rows[0]['latent']
            raw=bind(item['report'],freeze,result_root,phase+'-parity-'+item['name']+'.json')
            validate_capture(raw,source_rows,greedy,joint,candidate=True,summary=summary,report=report,state=phase,latent=item['control'])
            current=[{'tokens':occ['scores']['tokens'],'binary32':binary(projection(occ['scores'],True)).hex(),
                      'readout':{k:g.get(k) for k in ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')}}
                      for occ,g in zip(raw['occurrences'],raw['inference']['rows'],strict=True)]
            require(first is None or canonical(first) == canonical(current),'Dormant latent control changes complete head/readout')
            first=current;new_inference_rows+=2
        dormant.append({'phase':phase,'controls':4,'rows_each':2,'invariant':True,'genuine_latent_semantics_tested':False})
    require(new_inference_rows == 1520,'Actual saved new capture inference scope differs')
    summaries=[];scores={};coverage={}
    for (state,panel),(raw,chosen) in actual.items():
        if state == 'parent' and panel in OLD_PANELS:
            continue
        source_rows=rows if panel == 'training168' else populations[panel]
        meta=data['training_metadata'] if panel == 'training168' else metadata.get(panel)
        compact,record,cov=panel_score(panel,state,source_rows,meta,raw,chosen,scorer,namespace,joint)
        summaries.append(compact)
        if record is not None:
            scores[state,panel]=record;coverage[state,panel]=cov
    require(len(summaries) == 23 and len(scores) == 21,'Exact23 panel/21 authored score-set scope differs')
    for route,key in [('raw','raw_exact_ir'),('joint','joint_exact_ir')]:
        require(sum(r[key] for r in scores['parent','training168'])
                == prior['states']['parent']['totals'][route]['full_ir_exact'] == 153,
                'Common N4 parent training168 full-IR audit baseline differs')
    paired={};coupling={};initial_coverage_changes={}
    for panel in (*[p for p in PANELS if p != 'law'],'training168'):
        paired[panel]=paired_changes(scores['initial',panel],scores['trained',panel])
        coupling[panel]=decoded_coupling(actual['initial',panel][0],actual['trained',panel][0],
                                        actual['initial',panel][1],actual['trained',panel][1])
        before,after=coverage['initial',panel],coverage['trained',panel]
        initial_coverage_changes[panel]=coverage_changes(before,after)
    ce_actual,ce_summaries,ce_scores,ce_coverage,ce_custody=frozen_CE(
        contract,rows,data['training_metadata'],populations,metadata,greedy,joint,scorer,namespace,report)
    summaries.extend(ce_summaries)
    ce_paired={};ce_rank={};ce_coupling={}
    ce_protected={}
    for panel in (*PANELS,'training168'):
        source_rows=rows if panel == 'training168' else sources[panel]
        ce_protected[panel]=compare_saved(source_rows,ce_actual[panel][0],actual['trained',panel][0],full=False)
    require(sum(map(len,ce_protected.values())) == 632,'Complete CE/N9 protected632 comparison differs')
    for panel in (*[p for p in PANELS if p != 'law'],'training168'):
        ce_paired[panel]=paired_changes(ce_scores[panel],scores['trained',panel])
        ce_rank[panel]=coverage_changes(ce_coverage[panel],coverage['trained',panel])
        ce_coupling[panel]=decoded_coupling(ce_actual[panel][0],actual['trained',panel][0],
                                           ce_actual[panel][1],actual['trained',panel][1])
    focus=set(prior['states']['trained']['totals']['joint']['full_ir_failure_ids'])
    for route in (*paired['training168'].values(),*ce_paired['training168'].values()):
        for metric in route.values():
            focus.update(metric['gain_ids']);focus.update(metric['loss_ids'])
    training_focus=[]
    for i,source in enumerate(rows):
        if source['id'] in focus:
            training_focus.append({'id':source['id'],
                'initial_score_flags':scores['initial','training168'][i],'trained_score_flags':scores['trained','training168'][i],
                'initial_actor_coverage':coverage['initial','training168'][i],'trained_actor_coverage':coverage['trained','training168'][i],
                'frozen_CE_score_flags':ce_scores['training168'][i],'frozen_CE_actor_coverage':ce_coverage['training168'][i]})
    for path,identity in list(OBSERVED.items()):
        pin(path,identity)
    legacy=next(r for r in summaries if r['state'] == 'trained' and r['panel'] == 'old_tune')
    result={'schema':'actor-ranking-exposed-result-analysis/v1','passed':True,'findings':[],
        'observed_at_utc':datetime.now(timezone.utc).isoformat(),'analyzer':own,'independent_source_review':approval_pin,
        'freeze':freeze_pin,'runtime_review':runtime_pin,'plan':plan_pin,'evaluation_contract':fixed(ROOT/'evaluation-contract-v02.json'),
        'qualified_N7_full_IR_modality_audit':fixed(N8/'n7-training168-full-ir-modality-audit-v01.json'),
        'accounting':counts,'training_metadata':training,'panel_count':33,'authored_score_sets':30,'paired_panel_count':9,
        'frozen_CE_comparison':ce_custody,'paired_frozen_CE_to_N9':ce_paired,
        'actor_coverage_frozen_CE_to_N9':ce_rank,'decoded_coupling_frozen_CE_to_N9':ce_coupling,
        'frozen_CE_N9_protected632_equal':True,
        'panel_summaries':summaries,'paired_initial_to_trained':paired,'decoded_nonactor_coupling':coupling,
        'actor_gold_coverage_changes':initial_coverage_changes,'training_focus':training_focus,
        'initial_full_head_parity':{'rows':632,'all_binary32_components_equal':True,
            'panels':{p:{'rows':len(v),'records_sha256':digest(v)} for p,v in initial.items()}},
        'final_protected_head_retention':{'rows':632,'all_required_binary32_components_equal':True,
            'excluded_components_only':['start_logits.actor','end_logits.actor'],
            'panels':{p:{'rows':len(v),'records_sha256':digest(v)} for p,v in protected.items()},
            'actor_vector_changed_ids':actor_changed},
        'dormant_controls':dormant,'legacy_exposed_retention_diagnostic':{'raw_exact_ir':legacy['raw_exact_ir'],
            'joint_exact_ir':legacy['joint_exact_ir'],'permission_outcomes':legacy['permission_outcomes'],
            'all32P_retained':all(v == dict(P_to_P=32,P_to_O=0,P_to_F=0,P_abstentions=0) for v in legacy['permission_outcomes'].values()),
            'frozen_CE_full_IR_baseline':94,'full_IR_changes_vs_CE':ce_paired['old_tune'],
            'used_for_selection':False},
        'all_panels_previously_exposed_diagnostics':True,'new_blind_generalization_claim':False,
        'checkpoint_selection_executed':False,'automatic_selection_or_promotion':False,'engineering_selection':None,
        'default_promotion':False,'semantic_accuracy':None,'independent_statutory_gold':False,
        'Lake_executed':False,'broader_logic_families_qualified':False,'genuine_latent_semantics_qualified':False,
        'statutory8_unscored':True,'metric_full_IR_includes_modality':True,'evaluation_reference_gold_used_in_model_child':False,
        'checkpoint_JSON_parses':0,'model_or_encoder_calls':0,'new_optimizer_updates_by_analyzer':0,
        'private_body_reads':0,'resource_API_calls':0,'network_calls':0,'Git_mutations':0,
        'input_pins':OBSERVED,'closing_raw_pins_unchanged':True,
        'limits':['Actor and full-IR metrics are separately reported; the six-role map omits modality only as a diagnostic decomposition.',
            'Fixed nonactor score vectors can produce different copied nonactor spans through greedy/joint nonoverlap coupling.',
            'Top8 gold coverage is reference-dependent post-inference analysis and does not insert gold or prove full-domain optimality.',
            'All inherited and N7fresh panels are exposed authored engineering diagnostics, with no selection or blind semantic accuracy claim.']}
    require(len(summaries) == 33 and len(paired) == len(ce_paired) == 9,
            'Exact33 total panel and nine paired exposed authored scopes required')
    encoded=(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    require(len(encoded) <= 2000000,'Bounded summary exceeds2MB; do not duplicate raw arrays')
    with output.open('xb') as handle:
        handle.write(encoded);handle.flush();os.fsync(handle.fileno())
    output.chmod(0o444)
    print(json.dumps({'path':str(output),'bytes':len(encoded),'sha256':hashlib.sha256(encoded).hexdigest(),
                      'passed':True,'default_promotion':False,'semantic_accuracy':None}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',required=True)
    parser.add_argument('--freeze-bytes',type=int,required=True)
    parser.add_argument('--freeze-sha256',required=True)
    parser.add_argument('--output',default=str(ROOT/'actor-ranking-result-analysis-v01.json'))
    main(parser.parse_args())
