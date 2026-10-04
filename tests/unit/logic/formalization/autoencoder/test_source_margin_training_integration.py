"""Restricted auxiliary gradients and unchanged decoder gates; no qualification."""
from copy import deepcopy
import sys
from types import ModuleType, SimpleNamespace

import pytest

torch = pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as fields
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as subject
from .test_context_boundary_training_runner import fake_context_boundary
from .test_generated_field_training_runner import fake_joint
from .test_ordered_clause_recurrent_training_runner import real_fixture

NAMES = [
    'body.body.body.condition.weight', 'body.body.body.condition.bias',
    'body.body.body.decoder.weight_ih_l0', 'body.body.body.decoder.weight_hh_l0',
    'body.body.body.decoder.bias_ih_l0', 'body.body.body.decoder.bias_hh_l0',
    'body.body.body.output.weight', 'body.body.body.output.bias',
    'body.body.body.target_embedding.weight', 'body.body.source_to_embedding.weight',
    'clause_to_embedding.weight',
]


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def fit(model, train, tune, options, contexts, **kwargs):
    return subject.train(model, train, tune, source_contexts=contexts, source_value_weight=.25,
        cardinality_weight=.25, count_exposure='balanced_all', action_contrastive_weight=.05,
        non_action_learning_rate_multiplier=10., **options, **kwargs)


def fake_margin(monkeypatch, *, empty=False, expired=None):
    """Closed fake validates trainer wiring without relying on helper numerics."""
    owner = ModuleType(package.__name__ + '.generated_source_margin_training')
    observed = dict(preparations=[], collections=[], losses=[], gradients=[], whitelist=[])
    original_prepare = fields.prepare_training_inventory

    def prepare(rows, refs, **kwargs):
        assert {r['id'] for r in rows} == {r['id'] for r in refs} == set(kwargs['contexts'])
        assert all(r['id'].startswith('train-') for r in rows)
        observed['preparations'].append(deepcopy(rows))
        return original_prepare(rows, refs, **kwargs)

    def inventory(model):
        actual = dict(model.named_parameters())
        result = [(name, actual[name]) for name in NAMES]
        assert all(p.requires_grad for _, p in result)
        observed['whitelist'].append(result)
        return result

    def collect(model, rows, **kwargs):
        assert all(set(row) == {'id', 'input', 'source_text'} and row['id'].startswith('train-') for row in rows)
        assert set(kwargs['source_contexts']) == {row['id'] for row in rows}
        assert not {'inventory', 'references', 'training_references', 'site_policy'} & set(kwargs)
        observed['collections'].append(dict(model=model, rows=deepcopy(rows)))
        if expired == 'collection':
            raise TimeoutError('synthetic collection')
        return dict(rows=rows)

    def losses(torch, model, collection, inventory, **kwargs):
        assert kwargs['boundary_site_policy'] == 'first_last'
        assert set(kwargs['source_contexts']) == {row['id'] for row in collection['rows']}
        actual = dict(model.named_parameters())
        recurrent = actual[NAMES[0]]
        head = actual['non_action_head.source_projection.weight']
        if expired in ('loss', 'retry'):
            recurrent.grad = torch.ones_like(recurrent)
            raise TimeoutError('synthetic '+expired)
        boundary = recurrent.square().mean() + head.square().mean() + .125
        margin = (recurrent + 2.).square().mean() + (head + 3.).square().mean()
        margin.register_hook(lambda value: observed['gradients'].append(float(value)))
        result = dict(boundary_loss=None if empty else boundary, margin_loss=None if empty else margin,
            receipt=dict(synthetic=True, boundary=dict(mean_loss=None if empty else float(boundary.detach())),
                margin=dict(mean_loss=None if empty else float(margin.detach())),
                row_ids=[row['id'] for row in collection['rows']]))
        observed['losses'].append(result)
        return result

    owner.recurrent_auxiliary_parameters = inventory
    owner.collect_source_margin_sites = collect
    owner.generated_margin_losses = losses
    monkeypatch.setitem(sys.modules, owner.__name__, owner)
    monkeypatch.setattr(package, 'generated_source_margin_training', owner, raising=False)
    monkeypatch.setattr(fields, 'prepare_training_inventory', prepare)
    return observed


def assert_same(left, right):
    for role in ('state_dict', 'last_complete_attempt_state_dict'):
        assert all(torch.equal(value, right[role][name]) for name, value in left[role].items())
    a, b = deepcopy(left['report']), deepcopy(right['report'])
    a.pop('elapsed_seconds'); b.pop('elapsed_seconds')
    assert a == b
    assert left['predictions'] == right['predictions']


