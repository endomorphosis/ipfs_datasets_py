"""Training-only, masked decoder distillation with separate output heads.

Each head must declare matching vocabulary and reference-prefix identities.
Those declarations and qualification hashes are bindings, not independently
authenticated teacher qualification. This module loads no model, constructs no
optimizer, and never supplies target prefixes to an inference/source interface.
Torch is imported only when an objective is requested.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re


SCHEMA = "gte-masked-decoder-distillation/v1"
COMBINED_SCHEMA = "gte-multiteacher-decoder-objective/v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CONTRACT_FIELDS = {
    "student_codec_sha256", "teacher_codec_sha256",
    "student_prefix_sha256", "teacher_prefix_sha256", "prefix_policy",
    "distribution", "teacher_checkpoint_sha256", "teacher_qualification_sha256",
    "teacher_scope_id",
}
_RESULT_FIELDS = {
    "schema", "loss", "valid_token_count", "excluded_token_count", "batch_size",
    "sequence_length", "vocabulary_size", "temperature", "alignment_contract",
    "alignment_contract_sha256", "teacher_logits_detached",
    "qualification_authenticated", "training_performed", "proof_authority",
}
MAX_LOGIT_ELEMENTS = 16 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def validate_alignment_contract(value):
    """Check one head's declared codec, prefix and donor evidence identities.

    Raw and grammar-masked heads are separate distributions. Grammar-masked
    inputs use finite logits; this helper does not infer grammar masks or align
    unequal vocabularies, prefixes, timestep policies, or teacher scopes.
    """
    _require(type(value) is dict and set(value) == _CONTRACT_FIELDS,
             "closed per-head alignment contract required")
    for name in ("student_codec_sha256", "teacher_codec_sha256",
                 "student_prefix_sha256", "teacher_prefix_sha256",
                 "teacher_checkpoint_sha256", "teacher_qualification_sha256"):
        _require(type(value[name]) is str and _SHA.fullmatch(value[name]),
                 "full lowercase " + name + " required")
    _require(value["student_codec_sha256"] == value["teacher_codec_sha256"],
             "student and teacher codec identities differ within this head")
    _require(value["student_prefix_sha256"] == value["teacher_prefix_sha256"],
             "student and teacher reference-prefix identities differ within this head")
    _require(value["prefix_policy"] == "reference_prefix",
             "explicit training reference-prefix policy required")
    _require(value["distribution"] in ("raw", "grammar_masked"),
             "explicit raw or grammar-masked distribution required")
    scope = value["teacher_scope_id"]
    _require(type(scope) is str and 0 < len(scope) <= 256 and scope.strip() == scope
             and all(character.isprintable() for character in scope),
             "bounded printable teacher scope identity required")
    return deepcopy(value)


def _torch():
    import torch
    return torch


def _temperature(value):
    _require(type(value) in (int, float) and .01 <= value <= 100. and math.isfinite(value),
             "finite temperature between 0.01 and 100 required")
    return float(value)


def _logits(torch, student, teacher, mask):
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled training objective required")
    for tensor, name in ((student, "student"), (teacher, "teacher")):
        _require(isinstance(tensor, torch.Tensor) and tensor.device.type == "cpu"
                 and tensor.dtype == torch.float32 and tensor.layout == torch.strided and tensor.ndim == 3,
                 "CPU float32 batched " + name + " logits required")
        _require(bool(torch.isfinite(tensor).all()), "nonfinite " + name + " logits")
    _require(student.shape == teacher.shape, "matching per-head logits shape required")
    batch, steps, vocabulary = student.shape
    _require(1 <= batch <= 256 and 1 <= steps <= 1024 and 2 <= vocabulary <= 4096
             and student.numel() <= MAX_LOGIT_ELEMENTS, "bounded per-head logits geometry required")
    _require(student.requires_grad, "differentiable student logits required")
    _require(isinstance(mask, torch.Tensor) and mask.device.type == "cpu"
             and mask.dtype == torch.bool and mask.layout == torch.strided
             and tuple(mask.shape) == (batch, steps),
             "explicit CPU boolean per-token qualification mask required")
    return batch, steps, vocabulary


def masked_teacher_kl(student_logits, teacher_logits, *, token_mask,
                      temperature=2., alignment_contract):
    """Return T² KL(teacher || student), averaged over eligible tokens only.

    ``token_mask`` explicitly excludes unsupported/padded/scope-mismatched
    positions. The caller determines and authenticates that eligibility. All
    supplied logits must be finite, including excluded positions. Teachers are
    detached; student derivatives are exactly zero at excluded positions. An
    entirely excluded head returns a differentiable zero, with no KL evaluation.
    """
    contract = validate_alignment_contract(alignment_contract)
    temperature = _temperature(temperature)
    torch = _torch()
    batch, steps, vocabulary = _logits(torch, student_logits, teacher_logits, token_mask)
    valid = int(token_mask.sum().item())
    if not valid:
        # A full sum can overflow even for finite logits; one scalar suffices
        # to preserve the zero-gradient connection to the entire input tensor.
        loss = student_logits.reshape(-1)[0] * 0.
    else:
        student = student_logits[token_mask] / temperature
        teacher = teacher_logits.detach()[token_mask] / temperature
        _require(bool(torch.isfinite(student).all()) and bool(torch.isfinite(teacher).all()),
                 "temperature scaling produced nonfinite logits")
        student_log_probs = torch.nn.functional.log_softmax(student, dim=-1)
        teacher_log_probs = torch.nn.functional.log_softmax(teacher, dim=-1)
        _require(bool(torch.isfinite(student_log_probs).all())
                 and bool(torch.isfinite(teacher_log_probs).all()),
                 "nonfinite per-head log probabilities")
        token_losses = torch.nn.functional.kl_div(student_log_probs, teacher_log_probs,
            log_target=True, reduction="none").sum(dim=-1)
        _require(bool(torch.isfinite(token_losses).all()), "nonfinite per-token KL")
        loss = token_losses.mean() * temperature**2
    _require(loss.ndim == 0 and bool(torch.isfinite(loss)) and loss.requires_grad,
             "finite differentiable scalar loss required")
    return {
        "schema": SCHEMA, "loss": loss, "valid_token_count": valid,
        "excluded_token_count": batch * steps - valid, "batch_size": batch,
        "sequence_length": steps, "vocabulary_size": vocabulary,
        "temperature": temperature, "alignment_contract": contract,
        "alignment_contract_sha256": _digest(contract), "teacher_logits_detached": True,
        "qualification_authenticated": False, "training_performed": False,
        "proof_authority": False,
    }


def _head_name(value):
    return (type(value) is str and 0 < len(value) <= 64
            and re.fullmatch(r"[a-z][a-z0-9_]*", value) is not None)


def _head_result(torch, result):
    _require(type(result) is dict and set(result) == _RESULT_FIELDS and result["schema"] == SCHEMA,
             "closed masked-head result required")
    contract = validate_alignment_contract(result["alignment_contract"])
    _require(result["alignment_contract_sha256"] == _digest(contract),
             "head alignment contract digest differs")
    _temperature(result["temperature"])
    for name, lower, upper in (("batch_size", 1, 256), ("sequence_length", 1, 1024),
                               ("vocabulary_size", 2, 4096)):
        _require(type(result[name]) is int and lower <= result[name] <= upper,
                 "bounded head " + name + " required")
    total = result["batch_size"] * result["sequence_length"]
    _require(total * result["vocabulary_size"] <= MAX_LOGIT_ELEMENTS,
             "bounded head geometry required")
    _require(type(result["valid_token_count"]) is int and 0 <= result["valid_token_count"] <= total
             and type(result["excluded_token_count"]) is int
             and result["excluded_token_count"] == total - result["valid_token_count"],
             "consistent per-head token accounting required")
    _require(result["teacher_logits_detached"] is True
             and all(result[name] is False for name in (
                 "qualification_authenticated", "training_performed", "proof_authority")),
             "conservative per-head evidence declarations required")
    loss = result["loss"]
    _require(isinstance(loss, torch.Tensor) and loss.device.type == "cpu"
             and loss.dtype == torch.float32 and loss.ndim == 0 and loss.requires_grad
             and bool(torch.isfinite(loss)), "finite differentiable CPU float32 head loss required")


def combine_multiteacher_losses(head_results, *, weights):
    """Weight scalar objectives; keep each output head's normalization separate.

    Different codec sizes and timestep counts across heads are allowed. No
    logits, vocabulary entries, prefix positions or probability distributions
    are combined. This function creates no optimizer and performs no fitting.
    """
    _require(type(head_results) is dict and 1 <= len(head_results) <= 16
             and all(_head_name(name) for name in head_results),
             "bounded named head results required")
    _require(type(weights) is dict and set(weights) == set(head_results),
             "exact per-head weights required")
    _require(all(type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value)
                 for value in weights.values()) and any(value > 0 for value in weights.values()),
             "finite nonnegative head weights with one positive weight required")
    torch = _torch()
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "gradient-enabled objective combination required")
    names = sorted(head_results)
    for name in names:
        _head_result(torch, head_results[name])
    weighted = [head_results[name]["loss"] * float(weights[name]) for name in names]
    loss = torch.stack(weighted).sum()
    _require(bool(torch.isfinite(loss)) and loss.requires_grad,
             "finite differentiable combined loss required")
    heads = {}
    for name in names:
        result = head_results[name]
        heads[name] = {key: deepcopy(value) for key, value in result.items() if key != "loss"}
        heads[name].update(weight=float(weights[name]),
                           loss_value=float(result["loss"].detach().item()))
    return {"schema": COMBINED_SCHEMA, "loss": loss, "heads": heads,
            "head_normalization": "eligible_tokens_within_each_head",
            "logits_combined": False, "qualification_authenticated": False,
            "training_performed": False, "proof_authority": False}
