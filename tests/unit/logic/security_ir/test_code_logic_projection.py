"""Exact source joins, real native projections, and missing-evidence boundaries."""
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
from ipfs_datasets_py.logic.security_ir.code_logic_projection import (
    CodeLogicEvidence, CodeLogicProjectionError, SUPPORTED_KINDS,
    describe_code_logic_projection_profile, project_code_logic, validate_code_logic_projection,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
from ipfs_datasets_py.logic.software_verification.contracts import ProgramContract, ContractClause
from ipfs_datasets_py.logic.software_verification.program import (
    ProgramIR, ProgramExpression, ProgramCommand, ProgramFunction,
    ControlFlowGraph, BasicBlock,
)
from ipfs_datasets_py.logic.software_verification.state import (
    StateSchema, StateVariable, FiniteDomainBound, StatePredicate,
)
from ipfs_datasets_py.logic.software_verification.transitions import (
    StateTransitionIR, Action, ActionFrame, TransitionRelation,
)
from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
from ipfs_datasets_py.logic.software_verification.heap import HeapModel, HeapLocation, HeapValue
from ipfs_datasets_py.logic.software_verification.separation import SeparationLogicIR, emp_formula
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    HyperpropertyIR, InformationFlowPolicy, SelfCompositionBound,
)

BODY = b"def one():\n    return 1\n"


@pytest.fixture
def binding():
    cid = canonical_identity({"fixture": "authored"}, domain="authored", schema_version="v1").cid
    body_cid = canonical_identity({"body": BODY.decode()}, domain="cvefixes-security-ir/code-body",
                                  schema_version="cvefixes-code-body/v1").cid
    unit = CodeUnit(source_cids=(cid,), parent_cids=(cid,), config_cid=cid,
        unit_kind="symbol", language="Python", path="one.py", polarity="fixed",
        payload={"body_sha256": hashlib.sha256(BODY).hexdigest(), "body_cid": body_cid,
                 "cwe_id": "CWE-22"})
    source = SourceRef(ref_id=unit.cid, source_uri="code-unit:" + unit.cid,
        source_id=unit.path, source_revision="authored-fixture-v1",
        content_sha256=unit.payload["body_sha256"], content_cid=body_cid)
    return unit, source


def program(source):
    mapped = {"source_ref_ids": (source.ref_id,)}
    body = ProgramExpression("expr:one", "literal", "integer", attributes={"value": 1}, **mapped)
    true = ProgramExpression("expr:true", "literal", "boolean", attributes={"value": True}, **mapped)
    command = ProgramCommand("cmd:return", "return", expression_ids=("expr:one",), **mapped)
    graph = ControlFlowGraph(graph_id="cfg:one", entry_block_id="block:one",
        blocks=(BasicBlock("block:one", ("cmd:return",), **mapped),), edges=(),
        normal_exit_block_ids=("block:one",))
    function = ProgramFunction(function_id="function:one", name="one", cfg=graph,
                               return_type="integer", **mapped)
    return ProgramIR(sources=(source,), spans=(), symbols=(), expressions=(body, true),
                     commands=(command,), functions=(function,))


def contract(source):
    mapped = {"source_ref_ids": (source.ref_id,)}
    return ProgramContract("contract:one", "function:one",
        preconditions=(ContractClause("pre:true", "precondition", "expr:true", "true", **mapped),),
        postconditions=(ContractClause("post:true", "postcondition", "expr:true", "true", **mapped),), **mapped)


def transition(source):
    mapped = {"source_ref_ids": (source.ref_id,)}
    schema = StateSchema(variables=(StateVariable("var:x", "x", "integer", "finite",
        domain_bound=FiniteDomainBound("bound:x", lower=0, upper=1)),))
    initial = StatePredicate("pred:init", "initial", "x = 0", expression={"x": 0},
        subject_variable_ids=("var:x",), **mapped)
    nxt = StatePredicate("pred:next", "next", "x' = 1", expression={"x": 1},
        subject_variable_ids=("var:x",), **mapped)
    invariant = StatePredicate("pred:safe", "invariant", "x <= 1",
        subject_variable_ids=("var:x",), **mapped)
    action = Action("action:set", "Set", ActionFrame(reads=("var:x",), writes=("var:x",)),
                    next_predicate_id="pred:next")
    relation = TransitionRelation("rel:next", "action", "Set or stutter",
                                   action_ids=("action:set",), allows_stutter=True)
    return StateTransitionIR(schema=schema, predicates=(initial, nxt, invariant),
                              actions=(action,), transitions=(relation,))


