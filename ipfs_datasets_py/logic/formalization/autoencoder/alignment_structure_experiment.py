"""Source-pinned structural diagnostics and blank richer review preparation.

References are used for posthoc formal-representation assays, never to generate
query declarations. The emitted-candidate assay consumes existing pinned parser
receipts; this experiment does not generate new candidates or fit any weights.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from .alignment_baseline import _digest, _raw
from .alignment_experiment import _write_json
from .alignment_parser_experiment import score_explicit_reference, validate_explicit_construction
from .alignment_projection import _validate_codec, encode_legal_target
from .alignment_retrieval_experiment import _read_bound_json, _verify_origins
from .alignment_richer_evaluation import _ir_diagnostics
from .alignment_richer_experiment import _summarize_rows, representation_collision_assay
from .alignment_richer_panel import richer_training_vocabulary, validate_alignment_richer_panel
from .alignment_richer_review import prepare_richer_review, validate_richer_review_bundle
from .alignment_structure import (
    encode_structural_features,
    prepare_structural_features,
    restore_structural_ir,
)
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
)

CONFIG_SCHEMA = "alignment-structure-experiment-config/v1"
REPORT_SCHEMA = "alignment-structure-experiment-report/v1"
HASH_VARIANTS = ((2048, 0), (2048, 1), (4096, 0), (4096, 1))
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/features.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure_experiment.py",
    "scripts/ops/legal_ir/run_alignment_structure_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_structure_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    settings = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(type(settings) is dict and set(settings) == {"schema", "study_id", "parser_report", "max_seconds"}
             and settings["schema"] == CONFIG_SCHEMA, "closed structural experiment config required")
    _require(settings["study_id"] == "autoformalization-structure-development-v1", "exposed development identity required")
    binding = settings["parser_report"]
    _require(type(binding) is dict and set(binding) == {"path", "sha256"}
             and type(binding["path"]) is str and 0 < len(binding["path"]) <= 4096
             and type(binding["sha256"]) is str and len(binding["sha256"]) == 64
             and all(char in "0123456789abcdef" for char in binding["sha256"]), "bound parser report required")
    seconds = settings["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 120 and math.isfinite(seconds), "invalid max_seconds")
    return settings, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _collisions(buckets):
    groups = [{"coordinate_sha256": coordinate, "distinct_targets": len(targets),
               "targets": [{"target_sha256": target, "row_ids": ids} for target, ids in sorted(targets.items())]}
              for coordinate, targets in sorted(buckets.items()) if len(targets) > 1]
    return {"distinct_vectors": len(buckets), "collision_groups": len(groups),
            "distinct_target_collision_pairs": sum(group["distinct_targets"] * (group["distinct_targets"] - 1) // 2
                                                   for group in groups), "collisions": groups}


def structural_collision_assay(rows):
    """Exact named counts versus fixed hashed counts, with cross-row traces.

    A token-coordinate collision is not necessarily an equal target vector.
    Both are measured, including shared-token collisions across declarations.
    Metadata identifiers are excluded from every compared coordinate signature.
    """
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 72, "bounded structural assay rows required")
    exact_buckets, records, identities = defaultdict(dict), [], set()
    vector_buckets = {variant: defaultdict(dict) for variant in HASH_VARIANTS}
    corpus_tokens = {variant: {} for variant in HASH_VARIANTS}
    within_pairs = Counter()
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "target"} and type(row["id"]) is str
                 and 0 < len(row["id"]) <= 256 and row["id"] not in identities, "unique closed structural assay rows required")
        identities.add(row["id"])
        features = prepare_structural_features(row["target"])
        restored = restore_structural_ir(features)
        target_hash = features["declaration_sha256"]
        named_counts = [{"name": item["name"], "count": item["count"]} for item in features["feature_dictionary"]]
        signature = _digest(named_counts)
        exact_buckets[signature].setdefault(target_hash, []).append(row["id"])
        hashes = {}
        for dimension, seed in HASH_VARIANTS:
            variant = (dimension, seed)
            encoded = encode_structural_features(features, dimension=dimension, seed=seed)
            hashes[f"d{dimension}-s{seed}"] = encoded
            vector_buckets[variant][encoded["coordinate_values_sha256"]].setdefault(target_hash, []).append(row["id"])
            within_pairs[variant] += encoded["distinct_feature_collision_pairs"]
            for token in encoded["token_trace"]:
                name, index = token["name"], token["index"]
                _require(name not in corpus_tokens[variant] or corpus_tokens[variant][name] == index,
                         "coordinate recipe changed across declarations")
                corpus_tokens[variant][name] = index
        records.append({"id": row["id"], "target_sha256": target_hash, "features": features,
                        "named_count_sha256": signature, "exact_owner_restoration": restored == features["canonical_ir"],
                        "hashed_counts": hashes})
    hashed_summaries = {}
    for dimension, seed in HASH_VARIANTS:
        variant = (dimension, seed)
        buckets = defaultdict(list)
        for name, index in sorted(corpus_tokens[variant].items()):
            buckets[index].append(name)
        collisions = [{"index": index, "distinct_features": len(names), "feature_names": names}
                      for index, names in sorted(buckets.items()) if len(names) > 1]
        hashed_summaries[f"d{dimension}-s{seed}"] = {
            "dimension": dimension, "seed": seed, **_collisions(vector_buckets[variant]),
            "per_row_token_collision_pairs_sum": within_pairs[variant],
            "unique_corpus_tokens": len(corpus_tokens[variant]), "occupied_corpus_coordinates": len(buckets),
            "corpus_token_collision_buckets": collisions,
            "corpus_distinct_token_collision_pairs": sum(item["distinct_features"] * (item["distinct_features"] - 1) // 2
                                                         for item in collisions),
            "lossless": False, "trained_embedding": False}
    return {"schema": "alignment-structural-collision-assay/v1", "rows": len(records),
            "distinct_normalized_target_payloads": len({record["target_sha256"] for record in records}),
            "exact_owner_restorations": sum(record["exact_owner_restoration"] for record in records),
            "exact_named_counts": _collisions(exact_buckets), "hashed_count_variants": hashed_summaries,
            "records": records, "vocabulary_fit": False, "source_semantics_verified": False,
            "binder_semantics_inferred": False, "proof_authority": False, "qualified": False}


def structural_challenge_rows():
    """Six manually authored declarations; no text/generation/evaluation gold."""
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    def rule(condition, exception="storm", actor="clerk"):
        return {"modality": "O", "actor": actor, "action": "notify", "object": "applicant",
                "conditions": [condition], "exceptions": [exception], "temporal": ["within_48_hours"]}

    declarations = (
        ("unknown-identity-a", [rule("unseen_red")]),
        ("unknown-identity-b", [rule("unseen_blue")]),
        ("same-core-coassociation-a", [rule("red", "storm"), rule("blue", "flood")]),
        ("same-core-coassociation-b", [rule("red", "flood"), rule("blue", "storm")]),
        ("actor-association-a", [rule("red", actor="clerk"), rule("blue", actor="custodian")]),
        ("actor-association-b", [rule("blue", actor="clerk"), rule("red", actor="custodian")]),
    )
    return [{"id": identity, "target": CanonicalRoundTripIR.from_dict({"rules": rules}).to_dict()}
            for identity, rules in declarations]


def challenge_pair_diagnostics(rows, codecs):
    by_id = {row["id"]: row["target"] for row in rows}
    results = []
    for prefix in ("unknown-identity", "same-core-coassociation", "actor-association"):
        left, right = by_id[prefix + "-a"], by_id[prefix + "-b"]
        features = [prepare_structural_features(target) for target in (left, right)]

        def bag(record, kind):
            return {item["name"]: item["count"] for item in record["feature_dictionary"]
                    if item["descriptor"]["kind"] == kind}

        old = {}
        for name, codec in codecs.items():
            admitted = len(left["rules"]) == len(right["rules"]) == 1
            old[name] = {"status": "executed" if admitted else "not_applicable_single_rule_codec",
                         "same_vector": encode_legal_target(left, codec) == encode_legal_target(right, codec) if admitted else None,
                         "multi_rule_pooling_invented": False}
        results.append({"pair_id": prefix, "left_id": prefix + "-a", "right_id": prefix + "-b",
                        "same_typed_atom_bag": bag(features[0], "typed_atom") == bag(features[1], "typed_atom"),
                        "same_core_qualifier_bag": bag(features[0], "core_qualifier") == bag(features[1], "core_qualifier"),
                        "same_complete_rule_bag": bag(features[0], "complete_rule") == bag(features[1], "complete_rule"),
                        "existing_ir_diagnostics": _ir_diagnostics(left, right), "legacy_codecs": old,
                        "source_fidelity_established": False, "qualified": False})
    return results


def _source_bindings(repository, prior):
    bindings = [_observed_binding(repository, {"path": item["path"], "sha256": item["sha256"]})
                for item in prior["source_bindings"]]
    for relative in _SOURCE_FILES:
        raw = _bounded_bytes(repository / relative, 1_000_000)
        bindings.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    _verify_origins(repository, bindings)
    return bindings


def _deadline(deadline):
    _require(time.perf_counter() <= deadline, "cooperative structural experiment deadline exceeded")


def run_structure_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_structure_config(config_path)
    deadline = started + settings["max_seconds"]
    _, prior = _read_bound_json(workspace, settings["parser_report"])
    _require(prior.get("schema") == "alignment-parser-experiment-report/v1" and prior.get("status") == "completed"
             and prior["report_sha256"] == _digest({key: value for key, value in prior.items() if key != "report_sha256"}),
             "completed content-bound parser report required")
    _require(prior["evaluation_role"] == "exposed_development" and prior["target_origin"] == "synthetic_authored_unreviewed"
             and prior["development_used_to_design_grammar"] is True
             and all(prior[name] is False for name in ("qualified", "production_admitted", "sealed_final_test_accessed",
                 "original_validation_accessed", "development_used_in_vocabulary_fit", "query_targets_used_in_construction")),
             "predecessor scope differs")
    bindings = _source_bindings(repository, prior)
    protocols = [_observed_binding(workspace, {"path": item["path"], "sha256": item["sha256"]})
                 for item in prior["protected_protocol_bindings"]]
    _, panel = _read_bound_json(workspace, prior["panel_binding"])
    _, saved = _read_bound_json(workspace, prior["construction_binding"])
    _, legacy = _read_bound_json(workspace, prior["representation_assay_binding"])
    validate_alignment_richer_panel(panel)
    vocabulary = richer_training_vocabulary(panel)
    _require(_raw(vocabulary.to_dict()) == _raw(prior["training_vocabulary"])
             and _digest(vocabulary.to_dict()) == prior["training_vocabulary_sha256"], "frozen training vocabulary differs")
    _require(saved.get("schema") == "alignment-parser-comparisons/v1" and len(saved["rows"]) == len(panel["rows"]),
             "frozen parser row accounting differs")
    candidates = []
    for row, receipt in zip(panel["rows"], saved["rows"], strict=True):
        _deadline(deadline)
        _require(all(_raw(row[name]) == _raw(receipt[name]) for name in ("id", "group_id", "split", "row_kind", "input_sha256"))
                 and _raw(row["target"]) == _raw(receipt["authored_target"]), "panel and parser receipt identity differ")
        construction = validate_explicit_construction(receipt["construction"])
        _require(construction["request"]["source_text"] == row["source_text"]
                 and construction["context"]["text"] == row["context"]["text"]
                 and construction["request"]["atom_vocabulary"] == vocabulary.to_dict(), "parser input or training vocabulary differs")
        _require(_raw(score_explicit_reference(construction, row["target"])) == _raw(receipt["posthoc_authored_score"]),
                 "posthoc parser score differs")
        if construction["canonical_ir"] is not None:
            candidates.append({"id": row["id"], "target": construction["canonical_ir"]})
    _require(_raw({"all": _summarize_rows(saved["rows"]),
                   "train": _summarize_rows([row for row in saved["rows"] if row["split"] == "train"]),
                   "development": _summarize_rows([row for row in saved["rows"] if row["split"] == "validation"])})
             == _raw(prior["summaries"]), "parser summary differs from receipts")
    positives = [row for row in panel["rows"] if row["row_kind"] == "positive"]
    _require(set(legacy) == {"original_training_codec", "richer_training_codec"}, "both frozen feature codecs required")
    codecs = {}
    for name, entry in legacy.items():
        codec = entry["codec"]
        _validate_codec(codec)
        codecs[name] = codec
        for scope, rows in (("all_positive_rows", positives), ("training_rows", [r for r in positives if r["split"] == "train"]),
                            ("development_rows", [r for r in positives if r["split"] == "validation"])):
            _require(_raw(representation_collision_assay(rows, codec)) == _raw(entry[scope]), "frozen flat-codec assay differs")
    challenges = structural_challenge_rows()
    assays = {
        "authored_positive_references": {"input_role": "posthoc_synthetic_authored_unreviewed_reference",
            "query_generation_executed": False, **structural_collision_assay([{"id": row["id"], "target": row["target"]} for row in positives])},
        "emitted_candidates": {"input_role": "pinned_parser_generated_declaration",
            "query_reference_supplied_to_generation": False, "query_generation_executed": False, **structural_collision_assay(candidates)},
        "structural_challenges": {"input_role": "manual_source_free_adversarial_declarations",
            "training_or_benchmark_gold": False, **structural_collision_assay(challenges)},
        "challenge_pairs": challenge_pair_diagnostics(challenges, codecs),
    }
    review = prepare_richer_review(panel, {"evaluation_role": "exposed_development", "parser_report": settings["parser_report"],
                                         "panel": prior["panel_binding"], "sources": bindings})
    review_validation = validate_richer_review_bundle(review)
    _deadline(deadline)
    _require(_raw(bindings) == _raw(_source_bindings(repository, prior)), "executing source bytes changed during run")
    _require(config_binding["sha256"] == load_structure_config(config_path)[1]["sha256"], "configuration changed during run")
    _read_bound_json(workspace, settings["parser_report"])
    for key in ("panel_binding", "construction_binding", "representation_assay_binding"):
        _read_bound_json(workspace, prior[key])
    for item in prior["protected_protocol_bindings"]:
        _observed_binding(workspace, {"path": item["path"], "sha256": item["sha256"]})
    output.mkdir(parents=True, exist_ok=False)
    assay_binding = _write_json(output / "representation_assays.json", assays)
    review_bindings = {}
    for key, filename in (("reviewer_payload", "reviewer_items.json"), ("reviewer_manifest", "reviewer_manifest.json"),
                          ("organizer_payload", "organizer_private.json"), ("organizer_manifest", "organizer_manifest_private.json")):
        review_bindings[key] = _write_json(output / filename, review[key])
    review_bindings["full_bundle_private"] = _write_json(output / "review_bundle_private.json", review)
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "status": "completed",
              "configuration": settings, "configuration_binding": config_binding, "predecessor_binding": settings["parser_report"],
              "source_bindings": bindings, "protected_protocol_bindings": protocols,
              "panel_binding": prior["panel_binding"], "parser_construction_binding": prior["construction_binding"],
              "legacy_representation_assay_binding": prior["representation_assay_binding"], "representation_assay_binding": assay_binding,
              "parser_receipts_validated": len(saved["rows"]), "parser_summaries": prior["summaries"],
              "legacy_codecs": {name: {"dimension": codec["feature_dimension"], "feature_space_id": codec["feature_space_id"],
                  "all_positive_rows": legacy[name]["all_positive_rows"]} for name, codec in codecs.items()},
              "structural_summaries": {name: {key: value for key, value in assay.items() if key != "records"}
                  for name, assay in assays.items() if name != "challenge_pairs"}, "challenge_pairs": assays["challenge_pairs"],
              "review_bindings": review_bindings, "review_preparation_validation": review_validation,
              "review_distribution": "send_only_reviewer_payload_and_reviewer_manifest; private_files_are_audience_labels_not_access_controls",
              "new_review_items_pending": review_validation["item_count"], "completed_independent_reviews": 0,
              "original_40_review_bundle_reusable": False, "review_admission_executed": False,
              "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
              "development_exposed_in_prior_grammar_design": True, "vocabulary_fit": False,
              "query_generation_executed": False, "query_targets_used_in_construction": False,
              "new_source_embeddings_computed": 0, "source_input_dimensions": [8, 384, 768],
              "source_encoder_lanes_exercised": False, "leanstral_hidden_states_extracted": False,
              "formal_hash_dimensions": [2048, 4096], "model_training_executed": False,
              "sealed_final_test_accessed": False, "original_validation_accessed": False,
              "complete_dependency_manifest": False, "dependency_binding_scope": "listed_study_and_core_source_files_only",
              "source_fidelity_established": False, "proof_authority": False, "qualified": False, "production_admitted": False,
              "primary_fidelity": {"status": "unavailable_independent_review", "value": None},
              "native_useful_proof_coverage": {"status": "unrun", "value": None},
              "resource_scope": {"model_loads": 0, "provider_calls": 0, "prover_calls": 0, "optimizer_steps": 0,
                  "deadline_kind": "cooperative_between_bounded_assays_no_preemption"},
              "limitations": ["Exact features restore normalized seven-facet declarations, not source meaning or arbitrary logical binders.",
                  "Opaque atom labels and positional connectives do not infer inner qualifier semantics.",
                  "Finite hashed coordinates are lossy; measured token and whole-vector collisions are different outcomes.",
                  "Cryptographic descriptor identities rely on SHA256; observed noncollisions are not an injectivity guarantee.",
                  "Formal representations of references are posthoc diagnostics; no source generation gain was measured.",
                  "Richer review is blank preparation with zero actual authenticated submissions; a future admission interface is required.",
                  "Independent 8D, 384D, 768D and Leanstral encoder/prover lanes remain unrun in this stage."],
              "elapsed_seconds": time.perf_counter() - started}
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    persisted = json.loads(_bounded_bytes(output / "report.json", 32_000_000),
                           object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(_raw(persisted) == _raw(report), "persisted structural report differs")
    return report
