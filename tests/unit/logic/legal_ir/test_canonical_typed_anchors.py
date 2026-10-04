"""Prediction-driven exact anchors, with no target or semantic fallback."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec as byte_codec
from ipfs_datasets_py.logic.legal_ir import canonical_typed_anchors as subject

SOURCE = ('The clerk must record evidence within ten days if fees are paid and '
          'the application is complete, unless a court order applies or a legal hold applies.')
FALSE_FIELDS = ('target_access', 'model_executed', 'source_fidelity_established',
                'qualified', 'proof_authority', 'accepted')


def proposal(source=SOURCE):
    rule = dict(actor='clerk', modality='O', action='record', object='evidence',
                conditions=['application_complete', 'fees_paid'],
                exceptions=['court_order', 'legal_hold'], temporal=['within_ten_days'])
    surfaces = {'actor': 'clerk', 'modality': 'must', 'action': 'record', 'object': 'evidence',
                'conditions/0': 'the application is complete', 'conditions/1': 'fees are paid',
                'exceptions/0': 'a court order applies', 'exceptions/1': 'a legal hold applies',
                'temporal/0': 'within\t ten  days' if 'within\t ten  days' in source else 'within ten days'}
    anchors = []
    for leaf, text in sorted(surfaces.items()):
        facet = leaf.split('/')[0]
        symbol = rule[facet] if '/' not in leaf else rule[facet][int(leaf.split('/')[1])]
        start = source.index(text)
        anchors.append(dict(field_path='/rules/0/' + leaf, facet=facet,
                            canonical_symbol=symbol, start=start, end=start + len(text),
                            source_text=text, offset_unit='unicode_character_half_open'))
    return dict(schema=byte_codec.PROPOSAL_SCHEMA,
                source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                canonical_ir={'rules': [rule]}, anchors=anchors,
                facet_operators=dict(conditions='all', exceptions='any', temporal='all'),
                single_rule_scope=True, **dict.fromkeys(FALSE_FIELDS, False))


def request(identity='one', source=SOURCE, **changes):
    result = dict(id=identity, source_text=source, context_text='', requires_context_resolution=False)
    result.update(changes)
    return result


def queries(value=None):
    value = proposal() if value is None else value
    return [dict(field_path=a['field_path'], facet=a['facet'], canonical_symbol=a['canonical_symbol'],
                 query_token_id=index + 3) for index, a in enumerate(value['anchors'])]


def scores_for(value, source):
    tokens = subject.tokenize_source(source)
    start, end = [], []
    for anchor in value['anchors']:
        left = next(i for i, token in enumerate(tokens) if token['start'] == anchor['start'])
        right = next(i for i, token in enumerate(tokens) if token['end'] == anchor['end'])
        start.append([8.0 if i == left else 0.0 for i in range(len(tokens))])
        end.append([8.0 if i == right else 0.0 for i in range(len(tokens))])
    return tokens, start, end


def test_source_tokens_preserve_original_occurrences_and_casefold_separately():
    source = 'É📄 The Straße must RECORD evidence; evidence.'
    tokens = subject.tokenize_source(source)
    assert all(source[token['start']:token['end']] == token['text'] for token in tokens)
    assert all(token['normalized'] == token['text'].casefold() for token in tokens)
    repeated = [token for token in tokens if token['text'] == 'evidence']
    assert len(repeated) == 2 and repeated[0]['start'] != repeated[1]['start']
    street = next(token for token in tokens if token['text'] == 'Straße')
    assert street['normalized'] == 'strasse'
    assert len(source[:street['start']].encode()) != street['start']


@pytest.mark.parametrize('source', ['', ' ', None, 8, '\ud800', 'x' * 16385])
def test_source_tokenizer_rejects_invalid_input_without_truncation(source):
    with pytest.raises(ValueError):
        subject.tokenize_source(source)


def test_token_aligned_scores_reconstruct_all_predicted_leaves_without_alias_lookup():
    value = proposal()
    tokens, start, end = scores_for(value, SOURCE)
    predicted = subject._predict_spans(start, end, tokens, queries(value), source_text=SOURCE)
    assert predicted['anchors'] == value['anchors']
    assert len(predicted['anchors']) == 9
    assert value['canonical_ir']['rules'][0]['conditions'][0] not in SOURCE
    assert all(anchor['source_text'] == SOURCE[anchor['start']:anchor['end']]
               for anchor in predicted['anchors'])


def test_repeated_surface_uses_predicted_occurrence_not_first_text_match():
    source = SOURCE + ' evidence'
    value = proposal(source)
    anchor = next(item for item in value['anchors'] if item['facet'] == 'object')
    anchor.update(start=len(SOURCE) + 1, end=len(source), source_text='evidence')
    tokens, start, end = scores_for(value, source)
    assert subject._predict_spans(start, end, tokens, queries(value), source_text=source)['anchors'] == value['anchors']


@pytest.mark.parametrize('field,poison', [('start', float('nan')), ('end', float('inf')),
                                      ('start', float('-inf'))])
def test_nonfinite_anchor_scores_reject_the_entire_prediction(field, poison):
    tokens, start, end = scores_for(proposal(), SOURCE)
    (start if field == 'start' else end)[-1][-1] = poison
    with pytest.raises(ValueError):
        subject._predict_spans(start, end, tokens, queries(), source_text=SOURCE)


def test_anchor_tie_is_rejected_instead_of_arbitrary_argmax():
    tokens = subject.tokenize_source('The clerk must record evidence.')
    zeros = [[0.0] * len(tokens)]
    with pytest.raises(ValueError):
        subject._predict_spans(zeros, zeros, tokens, queries()[:1], source_text='The clerk must record evidence.')


def test_overlapping_predicted_leaf_spans_reject_whole_candidate():
    tokens, start, end = scores_for(proposal(), SOURCE)
    start[1], end[1] = list(start[0]), list(end[0])
    with pytest.raises(ValueError):
        subject._predict_spans(start, end, tokens, queries(), source_text=SOURCE)


@pytest.mark.parametrize('change', ['rows', 'columns', 'empty'])
def test_anchor_score_shape_mismatch_rejected(change):
    tokens, start, end = scores_for(proposal(), SOURCE)
    if change == 'rows':
        start.pop()
    elif change == 'columns':
        end[-1].pop()
    else:
        tokens.clear()
    with pytest.raises(ValueError):
        subject._predict_spans(start, end, tokens, queries(), source_text=SOURCE)


def test_multiword_anchor_preserves_tabs_and_repeated_source_spaces():
    source = SOURCE.replace('within ten days', 'within\t ten  days')
    value = proposal(source)
    anchor = next(a for a in value['anchors'] if a['facet'] == 'temporal')
    anchor.update(end=anchor['start'] + len('within\t ten  days'), source_text='within\t ten  days')
    tokens, start, end = scores_for(value, source)
    assert subject._predict_spans(start, end, tokens, queries(value), source_text=source)['anchors'] == value['anchors']


def boundary_decoder(monkeypatch, *, generated=None, parent_error=None, anchor_error=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec

    original = proposal()
    alternative = copy.deepcopy(original['canonical_ir'])
    alternative['rules'][0]['modality'] = 'F'
    frozen_codec = codec.fit_codec([
        dict(id='fixture', source_text=SOURCE, canonical_ir=original['canonical_ir']),
        dict(id='unit-alternative', source_text=SOURCE.replace('must', 'must not'), canonical_ir=alternative),
    ])
    generated = copy.deepcopy(original['canonical_ir'] if generated is None else generated)
    generated_ids = codec.encode_target(frozen_codec, generated)
    decoder = subject.TypedAnchorDecoder.__new__(subject.TypedAnchorDecoder)
    decoder.source_checkpoint_sha256 = 'a' * 64
    decoder.anchor_checkpoint_sha256 = 'b' * 64
    decoder.parent = SimpleNamespace(codec=frozen_codec, checkpoint_sha256='a' * 64,
                                     checkpoint={'progress': {'optimizer_steps': 0}})
    calls = {'parent': [], 'head': []}
    monkeypatch.setattr(decoder, '_assert_state', lambda: None)

    def source_decode(texts):
        calls['parent'].append(copy.deepcopy(texts))
        if parent_error is not None:
            raise parent_error
        native = subject._native()
        display = native._display(generated)
        output = dict(family='deontic', format='typed-deontic-rule/v1', payload=generated['rules'][0],
                      formula_text=display, formula_text_role='display_only_full_ast_is_authoritative',
                      syntax_scope='canonical_rule_schema_and_decoder_grammar',
                      origin='learned_source_conditioned_formula_decoder', **native.FALSE)
        rows = [dict(source_sha256=hashlib.sha256(text.encode()).hexdigest(), status='decoded', reason=None,
                     canonical_ir=copy.deepcopy(generated), generated_token_ids=list(generated_ids),
                     formula_text=display, formal_outputs=[copy.deepcopy(output)],
                     minimum_decision_logit_margin=1.0, syntax_scope='canonical_rule_schema_and_decoder_grammar',
                     target_access=False, teacher_forcing=False, training_executed=False,
                     source_input_conditioned=True, independent_text_to_logic=True, learned_formula_generation=True,
                     sample_memory_used=False, family_syntax_checked=False, temperature=0, **native.FALSE)
                for text in texts]
        return dict(schema='learned-legal-formula-inference/v1', lineage_id=native.LINEAGE_ID,
                    checkpoint_sha256='a' * 64, rows=rows, target_access=False, teacher_forcing=False,
                    training_executed=False, source_input_conditioned=True, independent_text_to_logic=True,
                    learned_formula_generation=True, trained_checkpoint=False, checkpoint_optimizer_steps=0,
                    status='decoded', decoded_formulas_generated=True, decoded_count=len(rows), **native.FALSE)

    def anchor_generated(source, canonical_ir):
        calls['head'].append((source, copy.deepcopy(canonical_ir)))
        if anchor_error is not None:
            raise anchor_error
        value = proposal(source)
        value['canonical_ir'] = copy.deepcopy(canonical_ir)
        for anchor in value['anchors']:
            facet = anchor['facet']
            rule = canonical_ir['rules'][0]
            anchor['canonical_symbol'] = rule[facet] if facet not in ('conditions', 'exceptions', 'temporal') else rule[facet][int(anchor['field_path'].rsplit('/', 1)[1])]
        return dict(proposal=value, diagnostics=[], source_tokens=subject.tokenize_source(source))

    monkeypatch.setattr(decoder, '_source_decode', source_decode)
    monkeypatch.setattr(decoder, '_anchor_generated', anchor_generated)
    return decoder, calls


@pytest.mark.parametrize('changes', [dict(canonical_ir={}), dict(target={}), dict(proposal={}),
                                    dict(latents=[]), dict(requires_context_resolution=1)])
def test_source_requests_are_closed_and_reject_target_bearing_inputs_before_calls(monkeypatch, changes):
    decoder, calls = boundary_decoder(monkeypatch)
    with pytest.raises(ValueError):
        decoder.decode_proposals([request(**changes)])
    assert calls == {'parent': [], 'head': []}


@pytest.mark.parametrize('source,changes,outcome', [
    ('Every clerk must record evidence.', {}, 'source_blocked'),
    ('The clerk is not required to record evidence.', {}, 'source_blocked'),
    (SOURCE, dict(context_text='The clerk means the custodian.'), 'clarification_required'),
    (SOURCE, dict(requires_context_resolution=True), 'clarification_required'),
    ('The astronaut must record evidence.', {}, 'source_encoding_unavailable'),
])
def test_blocked_unresolved_and_unknown_source_inputs_have_no_owner_or_head_calls(monkeypatch, source, changes, outcome):
    decoder, calls = boundary_decoder(monkeypatch)
    result = decoder.decode_proposals([request(source=source, **changes)])
    assert result['rows'][0]['outcome'] == outcome
    assert calls == {'parent': [], 'head': []}
    assert result['parent_invocation_count'] == result['anchor_invocation_count'] == 0
    assert result['inference_attempted'] is False and result['rows'][0]['proposal'] is None


def test_actual_generation_flags_are_separate_from_byte_transport_constants(monkeypatch):
    decoder, calls = boundary_decoder(monkeypatch)
    requests = [request()]
    original = copy.deepcopy(requests)
    result = decoder.decode_proposals(requests)
    assert requests == original
    assert result['parent_inference_attempted'] and result['anchor_inference_attempted']
    assert result['parent_invocation_count'] == result['anchor_invocation_count'] == 1
    assert result['rows'][0]['outcome'] == 'anchored_proposal'
    assert result['proposal_flag_scope'] == 'transport_validation_only_not_generation_provenance'
    assert all(result['rows'][0]['proposal'][field] is False for field in FALSE_FIELDS)
    assert all(result[field] is False for field in ('target_access', 'teacher_forcing', 'proof_authority',
                                                 'source_fidelity_established', 'accepted'))
    assert calls['head'] == [(SOURCE, proposal()['canonical_ir'])]


def test_inference_does_not_refit_vocabulary_encode_targets_or_read_source_grammar(monkeypatch):
    decoder, _ = boundary_decoder(monkeypatch)
    native = subject._native()

    def forbidden(*args, **kwargs):
        raise AssertionError('inference requested a teacher or source grammar')

    monkeypatch.setattr(native.codec_module, 'fit_codec', forbidden)
    monkeypatch.setattr(native.codec_module, 'encode_target', forbidden)
    monkeypatch.setattr(native, 'train_decoder', forbidden)
    result = decoder.decode_proposals([request()])
    assert result['proposal_count'] == 1


@pytest.mark.parametrize('error', [ValueError('ambiguous_anchor_scores'), ValueError('predicted_source_spans_overlap'),
                                 ValueError('nonfinite anchor scores')])
def test_anchor_rejection_never_returns_partial_canonical_proposal(monkeypatch, error):
    decoder, calls = boundary_decoder(monkeypatch, anchor_error=error)
    result = decoder.decode_proposals([request()])
    assert result['rows'][0]['outcome'] == 'anchor_abstained'
    assert result['rows'][0]['proposal'] is None and result['rows'][0]['anchor_diagnostics'] is None
    assert result['proposal_count'] == 0 and len(calls['head']) == 1


@pytest.mark.parametrize('error', [ImportError('unavailable'), OSError('unavailable'), RuntimeError('unavailable')])
def test_operational_parent_failure_preserves_denominator_and_skips_head(monkeypatch, error):
    decoder, calls = boundary_decoder(monkeypatch, parent_error=error)
    result = decoder.decode_proposals([request()])
    assert result['rows'][0]['outcome'] == 'parent_unavailable'
    assert result['input_count'] == 1 and result['parent_completion_count'] == 0
    assert result['parent_exception_type'] == type(error).__name__ and calls['head'] == []


def test_parent_contract_failure_propagates_and_is_not_operational_unavailability(monkeypatch):
    decoder, _ = boundary_decoder(monkeypatch, parent_error=ValueError('receipt contract differs'))
    with pytest.raises(ValueError):
        decoder.decode_proposals([request()])


def test_predicted_modality_is_preserved_without_a_reference_rule_repair(monkeypatch):
    generated = proposal()['canonical_ir']
    generated['rules'][0]['modality'] = 'F'
    decoder, calls = boundary_decoder(monkeypatch, generated=generated)
    result = decoder.decode_proposals([request()])
    value = result['rows'][0]['proposal']
    assert calls['head'][0][1] == generated
    assert value['canonical_ir']['rules'][0]['modality'] == 'F'
    assert next(anchor for anchor in value['anchors'] if anchor['facet'] == 'modality')['source_text'] == 'must'
    assert result['source_fidelity_established'] is False


def test_typed_query_ids_come_from_predicted_fields_and_reject_unknown_atoms(monkeypatch):
    decoder, _ = boundary_decoder(monkeypatch)
    generated = proposal()['canonical_ir']
    leaf_queries = subject._leaf_queries(decoder.parent.codec, generated)
    assert len(leaf_queries) == 9
    for query in leaf_queries:
        assert json.loads(decoder.parent.codec['target_vocabulary'][query['query_token_id']]) == [
            'atom', query['facet'], query['canonical_symbol']]
    generated['rules'][0]['conditions'] = ['unseen_condition']
    with pytest.raises(ValueError):
        subject._leaf_queries(decoder.parent.codec, generated)


@pytest.mark.parametrize('mutation', [
    lambda batch: batch.update(checkpoint_sha256='0' * 64),
    lambda batch: batch.update(decoded_count=True),
    lambda batch: batch.update(proof_authority=True),
    lambda batch: batch['rows'][0].update(source_sha256='0' * 64),
    lambda batch: batch['rows'][0].update(canonical_ir={'rules': []}),
    lambda batch: batch['rows'][0].update(generated_token_ids=[1, 2]),
    lambda batch: batch['rows'][0].update(minimum_decision_logit_margin=float('nan')),
    lambda batch: batch['rows'][0].update(extra='unsupported'),
])
def test_malformed_parent_receipts_fail_the_call_before_anchor_head(monkeypatch, mutation):
    decoder, calls = boundary_decoder(monkeypatch)
    original_decode = decoder._source_decode

    def altered(texts):
        value = original_decode(texts)
        mutation(value)
        return value

    monkeypatch.setattr(decoder, '_source_decode', altered)
    with pytest.raises(ValueError):
        decoder.decode_proposals([request()])
    assert calls['head'] == []


def test_parent_abstention_skips_anchor_head_and_keeps_native_reason(monkeypatch):
    decoder, calls = boundary_decoder(monkeypatch)
    original_decode = decoder._source_decode

    def abstained(texts):
        value = original_decode(texts)
        row = value['rows'][0]
        for key in ('generated_token_ids', 'minimum_decision_logit_margin', 'syntax_scope'):
            row.pop(key)
        row.update(status='abstained', reason='zero_output_head', canonical_ir=None,
                   formula_text=None, formal_outputs=[], family_syntax_checked=False)
        value.update(status='abstained', decoded_count=0, decoded_formulas_generated=False)
        return value

    monkeypatch.setattr(decoder, '_source_decode', abstained)
    result = decoder.decode_proposals([request()])
    assert result['rows'][0]['outcome'] == 'parent_abstained'
    assert result['rows'][0]['reason'] == 'zero_output_head'
    assert result['anchor_invocation_count'] == 0 and calls['head'] == []


def test_duplicate_request_ids_and_late_target_injection_prevent_whole_batch_calls(monkeypatch):
    decoder, calls = boundary_decoder(monkeypatch)
    for requests in ([request(), request()], [request(), request('two', target={})]):
        with pytest.raises(ValueError):
            decoder.decode_proposals(requests)
    assert calls == {'parent': [], 'head': []}


@pytest.fixture(scope='module')
def numerical_checkpoints():
    """Two bounded anchor-head updates on one authored unit fixture."""
    torch = pytest.importorskip('torch')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning

    original_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        example = dict(id='unit-fixture', source_text=SOURCE, proposal=proposal())
        parent = legal_formula_learning.train_decoder(
            [dict(id=example['id'], source_text=SOURCE, canonical_ir=example['proposal']['canonical_ir'])],
            [], epochs=1, max_seconds=0, learning_rate=.01, batch_size=1,
            seed=19, hidden_size=8, embedding_dim=8)['checkpoint']
        parent_before = copy.deepcopy(parent)
        initial = subject.train_anchor_decoder(parent, [example], epochs=1, max_seconds=0,
                                              batch_size=1, seed=23)
        trained = subject.train_anchor_decoder(parent, [example], epochs=2, max_seconds=30,
                                              batch_size=1, seed=23)
        assert parent == parent_before
        yield torch, parent, initial, trained, example
    finally:
        torch.set_num_threads(original_threads)


def test_actual_head_updates_and_keeps_source_parent_frozen(numerical_checkpoints):
    _, parent, initial, trained, _ = numerical_checkpoints
    subject.validate_checkpoint(parent, initial['checkpoint'])
    subject.validate_checkpoint(parent, trained['checkpoint'])
    assert initial['checkpoint']['model_state'] != trained['checkpoint']['model_state']
    assert subject.checkpoint_digest(initial['checkpoint']) != subject.checkpoint_digest(trained['checkpoint'])
    assert trained['report']['gradient_norm_max'] > 0
    assert trained['report']['optimizer_steps'] == 2
    assert trained['report']['source_parent_before_sha256'] == trained['report']['source_parent_after_sha256']
    assert trained['report']['source_parent_training_executed'] is False
    assert initial['report']['optimizer_steps'] == 0 and initial['report']['training_executed'] is False


def test_private_reloads_have_disjoint_anchor_and_parent_tensor_storage(numerical_checkpoints):
    torch, parent, _, trained, _ = numerical_checkpoints
    before_rng = torch.random.get_rng_state().clone()
    first = subject.TypedAnchorDecoder(parent, trained['checkpoint'])
    second = subject.TypedAnchorDecoder(parent, trained['checkpoint'])
    assert torch.equal(torch.random.get_rng_state(), before_rng)
    for left_model, right_model in ((first.model, second.model), (first.parent.model, second.parent.model)):
        left, right = dict(left_model.named_parameters()), dict(right_model.named_parameters())
        assert set(left) == set(right)
        assert all(torch.equal(left[name], right[name]) for name in left)
        assert all(left[name].data_ptr() != right[name].data_ptr() for name in left)


def _poison_first_scalar(value, poison):
    if type(value) is list:
        if type(value[0]) is list:
            _poison_first_scalar(value[0], poison)
        else:
            value[0] = poison
    else:
        raise AssertionError('tensor payload must be a list')


@pytest.mark.parametrize('poison', [float('nan'), float('inf'), True])
def test_nonfinite_and_boolean_saved_head_tensors_rejected(numerical_checkpoints, poison):
    _, parent, _, trained, _ = numerical_checkpoints
    changed = copy.deepcopy(trained['checkpoint'])
    _poison_first_scalar(next(iter(changed['model_state'].values())), poison)
    with pytest.raises(ValueError):
        subject.validate_checkpoint(parent, changed)


def test_saved_head_tensor_shape_tamper_rejected(numerical_checkpoints):
    _, parent, _, trained, _ = numerical_checkpoints
    changed = copy.deepcopy(trained['checkpoint'])
    next(iter(changed['model_state'].values())).pop()
    with pytest.raises(ValueError):
        subject.validate_checkpoint(parent, changed)


def test_rebound_parent_checkpoint_is_rejected(numerical_checkpoints):
    _, parent, _, trained, _ = numerical_checkpoints
    changed_parent = copy.deepcopy(parent)
    tensor = next(iter(changed_parent['model_state'].values()))
    _poison_first_scalar(tensor, 0.125)
    with pytest.raises(ValueError):
        subject.validate_checkpoint(changed_parent, trained['checkpoint'])


def test_unknown_source_training_labels_do_not_extend_frozen_parent_codec(numerical_checkpoints):
    _, parent, _, _, example = numerical_checkpoints
    changed = copy.deepcopy(example)
    source = 'Extraterrestrial ' + SOURCE
    changed['source_text'] = source
    changed['proposal'] = proposal(source)
    before = copy.deepcopy(parent)
    with pytest.raises(ValueError):
        subject.train_anchor_decoder(parent, [changed], epochs=1, max_seconds=0, batch_size=1, seed=23)
    assert parent == before


def test_unknown_canonical_training_atom_does_not_extend_parent_codec(numerical_checkpoints):
    _, parent, _, _, example = numerical_checkpoints
    changed = copy.deepcopy(example)
    changed['proposal']['canonical_ir']['rules'][0]['actor'] = 'new_unseen_actor'
    next(anchor for anchor in changed['proposal']['anchors'] if anchor['facet'] == 'actor')[
        'canonical_symbol'] = 'new_unseen_actor'
    before = copy.deepcopy(parent)
    with pytest.raises(ValueError):
        subject.train_anchor_decoder(parent, [changed], epochs=1, max_seconds=0, batch_size=1, seed=23)
    assert parent == before


def test_resumed_adam_weights_and_moments_match_uninterrupted_updates(numerical_checkpoints):
    _, parent, _, trained, example = numerical_checkpoints
    first = subject.train_anchor_decoder(parent, [example], epochs=1, max_seconds=30, batch_size=1, seed=23)
    original = copy.deepcopy(first['checkpoint'])
    second = subject.train_anchor_decoder(parent, [example], epochs=1, max_seconds=30, batch_size=1,
                                         seed=23, checkpoint=first['checkpoint'])
    assert first['checkpoint'] == original
    for field in ('model_state', 'optimizer_state', 'progress'):
        assert second['checkpoint'][field] == trained['checkpoint'][field]
    assert second['checkpoint']['parent_anchor_checkpoint_sha256'] == subject.checkpoint_digest(first['checkpoint'])


def test_exact_checkpoint_file_binding_and_exclusive_write(numerical_checkpoints, tmp_path):
    _, parent, _, trained, _ = numerical_checkpoints
    path = tmp_path / 'anchor-checkpoint.json'
    reference = subject.save_checkpoint(parent, trained['checkpoint'], path)
    assert subject.load_checkpoint(parent, path, expected_sha256=reference['sha256']) == trained['checkpoint']
    with pytest.raises(FileExistsError):
        subject.save_checkpoint(parent, trained['checkpoint'], path)
    with pytest.raises(ValueError):
        subject.load_checkpoint(parent, path, expected_sha256='0' * 64)
    changed = json.loads(path.read_bytes())
    changed['implementation']['files']['canonical_typed_anchors.py'] = '0' * 64
    with pytest.raises(ValueError):
        subject.validate_checkpoint(parent, changed)


def test_actual_free_running_inference_is_immutable_reproducible_and_target_free(numerical_checkpoints, monkeypatch):
    torch, parent, _, trained, _ = numerical_checkpoints
    decoder = subject.TypedAnchorDecoder(parent, trained['checkpoint'])
    before_parent = {name: value.detach().clone() for name, value in decoder.parent.model.state_dict().items()}
    before_head = {name: value.detach().clone() for name, value in decoder.model.state_dict().items()}
    before_rng = torch.random.get_rng_state().clone()

    def forbidden(*args, **kwargs):
        raise AssertionError('free inference accessed target supervision')

    monkeypatch.setattr(subject._native().codec_module, 'encode_target', forbidden)
    monkeypatch.setattr(subject._native(), 'train_decoder', forbidden)
    first = decoder.decode_proposals([request()])
    second = decoder.decode_proposals([request()])
    assert first == second
    assert torch.equal(torch.random.get_rng_state(), before_rng)
    assert all(torch.equal(value, before_parent[name]) for name, value in decoder.parent.model.state_dict().items())
    assert all(torch.equal(value, before_head[name]) for name, value in decoder.model.state_dict().items())
    assert all(parameter.grad is None and not parameter.requires_grad for parameter in decoder.parent.model.parameters())
    first['rows'][0]['parent_row']['reason'] = 'mutated caller receipt'
    assert second['rows'][0]['parent_row']['reason'] != first['rows'][0]['parent_row']['reason']


@pytest.mark.parametrize('owner', ['parent', 'head'])
def test_changed_private_numerical_state_rejects_inference(numerical_checkpoints, owner):
    torch, parent, _, trained, _ = numerical_checkpoints
    decoder = subject.TypedAnchorDecoder(parent, trained['checkpoint'])
    model = decoder.parent.model if owner == 'parent' else decoder.model
    with torch.no_grad():
        next(model.parameters()).flatten()[0].add_(1.0)
    with pytest.raises(ValueError):
        decoder.decode_proposals([request()])
