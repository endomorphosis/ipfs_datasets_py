"""Typed routing preserves exact document ranges and contextual coverage."""
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
from .test_security_formula_decoder import formula_checkpoint


FUNCTION = 'def example(value):\n    return (value + 2) * (value - 7)\n'


def test_python_document_reaches_actual_checkpoint_and_equations(formula_checkpoint):
    text = 'import unavailable_dependency\n\n' + FUNCTION
    result = prepare_source_document(text, source_path='example.py', source_format='code',
        language='python', security_checkpoint=formula_checkpoint)
    assert result['status'] == 'partial_candidates'
    assert result['counts']['security_program_candidates'] == 1
    assert result['counts']['security_equation_candidates'] == 1
    assert result['counts']['equation_candidates_using_recovered_context'] == 0
    candidate = result['candidates'][0]
    assert text.encode()[candidate['start_byte']:candidate['end_byte']] == FUNCTION.rstrip('\n').encode()
    unit = result['security_regions'][0]['report']['units'][0]
    assert unit['decode']['predicted_productions']
    assert result['whole_document_formalized'] is result['source_semantics_verified'] is False


def test_explicit_python_document_language_keeps_non_python_filename(formula_checkpoint):
    result = prepare_source_document(FUNCTION, source_path='snippets/example.txt', source_format='code',
        language='python', security_checkpoint=formula_checkpoint)
    assert result['counts']['security_equation_candidates'] == 1
    region = result['security_regions'][0]
    assert region['report']['source_path'] == 'snippets/example.txt'
    assert region['report']['language'] == 'python'


def test_partial_window_needs_explicit_context_and_separate_success_credit(formula_checkpoint):
    start = FUNCTION.index('return')
    args = dict(source_path='example.py', source_format='code', language='python',
        security_checkpoint=formula_checkpoint, start_char=start, end_char=len(FUNCTION))
    direct = prepare_source_document(FUNCTION, **args)
    assert direct['counts']['security_equation_candidates'] == 0
    assert not direct['candidates']
    recovered = prepare_source_document(FUNCTION, recover_context=True, **args)
    assert recovered['counts']['security_equation_candidates'] == 1
    assert recovered['counts']['equation_candidates_using_recovered_context'] == 1
    assert recovered['candidates'][0]['context_recovered'] is True
    assert recovered['whole_source_context_supplied'] is True
    assert recovered['selection']['start_byte'] > recovered['candidates'][0]['start_byte']


@pytest.mark.parametrize('fence', ['```python', '~~~py', '```python3'])
def test_markdown_python_fences_keep_outer_utf8_byte_mapping(formula_checkpoint, fence):
    header = '# Examples: café and λ\n\n'
    text = header + fence + '\n' + FUNCTION + fence[:3] + '\n\nOther documentation.\n'
    result = prepare_source_document(text, source_path='guide.md', source_format='markdown',
        security_checkpoint=formula_checkpoint)
    assert result['counts']['security_equation_candidates'] == 1
    assert result['counts']['intent_candidates'] == 0
    region = result['security_regions'][0]
    left = text.index('def example')
    assert region['start_char'] == left
    assert region['start_byte'] == len(text[:left].encode())
    assert text.encode()[region['start_byte']:region['end_byte']] == FUNCTION.encode()
    assert region['source_sha256'] == hashlib.sha256(FUNCTION.encode()).hexdigest()
    candidate = result['candidates'][0]
    assert text.encode()[candidate['start_byte']:candidate['end_byte']] == FUNCTION.rstrip('\n').encode()
    assert all(row['accepted'] is False for row in result['intent']['units'] if row['block_kind'] == 'fenced_code')


def test_selection_inside_fence_cannot_route_code_into_intent(formula_checkpoint):
    text = '# Example\n\n```python\n' + FUNCTION + '```\n'
    start = text.index('return')
    end = start + len('return (value + 2) * (value - 7)')
    args = dict(source_path='guide.md', source_format='markdown',
        security_checkpoint=formula_checkpoint, start_char=start, end_char=end)
    direct = prepare_source_document(text, **args)
    assert not direct['candidates']
    recovered = prepare_source_document(text, recover_context=True, **args)
    assert recovered['counts']['intent_candidates'] == 0
    assert recovered['counts']['equation_candidates_using_recovered_context'] == 1
    assert recovered['candidates'][0]['start_byte'] == len(text[:text.index('def example')].encode())


@pytest.mark.parametrize('opening,closing', [('```javascript', '```'), ('```', '```'),
    ('```python', ''), ('```python extra', '```')])
def test_undeclared_other_language_and_unclosed_fences_are_not_python(formula_checkpoint, opening, closing):
    text = opening + '\n' + FUNCTION + closing + '\n'
    result = prepare_source_document(text, source_path='guide.md', source_format='markdown',
        security_checkpoint=formula_checkpoint)
    assert not result['security_regions']
    assert result['counts']['security_equation_candidates'] == 0
    assert result['routing_frontiers']


@pytest.mark.parametrize('source_format,language', [('security_prose', None), ('diff', None),
    ('code', 'javascript'), ('code', None)])
def test_unsupported_domains_are_not_guessed_from_text(formula_checkpoint, source_format, language):
    result = prepare_source_document(FUNCTION, source_path='example.py', source_format=source_format,
        language=language, security_checkpoint=formula_checkpoint)
    assert result['status'] == 'unsupported'
    assert not result['security_regions'] and not result['candidates']
    assert result['routing_frontiers']


def test_checkpoint_absence_remains_explicit(formula_checkpoint):
    result = prepare_source_document(FUNCTION, source_path='example.py', source_format='code', language='python')
    assert result['security_regions'][0]['frontier'] == 'security_checkpoint_not_selected'
    assert result['counts']['security_equation_candidates'] == 0


@pytest.mark.parametrize('selection', [(-1, 5), (0, 0), (False, 5), (0, 10000)])
def test_selection_must_be_exact_valid_character_range(selection):
    with pytest.raises(ValueError, match='character selection'):
        prepare_source_document(FUNCTION, source_path='example.py', source_format='code', language='python',
            start_char=selection[0], end_char=selection[1])


@pytest.mark.parametrize('separator', ['\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'])
def test_nonphysical_line_separator_cannot_create_fence_scope(separator):
    # str.splitlines recognizes these characters; Python and Markdown physical
    # line handling must not acquire a fabricated closing fence through them.
    source = '```text\ncomment' + separator + '```\n```python\n' + FUNCTION + '```\n'
    result = prepare_source_document(source, source_path='scope.md', source_format='markdown',
                                    security_checkpoint={'must_not': 'be_loaded'})
    assert result['status'] == 'unsupported'
    assert result['routing_frontiers'][0]['reason'] == 'nonphysical_markdown_line_separator_requires_parser_support'
    assert not result['security_regions'] and not result['candidates']
    assert result['counts']['security_decoder_calls'] == 0
