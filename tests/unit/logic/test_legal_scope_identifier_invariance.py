from copy import deepcopy
import pytest

from scripts.ops.legal_ir import audit_legal_scope_identifier_invariance as audit


def example():
    text = 'Registry must retain records.'
    source = {'candidate_id': 'visible-independent-id', 'source_text': text, 'source_sha256': audit.boundary.text_sha(text)}
    renamed = audit.opaque_sources([source])[0]
    tokens = audit.boundary.tokenize(text); ends = [len(tokens) - 1]
    row = {'candidate_id': source['candidate_id'], 'source_sha256': source['source_sha256'], 'boundary_logits': [-1.] * (len(tokens) - 1) + [2.],
           'boundary_token_indices': ends, 'scope_logits': [-2., 2.], 'scope_supported_probability': .98,
           'raw_learned_scope_supported': True, 'predicted_rule_count': 1, 'status': 'segmented', 'reason': None,
           'plan': audit.boundary.source_plan(source, tokens, ends), 'target_access': False}
    return source, renamed, {'rows': [row], 'reports': [{'rows': [deepcopy(row)], 'target_access': False}], 'target_access': False}


def test_opaque_ids_independent_of_original_identity_or_text():
    source, renamed, _ = example()
    other = {**source, 'candidate_id': 'visible-nested-id', 'source_text': 'Other', 'source_sha256': audit.boundary.text_sha('Other')}
    assert audit.opaque_sources([other])[0]['candidate_id'] == renamed['candidate_id']
    assert renamed['candidate_id'].startswith('opaque-') and renamed['candidate_id'] != source['candidate_id']


def test_complete_generation_matches_only_after_valid_plan_rebinding():
    source, renamed, original = example()
    actual = audit.expected_generation(original, [source], [renamed])
    result = audit.assert_generation_invariance(original, actual, [source], [renamed])
    assert result['all_output_fields_equal_after_identity_rebinding']
    assert actual['rows'][0]['plan']['plan_sha256'] != original['rows'][0]['plan']['plan_sha256']
    assert actual['rows'][0]['plan']['clauses'] == original['rows'][0]['plan']['clauses']


@pytest.mark.parametrize('field', ['scope_logits', 'boundary_logits', 'status', 'plan', 'report_copy', 'target_access'])
def test_any_nonidentity_numerical_or_final_change_is_rejected(field):
    source, renamed, original = example(); changed = audit.expected_generation(original, [source], [renamed])
    if field == 'report_copy': changed['reports'][0]['rows'][0]['target_access'] = True
    elif field == 'target_access': changed[field] = True
    elif field == 'plan': changed['rows'][0]['plan']['clauses'][0]['char_end'] -= 1
    else: changed['rows'][0][field] = 'different'
    with pytest.raises(ValueError, match='opaque ID changed'):
        audit.assert_generation_invariance(original, changed, [source], [renamed])


def test_source_text_change_is_not_permitted_identity_rebinding():
    source, renamed, original = example(); renamed['source_text'] += ' changed'
    with pytest.raises(ValueError, match='only source identity'):
        audit.expected_generation(original, [source], [renamed])
