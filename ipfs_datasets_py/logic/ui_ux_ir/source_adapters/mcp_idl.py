"""MCP-IDL → UI/UX IR source adapter (UIR-030).

Projects a verified MCP interface descriptor into UI program bindings and an
explicit loss receipt for semantics that cannot be derived from IDL alone.
Never mints execution grants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Sequence

from ..model.bindings import (
    ConfirmationClass,
    IdempotencyClass,
    ProgramBindingTargetKind,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
    validate_action_binding,
)
from ..schema import UIIRValidationError
from .mcp_idl_identity import (
    INTERFACE_IDENTITY_PROFILE,
    MCPIDLIdentityError,
    compute_verified_interface_cid,
    is_pseudo_interface_cid,
    verify_interface_preimage,
)

MCPIDLUIIR_ADAPTER: Final = "MCPIDLUIIRAdapter@1"
MCPIDLUIIR_ADAPTER_VERSION: Final = "mcp-idl-uiir-adapter/v1"


@dataclass(frozen=True, slots=True)
class LossReceipt:
    loss_id: str
    path: str
    reason: str
    disposition: str = "explicit_unsupported"


@dataclass(frozen=True, slots=True)
class MCPIDLAdapterResult:
    interface_cid: str
    profile: str
    action_bindings: tuple[UIActionBinding, ...]
    losses: tuple[LossReceipt, ...] = ()
    ui_semantics_not_derived: tuple[str, ...] = ()
    adapter: str = MCPIDLUIIR_ADAPTER
    schema_version: str = MCPIDLUIIR_ADAPTER_VERSION
    execution_grant: None = None  # always None; never an authority surface


class MCPIDLUIIRAdapter:
    """Side-effect-free MCP-IDL → UIIR adapter."""

    interface: str = MCPIDLUIIR_ADAPTER

    def adapt(
        self,
        descriptor: Mapping[str, Any],
        *,
        claimed_interface_cid: str = "",
        legacy_aliases: Sequence[str] = (),
    ) -> MCPIDLAdapterResult:
        return adapt_mcp_idl_to_uiir(
            descriptor,
            claimed_interface_cid=claimed_interface_cid,
            legacy_aliases=legacy_aliases,
        )


def adapt_mcp_idl_to_uiir(
    descriptor: Mapping[str, Any],
    *,
    claimed_interface_cid: str = "",
    legacy_aliases: Sequence[str] = (),
) -> MCPIDLAdapterResult:
    """Adapt one MCP interface descriptor into UI action bindings + losses."""

    if not isinstance(descriptor, Mapping):
        raise UIIRValidationError("MCP-IDL descriptor must be a mapping")
    if claimed_interface_cid and is_pseudo_interface_cid(claimed_interface_cid):
        raise UIIRValidationError(
            f"Rejecting pseudo or placeholder interface CID: {claimed_interface_cid!r}"
        )
    try:
        if claimed_interface_cid:
            verified = verify_interface_preimage(
                claimed_interface_cid,
                descriptor,
                legacy_aliases=legacy_aliases,
            )
            interface_cid = verified.interface_cid
        else:
            interface_cid = compute_verified_interface_cid(descriptor)
            verify_interface_preimage(interface_cid, descriptor, legacy_aliases=legacy_aliases)
    except MCPIDLIdentityError as exc:
        raise UIIRValidationError(str(exc)) from exc

    methods = descriptor.get("methods") or ()
    if not isinstance(methods, (list, tuple)):
        raise UIIRValidationError("descriptor.methods must be an array")

    bindings: list[UIActionBinding] = []
    losses: list[LossReceipt] = []
    for index, method in enumerate(methods):
        if not isinstance(method, Mapping):
            raise UIIRValidationError(f"methods[{index}] must be an object")
        name = str(method.get("name") or "").strip()
        if not name:
            raise UIIRValidationError(f"methods[{index}].name must not be empty")
        program_ref = UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid=interface_cid,
            mcp_idl_method_name=name,
        )
        binding = validate_action_binding(
            UIActionBinding(
                binding_id=f"bind:mcp:{name}",
                action_id=f"action:mcp:{name}",
                program_ref=program_ref,
                risk_class=RiskClass.MEDIUM,
                confirmation_class=ConfirmationClass.NONE,
                idempotency=IdempotencyClass.UNKNOWN,
            )
        )
        bindings.append(binding)
        # IDL does not encode UI layout, accessibility names, or modality alternatives.
        losses.append(
            LossReceipt(
                loss_id=f"loss:ui-not-in-idl:{name}",
                path=f"methods[{index}]",
                reason="UI layout/accessibility/modality semantics are not present in MCP-IDL",
            )
        )

    ui_not_derived = (
        "layout_regions",
        "accessibility_names",
        "modality_alternatives",
        "visual_order",
        "locale_messages",
    )
    return MCPIDLAdapterResult(
        interface_cid=interface_cid,
        profile=INTERFACE_IDENTITY_PROFILE,
        action_bindings=tuple(bindings),
        losses=tuple(losses),
        ui_semantics_not_derived=ui_not_derived,
        execution_grant=None,
    )


__all__ = [
    "LossReceipt",
    "MCPIDLAdapterResult",
    "MCPIDLUIIR_ADAPTER",
    "MCPIDLUIIRAdapter",
    "adapt_mcp_idl_to_uiir",
]
