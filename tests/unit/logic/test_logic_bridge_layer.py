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


def test_deontic_phase8_quality_soft_passes_stale_coverage_validation() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import (
        _merge_phase8_validation_from_coverage_records,
    )

    phase8_records = [
        {
            "source_id": "deontic:test",
            "phase8_quality_complete": True,
            "requires_validation": False,
            "coverage_blockers": [],
            "coverage_summary": {
                "phase8_quality_complete": True,
                "requires_validation": False,
                "coverage_blockers": [],
                "reconstruction_slot_loss": {
                    "slot_reconstruction_complete": True,
                },
                "ir_slot_provenance": {
                    "all_checked_slots_grounded": True,
                },
                "prover_syntax_corpus_coverage": {
                    "all_sources_complete": True,
                },
            },
        }
    ]
    stale_coverage_records = [
        {
            "source_id": "deontic:test",
            "requires_validation": True,
            "coverage_blockers": ["legacy_requires_validation"],
            "coverage_summary": {"requires_validation": True},
        }
    ]

    merged = _merge_phase8_validation_from_coverage_records(
        phase8_records,
        stale_coverage_records,
    )

    assert merged[0]["phase8_quality_complete"] is True
    assert merged[0]["requires_validation"] is False
    assert merged[0]["coverage_blockers"] == []
    assert merged[0]["coverage_validation_soft_pass"] is True
    assert merged[0]["coverage_validation_blockers"] == ["legacy_requires_validation"]


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
    assert report.round_trip.to_dict()["ontology_violation_count"] == 0.0
    assert report.total_loss >= 0.0
    assert report.to_dict()["ir_document"]["has_frame_logic"] is True


def test_external_prover_router_uses_syntactic_fallback_when_backends_absent() -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_external_binaries=False,
        enable_native=False,
    )
    report = adapter.evaluate(
        (
            "15 U.S.C. 52. It shall be unlawful for any person to "
            "disseminate any false advertisement."
        ),
        document_id="bridge-layer-external-router-syntactic-fallback",
        citation="15 U.S.C. 52",
        compiler_guidance={"action": "repair_external_prover_router"},
    )

    assert report.status == "ok"
    assert report.proof_gate.compiles is True
    assert report.proof_gate.failure_ratio == 0.0
    assert report.round_trip.extra_losses["external_prover_unavailable_loss"] == 0.0
    assert "native_syntactic" in report.metadata["available_provers"]


def test_external_prover_router_promotes_nested_distillation_bundle() -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
        _router_guidance_signal,
    )

    compiler_guidance = {
        "bundle": (
            '{"program_synthesis_scope":"external_provers",'
            '"source":"compiler_guidance_distillation_v1",'
            '"target_component":"external_provers.router",'
            '"support":1}'
        )
    }

    signal = _router_guidance_signal(compiler_guidance)
    assert signal["prover_gate_hint"] is True
    assert "repair_external_prover_router" in signal["routes"]

    adapter = ExternalProverRouterBridgeAdapter(
        enable_external_binaries=False,
        enable_native=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="bridge-layer-external-router-nested-guidance",
        citation="Bridge Layer Nested Guidance",
        compiler_guidance=compiler_guidance,
    )

    assert report.metadata["compiler_guidance_applied"] is True
    assert report.metadata["compiler_guidance_prover_gate_hint"] is True
    assert report.proof_gate.compiles is True


def test_fol_tdfol_bridge_promotes_json_string_parse_repair_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _Converter:
        def convert(self, _text: str):
            return SimpleNamespace(metadata={})

    adapter = FolTdfolBridgeAdapter(converter=_Converter())
    report = adapter.evaluate(
        (
            "10 U.S.C. 2263: U.S.C. Title 10 - ARMED FORCES "
            "Sec. 2263 - Transfer of funds. The Secretary shall transfer "
            "amounts as provided in this section."
        ),
        document_id="bridge-layer-tdfol-json-evidence",
        citation="10 U.S.C. 2263",
        compiler_guidance={
            "evidence": (
                '{"bridge_failure_name":"tdfol_parse_failure_ratio",'
                '"target_metrics":"tdfol_parse_failure_ratio, '
                'tdfol_no_formula_loss, legal_ir_view_cross_entropy_loss",'
                '"target_file_lane":"tdfol",'
                '"target_view":"TDFOL.prover"}'
            )
        },
    )

    records = report.ir_document.views["tdfol_formula"].payload["records"]
    guidance_records = [
        record
        for record in records
        if str(record["source_id"]).startswith("tdfol:compiler_guidance:")
    ]

    assert report.metadata["compiler_guidance_applied"] is True
    assert guidance_records
    assert all(record["parse_ok"] is True for record in guidance_records)
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


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
        triple["predicate"] == "selected_ontology_term"
        and triple["object"] == "repair_flogic_ontology_constraints"
        for triple in frame_triples
    )
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


def test_modal_frame_logic_bridge_promotes_bundle_only_flogic_guidance() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="bridge-layer-bundle-only-guided-flogic",
        citation="Bridge Layer Bundle Only Guided FLogic",
        compiler_guidance={
            "bundle": {
                "program_synthesis_scope": "frame_logic",
                "route": "repair_flogic_ontology_constraints",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "modal.frame_logic",
            },
        },
        evaluate_provers=False,
    )

    modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"][
        "metadata"
    ]
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]
    selected_terms = {
        triple["object"]
        for triple in frame_triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert modal_metadata["compiler_guidance_legal_ir_target_view_distribution"] == {
        "modal.frame_logic": 1.0
    }
    assert modal_metadata["compiler_guidance_synthesis_focus"] == [
        "repair_flogic_ontology_constraints"
    ]
    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0
    assert "repair_flogic_ontology_constraints" in selected_terms
    assert "modal_frame_logic" in selected_terms
    assert any(
        triple["predicate"] == "modal_frame_logic_ontology_constraint"
        and triple["object"] == "selected_ontology_term:required:satisfied"
        for triple in frame_triples
    )


def test_modal_frame_logic_bridge_infers_flogic_route_from_passing_gap_evidence() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="bridge-layer-gap-guided-flogic",
        citation="Bridge Layer Gap Guided FLogic",
        compiler_guidance={
            "compiler_guidance_attribution": {
                "basis": "sample_records",
                "legal_ir_view_gaps": {
                    "modal_frame_logic:overrepresented": {
                        "count": 5,
                        "quality_gate": "pass",
                    }
                },
                "todo_routes": {},
            },
            "compiler_guidance_legal_ir_view_gaps": {
                "modal_frame_logic:overrepresented": 5,
            },
            "compiler_guidance_quality_gate": "pass",
            "source": "compiler_guidance_distillation_v1",
        },
        evaluate_provers=False,
    )

    modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"][
        "metadata"
    ]
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]
    selected_terms = {
        triple["object"]
        for triple in frame_triples
        if triple["predicate"] == "selected_ontology_term"
    }
    audit_terms = set(modal_metadata["frame_ontology_term_audit_terms"])

    assert modal_metadata["compiler_guidance_synthesis_focus"] == [
        "repair_flogic_ontology_constraints"
    ]
    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0
    assert "repair_flogic_ontology_constraints" in selected_terms
    assert "modal_frame_logic" in selected_terms
    assert "modal_frame_logic" in audit_terms
    assert any(
        triple["predicate"] == "modal_frame_logic_ontology_constraint"
        and triple["object"] == "selected_ontology_term:required:satisfied"
        for triple in frame_triples
    )


def test_modal_frame_logic_bridge_projects_frame_alignment_guidance_routes_to_terms() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    routes = (
        "improve_flogic_frame_alignment",
        "audit_frame_logic_terms",
    )

    for route in routes:
        report = adapter.evaluate(
            (
                "26 U.S.C. 9601: U.S.C. Title 26 - INTERNAL REVENUE CODE "
                "CHAPTER 98 - TRUST FUND CODE Sec. 9601 - Transfer of "
                "amounts. The Secretary shall transfer amounts as provided "
                "in this section."
            ),
            document_id=f"bridge-layer-{route}",
            citation="26 U.S.C. 9601",
            compiler_guidance={
                "bundle": {
                    "route": route,
                    "source": "compiler_guidance_distillation_v1",
                    "target_component": "modal.frame_logic",
                },
                "feature_groups": {
                    "frame_logic": [
                        "legal-ir-view:modal.frame_logic",
                        "legal-ir-view:deontic.ir",
                        "legal-ir-view:TDFOL.prover",
                        "legal-ir-view:knowledge_graphs.neo4j_compat",
                    ],
                },
                "ranked_guidance_features": [
                    {"feature": "legal-ir-view:modal.frame_logic", "score": 1.0},
                ],
            },
            evaluate_provers=False,
        )

        modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"][
            "metadata"
        ]
        audit_terms = set(modal_metadata["frame_ontology_term_audit_terms"])
        high_signal_terms = set(
            modal_metadata["frame_ontology_high_signal_term_audit_terms"]
        )
        frame_triples = report.ir_document.views["frame_logic"].payload["triples"]

        assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0
        assert route in audit_terms
        assert "modal_frame_logic" in high_signal_terms
        assert "deontic_ir" in high_signal_terms
        assert "tdfol_prover" in high_signal_terms
        assert any(
            triple["predicate"] == "audited_ontology_term"
            and triple["object"] == route
            for triple in frame_triples
        )
        assert any(
            triple["predicate"] == "selected_ontology_term"
            and triple["object"] == "deontic_ir"
            for triple in frame_triples
        )
        assert any(
            triple["predicate"] == "selected_ontology_term"
            and triple["object"] == "tdfol_prover"
            for triple in frame_triples
        )


def test_modal_frame_logic_bridge_audits_packet_frame_feature_evidence() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "10 U.S.C. 2263: The Secretary shall provide administrative "
            "notice and records before final disposition."
        ),
        document_id="bridge-layer-packet-frame-features",
        citation="10 U.S.C. 2263",
        compiler_guidance={
            "action": "audit_frame_logic_terms",
            "target_component": "modal.frame_logic",
            "frame_features": [
                "legal-ir-view:deontic.ir",
                "legal-ir-view:modal.frame_logic",
                "quality:bias",
                "quality:symbolic:has-formula",
                "legal-ir-view:modal.autoencoder",
                "legal-ir-view:TDFOL.prover",
                "quality:frame:rank-top",
            ],
            "pipeline_stage_focus": [
                "modal_family_registry",
                "legal_ir_multiview",
            ],
            "primary_pipeline_stage": "modal_family_registry",
            "top_family_features": [
                "legal-ir-view:deontic.ir",
                "legal-ir-view:modal.frame_logic",
                "quality:bias",
                "quality:symbolic:has-formula",
                "legal-ir-view:modal.autoencoder",
                "legal-ir-view:TDFOL.prover",
                "quality:frame:rank-top",
            ],
        },
        evaluate_provers=False,
    )

    modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"][
        "metadata"
    ]
    audit_terms = set(modal_metadata["frame_ontology_term_audit_terms"])
    high_signal_terms = set(
        modal_metadata["frame_ontology_high_signal_term_audit_terms"]
    )
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]
    selected_terms = {
        triple["object"]
        for triple in frame_triples
        if triple["predicate"] == "selected_ontology_term"
    }

    assert report.round_trip.to_dict()["ontology_violation_count"] == 0.0
    assert "audit_frame_logic_terms" in selected_terms
    assert "deontic_ir" in selected_terms
    assert "modal_autoencoder" in selected_terms
    assert "tdfol_prover" in selected_terms
    assert "rank_top" in audit_terms
    assert "symbolic_has_formula" in audit_terms
    assert "modal_family_registry" in high_signal_terms
    assert "legal_ir_multiview" in high_signal_terms


def test_modal_frame_logic_bridge_promotes_graph_projection_guidance_to_neo4j_view() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE CODE "
            "Subtitle A - Income Taxes CHAPTER 1 - NORMAL TAXES AND SURTAXES "
            "Sec. 994 - Regulations. The Secretary shall prescribe such "
            "regulations as may be necessary after notice."
        ),
        document_id="us-code-26-994-guided-graph-projection",
        citation="26 U.S.C. 994",
        compiler_guidance={
            "bundle": {
                "route": "repair_multiview_legal_ir_graph_projection",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "knowledge_graphs.neo4j_compat",
            },
            "source": "compiler_guidance_distillation_v1",
            "evidence": [
                {
                    "citation": "26 U.S.C. 994",
                    "compiler_guidance_route": (
                        "repair_multiview_legal_ir_graph_projection"
                    ),
                    "selected_frame_after": "administrative_notice_hearing",
                    "selected_frame_before": "administrative_notice_hearing",
                }
            ],
        },
        evaluate_provers=False,
    )

    modal_metadata = report.ir_document.views["modal_ir"].payload["modal_ir"]["metadata"]
    frame_triples = report.ir_document.views["frame_logic"].payload["triples"]
    graph_metadata = report.ir_document.views["neo4j_graph_data"].metadata

    assert modal_metadata["compiler_guidance_legal_ir_target_view_distribution"] == {
        "knowledge_graphs.neo4j_compat": 1.0
    }
    assert modal_metadata["compiler_guidance_synthesis_focus"] == [
        "repair_multiview_legal_ir_graph_projection"
    ]
    assert any(
        triple["predicate"] == "learned_legal_ir_target_view"
        and triple["object"] == "knowledge_graphs.neo4j_compat"
        for triple in frame_triples
    )
    assert graph_metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert (
        graph_metadata["canonical_legal_ir_projection_view_distribution"][
            "knowledge_graphs.neo4j_compat"
        ]
        > 0.0
    )


def test_modal_frame_logic_bridge_promotes_action_shaped_graph_guidance_to_neo4j_view() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "25 U.S.C. 305c-1: U.S.C. Title 25 - INDIANS CHAPTER 7A - "
            "PROMOTION OF SOCIAL AND ECONOMIC WELFARE Sec. 305c-1 - "
            "Repealed. Pub. L. 87-23, section 2, Apr. 24, 1961, 75 Stat. 45."
        ),
        document_id="us-code-25-305c-1-action-guided-graph-projection",
        citation="25 U.S.C. 305c-1",
        compiler_guidance={
            "bundle": {
                "action": "repair_multiview_legal_ir_graph_projection",
                "program_synthesis_scope": "knowledge_graphs",
                "target_component": "knowledge_graphs.neo4j_compat",
            },
            "evidence": [
                {
                    "bridge_failure_name": "legal_ir_multiview_graph_failure_penalty",
                    "predicted_view": "knowledge_graphs.neo4j_compat",
                    "target_view": "knowledge_graphs.neo4j_compat",
                }
            ],
        },
        evaluate_provers=False,
    )

    graph_view = report.ir_document.views["neo4j_graph_data"]
    graph_metadata = graph_view.metadata
    graph_relationships = graph_view.payload["relationships"]

    assert any(
        relationship["properties"]["flogic_predicate"]
        == "learned_legal_ir_target_view"
        and relationship["properties"]["flogic_object"]
        == "knowledge_graphs.neo4j_compat"
        for relationship in graph_relationships
    )
    assert graph_metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_metadata["legal_ir_multiview_graph_failure_penalty"] == 0.0
    assert graph_metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_projection_promotes_packet_metadata_guidance_to_alignment_view() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import modal_ir_to_neo4j_graph_data
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
        ModalIRDocument,
        ModalIRFrameLogic,
    )

    modal_ir = ModalIRDocument(
        document_id="us-code-26-994-packet-metadata-projection",
        source="us_code",
        normalized_text=(
            "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE CODE "
            "Sec. 994 - Regulations."
        ),
        frame_logic=ModalIRFrameLogic.from_triples(
            [
                {
                    "subject": "us-code-26-994-packet-metadata-projection",
                    "predicate": "source_id",
                    "object": "us-code-26-994",
                },
                {
                    "subject": "us-code-26-994-packet-metadata-projection",
                    "predicate": "source_text",
                    "object": (
                        "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE "
                        "CODE CHAPTER 1 - NORMAL TAXES AND SURTAXES "
                        "Sec. 994 - Regulations."
                    ),
                },
            ]
        ),
        metadata={
            "bundle": {
                "program_synthesis_scope": "knowledge_graphs",
                "route": "repair_multiview_legal_ir_graph_projection",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "knowledge_graphs.neo4j_compat",
            },
            "evidence": [
                {
                    "bridge_failure_name": (
                        "legal_ir_multiview_graph_failure_penalty"
                    ),
                    "target_view": "knowledge_graphs.neo4j_compat",
                }
            ],
        },
    )

    graph_data = modal_ir_to_neo4j_graph_data(modal_ir)
    graph_relationships = graph_data.to_dict()["relationships"]

    assert any(
        relationship["properties"]["flogic_predicate"]
        == "learned_legal_ir_target_view"
        and relationship["properties"]["flogic_object"]
        == "knowledge_graphs.neo4j_compat"
        for relationship in graph_relationships
    )
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_projection_promotes_packet_view_gap_buckets_to_alignment_view() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import modal_ir_to_neo4j_graph_data
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
        ModalIRDocument,
        ModalIRFrameLogic,
    )

    modal_ir = ModalIRDocument(
        document_id="us-code-43-1312-packet-gap-projection",
        source="us_code",
        normalized_text=(
            "43 U.S.C. 1312: U.S.C. Title 43 - PUBLIC LANDS "
            "Sec. 1312. Seaward boundaries of States."
        ),
        frame_logic=ModalIRFrameLogic.from_triples(
            [
                {
                    "subject": "us-code-43-1312-packet-gap-projection",
                    "predicate": "source_id",
                    "object": "us-code-43-1312",
                },
                {
                    "subject": "us-code-43-1312-packet-gap-projection",
                    "predicate": "source_text",
                    "object": (
                        "43 U.S.C. 1312: U.S.C. Title 43 - PUBLIC LANDS "
                        "CHAPTER 29 - SUBMERGED LANDS Sec. 1312. "
                        "Seaward boundaries of States."
                    ),
                },
            ]
        ),
        metadata={
            "compiler_guidance_legal_ir_view_gaps": {
                "knowledge_graphs_neo4j_compat:underrepresented": 3,
                "modal_frame_logic:overrepresented": 5,
            }
        },
    )

    graph_data = modal_ir_to_neo4j_graph_data(modal_ir)
    graph_relationships = graph_data.to_dict()["relationships"]

    assert any(
        relationship["properties"]["flogic_predicate"]
        == "learned_legal_ir_target_view"
        and relationship["properties"]["flogic_object"]
        == "knowledge_graphs.neo4j_compat"
        for relationship in graph_relationships
    )
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_projection_promotes_nested_packet_metric_scope_guidance() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import modal_ir_to_neo4j_graph_data
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
        ModalIRDocument,
        ModalIRFrameLogic,
    )

    modal_ir = ModalIRDocument(
        document_id="us-code-26-994-packet-attribution-projection",
        source="us_code",
        normalized_text=(
            "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE CODE "
            "Sec. 994 - Regulations."
        ),
        frame_logic=ModalIRFrameLogic.from_triples(
            [
                {
                    "subject": "us-code-26-994-packet-attribution-projection",
                    "predicate": "source_id",
                    "object": "us-code-26-994",
                },
                {
                    "subject": "us-code-26-994-packet-attribution-projection",
                    "predicate": "source_text",
                    "object": (
                        "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE "
                        "CODE Sec. 994 - Regulations."
                    ),
                },
            ]
        ),
        metadata={
            "compiler_guidance_attribution": {
                "semantic_bundle_key": (
                    "compiler-guidance:"
                    "repair_multiview_legal_ir_graph_projection"
                ),
                "target_metrics": (
                    "cross_entropy_loss, legal_ir_multiview_graph_failure_penalty, "
                    "legal_ir_view_cross_entropy_loss"
                ),
                "program_synthesis_scope": "knowledge_graphs",
            }
        },
    )

    graph_data = modal_ir_to_neo4j_graph_data(modal_ir)
    graph_relationships = graph_data.to_dict()["relationships"]

    assert any(
        relationship["properties"]["flogic_predicate"]
        == "learned_legal_ir_target_view"
        and relationship["properties"]["flogic_object"]
        == "knowledge_graphs.neo4j_compat"
        for relationship in graph_relationships
    )
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_data.metadata["legal_ir_multiview_graph_failure_penalty"] == 0.0
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_augments_sparse_legal_sample_text_projection() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-33-763a-2-eb25ca5574fc2e5c",
                "predicate": "sample_id",
                "object": "us-code-33-763a-2-eb25ca5574fc2e5c",
            },
            {
                "subject": "us-code-33-763a-2-eb25ca5574fc2e5c",
                "predicate": "source_text",
                "object": (
                    "U.S.C. Title 33 - NAVIGATION AND NAVIGABLE WATERS "
                    "33 U.S.C. United States Code, 2024 Edition CHAPTER 16 "
                    "- LIGHTHOUSES Sec. 763a-2 - Repealed. "
                    "§763a–2. Repealed."
                ),
            },
        ],
        graph_id="sparse-legal-sample-text-projection",
    )

    triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }
    view_distribution = graph_data.metadata["frame_logic_projection_view_distribution"]

    assert ("citation_canonical", "33 U.S.C. 763a-2") in triples
    assert ("source_id_citation_canonical", "33 U.S.C. 763a-2") in triples
    assert ("source_id_section_component_profile", "mixed") in triples
    assert view_distribution["citation_structure"] >= 1
    assert view_distribution["document_scope"] >= 1
    assert view_distribution["editorial_status"] >= 1
    assert view_distribution["section_structure"] >= 1
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_augments_packet_sample_text_section_markers() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-42-285c-c93bc6252b834d56",
                "predicate": "sample_id",
                "object": "us-code-42-285c-c93bc6252b834d56",
            },
            {
                "subject": "us-code-42-285c-c93bc6252b834d56",
                "predicate": "source_text",
                "object": (
                    "§285c–2. Division Directors for Diabetes, Endocrinology, "
                    "and Metabolic Diseases, Digestive Diseases and Nutrition, "
                    "and Kidney, Urologic, and Hematologic Diseases; functions "
                    "(a)(1) In the Institute there shall be a Division Director."
                ),
            },
        ],
        graph_id="packet-sparse-section-marker-projection",
    )

    triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }
    view_distribution = graph_data.metadata["frame_logic_projection_view_distribution"]

    assert ("source_id_citation_canonical", "42 U.S.C. 285c") in triples
    assert ("section_marker_normalized", "285c-2") in triples
    assert ("section_heading_part_count", "2") in triples
    assert (
        "section_catchline",
        (
            "Division Directors for Diabetes, Endocrinology, and Metabolic "
            "Diseases, Digestive Diseases and Nutrition, and Kidney, Urologic, "
            "and Hematologic Diseases; functions"
        ),
    ) in triples
    assert view_distribution["citation_structure"] >= 1
    assert view_distribution["document_scope"] >= 1
    assert view_distribution["section_structure"] >= 1
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_augments_plural_omitted_section_list_projection() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-30-44-af21ffcc7eedf9f3",
                "predicate": "sample_id",
                "object": "us-code-30-44-af21ffcc7eedf9f3",
            },
            {
                "subject": "us-code-30-44-af21ffcc7eedf9f3",
                "predicate": "source_text",
                "object": (
                    "30 U.S.C. 44: U.S.C. Title 30 - MINERAL LANDS AND "
                    "MINING 30 U.S.C. United States Code, 2024 Edition "
                    "Title 30 - MINERAL LANDS AND MINING CHAPTER 2 - "
                    "MINERAL LANDS AND REGULATIONS IN GENERAL Secs. 44, "
                    "45 - Omitted From the U.S. Government Publishing Office"
                ),
            },
            {
                "subject": "us-code-30-44-af21ffcc7eedf9f3",
                "predicate": "learned_legal_ir_target_view",
                "object": "knowledge_graphs.neo4j_compat",
            },
        ],
        graph_id="packet-plural-omitted-section-list-projection",
    )

    triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }

    assert ("citation_canonical", "30 U.S.C. 44") in triples
    assert ("source_id_citation_canonical", "30 U.S.C. 44") in triples
    assert ("section_marker_component_profile", "list") in triples
    assert ("section_marker_list", "44, 45") in triples
    assert ("section_marker_list_count", "2") in triples
    assert ("section_marker_list_first", "44") in triples
    assert ("section_marker_list_last", "45") in triples
    assert ("section_catchline", "Omitted") in triples
    assert ("status_keyword", "omitted") in triples
    assert (
        "usc_hierarchy_chapter_heading",
        "MINERAL LANDS AND REGULATIONS IN GENERAL",
    ) in triples
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_augments_packet_samples_past_modal_triple_cutoff() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    packet_samples = [
        (
            "us-code-26-994-cbae6d13150585b8",
            "26 U.S.C. 994",
            "Regulations",
            (
                "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE CODE "
                "26 U.S.C. United States Code, 2024 Edition Subtitle A - "
                "Income Taxes CHAPTER 1 - NORMAL TAXES AND SURTAXES "
                "Subchapter N - Tax Based on Income From Sources Within or "
                "Without the United States Sec. 994 - Regulations From the "
                "U.S. Government Publishing Office"
            ),
        ),
        (
            "us-code-24-295a-16dcd47733b0e7d4",
            "24 U.S.C. 295a",
            "Arlington Memorial Amphitheater",
            (
                "24 U.S.C. 295a: U.S.C. Title 24 - HOSPITALS AND ASYLUMS "
                "24 U.S.C. United States Code, 2024 Edition CHAPTER 7 - "
                "NATIONAL CEMETERIES Sec. 295a - Arlington Memorial "
                "Amphitheater From the U.S. Government Publishing Office"
            ),
        ),
    ]

    for sample_id, citation, catchline, source_text in packet_samples:
        triples = [
            {
                "subject": sample_id,
                "predicate": f"modal_feature_{index}",
                "object": f"value_{index}",
            }
            for index in range(20)
        ]
        triples.extend(
            [
                {
                    "subject": sample_id,
                    "predicate": "sample_id",
                    "object": sample_id,
                },
                {
                    "subject": sample_id,
                    "predicate": "source_text",
                    "object": source_text,
                },
                {
                    "subject": sample_id,
                    "predicate": "learned_legal_ir_target_view",
                    "object": "knowledge_graphs.neo4j_compat",
                },
            ]
        )

        graph_data = flogic_triples_to_graph_data(
            triples,
            graph_id=f"{sample_id}:packet-cutoff-projection",
        )
        graph_triples = {
            (
                relationship.properties["flogic_predicate"],
                relationship.properties["flogic_object"],
            )
            for relationship in graph_data.relationships
        }

        assert ("citation_canonical", citation) in graph_triples
        assert ("source_id_citation_canonical", citation) in graph_triples
        assert ("section_catchline", catchline) in graph_triples
        assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
        assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_trims_truncated_gpo_tail_from_packet_catchline() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-25-5126-36d2f002e4c2bb26",
                "predicate": "sample_id",
                "object": "us-code-25-5126-36d2f002e4c2bb26",
            },
            {
                "subject": "us-code-25-5126-36d2f002e4c2bb26",
                "predicate": "source_text",
                "object": (
                    "25 U.S.C. 5126: U.S.C. Title 25 - INDIANS 25 U.S.C. "
                    "United States Code, 2024 Edition Title 25 - INDIANS "
                    "CHAPTER 45 - PROTECTION OF INDIANS AND CONSERVATION "
                    "OF RESOURCES Sec. 5126 - Mandatory application of "
                    "sections 5102 and 5124 From the U.S. Government"
                ),
            },
        ],
        graph_id="packet-truncated-gpo-catchline-projection",
    )

    graph_triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }

    assert (
        "section_catchline",
        "Mandatory application of sections 5102 and 5124",
    ) in graph_triples
    assert (
        "section_heading_tail",
        "Mandatory application of sections 5102 and 5124",
    ) in graph_triples
    assert (
        "section_catchline",
        "Mandatory application of sections 5102 and 5124 From the U.S. Government",
    ) not in graph_triples
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_projects_uscode_hierarchy_and_repealed_catchlines() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-16-4107-13dda804a14c7ced",
                "predicate": "sample_id",
                "object": "us-code-16-4107-13dda804a14c7ced",
            },
            {
                "subject": "us-code-16-4107-13dda804a14c7ced",
                "predicate": "source_text",
                "object": (
                    "16 U.S.C. 4107: U.S.C. Title 16 - CONSERVATION "
                    "16 U.S.C. United States Code, 2024 Edition "
                    "CHAPTER 61 - INTERJURISDICTIONAL FISHERIES "
                    "Sec. 4107 - Repealed. Pub. L. 117-328, div. S, "
                    "title II, section 204(a), Dec. 29, 2022."
                ),
            },
        ],
        graph_id="packet-uscode-hierarchy-projection",
    )

    graph_triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }
    view_distribution = graph_data.metadata["frame_logic_projection_view_distribution"]
    view_by_predicate = {
        relationship.properties["flogic_predicate"]: relationship.properties[
            "frame_logic_projection_view"
        ]
        for relationship in graph_data.relationships
    }

    assert ("usc_hierarchy_title_label", "16") in graph_triples
    assert ("usc_hierarchy_title_heading", "CONSERVATION") in graph_triples
    assert ("usc_hierarchy_chapter_label", "61") in graph_triples
    assert (
        "usc_hierarchy_chapter_heading",
        "INTERJURISDICTIONAL FISHERIES",
    ) in graph_triples
    assert ("section_catchline", "Repealed") in graph_triples
    assert ("section_heading_tail", "Repealed") in graph_triples
    assert ("status_keyword", "repealed") in graph_triples
    assert view_by_predicate["usc_hierarchy_title_label"] == "section_structure"
    assert view_by_predicate["usc_hierarchy_chapter_heading"] == "section_structure"
    assert view_distribution["citation_structure"] >= 1
    assert view_distribution["section_structure"] >= 1
    assert view_distribution["editorial_status"] >= 1
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_projects_packet_legal_ir_hierarchy_samples_as_section_structure() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-10-2515-cb1304b3980adf2a",
                "predicate": "source_text",
                "object": (
                    "10 U.S.C. 2515: U.S.C. Title 10 - ARMED FORCES "
                    "10 U.S.C. United States Code, 2024 Edition Title 10 - "
                    "ARMED FORCES Subtitle A - General Military Law PART IV - "
                    "SERVICE, SUPPLY, AND PROPERTY CHAPTER 148 - REPEALED "
                    "SUBCHAPTER III - REPEALED Sec. 2515 - Repealed."
                ),
            },
            {
                "subject": "us-code-22-290k-5-2914184e2690e597",
                "predicate": "source_text",
                "object": (
                    "22 U.S.C. 290k-5: U.S.C. Title 22 - FOREIGN RELATIONS "
                    "AND INTERCOURSE 22 U.S.C. United States Code, 2024 "
                    "Edition CHAPTER 7 - INTERNATIONAL BUREAUS, CONGRESSES, "
                    "ETC. SUBCHAPTER XXVI - MULTILATERAL INVESTMENT "
                    "GUARANTEE AGENCY Sec. 290k-5 - Jurisdiction."
                ),
            },
        ],
        graph_id="packet-000193-uscode-hierarchy-projection",
    )

    graph_triples = {
        (
            relationship.properties["flogic_subject"],
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }
    views_by_predicate = {
        relationship.properties["flogic_predicate"]: relationship.properties[
            "frame_logic_projection_view"
        ]
        for relationship in graph_data.relationships
    }

    assert (
        "us-code-10-2515-cb1304b3980adf2a",
        "usc_hierarchy_part_heading",
        "SERVICE, SUPPLY, AND PROPERTY",
    ) in graph_triples
    assert (
        "us-code-10-2515-cb1304b3980adf2a",
        "usc_hierarchy_subchapter_heading",
        "REPEALED",
    ) in graph_triples
    assert (
        "us-code-22-290k-5-2914184e2690e597",
        "usc_hierarchy_subchapter_heading",
        "MULTILATERAL INVESTMENT GUARANTEE AGENCY",
    ) in graph_triples
    assert views_by_predicate["usc_hierarchy_part_heading"] == "section_structure"
    assert views_by_predicate["usc_hierarchy_subchapter_heading"] == "section_structure"
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_splits_nested_part_and_subpart_hierarchy_levels() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-12-4583-b48011e8796a83f9",
                "predicate": "sample_id",
                "object": "us-code-12-4583-b48011e8796a83f9",
            },
            {
                "subject": "us-code-12-4583-b48011e8796a83f9",
                "predicate": "source_text",
                "object": (
                    "U.S.C. Title 12 - BANKS AND BANKING 12 U.S.C. "
                    "United States Code, 2024 Edition CHAPTER 46 - "
                    "GOVERNMENT SPONSORED ENTERPRISES SUBCHAPTER I - "
                    "SUPERVISION AND REGULATION OF ENTERPRISES Part B - "
                    "Additional Authorities of the Director subpart 3 - "
                    "enforcement Sec. 4583 - Judicial review"
                ),
            },
        ],
        graph_id="packet-uscode-part-subpart-hierarchy-projection",
    )

    graph_triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }

    assert (
        "usc_hierarchy_subchapter_heading",
        "SUPERVISION AND REGULATION OF ENTERPRISES",
    ) in graph_triples
    assert ("usc_hierarchy_part_label", "B") in graph_triples
    assert (
        "usc_hierarchy_part_heading",
        "Additional Authorities of the Director",
    ) in graph_triples
    assert ("usc_hierarchy_subpart_label", "3") in graph_triples
    assert ("usc_hierarchy_subpart_heading", "enforcement") in graph_triples
    assert (
        "usc_hierarchy_subchapter_heading",
        (
            "SUPERVISION AND REGULATION OF ENTERPRISES Part B - Additional "
            "Authorities of the Director subpart 3 - enforcement"
        ),
    ) not in graph_triples
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_neo4j_compat_splits_uppercase_part_after_subchapter() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-26-9707-9ae6031ba65cd77d",
                "predicate": "sample_id",
                "object": "us-code-26-9707-9ae6031ba65cd77d",
            },
            {
                "subject": "us-code-26-9707-9ae6031ba65cd77d",
                "predicate": "source_text",
                "object": (
                    "U.S.C. Title 26 - INTERNAL REVENUE CODE 26 U.S.C. "
                    "United States Code, 2024 Edition Subtitle J - Coal "
                    "Industry Health Benefits CHAPTER 99 - COAL INDUSTRY "
                    "HEALTH BENEFITS Subchapter B - Combined Benefit Fund "
                    "PART III - ENFORCEMENT Sec. 9707 - Failure to pay premium"
                ),
            },
        ],
        graph_id="packet-uscode-uppercase-part-hierarchy-projection",
    )

    graph_triples = {
        (
            relationship.properties["flogic_predicate"],
            relationship.properties["flogic_object"],
        )
        for relationship in graph_data.relationships
    }

    assert ("usc_hierarchy_subchapter_heading", "Combined Benefit Fund") in graph_triples
    assert ("usc_hierarchy_part_label", "III") in graph_triples
    assert ("usc_hierarchy_part_heading", "ENFORCEMENT") in graph_triples
    assert (
        "usc_hierarchy_subchapter_heading",
        "Combined Benefit Fund PART III - ENFORCEMENT",
    ) not in graph_triples
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


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


