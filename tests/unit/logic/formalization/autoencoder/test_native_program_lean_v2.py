"""Source-bound operational Lean evidence consumes exact metadata and effects."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_program_lean as previous
from ipfs_datasets_py.logic.formalization.autoencoder import native_program_lean_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384_v2 as binding
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR

OPERATORS = {"+": 6, "-": 2, "*": 8, "<": False, "<=": False,
    ">": True, ">=": True, "==": False, "!=": True}


def fixture(operator="+", temporary=False):
    type_ = "boolean" if operator in ("<", "<=", ">", ">=", "==", "!=") else "integer"
    source = f"def combine(left: int, right: int) -> {'bool' if type_ == 'boolean' else 'int'}:\n"
    source += (f"    outcome = left {operator} right\n    return outcome\n" if temporary
        else f"    return left {operator} right\n")
    refs = ("expr:left", "expr:right")
    candidate = {"kind": "program_expression", "document": ProgramExpression("expr:result", "binary", type_,
        operand_ids=refs, evaluation_order=refs, operator=operator, source_ref_ids=("source",)).to_dict()}
    qualified = binding.qualify_source_candidate(source, candidate)
    assert qualified["status"] == "qualified", qualified
    return qualified["projections"][0]["native_document"]


def rebuild(payload):
    payload.pop("program_id", None)
    return ProgramIR.from_dict(payload).to_dict()


@pytest.mark.parametrize("temporary", [False, True])
@pytest.mark.parametrize("operator", OPERATORS)
def test_all_nine_source_operators_emit_exact_original_metadata_and_complete_effects(operator, temporary):
    payload = fixture(operator, temporary)
    before = deepcopy(payload)
    source, details = subject.emit_program(payload)
    assert payload == before
    assert details["profile"] == subject.PROFILE
    assert details["program_sha256"] == subject._digest(payload)
    assert details["original_metadata_sha256"] == subject._digest(payload["metadata"])
    assert details["original_program_id"] == payload["program_id"]
    assert details["operational_view_program_id"] != details["original_program_id"]
    assert details["operational_view_sha256"] != details["program_sha256"]
    assert details["original_program_modified"] is False
    assert details["source_bytes_replayed"] is False
    assert details["source_hash_consistency_checked"] is True
    assert details["complete_read_write_summaries_checked"] is True
    assert details["metadata_emitted_as_explicit_evidence"] is True
    assert details["effect_audit"] == payload["metadata"]["effect_summary_audit"]
    assert details["original_source_references"] == payload["sources"]
    assert "def sourceEvidenceMetadataJSON : String" in source
    assert "def sourceEvidenceEffectAuditJSON : String" in source
    assert "def sourceEvidenceAssumptions : List String" in source
    assert "def sourceEvidence_commands_reads : List (String × List String)" in source
    assert "def sourceEvidence_functions_writes : List (String × List String)" in source
    assert all(details[key] is False for key in subject.AUTHORITY)
    function = payload["functions"][0]
    expected_reads = set(function["parameter_symbol_ids"]) | (set(function["local_symbol_ids"]) if temporary else set())
    assert details["actual_reads"] == sorted(expected_reads)
    assert details["actual_writes"] == sorted(function["local_symbol_ids"])
    with pytest.raises(UnsupportedNativeLean, match="metadata"):
        previous.emit_program(payload)


@pytest.mark.parametrize("change,reason", [
    (lambda p: p["metadata"].update(unreviewed_semantics=True), "closed_source_effect_metadata"),
    (lambda p: p["metadata"].update(proof_authority=True), "authority"),
    (lambda p: p["metadata"].update(proof_authority=0), "authority"),
    (lambda p: p["metadata"]["assumptions"].pop(), "assumptions"),
    (lambda p: p["metadata"].update(effect_summary_assumption="Trust all effects."), "assumption"),
    (lambda p: p["metadata"].update(source_sha256="0" * 64), "hash_mismatch"),
    (lambda p: p["sources"][0]["metadata"].update(unknown=True), "closed_source_reference"),
    (lambda p: p["sources"][0]["metadata"].update(byte_length=1), "span_bounds"),
    (lambda p: p["metadata"]["effect_summary_audit"].update(unknown=True), "closed_source_effect_audit"),
    (lambda p: p["metadata"]["effect_summary_audit"].update(base_program_sha256="0" * 64), "original_program_identity"),
    (lambda p: p["metadata"]["effect_summary_audit"]["commands"][0].update(unknown=True), "closed_effect_audit_record"),
    (lambda p: p["metadata"]["effect_summary_audit"]["commands"][0]["after"].update(reads=[]), "complete_exact_operational_effect"),
    (lambda p: p["metadata"]["effect_summary_audit"]["commands"][0]["retained_effects"].update(performs_io=True), "effects_changed"),
    (lambda p: p["metadata"]["effect_summary_audit"]["functions"][0].update(purity="pure"), "purity_changed"),
])
def test_unknown_or_forged_metadata_effects_and_authority_fail_closed(change, reason):
    payload = fixture(temporary=True)
    change(payload)
    with pytest.raises((UnsupportedNativeLean, ValueError), match=reason):
        subject.emit_program(rebuild(payload))


def test_omitted_command_reads_cannot_be_hidden_by_consistent_forged_audit():
    payload = fixture(temporary=True)
    command = next(row for row in payload["commands"] if row["kind"] == "return")
    command["effects"]["reads"] = []
    audit = payload["metadata"]["effect_summary_audit"]
    next(row for row in audit["commands"] if row["command_id"] == command["command_id"])["after"]["reads"] = []
    with pytest.raises(UnsupportedNativeLean, match="actual_program_reads_exceed"):
        subject.emit_program(rebuild(payload))


def test_base_lineage_reconstruction_detects_rewritten_before_effects():
    payload = fixture()
    record = payload["metadata"]["effect_summary_audit"]["commands"][0]
    record["before"]["reads"] = record["after"]["reads"]
    with pytest.raises(UnsupportedNativeLean, match="original_program_identity"):
        subject.emit_program(rebuild(payload))


def test_effect_refinement_cannot_erase_previous_declared_effect_bounds():
    payload = fixture(temporary=True)
    record = next(row for row in payload["metadata"]["effect_summary_audit"]["commands"]
        if row["after"]["writes"])
    record["before"]["writes"] = sorted([payload["functions"][0]["parameter_symbol_ids"][0], *record["after"]["writes"]])
    with pytest.raises(UnsupportedNativeLean, match="must_not_erase"):
        subject.emit_program(rebuild(payload))


def test_projection_dispatch_does_not_claim_contract_or_other_family_support():
    for row in ({"logic_family": "program", "payload": {"schema_version": "program-contract/v1"}},
                {"logic_family": "deontic", "payload": fixture()}):
        with pytest.raises(NotImplementedError):
            subject.emit_projection(row)
    payload = fixture()
    assert subject.emit_projection({"logic_family": "program", "payload": payload}) == subject.emit_program(payload)


def _lean_value(value):
    return str(value).lower() if type(value) is bool else f"({value} : Int)"


def test_real_lake_compiles_evidence_and_executes_all_nine_operations_in_both_source_forms():
    available = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not available:
        pytest.skip("Installed Lake unavailable; no download attempted")
    fragments = ["set_option autoImplicit false", "namespace SourceProgramV2"]
    for index, (operator, expected) in enumerate(OPERATORS.items()):
        for temporary in (False, True):
            payload = fixture(operator, temporary)
            source, _ = subject.emit_program(payload)
            initial_fields, final_fields = [], []
            for position, symbol in enumerate(payload["symbols"]):
                value = 4 if symbol["name"] == "left" else 2 if symbol["name"] == "right" else (
                    False if symbol["type_ref"] == "boolean" else 0)
                initial_fields.append(f"v{position} := {_lean_value(value)}")
                final_value = expected if symbol["kind"] == "local" else value
                final_fields.append(f"v{position} := {_lean_value(final_value)}")
            fragments.extend([f"namespace Case{index}_{int(temporary)}", source,
                "def initialExample : Store := { " + ", ".join(initial_fields) + " }",
                "def finalExample : Store := { " + ", ".join(final_fields) + " }",
                "example : run initialExample = Outcome.returned finalExample " + _lean_value(expected) + " := by decide",
                f"end Case{index}_{int(temporary)}"])
    fragments.append("end SourceProgramV2")
    receipt = _execute("\n\n".join(fragments), "SourceProgramV2", available[-1], 60)
    assert receipt["status"] == "passed", receipt
