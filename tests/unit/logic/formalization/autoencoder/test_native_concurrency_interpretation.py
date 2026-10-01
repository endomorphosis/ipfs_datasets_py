"""Interpret the unchanged producer/consumer declarations without inventing slots."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_concurrency_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder import native_concurrency_interpretation as bridge
from ipfs_datasets_py.logic.formalization.autoencoder import native_interpretation_expressions as typed
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramSymbol, ProgramIR
from tests.unit.logic.software_verification.test_concurrency_refinement import _producer_consumer
from tests.unit.logic.formalization.autoencoder.test_native_concurrency_lean import lake


def authored_interpretation(original_payload):
    """Reviewed fixture interpretation; refuses every other native declaration.

    This helper is test evidence, never a production prose-to-logic decoder.
    In particular buffer_space = 4-buffer, FIFO discipline, and mathematical
    integer contracts are explicit assumptions supplied here.
    """
    assert original_payload == _producer_consumer().to_dict()
    source = SourceRef("source:authored-concurrency-interpretation", "urn:test:explicit-concurrency-interpretation",
        "explicit-concurrency-interpretation", "fixture:v1", content_sha256=typed.digest(original_payload))
    mapped = {"source_ref_ids": (source.ref_id,)}
    symbol = ProgramSymbol("buffer", "buffer", "integer", "global", **mapped)
    expressions = []
    def term(key, kind, ty, *operands, operator="", value=None, symbols=()):
        expressions.append(ProgramExpression(key, kind, ty, operand_ids=operands, evaluation_order=operands,
            symbol_ids=tuple(symbols), operator=operator, attributes={"value": value} if kind == "literal" else {}, **mapped))
        return key
    term("buffer", "symbol", "integer", symbols=("buffer",))
    term("old_buffer", "old", "integer", "buffer")
    for key, value in (("zero", 0), ("one", 1), ("capacity", 4)):
        term(key, "literal", "integer", value=value)
    term("true", "literal", "boolean", value=True)
    term("space", "binary", "integer", "capacity", "buffer", operator="sub")
    term("can_produce", "binary", "boolean", "space", "zero", operator="gt")
    term("can_consume", "binary", "boolean", "buffer", "zero", operator="gt")
    term("produce", "binary", "integer", "buffer", "one", operator="add")
    term("consume", "binary", "integer", "buffer", "one", operator="sub")
    term("nonnegative", "binary", "boolean", "buffer", "zero", operator="ge")
    term("increase", "binary", "integer", "buffer", "old_buffer", operator="sub")
    term("decrease", "binary", "integer", "old_buffer", "buffer", operator="sub")
    for key in ("increase", "decrease"):
        term(key + "_nonnegative", "binary", "boolean", key, "zero", operator="ge")
        term(key + "_at_most_one", "binary", "boolean", key, "one", operator="le")
        term(key + "_bounded", "binary", "boolean", key + "_nonnegative", key + "_at_most_one", operator="and")
        term(key + "_one", "binary", "boolean", key, "one", operator="eq")
    carrier = typed.make_carrier([symbol], expressions, sources=[source])
    steps = []
    for step in original_payload["steps"]:
        kind = {"step:prod-write": "produce", "step:cons-read": "consume", "step:env-noise": None}[step["step_id"]]
        steps.append({"step_id": step["step_id"], "guard_expression_id": "can_" + kind if kind else "true",
            "updates": {"var:buffer": kind} if kind else {}, "evidence_id": "fixture:reviewed-step:" + step["step_id"]})
    bindings = []
    for path, statement in bridge.statement_bindings(original_payload).items():
        meaning = "descriptive" if path.startswith("/metadata/") else "typed_expression" if path.startswith(("/steps/", "/rely_guarantee/", "/linearizability_points/")) else "native_structure"
        bindings.append({"path": path, "statement_sha256": typed.digest(statement), "meaning": meaning,
            "evidence_id": "fixture:reviewed-statement:" + path})
    return {"schema": bridge.SCHEMA, "native_document_sha256": typed.digest(original_payload),
        "expression_program": carrier, "variable_symbols": {"var:buffer": "buffer"}, "surface_aliases": {"buffer_space": "space"},
        "steps": steps, "contracts": [{"contract_id": row["contract_id"], "rely_expression_id": "nonnegative",
            "guarantee_expression_id": ("increase" if row["component_id"] == "comp:producer" else "decrease") + "_bounded",
            "evidence_id": "fixture:reviewed-contract:" + row["contract_id"]} for row in original_payload["rely_guarantee"]],
        "linearizations": [{"point_id": row["point_id"], "relation_expression_id": ("increase" if row["point_id"] == "lin:prod" else "decrease") + "_one",
            "evidence_id": "fixture:reviewed-abstract-operation:" + row["point_id"]} for row in original_payload["linearizability_points"]],
        "channel_semantics": [{"channel_id": row["channel_id"], "discipline": "fifo", "evidence_id": "fixture:explicit-FIFO-choice"} for row in original_payload["channels"]],
        "statement_bindings": bindings, "evidence_id": "fixture:explicit-authored-concurrency-interpretation"}


def fixture():
    original = _producer_consumer().to_dict()
    return original, authored_interpretation(original)


def test_original_identity_is_unchanged_and_interpretation_is_explicit():
    original, evidence = fixture()
    before, before_evidence = deepcopy(original), deepcopy(evidence)
    with pytest.raises(UnsupportedNativeLean):
        emit.emit_concurrency(original)
    source, details = emit.emit_concurrency(original, interpretation=evidence)
    assert original == before and evidence == before_evidence
    assert details["payload_sha256"] == typed.digest(original)
    assert not any(details[key] for key in ("original_native_document_modified", "source_semantics_verified",
        "obligations_discharged", "capability_floor_eligible", "proof_authority", "channel_store_coupling_verified",
        "session_execution_linked", "global_linearizability_verified", "interpretation_authenticity_verified"))
    result = lake(source)
    assert result["status"] == "passed", result


def test_arithmetic_guards_updates_frames_and_owner_distinction_in_real_lean():
    original, evidence = fixture()
    source, _ = emit.emit_concurrency(original, interpretation=evidence)
    # Sorted native IDs: consume, environment, produce; consumer then producer.
    result = lake(source, """