def test_modal_frame_logic_bridge_aligns_compact_uscode_heading_scaffolds() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    samples = [
        (
            "25 U.S.C. 2017",
            (
                "25 U.S.C. 2017: U.S.C. Title 25 - INDIANS 25 U.S.C. United "
                "States Code, 2024 Edition Title 25 - INDIANS CHAPTER 22 - "
                "BUREAU OF INDIAN AFFAIRS PROGRAMS SUBCHAPTER II - INDIAN "
                "EDUCATION Sec. 2017 - Annual report"
            ),
        ),
        (
            "50 U.S.C. 1906",
            (
                "50 U.S.C. 1906. U.S.C. Title 50 - WAR AND NATIONAL DEFENSE "
                "United States Code, 2024 Edition CHAPTER 44 - NATIONAL "
                "SECURITY SUBCHAPTER I - COORDINATION FOR NATIONAL SECURITY "
                "Sec. 1906 - Annual report"
            ),
        ),
    ]

    for citation, text in samples:
        report = adapter.evaluate(
            text,
            document_id=citation.lower().replace(" ", "-").replace(".", ""),
            citation=citation,
            evaluate_provers=False,
        )

        assert report.ir_document.has_frame_logic is True
        assert report.round_trip.flogic_similarity_loss < 0.05
        assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0


def test_modal_frame_logic_bridge_aligns_citation_backed_section_digests() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "§285 l . Purpose of Institute The general purpose of the National "
            "Institute of Environmental Health Sciences (in this subpart "
            "referred to as the \"Institute\") is the conduct and support of "
            "research, training, health information dissemination, and other "
            "programs with respect to factors in the environment that affect "
            "human health, directly or indirectly."
        ),
        document_id="42-usc-285-section-digest",
        citation="42 U.S.C. 285",
        evaluate_provers=False,
    )

    assert report.ir_document.has_frame_logic is True
    assert report.round_trip.flogic_similarity_loss < 0.05
    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0


def test_modal_frame_logic_bridge_aligns_citation_backed_frame_digest_variants() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    samples = [
        (
            "54 U.S.C. 102503",
            (
                "§102503. Authority of Secretary (a) In General .-"
                "Notwithstanding other provisions or limitations of law, the "
                "Secretary may perform the functions described in this section "
                "in the manner that the Secretary considers to be in the public "
                "interest."
            ),
            0.05,
        ),
        (
            "10 U.S.C. 8670",
            (
                "§8670. Regular Navy: retired list (a) Officers.-The Secretary "
                "of the Navy may retire an officer of the Regular Navy who is "
                "serving in a grade above lieutenant commander."
            ),
            0.05,
        ),
        (
            "12 U.S.C. 3912",
            (
                "§3912. Definitions For purposes of this chapter, the term "
                "appropriate Federal banking agency has the same meaning as in "
                "section 1813 of this title."
            ),
            0.05,
        ),
        (
            "50 U.S.C. 1231 to 1238",
            (
                "§§1231 to 1238. Repealed. Pub. L. 85-861, §36A, Sept. 2, "
                "1958, 72 Stat. 1569 Section 1231, act Sept. 3, 1954, ch. "
                "1257, title III, §308, 68 Stat. 1155, provided for promotion "
                "to first lieutenant. See section 14301 et seq. of Title 10, "
                "Armed Forces."
            ),
            0.11,
        ),
    ]

    for citation, text, max_loss in samples:
        report = adapter.evaluate(
            text,
            document_id=citation.lower().replace(" ", "-").replace(".", ""),
            citation=citation,
            evaluate_provers=False,
        )

        assert report.ir_document.has_frame_logic is True
        assert report.round_trip.flogic_similarity_loss < max_loss
        assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0


def test_modal_frame_logic_bridge_aligns_packet_citation_status_bodies() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    samples = [
        (
            "7 U.S.C. 3416",
            (
                "7 U.S.C. 3416. Repealed. Pub. L. 102-237, title IV, "
                "section 402(1), Dec. 13, 1991, 105 Stat. 1863."
            ),
        ),
        (
            "12 U.S.C. 1701d",
            (
                "12 U.S.C. 1701d. Repealed. Pub. L. 88-560, title I, "
                "section 101, Sept. 2, 1964, 78 Stat. 769."
            ),
        ),
        (
            "42 U.S.C. 6979b",
            (
                "42 U.S.C. 6979b. Codification The text of section 6979b "
                "of this title was omitted."
            ),
        ),
        (
            "43 U.S.C. 261",
            (
                "43 U.S.C. 261. Canals and appurtenant structures; transfer "
                "of title; power development The Secretary may transfer title "
                "to canals and appurtenant structures."
            ),
        ),
    ]

    for citation, text in samples:
        report = adapter.evaluate(
            text,
            document_id=citation.lower().replace(" ", "-").replace(".", ""),
            citation=citation,
            evaluate_provers=False,
        )

        assert report.ir_document.has_frame_logic is True
        assert report.metadata["statutory_scaffold_loss_calibrated"] is True
        assert report.round_trip.flogic_similarity_loss < 0.05
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


def test_modal_frame_logic_bridge_asserts_projection_ontology_constraints() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "42 U.S.C. 17822 to 17824.: §§17822 to 17824. Repealed. "
            "Pub. L. 111-314, §6, Dec. 18, 2010, 124 Stat. 3444 Section "
            "17822, Pub. L. 110-422, title XI, §1103, Oct. 15, 2008, "
            "122 Stat. 4808, related to astronaut health care."
        ),
        document_id="bridge-layer-repealed-range-ontology-constraints",
        citation="42 U.S.C. 17822 to 17824.",
        evaluate_provers=False,
    )

    triples = report.ir_document.views["frame_logic"].payload["triples"]
    triple_pairs = {
        (triple["predicate"], triple["object"])
        for triple in triples
    }

    assert report.round_trip.extra_losses["ontology_violation_count"] == 0.0
    assert (
        "learned_legal_ir_projection_coverage_complete",
        "true",
    ) in triple_pairs
    assert (
        "learned_legal_ir_required_projection_view",
        "editorial_status",
    ) in triple_pairs
    assert (
        "learned_legal_ir_satisfied_projection_view",
        "editorial_status",
    ) in triple_pairs
    assert (
        "modal_frame_logic_ontology_constraint",
        "editorial_status:required:satisfied",
    ) in triple_pairs
    assert (
        "modal_frame_logic_ontology_constraint",
        "selected_ontology_frame:required:satisfied",
    ) in triple_pairs
    assert (
        "modal_frame_logic_ontology_constraint",
        "selected_ontology_term:required:satisfied",
    ) in triple_pairs
    assert any(
        predicate == "selected_ontology_frame_term_coverage_complete"
        and value == "true"
        for predicate, value in triple_pairs
    )
    assert not any(
        triple["predicate"] == "learned_legal_ir_missing_projection_view"
        for triple in triples
    )


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


def test_modal_frame_logic_bridge_augments_sparse_us_code_graph_projection() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-50-2205",
                "predicate": "source_id",
                "object": "us-code-50-2205.",
            },
            {
                "subject": "us-code-50-2205",
                "predicate": "citation",
                "object": "50 U.S.C. 2205.",
            },
        ],
        graph_id="us-code-50-2205:flogic",
    )

    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }

    assert view_by_predicate["source_id"] == "document_scope"
    assert view_by_predicate["source_id_title"] == "citation_structure"
    assert view_by_predicate["source_id_section_normalized"] == "section_structure"
    assert view_by_predicate["citation_section_normalized"] == "section_structure"
    assert graph_data.metadata["frame_logic_projection_legal_view_required"] == [
        "citation_structure",
        "document_scope",
        "section_structure",
    ]
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_modal_frame_logic_bridge_augments_sparse_us_code_section_ranges() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-50-1231-to-1238",
                "predicate": "source_id",
                "object": "us-code-50-1231 to 1238.-54ddc50447da3288",
            },
            {
                "subject": "us-code-50-1231-to-1238",
                "predicate": "citation",
                "object": "50 U.S.C. 1231 to 1238.",
            },
        ],
        graph_id="us-code-50-1231-to-1238:flogic",
    )

    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }
    objects_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["flogic_object"]
        for rel in graph_data.relationships
    }

    assert view_by_predicate["source_id_section_range"] == "section_structure"
    assert view_by_predicate["source_id_section_range_start"] == "section_structure"
    assert view_by_predicate["source_id_section_range_end"] == "section_structure"
    assert view_by_predicate["citation_section_range"] == "section_structure"
    assert view_by_predicate["citation_section_range_connector"] == "section_structure"
    assert objects_by_predicate["source_id_section_range"] == "1231 to 1238"
    assert objects_by_predicate["source_id_section_range_number_span"] == "7"
    assert objects_by_predicate["citation_section_component_profile"] == "range"
    assert graph_data.metadata["frame_logic_projection_legal_view_required"] == [
        "citation_structure",
        "document_scope",
        "section_structure",
    ]
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_modal_frame_logic_bridge_aligns_sparse_us_code_source_and_citation_views() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-43-617f",
                "predicate": "source_id",
                "object": "us-code-43-617f.-aec77238eacf8e25",
            },
            {
                "subject": "us-code-43-617f",
                "predicate": "citation",
                "object": "43 U.S.C. 617f.",
            },
            {
                "subject": "us-code-33-763a-2",
                "predicate": "source_id",
                "object": "us-code-33-763a-2-eb25ca5574fc2e5c",
            },
            {
                "subject": "us-code-33-763a-2",
                "predicate": "citation",
                "object": "33 U.S.C. 763a-2",
            },
            {
                "subject": "us-code-33-763a-2",
                "predicate": "status_keyword",
                "object": "repealed",
            },
        ],
        graph_id="sparse-us-code-source-citation-alignment:flogic",
    )

    objects_by_subject_predicate = {
        (
            rel.properties["flogic_subject"],
            rel.properties["flogic_predicate"],
        ): rel.properties["flogic_object"]
        for rel in graph_data.relationships
    }
    view_by_predicate = {
        rel.properties["flogic_predicate"]: rel.properties["frame_logic_projection_view"]
        for rel in graph_data.relationships
    }

    assert (
        objects_by_subject_predicate[
            ("us-code-43-617f", "citation_source_id_alignment")
        ]
        == "canonical_match"
    )
    assert (
        objects_by_subject_predicate[
            ("us-code-33-763a-2", "citation_source_id_section_match")
        ]
        == "true"
    )
    assert view_by_predicate["citation_source_id_section_match"] == "section_structure"
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True
    assert graph_data.metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_modal_frame_logic_bridge_labels_legal_projection_view_nodes() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-36-50111",
                "predicate": "source_id",
                "object": "us-code-36-50111-738f0d70f38dacf1",
            },
            {
                "subject": "us-code-36-50111",
                "predicate": "source_id_citation_canonical",
                "object": "36 U.S.C. 50111",
            },
            {
                "subject": "us-code-36-50111",
                "predicate": "source_id_section_normalized",
                "object": "50111",
            },
            {
                "subject": "us-code-36-50111",
                "predicate": "status_keyword",
                "object": "active",
            },
            {
                "subject": "us-code-36-50111",
                "predicate": "learned_legal_ir_target_view",
                "object": "knowledge_graphs.neo4j_compat",
            },
        ],
        graph_id="us-code-36-50111:flogic",
    )

    labels = set(graph_data.schema.node_labels)
    assert {
        "LegalCitationStructure",
        "LegalDocumentScope",
        "LegalEditorialStatus",
        "LegalIRViewAlignment",
        "LegalSectionStructure",
    } <= labels
    assert graph_data.metadata["frame_logic_projection_legal_view_missing"] == []
    assert graph_data.metadata[
        "frame_logic_projection_legal_view_coverage_complete"
    ] is True


def test_modal_frame_logic_bridge_counts_view_alignment_as_graph_projection_evidence() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-42-285",
                "predicate": "source_id",
                "object": "us-code-42-285",
            },
            {
                "subject": "us-code-42-285",
                "predicate": "source_id_citation_canonical",
                "object": "42 U.S.C. 285",
            },
            {
                "subject": "us-code-42-285",
                "predicate": "source_id_section_normalized",
                "object": "285",
            },
            {
                "subject": "us-code-42-285",
                "predicate": "learned_legal_ir_target_view",
                "object": "knowledge_graphs.neo4j_compat",
            },
        ],
        graph_id="us-code-42-285:flogic",
    )

    canonical_distribution = graph_data.metadata[
        "canonical_legal_ir_projection_view_distribution"
    ]

    assert graph_data.metadata["frame_logic_projection_view_distribution"][
        "legal_ir_view_alignment"
    ] == 1
    assert canonical_distribution == {
        "knowledge_graphs.neo4j_compat": 0.8,
        "modal.frame_logic": 0.2,
    }


def test_modal_frame_logic_bridge_requires_editorial_and_alignment_graph_views() -> None:
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    graph_data = flogic_triples_to_graph_data(
        [
            {
                "subject": "us-code-42-4906",
                "predicate": "source_id",
                "object": "us-code-42-4906",
            },
            {
                "subject": "us-code-42-4906",
                "predicate": "source_id_citation_canonical",
                "object": "42 U.S.C. 4906",
            },
            {
                "subject": "us-code-42-4906",
                "predicate": "source_id_section_normalized",
                "object": "4906",
            },
            {
                "subject": "us-code-42-4906",
                "predicate": "status_keyword",
                "object": "omitted",
            },
            {
                "subject": "us-code-42-4906",
                "predicate": "learned_legal_ir_target_view",
                "object": "knowledge_graphs.neo4j_compat",
            },
        ],
        graph_id="us-code-42-4906:flogic",
    )

    assert graph_data.metadata["frame_logic_projection_legal_view_required"] == [
        "citation_structure",
        "document_scope",
        "editorial_status",
        "legal_ir_view_alignment",
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


def test_modal_frame_logic_bridge_exposes_graph_projection_target_metrics() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    report = adapter.evaluate(
        (
            "26 U.S.C. 6681: U.S.C. Title 26 - INTERNAL REVENUE CODE "
            "CHAPTER 68 - ADDITIONS TO THE TAX, ADDITIONAL AMOUNTS, AND "
            "ASSESSABLE PENALTIES Sec. 6681 - Repealed. Pub. L. 94-455, "
            "title XIX, section 1904(b)(10)(D)(i), Oct. 4, 1976."
        ),
        document_id="bridge-layer-target-metric-availability",
        citation="26 U.S.C. 6681",
        evaluate_provers=False,
    )

    target_metric_names = {
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_view_cross_entropy_loss",
        "cross_entropy_loss",
        "cosine_similarity",
        "source_copy_reward_hack_penalty",
        "source_decompiled_text_embedding_cosine_loss",
        "source_decompiled_text_token_loss",
    }
    report_dict = report.to_dict()
    graph_metadata = report_dict["graph_projection"]["metadata"]
    report_metadata = report_dict["metadata"]

    assert target_metric_names <= set(report_metadata)
    assert {
        "legal_ir_multiview_graph_failure_penalty",
        "legal_ir_view_cross_entropy_loss",
    } <= set(graph_metadata)
    assert report_metadata["legal_ir_multiview_graph_failure_penalty"] == 0.0
    assert graph_metadata["legal_ir_multiview_graph_failure_penalty"] == 0.0
    assert report_metadata["legal_ir_view_cross_entropy_loss"] == 0.0
    assert graph_metadata["legal_ir_view_cross_entropy_loss"] == 0.0


def test_bridge_contract_compacts_admin_notice_review_uscode_targets() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    base_distribution = {
        "CEC.native": 0.16,
        "TDFOL.prover": 0.15,
        "deontic.ir": 0.16,
        "external_provers.router": 0.12,
        "knowledge_graphs.neo4j_compat": 0.12,
        "modal.frame_logic": 0.15,
        "zkp.circuits": 0.14,
    }
    text = (
        "25 U.S.C. 1750a: U.S.C. Title 25 - INDIANS CHAPTER 19 - "
        "INDIAN LAND CLAIMS SETTLEMENTS Sec. 1750a - Review and "
        "approval of tribal management contracts. The Chairman shall "
        "provide written notification within 30 days after receipt of "
        "an ordinance or resolution. The Commission may approve the "
        "modification after public notice and opportunity for a hearing."
    )

    compacted = _compact_official_usc_contract_distribution(
        base_distribution,
        text=text,
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["deontic.ir"] > compacted["CEC.native"]
    assert compacted["TDFOL.prover"] > compacted["knowledge_graphs.neo4j_compat"]
    assert abs(sum(compacted.values()) - 1.0) < 1e-12


def test_bridge_contract_promotes_packet_json_bundle_guidance() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compiler_guidance_bridge_contract_metadata,
    )

    metadata = _compiler_guidance_bridge_contract_metadata(
        {
            "bundle": (
                '{"program_synthesis_scope":"bridge",'
                '"route":"repair_multiview_legal_ir_loss",'
                '"source":"compiler_guidance_distillation_v1",'
                '"target_component":"bridge.contracts"}'
            ),
            "target_metrics": (
                "cross_entropy_loss, cosine_similarity, "
                "compiler_ir_cross_entropy_loss, compiler_ir_cosine_similarity, "
                "source_copy_reward_hack_penalty, legal_ir_view_cross_entropy_loss, "
                "legal_ir_multiview_total_loss"
            ),
        }
    )

    target_distribution = metadata[
        "compiler_guidance_bridge_contract_target_distribution"
    ]

    assert metadata["compiler_guidance_bridge_contract_target_lanes"]
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
        "modal.frame_logic",
    }
    assert target_distribution["CEC.native"] > 0.0
    assert target_distribution["TDFOL.prover"] > 0.0
    assert target_distribution["knowledge_graphs.neo4j_compat"] > 0.0
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-12


def test_bridge_contract_promotes_packet_todo_guidance_fields() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH,
        _compiler_guidance_bridge_contract_metadata,
    )

    metadata = _compiler_guidance_bridge_contract_metadata(
        {
            "program_synthesis_scope": "bridge",
            "route": "repair_multiview_legal_ir_loss",
            "samples": "compiler-guidance:repair_multiview_legal_ir_loss",
            "source": "compiler_guidance_distillation_v1",
            "support": 1,
            "target_component": "bridge.contracts",
            "target_metrics": (
                "cross_entropy_loss, cosine_similarity, "
                "compiler_ir_cross_entropy_loss, compiler_ir_cosine_similarity, "
                "source_copy_reward_hack_penalty, legal_ir_view_cross_entropy_loss, "
                "legal_ir_multiview_total_loss"
            ),
            "vector_bundle": "score",
        }
    )

    target_distribution = metadata[
        "compiler_guidance_bridge_contract_target_distribution"
    ]

    assert metadata["compiler_guidance_bridge_contract_evidence_count"] == 0
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
        "modal.frame_logic",
    }
    assert metadata["compiler_guidance_bridge_contract_projection_strength"] > (
        _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH
    )
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-12


