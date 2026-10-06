"""Actual optimizer, source-copy prediction and safe numerical checkpoint tests."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder as span


@pytest.fixture(scope='module', autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def config(seed=17):
    return span.SpanDecoderConfig(seed=seed, byte_dim=8, token_dim=24, token_hidden=24,
                                  slot_hidden=32, max_tokens=64, max_token_bytes=32)


def example(source='The Clerk shall publish notice or shall retain records.',
            scope='modal_over_actions', actor='Clerk', actions=('publish notice', 'retain records'), modality='O'):
    actor_span = (source.index(actor), source.index(actor) + len(actor))
    members = tuple(span.GroupedSpanTarget(actor_span, (source.index(action), source.index(action) + len(action)), modality)
                    for action in actions)
    return span.GroupedSpanExample(source, scope, members)


def reseal(checkpoint):
    checkpoint['checkpoint_sha256'] = sha256(json.dumps(
        {key: value for key, value in checkpoint.items() if key != 'checkpoint_sha256'},
        sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    return checkpoint


def test_generic_utf8_tokenization_keeps_exact_original_offsets_and_no_truncation():
    source = '  O’Connor\tshall file café-report; or shall retain copies. '
    tokens = span.tokenize_source(source, config())
    assert [token.text for token in tokens] == ['O', '’', 'Connor', 'shall', 'file', 'café', '-', 'report', ';', 'or', 'shall', 'retain', 'copies', '.']
    assert all(source[token.start:token.end] == token.text for token in tokens)
    assert tokens[0].start == 2
    with pytest.raises(ValueError, match='byte bounds'):
        span.tokenize_source('a' * 33, config())
    with pytest.raises(ValueError, match='token bounds'):
        span.tokenize_source(' '.join(['word'] * 65), config())


def test_seeded_model_initialization_is_reproducible_without_mutating_global_rng():
    torch.manual_seed(144)
    before = torch.random.get_rng_state().clone()
    first = span.GroupedSpanDecoder(config())
    assert torch.equal(torch.random.get_rng_state(), before)
    second = span.GroupedSpanDecoder(config())
    third = span.GroupedSpanDecoder(config(18))
    assert all(torch.equal(value, second.state_dict()[key]) for key, value in first.state_dict().items())
    assert any(not torch.equal(value, third.state_dict()[key]) for key, value in first.state_dict().items())


def test_real_optimizer_learns_source_spans_and_preserves_two_explicit_scope_choices():
    samples = [example(scope=scope) for scope in span.SCOPES]
    samples += [example('The Director may file reports or may archive copies.', scope, 'Director',
                        ('file reports', 'archive copies'), 'P') for scope in span.SCOPES]
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model, learning_rate=0.015)
    first = span.train_grouped_span_step(model, optimizer, samples)
    for _ in range(99):
        last = span.train_grouped_span_step(model, optimizer, samples)
    assert last['loss'] < first['loss'] * 0.03
    for sample in samples:
        prediction = span.predict_grouped_span_decoder(model, sample.source_text, sample.modal_scope)
        assert prediction['status'] == 'predicted'
        assert prediction['request']['modal_scope'] == sample.modal_scope
        assert prediction['raw_prediction']['count'] == len(sample.members)
        assert prediction['predicted_character_spans'] == [
            {'actor': list(member.actor_span), 'action': list(member.action_span)} for member in sample.members]
        assert prediction['request']['members'] == [
            {'actor': sample.source_text[slice(*member.actor_span)].casefold(), 'modality': member.modality,
             'action': sample.source_text[slice(*member.action_span)]} for member in sample.members]
        assert prediction['source_semantics_verified'] is prediction['proof_ready'] is False
        assert prediction['targets_used_at_inference'] is False


def test_checkpoint_restores_optimizer_progress_and_exact_next_update_without_source_data():
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model, learning_rate=0.006)
    samples = [example(scope=scope) for scope in span.SCOPES]
    span.train_grouped_span_step(model, optimizer, samples)
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=1)
    encoded = json.dumps(checkpoint, allow_nan=False)
    assert samples[0].source_text not in encoded
    assert 'Clerk' not in encoded and 'publish notice' not in encoded
    restored, resumed_optimizer, steps = span.restore_grouped_span_checkpoint(json.loads(encoded))
    assert steps == 1
    assert all(torch.equal(value, restored.state_dict()[key]) for key, value in model.state_dict().items())
    original_prediction = span.predict_grouped_span_decoder(model, samples[0].source_text, samples[0].modal_scope)
    assert span.predict_grouped_span_decoder(restored, samples[0].source_text, samples[0].modal_scope) == original_prediction
    actual = span.train_grouped_span_step(model, optimizer, samples)
    resumed = span.train_grouped_span_step(restored, resumed_optimizer, samples)
    assert actual == resumed
    assert all(torch.equal(value, restored.state_dict()[key]) for key, value in model.state_dict().items())
    assert span.save_grouped_span_checkpoint(model, optimizer, steps=2) == span.save_grouped_span_checkpoint(restored, resumed_optimizer, steps=2)


@pytest.mark.parametrize('mutation', ['extra', 'shape', 'dtype', 'bool_tensor', 'producer', 'schema', 'progress', 'optimizer_extra', 'variance'])
def test_checkpoint_rejects_tampered_schema_or_numerical_state_even_when_resealed(mutation):
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    span.train_grouped_span_step(model, optimizer, [example()])
    checkpoint = deepcopy(span.save_grouped_span_checkpoint(model, optimizer, steps=1))
    tensor = next(iter(checkpoint['model_state'].values()))
    if mutation == 'extra':
        checkpoint['target_request'] = {'members': []}
    elif mutation == 'shape':
        tensor['shape'] = [True, 8]
    elif mutation == 'dtype':
        tensor['dtype'] = 'float64'
    elif mutation == 'bool_tensor':
        tensor['values'][0] = True
    elif mutation == 'producer':
        checkpoint['producer']['implementation_sha256'] = '0' * 64
    elif mutation == 'schema':
        checkpoint['schema'] = 'pickle'
    elif mutation == 'progress':
        checkpoint['steps'] = 2
    elif mutation == 'optimizer_extra':
        checkpoint['optimizer']['source_text'] = example().source_text
    else:
        checkpoint['optimizer']['state']['0']['exp_avg_sq']['values'][0] = -1.0
    reseal(checkpoint)
    with pytest.raises(ValueError):
        span.restore_grouped_span_checkpoint(checkpoint)


@pytest.mark.parametrize('kind', ['nan', 'infinity', 'float32_overflow'])
def test_checkpoint_rejects_nonfinite_or_unrepresentable_float32_values(kind):
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=0)
    tensor = next(iter(checkpoint['model_state'].values()))
    tensor['values'][0] = {'nan': float('nan'), 'infinity': float('inf'), 'float32_overflow': 1e300}[kind]
    if kind == 'float32_overflow':
        reseal(checkpoint)
    with pytest.raises(ValueError):
        span.restore_grouped_span_checkpoint(checkpoint)


def test_training_rejects_unaligned_source_labels_before_any_parameter_update():
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    valid = example()
    invalid = span.GroupedSpanExample(valid.source_text, valid.modal_scope,
        (span.GroupedSpanTarget((5, 9), valid.members[0].action_span, 'O'), valid.members[1]))
    original = {key: value.clone() for key, value in model.state_dict().items()}
    with pytest.raises(ValueError, match='token boundaries'):
        span.train_grouped_span_step(model, optimizer, [invalid])
    assert not optimizer.state
    assert all(torch.equal(value, model.state_dict()[key]) for key, value in original.items())


def test_checkpoint_cannot_claim_progress_without_actual_optimizer_steps():
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    with pytest.raises(ValueError):
        span.save_grouped_span_checkpoint(model, optimizer, steps=1)
    zero = span.save_grouped_span_checkpoint(model, optimizer, steps=0)
    restored, resumed, steps = span.restore_grouped_span_checkpoint(zero)
    assert steps == 0 and not resumed.state
    assert all(torch.equal(value, restored.state_dict()[key]) for key, value in model.state_dict().items())


@pytest.mark.parametrize('kwargs', [{'seed': True}, {'max_tokens': 257}, {'slot_hidden': 1000}, {'max_token_bytes': 0}])
def test_model_configuration_is_closed_typed_and_bounded(kwargs):
    with pytest.raises(ValueError):
        span.SpanDecoderConfig(**kwargs)
    with pytest.raises(ValueError):
        span.SpanDecoderConfig.from_dict({**config().to_dict(), 'target_request': {}})
    with pytest.raises(FrozenInstanceError):
        config().seed = 4
