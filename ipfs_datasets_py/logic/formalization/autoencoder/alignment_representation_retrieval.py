"""Reference-free cosine ranking of named checkpoint endpoints, then scoring.

Representation widths are independent of native source width. Author-created
development labels enter only the posthoc scorer. The branch activation is a
residual control, rather than a standalone compressed autoencoder state.
"""
from __future__ import annotations

import math

from .alignment_baseline import _digest, _raw
from .alignment_checkpoint_representations import ENDPOINTS, validate_source384_representations
from .alignment_richer_embeddings import prepare_richer_embedding_inputs
from .alignment_richer_panel import validate_alignment_richer_panel
from .alignment_richer_retrieval import FACET_WEIGHTS, _coverage, _facet_matches, _target, _unit

RANK_SCHEMA = "alignment-checkpoint-representation-rankings/v1"
SCORE_SCHEMA = "alignment-checkpoint-representation-authored-scores/v1"
FALSE = dict.fromkeys(("qualified", "proof_authority", "source_fidelity_established",
    "context_resolution_executed", "independent_fidelity_available", "training_executed",
    "source_encoder_executed", "model_inference_executed"), False)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _seal(value):
    value["payload_sha256"] = _digest(value)
    return value


def _metadata(panel, inputs):
    validate_alignment_richer_panel(panel)
    _require(_raw(inputs) == _raw(prepare_richer_embedding_inputs(panel)), "saved inputs differ from source/context panel")
    return {"sha256:" + row["input_sha256"]: row for row in panel["rows"]}


def _source_selection(metadata):
    # Targets, expectations, row kind and semantic reference hashes are absent.
    return [{key: row[key] for key in ("group_id", "split", "domain_id", "logic_family",
            "source_sha256", "input_sha256")} | {"id": identity, "context_role": row["context"]["role"]}
            for identity, row in sorted(metadata.items())]


def _rank(query, candidates, width):
    if query is None or any(vector is None for vector in candidates.values()):
        return {"status": "unavailable", "reason": "missing_representation", "ranked": [], "full_pool_ranking": []}
    query_unit = _unit(query, width=width, allow_zero=True)
    candidate_units = {key: _unit(vector, width=width, allow_zero=True) for key, vector in candidates.items()}
    if query_unit is None or any(vector is None for vector in candidate_units.values()):
        return {"status": "unavailable", "reason": "zero_direction_in_query_or_fixed_pool", "ranked": [], "full_pool_ranking": []}
    full = [{"candidate_id": key, "cosine_similarity": max(-1., min(1., math.fsum(
        a * b for a, b in zip(query_unit, vector, strict=True))))} for key, vector in candidate_units.items()]
    full.sort(key=lambda row: (-row["cosine_similarity"], row["candidate_id"]))
    return {"status": "available", "reason": None, "ranked": full[:5], "full_pool_ranking": full}


def rank_checkpoint_representations(panel, raw_inputs, representation_result):
    """Rank exactly 16 TRAIN sources; no query references enter similarities."""
    metadata = _metadata(panel, raw_inputs)
    validate_source384_representations(representation_result, raw_inputs)
    selection = _source_selection(metadata)
    candidate_ids = sorted(key for key, row in metadata.items() if row["split"] == "train")
    query_ids = sorted(set(metadata) - set(candidate_ids))
    _require(len(candidate_ids) == 16 and len(query_ids) == 18, "fixed authored split accounting differs")
    _require(not {metadata[key]["group_id"] for key in candidate_ids}
             & {metadata[key]["group_id"] for key in query_ids}, "query source group leaks into TRAIN pool")
    widths = {"raw_source_384": 384, **ENDPOINTS}
    vectors = {arm: {} for arm in widths}
    for receipt in representation_result["raw_lane"]["receipts"]:
        vectors["raw_source_384"][receipt["id"]] = receipt["embedding"]
    for receipt in representation_result["rows"]:
        for arm, endpoint in receipt["endpoints"].items():
            vectors[arm][receipt["id"]] = endpoint["values"]
    arms = {}
    for arm, width in widths.items():
        pool = {key: vectors[arm].get(key) for key in candidate_ids}
        records = [{"id": key, "input_sha256": metadata[key]["input_sha256"],
            "query_vector_sha256": _digest(vectors[arm][key]) if key in vectors[arm] else None,
            **_rank(vectors[arm].get(key), pool, width)} for key in query_ids]
        arms[arm] = {"dimension": width, "native_input_dimension": 384,
            "candidate_vector_sha256s": {key: _digest(v) if v is not None else None for key, v in pool.items()}, "rows": records}
    return _seal({"schema": RANK_SCHEMA, "representation_result_sha256": representation_result["payload_sha256"],
        "source_selection": selection, "source_selection_sha256": _digest(selection),
        "candidate_ids": candidate_ids, "query_count": 18, "top_k": 5,
        "recipe": "cosine_of_each_declared_endpoint; descending_cosine_then_lexicographic_input_id",
        "arms": arms, "query_reference_consumed": False, "reference_targets_in_candidate_features": False, **FALSE})


