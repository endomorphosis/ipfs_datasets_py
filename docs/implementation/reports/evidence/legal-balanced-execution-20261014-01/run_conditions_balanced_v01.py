"""One bounded conditions-balanced CE head repair from the exact trained N10 parent.

Fresh reference labels remain outside this process. Execute only through the
unchanged qualified guardian; all scoring follows a durable output freeze.
"""
from contextlib import ExitStack
import argparse
import ctypes.util
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
from unittest.mock import patch

F = Path(__file__).resolve().parent
N6 = F.parent / 'legal-temporal-adapter-20261013-01'
LEGACY_RUNNER = N6 / 'run_temporal_adapter.py'
LEGACY_SHA = '51fc99fa25a0c2c7636c34f1d569651ba0a545562a3ca26723280104384d5c3b'
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
CELL = 'conditions-balanced-ce'
ATTEMPT = 'conditions-balanced-20261014-' + CELL + '-01'
OLD_PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
FRESH_PANELS = ('fresh_dev', 'fresh_test')
PANELS = OLD_PANELS + FRESH_PANELS
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8, 36, 36), strict=True))
SOURCE_SHA = 'b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3'
SOURCE_STATE_SHA = 'c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
             semantic_correctness_verified=False, promotion_performed=False)
STATE = dict(created_output=None, completed_updates=0, stage='preflight', in_progress_updates_unknown=False)
READ_PINS = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(), 'Physical absolute file required')
    before = path.stat()
    hashed, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            hashed.update(block)
            size += len(block)
    after = path.stat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    require(identity(before) == identity(after) and size == before.st_size, 'Raw input drift')
    return dict(path=str(path), bytes=size, sha256=hashed.hexdigest())


def read(path, expected=None):
    path = Path(path)
    captured = pin(path)
    require(captured['bytes'] <= 32 * 1024 * 1024 and (expected is None or captured == expected), 'Exact bounded input required')
    raw = path.read_bytes()
    require(dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == captured and pin(path) == captured,
            'Consumed metadata bytes differ')
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == captured, 'Previous parsed identity drift')
    READ_PINS[str(path)] = captured
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def finite(raw):
        value = float(raw)
        require(math.isfinite(value), 'Nonfinite JSON float')
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def write(path, value):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, 'Physical output path required')
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return pin(path)


