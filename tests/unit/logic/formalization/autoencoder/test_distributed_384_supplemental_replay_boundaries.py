"""Adversarial boundary checks: lowering helpers are not replay evidence."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
from ipfs_datasets_py.logic.formalization.autoencoder import native_supplemental_lean as routes
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import candidate_native_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters import UnsupportedNativeLean
from .test_distributed_384_supplemental_native_lake import prepared


@pytest.fixture(scope="module")
def candidate_preparation():
    return prepared()


def rehash(report):
    """Recompute superficial checksums; exact source regeneration must still win."""
    for row in report["projections"]:
        row["target_sha256"] = core._sha({key: value for key, value in row.items() if key != "target_sha256"})
    report["report_sha256"] = core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    return report


@pytest.mark.parametrize("domain", ["intent_ir", "legal_ir", "ui_ux_ir", "unknown_ir"])
def test_security_projection_cannot_be_routed_as_a_different_domain(candidate_preparation, domain):
    for row in candidate_preparation.native_report["projections"]:
        assert not routes.recognizes(row, domain)
        with pytest.raises(UnsupportedNativeLean, match="known_native_supplemental"):
            routes.emit_projection(row, domain=domain)


@pytest.mark.parametrize("kind", ["concurrency", "protocol", "refinement"])
def test_security_only_model_cannot_be_admitted_by_relabeling_intent_prefix(candidate_preparation, kind):
    row = next(row for row in candidate_preparation.native_report["projections"]
               if row["projection_id"] == "security_ir/supplemental/" + kind + "/v2")
    row["projection_id"] = "intent_ir/supplemental/" + kind + "/v2"
    with pytest.raises(UnsupportedNativeLean, match="known_native_supplemental"):
        routes.emit_projection(row, domain="intent_ir")


@pytest.mark.parametrize("part", ["bridge", "typed_expression"])
def test_rehashed_bridge_spoof_is_rejected_by_enclosing_exact_report_replay(candidate_preparation, part):
    report = candidate_preparation.native_report
    row = report["projections"][0]
    row["payload"][part] = {"fabricated": True, "source_semantics_verified": True}
    rehash(report)
    # The pure lowering helper intentionally consumes only a canonical native
    # document. Successful code emission is not a claim about bridge evidence.
    _, details = routes.emit_projection(row, domain="security_ir")
    assert not details["source_semantics_verified"] and not details["capability_floor_eligible"]
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=candidate_preparation.source_inputs,
            source_text=candidate_preparation.source_text, candidate=candidate_preparation.candidate)


def test_rehashed_success_flag_cannot_promote_a_report(candidate_preparation):
    report = candidate_preparation.native_report
    report["source_semantics_verified"] = True
    rehash(report)
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=candidate_preparation.source_inputs,
            source_text=candidate_preparation.source_text, candidate=candidate_preparation.candidate)


@pytest.mark.parametrize("unissued", [{"status": "passed", "backend_executed": True}, gate.CandidateNativeLakeExecution()])
def test_serialized_or_fabricated_receipt_is_never_live_backend_evidence(candidate_preparation, unissued):
    with pytest.raises(ValueError, match="live issued"):
        gate.verify_native_family_lake(unissued, candidate_preparation.native_report,
            source_inputs=candidate_preparation.source_inputs,
            source_text=candidate_preparation.source_text, candidate=candidate_preparation.candidate)


def test_manual_supplemental_models_are_reported_as_context_not_learned_outputs(candidate_preparation):
    report = candidate_preparation.report
    assert report["context_declaration_count"] == 4
    assert report["evidence_scope"] == "unchanged_decoded_candidate_plus_explicit_caller_declarations"
    assert report["declaration_scope"] == "source_binding_is_identity_not_source_semantic_fidelity"
    assert report["native_check_scope"] == "syntax_and_types_only"
    for flag in ("context_inferred_by_model", "source_semantics_verified", "complete_target_semantics",
                 "target_rewritten", "qualified", "admitted", "proof_authority", "promotion_performed"):
        assert report[flag] is False
    for family in report["families"]:
        assert family["coverage_scope"] == "declared_native_views_only"
        assert not family["complete_target_semantics"]
        for lowering in family["native_lowering"]:
            assert not lowering["qualified"] and not lowering["proof_authority"]
            assert not lowering["lowering"]["source_meaning_inferred"]
            assert not lowering["lowering"]["capability_floor_eligible"]


def test_mutating_detached_report_does_not_rewrite_the_registered_candidate(candidate_preparation):
    first = candidate_preparation.report
    saved = deepcopy(first)
    first["native_report"]["projections"][0]["payload"]["native_document"]["facts"] = []
    assert candidate_preparation.report == saved
