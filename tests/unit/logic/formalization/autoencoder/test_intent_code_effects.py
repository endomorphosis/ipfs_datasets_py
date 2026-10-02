"""Explicit cross-source action effects retain all bounded cases and provenance."""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_interpretation_expressions as typed
from ipfs_datasets_py.logic.formalization.autoencoder.security.source_state_model import derive_source_state_model
from ipfs_datasets_py.logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
    StatementKind, IntentModality, IntentAction, SourceRef)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef as CodeSourceRef
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramSymbol, ProgramIR


def fixture(status="satisfied", *, operator="+", temporary=False, precondition_lower_bound=None):
    """Return six explicit inputs; Intent/effect declarations are authored controls."""
    assert status in {"satisfied", "refuted", "no_enabled_cases"}
    boolean = operator in {"<", "<=", ">", ">=", "==", "!="}
    expected_operator = "-" if status == "refuted" else operator
    result_type = "boolean" if boolean else "integer"
    instruction = "Compute the declared scalar result and finish, under the explicit input condition."
    sha = hashlib.sha256(instruction.encode()).hexdigest()
    ref = SourceRef("instruction:source", "urn:authored:intent-code-fixture", "authored", sha, content_sha256=sha)
    statements = (
        IntentStatement("goal", StatementKind.GOAL, IntentModality.REQUIRED, "Compute the scalar result.",
            (ref.ref_id,), "compute", ("operator", "result")),
        IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED, "The declared input condition holds.",
            (ref.ref_id,), "allowed_input", ("left", "right")),
        IntentStatement("effect", StatementKind.POSTCONDITION, IntentModality.ASSERTED,
            "The returned result has the declared input-dependent value.",
            (ref.ref_id,), "returned_value", ("result", "left", "right")),
    )
    action = IntentAction("compute", "operator", "compute", ("result",), (ref.ref_id,),
        precondition_ids=("pre",), effect_ids=("effect",))
    document = IntentIRDocument("bound-intent", "Authored scalar contract", IntentKind.PROCEDURE,
        (ref,), statements, (action,), (), (action.action_id,), (action.action_id,))
    source = "def compute(left: int, right: int) -> " + ("bool" if boolean else "int") + ":\n"
    source += ("    answer = left " + operator + " right\n    return answer\n" if temporary else
        "    return left " + operator + " right\n")
    operands = ("expr:left", "expr:right")
    candidate = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", result_type,
        operand_ids=operands, evaluation_order=operands, operator=operator, source_ref_ids=("source",)).to_dict())
    domains = {name: dict(lower=-1, upper=1) for name in ("left", "right")}
    inputs = (instruction, document.to_dict(), source, candidate, domains)
    requirement = api.intent_code_effect_requirements(*inputs)
    model = derive_source_state_model(source, candidate, domains)
    code_ref = CodeSourceRef.from_dict(requirement["code_source_refs"][0])
    ids = (code_ref.ref_id,)
    symbols, expressions, mappings = [], [], []
    variable_ids = [model["parameter_variables"][name] for name in model["parameter_order"]]
    variable_ids += [model["result_variable_id"], model["returned_variable_id"]]
    for name, variable_id, kind in zip(("left", "right", "result", "returned"), variable_ids,
            ("integer", "integer", result_type, "boolean")):
        sid = "symbol:" + name
        symbols.append(ProgramSymbol(sid, name, type_ref=kind, kind="global", source_ref_ids=ids))
        expressions.append(ProgramExpression("read:" + name, "symbol", kind,
            symbol_ids=(sid,), source_ref_ids=ids))
        mappings.append(dict(symbol_id=sid, state_variable_id=variable_id))
    for name in ("left", "right"):
        operands = ("read:" + name,)
        expressions.append(ProgramExpression("old:" + name, "old", "integer", operand_ids=operands,
            evaluation_order=operands, source_ref_ids=ids))
    operators = {"+": "add", "-": "sub", "*": "mul", "<": "lt", "<=": "le",
        ">": "gt", ">=": "ge", "==": "eq", "!=": "ne"}
    def binary(identity, kind, operation, left, right):
        expressions.append(ProgramExpression(identity, "binary", kind, operator=operation,
            operand_ids=(left, right), evaluation_order=(left, right), source_ref_ids=ids))
    binary("expected", result_type, operators[expected_operator], "old:left", "old:right")
    binary("result_matches", "boolean", "eq", "read:result", "expected")
    binary("effect", "boolean", "and", "read:returned", "result_matches")
    if status == "no_enabled_cases" or precondition_lower_bound is not None:
        limit = 100 if status == "no_enabled_cases" else precondition_lower_bound
        expressions.append(ProgramExpression("limit", "literal", "integer", attributes={"value": limit}, source_ref_ids=ids))
        binary("pre", "boolean", "gt", "read:left", "limit")
    else:
        expressions.append(ProgramExpression("pre", "literal", "boolean", attributes={"value": True}, source_ref_ids=ids))
    carrier = typed.make_carrier(symbols, expressions, sources=(code_ref,))
    association = dict(schema=api.ASSOCIATION_SCHEMA,
        **{key: requirement[key] for key in api.IDENTITY_FIELDS},
        action_id=action.action_id, intent_evidence_ref=ref.ref_id, code_evidence_ref=code_ref.ref_id,
        expression_program=carrier, symbol_bindings=mappings,
        precondition_bindings=[dict(statement_id="pre", expression_id="pre", evidence_ref=ref.ref_id)],
        effect_bindings=[dict(statement_id="effect", expression_id="effect", evidence_ref=ref.ref_id)])
    return (*inputs, association)


