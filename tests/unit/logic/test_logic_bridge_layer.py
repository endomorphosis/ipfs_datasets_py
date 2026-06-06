from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


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
        "zkp_attestation",
    } <= names
    assert manifest["implemented_bridges"] == [
        "modal_frame_logic",
        "deontic_norms",
        "fol_tdfol",
        "cec_dcec",
        "external_prover_router",
        "zkp_attestation",
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
    assert bridge_name_for_component("zkp.circuits") == "zkp_attestation"


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
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]
    assert any(
        triple["predicate"] == "audited_ontology_term"
        for triple in frame_triples
    )
    assert any(
        triple["predicate"] == "audited_high_signal_ontology_term"
        for triple in frame_triples
    )
    assert (
        report.ir_document.views["modal_ir"].payload["modal_ir"]["metadata"][
            "frame_ontology_term_audit_count"
        ]
        > 0
    )
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.node_count > 0
    assert report.graph_projection.relationship_count > 0
    assert "ontology_term" in report.graph_projection.metadata[
        "frame_logic_projection_views"
    ]
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.compiles is True
    assert report.round_trip.cross_entropy_loss >= 0.0
    assert "cosine_similarity" in report.round_trip.to_dict()
    assert report.total_loss >= 0.0
    assert report.to_dict()["ir_document"]["has_frame_logic"] is True


def test_modal_frame_logic_bridge_projects_flogic_repair_guidance_to_ontology_terms() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="bridge-layer-guided-flogic",
        citation="Bridge Layer Guided FLogic",
        compiler_guidance={
            "feature_groups": {
                "frame_logic": [
                    "legal-ir-view:modal.frame_logic",
                    "flogic:statement_hint:modal-synthesis",
                ],
            },
            "legal_ir_target_view_distribution": {"modal.frame_logic": 1.0},
            "ranked_guidance_features": [
                {"feature": "legal-ir-view:modal.frame_logic", "score": 1.0},
            ],
            "synthesis_focus": ["repair_flogic_ontology_constraints"],
        },
        evaluate_provers=False,
    )

    modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"]["metadata"]
    audit_terms = set(modal_metadata["frame_ontology_term_audit_terms"])
    high_signal_terms = set(
        modal_metadata["frame_ontology_high_signal_term_audit_terms"]
    )
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]

    assert report.metadata["selected_frame"]
    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0
    assert "repair_flogic_ontology_constraints" in audit_terms
    assert "modal_frame_logic" in high_signal_terms
    assert any(
        triple["predicate"] == "audited_ontology_term"
        and triple["object"] == "repair_flogic_ontology_constraints"
        for triple in frame_triples
    )
    assert any(
        triple["predicate"] == "audited_high_signal_ontology_term"
        and triple["object"] == "modal_frame_logic"
        for triple in frame_triples
    )


def test_modal_frame_logic_bridge_bounds_flogic_similarity_loss_for_heading_samples() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "7 U.S.C. 2242b: U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United "
            "States Code, 2024 Edition Title 7 - AGRICULTURE CHAPTER 55 - "
            "DEPARTMENT OF AGRICULTURE Sec. 2242b - Translation of "
            "publications into foreign languages From the U.S. Government "
            "Publishing Office"
        ),
        document_id="bridge-layer-heading-flogic-loss-bound",
        citation="7 U.S.C. 2242b",
        evaluate_provers=False,
    )

    assert report.ir_document.has_frame_logic is True
    assert 0.0 <= report.round_trip.flogic_similarity_score <= 1.0
    assert 0.0 <= report.round_trip.flogic_similarity_loss <= 1.0
    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0


def test_graph_projection_parses_string_boolean_metadata() -> None:
    from ipfs_datasets_py.logic.bridge.types import GraphProjectionResult

    graph_data = SimpleNamespace(
        metadata={"graph_id": "g1", "neo4j_compatible": "false"},
        node_count=4,
        relationship_count=3,
        schema=SimpleNamespace(node_labels=("A",), relationship_types=("R",)),
    )

    result = GraphProjectionResult.from_graph_data(graph_data)

    assert result.neo4j_compatible is False
    assert result.graph_failure_penalty == 1.0


def test_graph_projection_infers_neo4j_shape_when_metadata_flag_missing() -> None:
    from ipfs_datasets_py.logic.bridge.types import GraphProjectionResult

    graph_data = SimpleNamespace(
        metadata={"graph_id": "g1"},
        node_count=2,
        relationship_count=1,
        nodes=(
            SimpleNamespace(id="n1"),
            SimpleNamespace(id="n2"),
        ),
        relationships=(
            SimpleNamespace(type="CITES", start_node="n1", end_node="n2"),
        ),
        schema=SimpleNamespace(node_labels=("LegalNode",), relationship_types=("CITES",)),
    )

    result = GraphProjectionResult.from_graph_data(graph_data)

    assert result.neo4j_compatible is True
    assert result.graph_failure_penalty == 0.0


def test_modal_frame_logic_bridge_projects_repealed_status_as_graph_view() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "7 U.S.C. 2583: U.S.C. Title 7 - AGRICULTURE CHAPTER 57 - "
            "PLANT VARIETY PROTECTION SUBCHAPTER III - PLANT VARIETY PROTECTION "
            "AND RIGHTS Part M - Intent and Severability Sec. 2583 - Repealed."
        ),
        document_id="bridge-layer-repealed-status-graph-view",
        citation="7 U.S.C. 2583",
        evaluate_provers=False,
    )

    graph_view = report.ir_document.views["neo4j_graph_data"]
    view_distribution = graph_view.metadata[
        "frame_logic_projection_view_distribution"
    ]
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.graph_failure_penalty == 0.0
    assert view_distribution["editorial_status"] >= 1
    assert view_distribution["citation_structure"] >= 1
    assert "editorial_status" in graph_view.metadata["frame_logic_projection_views"]


def test_modal_frame_logic_bridge_preserves_selected_frame_without_splitting_view_family() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "26-usc-994",
                "predicate": "selected_ontology_frame",
                "object": "administrative_notice_hearing",
            },
            {
                "subject": "26-usc-994",
                "predicate": "candidate_ontology_frame",
                "object": "administrative_notice_hearing",
            },
            {
                "subject": "26-usc-994",
                "predicate": "selected_ontology_term",
                "object": "notice",
            },
        ],
        graph_id="administrative-notice-hearing-projection",
    )

    view_distribution = graph_data.metadata["frame_logic_projection_view_distribution"]
    assert graph_data.metadata["frame_logic_selected_frame"] == (
        "administrative_notice_hearing"
    )
    assert view_distribution["frame_link"] == 2
    assert "frame_link" in graph_data.metadata["frame_logic_projection_views"]
    assert "administrative_notice_hearing" not in graph_data.metadata[
        "frame_logic_projection_views"
    ]
    assert any(
        relationship.properties["frame_logic_projection_view"] == "frame_link"
        for relationship in graph_data.relationships
    )


def test_modal_frame_logic_bridge_projects_us_code_source_id_components_to_legal_views() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-28-1655",
                "predicate": "source_id",
                "object": "us-code-28-1655",
            },
            {
                "subject": "us-code-28-1655",
                "predicate": "source_id_title",
                "object": "28",
            },
            {
                "subject": "us-code-28-1655",
                "predicate": "source_id_citation_canonical",
                "object": "28 U.S.C. 1655",
            },
            {
                "subject": "us-code-28-1655",
                "predicate": "source_id_section_normalized",
                "object": "1655",
            },
            {
                "subject": "us-code-28-1655",
                "predicate": "citation_section_component_profile",
                "object": "numeric",
            },
            {
                "subject": "us-code-28-1655",
                "predicate": "citation_source_id_section_profile_match",
                "object": "true",
            },
        ],
        graph_id="us-code-28-1655:flogic",
    )

    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }

    assert view_by_predicate["source_id"] == "document_scope"
    assert view_by_predicate["source_id_title"] == "citation_structure"
    assert view_by_predicate["source_id_citation_canonical"] == "citation_structure"
    assert view_by_predicate["source_id_section_normalized"] == "section_structure"
    assert view_by_predicate["citation_section_component_profile"] == "section_structure"
    assert (
        view_by_predicate["citation_source_id_section_profile_match"]
        == "section_structure"
    )
    assert graph_data.metadata["frame_logic_projection_view_distribution"] == {
        "citation_structure": 2,
        "document_scope": 1,
        "section_structure": 3,
    }
    assert graph_data.metadata["frame_logic_projection_legal_view_required"] == [
        "citation_structure",
        "document_scope",
        "section_structure",
    ]
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True


def test_modal_frame_logic_bridge_projects_heading_and_learned_views() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-10-2350e",
                "predicate": "source_id",
                "object": "us-code-10-2350e-b6911045de25d2e1",
            },
            {
                "subject": "us-code-10-2350e",
                "predicate": "source_id_citation_canonical",
                "object": "10 U.S.C. 2350e",
            },
            {
                "subject": "us-code-10-2350e",
                "predicate": "source_id_section_normalized",
                "object": "2350e",
            },
            {
                "subject": "us-code-10-2350e",
                "predicate": "section_heading_tail",
                "object": (
                    "NATO Airborne Warning and Control System program: "
                    "authority of Secretary of Defense"
                ),
            },
            {
                "subject": "us-code-10-2350e",
                "predicate": "condition_scope_token",
                "object": "authority",
            },
            {
                "subject": "us-code-10-2350e",
                "predicate": "learned_legal_ir_target_view",
                "object": "knowledge_graphs.neo4j_compat",
            },
        ],
        graph_id="us-code-10-2350e:flogic",
    )

    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }

    assert view_by_predicate["section_heading_tail"] == "section_structure"
    assert view_by_predicate["condition_scope_token"] == "modal_semantics"
    assert (
        view_by_predicate["learned_legal_ir_target_view"]
        == "legal_ir_view_alignment"
    )
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True


def test_modal_frame_logic_bridge_projects_graph_lane_alignment_metadata() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "43 U.S.C. 1312: U.S.C. Title 43 - PUBLIC LANDS CHAPTER 29 - "
            "SUBMERGED LANDS Sec. 1312. Seaward boundaries of States. The "
            "seaward boundary of each original coastal State is approved and "
            "confirmed as a line three geographical miles distant from its "
            "coast line."
        ),
        document_id="bridge-layer-us-code-graph-lane-alignment",
        citation="43 U.S.C. 1312",
        evaluate_provers=False,
    )

    graph_view = report.ir_document.views["neo4j_graph_data"]
    canonical_distribution = graph_view.metadata[
        "canonical_legal_ir_projection_view_distribution"
    ]

    assert report.graph_projection.graph_failure_penalty == 0.0
    assert graph_view.source_component == "knowledge_graphs.neo4j_compat"
    assert graph_view.metadata["frame_logic_to_neo4j_component_pair"] == (
        "modal.frame_logic->knowledge_graphs.neo4j_compat"
    )
    assert graph_view.metadata["frame_logic_to_neo4j_alignment_total"] == (
        graph_view.metadata["relationship_count"]
    )
    assert set(canonical_distribution) == {
        "knowledge_graphs.neo4j_compat",
        "modal.frame_logic",
    }
    assert canonical_distribution["knowledge_graphs.neo4j_compat"] > 0.0
    assert canonical_distribution["modal.frame_logic"] > 0.0


def test_modal_frame_logic_bridge_scales_sparse_citation_loss() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        "16 U.S.C. 973k",
        document_id="bridge-layer-citation-only",
        citation="16 U.S.C. 973k",
    )

    assert report.status == "ok"
    assert report.accepted is True
    assert report.total_loss < 2.0
    assert report.metadata["sparse_citation_loss_calibrated"] is True
    assert report.metadata["sparse_citation_loss_scale"] < 1.0


def test_modal_frame_logic_bridge_scales_us_code_scaffold_loss() -> None:
    from ipfs_datasets_py.logic.bridge.modal_frame_logic import (
        _calibrate_round_trip_for_statutory_scaffold,
    )
    from ipfs_datasets_py.logic.bridge.types import RoundTripMetrics

    round_trip = RoundTripMetrics(
        cosine_similarity=0.2,
        cosine_loss=0.8,
        cross_entropy_loss=2.0,
        reconstruction_loss=1.0,
        text_reconstruction_loss=0.5,
        extra_losses={"cross_entropy_excess_loss": 1.5},
    )

    calibrated, did_calibrate = _calibrate_round_trip_for_statutory_scaffold(
        round_trip,
        citation="28 U.S.C. 1655",
        text=(
            "U.S.C. Title 28 - JUDICIARY AND JUDICIAL PROCEDURE 28 U.S.C. "
            "United States Code, 2024 Edition Title 28 - JUDICIARY AND "
            "JUDICIAL PROCEDURE PART V - PROCEDURE CHAPTER 111 - GENERAL "
            "PROVISIONS Sec. 1655 - Lien enforcement; absent defendants "
            "From the U.S. Government Publishing Office. In an action in a "
            "district court to enforce any lien upon or claim to property, "
            "the court may order the absent defendant to appear or plead by "
            "a day certain. Pub. L. 85-699, title III, section 361."
        ),
    )

    assert did_calibrate is True
    assert calibrated.cross_entropy_loss < round_trip.cross_entropy_loss
    assert calibrated.reconstruction_loss < round_trip.reconstruction_loss
    assert calibrated.extra_losses["cross_entropy_excess_loss"] < 1.5


def test_modal_frame_logic_bridge_does_not_scale_short_statutory_sentence() -> None:
    from ipfs_datasets_py.logic.bridge.modal_frame_logic import (
        _calibrate_round_trip_for_statutory_scaffold,
    )
    from ipfs_datasets_py.logic.bridge.types import RoundTripMetrics

    round_trip = RoundTripMetrics(cross_entropy_loss=2.0)

    calibrated, did_calibrate = _calibrate_round_trip_for_statutory_scaffold(
        round_trip,
        citation="5 U.S.C. 552",
        text="The agency shall publish notice before the permit takes effect.",
    )

    assert did_calibrate is False
    assert calibrated is round_trip


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


def test_deontic_bridge_phase8_quality_gate_uses_present_optional_slots_only() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        "The Director shall issue a permit after notice and hearing.",
        document_id="deontic-bridge-phase8-slot-scope",
        citation="Deontic Bridge Phase8 Slot Scope",
    )

    phase8_records = report.ir_document.views["deontic_phase8_quality"].payload["records"]
    assert len(phase8_records) >= 1
    first = phase8_records[0]
    assert first["phase8_quality_complete"] is True
    assert first["requires_validation"] is False
    assert "missing_reconstruction_slot:exceptions" not in first["coverage_blockers"]
    assert "missing_reconstruction_slot:cross_references" not in first["coverage_blockers"]
    assert "missing_ir_slot_provenance:exceptions" not in first["coverage_blockers"]
    assert "missing_ir_slot_provenance:cross_references" not in first["coverage_blockers"]
    assert report.round_trip.extra_losses["deontic_phase8_quality_incomplete_loss"] == 0.0


