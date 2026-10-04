"""Conservative partitions preserve syntax atoms, source bytes, and scope."""
import hashlib
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization import code_structure as structure


def build(text, **kwargs):
    return structure.build_code_structure(text, **kwargs)


def build_private(text, **kwargs):
    return structure._split_code_structure_in_process(text, **kwargs)


def assert_fidelity(text, report):
    cursor = byte_cursor = 0
    raw = text.encode()
    for row in report['units']:
        assert row['start'] == row['start_char'] == cursor
        assert row['start_byte'] == byte_cursor
        assert text[row['start']:row['end']].encode() == raw[row['start_byte']:row['end_byte']]
        assert row['end'] == row['end_char'] > cursor
        for reference in row['context']:
            assert text[reference['start_char']:reference['end_char']].encode() == raw[reference['start_byte']:reference['end_byte']]
        cursor, byte_cursor = row['end'], row['end_byte']
        assert row['requires_context']
        assert not row['training_eligible']
        assert not row['source_semantics_verified']
        assert not row['complete_compilation_unit']
        assert not row['proof_authority']
        assert not row['execution_authority']
    assert cursor == len(text) and byte_cursor == len(raw)
    assert report['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert report['diagnostics']['source_reconstructed_exactly']


def have_grammar(name):
    pytest.importorskip('tree_sitter')
    pytest.importorskip('tree_sitter_' + name)


@pytest.mark.parametrize('format', ['code', 'diff'])
@pytest.mark.parametrize('text', ['', ' \t\r\n', 'Café 😀\nnext line\r\n'])
def test_empty_layout_unicode_exactly_preserved(format, text):
    report = build(text, format=format, max_chars=5)
    assert_fidelity(text, report)


@pytest.mark.parametrize('language,reason', [(None, 'language_not_provided'), ('invented', 'unsupported_language')])
def test_no_language_guess_without_explicit_auto(language, reason):
    text = 'def valid():\n    return 1\n'
    report = build(text, max_chars=8, language=language)
    assert report['diagnostics']['status'] == reason
    assert len(report['units']) == 1
    assert_fidelity(text, report)


def test_small_source_is_unparsed_not_declared_valid():
    report = build('def malformed(', language='python')
    assert report['diagnostics']['status'] == 'within_budget_unparsed'
    assert not report['diagnostics']['parse_attempted']
    assert 'parser_accepts_source' not in report['diagnostics']


def test_python_large_function_splits_only_whole_statements_with_scope():
    have_grammar('python')
    text = 'def calculate():\n'+''.join(f'    value_{i} = {i}\n' for i in range(30))+'    return value_29\n'
    report = build(text, language='python', max_chars=100)
    assert_fidelity(text, report)
    assert len(report['units']) > 2
    assert all(not row['exceeds_max_chars'] for row in report['units'])
    boundaries = {row['start'] for row in report['units'][1:]}
    assert all(text[position:].startswith('    value_') or text[position:].startswith('    return ') for position in boundaries)
    for row in report['units']:
        roles = {reference['role'] for reference in row['context']}
        assert {'code_source', 'enclosing_scope', 'scope_header'} <= roles
        assert any(text[r['start_char']:r['end_char']] == 'def calculate():\n' for r in row['context'] if r['role']=='scope_header')


def test_python_strings_comments_and_multiline_expressions_remain_atomic():
    have_grammar('python')
    expression = '    value = (\n        "Café 😀"\n        + "literal ; { }"\n    )\n'
    literal = '    doc = """first line\nnot a statement\nlast line"""\n'
    comment = '    # preserve this comment with the next assignment\n'
    text = 'def sample():\n'+expression+literal+comment+'    second = 2\n    return value\n'
    report = build(text, language='python', max_chars=65)
    assert_fidelity(text, report)
    boundaries = {row['end'] for row in report['units'][:-1]}
    for atom in (expression, literal, comment):
        start = text.index(atom)
        assert not any(start < point < start+len(atom) for point in boundaries)
    comment_start = text.index(comment)
    assert not any(comment_start < point <= text.index('    second = 2') for point in boundaries)


@pytest.mark.parametrize('text', [
    'def broken(:\n    return 1\n',
    '    value = 1\n    other = 2\n',
    'def broken():\n    value = "unterminated\n',
])
def test_python_errors_and_indented_fragments_retained_without_rewriting(text):
    have_grammar('python')
    report = build(text, language='python', max_chars=8)
    assert_fidelity(text, report)
    assert len(report['units']) == 1
    assert report['diagnostics']['status'] == 'no_clean_parse'
    assert report['diagnostics']['rejected_candidates']['python'] == 'python_syntax_error'


def test_huge_single_expression_is_explicitly_unsplittable():
    have_grammar('python')
    text = 'value = "'+('x'*500)+'"\n'
    report = build(text, language='python', max_chars=50)
    assert_fidelity(text, report)
    assert len(report['units']) == 1
    assert report['units'][0]['exceeds_max_chars']
    assert report['diagnostics']['unit_reasons'] == {'unsplittable_syntax_node': 1}


@pytest.mark.parametrize('language,header,statement,footer', [
    ('c', 'int f(void) {\n', '    int x{index} = {index};\n', '    return 1;\n}\n'),
    ('cpp', 'class Box { public: void f() {\n', '    int x{index} = {index};\n', '} };\n'),
    ('java', 'class Box { void f() {\n', '    int x{index} = {index};\n', '} }\n'),
    ('javascript', 'function f() {\n', '    const x{index} = {index};\n', '}\n'),
    ('go', 'package main\nfunc f() {\n', '    x{index} := {index}\n', '}\n'),
    ('rust', 'fn f() {\n', '    let x{index} = {index};\n', '}\n'),
    ('ruby', 'def f\n', '    x{index} = {index}\n', 'end\n'),
    ('php', 'function f() {\n', '    $x{index} = {index};\n', '}\n'),
])
def test_supported_local_grammars_keep_exact_offsets(language, header, statement, footer):
    have_grammar(language)
    text = header+''.join(statement.format(index=i) for i in range(20))+footer
    report = build(text, language=language, max_chars=90)
    assert_fidelity(text, report)
    assert report['diagnostics']['status'] == 'provided_hint_clean_parse'
    assert len(report['units']) > 1
    assert report['diagnostics']['parser_versions'][language]['grammar']


def test_c_multiline_comment_and_string_punctuation_do_not_create_cuts():
    have_grammar('c')
    text = 'void f(void) {\n    const char *s = "brace } ; comma ,";\n    /* comment;\n       still comment { */\n    int y = 2;\n    int z = 3;\n}\n'
    report = build(text, language='c', max_chars=50)
    assert_fidelity(text, report)
    starts = {row['start'] for row in report['units']}
    comment_start, comment_end = text.index('/*'), text.index('*/')+2
    assert not any(comment_start < start < comment_end for start in starts)
    string_start, string_end = text.index('"'), text.rindex('"')+1
    assert not any(string_start < start < string_end for start in starts)


def test_ruby_nonlocal_heredoc_is_not_split_at_cst_sibling_boundary():
    have_grammar('ruby')
    text = 'message = <<~TEXT\n'+('  literal content not code\n'*8)+'TEXT\nputs message\n'
    report = build(text, language='ruby', max_chars=50)
    assert_fidelity(text, report)
    assert len(report['units']) == 1
    assert report['diagnostics']['rejected_candidates']['ruby'] == 'nonlocal_syntax_requires_parent'


def test_auto_clean_parsers_must_agree_boundaries(monkeypatch):
    text = 'first; second;'
    monkeypatch.setattr(structure, 'LANGUAGES', ('c', 'cpp'))
    monkeypatch.setattr(structure, '_parse', lambda raw, language: (language, {}, 1))
    def disagree(raw, root, max_chars):
        cut = 6 if root == 'c' else 7
        return [structure._unit(0, cut, 'code_context'), structure._unit(cut, len(raw), 'code_context')]
    monkeypatch.setattr(structure, '_syntax_units', disagree)
    report = build_private(text, language='auto', max_chars=5)
    assert report['diagnostics']['status'] == 'ambiguous_parse_boundaries'
    assert report['diagnostics']['candidate_languages'] == ['c', 'cpp']
    assert len(report['units']) == 1
    assert_fidelity(text, report)


def test_missing_optional_parsers_do_not_download_or_fake_boundaries(monkeypatch):
    def unavailable(*args):
        raise ImportError('not installed')
    monkeypatch.setattr(structure, '_parse', unavailable)
    report = build_private('source needing analysis', language='auto', max_chars=4)
    assert report['diagnostics']['status'] == 'no_clean_parse'
    assert set(report['diagnostics']['rejected_candidates'].values()) == {'parser_unavailable'}
    assert report['diagnostics']['consensus_scope'] == 'installed_supported_grammars_only'
    assert len(report['units']) == 1


def test_source_and_node_limits_are_explicit(monkeypatch):
    text = 'def f():\n    return 1\n'
    monkeypatch.setattr(structure, 'MAX_PARSE_BYTES', 10)
    report = build(text, language='python', max_chars=4)
    assert report['diagnostics']['status'] == 'parse_byte_limit'
    report = build(text, format='diff', max_chars=4)
    assert report['diagnostics']['status'] == 'parse_byte_limit'
    assert_fidelity(text, report)


def test_parse_node_limit_retains_original_source(monkeypatch):
    have_grammar('python')
    monkeypatch.setattr(structure, 'MAX_PARSE_NODES', 2)
    text = 'def f():\n    return 1\n'
    report = build_private(text, language='python', max_chars=4)
    assert_fidelity(text, report)
    assert report['diagnostics']['rejected_candidates']['python'] == 'parse_node_limit'
    assert len(report['units']) == 1


def test_native_timeout_is_configured_and_none_result_is_indeterminate(monkeypatch):
    called = []
    class BoundedParser:
        timeout_micros = 0
        def __init__(self, grammar):
            pass
        def parse(self, raw):
            called.append(self.timeout_micros)
            return None
    monkeypatch.setitem(sys.modules, 'tree_sitter', SimpleNamespace(Parser=BoundedParser))
    monkeypatch.setattr(structure, '_grammar', lambda language: (object(), {}))
    text = 'int function(void) { return 1; }'
    report = build_private(text, language='c', max_chars=5)
    assert called == [structure.MAX_PARSE_MICROSECONDS]
    assert report['diagnostics']['status'] == 'indeterminate_parse_budget'
    assert report['diagnostics']['indeterminate_candidates'] == {'c': 'parse_timeout'}
    assert_fidelity(text, report)
    assert len(report['units']) == 1


def test_runtime_without_native_timeout_never_calls_parser(monkeypatch):
    class UnboundedParser:
        def __init__(self, grammar):
            pass
        def parse(self, raw):
            pytest.fail('unbounded parser must not be called')
    monkeypatch.setitem(sys.modules, 'tree_sitter', SimpleNamespace(Parser=UnboundedParser))
    monkeypatch.setattr(structure, '_grammar', lambda language: (object(), {}))
    report = build_private('int function(void) { return 1; }', language='c', max_chars=5)
    assert report['diagnostics']['status'] == 'indeterminate_parse_budget'
    assert report['diagnostics']['indeterminate_candidates'] == {'c': 'parse_budget_unavailable'}
    assert len(report['units']) == 1


@pytest.mark.parametrize('reason', ['parse_timeout', 'parse_budget_unavailable', 'parse_node_limit'])
def test_auto_consensus_cannot_ignore_an_indeterminate_candidate(monkeypatch, reason):
    monkeypatch.setattr(structure, 'LANGUAGES', ('c', 'cpp'))
    def parse(raw, language):
        if language == 'cpp':
            raise ValueError(reason)
        return language, {}, 1
    monkeypatch.setattr(structure, '_parse', parse)
    monkeypatch.setattr(structure, '_syntax_units', lambda raw, root, max_chars: [
        structure._unit(0, 6, 'code_context'), structure._unit(6, len(raw), 'code_context')])
    report = build_private('first; second;', language='auto', max_chars=5)
    assert report['diagnostics']['candidate_languages'] == ['c']
    assert report['diagnostics']['indeterminate_candidates'] == {'cpp': reason}
    assert report['diagnostics']['status'] == 'indeterminate_parse_budget'
    assert len(report['units']) == 1


@pytest.mark.parametrize('exception,reason', [(ValueError('Parsing failed'), 'parse_timeout'),
    (RuntimeError('unexpected native failure'), 'native_parse_failure')])
def test_native_errors_remain_indeterminate(monkeypatch, exception, reason):
    class FailedParser:
        timeout_micros = 0
        def __init__(self, grammar):
            pass
        def parse(self, raw):
            raise exception
    monkeypatch.setitem(sys.modules, 'tree_sitter', SimpleNamespace(Parser=FailedParser))
    monkeypatch.setattr(structure, '_grammar', lambda language: (object(), {}))
    report = build_private('int function(void) { return 1; }', language='c', max_chars=5)
    assert report['diagnostics']['indeterminate_candidates'] == {'c': reason}
    assert len(report['units']) == 1


def test_real_native_timeout_contract(monkeypatch):
    have_grammar('c')
    monkeypatch.setattr(structure, 'MAX_PARSE_MICROSECONDS', 1)
    text = 'int f(void) {\n'+('int x=1;\n'*10000)+'}\n'
    report = build_private(text, language='c', max_chars=50)
    assert report['diagnostics']['indeterminate_candidates'] == {'c': 'parse_timeout'}
    assert_fidelity(text, report)


def test_actual_child_native_crash_cannot_terminate_parent(monkeypatch):
    run = structure.subprocess.run
    def crashed(command, **kwargs):
        return run([sys.executable, '-c',
            'import os,signal,resource;resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.kill(os.getpid(),signal.SIGSEGV)'], **kwargs)
    monkeypatch.setattr(structure.subprocess, 'run', crashed)
    text = 'int f(void) { return 1; }'
    report = build(text, language='auto', max_chars=5)
    assert report['diagnostics']['status'] == 'parser_worker_crash'
    assert report['diagnostics']['worker_exit_code'] == -11
    assert report['diagnostics']['incomplete_language_assessment']
    assert len(report['units']) == 1
    assert_fidelity(text, report)


def test_actual_child_timeout_is_killed_and_original_source_retained(monkeypatch):
    run = structure.subprocess.run
    def slow(command, **kwargs):
        return run([sys.executable, '-c', 'import time;time.sleep(5)'], **kwargs)
    monkeypatch.setattr(structure.subprocess, 'run', slow)
    monkeypatch.setattr(structure, 'MAX_WORKER_SECONDS', .05)
    text = 'int f(void) { return 1; }'
    report = build(text, language='auto', max_chars=5)
    assert report['diagnostics']['status'] == 'parser_worker_timeout'
    assert report['diagnostics']['incomplete_language_assessment']
    assert len(report['units']) == 1
    assert_fidelity(text, report)


def test_unparseable_policy_cases_do_not_start_worker(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('worker unnecessary for this source')
    monkeypatch.setattr(structure.subprocess, 'run', forbidden)
    for text, language, maximum in [('small', 'auto', 100), ('source text', None, 1), ('source text', 'unknown', 1)]:
        assert build(text, language=language, max_chars=maximum)['diagnostics']['worker_status'] == 'not_required'


def diff_text(count=6):
    return ('diff --git a/example.py b/example.py\n--- a/example.py\n+++ b/example.py\n'
        +f'@@ -1,{count*2} +1,{count*2} @@\n'
        +''.join(f'-old_{i} = "é"\n+new_{i} = "😀"\n context_{i}\n' for i in range(count)))


def test_diff_uses_whole_replacement_runs_and_preserves_full_context():
    text = diff_text()
    report = build(text, format='diff', max_chars=75)
    assert_fidelity(text, report)
    assert report['diagnostics']['hunks_validated'] == 1
    assert report['diagnostics']['boundary_basis'] == 'unified_diff_runs_not_code_syntax'
    assert len(report['units']) > 2
    assert any(row['kind'] == 'diff_edit_group' for row in report['units'])
    starts = {row['start'] for row in report['units']}
    assert not any(text[start:].startswith('+new_') for start in starts)
    for row in report['units'][1:]:
        roles = {context['role'] for context in row['context']}
        assert roles == {'diff_hunk', 'diff_file_header'}
        hunk = next(c for c in row['context'] if c['role'] == 'diff_hunk')
        assert text[hunk['start_char']:hunk['end_char']] == text[text.index('@@'):]
        assert not row['missing_file_header_context']


def test_single_giant_diff_edit_is_retained_not_line_split():
    text = '--- a/f\n+++ b/f\n@@ -1,30 +1,30 @@\n'+('-old value\n'*30)+('+new value\n'*30)
    report = build(text, format='diff', max_chars=40)
    assert_fidelity(text, report)
    assert len(report['units']) == 2
    assert report['units'][1]['kind'] == 'diff_hunk'
    assert report['units'][1]['exceeds_max_chars']
    assert report['units'][1]['reason'] == 'whole_hunk'


def test_diff_header_like_payload_does_not_replace_file_scope():
    text = 'diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n--- spoof\n+++ spoof\n@@ -3 +3 @@\n-old\n+new\n'
    report = build(text, format='diff', max_chars=25)
    assert_fidelity(text, report)
    for row in report['units'][1:]:
        context = next(c for c in row['context'] if c['role'] == 'diff_file_header')
        assert text[context['start_char']:context['end_char']] == 'diff --git a/a b/a\n--- a/a\n+++ b/a\n'


@pytest.mark.parametrize('body', [
    '@@ -1,2 +1,2 @@\n-old\n+new\n',
    '@@ -1 +1 @@\n-old\n+new\n+excess\n',
    '@@ malformed\n-old\n+new\n',
    '@@ -1 +1 @@\n\\ No newline at end of file\n-old\n+new\n',
    '@@ -1 +1 @@\n-old\n\\ No newline at end of file\n\\ No newline at end of file\n+new\n',
    '@@@ -1,2 -1,2 +1,2 @@@\n-old\n+new\n',
])
def test_malformed_diffs_retained_whole_with_explicit_reason(body):
    text = '--- a/a\n+++ b/a\n'+body
    report = build(text, format='diff', max_chars=15)
    assert_fidelity(text, report)
    assert len(report['units']) == 1
    assert report['diagnostics']['status'] == 'malformed_diff_retained'


def test_crlf_diff_no_newline_markers_and_missing_header():
    text = '@@ -1 +1 @@\r\n-old\r\n\\ No newline at end of file\r\n+new\r\n\\ No newline at end of file\r\n'
    report = build(text, format='diff', max_chars=20)
    assert_fidelity(text, report)
    assert report['diagnostics']['hunks_validated'] == 1
    assert report['units'][0]['missing_file_header_context']


def test_multiple_diff_files_receive_separate_header_selectors():
    first = '--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n'
    second = '--- a/b\n+++ b/b\n@@ -1 +1 @@\n-old\n+new\n'
    report = build(first+second, format='diff', max_chars=25)
    assert_fidelity(first+second, report)
    hunks = [row for row in report['units'] if row['kind'] == 'diff_hunk']
    assert len(hunks) == 2
    assert hunks[0]['context'][1]['start_char'] == 0
    assert hunks[1]['context'][1]['start_char'] == len(first)


@pytest.mark.parametrize('kwargs', [{'max_chars': 0}, {'max_chars': True}, {'format': 'prose'}, {'language': 8}])
def test_configuration_errors(kwargs):
    with pytest.raises(ValueError):
        build('source text', **kwargs)
