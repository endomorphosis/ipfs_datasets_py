"""Actual trained rich child dispatch through the shared source-document API."""
from copy import deepcopy
from pathlib import Path

import pytest

from .test_rich_intent_decoder import published_child, actual_candidate
from ipfs_datasets_py.logic.formalization.autoencoder.source_document import prepare_source_document
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction


def prepare(text, checkpoint, **options):
    return prepare_source_document(text, source_path="benchmark-instruction.md", source_format="markdown",
        intent_checkpoint=checkpoint, **options)


def test_actual_child_selects_rich_dispatch_and_retains_full_source(actual_candidate, published_child):
    instruction, learned = actual_candidate
    report = prepare(instruction, published_child, project_logic_families=True)
    assert report["intent"] is None and report["intent_family_projection"] is None
    rich = report["rich_intent"]
    assert rich["schema"] == "intent-rich-document/v1"
    assert "".join(row["text"] for row in rich["units"]) == instruction
    assert report["counts"]["intent_candidates"] == 1
    assert report["counts"]["intent_encoder_executions"] >= 1
    assert report["counts"]["intent_decoder_executions"] >= 1
    assert report["candidates"][0]["rich_ir"] == learned["rich_ir"]
    assert report["candidates"][0]["rich_ir"]["ast"] == parse_instruction(instruction)
    assert report["counts"]["lake_attempts"] == report["counts"]["lake_passes"] == 0
    assert report["llm_calls"] == report["download_calls"] == report["training_steps"] == 0
    assert not report["proof_authority"] and not report["whole_document_formalized"]


def test_rich_checkpoint_explicitly_enables_own_projection_mode_without_legacy_flag(actual_candidate, published_child):
    instruction, _ = actual_candidate
    report = prepare(instruction, published_child)
    assert report["project_logic_families"] is False
    assert report["rich_projection_enabled_by_checkpoint"] is True
    assert report["rich_intent"]["projection_mode"]
    assert report["counts"]["intent_logic_families"] >= 1


def test_atomic_rich_candidate_preserves_existing_native_family_views(actual_candidate, published_child):
    instruction, learned = actual_candidate
    report = prepare(instruction, published_child, project_logic_families=True)
    unit = next(row for row in report["rich_intent"]["units"] if row["accepted"])
    assert unit["inference"]["logic"] == learned["logic"]
    assert unit["atomic_family_projection"]["native_targets"]["projections"]
    families = {row["family_id"] for row in report["rich_intent"]["family_inventory"] if row["status"] == "available_views"}
    assert families >= {"first_order", "deontic", "program", "frame_logic", "datalog", "horn_chc", "higher_order", "dcec", "tdfol"}
    assert report["counts"]["intent_logic_families"] == len(families)


def test_rich_slot_context_cannot_imply_specialization_of_unselected_lean(actual_candidate, published_child):
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_document import CONTEXT_SCHEMA
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_decoder import sha, wire
    instruction, _ = actual_candidate
    report = prepare(instruction, published_child)
    unit = next(row for row in report["rich_intent"]["units"] if row["accepted"])
    context = {"schema": CONTEXT_SCHEMA, "source_sha256": sha(instruction.encode()),
        "checkpoint_sha256": sha(wire(published_child)), "units": [{"unit_id": unit["unit_id"],
            "clause_sha256": sha(instruction.encode()), "slot_context": {}}]}
    with pytest.raises(ValueError, match="requires selected higher_order"):
        prepare(instruction, published_child, project_logic_families=True,
            requested_intent_families=["dcec"], intent_family_context=context)


def test_requested_family_counts_only_selected_real_views(actual_candidate, published_child):
    instruction, _ = actual_candidate
    report = prepare(instruction, published_child, project_logic_families=True,
        requested_intent_families=["tdfol"])
    rich = report["rich_intent"]
    assert report["counts"]["intent_candidates"] == report["counts"]["intent_logic_families"] == 1
    accepted = [row for row in rich["units"] if row["accepted"]]
    assert len(accepted) == 1
    assert {row["family_id"] for row in accepted[0]["selected_projections"]} == {"tdfol"}
    assert all(row["status"] == "not_requested" for row in rich["family_inventory"] if row["family_id"] != "tdfol")