def test_deontic_bridge_decoder_slot_loss_uses_present_optional_slots_only() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        "The electors shall vote for President and Vice President, respectively, in the manner directed by the Constitution.",
        document_id="deontic-bridge-decoder-slot-scope",
        citation="Deontic Bridge Decoder Slot Scope",
    )

    summary = report.ir_document.views["deontic_reconstruction_slot_loss"].payload["summary"]
    assert summary["required_slots"] == ["actor", "modality", "action"]
    assert summary["missing_required_slots"] == []
    assert summary["slot_reconstruction_complete"] is True
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0


def test_deontic_bridge_recovers_core_slots_from_nested_prompt_context() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Commission shall conduct security evaluations at each licensed facility."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:nested-prompt-context",
                "canonical_citation": "42 U.S.C. 2210d",
                "norm_type": "obligation",
                "deontic_operator": "",
                "subject": [],
                "action": [],
                "text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "llm_repair": {
                    "prompt_context": {
                        "deontic_operator": "shall",
                        "subject": ["Commission"],
                        "action_text": "conduct security evaluations",
                        "text": source_text,
                        "support_text": source_text,
                        "support_span": [0, len(source_text)],
                        "field_spans": {
                            "subject": [4, 14],
                            "modality": [15, 20],
                            "action": [21, 49],
                        },
                    }
                },
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-nested-prompt-context",
        citation="Deontic Bridge Nested Prompt Context",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    summary = report.ir_document.views["deontic_reconstruction_slot_loss"].payload["summary"]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload["records"][0]

    assert norm["actor"] == "Commission"
    assert norm["action"] == "conduct security evaluations"
    assert summary["missing_required_slots"] == []
    assert summary["slot_reconstruction_complete"] is True
    assert phase8_record["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_treats_reconstruction_neutral_warning_bundle_as_quality_complete() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    long_source = (
        "Section heading and codification notes. "
        "Historical amendments and editorial notes. "
        "The Secretary shall publish notice. "
        "Additional historical notes and statutory metadata for codification context. "
        "Further editorial material and unrelated publication notes."
    )

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:warning-bundle",
                "canonical_citation": "42 U.S.C. 2000dd-1",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": long_source,
                "source_text": long_source,
                "support_text": "The Secretary shall publish notice.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": False,
                "parser_warnings": [
                    "enumerated_clause_requires_item_level_review",
                    "cross_reference_requires_resolution",
                    "overlong_action_span",
                ],
                "export_readiness": {
                    "blockers": [
                        "enumerated_clause_requires_item_level_review",
                        "cross_reference_requires_resolution",
                        "overlong_action_span",
                        "llm_repair_required",
                    ]
                },
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall publish notice.",
        document_id="deontic-bridge-reconstruction-warning-bundle",
        citation="Deontic Bridge Reconstruction Warning Bundle",
    )

    decoder_record = report.ir_document.views["deontic_decoder_reconstructions"].payload["records"][0]
    assert decoder_record["requires_validation"] is False

    formula_record = report.ir_document.views["deontic_formula_records"].payload["records"][0]
    assert formula_record["proof_ready"] is True
    assert formula_record["requires_validation"] is False
    assert formula_record["deterministic_resolution"]["type"] == (
        "source_grounded_reconstruction_warning_bundle"
    )

    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload["records"][0]
    assert phase8_record["phase8_quality_complete"] is True
    assert phase8_record["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_phase8_quality_includes_coverage_only_source_records() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall publish notice."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:phase8-main",
                "canonical_citation": "42 U.S.C. 2000dd-1",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": source_text,
                "source_text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "norm_type": "obligation",
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:phase8-main",
                    "requires_validation": False,
                    "coverage_blockers": [],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "target_status_by_target": {"fol": "passed"},
                        "quality_gate_summary": {},
                        "target_role_matrix_summary": {},
                    },
                },
                {
                    "source_id": "legacy:deontic:coverage-only",
                    "requires_validation": True,
                    "coverage_blockers": ["failed_prover_syntax_target:fol"],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "target_status_by_target": {"fol": "failed"},
                        "quality_gate_summary": {},
                        "target_role_matrix_summary": {},
                        "requires_validation": True,
                    },
                },
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-phase8-coverage-only-source",
        citation="Deontic Bridge Phase8 Coverage Only Source",
    )

    phase8_records = report.ir_document.views["deontic_phase8_quality"].payload["records"]
    coverage_only = next(
        row for row in phase8_records if row.get("source_id") == "legacy:deontic:coverage-only"
    )
    assert coverage_only["requires_validation"] is True
    assert coverage_only["phase8_quality_complete"] is False
    assert "failed_prover_syntax_target:fol" in coverage_only["coverage_blockers"]
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] > 0.0


def test_deontic_bridge_promotes_quality_validated_coverage_records() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall publish notice."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:quality-promoted",
                "canonical_citation": "42 U.S.C. 2000dd-1",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": source_text,
                "source_text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "norm_type": "obligation",
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:quality-promoted",
                    "requires_validation": True,
                    "coverage_blockers": [],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "passed_targets": ["fol"],
                        "failed_targets": [],
                        "missing_targets": [],
                        "target_status_by_target": {"fol": "passed"},
                        "all_required_passed": True,
                        "requires_validation": True,
                        "quality_gate_summary": {
                            "quality_gate_record_count": 1,
                            "quality_gate_all_targets_complete": True,
                            "failed_quality_check_count": 0,
                            "failed_quality_check_distribution": {},
                        },
                        "target_role_matrix_summary": {
                            "target_role_matrix_complete": True,
                            "target_role_matrix_requires_validation": False,
                            "target_role_matrix_blockers": [],
                        },
                    },
                },
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-quality-promoted",
        citation="Deontic Bridge Quality Promoted",
    )

    coverage_view = report.ir_document.views["deontic_prover_syntax"]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]

    assert coverage_view.metadata["coverage_requires_validation_count"] == 0
    assert phase8_record["requires_validation"] is False
    assert phase8_record["phase8_quality_complete"] is True
    assert report.metadata["coverage_requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_quality_gate_clears_stale_proof_repair_rows() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall publish notice."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:stale-proof-repair",
                "canonical_citation": "42 U.S.C. 2000dd-1",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": source_text,
                "source_text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "norm_type": "obligation",
                "promotable_to_theorem": False,
                "export_readiness": {
                    "blockers": ["legacy_quality_gate_requires_validation"]
                },
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:stale-proof-repair",
                    "requires_validation": True,
                    "coverage_blockers": [],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "passed_targets": ["fol"],
                        "failed_targets": [],
                        "missing_targets": [],
                        "target_status_by_target": {"fol": "passed"},
                        "all_required_passed": True,
                        "requires_validation": True,
                        "quality_gate_summary": {
                            "quality_gate_record_count": 1,
                            "quality_gate_all_targets_complete": True,
                            "failed_quality_check_count": 0,
                            "failed_quality_check_distribution": {},
                        },
                        "target_role_matrix_summary": {
                            "target_role_matrix_complete": True,
                            "target_role_matrix_requires_validation": False,
                            "target_role_matrix_blockers": [],
                        },
                    },
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-stale-proof-repair",
        citation="Deontic Bridge Stale Proof Repair",
    )

    proof_record = report.ir_document.views["deontic_proof_obligations"].payload[
        "records"
    ][0]

    assert proof_record["requires_validation"] is False
    assert proof_record["repair_required"] is False
    assert proof_record["validated_by_phase8_quality_gate"] is True
    assert report.ir_document.views["deontic_repair_queue"].metadata[
        "repair_record_count"
    ] == 0
    assert report.round_trip.extra_losses["deontic_repair_queue_rate"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_promotes_nested_prover_syntax_records_to_validated_coverage() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_id = "legal-norm-ir:nested-prover-syntax"
    target_profiles = {
        "frame_logic": ("frame_record", "frame_logic"),
        "deontic_cec": ("event_calculus_state", "event_calculus"),
        "fol": ("first_order_formula", "first_order"),
        "deontic_fol": ("deontic_first_order_formula", "deontic_first_order"),
        "deontic_temporal_fol": (
            "temporal_deontic_first_order_formula",
            "deontic_temporal_first_order",
        ),
    }

    class _FakeResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "schema_version": "legal_norm_ir-v1",
                    "source_id": source_id,
                    "canonical_citation": "6 U.S.C. 469",
                    "deontic_operator": "shall",
                    "subject": ["Secretary"],
                    "action": ["publish notice"],
                    "text": "The Secretary shall publish notice.",
                    "support_text": "The Secretary shall publish notice.",
                    "support_span": [0, 35],
                    "norm_type": "obligation",
                    "promotable_to_theorem": True,
                    "export_readiness": {"blockers": []},
                    "field_spans": {
                        "subject": [4, 13],
                        "modality": [14, 19],
                        "action": [20, 34],
                    },
                    "prover_syntax_records": [
                        {
                            "target": target,
                            "syntax_valid": True,
                            "exported_formula": f"{target}(secretary,publish_notice)",
                            "target_components": {
                                "formula_role": role,
                                "dialect_family": dialect,
                                "semantic_formula_family": "notice_duty",
                            },
                            "target_quality_gate": {
                                "formal_validation_complete": True,
                                "failed_quality_checks": [],
                            },
                        }
                        for target, (role, dialect) in target_profiles.items()
                    ],
                }
            ]
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall publish notice.",
        document_id="deontic-bridge-nested-prover-syntax",
        citation="Deontic Bridge Nested Prover Syntax",
    )

    coverage_record = report.ir_document.views["deontic_prover_syntax"].payload[
        "records"
    ][0]
    semantic_summary = coverage_record["coverage_summary"]["semantic_family_summary"]

    assert coverage_record["requires_validation"] is False
    assert coverage_record["target_role_matrix_complete"] is True
    assert semantic_summary["semantic_formula_family_distribution"] == {
        "notice_duty": 5
    }
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_treats_definition_warning_bundle_as_quality_complete() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    support_text = (
        'the term "Hispanic-serving institution" has the meaning given the term '
        "in section 1101a of this title"
    )

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:definition-warning-bundle",
                "canonical_citation": "20 U.S.C. 1131-1(c)(1)",
                "norm_type": "definition",
                "subject": ["Hispanic-serving institution"],
                "action": [support_text],
                "defined_term": "Hispanic-serving institution",
                "text": support_text,
                "source_text": support_text,
                "support_text": support_text,
                "support_span": [0, len(support_text)],
                "promotable_to_theorem": False,
                "parser_warnings": [
                    "enumerated_clause_requires_item_level_review",
                    "cross_reference_requires_resolution",
                    "overlong_action_span",
                ],
                "export_readiness": {
                    "blockers": [
                        "enumerated_clause_requires_item_level_review",
                        "cross_reference_requires_resolution",
                        "overlong_action_span",
                        "llm_repair_required",
                    ]
                },
                "field_spans": {
                    "subject": [10, 39],
                    "action": [0, len(support_text)],
                },
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        support_text,
        document_id="deontic-bridge-definition-warning-bundle",
        citation="Deontic Bridge Definition Warning Bundle",
    )

    formula_record = report.ir_document.views["deontic_formula_records"].payload["records"][0]
    assert formula_record["proof_ready"] is True
    assert formula_record["requires_validation"] is False
    assert formula_record["deterministic_resolution"]["type"] == (
        "source_grounded_reconstruction_warning_bundle"
    )

    coverage_record = report.ir_document.views["deontic_prover_syntax"].payload["records"][0]
    assert coverage_record["requires_validation"] is False
    assert "failed_prover_quality_check:formula_proof_ready" not in coverage_record["coverage_blockers"]
    assert "failed_prover_quality_check:formula_requires_validation" not in coverage_record["coverage_blockers"]

    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload["records"][0]
    assert phase8_record["phase8_quality_complete"] is True
    assert phase8_record["requires_validation"] is False


def test_deontic_bridge_reconstruction_tokens_allow_cross_reference_provenance_only_text() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    support_text = "The Institute shall receive funding under this subchapter."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:crossref-provenance",
                "canonical_citation": "20 U.S.C. 1131-1(a)",
                "deontic_operator": "shall",
                "norm_type": "obligation",
                "subject": ["Institute"],
                "action": ["receive funding"],
                "text": support_text,
                "source_text": support_text,
                "support_text": support_text,
                "support_span": [0, len(support_text)],
                "promotable_to_theorem": False,
                "parser_warnings": [
                    "cross_reference_requires_resolution",
                    "overlong_action_span",
                ],
                "export_readiness": {
                    "blockers": [
                        "cross_reference_requires_resolution",
                        "overlong_action_span",
                        "llm_repair_required",
                    ]
                },
                "cross_reference_details": [
                    {
                        "value": "under this subchapter",
                        "span": [35, 56],
                    }
                ],
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 35],
                },
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        support_text,
        document_id="deontic-bridge-crossref-provenance",
        citation="Deontic Bridge Cross-Reference Provenance",
    )

    coverage_record = report.ir_document.views["deontic_prover_syntax"].payload["records"][0]
    assert coverage_record["requires_validation"] is False
    assert "failed_prover_quality_check:reconstruction_tokens" not in coverage_record["coverage_blockers"]

    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload["records"][0]
    assert phase8_record["phase8_quality_complete"] is True
    assert phase8_record["requires_validation"] is False


def test_deontic_bridge_soft_accepts_non_normative_statutory_text() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        "Congress finds that unfair methods of competition burden commerce.",
        document_id="deontic-bridge-non-normative",
        citation="15 U.S.C. 1431",
    )

    assert report.ir_document.views["deontic_ir"].metadata["norm_count"] == 0
    assert report.proof_gate.compiles is True
    assert report.proof_gate.details[0]["reason"] == "no_deontic_coverage_records"
    assert report.round_trip.cosine_similarity == 1.0
    assert report.round_trip.reconstruction_loss == 0.0
    assert report.round_trip.symbolic_validity_penalty == 0.0
    assert report.status == "ok"
    assert report.accepted is True


def test_deontic_bridge_recovers_coverage_from_single_parser_element_metadata() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:1",
                "canonical_citation": "25 U.S.C. 640d-28",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": "The Secretary shall submit report.",
                "support_text": "The Secretary shall submit report.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="deontic-bridge-legacy-fallback",
        citation="Deontic Bridge Legacy Fallback",
    )

    assert report.ir_document.views["deontic_ir"].metadata["norm_count"] == 1
    assert report.ir_document.views["deontic_prover_syntax"].metadata[
        "coverage_record_count"
    ] >= 1
    assert report.proof_gate.attempted_count >= 5
    assert report.proof_gate.valid_count >= 5
    assert report.proof_gate.compiles is True


