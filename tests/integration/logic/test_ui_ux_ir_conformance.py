"""UIR-083: root current-tree conformance / release gate (offline)."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.logic.ui_ux_ir import (
    UIUXIR_PUBLIC_API_INTERFACE,
    public_api_manifest,
)
from ipfs_datasets_py.logic.ui_ux_ir.conformance import (
    UIIR_CROSS_LANGUAGE_PARITY_INTERFACE,
    default_golden_path,
    run_conformance,
)
from ipfs_datasets_py.logic.submodule_registry import logic_submodule_spec
from ipfs_datasets_py.logic.bridge.registry import logic_bridge_spec


def test_public_api_and_registries_present() -> None:
    assert UIUXIR_PUBLIC_API_INTERFACE == "UIUXIRPublicAPI@1"
    manifest = public_api_manifest()
    assert manifest["schema_id"] == "ui-ux-ir/v1"
    assert logic_submodule_spec("ui_ux_ir").module.endswith("ui_ux_ir")
    assert logic_bridge_spec("ui_ux_ir_formalization").implemented is True


def test_golden_conformance_green() -> None:
    # Resolve fixture relative to package tests when default path works.
    candidates = [
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "ui_ux_ir"
        / "v1"
        / "golden_vectors.json",
        default_golden_path(),
    ]
    path = next(p for p in candidates if Path(p).is_file())
    report = run_conformance(path)
    assert report.passed is True
    assert report.interface == UIIR_CROSS_LANGUAGE_PARITY_INTERFACE


def test_pilot_fixtures_enumerated() -> None:
    pilot_dir = (
        Path(__file__).resolve().parents[2] / "fixtures" / "ui_ux_ir" / "pilots"
    )
    expected = {
        "responsive_form.json",
        "destructive_workflow.json",
        "meta_glasses.json",
        "agent_supervisor_program.json",
    }
    present = {p.name for p in pilot_dir.glob("*.json")}
    assert expected <= present


def test_no_authority_substitution_in_public_manifest() -> None:
    # Manifest must not claim that formalization replaces mediation.
    manifest = public_api_manifest()
    assert "evaluate_ui_interaction" in manifest["public_symbols"]
    assert manifest["optional_runtimes_eager"] is False