def legacy_runner():
    require(pin(LEGACY_RUNNER)['sha256'] == LEGACY_SHA, 'Qualified N6 helper source changed')
    spec = importlib.util.spec_from_file_location('retained_actor_boundary_helpers', LEGACY_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_KEYS = {'schema', 'package_root', 'runner_path', 'guardian_path', 'attempt_name', 'cell',
    'source_owner_pins', 'artifacts', 'data_export', 'fresh_source_export', 'source_checkpoint',
    'source_model_state_sha256', 'context_contract', 'training_manifest_sha256', 'legacy_prefix_sha256',
    'source_reference_panels', 'ctypes_dl_resolution', 'forbidden_reference_paths',
    'resource_contract', 'training_seconds', 'diagnostic_panels', 'evaluation_contract', 'proposal',
    'configured_dimension', 'latent_enabled', 'default_promotion', 'Lake_executed','expected_loaded_owner_count'}


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == PLAN_KEYS and plan['schema'] == 'conditions-balanced-cell-plan/v1', 'Closed conditions-balanced plan required')
    require(plan['package_root'] == str(F / 'datasets') and plan['runner_path'] == str(Path(__file__).resolve())
            and plan['guardian_path'] == str(F / 'run_scope_guardian_v02.py') and plan['cell'] == CELL
            and plan['attempt_name'] == ATTEMPT, 'Exact owned producers/attempt required')
    require(plan['source_checkpoint']['sha256'] == SOURCE_SHA and plan['source_checkpoint']['bytes'] == 6464267
            and plan['source_model_state_sha256'] == SOURCE_STATE_SHA, 'Exact trained N10 parent required')
    require(plan['legacy_prefix_sha256'] == '4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995', 'Legacy training prefix changed')
    require(plan['resource_contract'] == dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300), 'Unchanged training envelope required')
    require(type(plan['training_seconds']) is int and plan['training_seconds'] == 32 and plan['configured_dimension'] == 384
            and plan['latent_enabled'] is False and plan['default_promotion'] is False and plan['Lake_executed'] is False,
            'Fixed source-only training recipe required')
    require(plan['diagnostic_panels'] == [dict(name=n, count=COUNTS[n]) for n in PANELS], 'All464 source diagnostics required')
    require(set(plan['source_reference_panels']) == {*PANELS,'training168'}, 'All632 trained N10 saved parent references required')
    require(type(plan['expected_loaded_owner_count']) is int and plan['expected_loaded_owner_count']==15, 'Actual inert-bootstrap15 loaded owners required')
    require(len(plan['source_owner_pins']) == 39, 'Closed retained38 plus one conditions-balanced producer required')
    required = [plan[k] for k in ('data_export', 'fresh_source_export', 'source_checkpoint', 'evaluation_contract', 'proposal')]
    for pair in plan['source_reference_panels'].values():
        require(type(pair) is dict and set(pair) == {'raw', 'joint'}, 'Closed saved parent reference pair required')
        required += list(pair.values())
    for descriptor in required:
        require(set(descriptor) == {'path', 'bytes', 'sha256'} and plan['artifacts'].get(descriptor['path']) ==
                {k: descriptor[k] for k in ('bytes', 'sha256')}, 'Exact input absent from admitted closure')
    require(not set(plan['artifacts']) & set(plan['forbidden_reference_paths']), 'Reference labels in admitted closure')
    require(str(F.parent / 'legal-temporal-attention-20261013-01' / 'fresh-reference-packet-v01.json') in plan['forbidden_reference_paths']
            and str(F.parent / 'legal-temporal-attention-20261013-01' / 'build_fresh_authored_temporal_reference_v02.py') in plan['forbidden_reference_paths']
            and str(F.parent / 'legal-temporal-attention-20261013-01' / 'fresh-reference-independent-review-v01.json') in plan['forbidden_reference_paths'],
            'Parent-only fresh reference material must be denied')
    require({str(F / name) for name in ('diagnose_conditions_balanced_oracle_v01.py','conditions-balanced-oracle-diagnostic-v01.json','parent-conditions-balanced-baseline-v01.json')} <= set(plan['forbidden_reference_paths']), 'Gold-dependent N12 oracle artifacts must be denied')
    require({str(F/name) for name in ('capacity-clearance-v01.json','capacity-clearance-inputs-v01.json','capacity-clearance-source-independent-review-v01.json','review_conditions_balanced_capacity_clearance_v01.py')} <= set(plan['artifacts']), 'Exact capacity clearance receipt and qualified producer closure required')
    for path in (plan['runner_path'], plan['guardian_path'], str(LEGACY_RUNNER),str(F/'conditions_balanced_resource_protocol_v01.py')):
        require(path in plan['artifacts'], 'Admitted producer missing')


