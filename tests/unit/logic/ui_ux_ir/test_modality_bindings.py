"""UIR-014: modality capability, program-binding, and protocol contracts."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ProgramBindingTargetKind,
    UIActionBinding,
    UIProgramRef,
    validate_action_binding,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.modality import (
    DeviceProfile,
    InputCapability,
    InputCapabilityKind,
    ModalityDirection,
    ModalityRequirementSpec,
    OutputCapability,
    OutputCapabilityKind,
    UIModalityContract,
    default_input_capability_catalogue,
    default_output_capability_catalogue,
    require_supported_capability,
    validate_modality_contract,
)
from ipfs_datasets_py.logic.ui_ux_ir.protocols import (
    DefaultUICapabilityNegotiator,
    ReferenceUIUXIRProtocols,
    UI_UX_IR_PROTOCOLS_INTERFACE,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def test_canonical_capabilities_cover_declared_modalities() -> None:
    inputs = {cap.capability_id for cap in default_input_capability_catalogue()}
    outputs = {cap.capability_id for cap in default_output_capability_catalogue()}
    for expected in (
        "pointer_mouse",
        "keyboard",
        "touchscreen",
        "speech",
        "hand_gesture",
        "gaze",
        "head_pose",
        "neural_band_normalized",
        "dpad_captouch",
        "agent_proposal",
    ):
        assert expected in inputs
    for expected in ("display", "spatial_display", "audio", "haptic", "fallback"):
        assert expected in outputs
    # Raw EMG / continuous neural streams are not admitted.
    assert "raw_emg" not in inputs
    assert "continuous_neural_band" not in inputs


def test_require_supported_capability_fails_closed() -> None:
    require_supported_capability("keyboard")
    with pytest.raises(UIIRValidationError):
        require_supported_capability("raw_emg_stream")


def test_modality_contract_validates_and_rejects_unknown() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir.schema import UIModalityAlternative

    contract = UIModalityContract(
        contract_id="c1",
        input_capabilities=(
            InputCapability(
                capability_id="keyboard", kind=InputCapabilityKind.KEYBOARD
            ),
            InputCapability(
                capability_id="speech", kind=InputCapabilityKind.SPEECH
            ),
        ),
        output_capabilities=(
            OutputCapability(
                capability_id="display", kind=OutputCapabilityKind.DISPLAY
            ),
        ),
        requirements=(
            ModalityRequirementSpec(
                requirement_id="r_keyboard",
                direction=ModalityDirection.INPUT,
                capability_ids=("keyboard",),
                essential=True,
            ),
            ModalityRequirementSpec(
                requirement_id="r_speech_alt",
                direction=ModalityDirection.INPUT,
                capability_ids=("speech",),
                essential=False,
            ),
        ),
        alternatives=(
            UIModalityAlternative(
                alternative_id="alt_kb_speech",
                primary_requirement_id="r_keyboard",
                alternative_requirement_id="r_speech_alt",
            ),
        ),
    )
    assert validate_modality_contract(contract).contract_id == "c1"
    bad = UIModalityContract(
        contract_id="c2",
        input_capabilities=(
            InputCapability(
                capability_id="keyboard", kind=InputCapabilityKind.KEYBOARD
            ),
        ),
        output_capabilities=(
            OutputCapability(
                capability_id="display", kind=OutputCapabilityKind.DISPLAY
            ),
        ),
        requirements=(
            ModalityRequirementSpec(
                requirement_id="r_bad",
                direction=ModalityDirection.INPUT,
                capability_ids=("not_a_real_capability",),
                essential=True,
            ),
        ),
    )
    with pytest.raises(UIIRValidationError):
        validate_modality_contract(bad)


def test_action_binding_is_single_target_and_non_authorizing() -> None:
    pref = UIProgramRef(
        target_kind=ProgramBindingTargetKind.MCP_IDL,
        mcp_idl_interface_cid="baguqeeraexampleinterface0000000000000000000000000000",
        mcp_idl_method_name="submit",
    )
    binding = UIActionBinding(
        binding_id="bind_submit",
        action_id="submit_form",
        program_ref=pref,
    )
    validated = validate_action_binding(binding)
    assert validated.action_id == "submit_form"
    # Exactly one semantic target: dual target kinds must fail.
    with pytest.raises(Exception):
        validate_action_binding(
            UIActionBinding(
                binding_id="bind_dual",
                action_id="submit_form",
                program_ref=UIProgramRef(
                    target_kind=ProgramBindingTargetKind.MCP_IDL,
                    mcp_idl_interface_cid="baguqeeraexampleinterface0000000000000000000000000000",
                    mcp_idl_method_name="submit",
                    intent_document_id="intent:also",  # second target smuggled
                    intent_action_id="also",
                ),
            )
        )


def test_capability_negotiator_fails_when_essential_missing() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir.schema import UIModalityAlternative

    contract = UIModalityContract(
        contract_id="c_neg",
        input_capabilities=(
            InputCapability(
                capability_id="speech", kind=InputCapabilityKind.SPEECH
            ),
            InputCapability(
                capability_id="keyboard", kind=InputCapabilityKind.KEYBOARD
            ),
        ),
        output_capabilities=(
            OutputCapability(
                capability_id="audio", kind=OutputCapabilityKind.AUDIO
            ),
        ),
        requirements=(
            ModalityRequirementSpec(
                requirement_id="need_speech",
                direction=ModalityDirection.INPUT,
                capability_ids=("speech",),
                essential=True,
            ),
            ModalityRequirementSpec(
                requirement_id="need_kb_alt",
                direction=ModalityDirection.INPUT,
                capability_ids=("keyboard",),
                essential=False,
            ),
        ),
        alternatives=(
            UIModalityAlternative(
                alternative_id="alt_speech_kb",
                primary_requirement_id="need_speech",
                alternative_requirement_id="need_kb_alt",
            ),
        ),
    )
    negotiator = DefaultUICapabilityNegotiator()
    ok = negotiator.negotiate(
        contract, available_capability_ids=("speech", "audio")
    )
    assert ok["status"] == "satisfied"
    # Neither primary nor alternative present.
    with pytest.raises(UIIRValidationError):
        negotiator.negotiate(
            contract, available_capability_ids=("touchscreen",)
        )


def test_reference_protocols_bundle_exports_interface() -> None:
    bundle = ReferenceUIUXIRProtocols()
    assert bundle.interface == UI_UX_IR_PROTOCOLS_INTERFACE
    assert bundle.modality_validator is not None
    assert bundle.binding_validator is not None
