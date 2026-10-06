"""Source-head integration with the existing main-family renderer, without legacy grouping."""
from copy import deepcopy
from hashlib import sha256
import inspect
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_coordination_evaluation as evaluation
from ipfs_datasets_py.logic.deontic import coordination_decoder as semantic
from ipfs_datasets_py.logic.deontic.utils import deontic_parser
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder as v1
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as v2

SOURCE = 'The Clerk shall publish notice or shall retain records.'


@pytest.fixture(scope='module', autouse=True)
def bounded_cpu_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


def deny(*_args, **_kwargs):
    raise AssertionError('Forbidden source parser, target helper, or fallback called')


def model(module):
    return module.GroupedSpanDecoder(module.SpanDecoderConfig(
        seed=7, byte_dim=8, token_dim=16, token_hidden=16, slot_hidden=24,
        max_tokens=64, max_token_bytes=32))


def fixed_heads(module, scope, *, support=10.0, invalid_span=False):
    """Controlled logits exercise integration contracts, not training accuracy."""
    def forward(token_bytes, token_mask, caller_scope):
        assert token_bytes.shape[0] == 1 and token_mask.sum() == 10
        assert caller_scope.tolist() == [module.SCOPES.index(scope)]
        heads = {'count': torch.full((1, 7), -10.0), 'scope': torch.full((1, 2), -10.0),
                 'modality': torch.full((1, 8, 3), -10.0),
                 **{name: torch.full((1, 8, 10), -10.0) for name in module.POINTERS}}
        heads['count'][0, 0] = 10.0
        heads['scope'][0, module.SCOPES.index(scope)] = 10.0
        heads['modality'][0, :2, 0] = 10.0
        for slot, (start, end) in enumerate(((3, 4), (7, 8))):
            heads['actor_start'][0, slot, 1] = 10.0
            heads['actor_end'][0, slot, 1] = 10.0
            heads['action_start'][0, slot, end if invalid_span else start] = 10.0
            heads['action_end'][0, slot, start if invalid_span else end] = 10.0
        if module is v2:
            heads['support'] = torch.tensor([support], dtype=torch.float32)
        return heads
    return forward


def expected(scope='modal_over_actions'):
    return semantic.CoordinationDecodeRequest(scope, 'inclusive_or', 'universal_actor_predicate', (
        semantic.CoordinationDecodeMember('clerk', 'O', 'publish notice'),
        semantic.CoordinationDecodeMember('clerk', 'O', 'retain records'),
    ))


def poison_source_and_training(monkeypatch, module):
    for name in ('extract_normative_elements', 'analyze_normative_sentence', 'classify_modal'):
        if hasattr(deontic_parser, name):
            monkeypatch.setattr(deontic_parser, name, deny)
    for name in ('_labels', 'GroupedSpanTarget', 'GroupedSpanExample', 'train_grouped_span_step'):
        monkeypatch.setattr(module, name, deny)
    if module is v2:
        monkeypatch.setattr(v1, 'predict_grouped_span_decoder', deny)


@pytest.mark.parametrize('module', [v1, v2], ids=['v1', 'v2'])
@pytest.mark.parametrize('scope', v2.SCOPES)
def test_copied_request_renders_with_main_family_owners_and_no_parser_or_teacher(monkeypatch, module, scope):
    instance = model(module)
    monkeypatch.setattr(instance, 'forward', fixed_heads(module, scope))
    poison_source_and_training(monkeypatch, module)
    result = module.predict_grouped_span_decoder(instance, SOURCE, scope)
    assert result['status'] == 'predicted'
    request = semantic.CoordinationDecodeRequest.from_dict(result['request'])
    assert request.to_dict() == expected(scope).to_dict()
    assert result['predicted_character_spans'] == [
        {'actor': [4, 9], 'action': [16, 30]}, {'actor': [4, 9], 'action': [40, 54]}]
    rendered = semantic.decode_coordination_request(request)
    assert rendered['family_validation']['passed'] is True
    assert rendered['native_validation']['validator'] == 'strict_native_reparse_and_exact_AST'
    assert rendered['native_payload']['payload']['formulas'][0]['ast'] == rendered['native_ast']
    assert rendered['native_ast']['node_type'] == ('DeonticFormula' if scope == 'modal_over_actions' else 'BinaryFormula')
    assert rendered['lean_body']
    for flag in ('proof_ready', 'source_semantics_verified', 'admitted', 'formalized'):
        assert rendered[flag] is False
    assert result['targets_used_at_inference'] is False
    # These tests establish typed/native generation, not Lake execution/admission.
    assert rendered['context'] == 'source_withheld_semantic_ir'


