"""Exact source, special-token budgets, overlap recounting, and progress."""
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.token_windows import build_token_windows, TokenWindowError


class CharacterTokenizer:
    is_fast = True
    unk_token_id = 100

    def __init__(self, *, duplicates=1, zeros=0):
        self.duplicates, self.zeros = duplicates, zeros
        self.calls = []

    def __call__(self, text, **kwargs):
        assert kwargs['truncation'] is False
        assert kwargs['padding'] is False
        assert kwargs['add_special_tokens'] is True
        self.calls.append(len(text))
        ids, offsets = [88]*self.zeros, [(0, 0)]*self.zeros
        for i, char in enumerate(text):
            if not char.isspace():
                ids.extend([ord(char)+1000]*self.duplicates)
                offsets.extend([(i, i+1)]*self.duplicates)
        return {'input_ids': [101]+ids+[102], 'offset_mapping': [(0, 0)]+offsets+[(0, 0)],
            'special_tokens_mask': [1]+[0]*len(ids)+[1]}

    def decode(self, *args, **kwargs):
        pytest.fail('source windows must never decode model tokens')


def make(text, tokenizer=None, **kwargs):
    return build_token_windows(text, tokenizer=tokenizer or CharacterTokenizer(),
        source_id='source:fixture', parent_id='parent:fixture', **kwargs)


def assert_contract(text, tokenizer, report, *, char_start=0, byte_start=0):
    windows = report['windows']
    raw = text.encode()
    reconstructed, previous_end, previous_start = [], char_start, char_start-1
    for row in windows:
        start, end = row['start_char']-char_start, row['end_char']-char_start
        exclusive = row['exclusive_start_char']-char_start
        assert row['text'] == text[start:end]
        assert row['text'].encode() == raw[row['start_byte']-byte_start:row['end_byte']-byte_start]
        assert row['exclusive_start_char'] == previous_end
        assert row['start_char'] > previous_start
        assert row['exclusive_end_char'] == row['end_char']
        assert row['overlap_start_char'] == row['start_char']
        assert row['overlap_end_char'] == row['exclusive_start_char']
        assert text[start:exclusive].encode() == raw[row['overlap_start_byte']-byte_start:row['overlap_end_byte']-byte_start]
        assert text[exclusive:end].encode() == raw[row['exclusive_start_byte']-byte_start:row['exclusive_end_byte']-byte_start]
        measured = tokenizer(row['text'], add_special_tokens=True, truncation=False, padding=False,
            return_offsets_mapping=True, return_special_tokens_mask=True)
        assert row['input_tokens'] == len(measured['input_ids']) <= row['max_input_tokens']
        assert row['special_tokens'] == sum(measured['special_tokens_mask'])
        assert row['content_tokens'] == row['input_tokens']-row['special_tokens']
        overlap = tokenizer(text[start:exclusive], add_special_tokens=True, truncation=False, padding=False,
            return_offsets_mapping=True, return_special_tokens_mask=True)
        count = len(overlap['input_ids'])-sum(overlap['special_tokens_mask']) if start < exclusive else 0
        assert row['overlap_tokens'] == count <= row['requested_overlap_tokens']
        assert row['requires_context']
        assert not any(row[key] for key in ('training_eligible', 'proof_authority', 'execution_authority',
            'context_in_payload', 'source_semantics_verified', 'encoding_losslessness_verified', 'truncated'))
        reconstructed.append(row['text'][exclusive-start:])
        previous_end, previous_start = row['end_char'], row['start_char']
    assert ''.join(reconstructed) == text
    assert previous_end == char_start+len(text)
    assert report['diagnostics']['exclusive_characters'] == len(text)
    assert report['diagnostics']['exclusive_utf8_bytes'] == len(raw)
    assert report['diagnostics']['source_coverage_complete']


@pytest.mark.parametrize('text', ['', ' \t\r\n'*50, 'Café 😀.\r\n\tCombine e\u0301.'])
@pytest.mark.parametrize('overlap', [0, 3])
def test_exact_unicode_whitespace_and_empty_source(text, overlap):
    tokenizer = CharacterTokenizer()
    report = make(text, tokenizer, max_input_tokens=12, overlap_tokens=overlap)
    assert_contract(text, tokenizer, report)


