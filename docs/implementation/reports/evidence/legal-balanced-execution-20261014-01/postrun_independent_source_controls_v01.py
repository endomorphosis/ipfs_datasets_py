"""Detached AST predicates and synthetic traces only; no production imports or main."""
import ast
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
from types import SimpleNamespace

F = Path(__file__).resolve().parent
N12 = F.parent / 'legal-conditions-recall-20261014-01'
N13 = F.parent / 'legal-storage-continuation-20261014-01'


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pin(path):
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def extract(path, names, namespace):
    tree = ast.parse(path.read_bytes())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes} == set(names), 'exact detached function inventory')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def f32(value):
    return struct.unpack('!f', struct.pack('!f', value))[0]


cases = []


def case(name, fn, accepted):
    try:
        fn()
        result = True
    except (ValueError, KeyError, AssertionError):
        result = False
    require(result == accepted, name)
    cases.append(dict(name=name, passed=True, expected_acceptance=accepted))


runner_path = F / 'run_conditions_balanced_v01.py'
freezer_path = F / 'freeze_conditions_balanced_outputs_v01.py'
terminal_path = F / 'audit_conditions_balanced_terminal_resources_v01.py'
source_sha = 'b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3'
state_sha = 'c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab'
cell = 'conditions-balanced-ce'
attempt = 'conditions-balanced-20261014-' + cell + '-01'
panels = ('old_tune', 'fresh_tune', 'fresh_challenge', 'old_authored_eval',
          'authored_dev', 'authored_eval', 'law', 'fresh_dev', 'fresh_test')
counts = dict(zip(panels, (96, 36, 36, 72, 72, 72, 8, 36, 36), strict=True))
ns = extract(runner_path, {'qualify_conditions_trace'},
             dict(require=require, digest=digest, math=math, struct=struct,
                  CELL=cell, SOURCE_STATE_SHA=state_sha))
r = SimpleNamespace(require=require, qualify_conditions_trace=ns['qualify_conditions_trace'],
                    CELL=cell, ATTEMPT=attempt, SOURCE_SHA=source_sha,
                    SOURCE_STATE_SHA=state_sha, PANELS=panels, COUNTS=counts)
fns = extract(freezer_path, {'expected_names', 'qualify_training_summary', 'qualify_gates'}, dict(r=r))
case('exact flat62 inventory', lambda: require(len(fns['expected_names']()) == 62, '62'), True)
case('freezer exact reviewed F13 bytes', lambda: require(freezer_path.read_bytes() ==
     (N13 / 'freeze_conditions_balanced_outputs_draft_v01.py').read_bytes(), 'byte parity'), True)

names = ['conditions_presence.weight', 'conditions_presence.bias']
branch_keys = {'modality_feature_state_sha256', 'span_feature_state_sha256',
    'modality_path_state_sha256', 'span_path_state_sha256', 'dormant_latent_state_sha256',
    'frozen_base34_state_sha256', 'actor_head_state_sha256', 'inactive_actor_head_rows_sha256',
    'actor_attention_query_sha256', 'actor_context_gate_sha256', 'frozen_parent40_state_sha256',
    'conditions_presence_state_sha256', 'inactive_conditions_presence_rows_sha256'}
branches = dict.fromkeys(branch_keys, '1' * 64)
branches['frozen_parent40_state_sha256'] = state_sha
inactive = branches['inactive_conditions_presence_rows_sha256']
objective = dict(conditions_pair_cross_entropy=True, mean_all_batch_rows=True,
    actor_ranking_enabled=False, training_row_reweighting=True,
    class_balance=dict(class_order=['absent', 'present'], counts=dict(absent=96, present=72),
        weights_rational=[[7, 8], [7, 6]], weights=[7/8, 7/6],
        weight_rule='training_count/(2*class_count)',
        counts_source='authenticated_training168_conditions_presence_only',
        normalization='fixed_batch_row_count'),
    source_order='unchanged_targeted_seed1729_epoch_permutation', batch_order_seed=1729,
    batch_size=12)
policy = dict(objective=cell, objective_policy=objective, inherited_optimizer_moments=False,
    optimizer=dict(name='Adam', learning_rate=.001, betas=[.9, .999], eps=1e-8,
                   weight_decay=0., foreach=False, gradient_clip_norm=5.))
partition = dict(model_parameter_names=names + ['frozen' + str(i) for i in range(40)],
    frozen_parameter_names=['frozen' + str(i) for i in range(40)],
    trainable_parameter_names=names, optimizer_parameter_order=names,
    stored_trainable_scalar_count=520, active_trainable_scalar_count=130,
    inactive_stored_scalar_count=390, active_head_rows=[2, 3],
    inactive_head_rows=[0, 1, 4, 5, 6, 7])
