"""LPC-043 / DomainLogicSlice@2 adapter role for the committed UI/UX IR package.

This is a thin inventory alias (`ui_ux_ir.domain_slice`) over the reviewed
`UIUXLogicSlice@2` gate and the package's formalization compiler. It does not
invent a second UI/UX ontology.
"""

from __future__ import annotations

from ipfs_datasets_py.logic.conformance.ui_ux_logic_gate_v2 import (
    UIUX_DOMAIN_ID,
    UIUX_LOGIC_SLICE_V2_INTERFACE,
    UIUXLogicSliceConnector,
    UIUXSourceGate,
    package_is_present,
    ui_ux_package_path,
)

DOMAIN_ID = UIUX_DOMAIN_ID
INTERFACE = UIUX_LOGIC_SLICE_V2_INTERFACE


def package_available() -> bool:
    return package_is_present(ui_ux_package_path())


def connect_ui_ux_logic_slice() -> UIUXLogicSliceConnector:
    """Return the production UI/UX slice connector (source must be present)."""

    return UIUXLogicSliceConnector()


def source_gate() -> UIUXSourceGate:
    return UIUXSourceGate()
