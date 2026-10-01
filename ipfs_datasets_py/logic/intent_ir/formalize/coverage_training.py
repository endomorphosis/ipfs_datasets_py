"""Bounded Intent continuation and separate shared logic-family objective.

The existing rich checkpoint schema and inference modules remain unchanged.
The legal initializer is retained through its frozen lexical branch; the actual
trainable sequence model is inherited in full from the explicit parent.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .coverage_curriculum import prepare_coverage_training_data, freeze_coverage_holdouts
from .rich_decoder import register_rich_intent_checkpoint, sha, wire


def _legal_lineage(training, expected_initializer_sha256):
    if (type(expected_initializer_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_initializer_sha256) is None):
        raise ValueError("explicit expected legal initializer SHA256 required")
    lineage = training.get("lexical_lineage")
    if (type(lineage) is not dict or lineage.get("present") is not True
            or lineage.get("frozen") is not True or lineage.get("parent_modified") is not False
            or lineage.get("initializer_sha256") != expected_initializer_sha256):
        raise ValueError("frozen legal lexical initializer lineage differs")
    return dict(lineage)


def select_family_training_rows(corpus, prepared, *, limits=None):
    """Bounded structural supervision selected independently of predictions.

    Round-robin strata preserve constructors, modality and source-form coverage.
    Every selected row already passed the same fitting/tuning quarantine.
    """
    limits = {"train": 48, "validation": 16} if limits is None else dict(limits)
    if (set(limits) != {"train", "validation"}
            or any(type(n) is not int or not 1 <= n <= 256 for n in limits.values())):
        raise ValueError("bounded family training and validation row limits required")
    if prepared.get("corpus_sha256") != sha(wire(corpus)):
        raise ValueError("prepared training data belongs to a different corpus")
    rows = {row["id"]: row for row in corpus["samples"]}
    selected = {}
    for split, ids in prepared["selected_row_ids"].items():
        strata = defaultdict(list)
        for identity in ids:
            row = rows[identity]
            ast, provenance = row["ast"], row["provenance"]
            key = (ast["kind"], ast.get("modality", "composed"),
                   provenance.get("object_shape", "original"))
            strata[key].append(row)
        for group in strata.values():
            group.sort(key=lambda row: sha(("intent-family-training/v1:" + row["id"]).encode()))
        picked = []
        # Reserve one representative of every constructor before the many
        # atom shape/modality strata can consume the bound.
        for kind in sorted({key[0] for key in strata}):
            key = next(key for key in sorted(strata) if key[0] == kind)
            picked.append(strata[key].pop(0))
            if not strata[key]:
                del strata[key]
            if len(picked) == limits[split]:
                break
        while strata and len(picked) < limits[split]:
            for key in sorted(tuple(strata)):
                picked.append(strata[key].pop(0))
                if not strata[key]:
                    del strata[key]
                if len(picked) == limits[split]:
                    break
        selected[split] = picked
    return selected


def train_coverage_intent(corpus, *, parent_backend_descriptor, expected_legal_initializer_sha256,
                          output, source_training_options=None, train_family_projection=True,
                          family_training_options=None, family_target_limits=None):
    """Fork an existing model, preserving the legal lexical transfer branch.

    Source roundtrip and family projection reconstruction have separate weights,
    receipts and metrics. The latter never supplies a missing source-to-IR
    prediction and cannot authorize a failed source interpretation.
    """
    from ....optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as continuation
    if type(train_family_projection) is not bool:
        raise ValueError("explicit family training mode required")
    if family_training_options is not None and (type(family_training_options) is not dict
            or set(family_training_options) - {"epochs", "latent_width", "learning_rate", "minibatch_size",
                "denoising", "seed", "max_seconds", "parent_descriptor"}):
        raise ValueError("known bounded family training options required")
    source_options = {"epochs": 80, "max_seconds": 180, "learning_rate": 0.001, "copy_dropout": 0.25}
    if source_training_options is not None:
        if type(source_training_options) is not dict or set(source_training_options) - set(source_options):
            raise ValueError("known bounded source training options required")
        source_options.update(source_training_options)
    prepared = prepare_coverage_training_data(corpus)
    parent = continuation.load_paired_copy_continuation(parent_backend_descriptor)
    before = _legal_lineage(parent["training"], expected_legal_initializer_sha256)
    if any(not 1 <= len(pairs) <= 8192 for pairs in prepared["pairs"].values()):
        raise ValueError("each source training/tuning direction-pair set must fit the frozen 8192-example bound")
    parent_path = Path(parent_backend_descriptor["path"]).resolve(strict=True)
    parent_sha256 = sha(parent_path.read_bytes())
    family_rows = select_family_training_rows(corpus, prepared, limits=family_target_limits)
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    (output / "corpus.json").write_bytes(wire(corpus))
    (output / "frozen-holdouts.json").write_bytes(wire(freeze_coverage_holdouts(corpus)))
    (output / "prepared-data.json").write_bytes(wire(prepared))
    child = continuation.train_paired_copy_continuation(prepared["pairs"]["train"], prepared["pairs"]["validation"],
        parent_descriptor=parent_backend_descriptor, output_dir=output / "model", **source_options)
    trained = continuation.load_paired_copy_continuation(child)
    after = _legal_lineage(trained["training"], expected_legal_initializer_sha256)
    if before != after or sha(parent_path.read_bytes()) != parent_sha256:
        raise ValueError("continuation changed its parent or frozen legal lexical lineage")
    descriptor = register_rich_intent_checkpoint(child, output=output, corpus_sha256=sha(wire(corpus)))
    (output / "descriptor.json").write_bytes(wire(descriptor))
    receipt = {"schema": "intent-source-form-training-run/v1", "checkpoint": descriptor, "backend": child,
        "parent_backend": parent_backend_descriptor, "parent_bytes_unchanged": True,
        "legal_initializer_lineage": after,
        "lineage_scope": "frozen legal lexical transfer; full trainable sequence weights inherited from explicit parent",
        "corpus_sha256": sha(wire(corpus)), "source_training_options": source_options,
        "inference_apis": {"frozen_direct": "ipfs_datasets_py.logic.intent_ir.formalize.rich_decoder.prepare_rich_intent_instruction",
            "optional_token_faithful_inverse_recovery": "ipfs_datasets_py.logic.intent_ir.formalize.rich_inverse_recovery.prepare_inverse_recovered_rich_intent",
            "default_supervisor_dispatch_changed": False},
        "source_pair_counts": {split: len(pairs) for split, pairs in prepared["pairs"].items()},
        "quarantined": prepared["quarantined"],
        "family_training": {"status": "pending" if train_family_projection else "not_requested"},
        "test_used_for_fit_or_tuning": False, "source_semantics_verified": False,
        "proof_authority": False, "execution_authority": False, "published": False}
    (output / "training-receipt.json").write_bytes(wire(receipt))
    if train_family_projection:
        from ...formalization.autoencoder.family_training import prepare_family_training_targets
        from ....optimizers.logic_theorem_optimizer.autoencoder_family_training import train_family_projection_autoencoder
        reports = {split: [prepare_family_training_targets("intent_ir", document=row["ast"],
                    source_text=row["instruction"]) for row in selected] for split, selected in family_rows.items()}
        (output / "family-training-inputs.json").write_bytes(wire({"selected_row_ids": {
            split: [r["id"] for r in selected] for split, selected in family_rows.items()}, "reports": reports}))
        family = train_family_projection_autoencoder(reports["train"], reports["validation"],
            output_dir=output / "family-model", **(family_training_options or {}))
        receipt["family_training"] = {"status": "completed", "result": family,
            "selected_row_counts": {split: len(selected) for split, selected in family_rows.items()},
            "objective": "structural projection reconstruction, independent of source-to-IR acceptance",
            "all_registered_families_inventoried": True, "all_families_assumed_supported": False}
        (output / "training-receipt.json").write_bytes(wire(receipt))
    return receipt


__all__ = ["select_family_training_rows", "train_coverage_intent"]
