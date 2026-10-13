"""Actor contracts using detached stdlib owners; numerical imports are forbidden."""
import ast
import builtins
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[4] / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_boundary.py'
SPLIT = SOURCE.with_name('legal_span_split_features.py')


def require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def deny_import(name, *args, **kwargs):
    raise AssertionError('Detached actor contracts cannot import: ' + name)


def coordinates(value, count):
    require(type(value) in (list, tuple) and len(value) == 2
        and all(type(v) is int for v in value) and 0 <= value[0] <= value[1] < count, 'coordinates')
    return tuple(value)


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
    def actor_record(record):
        require(record['labels']['presence'][0] is True, 'mandatory actor')
        count = len(record['tokens'])
        gold = coordinates(record['labels']['spans'][0], count)
        return count, gold, {}, []
    def bounded(rows, tuning):
        require(type(rows) in (list, tuple) and len(rows) == 168 and not tuning, 'training only')
        return [dict(id=r['id'], source_text=r['source_text'], tokens=[{}, {}, {}],
            labels=dict(presence=[True, True, False, False, False, False],
                spans=[(0, 0), (1, 1), (-100, -100), (-100, -100), (-100, -100), (-100, -100)])) for r in rows], []
    targeted = SimpleNamespace(MAX_BYTES=128*1024*1024, LEGACY96_SHA256='d'*64,
        _policy=lambda seed, **kw: dict(seed=seed, **kw), _implementation=lambda: {'inert': 'targeted'},
        _progress=progress, _batch_indices=indices, _bounded_splits=bounded, _actor_record=actor_record,
        _span_coordinates=coordinates,
        _validate_objective_diagnostics=lambda d: require(set(d) == {'total_loss', 'rows'} and d['total_loss'] == 2., 'base diagnostic'))
    split = SimpleNamespace(MODEL_PARAMETER_NAMES=names, _implementation=lambda: {'inert': 'split'},
        _validated=lambda source: require(set(source['model_state']) == set(names), 'source34'),
        _branch_digests=lambda state: dict.fromkeys(('modality_feature_state_sha256', 'span_feature_state_sha256',
            'modality_path_state_sha256', 'span_path_state_sha256', 'dormant_latent_state_sha256'), digest(state)))
    continuation = SimpleNamespace(_implementation=lambda: {'inert': 'continuation'}, _context_contract=copy.deepcopy)
    namespace = dict(__file__=str(SOURCE), __name__='detached_actor_boundary', copy=copy, hashlib=hashlib,
        json=json, math=math, Path=Path, split=split, targeted=targeted, continuation=continuation, span=span)
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
    rows = [dict(id='train-' + str(index), source_text='source ' + str(index)) for index in range(168)]
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


def fake_model_forward(namespace):
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
    torch.get_rng_state = lambda: Value()
    torch.equal = lambda left, right: True
    torch.no_grad = Guard
    torch.cat = lambda values, dim: Value([row for value in values for row in value.rows])
    namespace['split']._model = lambda owner, config: Base()
    model = namespace['_model'](torch, dict(hidden_size=32))
    require(model.actor_start is not model.start and model.actor_end is not model.end, 'head aliases')
    model.actor_start.tag, model.actor_end.tag = 'actor_start', 'actor_end'
    output = model.forward(Value(), Value(), Value(), Value())
    return model, output, calls


class ActorBoundaryContracts(unittest.TestCase):
    def setUp(self): self.ns = owner_namespace()

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
        policy = ns['_policy']('actor-boundary-ce')
        self.assertFalse(policy['objective_policy']['actor_ranking_enabled'])
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
            return total, {'total_loss': 2., 'rows': [dict(id=r['id'], token_count=3, gold_coordinates=[0, 0]) for r in batch]}
        ns['targeted']._loss = base_loss
        actual, details = ns['_loss'](None, output, records[:2], [0, 1], ns['_policy']('actor-boundary-ce'))
        self.assertIs(actual, total)
        self.assertIs(calls[0][0], output)
        entry = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], details=details)
        batch = dict(optimizer_step=1, indices=[0, 1], ids=['train-0', 'train-1'], loss=2.)
        ns['_validate_objective_entry'](entry, batch, ns['_policy']('actor-boundary-ce'))
        for mutate in (lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[2, 3]),
                       lambda e: e['details']['rows'][0].update(actor_gold_coordinates=[1, 1]),
                       lambda e: e['details']['rows'][0].update(training_index=167),
                       lambda e: e['details'].update(total_loss=2.5)):
            bad = copy.deepcopy(entry); mutate(bad)
            with self.assertRaises(ValueError): ns['_validate_objective_entry'](bad, batch, ns['_policy']('actor-boundary-ce'))

    def test_inference_and_capture_reject_129_before_restore_or_target_access(self):
        tree = ast.parse(SOURCE.read_bytes())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SpanActorBoundaryAdapterDecoder')
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
