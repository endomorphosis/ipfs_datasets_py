"""Source binding is an independent abstaining check, never decoder repair."""
import copy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384 as binding
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR


def candidate(operator="<", *, left="capacity", right="threshold"):
    refs = ("expr:" + left, "expr:" + right)
    return dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
        "integer" if operator in {"+", "-", "*", "//", "^"} else "boolean",
        operand_ids=refs, evaluation_order=refs, operator=operator,
        source_ref_ids=("source",)).to_dict())


def source(operator="<", *, temporary=False):
    annotation = "int" if operator in {"+", "-", "*", "//", "^"} else "bool"
    body = (f"    temporary = capacity {operator} threshold\n    return temporary\n" if temporary
            else f"    return capacity {operator} threshold\n")
    return f"def assess(capacity: int, threshold: int) -> {annotation}:\n" + body


@pytest.mark.parametrize("operator", ["+", "-", "*", "<", "<=", ">", ">=", "==", "!="])
@pytest.mark.parametrize("temporary", [False, True])
def test_complete_native_context_with_exact_source_provenance(operator, temporary):
    text, predicted = source(operator, temporary=temporary), candidate(operator)
    saved = copy.deepcopy(predicted)
    report = binding.qualify_source_candidate(text, predicted)
    assert report["status"] == "qualified" and report["qualified"]
    assert predicted == saved
    assert report["provider_calls"] == report["solver_calls"] == 0
    assert not report["executes_source"]
    assert all(report[key] is False for key in binding._AUTHORITY)
    projection, = report["projections"]
    assert (projection["family_id"], projection["profile_id"]) == ("program", "program_ir")
    assert projection["bridge"]["preservation"] == "exact"
    program = ProgramIR.from_dict(projection["native_document"])
    assert program.sources[0].content_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert {symbol.type_ref for symbol in program.symbols if symbol.kind.value == "parameter"} == {"integer"}
    assert program.functions[0].return_type == predicted["document"]["type_ref"]
    refs = report["source_binding"]["expression_references"]
    expression = next(row for row in program.expressions if row.expression_id == refs["expr:result"])
    assert expression.operand_ids == (refs["expr:capacity"], refs["expr:threshold"])
    assert expression.evaluation_order == expression.operand_ids
    assert expression.type_ref == predicted["document"]["type_ref"]
    for row in report["source_binding"]["spans"]:
        assert row["sha256"] == hashlib.sha256(text.encode()[row["start_byte"]:row["end_byte"]]).hexdigest()
    assert binding.verify_source_qualification(report, text, predicted) == report


@pytest.mark.parametrize("field,value", [
    ("operator", "<="), ("type_ref", "integer"),
    ("operand_ids", ["expr:threshold", "expr:capacity"]),
    ("evaluation_order", ["expr:threshold", "expr:capacity"]),
    ("evaluation_order", []), ("source_ref_ids", ["foreign"]),
    ("span_ids", ["invented"]), ("expression_id", "invented"),
    ("symbol_ids", ["symbol:foreign"]), ("attributes", {"proof_authority": True}),
])
def test_candidate_drift_is_rejected_without_correction(field, value):
    predicted = candidate()
    predicted["document"][field] = value
    before = copy.deepcopy(predicted)
    report = binding.qualify_source_candidate(source(), predicted)
    assert report["status"] == "mismatch"
    assert not report["qualified"] and not report["projections"]
    assert report["source_binding"] is None
    assert predicted == before


@pytest.mark.parametrize("text,reason", [
    ("def assess(capacity, threshold):\n    return capacity < threshold\n", "explicit_integer_parameter_annotations_required"),
    (source().replace("capacity: int", "capacity: float"), "explicit_integer_parameter_annotations_required"),
    (source().replace("capacity", "result"), "candidate_expression_reference_collision"),
    (source().replace("-> bool", "-> int"), "return_annotation_mismatch"),
    (source().replace("return capacity < threshold", "return capacity < threshold < 3"), "single_binary_expression_required"),
    (source().replace("return capacity < threshold", "return capacity < foreign"), "both_distinct_parameters_must_be_operands"),
    (source().replace("return capacity < threshold", "return check(capacity, threshold)"), "single_binary_expression_required"),
    (source().replace("threshold: int", "threshold: int = 1"), "function_signature_unsupported"),
    ("@decorator\n" + source(), "function_signature_unsupported"),
    (source() + source().replace("assess", "another"), "one_plain_function_required"),
    (source(temporary=True).replace("temporary =", "capacity =").replace("return temporary", "return capacity"), "parameter_reassignment_unsupported"),
    (source(temporary=True).replace("return temporary", "return threshold"), "temporary_return_mismatch"),
    (source().replace("return capacity < threshold", "if capacity:\n        return threshold"), "direct_return_or_single_temporary_required"),
    (source("//"), "operator_semantics_unsupported"),
    (source("^"), "operator_semantics_unsupported"),
])
def test_unsupported_source_never_invents_enclosing_context(text, reason):
    report = binding.qualify_source_candidate(text, candidate())
    assert report["status"] == "unsupported" and report["reason"] == reason
    assert not report["projections"] and not report["qualified"]


def test_swapped_source_operand_order_requires_same_predicted_order():
    text = source().replace("capacity < threshold", "threshold < capacity")
    assert binding.qualify_source_candidate(text, candidate())["status"] == "mismatch"
    assert binding.qualify_source_candidate(text, candidate(left="threshold", right="capacity"))["qualified"]


def test_replay_rejects_source_comment_or_evidence_drift():
    text, predicted = source(), candidate()
    report = binding.qualify_source_candidate(text, predicted)
    with pytest.raises(ValueError, match="exact replay"):
        binding.verify_source_qualification(report, text + "# changed bytes\n", predicted)
    modified = copy.deepcopy(report)
    modified["source_binding"]["source_references"]["source"] = "foreign"
    with pytest.raises(ValueError, match="exact replay"):
        binding.verify_source_qualification(modified, text, predicted)


def test_native_source_adapter_drift_abstains(monkeypatch):
    native = binding.adapt_source_to_software_verification

    def altered(*args, **kwargs):
        result = native(*args, **kwargs)
        # A valid program may still disagree with the original AST; validation
        # alone must not admit a subtly changed native lowering.
        from dataclasses import replace
        changed = tuple(replace(row, operator="le") if row.kind.value == "binary" else row
                        for row in result.program.expressions)
        program = replace(result.program, expressions=changed, program_id="")
        return replace(result, program=program)

    monkeypatch.setattr(binding, "adapt_source_to_software_verification", altered)
    report = binding.qualify_source_candidate(source(), candidate())
    assert report["status"] == "unsupported" and report["reason"] == "native_operation_changed"
    assert not report["projections"]


@pytest.mark.parametrize("value", [None, 3, {}, {"kind": "program_expression", "document": float("nan")},
                                    {"kind": "program_expression", "document": {}},
                                    {**candidate(), "proof_authority": True}])
def test_malformed_candidates_fail_open(value):
    report = binding.qualify_source_candidate(source(), value)
    assert not report["qualified"] and not report["projections"]


def test_source_resource_bound():
    report = binding.qualify_source_candidate("x" * (binding.MAX_SOURCE_BYTES + 1), candidate())
    assert report["reason"] == "source_size_bound"
