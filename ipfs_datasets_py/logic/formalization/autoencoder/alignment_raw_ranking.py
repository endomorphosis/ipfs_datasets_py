"""Rank pinned raw source views as a bounded, target-free diagnostic.

This pure standard-library helper performs cosine arithmetic. It reads no
files, fits no model and gives no semantic, split, production or proof authority.
Subprocess limits and durable publication belong to the separate file workflow.
"""
from __future__ import annotations

import json
import math

from . import alignment_lane_bundle as lanes
from . import alignment_stage_declarations as stages

SCHEMA = "alignment-raw-source-ranking-diagnostic/v1"
METRIC = "cosine_hypot_fsum_unit_operands_float64/v1"
RAW_STAGES = {"historical_linguistic_features", "raw_embedding"}
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "source_semantics_verified",
                      "proof_authority", "semantic_label_admission", "production_ranking_authorized",
                      "derivative_provenance_exclusion_verified", "split_provenance_authenticated",
                      "reviewer_identity_authenticated", "independent_semantic_review_completed",
                      "runtime_computation_proven", "producer_identity_authenticated", "file_bindings_verified",
                      "reference_durability_verified", "query_reference_accessed", "training_executed",
                      "scoring_executed", "model_executed", "target_access", "checkpoint_loaded",
                      "subprocess_execution_attested", "formal_vector_bank_verified",
                      "projection_checkpoint_contents_verified"), False)


def _seal(value):
    value["content_sha256"] = lanes._digest(value)
    return value


def _cosine(query, query_norm, candidate, candidate_norm):
    """Normalize only metric operands; never change retained producer vectors."""
    lanes._require(len(query) == len(candidate), "raw cosine dimensions differ")
    score = math.fsum((left / query_norm) * (right / candidate_norm)
                      for left, right in zip(query, candidate, strict=True))
    lanes._require(math.isfinite(score), "raw cosine arithmetic must remain finite")
    return score


def _norm(vector):
    value = math.hypot(*vector)
    lanes._require(math.isfinite(value) and value > 0, "available raw vector requires a finite positive norm")
    return value


