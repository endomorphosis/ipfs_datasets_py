#!/usr/bin/env python3
"""Freeze contrastive independent/nested scope documents with direct coordinates.

Scope-pair labels intentionally differ. Identical local clause bodies are embedded
in flat independent and unsupported nested-exception contexts. These are authored
profile controls, never reviewed statutory meaning or a nested-logic target.
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
from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as temporal
from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as legacy

boundary, clauses = legacy.boundary, legacy.clauses
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(temporal, name) for name in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
SCHEMA = 'authored-legal-scope-retention-corpus/v1'
COUNTS = {'train': 192, 'tuning': 96, 'fresh': 192}
FAMILIES = ('plain_join', 'numbered_child', 'duration_child', 'heading_duration_child')
PREFIXES = {'train': 'Hemlockscope', 'tuning': 'Cypressscope', 'fresh': 'Redwoodscope'}
FIELDS = temporal.FIELDS
SOURCE_KEYS = {'candidate_id', 'source_text', 'source_sha256'}
ROW_KEYS = SOURCE_KEYS | {'supported', 'construction', 'repeated_rule_occurrences', 'clauses', 'unsupported_reason', 'label_origin'}
PAIR_KEYS = {'pair_id', 'case_group', 'independent_id', 'nested_id', 'local_clause_body_sha256'}
SEALED = ('fresh_targets', 'fresh_pairs', 'annotation_ledger', 'exposure_audit')
DEFAULT_PRIOR = temporal.prior.ARTIFACTS / 'legal-decoder-temporal-presence-20261003/corpus-01/manifest.json'
DEFAULT_BOUNDARY = temporal.prior.ARTIFACTS / 'legal-decoder-boundary-curriculum-20261002/corpus-01/manifest.json'


def source_row(row):
    return {key: row[key] for key in sorted(SOURCE_KEYS)}


def render_local(panel, case, ordinal):
    require(panel in COUNTS and 0 <= case < COUNTS[panel] // 2 and ordinal in (0, 1, 2), 'bounded authored local clause required')
    variants = 8 if panel != 'tuning' else 4
    modality = ('O', 'P', 'F')[(case // (4 * variants) + ordinal) % 3]
    mask = (case // variants) % 4
    variant = case % variants
    family = FAMILIES[variant % 4]
    entity = f'{PREFIXES[panel]}{case:03d}x{ordinal}'
    trigger = {'O': ('shall', 'must'), 'P': ('may', 'is permitted to'), 'F': ('must not', 'may not')}[modality][(case + ordinal) % 2]
    actor = f'the {entity} ' + ('Records Office', 'Dept. of Records', 'Registry')[(case + ordinal) % 3]
    condition = f'the {entity.lower()} permit is active'
    exception = f'the {entity.lower()} exemption is active'
    time_kind = (variant + ordinal) % 4
    time = (None, f'within {18 + case + ordinal} days', f'within {22 + case + ordinal} hours',
            f'before 2047-03-{1 + (case + ordinal) % 27:02d}')[time_kind]
    if ordinal == 1 and family in ('duration_child', 'heading_duration_child') and time is None:
        time = f'within {31 + case} days'
    rule = {'modality': modality, 'actor': actor,
            'action': ('retain', 'inspect', 'archive', 'review', 'publish', 'transfer')[(case + ordinal) % 6],
            'object': f'the {entity.lower()} filing packet',
            'conditions': [condition] if mask & 1 else [],
            'exceptions': [exception] if mask & 2 else [], 'temporal': [time] if time else []}
    writer = temporal.prior.CoordinateWriter()
    editorial, cues = [], []
    if ordinal == 1 and family in ('numbered_child', 'heading_duration_child'):
        heading = ('Record duty [1]. ', '(b) Filing duty.— ')[case % 2]
        editorial.append({'start_char': 0, 'end_char': len(heading), 'source_text': heading,
                          'author_stipulated_role': 'nonoperative_editorial_context'})
        writer.add(heading)
    def facet(name):
        value = rule[name]
        writer.add(value[0] if isinstance(value, list) else value, name)
    def qualifier(name, cue, suffix):
        start = len(writer.text)
        writer.add(cue)
        if cue:
            cues.append({'field': name, 'start_char': start, 'end_char': len(writer.text), 'source_text': cue})
        facet(name); writer.add(suffix)
    # Both matched layouts and held-out combinations are intentional. All cues,
    # individual placements, headings and duration units occur in training.
    fresh_combination = panel == 'fresh' and case % 2 == 1
    front_time = time is not None and (ordinal == 1 or fresh_combination)
    front_condition = bool(rule['conditions']) and (case + ordinal) % 3 == 0
    front_exception = bool(rule['exceptions']) and (case + ordinal) % 3 == 1
    if front_time: qualifier('temporal', '', ', ')
    if front_exception: qualifier('exceptions', 'Unless ', ', ')
    if front_condition: qualifier('conditions', 'When ' if fresh_combination else 'If ', ', ')
    facet('actor'); writer.add(' '); writer.add(trigger, 'trigger')
    post_condition = bool(rule['conditions']) and not front_condition and (case + ordinal) % 2 == 1
    if post_condition: qualifier('conditions', ', when ' if fresh_combination else ', if ', ',')
    writer.add(' '); facet('action'); writer.add(' '); facet('object')
    if time and not front_time: qualifier('temporal', ' ', '')
    if rule['conditions'] and not front_condition and not post_condition: qualifier('conditions', ' when ', '')
    if rule['exceptions'] and not front_exception:
        qualifier('exceptions', (' unless ', ' except when ', ' except where ')[(case + ordinal) % 3], '')
    return {'source_text': writer.text, 'rule': rule, 'facet_spans': {f: writer.spans.get(f) for f in FIELDS},
            'trigger_span': writer.spans['trigger'], 'editorial_context': editorial, 'qualifier_cues': cues, 'family': family}


def make_pair(panel, case):
    variants = 8 if panel != 'tuning' else 4
    count = 2 + ((case // 4 + case // (4 * variants)) % 2)
    local = [render_local(panel, case, i) for i in range(count)]
    repeated = count == 3 and case % 8 == 7
    if repeated: local[2] = deepcopy(local[0])
    family = local[0]['family']
    rows, annotations = [], []
    case_group = f'scope-{panel}-case-{case:03d}'
    for supported in (True, False):
        text, occurrences, declarations, attachment = '', [], [], None
        for index, item in enumerate(local):
            if index:
                if not supported and index == 1:
                    cue = (' unless ', ' except when ', ' except where ')[case % 3]
                    start = len(text); text += cue
                    attachment = {'start_char': start, 'end_char': len(text), 'source_text': cue,
                                  'parent_occurrence': 0, 'child_occurrence': 1,
                                  'declared_relation': 'nested_normative_exception_outside_flat_profile'}
                else:
                    text += '\n' if case % 2 else ' '
            start = len(text); text += item['source_text']; end = len(text)
            occurrence = {'index': index, 'char_start': start, 'char_end': end,
                          'source_text': item['source_text'], 'source_sha256': sha(item['source_text'].encode()),
                          'rule': item['rule'],
                          'facet_spans': {k: [start + x for x in v] if v is not None else None for k, v in item['facet_spans'].items()},
                          'trigger_span': [start + x for x in item['trigger_span']],
                          'editorial_context': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['editorial_context']],
                          'qualifier_cues': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['qualifier_cues']]}
            occurrences.append(occurrence)
            if supported or index != 0:
                text += ';' if supported and index < count - 1 and case % 3 == 0 else '.'
            if supported:
                declarations.append({'char_start': start, 'char_end': len(text), 'rule': deepcopy(item['rule'])})
        side = 'independent' if supported else 'nested'
        candidate_id = f'scope-{panel}-{case:03d}-{side}-' + sha(text.encode())[:16]
        row = {'candidate_id': candidate_id, 'source_text': text, 'source_sha256': sha(text.encode()),
               'supported': supported, 'construction': family if supported else 'unsupported/nested_normative_exception',
               'repeated_rule_occurrences': repeated if supported else False, 'clauses': declarations,
               'unsupported_reason': None if supported else 'nested_normative_exception',
               'label_origin': 'authored_scope_contrast_not_statutory_gold'}
        annotation = {'candidate_id': candidate_id, 'source_sha256': row['source_sha256'], 'panel': panel,
                      'case_group': case_group, 'family': family, 'supported': supported, 'side': side,
                      'local_clause_coordinates': occurrences, 'scope_attachment': attachment,
                      'annotation_authority': 'author_stipulated_flat_profile_eligibility_not_semantic_truth'}
        validate_document(row, annotation)
        rows.append(row); annotations.append(annotation)
    pair = {'pair_id': case_group + '-contrast', 'case_group': case_group,
            'independent_id': rows[0]['candidate_id'], 'nested_id': rows[1]['candidate_id'],
            'local_clause_body_sha256': [sha(x['source_text'].encode()) for x in local]}
    return rows, pair, annotations


def validate_document(row, annotation=None):
    require(type(row) is dict and set(row) == ROW_KEYS, 'closed authored scope document required')
    legacy.validate_references([row], 1, int(row['supported']))
    require(row['unsupported_reason'] == (None if row['supported'] else 'nested_normative_exception'), 'scope label and unsupported reason differ')
    require(not boundary.UNSUPPORTED.search(row['source_text']), 'new scope contrasts must not be solved by frozen phrase guard')
    if annotation is None: return
    require(annotation['candidate_id'] == row['candidate_id'] and annotation['source_sha256'] == row['source_sha256']
            and annotation['supported'] is row['supported'], 'annotation identity differs')
    occupied = []
    for occurrence in annotation['local_clause_coordinates']:
        start, end = occurrence['char_start'], occurrence['char_end']
        require(0 <= start < end <= len(row['source_text']) and (not occupied or occupied[-1][1] <= start), 'invalid local occurrence intervals')
        require(row['source_text'][start:end] == occurrence['source_text']
                and sha(occurrence['source_text'].encode()) == occurrence['source_sha256'], 'local source body differs')
        spans = []
        for field in FIELDS:
            value, interval = occurrence['rule'][field], occurrence['facet_spans'][field]
            value = value[0] if isinstance(value, list) and value else value
            if interval is None:
                require(value == [], 'missing role span for present atom'); continue
            require(start <= interval[0] < interval[1] <= end and row['source_text'][slice(*interval)] == value,
                    'direct source role span differs')
            spans.append(interval)
        spans.append(occurrence['trigger_span'])
        require(all(start <= a < b <= end for a, b in spans), 'local span escapes occurrence')
        spans.sort(); require(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'overlapping local role/trigger spans')
        trigger = row['source_text'][slice(*occurrence['trigger_span'])]
        require(temporal.TRIGGER_MEANINGS[trigger] == occurrence['rule']['modality'], 'local modal force differs')
        occupied.append((start, end))
    attachment = annotation['scope_attachment']
    if row['supported']:
        require(attachment is None and len(row['clauses']) == len(occupied), 'independent declaration differs')
    else:
        require(type(attachment) is dict and row['source_text'][attachment['start_char']:attachment['end_char']] == attachment['source_text']
                and attachment['start_char'] == occupied[0][1] and attachment['end_char'] == occupied[1][0], 'nested attachment coordinates differ')


def validate_pairs(rows, pairs, expected):
    require(len(rows) == expected * 2 and len(pairs) == expected, 'complete contrastive pair denominator required')
    by_id = {r['candidate_id']: r for r in rows}; seen = set()
    require(len(by_id) == len(rows), 'duplicate scope identity')
    for pair in pairs:
        require(type(pair) is dict and set(pair) == PAIR_KEYS, 'closed scope contrast pair required')
        left, right = pair['independent_id'], pair['nested_id']
        require(left != right and left in by_id and right in by_id and not {left, right} & seen, 'contrast membership differs')
        require(by_id[left]['supported'] is True and by_id[right]['supported'] is False, 'opposite scope labels required')
        require(type(pair['local_clause_body_sha256']) is list and len(pair['local_clause_body_sha256']) in (2, 3)
                and all(type(x) is str and re.fullmatch('[0-9a-f]{64}', x) for x in pair['local_clause_body_sha256']), 'local body commitment required')
        independent, nested = by_id[left], by_id[right]
        declarations = independent['clauses']
        bodies = [independent['source_text'][r['char_start']:r['char_end'] - 1] for r in declarations]
        require(len(bodies) == len(pair['local_clause_body_sha256'])
                and [sha(text.encode()) for text in bodies] == pair['local_clause_body_sha256'], 'pair local body commitment differs')
        require(all(independent['source_text'][r['char_end'] - 1] in '.;' for r in declarations), 'authored local sentence terminator required')
        alternatives = []
        for cue in (' unless ', ' except when ', ' except where '):
            text = bodies[0] + cue + bodies[1] + '.'
            for i in range(2, len(bodies)):
                gap = independent['source_text'][declarations[i - 1]['char_end']:declarations[i]['char_start']]
                text += gap + bodies[i] + '.'
            alternatives.append(text)
        require(nested['source_text'] in alternatives, 'scope contrast must preserve every exact local body and only change outer attachment')
        seen.update((left, right))
    require(seen == set(by_id) and len({p['case_group'] for p in pairs}) == expected, 'scope pairs must exhaust unique cases')


def role_layout(row, annotation):
    replacements = []
    for occurrence in annotation['local_clause_coordinates']:
        replacements.extend((span[0], span[1], '<' + field + '>') for field, span in occurrence['facet_spans'].items() if span)
        replacements.append((*occurrence['trigger_span'], '<modal>'))
    text, cursor = '', 0
    for start, end, replacement in sorted(replacements):
        require(start >= cursor, 'role layout spans overlap')
        text += row['source_text'][cursor:start] + replacement; cursor = end
    text += row['source_text'][cursor:]
    return re.sub(r'\d+', '#', ' '.join(text.casefold().split()))


def make_panels():
    panels, pairs, annotations = {}, {}, []
    for panel, count in COUNTS.items():
        panels[panel], pairs[panel] = [], []
        for case in range(count // 2):
            rows, pair, ledger = make_pair(panel, case)
            panels[panel].extend(rows); pairs[panel].append(pair); annotations.extend(ledger)
        validate_pairs(panels[panel], pairs[panel], count // 2)
    texts = [temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows]
    require(len(texts) == len(set(texts)), 'scope split source overlap')
    return panels, pairs, {'schema': 'legal-scope-retention-annotations/v1', 'document_rows': annotations}


def historical_inventory(prior_manifest_path, boundary_manifest_path):
    previous = read_ref(file_ref(prior_manifest_path))
    old, pools, excluded, references, source_refs, real_count = temporal.historical_inputs(previous['inputs']['prior_corpus']['path'])
    for key in ('new_training', 'new_tuning', 'challenge_targets', 'document_tuning_targets', 'document_challenge_targets'):
        reference = previous['artifacts'][key]; values = read_ref(reference)
        excluded.update(row['source_text'] for row in values)
        if 'document' in key:
            references['temporal_' + key] = {'reference': reference, 'representation': 'document_clauses'}
    bm = read_ref(file_ref(boundary_manifest_path))
    replay_refs = {'original': bm['artifacts']['original_replay_targets'], 'expanded': bm['artifacts']['new_training_targets']}
    replay_hashes = {r['sha256'] for r in replay_refs.values()}
    retention, seen = {}, set()
    for name, item in references.items():
        ref = item['reference']
        if item['representation'] != 'document_clauses' or ref['sha256'] in replay_hashes | seen: continue
        retention[name] = ref; seen.add(ref['sha256'])
    for reference in list(retention.values()) + list(replay_refs.values()):
        for row in read_ref(reference): excluded.add(row['source_text'])
    return replay_refs, retention, excluded, source_refs, real_count


def freeze(output, prior_manifest_path=DEFAULT_PRIOR, boundary_manifest_path=DEFAULT_BOUNDARY):
    output = Path(output).resolve(); require(not output.exists(), 'new scope output directory required')
    replay_refs, retention, excluded, source_refs, real_count = historical_inventory(prior_manifest_path, boundary_manifest_path)
    panels, pairs, ledger = make_panels()
    normalized_old = {temporal.prior.normalized_source(x) for x in excluded}
    require(not normalized_old & {temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows}, 'new scope source overlaps known local inventory')
    output.mkdir(parents=True)
    artifacts = {}
    for panel, target_key, pair_key, source_key in (
        ('train', 'new_training_targets', 'training_pairs', None),
        ('tuning', 'tuning_targets', 'tuning_pairs', 'tuning_sources'),
        ('fresh', 'fresh_targets', 'fresh_pairs', 'fresh_sources')):
        suffix = '.sealed.json' if panel == 'fresh' else '.json'
        artifacts[target_key] = write_new(output / (target_key.replace('_', '-') + suffix), panels[panel])
        artifacts[pair_key] = write_new(output / (pair_key.replace('_', '-') + suffix), pairs[panel])
        if source_key: artifacts[source_key] = write_new(output / (source_key.replace('_', '-') + '.json'), [source_row(r) for r in panels[panel]])
    artifacts['annotation_ledger'] = write_new(output / 'annotations.sealed.json', ledger)
    by_id = {r['candidate_id']: r for r in ledger['document_rows']}
    known_layouts = {p: {role_layout(r, by_id[r['candidate_id']]) for r in panels[p]} for p in ('train', 'tuning')}
    exposure_rows = []
    for row in panels['fresh']:
        annotation = by_id[row['candidate_id']]; layout = role_layout(row, annotation)
        matches = [p for p, values in known_layouts.items() if layout in values]
        exposure_rows.append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
                              'case_group': annotation['case_group'], 'role_masked_layout': layout, 'matching_new_pools': matches,
                              'layout_status': 'matched_new_layout' if matches else 'unmatched_new_combination'})
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.sealed.json', {
        'schema': 'legal-scope-retention-exposure/v1', 'rows': exposure_rows,
        'known_new_layouts': {k: sorted(v) for k, v in known_layouts.items()},
        'historical_source_inventory_count': len(normalized_old),
        'historical_source_inventory_sha256': boundary.digest(sorted(normalized_old)),
        'historical_source_references': source_refs, 'historical_retention_references': retention,
        'real_exposed_views': real_count, 'new_source_overlap_count': 0,
        'claim': 'Shared grammar and individual cues; new entity cases and a mixture of matched/new layout combinations against this study training/tuning only. No historical-layout or universal novelty claim.'})
    counts = {}
    for panel, rows in panels.items():
        annotations = [by_id[r['candidate_id']] for r in rows]
        counts[panel] = {'documents': len(rows), 'supported': sum(r['supported'] for r in rows),
                         'unsupported': sum(not r['supported'] for r in rows), 'scope_pairs': len(pairs[panel]),
                         'families': dict(Counter(a['family'] for a in annotations)),
                         'local_occurrence_counts': dict(Counter(str(len(a['local_clause_coordinates'])) for a in annotations)),
                         'first_clause_modality': dict(Counter(a['local_clause_coordinates'][0]['rule']['modality'] for a in annotations)),
                         'first_clause_CE_mask': dict(Counter(str(int(bool(a['local_clause_coordinates'][0]['rule']['conditions'])) + 2 * int(bool(a['local_clause_coordinates'][0]['rule']['exceptions']))) for a in annotations))}
    manifest = {'schema': SCHEMA, 'generator': file_ref(__file__), 'frozen_before_training': True,
                'dependencies': {name: file_ref(module.__file__) for name, module in (('temporal_corpus', temporal), ('boundary_experiment', legacy), ('boundary_decoder', boundary), ('original_experiment', clauses))},
                'inputs': {'prior_temporal_corpus': file_ref(prior_manifest_path), 'prior_boundary_corpus': file_ref(boundary_manifest_path)},
                'artifacts': artifacts, 'replay_references': replay_refs, 'retention_target_references': retention,
                'counts': counts, 'sealed_artifacts': list(SEALED), 'training_performed': False,
                'source_semantics_verified': False, 'statutory_gold_available': False,
                'scope': 'Contrastive flat-profile eligibility only; unsupported nested sides have no invented flat logical targets. Prior exposed document panels are admitted retention before fitting.'}
    return write_new(output / 'manifest.json', manifest)


def load_training_inputs(manifest_path):
    manifest = read_ref(file_ref(manifest_path))
    require(manifest['schema'] == SCHEMA and manifest['frozen_before_training'] is True
            and manifest['sealed_artifacts'] == list(SEALED), 'frozen scope corpus contract required')
    require(set(manifest['counts']) == set(COUNTS) and all(manifest['counts'][panel]['documents'] == count
            and manifest['counts'][panel]['supported'] == manifest['counts'][panel]['unsupported'] == count // 2
            and manifest['counts'][panel]['scope_pairs'] == count // 2 for panel, count in COUNTS.items()), 'frozen scope counts differ')
    verify_ref(manifest['generator'])
    for ref in list(manifest['dependencies'].values()) + list(manifest['inputs'].values()): verify_ref(ref)
    artifacts = manifest['artifacts']
    train, tune = read_ref(artifacts['new_training_targets']), read_ref(artifacts['tuning_targets'])
    training_pairs, tuning_pairs = read_ref(artifacts['training_pairs']), read_ref(artifacts['tuning_pairs'])
    validate_pairs(train, training_pairs, 96); validate_pairs(tune, tuning_pairs, 48)
    for row in train + tune: validate_document(row)
    fresh = read_ref(artifacts['fresh_sources']); legacy.validate_sources(fresh, 192)
    require(read_ref(artifacts['tuning_sources']) == [source_row(r) for r in tune], 'tuning source binding differs')
    replay = {name: read_ref(ref) for name, ref in manifest['replay_references'].items()}
    require({k: len(v) for k, v in replay.items()} == {'original': 192, 'expanded': 384}, 'complete original and expanded replay required')
    tuning = {name: read_ref(ref) for name, ref in manifest['retention_target_references'].items()}
    tuning['scope_new'] = tune
    for rows in list(replay.values()) + list(tuning.values()): legacy.validate_references(rows, len(rows), sum(r['supported'] for r in rows))
    new_sources = [r['source_sha256'] for r in train + tune + fresh]
    require(len(new_sources) == len(set(new_sources)) == 480, 'new scope source overlap')
    historical = {r['source_sha256'] for rows in list(replay.values()) + list(tuning.values())[:-1] for r in rows}
    require(not set(new_sources) & historical, 'new source overlaps admitted historical documents')
    return {'manifest': manifest, 'new_train': train, 'training_pairs': training_pairs, 'new_tuning': tune,
            'tuning_pairs': tuning_pairs, 'replay': replay, 'tuning': tuning, 'fresh_sources': fresh}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--prior-manifest', default=str(DEFAULT_PRIOR))
    parser.add_argument('--boundary-manifest', default=str(DEFAULT_BOUNDARY))
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.prior_manifest, args.boundary_manifest), sort_keys=True))
