"""Conformance: exact-source UI/UX migration gate (LFP-038 / LFP-050).

Acceptance:

* The current absent UI/UX source causes no ui_ux_ir writes and yields a typed,
  content-addressed external-source gate rather than a blocked lane
* Matrix disposition is declaration_only + source_missing with
  source_not_in_pinned_revision
* When a new pinned revision contains the package, identical scanning emits
  exactly one derived migration task
* Derived-task acceptance requires declared-syntax parsing, frame_logic alias
  canonicalization, and typed structural round trips — not token presence
* UIUXFormalizationAdapter@1 remains fail-closed until exact source import

Interfaces: UIUXSourceGate@1, UIUXFormalizationAdapter@1
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
from ipfs_datasets_py.logic.conformance.ui_ux_source_gate import (
    ADAPTER_SCOPE_IDS,
    DERIVED_TASK_ACCEPTANCE_REQUIREMENTS,
    FRAME_LOGIC_ALIASES,
    FRAME_LOGIC_FAMILY_ID,
    SOURCE_NOT_IN_PINNED_REVISION,
    UIUX_DOMAIN_ID,
    UIUX_FORMALIZATION_ADAPTER_INTERFACE,
    UIUX_PACKAGE_NAME,
    UIUX_SOURCE_GATE_INTERFACE,
    AdapterScope,
    GateDisposition,
    SourcePresence,
    UIUXFormalizationAdapter,
    UIUXFreeFormRejectedError,
    UIUXPackageWriteForbiddenError,
    UIUXSourceGate,
    UIUXSourceGateError,
    UIUXSourceMissingError,
    absent_matrix_disposition,
    build_derived_migration_task,
    canonicalize_frame_logic_label,
    default_logic_package_root,
    derived_migration_tasks_for,
    frame_logic_alias_table,
    package_is_present,
    scan_ui_ux_source_gate,
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


def test_source_gate_interface_identity() -> None:
    gate = UIUXSourceGate()
    assert UIUXSourceGate.INTERFACE == UIUX_SOURCE_GATE_INTERFACE
    assert gate.interface == "UIUXSourceGate@1"
    assert gate.version == UIUXSourceGate.VERSION
    wire = gate.to_dict()
    assert wire["interface"] == "UIUXSourceGate@1"
    assert wire["domain"] == UIUX_DOMAIN_ID


def test_formalization_adapter_interface_identity() -> None:
    adapter = UIUXFormalizationAdapter()
    assert UIUXFormalizationAdapter.INTERFACE == UIUX_FORMALIZATION_ADAPTER_INTERFACE
    assert adapter.interface == "UIUXFormalizationAdapter@1"
    assert adapter.domain == UIUX_DOMAIN_ID
    wire = adapter.to_dict()
    assert wire["interface"] == "UIUXFormalizationAdapter@1"
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
    receipt = scan_ui_ux_source_gate(
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
    assert receipt.derived_tasks == ()
    assert receipt.writes_ui_ux_ir is False
    assert derived_migration_tasks_for(receipt) == ()


def test_live_scan_matches_absent_matrix_disposition() -> None:
    """Pinned workspace must record source_not_in_pinned_revision, not block."""

    receipt = scan_ui_ux_source_gate()
    expected = absent_matrix_disposition()
    assert receipt.disposition is GateDisposition.DECLARATION_ONLY
    assert receipt.matrix.reason_code == expected.reason_code
    assert receipt.matrix.support is expected.support
    assert receipt.matrix.availability is expected.availability
    assert receipt.writes_ui_ux_ir is False
    # Gate must not invent package files.
    assert package_is_present(ui_ux_package_path()) is False


def test_receipt_is_content_addressed_and_deterministic(
    logic_root_absent: Path,
) -> None:
    first = scan_ui_ux_source_gate(
        logic_root=logic_root_absent,
        pinned_revision="rev-a",
    )
    second = scan_ui_ux_source_gate(
        logic_root=logic_root_absent,
        pinned_revision="rev-a",
    )
    assert first.content_digest == second.content_digest
    assert first.content_digest == first.recompute_content_digest()
    assert len(first.content_digest) == 64
    # Absolute paths may differ in wire form but digest body is stable.
    body = first.to_dict()
    assert body["content_digest"] == first.content_digest
    assert body["writes_ui_ux_ir"] is False
    assert "source_not_in_pinned_revision" in json.dumps(body, sort_keys=True)


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


# ---------------------------------------------------------------------------
# Present source → exactly one derived migration task
# ---------------------------------------------------------------------------


def test_present_source_emits_exactly_one_derived_task(
    logic_root_present: Path,
) -> None:
    receipt = scan_ui_ux_source_gate(
        logic_root=logic_root_present,
        pinned_revision="git:fixture-present",
    )
    assert receipt.disposition is GateDisposition.DERIVE_MIGRATION_TASK
    assert receipt.identity.presence is SourcePresence.PRESENT
    assert receipt.identity.is_present is True
    assert receipt.identity.source_fingerprint
    assert len(receipt.derived_tasks) == 1
    tasks = derived_migration_tasks_for(receipt)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id.startswith("ui-ux-adapter-migration:")
    assert task.source_fingerprint == receipt.identity.source_fingerprint
    assert task.adapter_interface == UIUX_FORMALIZATION_ADAPTER_INTERFACE
    assert task.domain_id == UIUX_DOMAIN_ID
    # Identical re-scan emits the same single task (content-addressed).
    again = scan_ui_ux_source_gate(
        logic_root=logic_root_present,
        pinned_revision="git:fixture-present",
    )
    assert len(again.derived_tasks) == 1
    assert again.derived_tasks[0].task_id == task.task_id
    assert again.derived_tasks[0].content_digest() == task.content_digest()


def test_derived_task_acceptance_requires_syntax_not_tokens(
    logic_root_present: Path,
) -> None:
    receipt = scan_ui_ux_source_gate(logic_root=logic_root_present)
    task = receipt.derived_tasks[0]
    required = set(task.acceptance_requirements)
    assert required == set(DERIVED_TASK_ACCEPTANCE_REQUIREMENTS)
    assert "declared_syntax_parsing" in required
    assert "frame_logic_alias_canonicalization" in required
    assert "typed_structural_round_trips" in required
    assert "token_presence" not in required
    assert "token_presence" in task.rejected_acceptance
    # Owner-scoped surfaces from the program effects list.
    scopes = set(task.scopes)
    assert scopes == set(ADAPTER_SCOPE_IDS)
    for scope in AdapterScope:
        assert scope.value in scopes
    # Preserve graph schemas, source maps, authority flags, golden vectors.
    preserve = set(task.preserve)
    assert {
        "graph_schemas",
        "source_maps",
        "authority_flags",
        "golden_vectors",
    }.issubset(preserve)


def test_build_derived_task_fails_when_source_absent(
    logic_root_absent: Path,
) -> None:
    identity = UIUXSourceGate(logic_root=logic_root_absent).observe_identity()
    with pytest.raises(UIUXSourceGateError, match="absent"):
        build_derived_migration_task(identity)


def test_empty_directory_is_not_present_source(tmp_path: Path) -> None:
    root = tmp_path / "ipfs_datasets_py" / "logic"
    empty = root / UIUX_PACKAGE_NAME
    empty.mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    assert package_is_present(empty) is False
    receipt = scan_ui_ux_source_gate(logic_root=root)
    assert receipt.disposition is GateDisposition.DECLARATION_ONLY
    assert receipt.derived_tasks == ()


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
    with pytest.raises(UIUXSourceGateError):
        canonicalize_frame_logic_label("first_order")
    with pytest.raises(UIUXSourceGateError):
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
    # the derived migration implements formalization.
    with pytest.raises(UIUXSourceGateError, match="declaration-only interface"):
        adapter.formalize({"kind": "component_frame"})


def test_adapter_acceptance_contract() -> None:
    contract = UIUXFormalizationAdapter().acceptance_contract()
    assert contract["adapter_interface"] == "UIUXFormalizationAdapter@1"
    assert set(contract["required_acceptance"]) == set(
        DERIVED_TASK_ACCEPTANCE_REQUIREMENTS
    )
    assert "token_presence" in contract["rejected_acceptance"]
    assert contract["frame_logic_aliases"]["FLogic"] == "frame_logic"


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
    # Round-trip wire form.
    wire = disposition.to_dict()
    assert wire["support"] == "declaration_only"
    assert wire["availability"] == "source_missing"
    assert wire["reason_code"] == "source_not_in_pinned_revision"


def test_default_logic_root_resolution() -> None:
    root = default_logic_package_root()
    assert root.name == "logic"
    assert root.is_dir()
    # Gate module lives under logic/conformance/.
    assert (root / "conformance" / "ui_ux_source_gate.py").is_file()
