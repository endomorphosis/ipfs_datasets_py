"""Independent post-release checks for source-bound scope contrast annotations.

This module does not open files. The caller supplies references only after its
generation/replay/build release gate. Source-text controls remain authored, not
statutory gold; visibly class-bearing identifiers remain an explicit limitation.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import re

from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary

require = boundary.require
FIELDS = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
FAMILIES = {'plain_join', 'numbered_child', 'duration_child', 'heading_duration_child'}
MODALS = {'shall': 'O', 'must': 'O', 'may': 'P', 'is permitted to': 'P', 'must not': 'F', 'may not': 'F'}
ANNOTATION_KEYS = {'candidate_id', 'source_sha256', 'panel', 'case_group', 'family', 'supported', 'side',
                   'local_clause_coordinates', 'scope_attachment', 'annotation_authority'}
OCCURRENCE_KEYS = {'index', 'char_start', 'char_end', 'source_text', 'source_sha256', 'rule', 'facet_spans',
                   'trigger_span', 'editorial_context', 'qualifier_cues'}


def text_sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def interval(value, text, lower, upper):
    require(type(value) is list and len(value) == 2 and all(type(x) is int for x in value)
            and lower <= value[0] < value[1] <= upper <= len(text), 'bounded direct source interval required')
    return text[value[0]:value[1]]


def audit_document(row, annotation, panel):
    require(type(annotation) is dict and set(annotation) == ANNOTATION_KEYS, 'closed scope annotation required')
    text = row['source_text']
    require(annotation['candidate_id'] == row['candidate_id'] and annotation['source_sha256'] == row['source_sha256'] == text_sha(text)
            and annotation['panel'] == panel and type(row['supported']) is bool and annotation['supported'] is row['supported'], 'scope annotation source or label binding differs')
    require(annotation['family'] in FAMILIES and annotation['side'] == ('independent' if row['supported'] else 'nested')
            and annotation['annotation_authority'] == 'author_stipulated_flat_profile_eligibility_not_semantic_truth', 'scope annotation authority/side differs')
    require(row['label_origin'] == 'authored_scope_contrast_not_statutory_gold' and type(row['repeated_rule_occurrences']) is bool,
            'authored profile label required')
    require(row['construction'] == (annotation['family'] if row['supported'] else 'unsupported/nested_normative_exception')
            and row['unsupported_reason'] == (None if row['supported'] else 'nested_normative_exception'), 'scope construction label differs')
    occurrences = annotation['local_clause_coordinates']
    require(type(occurrences) is list and len(occurrences) in (2, 3), 'two or three local occurrences required')
    replacements, previous_end = [], 0
    for index, occurrence in enumerate(occurrences):
        require(type(occurrence) is dict and set(occurrence) == OCCURRENCE_KEYS and type(occurrence['index']) is int and occurrence['index'] == index,
                'closed ordered local occurrence required')
        start, end = occurrence['char_start'], occurrence['char_end']
        body = interval([start, end], text, previous_end, len(text))
        require(body == occurrence['source_text'] and text_sha(body) == occurrence['source_sha256'], 'local body source binding differs')
        previous_end = end
        rule = occurrence['rule']
        require(type(rule) is dict and set(rule) == set(FIELDS) | {'modality'} and rule['modality'] in ('O', 'P', 'F'), 'closed flat local role tuple required')
        require(type(occurrence['facet_spans']) is dict and set(occurrence['facet_spans']) == set(FIELDS), 'complete facet coordinates required')
        occupied = []
        for field in FIELDS:
            value = rule[field]
            if field in FIELDS[3:]:
                require(type(value) is list and len(value) <= 1 and all(type(v) is str and v for v in value), 'bounded opaque qualifier atom required')
                value = value[0] if value else None
            else: require(type(value) is str and bool(value), 'nonempty scalar role atom required')
            span = occurrence['facet_spans'][field]
            if value is None:
                require(span is None, 'absent role must have no span'); continue
            require(interval(span, text, start, end) == value, 'local role text or offset differs')
            occupied.append(span); replacements.append((*span, '<' + field + '>'))
        trigger = occurrence['trigger_span']
        require(MODALS.get(interval(trigger, text, start, end)) == rule['modality'], 'trigger and author-stipulated force differ')
        occupied.append(trigger); replacements.append((*trigger, '<modal>'))
        occupied.sort()
        require(all(a[1] <= b[0] for a, b in zip(occupied, occupied[1:])), 'local role/trigger spans overlap')
        for editorial in occurrence['editorial_context']:
            require(set(editorial) == {'start_char', 'end_char', 'source_text', 'author_stipulated_role'}
                    and editorial['author_stipulated_role'] == 'nonoperative_editorial_context', 'authored editorial provenance required')
            span = [editorial['start_char'], editorial['end_char']]
            require(interval(span, text, start, end) == editorial['source_text']
                    and all(span[1] <= a or b <= span[0] for a, b in occupied), 'editorial text must be source-bound and outside copied roles')
        seen_cues = set()
        for cue in occurrence['qualifier_cues']:
            require(set(cue) == {'field', 'start_char', 'end_char', 'source_text'}
                    and cue['field'] in FIELDS[3:] and cue['field'] not in seen_cues, 'closed unique qualifier cue required')
            span = [cue['start_char'], cue['end_char']]
            require(interval(span, text, start, end) == cue['source_text'] and occurrence['facet_spans'][cue['field']] is not None
                    and span[1] == occurrence['facet_spans'][cue['field']][0], 'qualifier cue must adjoin its owned atom')
            seen_cues.add(cue['field'])
    attachment = annotation['scope_attachment']
    if row['supported']:
        require(attachment is None and len(row['clauses']) == len(occurrences), 'independent scope declaration differs')
        cursor = 0
        for clause, occurrence in zip(row['clauses'], occurrences, strict=True):
            require(set(clause) == {'char_start', 'char_end', 'rule'} and clause['rule'] == occurrence['rule']
                    and clause['char_start'] == occurrence['char_start'] and clause['char_end'] == occurrence['char_end'] + 1
                    and text[clause['char_end'] - 1] in '.;' and not text[cursor:clause['char_start']].strip(), 'supported source interval/meaning or coverage differs')
            cursor = clause['char_end']
        require(not text[cursor:].strip(), 'supported source tail omitted')
        repeated = len({boundary.digest(o['rule']) for o in occurrences}) < len(occurrences)
        require(row['repeated_rule_occurrences'] is repeated, 'repeated supported occurrence flag differs')
    else:
        require(row['clauses'] == [] and row['repeated_rule_occurrences'] is False, 'unsupported nested source must not invent flat targets')
        require(type(attachment) is dict and set(attachment) == {'start_char', 'end_char', 'source_text', 'parent_occurrence', 'child_occurrence', 'declared_relation'}, 'closed outer attachment required')
        require(attachment['parent_occurrence'] == 0 and attachment['child_occurrence'] == 1
                and attachment['declared_relation'] == 'nested_normative_exception_outside_flat_profile'
                and attachment['start_char'] == occurrences[0]['char_end'] and attachment['end_char'] == occurrences[1]['char_start']
                and interval([attachment['start_char'], attachment['end_char']], text, 0, len(text)) == attachment['source_text']
                and attachment['source_text'] in (' unless ', ' except when ', ' except where '), 'nested attachment source or relation differs')
    result, cursor = '', 0
    for start, end, replacement in sorted(replacements):
        require(start >= cursor, 'document role-mask overlap')
        result += text[cursor:start] + replacement; cursor = end
    result += text[cursor:]
    return re.sub(r'\d+', '#', ' '.join(result.casefold().split()))


def audit_scope_annotations(inputs, fresh_targets, fresh_pairs, ledger, exposure):
    from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
    panels = {'train': inputs['new_train'], 'tuning': inputs['tuning']['scope_new'], 'fresh': fresh_targets}
    pair_panels = {'train': inputs['training_pairs'], 'tuning': inputs['tuning_pairs'], 'fresh': fresh_pairs}
    require({k: len(v) for k, v in panels.items()} == {'train': 192, 'tuning': 96, 'fresh': 192}, 'complete480 scope target inventory required')
    require(type(ledger) is dict and set(ledger) == {'schema', 'document_rows'}
            and ledger['schema'] == 'legal-scope-retention-annotations/v1' and len(ledger['document_rows']) == 480, 'complete scope annotation ledger required')
    annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    allrows = [r for rows in panels.values() for r in rows]
    require(len(annotations) == len({r['candidate_id'] for r in allrows}) == 480
            and set(annotations) == {r['candidate_id'] for r in allrows}, 'scope annotations have missing/duplicate/extraneous IDs')
    source_views = inputs['sources']['scope_fresh']
    require([{k: row[k] for k in ('candidate_id', 'source_text', 'source_sha256')} for row in fresh_targets] == source_views,
            'fresh scope source order/content differs from source-only generation inventory')
    layouts, case_sets, panel_audits, source_sets = {}, {}, {}, {}
    for panel, rows in panels.items():
        pair_audit = verify_scope_pairs(rows, pair_panels[panel], len(rows) // 2)
        by_id = {r['candidate_id']: r for r in rows}
        for pair in pair_panels[panel]:
            positive, negative = [annotations[pair[k]] for k in ('independent_id', 'nested_id')]
            require(positive['case_group'] == negative['case_group'] == pair['case_group'], 'scope contrast case ownership differs')
            require(positive['family'] == negative['family'] and positive['panel'] == negative['panel'] == panel, 'scope contrast family/panel differs')
            left, right = positive['local_clause_coordinates'], negative['local_clause_coordinates']
            require([r['source_text'] for r in left] == [r['source_text'] for r in right]
                    and [r['rule'] for r in left] == [r['rule'] for r in right], 'same local bodies must retain the same complete local role atoms across outer scope contrasts')
        layouts[panel] = {r['candidate_id']: audit_document(r, annotations[r['candidate_id']], panel) for r in rows}
        case_sets[panel] = set(pair_audit['cases'])
        source_sets[panel] = {' '.join(r['source_text'].casefold().split()) for r in rows}
        require(len(source_sets[panel]) == len(rows), 'duplicate scope source within split')
        family_counts = Counter(annotations[r['candidate_id']]['family'] for r in rows)
        require(family_counts == {family: len(rows) // 4 for family in FAMILIES}, 'four-family balance differs')
        modal_counts = Counter(annotations[r['candidate_id']]['local_clause_coordinates'][0]['rule']['modality'] for r in rows)
        require(modal_counts == {m: len(rows) // 3 for m in 'OPF'}, 'first-clause O/P/F balance differs')
        masks = Counter(int(bool(annotations[r['candidate_id']]['local_clause_coordinates'][0]['rule']['conditions']))
                        + 2 * int(bool(annotations[r['candidate_id']]['local_clause_coordinates'][0]['rule']['exceptions'])) for r in rows)
        require(masks == {i: len(rows) // 4 for i in range(4)}, 'first-clause C/E presence balance differs')
        panel_audits[panel] = {**pair_audit, 'families': dict(family_counts), 'first_modality': dict(modal_counts),
                               'first_CE_mask': dict(masks), 'local_occurrences': sum(len(annotations[r['candidate_id']]['local_clause_coordinates']) for r in rows)}
    for a in panels:
        for b in panels:
            if a < b: require(not case_sets[a] & case_sets[b] and not source_sets[a] & source_sets[b], 'scope case/source split overlap')
    require(exposure['schema'] == 'legal-scope-retention-exposure/v1' and len(exposure['rows']) == 192, 'complete scope exposure inventory required')
    expected_known = {p: sorted(set(layouts[p].values())) for p in ('train', 'tuning')}
    require(exposure['known_new_layouts'] == expected_known, 'declared known-new layout inventory differs')
    by_exposure = {r['candidate_id']: r for r in exposure['rows']}
    require(len(by_exposure) == 192 and set(by_exposure) == set(layouts['fresh']), 'fresh layout inventory ID mismatch')
    statuses, matched_training = Counter(), 0
    for row in fresh_targets:
        row_id = row['candidate_id']; layout = layouts['fresh'][row_id]
        matches = [p for p in ('train', 'tuning') if layout in expected_known[p]]
        status = 'matched_new_layout' if matches else 'unmatched_new_combination'
        require(by_exposure[row_id] == {'candidate_id': row_id, 'source_sha256': row['source_sha256'],
            'case_group': annotations[row_id]['case_group'], 'role_masked_layout': layout,
            'matching_new_pools': matches, 'layout_status': status}, 'independent fresh layout exposure differs')
        statuses[status] += 1; matched_training += 'train' in matches
    historical = [r for rows in inputs['tuning'].values() for r in rows if r['candidate_id'] not in annotations]
    historical += inputs['replay']
    history_sources = {' '.join(r['source_text'].casefold().split()) for r in historical}
    require(not set.union(*source_sets.values()) & history_sources, 'new scope source overlaps admitted historical document inventory')
    require(exposure['historical_retention_references'] == inputs['manifest']['retention_target_references']
            and exposure['new_source_overlap_count'] == 0, 'historical reference binding or claimed overlap differs')
    heading_counts = {panel: {'standalone_record_duty_heading': sum(bool(re.search(r'Record duty \[\d+\]\.', r['source_text'])) for r in rows),
                              'numbered_dot_emdash_heading': sum('(b) Filing duty.—' in r['source_text'] for r in rows)} for panel, rows in panels.items()}
    id_labels = {'independent_token': sum('-independent-' in r['candidate_id'] for r in fresh_targets),
                 'nested_token': sum('-nested-' in r['candidate_id'] for r in fresh_targets)}
    return {'schema': 'legal-scope-retention-independent-annotation-audit/v1', 'panels': panel_audits,
            'all480_source_role_and_attachment_annotations_reconstructed': True,
            'all240_contrasts_preserve_complete_local_roles': True, 'fresh_layout_counts': dict(statuses),
            'fresh_rows_matching_new_training_layout': matched_training,
            'historical_admitted_document_source_overlap': 0,
            'historical_full_single_plus_document_inventory_commitment_recomputed': False,
            'layout_novelty_scope': 'Only exact role-masked constructions against this study train/tuning; shared cues and no universal or historical-layout novelty claim.',
            'realized_heading_counts': heading_counts, 'identifier_class_tokens': id_labels,
            'limitations': ['The intended standalone-period Record duty [1]. heading variant is absent from new training; the present dot-and-dash heading still contains a period.',
                           'Fresh candidate IDs expose independent/nested classes. File sealing does not establish label-free metadata; consult the separate measured ID-invariance receipt.',
                           'Local role meanings and independent/nested eligibility are author-stipulated; no statutory gold or supported nested-logic translation is established.'],
            'new_files_opened_by_helper': False, 'model_inference_performed': False}
