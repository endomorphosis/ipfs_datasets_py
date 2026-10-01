"""Interpretation evidence never changes native declarations or source identity."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import supplemental_context as api
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import digest
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context


def rows(kind="concurrency", document=None):
    return [{"kind": kind, "interpretation": {"schema": "emitter-owned", "native_document_sha256": digest(document or {})}}]


@pytest.mark.parametrize("change", ["kind", "duplicate", "field", "digest", "not_list", "not_document"])
def test_closed_bounded_unique_interpretation_envelope(change):
    value = rows()
    if change == "kind": value[0]["kind"] = "authorization"
    elif change == "duplicate": value *= 2
    elif change == "field": value[0]["proof_authority"] = True
    elif change == "digest": value[0]["interpretation"]["native_document_sha256"] = "G" * 64
    elif change == "not_list": value = tuple(value)
    else: value[0]["interpretation"] = []
    with pytest.raises(ValueError): api.canonical_interpretations(value)


def test_split_preserves_original_context_and_exact_native_payloads():
    inputs = {"code_unit": {"unchanged": True}, api.KEY: rows()}
    context = bind_context("security_ir", {"candidate": 1}, "exact source", inputs)
    original = deepcopy(context)
    native, evidence = api.split_context("security_ir", {"candidate": 1}, "exact source", context)
    assert context == original and native["inputs"] == {"code_unit": {"unchanged": True}}
    assert evidence == inputs[api.KEY]
    assert native["candidate_sha256"] == context["candidate_sha256"]
    assert native["source_sha256"] == context["source_sha256"]
    evidence[0]["interpretation"]["schema"] = "mutated"
    assert context == original


@pytest.mark.parametrize("domain", ["intent_ir", "legal_ir", "ui_ux_ir"])
def test_interpretations_cannot_enter_an_unrelated_domain(domain):
    context = bind_context(domain, {}, "source", {api.KEY: rows()})
    with pytest.raises(ValueError, match="SecurityIR"):
        api.split_context(domain, {}, "source", context)


@pytest.mark.parametrize("change", ["absent", "duplicate", "native", "domain"])
def test_every_interpretation_must_bind_one_active_exact_native_document(change):
    document = {"unchanged": 1}
    report = {"domain_id": "security_ir", "projections": [dict(
        projection_id="security_ir/supplemental/concurrency/v2", payload={"native_document": document})]}
    value = rows(document=document)
    if change == "absent": report["projections"] = []
    elif change == "duplicate": report["projections"] *= 2
    elif change == "native": report["projections"][0]["payload"]["native_document"] = {"unchanged": 2}
    else: report["domain_id"] = "intent_ir"
    with pytest.raises(ValueError): api.validate_native_bindings(value, report)


def test_valid_binding_retains_full_emitter_owned_interpretation():
    document = {"unchanged": 1}
    value = rows(document=document)
    report = {"domain_id": "security_ir", "projections": [dict(
        projection_id="security_ir/supplemental/concurrency/v2", payload={"native_document": document})]}
    result = api.validate_native_bindings(value, report)
    assert result == {"security_ir/supplemental/concurrency/v2": value[0]["interpretation"]}
