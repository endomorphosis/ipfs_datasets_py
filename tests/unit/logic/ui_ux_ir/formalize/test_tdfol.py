from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import FormalView
from ipfs_datasets_py.logic.ui_ux_ir.formalize.tdfol import compile_action_bindings_to_tdfol
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    ProgramBindingTargetKind,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)

def test_tdfol_compiles_confirmation_obligations_for_high_risk():
    binding = UIActionBinding(
        binding_id="b1",
        action_id="delete",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i",
            mcp_idl_method_name="delete",
        ),
        risk_class=RiskClass.HIGH,
        confirmation_class=ConfirmationClass.CONFIRM,
    )
    result = compile_action_bindings_to_tdfol((binding,))
    assert result.view is FormalView.TDFOL
    ops = {f.operator for f in result.formulas}
    assert "obligation" in ops and "prohibition" in ops
    assert any("before confirm" in f.proposition for f in result.formulas)
    assert all(f.strength for f in result.formulas)