example : stepRelation Step.s2 ⟨0⟩ ⟨1⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : stepRelation Step.s0 ⟨1⟩ ⟨0⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : stepRelation Step.s1 ⟨3⟩ ⟨3⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ stepRelation Step.s0 ⟨0⟩ ⟨-1⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ stepRelation Step.s2 ⟨4⟩ ⟨5⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ stepRelation Step.s1 ⟨1⟩ ⟨2⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ componentStep Component.c0 Step.s1 ⟨0⟩ ⟨0⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : readFrame Step.s1 = ["var:buffer"] := rfl
example : writeFrame Step.s1 = [] := rfl
""")
    assert result["status"] == "passed", result
    failed = lake(source, "example : stepRelation Step.s2 ⟨4⟩ ⟨5⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]")
    assert failed["status"] == "failed"


def test_rely_guarantee_and_abstract_operation_relations_are_not_opaque_propositions():
    original, evidence = fixture()
    source, _ = emit.emit_concurrency(original, interpretation=evidence)
    result = lake(source, """
example : relyRelation_0 ⟨3⟩ ⟨0⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ relyRelation_0 ⟨0⟩ ⟨-1⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : guaranteeRelation_0 ⟨2⟩ ⟨1⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ guaranteeRelation_0 ⟨2⟩ ⟨0⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : guaranteeRelation_1 ⟨2⟩ ⟨3⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ guaranteeRelation_1 ⟨2⟩ ⟨4⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : linearizationRelation_0 ⟨2⟩ ⟨1⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : ¬ linearizationRelation_0 ⟨2⟩ ⟨2⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : linearizationRelation_1 ⟨2⟩ ⟨3⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : interferenceAccess_0 Step.s1 = true := rfl
example : interferenceAccess_0 Step.s0 = false := rfl
example : interferenceAccess_1 Step.s0 = true := rfl
""")
    assert result["status"] == "passed", result
    failed = lake(source, "example : guaranteeRelation_1 ⟨2⟩ ⟨4⟩ := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]")
    assert failed["status"] == "failed"


def test_native_capacity_FIFO_order_and_session_duality_survive_lowering():
    original, evidence = fixture()
    source, _ = emit.emit_concurrency(original, interpretation=evidence)
    result = lake(source, """
example : channelSend_0 (Value := fun _ => Nat) Component.c1 7 [1,2,3] [1,2,3,7] := by
  simp [channelSend_0]
example : ¬ channelSend_0 (Value := fun _ => Nat) Component.c1 7 [1,2,3,4] [1,2,3,4,7] := by
  simp [channelSend_0]
example : channelReceive_0 (Value := fun _ => Nat) Component.c0 1 [1,2] [2] := by
  simp [channelReceive_0]
example : ¬ channelReceive_0 (Value := fun _ => Nat) Component.c0 2 [1,2] [1] := by
  simp [channelReceive_0]