@pytest.mark.parametrize('count,expected', [(510, 1), (511, 2), (1020, 2)])
def test_budget_includes_two_specials(count, expected):
    tokenizer = CharacterTokenizer()
    report = make('x'*count, tokenizer, overlap_tokens=0)
    assert len(report['windows']) == expected
    assert report['diagnostics']['content_budget'] == 510
    assert_contract('x'*count, tokenizer, report)


def test_absolute_parent_offsets_and_hashes_stay_distinct():
    prefix, text, suffix = 'é header\n', 'αβγ δ😀ε '*20, '\ntrailer'
    whole = prefix+text+suffix
    digest = hashlib.sha256(whole.encode()).hexdigest()
    tokenizer = CharacterTokenizer()
    report = make(text, tokenizer, parent_start_char=len(prefix), parent_start_byte=len(prefix.encode()),
        source_sha256=digest, max_input_tokens=20, overlap_tokens=4)
    assert report['parent_ref']['source_sha256'] == digest
    assert report['parent_ref']['parent_sha256'] == hashlib.sha256(text.encode()).hexdigest() != digest
    assert_contract(text, tokenizer, report, char_start=len(prefix), byte_start=len(prefix.encode()))
    for row in report['windows']:
        assert row['text'] == whole[row['start_char']:row['end_char']]
        assert 'text' not in row['parent_ref']


@pytest.mark.parametrize('duplicates,zeros', [(2, 0), (1, 2), (2, 2)])
def test_duplicate_and_zero_length_offsets_preserve_source_and_progress(duplicates, zeros):
    tokenizer = CharacterTokenizer(duplicates=duplicates, zeros=zeros)
    text = '😀abcdef '*20
    report = make(text, tokenizer, max_input_tokens=15, overlap_tokens=3)
    assert_contract(text, tokenizer, report)
    assert report['diagnostics']['parent_unknown_statistics']['zero_length_content_offsets'] == zeros


def test_impossible_single_codepoint_budget_raises_not_loops():
    tokenizer = CharacterTokenizer(duplicates=8)
    with pytest.raises(TokenWindowError, match='one source codepoint'):
        make('😀', tokenizer, max_input_tokens=5, overlap_tokens=0)


def test_large_parent_offset_pass_and_bounded_recounts():
    tokenizer = CharacterTokenizer()
    text = 'a'*20000
    report = make(text, tokenizer, max_input_tokens=128, overlap_tokens=16)
    assert tokenizer.calls[0] == len(text)
    assert all(length <= 126 for length in tokenizer.calls[1:])
    assert report['diagnostics']['tokenizer_calls'] <= 1+3*len(report['windows'])
    assert_contract(text, tokenizer, report)


def test_short_parent_remains_single_whole_payload_with_large_requested_overlap():
    tokenizer = CharacterTokenizer()
    report = make('short source', tokenizer, overlap_tokens=64)
    assert len(report['windows']) == 1
    assert report['windows'][0]['whole_parent']
    assert report['windows'][0]['text'] == 'short source'
    assert report['windows'][0]['overlap_tokens'] == 0
    assert report['diagnostics']['tokenizer_calls'] == 1


class UnknownTokenizer(CharacterTokenizer):
    def __call__(self, text, **kwargs):
        if len(text) > 100:
            return {'input_ids': [101, 100, 102], 'offset_mapping': [(0, 0), (0, len(text)), (0, 0)],
                'special_tokens_mask': [1, 0, 1]}
        return super().__call__(text, **kwargs)


def test_long_unk_preserves_source_but_discloses_lossy_encoding():
    text = 'x'*10000
    tokenizer = UnknownTokenizer()
    report = make(text, tokenizer)
    assert len(report['windows']) == 1
    row = report['windows'][0]
    assert row['input_tokens'] == 3
    assert row['unknown_tokens'] == 1
    assert row['unknown_characters'] == row['longest_unknown_span'] == 10000
    assert not row['encoding_losslessness_verified']
    assert_contract(text, tokenizer, report)


