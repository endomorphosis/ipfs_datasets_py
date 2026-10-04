"""Batched inference for unchanged domain-384 v1 checkpoints.

This is a readout adapter, not a checkpoint migration or a new learned model.
It preserves tensors, vocabulary, token limit and greedy decoding. UI candidates
also pass the existing semantic component owner; raw generated JSON is retained
when that stricter gate refuses it. No qualification or Lean admit is inferred.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import domain_384_autoencoder as base
from . import domain_384_autoencoder_v2 as batches
from . import domain_384_fidelity as fidelity

SCHEMA = "domain-384-batched-inference/v1"
FALSE = dict(base.FALSE)


def _implementation():
    return {"adapter": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "batch_and_validation_owners": batches._implementation()}


_IMPORTED = _implementation()


def _guard():
    base._require(_implementation() == _IMPORTED, "batched inference producer changed after import")
    batches._guard()


class Runtime:
    """Load a genuine v1 artifact once, then batch target-free inference."""

    def __init__(self, checkpoint, *, batch_size=None, memory_budget_bytes=512 * 1024 * 1024):
        _guard()
        config = checkpoint.get("config") if type(checkpoint) is dict else None
        size = config.get("batch_size") if batch_size is None and type(config) is dict else batch_size
        base._require(type(size) is int and 1 <= size <= 64, "invalid inference batch size")
        base._require(type(memory_budget_bytes) is int and 1024**2 <= memory_budget_bytes <= 8 * 1024**3,
                      "invalid inference memory budget")
        legacy = base.Runtime(checkpoint)
        self.checkpoint, self.model = legacy.checkpoint, legacy.model
        self._legacy_description = legacy.describe()
        self._config = {**self.checkpoint["config"], "batch_size": size, "memory_budget_bytes": memory_budget_bytes}
        self._identity = {"mean": [0.] * base.DIMENSION, "scale": 1.}

    def describe(self):
        return {**deepcopy(self._legacy_description), "schema": SCHEMA,
            "checkpoint_schema": base.SCHEMA, "inference_producer": _implementation(),
            "inference_batch_size": self._config["batch_size"], "weights_modified": False,
            "checkpoint_migrated": False, "training_executed": False,
            "native_validation": "same_native_owners_plus_UI_semantic_component_contract", **FALSE}

    def infer(self, rows, *, weight_ablation=None):
        _guard()
        checkpoint = self.checkpoint
        rows = base._rows(checkpoint["domain_id"], rows, training=False)
        base._require(weight_ablation in (None, "zero_projection", "zero_condition", "zero_decoder"), "unknown weight ablation")
        memory = batches._memory(self._config, len(rows), len(checkpoint["codec"]["target_vocabulary"]),
            sum(parameter.numel() for parameter in self.model.parameters()))
        model = self.model if weight_ablation is None else deepcopy(self.model)
        with base._cpu() as torch:
            if weight_ablation:
                with torch.no_grad():
                    for name, parameter in model.named_parameters():
                        if (weight_ablation == "zero_projection" and name.startswith("projection_")) or (
                            weight_ablation == "zero_condition" and name.startswith("condition.")) or (
                            weight_ablation == "zero_decoder" and name.startswith(("decoder.", "output."))):
                            parameter.zero_()
            generated = batches._generate(torch, model, rows, checkpoint["codec"]["target_vocabulary"],
                self._config, self._identity)
        for row in generated:
            parsed = fidelity.parse_generated(row["generated_tokens"], ended=row["ended"])
            candidate, envelope_valid, reason = None, False, parsed["error"]
            if parsed["json_valid"]:
                try:
                    base.validate_target(checkpoint["domain_id"], parsed["candidate"])
                    envelope_valid = True
                    candidate = fidelity.validate_native_target(checkpoint["domain_id"], parsed["candidate"])["canonical_ir"]
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    reason = str(exc)[:512]
            row.update(candidate_ir=candidate, raw_candidate_ir=parsed["candidate"],
                native_envelope_valid=envelope_valid, native_semantic_valid=candidate is not None,
                status="unqualified_candidate" if candidate is not None else "invalid_generated_output",
                reason=reason, weights_sha256=checkpoint["weights_sha256"], weight_ablation=weight_ablation,
                target_access=False, teacher_forcing=False, continue_planning=True)
        _guard()
        return {"schema": SCHEMA, "checkpoint_schema": base.SCHEMA, "domain_id": checkpoint["domain_id"],
            "dimension": base.DIMENSION, "rows": generated, "weights_modified": False,
            "training_executed": False, "checkpoint_migrated": False, "inference_memory_estimate": memory,
            "numerical_note": "batched matrix arithmetic can differ in rounding; tokens require measured comparison", **FALSE}


def load_checkpoint(path, *, expected_sha256, expected_domain, **options):
    path = Path(path)
    base._require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= base.MAX_BYTES,
                  "bounded regular checkpoint required")
    raw = path.read_bytes()
    base._require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint bytes differ")
    checkpoint = base._parse(raw)
    base._require(type(checkpoint) is dict and checkpoint.get("domain_id") == expected_domain,
                  "checkpoint belongs to another domain")
    return Runtime(checkpoint, **options)


__all__ = ["SCHEMA", "Runtime", "load_checkpoint"]
