"""Evaluation accounting must not turn broken targets or absent predictions into success."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.autoformal import legal_coordination_evaluation as evaluation
from ipfs_datasets_py.logic.autoformal import legal_coordination as bridge
from ipfs_datasets_py.logic.deontic.coordination import build_coordination_groups
from ipfs_datasets_py.logic.deontic.coordination_decoder import (
    COORDINATION_DECODE_REQUEST_SCHEMA, CoordinationDecodeRequest,
)


def request():
    return CoordinationDecodeRequest.from_dict({
        "schema": COORDINATION_DECODE_REQUEST_SCHEMA,
        "modal_scope": "disjunction_of_norms", "connective": "inclusive_or",
        "binding_profile": "universal_actor_predicate",
        "members": [
            {"actor": "registrar", "modality": "O", "action": "publish notice"},
            {"actor": "registrar", "modality": "O", "action": "retain records"},
        ],
    })


@pytest.mark.parametrize("targets,outputs", [(None, []), ([], None), ({}, []), ([], {})])
def test_evaluation_rejects_unbounded_or_wrong_sequence_types(targets, outputs):
    with pytest.raises(ValueError, match="bounded target/output sequences"):
        evaluation.evaluate_coordination_outputs(targets, outputs)


@pytest.mark.parametrize("side", ["targets", "outputs"])
def test_item_bound_is_enforced_before_rendering(monkeypatch, side):
    def unexpected_render(value):
        pytest.fail("over-limit evaluation must not render")
    monkeypatch.setattr(evaluation, "decode_coordination_request", unexpected_render)
    values = {"targets": [], "outputs": []}
    values[side] = [request()] * (evaluation.MAX_EVALUATION_ITEMS + 1)
    with pytest.raises(ValueError, match="item bound"):
        evaluation.evaluate_coordination_outputs(**values)


def test_wire_reference_is_rejected_instead_of_coerced_into_a_teacher():
    with pytest.raises(ValueError, match="typed reference"):
        evaluation.evaluate_coordination_outputs([request().to_dict()], [request()])


def test_invalid_reference_modal_binding_aborts_instead_of_scoring_outputs():
    target = request()
    changed = replace(target.members[1], actor="clerk")
    invalid_reference = replace(target, modal_scope="modal_over_actions",
                                members=(target.members[0], changed))
    with pytest.raises(ValueError, match="one normalized actor"):
        evaluation.evaluate_coordination_outputs([invalid_reference], [target])


def test_postconstruction_corrupt_reference_is_revalidated():
    target = request()
    object.__setattr__(target.members[0], "modality", "invalid")
    with pytest.raises(ValueError, match="modality"):
        evaluation.evaluate_coordination_outputs([target], [])


def test_render_failure_is_counted_for_candidate_but_not_repaired():
    target = request()
    candidate = target.to_dict()
    candidate["modal_scope"] = "modal_over_actions"
    candidate["members"][1]["actor"] = "clerk"
    result = evaluation.evaluate_coordination_outputs([target], [candidate])
    assert result["invalid_output_count"] == result["failed_count"] == 1
    assert result["passed_count"] == 0
    row = result["cases"][0]
    assert row["blockers"] == ["invalid_output_schema"]
    assert "candidate_formula" not in row
    assert not any(row[key] for key in result["measure_counts"])


def test_report_does_not_claim_model_training_or_source_equivalence():
    target = request()
    result = evaluation.evaluate_coordination_outputs([target], [target.to_dict()])
    assert result["passed_count"] == 1
    assert result["target_ir_comparison_only"] is True
    for name in ("source_semantics_verified", "semantic_equivalence_checked",
                 "model_accuracy_claimed", "proof_ready"):
        assert result[name] is False
    assert result["model_calls"] == result["training_calls"] == 0


def test_input_predictions_and_targets_are_not_mutated():
    target = request()
    outputs = [target.to_dict(), {"malformed": "prediction"}]
    before_outputs = deepcopy(outputs)
    before_target = target.to_dict()
    result = evaluation.evaluate_coordination_outputs((target,), outputs)
    assert result["case_count"] == 2
    assert result["passed_count"] == 1
    assert result["unexpected_output_count"] == result["failed_count"] == 1
    assert outputs == before_outputs
    assert target.to_dict() == before_target


@pytest.mark.parametrize("action", [
    "inspect tin can", "publish will", "file section headings",
    "is hereby prohibited from disclosure",
])
def test_source_groups_outside_decoder_lexical_profile_keep_evidence_without_compiler_crash(action):
    group, = build_coordination_groups("The registrar shall " + action + " or shall retain records.")
    assert group.structure_supported
    declaration = bridge.interpretation_skeleton(group)
    declaration.update(modal_scope="disjunction_of_norms", connective="inclusive_or",
                       binding_profile="universal_actor_predicate")
    record = bridge.compile_coordination_group(group, declaration)
    assert record["blockers"] == ["group_decoder_profile_unsupported", "source_interpretation_unreviewed"]
    assert record["structure_compiled"] is False
    assert record["formula"] == record["lean_body"] == ""
    assert record["native_ast"] is record["native_payload"] is None
    assert record["mapping"] == {"actor_symbols": [], "action_symbols": []}
    assert bridge.reconstruct_compiled_group(record) == group.scope_raw_text
    with pytest.raises(ValueError, match="structurally compiled"):
        bridge.coordination_decode_request_from_compiled(record)