def test_bridge_contract_guidance_keeps_packet_120_primary_lanes() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compiler_guidance_bridge_contract_metadata,
    )

    metadata = _compiler_guidance_bridge_contract_metadata(
        {
            "action": "repair_multiview_legal_ir_loss",
            "target_component": "bridge.contracts",
            "target_metrics": (
                "legal_ir_view_cross_entropy_loss, "
                "legal_ir_multiview_cross_entropy_loss, "
                "legal_ir_multiview_total_loss"
            ),
            "evidence": [
                {
                    "bridge_failure_name": "legal_ir_view_cross_entropy_loss",
                    "legal_ir_underrepresented_components": [
                        "deontic.ir",
                        "CEC.native",
                        "TDFOL.prover",
                    ],
                    "legal_ir_component_gaps": {
                        "CEC.native": 0.079236331356,
                        "TDFOL.prover": 0.020231776812,
                        "deontic.ir": 0.172374264327,
                        "knowledge_graphs.neo4j_compat": -0.051654209669,
                        "modal.frame_logic": -0.091066231133,
                    },
                    "pipeline_stage_diagnostics": {
                        "modal_family_target_probability_gap": 0.295535745503,
                        "legal_ir_component_gap_max": 0.172374264327,
                    },
                    "predicted_view": "deontic.ir",
                    "target_component": "bridge.contracts",
                    "target_view": "deontic.ir",
                },
                {
                    "bridge_failure_name": "legal_ir_view_cross_entropy_loss",
                    "legal_ir_underrepresented_components": ["CEC.native"],
                    "legal_ir_component_gaps": {
                        "CEC.native": 0.353279505188,
                        "TDFOL.prover": -0.080527661937,
                        "deontic.ir": -0.012025083173,
                        "knowledge_graphs.neo4j_compat": -0.040480938633,
                        "modal.frame_logic": -0.09114411508,
                    },
                    "pipeline_stage_diagnostics": {
                        "modal_family_target_probability_gap": 0.212526850531,
                        "legal_ir_component_gap_max": 0.353279505188,
                    },
                    "predicted_view": "CEC.native",
                    "target_component": "bridge.contracts",
                    "target_view": "CEC.native",
                },
            ],
        }
    )

    target_distribution = metadata[
        "compiler_guidance_bridge_contract_target_distribution"
    ]

    assert {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
    } <= set(target_distribution)
    assert target_distribution["CEC.native"] > target_distribution["modal.frame_logic"]
    assert target_distribution["deontic.ir"] > target_distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert metadata["compiler_guidance_bridge_contract_projection_strength"] > 0.32


def test_modal_frame_logic_bridge_exports_graph_projection_signal_for_uscode_scaffolds() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("modal_frame_logic")
    samples = [
        (
            "10 U.S.C. 1404",
            (
                "10 U.S.C. 1404: U.S.C. Title 10 - ARMED FORCES 10 U.S.C. "
                "United States Code, 2024 Edition Title 10 - ARMED FORCES "
                "Subtitle A - General Military Law PART II - PERSONNEL "
                "CHAPTER 71 - COMPUTATION OF RETIRED PAY Sec. 1404 - "
                "Applicability of section 8301 of title 5"
            ),
        ),
        (
            "15 U.S.C. 7308",
            (
                "15 U.S.C. 7308: U.S.C. Title 15 - COMMERCE AND TRADE 15 "
                "U.S.C. United States Code, 2024 Edition Title 15 - COMMERCE "
                "AND TRADE CHAPTER 99 - NATIONAL CONSTRUCTION SAFETY TEAM "
                "Sec. 7308 - National Institute of Standards and Technology "
                "actions From the U.S. Government Publishing Office"
            ),
        ),
    ]

    for citation, text in samples:
        report = adapter.evaluate(
            text,
            document_id=citation.lower().replace(" ", "-").replace(".", ""),
            citation=citation,
            evaluate_provers=False,
        )
        graph_view = report.ir_document.views["neo4j_graph_data"]
        metadata = graph_view.metadata
        graph_metadata = report.graph_projection.metadata
        projection_distribution = metadata["frame_logic_projection_view_distribution"]

        expected_signal_count = sum(
            projection_distribution.get(view_name, 0)
            for view_name in (
                "citation_structure",
                "document_scope",
                "frame_link",
                "editorial_status",
                "legal_ir_view_alignment",
                "ontology_term",
                "section_structure",
                "type_assertion",
            )
        )
        assert report.graph_projection.graph_failure_penalty == 0.0
        assert graph_metadata["legal_ir_graph_projection_signal_count"] == (
            expected_signal_count
        )
        assert graph_metadata["legal_ir_graph_projection_signal_count"] > 0
        assert 0.0 < metadata["legal_ir_graph_projection_signal_ratio"] <= 1.0
        assert (
            graph_view.metadata["canonical_legal_ir_projection_view_distribution"][
                "knowledge_graphs.neo4j_compat"
            ]
            > 0.0
        )


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


def test_multiview_contract_compacts_short_repealed_section_ranges() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    compacted = _compact_official_usc_contract_distribution(
        {
            "CEC.native": 0.156,
            "TDFOL.prover": 0.080,
            "deontic.ir": 0.150,
            "external_provers.router": 0.121,
            "knowledge_graphs.neo4j_compat": 0.210,
            "modal.frame_logic": 0.143,
            "zkp.circuits": 0.140,
        },
        text=(
            "§§7705, 7705a. Repealed. Pub. L. 105-47, §4, Oct. 1, "
            "1997, 111 Stat. 1164 Section 7705, Pub. L. 95-124, §6, "
            "Oct. 7, 1977, 91 Stat. 1102; Pub. L. 96-472, title I, "
            "§102(a), Oct. 19, 1980, 94 Stat. 2259; Pub. L. 101-614, "
            "§6, Nov. 16, 1990, 104 Stat. 3236, related to Office of "
            "Science and Technology Policy report."
        ),
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["knowledge_graphs.neo4j_compat"] >= 0.24
    assert compacted["CEC.native"] >= 0.20


def test_multiview_contract_rebalances_sparse_findings_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _rebalance_sparse_contract_distribution,
    )

    distribution = {
        "TDFOL.prover": 0.4318076849457582,
        "deontic.ir": 0.4659705307613379,
        "knowledge_graphs.neo4j_compat": 0.1022217842929039,
    }

    rebalanced = _rebalance_sparse_contract_distribution(
        distribution,
        text=(
            "15 U.S.C. 8001: U.S.C. Title 15 - COMMERCE AND TRADE "
            "United States Code, 2024 Edition Title 15 - COMMERCE AND "
            "TRADE CHAPTER 106 - POOL AND SPA SAFETY Sec. 8001 - "
            "Findings From the U.S. Government Publishing Office. "
            "Congress finds that the safety of children in swimming pools "
            "and spas is affected by drain entrapment hazards and that the "
            "Commission should establish mandatory safety standards."
        ),
    )

    assert rebalanced["TDFOL.prover"] > 0.4318076849457582
    assert rebalanced["deontic.ir"] > 0.31
    assert rebalanced["knowledge_graphs.neo4j_compat"] < 0.2581923150542418
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9
def test_multiview_contract_projects_preemption_contract_norms_to_deontic_lane() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    compacted = _compact_official_usc_contract_distribution(
        {
            "CEC.native": 0.0719943666346951,
            "TDFOL.prover": 0.11237789572983307,
            "deontic.ir": 0.3,
            "external_provers.router": 0.09036071666485554,
            "knowledge_graphs.neo4j_compat": 0.17457727075623553,
            "modal.frame_logic": 0.13592310905141208,
            "zkp.circuits": 0.11476664116296861,
        },
        text=(
            "U.S.C. Title 15 - COMMERCE AND TRADE 15 U.S.C. United States "
            "Code, 2024 Edition CHAPTER 108 - STATE-BASED INSURANCE REFORM "
            "SUBCHAPTER II - REINSURANCE Sec. 8221 - Regulation of credit for "
            "reinsurance and reinsurance agreements From the U.S. Government "
            "Publishing Office. If the State of domicile of a ceding insurer "
            "recognizes credit for reinsurance, then no other State may deny "
            "such credit for reinsurance. State laws are preempted to the "
            "extent that they require a State's law to govern the reinsurance "
            "contract or disputes arising from the reinsurance contract."
        ),
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["deontic.ir"] >= 0.49
    assert compacted["TDFOL.prover"] <= 0.18


def test_multiview_contract_keeps_references_repeal_crossrefs_in_graph_lane() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
    )

    compacted = _compact_official_usc_contract_distribution(
        {
            "CEC.native": 0.2041096602559515,
            "TDFOL.prover": 0.11704947439287061,
            "deontic.ir": 0.11366427927167234,
            "external_provers.router": 0.09017598060619479,
            "knowledge_graphs.neo4j_compat": 0.2248034847486921,
            "modal.frame_logic": 0.13543047956165008,
            "zkp.circuits": 0.11476664116296864,
        },
        text=(
            "U.S.C. Title 13 - CENSUS 13 U.S.C. United States Code, 2024 "
            "Edition CHAPTER 1 - ADMINISTRATION Sec. 15 - Leases for 1980 "
            "decennial census From the U.S. Government Publishing Office. "
            "The 15 percent limitation contained in section 322 of the Act "
            "of June 30, 1932 shall not apply to leases entered into by the "
            "Secretary for the purpose of carrying out the 1980 decennial "
            "census, but no lease may be entered into for such purpose at a "
            "rental in excess of 105 percent of the appraised fair annual "
            "rental. Editorial Notes References in Text Section 322 of the "
            "Act of June 30, 1932, referred to in text, was repealed by Pub. "
            "L. 100-678. Amendments Statutory Notes and Related Subsidiaries "
            "Effective Date of 2003 Amendment."
        ),
    )

    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["knowledge_graphs.neo4j_compat"] >= 0.28
    assert compacted["deontic.ir"] <= 0.24


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


def test_deontic_bridge_falls_back_to_parser_for_failed_definition_conversion() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    class _FailedConversionResult:
        success = False
        metadata = {}
        output = None

    class _FailedConverter:
        @staticmethod
        def convert(_text: str):
            return _FailedConversionResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FailedConverter())
    report = adapter.evaluate(
        "22 U.S.C. 4132: The term Secretary means the Secretary of State.",
        document_id="deontic-bridge-definition-fallback",
        citation="22 U.S.C. 4132",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    coverage_record = report.ir_document.views["deontic_prover_syntax"].payload[
        "records"
    ][0]

    assert norm["norm_type"] == "definition"
    assert norm["actor"] == "Secretary"
    assert report.proof_gate.failure_ratio == 0.0
    assert report.proof_gate.valid_count == 5
    assert coverage_record["formal_syntax_valid"] is True
    assert coverage_record["coverage_blockers"] == []
    assert (
        report.round_trip.extra_losses["deontic_decoder_slot_loss"]
        == 0.0
    )


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


def test_deontic_bridge_recovers_purpose_clause_as_quality_complete_ir() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        (
            "42 U.S.C. 285: Purpose of Institute. The general purpose of the "
            "National Institute of Environmental Health Sciences (in this subpart "
            "referred to as the Institute) is the conduct and support of research, "
            "training, health information dissemination, and other programs with "
            "respect to factors in the environment that affect human health."
        ),
        document_id="deontic-bridge-purpose-clause",
        citation="42 U.S.C. 285",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    formula = report.ir_document.views["deontic_formula_records"].payload[
        "records"
    ][0]["formula"]
    slot_summary = report.ir_document.views[
        "deontic_reconstruction_slot_loss"
    ].payload["summary"]
    phase8_summary = report.ir_document.views["deontic_phase8_quality"].payload[
        "summary"
    ]

    assert norm["norm_type"] == "purpose"
    assert norm["modality"] == "PURP"
    assert norm["actor"].startswith("National Institute")
    assert formula.startswith("Purpose(")
    assert slot_summary["required_slots"] == ["actor", "action"]
    assert slot_summary["slot_reconstruction_complete"] is True
    assert phase8_summary["phase8_quality_complete"] is True
    assert phase8_summary["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert (
        report.round_trip.extra_losses["deontic_quality_requires_validation_loss"]
        == 0.0
    )


def test_deontic_bridge_recovers_us_code_section_status_lifecycle_notes() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    samples = [
        (
            "§§7705, 7705a. Repealed. Pub. L. 105-47, §4, Oct. 1, 1997, 111 Stat. 1164",
            "Repealed",
        ),
        (
            "§4906. Omitted Editorial Notes Codification Section, Pub. L. 92-574, "
            "§7(a), Oct. 27, 1972, 86 Stat. 1239, related to a study by the "
            "Administrator of the adequacy of noise controls.",
            "Omitted",
        ),
    ]

    for text, predicate in samples:
        report = adapter.evaluate(
            text,
            document_id=f"deontic-bridge-section-status-{predicate.lower()}",
            citation=f"Deontic Bridge Section Status {predicate}",
        )

        norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
        formula = report.ir_document.views["deontic_formula_records"].payload[
            "records"
        ][0]["formula"]
        slot_summary = report.ir_document.views[
            "deontic_reconstruction_slot_loss"
        ].payload["summary"]
        phase8_summary = report.ir_document.views["deontic_phase8_quality"].payload[
            "summary"
        ]

        assert norm["norm_type"] == "instrument_lifecycle"
        assert norm["modality"] == "LIFE"
        assert norm["actor"]
        assert norm["action"].startswith(predicate.lower())
        assert formula.startswith(f"{predicate}(")
        assert slot_summary["slot_reconstruction_complete"] is True
        assert phase8_summary["phase8_quality_complete"] is True
        assert phase8_summary["requires_validation"] is False
        assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
        assert (
            report.round_trip.extra_losses["deontic_quality_requires_validation_loss"]
            == 0.0
        )


def test_deontic_bridge_grounds_lifecycle_actor_from_us_code_citation() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        "33 U.S.C. 763a-2 Repealed. Pub. L. 117-263, div. K, title CXVIII.",
        document_id="deontic-bridge-lifecycle-citation-actor",
        citation="33 U.S.C. 763a-2",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]
    provenance = phase8_record["coverage_summary"]["ir_slot_provenance"]

    assert norm["norm_type"] == "instrument_lifecycle"
    assert norm["actor"] == "33 U.S.C. 763a-2"
    assert "actor" in provenance["grounded_slots"]
    assert "ungrounded_ir_slot_provenance:actor" not in phase8_record[
        "coverage_blockers"
    ]
    assert phase8_record["requires_validation"] is False
    assert (
        report.round_trip.extra_losses["deontic_quality_requires_validation_loss"]
        == 0.0
    )


def test_deontic_bridge_recovers_savings_preservation_clause() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        (
            "42 U.S.C. 18726. Savings provision. Nothing in this part affects "
            "the authority, existing on the day before November 15, 2021, of "
            "any other Federal department or agency, including the authority "
            "provided to the Secretary of Homeland Security."
        ),
        document_id="deontic-bridge-savings-preservation",
        citation="42 U.S.C. 18726",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    slot_summary = report.ir_document.views[
        "deontic_reconstruction_slot_loss"
    ].payload["summary"]
    phase8_summary = report.ir_document.views["deontic_phase8_quality"].payload[
        "summary"
    ]

    assert norm["norm_type"] == "exemption"
    assert norm["modality"] == "EXEMPT"
    assert norm["actor"] == "other Federal department or agency"
    assert norm["action"] == "preserve authority from this part"
    assert slot_summary["slot_reconstruction_complete"] is True
    assert phase8_summary["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert (
        report.round_trip.extra_losses["deontic_quality_requires_validation_loss"]
        == 0.0
    )


def test_deontic_bridge_classifies_no_subject_may_as_prohibition() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("deontic_norms")
    report = adapter.evaluate(
        (
            "If the State recognizes credit for reinsurance, then no other "
            "State may deny credit for reinsurance."
        ),
        document_id="deontic-bridge-no-subject-may-prohibition",
        citation="Deontic Bridge No Subject May Prohibition",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    formula = report.ir_document.views["deontic_formula_records"].payload[
        "records"
    ][0]["formula"]

    assert norm["norm_type"] == "prohibition"
    assert norm["modality"] == "F"
    assert norm["actor"] == "other State"
    assert norm["action"] == "deny credit for reinsurance"
    assert formula.startswith("F(")
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert (
        report.round_trip.extra_losses["deontic_quality_requires_validation_loss"]
        == 0.0
    )


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


def test_deontic_bridge_fills_reduced_parser_rows_from_legal_norm_ir_rows() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall publish notice."
    source_id = "legacy:deontic:legal-norm-ir-sibling"

    class _FakeResult:
        success = True
        metadata = {
            "parser_elements": [
                {
                    "schema_version": "legal_norm_ir-v1",
                    "source_id": source_id,
                    "canonical_citation": "20 U.S.C. 107b-3",
                    "norm_type": "obligation",
                    "subject": [],
                    "action": [],
                    "modality": "",
                    "text": source_text,
                    "support_text": source_text,
                    "support_span": [0, len(source_text)],
                    "promotable_to_theorem": True,
                    "export_readiness": {"blockers": []},
                }
            ],
            "legal_norm_irs": [
                {
                    "schema_version": "legal_norm_ir-v1",
                    "source_id": source_id,
                    "canonical_citation": "20 U.S.C. 107b-3",
                    "norm_type": "obligation",
                    "modality": "O",
                    "actor": "Secretary",
                    "action": "publish notice",
                    "source_text": source_text,
                    "support_text": source_text,
                    "source_span": [0, len(source_text)],
                    "support_span": [0, len(source_text)],
                    "field_spans": {
                        "subject": [4, 13],
                        "modality": [14, 19],
                        "action": [20, 34],
                    },
                    "quality": {
                        "promotable_to_theorem": True,
                        "parser_warnings": [],
                        "export_readiness": {"blockers": []},
                    },
                    "export_readiness": {"blockers": []},
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
        document_id="deontic-bridge-legal-norm-ir-sibling",
        citation="Deontic Bridge LegalNormIR Sibling",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    decoder_record = report.ir_document.views["deontic_decoder_reconstructions"].payload[
        "records"
    ][0]
    slot_loss = report.ir_document.views["deontic_reconstruction_slot_loss"].payload[
        "summary"
    ]

    assert norm["actor"] == "Secretary"
    assert norm["modality"] == "O"
    assert norm["action"] == "publish notice"
    assert decoder_record["missing_slots"] == []
    assert decoder_record["requires_validation"] is False
    assert slot_loss["slot_reconstruction_complete"] is True
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0


def test_deontic_bridge_promotes_passed_guidance_ir_into_reduced_parser_rows() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Secretary shall publish notice."
    source_id = "legacy:deontic:guidance-reduced-row"

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": source_id,
                "canonical_citation": "20 U.S.C. 107b-3",
                "norm_type": "obligation",
                "subject": [],
                "action": [],
                "deontic_operator": "",
                "text": source_text,
                "source_text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-guidance-reduced-row",
        citation="Deontic Bridge Guidance Reduced Row",
        compiler_guidance={
            "compiler_guidance_route": "repair_deontic_bridge_quality_gate",
            "compiler_guidance_quality_gate": "pass",
            "target_component": "deontic.ir",
            "metric_sample_payloads": [
                {
                    "sample_id": source_id,
                    "target_view": "deontic.ir",
                    "quality_gate": "pass",
                    "legal_norm_ir": {
                        "actor": "Secretary",
                        "modality": "O",
                        "norm_type": "obligation",
                        "action": "publish notice",
                        "source_text": source_text,
                        "support_text": source_text,
                        "support_span": [0, len(source_text)],
                        "field_spans": {
                            "subject": [4, 13],
                            "modality": [14, 19],
                            "action": [20, 34],
                        },
                    },
                }
            ],
        },
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    legal_frame = norm["legal_frame"]
    summary = report.ir_document.views["deontic_reconstruction_slot_loss"].payload[
        "summary"
    ]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]

    assert report.metadata["compiler_guidance_applied"] is True
    assert norm["actor"] == "Secretary"
    assert norm["modality"] == "O"
    assert norm["action"] == "publish notice"
    assert legal_frame["compiler_guidance_quality_gate"] == "pass"
    assert legal_frame["compiler_guidance_target_view"] == "deontic.ir"
    assert summary["missing_required_slots"] == []
    assert summary["slot_reconstruction_complete"] is True
    assert phase8_record["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_recovers_purpose_slots_from_nested_legal_frame() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = (
        "The purpose of the clearinghouse is to provide information on "
        "methamphetamine education and prevention."
    )
    actor = "clearinghouse"
    action = "provide information on methamphetamine education and prevention"

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:nested-purpose-frame",
                "canonical_citation": "21 U.S.C. 2013",
                "norm_type": "",
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
                        "text": source_text,
                        "support_text": source_text,
                        "support_span": [0, len(source_text)],
                        "legal_frame": {
                            "norm_type": "purpose",
                            "modality": "PURP",
                            "subject": [actor],
                            "purpose_details": [
                                {
                                    "purpose_text": action,
                                    "span": [
                                        source_text.index(action),
                                        source_text.index(action) + len(action),
                                    ],
                                }
                            ],
                            "field_spans": {
                                "subject": [
                                    source_text.index(actor),
                                    source_text.index(actor) + len(actor),
                                ],
                                "action": [
                                    source_text.index(action),
                                    source_text.index(action) + len(action),
                                ],
                            },
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
        document_id="deontic-bridge-nested-purpose-frame",
        citation="21 U.S.C. 2013",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    summary = report.ir_document.views["deontic_reconstruction_slot_loss"].payload[
        "summary"
    ]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]

    assert norm["norm_type"] == "purpose"
    assert norm["modality"] == "PURP"
    assert norm["actor"] == actor
    assert norm["action"] == action
    assert summary["missing_required_slots"] == []
    assert summary["slot_reconstruction_complete"] is True
    assert phase8_record["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_scopes_migrated_detail_slots_to_norm_support_span() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = (
        "Notwithstanding another section, no permit shall issue unless approved. "
        "Historical notes and cross references. "
        "The Secretary shall publish notice."
    )
    support_text = "The Secretary shall publish notice."
    support_start = source_text.index(support_text)
    support_end = support_start + len(support_text)

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:scoped-detail-slots",
                "canonical_citation": "42 U.S.C. 1591",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": source_text,
                "source_text": source_text,
                "support_text": support_text,
                "support_span": [support_start, support_end],
                "norm_type": "obligation",
                "promotable_to_theorem": False,
                "parser_warnings": [
                    "enumerated_clause_requires_item_level_review",
                    "cross_reference_requires_resolution",
                    "exception_requires_scope_review",
                    "override_clause_requires_precedence_review",
                    "llm_repair_required",
                ],
                "export_readiness": {
                    "blockers": [
                        "enumerated_clause_requires_item_level_review",
                        "cross_reference_requires_resolution",
                        "exception_requires_scope_review",
                        "override_clause_requires_precedence_review",
                        "llm_repair_required",
                    ]
                },
                "field_spans": {
                    "subject": [support_start + 4, support_start + 13],
                    "modality": [support_start + 14, support_start + 19],
                    "action": [support_start + 20, support_start + 34],
                },
                "exception_details": [
                    {
                        "value": "approved",
                        "span": [58, 66],
                        "clause_span": [51, 67],
                    }
                ],
                "cross_reference_details": [
                    {
                        "value": "another section",
                        "span": [18, 33],
                    }
                ],
                "override_clause_details": [
                    {
                        "value": "Notwithstanding another section",
                        "span": [0, 33],
                    }
                ],
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id="deontic-bridge-scoped-detail-slots",
        citation="Deontic Bridge Scoped Detail Slots",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    formula_record = report.ir_document.views["deontic_formula_records"].payload[
        "records"
    ][0]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]

    assert norm["exceptions"] == []
    assert norm["cross_references"] == []
    assert norm["overrides"] == []
    assert "exception_requires_scope_review" not in formula_record["blockers"]
    assert "cross_reference_requires_resolution" not in formula_record["blockers"]
    assert "override_clause_requires_precedence_review" not in formula_record["blockers"]
    assert formula_record["proof_ready"] is True
    assert formula_record["requires_validation"] is False
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


def test_deontic_bridge_uses_persisted_formula_readiness_for_decoder_validation() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    support_text = (
        "The Secretary shall publish notice except as provided in section 552."
    )
    actor_start = support_text.index("Secretary")
    modality_start = support_text.index("shall")
    action_start = support_text.index("publish")
    exception_start = support_text.index("except")
    reference_start = support_text.index("section 552")

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:persisted-readiness-decoder",
                "canonical_citation": "5 U.S.C. 552",
                "deontic_operator": "shall",
                "subject": ["Secretary"],
                "action": ["publish notice"],
                "text": support_text,
                "source_text": support_text,
                "support_text": support_text,
                "support_span": [0, len(support_text)],
                "norm_type": "obligation",
                "promotable_to_theorem": False,
                "parser_warnings": [
                    "cross_reference_requires_resolution",
                    "exception_requires_scope_review",
                ],
                "export_readiness": {
                    "blockers": [
                        "cross_reference_requires_resolution",
                        "exception_requires_scope_review",
                    ],
                    "formula_proof_ready": True,
                    "formula_requires_validation": False,
                    "formula_repair_required": False,
                    "deterministic_resolution": {
                        "type": "resolved_same_document_reference_exception",
                        "resolved_blockers": [
                            "cross_reference_requires_resolution",
                            "exception_requires_scope_review",
                        ],
                    },
                },
                "field_spans": {
                    "subject": [actor_start, actor_start + len("Secretary")],
                    "modality": [modality_start, modality_start + len("shall")],
                    "action": [action_start, action_start + len("publish notice")],
                },
                "exception_details": [
                    {
                        "value": "except as provided in section 552",
                        "span": [exception_start, len(support_text) - 1],
                    }
                ],
                "cross_reference_details": [
                    {
                        "value": "section 552",
                        "span": [reference_start, reference_start + len("section 552")],
                    }
                ],
            }
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        support_text,
        document_id="deontic-bridge-persisted-readiness-decoder",
        citation="Deontic Bridge Persisted Readiness Decoder",
    )

    decoder_record = report.ir_document.views["deontic_decoder_reconstructions"].payload[
        "records"
    ][0]
    formula_record = report.ir_document.views["deontic_formula_records"].payload[
        "records"
    ][0]
    phase8_record = report.ir_document.views["deontic_phase8_quality"].payload[
        "records"
    ][0]

    assert formula_record["requires_validation"] is False
    assert decoder_record["missing_slots"] == []
    assert decoder_record["requires_validation"] is False
    assert decoder_record["decoder_validation_resolution"]["type"] == (
        "formula_deterministic_readiness"
    )
    assert phase8_record["requires_validation"] is False
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
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


