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
    assert report.graph_projection.neo4j_compatible is True
    assert report.graph_projection.node_count > 0
    assert report.graph_projection.relationship_count > 0
    assert report.proof_gate.attempted_count >= 1
    assert report.proof_gate.compiles is True
    assert report.round_trip.cross_entropy_loss >= 0.0
    assert "cosine_similarity" in report.round_trip.to_dict()
    assert report.total_loss >= 0.0
    assert report.to_dict()["ir_document"]["has_frame_logic"] is True


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


def test_multiview_training_target_distribution_prunes_non_contract_tail_lanes() -> None:
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
    assert "modal.frame_logic" not in target_distribution
    assert "external_provers.router" not in target_distribution
    assert set(target_distribution) == {
        "CEC.native",
        "TDFOL.prover",
        "deontic.ir",
        "knowledge_graphs.neo4j_compat",
        "zkp.circuits",
    }
    assert abs(sum(target_distribution.values()) - 1.0) < 1e-9


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
