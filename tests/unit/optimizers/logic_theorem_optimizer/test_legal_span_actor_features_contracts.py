"""Detached stdlib contracts for actor feature adaptation; no numerical imports."""
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

SOURCE = Path(__file__).resolve().parents[4] / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_features.py'
SPLIT = SOURCE.with_name('legal_span_split_features.py')
PARENT = SOURCE.with_name('legal_span_actor_boundary.py')
ATTENTION = SOURCE.with_name('legal_span_temporal_attention.py')
TARGETED = SOURCE.with_name('legal_span_targeted_loss.py')

def require(value, message):
    if not value:
        raise ValueError(message)

def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()

def deny_import(name, *args, **kwargs):
    raise AssertionError('Detached actor features contracts cannot import: ' + name)

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

def objective_diagnostics(namespace, records, enabled=False):
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
    retained = dict(copy=copy, math=math, BASE_PARAMETER_NAMES=names, _require=require, _finite_shape=None, TRAINABLE_PARAMETER_NAMES=('actor_start.weight', 'actor_start.bias', 'actor_end.weight', 'actor_end.bias'), ENCODED_WIDTH=64)
    detached(PARENT, ('_finite_shape', '_trainable_shapes', '_initial_state', '_inactive_state'), retained)
    actor_ce._initial_state = retained['_initial_state']
    actor_ce._inactive_state = retained['_inactive_state']
    namespace = dict(__file__=str(SOURCE), __name__='detached_actor_features', copy=copy, hashlib=hashlib,
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
        exp_avg=[[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * (64 if name in namespace['FEATURE_PARAMETER_NAMES'] else 6),
        exp_avg_sq=[[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * (64 if name in namespace['FEATURE_PARAMETER_NAMES'] else 6))
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


class ActorFeaturesContracts(unittest.TestCase):
    def setUp(self): self.ns = owner_namespace()

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
            policy = ns['_policy']('actor-features-ce')
            self.assertFalse(policy['objective_policy']['actor_ranking_enabled'])
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
                named[name].grad = Array([[1.] * 64] + [[0.] * 64 for _ in range(5)] if name.endswith('weight') else ([1.] * 64 if name in ns['FEATURE_PARAMETER_NAMES'] else [1.] + [0.] * 5))
                state[named[name]] = dict(exp_avg=Array([[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * (64 if name in ns['FEATURE_PARAMETER_NAMES'] else 6)),
                    exp_avg_sq=Array([[0.] * 64 for _ in range(6)] if name.endswith('weight') else [0.] * (64 if name in ns['FEATURE_PARAMETER_NAMES'] else 6)))
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
            output = object(); total = Scalar(1.75); calls = []
            def base_loss(torch, model, batch, policy):
                calls.append((model(), batch, policy))
                return total, objective_diagnostics(ns, batch)
            ns['targeted']._loss = base_loss
            actual, details = ns['_loss'](None, output, records[:2], [0, 1], ns['_policy']('actor-features-ce'))
            self.assertIs(actual, total)
            self.assertIs(calls[0][0], output)
            self.assertFalse(calls[0][2]['actor_ranking_enabled'])
            entry = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], details=details)
            batch = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], loss=1.75)
            ns['_validate_objective_entry'](entry, batch, ns['_policy']('actor-features-ce'))
            for mutate in (lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[2, 3]),
                           lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[1, 1]),
                           lambda e: e['details']['rows'][0].update(training_index=167),
                           lambda e: e['details'].update(total_loss=2.5)):
                bad = copy.deepcopy(entry); mutate(bad)
                with self.assertRaises(ValueError): ns['_validate_objective_entry'](bad, batch, ns['_policy']('actor-features-ce'))

    def test_inference_and_capture_reject_129_before_restore_or_target_access(self):
            tree = ast.parse(SOURCE.read_bytes())
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SpanActorFeaturesAdapterDecoder')
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


def feature_fixture(step=1):
    batch = dict(optimizer_step=step, indices=[0, 1], ids=['train-0', 'train-1'])
    entry = dict(batch, gradients_finite_connected=True, first_update_requirements_checked=step == 1)
    for label in ('query', 'gate', 'context', 'residual'):
        zero = step == 1 and label in ('query', 'context')
        entry[label + '_gradient_l2'] = 0. if zero else 2.
        entry[label + '_gradient_exact_zero'] = zero
    for label in ('query', 'gate'):
        changed = step != 1 or label == 'gate'
        entry[label + '_before_sha256'] = 'a' * 64
        entry[label + '_after_sha256'] = ('b' if changed else 'a') * 64
        entry[label + '_changed'] = changed
        entry[label + '_Adam_moments_exact_zero'] = step == 1 and label == 'query'
        for key in ('exp_avg', 'exp_avg_sq'): entry[label + '_' + key + '_sha256'] = 'c' * 64
    return entry, batch