batches, objectives, freezes = [], [], []
for step in range(1, 33):
    indices = list(range(12))
    identifiers = ['synthetic-' + str(i) for i in indices]
    rows = [dict(id=identifier, training_index=i, conditions_present=bool(i % 2),
        conditions_logits=[0., 0.], class_weight=f32(7/6 if i % 2 else 7/8),
        unweighted_cross_entropy=.5,
        weighted_cross_entropy=f32(.5 * f32(7/6 if i % 2 else 7/8)))
        for i, identifier in zip(indices, identifiers, strict=True)]
    loss = sum(row['weighted_cross_entropy'] for row in rows) / 12
    batch = dict(optimizer_step=step, indices=indices, ids=identifiers, loss=loss)
    batches.append(batch)
    details = dict(total_loss=loss, conditions_cross_entropy_balanced=loss,
        conditions_cross_entropy_unweighted=.5, batch_denominator=12, rows=rows,
        teacher_forcing=True, evaluation_references_used=False, actor_hinge_applied=False,
        batch_class_counts=dict(absent=6, present=6),
        batch_weight_sum=sum(row['class_weight'] for row in rows))
    objectives.append(dict(optimizer_step=step, indices=indices, ids=identifiers, details=details))
    freezes.append(dict(optimizer_step=step, indices=indices, ids=identifiers,
        frozen_gradients_none=True, trainable_gradients_finite_nonNone=True,
        inactive_gradients_zero=True, inactive_moments_zero=True, completed_returned_update=True,
        frozen_before=state_sha, frozen_after=state_sha, inactive_before=inactive,
        inactive_after=inactive, changed_parameter_names=names,
        branch_digests_before=branches.copy(), branch_digests_after=branches.copy()))
report = dict(schema='bounded-conditions-balanced-adapter-training/v1',
    optimizer_steps=32, stopped_reason='step_limit', training_policy=policy,
    training_conditions_class_counts=dict(absent=96, present=72), parameter_partition=partition,
    frozen_parent40_sha256_initial=state_sha, frozen_parent40_sha256_final=state_sha,
    inactive_head_rows_sha256_initial=inactive, inactive_head_rows_sha256_final=inactive,
    batch_trace=dict(completed_updates=32, training_count=168,
        training_manifest_sha256='2' * 64, batches=batches), batch_losses=[b['loss'] for b in batches],
    optimizer_parameter_order=names, checkpoint_sha256='3' * 64,
    final_model_state_sha256='4' * 64, source_actor_features_checkpoint_sha256=source_sha,
    source_actor_features_model_state_sha256=state_sha, source_actor_features_optimizer_steps=32,
    training_call_initial_branch_digests=branches.copy(), initial_branch_digests=branches.copy(),
    final_branch_digests=branches.copy(),
    forward_accounting=dict(training_model_forward_calls=32,
        training_frozen_actor_features_model_calls=32, training_modality_encoder_calls=32,
        training_conditions_presence_head_calls=32, training_span_encoder_calls=64,
        training_source_row_occurrences=384, actual_model_counter_deltas={'a': 32, 'b': 32}))
for kind, values in [('objective', objectives), ('freeze', freezes)]:
    report[kind + '_trace'] = dict(schema='completed-conditions-balanced-adapter-' + kind + '-trace/v1',
        completed_updates=32, batches=values, batches_sha256=digest(values),
        independent_numerical_kernel_trace=False)
case('complete synthetic32 weighted trace accepted', lambda: ns['qualify_conditions_trace'](report), True)


def bad_trace(name, modify):
    bad = copy.deepcopy(report)
    modify(bad)
    for kind in ('objective', 'freeze'):
        bad[kind + '_trace']['batches_sha256'] = digest(bad[kind + '_trace']['batches'])
    case(name, lambda: ns['qualify_conditions_trace'](bad), False)


bad_trace('130 active scalar tamper refused', lambda d: d['parameter_partition'].update(active_trainable_scalar_count=129))
bad_trace('40 frozen tensor tamper refused', lambda d: d['parameter_partition']['frozen_parameter_names'].pop())
bad_trace('nonzero inactive gradients refused', lambda d: d['freeze_trace']['batches'][0].update(inactive_gradients_zero=False))
bad_trace('nonzero inactive Adam moments refused', lambda d: d['freeze_trace']['batches'][0].update(inactive_moments_zero=False))
bad_trace('frozen parent digest drift refused', lambda d: d.update(frozen_parent40_sha256_final='5' * 64))
bad_trace('protected branch chain drift refused', lambda d: d['freeze_trace']['batches'][0]['branch_digests_after'].update(actor_head_state_sha256='5' * 64))
bad_trace('weighted sum denominator refused', lambda d: d['objective_trace']['batches'][0]['details'].update(batch_denominator=11))
bad_trace('class weight tamper refused', lambda d: d['objective_trace']['batches'][0]['details']['rows'][0].update(class_weight=1.))
bad_trace('actor ranking activation refused', lambda d: d['training_policy']['objective_policy'].update(actor_ranking_enabled=True))
bad_trace('31 actual returned forwards refused', lambda d: d['forward_accounting'].update(training_model_forward_calls=31))

