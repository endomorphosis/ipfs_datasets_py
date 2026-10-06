"""Trainable source-conditioned grouped semantic span decoder.

The model receives generic UTF-8 token features and an explicit caller scope.
It learns count, scope, modality and source-span pointers jointly. Inference
never consults source parsers, reference groups, annotations or target requests.
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

from ...deontic import coordination_decoder as semantic

CHECKPOINT_SCHEMA = "legal-grouped-span-decoder-checkpoint/v1"
PREDICTION_SCHEMA = "legal-grouped-span-decoder-prediction/v1"
TOKENIZER_PROFILE = "unicode_word_or_punctuation_utf8_offsets/v1"
SCOPES = ("modal_over_actions", "disjunction_of_norms")
MODALITIES = ("O", "P", "F")
POINTERS = ("actor_start", "actor_end", "action_start", "action_end")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_MAX_BATCH = 128


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _producer_pins() -> dict[str, str]:
    return {"implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "semantic_decoder_sha256": sha256(Path(semantic.__file__).read_bytes()).hexdigest(),
            "torch_version": str(torch.__version__), "tokenizer_profile": TOKENIZER_PROFILE}


_IMPORTED_PINS = _producer_pins()


def producer_pins() -> dict[str, str]:
    _require(_producer_pins() == _IMPORTED_PINS, "span decoder producer changed since import")
    return dict(_IMPORTED_PINS)


@dataclass(frozen=True, slots=True)
class SpanDecoderConfig:
    seed: int = 0
    byte_dim: int = 16
    token_dim: int = 64
    token_hidden: int = 64
    slot_hidden: int = 128
    max_tokens: int = 192
    max_token_bytes: int = 64
    max_source_chars: int = 8192

    def __post_init__(self) -> None:
        bounds = {"seed": (0, 2**31 - 1), "byte_dim": (4, 64), "token_dim": (8, 256),
                  "token_hidden": (8, 256), "slot_hidden": (8, 256), "max_tokens": (8, 256),
                  "max_token_bytes": (4, 128), "max_source_chars": (32, 16384)}
        for key, (low, high) in bounds.items():
            value = getattr(self, key)
            _require(type(value) is int and low <= value <= high, "invalid bounded config field: " + key)

    def to_dict(self) -> dict[str, int]:
        self.__post_init__()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SpanDecoderConfig:
        _require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), "closed span config required")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SourceToken:
    text: str
    start: int
    end: int


def tokenize_source(source_text: str, config: SpanDecoderConfig) -> tuple[SourceToken, ...]:
    """Tokenize all source characters generically; never trim or truncate spans."""
    _require(type(config) is SpanDecoderConfig, "typed span config required")
    config.__post_init__()
    _require(type(source_text) is str and 0 < len(source_text) <= config.max_source_chars,
             "source character bounds exceeded or source empty")
    try:
        source_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF-8 source required") from error
    tokens = tuple(SourceToken(match.group(), match.start(), match.end()) for match in _TOKEN_RE.finditer(source_text))
    _require(1 <= len(tokens) <= config.max_tokens, "source token bounds exceeded or source empty")
    _require(all(1 <= len(token.text.encode("utf-8")) <= config.max_token_bytes for token in tokens),
             "token byte bounds exceeded; source is never truncated")
    return tokens


def _span(value: Any) -> None:
    _require(type(value) is tuple and len(value) == 2 and all(type(part) is int for part in value)
             and 0 <= value[0] < value[1] <= 16384, "immutable half-open character span required")


@dataclass(frozen=True, slots=True)
class GroupedSpanTarget:
    actor_span: tuple[int, int]
    action_span: tuple[int, int]
    modality: str

    def __post_init__(self) -> None:
        _span(self.actor_span)
        _span(self.action_span)
        _require(type(self.modality) is str and self.modality in MODALITIES, "target modality must be O/P/F")


@dataclass(frozen=True, slots=True)
class GroupedSpanExample:
    source_text: str
    modal_scope: str
    members: tuple[GroupedSpanTarget, ...]

    def __post_init__(self) -> None:
        _require(type(self.source_text) is str and 0 < len(self.source_text) <= 16384, "bounded source required")
        _require(type(self.modal_scope) is str and self.modal_scope in SCOPES, "explicit target caller scope required")
        _require(type(self.members) is tuple and 2 <= len(self.members) <= 8
                 and all(type(member) is GroupedSpanTarget for member in self.members), "two through eight typed span targets required")
        for member in self.members:
            member.__post_init__()
            _require(member.actor_span[1] <= len(self.source_text) and member.action_span[1] <= len(self.source_text),
                     "target span outside source")


class GroupedSpanDecoder(nn.Module):
    """Fixed alphabet byte features, token BiGRU and learned ordered span slots."""
    def __init__(self, config: SpanDecoderConfig | None = None):
        super().__init__()
        self.config = config if config is not None else SpanDecoderConfig()
        _require(type(self.config) is SpanDecoderConfig, "typed span config required")
        self.config.__post_init__()
        cfg = self.config
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(cfg.seed)
            self.byte_embedding = nn.Embedding(257, cfg.byte_dim, padding_idx=0)
            self.token_projection = nn.Linear(3 * cfg.byte_dim + 1, cfg.token_dim)
            self.position_embedding = nn.Embedding(cfg.max_tokens, cfg.token_dim)
            self.token_gru = nn.GRU(cfg.token_dim, cfg.token_hidden, batch_first=True, bidirectional=True)
            encoded = 2 * cfg.token_hidden
            self.global_projection = nn.Linear(3 * encoded + 1, cfg.slot_hidden)
            self.scope_embedding = nn.Embedding(2, cfg.slot_hidden)
            self.slot_queries = nn.Embedding(8, cfg.slot_hidden)
            self.attention_keys = nn.Linear(encoded, cfg.slot_hidden)
            self.slot_fusion = nn.Linear(cfg.slot_hidden + encoded, cfg.slot_hidden)
            self.count_head = nn.Linear(cfg.slot_hidden, 7)
            self.scope_head = nn.Linear(cfg.slot_hidden, 2)
            self.modality_head = nn.Linear(cfg.slot_hidden, 3)
            self.pointer_keys = nn.ModuleDict({key: nn.Linear(encoded, cfg.slot_hidden) for key in POINTERS})
            self.pointer_queries = nn.ModuleDict({key: nn.Linear(cfg.slot_hidden, cfg.slot_hidden) for key in POINTERS})

    def forward(self, token_bytes: torch.Tensor, token_mask: torch.Tensor,
                scope_indices: torch.Tensor) -> dict[str, torch.Tensor]:
        _require(token_bytes.device.type == token_mask.device.type == scope_indices.device.type == "cpu",
                 "this diagnostic model uses CPU tensors")
        _require(token_bytes.dtype == torch.long and token_mask.dtype == torch.bool and scope_indices.dtype == torch.long,
                 "typed token/scope tensors required")
        _require(token_bytes.ndim == 3 and token_mask.shape == token_bytes.shape[:2]
                 and scope_indices.shape == token_bytes.shape[:1], "inconsistent source tensor shapes")
        batch, tokens, width = token_bytes.shape
        _require(1 <= batch <= _MAX_BATCH and 1 <= tokens <= self.config.max_tokens
                 and 1 <= width <= self.config.max_token_bytes, "source tensor bounds exceeded")
        _require(bool(((token_bytes >= 0) & (token_bytes <= 256)).all())
                 and bool(((scope_indices >= 0) & (scope_indices <= 1)).all()), "fixed alphabet or caller scope out of range")
        lengths = token_mask.sum(1)
        expected_mask = torch.arange(tokens).unsqueeze(0) < lengths.unsqueeze(1)
        _require(bool((lengths > 0).all()) and torch.equal(expected_mask, token_mask), "contiguous nonempty token mask required")
        byte_mask = token_bytes != 0
        byte_lengths = byte_mask.sum(-1)
        _require(torch.equal(byte_lengths > 0, token_mask), "token byte padding differs from source mask")
        expected_bytes = torch.arange(width).reshape(1, 1, -1) < byte_lengths.unsqueeze(-1)
        _require(torch.equal(byte_mask, expected_bytes), "contiguous token bytes required")
        embedded = self.byte_embedding(token_bytes)
        means = (embedded * byte_mask.unsqueeze(-1)).sum(-2) / byte_lengths.clamp_min(1).unsqueeze(-1)
        first = embedded[:, :, 0, :]
        last = embedded.gather(2, (byte_lengths.clamp_min(1) - 1).reshape(batch, tokens, 1, 1)
                               .expand(-1, -1, 1, self.config.byte_dim)).squeeze(2)
        token_features = torch.cat((means, first, last, torch.log1p(byte_lengths.float()).unsqueeze(-1)), -1)
        token_embeddings = torch.tanh(self.token_projection(token_features))
        token_embeddings = token_embeddings + self.position_embedding(torch.arange(tokens)).unsqueeze(0)
        packed = pack_padded_sequence(token_embeddings, lengths.cpu(), batch_first=True, enforce_sorted=False)
        packed_output, _ = self.token_gru(packed)
        encoded, _ = pad_packed_sequence(packed_output, batch_first=True, total_length=tokens)
        pooled = (encoded * token_mask.unsqueeze(-1)).sum(1) / lengths.unsqueeze(-1)
        final = encoded[torch.arange(batch), lengths - 1]
        global_state = torch.tanh(self.global_projection(torch.cat(
            (pooled, encoded[:, 0], final, torch.log1p(lengths.float()).unsqueeze(-1)), -1))
            + self.scope_embedding(scope_indices))
        queries = torch.tanh(global_state.unsqueeze(1) + self.slot_queries.weight.unsqueeze(0))
        attention = torch.einsum('bsh,bth->bst', queries, self.attention_keys(encoded)) / math.sqrt(self.config.slot_hidden)
        attention = attention.masked_fill(~token_mask.unsqueeze(1), -10000.0)
        context = torch.bmm(attention.softmax(-1), encoded)
        slots = torch.tanh(self.slot_fusion(torch.cat((queries, context), -1)))
        result = {"count": self.count_head(global_state), "scope": self.scope_head(global_state),
                  "modality": self.modality_head(slots)}
        for key in POINTERS:
            logits = torch.einsum('bsh,bth->bst', self.pointer_queries[key](slots), self.pointer_keys[key](encoded))
            result[key] = (logits / math.sqrt(self.config.slot_hidden)).masked_fill(~token_mask.unsqueeze(1), -10000.0)
        return result


def _encoded_sources(config: SpanDecoderConfig, sources: list[str], scopes: list[str]):
    _require(type(sources) is list and type(scopes) is list and 1 <= len(sources) == len(scopes) <= _MAX_BATCH,
             "bounded source/caller-scope batch required")
    _require(all(type(scope) is str and scope in SCOPES for scope in scopes), "explicit supported caller scopes required")
    token_rows = [tokenize_source(source, config) for source in sources]
    token_count = max(map(len, token_rows))
    byte_count = max(len(token.text.encode("utf-8")) for row in token_rows for token in row)
    values = torch.zeros((len(sources), token_count, byte_count), dtype=torch.long)
    mask = torch.zeros((len(sources), token_count), dtype=torch.bool)
    for row, tokens in enumerate(token_rows):
        for column, token in enumerate(tokens):
            raw = token.text.encode("utf-8")
            values[row, column, :len(raw)] = torch.tensor([byte + 1 for byte in raw], dtype=torch.long)
            mask[row, column] = True
    return (values, mask, torch.tensor([SCOPES.index(scope) for scope in scopes], dtype=torch.long)), token_rows


def _labels(examples: list[GroupedSpanExample], token_rows):
    values = {key: torch.full((len(examples), 8), -100, dtype=torch.long) for key in (*POINTERS, "modality")}
    values["count"] = torch.tensor([len(example.members) - 2 for example in examples], dtype=torch.long)
    values["scope"] = torch.tensor([SCOPES.index(example.modal_scope) for example in examples], dtype=torch.long)
    for row, (example, tokens) in enumerate(zip(examples, token_rows)):
        starts = {token.start: index for index, token in enumerate(tokens)}
        ends = {token.end: index for index, token in enumerate(tokens)}
        decoded_members = []
        for column, target in enumerate(example.members):
            for slot, span in (("actor", target.actor_span), ("action", target.action_span)):
                _require(span[0] in starts and span[1] in ends, "training span is not exactly aligned to token boundaries")
                values[slot + "_start"][row, column] = starts[span[0]]
                values[slot + "_end"][row, column] = ends[span[1]]
            values["modality"][row, column] = MODALITIES.index(target.modality)
            decoded_members.append(semantic.CoordinationDecodeMember(
                semantic.semantic_label_identity(example.source_text[slice(*target.actor_span)], actor=True), target.modality,
                semantic.semantic_label_identity(example.source_text[slice(*target.action_span)], actor=False)))
        request = semantic.CoordinationDecodeRequest(example.modal_scope, "inclusive_or", "universal_actor_predicate", tuple(decoded_members))
        if request.modal_scope == "modal_over_actions":
            _require(len({member.actor for member in request.members}) == 1 and len({member.modality for member in request.members}) == 1,
                     "training labels conflict with the explicit shared-modal scope")
    return values


def make_grouped_span_optimizer(model: GroupedSpanDecoder, learning_rate: float = 0.003,
                                weight_decay: float = 0.0) -> torch.optim.AdamW:
    _require(type(model) is GroupedSpanDecoder, "typed grouped span model required")
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= 0.1,
             "bounded finite learning rate required")
    _require(type(weight_decay) in (int, float) and math.isfinite(weight_decay) and 0 <= weight_decay <= 1,
             "bounded finite weight decay required")
    return torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay), foreach=False)


def _optimizer_settings(model, optimizer):
    _require(type(optimizer) is torch.optim.AdamW and len(optimizer.param_groups) == 1, "one-group AdamW optimizer required")
    group = optimizer.param_groups[0]
    _require(all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                 for parameter in model.parameters()), "CPU float32 model parameters required")
    _require(type(group["lr"]) in (int, float) and math.isfinite(group["lr"]) and 0 < group["lr"] <= 0.1
             and type(group["weight_decay"]) in (int, float) and math.isfinite(group["weight_decay"])
             and 0 <= group["weight_decay"] <= 1, "invalid live optimizer settings")
    _require([id(value) for value in group["params"]] == [id(value) for value in model.parameters()],
             "optimizer parameters do not match this model")
    _require(group["betas"] == (0.9, 0.999) and group["eps"] == 1e-8 and not group["amsgrad"]
             and not group["maximize"] and not group["capturable"] and not group["differentiable"],
             "unsupported optimizer settings")
    _require(group["foreach"] is False and group.get("fused") is None, "unsupported optimizer backend")
    return {"learning_rate": group["lr"], "weight_decay": group["weight_decay"]}


def train_grouped_span_step(model: GroupedSpanDecoder, optimizer: torch.optim.AdamW,
                            examples: list[GroupedSpanExample], gradient_clip: float = 5.0) -> dict[str, float]:
    """Perform one actual optimizer step; split/selection policy belongs to caller."""
    before = producer_pins()
    _require(type(model) is GroupedSpanDecoder and type(examples) is list and 1 <= len(examples) <= _MAX_BATCH
             and all(type(example) is GroupedSpanExample for example in examples), "bounded typed training examples required")
    _optimizer_settings(model, optimizer)
    _require(type(gradient_clip) in (int, float) and math.isfinite(gradient_clip) and 0 < gradient_clip <= 100,
             "bounded finite gradient clipping required")
    for example in examples:
        example.__post_init__()
    batch, token_rows = _encoded_sources(model.config, [example.source_text for example in examples], [example.modal_scope for example in examples])
    targets = _labels(examples, token_rows)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    outputs = model(*batch)
    losses = {key: F.cross_entropy(logits if key in {"count", "scope"} else logits.reshape(-1, logits.shape[-1]),
                                  targets[key] if key in {"count", "scope"} else targets[key].reshape(-1), ignore_index=-100)
              for key, logits in outputs.items()}
    loss = sum(losses.values())
    _require(bool(torch.isfinite(loss)), "nonfinite training loss")
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), float(gradient_clip), error_if_nonfinite=True)
    optimizer.step()
    _require(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters()), "nonfinite model after update")
    _require(producer_pins() == before, "training producers changed during optimizer step")
    return {"loss": float(loss.detach()), "gradient_norm": float(norm),
            **{key + "_loss": float(value.detach()) for key, value in losses.items()}}


def predict_grouped_span_decoder(model: GroupedSpanDecoder, source_text: str, modal_scope: str | None) -> dict[str, Any]:
    """Predict solely from source and an explicit caller declaration; never repair."""
    result = {"schema": PREDICTION_SCHEMA, "status": "blocked", "request": None,
              "blockers": [], "raw_prediction": None, "source_semantics_verified": False,
              "proof_ready": False, "model_accuracy_claimed": False, "targets_used_at_inference": False}
    if type(modal_scope) is not str or modal_scope not in SCOPES:
        result.update(status="abstained", blockers=["explicit_caller_scope_required"])
        return result
    before = producer_pins()
    _require(type(model) is GroupedSpanDecoder, "typed grouped span model required")
    try:
        batch, token_rows = _encoded_sources(model.config, [source_text], [modal_scope])
    except ValueError as error:
        result["blockers"] = ["source_profile_unsupported"]
        result["diagnostic"] = str(error)
        return result
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            outputs = model(*batch)
    finally:
        model.train(was_training)
    expected_shapes = {"count": (1, 7), "scope": (1, 2), "modality": (1, 8, 3),
                       **{key: (1, 8, len(token_rows[0])) for key in POINTERS}}
    if (type(outputs) is not dict or set(outputs) != set(expected_shapes)
            or any(not isinstance(outputs[key], torch.Tensor)
                   or outputs[key].device.type != "cpu" or outputs[key].dtype != torch.float32
                   or tuple(outputs[key].shape) != shape for key, shape in expected_shapes.items())):
        result["blockers"] = ["malformed_model_prediction"]
        return result
    if not all(bool(torch.isfinite(logits).all()) for logits in outputs.values()):
        result["blockers"] = ["nonfinite_model_prediction"]
        return result
    count = int(outputs["count"].argmax(-1)[0]) + 2
    scope = SCOPES[int(outputs["scope"].argmax(-1)[0])]
    raw = {"count": count, "modal_scope": scope, "members": []}
    for index in range(count):
        raw["members"].append({"modality": MODALITIES[int(outputs["modality"][0, index].argmax())],
                               **{key: int(outputs[key][0, index].argmax()) for key in POINTERS}})
    result["raw_prediction"] = raw
    result["confidence"] = {"count": float(outputs["count"].softmax(-1)[0].max()),
                            "scope": float(outputs["scope"].softmax(-1)[0].max())}
    if scope != modal_scope:
        result["blockers"] = ["predicted_scope_disagrees_with_caller"]
        return result
    tokens = token_rows[0]
    members = []
    spans = []
    try:
        for item in raw["members"]:
            member_spans = {}
            for field in ("actor", "action"):
                start, end = item[field + "_start"], item[field + "_end"]
                _require(0 <= start <= end < len(tokens), "predicted span order/bounds invalid")
                member_spans[field] = [tokens[start].start, tokens[end].end]
            actor = semantic.semantic_label_identity(source_text[slice(*member_spans["actor"])], actor=True)
            action = semantic.semantic_label_identity(source_text[slice(*member_spans["action"])], actor=False)
            members.append(semantic.CoordinationDecodeMember(actor, item["modality"], action))
            spans.append(member_spans)
        request = semantic.CoordinationDecodeRequest(scope, "inclusive_or", "universal_actor_predicate", tuple(members))
        if scope == "modal_over_actions":
            _require(len({member.actor for member in members}) == 1 and len({member.modality for member in members}) == 1,
                     "predicted shared-modal actor/operator mismatch")
    except ValueError as error:
        result.update(blockers=["predicted_span_or_request_invalid"], diagnostic=str(error))
        return result
    result.update(status="predicted", request=request.to_dict(), predicted_character_spans=spans)
    _require(producer_pins() == before, "prediction producers changed during inference")
    return result


def _canonical(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("finite JSON checkpoint required") from error
    _require(len(encoded) <= 100_000_000, "checkpoint byte bound exceeded")
    return encoded


def _tensor_record(tensor: torch.Tensor):
    _require(tensor.device.type == "cpu" and tensor.dtype == torch.float32 and bool(torch.isfinite(tensor).all()),
             "finite CPU float32 checkpoint tensors required")
    return {"shape": list(tensor.shape), "dtype": "float32", "values": tensor.detach().reshape(-1).tolist()}


def _restore_tensor(value, expected_shape):
    _require(type(value) is dict and set(value) == {"shape", "dtype", "values"}, "closed tensor record required")
    _require(type(value["shape"]) is list and all(type(item) is int for item in value["shape"])
             and value["shape"] == list(expected_shape) and value["dtype"] == "float32", "tensor shape/dtype mismatch")
    items = value["values"]
    _require(type(items) is list and len(items) == math.prod(expected_shape)
             and all(type(item) is float and math.isfinite(item) for item in items), "finite float tensor values required")
    tensor = torch.tensor(items, dtype=torch.float32).reshape(expected_shape)
    _require(bool(torch.isfinite(tensor).all()), "checkpoint values overflow float32")
    return tensor


def save_grouped_span_checkpoint(model: GroupedSpanDecoder, optimizer: torch.optim.AdamW, *, steps: int) -> dict[str, Any]:
    """Save numerical state/progress only; never serialize source or targets."""
    pins = producer_pins()
    _require(type(model) is GroupedSpanDecoder and type(steps) is int and 0 <= steps <= 10_000_000,
             "typed model and bounded integer progress required")
    settings = _optimizer_settings(model, optimizer)
    state = optimizer.state_dict()
    parameters = list(model.parameters())
    _require(set(state["state"]) == (set() if steps == 0 else set(range(len(parameters)))),
             "optimizer state parameter inventory mismatch")
    optimizer_records = {}
    for index, values in state["state"].items():
        _require(type(index) is int and set(values) == {"step", "exp_avg", "exp_avg_sq"}, "closed AdamW state required")
        _require(values["step"].shape == torch.Size([]) and float(values["step"]) == steps,
                 "optimizer step differs from declared progress")
        _require(values["exp_avg"].shape == parameters[index].shape
                 and values["exp_avg_sq"].shape == parameters[index].shape
                 and bool((values["exp_avg_sq"] >= 0).all()), "optimizer moment shape/variance invalid")
        optimizer_records[str(index)] = {key: _tensor_record(tensor) for key, tensor in values.items()}
    _require((steps == 0 and not optimizer_records) or (steps > 0 and len(optimizer_records) == len(list(model.parameters()))),
             "optimizer state does not cover progress/model parameters")
    result = {"schema": CHECKPOINT_SCHEMA, "producer": pins, "config": model.config.to_dict(),
              "profile": {"tokenizer": TOKENIZER_PROFILE, "alphabet_size": 257, "members": [2, 8],
                          "input_fields": ["source_text", "modal_scope"], "numeric_vector_conditioning": False},
              "steps": steps, "model_state": {key: _tensor_record(tensor) for key, tensor in model.state_dict().items()},
              "optimizer": {"kind": "AdamW", "settings": settings, "state": optimizer_records}}
    result["checkpoint_sha256"] = sha256(_canonical(result)).hexdigest()
    _require(producer_pins() == pins, "checkpoint producers changed while saving")
    return result


def restore_grouped_span_checkpoint(checkpoint: dict[str, Any]) -> tuple[GroupedSpanDecoder, torch.optim.AdamW, int]:
    """Strictly restore bounded finite tensors without pickle or dynamic objects."""
    fields = {"schema", "producer", "config", "profile", "steps", "model_state", "optimizer", "checkpoint_sha256"}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed span checkpoint required")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["producer"] == producer_pins(), "checkpoint schema/producer mismatch")
    expected_profile = {"tokenizer": TOKENIZER_PROFILE, "alphabet_size": 257, "members": [2, 8],
                        "input_fields": ["source_text", "modal_scope"], "numeric_vector_conditioning": False}
    _require(type(checkpoint["profile"]) is dict and _canonical(checkpoint["profile"]) == _canonical(expected_profile),
             "checkpoint source profile mismatch")
    seal = sha256(_canonical({key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"})).hexdigest()
    _require(type(checkpoint["checkpoint_sha256"]) is str and seal == checkpoint["checkpoint_sha256"], "checkpoint seal mismatch")
    steps = checkpoint["steps"]
    _require(type(steps) is int and 0 <= steps <= 10_000_000, "invalid checkpoint progress")
    model = GroupedSpanDecoder(SpanDecoderConfig.from_dict(checkpoint["config"]))
    expected_state = model.state_dict()
    records = checkpoint["model_state"]
    _require(type(records) is dict and set(records) == set(expected_state), "checkpoint parameter inventory mismatch")
    restored = {key: _restore_tensor(records[key], tensor.shape) for key, tensor in expected_state.items()}
    optimizer_record = checkpoint["optimizer"]
    _require(type(optimizer_record) is dict and set(optimizer_record) == {"kind", "settings", "state"}
             and optimizer_record["kind"] == "AdamW", "closed AdamW checkpoint required")
    settings = optimizer_record["settings"]
    _require(type(settings) is dict and set(settings) == {"learning_rate", "weight_decay"}, "closed optimizer settings required")
    optimizer = make_grouped_span_optimizer(model, **settings)
    optimizer_state = optimizer_record["state"]
    parameters = list(model.parameters())
    _require(type(optimizer_state) is dict and set(optimizer_state) == (set() if steps == 0 else {str(i) for i in range(len(parameters))}),
             "optimizer state inventory mismatch")
    restored_optimizer = {}
    for index, parameter in enumerate(parameters):
        if steps == 0:
            break
        value = optimizer_state[str(index)]
        _require(type(value) is dict and set(value) == {"step", "exp_avg", "exp_avg_sq"}, "closed optimizer tensor state required")
        tensors = {key: _restore_tensor(value[key], () if key == "step" else parameter.shape) for key in value}
        _require(float(tensors["step"]) == steps and bool((tensors["exp_avg_sq"] >= 0).all()), "optimizer progress/variance invalid")
        restored_optimizer[index] = tensors
    model.load_state_dict(restored, strict=True)
    state = optimizer.state_dict()
    state["state"] = restored_optimizer
    optimizer.load_state_dict(state)
    _require(save_grouped_span_checkpoint(model, optimizer, steps=steps) == checkpoint, "checkpoint differs after strict restoration")
    return model, optimizer, steps