def test_deontic_bridge_promotes_compiler_guidance_frame_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_id = "us-code-24-295a-16dcd47733b0e7d4"

    class _FakeResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "schema_version": "legal_norm_ir-v1",
                    "source_id": source_id,
                    "canonical_citation": "24 U.S.C. 295a",
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
                }
            ],
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        "24 U.S.C. 295a: The Secretary shall publish notice.",
        document_id=source_id,
        citation="24 U.S.C. 295a",
        compiler_guidance={
            "compiler_guidance_route": "repair_deontic_bridge_quality_gate",
            "target_component": "deontic.ir",
            "evidence": [
                {
                    "citation": "24 U.S.C. 295a",
                    "evidence_rank": 1,
                    "sample_id": source_id,
                    "selected_frame_after": "administrative_notice_hearing",
                }
            ],
        },
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    legal_frame = norm["legal_frame"]
    assert legal_frame["selected_frame"] == "administrative_notice_hearing"
    assert legal_frame["selected_frame_source"] == (
        "compiler_guidance.evidence.selected_frame_after"
    )
    assert legal_frame["compiler_guidance_source"] == (
        "repair_deontic_bridge_quality_gate"
    )
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.ir_document.metadata["compiler_guidance_applied"] is True
    assert any(
        triple["predicate"] == "selected_frame"
        and triple["object"] == "administrative_notice_hearing"
        for triple in report.ir_document.frame_logic_triples
    )
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_trims_uscode_catchline_from_modal_actor() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = (
        "Assistance to the Republic of the Philippines The President is "
        "authorized to assist the Republic of the Philippines."
    )
    actor_start = source_text.index("The President")
    modal_start = source_text.index("is authorized")
    action_start = source_text.index("assist the Republic")

    class _FakeResult:
        success = True
        metadata = {
            "parser_element": {
                "schema_version": "legal_norm_ir-v1",
                "source_id": "legacy:deontic:catchline-actor",
                "canonical_citation": "38 U.S.C. 1731",
                "deontic_operator": "authorized",
                "norm_type": "permission",
                "subject": ["Philippines The President"],
                "action": ["assist the Republic of the Philippines"],
                "text": source_text,
                "source_text": source_text,
                "support_text": source_text,
                "support_span": [0, len(source_text)],
                "promotable_to_theorem": True,
                "export_readiness": {"blockers": []},
                "field_spans": {
                    "subject": [
                        source_text.index("Philippines The President"),
                        actor_start + len("The President"),
                    ],
                    "modal": [modal_start, modal_start + len("is authorized")],
                    "action": [
                        action_start,
                        action_start + len("assist the Republic of the Philippines"),
                    ],
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
        document_id="deontic-bridge-catchline-actor",
        citation="38 U.S.C. 1731",
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    decoder_record = report.ir_document.views["deontic_decoder_reconstructions"].payload[
        "records"
    ][0]
    actor_phrase = next(
        phrase
        for phrase in decoder_record["phrase_provenance"]
        if phrase["slot"] == "actor"
    )

    assert norm["actor"] == "The President"
    assert actor_phrase["text"] == "The President"
    assert actor_phrase["spans"] == [[actor_start, actor_start + len("The President")]]
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


def test_deontic_bridge_promotes_packet_action_guidance_to_ir_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter

    source_text = "The Chief Administrative Officer may collect fees."
    source_id = "us-code-2-5541-462165e82b6b68ce"

    class _FakeResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "schema_version": "legal_norm_ir-v1",
                    "source_id": source_id,
                    "canonical_citation": "2 U.S.C. 5541",
                    "norm_type": "permission",
                    "modality": "P",
                    "actor": "Chief Administrative Officer",
                    "action": "collect fees",
                    "source_text": source_text,
                    "support_text": source_text,
                    "source_span": [0, len(source_text)],
                    "support_span": [0, len(source_text)],
                    "field_spans": {
                        "subject": [4, 32],
                        "modality": [33, 36],
                        "action": [37, 49],
                    },
                    "quality": {
                        "promotable_to_theorem": True,
                        "parser_warnings": [],
                        "export_readiness": {"blockers": []},
                    },
                    "export_readiness": {"blockers": []},
                }
            ]
        }

    class _FakeConverter:
        @staticmethod
        def convert(_text: str):
            return _FakeResult()

    adapter = DeonticNormsBridgeAdapter(converter=_FakeConverter())
    report = adapter.evaluate(
        source_text,
        document_id=source_id,
        citation="2 U.S.C. 5541",
        compiler_guidance={
            "compiler_guidance_quality_gate": "pass",
            "bundle": {
                "action": "repair_deontic_bridge_quality_gate",
                "target_component": "deontic.ir",
            },
            "evidence": [
                {
                    "sample_id": source_id,
                    "quality_gate": "pass",
                    "target_view": "deontic.ir",
                    "predicted_view": "deontic.ir",
                    "legal_ir_underrepresented_components": [
                        "deontic.ir",
                        "TDFOL.prover",
                    ],
                    "legal_ir_component_gaps": {
                        "deontic.ir": 0.138041708115,
                        "TDFOL.prover": 0.041522358337,
                    },
                }
            ],
        },
    )

    norm = report.ir_document.views["deontic_ir"].payload["norms"][0]
    legal_frame = norm["legal_frame"]
    assert legal_frame["compiler_guidance_target_view"] == "deontic.ir"
    assert legal_frame["compiler_guidance_quality_gate"] == "pass"
    assert legal_frame["compiler_guidance_legal_ir_underrepresented_components"] == [
        "deontic.ir",
        "TDFOL.prover",
    ]
    assert report.metadata["compiler_guidance_applied"] is True
    assert any(
        triple["predicate"] == "compiler_guidance_target_view"
        and triple["object"] == "deontic.ir"
        for triple in report.ir_document.frame_logic_triples
    )
    assert any(
        triple["predicate"]
        == "compiler_guidance_legal_ir_underrepresented_component"
        and triple["object"] == "deontic.ir"
        for triple in report.ir_document.frame_logic_triples
    )
    assert report.round_trip.extra_losses["deontic_decoder_slot_loss"] == 0.0
    assert report.round_trip.extra_losses["deontic_quality_requires_validation_loss"] == 0.0


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
    from ipfs_datasets_py.logic.bridge import (
        load_logic_bridge_adapter,
        logic_bridge_spec,
    )

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
    assert report.round_trip.cross_entropy_loss >= 0.0
    assert {
        "cosine_similarity",
        "cross_entropy_loss",
        "legal_ir_view_cross_entropy_loss",
        "source_copy_reward_hack_penalty",
        "tdfol_no_formula_loss",
        "tdfol_parse_failure_ratio",
    } <= set(logic_bridge_spec("fol_tdfol").loss_names)
    assert "legal_ir_view_cross_entropy_loss" in report.round_trip.extra_losses
    assert "source_copy_reward_hack_penalty" in report.round_trip.extra_losses


def test_tdfol_bridge_keeps_shall_clause_before_permit_as_obligation() -> None:
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
        "The agency shall publish notice before the permit takes effect.",
        document_id="tdfol-bridge-permit-object",
    )

    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["formula"].startswith("O(")
    assert "publish_notice" in record["formula"]
    assert record["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


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


def test_tdfol_bridge_recovers_raw_statutory_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _RawStatutoryResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "proof_obligation_id": "raw:repealed-section",
                    "formula": (
                        "42 U.S.C. 1411d.: §1411d. Repealed. Pub. L. "
                        "93-383, title II, §204, Aug. 22, 1974, 88 Stat. 668"
                    ),
                },
                {
                    "proof_obligation_id": "raw:heading-section",
                    "text": (
                        "20 U.S.C. 7372: U.S.C. Title 20 - EDUCATION "
                        "CHAPTER 70 - STRENGTHENING AND IMPROVEMENT OF "
                        "ELEMENTARY AND SECONDARY SCHOOLS"
                    ),
                },
            ],
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _RawStatutoryConverter:
        @staticmethod
        def convert(_text: str):
            return _RawStatutoryResult()

    adapter = FolTdfolBridgeAdapter(converter=_RawStatutoryConverter())
    report = adapter.evaluate(
        "42 U.S.C. 1411d. Repealed. 20 U.S.C. 7372 Title 20 - Education.",
        document_id="tdfol-raw-proof-rows",
        citation="42 U.S.C. 1411d",
    )

    records = report.ir_document.views["tdfol_formula"].payload["records"]

    assert len(records) >= 2
    assert all(record["parse_ok"] for record in records)
    assert {
        "raw:repealed-section",
        "raw:heading-section",
    } <= {record["source_id"] for record in records}
    assert report.proof_gate.failed_count == 0
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["tdfol_no_formula_loss"] == 0.0


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


def test_tdfol_bridge_coerce_preserves_targeted_quantified_obligation_view() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import QuantifiedFormula
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = (
        "TDFOL.prover proof obligation view: forall t. "
        "true and By(t,2026-03-20) -> O(frm:10-2851a,t)."
    )

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, QuantifiedFormula)
    assert "By" in coerced.get_predicates()
    assert "legacy_deontic_target" in coerced.get_predicates()


def test_tdfol_bridge_coerce_parses_colon_quantifier_before_nullary_atom() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import QuantifiedFormula
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "forall t: true and By(t,2026-03-20) -> O(frm:10-2851a,t)"

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


def test_tdfol_bridge_coerce_extracts_json_formula_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = '{"target_logic": "TDFOL", "formula": "P(establish_fund(secretary))"}'

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.PERMISSION
    assert coerced.to_string() == "P(establish_fund(secretary))"


def test_tdfol_bridge_coerce_extracts_assignment_formula_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "target_logic=TDFOL; formula=O(perform_functions(secretary))"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(perform_functions(secretary))"


def test_tdfol_bridge_coerce_extracts_targeted_json_view_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = (
        'TDFOL.prover proof obligation view: '
        '{"formula": "O(collect_fees(chief_administrative_officer))"}'
    )

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(collect_fees(chief_administrative_officer))"


def test_tdfol_bridge_coerce_extracts_assignment_container_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = (
        'target_logic=TDFOL; proof_obligations='
        '[{"formula": "O(collect_fees(chief_administrative_officer))"}]'
    )

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(collect_fees(chief_administrative_officer))"


def test_tdfol_bridge_coerce_canonicalizes_deontic_label_export_text() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    coerced = coerce_tdfol_formula("O: publish_notice(agency)")

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(publish_notice(agency))"


def test_tdfol_bridge_coerce_canonicalizes_deontic_agent_prefix_export() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "proof obligation: O(agency, publish_notice(agency, deadline))"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(publish_notice(agency, deadline))"


def test_tdfol_bridge_coerce_canonicalizes_keyword_deontic_export() -> None:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    formula = "O(agent=agency, action=publish_notice(agency, deadline))"

    coerced = coerce_tdfol_formula(formula)

    assert isinstance(coerced, DeonticFormula)
    assert coerced.operator == DeonticOperator.OBLIGATION
    assert coerced.to_string() == "O(publish_notice(agency, deadline))"


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


def test_tdfol_bridge_canonicalizes_assignment_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "proof_input": (
                        "target_logic=TDFOL; formula=O: publish_notice(agency)"
                    ),
                    "source_id": "tdfol:guidance:assignment",
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

    report = adapter.evaluate("The agency shall publish notice.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["formula"] == "O(publish_notice(agency))"
    assert record["parse_ok"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_canonicalizes_targeted_prover_wrapper_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "proof_formula": (
                        "TDFOL.prover("
                        "proof_obligation=O(publish_notice(agency)), "
                        "target_metric=tdfol_parse_failure_ratio)"
                    ),
                    "source_id": "tdfol:guidance:targeted-wrapper",
                },
                {
                    "proof_formula": (
                        "TDFOL.prover(P(accept_payment(secretary)))"
                    ),
                    "source_id": "tdfol:guidance:targeted-direct",
                },
            ],
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _ProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _ProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_ProofObligationConverter())

    report = adapter.evaluate("The agency shall publish notice.")
    records = report.ir_document.views["tdfol_formula"].payload["records"]
    formulas = {record["source_id"]: record["formula"] for record in records}

    assert formulas["tdfol:guidance:targeted-wrapper"] == "O(publish_notice(agency))"
    assert formulas["tdfol:guidance:targeted-direct"] == "P(accept_payment(secretary))"
    assert all(record["parse_ok"] for record in records)
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_accepts_exported_formula_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "target_component": "TDFOL.prover",
                    "exported_formula": "O(make_report(person))",
                    "source_id": "tdfol:guidance:exported-formula",
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

    report = adapter.evaluate("The person shall make a report.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["source_id"] == "tdfol:guidance:exported-formula"
    assert record["formula"] == "O(make_report(person))"
    assert record["parse_ok"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_accepts_router_alias_formula_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": {
                "records": [
                    {
                        "candidate_formula": "O(collect_fees(chief_administrative_officer))",
                        "source_id": "tdfol:guidance:candidate-formula",
                    },
                    {
                        "theorem_formula": "P(accept_payment(chief_administrative_officer))",
                        "source_id": "tdfol:guidance:theorem-formula",
                    },
                    {
                        "logical_form": "F(disclose_records(agency))",
                        "source_id": "tdfol:guidance:logical-form",
                    },
                ]
            },
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _ProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _ProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_ProofObligationConverter())

    report = adapter.evaluate("The officer shall collect fees.")
    records = report.ir_document.views["tdfol_formula"].payload["records"]

    assert {
        "tdfol:guidance:candidate-formula",
        "tdfol:guidance:theorem-formula",
        "tdfol:guidance:logical-form",
    } <= {record["source_id"] for record in records}
    assert all(record["parse_ok"] for record in records)
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["tdfol_no_formula_loss"] == 0.0


def test_tdfol_bridge_recovers_nested_alternate_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": {
                "obligations": [
                    {
                        "proof_formula": (
                            "O(agent=agency, action=publish_notice(agency, deadline))"
                        ),
                        "source_id": "tdfol:guidance:keyword",
                    }
                ]
            },
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _ProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _ProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_ProofObligationConverter())

    report = adapter.evaluate("The agency shall publish notice.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["source_id"] == "tdfol:guidance:keyword"
    assert record["formula"] == "O(publish_notice(agency, deadline))"
    assert record["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_recovers_alternate_rows_after_empty_records_list() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": {
                "records": [],
                "rows": [
                    {
                        "proof_input": "O(collect_fees(chief_administrative_officer))",
                        "source_id": "tdfol:guidance:rows",
                    }
                ],
            },
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _ProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _ProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_ProofObligationConverter())

    report = adapter.evaluate("The Chief Administrative Officer shall collect fees.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["source_id"] == "tdfol:guidance:rows"
    assert record["formula"] == "O(collect_fees(chief_administrative_officer))"
    assert record["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_recovers_nested_view_payload_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _ProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "target_view": "TDFOL.prover",
                    "payload": {
                        "obligations": [
                            {
                                "target_logic": "TDFOL",
                                "proof_goal": (
                                    "TDFOL.prover proof_obligation view: "
                                    "O(Chief Administrative Officer, "
                                    "collect fees for internal services)"
                                ),
                            }
                        ]
                    },
                    "source_id": "tdfol:guidance:nested-view",
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

    report = adapter.evaluate("The Chief Administrative Officer shall collect fees.")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["source_id"] == "tdfol:guidance:nested-view"
    assert record["formula"] == (
        "O(collect_fees_for_internal_services(chief_administrative_officer))"
    )
    assert record["parse_ok"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_synthesizes_raw_text_proof_obligation_rows() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _RawProofObligationResult:
        success = True
        metadata = {
            "proof_obligations": [
                {
                    "text": (
                        "Each State shall prepare and submit to the Administrator "
                        "a report on water quality."
                    ),
                    "source_id": "tdfol:guidance:raw-text",
                }
            ],
            "legal_norm_irs": [],
            "parser_elements": [],
        }

    class _RawProofObligationConverter:
        @staticmethod
        def convert(_text: str):
            return _RawProofObligationResult()

    adapter = FolTdfolBridgeAdapter(converter=_RawProofObligationConverter())

    report = adapter.evaluate("stub")
    record = report.ir_document.views["tdfol_formula"].payload["records"][0]

    assert record["source_id"] == "tdfol:guidance:raw-text"
    assert record["formula"].startswith("O(")
    assert "each_state_prepare_submit_administrator_report" in record["predicates"]
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


def test_tdfol_bridge_compacts_status_and_definition_fallback_predicates() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _EmptyResult:
        success = True
        metadata = {"legal_norm_irs": [], "parser_elements": []}

    class _EmptyConverter:
        @staticmethod
        def convert(_text: str):
            return _EmptyResult()

    adapter = FolTdfolBridgeAdapter(converter=_EmptyConverter())

    repealed = adapter.evaluate("42 U.S.C. 7705: §§7705, 7705a. Repealed.")
    definition = adapter.evaluate(
        '46 U.S.C. 4701. Definitions In this chapter- (1) "abandon" means to moor a barge.'
    )

    repealed_formula = repealed.ir_document.views["tdfol_formula"].payload["records"][0][
        "formula"
    ]
    definition_formula = definition.ir_document.views["tdfol_formula"].payload[
        "records"
    ][0]["formula"]

    assert "statute_status_repealed" in repealed_formula
    assert "define_abandon" in definition_formula
    assert repealed.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0
    assert definition.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_uses_uscode_heading_when_only_catalog_text_is_available() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _EmptyResult:
        success = True
        metadata = {"legal_norm_irs": [], "parser_elements": []}

    class _EmptyConverter:
        @staticmethod
        def convert(_text: str):
            return _EmptyResult()

    adapter = FolTdfolBridgeAdapter(converter=_EmptyConverter())

    catchline = adapter.evaluate(
        (
            "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, "
            "2024 Edition Title 25 - INDIANS Sec. 5126 - Mandatory "
            "application of sections 5102 and 5124 From the U.S. "
            "Government Publishing Office"
        )
    )
    truncated_heading = adapter.evaluate(
        (
            "U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE 22 U.S.C. "
            "United States Code, 2024 Edition Title 22 - FOREIGN RELATIONS "
            "AND INTERCOURSE CHAPTER 29 - CULTURAL, TECHNICAL, AND "
            "EDUCATIONAL CENTERS SUBCHAPTER I - CENTER BETWEEN EAST AND WES"
        )
    )

    catchline_formula = catchline.ir_document.views["tdfol_formula"].payload[
        "records"
    ][0]["formula"]
    heading_formula = truncated_heading.ir_document.views["tdfol_formula"].payload[
        "records"
    ][0]["formula"]

    assert "mandatory_application_of_sections_5102_and_5124" in catchline_formula
    assert "center_between_east_and_wes" in heading_formula
    assert "u_s_c_title" not in catchline_formula
    assert "u_s_c_title" not in heading_formula
    assert catchline.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0
    assert truncated_heading.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


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


def test_tdfol_bridge_accepts_packet_shaped_compiler_guidance_route() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _GuidanceResult:
        success = True
        metadata = {"legal_norm_irs": [], "parser_elements": []}

    class _GuidanceConverter:
        @staticmethod
        def convert(_text: str):
            return _GuidanceResult()

    guidance = {
        "compiler_guidance_quality_gate": "pass",
        "compiler_guidance_route": "repair_tdfol_bridge_parse",
        "semantic_bundle_key": (
            '{"program_synthesis_scope":"tdfol",'
            '"route":"repair_tdfol_bridge_parse",'
            '"source":"compiler_guidance_distillation_v1",'
            '"target_component":"TDFOL.prover"}'
        ),
        "target_component": "TDFOL.prover",
    }
    adapter = FolTdfolBridgeAdapter(converter=_GuidanceConverter())

    report = adapter.evaluate(
        (
            "7 U.S.C. 7218: U.S.C. Title 7 - AGRICULTURE Sec. 7218 - "
            "Planting flexibility."
        ),
        compiler_guidance=guidance,
    )
    records = report.ir_document.views["tdfol_formula"].payload["records"]

    assert records[0]["source_id"] == "tdfol:compiler_guidance:repair_tdfol_bridge_parse"
    assert records[0]["parse_ok"] is True
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.ir_document.metadata["compiler_guidance_applied"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_promotes_packet_evidence_to_parse_repair_rule() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _GuidanceResult:
        success = True
        metadata = {"legal_norm_irs": [], "parser_elements": []}

    class _GuidanceConverter:
        @staticmethod
        def convert(_text: str):
            return _GuidanceResult()

    guidance = {
        "evidence": [
            {
                "bridge_failure_name": "tdfol_parse_failure_ratio",
                "hint_id": "modal-synthesis-593e5f25a253c792",
                "predicted_view": "TDFOL.prover",
                "target_file_lane": "tdfol",
                "target_view": "TDFOL.prover",
            }
        ],
        "legal_ir_underrepresented_components": ["TDFOL.prover"],
    }
    adapter = FolTdfolBridgeAdapter(converter=_GuidanceConverter())

    report = adapter.evaluate(
        (
            "43 U.S.C. 390h: The Secretary, in cooperation with the City of "
            "Redwood City, is authorized to participate in construction when "
            "recycled water facilities are planned."
        ),
        compiler_guidance=guidance,
    )
    records = report.ir_document.views["tdfol_formula"].payload["records"]

    assert records[0]["source_id"] == "tdfol:compiler_guidance:repair_tdfol_bridge_parse"
    assert records[0]["parse_ok"] is True
    assert records[0]["formula"].startswith("□((→")
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.proof_gate.compiles is True
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


def test_cec_dcec_bridge_exposes_rescue_target_metrics() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "42 U.S.C. 19120. After the Directorate has been in operation "
            "for 6 years, the Director shall enter into an agreement with "
            "the National Academies to provide an evaluation."
        ),
        document_id="cec-bridge-rescue-target-metrics",
        citation="42 U.S.C. 19120",
    )

    target_metric_names = {
        "cec_dcec_event_formula_invalid_ratio",
        "cec_dcec_validation_failure_ratio",
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
        "cross_entropy_loss",
        "cosine_similarity",
        "legal_ir_view_cross_entropy_loss",
        "source_decompiled_text_embedding_cosine_loss",
        "source_copy_reward_hack_penalty",
    }
    round_trip_dict = report.round_trip.to_dict()
    metric_values = {
        **round_trip_dict,
        **round_trip_dict["extra_losses"],
        **report.metadata["target_metrics"],
    }

    assert target_metric_names <= set(metric_values)
    assert report.round_trip.cross_entropy_loss == 0.0
    assert report.round_trip.extra_losses["legal_ir_view_cross_entropy_loss"] == 0.0
    assert (
        report.round_trip.extra_losses[
            "source_decompiled_text_embedding_cosine_loss"
        ]
        == 0.0
    )
    assert report.round_trip.extra_losses["source_copy_reward_hack_penalty"] == 0.0
    assert report.metadata["target_metrics"]["cosine_similarity"] == 1.0


def test_cec_dcec_bridge_promotes_packet_shaped_compiler_guidance() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    guidance = {
        "bundle": (
            '{"program_synthesis_scope":"cec",'
            '"route":"repair_cec_dcec_bridge",'
            '"source":"compiler_guidance_distillation_v1",'
            '"target_component":"CEC.native"}'
        ),
        "target_metrics": (
            "cross_entropy_loss, cosine_similarity, "
            "compiler_ir_cross_entropy_loss, compiler_ir_cosine_similarity, "
            "source_copy_reward_hack_penalty, cec_dcec_validation_failure_ratio, "
            "legal_ir_view_cross_entropy_loss"
        ),
        "compiler_guidance_quality_gate": "pass",
    }

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "The agency shall publish notice before the permit takes effect."
        ),
        document_id="cec-bridge-packet-guidance",
        citation="CEC Bridge Packet Guidance",
        compiler_guidance=guidance,
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert report.metadata["compiler_guidance_applied"] is True
    assert report.ir_document.metadata["compiler_guidance_applied"] is True
    assert report.metadata["compiler_guidance_routes"] == [
        "repair_cec_dcec_bridge"
    ]
    assert report.metadata["compiler_guidance_target_component"] == "CEC.native"
    assert report.metadata["compiler_guidance_quality_gate"] == "pass"
    assert {
        "compiler_ir_cross_entropy_loss",
        "compiler_ir_cosine_similarity",
        "cec_dcec_validation_failure_ratio",
    } <= set(report.metadata["compiler_guidance_target_metrics"])
    assert event_record["event_formula_source"] == (
        "compiler_guidance.top_level.materialized_event_formula"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_quality_gate"][
            "compiler_guidance_materialized"
        ]
        is True
    )
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["compiler_ir_cross_entropy_loss"] == 0.0
    assert report.round_trip.extra_losses["compiler_ir_cosine_similarity"] == 1.0
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0


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


def test_cec_dcec_bridge_recognizes_repealed_section_status_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("editorial section status should not invoke converter")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "U.S.C. Title 20 - EDUCATION Secs. 6577, 6578 - Repealed. "
            "Pub. L. 114-95, title I, Dec. 10, 2015. "
            "§§6577, 6578. Repealed. Section 6577 related to State report."
        ),
        document_id="cec-bridge-repealed-status",
        citation="20 U.S.C. 6577",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "statute_section"
    assert event_record["event"] == "record_section_repeal"
    assert formula_record["proof_input"].startswith("LifecycleState(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_recognizes_omitted_section_status_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("editorial section status should not invoke converter")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "42 U.S.C. 4906. §4906. Omitted Editorial Notes Codification "
            "Section, Pub. L. 92-574, §7(a), Oct. 27, 1972, 86 Stat. 1239, "
            "related to a study by the Administrator of the adequacy of noise "
            "controls and noise emission standards."
        ),
        document_id="cec-bridge-omitted-status",
        citation="42 U.S.C. 4906",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "statute_section"
    assert event_record["event"] == "record_section_omission"
    assert formula_record["proof_input"].startswith("LifecycleState(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_rejects_heading_polluted_fallback_proposition() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _HeadingPollutedOutput:
        proposition = (
            "U.S.C. Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES "
            "United States Code From the U.S. Government Publishing Office "
            + ("heading text " * 30)
        )
        operator = None
        agent = None

    class _HeadingPollutedResult:
        success = True
        output = _HeadingPollutedOutput()
        metadata = {}

    class _HeadingPollutedConverter:
        @staticmethod
        def convert(_text: str):
            return _HeadingPollutedResult()

    adapter = CecDcecBridgeAdapter(converter=_HeadingPollutedConverter())
    report = adapter.evaluate(
        (
            "U.S.C. Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES "
            "Sec. 50111 - Liability for acts of officers and agents "
            "§50111. Liability for acts of officers and agents The corporation "
            "is liable for the acts of its officers and agents acting within "
            "the scope of their authority."
        ),
        document_id="cec-bridge-heading-polluted-fallback",
        citation="36 U.S.C. 50111",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "corporation"
    assert event_record["event"] == "assume_liability_for_acts_of_officers_and_agents"
    assert "usc_title" not in formula_record["proof_input"].lower()
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


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
        "=> HoldsAt(O(Happens(agency,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"]["top_level_connector"]
        == "=>"
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_wraps_direct_state_formula_exports() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _StateFormulaResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "direct:cec:state-formula",
                    "actor": "Statute section",
                    "action": "record section repeal",
                    "modality": "obligated",
                    "norm_type": "definition",
                    "event_calculus_formula": (
                        "definition(statute_section, record_section_repeal)."
                    ),
                    "event_formula_source": "canonical_legal_ir",
                }
            ]
        }

    class _StateFormulaConverter:
        @staticmethod
        def convert(_text: str):
            return _StateFormulaResult()

    adapter = CecDcecBridgeAdapter(converter=_StateFormulaConverter())
    report = adapter.evaluate(
        "The section is repealed.",
        document_id="cec-bridge-direct-state-formula",
        citation="CEC Bridge Direct State Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    parse_profile = event_record["event_formula_target_parse_profile"]

    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(direct_cec_state_formula), t) "
        "=> HoldsAt(Definition(statute_section, record_section_repeal), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert parse_profile["event_predicates"] == ["Happens", "HoldsAt"]
    assert parse_profile["event_predicate_slot_complete"] is True
    assert parse_profile["target_parse_profile_complete"] is True
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


