"""Private persistent-source adapter for exposed decoder development only.

The inherited single-layer GRU and its checkpoint remain unchanged. A new
zero-initialized source-to-token-embedding residual supplies the projected input
at every recurrent step or only at the first BOS position, with equal parameter
capacity in both arms. Source context travels in explicit per-sequence state;
there is no mutable module cache or access to reference targets during generation.

This owner changes neither encoder context nor decoder output budgets. Its model
implements the v1 experiment's numerical protocol, but its new state dictionary
belongs to a separate experimental architecture, not a published checkpoint.
"""
from __future__ import annotations

from copy import deepcopy

from . import decoder_distillation_experiment as v1

SCHEMA = "persistent-source-decoder-development/v1"
ARCHITECTURE = "projected-source-token-embedding-residual-gru/v1"
FALSE = dict(v1.FALSE)
_require = v1._require
_BODY_MODULES = {"projection_down", "projection_up", "condition", "target_embedding", "decoder", "output"}
_BODY_PARAMETERS = {
    "projection_down.weight", "projection_down.bias", "projection_up.weight", "projection_up.bias",
    "condition.weight", "condition.bias", "target_embedding.weight", "decoder.weight_ih_l0",
    "decoder.weight_hh_l0", "decoder.bias_ih_l0", "decoder.bias_hh_l0", "output.weight", "output.bias"}


def _body_spec(model, dimension, torch):
    _require(type(dimension) is int and dimension in (8, 384, 768), "explicit supported input dimension required")
    _require(isinstance(model, torch.nn.Module) and all(callable(getattr(model, name, None))
        for name in ("project", "start", "next_logits")), "raw numerical body protocol required")
    _require(set(dict(model.named_children())) == _BODY_MODULES
        and set(model.state_dict()) == _BODY_PARAMETERS, "unwrapped inherited GRU body required")
    for name in ("projection_down", "projection_up", "condition", "output"):
        _require(isinstance(getattr(model, name), torch.nn.Linear), "inherited linear modules required")
    _require(isinstance(model.target_embedding, torch.nn.Embedding)
        and isinstance(model.decoder, torch.nn.GRU), "inherited embedding and GRU required")
    embedding, decoder = model.target_embedding, model.decoder
    _require(1 <= model.projection_down.out_features <= 64
        and model.projection_down.in_features == dimension
        and model.projection_up.in_features == model.projection_down.out_features
        and model.projection_up.out_features == dimension, "projection input dimension or width differs")
    _require(8 <= decoder.hidden_size <= 128 and 8 <= embedding.embedding_dim <= 64
        and 4 <= embedding.num_embeddings <= 4096 and embedding.padding_idx == 0,
        "bounded inherited decoder geometry required")
    _require(decoder.num_layers == 1 and decoder.batch_first and not decoder.bidirectional
        and decoder.dropout == 0 and decoder.bias and decoder.input_size == embedding.embedding_dim,
        "single-layer original GRU input geometry required")
    _require(model.condition.in_features == dimension and model.condition.out_features == decoder.hidden_size
        and model.output.in_features == decoder.hidden_size and model.output.out_features == embedding.num_embeddings,
        "inherited source conditioning or output geometry differs")
    for tensor in model.state_dict().values():
        _require(tensor.device.type == "cpu" and tensor.dtype == torch.float32
            and bool(torch.isfinite(tensor).all()), "finite CPU float32 inherited tensors required")
    return dict(dimension=dimension, hidden_width=decoder.hidden_size,
        token_embedding_width=embedding.embedding_dim, vocabulary_size=embedding.num_embeddings,
        projection_width=model.projection_down.out_features)