def test_deontic_bridge_rehydrates_legacy_coverage_rows_without_summary() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:min-coverage",
                "canonical_citation": "16 U.S.C. 452a",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": "The Secretary shall submit report.",
                "support_text": "The Secretary shall submit report.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:min-coverage",
                    "target_logic": "local_prover_syntax",
                    "required_targets": [
                        "frame_logic",
                        "deontic_cec",
                        "fol",
                        "deontic_fol",
                        "deontic_temporal_fol",
                    ],
                    "present_required_target_count": 5,
                    "record_count": 5,
                    "syntax_valid_rate": 1.0,
                    "formal_syntax_valid": True,
                    "requires_validation": False,
                    "coverage_blockers": [],
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="deontic-bridge-legacy-coverage-summary",
        citation="Deontic Bridge Legacy Coverage Summary",
    )

    assert report.ir_document.views["deontic_prover_syntax"].metadata[
        "coverage_record_count"
    ] >= 1
    coverage_records = report.ir_document.views["deontic_prover_syntax"].payload["records"]
    assert isinstance(coverage_records[0].get("coverage_summary"), dict)
    assert report.proof_gate.attempted_count >= 5
    assert report.proof_gate.valid_count >= 5
    assert report.proof_gate.compiles is True


def test_deontic_bridge_rehydrates_legacy_coverage_status_map_without_target_lists() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:status-map",
                "canonical_citation": "15 U.S.C. 1431",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": "The Secretary shall submit report.",
                "support_text": "The Secretary shall submit report.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:status-map",
                    "target_logic": "local_prover_syntax",
                    "coverage_summary": {
                        "required_targets": [
                            "frame_logic",
                            "deontic_cec",
                            "fol",
                            "deontic_fol",
                            "deontic_temporal_fol",
                        ],
                        "target_status_by_target": {
                            "frame_logic": "passed",
                            "deontic_cec": "passed",
                            "fol": "passed",
                            "deontic_fol": "passed",
                            "deontic_temporal_fol": "passed",
                        },
                        "syntax_valid_rate": 1.0,
                    },
                    "coverage_blockers": [],
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="deontic-bridge-legacy-coverage-status-map",
        citation="Deontic Bridge Legacy Coverage Status Map",
    )

    assert report.ir_document.views["deontic_prover_syntax"].metadata[
        "coverage_record_count"
    ] >= 1
    assert report.proof_gate.attempted_count >= 5
    assert report.proof_gate.valid_count >= 5
    assert report.proof_gate.compiles is True


def test_deontic_bridge_legacy_string_false_requires_validation_does_not_trip_gate() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:string-false",
                "canonical_citation": "15 U.S.C. 1431",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": "The Secretary shall submit report.",
                "support_text": "The Secretary shall submit report.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:string-false",
                    "requires_validation": "false",
                    "coverage_blockers": [],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "target_status_by_target": {"fol": "passed"},
                        "quality_gate_summary": {},
                        "target_role_matrix_summary": {},
                        "requires_validation": "false",
                    },
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="deontic-bridge-legacy-string-false",
        citation="Deontic Bridge Legacy String False",
    )

    assert report.ir_document.views["deontic_prover_syntax"].metadata[
        "coverage_requires_validation_count"
    ] == 0
    phase8_records = report.ir_document.views["deontic_phase8_quality"].payload["records"]
    assert phase8_records[0]["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_promotes_legacy_passed_coverage_without_quality_summary() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall submit report."

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:passed-no-quality-summary",
                "canonical_citation": "15 U.S.C. 1431",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_prover_syntax_target_coverage_records": [
                {
                    "source_id": "legacy:deontic:passed-no-quality-summary",
                    "requires_validation": True,
                    "coverage_blockers": [],
                    "coverage_summary": {
                        "required_targets": ["fol"],
                        "target_status_by_target": {"fol": "passed"},
                        "all_required_passed": True,
                        "requires_validation": True,
                    },
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-legacy-passed-no-quality-summary",
        citation="Deontic Bridge Legacy Passed No Quality Summary",
    )

    assert report.ir_document.views["deontic_prover_syntax"].metadata[
        "coverage_requires_validation_count"
    ] == 0
    phase8_records = report.ir_document.views["deontic_phase8_quality"].payload["records"]
    assert phase8_records[0]["requires_validation"] is False
    assert phase8_records[0]["phase8_quality_complete"] is True
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


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


def test_tdfol_bridge_synthesizes_formula_when_converter_yields_no_norms() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _EmptyResult:
        success = True
        metadata = {
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _EmptyConverter:
        @staticmethod
        def convert(_text: str):
            return _EmptyResult()

    adapter = FolTdfolBridgeAdapter(converter=_EmptyConverter())
    report = adapter.evaluate(
        "There is established in the Treasury a fund known as the conservation fund.",
        document_id="tdfol-bridge-fallback",
        citation="16 U.S.C. 452a",
    )

    formula_view = report.ir_document.views["tdfol_formula"]
    obligation_view = report.ir_document.views["proof_obligations"]
    records = formula_view.payload["records"]

    assert formula_view.metadata["formula_count"] == 1
    assert obligation_view.metadata["obligation_count"] == 1
    assert records[0]["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_no_formula_loss"] == 0.0
    assert report.proof_gate.attempted_count == 1
    assert report.proof_gate.valid_count == 1


def test_tdfol_bridge_builds_formula_for_non_normative_statutory_text() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("fol_tdfol")
    report = adapter.evaluate(
        "There is established in the Treasury a fund known as the conservation fund.",
        document_id="tdfol-bridge-non-normative",
        citation="16 U.S.C. 452a",
    )

    assert report.ir_document.views["tdfol_formula"].metadata["formula_count"] >= 1
    assert report.ir_document.views["proof_obligations"].metadata["obligation_count"] >= 1
    assert report.round_trip.extra_losses["tdfol_no_formula_loss"] == 0.0
    assert report.proof_gate.valid_count >= 1


def test_tdfol_bridge_coerce_handles_core_prefix_binary_round_trip() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        BinaryFormula,
        Constant,
        DeonticFormula,
        DeonticOperator,
        LogicOperator,
        Predicate,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    left = Predicate("publish_notice", (Constant("agency"),))
    right = Predicate("issue_permit", (Constant("agency"),))
    implication = BinaryFormula(LogicOperator.IMPLIES, left, right)
    formula = DeonticFormula(DeonticOperator.OBLIGATION, implication)

    text = formula.to_string()
    coerced = coerce_tdfol_formula(text)

    assert coerced is not None
    assert coerced.to_string() == text


def test_tdfol_bridge_coerce_handles_proof_obligation_payload_mapping() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    payload = {
        "formula": "F(disclose_records(agency))",
        "source_id": "tdfol:norm:test",
        "target_logic": "TDFOL",
    }

    coerced = coerce_tdfol_formula(payload)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.PROHIBITION
    assert coerced.to_string() == payload["formula"]


def test_tdfol_bridge_coerce_handles_nested_proof_obligation_payload_view() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    payload = {
        "obligations": [
            {
                "formula": "O(disclose_records(agency))",
                "source_id": "tdfol:norm:test",
                "target_logic": "TDFOL",
            }
        ]
    }

    coerced = coerce_tdfol_formula(payload)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == payload["obligations"][0]["formula"]


def test_tdfol_bridge_coerce_parses_textual_logical_connectives() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import QuantifiedFormula
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = (
        "forall t. (activation_clause(nrm_1) and true and not (false))"
        " -> O_t(Act_deadbeef(actor, t))."
    )

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, QuantifiedFormula)
    assert "activation_clause" in coerced.get_predicates()
    assert "O_t" in coerced.get_predicates()


def test_tdfol_bridge_coerce_parses_legacy_proof_obligation_formula() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import QuantifiedFormula
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "forall t (true and By(t,2026-03-20) and not(false) -> O(frm:1,t))"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, QuantifiedFormula)
    assert "By" in coerced.get_predicates()
    assert "legacy_deontic_target" in coerced.get_predicates()


def test_tdfol_bridge_coerce_parses_legal_id_proof_obligation_formula() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import QuantifiedFormula
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "forall t (true and By(t,2026-03-20) -> O(frm:10-2851a,t))"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, QuantifiedFormula)
    assert "By" in coerced.get_predicates()
    assert "legacy_deontic_target" in coerced.get_predicates()


def test_tdfol_bridge_coerce_normalizes_bracketed_deontic_export_formula() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "F[disclose_records(agency)]"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.PROHIBITION
    assert coerced.to_string() == "F(disclose_records(agency))"


def test_tdfol_bridge_coerce_parses_prefixed_formula_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "formula: O(disclose_records(agency))."

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(disclose_records(agency))"


def test_tdfol_bridge_coerce_parses_prefixed_proof_obligation_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    coerced = coerce_tdfol_formula("proof obligation: O(disclose_records(agency))")

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(disclose_records(agency))"


def test_tdfol_bridge_canonicalizes_prefixed_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "formula": "proof obligation: O(disclose_records(agency))",
                    "source_id": "tdfol:guidance:test",
                }
            ],
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _ProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _ProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_ProofObligationConverter())

    report = adapter.evaluate("The agency shall disclose records.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["formula"] == "O(disclose_records(agency))"
    assert record["proof_input"] == "O(disclose_records(agency))"
    assert record["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_recovers_deontic_operator_from_norm_text() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "action": "may not issue stock",
                    "actor": "corporation",
                    "modality": "obligation",
                    "source_id": "tdfol:norm:prohibition",
                    "source_text": "The corporation may not issue stock.",
                },
                {
                    "action": "may establish mechanisms",
                    "actor": "secretary",
                    "modality": "obligation",
                    "source_id": "tdfol:norm:permission",
                    "source_text": "The Secretary may establish mechanisms.",
                },
            ],
            "parser_elements": [],
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    adapter = FolTdfolBridgeAdapter(converter=_NormConverter())

    report = adapter.evaluate("stub")
    formulas = [
        record["formula"]
        for record in report.ir_document.views["tdfol_formula"].payload["records"]
    ]

    assert formulas[0].startswith("F(")
    assert formulas[1].startswith("P(")
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_applies_compiler_guidance_conditioned_temporal_rule() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _GuidanceResult:
        success = True
        metadata = {"legal_norm_irs": [], "parser_elements": []}

    class _GuidanceConverter:
        @staticmethod
        def convert(_text: str):
            return _GuidanceResult()

    guidance = {
        "compiler_guidance_todo_routes": {"repair_tdfol_bridge_parse": 1},
        "compiler_guidance_semantic_overlay_terms": {
            "if": 3,
            "when": 2,
            "not": 3,
            "shall": 3,
        },
        "compiler_guidance_surface_features": {
            "decompiler-surface:force-polarity-template:obligation:negative_scope:conditioned+temporal": 3,
            "decompiler-surface:slot-order:condition>subject>force>polarity>action>object>temporal": 2,
        },
    }
    adapter = FolTdfolBridgeAdapter(converter=_GuidanceConverter())

    report = adapter.evaluate(
        "When notice is deficient, the agency shall not publish the rule.",
        compiler_guidance=guidance,
    )
    records = report.ir_document.views["tdfol_formula"].payload["records"]
    guidance_record = records[0]

    assert guidance_record["source_id"] == "tdfol:compiler_guidance:repair_tdfol_bridge_parse"
    assert guidance_record["parse_ok"] is True
    assert guidance_record["formula"].startswith("□((→")
    assert "O(¬" in guidance_record["formula"]
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


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
    assert report.ir_document.views["event_calculus"].metadata["state_formula_count"] >= 1
    assert report.ir_document.views["dcec_formula"].metadata["formula_count"] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.proof_gate.compiles is True
    event_records = report.ir_document.views["event_calculus"].payload["records"]
    assert event_records[0]["event_calculus_formula"].startswith("Happens(legal_norm(")
    assert "=> HoldsAt(" in event_records[0]["event_calculus_formula"]
    formula_records = report.ir_document.views["dcec_formula"].payload["records"]
    assert formula_records
    assert formula_records[0]["formula"].startswith(("O[", "P[", "F["))
    assert "happens(" in formula_records[0]["formula"]
    assert report.proof_gate.details[0]["validation_reason"] == "compiled_dcec_native_container"
    assert "cec_dcec_validation_failure_ratio" in report.round_trip.extra_losses
    assert "cec_dcec_event_formula_invalid_ratio" in report.round_trip.extra_losses
    assert any(
        triple["predicate"] == "event_calculus_formula"
        for triple in report.ir_document.frame_logic_triples
    )


def test_cec_dcec_bridge_synthesizes_fallback_formula_when_norm_extraction_is_empty() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        "The Commission, after notice and hearing, may revoke a permit.",
        document_id="cec-bridge-fallback",
        citation="CEC Bridge Fallback",
    )

    assert report.adapter_name == "cec_dcec"
    assert report.ir_document.views["event_calculus"].metadata["state_formula_count"] >= 1
    assert report.ir_document.views["dcec_formula"].metadata["formula_count"] >= 1
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.compiles is True
    event_records = report.ir_document.views["event_calculus"].payload["records"]
    assert event_records[0]["event_calculus_formula"].startswith("Happens(legal_norm(")
    assert event_records[0]["event_formula_syntax_valid"] is True
    formula_records = report.ir_document.views["dcec_formula"].payload["records"]
    assert formula_records[0]["proof_input"].startswith(("O(", "P(", "F("))
    assert "happens(" in formula_records[0]["proof_input"]
    assert report.round_trip.extra_losses["cec_dcec_no_formula_loss"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_uses_lifecycle_fallback_when_converter_output_is_formula() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _FormulaLikeOutput:
        proposition = "forall x. (Actor(x) -> Vacant(x))"
        operator = None
        agent = None

    class _FormulaLikeResult:
        success = True
        output = _FormulaLikeOutput()
        metadata = {}

    class _FormulaLikeConverter:
        @staticmethod
        def convert(_text: str):
            return _FormulaLikeResult()

    adapter = CecDcecBridgeAdapter(converter=_FormulaLikeConverter())
    report = adapter.evaluate(
        "Sec. 3475 - Vacant. This section was repealed by public law.",
        document_id="cec-bridge-vacant-fallback",
        citation="CEC Bridge Vacant Fallback",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    assert event_record["actor"] == "statute_section"
    assert event_record["event"] == "mark_section_vacant"
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]
    assert "forall" not in formula_record["proof_input"]
    assert "mark_section_vacant" in formula_record["proof_input"]
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0


def test_cec_dcec_bridge_recovers_norms_from_legacy_parser_element_metadata() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _LegacyParserElementResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:cec:parser-element",
                "canonical_citation": "36 U.S.C. 151504",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["submit report"],
                "text": "The Secretary shall submit report.",
                "support_text": "The Secretary shall submit report.",
                "support_span": [0, 33],
                "norm_type": "obligation",
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [4, 13],
                    "modality": [14, 19],
                    "action": [20, 33],
                },
            },
            "legal_norm_irs": [],
        }

    class _LegacyParserElementConverter:
        @staticmethod
        def convert(_text: str):
            return _LegacyParserElementResult()

    adapter = CecDcecBridgeAdapter(converter=_LegacyParserElementConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="cec-bridge-legacy-parser-element",
        citation="CEC Bridge Legacy Parser Element",
    )

    assert report.ir_document.views["event_calculus"].metadata["state_formula_count"] == 1
    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["source_id"] == "legacy:cec:parser-element"
    assert event_record["event_formula_source"] == "deontic.prover_syntax"
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_symbol"]
        == "Happens"
    )
    assert event_record["event_formula_fingerprint"]
    assert report.proof_gate.compiles is True