example : ¬ channelReceive_0 (Value := fun _ => Nat) Component.c0 1 [1,2,3,4,5] [2,3,4,5] := by
  simp [channelReceive_0]
example : sessionDuality_0 = true := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : sessionDuality_1 = true := by simp [stepRelation, stepGuard, stepUpdate, componentStep, stepActor, relyRelation_0, guaranteeRelation_0, guaranteeRelation_1, linearizationRelation_0, linearizationRelation_1, sessionDuality_0, sessionDuality_1, sessionDual, sessionActions_0, sessionActions_1, dualPolarity]
example : sessionStep_0 "sess:req" "send" "Item" (some "sess:ack") := by
  simp [sessionStep_0, sessionActions_0]
example : ¬ sessionStep_0 "sess:req" "receive" "Item" (some "sess:ack") := by
  simp [sessionStep_0, sessionActions_0]
example : ¬ sessionStep_0 "sess:req" "send" "Ack" (some "sess:ack") := by
  simp [sessionStep_0, sessionActions_0]
example : ¬ sessionStep_0 "sess:req" "send" "Item" (some "sess:end") := by
  simp [sessionStep_0, sessionActions_0]
""")
    assert result["status"] == "passed", result


def test_dynamic_fairness_rejects_an_enabled_starved_producer():
    original, evidence = fixture()
    source, _ = emit.emit_concurrency(original, interpretation=evidence)
    result = lake(source, """
def stalled : Execution := ⟨fun _ => ⟨0⟩, fun _ => Step.s1⟩
example : validExecution stalled := by
  intro t
  constructor <;> rfl
example : ¬ fairness_1 stalled := by
  intro fair
  have enabled : continuouslyEventually (fun t => selectedEnabled [Step.s2] (stalled.state t)) := by
    refine ⟨0, ?_⟩
    intro t _
    exact ⟨Step.s2, by simp, rfl⟩
  obtain ⟨t, _, wrong⟩ := fair enabled 0
  simp [stalled] at wrong
example : ¬ schedule_0 [Step.s0,Step.s0,Step.s0,Step.s0,Step.s0,Step.s0,Step.s0,Step.s0,Step.s0] := by
  simp [schedule_0]
""")
    assert result["status"] == "passed", result


@pytest.mark.parametrize("mutation,reason", [
    (lambda e: e.update(native_document_sha256="0" * 64), "digest"),
    (lambda e: e.update(extra_semantics=True), "closed"),
    (lambda e: e["statement_bindings"].pop(), "complete_exact"),
    (lambda e: e["statement_bindings"][0].update(statement_sha256="0" * 64), "digest"),
    (lambda e: e["statement_bindings"][0].update(meaning="descriptive"), "kind"),
    (lambda e: e["surface_aliases"].clear(), "explicit_alias"),
    (lambda e: e["surface_aliases"].update(buffer_space="buffer"), "surface"),
    (lambda e: e["steps"][0].update(guard_expression_id="true"), "surface"),
    (lambda e: e["steps"][0]["updates"].update({"var:buffer": "produce"}), "surface"),
    (lambda e: e["steps"][0]["updates"].clear(), "write_frame"),
    (lambda e: e["contracts"][0].update(rely_expression_id="buffer"), "type"),
    (lambda e: e["channel_semantics"][0].update(discipline="unordered"), "fifo"),
    (lambda e: e["variable_symbols"].update({"var:buffer": "undeclared"}), "bijection"),
    (lambda e: e["steps"][0].update(evidence_id=""), "evidence"),
])
def test_stale_missing_or_contradictory_interpretations_fail_closed(mutation, reason):
    original, evidence = fixture(); mutation(evidence)
    with pytest.raises((UnsupportedNativeLean, ValueError), match=reason):
        emit.emit_concurrency(original, interpretation=evidence)


def test_modified_native_document_requires_new_identity_and_statement_bindings():
    original, evidence = fixture()
    original["steps"][0]["guard_statement"] = "buffer >= 0"
    original.pop("document_id")
    changed = bridge.native.ConcurrencyIR.from_dict(original).to_dict()
    with pytest.raises(UnsupportedNativeLean, match="digest"):
        emit.emit_concurrency(changed, interpretation=evidence)
    evidence["native_document_sha256"] = typed.digest(changed)
    with pytest.raises(UnsupportedNativeLean, match="statement_binding_digest"):
        emit.emit_concurrency(changed, interpretation=evidence)


def test_fixture_evidence_helper_is_not_a_general_source_decoder():
    changed = _producer_consumer().to_dict(); changed["metadata"]["example"] = "other"
    with pytest.raises(AssertionError):
        authored_interpretation(changed)
