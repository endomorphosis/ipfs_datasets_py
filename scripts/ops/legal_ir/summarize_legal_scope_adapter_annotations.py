"""Pure independent post-release scope-adapter annotation/exposure audit.

The caller supplies every value only after its reference-release gate. This helper
opens no files and runs no model. Authored flat-profile labels are not legal gold.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import random
import re

from scripts.ops.legal_ir import summarize_legal_scope_retention_annotations as previous

boundary, require, text_sha = previous.boundary, previous.require, previous.text_sha
FIELDS = previous.FIELDS
HEADINGS = {'dash': '(b) Filing duty.— ', 'period_bracket': 'Record duty [1]. '}
TIME_KINDS = ('none', 'days', 'hours', 'calendar')
FACTORS = {'first_modality', 'heading', 'child_time_kind', 'clause_count', 'first_CE_mask'}
COUNTS = {'train': 384, 'tuning': 96, 'fresh': 192}
SOURCE_KEYS = {'candidate_id', 'source_text', 'source_sha256'}


def normalize(text):
    return ' '.join(re.findall(r'\w+|[^\w\s]', text.casefold()))


def audit_document(row, annotation, panel):
    require(type(annotation) is dict and set(annotation) == previous.ANNOTATION_KEYS | {'factors'},
        'closed adapter annotation required')
    factors = annotation['factors']
    require(type(factors) is dict and set(factors) == FACTORS and factors['heading'] in HEADINGS
        and annotation['family'] == factors['heading'], 'closed source construction factors required')
    require(row['candidate_id'] == 'scope-' + text_sha(row['source_text'])
        and row['source_sha256'] == text_sha(row['source_text']), 'opaque class-independent source hash identity required')
    require(row['construction'] == (annotation['family'] if row['supported'] else 'unsupported/nested_normative_exception'),
        'actual adapter construction label differs')
    # Reuse the separately tested direct-coordinate checker. Only its historical
    # family vocabulary is normalized transiently; all source/role/scope values
    # remain exact and the actual two-family contract is checked above and below.
    legacy_annotation = {k: deepcopy(v) for k, v in annotation.items() if k != 'factors'}
    legacy_annotation['family'] = 'numbered_child'
    legacy_row = {**row, 'construction': 'numbered_child' if row['supported'] else row['construction']}
    layout = previous.audit_document(legacy_row, legacy_annotation, panel)
    local = annotation['local_clause_coordinates']
    require(type(factors['clause_count']) is int and len(local) == factors['clause_count'] in (2, 3), 'local clause-count factor differs')
    first = local[0]['rule']
    mask = int(bool(first['conditions'])) + 2 * int(bool(first['exceptions']))
    require(type(factors['first_CE_mask']) is int and factors['first_CE_mask'] == mask
        and factors['first_modality'] == first['modality'], 'modality/C/E factors differ from direct source roles')
    child = local[1]; notes = child['editorial_context']
    require(len(notes) == 1 and notes[0]['source_text'] == HEADINGS[factors['heading']]
        and notes[0]['start_char'] == child['char_start'], 'actual child heading literal or direct interval differs')
    temporal, span = child['rule']['temporal'], child['facet_spans']['temporal']
    if not temporal:
        require(factors['child_time_kind'] == 'none' and span is None, 'absent child leading time differs')
    else:
        literal = temporal[0]
        kind = ('hours' if re.fullmatch(r'within \d+ hours', literal) else
            'days' if re.fullmatch(r'within \d+ days', literal) else
            'calendar' if re.fullmatch(r'before \d{4}-\d{2}-\d{2}', literal) else None)
        require(kind is not None and factors['child_time_kind'] == kind and span[0] == notes[0]['end_char']
            and span[1] < child['facet_spans']['actor'][0], 'child time form or leading attachment differs')
    require(len(boundary.tokenize(row['source_text'])) <= 512 and not boundary.UNSUPPORTED.search(row['source_text']),
        'complete bounded source and unchanged surface policy required')
    return layout


def historical_flat_layout(row):
    """Reconstruct unique copied atoms inside each old supported clause interval."""
    require(row['source_sha256'] == text_sha(row['source_text']), 'historical source hash differs')
    if not row['supported']: return None
    replacements = []
    for clause in row['clauses']:
        start, end = clause['char_start'], clause['char_end']
        require(0 <= start < end <= len(row['source_text']), 'historical clause interval differs')
        local = row['source_text'][start:end]
        for field in FIELDS:
            atom = clause['rule'][field]
            if field in FIELDS[3:]:
                require(type(atom) is list and len(atom) <= 1, 'historical single qualifier atom required')
                atom = atom[0] if atom else None
            if atom is None: continue
            matches = [(m.start(), m.end()) for m in re.finditer(re.escape(atom), local)]
            require(len(matches) == 1, 'ambiguous historical role occurrence is not admissible layout evidence')
            left, right = matches[0]; replacements.append((start + left, start + right, '<' + field + '>'))
    result, cursor = '', 0
    for left, right, marker in sorted(replacements):
        require(cursor <= left < right, 'historical role intervals overlap')
        result += row['source_text'][cursor:left] + marker; cursor = right
    result += row['source_text'][cursor:]
    for cue in sorted(previous.MODALS, key=len, reverse=True):
        result = re.sub(r'\b' + re.escape(cue) + r'\b', '<modal>', result, flags=re.I)
    return re.sub(r'\d+', '#', ' '.join(result.casefold().split()))


def audit_scope_annotations(inputs, fresh_targets, fresh_pairs, ledger, exposure, *,
    historical_documents, prior_scope_annotations, historical_source_inventory, historical_manifests):
    from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs
    require(set(historical_manifests) == {'prior_scope', 'prior_condition'}, 'two pinned historical manifests required')
    old_scope, old_condition = (historical_manifests[k] for k in ('prior_scope', 'prior_condition'))
    panels = {'train': inputs['new_train'], 'tuning': inputs['tuning']['scope_new'], 'fresh': fresh_targets}
    pair_panels = {'train': inputs['training_pairs'], 'tuning': inputs['tuning_pairs'], 'fresh': fresh_pairs}
    require({p: len(v) for p, v in panels.items()} == COUNTS, 'all672 new scope documents required')
    require(set(ledger) == {'schema', 'document_rows'} and ledger['schema'] == 'legal-scope-adapter-annotations/v1', 'adapter ledger schema differs')
    annotations = {a['candidate_id']: a for a in ledger['document_rows']}
    require(len(annotations) == len(ledger['document_rows']) == 672
        and set(annotations) == {r['candidate_id'] for rows in panels.values() for r in rows}, 'complete unique new annotations required')
    require([{k: r[k] for k in SOURCE_KEYS} for r in fresh_targets] == inputs['sources']['scope_fresh'], 'fresh source order/content join differs')
    require(all(set(r) == SOURCE_KEYS for r in inputs['sources']['scope_fresh']), 'source-only rows include label metadata')
    layouts, panel_audits, source_sets, meaning_sets, case_sets = {}, {}, {}, {}, {}
    for panel, rows in panels.items():
        audit = verify_scope_pairs(rows, pair_panels[panel], len(rows) // 2)
        labels = [annotations[r['candidate_id']] for r in rows]
        layouts[panel] = {r['candidate_id']: audit_document(r, annotations[r['candidate_id']], panel) for r in rows}
        for pair in pair_panels[panel]:
            left, right = (annotations[pair[key]] for key in ('independent_id', 'nested_id'))
            require(left['case_group'] == right['case_group'] == pair['case_group']
                and left['factors'] == right['factors'], 'contrast case/factor membership differs')
            require([o['source_text'] for o in left['local_clause_coordinates']] == [o['source_text'] for o in right['local_clause_coordinates']]
                and [o['rule'] for o in left['local_clause_coordinates']] == [o['rule'] for o in right['local_clause_coordinates']], 'outer attachment changed local source bodies or complete meanings')
        factor_counts = {key: dict(Counter(str(a['factors'][key]) for a in labels)) for key in sorted(FACTORS)}
        for key, values in (('first_modality', 'OPF'), ('heading', HEADINGS), ('child_time_kind', TIME_KINDS),
            ('clause_count', (2, 3)), ('first_CE_mask', range(4))):
            for side in (True, False):
                observed = Counter(str(a['factors'][key]) for a in labels if a['supported'] is side)
                require(observed == {str(v): len(rows) // (2 * len(values)) for v in values}, 'per-class factor balance differs: ' + key)
        if panel == 'train':
            factor_tuples = [tuple(annotations[p['independent_id']]['factors'][k] for k in sorted(FACTORS)) for p in pair_panels[panel]]
            require(len(set(factor_tuples)) == 192, 'full192 training factor combinations required')
        literal_counts = {k: sum(v in r['source_text'] for r in rows) for k, v in HEADINGS.items()}
        require(literal_counts == {k: len(rows) // 2 for k in HEADINGS}, 'actual heading branches are not balanced')
        unshuffled = [a['candidate_id'] for a in ledger['document_rows'] if a['panel'] == panel]
        random.Random(821713 + list(COUNTS).index(panel)).shuffle(unshuffled)
        require(unshuffled == [r['candidate_id'] for r in rows], 'declared class-neutral source-order shuffle differs')
        source_sets[panel] = {normalize(r['source_text']) for r in rows}
        meaning_sets[panel] = {boundary.digest(o['rule']) for a in labels for o in a['local_clause_coordinates']}
        case_sets[panel] = set(audit['cases'])
        require(len(source_sets[panel]) == len(rows), 'new normalized source repeats within panel')
        panel_audits[panel] = {**audit, 'factor_counts': factor_counts, 'heading_literals': literal_counts,
            'local_occurrences': sum(len(a['local_clause_coordinates']) for a in labels),
            'max_source_tokens': max(len(boundary.tokenize(r['source_text'])) for r in rows)}
    for i, left in enumerate(panels):
        for right in list(panels)[i + 1:]:
            require(not(source_sets[left] & source_sets[right] or meaning_sets[left] & meaning_sets[right]
                or case_sets[left] & case_sets[right]), 'source, local meaning or case crosses split')

    expected_refs = {**old_scope['replay_references'], 'prior_scope': old_scope['artifacts']['new_training_targets'],
        **old_scope['retention_target_references'], 'prior_scope_tuning': old_scope['artifacts']['tuning_targets'],
        'prior_scope_exposed_fresh': old_scope['artifacts']['fresh_targets'],
        'condition_document_tuning': old_condition['artifacts']['document_tuning_targets'],
        'condition_exposed_documents': old_condition['artifacts']['document_challenge_targets']}
    require(set(historical_documents) == set(expected_refs)
        and all(historical_documents[k]['reference'] == pin for k, pin in expected_refs.items()), 'historical document manifest ancestry differs')
    require(prior_scope_annotations['reference'] == old_scope['artifacts']['annotation_ledger'], 'prior scope annotation pin differs')
    old_ledger = prior_scope_annotations['ledger']
    require(old_ledger['schema'] == 'legal-scope-retention-annotations/v1', 'prior scope annotation schema differs')
    old_annotations = {a['candidate_id']: a for a in old_ledger['document_rows']}
    require(len(old_annotations) == len(old_ledger['document_rows']), 'duplicate prior scope annotations')
    old_layout_rows, skipped, all_old_document_sources, old_meanings = {}, {}, set(), set()
    for name, item in historical_documents.items():
        old_layout_rows[name], skipped[name] = [], []
        for row in item['rows']:
            all_old_document_sources.add(row['source_text'])
            old_meanings.update(boundary.digest(c['rule']) for c in row['clauses'])
            if row['candidate_id'] in old_annotations:
                a = old_annotations[row['candidate_id']]
                layout = previous.audit_document(row, a, a['panel'])
            else: layout = historical_flat_layout(row)
            if layout is None: skipped[name].append(row['candidate_id'])
            else: old_layout_rows[name].append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'], 'role_masked_layout': layout})
    known = {p: sorted({r['role_masked_layout'] for r in rows}) for p, rows in old_layout_rows.items()}
    known.update({'new_' + p: sorted(set(layouts[p].values())) for p in ('train', 'tuning')})
    require(exposure['schema'] == 'legal-scope-adapter-exposure/v1'
        and exposure['historical_document_references'] == expected_refs
        and exposure['prior_scope_annotation_reference'] == prior_scope_annotations['reference']
        and exposure['historical_layout_rows'] == old_layout_rows
        and exposure['historical_unannotated_unsupported_ids'] == skipped
        and exposure['known_role_masked_layouts'] == known, 'independent historical layout inventory differs')
    expected_rows = []
    for row in fresh_targets:
        identity = row['candidate_id']; layout = layouts['fresh'][identity]
        matches = sorted(k for k, values in known.items() if layout in values)
        expected_rows.append({'candidate_id': identity, 'source_sha256': row['source_sha256'],
            'case_group': annotations[identity]['case_group'], 'role_masked_layout': layout, 'matching_pools': matches,
            'layout_status': 'matched_audited_layout' if matches else 'unmatched_audited_combination'})
    require(exposure['rows'] == expected_rows, 'complete192 fresh exposure rows differ')
    old_texts = {normalize(t) for t in historical_source_inventory['source_texts']}
    require({normalize(t) for t in all_old_document_sources} <= old_texts, 'source inventory omits admitted historical documents')
    require(exposure['historical_source_inventory_count'] == len(old_texts)
        and exposure['historical_source_inventory_sha256'] == boundary.digest(sorted(old_texts)), 'historical source commitment differs')
    require(exposure['prior_source_references'] == historical_source_inventory['prior_source_references']
        and exposure['prior_condition_single_references'] == historical_source_inventory['condition_single_references']
        == {k: old_condition['artifacts'][k] for k in ('new_tuning', 'challenge_targets')}
        and exposure['real_exposed_views'] == historical_source_inventory['real_exposed_views'] == 86, 'pinned old source inventory provenance differs')
    require(not old_texts & set.union(*source_sets.values()) and not old_meanings & set.union(*meaning_sets.values())
        and exposure['new_source_overlap_count'] == 0, 'new authored source or supported local meaning overlaps history')
    return {'schema': 'legal-scope-adapter-independent-annotation-audit/v1', 'panels': panel_audits,
        'new_documents': 672, 'new_scope_pairs': 336, 'direct_source_role_and_scope_annotations_verified': True,
        'train_full_factorial_combinations': 192, 'source_hash_ids_contain_no_explicit_class_or_case_fields': True,
        'class_neutral_source_order_shuffle_verified': True, 'historical_layout_counts': {k: len(v) for k, v in old_layout_rows.items()},
        'historical_unsupported_without_role_annotations': {k: len(v) for k, v in skipped.items()},
        'known_normalized_source_count': len(old_texts), 'fresh_layout_counts': dict(Counter(r['layout_status'] for r in expected_rows)),
        'fresh_matching_new_training_layout': sum('new_train' in r['matching_pools'] for r in expected_rows),
        'historical_source_and_supported_document_meaning_overlap': 0, 'helper_opens_files': False,
        'prior_released_challenges_are_exposed_retention': True, 'statutory_gold_available': False,
        'limits': ['Grammar is shared; case/source isolation does not establish universal construction novelty.',
            'Historical unsupported documents without role annotations contribute to source exclusion but not exact layout novelty.',
            'Historical source enumeration is supplied by the caller from pinned old inventories; its normalized commitment is independently recomputed.',
            'Authored local roles inside a nested control do not constitute an admitted nested-logic target.']}