def test_cec_dcec_bridge_recognizes_transferred_section_status_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("editorial transferred status should not invoke converter")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "§3796ee-7. Transferred Editorial Notes Codification Section "
            "3796ee-7 was editorially reclassified as section 10408 of "
            "Title 34, Crime Control and Law Enforcement."
        ),
        document_id="cec-bridge-transferred-status",
        citation="42 U.S.C. 3796ee",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "statute_section"
    assert event_record["event"] == "record_section_transfer"
    assert formula_record["proof_input"].startswith("LifecycleState(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_does_not_treat_transfer_of_amounts_as_editorial_status() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _TransferNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-26-9601-transfer-amounts",
                    "actor": "amounts appropriated",
                    "action": "be transferred at least monthly",
                    "modality": "obligated",
                    "support_text": (
                        "The amounts appropriated by any section shall be "
                        "transferred at least monthly from the general fund."
                    ),
                }
            ]
        }

    class _TransferNormConverter:
        @staticmethod
        def convert(_text: str):
            return _TransferNormResult()

    adapter = CecDcecBridgeAdapter(converter=_TransferNormConverter())
    report = adapter.evaluate(
        (
            "Sec. 9601 - Transfer of amounts From the U.S. Government "
            "Publishing Office, www.gpo.gov §9601. Transfer of amounts "
            "The amounts appropriated by any section shall be transferred "
            "at least monthly from the general fund."
        ),
        document_id="cec-bridge-transfer-of-amounts",
        citation="26 U.S.C. 9601",
    )

    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]
    event_record = report.ir_document.views["cec_events"].payload["events"][0]

    assert formula_record["proof_input"].startswith("O(")
    assert not formula_record["proof_input"].startswith("LifecycleState(")
    assert event_record["event"] == "be_transferred_at_least_monthly_from_the_general_fund"
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_generic_shall_clause_before_revision_notes() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("generic shall clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "U.S.C. Title 41 - PUBLIC CONTRACTS Sec. 4711 - Linking of award "
            "and incentive fees to acquisition outcomes From the U.S. Government "
            "Publishing Office, www.gpo.gov §4711. Linking of award and "
            "incentive fees to acquisition outcomes (b) Guidance for Executive "
            "Agencies on Linking of Award and Incentive Fees to Acquisition "
            "Outcomes .-The Federal Acquisition Regulation shall provide "
            "executive agencies other than the Department of Defense with "
            "instructions on the appropriate use of award and incentive fees. "
            "Historical and Revision Notes The words are omitted because of "
            "section 6(f) of the bill."
        ),
        document_id="cec-bridge-generic-shall-before-revision-notes",
        citation="41 U.S.C. 4711",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "federal_acquisition_regulation"
    assert event_record["event"].startswith("provide_executive_agencies")
    assert formula_record["proof_input"].startswith("O(")
    assert not formula_record["proof_input"].startswith("LifecycleState(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_bare_usc_shall_clause_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("bare U.S.C. citation shall clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "25 U.S.C. 5344. The Secretary shall submit a report to Congress "
            "after consultation with Indian tribes."
        ),
        document_id="cec-bridge-bare-usc-shall-clause",
        citation="25 U.S.C. 5344",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "secretary"
    assert event_record["event"].startswith("submit_a_report_to_congress")
    assert formula_record["proof_input"].startswith("O(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_mandatory_application_without_heading_duplication() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("mandatory application clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "25 U.S.C. 5126: U.S.C. Title 25 - INDIANS Sec. 5126 - "
            "Mandatory application of sections 5102 and 5124 From the U.S. "
            "Government Publishing Office, www.gpo.gov §5126. Mandatory "
            "application of sections 5102 and 5124 Sections 5102 and 5124 "
            "of this title shall apply to this subchapter."
        ),
        document_id="cec-bridge-mandatory-application",
        citation="25 U.S.C. 5126",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "sections_5102_and_5124_of_this_title"
    assert event_record["event"] == "apply_to_this_subchapter"
    assert formula_record["proof_input"].startswith("AppliesTo(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_applicable_to_state_clause_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("applicability clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "7 U.S.C. 3416: U.S.C. Title 7 - AGRICULTURE Sec. 3416 - "
            "Amendments to orders From the U.S. Government Publishing Office, "
            "www.gpo.gov §3416. Amendments to orders The provisions of this "
            "chapter applicable to orders shall be applicable to amendments "
            "to orders."
        ),
        document_id="cec-bridge-applicable-to-state-clause",
        citation="7 U.S.C. 3416",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "provisions_of_this_chapter_applicable_to_orders"
    assert event_record["event"] == "apply_to_amendments_to_orders"
    assert formula_record["proof_input"].startswith("AppliesTo(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_construction_exemption_state_clause_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("construction exemption should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "20 U.S.C. 7372: U.S.C. Title 20 - EDUCATION Sec. 7372 - "
            "Rule of construction on equalized spending From the U.S. "
            "Government Publishing Office, www.gpo.gov §7372. Rule of "
            "construction on equalized spending Nothing in this subchapter "
            "shall be construed to mandate equalized spending per pupil for "
            "a State, local educational agency, or school."
        ),
        document_id="cec-bridge-construction-exemption-state-clause",
        citation="20 U.S.C. 7372",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "this_subchapter"
    assert event_record["event"].startswith("mandate_equalized_spending")
    assert formula_record["proof_input"].startswith("ExemptedFrom(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_definition_section_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("definition clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "5 U.S.C. 2106: U.S.C. Title 5 - GOVERNMENT ORGANIZATION AND "
            "EMPLOYEES Sec. 2106 - Member of Congress For the purpose of "
            "this title, Member of Congress means the Vice President, a "
            "Senator, Representative, Delegate, or Resident Commissioner."
        ),
        document_id="cec-bridge-definition-member-of-congress",
        citation="5 U.S.C. 2106",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "member_of_congress"
    assert event_record["event"].startswith("mean_vice_president")
    assert formula_record["proof_input"].startswith("Definition(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_appropriation_authorization_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("appropriation authorization should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "22 U.S.C. 290g-9: U.S.C. Title 22 - FOREIGN RELATIONS AND "
            "INTERCOURSE Sec. 290g-9 - Authorization of appropriations "
            "There are authorized to be appropriated such sums as may be "
            "necessary for United States contributions to the African "
            "Development Fund."
        ),
        document_id="cec-bridge-appropriation-authorization",
        citation="22 U.S.C. 290g-9",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "congress"
    assert event_record["event"].startswith("authorize_appropriation_of_such_sums")
    assert formula_record["proof_input"].startswith("P(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_fers_applicability_clause_without_purpose_pollution() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("FERS applicability clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "§2151. Application of Federal Employees' Retirement System to Agency "
            "employees (a) General rule Except as provided in subsections (b) "
            "and (c), all employees of the Agency, any of whose service after "
            "December 31, 1983, is employment for the purpose of title II of "
            "the Social Security Act [42 U.S.C. 401 et seq.] and chapter 21 "
            "of title 26, shall be subject to chapter 84 of title 5."
        ),
        document_id="cec-bridge-fers-applicability",
        citation="50 U.S.C. 2151",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "all_employees_of_the_agency"
    assert event_record["event"] == "be_subject_to_chapter_84_of_title_5"
    assert formula_record["proof_input"].startswith("O(")
    assert not formula_record["proof_input"].startswith("Purpose(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_penalty_imposition_clause_without_purpose_pollution() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("penalty imposition clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "Sec. 9707 - Failure to pay premium §9707. Failure to pay premium "
            "(a) Failures to pay (1) Premiums for eligible beneficiaries There "
            "is hereby imposed a penalty on the failure of any assigned operator "
            "to pay any premium required to be paid under section 9704 with "
            "respect to any eligible beneficiary. (c) Noncompliance period For "
            "purposes of this section, the term noncompliance period means the "
            "period beginning on the due date."
        ),
        document_id="cec-bridge-penalty-imposition",
        citation="26 U.S.C. 9707",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "any_assigned_operator"
    assert event_record["event"].startswith("pay_any_premium_required")
    assert formula_record["proof_input"].startswith("O(")
    assert not formula_record["proof_input"].startswith("Purpose(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_discretionary_transfer_power_without_heading_pollution() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("discretionary transfer power should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "§617f. Canals and appurtenant structures; transfer of title; "
            "power development The Secretary of the Interior may, in his "
            "discretion, when repayments to the United States of all money "
            "advanced, with interest, reimbursable hereunder, shall have been "
            "made, transfer title to the canals and appurtenant structures."
        ),
        document_id="cec-bridge-discretionary-transfer-power",
        citation="43 U.S.C. 617f",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "secretary_of_the_interior"
    assert event_record["event"] == "transfer_title_to_the_canals_and_appurtenant_structures"
    assert "power_development" not in formula_record["proof_input"]
    assert formula_record["proof_input"].startswith("P(")
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_statutory_purpose_before_notes() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("purpose statement should be handled deterministically")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "§4501. Congressional statement of purpose It is the policy of "
            "the Congress and the purpose of this chapter to provide for the "
            "development of a national urban policy. Editorial Notes "
            "Statutory Notes and Related Subsidiaries Short Title This title "
            "may be cited as the National Urban Policy Act."
        ),
        document_id="cec-bridge-purpose-statement",
        citation="42 U.S.C. 4501",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "congress"
    assert event_record["event"] == "provide_for_the_development_of_a_national_urban_policy"
    assert formula_record["proof_input"].startswith("Purpose(")
    assert "may_be_cited" not in formula_record["proof_input"]
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_plural_purposes_after_uscode_header() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("plural purpose statement should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "Sec. 30902 - Purposes From the U.S. Government Publishing Office, "
            "www.gpo.gov §30902. Purposes The purposes of the corporation are "
            "to promote the ability of boys to do things for themselves and "
            "others. Historical and Revision Notes source table."
        ),
        document_id="cec-bridge-plural-purpose-statement",
        citation="36 U.S.C. 30902",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    formula_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "corporation"
    assert event_record["event"] == (
        "promote_the_ability_of_boys_to_do_things_for_themselves_and_others"
    )
    assert formula_record["proof_input"].startswith("Purpose(")
    assert "u_s_government_publishing_office" not in formula_record["proof_input"]
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


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


def test_cec_dcec_bridge_promotes_packet_hint_evidence_by_sample_id() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _PlainNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-2-4106-4a1b0ac1149099ad",
                    "actor": "Clerk",
                    "action": "specify stationery",
                    "modality": "obligated",
                    "support_text": "The Clerk shall specify stationery.",
                }
            ]
        }

    class _PlainNormConverter:
        @staticmethod
        def convert(_text: str):
            return _PlainNormResult()

    adapter = CecDcecBridgeAdapter(converter=_PlainNormConverter())
    report = adapter.evaluate(
        "2 U.S.C. 4106: The Clerk shall specify stationery.",
        document_id="us-code-2-4106-4a1b0ac1149099ad",
        citation="2 U.S.C. 4106",
        compiler_guidance={
            "compiler_guidance_route": "repair_cec_dcec_bridge",
            "target_component": "CEC.native",
            "hint_evidence": [
                {
                    "citation": "26 U.S.C. 994",
                    "evidence_rank": 1,
                    "sample_id": "us-code-26-994-cbae6d13150585b8",
                    "selected_frame_after": "nonmatching_frame",
                },
                {
                    "citation": "2 U.S.C. 4106",
                    "evidence_rank": 2,
                    "sample_id": "us-code-2-4106-4a1b0ac1149099ad",
                    "selected_frame_after": "administrative_notice_hearing",
                },
            ],
        },
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["selected_frame"] == "administrative_notice_hearing"
    assert event_record["selected_frame_source"] == (
        "compiler_guidance.hint_evidence.selected_frame_after"
    )
    assert event_record["compiler_guidance_source"] == "repair_cec_dcec_bridge"
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0


def test_cec_dcec_bridge_promotes_compiler_guidance_event_formula_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _PlainNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-7-7218-guided-cec",
                    "actor": "Secretary",
                    "action": "allow planting flexibility",
                    "modality": "permitted",
                    "support_text": "The Secretary may allow planting flexibility.",
                }
            ]
        }

    class _PlainNormConverter:
        @staticmethod
        def convert(_text: str):
            return _PlainNormResult()

    adapter = CecDcecBridgeAdapter(converter=_PlainNormConverter())
    report = adapter.evaluate(
        "7 U.S.C. 7218: The Secretary may allow planting flexibility.",
        document_id="us-code-7-7218-guided-cec",
        citation="7 U.S.C. 7218",
        compiler_guidance={
            "bundle": {
                "program_synthesis_scope": "cec",
                "route": "repair_cec_dcec_bridge",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "CEC.native",
            },
            "evidence": [
                {
                    "citation": "7 U.S.C. 7218",
                    "evidence_rank": 1,
                    "sample_id": "us-code-7-7218-guided-cec",
                    "event_calculus_formula_after": (
                        "Happens[legal_norm(us_code_7_7218_guided_cec), t] "
                        "=> HoldsAt[P[happens(secretary,allow_planting_flexibility,t0)], t]."
                    ),
                }
            ],
        },
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    assert event_record["event_formula_source"] == (
        "compiler_guidance.evidence.event_calculus_formula_after"
    )
    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(us_code_7_7218_guided_cec), t) "
        "=> HoldsAt(P(Happens(secretary,allow_planting_flexibility,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_parse_profile"][
            "target_parse_profile_complete"
        ]
        is True
    )
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is False
    )
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_materializes_event_formula_from_packet_guidance() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _PlainNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-33-3803-ac8f8e7ef6c14117",
                    "actor": "Administrator",
                    "action": "administer and enforce clean hull requirements",
                    "modality": "obligated",
                    "support_text": "The Administrator shall administer and enforce this chapter.",
                }
            ]
        }

    class _PlainNormConverter:
        @staticmethod
        def convert(_text: str):
            return _PlainNormResult()

    adapter = CecDcecBridgeAdapter(converter=_PlainNormConverter())
    report = adapter.evaluate(
        "33 U.S.C. 3803: Administrative enforcement evidence.",
        document_id="us-code-33-3803-ac8f8e7ef6c14117",
        citation="33 U.S.C. 3803",
        compiler_guidance={
            "bundle": {
                "program_synthesis_scope": "cec",
                "route": "repair_cec_dcec_bridge",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "CEC.native",
            },
            "evidence": [
                {
                    "bridge_failure_name": "cec_dcec_validation_failure_ratio",
                    "cosine_loss": 0.0,
                    "sample_id": "us-code-33-3803-ac8f8e7ef6c14117",
                    "spacy_modal_formula_count": 19,
                    "spacy_parser_missing_formula": False,
                    "target_view": "CEC.native",
                }
            ],
        },
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert event_record["event_formula_source"] == (
        "compiler_guidance.evidence.materialized_event_formula"
    )
    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(us_code_33_3803_ac8f8e7ef6c14117), t) "
        "=> HoldsAt(O(Happens(administrator,administer_and_enforce_clean_hull_requirements,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_components"][
            "compiler_guidance_materialized"
        ]
        is True
    )
    assert event_record["compiler_guidance_source"] == "repair_cec_dcec_bridge"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_materializes_event_formula_from_json_packet_guidance() -> None:
    import json

    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _PlainNormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "us-code-38-1731-7736f9e2e50472ec",
                    "actor": "President",
                    "action": "assist veterans health care providers",
                    "modality": "permitted",
                    "support_text": "The President is authorized to assist.",
                }
            ]
        }

    class _PlainNormConverter:
        @staticmethod
        def convert(_text: str):
            return _PlainNormResult()

    adapter = CecDcecBridgeAdapter(converter=_PlainNormConverter())
    report = adapter.evaluate(
        "38 U.S.C. 1731: The President is authorized to assist.",
        document_id="us-code-38-1731-7736f9e2e50472ec",
        citation="38 U.S.C. 1731",
        compiler_guidance={
            "bundle": json.dumps(
                {
                    "action": "repair_cec_dcec_bridge",
                    "program_synthesis_scope": "cec",
                    "target_component": "CEC.native",
                }
            ),
            "evidence": json.dumps(
                [
                    {
                        "bridge_failure_name": "cec_dcec_validation_failure_ratio",
                        "sample_id": "us-code-38-1731-7736f9e2e50472ec",
                        "spacy_modal_formula_count": 12,
                        "spacy_parser_missing_formula": False,
                        "target_view": "CEC.native",
                    }
                ]
            ),
        },
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert event_record["event_formula_source"] == (
        "compiler_guidance.evidence.materialized_event_formula"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_components"][
            "compiler_guidance_materialized"
        ]
        is True
    )
    assert event_record["compiler_guidance_source"] == "repair_cec_dcec_bridge"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_guidance_overrides_generic_legal_frame_category() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "26 U.S.C. 994: U.S.C. Title 26 - INTERNAL REVENUE CODE "
            "Sec. 994 - Regulations. The Secretary shall prescribe such "
            "regulations as may be necessary after notice and hearing."
        ),
        document_id="us-code-26-994-cbae6d13150585b8",
        citation="26 U.S.C. 994",
        compiler_guidance={
            "bundle": {
                "route": "repair_cec_dcec_bridge",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "CEC.native",
            },
            "evidence": [
                {
                    "citation": "26 U.S.C. 994",
                    "compiler_guidance_route": "repair_cec_dcec_bridge",
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
    assert (
        event_record["event_formula_target_components"]["selected_frame"]
        == "administrative_notice_hearing"
    )


def test_cec_dcec_bridge_materializes_guided_notice_hearing_frame_events() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "24 U.S.C. 295a: U.S.C. Title 24 - HOSPITALS AND ASYLUMS "
            "24 U.S.C. United States Code, 2024 Edition Title 24 - "
            "HOSPITALS AND ASYLUMS CHAPTER 7 - NATIONAL CEMETERIES "
            "Sec. 295a - Arlington Memorial Amphitheater From the U.S. "
            "Government Publishing Office, www.gpo.gov §295a. Arlington "
            "Memorial Amphitheater The Secretary of the Army is authorized "
            "to maintain the Arlington Memorial Amphitheater."
        ),
        document_id="us-code-24-295a-16dcd47733b0e7d4",
        citation="24 U.S.C. 295a",
        compiler_guidance={
            "bundle": {
                "route": "repair_cec_dcec_bridge",
                "source": "compiler_guidance_distillation_v1",
                "target_component": "CEC.native",
            },
            "evidence": [
                {
                    "citation": "24 U.S.C. 295a",
                    "compiler_guidance_route": "repair_cec_dcec_bridge",
                    "evidence_rank": 2,
                    "sample_id": "us-code-24-295a-16dcd47733b0e7d4",
                    "selected_frame_after": "administrative_notice_hearing",
                }
            ],
        },
    )

    event_view = report.ir_document.views["cec_events"]
    norm_event = next(
        event
        for event in event_view.payload["events"]
        if event["event_role"] == "norm_action"
    )
    procedure_events = [
        event
        for event in event_view.payload["events"]
        if event["event_role"] == "procedure_event"
    ]
    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert norm_event["actor"] == "secretary_of_the_army"
    assert event_view.metadata["procedure_event_count"] == 2
    assert [event["event"] for event in procedure_events] == ["notice", "hearing"]
    assert procedure_events[1]["relation"] == "after"
    assert procedure_events[1]["anchor_event"] == "notice"
    assert event_record["selected_frame"] == "administrative_notice_hearing"
    assert event_record["compiler_guidance_source"] == "repair_cec_dcec_bridge"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0
    assert any(
        triple["predicate"] == "has_procedure_event"
        and triple["object"].endswith(":procedure:notice")
        for triple in report.ir_document.frame_logic_triples
    )


def test_cec_dcec_bridge_extracts_conditional_required_clause_without_converter() -> None:
    from ipfs_datasets_py.logic.bridge.cec_dcec import CecDcecBridgeAdapter

    class _NoisyConverter:
        @staticmethod
        def convert(_text: str):
            raise AssertionError("conditional required clause should be deterministic")

    adapter = CecDcecBridgeAdapter(converter=_NoisyConverter())
    report = adapter.evaluate(
        (
            "15 U.S.C. 9901. If the applicant submits a complete notice, "
            "the Secretary is required to approve the registration."
        ),
        document_id="cec-bridge-conditional-required-clause",
        citation="15 U.S.C. 9901",
        compiler_guidance={
            "compiler_guidance_quality_gate": "pass",
            "compiler_guidance_route": "repair_cec_dcec_bridge",
            "source": "compiler_guidance_distillation_v1",
            "target_component": "CEC.native",
        },
    )

    event_view = report.ir_document.views["cec_events"]
    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    procedure_events = [
        event
        for event in event_view.payload["events"]
        if event["event_role"] == "procedure_event"
    ]

    assert event_record["source_id"].startswith("dcec:section:")
    assert event_record["event_calculus_formula"].startswith("Happens(legal_norm(")
    assert event_record["event_formula_syntax_valid"] is True
    assert event_record["procedure_event_records"][0]["relation"] == (
        "condition_precedent"
    )
    assert procedure_events[0]["event"] == "applicant submits a complete notice"
    assert event_view.metadata["procedure_event_count"] == 1
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_conditional_fee_collection_actor() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "U.S.C. Title 2 - THE CONGRESS Sec. 5541 - Fees for internal "
            "delivery in House of Representatives of nonpostage mail from "
            "outside sources From the U.S. Government Publishing Office, "
            "www.gpo.gov §5541. Fees for internal delivery in House of "
            "Representatives of nonpostage mail from outside sources Effective "
            "with respect to fiscal years beginning with fiscal year 1995, in "
            "the case of mail from outside sources presented to the Chief "
            "Administrative Officer of the House of Representatives (other "
            "than mail through the Postal Service and mail with postage "
            "otherwise paid) for internal delivery in the House of "
            "Representatives, the Chief Administrative Officer is authorized "
            "to collect fees equal to the applicable postage."
        ),
        document_id="us-code-2-5541-conditional-fee-collection",
        citation="2 U.S.C. 5541",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "chief_administrative_officer"
    assert event_record["event"] == "collect_fees_equal_to_the_applicable_postage"
    assert proof_record["proof_input"].startswith("P(")
    assert "effective_with_respect" not in proof_record["proof_input"]
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_authorized_assistance_without_catchline_pollution() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "38 U.S.C. 1731: U.S.C. Title 38 - VETERANS' BENEFITS Sec. "
            "1731 - Assistance to the Republic of the Philippines From the "
            "U.S. Government Publishing Office, www.gpo.gov §1731. "
            "Assistance to the Republic of the Philippines The President is "
            "authorized to assist the Republic of the Philippines in "
            "fulfilling its responsibility in providing medical care and "
            "treatment for Commonwealth Army veterans and new Philippine "
            "Scouts in need of such care and treatment."
        ),
        document_id="us-code-38-1731-authorized-assistance",
        citation="38 U.S.C. 1731",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "president"
    assert event_record["event"].startswith("assist_the_republic_of_the_philippines")
    assert proof_record["proof_input"].startswith("P(")
    assert "assistance_to_the_republic" not in proof_record["proof_input"]
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_keeps_nato_contribution_limit_as_permission() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "10 U.S.C. 2263: Sec. 2263 - United States contributions to "
            "the North Atlantic Treaty Organization common-funded budgets "
            "§2263. United States contributions to the North Atlantic Treaty "
            "Organization common-funded budgets (a) In General .-The total "
            "amount contributed by the Secretary of Defense in any fiscal "
            "year for the common-funded budgets of NATO may be an amount in "
            "excess of the maximum amount that would otherwise be applicable "
            "to those contributions in such fiscal year under the fiscal year "
            "1998 baseline limitation. (b) Definitions .-In this section: "
            "The term common-funded budgets of NATO means the Military Budget."
        ),
        document_id="us-code-10-2263-nato-contribution-limit",
        citation="10 U.S.C. 2263",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "secretary_of_defense"
    assert event_record["event"].startswith("contribute_an_amount_in_excess")
    assert proof_record["proof_input"].startswith("P(")
    assert not proof_record["proof_input"].startswith("Definition(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_passive_administration_agent() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "16 U.S.C. 430w: Sec. 430w - Administration, protection, and "
            "development §430w. Administration, protection, and development "
            "The administration, protection, and development of the aforesaid "
            "national battlefield park shall be exercised under the direction "
            "of the Secretary of the Interior by the National Park Service "
            "subject to the provisions of the Act of August 25, 1916."
        ),
        document_id="us-code-16-430w-passive-administration",
        citation="16 U.S.C. 430w",
    )

    event_record = report.ir_document.views["cec_events"].payload["events"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["actor"] == "national_park_service"
    assert event_record["event"].startswith(
        "administer_administration_protection_and_development"
    )
    assert proof_record["proof_input"].startswith("O(")
    assert "be_exercised_under_the_direction" not in proof_record["proof_input"]
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_extracts_retained_rights_as_exemption_state() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "U.S.C. Title 20 - EDUCATION 20 U.S.C. United States Code, "
            "2024 Edition Sec. 3609 - Retained rights From the U.S. "
            "Government Publishing Office, www.gpo.gov §3609. Retained "
            "rights Except as otherwise provided in section 3607 of this "
            "title, nothing in this chapter shall— (1) affect the right "
            "of any party to seek legal redress in connection with the "
            "purchase or installation of asbestos materials in schools; "
            "or (2) affect the rights of any party under any other law."
        ),
        document_id="us-code-20-3609-retained-rights",
        citation="20 U.S.C. 3609",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert event_record["modality"] == "permitted"
    assert event_record["event_formula_syntax_valid"] is True
    assert proof_record["formula"].startswith("ExemptedFrom(")
    assert report.round_trip.extra_losses["cec_dcec_validation_failure_ratio"] == 0.0


