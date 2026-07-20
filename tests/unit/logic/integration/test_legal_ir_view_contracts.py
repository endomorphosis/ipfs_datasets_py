"""Tests for canonical, deterministic multi-view LegalIR contracts."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION,
    LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION,
    LEGAL_IR_VIEW_CONTRACTS,
    LegalIRView,
    legal_ir_codex_todo_projection,
    legal_ir_view_contract,
    legal_ir_view_contract_manifest,
    legal_ir_view_contracts,
    validate_legal_ir_view,
)


EXPECTED_IDS = {
    "deontic": "legal-ir-view/deontic/v1",
    "frame_logic": "legal-ir-view/frame-logic/v1",
    "tdfol": "legal-ir-view/tdfol/v1",
    "cec": "legal-ir-view/cec/v1",
    "knowledge_graphs": "legal-ir-view/knowledge-graphs/v1",
    "external_provers": "legal-ir-view/external-provers/v1",
    "decompiler": "legal-ir-view/decompiler/v1",
}


def _valid_payloads() -> dict[str, dict[str, object]]:
    return {
        "deontic": {
            "formula_id": "formula-1",
            "operator": "F",
            "norm_type": "prohibition",
            "polarity": "negative",
            "actor": "agency",
            "action": "disclose",
            "object": "record",
            "conditions": [],
            "exceptions": ["exception-1"],
            "provenance_ids": ["prov:sha256:111"],
        },
        "frame_logic": {
            "formula_id": "formula-1",
            "frame_id": "frame-1",
            "subject": "agency",
            "predicate": "must_not_disclose",
            "object": "record",
            "role": "prohibition",
            "provenance_ids": ["prov:sha256:111"],
        },
        "tdfol": {
            "formula_id": "formula-1",
            "expression": {"operator": "before", "arguments": ["notice", "disclose"]},
            "quantifiers": [],
            "temporal_anchors": ["event:notice"],
            "provenance_ids": ["prov:sha256:111"],
        },
        "cec": {
            "formula_id": "formula-1",
            "events": [{"id": "event:notice", "type": "notice"}],
            "fluents": [{"id": "fluent:eligible", "type": "eligibility"}],
            "lifecycle_transitions": [
                {
                    "event_id": "event:notice",
                    "fluent_id": "fluent:eligible",
                    "effect": "initiates",
                }
            ],
            "provenance_ids": ["prov:sha256:111"],
        },
        "knowledge_graphs": {
            "graph_id": "graph-1",
            "nodes": [
                {"id": "agency", "type": "Actor"},
                {"id": "record", "labels": ["LegalObject"]},
            ],
            "relationships": [
                {"source": "agency", "target": "record", "type": "MUST_NOT_DISCLOSE"}
            ],
            "provenance_ids": ["prov:sha256:111"],
        },
        "external_provers": {
            "obligation_id": "obligation-1",
            "input_formula_id": "formula-1",
            "backend_route": ["z3", "cvc5"],
            "backend_status": {"z3": "proved", "cvc5": "not_run"},
            "reconstruction_status": "verified",
            "provenance_ids": ["prov:sha256:111"],
        },
        "decompiler": {
            "formula_id": "formula-1",
            "source_contract_id": EXPECTED_IDS["deontic"],
            "reconstructed_structure": {"norm_type": "prohibition", "role": "object"},
            "operator": "F",
            "predicate": {"name": "disclose", "arity": 2},
            "arguments": ["agency", "record"],
            "conditions": [],
            "exceptions": ["exception-1"],
            "provenance_ids": ["prov:sha256:111"],
        },
    }


def test_registry_has_exact_canonical_views_and_stable_contract_ids() -> None:
    contracts = legal_ir_view_contracts()

    assert tuple(contract.view.value for contract in contracts) == tuple(EXPECTED_IDS)
    assert {
        contract.view.value: contract.contract_id for contract in contracts
    } == EXPECTED_IDS
    assert len(LEGAL_IR_VIEW_CONTRACTS) == 7
    assert all(
        contract.schema_version == LEGAL_IR_VIEW_CONTRACT_SCHEMA_VERSION
        for contract in contracts
    )


def test_registry_resolves_names_components_aliases_enums_and_ids() -> None:
    assert legal_ir_view_contract(LegalIRView.TDFOL) is legal_ir_view_contract(
        "TDFOL.prover"
    )
    assert legal_ir_view_contract("tdfol_prover") is legal_ir_view_contract("tdfol")
    assert legal_ir_view_contract("modal.frame_logic").view is LegalIRView.FRAME_LOGIC
    assert legal_ir_view_contract("modal.decompiler").view is LegalIRView.DECOMPILER
    assert legal_ir_view_contract(EXPECTED_IDS["cec"]).target_component == "CEC.native"
    with pytest.raises(KeyError):
        legal_ir_view_contract("unknown_view")


def test_every_contract_is_complete_for_all_downstream_consumers() -> None:
    for contract in legal_ir_view_contracts():
        assert "provenance_ids" in contract.required_field_names
        assert contract.provenance_requirements.source_text_policy == "identifiers_only"
        assert contract.modality_semantics.family
        assert contract.modality_semantics.preservation_rules
        assert contract.validation_hooks
        assert contract.obligation_families
        assert contract.cross_view_obligation_families
        assert contract.metric_families
        assert contract.allowed_repair_lanes
        assert set(contract.autoencoder_feature_families) >= {
            "contract_id",
            "obligation_family",
            "metric_family",
            "repair_lane",
        }
        for lane in contract.repair_lanes:
            assert lane.target_component == contract.target_component
            assert lane.allowed_paths
            assert all(
                path.startswith("ipfs_datasets_py/") for path in lane.allowed_paths
            )
            assert lane.validation_commands


def test_all_representative_payloads_pass_typed_validation() -> None:
    for view, payload in _valid_payloads().items():
        result = validate_legal_ir_view(view, payload)
        assert result.valid, result.to_dict()
        assert result.contract_id == EXPECTED_IDS[view]
        assert not result.missing_required_fields


def test_validation_reports_missing_fields_and_never_accepts_source_text() -> None:
    result = validate_legal_ir_view(
        "deontic",
        {
            "formula_id": "formula-1",
            "source_text": "The agency shall not disclose the record.",
            "provenance_ids": [],
        },
    )

    assert not result.valid
    assert {"operator", "norm_type", "polarity", "actor", "action", "object"} <= set(
        result.missing_required_fields
    )
    codes = {issue.code for issue in result.issues}
    assert "source_text_forbidden" in codes
    assert "empty_required_field" in codes
    assert "missing_provenance_id" in codes
    serialized = result.to_dict()
    assert "The agency shall not disclose" not in json.dumps(serialized)


def test_view_specific_hooks_enforce_semantic_invariants() -> None:
    payloads = _valid_payloads()

    deontic = dict(payloads["deontic"], polarity="positive")
    assert "prohibition_polarity_mismatch" in {
        issue.code for issue in validate_legal_ir_view("deontic", deontic).issues
    }

    tdfol = dict(payloads["tdfol"], temporal_anchors=[])
    assert "missing_temporal_anchor" in {
        issue.code for issue in validate_legal_ir_view("tdfol", tdfol).issues
    }

    cec = dict(payloads["cec"], lifecycle_transitions=[])
    assert "missing_lifecycle_transition" in {
        issue.code for issue in validate_legal_ir_view("cec", cec).issues
    }

    graph = dict(payloads["knowledge_graphs"])
    graph["relationships"] = [
        {"source": "agency", "target": "missing", "type": "ACTS_ON"}
    ]
    assert "unknown_graph_endpoint" in {
        issue.code for issue in validate_legal_ir_view("knowledge_graphs", graph).issues
    }


def test_manifest_and_consumer_projections_are_deterministic_and_source_free() -> None:
    first = legal_ir_view_contract_manifest()
    second = legal_ir_view_contract_manifest()

    assert first == second
    assert first["registry_version"] == LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION
    assert first["contract_count"] == 7
    assert first["contract_ids"] == list(EXPECTED_IDS.values())
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )

    for contract in legal_ir_view_contracts():
        consumer = contract.consumer_contract()
        assert consumer["contract_id"] == contract.contract_id
        assert set(consumer["obligation_families"]) == set(
            contract.all_obligation_families
        )
        assert consumer["metric_families"] == list(contract.metric_families)
        features = contract.autoencoder_features()
        assert f"contract_id:{contract.contract_id}" in features
        assert not any("source_text" in feature for feature in features)


def test_codex_projection_is_lane_bounded_and_contains_stable_contract_id() -> None:
    contract = legal_ir_view_contract("knowledge_graphs")
    lane = contract.repair_lanes[0]

    projection = legal_ir_codex_todo_projection("neo4j_compat", lane.lane_id)

    assert projection["contract_id"] == EXPECTED_IDS["knowledge_graphs"]
    assert projection["target_component"] == "knowledge_graphs.neo4j_compat"
    assert projection["allowed_repair_lanes"] == [lane.lane_id]
    assert projection["allowed_paths"] == list(lane.allowed_paths)
    assert projection["validation_commands"] == list(lane.validation_commands)
    assert "source_text" not in json.dumps(projection)
    with pytest.raises(KeyError):
        legal_ir_codex_todo_projection("knowledge_graphs", "unbounded-lane")


def test_logic_ir_view_envelope_payload_is_accepted_without_envelope_source_text() -> (
    None
):
    payload = _valid_payloads()["frame_logic"]
    envelope = {
        "name": "frame_logic",
        "format": "frame_logic",
        "payload": payload,
        "source_component": "modal.frame_logic",
    }

    assert validate_legal_ir_view("frame_logic", envelope).valid
