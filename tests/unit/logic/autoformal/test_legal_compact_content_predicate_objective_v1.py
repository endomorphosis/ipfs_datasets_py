"""Fixed-score objective diagnostics with genuine retained warm-start validation.

The two original zero-progress checkpoints are immutable input evidence. These
controls construct only finite logits, evaluate scalar objectives and perform
same-graph backward checks. They restore no model/optimizer and perform no
forward, update, generation, encoding, checkpoint packing or semantic review.
No legacy checkpoint validator is replaced by a fixture or authored double.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_content_predicate_objective_v1 as subject,
    legal_compact_content_role_warmstart_training_v1 as legacy,
)


EXPORTS = Path(os.environ.get('LEGAL_IR_CP128_EXPORTS',
    Path(__file__).parents[4] / 'workspace/test-logs/federal-corpus-audits/'
    'owned-validation-runs/cp128-warmstart-qualification-v01-cp128-warmstart-mechanics/exports'))
INPUTS = {
    'full537': {
        'path': EXPORTS / 'full537-step-0.json',
        'bytes': 2704855,
        'raw_sha256': '599da742ac6bb76c59ae38ac3274fbe37e8064bfa22be5eb3493baea5916fbf3',
        'checkpoint_sha256': '1ef7d777554bea20aa1d77209f55f1eb987598e44a18b737a1d3541e2683ab12',
        'policy_sha256': '0ed591ba2aa4eb4e12fa82766cd1436054438540e64a338ab5177cf77e946c6f',
    },
    'scope_conditional': {
        'path': EXPORTS / 'scope_conditional-step-0.json',
        'bytes': 2704885,
        'raw_sha256': '5458464a4ebadef9820247d9dd025e255d498c508b3c039c2afdff8e03d7fc23',
        'checkpoint_sha256': 'a6b6b0cd589a74d59598c6984040676baf6f27a24a7b61f0ba0a6a5f38d5f64e',
        'policy_sha256': '701807e4e15652321efe70c29ffa894e6626776ef5df872447cb270ca0dd1c3a',
    },
}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


@pytest.fixture(scope='session')
def original_checkpoints():
    if 'LEGAL_IR_CP128_EXPORTS' not in os.environ and any(
            not expected['path'].is_file() for expected in INPUTS.values()):
        pytest.skip('retained CP128 checkpoint evidence is not installed in this checkout')
    assert EXPORTS.is_absolute() and EXPORTS.is_dir()
    result = {}
    for name, expected in INPUTS.items():
        raw = expected['path'].read_bytes()
        assert len(raw) == expected['bytes']
        assert hashlib.sha256(raw).hexdigest() == expected['raw_sha256']
        checkpoint = json.loads(raw)
        assert digest(checkpoint) == expected['checkpoint_sha256']
        assert checkpoint['objective_policy_sha256'] == expected['policy_sha256']
        assert checkpoint['objective_policy']['objective_kind'] == name
        assert checkpoint['progress'] == dict(optimizer_steps=0, epochs_completed=0, row_cursor=0)
        result[name] = checkpoint
    return result


@pytest.fixture(params=('full537', 'scope_conditional'))
def case(request, original_checkpoints):
    name = request.param
    return name, deepcopy(original_checkpoints[name]), dict(INPUTS[name])


def fixed_logits():
    # Every score is an exactly representable multiple of1/8. No RNG or model.
    scores = [[float((position * 29 + token * 17) % 113 - 56) / 8
               for token in range(537)] for position in range(46)]
    return torch.tensor([scores], device='cpu', dtype=torch.float32, requires_grad=True)


def offered(case, logits=None, **overrides):
    _, checkpoint, expected = case
    options = dict(expected_checkpoint_sha256=expected['checkpoint_sha256'],
        expected_policy_sha256=expected['policy_sha256'],
        expected_diagnostic_policy_sha256=subject.policy_sha256(subject.policy()))
    options.update(overrides)
    return subject.objective(checkpoint, fixed_logits() if logits is None else logits, **options)


def independent_geometry(checkpoint):
    parent = checkpoint['warmstart_parent_checkpoint']
    inventory = parent['role_inventories'][checkpoint['progress']['row_cursor']]
    positions = inventory['positions']
    predicate = [index for index, position in enumerate(positions)
                 if position['role'] == 'predicate_constructor']
    assert len(positions) == 46 and len(predicate) == 1
    index = predicate[0]
    assert positions[index]['lexical_token'] == '"predicate"'
    weights = [position['weight'] for position in positions]
    assert math.fsum(weights) == 67 and weights[index] == 1
    assert sum(weight == 4.5 for weight in weights) == 6
    assert sum(weight == 1 for weight in weights) == 40
    revised = list(weights)
    revised[index] = 4.0
    assert math.fsum(revised) == 70
    allowed = (inventory['scope_allowed_token_ids']
        if checkpoint['objective_policy']['objective_kind'] == 'scope_conditional'
        else [list(range(537)) for _ in range(46)])
    return inventory['target_ids'][1:], allowed, weights, revised, index


def independent_ce_and_gradient(scores, labels, allowed, weights):
    """Direct stdlib weighted CE; no diagnostic formula or Torch loss reuse."""
    divisor = math.fsum(weights)
    losses, gradients = [], []
    for values, label, choices, weight in zip(scores, labels, allowed, weights):
        assert len(values) == 537 and label in choices
        peak = max(values[token] for token in choices)
        exponentials = {token: math.exp(values[token] - peak) for token in choices}
        partition = math.fsum(exponentials.values())
        losses.append((math.log(partition) + peak - values[label]) * weight / divisor)
        gradients.append([(exponentials[token] / partition - (token == label)) * weight / divisor
            if token in exponentials else 0.0 for token in range(537)])
    return math.fsum(losses), gradients


def test_predicate_objective_fixed_policy_is_a_separate_nonpackable_diagnostic():
    descriptor = subject.policy()
    assert descriptor['schema'] == 'legal-compact-predicate-objective-policy/v1'
    assert descriptor['profile'] == 'authored384-fixed537-predicate-constructor-four-diagnostic/v1'
    assert descriptor['supported_legacy_objective_kinds'] == ['full537', 'scope_conditional']
    assert descriptor['legacy_weighting'] == 'semantic_priority'
    assert descriptor['logits_shape'] == [1, 46, 537]
    assert descriptor['changed_role'] == 'predicate_constructor'
    assert descriptor['required_changed_positions'] == 1
    assert descriptor['old_predicate_weight'] == dict(numerator=1, denominator=1)
    assert descriptor['new_predicate_weight'] == dict(numerator=4, denominator=1)
    assert descriptor['old_complete_weight_sum'] == dict(numerator=67, denominator=1)
    assert descriptor['new_complete_weight_sum'] == dict(numerator=70, denominator=1)
    assert descriptor['normalization'] == 'sum_of_complete_position_weights'
    assert descriptor['scalar_formula'] == '(67*legacy_loss+3*predicate_cross_entropy)/70'
    assert descriptor['legacy_objective_calls'] == 1
    assert descriptor['training_profile_implemented'] is descriptor['checkpoint_profile_implemented'] is False
    assert descriptor['authority'] and all(value is False for value in descriptor['authority'].values())
    assert type(descriptor['training_mask']) is type(descriptor['evaluation_gold_mask']) is int
    assert descriptor['training_mask'] == descriptor['evaluation_gold_mask'] == 0
    assert subject.policy_sha256(descriptor) == digest(descriptor)
    descriptor['new_predicate_weight']['numerator'] = 100
    assert subject.policy()['new_predicate_weight'] == dict(numerator=4, denominator=1)


@pytest.mark.parametrize('damage', ('missing', 'extra', 'weight', 'denominator', 'boolean-count',
    'authority', 'training', 'checkpoint', 'nonfinite', 'not-dict'))
def test_predicate_objective_policy_hash_refuses_resealed_or_promoted_descriptors(damage):
    descriptor = subject.policy()
    if damage == 'missing':
        descriptor.pop('schema')
    elif damage == 'extra':
        descriptor['unbound_choice'] = 1
    elif damage == 'weight':
        descriptor['new_predicate_weight']['numerator'] = 1
    elif damage == 'denominator':
        descriptor['new_complete_weight_sum']['numerator'] = 67
    elif damage == 'boolean-count':
        descriptor['required_changed_positions'] = True
    elif damage == 'authority':
        descriptor['authority']['source_semantics_verified'] = True
    elif damage == 'training':
        descriptor['training_profile_implemented'] = True
    elif damage == 'checkpoint':
        descriptor['checkpoint_profile_implemented'] = True
    elif damage == 'nonfinite':
        descriptor['new_predicate_weight']['numerator'] = float('nan')
    else:
        descriptor = list(descriptor.items())
    with pytest.raises(ValueError):
        subject.policy_sha256(descriptor)


def test_predicate_objective_matches_direct_ce_and_all_same_backward_coordinates(case):
    _, checkpoint, _ = case
    logits = fixed_logits()
    before, version, rng = digest(checkpoint), logits._version, torch.get_rng_state().clone()
    scores = logits.detach().tolist()[0]
    labels, allowed, old_weights, new_weights, predicate = independent_geometry(checkpoint)
    expected, gradient = independent_ce_and_gradient(scores, labels, allowed, new_weights)
    original, _ = independent_ce_and_gradient(scores, labels, allowed, old_weights)
    loss, report = offered(case, logits)
    assert loss.ndim == 0 and loss.requires_grad and torch.isfinite(loss)
    assert math.isclose(float(loss.detach()), expected, rel_tol=3e-6, abs_tol=2e-6)
    loss.backward()
    actual = logits.grad.tolist()[0]
    checked = 0
    for position, (row, wanted) in enumerate(zip(actual, gradient)):
        for token, (observed, value) in enumerate(zip(row, wanted)):
            assert math.isfinite(observed)
            assert math.isclose(observed, value, rel_tol=3e-5, abs_tol=2e-8), (position, token)
            if token not in allowed[position] or len(allowed[position]) == 1:
                assert observed == 0.0
            checked += 1
    assert checked == 24702
    assert old_weights[predicate] == 1 and new_weights[predicate] == 4
    assert [i for i, (a, b) in enumerate(zip(old_weights, new_weights)) if a != b] == [predicate]
    assert digest(checkpoint) == before and logits._version == version
    assert logits.detach().tolist()[0] == scores and torch.equal(rng, torch.get_rng_state())
    assert report['schema'] == 'legal-compact-predicate-objective-observation/v1'
    assert report['profile'] == 'authored384-fixed537-predicate-constructor-four-diagnostic/v1'
    assert report['legacy_report']['weighted_loss'] == pytest.approx(original, rel=3e-6, abs=2e-6)
    assert report['legacy_report_sha256'] == digest(report['legacy_report'])
    assert report['old_position_weights'] == old_weights
    assert report['proposed_position_weights'] == new_weights
    assert report['predicate_position_index'] == predicate
    assert report['predicate_target_position'] == predicate + 1
    assert report['predicate_allowed_token_ids'] == allowed[predicate]
    assert report['predicate_scope_allowed_token_ids'] == checkpoint['warmstart_parent_checkpoint']['role_inventories'][0]['scope_allowed_token_ids'][predicate]
    assert report['old_weight_sum'] == 67.0 and report['proposed_weight_sum'] == 70.0
    assert report['proposed_weighted_loss'] == float(loss.detach())
    assert report['legacy_weighted_loss'] == report['legacy_report']['weighted_loss']
    assert report['legacy_objective_calls'] == 1
    full_allowed = [list(range(537)) for _ in range(46)]
    old_full, _ = independent_ce_and_gradient(scores, labels, full_allowed, old_weights)
    proposed_full, _ = independent_ce_and_gradient(scores, labels, full_allowed, new_weights)
    predicate_full, _ = independent_ce_and_gradient(
        [scores[predicate]], [labels[predicate]], [list(range(537))], [1.0])
    assert report['legacy_full537_weighted_loss'] == pytest.approx(old_full, rel=3e-6, abs=2e-6)
    assert report['proposed_full537_weighted_loss'] == pytest.approx(proposed_full, rel=3e-6, abs=2e-6)
    assert report['predicate_full537_cross_entropy'] == pytest.approx(predicate_full, rel=3e-6, abs=2e-6)
    predicate_active, _ = independent_ce_and_gradient(
        [scores[predicate]], [labels[predicate]], [allowed[predicate]], [1.0])
    assert report['predicate_cross_entropy'] == pytest.approx(predicate_active, rel=3e-6, abs=2e-6)
    if case[0] == 'scope_conditional':
        assert report['legacy_conditional_weighted_loss'] == pytest.approx(original, rel=3e-6, abs=2e-6)
        assert report['proposed_conditional_weighted_loss'] == pytest.approx(expected, rel=3e-6, abs=2e-6)
        assert report['predicate_conditional_cross_entropy'] == pytest.approx(predicate_active, rel=3e-6, abs=2e-6)
    else:
        assert report['legacy_conditional_weighted_loss'] is None
        assert report['proposed_conditional_weighted_loss'] is None
        assert report['predicate_conditional_cross_entropy'] is None
    assert report['new_training_profile_status'] == report['new_checkpoint_profile_status'] == 'UNIMPLEMENTED'
    assert report['checkpoint_compatible'] is False
    for flag in ('model_constructed', 'optimizer_constructed', 'restore_performed', 'forward_performed',
                 'backward_performed', 'optimizer_update_performed', 'checkpoint_created', 'checkpoint_packed'):
        assert report[flag] is False
    # The denominator change rescales all unchanged coefficients. Only the
    # predicate's unnormalized weight changes; no unaffected-gradient claim.
    assert math.isclose(new_weights[0] / 70, old_weights[0] / 67 * (67 / 70), abs_tol=1e-16)
    assert report['authority'] and all(value is False for value in report['authority'].values())
    assert type(report['training_mask']) is type(report['evaluation_gold_mask']) is int
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0


def test_predicate_objective_calls_genuine_legacy_objective_once_without_numerical_lifecycle(case, monkeypatch):
    actual, calls, preserved = legacy.objective, [], []
    def observe(*args, **kwargs):
        calls.append((args, kwargs))
        loss, report = actual(*args, **kwargs)
        preserved.append(deepcopy(report))
        return loss, report
    def forbidden(*args, **kwargs):
        raise AssertionError('diagnostic entered model/optimizer/checkpoint lifecycle')
    monkeypatch.setattr(legacy, 'objective', observe)
    for name in ('restore', 'pack', 'create'):
        monkeypatch.setattr(legacy, name, forbidden)
    monkeypatch.setattr(torch.nn.Module, '__call__', forbidden)
    monkeypatch.setattr(torch.optim.Adam, '__init__', forbidden)
    _, report = offered(case)
    assert len(calls) == len(preserved) == 1
    assert report['legacy_report'] == preserved[0]
    assert calls[0][1]['expected_checkpoint_sha256'] == case[2]['checkpoint_sha256']
    assert calls[0][1]['expected_policy_sha256'] == case[2]['policy_sha256']


@pytest.mark.parametrize('bad', (None, True, 0, '', '0' * 63, 'G' * 64, '0' * 64),
    ids=('null', 'bool', 'int', 'empty', 'short', 'uppercase', 'foreign'))
def test_predicate_objective_refuses_foreign_diagnostic_policy_before_legacy(case, monkeypatch, bad):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('legacy numerical objective entered for invalid diagnostic policy')
    monkeypatch.setattr(legacy, 'objective', forbidden)
    with pytest.raises(ValueError):
        offered(case, expected_diagnostic_policy_sha256=bad)
    assert calls == []


@pytest.mark.parametrize('field', ('expected_checkpoint_sha256', 'expected_policy_sha256'))
def test_predicate_objective_refuses_foreign_legacy_independent_commitments(case, field):
    with pytest.raises(ValueError):
        offered(case, **{field: '0' * 64})


@pytest.mark.parametrize('damage', ('authority', 'weights', 'role'))
def test_predicate_objective_genuine_validator_rejects_resealed_checkpoint_damage(case, damage):
    _, checkpoint, expected = case
    if damage == 'authority':
        checkpoint['authority']['training_gold_qualified'] = True
    elif damage == 'weights':
        name = checkpoint['parameter_order'][0]
        value = checkpoint['model_state'][name]
        while isinstance(value[0], list):
            value = value[0]
        value[0] += 1
        checkpoint['weights_sha256'] = digest(checkpoint['model_state'])
    else:
        parent = checkpoint['warmstart_parent_checkpoint']
        inventory = parent['role_inventories'][0]
        index = next(i for i, p in enumerate(inventory['positions']) if p['role'] == 'predicate_constructor')
        inventory['positions'][index]['role'] = 'variable_reference'
        parent['role_inventories_sha256'] = digest(parent['role_inventories'])
        checkpoint['role_inventories_sha256'] = parent['role_inventories_sha256']
        checkpoint['warmstart_parent_checkpoint_sha256'] = digest(parent)
    with pytest.raises(ValueError):
        offered(case, expected_checkpoint_sha256=digest(checkpoint))


@pytest.mark.parametrize('kind', ('wrong-shape', 'float64', 'not-differentiable', 'list'))
def test_predicate_objective_refuses_unsupported_logits(case, kind):
    logits = fixed_logits()
    if kind == 'wrong-shape':
        logits = logits[:, :-1, :]
    elif kind == 'float64':
        logits = logits.to(dtype=torch.float64)
    elif kind == 'not-differentiable':
        logits = logits.detach()
    else:
        logits = logits.detach().tolist()
    with pytest.raises(ValueError):
        offered(case, logits)


@pytest.mark.parametrize('bad', (float('nan'), float('inf'), -float('inf')),
    ids=('nan', 'positive-inf', 'negative-inf'))
def test_predicate_objective_refuses_nonfinite_scores_even_outside_conditional_mask(case, bad):
    logits = fixed_logits()
    _, allowed, _, _, _ = independent_geometry(case[1])
    # The conditional case excludes this coordinate. Full537 remains a complete
    # finite-logit contract too, rather than silently accepting an unmasked NaN.
    position = next(i for i, choices in enumerate(allowed) if len(choices) == 1) if case[0] == 'scope_conditional' else 0
    token = next(i for i in range(537) if i not in allowed[position]) if case[0] == 'scope_conditional' else 536
    with torch.no_grad():
        logits[position // 46, position, token] = bad
    with pytest.raises(ValueError):
        offered(case, logits)


def test_predicate_objective_refuses_original_checkpoint_mutation_after_genuine_legacy_return(case, monkeypatch):
    actual = legacy.objective
    def mutate(*args, **kwargs):
        result = actual(*args, **kwargs)
        case[1]['authority']['training_gold_qualified'] = True
        return result
    monkeypatch.setattr(legacy, 'objective', mutate)
    with pytest.raises(ValueError):
        offered(case)


def test_predicate_objective_refuses_detached_checkpoint_mutation_after_genuine_legacy_return(case, monkeypatch):
    actual = legacy.objective
    def mutate(checkpoint, *args, **kwargs):
        result = actual(checkpoint, *args, **kwargs)
        checkpoint['authority']['training_gold_qualified'] = True
        return result
    monkeypatch.setattr(legacy, 'objective', mutate)
    with pytest.raises(ValueError):
        offered(case)


def test_predicate_objective_refuses_logits_mutation_after_genuine_legacy_return(case, monkeypatch):
    actual = legacy.objective
    def mutate(checkpoint, logits, **kwargs):
        result = actual(checkpoint, logits, **kwargs)
        with torch.no_grad():
            logits[0, 0, 0] += 1
        return result
    monkeypatch.setattr(legacy, 'objective', mutate)
    with pytest.raises(ValueError):
        offered(case)


def test_predicate_objective_refuses_rng_mutation_after_genuine_legacy_return(case, monkeypatch):
    actual = legacy.objective
    original_rng = torch.get_rng_state().clone()
    def mutate(*args, **kwargs):
        result = actual(*args, **kwargs)
        torch.rand(1)
        return result
    monkeypatch.setattr(legacy, 'objective', mutate)
    try:
        with pytest.raises(ValueError):
            offered(case)
    finally:
        torch.set_rng_state(original_rng)


@pytest.mark.parametrize('damage', ('role', 'weight', 'allowed-set', 'scalar'))
def test_predicate_objective_refuses_damaged_report_after_genuine_legacy_callback(case, monkeypatch, damage):
    actual, calls = legacy.objective, []
    def corrupt(*args, **kwargs):
        loss, report = actual(*args, **kwargs)
        calls.append(True)
        index = report['position_roles'].index('predicate_constructor')
        if damage == 'role':
            report['position_roles'][index] = 'variable_reference'
        elif damage == 'weight':
            report['position_weights'][index] = 4.0
        elif damage == 'allowed-set':
            report['scope_allowed_token_ids'][index] = [report['label_ids'][index]]
        else:
            report['weighted_loss'] += 1
        return loss, report
    monkeypatch.setattr(legacy, 'objective', corrupt)
    with pytest.raises(ValueError):
        offered(case)
    assert len(calls) == 1


@pytest.mark.parametrize('damage', ('source-observation', 'loaded-origin'))
def test_predicate_objective_closing_source_fence_runs_after_genuine_callback(case, monkeypatch, damage):
    actual, source, completed = legacy.objective, subject._source, []
    def observe_source(path, expected):
        value = source(path, expected)
        if completed and damage == 'source-observation' and path == subject._SELF_PATH:
            descriptor, identity = value
            descriptor = dict(descriptor, sha256='0' * 64)
            return descriptor, identity
        return value
    def complete(*args, **kwargs):
        result = actual(*args, **kwargs)
        completed.append(True)
        if damage == 'loaded-origin':
            monkeypatch.setattr(legacy, '__file__', str(Path(legacy.__file__).with_name('foreign.py')))
        return result
    monkeypatch.setattr(subject, '_source', observe_source)
    monkeypatch.setattr(legacy, 'objective', complete)
    with pytest.raises(ValueError):
        offered(case)
    assert len(completed) == 1


def test_predicate_objective_final_report_wire_is_inside_original_checkpoint_fence(case, monkeypatch):
    actual, reached = subject._wire, []
    def late_wire(value):
        raw = actual(value)
        if type(value) is dict and value.get('schema') == subject.SCHEMA:
            reached.append(True)
            case[1]['authority']['training_gold_qualified'] = True
        return raw
    monkeypatch.setattr(subject, '_wire', late_wire)
    with pytest.raises(ValueError):
        offered(case)
    assert reached == [True]
