"""Structural review contracts on explicitly fictional, never-fetched sources."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_context_review as review
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
from scripts.ops.legal_ir import build_legal_context_review_packet as cli


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return review.file_ref(path)


@pytest.fixture
def source(tmp_path):
    # GovInfo-shaped fixture identity only: these authored bytes are not fetched.
    raw = b'''<h3 class="section-head">\xc2\xa73318. Fictional fixture</h3>
<p class="statutory-body">(a) Definitions.\xe2\x80\x94In this section:</p>
<p class="statutory-body-1em">(1) The term "office" means a registered office.</p>
<p class="statutory-body">(b) Except as provided in subsection (c), the office shall file a notice under section 3301 of this title.</p>
<p class="statutory-body">(c) Exceptions.\xe2\x80\x94</p>
<p class="statutory-body-1em">(1) The duty does not apply if a permit has expired.</p>
<p class="source-credit">(Added by a fictional act.)</p>
<h4>Fictional notes</h4><p>A note with legal wording shall be retained.</p>
<p>Second note retained as separate context.</p>'''
    url = 'https://www.govinfo.gov/content/pkg/USCODE-2024-title40/html/USCODE-2024-title40-subtitleII-partA-chap33-sec3318.htm'
    html = tmp_path / 'source.html'
    html.write_bytes(raw)
    document = context.extract_document(raw, url=url, edition=2024, legal_id='usc:us:40:3318')
    doc_ref = write(tmp_path / 'document.json', document)
    rows = [dict(row, document=doc_ref) for row in routing._expected_views(document)]
    source_ref = write(tmp_path / 'sources.json', rows)
    manifest = {'schema': 'legal-official-uscode-diagnostic-manifest/v1',
                'documents': [{'document': doc_ref, 'raw_html': review.file_ref(html)}],
                'sources': source_ref,
                'counts': {'documents': 1, 'views': len(rows), 'distinct_texts': len({s['source_sha256'] for s in rows}),
                           'view_kinds': dict(review.Counter(s['kind'] for s in rows))},
                'implementation': [review.file_ref(context.__file__)],
                'views_are_independent_examples': False, 'source_context_closed': False,
                'statutory_accuracy_available': False, 'training_qualified': False}
    path = tmp_path / 'manifest.json'
    write(path, manifest)
    return path


def make_proposals(packet, kind='exception'):
    d = packet['documents'][0]
    did = d['identity']['document_id']
    def span(p):
        return review.source_span(packet, did, p['paragraph_index'], p['char_start'], p['char_end'])
    edge = {'edge_id': 'authored-proposal-1', 'kind': kind,
            'from_span': span(d['codified_body'][2]), 'to_spans': [span(d['codified_body'][3])],
            'evidence_spans': [span(d['codified_body'][2])],
            'context_document_ids': [did],
            'unresolved_dependency_ids': sorted(r['dependency_id'] for r in d['dependency_inventory']),
            'interpretation_note': 'Authored fixture proposal only; no independent review.',
            'status': 'caller_proposed_unreviewed', 'semantic_verified': False}
    return {'schema': review.PROPOSAL_SCHEMA, 'packet_content_sha256': review.digest(packet), 'edges': [edge]}


def validate(packet, source):
    return review.validate_packet(packet, expected_manifest_ref=review.file_ref(source))


def test_complete_body_notes_and_overlapping_views_preserved(source):
    packet = review.build_packet(source)
    result = validate(packet, source)
    d = packet['documents'][0]
    assert packet['counts'] == {'documents': 1, 'body_paragraphs': 5, 'source_credits': 1,
                                'notes_or_other': 2, 'diagnostic_views': 9, 'distinct_view_texts': 9,
                                'structural_edges': 2, 'dependency_mentions': 4}
    assert d['blocks'][3]['descendant_paragraphs'] == [4]
    assert {e['child_paragraph_index'] for e in d['structural_edges']} == {1, 4}
    assert d['reviewer_records'] == [] and d['adjudication'] is None and d['reference_ir'] is None
    assert d['proposed_attachments'] == []
    assert result['all_paragraphs_and_views_replayed'] and result['gold_targets_created'] == 0
    assert not packet['heldout_accuracy_partition']


@pytest.mark.parametrize('mutation', ['drop_exception', 'drop_descendant', 'drop_notes', 'truncate_block',
                                     'drop_view', 'invent_review', 'invent_ir', 'alter_parent', 'inflate_count'])
def test_complete_source_replay_rejects_omission_or_authority_claim(source, mutation):
    packet = review.build_packet(source)
    d = packet['documents'][0]
    if mutation == 'drop_exception':
        del d['codified_body'][3]
    elif mutation == 'drop_descendant':
        del d['codified_body'][4]
    elif mutation == 'drop_notes':
        d['notes_or_other'].pop()
    elif mutation == 'truncate_block':
        d['blocks'][3]['descendant_paragraphs'] = []
        d['blocks'][3]['char_end'] = d['codified_body'][3]['char_end']
    elif mutation == 'drop_view':
        d['diagnostic_views'].pop()
    elif mutation == 'invent_review':
        d['reviewer_records'] = [{'reviewer_id': 'fabricated'}]
    elif mutation == 'invent_ir':
        d['reference_ir'] = {'rules': []}
    elif mutation == 'alter_parent':
        d['structural_edges'][0]['parent_paragraph_index'] = 3
    else:
        packet['counts']['body_paragraphs'] += 1
    with pytest.raises(ValueError, match='complete pinned source'):
        validate(packet, source)


@pytest.mark.parametrize('kind', review.EDGE_KINDS)
def test_six_attachment_types_are_structurally_valid_but_unreviewed(source, kind):
    packet = review.build_packet(source)
    result = review.validate_attachment_proposals(packet, make_proposals(packet, kind),
                                                 expected_manifest_ref=review.file_ref(source))
    assert result['edge_count'] == 1 and result['source_bindings_verified']
    assert result['semantic_attachments_verified'] is False
    assert result['independent_review_verified'] is False and result['reference_ir'] is None


@pytest.mark.parametrize('mutation', ['stale_edition', 'wrong_3318_heading', 'wrong_3318_url', 'tampered_text',
                                     'repaired_text_hash', 'cross_paragraph_span', 'drop_external',
                                     'drop_local_dependency', 'claim_resolved', 'omit_context',
                                     'duplicate_edge', 'unknown_kind', 'extra_field'])
def test_attachment_rejects_identity_and_dependency_tampering(source, mutation):
    packet = review.build_packet(source)
    proposals = make_proposals(packet)
    e = proposals['edges'][0]
    span = e['from_span']
    if mutation == 'stale_edition': span['edition'] = 2025
    elif mutation == 'wrong_3318_heading': span['section_heading'] = '§3318. Federal building information'
    elif mutation == 'wrong_3318_url': span['source_url'] = span['source_url'].replace('sec3318.htm', 'sec3318-2.htm')
    elif mutation in ('tampered_text', 'repaired_text_hash'):
        span['text'] = 'The office may file.'
        if mutation == 'repaired_text_hash': span['text_sha256'] = context.sha(span['text'])
    elif mutation == 'cross_paragraph_span': span['char_end'] += 2
    elif mutation in ('drop_external', 'drop_local_dependency'):
        kind = 'external_section_or_title' if mutation == 'drop_external' else 'same_section_locator'
        identity = next(r['dependency_id'] for r in packet['documents'][0]['dependency_inventory'] if r['kind'] == kind)
        e['unresolved_dependency_ids'].remove(identity)
    elif mutation == 'claim_resolved': e['semantic_verified'] = True
    elif mutation == 'omit_context': e['context_document_ids'] = []
    elif mutation == 'duplicate_edge': proposals['edges'].append(deepcopy(e))
    elif mutation == 'unknown_kind': e['kind'] = 'proof_of_equivalence'
    else: e['admitted'] = True
    with pytest.raises(ValueError):
        review.validate_attachment_proposals(packet, proposals, expected_manifest_ref=review.file_ref(source))


def test_changed_html_is_rejected_even_if_document_and_packet_not_changed(source):
    packet = review.build_packet(source)
    html = Path(packet['documents'][0]['source_pins']['raw_html']['path'])
    html.write_bytes(html.read_bytes().replace(b'notice', b'noticeX'))
    with pytest.raises(ValueError, match='HTML bytes changed'):
        validate(packet, source)


def test_changed_manifest_cannot_rebase_trusted_input_pin(source):
    packet = review.build_packet(source)
    trusted = review.file_ref(source)
    data = json.loads(source.read_text())
    data['counts']['views'] -= 1
    write(source, data)
    with pytest.raises(ValueError, match='pinned artifact bytes differ'):
        review.validate_packet(packet, expected_manifest_ref=trusted)


def test_duplicate_document_identity_fails(source):
    data = json.loads(source.read_text())
    data['documents'].append(deepcopy(data['documents'][0]))
    write(source, data)
    with pytest.raises(ValueError, match='duplicate document identity'):
        review.build_packet(source)


def observation_audit(tmp_path, *, duplicate_id=False, choose_ambiguous=False):
    raw_text = 'Préface. Repeat. Repeat.'
    raw = tmp_path / 'raw-section.txt'
    raw.write_text(raw_text)
    occurrences = []
    cursor = 0
    for _ in range(2):
        start = raw_text.index('Repeat.', cursor); end = start + len('Repeat.'); cursor = end
        occurrences.append({'char_start': start, 'char_end': end,
                            'utf8_byte_start': len(raw_text[:start].encode()), 'utf8_byte_end': len(raw_text[:end].encode()),
                            'raw_text_ref': review.file_ref(raw), 'parquet_row_index': 7,
                            'legal_id': 'usc:us:40:3318'})
    rows = [{'source_span_id': 'observation-0' if duplicate_id else f'observation-{i}',
             'source_text': 'Repeat.', 'source_text_sha256': context.sha('Repeat.'),
             'legal_ids': ['usc:us:40:3318'], 'independent_gold': False, 'training_qualified': False,
             'legal_meaning_reference': None, 'exact_occurrences': occurrences, 'occurrence_count': 2,
             'source_occurrence_status': 'ambiguous_exact_occurrences',
             'selected_occurrence': occurrences[0] if choose_ambiguous else None} for i in range(2)]
    rows_ref = write(tmp_path / 'observations.json', rows)
    audit = {'schema': 'legal-uscode-source-context-recovery/v1', 'independent_gold': False,
             'training_qualified': False, 'artifacts': {'observations': rows_ref},
             'counts': {'source_observations': 2, 'occurrence_status': {'ambiguous_exact_occurrences': 2}}}
    path = tmp_path / 'audit.json'; write(path, audit)
    return path


def test_duplicate_text_keeps_separate_observation_ids_and_all_ambiguous_occurrences(source, tmp_path):
    audit = observation_audit(tmp_path)
    packet = review.build_packet(source, observation_audit_path=audit)
    result = review.validate_packet(packet, expected_manifest_ref=review.file_ref(source),
                                    expected_observation_audit_ref=review.file_ref(audit))
    rows = packet['observation_inventory']['rows']
    assert len(rows) == 2 and {r['source_span_id'] for r in rows} == {'observation-0', 'observation-1'}
    assert all(len(r['exact_occurrences']) == 2 and r['selected_occurrence'] is None for r in rows)
    assert all(r['official_coordinate_mapping_verified'] is False for r in rows)
    assert result['training_qualified'] is False


@pytest.mark.parametrize('option', ['duplicate_id', 'choose_ambiguous'])
def test_invalid_observation_identity_or_ambiguous_selection_rejected(source, tmp_path, option):
    audit = observation_audit(tmp_path, **{option: True})
    with pytest.raises(ValueError):
        review.build_packet(source, observation_audit_path=audit)


def test_cli_writes_only_unreviewed_packet_and_refuses_overwrite(source, tmp_path):
    output = tmp_path / 'result'
    summary = review.read_ref(cli.run(source, output))
    assert summary['external_reviews_received'] == summary['gold_targets_created'] == 0
    assert summary['training_executed'] is False and summary['model_inference'] is False
    proposals = review.read_ref(summary['attachment_proposals'])
    assert proposals['edges'] == []
    with pytest.raises(FileExistsError):
        cli.run(source, output)


def test_nonfinite_or_duplicate_json_key_rejected(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        review.read_ref(review.file_ref(p))
    p.write_text('{"a": NaN}')
    with pytest.raises(ValueError, match='nonfinite'):
        review.read_ref(review.file_ref(p))


@pytest.fixture(scope='module')
def official_packet():
    source = Path('/home/barberb/lift_coding/artifacts/legal-decoder-uscode-fidelity-20261003/official-context-02/manifest.json')
    if not source.is_file():
        pytest.skip('optional immutable local official-context02 integration fixture is unavailable')
    assert review.file_ref(source)['sha256'] == '6d22979d7ec8162b19625aca411e3fa94bb2be2b20be6d113ff9f1ae9d3f6bdd'
    packet = review.build_packet(source)
    validate(packet, source)
    return packet, source


@pytest.mark.parametrize('legal_id,body_count,notes_count', [
    ('usc:us:18:4004', 1, 6), ('usc:us:18:3284', 1, 8), ('usc:us:10:7657', 1, 4),
    ('usc:us:40:3318', 14, 2), ('usc:us:10:4873', 42, 11)])
def test_five_real_documents_preserve_regions_without_meaning_claim(official_packet, legal_id, body_count, notes_count):
    packet, _ = official_packet
    d = next(d for d in packet['documents'] if d['identity']['legal_id'] == legal_id)
    assert len(d['codified_body']) == body_count and len(d['notes_or_other']) == notes_count
    assert d['identity']['edition'] == 2024
    assert d['reviewer_records'] == [] and d['reference_ir'] is None
    assert packet['counts']['diagnostic_views'] == 86 and packet['counts']['body_paragraphs'] == 59
    assert packet['counts']['distinct_view_texts'] == 83


def test_real_exception_descendants_applicability_and_external_references_remain_pending(official_packet):
    packet, source = official_packet
    d = next(d for d in packet['documents'] if d['identity']['legal_id'] == 'usc:us:40:3318')
    assert 'Lactation room' in d['identity']['heading']
    block = next(b for b in d['blocks'] if b['subsection_path'] == '(c)')
    assert block['descendant_paragraphs'] == [9, 10, 11, 12]
    altered = deepcopy(packet)
    victim = next(d for d in altered['documents'] if d['identity']['legal_id'] == 'usc:us:40:3318')
    victim['codified_body'] = [p for p in victim['codified_body'] if not (p['subsection_path'] or '').startswith('(c)')]
    with pytest.raises(ValueError): validate(altered, source)
    board = next(d for d in packet['documents'] if d['identity']['legal_id'] == 'usc:us:10:4873')
    assert next(p for p in board['codified_body'] if p['subsection_path'] == '(a)(3)')['char_start'] == 330
    assert next(p for p in board['codified_body'] if p['subsection_path'] == '(e)')['char_start'] == 5377
    external = [r for r in board['dependency_inventory'] if r['text'] == 'section 3573']
    assert len(external) == 1 and not external[0]['locator_resolved'] and not external[0]['semantic_dependency_resolved']


@pytest.mark.parametrize('mutation', ['boolean_count', 'floating_count', 'floating_edition', 'boolean_paragraph'])
def test_packet_replay_is_json_type_strict(source, mutation):
    packet = review.build_packet(source)
    if mutation == 'boolean_count': packet['counts']['documents'] = True
    elif mutation == 'floating_count': packet['counts']['documents'] = 1.0
    elif mutation == 'floating_edition': packet['documents'][0]['identity']['edition'] = 2024.0
    else: packet['documents'][0]['codified_body'][0]['paragraph_index'] = False
    with pytest.raises(ValueError, match='complete pinned source'):
        validate(packet, source)


@pytest.mark.parametrize('index', [False, 0.0])
def test_source_span_rejects_numeric_alias_paragraph_identity(source, index):
    packet = review.build_packet(source)
    did = packet['documents'][0]['identity']['document_id']
    with pytest.raises(ValueError, match='integer paragraph'):
        review.source_span(packet, did, index, 0, 1)


def test_proposed_span_rejects_floating_edition(source):
    packet = review.build_packet(source)
    proposals = make_proposals(packet)
    proposals['edges'][0]['from_span']['edition'] = 2024.0
    with pytest.raises(ValueError, match='source/version/heading/span binding'):
        review.validate_attachment_proposals(packet, proposals, expected_manifest_ref=review.file_ref(source))


def test_overbound_in_memory_packet_fails_before_source_reads(source, monkeypatch):
    packet = review.build_packet(source)
    trusted = review.file_ref(source)
    monkeypatch.setattr(review, 'MAX_BYTES', len(review.wire(packet).encode()) - 1)
    with pytest.raises(ValueError, match='in-memory JSON exceeds'):
        review.validate_packet(packet, expected_manifest_ref=trusted)


def test_overbound_proposal_bundle_fails_before_validation(source, monkeypatch):
    packet = review.build_packet(source)
    proposals = make_proposals(packet)
    trusted = review.file_ref(source)
    limit = len(review.wire(packet).encode()) + 1000
    proposals['edges'][0]['interpretation_note'] = 'x' * limit
    monkeypatch.setattr(review, 'MAX_BYTES', limit)
    with pytest.raises(ValueError, match='in-memory JSON exceeds'):
        review.validate_attachment_proposals(packet, proposals, expected_manifest_ref=trusted)


def test_manifest_count_numeric_alias_rejected(source):
    data = json.loads(source.read_text())
    data['counts']['documents'] = True
    write(source, data)
    with pytest.raises(ValueError, match='denominators'):
        review.build_packet(source)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), {'tuple': (1, 2)}, {1: 'key'}])
def test_wire_requires_finite_json_native_types(value):
    with pytest.raises(ValueError): review.wire(value)
