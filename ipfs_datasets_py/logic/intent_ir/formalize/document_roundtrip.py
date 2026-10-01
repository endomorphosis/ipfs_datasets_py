"""Compose source-bound clause inference without treating a document as one clause.

The existing Markdown/sentence inventory supplies complete semantic units and
their surrounding scope. Only independent units within the declared instruction
grammar reach the frozen learned copy codec. A post-inference surface agreement
check rejects changed actors, actions, objects and modalities; it supplies no
targets to either neural direction and grants no proof authority.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from . import copy_roundtrip, instruction_scope, roundtrip, skillcenter_spans
from ...formalization import coherent_spans, text_spans

SCHEMA = "intent-document-roundtrip/v1"
MAX_SOURCE_CHARS = 1_048_576
MAX_INFERENCE_UNITS = 256
_AUTHORITY = {"proof_authority": False, "execution_authority": False,
              "completion_authority": False, "omission_authority": False,
              "source_semantics_verified": False, "combination_semantics_verified": False}
_CONTEXT_MODAL = re.compile(
    r"\b(required|prohibited|forbidden|permitted|recommended|intended|must|shall|"
    r"should|may|never|avoid|not|no|anti[- ]?patterns?)\b", re.I)
_NONPHYSICAL_LINES = frozenset("\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_MODAL_SURFACES = {
    "intended": ("intends to",),
    "required": ("must", "shall", "is required to"),
    "prohibited": ("must not", "shall not", "is forbidden to", "is prohibited from"),
    "permitted": ("may", "is allowed to", "is permitted to"),
    "recommended": ("should", "is advised to", "is recommended to"),
}
_OMITTED_SURFACES = {
    "intended": ("", "please "),
    "required": ("must ", "shall "),
    "prohibited": ("must not ", "shall not ", "do not ", "never ",
                   "please do not ", "please never "),
    "permitted": ("may ",), "recommended": ("should ",),
}
_HEADINGS = {"intended": ("intended",), "required": ("required", "must do"),
             "prohibited": ("prohibited", "must not do"),
             "permitted": ("permitted",), "recommended": ("recommended",)}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def assess_frame_source_agreement(instruction, frame):
    """Check generated slots against supported source surfaces after inference.

    This bounded lexical contract is deliberately weaker than semantic truth.
    Objects remain opaque; an optional definite article follows the existing
    single-clause training convention. Conditions, references and coordination
    must already pass the unchanged source scope gate (normally they abstain).
    """
    scope = instruction_scope.assess_intent_instruction_scope(instruction)
    report = {"schema": "intent-frame-source-agreement/v1",
              "instruction_sha256": _sha(instruction.encode("utf-8", errors="surrogatepass")),
              "status": "rejected_source_scope", "matched": False,
              "scope": scope, "frame_sha256": None,
              "normalization": ["scope_approved_case_and_horizontal_whitespace",
                                "optional_terminal_period", "optional_definite_article"],
              "object_semantics": "opaque_phrase", **_AUTHORITY}
    try:
        frame = roundtrip.validate_frame(frame)
    except (ValueError, TypeError):
        report["status"] = "rejected_invalid_frame"
        return report
    report["frame_sha256"] = _sha(_wire(frame))
    if not scope["eligible_for_inference"]:
        return report
    actor, action, object_, modality = (frame[key] for key in roundtrip.FRAME_KEYS)
    surfaces = set()
    for object_surface in (object_, "the " + object_):
        body = action + " " + object_surface
        for actor_surface in (actor, "the " + actor):
            surfaces.update(actor_surface + " " + modal + " " + body
                            for modal in _MODAL_SURFACES[modality])
            if modality == "intended":
                surfaces.add("please ask " + actor_surface + " to " + body)
        if actor == "unspecified":
            surfaces.update(prefix + body for prefix in _OMITTED_SURFACES[modality])
            for heading in _HEADINGS[modality]:
                surfaces.update((heading + ": " + body, heading + ": please " + body))
    normalized = re.sub(r"[ \t]+", " ", instruction.strip()).lower().removesuffix(".")
    report["matched"] = normalized in surfaces
    report["status"] = ("supported_surface_agreement" if report["matched"]
                        else "rejected_predicted_slots_disagree_with_source")
    return report


def _inventory(source_text):
    source_sha = _sha(source_text.encode())
    if any(char in _NONPHYSICAL_LINES for char in source_text):
        # The reused legacy Markdown parser uses str.splitlines(). Do not let
        # alternate Unicode separators fabricate physical fences or headings.
        selector = text_spans.source_selector(source_text, 0, len(source_text))
        return [{"id": "unsupported-lines:" + source_sha, **selector,
            "source_sha256": source_sha, "heading_context": [], "structural_context": [],
            "block_context": {"kind": "unsupported_line_separators",
                **{k: selector[k] for k in ("start_char", "end_char", "start_byte", "end_byte")}},
            "status": "excluded", "reason": "nonphysical_line_separator_requires_safe_parser"}]
    spans = skillcenter_spans._source_spans({"instruction": source_text,
        "source_id": "instruction:" + source_sha, "source_sha256": source_sha,
        "domain": "intent_ir", "split": "inference"})
    structured = coherent_spans._markdown_units(source_text)
    inherited_scope = None
    for unit in structured:
        if unit["kind"] == "heading":
            inherited_scope = None
        if inherited_scope is not None:
            unit["context"].append(inherited_scope)
        text = source_text[unit["start"]:unit["end"]]
        if (unit["kind"] in {"paragraph", "list_item"} and _CONTEXT_MODAL.search(text)
                and re.search(r"\b(following|below|listed|these|those|such)\b", text, re.I)):
            inherited_scope = {"role": "lead_in", "start_char": unit["start"], "end_char": unit["end"]}
            unit["context"].append(inherited_scope)
    cursor = 0
    for span in spans:
        while cursor < len(structured) and structured[cursor]["end"] <= span["start_char"]:
            cursor += 1
        contexts = []
        for unit in structured[cursor:]:
            if unit["start"] >= span["end_char"]:
                break
            contexts.extend(unit["context"])
        span["structural_context"] = contexts
    return spans


def prepare_intent_document(source_text, checkpoint_descriptor=None, *, start_char=0, end_char=None,
                            search_recovery=True):
    """Infer complete clauses selected from a full, unchanged source document.

    ``start_char``/``end_char`` select an existing chunk while segmentation uses
    the *whole* document, so a chunk starting inside a code fence cannot acquire
    instruction authority. A sentence crossing a selection edge is retained as
    an unsupported partial unit. No missing context is fetched or synthesized.
    """
    if type(source_text) is not str:
        raise ValueError("exact source document required")
    if len(source_text) > MAX_SOURCE_CHARS:
        raise ValueError("source document exceeds the bounded inventory limit")
    if type(search_recovery) is not bool:
        raise ValueError("search recovery must be an explicit boolean")
    end_char = len(source_text) if end_char is None else end_char
    selection = text_spans.source_selector(source_text, start_char, end_char)
    counts, units, candidates = Counter(), [], []
    inferred = 0
    for span in _inventory(source_text):
        left, right = max(start_char, span["start_char"]), min(end_char, span["end_char"])
        if left >= right:
            continue
        selector = text_spans.source_selector(source_text, left, right)
        complete = left == span["start_char"] and right == span["end_char"]
        unit = {"unit_id": "intent-unit:" + _sha(_wire({
                    "source_sha256": span["source_sha256"], "start_char": left, "end_char": right})),
                **selector, "source_span": {key: span[key] for key in
                    ("id", "start_char", "end_char", "start_byte", "end_byte")},
                "block_kind": span["block_context"]["kind"],
                "full_block": span["block_context"], "heading_context": span["heading_context"],
                "structural_context": span["structural_context"],
                "complete_source_unit": complete,
                "status": "not_an_instruction_unit", "reason": span["reason"],
                "scope": None, "inference": None, "source_agreement": None,
                "greedy_inference": None,
                "model_input_normalization": "existing_sentence_whitespace_normalization",
                "accepted": False, **_AUTHORITY}
        if not complete:
            unit.update(status="unsupported_partial_unit", reason="selection_splits_source_unit")
        elif span["status"] != "candidate":
            if span["status"] != "excluded":
                unit["status"] = "unsupported_context_or_size"
        elif any(_CONTEXT_MODAL.search(h["title"]) for h in span["heading_context"]):
            unit.update(status="unsupported_context_or_size", reason="modal_heading_requires_composition")
        elif any(c["role"] in {"label", "lead_in", "parent_list", "structural_unit"}
                 for c in span["structural_context"]):
            unit.update(status="unsupported_context_or_size", reason="structural_scope_requires_composition")
        else:
            instruction = span["normalized_text"]
            scope = instruction_scope.assess_intent_instruction_scope(instruction)
            unit["scope"] = scope
            if not scope["eligible_for_inference"]:
                unit.update(status="unsupported_clause_grammar", reason=scope["reasons"][0])
            elif inferred >= MAX_INFERENCE_UNITS:
                unit.update(status="inference_budget_exhausted", reason="document_inference_unit_limit")
            else:
                inferred += 1
                inference = copy_roundtrip.prepare_copy_intent_instruction(instruction, checkpoint_descriptor)
                counts["encoder_executions"] += int(inference["learned"]["encoder"] is not None)
                counts["decoder_executions"] += int(inference["learned"]["decoder"] is not None)
                if search_recovery and checkpoint_descriptor is not None:
                    agreement = assess_frame_source_agreement(instruction, inference["learned"]["frame"])
                    if inference["candidate_intent_ir"] is None or not agreement["matched"]:
                        from .copy_search import prepare_copy_intent_search
                        unit["greedy_inference"] = inference
                        inference = prepare_copy_intent_search(instruction, checkpoint_descriptor)
                        counts["search_recovery_attempts"] += 1
                        counts["search_recovered_candidates"] += int(inference["candidate_intent_ir"] is not None)
                        counts["encoder_executions"] += int(inference["encoder_search"] is not None)
                        counts["decoder_executions"] += len(inference["decoder_searches"])
                unit["inference"] = inference
                unit.update(status=inference["status"], reason=inference["status"])
                learned = inference["learned"]
                if inference["candidate_intent_ir"] is not None:
                    agreement = assess_frame_source_agreement(instruction, learned["frame"])
                    unit["source_agreement"] = agreement
                    if agreement["matched"]:
                        unit.update(accepted=True, status="source_supported_clause_candidate",
                                    reason="learned_roundtrip_and_bounded_source_agreement")
                        candidates.append({"unit_id": unit["unit_id"],
                            "start_char": left, "end_char": right,
                            "candidate_intent_ir": inference["candidate_intent_ir"],
                            "projections": inference["projections"],
                            "extended_projections": inference["extended_projections"],
                            "inference_report_sha256": inference["report_sha256"], **_AUTHORITY})
                    else:
                        unit.update(status="rejected_source_disagreement", reason=agreement["status"])
        counts["units"] += 1
        counts["status:" + unit["status"]] += 1
        counts["source_characters"] += right - left
        counts["accepted_clause_characters"] += (right - left) if unit["accepted"] else 0
        units.append(unit)
    if "".join(unit["text"] for unit in units) != selection["text"]:
        raise ValueError("document inference must retain every selected source character")
    counts["accepted_clauses"] = len(candidates)
    counts["inference_attempts"] = inferred
    from . import copy_search
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_search
    report = {"schema": SCHEMA,
        "status": "partial_clause_advice" if candidates else "fail_open_no_supported_clauses",
        "source_sha256": _sha(source_text.encode()), "source_characters": len(source_text),
        "selection": {**selection, "sha256": _sha(selection["text"].encode())},
        "checkpoint_descriptor": checkpoint_descriptor,
        "search_recovery": search_recovery,
        "units": units, "candidates": candidates, "counts": dict(counts),
        "continue_planning": True, "raw_instruction_preserved": True,
        "complete_document_formalization": False,
        "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "producer_pins": {module.__name__: _sha(Path(module.__file__).read_bytes())
            for module in (copy_roundtrip, copy_search, instruction_scope, roundtrip, skillcenter_spans,
                           text_spans, coherent_spans, autoencoder_paired_search)},
        "producer_sha256": _sha(Path(__file__).read_bytes()),
        "limitations": ["independent_single_clause_candidates_only",
            "source_surface_agreement_is_not_proof_of_semantic_equivalence",
            "unsupported_regions_preserved_and_never_marked_formalized",
            "no_joint_workflow_or_document_equivalence_claim", "no_training_or_checkpoint_migration"],
        **_AUTHORITY}
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_intent_document_report(report, *, source_text, checkpoint_descriptor=None):
    """Replay source segmentation, installed numerical inference and admission."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("Intent document report required")
    selection = report.get("selection", {})
    expected = prepare_intent_document(source_text, checkpoint_descriptor,
        start_char=selection.get("start_char"), end_char=selection.get("end_char"),
        search_recovery=report.get("search_recovery"))
    if _wire(report) != _wire(expected):
        raise ValueError("Intent document report differs from source/numerical replay")
    return report
