"""Conservative, lossless syntax and unified-diff partitions.

No source rewriting, dedenting, guessed language assertion, or line/character
cuts are used. Optional Tree-sitter grammars must already be installed. A clean
parse describes parser acceptance, not compilation or semantic correctness.
Install ``tree-sitter`` and the desired ``tree-sitter-<language>`` wheels in
the caller's environment; this module never installs or downloads dependencies.
"""
from __future__ import annotations

import ast
from bisect import bisect_left
from collections import Counter
from functools import lru_cache
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys

SCHEMA = 'source-code-structure/v1'
MAX_PARSE_BYTES = 4 * 1024 * 1024
MAX_PARSE_NODES = 200000
MAX_PARSE_DEPTH = 64
MAX_PARSE_MICROSECONDS = 100000
MAX_WORKER_SECONDS = 3.0
_INDETERMINATE = frozenset({'parse_timeout', 'parse_budget_unavailable', 'parse_node_limit',
    'native_parse_failure', 'RecursionError', 'RuntimeError', 'TypeError', 'AttributeError', 'ValueError'})
LANGUAGES = ('c', 'cpp', 'java', 'javascript', 'python', 'go', 'rust', 'ruby', 'php')
_ALIASES = {'c++': 'cpp', 'js': 'javascript', 'py': 'python', 'rb': 'ruby', 'golang': 'go'}
_CONTAINERS = frozenset({'translation_unit', 'program', 'module', 'source_file',
    'compound_statement', 'statement_block', 'block', 'class_body',
    'field_declaration_list', 'declaration_list', 'body_statement', 'statement_list'})
_COMMENTS = frozenset({'comment', 'line_comment', 'block_comment'})


def _context(role, start, end):
    return {'role': role, 'start_byte': start, 'end_byte': end}


def _unit(start, end, kind, context=(), reason='structural_boundary', syntax_type=None):
    return {'start_byte': start, 'end_byte': end, 'kind': kind, 'context': list(context),
        'reason': reason, 'syntax_type': syntax_type}


def _finish(text, raw, units, diagnostics, max_chars):
    points = {0, len(raw)}
    for row in units:
        points.update((row['start_byte'], row['end_byte']))
        for context in row['context']:
            points.update((context['start_byte'], context['end_byte']))
    offsets, cursor, character = {}, 0, 0
    for point in sorted(points):
        character += len(raw[cursor:point].decode('utf-8'))
        offsets[point] = character; cursor = point
    cursor = 0
    for row in units:
        a, b = row['start_byte'], row['end_byte']
        assert a == cursor and a < b <= len(raw)
        row.update(start=offsets[a], end=offsets[b], start_char=offsets[a], end_char=offsets[b],
            exceeds_max_chars=offsets[b]-offsets[a] > max_chars, requires_context=True,
            complete_compilation_unit=False, source_semantics_verified=False,
            training_eligible=False, proof_authority=False, execution_authority=False)
        for context in row['context']:
            context.update(start_char=offsets[context['start_byte']], end_char=offsets[context['end_byte']])
        cursor = b
    assert cursor == len(raw)
    diagnostics.update(source_characters=len(text), source_utf8_bytes=len(raw),
        units=len(units), oversized_units=sum(row['exceeds_max_chars'] for row in units),
        unit_reasons=dict(Counter(row['reason'] for row in units)),
        source_reconstructed_exactly=True, syntax_is_not_semantic_proof=True,
        max_chars=max_chars, max_parse_bytes=MAX_PARSE_BYTES, max_parse_nodes=MAX_PARSE_NODES,
        native_parse_timeout_micros=MAX_PARSE_MICROSECONDS)
    return {'schema': SCHEMA, 'source_sha256': hashlib.sha256(raw).hexdigest(),
        'units': units, 'diagnostics': diagnostics}


@lru_cache(maxsize=len(LANGUAGES))
def _grammar(language):
    """Load only local grammar wheels; never download parser assets."""
    from tree_sitter import Language
    module = importlib.import_module('tree_sitter_' + language)
    factory = getattr(module, 'language_php_only') if language == 'php' else module.language
    return Language(factory()), {
        'tree_sitter': importlib.metadata.version('tree-sitter'),
        'grammar': importlib.metadata.version('tree-sitter-' + language),
    }