def test_cec_dcec_bridge_ignores_executive_boilerplate_for_no_restriction_clause() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "U.S.C. Title 13 - CENSUS 13 U.S.C. United States Code, 2024 "
            "Edition Sec. 62 - Additional statistics From the U.S. "
            "Government Publishing Office, www.gpo.gov §62. Additional "
            "statistics This subchapter does not restrict or limit the "
            "Secretary in the collection and publication, under the general "
            "authority of the Secretary, of such statistics on fats and oils "
            "or products thereof not specifically required in this subchapter, "
            "as he deems to be in the public interest. Historical and Revision "
            "Notes Based on title 13. Executive Documents Transfer of "
            "Functions effective May 24, 1950, 15 F.R. 3174."
        ),
        document_id="us-code-13-62-no-restriction",
        citation="13 U.S.C. 62",
    )

    context_record = report.ir_document.views["event_calculus"].payload["records"][0]
    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert context_record["event_formula_syntax_valid"] is True
    assert proof_record["formula"].startswith("ExemptedFrom(")
    assert "effective" not in proof_record["proof_input"]
    assert "sym_24_1950" not in proof_record["proof_input"]


def test_cec_dcec_bridge_preserves_conditional_rights_actor() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "U.S.C. Title 25 - INDIANS 25 U.S.C. United States Code, 2024 "
            "Edition Sec. 116 - Indians 18 years of age to have right to "
            "receipt for annuity From the U.S. Government Publishing Office, "
            "www.gpo.gov §116. Indians 18 years of age to have right to "
            "receipt for annuity All Indians, when they shall arrive at the "
            "age of eighteen years, shall have the right to receive and "
            "receipt for all annuity money that may be due or become due to "
            "them, if not otherwise incapacitated under the regulations of "
            "the Indian Office."
        ),
        document_id="us-code-25-116-conditional-right",
        citation="25 U.S.C. 116",
    )

    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert "all_indians" in proof_record["proof_input"]
    assert "age_of_eighteen_years" not in proof_record["proof_input"]
    assert proof_record["formula"].startswith("P[")


def test_cec_dcec_bridge_keeps_subsection_dash_first_clause() -> None:
    from ipfs_datasets_py.logic.bridge import load_logic_bridge_adapter

    adapter = load_logic_bridge_adapter("cec_dcec")
    report = adapter.evaluate(
        (
            "U.S.C. Title 36 - PATRIOTIC AND NATIONAL OBSERVANCES, "
            "CEREMONIES, AND ORGANIZATIONS 36 U.S.C. United States Code, "
            "2024 Edition Sec. 150511 - Service of process From the U.S. "
            "Government Publishing Office, www.gpo.gov §150511. Service "
            "of process (a) District of Columbia .-The corporation shall "
            "have a designated agent in the District of Columbia to receive "
            "service of process for the corporation. Designation of the "
            "agent shall be filed in the office of the clerk of the United "
            "States District Court for the District of Columbia."
        ),
        document_id="us-code-36-150511-service-process",
        citation="36 U.S.C. 150511",
    )

    proof_record = report.ir_document.views["dcec_formula"].payload["records"][0]

    assert "corporation" in proof_record["proof_input"]
    assert "have_a_designated_agent" in proof_record["proof_input"]
    assert "designation_of_the_agent" not in proof_record["proof_input"]


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
        "=> HoldsAt(O(Happens(agency,publish_notice,t0)), t)"
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


