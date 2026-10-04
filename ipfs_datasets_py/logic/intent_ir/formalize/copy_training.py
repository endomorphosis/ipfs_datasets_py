"""Training and held-out evaluation for the additive IntentIR copy model."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .roundtrip import (_raw, _sha, FRAME_KEYS, canonical_frame_text, frame_to_sequence,
    sequence_to_frame, normalized_text_to_frame, frame_to_intent_ir, intent_ir_to_frame)
from .roundtrip_training import _validated_samples, build_training_pairs, _parse_prediction, _metrics
from .copy_roundtrip import register_intent_copy_checkpoint, load_intent_copy_checkpoint


def train_intent_copy(corpus, output, *, lexical_initializer_path=None, epochs=100,
                      max_seconds=300, hidden_size=96, embedding_dim=48, copy_dropout=0.20):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import train_paired_copy, load_paired_copy
    if corpus.get("schema") == "intent-rich-span-pairs/v1":
        from .rich_span_training import validate_rich_span_pairs
        validate_rich_span_pairs(corpus)
    samples = _validated_samples(corpus)
    train = build_training_pairs([r for r in samples if r["split"] == "train"])
    tune = build_training_pairs([r for r in samples if r["split"] == "validation"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus_raw = _raw(corpus)
    (output / "corpus.json").write_bytes(corpus_raw)
    backend = train_paired_copy(train, tune, output_dir=output / "model",
        lexical_initializer_path=Path(lexical_initializer_path).resolve() if lexical_initializer_path else None,
        epochs=epochs, max_seconds=max_seconds, hidden_size=hidden_size,
        embedding_dim=embedding_dim, copy_dropout=copy_dropout)
    descriptor = register_intent_copy_checkpoint(backend, output=output, corpus_sha256=_sha(corpus_raw))
    (output / "descriptor.json").write_bytes(_raw(descriptor))
    loaded = load_paired_copy(backend)
    receipt = {"schema": "intent-copy-roundtrip-training/v1", "checkpoint": descriptor,
        "corpus_sha256": _sha(corpus_raw), "shared_backend": backend,
        "source_split_counts": dict(Counter(r["split"] for r in samples)),
        "source_kind_counts": dict(Counter(str(r["provenance"].get("kind", "unspecified")) for r in samples)),
        "training_pair_count": len(train), "validation_pair_count": len(tune),
        "test_used_for_training_or_tuning": False, "shared_training": loaded["training"],
        "normalized_wording_requested": True, "corpus_schema": corpus.get("schema"),
        "supervision": corpus.get("supervision", "caller_supplied_paired_development_targets"),
        "scope": "single_clause_actor_action_object_modality_with_source_copying",
        "semantic_correctness_verified": False, "proofs_run": False, "published": False}
    (output / "training-receipt.json").write_bytes(_raw(receipt))
    return receipt


def _covered(row):
    return row.get("input_coverage_complete") is True and row.get("uncovered_input_tokens") == []


def evaluate_intent_copy(descriptor, samples, *, weight_ablation=None):
    """Report all rows, including addressed OOV and incorrect valid candidates."""
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import evaluate_paired_copy
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    loaded = load_intent_copy_checkpoint(descriptor)
    backend = loaded["backend_descriptor"]
    if not samples:
        return {"count": 0, "rows": [], "groups": {}}
    options = {"weight_ablation": weight_ablation}
    encoded = evaluate_paired_copy(backend, [{"id": r["id"],
        "source": " ".join(r["instruction"].lower().split()),
        "target": frame_to_sequence(r["frame"]), "direction": "encode"} for r in samples], **options)
    decoded = evaluate_paired_copy(backend, [{"id": r["id"], "source": frame_to_sequence(r["frame"]),
        "target": r["canonical_text"], "direction": "decode"} for r in samples], **options)
    predictions = {r["id"]: _parse_prediction(r, sequence_to_frame) for r in encoded["rows"]}
    comp_pairs = [{"id": r["id"], "source": frame_to_sequence(predictions[r["id"]]),
        "target": canonical_frame_text(predictions[r["id"]]), "direction": "decode"}
        for r in samples if predictions[r["id"]] is not None]
    composed = evaluate_paired_copy(backend, comp_pairs, **options) if comp_pairs else {"rows": []}
    compositions = {r["id"]: r for r in composed["rows"]}
    cycle_pairs = [{"id": r["id"], "source": r["generated_text"],
        "target": frame_to_sequence(normalized_text_to_frame(r["generated_text"])), "direction": "encode"}
        for r in composed["rows"] if _parse_prediction(r, normalized_text_to_frame) is not None]
    cycled = evaluate_paired_copy(backend, cycle_pairs, **options) if cycle_pairs else {"rows": []}
    cycles = {r["id"]: _parse_prediction(r, sequence_to_frame) for r in cycled["rows"]}
    rows = []
    for sample, enc, dec in zip(samples, encoded["rows"], decoded["rows"]):
        frame, comp = predictions[sample["id"]], compositions.get(sample["id"])
        inverse_frame = _parse_prediction(dec, normalized_text_to_frame)
        composed_frame = _parse_prediction(comp, normalized_text_to_frame) if comp else None
        deployable = frame is not None and _covered(enc) and comp is not None and _covered(comp) and composed_frame == frame
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
            "encoder_oov": bool(enc["input_oov_tokens"]), "encoder_coverage_complete": _covered(enc),
            "deployable_candidate": deployable, "deployable_exact": deployable and frame == sample["frame"],
            "slot_correct": {key: frame is not None and frame[key] == sample["frame"][key] for key in FRAME_KEYS},
            "encoder_output": enc, "inverse_from_expected_ir": dec, "inverse_from_predicted_ir": comp,
            "projections": projections})
    return {"schema": "intent-copy-roundtrip-evaluation/v1", "checkpoint": descriptor,
        "weight_ablation": weight_ablation, "metrics": _metrics(rows),
        "groups": {name: _metrics([r for r in rows if r["group"] == name]) for name in ("authored", "weak_public_source")},
        "rows": rows, "teacher_forcing": False, "inference_target_access": False,
        "development_holdout_only": True, "source_semantics_verified": False,
        "native_projections_are_compiler_results_from_predicted_ir": True,
        "coverage_is_not_semantic_accuracy": True}