def recanonicalize(inputs):
    carrier = inputs[-1]["expression_program"]
    carrier.pop("program_id", None)
    inputs[-1]["expression_program"] = ProgramIR.from_dict(carrier).to_dict()
    return inputs


@pytest.mark.parametrize("operator", ["+", "-", "*", "<", "<=", ">", ">=", "==", "!="])
@pytest.mark.parametrize("temporary", [False, True])
def test_all_supported_scalar_forms_bind_input_dependent_effects_without_source_rebinding(operator, temporary):
    inputs = fixture(operator=operator, temporary=temporary)
    before = deepcopy(inputs)
    result = api.prepare_intent_code_effects(*inputs)
    assert inputs == before
    assert result["status"] == "satisfied" and result["enabled_case_count"] == result["case_count"] == 9
    assert result["all_enabled_effects_satisfied"] and not result["bounded_effects_satisfied"]
    assert all(row["enabled"] and row["effects_passed"] for row in result["cases"])
    assert result["intent_candidate_ir"] == inputs[1] and result["code_candidate_ir"] == inputs[3]
    assert result["intent_source_refs"] == inputs[1]["sources"]
    assert result["code_source_refs"] == result["source_state_model"]["source_program"]["sources"]
    assert result["intent_source_refs"] != result["code_source_refs"]
    assert result["unselected_statement_ids"] == ["goal"]
    assert all(result[key] is False for key in api.FALSE)
    assert api.verify_intent_code_effects(result, *inputs) == result


def test_false_effect_is_a_refutation_and_keeps_every_witness_case():
    result = api.prepare_intent_code_effects(*fixture("refuted"))
    assert result["status"] == "refuted" and result["enabled_case_count"] == 9
    assert result["counterexample_case_indices"] == [0, 2, 3, 5, 6, 8]
    assert len(result["cases"]) == 9 and not result["all_enabled_effects_satisfied"]
    witness = result["cases"][0]
    assert witness["parameter_values"] == {"left": -1, "right": -1}
    assert witness["after_state"]["state:result"] == -2
    assert witness["preconditions"][0]["value"] is True and witness["effects"][0]["value"] is False


def test_no_enabled_cases_remains_blocked_despite_vacuous_implications():
    result = api.prepare_intent_code_effects(*fixture("no_enabled_cases"))
    assert result["status"] == "no_enabled_cases" and result["enabled_case_count"] == 0
    assert result["disabled_case_count"] == 9 and result["counterexample_case_indices"] == []
    assert all(row["conditional_effects_passed"] for row in result["cases"])
    assert not result["all_enabled_effects_satisfied"] and not result["bounded_effects_satisfied"]