@pytest.mark.parametrize('field_weight', [0., .05])
def test_disabled_margin_path_is_exact_and_does_not_import_helper(monkeypatch, field_weight):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    if field_weight:
        fake_joint(monkeypatch)
    else:
        fake_context_boundary(monkeypatch)
    monkeypatch.setitem(sys.modules, package.__name__ + '.generated_source_margin_training', None)
    args = dict(generated_boundary_weight=.05, generated_field_weight=field_weight)
    ordinary = fit(model, train, tune, options, contexts, **args)
    explicit = fit(model, train, tune, options, contexts, **args,
        generated_source_margin_weight=0., generated_source_margin_replay=False)
    assert_same(ordinary, explicit)
    assert not any(key.startswith('generated_source_margin') for key in explicit['report'])


@pytest.mark.parametrize('bad', [True, None, -.01, 1.01, float('inf'), float('nan'), '.01'])
def test_margin_weight_is_validated_before_private_copy(monkeypatch, bad):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, 'deepcopy', lambda *a: pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError, match='source-margin weight'):
        fit(model, train, tune, options, contexts, generated_source_margin_weight=bad)


@pytest.mark.parametrize('bad', [None, 0, 1, .5, [], {}, 'true'])
def test_margin_flag_requires_bool(monkeypatch, bad):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, 'deepcopy', lambda *a: pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError, match='source-margin replay must be a boolean'):
        fit(model, train, tune, options, contexts, generated_source_margin_replay=bad)


@pytest.mark.parametrize('extra', [dict(generated_field_weight=.05), dict(joint_generated_replay=True),
    dict(generated_site_interval=2), dict(generated_boundary_weight=0.),
    dict(generated_boundary_gradient_scope='count_head_only')])
def test_mutually_exclusive_replay_and_boundary_requirements(monkeypatch, extra):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, 'deepcopy', lambda *a: pytest.fail('unexpected model copy'))
    args = dict(generated_boundary_weight=.05, generated_source_margin_replay=True, **{})
    args.update(extra)
    with pytest.raises(ValueError):
        fit(model, train, tune, options, contexts, **args)


def test_margin_requires_ordered_recurrent_head_before_copy(monkeypatch):
    _, donor, train, tune, options, contexts = real_fixture(monkeypatch)
    monkeypatch.setattr(subject, 'deepcopy', lambda *a: pytest.fail('unexpected model copy'))
    with pytest.raises(ValueError, match='ordered recurrent contextual model'):
        fit(donor, train, tune, options, contexts, generated_boundary_weight=.05,
            generated_source_margin_replay=True)


def test_split_gradient_matches_explicit_restricted_derivative_and_preserves_none():
    p, q, head, unused = [torch.nn.Parameter(torch.tensor(value)) for value in (2., 3., 4., 5.)]
    ordinary = (p*head+q).square()
    margin = (p+head).square()
    # q is whitelisted but disconnected from this auxiliary; unused is never attached.
    named = [('recurrent.p', p), ('recurrent.q', q), ('recurrent.unused', unused)]
    base_expected = torch.autograd.grad(ordinary, [p, q, head], retain_graph=True)
    gradients, receipt = subject._source_margin_gradients(torch, margin, named, .01)
    assert all(value.grad is None for value in (p, q, head, unused))
    assert gradients[1:] == [None, None]
    assert all(g is None or not g.requires_grad for g in gradients)
    ordinary.backward()
    subject._add_source_margin_gradients(torch, named, gradients)
    assert p.grad == base_expected[0] + .01*12.
    assert q.grad == base_expected[1] and head.grad == base_expected[2] and unused.grad is None
    assert receipt['none_gradient_parameter_names'] == ['recurrent.q', 'recurrent.unused']
    assert receipt['unscaled_l2_norm'] == 12.
    assert receipt['scaled_l2_norm'] == pytest.approx(.12)
    assert receipt['backward_executed'] and receipt['backward_elapsed_seconds'] >= 0.


@pytest.mark.parametrize('weight,loss_absent', [(0., False), (.01, True)])
def test_no_auxiliary_backward_or_materialized_zero_grads(monkeypatch, weight, loss_absent):
    parameter = torch.nn.Parameter(torch.tensor(2.))
    loss = None if loss_absent else parameter.square()
    monkeypatch.setattr(torch.autograd, 'grad', lambda *a, **kw: pytest.fail('unnecessary reverse pass'))
    gradients, receipt = subject._source_margin_gradients(torch, loss, [('p', parameter)], weight)
    subject._add_source_margin_gradients(torch, [('p', parameter)], gradients)
    assert gradients == [None] and parameter.grad is None
    assert receipt['backward_executed'] is False
    assert receipt['unscaled_l2_norm'] == receipt['scaled_l2_norm'] == receipt['backward_elapsed_seconds'] == 0.


