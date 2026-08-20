"""LPC-043: UI/UX adapter conformance without inventing ui_ux_ir.

The pinned datasets tree keeps UI/UX as declaration-only via UIUXSourceGate@2
/ UIUXLogicSlice@2. Tests live here so LPC-043 validation has a path; they
must never create ipfs_datasets_py/logic/ui_ux_ir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.conformance.ui_ux_logic_gate_v2 import (
    UIUX_DOMAIN_ID,
    UIUX_LOGIC_SLICE_V2_INTERFACE,
    UIUXPackageWriteForbiddenError,
    UIUXLogicSliceConnector,
    UIUXSourceGate,
    package_is_present,
    scan_ui_ux_source_gate_v2,
    ui_ux_package_path,
)


def _adapter_note() -> Path:
    relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "intent_uiux_adapters.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / relative


def test_ui_ux_adapter_note_declares_required_contract_fields() -> None:
    text = _adapter_note().read_text(encoding="utf-8").lower()
    for field in (
        "source domain",
        "view",
        "family / profile",
        "property",
        "notation",
        "preserved semantics",
        "lost semantics",
        "assumptions",
        "unsupported constructs",
        "proof-safety",
        "counterexample-safety",
        "ui_ux_ir",
        "declaration-only",
    ):
        assert field in text, field


def test_ui_ux_package_is_present_on_campaign_pin() -> None:
    assert UIUX_DOMAIN_ID == "ui_ux_ir"
    assert UIUX_LOGIC_SLICE_V2_INTERFACE == "UIUXLogicSlice@2"
    connector = UIUXLogicSliceConnector()
    assert connector.to_dict()["domain"] == UIUX_DOMAIN_ID
    package = ui_ux_package_path()
    assert package_is_present(package) is True
    receipt = scan_ui_ux_source_gate_v2()
    assert "missing" not in str(receipt.disposition).lower()


def test_ui_ux_gate_forbids_inventing_the_package() -> None:
    gate = UIUXSourceGate()
    with pytest.raises(UIUXPackageWriteForbiddenError):
        gate.forbid_package_write(ui_ux_package_path() / "__init__.py")
