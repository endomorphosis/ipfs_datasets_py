"""Seeded counted28 weights and unmasked observations of the existing GRU.

This profile adapter preserves the fixed537 head and numerical kernel. Complete
counted targets and their derived context are labels for teacher forcing only.
There is no optimizer, grammar mask, generation loop or legal eligibility grant.
Callers must arrange the existing admitted one-thread CPU execution scope.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path

SCHEMA = "legal-counted-content-head-checkpoint/v1"
PROFILE = "seeded-counted28-content-head-384/v1"
SCORE_SCHEMA = "legal-counted-content-head-score/v1"
EVALUATION_SCHEMA = "legal-counted-content-head-teacher-forced/v1"
DIMENSION, VOCABULARY_SIZE, MAX_SEQUENCE_TOKENS = 384, 28, 512
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_BASE_NAME = "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_head_v1"
_OWNER_SPECS = (
    (_BASE_NAME, "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("ipfs_datasets_py.logic.formalization.autoencoder.ir_decoder_profile_inventory",
     "logic/formalization/autoencoder/ir_decoder_profile_inventory.py",
     "8cdb805cc966b361d1bcc5e626831fe4cad568da7222bc225ef58ad4e76b4877"),
    ("ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1",
     "logic/autoformal/legal_counted_frame_v1.py",
     "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"),
)
_CODEC_SHA = "8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8"
_AUTHORITY = dict.fromkeys((
    "source_bound", "source_semantics_verified", "conditioning_producer_verified",
    "conditioning_space_training_compatibility_verified", "permitted_inference_context_verified",
    "varied_reviewed_target_population_verified", "training_qualified",
    "training_gold_qualified", "evaluation_gold_qualified", "source_fidelity_verified",
    "accepted", "admitted", "proof_authority", "Lean_admitted",
), False)
_LIMITATIONS = [
    "Seeded weights only: zero counted optimizer updates, no donor transfer or optimizer state.",
    "Conditioning is a caller-supplied384 vector; no native producer or source correspondence is verified.",
    "All28 logits remain unmasked. A token-range check is not grammatical prefix acceptance.",
    "Teacher forcing exposes one fixed authored target and its derived context as labels only; neither enters the conditioning vector.",
    "Teacher-forced loss and token accuracy are engineering observations, not autonomous reconstruction or held-out statutory accuracy.",
    "The counted codec recognizes one fixed content/context; it is not a varied reviewed training population.",
    "Named source fences and stored Torch version do not attest loaded bytecode, third-party binaries or a hermetic runtime.",
]


def _base():
    module = importlib.import_module(_BASE_NAME)
    expected = _SELF_PATH.with_name("legal_compact_content_head_v1.py")
    if type(getattr(module, "__file__", None)) is not str or Path(module.__file__).absolute() != expected:
        raise ValueError("canonical fixed537 numerical wrapper required")
    module._source(expected, _OWNER_SPECS[0][2])
    return module


def _owners(base):
    package = _SELF_PATH.parents[3]
    pins = [base._source(_SELF_PATH, _SELF_SHA)]
    modules = {}
    for name, relative, expected in _OWNER_SPECS:
        path = package / relative
        pins.append(base._source(path, expected))
        module = importlib.import_module(name)
        base._need(type(module.__file__) is str and Path(module.__file__).absolute() == path,
                   "canonical counted profile owner origin differs")
        modules[name] = module
    return modules, pins


def _operation(original, work, *, numeric=False, as_bytes=False):
    base = _base()
    snapshot = base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)
    token = base._fingerprint(snapshot)
    modules, pins = _owners(base)
    failure = None
    def fence():
        observed, current_pins = _owners(base)
        base._need(current_pins == pins and all(observed[name] is module for name, module in modules.items()),
                   "counted profile sources or captured owners changed")
        base._need(base._fingerprint(base._copy(original, base.MAX_INPUT_BYTES, allow_bytes=True)) == token
                   and base._fingerprint(snapshot) == token, "original counted operation inputs changed")
    try:
        def delegate(data, loaded):
            result = work(data, loaded, base, modules)
            fence()
            return result
        return base._operation(snapshot, delegate, numeric=numeric, as_bytes=as_bytes)
    except BaseException as error:
        failure = error
        raise
    finally:
        base._finish(failure, fence)


def _metadata(base, modules, config):
    settings = base._config(config)
    counted = modules[_OWNER_SPECS[2][0]]
    profiles = modules[_OWNER_SPECS[1][0]]
    codec = counted.build_counted_frame_token_codec_v1()
    base._need(counted.counted_frame_token_codec_sha256(codec) == _CODEC_SHA
               and codec["vocabulary_size"] == VOCABULARY_SIZE,
               "selected full counted28 codec required")
    geometry = {name: settings[name] for name in base._SHAPE_FIELDS}
    spec = profiles.build_counted_content_head_spec_v1(
        codec, expected_codec_sha256=_CODEC_SHA, config=geometry)
    spec_sha = profiles.counted_content_head_spec_sha256(spec)
    profiles.validate_counted_content_head_spec_v1(spec, codec,
        expected_spec_sha256=spec_sha, expected_codec_sha256=_CODEC_SHA, config=geometry)
    return settings, codec, spec, spec_sha


def _implementation():
    return {"adapter_sha256": _SELF_SHA,
            "owners": {relative: expected for _, relative, expected in _OWNER_SPECS}}


def _state(base, state, shapes):
    base._need(type(state) is dict and set(state) == set(shapes),
               "exact counted thirteen-tensor inventory required")
    def visit(value, shape):
        if shape:
            base._need(type(value) is list and len(value) == shape[0],
                       "complete counted tensor shape differs")
            for child in value:
                visit(child, shape[1:])
        else:
            base._need(type(value) is float and base._f32(value).hex() == value.hex(),
                       "exact finite exported counted float32 scalar required")
    for name, shape in shapes.items():
        visit(state[name], shape)


def _checkpoint(data, base, modules):
    offered, expected = data["checkpoint"], data["expected_checkpoint_sha256"]
    base._hash(expected, "complete counted checkpoint")
    value = base._copy(offered, base.MAX_CHECKPOINT_BYTES)
    base._need(base._digest(value) == expected, "independent counted checkpoint hash differs")
    fields = {"schema", "profile", "architecture", "input_dimension", "input_role", "device", "dtype",
              "torch_version", "config", "codec", "codec_sha256", "spec", "spec_sha256", "implementation",
              "model_state", "weights_sha256", "initialization", "optimizer_state_included",
              "counted_training_steps", "max_total_ids", "authority", "training_mask",
              "evaluation_gold_mask", "limitations"}
    base._need(type(value) is dict and set(value) == fields, "closed counted checkpoint required")
    base._need(value["schema"] == SCHEMA and value["profile"] == PROFILE
               and value["architecture"] == base.ARCHITECTURE
               and type(value["input_dimension"]) is int and value["input_dimension"] == DIMENSION
               and value["input_role"] == "unverified_caller_supplied_conditioning_vector"
               and value["device"] == "cpu" and value["dtype"] == "float32"
               and type(value["torch_version"]) is str and 0 < len(value["torch_version"]) <= 128
               and type(value["max_total_ids"]) is int and value["max_total_ids"] == MAX_SEQUENCE_TOKENS,
               "counted profile, input declaration or geometry differs")
    base._need(type(value["config"]) is dict, "closed counted configuration required")
    settings, codec, spec, spec_sha = _metadata(base, modules, value["config"])
    base._need(set(value["config"]) == set(settings) and value["config"] == settings
               and base._wire(value["codec"], base.MAX_CODEC_BYTES) == base._wire(codec, base.MAX_CODEC_BYTES)
               and value["codec_sha256"] == _CODEC_SHA
               and base._wire(value["spec"], base.MAX_CHECKPOINT_BYTES) == base._wire(spec, base.MAX_CHECKPOINT_BYTES)
               and value["spec_sha256"] == spec_sha and value["implementation"] == _implementation(),
               "complete counted codec, spec or implementation differs")
    _state(base, value["model_state"], spec["identity"]["tensor_shapes"])
    base._need(value["weights_sha256"] == base._digest(value["model_state"])
               and base._wire(value["initialization"], base.MAX_CODEC_BYTES)
                   == base._wire({"mode": "seeded_new", "seed": settings["seed"],
                       "fresh_optimizer_required": True, "donor_weights_transferred": False}, base.MAX_CODEC_BYTES)
               and value["optimizer_state_included"] is False
               and type(value["counted_training_steps"]) is int and value["counted_training_steps"] == 0
               and value["authority"] == _AUTHORITY
               and all(flag is False for flag in value["authority"].values())
               and type(value["training_mask"]) is int and value["training_mask"] == 0
               and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0
               and value["limitations"] == _LIMITATIONS,
               "counted weights, initialization or zero-step authority differs")
    return value


def _model(value, loaded, base):
    torch = base._torch(loaded)
    base._need(value["torch_version"] == str(torch.__version__), "counted Torch version differs")
    numerical = loaded["modules"]["numerical"]
    numerical._implementation()
    rng = torch.get_rng_state().clone()
    try:
        model = base._new_model(loaded, value["config"], value["codec"]["vocabulary"])
        templates = model.state_dict()
        shapes = value["spec"]["identity"]["tensor_shapes"]
        base._need(set(templates) == set(shapes)
                   and all(list(tensor.shape) == shapes[name] for name, tensor in templates.items()),
                   "actual counted kernel geometry differs from declared spec")
        state = {name: numerical._tensor(value["model_state"][name], tensor, name)
                 for name, tensor in templates.items()}
        model.load_state_dict(state, strict=True)
        base._need(all(tensor.device.type == "cpu" and tensor.dtype == torch.float32
                       and bool(torch.isfinite(tensor).all()) for tensor in model.state_dict().values()),
                   "restored counted CPU float32 state differs")
        return model.eval()
    finally:
        base._need(torch.equal(rng, torch.get_rng_state()), "counted restore changed ambient CPU RNG")


def create_counted_content_head_v1(*, config=None):
    """Create a separate seeded weights-only counted28 snapshot; never train."""
    def work(data, loaded, base, modules):
        settings, codec, spec, spec_sha = _metadata(base, modules, data["config"])
        torch = base._torch(loaded)
        loaded["modules"]["numerical"]._implementation()
        rng = torch.get_rng_state().clone()
        try:
            model = base._new_model(loaded, settings, codec["vocabulary"])
            base._need(all(tensor.device.type == "cpu" and tensor.dtype == torch.float32
                           and bool(torch.isfinite(tensor).all()) for tensor in model.state_dict().values()),
                       "created counted state must be finite CPU float32")
            state = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
            _state(base, state, spec["identity"]["tensor_shapes"])
            value = {"schema": SCHEMA, "profile": PROFILE, "architecture": base.ARCHITECTURE,
                "input_dimension": DIMENSION, "input_role": "unverified_caller_supplied_conditioning_vector",
                "device": "cpu", "dtype": "float32", "torch_version": str(torch.__version__),
                "config": settings, "codec": codec, "codec_sha256": _CODEC_SHA, "spec": spec,
                "spec_sha256": spec_sha, "implementation": _implementation(), "model_state": state,
                "weights_sha256": base._digest(state), "initialization": {"mode": "seeded_new",
                    "seed": settings["seed"], "fresh_optimizer_required": True, "donor_weights_transferred": False},
                "optimizer_state_included": False, "counted_training_steps": 0,
                "max_total_ids": MAX_SEQUENCE_TOKENS, "authority": dict(_AUTHORITY),
                "training_mask": 0, "evaluation_gold_mask": 0, "limitations": list(_LIMITATIONS)}
            _checkpoint(dict(checkpoint=value, expected_checkpoint_sha256=base._digest(value)), base, modules)
            return value
        finally:
            base._need(torch.equal(rng, torch.get_rng_state()), "counted construction changed ambient CPU RNG")
    return _operation(dict(config=config), work, numeric=True)


def counted_content_head_sha256(checkpoint):
    """Hash a bounded checkpoint value without asserting it is a valid snapshot."""
    return _operation(dict(checkpoint=checkpoint),
                      lambda data, loaded, base, modules: base._digest(data["checkpoint"]))


def validate_counted_content_head_v1(checkpoint, *, expected_checkpoint_sha256):
    """Validate the whole separate profile, then strictly restore actual tensors."""
    def work(data, loaded, base, modules):
        value = _checkpoint(data, base, modules)
        _model(value, loaded, base)
        return value
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256),
                      work, numeric=True)


def counted_content_head_bytes_v1(checkpoint, *, expected_checkpoint_sha256):
    """Serialize a fully validated and numerically restored counted snapshot."""
    def work(data, loaded, base, modules):
        value = _checkpoint(data, base, modules)
        _model(value, loaded, base)
        return base._wire(value, base.MAX_CHECKPOINT_BYTES)
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256),
                      work, numeric=True, as_bytes=True)


def load_counted_content_head_v1(checkpoint_raw, *, expected_raw_sha256):
    """Check exact received bytes separately from canonical checkpoint identity."""
    base = _base()
    base._hash(expected_raw_sha256, "raw counted snapshot")
    base._need(type(checkpoint_raw) is bytes and 0 < len(checkpoint_raw) <= base.MAX_CHECKPOINT_BYTES
               and hashlib.sha256(checkpoint_raw).hexdigest() == expected_raw_sha256,
               "bounded independently pinned counted snapshot bytes required")
    def pairs(rows):
        result = {}
        for key, value in rows:
            base._need(key not in result, "duplicate counted checkpoint key")
            result[key] = value
        return result
    def nonfinite(_):
        raise base.CompactContentHeadError("nonfinite counted snapshot JSON refused")
    try:
        value = json.loads(checkpoint_raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise base.CompactContentHeadError("bounded duplicate-free counted snapshot JSON required") from error
    return validate_counted_content_head_v1(value, expected_checkpoint_sha256=base._digest(value))


def _prefix(base, ids):
    base._need(type(ids) is list and 1 <= len(ids) < MAX_SEQUENCE_TOKENS
               and all(type(item) is int and 0 <= item < VOCABULARY_SIZE for item in ids)
               and ids[0] == 1 and all(item >= 3 for item in ids[1:]),
               "bounded nonterminal BOS then lexical counted IDs required")


def _forward(value, numeric, ids, loaded, base):
    torch = base._torch(loaded)
    model = _model(value, loaded, base)
    with torch.inference_mode():
        vector = torch.tensor([numeric], dtype=torch.float32, device="cpu")
        prefix = torch.tensor([ids], dtype=torch.long, device="cpu")
        projected, logits = model(vector, prefix)
        base._need(list(projected.shape) == [1, DIMENSION]
                   and list(logits.shape) == [1, len(ids), VOCABULARY_SIZE]
                   and bool(torch.isfinite(projected).all()) and bool(torch.isfinite(logits).all()),
                   "counted forward output shape or finite values differ")
        return logits[0].detach().tolist()


def _observation(base, value, data, numeric):
    return {"schema": SCORE_SCHEMA, "profile": PROFILE,
        "checkpoint_sha256": data["expected_checkpoint_sha256"], "weights_sha256": value["weights_sha256"],
        "codec_sha256": value["codec_sha256"], "spec_sha256": value["spec_sha256"],
        "conditioning": data["conditioning"], "conditioning_sha256": base._digest(data["conditioning"]),
        "numeric_conditioning": numeric, "conditioning_role": value["input_role"],
        "grammar_mask_applied": False, "grammatical_prefix_verified": False,
        "numerical_forward_executed": True, "model_restore_performed": True,
        "optimizer_executed": False, "counted_training_steps": 0,
        "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        "limitations": list(_LIMITATIONS)}


def score_counted_content_head_v1(checkpoint, conditioning, prefix_ids, *, expected_checkpoint_sha256):
    """Expose all28 last-position logits without a grammar mask or target lookup."""
    def work(data, loaded, base, modules):
        value = _checkpoint(data, base, modules)
        numeric = base._conditioning(data["conditioning"])
        _prefix(base, data["prefix_ids"])
        logits = _forward(value, numeric, data["prefix_ids"], loaded, base)[-1]
        result = _observation(base, value, data, numeric)
        result.update(prefix_ids=data["prefix_ids"], output_shape=[1, len(data["prefix_ids"]), VOCABULARY_SIZE],
                      logits=logits, logits_sha256=base._digest(logits),
                      raw_argmax_token_id=max(range(VOCABULARY_SIZE), key=lambda index: logits[index]))
        return result
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, prefix_ids=prefix_ids,
                           expected_checkpoint_sha256=expected_checkpoint_sha256), work, numeric=True)


def evaluate_counted_content_head_v1(checkpoint, conditioning, target_ids, context_raw, *,
                                     expected_checkpoint_sha256, expected_context_sha256):
    """Observe unmasked teacher-forced CE after genuine complete counted decoding."""
    def work(data, loaded, base, modules):
        value = _checkpoint(data, base, modules)
        numeric = base._conditioning(data["conditioning"])
        counted = modules[_OWNER_SPECS[2][0]]
        # Complete fixed-language decoding happens before any numerical forward.
        decoded = counted.decode_counted_frame_tokens_v1(data["target_ids"], data["context_raw"],
            expected_context_sha256=data["expected_context_sha256"], codec=value["codec"],
            expected_codec_sha256=value["codec_sha256"])
        ids = data["target_ids"]
        _prefix(base, ids[:-1])
        logits = _forward(value, numeric, ids[:-1], loaded, base)
        labels = ids[1:]
        losses, predictions = [], []
        for row, label in zip(logits, labels):
            maximum = max(row)
            losses.append(maximum + math.log(sum(math.exp(item - maximum) for item in row)) - row[label])
            predictions.append(max(range(VOCABULARY_SIZE), key=lambda index: row[index]))
        base._need(len(losses) == len(labels) and losses and all(math.isfinite(loss) for loss in losses),
                   "complete finite teacher-forced counted loss required")
        result = _observation(base, value, data, numeric)
        result.update(schema=EVALUATION_SCHEMA, target_ids=ids, input_ids=ids[:-1], label_ids=labels,
            context_raw_sha256=data["expected_context_sha256"], target_context_role="label_only_target_derived",
            complete_target_decode_sha256=counted.counted_frame_report_sha256(decoded),
            output_shape=[1, len(labels), VOCABULARY_SIZE], logits=logits, logits_sha256=base._digest(logits),
            token_losses=losses, mean_cross_entropy=sum(losses) / len(losses),
            prediction_ids=predictions, predicted_tokens=len(labels), eos_included_in_loss=labels[-1] == 2,
            exact_teacher_forced_token_matches=sum(a == b for a, b in zip(predictions, labels)),
            exact_teacher_forced_sequence_match=predictions == labels,
            raw_predicted_eos_positions=[index for index, item in enumerate(predictions) if item == 2],
            generation_executed=False, target_population_size=1)
        return result
    return _operation(dict(checkpoint=checkpoint, conditioning=conditioning, target_ids=target_ids,
                           context_raw=context_raw, expected_checkpoint_sha256=expected_checkpoint_sha256,
                           expected_context_sha256=expected_context_sha256), work, numeric=True)


__all__ = ["create_counted_content_head_v1", "counted_content_head_sha256",
           "validate_counted_content_head_v1", "counted_content_head_bytes_v1",
           "load_counted_content_head_v1", "score_counted_content_head_v1",
           "evaluate_counted_content_head_v1"]
