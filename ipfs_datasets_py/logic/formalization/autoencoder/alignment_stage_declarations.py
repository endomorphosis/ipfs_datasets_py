"""Closed, externally pinned fit/rank/score declarations; no numerical work.

Every role's external ``value_sha256`` hashes its complete sealed JSON value,
including ``content_sha256``. ``rows_sha256`` hashes its ordered ``rows`` list,
or is null for a role without rows. Canonical JSON is sorted, compact UTF8.
These pins establish declared associations, not file I/O, authentication,
durability, semantic admission or an attestation of numerical execution.
"""
from __future__ import annotations

import json
import math

from .alignment_lane_bundle import (
    FALSE as LANE_FALSE,
)
from .alignment_lane_bundle import (
    MASKS,
    ROW_BINDING_FIELDS,
    STAGES,
    _closed,
    _digest,
    _raw,
    _require,
    _seal_check,
    _sha,
    _text,
)
from .alignment_lane_bundle import (
    VALIDATION_SCHEMA as LANE_VALIDATION_SCHEMA,
)

FIT_SCHEMA = "alignment-fit-declaration/v1"
RANK_SCHEMA = "alignment-rank-declaration/v1"
SCORE_SCHEMA = "alignment-score-declaration/v1"
VALIDATION_SCHEMA = "alignment-stage-declaration-validation/v1"
MAX_ROWS = 128
MAX_BYTES = 2 * 1024 * 1024
RELATION_POLICY = "exact_formal_identity_is_weak_structural_only_unknown_pairs_excluded/v1"
TIE_BREAK = "score_desc_candidate_id_asc"
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "proof_authority",
                      "semantic_label_admission", "reviewer_identity_authenticated",
                      "independent_semantic_review_completed", "file_bindings_verified",
                      "reference_durability_verified", "runtime_computation_proven",
                      "formal_vector_bank_verified", "projection_checkpoint_contents_verified",
                      "self_or_derivative_exclusion_verified", "split_provenance_authenticated",
                      "training_executed", "ranking_executed", "scoring_executed", "model_executed",
                      "query_reference_accessed", "numerical_worker_implemented"), False)
ROW_FIELDS = {"id", "input_sha256", "representation_sha256", "status", "reason"}


def _bounded(value):
    _require(len(_raw(value)) <= MAX_BYTES, "stage declaration byte bound exceeded")


def _int(value, low, high, label):
    _require(type(value) is int and low <= value <= high, "bounded integer " + label + " required")


def _zero_masks(value):
    _closed(value, MASKS, "zero supervision masks")
    _require(all(type(value[name]) is int and value[name] == 0 for name in MASKS),
             "all supervision masks must remain exact integer zero")


def _role(value, fields, schema, label):
    _closed(value, set(fields) | {"schema", "content_sha256"}, label)
    _require(value["schema"] == schema, label + " schema differs")
    _seal_check(value, label)


def _pins(values, expected):
    _closed(expected, values, "externally selected stage role bindings")
    for name, value in values.items():
        binding = expected[name]
        _closed(binding, {"value_sha256", "rows_sha256"}, "external " + name + " binding")
        _sha(binding["value_sha256"], "external role value SHA")
        _sha(binding["rows_sha256"], "external ordered rows SHA", nullable=True)
        _require(binding["value_sha256"] == _digest(value), "externally pinned " + name + " differs")
        rows = value.get("rows") if type(value) is dict else None
        _require(binding["rows_sha256"] == (_digest(rows) if rows is not None else None),
                 "externally pinned " + name + " ordered rows differ")


def _bindings(values):
    return {name: {"value_sha256": _digest(value),
                   "rows_sha256": _digest(value["rows"]) if type(value) is dict and "rows" in value else None}
            for name, value in values.items()}


def _file(value):
    if value is None:
        return
    _closed(value, {"path", "sha256", "bytes"}, "declared file binding")
    _text(value["path"], "declared file path", maximum=4096)
    _sha(value["sha256"], "declared file SHA")
    _int(value["bytes"], 1, 256 * 1024 * 1024, "declared file size")


def _rows(rows, fields, label):
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS, "bounded ordered " + label + " rows required")
    seen = set()
    for row in rows:
        _closed(row, fields, label + " row")
        _text(row["id"], label + " id", maximum=512)
        _require(row["id"] not in seen, "duplicate " + label + " id")
        seen.add(row["id"])
        _sha(row["input_sha256"], label + " source/context input SHA")