def test_false_effects_on_disabled_inputs_remain_visible_without_becoming_counterexamples():
    result = api.prepare_intent_code_effects(*fixture("refuted", precondition_lower_bound=0))
    assert result["status"] == "refuted" and result["enabled_case_count"] == 3
    assert result["disabled_case_count"] == 6 and len(result["cases"]) == 9
    assert result["counterexample_case_indices"] == [6, 8]
    assert result["cases"][0]["effects_passed"] is False
    assert result["cases"][0]["enabled"] is False and result["cases"][0]["conditional_effects_passed"] is True


@pytest.mark.parametrize("status", ["satisfied", "refuted"])
def test_native_unary_boolean_and_conditional_expression_operators_preserve_case_verdicts(status):
    inputs = list(fixture(status))
    expected = api.prepare_intent_code_effects(*inputs)
    carrier = inputs[-1]["expression_program"]
    refs = (carrier["sources"][0]["ref_id"],)
    def add(identity, kind, type_ref, children, operator=""):
        carrier["expressions"].append(ProgramExpression(identity, kind, type_ref, operator=operator,
            operand_ids=children, evaluation_order=children, source_ref_ids=refs).to_dict())
    add("negative", "unary", "integer", ("expected",), "neg")
    add("positive", "unary", "integer", ("negative",), "pos")
    add("restored", "unary", "integer", ("positive",), "neg")
    for expression in carrier["expressions"]:
        if expression["expression_id"] == "result_matches":
            expression["operand_ids"] = expression["evaluation_order"] = ["read:result", "restored"]
    add("negative_effect", "unary", "boolean", ("effect",), "not")
    add("restored_effect", "unary", "boolean", ("negative_effect",), "not")
    add("conditional", "conditional", "boolean", ("read:returned", "restored_effect", "pre"))
    add("alternative", "binary", "boolean", ("conditional", "effect"), "or")
    inputs[-1]["effect_bindings"][0]["expression_id"] = "alternative"
    actual = api.prepare_intent_code_effects(*recanonicalize(inputs))
    assert actual["status"] == expected["status"]
    assert actual["counterexample_case_indices"] == expected["counterexample_case_indices"]


def test_explicit_old_result_reads_before_observation_not_after_output():
    inputs = list(fixture())
    carrier = inputs[-1]["expression_program"]
    refs = (carrier["sources"][0]["ref_id"],)
    carrier["expressions"] = [row for row in carrier["expressions"] if row["expression_id"]
        not in {"old:left", "old:right", "expected", "read:left", "read:right"}]
    carrier["expressions"].append(ProgramExpression("old:result", "old", "integer",
        operand_ids=("read:result",), evaluation_order=("read:result",), source_ref_ids=refs).to_dict())
    for row in carrier["expressions"]:
        if row["expression_id"] == "result_matches":
            row["operand_ids"] = row["evaluation_order"] = ["read:result", "old:result"]
    result = api.prepare_intent_code_effects(*recanonicalize(inputs))
    assert result["status"] == "refuted"
    assert result["counterexample_case_indices"] == [0, 1, 3, 5, 7, 8]


@pytest.mark.parametrize("change", ["prohibited_effect", "goal_as_effect", "conflicting_predicate", "source_ref_collision"])
def test_existing_native_statement_modality_meaning_and_provenance_cannot_be_reinterpreted_silently(change):
    inputs = list(fixture())
    document = inputs[1]
    statements = {row["statement_id"]: row for row in document["statements"]}
    if change == "prohibited_effect": statements["effect"]["modality"] = "prohibited"
    elif change == "goal_as_effect":
        statements["effect"]["kind"] = "goal"
        with pytest.raises(ValueError, match="incompatible statement kinds"):
            api.intent_code_effect_requirements(*inputs[:5])
        return
    elif change == "conflicting_predicate":
        statements["effect"]["predicate"] = statements["pre"]["predicate"]
        statements["effect"]["arguments"] = list(statements["pre"]["arguments"])
    else:
        old = document["sources"][0]["ref_id"]
        new = inputs[-1]["code_evidence_ref"]
        document["sources"][0]["ref_id"] = new
        for row in [*document["statements"], *document["actions"]]:
            row["source_ref_ids"] = [new if key == old else key for key in row["source_ref_ids"]]
        with pytest.raises(ValueError, match="conflicting cross-source"):
            api.intent_code_effect_requirements(*inputs[:5])
        return
    req = api.intent_code_effect_requirements(*inputs[:5])
    inputs[-1].update({key: req[key] for key in api.IDENTITY_FIELDS})
    with pytest.raises(ValueError, match="asserted native|conflicting interpretation"):
        api.prepare_intent_code_effects(*inputs)


