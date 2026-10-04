"""Shared source inference performs real native checks on target-free inputs."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as api
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression, ProgramIR

SECURITY_TEXT = "def assess(capacity: int, threshold: int) -> bool:\n    return capacity < threshold\n"
UI_TEXT = "The submit component is an interactive button with restricted privacy sensitivity."
AUTHORITY_FIELDS = ("proof_authority", "execution_authority", "completion_authority",
    "source_semantics_verified", "whole_program_semantics_verified", "security_specification_inferred",
    "claim_proved")


def security_candidate(operator="<"):
    return dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", "boolean",
        operand_ids=("expr:capacity", "expr:threshold"), evaluation_order=("expr:capacity", "expr:threshold"),
        operator=operator, source_ref_ids=("source",)).to_dict())


def ui_candidate(**fields):
    return dict(kind="ui_component", document={"component_id": "submit", "role": "button",
        "privacy_sensitivity": "restricted", "presentation_classification": "interactive", **fields})


def ui_document(**fields):
    from ipfs_datasets_py.logic.ui_ux_ir.schema import (
        UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
    )
    source = UISourceRef(ref_id="source", source_uri="fixture://instruction", source_id="authored",
        source_revision="v1", content_sha256=hashlib.sha256(UI_TEXT.encode()).hexdigest())
    node = UIComponent(component_id="submit", role="button", source_ref_ids=("source",), **fields)
    terminal = UITerminalOutcome(outcome_id="success", kind=TerminalOutcomeKind.SUCCESS,
                                 source_ref_ids=("source",))
    return dict(kind="document", document=UIIRDocument(document_id="ui", title="UI",
        sources=(source,), components=(node,), entry_components=("submit",),
        terminal_outcomes=(terminal,)).to_dict())


def report_for(domain="security_ir", text=SECURITY_TEXT, candidate=None, *, row_id="input-0", authority=False):
    flags = {name: authority for name in AUTHORITY_FIELDS}
    return dict(domain_id=domain, rows=[dict(id=row_id, source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        candidate_ir=security_candidate() if candidate is None else candidate,
        status="unqualified_candidate", continue_planning=True, **flags)], **flags)


def sources(text=SECURITY_TEXT, row_id="input-0"):
    return [dict(id=row_id, source_text=text)]


def test_typed_security_candidate_gets_actual_source_bound_native_program():
    report = report_for()
    before = deepcopy(report)
    result = api.qualify_source_candidates_384(report, sources())
    assert report == before and result is not report
    assert result["source_contracts_checked"] is True
    row = result["rows"][0]
    assert row["candidate_ir"] == before["rows"][0]["candidate_ir"]
    checked = row["source_contract"]
    assert checked["status"] == "qualified" and checked["qualified"]
    projection, = checked["projections"]
    assert projection["family_id"] == "program"
    native = ProgramIR.from_dict(projection["native_document"])
    assert native.sources[0].content_sha256 == row["source_sha256"]
    assert native.functions[0].return_type == "boolean"
    assert checked["source_binding"]["source_sha256"] == row["source_sha256"]
    assert row["status"] == "unqualified_candidate"
    assert all(result[key] is False and row[key] is False for key in AUTHORITY_FIELDS)


def test_mismatched_operator_fails_open_without_rewriting_the_prediction():
    predicted = security_candidate("<=")
    report = report_for(candidate=predicted)
    before = deepcopy(report)
    result = api.qualify_source_candidates_384(report, sources())
    row = result["rows"][0]
    assert row["status"] == "fail_open_source_contract_mismatch" and row["continue_planning"]
    assert row["source_contract"]["projections"] == []
    assert row["candidate_ir"] == predicted and report == before


def test_unannotated_security_source_is_not_silently_given_integer_types():
    text = SECURITY_TEXT.replace(": int", "")
    result = api.qualify_source_candidates_384(report_for(text=text), sources(text))
    row = result["rows"][0]
    assert row["status"] == "fail_open_source_contract_unsupported"
    assert row["source_contract"]["reason"] == "explicit_integer_parameter_annotations_required"
    assert row["source_contract"]["projections"] == [] and row["continue_planning"]


@pytest.mark.parametrize("change", ["hash", "source", "id", "duplicate_source_id", "duplicate_report_id", "missing"])
def test_source_identity_or_hash_drift_is_rejected(change):
    report, rows = report_for(), sources()
    if change == "hash":
        report["rows"][0]["source_sha256"] = "0" * 64
    elif change == "source":
        rows[0]["source_text"] += "# altered bytes\n"
    elif change == "id":
        rows[0]["id"] = "foreign"
    elif change == "duplicate_source_id":
        rows.append(deepcopy(rows[0]))
    elif change == "duplicate_report_id":
        report["rows"].append(deepcopy(report["rows"][0]))
    else:
        rows = []
    before = deepcopy(report)
    with pytest.raises(ValueError, match="source qualification"):
        api.qualify_source_candidates_384(report, rows)
    assert report == before


@pytest.mark.parametrize("key,value", [("target", security_candidate()), ("embedding", [0.] * 384),
    ("candidate_ir", security_candidate()), ("source_contract", {"qualified": True})])
def test_qualification_source_rows_forbid_targets_and_extra_context(key, value):
    rows = sources()
    rows[0][key] = value
    with pytest.raises(ValueError, match="closed source qualification rows"):
        api.qualify_source_candidates_384(report_for(), rows)


@pytest.mark.parametrize("builder", [ui_candidate, ui_document])
def test_ui_fragments_and_full_documents_receive_native_semantic_checks(builder):
    target = builder(privacy_sensitivity="restricted", presentation_classification="interactive")
    report = report_for("ui_ux_ir", UI_TEXT, target)
    result = api.qualify_source_candidates_384(report, sources(UI_TEXT))
    checked = result["rows"][0]["source_contract"]
    assert checked["status"] == "projected_candidate"
    assert checked["projections"][0]["family_id"] == "frame_logic"
    assert checked["projection_scope"] == "component_identity_role_and_relationship_facts_only"
    assert checked["source_fidelity_check_required"] is True
    assert not checked["source_semantics_verified"] and not checked["proof_authority"]
    assert result["rows"][0]["candidate_ir"] == target


@pytest.mark.parametrize("builder", [ui_candidate, ui_document])
def test_invalid_ui_semantic_labels_are_not_accepted_by_a_permissive_envelope(builder):
    target = builder(privacy_sensitivity="sensitive", presentation_classification="informational")
    report = report_for("ui_ux_ir", UI_TEXT, target)
    result = api.qualify_source_candidates_384(report, sources(UI_TEXT))
    row = result["rows"][0]
    assert row["status"] == "fail_open_source_contract_invalid"
    assert row["source_contract"]["projections"] == [] and row["continue_planning"]
    assert row["candidate_ir"] == target


@pytest.mark.parametrize("domain,text,target", [
    ("security_ir", SECURITY_TEXT, security_candidate()), ("ui_ux_ir", UI_TEXT, ui_candidate()),
])
def test_public_qualification_cannot_preserve_forged_authority(domain, text, target):
    report = report_for(domain, text, target, authority=True)
    result = api.qualify_source_candidates_384(report, sources(text))
    for owner in (result, result["rows"][0]):
        assert all(owner[name] is False for name in AUTHORITY_FIELDS)


@pytest.mark.parametrize("domain,text,target", [
    ("security_ir", SECURITY_TEXT, security_candidate()), ("ui_ux_ir", UI_TEXT, ui_document()),
])
def test_source_text_helper_connects_embedding_decoder_and_native_qualification(monkeypatch, domain, text, target):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    embedding = [0.125] * 384
    calls = []

    def embed(texts, **options):
        assert texts == [text] and options == {"snapshot_path": "verified-snapshot"}
        calls.append("embedding")
        return [embedding]

    def infer(rows, **options):
        assert rows == [dict(id="input-0", source_text=text, embedding=embedding)]
        assert options == {"weight_ablation": "zero_head"}
        calls.append("decoder")
        return report_for(domain, text, target)

    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    result = api.infer_source_texts_384(SimpleNamespace(infer=infer), [text],
        snapshot_path="verified-snapshot", weight_ablation="zero_head")
    assert calls == ["embedding", "decoder"]
    assert result["source_contracts_checked"] is True
    assert result["rows"][0]["source_contract"]["projections"]
    assert result["rows"][0]["candidate_ir"] == target
    if domain == "ui_ux_ir":
        assert result["rows"][0]["native_component_validated"] is True


def test_no_candidate_retains_decoder_abstention():
    report = report_for()
    report["rows"][0].update(candidate_ir=None, status="fail_open_decoder_abstained")
    result = api.qualify_source_candidates_384(report, sources())
    row = result["rows"][0]
    assert row["status"] == "fail_open_decoder_abstained" and row["candidate_ir"] is None
    assert "source_contract" not in row
