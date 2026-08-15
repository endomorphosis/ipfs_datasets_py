"""UIR-030: MCP-IDL → UI/UX IR source adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl import (
    MCPIDLUIIR_ADAPTER,
    adapt_mcp_idl_to_uiir,
)
from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl_identity import (
    compute_verified_interface_cid,
    is_pseudo_interface_cid,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "ui_ux_ir"
    / "v1"
    / "mcp_idl_identity_vectors.json"
)


def _golden_descriptor():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["golden"]["descriptor"], data["golden"]["interface_cid"]


def test_adapt_preserves_verified_interface_cid_and_no_grant() -> None:
    descriptor, expected_cid = _golden_descriptor()
    result = adapt_mcp_idl_to_uiir(descriptor)
    assert result.interface_cid == expected_cid
    assert result.interface_cid == compute_verified_interface_cid(descriptor)
    assert result.execution_grant is None
    assert result.adapter == MCPIDLUIIR_ADAPTER
    assert result.action_bindings
    for binding in result.action_bindings:
        assert binding.program_ref.mcp_idl_interface_cid == expected_cid
        assert binding.program_ref.mcp_idl_method_name
    assert "layout_regions" in result.ui_semantics_not_derived
    assert result.losses


def test_reject_pseudo_cid_and_preimage_mismatch() -> None:
    descriptor, expected_cid = _golden_descriptor()
    assert is_pseudo_interface_cid("cidv1-sha256-" + "a" * 64)
    with pytest.raises(UIIRValidationError):
        adapt_mcp_idl_to_uiir(
            descriptor, claimed_interface_cid="cidv1-sha256-" + "a" * 64
        )
    mutated = json.loads(json.dumps(descriptor))
    mutated["name"] = "mutated.interface"
    with pytest.raises(UIIRValidationError):
        adapt_mcp_idl_to_uiir(mutated, claimed_interface_cid=expected_cid)


def test_domains_are_not_execution_grants() -> None:
    descriptor, _ = _golden_descriptor()
    result = adapt_mcp_idl_to_uiir(descriptor)
    assert result.execution_grant is None
    # Adapter result must not expose authority-bearing fields.
    assert not hasattr(result, "ucan")
    assert not hasattr(result, "capability_token")
