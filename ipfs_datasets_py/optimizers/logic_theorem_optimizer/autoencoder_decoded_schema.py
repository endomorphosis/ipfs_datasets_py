"""Run supported learned decoders and Lake-check their actual output records.

This inference-only integration never substitutes a training target for a
failed prediction. Native models consume structured projection inputs; their
serialized input bytes are bound separately from their supplied source digest.
The retained JSON is an audit observation, not transferable proof authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import autoencoder_runtime_registry as interface
from . import autoencoder_schema_lake as schema_lake
from . import legal_formula_learning as legal_learning
from ...logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope

SCHEMA = "autoencoder-decoded-schema-evaluation/v1"
MAX_SAMPLES = 32
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_PROJECTIONS = 128


class DecodedSchemaError(ValueError):
    """Unsupported runtime or inconsistent input/decoder/checkpoint binding."""


def _require(condition, reason):
    if not condition:
        raise DecodedSchemaError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _binding(runtime):
    if type(runtime) is interface.LearnedFormulaRuntime:
        checkpoint = runtime.checkpoint
        _require(checkpoint is not None, "a learned legal checkpoint is required")
        legal_learning.validate_checkpoint(checkpoint)
        return "legal_ir", interface.LEARNED_FORMULA_VERSION, legal_learning.checkpoint_digest(checkpoint)
    if type(runtime) is interface.NativeFormulaRuntime:
        from . import native_formula_training as learning
        checkpoint = runtime.checkpoint
        learning.validate_checkpoint(checkpoint)
        _require(checkpoint["domain_id"] == runtime._domain, "native runtime domain differs from checkpoint")
        return runtime._domain, interface.NATIVE_FORMULA_VERSION, learning.checkpoint_digest(checkpoint)
    raise DecodedSchemaError("unsupported runtime: only learned legal and native_formula_v1 are wired")


def _inputs(domain, samples):
    _require(type(samples) in (list, tuple) and 1 <= len(samples) <= MAX_SAMPLES,
             "one to 32 explicit model inputs required")
    if domain == "legal_ir":
        _require(all(type(item) is str and 0 < len(item) <= 16384 for item in samples),
                 "learned legal inference accepts only bounded source text strings")
        result = list(samples)
    else:
        result = []
        for value in samples:
            _require(type(value) in (dict, DomainTargetEnvelope), "native inference requires exact target-envelope inputs")
            envelope = DomainTargetEnvelope.from_dict(value if type(value) is dict else value.to_dict())
            _require(envelope.domain_id == domain, "model input belongs to another domain")
            result.append(envelope.to_dict())
    _require(len(_raw(result)) <= MAX_BATCH_BYTES, "model input batch exceeds byte bound")
    return result


def _write(path, value):
    raw = _raw(value)
    _require(len(raw) <= MAX_BATCH_BYTES * 4, "retained report exceeds byte bound")
    with path.open("xb") as handle:
        handle.write(raw)


def validate_decoded_outputs(runtime, samples, *, output_directory, timeout_seconds=60):
    """Infer, validate native outputs, and execute structural Lake checks.

    Runtime/checkpoint identity is obtained internally. Inputs and outputs are
    retained separately. Errors/abstentions remain in the result; they never
    acquire a source-only compiler fallback or a passed schema observation.
    The timeout is per actual Lake build, not a whole-batch training budget.
    """
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and 1 <= timeout_seconds <= 120, "bounded Lake timeout required")
    domain, version, checkpoint_sha = _binding(runtime)
    inputs = _inputs(domain, samples)
    directory = Path(output_directory).absolute()
    _require(not directory.exists() and directory.parent.is_dir(), "fresh output directory required")
    directory.mkdir(mode=0o700)
    _write(directory / "inputs.json", inputs)
    rows, inference_records = [], []
    build_count, passed_count, projection_count, decoded_count = 0, 0, 0, 0
    for index, sample in enumerate(inputs):
        source_text = sample if domain == "legal_ir" else _raw(sample).decode()
        source_sha = hashlib.sha256(source_text.encode()).hexdigest()
        row = {"input_index": index, "exact_model_input_sha256": source_sha,
            "source_binding_scope": "raw_source_text" if domain == "legal_ir" else "exact_model_input_artifact",
            "native_input_source_digest": None if domain == "legal_ir" else sample["source_digest"],
            "status": "inference_error", "reason": None, "outputs": [], **schema_lake.FALSE}
        inference = None
        try:
            _require(_binding(runtime) == (domain, version, checkpoint_sha), "runtime changed before inference")
            # Exact class dispatch excludes arbitrary lookalike objects and
            # avoids using an attached per-instance replacement as a decoder.
            inference = type(runtime).decode_formal_logic(runtime, [sample])
            _require(_binding(runtime) == (domain, version, checkpoint_sha), "runtime changed during inference")
            _require(type(inference) is dict and inference.get("checkpoint_sha256") == checkpoint_sha
                     and inference.get("training_executed") is False,
                     "decoder did not bind its inference-only checkpoint")
            _require(type(inference.get("rows")) is list and len(inference["rows"]) == 1,
                     "one decoded row per model input required")
            decoded = inference["rows"][0]
            _require(type(decoded) is dict, "decoded row must be a mapping")
            if domain == "legal_ir":
                _require(decoded.get("source_sha256") == source_sha, "decoder source hash differs from exact input")
                candidates = [{"projection_id": "canonical-deontic-rules/v1", "status": decoded.get("status"),
                               "reason": decoded.get("reason"), "canonical_ir": decoded.get("canonical_ir")}]
            else:
                _require(inference.get("domain_id") == domain, "decoder reported another domain")
                _require(decoded.get("source_digest") == sample["source_digest"], "decoder input source digest differs")
                candidates = decoded.get("projections")
                _require(type(candidates) is list and candidates, "native decoded projection rows required")
            projection_count += len(candidates)
            _require(projection_count <= MAX_PROJECTIONS, "decoded projection count bound exceeded")
            row["status"] = "decoded_outputs_observed"
            for ordinal, candidate in enumerate(candidates):
                _require(type(candidate) is dict, "decoded projection must be a mapping")
                observed = {"projection_id": candidate.get("projection_id"), "decoder_status": candidate.get("status"),
                            "status": "not_decoded", "reason": candidate.get("reason"), "lake_receipt": None,
                            **schema_lake.FALSE}
                row["outputs"].append(observed)
                if candidate.get("status") != ("decoded" if domain == "legal_ir" else "decoded_candidate"):
                    continue
                decoded_count += 1
                try:
                    output = candidate["canonical_ir"] if domain == "legal_ir" else {
                        key: candidate[key] for key in ("projection_id", "expression", *schema_lake.DESCRIPTOR_FIELDS)}
                    observed["output_sha256"] = _sha(output)
                    execution = schema_lake.validate_schema_output(domain, output, source_text=source_text,
                        checkpoint_sha256=checkpoint_sha, output_directory=directory / f"sample-{index}-projection-{ordinal}",
                        timeout_seconds=timeout_seconds)
                    receipt = schema_lake.verify_schema_execution(execution, domain, output,
                        source_text=source_text, checkpoint_sha256=checkpoint_sha)
                    observed["lake_receipt"] = receipt
                    observed["status"] = "schema_typechecked" if receipt["schema_instance_typecheck_passed"] else "schema_typecheck_failed"
                    observed["reason"] = receipt["reason"]
                    build_count += 1
                    passed_count += int(receipt["schema_instance_typecheck_passed"])
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    observed.update(status="schema_validation_error", reason=type(exc).__name__ + ": " + str(exc)[:2000])
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            row.update(status="inference_error", reason=type(exc).__name__ + ": " + str(exc)[:2000])
        inference_records.append({"input_index": index, "inference": inference})
        rows.append(row)
    # A mutation never qualifies earlier rows; this invocation remains an
    # audit of exact observations, not an inference promotion mechanism.
    try:
        final_binding_unchanged = _binding(runtime) == (domain, version, checkpoint_sha)
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        final_binding_unchanged = False
    _write(directory / "inference.json", inference_records)
    report = {"schema": SCHEMA, "domain": domain, "runtime_version": version,
        "checkpoint_sha256": checkpoint_sha, "checkpoint_binding_computed_internally": True,
        "runtime_binding_unchanged": final_binding_unchanged, "sample_count": len(inputs), "input_count": len(inputs),
        "projection_row_count": projection_count, "decoded_projection_count": decoded_count,
        "lake_build_count": build_count, "schema_check_count": build_count,
        "schema_typecheck_pass_count": passed_count, "schema_pass_count": passed_count,
        "schema_checks_complete": final_binding_unchanged and bool(rows) and all(
            row["status"] == "decoded_outputs_observed" and row["outputs"] and all(
                item["status"] == "schema_typechecked" for item in row["outputs"]) for row in rows),
        "rows": rows,
        "training_executed": False, "inference_executed": True,
        "output_origin": "actual_runtime_decode_result_without_target_or_compiler_fallback",
        "validation_scope": "per_artifact_structural_schema_and_instance_not_domain_wide_semantics",
        "persisted_receipt_scope": "audit_only_fresh_execution_required_to_reestablish_trust",
        "retained_inputs_sha256": _sha(inputs), "retained_inference_sha256": _sha(inference_records),
        "directory": str(directory), **schema_lake.FALSE}
    _write(directory / "report.json", report)
    return report


__all__ = ["DecodedSchemaError", "validate_decoded_outputs"]
