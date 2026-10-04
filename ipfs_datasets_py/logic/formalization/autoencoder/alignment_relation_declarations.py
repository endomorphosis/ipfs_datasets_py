"""Check pinned TRAIN relation declarations without admitting any relation.

Exact formal-view identity is a weak structural observation. Declared positive
and negative relations, family scopes and evidence hashes remain unverified
metadata. This owner performs no file I/O, numerical loss, model or proof call.
"""
from __future__ import annotations

import json
from collections import Counter

from . import alignment_stage_declarations as stages
from .alignment_lane_bundle import MASKS, _closed, _digest, _raw, _require, _sha, _text

SCHEMA = "alignment-train-relation-declaration/v1"
POLICY_SCHEMA = "alignment-train-relation-policy/v1"
LEDGER_SCHEMA = "alignment-train-pair-ledger/v1"
VALIDATION_SCHEMA = "alignment-train-relation-validation/v1"
MAX_TRAIN_ROWS = 128
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPECTED_BYTES = 1024 * 1024
MODE = "diagnostic_unadmitted_relations/v1"
PAIR_ORDER = "train_row_major/v1"
WEAK_STRUCTURAL_POLICY = "exact_formal_identity_only/v1"
FAMILY_COERCION_POLICY = "not_performed/v1"
ELIGIBILITY = "blocked_no_admitted_relations"
STATUSES = ("unknown", "declared_positive", "declared_negative", "weak_structural_identity")
PAIR_FIELDS = {"left_id", "right_id", "left_input_sha256", "right_input_sha256",
               "left_formal_view_sha256", "right_formal_view_sha256", "relation_status",
               "evidence_sha256", "reason", "positive_mask", "permitted_negative_mask"}
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "proof_authority",
                      "semantic_label_admission", "reviewer_identity_authenticated",
                      "independent_semantic_review_completed", "file_bindings_verified",
                      "evidence_contents_verified", "relation_semantics_verified", "family_profile_scope_verified",
                      "family_coercion_executed", "split_provenance_authenticated", "training_executed",
                      "model_executed", "numerical_worker_executed", "query_reference_accessed",
                      "weak_structural_diagnostic_fit_authorized"), False)


def _bounded(value, maximum, label):
    _require(len(_raw(value)) <= maximum, label + " byte bound exceeded")


def _policy(policy, lane):
    fields = {"mode", "pair_order", "weak_structural_policy", "family_coercion_policy",
              "source_family_id", "target_family_id", "source_profile_sha256", "target_profile_sha256"}
    stages._role(policy, fields, POLICY_SCHEMA, "diagnostic relation policy")
    for key, expected in (("mode", MODE), ("pair_order", PAIR_ORDER),
                          ("weak_structural_policy", WEAK_STRUCTURAL_POLICY),
                          ("family_coercion_policy", FAMILY_COERCION_POLICY)):
        _require(policy[key] == expected, "diagnostic relation " + key + " differs")
    for key in ("source_family_id", "target_family_id"):
        if policy[key] is not None:
            _text(policy[key], "declared " + key, maximum=512)
    _sha(policy["source_profile_sha256"], "declared source profile SHA")
    _require(policy["source_profile_sha256"] == lane["profile_sha256"],
             "relation policy source profile differs from bound lane")
    _sha(policy["target_profile_sha256"], "opaque declared target profile SHA", nullable=True)


