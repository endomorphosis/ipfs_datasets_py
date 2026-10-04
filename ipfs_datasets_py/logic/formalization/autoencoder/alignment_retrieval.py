"""Source-only facet probes and train-candidate reranking for Legal alignment.

Only ridge fitting lazily imports PyTorch. Prediction and reranking use ordinary
finite vectors and metadata; neither accepts a query target. Candidate labels
are training demonstrations. Ridge softmax scores are uncalibrated predictions,
and selection coverage concerns predicted labels, not adjudicated source meaning.
Independent facet coverage does not establish joint actor/modality/object or
action/modality/object support; those are separate evaluation diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import math

FACETS = ("modality", "actor", "action", "object")
PROBE_SCHEMA = "legal-source-facet-ridge-probe/v1"
SOURCE_SPACE_ID = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
                   "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
MAX_ITEMS = 512
MAX_PROBE_BYTES = 32 * 1024 * 1024


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("finite ordinary JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _finite(number):
    if type(number) not in (int, float):
        return False
    try:
        return math.isfinite(number)
    except OverflowError:
        return False


def _rule(target):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule

    _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
             and len(target["rules"]) == 1, "one canonical training rule required")
    rule = CanonicalRule.from_dict(target["rules"][0]).to_dict()
    _require(_raw(rule) == _raw(target["rules"][0]), "training target must already be canonical")
    return rule


def _vector(value, width=None):
    _require(type(value) in (list, tuple) and len(value) in (384, 512)
             and (width is None or len(value) == width)
             and all(_finite(number) for number in value),
             "finite numeric 384D or 512D vector required; bool is forbidden")
    scale = max(abs(number) for number in value)
    _require(scale > 0, "zero vector is unsupported")
    scaled = [number / scale for number in value]
    norm = math.sqrt(math.fsum(number * number for number in scaled))
    return [number / norm for number in scaled]


def fit_facet_probe(training_rows, regularization=0.01) -> dict:
    """Fit summed-residual ridge with an unregularized intercept on training only."""
    _require(type(training_rows) in (list, tuple) and 1 <= len(training_rows) <= MAX_ITEMS,
             "bounded nonempty training rows required")
    _require(_finite(regularization)
             and 1e-12 <= regularization <= 1000, "bounded positive ridge regularization required")
    rules, vectors, manifest, ids = [], [], [], set()
    for row in training_rows:
        _require(type(row) is dict and {"id", "unit_vector", "target"} <= set(row), "validated training row fields required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in ids,
                 "unique bounded training ID required")
        if "split" in row:
            _require(row["split"] == "train", "facet probe must fit training split only")
        if "evaluation_role" in row:
            _require(row["evaluation_role"] == "exposed_development", "nondevelopment training role")
        ids.add(row["id"])
        vector, rule = _vector(row["unit_vector"], 384), _rule(row["target"])
        vectors.append(vector)
        rules.append(rule)
        manifest.append({"id": row["id"], "source_vector_sha256": _digest(vector), "target_sha256": _digest(row["target"])})
    vocabulary = {facet: sorted({rule[facet] for rule in rules}) for facet in FACETS}
    columns = [(facet, label) for facet in FACETS for label in vocabulary[facet]]
    labels = [[float(rule[facet] == label) for facet, label in columns] for rule in rules]
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("ridge probe fitting requires optional PyTorch") from error
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        with torch.no_grad():
            x = torch.tensor(vectors, dtype=torch.float64, device="cpu")
            y = torch.tensor(labels, dtype=torch.float64, device="cpu")
            x_mean, y_mean = x.mean(0), y.mean(0)
            xc, yc = x - x_mean, y - y_mean
            if len(vectors) < 384:
                system = xc @ xc.T + regularization * torch.eye(len(vectors), dtype=torch.float64, device="cpu")
                weights = xc.T @ torch.linalg.solve(system, yc)
                solve_kind = "centered_dual"
            else:
                system = xc.T @ xc + regularization * torch.eye(384, dtype=torch.float64, device="cpu")
                weights = torch.linalg.solve(system, xc.T @ yc)
                solve_kind = "centered_primal"
            bias = y_mean - x_mean @ weights
            _require(bool(torch.isfinite(weights).all()) and bool(torch.isfinite(bias).all()), "nonfinite ridge parameters")
            weight_values, bias_values = weights.T.tolist(), bias.tolist()
    finally:
        torch.set_num_threads(previous_threads)
    probe = {"schema": PROBE_SCHEMA, "source_space_id": SOURCE_SPACE_ID, "input_dimension": 384,
             "facets": list(FACETS), "vocabulary": vocabulary, "weight": weight_values, "bias": bias_values,
             "training_row_count": len(training_rows), "training_manifest_sha256": _digest(manifest),
             "recipe": {"regularization": float(regularization), "objective": "sum_squared_residuals_plus_lambda_weight_l2",
                        "intercept_regularized": False, "input_normalization": "l2", "solve_kind": solve_kind,
                        "device": "cpu", "dtype": "float64", "cpu_threads": 1, "softmax_temperature": 1.0},
             "fit_policy": "training_rows_only", "development_fit": False, "qualified": False,
             "prediction_kind": "uncalibrated_softmax_ridge_scores"}
    probe["content_sha256"] = _digest(probe)
    _validate_probe(probe)
    return probe


def _validate_probe(probe):
    fields = {"schema", "source_space_id", "input_dimension", "facets", "vocabulary", "weight", "bias",
              "training_row_count", "training_manifest_sha256", "recipe", "fit_policy", "development_fit",
              "qualified", "prediction_kind", "content_sha256"}
    _require(type(probe) is dict and set(probe) == fields, "closed ridge probe required")
    _require(probe["schema"] == PROBE_SCHEMA and probe["source_space_id"] == SOURCE_SPACE_ID
             and type(probe["input_dimension"]) is int and probe["input_dimension"] == 384
             and probe["facets"] == list(FACETS) and probe["fit_policy"] == "training_rows_only"
             and probe["development_fit"] is False and probe["qualified"] is False
             and probe["prediction_kind"] == "uncalibrated_softmax_ridge_scores", "ridge probe identity or fit scope differs")
    _require(type(probe["training_row_count"]) is int and 1 <= probe["training_row_count"] <= MAX_ITEMS,
             "bounded training row count required")
    _require(type(probe["training_manifest_sha256"]) is str and len(probe["training_manifest_sha256"]) == 64
             and all(letter in "0123456789abcdef" for letter in probe["training_manifest_sha256"]),
             "training manifest SHA256 required")
    vocabulary = probe["vocabulary"]
    _require(type(vocabulary) is dict and set(vocabulary) == set(FACETS), "four core facet vocabularies required")
    for values in vocabulary.values():
        _require(type(values) is list and 1 <= len(values) <= MAX_ITEMS
                 and all(type(value) is str and 0 < len(value) <= 4096 for value in values)
                 and values == sorted(set(values)), "unique sorted facet labels required")
    size = sum(len(vocabulary[facet]) for facet in FACETS)
    _require(type(probe["weight"]) is list and len(probe["weight"]) == size
             and all(type(row) is list and len(row) == 384 for row in probe["weight"]), "ridge weight geometry differs")
    _require(type(probe["bias"]) is list and len(probe["bias"]) == size, "ridge bias geometry differs")
    _require(all(_finite(number) for row in probe["weight"] for number in row)
             and all(_finite(number) for number in probe["bias"]),
             "finite numeric ridge parameters required; bool is forbidden")
    recipe = probe["recipe"]
    _require(type(recipe) is dict and set(recipe) == {"regularization", "objective", "intercept_regularized",
             "input_normalization", "solve_kind", "device", "dtype", "cpu_threads", "softmax_temperature"}
             and recipe["objective"] == "sum_squared_residuals_plus_lambda_weight_l2"
             and recipe["intercept_regularized"] is False and recipe["input_normalization"] == "l2"
             and recipe["solve_kind"] in ("centered_dual", "centered_primal")
             and recipe["device"] == "cpu" and recipe["dtype"] == "float64"
             and type(recipe["cpu_threads"]) is int and recipe["cpu_threads"] == 1
             and type(recipe["softmax_temperature"]) is float and recipe["softmax_temperature"] == 1.0
             and _finite(recipe["regularization"])
             and 1e-12 <= recipe["regularization"] <= 1000, "ridge recipe differs")
    _require(probe["content_sha256"] == _digest({name: value for name, value in probe.items() if name != "content_sha256"}),
             "ridge probe content digest differs")
    _require(len(_raw(probe)) <= MAX_PROBE_BYTES, "ridge probe exceeds ordinary JSON size bound")


def predict_source_facets(source_vectors, probe) -> list[dict]:
    """Predict from source vectors alone; no targets, groups or retrieval labels."""
    _validate_probe(probe)
    _require(type(source_vectors) in (list, tuple) and 1 <= len(source_vectors) <= MAX_ITEMS,
             "bounded source vector batch required")
    predictions = []
    for supplied in source_vectors:
        vector = _vector(supplied, 384)
        try:
            scores = [math.fsum(a * b for a, b in zip(vector, weight, strict=True)) + bias
                      for weight, bias in zip(probe["weight"], probe["bias"], strict=True)]
        except OverflowError as error:
            raise ValueError("nonfinite facet prediction") from error
        _require(all(math.isfinite(score) for score in scores), "nonfinite facet prediction")
        offset, result = 0, {}
        for facet in FACETS:
            labels = probe["vocabulary"][facet]
            values = scores[offset:offset + len(labels)]
            maximum = max(values)
            masses = [math.exp(value - maximum) for value in values]
            total = math.fsum(masses)
            probabilities = {label: mass / total for label, mass in zip(labels, masses, strict=True)}
            chosen = min(labels, key=lambda label: (-probabilities[label], label))
            result[facet] = {"label": chosen, "scores": probabilities}
            offset += len(labels)
        predictions.append(result)
    return predictions


def _predictions(value):
    _require(type(value) is dict and set(value) == set(FACETS), "four predicted facet distributions required")
    for part in value.values():
        _require(type(part) is dict and set(part) == {"label", "scores"}, "prediction is label plus scores, never a query target")
        scores = part["scores"]
        _require(type(scores) is dict and 1 <= len(scores) <= MAX_ITEMS
                 and all(type(label) is str and 0 < len(label) <= 4096 for label in scores)
                 and all(_finite(probability)
                         and 0 <= probability <= 1 for probability in scores.values())
                 and abs(math.fsum(scores.values()) - 1) <= 1e-6, "normalized finite prediction probabilities required")
        _require(type(part["label"]) is str and part["label"] in scores
                 and scores[part["label"]] == max(scores.values()), "prediction label differs from score maximum")
    return value


class PreparedTrainingCandidates:
    """Immutable, process-local admitted pool; create through the factory only.

    This is a runtime optimization rather than a persisted trust assertion.
    Canonical targets and finite vectors are checked before immutable tuple
    snapshots are made; every ranking still checks query/training ID overlap.
    """

    __slots__ = ("_rows", "_training_ids", "dimension", "admission_sha256")

    def __init__(self):
        raise ValueError("use prepare_training_candidates for checked admission")

    def __setattr__(self, name, value):
        raise AttributeError("prepared training candidates are immutable")


def prepare_training_candidates(candidates, *, candidate_vectors=None) -> PreparedTrainingCandidates:
    """Validate and freeze one training pool, optionally in a projected geometry.

    The supplied candidates must be caller-admitted training demonstrations.
    No source query, query target, or development labels are accepted here.
    """
    _require(type(candidates) in (list, tuple) and 1 <= len(candidates) <= MAX_ITEMS, "bounded training candidate pool required")
    lookup, identities = {}, set()
    for candidate in candidates:
        _require(type(candidate) is dict and set(candidate) == {"candidate_id", "target", "source_vector", "train_ids"},
                 "closed training candidate required")
        identity = candidate["candidate_id"]
        _require(type(identity) is str and 0 < len(identity) <= 512 and identity not in lookup, "unique candidate ID required")
        train_ids = candidate["train_ids"]
        _require(type(train_ids) is list and 1 <= len(train_ids) <= MAX_ITEMS
                 and all(type(value) is str and 0 < len(value) <= 512 for value in train_ids)
                 and len(set(train_ids)) == len(train_ids) and not identities.intersection(train_ids), "unique training membership required")
        identities.update(train_ids)
        lookup[identity] = {"rule": _rule(candidate["target"]), "vector": _vector(candidate["source_vector"], 384),
                            "train_ids": tuple(train_ids), "target_sha256": _digest(candidate["target"])}
        lookup[identity]["source_vector_sha256"] = _digest(lookup[identity]["vector"])
    dimension = 384
    if candidate_vectors is not None:
        _require(type(candidate_vectors) is dict and set(candidate_vectors) == set(lookup), "projected candidate map must match the training pool")
        dimension = len(_vector(next(iter(candidate_vectors.values()))))
        for identity, vector in candidate_vectors.items():
            lookup[identity]["vector"] = _vector(vector, dimension)
    rows = tuple((identity, tuple(item["rule"][facet] for facet in FACETS), tuple(item["vector"]), item["train_ids"])
                 for identity, item in sorted(lookup.items()))
    manifest = [{"candidate_id": identity, "target_sha256": item["target_sha256"],
                 "train_ids": list(item["train_ids"]), "source_vector_sha256": item["source_vector_sha256"],
                 "effective_vector_sha256": _digest(item["vector"])}
                for identity, item in sorted(lookup.items())]
    result = object.__new__(PreparedTrainingCandidates)
    object.__setattr__(result, "_rows", rows)
    object.__setattr__(result, "_training_ids", frozenset(identities))
    object.__setattr__(result, "dimension", dimension)
    object.__setattr__(result, "admission_sha256", _digest(manifest))
    return result


def rerank_candidates(query_id, query_vector, candidates, *, policy, top_k=5, shortlist=20,
                      diversity_lambda=0.7, predicted_facets=None, candidate_vectors=None) -> dict:
    """Rank training candidates using only query geometry and predicted facets.

    A factory-prepared immutable pool may be reused across source queries;
    ordinary candidate lists receive exactly the same validation per call.
    """
    _require(type(query_id) is str and 0 < len(query_id) <= 512, "bounded source query ID required")
    query = _vector(query_vector)
    _require(policy in ("cosine", "mmr", "facet_cover"), "unsupported reranking policy")
    _require(type(top_k) is int and type(shortlist) is int and 1 <= top_k <= shortlist <= MAX_ITEMS,
             "bounded top_k <= shortlist required")
    _require(_finite(diversity_lambda)
             and 0 <= diversity_lambda <= 1, "diversity lambda must be between zero and one")
    if type(candidates) is PreparedTrainingCandidates:
        _require(candidate_vectors is None, "prepared geometry cannot be replaced during ranking")
        prepared = candidates
    else:
        prepared = prepare_training_candidates(candidates, candidate_vectors=candidate_vectors)
    _require(prepared.dimension == len(query), "query and admitted candidate geometry dimensions differ")
    _require(query_id not in prepared._training_ids, "query ID cannot occur in its training retrieval pool")
    lookup = {identity: {"rule": dict(zip(FACETS, labels, strict=True)), "vector": vector}
              for identity, labels, vector, _train_ids in prepared._rows}
    if policy == "facet_cover":
        predicted_facets = _predictions(predicted_facets)
    else:
        _require(predicted_facets is None, "predicted facets are used only by facet_cover")
    similarities = {identity: max(-1., min(1., math.fsum(a * b for a, b in zip(query, item["vector"], strict=True))))
                    for identity, item in lookup.items()}
    pool = sorted(lookup, key=lambda identity: (-similarities[identity], identity))[:shortlist]
    selected, covered, retrieved = [], set(), []
    for _ in range(min(top_k, len(pool))):
        scores = {}
        for identity in pool:
            if identity in selected:
                continue
            relevance = similarities[identity]
            marginal = 0.0
            if policy == "cosine" or policy == "mmr" and not selected:
                score = relevance
            elif policy == "mmr":
                redundancy = max(math.fsum(a * b for a, b in zip(lookup[identity]["vector"], lookup[other]["vector"], strict=True))
                                 for other in selected)
                score = diversity_lambda * relevance - (1 - diversity_lambda) * redundancy
            else:
                rule = lookup[identity]["rule"]
                marginal = math.fsum(predicted_facets[facet]["scores"].get(rule[facet], 0.0)
                                     for facet in FACETS if (facet, rule[facet]) not in covered) / len(FACETS)
                score = diversity_lambda * ((relevance + 1) / 2) + (1 - diversity_lambda) * marginal
            scores[identity] = (score, marginal)
        chosen = min(scores, key=lambda identity: (-scores[identity][0], identity))
        score, marginal = scores[chosen]
        selected.append(chosen)
        if policy == "facet_cover":
            covered.update((facet, lookup[chosen]["rule"][facet]) for facet in FACETS)
        retrieved.append({"candidate_id": chosen, "cosine_similarity": similarities[chosen],
                          "selection_score": score, "marginal_predicted_coverage": marginal})
    return {"id": query_id, "policy": policy, "retrieved": retrieved,
            "trace": {"shortlist_count": len(pool), "candidate_count": len(lookup),
                      "shortlist": [{"candidate_id": identity, "cosine_similarity": similarities[identity]}
                                    for identity in pool],
                      "diversity_lambda": float(diversity_lambda),
                      "objective": {"cosine": "query_cosine", "mmr": "lambda_query_cosine_minus_one_minus_lambda_max_selected_cosine",
                                    "facet_cover": "lambda_normalized_query_cosine_plus_one_minus_lambda_marginal_expected_four_facet_coverage"}[policy],
                      "prediction_sha256": _digest(predicted_facets) if predicted_facets is not None else None,
                      "candidate_admission_sha256": prepared.admission_sha256,
                      "coverage_scope": "independent_four_core_facet_values" if policy == "facet_cover" else None,
                      "covered_facet_values": [list(pair) for pair in sorted(covered)],
                      "query_target_consumed": False, "qualified": False}}
