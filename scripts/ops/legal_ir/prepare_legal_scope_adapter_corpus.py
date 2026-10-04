#!/usr/bin/env python3
"""Author paired flat/nested scope controls with explicit coverage and opaque IDs.

These are source-bound authored eligibility labels, not statutory gold or targets
for nested legal logic. Previous released challenges are exposed retention data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from itertools import product
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as previous
from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as condition

temporal, boundary, legacy = previous.temporal, previous.boundary, previous.legacy
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(previous, key) for key in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
FIELDS, SOURCE_KEYS, ROW_KEYS, PAIR_KEYS, SEALED = (
    getattr(previous, key) for key in ('FIELDS', 'SOURCE_KEYS', 'ROW_KEYS', 'PAIR_KEYS', 'SEALED'))
SCHEMA = 'authored-legal-scope-adapter-corpus/v1'
COUNTS = {'train': 384, 'tuning': 96, 'fresh': 192}
PREFIXES = {'train': 'Mapleharbor', 'tuning': 'Willowharbor', 'fresh': 'Birchharbor'}
HEADINGS = {'dash': '(b) Filing duty.— ', 'period_bracket': 'Record duty [1]. '}
TIME_KINDS = ('none', 'days', 'hours', 'calendar')
FAMILIES = tuple(HEADINGS)
FACTOR_KEYS = {'first_modality', 'heading', 'child_time_kind', 'clause_count', 'first_CE_mask'}
DEFAULT_SCOPE = temporal.prior.ARTIFACTS / 'legal-decoder-scope-retention-20261003/scope-corpus-01/manifest.json'
DEFAULT_CONDITION = temporal.prior.ARTIFACTS / 'legal-decoder-scope-retention-20261003/clause-corpus-02/manifest.json'


def source_row(row):
    return {key: row[key] for key in sorted(SOURCE_KEYS)}


def factor_schedule(panel):
    require(panel in COUNTS, 'known authored panel required')
    result = []
    for modal, heading, time, count in product(range(3), range(2), range(4), (2, 3)):
        offset = (modal + heading + time + count) % 4
        masks = range(4) if panel == 'train' else (offset,) if panel == 'tuning' else (offset, (offset + 2) % 4)
        for mask in masks:
            result.append({'first_modality': 'OPF'[modal], 'heading': FAMILIES[heading],
                'child_time_kind': TIME_KINDS[time], 'clause_count': count, 'first_CE_mask': mask})
    require(len(result) * 2 == COUNTS[panel], 'exact factor schedule denominator required')
    return result


def render_local(panel, case, ordinal, factors):
    require(panel in COUNTS and type(case) is int and 0 <= case < COUNTS[panel] // 2
        and type(ordinal) is int and 0 <= ordinal < factors['clause_count'], 'bounded local source coordinates required')
    require(set(factors) == FACTOR_KEYS and factors == factor_schedule(panel)[case], 'case/factor schedule binding differs')
    entity = f'{PREFIXES[panel]}{case:03d}x{ordinal}'
    modality = 'OPF'[('OPF'.index(factors['first_modality']) + ordinal) % 3]
    mask = factors['first_CE_mask']
    style = (mask + ordinal + TIME_KINDS.index(factors['child_time_kind'])) % 4
    trigger = temporal.TRIGGERS[modality][(case + ordinal) % 2]
    kind = factors['child_time_kind'] if ordinal == 1 else 'none'
    duration = {'none': None, 'days': f'within {17 + case % 37} days',
        'hours': f'within {23 + case % 41} hours', 'calendar': f'before 2059-04-{1 + case % 28:02d}'}[kind]
    rule = {'modality': modality, 'actor': f'the {entity} ' + ('Registry', 'Records Office', 'Dept. of Records')[ordinal],
        'action': temporal.VERBS[(case + ordinal) % len(temporal.VERBS)],
        'object': f'the {entity.lower()} filing packet',
        'conditions': [f'the {entity.lower()} permit is active'] if mask & 1 else [],
        'exceptions': [f'the {entity.lower()} exemption is active'] if mask & 2 else [],
        'temporal': [duration] if duration else []}
    writer = temporal.prior.CoordinateWriter()
    editorial, cues = [], []
    if ordinal == 1:
        text = HEADINGS[factors['heading']]
        editorial.append({'start_char': 0, 'end_char': len(text), 'source_text': text,
            'author_stipulated_role': 'nonoperative_editorial_context'})
        writer.add(text)
    def facet(field):
        value = rule[field]; writer.add(value[0] if isinstance(value, list) else value, field)
    def qualifier(field, cue, suffix):
        start = len(writer.text); writer.add(cue)
        if cue: cues.append({'field': field, 'start_char': start, 'end_char': len(writer.text), 'source_text': cue})
        facet(field); writer.add(suffix)
    if duration: qualifier('temporal', '', ', ')
    front_c = bool(rule['conditions']) and style == 0
    front_e = bool(rule['exceptions']) and style == 1
    if front_c: qualifier('conditions', 'If ' if case % 2 else 'When ', ', ')
    if front_e: qualifier('exceptions', 'Unless ', ', ')
    facet('actor')
    infix_c = bool(rule['conditions']) and style == 2
    if infix_c: qualifier('conditions', ', when ', ',')
    writer.add(' '); writer.add(trigger, 'trigger')
    post_c = bool(rule['conditions']) and style == 3
    if post_c: qualifier('conditions', ', if ' if case % 2 else ', when ', ',')
    writer.add(' '); facet('action'); writer.add(' '); facet('object')
    if rule['conditions'] and not (front_c or infix_c or post_c): qualifier('conditions', ' if ', '')
    if rule['exceptions'] and not front_e:
        qualifier('exceptions', (' unless ', ' except when ', ' except where ')[(case + ordinal) % 3], '')
    return {'source_text': writer.text, 'rule': rule, 'facet_spans': {f: writer.spans.get(f) for f in FIELDS},
        'trigger_span': writer.spans['trigger'], 'editorial_context': editorial, 'qualifier_cues': cues}


def make_pair(panel, case):
    factors = factor_schedule(panel)[case]
    local = [render_local(panel, case, i, factors) for i in range(factors['clause_count'])]
    repeated = factors['clause_count'] == 3 and case % 4 == 3
    if repeated: local[2] = deepcopy(local[0])
    group = 'case-' + sha(f'scope-adapter/{panel}/{case}'.encode())
    rows, annotations = [], []
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
                else: text += '\n' if case % 2 else ' '
            start = len(text); text += item['source_text']; end = len(text)
            occurrences.append({'index': index, 'char_start': start, 'char_end': end,
                'source_text': item['source_text'], 'source_sha256': sha(item['source_text'].encode()), 'rule': deepcopy(item['rule']),
                'facet_spans': {k: [start + x for x in span] if span else None for k, span in item['facet_spans'].items()},
                'trigger_span': [start + x for x in item['trigger_span']],
                'editorial_context': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['editorial_context']],
                'qualifier_cues': [{**v, 'start_char': start + v['start_char'], 'end_char': start + v['end_char']} for v in item['qualifier_cues']]})
            if supported or index != 0: text += ';' if supported and index < len(local) - 1 and case % 3 == 0 else '.'
            if supported: declarations.append({'char_start': start, 'char_end': len(text), 'rule': deepcopy(item['rule'])})
        source_hash = sha(text.encode()); identity = 'scope-' + source_hash
        row = {'candidate_id': identity, 'source_text': text, 'source_sha256': source_hash,
            'supported': supported, 'construction': factors['heading'] if supported else 'unsupported/nested_normative_exception',
            'repeated_rule_occurrences': repeated if supported else False, 'clauses': declarations,
            'unsupported_reason': None if supported else 'nested_normative_exception',
            'label_origin': 'authored_scope_contrast_not_statutory_gold'}
        annotation = {'candidate_id': identity, 'source_sha256': source_hash, 'panel': panel, 'case_group': group,
            'family': factors['heading'], 'factors': deepcopy(factors), 'supported': supported,
            'side': 'independent' if supported else 'nested', 'local_clause_coordinates': occurrences,
            'scope_attachment': attachment, 'annotation_authority': 'author_stipulated_flat_profile_eligibility_not_semantic_truth'}
        validate_document(row, annotation)
        rows.append(row); annotations.append(annotation)
    pair = {'pair_id': 'pair-' + sha(group.encode()), 'case_group': group,
        'independent_id': rows[0]['candidate_id'], 'nested_id': rows[1]['candidate_id'],
        'local_clause_body_sha256': [sha(r['source_text'].encode()) for r in local]}
    return rows, pair, annotations


def validate_document(row, annotation=None):
    try:
        previous.validate_document(row, annotation)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('malformed scope source/coordinate annotation') from exc
    require(row['candidate_id'] == 'scope-' + row['source_sha256'], 'opaque exact-source identity required')
    boundary.tokenize(row['source_text'])  # Complete512-token bound; truncation is forbidden.
    if annotation is None: return
    f = annotation['factors']; local = annotation['local_clause_coordinates']
    require(set(f) == FACTOR_KEYS and annotation['family'] == f['heading'] in HEADINGS
        and len(local) == f['clause_count'] in (2, 3), 'explicit factor inventory differs')
    require(local[0]['rule']['modality'] == f['first_modality'] and f['first_modality'] in 'OPF', 'first modal factor differs')
    mask = int(bool(local[0]['rule']['conditions'])) + 2 * int(bool(local[0]['rule']['exceptions']))
    require(mask == f['first_CE_mask'], 'first C/E factor differs')
    child = local[1]; notes = child['editorial_context']
    require(len(notes) == 1 and notes[0]['source_text'] == HEADINGS[f['heading']]
        and notes[0]['start_char'] == child['char_start'], 'realized heading branch differs')
    wanted = f['child_time_kind']; value = child['rule']['temporal']; interval = child['facet_spans']['temporal']
    if wanted == 'none': require(value == [] and interval is None, 'absent child temporal factor differs')
    else:
        pattern = {'days': r'within \d+ days', 'hours': r'within \d+ hours', 'calendar': r'before \d{4}-\d{2}-\d{2}'}[wanted]
        require(len(value) == 1 and re.fullmatch(pattern, value[0]) and interval[0] == notes[0]['end_char']
            and interval[1] < child['facet_spans']['actor'][0], 'child-leading duration/calendar factor differs')
    for occurrence in local:
        for note in occurrence['editorial_context']:
            require(row['source_text'][note['start_char']:note['end_char']] == note['source_text'], 'editorial exact interval differs')
        for cue in occurrence['qualifier_cues']:
            require(row['source_text'][cue['start_char']:cue['end_char']] == cue['source_text']
                and cue['end_char'] == occurrence['facet_spans'][cue['field']][0], 'qualifier cue ownership differs')


def validate_pairs(rows, pairs, expected):
    previous.validate_pairs(rows, pairs, expected)
    for row in rows: validate_document(row)


def realized_counts(rows, annotations, pair_count):
    lookup = {a['candidate_id']: a for a in annotations}
    actual = {'documents': len(rows), 'supported': sum(r['supported'] for r in rows),
        'unsupported': sum(not r['supported'] for r in rows), 'scope_pairs': pair_count,
        'factors': {key: dict(Counter(str(lookup[r['candidate_id']]['factors'][key]) for r in rows)) for key in sorted(FACTOR_KEYS)},
        'heading_literals': {key: sum(HEADINGS[key] in r['source_text'] for r in rows) for key in HEADINGS},
        'max_source_tokens': max(len(boundary.tokenize(r['source_text'])) for r in rows),
        'repeated_supported_documents': sum(r['repeated_rule_occurrences'] for r in rows)}
    for key, values in (('first_modality', 'OPF'), ('heading', HEADINGS), ('child_time_kind', TIME_KINDS),
                        ('clause_count', (2, 3)), ('first_CE_mask', range(4))):
        require(actual['factors'][key] == {str(v): len(rows) // len(values) for v in values}, 'realized factor margin differs: ' + key)
    require(actual['heading_literals'] == {k: len(rows) // 2 for k in HEADINGS}, 'both actual heading branches must be rendered equally')
    return actual


def make_panels():
    panels, pairs, annotations, counts = {}, {}, [], {}
    for panel, count in COUNTS.items():
        rows, pairs[panel], labels = [], [], []
        for case in range(count // 2):
            pair_rows, metadata, pair_labels = make_pair(panel, case)
            rows.extend(pair_rows); pairs[panel].append(metadata); labels.extend(pair_labels)
        random.Random(821713 + list(COUNTS).index(panel)).shuffle(rows)
        validate_pairs(rows, pairs[panel], count // 2)
        counts[panel] = realized_counts(rows, labels, len(pairs[panel]))
        panels[panel] = rows; annotations.extend(labels)
    normalized = [temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows]
    require(len(normalized) == len(set(normalized)) == sum(COUNTS.values()), 'new source split overlap')
    meanings = [{boundary.digest(a['rule']) for r in annotations if r['panel'] == p for a in r['local_clause_coordinates']} for p in COUNTS]
    require(not any(a & b for i, a in enumerate(meanings) for b in meanings[i + 1:]), 'local canonical meanings cross splits')
    return panels, pairs, {'schema': 'legal-scope-adapter-annotations/v1', 'document_rows': annotations}, counts


def role_layout(row, annotation):
    return previous.role_layout(row, annotation)


def historical_document_layout(row):
    """Mask supported historical flat roles only; unknown guards stay unknown."""
    if not row['supported']: return None
    locals_ = temporal.construction.document_clauses_for_audit([row])
    replacements = []
    for clause, local in zip(row['clauses'], locals_, strict=True):
        for field, span in local['facet_spans'].items():
            if span: replacements.append((clause['char_start'] + span[0], clause['char_start'] + span[1], '<' + field + '>'))
    text, cursor = '', 0
    for start, end, replacement in sorted(replacements):
        require(cursor <= start < end, 'historical role occurrence overlaps')
        text += row['source_text'][cursor:start] + replacement; cursor = end
    text += row['source_text'][cursor:]
    for cue in sorted(temporal.TRIGGER_MEANINGS, key=len, reverse=True):
        text = re.sub(r'\b' + re.escape(cue) + r'\b', '<modal>', text, flags=re.I)
    return re.sub(r'\d+', '#', ' '.join(text.casefold().split()))


def historical_inventory(scope_manifest_path, condition_manifest_path):
    scope, cm = read_ref(file_ref(scope_manifest_path)), read_ref(file_ref(condition_manifest_path))
    replay_refs = {**scope['replay_references'], 'prior_scope': scope['artifacts']['new_training_targets']}
    retention_refs = dict(scope['retention_target_references'])
    docs = {**replay_refs, **retention_refs,
        'prior_scope_tuning': scope['artifacts']['tuning_targets'], 'prior_scope_exposed_fresh': scope['artifacts']['fresh_targets'],
        'condition_document_tuning': cm['artifacts']['document_tuning_targets'],
        'condition_exposed_documents': cm['artifacts']['document_challenge_targets']}
    _, _, excluded, _, source_refs, real_count = condition.historical_inputs(cm['inputs']['prior_corpus']['path'])
    for key in ('new_tuning', 'challenge_targets', 'document_tuning_targets', 'document_challenge_targets'):
        excluded.update(r['source_text'] for r in read_ref(cm['artifacts'][key]))
    old_annotations = read_ref(scope['artifacts']['annotation_ledger'])
    lookup = {a['candidate_id']: a for a in old_annotations['document_rows']}
    pools, layout_rows, missing = {}, {}, {}
    for name, pin in docs.items():
        values = read_ref(pin); pools[name] = values; excluded.update(r['source_text'] for r in values)
        layout_rows[name], missing[name] = [], []
        for row in values:
            layout = role_layout(row, lookup[row['candidate_id']]) if row['candidate_id'] in lookup else historical_document_layout(row)
            if layout is None: missing[name].append(row['candidate_id'])
            else: layout_rows[name].append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'], 'role_masked_layout': layout})
    return {'replay_references': replay_refs, 'retention_target_references': retention_refs,
        'document_references': docs, 'layout_rows': layout_rows, 'unannotated_unsupported_ids': missing,
        'excluded_sources': excluded, 'prior_source_references': source_refs, 'real_exposed_views': real_count,
        'prior_scope_annotation_reference': scope['artifacts']['annotation_ledger'], 'pools': pools,
        'condition_single_references': {k: cm['artifacts'][k] for k in ('new_tuning', 'challenge_targets')}}


def freeze(output, scope_manifest_path=DEFAULT_SCOPE, condition_manifest_path=DEFAULT_CONDITION):
    output = Path(output).resolve(); require(not output.exists(), 'new output directory required')
    history = historical_inventory(scope_manifest_path, condition_manifest_path)
    panels, pairs, ledger, counts = make_panels()
    old_texts = {temporal.prior.normalized_source(s) for s in history['excluded_sources']}
    new_texts = {temporal.prior.normalized_source(r['source_text']) for rows in panels.values() for r in rows}
    require(not old_texts & new_texts, 'new source overlaps prior local inventory')
    old_rules = {boundary.digest(c['rule']) for values in history['pools'].values() for r in values for c in r['clauses']}
    require(not old_rules & {boundary.digest(o['rule']) for a in ledger['document_rows'] for o in a['local_clause_coordinates']}, 'new local meaning overlaps old supported document rules')
    output.mkdir(parents=True)
    artifacts = {}
    for panel, target_key, pair_key, source_key in (
        ('train', 'new_training_targets', 'training_pairs', 'training_sources'),
        ('tuning', 'tuning_targets', 'tuning_pairs', 'tuning_sources'),
        ('fresh', 'fresh_targets', 'fresh_pairs', 'fresh_sources')):
        suffix = '.sealed.json' if panel == 'fresh' else '.json'
        artifacts[target_key] = write_new(output / (target_key.replace('_', '-') + suffix), panels[panel])
        artifacts[pair_key] = write_new(output / (pair_key.replace('_', '-') + suffix), pairs[panel])
        artifacts[source_key] = write_new(output / (source_key.replace('_', '-') + '.json'), [source_row(r) for r in panels[panel]])
    artifacts['annotation_ledger'] = write_new(output / 'annotations.sealed.json', ledger)
    lookup = {a['candidate_id']: a for a in ledger['document_rows']}
    known = {name: {r['role_masked_layout'] for r in values} for name, values in history['layout_rows'].items()}
    known.update({'new_' + p: {role_layout(r, lookup[r['candidate_id']]) for r in panels[p]} for p in ('train', 'tuning')})
    exposure_rows = []
    for row in panels['fresh']:
        layout = role_layout(row, lookup[row['candidate_id']]); matches = sorted(k for k, values in known.items() if layout in values)
        exposure_rows.append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
            'case_group': lookup[row['candidate_id']]['case_group'], 'role_masked_layout': layout, 'matching_pools': matches,
            'layout_status': 'matched_audited_layout' if matches else 'unmatched_audited_combination'})
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.sealed.json', {
        'schema': 'legal-scope-adapter-exposure/v1', 'rows': exposure_rows,
        'known_role_masked_layouts': {k: sorted(v) for k, v in known.items()},
        'historical_layout_rows': history['layout_rows'], 'historical_unannotated_unsupported_ids': history['unannotated_unsupported_ids'],
        'historical_document_references': history['document_references'],
        'prior_scope_annotation_reference': history['prior_scope_annotation_reference'],
        'prior_condition_single_references': history['condition_single_references'],
        'prior_source_references': history['prior_source_references'],
        'historical_source_inventory_count': len(old_texts), 'historical_source_inventory_sha256': boundary.digest(sorted(old_texts)),
        'real_exposed_views': history['real_exposed_views'], 'new_source_overlap_count': 0,
        'claim': 'New case/entity/source holdout with shared grammar. Exact full-document role layouts audited against prior direct scope annotations, supported historical flat documents, and new train/tuning. Historical unsupported documents without role annotations are excluded from layout claims, but included in source exclusion. No universal construction novelty or statutory gold.'})
    manifest = {'schema': SCHEMA, 'generator': file_ref(__file__), 'frozen_before_training': True,
        'dependencies': {name: file_ref(module.__file__) for name, module in (('previous_scope', previous), ('condition_corpus', condition), ('temporal_corpus', temporal), ('boundary_decoder', boundary))},
        'inputs': {'prior_scope_corpus': file_ref(scope_manifest_path), 'prior_condition_corpus': file_ref(condition_manifest_path)},
        'artifacts': artifacts, 'replay_references': history['replay_references'], 'retention_target_references': history['retention_target_references'],
        'counts': counts, 'sealed_artifacts': list(SEALED), 'training_performed': False,
        'source_identity_policy': 'scope- plus full SHA256(source_text), independent of class/case metadata; deterministic per-panel source shuffle',
        'source_semantics_verified': False, 'statutory_gold_available': False,
        'scope': 'Authored flat-profile eligibility, not nested logic translation; previous released challenges are exposed retention.'}
    return write_new(output / 'manifest.json', manifest)


def load_training_inputs(manifest_path):
    """Open admitted labels and source-only new holdout; never parse sealed refs."""
    manifest = read_ref(file_ref(manifest_path))
    require(manifest['schema'] == SCHEMA and manifest['frozen_before_training'] is True
        and manifest['sealed_artifacts'] == list(SEALED), 'frozen corpus schema/seals required')
    verify_ref(manifest['generator'])
    for pin in list(manifest['dependencies'].values()) + list(manifest['inputs'].values()): verify_ref(pin)
    require(set(manifest['counts']) == set(COUNTS) and all(manifest['counts'][p]['documents'] == n
        and manifest['counts'][p]['supported'] == manifest['counts'][p]['unsupported'] == n // 2
        and manifest['counts'][p]['scope_pairs'] == n // 2 for p, n in COUNTS.items()), 'closed authored denominators differ')
    a = manifest['artifacts']
    train, tune = read_ref(a['new_training_targets']), read_ref(a['tuning_targets'])
    pairs, tpairs = read_ref(a['training_pairs']), read_ref(a['tuning_pairs'])
    validate_pairs(train, pairs, 192); validate_pairs(tune, tpairs, 48)
    fresh = read_ref(a['fresh_sources']); legacy.validate_sources(fresh, 192)
    for source in [source_row(r) for r in train + tune] + fresh:
        require(set(source) == SOURCE_KEYS and source['candidate_id'] == 'scope-' + sha(source['source_text'].encode())
            and source['source_sha256'] == sha(source['source_text'].encode()), 'source-only opaque identity differs')
        boundary.tokenize(source['source_text'])
    require(read_ref(a['training_sources']) == [source_row(r) for r in train]
        and read_ref(a['tuning_sources']) == [source_row(r) for r in tune], 'admitted source/target ordering differs')
    replay = {name: read_ref(pin) for name, pin in manifest['replay_references'].items()}
    require({k: len(v) for k, v in replay.items()} == {'original': 192, 'expanded': 384, 'prior_scope': 192}, 'complete768 historical TRAIN replay required')
    tuning = {name: read_ref(pin) for name, pin in manifest['retention_target_references'].items()}
    require('scope_new' not in tuning, 'new tuning name collides with history'); tuning['scope_new'] = tune
    for rows in list(replay.values()) + list(tuning.values()): legacy.validate_references(rows, len(rows), sum(r['supported'] for r in rows))
    new_hashes = {r['source_sha256'] for r in train + tune + fresh}
    old_replay = [r for rows in replay.values() for r in rows]
    require(len(new_hashes) == sum(COUNTS.values()) and len({r['source_sha256'] for r in old_replay}) == 768, 'new or replay source duplication')
    history_hashes = {r['source_sha256'] for rows in list(replay.values()) + [v for k, v in tuning.items() if k != 'scope_new'] for r in rows}
    require(not new_hashes & history_hashes, 'new source overlaps admitted historical documents')
    return {'manifest': manifest, 'new_train': train, 'training_pairs': pairs, 'new_tuning': tune,
        'tuning_pairs': tpairs, 'replay': replay, 'tuning': tuning, 'fresh_sources': fresh}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True); parser.add_argument('--prior-scope-manifest', default=str(DEFAULT_SCOPE))
    parser.add_argument('--prior-condition-manifest', default=str(DEFAULT_CONDITION))
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.prior_scope_manifest, args.prior_condition_manifest), sort_keys=True))
