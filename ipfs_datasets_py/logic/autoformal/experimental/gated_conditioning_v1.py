"""Development-only compact384 per-step conditioning; never an optimizer owner.

Migration accepts only the retained a98 trained checkpoint or its exact c7d
initial checkpoint.  Historical Adam state is retained inside the parent as
provenance and is never constructed/restored.  The new architecture preserves
the body and computes e_t + gate * source_to_embedding(projected_source), with
a privately seeded nonzero projection and an initially zero scalar gate.

Preparation/inspection is separate from full-prefix forwards.  The caller owns
original resource admission, source custody, evaluation, and all experiment
instrumentation.  No encoder, legal accuracy, or production readiness follows.
"""
from copy import deepcopy
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import struct

from . import _legacy_source_bridge_v1 as _bridge

_PORTED_SOURCE_SHA256 = _bridge.source_reference('gated_conditioning')["sha256"]

SCHEMA = "legal-compact-gated-conditioning-checkpoint/v1"
PROFILE = "authored-compact384-per-step-gated-conditioning-development/v1"
ARCHITECTURE = "joint-gru-h0-plus-gated-projected-source-embedding/v1"
TRAINED_SHA = "a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b"
INITIAL_SHA = "c7d56d501e0eeca53202b69f8ea104b9e33d3227086971afbd7534ccb6da8f44"
PROJECTION_SEED = 2729
MAX_BYTES = 64 * 1024**2
CONFIG = {"hidden_size": 8, "projection_width": 4, "seed": 1729, "token_embedding_dim": 8}
AUTHORITY = {name: False for name in (
    "production_ready", "source_encoder_authenticated", "legal_accuracy",
    "heldout_accuracy", "graph_admission", "Lean_admission", "native_admission")}
SPECS = (
    ("head", "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("trainer", "logic/formalization/autoencoder/legal_compact_content_training_v2.py",
     "3ff34b8094a8bb19315741a03873c95f7d809654b35717fd4cee97e074fd2b59"),
    ("runtime", "logic/formalization/autoencoder/legal_compact_content_trained_runtime_v2.py",
     "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"),
    ("numerical", "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
)
BODY_SHAPES = {
    "projection_down.weight": (4, 384), "projection_down.bias": (4,),
    "projection_up.weight": (384, 4), "projection_up.bias": (384,),
    "condition.weight": (8, 384), "condition.bias": (8,),
    "target_embedding.weight": (537, 8), "decoder.weight_ih_l0": (24, 8),
    "decoder.weight_hh_l0": (24, 8), "decoder.bias_ih_l0": (24,),
    "decoder.bias_hh_l0": (24,), "output.weight": (537, 8), "output.bias": (537,),
}
SHAPES = {"gate": (), **{"body." + name: shape for name, shape in BODY_SHAPES.items()},
          "source_to_embedding.weight": (8, 384)}
FIELDS = {"schema", "profile", "architecture", "input_dimension", "vocabulary_size",
          "max_total_ids", "config", "codec", "codec_sha256", "parent_checkpoint",
          "parent_checkpoint_sha256", "parent_kind", "parent_weights_sha256",
          "historical_progress", "model_state", "weights_sha256", "parameter_order",
          "initialization", "implementation", "optimizer_state_included",
          "optimizer_state_scope", "parent_optimizer_state_retained_as_provenance",
          "new_optimizer_updates", "training_mask", "evaluation_gold_mask", "authority"}


class GatedConditioningError(ValueError):
    """A bounded development-profile or exact parent contract was violated."""


def _need(ok, message):
    if not ok:
        raise GatedConditioningError(message)


def _copy(value):
    """Copy only bounded ordinary JSON; reject cycles/custom scalar methods."""
    active, remaining = set(), [MAX_BYTES, 3000000]
    def visit(item, depth):
        remaining[1] -= 1
        _need(remaining[1] >= 0 and depth <= 48, "whole JSON item/depth bound exceeded")
        if type(item) in (dict, list):
            _need(id(item) not in active and len(item) <= remaining[1], "cyclic/oversized JSON refused")
            active.add(id(item))
            remaining[0] -= 2 + len(item)
            try:
                if type(item) is dict:
                    _need(all(type(k) is str for k in item), "plain string keys required")
                    result = {visit(k, depth+1): visit(v, depth+1) for k, v in item.items()}
                else:
                    result = [visit(v, depth+1) for v in item]
            finally:
                active.remove(id(item))
        elif type(item) is str:
            _need(len(item) <= MAX_BYTES and all(0 < ord(c) < 0xD800 or 0xDFFF < ord(c) <= 0x10FFFF for c in item),
                  "ordinary scalar UTF8 strings required")
            remaining[0] -= len(item.encode("utf-8")) + 2
            result = item
        elif type(item) is float:
            _need(math.isfinite(item), "finite JSON numbers required")
            remaining[0] -= len(repr(item)); result = item
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded integer required")
            remaining[0] -= len(str(item)); result = item
        elif item is None or type(item) is bool:
            remaining[0] -= 5; result = item
        else:
            raise GatedConditioningError("ordinary JSON containers/primitives required")
        _need(remaining[0] >= 0, "whole JSON byte bound exceeded")
        return result
    return visit(value, 0)


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_BYTES, "complete checkpoint exceeds byte bound")
    return raw


