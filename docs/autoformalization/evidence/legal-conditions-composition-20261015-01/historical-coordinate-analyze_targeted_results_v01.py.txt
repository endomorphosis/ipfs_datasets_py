"""Analyze an independently frozen four-cell matrix without opening models.

Evaluation references are opened only after the full four-cell hash/terminal/
returned-update chain passes and the caller explicitly requests authored eval
scoring. Checkpoints stay opaque. No model, numerical, resource or compiler API
is imported or invoked; saved head-score arithmetic and authored scoring use
named frozen-source Python predicates only.
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
import random
import re
import stat
import struct
import sys
from types import SimpleNamespace

M = Path(__file__).resolve().parent
T = M.parent/'legal-temporal-binding-20261012-01'
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
PACKET = M/'authored-reference-packet-v01.json'
REGISTRATION = M/'registration-v01.json'
EXPORT = M/'training-export-v01.json'
RUNNER = M/'run_targeted_loss.py'
HELPER = T/'run_temporal_contrast_pilot.py'
HELPER_SHA = '0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'
FIXED_PINS = {RUNNER:dict(bytes=35247,sha256='092cc00ee5f55f1cbb33b76cabaf3aa759ad7e6b444385a87bcba06f861f3c78')}
TARGETED = M/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_targeted_loss.py'
TARGETED_PIN = dict(bytes=49658,sha256='f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b')
TARGETED_PURE = None

FIELDS = ('actor','action','object','conditions','exceptions','temporal')
PANELS = ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law')
COUNTS = dict(old_tune=96,fresh_tune=36,fresh_challenge=36,old_authored_eval=72,authored_dev=72,authored_eval=72,law=8)
FALSE = dict(qualified=False,admitted=False,formalized=False,proof_authority=False,
             semantic_correctness_verified=False,promotion_performed=False)
CELLS = {f'rank{rank}-presence{presence}':dict(id=f'rank{rank}-presence{presence}',actor_ranking_enabled=bool(rank),presence_ce_weight=presence,modality_loss_weight=2)
         for rank,presence in itertools.product((0,1),(1,2))}
OLD_CONTRAST_REGRESSIONS = ('native-tuning-calendula-t4-q5-p','native-tuning-calendula-t6-q7-p',
                          'native-tuning-hellebore-t0-q3-p','native-tuning-hellebore-t1-q4-p')
MAX_JSON_BYTES = 128*1024*1024
PACKET_ALLOWED = False
OUTPUT = None


def require(condition,message):
    if not condition:raise ValueError(message)


def audit(event,args):
    if event=='import' and args[0].split('.')[0] in {'torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'}:
        raise AssertionError('Saved-result analyzer forbids numerical/production imports')
    if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock',
            'os.mkdir','os.remove','os.rename','os.replace','os.rmdir','os.unlink'}:
        raise AssertionError('Saved-result analyzer forbids process/network/resource/filesystem operations')
    if event=='open':
        p,mode,flags=args
        if isinstance(p,(str,bytes,os.PathLike)):
            resolved=Path(os.fsdecode(p)).absolute()
            if resolved==PACKET and not PACKET_ALLOWED:
                raise AssertionError('Four-cell freeze and explicit scoring authorization required before packet access')
        else:resolved=None
        write=isinstance(mode,str) and any(c in mode for c in 'wax+')
        write|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write and (OUTPUT is None or resolved!=OUTPUT):
            raise AssertionError('Only one exclusive owned analysis output may be written')


sys.dont_write_bytecode=True
sys.addaudithook(audit)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pair(value):
    return {key:value[key] for key in ('bytes','sha256')}


def pin(path):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path,'Absolute canonical artifact required')
    for part in (*reversed(path.parents),path):
        info=part.lstat();require(not stat.S_ISLNK(info.st_mode),'Symlink artifact refused')
        require(stat.S_ISREG(info.st_mode) if part==path else stat.S_ISDIR(info.st_mode),'Ordinary artifact required')
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());hashed=hashlib.sha256();size=0
        for block in iter(lambda:stream.read(1048576),b''):hashed.update(block);size+=len(block)
        after=os.fstat(stream.fileno())
    current=path.lstat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after)==identity(current),'Artifact changed during raw hash')
    return dict(path=str(path),bytes=size,sha256=hashed.hexdigest())


def checked_pin(value,expected_path=None):
    require(type(value) is dict and set(value)=={'path','bytes','sha256'},'Closed absolute raw pin required')
    if expected_path is not None:require(value['path']==str(expected_path),'Exact artifact role/path required')
    actual=pin(Path(value['path']));require(actual==value,'Frozen raw artifact drift')
    return actual


def read(path):
    path=Path(path)
    require(not ('checkpoint' in path.name and path.suffix=='.json'), 'Checkpoint JSON parsing is prohibited')
    require(path.stat().st_size<=MAX_JSON_BYTES,'Bounded JSON required before allocation')
    def unique(items):
        result={}
        for key,value in items:require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    def reject(value):raise ValueError('Nonfinite JSON constant '+value)
    value=json.loads(path.read_bytes(),object_pairs_hook=unique,parse_constant=reject)
    def finite(item):
        if type(item) is float:require(math.isfinite(item),'Finite JSON numbers required')
        elif type(item) is list:
            for child in item:finite(child)
        elif type(item) is dict:
            for child in item.values():finite(child)
    finite(value);return value


def ordinary_inventory(root):
    root=Path(root);require(root.is_dir() and not root.is_symlink(),'Ordinary result directory required')
    entries={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(),'Symlink in result bundle refused')
        if path.is_dir():continue
        require(len(entries)<1024 and path.suffix=='.json','Bounded JSON-only result bundle required')
        entries[str(path)]=pair(pin(path))
    return entries


def schedule(rows,seed=1729):
    epoch=cursor=0;indices=[];ids=[]
    for _ in range(32):
        order=list(range(len(rows)));random.Random(seed+epoch).shuffle(order)
        batch=order[cursor:cursor+12];indices.append(batch);ids.append([rows[i]['id'] for i in batch]);cursor+=len(batch)
        if cursor==len(rows):epoch+=1;cursor=0
    return dict(batch_indices=indices,batch_ids=ids,batch_indices_sha256=digest(indices),
                final_progress=dict(epochs_completed=epoch,row_cursor=cursor,optimizer_steps=32))


def targeted_pure():
    global TARGETED_PURE
    require(pair(pin(TARGETED))==TARGETED_PIN,'Exact independently reviewed targeted policy source required')
    if TARGETED_PURE is None:
        names={'_require','_raw','checkpoint_digest','_policy','_validate_policy','_f32','_span_coordinates','_actor_domain','_validate_objective_diagnostics','_objective_trace_summary'}
        namespace=dict(copy=SimpleNamespace(deepcopy=deepcopy),hashlib=hashlib,json=json,math=math,struct=struct,
            SPAN_FIELDS=FIELDS,MAX_SOURCE_TOKENS=128,MAX_NEW_STEPS=32,MAX_SECONDS=32,
            POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
            LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995',
            span=SimpleNamespace(_SHA=re.compile(r'[0-9a-f]{64}\Z')))
        TARGETED_PURE=detached(TARGETED,names,namespace)
    return TARGETED_PURE


def expected_policy(cell):
    require(canonical(cell)==canonical(CELLS[cell['id']]),'Exact objective-factor cell required')
    return targeted_pure()['_policy'](1729,actor_ranking_enabled=cell['actor_ranking_enabled'],
        presence_ce_weight=cell['presence_ce_weight'],batch_order_seed=1729,batch_size=12)


def validate_training(summary,report,plan,rows,checkpoint_pin):
    require(report['schema']=='bounded-targeted-loss-span-legal-formula-training/v1'
        and all(report.get(k) is v for k,v in FALSE.items()),'New unqualified authoritative training schema required')
    require(type(report['optimizer_steps']) is int and report['optimizer_steps']==report['continuation_optimizer_steps_total']==32
        and report['training_executed'] is True and report['stopped_reason']=='step_limit','Complete32 returned updates required')
    require(report['checkpoint_sha256']==checkpoint_pin['sha256'],'Opaque canonical checkpoint raw hash/report join differs')
    require(report['source_parent_checkpoint_sha256']==plan['parent_base_canonical_sha256']
        and report['source_parent_model_state_sha256']==plan['parent_model_state_sha256'],'Exact common source parent differs')
    policy=expected_policy(plan['cell']);require(canonical(report['training_policy'])==canonical(policy)
        and report['training_policy_sha256']==digest(policy),'Exact weighted objective/order policy differs')
    prepared=schedule(rows);require(summary['prepared_schedule']==prepared,'Same matched index schedule required')
    trace=report['batch_trace'];require(trace['schema']=='completed-curriculum-batch-trace/v1'
        and trace['training_count']==168 and trace['completed_updates']==32 and trace['training_manifest_sha256']==digest(rows)
        and trace['batch_size']==12 and trace['batch_order_seed']==1729 and trace['batch_order_seed_origin']=='explicit'
        and trace['scope']=='indices_and_IDs_used_by_this_trainer_recorded_after_returned_optimizer_step_and_finite_guards'
        and trace['independent_runtime_trace'] is False and trace['unreturned_partial_updates_attested'] is False,
        'Completed trace authority/population/order differs')
    initial=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0)
    require(trace['initial_progress']==initial and trace['final_progress']==prepared['final_progress'],'Trace initial/final progress differs')
    batches=trace['batches'];require(type(batches) is list and len(batches)==32
        and len(report['batch_losses'])==32,'Exactly32 actual batch entries/losses required')
    progress=dict(initial)
    for step,(entry,indices,ids,loss) in enumerate(zip(batches,prepared['batch_indices'],prepared['batch_ids'],report['batch_losses'],strict=True),1):
        require(set(entry)=={'schema','indices','ids','pre_progress','post_progress','optimizer_step','loss','gradient_norm_before_clip'}
            and entry['schema']=='completed-curriculum-batch/v1' and entry['indices']==indices and entry['ids']==ids
            and entry['pre_progress']==progress and type(entry['optimizer_step']) is int and entry['optimizer_step']==step
            and type(loss) in (int,float) and math.isfinite(loss) and loss>=0 and entry['loss']==loss
            and type(entry['gradient_norm_before_clip']) in (int,float) and math.isfinite(entry['gradient_norm_before_clip'])
            and entry['gradient_norm_before_clip']>=0,'Completed actual batch chain differs')
        progress['optimizer_steps']+=1;progress['row_cursor']+=len(indices)
        if progress['row_cursor']==168:progress['epochs_completed']+=1;progress['row_cursor']=0
        require(entry['post_progress']==progress,'Actual post-update transition differs')
    require(progress==prepared['final_progress'] and trace['indices_sha256']==digest(prepared['batch_indices'])
        and trace['ids_sha256']==digest(prepared['batch_ids']) and trace['batches_sha256']==digest(batches),'Completed trace hashes differ')
    require(all(type(report[k]) is str and re.fullmatch(r'[0-9a-f]{64}',report[k])
        for k in ('initial_targeted_checkpoint_sha256','previous_targeted_checkpoint_sha256')),
        'Reported initial self-free and previous complete outer fingerprint formats differ')
    require(report['gradient_norm_max']==max(b['gradient_norm_before_clip'] for b in batches),'Recorded gradient-norm summary differs')
    tuning=report['tuning'];require(type(tuning['rows_evaluated']) is int and 0<=tuning['rows_evaluated']<=96
        and tuning['complete'] is (tuning['rows_evaluated']==96) and tuning['teacher_forcing'] is True
        and tuning['used_for_fit_or_selection'] is False and tuning['objective_policy_sha256']==digest(policy)
        and (tuning['objective_loss'] is None if tuning['rows_evaluated']==0 else type(tuning['objective_loss']) in (int,float)
            and math.isfinite(tuning['objective_loss']) and tuning['objective_loss']>=0),
        'Exposed tuning diagnostic or objective identity differs')
    objective=validate_objective_trace(report,rows,policy,batches)
    changed=report['changed_parameter_names'];require(type(changed) is list and len(changed)==len(set(changed))
        and all(type(k) is str and not k.startswith('latent_') for k in changed),'Reported dormant latent change or parameter duplication')
    return dict(policy=policy,policy_sha256=digest(policy),recorded_completed_updates=32,trace_sha256=digest(trace),
        trace_indices_sha256=trace['indices_sha256'],trace_IDs_sha256=trace['ids_sha256'],final_progress=progress,
        checkpoint_opaque_raw_pin=checkpoint_pin,checkpoint_JSON_parsed=False,
        objective_trace=objective,initial_targeted_checkpoint_sha256=report['initial_targeted_checkpoint_sha256'],
        previous_complete_outer_checkpoint_sha256=report['previous_targeted_checkpoint_sha256'],
        outer_fingerprint_scope='Reported opaque lineage: initial excludes its self-fingerprint; previous includes it; no model reconstruction',
        changed_parameter_names_reported=changed,tuning_loss=tuning['objective_loss'],
        tuning_loss_rows_evaluated=tuning['rows_evaluated'],tuning_loss_complete=tuning['complete'],
        tuning_loss_comparable_across_different_objective_weights=False)


def detached(path,names,namespace):
    tree=ast.parse(Path(path).read_text());selected=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    require({n.name for n in selected}==set(names),'Exact pure saved-predicate set required')
    require(not any(getattr(n,'decorator_list',[]) for n in selected),'Detached predicate decorators refused')
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def geometry_validator():
    require(pair(pin(RUNNER))==FIXED_PINS[RUNNER] and pin(HELPER)['sha256']==HELPER_SHA,'Exact pure geometry source required')
    ns=dict(require=require,canonical=canonical,digest=digest,math=math,FIELDS=FIELDS,FALSE=FALSE,
        DATA_SCHEMA='targeted-loss-curriculum-export/v1',
        REFERENCE_SCOPE='Authored engineering only; eval references excluded until all matrix outputs are frozen',
        closed=lambda value,keys,label:require(type(value) is dict and set(value)==set(keys),'Closed '+label))
    authored=detached(HELPER,{'validate_authored_pairs'},dict(ns))
    geometry=detached(RUNNER,{'validate_data'},dict(ns))
    return lambda plan,data:geometry['validate_data'](plan,data,SimpleNamespace(validate_authored_pairs=authored['validate_authored_pairs']))


def expected_result_paths(root,first):
    names={'cell-checkpoint.json','cell-training.json','data-schedule-before-models.json','summary.json'}
    for stage in ('initial','trained'):
        names.add(stage+'-parity.json')
        names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    for state in (('baseline','trained') if first else ('trained',)):
        for panel in PANELS:
            names.update(state+'-'+panel+'-'+kind+'.json' for kind in ('raw','joint'))
            if panel not in ('authored_eval','law'):names.add(state+'-'+panel+'-score.json')
    return {str(root/name) for name in names}


def tokenize(source):
    require(type(source) is str and source.strip() and len(source)<=16384,'Bounded source required')
    rows=[dict(text=m.group(),start=m.start(),end=m.end()) for m in re.finditer(r'\w+|[^\w\s]',source,re.UNICODE)]
    require(0<len(rows)<=256 and all(len(t['text'].casefold().encode())<=2048 for t in rows),'Bounded complete source tokens required')
    return rows


def strict_rule(ir):
    require(type(ir) is dict and set(ir)=={'rules'} and type(ir['rules']) is list and len(ir['rules'])==1,'Single copied rule required')
    rule=ir['rules'][0];require(type(rule) is dict and set(rule)=={'modality',*FIELDS} and rule['modality'] in ('O','P','F'),'Closed typed copied rule')
    for field in FIELDS:
        v=rule[field]
        if field in FIELDS[3:]:require(type(v) is list and len(v)<=1 and all(type(x) is str and x.strip() for x in v),'Single qualifier required')
        else:require(type(v) is str and (field=='object' or v.strip()),'Actor/action/source atom required')
    return rule


def gold_coordinates(row):
    """Exact retained character/token matching, without a model or codec import."""
    text=row['source_text'];tokens=tokenize(text);rule=strict_rule(row['canonical_ir'])
    require(len(tokens)<=128,'Targeted source token limit differs')
    starts={t['start']:i for i,t in enumerate(tokens)};ends={t['end']:i for i,t in enumerate(tokens)}
    active={}
    for field in FIELDS:
        atom=(rule[field][0] if rule[field] else '') if field in FIELDS[3:] else rule[field]
        if not atom:
            require(field in FIELDS[2:],'Required gold actor/action is empty');continue
        locations=[];cursor=0
        while True:
            offset=text.find(atom,cursor)
            if offset<0:break
            if offset in starts and offset+len(atom) in ends:locations.append((starts[offset],ends[offset+len(atom)]))
            cursor=offset+1
        require(len(locations)==1,'Gold atom must be uniquely exact and token aligned')
        active[field]=locations[0]
    require(all(b<c or d<a for i,(a,b) in enumerate(active.values()) for c,d in list(active.values())[i+1:]),'Gold source facets overlap')
    return tokens,active


def validate_objective_trace(report,rows,policy,batches):
    """Join saved scalar contracts to actual teacher-forced source annotations."""
    pure=targeted_pure();objective=report['objective_trace']
    require(type(objective) is dict and type(objective.get('batches')) is list,'Objective trace required')
    expected=pure['_objective_trace_summary'](objective['batches'],batches,policy)
    require(canonical(objective)==canonical(expected),'Closed objective trace/hash/policy/loss association differs')
    geometry=[gold_coordinates(row) for row in rows]
    all_rows=[]
    for entry in objective['batches']:
        actual=entry['diagnostics']['rows'];indices=entry['indices']
        width=max(len(geometry[i][0]) for i in indices)
        for position,(index,diagnostic) in enumerate(zip(indices,actual,strict=True)):
            source=rows[index];tokens,active=geometry[index]
            require(diagnostic['id']==source['id'] and diagnostic['source_sha256']==hashlib.sha256(source['source_text'].encode()).hexdigest()
                and diagnostic['row_position']==position and diagnostic['token_count']==len(tokens)
                and diagnostic['padded_score_width']==width and diagnostic['gold_coordinates']==list(active['actor'])
                and diagnostic['present_gold_nonactor_coordinates']=={f:list(v) for f,v in active.items() if f!='actor'},
                'Actual source/label/domain geometry differs from objective trace')
            all_rows.append(diagnostic)
    return dict(schema=objective['schema'],sha256=digest(objective),completed_updates=32,
        actual_source_row_occurrences=len(all_rows),source_and_gold_geometry_joined=True,
        hinge_scalar_associations_checked=True,numerical_logits_argmax_gradients_replayed=False,
        policy_actor_hinge_applied=policy['actor_ranking_enabled'],counterfactual_hinge_recorded_when_OFF=True,
        zero_wrong_domains=sum(r['compatible_wrong_candidate_count']==0 for r in all_rows),
        hinge_active_rows=sum(r['hinge_active'] for r in all_rows),
        compatible_wrong_domain_counts=dict(Counter(str(r['compatible_wrong_candidate_count']) for r in all_rows)),
        source_token_counts=dict(Counter(str(r['token_count']) for r in all_rows)),
        scope='Teacher-forced saved scalar/source joins only; no original logits, argmax choice or gradient replay')


def candidate_mechanism(row,scores,score,joint):
    """Separate inference raw-domain rank from target-dependent compatible rank."""
    tokens,active=gold_coordinates(row);actor=active['actor'];others={f:v for f,v in active.items() if f!='actor'}
    rankings,_=joint['_rank_spans'](scores,'actor')
    raw_rank=next(i for i,c in enumerate(rankings,1) if tuple(c[1:])==actor)
    compatible=[c for c in rankings if all(c[2]<a or b<c[1] for a,b in others.values())]
    compatible_rank=next(i for i,c in enumerate(compatible,1) if tuple(c[1:])==actor)
    gold_score=next(c[0] for c in rankings if tuple(c[1:])==actor)
    presence={}
    for field in FIELDS[2:]:
        choice,margin=joint['_choice'](scores['presence_logits'][field]);expected=field in active
        presence[field]=dict(expected_present=expected,predicted_present=choice==1,margin_float32=margin,
            correct=(choice==1)==expected,gold_coordinates=list(active[field]) if expected else None)
        if expected:
            ranks,_=joint['_rank_spans'](scores,field)
            presence[field]['gold_raw_boundary_rank']=next(i for i,c in enumerate(ranks,1) if tuple(c[1:])==active[field])
    modality,margin=joint['_choice'](scores['modality_logits'])
    return dict(id=row['id'],source_sha256=hashlib.sha256(row['source_text'].encode()).hexdigest(),
        gold_actor_coordinates=list(actor),gold_actor_score_float32=gold_score,
        raw_actor_domain_count=len(rankings),gold_compatible_actor_domain_count=len(compatible),
        raw_actor_rank=raw_rank,gold_compatible_actor_rank=compatible_rank,
        raw_actor_in_K8=raw_rank<=8,raw_actor_in_K16=raw_rank<=16,
        incompatible_actor_spans_ahead_of_gold=raw_rank-compatible_rank,
        raw_actor_top_score_minus_gold_float32=f32(rankings[0][0]-gold_score),
        compatible_actor_top_score_minus_gold_float32=f32(compatible[0][0]-gold_score),
        expected_modality=row['canonical_ir']['rules'][0]['modality'],
        saved_modality_choice=('O','P','F')[modality],modality_margin_float32=margin,
        raw_actor_exact=score['role_exact']['actor'],joint_actor_exact=score['joint_role_exact']['actor'],
        optional_presence=presence,
        compatibility_authority='Target-dependent gold nonoverlap diagnostic; inference topK8 precedes compatibility',
        inference_candidate_coverage_guaranteed=False)


def f32(value):
    require(type(value) in (int,float) and math.isfinite(value),'Finite scalar required')
    result=struct.unpack('!f',struct.pack('!f',value))[0];require(math.isfinite(result),'Finite float32 required')
    return result


def scorers(owners):
    require(pin(HELPER)['sha256']==HELPER_SHA,'Exact retained pure scorer source required')
    common=dict(hashlib=hashlib,json=json,math=math,struct=struct)
    capture=owners['ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture']['path']
    greedy=detached(capture,{'_require','_wire','_same','_f32','_pair_winners','_verify_greedy'},dict(common,SPAN_FIELDS=FIELDS,OPTIONAL_FIELDS=FIELDS[2:],MODALITIES=('O','P','F')))
    joint_path=owners['ipfs_datasets_py.logic.legal_ir.joint_span_selection']['path']
    flags={**FALSE,'roundtrip_ok':False,'publication_performed':False,'default_promoted':False,'target_access':False,
        'teacher_forcing':False,'training_executed':False,'model_execution_performed':False,'encoder_execution_performed':False,'Lake_executed':False}
    joint_ns=dict(common,SCORE_SCHEMA='joint-source-span-scores/v1',SCHEMA='joint-copied-span-selection/v1',ORIGIN='bounded_joint_source_span_selector',
        FIELDS=FIELDS,OPTIONAL_FIELDS=FIELDS[2:],QUALIFIERS=FIELDS[3:],MODALITIES=('O','P','F'),AMBIGUITY_GUARD=1e-7,
        MAX_TOP_K=16,MAX_SEARCH_NODES=50000,FALSE=flags,_owner=lambda:SimpleNamespace(tokenize_source=tokenize,codec_module=SimpleNamespace(_rule=strict_rule)))
    joint=detached(joint_path,{'JointSelectionError','_require','_raw','_f32','_keys','_validated','_choice','_rank_spans','_span','_canonical','_greedy','select_joint_spans'},joint_ns)
    score=detached(HELPER,{'score_panel'},dict(require=require,canonical=canonical,digest=digest,f32=f32,re=re,hashlib=hashlib,
        FIELDS=FIELDS,FALSE=FALSE,itertools=itertools,closed=lambda v,k,l:require(type(v) is dict and set(v)==set(k),'Closed '+l)))
    return greedy,joint,score


def validate_capture(raw,rows,model,greedy,joint,*,control='none',vectors=None):
    require(raw['schema']=='temporal-contrast-target-free-head-capture/v1' and raw['actual_source_forwards']==len(rows)
        and raw['extra_capture_forwards']==0 and raw['target_access'] is False and raw['teacher_forcing'] is False
        and raw['model_weights_unchanged'] is True and raw['original_greedy_observations_verified'] is True
        and raw['ambient_CPU_RNG_preserved'] is True and all(raw.get(k) is v for k,v in FALSE.items()),'Saved target-free capture scope differs')
    inference=raw['inference'];require(inference['schema']=='warm-start-span-legal-formula-inference/v1'
        and inference['checkpoint_sha256']==model['continuation_sha256']
        and inference['source_parent_checkpoint_sha256']==model['parent_base_sha256']
        and inference['source_parent_optimizer_steps']==400 and inference['context_contract_sha256']==model['context_sha256']
        and inference['latent_ablation']==control and inference['target_access'] is False and inference['teacher_forcing'] is False
        and inference['training_executed'] is False and all(inference.get(k) is v for k,v in FALSE.items()),'Saved inference source/model/context differs')
    if 'base_sha256' in model:require(inference['base_checkpoint_sha256']==model['base_sha256'],'Saved base identity differs')
    require(len(inference['rows'])==len(raw['occurrences'])==len(rows),'Full source occurrence coverage required')
    for index,(source,occurrence,result) in enumerate(zip(rows,raw['occurrences'],inference['rows'],strict=True)):
        source_hash=hashlib.sha256(source['source_text'].encode()).hexdigest();vector=source['latent'] if vectors is None else vectors[index]
        require(occurrence['id']==source['id'] and occurrence['source_sha256']==result['source_sha256']==source_hash
            and result['latent_sha256']==digest(vector) and result['latent_input_enabled'] is False,'Source/ID/dormant latent join differs')
        require(result['teacher_forcing'] is False and result['target_access'] is False and result['training_executed'] is False
            and result['source_input_conditioned'] is True and result['sample_memory_used'] is False
            and all(result.get(k) is v for k,v in FALSE.items()),'Saved raw row authority differs')
        joint['_validated'](source['source_text'],occurrence['scores'])
        greedy['_verify_greedy'](source['source_text'],occurrence['scores'],result)
    require(inference['decoded_count']==sum(r['status']=='decoded' for r in inference['rows']),'Saved decoded count differs')
    return inference['rows']


def panel_analysis(state,name,descriptor,rows,metadata,model,greedy,joint,scorer,saved,result_root):
    require(set(descriptor)=={'name','row_count','raw','joint','score','has_authored_reference'}
        and descriptor['name']==name and descriptor['row_count']==COUNTS[name],'Exact panel descriptor/count required')
    raw_path=Path(descriptor['raw']['path']);joint_path=Path(descriptor['joint']['path'])
    prefix='baseline' if state=='baseline' else 'trained'
    require(raw_path==result_root/(prefix+'-'+name+'-raw.json') and joint_path==result_root/(prefix+'-'+name+'-joint.json'), 'Exact panel state/attempt paths required')
    require(pair(checked_pin(descriptor['raw']))==saved[str(raw_path)] and pair(checked_pin(descriptor['joint']))==saved[str(joint_path)],'Panel is outside frozen results')
    raw=read(raw_path);selected=read(joint_path);raw_rows=validate_capture(raw,rows,model,greedy,joint)
    require(selected['schema']=='targeted-loss-joint-panel/v1' and selected['top_k']==8 and selected['max_search_nodes']==50000
        and selected['learned_presence_and_modality_fixed'] is True and len(selected['rows'])==len(rows)
        and all(selected.get(k) is v for k,v in FALSE.items()),'Saved joint policy differs')
    for source,occurrence,jrow in zip(rows,raw['occurrences'],selected['rows'],strict=True):
        require(jrow['id']==source['id'] and joint['select_joint_spans'](source['source_text'],occurrence['scores'],top_k=8,max_search_nodes=50000)==jrow['result'],'Complete saved-logit joint replay differs')
    if name=='law':
        require(descriptor['score'] is None and not descriptor['has_authored_reference'] and metadata is None,'Unreviewed law must remain unscored')
        return dict(state=state,panel=name,rows=8,raw_decoded=sum(r['status']=='decoded' for r in raw_rows),joint_selected=sum(r['result']['status']=='selected' for r in selected['rows']),
            raw_exact=None,joint_exact=None,reference_authority='previously_exposed_unreviewed_law_without_targets',semantic_accuracy=None),{}
    recomputed=scorer['score_panel'](rows,metadata,raw,selected['rows'])
    if name=='authored_eval':require(descriptor['score'] is None and not descriptor['has_authored_reference'],'Deferred evaluation must have no numerical-child score')
    else:
        require(descriptor['score'] is not None and descriptor['has_authored_reference'],'Exposed/development score required')
        sp=checked_pin(descriptor['score'],result_root/(prefix+'-'+name+'-score.json'));require(pair(sp)==saved[sp['path']] and read(Path(sp['path']))==recomputed,'Saved authored score differs from pure recomputation')
    compact={row['id']:deepcopy(row) for row in recomputed['rows']};errors=[];confusion={'raw':Counter(),'joint':Counter()}
    permission_errors=[];mechanisms=[];presence_counts={f:Counter() for f in FIELDS[2:]}
    coverage=Counter();coverage_classes={};coverage_layouts={}
    for source,actual,jrow,score,occurrence,meta in zip(rows,raw_rows,selected['rows'],recomputed['rows'],raw['occurrences'],metadata,strict=True):
        reference=source['canonical_ir']['rules'][0]
        predicted_modalities={}
        for readout,candidate in (('raw',actual.get('canonical_ir')),('joint',jrow['result'].get('canonical_ir'))):
            predicted=None if candidate is None else candidate['rules'][0]['modality'];confusion[readout][reference['modality']+'->'+(predicted or 'abstained')]+=1
            predicted_modalities[readout]=predicted
        compact[score['id']]['observed_modalities']=predicted_modalities
        compact[score['id']]['reference_modality']=reference['modality']
        if reference['modality']=='P' and any(v=='O' for v in predicted_modalities.values()):
            permission_errors.append(dict(id=score['id'],class_name=score['class_name'],pair_id=score['pair_id'],
                source_sha256=occurrence['source_sha256'],reference_modality='P',raw_predicted_modality=predicted_modalities['raw'],
                joint_predicted_modality=predicted_modalities['joint']))
        for field in FIELDS[2:]:
            choice,_=joint['_choice'](occurrence['scores']['presence_logits'][field]);expected=bool(reference[field])
            presence_counts[field]['correct']+=((choice==1)==expected)
            presence_counts[field]['false_positive']+=((choice==1) and not expected)
            presence_counts[field]['false_negative']+=((choice==0) and expected)
        mechanism=candidate_mechanism(source,occurrence['scores'],score,joint)
        lexical_index=int(meta['group_id'].rsplit('-',1)[1]) if name in ('authored_dev','authored_eval','old_authored_eval') else None
        coverage_buckets=[coverage,coverage_classes.setdefault(score['class_name'],Counter())]
        if lexical_index is not None:coverage_buckets.append(coverage_layouts.setdefault(score['class_name']+'/lexical'+str(lexical_index),Counter()))
        for bucket in coverage_buckets:
            bucket['rows']+=1
            for key,value in dict(raw_gold_in_K8=mechanism['raw_actor_in_K8'],raw_gold_in_K16=mechanism['raw_actor_in_K16'],
                raw_gold_rank1=mechanism['raw_actor_rank']==1,compatible_gold_rank1=mechanism['gold_compatible_actor_rank']==1,
                compatible_gold_in_K8=mechanism['gold_compatible_actor_rank']<=8,
                incompatible_higher_scores_crowd_raw_K8=not mechanism['raw_actor_in_K8'] and mechanism['gold_compatible_actor_rank']<=8).items():bucket[key]+=value
        if (not score['role_exact']['actor'] or not score['joint_role_exact']['actor']
                or score['class_name']=='condition_exception_duration' and (not score['raw_exact_ir'] or not score['joint_exact_ir'])):
            mechanisms.append({**mechanism,
                'class_name':score['class_name'],'group_id':meta['group_id'],'pair_id':score['pair_id'],
                'pair_variant':meta['pair_variant'],'declared_lexical_index':lexical_index,
                'joint_selected':jrow['result']['status']=='selected','joint_reason':jrow['result'].get('reason'),
                'raw_exact_IR':score['raw_exact_ir'],'joint_exact_IR':score['joint_exact_ir']})
        if not score['raw_exact_ir'] or not score['joint_exact_ir']:
            errors.append(dict(id=score['id'],class_name=score['class_name'],pair_id=score['pair_id'],pair_variant=score['pair_variant'],
                raw_exact=score['raw_exact_ir'],joint_exact=score['joint_exact_ir'],raw_reason=actual.get('reason'),joint_reason=jrow['result'].get('reason'),
                raw_mismatched_roles=[f for f in FIELDS if not score['role_exact'][f]],joint_mismatched_roles=[f for f in FIELDS if not score['joint_role_exact'][f]],
                raw_modality_exact=score['modality_exact'],joint_modality_exact=score['joint_modality_exact'],temporal_false_positive=score['temporal_false_positive'],temporal_false_negative=score['temporal_false_negative']))
    pairs=recomputed['pairwise_consistency']
    result=dict(state=state,panel=name,rows=len(rows),raw_exact=recomputed['raw_exact_ir'],joint_exact=recomputed['joint_exact_ir'],
        raw_exact_rate=recomputed['raw_exact_ir']/len(rows),joint_exact_rate=recomputed['joint_exact_ir']/len(rows),
        raw_abstentions=recomputed['raw_abstentions'],joint_abstentions=sum(r['result']['status']!='selected' for r in selected['rows']),
        temporal_presence_correct=recomputed['temporal_presence_correct'],temporal_false_positives=recomputed['temporal_false_positives'],temporal_false_negatives=recomputed['temporal_false_negatives'],
        modality_exact=recomputed['modality_exact'],joint_modality_exact=recomputed['joint_modality_exact'],modality_confusions={k:dict(v) for k,v in confusion.items()},
        permission_to_obligation_raw=confusion['raw'].get('P->O',0),permission_to_obligation_joint=confusion['joint'].get('P->O',0),
        permission_to_obligation_rows=permission_errors,optional_presence_counts={f:dict(c) for f,c in presence_counts.items()},
        optional_presence_counts_scope='Saved binary head argmax; ambiguous/abstained IR is reported separately',
        actor_candidate_coverage_counts=dict(coverage),actor_candidate_coverage_by_class={k:dict(v) for k,v in coverage_classes.items()},
        actor_candidate_coverage_by_lexical_layout={k:dict(v) for k,v in coverage_layouts.items()},
        actor_and_combined_scope_failure_mechanisms=mechanisms,
        role_exact_counts=recomputed['role_exact_counts'],joint_role_exact_counts=recomputed['joint_role_exact_counts'],classes=recomputed['classes'],
        pair_count=len(pairs),pair_both_raw_exact=sum(p['raw_both_exact'] for p in pairs),pair_both_joint_exact=sum(p['joint_both_exact'] for p in pairs),
        pair_both_temporal_correct=sum(p['temporal_both_correct'] for p in pairs),pair_failures=[p for p in pairs if not p['all_raw_exact'] or not p['all_temporal_correct'] or not p['joint_both_exact']],
        errors=errors,reference_authority='deferred_author_visible_shared_template_engineering_evaluation' if name=='authored_eval' else 'authored_exposed_training_development_diagnostic',semantic_accuracy=None,
        pure_recomputed_score_sha256=digest(recomputed))
    return result,compact


def factorial(values,denominator):
    require(set(values)==set(CELLS) and all(type(v) in (int,float) and math.isfinite(v) for v in values.values()),'Complete finite four-cell values required')
    require(type(denominator) is int and denominator>0,'Positive matched denominator required')
    grid={(int(c['actor_ranking_enabled']),c['presence_ce_weight']-1):values[k] for k,c in CELLS.items()}
    main=dict(actor_ranking_ON_minus_OFF=(grid[1,0]+grid[1,1]-grid[0,0]-grid[0,1])/2,
        presence_weight2_minus1=(grid[0,1]+grid[1,1]-grid[0,0]-grid[1,0])/2)
    interaction=grid[1,1]-grid[1,0]-grid[0,1]+grid[0,0]
    require(all(math.isfinite(v) for v in main.values()) and math.isfinite(interaction),'Finite2x2 effects required')
    return dict(main_high_minus_low_counts=main,actor_by_presence_difference_of_differences_counts=interaction,
        orthogonal_coded_effect_counts={**main,'actor_by_presence':interaction/2},
        main_effect_percentage_points={k:v/denominator*100 for k,v in main.items()},normalization_denominator=denominator,
        statistical_significance_claimed=False,scope='Descriptive matched2x2 objective contrasts on one authored seed; no legal-semantic or causal qualification')


def main(args):
    global PACKET_ALLOWED,OUTPUT
    helper_opening_pin=pin(Path(__file__).resolve())
    OUTPUT=Path(args.output).absolute();require(OUTPUT==M/'targeted-result-analysis-v01.json' and OUTPUT.parent==M and OUTPUT.resolve()==OUTPUT and not OUTPUT.exists(),'Fresh root-local analysis output required')
    manifest_path=Path(args.freeze_manifest).absolute();require(manifest_path==M/'four-cell-output-freeze-v01.json','Exact new four-cell freeze path required');manifest_pin=pin(manifest_path);require(type(args.freeze_manifest_sha256) is str and re.fullmatch(r'[0-9a-f]{64}',args.freeze_manifest_sha256) and manifest_pin['sha256']==args.freeze_manifest_sha256,'Explicit freeze raw SHA256 required');manifest=read(manifest_path)
    require(manifest['schema']=='targeted-loss-four-cell-freeze/v1' and manifest['all_four_outputs_frozen'] is True
        and manifest['authorizes_authored_eval_scoring'] is True and manifest['evaluation_packet_scored_before_freeze'] is False,
        'Explicit four-cell freeze/scoring authority required')
    freeze_role_pins={}
    for role,path in (('runner',RUNNER),('registration',REGISTRATION),('training_export',EXPORT)):
        actual=checked_pin(manifest[role],path);require(path not in FIXED_PINS or pair(actual)==FIXED_PINS[path],'Reviewed fixed producer identity differs')
        freeze_role_pins[str(path)]=pair(actual)
    registration=read(REGISTRATION);data=read(EXPORT)
    require(registration['schema']=='targeted-loss-curriculum-registration/v1' and registration['data_export']==manifest['training_export']
        and registration['semantic_gold'] is False and registration['reference_packet_child_access'] is False,'Exact child-safe registration scope differs')
    require(manifest['reference_packet']==registration['reference_packet'] and manifest['reference_packet']['path']==str(PACKET), 'Exact deferred packet registration required')
    require(type(manifest['cells']) is list and len(manifest['cells'])==4 and {e['cell']['id'] for e in manifest['cells']}==set(CELLS), 'Exactly four distinct factorial cells required')
    saved={};cell_data={};all_source_pins={};baseline_entry=None;first_id='rank0-presence1';seen_attempts=set()
    validate_geometry=geometry_validator()
    for entry in manifest['cells']:
        cell=entry['cell'];require(canonical(cell)==canonical(CELLS[cell['id']]),'Cell factors differ')
        plan_path=M/(cell['id']+'-plan-v01.json');checked_pin(entry['plan'],plan_path);plan=read(plan_path)
        require(plan['cell']==cell and plan['source_owner_pins']==registration['source_owner_pins'] and plan['data_export']==manifest['training_export']
            and plan['context_contract']==registration['context_contract'] and plan['seed']==plan['batch_order_seed']==1729
            and plan['dimension']==384 and plan['latent_enabled'] is False
            and plan['schema']=='targeted-loss-curriculum-cell-plan/v1'
            and type(plan['training_seconds']) in (int,float) and plan['training_seconds']==32,'Exact common source/data/context/dormant384 recipe differs')
        require(plan['parent_base_canonical_sha256']=='fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279'
            and plan['parent_model_state_sha256']=='54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb'
            and plan['historical_parent_file_pin']['sha256']=='5df537d8c7141578c1355af43317b9c5a327305295a11760aee2897244bc5dbb','Original common parent identity differs')
        require(type(plan['attempt_name']) is str and Path(plan['attempt_name']).name==plan['attempt_name']
            and plan['attempt_name'] not in seen_attempts,'Distinct canonical one-cell attempt names required');seen_attempts.add(plan['attempt_name'])
        result_root=RUN_ROOT/plan['attempt_name']/'results';checked_pin(entry['summary'],result_root/'summary.json')
        require(ordinary_inventory(result_root)==entry['results'],'Complete frozen result bundle drift')
        require(set(entry['results'])==expected_result_paths(result_root,cell['id']==first_id),'Exact saved one-cell output paths differ')
        for path,v in entry['results'].items():require(set(v)=={'bytes','sha256'},'Closed frozen result value required');saved[path]=v
        terminal_path=result_root.parent/'guardian-exit.json';pre_path=result_root.parent/'pre-admission.json'
        checked_pin(entry['guardian_terminal'],terminal_path);checked_pin(entry['pre_admission'],pre_path)
        for key in ('plan','summary','guardian_terminal','pre_admission'):
            current=entry[key];require(current['path'] not in freeze_role_pins,'Repeated frozen operational role refused');freeze_role_pins[current['path']]=pair(current)
        terminal,pre=read(terminal_path),read(pre_path)
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int and terminal['returncode']==terminal['child_returncode']==0
            and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,'Successful durable released terminal required')
        require(pre['plan']==entry['plan'] and pre['runner']==manifest['runner'],'Actual admitted plan/runner differs')
        summary=read(result_root/'summary.json');require(summary['schema']=='targeted-loss-curriculum-cell-results/v1' and summary['status']=='completed'
            and summary['cell']==cell and summary['attempt_name']==plan['attempt_name'] and summary['actual_new_updates']==32
            and summary['actual_encoder_calls']==0 and summary['fresh_Adam'] is True and summary['inherited_optimizer_moments'] is False
            and summary['parent_optimizer_steps']==400 and summary['configured_dimension']==384 and summary['latent_enabled'] is False
            and summary['same_original_parent_model_sha256']==plan['parent_model_state_sha256'] and summary['training_count']==168,'Complete common-parent freshAdam source-only result required')
        require(summary['promotion_gate']==plan['promotion_gate']==dict(schema='legacy-exact-permission-preservation-gate/v1',
            applies_to='raw_and_joint_IR',automatic_selection=False,new_permission_to_obligation_allowed=0,
            old_count=96,required_old_exact=96),'Exact external legacy96 promotion gate differs')
        require(summary['semantic_accuracy'] is None and summary['independent_statutory_gold'] is False and summary['default_promotion'] is False
            and summary['checkpoint_selection_executed'] is False and summary['Lake_executed'] is False
            and summary['original_artifacts_byte_exact'] is True and all(summary.get(k) is v for k,v in FALSE.items()),'Unqualified authored scope required')
        checkpoint=checked_pin(summary['checkpoint'],result_root/'cell-checkpoint.json');training=checked_pin(summary['training'],result_root/'cell-training.json')
        require(pair(checkpoint)==entry['results'][checkpoint['path']] and pair(training)==entry['results'][training['path']],'Opaque checkpoint/report outside freeze')
        require(registration['source_owner_pins']['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_targeted_loss']=={**TARGETED_PIN,'path':str(TARGETED)},'Exact new policy owner pin differs')
        report=read(Path(training['path']));rows=validate_geometry(plan,data)
        contract=validate_training(summary,report,plan,rows,checkpoint)
        schedule_before=read(result_root/'data-schedule-before-models.json');require(schedule_before['schedule']==summary['prepared_schedule']
            and schedule_before['training_count']==168 and schedule_before['model_imported'] is False
            and all(schedule_before.get(k) is v for k,v in FALSE.items()),'Saved pre-model matched schedule differs')
        require(summary['baseline_optimizer_steps']==0 and summary['baseline_model_state_sha256']==plan['parent_model_state_sha256'],'Zero-update baseline weight provenance differs')
        require(summary['opening_owners']==summary['closing_owners']
            and all(v==registration['source_owner_pins'][k] for k,v in summary['opening_owners'].items())
            and all('ipfs_datasets_py.optimizers.logic_theorem_optimizer.'+name in summary['opening_owners']
                for name in ('legal_span_formula','legal_span_continuation','legal_span_targeted_loss')),
            'Saved loaded producer subset/required trainers differ from complete declared closure')
        for path,expected in plan['artifacts'].items():
            require(Path(path)!=PACKET,'Packet must not enter a numerical plan closure')
            if path in all_source_pins:require(all_source_pins[path]==expected,'Conflicting source closures')
            else:require(pair(pin(path))==expected,'Frozen source/diagnostic dependency drift');all_source_pins[path]=expected
        cell_data[cell['id']]=dict(entry=entry,plan=plan,summary=summary,report=report,contract=contract,result_root=result_root)
        if cell['id']==first_id:baseline_entry=cell_data[cell['id']]
    require(baseline_entry is not None and len(saved)==151,'Required baseline and exact151-file closed output matrix missing')
    require(manifest['independent_blinding'] is False and manifest['reference_builder_author_visible'] is True,'Authored reference visibility scope differs')
    first_summary=baseline_entry['summary'];first_pin=baseline_entry['entry']['summary']
    for cid,info in cell_data.items():
        require(info['summary']['baseline_panels']==first_summary['baseline_panels'],'Same exact first-cell baseline descriptors required')
        require(info['summary']['baseline_reuse']==(None if cid==first_id else first_pin)
            and info['plan']['baseline_results']==(None if cid==first_id else first_pin),'Baseline reuse provenance differs')
        require(info['summary']['prepared_schedule']==first_summary['prepared_schedule'],'All cells must have identical slot indices and IDs')
        require(info['summary']['initial_continuation_checkpoint_sha256']==first_summary['initial_continuation_checkpoint_sha256'],'All four initial warm child hashes must match')
        require(info['summary']['opening_owners']==first_summary['opening_owners'],'All cells must report the same loaded producer subset')
        require(info['plan']['baseline_plan']==(None if cid==first_id else baseline_entry['entry']['plan']),'Exact first-cell baseline plan join differs')
    # Recheck every opening result/source/operational binding immediately before
    # reference access; the later closing fences cover the complete scoring span.
    for path,expected in {**saved,**all_source_pins,**freeze_role_pins}.items():require(pair(pin(path))==expected,'Pre-reference opening artifact drift')
    require(pin(manifest_path)==manifest_pin,'Pre-reference freeze manifest drift')
    # This is the sole transition that permits reference-packet reads. It comes
    # after all four complete raw inventories, terminals, policy/trace chains
    # and common immutable source fences have passed.
    require(args.score_authored_eval is True,'Explicit --score-authored-eval required; no packet opened')
    PACKET_ALLOWED=True
    packet_pin=checked_pin(manifest['reference_packet'],PACKET);packet=read(PACKET)
    require(packet['geometry_review_packet']['schema']=='targeted-loss-author-declaration-packet/v1'
        and packet['geometry_review_packet']['semantic_gold'] is False and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
        and packet['split_contract']['shared_authored_templates'] is True and packet['split_contract']['statutory_provision_holdout'] is False
        and all(value is False for value in packet['authority'].values()),
        'Authored shared-template reference authority differs')
    geometry=packet['geometry_review_packet']['authored_eval'];require(type(geometry) is list and len(geometry)==72,'Full deferred72 authored rows required')
    eval_rows=[r['model_example'] for r in geometry]
    eval_metadata=[{k:r[k] for k in ('id','class_name','group_id','pair_id','pair_variant')} for r in geometry]
    require([{k:r[k] for k in ('id','source_text','latent')} for r in eval_rows]==data['diagnostic_populations']['authored_eval'], 'Deferred source/reference join differs')
    require('authored_eval' not in packet['diagnostic_metadata'],'Deferred evaluation metadata must live only in geometry packet')
    require(packet['training_populations']==data['training_populations'] and packet['training_metadata']==data['training_metadata'],'Reference-packet training declaration differs')
    require(packet['diagnostic_populations']==data['diagnostic_populations'] and {k:packet['diagnostic_metadata'][k] for k in data['diagnostic_metadata']}==data['diagnostic_metadata'],'Reference-packet diagnostic declaration differs')
    greedy,joint,scorer=scorers(registration['source_owner_pins']);table=[];row_maps={};raw_saved=saved
    model_baseline=dict(continuation_sha256=first_summary['initial_continuation_checkpoint_sha256'],parent_base_sha256=baseline_entry['plan']['parent_base_canonical_sha256'],context_sha256=digest(registration['context_contract']))
    states=[('baseline',first_summary['baseline_panels'],model_baseline,baseline_entry['result_root'])]
    for cid in sorted(cell_data):
        info=cell_data[cid];report=info['report'];states.append((cid,info['summary']['diagnostics'],dict(continuation_sha256=report['continuation_checkpoint_sha256'],base_sha256=report['base_checkpoint_sha256'],parent_base_sha256=info['plan']['parent_base_canonical_sha256'],context_sha256=digest(registration['context_contract'])),info['result_root']))
    for state,descriptors,model,result_root in states:
        require([p['name'] for p in descriptors]==list(PANELS),'Exact seven diagnostic panels required')
        for name,descriptor in zip(PANELS,descriptors,strict=True):
            rows=eval_rows if name=='authored_eval' else data['diagnostic_populations'][name]
            metadata=eval_metadata if name=='authored_eval' else data['diagnostic_metadata'].get(name)
            result,compact=panel_analysis(state,name,descriptor,rows,metadata,model,greedy,joint,scorer,raw_saved,result_root)
            table.append(result);row_maps[state,name]=compact
    parity_observations=0
    for cid,info in cell_data.items():
        for stage,key,model in [('initial','initial_parity',dict(continuation_sha256=info['summary']['initial_continuation_checkpoint_sha256'],parent_base_sha256=info['plan']['parent_base_canonical_sha256'],context_sha256=digest(registration['context_contract']))),('trained','trained_parity',next(m for s,_,m,_ in states if s==cid))]:
            pp=checked_pin(info['summary'][key],info['result_root']/(stage+'-parity.json'));require(pair(pp)==raw_saved[pp['path']],'Parity outside freeze')
            parity=read(Path(pp['path']));require(parity['schema']=='source-only-dormant384-placeholder-parity/v1'
                and parity['passed'] is True and parity['source_count']==2 and parity['score_and_greedy_decisions_bit_equal'] is True
                and parity['genuine_latent_semantics_tested'] is False and parity['actual_encoder_calls']==0
                and all(parity.get(k) is v for k,v in FALSE.items()),'Dormant placeholder parity scope differs')
            require([c['name'] for c in parity['controls']]==['zeros','alternate_placeholders','disabled','rotated_placeholders'],'All placeholder controls required')
            projection=None;rows=data['diagnostic_populations']['fresh_tune'][:2]
            for ctl in parity['controls']:
                require(ctl['control']=={'zeros':'none','alternate_placeholders':'none','disabled':'disabled','rotated_placeholders':'rotate'}[ctl['name']], 'Exact saved dormant control mapping required')
                cp=checked_pin(ctl['report'],info['result_root']/(stage+'-parity-'+ctl['name']+'.json'));require(pair(cp)==raw_saved[cp['path']],'Parity capture outside freeze');raw=read(Path(cp['path']))
                vectors=None if ctl['name']=='zeros' else [[.25 if i==0 else -.25]*384 for i in range(2)]
                if ctl['name']=='rotated_placeholders':vectors=vectors[::-1]
                actual=validate_capture(raw,rows,model,greedy,joint,control=ctl['control'],vectors=vectors)
                current=[dict(scores=c['scores'],raw={k:r.get(k) for k in ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')}) for c,r in zip(raw['occurrences'],actual,strict=True)]
                require(projection is None or current==projection,'Saved placeholder projections differ');projection=current;parity_observations+=2
    comparisons=[];effects={};class_effects={};facet_effects={};pair_effects={};presence_effects={}
    for name in PANELS[:-1]:
        baseline=row_maps['baseline',name]
        for cid in sorted(cell_data):
            current=row_maps[cid,name];require(set(current)==set(baseline),'Same evaluation occurrence IDs required')
            comparisons.append(dict(cell=cid,panel=name,
                raw_regressions=[i for i,r in current.items() if baseline[i]['raw_exact_ir'] and not r['raw_exact_ir']],
                raw_recoveries=[i for i,r in current.items() if not baseline[i]['raw_exact_ir'] and r['raw_exact_ir']],
                joint_regressions=[i for i,r in current.items() if baseline[i]['joint_exact_ir'] and not r['joint_exact_ir']],
                joint_recoveries=[i for i,r in current.items() if not baseline[i]['joint_exact_ir'] and r['joint_exact_ir']],
                all_changed_permission_to_obligation_rows=[dict(id=i,readout=readout,
                    baseline_modality=baseline[i]['observed_modalities'][readout],cell_modality=r['observed_modalities'][readout],
                    direction='new_P_to_O' if r['observed_modalities'][readout]=='O' else 'recovered_P_to_O')
                    for i,r in current.items() for readout in ('raw','joint')
                    if r['reference_modality']=='P' and baseline[i]['observed_modalities'][readout]!=r['observed_modalities'][readout]
                    and 'O' in (baseline[i]['observed_modalities'][readout],r['observed_modalities'][readout])],
                known_prior_contrast_regression_recovered=[i for i in OLD_CONTRAST_REGRESSIONS if i in current and current[i]['raw_exact_ir'] and current[i]['joint_exact_ir']] if name=='old_tune' else []))
        entries={r['state']:r for r in table if r['panel']==name and r['state']!='baseline'}
        effects[name]={metric:factorial({cid:entries[cid][metric] for cid in CELLS},COUNTS[name]) for metric in
            ('raw_exact','joint_exact','raw_abstentions','joint_abstentions','temporal_presence_correct','temporal_false_positives','temporal_false_negatives',
             'permission_to_obligation_raw','permission_to_obligation_joint')}
        pair_count=entries[first_id]['pair_count'];require(all(e['pair_count']==pair_count for e in entries.values()),'Matched factorial pair count differs')
        pair_effects[name]={metric:factorial({cid:entries[cid][metric] for cid in CELLS},pair_count) for metric in
            ('pair_both_raw_exact','pair_both_joint_exact','pair_both_temporal_correct')} if pair_count else None
        class_names=set(entries[first_id]['classes'])
        require(all(set(e['classes'])==class_names for e in entries.values()),'Same factorial class panels required')
        class_effects[name]={}
        for class_name in sorted(class_names):
            count=entries[first_id]['classes'][class_name]['rows'];require(count>0
                and all(e['classes'][class_name]['rows']==count for e in entries.values()),'Matched class count differs')
            class_effects[name][class_name]={metric:factorial({cid:entries[cid]['classes'][class_name][metric] for cid in CELLS},count)
                for metric in ('raw_exact_ir','joint_exact_ir','raw_decoded','temporal_presence_correct','temporal_false_positive','temporal_false_negative')}
        facet_effects[name]={readout:{field:factorial({cid:entries[cid][key][field] for cid in CELLS},COUNTS[name]) for field in FIELDS}
            for readout,key in (('raw','role_exact_counts'),('joint','joint_role_exact_counts'))}
        presence_effects[name]={field:{metric:factorial({cid:entries[cid]['optional_presence_counts'][field].get(metric,0) for cid in CELLS},COUNTS[name])
            for metric in ('correct','false_positive','false_negative')} for field in FIELDS[2:]}
    promotion_observations={}
    for cid in CELLS:
        old=next(r for r in table if r['state']==cid and r['panel']=='old_tune')
        promotion_observations[cid]=dict(raw_exact_IR=old['raw_exact'],joint_exact_IR=old['joint_exact'],
            permission_to_obligation_raw=old['permission_to_obligation_raw'],permission_to_obligation_joint=old['permission_to_obligation_joint'],
            exposed_legacy96_gate_met=old['raw_exact']==old['joint_exact']==96 and old['permission_to_obligation_raw']==old['permission_to_obligation_joint']==0,
            scope='Necessary external legacy96 engineering gate only; legal gold/family/Lake/latent gates remain open',
            checkpoint_selected=False,promotion_performed=False)
    for path,expected in saved.items():require(pair(pin(path))==expected,'Closing frozen output drift')
    for cid,info in cell_data.items():require(ordinary_inventory(info['result_root'])==info['entry']['results'],'Closing complete result inventory differs')
    for path,expected in all_source_pins.items():require(pair(pin(path))==expected,'Closing immutable source dependency drift')
    for path,expected in freeze_role_pins.items():require(pair(pin(path))==expected,'Closing plan/terminal/admission/fixed-artifact drift')
    require(pin(manifest_path)==manifest_pin and pin(PACKET)==packet_pin and pin(Path(__file__).resolve())==helper_opening_pin,'Closing freeze/packet/analyzer drift')
    limitations=['All references are caller-authored engineering declarations. Deferred authored_eval uses shared templates and references visible to the builder author, not independently reviewed USCode gold or a statutory holdout.',
        'Older tuning/fresh diagnostic panels, old_authored_eval and authored_dev are exposed; none can establish unbiased legal fidelity. Law8 has no reviewed target and remains unscored regardless of decoded/selected coverage.',
        'One common400-step parent,168 matched rows,32 freshAdam updates and one initialization/order seed1729. Main effects/interaction are finite descriptive factorial contrasts; no statistical significance, seed robustness or general legal causality is claimed.',
        'All four checkpoints remain retained; no automatic winner, checkpoint selection or default promotion occurs. Different weighted tuning losses are not ranked as the same objective.',
        'Checkpoints are opaque raw-hashed artifacts; no checkpoint JSON, historical parent or model state is parsed/restored. Actual updates/gradients are trainer-reported completed-prefix evidence, not an independent numerical optimizer replay.',
        'Actor hinge diagnostics are teacher-forced training scalars. The full gold-compatible ranking domain filters before argmax; inference topK8 is formed before compatibility, so incompatible high-score spans can crowd K8. Raw and gold-compatible actor ranks are separate diagnostics, not predicted legal semantics.',
        'Pure saved-head selection replay uses named frozen-source predicates with structural tokenizer/single-rule stubs. It validates saved arithmetic/IR joins rather than independently qualifying codec semantics, broader families or a compiler.',
        'Configured384 conditioning is disabled. Placeholder parity is not genuine8D/384D/768D latent evidence. No Lake build, independent reviewed legal fidelity, broader logic-family promotion or HF publication is performed.',
        'Guardian terminal flags and raw pins bind completed runs. Current lease/storage/RSS custody and source-resource closure require their separately issued runtime reviews.']
    card_changes=['Declare bounded-targeted-loss-span-legal-formula-checkpoint/v1 as the authoritative outer schema; nested legacy loss/initialization fields are constructor descriptors, not the actual weighted training objective or copied-parent provenance.',
        'Show all4 actor-ranking OFF/ON by condition/exception presence weight1/2 cells with fixed modality weight2, exact checkpoint pins, initialization/order seed1729,168 rows,32 new updates each and freshAdam; publish raw/joint tables with older regressions, class/pair failures and no default winner.',
        'Label authored_dev/exposed panels and deferred shared-template authored_eval separately; state author-visible references, law8 unscored, no independent USCode gold and no significance claim.',
        'Describe source-only384 disabled conditioning, opaque original parent identity, actual main objective normalization8/10 and separate .25 actor hinge and trace provenance. Explicitly leave genuine latents, broader families and lake build legal unqualified.',
        'Keep all4 archived candidates experimental. Link the frozen source/data/protocol/runtime/scientific receipts; adapt loaders to the new outer policy instead of silently interpreting its nested payload as a vanilla warm-start training state.']
    result=dict(schema='targeted-loss-four-cell-saved-result-analysis/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        helper=helper_opening_pin,freeze_manifest=manifest_pin,reference_packet=packet_pin,registration=manifest['registration'],training_export=manifest['training_export'],runner=manifest['runner'],
        saved_output_pins=saved,immutable_source_pins=all_source_pins,operational_freeze_role_pins=freeze_role_pins,
        cell_contracts={cid:i['contract'] for cid,i in cell_data.items()},
        baseline_and_four_cell_panels=table,regressions_and_recoveries_relative_to_common_baseline=comparisons,factorial_effects=effects,
        factorial_class_effects=class_effects,factorial_facet_effects=facet_effects,factorial_pair_effects=pair_effects,
        factorial_presence_head_effects=presence_effects,external_legacy96_gate_observations=promotion_observations,
        checkpoint_inventory={cid:i['summary']['checkpoint'] for cid,i in cell_data.items()},all_four_candidates_retained=True,selected_candidate_id=None,
        checkpoint_selection_performed=False,default_promotion=False,recorded_new_updates_total=128,parity_source_observations=parity_observations,
        scored_source_rows=sum(r['rows'] for r in table if r['panel']!='law'),unscored_law_source_rows=40,
        source_only_dimension=384,latent_enabled=False,actual_encoder_calls_recorded=0,semantic_accuracy=None,statistical_significance_claimed=False,
        recommended_model_card_changes=card_changes,limitations=limitations,
        analyzer_actions=dict(numerical_imports=0,model_restores=0,model_forwards=0,checkpoint_JSON_parses=0,optimizer_updates=0,
            resource_API_leases_locks=0,network_external_compiler_Git_HF_mutations=0,evaluation_packet_opened_only_after_all4_freeze_fences=True))
    with OUTPUT.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps(dict(passed=True,output=pin(OUTPUT),cells=4,recorded_updates=128,selected_candidate=None),sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-manifest',required=True)
    parser.add_argument('--freeze-manifest-sha256',required=True)
    parser.add_argument('--score-authored-eval',action='store_true')
    parser.add_argument('--output',required=True)
    main(parser.parse_args())
