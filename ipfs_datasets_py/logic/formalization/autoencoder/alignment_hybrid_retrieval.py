"""Source-only two-geometry discovery with a fixed hard joint selector.

The pair factory binds source and formal candidate geometries to one frozen
canonical training pool, including qualifier-bearing target hashes. A shared
query ID identifies both source-side query vectors; the caller must bind those
vectors to the same source through its experiment provenance.

Five fixed policies distinguish discovery from selection. ``source_only`` and
``formal_only`` replay the corresponding existing hard joint selector exactly.
``source_discovery_formal_select`` keeps source discovery but uses formal cosine
selection. ``rrf_formal`` fuses two rank prefixes with equal reciprocal-rank
scores (offset 60, absent ranks contribute zero). ``quota_formal`` alternates
the first ten ranks from each head, deduplicates them, then alternates remaining
ranks to fill twenty. Both fused policies use formal cosine for selection;
fusion scores never become the selector's relevance scores.

The final shortlist/top-five budgets stay fixed, while two-head discovery can
inspect forty candidates instead of twenty. The unpruned union is reported
even for control policies as a postranking diagnostic. No query targets,
adaptive gold routing, model loads, fitting or qualification occur here.
"""
from __future__ import annotations

import math

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_joint_retrieval as _joint,
)
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval as _base

SCHEMA = "legal-source-hybrid-discovery-rerank/v1"
POLICIES = ("source_only", "formal_only", "source_discovery_formal_select", "rrf_formal", "quota_formal")
MAX_PAIR_METADATA_BYTES = 32 * 1024 * 1024


class PreparedHybridCandidatePair:
    """Immutable process-local linkage; create with the checked factory only."""

    __slots__ = ("source_candidates", "formal_candidates", "shared_candidate_manifest_sha256", "candidate_count")

    def __init__(self):
        raise ValueError("use prepare_hybrid_candidate_pair for checked admission")

    def __setattr__(self, name, value):
        raise AttributeError("hybrid candidate pairs are immutable")


def _vector_map_snapshot(vectors, identities):
    _base._require(type(vectors) is dict and set(vectors) == identities, "head vector map must match the full training pool")
    copied, width = {}, None
    for identity, vector in vectors.items():
        validated = _base._vector(vector, width)
        width = len(validated)
        copied[identity] = list(vector)
    return copied


def prepare_hybrid_candidate_pair(candidates, *, source_candidate_vectors, formal_candidate_vectors) -> PreparedHybridCandidatePair:
    """Bind two immutable geometries to the same complete canonical targets.

    Both maps cover the entire training pool. Caller objects are copied before
    the existing prepared factories inspect them, so later input mutation
    cannot alter target linkage, training membership or candidate vectors.
    """
    _base._require(type(candidates) in (list, tuple) and 1 <= len(candidates) <= _base.MAX_ITEMS,
                   "bounded nonempty full training candidate pool required")
    snapshots, manifest, size = [], [], 0
    for candidate in candidates:
        _base._require(type(candidate) is dict and set(candidate) == {"candidate_id", "target", "source_vector", "train_ids"},
                       "closed canonical training candidate required")
        identity, train_ids = candidate["candidate_id"], candidate["train_ids"]
        _base._require(type(identity) is str and 0 < len(identity) <= 512, "bounded candidate ID required")
        _base._require(type(train_ids) is list and 1 <= len(train_ids) <= _base.MAX_ITEMS
                       and all(type(value) is str and 0 < len(value) <= 512 for value in train_ids),
                       "bounded training membership required")
        _base._vector(candidate["source_vector"], 384)
        target = {"rules": [_base._rule(candidate["target"])]}
        snapshot = {"candidate_id": identity, "target": target, "train_ids": list(train_ids),
                    "source_vector": list(candidate["source_vector"])}
        size += len(_base._raw(snapshot))
        _base._require(size <= MAX_PAIR_METADATA_BYTES, "full candidate metadata exceeds the bounded prototype")
        snapshots.append(snapshot)
        manifest.append({"candidate_id": identity, "target_sha256": _base._digest(target),
                         "train_ids": sorted(train_ids), "source_vector_sha256": _base._digest(snapshot["source_vector"])})
    identities = {candidate["candidate_id"] for candidate in snapshots}
    source_map = _vector_map_snapshot(source_candidate_vectors, identities)
    formal_map = _vector_map_snapshot(formal_candidate_vectors, identities)
    source = _base.prepare_training_candidates(snapshots, candidate_vectors=source_map)
    formal = _base.prepare_training_candidates(snapshots, candidate_vectors=formal_map)
    source_memberships = {identity: (labels, frozenset(train_ids)) for identity, labels, _vector, train_ids in source._rows}
    formal_memberships = {identity: (labels, frozenset(train_ids)) for identity, labels, _vector, train_ids in formal._rows}
    _base._require(source_memberships == formal_memberships, "head training identities, core labels or memberships differ")
    result = object.__new__(PreparedHybridCandidatePair)
    object.__setattr__(result, "source_candidates", source)
    object.__setattr__(result, "formal_candidates", formal)
    object.__setattr__(result, "shared_candidate_manifest_sha256", _base._digest(sorted(manifest, key=lambda item: item["candidate_id"])))
    object.__setattr__(result, "candidate_count", len(snapshots))
    return result