def fake_forward(namespace, rng_drift=False):
    """Call the actual factory/forward with symbolic tensors and copied heads."""
    calls, torch = [], SimpleNamespace(inside_no_grad=False)
    class Value:
        def __init__(self, rows=(), tag='value'): self.rows, self.tag = list(rows), tag
        def clone(self): return Value(self.rows, self.tag)
        def __mul__(self, other): return Value(tag=self.tag + '*')
        def __truediv__(self, other): return self
        def __add__(self, other): return Value(tag='sum')
        def sum(self, axis): return self
        def reshape(self, *shape): return self
        def transpose(self, *axes): return self
        def masked_fill(self, *args): return self
        def __invert__(self): return self
        def __eq__(self, other): return self
        def all(self): return True
        def __getitem__(self, key):
            if isinstance(key, tuple) and len(key) == 3 and isinstance(key[1], slice):
                return Value(self.rows[key[1]], self.tag)
            return self
    class Guard:
        def __enter__(self): torch.inside_no_grad = True
        def __exit__(self, *args): torch.inside_no_grad = False
    class Function:
        @classmethod
        def apply(cls, *args): return cls.forward(None, *args)
    class Module:
        def register_parameter(self, name, value): setattr(self, name, value)
    class Head:
        def __init__(self, tag): self.tag = tag
        def __call__(self, value):
            active = self.tag.startswith('actor_')
            require(torch.inside_no_grad is not active, 'frozen/actor graph route')
            if active: require(value.tag == 'span_features', 'exactzero original tensor route')
            calls.append(self.tag)
            return Value([self.tag + ':' + str(index) for index in range(6)])
    class Base:
        def __init__(self):
            for name in ('modality', 'presence', 'start', 'end', 'actor_start', 'actor_end'): setattr(self, name, Head(name))
            self.training = False
            self._actor_forward_accounting = dict.fromkeys(('source_model_forwards', 'modality_encoder_forwards',
                'span_encoder_forwards', 'original_presence_head_forwards', 'original_start_head_forwards',
                'original_end_head_forwards', 'actor_start_head_forwards', 'actor_end_head_forwards'), 0)
        def _features(self, *args):
            require(torch.inside_no_grad, 'features detached')
            label = 'span_features' if args[-1] else 'modality_features'
            calls.append(label)
            return Value(tag=label), Value(tag='mask')
    torch.rng_state = Value([1729])
    torch.get_rng_state = lambda: torch.rng_state.clone()
    torch.equal = lambda a, b: a.rows == b.rows
    torch.no_grad, torch.is_grad_enabled = Guard, lambda: False
    torch.softmax = lambda value, dim: Value(tag='attention')
    torch.zeros = lambda width: Value([0.] * width)
    torch.nn = SimpleNamespace(Module=Module, Parameter=lambda value: value)
    torch.autograd = SimpleNamespace(Function=Function)
    torch.cat = lambda values, dim: Value([row for value in values for row in value.rows])
    def factory(owner, config):
        if rng_drift: torch.rng_state = Value([1730])
        return Base()
    namespace['actor_ce']._model = factory
    model = namespace['_model'](torch, dict(hidden_size=32))
    output = model.forward(Value(), Value(), Value(), Value())
    return model, output, calls