def test_actual_source_dispatch_counts_actual_lake_not_projection_presence(actual_candidate, published_child):
    paths = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not paths:
        pytest.skip("installed native Lean required")
    instruction, _ = actual_candidate
    report = prepare(instruction, published_child, project_logic_families=True,
        requested_intent_families=["higher_order"], lake_executable=str(paths[-1]))
    assert report["counts"]["intent_candidates"] == 1
    assert report["counts"]["lake_attempts"] == report["counts"]["lake_passes"] == 1
    assert len(report["lake_checks"]) == 1
    receipt = report["lake_checks"][0]["receipt"]
    assert receipt["backend_executed"] and receipt["syntax_verified"]
    assert receipt["validated_scope"] == "parameterized_rich_formula_syntax_only"
    assert not receipt["claim_proved"] and not receipt["actual_guard_truth_checked"]


def test_python_fence_never_reaches_rich_intent_as_prose(actual_candidate, published_child):
    instruction, _ = actual_candidate
    source = instruction + "\n\n```python\ndef sample(value):\n    return value\n```\n"
    report = prepare(source, published_child, project_logic_families=True)
    assert report["counts"]["intent_candidates"] == 1
    assert len(report["security_regions"]) == 1
    assert report["security_regions"][0]["frontier"] == "security_checkpoint_not_selected"
    assert report["counts"]["security_decoder_calls"] == 0
    assert "".join(row["text"] for row in report["rich_intent"]["units"]) == source
    assert all("def sample" not in row["text"] for row in report["rich_intent"]["units"] if row["accepted"])


def test_partial_source_selection_refuses_before_actual_model_execution(published_child):
    source = "agent must inspect cache."
    report = prepare(source, published_child, start_char=11, end_char=18)
    assert not report["candidates"]
    assert report["counts"]["intent_encoder_executions"] == report["counts"]["intent_decoder_executions"] == 0
    assert "".join(row["text"] for row in report["rich_intent"]["units"]) == source[11:18]


def test_changed_real_manifest_digest_fails_open_without_native_fallback(published_child):
    changed = deepcopy(published_child)
    changed["sha256"] = "0" * 64
    report = prepare("agent must inspect cache.", changed, project_logic_families=True)
    assert not report["candidates"] and report["intent"] is None
    assert report["counts"]["intent_encoder_executions"] == report["counts"]["intent_decoder_executions"] == 0
    unit = next(row for row in report["rich_intent"]["units"] if row["inference"] is not None)
    assert unit["inference"]["status"] == "fail_open_checkpoint_or_inference_error"


def test_modal_heading_keeps_raw_task_without_unscoped_rich_candidate(published_child):
    source = "## Prohibited\n\nagent must inspect cache.\n"
    report = prepare(source, published_child)
    assert not report["candidates"]
    assert report["counts"]["intent_encoder_executions"] == report["counts"]["intent_decoder_executions"] == 0
    assert "".join(row["text"] for row in report["rich_intent"]["units"]) == source


def test_optional_projector_failure_does_not_leave_an_accepted_unlisted_candidate(actual_candidate, published_child, monkeypatch):
    # Boundary failure injection only: the actual trained atom encoder and
    # inverse still run; only the optional deterministic projector is mocked.
    from ipfs_datasets_py.logic.intent_ir.formalize import extended_projections
    instruction, _ = actual_candidate

    def fail_optional_projection(*args, **kwargs):
        raise ValueError("authored_optional_projection_failure")

    monkeypatch.setattr(extended_projections, "project_intent_families", fail_optional_projection)
    report = prepare(instruction, published_child, project_logic_families=True)
    assert not report["candidates"] and report["counts"]["intent_candidates"] == 0
    unit = next(row for row in report["rich_intent"]["units"] if row["inference"] is not None)
    assert unit["inference"]["rich_ir"] is not None
    assert unit["inference"]["counts"]["encoder_executions"] >= 1
    assert unit["accepted"] is False
    assert unit["reason"] == "authored_optional_projection_failure"
