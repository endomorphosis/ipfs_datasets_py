"""Authored richer-rule construction and train-only representation diagnostics.

This experiment loads no encoders, projection weights, solvers, or reviewed
evaluation data. References enter only the vocabulary fit on training rows and
post-construction diagnostics. Actual native proof and source fidelity remain
separate, unavailable outcomes.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from .alignment_baseline import _digest, _load_file, _validated_rows
from .alignment_experiment import _write_json
from .alignment_projection import _validate_codec, encode_legal_target, fit_legal_feature_codec
from .alignment_retrieval_experiment import _artifact_path, _verify_origins
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
    load_alignment_config,
)

CONFIG_SCHEMA = "alignment-richer-experiment-config/v1"
REPORT_SCHEMA = "alignment-richer-experiment-report/v1"
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_evaluation.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_projection.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_baseline.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_study.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval_experiment.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py",
    "ipfs_datasets_py/logic/bridge/canonical.py",
    "ipfs_datasets_py/utils/cid_utils.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "scripts/ops/legal_ir/run_alignment_richer_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_richer_config(path):
    """Bind bounded, strict configuration bytes without reading any rows."""
    raw = _bounded_bytes(Path(path), 262_144)
    settings = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(type(settings) is dict and set(settings) == {"schema", "study_id", "study_config", "max_seconds"}
             and settings["schema"] == CONFIG_SCHEMA, "closed richer experiment config required")
    _require(settings["study_id"] == "autoformalization-richer-development-v1", "exposed development identity required")
    binding = settings["study_config"]
    _require(type(binding) is dict and set(binding) == {"path", "sha256"}
             and type(binding["path"]) is str and 0 < len(binding["path"]) <= 4096
             and type(binding["sha256"]) is str and len(binding["sha256"]) == 64
             and all(char in "0123456789abcdef" for char in binding["sha256"]), "bound study config required")
    seconds = settings["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 120 and math.isfinite(seconds), "invalid max_seconds")
    return settings, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def representation_collision_assay(rows, codec):
    """Posthoc exact collisions of distinct payloads, without training a model.

    Equal feature vectors must remain equal through any deterministic head.
    Distinct vectors need not remain distinct after projection. This diagnoses
    the codec only, not encoder performance or a semantics-preserving AST.
    """
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 5000, "bounded target rows required")
    _validate_codec(codec)
    buckets, records, identities = defaultdict(dict), [], set()
    target_rules = {}
    unknown_counts = {block["facet"]: 0 for block in codec["blocks"]}
    for row in rows:
        _require(type(row) is dict and type(row.get("id")) is str and row["id"] not in identities,
                 "unique row identities required")
        identities.add(row["id"])
        target = row["target"]
        features = encode_legal_target(target, codec)
        target_hash, feature_hash = _digest(target), _digest(features)
        buckets[tuple(features)].setdefault(target_hash, []).append(row["id"])
        rule = target["rules"][0]
        target_rules[target_hash] = rule
        unknown = {}
        for block in codec["blocks"]:
            values = [rule[block["facet"]]] if block["kind"] == "categorical" else rule[block["facet"]]
            count = sum(value not in block["vocabulary"] for value in values)
            unknown[block["facet"]] = count
            unknown_counts[block["facet"]] += count
        records.append({"id": row["id"], "target_sha256": target_hash,
                        "feature_sha256": feature_hash, "unknown_atom_counts": unknown})
    collisions = []
    for features, targets in buckets.items():
        if len(targets) < 2:
            continue
        core_counts = defaultdict(int)
        for target_hash in targets:
            core_counts[_digest({facet: target_rules[target_hash][facet]
                                 for facet in ("modality", "actor", "action", "object")})] += 1
        collisions.append({"feature_sha256": _digest(list(features)), "distinct_targets": len(targets),
                           "same_core_distinct_target_pairs": sum(count * (count - 1) // 2 for count in core_counts.values()),
                           "differing_facets": [block["facet"] for block in codec["blocks"]
                              if len({_digest(target_rules[target][block["facet"]]) for target in targets}) > 1],
                           "targets": [{"target_sha256": target, "row_ids": ids} for target, ids in sorted(targets.items())]})
    collisions.sort(key=lambda item: item["feature_sha256"])
    return {"schema": "alignment-representation-collision-assay/v1", "rows": len(records),
            "distinct_target_payloads": len({record["target_sha256"] for record in records}),
            "distinct_feature_vectors": len(buckets), "collision_groups": len(collisions),
            "distinct_target_collision_pairs": sum(item["distinct_targets"] * (item["distinct_targets"] - 1) // 2
                                                   for item in collisions),
            "same_core_distinct_target_collision_pairs": sum(item["same_core_distinct_target_pairs"] for item in collisions),
            "rows_in_collision_groups": sum(len(target["row_ids"]) for item in collisions for target in item["targets"]),
            "unknown_atom_counts": unknown_counts, "codec_space_id": codec["feature_space_id"],
            "feature_dimension": codec["feature_dimension"], "collisions": collisions, "row_bindings": records,
            "evaluation_role": "posthoc_authored_reference_diagnostic", "projection_weights_loaded": False,
            "qualified": False, "binder_or_scope_semantics_evaluated": False}


def _source_bindings(repository):
    observed = []
    for relative in _SOURCE_FILES:
        raw = _bounded_bytes(repository / relative, 1_000_000)
        observed.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    _verify_origins(repository, observed)
    return observed


def _deadline(deadline):
    _require(time.perf_counter() <= deadline, "cooperative richer experiment deadline exceeded")


def construct_panel_sources(panel, vocabulary, deadline):
    """Construction boundary passes text and explicit context, never targets."""
    from .alignment_richer_evaluation import construct_source
    from .alignment_richer_panel import richer_row_input

    results = []
    for row in panel["rows"]:
        _deadline(deadline)
        needs_context = row["context"]["role"] != "none_required"
        source_input = richer_row_input(row, mode="source_with_context" if needs_context else "source_only")
        # Row expectation, reference facets, and reference hashes never enter
        # the compiler wrapper. Context availability follows the input role.
        premises = ({"id": row["id"] + ":context", "text": row["context"]["text"]},) if needs_context else ()
        result = construct_source(source_input["source_text"], vocabulary, request_id=row["id"],
                                  context_premises=premises, requires_context_resolution=needs_context)
        results.append({"id": row["id"], "input_sha256": row["input_sha256"], "construction": result})
    _deadline(deadline)
    return results


def _summarize_rows(rows):
    positives = [row for row in rows if row["row_kind"] == "positive"]
    negatives = [row for row in rows if row["row_kind"] in ("unsupported", "ambiguous")]
    contextual = [row for row in rows if row["row_kind"] == "explicit_context"]
    status_counts = defaultdict(int)
    for row in rows:
        status_counts[row["construction"]["construction_status"]] += 1
    qualifier_counts = {}
    for scope in ("typed_qualifier_counts", "unscoped_qualifier_presence"):
        qualifier_counts[scope] = {}
        for facet in ("conditions", "exceptions", "temporal"):
            counts = {name: sum(row["posthoc_authored_score"][scope][facet][name] for row in positives)
                      for name in ("tp", "fp", "fn")}
            counts.update(precision=counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None,
                          recall=counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None)
            qualifier_counts[scope][facet] = counts
    return {"rows": len(rows), "construction_status_counts": dict(sorted(status_counts.items())),
            "positive_rows": len(positives),
            "positive_ir_emitted": sum(row["construction"]["canonical_ir"] is not None for row in positives),
            "positive_exact_authored_ir": sum(row["construction"]["canonical_ir"] == row["authored_target"] for row in positives),
            "positive_exact_candidate_roundtrips": sum(row["construction"]["roundtrip"]["exact_ir"] is True for row in positives),
            "negative_rows": len(negatives),
            "negative_ir_emissions": sum(row["construction"]["canonical_ir"] is not None for row in negatives),
            "negative_no_ir": sum(row["construction"]["canonical_ir"] is None for row in negatives),
            "explicit_context_rows": len(contextual),
            "explicit_context_ir_emissions": sum(row["construction"]["canonical_ir"] is not None for row in contextual),
            "positive_qualifier_counts": qualifier_counts,
            "positive_cross_facet_migrations": sum(len(row["posthoc_authored_score"]["cross_facet_migrations"]) for row in positives),
            "scoring_role": "synthetic_authored_unreviewed_posthoc", "qualified": False}


def run_richer_experiment(config_path, repository_root, workspace_root, output_directory):
    """Execute real bounded construction checks and publish fresh evidence."""
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_richer_config(config_path)
    deadline = started + settings["max_seconds"]
    source_bindings = _source_bindings(repository)
    base_path = _artifact_path(workspace, settings["study_config"])
    base, base_binding = load_alignment_config(base_path, expected_sha256=settings["study_config"]["sha256"])
    protocol_bindings = [_observed_binding(workspace, binding) for binding in base["protected_protocols"]]
    # Only the original public training split is opened for codec reconstruction.
    # Its validation split and every sealed/test partition remain unopened.
    corpus = base["corpus"]
    _, old_raw = _load_file(corpus["train"], (workspace,), "train.json", corpus["max_file_bytes"])
    old_train = _validated_rows(old_raw, "train", corpus["max_rows"])
    old_codec = fit_legal_feature_codec([row["target"] for row in old_train])
    from .alignment_richer_evaluation import score_authored_reference
    from .alignment_richer_panel import (
        build_alignment_richer_panel,
        richer_training_vocabulary,
        validate_alignment_richer_panel,
    )

    panel = build_alignment_richer_panel()
    panel_validation = validate_alignment_richer_panel(panel)
    vocabulary = richer_training_vocabulary(panel)
    positive_rows = [row for row in panel["rows"] if row["row_kind"] == "positive"]
    training = [row for row in positive_rows if row["split"] == "train"]
    development = [row for row in positive_rows if row["split"] == "validation"]
    richer_codec = fit_legal_feature_codec([row["target"] for row in training])
    constructions = construct_panel_sources(panel, vocabulary, deadline)
    scored = []
    for row, construction in zip(panel["rows"], constructions, strict=True):
        _require(row["id"] == construction["id"], "construction row accounting differs")
        scored.append({**construction, "group_id": row["group_id"], "split": row["split"],
                       "row_kind": row["row_kind"], "authored_target": row["target"],
                       "posthoc_authored_score": score_authored_reference(construction["construction"], row["target"])})
    assays = {}
    for name, codec in (("original_training_codec", old_codec), ("richer_training_codec", richer_codec)):
        assays[name] = {"codec": codec, "all_positive_rows": representation_collision_assay(positive_rows, codec),
                        "training_rows": representation_collision_assay(training, codec),
                        "development_rows": representation_collision_assay(development, codec)}
    _deadline(deadline)
    _require(source_bindings == _source_bindings(repository), "executing source bytes changed during run")
    _require(config_binding["sha256"] == load_richer_config(config_path)[1]["sha256"], "configuration changed during run")
    load_alignment_config(base_path, expected_sha256=settings["study_config"]["sha256"])
    for binding in base["protected_protocols"]:
        _observed_binding(workspace, binding)
    _load_file(corpus["train"], (workspace,), "train.json", corpus["max_file_bytes"])
    output.mkdir(parents=True, exist_ok=False)
    panel_binding = _write_json(output / "panel.json", panel)
    result_binding = _write_json(output / "constructions.json", {"schema": "alignment-richer-constructions/v1", "rows": scored})
    assay_binding = _write_json(output / "representation_assays.json", assays)
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "status": "completed",
              "configuration": settings, "configuration_binding": config_binding,
              "base_configuration_binding": base_binding, "source_bindings": source_bindings,
              "protected_protocol_bindings": protocol_bindings, "original_training_binding": corpus["train"],
              "original_training_rows": len(old_train), "panel_binding": panel_binding,
              "construction_binding": result_binding, "representation_assay_binding": assay_binding,
              "panel_validation": panel_validation, "training_vocabulary": vocabulary.to_dict(),
              "training_vocabulary_sha256": _digest(vocabulary.to_dict()),
              "summaries": {"all": _summarize_rows(scored),
                            "train": _summarize_rows([row for row in scored if row["split"] == "train"]),
                            "development": _summarize_rows([row for row in scored if row["split"] == "validation"])},
              "representation_summaries": {name: {"feature_dimension": assay["codec"]["feature_dimension"],
                  **{split: {key: value for key, value in assay[split].items() if key not in ("collisions", "row_bindings")}
                     for split in ("all_positive_rows", "training_rows", "development_rows")}}
                  for name, assay in assays.items()},
              "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
              "complete_dependency_manifest": False, "dependency_binding_scope": "listed_study_and_core_source_files_only",
              "development_used_in_fit": False, "query_targets_used_in_construction": False,
              "sealed_final_test_accessed": False, "original_validation_accessed": False,
              "qualified": False, "production_admitted": False,
              "primary_fidelity": {"status": "unavailable_independent_review", "value": None},
              "native_useful_proof_coverage": {"status": "unrun", "value": None},
              "resource_scope": {"model_loads": 0, "provider_calls": 0, "prover_calls": 0,
                                 "optimizer_steps": 0, "model_embeddings_computed": 0,
                                 "deadline_kind": "cooperative_between_rows_no_preemption"},
              "limitations": ["Manual fixture references are regression labels, not independent source fidelity evidence.",
                              "Roundtrip equality tests candidate preservation, not fidelity to its original source.",
                              "Flat qualifier atoms do not bind quantified variables, native activation semantics, or temporal scope.",
                              "Context-required inputs cannot be resolved by the current source-only compiler.",
                              "Unknown-count collisions cannot be repaired by a deterministic projection of the same codec.",
                              "Distinct input features can still collapse under a learned projection; no richer projection was fitted.",
                              "Native transport/schema receipts are not kernel proofs or useful proof acceptance."],
              "elapsed_seconds": time.perf_counter() - started}
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    persisted = json.loads(_bounded_bytes(output / "report.json", 32_000_000),
                           object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(persisted == report and persisted["report_sha256"] == _digest({key: value for key, value in persisted.items()
                                                                           if key != "report_sha256"}), "persisted report identity differs")
    return report
