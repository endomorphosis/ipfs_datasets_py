from copy import deepcopy
import pytest
from scripts.ops.legal_ir import summarize_legal_construction_retention_experiment as subject


def stages(a=(95, 50, 80, 60), b=(95, 50, 80, 60)):
    return [{'steps': step, 'earlier_exact': v[0], 'prior_new_exact': v[1], 'temporal_exact': v[2], 'document_exact': v[3]}
            for step, v in zip((400, 800), (a, b))]


def test_gate_protects_matched_baseline_documents_even_when_source_parent_would_pass():
    assert subject.retention_choice(stages(a=(96, 96, 120, 58), b=(96, 96, 119, 59)), 96, 61, 96) is None
    assert subject.retention_choice(stages(a=(95, 50, 80, 60), b=(94, 96, 120, 72)), 96, 61, 96)['steps'] == 400
    with pytest.raises(ValueError, match='fallback violates'):
        subject.retention_choice(stages(), 96, 61, 94)


def test_gate_ranks_temporal_then_document_then_prior_new_then_earlier_then_earliest():
    assert subject.retention_choice(stages(), 96, 61, 96)['steps'] == 400
    for a, b in [((95, 50, 80, 60), (96, 50, 80, 60)),
                 ((96, 50, 80, 60), (95, 51, 80, 60)),
                 ((96, 96, 80, 60), (95, 0, 80, 61)),
                 ((96, 96, 80, 72), (95, 0, 81, 60))]:
        assert subject.retention_choice(stages(a, b), 96, 61, 96)['steps'] == 800


@pytest.mark.parametrize('mutation', ['fresh_score', 'bool', 'out_of_bounds', 'duplicate_step'])
def test_gate_rejects_unadmitted_metrics(mutation):
    rows = stages()
    if mutation == 'fresh_score': rows[0]['fresh_document_exact'] = 72
    elif mutation == 'bool': rows[0]['document_exact'] = True
    elif mutation == 'out_of_bounds': rows[0]['document_exact'] = 73
    else: rows[1]['steps'] = 400
    with pytest.raises(ValueError): subject.retention_choice(rows, 96, 61, 96)


def inventory():
    items = [{'name': f'{arm}-{seed}', 'enabled': arm.endswith('grounding'), 'decoder_kind': 'mixed'} for arm in subject.ARMS for seed in subject.SEEDS]
    items += [{'name': f'parent-{seed}', 'enabled': False, 'decoder_kind': 'parent'} for seed in subject.SEEDS]
    singles = {r['name']: {panel: {} for panel in subject.SINGLE_COUNTS} for r in items}
    documents = {r['name']: {panel: {} for panel in subject.DOCUMENT_COUNTS} for r in items}
    for row in items:
        if row['enabled']: singles[row['name']]['fresh_disabled'] = {}
    return items, singles, documents


def test_complete_inventory_keeps_baseline_fallback_as_mixed_grounding():
    items, singles, documents = inventory()
    for row in items:
        if row['name'].startswith('document_retained'): row['selection'] = 'baseline_fallback'
    assert subject.verify_panel_inventory(items, singles, documents) == {'single_rows': 18900, 'document_rows': 4320, 'model_slots': 15}


@pytest.mark.parametrize('mutation', ['document', 'single', 'control', 'parent', 'fallback_disabled'])
def test_complete_inventory_rejects_dropped_rows_or_fallback_control(mutation):
    items, singles, documents = inventory()
    if mutation == 'document': documents['prior_grounding-1729'].pop('fresh_documents')
    elif mutation == 'single': singles['prior_continuation-1730'].pop('temporal_regression')
    elif mutation == 'control': singles['document_retained_grounding-1730'].pop('fresh_disabled')
    elif mutation == 'parent': documents.pop('parent-1731')
    else:
        row = next(r for r in items if r['name'] == 'document_retained_grounding-1730')
        row['enabled'] = False; singles[row['name']].pop('fresh_disabled')
    with pytest.raises(ValueError): subject.verify_panel_inventory(items, singles, documents)


def documents():
    rule = {'actor': 'Agency'}
    sources = [{'candidate_id': str(i), 'source_sha256': str(i)} for i in range(4)]
    targets = [{**source, 'supported': i < 3, 'clauses': [{'rule': rule, 'char_start': 0, 'char_end': 5}, {'rule': rule, 'char_start': 6, 'char_end': 11}] if i < 3 else []} for i, source in enumerate(sources)]
    rows = [{**source, 'status': 'composed' if i != 2 else 'abstained', 'segmentation_status': 'segmented',
             'composition': None if i == 2 else {'source_rule_list': [rule, rule] if i == 0 else [rule], 'source_plan': {'clauses': [{'char_start': 0, 'char_end': 5}, {'char_start': 6, 'char_end': 11}]}}} for i, source in enumerate(sources)]
    return {'rows': rows}, sources, targets


