"""Exact-source boundary candidates for a separate token-budget window builder.

Sentence/line positions are lexical candidates, not embedding semantics. Real
adjacent-vector decisions reuse ``group_semantic_atoms``. Callers supply any
structural boundaries from the whole source; this module never parses fragments,
loads a model, selects a provider, or certifies syntax/semantic correctness.
"""
from __future__ import annotations

import hashlib
import math
import re
from numbers import Real

from .chunker import sentence_source_spans_with_diagnostics
from .semantic_boundaries import group_semantic_atoms


class WindowBoundaryError(ValueError):
    """Invalid source, candidate, or explicitly supplied embedding configuration."""


def _lines(text, start=0, end=None):
    end = len(text) if end is None else end
    cursor = start
    cuts = []
    for line in text[start:end].splitlines(keepends=True):
        cursor += len(line)
        if cursor < end:
            cuts.append(cursor)
    return cuts


def prepare_window_atoms(text, *, format="prose", structural_boundaries=()):
    """Prepare exact complete atoms and separately ranked boundary candidates.

    ``structural_boundaries`` contains caller-supplied character offsets in this
    exact text, usually projected from a whole-source syntax/Markdown/diff plan.
    Endpoint offsets are harmless and omitted. Their syntax safety is not
    independently verified here. Prose is sentence-split within each supplied
    block. Other formats use supplied structural units as atoms, or exact lines
    if no structural cuts are supplied. Interior lines remain explicitly lexical
    fallback candidates, even inside structural atoms; they are never AST cuts.
    """
    if type(text) is not str or format not in {"prose", "code", "diff", "opaque"}:
        raise WindowBoundaryError("invalid_source_or_format")
    try:
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        supplied = list(structural_boundaries)
    except (TypeError, UnicodeEncodeError):
        raise WindowBoundaryError("invalid_source_or_structural_boundaries") from None
    if any(type(point) is not int or not 0 <= point <= len(text) for point in supplied):
        raise WindowBoundaryError("structural_boundaries_must_be_source_offsets")
    structural = sorted({point for point in supplied if 0 < point < len(text)})
    candidates = {point: {"offset": point, "kind": "supplied_structure", "priority": 3}
        for point in structural}
    cuts = set(structural)
    sentence_reports = []
    if format == "prose":
        blocks = [0, *structural, len(text)]
        for start, end in zip(blocks, blocks[1:]):
            if start == end:
                continue
            report = sentence_source_spans_with_diagnostics(text[start:end])
            sentence_reports.append({"start_char": start, "end_char": end, **report})
            for point, _ in report["spans"][1:]:
                absolute = start + point
                cuts.add(absolute)
                candidates.setdefault(absolute, {"offset": absolute, "kind": "sentence", "priority": 1})
        atom_kind = "sentence"
    else:
        for point in _lines(text):
            candidates.setdefault(point, {"offset": point, "kind": "line_fallback", "priority": 1})
        if not structural:
            cuts.update(_lines(text))
        atom_kind = "structural_unit" if structural else "lexical_line"
    points = [0, *sorted(cuts), len(text)]
    atoms = [{"start_char": start, "end_char": end, "kind": atom_kind}
        for start, end in zip(points, points[1:]) if start < end]
    assert "".join(text[row["start_char"]:row["end_char"]] for row in atoms) == text
    semantic_comparison_required = any(row["start_char"] not in structural for row in atoms[1:])
    return {"schema": "source-window-boundary-atoms/v1", "source_sha256": source_hash,
        "source_characters": len(text), "format": format, "atoms": atoms,
        "structural_boundaries": structural,
        "candidates": [candidates[point] for point in sorted(candidates)],
        "sentence_reports": sentence_reports, "source_coverage_complete": True,
        "semantic_comparison_required": semantic_comparison_required,
        "structural_safety_binding": "caller_supplied_not_verified",
        "parser_called": False, "model_loaded": False,
        "syntax_preservation_verified": False, "semantic_correctness_verified": False,
        "proof_authority": False, "execution_authority": False}


