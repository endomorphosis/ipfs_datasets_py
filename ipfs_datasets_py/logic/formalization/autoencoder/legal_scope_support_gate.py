"""Opt-in support-only gates on a wholly frozen support/action parent.

Matched heads see identical frozen contextual and ordered-byte features. Only
source pooling changes: global mean versus predicted modality coverage. Explicit
TRAIN support booleans supervise the new gate; proposals retain zero authority.
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

from . import legal_scope_span_decoder as span
from . import legal_scope_span_proposal as proposal
from . import legal_scope_trigger_readout as trigger
from . import legal_scope_support_action as action

CHECKPOINT_SCHEMA = "legal-scope-support-gate-checkpoint/v1"
PREDICTION_SCHEMA = "legal-scope-support-gate-result/v1"
FEATURE_PROFILE = "frozen_context64_ordered_byte33_support_pooling/v1"
FACETS, OPTIONAL, MODALITIES = span.FACETS, span.OPTIONAL, span.MODALITIES
MAX_SOURCE_CHARS, SUPPORT_THRESHOLD = span.MAX_SOURCE_CHARS, span.SUPPORT_THRESHOLD
MAX_TOKENS, MAX_TOKEN_BYTES, MAX_BATCH = span.MAX_TOKENS, span.MAX_TOKEN_BYTES, span.MAX_BATCH
_require = span._require


def _producer_pins():
    return {"implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "support_action_producer": action.producer_pins(), "feature_profile": FEATURE_PROFILE}


_IMPORTED_PINS = _producer_pins()


def producer_pins():
    _require(_producer_pins() == _IMPORTED_PINS, "support gate producer changed since import")
    return json.loads(json.dumps(_IMPORTED_PINS))


@dataclass(frozen=True, slots=True)
class SupportGateConfig:
    seed: int = 24605
    mode: str = "global"
    hidden: int = 32

    def __post_init__(self):
        _require(type(self.seed) is int and 0 <= self.seed < 2**31, "bounded seed required")
        _require(type(self.mode) is str and self.mode in ("global", "predicted_trigger"), "closed gate pooling mode required")
        _require(type(self.hidden) is int and self.hidden == 32, "fixed matched hidden width 32 required")

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), "closed support gate config required")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SupportGateExample:
    source_text: str
    supported: bool

    def __post_init__(self):
        span.tokenize_source(self.source_text)
        _require(type(self.supported) is bool, "explicit boolean source support required")


def _ordered_byte_features(donor, token_bytes, token_mask):
    """The pinned donor's 33 features before token_projection, on validated input.

    The caller first runs the original checked tensor path. Both arms compute
    this same frozen frontend; no new byte parameters or symbolic word features.
    """
    batch, tokens, width = token_bytes.shape
    byte_mask = token_bytes != 0
    byte_lengths = byte_mask.sum(-1)
    embedded = donor.byte_embedding(token_bytes).reshape(batch * tokens, width, donor.config.byte_dim).transpose(1, 2)
    mask = byte_mask.reshape(batch * tokens, 1, width)
    for convolution in donor.byte_convs:
        embedded = F.gelu(convolution(embedded)) * mask
    means = embedded.sum(-1) / byte_lengths.reshape(-1, 1).clamp_min(1)
    maxima = embedded.masked_fill(~mask, -torch.inf).amax(-1)
    maxima = torch.where(byte_lengths.reshape(-1, 1) > 0, maxima, torch.zeros_like(maxima))
    features = torch.cat((means, maxima, torch.log1p(byte_lengths.float()).reshape(-1, 1)), -1).reshape(batch, tokens, -1)
    features = features * token_mask[:, :, None]
    if tuple(features.shape) != (batch, tokens, 33) or not bool(torch.isfinite(features).all()):
        raise trigger._InvalidTriggerFeature("finite frozen ordered-byte features required")
    return features


class FrozenSupportGate(nn.Module):
    def __init__(self, parent_checkpoint_bytes, *, expected_parent_sha256, config=None):
        super().__init__()
        self.config = config if config is not None else SupportGateConfig()
        _require(type(self.config) is SupportGateConfig, "typed support gate config required")
        self.config.__post_init__()
        text, checkpoint = trigger._parse_donor(parent_checkpoint_bytes, expected_parent_sha256)
        # Strict original restoration validates every generation of weights and
        # full Adam before freezing the old residual heads. Its typed forward,
        # assertion and saver contracts are never called on this frozen object.
        self._parent, _, self.parent_steps, self.parent_action_steps = action.restore_support_action_checkpoint(checkpoint)
        donor = self._parent._parent.donor
        _require(self._parent.config.head_kind == "mlp" and self._parent.config.hidden == 32
                 and donor.config.byte_kernel == 3 and donor.config.byte_hidden == 16
                 and donor.config.token_hidden == 32, "ordered 97D MLP parent recipe required")
        self._parent_json_utf8 = text
        self.parent_sha256 = expected_parent_sha256
        self._parent_bytes = len(parent_checkpoint_bytes)
        self._original_parent_artifact = (text, expected_parent_sha256, self._parent_bytes,
                                          self.parent_steps, self.parent_action_steps)
        for parameter in self._parent.parameters():
            parameter.requires_grad_(False)
            parameter.grad = None
        self._parent_state = {name: value.detach().clone() for name, value in self._parent.state_dict().items()}
        self._parent_modes = {name: module.training for name, module in self._parent.named_modules()}
        self._parent_flags = {name: p.requires_grad for name, p in self._parent.named_parameters()}
        self._parent_configs = self._configs()
        self._parent_artifacts = self._artifacts()
        self._config = self.config.to_dict()
        self.feature_width = 97
        cpu = {"device": "cpu", "dtype": torch.float32}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.config.seed)
            self.gate = nn.Sequential(nn.Linear(self.feature_width, self.config.hidden, **cpu),
                                      nn.Tanh(), nn.Linear(self.config.hidden, 1, **cpu))
            nn.init.zeros_(self.gate[2].weight)
            nn.init.zeros_(self.gate[2].bias)
        self._initial_gate_state = {name: value.detach().clone() for name, value in self.gate.state_dict().items()}
        self._assert_parent()

    def _configs(self):
        return {name: module.config.to_dict() for name, module in self._parent.named_modules() if hasattr(module, "config")}

    def _artifacts(self):
        parent, middle = self._parent, self._parent._parent
        return {"support_action": (parent._parent_json_utf8, parent.parent_sha256, parent._parent_bytes,
                                   parent.parent_steps, parent._original_parent_artifact),
                "trigger": (middle._donor_json_utf8, middle.donor_sha256, middle._donor_bytes, middle.donor_steps)}

    @property
    def parent_checkpoint(self):
        """Defensive parsed exact parent, including complete historical moments."""
        return trigger._parse_donor(self._parent_json_utf8.encode("utf-8"), self.parent_sha256)[1]

    def train(self, mode=True):
        _require(type(mode) is bool, "boolean model mode required")
        self.training = mode
        self.gate.train(mode)
        return self

    def _assert_parent(self):
        _require((self._parent_json_utf8, self.parent_sha256, self._parent_bytes, self.parent_steps, self.parent_action_steps)
                 == self._original_parent_artifact, "frozen parent artifact provenance changed")
        _require(type(self.config) is SupportGateConfig and self.config.to_dict() == self._config and self.feature_width == 97,
                 "support gate recipe changed")
        _require(self._configs() == self._parent_configs and self._artifacts() == self._parent_artifacts,
                 "frozen parent recipe or nested artifact changed")
        _require(self._parent_modes == {n: m.training for n, m in self._parent.named_modules()}, "frozen parent mode changed")
        state = self._parent.state_dict()
        _require(set(state) == set(self._parent_state) and all(v.device.type == "cpu" and v.dtype == torch.float32
                 and torch.equal(v, self._parent_state[n]) for n, v in state.items()), "frozen parent tensor changed")
        _require(self._parent_flags == {n: p.requires_grad for n, p in self._parent.named_parameters()}
                 and all(not p.requires_grad and p.grad is None for p in self._parent.parameters()), "frozen parent gradient custody changed")
        _require(all(m.training is self.training for m in self.gate.modules()) and all(p.requires_grad and p.device.type == "cpu"
                 and p.dtype == torch.float32 and bool(torch.isfinite(p).all()) for p in self.gate.parameters()),
                 "finite CPU float32 support gate required")

    def forward(self, token_bytes, token_mask):
        """Original five-logit structure; only support changes after gate fit."""
        producer_pins()
        self._assert_parent()
        with torch.no_grad():
            middle = self._parent._parent
            output, encoded, pooled = trigger._donor_tensor_path(middle.donor, token_bytes, token_mask)
            class_feature = trigger._predicted_trigger_feature(encoded, token_mask,
                output["start"]["modality"], output["end"]["modality"])
            output["modality"] = output["modality"] + middle.adapter(class_feature)
            output["support"] = output["support"] + self._parent.heads["support"](pooled).squeeze(-1)
            for key, name in (("start", "action_start"), ("end", "action_end")):
                output[key]["action"] = (output[key]["action"] + self._parent.heads[name](encoded).squeeze(-1)).masked_fill(~token_mask, -10000.0)
            bundle = torch.cat((encoded, _ordered_byte_features(middle.donor, token_bytes, token_mask)), -1)
            if self.config.mode == "global":
                feature = (bundle * token_mask[:, :, None]).sum(1) / token_mask.sum(1)[:, None]
            else:
                feature = trigger._predicted_trigger_feature(bundle, token_mask,
                    output["start"]["modality"], output["end"]["modality"])
            if tuple(feature.shape) != (token_bytes.shape[0], 97) or not bool(torch.isfinite(feature).all()):
                raise trigger._InvalidTriggerFeature("finite matched support features required")
        output["support"] = output["support"] + self.gate(feature).squeeze(-1)
        return output


def make_support_gate_optimizer(model, learning_rate=0.003, weight_decay=0.0):
    _require(type(model) is FrozenSupportGate, "typed support gate model required")
    model._assert_parent()
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "bounded finite learning rate required")
    _require(type(weight_decay) in (int, float) and math.isfinite(weight_decay) and 0 <= weight_decay <= 1,
             "bounded finite weight decay required")
    return torch.optim.AdamW(model.gate.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay), foreach=False)


def train_support_gate_step(model, optimizer, examples, gradient_clip=5.0):
    pins = producer_pins()
    _require(type(model) is FrozenSupportGate and type(examples) is list and 1 <= len(examples) <= MAX_BATCH
             and all(type(e) is SupportGateExample for e in examples), "bounded typed TRAIN support examples required")
    model._assert_parent()
    span._optimizer_settings(model.gate, optimizer)
    _require(type(gradient_clip) in (int, float) and math.isfinite(gradient_clip) and 0 < gradient_clip <= 100,
             "bounded finite gradient clip required")
    for example in examples: example.__post_init__()
    batch, _ = span._encoded_sources([e.source_text for e in examples])
    support = torch.tensor([float(e.supported) for e in examples], dtype=torch.float32)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    output = model(*batch)
    loss = F.binary_cross_entropy_with_logits(output["support"], support)
    _require(bool(torch.isfinite(loss)), "nonfinite support gate loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.gate.parameters(), float(gradient_clip), error_if_nonfinite=True)
    optimizer.step()
    model._assert_parent()
    _require(all(bool(torch.isfinite(v).all()) for s in optimizer.state.values()
                 for v in s.values() if isinstance(v, torch.Tensor)), "nonfinite gate Adam state")
    _require(producer_pins() == pins, "producer changed during training")
    positive = int(support.bool().sum())
    return {"loss": float(loss.detach()), "support_loss": float(loss.detach()), "gradient_norm": float(norm),
            "supported_examples": positive, "unsupported_examples": len(examples)-positive,
            "encoded_examples": len(examples), "optimizer_step_executed": True,
            "support_optimizer_step_executed": True}


def _profile(config):
    return {"input_fields": ["source_text", "condition_attachment", "expected_source_sha256"],
            "model_input_fields": ["source_text"], "feature_profile": FEATURE_PROFILE, "feature_width": 97,
            "pooling": config.mode, "hidden": config.hidden, "ordered_byte_features": "frozen_conv3_mean_max_log_length",
            "all_parent_parameters_frozen": True, "old_Adam_continued": False, "optimizer_parameters": "new_support_gate_only",
            "train_targets": ["explicit_support_bool"], "loss": "BCE_support_all", "support_optimizer_steps": "all_batches",
            "action_loss": False, "class_loss": False, "structural_parameters_updated": False,
            "target_spans_at_inference": False, "lexicon_or_symbolic_validator": False,
            "condition_attachment_origin": "explicit_caller_premise", "output_wire": proposal.PREDICTION_SCHEMA,
            "interpretation_profile": proposal.INTERPRETATION_PROFILE, "support_threshold": SUPPORT_THRESHOLD,
            "max_source_chars": MAX_SOURCE_CHARS, "max_tokens": MAX_TOKENS, "max_token_bytes": MAX_TOKEN_BYTES,
            "max_batch": MAX_BATCH, "facets": list(FACETS), "nullable_facets": list(OPTIONAL),
            "initial_residual": "zero_final_projection"}


def save_support_gate_checkpoint(model, optimizer, *, steps):
    pins = producer_pins()
    _require(type(model) is FrozenSupportGate, "typed support gate model required")
    model._assert_parent()
    settings = span._optimizer_settings(model.gate, optimizer)
    state = optimizer.state_dict()["state"]
    trigger._progress(state, list(model.gate.parameters()), steps)
    if steps == 0:
        _require(all(torch.equal(value, model._initial_gate_state[name]) for name, value in model.gate.state_dict().items()),
                 "zero progress requires the exact seeded cold gate")
    raw = model._parent_json_utf8.encode("utf-8")
    _require(len(raw) == model._parent_bytes and sha256(raw).hexdigest() == model.parent_sha256, "exact parent artifact custody changed")
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "producer": pins, "config": model.config.to_dict(),
                  "profile": _profile(model.config), "steps": steps, "model_training": model.training,
                  "parent": {"json_utf8": model._parent_json_utf8, "sha256": model.parent_sha256, "bytes": model._parent_bytes},
                  "gate_state": {k: span._tensor_record(v) for k, v in model.gate.state_dict().items()},
                  "optimizer": {"kind": "AdamW", "settings": settings,
                    "state": {str(i): {k: span._tensor_record(v) for k, v in record.items()} for i, record in state.items()}}}
    checkpoint["checkpoint_sha256"] = sha256(span._canonical(checkpoint)).hexdigest()
    _require(producer_pins() == pins, "producer changed during checkpoint save")
    return checkpoint


def restore_support_gate_checkpoint(checkpoint):
    _require(type(checkpoint) is dict and set(checkpoint) == {"schema", "producer", "config", "profile", "steps",
             "model_training", "parent", "gate_state", "optimizer", "checkpoint_sha256"}, "closed support gate checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["producer"] == producer_pins(), "checkpoint schema/producer mismatch")
    _require(type(checkpoint["model_training"]) is bool, "explicit model mode required")
    seal = sha256(span._canonical({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest()
    _require(type(checkpoint["checkpoint_sha256"]) is str and seal == checkpoint["checkpoint_sha256"], "checkpoint seal mismatch")
    config = SupportGateConfig.from_dict(checkpoint["config"])
    parent = checkpoint["parent"]
    _require(type(parent) is dict and set(parent) == {"json_utf8", "sha256", "bytes"}
             and type(parent["json_utf8"]) is str and type(parent["bytes"]) is int, "closed exact parent artifact required")
    try: raw = parent["json_utf8"].encode("utf-8")
    except UnicodeError as error: raise ValueError("ordinary UTF8 parent required") from error
    _require(len(raw) == parent["bytes"], "parent byte count mismatch")
    model = FrozenSupportGate(raw, expected_parent_sha256=parent["sha256"], config=config)
    _require(span._canonical(checkpoint["profile"]) == span._canonical(_profile(config)), "checkpoint source recipe mismatch")
    records = checkpoint["gate_state"]; expected = model.gate.state_dict()
    _require(type(records) is dict and set(records) == set(expected), "gate parameter inventory mismatch")
    weights = {k: span._restore_tensor(records[k], v.shape) for k, v in expected.items()}
    saved = checkpoint["optimizer"]
    _require(type(saved) is dict and set(saved) == {"kind", "settings", "state"} and saved["kind"] == "AdamW", "closed AdamW required")
    _require(type(saved["settings"]) is dict and set(saved["settings"]) == {"learning_rate", "weight_decay"}, "closed AdamW settings required")
    optimizer = make_support_gate_optimizer(model, **saved["settings"])
    parameters = list(model.gate.parameters())
    _require(type(saved["state"]) is dict and set(saved["state"]) <= {str(i) for i in range(len(parameters))}, "Adam inventory mismatch")
    restored = {}
    for key, record in saved["state"].items():
        _require(type(record) is dict and set(record) == {"step", "exp_avg", "exp_avg_sq"}, "closed Adam moments required")
        i = int(key)
        restored[i] = {k: span._restore_tensor(v, () if k == "step" else parameters[i].shape) for k, v in record.items()}
    trigger._progress(restored, parameters, checkpoint["steps"])
    model.gate.load_state_dict(weights, strict=True)
    model.train(checkpoint["model_training"])
    state = optimizer.state_dict(); state["state"] = restored
    optimizer.load_state_dict(state)
    _require(save_support_gate_checkpoint(model, optimizer, steps=checkpoint["steps"]) == checkpoint,
             "checkpoint differs after exact restoration")
    return model, optimizer, checkpoint["steps"]


def predict_support_gate(model, source_text, condition_attachment, *, expected_source_sha256):
    """Predict source endpoints; attachment is always an explicit caller premise."""
    result = {"schema": PREDICTION_SCHEMA, "status": "blocked", "prediction": None, "proposal": None,
              "blockers": [], "raw_prediction": None, "target_access": False, "targets_used_at_inference": False,
              "source_semantics_verified": False, "proof_ready": False, "proof_authority": False,
              "qualified": False, "accepted": False, "formalized": False, "formal_output": None,
              "condition_attachment_origin": "explicit_caller_premise", "model_executed": False,
              "modality_logits": None}
    _require(type(model) is FrozenSupportGate, "typed support gate model required")
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
    result.update(parent_sha256=model.parent_sha256, gate_feature_mode=model.config.mode)
    try:
        batch, rows = span._encoded_sources([source_text])
    except ValueError as error:
        return {**result, "blockers": ["source_profile_unsupported"], "diagnostic": str(error)}
    training = model.training
    model.eval()
    try:
        with torch.no_grad():
            output = model(*batch)
    except trigger._InvalidTriggerFeature as error:
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