def test_document_scores_keep_rule_count_mismatch_abstention_and_unsupported_acceptance():
    measured = subject.score_documents(*documents())
    assert measured['count'] == 4 and measured['supported'] == 3
    assert measured['composed'] == 3 and measured['abstained'] == 1
    assert measured['exact'] == measured['decision_exact'] == 1
    assert measured['unsupported_accepted'] == 1
    assert measured['rows'][1]['exact'] is False  # Accepted one-rule merge of two references.


@pytest.mark.parametrize('mutation', ['dropped', 'duplicate', 'wrong_source', 'status'])
def test_document_scores_reject_corrupt_joins_without_dropping_real_errors(mutation):
    generation, sources, targets = documents()
    if mutation == 'dropped': generation['rows'].pop()
    elif mutation == 'duplicate': generation['rows'][1] = generation['rows'][0]
    elif mutation == 'wrong_source': targets[0]['source_sha256'] = 'changed'
    else: generation['rows'][0]['status'] = 'abstained'
    with pytest.raises(ValueError): subject.score_documents(generation, sources, targets)


def test_matching_repeated_rules_with_wrong_occurrence_boundary_fail_joint_exactness():
    generation, sources, targets = documents()
    generation['rows'][0]['composition']['source_plan']['clauses'][0]['char_end'] = 4
    result = subject.score_documents(generation, sources, targets)
    assert result['canonical_rule_list_exact'] == 1 and result['exact'] == 0
    assert result['rows'][0]['canonical_rule_list_exact'] is True
    assert result['rows'][0]['occurrence_boundaries_exact'] is False


def test_masked_layout_removes_entity_modal_and_citation_variation_but_keeps_clause_order():
    def row(actor, modal, number, letter):
        text = f'Under section {number}({letter}), {actor} {modal} file.'
        start = text.index(actor)
        return {'source_text': text, 'facet_spans': {'actor': [start, start + len(actor)],
            'action': [text.index('file'), text.index('file') + 4]}}
    a, b = row('Agency May Office', 'must not', 12, 'a'), row('Other Authority', 'has a duty to', 99, 'q')
    assert subject.independent_layout(a) == subject.independent_layout(b)
    assert subject.independent_layout(a) == 'under section #(#), <actor> <modal> <action>'
    changed = deepcopy(a); changed['facet_spans']['action'] = [0, len(changed['source_text'])]
    with pytest.raises(ValueError, match='overlap'): subject.independent_layout(changed)


def test_historical_document_exposure_refuses_ambiguous_atom_instead_of_guessing():
    rule = {'actor': 'Agency', 'action': 'file', 'object': 'reports', 'conditions': [], 'exceptions': [], 'temporal': []}
    text = 'Agency must file reports.'
    documents = [{'candidate_id': 'a', 'source_text': text, 'clauses': [{'char_start': 0, 'char_end': len(text), 'rule': rule}]}]
    clauses = subject.document_audit_clauses(documents)
    assert subject.independent_layout(clauses[0]) == '<actor> <modal> <action> <object>'
    documents[0]['source_text'] = 'Agency tells Agency to file reports.'
    documents[0]['clauses'][0]['char_end'] = len(documents[0]['source_text'])
    with pytest.raises(ValueError, match='ambiguous'): subject.document_audit_clauses(documents)


def document_build_fixture():
    selection = {'rows': [{'candidate': {'candidate_id': '0'}}],
                 'excluded': [{'candidate_id': str(i)} for i in range(1, 96)]}
    metric = {'composed': 1, 'abstained': 95,
              'rows': [{'id': str(i), 'exact': False, 'canonical_rule_list_exact': i == 0} for i in range(96)]}
    batches = [{'candidate_ids': ['0'], 'build_passed': True, 'backend_executed': True}]
    return selection, batches, metric


def test_document_build_counts_canonical_coincidence_with_wrong_boundaries_as_compiled_mismatch():
    result = subject.document_build_accounting(*document_build_fixture())
    assert result['count'] == 96 and result['built'] == result['built_canonical_only_exact'] == 1
    assert result['built_exact'] == 0 and result['built_reference_mismatch'] == 1
    assert result['abstained'] == 95


@pytest.mark.parametrize('mutation', ['dropped_abstention', 'missing_batch'])
def test_document_build_rejects_incomplete_denominator_or_batch(mutation):
    selection, batches, metric = document_build_fixture()
    if mutation == 'dropped_abstention': selection['excluded'].pop()
    else: batches[0]['candidate_ids'] = []
    with pytest.raises(ValueError): subject.document_build_accounting(selection, batches, metric)
