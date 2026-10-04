"""Opt-in syntax partitioning retains source and dependency selectors."""
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.coherent_spans import build_coherent_spans


def check_source(text, report):
    assert ''.join(c['text'] for c in report['chunks']) == text
    assert report['source_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    for c in report['chunks']:
        assert text[c['start_char']:c['end_char']] == c['text']
        assert text.encode()[c['start_byte']:c['end_byte']] == c['text'].encode()
        assert c['context_only'] and c['requires_context']
        assert not any(c[k] for k in ('training_eligible', 'complete_compilation_unit', 'source_semantics_verified',
            'gold_target', 'proof_authority', 'execution_authority', 'truncated'))
        for ref in c['context_selectors']:
            assert text[ref['start_char']:ref['end_char']] == ref['text']
            assert text.encode()[ref['start_byte']:ref['end_byte']] == ref['text'].encode()


def test_explicit_python_structure_preserves_raw_ids_and_context_without_embeddings():
    pytest.importorskip('tree_sitter')
    pytest.importorskip('tree_sitter_python')
    text = '# café 😀\n' + ''.join(f'def process_{i}():\n    return "λ{i}"\n\n' for i in range(10))
    raw = [{'id': 'raw:whole', 'start_char': 0, 'end_char': len(text), 'text': text}]

    def no_embedding(_):
        pytest.fail('syntax chunks must not be embedded as prose')

    old = build_coherent_spans(text, source_id='test', format='code', raw_spans=raw,
        max_chars=100, min_chars=0)
    new = build_coherent_spans(text, source_id='test', format='code', raw_spans=raw,
        max_chars=100, min_chars=0, code_structure=True, code_language='python', embedder=no_embedding)
    assert len(old['chunks']) == 1
    assert old['policy_id'] != new['policy_id']
    assert len(new['chunks']) > 1
    assert all(c['raw_span_ids'] == ['raw:whole'] for c in new['chunks'])
    assert new['diagnostics']['grouping'] == []
    assert 'code_structure' in new['diagnostics']
    check_source(text, new)


def test_malformed_python_is_retained_without_manufacturing_a_module():
    text = '    if enabled:\n        result = function(\n' * 20
    report = build_coherent_spans(text, source_id='test', format='code', code_structure=True,
        code_language='python', max_chars=64, min_chars=0)
    assert len(report['chunks']) == 1
    assert report['chunks'][0]['exceeds_max_chars']
    check_source(text, report)


def test_valid_diff_keeps_replacement_sides_and_original_hunk_context():
    context = ''.join(' context_' + str(i) + '\n' for i in range(12))
    text = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,14 +1,14 @@\n-old_λ\n+new_λ\n' + context + '-old_2\n+new_2\n'
    report = build_coherent_spans(text, source_id='diff', format='diff',
        code_structure=True, max_chars=90, min_chars=0)
    check_source(text, report)
    for token in ('-old_λ\n+new_λ', '-old_2\n+new_2'):
        assert any(token in c['text'] for c in report['chunks'])
    assert any(ref['role'] == 'diff_file_header' for c in report['chunks'] for ref in c['context_selectors'])


@pytest.mark.parametrize('kwargs', [{'code_structure': 1}, {'code_language': 'python'},
    {'code_structure': True, 'code_language': ''}, {'code_structure': True, 'code_language': 3}])
def test_invalid_opt_in_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build_coherent_spans('pass', source_id='test', format='code', **kwargs)