def evidence(source):
    temporal = TemporalFormula("always", operands=(TemporalFormula("atom", proposition="safe",
        source_ref_ids=(source.ref_id,)),), source_ref_ids=(source.ref_id,))
    heap = HeapModel(locations=(HeapLocation("loc:cell", "cell", "address", "integer",
        source_ref_ids=(source.ref_id,)),), values=(HeapValue("val:one", "integer", "integer",
        literal="1", source_ref_ids=(source.ref_id,)),), model_id="heap:cell")
    separation = SeparationLogicIR(sources=(source,), heap=heap,
        formulas=(emp_formula("formula:emp", source_ref_ids=(source.ref_id,)),), root_formula_id="formula:emp")
    policy = InformationFlowPolicy(policy_id="policy:flow", low_input_fields=("public",),
        high_input_fields=("secret",), observation_fields=("result",))
    hyper = HyperpropertyIR.noninterference_document(policy=policy,
        bound=SelfCompositionBound("bound:flow", max_traces=2, max_pairs=1, max_steps=4))
    return [CodeLogicEvidence(doc, source) for doc in
        (program(source), contract(source), transition(source), temporal, heap, separation, hyper)]


def test_profile_reuses_native_families_and_explicitly_limits_capability():
    profile = describe_code_logic_projection_profile()
    routes = {row["kind"]: row for row in profile["projections"]}
    assert profile["supported_kinds"] == list(SUPPORTED_KINDS)
    assert (routes["contract"]["family"], routes["contract"]["profile"]) == ("program", "dynamic_hoare")
    assert routes["hyperproperty"]["family"] == "hyperproperty"
    assert profile["tla_encoding"]["encoding"] == "tla+"
    assert not profile["tla_encoding"]["model_checker_executed"]
    assert not profile["proof_authority"] and not profile["source_semantics_verified"]
    assert all(not row["available_without_typed_evidence"] for row in routes.values())
    assert json.loads(json.dumps(profile)) == profile


def test_native_all_family_projection_and_tla_compilation_replay(binding):
    unit, source = binding
    projected = project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=evidence(source))
    assert projected["status"] == "projected" and projected["unsupported"] == []
    targets = {row["kind"]: row for row in projected["targets"]}
    assert set(targets) == set(SUPPORTED_KINDS)
    assert all(row["bridge"]["status"] == "ok" for row in targets.values())
    assert targets["contract"]["program_binding_validated"] is True
    tla = targets["transition"]["encoding"]
    assert "MODULE CodeTransition" in tla["artifact"]["model_text"]
    assert tla["artifact"]["safety_properties"]
    assert tla["artifact"]["bounded"] and not tla["model_checker_executed"]
    assert projected["backend_calls"] == projected["provider_calls"] == 0
    assert validate_code_logic_projection(json.loads(json.dumps(projected)), code_unit=unit, source_bytes=BODY) == projected
    reordered = project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=list(reversed(evidence(source))))
    assert reordered == projected


def test_labels_and_bodies_do_not_create_formal_targets(binding):
    unit, _ = binding
    result = project_code_logic(code_unit=unit, source_bytes=BODY)
    assert result["status"] == "unsupported" and result["targets"] == []
    assert len(result["unsupported"]) == len(SUPPORTED_KINDS)
    assert {row["reason"] for row in result["unsupported"]} == {"missing_typed_evidence"}
    with pytest.raises(CodeLogicProjectionError, match="CodeLogicEvidence"):
        project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=[{"cwe": "CWE-22"}])


@pytest.mark.parametrize("missing", ["bytes", "body_sha256", "body_cid"])
def test_missing_public_body_material_is_quarantined(binding, missing):
    unit, _ = binding
    raw = BODY
    if missing == "bytes":
        raw = None
    else:
        payload = dict(unit.payload)
        del payload[missing]
        unit = replace(unit, payload=payload, record_id="")
    result = project_code_logic(code_unit=unit, source_bytes=raw)
    assert result["status"] == "quarantined" and result["targets"] == []
    assert validate_code_logic_projection(result, code_unit=unit, source_bytes=raw) == result


def test_exact_body_and_explicit_model_source_mismatch_rejected(binding):
    unit, source = binding
    with pytest.raises(CodeLogicProjectionError, match="SHA differs"):
        project_code_logic(code_unit=unit, source_bytes=BODY + b"# changed\n")
    wrong = replace(source, content_cid=unit.cid)
    with pytest.raises(CodeLogicProjectionError, match="SourceRef differs"):
        project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=[CodeLogicEvidence(contract(source), wrong)])
    other = replace(source, ref_id="source:other")
    with pytest.raises(CodeLogicProjectionError, match="different code unit"):
        project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=[CodeLogicEvidence(contract(other), source)])
    corrupt = replace(unit, payload={**unit.payload, "body_cid": unit.cid}, record_id="")
    with pytest.raises(CodeLogicProjectionError, match="CID differs"):
        project_code_logic(code_unit=corrupt, source_bytes=BODY)
    prepared = project_code_logic(code_unit=unit, source_bytes=BODY)
    with pytest.raises(CodeLogicProjectionError, match="SHA differs"):
        validate_code_logic_projection(prepared, code_unit=unit, source_bytes=BODY + b"# changed\n")


def test_contract_requires_closed_native_program(binding):
    unit, source = binding
    result = project_code_logic(code_unit=unit, source_bytes=BODY,
        typed_inputs=[CodeLogicEvidence(contract(source), source)], requested_kinds=["contract"])
    assert result["targets"] == []
    assert result["unsupported"] == [{"kind": "contract", "reason": "missing_typed_program_for_contract"}]
    dangling = replace(contract(source), function_id="function:missing")
    with pytest.raises(ValueError, match="unknown function"):
        project_code_logic(code_unit=unit, source_bytes=BODY,
            typed_inputs=[CodeLogicEvidence(program(source), source), CodeLogicEvidence(dangling, source)])


