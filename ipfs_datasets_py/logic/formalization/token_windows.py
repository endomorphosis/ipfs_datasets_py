"""Exact-source token-budget windows using an explicitly supplied fast tokenizer.

Windows may break syntax and always require their parent context. Source bytes
are preserved independently of the tokenizer's possibly lossy normalization or
UNK representation. Context references are metadata, never appended payload.
No model/tokenizer loading, decoding, network calls, or training occurs here.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping
import hashlib
import json
import math
import re
from typing import Protocol

SCHEMA = 'source-token-budget-windows/v1'
BOUNDARY_POLICY = 'source-token-preferred-boundaries/v1'


class FastOffsetTokenizer(Protocol):
    is_fast: bool
    unk_token_id: int | None

    def __call__(self, text: str, **kwargs) -> Mapping: ...


class TokenWindowError(ValueError):
    """The tokenizer/configuration cannot certify exact-source budget windows."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _union_characters(intervals):
    total = end = 0
    for left, right in sorted(intervals):
        total += max(0, right-max(end, left))
        end = max(end, right)
    return total


def _encoding(tokenizer, text):
    encoded = tokenizer(text, add_special_tokens=True, truncation=False, padding=False,
        return_offsets_mapping=True, return_special_tokens_mask=True,
        return_attention_mask=False, return_token_type_ids=False)
    if not isinstance(encoded, Mapping):
        raise TokenWindowError('tokenizer must return an inert mapping')
    ids, offsets, mask = (encoded.get(key) for key in ('input_ids', 'offset_mapping', 'special_tokens_mask'))
    if (not all(isinstance(value, (list, tuple)) for value in (ids, offsets, mask))
            or not len(ids) == len(offsets) == len(mask)
            or any(type(token) is not int or token < 0 for token in ids)
            or any(type(item) is not int or item not in (0, 1) for item in mask)):
        raise TokenWindowError('invalid token IDs, offsets, or special-token mask')
    content, previous_start, previous_end = [], 0, 0
    for token, pair, special in zip(ids, offsets, mask):
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(type(position) is not int for position in pair)
                or not 0 <= pair[0] <= pair[1] <= len(text)):
            raise TokenWindowError('invalid tokenizer character offset')
        if special:
            continue
        left, right = pair
        if left < right:
            if left < previous_start or right < previous_end:
                raise TokenWindowError('nonmonotone tokenizer character offsets')
            previous_start, previous_end = left, right
        content.append((left, right, token))
    return {'ids': list(ids), 'content': content, 'special_tokens': sum(mask),
        'input_tokens': len(ids), 'content_tokens': len(content)}


def _unknown(encoding, unknown_id):
    intervals = [(a, b) for a, b, token in encoding['content'] if token == unknown_id]
    return {'unknown_tokens': len(intervals), 'unknown_characters': _union_characters(intervals),
        'longest_unknown_span': max((b-a for a, b in intervals), default=0),
        'zero_length_content_offsets': sum(a == b for a, b, _ in encoding['content']),
        'mapped_token_characters': _union_characters((a, b) for a, b, _ in encoding['content'])}