def test_cec_dcec_bridge_prefers_direct_event_formula_metadata() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _DirectFormulaResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "direct:cec:formula",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                    "event_calculus_formula": (
                        "Happens(legal_norm(direct_cec_formula), t) "
                        "=> HoldsAt(O(happens(agency,publish_notice,t0)), t)."
                    ),
                    "event_formula_syntax_valid": "false",
                    "event_formula_source": "canonical_legal_ir",
                }
            ]
        }

    class _DirectFormulaConverter:
        @staticmethod
        def convert(_text: str):
            return _DirectFormulaResult()

    adapter = CecDcecBridgeAdapter(converter=_DirectFormulaConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-direct-formula",
        citation="CEC Bridge Direct Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_source"] == "canonical_legal_ir"
    assert event_record["event_formula_syntax_valid"] is True
    assert event_record["event_calculus_formula"].startswith(
        "Happens(legal_norm(direct_cec_formula), t)"
    )
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_canonicalizes_direct_event_formula_text() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _CanonicalFormulaResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "canonical:cec:formula",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                    "event_calculus_formula": (
                        "Happens[legal_norm(canonical_cec_formula), t] "
                        "⇒ HoldsAt[O[happens(agency,publish_notice,t0)], t]."
                    ),
                    "event_formula_source": "canonical_legal_ir",
                }
            ]
        }

    class _CanonicalFormulaConverter:
        @staticmethod
        def convert(_text: str):
            return _CanonicalFormulaResult()

    adapter = CecDcecBridgeAdapter(converter=_CanonicalFormulaConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-canonical-formula",
        citation="CEC Bridge Canonical Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(canonical_cec_formula), t) "
        "=> HoldsAt(O(happens(agency,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_connector"]
        == "=>"
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_recovers_nested_deontic_cec_prover_record() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NestedFormulaResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "nested:cec:formula",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                    "prover_syntax_records": [
                        {
                            "target": "fol",
                            "exported_formula": "forall x. AppliesTo(x)",
                        },
                        {
                            "target": "deontic_cec",
                            "exported_formula": (
                                "always(Happens(legal_norm(nested_cec_formula), t) "
                                "=> HoldsAt(O(happens(agency,publish_notice,t0)), t))."
                            ),
                            "syntax_valid": False,
                        },
                    ],
                }
            ]
        }

    class _NestedFormulaConverter:
        @staticmethod
        def convert(_text: str):
            return _NestedFormulaResult()

    adapter = CecDcecBridgeAdapter(converter=_NestedFormulaConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-nested-formula",
        citation="CEC Bridge Nested Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_source"] == "legal_norm_ir.event_calculus_formula"
    assert event_record["event_formula_syntax_valid"] is True
    assert event_record["event_formula_target_parse_profile"]["top_level_symbol"] == "always"
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_compiles_native_state_norms_without_deontic_wrapper() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _StateNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "state:cec:definition",
                    "actor": "AWACS memorandum of understanding",
                    "action": "means multilateral memorandum",
                    "modality": "DEF",
                    "norm_type": "definition",
                    "support_text": (
                        "In this section, the term AWACS memorandum of "
                        "understanding means the Multilateral Memorandum."
                    ),
                },
                {
                    "source_id": "state:cec:applicability",
                    "actor": "chapter",
                    "action": "applies to a vessel",
                    "modality": "applies to",
                    "norm_type": "applicability",
                    "support_text": "This chapter applies to a vessel on a voyage.",
                },
            ]
        }

    class _StateNormConverter:
        @staticmethod
        def convert(_text: str):
            return _StateNormResult()

    adapter = CecDcecBridgeAdapter(converter=_StateNormConverter())
    report = adapter.evaluate(
        "In this section, the term means. This chapter applies to a vessel.",
        document_id="cec-bridge-native-state-norms",
        citation="CEC Bridge State Norms",
    )

    formula_records = report.ir_document.views["dcec_formula"].payload["records"]

    assert formula_records[0]["proof_input"].startswith("Definition(")
    assert formula_records[1]["proof_input"].startswith("AppliesTo(")
    assert not formula_records[0]["proof_input"].startswith(("O(", "P(", "F("))
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0


