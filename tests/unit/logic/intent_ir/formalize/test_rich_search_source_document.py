"""Actual training-03 child recovery through source documents and native Lake.

The fixed source is a development coverage control, not held-out accuracy.
No learned predictions, numerical calls, or Lake execution are substituted.
"""
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
from ipfs_datasets_py.logic.intent_ir.formalize.rich_document import prepare_rich_intent_document
from ipfs_datasets_py.logic.intent_ir.formalize.rich_search_policy import policy_identity

INSTRUCTION = "Check availability across date range"
EXPECTED_AST = {"kind": "atom", "actor": "unspecified", "action": "check",
                "object": "availability across date range", "modality": "intended"}


@pytest.fixture(scope="module")
def published_search_child():
    default = Path(__file__).resolve().parents[7] / "artifacts/intent-rich-decoder-20261002/training-03/descriptor.json"
    selected = Path(os.environ.get("INTENT_RICH_SEARCH_TEST_CHECKPOINT", str(default)))
    if not selected.exists():
        pytest.skip("training-03 search child is not installed; set INTENT_RICH_SEARCH_TEST_CHECKPOINT")
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_decoder import load_rich_intent_checkpoint
    value = json.loads(selected.read_text())
    load_rich_intent_checkpoint(value)
    return value


@pytest.fixture(scope="module")
def actual_search_document(published_search_child):
    paths = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    return prepare_source_document(INSTRUCTION, source_path="benchmark-instruction.md", source_format="markdown",
        intent_checkpoint=published_search_child, project_logic_families=True,
        requested_intent_families=["higher_order", "dcec"],
        lake_executable=str(paths[-1]) if paths else None)


def test_real_source_dispatch_recovers_roundtrip_with_explicit_syntax_search(actual_search_document):
    report = actual_search_document
    rich = report["rich_intent"]
    assert rich["grammar_search_recovery"] is True
    assert rich["counts"]["grammar_search_attempts"] == rich["counts"]["grammar_searched_accepted_clauses"] == 1
    assert rich["counts"]["direct_accepted_clauses"] == rich["counts"]["composed_accepted_clauses"] == 0
    assert report["counts"]["intent_candidates"] == 1
    assert "".join(unit["text"] for unit in rich["units"]) == INSTRUCTION
    unit = next(unit for unit in rich["units"] if unit["accepted"])
    inference = unit["inference"]
    assert unit["decoding_method"] == "grammar_constrained_neural_roundtrip"
    assert inference["rich_ir"]["ast"] == EXPECTED_AST
    assert inference["direct_report"]["rich_ir"] is None
    assert inference["learned"]["encoder"]["status"] == inference["learned"]["decoder"]["status"] == "generated"
    assert inference["policy"] == policy_identity()
    assert inference["counts"]["encoder_executions"] >= 1
    assert inference["counts"]["decoder_executions"] >= 1
    assert inference["phase_counts"]["grammar_search"]["decoder_executions"] >= 1
    assert inference["whole_AST_generated_by_neural_encoder"] and inference["whole_inverse_generated_by_neural_decoder"]
    assert not inference["syntax_constraints_are_semantic_evidence"]
    assert not inference["constraint_receives_source_or_expected_AST"]
    assert not report["proof_authority"] and not report["whole_document_formalized"]
    assert report["llm_calls"] == report["download_calls"] == report["training_steps"] == 0


def test_recovered_actual_formula_passes_one_native_lake_build(actual_search_document):
    report = actual_search_document
    if not report["lake_checks"]:
        pytest.skip("installed native Lean required")
    assert report["counts"]["lake_attempts"] == report["counts"]["lake_passes"] == 1
    assert len(report["lake_checks"]) == 1
    receipt = report["lake_checks"][0]["receipt"]
    assert receipt["backend_executed"] and receipt["syntax_verified"]
    assert receipt["validated_scope"] == "parameterized_rich_formula_syntax_only"
    assert not receipt["claim_proved"] and not receipt["actual_guard_truth_checked"]


def test_disabling_grammar_recovery_restores_actual_direct_refusal(published_search_child):
    report = prepare_rich_intent_document(INSTRUCTION, published_search_child,
        requested_families=["higher_order", "dcec"], grammar_search_recovery=False)
    assert report["grammar_search_recovery"] is False
    assert not report["candidates"]
    assert report["counts"]["grammar_search_attempts"] == report["counts"]["grammar_searched_accepted_clauses"] == 0
    assert report["counts"]["encoder_executions"] >= 1
    assert report["counts"]["decoder_executions"] >= 1
    assert "".join(unit["text"] for unit in report["units"]) == INSTRUCTION
    unit = next(unit for unit in report["units"] if unit["inference"] is not None)
    assert unit["inference"]["rich_ir"] is None
    assert unit["decoding_method"] == "direct_neural_roundtrip"
