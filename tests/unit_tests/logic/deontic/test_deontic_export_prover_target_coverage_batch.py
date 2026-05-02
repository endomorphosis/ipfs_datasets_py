"""Tests for batched prover-syntax target coverage export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    LOCAL_PROVER_SYNTAX_TARGETS,
    build_prover_syntax_target_coverage_records_from_irs,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_batch_prover_target_coverage_records_preserve_ir_order_and_source_ids():
    elements = [
        extract_normative_elements("The tenant must pay rent monthly.")[0],
        extract_normative_elements("The permittee may appeal the decision.")[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    records = build_prover_syntax_target_coverage_records_from_irs(norms)

    assert [record["source_id"] for record in records] == [
        norm.source_id for norm in norms
    ]
    assert [record["target_logic"] for record in records] == [
        "local_prover_syntax",
        "local_prover_syntax",
    ]
    assert [record["required_targets"] for record in records] == [
        list(LOCAL_PROVER_SYNTAX_TARGETS),
        list(LOCAL_PROVER_SYNTAX_TARGETS),
    ]

    for record in records:
        assert record["prover_syntax_summary_id"].startswith(
            "prover-syntax-coverage:"
        )
        assert record["record_count"] >= 1
        assert set(record["coverage_summary"]["required_targets"]) == set(
            LOCAL_PROVER_SYNTAX_TARGETS
        )
        assert record["formal_syntax_valid"] in {True, False}
        if not record["formal_syntax_valid"]:
            assert record["requires_validation"] is True
            assert record["coverage_blockers"]


def test_batch_prover_target_coverage_keeps_unresolved_numbered_exception_blocked():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(blocked)

    records = build_prover_syntax_target_coverage_records_from_irs([norm])

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert records[0]["source_id"] == norm.source_id
    assert records[0]["target_logic"] == "local_prover_syntax"
    assert records[0]["required_targets"] == list(LOCAL_PROVER_SYNTAX_TARGETS)
    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert "exception_requires_scope_review" in norm.blockers
