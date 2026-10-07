"""Opt-in support/action residuals on an entirely frozen trigger parent.

Linear and tanh-MLP heads share source features and zero initial residuals.
Only explicit TRAIN support/action anchors supervise new heads. Class, optional
presence and all other facets remain frozen; transport retains zero authority.
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

CHECKPOINT_SCHEMA = "legal-scope-support-action-checkpoint/v1"
PREDICTION_SCHEMA = "legal-scope-support-action-result/v1"
FEATURE_PROFILE = "frozen_mean_encoded_support_and_token_action_residual/v1"
HEADS = ("support", "action_start", "action_end")
FACETS, OPTIONAL, MODALITIES = span.FACETS, span.OPTIONAL, span.MODALITIES
MAX_SOURCE_CHARS, SUPPORT_THRESHOLD = span.MAX_SOURCE_CHARS, span.SUPPORT_THRESHOLD
MAX_TOKENS, MAX_TOKEN_BYTES, MAX_BATCH = span.MAX_TOKENS, span.MAX_TOKEN_BYTES, span.MAX_BATCH
_require = span._require


def _producer_pins():
    return {"implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "trigger_producer": trigger.producer_pins(), "feature_profile": FEATURE_PROFILE}


_IMPORTED_PINS = _producer_pins()


def producer_pins():
    _require(_producer_pins() == _IMPORTED_PINS, "support/action producer changed since import")
    return json.loads(json.dumps(_IMPORTED_PINS))


@dataclass(frozen=True, slots=True)
class SupportActionConfig:
    seed: int = 24604
    head_kind: str = "linear"
    hidden: int = 32

    def __post_init__(self):
        _require(type(self.seed) is int and 0 <= self.seed < 2**31, "bounded seed required")
        _require(type(self.head_kind) is str and self.head_kind in ("linear", "mlp"), "closed residual head kind required")
        _require(type(self.hidden) is int and 8 <= self.hidden <= 128, "bounded MLP hidden width required")

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), "closed support/action config required")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SupportActionExample:
    source_text: str
    supported: bool
    action_span: list[int] | None = None

    def __post_init__(self):
        tokens = span.tokenize_source(self.source_text)
        _require(type(self.supported) is bool, "explicit boolean source support required")
        if not self.supported:
            _require(self.action_span is None, "unsupported source cannot carry an action target")
            return
        pair = self.action_span
        _require(type(pair) is list and len(pair) == 2 and all(type(v) is int for v in pair),
                 "explicit positive action occurrence pair required")
        _require(0 <= pair[0] < pair[1] <= len(self.source_text)
                 and pair[0] in {t.start for t in tokens} and pair[1] in {t.end for t in tokens},
                 "TRAIN action anchor must use complete source token boundaries")


class FrozenSupportAction(nn.Module):
    def __init__(self, parent_checkpoint_bytes, *, expected_parent_sha256, config=None):
        super().__init__()
        self.config = config if config is not None else SupportActionConfig()
        _require(type(self.config) is SupportActionConfig, "typed support/action config required")
        self.config.__post_init__()
        text, checkpoint = trigger._parse_donor(parent_checkpoint_bytes, expected_parent_sha256)
        # Validate the entire parent and both generations of full Adam BEFORE
        # freezing its class adapter. Its old typed contract is never called on
        # the frozen instance afterward; exact original bytes carry provenance.
        self._parent, _, self.parent_steps = trigger.restore_trigger_readout_checkpoint(checkpoint)
        _require(self._parent.config.mode == "predicted_trigger", "selected predicted-trigger parent required")
        self._parent_json_utf8 = text
        self.parent_sha256 = expected_parent_sha256
        self._parent_bytes = len(parent_checkpoint_bytes)
        self._original_parent_artifact = (text, expected_parent_sha256, self._parent_bytes, self.parent_steps)
        for parameter in self._parent.parameters():
            parameter.requires_grad_(False)
            parameter.grad = None
        self._parent_state = {name: tensor.detach().clone() for name, tensor in self._parent.state_dict().items()}
        self._parent_modes = {name: module.training for name, module in self._parent.named_modules()}
        self._parent_flags = {name: p.requires_grad for name, p in self._parent.named_parameters()}
        self._parent_config = self._parent.config.to_dict()
        self._donor_config = self._parent.donor.config.to_dict()
        self._config = self.config.to_dict()
        self.feature_width = 2 * self._parent.donor.config.token_hidden
        cpu = {"device": "cpu", "dtype": torch.float32}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(self.config.seed)
            def make_head():
                if self.config.head_kind == "linear":
                    head = nn.Linear(self.feature_width, 1, **cpu)
                    final = head
                else:
                    head = nn.Sequential(nn.Linear(self.feature_width, self.config.hidden, **cpu),
                                         nn.Tanh(), nn.Linear(self.config.hidden, 1, **cpu))
                    final = head[2]
                nn.init.zeros_(final.weight)
                nn.init.zeros_(final.bias)
                return head
            self.heads = nn.ModuleDict({name: make_head() for name in HEADS})
        self._assert_parent()

    @property
    def parent_checkpoint(self):
        """Defensive parsed original artifact, including complete old moments."""
        return trigger._parse_donor(self._parent_json_utf8.encode("utf-8"), self.parent_sha256)[1]

    def train(self, mode=True):
        _require(type(mode) is bool, "boolean model mode required")
        self.training = mode
        self.heads.train(mode)
        return self

    def _assert_parent(self):
        _require((self._parent_json_utf8, self.parent_sha256, self._parent_bytes, self.parent_steps)
                 == self._original_parent_artifact, "frozen parent artifact provenance changed")
        _require(type(self.config) is SupportActionConfig and self.config.to_dict() == self._config,
                 "support/action recipe changed")
        _require(self._parent.config.to_dict() == self._parent_config
                 and self._parent.donor.config.to_dict() == self._donor_config, "frozen parent recipe changed")
        _require(self._parent_modes == {n: m.training for n, m in self._parent.named_modules()}, "frozen parent mode changed")
        state = self._parent.state_dict()
        _require(set(state) == set(self._parent_state) and all(v.device.type == "cpu" and v.dtype == torch.float32
                 and torch.equal(v, self._parent_state[n]) for n, v in state.items()), "frozen parent tensor changed")
        _require(self._parent_flags == {n: p.requires_grad for n, p in self._parent.named_parameters()}
                 and all(not p.requires_grad and p.grad is None for p in self._parent.parameters()), "frozen parent gradient custody changed")
        _require(all(m.training is self.training for m in self.heads.modules()) and all(p.requires_grad and p.device.type == "cpu"
                 and p.dtype == torch.float32 and bool(torch.isfinite(p).all()) for p in self.heads.parameters()),
                 "finite CPU float32 residual heads required")
        _require(self.feature_width == 2 * self._parent.donor.config.token_hidden, "feature width changed")

    def forward(self, token_bytes, token_mask):
        """Five source-logit keys; only support and action endpoints vary."""
        producer_pins()
        self._assert_parent()
        with torch.no_grad():
            output, encoded, pooled = trigger._donor_tensor_path(self._parent.donor, token_bytes, token_mask)
            feature = trigger._predicted_trigger_feature(encoded, token_mask,
                output["start"]["modality"], output["end"]["modality"])
            output["modality"] = output["modality"] + self._parent.adapter(feature)
        output["support"] = output["support"] + self.heads["support"](pooled).squeeze(-1)
        for key, head in (("start", "action_start"), ("end", "action_end")):
            output[key]["action"] = (output[key]["action"] + self.heads[head](encoded).squeeze(-1)).masked_fill(~token_mask, -10000.0)
        return output


def make_support_action_optimizer(model, learning_rate=0.003, weight_decay=0.0):
    _require(type(model) is FrozenSupportAction, "typed support/action model required")
    model._assert_parent()
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "bounded finite learning rate required")
    _require(type(weight_decay) in (int, float) and math.isfinite(weight_decay) and 0 <= weight_decay <= 1,
             "bounded finite weight decay required")
    return torch.optim.AdamW(model.heads.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay), foreach=False)


def _action_labels(examples, rows):
    """Validate and index explicit TRAIN anchors; never infer an action."""
    labels = {key: torch.full((len(examples),), -100, dtype=torch.long) for key in ("start", "end")}
    for i, (example, tokens) in enumerate(zip(examples, rows, strict=True)):
        if not example.supported:
            continue
        labels["start"][i] = {t.start: j for j, t in enumerate(tokens)}[example.action_span[0]]
        labels["end"][i] = {t.end: j for j, t in enumerate(tokens)}[example.action_span[1]]
    return labels


def train_support_action_step(model, optimizer, examples, gradient_clip=5.0):
    pins = producer_pins()
    _require(type(model) is FrozenSupportAction and type(examples) is list and 1 <= len(examples) <= MAX_BATCH
             and all(type(e) is SupportActionExample for e in examples), "bounded typed TRAIN examples required")
    model._assert_parent()
    span._optimizer_settings(model.heads, optimizer)
    _require(type(gradient_clip) in (int, float) and math.isfinite(gradient_clip) and 0 < gradient_clip <= 100,
             "bounded finite gradient clip required")
    for example in examples: example.__post_init__()
    batch, rows = span._encoded_sources([e.source_text for e in examples])
    labels = _action_labels(examples, rows)
    support = torch.tensor([float(e.supported) for e in examples], dtype=torch.float32)
    positive = support.bool()
    model.train()
    optimizer.zero_grad(set_to_none=True)
    output = model(*batch)
    support_loss = F.binary_cross_entropy_with_logits(output["support"], support)
    if bool(positive.any()):
        action_loss = .5 * sum(F.cross_entropy(output[key]["action"][positive], labels[key][positive]) for key in ("start", "end"))
    else:
        # No ignored-target CE and no action graph: existing moments stay idle.
        action_loss = output["support"].new_zeros(())
    loss = support_loss + action_loss
    _require(bool(torch.isfinite(loss)), "nonfinite support/action loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.heads.parameters(), float(gradient_clip), error_if_nonfinite=True)
    optimizer.step()
    model._assert_parent()
    _require(all(bool(torch.isfinite(v).all()) for s in optimizer.state.values()
                 for v in s.values() if isinstance(v, torch.Tensor)), "nonfinite residual Adam state")
    _require(producer_pins() == pins, "producer changed during training")
    return {"loss": float(loss.detach()), "support_loss": float(support_loss.detach()),
            "action_loss": float(action_loss.detach()), "gradient_norm": float(norm),
            "supported_examples": int(positive.sum()), "unsupported_examples": int((~positive).sum()),
            "encoded_examples": len(examples), "optimizer_step_executed": True,
            "action_optimizer_step_executed": bool(positive.any())}


def _profile(config, feature_width):
    return {"input_fields": ["source_text", "condition_attachment", "expected_source_sha256"],
            "model_input_fields": ["source_text"], "feature_profile": FEATURE_PROFILE, "feature_width": feature_width,
            "head_kind": config.head_kind, "hidden_used": config.hidden if config.head_kind == "mlp" else None,
            "all_parent_parameters_frozen": True, "old_Adam_continued": False, "optimizer_parameters": "new_residual_heads_only",
            "train_targets": ["explicit_support_bool", "positive_source_action_pair"], "unsupported_action_target": False,
            "loss": "BCE_support_all+.5*(CE_action_start_positive+CE_action_end_positive)",
            "action_optimizer_steps": "positive_batches_only", "support_optimizer_steps": "all_batches",
            "class_loss": False, "class_parameters_updated": False, "target_spans_at_inference": False,
            "condition_attachment_origin": "explicit_caller_premise", "output_wire": proposal.PREDICTION_SCHEMA,
            "interpretation_profile": proposal.INTERPRETATION_PROFILE, "support_threshold": SUPPORT_THRESHOLD,
            "max_source_chars": MAX_SOURCE_CHARS, "max_tokens": MAX_TOKENS, "max_token_bytes": MAX_TOKEN_BYTES,
            "max_batch": MAX_BATCH, "facets": list(FACETS), "nullable_facets": list(OPTIONAL),
            "initial_residual": "zero_final_projection"}


def _progress(model, state, steps, action_steps):
    _require(type(steps) is int and type(action_steps) is int and 0 <= action_steps <= steps <= 10_000_000,
             "bounded support/action integer progress required")
    named = list(model.heads.named_parameters())
    counts = {i: steps if name.startswith("support.") else action_steps for i, (name, _) in enumerate(named)}
    _require(set(state) == {i for i, count in counts.items() if count}, "residual Adam inventory mismatch")
    for i, record in state.items():
        _require(type(record) is dict and set(record) == {"step", "exp_avg", "exp_avg_sq"}, "closed residual Adam state required")
        step = record["step"]
        _require(isinstance(step, torch.Tensor) and step.device.type == "cpu" and step.dtype == torch.float32
                 and step.shape == torch.Size([]) and bool(torch.isfinite(step)) and float(step) == counts[i],
                 "residual Adam per-head progress mismatch")
        shape = named[i][1].shape
        _require(all(isinstance(record[k], torch.Tensor) and record[k].device.type == "cpu" and record[k].dtype == torch.float32
                 and record[k].shape == shape and bool(torch.isfinite(record[k]).all()) for k in ("exp_avg", "exp_avg_sq"))
                 and bool((record["exp_avg_sq"] >= 0).all()), "Adam moments shape/variance invalid")


def save_support_action_checkpoint(model, optimizer, *, steps, action_steps):
    pins = producer_pins()
    _require(type(model) is FrozenSupportAction, "typed support/action model required")
    model._assert_parent()
    settings = span._optimizer_settings(model.heads, optimizer)
    state = optimizer.state_dict()["state"]
    _progress(model, state, steps, action_steps)
    raw = model._parent_json_utf8.encode("utf-8")
    _require(len(raw) == model._parent_bytes and sha256(raw).hexdigest() == model.parent_sha256, "exact parent artifact custody changed")
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "producer": pins, "config": model.config.to_dict(),
                  "profile": _profile(model.config, model.feature_width), "steps": steps, "action_steps": action_steps,
                  "model_training": model.training,
                  "parent": {"json_utf8": model._parent_json_utf8, "sha256": model.parent_sha256, "bytes": model._parent_bytes},
                  "head_state": {k: span._tensor_record(v) for k, v in model.heads.state_dict().items()},
                  "optimizer": {"kind": "AdamW", "settings": settings,
                    "state": {str(i): {k: span._tensor_record(v) for k, v in record.items()} for i, record in state.items()}}}
    checkpoint["checkpoint_sha256"] = sha256(span._canonical(checkpoint)).hexdigest()
    _require(producer_pins() == pins, "producer changed during checkpoint save")
    return checkpoint


def restore_support_action_checkpoint(checkpoint):
    _require(type(checkpoint) is dict and set(checkpoint) == {"schema", "producer", "config", "profile", "steps", "action_steps",
             "model_training", "parent", "head_state", "optimizer", "checkpoint_sha256"}, "closed support/action checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["producer"] == producer_pins(), "checkpoint schema/producer mismatch")
    _require(type(checkpoint["model_training"]) is bool, "explicit model mode required")
    seal = sha256(span._canonical({k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest()
    _require(type(checkpoint["checkpoint_sha256"]) is str and seal == checkpoint["checkpoint_sha256"], "checkpoint seal mismatch")
    config = SupportActionConfig.from_dict(checkpoint["config"])
    parent = checkpoint["parent"]
    _require(type(parent) is dict and set(parent) == {"json_utf8", "sha256", "bytes"}
             and type(parent["json_utf8"]) is str and type(parent["bytes"]) is int, "closed exact parent artifact required")
    try: raw = parent["json_utf8"].encode("utf-8")
    except UnicodeError as error: raise ValueError("ordinary UTF8 parent required") from error
    _require(len(raw) == parent["bytes"], "parent byte count mismatch")
    model = FrozenSupportAction(raw, expected_parent_sha256=parent["sha256"], config=config)
    _require(span._canonical(checkpoint["profile"]) == span._canonical(_profile(config, model.feature_width)), "checkpoint source recipe mismatch")
    records = checkpoint["head_state"]; expected = model.heads.state_dict()
    _require(type(records) is dict and set(records) == set(expected), "head parameter inventory mismatch")
    weights = {k: span._restore_tensor(records[k], v.shape) for k, v in expected.items()}
    saved = checkpoint["optimizer"]
    _require(type(saved) is dict and set(saved) == {"kind", "settings", "state"} and saved["kind"] == "AdamW", "closed AdamW required")
    _require(type(saved["settings"]) is dict and set(saved["settings"]) == {"learning_rate", "weight_decay"}, "closed AdamW settings required")
    optimizer = make_support_action_optimizer(model, **saved["settings"])
    parameters = list(model.heads.parameters())
    _require(type(saved["state"]) is dict and set(saved["state"]) <= {str(i) for i in range(len(parameters))}, "Adam inventory mismatch")
    restored = {}
    for key, record in saved["state"].items():
        _require(type(record) is dict and set(record) == {"step", "exp_avg", "exp_avg_sq"}, "closed Adam moments required")
        i = int(key)
        restored[i] = {k: span._restore_tensor(v, () if k == "step" else parameters[i].shape) for k, v in record.items()}
    _progress(model, restored, checkpoint["steps"], checkpoint["action_steps"])
    model.heads.load_state_dict(weights, strict=True)
    model.train(checkpoint["model_training"])
    state = optimizer.state_dict(); state["state"] = restored
    optimizer.load_state_dict(state)
    _require(save_support_action_checkpoint(model, optimizer, steps=checkpoint["steps"], action_steps=checkpoint["action_steps"]) == checkpoint,
             "checkpoint differs after exact restoration")
    return model, optimizer, checkpoint["steps"], checkpoint["action_steps"]


def predict_support_action(model, source_text, condition_attachment, *, expected_source_sha256):
    """Predict source endpoints; attachment is always an explicit caller premise."""
    result = {"schema": PREDICTION_SCHEMA, "status": "blocked", "prediction": None, "proposal": None,
              "blockers": [], "raw_prediction": None, "target_access": False, "targets_used_at_inference": False,
              "source_semantics_verified": False, "proof_ready": False, "proof_authority": False,
              "qualified": False, "accepted": False, "formalized": False, "formal_output": None,
              "condition_attachment_origin": "explicit_caller_premise", "model_executed": False,
              "modality_logits": None}
    _require(type(model) is FrozenSupportAction, "typed support/action model required")
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
    result.update(parent_sha256=model.parent_sha256, residual_head_kind=model.config.head_kind)
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
