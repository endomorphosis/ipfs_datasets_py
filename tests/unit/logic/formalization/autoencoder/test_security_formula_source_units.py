"""Complete source selection uses real frozen weights and exact byte maps."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_formula_source_units as api
from .test_security_formula_decoder import formula_checkpoint  # shared real trained fixture


SOURCE = (b'# Module context is not executed.\nimport unavailable_dependency\n\n'
          b'def first(value):\n    return value + 2\n\n'
          b'class Wrapper:\n    def second(left, right):\n'
          b'        return (left - 7) * (right + 2)\n\n'
          b'def unsupported(value):\n    for entry in value:\n        print(entry)\n')


def decode(checkpoint, source=SOURCE, **kwargs):
    return api.decode_security_source_units(source_bytes=source,
        source_sha256=hashlib.sha256(source).hexdigest(),
        source_path='example.py', checkpoint=checkpoint, **kwargs)


def test_complete_module_and_class_units_consume_real_weights(formula_checkpoint, monkeypatch):
    monkeypatch.setattr(api.decoder, 'train_security_formula_decoder',
        lambda **kwargs: pytest.fail('inference must not train'))
    result = decode(formula_checkpoint)
    assert result['counts']['observed_functions'] == 3
    assert result['counts']['learned_inference_functions'] == 2
    assert result['counts']['accepted_functions'] == 2
    assert result['counts']['accepted_contained_functions'] == 2
    assert result['counts']['accepted_context_recovered_functions'] == 0
    assert [r['qualified_name'] for r in result['units']] == ['first', 'Wrapper.second', 'unsupported']
    assert result['units'][1]['enclosing_scope'] == ['Wrapper']
    for unit in result['units']:
        body, binding = api._function_span(SOURCE,
            next(node for node in api.ast.walk(api.ast.parse(SOURCE))
                 if isinstance(node, api.ast.FunctionDef) and node.name == unit['qualified_name'].split('.')[-1]))
        api._verify_span(SOURCE, body, unit['source_binding'])
        assert binding == unit['source_binding']
        assert unit['decode']['source_sha256'] == hashlib.sha256(body).hexdigest()
    assert result['units'][-1]['decode']['status'] == 'unsupported'
    assert result['training_steps'] == result['provider_calls'] == result['download_calls'] == 0
    assert result['source_semantics_verified'] is result['whole_file_semantics_verified'] is False
    assert api.validate_security_source_units(result, source_bytes=SOURCE, checkpoint=formula_checkpoint) == result


def test_window_context_recovery_never_counts_as_standalone_success(formula_checkpoint):
    start = SOURCE.index(b'return value')
    end = start + len(b'return value + 2')
    direct = decode(formula_checkpoint, window_start_byte=start, window_end_byte=end)
    assert direct['counts']['selected_functions'] == 0
    assert direct['units'][0]['window_relation'] == 'intersects'
    recovered = decode(formula_checkpoint, window_start_byte=start, window_end_byte=end, recover_context=True)
    assert recovered['counts']['selected_functions'] == 1
    assert recovered['counts']['accepted_context_recovered_functions'] == 1
    assert recovered['counts']['accepted_contained_functions'] == 0
    assert recovered['units'][0]['context_recovered'] is True
    assert recovered['units'][0]['decode']['validation']['source_AST_equivalent'] is True
    assert all(row['decode'] is None for row in recovered['units'][1:])


@pytest.mark.parametrize('options', [{'model_enabled': False}, {'weight_ablation': 'zero_production_heads'}])
def test_model_off_and_zero_head_do_not_receive_parser_fallback(formula_checkpoint, options):
    report = decode(formula_checkpoint, **options)
    assert report['counts']['accepted_functions'] == report['counts']['learned_formula_count'] == 0
    assert all(row['decode']['candidate'] is None for row in report['units'])


@pytest.mark.parametrize('source', [b'def broken(x):\n    return (x +\n',
    b'    return value + 2\n', b'def f(x):\\n    return x+2\\n', b'Fix a command injection vulnerability.'])
def test_fragments_and_prose_are_not_repaired(formula_checkpoint, source):
    result = decode(formula_checkpoint, source)
    assert result['status'] == 'unsupported'
    assert result['counts']['learned_inference_functions'] == 0
    assert result['frontiers'] == ['complete_python_source_required; fragments are not repaired']


@pytest.mark.parametrize('change', ['mapping', 'recovered_credit', 'source', 'checkpoint'])
def test_replay_rejects_forged_provenance_or_success_credit(formula_checkpoint, change):
    report = deepcopy(decode(formula_checkpoint))
    if change == 'mapping':
        report['units'][0]['source_binding']['start_byte'] += 1
    elif change == 'recovered_credit':
        report['counts']['accepted_context_recovered_functions'] += 1
    elif change == 'source':
        report['source_sha256'] = '0' * 64
    else:
        report['checkpoint']['weights_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        api.validate_security_source_units(report, source_bytes=SOURCE, checkpoint=formula_checkpoint)


def test_bound_overflow_does_not_silently_drop_functions(formula_checkpoint):
    with pytest.raises(ValueError, match='not truncated'):
        decode(formula_checkpoint, max_functions=2)


@pytest.mark.parametrize('window', [(-1, 5), (5, 5), (False, 5), (0, len(SOURCE) + 1)])
def test_bad_byte_windows_refused(formula_checkpoint, window):
    with pytest.raises(ValueError, match='byte range'):
        decode(formula_checkpoint, window_start_byte=window[0], window_end_byte=window[1])


def test_source_digest_must_match_independently_pinned_source(formula_checkpoint):
    with pytest.raises(ValueError, match='SHA256'):
        api.decode_security_source_units(source_bytes=SOURCE, source_sha256='0' * 64,
            source_path='example.py', checkpoint=formula_checkpoint)


def test_non_python_source_not_guessed_from_function_spelling(formula_checkpoint):
    result = api.decode_security_source_units(source_bytes=b'def f(x):\n    return x+2\n',
        source_sha256=hashlib.sha256(b'def f(x):\n    return x+2\n').hexdigest(),
        source_path='example.js', checkpoint=formula_checkpoint)
    assert result['counts']['observed_functions'] == 0
    assert result['frontiers'] == ['non_python_source; choose a decoder for the declared language']


def test_indentation_removal_cannot_change_multiline_literal_contents(formula_checkpoint):
    source = b'class Wrapper:\n    def message(value):\n        return """first\n        second"""\n'
    result = decode(formula_checkpoint, source)
    assert result['counts']['observed_functions'] == 1
    assert result['counts']['learned_inference_functions'] == 0
    unit = result['units'][0]
    assert unit['normalized_AST_matches_source_function'] is False
    assert unit['decode'] is None
    assert unit['preparation_frontiers'] == ['normalization_does_not_preserve_original_function_AST']


def test_utf8_before_a_function_keeps_source_byte_maps(formula_checkpoint):
    source = '# Examples: café and λ\n'.encode() + b'def arithmetic(value):\n    return value+2\n'
    result = decode(formula_checkpoint, source)
    assert result['counts']['accepted_functions'] == 1
    unit = result['units'][0]
    assert unit['start_byte'] == source.index(b'def arithmetic')
    assert unit['normalized_AST_matches_source_function'] is True


def test_explicit_python_language_preserves_arbitrary_original_source_path(formula_checkpoint):
    raw = b'def f(value):\n    return value + 2\n'
    result = api.decode_security_source_units(source_bytes=raw, source_sha256=hashlib.sha256(raw).hexdigest(),
        source_path='embedded/snippet.txt', language='python', checkpoint=formula_checkpoint)
    assert result['source_path'] == 'embedded/snippet.txt'
    assert result['language'] == 'python'
    assert result['counts']['accepted_functions'] == 1
    assert api.validate_security_source_units(result, source_bytes=raw, checkpoint=formula_checkpoint) == result


def test_explicit_other_language_overrides_python_filename(formula_checkpoint):
    raw = b'def f(value):\n    return value + 2\n'
    result = api.decode_security_source_units(source_bytes=raw, source_sha256=hashlib.sha256(raw).hexdigest(),
        source_path='example.py', language='javascript', checkpoint=formula_checkpoint)
    assert result['counts']['observed_functions'] == 0
    assert result['frontiers'] == ['non_python_source; choose a decoder for the declared language']