@pytest.mark.parametrize('changed', [
    {'offset_mapping': [(0, 0), (0, 999), (0, 0)]},
    {'offset_mapping': [(0, 0), (-1, 0), (0, 0)]},
    {'input_ids': [101, True, 102]},
    {'special_tokens_mask': [1, 0]},
])
def test_invalid_inert_tokenizer_output_rejected(changed):
    class Invalid(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            return {**super().__call__(text, **kwargs), **changed}
    with pytest.raises(TokenWindowError):
        make('x', Invalid())


def test_nonmonotone_offsets_rejected():
    class Invalid(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            return {'input_ids': [101, 200, 201, 102], 'special_tokens_mask': [1, 0, 0, 1],
                'offset_mapping': [(0, 0), (1, 2), (0, 1), (0, 0)]}
    with pytest.raises(TokenWindowError, match='nonmonotone'):
        make('ab', Invalid())


@pytest.mark.parametrize('kwargs', [{'max_input_tokens': 0}, {'max_input_tokens': True},
    {'overlap_tokens': -1}, {'overlap_tokens': 512}, {'parent_start_byte': -1}, {'source_sha256': 'not-a-hash'}])
def test_invalid_configuration_rejected(kwargs):
    with pytest.raises(TokenWindowError):
        make('source', **kwargs)


def test_overlap_cannot_consume_entire_content_capacity():
    with pytest.raises(TokenWindowError, match='no progressing'):
        make('long source', max_input_tokens=6, overlap_tokens=4)


def test_invalid_surrogate_source_rejected_without_normalization():
    tokenizer = CharacterTokenizer()
    with pytest.raises(TokenWindowError, match='UTF-8'):
        make('\ud800', tokenizer)
    assert tokenizer.calls == []


@pytest.fixture(scope='module')
def gte_tokenizer():
    transformers = pytest.importorskip('transformers')
    snapshot = Path.home()/'.cache/huggingface/hub/models--thenlper--gte-small/snapshots/17e1f347d17fe144873b1201da91788898c639cd'
    if not (snapshot/'tokenizer.json').exists():
        pytest.skip('pinned local GTE tokenizer is not installed; no download permitted')
    return transformers.AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False)


@pytest.mark.parametrize('overlap', [0, 64])
def test_real_wordpiece_retokenization_and_overlap_ceiling(gte_tokenizer, overlap):
    text = 'microarchitecturalization '*260
    report = make(text, gte_tokenizer, overlap_tokens=overlap)
    assert len(report['windows']) > 1
    assert_contract(text, gte_tokenizer, report)
    assert all(row['special_tokens'] == 2 for row in report['windows'])
    assert report['diagnostics']['parent_input_tokens'] > 512
    assert all(row['overlap_tokens'] <= overlap for row in report['windows'])


def test_real_64_continuation_pieces_can_retokenize_to_65(gte_tokenizer):
    text = 'microarchitecturalization '*260
    plain = gte_tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    start, end = plain['offset_mapping'][441][0], plain['offset_mapping'][504][1]
    actual = gte_tokenizer(text[start:end], add_special_tokens=False, truncation=False)
    assert len(actual['input_ids']) == 65
    report = make(text, gte_tokenizer, overlap_tokens=64)
    assert_contract(text, gte_tokenizer, report)


@pytest.mark.parametrize('text,content,whitespace', [
    ('x'*1000, 1, False), (' \t\r\n'*2000, 0, True), ('\x00\x01'*100, 0, False),
])
def test_real_unknown_whitespace_and_ignored_controls(gte_tokenizer, text, content, whitespace):
    report = make(text, gte_tokenizer)
    row = report['windows'][0]
    assert len(report['windows']) == 1
    assert row['content_tokens'] == content
    assert row['whitespace_only'] == whitespace
    assert row['zero_content_tokens'] == (content == 0)
    if text.startswith('x'):
        assert row['unknown_tokens'] == 1 and row['longest_unknown_span'] == 1000
    assert_contract(text, gte_tokenizer, report)


def test_real_literal_special_tokens_and_source_gaps_preserved(gte_tokenizer):
    text = '\r\n[CLS] café e\u0301 \x00[SEP]\r\n'*150
    report = make(text, gte_tokenizer, overlap_tokens=64)
    assert_contract(text, gte_tokenizer, report)
    assert all(row['special_tokens'] == 2 for row in report['windows'])
    assert report['diagnostics']['parent_unmapped_source_characters'] > 0


@pytest.mark.parametrize('text,overlap,expected', [
    ('', 0, '66b51755a790e17e7b94f1c501f3b093fd5a608204b83308c6d8575d3bc93add'),
    ('short source', 64, 'b92aed8680a68784fc9445c2a2c7bcde4feb70adeaa02fbf27850422cf174735'),
    ('é😀abcdefgh '*30, 0, '3b08ba97aedeffe6f65bc5e68595a43f4a8a54002a85a2531dabbadb93ac06a5'),
    ('é😀abcdefgh '*30, 4, '6a3e1eb6b0596755047569732c3d2e902ebe2184cd97dbd6b58119c4d9fc8a87'),
])
def test_none_boundary_policy_preserves_entire_frozen_legacy_report(text, overlap, expected):
    # Captured before boundary support: binds legacy IDs, metadata, and counts.
    report = make(text, max_input_tokens=20 if len(text)>20 else 512,
        overlap_tokens=overlap, boundary_candidates=None)
    wire = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    assert hashlib.sha256(wire).hexdigest() == expected


def boundary(offset, kind='sentence', priority=1):
    return {'offset': offset, 'kind': kind, 'priority': priority}


def test_highest_priority_then_rightmost_boundary_and_full_tail():
    text = 'x'*35
    tokenizer = CharacterTokenizer()
    report = make(text, tokenizer, max_input_tokens=22, overlap_tokens=0,
        boundary_candidates=[boundary(10), boundary(19), boundary(12, 'semantic', 2),
            boundary(8, 'statement', 3), boundary(18, 'statement', 3), boundary(30, 'statement', 3)])
    assert [(w['end_char'], w['cut_basis']) for w in report['windows']] == [
        (18, 'preferred_boundary'), (35, 'parent_end')]
    assert report['windows'][0]['cut_kind'] == 'statement'
    assert report['windows'][-1]['cut_kind'] is None
    assert_contract(text, tokenizer, report)


def test_short_structural_unit_is_preserved_but_low_priority_fill_gate_is_explicit():
    text = 'x'*600
    structural = make(text, overlap_tokens=0, boundary_candidates=[boundary(100, 'statement', 3)])
    weak = make(text, overlap_tokens=0, boundary_candidates=[boundary(100, 'semantic', 2)])
    assert [w['content_tokens'] for w in structural['windows']] == [100, 500]
    assert structural['diagnostics']['boundary_counts']['underfilled_structural_cuts'] == 1
    assert structural['boundary_policy']['structural_priority_threshold'] == 3
    assert weak['windows'][0]['end_char'] == 510
    assert weak['windows'][0]['cut_basis'] == 'hard_token_fallback'
    assert weak['diagnostics']['boundary_skips']['before_min_fill_region'] == 1


def test_candidate_prefix_is_recounted_and_overbudget_priority_does_not_win():
    class PrefixExpansion(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            if len(text) == 6:
                return CharacterTokenizer(duplicates=3)(text, **kwargs)
            return super().__call__(text, **kwargs)
    tokenizer = PrefixExpansion()
    text = 'x'*30
    report = make(text, tokenizer, max_input_tokens=12, overlap_tokens=0,
        boundary_candidates=[boundary(6, 'strong', 4), boundary(8, 'statement', 3)])
    assert report['windows'][0]['end_char'] == 8
    assert report['diagnostics']['boundary_skips']['candidate_over_budget'] == 1
    assert_contract(text, tokenizer, report)


def test_retokenized_underfilled_weak_candidate_is_skipped():
    class PrefixCollapse(CharacterTokenizer):
        def __call__(self, text, **kwargs):
            if len(text) == 8:
                return {'input_ids': [101, 100, 102], 'offset_mapping': [(0, 0), (0, 8), (0, 0)],
                    'special_tokens_mask': [1, 0, 1]}
            return super().__call__(text, **kwargs)
    tokenizer = PrefixCollapse()
    text = 'x'*30
    report = make(text, tokenizer, max_input_tokens=12, overlap_tokens=0,
        boundary_candidates=[boundary(8, 'semantic', 2), boundary(6)])
    assert report['windows'][0]['end_char'] == 6
    assert report['diagnostics']['boundary_skips']['candidate_below_min_fill'] == 1
    assert_contract(text, tokenizer, report)


def test_overlap_start_prefers_structure_then_largest_fitting_overlap():
    text = 'x'*70
    tokenizer = CharacterTokenizer()
    rows = [boundary(13), boundary(14, 'statement', 3), boundary(16, 'statement', 3),
        boundary(18, 'statement', 3), boundary(32, 'statement', 3), boundary(50, 'statement', 3)]
    report = make(text, tokenizer, max_input_tokens=22, overlap_tokens=6, boundary_candidates=rows)
    assert report['windows'][0]['end_char'] == 18
    second = report['windows'][1]
    assert second['start_char'] == 14 and second['overlap_tokens'] == 4
    assert second['overlap_kind'] == 'statement' and second['overlap_basis'] == 'preferred_boundary'
    assert second['end_char'] > second['exclusive_start_char'] == 18
    assert_contract(text, tokenizer, report)


def test_overlap_without_fitting_boundary_is_zero_not_an_identifier_cut():
    text = 'x'*70
    report = make(text, max_input_tokens=22, overlap_tokens=6,
        boundary_candidates=[boundary(i, 'statement', 3) for i in (18, 36, 54)])
    assert all(w['overlap_tokens'] == 0 for w in report['windows'])
    assert all(w['overlap_basis'] == 'no_fitting_boundary' for w in report['windows'][1:])
    assert report['diagnostics']['boundary_counts']['overlap_dropped_no_boundary'] == 3
    assert_contract(text, CharacterTokenizer(), report)


def test_empty_candidate_policy_keeps_hard_boundaries_but_has_distinct_identity():
    legacy = make('x'*60, max_input_tokens=22, overlap_tokens=0)
    aware = make('x'*60, max_input_tokens=22, overlap_tokens=0, boundary_candidates=[])
    assert [w['text'] for w in aware['windows']] == [w['text'] for w in legacy['windows']]
    assert all(a['window_id'] != b['window_id'] for a, b in zip(aware['windows'], legacy['windows']))
    assert aware['diagnostics']['boundary_counts']['cut_hard_token_fallback'] == 2
    assert aware['diagnostics']['boundary_skips']['no_candidate_in_safe_payload'] == 2
    assert not aware['diagnostics']['boundary_semantics_verified']


def test_empty_candidates_drop_overlap_while_none_retains_requested_overlap():
    legacy = make('x'*60, max_input_tokens=22, overlap_tokens=6)
    aware = make('x'*60, max_input_tokens=22, overlap_tokens=6, boundary_candidates=[])
    assert legacy['diagnostics']['total_overlap_tokens'] > 0
    assert aware['diagnostics']['total_overlap_tokens'] == 0
    assert aware['diagnostics']['boundary_counts']['overlap_dropped_no_boundary'] == 2
    assert all(w['overlap_basis'] == 'no_fitting_boundary' for w in aware['windows'][1:])


@pytest.mark.parametrize('rows', [True, {}, 'offset', [None], [{'offset': 2}],
    [boundary(-1)], [boundary(7)], [boundary(True)], [boundary(1, '', 1)],
    [boundary(1, 'sentence', 0)], [boundary(1, 'sentence', True)],
    [{**boundary(1), 'unrecognized': 'value'}]])
def test_invalid_boundary_candidates_rejected_before_tokenization(rows):
    tokenizer = CharacterTokenizer()
    with pytest.raises(TokenWindowError, match='boundary'):
        make('source', tokenizer, boundary_candidates=rows)
    assert not tokenizer.calls


@pytest.mark.parametrize('fill', [0, -1, 1.1, float('nan'), float('inf'), True, '0.5'])
def test_invalid_minimum_fill_rejected(fill):
    with pytest.raises(TokenWindowError, match='minimum boundary fill'):
        make('source', boundary_candidates=[], min_boundary_fill=fill)


def test_duplicate_offsets_and_candidate_order_have_canonical_policy_identity():
    rows = [boundary(8, 'b', 3), boundary(8, 'a', 3), boundary(8, 'weak', 1), boundary(18)]
    first = make('x'*25, max_input_tokens=12, overlap_tokens=0, boundary_candidates=rows)
    reordered = make('x'*25, max_input_tokens=12, overlap_tokens=0, boundary_candidates=rows[::-1])
    assert first == reordered
    assert first['windows'][0]['cut_kind'] == 'a'
    assert first['diagnostics']['boundary_candidates'] == 2


def test_aware_unicode_absolute_selectors_and_dense_candidate_recounts_remain_bounded():
    text = '😀abc '*1000
    tokenizer = CharacterTokenizer()
    rows = [boundary(i, 'word', 1) for i, c in enumerate(text) if c == ' ']
    report = make(text, tokenizer, max_input_tokens=128, overlap_tokens=16,
        parent_start_char=7, parent_start_byte=12, boundary_candidates=rows)
    assert tokenizer.calls[0] == len(text)
    assert all(length <= 160 for length in tokenizer.calls[1:])
    assert report['diagnostics']['boundary_counts']['cut_preferred_boundary'] > 0
    assert_contract(text, tokenizer, report, char_start=7, byte_start=12)


def test_real_word_boundaries_align_both_ends_without_breaking_wordpiece_budget(gte_tokenizer):
    text = 'microarchitecturalization '*260
    boundaries = [boundary(i+1, 'word', 1) for i, c in enumerate(text) if c == ' ']
    report = make(text, gte_tokenizer, boundary_candidates=boundaries, overlap_tokens=64)
    assert_contract(text, gte_tokenizer, report)
    for row in report['windows']:
        width = len('microarchitecturalization ')
        assert row['start_char'] % width == 0 and row['end_char'] % width == 0
        assert row['text'].startswith('microarchitecturalization')
    assert all(row['overlap_basis'] == 'preferred_boundary' for row in report['windows'][1:])
    assert all(row['cut_basis'] == 'preferred_boundary' for row in report['windows'][:-1])


def scored_boundary(offset, score):
    return {**boundary(offset, 'semantic_ranked', 2), 'semantic_score': score}


def test_measured_scores_select_weaker_similarity_instead_of_rightmost_cut():
    rows = [scored_boundary(12, .6), scored_boundary(18, .95)]
    plain = [{key: value for key, value in row.items() if key != 'semantic_score'} for row in rows]
    ranked = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=rows)
    unspecified = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=plain)
    assert ranked['windows'][0]['end_char'] == 12
    assert unspecified['windows'][0]['end_char'] == 18
    assert ranked['windows'][0]['cut_semantic_score'] == .6
    assert 'semantic_ranking' in ranked['boundary_policy']
    assert 'semantic_ranking' not in unspecified['boundary_policy']
    assert all('cut_semantic_score' not in row for row in unspecified['windows'])
    assert_contract('x'*35, CharacterTokenizer(), ranked)


