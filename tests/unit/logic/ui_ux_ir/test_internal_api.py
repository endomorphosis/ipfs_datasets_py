"""UIR-069: internal package export surfaces — offline, lazy, reviewed symbols."""

from __future__ import annotations

import importlib
import socket
from typing import Any


INTERNAL_PACKAGES = (
    "ipfs_datasets_py.logic.ui_ux_ir.model",
    "ipfs_datasets_py.logic.ui_ux_ir.formalize",
    "ipfs_datasets_py.logic.ui_ux_ir.source_adapters",
    "ipfs_datasets_py.logic.ui_ux_ir.projection",
    "ipfs_datasets_py.logic.ui_ux_ir.runtime",
    "ipfs_datasets_py.logic.ui_ux_ir.runtime.input",
    "ipfs_datasets_py.logic.ui_ux_ir.assurance",
)


def test_internal_packages_import_offline() -> None:
    """Import closure succeeds without network (socket blocked as canary)."""

    real_socket = socket.socket

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("internal package import must not open sockets")

    socket.socket = _blocked  # type: ignore[assignment]
    try:
        for name in INTERNAL_PACKAGES:
            mod = importlib.import_module(name)
            assert hasattr(mod, "__all__")
            assert "UIUXIR_INTERNAL_PACKAGES_INTERFACE" in mod.__all__
            assert (
                getattr(mod, "UIUXIR_INTERNAL_PACKAGES_INTERFACE")
                == "UIUXIRInternalPackages@1"
            )
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def test_lazy_module_symbols_resolve() -> None:
    runtime = importlib.import_module("ipfs_datasets_py.logic.ui_ux_ir.runtime")
    # Lazy attribute access should load leaf modules.
    mediator = runtime.mediator
    assert hasattr(mediator, "UIMediator")
    receipts = runtime.receipts
    assert hasattr(receipts, "build_receipt_from_decision")
    state = runtime.state_machine
    assert hasattr(state, "UIStateRuntime")

    formalize = importlib.import_module("ipfs_datasets_py.logic.ui_ux_ir.formalize")
    contracts = formalize.contracts
    assert hasattr(contracts, "FormalView")

    assurance = importlib.import_module("ipfs_datasets_py.logic.ui_ux_ir.assurance")
    assert assurance.UIAccessibilityValidator is not None
    assert assurance.UIPrivacyValidator is not None
    assert assurance.UISecurityValidator is not None


def test_no_backend_private_types_on_package_all() -> None:
    """Package __all__ must not re-export raw prover/backend AST private types."""

    forbidden_substrings = (
        "ErgoAST",
        "PrivateBackend",
        "RawNeuralStream",
        "BrowserDriver",
        "DeviceSDK",
    )
    for name in INTERNAL_PACKAGES:
        mod = importlib.import_module(name)
        for symbol in mod.__all__:
            for bad in forbidden_substrings:
                assert bad not in symbol, f"{name}.__all__ leaks {symbol}"


def test_dir_lists_reviewed_surface() -> None:
    for name in INTERNAL_PACKAGES:
        mod = importlib.import_module(name)
        names = dir(mod)
        assert "UIUXIR_INTERNAL_PACKAGES_INTERFACE" in names
        for symbol in mod.__all__:
            assert symbol in names


def test_stable_symbol_receipt() -> None:
    """Evidence receipt: key symbols remain importable from reviewed leaves."""

    symbols = {
        "ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator": "UIMediator",
        "ipfs_datasets_py.logic.ui_ux_ir.runtime.receipts": "UIInteractionReceipt",
        "ipfs_datasets_py.logic.ui_ux_ir.runtime.state_machine": "UIStateRuntime",
        "ipfs_datasets_py.logic.ui_ux_ir.assurance.accessibility": "UIAccessibilityValidator",
        "ipfs_datasets_py.logic.ui_ux_ir.conformance": "run_conformance",
    }
    for module_name, attr in symbols.items():
        mod = importlib.import_module(module_name)
        assert getattr(mod, attr) is not None
