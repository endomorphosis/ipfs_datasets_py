"""Finite genuine predicate-profile update/resume integration, not a learning fit.

Exactly two numerical cases select the two normalization domains. Each owns two
model/Adam restores and three physical updates: row0, row1, saved-step1→row1.
All malformed-input controls must refuse without extra numerical lifecycle.
Original packets are immutable witnesses; no legacy validator is replaced.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import time

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_predicate_training_v1 as subject,
    legal_compact_content_predicate_objective_v1 as diagnostic,
    legal_compact_content_role_warmstart_training_v1 as legacy,
    legal_compact_content_role_warmstart_runtime_v1 as old_runtime,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


EXPORTS = Path(os.environ.get('LEGAL_IR_CP128_EXPORTS', Path(__file__).parents[4] /
    'workspace/test-logs/federal-corpus-audits/owned-validation-runs/'
    'cp128-warmstart-qualification-v01-cp128-warmstart-mechanics/exports'))
INPUTS = {
    'full537': {
        'row0': dict(name='full537-step-0.json', bytes=2704855,
            raw_sha256='599da742ac6bb76c59ae38ac3274fbe37e8064bfa22be5eb3493baea5916fbf3',
            checkpoint_sha256='1ef7d777554bea20aa1d77209f55f1eb987598e44a18b737a1d3541e2683ab12'),
        'row1': dict(name='full537-step-1.json', bytes=3228182,
            raw_sha256='155497cfafe703c7c99b44df7d44a525099655a76000ed6dd75f24fe7f386b25',
            checkpoint_sha256='e69ea83a93cade5898578841b864311cae90643afda5a7eb9a220cb2e6120a11'),
        'legacy_policy_sha256': '0ed591ba2aa4eb4e12fa82766cd1436054438540e64a338ab5177cf77e946c6f',
    },
    'scope_conditional': {
        'row0': dict(name='scope_conditional-step-0.json', bytes=2704885,
            raw_sha256='5458464a4ebadef9820247d9dd025e255d498c508b3c039c2afdff8e03d7fc23',
            checkpoint_sha256='a6b6b0cd589a74d59598c6984040676baf6f27a24a7b61f0ba0a6a5f38d5f64e'),
        'row1': dict(name='scope_conditional-step-1.json', bytes=3052648,
            raw_sha256='2823d625237dda8d51e57a7d370fd0baac45a5e0085482a4aa92fa4a85b8f398',
            checkpoint_sha256='9d93601d35dc371ea6895e1deca175b7b41b6279a05400c695edfaa2c8e96116'),
        'legacy_policy_sha256': '701807e4e15652321efe70c29ffa894e6626776ef5df872447cb270ca0dd1c3a',
    },
}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


@pytest.fixture(scope='session')
def retained_packets():
    if 'LEGAL_IR_CP128_EXPORTS' not in os.environ and any(
            not (EXPORTS / INPUTS[kind][row]['name']).is_file()
            for kind in INPUTS for row in ('row0', 'row1')):
        pytest.skip('retained CP128 checkpoint evidence is not installed in this checkout')
    assert EXPORTS.is_absolute() and EXPORTS.is_dir()
    result = {}
    for kind, expected in INPUTS.items():
        result[kind] = {}
        for index, row in enumerate(('row0', 'row1')):
            descriptor = expected[row]
            raw = (EXPORTS / descriptor['name']).read_bytes()
            assert len(raw) == descriptor['bytes']
            assert hashlib.sha256(raw).hexdigest() == descriptor['raw_sha256']
            value = json.loads(raw)
            assert digest(value) == descriptor['checkpoint_sha256']
            assert value['objective_policy_sha256'] == expected['legacy_policy_sha256']
            assert value['objective_policy']['objective_kind'] == kind
            assert value['progress']['row_cursor'] == value['progress']['optimizer_steps'] == index
            result[kind][row] = value
    return result


@pytest.fixture(params=('full537', 'scope_conditional'))
def case(request, retained_packets):
    kind = request.param
    return kind, deepcopy(retained_packets[kind]), deepcopy(INPUTS[kind])


def create(case, **overrides):
    kind, references, expected = case
    options = dict(expected_reference_checkpoint_sha256={
        row: expected[row]['checkpoint_sha256'] for row in ('row0', 'row1')},
        expected_legacy_policy_sha256=expected['legacy_policy_sha256'], objective_kind=kind)
    options.update(overrides)
    return subject.create(references, **options)


def options(checkpoint, references, **overrides):
    result = dict(reference_inputs=references, expected_checkpoint_sha256=digest(checkpoint),
        expected_policy_sha256=checkpoint['objective_policy_sha256'])
    result.update(overrides)
    return result


class Captures:
    def __init__(self, kind, tmp_path):
        self.kind = kind
        self.root = Path(os.environ.get('LEGAL_IR_PREDICATE_TRAINING_CAPTURES', tmp_path))
        assert self.root.is_absolute() and self.root.resolve(strict=True) == self.root
        self.files = {}

    def save(self, name, value):
        assert name not in self.files and Path(name).name == name
        raw = wire(value) + b'\n'
        assert len(raw) <= 12 * 1024**2
        path = self.root / (self.kind + '-' + name)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.files[name] = dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return self.files[name]

    def read(self, name):
        item = self.files[name]
        raw = Path(item['path']).read_bytes()
        assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
        return json.loads(raw)


def coordinates(value):
    return sum(coordinates(child) for child in value) if type(value) is list else 1


def independent_objective(logits, labels, allowed, weights, observed_loss, gradient):
    """Direct stdlib CE and all actual same-backward logit coordinates."""
    assert len(logits) == len(gradient) == 1
    assert len(logits[0]) == len(gradient[0]) == len(labels) == len(allowed) == len(weights) == 46
    assert math.fsum(weights) == 70
    losses, checked, max_error = [], 0, 0.0
    for index, (scores, target, choices, weight) in enumerate(zip(logits[0], labels, allowed, weights)):
        assert len(scores) == len(gradient[0][index]) == 537 and target in choices
        peak = max(scores[token] for token in choices)
        exps = {token: math.exp(scores[token] - peak) for token in choices}
        denominator = math.fsum(exps.values())
        losses.append((math.log(denominator) + peak - scores[target]) * weight / 70)
        for token, observed in enumerate(gradient[0][index]):
            expected = (exps[token] / denominator - (token == target)) * weight / 70 if token in exps else 0.0
            assert math.isfinite(observed) and math.isclose(observed, expected, rel_tol=3e-5, abs_tol=2e-8)
            if len(choices) == 1 or token not in exps:
                assert observed == 0.0
            checked += 1
            max_error = max(max_error, abs(observed - expected))
    expected_loss = math.fsum(losses)
    assert checked == 24702
    assert math.isclose(observed_loss, expected_loss, rel_tol=3e-6, abs_tol=2e-6)
    return dict(checked_logit_gradient_coordinates=checked, expected_loss=expected_loss,
        max_absolute_logit_gradient_error=max_error)


def independent_parameter_checks(before, after, logit_gradient):
    """Bias-gradient identity plus finite complete parameter gradients/clip."""
    assert list(before) == list(after) and len(before) == 13
    flattened = []
    def finite(value):
        if type(value) is list:
            for child in value:
                finite(child)
        else:
            assert type(value) is float and math.isfinite(value)
            flattened.append(value)
    for tensor in before.values():
        finite(tensor)
    assert len(flattened) == 16101
    l2 = math.sqrt(math.fsum(value * value for value in flattened))
    scale = min(1.0, 5.0 / (l2 + 1e-6))
    bias = before['output.bias']
    assert len(bias) == 537
    errors = []
    for token, observed in enumerate(bias):
        expected = math.fsum(row[token] for row in logit_gradient[0])
        assert math.isclose(observed, expected, rel_tol=3e-5, abs_tol=2e-7)
        errors.append(abs(observed - expected))
    def clipped(a, b):
        if type(a) is list:
            assert type(b) is list and len(a) == len(b)
            for x, y in zip(a, b):
                clipped(x, y)
        else:
            assert type(b) is float and math.isfinite(b)
            assert math.isclose(b, a * scale, rel_tol=3e-5, abs_tol=2e-8)
    for name in before:
        clipped(before[name], after[name])
    return dict(parameter_gradient_coordinates=16101, checked_bias_gradient_coordinates=537,
        independent_preclip_l2=l2, clipping_active=l2 > 5,
        max_absolute_bias_gradient_error=max(errors))


def independent_adam_checks(before_weights, after_weights, before_state, after_state, gradients, step):
    """Stdlib named moment and parameter arithmetic, with float32 tolerances."""
    # Canonical JSON sorts checkpoint-map keys; actual model order is checked
    # independently against parameter_order by the trace and genuine owners.
    assert set(before_weights) == set(after_weights) == set(gradients)
    assert len(before_weights) == 13
    assert set(after_state['parameters']) == set(before_weights)
    assert set(before_state['parameters']) == (set(before_weights) if step > 1 else set())
    checked, maximum = 0, dict(first_moment=0.0, second_moment=0.0, parameter=0.0)
    def zero_like(value):
        return [zero_like(child) for child in value] if type(value) is list else 0.0
    def visit(a, b, g, old_m, old_v, new_m, new_v):
        nonlocal checked
        if type(a) is list:
            assert all(type(value) is list and len(value) == len(a)
                for value in (b, g, old_m, old_v, new_m, new_v))
            for values in zip(a, b, g, old_m, old_v, new_m, new_v):
                visit(*values)
            return
        assert all(type(value) is float and math.isfinite(value)
            for value in (a, b, g, old_m, old_v, new_m, new_v))
        expected_m = 0.9 * old_m + 0.1 * g
        expected_v = 0.999 * old_v + 0.001 * g * g
        assert new_v >= 0 and math.isclose(new_m, expected_m, rel_tol=3e-5, abs_tol=2e-8)
        assert math.isclose(new_v, expected_v, rel_tol=3e-5, abs_tol=2e-10)
        expected_parameter = a - (0.001 / (1 - 0.9 ** step)) * new_m / (
            math.sqrt(new_v) / math.sqrt(1 - 0.999 ** step) + 1e-8)
        assert math.isclose(b, expected_parameter, rel_tol=3e-5, abs_tol=2e-7)
        if g == old_m == old_v == 0.0:
            assert b == a and new_m == new_v == 0.0
        maximum['first_moment'] = max(maximum['first_moment'], abs(new_m - expected_m))
        maximum['second_moment'] = max(maximum['second_moment'], abs(new_v - expected_v))
        maximum['parameter'] = max(maximum['parameter'], abs(b - expected_parameter))
        checked += 1
    for name in gradients:
        stored = after_state['parameters'][name]
        assert type(stored['step']) is int and stored['step'] == step
        previous = before_state['parameters'].get(name)
        if previous is None:
            old_m = old_v = zero_like(before_weights[name])
        else:
            assert previous['step'] == step - 1
            old_m, old_v = previous['exp_avg'], previous['exp_avg_sq']
        visit(before_weights[name], after_weights[name], gradients[name], old_m, old_v,
            stored['exp_avg'], stored['exp_avg_sq'])
    assert checked == 16101
    return dict(checked_parameter_and_each_moment_coordinates=checked,
        first_moment_coordinates=checked, second_moment_coordinates=checked,
        maximum_absolute_errors=maximum, parameter_abs_tolerance=2e-7,
        first_moment_abs_tolerance=2e-8, second_moment_abs_tolerance=2e-10,
        relative_tolerance=3e-5, first_step_gradient_proportionality_claimed=False)


class TrainingTrace:
    """Observe genuine factories, one loss graph and named updates, never doubles."""
    def __init__(self, monkeypatch, references):
        self.references = references
        self.counts = dict(model_allocations=0, adam_allocations=0, optimizer_base_allocations=0,
            forwards=0, gru_forwards=0, backwards=0, clips=0, adam_steps=0,
            diagnostic_completed=0, diagnostic_refused=0, legacy_objectives=0,
            logits_gradient_hooks=0, legacy_restores=0, forbidden_calls=0,
            nonfinite_objective_refusals=0, diagnostic_return_refusals=0,
            pack_without_update_refusals=0)
        self.active = dict(phase='pure', model=None, optimizer=None, checkpoint=None, item=None)
        self.reports = []
        self.handles = []
        self.return_damage = None
        real_model, real_adam, real_base = numerical._model, torch.optim.Adam.__init__, torch.optim.Optimizer.__init__
        real_gru, real_backward = torch.nn.GRU.forward, torch.autograd.backward
        real_clip, real_step = torch.nn.utils.clip_grad_norm_, torch.optim.Adam.step
        real_diagnostic, real_objective, real_restore = diagnostic.objective, legacy.objective, legacy.restore

        def construct_model(*args, **kwargs):
            assert self.active['phase'] == 'restore' and self.active['model'] is None
            assert self.counts['model_allocations'] < 2
            self.counts['model_allocations'] += 1
            model = real_model(*args, **kwargs)
            self.active['model'] = model
            self.handles.extend((model.register_forward_pre_hook(self.before_forward),
                model.register_forward_hook(self.after_forward)))
            return model

        def construct_adam(optimizer, *args, **kwargs):
            assert self.active['phase'] == 'restore' and self.active['optimizer'] is None
            assert self.counts['adam_allocations'] < 2
            self.counts['adam_allocations'] += 1
            value = real_adam(optimizer, *args, **kwargs)
            self.active['optimizer'] = optimizer
            return value

        def construct_base(optimizer, *args, **kwargs):
            assert self.active['phase'] == 'restore'
            assert self.counts['optimizer_base_allocations'] + 1 == self.counts['adam_allocations']
            self.counts['optimizer_base_allocations'] += 1
            return real_base(optimizer, *args, **kwargs)

        def old_restore(reference, **kwargs):
            assert self.active['phase'] == 'restore' and digest(reference) == digest(self.references['row0'])
            self.counts['legacy_restores'] += 1
            return real_restore(reference, **kwargs)

        def gru(module, *args, **kwargs):
            item = self.active['item']
            assert self.active['phase'] == 'train' and item is not None and not item['gru']
            assert module is self.active['model'].decoder and self.counts['gru_forwards'] < 3
            self.counts['gru_forwards'] += 1
            value = real_gru(module, *args, **kwargs)
            item['gru'] = True
            return value

        def objective_reference(reference, logits, **kwargs):
            assert self.active['phase'] == 'train' and self.active['item'] is not None
            index = self.active['checkpoint']['progress']['row_cursor']
            expected = self.references['row' + str(index)]
            assert digest(reference) == digest(expected)
            assert kwargs['expected_checkpoint_sha256'] == digest(expected)
            assert kwargs['expected_policy_sha256'] == expected['objective_policy_sha256']
            try:
                value = real_diagnostic(reference, logits, **kwargs)
            except ValueError:
                self.counts['diagnostic_refused'] += 1
                raise
            self.counts['diagnostic_completed'] += 1
            if self.return_damage is not None:
                report = value[1]
                if self.return_damage == 'current-state-reference':
                    report['legacy_checkpoint_sha256'] = digest(self.active['checkpoint'])
                else:
                    report['proposed_position_weights'][report['predicate_position_index']] = 1.0
                return value
            assert self.active['item']['diagnostic_scalar'] is None
            self.active['item']['diagnostic_scalar'] = value[0]
            self.active['item']['diagnostic_report'] = deepcopy(value[1])
            return value

        def original_objective(*args, **kwargs):
            assert self.active['phase'] == 'train'
            self.counts['legacy_objectives'] += 1
            return real_objective(*args, **kwargs)

        def backward(*args, **kwargs):
            item = self.active['item']
            assert self.active['phase'] == 'train' and item is not None and item['gru'] and not item['backward']
            offered = args[0] if args else kwargs.get('tensors')
            if isinstance(offered, (tuple, list)):
                assert len(offered) == 1
                offered = offered[0]
            assert offered is item['diagnostic_scalar'] is self.active['loss']
            assert self.counts['backwards'] < 3
            value = real_backward(*args, **kwargs)
            self.counts['backwards'] += 1
            item['backward'] = True
            return value

        def clip(parameters, *args, **kwargs):
            item = self.active['item']
            assert item is not None and item['backward'] and not item['clipped']
            offered, expected = list(parameters), list(self.active['model'].parameters())
            assert len(offered) == len(expected) and all(a is b for a, b in zip(offered, expected))
            assert args == (5.0,) and kwargs == {'error_if_nonfinite': True}
            item['preclip_gradients'] = self.gradients()
            value = real_clip(offered, *args, **kwargs)
            item['postclip_gradients'] = self.gradients()
            item['actual_preclip_l2'] = float(value)
            self.counts['clips'] += 1
            item['clipped'] = True
            return value

        def step(optimizer, *args, **kwargs):
            item = self.active['item']
            assert optimizer is self.active['optimizer'] and item is not None
            assert item['clipped'] and not item['updated'] and not args and not kwargs
            assert self.counts['adam_steps'] < 3
            item['before_optimizer_state'] = numerical._pack(self.active['model'], optimizer)[1]
            value = real_step(optimizer)
            self.counts['adam_steps'] += 1
            item['after_weights'], item['after_optimizer_state'] = numerical._pack(self.active['model'], optimizer)
            item['updated'] = True
            return value

        def forbidden(*args, **kwargs):
            self.counts['forbidden_calls'] += 1
            raise AssertionError('undeclared differentiation or legacy checkpoint packing')

        for module, name, function in ((numerical, '_model', construct_model),
                (torch.optim.Adam, '__init__', construct_adam), (torch.optim.Optimizer, '__init__', construct_base),
                (torch.nn.GRU, 'forward', gru), (torch.autograd, 'backward', backward),
                (torch.nn.utils, 'clip_grad_norm_', clip), (torch.optim.Adam, 'step', step),
                (diagnostic, 'objective', objective_reference), (legacy, 'objective', original_objective),
                (legacy, 'restore', old_restore), (legacy, 'pack', forbidden),
                (torch.autograd, 'grad', forbidden)):
            monkeypatch.setattr(module, name, function)

    def state(self, model):
        return {name: value.detach().tolist() for name, value in model.state_dict().items()}

    def gradients(self):
        result = {}
        for name, parameter in self.active['model'].named_parameters():
            assert parameter.grad is not None and parameter.grad.dtype is torch.float32
            assert parameter.grad.device.type == 'cpu' and torch.isfinite(parameter.grad).all()
            result[name] = parameter.grad.detach().tolist()
        assert list(result) == self.active['checkpoint']['parameter_order']
        assert sum(coordinates(value) for value in result.values()) == 16101
        return result

    def before_forward(self, model, args):
        assert self.active['phase'] == 'train' and model is self.active['model']
        assert self.active['item'] is None and self.counts['forwards'] < 3
        cp = self.active['checkpoint']
        index = cp['progress']['row_cursor']
        reference = self.references['row' + str(index)]
        original = reference['warmstart_parent_checkpoint']['basis_checkpoint']['rows_utf8'][index]
        target_ids = reference['warmstart_parent_checkpoint']['role_inventories'][index]['target_ids']
        vector, prefix = args
        assert model.training and torch.is_grad_enabled() and not torch.is_inference_mode_enabled()
        assert all(parameter.grad is None for parameter in model.parameters())
        assert vector.dtype is torch.float32 and vector.device.type == 'cpu' and list(vector.shape) == [1, 384]
        assert vector.detach().tolist() == torch.tensor([original['conditioning']], dtype=torch.float32).tolist()
        assert prefix.dtype is torch.long and prefix.device.type == 'cpu'
        assert prefix.detach().tolist() == [target_ids[:-1]]
        assert self.state(model) == cp['model_state']
        self.active['item'] = dict(gru=False, backward=False, clipped=False, updated=False,
            diagnostic_scalar=None, logits_gradient=None, before_weights=deepcopy(cp['model_state']))
        self.counts['forwards'] += 1

    def after_forward(self, model, args, output):
        item = self.active['item']
        projected, logits = output
        assert item is not None and item['gru'] and model is self.active['model']
        assert list(projected.shape) == [1, 384] and list(logits.shape) == [1, 46, 537]
        assert logits.dtype is torch.float32 and logits.device.type == 'cpu' and logits.requires_grad
        assert torch.isfinite(projected).all() and torch.isfinite(logits).all()
        item['logits'] = logits.detach().tolist()
        def observe_gradient(gradient):
            assert self.active['item'] is item and item['logits_gradient'] is None
            assert list(gradient.shape) == [1, 46, 537] and torch.isfinite(gradient).all()
            item['logits_gradient'] = gradient.detach().tolist()
            self.counts['logits_gradient_hooks'] += 1
        self.handles.append(logits.register_hook(observe_gradient))


def test_predicate_training_genuine_two_steps_and_serialized_resume(case, monkeypatch, tmp_path):
    kind, references, expected = case
    original_references = digest(references)
    rng = torch.get_rng_state().clone()
    trace = TrainingTrace(monkeypatch, references)
    captures = Captures(kind, tmp_path)
    initial = create(case)
    parent = references['row0']['warmstart_parent_checkpoint']
    assert initial['model_state'] == parent['model_state']
    assert initial['weights_sha256'] == parent['weights_sha256']
    assert initial['optimizer_state']['parameters'] == {}
    assert initial['progress'] == dict(optimizer_steps=0, epochs_completed=0, row_cursor=0)
    assert len(initial['parameter_order']) == 13 and sum(coordinates(x) for x in initial['model_state'].values()) == 16101
    assert initial['causal_gradient_history_attested'] is False
    captures.save('initial.json', initial)

    def restore(checkpoint):
        trace.active.update(phase='restore', checkpoint=checkpoint, model=None, optimizer=None, item=None)
        model, optimizer = subject.restore(checkpoint, **options(checkpoint, references))
        assert model is trace.active['model'] and optimizer is trace.active['optimizer']
        weights, moments = numerical._pack(model, optimizer)
        assert weights == checkpoint['model_state'] and moments == checkpoint['optimizer_state']
        assert type(optimizer) is torch.optim.Adam and optimizer.param_groups[0]['lr'] == 0.001
        assert optimizer.param_groups[0]['betas'] == (0.9, 0.999) and optimizer.param_groups[0]['eps'] == 1e-8
        assert torch.equal(rng, torch.get_rng_state())
        return model, optimizer

    def update(checkpoint, model, optimizer, label, *, refuse_nan=False):
        trace.active.update(phase='train', checkpoint=checkpoint, model=model, optimizer=optimizer, item=None, loss=None)
        before = digest(checkpoint)
        row = subject.training_row(checkpoint, **options(checkpoint, references))
        assert math.fsum(row['position_weights']) == 67 and math.fsum(row['proposed_position_weights']) == 70
        assert [i for i, pair in enumerate(zip(row['position_weights'], row['proposed_position_weights'])) if pair[0] != pair[1]] == [row['position_roles'].index('predicate_constructor')]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        started = time.perf_counter()
        vector = torch.tensor([row['conditioning']], dtype=torch.float32, device='cpu')
        prefix = torch.tensor([row['target_ids'][:-1]], dtype=torch.long, device='cpu')
        _, logits = model(vector, prefix)
        if refuse_nan:
            token = next(i for i in range(537) if i not in row['scope_allowed_token_ids'][0])
            damaged = logits.clone()
            with torch.no_grad():
                damaged[0, 0, token] = float('nan')
            with pytest.raises(ValueError):
                subject.objective(checkpoint, damaged, **options(checkpoint, references))
            trace.counts['nonfinite_objective_refusals'] += 1
            assert logits.isfinite().all()
            trace.return_damage = 'current-state-reference' if kind == 'full537' else 'weight'
            try:
                with pytest.raises(ValueError):
                    subject.objective(checkpoint, logits, **options(checkpoint, references))
                trace.counts['diagnostic_return_refusals'] += 1
            finally:
                trace.return_damage = None
            assert trace.active['item']['diagnostic_scalar'] is None
        loss, report = subject.objective(checkpoint, logits, **options(checkpoint, references))
        assert loss is trace.active['item']['diagnostic_scalar']
        assert report['diagnostic_report'] == trace.active['item']['diagnostic_report']
        assert report['diagnostic_report_sha256'] == digest(report['diagnostic_report'])
        reference_pin = digest(references['row' + str(row['row_index'])])
        assert report['checkpoint_sha256'] == digest(checkpoint)
        assert report['objective_policy_sha256'] == checkpoint['objective_policy_sha256']
        assert report['progress'] == checkpoint['progress'] and report['row_index'] == row['row_index']
        assert report['reference_checkpoint_sha256'] == reference_pin
        assert report['diagnostic_report']['legacy_checkpoint_sha256'] == reference_pin
        assert report['reference_context_not_current_model_state'] is True
        assert report['logits_origin_independently_verified'] is False
        assert report['causal_gradient_history_attested'] is report['legacy_checkpoint_compatible'] is False
        assert report['authority'] and all(value is False for value in report['authority'].values())
        assert type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
        assert report['training_mask'] == report['evaluation_gold_mask'] == 0
        assert report['diagnostic_report']['new_training_profile_status'] == 'UNIMPLEMENTED'
        assert report['diagnostic_report']['new_checkpoint_profile_status'] == 'UNIMPLEMENTED'
        trace.active['loss'] = loss
        loss.backward()
        item = trace.active['item']
        allowed = row['scope_allowed_token_ids'] if kind == 'scope_conditional' else [list(range(537)) for _ in range(46)]
        analytic = independent_objective(item['logits'], row['target_ids'][1:], allowed,
            row['proposed_position_weights'], float(loss.detach()), item['logits_gradient'])
        torch.nn.utils.clip_grad_norm_(list(model.parameters()), 5.0, error_if_nonfinite=True)
        parameter_checks = independent_parameter_checks(item['preclip_gradients'], item['postclip_gradients'], item['logits_gradient'])
        assert math.isclose(item['actual_preclip_l2'], parameter_checks['independent_preclip_l2'], rel_tol=3e-5, abs_tol=2e-7)
        optimizer.step()
        steps = checkpoint['progress']['optimizer_steps'] + 1
        adam_checks = independent_adam_checks(item['before_weights'], item['after_weights'],
            item['before_optimizer_state'], item['after_optimizer_state'], item['postclip_gradients'], steps)
        successor = subject.pack(model, optimizer, checkpoint,
            dict(optimizer_steps=steps, epochs_completed=steps // 2, row_cursor=steps % 2),
            **options(checkpoint, references))
        assert successor['model_state'] == item['after_weights']
        assert successor['optimizer_state'] == item['after_optimizer_state']
        assert successor['weights_sha256'] == digest(item['after_weights'])
        assert successor['optimizer_state_sha256'] == digest(item['after_optimizer_state'])
        assert successor['parent_checkpoint_sha256'] == digest(checkpoint)
        assert successor['objective_policy_sha256'] == checkpoint['objective_policy_sha256']
        assert successor['causal_gradient_history_attested'] is False
        assert item['after_weights'] != checkpoint['model_state'] and item['after_optimizer_state'] != checkpoint['optimizer_state']
        assert all(value['step'] == steps for value in successor['optimizer_state']['parameters'].values())
        assert digest(checkpoint) == before and digest(references) == original_references
        observation = dict(label=label, row_index=row['row_index'], checkpoint_before_sha256=before,
            checkpoint_after_sha256=digest(successor), objective_kind=kind,
            current_weights_before_sha256=checkpoint['weights_sha256'],
            reference_checkpoint_sha256=digest(references['row' + str(row['row_index'])]),
            loss=float(loss.detach()), objective_report=report, logits=item['logits'],
            logit_gradient=item['logits_gradient'], preclip_gradients=item['preclip_gradients'],
            postclip_gradients=item['postclip_gradients'], preclip_l2=item['actual_preclip_l2'],
            independently_checked_objective=analytic, independently_checked_parameter_gradients=parameter_checks,
            independently_checked_Adam=adam_checks,
            teacher_prefix_ids=row['target_ids'][:-1], labels=row['target_ids'][1:],
            proposed_weights=row['proposed_position_weights'], scope_allowed_token_ids=row['scope_allowed_token_ids'],
            training_mask=0, evaluation_gold_mask=0,
            elapsed_seconds=time.perf_counter() - started)
        for key in ('logits', 'logit_gradient', 'preclip_gradients', 'postclip_gradients'):
            observation[key + '_sha256'] = digest(observation[key])
        captures.save(label + '.json', successor)
        captures.save(label + '-report.json', observation)
        trace.reports.append(observation)
        trace.active.update(phase='pure', item=None, loss=None)
        return successor

    try:
        model, optimizer = restore(initial)
        with pytest.raises(ValueError):
            subject.pack(model, optimizer, initial,
                dict(optimizer_steps=1, epochs_completed=0, row_cursor=1),
                **options(initial, references))
        trace.counts['pack_without_update_refusals'] += 1
        one = update(initial, model, optimizer, 'step-1', refuse_nan=True)
        two = update(one, model, optimizer, 'step-2')
        model, optimizer = restore(captures.read('step-1.json'))
        repeated = update(captures.read('step-1.json'), model, optimizer, 'resume-step-2')
        assert wire(two) == wire(repeated) == wire(captures.read('step-2.json'))
        a, b = trace.reports[1:]
        fields = ('loss', 'logits', 'logit_gradient', 'preclip_gradients', 'postclip_gradients',
            'preclip_l2', 'teacher_prefix_ids', 'labels', 'proposed_weights', 'scope_allowed_token_ids')
        assert all(wire(a[key]) == wire(b[key]) for key in fields)
        assert trace.counts == dict(model_allocations=2, adam_allocations=2, optimizer_base_allocations=2,
            forwards=3, gru_forwards=3, backwards=3, clips=3, adam_steps=3,
            diagnostic_completed=4, diagnostic_refused=0, legacy_objectives=4,
            logits_gradient_hooks=3, legacy_restores=2, forbidden_calls=0,
            nonfinite_objective_refusals=1, diagnostic_return_refusals=1,
            pack_without_update_refusals=1)
        assert digest(references) == original_references and torch.equal(rng, torch.get_rng_state())
        assert sum(x['independently_checked_objective']['checked_logit_gradient_coordinates'] for x in trace.reports) == 74106
        assert sum(x['independently_checked_parameter_gradients']['checked_bias_gradient_coordinates'] for x in trace.reports) == 1611
        captures.save('resume-comparison.json', dict(complete_checkpoint_exact=True,
            complete_observation_fields=list(fields), unique_new_steps=2, physical_updates=3,
            additional_physical_resume_updates=1, checkpoint_sha256=digest(two),
            model_or_optimizer_input_packets_changed=False, causal_gradient_history_attested=False,
            legal_or_holdout_accuracy=False, generation_performed=False))
        captures.save('actual-counts.json', dict(status='passed', counts=trace.counts,
            checked_logit_gradient_coordinates=74106, checked_bias_gradient_coordinates=1611,
            captured_parameter_gradient_coordinates=48303, unique_new_steps=2,
            independently_checked_Adam_parameter_coordinates=48303,
            independently_checked_Adam_first_moment_coordinates=48303,
            independently_checked_Adam_second_moment_coordinates=48303,
            original_references_unchanged=True, final_rng_unchanged=True,
            checkpoint_created_under_new_profile=True, training_gold_qualified=False,
            generation_performed=False, convergence_or_statutory_meaning_established=False))
    except BaseException as error:
        captures.save('failure.json', dict(error_type=type(error).__name__, message=str(error)[:3000],
            phase=trace.active['phase'], counts=trace.counts, qualification_credit=0))
        raise
    finally:
        for handle in trace.handles:
            handle.remove()


@pytest.fixture(autouse=True)
def metadata_cases_allocate_no_numerical_lifecycle(request, monkeypatch):
    if request.node.originalname == 'test_predicate_training_genuine_two_steps_and_serialized_resume':
        return
    def forbidden(*args, **kwargs):
        raise AssertionError('metadata/refusal case entered undeclared numerical lifecycle')
    for module, name in ((numerical, '_model'), (torch.optim.Adam, '__init__'),
            (torch.nn.GRU, 'forward'), (torch.autograd, 'backward'),
            (torch.autograd, 'grad'), (torch.optim.Adam, 'step')):
        monkeypatch.setattr(module, name, forbidden)


@pytest.mark.parametrize('kind', ('full537', 'scope_conditional'))
def test_predicate_training_policy_is_distinct_sum70_with_no_legacy_compatibility(kind):
    policy = subject.policy(kind)
    assert policy['schema'] == 'legal-compact-predicate-training-objective/v1'
    assert policy['profile'] == 'authored-h0-384-fixed537-CP128-fresh-Adam-predicate-sum70/v1'
    assert policy['objective_kind'] == kind
    assert policy['old_predicate_weight'] == 1 and policy['new_predicate_weight'] == 4
    assert policy['old_complete_weight_sum'] == 67 and policy['new_complete_weight_sum'] == 70
    assert policy['reference_row_order'] == ['row0', 'row1']
    assert policy['old_row1_weights_and_Adam_inherited'] is False
    assert policy['causal_gradient_history_attested'] is policy['legacy_checkpoint_compatible'] is False
    assert policy['authority'] and all(value is False for value in policy['authority'].values())
    assert type(policy['training_mask']) is type(policy['evaluation_gold_mask']) is int
    assert policy['training_mask'] == policy['evaluation_gold_mask'] == 0
    assert subject.policy_sha256(policy) == digest(policy)
    policy['reference_checkpoint_sha256']['row1'] = '0' * 64
    assert subject.policy(kind)['reference_checkpoint_sha256']['row1'] == INPUTS[kind]['row1']['checkpoint_sha256']


@pytest.mark.parametrize('kind', (None, True, 'baseline', 'unknown'))
def test_predicate_training_unknown_policy_refuses(kind):
    with pytest.raises(ValueError):
        subject.policy(kind)


@pytest.mark.parametrize('kind', ('full537', 'scope_conditional'))
@pytest.mark.parametrize('damage', ('weight', 'sum', 'authority', 'causal', 'extra'))
def test_predicate_training_policy_hash_rejects_resealed_changes(kind, damage):
    policy = subject.policy(kind)
    if damage == 'weight':
        policy['new_predicate_weight'] = 1
    elif damage == 'sum':
        policy['new_complete_weight_sum'] = 67
    elif damage == 'authority':
        policy['authority']['training_gold_qualified'] = True
    elif damage == 'causal':
        policy['causal_gradient_history_attested'] = True
    else:
        policy['unbound_training_choice'] = 0.5
    with pytest.raises(ValueError):
        subject.policy_sha256(policy)


def test_predicate_training_initial_metadata_commits_witnesses_without_embedding_them(case):
    _, references, expected = case
    saved = digest(references)
    checkpoint = create(case)
    inspect = subject.inspect(checkpoint, **options(checkpoint, references))
    assert checkpoint['schema'] == 'legal-compact-predicate-training-checkpoint/v1'
    assert checkpoint['objective_policy_sha256'] == subject.policy_sha256(subject.policy(case[0]))
    assert checkpoint['model_state'] == references['row0']['model_state']
    assert checkpoint['model_state'] != references['row1']['model_state']
    assert checkpoint['optimizer_state']['parameters'] == {}
    assert checkpoint['optimizer_state'] != references['row1']['optimizer_state']
    assert checkpoint['initial_checkpoint_sha256'] is checkpoint['parent_checkpoint_sha256'] is None
    assert 'reference_inputs' not in checkpoint and 'warmstart_parent_checkpoint' not in checkpoint
    assert len(wire(checkpoint)) < 4 * 1024**2
    assert set(checkpoint['reference_commitments']) == {'row0', 'row1'}
    for index, key in enumerate(('row0', 'row1')):
        assert checkpoint['reference_commitments'][key]['checkpoint_sha256'] == expected[key]['checkpoint_sha256']
        assert checkpoint['reference_commitments'][key]['row_index'] == index
    row = subject.training_row(checkpoint, **options(checkpoint, references))
    old = references['row0']['warmstart_parent_checkpoint']['role_inventories'][0]
    assert row['position_weights'] == old['position_weights']
    assert row['target_ids'] == old['target_ids'] and row['scope_allowed_token_ids'] == old['scope_allowed_token_ids']
    assert math.fsum(row['proposed_position_weights']) == 70
    assert row['reference_context_not_current_model_state'] is True
    assert checkpoint['causal_gradient_history_attested'] is False
    assert all(value is False for value in checkpoint['authority'].values())
    assert inspect['model_constructed'] is inspect['optimizer_constructed'] is False
    assert subject.checkpoint_sha256(checkpoint) == digest(checkpoint)
    row['proposed_position_weights'][0] = 999
    assert subject.training_row(checkpoint, **options(checkpoint, references))['proposed_position_weights'][0] != 999
    assert digest(references) == saved


@pytest.mark.parametrize('damage', ('row0-pin', 'row1-pin', 'legacy-policy', 'domain'))
def test_predicate_training_create_refuses_foreign_independent_commitments(case, damage):
    _, _, expected = case
    changes = {}
    if damage in ('row0-pin', 'row1-pin'):
        keys = {key: expected[key]['checkpoint_sha256'] for key in ('row0', 'row1')}
        keys[damage.split('-')[0]] = '0' * 64
        changes['expected_reference_checkpoint_sha256'] = keys
    elif damage == 'legacy-policy':
        changes['expected_legacy_policy_sha256'] = '0' * 64
    else:
        changes['objective_kind'] = 'scope_conditional' if case[0] == 'full537' else 'full537'
    with pytest.raises(ValueError):
        create(case, **changes)


@pytest.mark.parametrize('damage', ('missing', 'extra', 'swapped', 'other-domain'))
def test_predicate_training_original_reference_bank_refuses_rearrangement(case, retained_packets, damage):
    kind, references, _ = case
    if damage == 'missing':
        references.pop('row1')
    elif damage == 'extra':
        references['row2'] = deepcopy(references['row0'])
    elif damage == 'swapped':
        references['row0'], references['row1'] = references['row1'], references['row0']
    else:
        other = 'scope_conditional' if kind == 'full537' else 'full537'
        references['row1'] = deepcopy(retained_packets[other]['row1'])
    with pytest.raises(ValueError):
        create(case)


@pytest.mark.parametrize('damage', ('authority', 'causal', 'bool-progress', 'inherited-Adam',
    'weights', 'reference', 'implementation'))
def test_predicate_training_resealed_checkpoint_damage_refuses_before_restore(case, damage):
    _, references, _ = case
    checkpoint = create(case)
    if damage == 'authority':
        checkpoint['authority']['training_gold_qualified'] = True
    elif damage == 'causal':
        checkpoint['causal_gradient_history_attested'] = True
    elif damage == 'bool-progress':
        checkpoint['progress']['optimizer_steps'] = False
    elif damage == 'inherited-Adam':
        checkpoint['optimizer_state'] = deepcopy(references['row1']['optimizer_state'])
        checkpoint['optimizer_state_sha256'] = digest(checkpoint['optimizer_state'])
    elif damage == 'weights':
        checkpoint['model_state']['output.bias'][0] += 1
        checkpoint['weights_sha256'] = digest(checkpoint['model_state'])
    elif damage == 'reference':
        checkpoint['reference_commitments']['row1']['checkpoint_sha256'] = digest(references['row0'])
    else:
        checkpoint['implementation']['predicate_training_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        subject.restore(checkpoint, **options(checkpoint, references))


def test_predicate_training_old_runtime_genuinely_rejects_new_envelope_before_model(case):
    _, references, _ = case
    checkpoint = create(case)
    with pytest.raises(ValueError):
        old_runtime.inspect(checkpoint, expected_checkpoint_sha256=digest(checkpoint),
            expected_policy_sha256=checkpoint['objective_policy_sha256'])
    with pytest.raises(ValueError):
        legacy.restore(checkpoint, expected_checkpoint_sha256=digest(checkpoint),
            expected_policy_sha256=checkpoint['objective_policy_sha256'])


@pytest.mark.parametrize('field', ('expected_checkpoint_sha256', 'expected_policy_sha256'))
def test_predicate_training_inspection_requires_independent_own_profile_pins(case, field):
    _, references, _ = case
    checkpoint = create(case)
    with pytest.raises(ValueError):
        subject.inspect(checkpoint, **options(checkpoint, references, **{field: '0' * 64}))


@pytest.mark.parametrize('damage', ('same-step', 'skip-step', 'bool-step'))
def test_predicate_training_pack_progress_refuses_before_model_or_optimizer_access(case, damage):
    _, references, _ = case
    checkpoint = create(case)
    progress = (dict(optimizer_steps=0, epochs_completed=0, row_cursor=0) if damage == 'same-step'
        else dict(optimizer_steps=2, epochs_completed=1, row_cursor=0) if damage == 'skip-step'
        else dict(optimizer_steps=True, epochs_completed=0, row_cursor=1))
    with pytest.raises(ValueError):
        subject.pack(None, None, checkpoint, progress, **options(checkpoint, references))


@pytest.mark.parametrize('damage', ('original', 'detached'))
def test_predicate_training_reference_fence_closes_after_genuine_legacy_validation(case, monkeypatch, damage):
    actual, calls = legacy._validate, []
    def validate(offered, *args, **kwargs):
        value = actual(offered, *args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            target = case[1]['row0'] if damage == 'original' else offered
            target['authority']['training_gold_qualified'] = True
        return value
    monkeypatch.setattr(legacy, '_validate', validate)
    with pytest.raises(ValueError):
        create(case)
    assert calls


@pytest.mark.parametrize('damage', ('source-observation', 'loaded-origin'))
def test_predicate_training_source_fence_closes_after_genuine_reference_validation(case, monkeypatch, damage):
    validate, source, completed = legacy._validate, subject._source, []
    def observe_source(path, expected):
        result = source(path, expected)
        if completed and damage == 'source-observation' and path == subject._SELF_PATH:
            descriptor, identity = result
            return dict(descriptor, sha256='0' * 64), identity
        return result
    def genuine(offered, *args, **kwargs):
        value = validate(offered, *args, **kwargs)
        completed.append(True)
        if damage == 'loaded-origin':
            monkeypatch.setattr(legacy, '__file__', str(Path(legacy.__file__).with_name('foreign.py')))
        return value
    monkeypatch.setattr(subject, '_source', observe_source)
    monkeypatch.setattr(legacy, '_validate', genuine)
    with pytest.raises(ValueError):
        create(case)
    assert completed
