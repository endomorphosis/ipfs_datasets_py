"""Replayed richer span targets admitted to the unchanged single-action codec.

Structured conditions, sequences and case-sensitive targets stay in the target
export. They must not be flattened into single-action numerical training pairs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

SCHEMA = "intent-rich-span-pairs/v1"


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pins():
    from . import rich_span_targets, structured_target_bridge, roundtrip, roundtrip_corpus
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_text
    return {__name__: _sha(Path(__file__).read_bytes()), **{
        m.__name__: _sha(Path(m.__file__).read_bytes()) for m in
        (rich_span_targets, structured_target_bridge, roundtrip, roundtrip_corpus, autoencoder_paired_text)}}


def build_rich_span_pairs(target_descriptor, *, include_authored=False):
    """Load and replay source targets, then retain exactly compatible frames."""
    from .rich_span_targets import load_skillcenter_rich_span_targets
    from .roundtrip import (frame_to_sequence, canonical_frame_text, intent_ir_to_frame)
    from .roundtrip_corpus import authored_intent_pairs, _quarantine_collisions
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize, MAX_TOKENS

    if type(include_authored) is not bool:
        raise ValueError("include_authored must be a Boolean")
    targets = load_skillcenter_rich_span_targets(target_descriptor)
    samples, omitted = [], []
    for row in targets["targets"]:
        target = row["target"]
        source = {"target_id": row["id"], "span_id": row["span_id"],
                  "source_id": row["source_id"], "split": row["split"]}
        if (target["kind"] != "action" or target["condition"] is not None
                or len(target["actions"]) != 1 or row["qualification"]["training_supported"] is not True):
            omitted.append({**source, "reason": "outside_single_action_codec", "target_kind": target["kind"]})
            continue
        frame, instruction = target["actions"][0], row["instruction"]
        try:
            wire, inverse = frame_to_sequence(frame), canonical_frame_text(frame)
            if (len(instruction) > 4096 or len(instruction.split()) > 48
                    or len(tokenize(instruction)) >= MAX_TOKENS
                    or any(len(tokenize(v)) >= 96 for v in (wire, inverse))):
                raise ValueError("frozen codec text limits exceeded")
        except ValueError:
            omitted.append({**source, "reason": "outside_single_action_text_bounds", "target_kind": target["kind"]})
            continue
        if intent_ir_to_frame(row["native_intent_ir"]) != frame:
            raise ValueError("native rich target differs from its single-action frame")
        samples.append({
            "id": "rich-span-pair:" + _sha(_wire({"id": row["id"], "frame": frame})),
            "split": row["split"], "group_id": "skillcenter-source:" + row["source_id"],
            "instruction": instruction, "frame": frame, "canonical_text": inverse,
            "native_intent_ir": row["native_intent_ir"],
            "provenance": {**row["provenance"], **source, "kind": "skillcenter_rich_weak_span",
                           "human_reviewed": False, "gold_source_semantics": False},
        })
    if include_authored:
        samples.extend(authored_intent_pairs())
    # The unchanged trainer lowercases and collapses input whitespace. Detect
    # mixed public/authored collisions using that exact view, while retaining
    # original instructions, source selectors and frames in admitted samples.
    # The old helper still checks semantic frame collisions as before.
    collision_view = [{**row, "instruction": " ".join(row["instruction"].lower().split())}
                      for row in samples]
    _, quarantined = _quarantine_collisions(collision_view)
    blocked = {row["id"] for row in quarantined}
    # The shared backend identifies input by tokens, not by display text.
    # Punctuation spacing can produce the same model input, and incompatible
    # weak labels are invalid even when every conflicting row is in TRAIN.
    model_inputs = defaultdict(list)
    for row in collision_view:
        model_inputs[tuple(tokenize(row["instruction"]))].append(row)
    for group in model_inputs.values():
        conflicting = len({frame_to_sequence(row["frame"]) for row in group}) > 1
        cross_partition = len({row["split"] for row in group}) > 1
        if not conflicting and not cross_partition:
            continue
        reason = ("conflicting_model_input_targets" if conflicting
                  else "cross_partition_model_input_collision")
        for row in group:
            if row["id"] not in blocked:
                quarantined.append({"id": row["id"], "source_id": row["provenance"]["source_id"],
                                    "split": row["split"], "reason": reason})
                blocked.add(row["id"])
    samples = [row for row in samples if row["id"] not in blocked]
    if len(samples) > 4096:
        raise ValueError("rich span pairs exceed the 4096-example development bound")
    kinds = sorted({r["provenance"]["kind"] for r in samples})
    report = {
        "schema": SCHEMA, "rich_target_descriptor": dict(target_descriptor),
        "include_authored": include_authored, "producer_sha256": _pins(),
        "samples": sorted(samples, key=lambda r: r["id"]), "omitted": omitted,
        "quarantined": quarantined,
        "counts": {"exported_targets": len(targets["targets"]), "pairs": len(samples),
                   "splits": dict(Counter(r["split"] for r in samples)),
                   "by_source": {kind: dict(Counter(r["split"] for r in samples if r["provenance"]["kind"] == kind))
                                 for kind in kinds},
                   "omission_reasons": dict(Counter(r["reason"] for r in omitted)), "quarantined": len(quarantined)},
        "supervision": "unreviewed_rich_span_single_action_labels_with_optional_authored_controls",
        "source_content_executed": False, "provider_calls": 0, "human_reviewed_pair_count": 0,
        "semantic_correctness_verified": False, "conditional_or_sequence_training": False,
        "qualified": False, "admitted": False,
    }
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_rich_span_pairs(report):
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("rich span pair corpus required")
    expected = build_rich_span_pairs(report["rich_target_descriptor"], include_authored=report["include_authored"])
    if _wire(expected) != _wire(report):
        raise ValueError("rich span pair corpus differs from source replay")
