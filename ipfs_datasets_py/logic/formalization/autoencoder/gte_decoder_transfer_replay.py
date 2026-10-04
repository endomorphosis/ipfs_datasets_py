"""Export preserved decoder behavior on original 384D and 8D inputs.

This replays copied decoder bodies against independently loaded original donor
weights. It bypasses both new interfaces and never creates a 768D input. The
reference-prefix logits are unqualified preparation data, not completed KD.
Import and receipt inspection are dependency-free; execution is private CPU.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct


SCHEMA = "gte-decoder-transfer-replay/v1"
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_LOGIT_ELEMENTS = MAX_OUTPUT_BYTES // 64
TEMPERATURE = 2.0
FLAGS = {
    "original_decoder_initialization_unchanged": True,
    "all_26_inherited_tensors_unchanged": True,
    "input_adapter_exercised": False,
    "auxiliary_connector_exercised": False,
    "native768_inputs_used": False,
    "encoder_inference_executed": False,
    "training_executed": False,
    "distillation_executed": False,
    "teacher_qualified": False,
    "production_kd_eligible": False,
    "proof_authority": False,
}
_ROW_FIELDS = {
    "id", "source_sha256", "input_sha256", "reference_sha256",
    "reference_prefix_sha256", "batch_row_sha256", "prefix_ids", "next_token_ids",
    "reference_token_mask", "kd_token_mask", "teacher_logits", "teacher_logits_sha256",
    "teacher_projected_sha256", "teacher_condition_sha256", "exact_projected",
    "exact_condition", "exact_logits", "max_projected_error", "max_condition_error",
    "max_logit_error", "diagnostic_kl_t2",
}
_HEAD_FIELDS = {
    "schema", "input_dimension", "input_origin", "codec_sha256", "teacher_checkpoint_sha256",
    "teacher_weights_sha256", "vocabulary_size", "hidden_size", "max_target_tokens",
    "selected_row_count", "total_logit_elements", "prefix_policy", "distribution",
    "decoder_input_dtype", "export_dtype", "logits_detached", "rows", "exact_projected",
    "exact_condition", "exact_logits", "max_projected_error", "max_condition_error",
    "max_logit_error", "diagnostic_kl_temperature", "diagnostic_kl_t2",
}
_FIELDS = {"schema", "status", "batch_sha256", "initialization_representation_id",
    "donor_pins", "heads", "implementation", "numerical_profile", "optimizer_steps", *FLAGS}
_NUMERICAL_PROFILE = {"device": "cpu", "dtype": "float32", "threads": 1,
    "evaluation_mode": True, "gradients_enabled": False, "diagnostic_kl_temperature": TEMPERATURE}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_transfer_replay_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load decoder transfer replay dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("bounded finite replay JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _implementation():
    names = ("gte_decoder_transfer_replay", "gte_decoder_transfer_batch", "gte_decoder_reuse",
             "gte_decoder_warm_start", "gte_legacy8_decoder_donor", "gte_bridge_teacher")
    return {name + ".py": hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
            for name in names}


def _admit_originals(initialization, primary, legacy8, pins, reuse):
    """Check original parsed donor objects before any numerical library import."""
    inspector = reuse._PRIMARY._TEACHER
    inspector._fields(primary, inspector._CHECKPOINT_FIELDS, "original primary checkpoint")
    _require(primary["schema"] == inspector.CHECKPOINT_SCHEMA
             and primary["architecture"] == inspector.ARCHITECTURE
             and primary["domain_id"] == "legal_ir" and type(primary["dimension"]) is int
             and primary["dimension"] == 384, "original primary architecture differs")
    _require(all(primary[key] is False for key in inspector._FLAGS), "original primary cannot grant authority")
    inspector._config(primary)
    inspector._provenance(primary)
    codec, transform = inspector._codec(primary), inspector._transform(primary)
    expected_config = initialization["primary"]["config"]
    _require(all(primary["config"][key] == value for key, value in expected_config.items()),
             "original primary decoder configuration differs")
    _require(codec == initialization["primary"]["codec"]
             and digest(codec) == pins["teacher384_codec_sha256"]
             and transform == initialization["primary"]["input_transform"],
             "original primary codec or transform differs")
    state = primary["model_state"]
    _require(primary["weights_sha256"] == digest(state) == pins["teacher384_weights_sha256"],
             "original primary weights differ from external donor")
    shapes = inspector._INVENTORY._sequence_shapes(primary, 384)
    actual = inspector._INVENTORY._tensors(state, "original primary state")
    inspector._INVENTORY._shape_check(actual, shapes, "original primary state")
    for values in state.values():
        _exact_float32(values)
    source_pins = inspector._source_pins(primary)
    for relative, expected in source_pins.items():
        matches = [pin for pin in initialization["primary"]["donor_source_pins"]
                   if pin["path"].endswith("/" + relative)]
        _require(len(matches) == 1 and matches[0]["sha256"] == expected,
                 "original primary implementation source differs")
    snapshot = reuse._LEGACY.normalize_legacy8_decoder_donor(legacy8,
        source_checkpoint_sha256=pins["legacy8_checkpoint_sha256"])
    _require(snapshot["source_model_state_sha256"] == pins["legacy8_weights_sha256"]
             and snapshot["source_codec_sha256"] == pins["legacy8_codec_sha256"]
             and snapshot["binding"] == initialization["legacy8"]["binding"]
             and snapshot["config"] == initialization["legacy8"]["config"]
             and snapshot["codec"] == initialization["legacy8"]["codec"],
             "original legacy8 decoder identity differs")
    for values in snapshot["model_state"].values():
        _exact_float32(values)
    return snapshot


def _exact_float32(value):
    if type(value) is list:
        for child in value:
            _exact_float32(child)
        return
    _require(type(value) is float, "replay tensor leaves must be float32 serialized floats")
    try:
        restored = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("replay tensor exceeds float32") from exc
    _require(math.isfinite(value) and math.isfinite(restored) and value == restored,
             "replay tensor must contain exact finite float32 values")


def _hash(value, label):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             label + " requires lowercase SHA256")


def inspect_decoder_transfer_replay(receipt, batch, *, initialization, expected_donor_pins):
    """Check an externally authenticated replay receipt against its input batch.

    Consistency checks cannot attest that the exporter executed independently.
    Caller-admitted receipt, batch, initialization and donor file bytes remain
    necessary. False KD masks are retained until a separately qualified scope.
    """
    _helper("gte_decoder_transfer_batch").inspect_decoder_transfer_batch(
        batch, initialization, expected_donor_pins=expected_donor_pins)
    _require(type(receipt) is dict and set(receipt) == _FIELDS, "closed decoder transfer replay required")
    _require(len(_raw(receipt)) <= MAX_OUTPUT_BYTES, "replay receipt exceeds 16 MiB")
    _require(receipt["schema"] == SCHEMA and receipt["status"] == "behavior_preserved_unqualified",
             "decoder replay schema or status differs")
    _require(receipt["batch_sha256"] == batch["batch_sha256"]
             and receipt["initialization_representation_id"] == initialization["representation_id"]
             and receipt["donor_pins"] == expected_donor_pins, "replay external input identities differ")
    _require(receipt["implementation"] == _implementation(), "decoder replay implementation differs")
    _require(_raw(receipt["numerical_profile"]) == _raw(_NUMERICAL_PROFILE), "replay numerical profile differs")
    _require(all(type(receipt[key]) is bool and receipt[key] == value for key, value in FLAGS.items()),
             "replay cannot declare native768 training, KD or qualification")
    _require(type(receipt["optimizer_steps"]) is int and receipt["optimizer_steps"] == 0,
             "replay contains no optimizer steps")
    heads = receipt["heads"]
    _require(type(heads) is dict and set(heads) == {"primary384", "legacy8"}, "separate replay heads required")
    row_counts = {}
    for head_name, donor_name, pin_prefix in (("primary384", "primary", "teacher384"),
                                             ("legacy8", "legacy8", "legacy8")):
        head, input_head, donor = heads[head_name], batch["heads"][head_name], initialization[donor_name]
        _require(type(head) is dict and set(head) == _HEAD_FIELDS, "closed replay head required")
        vocabulary_size = len(input_head["target_vocabulary"])
        _require(head["schema"] == "gte-decoder-reference-prefix-head-replay/v1"
                 and head["input_dimension"] == input_head["input_dimension"]
                 and head["input_origin"] == input_head["input_origin"]
                 and head["codec_sha256"] == input_head["codec_sha256"]
                 and head["teacher_checkpoint_sha256"] == expected_donor_pins[pin_prefix + "_checkpoint_sha256"]
                 and head["teacher_weights_sha256"] == expected_donor_pins[pin_prefix + "_weights_sha256"],
                 "replay head input or donor identity differs")
        _require(type(head["vocabulary_size"]) is int and head["vocabulary_size"] == vocabulary_size
                 and type(head["hidden_size"]) is int and head["hidden_size"] == donor["config"]["hidden_size"]
                 and type(head["max_target_tokens"]) is int
                 and head["max_target_tokens"] == donor["config"]["max_target_tokens"], "replay head geometry differs")
        _require(head["prefix_policy"] == "reference_prefix" and head["distribution"] == "raw"
                 and head["decoder_input_dtype"] == head["export_dtype"] == "float32"
                 and head["logits_detached"] is True, "replay prefix/distribution policy differs")
        _require(type(head["rows"]) is list and len(head["rows"]) == input_head["selected_row_count"]
                 and type(head["selected_row_count"]) is int and head["selected_row_count"] == len(head["rows"]),
                 "replay row coverage differs")
        total = 0
        for row, original in zip(head["rows"], input_head["rows"]):
            _require(type(row) is dict and set(row) == _ROW_FIELDS, "closed replay row required")
            for name in ("id", "source_sha256", "input_sha256", "reference_sha256", "reference_prefix_sha256",
                         "prefix_ids", "next_token_ids", "reference_token_mask", "kd_token_mask"):
                _require(_raw(row[name]) == _raw(original[name]), "replay row binding differs: " + name)
            _require(row["batch_row_sha256"] == original["row_sha256"], "replay input row hash differs")
            logits = row["teacher_logits"]
            _require(type(logits) is list and len(logits) == len(original["prefix_ids"]),
                     "replay logit timestep count differs")
            for timestep in logits:
                _require(type(timestep) is list and len(timestep) == vocabulary_size,
                         "replay logits must use exact head vocabulary")
                _exact_float32(timestep)
            _require(row["teacher_logits_sha256"] == digest(logits), "replay logits digest differs")
            for name in ("teacher_projected_sha256", "teacher_condition_sha256"):
                _hash(row[name], name)
            _preserved(row)
            total += len(logits) * vocabulary_size
        _require(type(head["total_logit_elements"]) is int and head["total_logit_elements"] == total,
                 "replay total logit geometry differs")
        _preserved(head)
        _require(type(head["diagnostic_kl_temperature"]) is float
                 and head["diagnostic_kl_temperature"] == TEMPERATURE,
                 "diagnostic KL temperature differs")
        row_counts[head_name] = len(head["rows"])
    return {"schema": "gte-decoder-transfer-replay-inspection/v1",
        "status": receipt["status"], "batch_sha256": receipt["batch_sha256"],
        "row_counts": row_counts, "total_rows": sum(row_counts.values()),
        "receipt_sha256": digest(receipt), "execution_authenticated": False,
        "optimizer_steps": 0, **FLAGS}


def _preserved(value):
    _require(all(value[key] is True for key in ("exact_projected", "exact_condition", "exact_logits")),
             "copied decoder behavior differs from original donor")
    _require(all(type(value[key]) is float and value[key] == 0. for key in (
        "max_projected_error", "max_condition_error", "max_logit_error", "diagnostic_kl_t2")),
        "preserved copied behavior requires zero errors and zero diagnostic KL")


@contextmanager
def _numerical_context(torch):
    previous_threads = torch.get_num_threads()
    try:
        if previous_threads != 1:
            torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]), torch.no_grad():
            yield
    finally:
        if torch.get_num_threads() != previous_threads:
            torch.set_num_threads(previous_threads)


def _original_primary_model(torch, checkpoint):
    """Independent original 13-tensor architecture; no student adapter exists."""
    config, codec, transform = checkpoint["config"], checkpoint["codec"], checkpoint["input_transform"]
    options = {"device": "cpu", "dtype": torch.float32}
    class OriginalPrimary(torch.nn.Module):
        def __init__(self):
            super().__init__()
            hidden, width, embedding = config["hidden_size"], config["projection_width"], config["token_embedding_dim"]
            self.projection_down = torch.nn.Linear(384, width, **options)
            self.projection_up = torch.nn.Linear(width, 384, **options)
            self.condition = torch.nn.Linear(384, hidden, **options)
            self.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]), embedding, padding_idx=0, **options)
            self.decoder = torch.nn.GRU(embedding, hidden, batch_first=True, **options)
            self.output = torch.nn.Linear(hidden, len(codec["target_vocabulary"]), **options)
            self.register_buffer("input_mean", torch.tensor(transform["mean"], **options), persistent=False)
            self.input_scale = transform["scale"]
        def forward(self, raw384, prefix):
            normalized = (raw384 - self.input_mean) / self.input_scale
            projected = normalized + self.projection_up(torch.tanh(self.projection_down(normalized)))
            condition = torch.tanh(self.condition(projected))
            outputs, _ = self.decoder(self.target_embedding(prefix), condition.unsqueeze(0))
            return projected, condition, self.output(outputs)
    model = OriginalPrimary()
    tensors = {name: torch.tensor(value, **options) for name, value in checkpoint["model_state"].items()}
    _require(digest({name: value.tolist() for name, value in tensors.items()}) == checkpoint["weights_sha256"],
             "original primary tensors are not exact float32")
    model.load_state_dict(tensors, strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model.eval()


def _private_body_check(torch, student, original_primary, original_legacy8, initialization):
    count = 0
    for branch_name, donor in (("primary", original_primary), ("legacy8", original_legacy8)):
        original_state = donor.state_dict()
        student_state = getattr(student, branch_name).state_dict()
        _require(len(original_state) == 13, "all thirteen original decoder tensors required")
        for name, tensor in original_state.items():
            copied = student_state[name]
            _require(torch.equal(tensor, copied) and digest(tensor.tolist()) == digest(copied.tolist())
                     and tensor.untyped_storage().data_ptr() != copied.untyped_storage().data_ptr(),
                     "copied decoder tensor differs or aliases original donor")
            count += 1
    _require(count == 26, "all twenty-six inherited tensors required")
    expected = {"primary." + name: value for name, value in initialization["primary"]["model_state"].items()}
    expected.update({"legacy8." + name: value for name, value in initialization["legacy8"]["model_state"].items()})
    expected.update({"auxiliary_connector." + name: value for name, value in initialization["connector"].items()})
    _require(digest({name: value.tolist() for name, value in student.state_dict().items()}) == digest(expected),
             "private student initialization changed during replay")
    _require(all(parameter.grad is None for model in (student, original_primary, original_legacy8)
                 for parameter in model.parameters()), "replay must not create parameter gradients")


def _row_replay(torch, row, teacher_values, student_values):
    projected, condition, logits = teacher_values
    copied_projected, copied_condition, copied_logits = student_values
    for value in (*teacher_values, *student_values):
        _require(value.dtype == torch.float32 and value.device.type == "cpu" and not value.requires_grad
                 and bool(torch.isfinite(value).all()), "finite detached CPU float32 replay tensors required")
    comparisons = {}
    for name, left, right in (("projected", projected, copied_projected),
        ("condition", condition, copied_condition), ("logits", logits, copied_logits)):
        _require(tuple(left.shape) == tuple(right.shape), "copied replay tensor geometry differs")
        comparisons["exact_" + name] = bool(torch.equal(left, right) and digest(left.tolist()) == digest(right.tolist()))
        comparisons["max_" + ("logit" if name == "logits" else name) + "_error"] = float((left - right).abs().max().item())
    teacher_log_probs = torch.nn.functional.log_softmax(logits / TEMPERATURE, dim=-1)
    copied_log_probs = torch.nn.functional.log_softmax(copied_logits / TEMPERATURE, dim=-1)
    divergence = torch.nn.functional.kl_div(copied_log_probs, teacher_log_probs,
        log_target=True, reduction="none").sum(dim=-1).mean() * TEMPERATURE**2
    comparisons["diagnostic_kl_t2"] = float(divergence.item())
    _preserved(comparisons)
    exported = logits.detach().squeeze(0).tolist()
    return {**{name: deepcopy(row[name]) for name in ("id", "source_sha256", "input_sha256", "reference_sha256",
        "reference_prefix_sha256", "prefix_ids", "next_token_ids", "reference_token_mask", "kd_token_mask")},
        "batch_row_sha256": row["row_sha256"], "teacher_logits": exported,
        "teacher_logits_sha256": digest(exported), "teacher_projected_sha256": digest(projected.squeeze(0).tolist()),
        "teacher_condition_sha256": digest(condition.squeeze(0).tolist()), **comparisons}


def export_decoder_transfer_batch(initialization, batch, *, expected_donor_pins,
                                  primary_checkpoint, legacy8_checkpoint):
    """Replay original inputs and export unqualified per-head logits privately."""
    initialization, batch, pins, primary_checkpoint, legacy8_checkpoint = deepcopy(
        (initialization, batch, expected_donor_pins, primary_checkpoint, legacy8_checkpoint))
    _helper("gte_decoder_transfer_batch").inspect_decoder_transfer_batch(
        batch, initialization, expected_donor_pins=pins)
    reuse = _helper("gte_decoder_reuse")
    legacy_snapshot = _admit_originals(initialization, primary_checkpoint, legacy8_checkpoint, pins, reuse)
    total_elements = sum(len(row["prefix_ids"]) * len(head["target_vocabulary"])
                         for head in batch["heads"].values() for row in head["rows"])
    _require(total_elements <= MAX_LOGIT_ELEMENTS,
             "requested replay exceeds bounded logit export before model loading")
    implementation = _implementation()
    import torch
    with _numerical_context(torch):
        teacher_primary = _original_primary_model(torch, primary_checkpoint)
        teacher_legacy = reuse._LEGACY.load_private_legacy8_decoder_snapshot(legacy_snapshot,
            expected_source_checkpoint_sha256=pins["legacy8_checkpoint_sha256"],
            expected_source_model_state_sha256=pins["legacy8_weights_sha256"])["model"]
        student = reuse.load_dual_decoder(initialization, expected_donor_pins=pins)
        _private_body_check(torch, student, teacher_primary, teacher_legacy, initialization)
        heads = {}
        for head_name, donor_name, pin_prefix in (("primary384", "primary", "teacher384"),
                                                 ("legacy8", "legacy8", "legacy8")):
            input_head, copied = batch["heads"][head_name], getattr(student, donor_name)
            records = []
            for row in input_head["rows"]:
                values = torch.tensor([row["input_vector"]], dtype=torch.float32, device="cpu")
                prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64, device="cpu")
                if head_name == "primary384":
                    teacher_values = teacher_primary(values, prefix)
                    normalized = (values - copied.input_mean) / copied.input_scale
                    projected = copied.project(normalized)
                    condition = copied.start(projected).squeeze(0)
                    student_values = (projected, condition, copied.decode_from_condition(condition, prefix))
                else:
                    teacher_projected, teacher_logits = teacher_legacy(values, prefix)
                    teacher_condition = teacher_legacy.start(teacher_projected).squeeze(0)
                    projected, logits = copied(values, prefix)
                    condition = copied.start(projected).squeeze(0)
                    teacher_values = teacher_projected, teacher_condition, teacher_logits
                    student_values = projected, condition, logits
                records.append(_row_replay(torch, row, teacher_values, student_values))
            vocabulary_size = len(input_head["target_vocabulary"])
            heads[head_name] = {"schema": "gte-decoder-reference-prefix-head-replay/v1",
                "input_dimension": input_head["input_dimension"], "input_origin": input_head["input_origin"],
                "codec_sha256": input_head["codec_sha256"],
                "teacher_checkpoint_sha256": pins[pin_prefix + "_checkpoint_sha256"],
                "teacher_weights_sha256": pins[pin_prefix + "_weights_sha256"],
                "vocabulary_size": vocabulary_size, "hidden_size": initialization[donor_name]["config"]["hidden_size"],
                "max_target_tokens": initialization[donor_name]["config"]["max_target_tokens"],
                "selected_row_count": len(records), "total_logit_elements": sum(len(row["prefix_ids"]) * vocabulary_size for row in records),
                "prefix_policy": "reference_prefix", "distribution": "raw", "decoder_input_dtype": "float32",
                "export_dtype": "float32", "logits_detached": True, "rows": records,
                "exact_projected": True, "exact_condition": True, "exact_logits": True,
                "max_projected_error": 0., "max_condition_error": 0., "max_logit_error": 0.,
                "diagnostic_kl_temperature": TEMPERATURE, "diagnostic_kl_t2": 0.}
        _private_body_check(torch, student, teacher_primary, teacher_legacy, initialization)
    receipt = {"schema": SCHEMA, "status": "behavior_preserved_unqualified", "batch_sha256": batch["batch_sha256"],
        "initialization_representation_id": initialization["representation_id"], "donor_pins": pins,
        "heads": heads, "implementation": implementation, "numerical_profile": deepcopy(_NUMERICAL_PROFILE),
        "optimizer_steps": 0, **FLAGS}
    inspect_decoder_transfer_replay(receipt, batch, initialization=initialization, expected_donor_pins=pins)
    return receipt


__all__ = ["SCHEMA", "MAX_OUTPUT_BYTES", "export_decoder_transfer_batch", "inspect_decoder_transfer_replay", "digest"]