def test_carrier_provenance_cannot_replace_code_source_or_hide_unused_expressions():
    inputs = list(fixture())
    carrier = inputs[-1]["expression_program"]
    carrier["sources"][0]["content_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="exact original code"):
        api.prepare_intent_code_effects(*recanonicalize(inputs))
    inputs = list(fixture())
    inputs[-1]["expression_program"]["expressions"].append(ProgramExpression("unused", "literal", "boolean",
        attributes={"value": False}, source_ref_ids=(inputs[-1]["code_evidence_ref"],)).to_dict())
    with pytest.raises(ValueError, match="every declared"):
        api.prepare_intent_code_effects(*recanonicalize(inputs))


@pytest.mark.parametrize("field", sorted(api.IDENTITY_FIELDS))
def test_association_cannot_borrow_either_source_candidate_or_model_identity(field):
    inputs = list(fixture()); inputs[-1][field] = "0" * 64
    with pytest.raises(ValueError, match="identity"):
        api.prepare_intent_code_effects(*inputs)


@pytest.mark.parametrize("change", ["extra", "action", "intent_ref", "code_ref", "missing_effect", "extra_goal",
    "duplicate_effect", "missing_pre", "foreign_effect_ref", "wrong_root_type", "old_pre", "symbol", "type", "extra_symbol"])
def test_closed_typed_complete_condition_and_symbol_associations_are_required(change):
    inputs = list(fixture()); a = inputs[-1]
    if change == "extra": a["verified"] = True
    elif change == "action": a["action_id"] = "missing"
    elif change == "intent_ref": a["intent_evidence_ref"] = a["code_evidence_ref"]
    elif change == "code_ref": a["code_evidence_ref"] = a["intent_evidence_ref"]
    elif change == "missing_effect": a["effect_bindings"] = []
    elif change == "extra_goal": a["effect_bindings"].append({**a["effect_bindings"][0], "statement_id": "goal"})
    elif change == "duplicate_effect": a["effect_bindings"] *= 2
    elif change == "missing_pre": a["precondition_bindings"] = []
    elif change == "foreign_effect_ref": a["effect_bindings"][0]["evidence_ref"] = a["code_evidence_ref"]
    elif change == "wrong_root_type": a["effect_bindings"][0]["expression_id"] = "expected"
    elif change == "old_pre": a["precondition_bindings"][0]["expression_id"] = "effect"
    elif change == "symbol": a["symbol_bindings"][0]["state_variable_id"] = "missing"
    elif change == "type": a["symbol_bindings"][0]["state_variable_id"] = "state:returned"
    else: a["symbol_bindings"].append(deepcopy(a["symbol_bindings"][0]))
    with pytest.raises(ValueError): api.prepare_intent_code_effects(*inputs)


@pytest.mark.parametrize("field", ["cases", "source_state_model", "intent_document", "association", "status", "enabled_case_count",
    "variable_symbols", "proof_authority", "unselected_statement_ids"])
def test_rehashed_saved_report_is_not_authority(field):
    inputs = fixture(); report = api.prepare_intent_code_effects(*inputs)
    if field == "status": report[field] = "refuted"
    elif field == "proof_authority": report[field] = True
    elif field == "enabled_case_count": report[field] = 0
    elif field in ("cases", "unselected_statement_ids"): report[field] = []
    else: report[field] = {}
    report["report_sha256"] = api._digest({key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="replay"):
        api.verify_intent_code_effects(report, *inputs)


def test_learned_atomic_intent_without_effects_cannot_receive_invented_effects():
    inputs = list(fixture())
    inputs[0] = "The operator must classify the report."
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
    inputs[1] = {"kind": "intent_rich_ast", "document": parse_instruction(inputs[0])}
    req = api.intent_code_effect_requirements(*inputs[:5])
    inputs[-1].update({key: req[key] for key in api.IDENTITY_FIELDS})
    inputs[-1]["action_id"] = req["actions"][0]["action_id"]
    with pytest.raises(ValueError, match="no declared effects"):
        api.prepare_intent_code_effects(*inputs)
