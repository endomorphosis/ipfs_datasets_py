"""Frozen source-span donor with a source-only residual modality readout.

The two arms differ only in the feature: global mean or soft predicted trigger.
Only the adapter is fitted. Caller attachment and zero-authority proposal custody
remain with the existing owner; neither labels nor target coordinates enter it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from . import legal_scope_span_decoder as span
from . import legal_scope_span_proposal as proposal

CHECKPOINT_SCHEMA = "legal-scope-trigger-readout-checkpoint/v1"
PREDICTION_SCHEMA = "legal-scope-trigger-readout-result/v1"
FEATURE_PROFILE = "frozen_encoded_global_or_predicted_interval_coverage/v1"
FACETS, OPTIONAL, MODALITIES = span.FACETS, span.OPTIONAL, span.MODALITIES
MAX_BATCH, MAX_TOKENS, MAX_TOKEN_BYTES = span.MAX_BATCH, span.MAX_TOKENS, span.MAX_TOKEN_BYTES
MAX_SOURCE_CHARS, SUPPORT_THRESHOLD = span.MAX_SOURCE_CHARS, span.SUPPORT_THRESHOLD
_require = span._require


def _producer_pins():
    return {"implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "donor_producer": span.producer_pins(), "feature_profile": FEATURE_PROFILE}


_IMPORTED_PINS = _producer_pins()


def producer_pins():
    _require(_producer_pins() == _IMPORTED_PINS, "trigger readout producer changed since import")
    # Return a fresh nested value rather than exposing the cached dependency pins.
    return json.loads(json.dumps(_IMPORTED_PINS))


@dataclass(frozen=True, slots=True)
class TriggerReadoutConfig:
    seed: int = 24603
    mode: str = "global"
    hidden: int = 64

    def __post_init__(self):
        _require(type(self.seed) is int and 0 <= self.seed < 2**31, "bounded seed required")
        _require(type(self.mode) is str and self.mode in ("global", "predicted_trigger"), "closed feature mode required")
        _require(type(self.hidden) is int and 8 <= self.hidden <= 128, "bounded adapter hidden width required")

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), "closed readout config required")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TriggerReadoutExample:
    source_text: str
    supported: bool
    modality: str | None = None

    def __post_init__(self):
        span.tokenize_source(self.source_text)
        _require(type(self.supported) is bool, "explicit boolean source support required")
        _require((type(self.modality) is str and self.modality in MODALITIES) if self.supported
                 else self.modality is None, "explicit positive class and no unsupported class required")


def _closed_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _parse_donor(raw, expected_sha256):
    _require(type(raw) is bytes and 0 < len(raw) <= span.MAX_CHECKPOINT_BYTES, "bounded exact donor bytes required")
    _require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
             "externally expected donor SHA256 required")
    _require(sha256(raw).hexdigest() == expected_sha256, "donor digest mismatch")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_closed_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite donor JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("ordinary UTF8 donor JSON required") from error
    return text, value


class FrozenTriggerReadout(nn.Module):
    def __init__(self, donor_checkpoint_bytes, *, expected_donor_sha256, config=None):
        super().__init__()
        self.config = config if config is not None else TriggerReadoutConfig()
        _require(type(self.config) is TriggerReadoutConfig, "typed trigger readout config required")
        self.config.__post_init__()
        text, checkpoint = _parse_donor(donor_checkpoint_bytes, expected_donor_sha256)
        # Restore validates the complete donor model AND its Adam state. Donor
        # moments are retained only in the immutable artifact, never continued.
        self.donor, _, self.donor_steps = span.restore_scope_span_checkpoint(checkpoint)
        self._donor_json_utf8 = text
        self.donor_sha256 = expected_donor_sha256
        self._donor_bytes = len(donor_checkpoint_bytes)
        self._donor_training = self.donor.training
        self._donor_modes = {name: module.training for name, module in self.donor.named_modules()}
        self._donor_config = self.donor.config.to_dict()
        self._config = self.config.to_dict()
        for parameter in self.donor.parameters():
            parameter.requires_grad_(False)
            parameter.grad = None
        self._frozen_state = {key: value.detach().clone() for key, value in self.donor.state_dict().items()}
        cpu = {"device": "cpu", "dtype": torch.float32}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.config.seed)
            self.adapter = nn.Sequential(nn.Linear(2 * self.donor.config.token_hidden, self.config.hidden, **cpu),
                                         nn.Tanh(), nn.Linear(self.config.hidden, 3, **cpu))
            nn.init.zeros_(self.adapter[2].weight)
            nn.init.zeros_(self.adapter[2].bias)
        self._assert_frozen()

    @property
    def donor_checkpoint(self):
        return _parse_donor(self._donor_json_utf8.encode("utf-8"), self.donor_sha256)[1]

    def train(self, mode=True):
        _require(type(mode) is bool, "boolean model mode required")
        self.training = mode
        # Do not recursively mutate the original donor mode.
        self.adapter.train(mode)
        return self

    def _assert_frozen(self):
        self.config.__post_init__()
        _require(self.config.to_dict() == self._config and self.donor.config.to_dict() == self._donor_config,
                 "frozen model recipe changed")
        _require(self.donor.training is self._donor_training and self._donor_modes == {
            name: module.training for name, module in self.donor.named_modules()}, "donor mode changed")
        _require(self.adapter.training is self.training, "adapter mode changed")
        state = self.donor.state_dict()
        _require(set(state) == set(self._frozen_state) and all(
            value.device.type == "cpu" and value.dtype == torch.float32
            and torch.equal(value, self._frozen_state[key]) for key, value in state.items()), "frozen donor state changed")
        _require(all(not p.requires_grad and p.grad is None for p in self.donor.parameters()), "donor gradient custody changed")
        _require(all(p.requires_grad and p.device.type == "cpu" and p.dtype == torch.float32
                     and bool(torch.isfinite(p).all()) for p in self.adapter.parameters()), "finite CPU float32 adapter required")

    def forward(self, token_bytes, token_mask):
        """Same five donor output keys; only modality has a residual adapter.

        Public tensor inference provides source-only logits for diagnostics. The
        private donor tensor path faithfully preserves its ordered byte encoder.
        """
        producer_pins()
        self._assert_frozen()
        with torch.no_grad():
            output, encoded, pooled = _donor_tensor_path(self.donor, token_bytes, token_mask)
            feature = pooled if self.config.mode == "global" else _predicted_trigger_feature(
                encoded, token_mask, output["start"]["modality"], output["end"]["modality"])
        residual = self.adapter(feature)
        output["modality"] = output["modality"] + residual
        return output


class _InvalidTriggerFeature(ValueError):
    """Reject invalid interval arithmetic without repairing the distribution."""


def _predicted_trigger_feature(encoded, token_mask, start_logits, end_logits):
    """Expected interval coverage P(S<=t)*P(E>=t), normalized on real tokens."""
    if not (bool(torch.isfinite(start_logits).all()) and bool(torch.isfinite(end_logits).all())):
        raise _InvalidTriggerFeature("finite predicted trigger logits required")
    starts = start_logits.masked_fill(~token_mask, -torch.inf).softmax(-1)
    ends = end_logits.masked_fill(~token_mask, -torch.inf).softmax(-1)
    weights = starts.cumsum(-1) * ends.flip(-1).cumsum(-1).flip(-1)
    weights = weights * token_mask
    normalizer = weights.sum(-1, keepdim=True)
    if not (bool(torch.isfinite(normalizer).all()) and bool((normalizer > 0).all())):
        raise _InvalidTriggerFeature("positive finite coverage required")
    return (encoded * (weights / normalizer)[:, :, None]).sum(1)


def make_trigger_readout_optimizer(model, learning_rate=0.003, weight_decay=0.0):
    _require(type(model) is FrozenTriggerReadout, "typed trigger readout model required")
    model._assert_frozen()
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "bounded finite learning rate required")
    _require(type(weight_decay) in (int, float) and math.isfinite(weight_decay) and 0 <= weight_decay <= 1,
             "bounded finite weight decay required")
    return torch.optim.AdamW(model.adapter.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay), foreach=False)


def train_trigger_readout_step(model, optimizer, examples, gradient_clip=5.0):
    pins = producer_pins()
    _require(type(model) is FrozenTriggerReadout and type(examples) is list and 1 <= len(examples) <= MAX_BATCH
             and all(type(e) is TriggerReadoutExample for e in examples), "bounded typed TRAIN examples required")
    model._assert_frozen()
    span._optimizer_settings(model.adapter, optimizer)
    _require(type(gradient_clip) in (int, float) and math.isfinite(gradient_clip) and 0 < gradient_clip <= 100,
             "bounded finite gradient clipping required")
    for example in examples:
        example.__post_init__()
    positive = [e for e in examples if e.supported]
    optimizer.zero_grad(set_to_none=True)
    if not positive:
        # No model invocation or AdamW step; existing moments and weight decay idle.
        return {"loss": 0.0, "modality_loss": 0.0, "gradient_norm": 0.0, "supported_examples": 0,
                "unsupported_examples": len(examples), "optimizer_step_executed": False}
    batch, _ = span._encoded_sources([e.source_text for e in positive])
    labels = torch.tensor([MODALITIES.index(e.modality) for e in positive], dtype=torch.long)
    model.train()
    output = model(*batch)
    loss = F.cross_entropy(output["modality"], labels)
    _require(bool(torch.isfinite(loss)), "nonfinite adapter training loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.adapter.parameters(), float(gradient_clip), error_if_nonfinite=True)
    optimizer.step()
    model._assert_frozen()
    _require(all(bool(torch.isfinite(v).all()) for s in optimizer.state.values()
                 for v in s.values() if isinstance(v, torch.Tensor)), "nonfinite updated adapter Adam state")
    _require(producer_pins() == pins, "producer changed during training")
    return {"loss": float(loss.detach()), "modality_loss": float(loss.detach()), "gradient_norm": float(norm),
            "supported_examples": len(positive), "unsupported_examples": len(examples) - len(positive),
            "optimizer_step_executed": True}


def _profile(config):
    return {"input_fields": ["source_text", "condition_attachment", "expected_source_sha256"],
            "model_input_fields": ["source_text"], "feature_profile": FEATURE_PROFILE, "feature_mode": config.mode,
            "trigger_weights": "normalize_real_tokens(P(S<=t)*P(E>=t))", "donor_frozen": True,
            "donor_adam_continued": False, "optimizer_parameters": "adapter_only",
            "train_positive_target": "explicit_O_P_F", "unsupported_class_target": False,
            "target_spans_at_inference": False, "target_parser": False,
            "condition_attachment_origin": "explicit_caller_premise", "output_wire": proposal.PREDICTION_SCHEMA,
            "interpretation_profile": proposal.INTERPRETATION_PROFILE, "support_threshold": SUPPORT_THRESHOLD,
            "max_source_chars": MAX_SOURCE_CHARS, "max_tokens": MAX_TOKENS, "max_token_bytes": MAX_TOKEN_BYTES,
            "max_batch": MAX_BATCH, "facets": list(FACETS), "nullable_facets": list(OPTIONAL),
            "residual": "seeded_linear_tanh_linear_zero_final_projection"}


def _progress(state, parameters, steps):
    _require(type(steps) is int and 0 <= steps <= 10_000_000, "bounded integer adapter progress required")
    _require(set(state) == (set(range(len(parameters))) if steps else set()), "adapter Adam inventory mismatch")
    for i, record in state.items():
        _require(type(record) is dict and set(record) == {"step", "exp_avg", "exp_avg_sq"}, "closed adapter Adam state required")
        step = record["step"]
        _require(isinstance(step, torch.Tensor) and step.device.type == "cpu" and step.dtype == torch.float32
                 and step.shape == torch.Size([]) and bool(torch.isfinite(step)) and float(step) == steps,
                 "adapter Adam progress mismatch")
        _require(all(isinstance(record[k], torch.Tensor) and record[k].device.type == "cpu"
                     and record[k].dtype == torch.float32 and record[k].shape == parameters[i].shape
                     and bool(torch.isfinite(record[k]).all()) for k in ("exp_avg", "exp_avg_sq"))
                 and bool((record["exp_avg_sq"] >= 0).all()), "adapter Adam moments shape/variance invalid")


def save_trigger_readout_checkpoint(model, optimizer, *, steps):
    pins = producer_pins()
    _require(type(model) is FrozenTriggerReadout, "typed trigger readout model required")
    model._assert_frozen()
    settings = span._optimizer_settings(model.adapter, optimizer)
    state = optimizer.state_dict()["state"]
    _progress(state, list(model.adapter.parameters()), steps)
    donor_raw = model._donor_json_utf8.encode("utf-8")
    _require(len(donor_raw) == model._donor_bytes and sha256(donor_raw).hexdigest() == model.donor_sha256,
             "embedded donor custody mismatch")
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "producer": pins, "config": model.config.to_dict(),
                  "profile": _profile(model.config), "steps": steps, "model_training": model.training,
                  "donor": {"json_utf8": model._donor_json_utf8, "sha256": model.donor_sha256, "bytes": model._donor_bytes},
                  "adapter_state": {k: span._tensor_record(v) for k, v in model.adapter.state_dict().items()},
                  "optimizer": {"kind": "AdamW", "settings": settings,
                                "state": {str(i): {k: span._tensor_record(v) for k, v in record.items()}
                                          for i, record in state.items()}}}
    checkpoint["checkpoint_sha256"] = sha256(span._canonical(checkpoint)).hexdigest()
    _require(producer_pins() == pins, "producer changed during checkpoint save")
    return checkpoint


def restore_trigger_readout_checkpoint(checkpoint):
    _require(type(checkpoint) is dict and set(checkpoint) == {
        "schema", "producer", "config", "profile", "steps", "model_training", "donor", "adapter_state", "optimizer", "checkpoint_sha256"},
        "closed trigger readout checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["producer"] == producer_pins(),
             "checkpoint schema/producer mismatch")
    _require(type(checkpoint["model_training"]) is bool, "explicit checkpoint model mode required")
    seal = sha256(span._canonical({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest()
    _require(type(checkpoint["checkpoint_sha256"]) is str and seal == checkpoint["checkpoint_sha256"], "checkpoint seal mismatch")
    config = TriggerReadoutConfig.from_dict(checkpoint["config"])
    _require(span._canonical(checkpoint["profile"]) == span._canonical(_profile(config)), "checkpoint source recipe mismatch")
    donor = checkpoint["donor"]
    _require(type(donor) is dict and set(donor) == {"json_utf8", "sha256", "bytes"}
             and type(donor["json_utf8"]) is str and type(donor["bytes"]) is int, "closed exact donor artifact required")
    try:
        raw = donor["json_utf8"].encode("utf-8")
    except UnicodeError as error:
        raise ValueError("UTF8 donor required") from error
    _require(len(raw) == donor["bytes"], "donor byte count mismatch")
    model = FrozenTriggerReadout(raw, expected_donor_sha256=donor["sha256"], config=config)
    records = checkpoint["adapter_state"]
    expected = model.adapter.state_dict()
    _require(type(records) is dict and set(records) == set(expected), "adapter parameter inventory mismatch")
    weights = {k: span._restore_tensor(records[k], v.shape) for k, v in expected.items()}
    saved = checkpoint["optimizer"]
    _require(type(saved) is dict and set(saved) == {"kind", "settings", "state"} and saved["kind"] == "AdamW",
             "closed adapter AdamW checkpoint required")
    _require(type(saved["settings"]) is dict and set(saved["settings"]) == {"learning_rate", "weight_decay"}, "closed AdamW settings required")
    optimizer = make_trigger_readout_optimizer(model, **saved["settings"])
    parameters = list(model.adapter.parameters())
    _require(type(saved["state"]) is dict and set(saved["state"]) <= {str(i) for i in range(len(parameters))}, "Adam state inventory mismatch")
    restored = {}
    for key, values in saved["state"].items():
        _require(type(values) is dict and set(values) == {"step", "exp_avg", "exp_avg_sq"}, "closed Adam moments required")
        i = int(key)
        restored[i] = {k: span._restore_tensor(v, () if k == "step" else parameters[i].shape) for k, v in values.items()}
    _progress(restored, parameters, checkpoint["steps"])
    model.adapter.load_state_dict(weights, strict=True)
    model.train(checkpoint["model_training"])
    state = optimizer.state_dict()
    state["state"] = restored
    optimizer.load_state_dict(state)
    _require(save_trigger_readout_checkpoint(model, optimizer, steps=checkpoint["steps"]) == checkpoint,
             "checkpoint differs after exact restoration")
    return model, optimizer, checkpoint["steps"]


# Faithful tensor path from the pinned donor; no mutation or forward hooks.
def _donor_tensor_path(donor, token_bytes, token_mask):
    _require(isinstance(token_bytes, torch.Tensor) and isinstance(token_mask, torch.Tensor)
             and token_bytes.device.type == token_mask.device.type == "cpu"
             and token_bytes.dtype == torch.long and token_mask.dtype == torch.bool,
             "CPU typed source tensors required")
    _require(token_bytes.ndim == 3 and token_mask.shape == token_bytes.shape[:2], "source tensor shape mismatch")
    batch, tokens, width = token_bytes.shape
    _require(1 <= batch <= MAX_BATCH and 1 <= tokens <= MAX_TOKENS and 1 <= width <= MAX_TOKEN_BYTES,
             "source tensor bounds exceeded")
    _require(bool(((token_bytes >= 0) & (token_bytes <= 256)).all()), "fixed byte alphabet required")
    lengths = token_mask.sum(1)
    _require(bool((lengths > 0).all()) and torch.equal(torch.arange(tokens)[None, :] < lengths[:, None], token_mask),
             "contiguous nonempty token padding required")
    byte_mask = token_bytes != 0
    byte_lengths = byte_mask.sum(-1)
    _require(torch.equal(byte_lengths > 0, token_mask)
             and torch.equal(torch.arange(width)[None, None, :] < byte_lengths[:, :, None], byte_mask),
             "contiguous byte padding required")
    embedded = donor.byte_embedding(token_bytes).reshape(batch * tokens, width, donor.config.byte_dim).transpose(1, 2)
    mask = byte_mask.reshape(batch * tokens, 1, width)
    for convolution in donor.byte_convs:
        embedded = F.gelu(convolution(embedded)) * mask
    means = embedded.sum(-1) / byte_lengths.reshape(-1, 1).clamp_min(1)
    maxima = embedded.masked_fill(~mask, -torch.inf).amax(-1)
    maxima = torch.where(byte_lengths.reshape(-1, 1) > 0, maxima, torch.zeros_like(maxima))
    features = torch.cat((means, maxima, torch.log1p(byte_lengths.float()).reshape(-1, 1)), -1)
    token_features = torch.tanh(donor.token_projection(features.reshape(batch, tokens, -1)))
    packed = pack_padded_sequence(token_features, lengths.cpu(), batch_first=True, enforce_sorted=False)
    encoded, _ = donor.token_gru(packed)
    encoded, _ = pad_packed_sequence(encoded, batch_first=True, total_length=tokens)
    pooled = (encoded * token_mask[:, :, None]).sum(1) / lengths[:, None]
    global_state = torch.tanh(donor.global_projection(pooled))
    output = {"support": donor.support_head(global_state).squeeze(-1), "modality": donor.modality_head(global_state),
            "presence": donor.presence_head(global_state).reshape(batch, 2, 2),
            **{key: {facet: head(encoded).squeeze(-1).masked_fill(~token_mask, -10000.0)
                     for facet, head in heads.items()}
               for key, heads in (("start", donor.start_heads), ("end", donor.end_heads))}}
    return output, encoded, pooled


def predict_trigger_readout(model, source_text, condition_attachment, *, expected_source_sha256):
    """Predict source endpoints; attachment is always an explicit caller premise."""
    result = {"schema": PREDICTION_SCHEMA, "status": "blocked", "prediction": None, "proposal": None,
              "blockers": [], "raw_prediction": None, "target_access": False, "targets_used_at_inference": False,
              "source_semantics_verified": False, "proof_ready": False, "proof_authority": False,
              "qualified": False, "accepted": False, "formalized": False, "formal_output": None,
              "condition_attachment_origin": "explicit_caller_premise", "model_executed": False,
              "modality_logits": None}
    _require(type(model) is FrozenTriggerReadout, "typed trigger readout model required")
    _require(type(expected_source_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256) is not None,
             "externally expected source SHA256 required")
    _require(type(source_text) is str and len(source_text) <= MAX_SOURCE_CHARS, "bounded source text required")
    try:
        raw_source = source_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF8 source required") from error
    _require(sha256(raw_source).hexdigest() == expected_source_sha256, "source digest mismatch")
    if type(condition_attachment) is not str or condition_attachment not in ("rule", "statement"):
        return {**result, "status": "abstained", "blockers": ["explicit_caller_condition_attachment_required"]}
    pins = producer_pins()
    result.update(donor_sha256=model.donor_sha256, adapter_feature_mode=model.config.mode)
    try:
        batch, rows = span._encoded_sources([source_text])
    except ValueError as error:
        return {**result, "blockers": ["source_profile_unsupported"], "diagnostic": str(error)}
    training = model.training
    model.eval()
    try:
        with torch.no_grad():
            output = model(*batch)
    except _InvalidTriggerFeature as error:
        return {**result, "model_executed": True, "blockers": ["invalid_predicted_trigger_coverage"],
                "diagnostic": str(error)}
    finally:
        model.train(training)
    result["model_executed"] = True
    tokens = rows[0]
    shapes = {"support": (1,), "modality": (1, 3), "presence": (1, 2, 2)}
    def tensor_valid(value, shape):
        return (isinstance(value, torch.Tensor) and value.device.type == "cpu"
                and value.dtype == torch.float32 and tuple(value.shape) == shape)
    if (type(output) is not dict or set(output) != set(shapes) | {"start", "end"}
            or any(not isinstance(output[k], torch.Tensor) or output[k].device.type != "cpu"
                   or output[k].dtype != torch.float32 or tuple(output[k].shape) != shape for k, shape in shapes.items())
            or any(type(output[key]) is not dict or set(output[key]) != set(FACETS)
                   or any(not tensor_valid(value, (1, len(tokens))) for value in output[key].values())
                   for key in ("start", "end"))):
        return {**result, "blockers": ["malformed_model_prediction"]}
    tensors = [output[key] for key in shapes] + [output[key][facet] for key in ("start", "end") for facet in FACETS]
    if not all(bool(torch.isfinite(value).all()) for value in tensors):
        return {**result, "blockers": ["nonfinite_model_prediction"]}
    result["modality_logits"] = output["modality"][0].tolist()
    probability = float(output["support"].sigmoid()[0])
    result.update(support_probability=probability, support_threshold=SUPPORT_THRESHOLD)
    raw = {"modality": MODALITIES[int(output["modality"][0].argmax())],
           "presence": {facet: bool(output["presence"][0, j].argmax()) for j, facet in enumerate(OPTIONAL)},
           "token_spans": {facet: [int(output["start"][facet][0].argmax()), int(output["end"][facet][0].argmax())]
                           for facet in FACETS}}
    result["raw_prediction"] = raw
    if probability < SUPPORT_THRESHOLD:
        return {**result, "status": "abstained", "blockers": ["learned_source_unsupported"]}
    prediction = {"schema": proposal.PREDICTION_SCHEMA, "interpretation_profile": proposal.INTERPRETATION_PROFILE,
                  "modality": raw["modality"], "spans": {}, "condition_attachment": None}
    try:
        for facet in FACETS:
            if facet in OPTIONAL and not raw["presence"][facet]:
                prediction["spans"][facet] = None
                continue
            left, right = raw["token_spans"][facet]
            _require(0 <= left <= right < len(tokens), "predicted span order/bounds invalid")
            prediction["spans"][facet] = [tokens[left].start, tokens[right].end]
        if prediction["spans"]["condition"] is not None:
            prediction["condition_attachment"] = condition_attachment
        transported = proposal.propose_scope_from_spans(source_text, prediction,
            expected_source_sha256=expected_source_sha256)
    except ValueError as error:
        return {**result, "blockers": ["predicted_occurrence_proposal_invalid"], "diagnostic": str(error)}
    _require(producer_pins() == pins and all(v == 0 for v in transported["masks"].values()),
             "producer changed or proposal gained authority")
    return {**result, "status": "predicted", "prediction": prediction, "proposal": transported,
            "masks": dict(transported["masks"]), "blockers": list(transported["blockers"])}
