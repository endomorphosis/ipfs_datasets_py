"""One bounded actor-refinement CE head repair from the exact trained N11 parent.

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
CELL = 'actor-refinement-ce'
ATTEMPT = 'actor-refinement-20261014-' + CELL + '-01'
OLD_PANELS = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval', 'authored_dev', 'authored_eval', 'law')
FRESH_PANELS = ('fresh_dev', 'fresh_test')
PANELS = OLD_PANELS + FRESH_PANELS
COUNTS = dict(zip(PANELS, (96, 36, 36, 72, 72, 72, 8, 36, 36), strict=True))
SOURCE_SHA = '34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd'
SOURCE_STATE_SHA = 'b3b6fdb2eeb7653265930660d3a4eaae7b1a93db22b09e71a2276367c1b156a9'
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
    require(type(plan) is dict and set(plan) == PLAN_KEYS and plan['schema'] == 'actor-refinement-cell-plan/v1', 'Closed actor-refinement plan required')
    require(plan['package_root'] == str(F / 'datasets') and plan['runner_path'] == str(Path(__file__).resolve())
            and plan['guardian_path'] == str(F / 'run_scope_guardian_v02.py') and plan['cell'] == CELL
            and plan['attempt_name'] == ATTEMPT, 'Exact owned producers/attempt required')
    require(plan['source_checkpoint']['sha256'] == SOURCE_SHA and plan['source_checkpoint']['bytes'] == 9337558
            and plan['source_model_state_sha256'] == SOURCE_STATE_SHA, 'Exact trained N11 parent required')
    require(plan['legacy_prefix_sha256'] == '4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995', 'Legacy training prefix changed')
    require(plan['resource_contract'] == dict(cpu_slots=2, rss_mib=1536, child_slots=1, storage_bytes=200000000, deadline_seconds=300), 'Unchanged training envelope required')
    require(type(plan['training_seconds']) is int and plan['training_seconds'] == 32 and plan['configured_dimension'] == 384
            and plan['latent_enabled'] is False and plan['default_promotion'] is False and plan['Lake_executed'] is False,
            'Fixed source-only training recipe required')
    require(plan['diagnostic_panels'] == [dict(name=n, count=COUNTS[n]) for n in PANELS], 'All464 source diagnostics required')
    require(set(plan['source_reference_panels']) == {*PANELS,'training168'}, 'All632 trained N11 saved parent references required')
    require(type(plan['expected_loaded_owner_count']) is int and plan['expected_loaded_owner_count']==16, 'Actual inert-bootstrap16 loaded owners required')
    require(len(plan['source_owner_pins']) == 39, 'Closed retained38 plus one actor-refinement producer required')
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
    require({str(F / name) for name in ('diagnose_actor_refinement_oracle_v01.py','actor-refinement-oracle-diagnostic-v01.json','parent-actor-refinement-baseline-v01.json')} <= set(plan['forbidden_reference_paths']), 'Gold-dependent oracle artifacts must be denied')
    for path in (plan['runner_path'], plan['guardian_path'], str(LEGACY_RUNNER)):
        require(path in plan['artifacts'], 'Admitted producer missing')


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
    require(module.__name__.rsplit('.', 1)[-1] in {'legal_span_actor_refinement'} and len(rows) == 168,
            'Only exact parent/candidate training168 uses this chunk path')
    chunks = [module.captured_inference(torch, span, warm, checkpoint, rows[:128]),
              module.captured_inference(torch, span, warm, checkpoint, rows[128:])]
    raw_counts = {'actual_source_forwards','source_model_forwards','actor_features_model_forwards',
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
                    for key in ('source_model_forwards','actor_features_model_forwards','frozen_modality_encoder_forwards','frozen_span_encoder_forwards','additional_frozen_span_encoder_forwards','conditions_presence_head_forwards')),
            'One complete source forward per capture required')
    raw_pin = write(out / (label + '-raw.json'), raw)
    selected = [dict(id=source['id'], result=joint.select_joint_spans(source['source_text'], item['scores'], top_k=8, max_search_nodes=50000))
                for source, item in zip(rows, raw['occurrences'], strict=True)]
    joint_pin = write(out / (label + '-joint.json'), dict(schema='actor-refinement-joint-panel/v1', rows=selected,
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
        left = {'modality_logits':xs['modality_logits'],'presence_logits':dict(xs['presence_logits'])}
        right = {'modality_logits':ys['modality_logits'],'presence_logits':dict(ys['presence_logits'])}
        for key in ('start_logits', 'end_logits'):
            require(set(xs[key]) == set(ys[key]) == {'actor', 'action', 'object', 'conditions', 'exceptions', 'temporal'},
                    'Closed six-role pointer scores required')
            left[key] = {k:v for k,v in xs[key].items() if full or k!='actor'}
            right[key] = {k:v for k,v in ys[key].items() if full or k!='actor'}
        require(binary(left) == binary(right), 'Required binary32 head parity failed')
        if full:
            keys = ('status', 'reason', 'canonical_ir', 'span_diagnostics', 'minimum_decision_logit_margin')
            require({k: a['inference']['rows'][index].get(k) for k in keys} == {k: b['inference']['rows'][index].get(k) for k in keys}, 'Initial greedy parity failed')
            require(aj[index] == bj[index], 'Initial joint parity failed')
        result.append(dict(id=source['id'], source_sha256=source_sha, binary32_sha256=hashlib.sha256(binary(left)).hexdigest()))
    return result


def qualify_actor_trace(report):
    actor = importlib.import_module('ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_actor_refinement')
    names = list(actor.TRAINABLE_PARAMETER_NAMES)
    policy = report['training_policy']
    actor._validate_policy(policy)
    require(policy['objective'] == CELL and report['parameter_partition'] == actor._partition()
            and report['optimizer_parameter_order'] == names and len(names) == 6
            and report['stored_trainable_scalar_count'] == 908 and report['active_trainable_scalar_count'] == 258,
            'Exact actor6/258 active/650 inactive and frozen36 policy required')
    require(report['source_conditions_presence_checkpoint_sha256'] == SOURCE_SHA
            and report['source_conditions_presence_model_state_sha256'] == SOURCE_STATE_SHA
            and report['source_conditions_presence_optimizer_steps'] == 32
            and report['training_call_initial_model_state_sha256'] == report['initial_model_state_sha256'] == SOURCE_STATE_SHA
            and report['continuation_optimizer_steps_total'] == 32,
            'Continuation must start at all42 trained N11 tensors with fresh32 updates')
    expected = report['source_frozen36_state_sha256']
    require(report['frozen_parent36_sha256_initial'] == report['frozen_parent36_sha256_final']
            == report['frozen_parameters_sha256_initial'] == report['frozen_parameters_sha256_final'] == expected
            and report['inactive_head_rows_sha256_initial'] == report['inactive_head_rows_sha256_final'],
            'Frozen36 and inactive650 identities differ')
    batches = report['batch_trace']['batches']
    require(len(batches) == 32 and [b['optimizer_step'] for b in batches] == list(range(1, 33)),
            'Exactly32 sequential returned updates required')
    for kind in ('objective', 'freeze', 'feature'):
        trace = report[kind + '_trace']
        require(trace['schema'] == 'completed-actor-refinement-adapter-' + kind + '-trace/v1'
                and trace['completed_updates'] == len(trace['batches']) == 32
                and trace['batches_sha256'] == digest(trace['batches'])
                and trace['independent_numerical_kernel_trace'] is False,
                'Closed32 completed trace required')
    require(report['objective_trace']['evaluation_references_used'] is False,
            'Evaluation references cannot enter training')
    prior = report['training_call_initial_branch_digests']
    require(prior == report['initial_branch_digests'] and prior['frozen_nonactor36_state_sha256'] == expected,
            'Exact initial donor branch identities required')
    for batch, objective, freeze, feature in zip(batches, report['objective_trace']['batches'],
            report['freeze_trace']['batches'], report['feature_trace']['batches'], strict=True):
        actor._validate_objective_entry(objective, batch, policy)
        actor._validate_freeze_entry(freeze, batch)
        actor._validate_feature_entry(feature, batch)
        require(len(batch['indices']) == len(batch['ids']) == 12
                and freeze['source_frozen36_state_sha256'] == expected
                and freeze['branch_digests_before'] == prior,
                'Actual12-row completed batch and frozen branch chain differ')
        before, after = freeze['branch_digests_before'], freeze['branch_digests_after']
        for label, branch in (('query', 'actor_attention_query_sha256'), ('gate', 'actor_context_gate_sha256')):
            require(feature[label + '_before_sha256'] == before[branch]
                    and feature[label + '_after_sha256'] == after[branch], 'Feature/freeze branch joins differ')
        prior = after
    require(prior == report['final_branch_digests']
            and len(report['changed_parameter_names']) == len(set(report['changed_parameter_names']))
            and set(report['changed_parameter_names']) <= set(names), 'Final returned branch chain differs')
    features = report['feature_trace']['batches']
    learning = dict(query_changed_updates=sum(e['query_changed'] for e in features),
        gate_changed_updates=sum(e['gate_changed'] for e in features))
    learning.update({label + '_nonzero_gradient_updates':sum(not e[label + '_gradient_exact_zero'] for e in features)
                     for label in ('query', 'gate', 'context', 'residual')})
    require(report['feature_learning'] == learning, 'Feature learning aggregate differs')
    f = report['forward_accounting']
    require(f['training_model_forward_calls'] == f['training_actor_features_model_calls']
            == f['training_modality_encoder_calls'] == f['training_conditions_presence_head_calls'] == 32
            and f['training_span_encoder_calls'] == 64 and f['training_source_row_occurrences'] == 384
            and len(f['actual_model_counter_deltas']) == 6
            and all(type(value) is int and value == 32 for value in f['actual_model_counter_deltas'].values())
            and f['tuning_model_forward_calls'] == f['teacher_model_forward_calls'] == 0,
            'Exact32 training forwards/384 occurrences/three feature paths required')


def completion(report,checkpoint,schedule,rows):
    require(report['optimizer_steps']==32 and report['stopped_reason']=='step_limit' and checkpoint['progress']==schedule['final_progress']
        and report['checkpoint_sha256']==digest(checkpoint) and report['training_policy']==checkpoint['training_policy'], 'Complete32 returned checkpoint and policy required')
    trace=report['batch_trace'];require(trace['training_count']==168 and trace['training_manifest_sha256']==digest(rows)
        and [b['indices'] for b in trace['batches']]==schedule['batch_indices']
        and [b['ids'] for b in trace['batches']]==schedule['batch_ids'] and [b['loss'] for b in trace['batches']]==report['batch_losses'], 'Actual schedule/source manifest differs')
    require(report['source_frozen36_state_sha256'] == checkpoint['source_frozen36_state_sha256'],
            'Report frozen subset must join validated checkpoint source subset')
    qualify_actor_trace(report)


def reused_parent_capture(plan,panel,out,label):
    pair=plan['source_reference_panels'][panel];result={}
    for view in ('raw','joint'):
        source=pair[view];target=out/(label+'-'+view+'.json');require(pin(source['path'])==source,'Exact frozen N11 parent capture required')
        with target.open('xb') as stream:stream.write(Path(source['path']).read_bytes());stream.flush();os.fsync(stream.fileno())
        copied=pin(target);require(all(copied[k]==source[k] for k in ('bytes','sha256')),'Reused saved parent bytes differ');result[view]=copied
    result['row_count']=168 if panel=='training168' else COUNTS[panel]
    return result


def qualify_resource_baseline(plan):
    protocol_path = F / 'actor_refinement_resource_protocol_v01.py'
    baseline_path = F / 'resource-baseline-v01.json'
    for path in (protocol_path, baseline_path):
        require(plan['artifacts'].get(str(path)) == {k: pin(path)[k] for k in ('bytes', 'sha256')},
                'Actual baseline/protocol must join admitted raw closure')
    specification = importlib.util.spec_from_file_location('qualified_actor_refinement_resource_guard', protocol_path)
    protocol = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(protocol)
    baseline = read(baseline_path, pin(baseline_path))
    ledger = protocol.qualify_baseline(baseline)
    qualification = baseline['source_qualification']
    require(plan['artifacts'].get(qualification['path']) == {k: qualification[k] for k in ('bytes', 'sha256')},
            'Actual independent resource gate must join admitted closure')
    gate = read(qualification['path'], qualification)
    require(gate['schema'] == 'actor-refinement-resource-observer-source-independent-review/v1'
            and gate['passed'] is True and gate['findings'] == [] and gate['observer'] == baseline['observer'],
            'Exact independently qualified observer required')
    for mapping in (baseline['artifacts'], gate['artifacts']):
        for path, item in mapping.items():
            wanted = {k: item[k] for k in ('bytes', 'sha256')}
            require(plan['artifacts'].get(path) == wanted
                    and {k: pin(Path(path))[k] for k in ('bytes', 'sha256')} == wanted,
                    'Complete public baseline/source qualification must be raw-admitted')
    return ledger


def main(args):
    started = time.monotonic()
    plan = read(Path(args.plan)); validate_plan(plan)
    out = Path(args.output)
    require(out.is_absolute() and out.resolve() == out and out == RUN_ROOT / ATTEMPT / 'results' and not out.exists(), 'Fresh guardian result directory required')
    forbidden = set(plan['forbidden_reference_paths'])
    def audit(event, values):
        if event.startswith(('subprocess.', 'os.exec', 'os.spawn', 'socket.')) or event in ('os.system', 'os.fork'):
            raise ValueError('Process/network denied in model child: ' + event)
        if event == 'open' and isinstance(values[0], (str, bytes)):
            target = Path(os.fsdecode(values[0])).absolute()
            require(str(target) not in forbidden, 'Reference-bearing parent artifact access denied')
            require('private-runtime-snapshots' not in target.parts and 'private-root-identity-rebind-v01' not in target.parts
                    and target.name not in {'disk-reservations.json','resources-start.json','resources-final.json','ipfs-datasets-resource-scheduler-1000.json'},
                    'Private/global resource bodies denied in model child')
            require(not target.is_relative_to(RUN_ROOT / 'actor-boundary-20261013-actor-boundary-ce-02' / 'results')
                    and not target.is_relative_to(RUN_ROOT / 'actor-ranking-20261013-actor-ranking-hinge-01' / 'results'),
                    'Completed N8/N9 control outputs forbidden until N11 freeze')
    sys.addaudithook(audit)
    for path, expected in plan['artifacts'].items():
        require({k: pin(Path(path))[k] for k in ('bytes', 'sha256')} == expected, 'Opening admitted input drift')
    qualify_resource_baseline(plan)
    out.mkdir(mode=0o700); STATE['created_output'] = str(out)
    legacy = legacy_runner(); retained = legacy.prior_runner(); helper = retained.helpers()
    sys.meta_path.insert(0, helper.NoEncoder()); helper.bootstrap(Path(plan['package_root']))
    prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    span = importlib.import_module(prefix + 'legal_span_formula')
    warm = importlib.import_module(prefix + 'legal_span_continuation')
    split = importlib.import_module(prefix + 'legal_span_split_features')
    actor = importlib.import_module(prefix + 'legal_span_actor_refinement')
    joint = importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    opening_owners = retained.owner_origins(plan)
    required_owners = {prefix + name for name in ('legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss',
                                                 'legal_span_split_features', 'legal_span_actor_boundary', 'legal_span_actor_features','legal_span_conditions_presence','legal_span_actor_refinement')}
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
        require(sum(map(len,initial_records.values()))==632,'All632 initial trainedN11 parent comparisons required before anyupdate')
        initial_gate = write(out / 'initial-parent-head-parity.json', dict(schema='actor-refinement-initial-parent-parity/v1', source_rows=632,
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
        final_gate = write(out / 'trained-frozen-head-retention.json', dict(schema='actor-refinement-frozen-head-retention/v1', source_rows=632,
            rows=protected, all_compared_components_bit_equal=True, compared_all_boundaries=False,compared_conditions_presence=True,compared_nonactor_boundaries=True,compared_actor_boundaries=False,
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
    write(out / 'summary.json', dict(schema='actor-refinement-cell-results/v1', status='completed', cell=CELL, attempt_name=ATTEMPT,
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
