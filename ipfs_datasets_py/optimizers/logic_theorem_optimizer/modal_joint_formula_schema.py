"""Lake-check actual outputs of lineage-bound modal formula heads.

The complete serialized modal input and its source string are retained
separately. Parser-derived input features are allowed and explicitly recorded;
this is not an independent text-to-logic or legal correctness test. Only the
single supported deontic projection is tested here, without target fallback.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from . import autoencoder_schema_lake as schema_lake
from . import modal_joint_formula as joint
from . import modal_latent_formula as learning

SCHEMA = "modal-joint-formula-schema-evaluation/v1"
MAX_SAMPLES = 32
MAX_BATCH_BYTES = 8 * 1024 * 1024


def _require(condition, message):
    from .autoencoder_decoded_schema import DecodedSchemaError
    if not condition:
        raise DecodedSchemaError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _write(path, value):
    raw = _raw(value)
    _require(len(raw) <= 4 * MAX_BATCH_BYTES, "retained report exceeds byte bound")
    with path.open("xb") as stream:
        stream.write(raw)


def _binding(runtime):
    from . import autoencoder_runtime_registry as interface
    from .autoencoder_lineages import legacy_v1, current_v2, legacy_v1_optimized
    _require(type(runtime) is interface.LegalRuntime, "exact legal modal runtime required")
    classes = {legacy_v1.Autoencoder: ("legacy_v1", legacy_v1.LegalSample),
               current_v2.Autoencoder: ("current_v2", current_v2.LegalSample),
               legacy_v1_optimized.Autoencoder: ("legacy_v1_optimized", legacy_v1.LegalSample)}
    _require(type(runtime.model) in classes, "unsupported modal lineage implementation")
    version, sample_class = classes[type(runtime.model)]
    model = runtime.model
    # Do not permit an instance replacement to masquerade as the registered
    # runtime method, raw feature extractor, or cached learned decoder.
    for owner in (runtime, model):
        _require(not any(callable(value) for value in vars(owner).values()),
                 "instance method replacements are unsupported")
    core = joint._core_binding(model)
    checkpoint = model.formula_checkpoint
    _require(checkpoint is not None, "an attached learned modal formula checkpoint is required")
    learning.validate_checkpoint(checkpoint)
    _require(checkpoint["binding"] == core, "formula head and current numerical core differ")
    decoder = model._joint_formula_decoder
    _require(type(decoder) is learning.LatentFormulaDecoder,
             "exact attached learned latent decoder required")
    _require(not any(callable(value) for value in vars(decoder).values()
                     if value is not decoder.model), "decoder instance replacements are unsupported")
    checkpoint_sha = learning.checkpoint_digest(checkpoint)
    _require(decoder.checkpoint == checkpoint and decoder.checkpoint_sha256 == checkpoint_sha,
             "cached decoder checkpoint differs from attached formula head")
    weights = {name: tensor.detach().tolist() for name, tensor in decoder.model.state_dict().items()}
    _require(weights == checkpoint["model_state"], "cached decoder weights differ from attached formula head")
    files = (Path(__file__), Path(interface.__file__), Path(__file__).with_name("autoencoder_decoded_schema.py"))
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    return {"runtime_version": version, "core": core, "checkpoint_sha256": checkpoint_sha,
            "schema_integration_sources": sources}, sample_class


def validate_modal_decoded_outputs(runtime, samples, *, output_directory, timeout_seconds=60):
    """Infer from typed modal samples and build their actual canonical outputs.

    Every source, serialized input, core and head is bound before and after
    inference. Abstentions or changed bindings cannot acquire a passed check.
    Successful Lake results remain artifact schema checks without semantics.
    """
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and 1 <= timeout_seconds <= 120, "bounded Lake timeout required")
    binding, sample_class = _binding(runtime)
    _require(type(samples) in (list, tuple) and 1 <= len(samples) <= MAX_SAMPLES,
             "one to 32 explicit model inputs required")
    _require(all(type(sample) is sample_class for sample in samples),
             "exact typed samples for the selected modal lineage required")
    inputs = joint._samples(runtime.model, samples)
    captured_inputs = [copy.deepcopy(sample.to_dict()) for sample in inputs]
    sources = [{"input_index": index, "sample_id": sample.sample_id, "source_text": sample.text,
                "source_sha256": hashlib.sha256(sample.text.encode()).hexdigest()}
               for index, sample in enumerate(inputs)]
    _require(len(_raw(captured_inputs)) + len(_raw(sources)) <= MAX_BATCH_BYTES,
             "model input batch exceeds byte bound")
    directory = Path(output_directory).absolute()
    _require(not directory.exists() and directory.parent.is_dir(), "fresh output directory required")
    directory.mkdir(mode=0o700)
    _write(directory / "inputs.json", captured_inputs)
    _write(directory / "sources.json", sources)
    checkpoint_sha = binding["checkpoint_sha256"]
    rows, inference_records = [], []
    builds, passes, decoded_count = 0, 0, 0
    for index, sample in enumerate(inputs):
        source = sources[index]
        row = {"input_index": index, "sample_id": source["sample_id"],
               "exact_model_input_sha256": _sha(captured_inputs[index]),
               "source_sha256": source["source_sha256"],
               "source_binding_scope": "exact_serialized_modal_input_and_separate_source_string",
               "parser_features_in_input": True, "independent_text_to_logic": False,
               "status": "inference_error", "reason": None, "outputs": [],
               "roundtrip_ok": False, **schema_lake.FALSE}
        inference = None
        try:
            _require(_binding(runtime)[0] == binding, "runtime changed before inference")
            _require(sample.to_dict() == captured_inputs[index], "model input changed before inference")
            # Exact class dispatch ignores any per-instance runtime attribute.
            inference = type(runtime).infer(runtime, [sample])
            _require(_binding(runtime)[0] == binding, "runtime changed during inference")
            _require(sample.to_dict() == captured_inputs[index], "model input changed during inference")
            _require(type(inference) is dict and inference.get("checkpoint_sha256") == checkpoint_sha
                     and inference.get("binding") == binding["core"], "decoder checkpoint/core binding differs")
            _require(inference.get("training_executed") is False and inference.get("target_access") is False
                     and inference.get("teacher_forcing") is False
                     and inference.get("independent_text_to_logic") is False,
                     "decoder did not report the required inference-only input scope")
            _require(type(inference.get("rows")) is list and len(inference["rows"]) == 1,
                     "one decoded row per model input required")
            decoded = inference["rows"][0]
            _require(type(decoded) is dict and decoded.get("id") == sample.sample_id
                     and decoded.get("source_sha256") == source["source_sha256"],
                     "decoder source identity differs from the exact captured input")
            _require(decoded.get("latent_sha256") == learning.checkpoint_digest(joint.raw_projection(runtime.model, sample)),
                     "decoder latent differs from the exact modal projection")
            _require(decoded.get("projection_id") == learning.PROJECTION_ID,
                     "unsupported learned projection")
            _require(decoded.get("target_access") is False and decoded.get("teacher_forcing") is False
                     and decoded.get("training_executed") is False,
                     "decoded row is not an inference-only observation")
            # Retain the observation immediately, independently of later mutable
            # cached inference objects. No caller target is accepted anywhere.
            inference = json.loads(_raw(inference))
            decoded = inference["rows"][0]
            observed = {"projection_id": learning.PROJECTION_ID, "logic_family": "deontic",
                        "decoder_status": decoded.get("status"), "status": "not_decoded",
                        "reason": decoded.get("reason"), "lake_receipt": None, **schema_lake.FALSE}
            row.update(status="decoded_outputs_observed", outputs=[observed])
            if decoded.get("status") == "decoded":
                decoded_count += 1
                output = decoded["canonical_ir"]
                observed["output_sha256"] = _sha(output)
                try:
                    execution = schema_lake.validate_schema_output("legal_ir", output,
                        source_text=source["source_text"], checkpoint_sha256=checkpoint_sha,
                        output_directory=directory / f"sample-{index}-projection-0", timeout_seconds=timeout_seconds)
                    receipt = schema_lake.verify_schema_execution(execution, "legal_ir", output,
                        source_text=source["source_text"], checkpoint_sha256=checkpoint_sha)
                    builds += 1
                    _require(_binding(runtime)[0] == binding, "runtime changed during schema execution")
                    _require(sample.to_dict() == captured_inputs[index], "model input changed during schema execution")
                    observed.update(lake_receipt=receipt,
                        status="schema_typechecked" if receipt["schema_instance_typecheck_passed"] else "schema_typecheck_failed",
                        reason=receipt["reason"])
                    passes += int(receipt["schema_instance_typecheck_passed"])
                except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
                    observed.update(status="schema_validation_error", reason=type(exc).__name__ + ": " + str(exc)[:2000])
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
            row.update(status="inference_error", reason=type(exc).__name__ + ": " + str(exc)[:2000])
        inference_records.append({"input_index": index, "inference": inference})
        rows.append(row)
    try:
        unchanged = _binding(runtime)[0] == binding and all(
            sample.to_dict() == captured_inputs[index] for index, sample in enumerate(inputs))
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        unchanged = False
    _write(directory / "inference.json", inference_records)
    report = {"schema": SCHEMA, "domain": "legal_ir", "runtime_version": binding["runtime_version"],
              "lineage_id": binding["core"]["lineage_id"], "dimension": binding["core"]["dimension"],
              "core_binding": binding["core"], "checkpoint_sha256": checkpoint_sha,
              "schema_integration_sources": binding["schema_integration_sources"],
              "checkpoint_binding_computed_internally": True, "runtime_binding_unchanged": unchanged,
              "sample_count": len(inputs), "input_count": len(inputs),
              "projection_row_count": sum(len(row["outputs"]) for row in rows),
              "decoded_projection_count": decoded_count, "lake_build_count": builds,
              "schema_check_count": builds, "schema_typecheck_pass_count": passes, "schema_pass_count": passes,
              "schema_checks_complete": unchanged and all(row["status"] == "decoded_outputs_observed"
                    and row["outputs"] and all(item["status"] == "schema_typechecked" for item in row["outputs"])
                    for row in rows),
              "rows": rows, "training_executed": False, "inference_executed": True,
              "parser_features_in_input": True, "independent_text_to_logic": False,
              "source_text_is_neural_input": False, "supported_logic_families": ["deontic"],
              "output_origin": "actual_attached_modal_formula_head_without_target_or_compiler_fallback",
              "validation_scope": "per_artifact_structural_schema_and_instance_not_domain_wide_semantics",
              "persisted_receipt_scope": "audit_only_fresh_execution_required_to_reestablish_trust",
              "retained_inputs_sha256": _sha(captured_inputs), "retained_sources_sha256": _sha(sources),
              "retained_inference_sha256": _sha(inference_records), "directory": str(directory),
              "roundtrip_ok": False, **schema_lake.FALSE}
    _write(directory / "report.json", report)
    return report


__all__ = ["validate_modal_decoded_outputs"]
