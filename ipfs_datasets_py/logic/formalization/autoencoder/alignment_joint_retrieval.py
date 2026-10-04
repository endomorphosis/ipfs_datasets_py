"""Inference-only coverage of coherent predicted Legal IR triples.

Each candidate contributes actor/modality/object and action/modality/object
triples. Their coverage functions are averaged with equal family weights:

    F(S) = 0.5 * sum(weight(t) for distinct actor triples in S)
         + 0.5 * sum(weight(t) for distinct action triples in S).

``hard_joint`` assigns weight one only to each family's predicted argmax
triple. ``soft_joint`` assigns the product of its three facet marginal scores.
The latter is a factorized proxy from uncalibrated predictions, not a measured
joint probability or probability of complementary support in a common context.
Each triple saturates after its first occurrence, giving diminishing returns.

The exact existing normalized cosine shortlist is reused. Greedy selection
maximizes lambda * (cosine + 1) / 2 + (1 - lambda) * marginal F. It rewards
coherent triples rather than scattered individual labels; relevance can still
outweigh a missing family even when that family is available in the shortlist.
Wrong source predictions can reward semantically wrong demonstrations. This
helper makes no source-fidelity, proof or qualification claim, and accepts no
query targets. It fits nothing, loads no models and changes no shared state.
"""
from __future__ import annotations

import math

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval as _base

SCHEMA = "legal-source-joint-coverage-rerank/v1"
VARIANTS = ("hard_joint", "soft_joint")
JOINT_FAMILIES = (
    ("actor_modality_object", ("actor", "modality", "object")),
    ("action_modality_object", ("action", "modality", "object")),
)


def _prediction_snapshot(predicted_facets):
    # Reuse the source-only closed prediction admission from the existing
    # helper; snapshot its ordinary values so this call mutates no caller data.
    _base._predictions(predicted_facets)
    snapshot = {facet: {"label": predicted_facets[facet]["label"],
                        "scores": dict(predicted_facets[facet]["scores"])}
                for facet in _base.FACETS}
    # Validation admits tiny sum-rounding error. Unit-sum normalization is a
    # deterministic numerical operation, not probability calibration or fit.
    probabilities = {facet: {label: probability / math.fsum(part["scores"].values())
                             for label, probability in part["scores"].items()}
                     for facet, part in snapshot.items()}
    argmax = {facet: min(scores, key=lambda label: (-scores[label], label))
              for facet, scores in probabilities.items()}
    return snapshot, probabilities, argmax


def _triple_weights(labels, probabilities, argmax, variant):
    rule = dict(zip(_base.FACETS, labels, strict=True))
    result = []
    for family, facets in JOINT_FAMILIES:
        triple = tuple(rule[facet] for facet in facets)
        if variant == "hard_joint":
            weight = float(triple == tuple(argmax[facet] for facet in facets))
        else:
            weight = math.prod(probabilities[facet].get(rule[facet], 0.0) for facet in facets)
        result.append((family, triple, weight))
    return tuple(result)


