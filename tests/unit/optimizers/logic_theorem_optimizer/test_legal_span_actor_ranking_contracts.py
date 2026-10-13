"""Actor ranking contracts using detached stdlib owners; numerical imports are forbidden."""
import ast
import builtins
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import random
import struct
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[4] / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_ranking.py'
SPLIT = SOURCE.with_name('legal_span_split_features.py')
PARENT = SOURCE.with_name('legal_span_actor_boundary.py')
TARGETED = SOURCE.with_name('legal_span_targeted_loss.py')
TARGETED_CONTROLS = Path(__file__).with_name('test_legal_span_targeted_loss_contracts.py')


def require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def deny_import(name, *args, **kwargs):
    raise AssertionError('Detached actor ranking contracts cannot import: ' + name)


def coordinates(value, count):
    require(type(value) in (list, tuple) and len(value) == 2
        and all(type(v) is int for v in value) and 0 <= value[0] <= value[1] < count, 'coordinates')
    return tuple(value)


def detached(path, names, namespace):
    """Run only named definitions; source imports and module bodies never run."""
    tree = ast.parse(path.read_bytes())
    selected = {node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names}
    require(set(selected) == set(names), 'exact detached definitions required')
    for node in selected.values():
        require(not node.decorator_list and not any(isinstance(child, (ast.Import, ast.ImportFrom))
            for child in ast.walk(node)), 'detached definitions cannot import')
    namespace['__builtins__'] = dict(vars(builtins), __import__=deny_import)
    exec(compile(ast.Module(body=[selected[name] for name in names], type_ignores=[]),
        str(path) + '#detached', 'exec'), namespace)
    return namespace


def objective_diagnostics(namespace, records, enabled=True):
    targeted = namespace['targeted']
    rows = []
    for position, record in enumerate(records):
        count, gold, others, domain = targeted._actor_record(record)
        decision = targeted._choose_actor_wrong([0.] * count, [0.] * count, count, gold, others)
        rows.append(dict(decision, selection_implementation='vectorized_detached_source_boundary_gather',
            row_position=position, id=record['id'], source_sha256=hashlib.sha256(record['source_text'].encode()).hexdigest(),
            actor_hinge_value=1. if domain else 0., hinge_active=bool(domain), gradient_enabled_by_policy=enabled,
            zero_domain_differentiable_zero=not domain, teacher_forced_compatibility=True,
            semantic_compatibility_verified=False))
    mean = sum(row['actor_hinge_value'] for row in rows) / len(rows)
    return dict(schema='targeted-source-span-objective-diagnostics/v1', main_loss=1.75,
        actor_hinge_mean=mean, actor_hinge_applied=enabled, actor_hinge_coefficient=.25,
        total_loss=1.75+.25*mean if enabled else 1.75,
        presence_CE_means=dict(conditions=.25, exceptions=.25), rows=rows, teacher_forcing=True,
        evaluation_references_used=False, semantic_compatibility_verified=False)


def gradient_fakes():
    return detached(TARGETED_CONTROLS,
        ('f32', 'Scalar', 'BoolVector', 'Vector', 'Cube', 'FakeTorch', 'fake_output'),
        dict(struct=struct, SimpleNamespace=SimpleNamespace))


