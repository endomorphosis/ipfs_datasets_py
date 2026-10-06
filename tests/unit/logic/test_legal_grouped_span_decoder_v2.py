"""Order-sensitive bytes, learned abstention and exact masked-training resumption."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as span


@pytest.fixture(scope='module', autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def config(seed=17):
    return span.SpanDecoderConfig(seed=seed, byte_dim=8, byte_hidden=12, token_dim=24,
                                  token_hidden=24, slot_hidden=32, max_tokens=64, max_token_bytes=32)


def example(scope='modal_over_actions'):
    source = 'The Clerk shall publish notice or shall retain records.'
    actor = (4, 9)
    actions = ('publish notice', 'retain records')
    members = tuple(span.GroupedSpanTarget(actor, (source.index(action), source.index(action) + len(action)), 'O')
                    for action in actions)
    return span.GroupedSpanExample(source, scope, members, True)


def unsupported(scope='modal_over_actions'):
    return span.GroupedSpanExample('The Clerk shlal publish notice or shlal retain records.', scope, (), False)


def reseal(checkpoint):
    checkpoint['checkpoint_sha256'] = sha256(json.dumps(
        {key: value for key, value in checkpoint.items() if key != 'checkpoint_sha256'},
        sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return checkpoint


def features(model, sources):
    captured = []
    handle = model.token_projection.register_forward_pre_hook(lambda _module, values: captured.append(values[0].detach().clone()))
    try:
        batch, tokens = span._encoded_sources(model.config, sources, ['modal_over_actions'] * len(sources))
        with torch.no_grad():
            outputs = model(*batch)
    finally:
        handle.remove()
    return captured[0], tokens, outputs


@pytest.mark.parametrize('first,second', [('shall', 'shlal'), ('must', 'msut'), ('form', 'from')])
def test_real_ordered_token_features_distinguish_internal_anagrams(first, second):
    assert sorted(first) == sorted(second) and first[0] == second[0] and first[-1] == second[-1]
    model = span.GroupedSpanDecoder(config())
    actual, _, _ = features(model, [first, second])
    # These pairs had identical mathematical features in v1's byte bag pool.
    assert float((actual[0, 0] - actual[1, 0]).abs().max()) > 1e-4


def test_byte_features_and_all_logits_are_invariant_to_neighbor_padding_widths():
    model = span.GroupedSpanDecoder(config())
    source = example().source_text
    alone, _, single = features(model, [source])
    together, tokens, padded = features(model, [source, ' '.join(['abcdefghijklmnopqrstuvwx'] * 23)])
    assert together.shape[1] > alone.shape[1]
    assert torch.allclose(alone[0], together[0, :len(tokens[0])], atol=2e-7, rtol=1e-6)
    for key in single:
        actual = padded[key][0]
        if key in span.POINTERS:
            actual = actual[:, :len(tokens[0])]
        assert torch.allclose(single[key][0], actual, atol=2e-6, rtol=1e-5)


def test_seeded_initialization_preserves_rng_and_v1_production_bytes():
    before = torch.random.get_rng_state().clone()
    first, second = span.GroupedSpanDecoder(config()), span.GroupedSpanDecoder(config())
    assert torch.equal(torch.random.get_rng_state(), before)
    assert all(torch.equal(value, second.state_dict()[key]) for key, value in first.state_dict().items())
    previous = Path(span.__file__).with_name('legal_grouped_span_decoder.py')
    assert sha256(previous.read_bytes()).hexdigest() == 'd03c343d6130e4cb099468dbd605e524fdb15bd21092bc4f526c35c4167c9d51'


def test_actual_joint_training_learns_positive_spans_and_anagram_abstention():
    samples = [example(scope) for scope in span.SCOPES] + [unsupported(scope) for scope in span.SCOPES]
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model, learning_rate=0.015)
    first = span.train_grouped_span_step(model, optimizer, samples)
    for _ in range(149):
        last = span.train_grouped_span_step(model, optimizer, samples)
    assert last['loss'] < first['loss'] * 0.025
    assert last['supported_examples'] == last['unsupported_examples'] == 2
    for sample in samples:
        predicted = span.predict_grouped_span_decoder(model, sample.source_text, sample.modal_scope)
        assert predicted['proof_ready'] is predicted['source_semantics_verified'] is False
        assert predicted['targets_used_at_inference'] is False
        if sample.supported:
            assert predicted['status'] == 'predicted'
            assert predicted['predicted_character_spans'] == [
                {'actor': list(member.actor_span), 'action': list(member.action_span)} for member in sample.members]
            assert predicted['request']['modal_scope'] == sample.modal_scope
            assert predicted['support_probability'] > 0.9
        else:
            assert predicted['status'] == 'abstained'
            assert predicted['blockers'] == ['learned_source_unsupported']
            assert predicted['request'] is None and predicted['support_probability'] < 0.1


def test_all_negative_batches_leave_structural_moments_idle_even_after_positive_training():
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model, learning_rate=0.01, weight_decay=0.2)
    span.train_grouped_span_step(model, optimizer, [example()])
    names = dict(model.named_parameters())
    structural = ('slot_queries.', 'attention_keys.', 'slot_fusion.', 'count_head.', 'scope_head.',
                  'modality_head.', 'pointer_keys.', 'pointer_queries.')
    idle = {name: parameter.clone() for name, parameter in names.items() if name.startswith(structural)}
    moments = {name: deepcopy(optimizer.state[names[name]]) for name in idle}
    before_support = model.support_head.weight.clone()
    metrics = span.train_grouped_span_step(model, optimizer, [unsupported()])
    assert metrics['supported_examples'] == 0 and metrics['unsupported_examples'] == 1
    assert all(metrics[key + '_loss'] == 0 for key in ('count', 'scope', 'modality', *span.POINTERS))
    assert metrics['support_loss'] > 0
    assert not torch.equal(model.support_head.weight, before_support)
    for name, before in idle.items():
        assert names[name].grad is None
        assert torch.equal(names[name], before)
        assert all(torch.equal(value, optimizer.state[names[name]][key]) for key, value in moments[name].items())
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=2)
    assert {record['step']['values'][0] for record in checkpoint['optimizer']['state'].values()} == {1.0, 2.0}


@pytest.mark.parametrize('history', ['negative_only', 'positive_then_negative', 'mixed_then_negative'])
def test_masked_checkpoint_restores_exact_next_update_and_parameter_steps(history):
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model, learning_rate=0.006, weight_decay=0.1)
    batches = {'negative_only': [[unsupported()]], 'positive_then_negative': [[example()], [unsupported()]],
               'mixed_then_negative': [[example(), unsupported()], [unsupported()]]}[history]
    for batch in batches:
        span.train_grouped_span_step(model, optimizer, batch)
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=len(batches))
    if history == 'negative_only':
        assert len(checkpoint['optimizer']['state']) < len(list(model.parameters()))
    serialized = json.dumps(checkpoint)
    assert 'Clerk' not in serialized and example().source_text not in serialized
    restored, resumed, steps = span.restore_grouped_span_checkpoint(json.loads(serialized))
    assert steps == len(batches)
    original = span.train_grouped_span_step(model, optimizer, [example(), unsupported()])
    continued = span.train_grouped_span_step(restored, resumed, [example(), unsupported()])
    assert original == continued
    assert span.save_grouped_span_checkpoint(model, optimizer, steps=steps + 1) == span.save_grouped_span_checkpoint(restored, resumed, steps=steps + 1)


@pytest.mark.parametrize('mutation', ['missing_shared', 'partial_structural', 'shared_step', 'unequal_structural',
                                      'future_step', 'float_step', 'zero_step', 'v1_schema', 'threshold', 'byte_profile'])
def test_checkpoint_rejects_invalid_masked_progress_and_version_even_if_resealed(mutation):
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    span.train_grouped_span_step(model, optimizer, [example()])
    span.train_grouped_span_step(model, optimizer, [unsupported()])
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=2)
    names = [name for name, _ in model.named_parameters()]
    index = str(names.index('count_head.weight'))
    if mutation == 'missing_shared':
        del checkpoint['optimizer']['state']['0']
    elif mutation == 'partial_structural':
        del checkpoint['optimizer']['state'][index]
    elif mutation == 'shared_step':
        checkpoint['optimizer']['state']['0']['step']['values'] = [1.0]
    elif mutation in {'unequal_structural', 'future_step', 'float_step', 'zero_step'}:
        checkpoint['optimizer']['state'][index]['step']['values'] = [{'unequal_structural': 2.0, 'future_step': 3.0,
                                                                     'float_step': 1.5, 'zero_step': 0.0}[mutation]]
    elif mutation == 'v1_schema':
        checkpoint['schema'] = 'legal-grouped-span-decoder-checkpoint/v1'
    elif mutation == 'threshold':
        checkpoint['profile']['support_threshold'] = 0.1
    else:
        checkpoint['profile']['byte_encoder'] = 'bag_pool'
    with pytest.raises(ValueError):
        span.restore_grouped_span_checkpoint(reseal(checkpoint))


@pytest.mark.parametrize('supported,members', [(True, ()), (False, 'positive'), (1, ()), ('yes', ())])
def test_support_targets_are_explicit_and_cannot_smuggle_negative_structure(supported, members):
    positive = example()
    with pytest.raises(ValueError):
        span.GroupedSpanExample(positive.source_text, positive.modal_scope,
                                positive.members if members == 'positive' else members, supported)


def test_config_is_strict_and_checkpoint_cannot_claim_unperformed_steps():
    with pytest.raises(ValueError):
        span.SpanDecoderConfig(byte_hidden=True)
    with pytest.raises(ValueError):
        span.SpanDecoderConfig(byte_hidden=129)
    with pytest.raises(ValueError):
        span.SpanDecoderConfig.from_dict({**config().to_dict(), 'support_threshold': 0.4})
    with pytest.raises(FrozenInstanceError):
        config().byte_hidden = 30
    model = span.GroupedSpanDecoder(config())
    optimizer = span.make_grouped_span_optimizer(model)
    with pytest.raises(ValueError):
        span.save_grouped_span_checkpoint(model, optimizer, steps=1)
    checkpoint = span.save_grouped_span_checkpoint(model, optimizer, steps=0)
    restored, resumed, steps = span.restore_grouped_span_checkpoint(checkpoint)
    assert steps == 0 and not resumed.state
    assert all(torch.equal(value, restored.state_dict()[key]) for key, value in model.state_dict().items())
