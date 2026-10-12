"""Analyze an independently frozen eight-cell matrix without opening models.

Evaluation references are opened only after the full eight-cell hash/terminal/
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
RUNNER = M/'run_matched_curriculum.py'
HELPER = T/'run_temporal_contrast_pilot.py'
HELPER_SHA = '0ae80b9554c45ec104430b7f1a482ad834a33e5f41f5f031fdd203634374fa05'
FIXED_PINS = {
    RUNNER:dict(bytes=34990,sha256='a08e12b9aba758df9fc363185bf77675f284c740bb10f3e1ca95a3dea1855373'),
    REGISTRATION:dict(bytes=49475,sha256='73ec44610213d23ab27faa215565d6c10fe501fbf6212949f3e976ae0e29725e'),
    EXPORT:dict(bytes=9840705,sha256='dbf2cc7af675c3d5987c73c76eb3435fc4694d00bf669d3ca9955035e0019571'),
}
FIELDS = ('actor','action','object','conditions','exceptions','temporal')
PANELS = ('old_tune','fresh_tune','fresh_challenge','authored_dev','authored_eval','law')
COUNTS = dict(old_tune=96,fresh_tune=36,fresh_challenge=36,authored_dev=72,authored_eval=72,law=8)
FALSE = dict(qualified=False,admitted=False,formalized=False,proof_authority=False,
             semantic_correctness_verified=False,promotion_performed=False)
CELLS = {f'actor{a}-scope{s}-modality{w-1}':dict(id=f'actor{a}-scope{s}-modality{w-1}',actor_curriculum=a,scope_curriculum=s,modality_loss_weight=w)
         for a,s,w in itertools.product((0,1),(0,1),(1,2))}
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
                raise AssertionError('Eight-cell freeze and explicit scoring authorization required before packet access')
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


def expected_policy(cell):
    weight=cell['modality_loss_weight']
    return dict(schema='bounded-source-span-curriculum-policy/v1',objective='weighted_modality_equal_facet_mean_pointer/v1',
        modality_loss_weight=weight,facet_loss_weights={f:1 for f in FIELDS},normalization_denominator=weight+6,
        initialization_seed=1729,batch_order_seed=1729,batch_order_seed_origin='explicit',batch_size=12,
        max_new_optimizer_steps=32,latent_dimension=384,latent_enabled=False,
        nested_loss_metadata_scope='legacy_constructor_descriptor; this_outer_policy_defines_actual_training_objective')


def validate_training(summary,report,plan,rows,checkpoint_pin):
    require(report['schema']=='bounded-curriculum-span-legal-formula-training/v1'
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
    require(report['gradient_norm_max']==max(b['gradient_norm_before_clip'] for b in batches),'Recorded gradient-norm summary differs')
    tuning=report['tuning'];require(type(tuning['rows_evaluated']) is int and 0<=tuning['rows_evaluated']<=96
        and tuning['complete'] is (tuning['rows_evaluated']==96) and tuning['teacher_forcing'] is True
        and tuning['used_for_fit_or_selection'] is False and tuning['objective_policy_sha256']==digest(policy)
        and (tuning['objective_loss'] is None if tuning['rows_evaluated']==0 else type(tuning['objective_loss']) in (int,float)
            and math.isfinite(tuning['objective_loss']) and tuning['objective_loss']>=0),
        'Exposed tuning diagnostic or objective identity differs')
    changed=report['changed_parameter_names'];require(type(changed) is list and len(changed)==len(set(changed))
        and all(type(k) is str and not k.startswith('latent_') for k in changed),'Reported dormant latent change or parameter duplication')
    return dict(policy=policy,policy_sha256=digest(policy),recorded_completed_updates=32,trace_sha256=digest(trace),
        trace_indices_sha256=trace['indices_sha256'],trace_IDs_sha256=trace['ids_sha256'],final_progress=progress,
        checkpoint_opaque_raw_pin=checkpoint_pin,checkpoint_JSON_parsed=False,
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
        DATA_SCHEMA='matched-temporal-curriculum-export/v1',
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
    require(selected['schema']=='matched-curriculum-joint-panel/v1' and selected['top_k']==8 and selected['max_search_nodes']==50000
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
    compact={row['id']:row for row in recomputed['rows']};errors=[];confusion={'raw':Counter(),'joint':Counter()}
    for source,actual,jrow,score in zip(rows,raw_rows,selected['rows'],recomputed['rows'],strict=True):
        reference=source['canonical_ir']['rules'][0]
        for readout,candidate in (('raw',actual.get('canonical_ir')),('joint',jrow['result'].get('canonical_ir'))):
            predicted=None if candidate is None else candidate['rules'][0]['modality'];confusion[readout][reference['modality']+'->'+(predicted or 'abstained')]+=1
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
        role_exact_counts=recomputed['role_exact_counts'],joint_role_exact_counts=recomputed['joint_role_exact_counts'],classes=recomputed['classes'],
        pair_count=len(pairs),pair_both_raw_exact=sum(p['raw_both_exact'] for p in pairs),pair_both_joint_exact=sum(p['joint_both_exact'] for p in pairs),
        pair_both_temporal_correct=sum(p['temporal_both_correct'] for p in pairs),pair_failures=[p for p in pairs if not p['all_raw_exact'] or not p['all_temporal_correct'] or not p['joint_both_exact']],
        errors=errors,reference_authority='deferred_author_visible_shared_template_engineering_evaluation' if name=='authored_eval' else 'authored_exposed_training_development_diagnostic',semantic_accuracy=None,
        pure_recomputed_score_sha256=digest(recomputed))
    return result,compact


def factorial(values,denominator):
    require(set(values)==set(CELLS) and all(type(v) in (int,float) and math.isfinite(v) for v in values.values()),'Complete finite eight-cell values required')
    require(type(denominator) is int and denominator>0,'Positive matched normalization denominator required')
    lookup={(v['actor_curriculum'],v['scope_curriculum'],v['modality_loss_weight']-1):values[k] for k,v in CELLS.items()}
    main={};interactions={}
    names=('actor_curriculum','scope_curriculum','modality_weight2_vs1')
    for factor,name in enumerate(names):
        high=[v for levels,v in lookup.items() if levels[factor]==1];low=[v for levels,v in lookup.items() if levels[factor]==0]
        main[name]=math.fsum(high)/4-math.fsum(low)/4
    for left,right in itertools.combinations(range(3),2):
        remaining=next(i for i in range(3) if i not in (left,right));diffs=[]
        for level in (0,1):
            v={}
            for a,b in itertools.product((0,1),repeat=2):
                key=[0,0,0];key[left]=a;key[right]=b;key[remaining]=level;v[a,b]=lookup[tuple(key)]
            diffs.append(v[1,1]-v[1,0]-v[0,1]+v[0,0])
        interactions[names[left]+'__'+names[right]]=math.fsum(diffs)/2
    triple=math.fsum(value*math.prod(1 if v==1 else -1 for v in levels) for levels,value in lookup.items())
    outputs=dict(main_high_minus_low_counts=main,two_way_mean_difference_of_differences_counts=interactions,three_way_difference_of_differences_counts=triple,
        orthogonal_coded_effect_counts={**main,**{k:v/2 for k,v in interactions.items()},'actor__scope__modality':triple/4},
        main_effect_percentage_points={k:v/denominator*100 for k,v in main.items()},statistical_significance_claimed=False,
        normalization_denominator=denominator,
        scope='Descriptive matched2x2x2 single-initialization/order-seed contrasts; not independent legal-semantic evidence')
    require(all(math.isfinite(v) for group in (main,interactions) for v in group.values()) and math.isfinite(triple),'Finite factorial contrasts required')
    return outputs


def main(args):
    global PACKET_ALLOWED,OUTPUT
    helper_opening_pin=pin(Path(__file__).resolve())
    OUTPUT=Path(args.output).absolute();require(OUTPUT.parent==M and OUTPUT.resolve()==OUTPUT and not OUTPUT.exists(),'Fresh root-local analysis output required')
    manifest_path=Path(args.freeze_manifest).absolute();manifest_pin=pin(manifest_path);manifest=read(manifest_path)
    require(manifest['schema']=='matched-curriculum-eight-cell-freeze/v1' and manifest['all_eight_outputs_frozen'] is True
        and manifest['authorizes_authored_eval_scoring'] is True and manifest['evaluation_packet_scored_before_freeze'] is False,
        'Explicit eight-cell freeze/scoring authority required')
    freeze_role_pins={}
    for role,path in (('runner',RUNNER),('registration',REGISTRATION),('training_export',EXPORT)):
        actual=checked_pin(manifest[role],path);require(pair(actual)==FIXED_PINS[path],'Reviewed fixed producer/data identity differs')
        freeze_role_pins[str(path)]=pair(actual)
    registration=read(REGISTRATION);data=read(EXPORT)
    require(registration['schema']=='matched-temporal-curriculum-registration/v1' and registration['data_export']==manifest['training_export']
        and registration['semantic_gold'] is False and registration['reference_packet_child_access'] is False,'Exact child-safe registration scope differs')
    require(manifest['reference_packet']==registration['reference_packet'] and manifest['reference_packet']['path']==str(PACKET), 'Exact deferred packet registration required')
    require(type(manifest['cells']) is list and len(manifest['cells'])==8 and {e['cell']['id'] for e in manifest['cells']}==set(CELLS), 'Exactly eight distinct factorial cells required')
    saved={};cell_data={};all_source_pins={};baseline_entry=None;first_id='actor0-scope0-modality0';seen_attempts=set()
    validate_geometry=geometry_validator()
    for entry in manifest['cells']:
        cell=entry['cell'];require(cell==CELLS[cell['id']],'Cell factors differ')
        plan_path=M/(cell['id']+'-plan-v01.json');checked_pin(entry['plan'],plan_path);plan=read(plan_path)
        require(plan['cell']==cell and plan['source_owner_pins']==registration['source_owner_pins'] and plan['data_export']==manifest['training_export']
            and plan['context_contract']==registration['context_contract'] and plan['seed']==plan['batch_order_seed']==1729
            and plan['dimension']==384 and plan['latent_enabled'] is False,'Exact common source/data/context/dormant384 recipe differs')
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
        summary=read(result_root/'summary.json');require(summary['schema']=='matched-temporal-curriculum-cell-results/v1' and summary['status']=='completed'
            and summary['cell']==cell and summary['attempt_name']==plan['attempt_name'] and summary['actual_new_updates']==32
            and summary['actual_encoder_calls']==0 and summary['fresh_Adam'] is True and summary['inherited_optimizer_moments'] is False
            and summary['parent_optimizer_steps']==400 and summary['configured_dimension']==384 and summary['latent_enabled'] is False
            and summary['same_original_parent_model_sha256']==plan['parent_model_state_sha256'] and summary['training_count']==168,'Complete common-parent freshAdam source-only result required')
        require(summary['semantic_accuracy'] is None and summary['independent_statutory_gold'] is False and summary['default_promotion'] is False
            and summary['checkpoint_selection_executed'] is False and summary['Lake_executed'] is False
            and summary['original_artifacts_byte_exact'] is True and all(summary.get(k) is v for k,v in FALSE.items()),'Unqualified authored scope required')
        checkpoint=checked_pin(summary['checkpoint'],result_root/'cell-checkpoint.json');training=checked_pin(summary['training'],result_root/'cell-training.json')
        require(pair(checkpoint)==entry['results'][checkpoint['path']] and pair(training)==entry['results'][training['path']],'Opaque checkpoint/report outside freeze')
        report=read(Path(training['path']));rows=validate_geometry(plan,data)
        contract=validate_training(summary,report,plan,rows,checkpoint)
        schedule_before=read(result_root/'data-schedule-before-models.json');require(schedule_before['schedule']==summary['prepared_schedule']
            and schedule_before['training_count']==168 and schedule_before['model_imported'] is False
            and all(schedule_before.get(k) is v for k,v in FALSE.items()),'Saved pre-model matched schedule differs')
        require(summary['baseline_optimizer_steps']==0 and summary['baseline_model_state_sha256']==plan['parent_model_state_sha256'],'Zero-update baseline weight provenance differs')
        require(summary['opening_owners']==summary['closing_owners'] and all(v==registration['source_owner_pins'][k] for k,v in summary['opening_owners'].items()),'Saved producer closure differs')
        for path,expected in plan['artifacts'].items():
            require(Path(path)!=PACKET,'Packet must not enter a numerical plan closure')
            if path in all_source_pins:require(all_source_pins[path]==expected,'Conflicting source closures')
            else:require(pair(pin(path))==expected,'Frozen source/diagnostic dependency drift');all_source_pins[path]=expected
        cell_data[cell['id']]=dict(entry=entry,plan=plan,summary=summary,report=report,contract=contract,result_root=result_root)
        if cell['id']==first_id:baseline_entry=cell_data[cell['id']]
    require(baseline_entry is not None,'Required initial baseline missing')
    first_summary=baseline_entry['summary'];first_pin=baseline_entry['entry']['summary']
    for cid,info in cell_data.items():
        require(info['summary']['baseline_panels']==first_summary['baseline_panels'],'Same exact first-cell baseline descriptors required')
        require(info['summary']['baseline_reuse']==(None if cid==first_id else first_pin)
            and info['plan']['baseline_results']==(None if cid==first_id else first_pin),'Baseline reuse provenance differs')
        require(info['summary']['prepared_schedule']==first_summary['prepared_schedule'],'All cells must have identical slot indices and IDs')
        require(info['plan']['baseline_plan']==(None if cid==first_id else baseline_entry['entry']['plan']),'Exact first-cell baseline plan join differs')
    # Recheck every opening result/source/operational binding immediately before
    # reference access; the later closing fences cover the complete scoring span.
    for path,expected in {**saved,**all_source_pins,**freeze_role_pins}.items():require(pair(pin(path))==expected,'Pre-reference opening artifact drift')
    require(pin(manifest_path)==manifest_pin,'Pre-reference freeze manifest drift')
    # This is the sole transition that permits reference-packet reads. It comes
    # after all eight complete raw inventories, terminals, policy/trace chains
    # and common immutable source fences have passed.
    require(args.score_authored_eval is True,'Explicit --score-authored-eval required; no packet opened')
    PACKET_ALLOWED=True
    packet_pin=checked_pin(manifest['reference_packet'],PACKET);packet=read(PACKET)
    require(packet['geometry_review_packet']['schema']=='matched-temporal-author-declaration-packet/v1'
        and packet['geometry_review_packet']['semantic_gold'] is False and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
        and packet['split_contract']['shared_authored_templates'] is True and packet['split_contract']['statutory_provision_holdout'] is False
        and all(value is False for value in packet['authority'].values()),
        'Authored shared-template reference authority differs')
    geometry=packet['geometry_review_packet']['authored_eval'];require(type(geometry) is list and len(geometry)==72,'Full deferred72 authored rows required')
    eval_rows=[r['model_example'] for r in geometry];eval_metadata=packet['diagnostic_metadata']['authored_eval']
    require([{k:r[k] for k in ('id','source_text','latent')} for r in eval_rows]==data['diagnostic_populations']['authored_eval'], 'Deferred source/reference join differs')
    require(eval_metadata==[{k:r[k] for k in ('id','class_name','group_id','pair_id','pair_variant')} for r in geometry], 'Deferred metadata/geometry join differs')
    require(packet['training_populations']==data['training_populations'] and packet['training_metadata']==data['training_metadata'],'Reference-packet training declaration differs')
    require(packet['diagnostic_populations']==data['diagnostic_populations'] and {k:packet['diagnostic_metadata'][k] for k in data['diagnostic_metadata']}==data['diagnostic_metadata'],'Reference-packet diagnostic declaration differs')
    greedy,joint,scorer=scorers(registration['source_owner_pins']);table=[];row_maps={};raw_saved=saved
    model_baseline=dict(continuation_sha256=first_summary['initial_continuation_checkpoint_sha256'],parent_base_sha256=baseline_entry['plan']['parent_base_canonical_sha256'],context_sha256=digest(registration['context_contract']))
    states=[('baseline',first_summary['baseline_panels'],model_baseline,baseline_entry['result_root'])]
    for cid in sorted(cell_data):
        info=cell_data[cid];report=info['report'];states.append((cid,info['summary']['diagnostics'],dict(continuation_sha256=report['continuation_checkpoint_sha256'],base_sha256=report['base_checkpoint_sha256'],parent_base_sha256=info['plan']['parent_base_canonical_sha256'],context_sha256=digest(registration['context_contract'])),info['result_root']))
    for state,descriptors,model,result_root in states:
        require([p['name'] for p in descriptors]==list(PANELS),'Exact six diagnostic panels required')
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
    comparisons=[];effects={};class_effects={};facet_effects={};pair_effects={}
    for name in PANELS[:-1]:
        baseline=row_maps['baseline',name]
        for cid in sorted(cell_data):
            current=row_maps[cid,name];require(set(current)==set(baseline),'Same evaluation occurrence IDs required')
            comparisons.append(dict(cell=cid,panel=name,
                raw_regressions=[i for i,r in current.items() if baseline[i]['raw_exact_ir'] and not r['raw_exact_ir']],
                raw_recoveries=[i for i,r in current.items() if not baseline[i]['raw_exact_ir'] and r['raw_exact_ir']],
                joint_regressions=[i for i,r in current.items() if baseline[i]['joint_exact_ir'] and not r['joint_exact_ir']],
                joint_recoveries=[i for i,r in current.items() if not baseline[i]['joint_exact_ir'] and r['joint_exact_ir']],
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
    for path,expected in saved.items():require(pair(pin(path))==expected,'Closing frozen output drift')
    for cid,info in cell_data.items():require(ordinary_inventory(info['result_root'])==info['entry']['results'],'Closing complete result inventory differs')
    for path,expected in all_source_pins.items():require(pair(pin(path))==expected,'Closing immutable source dependency drift')
    for path,expected in freeze_role_pins.items():require(pair(pin(path))==expected,'Closing plan/terminal/admission/fixed-artifact drift')
    require(pin(manifest_path)==manifest_pin and pin(PACKET)==packet_pin and pin(Path(__file__).resolve())==helper_opening_pin,'Closing freeze/packet/analyzer drift')
    limitations=['All references are caller-authored engineering declarations. Deferred authored_eval uses shared templates and references visible to the builder author, not independently reviewed USCode gold or a statutory holdout.',
        'Older tuning/fresh diagnostic panels and authored_dev are exposed; none can establish unbiased legal fidelity. Law8 has no reviewed target and remains unscored regardless of decoded/selected coverage.',
        'One common400-step parent,168 matched rows,32 freshAdam updates and one initialization/order seed1729. Main effects/interactions are finite descriptive factorial contrasts; no statistical significance, seed robustness or general legal causality is claimed.',
        'All eight checkpoints remain retained; no automatic winner, checkpoint selection or default promotion occurs. Different weighted tuning losses are not ranked as the same objective.',
        'Checkpoints are opaque raw-hashed artifacts; no checkpoint JSON, historical parent or model state is parsed/restored. Actual updates/gradients are trainer-reported completed-prefix evidence, not an independent numerical optimizer replay.',
        'Pure saved-head selection replay uses named frozen-source predicates with structural tokenizer/single-rule stubs. It validates saved arithmetic/IR joins rather than independently qualifying codec semantics, broader families or a compiler.',
        'Configured384 conditioning is disabled. Placeholder parity is not genuine8D/384D/768D latent evidence. No Lake build, independent reviewed legal fidelity, broader logic-family promotion or HF publication is performed.',
        'Guardian terminal flags and raw pins bind completed runs. Current lease/storage/RSS custody and source-resource closure require their separately issued runtime reviews.']
    card_changes=['Declare bounded-curriculum-span-legal-formula-checkpoint/v1 as the authoritative outer schema; nested legacy loss/initialization fields are constructor descriptors, not the actual weighted training objective or copied-parent provenance.',
        'Show all8 actor/scope/modality-weight cells, exact checkpoint pins, initialization/order seed1729,168 rows,32 new updates each and freshAdam; publish raw/joint tables with older regressions, class/pair failures and no default winner.',
        'Label authored_dev/exposed panels and deferred shared-template authored_eval separately; state author-visible references, law8 unscored, no independent USCode gold and no significance claim.',
        'Describe source-only384 disabled conditioning, opaque original parent identity, actual objective normalization7/8 and trace provenance. Explicitly leave genuine latents, broader families and lake build legal unqualified.',
        'Keep all8 archived candidates experimental. Link the frozen source/data/protocol/runtime/scientific receipts; adapt loaders to the new outer policy instead of silently interpreting its nested payload as a vanilla warm-start training state.']
    result=dict(schema='matched-curriculum-eight-cell-saved-result-analysis/v1',passed=True,findings=[],observed_at_utc=datetime.now(timezone.utc).isoformat(),
        helper=helper_opening_pin,freeze_manifest=manifest_pin,reference_packet=packet_pin,registration=manifest['registration'],training_export=manifest['training_export'],runner=manifest['runner'],
        saved_output_pins=saved,immutable_source_pins=all_source_pins,operational_freeze_role_pins=freeze_role_pins,
        cell_contracts={cid:i['contract'] for cid,i in cell_data.items()},
        baseline_and_eight_cell_panels=table,regressions_and_recoveries_relative_to_common_baseline=comparisons,factorial_effects=effects,
        factorial_class_effects=class_effects,factorial_facet_effects=facet_effects,factorial_pair_effects=pair_effects,
        checkpoint_inventory={cid:i['summary']['checkpoint'] for cid,i in cell_data.items()},all_eight_candidates_retained=True,selected_candidate_id=None,
        checkpoint_selection_performed=False,default_promotion=False,recorded_new_updates_total=256,parity_source_observations=parity_observations,
        scored_source_rows=sum(r['rows'] for r in table if r['panel']!='law'),unscored_law_source_rows=72,
        source_only_dimension=384,latent_enabled=False,actual_encoder_calls_recorded=0,semantic_accuracy=None,statistical_significance_claimed=False,
        recommended_model_card_changes=card_changes,limitations=limitations,
        analyzer_actions=dict(numerical_imports=0,model_restores=0,model_forwards=0,checkpoint_JSON_parses=0,optimizer_updates=0,
            resource_API_leases_locks=0,network_external_compiler_Git_HF_mutations=0,evaluation_packet_opened_only_after_all8_freeze_fences=True))
    with OUTPUT.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps(dict(passed=True,output=pin(OUTPUT),cells=8,recorded_updates=256,selected_candidate=None),sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-manifest',required=True)
    parser.add_argument('--score-authored-eval',action='store_true')
    parser.add_argument('--output',required=True)
    main(parser.parse_args())
