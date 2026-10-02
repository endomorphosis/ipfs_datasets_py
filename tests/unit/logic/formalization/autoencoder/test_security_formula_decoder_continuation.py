"""Real bounded continuation, train-only balancing and independent inference."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from .test_security_formula_decoder_v2 import expanded_checkpoint, parent_checkpoint
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder_v2 as base
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_decoder_continuation as api
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_grammar_v2 as grammar
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_curriculum_v2 import authored_formula_samples_v2


@pytest.fixture(scope="module")
def child(expanded_checkpoint, tmp_path_factory):
    before = {path.name: path.read_bytes() for path in Path(expanded_checkpoint['output']).iterdir()}
    descriptor = api.train_security_formula_decoder_continuation(samples=authored_formula_samples_v2(),
        parent_checkpoint=expanded_checkpoint, output=tmp_path_factory.mktemp('continuation') / 'child',
        epochs=4, minibatch_size=32, learning_rate=.002, max_seconds=60.)
    assert before == {path.name: path.read_bytes() for path in Path(expanded_checkpoint['output']).iterdir()}
    return descriptor


def test_actual_full_parent_transfer_and_balanced_gradient_steps(child, expanded_checkpoint):
    parent = base.load_security_formula_decoder_v2(expanded_checkpoint)
    loaded = api.load_security_formula_decoder_continuation(child)
    training = loaded['training']
    assert training['initial_parameters_sha256'] == api._sha(api._json(parent['weights']['parameters']))
    assert loaded['weights']['lexical'] == parent['weights']['lexical']
    assert training['optimizer_steps'] > len(training['epochs'])
    assert max(row['max_gradient_norm'] for row in training['epochs']) > 0
    assert training['algorithm']['production_weighting'] == 'inverse_sqrt_train_frequency'
    assert training['test_used_for_fit_or_selection'] is False
    assert training['logic_family_heads_trained'] is False
    assert training['validation_used_for_selection'] is True
    assert training['epochs'][0]['learning_rate_first'] != training['epochs'][-1]['learning_rate_last']
    assert training['selected_parameters_changed'], training
    assert training['metrics']['validation']['macro_cross_entropy'] < training['before_validation']['macro_cross_entropy']
    assert all(value <= training['before_validation']['per_production_cross_entropy'][name] + training['algorithm']['regression_tolerance'] for name, value in training['metrics']['validation']['per_production_cross_entropy'].items())
    assert b'def ' not in b''.join(path.read_bytes() for path in Path(child['output']).iterdir())


def test_learned_inference_and_exact_replay(child, monkeypatch):
    source = b'def f(value):\n    return value <= 4\n'
    monkeypatch.setattr(api, 'train_security_formula_decoder_continuation', lambda **kw: pytest.fail('inference trained'))
    result = api.decode_security_formula_continuation(source_bytes=source, checkpoint=child, source_path='f.py')
    assert result['status'] == 'candidate'
    assert result['validation']['source_AST_equivalent']
    assert result['predicted_productions'] and result['neural_forward_count'] == 1
    assert result['learned_formula_count'] == 0
    assert api.validate_security_formula_continuation(result, source_bytes=source, checkpoint=child) == result
    altered = deepcopy(result); altered['candidate_source'] += '# forged'
    with pytest.raises(ValueError, match='replay'):
        api.validate_security_formula_continuation(altered, source_bytes=source, checkpoint=child)


@pytest.mark.parametrize('ablation', ['disabled', 'zero_production_heads'])
def test_ablation_cannot_use_teacher_fallback(child, ablation):
    result = api.decode_security_formula_continuation(source_bytes=b'def f(value):\n    return value <= 4\n',
        checkpoint=child, source_path='f.py', model_enabled=ablation != 'disabled',
        weight_ablation=None if ablation == 'disabled' else ablation)
    assert result['status'] in {'unsupported', 'rejected'}
    assert not result['validation']['source_AST_equivalent']


def test_teacher_labels_are_not_neural_predictions(child, monkeypatch):
    original = grammar.parse_formula_source
    def poison(raw):
        observed = original(raw)
        for row in observed['nodes']: row['teacher_production'] = 'false_label'
        return observed
    monkeypatch.setattr(grammar, 'parse_formula_source', poison)
    result = api.decode_security_formula_continuation(source_bytes=b'def f(value):\n    return value <= 4\n', checkpoint=child, source_path='f.py')
    assert result['status'] == 'candidate'


def test_test_changes_cannot_affect_weights_or_balancing(expanded_checkpoint, tmp_path):
    samples = authored_formula_samples_v2()
    common = dict(parent_checkpoint=expanded_checkpoint, epochs=2, minibatch_size=128, max_seconds=60.)
    first = api.train_security_formula_decoder_continuation(samples=samples, output=tmp_path/'one', **common)
    altered = deepcopy(samples)
    for sample in altered:
        if sample['split'] == 'test': sample['source'] = sample['source'].replace('value', 'other_value').replace('return 7', 'return 17')
    second = api.train_security_formula_decoder_continuation(samples=altered, output=tmp_path/'two', **common)
    one, two = [api.load_security_formula_decoder_continuation(item) for item in (first, second)]
    assert one['weights'] == two['weights']
    assert one['training']['training_row_weights_sha256'] == two['training']['training_row_weights_sha256']
    assert one['training']['training_production_counts'] == two['training']['training_production_counts']


def test_historical_split_role_is_protected(child, tmp_path):
    samples = authored_formula_samples_v2()
    samples[0]['split'] = 'test'
    with pytest.raises(ValueError, match='cross-split'):
        api.train_security_formula_decoder_continuation(samples=samples, parent_checkpoint=child, output=tmp_path/'bad', epochs=1)
    assert not (tmp_path/'bad').exists()


def test_alpha_renaming_cannot_cross_split():
    rows = [{'id':'one','split':'train','source':'def f(a):\n    return a + 1\n'},
            {'id':'two','split':'validation','source':'def g(b):\n    return b + 7\n'},
            {'id':'three','split':'test','source':'def h(c):\n    return -c\n'}]
    with pytest.raises(ValueError, match='cross-split'):
        api.prepare_security_production_samples(rows)


def test_child_is_standalone_and_can_continue(child, tmp_path):
    copied = deepcopy(child)
    copied['output'] = str(tmp_path/'standalone')
    shutil.copytree(child['output'], copied['output'])
    loaded = api.load_security_formula_decoder_continuation(copied)
    assert loaded['training']['parent_descriptor']['schema'] == base.SCHEMA
    grandchild = api.train_security_formula_decoder_continuation(samples=authored_formula_samples_v2(),
        parent_checkpoint=copied, output=tmp_path/'grandchild', epochs=1, max_seconds=60.)
    grown = api.load_security_formula_decoder_continuation(grandchild)
    assert grown['training']['initial_parameters_sha256'] == loaded['training']['final_parameters_sha256']
    assert grown['training']['split_history'] == loaded['training']['split_history']


def test_artifact_tampering_is_rejected(child, tmp_path):
    copied = deepcopy(child); copied['output'] = str(tmp_path/'tampered')
    shutil.copytree(child['output'], copied['output'])
    weights = Path(copied['output'])/'weights.json'
    weights.chmod(0o600); weights.write_bytes(weights.read_bytes()+b' ')
    with pytest.raises(ValueError, match='artifact drift'):
        api.load_security_formula_decoder_continuation(copied)


@pytest.mark.parametrize('setting', [{'epochs':True}, {'minibatch_size':0}, {'seed':-1}, {'learning_rate':float('nan')}, {'max_seconds':0}, {'label_smoothing':.5}])
def test_invalid_budgets_reject_before_writing(expanded_checkpoint, tmp_path, setting):
    with pytest.raises(ValueError):
        api.train_security_formula_decoder_continuation(samples=authored_formula_samples_v2(),
            parent_checkpoint=expanded_checkpoint, output=tmp_path/'bad', **setting)
    assert not (tmp_path/'bad').exists()


def test_balancing_survives_singleton_batches_and_estimates_same_global_gradient():
    import torch
    logits = torch.tensor([[.3, -.7], [.5, .2], [-.5, .9]], dtype=torch.float64, requires_grad=True)
    labels = torch.tensor([0, 0, 1])
    weights = torch.tensor([.25, .5, 2.25], dtype=torch.float64)  # Global mean is one.
    full = api._balanced_loss(torch, logits, labels, weights, label_smoothing=0.)
    full_gradient, = torch.autograd.grad(full, logits, retain_graph=True)
    pieces = [api._balanced_loss(torch, logits[i:i + 1], labels[i:i + 1], weights[i:i + 1], label_smoothing=0.) for i in range(3)]
    joined = torch.stack(pieces).mean()
    batch_gradient, = torch.autograd.grad(joined, logits, retain_graph=True)
    unweighted = torch.nn.functional.cross_entropy(logits, labels, reduction='none')
    assert torch.allclose(torch.stack(pieces), unweighted * weights)
    assert not torch.allclose(torch.stack(pieces), unweighted)
    assert torch.allclose(full, joined)
    assert torch.allclose(full_gradient, batch_gradient)
