"""Pure audit fixtures use admitted TRAIN grammar and fictional fresh entities.

No sealed study targets are opened or regenerated. The fictional fresh panel is
a length-preserving rename of train cases, not the actual fresh renderer branch.
"""
from copy import deepcopy
import pytest

from scripts.ops.legal_ir import prepare_legal_scope_retention_corpus as corpus
from scripts.ops.legal_ir import summarize_legal_scope_retention_annotations as audit


def renamed(value):
    if isinstance(value, dict): return {k: renamed(v) for k, v in value.items()}
    if isinstance(value, list): return [renamed(v) for v in value]
    if isinstance(value, str):
        return value.replace('Hemlockscope', 'Fictionscope').replace('hemlockscope', 'fictionscope').replace('scope-train', 'scope-fresh')
    return value


def fixture_pair(panel, case):
    if panel != 'fresh': return corpus.make_pair(panel, case)
    original = corpus.make_pair('train', case)
    rows, pair, annotations = [renamed(v) for v in original]
    identities = {}
    for row, annotation in zip(rows, annotations, strict=True):
        old_id = row['candidate_id']; row['source_sha256'] = audit.text_sha(row['source_text'])
        row['candidate_id'] = old_id.rsplit('-', 1)[0] + '-' + row['source_sha256'][:16]
        identities[old_id] = row['candidate_id']
        annotation['candidate_id'] = row['candidate_id']; annotation['source_sha256'] = row['source_sha256']; annotation['panel'] = 'fresh'
        for occurrence in annotation['local_clause_coordinates']:
            occurrence['source_sha256'] = audit.text_sha(occurrence['source_text'])
    pair['independent_id'] = identities[pair['independent_id']]; pair['nested_id'] = identities[pair['nested_id']]
    pair['local_clause_body_sha256'] = [r['source_sha256'] for r in annotations[0]['local_clause_coordinates']]
    return rows, pair, annotations


@pytest.fixture(scope='module')
def bundle():
    panels, pairs, annotations = {}, {}, []
    for panel, count in (('train', 96), ('tuning', 48), ('fresh', 96)):
        panels[panel], pairs[panel] = [], []
        for case in range(count):
            rows, pair, anns = fixture_pair(panel, case)
            panels[panel].extend(rows); pairs[panel].append(pair); annotations.extend(anns)
    lookup = {r['candidate_id']: r for r in annotations}
    layouts = {p: {r['candidate_id']: corpus.role_layout(r, lookup[r['candidate_id']]) for r in rows} for p, rows in panels.items()}
    known = {p: sorted(set(layouts[p].values())) for p in ('train', 'tuning')}
    exposure = {'schema': 'legal-scope-retention-exposure/v1', 'rows': [], 'known_new_layouts': known,
                'historical_retention_references': {}, 'new_source_overlap_count': 0}
    for row in panels['fresh']:
        layout = layouts['fresh'][row['candidate_id']]
        matches = [p for p in ('train', 'tuning') if layout in known[p]]
        exposure['rows'].append({'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'],
            'case_group': lookup[row['candidate_id']]['case_group'], 'role_masked_layout': layout, 'matching_new_pools': matches,
            'layout_status': 'matched_new_layout' if matches else 'unmatched_new_combination'})
    inputs = {'new_train': panels['train'], 'training_pairs': pairs['train'], 'tuning_pairs': pairs['tuning'],
              'tuning': {'scope_new': panels['tuning']}, 'sources': {'scope_fresh': [corpus.source_row(r) for r in panels['fresh']]},
              'manifest': {'retention_target_references': {}}, 'replay': []}
    return inputs, panels['fresh'], pairs['fresh'], {'schema': 'legal-scope-retention-annotations/v1', 'document_rows': annotations}, exposure


