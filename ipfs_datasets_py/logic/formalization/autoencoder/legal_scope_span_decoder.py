"""Experimental source-only single-rule occurrence head with learned refusal.

Targets supervise fitting only. Inference copies predicted source coordinates
and an explicit caller attachment into the existing unreviewed proposal owner.
No parser, target lookup, vector encoder, formula lowering or admission runs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from . import legal_scope_span_proposal as proposal
from ...legal_ir import canonical_statement_scope as scope

CHECKPOINT_SCHEMA = "legal-scope-span-decoder-checkpoint/v1"
PREDICTION_SCHEMA = "legal-scope-span-decoder-result/v1"
TOKENIZER_PROFILE = "unicode_word_or_punctuation_utf8_offsets/v1"
BYTE_ENCODER_PROFILE = "masked_two_conv_gelu_mean_max/v1"
FACETS = ("modality", "actor", "action", "object", "condition")
OPTIONAL = ("object", "condition")
MODALITIES = ("O", "P", "F")
SUPPORT_THRESHOLD = 0.5
MAX_SOURCE_CHARS = 8192
MAX_TOKENS = 96
MAX_TOKEN_BYTES = 64
MAX_BATCH = 64
MAX_CHECKPOINT_BYTES = 32_000_000
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_STRUCTURAL = ("modality_head.", "presence_head.", "start_heads.", "end_heads.")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _producer_pins():
    return {"implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "proposal_sha256": sha256(Path(proposal.__file__).read_bytes()).hexdigest(),
            "scope_sha256": sha256(Path(scope.__file__).read_bytes()).hexdigest(),
            "torch_version": str(torch.__version__), "tokenizer_profile": TOKENIZER_PROFILE}


_IMPORTED_PINS = _producer_pins()


def producer_pins():
    _require(_producer_pins() == _IMPORTED_PINS, "scope decoder producer changed since import")
    return dict(_IMPORTED_PINS)


@dataclass(frozen=True, slots=True)
class ScopeSpanDecoderConfig:
    seed: int = 0
    byte_kernel: int = 3
    byte_dim: int = 8
    byte_hidden: int = 16
    token_dim: int = 32
    token_hidden: int = 32
    head_hidden: int = 64

    def __post_init__(self):
        _require(type(self.byte_kernel) is int and self.byte_kernel in (1, 3), "byte kernel must be 1 or 3")
        for key, low, high in (("seed", 0, 2**31 - 1), ("byte_dim", 4, 32), ("byte_hidden", 4, 64),
                               ("token_dim", 8, 96), ("token_hidden", 8, 64), ("head_hidden", 8, 128)):
            value = getattr(self, key)
            _require(type(value) is int and low <= value <= high, "invalid bounded config field: " + key)

    def to_dict(self):
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        _require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), "closed scope config required")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SourceToken:
    text: str
    start: int
    end: int


def tokenize_source(source_text):
    """Preserve generic Unicode token offsets and complete bounded UTF8 bytes."""
    _require(type(source_text) is str and 0 < len(source_text) <= MAX_SOURCE_CHARS
             and source_text.strip() and "\x00" not in source_text, "bounded nonempty source required")
    try:
        source_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF8 source required") from error
    tokens = tuple(SourceToken(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(source_text))
    _require(1 <= len(tokens) <= MAX_TOKENS, "source token bounds exceeded; no truncation")
    _require(all(1 <= len(token.text.encode("utf-8")) <= MAX_TOKEN_BYTES for token in tokens),
             "token byte bounds exceeded; no truncation")
    return tokens


@dataclass(frozen=True, slots=True)
class ScopeSpanExample:
    source_text: str
    supported: bool
    target: dict[str, Any] | None = None

    def __post_init__(self):
        tokenize_source(self.source_text)
        _require(type(self.supported) is bool, "explicit boolean source support required")
        _require(type(self.target) is dict if self.supported else self.target is None,
                 "supported examples need explicit targets; unsupported examples cannot carry structural targets")


class ScopeSpanDecoder(nn.Module):
    def __init__(self, config=None):
        super().__init__()
        self.config = config if config is not None else ScopeSpanDecoderConfig()
        _require(type(self.config) is ScopeSpanDecoderConfig, "typed scope config required")
        cfg = self.config
        cfg.__post_init__()
        cpu = {"device": "cpu", "dtype": torch.float32}
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(cfg.seed)
            self.byte_embedding = nn.Embedding(257, cfg.byte_dim, padding_idx=0, **cpu)
            self.byte_convs = nn.ModuleList((nn.Conv1d(cfg.byte_dim, cfg.byte_hidden, cfg.byte_kernel,
                                                     padding=cfg.byte_kernel // 2, **cpu),
                                            nn.Conv1d(cfg.byte_hidden, cfg.byte_hidden, cfg.byte_kernel,
                                                     padding=cfg.byte_kernel // 2, **cpu)))
            self.token_projection = nn.Linear(2 * cfg.byte_hidden + 1, cfg.token_dim, **cpu)
            self.token_gru = nn.GRU(cfg.token_dim, cfg.token_hidden, batch_first=True, bidirectional=True, **cpu)
            width = 2 * cfg.token_hidden
            self.global_projection = nn.Linear(width, cfg.head_hidden, **cpu)
            self.support_head = nn.Linear(cfg.head_hidden, 1, **cpu)
            self.modality_head = nn.Linear(cfg.head_hidden, 3, **cpu)
            self.presence_head = nn.Linear(cfg.head_hidden, 4, **cpu)
            self.start_heads = nn.ModuleDict({facet: nn.Linear(width, 1, **cpu) for facet in FACETS})
            self.end_heads = nn.ModuleDict({facet: nn.Linear(width, 1, **cpu) for facet in FACETS})

    def forward(self, token_bytes, token_mask):
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
        embedded = self.byte_embedding(token_bytes).reshape(batch * tokens, width, self.config.byte_dim).transpose(1, 2)
        mask = byte_mask.reshape(batch * tokens, 1, width)
        for convolution in self.byte_convs:
            embedded = F.gelu(convolution(embedded)) * mask
        means = embedded.sum(-1) / byte_lengths.reshape(-1, 1).clamp_min(1)
        maxima = embedded.masked_fill(~mask, -torch.inf).amax(-1)
        maxima = torch.where(byte_lengths.reshape(-1, 1) > 0, maxima, torch.zeros_like(maxima))
        features = torch.cat((means, maxima, torch.log1p(byte_lengths.float()).reshape(-1, 1)), -1)
        token_features = torch.tanh(self.token_projection(features.reshape(batch, tokens, -1)))
        packed = pack_padded_sequence(token_features, lengths.cpu(), batch_first=True, enforce_sorted=False)
        encoded, _ = self.token_gru(packed)
        encoded, _ = pad_packed_sequence(encoded, batch_first=True, total_length=tokens)
        pooled = (encoded * token_mask[:, :, None]).sum(1) / lengths[:, None]
        global_state = torch.tanh(self.global_projection(pooled))
        return {"support": self.support_head(global_state).squeeze(-1), "modality": self.modality_head(global_state),
                "presence": self.presence_head(global_state).reshape(batch, 2, 2),
                **{key: {facet: head(encoded).squeeze(-1).masked_fill(~token_mask, -10000.0)
                         for facet, head in heads.items()}
                   for key, heads in (("start", self.start_heads), ("end", self.end_heads))}}


def _encoded_sources(sources):
    _require(type(sources) is list and 1 <= len(sources) <= MAX_BATCH, "bounded source batch required")
    rows = [tokenize_source(source) for source in sources]
    token_count = max(map(len, rows))
    byte_count = max(len(token.text.encode("utf-8")) for row in rows for token in row)
    values = torch.zeros((len(rows), token_count, byte_count), dtype=torch.long)
    mask = torch.zeros((len(rows), token_count), dtype=torch.bool)
    for i, row in enumerate(rows):
        for j, token in enumerate(row):
            raw = token.text.encode("utf-8")
            values[i, j, :len(raw)] = torch.tensor([byte + 1 for byte in raw], dtype=torch.long)
            mask[i, j] = True
    return (values, mask), rows


def _labels(examples, rows):
    labels = {key: torch.full((len(examples), 5), -100, dtype=torch.long) for key in ("start", "end")}
    labels.update(support=torch.tensor([float(e.supported) for e in examples], dtype=torch.float32),
                  modality=torch.full((len(examples),), -100, dtype=torch.long),
                  presence=torch.full((len(examples), 2), -100, dtype=torch.long))
    for i, (example, tokens) in enumerate(zip(examples, rows, strict=True)):
        if not example.supported:
            continue
        # This validation checks explicit TRAIN anchors. It never infers labels.
        proposal.propose_scope_from_spans(example.source_text, example.target,
            expected_source_sha256=sha256(example.source_text.encode("utf-8")).hexdigest())
        starts = {token.start: j for j, token in enumerate(tokens)}
        ends = {token.end: j for j, token in enumerate(tokens)}
        labels["modality"][i] = MODALITIES.index(example.target["modality"])
        for j, facet in enumerate(FACETS):
            span = example.target["spans"][facet]
            if facet in OPTIONAL:
                labels["presence"][i, OPTIONAL.index(facet)] = int(span is not None)
            if span is not None:
                labels["start"][i, j] = starts[span[0]]
                labels["end"][i, j] = ends[span[1]]
    return labels


def make_scope_span_optimizer(model, learning_rate=0.003, weight_decay=0.0):
    _require(type(model) is ScopeSpanDecoder, "typed scope model required")
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "bounded finite learning rate required")
    _require(type(weight_decay) in (int, float) and math.isfinite(weight_decay) and 0 <= weight_decay <= 1,
             "bounded finite weight decay required")
    return torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay), foreach=False)


def _optimizer_settings(model, optimizer):
    _require(type(optimizer) is torch.optim.AdamW and len(optimizer.param_groups) == 1, "one-group AdamW required")
    group = optimizer.param_groups[0]
    _require(all(p.device.type == "cpu" and p.dtype == torch.float32 for p in model.parameters()), "CPU float32 model required")
    _require([id(p) for p in group["params"]] == [id(p) for p in model.parameters()], "optimizer parameter identity mismatch")
    _require(type(group["lr"]) in (float, int) and math.isfinite(group["lr"]) and 0 < group["lr"] <= .1
             and type(group["weight_decay"]) in (float, int) and math.isfinite(group["weight_decay"])
             and 0 <= group["weight_decay"] <= 1, "invalid optimizer settings")
    _require(group["betas"] == (.9, .999) and group["eps"] == 1e-8 and not group["amsgrad"]
             and not group["maximize"] and not group["capturable"] and not group["differentiable"]
             and group["foreach"] is False and group.get("fused") is None, "unsupported optimizer backend")
    return {"learning_rate": group["lr"], "weight_decay": group["weight_decay"]}


def train_scope_span_step(model, optimizer, examples, gradient_clip=5.0):
    pins = producer_pins()
    _require(type(model) is ScopeSpanDecoder and type(examples) is list and 1 <= len(examples) <= MAX_BATCH
             and all(type(e) is ScopeSpanExample for e in examples), "bounded typed TRAIN examples required")
    _optimizer_settings(model, optimizer)
    _require(type(gradient_clip) in (int, float) and math.isfinite(gradient_clip) and 0 < gradient_clip <= 100,
             "bounded finite gradient clipping required")
    for example in examples:
        example.__post_init__()
    batch, rows = _encoded_sources([e.source_text for e in examples])
    labels = _labels(examples, rows)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    outputs = model(*batch)
    positive = labels["support"].bool()
    losses = {"support": F.binary_cross_entropy_with_logits(outputs["support"], labels["support"])}
    for key in ("modality", "presence"):
        if bool(positive.any()):
            logits = outputs[key][positive]
            targets = labels[key][positive]
            losses[key] = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1), ignore_index=-100)
        else:
            # Inactive heads get no graph: existing Adam moments cannot move them.
            losses[key] = outputs["support"].new_zeros(())
    for j, facet in enumerate(FACETS):
        active = positive & (labels["start"][:, j] != -100)
        if bool(active.any()):
            losses[facet + "_span"] = .5 * sum(F.cross_entropy(outputs[key][facet][active], labels[key][active, j])
                                               for key in ("start", "end"))
        else:
            losses[facet + "_span"] = outputs["support"].new_zeros(())
    loss = sum(losses.values())
    _require(bool(torch.isfinite(loss)), "nonfinite training loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), float(gradient_clip), error_if_nonfinite=True)
    optimizer.step()
    _require(all(bool(torch.isfinite(p).all()) for p in model.parameters()), "nonfinite updated model")
    _require(all(bool(torch.isfinite(value).all()) for state in optimizer.state.values()
                 for value in state.values() if isinstance(value, torch.Tensor)), "nonfinite updated Adam state")
    _require(producer_pins() == pins, "producer changed during training")
    return {"loss": float(loss.detach()), "gradient_norm": float(norm),
            "supported_examples": int(positive.sum()), "unsupported_examples": int((~positive).sum()),
            **{key + "_loss": float(value.detach()) for key, value in losses.items()}}


def predict_scope_span_decoder(model, source_text, condition_attachment, *, expected_source_sha256):
    """Predict source endpoints; attachment is always an explicit caller premise."""
    result = {"schema": PREDICTION_SCHEMA, "status": "blocked", "prediction": None, "proposal": None,
              "blockers": [], "raw_prediction": None, "target_access": False, "targets_used_at_inference": False,
              "source_semantics_verified": False, "proof_ready": False, "proof_authority": False,
              "qualified": False, "accepted": False, "formalized": False, "formal_output": None,
              "condition_attachment_origin": "explicit_caller_premise", "model_executed": False}
    _require(type(model) is ScopeSpanDecoder, "typed scope model required")
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
    try:
        batch, rows = _encoded_sources([source_text])
    except ValueError as error:
        return {**result, "blockers": ["source_profile_unsupported"], "diagnostic": str(error)}
    training = model.training
    model.eval()
    try:
        with torch.no_grad():
            output = model(*batch)
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


def _canonical(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("finite ordinary JSON checkpoint required") from error
    _require(len(raw) <= MAX_CHECKPOINT_BYTES, "checkpoint byte bound exceeded")
    return raw


def _tensor_record(tensor):
    _require(tensor.device.type == "cpu" and tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all()),
             "finite CPU float32 checkpoint tensors required")
    return {"shape": list(tensor.shape), "dtype": "float32", "values": tensor.detach().reshape(-1).tolist()}


def _restore_tensor(record, shape):
    _require(type(record) is dict and set(record) == {"shape", "dtype", "values"}, "closed tensor record required")
    _require(type(record["shape"]) is list and all(type(v) is int for v in record["shape"])
             and record["shape"] == list(shape) and record["dtype"] == "float32", "tensor shape/dtype mismatch")
    values = record["values"]
    _require(type(values) is list and len(values) == math.prod(shape)
             and all(type(v) is float and math.isfinite(v) for v in values), "finite float tensor values required")
    tensor = torch.tensor(values, dtype=torch.float32).reshape(shape)
    _require(bool(torch.isfinite(tensor).all()), "checkpoint values overflow float32")
    return tensor


def _progress(model, state, steps):
    _require(type(steps) is int and 0 <= steps <= 10_000_000, "bounded integer progress required")
    if steps == 0:
        _require(not state, "zero progress requires empty Adam state")
        return
    names = [name for name, _ in model.named_parameters()]
    shared = {i for i, name in enumerate(names) if not name.startswith(_STRUCTURAL)}
    structural = set(range(len(names))) - shared
    _require(set(state) <= set(range(len(names))) and shared <= set(state), "Adam parameter progress inventory mismatch")
    structural_steps = {}
    for i, record in state.items():
        _require(type(record) is dict and set(record) == {"step", "exp_avg", "exp_avg_sq"}, "closed Adam state required")
        step = record["step"]
        _require(isinstance(step, torch.Tensor) and step.device.type == "cpu" and step.dtype == torch.float32
                 and step.shape == torch.Size([]) and bool(torch.isfinite(step)), "finite scalar Adam step required")
        count = float(step)
        _require(count.is_integer() and 1 <= count <= steps, "Adam step outside declared progress")
        if i in shared:
            _require(count == steps, "shared Adam progress mismatch")
        else:
            structural_steps[names[i]] = count
    # Each optional endpoint is used only by positive batches where it exists.
    # Required endpoints, class and presence heads advance on every positive batch.
    required = {i for i in structural if not names[i].startswith(tuple(
        key + "." + facet + "." for key in ("start_heads", "end_heads") for facet in OPTIONAL))}
    _require(set(state) - shared >= required or not structural_steps, "missing required structural Adam state")
    required_counts = {structural_steps[names[i]] for i in required if i in state}
    _require(len(required_counts) <= 1, "required structural Adam progress mismatch")
    positive_steps = next(iter(required_counts), 0)
    for facet in OPTIONAL:
        members = {i for i in structural if names[i].startswith(("start_heads." + facet + ".", "end_heads." + facet + "."))}
        seen = members & set(state)
        _require(not seen or seen == members, "partial optional endpoint Adam inventory")
        counts = {structural_steps[names[i]] for i in seen}
        _require(len(counts) <= 1 and all(count <= positive_steps for count in counts), "optional endpoint Adam progress mismatch")


def _profile(config):
    return {"input_fields": ["source_text", "condition_attachment", "expected_source_sha256"],
            "model_input_fields": ["source_text"], "condition_attachment_origin": "explicit_caller_premise",
            "output_wire": proposal.PREDICTION_SCHEMA, "interpretation_profile": proposal.INTERPRETATION_PROFILE,
            "tokenizer": TOKENIZER_PROFILE, "byte_encoder": BYTE_ENCODER_PROFILE, "byte_kernel": config.byte_kernel,
            "alphabet_size": 257, "max_source_chars": MAX_SOURCE_CHARS, "max_tokens": MAX_TOKENS,
            "max_token_bytes": MAX_TOKEN_BYTES, "max_batch": MAX_BATCH, "facets": list(FACETS),
            "nullable_facets": list(OPTIONAL), "support_threshold": SUPPORT_THRESHOLD,
            "unsupported_structural_targets": False, "numeric_vector_conditioning": False}


def save_scope_span_checkpoint(model, optimizer, *, steps):
    pins = producer_pins()
    _require(type(model) is ScopeSpanDecoder, "typed scope model required")
    settings = _optimizer_settings(model, optimizer)
    state = optimizer.state_dict()["state"]
    _progress(model, state, steps)
    parameters = list(model.parameters())
    records = {}
    for i, values in state.items():
        _require(values["exp_avg"].shape == values["exp_avg_sq"].shape == parameters[i].shape
                 and bool((values["exp_avg_sq"] >= 0).all()), "Adam moments shape/variance invalid")
        records[str(i)] = {key: _tensor_record(value) for key, value in values.items()}
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "producer": pins, "config": model.config.to_dict(),
                  "profile": _profile(model.config), "steps": steps, "model_training": model.training,
                  "model_state": {key: _tensor_record(value) for key, value in model.state_dict().items()},
                  "optimizer": {"kind": "AdamW", "settings": settings, "state": records}}
    checkpoint["checkpoint_sha256"] = sha256(_canonical(checkpoint)).hexdigest()
    _require(producer_pins() == pins, "producer changed during checkpoint save")
    return checkpoint


def restore_scope_span_checkpoint(checkpoint):
    _require(type(checkpoint) is dict and set(checkpoint) == {
        "schema", "producer", "config", "profile", "steps", "model_training", "model_state", "optimizer", "checkpoint_sha256"},
        "closed scope checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["producer"] == producer_pins(),
             "checkpoint schema/producer mismatch")
    _require(type(checkpoint["model_training"]) is bool, "explicit checkpoint model mode required")
    seal = sha256(_canonical({key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"})).hexdigest()
    _require(type(checkpoint["checkpoint_sha256"]) is str and seal == checkpoint["checkpoint_sha256"], "checkpoint seal mismatch")
    config = ScopeSpanDecoderConfig.from_dict(checkpoint["config"])
    _require(_canonical(checkpoint["profile"]) == _canonical(_profile(config)), "checkpoint source profile mismatch")
    model = ScopeSpanDecoder(config)
    expected = model.state_dict()
    records = checkpoint["model_state"]
    _require(type(records) is dict and set(records) == set(expected), "checkpoint parameter inventory mismatch")
    weights = {key: _restore_tensor(records[key], tensor.shape) for key, tensor in expected.items()}
    saved = checkpoint["optimizer"]
    _require(type(saved) is dict and set(saved) == {"kind", "settings", "state"} and saved["kind"] == "AdamW",
             "closed AdamW checkpoint required")
    _require(type(saved["settings"]) is dict and set(saved["settings"]) == {"learning_rate", "weight_decay"},
             "closed AdamW settings required")
    optimizer = make_scope_span_optimizer(model, **saved["settings"])
    parameters = list(model.parameters())
    _require(type(saved["state"]) is dict and set(saved["state"]) <= {str(i) for i in range(len(parameters))},
             "Adam state inventory mismatch")
    restored = {}
    for i, parameter in enumerate(parameters):
        if str(i) not in saved["state"]:
            continue
        values = saved["state"][str(i)]
        _require(type(values) is dict and set(values) == {"step", "exp_avg", "exp_avg_sq"}, "closed Adam moments required")
        restored[i] = {key: _restore_tensor(value, () if key == "step" else parameter.shape) for key, value in values.items()}
        _require(bool((restored[i]["exp_avg_sq"] >= 0).all()), "negative Adam variance")
    _progress(model, restored, checkpoint["steps"])
    model.load_state_dict(weights, strict=True)
    model.train(checkpoint["model_training"])
    state = optimizer.state_dict()
    state["state"] = restored
    optimizer.load_state_dict(state)
    _require(save_scope_span_checkpoint(model, optimizer, steps=checkpoint["steps"]) == checkpoint,
             "checkpoint differs after exact restoration")
    return model, optimizer, checkpoint["steps"]
