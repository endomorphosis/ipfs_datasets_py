"""Complete source-local context observations for unreviewed sentence candidates.

The original partition and surface references are retained verbatim. Exact
parent-field/official-view substring pairs supply structural intersections,
never a selected original source, a legal role, or closed legal context.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib

from . import legal_cache_parent_occurrences as custody
from . import legal_parent_sentence_candidates as sentences
from . import legal_parent_text_views as parent_views
from . import legal_official_document_views as official_views
from . import legal_official_source_custody as acquisitions
from .legal_statutory_context import DEPENDENCY_KINDS

SCHEMA = "legal-candidate-context-inventory/v1"
POLICY = "all_exact_block_intersections_no_source_or_region_selection/v1"
DEFAULT_LIMITS = {"max_parent_rows": 32, "max_documents": 10, "max_source_blocks": 4096,
    "max_alignments": 8192, "max_partition_pieces": 4096, "max_reference_mentions": 1024,
    "max_intersections": 16384, "max_uncovered_ranges": 32768,
    "max_input_report_bytes": 32 * 1024**2, "max_report_bytes": 16 * 1024**2}
SENTENCE_FIELDS = {"expected_parent_text_views_report_sha256", "parent_text_views_inputs"}
ALIGNMENT_FIELDS = SENTENCE_FIELDS | {"document_inputs", "expected_document_population_sha256"}
AUTHORITY = {**sentences.AUTHORITY, **dict.fromkeys(("official_edition_authenticated",
    "producer_historical_source_binding_verified", "comparison_region_legal_classification_verified",
    "exception_scope_closed", "IR_semantic_fidelity_verified", "global_consistency_verified",
    "authenticated_review_received"), False)}


class CandidateContextInventoryError(ValueError):
    """A complete independent input pin, exact mapping, or finite bound differs."""


def _need(ok, message):
    if not ok:
        raise CandidateContextInventoryError(message)


def _wire(value, maximum=DEFAULT_LIMITS["max_report_bytes"]):
    return custody._wire(value, maximum)


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only context limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key], "unknown or raised context bound")
        result[key] = bound
    return result


def candidate_context_inventory_report_sha256(report):
    """FULL canonical digest including the internal context_inventory_sha256."""
    return _digest(report)


def _closed_inputs(value, required, label):
    _need(type(value) is dict and required <= set(value) and set(value) <= required | {"limits"},
        "closed complete " + label + " replay inputs required")


def _preflight_replay_inputs(sentence_inputs, alignment_inputs, bounds):
    """Refuse oversized nested populations before any report/input snapshot."""
    _closed_inputs(sentence_inputs, SENTENCE_FIELDS, "sentence")
    _closed_inputs(alignment_inputs, ALIGNMENT_FIELDS, "alignment")
    size = 0
    for inputs in (sentence_inputs, alignment_inputs):
        parent = inputs["parent_text_views_inputs"]
        _need(type(parent) is dict and custody.VIEW_FIELDS <= set(parent)
            and set(parent) <= custody.VIEW_FIELDS | {"page_limits", "limits"}, "closed complete parent replay bundle required")
        for key in ("row_ordinals", "expected_row_sha256s"):
            _need(type(parent[key]) is list and len(parent[key]) <= bounds["max_parent_rows"],
                "complete nested parent row population exceeds bound before snapshot")
        size += len(_wire(parent, bounds["max_input_report_bytes"]))
        _need(size <= bounds["max_input_report_bytes"], "nested parent replay bytes exceed bound before snapshot")
    documents = alignment_inputs["document_inputs"]
    _need(type(documents) is list and len(documents) <= bounds["max_documents"],
        "complete nested document population exceeds bound before snapshot")
    fields = {"descriptor", "raw_bytes", "expected_descriptor_sha256", "expected_raw_sha256",
        "expected_raw_bytes", "view_report", "expected_view_report_sha256"}
    total_raw = 0
    for item in documents:
        _need(type(item) is dict and set(item) == fields, "closed complete nested document replay record required")
        declared = item["expected_raw_bytes"]; raw = item["raw_bytes"]
        _need(type(declared) is int and 0 < declared <= acquisitions.MAX_HTML_BYTES,
            "bounded independently declared nested raw HTML size required before snapshot")
        _need(raw is None or type(raw) is bytes and len(raw) == declared,
            "exact bounded nested raw HTML bytes required before snapshot")
        total_raw += declared
        _need(total_raw <= 8 * 1024**2, "complete nested raw HTML byte population exceeds bound before snapshot")
        for key in fields - {"raw_bytes"}:
            size += len(_wire(item[key], bounds["max_input_report_bytes"]))
            _need(size <= bounds["max_input_report_bytes"], "nested document replay bytes exceed bound before snapshot")
    return size


def _trusted_inputs(sentence_report, alignment_report, sentence_pin, sentence_inputs, alignment_pin, alignment_inputs, bounds):
    from . import legal_parent_source_alignment as alignment
    custody._sha(sentence_pin); custody._sha(alignment_pin)
    size = _preflight_replay_inputs(sentence_inputs, alignment_inputs, bounds)
    _need(type(sentence_report) is dict and type(alignment_report) is dict, "complete input reports required")
    size += len(_wire(sentence_report, bounds["max_input_report_bytes"]))
    size += len(_wire(alignment_report, bounds["max_input_report_bytes"]))
    _need(size <= bounds["max_input_report_bytes"], "complete input reports exceed context bound before snapshot")
    _need(sentences.parent_sentence_candidates_report_sha256(sentence_report) == sentence_pin,
        "independent FULL sentence report differs")
    _need(alignment.parent_source_alignment_report_sha256(alignment_report) == alignment_pin,
        "independent FULL alignment report differs")
    # Both input owners must replay the same independently declared complete
    # physical parent population, not independently convenient subsets.
    _need(sentence_inputs["expected_parent_text_views_report_sha256"] == alignment_inputs["expected_parent_text_views_report_sha256"]
        and _wire(sentence_inputs["parent_text_views_inputs"]) == _wire(alignment_inputs["parent_text_views_inputs"]),
        "sentence and alignment parent replay populations differ")
    sentence_report = deepcopy(sentence_report); alignment_report = deepcopy(alignment_report)
    parent_report = alignment_report["parent_text_views_report"]
    alignment.validate_parent_source_alignment(alignment_report, parent_report,
        expected_report_sha256=alignment_pin, **alignment_inputs)
    sentences.validate_parent_sentence_candidates(sentence_report, parent_report,
        expected_report_sha256=sentence_pin, **sentence_inputs)
    _need(sentence_report["parent_text_views_report_sha256"] == sentence_inputs["expected_parent_text_views_report_sha256"],
        "sentence parent report pin differs")
    _need(len(parent_report["views"]) <= bounds["max_parent_rows"]
        and len(alignment_report["official_documents"]) <= bounds["max_documents"], "complete context source population exceeds bound")
    _need(len(sentence_report["rows"]) == len(alignment_report["rows"]) == len(parent_report["views"]),
        "complete physical parent row populations differ")
    return sentence_report, alignment_report, parent_report


def _slots():
    return [{"kind": kind, "status": "open_unreviewed_context_obligation", "semantic_attachment_verified": False,
        "closure_verified": False} for kind in DEPENDENCY_KINDS]


class _Budget:
    def __init__(self, bounds):
        self.bounds = bounds; self.bytes = 0; self.counts = Counter()

    def count(self, kind, bound):
        _need(self.counts[kind] < self.bounds[bound], "complete " + kind + " population exceeds bound before retention")
        self.counts[kind] += 1

    def retain(self, value):
        self.bytes += len(_wire(value, self.bounds["max_report_bytes"])) + 1
        _need(self.bytes <= self.bounds["max_report_bytes"], "complete context observation bytes exceed bound; no truncation")
        return value


def _uncovered(lo, hi, covered):
    cursor = lo; result = []
    for left, right in sorted(covered):
        left, right = max(left, lo), min(right, hi)
        if left >= right:
            continue
        if cursor < left:
            result.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < hi:
        result.append((cursor, hi))
    return result


def _source_tables(alignment_report, parent_report, bounds, budget):
    blocks = {}; documents = []; block_table = []
    for item in alignment_report["official_documents"]:
        index = item["document_index"]; report = item["view_report"]
        _need(type(index) is int and index == len(documents), "exact ordered official document indices required")
        documents.append(budget.retain({"document_index": index, "input_identity": deepcopy(item["input_identity"]),
            "view_report_sha256": official_views.document_view_report_sha256(report), "status": report["status"],
            "descriptor": deepcopy(report["descriptor"]), "normalized_view": deepcopy(report["normalized_view"]),
            "normalized_text": None if report["document"] is None else report["document"]["document_text"],
            "rendered_field_view": deepcopy(item["rendered_field_view"]),
            "issues": deepcopy(report["issues"]), "authority": dict(AUTHORITY)}))
        for block in (report["document"] or {}).get("blocks", []):
            budget.count("source_blocks", "max_source_blocks")
            ref = {"document_index": index, "block_index": block["block_index"], "block_id": block["block_id"]}
            key = (index, block["block_index"], block["block_id"])
            _need(key not in blocks, "duplicate physical official block reference")
            blocks[key] = block
            # The FULL source report pin retains original text/unknown metadata;
            # this table retains geometry and markup observations once.
            observation = {k: deepcopy(v) for k, v in block.items() if k not in {"text", "verbatim_text"}}
            block_table.append(budget.retain({"official_block_ref": ref, "original_block_sha256": _digest(block),
                "block_observation": observation, "text_characters": len(block["text"]), "authority_ref": "report.authority"}))
    parents = []
    for index, row in enumerate(parent_report["views"]):
        view = row["text_view"]
        parents.append(budget.retain({"parent_index": index, "row_ordinal": row["row_ordinal"],
            "row_group": row["row_group"], "row_group_ordinal": row["row_group_ordinal"], "raw_row_sha256": row["raw_row_sha256"],
            "parent_view_disposition": row["disposition"], "parent_view_issues": deepcopy(row["issues"]),
            "view_sha256": None if view is None else view["view_sha256"],
            "source_identity": None if view is None else deepcopy(view["source_identity"]),
            "coordinate_origin": None if view is None else deepcopy(view["coordinate_origin"]),
            "text": None if view is None else view["text"], "text_sha256": None if view is None else view["text_sha256"],
            "character_count": 0 if view is None else view["char_count"], "authority": dict(AUTHORITY)}))
    return {"parents": parents, "official_documents": documents, "official_blocks": block_table}, blocks


def _selector_projection(selector, *, parent_index=None, document_index=None):
    """Lossless geometry reference; the complete original selector is pinned."""
    _need((parent_index is None) != (document_index is None), "exactly one coordinate owner reference required")
    parent = parent_index is not None
    result = {"schema": "legal-candidate-context-selector-projection/v1", "selector_schema": selector["schema"],
        "coordinate_space": "parent_literal_field" if parent else "official_normalized_view",
        "source_ref": {"parent_index": parent_index, "view_sha256": selector["view_sha256"], "row_ordinal": selector["row_ordinal"]}
            if parent else {"document_index": document_index, "view_id": selector["view_id"], "document_id": selector["document_id"]},
        "char_start": selector["char_start"], "char_end": selector["char_end"],
        "text_sha256": selector["text_sha256"], "full_original_selector_sha256": _digest(selector),
        "owner_selector_identity": selector["selector_sha256"] if parent else selector["occurrence_id"]}
    for key in (("utf8byte_start", "utf8byte_end") if parent else ("utf8_byte_start", "utf8_byte_end")):
        result[key] = selector[key]
    result["projection_sha256"] = _digest(result)
    return result


class _ProjectionPool:
    """Exact deterministic interning; every reference occurrence is retained."""
    def __init__(self, budget):
        self.budget = budget; self.entries = []; self.by_sha256 = {}; self.reference_count = 0
        self.maximum_references = 2 * budget.bounds["max_intersections"] + budget.bounds["max_uncovered_ranges"]

    def reference(self, selector, **source_ref):
        _need(self.reference_count < self.maximum_references, "complete selector reference population exceeds bound before retention")
        self.reference_count += 1
        projection = _selector_projection(selector, **source_ref)
        key = projection["projection_sha256"]
        index = self.by_sha256.get(key)
        if index is None:
            _need(len(self.entries) < self.maximum_references, "complete unique selector projection population exceeds bound")
            self.budget.retain(projection)
            index = len(self.entries); self.entries.append(projection); self.by_sha256[key] = index
        else:
            _need(_wire(self.entries[index]) == _wire(projection), "selector projection digest collision")
        return {"schema": "legal-candidate-context-selector-reference/v1", "selector_projection_index": index}


def _comparison_context(selector, comparison, comparison_id, parent_index, view, official_report, blocks, parent_limits, budget, projections):
    lo, hi = selector["char_start"], selector["char_end"]
    intersections = []; covered = []; region_kinds = set(); neighbors = set()
    for anchor in comparison["exact_block_alignments"]:
        parent = anchor["parent_selector"]; left, right = max(lo, parent["char_start"]), min(hi, parent["char_end"])
        if left >= right:
            continue
        budget.count("intersections", "max_intersections")
        source = anchor["official_selector"]
        source_left = source["char_start"] + left - parent["char_start"]
        source_right = source_left + right - left
        parent_fragment = parent_views._selector(view, left, right, parent_limits)
        source_fragment = official_views._selector(official_report, source_left, source_right)
        _need(parent_fragment["text"] == source_fragment["text"], "exact alignment intersection characters differ")
        ref = anchor["official_block_ref"]; key = (ref["document_index"], ref["block_index"], ref["block_id"])
        block = blocks[key]; region_kinds.add(block["region_kind"])
        available = (official_report["document"] or {}).get("blocks", [])
        for neighbor in available[max(0, ref["block_index"] - 1):ref["block_index"] + 2]:
            neighbors.add((ref["document_index"], neighbor["block_index"], neighbor["block_id"]))
        covered.append((left, right))
        intersections.append(budget.retain({"alignment_id": anchor["alignment_id"], "official_block_ref": deepcopy(ref),
            "parent_intersection_selector": projections.reference(parent_fragment, parent_index=parent_index),
            "official_intersection_selector": projections.reference(source_fragment, document_index=comparison["document_index"]),
            "declared_region_kind_observation": block["region_kind"], "original_candidate_resegmented": False,
            "legal_region_classification_verified": False}))
    uncovered = []
    for left, right in _uncovered(lo, hi, covered):
        budget.count("uncovered_ranges", "max_uncovered_ranges")
        uncovered.append(budget.retain(projections.reference(parent_views._selector(view, left, right, parent_limits), parent_index=parent_index)))
    result = {"comparison_id": comparison_id, "document_index": comparison["document_index"],
        "comparison_view_available": official_report["status"] == "comparison_view_extracted",
        "exact_block_intersections": intersections, "uncovered_parent_ranges": uncovered,
        "declared_region_kind_observations": sorted(region_kinds),
        "neighboring_official_block_refs": [{"document_index": d, "block_index": b, "block_id": i} for d, b, i in sorted(neighbors)],
        "context_scope": "literal_block_intersections_and_immediate_comparison_block_neighbors_only",
        "selected_source_occurrence": None, "source_correspondence_verified": False,
        "legal_context_closure_verified": False, "authority_ref": "report.authority"}
    budget.retain({k: v for k, v in result.items() if k not in {"exact_block_intersections", "uncovered_parent_ranges"}})
    return result


def prepare_candidate_context_inventory(sentence_candidates_report, alignment_report, *,
        expected_sentence_candidates_report_sha256, sentence_inputs, expected_alignment_report_sha256,
        alignment_inputs, limits=None):
    """Replay complete inputs, then annotate every original piece/reference."""
    bounds = _limits(limits); budget = _Budget(bounds); projections = _ProjectionPool(budget)
    sentence_report, alignment_report, parent_report = _trusted_inputs(sentence_candidates_report, alignment_report,
        expected_sentence_candidates_report_sha256, sentence_inputs, expected_alignment_report_sha256, alignment_inputs, bounds)
    tables, blocks = _source_tables(alignment_report, parent_report, bounds, budget)
    alignment_table = []; comparison_table = []; rows = []; opportunities = []
    seen_alignments = set(); official_reports = [item["view_report"] for item in alignment_report["official_documents"]]
    for parent_index, (sentence_row, alignment_row, parent_row) in enumerate(zip(sentence_report["rows"], alignment_report["rows"], parent_report["views"])):
        _need((sentence_row["row_ordinal"], sentence_row["raw_row_sha256"], sentence_row["view_sha256"])
            == (alignment_row["row_ordinal"], alignment_row["raw_row_sha256"], alignment_row["view_sha256"]),
            "exact ordered sentence/alignment row bindings differ")
        _need([item["document_index"] for item in alignment_row["comparisons"]] == list(range(len(official_reports))),
            "complete ordered parent/document comparison population required")
        comparisons = []
        for comparison in alignment_row["comparisons"]:
            index = comparison["document_index"]; comparison_id = _digest({"parent_index": parent_index, "comparison": comparison})
            comparison_table.append(budget.retain({"comparison_id": comparison_id, "parent_index": parent_index,
                **{k: deepcopy(v) for k, v in comparison.items() if k != "exact_block_alignments"},
                "alignment_ids": [anchor["alignment_id"] for anchor in comparison["exact_block_alignments"]]}))
            comparisons.append((comparison, comparison_id))
            for anchor in comparison["exact_block_alignments"]:
                budget.count("alignments", "max_alignments")
                _need(anchor["alignment_id"] not in seen_alignments, "duplicate exact physical alignment identity")
                seen_alignments.add(anchor["alignment_id"])
                alignment_table.append(budget.retain({"parent_index": parent_index, "comparison_id": comparison_id, **deepcopy(anchor)}))
                ref = anchor["official_block_ref"]; block = blocks[(ref["document_index"], ref["block_index"], ref["block_id"])]
                if block["region_kind"] == "statute":
                    opportunity = {"parent_index": parent_index, "row_ordinal": sentence_row["row_ordinal"],
                        "alignment_id": anchor["alignment_id"], "official_block_ref": deepcopy(ref),
                        "original_block_sha256": _digest(block), "parent_selector": deepcopy(anchor["parent_selector"]),
                        "official_selector": deepcopy(anchor["official_selector"]),
                        "declared_region_kind_observation": "statute", "disposition": "unreviewed_declared_markup_statute_block_opportunity",
                        "legal_role_verified": False, "selected_as_legal_sentence": False, "autoformalization_eligible": False,
                        "context_dependency_slots": _slots(), "authority": dict(AUTHORITY)}
                    opportunity["opportunity_id"] = _digest({"policy": POLICY, "opportunity": opportunity})
                    opportunities.append(budget.retain(opportunity))
        view = parent_row["text_view"]
        result = {"parent_index": parent_index,
            "original_row_observation": {k: deepcopy(v) for k, v in sentence_row.items() if k not in {"segments", "dependency_candidates"}},
            "partition_piece_contexts": [], "surface_reference_contexts": [], "authority": dict(AUTHORITY)}
        for source_key, target_key, identity_key, kind, bound in (("segments", "partition_piece_contexts", "sentence_candidate_id", "partition_pieces", "max_partition_pieces"),
                ("dependency_candidates", "surface_reference_contexts", "dependency_candidate_id", "reference_mentions", "max_reference_mentions")):
            for original in sentence_row[source_key]:
                budget.count(kind, bound)
                _need(view is not None, "missing parent view cannot carry candidate observations")
                contexts = [_comparison_context(original["selector"], comparison, identifier, parent_index, view, official_reports[comparison["document_index"]],
                    blocks, parent_report["limits"], budget, projections) for comparison, identifier in comparisons]
                unit = {"source_observation_id": original[identity_key], "original_observation_sha256": _digest(original),
                    "original_observation": deepcopy(original), "comparison_contexts": contexts,
                    "context_dependency_slots": _slots(), "original_observation_selected": False, "authority_ref": "report.authority"}
                unit["context_unit_id"] = _digest({"policy": POLICY, "unit": unit})
                budget.retain({k: v for k, v in unit.items() if k != "comparison_contexts"})
                result[target_key].append(unit)
        # Originals, including every whitespace piece and surface mention,
        # must stay in exact physical row and original occurrence order.
        _need([unit["original_observation"] for unit in result["partition_piece_contexts"]] == sentence_row["segments"]
            and [unit["original_observation"] for unit in result["surface_reference_contexts"]] == sentence_row["dependency_candidates"],
            "complete original candidate/reference population differs")
        budget.retain({k: v for k, v in result.items() if k not in {"partition_piece_contexts", "surface_reference_contexts"}})
        rows.append(result)
    report = {"schema": SCHEMA, "context_policy": POLICY, "limits": bounds,
        "sentence_candidates_report_sha256": expected_sentence_candidates_report_sha256,
        "alignment_report_sha256": expected_alignment_report_sha256,
        "parent_text_views_report_sha256": sentence_inputs["expected_parent_text_views_report_sha256"],
        "document_population_sha256": alignment_inputs["expected_document_population_sha256"],
        "requested_parent_row_ordinals": deepcopy(sentence_report["requested_parent_row_ordinals"]),
        "expected_parent_row_sha256s": deepcopy(sentence_report["expected_parent_row_sha256s"]),
        "source_tables": tables, "comparison_table": comparison_table, "alignment_table": alignment_table,
        "selector_projection_table": projections.entries, "selector_projection_count": len(projections.entries),
        "selector_reference_count": projections.reference_count,
        "rows": rows, "source_block_opportunities": opportunities, "parent_row_count": len(rows),
        "official_document_count": len(official_reports), "source_block_count": len(tables["official_blocks"]),
        "comparison_count": len(comparison_table), "alignment_count": len(alignment_table),
        "partition_piece_count": budget.counts["partition_pieces"], "surface_reference_count": budget.counts["reference_mentions"],
        "intersection_count": budget.counts["intersections"], "uncovered_range_count": budget.counts["uncovered_ranges"],
        "source_block_opportunity_count": len(opportunities), "total_original_characters": sentence_report["total_source_characters"],
        "boundary_observation_count": sentence_report["total_boundary_observations"], "population_complete": True,
        "original_partition_and_references_retained_verbatim": True, "all_original_parent_characters_retained": True,
        "complete_official_views_referenced_by_independent_FULL_alignment_pin": True,
        "coverage_scope": "all_supplied_original_parent_pieces_references_and_all_independently_pinned_official_comparison_views",
        "original_HTML_coordinates_claimed": False, "paragraph_context_selectors_converted": False,
        "legal_region_classification_performed": False, "context_closure_verified": False,
        "authority": dict(AUTHORITY)}
    report["context_inventory_sha256"] = _digest(report)
    _wire(report, bounds["max_report_bytes"])
    return report


def validate_candidate_context_inventory(report, sentence_candidates_report, alignment_report, *, expected_report_sha256, **trusted_inputs):
    custody._sha(expected_report_sha256)
    _need(candidate_context_inventory_report_sha256(report) == expected_report_sha256, "independent FULL context inventory differs")
    expected = prepare_candidate_context_inventory(sentence_candidates_report, alignment_report, **trusted_inputs)
    _need(_wire(report) == _wire(expected), "context inventory differs from complete independent regeneration")
    return expected


__all__ = ["CandidateContextInventoryError", "prepare_candidate_context_inventory",
    "candidate_context_inventory_report_sha256", "validate_candidate_context_inventory"]
