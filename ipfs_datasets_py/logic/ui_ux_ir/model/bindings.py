"""Program and action bindings with exactly one semantic target.

UIProgramBinding@1 / UIActionBinding declare stable references to MCP-IDL,
Intent IR, Invocation templates, local state transitions, or versioned
composite workflows. Bindings never embed executable code and never grant
authority (no UCAN, capability tokens, role grants, or permission elevations).

Each action selects exactly one semantic target family.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Iterable, Mapping, Sequence

from ..schema import (
    ProgramBindingTargetKind,
    UIFormalConstraintRef,
    UIIRValidationError,
    UIProgramBinding as EnvelopeUIProgramBinding,
)

UI_PROGRAM_BINDING_INTERFACE: Final = "UIProgramBinding@1"
UI_ACTION_BINDING_SCHEMA_VERSION: Final = "ui-action-binding/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Authority-grant surface that UI bindings must never carry.
_FORBIDDEN_AUTHORITY_KEYS: Final = frozenset(
    {
        "authority_grant",
        "capability_token",
        "delegation",
        "grant",
        "grants",
        "permission",
        "permissions",
        "privilege",
        "privileges",
        "role_grant",
        "token_grant",
        "ucan",
        "ucan_token",
    }
)

_FORBIDDEN_EXECUTABLE_KEYS: Final = frozenset(
    {
        "callback",
        "callbacks",
        "code",
        "eval",
        "exec",
        "executable",
        "fn",
        "function",
        "handler",
        "handlers",
        "javascript",
        "jsx",
        "lambda",
        "listener",
        "listeners",
        "on_blur",
        "on_change",
        "on_click",
        "on_focus",
        "on_input",
        "on_submit",
        "onchange",
        "onclick",
        "onsubmit",
        "script",
        "scripts",
        "tsx",
    }
)

_FORBIDDEN_EXECUTABLE_KEY_PREFIXES: Final = ("on_", "handle_")


class RiskClass(str, Enum):
    """Closed risk classes for program actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"


class ConfirmationClass(str, Enum):
    """Closed confirmation requirements for program actions."""

    NONE = "none"
    CONFIRM = "confirm"
    DOUBLE_CONFIRM = "double_confirm"
    CONSENT = "consent"


class IdempotencyClass(str, Enum):
    """Whether replaying the action is safe."""

    UNKNOWN = "unknown"
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise UIIRValidationError(f"{name} must be a string")


def _validate_non_empty_string(name: str, value: Any) -> None:
    _validate_string(name, value)
    if not value.strip():
        raise UIIRValidationError(f"{name} must not be empty")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise UIIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _validate_identifier_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_identifier(f"{name}[{index}]", value)


def _is_forbidden_executable_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _FORBIDDEN_EXECUTABLE_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_EXECUTABLE_KEY_PREFIXES)


def _reject_code_and_authority(value: Any, label: str, *, _path: str = "") -> None:
    """Reject embedded code, callbacks, and authority grants in bindings."""

    if callable(value) or isinstance(value, type):
        raise UIIRValidationError(f"{label}{_path} contains an executable callback")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UIIRValidationError(f"{label}{_path} map keys must be strings")
            lowered = key.lower()
            if _is_forbidden_executable_key(key):
                raise UIIRValidationError(
                    f"{label}{_path}/{key} is an executable callback field"
                )
            if lowered in _FORBIDDEN_AUTHORITY_KEYS:
                raise UIIRValidationError(
                    f"{label}{_path}/{key} grants authority and is forbidden on UI bindings"
                )
            _reject_code_and_authority(item, label, _path=f"{_path}/{key}")
        return
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_code_and_authority(item, label, _path=f"{_path}[{index}]")