def test_score_ties_choose_rightmost_endpoint_and_finite_scores_precede_unscored():
    rows = [scored_boundary(12, .6), scored_boundary(18, .6), boundary(19, 'semantic', 2)]
    report = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=rows)
    assert report['windows'][0]['end_char'] == 18
    assert report['windows'][0]['cut_semantic_score'] == .6


def test_structural_cut_precedes_semantic_scores_and_remains_exempt_from_fill():
    rows = [scored_boundary(12, -1), scored_boundary(18, -.9), boundary(8, 'statement', 3)]
    report = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=rows)
    assert report['windows'][0]['end_char'] == 8
    assert report['windows'][0]['cut_semantic_score'] is None
    assert report['diagnostics']['boundary_counts']['underfilled_structural_cuts'] == 1


@pytest.mark.parametrize('score,expected', [(.1, 15), (.9, 12)])
def test_overlap_uses_lowest_score_then_leftmost_boundary(score, expected):
    rows = [scored_boundary(12, .9), scored_boundary(15, score), boundary(18, 'statement', 3)]
    report = make('x'*50, max_input_tokens=22, overlap_tokens=6, boundary_candidates=rows)
    assert report['windows'][0]['end_char'] == 18
    second = report['windows'][1]
    assert second['start_char'] == expected
    assert second['overlap_semantic_score'] == score
    assert second['overlap_tokens'] == 18-expected <= 6
    assert_contract('x'*50, CharacterTokenizer(), report)


