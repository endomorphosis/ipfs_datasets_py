"""Deterministic review requests, never review results or accepted legal text.

All original partition pieces and surface reference mentions remain in the
queue. Each exact occurrence of a markup-declared statute block is an additional
opportunity to review, preserving both coordinate owners without cropping an
original candidate or silently discarding notes, metadata, gaps or differences.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from . import legal_candidate_context_inventory as contexts

SCHEMA = "legal-source-review-handoff/v1"
POLICY = "complete_unselected_context_inventory_review_requests/v1"
CONTEXT_FIELDS = {"sentence_candidates_report", "alignment_report", "expected_sentence_candidates_report_sha256",
    "sentence_inputs", "expected_alignment_report_sha256", "alignment_inputs"}
DEFAULT_LIMITS = {"max_review_units": 8192, "max_input_report_bytes": 16 * 1024**2,
    "max_report_bytes": 16 * 1024**2}
REVIEW_OBLIGATION_KINDS = ("producer_historical_source_correspondence", "official_edition_authentication",
    "region_legal_classification", "definition_closure", "reference_closure", "exception_scope_closure",
    "temporal_closure", "IR_semantic_fidelity", "global_consistency", "Lean4_kernel_check")
AUTHORITY = {**contexts.AUTHORITY, **dict.fromkeys(("source_review_completed", "legal_review_completed",
    "formal_review_completed", "gold_candidate_accepted", "review_receipt_issued"), False)}


class SourceReviewHandoffError(ValueError):
    """An independent population pin, complete replay or finite queue bound differs."""


def _need(ok, message):
    if not ok:
        raise SourceReviewHandoffError(message)


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only handoff limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key], "unknown or raised handoff bound")
        result[key] = bound
    return result


def source_review_handoff_report_sha256(report):
    """FULL canonical digest including the internal review_handoff_sha256."""
    return contexts._digest(report)


def _obligations():
    return [{"kind": kind, "status": "pending_independent_review", "verified": False,
        "closed": False} for kind in REVIEW_OBLIGATION_KINDS]


def prepare_source_review_handoff(candidate_context_inventory_report, *,
        expected_candidate_context_inventory_report_sha256, context_inputs, limits=None):
    """Regenerate complete context and preserve every original review denominator."""
    bounds = _limits(limits)
    contexts.custody._sha(expected_candidate_context_inventory_report_sha256)
    _need(type(candidate_context_inventory_report) is dict, "complete context inventory required")
    contexts._wire(candidate_context_inventory_report, bounds["max_input_report_bytes"])
    _need(type(context_inputs) is dict and CONTEXT_FIELDS <= set(context_inputs)
        and set(context_inputs) <= CONTEXT_FIELDS | {"limits"}, "closed complete context replay inputs required")
    _need(contexts.candidate_context_inventory_report_sha256(candidate_context_inventory_report)
        == expected_candidate_context_inventory_report_sha256, "independent FULL context inventory differs")
    sentence_report = context_inputs["sentence_candidates_report"]
    alignment_report = context_inputs["alignment_report"]
    replay_inputs = {k: v for k, v in context_inputs.items() if k not in {"sentence_candidates_report", "alignment_report"}}
    checked = contexts.validate_candidate_context_inventory(candidate_context_inventory_report,
        sentence_report, alignment_report, expected_report_sha256=expected_candidate_context_inventory_report_sha256,
        **replay_inputs)
    queue = []; retained = 0; status_counts = Counter(); piece_ids = []; reference_ids = []; opportunity_ids = []
    def unit(kind, source_id, original, *, parent_index, context_unit_id=None):
        nonlocal retained
        _need(len(queue) < bounds["max_review_units"], "complete review queue exceeds bound before retention; no selection")
        value = {"queue_ordinal": len(queue), "unit_kind": kind, "parent_index": parent_index,
            "source_observation_id": source_id, "original_observation_sha256": contexts._digest(original),
            "original_observation": deepcopy(original), "context_unit_id": context_unit_id,
            "context_inventory_report_sha256": expected_candidate_context_inventory_report_sha256,
            "status": "pending_independent_source_and_legal_review", "review_obligations": _obligations(),
            "original_candidate_cropped_or_replaced": False, "selected_as_legal_text": False,
            "autoformalization_eligible": False, "authority": dict(AUTHORITY)}
        value["review_unit_id"] = contexts._digest({"policy": POLICY, "unit": value})
        retained += len(contexts._wire(value, bounds["max_report_bytes"])) + 1
        _need(retained <= bounds["max_report_bytes"], "complete review queue byte bound exceeded before retention")
        queue.append(value); status_counts[kind] += 1
    for row in checked["rows"]:
        for item in row["partition_piece_contexts"]:
            original = item["original_observation"]; piece_ids.append(item["source_observation_id"])
            unit("original_parent_partition_piece", item["source_observation_id"], original,
                parent_index=row["parent_index"], context_unit_id=item["context_unit_id"])
    for row in checked["rows"]:
        for item in row["surface_reference_contexts"]:
            original = item["original_observation"]; reference_ids.append(item["source_observation_id"])
            unit("original_unresolved_surface_reference", item["source_observation_id"], original,
                parent_index=row["parent_index"], context_unit_id=item["context_unit_id"])
    for opportunity in checked["source_block_opportunities"]:
        opportunity_ids.append(opportunity["opportunity_id"])
        unit("exact_declared_markup_statute_block_opportunity", opportunity["opportunity_id"], opportunity,
            parent_index=opportunity["parent_index"])
    # Missing/non-string parent rows cannot disappear merely because no textual
    # queue unit can be constructed for them.
    for row in checked["rows"]:
        if not row["partition_piece_contexts"] and not row["surface_reference_contexts"]:
            original = row["original_row_observation"]
            unit("unavailable_parent_text_observation", contexts._digest(original), original,
                parent_index=row["parent_index"])
    parents = []
    for row in checked["rows"]:
        original = row["original_row_observation"]
        parents.append({"parent_index": row["parent_index"], "original_row_observation": deepcopy(original),
            "partition_piece_ids": [v["source_observation_id"] for v in row["partition_piece_contexts"]],
            "surface_reference_ids": [v["source_observation_id"] for v in row["surface_reference_contexts"]],
            "authority": dict(AUTHORITY)})
    blocks = []
    for item in checked["source_tables"]["official_blocks"]:
        block = item["block_observation"]
        blocks.append({"official_block_ref": deepcopy(item["official_block_ref"]),
            "original_block_sha256": item["original_block_sha256"],
            "declared_region_kind_observation": block["region_kind"], "text_characters": item["text_characters"],
            "char_start": block["char_start"], "char_end": block["char_end"],
            "legal_role_verified": False})
    comparison_denominators = [{**{k: deepcopy(v) for k, v in c.items()
            if k not in {"parent_partition", "official_partition", "alignment_ids", "authority"}},
        "alignment_count": len(c["alignment_ids"]), "parent_partition_piece_count": len(c["parent_partition"]),
        "official_partition_piece_count": len(c["official_partition"]),
        "uncovered_parent_characters": sum(p["char_end"] - p["char_start"] for p in c["parent_partition"] if p["coverage_kind"] == "uncovered"),
        "uncovered_official_characters": sum(p["char_end"] - p["char_start"] for p in c["official_partition"] if p["coverage_kind"] == "uncovered"),
        "selected_source_occurrence": None, "authority": dict(AUTHORITY)} for c in checked["comparison_table"]]
    _need(len(piece_ids) == checked["partition_piece_count"] and len(reference_ids) == checked["surface_reference_count"]
        and len(opportunity_ids) == checked["source_block_opportunity_count"], "complete queue occurrence population differs")
    report = {"schema": SCHEMA, "review_request_policy": POLICY, "limits": bounds,
        "candidate_context_inventory_report_sha256": expected_candidate_context_inventory_report_sha256,
        "sentence_candidates_report_sha256": checked["sentence_candidates_report_sha256"],
        "alignment_report_sha256": checked["alignment_report_sha256"],
        "parent_text_views_report_sha256": checked["parent_text_views_report_sha256"],
        "document_population_sha256": checked["document_population_sha256"],
        "parent_rows": parents, "official_document_denominator": deepcopy(checked["source_tables"]["official_documents"]),
        "official_block_denominator": blocks, "comparison_denominators": comparison_denominators,
        "queue_units": queue, "queue_unit_count": len(queue), "unit_kind_counts": dict(status_counts),
        "ordered_partition_piece_ids": piece_ids, "ordered_surface_reference_ids": reference_ids,
        "ordered_markup_opportunity_ids": opportunity_ids,
        "parent_row_count": checked["parent_row_count"], "official_document_count": checked["official_document_count"],
        "official_block_count": checked["source_block_count"], "comparison_count": checked["comparison_count"],
        "alignment_count": checked["alignment_count"], "partition_piece_count": len(piece_ids),
        "surface_reference_count": len(reference_ids), "declared_statute_block_opportunity_count": len(opportunity_ids),
        "total_original_characters": checked["total_original_characters"],
        "boundary_observation_count": checked["boundary_observation_count"],
        "all_original_observations_retained": True, "population_complete": True,
        "all_review_obligations_pending": True, "actual_review_receipts_created": False,
        "legal_role_classification_performed": False, "source_candidates_used_as_gold": False,
        "accepted_graphs_created": False, "coverage_scope": "complete_supplied_partition_reference_and_declared_markup_opportunity_review_population_only",
        "authority": dict(AUTHORITY)}
    report["review_handoff_sha256"] = contexts._digest(report)
    contexts._wire(report, bounds["max_report_bytes"])
    return report


def bind_source_dossier_review_questions(dossier):
    """Attach the existing pending obligations to a source dossier.

    This does not replay context, create a review receipt, or decide meaning.
    A dossier that already claims operative uses or a completed review is refused.
    """
    _need(type(dossier) is dict and dossier.get("schema") == "legal-source-edition-context-dossier/v1",
          "source dossier schema differs")
    _need(type(dossier.get("operative_use_count")) is int and dossier["operative_use_count"] == 0
          and type(dossier.get("operative_uses")) is list
          and dossier["operative_uses"] == [], "dossier cannot assert operative uses")
    _need(dossier.get("legal_meaning_manufactured") is False and dossier.get("review_manufactured") is False,
          "dossier cannot carry manufactured meaning or review")
    _need(dossier.get("crosswalk_status") in {"missing", "declared_unreviewed"},
          "crosswalk must stay missing or unreviewed")
    authority = dossier.get("authority")
    _need(type(authority) is dict and authority and all(value is False for value in authority.values()),
          "dossier authority must stay false")
    return {"schema": "legal-source-dossier-review-questions/v1", "review_obligations": _obligations(),
            "all_review_obligations_pending": True, "actual_review_receipts_created": False,
            "legal_role_classification_performed": False, "source_review_completed": False,
            "authority": dict(AUTHORITY)}


def validate_source_review_handoff(report, candidate_context_inventory_report, *, expected_report_sha256, **trusted_inputs):
    contexts.custody._sha(expected_report_sha256)
    _need(source_review_handoff_report_sha256(report) == expected_report_sha256, "independent FULL review handoff differs")
    expected = prepare_source_review_handoff(candidate_context_inventory_report, **trusted_inputs)
    _need(contexts._wire(report) == contexts._wire(expected), "review handoff differs from complete independent regeneration")
    return expected


__all__ = ["SourceReviewHandoffError", "prepare_source_review_handoff", "source_review_handoff_report_sha256",
    "bind_source_dossier_review_questions", "validate_source_review_handoff"]