@dataclass(frozen=True, slots=True)
class UIProgramRef:
    """Exactly one semantic program target reference.

    Exactly one of the target-family fields is populated, matching
    :class:`ProgramBindingTargetKind`.
    """

    target_kind: ProgramBindingTargetKind
    # MCP-IDL
    mcp_idl_interface_cid: str = ""
    mcp_idl_method_name: str = ""
    mcp_idl_argument_schema_ref: str = ""
    mcp_idl_result_schema_ref: str = ""
    # Intent IR
    intent_document_id: str = ""
    intent_action_id: str = ""
    # Invocation
    invocation_template_cid: str = ""
    # Local state
    local_state_transition: str = ""
    # Composite workflow
    composite_workflow_ref: str = ""

    def validate(self) -> None:
        if not isinstance(self.target_kind, ProgramBindingTargetKind):
            raise UIIRValidationError(
                "UIProgramRef.target_kind must be a ProgramBindingTargetKind value"
            )

        optional_fields = (
            "mcp_idl_interface_cid",
            "mcp_idl_method_name",
            "mcp_idl_argument_schema_ref",
            "mcp_idl_result_schema_ref",
            "intent_document_id",
            "intent_action_id",
            "invocation_template_cid",
            "local_state_transition",
            "composite_workflow_ref",
        )
        for field_name in optional_fields:
            _validate_string(f"UIProgramRef.{field_name}", getattr(self, field_name))

        populated = self._populated_families()
        if len(populated) != 1:
            raise UIIRValidationError(
                "UIProgramRef must populate exactly one semantic target family; "
                f"found {len(populated)}: {', '.join(sorted(populated)) or '(none)'}"
            )
        expected = self._expected_family()
        if expected not in populated:
            raise UIIRValidationError(
                f"UIProgramRef.target_kind {self.target_kind.value!r} does not match "
                f"populated family {next(iter(populated))!r}"
            )

        if self.target_kind is ProgramBindingTargetKind.MCP_IDL:
            _validate_non_empty_string(
                "UIProgramRef.mcp_idl_interface_cid", self.mcp_idl_interface_cid
            )
            _validate_non_empty_string(
                "UIProgramRef.mcp_idl_method_name", self.mcp_idl_method_name
            )
        elif self.target_kind is ProgramBindingTargetKind.INTENT_IR:
            _validate_identifier(
                "UIProgramRef.intent_document_id", self.intent_document_id
            )
            if self.intent_action_id:
                _validate_identifier(
                    "UIProgramRef.intent_action_id", self.intent_action_id
                )
        elif self.target_kind is ProgramBindingTargetKind.INVOCATION_TEMPLATE:
            _validate_non_empty_string(
                "UIProgramRef.invocation_template_cid", self.invocation_template_cid
            )
        elif self.target_kind is ProgramBindingTargetKind.LOCAL_STATE:
            _validate_identifier(
                "UIProgramRef.local_state_transition", self.local_state_transition
            )
        elif self.target_kind is ProgramBindingTargetKind.COMPOSITE_WORKFLOW:
            _validate_non_empty_string(
                "UIProgramRef.composite_workflow_ref", self.composite_workflow_ref
            )
        _reject_code_and_authority(self.to_dict(), "UIProgramRef")

    def _expected_family(self) -> str:
        return {
            ProgramBindingTargetKind.MCP_IDL: "mcp_idl",
            ProgramBindingTargetKind.INTENT_IR: "intent_ir",
            ProgramBindingTargetKind.INVOCATION_TEMPLATE: "invocation",
            ProgramBindingTargetKind.LOCAL_STATE: "local_state",
            ProgramBindingTargetKind.COMPOSITE_WORKFLOW: "composite",
        }[self.target_kind]

    def _populated_families(self) -> set[str]:
        families: set[str] = set()
        if self.mcp_idl_interface_cid or self.mcp_idl_method_name:
            families.add("mcp_idl")
        if self.intent_document_id or self.intent_action_id:
            families.add("intent_ir")
        if self.invocation_template_cid:
            families.add("invocation")
        if self.local_state_transition:
            families.add("local_state")
        if self.composite_workflow_ref:
            families.add("composite")
        return families

    def target_ref(self) -> str:
        """Stable single-string target reference for envelope bindings."""

        self.validate()
        if self.target_kind is ProgramBindingTargetKind.MCP_IDL:
            return f"mcp:{self.mcp_idl_interface_cid}#{self.mcp_idl_method_name}"
        if self.target_kind is ProgramBindingTargetKind.INTENT_IR:
            if self.intent_action_id:
                return f"intent:{self.intent_document_id}#{self.intent_action_id}"
            return f"intent:{self.intent_document_id}"
        if self.target_kind is ProgramBindingTargetKind.INVOCATION_TEMPLATE:
            return f"invocation:{self.invocation_template_cid}"
        if self.target_kind is ProgramBindingTargetKind.LOCAL_STATE:
            return f"local:{self.local_state_transition}"
        return f"workflow:{self.composite_workflow_ref}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite_workflow_ref": self.composite_workflow_ref,
            "intent_action_id": self.intent_action_id,
            "intent_document_id": self.intent_document_id,
            "invocation_template_cid": self.invocation_template_cid,
            "local_state_transition": self.local_state_transition,
            "mcp_idl_argument_schema_ref": self.mcp_idl_argument_schema_ref,
            "mcp_idl_interface_cid": self.mcp_idl_interface_cid,
            "mcp_idl_method_name": self.mcp_idl_method_name,
            "mcp_idl_result_schema_ref": self.mcp_idl_result_schema_ref,
            "target_kind": self.target_kind.value,
        }


