"""Coverage tests for canonical-contract LegalIR proof obligations."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning import (
    LegalIRProofObligation,
    generate_legal_ir_contract_coverage_obligations,
    generate_legal_ir_proof_obligations,
    legal_ir_view_contracts,
)


def _document() -> dict[str, object]:
    return {
        "document_id": "contract-coverage-doc",
        "normalized_text": (
            "The agency shall not disclose a record unless an exception applies "
            "before the deadline."
        ),
        "formulas": [
            {
                "formula_id": "formula-1",
                "operator": {
                    "family": "deontic",
                    "system": "KD",
                    "symbol": "shall_not",
                },
                "predicate": {
                    "name": "disclose",
                    "arguments": ["agency", "record"],
                    "role": "prohibition",
                },
                "provenance": {
                    "source_id": "prov:contract-coverage-doc",
                    "start_char": 0,
                    "end_char": 91,
                },
                "conditions": ["before the deadline"],
                "exceptions": ["an exception applies"],
            }
        ],
        "frame_logic": {
            "triples": [
                {"subject": "agency", "predicate": "acts_on", "object": "record"}
            ]
        },
    }


def _contract_obligations() -> list[LegalIRProofObligation]:
    return generate_legal_ir_contract_coverage_obligations(_document())


def test_every_contract_emits_every_declared_local_and_cross_view_family() -> None:
    obligations = _contract_obligations()

    for contract in legal_ir_view_contracts():
        emitted = [
            obligation
            for obligation in obligations
            if obligation.metadata["contract_id"] == contract.contract_id
        ]
        emitted_families = {
            obligation.metadata["obligation_family"] for obligation in emitted
        }

        assert set(contract.obligation_families) <= emitted_families
        assert set(contract.cross_view_obligation_families) <= emitted_families
        assert any(
            obligation.metadata["coverage_scope"] in {
                "required_field",
                "local_semantics",
            }
            for obligation in emitted
        )
        assert any(
            obligation.metadata["coverage_scope"] == "cross_view_consistency"
            for obligation in emitted
        )
        assert all(
            obligation.legal_ir_view == contract.target_component
            for obligation in emitted
        )


def test_every_required_contract_field_has_an_individual_obligation() -> None:
    obligations = _contract_obligations()

    for contract in legal_ir_view_contracts():
        covered_fields = {
            obligation.metadata["required_field"]
            for obligation in obligations
            if obligation.metadata["contract_id"] == contract.contract_id
            and obligation.metadata["coverage_scope"] == "required_field"
        }
        assert covered_fields == set(contract.required_field_names)

        for obligation in obligations:
            if (
                obligation.metadata["contract_id"] == contract.contract_id
                and obligation.metadata["coverage_scope"] == "required_field"
            ):
                requirement = next(
                    field
                    for field in contract.required_fields
                    if field.path == obligation.metadata["required_field"]
                )
                assert obligation.metadata["required_field_types"] == list(
                    requirement.value_types
                )
                assert obligation.metadata["allow_empty"] is requirement.allow_empty


def test_specialized_contract_invariants_cover_acceptance_boundaries() -> None:
    obligations = _contract_obligations()
    by_family = {
        obligation.metadata["obligation_family"]: obligation
        for obligation in obligations
        if obligation.metadata["coverage_scope"] == "local_semantics"
    }

    expected_fragments = {
        "deontic_polarity": "prohibition_has_negative_polarity",
        "exception_scope_precedence": "scoped_exception_precedes_governed_norm",
        "temporal_anchor": "explicit_typed_anchor",
        "knowledge_graph_endpoint_typing": "endpoints_reference_typed_nodes",
        "cec_lifecycle_transition": "typed_event_and_fluent",
        "external_prover_route_preservation": "route_preserves_input_formula",
        "decompiler_round_trip_structure": "preserves_typed_structure",
    }
    assert expected_fragments.keys() <= by_family.keys()
    for family, fragment in expected_fragments.items():
        assert fragment in by_family[family].statement


def test_cross_view_obligations_name_all_peer_contracts_and_preservation_rules() -> None:
    contracts = legal_ir_view_contracts()
    obligations = _contract_obligations()

    for contract in contracts:
        cross_view = [
            obligation
            for obligation in obligations
            if obligation.metadata["contract_id"] == contract.contract_id
            and obligation.metadata["coverage_scope"] == "cross_view_consistency"
        ]
        expected_peer_ids = {
            peer.contract_id for peer in contracts if peer is not contract
        }
        assert cross_view
        for obligation in cross_view:
            assert set(obligation.metadata["related_contract_ids"]) == expected_peer_ids
            assert obligation.metadata["preservation_rules"] == list(
                contract.modality_semantics.preservation_rules
            )


def test_contract_obligation_ids_and_serialization_are_stable_unique_and_source_free() -> None:
    first = _contract_obligations()
    second = _contract_obligations()

    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert len({item.obligation_id for item in first}) == len(first)
    assert all(item.obligation_id.startswith("lir-obligation-") for item in first)
    serialized = json.dumps([item.to_dict() for item in first], sort_keys=True)
    assert "The agency shall not disclose" not in serialized
    assert "normalized_text" not in serialized
    assert "source_text" not in serialized


def test_primary_generator_includes_complete_contract_expansion() -> None:
    direct = _contract_obligations()
    all_obligations = generate_legal_ir_proof_obligations(_document())
    all_ids = {obligation.obligation_id for obligation in all_obligations}

    assert {obligation.obligation_id for obligation in direct} <= all_ids