def test_cec_dcec_bridge_validates_event_formula_slots_after_normalization(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:empty-slot:1",
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
            "bridge:empty-slot:1": [
                {
                    "event_calculus_formula": (
                        "Happens(legal_norm(bridge_empty_slot_1), ) => "
                        "HoldsAt(O(happens(agency,publish_notice,t0)), t)."
                    ),
                    "event_formula_source": "deontic.prover_syntax",
                    "event_formula_syntax_valid": True,
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
        document_id="cec-bridge-empty-event-slot",
        citation="CEC Bridge Empty Event Slot",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    parse_profile = event_record["event_formula_target_parse_profile"]

    assert event_record["event_formula_syntax_valid"] is False
    assert parse_profile["event_predicate_slot_complete"] is False
    assert parse_profile["target_parse_profile_complete"] is False
    assert (
        event_record["event_formula_target_quality_gate"]["requires_validation"]
        is True
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 1.0


def test_cec_dcec_bridge_falls_back_from_unstructured_event_formula_export(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:unstructured-export:1",
                    "actor": "Secretary",
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
            "bridge:unstructured-export:1": [
                {
                    "event_calculus_formula": (
                        "proof obligation: the Secretary shall publish notice"
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
        "The Secretary shall publish notice.",
        document_id="cec-bridge-unstructured-event-export",
        citation="CEC Bridge Unstructured Event Export",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]

    assert event_record["event_formula_source"] == (
        "deontic.prover_syntax:bridge_fallback"
    )
    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(bridge_unstructured_export_1), t) "
        "=> HoldsAt(O(Happens(secretary,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert (
        event_record["event_formula_target_quality_gate"][
            "cec_dcec_bridge_fallback_from_invalid_export"
        ]
        is True
    )
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_accepts_case_variant_event_formula_predicates(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:case-variant:1",
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
            "bridge:case-variant:1": [
                {
                    "event_calculus_formula": (
                        "happens(legal_norm(bridge_case_variant_1), t) => "
                        "holdsat(O(happens(agency,publish_notice,t0)), t)."
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
        document_id="cec-bridge-case-variant-event-formula",
        citation="CEC Bridge Case Variant Event Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    parse_profile = event_record["event_formula_target_parse_profile"]

    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(bridge_case_variant_1), t) => "
        "HoldsAt(O(Happens(agency,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert parse_profile["event_predicates"] == ["Happens", "HoldsAt"]
    assert parse_profile["event_predicate_slot_complete"] is True
    assert parse_profile["target_parse_profile_complete"] is True
    assert report.round_trip.extra_losses["cec_dcec_event_formula_invalid_ratio"] == 0.0


def test_cec_dcec_bridge_accepts_snake_case_event_formula_predicates(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge import cec_dcec as cec_dcec_mod

    class _NormResult:
        success = True
        metadata = {
            "legal_norm_irs": [
                {
                    "source_id": "bridge:snake-case:1",
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
            "bridge:snake-case:1": [
                {
                    "event_calculus_formula": (
                        "happens_at(legal_norm(bridge_snake_case_1), t) => "
                        "holds_at(O(happens_at(agency,publish_notice,t0)), t)."
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
        document_id="cec-bridge-snake-case-event-formula",
        citation="CEC Bridge Snake Case Event Formula",
    )

    event_record = report.ir_document.views["event_calculus"].payload["records"][0]
    parse_profile = event_record["event_formula_target_parse_profile"]

    assert event_record["event_calculus_formula"] == (
        "Happens(legal_norm(bridge_snake_case_1), t) => "
        "HoldsAt(O(Happens(agency,publish_notice,t0)), t)"
    )
    assert event_record["event_formula_syntax_valid"] is True
    assert parse_profile["event_predicates"] == ["Happens", "HoldsAt"]
    assert parse_profile["event_predicate_slot_complete"] is True
    assert parse_profile["target_parse_profile_complete"] is True
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
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.reason == "Used native_syntactic (no proof)"
    assert result.all_results["native_syntactic"].is_compiled() is True
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_syntactic_fallback_accepts_legacy_record_payloads(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for legacy payload fallback test")
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
    payload = {
        "records": [
            {
                "source_id": "us-code-42-4906",
                "text": (
                    "42 U.S.C. 4906. Omitted. Editorial Notes Codification "
                    "related to a study by the Administrator."
                ),
            }
        ]
    }

    result = router.route(payload, strategy="sequential")

    assert router.get_available_provers() == ["native_syntactic"]
    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_legacy_payload_prefers_proof_formula_over_source_text(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for mixed payload fallback test")
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
    payload = {
        "text": (
            "42 U.S.C. 9881 to 9887.: §§9881 to 9887. Repealed. "
            "Pub. L. 103-252, title I."
        ),
        "records": [
            {
                "source_id": "us-code-42-9881 to 9887",
                "text": "Editorial notes for the repealed program section.",
                "proof_input": "O(publish_notice(agency))",
            }
        ]
    }

    result = router.route(payload, strategy="sequential")

    fallback_result = result.all_results["native_syntactic"]
    assert result.is_compiled() is True
    assert fallback_result.is_valid is True
    assert fallback_result.formula.to_string() == "O(publish_notice(agency))"


def test_external_prover_router_prefers_candidate_formula_alias_over_source_text(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for candidate formula fallback test")
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
    payload = {
        "text": "7 U.S.C. 1012. Payments to counties. Source text follows.",
        "claims": [
            {
                "candidate_formula": "O(pay_to_county(secretary, county))",
                "source_text": "The Secretary shall pay to the county.",
            }
        ],
    }

    result = router.route(payload, strategy="sequential")

    fallback_result = result.all_results["native_syntactic"]
    assert result.is_compiled() is True
    assert fallback_result.is_valid is True
    assert fallback_result.formula.to_string() == "O(pay_to_county(secretary, county))"


def test_external_prover_router_syntactic_fallback_accepts_goal_payload_aliases(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for goal alias fallback test")
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
    payload = {
        "payload": {
            "goals": [
                {
                    "proof_goal": "O(register_notice(secretary))",
                    "target_logic": "TDFOL",
                }
            ]
        }
    }

    result = router.route(payload, strategy="sequential")

    fallback_result = result.all_results["native_syntactic"]
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert fallback_result.is_valid is True
    assert fallback_result.formula.to_string() == "O(register_notice(secretary))"


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
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.all_results["native_syntactic"].is_compiled() is True
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_uses_syntactic_backup_when_native_prove_fails(
    monkeypatch,
) -> None:
    import sys
    import types

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    module_name = "ipfs_datasets_py.logic.TDFOL.tdfol_prover"
    fake_module = types.ModuleType(module_name)

    class _FailingTDFOLProver:
        def prove(self, *_args, **_kwargs):
            raise RuntimeError("native prover locked")

    fake_module.TDFOLProver = _FailingTDFOLProver
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

    assert router.get_available_provers() == ["native", "native_syntactic"]
    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert "Error: native prover locked" in result.all_results["native"]
    assert result.all_results["native_syntactic"].is_compiled() is True
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_parallel_reports_syntactic_compile_fallback(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for parallel fallback test")
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
    result = router.route("O(register_notice(secretary))", strategy="parallel")

    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.reason == "Used native_syntactic (no proof)"


def test_external_prover_router_parallel_keeps_falsey_prover_results() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    class _FalseyCompileResult:
        is_compiled = True

        def __bool__(self) -> bool:
            return False

    class _FalseyCompileProver:
        @staticmethod
        def prove(*_args, **_kwargs):
            return _FalseyCompileResult()

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=False,
        enable_symbolicai=False,
        enable_z3=False,
    )
    router.provers = {"native_syntactic": _FalseyCompileProver()}

    result = router.route("O(register_notice(secretary))", strategy="parallel")

    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.all_results["native_syntactic"].is_compiled is True


def test_external_prover_router_result_compiled_honors_explicit_false() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import RouterProofResult

    result = RouterProofResult(
        is_proved=False,
        prover_used="native_syntactic",
        proof_time=0.0,
        all_results={
            "native_syntactic": SimpleNamespace(is_compiled=False),
        },
        strategy_used="sequential",
        reason="Used native_syntactic (no proof)",
    )

    assert result.is_compiled() is False


def test_external_prover_router_most_capable_reports_no_proof_for_syntactic_fallback(
    monkeypatch,
) -> None:
    import builtins

    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    real_import = builtins.__import__

    def blocked_tdfol_import(name, *args, **kwargs):
        if str(name).endswith("TDFOL.tdfol_prover"):
            raise ImportError("tdfol unavailable for most capable fallback test")
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
    result = router.route("O(register_notice(secretary))", strategy="most_capable")

    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.reason == "Used native_syntactic (no proof)"


def test_external_prover_router_most_capable_falls_back_after_inconclusive_prover() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    class _InconclusiveProver:
        @staticmethod
        def prove(*_args, **_kwargs):
            return False

    class _FallbackProver:
        @staticmethod
        def prove(*_args, **_kwargs):
            return True

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=False,
        enable_symbolicai=False,
        enable_z3=False,
    )
    router.provers = {
        "lean": _InconclusiveProver(),
        "native": _FallbackProver(),
    }

    result = router.route("O(register_notice(secretary))", strategy="most_capable")

    assert result.is_proved is True
    assert result.prover_used == "native"
    assert result.strategy_used == "most_capable"
    assert list(result.all_results) == ["lean", "native"]


def test_external_prover_router_fastest_keeps_native_compile_fallback() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import (
        ProverRouter,
        SyntacticNativeFallbackProver,
    )

    class _FailingFastProver:
        @staticmethod
        def prove(*_args, **_kwargs):
            raise RuntimeError("fast prover unavailable")

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=False,
        enable_symbolicai=False,
        enable_z3=False,
    )
    router.provers = {
        "z3": _FailingFastProver(),
        "native_syntactic": SyntacticNativeFallbackProver(),
    }

    result = router.route("O(register_notice(secretary))", strategy="fastest")

    assert result.is_proved is False
    assert result.is_compiled() is True
    assert result.prover_used == "native_syntactic"
    assert result.strategy_used == "fastest"
    assert "Error: fast prover unavailable" in result.all_results["z3"]
    assert result.all_results["native_syntactic"].is_valid is True


def test_external_prover_router_auto_falls_back_when_formula_analysis_fails() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter

    router = ProverRouter(
        enable_cache=False,
        enable_cvc5=False,
        enable_coq=False,
        enable_lean=False,
        enable_native=True,
        enable_symbolicai=False,
        enable_z3=False,
    )
    router.analyzer = SimpleNamespace(
        analyze=lambda _formula: (_ for _ in ()).throw(
            ValueError("legacy formula payload cannot be analyzed")
        )
    )

    result = router.route(
        {"proof_input": "O(register_notice(secretary))"},
        strategy="auto",
        timeout=1.0,
    )

    assert result.is_compiled() is True
    assert result.prover_used in {"native", "native_syntactic"}
    assert result.all_results
    assert any(not isinstance(item, str) for item in result.all_results.values())


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


def test_external_prover_router_bridge_recovers_nested_legacy_payload_formulas(
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

    class _NestedPayloadFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            base_record = dict(formula_records[0])
            nested_record = {
                "source_id": base_record["source_id"],
                "payload": {
                    "proof_obligations": [
                        {
                            "proof_input": base_record["formula"],
                            "target_logic": "TDFOL",
                        }
                    ]
                },
            }
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [nested_record],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoProverRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_NestedPayloadFolAdapter(),
        enable_native=False,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="external-prover-bridge-nested-payload-formula",
        citation="External Prover Bridge Nested Payload Formula",
    )

    records = report.ir_document.views["prover_formulas"].payload["records"]
    assert records
    assert records[0]["formula_parse_ok"] is True
    assert records[0]["formula"].startswith("O(")
    assert report.ir_document.metadata["router_resolved_formula_count"] == 1
    assert report.ir_document.metadata["router_text_fallback_formula_count"] == 0
    assert report.ir_document.metadata["router_unresolved_formula_count"] == 0
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_recovers_nested_goal_alias_formulas(
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

    class _GoalAliasFolAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            formula_records = list(context["formula_records"])
            assert formula_records
            base_record = dict(formula_records[0])
            goal_record = {
                "source_id": base_record["source_id"],
                "payload": {
                    "goals": [
                        {
                            "proof_goal": base_record["formula"],
                            "target_logic": "TDFOL",
                        }
                    ]
                },
            }
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [goal_record],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _NoProverRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_GoalAliasFolAdapter(),
        enable_native=False,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Secretary shall register notice.",
        document_id="external-prover-bridge-goal-alias-formula",
        citation="External Prover Bridge Goal Alias Formula",
    )

    records = report.ir_document.views["prover_formulas"].payload["records"]
    assert records
    assert records[0]["formula_parse_ok"] is True
    assert records[0]["formula"].startswith("O(")
    assert report.ir_document.metadata["router_resolved_formula_count"] == 1
    assert report.ir_document.metadata["router_text_fallback_formula_count"] == 0
    assert report.ir_document.metadata["router_unresolved_formula_count"] == 0
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


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


def test_external_prover_router_bridge_recovers_nested_packet_text_formula(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _CompiledResult:
        def __init__(self) -> None:
            self.is_proved = False
            self.prover_used = "native"
            self.proof_time = 0.01
            self.reason = "Used native (no proof)"
            self.strategy_used = "sequential"
            self.all_results = {"native": object()}

    class _CompiledRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _CompiledResult()

    class _NestedPacketFormulaAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [
                        {
                            "source_id": "packet:nested-text-formula",
                            "payload": {
                                "compiler_output": {
                                    "program": {
                                        "text": "O(register_notice(secretary))"
                                    }
                                }
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _CompiledRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_NestedPacketFormulaAdapter(),
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Secretary shall register notice.",
        document_id="external-prover-bridge-nested-packet-text-formula",
        citation="External Prover Bridge Nested Packet Text Formula",
    )

    records = report.ir_document.views["prover_formulas"].payload["records"]
    assert records[0]["formula_parse_ok"] is True
    assert records[0]["formula"] == "O(register_notice(secretary))"
    assert report.proof_gate.attempted_count == 1
    assert report.proof_gate.valid_count == 1
    assert report.proof_gate.details[0]["compiled"] is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_prefers_candidate_formula_alias(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _CompiledResult:
        def __init__(self) -> None:
            self.is_proved = False
            self.prover_used = "native"
            self.proof_time = 0.01
            self.reason = "Used native (no proof)"
            self.strategy_used = "sequential"
            self.all_results = {"native": object()}

    class _CompiledRouter:
        @staticmethod
        def get_available_provers() -> list[str]:
            return ["native"]

        @staticmethod
        def route(_formula, **_kwargs):
            return _CompiledResult()

    class _CandidateFormulaAdapter(FolTdfolBridgeAdapter):
        def encode(self, *args, **kwargs):
            document, context = super().encode(*args, **kwargs)
            return (
                document,
                {
                    **dict(context),
                    "formula_records": [
                        {
                            "source_id": "packet:candidate-formula",
                            "text": (
                                "25 U.S.C. 401. Leases for mining purposes "
                                "of unallotted lands in Kaw Reservation."
                            ),
                            "claims": [
                                {
                                    "candidate_formula": (
                                        "P(lease_for_mining(secretary, land))"
                                    )
                                }
                            ],
                        }
                    ],
                },
            )

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _CompiledRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        tdfol_adapter=_CandidateFormulaAdapter(),
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Secretary is authorized to lease lands for mining purposes.",
        document_id="external-prover-bridge-candidate-formula",
        citation="25 U.S.C. 401",
    )

    records = report.ir_document.views["prover_formulas"].payload["records"]
    assert records[0]["formula_parse_ok"] is True
    assert records[0]["formula"] == "P(lease_for_mining(secretary, land))"
    assert report.ir_document.metadata["router_resolved_formula_count"] == 1
    assert report.ir_document.metadata["router_text_fallback_formula_count"] == 0
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


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


def test_external_prover_router_bridge_accepts_packet_evidence_guidance_route(
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

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Director shall make awards on a competitive basis.",
        document_id="external-prover-bridge-packet-evidence-guidance-route",
        citation="42 U.S.C. 19012",
        compiler_guidance={
            "hint_evidence": [
                {
                    "action": "repair_external_prover_router",
                    "program_synthesis_scope": "external_provers",
                    "sample_id": "us-code-42-19012.-fa75b915b899733a",
                    "target_component": "external_provers.router",
                    "target_metrics": [
                        "external_prover_unavailable_loss",
                        "legal_ir_multiview_proof_failure_ratio",
                    ],
                }
            ],
            "target_component": "external_provers.router",
        },
    )

    assert report.status == "ok"
    assert report.metadata["compiler_guidance_applied"] is True
    assert report.metadata["compiler_guidance_prover_gate_hint"] is True
    assert report.proof_gate.compiles is True
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0


def test_external_prover_router_bridge_infers_route_from_passing_gap_evidence(
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

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=True,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Director shall make awards on a competitive basis.",
        document_id="external-prover-bridge-packet-gap-guidance-route",
        citation="42 U.S.C. 19012",
        compiler_guidance={
            "compiler_guidance_attribution": {
                "basis": "sample_records",
                "legal_ir_view_gaps": {
                    "external_provers_router:overrepresented": {
                        "count": 6,
                        "quality_gate": "pass",
                    }
                },
                "todo_routes": {},
            },
            "compiler_guidance_legal_ir_view_gaps": {
                "external_provers_router:overrepresented": 6,
            },
            "compiler_guidance_quality_gate": "pass",
            "source": "compiler_guidance_distillation_v1",
        },
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


def test_external_prover_router_bridge_inventory_fallback_reports_compile_only_success(
    monkeypatch,
) -> None:
    from ipfs_datasets_py.logic.bridge.external_prover_router import (
        ExternalProverRouterBridgeAdapter,
    )

    class _CompileOnlyProver:
        @staticmethod
        def prove(_formula, timeout_ms=1000):
            return {"is_compiled": True, "is_proved": False, "timeout_ms": timeout_ms}

    class _InventoryOnlyRouter:
        provers = {"native_syntactic": _CompileOnlyProver()}
        backup_provers = ("native_syntactic",)
        fallback_prover = "native_syntactic"

        @staticmethod
        def select_prover(_formula):
            return "native_syntactic"

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.bridge.external_prover_router._build_router",
        lambda **_kwargs: _InventoryOnlyRouter(),
    )

    adapter = ExternalProverRouterBridgeAdapter(
        enable_native=False,
        enable_external_binaries=False,
    )
    report = adapter.evaluate(
        "The Secretary shall develop a system to share supply chain risk information.",
        document_id="external-prover-bridge-inventory-compile-only",
        citation="6 U.S.C. 985",
    )

    assert report.proof_gate.compiles is True
    assert report.proof_gate.valid_count == report.proof_gate.attempted_count
    assert report.proof_gate.details[0]["compiled"] is True
    assert report.proof_gate.details[0]["prover_used"] == "native_syntactic"
    assert report.proof_gate.details[0]["reason"] == (
        "Used native_syntactic (no proof)"
    )
    assert "external_provers:native_syntactic" in report.proof_gate.verified_by
    assert report.round_trip.extra_losses["external_prover_failure_ratio"] == 0.0
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
        "TDFOL prover: O(issue_notice(administrator))": (
            "O(issue_notice(administrator))"
        ),
        (
            "proof_obligation(target=TDFOL.prover, "
            "formula=O(apply(this_chapter)))"
        ): "O(apply(this_chapter))",
        "O{apply(this_chapter)}": "O(apply(this_chapter))",
        "Obligation(agent=agency, action=publish_notice(agency))": (
            "O(publish_notice(agency))"
        ),
        "O[agency](publish_notice(agency))": "O(publish_notice(agency))",
        "P_secretary(establish_program(secretary))": (
            "P(establish_program(secretary))"
        ),
        "O[agency](P[secretary](establish_program(secretary)))": (
            "O(P(establish_program(secretary)))"
        ),
        "PERMISSION(secretary, establish_program(secretary))": (
            "P(establish_program(secretary))"
        ),
        "forbidden(disclose_records(agency))": "F(disclose_records(agency))",
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_extracts_fenced_and_multiline_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "```tdfol\nO(make_report(person))\n```": "O(make_report(person))",
        "TDFOL formula:\nO(make_report(person))\nsource: 2 U.S.C. 1511": (
            "O(make_report(person))"
        ),
        "proof obligation:\n- P(establish_program(secretary))\nconfidence: 0.91": (
            "P(establish_program(secretary))"
        ),
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_extracts_aliased_json_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        '{"target_logic": "TDFOL", "proof_obligation": "O(make_report(person))"}': (
            "O(make_report(person))"
        ),
        '{"target_component": "TDFOL.prover", "goal": "P(accept_grant(secretary))"}': (
            "P(accept_grant(secretary))"
        ),
        '{"record": {"obligation_formula": "F(disclose_records(carrier))"}}': (
            "F(disclose_records(carrier))"
        ),
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_extracts_colon_key_value_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "target_logic: TDFOL; proof_obligation: O(ensure_access(carrier))": (
            "O(ensure_access(carrier))"
        ),
        "proof_obligation(target: TDFOL.prover, goal: P(accept_grant(secretary)))": (
            "P(accept_grant(secretary))"
        ),
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_parses_colon_quantifier_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "forall t: P(t)": "∀t.P(t)",
        "∀t: publish_notice(t)": "∀t.publish_notice(t)",
        "exists x: Human(x) -> O(register(x))": "∃x.(→ Human(x) O(register(x)))",
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_extracts_prefixed_assignment_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    parsed = coerce_tdfol_formula(
        "TDFOL.prover: proof_obligation = O(agency, publish_notice(permit))"
    )

    assert parsed is not None
    assert parsed.to_string() == "O(publish_notice(permit))"


def test_fol_tdfol_coerce_formula_synthesizes_raw_deontic_text_exports() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "O(agency shall publish notice)": "O(agency_publish_notice(actor))",
        "P(the Secretary may detail members as instructors)": (
            "P(secretary_detail_members_instructors(secretary))"
        ),
        "F(person shall not disclose records)": (
            "F(person_disclose_records(actor))"
        ),
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_synthesizes_named_raw_deontic_labels() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        "obligation: agency shall publish notice": (
            "O(agency_publish_notice(actor))"
        ),
        "permission = the Secretary may detail members as instructors": (
            "P(secretary_detail_members_instructors(secretary))"
        ),
        "forbidden: person shall not disclose records": (
            "F(person_disclose_records(actor))"
        ),
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_accepts_tdfol_prover_proof_labels() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    parsed = coerce_tdfol_formula(
        "TDFOL.prover proof obligation: "
        "O(Chief Administrative Officer, collect_fees(internal_services))"
    )

    assert parsed is not None
    assert parsed.to_string() == "O(collect_fees(internal_services))"


def test_fol_tdfol_coerce_formula_accepts_plural_tdfol_prover_proof_labels() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        (
            "TDFOL.prover proof obligations: 1. "
            "O(collect_fees(chief_administrative_officer)); "
            "2. P(accept_payment(chief_administrative_officer))"
        ): "O(collect_fees(chief_administrative_officer))",
        (
            "TDFOL.prover proof obligations view: "
            "[O(collect_fees(chief_administrative_officer)), "
            "P(accept_payment(chief_administrative_officer))]"
        ): "O(collect_fees(chief_administrative_officer))",
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_accepts_targeted_prover_wrappers() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    cases = {
        (
            "proof_obligation: TDFOL.prover => "
            "O(Chief Administrative Officer, collect fees for internal services)"
        ): "O(collect_fees_for_internal_services(chief_administrative_officer))",
        (
            "TDFOL.prover proof_obligation view: "
            "obligation(Chief Administrative Officer, collect fees for internal services)"
        ): "O(collect_fees_for_internal_services(chief_administrative_officer))",
        (
            "target_view: TDFOL.prover, goal: "
            "P(Secretary, transfer funds when necessary)"
        ): "P(transfer_funds_when_necessary(secretary))",
    }

    for formula, expected in cases.items():
        parsed = coerce_tdfol_formula(formula)

        assert parsed is not None
        assert parsed.to_string() == expected


def test_fol_tdfol_coerce_formula_synthesizes_spaced_bracket_agents() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import coerce_tdfol_formula

    parsed = coerce_tdfol_formula(
        "O[Chief Administrative Officer](collect fees for internal services)"
    )

    assert parsed is not None
    assert (
        parsed.to_string()
        == "O(collect_fees_for_internal_services(chief_administrative_officer))"
    )


def test_tdfol_bridge_uscode_fallback_prefers_operative_shall_clause() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    adapter = FolTdfolBridgeAdapter()
    report = adapter.evaluate(
        (
            "2 U.S.C. 5541: U.S.C. Title 2 - THE CONGRESS 2 U.S.C. "
            "United States Code, 2024 Edition Title 2 - THE CONGRESS "
            "CHAPTER 55 - HOUSE OF REPRESENTATIVES OFFICERS AND "
            "ADMINISTRATION SUBCHAPTER III - CHIEF ADMINISTRATIVE OFFICER "
            "Sec. 5541 - Fees for internal services. The Chief "
            "Administrative Officer shall collect fees for services."
        ),
        document_id="tdfol-uscode-operative-shall-fallback",
        citation="2 U.S.C. 5541",
    )

    formulas = {
        record["formula"]
        for record in report.ir_document.views["tdfol_formula"].payload["records"]
    }
    assert "O(collect_fees_for_services(chief_administrative_officer))" in formulas
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_uscode_fallback_omits_heading_from_modal_actor() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    class _EmptyResult:
        success = True
        metadata = {
            "legal_norm_irs": [],
            "parser_elements": [],
            "proof_obligations": [],
        }

    class _EmptyConverter:
        @staticmethod
        def convert(_text: str):
            return _EmptyResult()

    adapter = FolTdfolBridgeAdapter(converter=_EmptyConverter())
    report = adapter.evaluate(
        (
            "2 U.S.C. 5541: U.S.C. Title 2 - THE CONGRESS 2 U.S.C. "
            "United States Code, 2024 Edition Title 2 - THE CONGRESS "
            "CHAPTER 55 - HOUSE OF REPRESENTATIVES OFFICERS AND "
            "ADMINISTRATION SUBCHAPTER III - CHIEF ADMINISTRATIVE OFFICER "
            "Sec. 5541 - Fees for internal services. The Chief "
            "Administrative Officer shall collect fees for services."
        ),
        document_id="tdfol-uscode-heading-trimmed-actor",
        citation="2 U.S.C. 5541",
    )

    records = report.ir_document.views["tdfol_formula"].payload["records"]

    assert records[0]["formula"] == (
        "O(collect_fees_for_services(chief_administrative_officer))"
    )
    assert records[0]["parse_ok"] is True
    assert report.round_trip.extra_losses["tdfol_parse_failure_ratio"] == 0.0


def test_tdfol_bridge_guidance_activates_from_target_metric_evidence() -> None:
    from ipfs_datasets_py.logic.bridge.fol_tdfol import FolTdfolBridgeAdapter

    adapter = FolTdfolBridgeAdapter()
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="tdfol-target-metric-guidance",
        citation="Bridge Layer Guided TDFOL",
        compiler_guidance={
            "evidence": [
                {
                    "program_synthesis_scope": "tdfol",
                    "target_component": "TDFOL.prover",
                    "target_metrics": ["tdfol_parse_failure_ratio"],
                }
            ],
        },
    )

    assert report.ir_document.metadata["compiler_guidance_formula_count"] == 1
    assert report.proof_gate.compiles is True
    assert report.proof_gate.failure_ratio == 0.0


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
    assert report.round_trip.extra_losses["legal_ir_view_cross_entropy_loss"] == 0.0
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


def test_zkp_attestation_bridge_promotes_top_level_packet_guidance() -> None:
    from ipfs_datasets_py.logic.bridge.zkp_attestation import ZkpAttestationBridgeAdapter
    from ipfs_datasets_py.logic.zkp import compiler_guidance_ref_from_metadata

    guidance = {
        "program_synthesis_scope": "zkp",
        "route": "repair_zkp_attestation_bridge",
        "source": "compiler_guidance_distillation_v1",
        "target_component": "zkp.circuits",
    }

    adapter = ZkpAttestationBridgeAdapter()
    report = adapter.evaluate(
        "The agency shall publish notice before the permit takes effect.",
        document_id="zkp-top-level-packet-guidance",
        citation="ZKP Top Level Packet Guidance",
        compiler_guidance=guidance,
    )

    record = report.ir_document.views["zkp_attestations"].payload["records"][0]
    expected_ref = compiler_guidance_ref_from_metadata(guidance)
    assert report.metadata["compiler_guidance_applied"] is True
    assert record["compiler_guidance_ref"] == expected_ref
    assert record["public_inputs"]["compiler_guidance_ref"] == expected_ref
    assert record["attestation_view"]["compiler_guidance_ref"] == expected_ref
    assert report.proof_gate.compiles is True


def test_form_certificate_serializes_distinct_zkp_public_inputs() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver
    from ipfs_datasets_py.logic.zkp.form_circuit import FormCompletionCertificate

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    certificate = FormCompletionCertificate(
        proof=proof,
        form_id="notice-form",
        source_pdf="notice.pdf",
        public_inputs={
            "form_template_hash": "f" * 64,
            "rule_set_hash": "r" * 64,
            "verdicts_hash": "v" * 64,
        },
    )

    serialized = certificate.to_dict()

    assert serialized["public_inputs"] == certificate.public_inputs
    assert serialized["zkp_public_inputs"]["attestation_ref"] == (
        proof.public_inputs["attestation_ref"]
    )
    assert serialized["zkp_public_inputs"]["theorem_hash"] == (
        proof.public_inputs["theorem_hash"]
    )
    assert serialized["zkp_attestation"]["attestation_ref"] == (
        proof.public_inputs["attestation_ref"]
    )
    assert "form_template_hash" not in serialized["zkp_public_inputs"]


def test_zkp_public_record_recovers_inputs_from_serialized_proof() -> None:
    from ipfs_datasets_py.logic.bridge.zkp_attestation import _public_attestation_record
    from ipfs_datasets_py.logic.zkp import (
        ZKPProver,
        zkp_attestation_legal_ir_view_loss,
    )

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    record = _public_attestation_record(
        {
            "axiom_count": 2,
            "proof": proof.to_dict(),
            "proof_hash": "p" * 64,
            "source_id": "tdfol:norm:0",
            "theorem": proof.public_inputs["theorem"],
            "verified": True,
        }
    )

    assert record["attestation_ref"] == record["public_inputs"]["attestation_ref"]
    assert record["attestation_view"]["attestation_ref"] == record["attestation_ref"]
    assert record["theorem_hash"] == record["public_inputs"]["theorem_hash"]
    assert zkp_attestation_legal_ir_view_loss([record]) == 0.0


def test_zkp_public_record_recovers_duplicated_fields_from_proof_only() -> None:
    from ipfs_datasets_py.logic.bridge.zkp_attestation import _public_attestation_record
    from ipfs_datasets_py.logic.zkp import (
        ZKPProver,
        zkp_attestation_legal_ir_view_loss,
    )

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(submit_report(state))",
        ["O(submit_report(state))", "uses_predicate(submit_report)"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "compiler_guidance_ref": "d" * 64,
            "compiler_guidance_version": 1,
        },
    )

    record = _public_attestation_record(
        {
            "axiom_count": 2,
            "proof": proof.to_dict(),
            "source_id": "tdfol:norm:report",
            "theorem": proof.public_inputs["theorem"],
            "verified": True,
        }
    )

    assert record["proof_hash"] == proof.metadata["attestation_view"]["proof_digest"]
    assert record["compiler_guidance_ref"] == "d" * 64
    assert record["public_inputs"]["attestation_ref"] == (
        proof.public_inputs["attestation_ref"]
    )
    assert record["public_inputs"]["compiler_guidance_ref"] == "d" * 64
    assert zkp_attestation_legal_ir_view_loss([record]) == 0.0


def test_zkp_attestation_records_cache_reuses_generated_attestations(monkeypatch) -> None:
    import ipfs_datasets_py.logic.zkp as zkp
    from ipfs_datasets_py.logic.bridge import zkp_attestation

    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    with zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE_LOCK:
        zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE.clear()
    original_prover = zkp.ZKPProver
    calls = {"prover_init": 0}

    class CountingProver(original_prover):
        def __init__(self, *args, **kwargs):
            calls["prover_init"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zkp, "ZKPProver", CountingProver)
    formula_records = [
        {
            "formula": "O(publish_notice(agency))",
            "predicates": ("publish_notice",),
            "source_id": "tdfol:norm:notice",
        }
    ]

    first = zkp_attestation._zkp_attestation_records(
        formula_records,
        prover_kwargs={"backend": "simulated", "enable_caching": True},
        verifier_kwargs={"backend": "simulated"},
    )
    second = zkp_attestation._zkp_attestation_records(
        formula_records,
        prover_kwargs={"backend": "simulated", "enable_caching": True},
        verifier_kwargs={"backend": "simulated"},
    )

    assert calls["prover_init"] == 1
    assert first == second
    assert first is not second
    assert first[0] is not second[0]


def test_zkp_attestation_records_use_persistent_disk_cache(
    tmp_path,
    monkeypatch,
) -> None:
    import ipfs_datasets_py.logic.zkp as zkp
    from ipfs_datasets_py.logic.bridge import zkp_attestation

    cache_dir = tmp_path / "legal-ir-metric-cache"
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "1")
    with zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE_LOCK:
        zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE.clear()
    original_prover = zkp.ZKPProver
    calls = {"prover_init": 0}

    class CountingProver(original_prover):
        def __init__(self, *args, **kwargs):
            calls["prover_init"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zkp, "ZKPProver", CountingProver)
    formula_records = [
        {
            "formula": "O(publish_notice(agency))",
            "predicates": ("publish_notice",),
            "source_id": "tdfol:norm:notice",
        }
    ]
    prover_kwargs = {"backend": "simulated", "enable_caching": True}
    verifier_kwargs = {"backend": "simulated"}

    first = zkp_attestation._zkp_attestation_records(
        formula_records,
        prover_kwargs=prover_kwargs,
        verifier_kwargs=verifier_kwargs,
    )
    cache_key = zkp_attestation._zkp_attestation_records_cache_key(
        formula_records,
        prover_kwargs=prover_kwargs,
        verifier_kwargs=verifier_kwargs,
    )
    cache_path = zkp_attestation._zkp_attestation_records_disk_cache_path(cache_key)
    assert cache_path is not None
    assert cache_path.is_file()
    with zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE_LOCK:
        zkp_attestation._ZKP_ATTESTATION_RECORD_CACHE.clear()

    second = zkp_attestation._zkp_attestation_records(
        formula_records,
        prover_kwargs=prover_kwargs,
        verifier_kwargs=verifier_kwargs,
    )

    assert calls["prover_init"] == 1
    assert first == second
    assert first is not second
    assert first[0] is not second[0]


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


def test_zkp_prover_derives_guidance_ref_from_packet_shaped_metadata() -> None:
    from ipfs_datasets_py.logic.zkp import (
        ZKPProver,
        ZKPVerifier,
        compiler_guidance_contract_from_metadata,
        compiler_guidance_ref_from_metadata,
    )

    metadata = {
        "circuit_ref": "legal_ir_zkp_attestation@v1",
        "circuit_version": 1,
        "program_synthesis_scope": "zkp",
        "route": "repair_zkp_attestation_bridge",
        "source": "compiler_guidance_distillation_v1",
        "target_component": "zkp.circuits",
    }
    theorem = "O(publish_notice(agency))"
    axioms = [theorem, "uses_predicate(publish_notice)"]

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(theorem, axioms, metadata=metadata)
    verifier = ZKPVerifier(backend="simulated")

    assert compiler_guidance_contract_from_metadata(metadata) == {
        "program_synthesis_scope": "zkp",
        "route": "repair_zkp_attestation_bridge",
        "source": "compiler_guidance_distillation_v1",
        "target_component": "zkp.circuits",
    }
    assert proof.public_inputs["compiler_guidance_ref"] == (
        compiler_guidance_ref_from_metadata(metadata)
    )
    assert (
        proof.metadata["attestation_view"]["compiler_guidance_ref"]
        == proof.public_inputs["compiler_guidance_ref"]
    )
    assert verifier.verify_proof(proof) is True


def test_zkp_guidance_ref_normalizes_json_encoded_packet_bundle() -> None:
    from ipfs_datasets_py.logic.zkp import (
        compiler_guidance_contract_from_metadata,
        compiler_guidance_ref_from_metadata,
    )

    bundled = {
        "bundle": (
            '{"program_synthesis_scope":"zkp",'
            '"route":"repair_zkp_attestation_bridge",'
            '"source":"compiler_guidance_distillation_v1",'
            '"target_component":"zkp.circuits"}'
        )
    }
    explicit = {
        "compiler_guidance_contract": {
            "program_synthesis_scope": "zkp",
            "route": "repair_zkp_attestation_bridge",
            "source": "compiler_guidance_distillation_v1",
            "target_component": "zkp.circuits",
        }
    }

    assert compiler_guidance_contract_from_metadata(bundled) == (
        compiler_guidance_contract_from_metadata(explicit)
    )
    assert compiler_guidance_ref_from_metadata(bundled) == (
        compiler_guidance_ref_from_metadata(explicit)
    )


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


def test_zkp_prover_replaces_caller_supplied_stale_attestation_view() -> None:
    from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={
            "attestation_view": {
                "attestation_ref": "0" * 64,
                "attestation_view_version": 1,
            },
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
        },
    )
    verifier = ZKPVerifier(backend="simulated")

    assert proof.metadata["attestation_view"]["attestation_ref"] == (
        proof.public_inputs["attestation_ref"]
    )
    assert proof.metadata["attestation_view"]["attestation_ref"] != "0" * 64
    assert verifier.verify_proof(proof) is True


def test_zkp_attestation_refresh_repairs_public_input_mutation() -> None:
    from ipfs_datasets_py.logic.zkp import (
        ZKPProver,
        ZKPVerifier,
        refresh_proof_attestation,
    )

    prover = ZKPProver(backend="simulated", enable_caching=False)
    proof = prover.generate_proof(
        "O(publish_notice(agency))",
        ["O(publish_notice(agency))", "uses_predicate(publish_notice)"],
        metadata={"circuit_ref": "legal_ir_zkp_attestation@v1", "circuit_version": 1},
    )
    verifier = ZKPVerifier(backend="simulated")

    proof.public_inputs["compiler_guidance_ref"] = "c" * 64
    proof.public_inputs["compiler_guidance_version"] = 1

    assert verifier.verify_proof(proof) is False

    refresh_proof_attestation(proof)

    assert proof.public_inputs["attestation_ref"] == (
        proof.metadata["attestation_view"]["attestation_ref"]
    )
    assert proof.metadata["attestation_view"]["compiler_guidance_ref"] == "c" * 64
    assert verifier.verify_proof(proof) is True


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


def test_multiview_training_target_rebalances_short_repealed_usc_excerpt() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    report = evaluate_legal_ir_multiview(
        (
            "§§1231 to 1238. Repealed. Pub. L. 85-861, §36A, Sept. 2, "
            "1958, 72 Stat. 1569 Section 1231, act Sept. 3, 1954, ch. "
            "1257, title III, §308, 68 Stat. 1155, provided for promotion "
            "to first lieutenant. See section 14301 et seq. of Title 10, "
            "Armed Forces."
        ),
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="multiview-short-repealed-usc-excerpt",
        citation="50 U.S.C. 1231 to 1238",
        cache=False,
        evaluate_provers=False,
    )

    raw_distribution = report.view_distribution()
    target_distribution = report.training_target().view_distribution
    assert set(target_distribution) == {
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert raw_distribution["deontic.ir"] > 0.45
    assert target_distribution["deontic.ir"] <= 0.28
    assert target_distribution["knowledge_graphs.neo4j_compat"] >= 0.26
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-9


def test_multiview_training_target_applies_compiler_guidance_view_gaps() -> None:
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    text = (
        "42 U.S.C. 18726.: §18726. Savings provision Nothing in this part "
        "affects the authority, existing on the day before November 15, 2021, "
        "of any other Federal department or agency, including the authority "
        "provided to the Secretary of Homeland Security."
    )
    compiler_guidance = {
        "bundle": {
            "route": "repair_multiview_legal_ir_loss",
            "source": "compiler_guidance_distillation_v1",
            "target_component": "bridge.contracts",
        },
        "evidence": [
            {
                "bridge_failure_name": "legal_ir_view_cross_entropy_loss",
                "legal_ir_component_gaps": {
                    "TDFOL.prover": 0.037693082997,
                    "deontic.ir": -0.068368644606,
                    "knowledge_graphs.neo4j_compat": 0.22812109314,
                },
                "legal_ir_underrepresented_components": [
                    "knowledge_graphs.neo4j_compat",
                    "TDFOL.prover",
                ],
                "predicted_view": "knowledge_graphs.neo4j_compat",
                "target_view": "knowledge_graphs.neo4j_compat",
            }
        ],
    }

    unguided = evaluate_legal_ir_multiview(
        text,
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="bridge-contract-guidance-unguided",
        citation="42 U.S.C. 18726",
        cache=False,
        evaluate_provers=False,
    )
    guided = evaluate_legal_ir_multiview(
        text,
        bridge_names=("deontic_norms", "fol_tdfol"),
        document_id="bridge-contract-guidance-guided",
        citation="42 U.S.C. 18726",
        compiler_guidance=compiler_guidance,
        cache=False,
        evaluate_provers=False,
    )

    target_distribution = guided.training_target().view_distribution
    metadata = guided.document.metadata

    assert metadata["compiler_guidance_bridge_contract_target_lanes"] == [
        "TDFOL.prover",
        "knowledge_graphs.neo4j_compat",
    ]
    assert (
        target_distribution["knowledge_graphs.neo4j_compat"]
        > unguided.training_target().view_distribution[
            "knowledge_graphs.neo4j_compat"
        ]
    )
    assert target_distribution["TDFOL.prover"] > 0.0
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-9


def test_bridge_contract_guidance_strength_uses_probability_and_component_gaps() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH,
        _compiler_guidance_bridge_contract_metadata,
    )

    metadata = _compiler_guidance_bridge_contract_metadata(
        {
            "bundle": {
                "route": "repair_multiview_legal_ir_loss",
                "target_component": "bridge.contracts",
            },
            "evidence": [
                {
                    "bridge_failure_name": "legal_ir_view_cross_entropy_loss",
                    "legal_ir_component_gaps": {
                        "CEC.native": 0.174666463809,
                        "TDFOL.prover": 0.014560416953,
                        "deontic.ir": -0.020584266796,
                        "knowledge_graphs.neo4j_compat": 0.051164392521,
                    },
                    "legal_ir_underrepresented_components": [
                        "CEC.native",
                        "knowledge_graphs.neo4j_compat",
                        "TDFOL.prover",
                    ],
                    "pipeline_stage_diagnostics": {
                        "legal_ir_component_gap_max": 0.174666463809,
                        "modal_family_target_probability_gap": 0.298229205982,
                    },
                    "predicted_view": "CEC.native",
                    "target_view": "CEC.native",
                }
            ],
        }
    )

    target_distribution = metadata[
        "compiler_guidance_bridge_contract_target_distribution"
    ]

    assert metadata["compiler_guidance_bridge_contract_projection_strength"] > (
        _BRIDGE_CONTRACT_GUIDANCE_PROJECTION_STRENGTH
    )
    assert metadata["compiler_guidance_bridge_contract_target_probability_gap"] == (
        0.298229205982
    )
    assert metadata["compiler_guidance_component_gap_max"] == 0.174666463809
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "knowledge_graphs.neo4j_compat",
    }
    assert target_distribution["CEC.native"] > target_distribution["TDFOL.prover"]


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


def test_multiview_training_target_projects_packet_official_usc_contract_patterns() -> None:
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
    samples = {
        "intergovernmental_report": (
            "U.S.C. Title 33 - NAVIGATION AND NAVIGABLE WATERS 33 U.S.C. "
            "United States Code, 2024 Edition Sec. 1521 - Negotiations with "
            "Canada and Mexico; report to Congress From the U.S. Government "
            "Publishing Office, www.gpo.gov §1521. The President of the "
            "United States is authorized and requested to enter into "
            "negotiations with the Governments of Canada and Mexico to "
            "determine the need for intergovernmental understandings, "
            "agreements, or treaties. The President shall report to the "
            "Congress the actions taken, the progress achieved, and "
            "recommendations for further action. (Pub. L. 93-627, §22, "
            "Jan. 3, 1975, 88 Stat. 2147.)"
        ),
        "subsidy_contract": (
            "§57516. Operating-differential subsidies If the Secretary of "
            "Transportation considers it necessary, the Secretary may make a "
            "contract with a charterer of a vessel owned by the Secretary for "
            "payment of an operating-differential subsidy, subject to the "
            "same limitations and restrictions. (Pub. L. 109-304, §8(c), "
            "Oct. 6, 2006, 120 Stat. 1667.)"
        ),
        "program_funding": (
            "§15824. State Technologies Advancement Collaborative The "
            "Secretary, in cooperation with the States, shall establish a "
            "cooperative program for research, development, demonstration, "
            "and deployment of technologies. Funding for the Collaborative "
            "may be provided from amounts specifically appropriated. There "
            "are authorized to carry out this section such sums as are "
            "necessary for each of fiscal years 2006 through 2010. (Pub. "
            "L. 109-58, title I, §127, Aug. 8, 2005, 119 Stat. 619.)"
        ),
        "installment_schedule": (
            "§471. Initial payment and annual installments of charges "
            "generally Any entryman or applicant shall pay into the "
            "reclamation fund 5 per centum of the construction charge as an "
            "initial installment, and shall pay the balance of said charge "
            "in annual installments. The first annual installment shall "
            "become due and payable on December 1 of the fifth calendar "
            "year after the initial installment. (Aug. 13, 1914, ch. 247, "
            "§1, 38 Stat. 686.) Editorial Notes Codification."
        ),
        "contractor_reporting": (
            "U.S.C. Title 41 - PUBLIC CONTRACTS 41 U.S.C. United States "
            "Code, 2024 Edition Sec. 8703 - Contractor responsibilities "
            "From the U.S. Government Publishing Office, www.gpo.gov "
            "§8703. Each contracting agency shall include in each prime "
            "contract a requirement that the prime contractor shall "
            "cooperate fully with a Federal Government agency investigating "
            "a violation. A prime contractor or subcontractor shall promptly "
            "report the possible violation in writing to the inspector "
            "general. (Pub. L. 111-350, §3, Jan. 4, 2011, 124 Stat. 3839.)"
        ),
        "medical_assistance": (
            "U.S.C. Title 38 - VETERANS' BENEFITS 38 U.S.C. United States "
            "Code, 2024 Edition CHAPTER 17 - HOSPITAL, NURSING HOME, "
            "DOMICILIARY, AND MEDICAL CARE Sec. 1731 - Assistance to the "
            "Republic of the Philippines From the U.S. Government Publishing "
            "Office, www.gpo.gov §1731. The President is authorized to assist "
            "the Republic of the Philippines in fulfilling its responsibility "
            "in providing medical care and treatment for Commonwealth Army "
            "veterans and new Philippine Scouts in need of such care and "
            "treatment for service-connected disabilities and non-service-"
            "connected disabilities under certain conditions. Editorial Notes "
            "Prior Provisions Amendments Statutory Notes and Related "
            "Subsidiaries Effective Date."
        ),
        "clean_hulls_administration": (
            "U.S.C. Title 33 - NAVIGATION AND NAVIGABLE WATERS 33 U.S.C. "
            "United States Code, 2024 Edition CHAPTER 51 - CLEAN HULLS "
            "Sec. 3803 - Administration and enforcement From the U.S. "
            "Government Publishing Office, www.gpo.gov §3803. Unless "
            "otherwise specified in this chapter, with respect to a vessel, "
            "the Secretary shall administer and enforce the Convention and "
            "this chapter. The Administrator shall administer and enforce "
            "subchapter III. The Administrator and the Secretary may each "
            "prescribe and enforce regulations as may be necessary to carry "
            "out their respective responsibilities under this chapter."
        ),
        "house_internal_delivery_fees": (
            "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, "
            "2024 Edition CHAPTER 55 - HOUSE OF REPRESENTATIVES OFFICERS "
            "AND ADMINISTRATION Sec. 5541 - Fees for internal delivery in "
            "House of Representatives of nonpostage mail from outside "
            "sources From the U.S. Government Publishing Office, www.gpo.gov "
            "§5541. Effective with respect to fiscal years beginning with "
            "fiscal year 1995, the Chief Administrative Officer is "
            "authorized to collect fees equal to the applicable postage. "
            "Amounts received by the Chief Administrative Officer as fees "
            "under the preceding sentence shall be deposited in the Treasury "
            "for credit to the account of the Office of the Chief "
            "Administrative Officer. Editorial Notes Codification."
        ),
        "nato_contribution_budget_limit": (
            "U.S.C. Title 10 - ARMED FORCES 10 U.S.C. United States Code, "
            "2024 Edition CHAPTER 134 - MISCELLANEOUS ADMINISTRATIVE "
            "PROVISIONS Sec. 2263 - United States contributions to the "
            "North Atlantic Treaty Organization common-funded budgets From "
            "the U.S. Government Publishing Office, www.gpo.gov §2263. The "
            "total amount contributed by the Secretary of Defense in any "
            "fiscal year for the common-funded budgets of NATO may be an "
            "amount in excess of the maximum amount that would otherwise be "
            "applicable to those contributions in such fiscal year under the "
            "fiscal year 1998 baseline limitation. Definitions. The term "
            "common-funded budgets of NATO means the Military Budget, the "
            "Security Investment Program, and the Civil Budget of the North "
            "Atlantic Treaty Organization."
        ),
    }

    projected = {
        name: _compact_official_usc_contract_distribution(distribution, text=text)
        for name, text in samples.items()
    }

    assert projected["intergovernmental_report"]["TDFOL.prover"] > 0.24
    assert projected["subsidy_contract"]["CEC.native"] > 0.21
    assert projected["program_funding"]["deontic.ir"] > 0.40
    assert projected["installment_schedule"]["TDFOL.prover"] > 0.29
    assert projected["contractor_reporting"]["deontic.ir"] > 0.40
    assert projected["medical_assistance"]["CEC.native"] > 0.40
    assert projected["clean_hulls_administration"]["CEC.native"] > 0.36
    assert projected["house_internal_delivery_fees"]["deontic.ir"] > 0.43
    assert projected["nato_contribution_budget_limit"]["deontic.ir"] > 0.42
    for compacted in projected.values():
        assert set(compacted) == {
            "CEC.native",
            "TDFOL.prover",
            "deontic.ir",
            "knowledge_graphs.neo4j_compat",
        }
        assert abs(sum(compacted.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_liability_and_reporting_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    liability = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "36 U.S.C. 50111. Liability for acts of officers and agents. "
            "The corporation is liable for the acts of its officers and agents "
            "acting within the scope of their authority."
        ),
    )
    reporting = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "50 U.S.C. 1906. Annual report. The Secretary shall submit to the "
            "President and to the congressional intelligence committees an annual "
            "report. The report shall contain an analysis of the program."
        ),
    )

    assert liability["deontic.ir"] > distribution["deontic.ir"]
    assert liability["CEC.native"] > distribution["CEC.native"]
    assert reporting["deontic.ir"] > distribution["deontic.ir"]
    assert reporting["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert abs(sum(liability.values()) - 1.0) < 1e-9
    assert abs(sum(reporting.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_determination_and_renaming_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    determination = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 1591. Determination of critical areas by President; "
            "requisite conditions. The authority shall not be exercised unless "
            "the President shall have determined that the area is critical."
        ),
    )
    renaming = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "16 U.S.C. 217a. Change in name of Abraham Lincoln National "
            "Historical Park. The park shall on and after September 8, 1959, "
            "be known as Abraham Lincoln Birthplace National Historic Site, and "
            "any law in which the park is designated or referred to shall be "
            "held to refer to such park under that name."
        ),
    )

    assert determination["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert determination["CEC.native"] > distribution["CEC.native"]
    assert renaming["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert renaming["CEC.native"] > distribution["CEC.native"]
    assert abs(sum(determination.values()) - 1.0) < 1e-9
    assert abs(sum(renaming.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_definition_purpose_and_policy_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    definition = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "6 U.S.C. 312. Definition. In this subchapter, the term Nuclear "
            "Incident Response Team means a resource that includes Department "
            "of Energy and Environmental Protection Agency response entities. "
            "Editorial Notes Codification."
        ),
    )
    purpose = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 285. Purpose of Institute. The general purpose of the "
            "National Institute is the conduct and support of research, "
            "training, health information dissemination, and other programs."
        ),
    )
    policy = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 4501. Congressional statement of purpose. It is the "
            "policy of the Congress and the purpose of this chapter to provide "
            "for the development of a national urban policy and to encourage "
            "orderly growth."
        ),
    )

    assert definition["CEC.native"] > distribution["CEC.native"]
    assert definition["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert purpose["CEC.native"] > distribution["CEC.native"]
    assert purpose["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert policy["CEC.native"] > distribution["CEC.native"]
    assert policy["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert abs(sum(definition.values()) - 1.0) < 1e-9
    assert abs(sum(purpose.values()) - 1.0) < 1e-9
    assert abs(sum(policy.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_editorial_status_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _compact_official_usc_contract_distribution,
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    transferred = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 16935. Transferred. Editorial Notes Codification "
            "Section 16935 was editorially reclassified as section 21501 of "
            "Title 34, Crime Control and Law Enforcement."
        ),
    )
    omitted = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "22 U.S.C. 297a. Omitted. Editorial Notes Codification. Section, "
            "which related to leaseholds, was not repeated in subsequent "
            "appropriation acts."
        ),
    )
    compacted = _compact_official_usc_contract_distribution(
        {
            "CEC.native": 0.156,
            "TDFOL.prover": 0.145,
            "deontic.ir": 0.162,
            "external_provers.router": 0.121,
            "knowledge_graphs.neo4j_compat": 0.134,
            "modal.frame_logic": 0.142,
            "zkp.circuits": 0.140,
        },
        text=(
            "§3796ee-7. Transferred Editorial Notes Codification Section "
            "3796ee-7 was editorially reclassified as section 10408 of Title "
            "34, Crime Control and Law Enforcement."
        ),
    )

    assert transferred["CEC.native"] > distribution["CEC.native"]
    assert transferred["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert transferred["deontic.ir"] < distribution["deontic.ir"]
    assert omitted["CEC.native"] > distribution["CEC.native"]
    assert omitted["deontic.ir"] < distribution["deontic.ir"]
    assert set(compacted) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
    }
    assert compacted["CEC.native"] > compacted["deontic.ir"]
    assert compacted["knowledge_graphs.neo4j_compat"] > compacted["deontic.ir"]
    assert abs(sum(transferred.values()) - 1.0) < 1e-9
    assert abs(sum(omitted.values()) - 1.0) < 1e-9
    assert abs(sum(compacted.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_asset_transfer_rules() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    projected = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "29 U.S.C. 1414. Asset transfer rules. A transfer of assets from "
            "a multiemployer plan to another plan shall comply with "
            "asset-transfer rules which shall be adopted by the plan and "
            "applied uniformly."
        ),
    )

    assert projected["deontic.ir"] > distribution["deontic.ir"]
    assert projected["TDFOL.prover"] >= 0.24
    assert projected["knowledge_graphs.neo4j_compat"] < distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_regulatory_cost_estimates_and_exemptions() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    regulatory_costs = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "2 U.S.C. 1511. Cost of regulations. The Director shall estimate "
            "the costs of Federal regulations to State, local, and tribal "
            "governments and the private sector."
        ),
    )
    construction = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "50 U.S.C. 2205. Construction. Nothing in this chapter shall "
            "apply to the abandonment or failure to take possession of spoils "
            "of war by troops in the field."
        ),
    )

    assert regulatory_costs["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert regulatory_costs["TDFOL.prover"] > regulatory_costs["CEC.native"]
    assert construction["deontic.ir"] > distribution["deontic.ir"]
    assert construction["deontic.ir"] > construction["CEC.native"]
    assert abs(sum(regulatory_costs.values()) - 1.0) < 1e-9
    assert abs(sum(construction.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_safety_policy_and_savings_sections() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    safety = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "33 U.S.C. 1509. Marine environmental protection and navigational "
            "safety. The Secretary shall prescribe and enforce procedures and "
            "shall issue and enforce regulations for safety zones."
        ),
    )
    policy = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "6 U.S.C. 543. Review of congressional committee structures. It is "
            "the sense of Congress that each House should review its committee "
            "structure in light of reorganization of responsibilities."
        ),
    )
    savings = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "30 U.S.C. 541h. Savings provision. Nothing in this chapter shall "
            "be deemed to amend or repeal any provision of chapter 12."
        ),
    )
    effect_on_existing_law = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 6979b. Effect on existing law. Nothing in this section "
            "shall be construed as affecting or limiting the authority of any "
            "State under other provisions of law."
        ),
    )

    assert safety["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert safety["deontic.ir"] > distribution["deontic.ir"]
    assert policy["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert policy["CEC.native"] > distribution["CEC.native"]
    assert savings["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert savings["CEC.native"] > distribution["CEC.native"]
    assert effect_on_existing_law["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert effect_on_existing_law["CEC.native"] > distribution["CEC.native"]
    assert abs(sum(safety.values()) - 1.0) < 1e-9
    assert abs(sum(policy.values()) - 1.0) < 1e-9
    assert abs(sum(savings.values()) - 1.0) < 1e-9
    assert abs(sum(effect_on_existing_law.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_packet_savings_and_rulemaking_deadlines() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    existing_authority_savings = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 18726. Savings provision. Nothing in this part affects "
            "the authority, existing on the day before November 15, 2021, of "
            "any other Federal department or agency, including the authority "
            "provided to the Secretary of Homeland Security."
        ),
    )
    pet_food_rulemaking = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "21 U.S.C. 2102. Ensuring the safety of pet food. Not later than "
            "2 years after September 27, 2007, the Secretary shall by "
            "regulation establish processing standards for pet food and "
            "updated standards for the labeling of pet food."
        ),
    )

    assert existing_authority_savings["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert existing_authority_savings["CEC.native"] > distribution["CEC.native"]
    assert pet_food_rulemaking["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert pet_food_rulemaking["deontic.ir"] > distribution["deontic.ir"]
    assert abs(sum(existing_authority_savings.values()) - 1.0) < 1e-9
    assert abs(sum(pet_food_rulemaking.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_bootstrap_bridge_samples() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    act_savings = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "33 U.S.C. 701e. Effect of act June 22, 1936, on provisions for "
            "Mississippi River and other projects. Nothing in this Act shall "
            "be construed as repealing or amending any provision of sections "
            "702a through 704 of this title."
        ),
    )
    false_advertising = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "15 U.S.C. 52. Dissemination of false advertisements. It shall be "
            "unlawful for any person to disseminate any false advertisement. "
            "The dissemination of any false advertisement shall be an unfair "
            "or deceptive act or practice in or affecting commerce."
        ),
    )
    performance_plan = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "38 U.S.C. 725. Annual performance plan for political appointees. "
            "The Secretary shall conduct an annual performance plan for each "
            "political appointee. Each annual performance plan shall include "
            "an assessment of whether the appointee is meeting the goals."
        ),
    )

    assert act_savings["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert act_savings["CEC.native"] > distribution["CEC.native"]
    assert false_advertising["deontic.ir"] > distribution["deontic.ir"]
    assert false_advertising["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert performance_plan["deontic.ir"] > distribution["deontic.ir"]
    assert performance_plan["TDFOL.prover"] >= distribution["TDFOL.prover"]
    assert abs(sum(act_savings.values()) - 1.0) < 1e-9
    assert abs(sum(false_advertising.values()) - 1.0) < 1e-9
    assert abs(sum(performance_plan.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_packet_100_bridge_contracts() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    administration_enforcement = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "33 U.S.C. 3803. Administration and enforcement. Unless otherwise "
            "specified, the Secretary shall administer and enforce the "
            "Convention and this chapter. The Administrator and Secretary may "
            "prescribe and enforce regulations."
        ),
    )
    medical_assistance = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "38 U.S.C. 1731. Veterans' benefits. The President is authorized "
            "to assist the Republic of the Philippines in providing medical "
            "care and treatment for veterans with service-connected "
            "disabilities."
        ),
    )
    fee_deposit = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "2 U.S.C. 5541. Fees for internal delivery. The Chief "
            "Administrative Officer is authorized to collect fees equal to "
            "the applicable postage. Amounts received as fees shall be "
            "deposited in the Treasury for credit to the account."
        ),
    )
    contribution_limit = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "10 U.S.C. 2263. Contributions to NATO common-funded budgets. "
            "The total amount contributed by the Secretary of Defense in any "
            "fiscal year for common-funded budgets may exceed the fiscal "
            "year 1998 baseline limitation."
        ),
    )

    assert administration_enforcement["CEC.native"] > distribution["CEC.native"]
    assert administration_enforcement["CEC.native"] > administration_enforcement[
        "deontic.ir"
    ]
    assert medical_assistance["CEC.native"] > distribution["CEC.native"]
    assert medical_assistance["CEC.native"] > medical_assistance["deontic.ir"]
    assert fee_deposit["deontic.ir"] > distribution["deontic.ir"]
    assert contribution_limit["deontic.ir"] > distribution["deontic.ir"]
    assert contribution_limit["TDFOL.prover"] > distribution["TDFOL.prover"]
    for projected in (
        administration_enforcement,
        medical_assistance,
        fee_deposit,
        contribution_limit,
    ):
        assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_packet_2711_bridge_samples() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    agency_goal = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "42 U.S.C. 18403. Goal for Agency space technology. It is "
            "critical that NASA maintain an Agency space technology base that "
            "helps align mission directorate investments and supports long "
            "term needs."
        ),
    )
    county_payments = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "7 U.S.C. 1012. Payments to counties. As soon as practicable "
            "after the end of each calendar year, the Secretary shall pay to "
            "the county 25 per centum of net revenues. Payments shall be made "
            "on the condition that they are used for school or road purposes."
        ),
    )
    teacher_participation = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "20 U.S.C. 3922. Participation of teachers from private schools. "
            "The Foundation shall, after consultation with appropriate "
            "private school representatives, make provision for the benefit "
            "of teachers in order to assure equitable participation."
        ),
    )
    surveys_projects = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "30 U.S.C. 553. Duties of Secretary; surveys, research, etc.; "
            "projects. The Secretary is authorized to conduct surveys, "
            "investigations, and research, to publish and disseminate results, "
            "and to plan and execute projects for control of fires."
        ),
    )
    patronage_pools = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "12 U.S.C. 2147. Patronage pools. The consolidated bank may "
            "establish separate patronage pools and allocate revenues, "
            "expenses, and net savings among such pools on an equitable basis."
        ),
    )
    repealed_status = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "10 U.S.C. 1183. Repealed. Pub. L. 105-261, div. A, title V, "
            "section 503(a), Oct. 17, 1998, 112 Stat. 2003. Section related "
            "to convening and determinations of boards of review."
        ),
    )
    nautical_schools = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "46 U.S.C. 51702. Civilian nautical schools. Definition. In this "
            "section, the term civilian nautical school means a school "
            "operated in the United States. Inspection. Each civilian "
            "nautical school is subject to inspection by the Secretary. "
            "Rating and Certification. The Secretary may provide for rating "
            "and certification of civilian nautical schools."
        ),
    )
    mining_leases = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "25 U.S.C. 401. Leases for mining purposes of unallotted lands. "
            "The Secretary is authorized to lease for mining purposes lands "
            "reserved from allotment. Provided, That production of oil and "
            "gas may be taxed, and such tax shall not become a lien against "
            "the land."
        ),
    )

    assert agency_goal["CEC.native"] > distribution["CEC.native"]
    assert agency_goal["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert county_payments["deontic.ir"] > distribution["deontic.ir"]
    assert county_payments["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert teacher_participation["deontic.ir"] > distribution["deontic.ir"]
    assert teacher_participation["CEC.native"] >= distribution["CEC.native"]
    assert surveys_projects["CEC.native"] > distribution["CEC.native"]
    assert surveys_projects["TDFOL.prover"] >= distribution["TDFOL.prover"]
    assert patronage_pools["deontic.ir"] > distribution["deontic.ir"]
    assert patronage_pools["CEC.native"] > distribution["CEC.native"]
    assert repealed_status["CEC.native"] > repealed_status["deontic.ir"]
    assert repealed_status["knowledge_graphs.neo4j_compat"] > repealed_status[
        "deontic.ir"
    ]
    assert nautical_schools["CEC.native"] > distribution["CEC.native"]
    assert nautical_schools["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert mining_leases["deontic.ir"] > distribution["deontic.ir"]
    assert mining_leases["TDFOL.prover"] > distribution["TDFOL.prover"]
    for projected in (
        agency_goal,
        county_payments,
        teacher_participation,
        surveys_projects,
        patronage_pools,
        repealed_status,
        nautical_schools,
        mining_leases,
    ):
        assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_packet_207_bridge_contracts() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    annual_cost_report = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "16 U.S.C. 1544. Annual cost analysis by Fish and Wildlife "
            "Service. On or before January 15, 1990, and each January 15 "
            "thereafter, the Secretary shall submit to Congress an annual "
            "report covering the preceding fiscal year."
        ),
    )
    retirement_election = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "50 U.S.C. 2151. Application of Federal Employees' Retirement "
            "System to Agency employees. Employees shall be subject to "
            "chapter 84 of title 5. An employee may elect to become subject "
            "to chapter 84 of title 5, and such election shall be irrevocable."
        ),
    )
    penalty_noncompliance = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "26 U.S.C. 9707. Failure to pay premium. There is imposed a "
            "penalty on failure to pay any premium. The noncompliance period "
            "begins on the due date and ends on the date of payment, and the "
            "person failing to meet the requirements shall be liable for the "
            "penalty."
        ),
    )
    seal_notice = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "28 U.S.C. 608. Seal. The Director shall use a seal approved by "
            "the Supreme Court. Judicial notice shall be taken of such seal."
        ),
    )
    ordinance_review = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "25 U.S.C. 2712. Review of existing ordinances and contracts. "
            "The Chairman shall review an ordinance or resolution within 90 "
            "days, approve a management contract, or provide written "
            "notification of necessary modifications, and the parties shall "
            "have not more than 120 days to come into compliance."
        ),
    )
    judicial_review = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "12 U.S.C. 4583. Judicial review. An enterprise may obtain review "
            "of a final order by filing in the United States Court of Appeals "
            "a written petition. The clerk shall transmit a copy to the "
            "Director, the Director shall file the record, and the court "
            "shall have jurisdiction to affirm, modify, terminate, or set "
            "aside the order."
        ),
    )
    repealed = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "16 U.S.C. 1414. Repealed. Pub. L. 105-42, section 6(c), "
            "Aug. 15, 1997. Section related to reviews, reports, and "
            "recommendations by Secretary of Commerce."
        ),
    )
    omitted = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "25 U.S.C. 1071. Omitted. Editorial Notes Codification. Section "
            "was omitted from the Code as being of special and not general "
            "application."
        ),
    )

    assert annual_cost_report["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert annual_cost_report["deontic.ir"] > distribution["deontic.ir"]
    assert retirement_election["deontic.ir"] > distribution["deontic.ir"]
    assert retirement_election["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert penalty_noncompliance["deontic.ir"] > distribution["deontic.ir"]
    assert penalty_noncompliance["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert seal_notice["deontic.ir"] > distribution["deontic.ir"]
    assert seal_notice["CEC.native"] > distribution["CEC.native"]
    assert ordinance_review["deontic.ir"] > distribution["deontic.ir"]
    assert ordinance_review["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert judicial_review["deontic.ir"] > distribution["deontic.ir"]
    assert judicial_review["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert repealed["CEC.native"] > repealed["deontic.ir"]
    assert repealed["knowledge_graphs.neo4j_compat"] > repealed["deontic.ir"]
    assert omitted["CEC.native"] > omitted["deontic.ir"]
    assert omitted["knowledge_graphs.neo4j_compat"] > omitted["deontic.ir"]
    for projected in (
        annual_cost_report,
        retirement_election,
        penalty_noncompliance,
        seal_notice,
        ordinance_review,
        judicial_review,
        repealed,
        omitted,
    ):
        assert abs(sum(projected.values()) - 1.0) < 1e-9


def test_official_usc_primary_projection_handles_packet_1136_bridge_contracts() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import (
        _project_official_usc_primary_contract_distribution,
    )

    distribution = {
        "CEC.native": 0.25,
        "TDFOL.prover": 0.25,
        "deontic.ir": 0.25,
        "knowledge_graphs.neo4j_compat": 0.25,
    }

    flexible_schedule = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "5 U.S.C. 6105. Flexible schedules. An agency may establish "
            "flexible or compressed work schedules. An employee may elect a "
            "work schedule, but an employee excluded under this section shall "
            "not be subject to the flexible schedule program."
        ),
    )
    census_confidentiality = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "13 U.S.C. 303. Reports and information. The Secretary of "
            "Commerce may require census reports and returns. Information "
            "furnished for statistical purposes shall be confidential and "
            "publication or disclosure may be subject to penalties."
        ),
    )
    bankruptcy_claims = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "11 U.S.C. 782. Treatment of customer claims. The trustee shall "
            "deliver securities and property of the estate, and a creditor "
            "may file a claim after notice and hearing for distribution."
        ),
    )
    historic_preservation = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "16 U.S.C. 470t. Historic preservation consultation. A Federal "
            "agency shall consult with the Advisory Council before approving "
            "an undertaking affecting a historic property listed on the "
            "National Register, and regulations may provide for review."
        ),
    )
    charter_governance = _project_official_usc_primary_contract_distribution(
        distribution,
        text=(
            "36 U.S.C. 20902. Powers. The corporation is a body corporate "
            "and may adopt bylaws, have perpetual succession, hold property, "
            "sue and be sued, and act through a board of directors."
        ),
    )

    assert flexible_schedule["deontic.ir"] > distribution["deontic.ir"]
    assert flexible_schedule["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert census_confidentiality["deontic.ir"] > distribution["deontic.ir"]
    assert census_confidentiality["knowledge_graphs.neo4j_compat"] >= 0.24
    assert bankruptcy_claims["deontic.ir"] > distribution["deontic.ir"]
    assert bankruptcy_claims["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert historic_preservation["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert historic_preservation["CEC.native"] > distribution["CEC.native"]
    assert charter_governance["CEC.native"] > distribution["CEC.native"]
    assert charter_governance["knowledge_graphs.neo4j_compat"] > distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    for projected in (
        flexible_schedule,
        census_confidentiality,
        bankruptcy_claims,
        historic_preservation,
        charter_governance,
    ):
        assert abs(sum(projected.values()) - 1.0) < 1e-9


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


def test_dense_contract_rebalance_projects_status_lifecycle_to_deontic_lane() -> None:
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
        "zkp.circuits": 0.139,
    }

    transferred = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "U.S.C. Title 2 - THE CONGRESS 2 U.S.C. United States Code, "
            "2024 Edition CHAPTER 4 - OFFICERS AND EMPLOYEES OF SENATE "
            "AND HOUSE OF REPRESENTATIVES Sec. 130g - Transferred From "
            "the U.S. Government Publishing Office."
        ),
    )
    omitted_authority = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "§3508. Omitted Editorial Notes Codification Section, which "
            "authorized the Secretary to make transfers of motor vehicles "
            "between bureaus and offices without transfer of funds."
        ),
    )

    assert transferred["deontic.ir"] >= 0.30
    assert omitted_authority["deontic.ir"] >= 0.30
    assert transferred["deontic.ir"] > distribution["deontic.ir"]
    assert omitted_authority["deontic.ir"] > distribution["deontic.ir"]
    assert abs(sum(transferred.values()) - 1.0) < 1e-9
    assert abs(sum(omitted_authority.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_keeps_omitted_only_status_archival() -> None:
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
        "zkp.circuits": 0.139,
    }

    rebalanced = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "Sections 8751 to 8755. Omitted Editorial Notes Codification. "
            "Sections 8751 to 8755 were omitted from the Code in view of "
            "termination of United States Synthetic Fuels Corporation."
        ),
    )

    assert rebalanced["deontic.ir"] <= 0.24
    assert rebalanced["CEC.native"] > rebalanced["deontic.ir"]
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9