def checkpoint_sha256(value):
    return hashlib.sha256(_wire(_copy(value))).hexdigest()


def _sources():
    _bridge.require_source("gated_conditioning", _PORTED_SOURCE_SHA256)
    # The same source may be reviewed in an artifact stage or later installed
    # beneath the canonical package. No artifact-stage location is a contract.
    root = None
    for ancestor in Path(__file__).absolute().parents:
        if ancestor.name == "ipfs_datasets_py":
            root = ancestor
            break
        candidate = ancestor / "external/ipfs_datasets/ipfs_datasets_py"
        if candidate.is_dir():
            root = candidate
            break
    _need(root is not None, "canonical package root not found")
    result = []
    for key, relative, expected in SPECS:
        path = root / relative
        _need(path.resolve(strict=True) == path and path.is_file(), "exact canonical owner path required")
        raw = path.read_bytes()
        _need(len(raw) <= 1024**2 and hashlib.sha256(raw).hexdigest() == expected,
              "canonical source pin differs: " + key)
        result.append({"owner": key, "path": str(path), "bytes": len(raw), "sha256": expected})
    return result


def _owners(*, numerical=False):
    before = _sources()
    result = {}
    for entry in before:
        key = entry["owner"]
        if key == "numerical" and not numerical:
            continue
        relative = next(relative for k, relative, _ in SPECS if k == key)
        module = importlib.import_module("ipfs_datasets_py." + relative[:-3].replace("/", "."))
        _need(Path(module.__file__).absolute() == Path(entry["path"]), "canonical import origin differs")
        result[key] = module
    _need(_sources() == before, "source changed during owner loading")
    return result


def _parent(value):
    parent = _copy(value)
    identity = checkpoint_sha256(parent)
    _need(identity in (TRAINED_SHA, INITIAL_SHA), "only exact retained a98 or nested c7d parent accepted")
    loaded = _owners()
    if identity == TRAINED_SHA:
        parent = loaded["runtime"].inspect_compact_content_trained_checkpoint_v2(
            parent, expected_checkpoint_sha256=TRAINED_SHA)
        kind, progress = "current_trained_v2", deepcopy(parent["progress"])
    else:
        parent = loaded["head"]._checkpoint(parent, INITIAL_SHA)
        kind, progress = "exact_retained_initial_v1", {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0}
    _need(parent["config"] == CONFIG and len(parent["codec"]["vocabulary"]) == 537,
          "exact retained compact384/8/4/537 geometry required")
    return parent, identity, kind, progress


def _tensor_shape(value, shape):
    if shape:
        _need(type(value) is list and len(value) == shape[0], "exact complete tensor shape required")
        for child in value:
            _tensor_shape(child, shape[1:])
    else:
        _need(type(value) is float and math.isfinite(value), "finite float32 export required")
        try:
            rounded = struct.unpack("!f", struct.pack("!f", value))[0]
        except (OverflowError, struct.error) as error:
            raise GatedConditioningError("float32 tensor overflow") from error
        _need(rounded.hex() == value.hex(), "tensor scalar must be exact float32 export")


