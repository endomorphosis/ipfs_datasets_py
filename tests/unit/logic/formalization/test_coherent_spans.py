"""Source fidelity, structural scope and non-authoritative grouping contracts."""
import copy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.coherent_spans import build_coherent_spans


def build(text, **kwargs):
    return build_coherent_spans(text, source_id='authored:source', **kwargs)


def assert_fidelity(text, report):
    cursor = byte_cursor = 0
    for chunk in report['chunks']:
        assert chunk['start_char'] == cursor
        assert chunk['start_byte'] == byte_cursor
        assert chunk['text'] == text[cursor:chunk['end_char']]
        assert chunk['text'].encode() == text.encode()[byte_cursor:chunk['end_byte']]
        cursor, byte_cursor = chunk['end_char'], chunk['end_byte']
        assert not chunk['training_eligible']
        assert not chunk['gold_target']
        assert not chunk['proof_authority']
        assert not chunk['execution_authority']
        assert not chunk['source_semantics_verified']
        assert not chunk['complete_compilation_unit']
        assert not chunk['truncated']
        for context in chunk['context_selectors']:
            assert context['text'] == text[context['start_char']:context['end_char']]
            assert context['text'].encode() == text.encode()[context['start_byte']:context['end_byte']]
    assert cursor == len(text)
    assert byte_cursor == len(text.encode())
    assert ''.join(chunk['text'] for chunk in report['chunks']) == text
    assert report['source_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert report['diagnostics']['source_reconstructed_exactly']


@pytest.mark.parametrize('format', ['prose', 'markdown', 'code', 'diff'])
@pytest.mark.parametrize('text', ['', ' \t\n\r\n', '  Café 😀.\r\n\r\nRead λ.  \n'])
def test_unicode_empty_and_layout_fidelity(format, text):
    report = build(text, format=format, max_chars=14, min_chars=0)
    assert_fidelity(text, report)
    if text.strip():
        assert all(chunk['text'].strip() for chunk in report['chunks'])
    elif text:
        assert len(report['chunks']) == 1
        assert report['chunks'][0]['context_only']


@pytest.mark.parametrize('text,first', [
    ('Compare full vs. masked inputs. Continue.', 'Compare full vs. masked inputs.'),
    ('Clear names (cf. issue 2170). Retry.', 'Clear names (cf. issue 2170).'),
    ('Use an adapter, e.g. a cache wrapper. Continue.', 'Use an adapter, e.g. a cache wrapper.'),
    ('Use version 1.2.3 at threshold 0.75. Continue.', 'Use version 1.2.3 at threshold 0.75.'),
    ('Read https://example.invalid/a.b?x=1.2. Continue.', 'Read https://example.invalid/a.b?x=1.2.'),
])
def test_sentence_boundaries_do_not_fragment_abbreviations_urls_or_decimals(text, first):
    report = build(text, max_chars=len(first) + 1, min_chars=0)
    assert_fidelity(text, report)
    assert report['chunks'][0]['text'].strip() == first
    assert len(report['chunks']) == 2
    receipt = report['diagnostics']['grouping'][0]['report']['sentence_segmentation']
    assert receipt['backend'] in {'pysbd-character-spans', 'source-punctuation-fallback/v1'}


def test_bold_labels_numbered_emphasis_and_heading_reset():
    text = '# Setup\n\n**HSTS Header:**\nRead the setting.\n\n**1. Save the changes**\nVerify the result.\n\n# Other\nArchive logs.\n'
    report = build(text, format='markdown')
    assert_fidelity(text, report)
    labels = [row for row in report['chunks'] if row['kind'] == 'bold_label']
    assert len(labels) == 2
    assert all(row['context_only'] for row in labels)
    assert '**1. Save the changes**' in labels[1]['text']
    read = next(row for row in report['chunks'] if row['text'].startswith('Read'))
    assert any(context['text'].strip() == '**HSTS Header:**' for context in read['context_selectors'])
    verify = next(row for row in report['chunks'] if row['text'].startswith('Verify'))
    assert [context['text'].strip() for context in verify['context_selectors'] if context['role'] == 'label'] == ['**1. Save the changes**']
    archive = next(row for row in report['chunks'] if row['text'].startswith('Archive'))
    assert [context['text'].strip() for context in archive['context_selectors']] == ['# Other']


def test_nested_conditional_list_context_does_not_leak_to_peer():
    text = '- If the service is available:\n  - Read the cache.\n  - Validate the index.\n- Archive the report.\n'
    report = build(text, format='markdown')
    assert_fidelity(text, report)
    for word in ['Read', 'Validate']:
        row = next(row for row in report['chunks'] if word in row['text'])
        assert any(context['role'] == 'parent_list' and 'If the service' in context['text'] for context in row['context_selectors'])
    archive = next(row for row in report['chunks'] if 'Archive' in row['text'])
    assert archive['context_selectors'] == []


def test_separate_bold_phrases_are_prose_not_one_label():
    report = build('**Use TLS** and **disable HTTP**\n', format='markdown')
    assert report['chunks'][0]['kind'] == 'paragraph'
    assert not report['chunks'][0]['context_only']


def test_nested_list_condition_preserves_outer_paragraph_scope():
    text = 'When the service is available:\n\n- If the cache is enabled:\n  - Read the cache.\n- Archive the report.\n'
    report = build(text, format='markdown')
    for word in ['Read', 'Archive']:
        row = next(row for row in report['chunks'] if word in row['text'])
        assert [context['text'].strip() for context in row['context_selectors'] if context['role'] == 'lead_in'] == ['When the service is available:']
        parents = [context['text'].strip() for context in row['context_selectors'] if context['role'] == 'parent_list']
        assert parents == (['If the cache is enabled:'] if word == 'Read' else [])


def test_list_label_continuation_retains_its_original_block_only():
    text = '- **Step:**\n  Read config.\n- Archive logs.\n'
    report = build(text, format='markdown')
    assert_fidelity(text, report)
    read = next(row for row in report['chunks'] if 'Read config' in row['text'])
    assert any(context['role'] == 'structural_unit' and context['text'] == '- **Step:**\n  Read config.\n'
               for context in read['context_selectors'])
    archive = next(row for row in report['chunks'] if 'Archive logs' in row['text'])
    assert archive['context_selectors'] == []


def test_paragraph_lead_in_applies_to_list_then_expires():
    text = 'For the active project:\n\n- Read configuration.\n- Save the result.\n\nArchive logs.\n\nRotate logs.\n'
    report = build(text, format='markdown')
    for row in report['chunks']:
        if row['kind'] == 'list_item':
            assert any(context['role'] == 'lead_in' for context in row['context_selectors'])
        if row['text'].startswith(('Archive', 'Rotate')):
            assert not any(context['role'] == 'lead_in' for context in row['context_selectors'])


def test_split_prose_retains_structural_unit_without_semantic_resolution():
    text = 'For each service, validate its configuration. Then restart it.'
    report = build(text, max_chars=45, min_chars=0)
    assert len(report['chunks']) == 2
    for row in report['chunks']:
        assert row['requires_context']
        assert len(row['context_selectors']) == 1
        assert row['context_selectors'][0]['role'] == 'structural_unit'
        assert row['context_selectors'][0]['text'] == text


def test_code_oversize_is_atomic_and_never_embedded():
    text = 'def process():\n' + '    return "λ"\n' * 500
    def fail(_):
        pytest.fail('code must not reach embedder')
    report = build(text, format='code', embedder=fail, max_chars=32, min_chars=0)
    assert_fidelity(text, report)
    assert len(report['chunks']) == 1
    assert report['chunks'][0]['exceeds_max_chars']
    assert report['chunks'][0]['requires_context']
    assert report['diagnostics']['grouping'] == []


def test_diff_hunks_link_real_headers_not_header_like_payload():
    text = 'diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n--- spoof\n+++ spoof\n@@ -3 +3 @@\n-old\n+new\n'
    report = build(text, format='diff')
    assert_fidelity(text, report)
    hunks = [row for row in report['chunks'] if row['kind'] == 'diff_hunk']
    assert len(hunks) == 2
    for row in hunks:
        assert row['context_selectors'][0]['text'] == 'diff --git a/a b/a\n--- a/a\n+++ b/a\n'
        assert not row['missing_file_header_context']


def test_diff_files_and_missing_header_are_explicit():
    text = '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-x\n+y\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-z\n+w\n'
    report = build(text, format='diff')
    assert_fidelity(text, report)
    hunks = [row for row in report['chunks'] if row['kind'] == 'diff_hunk']
    assert hunks[0]['context_selectors'][0]['text'] == '--- a/a\n+++ b/a\n'
    assert hunks[1]['context_selectors'][0]['text'] == '--- a/b\n+++ b/b\n'
    orphan = build('@@ -1 +1 @@\n-x\n+y\n', format='diff')['chunks'][0]
    assert orphan['missing_file_header_context']
    assert orphan['requires_context']


def test_raw_spans_are_immutable_overlap_provenance():
    text = 'Café. Retry.'
    raw = [{'id': 'raw:whole', 'source_id': 'authored:source', 'start_char': 0, 'end_char': len(text),
            'start_byte': 0, 'end_byte': len(text.encode()), 'text': text},
           {'id': 'raw:right', 'source_field_id': 'authored:source', 'start_char': 6, 'end_char': len(text)}]
    before = copy.deepcopy(raw)
    report = build(text, raw_spans=raw, max_chars=6, min_chars=0)
    assert_fidelity(text, report)
    assert raw == before
    assert report['chunks'][0]['raw_span_ids'] == ['raw:whole']
    assert report['chunks'][1]['raw_span_ids'] == ['raw:whole', 'raw:right']
    assert report == build(text, raw_spans=raw, max_chars=6, min_chars=0)


@pytest.mark.parametrize('changes', [
    {'source_id': 'wrong'}, {'source_field_id': 'wrong'}, {'text': 'wrong'},
    {'source_sha256': 'wrong'}, {'raw_body_sha256': 'wrong'}, {'end_byte': 3},
    {'start_char': True}, {'end_char': 500}, {'id': ''},
])
def test_raw_binding_mismatches_rejected(changes):
    row = {'id': 'raw', 'start_char': 0, 'end_char': 4, 'text': 'Café', **changes}
    with pytest.raises(ValueError, match='binding'):
        build('Café', raw_spans=[row])


def test_duplicate_raw_ids_rejected():
    row = {'id': 'same', 'start_char': 0, 'end_char': 4}
    with pytest.raises(ValueError, match='binding'):
        build('Café', raw_spans=[row, row])


def test_embedding_calls_respect_markdown_boundaries_and_single_atoms():
    calls = []
    def embed(inputs):
        calls.append(inputs)
        return [[1., 0.] for _ in inputs]
    text = '# Scope\nRead data. Save results.\n\n- Check state. Repair failures.\n- Stop now.\n\n```python\nprint("one. two.")\n```\n\n| a | b |\n| - | - |\n'
    report = build(text, format='markdown', embedder=embed, embedding_eligible=lambda _: True, min_chars=0)
    assert_fidelity(text, report)
    assert len(calls) == 2
    assert len(calls[0]) == len(calls[1]) == 2
    assert all('print(' not in part and 'Stop now.' not in part and '# Scope' not in part for call in calls for part in call)
    for item in report['diagnostics']['grouping']:
        receipt = item['report']
        if receipt['embeddings_used']:
            assert receipt['config']['token_budget_checked']
        else:
            assert receipt['embedding_status'] == 'not_required'


def test_prose_commit_message_keeps_wrapped_sentence_and_skips_marked_code():
    text = ('Avoid losing empty tokens via its split\ninvocation. Preserve the suffix.\n\n'
            '    token = prefix.\n    token += suffix.\n\n'
            '```abnf\nfield = token "." token\n```\n\n'
            'Read the update. Save the result.\n')
    calls = []
    def embed(parts):
        calls.append(parts)
        return [[1., 0.] for _ in parts]
    report = build(text, format='prose', embedder=embed, min_chars=0)
    assert_fidelity(text, report)
    assert report['format'] == 'prose'
    assert all(row['format'] == 'prose' for row in report['chunks'])
    assert len(calls) == 2
    assert len(calls[0]) == len(calls[1]) == 2
    assert calls[0][0] == 'Avoid losing empty tokens via its split\ninvocation. '
    assert all('token =' not in part and 'field =' not in part for call in calls for part in call)
    assert {'indented_code', 'fenced_code'} <= {row['kind'] for row in report['chunks']}
    assert all(row['context_only'] for row in report['chunks'] if row['kind'].endswith('code'))


def test_prose_paragraphs_are_hard_barriers_even_with_identical_vectors():
    text = 'Read logs. Save logs.\n\nArchive logs. Check logs.\n'
    calls = []
    def embed(parts):
        calls.append(parts)
        return [[1., 0.] for _ in parts]
    structural = build(text, format='prose', min_chars=0)
    vector = build(text, format='prose', embedder=embed, min_chars=0)
    assert_fidelity(text, structural)
    assert_fidelity(text, vector)
    assert len(calls) == 2
    assert len(structural['chunks']) == len(vector['chunks']) == 2
    assert vector['chunks'][0]['text'] == 'Read logs. Save logs.\n\n'
    assert vector['chunks'][1]['text'] == 'Archive logs. Check logs.\n'


def test_plain_prose_paragraph_retains_original_sentence_behavior():
    text = 'Read logs. Save logs.'
    report = build(text, format='prose')
    assert len(report['chunks']) == 1
    assert report['chunks'][0]['text'] == text
    assert report['chunks'][0]['kind'] == 'paragraph'
    assert not report['chunks'][0]['context_only']


def test_adjacent_vectors_change_only_within_block_boundaries():
    text = 'Read logs. Save logs. Archive logs.'
    high = build(text, embedder=lambda parts: [[1., 0.] for _ in parts], min_chars=0)
    low = build(text, embedder=lambda parts: [[1., 0.], [0., 1.], [1., 0.]], min_chars=0)
    assert len(high['chunks']) == 1
    assert len(low['chunks']) == 3
    assert_fidelity(text, high)
    assert_fidelity(text, low)


def test_token_ineligible_atoms_never_embedded_and_error_fallback_explicit():
    seen = []
    text = 'Read logs. Save logs.'
    report = build(text, embedder=lambda parts: seen.extend(parts) or [[1., 0.] for _ in parts],
                   embedding_eligible=lambda part: 'Save' not in part, min_chars=0)
    assert all('Save' not in part for part in seen)
    receipt = report['diagnostics']['grouping'][0]['report']
    assert receipt['opaque_atoms'] == [{'atom_index': 1, 'reason': 'atom_exceeds_embedding_token_budget'}]
    def broken(_):
        raise RuntimeError('local model unavailable')
    fallback = build(text, embedder=broken, min_chars=0)
    receipt = fallback['diagnostics']['grouping'][0]['report']
    assert receipt['embedding_status'] == 'structural_fallback'
    assert receipt['normalized_vectors'] == []
    assert not receipt['embeddings_used']
    assert_fidelity(text, fallback)


@pytest.mark.parametrize('format', ['markdown', 'prose'])
def test_markdown_bound_is_explicit_not_truncation(format):
    with pytest.raises(ValueError, match='bound'):
        build('x' * (1024 * 1024 + 1), format=format)


@pytest.mark.parametrize('kwargs', [
    {'max_chars': 0}, {'min_chars': -1}, {'min_chars': 10, 'max_chars': 2},
    {'embedder': []}, {'embedding_eligible': 3}, {'format': 'html'},
])
def test_invalid_configuration_fails(kwargs):
    with pytest.raises(ValueError, match='configuration'):
        build('Read.', **kwargs)