def prepare_window_boundaries(text, *, format="prose", structural_boundaries=(),
                              embedder=None, embedding_eligible=None,
                              max_embedding_chars=1024, similarity_threshold=0.5,
                              semantic_selection="threshold"):
    """Add actual low-cosine boundaries to a source-bound candidate plan.

    ``embedder(list[str])`` must return ordered real vectors, optionally from an
    explicitly bound precomputed vector bank. If supplied, ``embedding_eligible``
    is mandatory and must check the real model's untruncated token budget (512
    including special tokens for pinned GTE-small). No character bound suffices.
    ``semantic_selection="ranked"`` ranks all measured adjacent cosines relative
    to one another instead of requiring an absolute threshold crossing. Existing
    structural boundaries retain priority. No topic-change correctness is claimed.
    Embedding failure is reported as structural fallback. The separate window
    builder must still recount every final payload and respect the token budget.
    """
    if (type(semantic_selection) is not str or semantic_selection not in {"threshold", "ranked"}
            or embedder is not None and not callable(embedder)
            or embedding_eligible is not None and not callable(embedding_eligible)
            or embedder is not None and embedding_eligible is None
            or type(max_embedding_chars) is not int or max_embedding_chars < 1
            or isinstance(similarity_threshold, bool) or not isinstance(similarity_threshold, Real)
            or not math.isfinite(similarity_threshold) or not -1 <= similarity_threshold <= 1):
        raise WindowBoundaryError("invalid_embedding_configuration")
    plan = prepare_window_atoms(text, format=format, structural_boundaries=structural_boundaries)
    candidates = {row["offset"]: dict(row) for row in plan["candidates"]}
    native = None
    status = "structural_only" if embedder is None else "not_required"
    semantic_count = 0
    if embedder is not None and plan["semantic_comparison_required"]:
        intervals = [(row["start_char"], row["end_char"]) for row in plan["atoms"]]
        strong = set(plan["structural_boundaries"])
        barriers = [index for index, (start, _) in enumerate(intervals) if index and start in strong]
        native = group_semantic_atoms(text, intervals, embedder=embedder,
            max_chars=max(1, len(text)), min_chars=0, max_embedding_chars=max_embedding_chars,
            similarity_threshold=similarity_threshold, barriers=barriers,
            embedding_eligible=embedding_eligible, on_embedding_error="structural")
        status = native["embedding_status"]
        if native["embeddings_used"]:
            for decision in native["boundaries"]:
                if decision["reason"] != "similarity_below_threshold":
                    continue
                point = intervals[decision["before_atom"]][0]
                if candidates.get(point, {}).get("priority", 0) < 2:
                    candidates[point] = {"offset": point, "kind": "semantic", "priority": 2}
                    semantic_count += 1
    report = {**plan, "schema": "source-window-boundaries/v1",
        "atom_preparation_schema": plan["schema"],
        "candidates": [candidates[point] for point in sorted(candidates)], "grouping": native,
        "diagnostics": {"embedding_status": status,
            "embeddings_used": bool(native and native["embeddings_used"]),
            "token_budget_checked": bool(native and native["config"]["token_budget_checked"]),
            "semantic_candidates": semantic_count, "max_embedding_chars": max_embedding_chars,
            "similarity_threshold": float(similarity_threshold),
            "final_payload_token_budget_checked": False,
            "single_atom_embedding_skipped": embedder is not None and len(plan["atoms"]) < 2,
            "all_joins_structural_embedding_skipped": embedder is not None
                and len(plan["atoms"]) > 1 and not plan["semantic_comparison_required"],
            "fallback_line_cuts_are_syntax_safe": False,
            "model_loading_performed": False}}
    return rank_semantic_boundaries(report) if semantic_selection == "ranked" else report