def test_actual_neural_forward_receives_only_source_tensors_and_caller_scope(monkeypatch):
    instance = model(v2)
    calls = []
    original = instance.forward
    def observe(*args):
        calls.append(tuple((value.dtype, tuple(value.shape)) for value in args))
        return original(*args)
    monkeypatch.setattr(instance, 'forward', observe)
    poison_source_and_training(monkeypatch, v2)
    result = v2.predict_grouped_span_decoder(instance, SOURCE, 'modal_over_actions')
    assert len(calls) == 1 and len(calls[0]) == 3
    assert calls[0][0][0] == torch.long and calls[0][1] == (torch.bool, (1, 10))
    assert result['raw_prediction'] is not None
    assert result['status'] in {'predicted', 'blocked', 'abstained'}
    assert result['proof_ready'] is result['source_semantics_verified'] is False
    assert list(inspect.signature(v2.predict_grouped_span_decoder).parameters) == ['model', 'source_text', 'modal_scope']


@pytest.mark.parametrize('scope', [None, '', 'guessed_scope'])
def test_missing_declaration_abstains_before_source_encoding_or_forward(monkeypatch, scope):
    instance = model(v2)
    monkeypatch.setattr(instance, 'forward', deny)
    monkeypatch.setattr(v2, '_encoded_sources', deny)
    result = v2.predict_grouped_span_decoder(instance, SOURCE, scope)
    assert result['status'] == 'abstained' and result['request'] is None
    assert result['blockers'] == ['explicit_caller_scope_required']


@pytest.mark.parametrize('kind', ['learned_refusal', 'invalid_span'])
def test_refused_and_invalid_predictions_remain_null_and_in_evaluation_denominator(monkeypatch, kind):
    instance = model(v2)
    monkeypatch.setattr(instance, 'forward', fixed_heads(
        v2, 'modal_over_actions', support=-10.0 if kind == 'learned_refusal' else 10.0,
        invalid_span=kind == 'invalid_span'))
    predicted = v2.predict_grouped_span_decoder(instance, SOURCE, 'modal_over_actions')
    assert predicted['request'] is None
    assert predicted['status'] == ('abstained' if kind == 'learned_refusal' else 'blocked')
    report = evaluation.evaluate_coordination_outputs([expected(), expected()], [expected().to_dict(), predicted['request']])
    assert report['case_count'] == 2 and report['passed_count'] == report['failed_count'] == 1
    assert report['invalid_output_count'] == 1
    assert report['measure_rates']['semantic_ir_agreement'] == 0.5
    assert report['model_calls'] == report['training_calls'] == 0 and report['proof_ready'] is False


def test_evaluation_counts_missing_extra_and_changed_operator_requests():
    reference = expected()
    changed = deepcopy(reference.to_dict())
    for member in changed['members']:
        member['modality'] = 'P'
    changed_report = evaluation.evaluate_coordination_outputs([reference], [changed])
    assert changed_report['passed_count'] == 0 and changed_report['cases'][0]['candidate_syntax_valid']
    missing = evaluation.evaluate_coordination_outputs([reference, reference], [reference.to_dict()])
    assert missing['case_count'] == 2 and missing['missing_output_count'] == 1
    extra = evaluation.evaluate_coordination_outputs([reference], [reference.to_dict(), reference.to_dict()])
    assert extra['case_count'] == 2 and extra['unexpected_output_count'] == 1
    assert extra['passed_count'] == missing['passed_count'] == 1


def test_evaluation_item_bound_rejects_before_reference_rendering(monkeypatch):
    monkeypatch.setattr(evaluation, 'decode_coordination_request', deny)
    with pytest.raises(ValueError, match='item bound'):
        evaluation.evaluate_coordination_outputs([expected()] * (evaluation.MAX_EVALUATION_ITEMS + 1), [])


def test_checkpoint_producer_content_contract_is_preserved_in_candidate():
    pins = v2.producer_pins()
    assert pins['implementation_sha256'] == 'defe782605c99e9954e8ce0c0439af00cced49342c7594379840ea7cf1fc9ce8'
    assert pins['semantic_decoder_sha256'] == '49b01d995d30e20c42576f446c419b337d5d92d89d060390d6624a511415024f'
    assert sha256(Path(v1.__file__).read_bytes()).hexdigest() == 'd03c343d6130e4cb099468dbd605e524fdb15bd21092bc4f526c35c4167c9d51'
    assert v1.CHECKPOINT_SCHEMA != v2.CHECKPOINT_SCHEMA