def _parse(raw, language):
    from tree_sitter import Parser
    grammar, versions = _grammar(language)
    parser = Parser(grammar)
    # Do not run an unbounded native parser when the installed binding drops
    # timeout support. Version 0.25 exposes this per-parser time budget.
    try:
        if not hasattr(parser, 'timeout_micros'):
            raise ValueError('parse_budget_unavailable')
        parser.timeout_micros = MAX_PARSE_MICROSECONDS
        if parser.timeout_micros != MAX_PARSE_MICROSECONDS:
            raise ValueError('parse_budget_unavailable')
    except (AttributeError, TypeError, ValueError):
        raise ValueError('parse_budget_unavailable') from None
    if language == 'python':
        # Python's CST accepts some indented fragments rejected as full modules.
        # Keep such original snippets opaque rather than dedenting/wrapping them.
        ast.parse(raw.decode('utf-8'))
    try:
        tree = parser.parse(raw)
    except Exception as exc:
        # 0.25.2 raises this on its configured timeout instead of returning None.
        reason = 'parse_timeout' if isinstance(exc, ValueError) and str(exc) == 'Parsing failed' else 'native_parse_failure'
        raise ValueError(reason) from None
    if tree is None:
        raise ValueError('parse_timeout')
    root = tree.root_node
    if root.has_error:
        raise ValueError('syntax_errors')
    stack, count = [root], 0
    while stack:
        node = stack.pop(); count += 1
        if count > MAX_PARSE_NODES:
            raise ValueError('parse_node_limit')
        if node.is_missing or node.is_error:
            raise ValueError('syntax_errors')
        # Some grammars expose a heredoc opener and delayed body as separate
        # sibling nodes. Those are one lexical construct, not safe cut points.
        if node.type in {'heredoc_begin', 'heredoc_body'}:
            raise ValueError('nonlocal_syntax_requires_parent')
        stack.extend(node.named_children)
    return root, versions, count


def _syntax_units(raw, root, max_chars):
    line_starts = [0] + [match.end() for match in re.finditer(b'\n', raw)]

    @lru_cache(maxsize=None)
    def length(start, end):
        return len(raw[start:end].decode('utf-8'))

    def beginning(node):
        start = line_starts[node.start_point.row]
        return start if not raw[start:node.start_byte].strip() else node.start_byte

    def children(node):
        result, pending, previous = [], None, None
        for child in node.named_children:
            if child.type in _COMMENTS:
                if previous is None or child.start_point.row > previous.end_point.row:
                    pending = beginning(child) if pending is None else pending
                continue
            result.append((child, pending if pending is not None else beginning(child)))
            pending, previous = None, child
        return result

    def visit(node, start, end, context, depth=0):
        if length(start, end) <= max_chars:
            return [_unit(start, end, 'code_context', context, syntax_type=node.type)]
        if depth >= MAX_PARSE_DEPTH:
            return [_unit(start, end, 'code_context', context, 'parse_depth_limit', node.type)]
        container = node
        if node.type not in _CONTAINERS:
            bodies = [child for child in node.named_children if child.type in _CONTAINERS]
            if len(bodies) != 1:
                return [_unit(start, end, 'code_context', context, 'unsplittable_syntax_node', node.type)]
            container = bodies[0]
        items = children(container)
        # Go has one statement_list inside a block. Unwrap structural containers
        # only; expression/string/argument children never become cut candidates.
        if len(items) == 1 and items[0][0].type in _CONTAINERS:
            items = children(items[0][0])
        if not items:
            return [_unit(start, end, 'code_context', context, 'unsplittable_syntax_node', node.type)]
        scoped = list(context)
        if node is not root:
            scope = _context('enclosing_scope', node.start_byte, node.end_byte)
            if scope not in scoped:
                scoped.append(scope)
            header_end = max(node.start_byte, items[0][1])
            if header_end > node.start_byte:
                scoped.append(_context('scope_header', node.start_byte, header_end))
        starts = [start] + [item[1] for item in items[1:]]
        ends = starts[1:] + [end]
        if any(a >= b for a, b in zip(starts, ends)):
            return [_unit(start, end, 'code_context', context, 'nonseparable_syntax_children', node.type)]
        result = []
        for (child, _), a, b in zip(items, starts, ends):
            parts = visit(child, a, b, scoped, depth+1)
            for part in parts:
                if (result and result[-1]['context'] == part['context']
                        and length(result[-1]['start_byte'], part['end_byte']) <= max_chars):
                    result[-1]['end_byte'] = part['end_byte']
                    result[-1]['syntax_type'] = 'adjacent_syntax_nodes'
                else:
                    result.append(part)
        return result

    result = visit(root, 0, len(raw), [])
    if len(result) > 1:
        for row in result:
            row['context'].insert(0, _context('code_source', 0, len(raw)))
    return result


