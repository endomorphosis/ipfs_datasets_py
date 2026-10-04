#!/usr/bin/env python3
"""Author balanced qualifier-retention supervision and sealed composition tests.

All meanings are stipulated controlled examples, never statutory gold. Grammar,
core role/action vocabulary, and some layouts deliberately recur across splits;
case entities, exact sources, and canonical meanings do not. Preparation records
actual layout exposure without treating citation numbers as construction novelty.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_role_curriculum as previous

consistency = previous.previous
boundary_corpus = consistency.boundary_corpus
construction = consistency.previous
mixed, prior, documents = consistency.mixed, consistency.prior, consistency.documents
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(previous, name) for name in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
SCHEMA = 'authored-legal-facet-retention-corpus/v1'
FIELDS = previous.FIELDS
FAMILIES = ('front_exception', 'postmodal_condition', 'condition_exception_front',
    'exception_condition_mixed', 'numbered_heading', 'movable_dates', 'extent_framing', 'editorial_reference')
COUNTS = {'train': 768, 'tuning': 192, 'fresh': 192, 'document_tuning': 96, 'document_fresh': 96}
SINGLE_COUNTS = {k: COUNTS[k] for k in ('train', 'tuning', 'fresh')}
PER_MODAL_FAMILY = {'train': 16, 'tuning': 4, 'fresh': 4}
PREFIXES = {'train': 'Willowcrest', 'tuning': 'Hazelcrest', 'fresh': 'Maplecrest',
    'document_tuning': 'Cedarcrest', 'document_fresh': 'Laurelcrest'}
VERBS = ('retain', 'inspect', 'archive', 'review', 'publish', 'submit', 'record', 'transfer')
ROLE_NOUNS = ('Records Office', 'Dept. of Records', 'Registry', 'Public Register Authority')
CONDITION_CUES = ('if', 'when', 'provided that')
EXCEPTION_CUES = ('unless', 'except when', 'except where')
TRIGGERS = {'O': ('shall', 'must'), 'P': ('may', 'is permitted to'), 'F': ('must not', 'may not')}
TRIGGER_MEANINGS = {cue: modality for modality, cues in TRIGGERS.items() for cue in cues}
GUARDS = construction.GUARDS
SOURCE_KEYS = construction.SOURCE_KEYS
SEALED = ('challenge_targets', 'challenge_pairs', 'document_challenge_targets', 'annotation_ledger', 'exposure_audit')
DEFAULT_PRIOR = prior.ARTIFACTS / 'legal-decoder-context-routing-20261003/corpus-01/manifest.json'
DEFAULT_CONFIG = prior.ARTIFACTS / 'legal-decoder-context-routing-20261003/role-experiment-config.json'


def validate_row(row):
    require(type(row) is dict and set(row) == set(mixed.ROW_KEYS) and row['domain'] == 'new'
            and row['trigger_supervised'] is True, 'closed authored coordinate row required')
    text = row['source_text']
    require(type(text) is str and bool(text) and type(row['id']) is str,
            'authored source and identity required')
    require(row['id'].startswith('facet-') and row['id'].endswith('-' + sha(text.encode())[:24]),
            'authored identity must commit exact source text')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as runtime
    rule = runtime.span.codec_module._rule(row['canonical_ir'])
    tokens = runtime.span.tokenize_source(text)
    trigger = runtime._span_indices(row['trigger_span'], tokens, text, 'trigger')
    require(TRIGGER_MEANINGS.get(text[slice(*row['trigger_span'])]) == rule['modality'],
            'trigger differs from explicitly authored force')
    require(type(row['facet_spans']) is dict and set(row['facet_spans']) == set(FIELDS), 'closed authored facets required')
    occupied = set(range(trigger[0], trigger[1] + 1))
    for field in FIELDS:
        value = rule[field]
        if field in FIELDS[3:]:
            require(type(value) is list and len(value) <= 1, 'at most one qualifier atom')
            value = value[0] if value else None
        span = row['facet_spans'][field]
        if value is None:
            require(span is None, 'absent qualifier requires null span'); continue
        left, right = runtime._span_indices(span, tokens, text, field)
        positions = set(range(left, right + 1))
        require(text[slice(*span)] == value and not occupied & positions, 'authored role/trigger coordinates differ or overlap')
        occupied |= positions
    return row


def validate_pairs(rows, pairs, expected_pairs):
    require(type(rows) is list and type(pairs) is list and all(type(p) is dict for p in pairs),
            'closed row/pair inventories required')
    consistency.validate_pairs(rows, pairs, expected_pairs)
    require(all(p['case_group'] == p['pair_id'] for p in pairs)
            and len({p['case_group'] for p in pairs}) == expected_pairs, 'one pair per authored case required')


def _mask(panel, family_index, local):
    if panel == 'train': return local % 8
    parity = family_index % 2
    if panel == 'fresh': parity = 1 - parity
    return ((0, 3, 4, 7), (1, 2, 5, 6))[parity][local]


def values(panel, family, modality_index, local, clause=0):
    require(panel in PREFIXES and family in FAMILIES and modality_index in range(3), 'known authored panel/family/modal required')
    fi = FAMILIES.index(family)
    if panel in SINGLE_COUNTS:
        require(local in range(PER_MODAL_FAMILY[panel]), 'bounded single case index required')
        ordinal = (fi * 3 + modality_index) * PER_MODAL_FAMILY[panel] + local
        mask = _mask(panel, fi, local)
    else:
        require(local in range(96) and clause in range(3), 'bounded document case/clause required')
        ordinal = local * 3 + clause
        mask = (local + clause * 3) % 8
    name = PREFIXES[panel] + f'{ordinal:03d}'
    condition = (('to the maximum extent practicable', 'to the extent reasonably practicable')[ordinal % 2]
        if family == 'extent_framing' else f'the {name.lower()} permit is active')
    return {'ordinal': ordinal, 'mask': mask, 'modality': ('O', 'P', 'F')[modality_index],
        'actor': f'the {name} {ROLE_NOUNS[ordinal % len(ROLE_NOUNS)]}',
        'action': VERBS[(ordinal // 3 + fi) % len(VERBS)], 'object': f'the {name.lower()} filing packet',
        'conditions': condition, 'exceptions': f'the {name.lower()} exemption is active',
        'temporal': (f'before {2031 + list(PREFIXES).index(panel) * 2}-02-{1 + ordinal % 28:02d}'
                     if family == 'movable_dates' else f'within {17 + ordinal % 79} days'),
        'present': {f for bit, f in enumerate(FIELDS[3:]) if mask & (1 << bit)},
        'citation': f'{31001 + ordinal}.2', 'case_group': f'facet-{panel}-case-{ordinal:03d}'}


def _placement(family, side, panel):
    # Each tuple describes qualifier positions: before actor, after actor,
    # after modal, and after object. Every qualifier is inserted once if present.
    C, E, T = 'conditions', 'exceptions', 'temporal'
    profiles = {
        'front_exception': (((E,), (), (), (T, C)), ((), (), (E,), (T, C))),
        'postmodal_condition': (((), (), (C,), (T, E)), ((C,), (), (), (T, E))),
        'condition_exception_front': (((C, E), (), (), (T,)), ((C,), (), (E,), (T,))),
        'exception_condition_mixed': (((E,), (), (), (T, C)), ((C,), (), (E,), (T,))),
        'numbered_heading': (((C,), (), (), (T, E)), ((E,), (C,), (), (T,))),
        'movable_dates': (((T,), (), (), (C, E)), ((), (), (T,), (C, E))),
        'extent_framing': (((C,), (), (), (T, E)), ((E,), (), (C,), (T,))),
        'editorial_reference': (((), (), (C,), (T, E)), ((E,), (), (T,), (C,))),
    }
    if side == 1 and panel in ('fresh', 'document_fresh'):
        # Individually trained positions/cues, combined in fresh orders.
        return (((T,), (E,), (C,), ()) if FAMILIES.index(family) % 2 == 0
                else ((T, E), (), (C,), ()))
    if side == 1 and panel in ('tuning', 'document_tuning'):
        return (((C, T), (), (E,), ()) if FAMILIES.index(family) % 2 == 0
                else ((E,), (T,), (), (C,)))
    return profiles[family][side]


def role_layout(row):
    # Reuse the historical literal-role masker, then normalize every authored
    # modal spelling including may-not. No predicted spans enter this audit.
    layout = mixed.skeleton(row)
    for cue in sorted(set(prior.TRIGGER_MEANINGS) | set(TRIGGER_MEANINGS), key=len, reverse=True):
        layout = re.sub(r'\b' + re.escape(cue) + r'\b', '<modal>', layout)
    return layout.rstrip('.;')


def render(panel, family, modality_index, local, side, clause=0):
    require(type(side) is int and side in (0, 1), 'two authored pair sides required')
    value = values(panel, family, modality_index, local, clause)
    writer, editorial, cue_spans = prior.CoordinateWriter(), [], []
    fi = FAMILIES.index(family)
    ccue = CONDITION_CUES[(fi + value['mask'] + side) % 3]
    if panel.startswith('document_') and ccue == 'provided that': ccue = 'when'
    ecue = EXCEPTION_CUES[(fi + value['mask'] + side) % 3]
    cue = TRIGGERS[value['modality']][side]
    def add(text): writer.add(text)
    def field(name): writer.add(value[name], name)
    def note(text):
        start = len(writer.text); add(text)
        editorial.append({'start_char': start, 'end_char': len(writer.text), 'source_text': text,
                          'author_stipulated_role': 'nonoperative_editorial_context'})
    def qualifier(name, capital=False):
        if name == 'conditions': text = '' if family == 'extent_framing' else ccue + ' '
        elif name == 'exceptions': text = ecue + ' '
        else: text = ''
        if capital and text: text = text[0].upper() + text[1:]
        if text:
            start = len(writer.text); add(text)
            cue_spans.append({'field': name, 'start_char': start, 'end_char': len(writer.text), 'source_text': text})
        field(name)
    if family == 'numbered_heading': note(('(a) Filing duty.— ', 'Record duty [1]. ')[side])
    if family == 'editorial_reference':
        note(('Editorial cross-reference: section {n}. ', 'Editorial index [section {n}]: ')[side].format(n=value['citation']))
    front, after_actor, after_modal, suffix = _placement(family, side, panel)
    for name in front:
        if name in value['present']: qualifier(name, not writer.text); add(', ')
    field('actor')
    for name in after_actor:
        if name in value['present']: add(', '); qualifier(name); add(',')
    add(' '); writer.add(cue, 'trigger')
    for name in after_modal:
        if name in value['present']: add(', '); qualifier(name); add(',')
    add(' '); field('action'); add(' '); field('object')
    for name in suffix:
        if name in value['present']: add(' '); qualifier(name)
    add('.')
    rule = {'modality': value['modality'], **{name: value[name] for name in FIELDS[:3]},
        **{name: [value[name]] if name in value['present'] else [] for name in FIELDS[3:]}}
    row = validate_row({'id': f'facet-{panel}-' + sha(writer.text.encode())[:24], 'source_text': writer.text,
        'canonical_ir': {'rules': [rule]}, 'trigger_span': writer.spans['trigger'],
        'facet_spans': {name: writer.spans.get(name) for name in FIELDS}, 'domain': 'new', 'trigger_supervised': True})
    layout = role_layout(row)
    annotation = {'id': row['id'], 'source_sha256': sha(writer.text.encode()), 'panel': panel, 'family': family,
        'case_group': value['case_group'], 'meaning_group': value['case_group'], 'side': side,
        'template_id': f'facet-{panel}-{family}-{side}', 'template': layout, 'template_fingerprint': sha(layout.encode()),
        'presence_mask': value['mask'], 'editorial_context': editorial, 'qualifier_cues': cue_spans,
        'facet_spans': row['facet_spans'], 'trigger_span': row['trigger_span'],
        'annotation_authority': 'authored_controlled_example_not_statutory_gold',
        'scope': {'conditions': 'all_activate_at_evaluation_origin', 'exceptions': 'any_waives_at_evaluation_origin',
            'temporal': 'explicit_authored_closed_duration_or_before_calendar_date', 'rule_count': 1}}
    return row, annotation


def make_panel(panel):
    require(panel in SINGLE_COUNTS, 'single panel required')
    rows, annotations, pairs = [], [], []
    for family in FAMILIES:
        for modality in range(3):
            for local in range(PER_MODAL_FAMILY[panel]):
                pair = [render(panel, family, modality, local, side) for side in (0, 1)]
                left, right = (item[0] for item in pair)
                rows.extend((left, right)); annotations.extend(item[1] for item in pair)
                pairs.append({'pair_id': pair[0][1]['case_group'], 'case_group': pair[0][1]['case_group'],
                    'left_id': left['id'], 'right_id': right['id'],
                    'canonical_ir_sha256': sha(prior.canonical_bytes(left['canonical_ir']))})
    validate_pairs(rows, pairs, SINGLE_COUNTS[panel] // 2)
    return rows, annotations, pairs


def document_source(row):
    return {key: row[key] for key in ('candidate_id', 'source_text', 'source_sha256')}


def authored_document(panel, ordinal):
    require(panel in ('document_tuning', 'document_fresh') and ordinal in range(96), 'bounded document panel required')
    supported = ordinal < 72
    count = 1 + ordinal // 24 if supported else 2
    family = FAMILIES[ordinal % 8]
    rendered = [render(panel, FAMILIES[(ordinal + i) % 8], (ordinal + i) % 3, ordinal,
                       (ordinal // 8 + i) % 2, i) for i in range(count)]
    repeated = supported and ordinal in (*range(24, 30), *range(48, 54))
    if repeated: rendered[-1] = deepcopy(rendered[0])
    chunks, clauses, coordinates, cursor = [], [], [], 0
    for index, (row, annotation) in enumerate(rendered):
        text = row['source_text']
        if index < count - 1 and ordinal % 3 == 0: text = text[:-1] + ';'
        gap = ('\n' if ordinal % 2 == 0 else ' ') if index else ''
        cursor += len(gap); chunks.append(gap + text)
        clauses.append({'char_start': cursor, 'char_end': cursor + len(text), 'rule': row['canonical_ir']['rules'][0]})
        coords = {'clause_index': index, 'char_start': cursor, 'char_end': cursor + len(text),
            'facet_spans': {f: [x + cursor for x in span] if span else None for f, span in row['facet_spans'].items()},
            'trigger_span': [x + cursor for x in row['trigger_span']], 'family': annotation['family'],
            'presence_mask': annotation['presence_mask'], 'side': annotation['side'],
            'meaning_group': annotation['meaning_group'], 'editorial_context': [
                {**note, 'start_char': note['start_char'] + cursor, 'end_char': note['end_char'] + cursor}
                for note in annotation['editorial_context']]}
        coordinates.append(coords); cursor += len(text)
    text, reason = ''.join(chunks), None
    if not supported:
        reason = GUARDS[(ordinal - 72) % 3]
        first, second = (item[0]['source_text'] for item in rendered)
        if reason == 'shared_condition_prefix': text = 'Both following rules share the same condition: ' + first + ' ' + second
        elif reason == 'coordinated_action': text = first[:-1] + ' and publish the retained archive.'
        else: text = first[:-1] + ' unless ' + second
        clauses, coordinates, repeated = [], [], False
    row = {'candidate_id': f'facet-{panel}-{ordinal:03d}', 'source_text': text, 'source_sha256': sha(text.encode()),
        'supported': supported, 'construction': family if supported else 'unsupported/' + reason,
        'repeated_rule_occurrences': repeated, 'clauses': clauses, 'unsupported_reason': reason,
        'label_origin': 'new_authored_restricted_flat_profile_not_legal_authority'}
    annotation = {'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'], 'panel': panel,
        'case_group': f'facet-{panel}-case-{ordinal:03d}', 'family': family, 'supported': supported,
        'guard': reason, 'clause_coordinates': coordinates, 'clause_occurrences': len(clauses),
        'unique_rules': len({sha(prior.canonical_bytes(c['rule'])) for c in clauses})}
    validate_document(row, annotation)
    return row, annotation


def document_clause_rows(rows, annotations):
    by_id = {a['candidate_id']: a for a in annotations}
    result = []
    for row in rows:
        for index, coords in enumerate(by_id[row['candidate_id']]['clause_coordinates']):
            start, end = coords['char_start'], coords['char_end']; text = row['source_text'][start:end]
            result.append({'id': f"{row['candidate_id']}-occurrence-{index}-" + sha(text.encode())[:24],
                'source_text': text, 'canonical_ir': {'rules': [row['clauses'][index]['rule']]},
                'facet_spans': {f: [x - start for x in span] if span else None for f, span in coords['facet_spans'].items()},
                'trigger_span': [x - start for x in coords['trigger_span']], 'domain': 'new', 'trigger_supervised': True})
    return result


def validate_document(row, annotation=None):
    construction.validate_document(row)  # no historical cue-meaning assumptions
    if annotation is None: return
    require(annotation['candidate_id'] == row['candidate_id'] and annotation['source_sha256'] == row['source_sha256']
            and annotation['supported'] == row['supported'], 'document annotation source binding differs')
    require(len(annotation['clause_coordinates']) == len(row['clauses']) == annotation['clause_occurrences'],
            'document occurrence count differs')
    unique = len({sha(prior.canonical_bytes(c['rule'])) for c in row['clauses']})
    require(unique == annotation['unique_rules'] and row['repeated_rule_occurrences'] == (unique < len(row['clauses'])),
            'repeated occurrence versus unique rule accounting differs')
    for index, (clause, coordinate) in enumerate(zip(row['clauses'], annotation['clause_coordinates'], strict=True)):
        require(coordinate['clause_index'] == index and all(coordinate[k] == clause[k] for k in ('char_start', 'char_end')),
                'document coordinates differ')
    for local in document_clause_rows([row], [annotation]): validate_row(local)


def make_panels():
    panels, pairs, ledger = {}, {}, {'schema': 'authored-legal-facet-retention-annotations/v1', 'single_rows': [], 'document_rows': []}
    for panel in SINGLE_COUNTS:
        panels[panel], annotations, pairs[panel] = make_panel(panel); ledger['single_rows'].extend(annotations)
    for panel in ('document_tuning', 'document_fresh'):
        result = [authored_document(panel, index) for index in range(96)]
        panels[panel] = [item[0] for item in result]; ledger['document_rows'].extend(item[1] for item in result)
    validate_panels(panels, pairs, ledger)
    return panels, pairs, ledger


def validate_panels(panels, pairs, ledger):
    require({k: len(v) for k, v in panels.items()} == COUNTS, 'authored panel denominators differ')
    annotations = {a['id']: a for a in ledger['single_rows']}
    require(len(annotations) == len(ledger['single_rows']) == sum(SINGLE_COUNTS.values()), 'single annotation coverage differs')
    seen_sources, seen_meanings, seen_cases = set(), set(), set()
    for panel, count in SINGLE_COUNTS.items():
        rows = panels[panel]; validate_pairs(rows, pairs[panel], count // 2)
        source_set = {prior.normalized_source(r['source_text']) for r in rows}
        meanings = {sha(prior.canonical_bytes(r['canonical_ir'])) for r in rows}
        cases = {p['case_group'] for p in pairs[panel]}
        require(len(source_set) == count and len(meanings) == count // 2
                and not (source_set & seen_sources or meanings & seen_meanings or cases & seen_cases),
                'authored source/meaning/case overlap')
        expected = {(m, mask): count // 24 for m in 'OPF' for mask in range(8)}
        actual = Counter()
        for row in rows:
            validate_row(row); a = annotations[row['id']]; rule = row['canonical_ir']['rules'][0]
            mask = sum(1 << bit for bit, f in enumerate(FIELDS[3:]) if rule[f]); actual[(rule['modality'], mask)] += 1
            require(a['panel'] == panel and a['source_sha256'] == sha(row['source_text'].encode())
                    and a['facet_spans'] == row['facet_spans'] and a['trigger_span'] == row['trigger_span']
                    and a['presence_mask'] == mask and a['template'] == role_layout(row)
                    and a['template_fingerprint'] == sha(a['template'].encode()), 'single annotation source/coordinate binding differs')
        require(actual == expected, 'exact modality by all8 optional-mask balance required')
        require(Counter(annotations[r['id']]['family'] for r in rows) == {f: count // 8 for f in FAMILIES}, 'family balance differs')
        for p in pairs[panel]:
            left, right = annotations[p['left_id']], annotations[p['right_id']]
            require(left['case_group'] == right['case_group'] == p['case_group']
                    and left['meaning_group'] == right['meaning_group'] == p['pair_id']
                    and (left['side'], right['side']) == (0, 1), 'pair annotation lineage differs')
        seen_sources |= source_set; seen_meanings |= meanings; seen_cases |= cases
    doc_annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    require(len(doc_annotations) == len(ledger['document_rows']) == 192, 'document annotation coverage differs')
    for panel in ('document_tuning', 'document_fresh'):
        rows = panels[panel]
        require(Counter(r['supported'] for r in rows) == {True: 72, False: 24}, 'document support balance differs')
        require(Counter(len(r['clauses']) for r in rows if r['supported']) == {1: 24, 2: 24, 3: 24}, 'document occurrence balance differs')
        require(sum(r['repeated_rule_occurrences'] for r in rows) == 12, 'repeated-rule case count differs')
        require(Counter(r['unsupported_reason'] for r in rows if not r['supported']) == {g: 8 for g in GUARDS}, 'guard balance differs')
        local_texts, local_meanings = set(), set()
        for row in rows:
            a = doc_annotations[row['candidate_id']]; validate_document(row, a)
            text = prior.normalized_source(row['source_text'])
            require(a['panel'] == panel and a['case_group'] not in seen_cases and text not in seen_sources, 'document source/case overlap')
            seen_cases.add(a['case_group']); local_texts.add(text)
            for clause in row['clauses']:
                source = prior.normalized_source(row['source_text'][clause['char_start']:clause['char_end']])
                meaning = sha(prior.canonical_bytes({'rules': [clause['rule']]}))
                require(source not in seen_sources and meaning not in seen_meanings, 'document clause repeats another panel')
                local_texts.add(source); local_meanings.add(meaning)
        seen_sources |= local_texts; seen_meanings |= local_meanings
    return {'unique_normalized_sources_including_document_clauses': len(seen_sources),
            'canonical_meanings_including_document_clauses': len(seen_meanings), 'case_groups': len(seen_cases),
            'cross_split_source_overlap': 0, 'cross_split_meaning_overlap': 0, 'cross_split_case_overlap': 0,
            'layout_policy': 'Shared grammar and some matched layouts are intentional; exposure audit reports actual matches and unmatched combinations.',
            'lexical_policy': 'Split-specific entity names; shared core role/action vocabulary, qualifier cues, modal cues, headings and editorial framing.'}


def historical_inputs(prior_manifest_path):
    """Preparation-only inventory of released historical labels and source refs."""
    old = previous.load_training_inputs(prior_manifest_path); rm = old['manifest']
    cm = read_ref(rm['inputs']['prior_corpus'])
    _, _, _, pools, excluded, refs = consistency.historical_inputs(cm['inputs']['boundary_corpus']['path'])
    for prefix, manifest in (('consistency', cm), ('role', rm)):
        for split, key in (('train', 'new_training'), ('tuning', 'new_tuning'), ('exposed_fresh', 'challenge_targets')):
            name = prefix + '_' + split; pools[name] = read_ref(manifest['artifacts'][key])
            refs[name] = {'reference': manifest['artifacts'][key], 'representation': 'annotated_single'}
    docref = cm['artifacts']['document_challenge_targets']; rows = read_ref(docref)
    pools['consistency_exposed_document_clauses'] = construction.document_clauses_for_audit(rows)
    refs['consistency_exposed_document_clauses'] = {'reference': docref, 'representation': 'document_clauses'}
    excluded.update(row['source_text'] for row in rows)
    # Include exact real sources and every historical source panel without parsing
    # them into supervision or discarding duplicate document identities.
    from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as real
    real_manifest = read_ref(rm['inputs']['real_source_manifest'])
    real_sources = real.validate_manifest(real_manifest)
    excluded.update(r['source_text'] for r in real_sources)
    config = read_ref(rm['inputs']['prior_config']); source_refs = []
    for key, reference in config.items():
        if key.endswith('_sources'):
            value = read_ref(reference); rows = value['challenge'] if type(value) is dict and 'challenge' in value else value
            excluded.update(r['source_text'] for r in rows); source_refs.append(reference)
    for rows in pools.values(): excluded.update(r['source_text'] for r in rows)
    return old, pools, excluded, refs, source_refs, len(real_sources)


def freeze(output, prior_manifest_path=DEFAULT_PRIOR, prior_config_path=DEFAULT_CONFIG):
    output = Path(output).resolve(); require(not output.exists(), 'output already exists')
    config = json.loads(Path(prior_config_path).read_bytes())
    require(config['corpus_manifest'] == file_ref(prior_manifest_path), 'prior role config/corpus binding differs')
    old, known, excluded, pool_refs, source_refs, real_count = historical_inputs(prior_manifest_path)
    panels, pairs, ledger = make_panels(); split_audit = validate_panels(panels, pairs, ledger)
    normalized_excluded = {prior.normalized_source(s) for s in excluded}
    checked = []
    for panel, rows in panels.items():
        checked.extend(row['source_text'] for row in rows)
        if panel.startswith('document_'):
            checked.extend(row['source_text'][c['char_start']:c['char_end']] for row in rows for c in row['clauses'])
    require(not {prior.normalized_source(s) for s in checked} & normalized_excluded, 'new source/clause repeats admitted or exposed source')
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        'new_training': write_new(output / 'new-training.json', panels['train']),
        'training_pairs': write_new(output / 'training-pairs.json', pairs['train']),
        'new_tuning': write_new(output / 'new-tuning.json', panels['tuning']),
        'tuning_pairs': write_new(output / 'tuning-pairs.json', pairs['tuning']),
        'document_tuning_sources': write_new(output / 'document-tuning-sources.json', [document_source(r) for r in panels['document_tuning']]),
        'document_tuning_targets': write_new(output / 'document-tuning-targets.json', panels['document_tuning']),
        'challenge_sources': write_new(output / 'challenge-sources.json', [{k: r[k] for k in ('id', 'source_text')} for r in panels['fresh']]),
        'challenge_targets': write_new(output / 'challenge-targets.sealed.json', panels['fresh']),
        'challenge_pairs': write_new(output / 'challenge-pairs.sealed.json', pairs['fresh']),
        'document_challenge_sources': write_new(output / 'document-challenge-sources.json', [document_source(r) for r in panels['document_fresh']]),
        'document_challenge_targets': write_new(output / 'document-challenge-targets.sealed.json', panels['document_fresh']),
        'annotation_ledger': write_new(output / 'annotation-ledger.sealed.json', ledger)}
    for panel, key in (('train', 'new_training'), ('tuning', 'new_tuning')):
        known['new_facet_' + panel] = panels[panel]
        pool_refs['new_facet_' + panel] = {'reference': artifacts[key], 'representation': 'annotated_single'}
    known['new_facet_document_tuning'] = document_clause_rows(panels['document_tuning'], ledger['document_rows'])
    pool_refs['new_facet_document_tuning'] = {'reference': artifacts['document_tuning_targets'], 'representation': 'document_clauses'}
    layouts = {name: {role_layout(r) for r in rows} for name, rows in known.items()}
    by_id = {a['id']: a for a in ledger['single_rows']}
    evidence = {'single_rows': [], 'document_clause_rows': []}
    for kind, rows in (('single_rows', panels['fresh']), ('document_clause_rows', document_clause_rows(panels['document_fresh'], ledger['document_rows']))):
        for row in rows:
            layout = role_layout(row); matches = sorted(name for name, values in layouts.items() if layout in values)
            item = {'id': row['id'], 'source_sha256': sha(row['source_text'].encode()), 'role_masked_layout': layout,
                'matching_pools': matches, 'layout_status': 'matched_local_layout' if matches else 'unmatched_local_combination',
                'matched_new_training': 'new_facet_train' in matches}
            if kind == 'single_rows': item.update(case_group=by_id[row['id']]['case_group'], family=by_id[row['id']]['family'], side=by_id[row['id']]['side'])
            evidence[kind].append(item)
    cue_evidence = {cue: [a['id'] for a in ledger['single_rows'] if a['panel'] == 'train' and any(
        q['source_text'].strip().casefold() == cue for q in a['qualifier_cues'])] for cue in CONDITION_CUES + EXCEPTION_CUES}
    require(all(cue_evidence.values()), 'all condition/exception cue variants need explicit training exposure')
    exposure = {'schema': 'authored-legal-facet-retention-exposure/v1', **evidence, 'known_pool_references': pool_refs,
        'known_pool_counts': {k: len(v) for k, v in known.items()},
        'known_role_masked_layouts': {k: sorted(v) for k, v in layouts.items()},
        'cue_training_rows': cue_evidence, 'prior_unique_normalized_sources': len(normalized_excluded),
        'prior_inventory_sha256': sha(prior.canonical_bytes(sorted(sha(s.encode()) for s in normalized_excluded))),
        'prior_source_inputs': source_refs, 'real_exposed_views': real_count, 'new_overlap_count': 0,
        'split_audit': split_audit,
        'claim': 'Shared grammar and mixed matched-layout controls/unmatched local combinations. No universal or pretraining novelty claim.',
        'guard_wrapper_novelty_claimed': False}
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.sealed.json', exposure)
    plan = write_new(output / 'plan.json', {'schema': SCHEMA, 'counts': COUNTS, 'families': list(FAMILIES),
        'all8_masks_crossed_modalities_balanced': True, 'all_basic_condition_exception_cues_trained': True,
        'label_origin': 'new authored controlled examples; no statute or cached compiler labels',
        'may_not_semantics': 'prohibition by explicit author stipulation',
        'editorial_policy': 'marked headings/cross-references are nonoperative by author stipulation; not a rule for real statutes',
        'document_policy': 'flat independent rules; 24 each one/two/three occurrences, 12 repeated-rule cases, 8 each prior guard type per panel',
        'provided_that_policy': 'trained in single clauses; excluded from supported documents because frozen boundary policy rejects it',
        'split_policy': split_audit, 'fresh_targets_sealed_until_generation_and_build_freeze': True})
    manifest = {'schema': SCHEMA, 'frozen_before_training': True, 'plan': plan, 'generator': file_ref(__file__),
        'dependencies': {name: file_ref(module.__file__) for name, module in (
            ('previous_role', previous), ('consistency', consistency), ('boundary_corpus', boundary_corpus),
            ('construction', construction), ('mixed_corpus', mixed), ('coordinates', prior), ('documents', documents))},
        'inputs': {'prior_corpus': file_ref(prior_manifest_path), 'prior_config': file_ref(prior_config_path)},
        'artifacts': artifacts, 'counts': COUNTS,
        'split_audit': split_audit, 'sealed_artifacts': list(SEALED), 'source_semantics_verified': False,
        'training_qualified_as_statutory_gold': False, 'training_performed': False,
        'sealing_scope': 'loader reads training pairs, tuning and historical replay only; fresh sources contain no labels, pairs or layout evidence'}
    return write_new(output / 'manifest.json', manifest)


def load_training_inputs(manifest_path):
    """Load allowed supervision and source-only challenges; no sealed bytes."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    require(manifest.get('schema') == SCHEMA and manifest.get('frozen_before_training') is True, 'frozen facet corpus required')
    require(manifest.get('counts') == COUNTS and manifest.get('sealed_artifacts') == list(SEALED), 'frozen denominators or seal declarations differ')
    verify_ref(manifest['generator'])
    for reference in manifest['dependencies'].values(): verify_ref(reference)
    for reference in manifest['inputs'].values(): verify_ref(reference)
    old = previous.load_training_inputs(manifest['inputs']['prior_corpus']['path'])
    a = manifest['artifacts']; train, tune = read_ref(a['new_training']), read_ref(a['new_tuning'])
    pairs, tune_pairs = read_ref(a['training_pairs']), read_ref(a['tuning_pairs'])
    validate_pairs(train, pairs, 384); validate_pairs(tune, tune_pairs, 96)
    for row in train + tune: validate_row(row)
    fresh, docs = read_ref(a['challenge_sources']), read_ref(a['document_challenge_sources'])
    dtune, dtune_sources = read_ref(a['document_tuning_targets']), read_ref(a['document_tuning_sources'])
    require(len(fresh) == 192 and len(docs) == len(dtune) == len(dtune_sources) == 96, 'source panel denominators differ')
    require(all(set(r) == {'id', 'source_text'} and r['id'] == 'facet-fresh-' + sha(r['source_text'].encode())[:24] for r in fresh), 'closed fresh single sources required')
    require(all(set(r) == SOURCE_KEYS and r['source_sha256'] == sha(r['source_text'].encode()) for r in docs + dtune_sources), 'closed document source schema/hash required')
    require([document_source(r) for r in dtune] == dtune_sources, 'document tuning labels/source inventory differs')
    for row in dtune: validate_document(row)
    require(Counter(r['supported'] for r in dtune) == {True: 72, False: 24}, 'document tuning support denominator differs')
    allrows = train + tune + fresh + docs + dtune_sources
    sources = [prior.normalized_source(r['source_text']) for r in allrows]
    ids = [r.get('id', r.get('candidate_id')) for r in allrows]
    require(len(set(sources)) == len(sources) and len(set(ids)) == len(ids), 'new source panels duplicate or overlap')
    replay = {**old['replay'], 'prior_role': old['new_train']}
    tuning = {**old['tuning'], 'prior_role': old['new_tuning']}
    historical_sources = {prior.normalized_source(r['source_text']) for pool in list(replay.values()) + list(tuning.values()) for r in pool}
    require(not set(sources) & historical_sources, 'new source panels overlap historical admitted supervision')
    return {'manifest': manifest, 'new_train': train, 'training_pairs': pairs, 'new_tuning': tune, 'tuning_pairs': tune_pairs,
        'replay': replay, 'tuning': tuning, 'fresh_sources': fresh, 'fresh_document_sources': docs, 'document_tuning': dtune}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True); parser.add_argument('--prior-manifest', default=str(DEFAULT_PRIOR))
    parser.add_argument('--prior-config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args(); print(json.dumps(freeze(args.output, args.prior_manifest, args.prior_config), sort_keys=True))