@pytest.mark.parametrize('module', [v1, v2], ids=['v1', 'v2'])
def test_source_prediction_and_native_render_isolate_real_helpers_and_cached_aliases(monkeypatch, module):
    import sys
    from importlib import import_module
    from ipfs_datasets_py.logic.deontic import decoder as legacy_decoder

    scope = 'modal_over_actions'
    instance = model(module)
    monkeypatch.setattr(instance, 'forward', fixed_heads(module, scope))

    # Deny imports as well as package-attribute access, even if a prior test
    # loaded an optional source grouping/interpretation module.
    for name in ('ipfs_datasets_py.logic.deontic.coordination',
                 'ipfs_datasets_py.logic.autoformal.legal_coordination'):
        parent_name, _, child_name = name.rpartition('.')
        parent = import_module(parent_name)
        monkeypatch.delattr(parent, child_name, raising=False)
        monkeypatch.setitem(sys.modules, name, None)
        with pytest.raises(ModuleNotFoundError) as error:
            import_module(name)
        assert error.value.name == name
        assert not hasattr(parent, child_name)

    guarded = [(deontic_parser, name) for name in (
        'extract_normative_elements', 'analyze_normative_sentence', 'classify_modal')]
    guarded.append((legacy_decoder, 'decode_legal_norm_ir'))
    if hasattr(deontic_parser, '_unresolved_duty_disjunction_groups'):
        guarded.append((deontic_parser, '_unresolved_duty_disjunction_groups'))
    guarded.extend((module, name) for name in (
        '_labels', 'GroupedSpanTarget', 'GroupedSpanExample', 'train_grouped_span_step'))
    if module is v2:
        guarded.append((v1, 'predict_grouped_span_decoder'))
    original_helpers = tuple(getattr(owner, name) for owner, name in guarded)

    # Seed prior from-import references so a broken identity guard cannot pass
    # merely because today's modules happen not to capture a forbidden helper.
    namespaces = (semantic, v1, v2, evaluation)
    for namespace in namespaces:
        monkeypatch.setattr(namespace, '_isolation_cached_parser',
                            deontic_parser.extract_normative_elements, raising=False)
        monkeypatch.setattr(namespace, '_isolation_cached_decoder',
                            legacy_decoder.decode_legal_norm_ir, raising=False)
    cached_aliases = [(namespace, name) for namespace in namespaces
                      for name, value in tuple(vars(namespace).items())
                      if any(value is original for original in original_helpers)]
    for owner, name in guarded + cached_aliases:
        monkeypatch.setattr(owner, name, deny)
    for namespace in namespaces:
        assert (namespace, '_isolation_cached_parser') in cached_aliases
        assert (namespace, '_isolation_cached_decoder') in cached_aliases
    # These calls demonstrate that both real owners and captured aliases fail
    # if inference or rendering attempts a parser, teacher, or fallback path.
    for owner, name in guarded + cached_aliases:
        with pytest.raises(AssertionError, match='Forbidden source parser'):
            getattr(owner, name)()

    result = module.predict_grouped_span_decoder(instance, SOURCE, scope)
    assert result['status'] == 'predicted' and result['blockers'] == []
    request = semantic.CoordinationDecodeRequest.from_dict(result['request'])
    assert request.to_dict() == expected(scope).to_dict()
    assert result['predicted_character_spans'] == [
        {'actor': [4, 9], 'action': [16, 30]}, {'actor': [4, 9], 'action': [40, 54]}]
    assert result['targets_used_at_inference'] is False
    assert result['proof_ready'] is result['source_semantics_verified'] is False
    rendered = semantic.decode_coordination_request(request)
    assert rendered['family_validation']['passed'] is True
    assert rendered['native_validation']['validator'] == 'strict_native_reparse_and_exact_AST'
    assert rendered['native_payload']['payload']['formulas'][0]['ast'] == rendered['native_ast']
    assert rendered['native_ast']['node_type'] == 'DeonticFormula'
    assert rendered['lean_body'] and rendered['context'] == 'source_withheld_semantic_ir'
    for flag in ('proof_ready', 'source_semantics_verified', 'admitted', 'formalized'):
        assert rendered[flag] is False
    report = evaluation.evaluate_coordination_outputs([expected(scope)], [result['request']])
    assert report['case_count'] == report['passed_count'] == 1
    assert report['model_calls'] == report['training_calls'] == 0
    assert report['proof_ready'] is report['source_semantics_verified'] is False