def test_complete_pure_audit_and_explicit_realized_limitations(bundle):
    result = audit.audit_scope_annotations(*bundle)
    assert result['all480_source_role_and_attachment_annotations_reconstructed']
    assert result['all240_contrasts_preserve_complete_local_roles']
    assert result['fresh_rows_matching_new_training_layout'] == 192
    assert result['identifier_class_tokens'] == {'independent_token': 96, 'nested_token': 96}
    assert result['realized_heading_counts']['train'] == {'standalone_record_duty_heading': 0, 'numbered_dot_emdash_heading': 96}
    assert result['historical_full_single_plus_document_inventory_commitment_recomputed'] is False
    assert result['new_files_opened_by_helper'] is False


@pytest.mark.parametrize('mutation', ['missing_annotation', 'duplicate_annotation', 'source_hash', 'role_offset', 'role_atom',
    'modality', 'trigger_offset', 'positive_interval', 'negative_flat_target', 'attachment', 'cue', 'editorial',
    'pair_local_semantics', 'case_owner', 'repeated_flag', 'fresh_source_order', 'layout', 'known_layouts', 'matching_pool', 'extra_exposure'])
def test_independent_annotation_mutations_fail_closed(bundle, mutation):
    inputs, targets, pairs, ledger, exposure = deepcopy(bundle)
    anns = {r['candidate_id']: r for r in ledger['document_rows']}
    row = targets[0]; ann = anns[row['candidate_id']]
    if mutation == 'missing_annotation': ledger['document_rows'].pop()
    elif mutation == 'duplicate_annotation': ledger['document_rows'][-1] = deepcopy(ledger['document_rows'][0])
    elif mutation == 'source_hash': ann['source_sha256'] = '0' * 64
    elif mutation == 'role_offset': ann['local_clause_coordinates'][0]['facet_spans']['actor'][0] += 1
    elif mutation == 'role_atom': ann['local_clause_coordinates'][0]['rule']['actor'] = 'Different actor'
    elif mutation == 'modality': ann['local_clause_coordinates'][0]['rule']['modality'] = 'F'
    elif mutation == 'trigger_offset': ann['local_clause_coordinates'][0]['trigger_span'][1] -= 1
    elif mutation == 'positive_interval': row['clauses'][0]['char_end'] -= 1
    elif mutation == 'negative_flat_target': targets[1]['clauses'] = deepcopy(row['clauses'])
    elif mutation == 'attachment': anns[targets[1]['candidate_id']]['scope_attachment']['child_occurrence'] = 0
    elif mutation == 'cue':
        chosen = next(a for a in ledger['document_rows'] if a['local_clause_coordinates'][0]['qualifier_cues'])
        chosen['local_clause_coordinates'][0]['qualifier_cues'][0]['end_char'] -= 1
    elif mutation == 'editorial':
        chosen = next(a for a in ledger['document_rows'] if a['local_clause_coordinates'][1]['editorial_context'])
        chosen['local_clause_coordinates'][1]['editorial_context'][0]['source_text'] = 'Wrong heading'
    elif mutation == 'pair_local_semantics': anns[targets[1]['candidate_id']]['local_clause_coordinates'][0]['rule']['object'] = 'Different object'
    elif mutation == 'case_owner': ann['case_group'] = 'different-case'
    elif mutation == 'repeated_flag': row['repeated_rule_occurrences'] = True
    elif mutation == 'fresh_source_order': inputs['sources']['scope_fresh'].reverse()
    elif mutation == 'layout': exposure['rows'][0]['role_masked_layout'] += ' invented'
    elif mutation == 'known_layouts': exposure['known_new_layouts']['train'].pop()
    elif mutation == 'matching_pool': exposure['rows'][0]['matching_new_pools'] = []
    else: exposure['rows'].append(deepcopy(exposure['rows'][0]))
    with pytest.raises(ValueError): audit.audit_scope_annotations(inputs, targets, pairs, ledger, exposure)


def test_exact_source_reuse_against_admitted_history_rejected(bundle):
    inputs, targets, pairs, ledger, exposure = deepcopy(bundle)
    historical = deepcopy(targets[0]); historical['candidate_id'] = 'historical-other-id'
    inputs['replay'].append(historical)
    with pytest.raises(ValueError, match='historical'):
        audit.audit_scope_annotations(inputs, targets, pairs, ledger, exposure)
