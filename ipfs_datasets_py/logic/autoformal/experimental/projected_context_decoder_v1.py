"""Separate, parity-only LegalIR decoder with repeated projected384 context.

The caller supplies genuine Torch/source modules and authenticated parent assets.
No framework is imported here and no asset, provider, optimizer or training API
exists. The new GRU input has token16 followed by the actual projected384.
Every saved block is copied exactly; only the added input columns are zero.

The strict loader accepts this untrained initialization profile only. A future
trained context model needs a separately reviewed/versioned profile and loader.
Expanded state is never passed to the historical source.Runtime loader.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('context_initialization')["sha256"]


SCHEMA = "legal-ir-projected-context-decoder/v1"
ARCHITECTURE = "residual-projection-repeated-projected-context-formula-gru/v1"
PROFILE = "projected-context-initialization-parity/v1"
MAX_BYTES = 8 * 1024 * 1024
EXPANDED_TENSOR = "decoder.weight_ih_l0"
FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
         "source_semantics_verified": False, "publication_performed": False}
BINDING = {"ir_family_id": "legal_ir", "dimension": 384,
           "dimension_role": "input_embedding", "schema_version": None,
           "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
SLOT_PATHS = [["rules", 0, "action"], ["rules", 0, "actor"],
              ["rules", 0, "modality"], ["rules", 0, "object"]]
INITIALIZATION = {
    "profile_id": PROFILE,
    "copied_unchanged_full_tensor_count": 12,
    "expanded_tensor": EXPANDED_TENSOR,
    "original_input_weight_shape": [96, 16],
    "expanded_input_weight_shape": [96, 400],
    "copied_token_column_range": [0, 16],
    "zero_context_column_range": [16, 400],
    "added_context_dimension": 384,
    "added_context_parameters": 36864,
    "all_compatible_blocks_copied_exactly": True,
    "added_context_columns_exactly_zero": True,
    "context_source": "projected384",
    "context_order": "token_embedding16_then_projected384",
    "random_effective_parameters_used": False,
    "temporary_module_initialization": "isolated_cpu_fork_rng_then_strict_full_state_load",
}
TRAINING = {
    "profile_id": PROFILE, "optimizer_steps": 0, "optimizer_created": False,
    "parameter_updates_performed": False, "original_optimizer_state_inherited": False,
    "original_source_v2_training_provenance_inherited": False,
    "validation_rows_used_for_gradient_updates": 0, "test_rows_accessed": 0,
    "selected_or_promoted": False,
}
FIELDS = {"schema", "domain_id", "dimension", "architecture", "binding",
          "config", "codec", "input_transform", "semantic_paths", "parent_reference",
          "implementation", "initialization", "model_state", "weights_sha256",
          "training", *FALSE}
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(source, value):
    _bridge.require_shared_source(source)
    # Check standard JSON finiteness/types independently of the source serializer.
    json.dumps(value, allow_nan=False, sort_keys=True)
    raw = source._raw(value)
    _require(type(raw) is bytes, "canonical source serializer must return bytes")
    return raw


def _digest(source, value):
    return hashlib.sha256(_raw(source, value)).hexdigest()


def _sha(value, label):
    _require(type(value) is str and SHA.fullmatch(value) is not None,
             label + " requires a lowercase SHA256")
    return value


def _same_json(source, actual, expected):
    """Preserve JSON scalar types as well as values in closed identities."""
    return _raw(source, actual) == _raw(source, expected)


def _implementation(source):
    _bridge.require_shared_source(source)
    return {"context_decoder_sha256": _bridge.require_source("context_initialization", _PORTED_SOURCE_SHA256)["sha256"],
            "parent_source_implementation": source._implementation(),
            "source_profile_bridge_sha256": _bridge.implementation_sha256()}


def inspect_parent_source_compatibility(source, parent_checkpoint, *, expected_checkpoint_sha256):
    """Compare authenticated parent source metadata without loading its model.

    ``expected_checkpoint_sha256`` binds the entire canonical ``source._raw``
    value, not an arbitrary JSON file encoding. The caller authenticates any
    physical input file separately. Tensor contents, shapes, weight digests,
    architecture suitability and training history remain unchecked. A compatible
    report cannot replace the unchanged strict numerical parent/load validators.
    """
    _bridge.require_shared_source(source)
    _bridge.require_source("context_initialization", _PORTED_SOURCE_SHA256)
    _sha(expected_checkpoint_sha256, "expected canonical parent checkpoint")
    # Bound ordinary JSON before invoking serializers; never call object hooks.
    active, remaining = set(), [500000, MAX_BYTES]
    def bounded(value, depth=0):
        kind = type(value)
        remaining[0] -= 1
        _require(remaining[0] >= 0 and depth <= 64, "parent JSON node/depth bound exceeded")
        if kind is dict or kind is list:
            _require(id(value) not in active and len(value) <= remaining[0],
                     "cyclic or oversized parent JSON container")
            remaining[1] -= 2 + max(0, len(value) - 1)
            active.add(id(value))
            try:
                if kind is dict:
                    remaining[1] -= len(value)
                    for key, child in value.items():
                        _require(type(key) is str, "ordinary parent JSON string keys required")
                        bounded(key, depth + 1); bounded(child, depth + 1)
                else:
                    for child in value:
                        bounded(child, depth + 1)
            finally:
                active.remove(id(value))
        else:
            _require(value is None or kind is str or kind is bool or kind is int or kind is float,
                     "ordinary parent JSON scalars required")
            _require(kind is not str or len(value) <= 65536, "parent JSON string bound exceeded")
            _require(kind is not int or -2**63 <= value < 2**63, "parent JSON integer bound exceeded")
            _require(kind is not float or math.isfinite(value), "finite parent JSON numbers required")
            remaining[1] -= len(json.dumps(value, ensure_ascii=True, allow_nan=False))
        _require(remaining[1] >= 0, "parent JSON byte bound exceeded")
    bounded(parent_checkpoint)
    fields = {"schema", "domain_id", "dimension", "architecture", "codec", "config",
              "implementation", "parent_sha256", "parent_binding", "lineage", "model_state",
              "weights_sha256", "input_transform", "semantic_paths", "training_manifest",
              "validation_manifest", "training", *FALSE}
    _require(type(parent_checkpoint) is dict and set(parent_checkpoint) == fields,
             "closed source-v2 parent envelope required")
    _require(parent_checkpoint["schema"] == source.SCHEMA
             and parent_checkpoint["domain_id"] == "legal_ir"
             and type(parent_checkpoint["dimension"]) is int and parent_checkpoint["dimension"] == 384
             and type(parent_checkpoint["architecture"]) is str
             and 0 < len(parent_checkpoint["architecture"]) <= 256
             and all(parent_checkpoint[key] is False for key in FALSE),
             "unqualified LegalIR384 parent envelope required")
    for name in ("codec", "config", "implementation", "parent_binding", "lineage",
                 "model_state", "input_transform", "training"):
        _require(type(parent_checkpoint[name]) is dict, "parent " + name + " must be a plain object")
    for name in ("semantic_paths", "training_manifest", "validation_manifest"):
        _require(type(parent_checkpoint[name]) is list, "parent " + name + " must be a plain array")
    for name in ("parent_sha256", "weights_sha256"):
        _sha(parent_checkpoint[name], "declared parent " + name)
    raw = _raw(source, parent_checkpoint)
    _require(len(raw) <= MAX_BYTES, "canonical parent exceeds8MiB")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    _require(actual_sha256 == expected_checkpoint_sha256, "canonical parent checkpoint digest differs")
    offered = json.loads(raw)["implementation"]
    current = source._implementation()
    _bridge._bounded(offered); _bridge._bounded(current)
    mismatches = []
    def compare(saved, executing, path):
        _require(type(saved) is type(executing), "parent implementation scalar/container type differs")
        if type(executing) is dict:
            _require(set(saved) == set(executing), "closed parent implementation fields required")
            for key in sorted(executing):
                compare(saved[key], executing[key], path + [key])
        else:
            _require(type(executing) is str, "parent implementation strings required")
            if path[-1] != "scope":
                _sha(saved, "declared parent implementation identity")
                _sha(executing, "current parent implementation identity")
            if saved != executing:
                _require(len(mismatches) < 128, "parent implementation mismatch report exceeds bound")
                mismatches.append({"field_path": path, "expected": saved, "current": executing})
    compare(offered, current, ["implementation"])
    return {
        "schema": "legal-ir-parent-source-compatibility/v1",
        "scope": "source_implementation_metadata_only",
        "checkpoint_canonical_sha256": actual_sha256,
        "expected_implementation_sha256": _digest(source, offered),
        "current_implementation_sha256": _digest(source, current),
        "compatible": not mismatches, "mismatches": mismatches,
        "weights_checked": False, "tensor_shapes_checked": False,
        "numerical_execution_performed": False, "checkpoint_load_qualified": False,
        **FALSE,
    }


def _shapes(vocabulary_size, expanded):
    return {
        "projection_down.weight": (8, 384), "projection_down.bias": (8,),
        "projection_up.weight": (384, 8), "projection_up.bias": (384,),
        "condition.weight": (32, 384), "condition.bias": (32,),
        "target_embedding.weight": (vocabulary_size, 16),
        "decoder.weight_ih_l0": (96, 400 if expanded else 16),
        "decoder.weight_hh_l0": (96, 32),
        "decoder.bias_ih_l0": (96,), "decoder.bias_hh_l0": (96,),
        "output.weight": (vocabulary_size, 32), "output.bias": (vocabulary_size,),
    }


def _tensor(torch, value, shape, label):
    def check(part, remainder):
        if remainder:
            _require(type(part) is list and len(part) == remainder[0],
                     label + " tensor shape differs")
            for child in part:
                check(child, remainder[1:])
        else:
            _require(type(part) in (int, float) and math.isfinite(part),
                     label + " tensor value is not a finite number")
    check(value, shape)
    result = torch.tensor(value, dtype=torch.float32, device="cpu")
    _require(tuple(result.shape) == shape and bool(torch.isfinite(result).all()),
             label + " tensor overflows CPU float32")
    # Reject values silently rounded by the loader. Serialized state must be the
    # exact actual float32 values, so its digest describes the executing model.
    _require(result.tolist() == value, label + " state is not an exact float32 representation")
    return result


def _parent(torch, source, checkpoint, parent_file_sha256):
    _bridge.require_shared_source(source)
    _sha(parent_file_sha256, "authenticated parent file")
    _require(source.FALSE == FALSE and checkpoint["schema"] == source.SCHEMA
             and checkpoint["domain_id"] == "legal_ir" and checkpoint["dimension"] == 384,
             "genuine retained LegalIR384 source parent required")
    _require(checkpoint["implementation"] == source._implementation(),
             "parent source implementation differs")
    _require(all(checkpoint.get(key) is False for key in FALSE),
             "parent cannot grant authority")
    _require(checkpoint["architecture"] == source.numerical.ARCHITECTURE,
             "retained parent architecture differs")
    config = checkpoint["config"]
    _require(config["hidden_size"] == 32 and config["token_embedding_dim"] == 16
             and config["projection_width"] == 8 and config["max_target_tokens"] == 512,
             "parent shape or saved512 token cap differs")
    _require(type(config["batch_size"]) is int and 1 <= config["batch_size"] <= 256
             and type(config["seed"]) is int and 0 <= config["seed"] < 2**31,
             "invalid retained inference settings")
    codec = checkpoint["codec"]
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
             and codec["schema"] == "typed-json-lexical/v1", "retained codec differs")
    vocabulary = codec["target_vocabulary"]
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
             and vocabulary[:3] == list(source.native.SPECIAL)
             and all(type(token) is str and len(token) <= 16384
                     and source.native._TOKEN.fullmatch(token) for token in vocabulary[3:])
             and vocabulary[3:] == sorted(set(vocabulary[3:])), "retained vocabulary differs")
    _require(checkpoint["semantic_paths"] == SLOT_PATHS,
             "retained semantic paths differ")
    transform = checkpoint["input_transform"]
    _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
             and transform["origin"] == "training_only"
             and transform["mode"] == config["input_normalization"]
             and transform["mode"] in ("center_rms", "none"), "retained transform differs")
    _tensor(torch, transform["mean"], (384,), "retained input mean")
    _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
             and .01 <= transform["scale"] <= 1e8, "invalid retained input scalar scale")
    if transform["mode"] == "none":
        _require(transform["mean"] == [0.] * 384 and transform["scale"] == 1.,
                 "retained identity input transform differs")
    shapes = _shapes(len(vocabulary), expanded=False)
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(shapes) and len(state) == 13,
             "parent must have exact thirteen tensor inventory")
    tensors = {name: _tensor(torch, state[name], shape, "parent " + name)
               for name, shape in shapes.items()}
    _require(_digest(source, state) == _sha(checkpoint["weights_sha256"], "parent weights"),
             "retained parent weights digest differs")
    reference = {"schema": checkpoint["schema"], "architecture": checkpoint["architecture"],
                 "canonical_value_sha256": _digest(source, checkpoint),
                 "file_sha256": parent_file_sha256, "weights_sha256": checkpoint["weights_sha256"]}
    return tensors, reference


def _config(parent):
    return {"hidden_size": 32, "token_embedding_dim": 16, "projection_width": 8,
            "context_dimension": 384, "gru_input_dimension": 400,
            "context_source": "projected384", "context_order": "token_embedding16_then_projected384",
            "max_target_tokens": 512, "batch_size": parent["config"]["batch_size"],
            "seed": parent["config"]["seed"]}


def _model(torch, vocabulary_size, seed):
    class ProjectedContextDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            options = {"device": "cpu", "dtype": torch.float32}
            self.projection_down = torch.nn.Linear(384, 8, **options)
            self.projection_up = torch.nn.Linear(8, 384, **options)
            self.condition = torch.nn.Linear(384, 32, **options)
            self.target_embedding = torch.nn.Embedding(vocabulary_size, 16, padding_idx=0, **options)
            self.decoder = torch.nn.GRU(400, 32, batch_first=True, **options)
            self.output = torch.nn.Linear(32, vocabulary_size, **options)

        def project(self, latent):
            return latent + self.projection_up(torch.tanh(self.projection_down(latent)))

        def start(self, projected):
            return torch.tanh(self.condition(projected)).unsqueeze(0)

        def next_logits(self, tokens, hidden, context):
            _require(tokens.ndim == 2 and context.shape == (tokens.shape[0], 384)
                     and context.dtype == torch.float32 and context.device.type == "cpu"
                     and bool(torch.isfinite(context).all()), "actual projected384 context required")
            embedded = self.target_embedding(tokens)
            repeated = context.unsqueeze(1).expand(-1, tokens.shape[1], -1)
            joined = torch.cat((embedded, repeated), dim=-1)
            outputs, hidden = self.decoder(joined, hidden)
            return self.output(outputs), hidden

        def forward(self, latent, target):
            projected = self.project(latent)
            return projected, self.next_logits(target, self.start(projected), projected)[0]

    before_rng = torch.get_rng_state().clone()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = ProjectedContextDecoder()
    _require(torch.equal(torch.get_rng_state(), before_rng), "CPU construction RNG escaped isolation")
    return model


def model_state(torch, source, model):
    """Return actual finite CPU float32 expanded state and its canonical digest."""
    _bridge.require_shared_source(source)
    state = model.state_dict()
    _require(len(state) == 13 and all(value.device.type == "cpu" and value.dtype == torch.float32
                                     and bool(torch.isfinite(value).all()) for value in state.values()),
             "expanded state requires thirteen finite CPU float32 tensors")
    values = {name: value.detach().tolist() for name, value in state.items()}
    return values, _digest(source, values)


def _validate(torch, source, parent_checkpoint, checkpoint, parent_file_sha256):
    _require(type(checkpoint) is dict and set(checkpoint) == FIELDS, "closed new checkpoint required")
    _require(len(_raw(source, checkpoint)) <= MAX_BYTES, "new checkpoint exceeds8MiB")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["architecture"] == ARCHITECTURE
             and checkpoint["domain_id"] == "legal_ir" and type(checkpoint["dimension"]) is int
             and checkpoint["dimension"] == 384 and _same_json(source, checkpoint["binding"], BINDING),
             "new schema, architecture or decoder binding differs")
    _require(all(checkpoint[key] is False for key in FALSE), "new checkpoint cannot grant authority")
    parent_state, reference = _parent(torch, source, parent_checkpoint, parent_file_sha256)
    _require(_same_json(source, checkpoint["parent_reference"], reference), "new checkpoint parent identity differs")
    _require(_bridge.compatible_implementation(checkpoint["implementation"], _implementation(source)),
             "new decoder/source implementation differs")
    _require(_same_json(source, checkpoint["config"], _config(parent_checkpoint)),
             "closed new inference config differs")
    for name in ("codec", "input_transform", "semantic_paths"):
        _require(_same_json(source, checkpoint[name], parent_checkpoint[name]),
                 "new " + name + " differs from retained parent")
    _require(_same_json(source, checkpoint["initialization"], INITIALIZATION)
             and _same_json(source, checkpoint["training"], TRAINING),
             "parity-only profile required; trained context state needs another versioned loader")
    shapes = _shapes(len(checkpoint["codec"]["target_vocabulary"]), expanded=True)
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(shapes) and len(state) == 13,
             "new checkpoint tensor inventory differs")
    _require(_digest(source, state) == _sha(checkpoint["weights_sha256"], "new weights"),
             "new checkpoint weights digest differs")
    tensors = {name: _tensor(torch, state[name], shape, "new " + name)
               for name, shape in shapes.items()}
    for name, value in tensors.items():
        if name == EXPANDED_TENSOR:
            _require(torch.equal(value[:, :16], parent_state[name]), "saved GRU token columns differ")
            _require(bool((value[:, 16:] == 0).all()), "parity-only context columns must all be zero")
        else:
            _require(torch.equal(value, parent_state[name]), "compatible saved tensor differs: " + name)
    return tensors


def build_from_real_parent(torch, source, parent_checkpoint, parent_runtime, *, parent_file_sha256):
    """Construct an untrained expanded model from genuine authenticated parent."""
    _bridge.require_shared_source(source)
    _require(isinstance(parent_runtime, source.Runtime), "genuine original source.Runtime required")
    _require(_digest(source, parent_runtime.checkpoint) == _digest(source, parent_checkpoint),
             "parent Runtime checkpoint differs")
    tensors, reference = _parent(torch, source, parent_checkpoint, parent_file_sha256)
    actual_state = parent_runtime.model.state_dict()
    _require(set(actual_state) == set(tensors) and all(
        actual_state[name].dtype == torch.float32 and actual_state[name].device.type == "cpu"
        and torch.equal(actual_state[name].detach(), value) for name, value in tensors.items()),
        "actual original Runtime does not contain all thirteen saved tensors")
    expanded = {name: value.detach().clone() for name, value in tensors.items()}
    new_input = torch.zeros((96, 400), dtype=torch.float32, device="cpu")
    new_input[:, :16].copy_(expanded[EXPANDED_TENSOR])
    expanded[EXPANDED_TENSOR] = new_input
    values = {name: value.tolist() for name, value in expanded.items()}
    checkpoint = {"schema": SCHEMA, "domain_id": "legal_ir", "dimension": 384,
                  "architecture": ARCHITECTURE, "binding": deepcopy(BINDING),
                  "config": _config(parent_checkpoint), "codec": deepcopy(parent_checkpoint["codec"]),
                  "input_transform": deepcopy(parent_checkpoint["input_transform"]),
                  "semantic_paths": deepcopy(parent_checkpoint["semantic_paths"]),
                  "parent_reference": reference, "implementation": _implementation(source),
                  "initialization": deepcopy(INITIALIZATION), "model_state": values,
                  "weights_sha256": _digest(source, values), "training": deepcopy(TRAINING), **FALSE}
    model = load_with_real_parent(torch, source, parent_checkpoint, checkpoint,
                                  parent_file_sha256=parent_file_sha256)
    _require(all(torch.equal(parent_runtime.model.state_dict()[name].detach(), value)
                 for name, value in tensors.items()), "parent Runtime changed during expansion")
    return checkpoint, model


def load_with_real_parent(torch, source, parent_checkpoint, checkpoint, *, parent_file_sha256):
    """Strictly validate/load only the separate zero-context initialization profile.

    The file digest is supplied by the root owner after authenticating the actual
    parent file. This module authenticates content and the passed file identity;
    it never opens that asset. It reads only its own .py file for implementation
    binding. The historical Runtime is never asked to load expanded state.
    """
    _bridge.require_shared_source(source)
    _require(not torch.cuda.is_initialized(), "CPU-only context parity loader required")
    tensors = _validate(torch, source, parent_checkpoint, checkpoint, parent_file_sha256)
    model = _model(torch, len(checkpoint["codec"]["target_vocabulary"]), checkpoint["config"]["seed"])
    _require(set(model.state_dict()) == set(tensors), "new numerical tensor names differ")
    model.load_state_dict(tensors, strict=True)
    model.eval()
    values, digest = model_state(torch, source, model)
    _require(values == checkpoint["model_state"] and digest == checkpoint["weights_sha256"],
             "strict-loaded actual context model state differs")
    return model


def _greedy(torch, model, data, max_tokens):
    projected = model.project(data)
    hidden = model.start(projected)
    _require(bool(torch.isfinite(projected).all()), "nonfinite reconstructed embedding")
    current = torch.ones((len(data), 1), dtype=torch.long, device="cpu")
    active = torch.ones(len(data), dtype=torch.bool, device="cpu")
    sequences, ended = [[] for _ in range(len(data))], [False] * len(data)
    for _ in range(max_tokens - 1):
        logits, hidden = model.next_logits(current, hidden, projected)
        _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(hidden).all()),
                 "nonfinite generated context state")
        indices = logits[:, -1].argmax(-1)
        for index, token in enumerate(indices.tolist()):
            if not active[index]:
                continue
            if token == 2:
                ended[index], active[index] = True, False
            elif token in (0, 1):
                active[index] = False
            else:
                sequences[index].append(token)
        if not bool(active.any()):
            break
        current = indices.unsqueeze(1)
    return projected, sequences, ended


def infer(torch, source, parent_checkpoint, checkpoint, model, rows, *,
          parent_file_sha256, batch_size=None):
    """Target-free generation with new-schema identity and actual weight digest.

    Exactly id/source_text/embedding are allowed per source._rows(training=False).
    Source text contributes only its provenance hash; embeddings supply context.
    The optional batch override is for paired batch1/batch12 parity diagnostics.
    No gold target, readout predictions, templates or alternate decoder is used.
    """
    _validate(torch, source, parent_checkpoint, checkpoint, parent_file_sha256)
    rows = source._rows("legal_ir", rows, training=False)
    requested = checkpoint["config"]["batch_size"] if batch_size is None else batch_size
    _require(type(requested) is int and 1 <= requested <= 256, "invalid inference batch size")
    _require(not torch.cuda.is_initialized(), "CPU-only context inference required")
    before, digest = model_state(torch, source, model)
    _require(before == checkpoint["model_state"] and digest == checkpoint["weights_sha256"],
             "actual model differs from new checkpoint; stale weights are forbidden")
    transform, vocabulary = checkpoint["input_transform"], checkpoint["codec"]["target_vocabulary"]
    reports = []
    model.eval()
    with source.native._cpu() as cpu_torch, torch.inference_mode():
        _require(cpu_torch is torch, "genuine native CPU context must use supplied Torch")
        mean = torch.tensor(transform["mean"], dtype=torch.float32, device="cpu")
        for offset in range(0, len(rows), requested):
            part = rows[offset:offset + requested]
            raw = torch.tensor([row["embedding"] for row in part], dtype=torch.float32, device="cpu")
            data = (raw - mean) / transform["scale"]
            projected, sequences, ended = _greedy(torch, model, data, checkpoint["config"]["max_target_tokens"])
            reconstructed = projected * transform["scale"] + mean
            for row, sequence, end, embedding in zip(part, sequences, ended, reconstructed, strict=True):
                candidate, tokens, reason = source._candidate("legal_ir", sequence, end, vocabulary)
                reports.append({"id": row["id"],
                    "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                    "status": "unqualified_candidate" if candidate is not None else "fail_open_invalid_output",
                    "reason": reason, "candidate_ir": candidate, "generated_tokens": tokens,
                    "ended": end, "reconstructed_embedding": embedding.tolist(),
                    "weight_ablation": None, "weights_sha256": digest,
                    "target_access": False, "teacher_forcing": False, "continue_planning": True, **FALSE})
    _require(model_state(torch, source, model)[1] == digest and not torch.cuda.is_initialized(),
             "context inference changed weights or initialized CUDA")
    return {"schema": SCHEMA, "domain_id": "legal_ir", "dimension": 384, "rows": reports, **FALSE}


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('context_initialization', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('context_initialization')
