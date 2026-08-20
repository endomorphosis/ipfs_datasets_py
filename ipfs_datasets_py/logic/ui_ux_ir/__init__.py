"""UI/UX IR public package surface (``UIUXIRPublicAPI@1``) — UIR-070.

Cold import of this package is offline and side-effect free: no process,
network, model, browser, or device action is started. Heavy symbols resolve
lazily via ``__getattr__``.

Public API target (plan §8)::

    decode_ui_ir(payload) -> UIIRDocument
    canonicalize_ui_ir(document) -> bytes
    ui_ir_identity(document) -> str
    evaluate_ui_interaction(...)  # mediation decision
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Final, Mapping

UIUXIR_PUBLIC_API_INTERFACE: Final = "UIUXIRPublicAPI@1"
UIUXIR_BRIDGE_REGISTRATION_INTERFACE: Final = "UIUXIRBridgeRegistration@1"
UI_UX_IR_SCHEMA_ID: Final = "ui-ux-ir/v1"
UI_UX_IR_PACKAGE: Final = "ipfs_datasets_py.logic.ui_ux_ir"

# Stable public names — intentional surface only.
__all__ = [
    "UIUXIR_PUBLIC_API_INTERFACE",
    "UIUXIR_BRIDGE_REGISTRATION_INTERFACE",
    "UI_UX_IR_SCHEMA_ID",
    "UI_UX_IR_PACKAGE",
    "UI_UX_IR_SCHEMA_VERSION",
    "UIIRDocument",
    "UIIRValidationError",
    "decode_ui_ir",
    "canonicalize_ui_ir",
    "ui_ir_identity",
    "ui_ir_sha256",
    "evaluate_ui_interaction",
    "create_mediator",
    "UIMediator",
    "public_api_manifest",
]

_LAZY: Final[Mapping[str, tuple[str, str]]] = {
    "UI_UX_IR_SCHEMA_VERSION": (".schema", "UI_UX_IR_SCHEMA_VERSION"),
    "UIIRDocument": (".schema", "UIIRDocument"),
    "UIIRValidationError": (".schema", "UIIRValidationError"),
    "decode_ui_ir": (".decoder", "decode_ui_ir"),
    "canonicalize_ui_ir": (".canonicalize", "canonicalize_ui_ir"),
    "ui_ir_sha256": (".canonicalize", "ui_ir_sha256"),
    "create_mediator": (".runtime.mediator", "create_mediator"),
    "UIMediator": (".runtime.mediator", "UIMediator"),
}


def ui_ir_identity(document: Any) -> str:
    """Return the stable ``sha256:`` declaration identity for *document*."""

    from .canonicalize import ui_ir_sha256

    return ui_ir_sha256(document)


def evaluate_ui_interaction(
    binding: Any,
    event: Any,
    context: Any,
    *,
    mediator: Any | None = None,
) -> Any:
    """Evaluate one action against formal/runtime policy (``UIMediator@1``).

    Does not execute transport. Use :func:`execute_if_allowed` with a spy for
    allow-path checks.
    """

    from .runtime.mediator import UIMediator, create_mediator

    med = mediator if mediator is not None else create_mediator()
    if not isinstance(med, UIMediator):
        med = create_mediator()
    return med.mediate(binding, event, context)


def public_api_manifest() -> dict[str, Any]:
    """Deterministic public surface + registration receipt (UIR-070 evidence)."""

    return {
        "interface": UIUXIR_PUBLIC_API_INTERFACE,
        "bridge_registration_interface": UIUXIR_BRIDGE_REGISTRATION_INTERFACE,
        "schema_id": UI_UX_IR_SCHEMA_ID,
        "package": UI_UX_IR_PACKAGE,
        "public_symbols": list(__all__),
        "lazy_symbols": sorted(_LAZY.keys()),
        "cold_import_side_effects": False,
        "optional_runtimes_eager": False,
    }


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module_name, attr = _LAZY[name]
        mod = import_module(module_name, __name__)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