@dataclass(frozen=True, slots=True)
class UIActionBinding:
    """Action binding with exactly one semantic program target.

    Interface identity: ``UIProgramBinding@1``.
    """

    binding_id: str
    action_id: str
    program_ref: UIProgramRef
    risk_class: RiskClass = RiskClass.LOW
    confirmation_class: ConfirmationClass = ConfirmationClass.NONE
    idempotency: IdempotencyClass = IdempotencyClass.UNKNOWN
    precondition_ids: tuple[str, ...] = ()
    effect_ids: tuple[str, ...] = ()
    verification_ids: tuple[str, ...] = ()
    formal_constraint_ids: tuple[str, ...] = ()
    rollback_ref: str = ""
    audience: str = ""
    result_to_state: tuple[tuple[str, str], ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = UI_ACTION_BINDING_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != UI_ACTION_BINDING_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported action binding schema_version: {self.schema_version!r}"
            )
        _validate_identifier("UIActionBinding.binding_id", self.binding_id)
        _validate_identifier("UIActionBinding.action_id", self.action_id)
        if not isinstance(self.program_ref, UIProgramRef):
            raise UIIRValidationError(
                "UIActionBinding.program_ref must be a UIProgramRef"
            )
        self.program_ref.validate()
        if not isinstance(self.risk_class, RiskClass):
            raise UIIRValidationError(
                "UIActionBinding.risk_class must be a RiskClass value"
            )
        if not isinstance(self.confirmation_class, ConfirmationClass):
            raise UIIRValidationError(
                "UIActionBinding.confirmation_class must be a ConfirmationClass value"
            )
        if not isinstance(self.idempotency, IdempotencyClass):
            raise UIIRValidationError(
                "UIActionBinding.idempotency must be an IdempotencyClass value"
            )
        if self.risk_class in {RiskClass.HIGH, RiskClass.DESTRUCTIVE}:
            if self.confirmation_class is ConfirmationClass.NONE:
                raise UIIRValidationError(
                    f"UIActionBinding {self.binding_id!r} risk_class "
                    f"{self.risk_class.value!r} requires a non-none confirmation_class"
                )

        for field_name in (
            "precondition_ids",
            "effect_ids",
            "verification_ids",
            "formal_constraint_ids",
            "source_ref_ids",
        ):
            values = getattr(self, field_name)
            _require_tuple(f"UIActionBinding.{field_name}", values)
            _validate_identifier_items(f"UIActionBinding.{field_name}", values)
            _require_unique(values, f"UIActionBinding.{field_name} member")

        _validate_string("UIActionBinding.rollback_ref", self.rollback_ref)
        if self.rollback_ref:
            _validate_identifier("UIActionBinding.rollback_ref", self.rollback_ref)
        _validate_string("UIActionBinding.audience", self.audience)

        _require_tuple("UIActionBinding.result_to_state", self.result_to_state)
        seen_results: set[str] = set()
        for index, pair in enumerate(self.result_to_state):
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or not all(isinstance(part, str) for part in pair)
            ):
                raise UIIRValidationError(
                    f"UIActionBinding.result_to_state[{index}] must be a (result, state) string pair"
                )
            result_key, state_id = pair
            _validate_non_empty_string(
                f"UIActionBinding.result_to_state[{index}].result", result_key
            )
            _validate_identifier(
                f"UIActionBinding.result_to_state[{index}].state", state_id
            )
            if result_key in seen_results:
                raise UIIRValidationError(
                    f"Duplicate UIActionBinding.result_to_state result key: {result_key}"
                )
            seen_results.add(result_key)

        payload = self.to_dict()
        _reject_code_and_authority(payload, f"UIActionBinding {self.binding_id}")

    def semantic_target_count(self) -> int:
        """Return the number of populated semantic target families (must be 1)."""

        return len(self.program_ref._populated_families())

    def to_envelope_program_binding(self) -> EnvelopeUIProgramBinding:
        """Project into the envelope :class:`UIProgramBinding` leaf."""

        self.validate()
        return EnvelopeUIProgramBinding(
            binding_id=self.binding_id,
            target_kind=self.program_ref.target_kind,
            target_ref=self.program_ref.target_ref(),
            risk_class=self.risk_class.value,
            confirmation_class=self.confirmation_class.value,
            precondition_ids=self.precondition_ids,
            effect_ids=self.effect_ids,
            verification_ids=self.verification_ids,
            source_ref_ids=self.source_ref_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "audience": self.audience,
            "binding_id": self.binding_id,
            "confirmation_class": self.confirmation_class.value,
            "effect_ids": sorted(set(self.effect_ids)),
            "formal_constraint_ids": sorted(set(self.formal_constraint_ids)),
            "idempotency": self.idempotency.value,
            "interface": UI_PROGRAM_BINDING_INTERFACE,
            "precondition_ids": sorted(set(self.precondition_ids)),
            "program_ref": self.program_ref.to_dict(),
            "result_to_state": [
                {"result": result, "state_id": state}
                for result, state in sorted(self.result_to_state, key=lambda item: item[0])
            ],
            "risk_class": self.risk_class.value,
            "rollback_ref": self.rollback_ref,
            "schema_version": self.schema_version,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "verification_ids": sorted(set(self.verification_ids)),
        }


