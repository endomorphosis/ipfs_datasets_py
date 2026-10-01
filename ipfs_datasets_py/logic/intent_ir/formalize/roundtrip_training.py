"""Offline paired Intent training and free-running development evaluation.

Training labels never enter inference. The held-out records are evaluated with
teacher forcing disabled, and invalid/OOV predictions remain in denominators.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .roundtrip import (FRAME_KEYS, _raw, _sha, canonical_frame_text, frame_to_sequence,
                       sequence_to_frame, frame_to_intent_ir, intent_ir_to_frame,
                       normalized_text_to_frame, register_intent_roundtrip_checkpoint,
                       load_intent_roundtrip_checkpoint)


def _validated_samples(corpus):
    if type(corpus) is not dict or type(corpus.get("samples")) is not list or not corpus["samples"]:
        raise ValueError("nonempty paired corpus required")
    samples = corpus["samples"]
    if len(samples) > 4096:
        raise ValueError("development corpus bound exceeded")
    ids, groups, instructions, frames = set(), {}, {}, {}
    for row in samples:
        if type(row) is not dict or not {"id", "split", "group_id", "instruction", "frame", "canonical_text", "provenance"} <= set(row):
            raise ValueError("paired sample fields required")
        if row["split"] not in {"train", "validation", "test"} or type(row["id"]) is not str or row["id"] in ids:
            raise ValueError("unique paired sample IDs and fixed splits required")
        ids.add(row["id"])
        if type(row["instruction"]) is not str or not row["instruction"].strip() or len(row["instruction"].split()) > 48:
            raise ValueError("bounded paired instruction required")
        wire = frame_to_sequence(row["frame"])
        if row["canonical_text"] != canonical_frame_text(row["frame"]):
            raise ValueError("canonical inverse label differs from semantic frame")
        for key, mapping in ((row["group_id"], groups), (" ".join(row["instruction"].lower().split()), instructions), (wire, frames)):
            if key in mapping and mapping[key] != row["split"]:
                raise ValueError("source/semantic family split leakage")
            mapping[key] = row["split"]
    if not any(s["split"] == "train" for s in samples) or not any(s["split"] == "validation" for s in samples):
        raise ValueError("distinct training and validation families required")
    return samples


def build_training_pairs(samples):
    """One encoder pair per instruction; deduplicate inverse semantic frames."""
    pairs, inverse_seen = [], set()
    for row in samples:
        wire = frame_to_sequence(row["frame"])
        pairs.append({"id": "encode:" + row["id"], "source": " ".join(row["instruction"].lower().split()),
                      "target": wire, "direction": "encode"})
        if wire not in inverse_seen:
            inverse_seen.add(wire)
            pairs.append({"id": "decode:" + row["id"], "source": wire,
                          "target": row["canonical_text"], "direction": "decode"})
    return pairs


def train_intent_roundtrip(corpus, output, *, lexical_initializer_path=None,
                          epochs=100, max_seconds=300, hidden_size=96, embedding_dim=48):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import train_paired_text, load_paired_text
    samples = _validated_samples(corpus)
    train = build_training_pairs([r for r in samples if r["split"] == "train"])
    tune = build_training_pairs([r for r in samples if r["split"] == "validation"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus_raw = _raw(corpus)
    (output / "corpus.json").write_bytes(corpus_raw)
    backend = train_paired_text(train, tune, output_dir=output / "model",
        lexical_initializer_path=Path(lexical_initializer_path).resolve() if lexical_initializer_path is not None else None,
        epochs=epochs, max_seconds=max_seconds,
        hidden_size=hidden_size, embedding_dim=embedding_dim)
    descriptor = register_intent_roundtrip_checkpoint(backend, output=output, corpus_sha256=_sha(corpus_raw))
    (output / "descriptor.json").write_bytes(_raw(descriptor))
    loaded = load_paired_text(backend)
    receipt = {"schema": "intent-roundtrip-training/v1", "checkpoint": descriptor,
        "corpus_sha256": _sha(corpus_raw), "shared_backend": backend,
        "source_split_counts": {split: sum(r["split"] == split for r in samples) for split in ("train", "validation", "test")},
        "training_pair_count": len(train), "validation_pair_count": len(tune),
        "test_used_for_training_or_tuning": False,
        "shared_training": loaded["training"], "normalized_wording_requested": True,
        "supervision": corpus.get("supervision", "caller_supplied_paired_development_targets"),
        "corpus_schema": corpus.get("schema"),
        "source_kind_counts": dict(Counter(str(r["provenance"].get("kind", "unspecified")) for r in samples)),
        "scope": "single_clause_actor_action_object_modality",
        "semantic_correctness_verified": False, "proofs_run": False, "published": False}
    (output / "training-receipt.json").write_bytes(_raw(receipt))
    return receipt


def _parse_prediction(row, parser):
    if row["status"] != "generated":
        return None
    try:
        return parser(row["generated_text"])
    except ValueError:
        return None


def _metrics(rows):
    count = len(rows)
    if not count:
        return {"count": 0}
    bools = ("encode_valid", "encode_exact", "native_ir_valid", "decode_exact",
             "composed_exact", "cycle_consistent", "encoder_oov", "deployable_candidate", "deployable_exact")
    return {"count": count, **{key + "_rate": sum(r[key] for r in rows) / count for key in bools},
            "slot_accuracy": {key: sum(r["slot_correct"][key] for r in rows) / count for key in FRAME_KEYS}}


def evaluate_intent_roundtrip(descriptor, samples, *, weight_ablation=None):
    """Direct directions and composition, with raw failures retained and grouped."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_text import evaluate_paired_text
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    loaded = load_intent_roundtrip_checkpoint(descriptor)
    backend = loaded["backend_descriptor"]
    if not samples:
        return {"count": 0, "rows": [], "groups": {}}
    encoded = evaluate_paired_text(backend, [{"id": r["id"], "source": " ".join(r["instruction"].lower().split()),
        "target": frame_to_sequence(r["frame"]), "direction": "encode"} for r in samples], weight_ablation=weight_ablation)
    decoded = evaluate_paired_text(backend, [{"id": r["id"], "source": frame_to_sequence(r["frame"]),
        "target": r["canonical_text"], "direction": "decode"} for r in samples], weight_ablation=weight_ablation)
    predictions = {r["id"]: _parse_prediction(r, sequence_to_frame) for r in encoded["rows"]}
    composition_pairs = [{"id": r["id"], "source": frame_to_sequence(predictions[r["id"]]),
        "target": canonical_frame_text(predictions[r["id"]]), "direction": "decode"}
        for r in samples if predictions[r["id"]] is not None]
    composed = evaluate_paired_text(backend, composition_pairs, weight_ablation=weight_ablation) if composition_pairs else {"rows": []}
    compositions = {r["id"]: r for r in composed["rows"]}
    cycle_pairs = [{"id": r["id"], "source": r["generated_text"],
        "target": frame_to_sequence(normalized_text_to_frame(r["generated_text"])), "direction": "encode"}
        for r in composed["rows"]
        if _parse_prediction(r, normalized_text_to_frame) is not None]
    cycled = evaluate_paired_text(backend, cycle_pairs, weight_ablation=weight_ablation) if cycle_pairs else {"rows": []}
    cycles = {r["id"]: _parse_prediction(r, sequence_to_frame) for r in cycled["rows"]}
    rows = []
    for sample, enc, dec in zip(samples, encoded["rows"], decoded["rows"]):
        frame = predictions[sample["id"]]
        comp = compositions.get(sample["id"])
        inverse_frame = _parse_prediction(dec, normalized_text_to_frame)
        composed_frame = _parse_prediction(comp, normalized_text_to_frame) if comp else None
        deployable = (frame is not None and not enc["input_oov_tokens"] and comp is not None
                      and not comp["input_oov_tokens"] and composed_frame == frame)
        native_valid, projections = False, []
        if frame is not None:
            try:
                document = frame_to_intent_ir(frame, instruction=sample["instruction"])
                native_valid = intent_ir_to_frame(document) == frame
                target = prepare_intent_targets(document).to_dict()
                projections = [{"projection_id": p["projection_id"], "logic_family": p["logic_family"],
                    "native_formula_count": len(p["native_formulas"])} for p in target["projections"]]
            except ValueError:
                native_valid = False
        deployable = deployable and native_valid
        provenance = sample["provenance"]
        group = "authored" if str(sample["id"]).startswith("authored") or "authored" in str(provenance.get("kind", "")) else "weak_public_source"
        rows.append({"id": sample["id"], "split": sample["split"], "group": group,
            "instruction": sample["instruction"], "expected_frame": sample["frame"], "predicted_frame": frame,
            "encode_valid": frame is not None, "encode_exact": frame == sample["frame"],
            "native_ir_valid": native_valid, "decode_exact": inverse_frame == sample["frame"],
            "composed_exact": frame == sample["frame"] and composed_frame == sample["frame"],
            "cycle_consistent": frame is not None and cycles.get(sample["id"]) == frame,
            "encoder_oov": bool(enc["input_oov_tokens"]),
            "deployable_candidate": deployable, "deployable_exact": deployable and frame == sample["frame"],
            "slot_correct": {key: frame is not None and frame[key] == sample["frame"][key] for key in FRAME_KEYS},
            "encoder_output": enc, "inverse_from_expected_ir": dec, "inverse_from_predicted_ir": comp,
            "projections": projections})
    return {"schema": "intent-roundtrip-evaluation/v1", "checkpoint": descriptor,
        "weight_ablation": weight_ablation, "metrics": _metrics(rows),
        "groups": {name: _metrics([r for r in rows if r["group"] == name]) for name in ("authored", "weak_public_source")},
        "rows": rows, "teacher_forcing": False, "inference_target_access": False,
        "development_holdout_only": True, "source_semantics_verified": False,
        "native_projections_are_compiler_results_from_predicted_ir": True,
        "zero_head_is_an_ablation_not_an_untrained_quality_baseline": True}