def validate_checkpoint_rankings(rankings, panel, raw_inputs, representation_result):
    expected = rank_checkpoint_representations(panel, raw_inputs, representation_result)
    _require(_raw(rankings) == _raw(expected), "rankings differ from source-only vector recomputation")
    return {"status": "validated_integrity_and_numeric_ranking", "payload_sha256": rankings["payload_sha256"], **FALSE}


def _score(policy, reference, targets):
    reference = _target(reference)["canonical_ir"]
    facets = {key: _facet_matches(target, reference) for key, target in targets.items()}
    gains = {key: math.fsum(FACET_WEIGHTS[facet] * fraction for facet, fraction in values.items())
             / math.fsum(FACET_WEIGHTS.values()) for key, values in facets.items()}
    def dcg(values):
        return math.fsum(v / math.log2(i + 2) for i, v in enumerate(values))
    ideal = dcg(sorted(gains.values(), reverse=True)[:5])
    counterpart = sorted(key for key, target in targets.items() if target == reference)
    pool = _coverage(list(targets.values()), reference)
    result = {"reference_sha256": _digest(reference), "pool_coverage_ceiling": pool,
              "reference_target_present_in_pool": bool(counterpart), "status": policy["status"],
              "reason": policy["reason"], "authored_metrics": None}
    if policy["status"] == "available":
        ids = [r["candidate_id"] for r in policy["ranked"]]
        result["authored_metrics"] = {"graded_facet_ndcg": dcg([gains[key] for key in ids]) / ideal if ideal else None,
            "ranked_facet_matches": [{"candidate_id": key, "facets": facets[key], "weighted_fraction": gains[key]} for key in ids],
            "selected_coverage": _coverage([targets[key] for key in ids], reference),
            "exact_ir_counterpart_recall": {"available": bool(counterpart),
                "value": float(bool(set(ids) & set(counterpart))) if counterpart else None,
                "reason": None if counterpart else "no_reference_target_in_training_pool"}}
    return result


