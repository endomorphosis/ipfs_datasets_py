"""Private 768-input student initialized from a pinned learned 384D decoder.

The first student keeps the donor's complete numerical decoder, vocabulary and
normalization. Only its 768-to-384 input boundary is new. This factorization is
explicit: the 384D intermediate is an adapted latent, never a GTE-small vector.
Import, inspection and serialization use only the standard library. No encoder
assets, optimization, source-fidelity qualification or distillation are implied.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

SCHEMA = "gte-decoder-warm-start/v1"
ARCHITECTURE = "factorized-768-to-384-inherited-gru/v1"
DIMENSION = 768
INTERMEDIATE_DIMENSION = 384
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _helper(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_gte_warm_start_" + name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load warm-start helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TEACHER = _helper("gte_bridge_teacher")
_BRIDGE = _helper("gte_affine_bridge")
_IO = _TEACHER._IO
PROFILE_ID = _BRIDGE.STUDENT_REPRESENTATION_ID
FLAGS = {"decoder_parameters_random": False, "boundary_alignment_required": True,
         "encoder_numerics_verified": False, "source_fidelity_qualified": False,
         "proof_authority": False, "training_executed": False,
         "distillation_executed": False, "optimizer_resume_supported": False,
         "source_text_is_neural_input": False}
_FIELDS = {"schema", "architecture", "domain_id", "dimension", "intermediate_dimension",
           "runtime_id", "representation_id", "source_profile_id", "seed", "codec",
           "codec_sha256", "config", "donor", "donor_source_pins", "input_transform",
           "input_transform_sha256", "boundary_initialization", "freeze_inherited",
           "optimizer", "implementation", "model_state", "weights_sha256", "tensor_inventory", *FLAGS}
_DONOR_FIELDS = {"runtime_id", "dimension", "checkpoint_sha256", "weights_sha256", "codec_sha256",
                 "input_transform_sha256", "implementation_sha256", "source_representation_id"}
_NEW = {"input_adapter.weight", "input_adapter.bias"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("bounded finite JSON required") from error


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, label + " requires lowercase SHA256")
    return value


def _seed(value):
    _require(type(value) is int and 0 <= value < 2**31, "bounded integer seed required")
    return value


def _implementation():
    names = ("gte_decoder_warm_start", "gte_bridge_teacher", "gte_affine_bridge",
             "gte_worker_contract", "gte_migration_inventory")
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _config(value):
    _fields(value, {"hidden_size", "token_embedding_dim", "projection_width", "max_target_tokens"},
            "warm-start configuration")
    for name, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64),
                            ("projection_width", 1, 64), ("max_target_tokens", 4, 1024)):
        _require(type(value[name]) is int and low <= value[name] <= high, "invalid " + name)
    return deepcopy(value)


def _shapes(config, codec):
    return {**_TEACHER._INVENTORY._sequence_shapes({"config": config, "codec": codec}, 384),
            "input_adapter.weight": (384, 768), "input_adapter.bias": (384,)}


def _identity(checkpoint):
    fields = {name: checkpoint[name] for name in ("architecture", "domain_id", "source_profile_id",
             "codec_sha256", "input_transform_sha256", "weights_sha256")}
    fields["donor_checkpoint_sha256"] = checkpoint["donor"]["checkpoint_sha256"]
    return checkpoint["domain_id"] + ":factorized_768_decoder:" + digest(fields)


def _inventory(state, shapes, *, donor_state=None):
    result = []
    for name in sorted(shapes):
        inherited = name not in _NEW
        result.append({"name": name, "shape": list(shapes[name]), "sha256": digest(state[name]),
                       "origin": "copied_384_decoder" if inherited else "new_768_input_boundary",
                       "donor_tensor_sha256": digest(donor_state[name]) if inherited and donor_state is not None
                       else digest(state[name]) if inherited else None})
    return result


def inspect_warm_start(checkpoint, *, expected_teacher_sha256, expected_domain_id,
                       expected_codec_sha256):
    """Validate an externally authenticated initialization payload without Torch.

    Expected donor and codec pins must come from the caller's inspected donor.
    When loading a file, authenticate its complete bytes with read_pinned_json
    first. Recorded tensor digests are initialization evidence, not qualification.
    """
    _fields(checkpoint, _FIELDS, "warm-start checkpoint")
    _require(len(_raw(checkpoint)) <= MAX_CHECKPOINT_BYTES, "warm-start checkpoint exceeds byte bound")
    _hash(expected_teacher_sha256, "expected donor checkpoint")
    _hash(expected_codec_sha256, "expected codec")
    _require(type(expected_domain_id) is str and expected_domain_id in DOMAINS, "supported domain required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["architecture"] == ARCHITECTURE,
             "warm-start schema or architecture differs")
    _require(checkpoint["domain_id"] == expected_domain_id
             and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION
             and type(checkpoint["intermediate_dimension"]) is int
             and checkpoint["intermediate_dimension"] == INTERMEDIATE_DIMENSION, "warm-start geometry differs")
    _require(checkpoint["runtime_id"] == expected_domain_id + ":warm_start_decoder_768_v1"
             and checkpoint["source_profile_id"] == PROFILE_ID, "warm-start runtime or input profile differs")
    _require(all(type(checkpoint[name]) is bool and checkpoint[name] == value for name, value in FLAGS.items()),
             "warm-start declarations cannot grant alignment, qualification or resume")
    _seed(checkpoint["seed"])
    _require(type(checkpoint["freeze_inherited"]) is bool, "explicit inherited freeze mode required")
    _fields(checkpoint["optimizer"], {"mode", "state", "resume"}, "fresh optimizer declaration")
    _require(checkpoint["optimizer"]["mode"] == "fresh" and checkpoint["optimizer"]["state"] is None
             and checkpoint["optimizer"]["resume"] is False,
             "warm-start requires a fresh optimizer without donor moments")
    _require(checkpoint["implementation"] == _implementation(), "warm-start implementation pins differ")
    config = _config(checkpoint["config"])
    codec = _TEACHER._codec({"codec": checkpoint["codec"]})
    _require(_hash(checkpoint["codec_sha256"], "codec") == digest(codec) == expected_codec_sha256,
             "exact vocabulary identity differs")
    transform = _BRIDGE.validate_input_transform(checkpoint["input_transform"])
    _require(_hash(checkpoint["input_transform_sha256"], "input transform") == digest(transform),
             "donor input transformation differs")
    donor = checkpoint["donor"]
    _fields(donor, _DONOR_FIELDS, "donor binding")
    _require(donor["runtime_id"] == expected_domain_id + ":source_training_v2"
             and type(donor["dimension"]) is int and donor["dimension"] == 384
             and donor["source_representation_id"] == _TEACHER.SOURCE_REPRESENTATION_ID,
             "donor runtime, geometry or source representation differs")
    for name in ("checkpoint_sha256", "weights_sha256", "codec_sha256", "input_transform_sha256",
                 "implementation_sha256"):
        _hash(donor[name], "donor " + name)
    _require(donor["checkpoint_sha256"] == expected_teacher_sha256
             and donor["codec_sha256"] == expected_codec_sha256
             and donor["input_transform_sha256"] == checkpoint["input_transform_sha256"],
             "external donor bindings differ")
    pins = checkpoint["donor_source_pins"]
    _require(type(pins) is list and len(pins) == 14, "complete listed donor source closure required")
    for pin in pins:
        _fields(pin, {"path", "sha256", "bytes"}, "donor source receipt")
        _require(type(pin["path"]) is str and 0 < len(pin["path"]) <= 4096
                 and type(pin["bytes"]) is int and 0 < pin["bytes"] <= _TEACHER.MAX_SOURCE_BYTES,
                 "bounded donor source receipt required")
        _hash(pin["sha256"], "donor source")
    _require(len({pin["path"] for pin in pins}) == len(pins)
             and pins == sorted(pins, key=lambda value: value["path"]), "donor source receipts must be unique and ordered")
    expected_sources = {*_TEACHER._NATIVE_MODULE_PATHS.values(), *_TEACHER._NUMERICAL_PATHS.values(),
        "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"}
    roots = set()
    seen_sources = set()
    for pin in pins:
        matched = [relative for relative in expected_sources if pin["path"].endswith("/" + relative)]
        _require(Path(pin["path"]).is_absolute() and ".." not in Path(pin["path"]).parts
                 and len(matched) == 1, "donor source closure contains an unknown path")
        relative = matched[0]
        roots.add(pin["path"][:-len(relative)])
        seen_sources.add(relative)
    _require(len(roots) == 1 and seen_sources == expected_sources, "donor source closure differs")
    boundary = checkpoint["boundary_initialization"]
    _fields(boundary, {"mode", "seed", "bridge_checkpoint_sha256", "bridge_weights_sha256",
                       "bridge_adapted_representation_id", "alignment_qualified"}, "boundary initialization")
    _seed(boundary["seed"])
    _require(boundary["alignment_qualified"] is False, "boundary alignment remains unqualified")
    if boundary["mode"] == "seeded_unaligned_affine":
        _require(boundary["seed"] == checkpoint["seed"] and all(boundary[name] is None for name in (
            "bridge_checkpoint_sha256", "bridge_weights_sha256", "bridge_adapted_representation_id")),
            "seeded boundary cannot claim a bridge artifact")
    else:
        _require(boundary["mode"] == "pinned_affine_bridge", "unknown boundary initialization mode")
        _hash(boundary["bridge_checkpoint_sha256"], "bridge checkpoint")
        _hash(boundary["bridge_weights_sha256"], "bridge weights")
        _require(boundary["bridge_adapted_representation_id"] == _BRIDGE.adapted_representation_id(
            weights_sha256=boundary["bridge_weights_sha256"], teacher_checkpoint_sha256=expected_teacher_sha256,
            input_transform_sha256=checkpoint["input_transform_sha256"], student_representation_id=PROFILE_ID,
            source_representation_id=_TEACHER.SOURCE_REPRESENTATION_ID), "adapted bridge representation differs")
    state = checkpoint["model_state"]
    shapes = _shapes(config, codec)
    actual = _TEACHER._INVENTORY._tensors(state, "model_state")
    _TEACHER._INVENTORY._shape_check(actual, shapes, "model_state")
    for values in state.values():
        stack = [values]
        while stack:
            value = stack.pop()
            if type(value) is list:
                stack.extend(value)
            else:
                _require(abs(value) <= 3.4028234663852886e38, "tensor exceeds float32 range")
    _require(_hash(checkpoint["weights_sha256"], "weights") == digest(state), "warm-start weights digest differs")
    inventory = _inventory(state, shapes)
    _require(_raw(checkpoint["tensor_inventory"]) == _raw(inventory), "copied/new tensor inventory differs")
    donor_state = {name: state[name] for name in shapes if name not in _NEW}
    _require(digest(donor_state) == donor["weights_sha256"], "inherited decoder weights differ from donor")
    boundary_state = {name.removeprefix("input_adapter."): state[name] for name in sorted(_NEW)}
    if boundary["mode"] == "pinned_affine_bridge":
        _require(digest(boundary_state) == boundary["bridge_weights_sha256"], "inherited affine boundary differs")
    _require(checkpoint["representation_id"] == _identity(checkpoint), "student representation identity differs")
    copied = sum(math.prod(shapes[name]) for name in shapes if name not in _NEW)
    new = sum(math.prod(shapes[name]) for name in _NEW)
    return {"schema": "gte-decoder-warm-start-inspection/v1", "status": "initialized",
            "runtime_id": checkpoint["runtime_id"], "representation_id": checkpoint["representation_id"],
            "dimension": DIMENSION, "intermediate_dimension": INTERMEDIATE_DIMENSION,
            "copied_tensor_count": len(shapes) - len(_NEW), "new_tensor_count": len(_NEW),
            "copied_parameter_count": copied, "new_boundary_parameter_count": new,
            "codec_sha256": expected_codec_sha256, "teacher_checkpoint_sha256": expected_teacher_sha256,
            "boundary_initialization": deepcopy(boundary), "tensor_inventory": deepcopy(inventory), **FLAGS}


def _torch():
    import torch
    return torch


def _model(config, codec, transform, seed):
    torch = _torch()

    class FactorizedStudent(torch.nn.Module):
        def __init__(self):
            super().__init__()
            hidden, width = config["hidden_size"], config["projection_width"]
            self.input_adapter = torch.nn.Linear(768, 384, device="cpu", dtype=torch.float32)
            self.projection_down = torch.nn.Linear(384, width, device="cpu", dtype=torch.float32)
            self.projection_up = torch.nn.Linear(width, 384, device="cpu", dtype=torch.float32)
            self.condition = torch.nn.Linear(384, hidden, device="cpu", dtype=torch.float32)
            self.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]),
                config["token_embedding_dim"], padding_idx=0, device="cpu", dtype=torch.float32)
            self.decoder = torch.nn.GRU(config["token_embedding_dim"], hidden, batch_first=True,
                                        device="cpu", dtype=torch.float32)
            self.output = torch.nn.Linear(hidden, len(codec["target_vocabulary"]), device="cpu", dtype=torch.float32)
            self.register_buffer("input_mean", torch.tensor(transform["mean"], dtype=torch.float32), persistent=False)
            self.input_scale = transform["scale"]
            self.max_target_tokens = config["max_target_tokens"]

        def _input(self, vectors):
            _require(isinstance(vectors, torch.Tensor) and vectors.device.type == "cpu"
                     and vectors.dtype == torch.float32 and vectors.ndim == 2
                     and 1 <= vectors.shape[0] <= 4096 and vectors.shape[1] == 768
                     and bool(torch.isfinite(vectors).all()), "bounded finite CPU float32 768D inputs required")

        def project(self, adapted384):
            return adapted384 + self.projection_up(torch.tanh(self.projection_down(adapted384)))

        def start(self, projected384):
            return torch.tanh(self.condition(projected384)).unsqueeze(0)

        def project_input(self, vectors768):
            """Return the private adapted 384D intermediate, without identity claims."""
            self._input(vectors768)
            adapted = (self.input_adapter(vectors768) - self.input_mean) / self.input_scale
            projected = self.project(adapted)
            _require(bool(torch.isfinite(projected).all()), "nonfinite adapted decoder intermediate")
            return projected

        def condition_from_input(self, vectors768):
            """Return [batch, hidden_size] for separately typed additional heads."""
            return self.start(self.project_input(vectors768)).squeeze(0)

        def decode_from_condition(self, condition, tokens):
            _require(isinstance(condition, torch.Tensor) and condition.device.type == "cpu"
                     and condition.dtype == torch.float32 and condition.ndim == 2
                     and condition.shape[1] == self.decoder.hidden_size
                     and 1 <= condition.shape[0] <= 4096 and bool(torch.isfinite(condition).all()),
                     "bounded finite CPU decoder condition required")
            _require(isinstance(tokens, torch.Tensor) and tokens.ndim == 2
                     and tokens.shape[0] == condition.shape[0], "decoder prefix batch differs")
            return self.next_logits(tokens, condition.unsqueeze(0))[0]

        def next_logits(self, tokens, hidden):
            _require(isinstance(tokens, torch.Tensor) and tokens.device.type == "cpu"
                     and tokens.dtype == torch.int64 and tokens.ndim == 2
                     and 1 <= tokens.shape[1] <= self.max_target_tokens
                     and bool(((tokens >= 0) & (tokens < self.target_embedding.num_embeddings)).all()),
                     "bounded CPU int64 prefixes within exact donor vocabulary required")
            outputs, hidden = self.decoder(self.target_embedding(tokens), hidden)
            logits = self.output(outputs)
            _require(bool(torch.isfinite(logits).all()), "nonfinite decoder logits")
            return logits, hidden

        def forward(self, vectors768, tokens):
            projected = self.project_input(vectors768)
            _require(isinstance(tokens, torch.Tensor) and tokens.ndim == 2
                     and tokens.shape[0] == vectors768.shape[0], "decoder prefix batch differs")
            return projected, self.next_logits(tokens, self.start(projected))[0]

    with torch.random.fork_rng(devices=[]):
        # Every constructor draw is replaced by exact donor/boundary tensors.
        # Avoid manual_seed here: it also changes CUDA seed state in a CPU job.
        model = FactorizedStudent()
    return model


def _load_state(model, state):
    torch = _torch()
    templates = model.state_dict()
    _require(set(state) == set(templates), "student tensor names differ")
    tensors = {name: torch.tensor(value, dtype=torch.float32, device="cpu") for name, value in state.items()}
    _require(all(tuple(tensors[name].shape) == tuple(template.shape) and bool(torch.isfinite(tensors[name]).all())
                 for name, template in templates.items()), "student tensor shape or float32 range differs")
    _require(digest({name: tensor.tolist() for name, tensor in tensors.items()}) == digest(state),
             "student state is not exact float32 serialization")
    model.load_state_dict(tensors, strict=True)


def _freeze(model, freeze_inherited):
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(not freeze_inherited or name in _NEW)
    return model.eval()


def create_warm_start(teacher_path, *, expected_teacher_sha256, domain_id="legal_ir", seed=1729,
                      repository_root=None, freeze_inherited=False, bridge_checkpoint_path=None,
                      expected_bridge_sha256=None):
    """Clone all learned donor tensors into a separately owned 768-input student.

    A bridge artifact may supply the boundary. Without one, only the boundary
    uses private seeded initialization. The decoder itself has no random tensor.
    Existing donors, optimizers and process RNG/thread settings remain untouched.
    """
    seed = _seed(seed)
    _require(type(freeze_inherited) is bool, "explicit inherited freeze mode required")
    _require((bridge_checkpoint_path is None) == (expected_bridge_sha256 is None),
             "bridge path and external digest must be supplied together")
    binding = _TEACHER.inspect_teacher(teacher_path, expected_sha256=expected_teacher_sha256,
                                       domain_id=domain_id, repository_root=repository_root)
    donor, _ = _IO.read_pinned_json(teacher_path, expected_sha256=expected_teacher_sha256,
                                    max_bytes=_TEACHER.MAX_CHECKPOINT_BYTES)
    config = {name: donor["config"][name] for name in ("hidden_size", "token_embedding_dim", "projection_width",
                                                     "max_target_tokens")}
    model = _model(config, donor["codec"], donor["input_transform"], seed)
    if bridge_checkpoint_path is None:
        adapter = _BRIDGE.create_affine_bridge(seed)
        boundary = {"mode": "seeded_unaligned_affine", "seed": seed, "bridge_checkpoint_sha256": None,
                    "bridge_weights_sha256": None, "bridge_adapted_representation_id": None,
                    "alignment_qualified": False}
    else:
        bridge, _ = _IO.read_pinned_json(bridge_checkpoint_path, expected_sha256=expected_bridge_sha256,
                                       max_bytes=_BRIDGE.MAX_CHECKPOINT_BYTES)
        adapter = _BRIDGE.load_bridge_checkpoint(bridge, expected_domain_id=domain_id,
            expected_teacher_runtime_id=binding["teacher_runtime_id"],
            expected_source_representation_id=binding["source_representation_id"],
            expected_student_representation_id=PROFILE_ID,
            expected_teacher_checkpoint_sha256=expected_teacher_sha256, input_transform=donor["input_transform"])
        boundary = {"mode": "pinned_affine_bridge", "seed": bridge["seed"],
                    "bridge_checkpoint_sha256": expected_bridge_sha256, "bridge_weights_sha256": bridge["weights_sha256"],
                    "bridge_adapted_representation_id": bridge["adapted_representation_id"], "alignment_qualified": False}
    state = {**deepcopy(donor["model_state"]), **{"input_adapter." + name: value.detach().tolist()
              for name, value in adapter.state_dict().items()}}
    _load_state(model, state)
    _freeze(model, freeze_inherited)
    checkpoint = {"schema": SCHEMA, "architecture": ARCHITECTURE, "domain_id": domain_id,
        "dimension": DIMENSION, "intermediate_dimension": INTERMEDIATE_DIMENSION,
        "runtime_id": domain_id + ":warm_start_decoder_768_v1", "source_profile_id": PROFILE_ID,
        "seed": seed, "codec": deepcopy(donor["codec"]), "codec_sha256": binding["codec_sha256"], "config": config,
        "donor": {"runtime_id": binding["teacher_runtime_id"], "dimension": 384,
            "checkpoint_sha256": expected_teacher_sha256, "weights_sha256": binding["weights_sha256"],
            "codec_sha256": binding["codec_sha256"], "input_transform_sha256": binding["input_transform_sha256"],
            "implementation_sha256": binding["implementation_sha256"],
            "source_representation_id": binding["source_representation_id"]},
        "donor_source_pins": deepcopy(binding["sources"]), "input_transform": deepcopy(donor["input_transform"]),
        "input_transform_sha256": binding["input_transform_sha256"], "boundary_initialization": boundary,
        "freeze_inherited": freeze_inherited, "optimizer": {"mode": "fresh", "state": None, "resume": False},
        "implementation": _implementation(), "model_state": state, "weights_sha256": digest(state),
        "tensor_inventory": _inventory(state, _shapes(config, donor["codec"]), donor_state=donor["model_state"]), **FLAGS}
    checkpoint["representation_id"] = _identity(checkpoint)
    inspect_warm_start(checkpoint, expected_teacher_sha256=expected_teacher_sha256,
                       expected_domain_id=domain_id, expected_codec_sha256=binding["codec_sha256"])
    _require(_TEACHER.inspect_teacher(teacher_path, expected_sha256=expected_teacher_sha256,
             domain_id=domain_id, repository_root=repository_root) == binding,
             "donor binding changed while creating the student")
    if bridge_checkpoint_path is not None:
        _IO.read_pinned_json(bridge_checkpoint_path, expected_sha256=expected_bridge_sha256,
                             max_bytes=_BRIDGE.MAX_CHECKPOINT_BYTES)
    return model, checkpoint


def load_warm_start(checkpoint, *, expected_teacher_sha256, expected_domain_id, expected_codec_sha256):
    """Load an externally authenticated warm-start payload into private CPU state."""
    inspect_warm_start(checkpoint, expected_teacher_sha256=expected_teacher_sha256,
                       expected_domain_id=expected_domain_id, expected_codec_sha256=expected_codec_sha256)
    model = _model(checkpoint["config"], checkpoint["codec"], checkpoint["input_transform"], checkpoint["seed"])
    _load_state(model, checkpoint["model_state"])
    return _freeze(model, checkpoint["freeze_inherited"])


def create_fresh_optimizer(model, *, learning_rate=.003):
    """Start private Adam state; no 8D/384D optimizer moments are transferred."""
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate)
             and 0 < learning_rate <= .1, "bounded positive learning rate required")
    torch = _torch()
    _require(isinstance(model, torch.nn.Module), "student module required")
    parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    _require(bool(parameters) and all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
             for parameter in parameters), "trainable CPU float32 student parameters required")
    return torch.optim.Adam(parameters, lr=learning_rate, foreach=False)


__all__ = ["SCHEMA", "ARCHITECTURE", "PROFILE_ID", "create_warm_start", "inspect_warm_start",
           "load_warm_start", "create_fresh_optimizer", "digest"]
