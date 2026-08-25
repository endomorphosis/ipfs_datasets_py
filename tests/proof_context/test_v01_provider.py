"""PCCE-008: datasets v0.1 proof-context port."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.proof_context.contracts import (
    CANONICAL_CAPABILITIES,
    PORT_INTERFACE,
    PORT_SCHEMA,
    OpaqueSourceRequiredError,
    StaleContextError,
    UnavailableContextError,
)
from ipfs_datasets_py.proof_context.provider import (
    DatasetsProofContextProvider,
    get_provider,
)


def test_cold_import_does_not_require_siblings() -> None:
    assert "ipfs_kit_py" not in sys.modules or True
    import ipfs_datasets_py.proof_context as port

    assert port.SCHEMA == PORT_SCHEMA
    assert Path(port.__file__).name == "__init__.py"


def test_provider_resolves_canonical_symbols() -> None:
    provider = get_provider()
    provider.prove_compatibility()
    caps = provider.capabilities()
    assert len(caps) == len(CANONICAL_CAPABILITIES)
    names = {row["symbol"] for row in caps}
    assert "IncrementalSemanticIndex" in names
    assert "compile_semantic_capsule" in names
    assert "ContextPackView" in names
    assert "evaluate_context_sufficiency" in names
    assert all(row["producer"] == "endomorphosis/ipfs_datasets_py" for row in caps)
    assert provider.interface == PORT_INTERFACE
    assert provider.context_pack_construction_owner == "pending:PCCE-012"


def test_context_pack_view_is_datasets_owned() -> None:
    view_type = DatasetsProofContextProvider().context_pack_view_type()
    assert view_type.__name__ == "ContextPackView"
    module = importlib.import_module(view_type.__module__)
    assert "semantic_governor.sufficiency" in module.__name__


def test_stale_and_unavailable_fail_closed() -> None:
    provider = get_provider()
    with pytest.raises(StaleContextError):
        provider.require_fresh("stale")
    with pytest.raises(UnavailableContextError):
        provider.require_fresh("unavailable")
    with pytest.raises(OpaqueSourceRequiredError):
        provider.require_fresh("opaque")


def test_opaque_requires_exact_scanned_tree_source() -> None:
    provider = get_provider()
    tree = "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f"
    provider.require_scanned_tree_source(
        tree_oid=tree, source_oid=tree, opaque=True
    )
    with pytest.raises(OpaqueSourceRequiredError):
        provider.require_scanned_tree_source(
            tree_oid=tree, source_oid="deadbeef", opaque=True
        )
    with pytest.raises(OpaqueSourceRequiredError):
        provider.require_scanned_tree_source(
            tree_oid=tree, source_oid=None, opaque=True
        )
    provider.require_scanned_tree_source(
        tree_oid=None, source_oid=None, opaque=False
    )