def _source_row(row):
    _require(type(row["status"]) is str and row["status"] in {"available", "unavailable", "ablation_zero"},
             "known declared representation status required")
    _sha(row["representation_sha256"], "representation SHA", nullable=True)
    if row["status"] == "unavailable":
        _require(row["representation_sha256"] is None, "unavailable representation must stay null")
        _text(row["reason"], "unavailable reason", maximum=4096)
    else:
        _require(row["representation_sha256"] is not None, "available/ablation representation requires a binding")
        if row["status"] == "available":
            _require(row["reason"] is None, "available representation has no failure reason")
        else:
            _text(row["reason"], "explicit zero ablation reason", maximum=4096)


def _lane(value):
    fields = {"status", "lane_id", "stage", "dimension", "bundle_sha256", "profile_sha256",
              "producer_receipt_sha256", "row_count", "rows", "available_count", "unavailable_count",
              "zero_ablation_count", "input_recipes_agree", "normalization_performed",
              "padding_or_truncation_performed", "token_receipt_contents_verified", "leanstral_runtime_qualified",
              "verification_status", "admission_status", "masks", "model_calls", "encoder_calls",
              "prover_calls", "optimizer_updates"} | set(LANE_FALSE)
    _role(value, fields, LANE_VALIDATION_SCHEMA, "lane validation receipt")
    _require(value["status"] == "validated_declared_representation_identity_only",
             "lane receipt must retain its declared-only scope")
    _require(type(value["lane_id"]) is str and value["lane_id"] in {"legacy8", "native384", "native768", "leanstral"}
             and type(value["stage"]) is str and value["stage"] in STAGES, "known bound lane/stage required")
    _int(value["dimension"], 1, 8192, "lane dimension")
    for name in ("bundle_sha256", "profile_sha256", "producer_receipt_sha256"):
        _sha(value[name], name)
    _require(all(value[name] is False for name in LANE_FALSE), "lane receipt cannot claim authority or execution")
    for name in ("normalization_performed", "padding_or_truncation_performed", "token_receipt_contents_verified",
                 "leanstral_runtime_qualified"):
        _require(value[name] is False, "lane receipt claims an unsupported operation")
    _require(value["input_recipes_agree"] is True and value["verification_status"] == value["admission_status"] == "pending",
             "lane receipt verification/admission remains pending")
    _zero_masks(value["masks"])
    for name in ("model_calls", "encoder_calls", "prover_calls", "optimizer_updates"):
        _int(value[name], 0, 0, name)
    fields = ROW_BINDING_FIELDS | {"producer_row_sha256", "source_sha256", "context_sha256",
                                  "context_forwarded", "context_resolved"}
    _rows(value["rows"], fields, "lane")
    for row in value["rows"]:
        _source_row({**row, "representation_sha256": row["vector_sha256"]})
        for name in ("encoder_text_sha256", "producer_row_sha256", "source_sha256", "context_sha256"):
            _sha(row[name], name)
        for name in ("upstream_vector_sha256", "token_receipt_sha256"):
            _sha(row[name], name, nullable=True)
        _require(type(row["context_forwarded"]) is bool and row["context_resolved"] is False,
                 "context forwarding is declared, resolution is unestablished")
        binding = {key: row[key] for key in ROW_BINDING_FIELDS}
        _require(row["producer_row_sha256"] == _digest(binding), "lane producer row binding differs")
    _int(value["row_count"], 1, MAX_ROWS, "lane row count")
    _require(value["row_count"] == len(value["rows"]), "lane row count differs")
    for name, status in (("available_count", "available"), ("unavailable_count", "unavailable"),
                         ("zero_ablation_count", "ablation_zero")):
        _int(value[name], 0, MAX_ROWS, name)
        _require(value[name] == sum(row["status"] == status for row in value["rows"]), "lane status count differs")


def _join(rows, lane):
    _require(len(rows) == len(lane["rows"]), "complete ordered source ledger required")
    for row, bound in zip(rows, lane["rows"], strict=True):
        _source_row(row)
        expected = {"id": bound["id"], "input_sha256": bound["input_sha256"],
                    "representation_sha256": bound["vector_sha256"], "status": bound["status"], "reason": bound["reason"]}
        _require(_raw({key: row[key] for key in ROW_FIELDS}) == _raw(expected), "source/context/vector or ordered ledger differs")


