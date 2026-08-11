"""Conformance: exact-source-gated UI and accessibility logic adapter (LFP2-026).

Acceptance:

* Absent source yields typed source_missing/declaration_only without blocking
  other work
* Present source produces one content-addressed owner-scoped adapter gap
* UIUXLogicSlice@2 records accessibility, interaction/event, workflow,
  ontology/frame, authorization, and observable-state requirements
* Gate never creates, copies, or edits ui_ux_ir
* Adapter acceptance requires declared-syntax parsing, frame_logic alias
  canonicalization, and typed structural round trips — not token presence

Interfaces: UIUXLogicSlice@2, UIUXSourceGate@2
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.conformance.matrix import (
    AuthorityCeiling,
    AvailabilityStatus,
    SupportStatus,
)
from ipfs_datasets_py.logic.conformance.ui_ux_logic_gate_v2 import (
    ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS,
    ADAPTER_SCOPE_IDS,
    FRAME_LOGIC_ALIASES,
    FRAME_LOGIC_FAMILY_ID,
    REQUIREMENT_SURFACE_IDS,
    SOURCE_MISSING,
    SOURCE_NOT_IN_PINNED_REVISION,
    UIUX_DOMAIN_ID,
    UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE,
    UIUX_LOGIC_SLICE_V2_INTERFACE,
    UIUX_OWNER_ID,
    UIUX_PACKAGE_NAME,
    UIUX_SOURCE_GATE_V2_INTERFACE,
    AdapterScope,
    GateDisposition,
    RequirementSurface,
    SliceStatus,
    SourcePresence,
    UIUXFormalizationAdapter,
    UIUXFreeFormRejectedError,
    UIUXLogicGateV2Error,
    UIUXLogicSliceConnector,
    UIUXPackageWriteForbiddenError,
    UIUXSliceAdmissionError,
    UIUXSourceGate,
    UIUXSourceMissingError,
    absent_matrix_disposition,
    adapter_gaps_for,
    build_adapter_gap,
    build_ui_ux_logic_slice_v2,
    canonicalize_frame_logic_label,
    default_logic_package_root,
    default_requirement_surfaces,
    frame_logic_alias_table,
    package_is_present,
    scan_ui_ux_source_gate_v2,
    ui_ux_package_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def logic_root_absent(tmp_path: Path) -> Path:
    """A logic root without ui_ux_ir (mirrors the current pinned tree)."""

    root = tmp_path / "ipfs_datasets_py" / "logic"
    root.mkdir(parents=True)
    (root / "__init__.py").write_text("# logic package\n", encoding="utf-8")
    return root


@pytest.fixture
def logic_root_present(tmp_path: Path) -> Path:
    """A logic root with a minimal exact ui_ux_ir package present."""

    root = tmp_path / "ipfs_datasets_py" / "logic"
    package = root / UIUX_PACKAGE_NAME
    package.mkdir(parents=True)
    (root / "__init__.py").write_text("# logic package\n", encoding="utf-8")
    (package / "__init__.py").write_text(
        '"""Reviewed exact UI/UX source package (fixture)."""\n',
        encoding="utf-8",
    )
    (package / "model.py").write_text(
        "DOMAIN = 'ui_ux_ir'\n",
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_source_gate_v2_interface_identity() -> None:
    gate = UIUXSourceGate()
    assert UIUXSourceGate.INTERFACE == UIUX_SOURCE_GATE_V2_INTERFACE
    assert gate.interface == "UIUXSourceGate@2"
    assert gate.version == UIUXSourceGate.VERSION
    wire = gate.to_dict()
    assert wire["interface"] == "UIUXSourceGate@2"
    assert wire["domain"] == UIUX_DOMAIN_ID


def test_logic_slice_v2_interface_identity() -> None:
    connector = UIUXLogicSliceConnector()
    assert UIUXLogicSliceConnector.INTERFACE == UIUX_LOGIC_SLICE_V2_INTERFACE
    assert connector.interface == "UIUXLogicSlice@2"
    assert connector.version == "2.0.0"
    wire = connector.to_dict()
    assert wire["interface"] == "UIUXLogicSlice@2"
    assert wire["domain"] == UIUX_DOMAIN_ID
    assert wire["owner_id"] == UIUX_OWNER_ID


def test_formalization_adapter_v2_interface_identity() -> None:
    adapter = UIUXFormalizationAdapter()
    assert adapter.interface == UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE
    assert adapter.interface == "UIUXFormalizationAdapter@2"
    assert adapter.domain == UIUX_DOMAIN_ID
    wire = adapter.to_dict()
    assert wire["interface"] == "UIUXFormalizationAdapter@2"
    assert set(wire["scopes"]) == set(ADAPTER_SCOPE_IDS)


# ---------------------------------------------------------------------------
# Current pinned tree: source absent
# ---------------------------------------------------------------------------


def test_current_tree_ui_ux_package_is_absent() -> None:
    package = ui_ux_package_path()
    assert package.name == UIUX_PACKAGE_NAME
    assert package_is_present(package) is False
    assert not package.exists() or not package_is_present(package)


def test_scan_absent_source_is_declaration_only_not_blocked(
    logic_root_absent: Path,
) -> None:
    receipt = scan_ui_ux_source_gate_v2(
        logic_root=logic_root_absent,
        pinned_revision="git:fixture-absent",
    )
    assert receipt.disposition is GateDisposition.DECLARATION_ONLY
    assert receipt.identity.presence is SourcePresence.ABSENT
    assert receipt.identity.is_present is False
    assert receipt.matrix.support is SupportStatus.DECLARATION_ONLY
    assert receipt.matrix.availability is AvailabilityStatus.SOURCE_MISSING
    assert receipt.matrix.authority_ceiling is AuthorityCeiling.NONE
    assert receipt.matrix.reason_code == SOURCE_NOT_IN_PINNED_REVISION
    assert receipt.matrix.refill_eligible is True
    assert receipt.matrix.unimplemented is True
    assert receipt.matrix.blocks_other_work is False
    assert receipt.adapter_gaps == ()
    assert receipt.writes_ui_ux_ir is False
    assert receipt.blocks_other_work is False
    assert adapter_gaps_for(receipt) == ()
    wire = receipt.to_dict()
    assert wire["matrix"]["support"] == "declaration_only"
    assert wire["matrix"]["availability"] == SOURCE_MISSING
    assert wire["blocks_other_work"] is False


def test_live_scan_matches_absent_matrix_disposition() -> None:
    """Pinned workspace must record source_missing/declaration_only, not block."""

    receipt = scan_ui_ux_source_gate_v2()
    expected = absent_matrix_disposition()
    assert receipt.disposition is GateDisposition.DECLARATION_ONLY
    assert receipt.matrix.reason_code == expected.reason_code
    assert receipt.matrix.support is expected.support
    assert receipt.matrix.availability is expected.availability
    assert receipt.matrix.availability is AvailabilityStatus.SOURCE_MISSING
    assert receipt.matrix.support is SupportStatus.DECLARATION_ONLY
    assert receipt.writes_ui_ux_ir is False
    assert receipt.blocks_other_work is False
    # Gate must not invent package files.
    assert package_is_present(ui_ux_package_path()) is False


def test_receipt_is_content_addressed_and_deterministic(
    logic_root_absent: Path,
) -> None:
    first = scan_ui_ux_source_gate_v2(
        logic_root=logic_root_absent,
        pinned_revision="rev-a",
    )
    second = scan_ui_ux_source_gate_v2(
        logic_root=logic_root_absent,
        pinned_revision="rev-a",
    )
    assert first.content_digest == second.content_digest
    assert first.content_digest == first.recompute_content_digest()
    assert len(first.content_digest) == 64
    body = first.to_dict()
    assert body["content_digest"] == first.content_digest
    assert body["writes_ui_ux_ir"] is False
    assert body["blocks_other_work"] is False
    dumped = json.dumps(body, sort_keys=True)
    assert "source_missing" in dumped or "source_not_in_pinned_revision" in dumped
    assert "declaration_only" in dumped


def test_gate_never_writes_ui_ux_ir(logic_root_absent: Path, tmp_path: Path) -> None:
    gate = UIUXSourceGate(logic_root=logic_root_absent)
    package = ui_ux_package_path(logic_root_absent)
    assert not package.exists()
    # Scanning must leave the tree untouched.
    gate.scan()
    assert not package.exists()
    # Explicit write attempts under the package path fail closed.
    target = package / "model.py"
    with pytest.raises(UIUXPackageWriteForbiddenError):
        gate.forbid_package_write(target)
    # Unrelated paths are allowed.
    gate.forbid_package_write(tmp_path / "other.py")


def test_absent_source_does_not_block_other_work(logic_root_absent: Path) -> None:
    """Absent UI source is typed declaration-only and never a hard lane block."""

    receipt = scan_ui_ux_source_gate_v2(logic_root=logic_root_absent)
    slice_record = build_ui_ux_logic_slice_v2(logic_root=logic_root_absent)
    assert receipt.blocks_other_work is False
    assert receipt.matrix.blocks_other_work is False
    assert slice_record.blocks_other_work is False
    assert slice_record.is_declaration_only is True
    # Slice still records full requirement surfaces while source is missing.
    assert set(slice_record.surface_ids()) == set(REQUIREMENT_SURFACE_IDS)


# ---------------------------------------------------------------------------
# Present source → exactly one content-addressed owner-scoped adapter gap
# ---------------------------------------------------------------------------


def test_present_source_emits_exactly_one_adapter_gap(
    logic_root_present: Path,
) -> None:
    receipt = scan_ui_ux_source_gate_v2(
        logic_root=logic_root_present,
        pinned_revision="git:fixture-present",
    )
    assert receipt.disposition is GateDisposition.EMIT_ADAPTER_GAP
    assert receipt.identity.presence is SourcePresence.PRESENT
    assert receipt.identity.is_present is True
    assert receipt.identity.source_fingerprint
    assert len(receipt.adapter_gaps) == 1
    gaps = adapter_gaps_for(receipt)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_id.startswith("ui-ux-adapter-gap:")
    assert gap.source_fingerprint == receipt.identity.source_fingerprint
    assert gap.adapter_interface == UIUX_FORMALIZATION_ADAPTER_V2_INTERFACE
    assert gap.domain_id == UIUX_DOMAIN_ID
    assert gap.owner_id == UIUX_OWNER_ID
    # Identical re-scan emits the same single gap (content-addressed).
    again = scan_ui_ux_source_gate_v2(
        logic_root=logic_root_present,
        pinned_revision="git:fixture-present",
    )
    assert len(again.adapter_gaps) == 1
    assert again.adapter_gaps[0].gap_id == gap.gap_id
    assert again.adapter_gaps[0].content_digest() == gap.content_digest()
    # gap_id is content-addressed from the same body as content_digest.
    assert gap.gap_id == f"ui-ux-adapter-gap:{gap.content_digest()[:24]}"


def test_adapter_gap_acceptance_requires_syntax_not_tokens(
    logic_root_present: Path,
) -> None:
    receipt = scan_ui_ux_source_gate_v2(logic_root=logic_root_present)
    gap = receipt.adapter_gaps[0]
    required = set(gap.acceptance_requirements)
    assert required == set(ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS)
    assert "declared_syntax_parsing" in required
    assert "frame_logic_alias_canonicalization" in required
    assert "typed_structural_round_trips" in required
    assert "token_presence" not in required
    assert "token_presence" in gap.rejected_acceptance
    # Owner-scoped surfaces from the program effects list.
    scopes = set(gap.scopes)
    assert scopes == set(ADAPTER_SCOPE_IDS)
    for scope in AdapterScope:
        assert scope.value in scopes
    assert set(gap.requirement_surfaces) == set(REQUIREMENT_SURFACE_IDS)
    # Preserve graph schemas, source maps, authority flags, golden vectors.
    preserve = set(gap.preserve)
    assert {
        "graph_schemas",
        "source_maps",
        "authority_flags",
        "golden_vectors",
    }.issubset(preserve)


def test_build_adapter_gap_fails_when_source_absent(
    logic_root_absent: Path,
) -> None:
    identity = UIUXSourceGate(logic_root=logic_root_absent).observe_identity()
    with pytest.raises(UIUXLogicGateV2Error, match="absent"):
        build_adapter_gap(identity)


def test_empty_directory_is_not_present_source(tmp_path: Path) -> None:
    root = tmp_path / "ipfs_datasets_py" / "logic"
    empty = root / UIUX_PACKAGE_NAME
    empty.mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    assert package_is_present(empty) is False
    receipt = scan_ui_ux_source_gate_v2(logic_root=root)
    assert receipt.disposition is GateDisposition.DECLARATION_ONLY
    assert receipt.adapter_gaps == ()


# ---------------------------------------------------------------------------
# UIUXLogicSlice@2
# ---------------------------------------------------------------------------


def test_logic_slice_absent_records_requirements_without_blocking(
    logic_root_absent: Path,
) -> None:
    slice_record = build_ui_ux_logic_slice_v2(
        logic_root=logic_root_absent,
        pinned_revision="git:fixture-absent",
    )
    assert slice_record.interface == "UIUXLogicSlice@2"
    assert slice_record.status is SliceStatus.DECLARATION_ONLY
    assert slice_record.is_declaration_only is True
    assert slice_record.is_admitted is False
    assert slice_record.matrix.availability is AvailabilityStatus.SOURCE_MISSING
    assert slice_record.matrix.support is SupportStatus.DECLARATION_ONLY
    assert slice_record.adapter_gaps == ()
    assert slice_record.blocks_other_work is False
    assert set(slice_record.surface_ids()) == set(REQUIREMENT_SURFACE_IDS)
    for surface in RequirementSurface:
        assert surface.value in slice_record.surface_ids()
    with pytest.raises(UIUXSliceAdmissionError):
        slice_record.require_admitted()
    # Content-addressed and deterministic.
    again = build_ui_ux_logic_slice_v2(
        logic_root=logic_root_absent,
        pinned_revision="git:fixture-absent",
    )
    assert again.content_digest == slice_record.content_digest
    assert again.content_digest == again.recompute_content_digest()
    wire = slice_record.to_dict()
    assert wire["status"] == "declaration_only"
    assert wire["matrix"]["availability"] == "source_missing"
    assert wire["blocks_other_work"] is False


def test_logic_slice_present_carries_one_owner_scoped_adapter_gap(
    logic_root_present: Path,
) -> None:
    slice_record = build_ui_ux_logic_slice_v2(
        logic_root=logic_root_present,
        pinned_revision="git:fixture-present",
    )
    assert slice_record.status is SliceStatus.ADAPTER_GAP
    assert slice_record.identity.is_present is True
    assert len(slice_record.adapter_gaps) == 1
    gap = slice_record.adapter_gaps[0]
    assert gap.owner_id == UIUX_OWNER_ID
    assert gap.gap_id.startswith("ui-ux-adapter-gap:")
    assert set(gap.requirement_surfaces) == set(REQUIREMENT_SURFACE_IDS)
    assert slice_record.blocks_other_work is False
    assert slice_record.gate_receipt_digest
    assert len(slice_record.gate_receipt_digest) == 64
    # Still not admitted — adapter gap must be closed first.
    with pytest.raises(UIUXSliceAdmissionError):
        slice_record.require_admitted()


def test_requirement_surfaces_cover_plan_obligations() -> None:
    surfaces = default_requirement_surfaces()
    ids = {item.surface_id for item in surfaces}
    assert ids == set(REQUIREMENT_SURFACE_IDS)
    by_id = {item.surface_id: item for item in surfaces}
    assert by_id["accessibility"].family_hint == "first_order"
    assert by_id["interaction_event"].family_hint == "event_calculus"
    assert by_id["workflow"].family_hint == "temporal"
    assert by_id["ontology_frame"].family_hint == "frame_logic"
    assert by_id["authorization"].family_hint == "authorization"
    assert by_id["observable_state"].family_hint == "transition_system"
    for item in surfaces:
        assert item.owner_id == UIUX_OWNER_ID


def test_connector_projects_gate_receipt(logic_root_absent: Path) -> None:
    gate = UIUXSourceGate(
        logic_root=logic_root_absent,
        pinned_revision="rev-connector",
    )
    connector = UIUXLogicSliceConnector(gate=gate)
    slice_record = connector.connect()
    receipt = gate.scan()
    assert slice_record.gate_receipt_digest == receipt.content_digest
    assert slice_record.status is SliceStatus.DECLARATION_ONLY


# ---------------------------------------------------------------------------
# frame_logic alias canonicalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["frame_logic", "FLogic", "F-logic"])
def test_frame_logic_aliases_canonicalize(label: str) -> None:
    assert canonicalize_frame_logic_label(label) == FRAME_LOGIC_FAMILY_ID


def test_frame_logic_alias_table_covers_registry_aliases() -> None:
    table = frame_logic_alias_table()
    assert table[FRAME_LOGIC_FAMILY_ID] == FRAME_LOGIC_FAMILY_ID
    for alias in FRAME_LOGIC_ALIASES:
        assert table[alias] == FRAME_LOGIC_FAMILY_ID


def test_non_frame_logic_label_fails_closed() -> None:
    with pytest.raises(UIUXLogicGateV2Error):
        canonicalize_frame_logic_label("first_order")
    with pytest.raises(UIUXLogicGateV2Error):
        canonicalize_frame_logic_label("not_a_family_xyz")


def test_adapter_canonicalize_family_label() -> None:
    adapter = UIUXFormalizationAdapter()
    assert adapter.canonicalize_family_label("FLogic") == "frame_logic"
    assert adapter.canonicalize_family_label("F-logic") == "frame_logic"


# ---------------------------------------------------------------------------
# Formalization adapter fail-closed while source missing
# ---------------------------------------------------------------------------


def test_adapter_formalize_fails_when_source_missing(
    logic_root_absent: Path,
) -> None:
    adapter = UIUXFormalizationAdapter(
        gate=UIUXSourceGate(logic_root=logic_root_absent)
    )
    with pytest.raises(UIUXSourceMissingError):
        adapter.formalize({"kind": "component"})
    with pytest.raises(UIUXFreeFormRejectedError):
        adapter.formalize("token presence only")
    with pytest.raises(UIUXSourceMissingError):
        adapter.require_source_present()


def test_adapter_formalize_rejects_free_form_even_when_present(
    logic_root_present: Path,
) -> None:
    adapter = UIUXFormalizationAdapter(
        gate=UIUXSourceGate(logic_root=logic_root_present)
    )
    # Source is present but free-form tokens still fail closed.
    with pytest.raises(UIUXFreeFormRejectedError):
        adapter.formalize("just tokens")
    # Typed request is present-source but adapter is declaration-only until
    # the owner-scoped adapter gap is closed.
    with pytest.raises(UIUXLogicGateV2Error, match="declaration-only interface"):
        adapter.formalize({"kind": "component_frame"})


def test_adapter_acceptance_contract() -> None:
    contract = UIUXFormalizationAdapter().acceptance_contract()
    assert contract["adapter_interface"] == "UIUXFormalizationAdapter@2"
    assert set(contract["required_acceptance"]) == set(
        ADAPTER_GAP_ACCEPTANCE_REQUIREMENTS
    )
    assert "token_presence" in contract["rejected_acceptance"]
    assert contract["frame_logic_aliases"]["FLogic"] == "frame_logic"
    assert set(contract["requirement_surfaces"]) == set(REQUIREMENT_SURFACE_IDS)


# ---------------------------------------------------------------------------
# Matrix alignment helpers
# ---------------------------------------------------------------------------


def test_absent_disposition_matches_capability_matrix_axes() -> None:
    disposition = absent_matrix_disposition()
    assert disposition.domain_id == "ui_ux_ir"
    assert disposition.support is SupportStatus.DECLARATION_ONLY
    assert disposition.availability is AvailabilityStatus.SOURCE_MISSING
    assert disposition.authority_ceiling is AuthorityCeiling.NONE
    assert disposition.reason_code == "source_not_in_pinned_revision"
    assert disposition.blocks_other_work is False
    # Round-trip wire form.
    wire = disposition.to_dict()
    assert wire["support"] == "declaration_only"
    assert wire["availability"] == "source_missing"
    assert wire["reason_code"] == "source_not_in_pinned_revision"
    assert wire["blocks_other_work"] is False


def test_default_logic_root_resolution() -> None:
    root = default_logic_package_root()
    assert root.name == "logic"
    assert root.is_dir()
    # Gate module lives under logic/conformance/.
    assert (root / "conformance" / "ui_ux_logic_gate_v2.py").is_file()
