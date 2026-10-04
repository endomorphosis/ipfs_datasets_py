"""Additive, lossless source chunks with explicit structural dependencies.

These chunks organize source evidence; they do not supply reviewed targets,
training admission, or proof authority. Existing raw inventories are untouched.
Markdown and prose fields reuse the frozen structural parser: prose metadata
can contain paragraphs, lists and marked code. This retains the parser's limits
and prefix-encoding cost; large code/diff bodies bypass it. Unmarked or inline
code is not generally detected. New UTF-8 selectors use one sparse source pass.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from functools import lru_cache

SCHEMA = 'source-coherent-spans/v1'
POLICY_ID = 'source-structural-coherence/v1'
CODE_POLICY_ID = 'source-structural-coherence/code-structure-v2'
MAX_MARKDOWN_CHARACTERS = 1024 * 1024
_BOLD_LABEL = re.compile(r'^(?:\*\*(?:(?!\*\*)[^\r\n])+\*\*|__(?:(?!__)[^\r\n])+__)[ \t]*$')
_LIST = re.compile(r'^(?P<indent>[ \t]*)(?:[-+*]|\d+[.)])[ \t]+')
_ATOMIC = frozenset({'heading', 'bold_label', 'frontmatter', 'fenced_code', 'indented_code',
    'table_or_pipe_expression', 'quoted_example', 'code_context', 'diff_context', 'diff_hunk', 'layout'})


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def _reference(role, start, end):
    return {'role': role, 'start_char': start, 'end_char': end}


def _markdown_units(text):
    from ..intent_ir.formalize.skillcenter_spans import _markdown_blocks

    if len(text) > MAX_MARKDOWN_CHARACTERS:
        raise ValueError('Structured prose/Markdown exceeds the explicit legacy-parser character bound')
    units = []
    for block in _markdown_blocks(text):
        start, end, kind = block['start_char'], block['end_char'], block['kind']
        first_unit = len(units)
        marker = _LIST.match(text[start:end]) if kind == 'list_item' else None
        extra = {'is_list': marker is not None, 'indent': len(marker['indent'].expandtabs(4)) if marker else 0,
            'content_start': block.get('content_start_char', start),
            'level': block['heading_context'][-1]['level'] if kind == 'heading' else None}
        if kind in {'paragraph', 'list_item'}:
            # Bold-only lines act as local labels, not punctuation-split prose.
            cursor, piece = start, start
            for line in text[start:end].splitlines(keepends=True):
                label_text = line.strip()
                if marker is not None and cursor == start:
                    label_text = text[extra['content_start']:cursor + len(line)].strip()
                if _BOLD_LABEL.fullmatch(label_text):
                    if piece < cursor:
                        units.append({'start': piece, 'end': cursor, 'kind': kind, **extra})
                    units.append({'start': cursor, 'end': cursor + len(line), 'kind': 'bold_label', **extra})
                    piece = cursor + len(line)
                cursor += len(line)
            if piece < end:
                units.append({'start': piece, 'end': end, 'kind': kind, **extra,
                    'content_start': max(piece, extra['content_start'])})
        else:
            units.append({'start': start, 'end': end, 'kind': kind, **extra})
        if len(units) - first_unit > 1:
            for unit in units[first_unit:]:
                if unit['kind'] != 'bold_label':
                    unit['origin_context'] = _reference('structural_unit', start, end)
    headings, label, pending, list_lead, parents = [], None, None, None, []
    for unit in units:
        start, end, kind = unit['start'], unit['end'], unit['kind']
        if kind == 'whitespace':
            unit['context'] = []
            continue
        if kind == 'heading':
            headings = [item for item in headings if item['level'] < unit['level']]
            unit['context'] = [item['reference'] for item in headings]
            headings.append({'level': unit['level'], 'reference': _reference('heading', start, end)})
            label, pending, list_lead, parents = None, None, None, []
            continue
        context = [item['reference'] for item in headings]
        if 'origin_context' in unit:
            context.append(unit['origin_context'])
        if label is not None and kind != 'bold_label':
            context.append(label)
        if unit['is_list']:
            parents = [item for item in parents if item['indent'] < unit['indent']]
            context.extend(item['reference'] for item in parents)
            if pending is not None:
                # Item conditions are represented by the indentation-scoped
                # parent list selectors; they cannot replace the whole-list
                # paragraph lead-in when entering or leaving a nested item.
                if pending['indent'] is None:
                    list_lead = pending
                pending = None
            if list_lead is not None:
                context.append(list_lead['reference'])
            parents.append({'indent': unit['indent'],
                'reference': _reference('parent_list', max(start, unit['content_start']), end)})
        else:
            parents, list_lead = [], None
            if pending is not None and pending['indent'] is None:
                context.append(pending['reference'])
            pending = None
        unit['context'] = context
        if kind == 'bold_label' and not unit['is_list']:
            label = _reference('label', start, end)
        elif kind in {'paragraph', 'list_item'} and text[start:end].rstrip().endswith(':'):
            pending = {'reference': _reference('lead_in', max(start, unit['content_start']), end),
                'indent': unit['indent'] if unit['is_list'] else None}
        # Code, tables, and completed paragraphs never establish broad inherited
        # lead-ins merely because they contain a pronoun or quantifier.
    return units


def _diff_units(text):
    from ..security_ir.cvefixes.source_spans import _diff_intervals

    units = [{'start': start, 'end': end, 'kind': kind, 'context': []}
        for kind, start, end in _diff_intervals(text)]
    hunk_starts = {unit['start'] for unit in units if unit['kind'] == 'diff_hunk'}
    headers, current, header_end, offset, unit_index = {}, None, None, 0, 0
    lines = re.findall(r'[^\n]*\n|[^\n]+$', text)
    for index, line in enumerate(lines):
        while unit_index < len(units) and units[unit_index]['end'] <= offset:
            unit_index += 1
        in_context = unit_index < len(units) and units[unit_index]['kind'] == 'diff_context'
        paired_header = line.startswith('--- ') and index + 1 < len(lines) and lines[index + 1].startswith('+++ ')
        if in_context and (line.startswith('diff --git ') or paired_header and (current is None or header_end is not None)):
            current, header_end = offset, None
        if offset in hunk_starts and current is not None:
            if header_end is None:
                header_end = offset
            if current < header_end:
                headers[offset] = _reference('diff_file_header', current, header_end)
        offset += len(line)
    for unit in units:
        if unit['start'] in headers:
            unit['context'] = [headers[unit['start']]]
        unit['missing_file_header_context'] = unit['kind'] == 'diff_hunk' and not unit['context']
    return units


def _attach_layout(text, units):
    """Attach all layout to adjacent units without merging structural content."""
    attached = []
    for item in units:
        unit = dict(item)
        unit.setdefault('context', [])
        if not text[unit['start']:unit['end']].strip():
            if attached:
                attached[-1]['end'] = unit['end']
            continue
        if not attached:
            unit['start'] = 0
        attached.append(unit)
    if not attached and text:
        return [{'start': 0, 'end': len(text), 'kind': 'layout', 'context': []}]
    return attached


def _group_prose(part, *, content_start, embedder, max_chars, min_chars, embedding_eligible):
    from ...ml.embeddings.chunker import sentence_source_spans_with_diagnostics

    sentence_report = sentence_source_spans_with_diagnostics(part[content_start:])
    sentences = sentence_report['spans']
    starts = [content_start + start for start, _ in sentences]
    atoms = [(0 if index == 0 else start, starts[index + 1] if index + 1 < len(starts) else len(part))
        for index, start in enumerate(starts)]
    base = {'sentence_segmentation': sentence_report, 'sentence_input_start_char': content_start,
        'atoms': [{'start_char': start, 'end_char': end} for start, end in atoms]}
    if len(atoms) < 2:
        return [(0, len(part))], {**base, 'method': 'atomic_sentence' if atoms else 'layout_only',
            'embedding_status': 'not_required', 'embeddings_used': False, 'token_budget_checked': False}
    if embedder is not None:
        from ...ml.embeddings.semantic_boundaries import group_semantic_atoms

        report = group_semantic_atoms(part, atoms, embedder=embedder, max_chars=max_chars,
            min_chars=min_chars, embedding_eligible=embedding_eligible, on_embedding_error='structural')
        return [(row['start_char'], row['end_char']) for row in report['groups']], {**base, **report}
    groups = []
    for start, end in atoms:
        if groups and end - groups[-1][0] <= max_chars:
            groups[-1] = (groups[-1][0], end)
        else:
            groups.append((start, end))
    return groups, {**base, 'method': 'structural_sentence_packing', 'embedding_status': 'not_requested', 'embeddings_used': False,
        'atomic_sentence_count': len(atoms), 'token_budget_checked': False}


def build_coherent_spans(text, *, source_id, format='prose', raw_spans=(), embedder=None,
                         max_chars=2048, min_chars=128, embedding_eligible=None,
                         code_structure=False, code_language=None):
    """Return source-bound chunks, context selectors, and explicit grouping diagnostics.

    ``raw_spans`` may supply existing ``id``/``span_id`` and exact selectors;
    overlap links are provenance only. Embeddings are optional and local to a
    structural unit. A runtime failure records structural fallback; oversized
    atomic sentences/code remain intact and explicitly over budget. Opt in to
    ``code_structure`` for syntax-aware code and validated diff subdivisions;
    ``code_language='auto'`` explicitly requests conservative parser consensus.
    This has a separate policy identity and does not change raw source spans.
    """
    if (type(text) is not str or type(source_id) is not str or not source_id.strip()
            or format not in {'prose', 'markdown', 'code', 'diff'}
            or type(max_chars) is not int or max_chars < 1
            or type(min_chars) is not int or not 0 <= min_chars <= max_chars
            or type(code_structure) is not bool
            or code_language is not None and (type(code_language) is not str or not code_language.strip())
            or code_language is not None and not code_structure
            or embedder is not None and not callable(embedder)
            or embedding_eligible is not None and not callable(embedding_eligible)):
        raise ValueError('invalid coherent-span source or configuration')
    source_bytes = text.encode('utf-8')
    source_sha = _sha(source_bytes)
    policy_id = CODE_POLICY_ID if code_structure else POLICY_ID
    structure_report = None
    if code_structure and format in {'code', 'diff'}:
        from .code_structure import build_code_structure

        structure_report = build_code_structure(text, format=format,
            language=code_language, max_chars=max_chars)
        units = [{**unit, 'structural_code_context': True} for unit in structure_report['units']]
    elif format in {'prose', 'markdown'}:
        units = _markdown_units(text)
    elif format == 'diff':
        units = _diff_units(text)
    elif text:
        units = [{'start': 0, 'end': len(text), 'kind': 'code_context', 'context': []}]
    else:
        units = []
    units = _attach_layout(text, units)
    pieces, grouping = [], []
    for unit in units:
        start, end = unit['start'], unit['end']
        if unit['kind'] in _ATOMIC or unit.get('structural_code_context'):
            intervals = [(0, end - start)]
        else:
            intervals, report = _group_prose(text[start:end], content_start=max(0, unit.get('content_start', start) - start),
                embedder=embedder, max_chars=max_chars, min_chars=min_chars, embedding_eligible=embedding_eligible)
            grouping.append({'start_char': start, 'end_char': end, 'kind': unit['kind'], 'report': report})
        for left, right in intervals:
            contexts = list(unit['context'])
            if len(intervals) > 1:
                contexts.append(_reference('structural_unit', start, end))
            pieces.append({**unit, 'start': start + left, 'end': start + right, 'context': contexts})
    raw_rows, raw_ids = [], set()
    for row in raw_spans:
        if not isinstance(row, Mapping):
            raise ValueError('raw span must be an inert mapping')
        identifier = row.get('id', row.get('span_id'))
        start, end = row.get('start_char'), row.get('end_char')
        if (type(identifier) is not str or not identifier or identifier in raw_ids
                or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or 'text' in row and row['text'] != text[start:end]
                or 'source_sha256' in row and row['source_sha256'] != source_sha
                or 'raw_body_sha256' in row and row['raw_body_sha256'] != source_sha
                or 'source_id' in row and row['source_id'] != source_id
                or 'source_field_id' in row and row['source_field_id'] != source_id):
            raise ValueError('raw span source binding differs')
        raw_rows.append((start, end, identifier, row)); raw_ids.add(identifier)
    raw_rows.sort(key=lambda row: (row[0], row[1], row[2]))
    points = {0, len(text)}
    for piece in pieces:
        points.update((piece['start'], piece['end']))
        for context in piece['context']:
            points.update((context['start_char'], context['end_char']))
    for start, end, _, _ in raw_rows:
        points.update((start, end))
    byte_positions, cursor, byte_cursor = {}, 0, 0
    for point in sorted(points):
        byte_cursor += len(text[cursor:point].encode('utf-8'))
        byte_positions[point] = byte_cursor; cursor = point
    for start, end, _, row in raw_rows:
        if ('start_byte' in row and row['start_byte'] != byte_positions[start]
                or 'end_byte' in row and row['end_byte'] != byte_positions[end]):
            raise ValueError('raw span UTF-8 binding differs')
    @lru_cache(maxsize=None)
    def selector(start, end):
        value = text[start:end]
        return {'start_char': start, 'end_char': end, 'start_byte': byte_positions[start],
            'end_byte': byte_positions[end], 'text': value, 'normalized_text': _normalize(value)}
    chunks, active, raw_index, cursor = [], [], 0, 0
    for piece in pieces:
        start, end = piece['start'], piece['end']
        if start != cursor or not start < end:
            raise ValueError('structural chunks do not exactly partition source')
        cursor = end
        active = [row for row in active if row[1] > start]
        while raw_index < len(raw_rows) and raw_rows[raw_index][0] < end:
            if raw_rows[raw_index][1] > start:
                active.append(raw_rows[raw_index])
            raw_index += 1
        contexts = [{**selector(item['start_char'], item['end_char']), 'role': item['role']} for item in piece['context']]
        identity = {'policy_id': policy_id, 'source_id': source_id, 'source_sha256': source_sha,
            'format': format, 'kind': piece['kind'], 'start_char': start, 'end_char': end,
            'context_ranges': piece['context']}
        chunks.append({'schema': 'source-coherent-chunk/v1', 'chunk_id': 'sha256:' + _sha(_wire(identity)),
            **identity, **selector(start, end), 'context_selectors': contexts,
            'raw_span_ids': [row[2] for row in active], 'raw_provenance_status': 'overlap_links' if raw_rows else 'not_provided',
            'context_only': piece['kind'] in _ATOMIC or bool(piece.get('structural_code_context')),
            'requires_context': bool(contexts) or piece['kind'] in _ATOMIC or bool(piece.get('structural_code_context')),
            'missing_file_header_context': piece.get('missing_file_header_context', False),
            **({'code_structure': {'reason': piece.get('reason'), 'syntax_type': piece.get('syntax_type'),
                'source_status': structure_report['diagnostics']['status']}}
                if piece.get('structural_code_context') else {}),
            'exceeds_max_chars': end - start > max_chars, 'training_eligible': False, 'eligibility_status': 'not_assessed',
            'gold_target': False, 'source_semantics_verified': False, 'complete_compilation_unit': False,
            'proof_authority': False, 'execution_authority': False, 'truncated': False})
    if cursor != len(text):
        raise ValueError('coherent chunks omitted source text')
    return {'schema': SCHEMA, 'policy_id': policy_id, 'source_id': source_id, 'source_sha256': source_sha,
        'format': format, 'chunks': chunks, 'diagnostics': {'source_characters': len(text), 'source_utf8_bytes': len(source_bytes),
            'represented_characters': sum(len(row['text']) for row in chunks), 'source_reconstructed_exactly': True,
            'raw_span_count': len(raw_rows), 'structural_unit_count': len(units), 'oversize_chunks': sum(c['exceeds_max_chars'] for c in chunks),
            'grouping': grouping, 'embedding_requested': embedder is not None,
            'semantic_correctness_verified': False, 'training_admission_performed': False,
            'markdown_parser_character_bound': MAX_MARKDOWN_CHARACTERS if format in {'prose', 'markdown'} else None,
            **({'code_structure': structure_report['diagnostics'] if structure_report is not None else
                {'status': 'not_applicable', 'format': format}, 'code_language_requested': code_language}
               if code_structure else {})}}


__all__ = ['build_coherent_spans']