def _bank(value):
    _role(value, {"lane_validation", "rows", "file_binding"}, "alignment-frozen-train-bank/v1", "frozen TRAIN bank")
    _lane(value["lane_validation"])
    _file(value["file_binding"])
    _rows(value["rows"], ROW_FIELDS | {"split", "formal_view_sha256"}, "TRAIN bank")
    _join(value["rows"], value["lane_validation"])
    for row in value["rows"]:
        _require(row["split"] == "train", "bank contains a non-TRAIN candidate")
        _sha(row["formal_view_sha256"], "TRAIN candidate formal view SHA")


def _ranking_policy(value):
    _role(value, {"mode", "top_k", "tie_break"}, "alignment-ranking-policy/v1", "ranking policy")
    _require(type(value["mode"]) is str and value["mode"] in {
        "raw_source_to_source", "projected_source_to_source", "projected_source_to_formal"}, "known ranking mode required")
    _int(value["top_k"], 1, 20, "top k")
    _require(value["tie_break"] == TIE_BREAK, "fixed deterministic ranking order required")


def _receipt(stage, declaration, values, **details):
    result = {"schema": VALIDATION_SCHEMA, "stage": stage, "declaration_sha256": _digest(declaration),
              "role_bindings": _bindings(values), "validation_scope": "externally_pinned_declared_associations_only",
              "verification_status": "pending", "admission_status": "pending", "masks": dict.fromkeys(MASKS, 0),
              "model_calls": 0, "encoder_calls": 0, "prover_calls": 0, "optimizer_updates": 0,
              **FALSE, **details}
    result["content_sha256"] = _digest(result)
    _bounded(result)
    return json.loads(_raw(result))


def validate_fit_declaration(declaration, *, expected_bindings):
    """Validate TRAIN-only weak structural bindings; semantic fitting is blocked."""
    _bounded(declaration)
    _bounded(expected_bindings)
    _role(declaration, {"lane_validation", "train_manifest", "fit_policy"}, FIT_SCHEMA, "fit declaration")
    lane, train, policy = (declaration[key] for key in ("lane_validation", "train_manifest", "fit_policy"))
    _lane(lane)
    _role(train, {"rows", "file_binding"}, "alignment-train-manifest/v1", "TRAIN manifest")
    _file(train["file_binding"])
    _rows(train["rows"], ROW_FIELDS | {"split", "formal_view_sha256", "masks"}, "fit TRAIN")
    _join(train["rows"], lane)
    for row in train["rows"]:
        _require(row["split"] == "train", "fitting contains a non-TRAIN row")
        _sha(row["formal_view_sha256"], "TRAIN formal view SHA")
        _zero_masks(row["masks"])
    _role(policy, {"relation_policy", "checkpoint_selection", "budget"}, "alignment-fit-policy/v1", "fit policy")
    _require(policy["relation_policy"] == RELATION_POLICY and policy["checkpoint_selection"] == "fixed_final_step",
             "weak structural relation policy and fixed final step required")
    budget = policy["budget"]
    _closed(budget, {"trial_count", "steps_per_trial", "max_seconds"}, "proposed fit budget")
    for name, high in (("trial_count", 12), ("steps_per_trial", 200), ("max_seconds", 300)):
        _int(budget[name], 1, high, "proposed " + name)
    values = {key: declaration[key] for key in ("lane_validation", "train_manifest", "fit_policy")}
    _pins(values, expected_bindings)
    rows = train["rows"]
    structural = sum(left["formal_view_sha256"] == right["formal_view_sha256"] for left in rows for right in rows)
    return _receipt("fit", declaration, values, status="blocked_no_contrastive_admission", row_count=len(rows),
                    rows=[{"id": row["id"], "input_sha256": row["input_sha256"], "masks": dict.fromkeys(MASKS, 0)} for row in rows],
                    proposed_optimizer_updates=budget["trial_count"] * budget["steps_per_trial"],
                    weak_structural_identity_pair_count=structural, unknown_pair_count=len(rows) ** 2 - structural,
                    permitted_negative_pair_count=0, semantic_positive_pair_count=0,
                    fit_authorized=False, training_target_bindings_present=True)


