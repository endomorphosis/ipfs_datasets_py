"""Prepare blank source/context review, with a separate private authored key.

This helper performs no I/O or adjudication. Exact available input is visible
to reviewers; original identities, references, expectations, partitions, and
construction outcomes are withheld. Existing authored panel validation checks
integrity only. A prepared bundle creates no submissions, reviewer identity
attestations, source-fidelity evidence, or proof authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

SCHEMA = "alignment-richer-review-bundle/v1"
REVIEWER_SCHEMA = "alignment-richer-source-context-reviewer/v1"
ORGANIZER_SCHEMA = "alignment-richer-source-context-organizer/v1"
MANIFEST_SCHEMA = "alignment-richer-review-audience-manifest/v1"
MAX_BUNDLE_BYTES = 4 * 1024 * 1024
MAX_BINDING_BYTES = 256 * 1024
_ANNOTATION_FIELDS = ("interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                      "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc")
_AUTHORITY = {"qualified": False, "production_admitted": False, "independent_fidelity_available": False,
              "source_semantics_verified": False, "proof_authority": False,
              "reviewer_identity_attestations_created": False, "submissions_created": False}
_GUIDANCE = {
    "task": "Interpret the exact source and separately declared assumptions independently; no proposed answer is supplied.",
    "blank_annotations": "Null fields mean unreviewed or unanswered, never an adjudicated absence of meaning.",
    "explicit_none": "If review establishes no normative rule, explicitly record that interpretation and an empty normative_rules list with reasons.",
    "ambiguity": "Describe competing interpretations and the clarification needed rather than choosing an unstated referent or assumption.",
    "unsupported_meaning": "Record meaningful binders, scope, logical connectives, negated modalities, and temporal interpretation that a flat representation cannot express.",
    "normative_rules": "You may describe each proposed norm using modality, actor, action, object, conditions, exceptions, and temporal facets. No suggested values or target rules are supplied.",
    "freeform_qualifier_scope": "Explain qualifier connectives, scope, relationships, variable binding, and timing in free form. Seven flat facets need not express the source's full meaning.",
    "context": "Treat explicit_assumptions as separately supplied input. Do not infer missing context; distinguish source-only wording from interpretations requiring assumptions.",
    "reviewer_identity": "Leave identity and timestamp fields blank until an actual review. Entering a declared identity alone does not authenticate a reviewer or their independence.",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as error:
        raise ValueError("bounded finite ordinary JSON required") from error
    _require(len(raw) <= MAX_BUNDLE_BYTES, "richer review bundle exceeds byte bound")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _bindings(value):
    _require(type(value) is dict and value, "nonempty source bindings object required")
    _require(len(_raw(value)) <= MAX_BINDING_BYTES, "source bindings exceed byte bound")

    def check(item, depth=0):
        _require(depth <= 16, "source bindings exceed nesting bound")
        if type(item) is dict:
            _require(len(item) <= 512 and all(type(key) is str for key in item), "bounded string binding keys required")
            if "evaluation_role" in item:
                _require(item["evaluation_role"] == "exposed_development", "sealed evaluation binding forbidden")
            if "split" in item:
                _require(item["split"] in ("train", "validation"), "sealed split binding forbidden")
            if "path" in item:
                _require(type(item["path"]) is str and 0 < len(item["path"]) <= 4096, "bounded binding path required")
                _require(not any(re.search(r"(^|[-_])(sealed|holdout|heldout|final)([-_.]|$)", part.casefold())
                                 for part in item["path"].split("/")), "sealed/final source binding forbidden")
            if "sha256" in item:
                _require(type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]),
                         "canonical binding SHA256 required")
            if "bytes" in item:
                _require(type(item["bytes"]) is int and item["bytes"] >= 0, "nonnegative binding byte count required")
            for child in item.values():
                check(child, depth + 1)
        elif type(item) is list:
            _require(len(item) <= 512, "binding list exceeds bound")
            for child in item:
                check(child, depth + 1)
        else:
            _require(item is None or type(item) in (str, bool, int, float), "ordinary binding JSON required")

    check(value)
    return deepcopy(value)


def _item_id(input_sha256):
    return "richer-review-item-" + _digest({"schema": REVIEWER_SCHEMA, "input_sha256": input_sha256})[:24]


def _prepare(panel, source_bindings):
    from .alignment_richer_panel import validate_alignment_richer_panel

    _raw(panel)
    validate_alignment_richer_panel(panel)
    bindings = _bindings(source_bindings)
    rows = sorted(panel["rows"], key=lambda row: _item_id(row["input_sha256"]))
    _require(len({row["input_sha256"] for row in rows}) == len(rows), "unique available input identities required")
    reviewer_items, organizer_key = [], []
    for row in rows:
        item_id = _item_id(row["input_sha256"])
        reviewer_items.append({"item_id": item_id, "source_text": row["source_text"],
                               "source_sha256": row["source_sha256"], "context": deepcopy(row["context"]),
                               "input_sha256": row["input_sha256"],
                               "annotation": {field: None for field in _ANNOTATION_FIELDS}})
        organizer_key.append({"item_id": item_id, "original_id": row["id"], "original_group_id": row["group_id"],
                              "split": row["split"], "row_kind": row["row_kind"], "case_variant": row["case_variant"],
                              "input_sha256": row["input_sha256"], "source_sha256": row["source_sha256"],
                              "authored_reference": deepcopy(row["target"]), "authored_reference_sha256": row["target_sha256"],
                              "authored_expectation": deepcopy(row["expectation"]), "reference_review_status": "unreviewed"})
    _require(len({item["item_id"] for item in reviewer_items}) == len(rows), "review pseudonym collision")
    reviewer = {"schema": REVIEWER_SCHEMA, "instructions": deepcopy(_GUIDANCE), "items": reviewer_items}
    input_manifest = [{key: item[key] for key in ("item_id", "source_sha256", "input_sha256")}
                      for item in reviewer_items]
    organizer = {"schema": ORGANIZER_SCHEMA, "do_not_send_to_reviewers": True,
                 "source_panel": deepcopy(panel), "source_panel_sha256": _digest(panel),
                 "source_bindings": bindings, "source_bindings_sha256": _digest(bindings),
                 "reviewer_key": organizer_key, "input_manifest_sha256": _digest(input_manifest),
                 "status": "prepared_pending_human_review", "completed_reviews": 0,
                 "original_40_review_bundle_reusable": False, "automatic_adjudication": False, **_AUTHORITY}

    def manifest(payload, audience):
        return {"schema": MANIFEST_SCHEMA, "audience": audience, "payload_schema": payload["schema"],
                "payload_sha256": _digest(payload), "payload_bytes": len(_raw(payload)), "item_count": len(rows),
                "input_manifest_sha256": _digest(input_manifest), "candidate_reference_blind": audience == "reviewer",
                "digest_recipe": "sha256_sorted_compact_utf8_json_no_nan_no_newline", **_AUTHORITY}

    result = {"schema": SCHEMA, "status": "prepared_pending_human_review", "reviewer_payload": reviewer,
              "organizer_payload": organizer, "reviewer_manifest": manifest(reviewer, "reviewer"),
              "organizer_manifest": manifest(organizer, "organizer"),
              "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
              "training_executed": False, **_AUTHORITY}
    result["bundle_sha256"] = _digest(result)
    _raw(result)
    return result


def prepare_richer_review(panel, source_bindings) -> dict:
    """Return detached, separately bound reviewer/private-organizer payloads.

    All supplied exposed panel rows are included, sorted by source/context
    pseudonym; references never determine sampling. ``context.bindings`` are
    available caller assumptions, not generated target hints. Do not give the
    containing bundle or organizer payload to reviewers: send only the reviewer
    payload and its audience manifest. No files or submissions are created.
    """
    return _prepare(panel, source_bindings)


def validate_richer_review_bundle(bundle) -> dict:
    """Reconstruct a closed blank preparation; reject resealed leaks or reviews.

    This validates preparation integrity, not authenticity of provenance,
    correctness of authored labels, human review, or semantic equivalence.
    Submitted annotations require a separate future admission interface.
    """
    _raw(bundle)
    _require(type(bundle) is dict and bundle.get("schema") == SCHEMA,
             "richer review bundle schema required; old 40-item bundles are not reusable")
    organizer = bundle.get("organizer_payload")
    _require(type(organizer) is dict and "source_panel" in organizer and "source_bindings" in organizer,
             "private authored panel and source bindings required")
    expected = _prepare(organizer["source_panel"], organizer["source_bindings"])
    _require(_raw(bundle) == _raw(expected), "richer review preparation differs from closed blank source/context contract")
    return {"schema": "alignment-richer-review-preparation-validation/v1",
            "status": "validated_blank_preparation_only", "item_count": len(bundle["reviewer_payload"]["items"]),
            "bundle_sha256": bundle["bundle_sha256"],
            "reviewer_payload_sha256": bundle["reviewer_manifest"]["payload_sha256"],
            "organizer_payload_sha256": bundle["organizer_manifest"]["payload_sha256"],
            "completed_reviews": 0, "source_meaning_adjudicated": False, **_AUTHORITY}


__all__ = ["prepare_richer_review", "validate_richer_review_bundle"]