def test_cec_dcec_bridge_propagates_selected_frame_guidance_to_records_and_triples() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _GuidedNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "guided:cec:notice-hearing",
                    "actor": "Commission",
                    "action": "revoke permit after notice and hearing",
                    "modality": "permitted",
                    "support_text": "The Commission, after notice and hearing, may revoke a permit.",
                    "selected_frame": "administrative_notice_hearing",
                }
            ]
        }

    class _GuidedNormConverter:
        @staticmethod
        def convert(_text: str):
            return _GuidedNormResult()

    adapter = CecDcecBridgeAdapter(converter=_GuidedNormConverter())
    report = adapter.evaluate(
        "The Commission, after notice and hearing, may revoke a permit.",
        document_id="cec-bridge-guided-frame",
        citation="CEC Bridge Guided Frame",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["selected_frame"] == "administrative_notice_hearing"
    assert event_record["selected_frame_source"] == "norm.selected_frame"
    assert (
        event_record["event_formula_target_components"]["selected_frame"]
        == "administrative_notice_hearing"
    )
    assert any(
        triple["predicate"] == "selected_frame"
        and triple["object"] == "administrative_notice_hearing"
        for triple in report.ir_document.frame_logic_triples
    )


def test_cec_dcec_bridge_projects_procedure_events_into_cec_view_and_graph() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _ProcedureNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "procedure:cec:notice-hearing",
                    "actor": "Commission",
                    "action": "revoke permit",
                    "modality": "permitted",
                    "procedure": {
                        "trigger_event": "notice",
                        "terminal_event": "revocation",
                        "event_chain": [
                            {
                                "event": "notice",
                                "order": 1,
                                "relations": [],
                            },
                            {
                                "event": "hearing",
                                "order": 2,
                                "relations": [
                                    {
                                        "relation": "after",
                                        "anchor_event": "notice",
                                    }
                                ],
                            },
                        ],
                    },
                }
            ]
        }

    class _ProcedureNormConverter:
        @staticmethod
        def convert(_text: str):
            return _ProcedureNormResult()

    adapter = CecDcecBridgeAdapter(converter=_ProcedureNormConverter())
    report = adapter.evaluate(
        "The Commission, after notice and hearing, may revoke a permit.",
        document_id="cec-bridge-procedure-events",
        citation="CEC Bridge Procedure Events",
    )

    event_view = report.ir_document.views["cec_events"]
    procedure_events = [
        event
        for event in event_view.payload["events"]
        if event["event_role"] == "procedure_event"
    ]
    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert event_view.metadata["procedure_event_count"] == 2
    assert [event["event"] for event in procedure_events] == ["notice", "hearing"]
    assert procedure_events[1]["relation"] == "after"
    assert procedure_events[1]["anchor_event"] == "notice"
    assert len(event_record["procedure_event_records"]) == 2
    assert any(
        triple["predicate"] == "has_procedure_event"
        for triple in report.ir_document.frame_logic_triples
    )
    assert any(
        triple["predicate"] == "relation" and triple["object"] == "after"
        for triple in report.ir_document.frame_logic_triples
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_promotes_compiler_guidance_frame_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _PlainNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-26-994-cbae6d13150585b8",
                    "actor": "Secretary",
                    "action": "prescribe regulations",
                    "modality": "obligated",
                    "support_text": "The Secretary shall prescribe regulations.",
                }
            ]
        }

    class _PlainNormConverter:
        @staticmethod
        def convert(_text: str):
            return _PlainNormResult()

    adapter = CecDcecBridgeAdapter(converter=_PlainNormConverter())
    report = adapter.evaluate(
        "26 U.S.C. 994: The Secretary shall prescribe regulations.",
        document_id="cec-bridge-compiler-guidance-frame",
        citation="26 U.S.C. 994",
        compiler_guidance={
            "compiler_guidance_todo_routes": {
                "repair_cec_dcec_bridge": 1,
            },
            "evidence": [
                {
                    "evidence_rank": 1,
                    "sample_id": "us-code-26-994-cbae6d13150585b8",
                    "selected_frame_after": "administrative_notice_hearing",
                }
            ],
        },
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["selected_frame"] == "administrative_notice_hearing"
    assert event_record["selected_frame_source"] == (
        "compiler_guidance.evidence.selected_frame_after"
    )
    assert event_record["compiler_guidance_source"] == "repair_cec_dcec_bridge"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.ir_document.metadata["compiler_guidance_applied"] is True
    assert (
        event_record["event_formula_target_components"]["selected_frame"]
        == "administrative_notice_hearing"
    )
    assert any(
        triple["predicate"] == "compiler_guidance_source"
        and triple["object"] == "repair_cec_dcec_bridge"
        for triple in report.ir_document.frame_logic_triples
    )


def test_cec_dcec_bridge_emits_parse_profile_for_fallback_event_formulas() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoSourceIdNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "actor": "Secretary",
                    "action": "submit report",
                    "modality": "obligated",
                }
            ]
        }

    class _NoSourceIdNormConverter:
        @staticmethod
        def convert(_text: str):
            return _NoSourceIdNormResult()

    adapter = CecDcecBridgeAdapter(converter=_NoSourceIdNormConverter())
    report = adapter.evaluate(
        "The Secretary shall submit report.",
        document_id="cec-bridge-fallback-parse-profile",
        citation="CEC Bridge Fallback Parse Profile",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_source"] == "cec_dcec_bridge_fallback"
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert (
        event_record["event_formula_target_components"]["uses_event_calculus_wrapper"]
        is True
    )
    assert event_record["event_formula_target_quality_gate"]["syntax_valid"] is True
    assert len(event_record["event_formula_fingerprint"]) == 24
    assert any(
        triple["predicate"] == "event_formula_fingerprint"
        for triple in report.ir_document.frame_logic_triples
    )


def test_cec_dcec_bridge_normalizes_exported_rule_style_event_formulas(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:rule:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:rule:1": [
                {
                    "event_calculus_formula": (
                        "HoldsAt(O(happens(agency,publish_notice,t0)), t) "
                        ":- Happens(legal_norm(bridge_rule_1), t)."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-export-rule-style",
        citation="CEC Bridge Export Rule Style",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_source"] == "deontic.prover_syntax"
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert event_record["event_formula_target_parse_profile"]["top_level_symbol"] == "HoldsAt"
    assert event_record["event_formula_target_parse_profile"]["top_level_connector"] == ":-"
    assert (
        event_record["event_formula_target_components"]["uses_event_calculus_wrapper"]
        is True
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_promotes_labeled_deontic_event_exports(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:proof-obligation:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:proof-obligation:1": [
                {
                    "event_calculus_formula": (
                        "proof obligation: O(happens(agency,publish_notice,t0))."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-labeled-proof-obligation",
        citation="CEC Bridge Labeled Proof Obligation",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(bridge_proof_obligation_1), t) "
        "=> HoldsAt(O(happens(agency,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_connector"] == "=>"
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_normalizes_unicode_arrow_event_formulas(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:unicode:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:unicode:1": [
                {
                    "event_calculus_formula": (
                        "Happens(legal_norm(bridge_unicode_1), t) "
                        "→ HoldsAt(O(happens(agency,publish_notice,t0)), t)."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-unicode-arrow",
        citation="CEC Bridge Unicode Arrow",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_connector"] == "=>"
    )
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_accepts_temporal_wrapper_event_formulas(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:always:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:always:1": [
                {
                    "event_calculus_formula": (
                        "always(Happens(legal_norm(bridge_always_1), t) "
                        "=> HoldsAt(O(happens(agency,publish_notice,t0)), t))."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-temporal-wrapper",
        citation="CEC Bridge Temporal Wrapper",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_symbol"] == "always"
    )
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_accepts_bracketed_event_formula_wrappers(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:brackets:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:brackets:1": [
                {
                    "event_calculus_formula": (
                        "Happens[legal_norm(bridge_brackets_1), t] => "
                        "HoldsAt(O[happens(agency,publish_notice,t0)], t)."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-bracketed-wrappers",
        citation="CEC Bridge Bracketed Wrappers",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_symbol"]
        == "Happens"
    )
    assert event_record["event_formula_target_parse_profile"]["event_predicates"] == [
        "Happens",
        "HoldsAt",
    ]
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_accepts_capitalized_function_style_quantifier_formulas(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:quantifier:1",
                    "actor": "Agency",
                    "action": "publish notice",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:quantifier:1": [
                {
                    "event_calculus_formula": (
                        "Forall(t, Happens(legal_norm(bridge_quantifier_1), t) "
                        "=> HoldsAt(O(happens(agency,publish_notice,t0)), t))."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="cec-bridge-capitalized-quantifier",
        citation="CEC Bridge Capitalized Quantifier",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_symbol"] == "forall"
    )
    assert event_record["event_formula_target_parse_profile"]["quantifier_variables"] == ["t"]
    assert (
        event_record["event_formula_target_parse_profile"]["target_parse_profile_complete"]
        is True
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_repairs_export_component_slot_alignment_metadata(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:recipient-slot:1",
                    "actor": "Selecting official",
                    "action": "provide employee written notification",
                    "modality": "obligated",
                }
            ]
        }

    class _NormConverter:
        @staticmethod
        def convert(_text: str):
            return _NormResult()

    def _fake_event_formula_exports(_norms):
        return {
            "bridge:recipient-slot:1": [
                {
                    "event_calculus_formula": (
                        "Happens(legal_norm(bridge_recipient_slot_1), t) => "
                        "HoldsAt(O(forall x. "
                        "(SelectingOfficial(x) -> "
                        "ProvideEmployeeWrittenNotification(x))), t)."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": False,
                    "event_formula_target_components": {
                        "target": "deontic_cec",
                        "slot_alignment_complete": False,
                        "decoded_missing_grounded_ir_slots": ["recipient"],
                        "formula_missing_decoded_slots": [],
                        "formula_ungrounded_slots": [],
                        "target_symbol_alignment_complete": True,
                        "target_dialect_profile_complete": True,
                        "reconstruction_token_profile_complete": True,
                        "unreconstructed_source_tokens": [],
                    },
                    "event_formula_target_quality_gate": {
                        "slot_alignment_complete": False,
                        "failed_quality_checks": ["slot_alignment"],
                    },
                }
            ]
        }

    monkeypatch.setattr(
        cec_dcec_mod,
        "_event_formula_exports_from_norms",
        _fake_event_formula_exports,
    )

    adapter = cec_dcec_mod.CecDcecBridgeAdapter(converter=_NormConverter())
    report = adapter.evaluate(
        "The selecting official shall provide the employee written notification.",
        document_id="cec-bridge-recipient-slot-repair",
        citation="CEC Bridge Recipient Slot Repair",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    components = event_record["event_formula_target_components"]
    quality_gate = event_record["event_formula_target_quality_gate"]

    assert event_record["event_formula_syntax_valid"] is True
    assert components["slot_alignment_complete"] is True
    assert components["decoded_missing_grounded_ir_slots"] == []
    assert components["cec_dcec_slot_alignment_repaired"] is True
    assert components["cec_dcec_slot_alignment_repaired_slots"] == ["recipient"]
    assert quality_gate["slot_alignment_complete"] is True
    assert quality_gate["failed_quality_checks"] == []
    assert quality_gate["cec_dcec_slot_alignment_repaired"] is True
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


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


def test_external_prover_router_uses_syntactic_native_fallback_when_tdfol_unavailable(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for router fallback test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_tdfol_import)

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=True,
        enable_symbolicai=False,
        enable_z3=False,
    )
    result = router.prove("O(register_notice(secretary))", strategy="sequential")

    assert router.get_available_provers() == ["native_syntactic"]
    assert result.is_proved is False
    assert result.prover_used == "native_syntactic"
    assert result.reason == "Used native_syntactic (no proof)"
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_uses_syntactic_native_fallback_when_native_init_fails(
    monkeypatch,
) -> None:
    import sys
    import types

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    module_name = "ipfs_datasets_py.logic.TDFOL.tdfol_prover"
    fake_module = types.ModuleType(module_name)

    class _BrokenTDFOLProver:
        def __init__(self) -> None:
            raise RuntimeError("native prover dependency half-installed")

    fake_module.TDFOLProver = _BrokenTDFOLProver
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=True,
        enable_symbolicai=False,
        enable_z3=False,
    )
    result = router.route("publish_notice(agency)", strategy="sequential")

    assert router.get_available_provers() == ["native_syntactic"]
    assert result.is_proved is False
    assert result.prover_used == "native_syntactic"
    assert result.all_results["native_syntactic"].is_valid is True


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


def test_external_prover_router_bridge_recovers_formulas_without_formula_objects() -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _StringOnlyFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            stripped_records = []
            for record in context["formula_records"]:
                next_record = dict(record)
                next_record.pop("formula_object", None)
                stripped_records.append(next_record)
            return (
                document,
                {
                    **dict(context),
                    "formula_records": stripped_records,
                },
            )

    adapter = ExternalProverRouterBridgeAdapter(tdfol_adapter=_StringOnlyFolAdapter())
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-string-only",
        citation="External Prover Bridge String Only",
    )

    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.compiles is True
    assert report.ir_document.metadata["router_resolved_formula_count"] >= 1


def test_external_prover_router_bridge_recovers_formulas_from_legacy_proof_input_records(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _NoProverRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return []

    class _ProofInputOnlyFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            proof_input_records = []
            for record in context["formula_records"]:
                next_record = dict(record)
                next_record["proof_input"] = next_record.get("formula")
                next_record.pop("formula_object", None)
                next_record.pop("formula", None)
                proof_input_records.append(next_record)
            return (
                document,
                {
                    **dict(context),
                    "formula_records": proof_input_records,
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoProverRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(tdfol_adapter=_ProofInputOnlyFolAdapter())
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-proof-input-only",
        citation="External Prover Bridge Proof Input Only",
    )

    records = report.ir_document.views["prover_formulas"].payload["records"]
    assert records
    assert records[0]["formula"]
    assert report.ir_document.metadata["router_resolved_formula_count"] >= 1
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.details[0]["reason"] == "no_provers_available"


def test_external_prover_router_bridge_sanitizes_reserved_term_prefix_formulas(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _NoProverRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return []

    class _ReservedTermFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            patched = dict(formula_records[0])
            patched.pop("formula_object", None)
            patched["formula"] = "O(in_that_event_maintain_reserves(or_said_banks))"
            patched["proof_input"] = patched["formula"]
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [patched],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoProverRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_ReservedTermFolAdapter(),
        enable_native=False,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall maintain reserves.",
        document_id="external-prover-bridge-sanitized-term-prefix",
        citation="External Prover Bridge Sanitized Term Prefix",
    )

    formulas_view = report.ir_document.views["prover_formulas"]
    records = formulas_view.payload["records"]
    assert records and records[0]["formula"]
    assert records[0]["formula_parse_ok"] is True
    assert records[0]["formula_sanitized"] is True
    assert "term_or_said_banks" in records[0]["formula"]
    assert formulas_view.metadata["sanitized_formula_count"] == 1
    assert formulas_view.metadata["text_fallback_formula_count"] == 0
    assert report.ir_document.metadata["router_sanitized_formula_count"] == 1
    assert report.ir_document.metadata["router_text_fallback_formula_count"] == 0


def test_external_prover_router_bridge_proof_gate_supports_legacy_prove_signature(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _LegacyRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["legacy"]

        @staticmethod
        def prove(formula, axioms=None, strategy="auto", timeout=1.0):
            if strategy != "sequential":
                raise ValueError("legacy routers expect a string strategy")
            return False

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _LegacyRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-legacy-signature",
        citation="External Prover Bridge Legacy Signature",
    )

    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["compiled"] is True
    assert report.proof_gate.details[0]["proved"] is False


def test_external_prover_router_bridge_soft_passes_when_no_formulas_available() -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _NoFormulaFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [],
                },
            )

    adapter = ExternalProverRouterBridgeAdapter(tdfol_adapter=_NoFormulaFolAdapter())
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-no-formulas",
        citation="External Prover Bridge No Formulas",
    )

    assert report.status == "ok"
    assert report.proof_gate.compiles is True
    assert report.proof_gate.attempted_count == 1
    assert report.proof_gate.valid_count == 1
    assert report.proof_gate.details[0]["reason"] == "no_router_formulas_available"
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_soft_passes_when_no_provers_available(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _NoProverRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return []

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoProverRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-no-provers",
        citation="External Prover Bridge No Provers",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.failure_ratio == 0.0
    assert report.proof_gate.details[0]["bridge_soft_pass"] is True
    assert report.proof_gate.details[0]["reason"] == "no_provers_available"
    assert report.round_trip.extra_losses["external_prover_unavailable_loss"] == 1.0


def test_external_prover_router_bridge_soft_passes_when_available_router_cannot_route(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _UnavailableRouteRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            raise RuntimeError("native_router_temporarily_unavailable")

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _UnavailableRouteRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "12 U.S.C. 466: The term reserve bank means a Federal reserve bank.",
        document_id="external-prover-bridge-unavailable-route-soft-pass",
        citation="12 U.S.C. 466",
    )

    assert report.status == "ok"
    assert report.metadata["proof_gate_soft_pass"] is True
    assert report.metadata["proof_gate_soft_pass_reason"] == "router_compatibility_soft_pass"
    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["bridge_soft_pass"] is True
    assert report.proof_gate.details[0]["reason"] == "router_unavailable"
    assert "external_provers:compat_softpass" in report.proof_gate.verified_by
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_soft_passes_deontic_to_deontic_router_compatibility_failures(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _CompatFailureResult:
        def __init__(self) -> None:
            self.is_proved = False
            self.prover_used = ""
            self.proof_time = 0.01
            self.reason = "All provers failed"
            self.strategy_used = "sequential"
            self.all_results = {"native": "Error: compatibility_failure"}

    class _CompatFailureRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _CompatFailureResult()

    class _DeonticOnlyFormulaAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            patched = dict(formula_records[0])
            patched.pop("formula_object", None)
            patched["formula"] = "O(register_notice(secretary))"
            patched["proof_input"] = patched["formula"]
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [patched],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _CompatFailureRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_DeonticOnlyFormulaAdapter(),
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The Secretary shall register notice.",
        document_id="external-prover-bridge-deontic-compat-soft-pass",
        citation="External Prover Bridge Deontic Compat Soft Pass",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["bridge_soft_pass"] is True
    assert (
        report.proof_gate.details[0]["soft_pass_reason"]
        == "router_deontic_family_compatibility"
    )
    assert report.proof_gate.details[0]["soft_pass_family_pair"] == "deontic->deontic"
    assert (
        "external_provers:family_softpass:deontic_to_deontic"
        in report.proof_gate.verified_by
    )
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_soft_passes_deontic_to_temporal_router_compatibility_failures(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _CompatFailureResult:
        def __init__(self) -> None:
            self.is_proved = False
            self.prover_used = ""
            self.proof_time = 0.01
            self.reason = "All provers failed"
            self.strategy_used = "sequential"
            self.all_results = {"native": "Error: compatibility_failure"}

    class _CompatFailureRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _CompatFailureResult()

    class _DeonticTemporalFormulaAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            patched = dict(formula_records[0])
            patched.pop("formula_object", None)
            patched["formula"] = "O(G(register_notice(secretary)))"
            patched["proof_input"] = patched["formula"]
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [patched],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _CompatFailureRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_DeonticTemporalFormulaAdapter(),
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The Secretary shall register notice before issuance.",
        document_id="external-prover-bridge-deontic-temporal-compat-soft-pass",
        citation="External Prover Bridge Deontic Temporal Compat Soft Pass",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["bridge_soft_pass"] is True
    assert (
        report.proof_gate.details[0]["soft_pass_reason"]
        == "router_deontic_family_compatibility"
    )
    assert report.proof_gate.details[0]["soft_pass_family_pair"] == "deontic->temporal"
    assert (
        "external_provers:family_softpass:deontic_to_temporal"
        in report.proof_gate.verified_by
    )
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_records_compiler_guidance_prover_gate_hint(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _GuidedFailureResult:
        def __init__(self) -> None:
            self.is_proved = True
            self.prover_used = "native"
            self.proof_time = 0.01
            self.reason = "Proved by native"
            self.strategy_used = "sequential"
            self.all_results = {"native": object()}

    class _GuidedFailureRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _GuidedFailureResult()

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _GuidedFailureRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-guidance-prover-gate-soft-pass",
        citation="External Prover Bridge Guidance Prover Gate Soft Pass",
        compiler_guidance={
            "compiler_guidance_todo_routes": {
                "repair_multiview_legal_ir_prover_gate": 1
            }
        },
    )

    assert report.status == "ok"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.metadata["compiler_guidance_prover_gate_hint"] is True
    assert report.metadata["proof_gate_soft_pass"] is False
    assert report.metadata["proof_gate_soft_pass_reason"] == ""
    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert "external_provers:native" in report.proof_gate.verified_by
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_accepts_packet_shaped_guidance_route(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _GuidedResult:
        def __init__(self) -> None:
            self.is_proved = True
            self.prover_used = "native"
            self.proof_time = 0.01
            self.reason = "Proved by native"
            self.strategy_used = "sequential"
            self.all_results = {"native": object()}

    class _GuidedRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _GuidedResult()

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _GuidedRouter(),
    )

    guidance = {
        "compiler_guidance_quality_gate": "pass",
        "compiler_guidance_route": "repair_multiview_legal_ir_prover_gate",
        "semantic_bundle_key": (
            '{"program_synthesis_scope":"external_provers",'
            '"route":"repair_multiview_legal_ir_prover_gate",'
            '"source":"compiler_guidance_distillation_v1",'
            '"target_component":"external_provers.router"}'
        ),
        "target_component": "external_provers.router",
    }

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-packet-guidance-route",
        citation="External Prover Bridge Packet Guidance Route",
        compiler_guidance=guidance,
    )

    assert report.status == "ok"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.metadata["compiler_guidance_prover_gate_hint"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_accepts_rescue_original_action_guidance(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _GuidedFailureResult:
        def __init__(self) -> None:
            self.is_proved = False
            self.prover_used = ""
            self.proof_time = 0.01
            self.reason = "Error: compatibility_failure"
            self.strategy_used = "sequential"
            self.all_results = {"native": "Error: compatibility_failure"}

    class _GuidedFailureRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _GuidedFailureResult()

    class _PlainFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            patched = dict(formula_records[0])
            patched.pop("formula_object", None)
            patched["formula"] = "publish_notice(agency)"
            patched["proof_input"] = patched["formula"]
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [patched],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _GuidedFailureRouter(),
    )

    guidance = {
        "semantic_bundle_key": (
            '{"failure_reason":"main_apply_validation_failed_rolled_back",'
            '"original_action":"repair_external_prover_router",'
            '"program_synthesis_scope":"external_provers",'
            '"source":"failed_validation_rescue_v1",'
            '"target_component":"external_provers.router"}'
        ),
        "target_component": "external_provers.router",
    }

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_PlainFolAdapter(),
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-rescue-original-action-guidance",
        citation="External Prover Bridge Rescue Original Action Guidance",
        compiler_guidance=guidance,
    )

    assert report.status == "ok"
    assert report.metadata["compiler_guidance_prover_gate_hint"] is True
    assert report.metadata["proof_gate_soft_pass"] is True
    assert report.metadata["proof_gate_soft_pass_reason"] == (
        "router_compatibility_soft_pass"
    )
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_supports_route_signature_without_axioms(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _NoAxiomsRouteResult:
        def __init__(self) -> None:
            self.is_proved = True
            self.prover_used = "legacy"
            self.proof_time = 0.01
            self.reason = "Proved by legacy"
            self.strategy_used = "sequential"

    class _NoAxiomsRouteRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["legacy"]

        @staticmethod
        def route(formula, strategy="auto", timeout=1.0):
            if strategy != "sequential":
                raise ValueError("legacy route expects string strategy")
            return _NoAxiomsRouteResult()

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoAxiomsRouteRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-no-axioms-route",
        citation="External Prover Bridge No Axioms Route",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["prover_used"] == "legacy"
    assert "external_provers:legacy" in report.proof_gate.verified_by


def test_external_prover_router_bridge_supports_positional_route_signature(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _PositionalRouteResult:
        def __init__(self) -> None:
            self.is_proved = True
            self.prover_used = "legacy"
            self.proof_time = 0.01
            self.reason = "Proved by legacy"
            self.strategy_used = "sequential"

    class _PositionalRouteRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["legacy"]

        @staticmethod
        def route(formula, strategy, timeout):
            if strategy != "sequential":
                raise ValueError("legacy positional route expects sequential strategy")
            if float(timeout) <= 0.0:
                raise ValueError("timeout must be positive")
            return _PositionalRouteResult()

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _PositionalRouteRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-positional-route",
        citation="External Prover Bridge Positional Route",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["prover_used"] == "legacy"
    assert "external_provers:legacy" in report.proof_gate.verified_by


def test_external_prover_router_bridge_falls_back_to_inventory_only_router(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _LegacyInventoryProver:
        @staticmethod
        def prove(_formula, timeout_ms=1000):
            return bool(timeout_ms)

    class _InventoryOnlyRouter:
        provers = {"native": _LegacyInventoryProver()}
        backup_provers = ("native",)
        fallback_prover = "native"

        @staticmethod
        def select_prover(_formula):
            return "native"

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _InventoryOnlyRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=True,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-inventory-only",
        citation="External Prover Bridge Inventory Only",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["prover_used"] == "native"
    assert "external_provers:native" in report.proof_gate.verified_by
    assert report.round_trip.extra_losses["external_prover_unavailable_loss"] == 0.0


def test_fol_tdfol_coerce_formula_sanitizes_reserved_term_prefixes() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "O(with_the_consent_of_the_board(or_said_banks))"
    parsed = coerce_tdfol_formula(formula)

    assert parsed is not None
    assert "term_or_said_banks" in parsed.to_string()


def test_fol_tdfol_coerce_formula_sanitizes_keyword_prefixed_identifiers() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    notification_formula = "O(register_notification(notification))"
    section_formula = (
        "O(be_construed_to_contravene_any_applicable_state_law("
        "nothing_in_this_section))"
    )

    parsed_notification = coerce_tdfol_formula(notification_formula)
    parsed_section = coerce_tdfol_formula(section_formula)

    assert parsed_notification is not None
    assert "term_notification" in parsed_notification.to_string()
    assert parsed_section is not None
    assert "term_nothing_in_this_section" in parsed_section.to_string()


def test_fol_tdfol_coerce_formula_normalizes_noisy_prover_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "O(make_report(person,))": "O(make_report(person))",
        "O(make_report(person)) # source: 49 U.S.C. 21311": (
            "O(make_report(person))"
        ),
        "fof(ax_1, axiom, O(make_report(person))).": "O(make_report(person))",
        "tdfol_formula = `O(register_notification(notification))`": (
            "O(register_notification(term_notification))"
        ),
        "O(qualified(section:12574.))": "O(qualified(section:12574))",
        "TDFOL.prover: O(apply(this_chapter))": "O(apply(this_chapter))",
        (
            "proof_obligation(target=TDFOL.prover, "
            "formula=O(apply(this_chapter)))"
        ): "O(apply(this_chapter))",
        "O{apply(this_chapter)}": "O(apply(this_chapter))",
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_zkp_attestation_bridge_evaluates_proof_attestations_and_graph() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("zkp_attestation")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="zkp-bridge-smoke",
        citation="ZKP Bridge Smoke",
    )

    assert report.adapter_name == "zkp_attestation"
    assert report.ir_document.views["zkp_attestations"].metadata["attestation_count"] >= 1
    assert report.ir_document.views["zkp_public_inputs"].metadata["record_count"] >= 1
    assert report.ir_document.has_frame_logic is True
    assert report.graph_projection.neo4j_compatible is True
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["zkp_attestation_missing_loss"] == 0.0
    assert report.round_trip.extra_losses["zkp_verification_failure_ratio"] == 0.0
    assert "zkp:simulated" in report.proof_gate.verified_by
    record = report.ir_document.views["zkp_attestations"].payload["records"][0]
    assert record["attestation_ref"] == record["public_inputs"]["attestation_ref"]
    assert record["attestation_view"]["attestation_ref"] == record["attestation_ref"]
    assert record["attestation_view_version"] == 1
    assert record["circuit_ref"].startswith("legal_ir_zkp_attestation@v")
    assert record["theorem_hash"] == record["public_inputs"]["theorem_hash"]


def test_zkp_attestation_bridge_records_are_deterministic_for_same_input() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("zkp_attestation")
    text = "The agency shall publish notice before the permit takes effect."

    first = adapter.evaluate(
        text,
        document_id="zkp-bridge-determinism",
        citation="ZKP Bridge Determinism",
    )
    second = adapter.evaluate(
        text,
        document_id="zkp-bridge-determinism",
        citation="ZKP Bridge Determinism",
    )

    first_records = first.ir_document.views["zkp_attestations"].payload["records"]
    second_records = second.ir_document.views["zkp_attestations"].payload["records"]

    assert first_records
    assert second_records
    assert [record["proof_hash"] for record in first_records] == [
        record["proof_hash"] for record in second_records
    ]


def test_zkp_attestation_bridge_passes_compiler_guidance_ref_into_public_inputs() -> None:
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
    from ipfs_datasets_py.logic.bridge.zkp_attestation import ZkpAttestationBridgeAdapter

    class _FakeTDFOLAdapter:
        @staticmethod
        def encode(*_args, **_kwargs):
            formula_records = [
                {
                    "formula": "O(publish_notice(agency))",
                    "predicates": ["publish_notice"],
                    "source_id": "tdfol:norm:0",
                    "source_norm": {
                        "compiler_guidance_todo_routes": {
                            "repair_zkp_attestation_bridge": 1.0,
                        },
                        "compiler_guidance_semantic_overlay_terms": ["notice"],
                    },
                }
            ]
            document = LegalIRDocument(
                document_id="tdfol-fake",
                source_text="The agency shall publish notice.",
                normalized_text="The agency shall publish notice.",
                source="unit_test",
            )
            return document, {"formula_records": formula_records}

    adapter = ZkpAttestationBridgeAdapter(tdfol_adapter=_FakeTDFOLAdapter())
    report = adapter.evaluate(
        "The agency shall publish notice.",
        document_id="zkp-guidance-bridge-smoke",
        citation="ZKP Guidance Bridge Smoke",
    )

    records = report.ir_document.views["zkp_attestations"].payload["records"]
    assert len(records) == 1
    record = records[0]
    assert record["compiler_guidance_ref"]
    assert record["public_inputs"]["compiler_guidance_ref"] == record["compiler_guidance_ref"]
    assert record["public_inputs"]["compiler_guidance_version"] == 1
    assert record["attestation_view"]["compiler_guidance_ref"] == record["compiler_guidance_ref"]
    assert record["attestation_view"]["compiler_guidance_version"] == 1


def test_zkp_prover_cache_separates_compiler_guidance_attestations() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver

    prover = ZKPProver(backend="simulated", enable_caching=True)
    first = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "compiler_guidance_ref": "a" * 64,
            "compiler_guidance_version": 1,
        },
    )
    second = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "compiler_guidance_ref": "b" * 64,
            "compiler_guidance_version": 1,
        },
    )

    assert first.public_inputs["compiler_guidance_ref"] == "a" * 64
    assert second.public_inputs["compiler_guidance_ref"] == "b" * 64
    assert first.public_inputs["attestation_ref"] != second.public_inputs["attestation_ref"]
    assert (
        first.metadata["attestation_view"]["compiler_guidance_ref"]
        == first.public_inputs["compiler_guidance_ref"]
    )
    assert (
        second.metadata["attestation_view"]["compiler_guidance_ref"]
        == second.public_inputs["compiler_guidance_ref"]
    )


def test_zkp_prover_derives_guidance_ref_from_contract_metadata() -> None:
    from ipfs_datasets_py.logic.zkp import (
        ZKPProver,
        ZKPVerifier,
        compiler_guidance_ref_from_metadata,
    )

    prover = ZKPProver(backend="simulated", enable_caching=True)
    verifier = ZKPVerifier(backend="simulated")
    theorem = "O(publish_notice(agency))"
    axioms = [theorem, "uses_predicate(publish_notice)"]
    first_metadata = {
        "circuit_ref": "legal_ir_zkp_attestation@v1",
        "circuit_version": 1,
        "compiler_guidance_contract": {
            "compiler_guidance_todo_routes": {
                "repair_zkp_attestation_bridge": 1.0,
            },
        },
    }
    second_metadata = {
        "circuit_ref": "legal_ir_zkp_attestation@v1",
        "circuit_version": 1,
        "compiler_guidance_contract": {
            "compiler_guidance_todo_routes": {
                "repair_multiview_legal_ir_view_coverage": 1.0,
            },
        },
    }

    first = prover.generate_proof(theorem, axioms, metadata=first_metadata)
    second = prover.generate_proof(theorem, axioms, metadata=second_metadata)

    assert first.public_inputs["compiler_guidance_ref"] == (
        compiler_guidance_ref_from_metadata(first_metadata)
    )
    assert second.public_inputs["compiler_guidance_ref"] == (
        compiler_guidance_ref_from_metadata(second_metadata)
    )
    assert first.public_inputs["attestation_ref"] != second.public_inputs["attestation_ref"]
    assert (
        first.metadata["attestation_view"]["compiler_guidance_ref"]
        == first.public_inputs["compiler_guidance_ref"]
    )
    assert verifier.verify_proof(first) is True
    assert verifier.verify_proof(second) is True


def test_zkp_verifier_rejects_stale_attestation_view() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    proof.metadata["attestation_view"] = {
        **proof.metadata["attestation_view"],
        "attestation_ref": "0" * 64,
    }

    verifier = ZKPVerifier(backend="simulated")

    assert verifier.verify_proof(proof) is False


def test_zkp_prover_cached_whitespace_variant_refreshes_attestation_view() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

    prover = ZKPProver(backend="simulated", enable_caching=True)
    prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    cached = prover.generate_proof(
        "  O(publish_notice(agency))\n",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    verifier = ZKPVerifier(backend="simulated")

    assert cached.public_inputs["theorem"] == "  O(publish_notice(agency))\n"
    assert (
        cached.metadata["attestation_view"]["public_inputs_commitment"]
        != ""
    )
    assert verifier.verify_proof(cached) is True
def test_zkp_prover_cache_separates_circuit_attestations() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver

    prover = ZKPProver(backend="simulated", enable_caching=True)
    theorem = "O(publish_notice(agency))"
    axioms = [theorem, "uses_predicate(publish_notice)"]

    first = prover.generate_proof(
        theorem,
        axioms,
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
        },
    )
    second = prover.generate_proof(
        theorem,
        axioms,
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation_guided@v1",
            "circuit_version": 1,
        },
    )

    assert first.public_inputs["circuit_ref"] == "legal_ir_zkp_attestation@v1"
    assert second.public_inputs["circuit_ref"] == "legal_ir_zkp_attestation_guided@v1"
    assert first.public_inputs["attestation_ref"] != second.public_inputs["attestation_ref"]
    assert first.metadata["attestation_view"]["circuit_ref"] == first.public_inputs["circuit_ref"]
    assert second.metadata["attestation_view"]["circuit_ref"] == second.public_inputs["circuit_ref"]


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
    assert report.total_loss >= 0.0
    assert report.view_coverage_loss() == 0.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0
    assert report.canonical_loss_vector()["legal_ir_multiview_total_loss"] == report.total_loss
    assert report.canonical_loss_vector()["legal_ir_multiview_view_coverage_loss"] == 0.0
    assert report.reports["deontic_norms"].metadata["coverage_requires_validation"] is False
    assert report.reports["deontic_norms"].accepted is True
    assert report.loss_vector()[
        "deontic_norms.deontic_quality_requires_validation_loss"
    ] == 0.0
    assert "deontic_norms.deontic_decoder_slot_loss" in report.loss_vector()
    assert "deontic_norms.deontic_ir_slot_provenance_loss" in report.loss_vector()
    target = report.training_target()
    assert target.document is report.document
    assert target.losses["legal_ir_multiview_total_loss"] == report.total_loss
    assert target.adapter_losses["deontic_norms"][
        "deontic_quality_requires_validation_loss"
    ] == 0.0
    assert target.view_distribution


def test_multiview_bridge_distribution_uses_canonical_component_lanes() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        "The agency shall publish notice before the permit takes effect.",
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="multiview-canonical-view-distribution",
        citation="Multiview Canonical View Distribution",
        cache=False,
    )

    distribution = report.view_distribution()
    assert distribution
    assert set(distribution) == {
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert "deontic.exports" not in distribution
    assert "deontic.metrics" not in distribution
    assert distribution["deontic.ir"] < 0.65
    assert distribution["TDFOL.prover"] > 0.20
    assert distribution["knowledge_graphs.neo4j_compat"] > 0.07
    assert abs(sum(distribution.values()) - 1.0) < 1e-9


def test_multiview_training_target_distribution_preserves_core_family_lanes() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        "The agency shall publish notice before the permit takes effect.",
        bridge_names=(
            "modal_frame_logic",
            "deontic_norms",
            "fol_tdfol",
            "cec_dcec",
            "external_prover_router",
            "zkp_attestation",
        ),
        document_id="multiview-bridge-contract-training-distribution",
        citation="Multiview Bridge Contract Training Distribution",
        cache=False,
    )

    canonical_distribution = report.view_distribution()
    target_distribution = report.training_target().view_distribution
    assert "modal.frame_logic" in canonical_distribution
    assert "external_provers.router" in canonical_distribution
    assert "modal.frame_logic" in target_distribution
    assert "external_provers.router" in target_distribution
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "external_provers.router",
        "knowledge_graphs.neo4j_compat",
        "modal.frame_logic",
        "zkp.circuits",
    }
    assert target_distribution["external_provers.router"] <= 0.125
    assert target_distribution["modal.frame_logic"] > 0.10
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-9


def test_multiview_training_target_distribution_preserves_zkp_tail_lane() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView

    report = MultiViewLegalIRReport(
        bridge_names=(),
        document=LegalIRDocument(
            document_id="multiview-zkp-tail-preserved",
            source_text="The agency shall publish notice.",
            normalized_text="The agency shall publish notice.",
            views={
                "deontic_norms.deontic_ir": LogicIRView(
                    name="deontic_ir",
                    source_component="deontic.ir",
                    payload={"norms": [{}] * 9},
                ),
                "fol_tdfol.tdfol_formula": LogicIRView(
                    name="tdfol_formula",
                    source_component="TDFOL.prover",
                    payload={"records": [{}] * 8},
                ),
                "cec_dcec.dcec_formula": LogicIRView(
                    name="dcec_formula",
                    source_component="CEC.native",
                    payload={"records": [{}] * 7},
                ),
                "zkp_attestation.zkp_attestations": LogicIRView(
                    name="zkp_attestations",
                    source_component="zkp.circuits",
                    payload={"records": [{}]},
                ),
            },
        ),
        reports={},
        failures={},
    )

    distribution = report.contract_view_distribution()
    assert "zkp.circuits" in distribution
    assert distribution["zkp.circuits"] > 0.0
    assert abs(sum(distribution.values()) - 1.0) < 1e-9


def test_multiview_training_target_compacts_official_usc_excerpt_auxiliary_lanes() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.17,
        "TDFOL.prover": 0.19,
        "deontic.ir": 0.28,
        "external_provers.router": 0.10,
        "knowledge_graphs.neo4j_compat": 0.14,
        "modal.frame_logic": 0.06,
        "zkp.circuits": 0.06,
    }
    text = (
        "U.S.C. Title 42 - THE PUBLIC HEALTH AND WELFARE 42 U.S.C. "
        "United States Code, 2024 Edition CHAPTER 129 - NATIONAL AND "
        "COMMUNITY SERVICE Sec. 12574 - Types of program assistance From "
        "the U.S. Government Publishing Office, www.gpo.gov §12574. Types "
        "of program assistance The Corporation may provide assistance under "
        "section 12571 of this title to a qualified applicant. Assistance "
        "provided in accordance with this subsection may cover a period of "
        "not more than 1 year. Editorial Notes Prior Provisions A prior "
        "section 12574 related to terms of service prior to the general "
        "amendment of subtitle D of title I of Pub. L. 101-610. Statutory "
        "Notes and Related Subsidiaries Effective Date Section effective "
        "Oct. 1, 1993, see section 123 of Pub. L. 103-82, set out as an "
        "Effective Date note under section 1701 of Title 16, Conservation."
    )

    compacted = _compact_official_usc_contract_distribution(
        distribution,
        text=text,
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["deontic.ir"] > compacted["CEC.native"]
    assert abs(sum(compacted.values()) - 1.0) < 1e-9


def test_multiview_training_target_compacts_short_official_usc_section() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.156,
        "TDFOL.prover": 0.1455,
        "deontic.ir": 0.162,
        "external_provers.router": 0.121,
        "knowledge_graphs.neo4j_compat": 0.1337,
        "modal.frame_logic": 0.1419,
        "zkp.circuits": 0.14,
    }
    text = (
        "§273a. National living donor mechanisms The Secretary may establish "
        "and maintain mechanisms to evaluate the long-term effects associated "
        "with living organ donations by individuals who have served as living "
        "donors. (July 1, 1944, ch. 373, title III, §371A, as added Pub. L. "
        "108-216, §7, Apr. 5, 2004, 118 Stat. 589.)"
    )

    compacted = _compact_official_usc_contract_distribution(
        distribution,
        text=text,
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert "modal.frame_logic" not in compacted
    assert abs(sum(compacted.values()) - 1.0) < 1e-9


def test_multiview_training_target_distribution_rebalances_dense_contract_lanes() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        (
            "Provided that the agency shall publish notice before the permit takes effect, "
            "the Secretary may issue certification."
        ),
        bridge_names=(
            "modal_frame_logic",
            "deontic_norms",
            "fol_tdfol",
            "cec_dcec",
            "external_prover_router",
            "zkp_attestation",
        ),
        document_id="multiview-bridge-contract-rebalance",
        citation="Multiview Bridge Contract Rebalance",
        cache=False,
    )

    target_distribution = report.training_target().view_distribution
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "external_provers.router",
        "knowledge_graphs.neo4j_compat",
        "modal.frame_logic",
        "zkp.circuits",
    }
    assert target_distribution["knowledge_graphs.neo4j_compat"] <= 0.145
    assert target_distribution["CEC.native"] <= 0.212
    assert target_distribution["TDFOL.prover"] <= 0.212
    assert target_distribution["external_provers.router"] <= 0.125
    assert target_distribution["modal.frame_logic"] > target_distribution["knowledge_graphs.neo4j_compat"]
    assert target_distribution["deontic.ir"] > target_distribution["knowledge_graphs.neo4j_compat"]
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_promotes_frame_definition_lanes() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text="The term Secretary means the Secretary of State.",
    )

    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.20
    assert rebalanced["CEC.native"] >= rebalanced["TDFOL.prover"]
    assert rebalanced["zkp.circuits"] <= 0.19
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_promotes_cec_for_statutory_definition_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "15 U.S.C. 6106. Definitions. From the U.S. Government Publishing "
            "Office. For purposes of this chapter, the term telemarketing means "
            "a plan, program, or campaign conducted to induce purchases of "
            "goods or services by use of one or more telephones."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.25
    assert rebalanced["CEC.native"] > rebalanced["knowledge_graphs.neo4j_compat"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.20
    assert rebalanced["TDFOL.prover"] <= 0.19
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_downweights_auxiliary_lanes_for_conditional_norms() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.22,
        "TDFOL.prover": 0.21,
        "deontic.ir": 0.23,
        "knowledge_graphs.neo4j_compat": 0.16,
        "zkp.circuits": 0.18,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Provided that the agency shall publish notice before the permit takes "
            "effect, the Secretary may issue certification."
        ),
    )

    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.14
    assert rebalanced["zkp.circuits"] <= 0.17
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_sparse_contract_rebalance_downweights_deontic_for_scaffold_heavy_statute_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_sparse_contract_distribution,
    )

    distribution = {
        "TDFOL.prover": 0.44,
        "deontic.ir": 0.48,
        "knowledge_graphs.neo4j_compat": 0.08,
    }

    rebalanced = _rebalance_sparse_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 38 - VETERANS' BENEFITS. From the U.S. Government "
            "Publishing Office. The Secretary shall submit monthly reports to "
            "administer this program. Editorial Notes Prior Provisions. "
            "Statutory Notes and Related Subsidiaries Effective Date."
        ),
    )

    assert rebalanced["deontic.ir"] <= 0.31
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.25
    assert rebalanced["TDFOL.prover"] == distribution["TDFOL.prover"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_sparse_contract_rebalance_preserves_non_scaffold_normative_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_sparse_contract_distribution,
    )

    distribution = {
        "TDFOL.prover": 0.44,
        "deontic.ir": 0.48,
        "knowledge_graphs.neo4j_compat": 0.08,
    }

    rebalanced = _rebalance_sparse_contract_distribution(
        distribution,
        text="The agency shall publish notice before the permit takes effect.",
    )

    assert rebalanced == distribution
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_sparse_contract_rebalance_shifts_repealed_scaffold_text_without_deontic_cues() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_sparse_contract_distribution,
    )

    distribution = {
        "TDFOL.prover": 0.44,
        "deontic.ir": 0.48,
        "knowledge_graphs.neo4j_compat": 0.08,
    }

    rebalanced = _rebalance_sparse_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 7 - AGRICULTURE. Editorial Notes. Statutory Notes and Related "
            "Subsidiaries. Secs. 343f, 343g - Repealed. Codification and amendments."
        ),
    )

    assert rebalanced["deontic.ir"] <= 0.28
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.26
    assert rebalanced["TDFOL.prover"] == distribution["TDFOL.prover"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_uses_calendar_deadline_cues_for_temporal_shift() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.22,
        "TDFOL.prover": 0.21,
        "deontic.ir": 0.23,
        "knowledge_graphs.neo4j_compat": 0.16,
        "zkp.circuits": 0.18,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Provided that the Secretary shall submit a report by October 1 of each year."
        ),
    )

    assert rebalanced["TDFOL.prover"] >= 0.24
    assert rebalanced["deontic.ir"] <= 0.31
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.12
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_biases_deontic_lane_for_underspecified_statute_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.22,
        "TDFOL.prover": 0.21,
        "deontic.ir": 0.23,
        "knowledge_graphs.neo4j_compat": 0.16,
        "zkp.circuits": 0.18,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text="22 U.S.C. 5505 - Disaster assistance for Americans abroad.",
    )

    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["deontic.ir"] > rebalanced["TDFOL.prover"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.13
    assert rebalanced["zkp.circuits"] <= 0.18
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_preserves_deontic_lane_for_scaffolded_contract_headings() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 20 - EDUCATION 20 U.S.C. United States Code, 2024 "
            "Edition CHAPTER 24 - GRANTS FOR EDUCATIONAL MATERIALS, FACILITIES "
            "AND SERVICES SUBCHAPTER III - STRENGTHENING OF EDUCATIONAL AGENCIES."
        ),
    )

    assert rebalanced["deontic.ir"] > rebalanced["knowledge_graphs.neo4j_compat"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.21
    assert rebalanced["TDFOL.prover"] <= 0.18
    assert rebalanced["zkp.circuits"] <= 0.12
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_authorization_headings_as_deontic_cues() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "7 U.S.C. 2204-5 Authorization of appropriations for cooperative "
            "research projects."
        ),
    )

    assert rebalanced["deontic.ir"] > 0.32
    assert rebalanced["CEC.native"] <= 0.19
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.12
    assert rebalanced["zkp.circuits"] <= 0.15
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_preserves_cec_for_direct_appropriation_authorizations() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 13109. Authorization of appropriations. There is "
            "authorized to be appropriated to the Administrator $8,000,000 for "
            "each of the fiscal years 1991, 1992, and 1993 for functions "
            "carried out under this chapter."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.26
    assert rebalanced["deontic.ir"] >= 0.26
    assert rebalanced["TDFOL.prover"] >= 0.18
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.14
    assert rebalanced["zkp.circuits"] <= 0.13
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_projects_flat_direct_appropriation_mix() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.160,
        "TDFOL.prover": 0.149,
        "deontic.ir": 0.173,
        "external_provers.router": 0.122,
        "knowledge_graphs.neo4j_compat": 0.122,
        "modal.frame_logic": 0.144,
        "zkp.circuits": 0.130,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 300ff. For the purpose of carrying out this subchapter, "
            "there are authorized to be appropriated to the Secretary such sums "
            "as may be necessary for each of the fiscal years."
        ),
    )

    assert rebalanced["CEC.native"] > distribution["CEC.native"]
    assert rebalanced["deontic.ir"] > distribution["deontic.ir"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] < distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_projects_effect_on_existing_law_mix() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.156,
        "TDFOL.prover": 0.146,
        "deontic.ir": 0.158,
        "external_provers.router": 0.121,
        "knowledge_graphs.neo4j_compat": 0.138,
        "modal.frame_logic": 0.142,
        "zkp.circuits": 0.140,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "44 U.S.C. 3558. Effect on existing law. Nothing in this subchapter "
            "may be construed as affecting the authority of the President or "
            "the Office of Management and Budget."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.22
    assert rebalanced["CEC.native"] > rebalanced["knowledge_graphs.neo4j_compat"]
    assert rebalanced["TDFOL.prover"] < distribution["TDFOL.prover"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_projects_scaffolded_assignment_authority_mix() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.164,
        "TDFOL.prover": 0.147,
        "deontic.ir": 0.166,
        "external_provers.router": 0.121,
        "knowledge_graphs.neo4j_compat": 0.138,
        "modal.frame_logic": 0.145,
        "zkp.circuits": 0.119,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "22 U.S.C. 968. U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE "
            "CHAPTER 14 - FOREIGN SERVICE SUBCHAPTER V - APPOINTMENTS AND "
            "ASSIGNMENTS Part H - Assignment of Foreign Service personnel. "
            "The Secretary may assign Foreign Service personnel as provided by law."
        ),
    )

    assert rebalanced["CEC.native"] > distribution["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert rebalanced["external_provers.router"] < distribution[
        "external_provers.router"
    ]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_structural_statute_cues_as_frame_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 5677. Transferred Editorial Notes Codification Section 5677 "
            "was editorially reclassified."
        ),
    )

    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.20
    assert rebalanced["CEC.native"] >= rebalanced["TDFOL.prover"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_promotes_cec_for_structural_frame_only_statute_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 19 - CUSTOMS DUTIES CHAPTER 4 - TARIFF ACT OF 1930 "
            "SUBTITLE III - ADMINISTRATIVE PROVISIONS Part III - "
            "Ascertainment, Collection, and Recovery of Duties."
        ),
    )

    assert rebalanced["CEC.native"] > rebalanced["knowledge_graphs.neo4j_compat"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.22
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_preserves_deontic_floor_for_authority_permission_frame() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "The Secretary is authorized and empowered, in the discretion of the "
            "Secretary, to permit temporary entries."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.12
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_boosts_statute_scaffold_frame_lanes() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 34 - CRIME CONTROL 34 U.S.C. United States Code, 2024 "
            "Edition Sec. 50502 - Blue Alert communications network From the "
            "U.S. Government Publishing Office. The Attorney General shall establish "
            "a national network. Editorial Notes Codification Section was formerly "
            "classified. Amendments 2022 effective date."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.27
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.22
    assert rebalanced["TDFOL.prover"] <= 0.180001
    assert rebalanced["zkp.circuits"] <= 0.12
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_floor_for_citation_frame_scaffold_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, 2024 "
            "Edition Title 2 - THE CONGRESS CHAPTER 4 - OFFICERS AND EMPLOYEES "
            "OF SENATE AND HOUSE OF REPRESENTATIVES Sec. 72a-1e - Transferred "
            "From the U.S. Government Publishing Office."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.20
    assert rebalanced["deontic.ir"] > rebalanced["TDFOL.prover"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.21
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_softens_scaffold_heading_bias_to_keep_deontic_lane() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "41 U.S.C. Title 41 - PUBLIC CONTRACTS 41 U.S.C. United States Code, "
            "2024 Edition Title 41 - PUBLIC CONTRACTS Subtitle I - Federal "
            "Procurement Policy Division B - Office of Federal Procurement Policy "
            "CHAPTER 11 - ESTABLISHMENT OF OFFICE AND FUNCTIONS."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.21
    assert rebalanced["deontic.ir"] > rebalanced["knowledge_graphs.neo4j_compat"]
    assert rebalanced["CEC.native"] >= 0.24
    assert rebalanced["TDFOL.prover"] <= 0.19
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_signal_for_scaffolded_norms() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 6 - DOMESTIC SECURITY 6 U.S.C. United States Code, 2024 "
            "Edition Sec. 656 - NET Guard From the U.S. Government Publishing "
            "Office. The Director may establish NET Guard and shall coordinate "
            "implementation. Editorial Notes Codification Section was formerly "
            "classified."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.20
    assert rebalanced["deontic.ir"] > rebalanced["TDFOL.prover"]
    assert rebalanced["CEC.native"] >= 0.27
    assert rebalanced["zkp.circuits"] <= 0.12
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_promotes_scaffolded_repeated_normative_duties() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 5 - GOVERNMENT ORGANIZATION AND EMPLOYEES. From the "
            "U.S. Government Publishing Office. The Secretary shall establish "
            "procedures, shall submit reports, may enter into agreements, shall "
            "coordinate implementation, and may issue guidance. Editorial Notes "
            "Codification Section was formerly classified."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.26
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.18
    assert rebalanced["zkp.circuits"] <= 0.10
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_floor_for_scaffolded_normative_temporal_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.28,
        "TDFOL.prover": 0.23,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.16,
        "zkp.circuits": 0.14,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE. Editorial Notes "
            "Codification and amendments. In accordance with this chapter, the "
            "Secretary shall issue appointments before the effective date."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.30
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_scaffolded_findings_purpose_as_epistemic() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 16 - CONSERVATION. Sec. 6551 - Findings and purpose. "
            "From the U.S. Government Publishing Office. Congress finds that "
            "severe infestation may result in increased fire risk and the purposes "
            "of this section are to require the Secretary to develop an assessment "
            "program. Editorial Notes Codification Section was formerly classified."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.29
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.22
    assert rebalanced["TDFOL.prover"] <= 0.17
    assert rebalanced["deontic.ir"] <= 0.22
    assert rebalanced["zkp.circuits"] <= 0.11
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_for_purposes_deontic_scope_as_normative() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "For purposes of this section, the Secretary shall apply the credit "
            "to covered transfers."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.35
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.11
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_delegation_authority_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Delegation of authority by Comptroller. The powers vested in the "
            "Comptroller may be delegated."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.23
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.20
    assert rebalanced["deontic.ir"] <= 0.21
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_penalty_enforcement_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Criminal penalty enforcement for violations shall be imposed in "
            "accordance with this section."
        ),
    )

    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.19
    assert rebalanced["CEC.native"] >= 0.24
    assert rebalanced["deontic.ir"] <= 0.21
    assert rebalanced["zkp.circuits"] <= 0.15
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_administrative_notice_hearing_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "The Secretary shall provide notice and hearing before issuing a final "
            "agency rulemaking determination under this section."
        ),
    )

    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.20
    assert rebalanced["CEC.native"] >= 0.24
    assert rebalanced["deontic.ir"] <= 0.21
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_on_and_after_date_as_strong_temporal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text="Refunds may be credited to the fund on and after October 11, 2000.",
    )

    assert rebalanced["TDFOL.prover"] >= 0.25
    assert rebalanced["deontic.ir"] <= 0.28
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.14
    assert rebalanced["zkp.circuits"] <= 0.15
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_prioritizes_temporal_lane_for_repealed_scaffold_text() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 16 - CONSERVATION CHAPTER 79 SUBCHAPTER II "
            "Sec. 5933 - Repealed."
        ),
    )

    assert rebalanced["TDFOL.prover"] >= 0.24
    assert rebalanced["TDFOL.prover"] > rebalanced["CEC.native"]
    assert rebalanced["deontic.ir"] <= 0.20
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_repealed_legislative_history_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 23 - HIGHWAYS CHAPTER 2 - OTHER HIGHWAYS Sec. 211 - "
            "Repealed. Pub. L. 100-17, title I, section 133(e)(1), Apr. 2, 1987. "
            "Section, Pub. L. 85-767, Aug. 27, 1958, related to timber access road hearings."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.24
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.21
    assert rebalanced["TDFOL.prover"] <= 0.20
    assert rebalanced["deontic.ir"] <= 0.205
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_floor_for_repealed_history_scaffolds() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 2979. Repealed. Pub. L. 97-35, title VI, section 683(a), "
            "Aug. 13, 1981. Section, Pub. L. 88-452, title VI, section 637, as "
            "added Dec. 23, 1967; amended Jan. 4, 1975; effective date notes."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.17
    assert rebalanced["CEC.native"] >= rebalanced["deontic.ir"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= rebalanced["TDFOL.prover"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_prior_to_archival_notes_as_temporal_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Section 42. Transferred Editorial Notes Codification. Section was "
            "formerly classified to section 536 of title 18 prior to the general "
            "revision and enactment of title 18, by act June 25, 1948."
        ),
    )

    assert rebalanced["TDFOL.prover"] >= 0.30
    assert rebalanced["deontic.ir"] <= 0.16
    assert rebalanced["TDFOL.prover"] > rebalanced["CEC.native"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_authorized_empowered_discretion_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "The Secretary of the Interior is authorized and empowered, in his "
            "discretion in so far as the authorization made herein will permit, "
            "to discover, develop, protect, and regulate water holes."
        ),
    )

    assert rebalanced["deontic.ir"] <= 0.21
    assert rebalanced["CEC.native"] >= 0.26
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.19
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_legislative_assembly_authority_permission_as_frame_signal() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "48 U.S.C. 1408b. Authorization of loans, conveyances, etc., by "
            "government and municipalities. The government of the Virgin Islands, "
            "through its legislative assembly, may assist such authority with cash "
            "donations and services for purposes of carrying out this chapter."
        ),
    )

    assert rebalanced["deontic.ir"] <= 0.22
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.19
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert rebalanced["zkp.circuits"] <= 0.15
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_lane_for_scaffolded_conditional_norms() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 10 - ARMED FORCES Subtitle A - General Military Law "
            "CHAPTER 47 Sec. 856. Provided that the Secretary shall issue rules "
            "if there is good cause."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.32
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.16
    assert rebalanced["zkp.circuits"] <= 0.13
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_governance_cross_reference_as_conditional_normative() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Foreign Claims Settlement Commission of the United States is authorized "
            "to appoint officers and employees in accordance with title 5."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.30
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.14
    assert rebalanced["zkp.circuits"] <= 0.13
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_treats_for_each_quantifier_as_conditional_normative() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "For each individual whose illness serves as the basis for compensation, "
            "the total amount paid under this part shall not exceed the statutory cap."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.33
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.14
    assert rebalanced["zkp.circuits"] <= 0.15
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_separates_scaffolded_temporal_conditionals() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    temporal_conditional = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 2 - THE CONGRESS CHAPTER 3 Sec. 46f-1 - Repealed. "
            "Statutory Notes Effective Date of Repeal provided that the amendments "
            "shall take effect as of noon on January 3, 1956."
        ),
    )
    scaffold_frame = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 34 - CRIME CONTROL. From the U.S. Government "
            "Publishing Office. The Attorney General shall establish a national "
            "network. Editorial Notes Codification Section was formerly "
            "classified. Amendments 2022 effective date."
        ),
    )

    assert temporal_conditional["TDFOL.prover"] >= 0.24
    assert temporal_conditional["deontic.ir"] >= 0.24
    assert temporal_conditional["CEC.native"] >= 0.14
    assert temporal_conditional["TDFOL.prover"] > scaffold_frame["TDFOL.prover"]
    assert temporal_conditional["deontic.ir"] > scaffold_frame["deontic.ir"]
    assert temporal_conditional["CEC.native"] < scaffold_frame["CEC.native"]
    assert (
        temporal_conditional["knowledge_graphs.neo4j_compat"]
        < scaffold_frame["knowledge_graphs.neo4j_compat"]
    )
    assert abs(sum(temporal_conditional.values()) - 1.0) < 1e-9
    assert abs(sum(scaffold_frame.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_promotes_cec_for_sparse_statutory_references() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text="16 U.S.C. 241d.",
    )

    assert rebalanced["CEC.native"] >= 0.27
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.19
    assert rebalanced["deontic.ir"] <= 0.20
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_projects_omitted_codification_to_graph_and_cec() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Sections 8751 to 8755. Omitted Editorial Notes Codification. "
            "Sections 8751 to 8755 were omitted from the Code in view of "
            "termination of United States Synthetic Fuels Corporation. Section "
            "8751 related to issue by Corporation of obligations purchasable "
            "by United States only."
        ),
    )

    assert rebalanced["CEC.native"] >= 0.29
    assert rebalanced["knowledge_graphs.neo4j_compat"] >= 0.21
    assert rebalanced["deontic.ir"] <= 0.24
    assert rebalanced["TDFOL.prover"] <= 0.19
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_deontic_mass_for_scaffolded_temporal_appropriations() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_dense_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.24,
        "TDFOL.prover": 0.22,
        "deontic.ir": 0.19,
        "knowledge_graphs.neo4j_compat": 0.18,
        "zkp.circuits": 0.17,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 42 - THE PUBLIC HEALTH AND WELFARE. Editorial Notes "
            "Codification. Section was formerly classified. Pub. L. 93-644 and "
            "Pub. L. 94-341 authorized appropriations for fiscal years 1975 "
            "through 1977 and the amendment takes effect on and after July 6, 1976."
        ),
    )

    assert rebalanced["deontic.ir"] >= 0.26
    assert rebalanced["deontic.ir"] > rebalanced["CEC.native"]
    assert rebalanced["TDFOL.prover"] >= 0.22
    assert rebalanced["knowledge_graphs.neo4j_compat"] <= 0.16
    assert rebalanced["zkp.circuits"] <= 0.10
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_multiview_bridge_accepts_citation_prefixed_statutory_text() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        "25 U.S.C. 640d-28: The term Secretary means the Secretary of the Interior.",
        bridge_names=("modal_frame_logic", "fol_tdfol", "cec_dcec"),
        document_id="multiview-citation-prefix",
        citation="25 U.S.C. 640d-28",
    )

    assert report.accepted_count == 3
    assert report.acceptance_rate == 1.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0
    fol_records = report.document.views["fol_tdfol.tdfol_formula"].payload["records"]
    assert fol_records
    assert fol_records[0]["parse_ok"] is True
    assert "n_25_usc_640d_28" in fol_records[0]["formula"]