def validate_rank_declaration(declaration, *, expected_bindings):
    """Validate a frozen bank and reference-free query fields, without ranking."""
    _bounded(declaration)
    _bounded(expected_bindings)
    names = ("lane_validation", "queries", "frozen_bank", "ranking_policy", "checkpoint_binding")
    _role(declaration, names, RANK_SCHEMA, "rank declaration")
    lane, queries, bank, policy, checkpoint = (declaration[key] for key in names)
    _lane(lane)
    _role(queries, {"rows", "file_binding"}, "alignment-target-free-queries/v1", "target-free queries")
    _file(queries["file_binding"])
    _rows(queries["rows"], ROW_FIELDS, "query")
    _join(queries["rows"], lane)
    _bank(bank)
    other = bank["lane_validation"]
    _require(all(lane[name] == other[name] for name in ("profile_sha256", "lane_id", "stage", "dimension")),
             "query and bank representation profiles differ")
    candidates = {row["id"]: row for row in bank["rows"]}
    for query in queries["rows"]:
        if query["id"] in candidates:
            _require(_raw(query) == _raw({key: candidates[query["id"]][key] for key in ROW_FIELDS}),
                     "same-id query/bank source or vector differs")
    _ranking_policy(policy)
    if policy["mode"] == "raw_source_to_source":
        _require(checkpoint is None, "raw ranking cannot claim a projection checkpoint")
    else:
        _role(checkpoint, {"source_profile_sha256", "formal_feature_space_sha256", "file_binding"},
              "alignment-ranking-checkpoint-binding/v1", "projection checkpoint binding")
        _sha(checkpoint["source_profile_sha256"], "checkpoint source profile SHA")
        _require(checkpoint["source_profile_sha256"] == lane["profile_sha256"], "checkpoint source profile differs")
        _sha(checkpoint["formal_feature_space_sha256"], "formal feature space SHA")
        _file(checkpoint["file_binding"])
        _require(checkpoint["file_binding"] is not None, "projected ranking requires a declared checkpoint file pin")
    values = {key: declaration[key] for key in names}
    _pins(values, expected_bindings)
    return _receipt("rank", declaration, values, status="validated_reference_free_ranking_declaration_only",
                    row_count=len(queries["rows"]), rows=queries["rows"], candidate_count=len(bank["rows"]),
                    eligible_candidate_count=sum(row["status"] == "available" for row in bank["rows"]),
                    unavailable_candidate_count=sum(row["status"] == "unavailable" for row in bank["rows"]),
                    zero_ablation_candidate_count=sum(row["status"] == "ablation_zero" for row in bank["rows"]),
                    available_query_count=sum(row["status"] == "available" for row in queries["rows"]),
                    unavailable_query_count=sum(row["status"] == "unavailable" for row in queries["rows"]),
                    zero_ablation_query_count=sum(row["status"] == "ablation_zero" for row in queries["rows"]),
                    bank_eligibility_scope="available_source_rows_only", candidate_formal_bindings_present=True,
                    ranking_authorized=False, proposed_optimizer_updates=0)