def rerank_joint_candidates(query_id, query_vector, candidates, *, variant, predicted_facets,
                            top_k=5, shortlist=20, diversity_lambda=0.7,
                            candidate_vectors=None) -> dict:
    """Rank admitted training demonstrations using only source-side inputs.

    Candidates may be the existing closed training dictionaries or a reusable
    ``prepare_training_candidates`` immutable pool. A prepared pool's effective
    geometry cannot be replaced during ranking. Its private tuple snapshot is
    inspected read-only; all admission, vector normalization and query/train
    separation remain the existing helper's responsibility.

    Defaults define the fixed experiment (top five from cosine top twenty,
    relevance weight 0.7). Smaller bounded budgets are useful for diagnostics.
    Returned coverage always refers to predictions, never adjudicated meaning.
    """
    _base._require(type(variant) is str and variant in VARIANTS, "unsupported joint coverage variant")
    snapshot, probabilities, argmax = _prediction_snapshot(predicted_facets)
    if type(candidates) is _base.PreparedTrainingCandidates:
        _base._require(candidate_vectors is None, "prepared geometry cannot be replaced during ranking")
        prepared = candidates
    else:
        prepared = _base.prepare_training_candidates(candidates, candidate_vectors=candidate_vectors)
    # This call is the authoritative source-only shortlist computation and also
    # checks finite query vectors, budgets, lambda, dimension and train-ID overlap.
    cosine = _base.rerank_candidates(query_id, query_vector, prepared, policy="cosine",
                                     top_k=top_k, shortlist=shortlist, diversity_lambda=diversity_lambda)
    exact_shortlist = cosine["trace"]["shortlist"]
    candidate_labels = {identity: labels for identity, labels, _vector, _train_ids in prepared._rows}
    weights = {item["candidate_id"]: _triple_weights(candidate_labels[item["candidate_id"]],
                                                  probabilities, argmax, variant)
               for item in exact_shortlist}
    similarities = {item["candidate_id"]: item["cosine_similarity"] for item in exact_shortlist}
    selected, covered, retrieved = set(), {}, []
    cumulative = 0.0
    for _ in range(min(top_k, len(exact_shortlist))):
        scores = {}
        for identity in similarities:
            if identity in selected:
                continue
            new_triples = tuple((family, triple, weight) for family, triple, weight in weights[identity]
                                if weight > 0 and (family, triple) not in covered)
            marginal = math.fsum(weight for _family, _triple, weight in new_triples) / len(JOINT_FAMILIES)
            relevance = (similarities[identity] + 1) / 2
            score = diversity_lambda * relevance + (1 - diversity_lambda) * marginal
            scores[identity] = (score, marginal, new_triples)
        chosen = min(scores, key=lambda identity: (-scores[identity][0], identity))
        score, marginal, new_triples = scores[chosen]
        selected.add(chosen)
        for family, triple, weight in new_triples:
            covered[(family, triple)] = weight
        cumulative = math.fsum(covered.values()) / len(JOINT_FAMILIES)
        retrieved.append({"candidate_id": chosen, "cosine_similarity": similarities[chosen],
                          "selection_score": score, "marginal_joint_coverage": marginal,
                          "cumulative_joint_coverage": cumulative})
    trace = {
        "schema": SCHEMA,
        "shortlist": exact_shortlist,
        "shortlist_count": len(exact_shortlist),
        "candidate_count": cosine["trace"]["candidate_count"],
        "candidate_admission_sha256": prepared.admission_sha256,
        "prediction_sha256": _base._digest(snapshot),
        "normalized_marginals_sha256": _base._digest(probabilities),
        "diversity_lambda": float(diversity_lambda),
        "objective": "lambda_normalized_query_cosine_plus_one_minus_lambda_marginal_joint_triple_coverage",
        "coverage_scope": "average_saturated_coherent_triple_coverage_of_two_separate_families",
        "family_weights": {family: 1 / len(JOINT_FAMILIES) for family, _facets in JOINT_FAMILIES},
        "joint_families": {family: list(facets) for family, facets in JOINT_FAMILIES},
        "predicted_argmax_triples": {family: [argmax[facet] for facet in facets]
                                     for family, facets in JOINT_FAMILIES},
        "covered_joint_triples": [{"family": family, "triple": list(triple), "weight": weight}
                                  for (family, triple), weight in sorted(covered.items())],
        "joint_coverage": cumulative,
        "factorization": {
            "weight_kind": "argmax_triple_indicator" if variant == "hard_joint" else "product_of_uncalibrated_facet_marginal_scores",
            "marginal_normalization": "validated_unit_sum_renormalization",
            "argmax_tie_break": "lexicographic_label",
            "triple_saturation": "count_each_family_triple_once",
            "estimated_joint_probability": False,
            "common_context_complementary_support_probability": False,
            "source_fidelity_guaranteed": False,
            "shortlist_support_guaranteed_selected": False,
        },
        "query_target_consumed": False,
        "qualified": False,
    }
    return {"id": query_id, "policy": variant, "retrieved": retrieved, "trace": trace}