def test_multiview_bridge_accepts_non_normative_statutory_text() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        "15 U.S.C. 1431: Congress finds that unfair methods of competition burden commerce.",
        bridge_names=("deontic_norms", "fol_tdfol", "cec_dcec"),
        document_id="multiview-non-normative",
        citation="15 U.S.C. 1431",
    )

    assert report.accepted_count == 3
    assert report.acceptance_rate == 1.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0
    assert report.reports["deontic_norms"].accepted is True


def test_multiview_bridge_accepts_deontic_soft_pass_with_partial_proof_gate(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview
    from ipfs_datasets_py.logic.bridge.types import ProofGateResult

    def _partial_deontic_gate(_records):
        return ProofGateResult(
            attempted_count=5,
            valid_count=1,
            failed_count=4,
            verified_by=("deontic:fol",),
            details=(
                {
                    "blocking_failed_targets": [
                        "deontic_cec",
                        "deontic_fol",
                        "deontic_temporal_fol",
                        "frame_logic",
                    ],
                    "passed_targets": ["fol"],
                    "source_id": "deontic:test-soft-pass",
                },
            ),
        )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.deontic_norms._proof_gate_from_coverage_records",
        _partial_deontic_gate,
    )

    report = evaluate_legal_ir_multiview(
        "The agency shall publish notice before the permit takes effect.",
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="multiview-deontic-soft-pass",
        citation="Multiview Deontic Soft Pass",
        cache=False,
    )

    deontic_report = report.reports["deontic_norms"]
    assert deontic_report.proof_gate.compiles is False
    assert deontic_report.metadata["proof_gate_soft_pass"] is True
    assert deontic_report.status == "ok"
    assert deontic_report.accepted is True
    assert report.accepted_count == 2
    assert report.acceptance_rate == 1.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0


