"""Private source-value residual for exposed Legal decoder development.

The source readout predicts full-vocabulary logits for ordered scalar slots.
Only a causal, already-consumed prefix can select a slot during generation.
There is no target/count access, hard token mask, forced syntax, or closure.
Existing model and qualification policies remain unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import json

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from .long_span_decoder_training import reference_weights

SCHEMA = "source-value-decoder-development/v1"
SOURCE_FIELDS = ("actor", "action", "modality", "object")
MAX_RULES = 8
FALSE = dict(core.FALSE, native_family_validation_performed=False, lake_executed=False,
             convergence_proven=False, fresh_holdout=False)
_require = core._require


def _scan_value_prefix(token_rows, state_rows, tables, max_rules):
    """Recognize scalar-value sites after consumed colons, never future tokens.

    This follows the cardinality recognizer's lexical grammar exactly. The
    caller checks its final state against that recognizer on every invocation.
    A quoted field name used as a scalar value cannot create another site.
    """
    ids, string_rank, field_index, modality = tables
    source_field_index = {cardinality.FIELDS.index(name): index for index, name in enumerate(SOURCE_FIELDS)}
    final, sites = [], []
    for batch, (tokens, original) in enumerate(zip(token_rows, state_rows)):
        phase, seen, pending, count, length, last = original
        for offset, token in enumerate(tokens):
            rank, field = string_rank[token], field_index[token]
            following = cardinality._INVALID
            if phase == 0 and token == 1: following = 1
            elif phase == 1 and token == ids["{"]: following = 2
            elif phase == 2 and token == ids['"rules"']: following = 3
            elif phase == 3 and token == ids[":"]: following = 4
            elif phase == 4 and token == ids["["]: following = 5
            elif phase in (5, 14) and token == ids["{"]: following, seen = 6, 0
            elif phase == 6 and field >= 0 and not seen & (1 << field):
                following, seen, pending = 7, seen | (1 << field), field
            elif phase == 7 and token == ids[":"]:
                following = 8
                if pending in source_field_index and count < max_rules:
                    sites.append((batch, offset, count, source_field_index[pending]))
            elif phase == 8:
                if pending < 4 and rank > 0 and (pending != 0 or modality[token]): following = 9
                elif pending >= 4 and token == ids["["]: following, length, last = 10, 0, 0
            elif phase == 10 and token == ids["]"]: following = 9
            elif phase in (10, 12) and rank > last and rank > 0 and length < 4:
                following, length, last = 11, length + 1, rank
            elif phase == 11 and token == ids[","]: following = 12
            elif phase == 11 and token == ids["]"]: following = 9
            elif phase == 9 and token == ids[","]: following = 6
            elif phase == 9 and seen == 127 and token == ids["}"]: following, count = 13, count + 1
            elif phase == 13 and token == ids[","]: following = 14
            elif phase == 13 and token == ids["]"]: following = 15
            elif phase == 15 and token == ids["}"]: following = 16
            elif phase == 16 and token == 2: following = 17
            elif phase == 17 and token == 0: following = 17
            phase = following
        final.append([phase, seen, pending, count, length, last])
    return final, sites


def reference_source_values(rows, references, codec, *, validate_rule, max_rules=MAX_RULES):
    """Authenticate full training targets, then extract present scalar labels.

    Return ``id -> [slot][field]`` vocabulary IDs; absent slots use ``-1`` and
    must be ignored by auxiliary CE. This is training/evaluation preparation,
    not a generation API. Qualifiers still receive the complete sequence loss.
    """
    _require(type(max_rules) is int and 1 <= max_rules <= MAX_RULES, "bounded source slot count required")
    reference_weights(rows, references, codec, strategy="reference_ce", validate_rule=validate_rule)
    positions = {token: index for index, token in enumerate(codec["target_vocabulary"])}
    result = {}
    for reference in references:
        rules = reference["target"]["rules"]
        _require(len(rules) <= max_rules, "reference exceeds source slot coverage")
        labels = [[-1] * len(SOURCE_FIELDS) for _ in range(max_rules)]
        for slot, rule in enumerate(rules):
            for field, name in enumerate(SOURCE_FIELDS):
                value = rule.get(name)
                _require(type(value) is str, "complete scalar string source values required")
                token = json.dumps(value, ensure_ascii=True, allow_nan=False)
                _require(token in positions and positions[token] >= 3, "source scalar outside inherited lexical vocabulary")
                labels[slot][field] = positions[token]
        result[reference["id"]] = labels
    return result


def bind_source_value_model(model, *, codec, feature_kind="projected_source", max_rules=MAX_RULES,
                            guidance=True):
    """Copy a cardinality model and add zero-initialized source slot logits.

    ``feature_kind`` selects the actual projected vector or the concatenation
    of initial recurrent hidden and persistent source-embedding residual.
    Their dimensions and parameter counts are reported, not capacity-matched.
    Caller trainability is preserved; the new head starts trainable. Its
    auxiliary loss is owned separately by the training adapter.
    """
    torch = core._torch()
    core._model(model, torch)
    _require(type(guidance) is bool and feature_kind in ("projected_source", "inherited_conditioning"),
        "explicit source feature/guidance mode required")
    _require(type(max_rules) is int and 1 <= max_rules <= MAX_RULES, "bounded source slot count required")
    description = model.describe()
    _require(description.get("schema") == cardinality.SCHEMA
        and description.get("codec_sha256") == core.digest(codec), "matching inherited cardinality model required")
    specification = cardinality.conditioning._body_spec(model.body.body, model.dimension, torch)
    size = specification["vocabulary_size"]
    tables = cardinality._tables(codec, size, torch)
    feature_dimension = (model.dimension if feature_kind == "projected_source" else
        specification["hidden_width"] + specification["token_embedding_width"])
    # Construction bounds include parameters and the largest allowed batch's
    # output scores, before making a private model copy.
    added_parameters = (feature_dimension + 1) * max_rules * len(SOURCE_FIELDS) * size
    _require(added_parameters * 4 <= 67108864, "source head parameter allocation exceeds 64 MiB")
    inherited_digest = core.tensor_digest(model)

    class SourceValueDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension
            with torch.random.fork_rng(devices=[]):
                self.source_value_head = torch.nn.Linear(feature_dimension,
                    max_rules * len(SOURCE_FIELDS) * size, dtype=torch.float32)
            with torch.no_grad():
                self.source_value_head.weight.zero_()
                self.source_value_head.bias.zero_()
            _require(core.tensor_digest(self.body) == inherited_digest, "private inherited source model changed")

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            return self.body.count_logits(projected)

        def _features(self, projected, base_state=None):
            # This also enforces the inherited input geometry and CPU bounds.
            self.body.body._inputs(projected)
            if feature_kind == "projected_source":
                features = projected
            else:
                hidden = (self.body.start(projected) if base_state is None else base_state)[0].squeeze(0)
                persistent = self.body.body.source_to_embedding(projected)
                features = torch.cat((hidden, persistent), dim=1)
            _require(tuple(features.shape) == (len(projected), feature_dimension)
                and bool(torch.isfinite(features).all()), "finite actual source feature geometry required")
            return features

        def _head(self, features):
            values = self.source_value_head(features).reshape(len(features), max_rules, len(SOURCE_FIELDS), size)
            _require(bool(torch.isfinite(values).all()), "nonfinite source scalar logits")
            return values

        def source_value_logits(self, projected):
            return self._head(self._features(projected))

        def start(self, projected):
            base = self.body.start(projected)
            return (*base, self._head(self._features(projected, base)))

        def next_logits(self, tokens, state):
            _require(type(state) is tuple and len(state) == 6, "explicit decoder/count/grammar/value state required")
            values = state[-1]
            _require(isinstance(values, torch.Tensor) and values.device.type == "cpu" and values.dtype == torch.float32
                and tuple(values.shape) == (len(tokens), max_rules, len(SOURCE_FIELDS), size)
                and bool(torch.isfinite(values).all()), "finite bounded source value state required")
            logits, updated = self.body.next_logits(tokens, state[:5])
            final, sites = _scan_value_prefix(tokens.tolist(), state[4].tolist(), tables, max_rules)
            _require(final == updated[4].tolist(), "source value and cardinality recognizers disagree")
            if guidance and sites:
                locations = torch.tensor(sites, dtype=torch.long)
                batch, offset, slot, field = locations.unbind(1)
                # Each consumed token has at most one scalar-value site.
                # Scatter adds a soft full-vocabulary residual; no mask or
                # token override can convert it into forced syntax.
                flat = batch * tokens.shape[1] + offset
                residual = logits.new_zeros(len(tokens) * tokens.shape[1], size).index_add(
                    0, flat, values[batch, slot, field])
                logits = logits + residual.reshape_as(logits)
                _require(bool(torch.isfinite(logits).all()), "nonfinite source-guided token logits")
            return logits, (*updated, values)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, dimension=self.dimension, feature_kind=feature_kind,
                feature_dimension=feature_dimension, max_rules=max_rules, source_fields=list(SOURCE_FIELDS),
                vocabulary_size=size, codec_sha256=core.digest(codec), guidance=guidance,
                inherited_weights_sha256=inherited_digest, inherited_architecture=deepcopy(description),
                source_value_parameter_names=["source_value_head.weight", "source_value_head.bias"],
                source_value_parameter_count=added_parameters, initial_source_head_zero_initialized=True,
                initial_decoder_logits_unchanged=True, output_support="complete_inherited_vocabulary",
                source_value_target_access_during_generation=False, source_reference_count_access=False,
                source_value_sites="causal_scalar_field_colon_in_top_level_ordered_rule",
                source_value_guidance_above_max_rules="inactive_without_truncation_or_forced_closure",
                invalid_prefix_guidance="permanently_disabled", parser_is_semantic_validator=False,
                syntax_forced=False, closure_forced=False, source_context_cached_on_module=False,
                state_layout=["recurrent_hidden", "projected_source", "consumed_prefix_position",
                    "source_count_logits", "causal_grammar_state", "source_value_logits"],
                encoder_context_changed=False, output_budget_changed=False, scope="exposed_development_only",
                production_runtime_compatible=False, **FALSE)

    return SourceValueDecoder()


def bind_zero_condition_model(model):
    """Private source ablation preserving all source-independent head biases."""
    torch = core._torch()
    core._model(model, torch)
    description = model.describe()
    _require(description.get("schema") == SCHEMA, "source value model required")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension

        def project(self, values):
            return self.body.project(values)

        def _zero_values(self, projected):
            self.body.body.body._inputs(projected)
            return self.body._head(projected.new_zeros((len(projected), description["feature_dimension"])))

        def source_value_logits(self, projected):
            return self._zero_values(projected)

        def count_logits(self, projected):
            hidden = self.body.body.body.start(projected)[0].squeeze(0)
            return self.body.body.count_head(torch.zeros_like(hidden))

        def start(self, projected):
            hidden, source, position, _, grammar, _ = self.body.start(projected)
            counts = self.body.body.count_head(torch.zeros_like(hidden.squeeze(0)))
            return torch.zeros_like(hidden), torch.zeros_like(source), position, counts, grammar, self._zero_values(projected)

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema="zero-source-value-control/v1", dimension=self.dimension,
                initial_hidden_zeroed=True, persistent_source_zeroed=True, count_source_features_zeroed=True,
                scalar_source_features_zeroed=True, head_biases_retained_as_source_independent_priors=True,
                projection_preserved=True, prefix_and_parser_state_preserved=True,
                scope="development_ablation_only", **FALSE)

    return ZeroCondition()