def validate_score_declaration(declaration, *, expected_bindings):
    """Join declared saved results and reference bindings; fidelity scoring is blocked."""
    _bounded(declaration)
    _bounded(expected_bindings)
    names = ("saved_rankings", "frozen_bank", "references", "score_policy")
    _role(declaration, names, SCORE_SCHEMA, "score declaration")
    saved, bank, references, policy = (declaration[key] for key in names)
    _bank(bank)
    _role(saved, {"rows", "rank_declaration", "frozen_bank_sha256", "query_manifest_sha256", "ranking_policy",
                  "checkpoint_binding_sha256", "file_binding"}, "alignment-saved-ranking-bindings/v1", "saved ranking bindings")
    rank = saved["rank_declaration"]
    _bounded(rank)
    _require(type(rank) is dict, "complete rank declaration generation required")
    rank_roles = {name: value for name, value in rank.items() if name not in {"schema", "content_sha256"}}
    validate_rank_declaration(rank, expected_bindings=_bindings(rank_roles))
    _file(saved["file_binding"])
    for name in ("frozen_bank_sha256", "query_manifest_sha256", "checkpoint_binding_sha256"):
        _sha(saved[name], name)
    _require(saved["frozen_bank_sha256"] == _digest(bank), "saved rankings refer to a foreign frozen bank")
    _require(_raw(bank) == _raw(rank["frozen_bank"]), "saved rank generation uses a different frozen bank")
    _require(saved["query_manifest_sha256"] == _digest(rank["queries"]), "saved query manifest binding differs")
    _require(saved["checkpoint_binding_sha256"] == _digest(rank["checkpoint_binding"]), "saved checkpoint generation differs")
    _ranking_policy(saved["ranking_policy"])
    _require(_raw(saved["ranking_policy"]) == _raw(rank["ranking_policy"]), "saved ranking policy generation differs")
    if saved["ranking_policy"]["mode"] == "raw_source_to_source":
        _require(saved["checkpoint_binding_sha256"] == _digest(None), "raw saved rankings checkpoint binding differs")
    _rows(saved["rows"], {"id", "input_sha256", "status", "reason", "hits"}, "saved ranking")
    _require(len(saved["rows"]) == len(rank["queries"]["rows"]), "complete saved query ledger required")
    eligible = {row["id"] for row in bank["rows"] if row["status"] == "available"}
    for row, query in zip(saved["rows"], rank["queries"]["rows"], strict=True):
        _require(row["id"] == query["id"] and row["input_sha256"] == query["input_sha256"],
                 "saved rank generation query input or order differs")
        _require(type(row["status"]) is str and row["status"] in {"available", "unavailable", "not_executed"},
                 "known saved ranking status required")
        hits = row["hits"]
        _require(type(hits) is list, "ordered saved ranking hits required")
        if row["status"] != "available":
            _require(hits == [], "unavailable/unexecuted rankings cannot carry hits")
            _text(row["reason"], "saved ranking reason", maximum=4096)
            continue
        _require(query["status"] == "available", "unavailable/ablation query cannot have available ranking hits")
        _require(row["reason"] is None and 0 < len(hits) == min(saved["ranking_policy"]["top_k"], len(eligible)),
                 "complete available saved ranking required")
        seen = set()
        order = []
        for hit in hits:
            _closed(hit, {"candidate_id", "score"}, "saved ranking hit")
            _require(type(hit["candidate_id"]) is str and hit["candidate_id"] in eligible
                     and hit["candidate_id"] not in seen, "duplicate, unavailable or foreign ranked candidate")
            _require(type(hit["score"]) is float and math.isfinite(hit["score"]), "finite floating saved score required")
            seen.add(hit["candidate_id"])
            order.append((-hit["score"], hit["candidate_id"]))
        _require(order == sorted(order), "saved ranking score/ID tie order differs")
    _role(references, {"rows", "file_binding"}, "alignment-scoring-reference-bindings/v1", "scoring reference bindings")
    _file(references["file_binding"])
    _rows(references["rows"], {"id", "input_sha256", "reference_sha256", "admission_receipt_sha256",
                              "fidelity_evaluation", "status", "reason"}, "reference")
    _require(len(references["rows"]) == len(saved["rows"]), "complete ordered scoring reference ledger required")
    for reference, query in zip(references["rows"], saved["rows"], strict=True):
        _require(reference["id"] == query["id"] and reference["input_sha256"] == query["input_sha256"],
                 "scoring reference input or ordered identity differs")
        _int(reference["fidelity_evaluation"], 0, 0, "fidelity evaluation mask")
        _sha(reference["reference_sha256"], "declared reference SHA", nullable=True)
        _sha(reference["admission_receipt_sha256"], "declared admission receipt SHA", nullable=True)
        _require(type(reference["status"]) is str and reference["status"] in {"declared_unadmitted", "unavailable"},
                 "reference remains unadmitted or unavailable")
        if reference["status"] == "unavailable":
            _require(reference["reference_sha256"] is None and reference["admission_receipt_sha256"] is None,
                     "unavailable reference/admission bindings must stay null")
        else:
            _require(reference["reference_sha256"] is not None, "declared reference requires a binding")
        _text(reference["reason"], "pending/unavailable reference reason", maximum=4096)
    _role(policy, {"reference_policy", "metric_policy"}, "alignment-score-policy/v1", "score policy")
    _require(policy["reference_policy"] == "admitted_references_only/v1" and policy["metric_policy"] == "not_implemented/v1",
             "unimplemented admitted-reference scoring policy required")
    values = {key: declaration[key] for key in names}
    _pins(values, expected_bindings)
    return _receipt("score", declaration, values, status="blocked_no_admitted_fidelity_references",
                    row_count=len(saved["rows"]), rows=[{"id": row["id"], "input_sha256": row["input_sha256"],
                        "reference_status": row["status"], "fidelity_evaluation": 0, "score": None} for row in references["rows"]],
                    declared_reference_count=sum(row["status"] == "declared_unadmitted" for row in references["rows"]),
                    unavailable_reference_count=sum(row["status"] == "unavailable" for row in references["rows"]),
                    admitted_reference_count=0, scored_query_count=0, scoring_authorized=False,
                    proposed_optimizer_updates=0, scoring_reference_bindings_present=True)


__all__ = ["validate_fit_declaration", "validate_rank_declaration", "validate_score_declaration"]
