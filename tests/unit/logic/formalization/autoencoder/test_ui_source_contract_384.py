"""UI semantic vocabulary and explicitly limited source qualification evidence."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384 as subject
from ipfs_datasets_py.logic.ui_ux_ir.model.components import (
    PRESENTATION_CLASSIFICATION_VALUES, PRIVACY_SENSITIVITY_VALUES,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
)

SOURCE = "Present an interactive submit button."


def component(**fields):
    return {"kind": "ui_component", "document": {
        "component_id": "submit", "role": "button", "privacy_sensitivity": "none",
        "presentation_classification": "interactive", **fields}}


def document(**fields):
    source = UISourceRef(ref_id="source", source_uri="fixture://ui-instruction", source_id="authored-ui",
        source_revision="v1", content_sha256=hashlib.sha256(SOURCE.encode()).hexdigest())
    node = UIComponent(component_id="submit", role="button", source_ref_ids=("source",), **fields)
    outcome = UITerminalOutcome(outcome_id="success", kind=TerminalOutcomeKind.SUCCESS, source_ref_ids=("source",))
    return {"kind": "document", "document": UIIRDocument(document_id="authored-ui", title="Authored UI",
        sources=(source,), components=(node,), entry_components=("submit",), terminal_outcomes=(outcome,)).to_dict()}


@pytest.mark.parametrize("privacy", sorted(PRIVACY_SENSITIVITY_VALUES))
@pytest.mark.parametrize("presentation", sorted(PRESENTATION_CLASSIFICATION_VALUES))
def test_all_native_privacy_and_presentation_values_keep_projection_scope(privacy, presentation):
    for build in (component, document):
        target = build(privacy_sensitivity=privacy, presentation_classification=presentation)
        before = deepcopy(target)
        training = subject.validate_training_target(target)
        report = subject.qualify_source_candidate(SOURCE, target)
        assert target == before
        assert training["valid"] is True
        assert report["status"] == "projected_candidate"
        assert report["candidate_rewritten"] is False
        assert report["source_fidelity_check_required"] is True
        assert report["projection_scope"] == "component_identity_role_and_relationship_facts_only"
        assert {"privacy_policy", "presentation_behavior", "authorization"} <= set(report["unprojected_facets"])
        assert all(value is False for key, value in report.items() if key in subject.FALSE)
        projection = report["projections"][0]
        assert projection["family_id"] == "frame_logic"
        assert projection["facts"] == [{"predicate": "ui_component", "args": ["submit", "button"],
            "source_ref_ids": [] if build is component else ["source"]}]
        assert projection["proof_authority"] is False and projection["source_semantics_verified"] is False


@pytest.mark.parametrize("invalid", [{"privacy_sensitivity": "sensitive"},
    {"presentation_classification": "informational"}, {"privacy_sensitivity": "RESTRICTED"}])
@pytest.mark.parametrize("build", [component, document])
def test_training_and_qualification_reject_invalid_component_labels(invalid, build):
    target = build(**invalid)
    with pytest.raises(ValueError, match="closed vocabulary"):
        subject.validate_training_target(target)
    result = subject.qualify_source_candidate(SOURCE, target)
    assert result["status"] == "invalid"
    assert result["projections"] == []
    assert result["continue_planning"] is True
    assert result["proof_authority"] is False


def test_dangling_fragment_parent_remains_unqualified_missing_context():
    target = component(parent_id="absent-parent")
    assert subject.validate_training_target(target)["scope"] == "local_component_fragment"
    result = subject.qualify_source_candidate(SOURCE, target)
    assert result["status"] == "missing_context"
    assert result["projections"] == []
    assert "unknown ids" in result["reason"]
    assert result["continue_planning"] is True and result["candidate_rewritten"] is False


def test_dangling_full_document_parent_fails_native_document_validation():
    target = document(parent_id="absent-parent")
    with pytest.raises(ValueError):
        subject.validate_training_target(target)
    result = subject.qualify_source_candidate(SOURCE, target)
    assert result["status"] == "invalid"
    assert result["projections"] == []


@pytest.mark.parametrize("build", [component, document])
def test_source_mutation_changes_binding_but_never_claims_meaning_verified(build):
    target = build()
    original = subject.qualify_source_candidate(SOURCE, target)
    changed = subject.qualify_source_candidate("Remove the submit button entirely.", target)
    assert original["source_sha256"] != changed["source_sha256"]
    assert original["candidate_sha256"] == changed["candidate_sha256"]
    assert original["projections"] == changed["projections"]
    for result in (original, changed):
        assert result["source_semantics_verified"] is False
        assert result["source_fidelity_check_required"] is True
        assert result["proof_authority"] is False


def test_unknown_target_fields_cannot_disappear_during_native_lifting():
    target = component()
    target["document"]["ignored_policy"] = "must not disappear"
    with pytest.raises(ValueError, match="unknown UI component field"):
        subject.validate_training_target(target)
    result = subject.qualify_source_candidate(SOURCE, target)
    assert result["status"] == "invalid" and result["projections"] == []
