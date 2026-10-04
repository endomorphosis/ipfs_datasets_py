#!/usr/bin/env python3
"""Author a separate role-span auxiliary curriculum and supplied-boundary panels.

These are author-stipulated flat examples, not reviewed statutory meanings.
The old 4,080-row main inventory is never augmented or rewritten. Oracle inputs
disclose correct supported membership and clause intervals; they are not a
segmentation-label-free evaluation. Current fresh oracle inputs are unavailable
to the fitting loader, and all current fresh meaning references remain sealed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as temporal
from scripts.ops.legal_ir import prepare_legal_atom_boundary_corpus as atom
from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as legacy_runner
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose

prior, mixed, construction = temporal.prior, temporal.mixed, temporal.construction
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(temporal, name) for name in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
FIELDS = temporal.FIELDS
SCHEMA = 'authored-legal-role-span-rehearsal-corpus/v1'
AUTHORITY = 'authored_controlled_example_not_statutory_gold'
COUNTS = {'train': 576, 'tuning': 192, 'fresh': 192, 'document_tuning': 96, 'document_fresh': 96}
FAMILIES = ('caption_presence', 'caption_displacement', 'front_interposed', 'interposed_trailing')
CAPTIONS = ('(2) Filing duty: ', 'Record duty [2]. ', 'Editorial index [section 63001.2]: ')
PREFIXES = {'train': 'Maplerehearsal', 'tuning': 'Birchrehearsal', 'fresh': 'Elmrehearsal',
            'document_tuning': 'Ashrehearsal', 'document_fresh': 'Yewrehearsal'}
PAIR_KEYS = {'pair_id', 'case_group', 'left_id', 'right_id', 'canonical_ir_sha256'}
BLOCK_KEYS = {'block_id', 'pair_ids'}
OCCURRENCE_KEYS = {'id', 'document_id', 'document_source_sha256', 'source_sha256',
                   'char_start', 'char_end', 'occurrence_index'}
SEALED = ('fresh_targets', 'fresh_pairs', 'fresh_document_targets', 'fresh_document_pairs',
          'fresh_oracle_targets', 'annotation_ledger', 'exposure_audit')
EVALUATION_ONLY = ('fresh_oracle_sources', 'fresh_oracle_occurrences', 'fresh_oracle_boundaries', 'fresh_oracle_document_sources')
DEFAULT_LEGACY = prior.ARTIFACTS / 'legal-decoder-scope-retention-20261003/clause-experiment-config.json'
DEFAULT_ATOM = prior.ARTIFACTS / 'legal-decoder-atom-boundary-20261003/corpus-01/manifest.json'
SHUFFLE_SEED = 837241


def digest(value):
    return sha(prior.canonical_bytes(value))


def source_row(row):
    return {'id': row['id'], 'source_text': row['source_text']}


def document_source(row):
    return {k: row[k] for k in ('candidate_id', 'source_text', 'source_sha256')}


def presence_mask(row):
    return sum(1 << bit for bit, field in enumerate(FIELDS[3:]) if row['canonical_ir']['rules'][0][field])


def validate_row(row):
    require(type(row) is dict and set(row) == set(mixed.ROW_KEYS), 'closed seven-key role row required')
    require(row['id'].startswith(('role-', 'oracle-')), 'role or occurrence identity required')
    if row['id'].startswith('role-'):
        require(row['id']=='role-'+sha(row['source_text'].encode()), 'authored identity must commit exact source')
    # The inherited validator's prefix is an inventory rule, not a token rule.
    temporal.validate_row({**row, 'id': 'temporal-presence-validation-' + sha(row['source_text'].encode())[:24]})
    return row


def _profile(family, side, panel):
    C, E, T = 'conditions', 'exceptions', 'temporal'
    profiles = {
        'caption_presence': (((C, E, T), (), (), ()), ((C, E, T), (), (), ())),
        'caption_displacement': (((T, E, C), (), (), ()), ((T, E, C), (), (), ())),
        'front_interposed': (((C, E, T), (), (), ()), ((T,), (C,), (E,), ())),
        'interposed_trailing': (((E,), (T,), (C,), ()), ((), (), (), (C, E, T))),
    }
    if side == 1 and panel in ('tuning', 'document_tuning') and family in FAMILIES[2:]:
        return ((E, T), (), (C,), ()) if family == FAMILIES[2] else ((C,), (E,), (), (T,))
    if side == 1 and panel in ('fresh', 'document_fresh') and family in FAMILIES[2:]:
        return ((C,), (E,), (T,), ()) if family == FAMILIES[2] else ((T,), (), (E,), (C,))
    return profiles[family][side]


def render(panel, case, family, modality, mask, caption, side):
    """Record every role, cue and caption interval at insertion time."""
    require(panel in PREFIXES and type(case) is int and case >= 0 and family in FAMILIES
            and modality in 'OPF' and type(mask) is int and mask in range(8)
            and caption in range(3) and type(side) is int and side in (0, 1), 'bounded rendering factors required')
    entity = PREFIXES[panel] + f'{case:04d}'
    fi = FAMILIES.index(family)
    temporal_kind = ('days', 'hours', 'calendar')[(case + fi + caption) % 3]
    time = {'days': f'within {23 + case % 67} days', 'hours': f'within {37 + case % 59} hours',
            'calendar': f'before {2081 + list(PREFIXES).index(panel)}-04-{1 + case % 28:02d}'}[temporal_kind]
    condition_timing = bool(mask & 1) and not bool(mask & 4) and (case // 24 + caption) % 3 == 0
    condition = (f'the {entity.lower()} application was received within {29 + case % 41} days of publication'
                 if condition_timing else f'the {entity.lower()} permit is active')
    rule = {'modality': modality,
            'actor': f'the {entity} ' + ('Registry', 'Dept. of Records', 'Filing Duty Office', 'Record Duty Authority')[case % 4],
            'action': temporal.VERBS[(case + fi) % len(temporal.VERBS)], 'object': f'the {entity.lower()} filing packet',
            'conditions': [condition] if mask & 1 else [],
            'exceptions': [f'the {entity.lower()} exemption is active'] if mask & 2 else [],
            'temporal': [time] if mask & 4 else []}
    w, notes, cues = prior.CoordinateWriter(), [], []
    def facet(field):
        value = rule[field]; w.add(value[0] if isinstance(value, list) else value, field)
    def note():
        text = CAPTIONS[caption]; start = len(w.text); w.add(text)
        notes.append({'start_char': start, 'end_char': len(w.text), 'source_text': text,
                      'author_stipulated_role': 'nonoperative_editorial_context'})
    def qualifier(field):
        cue = temporal.CONDITION_CUES[(case + side + fi) % 3] if field == 'conditions' else (
            temporal.EXCEPTION_CUES[(case + side + caption) % 3] if field == 'exceptions' else '')
        if panel.startswith('document_') and cue == 'provided that': cue = 'when'
        if cue:
            start = len(w.text); w.add(cue + ' ')
            cues.append({'field': field, 'start_char': start, 'end_char': len(w.text), 'source_text': cue + ' '})
        facet(field)
    front, actor_infix, modal_infix, suffix = _profile(family, side, panel)
    headed = not (family == 'caption_presence' and side == 0)
    heading_first = headed and ((family == 'caption_displacement' and side == 0) or
                               (family == 'interposed_trailing' and side == 1))
    if heading_first: note()
    for field in front:
        if rule[field]: qualifier(field); w.add(', ')
    if headed and not heading_first: note()
    facet('actor')
    for field in actor_infix:
        if rule[field]: w.add(', '); qualifier(field); w.add(',')
    w.add(' '); w.add(temporal.TRIGGERS[modality][side], 'trigger')
    for field in modal_infix:
        if rule[field]: w.add(', '); qualifier(field); w.add(',')
    w.add(' '); facet('action'); w.add(' '); facet('object')
    for field in suffix:
        if rule[field]: w.add(' '); qualifier(field)
    w.add('.')
    row = validate_row({'id': 'role-' + sha(w.text.encode()), 'source_text': w.text,
        'canonical_ir': {'rules': [rule]}, 'trigger_span': w.spans['trigger'],
        'facet_spans': {f: w.spans.get(f) for f in FIELDS}, 'domain': 'new', 'trigger_supervised': True})
    layout = temporal.role_layout(row)
    annotation = {'id': row['id'], 'source_sha256': sha(w.text.encode()), 'panel': panel,
        'case_group': 'case-' + sha(f'role-span/{panel}/{case}'.encode()), 'family': family,
        'side': side, 'caption_style': caption, 'presence_mask': mask, 'editorial_context': notes,
        'qualifier_cues': cues, 'facet_spans': deepcopy(row['facet_spans']), 'trigger_span': list(row['trigger_span']),
        'role_masked_layout': layout, 'layout_sha256': sha(layout.encode()),
        'condition_owned_temporal_language': condition_timing, 'temporal_kind': temporal_kind if mask & 4 else None,
        'annotation_authority': AUTHORITY}
    return row, annotation


def validate_pairs(rows, pairs, expected):
    legacy_runner.validate_pairs(rows, pairs, expected)
    require(len({p['case_group'] for p in pairs}) == expected, 'one meaning pair per unique case required')


def make_panel(panel):
    require(panel in ('train', 'tuning', 'fresh'), 'single panel required')
    rows, annotations, pairs = [], [], []
    captions = range(3) if panel == 'train' else range(1)
    for case, (family, modality, mask, variant) in enumerate(product(FAMILIES, 'OPF', range(8), captions)):
        caption = variant if panel == 'train' else (case + FAMILIES.index(family)) % 3
        items = [render(panel, case, family, modality, mask, caption, side) for side in (0, 1)]
        left, right = (item[0] for item in items); group = items[0][1]['case_group']
        rows.extend((left, right)); annotations.extend(item[1] for item in items)
        pairs.append({'pair_id': group, 'case_group': group, 'left_id': left['id'], 'right_id': right['id'],
                      'canonical_ir_sha256': digest(left['canonical_ir'])})
    validate_pairs(rows, pairs, COUNTS[panel] // 2)
    random.Random(SHUFFLE_SEED + list(PREFIXES).index(panel)).shuffle(rows)
    return rows, annotations, pairs


def make_blocks(rows, pairs, annotations):
    labels = {a['id']: a for a in annotations}; lookup = {}
    for pair in pairs:
        a = labels[pair['left_id']]; rule = next(r['canonical_ir']['rules'][0] for r in rows if r['id'] == pair['left_id'])
        lookup[(a['family'], rule['modality'], a['caption_style'], a['presence_mask'])] = pair['pair_id']
    blocks = []
    for family, modality, caption, mask in product(FAMILIES, 'OPF', range(3), range(4)):
        ids = [lookup[(family, modality, caption, m)] for m in (mask, 7-mask)]
        blocks.append({'block_id': 'block-' + digest(ids), 'pair_ids': ids})
    validate_blocks(rows, pairs, blocks)
    return blocks


def validate_blocks(rows, pairs, blocks):
    require(type(blocks) is list and len(blocks) == 144, '144 auxiliary complement blocks required')
    by_id, pairmap, used = {r['id']: r for r in rows}, {p['pair_id']: p for p in pairs}, set()
    require(len({b['block_id'] for b in blocks}) == 144, 'unique block identities required')
    for block in blocks:
        require(type(block) is dict and set(block) == BLOCK_KEYS and type(block['pair_ids']) is list
                and len(block['pair_ids']) == len(set(block['pair_ids'])) == 2, 'closed two-pair block required')
        require(set(block['pair_ids']) <= set(pairmap) and not used.intersection(block['pair_ids']), 'pair reused or missing in blocks')
        selected = [by_id[pairmap[p][side]] for p in block['pair_ids'] for side in ('left_id', 'right_id')]
        masks = [presence_mask(r) for r in selected]
        require(len({r['id'] for r in selected}) == 4 and masks[0] == masks[1] and masks[2] == masks[3]
                and masks[0] ^ masks[2] == 7, 'block must contain two canonically paired complementary masks')
        require(len({r['canonical_ir']['rules'][0]['modality'] for r in selected}) == 1,
                'block modality must be shared')
        require(all(sum(bool(mask & (1 << bit)) for mask in masks) == 2 for bit in range(3)), 'balanced C/E/T block required')
        used.update(block['pair_ids'])
    require(used == set(pairmap), 'block inventory must exhaust all288 pairs')


def make_documents(panel):
    require(panel in ('document_tuning', 'document_fresh'), 'document panel required')
    rows, annotations, pairs = [], [], []
    for case in range(48):
        count = 2 + case % 2
        local = [render(panel, case*3+i, FAMILIES[(case+i) % 4], 'OPF'[(case+i) % 3],
                        (case+i*3) % 8, (case+i) % 3, (case//4+i) % 2) for i in range(count)]
        if case % 8 == 0: local[-1] = deepcopy(local[0])
        identities = []
        for supported in (True, False):
            text, clauses, coords, attachment = '', [], [], None
            for index, (clause, label) in enumerate(local):
                if index:
                    gap = (' unless ', ' except when ', ' except where ')[case % 3] if not supported and index == 1 else ('\n' if case % 2 else ' ')
                    start = len(text); text += gap
                    if not supported and index == 1:
                        attachment = {'start_char': start, 'end_char': len(text), 'source_text': gap,
                            'parent_occurrence': 0, 'child_occurrence': 1,
                            'declared_relation': 'nested_normative_exception_outside_flat_profile'}
                start = len(text); body = clause['source_text'][:-1]; text += body
                coordinate = {'occurrence_index': index, 'char_start': start, 'char_end': len(text),
                    'facet_spans': {f: [v+start for v in span] if span else None for f,span in clause['facet_spans'].items()},
                    'trigger_span': [v+start for v in clause['trigger_span']],
                    'editorial_context': [{**n, 'start_char': n['start_char']+start, 'end_char': n['end_char']+start} for n in label['editorial_context']],
                    'rule': deepcopy(clause['canonical_ir']['rules'][0]), 'family': label['family'],
                    'presence_mask': label['presence_mask'], 'caption_style': label['caption_style']}
                coords.append(coordinate)
                if supported or index != 0: text += '.'
                if supported: clauses.append({'char_start': start, 'char_end': len(text), 'rule': deepcopy(coordinate['rule'])})
            h = sha(text.encode()); identity = 'document-' + h; identities.append(identity)
            row = {'candidate_id': identity, 'source_text': text, 'source_sha256': h, 'supported': supported,
                'construction': 'role_span_independent' if supported else 'unsupported/nested_normative_exception',
                'repeated_rule_occurrences': supported and len({digest(c['rule']) for c in clauses}) < len(clauses),
                'clauses': clauses, 'unsupported_reason': None if supported else 'nested_normative_exception',
                'label_origin': AUTHORITY}
            construction.validate_document(row)
            annotation = {'candidate_id': identity, 'source_sha256': h, 'panel': panel,
                'case_group': 'case-' + sha(f'role-span/{panel}/{case}'.encode()), 'supported': supported,
                'local_clause_coordinates': coords, 'scope_attachment': attachment, 'annotation_authority': AUTHORITY}
            rows.append(row); annotations.append(annotation)
        pair_id = 'pair-' + sha(f'role-span/{panel}/{case}'.encode())
        pairs.append({'pair_id': pair_id, 'case_group': annotations[-1]['case_group'],
            'independent_id': identities[0], 'nested_id': identities[1],
            'local_clause_body_sha256': [sha(c[0]['source_text'][:-1].encode()) for c in local]})
    random.Random(SHUFFLE_SEED + list(PREFIXES).index(panel)).shuffle(rows)
    return rows, annotations, pairs


def _relative_row(document, clause, coordinate, ordinal):
    start, end = clause['char_start'], clause['char_end']; text = document['source_text'][start:end]
    identity = 'oracle-' + digest([document['candidate_id'], ordinal, start, end, sha(text.encode())])
    row = {'id': identity, 'source_text': text, 'canonical_ir': {'rules': [deepcopy(clause['rule'])]},
        'facet_spans': {f: [v-start for v in span] if span else None for f,span in coordinate['facet_spans'].items()},
        'trigger_span': [v-start for v in coordinate['trigger_span']], 'domain': 'new', 'trigger_supervised': True}
    return validate_row(row)


def validate_document_pairs(rows, pairs, annotations):
    lookup = {r['candidate_id']: r for r in rows}; labels = {a['candidate_id']: a for a in annotations}
    require(len(lookup) == len(rows) == 96 and len(pairs) == 48 and len(labels) == 96,
            'complete document pair/annotation inventory required')
    seen = set()
    for pair in pairs:
        require(set(pair) == {'pair_id','case_group','independent_id','nested_id','local_clause_body_sha256'}, 'closed document contrast metadata required')
        ids = [pair['independent_id'],pair['nested_id']]
        require(len(set(ids)) == 2 and not seen.intersection(ids) and set(ids) <= set(lookup), 'document pair reused or missing')
        left,right = (lookup[i] for i in ids)
        require(left['supported'] is True and right['supported'] is False and right['clauses'] == []
                and right['unsupported_reason'] == 'nested_normative_exception', 'document pair attachment classes differ')
        bodies, rules = [], []
        for row in (left,right):
            a=labels[row['candidate_id']]
            require(a['case_group']==pair['case_group'] and a['supported']==row['supported']
                    and a['source_sha256']==row['source_sha256']==sha(row['source_text'].encode()), 'document pair source annotation differs')
            coordinates=a['local_clause_coordinates']; current=[];current_rules=[]
            require(len(coordinates) in (2,3),'two/three local bodies required')
            for index,c in enumerate(coordinates):
                require(c['occurrence_index']==index,'document local occurrence order differs')
                start,end=c['char_start'],c['char_end'];body=row['source_text'][start:end]
                require(0<=start<end<=len(row['source_text']) and not body.endswith('.'),'body interval excludes terminal period')
                local={'id':'oracle-'+digest([row['candidate_id'],index]),'source_text':body+'.',
                    'canonical_ir':{'rules':[c['rule']]},'facet_spans':{f:[v-start for v in span] if span else None for f,span in c['facet_spans'].items()},
                    'trigger_span':[v-start for v in c['trigger_span']],'domain':'new','trigger_supervised':True}
                validate_row(local);current.append(sha(body.encode()));current_rules.append(c['rule'])
            bodies.append(current);rules.append(current_rules)
        require(bodies[0]==bodies[1]==pair['local_clause_body_sha256'] and rules[0]==rules[1], 'local bodies/meanings changed across scope contrast')
        a=labels[right['candidate_id']];attachment=a['scope_attachment'];first,second=a['local_clause_coordinates'][:2]
        require(attachment and attachment['start_char']==first['char_end'] and attachment['end_char']==second['char_start']
                and right['source_text'][attachment['start_char']:attachment['end_char']]==attachment['source_text']
                and attachment['source_text'] in (' unless ',' except when ',' except where ')
                and attachment['declared_relation']=='nested_normative_exception_outside_flat_profile'
                and labels[left['candidate_id']]['scope_attachment'] is None,'nested attachment provenance differs')
        seen.update(ids)
    require(seen==set(lookup),'document contrast inventory incomplete')


def oracle_pack(documents, annotations):
    """Retain every supported occurrence; plans openly supply scope eligibility."""
    lookup = {a['candidate_id']: a for a in annotations}; sources, targets, occurrences, boundaries = [], [], [], []
    supported_documents = [r for r in documents if r['supported']]
    for document in supported_documents:
        declarations = []
        if document['supported']:
            annotation = lookup[document['candidate_id']]
            coordinates = annotation.get('local_clause_coordinates', annotation.get('clause_coordinates'))
            require(len(coordinates) == len(document['clauses']), 'oracle coordinate coverage differs')
            for ordinal, (clause, coordinate) in enumerate(zip(document['clauses'], coordinates, strict=True)):
                require(coordinate['char_start'] == clause['char_start'] and coordinate['char_end'] in (clause['char_end'], clause['char_end']-1),
                        'oracle interval/annotation differs')
                row = _relative_row(document, clause, coordinate, ordinal); targets.append(row); sources.append(source_row(row))
                record = {'id': row['id'], 'document_id': document['candidate_id'], 'document_source_sha256': document['source_sha256'],
                    'source_sha256': sha(row['source_text'].encode()), 'char_start': clause['char_start'], 'char_end': clause['char_end'], 'occurrence_index': ordinal}
                occurrences.append(record)
                declarations.append({'clause_id': row['id'], 'char_start': clause['char_start'], 'char_end': clause['char_end'], 'scope': deepcopy(compose.FLAT_SCOPE)})
        plan = compose.prepare_source_plan(document_source(document), declarations) if declarations else None
        boundaries.append({'candidate_id': document['candidate_id'], 'source_sha256': document['source_sha256'],
            'status': 'planned' if plan else 'abstained', 'source_plan': plan,
            'supplied_boundary_policy': 'author_supplied_supported_eligibility_and_exact_occurrence_intervals'})
    document_sources = [document_source(r) for r in supported_documents]
    validate_oracle_pack(document_sources, sources, occurrences, boundaries, targets)
    return {'sources': sources, 'targets': targets, 'occurrences': occurrences, 'boundaries': boundaries, 'document_sources': document_sources}


def validate_oracle_pack(documents, sources, occurrences, boundaries, targets=None):
    docs = {r['candidate_id']: r for r in documents}
    require(len(docs) == len(documents) == len(boundaries) and len(sources) == len(occurrences), 'oracle document/occurrence coverage differs')
    require(len({s['id'] for s in sources}) == len(sources) and len({b['candidate_id'] for b in boundaries}) == len(documents), 'duplicate oracle identity')
    grouped = {key: [] for key in docs}
    for source, item in zip(sources, occurrences, strict=True):
        require(set(source) == {'id', 'source_text'} and set(item) == OCCURRENCE_KEYS, 'closed oracle source/occurrence schema required')
        doc = docs[item['document_id']]; start, end = item['char_start'], item['char_end']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(doc['source_text'])
                and item['document_source_sha256'] == doc['source_sha256'] and source['id'] == item['id']
                and source['source_text'] == doc['source_text'][start:end] and item['source_sha256'] == sha(source['source_text'].encode()), 'oracle source/interval/hash differs')
        require(item['id'] == 'oracle-' + digest([item['document_id'], item['occurrence_index'], start, end, item['source_sha256']]), 'oracle identity binding differs')
        grouped[item['document_id']].append(item)
    for boundary in boundaries:
        doc = docs[boundary['candidate_id']]; records = grouped[boundary['candidate_id']]
        require(boundary['source_sha256'] == doc['source_sha256'] and [r['occurrence_index'] for r in records] == list(range(len(records))), 'oracle order/source differs')
        require(bool(records), 'supported-only oracle inventory cannot contain an empty or rejected document')
        if records:
            plan = boundary['source_plan']; compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
            require(boundary['status'] == 'planned' and plan['source'] == document_source(doc)
                    and [c['clause_id'] for c in plan['clauses']] == [r['id'] for r in records]
                    and [(c['char_start'],c['char_end']) for c in plan['clauses']] == [(r['char_start'],r['char_end']) for r in records], 'oracle plan binding differs')
        else: require(boundary['status'] == 'abstained' and boundary['source_plan'] is None, 'empty oracle document must remain explicit')
        if 'supported' in doc: require(bool(records) == doc['supported'], 'oracle membership differs from declared support')
    if targets is not None:
        require([source_row(r) for r in targets] == sources, 'oracle target/source order differs')
        for row in targets: validate_row(row)


def make_panels():
    panels, pairs = {}, {}; ledger = {'schema': 'legal-role-span-rehearsal-annotations/v1', 'single_rows': [], 'document_rows': []}
    for panel in ('train', 'tuning', 'fresh'):
        panels[panel], annotations, pairs[panel] = make_panel(panel); ledger['single_rows'].extend(annotations)
    for panel in ('document_tuning', 'document_fresh'):
        panels[panel], annotations, pairs[panel] = make_documents(panel); ledger['document_rows'].extend(annotations)
    blocks = make_blocks(panels['train'], pairs['train'], [a for a in ledger['single_rows'] if a['panel'] == 'train'])
    validate_panels(panels, pairs, blocks, ledger)
    return panels, pairs, blocks, ledger


def validate_panels(panels, pairs, blocks, ledger):
    require({p: len(rows) for p,rows in panels.items()} == COUNTS, 'closed corpus denominators differ')
    annotations = {a['id']: a for a in ledger['single_rows']}; seen_sources, seen_meanings, seen_cases = set(), set(), set()
    for panel in ('train', 'tuning', 'fresh'):
        rows = panels[panel]; validate_pairs(rows, pairs[panel], COUNTS[panel]//2)
        sources = {prior.normalized_source(r['source_text']) for r in rows}; meanings = {digest(r['canonical_ir']) for r in rows}; cases = {p['case_group'] for p in pairs[panel]}
        require(len(sources) == len(rows) and len(meanings) == len(cases) == len(rows)//2
                and not (sources & seen_sources or meanings & seen_meanings or cases & seen_cases), 'single source/meaning/case isolation differs')
        require(Counter((r['canonical_ir']['rules'][0]['modality'], presence_mask(r)) for r in rows)
                == {(m,mask): len(rows)//24 for m in 'OPF' for mask in range(8)}, 'all modality by eight mask cells must balance')
        for row in rows:
            validate_row(row); a = annotations[row['id']]
            require(a['source_sha256'] == sha(row['source_text'].encode()) and a['panel'] == panel
                    and a['facet_spans'] == row['facet_spans'] and a['trigger_span'] == row['trigger_span']
                    and a['presence_mask'] == presence_mask(row) and a['role_masked_layout'] == temporal.role_layout(row), 'annotation coordinate/layout binding differs')
            for note in a['editorial_context']:
                start,end = note['start_char'],note['end_char']
                require(row['source_text'][start:end] == note['source_text'] and note['source_text'] in CAPTIONS
                        and all(span is None or span[1] <= start or span[0] >= end for span in row['facet_spans'].values()), 'caption/atom attachment overlap')
        seen_sources |= sources; seen_meanings |= meanings; seen_cases |= cases
    validate_blocks(panels['train'], pairs['train'], blocks)
    for panel in ('document_tuning','document_fresh'):
        rows = panels[panel]; labels = [a for a in ledger['document_rows'] if a['panel'] == panel]
        validate_document_pairs(rows,pairs[panel],labels)
        require(Counter(r['supported'] for r in rows) == {True:48,False:48}
                and Counter(len(r['clauses']) for r in rows if r['supported']) == {2:24,3:24}, 'document support/occurrence balance differs')
        pack = oracle_pack(rows, labels); cases = {a['case_group'] for a in labels}
        require(len(cases) == 48 and not cases & seen_cases and len(pack['targets']) == 120, 'independent document cases/occurrences required')
        sources = {prior.normalized_source(r['source_text']) for r in rows + pack['targets']}; meanings = {digest(r['canonical_ir']) for r in pack['targets']}
        require(not sources & seen_sources and not meanings & seen_meanings, 'document clause split leak')
        seen_sources |= sources; seen_meanings |= meanings; seen_cases |= cases
    return {'cross_split_source_overlap': 0, 'cross_split_meaning_overlap': 0, 'cross_split_case_overlap': 0,
        'case_groups': len(seen_cases), 'shared_grammar': True, 'all_layouts_novel_claimed': False,
        'structural_absence_collapses_are_reported': True}


def deduplicate_runtime_tuning(panels):
    """Runtime validation dedup only; occurrence-scored inventories stay intact."""
    rows, grouped = [], {}
    for panel, inventory in panels.items():
        for row in inventory:
            text = row['source_text']; binding = {k: row[k] for k in ('canonical_ir','facet_spans','trigger_span','domain','trigger_supervised')}
            if text in grouped:
                require(grouped[text]['binding'] == binding, 'same source has conflicting oracle/tuning labels')
            else:
                grouped[text] = {'binding': binding, 'representative_id': row['id'], 'occurrences': []}; rows.append(row)
            grouped[text]['occurrences'].append({'panel': panel, 'id': row['id']})
    require(len({r['id'] for r in rows}) == len(rows), 'runtime representative IDs collide')
    provenance = [{'source_sha256': sha(text.encode()), 'representative_id': v['representative_id'],
                   'occurrences': v['occurrences']} for text,v in grouped.items()]
    return rows, provenance


def historical_inputs(legacy_path, atom_path):
    legacy = legacy_runner.load_config(legacy_path); atom_manifest = read_ref(file_ref(atom_path))
    condition_manifest = legacy['manifest']; condition_targets = read_ref(condition_manifest['artifacts']['challenge_targets'])
    condition_docs = read_ref(condition_manifest['artifacts']['document_challenge_targets'])
    condition_ledger = read_ref(condition_manifest['artifacts']['annotation_ledger'])
    atom_docs = {name: read_ref(atom_manifest['artifacts'][key]) for name,key in (('old_tuning','tuning_targets'),('old_fresh','fresh_targets'))}
    atom_ledger = read_ref(atom_manifest['artifacts']['annotation_ledger'])
    old_docs = {'atom_tuning':atom_docs['old_tuning'], 'atom_fresh':atom_docs['old_fresh'], 'prior_condition':condition_docs}
    old_labels = {'atom_tuning':atom_ledger['document_rows'], 'atom_fresh':atom_ledger['document_rows'], 'prior_condition':condition_ledger['document_rows']}
    packs = {p: oracle_pack(rows, old_labels[p]) for p,rows in old_docs.items()}
    require(len(legacy['training']) == 4080 and len({r['source_text'] for r in legacy['training']}) == 4080, 'unchanged main4080 required')
    return legacy, atom_manifest, condition_targets, old_docs, packs


def exposure_inventory(legacy, atom_manifest, condition_targets, old_docs, packs):
    # Every ancestry source is already released. Full document inventories are
    # exclusions; only unambiguous recorded atoms contribute layout evidence.
    _, pools, excluded, refs, source_refs, real_count = temporal.historical_inputs(temporal.DEFAULT_PRIOR)
    pools.update(main_training=legacy['training'], **{'legacy_tuning_'+k:v for k,v in legacy['tuning'].items()},
                 **{'legacy_retention_'+k:v for k,v in legacy['retention_targets'].items()}, prior_condition=condition_targets,
                 **{'oracle_'+k:v['targets'] for k,v in packs.items()})
    for name, pin in atom_manifest['retention_target_references'].items():
        rows = read_ref(pin); excluded.update(r['source_text'] for r in rows)
        pools['old_document_'+name] = construction.document_clauses_for_audit(rows)
        refs['old_document_'+name] = {'reference':pin,'representation':'document_clauses'}
    for rows in legacy['sources'].values(): excluded.update(r['source_text'] for r in rows)
    for rows in legacy['document_sources'].values(): excluded.update(r['source_text'] for r in rows)
    for rows in old_docs.values(): excluded.update(r['source_text'] for r in rows)
    for rows in pools.values(): excluded.update(r['source_text'] for r in rows)
    return pools, excluded, refs, source_refs, real_count


def freeze(output, legacy_path=DEFAULT_LEGACY, atom_path=DEFAULT_ATOM):
    output = Path(output).resolve(); require(not output.exists(), 'new output directory required')
    legacy, old_atom, condition_targets, old_docs, old_packs = historical_inputs(legacy_path, atom_path)
    panels,pairs,blocks,ledger = make_panels(); split_audit = validate_panels(panels,pairs,blocks,ledger)
    new_packs = {p: oracle_pack(panels[p], [a for a in ledger['document_rows'] if a['panel'] == p])
                 for p in ('document_tuning','document_fresh')}
    pools,excluded,old_refs,source_refs,real_count = exposure_inventory(legacy,old_atom,condition_targets,old_docs,old_packs)
    checked = [r['source_text'] for rows in panels.values() for r in rows] + [r['source_text'] for pack in new_packs.values() for r in pack['targets']]
    normalized = {prior.normalized_source(s) for s in excluded}
    require(not {prior.normalized_source(s) for s in checked} & normalized, 'new source or oracle clause overlaps history')
    output.mkdir(parents=True, exist_ok=False); artifacts = {}
    def save(key, value, sealed=False):
        artifacts[key] = write_new(output / (key.replace('_','-') + ('.sealed.json' if sealed else '.json')), value)
    for key,panel in (('aux_rows','train'),('new_tuning','tuning'),('fresh_targets','fresh'),
                      ('document_tuning','document_tuning'),('fresh_document_targets','document_fresh')):
        save(key,panels[panel],key in SEALED)
    for key,panel in (('aux_pairs','train'),('tuning_pairs','tuning'),('fresh_pairs','fresh'),
                      ('document_tuning_pairs','document_tuning'),('fresh_document_pairs','document_fresh')):
        save(key,pairs[panel],key in SEALED)
    save('aux_blocks',blocks)
    save('fresh_sources',[source_row(r) for r in panels['fresh']])
    save('document_tuning_sources',[document_source(r) for r in panels['document_tuning']])
    save('fresh_document_sources',[document_source(r) for r in panels['document_fresh']])
    save('training_annotation_ledger',{'schema':ledger['schema'],'single_rows':[a for a in ledger['single_rows'] if a['panel']=='train'],'document_rows':[]})
    save('tuning_annotation_ledger',{'schema':ledger['schema'],'single_rows':[a for a in ledger['single_rows'] if a['panel']=='tuning'],
                                     'document_rows':[a for a in ledger['document_rows'] if a['panel']=='document_tuning']})
    save('annotation_ledger',ledger,True)
    admitted = {'new':new_packs['document_tuning'],**old_packs}
    for kind in ('sources','targets','occurrences','boundaries','document_sources'):
        save('oracle_'+kind,{p:v[kind] for p,v in admitted.items()})
        save('fresh_oracle_'+kind,new_packs['document_fresh'][kind],kind=='targets')
    pools.update(new_auxiliary=panels['train'],new_tuning=panels['tuning'],new_document_tuning=new_packs['document_tuning']['targets'])
    layouts = {p:{temporal.role_layout(r) for r in rows} for p,rows in pools.items()}
    evidence = []
    for panel,rows in (('single',panels['fresh']),('oracle_document',new_packs['document_fresh']['targets'])):
        for row in rows:
            layout = temporal.role_layout(row); matches = sorted(p for p,values in layouts.items() if layout in values)
            evidence.append({'id':row['id'],'panel':panel,'source_sha256':sha(row['source_text'].encode()),'role_masked_layout':layout,
                'matching_pools':matches,'layout_status':'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_auxiliary': 'new_auxiliary' in matches})
    exposure = {'schema':'legal-role-span-rehearsal-exposure/v1','rows':evidence,'known_pool_counts':{p:len(v) for p,v in pools.items()},
        'known_role_masked_layouts':{p:sorted(v) for p,v in layouts.items()},'historical_document_references':old_refs,
        'historical_source_references':source_refs,'real_exposed_views':real_count,'prior_source_hashes_sha256':digest(sorted(sha(s.encode()) for s in normalized)),
        'split_audit':split_audit,'new_source_overlap':0,'all_layouts_novel_claimed':False,
        'claim':'Shared cue grammar and some collapsed/matched layouts; report actual local combinations rather than universal novelty.'}
    save('exposure_audit',exposure,True)
    plan = write_new(output/'plan.json',{'schema':SCHEMA,'counts':COUNTS,'main_training_rows':4080,'auxiliary_rows':576,'auxiliary_pairs':288,'auxiliary_blocks':144,
        'families':list(FAMILIES),'caption_styles':list(CAPTIONS),'optional_masks_crossed_modalities':True,
        'block_balance':'Two pairs with masks m and7-m: two present/two absent rows per C/E/T.',
        'document_scope':'48 independent positives and48 nested-exception guards per panel;24 each two/three-rule positives;120 supported occurrences.',
        'provided_that_policy':'Single clauses only; supported document condition cue replaced by when.',
        'condition_timing_policy':'Whole opaque applicability atom; no nested temporal or broader logic-family claim.',
        'oracle_assistance':'Exact supported eligibility and occurrence intervals supplied; never segmentation-label-free.',
        'fresh_oracle_inputs_unavailable_to_fitting':True,'author_stipulated_meanings_not_statutory_gold':True,
        'all_layouts_novel_claimed':False,'old_atom_and_condition_fresh_are_exposed_retention':True})
    manifest = {'schema':SCHEMA,'frozen_before_training':True,'generator':file_ref(__file__),
        'dependencies':{k:file_ref(v.__file__) for k,v in (('temporal',temporal),('atom',atom),('legacy_runner',legacy_runner),('coordinates',prior),('mixed',mixed),('composition',compose),('construction',construction))},
        'inputs':{'legacy_config':file_ref(legacy_path),'prior_atom_corpus':file_ref(atom_path)},
        'artifacts':artifacts,'plan':plan,'counts':COUNTS,'main_training_rows':4080,'main_training_sha256':digest(legacy['training']),
        'sealed_artifacts':list(SEALED),'evaluation_only_artifacts':list(EVALUATION_ONLY),
        'oracle_admitted_occurrences':{p:len(v['targets']) for p,v in admitted.items()},'fresh_oracle_occurrences':120,
        'source_semantics_verified':False,'training_performed':False,'training_qualified_as_statutory_gold':False,
        'split_audit':split_audit}
    return write_new(output/'manifest.json',manifest)


def _manifest(path):
    m = read_ref(file_ref(path))
    require(m['schema']==SCHEMA and m['frozen_before_training'] is True and m['counts']==COUNTS
            and m['sealed_artifacts']==list(SEALED) and m['evaluation_only_artifacts']==list(EVALUATION_ONLY), 'frozen role-span corpus required')
    verify_ref(m['generator'])
    for pin in list(m['dependencies'].values())+list(m['inputs'].values()): verify_ref(pin)
    return m


def load_training_inputs(manifest_path):
    """No current fresh meanings, layouts, oracle boundaries or oracle membership."""
    m = _manifest(manifest_path); a=m['artifacts']
    legacy,old_atom,condition_targets,old_docs,old_packs=historical_inputs(m['inputs']['legacy_config']['path'],m['inputs']['prior_atom_corpus']['path'])
    require(digest(legacy['training'])==m['main_training_sha256'] and m['main_training_rows']==4080,'main training binding differs')
    train,tune=read_ref(a['aux_rows']),read_ref(a['new_tuning']); pairs,tpairs=read_ref(a['aux_pairs']),read_ref(a['tuning_pairs']);blocks=read_ref(a['aux_blocks'])
    validate_pairs(train,pairs,288);validate_pairs(tune,tpairs,96);validate_blocks(train,pairs,blocks)
    for row in train+tune:validate_row(row)
    docs=read_ref(a['document_tuning']);fresh=read_ref(a['fresh_sources']);freshdocs=read_ref(a['fresh_document_sources'])
    require(len(docs)==len(freshdocs)==96 and len(fresh)==192 and [document_source(r) for r in docs]==read_ref(a['document_tuning_sources']),'source denominators or tuning order differ')
    for row in docs:construction.validate_document(row)
    require(all(set(r)=={'id','source_text'} and r['id']=='role-'+sha(r['source_text'].encode()) for r in fresh),'closed opaque single source pack required')
    require(all(set(r)==construction.SOURCE_KEYS and r['candidate_id']=='document-'+sha(r['source_text'].encode())
                and r['source_sha256']==sha(r['source_text'].encode()) for r in freshdocs),'closed opaque document source pack required')
    oracle={kind:read_ref(a['oracle_'+kind]) for kind in ('sources','targets','occurrences','boundaries','document_sources')}
    all_docs={'new':docs,**old_docs}
    for panel,rows in all_docs.items():
        require(oracle['document_sources'][panel]==[document_source(r) for r in rows if r['supported']], 'oracle supported source membership differs')
        validate_oracle_pack(oracle['document_sources'][panel],oracle['sources'][panel],oracle['occurrences'][panel],oracle['boundaries'][panel],oracle['targets'][panel])
        if panel!='new':require(all(oracle[k][panel]==old_packs[panel][k] for k in oracle),'admitted oracle ancestry differs')
    tuning_ledger=read_ref(a['tuning_annotation_ledger']);newpack=oracle_pack(docs,tuning_ledger['document_rows'])
    validate_document_pairs(docs,read_ref(a['document_tuning_pairs']),tuning_ledger['document_rows'])
    require(all(oracle[k]['new']==newpack[k] for k in oracle),'new tuning oracle/coordinate binding differs')
    singlepanels={**{'legacy_'+k:v for k,v in legacy['tuning'].items()},**{'retention_'+k:v for k,v in legacy['retention_targets'].items()},
                  'prior_condition':condition_targets,'new':tune,**{'oracle_'+k:v for k,v in oracle['targets'].items()}}
    runtime_tuning,provenance=deduplicate_runtime_tuning(singlepanels)
    maintexts={r['source_text'] for r in legacy['training']};auxtexts={r['source_text'] for r in train};tunetexts={r['source_text'] for r in runtime_tuning}
    require(len(auxtexts)==576 and not maintexts&auxtexts and not (maintexts|auxtexts)&tunetexts,'main/auxiliary/tuning source overlap')
    challenge_texts=[r['source_text'] for r in fresh+freshdocs]
    require(len(set(challenge_texts))==288 and not set(challenge_texts)&(maintexts|auxtexts|tunetexts),
            'fresh source panels duplicate or overlap admitted clause inputs')
    return {'manifest':m,'legacy':legacy,'aux_rows':train,'aux_pairs':pairs,'aux_blocks':blocks,'new_tuning':tune,'tuning_pairs':tpairs,
        'fresh_sources':fresh,'document_tuning':docs,'fresh_document_sources':freshdocs,
        'atom_documents':{'old_tuning':old_docs['atom_tuning'],'old_fresh':old_docs['atom_fresh']},
        'prior_condition_targets':condition_targets,'prior_condition_documents':old_docs['prior_condition'],
        **{'oracle_'+k:v for k,v in oracle.items()},'runtime_tuning':runtime_tuning,'runtime_tuning_provenance':provenance,
        'training_annotation_ledger':read_ref(a['training_annotation_ledger']),'tuning_annotation_ledger':tuning_ledger}


def load_evaluation_sources(manifest_path):
    """Call after fitting: supplied segmentation/scope, without canonical labels."""
    m=_manifest(manifest_path);a=m['artifacts']
    fresh=read_ref(a['fresh_sources']);docs=read_ref(a['fresh_document_sources'])
    pack={k:read_ref(a['fresh_oracle_'+k]) for k in ('sources','occurrences','boundaries','document_sources')}
    require(len(pack['document_sources'])==48 and all(r in docs for r in pack['document_sources']), 'fresh supported oracle inventory differs')
    validate_oracle_pack(pack['document_sources'],pack['sources'],pack['occurrences'],pack['boundaries'])
    require(len(docs)==96 and len(fresh)==192 and len(pack['sources'])==120,'fresh oracle/source denominator differs')
    return {'fresh_sources':fresh,'fresh_document_sources':docs,**{'oracle_'+k:v for k,v in pack.items()},
            'assistance':'Oracle supplied boundaries and supported eligibility, not inferred segmentation.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    parser.add_argument('--legacy-config',default=str(DEFAULT_LEGACY));parser.add_argument('--prior-atom-manifest',default=str(DEFAULT_ATOM))
    args=parser.parse_args();print(json.dumps(freeze(args.output,args.legacy_config,args.prior_atom_manifest),sort_keys=True))