def _validate(checkpoint):
    value = _copy(checkpoint)
    _need(type(value) is dict and set(value) == FIELDS, "closed gated checkpoint fields required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["architecture"] == ARCHITECTURE
          and type(value["input_dimension"]) is int and value["input_dimension"] == 384
          and type(value["vocabulary_size"]) is int and value["vocabulary_size"] == 537
          and type(value["max_total_ids"]) is int and value["max_total_ids"] == 512
          and value["config"] == CONFIG, "exact development384 profile required; other widths pending")
    parent, identity, kind, progress = _parent(value["parent_checkpoint"])
    _need(value["parent_checkpoint_sha256"] == identity and value["parent_kind"] == kind
          and value["parent_weights_sha256"] == parent["weights_sha256"]
          and value["historical_progress"] == progress and value["codec"] == parent["codec"]
          and value["codec_sha256"] == parent["codec_sha256"], "parent/codec/history lineage differs")
    state = value["model_state"]
    _need(type(state) is dict and set(state) == set(SHAPES) and value["parameter_order"] == list(SHAPES),
          "exact15-tensor state/order required")
    for name, shape in SHAPES.items():
        _tensor_shape(state[name], shape)
    _need(state["gate"].hex() == 0.0.hex(), "migration checkpoint gate must be positive zero")
    _need(any(number != 0.0 for row in state["source_to_embedding.weight"] for number in row),
          "nonzero projection required; gate and projection cannot both vanish")
    _need(all(state["body." + name] == parent["model_state"][name] for name in BODY_SHAPES),
          "legacy tensor mapping must remain exact")
    _need(value["weights_sha256"] == checkpoint_sha256(state), "current weights digest differs")
    expected_initialization = {"projection_seed": PROJECTION_SEED, "projection": "Linear384to8_no_bias_default_seeded_uniform",
        "gate_initial_value": 0.0, "ambient_CPU_RNG_preserved": True,
        "projection_weights_sha256": checkpoint_sha256(state["source_to_embedding.weight"]),
        "new_parameter_count": 3073, "legacy_parameter_mapping": {name: "body." + name for name in BODY_SHAPES},
        "seed_replay_verified_by_pure_inspection": False}
    _need(value["initialization"] == expected_initialization and value["implementation"] == _sources(),
          "initialization or owner provenance differs")
    _need(value["optimizer_state_included"] is False
          and value["optimizer_state_scope"] == "no_new_architecture_or_resumable_optimizer_state"
          and value["parent_optimizer_state_retained_as_provenance"] is (kind == "current_trained_v2")
          and type(value["new_optimizer_updates"]) is int
          and value["new_optimizer_updates"] == 0 and value["authority"] == AUTHORITY
          and all(flag is False for flag in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0,
          "no optimizer/new training or semantic authority permitted")
    _wire(value)
    return value


def inspect_checkpoint(checkpoint):
    """Pure shape/source/lineage inspection; no Torch or optimizer allocation."""
    value = _validate(checkpoint)
    return {"schema": SCHEMA, "profile": PROFILE, "checkpoint_sha256": checkpoint_sha256(value),
        "weights_sha256": value["weights_sha256"], "parent_kind": value["parent_kind"],
        "parent_checkpoint_sha256": value["parent_checkpoint_sha256"],
        "historical_progress": deepcopy(value["historical_progress"]),
        "parameter_order": list(SHAPES), "tensor_shapes": {k: list(v) for k, v in SHAPES.items()},
        "legacy_tensors_exact_equal": True, "new_parameter_count": 3073,
        "gate_initial_value": 0.0, "seed_replay_verified": False,
        "numerical_runtime_verified": False, "optimizer_constructed": False, "optimizer_restored": False,
        "source_encoder_identity": None, "width8_768_qualification": "pending", "authority": dict(AUTHORITY)}


def runtime_metadata():
    """Live CPU runtime declaration, without a model or optimizer."""
    loaded = _owners(numerical=True)
    torch = loaded["numerical"]._torch()
    _need(torch.get_default_dtype() is torch.float32 and torch.get_default_device().type == "cpu"
          and torch.get_num_threads() == 1, "one-thread default CPU float32 runtime required")
    return {"python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
        "machine": platform.machine(), "torch_version": str(torch.__version__),
        "torch_build_sha256": hashlib.sha256(torch.__config__.show().encode()).hexdigest(),
        "device": "cpu", "dtype": "float32", "num_threads": torch.get_num_threads(),
        "num_interop_threads": torch.get_num_interop_threads(), "mkldnn_enabled": bool(torch.backends.mkldnn.enabled),
        "deterministic_algorithms": bool(torch.are_deterministic_algorithms_enabled())}


def _projection(torch):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(PROJECTION_SEED)
        return torch.nn.Linear(384, 8, bias=False, device="cpu", dtype=torch.float32)


def migrate(parent):
    """Explicit new inference/development checkpoint; never an Adam resume."""
    original_sha = checkpoint_sha256(parent)
    inherited, identity, kind, progress = _parent(parent)
    loaded = _owners(numerical=True)
    torch = loaded["numerical"]._torch()
    runtime = runtime_metadata()
    if identity == TRAINED_SHA:
        _need(runtime == inherited["runtime"], "live trained-parent runtime differs")
    else:
        _need(runtime["torch_version"] == inherited["torch_version"], "initial parent Torch version differs")
    rng = torch.get_rng_state().clone()
    try:
        projection = _projection(torch).weight.detach().tolist()
        state = {"gate": 0.0, **{"body." + name: deepcopy(inherited["model_state"][name]) for name in BODY_SHAPES},
                 "source_to_embedding.weight": projection}
        initialization = {"projection_seed": PROJECTION_SEED, "projection": "Linear384to8_no_bias_default_seeded_uniform",
            "gate_initial_value": 0.0, "ambient_CPU_RNG_preserved": True,
            "projection_weights_sha256": checkpoint_sha256(projection), "new_parameter_count": 3073,
            "legacy_parameter_mapping": {name: "body." + name for name in BODY_SHAPES},
            "seed_replay_verified_by_pure_inspection": False}
        result = {"schema": SCHEMA, "profile": PROFILE, "architecture": ARCHITECTURE,
            "input_dimension": 384, "vocabulary_size": 537, "max_total_ids": 512, "config": dict(CONFIG),
            "codec": deepcopy(inherited["codec"]), "codec_sha256": inherited["codec_sha256"],
            "parent_checkpoint": inherited, "parent_checkpoint_sha256": identity, "parent_kind": kind,
            "parent_weights_sha256": inherited["weights_sha256"], "historical_progress": progress,
            "model_state": state, "weights_sha256": checkpoint_sha256(state), "parameter_order": list(SHAPES),
            "initialization": initialization, "implementation": _sources(), "optimizer_state_included": False,
            "optimizer_state_scope": "no_new_architecture_or_resumable_optimizer_state",
            "parent_optimizer_state_retained_as_provenance": kind == "current_trained_v2",
            "new_optimizer_updates": 0, "training_mask": 0, "evaluation_gold_mask": 0, "authority": dict(AUTHORITY)}
        _validate(result)
        _need(checkpoint_sha256(parent) == original_sha, "caller parent changed during migration")
        return result
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "migration changed ambient CPU RNG")