def owner_namespace():
    previous = {}
    selected = {'ORIGINAL_PARAMETER_NAMES', 'FEATURE_PARAMETER_NAMES', 'SPLIT_FEATURE_PARAMETER_NAMES',
        'LATENT_PARAMETER_NAMES', 'MODEL_PARAMETER_NAMES'}
    for node in ast.parse(SPLIT.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in selected for t in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPLIT) + '#constants', 'exec'), previous)
    names = previous['MODEL_PARAMETER_NAMES']
    fields = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
    span = SimpleNamespace(FALSE=dict.fromkeys(('admitted', 'formalized', 'promotion_performed', 'proof_authority',
        'publication_performed', 'qualified', 'roundtrip_ok', 'semantic_correctness_verified'), False),
        _require=require, _raw=raw, checkpoint_digest=digest, _SHA=re.compile(r'[0-9a-f]{64}\Z'),
        OPTIONAL_FIELDS=fields[2:], SPAN_FIELDS=fields, _implementation=lambda: {'inert': 'span'})
    def progress(value):
        require(type(value) is dict and set(value) == {'optimizer_steps', 'epochs_completed', 'row_cursor'}
            and all(type(v) is int and v >= 0 for v in value.values()), 'progress')
        return dict(value)
    def indices(count, value, batch_size, seed):
        p = progress(value)
        require(p['row_cursor'] < count and p['row_cursor'] % batch_size == 0
            and p['optimizer_steps'] == p['epochs_completed'] * 14 + p['row_cursor'] // batch_size, 'cursor')
        return list(range(p['row_cursor'], min(count, p['row_cursor'] + batch_size)))
    def bounded(rows, tuning):
        require(type(rows) in (list, tuple) and len(rows) == 168 and not tuning, 'training only')
        return [dict(id=r['id'], source_text=r['source_text'], tokens=span.tokenize_source(r['source_text']),
            labels=dict(modality=0, presence=[True, True, False, False, False, False],
                spans=[(0, 0), (1, 1), (-100, -100), (-100, -100), (-100, -100), (-100, -100)])) for r in rows], []
    span.tokenize_source = lambda text: [dict(text=token) for token in text.split()]
    target_namespace = dict(copy=copy, hashlib=hashlib, json=json, math=math, random=random, struct=struct,
        span=span, SPAN_FIELDS=fields, MAX_SOURCE_TOKENS=128, MAX_NEW_STEPS=32, MAX_SECONDS=32,
        POLICY_SCHEMA='bounded-source-span-targeted-loss-policy/v1',
        LEGACY96_SHA256='4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995')
    selected_names = ('_require', '_raw', 'checkpoint_digest', '_policy', '_validate_policy',
        '_combine_total_loss', '_f32', '_span_coordinates', '_actor_domain', '_actor_record',
        '_choose_actor_wrong', '_actor_auxiliary', '_validate_objective_diagnostics',
        '_progress', '_batch_indices', '_advance_progress')
    detached(TARGETED, selected_names, target_namespace)
    targeted = SimpleNamespace(MAX_BYTES=128*1024*1024, LEGACY96_SHA256=target_namespace['LEGACY96_SHA256'],
        _implementation=lambda: {'inert': 'targeted'}, _bounded_splits=bounded,
        **{name: target_namespace[name] for name in selected_names})
    split = SimpleNamespace(MODEL_PARAMETER_NAMES=names, _implementation=lambda: {'inert': 'split'},
        _validated=lambda source: require(set(source['model_state']) == set(names), 'source34'),
        _branch_digests=lambda state: dict.fromkeys(('modality_feature_state_sha256', 'span_feature_state_sha256',
            'modality_path_state_sha256', 'span_path_state_sha256', 'dormant_latent_state_sha256'), digest(state)))
    continuation = SimpleNamespace(_implementation=lambda: {'inert': 'continuation'}, _context_contract=copy.deepcopy)
    actor_ce = SimpleNamespace(__file__=str(PARENT), _implementation=lambda: {'inert': 'retained_actor_ce'})
    namespace = dict(__file__=str(SOURCE), __name__='detached_actor_ranking', copy=copy, hashlib=hashlib,
        json=json, math=math, Path=Path, split=split, targeted=targeted, continuation=continuation, span=span, actor_ce=actor_ce)
    namespace['__builtins__'] = dict(vars(builtins), __import__=deny_import)
    tree = ast.parse(SOURCE.read_bytes())
    body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE) + '#detached', 'exec'), namespace)
    return namespace


def fixture(namespace):
    state = {name: [[float(index)]] for index, name in enumerate(namespace['BASE_PARAMETER_NAMES'])}
    for head in ('start', 'end'):
        state[head + '.weight'] = [[float(row + column) / 100 for column in range(64)] for row in range(6)]
        state[head + '.bias'] = [float(row) / 10 for row in range(6)]
    rows = [dict(id='train-' + str(index), source_text='source ' + str(index) + ' tail') for index in range(168)]
    context = dict(mode='source-only', dimension=384)
    child = dict(context_contract=context, context_contract_sha256=digest(context))
    source = dict(model_state=state, progress=dict(optimizer_steps=32),
        config=dict(hidden_size=32, latent_dimension=384, latent_enabled=False),
        initial_continuation_checkpoint=child, training_manifest_sha256=digest(rows),
        source_parent_checkpoint_sha256='a'*64, source_parent_model_state_sha256='b'*64)
    namespace['SOURCE_SPLIT_SHA256'] = digest(source)
    namespace['SOURCE_SPLIT_MODEL_SHA256'] = digest(state)
    checkpoint = namespace['build_checkpoint'](source, rows, (), context_contract=context)
    return source, rows, checkpoint


