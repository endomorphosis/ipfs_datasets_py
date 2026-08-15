from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import FormalView
from ipfs_datasets_py.logic.ui_ux_ir.formalize.event_calculus import compile_behavior_to_event_calculus
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition

def test_event_calculus_compiles_transitions_deterministically():
    model = BehaviorModel(
        model_id="bm",
        states=(BehaviorState(state_id="idle"), BehaviorState(state_id="done", terminal=True)),
        transitions=(
            BehaviorTransition(
                transition_id="t1",
                source_state_ids=("idle",),
                target_state_id="done",
                event_id="submit",
                timeout_ms=1000,
            ),
        ),
        initial_state_ids=("idle",),
    )
    a = compile_behavior_to_event_calculus(model)
    b = compile_behavior_to_event_calculus(model)
    assert a.formulas == b.formulas
    assert a.view is FormalView.EVENT_CALCULUS
    kinds = {f.kind for f in a.formulas}
    assert "happens" in kinds and "initiates" in kinds
