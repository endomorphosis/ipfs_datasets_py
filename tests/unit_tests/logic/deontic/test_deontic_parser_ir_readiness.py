"""Parser-boundary tests for deterministic IR/formula readiness projection."""

from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
    parser_elements_with_deterministic_ir_readiness,
)


def test_parser_ir_readiness_clears_formula_resolved_repair_noise_without_promoting_parser_gate():
    examples = [
        (
            "This section applies to food carts.",
            "local_scope_applicability",
        ),
        (
            "The applicant shall obtain a permit unless approval is denied.",
            "standard_substantive_exception",
        ),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            "pure_precedence_override",
        ),
    ]

    for text, resolution_type in examples:
        raw_element = extract_normative_elements(text)[0]
        projected = parser_elements_with_deterministic_ir_readiness([raw_element])[0]

        assert raw_element["promotable_to_theorem"] is False
        assert projected["promotable_to_theorem"] is False
        assert projected["llm_repair"]["required"] is False
        assert projected["llm_repair"]["allow_llm_repair"] is False
        assert projected["llm_repair"]["deterministically_resolved"] is True
        assert projected["llm_repair"]["deterministic_resolution"]["type"] == resolution_type
        assert projected["export_readiness"]["formula_proof_ready"] is True
        assert projected["export_readiness"]["formula_requires_validation"] is False
        assert projected["export_readiness"]["formula_repair_required"] is False
        assert projected["export_readiness"]["export_requires_validation"] is False
        assert projected["export_readiness"]["export_repair_required"] is False
        assert projected["export_readiness"]["deterministic_resolution"]["type"] == resolution_type


def test_parser_ir_readiness_keeps_unresolved_numbered_reference_exception_blocked():
    raw_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    projected = parser_elements_with_deterministic_ir_readiness([raw_element])[0]

    assert projected["promotable_to_theorem"] is False
    assert projected["llm_repair"]["required"] is True
    assert projected["llm_repair"].get("deterministically_resolved") is not True
    assert "cross_reference_requires_resolution" in projected["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in projected["llm_repair"]["reasons"]
    assert projected["export_readiness"]["formula_proof_ready"] is False
    assert projected["export_readiness"]["formula_requires_validation"] is True
    assert projected["export_readiness"]["formula_repair_required"] is True
    assert projected["export_readiness"]["export_requires_validation"] is True
    assert projected["export_readiness"]["export_repair_required"] is True
    assert projected["export_readiness"]["deterministic_resolution"] == {}


def test_parser_ir_readiness_resolves_numbered_reference_only_with_same_document_evidence():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "552"}

    projected = parser_elements_with_deterministic_ir_readiness(
        [reference_element, cited_element]
    )

    assert projected[0]["promotable_to_theorem"] is False
    assert projected[0]["llm_repair"]["required"] is False
    assert projected[0]["llm_repair"]["allow_llm_repair"] is False
    assert projected[0]["llm_repair"]["deterministically_resolved"] is True
    assert projected[0]["export_readiness"]["formula_proof_ready"] is True
    assert projected[0]["export_readiness"]["formula_requires_validation"] is False
    assert projected[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert projected[0]["export_readiness"]["deterministic_resolution"]["references"] == [
        "section 552"
    ]


def test_parser_ir_readiness_returns_copies_and_preserves_legacy_validation_list_shape():
    raw_element = extract_normative_elements("This section applies to food carts.")[0]
    raw_llm_repair = dict(raw_element["llm_repair"])
    raw_requires_validation = list(raw_element["export_readiness"]["requires_validation"])

    projected = parser_elements_with_deterministic_ir_readiness([raw_element])[0]

    assert projected is not raw_element
    assert raw_element["llm_repair"] == raw_llm_repair
    assert raw_element["export_readiness"]["requires_validation"] == raw_requires_validation
    assert isinstance(projected["export_readiness"]["requires_validation"], list)
    assert projected["export_readiness"]["requires_validation"] == raw_requires_validation
    assert projected["llm_repair"]["required"] is False
    assert raw_element["llm_repair"]["required"] is True