def _split_code_structure_in_process(text, *, max_chars=2048, language=None):
    _validate(text, max_chars)
    raw = text.encode('utf-8')
    requested = language
    if language is not None:
        if type(language) is not str:
            raise ValueError('language must be a string or None')
        language = _ALIASES.get(language.casefold(), language.casefold())
    diagnostics = {'format': 'code', 'requested_language': requested, 'parse_attempted': False,
        'language_is_known': False, 'candidate_languages': [], 'parser_versions': {},
        'backend': 'optional_local_tree_sitter', 'consensus_scope': 'installed_supported_grammars_only'}
    def retained(reason):
        diagnostics['status'] = reason
        return _finish(text, raw, [_unit(0, len(raw), 'code_context', reason=reason)] if raw else [], diagnostics, max_chars)
    if not raw or len(text) <= max_chars:
        return retained('within_budget_unparsed')
    if len(raw) > MAX_PARSE_BYTES:
        return retained('parse_byte_limit')
    if language is None:
        return retained('language_not_provided')
    if language not in (*LANGUAGES, 'auto'):
        return retained('unsupported_language')
    diagnostics['parse_attempted'] = True
    candidates, rejected = [], {}
    for candidate in LANGUAGES if language == 'auto' else (language,):
        try:
            root, versions, count = _parse(raw, candidate)
            units = _syntax_units(raw, root, max_chars)
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError, SyntaxError, RecursionError) as exc:
            rejected[candidate] = ('parser_unavailable' if isinstance(exc, ImportError) else
                'python_syntax_error' if isinstance(exc, SyntaxError) else str(exc) if isinstance(exc, ValueError)
                and str(exc) in {'syntax_errors', 'nonlocal_syntax_requires_parent', *_INDETERMINATE} else type(exc).__name__)
            continue
        candidates.append((candidate, units))
        diagnostics['parser_versions'][candidate] = versions
        diagnostics.setdefault('parse_node_counts', {})[candidate] = count
    diagnostics.update(candidate_languages=[name for name, _ in candidates], rejected_candidates=rejected,
        language_assessment='clean_parse_candidates_only' if language == 'auto' else 'provided_language_hint')
    indeterminate = {name: reason for name, reason in rejected.items() if reason in _INDETERMINATE}
    if indeterminate:
        diagnostics['indeterminate_candidates'] = indeterminate
        return retained('indeterminate_parse_budget')
    if not candidates:
        return retained('no_clean_parse')
    boundaries = [[row['end_byte'] for row in units] for _, units in candidates]
    if any(item != boundaries[0] for item in boundaries[1:]):
        return retained('ambiguous_parse_boundaries')
    units = candidates[0][1]
    for _, other in candidates[1:]:
        for row, alternative in zip(units, other):
            for context in alternative['context']:
                if context not in row['context']:
                    row['context'].append(context)
    diagnostics['status'] = 'clean_parse_consensus' if language == 'auto' else 'provided_hint_clean_parse'
    diagnostics['parser_accepts_source'] = True
    return _finish(text, raw, units, diagnostics, max_chars)


