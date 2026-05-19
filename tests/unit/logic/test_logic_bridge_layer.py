from __future__ import annotations

import importlib
import sys


def _fresh_import(module_name: str):
    root = module_name.split(".", 1)[0]
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(root + "."):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def test_bridge_manifest_exposes_optimizer_lanes() -> None:
    from ipfs_datasets_py.logic.bridge import (
        bridge_name_for_component,
        logic_bridge_manifest,
        logic_bridge_spec,
    )

    manifest = logic_bridge_manifest()
    names = {entry["name"] for entry in manifest["bridges"]}

    assert {
        "cec_dcec",
        "deontic_norms",
        "external_prover_router",
        "fol_tdfol",
        "modal_frame_logic",
    } <= names
    assert manifest["implemented_bridges"] == ["modal_frame_logic", "deontic_norms"]
    assert bridge_name_for_component("modal.frame_logic") == "modal_frame_logic"
    assert bridge_name_for_component("modal.frame_logic.audit") == "modal_frame_logic"
    assert logic_bridge_spec("modal_frame_logic").implemented is True
    assert bridge_name_for_component("deontic.ir") == "deontic_norms"
    assert logic_bridge_spec("deontic_norms").implemented is True


def test_bridge_import_is_lightweight() -> None:
    bridge = _fresh_import("ipfs_datasets_py.logic.bridge")

    assert "LegalIRDocument" in bridge.__all__
    assert "ipfs_datasets_py.logic.integration" not in sys.modules
    assert "ipfs_datasets_py.logic.external_provers" not in sys.modules


def test_modal_frame_logic_bridge_evaluates_ir_graph_and_proof_gate() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="bridge-layer-smoke",
        citation="Bridge Layer Smoke",
    )

    assert report.adapter_name == "modal_frame_logic"
    assert report.ir_document.has_frame_logic is True
    assert report.ir_document.views["modal_ir"].metadata["formula_count"] >= 1
    assert report.ir_document.views["frame_logic"].metadata["triple_count"] > 0
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.node_count > 0
    assert report.graph_projection.relationship_count > 0
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.compiles is True
    assert report.round_trip.cross_entropy_loss >= 0.0
    assert "cosine_similarity" in report.round_trip.to_dict()
    assert report.total_loss >= 0.0
    assert report.to_dict()["ir_document"]["has_frame_logic"] is True


def test_deontic_bridge_evaluates_legal_norm_ir_and_prover_syntax() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="deontic-bridge-smoke",
        citation="Deontic Bridge Smoke",
    )

    assert report.adapter_name == "deontic_norms"
    assert report.ir_document.views["deontic_ir"].metadata["norm_count"] >= 1
    assert report.ir_document.views["deontic_formula_records"].metadata[
        "proof_ready_count"
    ] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.node_count > 0
    assert report.graph_projection.relationship_count > 0
    assert report.proof_gate.attempted_count >= 5
    assert report.proof_gate.valid_count >= 5
    assert report.round_trip.cosine_similarity >= 0.0
    assert "deontic_quality_requires_validation_loss" in report.round_trip.extra_losses
    assert report.to_dict()["ir_document"]["views"]["deontic_prover_syntax"][
        "metadata"
    ]["coverage_record_count"] >= 1


def test_logic_manifest_includes_bridge_layer() -> None:
    from ipfs_datasets_py.logic.submodule_registry import logic_integration_manifest

    manifest = logic_integration_manifest()
    bridge_entries = [
        entry
        for entry in manifest["submodules"]
        if entry["name"] == "bridge"
    ]

    assert len(bridge_entries) == 1
    bridge_entry = bridge_entries[0]
    assert "optimizer_contract" in bridge_entry["roles"]
    assert "bridge.registry" in bridge_entry["optimizer_components"]
