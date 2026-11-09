"""Tests for LegalIR semantic-equivalence promotion metrics."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    COUNTEREXAMPLE_EQUIVALENCE,
    DECOMPILER_ROUND_TRIP_PRESERVATION,
    GRAPH_ISOMORPHISM,
    LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION,
    OBLIGATION_EQUIVALENCE,
    PROOF_OBLIGATION_DELTA,
    PROOF_OBLIGATION_DELTA_SCORE,
    SEMANTIC_EQUIVALENCE_METRICS,
    STRUCTURAL_EQUIVALENCE,
    TEMPORAL_WINDOW_AGREEMENT,
    SemanticEquivalenceConfig,
    compare_legal_ir_semantic_equivalence,
    evaluate_legal_ir_semantic_equivalence,
    semantic_equivalence_from_metrics,
    semantic_equivalence_promotion_gate,
)


def _reference_ir() -> dict:
    return {
        "rules": [
            {
                "id": "rule-a",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "n1", "label": "Agency", "type": "actor"},
                {"id": "n2", "label": "Notice", "type": "document"},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _isomorphic_ir() -> dict:
    return {
        "rules": [
            {
                "id": "renumbered",
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "condition": "within 30 days",
                "proof_obligation_ids": ["po-notice"],
                "temporal_window": {"start": "2026-01-01", "duration": "30 days"},
            }
        ],
        "graph": {
            "nodes": [
                {"id": "x", "label": "Notice", "type": "document"},
                {"id": "y", "label": "Agency", "type": "actor"},
            ],
            "edges": [
                {"source": "y", "target": "x", "label": "must_provide"},
            ],
        },
        "counterexamples": [{"assignment": {"notice": False}, "violates": "po-notice"}],
        "round_trip": {
            "decompiled": "O(agency, provide_notice)",
            "recompiled_ir": "O(agency, provide_notice)",
        },
    }


def _regressed_ir() -> dict:
    changed = _isomorphic_ir()
    changed["rules"][0].update(
        {
            "modality": "permission",
            "condition": "within 60 days",
            "proof_obligation_ids": ["po-permit"],
            "temporal_window": {"start": "2026-01-01", "duration": "60 days"},
        }
    )
    changed["graph"]["edges"][0]["label"] = "may_provide"
    changed["counterexamples"] = [{"assignment": {"notice": True}, "violates": "po-permit"}]
    changed["round_trip"]["recompiled_ir"] = "P(agency, provide_notice)"
    return changed


def _all_semantic_scores(score: float = 1.0) -> dict[str, float]:
    values = {metric: score for metric in SEMANTIC_EQUIVALENCE_METRICS}
    values[PROOF_OBLIGATION_DELTA] = 0.0 if score == 1.0 else 1.0
    return values


def test_raw_ir_pair_scores_semantic_equivalence_beyond_ids_and_order() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _isomorphic_ir(),
        family="deontic",
    )

    assert result.complete is True
    assert result.scores[STRUCTURAL_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[OBLIGATION_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] == pytest.approx(1.0)
    assert result.scores[GRAPH_ISOMORPHISM] == pytest.approx(1.0)
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] == pytest.approx(1.0)
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] == pytest.approx(1.0)
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(1.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(0.0)


def test_semantic_metrics_detect_obligation_graph_temporal_and_proof_delta() -> None:
    result = evaluate_legal_ir_semantic_equivalence(
        _reference_ir(),
        _regressed_ir(),
        family="deontic",
    )

    assert result.scores[OBLIGATION_EQUIVALENCE] < 1.0
    assert result.scores[COUNTEREXAMPLE_EQUIVALENCE] < 1.0
    assert result.scores[GRAPH_ISOMORPHISM] < 1.0
    assert result.scores[TEMPORAL_WINDOW_AGREEMENT] < 1.0
    assert result.scores[DECOMPILER_ROUND_TRIP_PRESERVATION] < 1.0
    assert result.scores[PROOF_OBLIGATION_DELTA_SCORE] == pytest.approx(0.0)
    assert result.raw_deltas[PROOF_OBLIGATION_DELTA] == pytest.approx(2.0)


def test_explicit_metric_payload_accepts_delta_alias_and_fails_closed_on_missing() -> None:
    complete = semantic_equivalence_from_metrics(
        {
            **_all_semantic_scores(),
            "proof_obligation_delta_count": 0,
        },
        family="kg",
    )
    incomplete = semantic_equivalence_from_metrics(
        {
            STRUCTURAL_EQUIVALENCE: 1.0,
            OBLIGATION_EQUIVALENCE: 1.0,
        },
        family="kg",
    )

    assert complete.family == "knowledge_graphs"
    assert complete.missing_metrics == ()
    assert incomplete.missing_metrics == (
        COUNTEREXAMPLE_EQUIVALENCE,
        GRAPH_ISOMORPHISM,
        TEMPORAL_WINDOW_AGREEMENT,
        DECOMPILER_ROUND_TRIP_PRESERVATION,
        PROOF_OBLIGATION_DELTA_SCORE,
    )


def test_comparison_reports_disagreement_when_ce_cosine_improve_but_semantics_regress() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
                "ir_cross_entropy_loss": 0.85,
                "ir_cosine_similarity": 0.68,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                **_all_semantic_scores(),
                OBLIGATION_EQUIVALENCE: 0.50,
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
                "ir_cross_entropy_loss": 0.35,
                "ir_cosine_similarity": 0.88,
            }
        }
    }

    report = compare_legal_ir_semantic_equivalence(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )
    payload = report.to_dict()

    assert report.accepted is False
    assert report.schema_version == LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION
    assert report.disagreements == ("deontic:ce_cosine_improved_semantic_equivalence_regressed",)
    assert "deontic:ce_cosine_semantic_disagreement" in report.block_reasons
    assert payload["family_results"]["deontic"]["disagreement"] is True


def test_raw_family_payload_can_drive_hard_promotion_gate() -> None:
    baseline = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _isomorphic_ir(),
                "autoencoder_cross_entropy_loss": 0.80,
                "autoencoder_cosine_similarity": 0.70,
            }
        }
    }
    candidate = {
        "view_family_metrics": {
            "deontic": {
                "reference_ir": _reference_ir(),
                "candidate_ir": _regressed_ir(),
                "autoencoder_cross_entropy_loss": 0.30,
                "autoencoder_cosine_similarity": 0.90,
            }
        }
    }

    gate = semantic_equivalence_promotion_gate(
        baseline,
        candidate,
        config=SemanticEquivalenceConfig(families=("deontic",)),
    )

    assert gate["accepted"] is False
    assert gate["hard_promotion_gate"] is True
    assert gate["failed_families"] == ["deontic"]
    assert "deontic:semantic_equivalence_regressed" in gate["block_reasons"]


# Additive exact-payload diagnostics; no model, prover or runtime is invoked.
from copy import deepcopy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    evaluate_complete_norm_payloads,
)


def _complete_norm_payload_fixture():
    return {"profile": "fictional-payload/v1", "typed_expression": {"root": {"kind": "forall",
        "binders": [{"name": "actor", "sort": "person"}], "arguments": [{"kind": "obligation",
        "predicate": "file", "arguments": ["agency", "report"], "exception": "emergency",
        "cardinality": 1, "time": "30days"}]}}, "argument_roles": [{"symbol": "file", "roles": ["actor", "object"]}],
        "assumptions": [], "governing_context": {"jurisdiction": "fictional", "instrument_id": "act",
        "governing_edition": "v1", "legal_as_of_utc": "2026-01-01", "valid_from_utc": "2025-01-01", "valid_until_utc": "2027-01-01"},
        "interpretation_id": "fixture:one", "source_binding": {"source_version_cid": "source-one",
        "occurrence_cid": "span-one", "document_revision": "v1"}, "definition_uses": [{"definition_unit_id": "definition",
        "defined_predicate": "file", "use_unit_id": "norm", "use_occurrence_cid": "span-one", "target_typed_paths": ["/root/arguments/0"],
        "applicability": "governing", "interpretation_id": "fixture:one", "evidence_refs": []}],
        "cross_references": [{"from_unit_id": "norm", "dependency_artifact_id": "external-one",
        "dependency_sha256": "a" * 64, "version": "v1", "evidence_refs": []}]}


def _complete_norm_case(candidate=None, *, outcome="complete", case_id="case-one"):
    target = _complete_norm_payload_fixture()
    return {"case_id": case_id, "reference": target,
            "candidate": deepcopy(target) if candidate is None else candidate, "outcome": outcome}


def test_complete_norm_payload_exact_positive_has_only_payload_comparison_authority():
    report = evaluate_complete_norm_payloads([_complete_norm_case()])
    assert report["denominator"] == 1
    assert all(value == 1 for value in report["metric_numerators"].values())
    assert report["scope"] == "exact_structural_and_local_facet_payload_comparison_only"
    assert all(report[key] is False for key in ("producer_authenticity_verified", "reference_authenticity_verified",
        "syntax_or_logic_family_validity_verified", "semantic_equivalence_proved", "governing_definition_meaning_verified",
        "source_fidelity_proved", "legal_admission_or_proof_authority"))


@pytest.mark.parametrize("change", ["actor", "role_order", "argument_order", "binder", "quantifier", "modality",
                                   "exception", "cardinality", "time", "assumption", "definition_path", "definition_applicability"])
def test_complete_norm_payload_preserves_ordered_structure_and_local_facets(change):
    candidate = _complete_norm_payload_fixture()
    root = candidate["typed_expression"]["root"]
    node = root["arguments"][0]
    if change == "actor": node["arguments"][0] = "court"
    elif change == "role_order": candidate["argument_roles"][0]["roles"].reverse()
    elif change == "argument_order": node["arguments"].reverse()
    elif change == "binder": root["binders"][0]["sort"] = "organization"
    elif change == "quantifier": root["kind"] = "exists"
    elif change == "modality": node["kind"] = "permission"
    elif change == "exception": node["exception"] = "different-exception"
    elif change == "cardinality": node["cardinality"] = 2
    elif change == "time": node["time"] = "60days"
    elif change == "assumption": candidate["assumptions"] = ["new premise"]
    elif change == "definition_path": candidate["definition_uses"][0]["target_typed_paths"] = ["/other"]
    else: candidate["definition_uses"][0]["applicability"] = "non-governing"
    scores = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])["cases"][0]["scores"]
    assert scores["local_structural_payload_exact"] == scores["full_nine_payload_exact"] == 0
    assert scores["interpretation_identity_exact"] == scores["source_binding_exact"] == 1


@pytest.mark.parametrize("change", ["interpretation", "definition_id", "xref_id", "xref_version", "source", "context"])
def test_complete_norm_payload_separates_custody_source_context_from_local_structure(change):
    candidate = _complete_norm_payload_fixture()
    if change == "interpretation": candidate["interpretation_id"] = "fixture:two"
    elif change == "definition_id": candidate["definition_uses"][0]["definition_unit_id"] = "other-definition"
    elif change == "xref_id": candidate["cross_references"][0]["dependency_artifact_id"] = "other-external"
    elif change == "xref_version": candidate["cross_references"][0]["version"] = "v2"
    elif change == "source": candidate["source_binding"]["source_version_cid"] = "other-source"
    else: candidate["governing_context"]["governing_edition"] = "v2"
    scores = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])["cases"][0]["scores"]
    assert scores["local_structural_payload_exact"] == 1
    assert scores["full_nine_payload_exact"] == 0


def test_complete_norm_payload_retains_every_noncomplete_outcome_in_denominator():
    rows = [_complete_norm_case()]
    for outcome in ("incomplete", "abstained", "unsupported", "invalid", "error"):
        rows.append(_complete_norm_case(outcome=outcome, case_id=outcome))
    malformed = _complete_norm_case(case_id="missing-field")
    malformed["candidate"].pop("typed_expression")
    rows.append(malformed)
    report = evaluate_complete_norm_payloads(rows)
    assert report["denominator"] == 7
    assert report["outcome_counts"] == {"complete": 2, "incomplete": 1, "abstained": 1, "unsupported": 1, "invalid": 1, "error": 1}
    assert report["metric_numerators"]["full_nine_payload_exact"] == 1
    assert report["metric_denominators"]["full_nine_payload_exact"] == 7
    assert report["rates"]["full_nine_payload_exact"] == pytest.approx(1/7)
    assert all(sum(row["scores"].values()) == 0 for row in report["cases"][1:])


@pytest.mark.parametrize("fault", ["duplicate_ids", "bad_reference", "extra_reference", "nonfinite", "nonstring_key", "nested_tuple", "extra_example", "bad_source", "bad_context", "bad_definition", "bad_xref", "bad_root"])
def test_complete_norm_payload_refuses_invalid_reference_or_nonlossless_evaluation(fault):
    rows = [_complete_norm_case()]
    if fault == "duplicate_ids": rows.append(deepcopy(rows[0]))
    elif fault == "bad_reference": rows[0]["reference"]["argument_roles"] = "not a list"
    elif fault == "extra_reference": rows[0]["reference"]["hidden"] = "not silently ignored"
    elif fault == "nonfinite": rows[0]["candidate"]["typed_expression"]["root"]["value"] = float("nan")
    elif fault == "nonstring_key": rows[0]["candidate"]["typed_expression"][1] = "not coerced"
    elif fault == "nested_tuple": rows[0]["reference"]["assumptions"] = ("not silently converted",)
    elif fault == "bad_source": rows[0]["reference"]["source_binding"]["source_version_cid"] = 7
    elif fault == "bad_context": rows[0]["reference"]["governing_context"]["governing_edition"] = []
    elif fault == "bad_definition": rows[0]["reference"]["definition_uses"][0]["defined_predicate"] = None
    elif fault == "bad_xref": rows[0]["reference"]["cross_references"][0]["evidence_refs"] = ["not a reference"]
    elif fault == "bad_root": rows[0]["reference"]["typed_expression"]["root"] = {}
    else: rows[0]["hidden"] = "not accepted"
    with pytest.raises(ValueError): evaluate_complete_norm_payloads(rows)


@pytest.mark.parametrize("value", [True, 1.0])
def test_complete_norm_payload_does_not_round_or_coerce_bool_numeric_identity(value):
    candidate = _complete_norm_payload_fixture()
    candidate["typed_expression"]["root"]["arguments"][0]["cardinality"] = value
    report = evaluate_complete_norm_payloads([_complete_norm_case(candidate)])
    assert report["metric_numerators"]["typed_expression_exact"] == 0


def test_complete_norm_payload_snapshot_does_not_return_reference_or_prediction_labels():
    row = _complete_norm_case()
    report = evaluate_complete_norm_payloads([row])
    row["candidate"]["typed_expression"]["root"]["kind"] = "changed later"
    assert report["metric_numerators"]["full_nine_payload_exact"] == 1
    assert all("reference" not in case and "candidate" not in case for case in report["cases"])



def test_complete_norm_payload_absent_candidate_keeps_original_denominator():
    row = _complete_norm_case()
    row["candidate"] = None
    report = evaluate_complete_norm_payloads([row])
    assert report["denominator"] == report["malformed_complete_candidate_count"] == 1
    assert all(value == 0 for value in report["metric_numerators"].values())
