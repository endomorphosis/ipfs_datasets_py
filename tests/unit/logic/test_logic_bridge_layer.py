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
    assert manifest["implemented_bridges"] == [
        "modal_frame_logic",
        "deontic_norms",
        "fol_tdfol",
        "cec_dcec",
        "external_prover_router",
    ]
    assert bridge_name_for_component("modal.frame_logic") == "modal_frame_logic"
    assert bridge_name_for_component("modal.frame_logic.audit") == "modal_frame_logic"
    assert logic_bridge_spec("modal_frame_logic").implemented is True
    assert bridge_name_for_component("deontic.ir") == "deontic_norms"
    assert logic_bridge_spec("deontic_norms").implemented is True
    assert bridge_name_for_component("TDFOL.prover") == "fol_tdfol"
    assert bridge_name_for_component("CEC.native") == "cec_dcec"
    assert (
        bridge_name_for_component("external_provers.router")
        == "external_prover_router"
    )


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
    assert report.ir_document.views["deontic_decoder_reconstructions"].metadata[
        "decoder_record_count"
    ] >= 1
    assert report.ir_document.views["deontic_ir_slot_provenance"].metadata[
        "provenance_record_count"
    ] >= 1
    assert report.ir_document.views["deontic_phase8_quality"].metadata[
        "quality_record_count"
    ] >= 1
    assert report.ir_document.views["deontic_graph"].metadata["rule_count"] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.node_count > 0
    assert report.graph_projection.relationship_count > 0
    assert report.proof_gate.attempted_count >= 5
    assert report.proof_gate.valid_count >= 5
    assert report.round_trip.cosine_similarity >= 0.0
    assert "deontic_decoder_slot_loss" in report.round_trip.extra_losses
    assert "deontic_ir_slot_provenance_loss" in report.round_trip.extra_losses
    assert "deontic_quality_requires_validation_loss" in report.round_trip.extra_losses
    assert report.total_loss >= report.round_trip.extra_losses[
        "deontic_quality_requires_validation_loss"
    ]
    assert report.to_dict()["ir_document"]["views"]["deontic_prover_syntax"][
        "metadata"
    ]["coverage_record_count"] >= 1


def test_tdfol_bridge_evaluates_proof_obligations_and_graph() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("fol_tdfol")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="tdfol-bridge-smoke",
        citation="TDFOL Bridge Smoke",
    )

    assert report.adapter_name == "fol_tdfol"
    assert report.ir_document.views["tdfol_formula"].metadata["formula_count"] >= 1
    assert report.ir_document.views["proof_obligations"].metadata[
        "obligation_count"
    ] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.proof_gate.attempted_count >= 1
    assert "tdfol_parse_failure_ratio" in report.round_trip.extra_losses


def test_cec_dcec_bridge_evaluates_event_formulas_and_graph() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="cec-bridge-smoke",
        citation="CEC Bridge Smoke",
    )

    assert report.adapter_name == "cec_dcec"
    assert report.ir_document.views["cec_events"].metadata["event_count"] >= 1
    assert report.ir_document.views["dcec_formula"].metadata["formula_count"] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.proof_gate.compiles is True
    formula_records = report.ir_document.views["dcec_formula"].payload["records"]
    assert formula_records
    assert formula_records[0]["formula"].startswith(("O[", "P[", "F["))
    assert "happens(" in formula_records[0]["formula"]
    assert report.proof_gate.details[0]["validation_reason"] == "compiled_dcec_native_container"
    assert "cec_dcec_validation_failure_ratio" in report.round_trip.extra_losses


def test_external_prover_router_bridge_uses_native_prover_gate() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("external_prover_router")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-smoke",
        citation="External Prover Bridge Smoke",
    )

    assert report.adapter_name == "external_prover_router"
    assert report.ir_document.views["prover_formulas"].metadata["formula_count"] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.proof_gate.attempted_count >= 1
    assert "external_prover_unavailable_loss" in report.round_trip.extra_losses


def test_external_prover_router_bridge_proof_gate_routes_external_when_native_disabled(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _FakeRouteResult:
        def __init__(self) -> None:
            self.is_proved = True
            self.prover_used = "symbolicai"
            self.proof_time = 0.01
            self.reason = "Proved by symbolicai"
            self.strategy_used = "sequential"

    class _FakeRouter:
        provers = {"symbolicai": object()}

        @staticmethod
        def get_available_provers() -> list[str]:
            return ["symbolicai"]

        @staticmethod
        def route(*_args, **_kwargs):
            return _FakeRouteResult()

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _FakeRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-external-only",
        citation="External Prover Bridge External Only",
    )

    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.compiles is True
    assert "external_provers:symbolicai" in report.proof_gate.verified_by


def test_multiview_bridge_evaluation_builds_canonical_legal_ir_document() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        "The agency shall publish notice before the permit takes effect.",
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="multiview-bridge-smoke",
        citation="MultiView Bridge Smoke",
    )

    assert report.attempted_count == 2
    assert report.document.version == "legal-ir-multiview-v1"
    assert report.document.has_frame_logic is True
    assert "deontic_norms.deontic_ir" in report.document.views
    assert "deontic_norms.deontic_prover_syntax" in report.document.views
    assert "deontic_norms.deontic_decoder_reconstructions" in report.document.views
    assert "deontic_norms.deontic_ir_slot_provenance" in report.document.views
    assert "deontic_norms.deontic_graph" in report.document.views
    assert "fol_tdfol.tdfol_formula" in report.document.views
    assert "fol_tdfol.proof_obligations" in report.document.views
    assert report.document.metadata["view_count"] == report.view_count
    assert report.failures == {}
    assert report.accepted_count == 2
    assert report.acceptance_rate == 1.0
    assert report.total_loss > 0.0
    assert report.view_coverage_loss() == 0.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0
    assert report.canonical_loss_vector()["legal_ir_multiview_total_loss"] == report.total_loss
    assert report.canonical_loss_vector()["legal_ir_multiview_view_coverage_loss"] == 0.0
    assert report.reports["deontic_norms"].metadata["coverage_requires_validation"] is True
    assert report.reports["deontic_norms"].accepted is True
    assert report.loss_vector()[
        "deontic_norms.deontic_quality_requires_validation_loss"
    ] == 1.0
    assert "deontic_norms.deontic_decoder_slot_loss" in report.loss_vector()
    assert "deontic_norms.deontic_ir_slot_provenance_loss" in report.loss_vector()
    target = report.training_target()
    assert target.document is report.document
    assert target.losses["legal_ir_multiview_total_loss"] == report.total_loss
    assert target.adapter_losses["deontic_norms"][
        "deontic_quality_requires_validation_loss"
    ] == 1.0
    assert target.view_distribution


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
