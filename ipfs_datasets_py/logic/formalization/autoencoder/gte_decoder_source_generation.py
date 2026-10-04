"""Source-only, unmasked greedy generation from preserved logic decoders.

Only an input vector, a private model, and fixed decoding controls enter the
numerical API. References belong to a separate scorer. Inspection is dependency
free and authenticates receipt structure, not numerical execution or quality.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "gte-decoder-source-only-generation/v1"
VARIANTS = {"donor384": {"primary384": 384}, "legacy8": {"legacy8": 8},
            "student768": {"primary384": 768, "legacy8": 768}}
NUMERICAL_PROFILE = {"device": "cpu", "dtype": "float32", "threads": 1,
    "eval_mode": True, "decoding": "greedy_unmasked_argmax", "batch_size": 1,
    "bos_token_id": 1, "eos_token_id": 2,
    "prefix_origin": "previously_generated_tokens_only", "target_budget_includes_bos": True}
TRUE_FLAGS = {"model_parameters_unchanged", "model_buffers_unchanged",
    "parameter_gradients_unchanged", "model_storage_unchanged",
    "model_training_modes_restored", "input_unchanged", "rng_restored", "threads_restored"}
FALSE_FLAGS = {"optimizer_created", "training_executed", "distillation_executed",
    "encoder_executed", "model_downloaded", "proof_authority", "qualification_executed"}
GENERATION_FIELDS = {"schema", "variant", "head", "input_dimension", "input_vector_sha256",
    "numerical_input_sha256", "max_new_tokens", "inherited_max_target_tokens",
    "effective_max_new_tokens", "vocabulary_size", "generated_ids", "generated_ids_sha256",
    "terminated", "truncated", "stop_reason", "steps", "step_count", "numerical_profile",
    "model_state_sha256_before", "model_state_sha256_after", "model_buffers_sha256_before",
    "model_buffers_sha256_after", "gradient_state_sha256_before", "gradient_state_sha256_after",
    "optimizer_steps", "implementation_sha256", *TRUE_FLAGS, *FALSE_FLAGS}
STEP_FIELDS = {"step", "prefix_length", "prefix_sha256", "input_vector_sha256",
               "raw_logits_sha256", "next_token_id"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _implementation():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _controls(variant, head, max_new_tokens, inherited_max_target_tokens):
    _require(type(variant) is str and variant in VARIANTS and type(head) is str
             and head in VARIANTS[variant], "explicit compatible variant and head required")
    _require(type(max_new_tokens) is int and 1 <= max_new_tokens <= 1024,
             "max_new_tokens must be an integer in [1, 1024]")
    _require(type(inherited_max_target_tokens) is int and 4 <= inherited_max_target_tokens <= 1024,
             "inherited target-token budget must be an integer in [4, 1024]")
    return VARIANTS[variant][head], min(max_new_tokens, inherited_max_target_tokens - 1)


def inspect_source_only_generation(receipt):
    """Validate a compact generated-prefix audit without importing Torch.

    Caller-authenticated bytes and a trusted numerical runner are still needed
    to establish that logits were computed. This inspector grants no quality.
    """
    _require(type(receipt) is dict and set(receipt) == GENERATION_FIELDS,
             "closed source-only generation receipt required")
    _require(receipt["schema"] == SCHEMA, "source-only generation schema differs")
    dimension, cap = _controls(receipt["variant"], receipt["head"], receipt["max_new_tokens"],
                               receipt["inherited_max_target_tokens"])
    _require(type(receipt["input_dimension"]) is int and receipt["input_dimension"] == dimension
             and type(receipt["effective_max_new_tokens"]) is int
             and receipt["effective_max_new_tokens"] == cap, "generation geometry or cap differs")
    _require(type(receipt["vocabulary_size"]) is int and 3 <= receipt["vocabulary_size"] <= 4096,
             "bounded inherited vocabulary required")
    ids = receipt["generated_ids"]
    _require(type(ids) is list and 2 <= len(ids) <= cap + 1 and ids[0] == 1
             and all(type(token) is int and 0 <= token < receipt["vocabulary_size"] for token in ids),
             "bounded generated IDs including BOS required")
    _require(2 not in ids[1:-1], "generation continued after EOS")
    terminated = ids[-1] == 2
    _require(type(receipt["terminated"]) is bool and receipt["terminated"] == terminated
             and type(receipt["truncated"]) is bool and receipt["truncated"] == (not terminated)
             and receipt["stop_reason"] == ("eos" if terminated else "token_limit")
             and (terminated or len(ids) == cap + 1), "generation stop policy differs")
    _require(type(receipt["steps"]) is list and type(receipt["step_count"]) is int
             and receipt["step_count"] == len(receipt["steps"]) == len(ids) - 1,
             "one generation step per emitted token required")
    for index, step in enumerate(receipt["steps"], 1):
        _require(type(step) is dict and set(step) == STEP_FIELDS
                 and type(step["step"]) is int and step["step"] == index
                 and type(step["prefix_length"]) is int and step["prefix_length"] == index
                 and step["prefix_sha256"] == digest(ids[:index])
                 and type(step["next_token_id"]) is int and step["next_token_id"] == ids[index]
                 and step["input_vector_sha256"] == receipt["input_vector_sha256"]
                 and _sha(step["raw_logits_sha256"]), "self-generated prefix chain differs")
    for key in ("input_vector_sha256", "numerical_input_sha256", "generated_ids_sha256",
                "model_state_sha256_before", "model_state_sha256_after", "model_buffers_sha256_before",
                "model_buffers_sha256_after", "gradient_state_sha256_before", "gradient_state_sha256_after",
                "implementation_sha256"):
        _require(_sha(receipt[key]), "lowercase generation SHA256 required: " + key)
    _require(receipt["generated_ids_sha256"] == digest(ids)
             and receipt["implementation_sha256"] == _implementation(), "generation binding differs")
    for stem in ("model_state", "model_buffers", "gradient_state"):
        _require(receipt[stem + "_sha256_before"] == receipt[stem + "_sha256_after"],
                 "generation changed " + stem)
    _require(all(type(receipt[key]) is bool and receipt[key] is True for key in TRUE_FLAGS)
             and all(type(receipt[key]) is bool and receipt[key] is False for key in FALSE_FLAGS)
             and type(receipt["optimizer_steps"]) is int and receipt["optimizer_steps"] == 0,
             "source-only generation cannot train, encode, qualify or grant proof authority")
    _require(type(receipt["numerical_profile"]) is dict
             and digest(receipt["numerical_profile"]) == digest(NUMERICAL_PROFILE),
             "deterministic CPU generation profile differs")
    return {"schema": "gte-decoder-source-only-generation-inspection/v1",
        "status": "source_only_generation_inspected", "variant": receipt["variant"],
        "head": receipt["head"], "generated_token_count": len(ids) - 1,
        "generation_sha256": digest(receipt), "execution_authenticated": False,
        "teacher_qualified": False, "proof_authority": False}


@contextmanager
def _numerical_context(torch, model):
    previous_threads = torch.get_num_threads()
    training_modes = [(part, part.training) for part in model.modules()]
    try:
        if previous_threads != 1:
            torch.set_num_threads(1)
        model.eval()
        with torch.random.fork_rng(devices=[]), torch.no_grad():
            yield
    finally:
        for part, training in training_modes:
            part.training = training
        if torch.get_num_threads() != previous_threads:
            torch.set_num_threads(previous_threads)


def _snapshot(torch, model):
    parameters = dict(model.named_parameters())
    buffers = dict(model.named_buffers())
    for name, tensor in {**parameters, **{"buffer:" + key: value for key, value in buffers.items()}}.items():
        _require(tensor.device.type == "cpu" and (not tensor.is_floating_point()
                 or tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all())),
                 "finite CPU float32 model tensors required: " + name)
    _require(all(tensor.dtype == torch.float32 for tensor in parameters.values()),
             "CPU float32 decoder parameters required")
    gradients = {name: parameter.grad for name, parameter in parameters.items()}
    _require(all(value is None or value.device.type == "cpu" and value.dtype == torch.float32
                 and bool(torch.isfinite(value).all()) for value in gradients.values()),
             "finite existing parameter gradients required")
    return {"parameters": parameters, "buffers": buffers, "gradients": gradients,
        "copies": {name: tensor.detach().clone() for name, tensor in parameters.items()},
        "buffer_copies": {name: tensor.detach().clone() for name, tensor in buffers.items()},
        "gradient_copies": {name: None if tensor is None else tensor.detach().clone()
                            for name, tensor in gradients.items()},
        "requires_grad": {name: tensor.requires_grad for name, tensor in parameters.items()},
        "pointers": {name: tensor.untyped_storage().data_ptr() for name, tensor in parameters.items()},
        "buffer_pointers": {name: tensor.untyped_storage().data_ptr() for name, tensor in buffers.items()},
        "state_sha256": digest({name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}),
        "buffers_sha256": digest({name: tensor.detach().tolist() for name, tensor in buffers.items()}),
        "gradients_sha256": digest({name: None if tensor is None else tensor.detach().tolist()
                                     for name, tensor in gradients.items()})}


def _unchanged(torch, before, after):
    for category, copy_key in (("parameters", "copies"), ("buffers", "buffer_copies")):
        _require(set(before[category]) == set(after[category])
                 and all(before[category][name] is after[category][name]
                    and torch.equal(before[copy_key][name], after[category][name])
                    for name in before[category]), "source generation changed model " + category)
    _require(before["requires_grad"] == after["requires_grad"]
             and before["pointers"] == after["pointers"]
             and before["buffer_pointers"] == after["buffer_pointers"], "source generation changed model storage")
    _require(all(before["gradients"][name] is after["gradients"][name]
                 and (before["gradient_copies"][name] is None
                      or torch.equal(before["gradient_copies"][name], after["gradients"][name]))
                 for name in before["gradients"]), "source generation changed parameter gradients")
    for stem in ("state", "buffers", "gradients"):
        _require(before[stem + "_sha256"] == after[stem + "_sha256"],
                 "source generation changed model " + stem)


def _logits(torch, model, variant, head, vector, prefix):
    if variant == "donor384":
        outputs = model(vector, prefix)
        _require(type(outputs) in (tuple, list) and len(outputs) == 3, "original 384D decoder outputs required")
        logits = outputs[2]
        intermediates = outputs
    elif variant == "legacy8":
        outputs = model(vector, prefix)
        _require(type(outputs) in (tuple, list) and len(outputs) == 2, "original 8D decoder outputs required")
        logits = outputs[1]
        intermediates = outputs
    else:
        shared = model.primary.condition_from_input(vector)
        if head == "primary384":
            logits = model.primary.decode_from_condition(shared, prefix)
            intermediates = (shared, logits)
        else:
            latent = model.auxiliary_connector(shared)
            projected, logits = model.legacy8(latent, prefix)
            intermediates = (shared, latent, projected, logits)
    _require(all(isinstance(value, torch.Tensor) and value.device.type == "cpu"
                 and value.dtype == torch.float32 and not value.requires_grad
                 and bool(torch.isfinite(value).all()) for value in intermediates),
             "finite detached CPU float32 generation outputs required")
    return logits


def generate_source_only(model, *, variant, head, input_vector, max_new_tokens,
                         inherited_max_target_tokens):
    """Generate only from source coordinates and previously emitted tokens.

    The fixed inherited budget includes BOS, as in the original V2 decoder.
    PAD and extra BOS predictions remain visible; no grammar mask or target
    length changes the raw argmax. Both stop paths include the emitted token.
    """
    dimension, cap = _controls(variant, head, max_new_tokens, inherited_max_target_tokens)
    _require(type(input_vector) is list and len(input_vector) == dimension
             and all(_finite_number(value) for value in input_vector),
             "finite source-only input vector with declared dimension required")
    owned_input = deepcopy(input_vector)
    input_sha256 = digest(owned_input)
    import torch
    _require(isinstance(model, torch.nn.Module), "private Torch decoder model required")
    _require(len(list(model.named_parameters())) == (30 if variant == "student768" else 13),
             "complete original or dual-student decoder tensors required")
    part = model.primary if variant == "student768" and head == "primary384" else (
        model.legacy8 if variant == "student768" else model)
    vocabulary_size = part.target_embedding.num_embeddings
    _require(type(vocabulary_size) is int and 3 <= vocabulary_size <= 4096,
             "bounded original head vocabulary required")
    if variant == "student768" and head == "primary384":
        _require(type(model.primary.max_target_tokens) is int
                 and model.primary.max_target_tokens == inherited_max_target_tokens,
                 "primary inherited token budget differs")
    vector = torch.tensor([owned_input], dtype=torch.float32, device="cpu")
    _require(bool(torch.isfinite(vector).all()), "source input overflows float32")
    numerical_input_sha256 = digest(vector.tolist()[0])
    before = _snapshot(torch, model)
    previous_rng = torch.get_rng_state().clone()
    previous_threads = torch.get_num_threads()
    modes = [part.training for part in model.modules()]
    ids, steps = [1], []
    with _numerical_context(torch, model):
        for index in range(1, cap + 1):
            prefix = torch.tensor([ids], dtype=torch.int64, device="cpu")
            logits = _logits(torch, model, variant, head, vector, prefix)
            _require(tuple(logits.shape) == (1, len(ids), vocabulary_size),
                     "generation logits do not match generated prefix and vocabulary")
            raw = logits[0, -1]
            token = int(raw.argmax().item())
            steps.append({"step": index, "prefix_length": len(ids), "prefix_sha256": digest(ids),
                "input_vector_sha256": input_sha256, "raw_logits_sha256": digest(raw.tolist()),
                "next_token_id": token})
            ids.append(token)
            if token == 2:
                break
    after = _snapshot(torch, model)
    _unchanged(torch, before, after)
    _require(torch.equal(previous_rng, torch.get_rng_state())
             and torch.get_num_threads() == previous_threads
             and modes == [part.training for part in model.modules()], "generation numerical context was not restored")
    _require(digest(input_vector) == input_sha256
             and digest(vector.tolist()[0]) == numerical_input_sha256, "generation changed source input")
    terminated = ids[-1] == 2
    receipt = {"schema": SCHEMA, "variant": variant, "head": head, "input_dimension": dimension,
        "input_vector_sha256": input_sha256, "numerical_input_sha256": numerical_input_sha256,
        "max_new_tokens": max_new_tokens, "inherited_max_target_tokens": inherited_max_target_tokens,
        "effective_max_new_tokens": cap, "vocabulary_size": vocabulary_size, "generated_ids": ids,
        "generated_ids_sha256": digest(ids), "terminated": terminated, "truncated": not terminated,
        "stop_reason": "eos" if terminated else "token_limit", "steps": steps, "step_count": len(steps),
        "numerical_profile": deepcopy(NUMERICAL_PROFILE),
        "model_state_sha256_before": before["state_sha256"], "model_state_sha256_after": after["state_sha256"],
        "model_buffers_sha256_before": before["buffers_sha256"], "model_buffers_sha256_after": after["buffers_sha256"],
        "gradient_state_sha256_before": before["gradients_sha256"],
        "gradient_state_sha256_after": after["gradients_sha256"], "optimizer_steps": 0,
        "implementation_sha256": _implementation(), **{key: True for key in TRUE_FLAGS},
        **{key: False for key in FALSE_FLAGS}}
    inspect_source_only_generation(receipt)
    return receipt


__all__ = ["generate_source_only", "inspect_source_only_generation", "digest", "SCHEMA", "GENERATION_FIELDS"]
