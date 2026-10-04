"""Source-only Legal compiler and cached source retrieval development controls.

This helper writes nothing and invokes no model, prover, downloader or trainer.
Authored synthetic references are scoring inputs, never independent adjudication.
Cached vectors retain their declared producer identity; integrity does not
authenticate the original encoder execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path

SCHEMA = "autoformal-alignment-baseline/v1"
VECTOR_SPACE_ID = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
                   "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
MAX_FILE_BYTES = 64 * 1024 * 1024
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
CORE_FACETS = ("modality", "actor", "action", "object")
_REQUIRED_ROW = {"id", "group_id", "split", "source_text", "source_sha256", "embedding",
                 "embedding_sha256", "target"}
_OPTIONAL_ROW = {"embedding_token_ids_sha256", "wording_style", "target_sha256",
                 "target_origin", "evaluation_role"}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def _normalized_source(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _load_file(binding, roots, expected_name, max_bytes=MAX_FILE_BYTES):
    _require(type(binding) is dict and set(binding) == {"path", "sha256"}, "file binding fields changed")
    _require(type(binding["path"]) is str and binding["path"], "bound path required")
    _require(type(binding["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]),
             "expected SHA256 required")
    supplied = Path(binding["path"])
    candidates = [supplied] if supplied.is_absolute() else [root / supplied for root in roots]
    matches = {path.resolve() for path in candidates if path.is_file()}
    _require(len(matches) == 1, "missing or ambiguous corpus path")
    path = matches.pop()
    relative = next((path.relative_to(root) for root in roots if path.is_relative_to(root)), None)
    _require(relative is not None, "corpus path outside declared roots")
    _require(path.name == expected_name, "only train.json and validation.json development inputs accepted")
    _require(not any(re.search(r"(^|[-_])(sealed|holdout|heldout|final|test)([-_.]|$)",
                              part.casefold()) for part in relative.parts), "sealed/final/test path forbidden")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    _require(len(raw) <= max_bytes, "corpus file exceeds byte bound")
    _require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "corpus file SHA256 mismatch")
    def reject_constant(value):
        raise ValueError("nonfinite JSON number forbidden: " + value)
    payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=reject_constant)
    _require(type(payload) is dict and set(payload) == {"rows"}, "closed corpus rows envelope required")
    return path, payload["rows"]


def _validated_rows(rows, split, max_rows):
    # Contract imports are lightweight; optional parser/model stacks remain lazy.
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule
    _require(type(rows) is list and 1 <= len(rows) <= max_rows, "bounded nonempty rows required")
    identities, source_targets = set(), {}
    prepared = []
    for row in rows:
        _require(type(row) is dict and _REQUIRED_ROW <= set(row)
                 and set(row) <= _REQUIRED_ROW | _OPTIONAL_ROW, "closed source row fields required")
        _require(row["split"] == split, "unexpected split; test/final/sealed rows forbidden")
        if "evaluation_role" in row:
            _require(row["evaluation_role"] == "exposed_development", "nondevelopment evaluation role")
        if "target_origin" in row:
            _require(row["target_origin"] == "synthetic_authored_unreviewed", "unsupported target origin")
        for name in ("id", "group_id"):
            _require(type(row[name]) is str and 0 < len(row[name]) <= 512 and row[name].strip(),
                     "bounded nonempty identity required")
        _require(row["id"] not in identities, "duplicate source ID")
        identities.add(row["id"])
        text = row["source_text"]
        _require(type(text) is str and text.strip() and len(text) <= 32768, "bounded original source required")
        _require(_text_hash(text) == row["source_sha256"], "source SHA256 mismatch")
        vector = row["embedding"]
        _require(type(vector) is list and len(vector) == 384, "exact native384 vector required")
        _require(all(type(value) in (int, float) and math.isfinite(value) for value in vector),
                 "finite numeric vector required")
        scale = max(abs(value) for value in vector)
        _require(scale > 0, "nonzero vector required")
        _require(_digest(vector) == row["embedding_sha256"], "embedding SHA256 mismatch")
        target = row["target"]
        _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
                 and len(target["rules"]) == 1, "single canonical authored Legal rule required")
        validated = CanonicalRule.from_dict(target["rules"][0]).to_dict()
        _require(_raw(validated) == _raw(target["rules"][0]), "target must retain canonical facet values")
        target_digest = _digest(target)
        if "target_sha256" in row:
            _require(row["target_sha256"] == target_digest, "target SHA256 mismatch")
        numeric_digest = _digest([float(value) if value else 0.0 for value in vector])
        for kind, key in (("source", row["source_sha256"]), ("numeric_vector", numeric_digest)):
            previous = source_targets.setdefault((kind, key), (row["group_id"], target_digest))
            _require(previous == (row["group_id"], target_digest), "conflicting source/vector group or target")
        scaled = [value / scale for value in vector]
        norm = math.sqrt(math.fsum(value * value for value in scaled))
        prepared.append({**deepcopy(row), "target_sha256": target_digest,
                         "normalized_source_sha256": _text_hash(_normalized_source(text)),
                         "numeric_embedding_sha256": numeric_digest,
                         "unit_vector": [value / norm for value in scaled]})
    return prepared


def _check_disjoint(training, development):
    for key in ("id", "group_id", "source_sha256", "normalized_source_sha256", "embedding_sha256",
                "numeric_embedding_sha256", "target_sha256"):
        _require(not {row[key] for row in training} & {row[key] for row in development},
                 "train/development leakage: " + key)


def _vocabulary(training):
    rules = [row["target"]["rules"][0] for row in training]
    return {name: sorted({rule[facet] for rule in rules if rule[facet]})
            for name, facet in (("actors", "actor"), ("actions", "action"), ("objects", "object"))} | {
        "qualifiers": sorted({value for rule in rules for facet in ("conditions", "exceptions", "temporal")
                              for value in rule[facet]})}


def _compile_sources(sources, vocabulary, deadline):
    """The generation boundary receives source-only rows and frozen train vocabulary."""
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalAtomVocabulary,
        CompilerRequest,
    )
    compiler = TypedDeonticCanonicalCompiler()
    results = []
    for source in sources:
        if time.perf_counter() >= deadline:
            break
        request = CompilerRequest(source_text=source["source_text"], request_id=source["id"],
                                  atom_vocabulary=CanonicalAtomVocabulary.from_dict(vocabulary))
        original_hash = _text_hash(source["source_text"])
        try:
            result = compiler.compile(request)
            _require(result.request_cid == request.request_cid, "compiler request binding changed")
            outcome = result.to_dict()
        except Exception as error:
            # Preserve current failure outcomes. A failed compiler has no candidate.
            outcome = {"status": "failed", "canonical_ir": None,
                       "request_cid": request.request_cid,
                       "error": {"exception_type": type(error).__name__, "message": str(error)[:2048]}}
        observed = _text_hash(request.source_text)
        _require(observed == original_hash, "compiler source binding changed")
        results.append({**outcome, "source_sha256_observed": observed})
    return results


def _facet_matches(candidate, reference):
    if not isinstance(candidate, dict) or not isinstance(candidate.get("rules"), list) or len(candidate["rules"]) != 1:
        return {name: False for name in FACETS}
    rule = candidate["rules"][0]
    return {name: isinstance(rule, dict) and name in rule
            and _raw(rule[name]) == _raw(reference["rules"][0][name]) for name in FACETS}


def run_alignment_baseline(config: dict, repository_root: Path | str, workspace_root: Path | str) -> dict:
    """Run B0/B1 on pinned exposed Legal development files without writing files.

    B1 retrieves training SOURCE vectors, not formal embeddings. References are
    used only after candidate production for explicitly authored diagnostics.
    No independent semantic or native-proof qualification can result.
    """
    started = time.perf_counter()
    _require(type(config) is dict and type(config.get("corpus")) is dict, "corpus configuration required")
    corpus = config["corpus"]
    required_corpus = {"train", "development", "dimension", "vector_space_id", "target_origin",
                       "evaluation_role", "max_rows"}
    optional_corpus = {"domain_id", "max_file_bytes", "provenance", "encoder_execution_authenticated",
                       "independent_source_review_available"}
    _require(required_corpus <= set(corpus) <= required_corpus | optional_corpus, "corpus configuration fields changed")
    _require(corpus["dimension"] == 384 and type(corpus["dimension"]) is int, "native384 dimension required")
    _require(corpus["vector_space_id"] == VECTOR_SPACE_ID, "native GTE-small vector identity required")
    _require(corpus["target_origin"] == "synthetic_authored_unreviewed", "unsupported target origin")
    _require(corpus["evaluation_role"] == "exposed_development", "exposed development required")
    _require(config.get("evaluation_role", "exposed_development") == "exposed_development", "nondevelopment study role")
    _require(corpus.get("domain_id", "legal_ir") == "legal_ir", "Legal source baseline required")
    _require(corpus.get("encoder_execution_authenticated", False) is False
             and corpus.get("independent_source_review_available", False) is False,
             "unavailable review/encoder evidence cannot be relabeled")
    _require(type(corpus["max_rows"]) is int and 1 <= corpus["max_rows"] <= 5000, "row bound required")
    max_bytes = corpus.get("max_file_bytes", MAX_FILE_BYTES)
    _require(type(max_bytes) is int and 1 <= max_bytes <= MAX_FILE_BYTES, "bounded file byte policy required")
    retrieval = config.get("retrieval")
    _require(type(retrieval) is dict and {"top_k"} <= set(retrieval) <= {"top_k", "kind"}, "closed retrieval configuration required")
    _require(retrieval.get("kind", "source_to_source_demonstrations") == "source_to_source_demonstrations", "source retrieval kind required")
    _require(type(retrieval["top_k"]) is int and 1 <= retrieval["top_k"] <= 50, "bounded top_k required")
    policy = config.get("resource_policy", {})
    _require(type(policy) is dict, "resource policy must be an object")
    for name in ("model_loads", "provider_calls", "prover_calls", "optimizer_steps"):
        _require(type(policy.get(name, 0)) is int and policy.get(name, 0) == 0, "forbidden resource policy: " + name)
    _require(policy.get("cpu_threads", 1) == 1, "single CPU thread required")
    seconds = policy.get("max_baseline_seconds", 120)
    _require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 120,
             "bounded baseline deadline required")
    deadline = started + seconds
    roots = tuple(dict.fromkeys((Path(workspace_root).resolve(), Path(repository_root).resolve())))
    train_path, train_rows = _load_file(corpus["train"], roots, "train.json", max_bytes)
    development_path, development_rows = _load_file(corpus["development"], roots, "validation.json", max_bytes)
    training = _validated_rows(train_rows, "train", corpus["max_rows"])
    development = _validated_rows(development_rows, "validation", corpus["max_rows"])
    _check_disjoint(training, development)
    vocabulary = _vocabulary(training)
    source_inputs = [{key: row[key] for key in ("id", "source_text")} for row in development]
    tick = time.perf_counter()
    outcomes = _compile_sources(source_inputs, deepcopy(vocabulary), deadline)
    b0_seconds = time.perf_counter() - tick
    _require(len(outcomes) <= len(development), "compiler outcome count changed")
    b0_rows = []
    for query, outcome in zip(development, outcomes, strict=False):
        _require(outcome.get("source_sha256_observed") == query["source_sha256"], "compiler source binding changed")
        candidate = outcome.get("canonical_ir")
        matches = _facet_matches(candidate, query["target"])
        b0_rows.append({"id": query["id"], "source_sha256": query["source_sha256"],
                        "reference_target_sha256": query["target_sha256"], "compiler_outcome": outcome,
                        "exact_authored_target": candidate is not None and _raw(candidate) == _raw(query["target"]),
                        "authored_facet_matches": matches})
    tick = time.perf_counter()
    b1_rows = []
    for query in development:
        if time.perf_counter() >= deadline:
            break
        ranking = sorted(((math.fsum(a * b for a, b in zip(query["unit_vector"], row["unit_vector"], strict=True)), row)
                          for row in training), key=lambda item: (-item[0], item[1]["id"]))[:retrieval["top_k"]]
        retrieved = [{"rank": rank, "train_id": row["id"], "train_group_id": row["group_id"],
                      "paired_target_ref": {"path": str(train_path), "id": row["id"], "sha256": row["target_sha256"]},
                      "cosine_similarity": score,
                      "authored_facet_matches": _facet_matches(row["target"], query["target"])}
                     for rank, (score, row) in enumerate(ranking, 1)]
        b1_rows.append({"id": query["id"], "source_sha256": query["source_sha256"],
                        "retrieved": retrieved,
                        "nearest_target_copy_exact_authored_target": _raw(ranking[0][1]["target"]) == _raw(query["target"]),
                        "best_top_k_authored_facet_fraction": max(sum(item["authored_facet_matches"].values()) / len(FACETS)
                                                                  for item in retrieved),
                        "best_top_k_authored_core_facet_fraction": max(
                            sum(item["authored_facet_matches"][name] for name in CORE_FACETS) / len(CORE_FACETS)
                            for item in retrieved)})
    b1_seconds = time.perf_counter() - tick
    # Recheck file bindings after generation to detect changed source artifacts.
    _load_file(corpus["train"], roots, "train.json", max_bytes)
    _load_file(corpus["development"], roots, "validation.json", max_bytes)
    count = len(development)
    completed = len(b0_rows) == count and len(b1_rows) == count
    compiler_path = Path(__file__).parents[2] / "legal_ir/canonical_compiler.py"
    return {"schema": SCHEMA, "status": "completed" if completed else "partial_timeout",
            "deadline_policy": "cooperative_before_each_case; synchronous compiler calls are not preempted",
            "evaluation_role": "exposed_development",
            "target_origin": "synthetic_authored_unreviewed", "corpus": deepcopy(corpus),
            "training_rows": len(training), "development_rows": count,
            "training_groups": len({row["group_id"] for row in training}),
            "development_groups": len({row["group_id"] for row in development}),
            "train_only_atom_vocabulary": vocabulary, "train_only_atom_vocabulary_sha256": _digest(vocabulary),
            "B0": {"arm": "current_deterministic_source_only_compiler", "elapsed_seconds": b0_seconds,
                   "compiler_source_sha256": hashlib.sha256(compiler_path.read_bytes()).hexdigest(),
                   "completed_rows": len(b0_rows), "pending_ids": [row["id"] for row in development[len(b0_rows):]],
                   "status_counts": dict(Counter(str(row["compiler_outcome"]["status"]) for row in b0_rows)),
                   "exact_authored_targets": sum(row["exact_authored_target"] for row in b0_rows),
                   "rate_denominator": "completed_cases_only",
                   "exact_authored_target_rate": sum(row["exact_authored_target"] for row in b0_rows) / len(b0_rows) if b0_rows else None,
                   "authored_facet_match_rates": {name: sum(row["authored_facet_matches"][name] for row in b0_rows) / len(b0_rows) if b0_rows else None
                                                 for name in FACETS}, "rows": b0_rows},
            "B1": {"arm": "cached_native384_source_to_source_train_only_retrieval", "top_k": retrieval["top_k"],
                   "elapsed_seconds": b1_seconds, "diagnostic_scope": "authored_facets_and_nearest_target_copy_only",
                   "completed_rows": len(b1_rows), "pending_ids": [row["id"] for row in development[len(b1_rows):]],
                   "nearest_target_copy_exact_authored_targets": sum(row["nearest_target_copy_exact_authored_target"] for row in b1_rows),
                   "rate_denominator": "completed_cases_only",
                   "mean_best_top_k_authored_facet_fraction": math.fsum(row["best_top_k_authored_facet_fraction"] for row in b1_rows) / len(b1_rows) if b1_rows else None,
                   "mean_best_top_k_authored_core_facet_fraction": math.fsum(
                       row["best_top_k_authored_core_facet_fraction"] for row in b1_rows) / len(b1_rows) if b1_rows else None,
                   "nearest_authored_facet_match_rates": {
                       name: sum(row["retrieved"][0]["authored_facet_matches"][name] for row in b1_rows) / len(b1_rows)
                       if b1_rows else None for name in FACETS},
                   "diagnostic_limitations": [
                       "No complete development target occurs in training; exact nearest-target copy cannot succeed on this panel.",
                       "Empty qualifier facets can inflate the seven-facet average; core-facet and per-facet diagnostics are separate.",
                       "Rankings alone do not measure downstream retrieval-conditioned generation or independent source fidelity.",
                   ],
                   "counterpart_recall": {"status": "not_applicable", "reason": "development targets are excluded from training"},
                   "formal_target_embeddings_available": False, "rows": b1_rows},
            "primary_metrics": {"independently_adjudicated_fidelity": {"status": "unavailable", "reason": "no independent source/target adjudication"},
                                "native_proof_coverage": {"status": "unavailable", "reason": "no native proof backend invoked"}},
            "elapsed_seconds": time.perf_counter() - started,
            "encoder_execution_authenticated": False, "model_calls": 0, "backend_calls": 0,
            "downloads": 0, "training_executed": False, "proof_authority": False,
            "source_semantics_verified": False, "qualified": False}


__all__ = ["run_alignment_baseline"]
