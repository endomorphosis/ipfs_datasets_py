"""UIR-070: public API, schema registration, and bridge manifest."""

from __future__ import annotations

import importlib
import socket
from typing import Any


def test_cold_import_is_side_effect_free() -> None:
    real_socket = socket.socket

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("ui_ux_ir cold import must not open sockets")

    socket.socket = _blocked  # type: ignore[assignment]
    try:
        importlib.invalidate_caches()
        mod = importlib.import_module("ipfs_datasets_py.logic.ui_ux_ir")
        assert mod.UIUXIR_PUBLIC_API_INTERFACE == "UIUXIRPublicAPI@1"
        assert mod.UI_UX_IR_SCHEMA_ID == "ui-ux-ir/v1"
        assert mod.public_api_manifest()["cold_import_side_effects"] is False
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def test_public_symbols_resolve_lazily() -> None:
    from ipfs_datasets_py.logic import ui_ux_ir as u

    assert callable(u.decode_ui_ir)
    assert callable(u.canonicalize_ui_ir)
    assert callable(u.ui_ir_identity)
    assert callable(u.evaluate_ui_interaction)
    assert u.UI_UX_IR_SCHEMA_VERSION.startswith("ui-ux-ir/")
    # Only intentional stable symbols.
    for name in u.__all__:
        assert not name.startswith("_")


def test_schema_registry_and_submodule_manifest() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_submodule_spec,
        logic_integration_manifest,
    )

    spec = logic_submodule_spec("ui_ux_ir")
    assert spec.module == "ipfs_datasets_py.logic.ui_ux_ir"
    assert "ui_ux_ir" in spec.roles
    assert "decode_ui_ir" in spec.public_symbols

    manifest = logic_integration_manifest()
    names = {entry["name"] for entry in manifest["submodules"]}
    assert "ui_ux_ir" in names


def test_bridge_registration_manifest() -> None:
    from ipfs_datasets_py.logic.bridge.registry import (
        logic_bridge_spec,
        logic_bridge_manifest,
    )

    bridge = logic_bridge_spec("ui_ux_ir_formalization")
    assert bridge.implemented is True
    assert bridge.source_view == "ui_ux_ir_document"
    assert "ui_ux_ir" in bridge.required_submodules

    manifest = logic_bridge_manifest()
    assert "ui_ux_ir_formalization" in manifest["implemented_bridges"]
    # Bridge registration interface identity for UIR-070 evidence.
    from ipfs_datasets_py.logic.ui_ux_ir import UIUXIR_BRIDGE_REGISTRATION_INTERFACE

    assert UIUXIR_BRIDGE_REGISTRATION_INTERFACE == "UIUXIRBridgeRegistration@1"


def test_logic_api_lazy_reexport() -> None:
    import ipfs_datasets_py.logic.api as api

    assert api.UI_UX_IR_SCHEMA_ID == "ui-ux-ir/v1"
    assert callable(api.decode_ui_ir)
    assert callable(api.ui_ir_identity)


def test_decode_canonicalize_round_trip_via_public_api() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir import (
        decode_ui_ir,
        canonicalize_ui_ir,
        ui_ir_identity,
    )
    from ipfs_datasets_py.logic.ui_ux_ir.schema import (
        ReviewStatus,
        SourceSpan,
        TerminalOutcomeKind,
        UIComponent,
        UIIRDocument,
        UISourceRef,
        UITerminalOutcome,
    )

    source = UISourceRef(
        ref_id="source:public-api",
        source_uri="https://example.test/ui",
        source_id="public-api",
        source_revision="rev-1",
        content_sha256="a" * 64,
        container_uri="ipfs://bafy-fixture",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
        span=SourceSpan(start_char=0, end_char=10),
    )
    root = UIComponent(
        component_id="component:root",
        role="form",
        purpose="Public API smoke form.",
        source_ref_ids=(source.ref_id,),
    )
    doc = UIIRDocument(
        document_id="doc:public-api",
        title="Public API",
        sources=(source,),
        components=(root,),
        entry_components=("component:root",),
        terminal_outcomes=(
            UITerminalOutcome(
                outcome_id="outcome:ok",
                kind=TerminalOutcomeKind.SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
    )
    payload = doc.to_dict()
    decoded = decode_ui_ir(payload)
    assert decoded.document_id == "doc:public-api"
    digest = ui_ir_identity(decoded)
    assert digest.startswith("sha256:")
    assert canonicalize_ui_ir(decoded) == canonicalize_ui_ir(payload)