class ActorFeaturesNewContracts(unittest.TestCase):
    def setUp(self): self.ns = owner_namespace()

    def test_exact_source_pins_used_factory_and_attention_recipe_raw_only(self):
        ns = self.ns
        self.assertEqual(ns['SCHEMA'], 'bounded-actor-features-adapter-checkpoint/v1')
        self.assertEqual(ns['SOURCE_SPLIT_SHA256'], '95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035')
        self.assertEqual(ns['SOURCE_SPLIT_MODEL_SHA256'], 'fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5')
        self.assertEqual(hashlib.sha256(PARENT.read_bytes()).hexdigest(), ns['DERIVED_ACTOR_CE_SHA256'])
        self.assertEqual(hashlib.sha256(ATTENTION.read_bytes()).hexdigest(), ns['ATTENTION_RECIPE_SHA256'])
        self.assertEqual(hashlib.sha256(TARGETED.read_bytes()).hexdigest(), 'f611490b2c15dee3437d0181686f16bb3aa56f3b20a00b9fa0d4ae2b2624637b')
        tree = ast.parse(SOURCE.read_bytes())
        imported = [alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names]
        self.assertEqual(imported, ['annotations', 'Path', 'legal_span_actor_boundary', 'legal_span_split_features',
            'legal_span_targeted_loss', 'legal_span_continuation', 'legal_span_formula'])
        ns['actor_ce'].__file__ = str(TARGETED)
        with self.assertRaises(ValueError): ns['_capture_implementation']()

    def test_closed_ce_policy_and_head_feature_scalar_partition(self):
        ns = self.ns; policy = ns['_policy']('actor-features-ce'); part = ns['_partition']()
        self.assertEqual((len(part['model_parameter_names']), len(part['frozen_parameter_names']),
            len(part['trainable_parameter_names'])), (40, 34, 6))
        self.assertEqual((part['stored_trainable_scalar_count'], part['active_trainable_scalar_count'],
            part['inactive_stored_scalar_count']), (908, 258, 650))
        self.assertEqual(part['feature_parameter_names'], ['actor_attention.query', 'actor_context.gate'])
        self.assertEqual(part['optimizer_parameter_order'], list(ns['TRAINABLE_PARAMETER_NAMES']))
        self.assertFalse(policy['objective_policy']['actor_ranking_enabled'])
        for mutate in (lambda p: p.update(objective='actor-ranking-hinge'),
                       lambda p: p['objective_policy'].update(actor_ranking_enabled=True),
                       lambda p: p['actor_features'].update(interaction='global_constant_shift'),
                       lambda p: p['optimizer'].update(weight_decay=.01)):
            bad = copy.deepcopy(policy); mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_policy'](bad)

    def test_initial_vectors_independent_exactzero_and_actor_head_copy(self):
        ns = self.ns; source, rows, checkpoint = fixture(ns); state = checkpoint['model_state']
        ns['_validated'](checkpoint)
        for name in ns['HEAD_PARAMETER_NAMES']:
            self.assertEqual(raw(state[name]), raw(source['model_state'][name.removeprefix('actor_')]))
        for name in ns['FEATURE_PARAMETER_NAMES']: self.assertEqual(raw(state[name]), raw([0.] * 64))
        self.assertIsNot(state['actor_attention.query'], state['actor_context.gate'])
        state['actor_start.weight'][0][0] = 99.
        self.assertNotEqual(state['start.weight'][0][0], 99.)
        self.assertNotEqual(source['model_state']['start.weight'][0][0], 99.)
        for name, value in (('actor_attention.query', [0.] * 63), ('actor_context.gate', [float('nan')] * 64), ('actor_attention.query', [float('inf')] * 64), ('actor_context.gate', [True] * 64),
                            ('actor_start.bias', [0.] * 5)):
            bad = copy.deepcopy(checkpoint); bad['model_state'][name] = value
            with self.assertRaises(ValueError): ns['_validated'](bad)

    def test_actual_factory_forward_keeps_full6_and_only_actor_context_route_and_rng(self):
        model, output, calls = fake_forward(self.ns)
        self.assertEqual(calls, ['modality_features', 'modality', 'span_features', 'presence', 'start', 'end', 'actor_start', 'actor_end'])
        for name in ('start', 'end'):
            self.assertEqual(output[name].rows, ['actor_' + name + ':0'] + [name + ':' + str(i) for i in range(1, 6)])
        self.assertEqual(set(model._actor_forward_accounting.values()), {1})
        self.assertIn('actor_attention_pool_forwards', model._actor_forward_accounting)
        self.assertIn('actor_context_feature_forwards', model._actor_forward_accounting)
        self.assertIsNone(model._actor_feature_taps)
        with self.assertRaisesRegex(ValueError, 'ambient CPU RNG'): fake_forward(self.ns, rng_drift=True)

    def test_exact_zero_custom_autograd_preserves_identity_signedzero_and_addition_derivative(self):
        owner = next(node for node in ast.parse(SOURCE.read_bytes()).body if isinstance(node, ast.FunctionDef) and node.name == '_model')
        cls = next(node for node in owner.body if isinstance(node, ast.ClassDef) and node.name == 'ExactZeroResidual')
        class V:
            def __init__(self, values): self.values = list(values)
            def __eq__(self, value): return SimpleNamespace(values=[v == value for v in self.values], all=lambda: all(v == value for v in self.values))
            def __add__(self, other): return V([a + b for a, b in zip(self.values, other.values)])
        def where(condition, original, updated):
            return V([a if keep else c for a, keep, c in zip(original.values, condition.values, updated.values)])
        torch = SimpleNamespace(autograd=SimpleNamespace(Function=object), where=where)
        namespace = dict(torch=torch)
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE) + '#exactzero', 'exec'), namespace)
        custom = namespace['ExactZeroResidual']; original = V([-0., 0., -3.])
        result = custom.forward(None, original, V([0., -0., 0.]))
        self.assertIs(result, original)
        self.assertEqual(struct.pack('!d', result.values[0]), struct.pack('!d', -0.))
        changed = custom.forward(None, original, V([0., 2., -1.]))
        self.assertEqual(changed.values, [-0., 2., -4.])
        self.assertEqual(struct.pack('!d', changed.values[0]), struct.pack('!d', -0.))
        gradient = object(); self.assertEqual(custom.backward(None, gradient), (gradient, gradient))

    def test_actual_attention_has_masked_softmax_token_product_and_zero_route(self):
        tree = ast.parse(SOURCE.read_bytes()); owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_model')
        actor = next(n for n in owner.body if isinstance(n, ast.ClassDef) and n.name == 'ActorFeaturesAdapter')
        forward = next(n for n in actor.body if isinstance(n, ast.FunctionDef) and n.name == 'forward')
        assignments = {n.targets[0].id: n.value for n in forward.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
        equations = {name: ast.unparse(assignments[name]) for name in ('scores', 'probabilities', 'context', 'interaction', 'residual', 'actor_encoded')}
        self.assertEqual(equations['scores'], '(encoded * self.actor_attention.query[None, None, :]).sum(-1) / math.sqrt(ENCODED_WIDTH)')
        self.assertEqual(equations['probabilities'], "torch.softmax(scores.masked_fill(~mask, -float('inf')), dim=1)")
        self.assertEqual(equations['context'], '(encoded * probabilities[..., None]).sum(1)')
        self.assertEqual(equations['interaction'], 'encoded * context[:, None, :]')
        self.assertEqual(equations['residual'], 'interaction * self.actor_context.gate[None, None, :]')
        self.assertEqual(equations['actor_encoded'], 'ExactZeroResidual.apply(encoded, residual)')
        # This scalar oracle distinguishes a useful token product from a constant logit shift.
        encoded, context, gate, pointer = [[1., 2.], [3., -1.]], [2., .5], [.1, -.2], [.7, -.4]
        scores = lambda rows: [sum(a*b for a,b in zip(row, pointer)) for row in rows]
        before = scores(encoded); after = scores([[h+h*c*g for h,c,g in zip(row,context,gate)] for row in encoded])
        self.assertNotEqual(after[0] - after[1], before[0] - before[1])

    def test_first_query_and_inactive_moments_exactzero_then_query_updates_allowed(self):
        ns = self.ns; first = moments(ns, 1); ns['_validate_optimizer_state'](first, 1)
        bad = copy.deepcopy(first); bad['parameters']['actor_attention.query']['exp_avg'][0] = .01
        with self.assertRaisesRegex(ValueError, 'first query Adam moments'): ns['_validate_optimizer_state'](bad, 1)
        later = moments(ns, 2); later['parameters']['actor_attention.query']['exp_avg'][0] = .01
        ns['_validate_optimizer_state'](later, 2)
        for name in ns['HEAD_PARAMETER_NAMES']:
            bad = moments(ns, 2)
            if name.endswith('weight'): bad['parameters'][name]['exp_avg'][5][0] = .01
            else: bad['parameters'][name]['exp_avg'][5] = .01
            with self.assertRaises(ValueError): ns['_validate_optimizer_state'](bad, 2)

    def test_feature_trace_first_update_and_later_diagnostics_are_closed(self):
        validate = self.ns['_validate_feature_entry']
        for step in (1, 2, 32):
            entry, batch = feature_fixture(step); validate(entry, batch)
        entry, batch = feature_fixture()
        for mutate in (lambda e: e.update(query_gradient_exact_zero=False),
                       lambda e: e.update(context_gradient_exact_zero=False),
                       lambda e: e.update(query_changed=True),
                       lambda e: e.update(query_Adam_moments_exact_zero=False),
                       lambda e: e.update(gate_changed=False),
                       lambda e: e.update(residual_gradient_l2=0.),
                       lambda e: e.update(query_gradient_l2=float('nan')),
                       lambda e: e.update(first_update_requirements_checked=False),
                       lambda e: e.update(gate_exp_avg_sha256='bad'),
                       lambda e: e.update(extra=True),
                       lambda e: e['ids'].__setitem__(0, 'wrong')):
            bad = copy.deepcopy(entry); mutate(bad)
            with self.assertRaises(ValueError): validate(bad, batch)

    def test_outer_objective_rejects_inherited_valid_ranking_ON(self):
        ns = self.ns; _, rows, _ = fixture(ns); records = ns['_training_records'](rows)[:2]
        base = objective_diagnostics(ns, records, enabled=True)
        ns['targeted']._validate_objective_diagnostics(base)
        entry = dict(optimizer_step=1, indices=[0,1], ids=[r['id'] for r in records], details=dict(base_objective=base,
            total_loss=base['total_loss'], batch_denominator=2, rows=[dict(id=r['id'], training_index=i, token_count=3,
                actor_gold_coordinates=[0,0], actor_present=True) for i,r in enumerate(records)], evaluation_references_used=False, teacher_forcing=True))
        batch = dict(optimizer_step=1, indices=[0,1], ids=entry['ids'], loss=base['total_loss'])
        with self.assertRaisesRegex(ValueError, 'leave ranking OFF'): ns['_validate_objective_entry'](entry,batch,ns['_policy']('actor-features-ce'))





class ActorFeatureGradientContracts(unittest.TestCase):
    def test_actual_feature_gradient_taps_require_first_queryzero_and_gate_connection(self):
        ns = owner_namespace()
        class Gradient(Array):
            def detach(self): return self
        gradients = dict(query=Gradient([0., 0.]), gate=Gradient([1., -2.]),
            context=Gradient([0., 0.]), residual=Gradient([.5, -.5]))
        torch = SimpleNamespace(linalg=SimpleNamespace(vector_norm=lambda value: math.sqrt(sum(v*v for v in value.flat()))))
        model = SimpleNamespace(_actor_feature_taps={name: SimpleNamespace(grad=gradients[name]) for name in ('context','residual')})
        named = {name: SimpleNamespace(grad=gradients[label]) for name,label in zip(ns['FEATURE_PARAMETER_NAMES'],('query','gate'))}
        result = ns['_feature_gradients'](torch,model,named,1)
        self.assertTrue(result['query_gradient_exact_zero']); self.assertGreater(result['gate_gradient_l2'],0)
        named['actor_attention.query'].grad = Gradient([.1,0.])
        with self.assertRaisesRegex(ValueError,'first zero-initialized'): ns['_feature_gradients'](torch,model,named,1)
        ns['_feature_gradients'](torch,model,named,2)
        model._actor_feature_taps['context'].grad = None
        with self.assertRaisesRegex(ValueError,'finite connected'): ns['_feature_gradients'](torch,model,named,2)

    def test_freeze_trace_permits_feature_changes_and_refuses_original_changes(self):
        ns = owner_namespace(); _,_,checkpoint=fixture(ns)
        before=checkpoint['initial_branch_digests']; after=copy.deepcopy(before)
        after['actor_context_gate_sha256']='d'*64
        batch=dict(optimizer_step=1,indices=[0],ids=['train-0'])
        entry=dict(batch, frozen_before=ns['SOURCE_SPLIT_MODEL_SHA256'],frozen_after=ns['SOURCE_SPLIT_MODEL_SHA256'],
            inactive_before=before['inactive_actor_head_rows_sha256'],inactive_after=before['inactive_actor_head_rows_sha256'],
            frozen_head_sample_sha256='e'*64,frozen_gradients_none=True,trainable_gradients_finite_nonNone=True,
            inactive_gradients_zero=True,inactive_moments_zero=True,changed_parameter_names=['actor_context.gate'],
            completed_returned_update=True,branch_digests_before=before,branch_digests_after=after)
        ns['_validate_freeze_entry'](entry,batch)
        for mutate in (lambda e:e['branch_digests_after'].update(modality_path_state_sha256='f'*64),
                       lambda e:e.update(changed_parameter_names=['start.weight']),
                       lambda e:e.update(inactive_moments_zero=False)):
            bad=copy.deepcopy(entry);mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_freeze_entry'](bad,batch)


if __name__ == '__main__':
    unittest.main()