def moments(namespace, steps):
    return dict(schema='adam-default-betas-eps/v1', parameters={name: dict(step=steps,
        exp_avg=[[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * 6,
        exp_avg_sq=[[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * 6)
        for name in namespace['TRAINABLE_PARAMETER_NAMES']})


class Bits:
    def __init__(self, values): self.values = values
    def all(self): return all(self.values)


class Array:
    def __init__(self, values): self.values = values
    def __getitem__(self, index): return Array(self.values[index])
    def flat(self):
        return [value for row in self.values for value in row] if self.values and isinstance(self.values[0], list) else self.values
    def isfinite(self): return Bits([math.isfinite(v) for v in self.flat()])
    def __eq__(self, other): return Bits([v == other for v in self.flat()])


class Parameter:
    def __init__(self, pointer, shape=(1,)):
        self.pointer, self.shape, self.grad, self.requires_grad = pointer, shape, 'unconfigured', None
    def untyped_storage(self): return SimpleNamespace(data_ptr=lambda: self.pointer)
    def requires_grad_(self, value): self.requires_grad = value
    def numel(self): return math.prod(self.shape)


class Scalar:
    def __init__(self, value): self.value = value
    def __float__(self): return float(self.value)
    def detach(self): return self


def fake_model_forward(namespace, *, rng_drift=False):
    """Exercise the actual factory/forward with symbolic full6 heads."""
    calls = []
    torch = SimpleNamespace(inside_no_grad=False)
    class Value:
        def __init__(self, rows=()): self.rows = list(rows)
        def clone(self): return Value(self.rows)
        def __mul__(self, other): return self
        def __truediv__(self, other): return self
        def sum(self, axis): return self
        def reshape(self, *shape): return self
        def transpose(self, *axes): return self
        def masked_fill(self, *args): return self
        def __invert__(self): return self
        def __getitem__(self, key):
            if isinstance(key, tuple) and len(key) == 3 and isinstance(key[1], slice):
                return Value(self.rows[key[1]])
            return self
    class Guard:
        def __enter__(self): torch.inside_no_grad = True
        def __exit__(self, *args): torch.inside_no_grad = False
    class Head:
        def __init__(self, tag): self.tag = tag
        def __call__(self, value):
            active = self.tag.startswith('actor_')
            require(torch.inside_no_grad is not active, 'frozen/actor grad context')
            calls.append(self.tag)
            return Value([self.tag + ':' + str(index) for index in range(6)])
    class Base:
        def __init__(self):
            for name in ('modality', 'presence', 'start', 'end'): setattr(self, name, Head(name))
        def _features(self, *args):
            require(torch.inside_no_grad, 'features must be detached')
            calls.append('span_features' if args[-1] else 'modality_features')
            return Value(), Value()
    torch.rng_state = Value([1729])
    torch.get_rng_state = lambda: torch.rng_state.clone()
    torch.equal = lambda left, right: left.rows == right.rows
    torch.no_grad = Guard
    torch.cat = lambda values, dim: Value([row for value in values for row in value.rows])
    def base_factory(owner, config):
        if rng_drift:
            torch.rng_state = Value([1730])
        return Base()
    namespace['split']._model = base_factory
    model = namespace['_model'](torch, dict(hidden_size=32))
    require(model.actor_start is not model.start and model.actor_end is not model.end, 'head aliases')
    model.actor_start.tag, model.actor_end.tag = 'actor_start', 'actor_end'
    output = model.forward(Value(), Value(), Value(), Value())
    return model, output, calls


class ActorRankingContracts(unittest.TestCase):
    def setUp(self): self.ns = owner_namespace()

    def test_versioned_objective_and_immutable_derivation_and_targeted_sources(self):
        ns = self.ns
        self.assertEqual(ns['SCHEMA'], 'bounded-actor-ranking-adapter-checkpoint/v1')
        self.assertEqual(ns['LINEAGE_ID'], 'bounded_actor_ranking_adapter_v1')
        self.assertEqual(ns['OBJECTIVES'], ('actor-ranking-hinge',))
        self.assertEqual(hashlib.sha256(PARENT.read_bytes()).hexdigest(),
            '442bfb72ae1038f541530a8d2446872f0393a5eeab07ba9c5616d6ad80368d4a')
        self.assertEqual(hashlib.sha256(TARGETED.read_bytes()).hexdigest(),
            'f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b')
        ns['_implementation']()
        ns['actor_ce'].__file__ = str(TARGETED)
        with self.assertRaisesRegex(ValueError, 'derivation source differs'):
            ns['_capture_implementation']()

    def test_mechanical_model_restore_partition_and_gradient_code_is_retained(self):
        old = {node.name: node for node in ast.parse(PARENT.read_bytes()).body if isinstance(node, ast.FunctionDef)}
        new = {node.name: node for node in ast.parse(SOURCE.read_bytes()).body if isinstance(node, ast.FunctionDef)}
        names = ('_finite_shape', '_trainable_shapes', '_initial_state', '_inactive_state', '_all_zero',
            '_partition', '_source', '_training_records', '_branch_digests', '_model', '_state_digest',
            '_configure_parameters', '_validate_optimizer_state', '_origin', '_validated', '_restore',
            '_frozen_head_digest', '_row_invariants', '_validate_freeze_entry')
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(ast.dump(new[name], include_attributes=False), ast.dump(old[name], include_attributes=False))
        for name in ('_actor_domain', '_choose_actor_wrong', '_actor_auxiliary', '_combine_total_loss'):
            self.assertNotIn(name, new)

    def test_closed_ranking_policy_rejects_OFF_coefficient_margin_domain_and_old_objective(self):
        ns = self.ns
        good = ns['_policy']('actor-ranking-hinge')
        ns['_validate_policy'](good)
        for mutate in (lambda p: p.update(objective='actor-boundary-ce'),
                       lambda p: p['objective_policy'].update(actor_ranking_enabled=False),
                       lambda p: p['objective_policy'].update(actor_hinge_coefficient=1.),
                       lambda p: p['objective_policy'].update(actor_hinge_margin=2.),
                       lambda p: p['objective_policy'].update(actor_negative_domain='all_spans_except_gold')):
            bad = copy.deepcopy(good); mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_policy'](bad)
        ns['targeted']._loss = lambda *args: self.fail('invalid policy reached inherited loss')
        bad = copy.deepcopy(good); bad['objective_policy']['actor_ranking_enabled'] = False
        with self.assertRaises(ValueError): ns['_loss'](None, object(), [{}], [0], bad)

    def test_actual_inherited_domain_keeps_gold_nonactor_filter_and_row_major_ties(self):
        target = self.ns['targeted']
        domain = target._actor_domain(5, (0, 0), {'action': (2, 2), 'object': (4, 4)})
        self.assertEqual(domain, [(0, 1), (1, 1), (3, 3)])
        choice = target._choose_actor_wrong([0.] * 6, [0.] * 6, 5, (0, 0),
            {'action': (2, 2), 'object': (4, 4)})
        self.assertEqual(choice['chosen_wrong_coordinates'], [0, 1])
        self.assertEqual(choice['chosen_wrong_tie_count'], 3)
        self.assertEqual(choice['compatible_wrong_domain_sha256'], digest(domain))
        self.assertEqual(target._actor_domain(2, (0, 0), {'action': (1, 1)}), [])
        for count in (True, 0, 129):
            with self.assertRaises(ValueError): target._actor_domain(count, (0, 0), {})

    def test_actual_inherited_hinge_routes_quarter_gradients_to_wrong_and_gold_actor_logits(self):
        ns = self.ns
        _, rows, _ = fixture(ns)
        record = ns['_training_records'](rows)[0]
        fake = gradient_fakes(); torch = fake['FakeTorch']()
        output = fake['fake_output']([0., 0., 2.], [0., 0., 2.])
        main = fake['Scalar'](1.75)
        seen = []
        def base_loss(owner, model, records, policy):
            seen.append(policy['actor_ranking_enabled'])
            hinge, diagnostics = ns['targeted']._actor_auxiliary(owner, model(), records, policy['actor_ranking_enabled'])
            return ns['targeted']._combine_total_loss(main, hinge, policy['actor_ranking_enabled']), {'rows': diagnostics}
        ns['targeted']._loss = base_loss
        total, details = ns['_loss'](torch, output, [record], [0], ns['_policy']('actor-ranking-hinge'))
        self.assertEqual(seen, [True])
        self.assertEqual(float(total), 3.)
        self.assertEqual(total.gradient, {'s2': .25, 'e2': .25, 's0': -.25, 'e0': -.25})
        self.assertEqual(details['base_objective']['rows'][0]['actor_hinge_value'], 5.)
        self.assertEqual(torch.argmax_calls, 1)
        off = ns['targeted']._combine_total_loss(main, fake['Scalar'](5., {'wrong': 1.}), False)
        self.assertIs(off, main)

    def test_outer_trace_requires_ranking_ON_even_for_internally_valid_OFF_diagnostics(self):
        ns = self.ns
        _, rows, _ = fixture(ns)
        records = ns['_training_records'](rows)[:2]
        policy = ns['_policy']('actor-ranking-hinge')
        details = dict(base_objective=objective_diagnostics(ns, records, enabled=False), total_loss=1.75,
            batch_denominator=2, rows=[dict(id=r['id'], training_index=i, token_count=3,
                actor_gold_coordinates=[0, 0], actor_present=True) for i, r in enumerate(records)],
            evaluation_references_used=False, teacher_forcing=True)
        ns['targeted']._validate_objective_diagnostics(details['base_objective'])
        entry = dict(optimizer_step=1, indices=[0, 1], ids=[r['id'] for r in records], details=details)
        batch = dict(optimizer_step=1, indices=[0, 1], ids=list(entry['ids']), loss=1.75)
        with self.assertRaisesRegex(ValueError, 'must apply the retained actor hinge'):
            ns['_validate_objective_entry'](entry, batch, policy)

    def test_fixed_32_update_schedule_is_384_occurrences_with_no_control_updates(self):
        target = self.ns['targeted']
        progress = dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
        batches = []
        for _ in range(32):
            indices = target._batch_indices(168, progress, 12, 1729)
            self.assertEqual(len(indices), 12)
            batches.append(indices)
            progress = target._advance_progress(progress, len(indices), 168)
        self.assertEqual(progress, dict(epochs_completed=2, row_cursor=48, optimizer_steps=32))
        self.assertEqual(sum(map(len, batches)), 384)
        self.assertEqual(set(sum(batches[:14], [])), set(range(168)))
        self.assertEqual(set(sum(batches[14:28], [])), set(range(168)))
        self.assertEqual(batches[0], target._batch_indices(168,
            dict(epochs_completed=0, row_cursor=0, optimizer_steps=0), 12, 1729))

    def test_factory_preserves_CPU_RNG_and_rejects_rng_drift(self):
        fake_model_forward(self.ns)
        with self.assertRaisesRegex(ValueError, 'ambient CPU RNG'):
            fake_model_forward(self.ns, rng_drift=True)

    def test_real_pins_closed_partition_and_counts(self):
        ns = self.ns
        self.assertEqual(ns['SOURCE_SPLIT_SHA256'], '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035')
        self.assertEqual(ns['SOURCE_SPLIT_MODEL_SHA256'], 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5')
        part = ns['_partition']()
        self.assertEqual(len(part['model_parameter_names']), 38)
        self.assertEqual(len(part['frozen_parameter_names']), 34)
        self.assertEqual(part['optimizer_parameter_order'], ['actor_start.weight', 'actor_start.bias', 'actor_end.weight', 'actor_end.bias'])
        self.assertEqual(part['active_head_rows'], [0])
        self.assertEqual(part['inactive_head_rows'], [1, 2, 3, 4, 5])
        self.assertEqual(part['active_trainable_scalar_count'], 130)
        self.assertEqual(part['stored_trainable_scalar_count'], 780)
        self.assertEqual(part['inactive_stored_scalar_count'], 650)

    def test_independent_initial_copies_and_malformed_source_shapes(self):
        ns = self.ns
        source, _, checkpoint = fixture(ns)
        state = checkpoint['model_state']
        for name in ns['TRAINABLE_PARAMETER_NAMES']:
            original = name.removeprefix('actor_')
            self.assertEqual(raw(state[name]), raw(source['model_state'][original]))
        state['actor_start.weight'][0][0] = 99.
        self.assertNotEqual(state['actor_start.weight'][0][0], state['start.weight'][0][0])
        self.assertNotEqual(state['actor_start.weight'][0][0], source['model_state']['start.weight'][0][0])
        for value in ([[]] * 6, [[0.] * 64] * 5, [[float('nan')] * 64] * 6, [[True] * 64] * 6):
            bad = copy.deepcopy(source['model_state']); bad['start.weight'] = value
            with self.subTest(shape=str(value)[:40]), self.assertRaises(ValueError): ns['_initial_state'](bad)

    def test_actual_factory_and_forward_route_only_actor_row_without_zero_add(self):
        model, output, calls = fake_model_forward(self.ns)
        self.assertEqual(calls, ['modality_features', 'modality', 'span_features', 'presence',
            'start', 'end', 'actor_start', 'actor_end'])
        self.assertEqual(output['modality'].rows, ['modality:' + str(index) for index in range(6)])
        self.assertEqual(output['presence'].rows, ['presence:' + str(index) for index in range(6)])
        for name in ('start', 'end'):
            self.assertEqual(output[name].rows, ['actor_' + name + ':0'] + [name + ':' + str(index) for index in range(1, 6)])
        self.assertEqual(set(model._actor_forward_accounting.values()), {1})

    def test_zero_step_state_preserves_signed_zero_and_json_types(self):
        ns = self.ns
        _, _, checkpoint = fixture(ns)
        ns['_validated'](checkpoint)
        for value in (-0., 0):
            bad = copy.deepcopy(checkpoint); bad['model_state']['actor_start.weight'][0][0] = value
            with self.subTest(value=repr(value)), self.assertRaises(ValueError): ns['_validated'](bad)

    def test_closed_source_context_authority_training_and_policy(self):
        ns = self.ns
        source, rows, checkpoint = fixture(ns)
        for mutate in (lambda c: c.update(extra=True), lambda c: c.update(admitted=True),
                       lambda c: c.update(source_split_checkpoint_sha256='e'*64),
                       lambda c: c['model_state']['start.weight'][0].__setitem__(0, 20.),
                       lambda c: c['model_state']['actor_end.weight'][5].__setitem__(0, 20.),
                       lambda c: c['model_state']['actor_end.bias'].__setitem__(0, float('inf')),
                       lambda c: c['config'].update(latent_enabled=True),
                       lambda c: c['progress'].update(row_cursor=1),
                       lambda c: c['training_policy']['optimizer'].update(weight_decay=.01)):
            bad = copy.deepcopy(checkpoint); mutate(bad)
            with self.assertRaises(ValueError): ns['_validated'](bad)
        for kwargs in (dict(objective='actor-anchor-margin'), dict(seed=True), dict(batch_size=13), dict(latent_enabled=True)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ns['build_checkpoint'](source, rows, (), context_contract=checkpoint['context_contract'], **kwargs)
        with self.assertRaises(ValueError): ns['build_checkpoint'](source, list(reversed(rows)), (), context_contract=checkpoint['context_contract'])
        with self.assertRaises(ValueError): ns['build_checkpoint'](source, rows, [{}], context_contract=checkpoint['context_contract'])
        policy = ns['_policy']('actor-ranking-hinge')
        self.assertTrue(policy['objective_policy']['actor_ranking_enabled'])
        self.assertEqual(policy['objective_policy']['actor_hinge_coefficient'], .25)
        self.assertEqual(policy['objective_policy']['actor_hinge_margin'], 1.)
        self.assertEqual(policy['objective_policy']['presence_ce_weight'], 1)
        self.assertNotIn('margin', policy)

    def test_optimizer_shape_subset_step_and_inactive_moment_rejections(self):
        ns = self.ns
        ns['_validate_optimizer_state'](dict(schema='adam-default-betas-eps/v1', parameters={}), 0)
        good = moments(ns, 1); ns['_validate_optimizer_state'](good, 1)
        for mutate in (lambda s: s['parameters'].pop('actor_start.bias'),
                       lambda s: s['parameters'].update({'start.bias': copy.deepcopy(s['parameters']['actor_start.bias'])}),
                       lambda s: s['parameters']['actor_start.bias'].update(step=2),
                       lambda s: s['parameters']['actor_end.weight']['exp_avg'][1].__setitem__(0, .1),
                       lambda s: s['parameters']['actor_start.weight']['exp_avg'][0].pop(),
                       lambda s: s['parameters']['actor_end.bias']['exp_avg_sq'].__setitem__(0, -.1)):
            bad = copy.deepcopy(good); mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_optimizer_state'](bad, 1)
        with self.assertRaises(ValueError): ns['_validate_optimizer_state'](good, 0)

    def test_configuration_alias_refusal_and_live_gradient_rows(self):
        ns = self.ns
        shapes = ns['_trainable_shapes']()
        named = {name: Parameter(index + 1, shapes.get(name, (1,))) for index, name in enumerate(ns['MODEL_PARAMETER_NAMES'])}
        model = SimpleNamespace(named_parameters=lambda: named.items())
        _, selected = ns['_configure_parameters'](model)
        self.assertEqual(selected, [named[name] for name in ns['TRAINABLE_PARAMETER_NAMES']])
        self.assertTrue(all(p.grad is None for p in named.values()))
        for name, p in named.items(): self.assertEqual(p.requires_grad, name in shapes)
        state = {}
        for name in shapes:
            named[name].grad = Array([[1.] * 64] + [[0.] * 64 for _ in range(5)] if name.endswith('weight') else [1.] + [0.] * 5)
            state[named[name]] = dict(exp_avg=Array([[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * 6),
                exp_avg_sq=Array([[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * 6))
        optimizer = SimpleNamespace(state=state)
        ns['_row_invariants'](named, optimizer)
        named['actor_end.bias'].grad.values[5] = .01
        with self.assertRaises(ValueError): ns['_row_invariants'](named, optimizer)
        named['actor_end.bias'].grad.values[5] = 0.
        named['start.bias'].grad = Array([0.])
        with self.assertRaises(ValueError): ns['_row_invariants'](named, optimizer)
        named['start.bias'].grad = None
        named['actor_end.bias'].pointer = named['actor_start.bias'].pointer
        with self.assertRaises(ValueError): ns['_configure_parameters'](model)

    def test_unchanged_loss_object_and_authenticated_actor_diagnostics(self):
        ns = self.ns
        _, rows, _ = fixture(ns)
        records = ns['_training_records'](rows)
        output = object(); total = Scalar(2.); calls = []
        def base_loss(torch, model, batch, policy):
            calls.append((model(), batch, policy))
            return total, objective_diagnostics(ns, batch)
        ns['targeted']._loss = base_loss
        actual, details = ns['_loss'](None, output, records[:2], [0, 1], ns['_policy']('actor-ranking-hinge'))
        self.assertIs(actual, total)
        self.assertIs(calls[0][0], output)
        self.assertTrue(calls[0][2]['actor_ranking_enabled'])
        entry = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], details=details)
        batch = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], loss=2.)
        ns['_validate_objective_entry'](entry, batch, ns['_policy']('actor-ranking-hinge'))
        for mutate in (lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[2, 3]),
                       lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[1, 1]),
                       lambda e: e['details']['rows'][0].update(training_index=167),
                       lambda e: e['details'].update(total_loss=2.5)):
            bad = copy.deepcopy(entry); mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_objective_entry'](bad, batch, ns['_policy']('actor-ranking-hinge'))

    def test_inference_and_capture_reject_129_before_restore_or_target_access(self):
        tree = ast.parse(SOURCE.read_bytes())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SpanActorRankingAdapterDecoder')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'decode_formal_logic')
        condition = compile(ast.Expression(method.body[0].value.args[0]), str(SOURCE) + '#bounds', 'eval')
        span = SimpleNamespace(tokenize_source=lambda text: [None] * int(text))
        self.assertTrue(eval(condition, dict(texts=['128'] * 128, span=span)))
        for texts in ([], ['1'] * 129, ['129'], [1]):
            self.assertFalse(eval(condition, dict(texts=texts, span=span)))
        capture = self.ns['captured_inference']
        for rows in ([], [{}] * 129, iter([{}])):
            with self.assertRaises(ValueError): capture(None, self.ns['span'], self.ns['continuation'], None, rows)
        for node in (method, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'captured_inference')):
            calls = [n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            self.assertNotIn('_labels', calls); self.assertNotIn('_actor_record', calls)

    def test_train_bounds_reject_before_numerical_restore(self):
        ns = self.ns
        for kwargs in (dict(max_steps=True), dict(max_steps=-1), dict(max_steps=33), dict(max_seconds=True),
                       dict(max_seconds=-1), dict(max_seconds=33), dict(max_seconds=float('nan'))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): ns['train_decoder']({}, [], **kwargs)
        with self.assertRaisesRegex(AssertionError, 'cannot import: torch'): ns['_restore']({})


if __name__ == '__main__':
    unittest.main()
