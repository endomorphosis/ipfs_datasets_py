"""The additive effect contract completes reads without erasing declarations."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384 as previous
from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384_v2 as subject
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR


def inputs(operator="<", temporary=False):
    result_type = "integer" if operator in ("+", "-", "*") else "boolean"
    body = (f"    outcome = capacity {operator} threshold\n    return outcome\n" if temporary
            else f"    return capacity {operator} threshold\n")
    source = f"def assess(capacity: int, threshold: int) -> {'int' if result_type == 'integer' else 'bool'}:\n" + body
    refs = ("expr:capacity", "expr:threshold")
    candidate = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", result_type,
        operand_ids=refs, evaluation_order=refs, operator=operator, source_ref_ids=("source",)).to_dict())
    return source, candidate


def payload(operator="<", temporary=False):
    source, candidate = inputs(operator, temporary)
    return previous.qualify_source_candidate(source, candidate)["projections"][0]["native_document"]


def normalize(document):
    document["program_id"] = ""
    return ProgramIR.from_dict(document).to_dict()


@pytest.mark.parametrize("operator", ["+", "-", "*", "<", "<=", ">", ">=", "==", "!="])
@pytest.mark.parametrize("temporary", [False, True])
def test_effects_complete_native_command_reads_and_function_union(operator, temporary):
    source, candidate = inputs(operator, temporary)
    original_candidate = deepcopy(candidate)
    old = previous.qualify_source_candidate(source, candidate)
    result = subject.qualify_source_candidate(source, candidate)
    assert result["schema"] == subject.SCHEMA and result["status"] == "qualified" and result["qualified"]
    assert candidate == original_candidate
    projection, = result["projections"]
    assert projection["bridge"]["preservation"] == "exact"
    program = ProgramIR.from_dict(projection["native_document"])
    native = program.to_dict()
    old_program = old["projections"][0]["native_document"]
    assert all(native["metadata"][key] == value for key, value in old_program["metadata"].items())
    assert set(native["metadata"]) - set(old_program["metadata"]) == set(subject.METADATA_EXTENSION_KEYS)
    assert native["program_id"] != old_program["program_id"]
    assert result["source_binding"]["native_program_id"] == native["program_id"]
    function, = native["functions"]
    commands = {row["command_id"]: row for row in native["commands"]}
    ordered = [commands[key] for key in function["cfg"]["blocks"][0]["command_ids"]]
    parameters = set(function["parameter_symbol_ids"])
    assert set(ordered[0]["effects"]["reads"]) == parameters
    expected_reads = parameters
    if temporary:
        local, = function["local_symbol_ids"]
        assert ordered[0]["effects"]["writes"] == [local]
        assert ordered[1]["effects"]["reads"] == [local] and ordered[1]["effects"]["writes"] == []
        expected_reads = parameters | {local}
        assert function["effects"]["writes"] == [local]
    else:
        assert ordered[0]["effects"]["writes"] == function["effects"]["writes"] == []
    assert set(function["effects"]["reads"]) == expected_reads
    assert function["purity"] == old_program["functions"][0]["purity"]
    assert all(result[key] is False for key in previous._AUTHORITY)
    assert subject.verify_source_qualification(result, source, candidate) == result


def test_audit_reverses_exactly_to_source_qualified_v1_program():
    source, candidate = inputs("+", temporary=True)
    old = payload("+", temporary=True)
    result = subject.qualify_source_candidate(source, candidate)
    wire = deepcopy(result["projections"][0]["native_document"])
    audit = wire["metadata"]["effect_summary_audit"]
    assert audit == result["source_binding"]["effect_summary_refinements"]
    assert audit["base_program_id"] == old["program_id"]
    assert audit["base_program_sha256"] == previous._sha(previous._wire(old))
    for collection, identifier in (("commands", "command_id"), ("functions", "function_id")):
        changes = {row[identifier]: row for row in audit[collection]}
        assert set(changes) == {row[identifier] for row in wire[collection]}
        for row in wire[collection]:
            change = changes[row[identifier]]
            assert {key: row["effects"][key] for key in ("reads", "writes")} == change["after"]
            assert {key: row["effects"][key] for key in subject.EFFECT_OTHER_FIELDS} == change["retained_effects"]
            row["effects"].update(change["before"])
    for key in subject.METADATA_EXTENSION_KEYS:
        del wire["metadata"][key]
    assert normalize(wire) == old


def test_non_read_write_effects_and_unknown_purity_are_preserved():
    before = payload("+", temporary=True)
    for command in before["commands"]:
        command["effects"].update(performs_io=True, nondeterministic=True, synchronizes=True)
    before["functions"][0]["effects"].update(performs_io=True, nondeterministic=True, synchronizes=True)
    before["functions"][0]["purity"] = "unknown"
    before = normalize(before)
    after, audit = subject._complete_effects(before)
    after = after.to_dict()
    assert after["functions"][0]["purity"] == audit["functions"][0]["purity"] == "unknown"
    for collection in ("commands", "functions"):
        for old, new, change in zip(before[collection], after[collection], audit[collection]):
            assert all(new["effects"][key] == old["effects"][key] == change["retained_effects"][key]
                       for key in subject.EFFECT_OTHER_FIELDS)


def test_extra_declared_reads_are_rejected_instead_of_removed():
    before = payload()
    result_id = before["functions"][0]["result_symbol_id"]
    before["commands"][0]["effects"]["reads"] = [result_id]
    before["functions"][0]["effects"]["reads"].append(result_id)
    before = normalize(before)
    saved = deepcopy(before)
    with pytest.raises(subject.EffectContractError, match="declared_effects_exceed"):
        subject._complete_effects(before)
    assert before == saved


@pytest.mark.parametrize("change", ["reordered_operand", "unused_expression", "unsupported_operator", "incompatible_type"])
def test_ambiguous_or_unsupported_native_graphs_are_not_given_effects(change):
    before = payload("+", temporary=True)
    expression = next(row for row in before["expressions"] if row["kind"] == "binary")
    if change == "reordered_operand":
        expression["evaluation_order"].reverse()
    elif change == "unused_expression":
        copied = deepcopy(next(row for row in before["expressions"] if row["kind"] == "symbol"))
        copied["expression_id"] = "expr:unused"
        before["expressions"].append(copied)
    elif change == "unsupported_operator":
        expression["operator"] = "floordiv"
    else:
        expression["type_ref"] = "boolean"
    before = normalize(before)
    with pytest.raises(subject.EffectContractError):
        subject._complete_effects(before)


def test_invalid_native_expression_reference_is_rejected():
    before = payload()
    next(row for row in before["expressions"] if row["kind"] == "binary")["operand_ids"][0] = "foreign"
    with pytest.raises(ValueError):
        subject._complete_effects(before)


def test_reapplying_effect_refinement_is_rejected():
    completed, _ = subject._complete_effects(payload())
    with pytest.raises(subject.EffectContractError, match="already_present"):
        subject._complete_effects(completed.to_dict())


@pytest.mark.parametrize("change", ["source_bytes", "audit_reads", "purity", "base_hash"])
def test_replay_rejects_effect_provenance_drift(change):
    source, candidate = inputs("+", temporary=True)
    report = subject.qualify_source_candidate(source, candidate)
    if change == "source_bytes":
        source += "# changed\n"
    elif change == "audit_reads":
        report["source_binding"]["effect_summary_refinements"]["commands"][0]["after"]["reads"] = []
    elif change == "purity":
        report["projections"][0]["native_document"]["functions"][0]["purity"] = "pure"
    else:
        report["projections"][0]["native_document"]["metadata"]["effect_summary_audit"]["base_program_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="exact replay"):
        subject.verify_source_qualification(report, source, candidate)


def test_v1_mismatch_and_unsupported_boundaries_remain_fail_open():
    source, candidate = inputs()
    candidate["document"]["operator"] = "<="
    saved = deepcopy(candidate)
    result = subject.qualify_source_candidate(source, candidate)
    assert result["status"] == "mismatch" and not result["projections"] and candidate == saved
    result = subject.qualify_source_candidate(source.replace(": int", ""), candidate)
    assert result["status"] == "unsupported" and not result["projections"]


def test_effect_contract_failure_is_fail_open(monkeypatch):
    source, candidate = inputs()

    def broken(_):
        raise subject.EffectContractError("unsupported_expression_graph")

    monkeypatch.setattr(subject, "_complete_effects", broken)
    result = subject.qualify_source_candidate(source, candidate)
    assert result["status"] == "unsupported" and result["reason"] == "unsupported_expression_graph"
    assert not result["qualified"] and not result["projections"] and result["source_binding"] is None
