"""Review refresh must preserve distinct contexts and never manufacture gold."""
import copy
import hashlib

import pytest

from scripts.ops.legal_ir import refresh_legal_statutory_review_predictions as refresh


def packet():
    text = 'Board shall file the notice.'
    hashed = hashlib.sha256(text.encode()).hexdigest()
    observation = {'source_span_id': 'span-1', 'source_text_variants': [text], 'training_qualified': False,
        'gold_target': None, 'legal_ids': ['usc:1'], 'available_context': 'fragment only',
        'context_review': {'status': 'pending'}, 'occurrence_count': 2}
    second = {**copy.deepcopy(observation), 'source_span_id': 'span-2', 'legal_ids': ['usc:2']}
    return {'repository': 'justicedao/uscode-autoformal-span-cache', 'training_qualified': False,
        'status': 'unreviewed', 'deduplication': {'unique_text_groups': 1, 'source_observations': 2},
        'groups': [{'text_group_id': 'source-text-sha256:' + hashed, 'source_text': text,
            'source_text_sha256': hashed, 'training_qualified': False, 'gold_target': None,
            'adjudication': None, 'independent_reviews': [], 'source_observations': [observation, second]}]}


def test_duplicate_text_retains_two_contexts_but_single_source_inference():
    sources, bindings = refresh.source_projection(packet())
    assert len(sources) == 1 and set(sources[0]) == {'id', 'source_text', 'source_sha256'}
    contexts = bindings[sources[0]['id']]
    assert [c['legal_ids'] for c in contexts] == [['usc:1'], ['usc:2']]
    assert all(c['gold_target'] is None and not c['training_qualified'] and not c['context_verified'] for c in contexts)


@pytest.mark.parametrize('field,value', [('gold_target', {'rules': []}), ('training_qualified', True),
    ('adjudication', {}), ('independent_reviews', [{'reviewer': 'already submitted'}])])
def test_existing_review_or_admission_cannot_be_silently_overwritten(field, value):
    value_packet = packet(); value_packet['groups'][0][field] = value
    with pytest.raises(ValueError, match='adjudication'): refresh.source_projection(value_packet)


@pytest.mark.parametrize('change', ['hash', 'duplicate_span', 'wrong_context_text', 'incomplete'])
def test_source_identity_and_complete_observation_denominator(change):
    value = packet(); group = value['groups'][0]
    if change == 'hash': group['source_text_sha256'] = 'bad'
    elif change == 'duplicate_span': group['source_observations'][1]['source_span_id'] = 'span-1'
    elif change == 'wrong_context_text': group['source_observations'][0]['source_text_variants'] = ['another text']
    else: value['deduplication']['source_observations'] = 3
    with pytest.raises(ValueError): refresh.source_projection(value)


def test_inference_boundary_rejects_producer_formula_or_gold_metadata():
    sources, _ = refresh.source_projection(packet())
    sources[0]['producer_formula'] = 'not an authorized inference input'
    with pytest.raises(ValueError, match='only source text'):
        refresh.source_only_generate(None, sources, parent=False)


def model_freeze():
    models = []
    for arm in ('prior_continuation', 'prior_grounding', 'document_retained_continuation', 'document_retained_grounding', 'parent'):
        for seed in (1729, 1730, 1731):
            parent, enabled = arm == 'parent', arm.endswith('_grounding')
            models.append({'name': f'{arm}-{seed}', 'arm': arm, 'seed': seed, 'new_optimizer_steps': 0,
                'architecture': 'parent' if parent else 'grounding' if enabled else 'continuation',
                'curriculum': 'parent' if parent else 'temporal_augmented', 'decoder_kind': 'parent' if parent else 'mixed',
                'selection': 'unchanged_parent' if parent else 'prior_selected' if arm.startswith('prior_') else 'candidate',
                'selected_steps': 0 if parent else 800, 'enabled': enabled, 'requested_enabled': enabled})
    return {'schema': 'legal-construction-retention-experiment/v1', 'all_selection_and_generation_complete': True,
        'challenge_targets_opened': False, 'regression_targets_opened': False, 'executed_optimizer_updates': 0,
        'training_executed': False, 'models': models}


@pytest.mark.parametrize('field,value', [('all_selection_and_generation_complete', False),
    ('challenge_targets_opened', True), ('regression_targets_opened', True),
    ('executed_optimizer_updates', 1), ('executed_optimizer_updates', False)])
def test_model_freeze_requires_finished_reference_free_selection(field, value):
    frozen = model_freeze()
    assert len(refresh.validate_model_freeze(frozen)) == 15
    frozen[field] = value
    with pytest.raises(ValueError, match='reference-free'): refresh.validate_model_freeze(frozen)


@pytest.mark.parametrize('field,value', [('name', '../escape'), ('seed', 1732), ('architecture', 'wrong'),
    ('enabled', True), ('curriculum', 'baseline')])
def test_model_bank_rejects_slot_or_attribution_substitution(field, value):
    frozen = model_freeze(); frozen['models'][0][field] = value
    with pytest.raises(ValueError): refresh.validate_model_freeze(frozen)


def test_baseline_fallback_keeps_its_actual_curriculum():
    frozen = model_freeze()
    slot = next(m for m in frozen['models'] if m['arm'] == 'document_retained_grounding')
    slot['selection'], slot['curriculum'] = 'baseline_fallback', 'baseline'
    assert len(refresh.validate_model_freeze(frozen)) == 15
    slot['curriculum'] = 'temporal_augmented'
    with pytest.raises(ValueError, match='fallback'): refresh.validate_model_freeze(frozen)