def test_scored_duplicate_candidates_have_canonical_identity_and_best_score():
    rows = [scored_boundary(12, .8), scored_boundary(12, .6), scored_boundary(18, .9)]
    first = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=rows)
    second = make('x'*35, max_input_tokens=22, overlap_tokens=0, boundary_candidates=rows[::-1])
    assert first == second
    assert first['windows'][0]['cut_semantic_score'] == .6


@pytest.mark.parametrize('row', [scored_boundary(3, float('nan')), scored_boundary(3, float('inf')),
    scored_boundary(3, 1.1), scored_boundary(3, -1.1), scored_boundary(3, True),
    scored_boundary(3, None), {**boundary(3, 'statement', 3), 'semantic_score': .5},
    {**boundary(3), 'semantic_score': .5}])
def test_invalid_score_candidates_fail_before_tokenizer(row):
    tokenizer = CharacterTokenizer()
    with pytest.raises(TokenWindowError, match='semantic score'):
        make('abcdef', tokenizer, boundary_candidates=[row])
    assert tokenizer.calls == []


def test_ranked_real_gte_windows_recount_budget_overlap_and_exact_unicode(gte_tokenizer):
    unit = 'Read microarchitecturalization café.\n'
    text = unit*260
    rows = [scored_boundary(len(unit)*i, .55+(i%7)*.05) for i in range(1, 260)]
    report = make(text, gte_tokenizer, boundary_candidates=rows, overlap_tokens=64,
        parent_start_char=7, parent_start_byte=12)
    assert report['diagnostics']['parent_input_tokens'] > 512
    assert_contract(text, gte_tokenizer, report, char_start=7, byte_start=12)
    assert any(row['cut_semantic_score'] is not None for row in report['windows'])
    assert max(row['input_tokens'] for row in report['windows']) <= 512
    assert max(row['overlap_tokens'] for row in report['windows']) <= 64


def test_existing_adjacent_vector_scores_actually_change_final_window_selection():
    from ipfs_datasets_py.ml.embeddings.window_boundaries import prepare_window_boundaries, rank_semantic_boundaries
    text = 'First. Second. Third. Fourth. Fifth.'
    threshold = prepare_window_boundaries(text, embedder=lambda _: [[1., 0.], [1., 0.], [.6, .8], [.6, .8], [1., 0.]],
        embedding_eligible=lambda _: True)
    assert threshold['diagnostics']['semantic_candidates'] == 0
    ranked = rank_semantic_boundaries(threshold)
    common = {'max_input_tokens': 24, 'overlap_tokens': 0}
    old = make(text, boundary_candidates=threshold['candidates'], **common)
    new = make(text, boundary_candidates=ranked['candidates'], **common)
    assert old['windows'][0]['end_char'] == text.index('Fourth')
    assert new['windows'][0]['end_char'] == text.index('Third')
    assert new['windows'][0]['cut_semantic_score'] == pytest.approx(.6)
    assert_contract(text, CharacterTokenizer(), new)
