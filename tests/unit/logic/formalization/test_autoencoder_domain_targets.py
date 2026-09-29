"""Concrete domain target preparation, isolation, and absent-evidence checks."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import (
    DomainTargetEnvelope, build_target_envelope, prepare_intent_targets, prepare_security_targets,
)
from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_FAILURE_VIEW_ID, IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.schema import IntentIRValidationError, IntentModality
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence, CodeLogicProjectionError
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.software_verification.program import (
    BasicBlock, ControlFlowGraph, ProgramCommand, ProgramExpression, ProgramFunction, ProgramIR,
)


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
BODY = b"def one():\n    return 1\n"


@pytest.fixture
def intent():
    return decode_intent_ir(json.loads((FIXTURES / "intent_ir/admissibility/intents/benign_skill.json").read_text()))


@pytest.fixture
def security():
    cid = canonical_identity({"fixture": "authored"}, domain="authored", schema_version="v1").cid
    body_cid = canonical_identity({"body": BODY.decode()}, domain="cvefixes-security-ir/code-body",
                                  schema_version="cvefixes-code-body/v1").cid
    unit = CodeUnit(source_cids=(cid,), parent_cids=(cid,), config_cid=cid,
        unit_kind="symbol", language="Python", path="one.py", polarity="fixed",
        payload={"body_sha256": hashlib.sha256(BODY).hexdigest(), "body_cid": body_cid, "cwe_id": "CWE-22"})
    source = SourceRef(ref_id=unit.cid, source_uri="code-unit:" + unit.cid, source_id=unit.path,
        source_revision="authored-fixture-v1", content_sha256=unit.payload["body_sha256"], content_cid=body_cid)
    mapped = {"source_ref_ids": (source.ref_id,)}
    expression = ProgramExpression("expr:one", "literal", "integer", attributes={"value": 1}, **mapped)
    command = ProgramCommand("cmd:return", "return", expression_ids=("expr:one",), **mapped)
    graph = ControlFlowGraph(graph_id="cfg:one", entry_block_id="block:one",
        blocks=(BasicBlock("block:one", ("cmd:return",), **mapped),), edges=(), normal_exit_block_ids=("block:one",))
    function = ProgramFunction(function_id="function:one", name="one", cfg=graph, return_type="integer", **mapped)
    program = ProgramIR(sources=(source,), spans=(), symbols=(), expressions=(expression,),
                        commands=(command,), functions=(function,))
    return unit, CodeLogicEvidence(program, source)


def test_intent_targets_preserve_native_expressions_and_split_families(intent):
    envelope = prepare_intent_targets(intent)
    wire = envelope.to_dict()
    native = IntentFormalizationCompiler().compile_document(intent)
    observed = {formula["formula_id"]: formula for row in wire["projections"] for formula in row["native_formulas"]}
    assert observed == {formula.formula_id: formula.to_dict() for formula in native.formulas}
    rows = {row["projection_id"]: row for row in wire["projections"]}
    assert rows["intent-route/intentions/v1"]["logic_family"] == "intention_agency"
    assert rows["intent-route/norms/v1"]["logic_family"] == "deontic"
    assert rows["intent-route/safety/v1"]["logic_family"] == "temporal"
    assert rows["intent-route/safety/v1"]["properties"] == ["safety"]
    assert rows["intent-route/verification-condition-role/v1"]["logic_family"] is None
    assert rows["intent-route/verification-condition-role/v1"]["view_role"] == "verification_condition"
    assert envelope.ready_for_training
    assert wire["qualification_gaps"]
    assert all(wire[key] is False for key in ("qualified", "admitted", "formalized"))
    assert envelope == prepare_intent_targets(intent)


def test_intent_native_schema_and_missing_projection_fail_closed(intent):
    with pytest.raises(IntentIRValidationError):
        prepare_intent_targets(intent.to_dict())
    with pytest.raises(IntentIRValidationError, match="statements must not be empty"):
        prepare_intent_targets(replace(intent, statements=()))
    with pytest.raises(ValueError, match="registered view"):
        prepare_intent_targets(intent, required_view_ids=("invented:logic",))
    absent = prepare_intent_targets(intent, required_view_ids=(INTENT_FAILURE_VIEW_ID,)).to_dict()
    assert not absent["ready_for_training"]
    assert {"view_id": INTENT_FAILURE_VIEW_ID, "reason": "missing_requested_projection"} in absent["unsupported"]


def test_intent_norm_changes_are_reflected_without_cross_family_target_reuse(intent):
    modified = replace(intent, statements=tuple(replace(row, modality=IntentModality.RECOMMENDED)
                        if row.statement_id == "statement:precondition" else row for row in intent.statements))
    old, new = prepare_intent_targets(intent), prepare_intent_targets(modified)
    assert old.source_digest != new.source_digest and old.digest != new.digest
    assert new.ready_for_training
    norms = next(row for row in new.to_dict()["projections"] if row["projection_id"] == "intent-route/norms/v1")
    assert any(expression["operator"] == "recommended" for expression in norms["expression"])


def test_security_reuses_exact_native_projection_and_replay(security):
    unit, evidence = security
    envelope = prepare_security_targets(code_unit=unit, source_bytes=BODY,
                                       typed_inputs=(evidence,), requested_kinds=("program",))
    wire = envelope.to_dict()
    assert wire["domain_id"] == "security_ir" and wire["ready_for_training"]
    row = wire["projections"][0]
    assert row["projection_id"] == "program.program_ir/v1"
    assert row["logic_family"] == "program" and row["profile"] == "program_ir"
    assert row["expression"] == json.loads(json.dumps(evidence.document.to_dict()))
    assert row["native_target"]["bridge"]["status"] == "ok"
    assert not row["native_target"]["source_semantics_verified"]
    assert wire["qualification_gaps"] and not wire["admitted"]
    assert envelope == prepare_security_targets(code_unit=unit, source_bytes=BODY,
                                                typed_inputs=(evidence,), requested_kinds=("program",))


def test_security_labels_and_missing_source_cannot_create_targets(security):
    unit, evidence = security
    missing = prepare_security_targets(code_unit=unit, source_bytes=BODY).to_dict()
    assert missing["projections"] == [] and not missing["ready_for_training"]
    assert {row["reason"] for row in missing["unsupported"]} == {"missing_typed_evidence"}
    missing_bytes = prepare_security_targets(code_unit=unit, source_bytes=None, typed_inputs=(evidence,)).to_dict()
    assert missing_bytes["projections"] == [] and not missing_bytes["ready_for_training"]
    assert {row["reason"] for row in missing_bytes["unsupported"]} == {"missing_exact_source_bytes"}
    with pytest.raises(CodeLogicProjectionError, match="CodeLogicEvidence"):
        prepare_security_targets(code_unit=unit, source_bytes=BODY, typed_inputs=({"cwe": "CWE-22"},))
    with pytest.raises(CodeLogicProjectionError):
        prepare_security_targets(code_unit=unit, source_bytes=BODY, requested_kinds=("unknown",))
    with pytest.raises(CodeLogicProjectionError, match="SHA differs"):
        prepare_security_targets(code_unit=unit, source_bytes=BODY + b"# changed\n", typed_inputs=(evidence,))


def test_immutable_envelope_roundtrip_rejects_promoted_authority_and_readiness(intent):
    envelope = prepare_intent_targets(intent)
    wire = envelope.to_dict()
    assert DomainTargetEnvelope.from_dict(wire) == envelope
    wire["projections"][0]["expression"].clear()
    assert envelope.to_dict()["projections"][0]["expression"]
    with pytest.raises(FrozenInstanceError):
        envelope.canonical_bytes = b"{}"
    for key in ("qualified", "admitted", "formalized"):
        mutated = envelope.to_dict()
        mutated[key] = True
        with pytest.raises(ValueError, match="qualification or admission"):
            DomainTargetEnvelope.from_dict(mutated)
    mutated = envelope.to_dict()
    mutated["ready_for_training"] = False
    with pytest.raises(ValueError, match="readiness"):
        DomainTargetEnvelope.from_dict(mutated)


def test_qualification_gap_does_not_prevent_feature_training_but_target_gap_does(intent):
    original = prepare_intent_targets(intent).to_dict()
    base = {key: original[key] for key in ("domain_id", "source_digest", "projections")}
    check = {"validator_id": "native", "status": "passed", "details": {}}
    qualification = {"validator_id": "external", "stage": "qualification", "status": "not_run", "details": {}}
    ready = build_target_envelope(**base, validation=[check, qualification], qualification_gaps=["solver absent"])
    assert ready.ready_for_training and not ready.to_dict()["qualified"]
    failed = build_target_envelope(**base, validation=[{**check, "status": "failed"}])
    assert not failed.ready_for_training
    gap = build_target_envelope(**base, validation=[check], unsupported=["missing_requested_projection"])
    assert not gap.ready_for_training
    empty = build_target_envelope(**{**base, "projections": []}, validation=[check])
    assert not empty.ready_for_training
    with pytest.raises(ValueError, match="required target validator"):
        build_target_envelope(**base, validation=[qualification])


def test_envelope_rejects_operation_as_family_and_empty_expressions(intent):
    wire = prepare_intent_targets(intent).to_dict()
    wire["projections"][0]["logic_family"] = "verification_condition"
    with pytest.raises(ValueError, match="canonical logic family"):
        DomainTargetEnvelope.from_dict(wire)
    wire = prepare_intent_targets(intent).to_dict()
    wire["projections"][0]["expression"] = {}
    with pytest.raises(ValueError, match="nonempty native"):
        DomainTargetEnvelope.from_dict(wire)