prefix = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
required = ['legal_span_formula', 'legal_span_continuation', 'legal_span_targeted_loss',
            'legal_span_split_features', 'legal_span_actor_boundary', 'legal_span_actor_features',
            'legal_span_conditions_balanced']
owners = {prefix + name: dict(path='/synthetic/' + name, bytes=1, sha256='6' * 64) for name in required}
owners.update({'synthetic.owner.' + str(i): dict(path='/synthetic/extra' + str(i), bytes=1,
               sha256='6' * 64) for i in range(8)})
plan = dict(expected_loaded_owner_count=15, source_owner_pins=owners,
            training_manifest_sha256='2' * 64, source_reference_panels={p: {'synthetic': p}
            for p in ('training168', 'fresh_dev', 'fresh_test')})
summary = dict(schema='conditions-balanced-cell-results/v1', status='completed', cell=cell,
    attempt_name=attempt, actual_new_updates=32, successful_output_file_count=62,
    actual_external_encoder_calls=0, latent_enabled=False, opening_owners=owners,
    closing_owners=copy.deepcopy(owners), checkpoint=dict(sha256='3' * 64),
    final_model_state_sha256='4' * 64, source_checkpoint=dict(sha256=source_sha),
    source_model_state_sha256=state_sha, source_optimizer_steps=32, fresh_Adam=True,
    inherited_optimizer_moments=False, candidate_training_capture_call_sizes=[128, 40],
    parent_training_capture_call_sizes=[128, 40], prepared_schedule=dict(
        batch_indices=[b['indices'] for b in batches], batch_ids=[b['ids'] for b in batches]),
    reused_parent_captures={label: plan['source_reference_panels'][p] for label, p in
        [('parent-training168', 'training168'), ('parent-fresh_dev', 'fresh_dev'),
         ('parent-fresh_test', 'fresh_test')]})
summary.update(total_inference_source_forwards=1280, actual_training_model_forwards=32,
    total_actual_model_forwards=1312, training_batch_source_occurrences=384,
    total_model_source_occurrences=1664, candidate_conditions_presence_inference_calls=1280,
    actual_conditions_presence_head_calls=1312, reused_parent_capture_file_count=6,
    reused_parent_capture_rows=240, new_parent_control_forwards=0,
    candidate_diagnostic_source_forwards=928, candidate_training_capture_source_forwards=336,
    dormant_control_source_forwards=16, parent_extra_source_forwards=0, feature_paths_per_source_forward=3)
case('complete synthetic runtime summary and actual trace validator accepted',
     lambda: fns['qualify_training_summary'](plan, summary, report), True)
for key, value in [('total_actual_model_forwards', 1552), ('reused_parent_capture_rows', 239),
                   ('new_parent_control_forwards', 1), ('candidate_training_capture_call_sizes', [168])]:
    bad = copy.deepcopy(summary); bad[key] = value
    case('summary ' + key + ' tamper refused',
         lambda bad=bad: fns['qualify_training_summary'](plan, bad, report), False)
bad = copy.deepcopy(summary); bad['closing_owners'][prefix + required[0]]['sha256'] = '7' * 64
case('loaded owner source drift refused', lambda: fns['qualify_training_summary'](plan, bad, report), False)
initial = dict(schema='conditions-balanced-initial-parent-parity/v1', source_rows=632,
    all_compared_components_bit_equal=True, optimizer_updates_before_gate=0,
    rows={p: [{}] * n for p, n in dict(counts, training168=168).items()})
final = dict(schema='conditions-balanced-frozen-head-retention/v1', source_rows=632,
    all_compared_components_bit_equal=True, compared_all_boundaries=True,
    compared_conditions_presence=False, compared_other_three_presence=True, compared_modality=True,
    rows=copy.deepcopy(initial['rows']))
case('all632 initial and protected final rows accepted', lambda: fns['qualify_gates'](initial, final), True)
bad = copy.deepcopy(final); bad['rows']['training168'].pop()
case('partial631 parity coverage refused', lambda: fns['qualify_gates'](initial, bad), False)
bad = copy.deepcopy(final); bad['compared_modality'] = False
case('unprotected modality refused', lambda: fns['qualify_gates'](initial, bad), False)

