"""Prepare source-only human review and separate unreviewed Legal IR contrasts.

This is AFI-04 preparation, not adjudication. Reviewer material never contains
reference targets, candidates, embeddings, corpus identities or compiler output.
Organizer material is a separate artifact and must not be given to reviewers.
No files, models, providers, encoders or provers are accessed by this helper.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from copy import deepcopy

SCHEMA = "autoformal-alignment-review-bundle/v1"
MAX_ITEMS = 40
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
_AUTHORITY = {"independent_fidelity_available": False, "source_semantics_verified": False,
              "proof_authority": False, "reviewer_attestations_created": False, "qualified": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _source_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pseudonym(kind, value):
    return "review-" + kind + "-" + _digest({"domain": SCHEMA, "kind": kind, "value": value})[:24]


def _canonical_target(target):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule
    _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
             and len(target["rules"]) == 1, "one canonical Legal rule required")
    canonical = {"rules": [CanonicalRule.from_dict(target["rules"][0]).to_dict()]}
    _require(_raw(canonical) == _raw(target), "canonical target facets must be preserved")
    return canonical


def _prepare_rows(rows, split):
    _require(type(rows) is list and 1 <= len(rows) <= 5000, "bounded nonempty source rows required")
    result, seen = [], set()
    for row in rows:
        _require(type(row) is dict and {"id", "group_id", "split", "source_text", "source_sha256", "target"} <= set(row),
                 "validated source row required")
        _require(row["split"] == split, "only train and exposed validation inputs accepted")
        _require(row.get("evaluation_role", "exposed_development") == "exposed_development", "sealed evaluation role forbidden")
        _require(row.get("target_origin", "synthetic_authored_unreviewed") == "synthetic_authored_unreviewed",
                 "review preparation requires synthetic authored provenance")
        for key in ("id", "group_id"):
            _require(type(row[key]) is str and row[key].strip() and len(row[key]) <= 512, "bounded source identity required")
        _require(row["id"] not in seen, "duplicate source ID")
        seen.add(row["id"])
        text = row["source_text"]
        _require(type(text) is str and text.strip() and len(text) <= 32768, "bounded exact source required")
        _require(_source_digest(text) == row["source_sha256"], "original source SHA256 mismatch")
        target = _canonical_target(row["target"])
        target_digest = _digest(target)
        if "target_sha256" in row:
            _require(row["target_sha256"] == target_digest, "reference target SHA256 mismatch")
        style = row.get("wording_style")
        _require(style is None or (type(style) is int and 0 <= style <= 100), "bounded construction style required")
        # Deliberately retain only organizer-required fields, never vectors or outcomes.
        result.append({"id": row["id"], "group_id": row["group_id"], "split": split,
                       "source_text": text, "source_sha256": row["source_sha256"],
                       "target": target, "target_sha256": target_digest, "wording_style": style,
                       "normalized_source_sha256": _source_digest(" ".join(unicodedata.normalize("NFKC", text).casefold().split()))})
    return result


def _select(rows):
    """Balance declared groups, authored modalities, styles and objects, then counts."""
    remaining = sorted(rows, key=lambda row: (row["source_sha256"], row["id"]))
    selected, groups, group_modalities, group_styles, group_objects = [], set(), set(), set(), set()
    modality_styles, group_counts = set(), Counter()
    while remaining and len(selected) < MAX_ITEMS:
        def score(row):
            group, rule, style = row["group_id"], row["target"]["rules"][0], row["wording_style"]
            return (group not in groups, (group, rule["modality"]) not in group_modalities,
                    (group, style) not in group_styles, (group, rule["object"]) not in group_objects,
                    -group_counts[group], (rule["modality"], style) not in modality_styles)
        index = max(range(len(remaining)), key=lambda index: score(remaining[index]))
        row = remaining.pop(index)
        selected.append(row)
        group, rule, style = row["group_id"], row["target"]["rules"][0], row["wording_style"]
        groups.add(group)
        group_modalities.add((group, rule["modality"]))
        group_styles.add((group, style))
        group_objects.add((group, rule["object"]))
        modality_styles.add((rule["modality"], style))
        group_counts[group] += 1
    return sorted(selected, key=lambda row: _pseudonym("item", row["source_sha256"]))


def _alternative(value, choices, facet):
    return next((choice for choice in sorted(choices) if choice != value), "review_proposed_alternative_" + facet)


def _contrasts(selected, training):
    choices = {facet: {row["target"]["rules"][0][facet] for row in training}
               for facet in ("actor", "action", "object")}
    result = []
    for row in selected:
        original = row["target"]
        for facet in FACETS:
            proposed = deepcopy(original)
            rule = proposed["rules"][0]
            if facet == "modality":
                rule[facet] = {"O": "P", "P": "F", "F": "O"}[rule[facet]]
            elif facet in choices:
                rule[facet] = _alternative(rule[facet], choices[facet], facet)
            else:
                rule[facet] = rule[facet][1:] if rule[facet] else ["review_proposed_" + facet + "_constraint"]
            validated = _canonical_target(proposed)
            changed = [name for name in FACETS if _raw(original["rules"][0][name]) != _raw(rule[name])]
            _require(changed == [facet], "contrast must change exactly one facet")
            proposal_digest = _digest(validated)
            result.append({"proposal_id": _pseudonym("contrast", {"source_sha256": row["source_sha256"],
                           "facet": facet, "proposed_target_sha256": proposal_digest}),
                           "item_id": _pseudonym("item", row["source_sha256"]),
                           "source_text": row["source_text"], "source_sha256": row["source_sha256"],
                           "original_reference_target_sha256": row["target_sha256"],
                           "changed_facet": facet, "proposed_target": validated,
                           "proposed_target_sha256": proposal_digest, "typed_contract_validated": True,
                           "status": "unreviewed_ir_contrast_proposal", "encoded": False,
                           "source_wording_rewritten": False, "semantic_mismatch_adjudicated": False,
                           "excluded_from_training": True, "excluded_from_evaluation_gold": True,
                           "proof_verified": False, **_AUTHORITY})
    return result


def _bindings(value):
    _require(type(value) is dict and value, "source integrity bindings required")
    _require(len(_raw(value)) <= 128 * 1024, "source bindings exceed byte bound")
    def check(item):
        if type(item) is dict:
            if "evaluation_role" in item:
                _require(item["evaluation_role"] == "exposed_development", "sealed source binding forbidden")
            if "split" in item:
                _require(item["split"] in ("train", "validation"), "sealed split binding forbidden")
            if "path" in item:
                _require(type(item["path"]) is str, "binding path must be text")
                _require(not any(re.search(r"(^|[-_])(sealed|holdout|heldout|final)([-_.]|$)", part.casefold())
                                 for part in item["path"].split("/")), "sealed/final source binding forbidden")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
    check(value)
    return deepcopy(value)


def prepare_alignment_review(training_rows, development_rows, source_bindings) -> dict:
    """Return separately hash-bound reviewer and organizer material, without I/O.

    References determine sampling coverage and contrasts only in the organizer
    payload. All annotations remain blank; typed contrasts remain unreviewed,
    unencoded proposals excluded from training and evaluation ground truth.
    """
    bindings = _bindings(source_bindings)
    training = _prepare_rows(training_rows, "train")
    development = _prepare_rows(development_rows, "validation")
    for field in ("id", "group_id", "source_sha256", "normalized_source_sha256", "target_sha256"):
        _require(not {row[field] for row in training} & {row[field] for row in development},
                 "train/development leakage: " + field)
    selected = _select(development)
    reviewer_items, key = [], []
    for row in selected:
        item_id = _pseudonym("item", row["source_sha256"])
        group_id = _pseudonym("group", row["group_id"])
        reviewer_items.append({"item_id": item_id, "group_pseudonym": group_id,
                               "source_text": row["source_text"], "source_sha256": row["source_sha256"],
                               "evaluation_role": "exposed_development",
                               "annotation": {"facets": {facet: None for facet in FACETS},
                                              "notes": None, "ambiguity": None, "unsupported_meaning": None,
                                              "reviewer_id": None, "reviewed_at_utc": None}})
        key.append({"item_id": item_id, "group_pseudonym": group_id, "original_id": row["id"],
                    "original_group_id": row["group_id"], "source_sha256": row["source_sha256"],
                    "split": row["split"], "wording_style": row["wording_style"],
                    "synthetic_authored_reference_target": deepcopy(row["target"]),
                    "reference_target_sha256": row["target_sha256"],
                    "reference_review_status": "unreviewed"})
    reviewer = {"schema": "autoformal-source-facet-reviewer/v1", "evaluation_role": "exposed_development",
                "source_provenance": "synthetic_authored_unreviewed",
                "instructions": "Read the exact source independently. Fill each facet or record ambiguity and unsupported meaning. Blank slots are unreviewed; do not infer absence from an empty slot.",
                "preparation_status": "pending_human_review", "items": reviewer_items}
    contrasts = _contrasts(selected, training)
    organizer = {"schema": "autoformal-source-facet-organizer/v1", "do_not_send_to_reviewers": True,
                 "source_bindings": bindings, "source_bindings_sha256": _digest(bindings),
                 "source_provenance": "synthetic_authored_unreviewed", "reviewer_key": key,
                 "sampling": {"policy": "deterministic_group_modality_style_object_coverage_then_group_balance",
                              "reference_labels_used_only_for_organizer_sampling": True,
                              "max_items": MAX_ITEMS, "training_rows": len(training),
                              "development_rows": len(development), "selected_items": len(selected),
                              "available_groups": len({row["group_id"] for row in development}),
                              "selected_groups": len({row["group_id"] for row in selected}),
                              "authored_modality_counts": dict(sorted(Counter(row["target"]["rules"][0]["modality"] for row in selected).items())),
                              "construction_style_counts": dict(sorted(Counter(str(row["wording_style"]) for row in selected).items()))},
                 "contrast_corpus": {"schema": "autoformal-unreviewed-ir-contrasts/v1", "rows": contrasts,
                                     "count": len(contrasts), "status": "pending_independent_mismatch_review",
                                     "not_ground_truth": True, "encoded": False,
                                     "excluded_from_training": True, "excluded_from_evaluation_gold": True,
                                     "proof_verified": False, **_AUTHORITY}, **_AUTHORITY}
    def manifest(payload, audience):
        return {"schema": "autoformal-source-facet-review-manifest/v1", "audience": audience,
                "payload_schema": payload["schema"], "payload_sha256": _digest(payload),
                "digest_recipe": "sha256_utf8_sorted_compact_json_ensure_ascii_false_no_nan_no_newline",
                "item_count": len(selected), "source_bindings_sha256": _digest(bindings),
                "candidate_blind": audience == "reviewer", "automatic_adjudication": False,
                "evaluation_role": "exposed_development", **_AUTHORITY}
    return {"schema": SCHEMA, "status": "prepared_pending_human_review",
            "reviewer_payload": reviewer, "organizer_payload": organizer,
            "reviewer_manifest": manifest(reviewer, "reviewer"),
            "organizer_manifest": manifest(organizer, "organizer"),
            "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
            "training_executed": False, **_AUTHORITY}


__all__ = ["prepare_alignment_review"]