def validate_relation_declaration(declaration, *, expected_bindings):
    """Validate a complete row-major ledger; all semantic masks stay false.

    Required external role pins hash each full sealed role and its ordered
    ``rows`` (null when absent), following the frozen stage declaration recipe.
    Matching pins establish declared associations, never evidence authenticity.
    """
    _bounded(declaration, MAX_BYTES, "relation declaration")
    _bounded(expected_bindings, MAX_EXPECTED_BYTES, "external relation pins")
    names = ("lane_validation", "train_manifest", "relation_policy", "pair_ledger")
    stages._role(declaration, names, SCHEMA, "relation declaration")
    values = {name: declaration[name] for name in names}
    stages._pins(values, expected_bindings)
    lane, train, policy, ledger = (values[name] for name in names)
    stages._lane(lane)
    stages._role(train, {"rows", "file_binding"}, "alignment-train-manifest/v1", "relation TRAIN manifest")
    stages._file(train["file_binding"])
    stages._rows(train["rows"], stages.ROW_FIELDS | {"split", "formal_view_sha256", "masks"}, "relation TRAIN")
    rows = train["rows"]
    _require(1 <= len(rows) <= MAX_TRAIN_ROWS, "bounded nonempty TRAIN manifest required")
    stages._join([{key: row[key] for key in stages.ROW_FIELDS} for row in rows], lane)
    for row in rows:
        _require(row["split"] == "train", "relation manifest contains a non-TRAIN row")
        _sha(row["formal_view_sha256"], "TRAIN formal view SHA")
        stages._zero_masks(row["masks"])
    _policy(policy, lane)
    stages._role(ledger, {"rows"}, LEDGER_SCHEMA, "complete TRAIN pair ledger")
    pairs = ledger["rows"]
    count = len(rows)
    _require(type(pairs) is list and len(pairs) == count * count,
             "complete ordered TRAIN Cartesian pair ledger required")
    counts = Counter()
    result_rows = []
    for index, pair in enumerate(pairs):
        _closed(pair, PAIR_FIELDS, "TRAIN pair declaration")
        left, right = rows[index // count], rows[index % count]
        for prefix, source in (("left", left), ("right", right)):
            expected = {prefix + "_id": source["id"], prefix + "_input_sha256": source["input_sha256"],
                        prefix + "_formal_view_sha256": source["formal_view_sha256"]}
            _require(all(pair[key] == value for key, value in expected.items()),
                     "TRAIN pair order or source/input/formal binding differs")
        status = pair["relation_status"]
        _require(type(status) is str and status in STATUSES, "known diagnostic relation status required")
        if status == "weak_structural_identity":
            _require(left["formal_view_sha256"] == right["formal_view_sha256"],
                     "weak structural identity requires exact formal-view identity")
        _sha(pair["evidence_sha256"], "declared unadmitted evidence SHA", nullable=True)
        _text(pair["reason"], "diagnostic relation reason", maximum=4096)
        _require(pair["positive_mask"] is False and pair["permitted_negative_mask"] is False,
                 "diagnostic relation masks must be exact boolean false")
        counts[status] += 1
        result_rows.append({**pair, "eligibility": ELIGIBILITY,
                            "evidence_status": "not_provided" if pair["evidence_sha256"] is None
                            else "declared_unverified_unadmitted"})
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_declared_train_relations_only",
              "eligibility": ELIGIBILITY, "declaration_sha256": _digest(declaration),
              "role_bindings": stages._bindings(values),
              "validation_scope": "externally_pinned_declared_train_pair_associations_only",
              "train_row_count": count, "pair_count": len(pairs), "pair_order": PAIR_ORDER,
              "declared_relation_counts": {status: counts[status] for status in STATUSES},
              "declared_evidence_count": sum(pair["evidence_sha256"] is not None for pair in pairs),
              "exact_formal_identity_pair_count": sum(left["formal_view_sha256"] == right["formal_view_sha256"]
                                                      for left in rows for right in rows),
              "admitted_positive_pair_count": 0, "permitted_negative_pair_count": 0,
              "semantic_positive_pair_count": 0, "admitted_evidence_count": 0,
              "positive_mask": [[False for _ in rows] for _ in rows],
              "permitted_negative_mask": [[False for _ in rows] for _ in rows],
              "rows": result_rows, "declared_family_profile_scope": {key: policy[key] for key in (
                  "source_family_id", "target_family_id", "source_profile_sha256", "target_profile_sha256")},
              "weak_diagnostic_policy_required": True, "verification_status": "pending", "admission_status": "pending",
              "masks": dict.fromkeys(MASKS, 0), "model_calls": 0, "encoder_calls": 0, "prover_calls": 0,
              "optimizer_updates": 0, **FALSE}
    result["content_sha256"] = _digest(result)
    _bounded(result, MAX_BYTES, "relation validation receipt")
    return json.loads(_raw(result))


__all__ = ["validate_relation_declaration"]
