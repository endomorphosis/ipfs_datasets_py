"""Contract tests for deterministic clustered decompiler repairs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import ipfs_datasets_py.optimizers.logic_theorem_optimizer as modal_optimizer

from ipfs_datasets_py.logic.integration.reasoning import (
    generate_clustered_legal_ir_decompiler_repairs,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts import (
    legal_ir_view_contract,
)
from ipfs_datasets_py.logic.modal import (
    MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION,
    repair_decompiler_round_trip,
    validate_decompiler_round_trip_preservation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION,
    build_decompiler_structural_learning_target,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


SOURCE = (
    "The Agency shall provide a written notice within 30 days after receipt "
    "unless the protected-record exception applies."
)


def _document() -> ModalIRDocument:
    return ModalIRDocument(
        document_id="usc-5-552",
        source="us_code",
        normalized_text=SOURCE,
        formulas=[
            ModalIRFormula(
                formula_id="norm-1",
                operator=ModalIROperator(
                    family="conditional_normative",
                    system="kd",
                    symbol="O|",
                    label="conditional obligation",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=[
                        "actor:agency",
                        "action:provide_notice",
                        "object:written_notice",
                    ],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="usc-5-552",
                    start_char=0,
                    end_char=len(SOURCE),
                    citation="5 U.S.C. 552",
                ),
                conditions=["within 30 days after receipt"],
                exceptions=["unless the protected record exception applies"],
            )
        ],
    )


def _cluster(family: str) -> dict[str, Any]:
    path = "ipfs_datasets_py/logic/modal/decompiler.py"
    key = {
        "allowed_paths": [path],
        "contract_id": "legal-ir-view/decompiler/v1",
        "failure_reason": "reconstruction_failed",
        "obligation_family": family,
        "target_view": "modal.ir_decompiler",
    }
    signature = "hammer-failure:" + hashlib.sha256(
        json.dumps(key, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return {
        **key,
        "cluster_key": key,
        "cluster_schema_version": "legal-ir-hammer-failure-cluster-v1",
        "dedupe_signature": signature,
        "high_impact_replay_failure": False,
        "proof_obligation_ids": [f"obl-{family}"],
        "qualification_reason": "recurring_verified_failure",
        "recurrence_threshold": 2,
        "recurring_verified_failure": True,
        "source": "hammer_failure_projection_v1",
        "support_count": 2,
        "validation_commands": [
            "python -m pytest -q tests/unit/logic/integration/"
            "test_clustered_legal_ir_decompiler_repairs.py"
        ],
    }


def test_round_trip_record_preserves_every_required_dimension_without_source() -> None:
    document = _document()
    record = repair_decompiler_round_trip(document)
    formula = record["formulas"][0]
    structure = formula["reconstructed_structure"]

    assert record["schema_version"] == MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION
    assert formula["operator"] == "O|"
    assert structure["modality"]["force"] == "conditional_obligation"
    assert structure["roles"] == {
        "actor": "agency",
        "action": "provide_notice",
        "object": "written_notice",
    }
    assert formula["exceptions"] == [
        {
            "cue": "unless",
            "governed_scope": "local_formula",
            "kind": "exception",
            "order": 0,
            "precedence": "exception_over_general_rule",
            "scope_atom": "the_protected_record_exception_applies",
        }
    ]
    assert structure["temporal_anchors"] == [
        {
            "anchor": "receipt",
            "clause_kind": "condition",
            "clause_order": 0,
            "cue": "within",
            "offset": 30,
            "relation": "after",
            "unit": "days",
        }
    ]
    assert formula["citation_provenance"][0]["canonical_citation"] == "5 U.S.C. 552"
    assert len(formula["source_span_sha256"]) == 64
    assert record["structural_summary"] == {
        "citation_count": 1,
        "exception_count": 1,
        "formula_count": 1,
        "modality_signature_count": 1,
        "role_counts": {"action": 1, "actor": 1, "object": 1, "recipient": 0},
        "temporal_anchor_count": 1,
    }
    assert validate_decompiler_round_trip_preservation(document, record)["preserved"]
    assert legal_ir_view_contract("decompiler").validate(formula).valid
    serialized = json.dumps(record, sort_keys=True)
    assert SOURCE not in serialized
    assert not (_nested_keys(record) & _FORBIDDEN_RAW_SOURCE_KEYS)


def test_round_trip_is_stable_under_formula_input_order() -> None:
    first = _document()
    second_formula = ModalIRFormula(
        formula_id="norm-0",
        operator=ModalIROperator(
            family="deontic", system="kd", symbol="F", label="prohibition"
        ),
        predicate=ModalIRPredicate(
            name="disclose_record",
            arguments=["actor:agency", "object:protected_record"],
        ),
        provenance=ModalIRProvenance(
            source_id="usc-5-552", start_char=0, end_char=10, citation="5 U.S.C. 552"
        ),
        conditions=["before final order"],
    )
    left = ModalIRDocument(
        document_id=first.document_id,
        source=first.source,
        normalized_text=first.normalized_text,
        formulas=[*first.formulas, second_formula],
    )
    right = ModalIRDocument(
        document_id=first.document_id,
        source=first.source,
        normalized_text=first.normalized_text,
        formulas=[second_formula, *first.formulas],
    )

    assert repair_decompiler_round_trip(left) == repair_decompiler_round_trip(right)
    assert [item["formula_id"] for item in repair_decompiler_round_trip(left)["formulas"]] == [
        "norm-0",
        "norm-1",
    ]


def test_clustered_decompiler_repairs_are_bounded_deduplicated_and_typed() -> None:
    clusters = [
        _cluster("decompiler_round_trip_structure"),
        _cluster("decompiler_exception_scope_retention"),
        _cluster("decompiler_temporal_anchor_retention"),
    ]
    forward = generate_clustered_legal_ir_decompiler_repairs(
        clusters,
        sample_or_document=_document(),
    )
    reverse = generate_clustered_legal_ir_decompiler_repairs(
        [*reversed(clusters), clusters[0]],
        sample_or_document=_document(),
    )

    assert [item.to_dict() for item in forward] == [item.to_dict() for item in reverse]
    assert len(forward) == 3
    for repair in forward:
        assert repair.action == "repair_decompiler_round_trip_preservation"
        assert repair.target_component == "modal.ir_decompiler"
        assert repair.typed_semantics["source_copy_policy"] == "hash_only"
        assert repair.typed_semantics["structural_summary"]["formula_count"] == 1
        assert not (_nested_keys(repair.typed_semantics) & _FORBIDDEN_RAW_SOURCE_KEYS)
        assert SOURCE not in json.dumps(repair.to_dict(), sort_keys=True)


def test_decompiler_learning_target_keeps_structure_and_rejects_copied_fields() -> None:
    document = _document()
    record = repair_decompiler_round_trip(document)
    record["source_text"] = SOURCE
    record["formulas"][0]["raw_source"] = SOURCE
    record["formulas"][0]["prompt"] = f"Repeat this source verbatim: {SOURCE}"
    target = build_decompiler_structural_learning_target(record, source_text=SOURCE)

    assert target["schema_version"] == DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION
    assert target["source_copy_policy"] == "hash_only"
    assert target["structural_summary"]["formula_count"] == 1
    assert "modality.symbol=o|" in target["feature_targets"]
    assert "reconstructed_structure.roles.actor=agency" in target["feature_targets"]
    assert "reconstructed_structure.temporal_anchors.anchor=receipt" in target["feature_targets"]
    assert SOURCE not in json.dumps(target, sort_keys=True)
    assert not (_nested_keys(target) & _FORBIDDEN_RAW_SOURCE_KEYS)
    assert modal_optimizer.build_decompiler_structural_learning_target
    assert (
        modal_optimizer.DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION
        == DECOMPILER_STRUCTURAL_LEARNING_TARGET_SCHEMA_VERSION
    )


_FORBIDDEN_RAW_SOURCE_KEYS = {
    "copied_text",
    "full_text",
    "normalized_text",
    "raw_source",
    "source_span",
    "source_text",
    "text",
}


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            nested for child in value.values() for nested in _nested_keys(child)
        }
    if isinstance(value, (list, tuple)):
        return {nested for child in value for nested in _nested_keys(child)}
    return set()