def validate_action_binding(binding: UIActionBinding) -> UIActionBinding:
    """Validate and return an action binding (fail closed)."""

    if not isinstance(binding, UIActionBinding):
        raise UIIRValidationError(
            "validate_action_binding requires a UIActionBinding instance"
        )
    binding.validate()
    if binding.semantic_target_count() != 1:
        raise UIIRValidationError(
            f"UIActionBinding {binding.binding_id!r} must have exactly one semantic target"
        )
    return binding


def validate_program_ref(program_ref: UIProgramRef) -> UIProgramRef:
    """Validate and return a program reference (fail closed)."""

    if not isinstance(program_ref, UIProgramRef):
        raise UIIRValidationError(
            "validate_program_ref requires a UIProgramRef instance"
        )
    program_ref.validate()
    return program_ref


def reject_authority_grant_payload(payload: Mapping[str, Any], label: str) -> None:
    """Public helper: fail closed when a binding payload embeds grants."""

    if not isinstance(payload, Mapping):
        raise UIIRValidationError(f"{label} must be a mapping")
    _reject_code_and_authority(payload, label)


__all__ = [
    "ConfirmationClass",
    "IdempotencyClass",
    "RiskClass",
    "UI_ACTION_BINDING_SCHEMA_VERSION",
    "UI_PROGRAM_BINDING_INTERFACE",
    "UIActionBinding",
    "UIFormalConstraintRef",
    "UIProgramRef",
    "reject_authority_grant_payload",
    "validate_action_binding",
    "validate_program_ref",
]
