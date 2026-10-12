"""Read-only sampled terminal resource audit; never restore or parse model states.

Each immutable phase review supplies every immediate opening record digest.
Private root-frozen endpoint copies let later cells proceed without changing the
meaning of this sampled closing observation. Neither sample proves continuous
custody, absolute RSS peaks, kernel quotas, legal accuracy, or model correctness.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.abc
import json
import math
import os
from pathlib import Path
import random
import stat
import struct
import sys

N = Path(__file__).resolve().parent
P = Path('/home/barberb/lift_coding/external/ipfs_datasets')
RUN_ROOT = P/'workspace/test-logs/legal-trigger-readout-pilot-20261007-01'
LEDGER = P/'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
BASELINE = N/'resource-baseline-audit-design-v01.json'
RESOURCES = dict(cpu_slots=2, memory_mb=1536, child_process_slots=1,
    storage_bytes=200_000_000, child_deadline_seconds=300,
    admission_timeout_seconds=120, ledger_lock_timeout_seconds=60)
PLAN_RESOURCES = dict(cpu_slots=2,rss_mib=1536,child_slots=1,
    storage_bytes=200_000_000,wall_seconds=300)
MAX_JSON_BYTES = 16*1024*1024
MAX_FILES = 1024
FIELDS = ('actor','action','object','conditions','exceptions','temporal')
GUARDIAN_WRAPPERS = ('pre-admission.json','scheduler-adoption.json','lease-binding.json',
    'command.json','resources-start.json','resource-observations.json','resources-final.json',
    'child-identity.json','child-exit.json','owned-group-final.json','guardian-exit.json',
    'group-rss-summary.json','lease-observations.jsonl','group-rss-observations.jsonl')
EXPECTED_PANELS = (('old_tune',96,True),('fresh_tune',36,True),('fresh_challenge',36,True),
    ('old_authored_eval',72,True),('authored_dev',72,True),('authored_eval',72,False),('law',8,False))
OUTPUT = None


def require(value, message):
    if not value:
        raise ValueError(message)


class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'}:
            raise AssertionError('Observer refuses numerical, model and resource-package imports: '+fullname)
        return None


def audit(event, args):
    if event.startswith(('subprocess.','socket.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock'}:
        raise AssertionError('Observer refuses network, subprocess, signalling and locks: '+event)
    if event == 'open':
        path, mode, flags = args
        if isinstance(path,(str,bytes,os.PathLike)):
            concrete = Path(os.fsdecode(path)).absolute()
            require(concrete.name != 'authored-reference-packet-v01.json', 'Evaluation reference packet prohibited')
        else:
            concrete = None
        writing = isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing |= isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing:
            require(OUTPUT is not None and concrete == OUTPUT, 'Only the exclusive owned audit receipt may be written')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def ordinary(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute ordinary path required')
    for part in (*reversed(path.parents),path):
        info = part.lstat()
        wanted = stat.S_ISDIR if part != path or directory else stat.S_ISREG
        require(not stat.S_ISLNK(info.st_mode) and wanted(info.st_mode), 'Ordinary path required: '+str(part))
    return path


def identity(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def pin(path):
    path = ordinary(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno()); hashed = hashlib.sha256(); size = 0
        for block in iter(lambda:stream.read(1024*1024),b''):
            hashed.update(block); size += len(block)
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(after) == identity(path.lstat()), 'Artifact changed during hash: '+str(path))
    return dict(path=str(path),bytes=size,sha256=hashed.hexdigest())


def same_pin(actual,expected):
    return all(actual[k] == expected[k] for k in ('bytes','sha256'))


def strict_json(raw):
    require(len(raw) <= MAX_JSON_BYTES, 'Bounded JSON required')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            require(key not in value, 'Duplicate JSON field'); value[key] = item
        return value
    def reject(value):
        raise ValueError('Nonfinite JSON constant: '+value)
    value = json.loads(raw,object_pairs_hook=unique,parse_constant=reject)
    def finite(item):
        if isinstance(item,float):
            require(math.isfinite(item),'Nonfinite parsed number')
        elif isinstance(item,dict):
            for child in item.values(): finite(child)
        elif isinstance(item,list):
            for child in item: finite(child)
    finite(value)
    return value


def read(path):
    path = Path(path)
    require('checkpoint' not in path.name and path.name != 'authored-reference-packet-v01.json', 'Model/reference JSON parse prohibited')
    before = pin(path)
    require(before['bytes'] <= MAX_JSON_BYTES,'Bounded JSON required')
    value = strict_json(path.read_bytes())
    require(pin(path) == before,'JSON changed while parsing')
    return value


def lines(path):
    before = pin(path); require(before['bytes'] <= MAX_JSON_BYTES,'Bounded JSONL required')
    rows = [strict_json(line) for line in Path(path).read_bytes().splitlines() if line]
    require(len(rows) <= 2048 and pin(path) == before,'Bounded stable JSONL required')
    return rows


def inventory(root):
    ordinary(root,directory=True); result = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat(); require(not stat.S_ISLNK(info.st_mode),'Symlink in owned attempt refused')
        if stat.S_ISDIR(info.st_mode): continue
        require(stat.S_ISREG(info.st_mode) and len(result) < MAX_FILES,'Bounded ordinary attempt artifacts required')
        result[str(path.relative_to(root))] = pin(path)
    return result


def root_identity(path):
    path = ordinary(path,directory=True); info = path.stat()
    return dict(path=str(path),device=info.st_dev,inode=info.st_ino)


def process(pid):
    try:
        raw = (Path('/proc')/str(pid)/'stat').read_text()
    except (FileNotFoundError,ProcessLookupError):
        return None
    fields = raw[raw.rfind(')')+2:].split()
    require(len(fields)>=22,'Valid Linux PID identity required')
    return dict(pid=pid,state=fields[0],group_pid=int(fields[2]),birth=fields[19],
        rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'))


def group_usage(child):
    require(type(child) is dict and set(child)=={'pid','birth'} and type(child['pid']) is int
        and child['pid']>1 and type(child['birth']) is str and child['birth'],'Exact owned child identity required')
    require(Path('/proc/self/stat').is_file(),'Linux process identities required')
    leader = process(child['pid'])
    require(leader is None or leader['birth']==child['birth'],'Owned PID reused; cannot qualify current group')
    entries = list(Path('/proc').iterdir()); require(len(entries)<=100_000,'Bounded process metadata observation required')
    live=rss=0
    for entry in entries:
        if entry.name.isdecimal():
            item=process(int(entry.name))
            if item is not None and item['group_pid']==child['pid'] and item['state']!='Z':
                live+=1; rss+=item['rss_bytes']
    return dict(available=True,live_processes=live,rss_bytes=rss)



def expected_policy(initialization_seed=1729, *, actor_ranking_enabled=False,
            presence_ce_weight=1, batch_order_seed=1729, batch_size=12):
    require(type(initialization_seed) is int and initialization_seed == 1729,
             "fixed inherited initialization seed1729 required")
    require(type(actor_ranking_enabled) is bool, "explicit actor ranking boolean required")
    require(type(presence_ce_weight) is int and presence_ce_weight in (1, 2),
             "conditions/exceptions presence weight must be integer1 or2")
    require(type(batch_order_seed) is int and batch_order_seed == 1729,
             "fixed distinct batch-order seed1729 required")
    require(type(batch_size) is int and batch_size == 12, "fixed batch size12 required")
    return {"schema": "bounded-source-span-targeted-loss-policy/v1",
        "objective": "modality2_presence_weighted_pointer_mean_plus_actor_hinge/v1",
        "modality_loss_weight": 2, "facet_pointer_CE_weights": {f: 1 for f in FIELDS},
        "optional_presence_CE_weights": {f: presence_ce_weight if f in ("conditions", "exceptions") else 1
                                        for f in FIELDS[2:]},
        "presence_ce_weight": presence_ce_weight,
        "normalization_denominator": 8 + 2 * (presence_ce_weight - 1),
        "main_summation_order": "(2*modality+sum(six_legacy_facets)+extra_two_presence_means)/(8+2*(w-1)); w1 uses exact legacy expression",
        "actor_ranking_enabled": actor_ranking_enabled, "actor_hinge_coefficient": .25,
        "actor_hinge_margin": 1., "actor_hinge_mean": "all_rows_in_batch_including_zero_negative_domain",
        "actor_span_score": "float32(start[left]+end[right])",
        "actor_negative_domain": "all_source_token_boundaries_left<=right_excluding_exactgold_and_overlap_with_present_gold_nonactor_facets",
        "actor_argmax": "detached_float32_scores; exact_ties_row_major; selected_score_recomputed_with_gradient",
        "actor_compatibility_scope": "teacher_forced_train_tune_only; token_range_nonoverlap_not_predictive_or_legalproof",
        "inference_candidate_coverage_guaranteed": False,
        "compatibility_filter_order_scope": "training_filters_before_argmax; unchanged_inference_topK_precedes_compatibility",
        "empty_actor_negative_domain": "differentiable_zero_on_valid_actor_logits; no_max_empty",
        "max_source_tokens": 128, "source_length_policy": "reject_above128_without_truncation",
        "initialization_seed": initialization_seed, "batch_order_seed": batch_order_seed,
        "batch_order_seed_origin": "explicit", "batch_size": batch_size,
        "max_new_optimizer_steps": 32, "max_seconds": 32,
        "latent_dimension": 384, "latent_enabled": False,
        "training_count": 168, "legacy_training_prefix_count": 96,
        "legacy_training_prefix_sha256": "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995",
        "promotion_gate": {"scope": "external_exposed_legacy96_engineering_diagnostic",
            "raw_exact_IR_required": 96, "joint_exact_IR_required": 96,
            "permission_to_obligation_errors_required": 0, "trainer_executes_promotion": False},
        "nested_loss_metadata_scope": "legacy_constructor_descriptor; this_outer_policy_defines_actual_training_objective"}


def validate_record_custody(original, opening_hashes, closing_hashes, own_id):
    require(type(original) is dict and len(original)==522,
        'Exact original522 record hashes required')
    require(type(opening_hashes) is dict and type(closing_hashes) is dict
        and all(opening_hashes.get(k)==v for k,v in original.items())
        and all(closing_hashes.get(k)==v for k,v in opening_hashes.items()),
        'Original522 or immediate opening record body changed')
    require(type(own_id) is str and own_id and own_id not in opening_hashes
        and set(closing_hashes)-set(opening_hashes)=={own_id},
        'Exactly one fresh owned closing record required')


def saved_float32(value):
    """Reproduce recorded scalar rounding only; never replay a numerical kernel."""
    require(type(value) in (int,float) and math.isfinite(value), 'Finite float32 scalar required')
    try:
        result=struct.unpack('!f',struct.pack('!f',value))[0]
    except (OverflowError,struct.error) as error:
        raise ValueError('Saved scalar overflows float32') from error
    require(math.isfinite(result), 'Saved scalar overflows float32')
    return result


def validate_objective_trace(report, batches, rows, policy):
    """Join saved teacher-forced diagnostics; never replay logits or models."""
    trace=report['objective_trace']
    require(type(trace) is dict and set(trace)=={'schema','batches','completed_updates',
        'batches_sha256','training_policy_sha256','scope','independent_numerical_kernel_trace',
        'evaluation_references_used'} and trace['schema']=='completed-targeted-objective-trace/v1'
        and type(trace['completed_updates']) is int and trace['completed_updates']==32
        and trace['training_policy_sha256']==digest(policy)
        and trace['scope']=='teacher_forced_training_objective_recorded_only_after_returned_finite_optimizer_step'
        and trace['independent_numerical_kernel_trace'] is False
        and trace['evaluation_references_used'] is False,
        'Closed saved objective-trace scope differs')
    entries=trace['batches']
    require(type(entries) is list and len(entries)==32 and trace['batches_sha256']==digest(entries),
        'Exact objective32 digest closure required')
    diagnostic_fields={'schema','main_loss','actor_hinge_mean','actor_hinge_applied',
        'actor_hinge_coefficient','total_loss','presence_CE_means','rows','teacher_forcing',
        'evaluation_references_used','semantic_compatibility_verified'}
    row_fields={'token_count','padded_score_width','full_valid_boundary_span_count',
        'compatible_wrong_candidate_count','compatible_wrong_domain_sha256','gold_coordinates',
        'gold_score_float32','chosen_wrong_coordinates','chosen_wrong_score_float32',
        'chosen_wrong_tie_count','present_gold_nonactor_coordinates','argmax_detached',
        'full_compatible_domain_traversed','padding_reversed_exactgold_and_othergold_overlap_excluded',
        'selection_implementation','row_position','id','source_sha256','actor_hinge_value','hinge_active',
        'gradient_enabled_by_policy','zero_domain_differentiable_zero',
        'teacher_forced_compatibility','semantic_compatibility_verified'}
    observed_rows=0
    for entry,batch in zip(entries,batches,strict=True):
        require(type(entry) is dict and set(entry)=={'schema','optimizer_step','indices','ids','diagnostics'}
            and entry['schema']=='completed-targeted-objective-batch/v1'
            and all(canonical(entry[k])==canonical(batch[k]) for k in ('optimizer_step','indices','ids')),
            'Objective/completed-batch identity join differs')
        diagnostic=entry['diagnostics']; numeric_fields=('main_loss','actor_hinge_mean','total_loss')
        require(type(diagnostic) is dict and set(diagnostic)==diagnostic_fields
            and diagnostic['schema']=='targeted-source-span-objective-diagnostics/v1'
            and diagnostic['actor_hinge_coefficient']==.25
            and diagnostic['actor_hinge_applied'] is policy['actor_ranking_enabled']
            and diagnostic['teacher_forcing'] is True and diagnostic['evaluation_references_used'] is False
            and diagnostic['semantic_compatibility_verified'] is False
            and type(diagnostic['presence_CE_means']) is dict
            and set(diagnostic['presence_CE_means'])=={'conditions','exceptions'},
            'Closed recorded teacher-forced objective differs')
        numbers=[diagnostic[k] for k in numeric_fields]+list(diagnostic['presence_CE_means'].values())
        require(all(type(v) is float and math.isfinite(v) and v>=0 and saved_float32(v)==v for v in numbers),
            'Finite nonnegative recorded objective means required')
        objective_rows=diagnostic['rows']
        require(type(objective_rows) is list and len(objective_rows)==len(batch['indices'])==12,
            'One objective diagnostic per returned batch row required')
        for position,(row,source_index) in enumerate(zip(objective_rows,batch['indices'],strict=True)):
            require(type(row) is dict and set(row)==row_fields and type(row['row_position']) is int
                and row['row_position']==position and row['id']==rows[source_index]['id']
                and row['source_sha256']==hashlib.sha256(rows[source_index]['source_text'].encode()).hexdigest(),
                'Objective actual training-source occurrence differs')
            count=row['token_count']; candidate_count=row['compatible_wrong_candidate_count']
            require(type(count) is int and 1<=count<=128 and type(row['padded_score_width']) is int
                and count<=row['padded_score_width']<=128
                and type(row['full_valid_boundary_span_count']) is int
                and row['full_valid_boundary_span_count']==count*(count+1)//2
                and type(candidate_count) is int and 0<=candidate_count<row['full_valid_boundary_span_count']
                and row['argmax_detached'] is True and row['full_compatible_domain_traversed'] is True
                and row['padding_reversed_exactgold_and_othergold_overlap_excluded'] is True
                and row['selection_implementation']=='vectorized_detached_source_boundary_gather'
                and row['teacher_forced_compatibility'] is True and row['semantic_compatibility_verified'] is False
                and row['gradient_enabled_by_policy'] is policy['actor_ranking_enabled'],
                'Recorded actor domain count/scope differs')
            def coordinates(value):
                return type(value) is list and len(value)==2 and all(type(i) is int for i in value) \
                    and 0<=value[0]<=value[1]<count
            gold=row['gold_coordinates']; chosen=row['chosen_wrong_coordinates']
            other=row['present_gold_nonactor_coordinates']
            require(coordinates(gold) and type(other) is dict and set(other)<=set(FIELDS)-{'actor'}
                and all(coordinates(span) for span in other.values()),
                'Bounded recorded gold compatibility coordinates required')
            active=[gold,*other.values()]
            require(all(a[1]<b[0] or b[1]<a[0] for index,a in enumerate(active)
                for b in active[index+1:]),'Recorded gold compatibility facets overlap')
            domain=[[left,right] for left in range(count) for right in range(left,count)
                if [left,right]!=gold and not any(left<=span[1] and span[0]<=right for span in other.values())]
            require(candidate_count==len(domain) and row['compatible_wrong_domain_sha256']==digest(domain)
                and ((chosen is None) is (candidate_count==0))
                and row['zero_domain_differentiable_zero'] is (candidate_count==0)
                and (chosen is None or coordinates(chosen) and chosen in domain),
                'Saved compatible domain/selected-coordinate custody differs')
            require(type(row['gold_score_float32']) is float and saved_float32(row['gold_score_float32'])==row['gold_score_float32']
                and type(row['actor_hinge_value']) is float and saved_float32(row['actor_hinge_value'])==row['actor_hinge_value']
                and row['actor_hinge_value']>=0 and row['hinge_active'] is (row['actor_hinge_value']>0)
                and type(row['chosen_wrong_tie_count']) is int
                and (row['chosen_wrong_score_float32'] is None and row['chosen_wrong_tie_count']==0
                     if chosen is None else type(row['chosen_wrong_score_float32']) is float
                     and saved_float32(row['chosen_wrong_score_float32'])==row['chosen_wrong_score_float32']
                     and 1<=row['chosen_wrong_tie_count']<=candidate_count),
                'Finite saved actor choice/hinge diagnostics required')
            expected_hinge=(0. if chosen is None else max(0.,saved_float32(
                saved_float32(1.+row['chosen_wrong_score_float32'])-row['gold_score_float32'])))
            require(row['actor_hinge_value']==expected_hinge,
                'Recorded left-associated float32 score/hinge arithmetic differs')
            observed_rows+=1
        # Scalar custody only: no logits, argmax, gradients or tensor reduction
        # are replayed. Match the trainer's nonnegative float32 reduction bound.
        count=len(objective_rows)
        reference_mean=math.fsum(r['actor_hinge_value'] for r in objective_rows)/count
        unit_roundoff=2.**-24
        gamma=(count+1)*unit_roundoff/(1.-(count+1)*unit_roundoff)
        tolerance=gamma*reference_mean+2.**-149
        total=(saved_float32(diagnostic['main_loss']+saved_float32(.25*diagnostic['actor_hinge_mean']))
            if policy['actor_ranking_enabled'] else diagnostic['main_loss'])
        require(abs(reference_mean-diagnostic['actor_hinge_mean'])<=tolerance
            and total==diagnostic['total_loss'] and diagnostic['total_loss']==batch['loss'],
            'Recorded objective means/batch loss float32 scalar closure differs')
    return dict(schema='targeted-objective-recorded-metadata-audit/v1',completed_updates=32,
        objective_training_row_occurrences=observed_rows,batches_sha256=digest(entries),
        teacher_forced_only=True,independent_argmax_or_gradient_replay=False,
        evaluation_reference_access=False,semantic_compatibility_verified=False)


def validate_trace(report,summary,plan):
    require(report['schema']=='bounded-targeted-loss-span-legal-formula-training/v1'
        and type(report['optimizer_steps']) is int and type(report['continuation_optimizer_steps_total']) is int
        and report['optimizer_steps']==report['continuation_optimizer_steps_total']==32
        and report['training_executed'] is True and report['stopped_reason']=='step_limit',
        'Exact completed32 targeted training report required')
    cell=plan['cell']; policy=report['training_policy']
    require(type(cell) is dict and set(cell)=={'id','actor_ranking_enabled','presence_ce_weight','modality_loss_weight'}
        and type(cell['actor_ranking_enabled']) is bool and type(cell['presence_ce_weight']) is int
        and cell['presence_ce_weight'] in (1,2) and type(cell['modality_loss_weight']) is int
        and cell['modality_loss_weight']==2
        and cell['id']=='rank'+str(int(cell['actor_ranking_enabled']))+'-presence'+str(cell['presence_ce_weight']),
        'Exact four-cell targeted objective identity required')
    expected=expected_policy(actor_ranking_enabled=cell['actor_ranking_enabled'],presence_ce_weight=cell['presence_ce_weight'])
    require(canonical(policy)==canonical(expected) and digest(policy)==report['training_policy_sha256'],
        'Declared closed targeted objective/sampler differs')
    require(report['source_parent_checkpoint_sha256']==plan['parent_base_canonical_sha256']
        and report['source_parent_model_state_sha256']==plan['parent_model_state_sha256'],
        'Training parent lineage differs')
    data=read(Path(plan['data_export']['path'])); rows=data['training_populations']['mixed']
    require(set(data['training_populations'])=={'mixed'} and len(rows)==168
        and digest(rows)==plan['training_manifest_sha256'], 'Exact common mixed168 manifest required')
    trace=report['batch_trace']; prepared=summary['prepared_schedule']; batches=trace['batches']
    require(trace['schema']=='completed-curriculum-batch-trace/v1'
        and type(trace['training_count']) is int and trace['training_count']==168
        and type(trace['completed_updates']) is int and trace['completed_updates']==32
        and type(batches) is list and len(batches)==32 and trace['training_manifest_sha256']==digest(rows)
        and type(trace['batch_size']) is int and trace['batch_size']==12
        and type(trace['batch_order_seed']) is int and trace['batch_order_seed']==1729
        and trace['batch_order_seed_origin']=='explicit' and trace['independent_runtime_trace'] is False
        and trace['unreturned_partial_updates_attested'] is False,
        'Exact completed batch count/manifest/trace scope required')
    progress=dict(epochs_completed=0,row_cursor=0,optimizer_steps=0)
    require(canonical(trace['initial_progress'])==canonical(progress),'Zero-origin32 updates required')
    for step,batch in enumerate(batches,1):
        order=list(range(168)); random.Random(1729+progress['epochs_completed']).shuffle(order)
        indices=order[progress['row_cursor']:progress['row_cursor']+12]
        require(set(batch)=={'schema','indices','ids','pre_progress','post_progress','optimizer_step','loss','gradient_norm_before_clip'}
            and batch['schema']=='completed-curriculum-batch/v1'
            and canonical(batch['pre_progress'])==canonical(progress)
            and type(batch['indices']) is list and all(type(i) is int for i in batch['indices'])
            and batch['indices']==indices and batch['ids']==[rows[i]['id'] for i in indices]
            and type(batch['optimizer_step']) is int and batch['optimizer_step']==step,
            'Completed batch schedule/identity differs')
        for key in ('loss','gradient_norm_before_clip'):
            require(type(batch[key]) in (int,float) and math.isfinite(batch[key]) and batch[key]>=0,
                'Finite nonnegative batch scalar required')
        progress=dict(progress); progress['optimizer_steps']+=1; progress['row_cursor']+=12
        if progress['row_cursor']==168:
            progress['epochs_completed']+=1; progress['row_cursor']=0
        require(canonical(batch['post_progress'])==canonical(progress),'Completed trace transition differs')
    indices=[b['indices'] for b in batches]; ids=[b['ids'] for b in batches]
    require(canonical(trace['final_progress'])==canonical(progress)==canonical(prepared['final_progress'])
        and progress==dict(epochs_completed=2,row_cursor=48,optimizer_steps=32)
        and prepared['batch_indices']==indices and prepared['batch_ids']==ids
        and trace['indices_sha256']==digest(indices) and trace['ids_sha256']==digest(ids)
        and trace['batches_sha256']==digest(batches) and report['batch_losses']==[b['loss'] for b in batches],
        'Exact32 trace closure differs')
    objective=validate_objective_trace(report,batches,rows,policy)
    return dict(returned_optimizer_updates=32,declared_sampler_independently_reproduced=True,
        batches_sha256=digest(batches),training_policy_sha256=digest(policy),final_progress=progress,
        objective_metadata=objective,
        trace_scope='Returned completed-batch/objective reports; no independent kernel, logits, gradient or numerical replay')


def main(args):
    global OUTPUT
    OUTPUT=Path(args.output).absolute()
    require(OUTPUT.parent==N and not OUTPUT.exists(),'Fresh owned audit receipt under N required')
    sys.dont_write_bytecode=True; sys.meta_path.insert(0,DenyModels()); sys.addaudithook(audit)
    source_review_path=ordinary(Path(args.source_review).absolute())
    source_review_pin=pin(source_review_path); source_review=read(source_review_path)
    require(source_review['passed'] is True and source_review['findings']==[]
        and source_review['auditor']==pin(Path(__file__).resolve()),'Independent exact auditor source approval required')
    require(pin(BASELINE)['sha256']=='329167f594fd856f6b297dba509e64778799a03d133a03ff3b0618ed109192d8',
        'Immutable initial baseline source differs')
    baseline=read(BASELINE); require(baseline['passed'] is True and baseline['findings']==[],'Exact clean initial baseline required')
    old=baseline['baseline_ledger']; original=old['record_body_hashes']
    require(len(original)==522 and digest(original)==old['record_body_hash_map_sha256'],'Initial522 digest baseline differs')
    plan_path=ordinary(Path(args.plan).absolute()); plan=read(plan_path)
    review_path=ordinary(Path(args.review).absolute()); review=read(review_path)
    attempt=RUN_ROOT/plan['attempt_name']; ordinary(attempt,directory=True)
    require(attempt.name==plan['attempt_name'] and plan['resource_contract']==PLAN_RESOURCES
        and plan['latent_enabled'] is False and plan['dimension']==384,'Exact bounded source-only cell required')
    require(review['passed'] is True and review['findings']==[] and review['phase']=='training'
        and review['selected_cell']==plan['cell'] and review['attempt_name']==plan['attempt_name']
        and review['package_root']==plan['package_root'] and review['run_root']==str(RUN_ROOT),
        'Concrete independent selected-cell review differs')
    pre=read(attempt/'pre-admission.json')
    for field,path in [('plan',plan_path),('runner',Path(plan['runner_path'])),('guardian',Path(plan['guardian_path'])),('review',review_path)]:
        require(pre[field]==pin(path),'Actual pre-admission pin differs: '+field)
        if field!='review':
            require(review[field+'_sha256']==pre[field]['sha256'],'Concrete source approval differs: '+field)
    compatible=pre['compatibility']; opening=review['opening_ledger']; opening_scheduler=review['opening_scheduler']
    opening_hashes=opening['record_body_sha256']
    require(len(opening_hashes)==opening['record_count'] and digest(opening_hashes)==opening['record_body_hash_map_sha256']
        and all(opening_hashes.get(k)==v for k,v in original.items()),'Opening review must preserve original522 bodies')
    require(same_pin(compatible['disk_ledger'],opening) and compatible['disk_ledger']['path']==str(LEDGER)
        and compatible['resources']==RESOURCES and compatible['disk_limit_bytes']==145_000_000_000
        and compatible['shared_config']==opening_scheduler['config']==baseline['scheduler_observation']['config']
        and same_pin(compatible['shared_state'],opening_scheduler),'Actual opening resource observation differs')
    for path,expected in compatible['producers'].items():
        require(same_pin(pin(Path(path)),expected),'Pinned resource producer differs: '+path)
    for path,expected in plan['artifacts'].items():
        require(same_pin(pin(Path(path)),expected),'Frozen input/source drift: '+path)
    # Dynamic global endpoints are bound by pre-admission and sampled copies,
    # rather than compared to an already superseded live endpoint.
    for path,expected in review['artifacts'].items():
        if path not in (str(LEDGER),str(SCHEDULER)):
            require(same_pin(pin(Path(path)),expected),'Independent static artifact drift: '+path)
    snapshot_path=ordinary(Path(args.snapshot_receipt).absolute())
    require(snapshot_path.parent==N/'private-runtime-snapshots'/plan['cell']['id'],'Cell-specific private snapshot receipt required')
    snapshot_receipt_pin=pin(snapshot_path); snapshots=read(snapshot_path)
    require(snapshots['schema']=='targeted-private-terminal-endpoints/v1' and snapshots['private_bodies'] is True
        and snapshots['continuous_custody'] is False and snapshots['resource_api_called'] is False
        and snapshots['cell']==plan['cell']['id'] and snapshots['plan']==pin(plan_path)
        and snapshots['terminal']==pin(attempt/'guardian-exit.json'),'Cell-specific private snapshot authority differs')
    for field,original_path in [('ledger',LEDGER),('scheduler',SCHEDULER)]:
        descriptor=snapshots[field]; snapshot=Path(descriptor['path'])
        require(snapshot.parent==snapshot_path.parent and same_pin(pin(snapshot),descriptor)
            and snapshots['source_'+field]['path']==str(original_path)
            and same_pin(descriptor,snapshots['source_'+field]),'Private sampled endpoint custody differs: '+field)
    ledger=read(Path(snapshots['ledger']['path'])); scheduler=read(Path(snapshots['scheduler']['path']))
    require(ledger['schema']==opening.get('schema',old['schema'])==old['schema']
        and ledger['limit_bytes']==opening['limit_bytes']==145_000_000_000
        and ledger['roots']==opening['roots']==baseline['counted_root_metadata'],'Ledger cap/schema/scope changed')
    require([root_identity(Path(r['path'])) for r in ledger['roots']]==ledger['roots'],'Counted root identity changed')
    hashes={key:digest(row) for key,row in ledger['reservations'].items()}
    require(all(hashes.get(k)==v for k,v in original.items()) and all(hashes.get(k)==v for k,v in opening_hashes.items()),
        'Original522 or immediate opening record body changed')
    files=inventory(attempt); terminal=read(attempt/'guardian-exit.json'); child_exit=read(attempt/'child-exit.json')
    require(set(GUARDIAN_WRAPPERS)<={p for p in files if '/' not in p}
        and 'child.log' in files,'All14 unchanged guardian wrapper artifacts and child log required')
    for name in GUARDIAN_WRAPPERS:
        (lines if name.endswith('.jsonl') else read)(attempt/name)
    require(terminal['schema']=='scope-pilot-guardian-exit/v1' and type(terminal['returncode']) is int
        and terminal['returncode']==0 and child_exit['returncode']==0 and child_exit['leader_reaped'] is True,
        'Successful terminal0/reaped child required; preserve failure without qualification')
    final=read(attempt/'resources-final.json'); start=read(attempt/'resources-start.json')
    own_id=final['owner']['reservation_id']; record=ledger['reservations'].get(own_id)
    validate_record_custody(original,opening_hashes,hashes,own_id)
    require(set(hashes)-set(opening_hashes)=={own_id} and own_id not in opening_hashes
        and record is not None and digest(record)==digest(final['owner']['record'])
        and start['reservation_id']==own_id,'Exactly one new owned claim and terminal body required')
    child=read(attempt/'child-identity.json'); cleanup=read(attempt/'owned-group-final.json')
    require(record['child']==child and record['attempt_directory']==root_identity(attempt)
        and cleanup['leader_reaped'] is True and cleanup['live_group_processes']==0,'Owned child/attempt cleanup differs')
    for key in ('storage_bytes','memory_mb','cpu_slots','child_process_slots'):
        require(record[key]==RESOURCES[key],'Owned reservation envelope differs: '+key)
    require(record['status']=='released' and record['artifacts_durable_asserted'] is True
        and record['attempt_exceeded_reservation'] is False and record['final_total_charged_bytes']<=200_000_000
        and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,
        'Successful durable own200MB release required')
    binding=read(attempt/'lease-binding.json'); lease_id=binding['own_fields']['lease_id']
    require(binding['capability_persisted'] is False and binding['state_path']==str(SCHEDULER)
        and binding['config_sha256']==digest(opening_scheduler['config'])
        and binding['own_fields']['requires_gpu'] is False and binding['own_fields']['gpu_memory_mb']==0
        and binding['own_fields']['unified_memory_mb']==0
        and all(binding['own_fields'][k]==RESOURCES[k] for k in ('cpu_slots','memory_mb','child_process_slots')),
        'Own lease envelope/capability differs')
    require(scheduler['config']==opening_scheduler['config'] and lease_id not in scheduler['leases'],
        'Sampled scheduler config differs or owned lease remains')
    lease_log=lines(attempt/'lease-observations.jsonl')
    starts=[e for e in lease_log if e.get('schema')=='guardian-owned-lease-watchdog-start/v1']
    require(len(starts)==1 and starts[0]['binding']==binding and starts[0]['poll_seconds']==1.0
        and starts[0]['maximum_observation_gap_seconds']==5.0
        and starts[0]['continuous_coverage_claimed'] is False,'Exact lease watchdog start binding differs')
    lease_events=[e for e in lease_log if e.get('schema')=='guardian-owned-lease-observation/v1']
    require(len(lease_events)+1==len(lease_log) and lease_events and all(e.get('healthy') is True
        and e.get('configuration_matches') is True and e.get('continuous_coverage_claimed') is False
        and e['lease_id']==lease_id and e['capability_persisted'] is False and e['read_only'] is True
        and e['expected_config_sha256']==binding['config_sha256']==e['observed_config_sha256']
        and e['changed_known_configuration_fields']==[] and e['unknown_configuration_fields_present'] is False
        and (e['expected']=='absent' or e['owned_identity_matches'] is True and e['lease_present'] is True)
        for e in lease_events),
        'Successful lease observation closure required')
    require({'pre_spawn','post_spawn','pre_finalize'} <= {e['stage'] for e in lease_events}
        and lease_events[-1]['stage']=='post_finalize' and lease_events[-1]['expected']=='absent'
        and lease_events[-1]['lease_present'] is False and final['lease_absent']==lease_events[-1]
        and final['continuous_lease_coverage_claimed'] is False,'Recorded own lease release closure differs')
    require(all(e.get('observation_gap_seconds',0)<=5 for e in lease_events if e['stage'] in {'monitor','post_spawn'}),
        'Recorded lease gap exceeds bound')
    require(all(a['observed_at_monotonic']<=b['observed_at_monotonic'] for a,b in zip(lease_events,lease_events[1:])),
        'Lease monotonic sample order differs')
    require(final['lease_events']==pin(attempt/'lease-observations.jsonl')
        and final['group_rss_summary']==pin(attempt/'group-rss-summary.json'),'Final observation pins differ')
    rss=read(attempt/'group-rss-summary.json'); rss_events=lines(attempt/'group-rss-observations.jsonl')
    require(rss['identity']==child and rss['memory_limit_bytes']==1536*1024*1024 and rss['failure'] is None
        and rss['events']==pin(attempt/'group-rss-observations.jsonl'),'Successful RSS evidence identity/pin differs')
    counts=dict(Counter(e['phase'] for e in rss_events))
    require(set(counts)<={'gated','model','post_model'} and len(rss_events)<=1024,'Bounded RSS phases required')
    previous=None
    for event in rss_events:
        observed=event['observed_at_monotonic']; gap=event['observation_gap_seconds']
        require(type(observed) in (int,float) and observed>=rss['sampler_started_at_monotonic']
            and event['sample_elapsed_seconds']>=0 and event['scheduler_or_claim_mutation'] is False,
            'RSS timestamp/read-only scope differs')
        # This is an auditor criterion for the observed sample gaps. The
        # unchanged RSS sampler does not advertise a configured five-second
        # hard-stop gap or continuous/absolute peak coverage.
        require(gap is None if previous is None else gap is not None and 0<=gap<=5
            and abs(gap-(observed-previous))<=1e-8,'RSS sampled timestamp/gap reconstruction differs')
        previous=observed
    for phase in ('gated','model','post_model'):
        events=[e for e in rss_events if e['phase']==phase]
        require(counts.get(phase,0)==rss['sample_counts_by_phase'][phase]
            and max((e['group_rss_bytes'] for e in events),default=0)==rss['sampled_peaks_by_phase'][phase]
            and (events[0]['observed_at_monotonic'] if events else None)==rss['first_observation_monotonic_by_phase'][phase]
            and (events[-1]['observed_at_monotonic'] if events else None)==rss['last_observation_monotonic_by_phase'][phase]
            and max((e['observation_gap_seconds'] for e in events if e['observation_gap_seconds'] is not None),default=0.0)
                ==rss['max_observation_gap_seconds_by_phase'][phase],
            'RSS count/peak reconstruction differs')
    require(all(e.get('schema')=='guardian-owned-group-rss-observation/v1' and e['identity']==child
        and e['memory_limit_bytes']==1536*1024*1024 and 0<=e['group_rss_bytes']<=1536*1024*1024
        and e['sampled_only'] is True and e['kernel_hard_cap'] is False for e in rss_events),
        'RSS observed envelope differs')
    require(rss['model_phase_sample_count']>0 and rss['sampled_peak_only'] is True
        and rss['model_phase_sample_count']==rss['sample_counts_by_phase']['model']
        and rss['sampled_model_phase_peak_rss_bytes']==rss['sampled_peaks_by_phase']['model']
        and rss['absolute_peak_measured'] is False and rss['continuous_coverage_claimed'] is False
        and rss['poll_seconds']==1.0 and rss['kernel_hard_cap'] is False and rss['scheduler_or_claim_mutation'] is False
        and abs(rss['model_phase_wall_seconds']-(rss['model_leader_reaped_at_monotonic']-rss['model_gate_permitted_at_monotonic']))<=1e-8
        and rss['model_phase_wall_seconds']<=300 and child_exit['launch_through_reap_wall_seconds']<=300
        and terminal['sampled_model_phase_peak_rss_bytes']==rss['sampled_model_phase_peak_rss_bytes']
        and terminal['model_phase_RSS_sample_count']==rss['model_phase_sample_count']
        and terminal['model_phase_peak_is_sampled'] is True and terminal['kernel_hard_memory_cap'] is False,
        'Sampled RSS/deadline qualification differs')
    summary=read(attempt/'results/summary.json')
    require(summary['schema']=='targeted-loss-curriculum-cell-results/v1' and summary['status']=='completed'
        and summary['cell']==plan['cell'] and summary['attempt_name']==plan['attempt_name']
        and summary['actual_new_updates']==32 and summary['actual_encoder_calls']==0
        and summary['configured_dimension']==384 and summary['latent_enabled'] is False
        and summary['training_count']==168 and summary['fresh_Adam'] is True
        and summary['inherited_optimizer_moments'] is False and summary['parent_optimizer_steps']==400
        and summary['same_original_parent_model_sha256']==plan['parent_model_state_sha256']
        and summary['baseline_model_state_sha256']==plan['parent_model_state_sha256'] and summary['baseline_optimizer_steps']==0,
        'Completed targeted-loss cell lineage/scope differs')
    require(summary['semantic_accuracy'] is None and summary['independent_statutory_gold'] is False
        and summary['checkpoint_selection_executed'] is False and summary['default_promotion'] is False
        and summary['Lake_executed'] is False,'Exploratory result authority differs')
    require(canonical(summary['promotion_gate'])==canonical(plan['promotion_gate']),
        'External retained-permission gate differs; auditor does not execute promotion')
    for field,name in [('checkpoint','cell-checkpoint.json'),('training','cell-training.json')]:
        require(summary[field]==pin(attempt/'results'/name),'Saved '+field+' custody differs')
    report=read(attempt/'results/cell-training.json')
    require(report['checkpoint_sha256']==summary['checkpoint']['sha256'],'Canonical saved checkpoint raw hash differs from report')
    trace=validate_trace(report,summary,plan)
    for owners in (summary['opening_owners'],summary['closing_owners']):
        require(owners and all(name in plan['source_owner_pins'] and expected==plan['source_owner_pins'][name]
            and pin(Path(expected['path']))==expected for name,expected in owners.items()),'Observed source owner origin differs')
    panel_rows=[]
    require(len(summary['diagnostics'])==len(plan['diagnostic_panels'])==7,'Complete selected diagnostics required')
    require([(p['name'],p['count'],p['has_authored_reference']) for p in plan['diagnostic_panels']]
        ==list(EXPECTED_PANELS) and all(type(p['count']) is int
        and type(p['has_authored_reference']) is bool for p in plan['diagnostic_panels']),
        'Exact five scored authored/exposed and two unscored source panels required')
    for panel,expected in zip(summary['diagnostics'],plan['diagnostic_panels'],strict=True):
        require(panel['name']==expected['name'] and panel['row_count']==expected['count']
            and panel['has_authored_reference'] is expected['has_authored_reference'],'Diagnostic panel differs')
        for field in ('raw','joint','score'):
            descriptor=panel[field]
            if descriptor is not None:
                path=Path(descriptor['path'])
                require(path.parent==attempt/'results' and path.name=='trained-'+panel['name']+'-'+field+'.json'
                    and pin(path)==descriptor,'Diagnostic saved artifact differs')
            else:
                require(field=='score' and not expected['has_authored_reference'],'Missing required diagnostic artifact')
        require((panel['score'] is not None)==expected['has_authored_reference'],'Evaluation/law reference score prohibited')
        panel_rows.append(dict(name=panel['name'],rows=panel['row_count'],saved_reference_score=panel['score'] is not None))
    require(sum(row['rows'] for row in panel_rows)==392,'Exact seven-panel392 source rows required')
    total=sum(row['bytes'] for row in files.values()); require(total<=200_000_000,'Terminal bytes exceed own200MB envelope')
    live=group_usage(child); require(live['live_processes']==0,'Current owned child group still live')
    # Repeat static/sample custody at close; no claim of live global endpoint stability.
    require(inventory(attempt)==files,'Attempt changed during audit')
    for descriptor in (snapshots['ledger'],snapshots['scheduler']):
        require(pin(Path(descriptor['path']))=={k:descriptor[k] for k in ('path','bytes','sha256')},'Private sampled endpoint changed during audit')
    require(pin(snapshot_path)==snapshot_receipt_pin,'Snapshot receipt changed during audit')
    for path,expected in plan['artifacts'].items():
        require(same_pin(pin(Path(path)),expected),'Closing frozen input/source drift: '+path)
    for path,expected in review['artifacts'].items():
        if path not in (str(LEDGER),str(SCHEDULER)):
            require(same_pin(pin(Path(path)),expected),'Closing independent static artifact drift: '+path)
    require(pin(source_review_path)==source_review_pin
        and pin(plan_path)==pre['plan'] and pin(review_path)==pre['review']
        and pin(Path(plan['runner_path']))==pre['runner'] and pin(Path(plan['guardian_path']))==pre['guardian']
        and pin(Path(__file__).resolve())==source_review['auditor']
        and pin(BASELINE)['sha256']=='329167f594fd856f6b297dba509e64778799a03d133a03ff3b0618ed109192d8',
        'Closing exact source/plan/review/baseline fence differs')
    result=dict(schema='targeted-loss-terminal-resource-audit/v1',passed=True,findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),auditor=pin(Path(__file__).resolve()),
        source_review=pin(source_review_path),phase_review=pre['review'],plan=pre['plan'],
        cell=plan['cell'],attempt_name=plan['attempt_name'],physical_attempt=str(attempt),artifacts=files,
        baseline=pin(BASELINE),snapshot_receipt=pin(snapshot_path),
        closing_ledger_sample=pin(Path(snapshots['ledger']['path'])),
        closing_scheduler_sample=pin(Path(snapshots['scheduler']['path'])),
        original_record_count=522,all_original522_record_bodies_unchanged=True,
        opening_record_count=len(opening_hashes),all_immediate_opening_record_bodies_unchanged=True,
        closing_record_count=len(hashes),exactly_one_new_owned_claim=True,
        own_reservation_id=own_id,own_record_body_sha256=hashes[own_id],own_record_status='released',
        resources=RESOURCES,cap_unchanged=True,root_identities_unchanged=True,
        attempt_terminal_bytes=total,final_total_charged_bytes=record['final_total_charged_bytes'],
        final_reserved_attempt_bytes=record['final_attempt_bytes'],
        final_accounting_excludes_later_terminal_receipts=True,
        guardian_returncode=0,child_returncode=0,leader_reaped=True,current_owned_group=live,
        artifacts_durable_asserted=True,lease_id=lease_id,owned_lease_absent_in_terminal_sample=True,
        scheduler_config_unchanged=True,lease_observation_count=len(lease_events),
        group_RSS_observation_count=len(rss_events),model_RSS_sample_count=rss['model_phase_sample_count'],
        sampled_model_phase_peak_rss_bytes=rss['sampled_model_phase_peak_rss_bytes'],
        model_phase_wall_seconds=rss['model_phase_wall_seconds'],
        child_launch_through_reap_wall_seconds=child_exit['launch_through_reap_wall_seconds'],
        guardian_elapsed_seconds=terminal['elapsed_seconds'],trace=trace,diagnostic_custody=panel_rows,
        guardian_wrapper_count=14,all14_guardian_wrappers_bound=True,
        diagnostic_panel_count=7,diagnostic_source_rows=392,
        sampled_endpoints_only=True,live_global_endpoints_not_requalified=True,
        sampled_peak_only=True,absolute_peak_measured=False,kernel_hard_cap=False,
        observed_RSS_gap_qualification_ceiling_seconds=5,guardian_configured_RSS_gap_ceiling_claimed=False,
        continuous_custody_claimed=False,audit_model_calls=0,audit_optimizer_updates=0,
        audit_resource_API_calls=0,audit_locks_acquired=0,audit_claims_modified=False,
        audit_limits_modified=False,audit_checkpoint_JSON_parses=0,audit_checkpoint_restore=False,
        audit_eval_reference_packet_access=False,full_record_bodies_published=False,
        HF_mutation=False,Lake_executed=False,semantic_accuracy=None)
    with OUTPUT.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps(dict(passed=True,cell=plan['cell']['id'],updates=32,own_claim_status='released',terminal_bytes=total),sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('plan','review','snapshot-receipt','source-review','output'):
        parser.add_argument('--'+option,required=True)
    main(parser.parse_args())