@pytest.mark.parametrize('weight', [0., .01])
def test_trainer_dispatch_gradient_scope_and_numeric_objective(monkeypatch, weight):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_margin(monkeypatch)
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as old
    monkeypatch.setattr(old, 'collect_source_boundary_prefixes', lambda *a, **kw: pytest.fail('second rollout'))
    before = core.tensor_digest(model)
    rng = torch.get_rng_state().clone()
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=weight, generated_source_margin_replay=weight == 0.)
    report = result['report']
    assert report['optimizer_steps'] == len(observed['collections']) == 2
    assert len(observed['preparations']) == 1 and len(observed['whitelist']) == 2
    assert report['generated_source_margin_parameter_names'] == NAMES
    assert report['generated_source_margin_scheduled_updates'] == 2
    assert report['generated_source_margin_auxiliary_backward_updates'] == (2 if weight else 0)
    assert observed['gradients'] == ([1., 1.] if weight else [])
    assert report['generated_source_margin_objective_enabled'] is bool(weight)
    assert report['generated_source_margin_used_for_selection'] is False
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert all(report[key] is False for key in subject.FALSE)
    for index, update in enumerate(report['committed_updates']):
        record = update['generated_source_margin']; gradient = record['gradient']; receipt = record['receipt']
        assert record['interval'] == 1 and record['zero_based_committed_step'] == index
        assert gradient['parameter_names'] == NAMES and gradient['backward_executed'] is bool(weight)
        assert gradient['combined_preclip_norm'] == update['preclip_norm']
        assert gradient['shared_clip_factor'] == float((report['config']['max_grad_norm']/
            (torch.tensor(update['preclip_norm'], dtype=torch.float32)+1e-6)).clamp(max=1.))
        expected = update['weighted_token_ce'] + report['config']['reconstruction_weight']*update['raw_reconstruction_mse']
        expected += .25*update['count_ce'] + .25*update['source_value_ce'] + .05*update['action_contrastive']['loss']
        expected += .05*receipt['boundary']['mean_loss']
        assert update['ordinary_objective'] == pytest.approx(expected, abs=2e-6)
        assert update['objective'] == pytest.approx(expected+weight*receipt['margin']['mean_loss'], abs=2e-6)
        assert 'generated_sites' not in update and 'generated_boundary' not in update
    assert core.tensor_digest(model) == before and torch.equal(rng, torch.get_rng_state())