def test_dense_contract_rebalance_projects_compliance_and_fiscal_norms() -> None:
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
        "zkp.circuits": 0.139,
    }

    compliance = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "15 U.S.C. 1679f. Administrative enforcement. Compliance with "
            "requirements imposed under this subchapter shall be enforced "
            "under the Federal Trade Commission Act."
        ),
    )
    fiscal = _rebalance_dense_contract_distribution(
        distribution,
        text=(
            "2 U.S.C. 5541. The Secretary of the Senate may make available "
            "amounts from the appropriations account for necessary expenses."
        ),
    )

    assert compliance["deontic.ir"] > distribution["deontic.ir"]
    assert compliance["TDFOL.prover"] > distribution["TDFOL.prover"]
    assert compliance["knowledge_graphs.neo4j_compat"] < distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert fiscal["deontic.ir"] >= 0.30
    assert fiscal["knowledge_graphs.neo4j_compat"] < distribution[
        "knowledge_graphs.neo4j_compat"
    ]
    assert abs(sum(compliance.values()) - 1.0) < 1e-9
    assert abs(sum(fiscal.values()) - 1.0) < 1e-9


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
    canonical_losses = report.canonical_loss_vector()
    assert canonical_losses["legal_ir_multiview_acceptance_loss"] == 0.0
    assert "source_decompiled_text_embedding_cosine_loss" in canonical_losses
    assert "source_decompiled_text_token_loss" in canonical_losses
    target_losses = report.training_target().losses
    assert target_losses["source_decompiled_text_embedding_cosine_loss"] == (
        canonical_losses["source_decompiled_text_embedding_cosine_loss"]
    )
    assert target_losses["source_decompiled_text_token_loss"] == (
        canonical_losses["source_decompiled_text_token_loss"]
    )
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


def test_multiview_bridge_soft_pass_uses_effective_proof_loss() -> None:
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import (
        BridgeEvaluationReport,
        GraphProjectionResult,
        LegalIRDocument,
        LogicIRView,
        ProofGateResult,
        RoundTripMetrics,
    )

    document = LegalIRDocument(
        document_id="multiview-effective-proof-loss",
        source_text="The agency shall publish notice.",
        normalized_text="The agency shall publish notice.",
        views={
            "tdfol_formula": LogicIRView(
                name="tdfol_formula",
                source_component="TDFOL.prover",
                payload={"records": [{"formula": "O(publish_notice(agency))"}]},
            )
        },
        frame_logic_triples=(
            {
                "subject": "agency",
                "predicate": "shall_publish",
                "object": "notice",
            },
        ),
    )
    bridge_report = BridgeEvaluationReport(
        adapter_name="fol_tdfol",
        target_component="TDFOL.prover",
        ir_document=document,
        round_trip=RoundTripMetrics(
            cosine_similarity=1.0,
            cross_entropy_loss=0.2,
            extra_losses={"legal_ir_view_cross_entropy_loss": 0.125},
        ),
        proof_gate=ProofGateResult(
            attempted_count=2,
            valid_count=1,
            failed_count=1,
        ),
        graph_projection=GraphProjectionResult(
            neo4j_compatible=True,
            node_count=2,
            relationship_count=1,
        ),
        status="ok",
        metadata={"proof_gate_soft_pass": True},
    )
    report = MultiViewLegalIRReport(
        bridge_names=("fol_tdfol",),
        document=document,
        reports={"fol_tdfol": bridge_report},
    )

    losses = report.loss_vector()
    canonical_losses = report.canonical_loss_vector()

    assert bridge_report.proof_gate.failure_ratio == 0.5
    assert bridge_report.effective_proof_failure_ratio == 0.0
    assert report.proof_failure_ratio == 0.0
    assert losses["fol_tdfol.raw_proof_failure_ratio"] == 0.5
    assert losses["fol_tdfol.proof_failure_ratio"] == 0.0
    assert canonical_losses["legal_ir_view_cross_entropy_loss"] == 0.125
    assert canonical_losses["legal_ir_multiview_total_loss"] == bridge_report.total_loss
    assert bridge_report.total_loss < 0.5


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