@pytest.mark.parametrize("alter", ["authority", "bridge", "encoding", "source", "input"])
def test_projection_tampering_rejected_even_with_unchanged_inputs(binding, alter):
    unit, source = binding
    result = project_code_logic(code_unit=unit, source_bytes=BODY,
        typed_inputs=[CodeLogicEvidence(transition(source), source)], requested_kinds=["transition"])
    if alter == "authority":
        result["proof_authority"] = True
    elif alter == "bridge":
        result["targets"][0]["family_id"] = "deontic"
    elif alter == "encoding":
        result["targets"][0]["encoding"]["artifact"]["model_text"] += "FALSE\n"
    elif alter == "source":
        result["source"]["body_sha256"] = "0" * 64
    else:
        result["typed_inputs"][0]["source"]["extra"] = True
    with pytest.raises(CodeLogicProjectionError, match="identity or content"):
        validate_code_logic_projection(result, code_unit=unit, source_bytes=BODY)


def test_temporal_profile_mismatch_is_explicit(binding):
    unit, source = binding
    formula = TemporalFormula("atom", logic="ltlf", proposition="safe", source_ref_ids=(unit.cid,))
    result = project_code_logic(code_unit=unit, source_bytes=BODY,
        typed_inputs=[CodeLogicEvidence(formula, source)], requested_kinds=["temporal"])
    assert result["targets"] == []
    assert result["unsupported"] == [{"kind": "temporal", "reason": "non_ltl_temporal_profile"}]


def test_closed_requested_kinds_reject_property_and_backend_as_family(binding):
    unit, _ = binding
    for bad in ("noninterference", "tla+", "deontic", "hoare", "cwe:CWE-22"):
        with pytest.raises(CodeLogicProjectionError, match="closed unique"):
            project_code_logic(code_unit=unit, source_bytes=BODY, requested_kinds=[bad])


def test_actual_native_cvefixes_projector_body_join():
    from ipfs_datasets_py.logic.security_ir.cvefixes.source_snapshot import CVEFIXES_COLUMNS, adapt_cvefixes_row
    from ipfs_datasets_py.logic.security_ir.cvefixes.projector import project_cvefixes_row
    row = dict.fromkeys(CVEFIXES_COLUMNS)
    row.update(cve_id="CVE-2024-12345", hash="a" * 40, repo_url="https://github.com/example/authored",
        file_paths=["one.py"], language="Python", fixed_code=BODY.decode(), cwe_id="CWE-22")
    native = project_cvefixes_row(adapt_cvefixes_row(row, row_index=0))
    unit = next(item for item in native.code_units if item.unit_kind == "file")
    source = SourceRef(unit.cid, "code-unit:" + unit.cid, unit.path, "authored-fixture",
        unit.payload["body_sha256"], content_cid=unit.payload["body_cid"])
    result = project_code_logic(code_unit=unit, source_bytes=BODY,
        typed_inputs=[CodeLogicEvidence(program(source), source), CodeLogicEvidence(contract(source), source)],
        requested_kinds=["program", "contract"])
    assert result["source"]["source_cids"] == [native.source_cid]
    assert {row["kind"] for row in result["targets"]} == {"program", "contract"}
    assert validate_code_logic_projection(result, code_unit=unit, source_bytes=BODY) == result


def test_duplicate_owners_and_unbounded_inputs_reject(binding):
    unit, source = binding
    item = CodeLogicEvidence(contract(source), source)
    with pytest.raises(CodeLogicProjectionError, match="duplicate"):
        project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=[item, item])
    with pytest.raises(CodeLogicProjectionError, match="bounded immutable"):
        project_code_logic(code_unit=unit, source_bytes=b"x" * 4_000_001)
    with pytest.raises(CodeLogicProjectionError, match="native typed"):
        CodeLogicEvidence({"family": "program", "formula": "safe"}, source)


def test_native_owner_without_bridge_identity_remains_unsupported(binding):
    unit, source = binding
    heap = next(item.document for item in evidence(source) if isinstance(item.document, HeapModel))
    heap = replace(heap, model_id="")
    result = project_code_logic(code_unit=unit, source_bytes=BODY,
        typed_inputs=[CodeLogicEvidence(heap, source)], requested_kinds=["heap"])
    assert result["targets"] == []
    assert result["unsupported"][0]["reason"] == "native_bridge_unsupported"


@pytest.mark.parametrize("container", [list, tuple])
def test_nested_native_metadata_cannot_hide_conflicting_source_refs(binding, container):
    unit, source = binding
    doc = replace(contract(source), attributes={"nested": container([{"source_ref_ids": ["source:other"]}])})
    with pytest.raises(CodeLogicProjectionError, match="different code unit"):
        project_code_logic(code_unit=unit, source_bytes=BODY, typed_inputs=[CodeLogicEvidence(doc, source)])
