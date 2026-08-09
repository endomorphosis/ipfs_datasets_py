"""Unit tests for LogicSurfaceInventory@1 (LFP-001)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.conformance.inventory import (
    DEFAULT_LOGIC_RELATIVE_ROOTS,
    FormulaBoundaryKind,
    InventoryError,
    InventoryIncompleteError,
    LOGIC_SURFACE_INVENTORY_INTERFACE,
    LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION,
    LogicSurfaceInventory,
    LogicSurfaceRecord,
    REQUIRED_EVIDENCE_FAMILIES,
    SurfaceInventoryPolicy,
    SurfaceKind,
    assert_inventory_complete,
    build_parser_inventory_report,
    curated_logic_surface_inventory,
    default_baseline_report_path,
    default_logic_package_root,
    inventory_logic_surfaces,
    load_parser_inventory,
    write_parser_inventory,
)

DATASETS_ROOT = Path(__file__).resolve().parents[4]
LOGIC_ROOT = DATASETS_ROOT / "ipfs_datasets_py" / "logic"
BASELINE_REPORT = (
    DATASETS_ROOT
    / "docs"
    / "architecture"
    / "logic"
    / "logic_parser_baseline"
    / "parser_inventory.json"
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_inventory_is_deterministic_and_side_effect_free(tmp_path: Path) -> None:
    """Two inventories over the same tree match exactly and do not write files."""

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
            "deontic/decoder.py": (
                "def decode_legal_norm_ir(norm):\n"
                "    return norm\n"
            ),
            "modal/compiler.py": (
                "class DeterministicModalCompiler:\n"
                "    def compile(self, formula: str):\n"
                "        return formula\n"
            ),
            "flogic/flogic_types.py": (
                "class FLogicFrame:\n"
                "    def to_ergo_string(self) -> str:\n"
                "        return ''\n"
            ),
            "software_verification/monitoring/runtime_mtl.py": (
                "class Formula:\n"
                "    operator: str\n"
            ),
            "backends/smt/compiler.py": (
                "class SoftwareVerificationSMTCompiler:\n"
                "    pass\n"
            ),
            "CEC/native/dcec_parsing.py": (
                "def parse_dcec(source: str):\n"
                "    return source\n"
            ),
        },
    )

    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}
    policy = SurfaceInventoryPolicy(relative_roots=DEFAULT_LOGIC_RELATIVE_ROOTS)
    first = inventory_logic_surfaces(
        logic_root=package,
        policy=policy,
        include_curated=False,
    )
    second = inventory_logic_surfaces(
        logic_root=package,
        policy=policy,
        include_curated=False,
    )
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()}

    assert first.to_dict() == second.to_dict()
    assert first.content_digest() == second.content_digest()
    assert before == after
    assert first.schema_version == LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION
    assert first.interface == LOGIC_SURFACE_INVENTORY_INTERFACE


def test_inventory_identifies_raw_string_and_arbitrary_json_boundaries(
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
            "fol/utils/fol_parser.py": "def parse_quantifiers(text: str): return []\n",
        },
    )
    inventory = inventory_logic_surfaces(
        logic_root=package,
        policy=SurfaceInventoryPolicy(
            relative_roots=("TDFOL", "formalization", "fol"),
        ),
        include_curated=False,
    )
    boundaries = inventory.formula_boundaries
    kinds = {item.boundary_kind for item in boundaries}
    assert FormulaBoundaryKind.RAW_STRING in kinds
    assert FormulaBoundaryKind.ARBITRARY_JSON in kinds
    assert any("FormalFormula.expression" in item.qualname for item in boundaries)


def test_inventory_path_complete_under_policy(tmp_path: Path) -> None:
    package = tmp_path / "logic"
    _write_tree(
        package,
        {
            "TDFOL/a.py": "class Formula: expression: str\n",
            "fol/b.py": "def parse_fol(text: str): return text\n",
            "deontic/c.py": "class DeonticParser: pass\n",
            "modal/d.py": "class ModalCompiler: pass\n",
            "flogic/e.py": "class FLogicFrame: pass\n",
            "software_verification/monitoring/runtime_mtl.py": "class Formula: pass\n",
            "backends/smt/compiler.py": "class SMTCompiler: pass\n",
            "CEC/native/parser.py": "class DCECParser: pass\n",
            "formalization/views.py": (
                "from typing import Any\n"
                "class FormalFormula:\n"
                "    expression: Any\n"
            ),
        },
    )
    roots = (
        "TDFOL",
        "fol",
        "deontic",
        "modal",
        "flogic",
        "software_verification/monitoring",
        "backends/smt",
        "CEC",
        "formalization",
    )
    policy = SurfaceInventoryPolicy(relative_roots=roots)
    inventory = inventory_logic_surfaces(
        logic_root=package, policy=policy, include_curated=True
    )
    assert_inventory_complete(inventory, policy=policy)

    incomplete = LogicSurfaceInventory(
        surfaces=inventory.surfaces,
        scanned_files=tuple(
            path for path in inventory.scanned_files if not path.startswith("fol/")
        ),
        diagnostics=inventory.diagnostics,
        required_evidence_families=inventory.required_evidence_families,
    )
    with pytest.raises(InventoryIncompleteError):
        assert_inventory_complete(incomplete, policy=policy)


def test_curated_inventory_covers_evidence_and_boundaries() -> None:
    inventory = curated_logic_surface_inventory()
    assert_inventory_complete(inventory, require_policy_roots=False)

    covered = inventory.covered_evidence_families()
    assert set(REQUIRED_EVIDENCE_FAMILIES) <= covered

    by_id = {item.surface_id: item for item in inventory.surfaces}
    assert "parser:TDFOL/tdfol_parser.py#TDFOLParser" in by_id
    boundary = by_id["formula_boundary:formalization/views.py#FormalFormula.expression"]
    assert boundary.boundary_kind is FormulaBoundaryKind.ARBITRARY_JSON
    assert any(
        item.boundary_kind is FormulaBoundaryKind.RAW_STRING
        for item in inventory.formula_boundaries
    )

    kinds = {item.kind for item in inventory.surfaces}
    for required in (
        SurfaceKind.PARSER,
        SurfaceKind.AST,
        SurfaceKind.FORMULA,
        SurfaceKind.TERM,
        SurfaceKind.PRINTER,
        SurfaceKind.COMPILER,
        SurfaceKind.RESULT_DECODER,
        SurfaceKind.FORMULA_BOUNDARY,
        SurfaceKind.LEGACY_DUPLICATE,
    ):
        assert required in kinds


def test_live_logic_package_inventory_is_deterministic_and_complete() -> None:
    """Scan the real logic package without importing production parsers."""

    assert LOGIC_ROOT.is_dir(), f"missing logic root {LOGIC_ROOT}"
    inventory = inventory_logic_surfaces(logic_root=LOGIC_ROOT, include_curated=True)
    assert_inventory_complete(inventory)

    covered = inventory.covered_evidence_families()
    assert set(REQUIRED_EVIDENCE_FAMILIES) <= covered

    curated_ids = set(curated_logic_surface_inventory().surface_ids)
    assert curated_ids <= set(inventory.surface_ids)

    again = inventory_logic_surfaces(logic_root=LOGIC_ROOT, include_curated=True)
    assert inventory.content_digest() == again.content_digest()
    assert len(inventory.surfaces) >= len(curated_ids)


def test_baseline_report_exists_and_matches_configured_inventory() -> None:
    """The tracked report is a read-only snapshot of the configured scan."""

    assert BASELINE_REPORT.is_file(), (
        f"missing baseline report at {BASELINE_REPORT}; "
        "LFP-001 owns this output and must materialize it"
    )
    before = BASELINE_REPORT.read_bytes()
    report = load_parser_inventory(BASELINE_REPORT)
    current = inventory_logic_surfaces(logic_root=LOGIC_ROOT)
    expected = build_parser_inventory_report(current)

    assert report["interface"] == LOGIC_SURFACE_INVENTORY_INTERFACE
    assert report["schema_version"] == LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION
    assert report["task_id"] == "LFP-001"
    assert report["goal_id"] == "LFP-G010"
    assert report == expected
    assert report["content_digest"] == current.content_digest()
    assert report["scanned_files"] == list(current.scanned_files)
    assert report["formula_boundaries"]["raw_string"]
    assert report["formula_boundaries"]["arbitrary_json"]
    assert report["evidence_coverage"]["missing_families"] == []
    assert set(REQUIRED_EVIDENCE_FAMILIES) <= set(
        report["evidence_coverage"]["covered_families"]
    )
    surface_ids = [surface["surface_id"] for surface in report["surfaces"]]
    assert len(surface_ids) == len(set(surface_ids))
    assert any(
        "runtime_mtl" in surface["family_hints"]
        for surface in report["surfaces"]
    )

    # Baseline paths that name files must exist in the live tree.
    for surface in report["surfaces"]:
        rel = surface["path"]
        if rel.endswith(".py"):
            path = LOGIC_ROOT / Path(*Path(rel).parts)
            assert path.is_file(), f"baseline path missing: {rel}"
    assert BASELINE_REPORT.read_bytes() == before


def test_write_parser_inventory_round_trip(tmp_path: Path) -> None:
    inventory = inventory_logic_surfaces(logic_root=LOGIC_ROOT)
    out = tmp_path / "parser_inventory.json"
    written = write_parser_inventory(out, inventory=inventory)
    assert written == out
    loaded = load_parser_inventory(out)
    assert loaded == build_parser_inventory_report(inventory)
    assert loaded["content_digest"] == inventory.content_digest()
    assert loaded["surface_count"] == len(inventory.surfaces)


def test_surface_record_rejects_invalid_path() -> None:
    with pytest.raises(InventoryError):
        LogicSurfaceRecord(
            surface_id="parser:x#Y",
            kind=SurfaceKind.PARSER,
            symbol="Y",
            path="../escape.py",
            qualname="Y",
        )


def test_default_paths_resolve_in_checkout() -> None:
    root = default_logic_package_root()
    assert root.name == "logic"
    baseline = default_baseline_report_path(LOGIC_ROOT)
    assert baseline.name == "parser_inventory.json"
    assert "logic_parser_baseline" in baseline.as_posix()


def test_inventory_from_dict_round_trip() -> None:
    inventory = curated_logic_surface_inventory()
    restored = LogicSurfaceInventory.from_dict(inventory.to_dict())
    assert restored.content_digest() == inventory.content_digest()


def test_import_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    """Importing the inventory module must not create ambient files."""

    marker = tmp_path / "no-write-marker"
    marker.write_text("ok", encoding="utf-8")
    before = marker.stat().st_mtime_ns
    import ipfs_datasets_py.logic.conformance.inventory as inv

    assert inv.LOGIC_SURFACE_INVENTORY_INTERFACE == LOGIC_SURFACE_INVENTORY_INTERFACE
    assert marker.stat().st_mtime_ns == before
    assert os.environ.get("LFP_INVENTORY_SHOULD_NOT_EXIST") is None
