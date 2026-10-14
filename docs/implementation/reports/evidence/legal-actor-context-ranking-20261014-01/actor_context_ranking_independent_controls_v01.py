"""Detached F16 source controls using stdlib scalar graphs and synthetic rows.

No decoder, numerical package, checkpoint, saved-head or resource import/read.
The scalar graph checks the retained ranking kernel, not PyTorch numerics.
"""
import ast
import builtins
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import struct
from types import SimpleNamespace

F = Path(__file__).resolve().parent
SOURCE = F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_context_ranking.py'
TARGET = SOURCE.with_name('legal_span_targeted_loss.py')
TESTS = F / 'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_actor_context_ranking_contracts.py'
CASES = []


def require(ok, message):
    if not ok:
        raise ValueError(message)


def f32(value):
    return struct.unpack('!f', struct.pack('!f', float(value)))[0]


class Scalar:
    def __init__(self, value, gradients=None):
        self.value, self.gradients = f32(value), dict(gradients or {})

    @staticmethod
    def lift(value):
        return value if isinstance(value, Scalar) else Scalar(value)

    def binary(self, other, value, left, right):
        other = self.lift(other)
        keys = set(self.gradients) | set(other.gradients)
        return Scalar(value, {k: left * self.gradients.get(k, 0.) + right * other.gradients.get(k, 0.) for k in keys})

    def __add__(self, other):
        other = self.lift(other)
        return self.binary(other, self.value + other.value, 1., 1.)

    __radd__ = __add__

    def __sub__(self, other):
        other = self.lift(other)
        return self.binary(other, self.value - other.value, 1., -1.)

    def __rsub__(self, other):
        return self.lift(other).__sub__(self)

    def __mul__(self, other):
        other = self.lift(other)
        return self.binary(other, self.value * other.value, other.value, self.value)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self * (1. / float(other))

    def detach(self):
        return Scalar(self.value)

    def item(self):
        return self.value

    def __float__(self):
        return self.value


class Vector:
    dtype = 'float32'
    device = SimpleNamespace(type='cpu')

    def __init__(self, values):
        self.values = [Scalar.lift(v) for v in values]
        self.shape = (len(self.values),)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return Vector(self.values[key])
        if isinstance(key, list):
            return Vector([self.values[i] for i in key])
        return self.values[key]

    def detach(self):
        return Vector([v.detach() for v in self.values])

    def __add__(self, other):
        return Vector([a + b for a, b in zip(self.values, other.values, strict=True)])

    def __eq__(self, other):
        return Vector([float(v) == float(other) for v in self.values])

    def sum(self):
        return sum(self.values, Scalar(0.))

    def mean(self):
        return self.sum() / len(self.values)


class Matrix:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, key):
        position, role = key
        require(role == 0, 'only actor vectors may be requested')
        return self.rows[position]


def relu(value):
    return value if float(value) > 0 else Scalar(0., {k: 0. for k in value.gradients})


TORCH = SimpleNamespace(float32='float32', long='long',
    tensor=lambda values, dtype: list(values),
    argmax=lambda vector: Scalar(max(range(len(vector.values)), key=lambda i: float(vector.values[i]))),
    stack=lambda values: Vector(values), nn=SimpleNamespace(functional=SimpleNamespace(relu=relu)))


def detached_target():
    names = {'_require', '_raw', 'checkpoint_digest', '_f32', '_span_coordinates', '_actor_domain',
        '_actor_record', '_choose_actor_wrong', '_actor_auxiliary', '_combine_main_loss', '_combine_total_loss'}
    tree = ast.parse(TARGET.read_bytes())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    require({n.name for n in nodes} == names, 'exact retained helper set')
    require(not any(isinstance(n, (ast.Import, ast.ImportFrom)) for root in nodes for n in ast.walk(root)), 'detached imports refused')
    fields = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
    span = SimpleNamespace(tokenize_source=lambda text: [dict(text=t) for t in text.split()])
    ns = dict(hashlib=hashlib, json=json, math=math, struct=struct, span=span,
        SPAN_FIELDS=fields, MAX_SOURCE_TOKENS=128)
    def denied(name, *args, **kwargs):
        raise AssertionError('import forbidden in detached ranking kernel: ' + name)
    ns['__builtins__'] = dict(vars(builtins), __import__=denied)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(TARGET) + '#independent', 'exec'), ns)
    return ns


