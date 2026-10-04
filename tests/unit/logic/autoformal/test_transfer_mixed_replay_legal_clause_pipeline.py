from copy import deepcopy
import pytest
from scripts.ops.legal_ir import transfer_mixed_replay_legal_clause_pipeline as subject


def inventory(fallback=False):
    parents = [{'name': f'parent-{seed}', 'arm': 'parent', 'seed': seed, 'enabled': False,
        'requested_enabled': False, 'decoder_kind': 'parent', 'selection': 'unchanged_parent',
        'selected_steps': 0, 'executed_steps': 0, 'checkpoint': {'sha256': str(seed)}} for seed in subject.SEEDS]
    heads = []
    for arm in subject.ARMS[:2]:
        for seed in subject.SEEDS:
            parent = {'sha256': str(seed)}
            stages = [{'steps': steps, 'tuning_earlier_exact': 80 if fallback else 96,
                'tuning_new_exact': steps // 100, 'checkpoint': {'sha256': f'{arm}-{seed}-{steps}'}} for steps in (400, 800)]
            heads.append({'name': f'{arm}-{seed}', 'arm': arm, 'seed': seed, 'enabled': arm == 'mixed_grounding' and not fallback,
                'requested_enabled': arm == 'mixed_grounding', 'parent': parent, 'parent_tuning_exact': {'earlier': 96, 'new': 0},
                'selected_steps': 0 if fallback else 800, 'executed_steps': 800,
                'decoder_kind': 'parent' if fallback else 'mixed', 'selection': 'parent_fallback' if fallback else 'candidate',
                'checkpoint': parent if fallback else stages[-1]['checkpoint'], 'stages': stages})
    models = heads + parents
    return {'schema': subject.mixed_run.SCHEMA, 'all_training_selection_and_generation_complete': True,
        'challenge_targets_opened': False, 'regression_targets_opened': False,
        'retention_gate_failures': [row['name'] for row in heads] if fallback else [],
        'models': models, 'files': {row['name']: {} for row in models}}, heads


@pytest.mark.parametrize('fallback', [False, True])
def test_all_nine_slots_retained_even_when_every_candidate_falls_back(fallback):
    assert len(subject.model_inventory(*inventory(fallback))) == 9


@pytest.mark.parametrize('mutation', ['drop', 'duplicate', 'wrong_parent', 'wrong_branch', 'wrong_decoder',
    'drop_stage', 'wrong_selection', 'wrong_checkpoint', 'unrecorded_failure', 'target_opened'])
def test_reject_malformed_inventory_or_selection(mutation):
    frozen, heads = deepcopy(inventory())
    row = heads[0]
    if mutation == 'drop': frozen['models'].pop()
    elif mutation == 'duplicate': frozen['models'][-1] = frozen['models'][-2]
    elif mutation == 'wrong_parent': row['parent'] = {'sha256': 'wrong'}
    elif mutation == 'wrong_branch': row['enabled'] = True
    elif mutation == 'wrong_decoder': row['decoder_kind'] = 'parent'
    elif mutation == 'drop_stage': row['stages'].pop()
    elif mutation == 'wrong_selection': row['selection'] = 'parent_fallback'
    elif mutation == 'wrong_checkpoint': row['checkpoint'] = row['stages'][0]['checkpoint']
    elif mutation == 'unrecorded_failure': frozen['retention_gate_failures'] = [row['name']]
    else: frozen['regression_targets_opened'] = True
    with pytest.raises(ValueError):
        subject.model_inventory(frozen, heads)


def test_reject_fallback_masquerading_as_trained_candidate():
    frozen, heads = inventory(True)
    heads[0]['decoder_kind'] = 'mixed'
    with pytest.raises(ValueError, match='fallback'):
        subject.model_inventory(frozen, heads)


@pytest.mark.parametrize('fallback', [False, True])
def test_all_three_parents_match_exact_payload_and_fallback_occurrences(monkeypatch, fallback):
    frozen, _ = inventory(fallback)
    models = frozen['models']
    prior = {'all_models_completed': True, 'reference_targets_opened': False,
        'models': {f'parent-{seed}': {'path': f'parent-{seed}'} for seed in subject.SEEDS}}
    rows = {row['name']: [{'example': row['seed']}, {'example': row['seed']}] for row in models}
    prior_payload = {f'parent-{seed}': {'checkpoint': {'sha256': str(seed)}, 'rows': deepcopy(rows[f'parent-{seed}'])} for seed in subject.SEEDS}
    monkeypatch.setattr(subject, 'read_ref', lambda ref: prior_payload[ref['path']])
    assert len(subject.reproduce_parents(rows, models, prior, {'models': models})) == 3
    rows['parent-1731'][1]['example'] = 'corrupt second occurrence'
    with pytest.raises(ValueError, match='differs'):
        subject.reproduce_parents(rows, models, prior, {'models': models})


def test_fallback_generation_must_equal_its_matching_parent(monkeypatch):
    frozen, _ = inventory(True)
    models = frozen['models']
    prior = {'all_models_completed': True, 'reference_targets_opened': False,
        'models': {f'parent-{seed}': {'path': f'parent-{seed}'} for seed in subject.SEEDS}}
    rows = {row['name']: [{'seed': row['seed']}] for row in models}
    parent_by_name = {row['name']: row for row in models if row['arm'] == 'parent'}
    monkeypatch.setattr(subject, 'read_ref', lambda ref: {
        'checkpoint': parent_by_name[ref['path']]['checkpoint'], 'rows': rows[ref['path']]})
    rows['mixed_grounding-1729'] = [{'seed': 1730}]
    with pytest.raises(ValueError, match='fallback output'):
        subject.reproduce_parents(rows, models, prior, {'models': models})


def test_full_denominator_and_duplicate_occurrences_remain_in_scoring():
    rule = {'actor': 'Agency'}
    targets = {'a': {'candidate_id': 'a', 'source_sha256': 'a', 'supported': True,
        'clauses': [{'rule': rule}, {'rule': rule}], 'repeated_rule_occurrences': True},
        'b': {'candidate_id': 'b', 'source_sha256': 'b', 'supported': True,
        'clauses': [{'rule': rule}], 'repeated_rule_occurrences': False},
        'c': {'candidate_id': 'c', 'source_sha256': 'c', 'supported': False,
        'clauses': [], 'repeated_rule_occurrences': False}}
    rows = [{'candidate_id': 'a', 'source_sha256': 'a', 'segmentation_status': 'segmented',
        'composition': {'source_rule_list': [rule, rule]}, 'status': 'composed', 'reason': None},
        {'candidate_id': 'b', 'source_sha256': 'b', 'segmentation_status': 'segmented',
        'composition': None, 'status': 'abstained', 'reason': 'decoder'},
        {'candidate_id': 'c', 'source_sha256': 'c', 'segmentation_status': 'abstained',
        'composition': None, 'status': 'abstained', 'reason': 'scope'}]
    score = subject.score_documents(rows, targets, {'a'})
    assert score['documents'] == 3 and score['supported_documents'] == 2
    assert score['composed_rule_occurrences'] == 2 and score['repeated_exact_documents'] == 1
    assert score['scope_abstentions'] == score['decoder_or_composition_abstentions'] == 1
    assert score['exact_supported_documents'] == 1 and score['whole_document_decision_exact'] == 2


def test_load_dispatches_by_decoder_kind_even_for_named_grounding_fallback(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    calls = []
    def dimensions_load(path, *, expected_sha256):
        calls.append(('parent', path, expected_sha256)); return 'parent-checkpoint'
    def mixed_load(path, *, expected_sha256):
        calls.append(('mixed', path, expected_sha256)); return 'mixed-checkpoint'
    monkeypatch.setattr(dimensions, 'load_checkpoint', dimensions_load)
    monkeypatch.setattr(mixed, 'load_checkpoint', mixed_load)
    monkeypatch.setattr(dimensions, 'DimensionalSpanDecoder', lambda cp: ('parent', cp))
    monkeypatch.setattr(mixed, 'MixedReplayDecoder', lambda cp: ('mixed', cp))
    row = {'arm': 'mixed_grounding', 'decoder_kind': 'parent', 'checkpoint': {'path': '/parent', 'sha256': 'hash'}}
    assert subject.load(row) == ('parent', 'parent-checkpoint')
    row['decoder_kind'] = 'mixed'
    assert subject.load(row) == ('mixed', 'mixed-checkpoint')
    assert [call[0] for call in calls] == ['parent', 'mixed']
