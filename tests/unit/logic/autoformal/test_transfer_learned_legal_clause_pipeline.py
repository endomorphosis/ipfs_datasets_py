from copy import deepcopy
import pytest
from scripts.ops.legal_ir import transfer_learned_legal_clause_pipeline as subject


def inventory():
    parents = [{'name': f'parent-{s}', 'arm': 'parent', 'seed': s, 'enabled': False, 'checkpoint': {'sha256': str(s)}} for s in subject.SEEDS]
    heads = [{'name': f'{arm}-{s}', 'arm': arm, 'seed': s, 'enabled': arm == 'trigger_grounding',
        'parent': {'sha256': str(s)}, 'checkpoint': {'sha256': arm + str(s)}} for arm in subject.ARMS[:2] for s in subject.SEEDS]
    models = heads + parents
    return {'schema': subject.grounding_run.SCHEMA, 'all_training_selection_and_generation_complete': True,
        'challenge_targets_opened': False, 'models': models, 'files': {r['name']: {} for r in models}}, heads


def test_full_nine_model_inventory():
    assert len(subject.model_inventory(*inventory())) == 9


@pytest.mark.parametrize('mutation', ['drop', 'duplicate', 'wrong_parent', 'wrong_branch'])
def test_reject_dropped_duplicated_or_misbound_models(mutation):
    frozen, heads = deepcopy(inventory())
    if mutation == 'drop': frozen['models'].pop()
    elif mutation == 'duplicate': frozen['models'][-1] = frozen['models'][-2]
    elif mutation == 'wrong_parent': frozen['models'][0]['parent'] = {'sha256': 'wrong'}
    else: frozen['models'][0]['enabled'] = True
    with pytest.raises(ValueError):
        subject.model_inventory(frozen, heads)


def fixtures():
    targets = {str(i): {'candidate_id': str(i), 'source_sha256': str(i), 'supported': i < 3,
        'clauses': [{'rule': {'actor': 'Agency'}}] if i < 3 else [], 'repeated_rule_occurrences': False} for i in range(4)}
    rows = [{'candidate_id': str(i), 'source_sha256': str(i), 'segmentation_status': 'segmented' if i < 3 else 'abstained',
        'composition': {'source_rule_list': [{'actor': 'Agency' if i == 0 else 'Wrong'}]} if i < 2 else None,
        'status': 'composed' if i < 2 else 'abstained', 'reason': None} for i in range(4)]
    return rows, targets


def test_full_denominator_includes_scope_and_decoder_abstentions_and_compiled_wrong():
    rows, targets = fixtures()
    measured = subject.score_documents(rows, targets, {'0', '1'})
    assert measured['documents'] == 4
    assert measured['supported_documents'] == 3
    assert measured['scope_abstentions'] == measured['decoder_or_composition_abstentions'] == 1
    assert measured['built_documents'] == 2 and measured['built_reference_mismatch'] == 1
    assert measured['exact_supported_documents'] == 1 and measured['whole_document_decision_exact'] == 2


def test_rejects_dropped_duplicate_document_and_changed_source():
    rows, targets = fixtures()
    for changed in (rows[:-1], [rows[0], *rows[:-1]]):
        with pytest.raises(ValueError, match='denominator'):
            subject.score_documents(changed, targets, set())
    rows[0]['source_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='source differs'):
        subject.score_documents(rows, targets, set())