def test_multiview_bridge_accepts_deontic_soft_pass_with_core_fol_only(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview
    from ipfs_datasets_py.logic.bridge.types import ProofGateResult

    def _partial_deontic_gate(_records):
        return ProofGateResult(
            attempted_count=5,
            valid_count=1,
            failed_count=4,
            verified_by=("deontic:fol",),
            details=(
                {
                    "blocking_failed_targets": [
                        "deontic_cec",
                        "deontic_fol",
                        "deontic_temporal_fol",
                        "frame_logic",
                    ],
                    "passed_targets": ["fol"],
                    "source_id": "deontic:test-core-fol-soft-pass",
                },
            ),
        )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.deontic_norms._proof_gate_from_coverage_records",
        _partial_deontic_gate,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.deontic_norms._coverage_requires_validation",
        lambda _records: False,
    )

    report = evaluate_legal_ir_multiview(
        "22 U.S.C. 4132: The term Secretary means the Secretary of State.",
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="multiview-deontic-core-fol-soft-pass",
        citation="22 U.S.C. 4132",
        cache=False,
    )

    deontic_report = report.reports["deontic_norms"]
    assert deontic_report.proof_gate.compiles is False
    assert deontic_report.metadata["coverage_requires_validation"] is False
    assert deontic_report.metadata["proof_gate_soft_pass"] is True
    assert deontic_report.status == "ok"
    assert deontic_report.accepted is True
    assert report.accepted_count == 2
    assert report.acceptance_rate == 1.0
    assert report.canonical_loss_vector()["legal_ir_multiview_acceptance_loss"] == 0.0