def test_excluded_head_base_gradients_match_before_shared_clip(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    options = deepcopy(options)
    options['config']['max_optimizer_steps'] = 1
    records = []
    original_add = subject._add_source_margin_gradients
    def checked_add(torch, names, gradients):
        working = observed['collections'][-1]['model']
        before = {name: None if p.grad is None else p.grad.detach().clone() for name, p in working.named_parameters()}
        original_add(torch, names, gradients)
        for name, p in working.named_parameters():
            if name not in NAMES:
                assert (p.grad is None) == (before[name] is None)
                if p.grad is not None:
                    assert torch.equal(p.grad, before[name])
        records.append(before)
    observed = fake_margin(monkeypatch)
    monkeypatch.setattr(subject, '_add_source_margin_gradients', checked_add)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    assert result['report']['optimizer_steps'] == len(records) == 1


@pytest.mark.parametrize('phase', ['collection', 'loss', 'retry', 'auxiliary', 'base', 'addition', 'clip'])
def test_deadline_aborts_clear_gradients_and_no_exposures(monkeypatch, phase):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_margin(monkeypatch, expired=phase)
    expired = [False]
    now = subject.time.monotonic
    monkeypatch.setattr(subject, 'time', SimpleNamespace(monotonic=lambda: now() + (1000. if expired[0] else 0.)))
    if phase in ('auxiliary', 'base', 'addition', 'clip'):
        target, name = {'auxiliary': (subject, '_source_margin_gradients'),
            'base': (torch.Tensor, 'backward'), 'addition': (subject, '_add_source_margin_gradients'),
            'clip': (torch.nn.utils, 'clip_grad_norm_')}[phase]
        original = getattr(target, name)
        def expire(*a, **kw):
            result = original(*a, **kw)
            expired[0] = True
            return result
        monkeypatch.setattr(target, name, expire)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *a, **kw: pytest.fail('expired step committed'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    report = result['report']
    assert report['optimizer_steps'] == report['row_presentations'] == report['source_value_presentations'] == 0
    assert report['count_training_row_presentations'] == report['generated_source_margin_scheduled_updates'] == 0
    assert report['generated_source_margin_auxiliary_backward_updates'] == 0
    assert report['committed_updates'] == [] and report['selected_epoch'] == 0
    assert report['stopped_reason'].startswith('deadline')
    assert all(p.grad is None for p in observed['collections'][0]['model'].parameters())
    assert all(torch.equal(value, result['state_dict'][name]) for name, value in model.state_dict().items())


def test_deadline_after_auxiliary_does_not_start_ordinary_backward(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_margin(monkeypatch)
    expired = [False]
    now = subject.time.monotonic
    monkeypatch.setattr(subject, 'time', SimpleNamespace(monotonic=lambda: now() + (1000. if expired[0] else 0.)))
    original = subject._source_margin_gradients
    def expire(*a, **kw):
        result = original(*a, **kw)
        expired[0] = True
        return result
    monkeypatch.setattr(subject, '_source_margin_gradients', expire)
    monkeypatch.setattr(torch.Tensor, 'backward', lambda *a, **kw: pytest.fail('expired ordinary backward began'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    assert result['report']['stopped_reason'] == 'deadline_after_source_margin_backward'


def test_deadline_after_ordinary_backward_does_not_add_auxiliary_gradients(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_margin(monkeypatch)
    expired = [False]
    now, backward = subject.time.monotonic, torch.Tensor.backward
    monkeypatch.setattr(subject, 'time', SimpleNamespace(monotonic=lambda: now() + (1000. if expired[0] else 0.)))
    def expire(*a, **kw):
        result = backward(*a, **kw)
        expired[0] = True
        return result
    monkeypatch.setattr(torch.Tensor, 'backward', expire)
    monkeypatch.setattr(subject, '_add_source_margin_gradients', lambda *a, **kw: pytest.fail('expired addition began'))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    assert result['report']['stopped_reason'] == 'deadline_after_ordinary_backward'


def test_auxiliary_reverse_pass_uses_declared_inputs_without_materializing_grads(monkeypatch):
    p, excluded = [torch.nn.Parameter(torch.tensor(x)) for x in (2., 3.)]
    actual = torch.autograd.grad
    calls = []
    def observed(output, inputs, **kwargs):
        calls.append((inputs, kwargs))
        return actual(output, inputs, **kwargs)
    monkeypatch.setattr(torch.autograd, 'grad', observed)
    gradients, receipt = subject._source_margin_gradients(torch, (p+excluded).square(), [('p', p)], .01)
    assert len(calls) == 1 and calls[0][0] == [p]
    assert calls[0][1] == dict(retain_graph=True, create_graph=False, allow_unused=True)
    assert p.grad is excluded.grad is None and len(gradients) == 1 and receipt['parameter_names'] == ['p']


def test_empty_margin_replay_does_not_change_ordinary_updates(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    ordinary = fit(model, train, tune, options, contexts)
    observed = fake_margin(monkeypatch, empty=True)
    monkeypatch.setattr(torch.autograd, 'grad', lambda *a, **kw: pytest.fail('empty auxiliary reverse pass'))
    replayed = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    for role in ('state_dict', 'last_complete_attempt_state_dict'):
        assert all(torch.equal(tensor, replayed[role][name]) for name, tensor in ordinary[role].items())
    assert replayed['report']['generated_source_margin_auxiliary_backward_updates'] == 0
    assert observed['gradients'] == []


def actual_geometry_fixture(monkeypatch):
    """Tiny authenticated cohort, with the campaign's declared32-wide GRU."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    build = numerical._model
    with monkeypatch.context() as patch:
        patch.setattr(numerical, '_model', lambda lineage, codec, config: build(lineage, codec,
            dict(config, hidden_size=32)))
        return real_fixture(patch)


@pytest.mark.parametrize('weight', [0., .01])
def test_real_source_margin_helper_integrates_with_unchanged_gates(monkeypatch, weight):
    from ipfs_datasets_py.logic.formalization.autoencoder import generated_source_margin_training as owner
    model, _, train, tune, options, contexts = actual_geometry_fixture(monkeypatch)
    before = core.tensor_digest(model)
    previous = deepcopy((train, tune, options, contexts))
    collect, losses = owner.collect_source_margin_sites, owner.generated_margin_losses
    sources, receipts = [], []
    def observed(working, rows, **kwargs):
        assert all(set(row) == {'id', 'input', 'source_text'} for row in rows)
        assert {row['id'] for row in rows} <= set(contexts['train'])
        assert not {'inventory', 'references', 'training_references', 'site_policy'} & set(kwargs)
        sources.append(deepcopy(rows))
        return collect(working, rows, **kwargs)
    def replayed(*args, **kwargs):
        result = losses(*args, **kwargs)
        if weight == 0. and result['margin_loss'] is not None:
            result['margin_loss'].register_hook(lambda gradient: pytest.fail('zero auxiliary graph attached'))
        receipts.append(result['receipt'])
        return result
    monkeypatch.setattr(owner, 'collect_source_margin_sites', observed)
    monkeypatch.setattr(owner, 'generated_margin_losses', replayed)
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=weight, generated_source_margin_replay=True)
    report = result['report']
    assert report['optimizer_steps'] == len(sources) == len(receipts) == 2
    assert report['generated_source_margin_parameter_names'] == list(owner.RECURRENT_PARAMETER_NAMES)
    assert report['generated_source_margin_inventory']['validation_rows_used'] is False
    assert report['generated_source_margin_used_for_selection'] is False
    assert report['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert core.tensor_digest(model) == before and (train, tune, options, contexts) == previous
    assert all(report[key] is False for key in subject.FALSE)
    for receipt in receipts:
        assert receipt['margin']['fields'] == ['actor', 'action', 'modality', 'object']
        assert receipt['margin']['teacher_detached'] is True and receipt['margin']['source_margin_ratio'] == 1.
        assert receipt['reference_labels_used_only_after_rollout'] and not receipt['validation_rows_used']
        assert receipt['replay_logits_atol'] == receipt['replay_logits_rtol'] == 2e-5
        assert not receipt['target_prefixes_used'] and not receipt['reference_documents_passed_to_model']
        assert receipt['generation']['rollout_count'] == 1 and receipt['generation']['inventory_access'] is False


@pytest.mark.parametrize('weight', [0., .01])
def test_margin_objective_cannot_override_generated_actor_regression(monkeypatch, weight):
    from .test_long_span_cardinality_training import evaluated
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_margin(monkeypatch)
    baseline = evaluated(options, ce=2.)
    regressed = evaluated(options, ce=.1, mutate=lambda target: target['rules'][0].update(actor='agency'))
    for panel in (baseline, regressed):
        panel['source_values'] = dict(cross_entropy=.01, predictions=[])
    panels = iter([baseline, regressed])
    monkeypatch.setattr(subject, '_evaluate', lambda *a, **kw: next(panels))
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_replay=True, generated_source_margin_weight=weight)
    report = result['report']
    assert report['optimizer_steps'] == 2 and report['selected_epoch'] == 0
    assert any('actor' in reason for reason in report['history'][-1]['rejection_reasons'])
    assert all(torch.equal(tensor, result['state_dict'][name]) for name, tensor in model.state_dict().items())


def test_unresolved_margin_replay_parity_error_cannot_step(monkeypatch):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    observed = fake_margin(monkeypatch)
    owner = getattr(package, 'generated_source_margin_training')
    def mismatched(*a, **kw):
        raise ValueError('synthetic strict source/combined replay mismatch')
    monkeypatch.setattr(owner, 'generated_margin_losses', mismatched)
    monkeypatch.setattr(torch.optim.AdamW, 'step', lambda *a, **kw: pytest.fail('unverified replay stepped'))
    before = core.tensor_digest(model)
    with pytest.raises(ValueError, match='strict source/combined replay mismatch'):
        fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
            generated_source_margin_weight=.01)
    assert len(observed['collections']) == 1 and core.tensor_digest(model) == before
    assert all(p.grad is None for p in model.parameters())


@pytest.mark.parametrize('step_cap,expected', [(1, 1), (1000, 2)])
def test_margin_memory_bound_uses_both_curriculum_and_step_limit(monkeypatch, step_cap, expected):
    model, _, train, tune, options, contexts = real_fixture(monkeypatch)
    fake_margin(monkeypatch)
    options = deepcopy(options)
    options['config']['max_optimizer_steps'] = step_cap
    options['config']['max_memory_bytes'] = 2147483648
    result = fit(model, train, tune, options, contexts, generated_boundary_weight=.05,
        generated_source_margin_weight=.01)
    assert result['report']['generated_source_margin_max_updates_estimated'] == expected
    assert result['report']['optimizer_steps'] <= expected
