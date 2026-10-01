"""The positive fixture is distinct from unsupported precondition-driven state."""
import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_semantic_projection_panel as panel
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v3 import prepare_native_family_lean


@pytest.mark.parametrize('index',[0,1,2])
def test_effect_only_Intent_fixture_prepares_every_projection_without_claiming_guard_support(index):
    case=panel.prepare_case('intent_ir',index)
    report=case['report']
    prepared=prepare_native_family_lean(report,source_inputs=case['source_inputs'])
    assert all(r['semantic_lowering_supported'] for r in prepared['per_projection'])
    assert len(report['requested_families'])==40
    assert any(p['projection_id']=='intent-route/workflow-temporal/v1' for p in report['projections'])
    assert case['fixture']['intent_contract_scope']=='effect_only_contract_with_separate_assumption_no_state_guard'
    assert case['fixture']['known_unsupported_binding']=='action_preconditions_have_no_reviewed_state_binding'
    assert not prepared['backend_executed']


def test_precondition_enabled_source_remains_blocked_without_dropping_workflow():
    case=panel.prepare_case('intent_ir',0,include_intent_precondition=True)
    prepared=prepare_native_family_lean(case['report'],source_inputs=case['source_inputs'])
    workflow=next(r for r in prepared['per_projection'] if r['projection_id']=='intent-route/workflow-temporal/v1')
    assert not workflow['semantic_lowering_supported']
    assert workflow['reason']=='workflow_requires_unique_exact_native_linear_state_projection'
    assert 'action_preconditions_have_no_reviewed_state_binding' in str(case['report']['frontier'])
    assert case['fixture']['intent_contract_scope']=='diagnostic_precondition_plus_effect'