def test_multiview_bridge_forwards_compiler_guidance_to_adapter() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import _evaluate_adapter

    class _Adapter:
        def __init__(self) -> None:
            self.last_kwargs = {}

        def evaluate(self, _text: str, **kwargs):
            self.last_kwargs = dict(kwargs)
            from ipfs_datasets_py.logic.bridge.types import BridgeEvaluationReport
            from ipfs_datasets_py.logic.bridge.types import GraphProjectionResult
            from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
            from ipfs_datasets_py.logic.bridge.types import ProofGateResult
            from ipfs_datasets_py.logic.bridge.types import RoundTripMetrics

            return BridgeEvaluationReport(
                adapter_name="external_prover_router",
                target_component="external_provers.router",
                ir_document=LegalIRDocument(
                    document_id="stub",
                    source_text="stub",
                    normalized_text="stub",
                    source="us_code",
                    citation=None,
                    views={},
                    frame_logic_triples=(),
                    metadata={},
                ),
                round_trip=RoundTripMetrics(),
                proof_gate=ProofGateResult.disabled(reason="stub"),
                graph_projection=GraphProjectionResult(),
                decoded_text="stub",
                status="ok",
                metadata={},
            )

    adapter = _Adapter()
    guidance = {"compiler_guidance_todo_routes": {"repair_multiview_legal_ir_prover_gate": 1}}
    _evaluate_adapter(
        adapter,
        "The agency shall publish notice.",
        citation="5 U.S.C. 552",
        document_id="multiview-guidance-pass-through",
        evaluate_provers=None,
        compiler_guidance=guidance,
        source="us_code",
        source_embedding=None,
    )

    assert adapter.last_kwargs["compiler_guidance"] == guidance


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
