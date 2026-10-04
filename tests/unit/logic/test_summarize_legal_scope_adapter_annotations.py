"""Pure qualifier fixtures use admitted train/tuning renderers and fictional IDs.

No actual new fresh renderer branch, target file or reference ledger is opened.
Historical released scope references remain admitted exposure data.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import random

import pytest
from scripts.ops.legal_ir import prepare_legal_scope_adapter_corpus as corpus
from scripts.ops.legal_ir import summarize_legal_scope_adapter_annotations as audit
from scripts.ops.legal_ir.summarize_legal_scope_retention_experiment import verify_scope_pairs


def rename(value):
    if isinstance(value, dict): return {k: rename(v) for k, v in value.items()}
    if isinstance(value, list): return [rename(v) for v in value]
    if isinstance(value, str): return value.replace('Mapleharbor', 'Novelharbor').replace('mapleharbor', 'novelharbor')
    return value


def fictional_pair(case):
    rows, pair, annotations = [rename(v) for v in corpus.make_pair('train', case)]
    old_ids = {}
    group = 'case-' + corpus.sha(('fictional/' + pair['case_group']).encode())
    for row, annotation in zip(rows, annotations, strict=True):
        old_id = row['candidate_id']; row['source_sha256'] = audit.text_sha(row['source_text'])
        row['candidate_id'] = 'scope-' + row['source_sha256']; old_ids[old_id] = row['candidate_id']
        annotation.update(candidate_id=row['candidate_id'], source_sha256=row['source_sha256'], panel='fresh', case_group=group)
        for occurrence in annotation['local_clause_coordinates']:
            occurrence['source_sha256'] = audit.text_sha(occurrence['source_text'])
    pair.update(pair_id='pair-' + corpus.sha(group.encode()), case_group=group,
        independent_id=old_ids[pair['independent_id']], nested_id=old_ids[pair['nested_id']],
        local_clause_body_sha256=[o['source_sha256'] for o in annotations[0]['local_clause_coordinates']])
    return rows, pair, annotations


@pytest.fixture(scope='module')
def bundle():
    panels, pairs, annotations = {}, {}, []
    # Fictional fresh cases are an independently selected balanced half of TRAIN
    # factors, with new atoms; no real fresh renderer or source files are used.
    fiction_cases = [i for i, f in enumerate(corpus.factor_schedule('train'))
        if (f['first_CE_mask'] + list(corpus.HEADINGS).index(f['heading'])
            + corpus.TIME_KINDS.index(f['child_time_kind']) + 'OPF'.index(f['first_modality']) + f['clause_count']) % 2 == 0]
    assert len(fiction_cases) == 96
    for panel, cases in (('train', range(192)), ('tuning', range(48)), ('fresh', fiction_cases)):
        panels[panel], pairs[panel] = [], []
        for case in cases:
            rows, pair, labels = fictional_pair(case) if panel == 'fresh' else corpus.make_pair(panel, case)
            panels[panel].extend(rows); pairs[panel].append(pair); annotations.extend(labels)
        random.Random(821713 + list(corpus.COUNTS).index(panel)).shuffle(panels[panel])
    ledger = {'schema': 'legal-scope-adapter-annotations/v1', 'document_rows': annotations}
    lookup = {a['candidate_id']: a for a in annotations}
    history = corpus.historical_inventory(corpus.DEFAULT_SCOPE, corpus.DEFAULT_CONDITION)
    old_scope, old_condition = (corpus.read_ref(corpus.file_ref(path)) for path in (corpus.DEFAULT_SCOPE, corpus.DEFAULT_CONDITION))
    known = {name: {r['role_masked_layout'] for r in rows} for name, rows in history['layout_rows'].items()}
    known.update({'new_' + p: {corpus.role_layout(r, lookup[r['candidate_id']]) for r in panels[p]} for p in ('train', 'tuning')})
    exposure_rows = []
    for row in panels['fresh']:
        layout = corpus.role_layout(row, lookup[row['candidate_id']]); matches = sorted(k for k, values in known.items() if layout in values)
        exposure_rows.append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
            'case_group': lookup[row['candidate_id']]['case_group'], 'role_masked_layout': layout,
            'matching_pools': matches, 'layout_status': 'matched_audited_layout' if matches else 'unmatched_audited_combination'})
    normalized = {corpus.temporal.prior.normalized_source(s) for s in history['excluded_sources']}
    exposure = {'schema': 'legal-scope-adapter-exposure/v1', 'rows': exposure_rows,
        'known_role_masked_layouts': {k: sorted(v) for k, v in known.items()},
        'historical_layout_rows': history['layout_rows'], 'historical_unannotated_unsupported_ids': history['unannotated_unsupported_ids'],
        'historical_document_references': history['document_references'],
        'prior_scope_annotation_reference': history['prior_scope_annotation_reference'],
        'prior_condition_single_references': history['condition_single_references'],
        'prior_source_references': history['prior_source_references'],
        'historical_source_inventory_count': len(normalized), 'historical_source_inventory_sha256': corpus.boundary.digest(sorted(normalized)),
        'real_exposed_views': 86, 'new_source_overlap_count': 0}
    inputs = {'new_train': panels['train'], 'training_pairs': pairs['train'], 'tuning_pairs': pairs['tuning'],
        'tuning': {'scope_new': panels['tuning']}, 'sources': {'scope_fresh': [corpus.source_row(r) for r in panels['fresh']]}}
    kwargs = {'historical_documents': {name: {'reference': pin, 'rows': history['pools'][name]} for name, pin in history['document_references'].items()},
        'prior_scope_annotations': {'reference': history['prior_scope_annotation_reference'], 'ledger': corpus.read_ref(history['prior_scope_annotation_reference'])},
        'historical_source_inventory': {'source_texts': sorted(history['excluded_sources']),
            'prior_source_references': history['prior_source_references'], 'condition_single_references': history['condition_single_references'], 'real_exposed_views': 86},
        'historical_manifests': {'prior_scope': old_scope, 'prior_condition': old_condition}}
    return (inputs, panels['fresh'], pairs['fresh'], ledger, exposure), kwargs


def test_complete672_documents336_pairs_and_historical_exposure_audit_opens_no_files(bundle, monkeypatch):
    args, kwargs = bundle
    def forbidden(*args, **kwargs): raise AssertionError('pure annotation helper opened a file')
    monkeypatch.setattr(Path, 'open', forbidden)
    result = audit.audit_scope_annotations(*args, **kwargs)
    assert result['new_documents'] == 672 and result['new_scope_pairs'] == 336
    assert result['train_full_factorial_combinations'] == 192
    assert result['source_hash_ids_contain_no_explicit_class_or_case_fields']
    assert result['class_neutral_source_order_shuffle_verified'] and not result['helper_opens_files']
    assert result['panels']['train']['heading_literals'] == {'dash': 192, 'period_bracket': 192}
    assert result['panels']['fresh']['heading_literals'] == {'dash': 96, 'period_bracket': 96}
    assert result['historical_layout_counts']['prior_scope_exposed_fresh'] == 192
    assert result['historical_unsupported_without_role_annotations']['prior_scope_exposed_fresh'] == 0
    assert sum(result['historical_unsupported_without_role_annotations'].values()) > 0
    assert result['fresh_matching_new_training_layout'] == 192


@pytest.mark.parametrize('change', ['duplicate_annotation', 'missing_annotation', 'source_hash', 'class_id', 'scope_pair',
    'pair_case', 'heading_factor', 'heading_literal', 'time_factor', 'time_position', 'modal_factor', 'mask_factor',
    'body_rule', 'facet_offset', 'editorial_overlap', 'scope_attachment', 'flatten_nested', 'fresh_order', 'metadata_label',
    'layout', 'layout_pool', 'history_reference', 'historical_layout', 'historical_guard_gap', 'history_source_commitment',
    'history_source_omission', 'new_overlap_claim', 'old_annotation'])
def test_independent_source_factor_scope_and_exposure_mutations_rejected(bundle, change):
    args, kwargs = deepcopy(bundle)
    inputs, targets, pairs, ledger, exposure = args
    by_id = {a['candidate_id']: a for a in ledger['document_rows']}
    chosen = next(r for r in targets if r['supported'] and by_id[r['candidate_id']]['factors']['child_time_kind'] == 'hours')
    a = by_id[chosen['candidate_id']]; child = a['local_clause_coordinates'][1]
    if change == 'duplicate_annotation': ledger['document_rows'][-1] = deepcopy(ledger['document_rows'][0])
    elif change == 'missing_annotation': ledger['document_rows'].pop()
    elif change == 'source_hash': a['source_sha256'] = '0' * 64
    elif change == 'class_id': targets[0]['candidate_id'] += '-nested'
    elif change == 'scope_pair': pairs[0]['nested_id'] = pairs[1]['nested_id']
    elif change == 'pair_case': a['case_group'] = 'other-case'
    elif change == 'heading_factor': a['factors']['heading'] = next(k for k in corpus.HEADINGS if k != a['family'])
    elif change == 'heading_literal': child['editorial_context'][0]['source_text'] = 'Other heading.'
    elif change == 'time_factor': a['factors']['child_time_kind'] = 'days'
    elif change == 'time_position': child['facet_spans']['temporal'][0] += 1
    elif change == 'modal_factor': a['factors']['first_modality'] = next(m for m in 'OPF' if m != a['factors']['first_modality'])
    elif change == 'mask_factor': a['factors']['first_CE_mask'] = (a['factors']['first_CE_mask'] + 1) % 4
    elif change == 'body_rule': child['rule']['actor'] = 'Another actor'
    elif change == 'facet_offset': child['facet_spans']['actor'][0] += 1
    elif change == 'editorial_overlap': child['editorial_context'][0]['end_char'] = child['facet_spans']['actor'][1]
    elif change == 'scope_attachment':
        negative = next(r for r in targets if not r['supported']); by_id[negative['candidate_id']]['scope_attachment']['child_occurrence'] = 0
    elif change == 'flatten_nested': next(r for r in targets if not r['supported'])['clauses'] = deepcopy(chosen['clauses'])
    elif change == 'fresh_order': inputs['sources']['scope_fresh'].reverse()
    elif change == 'metadata_label': inputs['sources']['scope_fresh'][0]['supported'] = True
    elif change == 'layout': exposure['rows'][0]['role_masked_layout'] += ' invented'
    elif change == 'layout_pool': exposure['rows'][0]['matching_pools'] = []
    elif change == 'history_reference': exposure['historical_document_references']['prior_scope']['sha256'] = '0' * 64
    elif change == 'historical_layout': exposure['historical_layout_rows']['prior_scope'][0]['role_masked_layout'] += ' invented'
    elif change == 'historical_guard_gap': exposure['historical_unannotated_unsupported_ids']['original'] = []
    elif change == 'history_source_commitment': exposure['historical_source_inventory_sha256'] = '0' * 64
    elif change == 'history_source_omission': kwargs['historical_source_inventory']['source_texts'] = []
    elif change == 'new_overlap_claim': exposure['new_source_overlap_count'] = 1
    else: kwargs['prior_scope_annotations']['ledger']['document_rows'][0]['local_clause_coordinates'][0]['facet_spans']['actor'][0] += 1
    with pytest.raises(ValueError): audit.audit_scope_annotations(*args, **kwargs)


def test_previous_scope_pair_verifier_accepts_new_opaque_admitted_ids():
    rows, pairs = [], []
    for case in range(3):
        values, pair, _ = corpus.make_pair('tuning', case); rows.extend(values); pairs.append(pair)
    assert verify_scope_pairs(rows, pairs, 3)['pairs'] == 3


def test_historical_unsupported_has_no_invented_role_layout():
    rows, _, _ = corpus.make_pair('tuning', 0)
    assert audit.historical_flat_layout(rows[1]) is None


def test_unambiguous_historical_atoms_required_even_after_source_hash_repair():
    rows, _, _ = corpus.make_pair('tuning', 0); row = deepcopy(rows[0])
    first = row['clauses'][0]; actor = first['rule']['actor']
    prefix = actor + ' ' + row['source_text']
    first['char_end'] += len(actor) + 1
    for later in row['clauses'][1:]:
        later['char_start'] += len(actor) + 1; later['char_end'] += len(actor) + 1
    row['source_text'] = prefix; row['source_sha256'] = audit.text_sha(prefix)
    with pytest.raises(ValueError, match='ambiguous'): audit.historical_flat_layout(row)
