"""Shared expression carrier typing and real interpreted pre/post semantics."""
from copy import deepcopy
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_interpretation_expressions as typed
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from tests.unit.logic.formalization.autoencoder.test_native_concurrency_interpretation import fixture
from tests.unit.logic.formalization.autoencoder.test_native_concurrency_lean import lake


def carrier():
    return fixture()[1]["expression_program"]


def recanonicalize(payload):
    payload = deepcopy(payload); payload.pop("program_id", None)
    return ProgramIR.from_dict(payload).to_dict()


def test_existing_native_expression_interpreter_preserves_before_and_after():
    model = typed.TypedExpressions(carrier())
    assert model.fields == {"buffer": "v0"}
    assert model.reads["increase_bounded"] == {"buffer"}
    assert model.special["increase_bounded"] == {"old"}
    assert model.require_root("increase_bounded", "boolean", allow_old=True) == "increase_bounded"
    source = model.store_declaration() + "\ndef condition (before after : Store) : Bool := " + model.render("increase_bounded")
    result = lake(source, """
example : condition ⟨2⟩ ⟨3⟩ = true := by decide
example : condition ⟨2⟩ ⟨4⟩ = false := by decide
example : condition ⟨2⟩ ⟨1⟩ = false := by decide
""")
    assert result["status"] == "passed", result


def test_state_predicates_cannot_read_old_or_use_wrong_result_type():
    model = typed.TypedExpressions(carrier())
    with pytest.raises(UnsupportedNativeLean, match="time_scope"):
        model.require_root("increase_bounded", "boolean")
    with pytest.raises(UnsupportedNativeLean, match="type_mismatch"):
        model.require_root("buffer", "boolean")
    with pytest.raises(UnsupportedNativeLean, match="known_interpretation_expression"):
        model.render("undeclared")


def test_carrier_does_not_silently_drop_real_operations_or_returns():
    payload = carrier()
    payload["commands"][0]["expression_ids"] = ["produce"]
    payload["commands"][0]["evaluation_order"] = ["produce"]
    payload["commands"][0]["effects"]["reads"] = ["buffer"]
    payload["functions"][0]["return_type"] = "integer"
    payload["functions"][0]["effects"]["reads"] = ["buffer"]
    with pytest.raises(UnsupportedNativeLean, match="Boolean_carrier"):
        typed.TypedExpressions(recanonicalize(payload))
    payload = carrier()
    key = payload["commands"][0]["expression_ids"][0]
    next(row for row in payload["expressions"] if row["expression_id"] == key)["attributes"]["value"] = False
    with pytest.raises(UnsupportedNativeLean, match="return_literal_true"):
        typed.TypedExpressions(recanonicalize(payload))


@pytest.mark.parametrize("mutation", [
    lambda p: next(e for e in p["expressions"] if e["expression_id"] == "increase").update(type_ref="boolean"),
    lambda p: p["symbols"][0].update(attributes={"unsigned": True}),
    lambda p: p["functions"][0].update(purity="unknown"),
    lambda p: p.update(metadata={"semantics": "atomic"}),
])
def test_type_and_unmodeled_carrier_semantics_fail_closed(mutation):
    payload = carrier(); mutation(payload)
    with pytest.raises((UnsupportedNativeLean, ValueError)):
        typed.TypedExpressions(recanonicalize(payload))


def test_stale_carrier_identity_and_unsafe_emission_names_are_rejected():
    payload = carrier(); payload["symbols"][0]["name"] = "other"
    with pytest.raises(ValueError): typed.TypedExpressions(payload)
    model = typed.TypedExpressions(carrier())
    with pytest.raises(UnsupportedNativeLean, match="safe_interpretation_store"):
        model.render("buffer", current="s; axiom bad : False")
    with pytest.raises(UnsupportedNativeLean, match="safe_interpretation_store"):
        model.store_declaration("Store\naxiom bad : False")


def test_large_evidence_is_chunked_without_truncating_or_asserting_it():
    value = {"explicit_provenance": "x" * 20000}
    declaration = typed.evidence_strings("retainedEvidence", value)
    chunks = json.loads(declaration.split(":=", 1)[1])
    assert json.loads("".join(chunks)) == value
    assert max(map(len, chunks)) <= 16384
    source = declaration + '\nexample : retainedEvidence.length = 3 := by decide'
    result = lake(source)
    assert result["status"] == "passed", result