def build_token_windows(parent_text: str, *, tokenizer: FastOffsetTokenizer, source_id: str,
                        parent_id: str, parent_start_char: int = 0, parent_start_byte: int = 0,
                        source_sha256: str | None = None, max_input_tokens: int = 512,
                        overlap_tokens: int = 64, boundary_candidates=None,
                        min_boundary_fill: float = 0.5) -> dict:
    """Preserve one parent while bounding every independently recounted payload.

    Absolute parent offsets and optional whole-source hash are caller-supplied
    provenance. This function verifies/hash-binds the exact parent slice itself.
    Requested overlap excludes special tokens and is a ceiling; retokenization
    or progress constraints can reduce it. Packing is not claimed to be maximal.
    Optional candidates are relative character offsets whose structural meaning
    is caller-supplied. They prefer cuts within the safe payload's final token
    region; exact candidate slices must also satisfy the minimum content fill.
    Priority >=3 declares a structural boundary and exempts it from that fill
    threshold, preserving short complete units before a larger next unit.
    Overlap starts prefer supplied boundaries and otherwise use zero overlap.
    Optional priority-2 ``semantic_score`` values are finite adjacent cosines.
    Lower scores rank first, then later endpoints / earlier overlap starts. This
    is relative ranking, not a claim that any score marks an absolute topic break.
    None or candidates without scores preserve existing reports and identities.
    """
    if (type(parent_text) is not str or not callable(tokenizer) or getattr(tokenizer, 'is_fast', None) is not True
            or any(type(value) is not str or not value.strip() for value in (source_id, parent_id))
            or any(type(value) is not int or value < 0 for value in (parent_start_char, parent_start_byte))
            or type(max_input_tokens) is not int or max_input_tokens < 1
            or type(overlap_tokens) is not int or not 0 <= overlap_tokens < max_input_tokens
            or source_sha256 is not None and (type(source_sha256) is not str or re.fullmatch('[0-9a-f]{64}', source_sha256) is None)):
        raise TokenWindowError('invalid source, fast tokenizer, or token-window configuration')
    if (type(min_boundary_fill) not in (int, float) or not math.isfinite(min_boundary_fill)
            or not 0 < min_boundary_fill <= 1):
        raise TokenWindowError('minimum boundary fill must be finite and in (0, 1]')
    aware = boundary_candidates is not None
    candidates = []
    if aware:
        if not isinstance(boundary_candidates, (list, tuple)):
            raise TokenWindowError('boundary candidates must be an inert list or tuple')
        by_offset = {}
        for row in boundary_candidates:
            if (type(row) is not dict or set(row) not in ({'offset', 'kind', 'priority'},
                    {'offset', 'kind', 'priority', 'semantic_score'})
                    or type(row['offset']) is not int or not 0 <= row['offset'] <= len(parent_text)
                    or type(row['kind']) is not str or not row['kind'].strip()
                    or type(row['priority']) is not int or row['priority'] < 1):
                raise TokenWindowError('invalid source-relative boundary candidate')
            if 'semantic_score' in row and (row['priority'] != 2
                    or type(row['semantic_score']) not in (int, float)
                    or not math.isfinite(row['semantic_score'])
                    or not -1 <= row['semantic_score'] <= 1):
                raise TokenWindowError('semantic score must be a finite priority-2 cosine')
            previous = by_offset.get(row['offset'])
            if previous is None or (-row['priority'], row.get('semantic_score', math.inf), row['kind']) < (
                    -previous['priority'], previous.get('semantic_score', math.inf), previous['kind']):
                by_offset[row['offset']] = dict(row)
        candidates = [by_offset[offset] for offset in sorted(by_offset)]
    ranked = any('semantic_score' in row for row in candidates)
    candidate_offsets = [row['offset'] for row in candidates]
    boundary_policy = {'schema': BOUNDARY_POLICY, 'candidates_sha256': _sha(_wire(candidates)),
        'min_boundary_fill': float(min_boundary_fill), 'structural_priority_threshold': 3,
        'meaning_binding': 'caller_supplied'} if aware else None
    if ranked:
        boundary_policy['semantic_ranking'] = {
            'schema': 'adjacent-cosine-relative-ranking/v1',
            'priority': 2, 'score_order': 'ascending', 'unscored_order': 'after_scored',
            'endpoint_tie_order': 'rightmost', 'overlap_tie_order': 'leftmost',
            'absolute_topic_break_claimed': False}
    boundary_counts, boundary_skips = Counter(), Counter()
    try:
        raw = parent_text.encode('utf-8')
    except UnicodeEncodeError:
        raise TokenWindowError('source is not valid UTF-8 encodable Unicode') from None
    unknown_id = getattr(tokenizer, 'unk_token_id', None)
    if unknown_id is not None and (type(unknown_id) is not int or unknown_id < 0):
        raise TokenWindowError('invalid tokenizer unknown-token identifier')
    calls = 0
    def encode(part):
        nonlocal calls
        calls += 1
        return _encoding(tokenizer, part)
    full = encode(parent_text)
    capacity = max_input_tokens-full['special_tokens']
    if full['input_tokens'] > max_input_tokens and (capacity < 1 or overlap_tokens >= capacity):
        raise TokenWindowError('special tokens/overlap leave no progressing content budget')
    parent_hash = _sha(raw)
    parent_ref = {'parent_id': parent_id, 'source_id': source_id, 'source_sha256': source_sha256,
        'parent_sha256': parent_hash, 'start_char': parent_start_char,
        'end_char': parent_start_char+len(parent_text), 'start_byte': parent_start_byte,
        'end_byte': parent_start_byte+len(raw)}
    mapped = [(a, b) for a, b, _ in full['content'] if a < b]
    ends = [b for _, b in mapped]
    recount_adjustments = overlap_adjustments = progress_overlap_drops = 0

    def prefer_end(start, covered, end, encoded):
        if end == len(parent_text):
            return end, encoded, 'parent_end', None, None
        required = math.ceil(capacity*min_boundary_fill)
        # Search only the current bounded token region, not the parent-wide
        # candidate list. Recounting below remains necessary: prefix token
        # counts can change nonmonotonically at a source cut.
        enough_fill = encoded['content_tokens'] >= required
        lower = max(covered+1, start+encoded['content'][required-1][1]) if enough_fill else end+1
        left, right = bisect_right(candidate_offsets, covered), bisect_right(candidate_offsets, end)
        if left == right:
            boundary_skips['no_candidate_in_safe_payload'] += 1
        eligible = sorted(candidates[left:right], key=lambda row: (
            -row['priority'], row.get('semantic_score', math.inf), -row['offset'], row['kind']))
        for row in eligible:
            structural = row['priority'] >= 3
            if not structural and row['offset'] < lower:
                boundary_skips['before_min_fill_region'] += 1
                continue
            chosen = encoded if row['offset'] == end else encode(parent_text[start:row['offset']])
            boundary_counts['endpoint_candidates_checked'] += 1
            if chosen['input_tokens'] > max_input_tokens:
                boundary_skips['candidate_over_budget'] += 1
                continue
            if chosen['content_tokens'] < required and not structural:
                boundary_skips['candidate_below_min_fill'] += 1
                continue
            if chosen['content_tokens'] < required:
                boundary_counts['underfilled_structural_cuts'] += 1
            return row['offset'], chosen, 'preferred_boundary', row['kind'], row.get('semantic_score')
        return end, encoded, 'hard_token_fallback', None, None

    def prefer_overlap(start, end, candidate):
        if not overlap_tokens:
            return end, 'disabled', None, None
        left = bisect_left(candidate_offsets, max(start+1, candidate))
        right = bisect_left(candidate_offsets, end)
        # Prefer higher-level boundaries, then retain the largest available
        # overlap. Every accepted source suffix is independently recounted.
        eligible = sorted(candidates[left:right], key=lambda row: (
            -row['priority'], row.get('semantic_score', math.inf), row['offset'], row['kind']))
        for row in eligible:
            repeated = encode(parent_text[row['offset']:end])
            boundary_counts['overlap_candidates_checked'] += 1
            if repeated['content_tokens'] <= overlap_tokens:
                return row['offset'], 'preferred_boundary', row['kind'], row.get('semantic_score')
            boundary_skips['overlap_candidate_over_budget'] += 1
        boundary_counts['overlap_dropped_no_boundary'] += 1
        return end, 'no_fitting_boundary', None, None

    def initial_end(start):
        first = bisect_right(ends, start)
        if first >= len(mapped):
            return len(parent_text)
        index = min(first+capacity, len(mapped))-1
        end = mapped[index][1]
        # Attach ignored layout between tokens without changing any source byte.
        if index+1 == len(mapped):
            end = len(parent_text)
        elif mapped[index+1][0] > end:
            end = mapped[index+1][0]
        return max(start+1, end)

    def bounded_payload(start):
        nonlocal recount_adjustments
        end = initial_end(start)
        while True:
            encoded = encode(parent_text[start:end])
            if encoded['input_tokens'] <= max_input_tokens:
                return end, encoded
            if end-start == 1:
                raise TokenWindowError('one source codepoint cannot fit the input token budget')
            available = max_input_tokens-encoded['special_tokens']
            valid = [(a, b) for a, b, _ in encoded['content'] if a < b]
            proposal = start+valid[min(available, len(valid))-1][1] if available > 0 and valid else end
            # Counts need not be monotone in prefix length (notably WordPiece
            # UNK collapse). This is a finite search for a valid slice, not a
            # maximum-size claim; every accepted raw slice is counted again.
            end = proposal if start < proposal < end else start+max(1, (end-start)//2)
            recount_adjustments += 1

    def next_start(start, end, encoded):
        nonlocal overlap_adjustments
        if not overlap_tokens:
            return end
        content = encoded['content']
        candidate = start+content[max(0, len(content)-overlap_tokens)][0] if content else end
        if candidate <= start:
            candidate = end
        while candidate < end:
            repeated = encode(parent_text[candidate:end])
            if repeated['content_tokens'] <= overlap_tokens:
                return candidate
            valid = [(a, b) for a, b, _ in repeated['content'] if a < b]
            proposal = candidate+valid[max(0, len(valid)-overlap_tokens)][0] if valid else candidate
            candidate = proposal if candidate < proposal <= end else candidate+max(1, (end-candidate)//2)
            overlap_adjustments += 1
        return end

    records = []
    if full['input_tokens'] <= max_input_tokens:
        records.append({'start': 0, 'end': len(parent_text), 'exclusive_start': 0,
            'encoding': full, 'previous_encoding': None, 'previous_start': 0})
        if aware:
            records[-1].update(cut_basis='parent_end', cut_kind=None,
                overlap_basis='parent_start', overlap_kind=None)
        if ranked:
            records[-1].update(cut_semantic_score=None, overlap_semantic_score=None)
    else:
        start = covered = 0
        previous_encoding, previous_start = None, 0
        overlap_basis, overlap_kind, overlap_score = 'parent_start', None, None
        while covered < len(parent_text):
            end, encoded = bounded_payload(start)
            if end <= covered:
                start = covered
                end, encoded = bounded_payload(start)
                progress_overlap_drops += 1
                overlap_basis, overlap_kind, overlap_score = 'progress_no_overlap', None, None
            if aware:
                end, encoded, cut_basis, cut_kind, cut_score = prefer_end(start, covered, end, encoded)
            if not start <= covered < end:
                raise TokenWindowError('window failed to make forward source progress')
            records.append({'start': start, 'end': end, 'exclusive_start': covered,
                'encoding': encoded, 'previous_encoding': previous_encoding, 'previous_start': previous_start})
            if aware:
                records[-1].update(cut_basis=cut_basis, cut_kind=cut_kind,
                    overlap_basis=overlap_basis, overlap_kind=overlap_kind)
            if ranked:
                records[-1].update(cut_semantic_score=cut_score, overlap_semantic_score=overlap_score)
            previous_encoding, previous_start = encoded, start
            covered = end
            if covered < len(parent_text):
                candidate = next_start(start, end, encoded)
                if aware:
                    start, overlap_basis, overlap_kind, overlap_score = prefer_overlap(start, end, candidate)
                else:
                    start = candidate
    points = {0, len(parent_text)}
    for record in records:
        points.update((record['start'], record['end'], record['exclusive_start']))
    byte_offsets, cursor, byte_cursor = {}, 0, 0
    for point in sorted(points):
        byte_cursor += len(parent_text[cursor:point].encode('utf-8'))
        byte_offsets[point] = byte_cursor; cursor = point
    windows, covered, previous_start = [], 0, -1
    for index, record in enumerate(records):
        start, end, exclusive = record['start'], record['end'], record['exclusive_start']
        encoded = record['encoding']
        text = parent_text[start:end]
        assert exclusive == covered and start <= exclusive <= end
        assert start > previous_start or index == 0
        repeated = encode(parent_text[start:exclusive]) if start < exclusive else None
        measured_overlap = repeated['content_tokens'] if repeated is not None else 0
        assert measured_overlap <= overlap_tokens
        def intersecting_tokens(encoding, origin):
            if encoding is None:
                return []
            return [(token, origin+a, origin+b) for a, b, token in encoding['content']
                if a < b and origin+a < exclusive and origin+b > start]
        old_tokens = intersecting_tokens(record['previous_encoding'], record['previous_start'])
        current_tokens = intersecting_tokens(encoded, start)
        statistics = _unknown(encoded, unknown_id)
        identity = {'schema': SCHEMA, 'source_id': source_id, 'source_sha256': source_sha256,
            'parent_id': parent_id, 'parent_sha256': parent_hash, 'start_char': parent_start_char+start,
            'end_char': parent_start_char+end, 'max_input_tokens': max_input_tokens,
            'requested_overlap_tokens': overlap_tokens, 'input_token_ids_sha256': _sha(_wire(encoded['ids']))}
        if aware:
            identity['boundary_policy'] = boundary_policy
        windows.append({**identity, 'window_id': 'sha256:'+_sha(_wire(identity)), 'text': text,
            'parent_ref': dict(parent_ref), 'start_byte': parent_start_byte+byte_offsets[start],
            'end_byte': parent_start_byte+byte_offsets[end],
            'exclusive_start_char': parent_start_char+exclusive, 'exclusive_end_char': parent_start_char+end,
            'exclusive_start_byte': parent_start_byte+byte_offsets[exclusive], 'exclusive_end_byte': parent_start_byte+byte_offsets[end],
            'overlap_start_char': parent_start_char+start, 'overlap_end_char': parent_start_char+exclusive,
            'overlap_start_byte': parent_start_byte+byte_offsets[start], 'overlap_end_byte': parent_start_byte+byte_offsets[exclusive],
            'input_tokens': encoded['input_tokens'], 'content_tokens': encoded['content_tokens'],
            'special_tokens': encoded['special_tokens'], 'overlap_tokens': measured_overlap,
            'overlap_previous_window_tokens': len(old_tokens), 'overlap_current_window_tokens': len(current_tokens),
            'overlap_tokenization_identical': old_tokens == current_tokens,
            **statistics, 'unmapped_source_characters': len(text)-statistics['mapped_token_characters'],
            'whitespace_only': not text.strip(), 'zero_content_tokens': encoded['content_tokens'] == 0,
            'encoding_losslessness_verified': False, 'source_semantics_verified': False,
            'syntax_may_be_split': len(records) > 1, 'requires_context': True,
            'context_in_payload': False, 'whole_parent': start == 0 and end == len(parent_text),
            'training_eligible': False, 'proof_authority': False, 'execution_authority': False,
            'truncated': False})
        if aware:
            windows[-1].update({key: record[key] for key in ('cut_basis', 'cut_kind', 'overlap_basis', 'overlap_kind')})
            if ranked:
                windows[-1].update(cut_semantic_score=record['cut_semantic_score'],
                    overlap_semantic_score=record['overlap_semantic_score'])
            boundary_counts['cut_'+record['cut_basis']] += 1
            boundary_counts['overlap_'+record['overlap_basis']] += 1
        assert windows[-1]['input_tokens'] <= max_input_tokens
        previous_start, covered = start, end
    assert covered == len(parent_text)
    parent_statistics = _unknown(full, unknown_id)
    result = {'schema': SCHEMA, 'parent_ref': parent_ref, 'windows': windows,
        'diagnostics': {'parent_input_tokens': full['input_tokens'], 'parent_content_tokens': full['content_tokens'],
            'special_tokens': full['special_tokens'], 'content_budget': capacity, 'max_input_tokens': max_input_tokens,
            'requested_overlap_tokens': overlap_tokens, 'windows': len(windows),
            'total_input_tokens': sum(window['input_tokens'] for window in windows),
            'total_content_tokens': sum(window['content_tokens'] for window in windows),
            'total_overlap_tokens': sum(window['overlap_tokens'] for window in windows),
            'source_characters': len(parent_text), 'source_utf8_bytes': len(raw),
            'exclusive_characters': sum(window['exclusive_end_char']-window['exclusive_start_char'] for window in windows),
            'exclusive_utf8_bytes': sum(window['exclusive_end_byte']-window['exclusive_start_byte'] for window in windows),
            'payload_characters': sum(len(window['text']) for window in windows),
            'source_coverage_complete': True, 'source_reconstructed_exactly': True,
            'tokenizer_calls': calls, 'recount_adjustments': recount_adjustments,
            'overlap_adjustments': overlap_adjustments, 'progress_overlap_drops': progress_overlap_drops,
            'parent_unknown_statistics': parent_statistics,
            'parent_unmapped_source_characters': len(parent_text)-parent_statistics['mapped_token_characters'],
            'unknown_token_tracking_available': unknown_id is not None,
            'encoding_losslessness_verified': False, 'tokenizer_class': type(tokenizer).__name__,
            'whole_source_hash_binding': 'caller_supplied' if source_sha256 else 'not_supplied',
            'absolute_parent_offsets_binding': 'caller_supplied', 'context_in_payload': False,
            'syntax_preservation_verified': False, 'maximal_packing_verified': False,
            'model_loading_performed': False, 'training_admission_performed': False}}
    if aware:
        result['boundary_policy'] = boundary_policy
        result['diagnostics'].update(boundary_candidates=len(candidates),
            boundary_counts=dict(boundary_counts), boundary_skips=dict(boundary_skips),
            boundary_semantics_verified=False)
    return result


__all__ = ['build_token_windows', 'FastOffsetTokenizer', 'TokenWindowError']
