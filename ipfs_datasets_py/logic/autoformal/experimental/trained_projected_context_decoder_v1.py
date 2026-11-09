"""Separately versioned trained repeated-context LegalIR checkpoint and loader.

Only stdlib is imported. The owner injects genuine Torch/source/parity modules,
authenticates the parent and step-zero files, and supplies training provenance.
Hashes bind those declarations; they do not independently prove training history.
No file other than these implementation .py files is opened by this module.

The immutable parity loader validates only the original step-zero checkpoint.
Trained state is validated here and loaded into its genuine expanded constructor;
neither the old source.Runtime nor the parity-only loader receives trained state.
The four projection tensors stay exact. Other saved tensors, including both old
and added GRU input columns, may change in this explicitly trained profile.
Auxiliary-head and optimizer state are deliberately absent from inference.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('context_trained')["sha256"]


SCHEMA = "legal-ir-projected-context-trained/v1"
ARCHITECTURE = "residual-projection-repeated-projected-context-formula-gru/v1"
PROFILE = "matched-context-auxiliary-150/v1"
PARITY_SCHEMA = "legal-ir-projected-context-decoder/v1"
PARITY_PROFILE = "projected-context-initialization-parity/v1"
PARITY_CODE_SHA256 = "de68e2ed3975c3ae27c6ed733fec7e1b162ffecc7d5a073280b40411eff3574d"
PARENT_FILE_SHA256 = "36b6b3a5a31ce88748a7ff69f1ab55f16dae79a78bfb635436a7b13a34c9cbf2"
PARENT_WEIGHTS_SHA256 = "089e67c808189b469ed76c61ce7a41dd144d1caa35fc9869a29b794053e823d2"
MAX_BYTES = 8 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
         "source_semantics_verified": False, "publication_performed": False}
BINDING = {"ir_family_id": "legal_ir", "dimension": 384,
           "dimension_role": "input_embedding", "schema_version": None,
           "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
PROJECTION_NAMES = ("projection_down.weight", "projection_down.bias",
                    "projection_up.weight", "projection_up.bias")
PROVENANCE_FIELDS = {"recipe_sha256", "minibatch_schedule_sha256",
                     "auxiliary_initial_state_sha256", "training_backend_sha256",
                     "request_sha256"}
FIELDS = {"schema", "domain_id", "dimension", "architecture", "binding",
          "config", "codec", "input_transform", "semantic_paths",
          "training_manifest", "validation_manifest", "parent_reference",
          "initial_reference", "implementation", "initialization", "model_state",
          "weights_sha256", "training", "provenance", *FALSE}
PARENT_FIELDS = {"schema", "domain_id", "dimension", "architecture", "codec",
                 "config", "implementation", "parent_sha256", "parent_binding",
                 "lineage", "model_state", "weights_sha256", "input_transform",
                 "semantic_paths", "training_manifest", "validation_manifest",
                 "training", *FALSE}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(source, value):
    _bridge.require_shared_source(source)
    json.dumps(value, allow_nan=False, sort_keys=True)
    result = source._raw(value)
    _require(type(result) is bytes, "genuine canonical bytes required")
    return result


def _digest(source, value):
    return hashlib.sha256(_raw(source, value)).hexdigest()


def _same(source, actual, expected):
    return _raw(source, actual) == _raw(source, expected)


def _sha(value, label):
    _require(type(value) is str and SHA.fullmatch(value) is not None,
             label + " requires a lowercase SHA256")
    return value


def _implementation(source, parity_module):
    _bridge.require_shared_source(source)
    parity_source = _bridge.require_module("context_initialization", parity_module)
    _require(parity_module.SCHEMA == PARITY_SCHEMA
             and parity_module.PROFILE == PARITY_PROFILE
             and parity_module.ARCHITECTURE == ARCHITECTURE
             and _same(source, parity_module.BINDING, BINDING)
             and _same(source, parity_module.FALSE, FALSE),
             "immutable parity module contracts differ")
    return {"trained_context_decoder_sha256": _bridge.require_source("context_trained", _PORTED_SOURCE_SHA256)["sha256"],
            "initial_context_decoder_sha256": parity_source["sha256"],
            "parent_source_implementation": source._implementation(),
            "source_profile_bridge_sha256": _bridge.implementation_sha256()}


def _manifests(source, parent):
    fields = {"id", "source_sha256", "normalized_source_sha256",
              "embedding_sha256", "target_sha256"}
    for name, count in (("training_manifest", 180), ("validation_manifest", 60)):
        rows = parent[name]
        _require(type(rows) is list and len(rows) == count,
                 "original split manifest count differs: " + name)
        _require(all(type(row) is dict and set(row) == fields
                     and type(row["id"]) is str and 0 < len(row["id"]) <= 256
                     and all(type(row[key]) is str and SHA.fullmatch(row[key]) is not None
                             for key in fields - {"id"}) for row in rows),
                 "closed original split manifest rows required")
        _require(len({row["id"] for row in rows}) == count, "duplicate split manifest IDs")
    for key in fields - {"target_sha256"}:
        _require(not {row[key] for row in parent["training_manifest"]}
                 & {row[key] for row in parent["validation_manifest"]},
                 "original train/validation manifest overlap")
    return {name + "_sha256": _digest(source, parent[name])
            for name in ("training_manifest", "validation_manifest")}


def _anchors(torch, source, parity_module, parent, initial, parent_file_sha256,
             initial_file_sha256):
    return _anchors_core(torch, source, parity_module, parent, initial,
                         parent_file_sha256, initial_file_sha256, profile=None)


def _anchors_core(torch, source, parity_module, parent, initial, parent_file_sha256,
             initial_file_sha256, *, profile):
    _bridge.require_module("context_initialization", parity_module)
    parity_module._profile_mode(profile)
    _require(not torch.cuda.is_initialized(), "CPU-only trained context loader required")
    implementation = _implementation(source, parity_module)
    _require(type(parent) is dict and set(parent) == PARENT_FIELDS
             and parent["schema"] == "shared-source-384-autoencoder/v2"
             and type(parent["dimension"]) is int and parent["dimension"] == 384
             and parent_file_sha256 == PARENT_FILE_SHA256
             and parent["weights_sha256"] == PARENT_WEIGHTS_SHA256,
             "authenticated original retained parent required")
    manifest_digests = _manifests(source, parent)
    _sha(initial_file_sha256, "authenticated initial parity file")
    # The reviewed parity validator authenticates its closed original schema,
    # source implementation, all thirteen exact float32 tensors, original
    # codec/normalization, copied blocks, and zero added columns. Trained state
    # is never supplied to it. No Runtime/model is created in this validation.
    initial_tensors = parity_module._validate_core(
        torch, source, parent, initial, parent_file_sha256, profile=profile)
    parent_tensors, parent_reference = parity_module._parent_core(
        torch, source, parent, parent_file_sha256, profile=profile)
    _require(_same(source, source.FALSE, FALSE), "genuine unqualified source flags differ")
    initial_reference = {
        "schema": PARITY_SCHEMA, "architecture": ARCHITECTURE,
        "profile_id": PARITY_PROFILE, "file_sha256": initial_file_sha256,
        "canonical_value_sha256": _digest(source, initial),
        "weights_sha256": initial["weights_sha256"],
    }
    _require(all(torch.equal(initial_tensors[name], parent_tensors[name])
                 for name in PROJECTION_NAMES), "step-zero projection differs from parent")
    return parent_tensors, parent_reference, initial_reference, implementation, manifest_digests


def _initialization(parity_module):
    return {"applies_to": "authenticated_step_zero_parity_checkpoint_only",
            "initial_state_contract": deepcopy(parity_module.INITIALIZATION),
            "trained_state_may_change_token_and_context_columns": True,
            "projection_tensors_unchanged_through_training": list(PROJECTION_NAMES)}


def _training(optimizer_steps, manifest_digests):
    _require(type(optimizer_steps) is int and optimizer_steps in (75, 150),
             "trained profile accepts only completed steps75 or150; step0 uses parity schema")
    return {
        "profile_id": PROFILE, "optimizer_steps": optimizer_steps,
        "optimizer": "fresh_Adam_default_betas_eps_weight_decay_zero",
        "learning_rate": .003, "batch_size": 12, "seed": 1729,
        "maximum_optimizer_steps": 150, "gradient_clip_norm": 5.,
        "auxiliary_weight": 1., "auxiliary_head_scope": "training_only_condition32_four_slots",
        "saved_objective": "source._loss_with_saved_token_weights_and_input_scale",
        "projection_parameters": "all_four_frozen_identically_in_both_arms",
        "optimizer_created": True, "parameter_updates_performed": True,
        "original_optimizer_state_inherited": False,
        "original_source_v2_training_provenance_inherited": False,
        "validation_rows_used_for_gradient_updates": 0, "test_rows_accessed": 0,
        "selected_or_promoted": False,
        "training_history_verified_by_hashes_alone": False,
        **manifest_digests,
    }


def _provenance(provenance):
    _require(type(provenance) is dict and set(provenance) == PROVENANCE_FIELDS,
             "closed owner-authenticated trained provenance required")
    for name in sorted(PROVENANCE_FIELDS):
        _sha(provenance[name], name)
    return deepcopy(provenance)


def _validate(torch, source, parity_module, parent, initial, checkpoint,
              parent_file_sha256, initial_file_sha256):
    return _validate_core(torch, source, parity_module, parent, initial, checkpoint,
                          parent_file_sha256, initial_file_sha256, profile=None)


def _validate_core(torch, source, parity_module, parent, initial, checkpoint,
              parent_file_sha256, initial_file_sha256, *, profile):
    _bridge.require_module("context_initialization", parity_module)
    parity_module._profile_mode(profile)
    if profile is not None:
        parity_module._retained_context150_checkpoint(source, checkpoint, "trained")
    _require(type(checkpoint) is dict and set(checkpoint) == FIELDS,
             "closed trained context checkpoint required")
    _require(len(_raw(source, checkpoint)) <= MAX_BYTES, "trained checkpoint exceeds8MiB")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["architecture"] == ARCHITECTURE
             and checkpoint["domain_id"] == "legal_ir"
             and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == 384
             and _same(source, checkpoint["binding"], BINDING),
             "trained schema, architecture or decoder binding differs")
    _require(all(checkpoint[key] is False for key in FALSE),
             "trained checkpoint cannot grant authority")
    parent_state, parent_ref, initial_ref, implementation, manifests = _anchors_core(
        torch, source, parity_module, parent, initial, parent_file_sha256, initial_file_sha256, profile=profile)
    for name, expected in (("parent_reference", parent_ref), ("initial_reference", initial_ref),
                           ("implementation", implementation),
                           ("initialization", _initialization(parity_module)),
                           ("config", parity_module._config(parent))):
        if name == "implementation" and profile is not None:
            continue  # Exact complete retained recipe was authenticated before tensor access.
        _require((_bridge.compatible_implementation(checkpoint[name], expected)
                  if name == "implementation" else _same(source, checkpoint[name], expected)),
                 "trained " + name + " differs")
    for name in ("codec", "input_transform", "semantic_paths", "training_manifest", "validation_manifest"):
        _require(_same(source, checkpoint[name], parent[name]),
                 "trained " + name + " differs from authenticated parent")
    training = checkpoint["training"]
    _require(type(training) is dict and "optimizer_steps" in training,
             "closed trained profile required")
    _require(_same(source, training, _training(training["optimizer_steps"], manifests)),
             "trained profile differs")
    _provenance(checkpoint["provenance"])
    shapes = parity_module._shapes(len(checkpoint["codec"]["target_vocabulary"]), expanded=True)
    state = checkpoint["model_state"]
    _require(type(state) is dict and len(state) == 13 and set(state) == set(shapes),
             "trained context requires exact thirteen tensor inventory")
    _require(_digest(source, state) == _sha(checkpoint["weights_sha256"], "trained weights"),
             "trained weights digest differs")
    tensors = {name: parity_module._tensor(torch, state[name], shape, "trained " + name)
               for name, shape in shapes.items()}
    for name in PROJECTION_NAMES:
        _require(torch.equal(tensors[name], parent_state[name]),
                 "frozen original projection changed: " + name)
    # Unlike the parity-only profile, no equality or zero restriction applies
    # to the nine trainable decoder tensors or either GRU input column block.
    return tensors


def _model_interface(torch, parity_module, model, vocabulary_size):
    _bridge.require_module("context_initialization", parity_module)
    return parity_module._model_interface(torch, model, vocabulary_size)


def _actual_state(torch, source, parity_module, model, vocabulary_size):
    _model_interface(torch, parity_module, model, vocabulary_size)
    state = model.state_dict()
    shapes = parity_module._shapes(vocabulary_size, expanded=True)
    _require(set(state) == set(shapes) and len(state) == 13 and not list(model.buffers()),
             "actual trained state inventory differs")
    _require(all(value.device.type == "cpu" and value.dtype == torch.float32
                 and tuple(value.shape) == shapes[name] and bool(torch.isfinite(value).all())
                 for name, value in state.items()),
             "actual trained state requires finite CPU float32 tensors with exact shapes")
    values = {name: value.detach().tolist() for name, value in state.items()}
    return values, _digest(source, values)


def make_checkpoint(torch, source, parity_module, parent_cp, initial_parity_cp, model, *,
                    parent_file_sha256, initial_file_sha256, optimizer_steps, provenance):
    """Snapshot actual trained numerical state with separate closed lineage.

    The owner must have observed the claimed optimizer steps and pin the actual
    recipe, train-only schedule, initial auxiliary state, backend and request.
    This function authenticates their shape/bindings, not execution history.
    """
    _, parent_ref, initial_ref, implementation, manifests = _anchors(
        torch, source, parity_module, parent_cp, initial_parity_cp,
        parent_file_sha256, initial_file_sha256)
    state, digest = _actual_state(torch, source, parity_module, model,
                                 len(parent_cp["codec"]["target_vocabulary"]))
    checkpoint = {
        "schema": SCHEMA, "domain_id": "legal_ir", "dimension": 384,
        "architecture": ARCHITECTURE, "binding": deepcopy(BINDING),
        "config": parity_module._config(parent_cp), "codec": deepcopy(parent_cp["codec"]),
        "input_transform": deepcopy(parent_cp["input_transform"]),
        "semantic_paths": deepcopy(parent_cp["semantic_paths"]),
        "training_manifest": deepcopy(parent_cp["training_manifest"]),
        "validation_manifest": deepcopy(parent_cp["validation_manifest"]),
        "parent_reference": parent_ref, "initial_reference": initial_ref,
        "implementation": implementation, "initialization": _initialization(parity_module),
        "model_state": state, "weights_sha256": digest,
        "training": _training(optimizer_steps, manifests),
        "provenance": _provenance(provenance), **FALSE,
    }
    _validate(torch, source, parity_module, parent_cp, initial_parity_cp, checkpoint,
              parent_file_sha256, initial_file_sha256)
    return checkpoint


def load_trained_with_real_parent(torch, source, parity_module, parent_cp,
                                  initial_parity_cp, trained_cp, *,
                                  parent_file_sha256, initial_file_sha256):
    """Validate trained schema and load only into the genuine expanded model."""
    tensors = _validate(torch, source, parity_module, parent_cp, initial_parity_cp,
                        trained_cp, parent_file_sha256, initial_file_sha256)
    return _load_validated_tensors(torch, source, parity_module, trained_cp, tensors)


def _load_validated_tensors(torch, source, parity_module, trained_cp, tensors):
    with source.native._cpu() as cpu_torch:
        _require(cpu_torch is torch, "genuine native CPU context must use supplied Torch")
        model = parity_module._model(torch, len(trained_cp["codec"]["target_vocabulary"]),
                                     trained_cp["config"]["seed"])
        _require(set(model.state_dict()) == set(tensors), "expanded constructor tensor names differ")
        model.load_state_dict(tensors, strict=True)
        model.eval()
        values, digest = _actual_state(torch, source, parity_module, model,
                                      len(trained_cp["codec"]["target_vocabulary"]))
    _require(_same(source, values, trained_cp["model_state"])
             and digest == trained_cp["weights_sha256"]
             and not torch.cuda.is_initialized(), "loaded actual trained model differs")
    return model


def infer_trained(torch, source, parity_module, parent_cp, initial_parity_cp,
                   trained_cp, model, rows, *, parent_file_sha256,
                   initial_file_sha256, batch_size=None):
    """Target-free inference with new trained schema and actual executing digest.

    Exactly id/source_text/embedding are accepted. The original normalized and
    frozen-projected384 embedding is repeated at every genuine GRU step. No
    gold prefix, auxiliary state, readout, template or alternative decoder enters
    generation. The optional batch override supports honest paired diagnostics.
    """
    _validate(torch, source, parity_module, parent_cp, initial_parity_cp, trained_cp,
              parent_file_sha256, initial_file_sha256)
    return _infer_validated(torch, source, parity_module, trained_cp, model, rows, batch_size=batch_size)


def _infer_validated(torch, source, parity_module, trained_cp, model, rows, *, batch_size):
    rows = source._rows("legal_ir", rows, training=False)
    requested = trained_cp["config"]["batch_size"] if batch_size is None else batch_size
    _require(type(requested) is int and 1 <= requested <= 256, "invalid trained inference batch size")
    _require(not torch.cuda.is_initialized(), "CPU-only trained inference required")
    vocabulary = trained_cp["codec"]["target_vocabulary"]
    before, digest = _actual_state(torch, source, parity_module, model, len(vocabulary))
    _require(_same(source, before, trained_cp["model_state"])
             and digest == trained_cp["weights_sha256"],
             "actual trained model differs from checkpoint; stale weights are forbidden")
    transform = trained_cp["input_transform"]
    reports = []
    model.eval()
    with source.native._cpu() as cpu_torch, torch.inference_mode():
        _require(cpu_torch is torch, "genuine native CPU context must use supplied Torch")
        mean = torch.tensor(transform["mean"], dtype=torch.float32, device="cpu")
        for offset in range(0, len(rows), requested):
            part = rows[offset:offset + requested]
            raw = torch.tensor([row["embedding"] for row in part], dtype=torch.float32, device="cpu")
            data = (raw - mean) / transform["scale"]
            projected, sequences, ended = parity_module._greedy(
                torch, model, data, trained_cp["config"]["max_target_tokens"])
            reconstructed = projected * transform["scale"] + mean
            _require(bool(torch.isfinite(reconstructed).all()), "nonfinite reconstructed embedding")
            for row, sequence, end, embedding in zip(part, sequences, ended, reconstructed, strict=True):
                candidate, tokens, reason = source._candidate("legal_ir", sequence, end, vocabulary)
                reports.append({
                    "id": row["id"],
                    "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                    "status": "unqualified_candidate" if candidate is not None else "fail_open_invalid_output",
                    "reason": reason, "candidate_ir": candidate, "generated_tokens": tokens,
                    "ended": end, "reconstructed_embedding": embedding.tolist(),
                    "weight_ablation": None, "weights_sha256": digest,
                    "target_access": False, "teacher_forcing": False,
                    "continue_planning": True, **FALSE,
                })
    after, after_digest = _actual_state(torch, source, parity_module, model, len(vocabulary))
    _require(_same(source, after, before) and after_digest == digest
             and not torch.cuda.is_initialized(), "trained inference changed weights or initialized CUDA")
    return {"schema": SCHEMA, "domain_id": "legal_ir", "dimension": 384,
            "rows": reports, **FALSE}


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('context_trained', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('context_trained')



def _retained_inputs(source, parity_module, parent, initial, trained, *, parent_file_sha256,
                     initial_file_sha256, trained_file_sha256):
    _bridge.require_shared_source(source)
    _bridge.require_source("context_trained", _PORTED_SOURCE_SHA256)
    _bridge.require_module("context_initialization", parity_module)
    _require(type(trained) is dict, "retained trained checkpoint required before numerical access")
    return parity_module._retained_context150_inputs(source, parent, initial, trained,
        parent_file_sha256=parent_file_sha256, initial_file_sha256=initial_file_sha256,
        trained_file_sha256=trained_file_sha256)


def load_retained_context150_trained(torch, source, parity_module, parent_cp,
                                    initial_parity_cp, trained_cp, *, parent_file_sha256,
                                    initial_file_sha256, trained_file_sha256):
    """Restore the exact retained step150 state with a separate immutable receipt."""
    parent, initial, trained = _retained_inputs(source, parity_module, parent_cp, initial_parity_cp, trained_cp,
        parent_file_sha256=parent_file_sha256, initial_file_sha256=initial_file_sha256,
        trained_file_sha256=trained_file_sha256)
    with source.native._cpu() as cpu_torch:
        _require(cpu_torch is torch, "genuine native CPU context must use supplied Torch")
        tensors = _validate_core(torch, source, parity_module, parent, initial, trained,
            parent_file_sha256, initial_file_sha256, profile=parity_module._RETAINED_CONTEXT150_PROFILE)
        model = _load_validated_tensors(torch, source, parity_module, trained, tensors)
        _retained_inputs(source, parity_module, parent_cp, initial_parity_cp, trained_cp,
            parent_file_sha256=parent_file_sha256, initial_file_sha256=initial_file_sha256,
            trained_file_sha256=trained_file_sha256)
        _, digest = _actual_state(torch, source, parity_module, model, len(trained["codec"]["target_vocabulary"]))
        receipt = parity_module._retained_context150_receipt(source, parent, initial, trained,
            operation="trained_checkpoint_restore", details={"actual_weights_sha256": digest})
        return model, receipt


def infer_retained_context150_trained(torch, source, parity_module, parent_cp, initial_parity_cp,
                                     trained_cp, model, rows, *, parent_file_sha256,
                                     initial_file_sha256, trained_file_sha256, batch_size=None):
    """Reauthenticate all three anchors before target-free retained inference."""
    parent, initial, trained = _retained_inputs(source, parity_module, parent_cp, initial_parity_cp, trained_cp,
        parent_file_sha256=parent_file_sha256, initial_file_sha256=initial_file_sha256,
        trained_file_sha256=trained_file_sha256)
    rows = source._rows("legal_ir", rows, training=False)
    input_rows_sha256 = _digest(source, rows)
    with source.native._cpu() as cpu_torch:
        _require(cpu_torch is torch, "genuine native CPU context must use supplied Torch")
        _validate_core(torch, source, parity_module, parent, initial, trained,
            parent_file_sha256, initial_file_sha256, profile=parity_module._RETAINED_CONTEXT150_PROFILE)
        report = _infer_validated(torch, source, parity_module, trained, model, rows, batch_size=batch_size)
        _retained_inputs(source, parity_module, parent_cp, initial_parity_cp, trained_cp,
            parent_file_sha256=parent_file_sha256, initial_file_sha256=initial_file_sha256,
            trained_file_sha256=trained_file_sha256)
        _, digest = _actual_state(torch, source, parity_module, model, len(trained["codec"]["target_vocabulary"]))
        receipt = parity_module._retained_context150_receipt(source, parent, initial, trained,
            operation="trained_target_free_inference", details={"output_sha256": _digest(source, report), "input_rows_sha256": input_rows_sha256,
                "batch_size": trained["config"]["batch_size"] if batch_size is None else batch_size,
                "max_target_tokens": trained["config"]["max_target_tokens"],
                "actual_weights_sha256": digest, "rows": len(report["rows"])})
        return report, receipt
