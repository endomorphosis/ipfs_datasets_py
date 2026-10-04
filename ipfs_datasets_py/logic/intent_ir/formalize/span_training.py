"""Source-replayed SkillCenter span pairs for the shared IntentIR trainer.

Segmentation is not semantic annotation. Only spans accepted by the existing
bounded clause adapter receive weak targets; all other spans retain their gap.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from . import roundtrip_corpus as clauses

SCHEMA = "skillcenter-intent-span-pairs/v1"
MAX_PAIRS = 4096


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pins():
    from . import roundtrip, typed_compiler
    from ...formalization.autoencoder import domain_targets
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_text
    modules = (clauses, roundtrip, typed_compiler, domain_targets, autoencoder_paired_text)
    return {__name__: _sha(Path(__file__).read_bytes()),
            **{m.__name__: _sha(Path(m.__file__).read_bytes()) for m in modules}}


def _pairs(inventory):
    from .roundtrip import frame_to_intent_ir, intent_ir_to_frame, frame_to_sequence
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize, MAX_TOKENS

    sources = {row["source_id"]: row for row in inventory["sources"]}
    samples, omitted = [], []
    for span in inventory["spans"]:
        origin = {"span_id": span["id"], "source_id": span["source_id"], "split": span["split"]}
        if not span["eligible_for_pairing"]:
            omitted.append({**origin, "reason": span["reason"] or span["status"]})
            continue
        parent = sources[span["source_id"]]
        # Preserve complete heading ancestry. The old clause adapter reads
        # modality headings and rejects contradictory explicit modalities.
        # Canonical ATX rendering also preserves Setext heading semantics for
        # the existing heading-aware clause adapter; raw selectors stay below.
        view = "\n".join(["#" * h["level"] + " " + h["title"] for h in span["heading_context"]]
                         + [span["normalized_text"]])
        try:
            extracted, exclusions = clauses.extract_skillcenter_pairs({
                "id": span["id"], "split": span["split"], "instruction": view,
                "source_sha256": _sha(view.encode()),
                "license_expression": parent["license_expression"],
                "source_record": {"source_url": parent["source_url"]},
            })
        except ValueError:
            omitted.append({**origin, "reason": "outside_bounded_clause_target"})
            continue
        if len(extracted) != 1:
            omitted.append({**origin, "reason": "no_single_bounded_intent_target",
                            "adapter_reasons": sorted({e["reason"] for e in exclusions})})
            continue
        pair = extracted[0]
        if len(pair["instruction"].split()) > 48 or len(pair["instruction"]) > 4096:
            omitted.append({**origin, "reason": "contextual_instruction_exceeds_codec_limit"})
            continue
        # The existing codec gives deterministic typed scaffolding; learned
        # semantic slots remain the training target, not a proof of source intent.
        try:
            if len(tokenize(pair["instruction"])) >= MAX_TOKENS:
                raise ValueError("no room for source boundary token")
            # Frozen inference emits at most 96 tokens, including EOS.
            if any(len(tokenize(t)) >= 96 for t in (frame_to_sequence(pair["frame"]), pair["canonical_text"])):
                raise ValueError("target exceeds the frozen generation limit")
            native = frame_to_intent_ir(pair["frame"], instruction=pair["instruction"])
        except ValueError:
            omitted.append({**origin, "reason": "outside_shared_codec_target_bounds"})
            continue
        if intent_ir_to_frame(native) != pair["frame"]:
            raise ValueError("span target failed typed IntentIR frame round trip")
        targets = prepare_intent_targets(native).to_dict()
        source_spans = [
            {key: row[key] for key in ("start_char", "end_char", "start_byte", "end_byte")}
            for row in [*span["heading_context"], span]
        ]
        fragments = [parent["instruction"][s["start_char"]:s["end_char"]] for s in source_spans]
        pair["id"] = "skillcenter-span-pair:" + _sha(_wire({"span_id": span["id"], "frame": pair["frame"]}))
        pair["group_id"] = "skillcenter-source:" + span["source_id"]
        pair["provenance"] = {
            "kind": "skillcenter_weak_span", **origin,
            "source_sha256": span["source_sha256"],
            "source_identity": parent["source_identity"],
            "source_family": parent["source_family"],
            "source_url": parent["source_url"], "license_expression": parent["license_expression"],
            "spans": source_spans, "source_fragments": fragments,
            "heading_context": span["heading_context"], "block_context": span["block_context"],
            "adapter_input": view, "adapter_input_sha256": _sha(view.encode()),
            "label_rule": "sentence_span_then_bounded_explicit_clause_and_modal_heading/v1",
            "instruction_normalization": "canonical_atx_headings_and_whitespace_then_existing_clause_adapter",
            "actor_default": pair["provenance"]["actor_default"],
            "object_semantics": "opaque_phrase", "human_reviewed": False,
            "gold_source_semantics": False,
        }
        pair["native_intent_ir"] = native.to_dict()
        pair["native_projection_summary"] = [
            {"projection_id": p["projection_id"], "logic_family": p["logic_family"],
             "native_formula_count": len(p["native_formulas"])} for p in targets["projections"]
        ]
        samples.append(pair)
    return samples, omitted


def build_skillcenter_span_pairs(span_descriptor, *, include_authored=False):
    """Replay span/source provenance before making any training targets."""
    from .skillcenter_spans import load_skillcenter_span_corpus
    if type(include_authored) is not bool:
        raise ValueError("include_authored must be a Boolean")
    inventory = load_skillcenter_span_corpus(span_descriptor)
    samples, omitted = _pairs(inventory)
    if include_authored:
        samples.extend(clauses.authored_intent_pairs())
    samples, quarantined = clauses._quarantine_collisions(samples)
    if len(samples) > MAX_PAIRS:
        raise ValueError("span paired corpus exceeds the 4096-example development limit")
    source_counts = {kind: dict(Counter(r["split"] for r in samples if r["provenance"]["kind"] == kind))
                     for kind in ("skillcenter_weak_span", "authored_development_control")}
    report = {
        "schema": SCHEMA, "frame_schema": clauses.FRAME_SCHEMA,
        "span_corpus_descriptor": dict(span_descriptor), "producer_sha256": _pins(),
        "include_authored": include_authored, "samples": sorted(samples, key=lambda r: r["id"]),
        "omitted": omitted, "quarantined": quarantined,
        "counts": {"pairs": len(samples), "source_spans": len(inventory["spans"]),
                   "splits": dict(Counter(r["split"] for r in samples)), "by_source": source_counts,
                   "omission_reasons": dict(Counter(r["reason"] for r in omitted)),
                   "quarantined": len(quarantined)},
        "supervision": "unreviewed_bounded_source_span_labels_with_optional_authored_controls",
        "split_scope": "inherited_parent_source_families_with_cross_split_collisions_excluded",
        "human_reviewed_pair_count": 0, "gold_formal_target_count": 0,
        "source_content_executed": False, "provider_calls": 0,
        "semantic_correctness_verified": False, "qualified": False, "admitted": False,
        "unsupported": ["arbitrary_instruction_semantics", "conditionals", "preconditions", "effects",
                        "workflow_order", "nested_negation", "internal_object_phrase_semantics"],
    }
    report["report_sha256"] = _sha(_wire(report))
    return report


def validate_skillcenter_span_pairs(report):
    """Exact replay rejects changed labels, source locations or split membership."""
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("SkillCenter span pair corpus required")
    expected = build_skillcenter_span_pairs(report["span_corpus_descriptor"],
                                           include_authored=report["include_authored"])
    if _wire(report) != _wire(expected):
        raise ValueError("span pair corpus differs from source replay")