def score_checkpoint_representations(panel, rankings, raw_inputs, representation_result):
    """Read authored targets after exact ranking replay; no new weights or calls."""
    validate_checkpoint_rankings(rankings, panel, raw_inputs, representation_result)
    metadata = _metadata(panel, raw_inputs)
    targets = {key: metadata[key]["target"] for key in rankings["candidate_ids"]}
    arms = {}
    for arm, records in rankings["arms"].items():
        positive, negative, contextual = [], [], []
        for row in records["rows"]:
            item = metadata[row["id"]]
            if item["context"]["role"] != "none_required":
                contextual.append({"id": row["id"], "status": "interpretation_unavailable_context_withheld",
                                   "semantic_score": None, "ranking_status": row["status"]})
            elif item["row_kind"] == "positive":
                positive.append({"id": row["id"], "score": _score(row, item["target"], targets)})
            else:
                negative.append({"id": row["id"], "row_kind": item["row_kind"],
                    "status": "diagnostic_ranking_only", "semantic_score": None, "ranking_status": row["status"]})
        _require(len(positive) == 8 and len(negative) == 8 and len(contextual) == 2, "fixed scoring scope differs")
        available = [r["score"]["authored_metrics"] for r in positive if r["score"]["status"] == "available"]
        ndcgs = [r["graded_facet_ndcg"] for r in available if r["graded_facet_ndcg"] is not None]
        coverage = {}
        for facet in ("conditions", "exceptions", "temporal"):
            values = [r["selected_coverage"]["unscoped_qualifier_identity"][facet] for r in available]
            recalls = [r["reference_identity_recall"] for r in values if r["reference_identity_recall"] is not None]
            required = sum(r["reference_atoms"] for r in values)
            coverage[facet] = {"mean_identity_recall": math.fsum(recalls) / len(recalls) if recalls else None,
                "occurrence_weighted_identity_recall": sum(len(r["matched_atoms"]) for r in values) / required if required else None}
        arms[arm] = {"dimension": records["dimension"], "positive_rows": positive,
            "negative_diagnostic_rows": negative, "context_diagnostic_rows": contextual,
            "summary": {"eligible_positive_queries": 8, "available_score_count": len(available),
                "mean_graded_facet_ndcg": math.fsum(ndcgs) / len(ndcgs) if ndcgs else None,
                "unscoped_qualifier_coverage": coverage}}
    return _seal({"schema": SCORE_SCHEMA, "ranking_sha256": rankings["payload_sha256"],
        "evaluation_role": "exposed_development", "reference_origin": "synthetic_authored_unreviewed",
        "facet_weights": dict(FACET_WEIGHTS), "facet_match_recipe": "typed_facet_multiset_jaccard; empty_empty_equals_one",
        "dcg_recipe": "linear_weighted_facet_fraction_over_log2_rank_plus_one; ideal_same_full_training_pool",
        "arms": arms, "semantic_equivalence_checked": False,
        "negative_abstention_or_context_resolution_established": False, **FALSE})


def assay_residual_projection(inputs, representation_result):
    """Input-vector preservation is distinct from authored retrieval relevance."""
    validate_source384_representations(representation_result, inputs)
    raw = {row["id"]: row["embedding"] for row in representation_result["raw_lane"]["receipts"]}
    transform = representation_result["plan"]["teacher_binding"]["input_transform"]
    records = []
    for row in representation_result["rows"]:
        before = raw[row["id"]]
        after = [v * transform["scale"] + mean for v, mean in zip(
            row["endpoints"]["residual_projection_384"]["values"], transform["mean"], strict=True)]
        delta = [a - b for a, b in zip(after, before, strict=True)]
        unit_a, unit_b = _unit(before, width=384, allow_zero=True), _unit(after, width=384, allow_zero=True)
        cosine = max(-1., min(1., math.fsum(a * b for a, b in zip(unit_a, unit_b, strict=True)))) if unit_a and unit_b else None
        records.append({"id": row["id"], "input_embedding_sha256": row["input_embedding_sha256"],
            "input_norm": math.hypot(*before), "reconstructed_norm": math.hypot(*after),
            "reconstructed_values_sha256": _digest(after), "correction_l2": math.hypot(*delta),
            "coordinate_mse": math.fsum(v * v for v in delta) / 384,
            "unit_cosine_similarity": cosine, "raw_identity_baseline_mse": 0.0})
    return _seal({"schema": "alignment-residual-projection-numeric-assay/v1",
        "representation_result_sha256": representation_result["payload_sha256"], "records": records,
        "summary": {"available_count": len(records), "mean_correction_l2": math.fsum(r["correction_l2"] for r in records) / len(records) if records else None,
            "mean_coordinate_mse": math.fsum(r["coordinate_mse"] for r in records) / len(records) if records else None,
            "mean_unit_cosine_similarity": math.fsum(r["unit_cosine_similarity"] for r in records) / len(records)
                if records and all(r["unit_cosine_similarity"] is not None for r in records) else None},
        "reconstruction_is_fidelity_evidence": False, **FALSE})
