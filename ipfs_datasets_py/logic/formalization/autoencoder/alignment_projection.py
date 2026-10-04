"""Training-only Legal facet features and CPU projection heads for alignment.

Import is standard-library-only. Numerical entry points lazily require PyTorch;
they never load an encoder, change donor weights, download assets, or use a GPU.
The formal features describe one canonical rule and preserve unknown values as
explicit unknown buckets. Projection outputs are normalized retrieval vectors,
not vocabulary logits, decoded formulas, or proof/qualification evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

CODEC_SCHEMA = "legal-alignment-facet-codec/v1"
CHECKPOINT_SCHEMA = "legal-alignment-projection-checkpoint/v1"
IMPLEMENTATION_PROFILE = "dual-linear-l2-cpu-float32/v1"
SOURCE_SPACE_ID = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
                   "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
MAX_FEATURE_DIMENSION = 4096
MAX_CODEC_BYTES = 1024 * 1024
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
MAX_BATCH_SIZE = 512
_FLOAT32_MAX = 3.4028234663852886e38
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("finite ordinary JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _rule(target):
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule

    _require(type(target) is dict and set(target) == {"rules"}
             and type(target["rules"]) is list and len(target["rules"]) == 1,
             "one canonical Legal rule target required")
    rule = CanonicalRule.from_dict(target["rules"][0]).to_dict()
    _require(_raw(rule) == _raw(target["rules"][0]), "target facets must already be canonical")
    return rule


def _validate_codec(codec):
    fields = {"schema", "fit_policy", "training_target_count", "training_target_manifest_sha256",
              "blocks", "feature_dimension", "unknown_policy", "development_fit",
              "qualified", "codec_sha256", "feature_space_id"}
    _require(type(codec) is dict and set(codec) == fields, "closed Legal feature codec required")
    _require(len(_raw(codec)) <= MAX_CODEC_BYTES, "codec exceeds byte bound")
    _require(codec["schema"] == CODEC_SCHEMA and codec["fit_policy"] == "training_targets_only"
             and codec["unknown_policy"] == "one_explicit_unknown_bucket_per_facet"
             and codec["development_fit"] is False and codec["qualified"] is False,
             "codec scope or fit policy differs")
    _require(type(codec["training_target_count"]) is int and 1 <= codec["training_target_count"] <= 5000,
             "bounded training target count required")
    _require(type(codec["training_target_manifest_sha256"]) is str
             and _SHA.fullmatch(codec["training_target_manifest_sha256"]), "training manifest SHA256 required")
    _require(type(codec["blocks"]) is list and len(codec["blocks"]) == len(FACETS), "seven facet blocks required")
    offset = 0
    for index, (facet, block) in enumerate(zip(FACETS, codec["blocks"], strict=True)):
        _require(type(block) is dict and set(block) == {"facet", "kind", "vocabulary", "offset", "width", "unknown_index"},
                 "closed facet block required")
        vocabulary = block["vocabulary"]
        _require(type(vocabulary) is list and len(vocabulary) <= MAX_FEATURE_DIMENSION
                 and all(type(value) is str and 0 < len(value) <= 32768 for value in vocabulary)
                 and vocabulary == sorted(set(vocabulary)), "canonical unique facet vocabulary required")
        _require(block["facet"] == facet and block["kind"] == ("categorical" if index < 4 else "bag"),
                 "facet identity or feature kind differs")
        for name, expected in (("offset", offset), ("width", len(vocabulary) + 1),
                               ("unknown_index", offset + len(vocabulary))):
            _require(type(block[name]) is int and block[name] == expected, "facet geometry differs")
        offset += block["width"]
    _require(type(codec["feature_dimension"]) is int and codec["feature_dimension"] == offset
             and 1 <= offset <= MAX_FEATURE_DIMENSION, "feature dimension differs or exceeds bound")
    body = {name: value for name, value in codec.items() if name not in ("codec_sha256", "feature_space_id")}
    digest = _digest(body)
    _require(codec["codec_sha256"] == digest and codec["feature_space_id"] == "canonical-legal-rule-facets:sha256:" + digest,
             "codec content identity differs")
    return codec


def fit_legal_feature_codec(training_targets) -> dict:
    """Fit only the supplied training targets; never accept development rows."""
    _require(type(training_targets) in (list, tuple) and 1 <= len(training_targets) <= 5000,
             "bounded nonempty training targets required")
    rules = [_rule(target) for target in training_targets]
    blocks, offset = [], 0
    for index, facet in enumerate(FACETS):
        values = {rule[facet] for rule in rules} if index < 4 else {value for rule in rules for value in rule[facet]}
        vocabulary = sorted(values)
        blocks.append({"facet": facet, "kind": "categorical" if index < 4 else "bag",
                       "vocabulary": vocabulary, "offset": offset, "width": len(vocabulary) + 1,
                       "unknown_index": offset + len(vocabulary)})
        offset += len(vocabulary) + 1
    codec = {"schema": CODEC_SCHEMA, "fit_policy": "training_targets_only",
             "training_target_count": len(rules),
             "training_target_manifest_sha256": _digest([_digest({"rules": [rule]}) for rule in rules]),
             "blocks": blocks, "feature_dimension": offset,
             "unknown_policy": "one_explicit_unknown_bucket_per_facet",
             "development_fit": False, "qualified": False}
    digest = _digest(codec)
    codec.update(codec_sha256=digest, feature_space_id="canonical-legal-rule-facets:sha256:" + digest)
    _validate_codec(codec)
    return codec


def encode_legal_target(target, codec) -> list[float]:
    """Encode against a frozen training codec, counting unseen values explicitly."""
    _validate_codec(codec)
    rule = _rule(target)
    features = [0.0] * codec["feature_dimension"]
    for block in codec["blocks"]:
        positions = {value: block["offset"] + index for index, value in enumerate(block["vocabulary"])}
        values = [rule[block["facet"]]] if block["kind"] == "categorical" else rule[block["facet"]]
        for value in values:
            features[positions.get(value, block["unknown_index"])] += 1.0
    return features


def _torch():
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("alignment projections require optional PyTorch") from error
    return torch


def _dimensions(input_dimension, formal_dimension, shared_dimension, seed):
    _require(type(input_dimension) is int and input_dimension == 384, "exact 384D source input required")
    _require(type(formal_dimension) is int and 1 <= formal_dimension <= MAX_FEATURE_DIMENSION,
             "bounded formal feature dimension required")
    _require(type(shared_dimension) is int and shared_dimension in (384, 512), "shared dimension must be 384 or 512")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer seed required")


def create_projection_heads(input_dimension, formal_dimension, shared_dimension, seed):
    """Create independent trainable CPU float32 linear heads without RNG drift."""
    _dimensions(input_dimension, formal_dimension, shared_dimension, seed)
    torch = _torch()

    class ProjectionHeads(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.input_dimension = input_dimension
            self.formal_dimension = formal_dimension
            self.shared_dimension = shared_dimension
            self.seed = seed
            self.implementation_profile = IMPLEMENTATION_PROFILE
            self.source_projection = torch.nn.Linear(input_dimension, shared_dimension, device="cpu", dtype=torch.float32)
            self.formal_projection = torch.nn.Linear(formal_dimension, shared_dimension, device="cpu", dtype=torch.float32)

        def _project(self, inputs, head, width):
            _require(isinstance(inputs, torch.Tensor) and inputs.device.type == "cpu"
                     and inputs.dtype == torch.float32 and inputs.ndim == 2
                     and 1 <= inputs.shape[0] <= MAX_BATCH_SIZE and inputs.shape[1] == width
                     and bool(torch.isfinite(inputs).all()), "bounded finite CPU float32 input required")
            output = head(inputs)
            _require(bool(torch.isfinite(output).all()), "nonfinite projection output")
            norms = torch.linalg.vector_norm(output, dim=1, keepdim=True)
            _require(bool(torch.isfinite(norms).all()) and bool((norms > 1e-12).all()),
                     "zero or nonfinite projection norm cannot produce a retrieval vector")
            return output / norms

        def source(self, inputs):
            return self._project(inputs, self.source_projection, input_dimension)

        def formal(self, inputs):
            return self._project(inputs, self.formal_projection, formal_dimension)

    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        return ProjectionHeads()


def multi_positive_contrastive_loss(source_embeddings, formal_embeddings, target_ids,
                                    temperature=0.07, hard_negative_weights=None):
    """Symmetric log positive mass; exact duplicate target IDs are positives.

    Optional NxN weights multiply only nonpositive denominator contributions.
    They must be finite and at least one on negatives; entries on positives are
    ignored. Returned gradients reach both supplied representations.
    """
    torch = _torch()
    _require(type(temperature) in (int, float) and math.isfinite(temperature) and temperature > 0,
             "finite positive temperature required")
    _require(isinstance(source_embeddings, torch.Tensor) and isinstance(formal_embeddings, torch.Tensor)
             and source_embeddings.device.type == formal_embeddings.device.type == "cpu"
             and source_embeddings.dtype == formal_embeddings.dtype
             and source_embeddings.dtype in (torch.float32, torch.float64)
             and source_embeddings.ndim == formal_embeddings.ndim == 2
             and source_embeddings.shape == formal_embeddings.shape
             and 1 <= source_embeddings.shape[0] <= MAX_BATCH_SIZE and source_embeddings.shape[1] > 0
             and bool(torch.isfinite(source_embeddings).all()) and bool(torch.isfinite(formal_embeddings).all()),
             "matching finite CPU floating-point representation batches required")
    count = source_embeddings.shape[0]
    _require(type(target_ids) in (list, tuple) and len(target_ids) == count
             and all(type(value) is str and 0 < len(value) <= 512 for value in target_ids),
             "one exact target identity per paired row required")
    positives = torch.tensor([[left == right for right in target_ids] for left in target_ids], dtype=torch.bool)
    logits = source_embeddings @ formal_embeddings.T / temperature
    _require(bool(torch.isfinite(logits).all()), "nonfinite contrastive logits")
    weighted = logits
    if hard_negative_weights is not None:
        weights = hard_negative_weights
        _require(isinstance(weights, torch.Tensor) and weights.device.type == "cpu"
                 and weights.dtype == logits.dtype and weights.shape == logits.shape,
                 "matching CPU floating-point NxN hard-negative weights required")
        negative_values = weights[~positives]
        _require(bool(torch.isfinite(negative_values).all()) and bool((negative_values >= 1).all()),
                 "negative weights must be finite and at least one")
        safe_weights = torch.where(positives, torch.ones_like(weights), weights)
        weighted = logits + safe_weights.log()
    positive_logits = logits.masked_fill(~positives, -torch.inf)
    rows = torch.logsumexp(weighted, dim=1) - torch.logsumexp(positive_logits, dim=1)
    columns = torch.logsumexp(weighted, dim=0) - torch.logsumexp(positive_logits, dim=0)
    loss = (rows.mean() + columns.mean()) / 2
    _require(bool(torch.isfinite(loss)), "nonfinite contrastive loss")
    return loss


def _implementation_digest():
    raw = Path(__file__).read_bytes()
    _require(len(raw) <= MAX_CODEC_BYTES, "implementation source exceeds bound")
    return hashlib.sha256(raw).hexdigest()


def _train_bindings(bindings):
    _require(type(bindings) is list and 1 <= len(bindings) <= 16, "explicit training bindings required")
    for binding in bindings:
        _require(type(binding) is dict and set(binding) == {"path", "sha256", "split"}, "closed training file binding required")
        _require(type(binding["path"]) is str and 0 < len(binding["path"]) <= 4096
                 and type(binding["sha256"]) is str and _SHA.fullmatch(binding["sha256"])
                 and binding["split"] == "train", "only pinned training split bindings are supported")


def _state_shapes(input_dimension, formal_dimension, shared_dimension):
    return {"source_projection.weight": (shared_dimension, input_dimension),
            "source_projection.bias": (shared_dimension,),
            "formal_projection.weight": (shared_dimension, formal_dimension),
            "formal_projection.bias": (shared_dimension,)}


def _validate_tensor(value, shape):
    if shape:
        _require(type(value) is list and len(value) == shape[0], "projection tensor shape differs")
        for item in value:
            _validate_tensor(item, shape[1:])
    else:
        _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= _FLOAT32_MAX,
                 "finite float32-range projection tensor scalar required; bool is forbidden")


def _validate_checkpoint(checkpoint, source_space_id):
    fields = {"schema", "implementation_profile", "implementation_source_sha256", "dependency_binding_scope",
              "source_space_id", "formal_space_id", "input_dimension", "formal_dimension", "shared_dimension",
              "seed", "generation_id", "codec", "train_bindings", "training_recipe", "model_state",
              "state_dtype", "state_device", "output_kind", "development_fit", "qualified",
              "proof_authority", "optimizer_resume_supported", "content_sha256"}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed projection checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA
             and checkpoint["implementation_profile"] == IMPLEMENTATION_PROFILE
             and checkpoint["implementation_source_sha256"] == _implementation_digest()
             and checkpoint["dependency_binding_scope"] == "projection_module_only",
             "checkpoint implementation identity differs")
    _require(source_space_id == SOURCE_SPACE_ID and checkpoint["source_space_id"] == SOURCE_SPACE_ID,
             "source vector-space identity differs")
    _dimensions(checkpoint["input_dimension"], checkpoint["formal_dimension"], checkpoint["shared_dimension"], checkpoint["seed"])
    _validate_codec(checkpoint["codec"])
    _require(checkpoint["formal_dimension"] == checkpoint["codec"]["feature_dimension"]
             and checkpoint["formal_space_id"] == checkpoint["codec"]["feature_space_id"],
             "formal feature-space identity differs")
    _require(type(checkpoint["generation_id"]) is str
             and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", checkpoint["generation_id"]),
             "explicit bounded adapter generation required")
    _train_bindings(checkpoint["train_bindings"])
    recipe = checkpoint["training_recipe"]
    _require(recipe is None or type(recipe) is dict and len(_raw(recipe)) <= 16384,
             "bounded declared training recipe required")
    _require(checkpoint["state_dtype"] == "float32" and checkpoint["state_device"] == "cpu"
             and checkpoint["output_kind"] == "l2_normalized_retrieval_vectors"
             and all(checkpoint[name] is False for name in
                     ("development_fit", "qualified", "proof_authority", "optimizer_resume_supported")),
             "checkpoint numerical or authority scope differs")
    shapes = _state_shapes(checkpoint["input_dimension"], checkpoint["formal_dimension"], checkpoint["shared_dimension"])
    _require(type(checkpoint["model_state"]) is dict and set(checkpoint["model_state"]) == set(shapes),
             "complete exact projection tensor inventory required")
    for name, shape in shapes.items():
        _validate_tensor(checkpoint["model_state"][name], shape)
    body = {name: value for name, value in checkpoint.items() if name != "content_sha256"}
    _require(checkpoint["content_sha256"] == _digest(body), "checkpoint content digest differs")
    _require(len(_raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, "checkpoint exceeds byte bound")


def create_projection_checkpoint(model, codec, *, source_space_id=SOURCE_SPACE_ID,
                                 train_bindings, generation_id, training_recipe=None) -> dict:
    """Describe exact current tensors; optimizer state and qualification are absent."""
    _validate_codec(codec)
    _require(source_space_id == SOURCE_SPACE_ID, "source vector-space identity differs")
    _train_bindings(train_bindings)
    torch = _torch()
    _require(isinstance(model, torch.nn.Module) and getattr(model, "implementation_profile", None) == IMPLEMENTATION_PROFILE,
             "projection model implementation required")
    _dimensions(model.input_dimension, model.formal_dimension, model.shared_dimension, model.seed)
    state = model.state_dict()
    _require(set(state) == set(_state_shapes(model.input_dimension, model.formal_dimension, model.shared_dimension)),
             "complete exact projection tensor inventory required")
    _require(all(tensor.device.type == "cpu" and tensor.dtype == torch.float32
                 and bool(torch.isfinite(tensor).all()) for tensor in state.values()),
             "finite CPU float32 projection parameters required")
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "implementation_profile": IMPLEMENTATION_PROFILE,
        "implementation_source_sha256": _implementation_digest(), "dependency_binding_scope": "projection_module_only",
        "source_space_id": source_space_id, "formal_space_id": codec["feature_space_id"],
        "input_dimension": model.input_dimension, "formal_dimension": model.formal_dimension,
        "shared_dimension": model.shared_dimension, "seed": model.seed, "generation_id": generation_id,
        "codec": json.loads(_raw(codec)), "train_bindings": json.loads(_raw(train_bindings)),
        "training_recipe": json.loads(_raw(training_recipe)),
        "model_state": {name: tensor.detach().tolist() for name, tensor in state.items()},
        "state_dtype": "float32", "state_device": "cpu", "output_kind": "l2_normalized_retrieval_vectors",
        "development_fit": False, "qualified": False, "proof_authority": False, "optimizer_resume_supported": False}
    checkpoint["content_sha256"] = _digest(checkpoint)
    _validate_checkpoint(checkpoint, source_space_id)
    return checkpoint


def _open(path, flags):
    path = Path(os.path.abspath(path))
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = descriptor
        return os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    finally:
        os.close(parent)


def _read_checkpoint(path):
    descriptor = _open(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_CHECKPOINT_BYTES, "bounded regular checkpoint file required")
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
        after = os.fstat(stream.fileno())
        _require(len(raw) == info.st_size and len(raw) <= MAX_CHECKPOINT_BYTES
                 and (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
                 == (after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size), "checkpoint changed during reading")
    return raw


def save_projection_checkpoint(checkpoint, path) -> dict:
    """Write a new exclusive ordinary-JSON file; never overwrite donor assets."""
    _validate_checkpoint(checkpoint, SOURCE_SPACE_ID)
    raw = _raw(checkpoint)
    descriptor = _open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    _require(_read_checkpoint(path) == raw, "saved checkpoint bytes differ")
    return {"path": str(Path(path).absolute()), "sha256": hashlib.sha256(raw).hexdigest(),
            "content_sha256": checkpoint["content_sha256"], "bytes": len(raw)}


def load_projection_checkpoint(path, *, expected_sha256, expected_source_space_id=SOURCE_SPACE_ID) -> dict:
    """Authenticate bounded JSON before constructing fresh CPU projection heads."""
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "external checkpoint SHA256 required")
    _require(expected_source_space_id == SOURCE_SPACE_ID, "source vector-space identity differs")
    raw = _read_checkpoint(path)
    digest = hashlib.sha256(raw).hexdigest()
    _require(digest == expected_sha256, "checkpoint file SHA256 differs")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite checkpoint JSON number: " + value)

    try:
        checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("strict checkpoint JSON required") from error
    _validate_checkpoint(checkpoint, expected_source_space_id)
    model = create_projection_heads(checkpoint["input_dimension"], checkpoint["formal_dimension"],
                                    checkpoint["shared_dimension"], checkpoint["seed"])
    torch = _torch()
    model.load_state_dict({name: torch.tensor(value, dtype=torch.float32, device="cpu")
                           for name, value in checkpoint["model_state"].items()}, strict=True)
    model.eval()
    return {"model": model, "codec": checkpoint["codec"], "checkpoint": checkpoint, "sha256": digest}