def resource_protocol():
    path=F/'conditions_balanced_resource_protocol_v01.py'
    spec=importlib.util.spec_from_file_location('conditions_balanced_execution_protocol',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def qualify_capacity_clearance(clearance,*,for_training):
    return resource_protocol().qualify_capacity_clearance(clearance,for_training=for_training)


def validate_sources(plan, old, fresh, helper, legacy):
    rows = legacy.validate_data(plan, old, helper)
    require(type(fresh) is dict and set(fresh) == {'schema', 'populations', 'semantic_gold'}
            and fresh['schema'] == 'temporal-attention-fresh-source-export/v1' and fresh['semantic_gold'] is False
            and set(fresh['populations']) == set(FRESH_PANELS), 'Target-stripped fresh export required')
    seen_ids = {row['id'] for row in rows}
    seen_texts = {row['source_text'] for row in rows}
    for panel in OLD_PANELS:
        for row in old['diagnostic_sources'][panel]:
            require(row['id'] not in seen_ids and row['source_text'] not in seen_texts, 'Old source overlap')
            seen_ids.add(row['id']); seen_texts.add(row['source_text'])
    for panel in FRESH_PANELS:
        incoming = fresh['populations'][panel]
        require(type(incoming) is list and len(incoming) == 36, 'Exact fresh36 panel required')
        for row in incoming:
            require(type(row) is dict and set(row) == {'id', 'source_text', 'latent'} and type(row['id']) is str
                    and row['id'].strip() and type(row['source_text']) is str and 0 < len(row['source_text'].strip()) <= 16384,
                    'Fresh source must contain no references')
            require(row['latent'] == [0.] * 384 and type(row['latent']) is list and len(row['latent']) == 384
                    and all(type(v) in (int, float) and math.isfinite(v) for v in row['latent']), 'Dormant zero384 placeholders required')
            require(row['id'] not in seen_ids and row['source_text'] not in seen_texts, 'Fresh source overlap')
            seen_ids.add(row['id']); seen_texts.add(row['source_text'])
    require(len(seen_ids) == len(seen_texts) == 632, 'Exact632 distinct optimization/diagnostic sources required')
    return rows, {**old['diagnostic_sources'], **fresh['populations']}


def binary(value):
    if type(value) is list:
        return b''.join(binary(v) for v in value)
    if type(value) is dict:
        return b''.join(binary(value[k]) for k in sorted(value))
    require(type(value) in (int, float) and math.isfinite(value), 'Finite binary32 scores required')
    packed = struct.pack('!f', value)
    require(struct.unpack('!f', packed)[0] == value, 'Capture is not exact binary32')
    return packed


def merged_training_capture(module, torch, span, warm, checkpoint, rows):
    """Respect both exact128-row capture APIs without additional source forwards."""
    require(module.__name__.rsplit('.', 1)[-1] in {'legal_span_conditions_balanced'} and len(rows) == 168,
            'Only exact parent/candidate training168 uses this chunk path')
    chunks = [module.captured_inference(torch, span, warm, checkpoint, rows[:128]),
              module.captured_inference(torch, span, warm, checkpoint, rows[128:])]
    raw_counts = {'actual_source_forwards','source_model_forwards','frozen_actor_features_model_forwards',
        'frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards'}
    report_counts = set(raw_counts) - {'actual_source_forwards'}
    for chunk, count in zip(chunks, (128, 40), strict=True):
        require(all(type(chunk[k]) is int and chunk[k] == count for k in raw_counts)
                and all(type(chunk['inference'][k]) is int and chunk['inference'][k] == count for k in report_counts)
                and chunk['extra_capture_forwards'] == 0
                and len(chunk['occurrences']) == len(chunk['inference']['rows']) == count,
                'Exact complete training128/40 captures required')
    invariant = lambda c: {k: v for k, v in c.items() if k not in raw_counts | {'occurrences', 'inference'}}
    report_invariant = lambda c: {k: v for k, v in c['inference'].items()
                                  if k not in report_counts | {'rows', 'decoded_count', 'status'}}
    require(canonical(invariant(chunks[0])) == canonical(invariant(chunks[1]))
            and canonical(report_invariant(chunks[0])) == canonical(report_invariant(chunks[1])),
            'Training chunk producer, checkpoint, policy or branch identities differ')
    combined = dict(chunks[0]); report = dict(chunks[0]['inference'])
    combined['occurrences'] = chunks[0]['occurrences'] + chunks[1]['occurrences']
    report['rows'] = chunks[0]['inference']['rows'] + chunks[1]['inference']['rows']
    for key in raw_counts: combined[key] = sum(c[key] for c in chunks)
    for key in report_counts: report[key] = sum(c['inference'][key] for c in chunks)
    report['decoded_count'] = sum(row['status'] == 'decoded' for row in report['rows'])
    report['status'] = 'decoded' if report['decoded_count'] == 168 else 'partial' if report['decoded_count'] else 'abstained'
    combined['inference'] = report
    for source, occurrence, decoded in zip(rows, combined['occurrences'], report['rows'], strict=True):
        require(source['id'] == occurrence['id'] and occurrence['source_sha256'] == decoded['source_sha256']
                == hashlib.sha256(source['source_text'].encode()).hexdigest(), 'Training chunk source order or join differs')
    return combined


def capture(module, torch, span, warm, joint, checkpoint, rows, out, label):
    raw = (merged_training_capture(module, torch, span, warm, checkpoint, rows) if len(rows) > 128
           else module.captured_inference(torch, span, warm, checkpoint, rows))
    require(raw['actual_source_forwards'] == len(rows) and raw['extra_capture_forwards'] == 0
            and len(raw['occurrences']) == len(raw['inference']['rows']) == len(rows)
            and all(type(raw[key]) is int and raw[key] == len(rows)
                    for key in ('source_model_forwards','frozen_actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards')),
            'One complete source forward per capture required')
    raw_pin = write(out / (label + '-raw.json'), raw)
    selected = [dict(id=source['id'], result=joint.select_joint_spans(source['source_text'], item['scores'], top_k=8, max_search_nodes=50000))
                for source, item in zip(rows, raw['occurrences'], strict=True)]
    joint_pin = write(out / (label + '-joint.json'), dict(schema='conditions-balanced-joint-panel/v1', rows=selected,
        top_k=8, max_search_nodes=50000, reference_scoring_performed=False, **FALSE))
    return dict(raw=raw_pin, joint=joint_pin, row_count=len(rows))


def compare_captures(rows, before, after, *, full):
    a, b = read(before['raw']['path'], before['raw']), read(after['raw']['path'], after['raw'])
    require(len(a['occurrences']) == len(b['occurrences']) == len(rows), 'Complete captured source coverage required')
    aj, bj = (read(before['joint']['path'], before['joint'])['rows'], read(after['joint']['path'], after['joint'])['rows']) if full else (None, None)
    result = []
    for index, (source, x, y) in enumerate(zip(rows, a['occurrences'], b['occurrences'], strict=True)):
        source_sha = hashlib.sha256(source['source_text'].encode()).hexdigest()
        require(source['id'] == x['id'] == y['id'] and source_sha == x['source_sha256'] == y['source_sha256'], 'Source score join differs')
        xs, ys = x['scores'], y['scores']
        require(canonical(xs['tokens']) == canonical(ys['tokens']), 'Token boundaries differ')
        require(set(xs['presence_logits']) == set(ys['presence_logits']) == {'object', 'conditions', 'exceptions', 'temporal'},
                'Closed all-four presence scores required')
        left = {'modality_logits':xs['modality_logits'],'presence_logits':{k:v for k,v in xs['presence_logits'].items() if full or k!='conditions'}}
        right = {'modality_logits':ys['modality_logits'],'presence_logits':{k:v for k,v in ys['presence_logits'].items() if full or k!='conditions'}}
        for key in ('start_logits', 'end_logits'):
            require(set(xs[key]) == set(ys[key]) == {'actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'},
                    'Closed six-role pointer scores required')
            left[key] = dict(xs[key])
            right[key] = dict(ys[key])
        require(binary(left) == binary(right), 'Required binary32 head parity failed')
        if full:
            keys = ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')
            require({k: a['inference']['rows'][index].get(k) for k in keys} == {k: b['inference']['rows'][index].get(k) for k in keys}, 'Initial greedy parity failed')
            require(aj[index] == bj[index], 'Initial joint parity failed')
        result.append(dict(id=source['id'], source_sha256=source_sha, binary32_sha256=hashlib.sha256(binary(left)).hexdigest()))
    return result


def qualify_conditions_trace(report):
    names=['conditions_presence.weight','conditions_presence.bias']
    require(report['training_conditions_class_counts']==dict(absent=96,present=72),'Authenticated168 conditions classcounts96absent72present required')
    policy=report['training_policy'];objective=policy['objective_policy'];partition=report['parameter_partition']
    require(policy['objective']==CELL and objective==dict(conditions_pair_cross_entropy=True,mean_all_batch_rows=True,
        actor_ranking_enabled=False,training_row_reweighting=True,class_balance=dict(class_order=['absent','present'],counts=dict(absent=96,present=72),weights_rational=[[7,8],[7,6]],weights=[7/8,7/6],weight_rule='training_count/(2*class_count)',counts_source='authenticated_training168_conditions_presence_only',normalization='fixed_batch_row_count'),source_order='unchanged_targeted_seed1729_epoch_permutation',batch_order_seed=1729,batch_size=12)
        and policy['inherited_optimizer_moments'] is False and policy['optimizer']==dict(name='Adam',learning_rate=.001,betas=[.9,.999],eps=1e-8,weight_decay=0.,foreach=False,gradient_clip_norm=5.),
        'Exact freshAdam1729/12 classbalanced conditionspair meanCE withfixedbatch12, no hinge required')
    require(len(partition['model_parameter_names'])==42 and len(partition['frozen_parameter_names'])==40
        and partition['trainable_parameter_names']==partition['optimizer_parameter_order']==names
        and partition['stored_trainable_scalar_count']==520 and partition['active_trainable_scalar_count']==130
        and partition['inactive_stored_scalar_count']==390 and partition['active_head_rows']==[2,3]
        and partition['inactive_head_rows']==[0,1,4,5,6,7], 'Exact42/40/2 full8head520/130/390 geometry required')
    require(report['frozen_parent40_sha256_initial']==report['frozen_parent40_sha256_final']==SOURCE_STATE_SHA
        and report['inactive_head_rows_sha256_initial']==report['inactive_head_rows_sha256_final'], 'Parent40 or inactive390 values changed')
    batches=report['batch_trace']['batches'];require([b['optimizer_step'] for b in batches]==list(range(1,33)), 'Exact32 returned sequential updates required')
    for kind in ('objective','freeze'):
        trace=report[kind+'_trace'];require(trace['schema']=='completed-conditions-balanced-adapter-'+kind+'-trace/v1'
            and trace['completed_updates']==len(trace['batches'])==32 and trace['batches_sha256']==digest(trace['batches'])
            and trace['independent_numerical_kernel_trace'] is False
            and all(all(row[k]==batch[k] for k in ('optimizer_step','indices','ids')) for row,batch in zip(trace['batches'],batches,strict=True)), 'Closed32 completed traces must join actual returned batches')
    for entry,batch in zip(report['objective_trace']['batches'],batches,strict=True):
        d=entry['details'];require(d['total_loss']==d['conditions_cross_entropy_balanced']==batch['loss']
            and d['batch_denominator']==len(d['rows'])==len(batch['indices'])==len(batch['ids'])==12
            and d['teacher_forcing'] is True and d['evaluation_references_used'] is False and d['actor_hinge_applied'] is False,
            'Actual selectedconditions meanCE source batch loss join required')
        for row,index,identifier in zip(d['rows'],batch['indices'],batch['ids'],strict=True):
            require(row['id']==identifier and row['training_index']==index and type(row['conditions_present']) is bool
                and len(row['conditions_logits'])==2 and all(type(v) is float and math.isfinite(v) for v in row['conditions_logits'])
                and row['class_weight']==struct.unpack('!f',struct.pack('!f',7/6 if row['conditions_present'] else 7/8))[0]
                and all(type(row[k]) is float and math.isfinite(row[k]) and row[k]>=0 for k in ('unweighted_cross_entropy','weighted_cross_entropy'))
                and row['weighted_cross_entropy']==struct.unpack('!f',struct.pack('!f',row['unweighted_cross_entropy']*row['class_weight']))[0],
                'Actual authenticated conditions row/logits and fixedfloat32 classweights must join')
        counts=dict(absent=sum(not row['conditions_present'] for row in d['rows']),present=sum(row['conditions_present'] for row in d['rows']))
        require(d['batch_class_counts']==counts and all(type(d[k]) is float and math.isfinite(d[k]) and d[k]>=0 for k in ('conditions_cross_entropy_unweighted','conditions_cross_entropy_balanced','batch_weight_sum'))
            and abs(d['batch_weight_sum']-sum(row['class_weight'] for row in d['rows']))<=2e-6
            and abs(d['conditions_cross_entropy_balanced']-sum(row['weighted_cross_entropy'] for row in d['rows'])/12)<=2e-6*max(1.,d['conditions_cross_entropy_balanced']),
            'Balancedloss must dividebyfixed12, withweightsum diagnostic only')
    branch_keys={'modality_feature_state_sha256','span_feature_state_sha256','modality_path_state_sha256','span_path_state_sha256','dormant_latent_state_sha256','frozen_base34_state_sha256','actor_head_state_sha256','inactive_actor_head_rows_sha256','actor_attention_query_sha256','actor_context_gate_sha256','frozen_parent40_state_sha256','conditions_presence_state_sha256','inactive_conditions_presence_rows_sha256'}
    prior=report['training_call_initial_branch_digests'];require(prior==report['initial_branch_digests'] and set(prior)==branch_keys and all(type(v) is str and len(v)==64 and all(c in '0123456789abcdef' for c in v) for v in prior.values()),'Fresh32run must start at exact returned13 branches')
    for entry in report['freeze_trace']['batches']:
        before,after=entry['branch_digests_before'],entry['branch_digests_after']
        require(all(entry[k] is True for k in ('frozen_gradients_none','trainable_gradients_finite_nonNone','inactive_gradients_zero','inactive_moments_zero','completed_returned_update'))
            and entry['frozen_before']==entry['frozen_after']==SOURCE_STATE_SHA and entry['inactive_before']==entry['inactive_after']
            and len(entry['changed_parameter_names'])==len(set(entry['changed_parameter_names'])) and set(entry['changed_parameter_names'])<=set(names) and before==prior and set(before)==set(after)
            and all(before[k]==after[k] for k in before if k!='conditions_presence_state_sha256')
            and before['frozen_parent40_state_sha256']==SOURCE_STATE_SHA
            and before['inactive_conditions_presence_rows_sha256']==entry['inactive_before'], 'Parent40/inactive390 gradients moments values and branch chain must stay frozen')
        prior=after
    require(prior==report['final_branch_digests'],'Final returned branch chain differs')
    f=report['forward_accounting'];require(f['training_model_forward_calls']==f['training_frozen_actor_features_model_calls']==f['training_modality_encoder_calls']==f['training_conditions_presence_head_calls']==32
        and f['training_span_encoder_calls']==64 and f['training_source_row_occurrences']==384
        and all(value==32 for value in f['actual_model_counter_deltas'].values()),'Exact32 sourceforwards withthreefeaturepaths and384occurrences required')


def completion(report,checkpoint,schedule,rows):
    require(report['optimizer_steps']==32 and report['stopped_reason']=='step_limit' and checkpoint['progress']==schedule['final_progress']
        and report['checkpoint_sha256']==digest(checkpoint) and report['training_policy']==checkpoint['training_policy'], 'Complete32 returned checkpoint and policy required')
    trace=report['batch_trace'];require(trace['training_count']==168 and trace['training_manifest_sha256']==digest(rows)
        and [b['indices'] for b in trace['batches']]==schedule['batch_indices']
        and [b['ids'] for b in trace['batches']]==schedule['batch_ids'] and [b['loss'] for b in trace['batches']]==report['batch_losses'], 'Actual schedule/source manifest differs')
    qualify_conditions_trace(report)


def reused_parent_capture(plan,panel,out,label):
    pair=plan['source_reference_panels'][panel];result={}
    for view in ('raw','joint'):
        source=pair[view];target=out/(label+'-'+view+'.json');require(pin(source['path'])==source,'Exact frozen N10 parent capture required')
        with target.open('xb') as stream:stream.write(Path(source['path']).read_bytes());stream.flush();os.fsync(stream.fileno())
        copied=pin(target);require(all(copied[k]==source[k] for k in ('bytes','sha256')),'Reused saved parent bytes differ');result[view]=copied
    result['row_count']=168 if panel=='training168' else COUNTS[panel]
    return result


def main(args):
    started = time.monotonic()
    plan = read(Path(args.plan)); validate_plan(plan)
    protocol_path=F/'conditions_balanced_resource_protocol_v01.py'
    require({k:pin(protocol_path)[k] for k in ('bytes','sha256')}==plan['artifacts'][str(protocol_path)],'Exact admitted resource protocol source required before qualification')
    clearance_path=F/'capacity-clearance-v01.json'
    clearance=read(clearance_path,dict(path=str(clearance_path),**plan['artifacts'][str(clearance_path)]))
    baseline_pin=clearance['baseline'];require(plan['artifacts'].get(baseline_pin['path'])=={k:baseline_pin[k] for k in ('bytes','sha256')},'Exact qualified baseline must join admitted plan')
    baseline=read(baseline_pin['path'],baseline_pin)
    for proof,schema in ((baseline,'conditions-balanced-resource-observer-source-independent-review/v1'),
                         (clearance,'conditions-balanced-capacity-clearance-source-independent-review/v1')):
        gate_pin=proof['source_qualification'];observer_pin=proof['observer']
        require(all(plan['artifacts'].get(item['path'])=={k:item[k] for k in ('bytes','sha256')} for item in (gate_pin,observer_pin)),
            'Exact baseline/clearance observer and qualification must join admitted plan')
        gate=read(gate_pin['path'],gate_pin)
        require(gate['schema']==schema and gate['passed'] is True and gate['findings']==[] and gate['observer']==observer_pin,
            'Exact independent actual baseline/clearance observer qualification required')
        require(pin(observer_pin['path'])==observer_pin,'Qualified resource observer source drift')
        for path,approved in gate['artifacts'].items():
            require(plan['artifacts'].get(path)=={k:approved[k] for k in ('bytes','sha256')},'Resource observer approved closure must join admitted plan')
    resource_protocol().qualify_execution_baseline(baseline)
    qualify_capacity_clearance(clearance,for_training=True)
    out = Path(args.output)
    require(out.is_absolute() and out.resolve() == out and out == RUN_ROOT / ATTEMPT / 'results' and not out.exists(), 'Fresh guardian result directory required')
    forbidden = set(plan['forbidden_reference_paths'])
    def audit(event, values):
        if event.startswith(('subprocess.', 'os.exec', 'os.spawn', 'socket.')) or event in ('os.system', 'os.fork'):
            raise ValueError('Process/network denied in model child: ' + event)
        if event == 'open' and isinstance(values[0], (str, bytes)):
            target = Path(os.fsdecode(values[0])).absolute()
            require(str(target) not in forbidden, 'Reference-bearing parent artifact access denied')
            require(not target.is_relative_to(RUN_ROOT / 'actor-boundary-20261013-actor-boundary-ce-02' / 'results')
                    and not target.is_relative_to(RUN_ROOT / 'actor-ranking-20261013-actor-ranking-hinge-01' / 'results')
                    and not target.is_relative_to(RUN_ROOT / 'conditions-presence-20261014-conditions-presence-ce-01' / 'results'),
                    'Completed N8/N9/N11 control outputs forbidden until N12 freeze')
    sys.addaudithook(audit)
    for path, expected in plan['artifacts'].items():
        require({k: pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Opening admitted input drift')
    out.mkdir(mode=0o700); STATE['created_output'] = str(out)
    legacy = legacy_runner(); retained = legacy.prior_runner(); helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder()); helper.bootstrap(Path(plan['package_root']))
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    span = importlib.import_module(prefix + 'legal_span_formula')
    warm = importlib.import_module(prefix + 'legal_span_continuation')
    split = importlib.import_module(prefix + 'legal_span_split_features')
    actor = importlib.import_module(prefix + 'legal_span_conditions_balanced')
    joint = importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    opening_owners = retained.owner_origins(plan)
    required_owners = {prefix + name for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss',
                                                 'legal_span_split_features', 'legal_span_actor_boundary', 'legal_span_actor_features','legal_span_conditions_balanced')}
    require(len(opening_owners) == plan['expected_loaded_owner_count'] and required_owners <= set(opening_owners) <= set(plan['source_owner_pins'])
            and all(opening_owners[name] == plan['source_owner_pins'][name] for name in opening_owners),
            'Exact loaded source-owner subset including mandatory trainers required')
    old = read(plan['data_export']['path'], plan['data_export'])
    fresh = read(plan['fresh_source_export']['path'], plan['fresh_source_export'])
    rows, sources = validate_sources(plan, old, fresh, helper, legacy)
    schedule = retained.schedule(rows)
    schedule_pin = write(out / 'data-schedule-before-models.json', dict(schedule=schedule, training_count=168, model_imported=False, **FALSE))
    source = read(plan['source_checkpoint']['path'], plan['source_checkpoint'])
    require(digest(source) == SOURCE_SHA and digest(source['model_state']) == SOURCE_STATE_SHA, 'Parent canonical state digest differs')
    fix, queries = plan['ctypes_dl_resolution'], []
    for key in ('library_pin', 'ctypes_util_pin', 'cuda_pathfinder_pin'):
        require(pin(Path(fix[key]['path'])) == fix[key], 'Dynamic library input drift')
    with ExitStack() as stack:
        def find_dl(name):
            require(name == 'dl' and pin(Path(fix['library_pin']['path'])) == fix['library_pin'], 'Unlisted dynamic library resolution')
            queries.append(name); return fix['library_pin']['path']
        stack.enter_context(patch.object(ctypes.util, 'find_library', find_dl))
        import torch
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        require(str(torch.__version__) == '2.13.0+cu130' and span.audit_examples(rows)['all_supported'], 'Qualified runtime/training support drift')
        checkpoint = actor.build_checkpoint(source, rows, (), context_contract=plan['context_contract'])
        initial_sha, initial_state = digest(checkpoint), digest(checkpoint['model_state'])
        baseline = {name: capture(actor, torch, span, warm, joint, checkpoint, sources[name], out, 'baseline-' + name) for name in PANELS}
        initial_training = capture(actor, torch, span, warm, joint, checkpoint, rows, out, 'initial-training168')
        parent_extra={name:reused_parent_capture(plan,name,out,'parent-'+name) for name in FRESH_PANELS}
        parent_training=reused_parent_capture(plan,'training168',out,'parent-training168')
        initial_records={name:compare_captures(sources[name],plan['source_reference_panels'][name],baseline[name],full=True) for name in PANELS}
        initial_records['training168']=compare_captures(rows,plan['source_reference_panels']['training168'],initial_training,full=True)
        require(sum(map(len,initial_records.values()))==632,'All632 initial trainedN10 parent comparisons required before anyupdate')
        initial_gate = write(out / 'initial-parent-head-parity.json', dict(schema='conditions-balanced-initial-parent-parity/v1', source_rows=632,
            rows=initial_records, all_compared_components_bit_equal=True, optimizer_updates_before_gate=0, **FALSE))
        initial_dormant = actor.source_only_parity(torch, span, warm, checkpoint, sources['fresh_tune'], out, 'initial')
        STATE.update(stage='training', in_progress_updates_unknown=True)
        trained = actor.train_decoder(checkpoint, rows, (), max_steps=32, max_seconds=32)
        checkpoint, report = trained['checkpoint'], trained['report']
        STATE.update(completed_updates=report['optimizer_steps'], in_progress_updates_unknown=False)
        actor.save_checkpoint(checkpoint, out / 'cell-checkpoint.json')
        checkpoint_pin = pin(out / 'cell-checkpoint.json'); training_pin = write(out / 'cell-training.json', report)
        completion(report, checkpoint, schedule, rows)
        STATE['stage'] = 'diagnostics'
        trained_panels = {name: capture(actor, torch, span, warm, joint, checkpoint, sources[name], out, 'trained-' + name) for name in PANELS}
        trained_training = capture(actor, torch, span, warm, joint, checkpoint, rows, out, 'trained-training168')
        protected = {name: compare_captures(sources[name], baseline[name], trained_panels[name], full=False) for name in PANELS}
        protected['training168'] = compare_captures(rows, initial_training, trained_training, full=False)
        require(sum(map(len, protected.values())) == 632, 'All632 final protected-head comparisons required')
        final_gate = write(out / 'trained-frozen-head-retention.json', dict(schema='conditions-balanced-frozen-head-retention/v1', source_rows=632,
            rows=protected, all_compared_components_bit_equal=True, compared_all_boundaries=True,compared_conditions_presence=False,
            compared_other_three_presence=True,compared_modality=True, **FALSE))
        trained_dormant = actor.source_only_parity(torch, span, warm, checkpoint, sources['fresh_tune'], out, 'trained')
    for path, expected in plan['artifacts'].items():
        require({k: pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Closing admitted input drift')
    for mapping in (READ_PINS, legacy.READ_PINS):
        for path, expected in mapping.items():
            require(pin(Path(path)) == expected, 'Closing consumed raw input drift')
    require(report['forward_accounting']['training_model_forward_calls'] == 32
            and report['forward_accounting']['training_source_row_occurrences'] == 384
            and report['forward_accounting']['training_conditions_presence_head_calls']==32, 'Actual training counters differ')
    require(len([p for p in out.iterdir() if p.is_file()]) == 61, 'Exactly61 files before completed summary required')
    closing_owners = retained.owner_origins(plan)
    require(opening_owners == closing_owners, 'Loaded producer closure changed')
    write(out / 'summary.json', dict(schema='conditions-balanced-cell-results/v1', status='completed', cell=CELL, attempt_name=ATTEMPT,
        actual_new_updates=32,
        actual_external_encoder_calls=0, configured_dimension=384, latent_enabled=False, source_checkpoint=plan['source_checkpoint'],
        source_model_state_sha256=SOURCE_STATE_SHA, source_optimizer_steps=32, fresh_Adam=True, inherited_optimizer_moments=False,
        training_count=168, prepared_schedule=schedule, schedule=schedule_pin, checkpoint=checkpoint_pin, training=training_pin,
        initial_checkpoint_sha256=initial_sha, initial_model_state_sha256=initial_state, final_model_state_sha256=digest(checkpoint['model_state']),
        baseline_panels=baseline, diagnostics=trained_panels, parent_fresh_panels=parent_extra, parent_training_capture=parent_training,
        initial_training_capture=initial_training, final_training_capture=trained_training,
        initial_parent_head_parity=initial_gate, frozen_head_retention=final_gate, initial_parity=initial_dormant, trained_parity=trained_dormant,
        successful_output_file_count=62, candidate_diagnostic_source_forwards=928, candidate_training_capture_source_forwards=336, dormant_control_source_forwards=16,
        parent_extra_source_forwards=0,
        total_inference_source_forwards=1280, actual_training_model_forwards=32, total_actual_model_forwards=1312,
        candidate_conditions_presence_inference_calls=1280, actual_conditions_presence_head_calls=1312,
        reused_parent_capture_file_count=6,reused_parent_capture_rows=240,new_parent_control_forwards=0,
        reused_parent_captures={label:{view:plan['source_reference_panels'][panel][view] for view in ('raw','joint')} for label,panel in [('parent-training168','training168'),('parent-fresh_dev','fresh_dev'),('parent-fresh_test','fresh_test')]},
        candidate_training_capture_call_sizes=[128, 40], parent_training_capture_call_sizes=[128, 40],
        training_batch_source_occurrences=sum(map(len, schedule['batch_indices'])), total_model_source_occurrences=1664,
        feature_paths_per_source_forward=3, equal_compute_budget_claimed=False, exposed_engineering_diagnostics_only=True,
        reference_scoring_performed=False, diagnostic_reference_labels_in_child=False, initial_and_final_training_labels_scored_by_child=False,
        opening_owners=opening_owners, closing_owners=closing_owners, original_artifacts_byte_exact=True,
        elapsed_seconds=time.monotonic() - started, ctypes_dl_queries=queries, semantic_accuracy=None, independent_statutory_gold=False,
        checkpoint_selection_executed=False, default_promotion=False, Lake_executed=False, **FALSE))
    print(json.dumps(dict(status='completed', cell=CELL, candidate_updates=32)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True); parser.add_argument('--output', required=True)
    try:
        main(parser.parse_args())
    except Exception as error:
        if STATE['created_output']:
            write(Path(STATE['created_output']) / 'child-failure.json', dict(**STATE, error_type=type(error).__name__, detail=str(error), **FALSE))
        raise