def rank_semantic_boundaries(report):
    """Rank existing, source-bound adjacent cosines without computing new scores.

    This consumes a ``prepare_window_boundaries`` report. Only paired eligible
    atoms with actual finite cosine scores become priority-2 candidates; supplied
    structural boundaries retain their higher priority. Scores above the native
    threshold can still be ranked, without being declared absolute topic breaks.

    Compact reports may omit ``normalized_vectors`` when ``vector_bank_ref`` is
    a caller-verified artifact pin (path, SHA-256, size in bytes). The caller owns
    checking that artifact and its vector-file pins; this pure helper performs
    no filesystem/model access or vector normalization. Source hashes bind the
    nested reports to each other; callers must check the actual source payload.
    """
    def fail():
        raise WindowBoundaryError("invalid_scored_boundary_report")

    def is_hash(value):
        return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None

    if (type(report) is not dict or report.get("schema") != "source-window-boundaries/v1"
            or not is_hash(report.get("source_sha256"))
            or type(report.get("source_characters")) is not int or report["source_characters"] < 0
            or type(report.get("atoms")) is not list
            or type(report.get("candidates")) is not list
            or type(report.get("structural_boundaries")) is not list
            or type(report.get("diagnostics")) is not dict):
        fail()
    atoms, cursor = [], 0
    for atom in report["atoms"]:
        if (type(atom) is not dict or type(atom.get("start_char")) is not int
                or type(atom.get("end_char")) is not int
                or atom["start_char"] != cursor
                or not cursor < atom["end_char"] <= report["source_characters"]):
            fail()
        atoms.append({"start_char": atom["start_char"], "end_char": atom["end_char"]})
        cursor = atom["end_char"]
    if cursor != report["source_characters"]:
        fail()
    structural = report["structural_boundaries"]
    starts = {atom["start_char"] for atom in atoms[1:]}
    if (any(type(point) is not int or point not in starts for point in structural)
            or structural != sorted(set(structural))):
        fail()
    candidates = {}
    previous = 0
    for row in report["candidates"]:
        if (type(row) is not dict or set(row) not in ({"offset", "kind", "priority"},
                {"offset", "kind", "priority", "semantic_score"})
                or type(row.get("offset")) is not int
                or not previous < row["offset"] < report["source_characters"]
                or type(row.get("priority")) is not int or row["priority"] not in (1, 2, 3)
                or type(row.get("kind")) is not str or not row["kind"].strip()):
            fail()
        if (row["priority"] == 3) != (row["offset"] in structural):
            fail()
        # Re-ranking cannot trust a previously inserted score or priority; all
        # nonstructural scores below are derived only from the native decisions.
        if "semantic_score" in row and (row["priority"] != 2
                or isinstance(row["semantic_score"], bool)
                or not isinstance(row["semantic_score"], Real)
                or not math.isfinite(row["semantic_score"])
                or not -1 <= row["semantic_score"] <= 1):
            fail()
        candidates[row["offset"]] = {key: value for key, value in row.items() if key != "semantic_score"}
        previous = row["offset"]
    if not starts <= candidates.keys() or not set(structural) <= candidates.keys():
        fail()
    native = report.get("grouping")
    scored, promoted = 0, 0
    if native is not None:
        if (type(native) is not dict or native.get("schema") != "source-semantic-boundaries/v1"
                or native.get("source_sha256") != report["source_sha256"]
                or native.get("atoms") != atoms
                or type(native.get("boundaries")) is not list
                or len(native["boundaries"]) != max(0, len(atoms)-1)
                or type(native.get("embedding_input_atom_indexes")) is not list
                or type(native.get("config")) is not dict
                or type(native.get("embeddings_used")) is not bool
                or native["embeddings_used"] != (native.get("embedding_status") == "embedded")
                or not is_hash(native.get("normalized_vectors_sha256"))
                or not is_hash(native.get("embedding_input_sha256"))):
            fail()
        indexes = native["embedding_input_atom_indexes"]
        if (any(type(index) is not int or not 0 <= index < len(atoms) for index in indexes)
                or indexes != sorted(set(indexes))):
            fail()
        expected_barriers = [i for i, atom in enumerate(atoms) if i and atom["start_char"] in structural]
        if native["config"].get("barriers") != expected_barriers:
            fail()
        if native["embeddings_used"] and native["config"].get("token_budget_checked") is not True:
            fail()
        if "normalized_vectors" in native:
            if (type(native["normalized_vectors"]) is not list
                    or len(native["normalized_vectors"]) != (len(indexes) if native["embeddings_used"] else 0)):
                fail()
        elif native["embeddings_used"]:
            pin = report.get("vector_bank_ref")
            if (type(pin) is not dict or not is_hash(pin.get("sha256"))
                    or type(pin.get("path")) is not str or not pin["path"].strip()
                    or type(pin.get("size_bytes")) is not int or pin["size_bytes"] < 0):
                fail()
        eligible = set(indexes) if native["embeddings_used"] else set()
        for index, decision in enumerate(native["boundaries"], 1):
            if type(decision) is not dict or type(decision.get("before_atom")) is not int or decision["before_atom"] != index:
                fail()
            score = decision.get("cosine_similarity")
            paired = index-1 in eligible and index in eligible
            if not paired:
                if score is not None:
                    fail()
                continue
            if (isinstance(score, bool) or not isinstance(score, Real)
                    or not math.isfinite(score) or not -1 <= score <= 1):
                fail()
            scored += 1
            point = atoms[index]["start_char"]
            if candidates[point]["priority"] < 3:
                candidates[point] = {"offset": point, "kind": "semantic_ranked", "priority": 2,
                    "semantic_score": float(score)}
                promoted += 1
    # Every priority-2 candidate must be supported by the current native report,
    # including a replay of a ranked report; malformed stale priorities fail.
    if any(row["priority"] == 2 and "semantic_score" not in row for row in candidates.values()):
        fail()
    return {**report, "candidates": [candidates[point] for point in sorted(candidates)],
        "diagnostics": {**report["diagnostics"], "semantic_selection": "ranked",
            "semantic_candidates": promoted, "scored_adjacent_pairs": scored,
            "semantic_score_order": "ascending_cosine_within_priority_2",
            "absolute_topic_break_claimed": False, "new_scores_computed": False,
            "vector_bank_pin_binding": "caller_verified" if "vector_bank_ref" in report else "native_report",
            "source_payload_binding": "caller_verified_sha256"}}


__all__ = ["prepare_window_atoms", "prepare_window_boundaries", "rank_semantic_boundaries", "WindowBoundaryError"]