def restore(checkpoint):
    """Prepare one eval model per bounded phase; full-prefix forwards thereafter."""
    original_sha = checkpoint_sha256(checkpoint)
    value = _validate(checkpoint)
    loaded = _owners(numerical=True)
    numerical, torch = loaded["numerical"], loaded["numerical"]._torch()
    runtime = runtime_metadata()
    parent = value["parent_checkpoint"]
    if value["parent_kind"] == "current_trained_v2":
        _need(runtime == parent["runtime"], "live restoration runtime differs")
    else:
        _need(runtime["torch_version"] == parent["torch_version"], "initial parent runtime differs")
    rng = torch.get_rng_state().clone()
    try:
        raw_body = numerical._model({"dimension": 384}, {"target_vocabulary": value["codec"]["vocabulary"]}, CONFIG)
        templates = raw_body.state_dict()
        _need(list(templates) == list(BODY_SHAPES), "raw JointDecoder state inventory differs")
        raw_body.load_state_dict({name: numerical._tensor(parent["model_state"][name], tensor, name)
                                 for name, tensor in templates.items()}, strict=True)

        class GatedDecoder(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.body = deepcopy(raw_body)
                self.source_to_embedding = _projection(torch)
                self.gate = torch.nn.Parameter(torch.zeros((), device="cpu", dtype=torch.float32))
                self.dimension = 384

            def forward(self, latent, prefix):
                _need(isinstance(latent, torch.Tensor) and latent.device.type == "cpu" and latent.dtype is torch.float32
                      and latent.ndim == 2 and 1 <= latent.shape[0] <= 128 and latent.shape[1] == 384
                      and bool(torch.isfinite(latent).all()), "exact finite CPU float32 latent matrix required")
                _need(isinstance(prefix, torch.Tensor) and prefix.device.type == "cpu" and prefix.dtype is torch.long
                      and prefix.ndim == 2 and prefix.shape[0] == latent.shape[0] and 1 <= prefix.shape[1] <= 512
                      and bool((prefix >= 0).all()) and bool((prefix < 537).all())
                      and bool((prefix[:, 0] == 1).all()), "bounded full BOS prefix required")
                projected = self.body.project(latent)
                persistent = self.gate * self.source_to_embedding(projected).unsqueeze(1)
                embedded = self.body.target_embedding(prefix) + persistent
                _need(bool(torch.isfinite(projected).all()) and bool(torch.isfinite(embedded).all()),
                      "nonfinite projection or gated embedding")
                outputs, _ = self.body.decoder(embedded, self.body.start(projected))
                logits = self.body.output(outputs)
                _need(list(logits.shape) == [len(latent), prefix.shape[1], 537] and bool(torch.isfinite(logits).all()),
                      "full537 finite output required")
                return projected, logits

            def describe(self):
                state = {name: tensor.detach().tolist() for name, tensor in self.state_dict().items()}
                return {"schema": SCHEMA, "profile": PROFILE, "architecture": ARCHITECTURE,
                    "tensor_shapes": {name: list(tensor.shape) for name, tensor in self.state_dict().items()},
                    "parameter_order": list(self.state_dict()), "weights_sha256": checkpoint_sha256(state),
                    "legacy_tensors_exact_equal": all(state["body."+name] == parent["model_state"][name] for name in BODY_SHAPES),
                    "new_parameter_count": 3073, "gate_value": float(self.gate.detach()),
                    "projection_seed": PROJECTION_SEED, "seed_replay_verified_at_restore": True,
                    "full_prefix_GRU": True, "incremental_state": False, "legacy_outputs_equality_qualified": False,
                    "optimizer_constructed": False, "optimizer_restored": False, "production_ready": False,
                    "source_encoder_identity": None, "authority": dict(AUTHORITY)}

        model = GatedDecoder()
        _need(model.source_to_embedding.weight.detach().tolist() == value["model_state"]["source_to_embedding.weight"],
              "projection seed replay differs from checkpoint")
        _need(list(model.state_dict()) == list(SHAPES), "new architecture parameter order differs")
        model.load_state_dict({name: numerical._tensor(value["model_state"][name], template, name)
                               for name, template in model.state_dict().items()}, strict=True)
        model.eval()
        _need({name: tensor.detach().tolist() for name, tensor in model.state_dict().items()} == value["model_state"],
              "restored tensors differ from exact checkpoint")
        _need(runtime_metadata() == runtime and checkpoint_sha256(checkpoint) == original_sha,
              "runtime or caller checkpoint changed during restore")
        return model
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "restoration changed ambient CPU RNG")


def source_profile_bridge():
    """Describe this experimental port without loading checkpoints or Torch."""
    _bridge.require_source('gated_conditioning', _PORTED_SOURCE_SHA256)
    return _bridge.profile_bridge('gated_conditioning')