def _worker_main():
    """Private one-request worker: native crashes cannot terminate its caller."""
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    request = json.load(sys.stdin)
    result = _split_code_structure_in_process(**request)
    json.dump(result, sys.stdout, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def split_code_structure(text, *, max_chars=2048, language=None):
    """Isolate every eligible oversized parse behind native and OS budgets."""
    _validate(text, max_chars)
    if language is not None and type(language) is not str:
        raise ValueError('language must be a string or None')
    normalized = _ALIASES.get(language.casefold(), language.casefold()) if language is not None else None
    raw = text.encode('utf-8')
    if len(text) <= max_chars or len(raw) > MAX_PARSE_BYTES or normalized not in (*LANGUAGES, 'auto'):
        result = _split_code_structure_in_process(text, language=language, max_chars=max_chars)
        result['diagnostics'].update(worker_isolation=False, worker_status='not_required')
        return result
    diagnostics = {'format': 'code', 'requested_language': language, 'parse_attempted': True,
        'language_is_known': False, 'candidate_languages': [], 'parser_versions': {},
        'backend': 'isolated_optional_local_tree_sitter', 'worker_isolation': True,
        'worker_timeout_seconds': MAX_WORKER_SECONDS, 'consensus_scope': 'installed_supported_grammars_only'}
    environment = dict(os.environ)
    environment.update(PYTHONPATH=os.pathsep.join(str(path) for path in sys.path),
        PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-c',
        'from ipfs_datasets_py.logic.formalization.code_structure import _worker_main; _worker_main()']
    request = json.dumps({'text': text, 'language': language, 'max_chars': max_chars}, ensure_ascii=False)
    try:
        completed = subprocess.run(command, input=request, text=True, encoding='utf-8',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
            timeout=MAX_WORKER_SECONDS, check=False)
        diagnostics['worker_exit_code'] = completed.returncode
        if completed.returncode:
            reason = 'parser_worker_crash' if completed.returncode < 0 else 'parser_worker_failed'
        else:
            result = json.loads(completed.stdout)
            assert result['schema'] == SCHEMA and result['source_sha256'] == hashlib.sha256(raw).hexdigest()
            cursor = byte_cursor = 0
            for row in result['units']:
                assert row['start'] == row['start_char'] == cursor and row['start_byte'] == byte_cursor
                end = row['end']
                assert type(end) is int and end == row['end_char'] and cursor < end <= len(text)
                byte_cursor += len(text[cursor:end].encode('utf-8'))
                assert row['end_byte'] == byte_cursor
                cursor = end
            assert cursor == len(text) and byte_cursor == len(raw)
            result['diagnostics'].update(worker_isolation=True, worker_status='completed',
                worker_exit_code=0, worker_timeout_seconds=MAX_WORKER_SECONDS)
            return result
    except subprocess.TimeoutExpired:
        reason = 'parser_worker_timeout'
    except OSError:
        reason = 'parser_worker_unavailable'
    except (ValueError, KeyError, TypeError, AssertionError):
        reason = 'parser_worker_protocol_error'
    diagnostics.update(status=reason, worker_status=reason, incomplete_language_assessment=True)
    return _finish(text, raw, [_unit(0, len(raw), 'code_context', reason=reason)], diagnostics, max_chars)


def split_diff_structure(text, *, max_chars=2048):
    """Split validated oversized unified hunks at complete edit/context runs.

    A contiguous removal/addition group is never bisected. Hunk counts and
    prefix grammar are checked, not language semantics or patch applicability.
    """
    _validate(text, max_chars)
    from ..security_ir.cvefixes.source_spans import _diff_intervals, _HUNK
    raw = text.encode('utf-8')
    diagnostics = {'format': 'diff', 'status': 'validated_hunk_runs', 'hunks_validated': 0,
        'language_is_known': False, 'parse_attempted': False, 'patch_applicability_verified': False,
        'boundary_basis': 'unified_diff_runs_not_code_syntax'}
    if len(raw) > MAX_PARSE_BYTES:
        diagnostics['status'] = 'parse_byte_limit'
        return _finish(text, raw, [_unit(0, len(raw), 'diff_context', reason='parse_byte_limit')], diagnostics, max_chars)
    intervals = list(_diff_intervals(text))
    # Native diff intervals are character-based; encode each once in source order.
    byte_points, previous, offset = {0: 0}, 0, 0
    for _, start, end in intervals:
        for point in (start, end):
            if point not in byte_points:
                offset += len(text[previous:point].encode()); byte_points[point] = offset; previous = point
    units, header, had_hunk = [], None, False
    try:
        for kind, start, end in intervals:
            part = text[start:end]
            lines = list(re.finditer(r'[^\n]*\n|[^\n]+$', part))
            a, b = byte_points[start], byte_points[end]
            if kind != 'diff_hunk':
                relative_byte = 0
                for i, line in enumerate(lines):
                    value = line[0]
                    paired = value.startswith('--- ') and i+1 < len(lines) and lines[i+1][0].startswith('+++ ')
                    if value.startswith('diff --git ') or paired and (header is None or had_hunk):
                        first = a + relative_byte
                        header = _context('diff_file_header', first, b); had_hunk = False
                    if value.startswith('@@') or (had_hunk and value[:1] in {'+', '-'} and not paired):
                        raise ValueError('malformed_hunk_material')
                    relative_byte += len(value.encode())
                units.append(_unit(a, b, 'diff_context', reason='file_context'))
                continue
            match = _HUNK.fullmatch(lines[0][0]) if lines else None
            if match is None:
                raise ValueError('malformed_hunk_header')
            old, new = int(match['old_count'] or '1'), int(match['new_count'] or '1')
            run_starts, previous_kind, payload_seen = [0], None, False
            for line in lines[1:]:
                value = line[0]
                if value.rstrip('\r\n') == '\\ No newline at end of file':
                    if not payload_seen:
                        raise ValueError('orphan_no_newline_marker')
                    payload_seen = False
                    continue
                delta = {' ': (1, 1), '-': (1, 0), '+': (0, 1)}.get(value[:1])
                if delta is None or old < delta[0] or new < delta[1] or not (old or new):
                    raise ValueError('malformed_hunk_payload')
                old -= delta[0]; new -= delta[1]; payload_seen = True
                run_kind = 'context' if value.startswith(' ') else 'change'
                if previous_kind is not None and run_kind != previous_kind:
                    run_starts.append(line.start())
                previous_kind = run_kind
            if old or new:
                raise ValueError('incomplete_hunk_counts')
            diagnostics['hunks_validated'] += 1; had_hunk = True
            context = [_context('diff_hunk', a, b)] + ([dict(header)] if header is not None else [])
            # Greedy packing uses only complete grammar runs, never line limits.
            ranges = list(zip(run_starts, run_starts[1:]+[len(part)]))
            grouped = []
            for left, right in ranges:
                if grouped and right-grouped[-1][0] <= max_chars:
                    grouped[-1] = (grouped[-1][0], right)
                else:
                    grouped.append((left, right))
            byte_cursor = a
            edit_starts = [line.start() for line in lines[1:] if line[0][:1] in {'-', '+'}]
            for left, right in grouped:
                byte_end = byte_cursor + len(part[left:right].encode())
                edit_index = bisect_left(edit_starts, left)
                edits = edit_index < len(edit_starts) and edit_starts[edit_index] < right
                kind = 'diff_hunk' if len(grouped) == 1 else 'diff_edit_group' if edits else 'diff_context_group'
                row = _unit(byte_cursor, byte_end, kind, context,
                    'whole_hunk' if len(grouped) == 1 else 'complete_diff_runs')
                row['missing_file_header_context'] = header is None
                units.append(row); byte_cursor = byte_end
    except (ValueError, OverflowError):
        diagnostics['status'] = 'malformed_diff_retained'
        diagnostics['hunks_validated'] = 0
        units = [_unit(0, len(raw), 'diff_context', reason='malformed_diff_retained')] if raw else []
    if not diagnostics['hunks_validated'] and diagnostics['status'] != 'malformed_diff_retained':
        diagnostics['status'] = 'no_unified_hunks'
    return _finish(text, raw, units, diagnostics, max_chars)


def _validate(text, max_chars):
    if type(text) is not str or type(max_chars) is not int or max_chars < 1:
        raise ValueError('invalid code-structure source or maximum')


def build_code_structure(text, *, format='code', language=None, max_chars=2048):
    if format == 'code':
        return split_code_structure(text, language=language, max_chars=max_chars)
    if format == 'diff':
        return split_diff_structure(text, max_chars=max_chars)
    raise ValueError('code structure supports only code or diff')


__all__ = ['build_code_structure', 'split_code_structure', 'split_diff_structure']
