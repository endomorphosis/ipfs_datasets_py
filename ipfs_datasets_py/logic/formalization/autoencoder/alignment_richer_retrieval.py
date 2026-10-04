"""Bounded training-only source-to-structure retrieval and posthoc diagnostics.

Native source widths are explicit independent lanes. Structural positive counts
are a lossy declared formal feature space, not a source embedding, autoencoder,
probability, semantic interpreter, or proof. This helper cannot authenticate a
caller's training split or encoder execution; the experiment must bind those.
Query envelopes exclude references, expectations, and construction outcomes.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

HEAD_SCHEMA = "alignment-richer-structural-ridge/v1"
RANK_SCHEMA = "alignment-richer-source-structural-rankings/v1"
SCORE_SCHEMA = "alignment-richer-authored-retrieval-diagnostics/v1"
MAX_TRAIN = 16
MAX_BYTES = 8 * 1024 * 1024
SOURCE_WIDTHS = (8, 384, 768)
CORE_FACETS = ("modality", "actor", "action", "object")
QUALIFIER_FACETS = ("conditions", "exceptions", "temporal")
FACET_WEIGHTS = {facet: 1.0 for facet in CORE_FACETS + QUALIFIER_FACETS}
_AUTHORITY = {"qualified": False, "source_fidelity_established": False, "proof_authority": False,
              "independent_fidelity_available": False, "autoencoder_training_executed": False}
_HEAD_FIELDS = frozenset({"schema", "training_manifest", "training_manifest_sha256", "source_width",
    "formal_dimension", "seed", "alpha", "intercept", "normalization", "formal_space_id",
    "source_units", "target_units", "kernel_inverse", "fit_recipe", "fit_scope", "training_count",
    "encoder_execution_authenticated", "head_sha256", *_AUTHORITY})
_RANK_FIELDS = frozenset({"schema", "id", "group_id", "query_vector_sha256", "head_sha256",
    "candidate_pool_sha256", "candidate_ids", "formal_dimension", "seed", "top_k", "source_width",
    "source_cosine", "structural_ridge", "query_reference_consumed", "ranking_sha256", *_AUTHORITY})


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as error:
        raise ValueError("bounded finite ordinary JSON required") from error
    _require(len(raw) <= MAX_BYTES, "richer retrieval artifact exceeds byte bound")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _finite(number):
    try:
        return type(number) in (int, float) and math.isfinite(number)
    except (ValueError, OverflowError):
        return False


def _identity(value, field):
    _require(type(value) is str and 0 < len(value) <= 512 and value.strip(), f"bounded {field} required")
    return value


def _unit(vector, *, width=None, source=False, allow_zero=False):
    _require(type(vector) in (list, tuple) and bool(vector)
             and (width is None or len(vector) == width)
             and (not source or len(vector) in SOURCE_WIDTHS)
             and all(_finite(value) for value in vector), "matching finite numeric vector required; bool is forbidden")
    scale = max(abs(value) for value in vector)
    if scale == 0:
        _require(allow_zero, "zero vector has no cosine direction")
        return None
    scaled = [float(value / scale) for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    _require(math.isfinite(norm) and norm > 0, "finite nonzero vector direction required")
    return [value / norm for value in scaled]


def _settings(dimension, seed, alpha):
    _require(type(dimension) is int and dimension in (2048, 4096), "declared structural dimension required")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer structural hash seed required")
    _require(_finite(alpha) and 0 < alpha <= 1_000_000, "positive finite ridge regularization required")


def _target(value):
    from .alignment_structure import prepare_structural_features

    features = prepare_structural_features(value)
    _require(_raw(value) == _raw(features["canonical_ir"]), "training/reference IR must already be canonical")
    return features


def _training(rows, dimension, seed):
    from .alignment_structure import encode_structural_features

    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= MAX_TRAIN, "one through sixteen declared TRAIN rows required")
    _raw(rows)
    manifest, sources, targets, identities, groups = [], [], [], set(), set()
    width, space = None, None
    for row in sorted(rows, key=lambda item: _identity(item.get("id"), "training id") if type(item) is dict else ""):
        _require(type(row) is dict and set(row) == {"id", "group_id", "source_vector", "target"}, "closed training row required")
        identity = _identity(row["id"], "training id")
        group = _identity(row["group_id"], "training group")
        _require(identity not in identities, "duplicate training identity")
        identities.add(identity)
        groups.add(group)
        source = _unit(row["source_vector"], width=width, source=True)
        width = len(source)
        features = _target(row["target"])
        encoded = encode_structural_features(features, dimension=dimension, seed=seed)
        _require(space is None or space == encoded["feature_space_id"], "formal coordinate spaces differ")
        space = encoded["feature_space_id"]
        dense = [0.0] * dimension
        for item in encoded["sparse_counts"]:
            dense[item["index"]] = float(item["value"])
        formal = _unit(dense, width=dimension)
        sources.append(source)
        targets.append(formal)
        manifest.append({"id": identity, "group_id": group, "unit_source_sha256": _digest(source),
                         "target_sha256": features["declaration_sha256"], "formal_values_sha256": _digest(formal)})
    return {"manifest": manifest, "sources": sources, "targets": targets,
            "width": width, "space": space, "ids": identities, "groups": groups}


def _dot(left, right):
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def fit_structural_ridge(training_rows, *, dimension=2048, seed=0, alpha=1.0):
    """Fit only supplied TRAIN pairs: C=(XXᵀ+αI)⁻¹Y; no intercept.

    Source X and hashed-count Y rows are separately L2 normalized. Store the
    small inverse and paired rows, avoiding a second dense coefficient copy.
    NumPy is imported only for this bounded CPU linear solve; no model is used.
    """
    _settings(dimension, seed, alpha)
    training = _training(training_rows, dimension, seed)
    import numpy as np

    x = np.asarray(training["sources"], dtype=np.float64)
    count = len(x)
    inverse = np.linalg.solve(x @ x.T + float(alpha) * np.eye(count, dtype=np.float64),
                              np.eye(count, dtype=np.float64))
    _require(bool(np.isfinite(inverse).all()), "ridge linear solve produced nonfinite parameters")
    head = {"schema": HEAD_SCHEMA, "training_manifest": training["manifest"],
            "training_manifest_sha256": _digest(training["manifest"]), "source_width": training["width"],
            "formal_dimension": dimension, "seed": seed, "alpha": float(alpha), "intercept": False,
            "normalization": "independent_l2_source_rows_and_positive_hashed_target_rows; prediction_l2_for_cosine",
            "formal_space_id": training["space"], "source_units": training["sources"],
            "target_units": training["targets"], "kernel_inverse": inverse.tolist(),
            "fit_recipe": "uncentered_dual_ridge_float64_inverse_kernel_plus_alpha_identity",
            "fit_scope": "caller_supplied_training_pairs_only", "training_count": count,
            "encoder_execution_authenticated": False, **_AUTHORITY}
    head["head_sha256"] = _digest(head)
    _validate_head(head, training)
    return head


def _matrix(value, rows, columns, name):
    _require(type(value) is list and len(value) == rows
             and all(type(row) is list and len(row) == columns and all(_finite(v) for v in row) for row in value),
             f"finite {name} matrix with declared shape required")


def _validate_head(head, training):
    _require(type(head) is dict and set(head) == _HEAD_FIELDS, "closed structural ridge head required")
    _raw(head)
    _settings(head["formal_dimension"], head["seed"], head["alpha"])
    _require(head["schema"] == HEAD_SCHEMA and head["source_width"] == training["width"]
             and type(head["source_width"]) is int and head["training_count"] == len(training["sources"])
             and type(head["training_count"]) is int and head["intercept"] is False
             and head["fit_recipe"] == "uncentered_dual_ridge_float64_inverse_kernel_plus_alpha_identity"
             and head["fit_scope"] == "caller_supplied_training_pairs_only"
             and head["normalization"] == "independent_l2_source_rows_and_positive_hashed_target_rows; prediction_l2_for_cosine"
             and head["encoder_execution_authenticated"] is False
             and all(head[key] is False for key in _AUTHORITY), "head recipe or authority changed")
    _require(head["training_manifest"] == training["manifest"]
             and head["training_manifest_sha256"] == _digest(training["manifest"])
             and head["source_units"] == training["sources"] and head["target_units"] == training["targets"]
             and head["formal_space_id"] == training["space"], "head does not bind the exact training source/target pairs")
    count = head["training_count"]
    _matrix(head["source_units"], count, head["source_width"], "source")
    _matrix(head["target_units"], count, head["formal_dimension"], "target")
    _matrix(head["kernel_inverse"], count, count, "kernel inverse")
    unsigned = {key: value for key, value in head.items() if key != "head_sha256"}
    _require(head["head_sha256"] == _digest(unsigned), "head digest changed")
    inverse = head["kernel_inverse"]
    kernel = [[_dot(a, b) + (head["alpha"] if i == j else 0.0)
               for j, b in enumerate(training["sources"])] for i, a in enumerate(training["sources"])]
    for i in range(count):
        for j in range(count):
            _require(abs(inverse[i][j] - inverse[j][i]) <= 1e-8, "ridge inverse symmetry changed")
            residue = math.fsum(kernel[i][k] * inverse[k][j] for k in range(count)) - (1.0 if i == j else 0.0)
            _require(math.isfinite(residue) and abs(residue) <= 1e-7, "resealed inverse is not the declared ridge solution")


def _policy(scores, top_k, *, prediction_digest=None):
    full = [{"candidate_id": identity, "cosine_similarity": value}
            for identity, value in sorted(scores, key=lambda item: (-item[1], item[0]))]
    return {"status": "available", "reason": None, "ranked": full[:top_k],
            "full_pool_ranking": full, "prediction_values_sha256": prediction_digest}


def rank_richer_candidates(query, training_rows, head, *, top_k=5):
    """Rank the complete bounded training pool; never accept a query reference."""
    _require(type(query) is dict and set(query) == {"id", "group_id", "source_vector"}, "closed target-free query required")
    _require(type(head) is dict and "formal_dimension" in head and "seed" in head, "structural ridge head required")
    _require(type(top_k) is int and 1 <= top_k <= MAX_TRAIN, "bounded integer top_k required")
    _settings(head["formal_dimension"], head["seed"], head.get("alpha"))
    training = _training(training_rows, head["formal_dimension"], head["seed"])
    _validate_head(head, training)
    identity = _identity(query["id"], "query id")
    group = _identity(query["group_id"], "query group")
    _require(identity not in training["ids"] and group not in training["groups"], "query identity/group leaks into training")
    source = _unit(query["source_vector"], width=training["width"], source=True)
    similarities = [_dot(source, vector) for vector in training["sources"]]
    coefficients = [math.fsum(similarities[i] * head["kernel_inverse"][i][j] for i in range(len(similarities)))
                    for j in range(len(similarities))]
    prediction = [math.fsum(coefficient * target[column] for coefficient, target in zip(coefficients, training["targets"], strict=True))
                  for column in range(head["formal_dimension"])]
    _require(all(_finite(value) for value in prediction), "ridge prediction produced nonfinite values")
    predicted_unit = _unit(prediction, width=head["formal_dimension"], allow_zero=True)
    ids = [item["id"] for item in training["manifest"]]
    structural = ({"status": "unavailable", "reason": "zero_prediction_vector", "ranked": [],
                   "full_pool_ranking": [], "prediction_values_sha256": _digest(prediction)}
                  if predicted_unit is None else _policy(list(zip(ids, [_dot(predicted_unit, target)
                      for target in training["targets"]], strict=True)), top_k, prediction_digest=_digest(prediction)))
    result = {"schema": RANK_SCHEMA, "id": identity, "group_id": group, "query_vector_sha256": _digest(source),
              "head_sha256": head["head_sha256"], "candidate_pool_sha256": _digest(training["manifest"]),
              "candidate_ids": ids, "formal_dimension": head["formal_dimension"], "seed": head["seed"],
              "top_k": top_k, "source_width": training["width"],
              "source_cosine": _policy(list(zip(ids, similarities, strict=True)), top_k),
              "structural_ridge": structural, "query_reference_consumed": False, **_AUTHORITY}
    result["ranking_sha256"] = _digest(result)
    return result


def _counter_jaccard(left, right):
    union = sum((left | right).values())
    return sum((left & right).values()) / union if union else 1.0


def _facet_matches(target, reference):
    def counts(payload, facet):
        return Counter(atom for rule in payload["rules"]
                       for atom in (rule[facet] if facet in QUALIFIER_FACETS else [rule[facet]]))
    return {facet: _counter_jaccard(counts(target, facet), counts(reference, facet)) for facet in FACET_WEIGHTS}


def _metrics(proposed, expected):
    true_positive = sum((proposed & expected).values())
    return {"tp": true_positive, "fp": sum((proposed - expected).values()), "fn": sum((expected - proposed).values()),
            "reference_recall": true_positive / sum(expected.values()) if expected else None,
            "exact": proposed == expected}


def _coverage(targets, reference):
    rules = [rule for target in targets for rule in target["rules"]]
    expected = reference["rules"]
    def core(rule):
        return tuple(rule[facet] for facet in CORE_FACETS)
    def scoped(items):
        return Counter((core(rule), facet, atom) for rule in items for facet in QUALIFIER_FACETS for atom in rule[facet])
    unscoped = {}
    for facet in QUALIFIER_FACETS:
        actual = {atom for rule in rules for atom in rule[facet]}
        required = {atom for rule in expected for atom in rule[facet]}
        unscoped[facet] = {"matched_atoms": sorted(required & actual), "missing_atoms": sorted(required - actual),
                           "reference_atoms": len(required), "reference_identity_recall": len(required & actual) / len(required) if required else None,
                           "empty_reference": not required}
    return {"unscoped_qualifier_identity": unscoped,
            "core_scoped_typed_qualifier_counts": _metrics(scoped(rules), scoped(expected)),
            "full_rule_counts": _metrics(Counter(_digest(rule) for rule in rules), Counter(_digest(rule) for rule in expected))}


def _validate_rankings(rankings, training):
    _require(type(rankings) is dict and set(rankings) == _RANK_FIELDS and rankings["schema"] == RANK_SCHEMA,
             "closed richer ranking receipt required")
    _require(all(rankings[key] is False for key in _AUTHORITY) and rankings["query_reference_consumed"] is False,
             "ranking cannot acquire semantic/proof authority")
    _require(type(rankings["top_k"]) is int and 1 <= rankings["top_k"] <= MAX_TRAIN
             and rankings["source_width"] == training["width"]
             and rankings["candidate_pool_sha256"] == _digest(training["manifest"])
             and rankings["candidate_ids"] == [item["id"] for item in training["manifest"]], "ranking candidate pool changed")
    _require(_identity(rankings["id"], "query id") not in training["ids"]
             and _identity(rankings["group_id"], "query group") not in training["groups"], "ranking query leaks into training")
    _require(rankings["ranking_sha256"] == _digest({key: value for key, value in rankings.items() if key != "ranking_sha256"}),
             "ranking receipt digest changed")
    for name in ("source_cosine", "structural_ridge"):
        policy = rankings[name]
        _require(type(policy) is dict and set(policy) == {"status", "reason", "ranked", "full_pool_ranking", "prediction_values_sha256"},
                 "closed ranking policy required")
        if policy["status"] == "unavailable":
            _require(name == "structural_ridge" and policy["reason"] == "zero_prediction_vector"
                     and policy["ranked"] == [] and policy["full_pool_ranking"] == [], "unavailable direction cannot have fabricated rankings")
            continue
        _require(policy["status"] == "available" and policy["reason"] is None
                 and type(policy["full_pool_ranking"]) is list, "invalid ranking availability")
        full = policy["full_pool_ranking"]
        _require(len(full) == len(training["ids"]), "complete training pool must be ranked")
        for item in full:
            _require(type(item) is dict and set(item) == {"candidate_id", "cosine_similarity"}
                     and item["candidate_id"] in training["ids"] and _finite(item["cosine_similarity"])
                     and abs(item["cosine_similarity"]) <= 1.000000000001, "invalid ranked candidate")
        _require({item["candidate_id"] for item in full} == training["ids"]
                 and full == sorted(full, key=lambda item: (-item["cosine_similarity"], item["candidate_id"]))
                 and policy["ranked"] == full[:rankings["top_k"]], "duplicate, unsorted or changed top-k candidates")


def score_richer_rankings(rankings, reference, training_rows):
    """Read an authored reference only after rankings have been frozen.

    Per-facet multiset Jaccard gains have seven fixed equal weights. Core exact
    matches reduce to 0/1 for single-rule rows. Qualifier identity coverage is
    deliberately separate from strict core-scoped/full-rule coverage. No exact
    counterpart retrieval metric is available when the pool lacks that target.
    """
    _require(type(rankings) is dict and "formal_dimension" in rankings and "seed" in rankings, "ranking receipt required")
    _settings(rankings["formal_dimension"], rankings["seed"], 1.0)
    training = _training(training_rows, rankings["formal_dimension"], rankings["seed"])
    _validate_rankings(rankings, training)
    reference = _target(reference)["canonical_ir"]
    lookup = {row["id"]: row["target"] for row in training_rows}
    gains, facets = {}, {}
    for identity, target in lookup.items():
        facets[identity] = _facet_matches(target, reference)
        gains[identity] = math.fsum(FACET_WEIGHTS[name] * score for name, score in facets[identity].items()) / math.fsum(FACET_WEIGHTS.values())
    count = min(rankings["top_k"], len(lookup))
    ideal = sorted(gains.values(), reverse=True)[:count]
    def dcg(values):
        return math.fsum(value / math.log2(index + 2) for index, value in enumerate(values))
    denominator = dcg(ideal)
    pool_coverage = _coverage(list(lookup.values()), reference)
    counterpart = sorted(identity for identity, target in lookup.items() if target == reference)
    policies = {}
    for name in ("source_cosine", "structural_ridge"):
        policy = rankings[name]
        if policy["status"] == "unavailable":
            policies[name] = {"status": "unavailable", "reason": policy["reason"], "authored_metrics": None}
            continue
        ids = [item["candidate_id"] for item in policy["ranked"]]
        selected_gains = [gains[identity] for identity in ids]
        policies[name] = {"status": "available", "reason": None, "authored_metrics": {
            "ranked_facet_matches": [{"candidate_id": identity, "facets": facets[identity], "weighted_fraction": gains[identity]} for identity in ids],
            "nearest_weighted_fraction": selected_gains[0], "best_top_k_weighted_fraction": max(selected_gains),
            "mean_top_k_weighted_fraction": math.fsum(selected_gains) / len(selected_gains),
            "graded_facet_ndcg": dcg(selected_gains) / denominator if denominator else None,
            "attainable_pool_best_weighted_fraction": max(gains.values()), "ideal_pool_top_k_dcg": denominator,
            "selected_coverage": _coverage([lookup[identity] for identity in ids], reference),
            "exact_ir_counterpart_recall": {"available": bool(counterpart), "value": float(bool(set(ids) & set(counterpart))) if counterpart else None,
                                            "reason": None if counterpart else "no_reference_target_in_training_pool"}}}
    result = {"schema": SCORE_SCHEMA, "query_id": rankings["id"], "ranking_sha256": rankings["ranking_sha256"],
              "reference_sha256": _digest(reference), "candidate_pool_sha256": rankings["candidate_pool_sha256"],
              "facet_weights": dict(FACET_WEIGHTS), "facet_match_recipe": "typed_facet_multiset_jaccard; empty_empty_equals_one",
              "dcg_recipe": "linear_weighted_facet_fraction_over_log2_rank_plus_one; ideal_same_full_training_pool",
              "pool_coverage_ceiling": pool_coverage, "reference_target_present_in_pool": bool(counterpart),
              "policies": policies, "evaluation_role": "exposed_development", "reference_origin": "synthetic_authored_unreviewed",
              "semantic_equivalence_checked": False, "qualifier_rule_coassociation_checked_by": "full_rule_counts_only",
              "negative_abstention_or_context_resolution_established": False, **_AUTHORITY}
    result["score_sha256"] = _digest(result)
    return result


__all__ = ["fit_structural_ridge", "rank_richer_candidates", "score_richer_rankings"]
