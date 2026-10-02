"""Shared 384D Intent action readout with separate, audited source binding.

The numerical decoder receives embeddings only. A fixed unbound provenance
record in its native target is replaced after exact, bounded source agreement;
the original prediction is retained. Neither agreement nor binding is a proof.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import re

from . import source_embeddings_384 as embeddings
from . import structured_source_384 as structured
from ...intent_ir.formalize import action_contracts as codec
from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer

SCHEMA = "intent-action-inference-384/v1"
FALSE = {"proof_authority": False, "execution_authority": False,
    "completion_authority": False, "source_semantics_verified": False,
    "whole_document_formalized": False, "qualified": False, "admitted": False,
    "formalized": False, "lake_executed": False, "training_executed": False,
    "llm_used": False, "download_performed": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _pins():
    from ....optimizers.logic_theorem_optimizer import autoencoder_schema_lake as owner
    modules = (importlib.import_module(__name__), codec, embeddings, producer, structured, owner)
    return {module.__name__: owner._pin_imported_module(module) for module in modules}


def _options(instruction, checkpoint_path, expected_sha256, snapshot_path):
    if type(instruction) is not str or not instruction.strip() or len(instruction.encode()) > 8192:
        raise ValueError("bounded nonempty original instruction required")
    if type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("exact checkpoint SHA-256 required")
    if not isinstance(checkpoint_path, (str, Path)) or not str(checkpoint_path):
        raise ValueError("explicit local checkpoint path required")
    if snapshot_path is not None and not isinstance(snapshot_path, (str, Path)):
        raise ValueError("local embedding snapshot path required")


def prepare_intent_action_inference(instruction, *, checkpoint_path, expected_sha256,
                                   snapshot_path=None):
    """Generate a native contract with the shared, unchanged structured reader.

    A prediction outside the exact controlled contract grammar is retained but
    cannot supply source-bound advice. No candidate is corrected or retrieved
    from the source parser. Missing local assets fail open, with no downloads.
    """
    _options(instruction, checkpoint_path, expected_sha256, snapshot_path)
    report = {"schema": SCHEMA, "status": "fail_open_unavailable", "reason": None,
        "instruction": instruction, "source_sha256": _sha(instruction.encode()),
        "checkpoint_path": str(checkpoint_path), "checkpoint_sha256": expected_sha256,
        "snapshot_path": None if snapshot_path is None else str(snapshot_path),
        "dimension": 384, "raw_candidate_ir": None, "native_intent_ir": None,
        "binding": None, "inference": None, "embedding_sha256": None,
        "embedding_provenance": None, "producer_pins": None,
        "producer_pin_scope": "direct_modules_loaded_functions_and_disk_not_full_environment",
        "model_inference_executed": False, "continue_planning": True,
        "raw_instruction_preserved": True, "candidate_semantics_rewritten": False,
        "provenance_binding_performed": False, **FALSE}
    try:
        # Scope screening has no semantic output passed to the numerical model.
        codec.parse_contract(instruction)
    except (ValueError, TypeError) as error:
        report.update(status="fail_open_input_out_of_scope", reason=str(error)[:512])
    else:
        try:
            before = _pins()
            reader = structured.load_checkpoint(checkpoint_path, expected_sha256=expected_sha256,
                                                expected_domain="intent_ir")
            snapshot, assets = producer._snapshot_assets(snapshot_path or producer.DEFAULT_SNAPSHOT_PATH)
            vectors = embeddings.embed_texts([instruction], snapshot_path=snapshot)
            report["embedding_sha256"] = _sha(_raw(vectors[0]))
            report["embedding_provenance"] = {"model_id": "thenlper/gte-small",
                "dimension": 384, "snapshot_path": str(snapshot), "asset_manifest": assets,
                "verified_local_assets": True}
            generated = reader.infer([{"id": "instruction", "source_text": instruction,
                                       "embedding": vectors[0]}])
            report.update(inference=generated, model_inference_executed=True)
            candidate = generated["rows"][0]["candidate_ir"]
            report["raw_candidate_ir"] = deepcopy(candidate)
            if candidate is None:
                report.update(status="fail_open_invalid_candidate", reason="shared reader rejected generated native target")
            else:
                binding = codec.bind_candidate_source(instruction, candidate)
                report["binding"] = binding
                if binding["status"] == "source_agreement":
                    report.update(status="source_supported_action_contract", reason=None,
                        native_intent_ir=deepcopy(binding["bound_candidate"]["document"]),
                        provenance_binding_performed=True)
                else:
                    report.update(status="fail_open_source_disagreement", reason=binding["status"])
            if before != _pins() or hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest() != expected_sha256:
                raise ValueError("Intent action producer or checkpoint changed during inference")
            _, final_assets = producer._snapshot_assets(snapshot)
            if final_assets != assets:
                raise ValueError("Intent embedding assets changed during inference")
            report["producer_pins"] = before
        except (ValueError, TypeError, KeyError, OSError, ImportError, RuntimeError) as error:
            report.update(status="fail_open_unavailable", reason=str(error)[:512],
                          native_intent_ir=None, provenance_binding_performed=False)
    report["report_sha256"] = _sha(_raw(report))
    return report


def verify_intent_action_inference(report, instruction, *, checkpoint_path,
                                  expected_sha256, snapshot_path=None):
    """Recompute inference and source binding; saved hashes confer no authority."""
    if type(report) is not dict or len(_raw(report)) > 4 * 1024 * 1024:
        raise ValueError("bounded Intent action inference report required")
    expected = prepare_intent_action_inference(instruction, checkpoint_path=checkpoint_path,
        expected_sha256=expected_sha256, snapshot_path=snapshot_path)
    if _raw(expected) != _raw(report):
        raise ValueError("Intent action inference replay differs")
    return expected


__all__ = ["SCHEMA", "prepare_intent_action_inference", "verify_intent_action_inference"]
