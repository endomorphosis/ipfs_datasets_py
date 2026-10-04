"""Source-predicted cardinality and causal rule-boundary guidance, experimental.

Counts are predicted from the inherited source-conditioned initial hidden state.
Reference counts never enter generation. A strict lexical streaming recognizer
enables a soft correction only immediately after a complete seven-facet rule in
the top-level rules array. It is neither a semantic validator nor a repair. Any
invalid prefix disables guidance permanently for that sequence. Output budgets,
encoder context, native validators and qualification policies stay unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import json

from . import decoder_distillation_experiment as core
from . import decoder_distillation_experiment_v2 as conditioning

SCHEMA = "source-cardinality-decoder-development/v1"
MAX_RULES = 32
FALSE = dict(core.FALSE)
_require = core._require
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
# A recognizer state is [phase, seen-field bitmask, pending field, completed
# rules, current qualifier length, last qualifier lexical rank]. Phases are:
# BOS,{,rules,:, [,first-rule,key,:,value,after-value,list-first,list-after,
# list-next,after-rule,next-rule,top-close,EOS,done,invalid.
_INVALID = 18


def _tables(codec, size, torch):
    _require(type(codec) is dict and type(codec.get("target_vocabulary")) is list,
        "explicit inherited lexical codec required")
    vocabulary = codec["target_vocabulary"]
    _require(len(vocabulary) == size and 4 <= size <= 4096
        and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
        and all(type(value) is str and 0 < len(value) <= 16384 for value in vocabulary)
        and len(set(vocabulary)) == size and len(core._raw(codec)) <= 4194304,
        "exact bounded codec and vocabulary required")
    required = ["{", "}", "[", "]", ":", ",", json.dumps("rules"), *map(json.dumps, FIELDS)]
    _require(all(token in vocabulary for token in required), "codec lacks full rule-grammar tokens")
    ids = {token: vocabulary.index(token) for token in required}
    strings = {}
    for index, token in enumerate(vocabulary[3:], 3):
        if token.startswith('"'):
            try:
                value = json.loads(token)
            except (ValueError, TypeError):
                continue
            if type(value) is str:
                strings[index] = value
    ranks = {value: rank+1 for rank, value in enumerate(sorted(set(strings.values())))}
    string_rank = torch.tensor([ranks[strings[i]] if i in strings else 0 for i in range(size)], dtype=torch.long)
    field_index = torch.full((size,), -1, dtype=torch.long)
    for index, name in enumerate(FIELDS):
        field_index[ids[json.dumps(name)]] = index
    modality = torch.tensor([i in strings and strings[i] in ("O", "P", "F") for i in range(size)], dtype=torch.bool)
    return ids, string_rank.tolist(), field_index.tolist(), modality.tolist()


def _scan_prefix(token_rows, state_rows, tables):
    """Lightweight causal lexical scan; one host conversion, no Torch token loop."""
    ids, string_rank, field_index, modality = tables
    final, boundaries = [], []
    for batch, (tokens, original) in enumerate(zip(token_rows, state_rows)):
        phase, seen, pending, count, length, last = original
        for offset, token in enumerate(tokens):
            rank, field = string_rank[token], field_index[token]
            following = _INVALID
            if phase == 0 and token == 1: following = 1
            elif phase == 1 and token == ids["{"]: following = 2
            elif phase == 2 and token == ids['"rules"']: following = 3
            elif phase == 3 and token == ids[":"]: following = 4
            elif phase == 4 and token == ids["["]: following = 5
            elif phase in (5, 14) and token == ids["{"]:
                following, seen = 6, 0
            elif phase == 6 and field >= 0 and not seen & (1 << field):
                following, seen, pending = 7, seen | (1 << field), field
            elif phase == 7 and token == ids[":"]: following = 8
            elif phase == 8:
                if pending < 4 and rank > 0 and (pending != 0 or modality[token]): following = 9
                elif pending >= 4 and token == ids["["]: following, length, last = 10, 0, 0
            elif phase == 10 and token == ids["]"]: following = 9
            elif phase in (10, 12) and rank > last and rank > 0 and length < 4:
                following, length, last = 11, length+1, rank
            elif phase == 11 and token == ids[","]: following = 12
            elif phase == 11 and token == ids["]"]: following = 9
            elif phase == 9 and token == ids[","]: following = 6
            elif phase == 9 and seen == 127 and token == ids["}"]:
                following, count = 13, count+1
                if count < MAX_RULES: boundaries.append((batch, offset, count))
            elif phase == 13 and token == ids[","]: following = 14
            elif phase == 13 and token == ids["]"]: following = 15
            elif phase == 15 and token == ids["}"]: following = 16
            elif phase == 16 and token == 2: following = 17
            elif phase == 17 and token == 0: following = 17
            phase = following
        final.append([phase, seen, pending, count, length, last])
    return final, boundaries


def boundary_log_odds(count_logits, completed_rules):
    """Return the requested count-vs-tail odds correction for counts1..31.

    Computing the tail relative to the selected logit makes a uniform head
    exactly zero, including float32 roundoff. This is algebraically
    logit[k-1]-logsumexp(logits[k:])+log(32-k). Counts>=32 are inactive.
    """
    torch = core._torch()
    _require(isinstance(count_logits, torch.Tensor) and count_logits.device.type == "cpu"
        and count_logits.dtype == torch.float32 and count_logits.ndim == 2 and count_logits.shape[1] == MAX_RULES
        and bool(torch.isfinite(count_logits).all()), "finite CPU count logits required")
    _require(isinstance(completed_rules, torch.Tensor) and completed_rules.device.type == "cpu"
        and completed_rules.dtype == torch.long and tuple(completed_rules.shape) == (len(count_logits),)
        and bool((completed_rules >= 0).all()), "explicit completed rule counters required")
    active = (completed_rules >= 1) & (completed_rules < MAX_RULES)
    k = completed_rules.clamp(1, MAX_RULES-1)
    selected = count_logits.gather(1, (k-1).unsqueeze(1))
    tail = torch.arange(MAX_RULES).unsqueeze(0) >= k.unsqueeze(1)
    relative = (count_logits-selected).masked_fill(~tail, float("-inf"))
    normalizer = torch.zeros_like(count_logits).masked_fill(~tail, float("-inf"))
    correction = torch.logsumexp(normalizer, dim=1)-torch.logsumexp(relative, dim=1)
    _require(bool(torch.isfinite(correction).all()), "nonfinite cardinality odds correction")
    return torch.where(active, correction, torch.zeros_like(correction))


def bind_cardinality_model(model, *, codec, guide_boundary=False):
    """Copy a published v2 bound model; both guidance modes add the same head."""
    torch = core._torch()
    core._model(model, torch)
    _require(type(guide_boundary) is bool and callable(getattr(model, "describe", None)), "explicit guidance mode required")
    description = model.describe()
    _require(description.get("schema") == conditioning.SCHEMA
        and description.get("architecture") == conditioning.ARCHITECTURE
        and description.get("state_layout") == ["recurrent_hidden", "projected_source", "consumed_prefix_position"],
        "published persistent-source adapter required")
    specification = conditioning._body_spec(model.body, model.dimension, torch)
    tables = _tables(codec, specification["vocabulary_size"], torch)
    codec_sha256 = core.digest(codec)
    inherited_digest = core.tensor_digest(model)

    class CardinalityDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension
            with torch.random.fork_rng(devices=[]):
                self.count_head = torch.nn.Linear(specification["hidden_width"], MAX_RULES, dtype=torch.float32)
            with torch.no_grad():
                self.count_head.weight.zero_(); self.count_head.bias.zero_()
            _require(core.tensor_digest(self.body) == inherited_digest, "private inherited adapter changed")

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            hidden = self.body.start(projected)[0]
            values = self.count_head(hidden.squeeze(0))
            _require(bool(torch.isfinite(values).all()), "nonfinite source count prediction")
            return values

        def start(self, projected):
            base_state = self.body.start(projected)
            logits = self.count_head(base_state[0].squeeze(0))
            _require(bool(torch.isfinite(logits).all()), "nonfinite source count prediction")
            grammar = torch.zeros((len(projected), 6), dtype=torch.long)
            return (*base_state, logits, grammar)

        def next_logits(self, tokens, state):
            _require(type(state) is tuple and len(state) == 5, "explicit decoder/count/grammar state required")
            hidden, source, position, counts, grammar = state
            _require(isinstance(counts, torch.Tensor) and counts.device.type == "cpu" and counts.dtype == torch.float32
                and tuple(counts.shape) == (len(tokens), MAX_RULES) and bool(torch.isfinite(counts).all()),
                "finite source count state required")
            _require(isinstance(grammar, torch.Tensor) and grammar.device.type == "cpu" and grammar.dtype == torch.long
                and tuple(grammar.shape) == (len(tokens), 6) and bool((grammar[:, 0] >= 0).all())
                and bool((grammar[:, 0] <= _INVALID).all()) and bool((grammar[:, 1:] >= 0).all())
                and bool((grammar[:, 1] <= 127).all()) and bool((grammar[:, 2] <= 6).all())
                and bool((grammar[:, 3] <= 1023).all()) and bool((grammar[:, 4] <= 4).all())
                and bool((grammar[:, 5] <= specification["vocabulary_size"]).all()), "bounded lexical grammar state required")
            logits, next_base = self.body.next_logits(tokens, (hidden, source, position))
            final, boundaries = _scan_prefix(tokens.tolist(), grammar.tolist(), tables)
            tracked = torch.tensor(final, dtype=torch.long)
            if guide_boundary and boundaries:
                locations = torch.tensor(boundaries, dtype=torch.long)
                batch, offset, completed = locations.unbind(1)
                correction = boundary_log_odds(counts[batch], completed)
                # One differentiable vector operation for all observed rule
                # boundaries; parsing itself contains no tensor/autograd work.
                flat_indices = batch*tokens.shape[1]+offset
                adjustments = logits.new_zeros(len(tokens)*tokens.shape[1]).scatter(0, flat_indices, correction)
                closing = logits.new_zeros(specification["vocabulary_size"])
                closing[tables[0]["]"]] = 1.
                logits = logits + adjustments.reshape(*tokens.shape, 1)*closing
                _require(bool(torch.isfinite(logits).all()), "nonfinite guided token logits")
            return logits, (*next_base, counts, tracked)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, dimension=self.dimension, guide_boundary=guide_boundary,
                inherited_architecture=conditioning.ARCHITECTURE, inherited_weights_sha256=inherited_digest,
                inherited_conditioning=description["conditioning"], codec_sha256=codec_sha256,
                count_classes=list(range(1, MAX_RULES+1)), count_features="inherited_source_initial_hidden",
                count_parameter_names=["count_head.weight", "count_head.bias"],
                count_parameter_count=MAX_RULES*(specification["hidden_width"]+1),
                count_head_zero_initialized=True, initial_decoder_logits_unchanged=True,
                guidance="source_predicted_count_log_odds_at_complete_rule_close_only",
                guidance_inactive_at_or_above_count=MAX_RULES, guidance_forces_closure=False,
                parser_scope="seven_exact_facets_string_scalars_sorted_unique_string_qualifiers_max4",
                parser_is_semantic_validator=False, invalid_prefix_guidance="permanently_disabled",
                decoder_reference_count_access=False, source_cache_on_module=False,
                encoder_context_changed=False, output_budget_changed=False,
                scope="exposed_development_only", production_runtime_compatible=False, **FALSE)

    return CardinalityDecoder()


def bind_zero_condition_model(model):
    """Source-free control retaining learned count-head bias as a global prior."""
    torch = core._torch()
    core._model(model, torch)
    _require(callable(getattr(model, "describe", None)) and model.describe().get("schema") == SCHEMA,
        "cardinality model required for complete source ablation")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            hidden = self.body.body.start(projected)[0]
            return self.body.count_head(torch.zeros_like(hidden.squeeze(0)))

        def start(self, projected):
            hidden, source, position, _, grammar = self.body.start(projected)
            counts = self.body.count_head(torch.zeros_like(hidden.squeeze(0)))
            return torch.zeros_like(hidden), torch.zeros_like(source), position, counts, grammar

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema="zero-source-cardinality-control/v1", dimension=self.dimension,
                initial_hidden_zeroed=True, persistent_source_zeroed=True, count_source_features_zeroed=True,
                count_bias_retained_as_source_independent_prior=True, projection_preserved=True,
                prefix_and_parser_state_preserved=True, scope="development_ablation_only", **FALSE)

    return ZeroCondition()