def _quota_discovery(source_ids, formal_ids, budget):
    selected, seen = [], set()
    half = budget // 2
    for start, stop in ((0, half), (half, max(len(source_ids), len(formal_ids)))):
        for index in range(start, stop):
            for head in (source_ids, formal_ids):
                if index < len(head) and head[index] not in seen:
                    selected.append(head[index])
                    seen.add(head[index])
                if len(selected) == budget:
                    return selected
    return selected


def _select_hard_joint(query_id, pool, similarities, prepared, snapshot, probabilities, argmax, diversity_lambda, top_k):
    """Apply the existing hard objective to an explicit admitted discovery pool."""
    labels = {identity: row_labels for identity, row_labels, _vector, _train_ids in prepared._rows}
    weights = {identity: _joint._triple_weights(labels[identity], probabilities, argmax, "hard_joint") for identity in pool}
    selected, covered, retrieved = set(), {}, []
    for _ in range(min(top_k, len(pool))):
        scores = {}
        for identity in pool:
            if identity in selected:
                continue
            new = tuple((family, triple, weight) for family, triple, weight in weights[identity]
                        if weight > 0 and (family, triple) not in covered)
            marginal = math.fsum(weight for _family, _triple, weight in new) / len(_joint.JOINT_FAMILIES)
            relevance = (similarities[identity] + 1) / 2
            score = diversity_lambda * relevance + (1 - diversity_lambda) * marginal
            scores[identity] = (score, marginal, new)
        chosen = min(scores, key=lambda identity: (-scores[identity][0], identity))
        score, marginal, new = scores[chosen]
        selected.add(chosen)
        for family, triple, weight in new:
            covered[(family, triple)] = weight
        cumulative = math.fsum(covered.values()) / len(_joint.JOINT_FAMILIES)
        retrieved.append({"candidate_id": chosen, "cosine_similarity": similarities[chosen], "selection_score": score,
                          "marginal_joint_coverage": marginal, "cumulative_joint_coverage": cumulative})
    trace = {
        "prediction_sha256": _base._digest(snapshot),
        "normalized_marginals_sha256": _base._digest(probabilities),
        "objective": "lambda_normalized_query_cosine_plus_one_minus_lambda_marginal_joint_triple_coverage",
        "joint_coverage": math.fsum(covered.values()) / len(_joint.JOINT_FAMILIES),
        "covered_joint_triples": [{"family": family, "triple": list(triple), "weight": weight}
                                  for (family, triple), weight in sorted(covered.items())],
        "predicted_argmax_triples": {family: [argmax[facet] for facet in facets] for family, facets in _joint.JOINT_FAMILIES},
        "query_target_consumed": False, "qualified": False,
    }
    return {"id": query_id, "policy": "hard_joint", "retrieved": retrieved, "trace": trace}


