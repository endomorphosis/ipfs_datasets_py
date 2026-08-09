"""Unit tests for RawLogicBoundaryInventory@1 (LFP2-002)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.conformance.raw_boundary_inventory import (
    DEFAULT_SEALED_RELATIVE_ROOTS,
    INVENTORY_GOAL_ID,
    INVENTORY_TASK_ID,
    RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE,
    RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION,
    REQUIRED_EVIDENCE_KINDS,
    REQUIRED_GATES,
    BoundaryDisposition,
    BoundaryRole,
    GateKind,
    RawBoundaryInventoryError,
    RawBoundaryInventoryIncompleteError,
    RawBoundaryInventoryPolicy,
    RawBoundaryKind,
    RawBoundaryRecord,
    RawLogicBoundaryInventory,
    assert_raw_boundary_inventory_complete,
    build_raw_boundary_inventory_report,
    classify_raw_ingress,
    curated_raw_boundary_inventory,
    default_baseline_report_path,
    default_logic_package_root,
    inventory_raw_boundaries,
    load_raw_boundary_inventory,
    write_raw_boundary_inventory,
)

DATASETS_ROOT = Path(__file__).resolve().parents[4]
LOGIC_ROOT = DATASETS_ROOT / "ipfs_datasets_py" / "logic"
BASELINE_REPORT = (
    DATASETS_ROOT
    / "docs"
    / "architecture"
    / "logic"
    / "logic_parser_v2_baseline"
    / "raw_boundary_inventory.json"
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_inventory_is_deterministic_and_side_effect_free(tmp_path: Path) -> None:
    """Two inventories over the same tree match and do not write files."""

    package = tmp_path / "logic"
    _write_tree(
        package,
        {
            "TDFOL/parser_mod.py": (
                "class TDFOLParser:\n"
                "    def parse(self, text: str):\n"
                "        return text\n"
                "class Formula:\n"
                "    expression: str\n"
            ),
            "fol/utils/fol_parser.py": (
                "def parse_quantifiers(text: str):\n"
                "    return []\n"
            ),
            "formalization/views.py": (
                "from typing import Any\n"
                "class FormalFormula:\n"
                "    expression: Any\n"
            ),
            "backends/smt/compiler.py": (
                "class SoftwareVerificationSMTCompiler:\n"
                "    def compile(self, formula: str) -> str:\n"
                "        return formula\n"
                "    def emit(self, target_source: str) -> str:\n"
                "        return target_source\n"
            ),
            "parsers/smtlib.py": (
                "from ipfs_datasets_py.logic.syntax_core.contracts import ParseArtifact\n"
                "from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression\n"
                "def parse(source: str) -> ParseArtifact:\n"
                "    raise NotImplementedError\n"
            ),
            "syntax_core/ast.py": (
                "class LogicExtensionNode:\n"
                "    payload: object\n"
            ),
            "modal/compiler.py": (
                "class DeterministicModalCompiler:\n"
                "    def compile(self, formula: str):\n"
                "        return formula\n"
            ),
            "deontic/utils/deontic_parser.py": (
                "def extract_normative_elements(text: str):\n"
                "    return []\n"
            ),
        },
    )

    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    policy = RawBoundaryInventoryPolicy(
        relative_roots=(
            "TDFOL",
            "fol",
            "formalization",
            "backends",
            "parsers",
            "syntax_core",
            "modal",
            "deontic",
        )
    )
    first = inventory_raw_boundaries(
        logic_root=package, policy=policy, include_curated=False
    )
    second = inventory_raw_boundaries(
        logic_root=package, policy=policy, include_curated=False
    )
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}

    assert first.to_dict() == second.to_dict()
    assert first.content_digest() == second.content_digest()
    assert before == after
    assert first.schema_version == RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION
    assert first.interface == RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE
    assert first.boundaries


def test_inventory_identifies_evidence_kinds_and_gate_crossings(
    tmp_path: Path,
) -> None:
    package = tmp_path / "logic"
    _write_tree(
        package,
        {
            "TDFOL/tdfol_parser.py": (
                "class TDFOLParser:\n"
                "    def parse(self, formula: str) -> object:\n"
                "        return formula\n"
            ),
            "formalization/views.py": (
                "from typing import Any\n"
                "class FormalFormula:\n"
                "    expression: Any\n"
            ),
            "syntax_core/ast.py": (
                "class LogicExtensionNode:\n"
                "    extension_payload: dict\n"
            ),
            "backends/smt/compiler.py": (
                "def emit_smt(target_source: str) -> str:\n"
                "    return target_source\n"
            ),
            "parsers/gated.py": (
                "class ParseArtifact: pass\n"
                "class TypedExpression: pass\n"
                "def parse(source: str) -> ParseArtifact:\n"
                "    return ParseArtifact()\n"
            ),
        },
    )
    inventory = inventory_raw_boundaries(
        logic_root=package,
        policy=RawBoundaryInventoryPolicy(
            relative_roots=(
                "TDFOL",
                "formalization",
                "syntax_core",
                "backends",
                "parsers",
            )
        ),
        include_curated=False,
    )
    kinds = {item.kind for item in inventory.boundaries}
    assert RawBoundaryKind.FROZEN_JSON in kinds or any(
        item.kind is RawBoundaryKind.FROZEN_JSON for item in inventory.boundaries
    )
    assert any(
        item.kind
        in {
            RawBoundaryKind.RAW_STRING,
            RawBoundaryKind.PARSER_BYPASS,
        }
        for item in inventory.boundaries
    )
    assert any(
        item.kind is RawBoundaryKind.EXTENSION_PAYLOAD
        or "extension" in item.qualname
        for item in inventory.boundaries
    )
    assert any(
        item.kind is RawBoundaryKind.TARGET_SOURCE for item in inventory.boundaries
    )
    # Gated frontend references ParseArtifact in the same function body.
    gated = [
        item
        for item in inventory.boundaries
        if item.path.startswith("parsers/") and item.crosses_parse_artifact
    ]
    assert gated


def test_inventory_path_complete_under_sealed_policy(tmp_path: Path) -> None:
    package = tmp_path / "logic"
    roots = (
        "TDFOL",
        "fol",
        "deontic",
        "modal",
        "flogic",
        "software_verification",
        "backends",
        "CEC",
        "formalization",
        "parsers",
        "syntax_core",
    )
    files = {
        "TDFOL/a.py": "def parse(text: str): return text\n",
        "fol/b.py": "def parse_fol(text: str): return text\n",
        "deontic/c.py": "def parse_deontic(text: str): return text\n",
        "modal/d.py": "def compile(formula: str): return formula\n",
        "flogic/e.py": "class Frame: expression: str\n",
        "software_verification/f.py": "def parse(source: str): return source\n",
        "backends/smt/compiler.py": (
            "def emit(target_source: str): return target_source\n"
        ),
        "CEC/native/parser.py": "def parse(expression: str): return expression\n",
        "formalization/views.py": (
            "from typing import Any\n"
            "class FormalFormula:\n"
            "    expression: Any\n"
        ),
        "parsers/smtlib.py": "def parse(source: str): return source\n",
        "syntax_core/ast.py": "class Node: extension_payload: object\n",
    }
    _write_tree(package, files)
    policy = RawBoundaryInventoryPolicy(relative_roots=roots)
    inventory = inventory_raw_boundaries(
        logic_root=package, policy=policy, include_curated=True
    )
    assert_raw_boundary_inventory_complete(inventory, policy=policy)

    incomplete = RawLogicBoundaryInventory(
        boundaries=inventory.boundaries,
        scanned_files=tuple(
            path for path in inventory.scanned_files if not path.startswith("fol/")
        ),
        diagnostics=inventory.diagnostics,
        required_evidence_kinds=inventory.required_evidence_kinds,
        required_gates=inventory.required_gates,
    )
    with pytest.raises(RawBoundaryInventoryIncompleteError):
        assert_raw_boundary_inventory_complete(incomplete, policy=policy)


def test_fails_on_unclassified_executable_raw_ingress() -> None:
    """Acceptance: unclassified executable raw ingress is fail-closed."""

    bad = RawBoundaryRecord(
        boundary_id="raw_string:evil/path.py#ingress",
        kind=RawBoundaryKind.RAW_STRING,
        symbol="ingress",
        path="evil/path.py",
        qualname="ingress",
        role=BoundaryRole.INGRESS,
        disposition=BoundaryDisposition.UNCLASSIFIED,
        gates_crossed=(),
        executable=True,
        notes="synthetic unclassified ingress",
        discovery="test",
    )
    inventory = RawLogicBoundaryInventory(
        boundaries=(bad,),
        scanned_files=("evil/path.py",),
        required_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
        # Provide curated-like coverage via extra classified rows so only
        # the unclassified check fails.
        policy_profile_id="test-unclassified@1",
    )
    # Ensure evidence kinds are present so the assert focuses on classification.
    extras = list(curated_raw_boundary_inventory().boundaries)
    inventory = RawLogicBoundaryInventory(
        boundaries=tuple([bad, *extras]),
        scanned_files=("evil/path.py",) + curated_raw_boundary_inventory().scanned_files,
        required_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
        policy_profile_id="test-unclassified@1",
    )
    with pytest.raises(RawBoundaryInventoryIncompleteError, match="unclassified"):
        assert_raw_boundary_inventory_complete(
            inventory,
            require_policy_roots=False,
        )


def test_fails_on_silent_parser_bypass() -> None:
    """Acceptance: silent parser bypass is fail-closed."""

    silent = RawBoundaryRecord(
        boundary_id="parser_bypass:evil/silent.py#bypass",
        kind=RawBoundaryKind.PARSER_BYPASS,
        symbol="bypass",
        path="evil/silent.py",
        qualname="bypass",
        role=BoundaryRole.INGRESS,
        disposition=BoundaryDisposition.SILENT_BYPASS,
        gates_crossed=(),
        executable=True,
        notes="synthetic silent bypass",
        discovery="test",
    )
    extras = list(curated_raw_boundary_inventory().boundaries)
    inventory = RawLogicBoundaryInventory(
        boundaries=tuple([silent, *extras]),
        scanned_files=("evil/silent.py",)
        + curated_raw_boundary_inventory().scanned_files,
        required_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
        policy_profile_id="test-silent@1",
    )
    with pytest.raises(RawBoundaryInventoryIncompleteError, match="silent parser bypass"):
        assert_raw_boundary_inventory_complete(
            inventory,
            require_policy_roots=False,
        )


def test_classify_raw_ingress_gate_rules() -> None:
    assert (
        classify_raw_ingress(
            kind=RawBoundaryKind.RAW_STRING,
            gates_crossed=(
                GateKind.PARSE_ARTIFACT.value,
                GateKind.TYPED_EXPRESSION.value,
            ),
            executable=True,
        )
        is BoundaryDisposition.GATED
    )
    assert (
        classify_raw_ingress(
            kind=RawBoundaryKind.PARSER_BYPASS,
            gates_crossed=(),
            executable=True,
        )
        is BoundaryDisposition.KNOWN_BYPASS
    )
    assert (
        classify_raw_ingress(
            kind=RawBoundaryKind.RAW_STRING,
            gates_crossed=(),
            executable=True,
            role=BoundaryRole.INGRESS,
        )
        is BoundaryDisposition.SILENT_BYPASS
    )
    assert (
        classify_raw_ingress(
            kind=RawBoundaryKind.TARGET_SOURCE,
            gates_crossed=(GateKind.COMPILED_ARTIFACT.value,),
            executable=True,
        )
        is BoundaryDisposition.GATED
    )


def test_curated_inventory_covers_evidence_subset() -> None:
    inventory = curated_raw_boundary_inventory()
    assert_raw_boundary_inventory_complete(
        inventory, require_policy_roots=False
    )
    covered = inventory.covered_evidence_kinds()
    assert set(REQUIRED_EVIDENCE_KINDS) <= covered
    assert inventory.task_id == INVENTORY_TASK_ID
    assert inventory.goal_id == INVENTORY_GOAL_ID
    assert inventory.silent_parser_bypasses() == ()
    assert inventory.unclassified_executable() == ()

    by_id = {item.boundary_id: item for item in inventory.boundaries}
    assert "frozen_json:formalization/views.py#FormalFormula.expression" in by_id
    assert any(
        item.kind is RawBoundaryKind.PARSER_BYPASS for item in inventory.boundaries
    )
    assert any(
        item.kind is RawBoundaryKind.TARGET_SOURCE for item in inventory.boundaries
    )
    assert any(
        item.kind is RawBoundaryKind.EXTENSION_PAYLOAD for item in inventory.boundaries
    )


def test_live_logic_package_inventory_is_deterministic_and_complete() -> None:
    """Scan the real logic package without importing production parsers."""

    assert LOGIC_ROOT.is_dir(), f"missing logic root {LOGIC_ROOT}"
    inventory = inventory_raw_boundaries(logic_root=LOGIC_ROOT, include_curated=True)
    assert_raw_boundary_inventory_complete(inventory)

    covered = inventory.covered_evidence_kinds()
    assert set(REQUIRED_EVIDENCE_KINDS) <= covered

    curated_ids = set(curated_raw_boundary_inventory().boundary_ids)
    assert curated_ids <= set(inventory.boundary_ids)

    again = inventory_raw_boundaries(logic_root=LOGIC_ROOT, include_curated=True)
    assert inventory.content_digest() == again.content_digest()
    assert len(inventory.boundaries) >= len(curated_ids)
    assert inventory.silent_parser_bypasses() == ()
    assert inventory.unclassified_executable() == ()

    # Gate vocabulary is recorded on the inventory contract.
    assert set(REQUIRED_GATES) <= set(inventory.required_gates)
    # At least one boundary records each gate label somewhere, or curated
    # rows cover the gate set via required_gates + gate_coverage in report.
    report = build_raw_boundary_inventory_report(inventory)
    assert set(report["gate_coverage"]) == set(REQUIRED_GATES)


def test_baseline_report_exists_and_matches_configured_inventory() -> None:
    """The tracked report is a read-only snapshot of the sealed curated inventory.

    The baseline seals the LFP2-002 evidence subset (curated high-signal raw
    boundaries). Live exhaustive scan completeness is covered separately by
    ``test_live_logic_package_inventory_is_deterministic_and_complete``.
    """

    assert BASELINE_REPORT.is_file(), (
        f"missing baseline report at {BASELINE_REPORT}; "
        "LFP2-002 owns this output and must materialize it"
    )
    before = BASELINE_REPORT.read_bytes()
    report = load_raw_boundary_inventory(BASELINE_REPORT)
    current = curated_raw_boundary_inventory()
    expected = build_raw_boundary_inventory_report(current)

    assert report["interface"] == RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE
    assert report["schema_version"] == RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION
    assert report["task_id"] == INVENTORY_TASK_ID
    assert report["goal_id"] == INVENTORY_GOAL_ID
    assert report == expected
    assert report["content_digest"] == current.content_digest()
    assert report["scanned_files"] == list(current.scanned_files)
    assert report["unclassified_executable_count"] == 0
    assert report["silent_parser_bypass_count"] == 0
    assert report["evidence_coverage"]["missing_kinds"] == []
    assert set(REQUIRED_EVIDENCE_KINDS) <= set(
        report["evidence_coverage"]["covered_kinds"]
    )
    boundary_ids = [item["boundary_id"] for item in report["boundaries"]]
    assert len(boundary_ids) == len(set(boundary_ids))

    for boundary in report["boundaries"]:
        rel = boundary["path"]
        if rel.endswith(".py"):
            path = LOGIC_ROOT / Path(*Path(rel).parts)
            assert path.is_file(), f"baseline path missing: {rel}"

    # Live scan must remain a superset of the sealed curated evidence rows.
    live = inventory_raw_boundaries(logic_root=LOGIC_ROOT, include_curated=True)
    assert set(current.boundary_ids) <= set(live.boundary_ids)
    assert BASELINE_REPORT.read_bytes() == before


def test_write_raw_boundary_inventory_round_trip(tmp_path: Path) -> None:
    inventory = inventory_raw_boundaries(logic_root=LOGIC_ROOT)
    out = tmp_path / "raw_boundary_inventory.json"
    written = write_raw_boundary_inventory(out, inventory=inventory)
    assert written == out
    loaded = load_raw_boundary_inventory(out)
    assert loaded == build_raw_boundary_inventory_report(inventory)
    assert loaded["content_digest"] == inventory.content_digest()
    assert loaded["boundary_count"] == len(inventory.boundaries)


def test_boundary_record_rejects_invalid_path() -> None:
    with pytest.raises(RawBoundaryInventoryError):
        RawBoundaryRecord(
            boundary_id="raw_string:x#Y",
            kind=RawBoundaryKind.RAW_STRING,
            symbol="Y",
            path="../escape.py",
            qualname="Y",
        )


def test_default_paths_resolve_in_checkout() -> None:
    root = default_logic_package_root()
    assert root.name == "logic"
    baseline = default_baseline_report_path(LOGIC_ROOT)
    assert baseline.name == "raw_boundary_inventory.json"
    assert "logic_parser_v2_baseline" in baseline.as_posix()


def test_inventory_from_dict_round_trip() -> None:
    inventory = curated_raw_boundary_inventory()
    restored = RawLogicBoundaryInventory.from_dict(inventory.to_dict())
    assert restored.content_digest() == inventory.content_digest()


def test_import_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    """Importing the inventory module must not create ambient files."""

    marker = tmp_path / "no-write-marker"
    marker.write_text("ok", encoding="utf-8")
    before = marker.stat().st_mtime_ns
    import ipfs_datasets_py.logic.conformance.raw_boundary_inventory as inv

    assert inv.RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE == (
        RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE
    )
    assert marker.stat().st_mtime_ns == before
    assert os.environ.get("LFP2_RAW_BOUNDARY_SHOULD_NOT_EXIST") is None


def test_sealed_roots_cover_parser_formalization_backend_domain() -> None:
    roots = set(DEFAULT_SEALED_RELATIVE_ROOTS)
    for required in (
        "parsers",
        "formalization",
        "backends",
        "TDFOL",
        "CEC",
        "security_ir",
        "crypto_ir",
        "intent_ir",
        "legal_ir",
        "software_verification",
    ):
        assert required in roots