def rank_raw_source_bundles(declaration, query_bundle, bank_bundle, *, expected_bindings,
                           expected_query_lane, expected_bank_lane):
    """Compute raw source-to-source rankings from independently pinned bundles.

    Both full input identity and row IDs must be disjoint across cohorts. Exact
    source strings or encoder texts alone do not establish context identity or
    derivative provenance. Every unavailable/zero-ablation query stays visible.
    """
    stage_validation = stages.validate_rank_declaration(declaration, expected_bindings=expected_bindings)
    query_lane = lanes.validate_lane_bundle(query_bundle, expected_bindings=expected_query_lane)
    bank_lane = lanes.validate_lane_bundle(bank_bundle, expected_bindings=expected_bank_lane)
    lanes._require(lanes._raw(query_lane) == lanes._raw(declaration["lane_validation"]),
                   "query bundle differs from declared lane receipt")
    lanes._require(lanes._raw(bank_lane) == lanes._raw(declaration["frozen_bank"]["lane_validation"]),
                   "bank bundle differs from declared lane receipt")
    policy = declaration["ranking_policy"]
    lanes._require(policy["mode"] == "raw_source_to_source" and declaration["checkpoint_binding"] is None,
                   "only checkpoint-free raw source-to-source diagnostics are implemented")
    lanes._require(query_lane["stage"] in RAW_STAGES and bank_lane["stage"] in RAW_STAGES
                   and query_lane["lane_id"] != "leanstral" and bank_lane["lane_id"] != "leanstral",
                   "learned/final-hidden views are outside this raw diagnostic")
    queries, candidates = query_bundle["rows"], bank_bundle["rows"]
    lanes._require({row["id"] for row in queries}.isdisjoint({row["id"] for row in candidates}),
                   "query and TRAIN bank IDs overlap")
    lanes._require({row["input_sha256"] for row in queries}.isdisjoint(
        {row["input_sha256"] for row in candidates}), "query and TRAIN bank exact input identities overlap")
    eligible = [(row["id"], row["vector"], _norm(row["vector"]))
                for row in candidates if row["status"] == "available"]
    rows, comparisons = [], 0
    for query in queries:
        result = {"id": query["id"], "input_sha256": query["input_sha256"],
                  "status": "unavailable", "reason": None, "hits": []}
        if query["status"] != "available":
            result["reason"] = "query_representation_" + query["status"]
        elif not eligible:
            result["reason"] = "no_available_train_candidates"
        else:
            query_norm = _norm(query["vector"])
            hits = [{"candidate_id": identity,
                     "score": _cosine(query["vector"], query_norm, vector, norm)}
                    for identity, vector, norm in eligible]
            comparisons += len(hits)
            hits.sort(key=lambda hit: (-hit["score"], hit["candidate_id"]))
            result.update(status="available", reason=None, hits=hits[:policy["top_k"]])
        rows.append(result)
    saved = _seal({"schema": "alignment-saved-ranking-bindings/v1", "rows": rows,
                   "rank_declaration": declaration, "frozen_bank_sha256": lanes._digest(declaration["frozen_bank"]),
                   "query_manifest_sha256": lanes._digest(declaration["queries"]), "ranking_policy": policy,
                   "checkpoint_binding_sha256": lanes._digest(None), "file_binding": None})
    stages._bounded(saved)
    diagnostic = _seal({"schema": SCHEMA, "status": "completed_raw_source_ranking_diagnostic",
                        "execution_scope": "pure_stdlib_cosine_arithmetic_not_production_or_fidelity_scoring",
                        "declaration_sha256": lanes._digest(declaration),
                        "stage_validation_sha256": lanes._digest(stage_validation),
                        "query_bundle_sha256": lanes._digest(query_bundle), "bank_bundle_sha256": lanes._digest(bank_bundle),
                        "query_lane_validation_sha256": lanes._digest(query_lane),
                        "bank_lane_validation_sha256": lanes._digest(bank_lane),
                        "saved_rankings_sha256": lanes._digest(saved),
                        "profile_sha256": query_lane["profile_sha256"], "lane_id": query_lane["lane_id"],
                        "stage": query_lane["stage"], "dimension": query_lane["dimension"],
                        "query_count": len(queries), "available_query_count": query_lane["available_count"],
                        "unavailable_query_count": query_lane["unavailable_count"],
                        "zero_ablation_query_count": query_lane["zero_ablation_count"],
                        "bank_row_count": len(candidates), "eligible_candidate_count": len(eligible),
                        "unavailable_candidate_count": bank_lane["unavailable_count"],
                        "zero_ablation_candidate_count": bank_lane["zero_ablation_count"],
                        "ranked_query_count": sum(row["status"] == "available" for row in rows),
                        "unavailable_ranking_count": sum(row["status"] == "unavailable" for row in rows),
                        "similarity_evaluation_count": comparisons,
                        "returned_hit_count": sum(len(row["hits"]) for row in rows),
                        "ranking_operation_executed": True, "cosine_computation_executed": comparisons > 0,
                        "metric": METRIC, "tie_break": stages.TIE_BREAK, "vector_values_modified": False,
                        "exact_id_disjointness_verified": True, "exact_full_input_disjointness_verified": True,
                        "bank_split_declarations_checked": True,
                        "verification_status": "pending", "admission_status": "pending",
                        "masks": dict.fromkeys(lanes.MASKS, 0), "optimizer_updates": 0,
                        "model_calls": 0, "encoder_calls": 0, "decoder_calls": 0, "prover_calls": 0,
                        "checkpoint_loads": 0, "fidelity_scored_query_count": 0, **FALSE})
    stages._bounded(diagnostic)
    # Detach the embedded declaration, policy and returned rows from callers.
    return json.loads(lanes._raw({"saved_rankings": saved, "diagnostic_receipt": diagnostic}))


__all__ = ["rank_raw_source_bundles"]