def rerank_hybrid_policies(query_id, source_query_vector, formal_query_vector, pair, *, policies=POLICIES,
                            predicted_facets, top_k=5, shortlist=20, head_budget=20, rrf_k=60,
                            diversity_lambda=0.7) -> list[dict]:
    """Compute both source-only heads once and rank fixed policies in order.

    Query/training separation is checked against both complete admitted pools,
    including candidates excluded from every head and final shortlist. Control
    selector outputs and embedded traces exactly reuse the existing helper.
    All new policies select using formal cosine, not reciprocal-rank scores.
    """
    _base._require(type(pair) is PreparedHybridCandidatePair, "factory-admitted hybrid candidate pair required")
    _base._require(type(policies) in (list, tuple) and 1 <= len(policies) <= len(POLICIES)
                   and all(type(policy) is str and policy in POLICIES for policy in policies)
                   and len(set(policies)) == len(policies), "unique supported hybrid policies required")
    _base._require(type(top_k) is int and type(shortlist) is int and type(head_budget) is int
                   and 1 <= top_k <= shortlist <= head_budget <= _base.MAX_ITEMS,
                   "bounded top_k <= final shortlist <= head budget required")
    _base._require("quota_formal" not in policies or shortlist % 2 == 0, "quota discovery needs an even final budget")
    _base._require(type(rrf_k) is int and 1 <= rrf_k <= 4096, "bounded positive reciprocal-rank offset required")
    snapshot, probabilities, argmax = _joint._prediction_snapshot(predicted_facets)
    complete_source = _base.rerank_candidates(query_id, source_query_vector, pair.source_candidates, policy="cosine",
                                             top_k=pair.candidate_count, shortlist=pair.candidate_count,
                                             diversity_lambda=diversity_lambda)
    complete_formal = _base.rerank_candidates(query_id, formal_query_vector, pair.formal_candidates, policy="cosine",
                                             top_k=pair.candidate_count, shortlist=pair.candidate_count,
                                             diversity_lambda=diversity_lambda)
    source_all, formal_all = complete_source["trace"]["shortlist"], complete_formal["trace"]["shortlist"]
    source_head, formal_head = source_all[:head_budget], formal_all[:head_budget]
    source_scores = {item["candidate_id"]: item["cosine_similarity"] for item in source_all}
    formal_scores = {item["candidate_id"]: item["cosine_similarity"] for item in formal_all}
    source_ids = [item["candidate_id"] for item in source_head]
    formal_ids = [item["candidate_id"] for item in formal_head]
    source_ranks = {identity: index + 1 for index, identity in enumerate(source_ids)}
    formal_ranks = {identity: index + 1 for index, identity in enumerate(formal_ids)}
    union_ids = set(source_ids) | set(formal_ids)
    rrf = {identity: (1 / (rrf_k + source_ranks[identity]) if identity in source_ranks else 0.)
                    + (1 / (rrf_k + formal_ranks[identity]) if identity in formal_ranks else 0.) for identity in union_ids}
    fusion_order = sorted(union_ids, key=lambda identity: (-rrf[identity], identity))
    union = [{"candidate_id": identity, "cosine_similarity": formal_scores[identity],
              "source_cosine_similarity": source_scores[identity], "formal_cosine_similarity": formal_scores[identity],
              "source_rank": source_ranks.get(identity), "formal_rank": formal_ranks.get(identity), "rrf_score": rrf[identity]}
             for identity in fusion_order]
    controls = {}
    for policy, query, prepared in (("source_only", source_query_vector, pair.source_candidates),
                                    ("formal_only", formal_query_vector, pair.formal_candidates)):
        if policy in policies:
            controls[policy] = _joint.rerank_joint_candidates(query_id, query, prepared, variant="hard_joint",
                                                             predicted_facets=snapshot, top_k=top_k, shortlist=shortlist,
                                                             diversity_lambda=diversity_lambda)
    rankings = []
    for policy in policies:
        if policy in ("source_only", "source_discovery_formal_select"):
            final_ids, consulted, discovery = source_ids[:shortlist], ["source"], "source_cosine_prefix"
        elif policy == "formal_only":
            final_ids, consulted, discovery = formal_ids[:shortlist], ["formal"], "formal_cosine_prefix"
        elif policy == "rrf_formal":
            final_ids, consulted, discovery = fusion_order[:shortlist], ["source", "formal"], "equal_reciprocal_rank_prefix_fusion"
        else:
            final_ids, consulted, discovery = _quota_discovery(source_ids, formal_ids, shortlist), ["source", "formal"], "alternating_top_half_prefixes_then_alternating_unique_fill"
        _base._require(len(final_ids) == min(shortlist, pair.candidate_count), "final shortlist accounting differs")
        selector_geometry = "source" if policy == "source_only" else "formal"
        selection_scores = source_scores if selector_geometry == "source" else formal_scores
        result = controls.get(policy) or _select_hard_joint(query_id, tuple(final_ids), selection_scores, pair.formal_candidates,
                                                           snapshot, probabilities, argmax, diversity_lambda, top_k)
        final_pool = [{"candidate_id": identity, "cosine_similarity": selection_scores[identity]} for identity in final_ids]
        trace = {
            "schema": SCHEMA, "head_budget": head_budget, "source_head_budget": head_budget,
            "formal_head_budget": head_budget, "final_budget": shortlist, "top_k": top_k,
            "shortlist": final_pool, "shortlist_count": len(final_pool), "candidate_count": pair.candidate_count,
            "source_head_shortlist": source_head, "formal_head_shortlist": formal_head,
            "unpruned_union": union, "unpruned_union_count": len(union), "unpruned_union_sha256": _base._digest(union),
            "consulted_heads": consulted,
            "upstream_discovery_budget": head_budget * len(consulted),
            "upstream_candidates_consulted": sum(len(source_head if head == "source" else formal_head) for head in consulted),
            "batch_computed_both_heads": True,
            "shared_candidate_manifest_sha256": pair.shared_candidate_manifest_sha256,
            "source_candidate_admission_sha256": pair.source_candidates.admission_sha256,
            "formal_candidate_admission_sha256": pair.formal_candidates.admission_sha256,
            "source_dimension": pair.source_candidates.dimension, "formal_dimension": pair.formal_candidates.dimension,
            "selector_geometry": selector_geometry, "selector_variant": "hard_joint",
            "discovery_rule": discovery, "rrf_k": rrf_k, "rrf_head_weights": {"source": 1., "formal": 1.},
            "missing_prefix_rank_contribution": 0., "rrf_used_as_selection_relevance": False,
            "diversity_lambda": float(diversity_lambda),
            "objective": result["trace"]["objective"], "prediction_sha256": result["trace"]["prediction_sha256"],
            "normalized_marginals_sha256": result["trace"]["normalized_marginals_sha256"],
            "predicted_argmax_triples": result["trace"]["predicted_argmax_triples"],
            "covered_joint_triples": result["trace"]["covered_joint_triples"], "joint_coverage": result["trace"]["joint_coverage"],
            "embedded_joint_trace": result["trace"] if policy in controls else None,
            "factorization": {"weight_kind": "argmax_triple_indicator", "triple_saturation": "count_each_family_triple_once",
                              "estimated_joint_probability": False, "source_fidelity_guaranteed": False,
                              "union_support_guaranteed_retained": False, "shortlist_support_guaranteed_selected": False},
            "query_identity_shared": True, "query_vector_source_binding": "caller_provenance_required",
            "query_target_consumed": False, "qualified": False,
        }
        rankings.append({"id": query_id, "policy": policy, "retrieved": result["retrieved"], "trace": trace})
    return rankings


def rerank_hybrid_candidates(query_id, source_query_vector, formal_query_vector, pair, *, policy,
                              predicted_facets, top_k=5, shortlist=20, head_budget=20, rrf_k=60,
                              diversity_lambda=0.7) -> dict:
    """Single-policy facade with the same admission and fixed selection rules."""
    return rerank_hybrid_policies(query_id, source_query_vector, formal_query_vector, pair, policies=(policy,),
                                  predicted_facets=predicted_facets, top_k=top_k, shortlist=shortlist,
                                  head_budget=head_budget, rrf_k=rrf_k, diversity_lambda=diversity_lambda)[0]
