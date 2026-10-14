"""Lossless source-local sentence-boundary proposals from verified parent fields.

Every original character belongs to one contiguous partition piece, including
whitespace, headings, citations, notes and unresolved fragments. Punctuation
rules propose boundaries; they do not supply sentence gold or operative-law
classification. Producer subsection/raw_json segmentation is never an input.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re

from . import legal_cache_parent_occurrences as custody

SCHEMA = "legal-parent-sentence-candidates/v1"
POLICY = "conservative_literal_punctuation_partition/v1"
DEFAULT_LIMITS = {key: custody.DEFAULT_LIMITS[key] for key in ("max_parent_views", "max_source_characters",
    "max_total_source_characters", "max_report_bytes")}
DEFAULT_LIMITS.update(max_candidate_characters=8192, max_segments=4096, max_boundary_observations=4096,
    max_dependency_candidates=1024, context_characters=256,
    max_structural_issue_observations=4096, max_structural_issue_bytes=512 * 1024)
AUTHORITY = {**custody.AUTHORITY, **dict.fromkeys(("sentence_gold_qualified", "sentence_boundaries_verified",
    "complete_legal_context_verified", "dependency_targets_resolved"), False)}
ABBREVIATIONS = frozenset(("usc", "sec", "secs", "pub", "l", "ch", "chs", "stat", "sts", "no", "nos",
    "art", "arts", "div", "par", "pars", "subch", "vol", "p", "pp", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "inc", "co", "corp", "mr", "mrs", "ms", "dr"))
REFERENCE = re.compile(r"\b(?:subsections?|paragraphs?|sections?|chapters?|titles?)\s+(?:\([A-Za-z0-9]{1,16}\)|[0-9][A-Za-z0-9\-–]{0,31})"
    r"|\b(?:this|such|that)\s+(?:subsection|paragraph|section|chapter|title)\b", re.IGNORECASE)
HTML = re.compile(r"</?[A-Za-z][^>]{0,256}>")


class ParentSentenceCandidatesError(ValueError):
    """A complete custody pin, lossless partition or finite proposal bound differs."""


def _need(ok, message):
    if not ok: raise ParentSentenceCandidatesError(message)


def _limits(value):
    _need(value is None or type(value) is dict, "closed lower-only sentence limits required")
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        _need(key in result and type(bound) is int and 0 < bound <= result[key], "unknown or raised sentence bound")
        result[key] = bound
    return result


def parent_sentence_candidates_report_sha256(report):
    """FULL canonical digest including the internal sentence_candidates_sha256."""
    return custody._digest(report)


def _scan(text, remaining, structural_budget, bounds):
    """Retain every terminator observation; suppress ambiguous lexical cuts."""
    observations = []; cuts = []; stack = []; quote = None; errors = []
    closing = {"(": ")", "[": "]", "{": "}"}
    def error(observation):
        count = structural_budget["count"] + 1
        size = structural_budget["bytes"] + len(custody._wire(observation))
        _need(count <= bounds["max_structural_issue_observations"]
            and size <= bounds["max_structural_issue_bytes"], "complete structural issue count/byte bound exceeded before retention")
        structural_budget["count"] = count; structural_budget["bytes"] = size
        errors.append(observation)
    for position, char in enumerate(text):
        previous = text[position - 1] if position else ""
        following = text[position + 1] if position + 1 < len(text) else ""
        escaped = False
        if char in ('"', "'", "“", "”", "‘", "’"):
            before = position - 1
            while before >= 0 and text[before] == "\\": before -= 1
            escaped = (position - 1 - before) % 2 == 1
        if quote is not None:
            if char == quote and not escaped: quote = None
        elif char in ('"', "“", "‘") and not escaped:
            quote = {"“": "”", "‘": "’"}.get(char, char)
        elif char == "'" and not escaped and not previous.isalnum() and following and not following.isspace(): quote = "'"
        elif char == "”": error({"code": "unmatched_closing_double_quotation", "char_position": position})
        elif char == "’" and not (previous.isalnum() and following.isalnum()):
            error({"code": "ambiguous_apostrophe_or_unmatched_closing_single_quotation", "char_position": position})
        elif char in closing:
            _need(len(stack) < 64, "sentence delimiter depth bound exceeded")
            stack.append((closing[char], position))
        elif char in ")]}":
            if stack and stack[-1][0] == char: stack.pop()
            else: error({"code": "unmatched_closing_delimiter", "char_position": position})
        if char not in ".!?": continue
        _need(len(observations) < remaining, "complete boundary observation bound exceeded; no truncation")
        reasons = []
        if quote is not None: reasons.append("inside_quotation_boundary_unresolved")
        if stack: reasons.append("inside_delimiter_group_boundary_unresolved")
        if char == ".":
            if previous.isdigit() and following.isdigit(): reasons.append("decimal_or_number_component")
            at = position
            while at > 0 and text[at - 1].isalpha(): at -= 1
            word = text[at:position]
            if word.lower() in ABBREVIATIONS: reasons.append("abbreviation_period_unresolved")
            elif len(word) == 1 and word.isupper(): reasons.append("initial_or_dotted_citation_period_unresolved")
            if following == "." or previous == ".": reasons.append("ellipsis_or_repeated_period_unresolved")
        if following and not following.isspace(): reasons.append("non_whitespace_continuation_unresolved")
        proposal = not reasons
        observations.append({"char_start": position, "char_end": position + 1,
            "punctuation": char, "split_candidate": proposal, "issues": reasons,
            "boundary_verified": False})
        if proposal: cuts.append(position + 1)
    if quote is not None: error({"code": "unterminated_quotation"})
    if stack: error({"code": "unterminated_delimiter_group", "opening_positions": [n for _, n in stack]})
    if HTML.search(text): error({"code": "markup_in_literal_parent_field_not_supported_for_sentence_partition"})
    # Invalid whole-source state cannot select apparently easy earlier pieces.
    if errors: cuts = []
    return observations, cuts, errors


def _partition(text, cuts, errors):
    result = []; cursor = 0
    for end in list(dict.fromkeys(cuts + [len(text)])):
        if end <= cursor: continue
        start = cursor; core_start = start; core_end = end
        while core_start < core_end and text[core_start].isspace(): core_start += 1
        while core_end > core_start and text[core_end - 1].isspace(): core_end -= 1
        if start < core_start: result.append((start, core_start, "raw_whitespace_gap"))
        if core_start < core_end:
            kind = "unresolved_fragment" if errors or end not in cuts else "lexical_sentence_boundary_candidate"
            result.append((core_start, core_end, kind))
        if core_end < end: result.append((core_end, end, "raw_whitespace_gap"))
        cursor = end
    _need(cursor == len(text) and all(a[1] == b[0] for a, b in zip(result, result[1:])), "complete contiguous raw-character partition differs")
    return result


def _context(view, lo, hi, bounds, view_bounds, coordinates):
    from . import legal_parent_text_views as views
    prefix_lo = max(0, lo - bounds["context_characters"])
    suffix_hi = min(view["char_count"], hi + bounds["context_characters"])
    return {"prefix": views._selector(view, prefix_lo, lo, view_bounds, coordinates) if prefix_lo < lo else None,
        "suffix": views._selector(view, hi, suffix_hi, view_bounds, coordinates) if hi < suffix_hi else None,
        "coverage_scope": "bounded_exact_parent_field_window_only_not_legal_context_closure",
        "definitions_resolved": False, "cross_section_context_resolved": False}


def prepare_parent_sentence_candidates(parent_text_views_report, *, expected_parent_text_views_report_sha256,
        parent_text_views_inputs, limits=None):
    """Partition all supplied parent text; never use cache fragments as sentence gold."""
    from . import legal_parent_text_views as views
    bounds = _limits(limits)
    parent_views = custody._trusted_parent_views(parent_text_views_report, expected_parent_text_views_report_sha256,
        parent_text_views_inputs, bounds)
    rows = []; total_segments = 0; total_boundaries = 0; total_dependencies = 0; total_characters = 0; retained = 0
    structural_budget = {"count": 0, "bytes": 0}
    for envelope in parent_views["views"]:
        view = envelope["text_view"]
        row = {"row_ordinal": envelope["row_ordinal"], "row_group": envelope["row_group"],
            "row_group_ordinal": envelope["row_group_ordinal"], "raw_row_sha256": envelope["raw_row_sha256"],
            "parent_view_disposition": envelope["disposition"], "parent_view_issues": deepcopy(envelope["issues"]),
            "view_sha256": None, "source_identity": None, "source_text": None, "segments": [],
            "boundary_observations": [], "dependency_candidates": [], "issues": [],
            "autoformalization_eligible": False, "authority": dict(AUTHORITY)}
        if view is None:
            row["disposition"] = "unresolved_parent_text_view_unavailable"
            row["character_coverage_status"] = "not_applicable_missing_or_nontext_field"
            rows.append(row); continue
        text = view["text"]; total_characters += len(text)
        observations, cuts, errors = _scan(text, bounds["max_boundary_observations"] - total_boundaries, structural_budget, bounds)
        total_boundaries += len(observations)
        pieces = _partition(text, cuts, errors)
        _need(total_segments + len(pieces) <= bounds["max_segments"], "complete source partition population exceeds bound; no easy selection")
        total_segments += len(pieces)
        pending_dependencies = []
        for match in REFERENCE.finditer(text):
            _need(total_dependencies < bounds["max_dependency_candidates"], "complete dependency candidate population exceeds bound")
            pending_dependencies.append((match.start(), match.end())); total_dependencies += 1
        positions = [n for item in pieces for n in item[:2]]
        positions.extend(n for observation in observations for n in (observation["char_start"], observation["char_end"]))
        positions.extend(n for pair in pending_dependencies for n in pair)
        positions.extend(n for lo, hi, _ in pieces for n in (max(0, lo - bounds["context_characters"]), min(len(text), hi + bounds["context_characters"])))
        coordinates = views._byte_positions(text, positions)
        dependencies = []
        for lo, hi in pending_dependencies:
            selector = views._selector(view, lo, hi, parent_views["limits"], coordinates)
            candidate = {"selector": selector, "disposition": "unresolved_surface_reference_mention",
                "target_candidates": [], "selected_target": None, "reference_scope_verified": False,
                "region_intersections": custody._intersections(view, selector), "authority": dict(AUTHORITY)}
            candidate["dependency_candidate_id"] = custody._digest({"policy": POLICY, "candidate": candidate})
            retained += len(custody._wire(candidate)); _need(retained <= bounds["max_report_bytes"], "dependency observation byte bound exceeded")
            dependencies.append(candidate)
        segments = []
        for lo, hi, kind in pieces:
            selector = views._selector(view, lo, hi, parent_views["limits"], coordinates)
            reasons = deepcopy(errors)
            if hi - lo > bounds["max_candidate_characters"]:
                reasons.append({"code": "candidate_length_exceeds_sentence_profile"})
            if kind == "unresolved_fragment" and not errors: reasons.append({"code": "terminal_sentence_boundary_not_proposed"})
            segment = {"kind": kind, "selector": selector,
                "disposition": "raw_gap_observation" if kind == "raw_whitespace_gap" else "unresolved_unclassified_source_local_candidate",
                "region_intersections": custody._intersections(view, selector), "issues": reasons,
                "context": _context(view, lo, hi, bounds, parent_views["limits"], coordinates),
                "dependency_candidate_ids": [candidate["dependency_candidate_id"] for candidate in dependencies
                    if max(lo, candidate["selector"]["char_start"]) < min(hi, candidate["selector"]["char_end"])],
                "selected_as_legal_sentence": False, "autoformalization_eligible": False, "authority": dict(AUTHORITY)}
            segment["sentence_candidate_id"] = custody._digest({"policy": POLICY, "segment": segment})
            retained += len(custody._wire(segment)); _need(retained <= bounds["max_report_bytes"], "complete partition observation byte bound exceeded; no truncation")
            segments.append(segment)
        for observation in observations:
            observation["selector"] = views._selector(view, observation.pop("char_start"), observation.pop("char_end"), parent_views["limits"], coordinates)
        _need("".join(segment["selector"]["text"] for segment in segments) == text, "raw character content lost or changed during partition")
        row.update(view_sha256=view["view_sha256"], source_identity=deepcopy(view["source_identity"]),
            source_text=text, source_text_sha256=view["text_sha256"], coordinate_origin=deepcopy(view["coordinate_origin"]),
            source_character_count=len(text), source_utf8_bytes=view["utf8_bytes"], segments=segments,
            boundary_observations=observations, dependency_candidates=dependencies,
            marker_observations=deepcopy(view["marker_observations"]), issues=errors,
            disposition="complete_unclassified_source_local_partition",
            character_coverage_status="every_exact_raw_character_preserved_once_in_order")
        retained += len(custody._wire({k: v for k, v in row.items() if k not in {"segments", "dependency_candidates"}}))
        _need(retained <= bounds["max_report_bytes"], "complete sentence report byte bound exceeded; no truncation")
        rows.append(row)
    report = {"schema": SCHEMA, "segmentation_policy": POLICY, "limits": bounds,
        "parent_text_views_report_sha256": expected_parent_text_views_report_sha256,
        "expected_parent_row_sha256s": deepcopy(parent_views["expected_row_sha256s"]),
        "requested_parent_row_ordinals": deepcopy(parent_views["requested_row_ordinals"]),
        "rows": rows, "row_count": len(rows), "total_source_characters": total_characters,
        "total_segments": total_segments, "total_boundary_observations": total_boundaries,
        "total_dependency_candidates": total_dependencies, "population_complete": True,
        "total_structural_issue_observations": structural_budget["count"], "structural_issue_bytes": structural_budget["bytes"],
        "status_counts": dict(Counter(row["disposition"] for row in rows)),
        "coverage_scope": "all_independently_pinned_supplied_original_parent_string_fields_only",
        "diagnostic_cache_fragments_used_as_gold": False, "producer_segmentation_fields_used_as_gold": False,
        "all_candidates_autoformalization_ineligible": True, "authority": dict(AUTHORITY)}
    report["sentence_candidates_sha256"] = custody._digest(report); custody._wire(report, bounds["max_report_bytes"])
    return report


def validate_parent_sentence_candidates(report, parent_text_views_report, *, expected_report_sha256, **trusted_inputs):
    custody._sha(expected_report_sha256)
    _need(parent_sentence_candidates_report_sha256(report) == expected_report_sha256, "independent FULL sentence report differs")
    expected = prepare_parent_sentence_candidates(parent_text_views_report, **trusted_inputs)
    _need(custody._wire(report) == custody._wire(expected), "sentence candidate report differs from exact complete regeneration")
    return {"valid": True, "row_count": report["row_count"], "all_candidates_autoformalization_ineligible": True, "all_authority_false": True}


__all__ = ["ParentSentenceCandidatesError", "prepare_parent_sentence_candidates",
    "validate_parent_sentence_candidates", "parent_sentence_candidates_report_sha256"]