contract = json.loads((F / 'resource-protocol-contract-v01.json').read_bytes())
tns = extract(terminal_path, {'qualify_public_custody'}, dict(p=SimpleNamespace(require=require), F=F, Path=Path))
producers = {label: dict(path=str(F / filename), bytes=1, sha256='8' * 64)
             for label, filename in [('runner', 'run_conditions_balanced_v01.py'), ('guardian', 'run_scope_guardian_v02.py')]}
pp = dict(path=str(F / 'conditions-balanced-ce-plan-v01.json'), bytes=1, sha256='9' * 64)
rp = dict(path=str(F / 'conditions-balanced-ce-training-review-v01.json'), bytes=1, sha256='a' * 64)
cp = dict(schema='conditions-balanced-cell-plan/v1', cell=contract['cell'],
    attempt_name=contract['attempt_name'], package_root=str(F / 'datasets'),
    runner_path=producers['runner']['path'], guardian_path=producers['guardian']['path'],
    artifacts={v['path']: {k: v[k] for k in ('bytes', 'sha256')} for v in producers.values()})
review = dict(schema=contract['review_schema'], passed=True, findings=[], phase='training',
    plan_sha256=pp['sha256'], package_root=cp['package_root'], run_root=contract['run_root'],
    artifacts={pp['path']: pp}, runner_sha256=producers['runner']['sha256'],
    guardian_sha256=producers['guardian']['sha256'])
wrappers = {'pre-admission.json': dict(plan=pp, review=rp, runner=producers['runner'], guardian=producers['guardian']),
    'command.json': dict(argv=['/synthetic/python', str(F / 'run_conditions_balanced_v01.py'),
        '--plan', pp['path'], '--output', str(Path(contract['run_root']) / contract['attempt_name'] / 'results')],
        cwd=cp['package_root'], candidate_pythonpath=cp['package_root'], resources=contract['resources'],
        no_cuda=True, no_proof_workers=True, model_authority=False)}
case('synthetic terminal public plan review wrapper joins accepted',
     lambda: tns['qualify_public_custody'](contract, cp, review, pp, rp, producers, wrappers), True)
bad = copy.deepcopy(review); bad['plan_sha256'] = 'b' * 64
case('terminal training review plan drift refused',
     lambda: tns['qualify_public_custody'](contract, cp, bad, pp, rp, producers, wrappers), False)
bad = copy.deepcopy(wrappers); bad['command.json']['resources']['storage_bytes'] += 1
case('terminal resource envelope change refused',
     lambda: tns['qualify_public_custody'](contract, cp, review, pp, rp, producers, bad), False)
bad = copy.deepcopy(wrappers); bad['command.json']['argv'][-1] += '-foreign'
case('terminal foreign result command refused',
     lambda: tns['qualify_public_custody'](contract, cp, review, pp, rp, producers, bad), False)

old_tree = ast.parse((N12 / 'audit_conditions_balanced_terminal_resources_v01.py').read_bytes())
new_tree = ast.parse(terminal_path.read_bytes())
functions = lambda tree: {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
old_funcs, new_funcs = functions(old_tree), functions(new_tree)
case('terminal inherited helper extractor and public custody AST exact', lambda: require(
    all(new_funcs[k] == old_funcs[k] for k in ('retained_helpers', 'qualify_public_custody')), 'retained AST'), True)

result = dict(schema='conditions-balanced-postrun-independent-source-controls/v1', passed=True,
    findings=[], control_count=len(cases), cases=cases,
    freezer=pin(freezer_path), terminal=pin(terminal_path), runner=pin(runner_path),
    source=pin(Path(__file__).resolve()), actual_public_contract=pin(F / 'resource-protocol-contract-v01.json'),
    fixture_scope='Synthetic complete32 weighted trace/envelopes and pure public custody predicates; source AST extraction only. Inherited full ownclaim/lease/RSS kernels not re-executed. Does not prove numerical CE, actual results, runtime plan or future endpoint custody.',
    full_module_or_main_executions=0, production_or_numerical_imports=0,
    actual_reference_savedscore_checkpoint_or_private_body_reads=0,
    actual_census_or_resource_API_calls=0, claims_cleanup_or_Git_mutations=0)
output = F / 'postrun-independent-source-controls-v01.json'
with output.open('x') as stream:
    json.dump(result, stream, sort_keys=True, indent=2)
    stream.write('\n');stream.flush();os.fsync(stream.fileno())
output.chmod(0o444)
print(json.dumps(pin(output), sort_keys=True))