def record(count=5, object_present=True):
    tokens = [dict(text='token' + str(i)) for i in range(count)]
    return dict(id='independent-synthetic', source_text=' '.join(t['text'] for t in tokens), tokens=tokens,
        labels=dict(modality=0, presence=[True, True, object_present, False, False, False],
            spans=[[0, 0], [1, 1], [3, 3] if object_present else [-100, -100], [-100, -100], [-100, -100], [-100, -100]]))


def auxiliary(ns, row, starts, ends):
    return ns['_actor_auxiliary'](TORCH, dict(start=Matrix([Vector(starts)]), end=Matrix([Vector(ends)])), [row], True)


def passed(name):
    CASES.append(dict(name=name, passed=True))


def refuses(name, call):
    try:
        call()
    except (ValueError, TypeError, KeyError):
        passed(name)
        return
    raise AssertionError(name + ' was accepted')


def main():
    ns = detached_target()
    row = record()
    starts = [Scalar(0., {'s' + str(i): 1.}) for i in range(6)]
    ends = [Scalar(0., {'e' + str(i): 1.}) for i in range(6)]
    for i in (1, 3, 5):
        starts[i] = Scalar(1000., {'s' + str(i): 1.})
        ends[i] = Scalar(1000., {'e' + str(i): 1.})
    loss, diagnostics = auxiliary(ns, row, starts, ends)
    require(diagnostics[0]['chosen_wrong_coordinates'] == [2, 2]
        and diagnostics[0]['chosen_wrong_tie_count'] == 2
        and diagnostics[0]['compatible_wrong_candidate_count'] == 2, 'filtered row-major tie/padding domain')
    require(loss.gradients == dict(s2=1., e2=1., s0=-1., e0=-1.), 'selected and gold logits must retain graph')
    passed('present_gold_facets_padding_exactgold_excluded_stable_ties_and_both_score_gradients')
    loss, diagnostics = auxiliary(ns, record(object_present=False), starts, ends)
    require(diagnostics[0]['chosen_wrong_coordinates'] == [3, 3], 'absent role cannot filter a valid candidate')
    passed('absent_nonactor_role_does_not_filter')
    shared = record(count=3, object_present=False)
    starts = [Scalar(0., {'shared_start': 1.}), Scalar(99.), Scalar(-10.)]
    ends = [Scalar(0., {'gold_end': 1.}), Scalar(99.), Scalar(2., {'wrong_end': 1.})]
    shared['labels']['spans'][1] = [1, 1]
    loss, diagnostics = auxiliary(ns, shared, starts, ends)
    # With action at1, only2,2 is eligible; use an independent domain with action at2 instead.
    shared['labels']['spans'][1] = [2, 2]
    starts[1], ends[1] = Scalar(-10.), Scalar(2., {'wrong_end': 1.})
    starts[2], ends[2] = Scalar(99.), Scalar(99.)
    loss, diagnostics = auxiliary(ns, shared, starts, ends)
    require(diagnostics[0]['chosen_wrong_coordinates'] == [0, 1]
        and loss.gradients == dict(shared_start=0., gold_end=-1., wrong_end=1.), 'shared start derivative cancellation')
    passed('shared_boundary_derivative_cancels_without_detaching_other_boundary')
    empty = record(count=2, object_present=False)
    loss, diagnostics = auxiliary(ns, empty, [Scalar(.2, {'s0': 1.}), Scalar(.3, {'s1': 1.})],
        [Scalar(.1, {'e0': 1.}), Scalar(.4, {'e1': 1.})])
    require(float(loss) == 0. and diagnostics[0]['zero_domain_differentiable_zero'] is True
        and set(loss.gradients) == {'s0', 's1', 'e0', 'e1'} and all(v == 0 for v in loss.gradients.values()), 'connected empty-domain zero')
    passed('empty_domain_connected_zero_no_empty_argmax')
    q, g = Scalar(.2, {'query': 1.}), Scalar(.3, {'gate': 1.})
    trained = record(count=4, object_present=False)
    loss, _ = auxiliary(ns, trained, [q + .5 * g, Scalar(99.), Scalar(-10.), 2. * q + .7 * g],
        [.2 * q + .3 * g, Scalar(99.), Scalar(-10.), .5 * q + .4 * g])
    total = ns['_combine_total_loss'](Scalar(2., {'CE': 1.}), loss, True)
    require(abs(total.gradients['query'] - .325) < 1e-7 and abs(total.gradients['gate'] - .075) < 1e-7
        and total.gradients['CE'] == 1., 'nonzero trained query/gate graph and coefficient')
    passed('retained_kernel_connects_nonzero_trained_query_gate_through_point25_hinge')
    inactive, _ = auxiliary(ns, record(count=3, object_present=False), [Scalar(10., {'s': 1.}), Scalar(99.), Scalar(-10.)],
        [Scalar(10., {'e': 1.}), Scalar(99.), Scalar(-10.)])
    require(float(inactive) == 0. and all(v == 0 for v in inactive.gradients.values()), 'inactive ReLU gradient')
    passed('inactive_hinge_has_zero_ranking_gradient')
    for count in range(2, 8):
        others = {'action': (1, 1)}
        if count >= 4:
            others['object'] = (count - 1, count - 1)
        expected = [(a, b) for a in range(count) for b in range(count) if a <= b and (a, b) != (0, 0)
            and not any(set(range(a, b + 1)) & set(range(x, y + 1)) for x, y in others.values())]
        require(ns['_actor_domain'](count, (0, 0), others) == expected, 'independent full-domain enumeration')
    passed('six_sizes_match_independent_set_intersection_domain_oracle')
    refuses('overlapping_gold_facets_refused', lambda: ns['_actor_domain'](4, (0, 1), {'action': (1, 2)}))
    bad = record(); bad['tokens'][0]['text'] = 'different'
    refuses('teacher_record_token_text_mismatch_refused', lambda: ns['_actor_record'](bad))
    main_loss = ns['_combine_main_loss'](Scalar(2.), [Scalar(1., {'actor_facet': 1.}), *[Scalar(1.) for _ in range(5)]],
        {'conditions': Scalar(0.), 'exceptions': Scalar(0.)}, 1)
    require(float(main_loss) == 1.25 and main_loss.gradients['actor_facet'] == .125, 'legacy main denominator must remain8')
    passed('legacy_main_expression_and_actor_facet_scale_preserved')
    author = runpy.run_path(str(TESTS), run_name='independent_detached_contract_fixture')
    model = author['namespace'](); policy = model['_policy']('actor-context-ranking-hinge')
    require(policy['objective_policy']['actor_ranking_enabled'] is True and policy['objective_policy']['actor_hinge_coefficient'] == .25
        and policy['objective_policy']['actor_hinge_margin'] == 1. and policy['objective_policy']['normalization_denominator'] == 8, 'actual candidate policy')
    for key, value in [('actor_hinge_coefficient', .5), ('actor_hinge_margin', 2.), ('actor_ranking_enabled', False), ('normalization_denominator', 1)]:
        bad = copy.deepcopy(policy); bad['objective_policy'][key] = value
        refuses('policy_mutation_' + key, lambda bad=bad: model['_validate_policy'](bad))
    passed('candidate_policy_exact_ranking_and_legacy_main')
    # Construct actual candidate objective diagnostics using only synthetic source rows.
    rec = model['_training_records']([dict(id='s' + str(i), source_text='actor acts object') for i in range(168)])[1]
    target = model['targeted']; count, gold, others, domain = target._actor_record(rec)
    chosen = target._choose_actor_wrong([0., 0., 0.], [0., 0., 0.], count, gold, others)
    chosen.update(selection_implementation='vectorized_detached_source_boundary_gather', row_position=0, id=rec['id'],
        source_sha256=hashlib.sha256(rec['source_text'].encode()).hexdigest(), actor_hinge_value=1., hinge_active=True,
        gradient_enabled_by_policy=True, zero_domain_differentiable_zero=False, teacher_forced_compatibility=True, semantic_compatibility_verified=False)
    base = dict(schema='targeted-source-span-objective-diagnostics/v1', main_loss=1., actor_hinge_mean=1., actor_hinge_applied=True,
        actor_hinge_coefficient=.25, total_loss=1.25, presence_CE_means=dict(conditions=0., exceptions=0.), rows=[chosen],
        teacher_forcing=True, evaluation_references_used=False, semantic_compatibility_verified=False)
    target._loss = lambda *args: (Scalar(1.25), copy.deepcopy(base))
    _, details = model['_loss'](None, object(), [rec], [1], policy)
    batch = dict(optimizer_step=1, indices=[1], ids=[rec['id']], loss=1.25)
    entry = dict(optimizer_step=1, indices=[1], ids=[rec['id']], details=details)
    model['_validate_objective_entry'](entry, batch, policy)
    for value in (True, 1.):
        bad = copy.deepcopy(entry); bad['details']['rows'][0]['training_index'] = value
        refuses('row_training_index_type_' + type(value).__name__, lambda bad=bad: model['_validate_objective_entry'](bad, batch, policy))
    feature, feature_batch = author['feature_entry'](); model['_validate_feature_entry'](feature, feature_batch)
    passed('trained_first_query_nonzero_gradient_change_moments_accepted')
    public = json.loads((F.parent / 'legal-actor-refinement-20261014-01/public-result-summary-v01.json').read_bytes())
    review = json.loads((F.parent / 'legal-actor-refinement-20261014-01/actor-refinement-result-independent-review-v01.json').read_bytes())
    require(model['SOURCE_ACTOR_REFINEMENT_SHA256'] == public['checkpoint']['sha256']
        and model['SOURCE_ACTOR_REFINEMENT_MODEL_SHA256'] == public['final_model_state_sha256']
        and model['SOURCE_FROZEN36_SHA256'] == review['training_trace_recount']['source_frozen36_state_sha256'], 'actual public donor/frozen36 pins')
    passed('candidate_donor_and_frozen36_match_public_F15_metadata')
    def pin(path):
        raw = path.read_bytes()
        return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    value = dict(schema='actor-context-ranking-independent-source-controls/v1', passed=True, findings=[], count=len(CASES), controls=CASES,
        source=pin(SOURCE), retained_ranking_source=pin(TARGET), control_source=pin(Path(__file__).resolve()),
        limits=['Scalar graph is a stdlib synthetic control of the actual retained ranking kernel, not PyTorch or model numerical qualification.',
            'Simple synthetic tokenization stub; no actual training or evaluation rows read.', 'No complete training-time argmax replay from recorded selected scores is claimed.'],
        model_calls=0, numerical_imports=0, checkpoint_JSON_parses=0, actual_training_updates=0, reference_packet_body_reads=0,
        saved_head_body_reads=0, private_resource_body_reads=0, SDK_calls=0, claims=0)
    out = F / 'model-independent-source-controls-v01.json'
    with out.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    out.chmod(0o444)
    print(json.dumps(pin(out)))


if __name__ == '__main__':
    main()