def bind_persistent_model(model, *, dimension, conditioning="every_step"):
    """Copy a raw donor body and add a zero-initialized persistent source path.

    Pass ``runtime.model`` or, for an already v1-bound private model,
    ``bound.body`` explicitly. The original tensors, flags, random generator and
    modules are untouched. Supports actual declared 8/384/768-wide inputs; this
    does not produce, pad or convert representations or authenticate their origin.

    Both modes add exactly the same parameters. ``every_step`` injects the new
    residual at every token; ``first_step`` injects it only at the first BOS
    position. ``start(projected)`` returns ``(hidden, source, position)`` with a
    per-sequence int64 consumed-prefix counter. ``next_logits`` returns updated
    hidden/counters and the same source tensor, without mutating any input state.
    """
    torch = v1._torch()
    _require(conditioning in ("every_step", "first_step"), "explicit supported conditioning mode required")
    specification = _body_spec(model, dimension, torch)
    inherited_digest = v1.tensor_digest(model)

    class PersistentDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = dimension
            # The temporary constructor's RNG use is isolated; all new values
            # are then set to zero and no inherited tensor is resized.
            with torch.random.fork_rng(devices=[]):
                self.source_to_embedding = torch.nn.Linear(dimension,
                    specification["token_embedding_width"], bias=False, dtype=torch.float32)
            with torch.no_grad():
                self.source_to_embedding.weight.zero_()
            _require(v1.tensor_digest(self.body) == inherited_digest, "private inherited body copy differs")

        def _inputs(self, values):
            _require(isinstance(values, torch.Tensor) and values.device.type == "cpu" and values.dtype == torch.float32
                and values.ndim == 2 and 1 <= values.shape[0] <= 128 and values.shape[1] == dimension
                and bool(torch.isfinite(values).all()), "bounded exact CPU source input required")

        def project(self, values):
            self._inputs(values)
            projected = self.body.project(values)
            self._inputs(projected)
            return projected

        def start(self, projected):
            self._inputs(projected)
            hidden = self.body.start(projected)
            _require(isinstance(hidden, torch.Tensor)
                and tuple(hidden.shape) == (1, len(projected), specification["hidden_width"])
                and hidden.device.type == "cpu" and hidden.dtype == torch.float32
                and bool(torch.isfinite(hidden).all()), "inherited initial hidden state differs")
            return hidden, projected, torch.zeros(len(projected), dtype=torch.long)

        def next_logits(self, tokens, state):
            _require(isinstance(tokens, torch.Tensor) and tokens.device.type == "cpu" and tokens.dtype == torch.long
                and tokens.ndim == 2 and 1 <= tokens.shape[0] <= 128 and 1 <= tokens.shape[1] <= 1023
                and bool((tokens >= 0).all()) and bool((tokens < specification["vocabulary_size"]).all()),
                "bounded decoder prefix IDs required")
            _require(type(state) is tuple and len(state) == 3, "explicit recurrent/source/position state tuple required")
            hidden, source, position = state
            self._inputs(source)
            _require(len(source) == len(tokens) and isinstance(hidden, torch.Tensor)
                and tuple(hidden.shape) == (1, len(tokens), specification["hidden_width"])
                and hidden.device.type == "cpu" and hidden.dtype == torch.float32
                and bool(torch.isfinite(hidden).all()), "recurrent/source state batch or geometry differs")
            _require(isinstance(position, torch.Tensor) and position.dtype == torch.long and position.device.type == "cpu"
                and tuple(position.shape) == (len(tokens),) and bool((position >= 0).all())
                and bool((position <= 1023).all())
                and bool((position + tokens.shape[1] <= 1023).all()), "bounded per-sequence prefix position required")
            _require(bool((tokens[position == 0, 0] == 1).all()), "initial decoder prefix must begin with BOS")
            embedded = self.body.target_embedding(tokens)
            persistent = self.source_to_embedding(source).unsqueeze(1)
            _require(bool(torch.isfinite(persistent).all()), "nonfinite persistent source residual")
            if conditioning == "first_step":
                first = position.unsqueeze(1) + torch.arange(tokens.shape[1], dtype=torch.long).unsqueeze(0) == 0
                persistent = persistent * first.unsqueeze(-1)
            recurrent_input = embedded + persistent
            _require(bool(torch.isfinite(recurrent_input).all()), "nonfinite conditioned token embedding")
            outputs, updated = self.body.decoder(recurrent_input, hidden)
            logits = self.body.output(outputs)
            _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(updated).all()),
                "nonfinite persistent decoding state")
            return logits, (updated, source, position + tokens.shape[1])

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, architecture=ARCHITECTURE, **specification,
                conditioning=conditioning,
                source_context="normalized_projected_input",
                source_residual_positions="every_token" if conditioning == "every_step" else "first_bos_token_only",
                state_layout=["recurrent_hidden", "projected_source", "consumed_prefix_position"],
                source_context_cached_on_module=False,
                inherited_initial_weights_sha256=inherited_digest,
                initial_adapter_zero_initialized=True,
                current_adapter_is_zero=bool((self.source_to_embedding.weight.detach() == 0).all()),
                added_parameter_names=["source_to_embedding.weight"],
                added_parameter_count=dimension * specification["token_embedding_width"],
                inherited_parameter_names=["body."+name for name in sorted(_BODY_PARAMETERS)],
                model_weights_sha256=v1.tensor_digest(self),
                encoder_context_changed=False, output_budget_changed=False,
                target_access_during_generation=False, production_runtime_compatible=False,
                scope="exposed_development_only", **FALSE)

    return PersistentDecoder()


def bind_zero_condition_model(model, *, dimension):
    """Private inference control removing initial and persistent source access.

    Reconstruction remains the real inherited projection. Only decoder state
    from ``start`` is replaced with zeros: the initial hidden state for the old
    model, and both hidden/source lanes for the persistent model. Subsequent
    recurrent state still depends on generated token history, as it should.
    No caller tensors, flags or context are modified and this is not a new input
    representation. Do not use the control as teacher qualification evidence.
    """
    torch = v1._torch()
    _require(type(dimension) is int and dimension in (8, 384, 768), "explicit supported input dimension required")
    if getattr(model, "dimension", None) is None:
        _body_spec(model, dimension, torch)
    else:
        v1._model(model, torch)
        _require(model.dimension == dimension, "ablation model input dimension differs")

    class ZeroConditionDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = dimension

        def project(self, values):
            return self.body.project(values)

        def start(self, projected):
            state = self.body.start(projected)
            if isinstance(state, torch.Tensor):
                return torch.zeros_like(state)
            _require(type(state) is tuple and len(state) in (2, 3)
                and all(isinstance(value, torch.Tensor) for value in state), "unsupported conditioning state layout")
            zero_condition = tuple(torch.zeros_like(value) for value in state[:2])
            if len(state) == 3:
                _require(state[2].dtype == torch.long and state[2].device.type == "cpu"
                    and state[2].ndim == 1, "explicit integer prefix position required")
                return (*zero_condition, state[2])
            return zero_condition

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema="zero-source-condition-control/v1", dimension=dimension,
                projection_preserved=True, initial_hidden_zeroed=True, persistent_source_zeroed_if_present=True,
                prefix_position_preserved=True,
                subsequent_generated_token_history_preserved=True, source_text_not_supplied=True,
                model_weights_sha256=v1.tensor_digest(self), scope="development_ablation_only", **FALSE)

    return ZeroConditionDecoder()


# These aliases deliberately preserve the v1 mathematical policy and guards.
# New source-fidelity selection policies need their own explicit versioned owner.
run_trial = v1.run_trial
evaluate_model = v1.evaluate_model
tensor_digest = v1.tensor_digest
