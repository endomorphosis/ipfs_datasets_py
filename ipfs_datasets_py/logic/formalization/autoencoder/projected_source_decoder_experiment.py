"""Private projected-source scalar/count readouts for Legal decoder development.

Training-only feature statistics and a smoothed training count prior are frozen
buffers. Generation receives source vectors and its own causal prefix only.
Count guidance is a soft log-odds residual relative to the training prior, not a
hard count, grammar mask, or closure rule. This owner grants no qualification.
"""
from copy import deepcopy
import math

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import decoder_distillation_experiment_v2 as conditioning
from . import source_value_decoder_experiment as source_values

SCHEMA = "projected-source-decoder-development/v1"
NORMALIZATION_SCHEMA = "training-source-normalization/v1"
PRIOR_SCHEMA = "training-source-count-prior/v1"
SOURCE_FIELDS = source_values.SOURCE_FIELDS
MAX_RULES = source_values.MAX_RULES
MAX_COUNTS = cardinality.MAX_RULES
FALSE = dict(source_values.FALSE)
_require = core._require


def _identities(rows, expected_training_ids, forbidden_validation_ids, training_rows_sha256, fields):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded training-only rows required")
    _require(type(expected_training_ids) is list and len(expected_training_ids) == len(rows)
        and all(type(value) is str and 0 < len(value) <= 512 for value in expected_training_ids)
        and len(set(expected_training_ids)) == len(expected_training_ids), "exact unique training identities required")
    _require(type(forbidden_validation_ids) is list
        and all(type(value) is str and 0 < len(value) <= 512 for value in forbidden_validation_ids)
        and len(set(forbidden_validation_ids)) == len(forbidden_validation_ids)
        and not set(expected_training_ids) & set(forbidden_validation_ids), "training/validation identity contamination")
    _require(type(training_rows_sha256) is str and core._SHA.fullmatch(training_rows_sha256),
        "authenticated training row digest required")
    inventory = []
    for row in rows:
        _require(type(row) is dict and set(row) == fields
            and type(row.get("id")) is str and row["id"] in expected_training_ids
            and type(row.get("source_sha256")) is str and core._SHA.fullmatch(row["source_sha256"]),
            "closed source-bound training row required")
        inventory.append(dict(id=row["id"], source_sha256=row["source_sha256"]))
    _require(len({row["id"] for row in inventory}) == len(rows)
        and {row["id"] for row in inventory} == set(expected_training_ids), "training inventory differs")
    return inventory


def fit_source_normalization(feature_rows, *, kind, expected_training_ids,
                             forbidden_validation_ids, training_rows_sha256):
    """Freeze training-only mean/global centered RMS, or an identity transform.

Rows are exactly ``id, source_sha256, features`` with actual projected vectors.
The caller authenticates their projection and source-row digest. Neither text,
targets, reference prefixes, nor validation features are accepted here.
"""
    _require(kind in ("none", "center_rms"), "explicit supported normalization required")
    inventory = _identities(feature_rows, expected_training_ids, forbidden_validation_ids,
        training_rows_sha256, {"id", "source_sha256", "features"})
    dimension = len(feature_rows[0]["features"]) if type(feature_rows[0]["features"]) is list else 0
    _require(dimension in (8, 384, 768), "explicit supported projected source dimension required")
    for row in feature_rows:
        core._vector(row["features"], dimension)
    _require(len(core._raw(feature_rows)) <= 67108864, "training feature serialization exceeds bound")
    torch = core._torch()
    with torch.inference_mode():
        features = torch.tensor([row["features"] for row in feature_rows], dtype=torch.float64)
        mean = features.mean(0)
        centered = features - mean
        energy = float(centered.square().sum()/len(features))
        _require(math.isfinite(energy) and energy >= 0., "nonfinite training feature energy")
        constant = energy == 0.
        _require(not constant or not bool(centered.any()), "training feature RMS underflow")
        fitted_scale = 1. if constant else math.sqrt(energy)
        actual_mean = mean if kind == "center_rms" else torch.zeros(dimension, dtype=torch.float64)
        actual_scale = fitted_scale if kind == "center_rms" else 1.
        _require(bool(torch.isfinite(actual_mean.float()).all())
            and math.isfinite(float(torch.tensor(actual_scale, dtype=torch.float32)))
            and float(torch.tensor(actual_scale, dtype=torch.float32)) > 0., "unrepresentable float32 normalization")
    receipt = dict(schema=NORMALIZATION_SCHEMA, kind=kind, dimension=dimension,
        mean=actual_mean.tolist(), scale=actual_scale,
        fitted_training_mean=mean.tolist(), fitted_training_scale=fitted_scale,
        fitted_training_centered_row_squared_norm=energy, constant_training_features=constant,
        normalization="identity" if kind == "none" else "center_then_global_RMS_of_row_L2_norm",
        statistics_dtype="float64", model_buffer_dtype="float32", fitted_rows=len(feature_rows),
        training_inventory=inventory, training_feature_rows_sha256=core.digest(feature_rows),
        training_rows_sha256=training_rows_sha256, expected_training_ids=list(expected_training_ids),
        forbidden_validation_ids=list(forbidden_validation_ids), validation_rows_used_for_fitting=0,
        projection_provenance="caller_authenticates_exact_frozen_projection_and_projected_feature_rows",
        scope="training_only_frozen_transform", **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return receipt


def fit_source_count_prior(training_count_rows, *, expected_training_ids,
                           forbidden_validation_ids, training_rows_sha256):
    """Fit a fixed Dirichlet(total1) prior with positive support for all32counts."""
    inventory = _identities(training_count_rows, expected_training_ids, forbidden_validation_ids,
        training_rows_sha256, {"id", "source_sha256", "count"})
    counts = [0]*MAX_COUNTS
    for row in training_count_rows:
        _require(type(row["count"]) is int and 1 <= row["count"] <= MAX_COUNTS,
            "bounded integer training count required")
        counts[row["count"]-1] += 1
    alpha = 1./MAX_COUNTS
    denominator = len(training_count_rows)+1.
    probabilities = [(count+alpha)/denominator for count in counts]
    torch = core._torch()
    log_prior = torch.tensor(probabilities, dtype=torch.float32).log().tolist()
    receipt = dict(schema=PRIOR_SCHEMA, count_classes=list(range(1, MAX_COUNTS+1)),
        class_counts=counts, alpha_per_class=alpha, total_pseudocount=1.,
        smoothing="fixed_symmetric_Dirichlet_total_one_all_32_classes",
        probabilities=probabilities, log_prior=log_prior, dtype="float32", fitted_rows=len(training_count_rows),
        training_inventory=inventory, training_count_rows_sha256=core.digest(training_count_rows),
        training_rows_sha256=training_rows_sha256, expected_training_ids=list(expected_training_ids),
        forbidden_validation_ids=list(forbidden_validation_ids), validation_rows_used_for_fitting=0,
        target_access="authenticated_training_count_labels_only", generation_reference_count_access=False,
        scope="training_only_frozen_count_prior", **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return receipt


def _checked_receipts(normalization, prior, dimension):
    for receipt, schema in ((normalization, NORMALIZATION_SCHEMA), (prior, PRIOR_SCHEMA)):
        _require(type(receipt) is dict and receipt.get("schema") == schema
            and receipt.get("receipt_sha256") == core.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"}),
            "frozen training receipt digest differs")
        _require(all(receipt.get(key) is False for key in FALSE)
            and receipt.get("validation_rows_used_for_fitting") == 0,
            "training receipt qualification or split policy differs")
        inventory = receipt.get("training_inventory")
        _identities(inventory, receipt.get("expected_training_ids"), receipt.get("forbidden_validation_ids"),
            receipt.get("training_rows_sha256"), {"id", "source_sha256"})
        _require(receipt.get("fitted_rows") == len(inventory), "training receipt row count differs")
    _require(normalization.get("dimension") == dimension and normalization.get("kind") in ("none", "center_rms")
        and type(normalization.get("scale")) in (int, float) and math.isfinite(normalization["scale"])
        and normalization["scale"] > 0., "normalization geometry differs")
    core._vector(normalization.get("mean"), dimension)
    core._vector(normalization.get("fitted_training_mean"), dimension)
    energy = normalization.get("fitted_training_centered_row_squared_norm")
    _require(type(energy) in (int, float) and math.isfinite(energy) and energy >= 0.
        and type(normalization.get("constant_training_features")) is bool
        and normalization["constant_training_features"] == (energy == 0.)
        and normalization.get("fitted_training_scale") == (1. if energy == 0. else math.sqrt(energy)),
        "normalization fitted statistics differ")
    _require(normalization["mean"] == (normalization["fitted_training_mean"] if normalization["kind"] == "center_rms" else [0.]*dimension)
        and normalization["scale"] == (normalization["fitted_training_scale"] if normalization["kind"] == "center_rms" else 1.),
        "normalization transformation differs from frozen fit")
    _require(normalization["training_inventory"] == prior["training_inventory"]
        and normalization["training_rows_sha256"] == prior["training_rows_sha256"]
        and normalization["expected_training_ids"] == prior["expected_training_ids"]
        and normalization["forbidden_validation_ids"] == prior["forbidden_validation_ids"],
        "feature and count prior training inventories differ")
    counts = prior.get("class_counts")
    _require(type(counts) is list and len(counts) == MAX_COUNTS
        and all(type(value) is int and value >= 0 for value in counts)
        and sum(counts) == prior["fitted_rows"] and prior.get("alpha_per_class") == 1./MAX_COUNTS
        and prior.get("total_pseudocount") == 1.
        and prior.get("count_classes") == list(range(1, MAX_COUNTS+1)), "count prior support differs")
    probabilities = [(value+1./MAX_COUNTS)/(sum(counts)+1.) for value in counts]
    torch = core._torch()
    _require(prior.get("probabilities") == probabilities
        and prior.get("log_prior") == torch.tensor(probabilities, dtype=torch.float32).log().tolist(),
        "count prior does not match smoothed training counts")


def prior_centered_boundary_log_odds(count_logits, completed_rules, prior_logits):
    """Soft stop-vs-tail odds relative to the fixed training count prior.

At the prior itself this expression is bit-exact zero. Counts >=32 have no
correction. The prior has positive support for all32classes; no class is masked
from count prediction. The tail mask describes survival beyond a causal count.
"""
    torch = core._torch()
    _require(isinstance(count_logits, torch.Tensor) and count_logits.dtype == torch.float32
        and count_logits.device.type == "cpu" and count_logits.ndim == 2
        and tuple(count_logits.shape[1:]) == (MAX_COUNTS,) and bool(torch.isfinite(count_logits).all()),
        "finite CPU count logits required")
    _require(isinstance(prior_logits, torch.Tensor) and prior_logits.dtype == torch.float32
        and prior_logits.device.type == "cpu" and tuple(prior_logits.shape) == (MAX_COUNTS,)
        and bool(torch.isfinite(prior_logits).all()), "finite frozen count prior logits required")
    _require(isinstance(completed_rules, torch.Tensor) and completed_rules.dtype == torch.long
        and completed_rules.device.type == "cpu" and tuple(completed_rules.shape) == (len(count_logits),)
        and bool((completed_rules >= 0).all()), "explicit causal completed-rule counts required")
    active = (completed_rules >= 1) & (completed_rules < MAX_COUNTS)
    k = completed_rules.clamp(1, MAX_COUNTS-1)
    tail = torch.arange(MAX_COUNTS).unsqueeze(0) >= k.unsqueeze(1)
    prior = prior_logits.unsqueeze(0).expand_as(count_logits)
    relative = (count_logits-count_logits.gather(1, (k-1).unsqueeze(1))).masked_fill(~tail, float("-inf"))
    prior_relative = (prior-prior.gather(1, (k-1).unsqueeze(1))).masked_fill(~tail, float("-inf"))
    result = torch.logsumexp(prior_relative, dim=1)-torch.logsumexp(relative, dim=1)
    _require(bool(torch.isfinite(result).all()), "nonfinite prior-centered boundary correction")
    return torch.where(active, result, torch.zeros_like(result))


def bind_projected_source_model(model, *, codec, normalization_receipt,
                                count_prior_receipt, guide_boundary=False, scalar_guidance=True):
    """Copy a persistent-source decoder; add independent projected-source heads.

The source-value and count residual heads start at zero. Count logits include a
frozen fitted prior. Initial generated logits equal the inherited model exactly
in both guidance modes. Projection parameters are frozen in the private copy.
"""
    torch = core._torch()
    core._model(model, torch)
    _require(type(guide_boundary) is bool and type(scalar_guidance) is bool,
        "explicit Boolean guidance controls required")
    description = model.describe()
    _require(description.get("schema") == conditioning.SCHEMA
        and description.get("architecture") == conditioning.ARCHITECTURE,
        "published persistent-source decoder required")
    specification = conditioning._body_spec(model.body, model.dimension, torch)
    _checked_receipts(normalization_receipt, count_prior_receipt, model.dimension)
    normalization = deepcopy(normalization_receipt)
    prior = deepcopy(count_prior_receipt)
    size = specification["vocabulary_size"]
    tables = cardinality._tables(codec, size, torch)
    added = (model.dimension+1)*(MAX_COUNTS+MAX_RULES*len(SOURCE_FIELDS)*size)
    _require(added*4 <= 67108864, "projected source head allocation exceeds64MiB")
    inherited_digest = core.tensor_digest(model)
    fixed_buffers = dict(source_mean=torch.tensor(normalization["mean"], dtype=torch.float32),
        source_scale=torch.tensor(normalization["scale"], dtype=torch.float32),
        count_prior_logits=torch.tensor(prior["log_prior"], dtype=torch.float32))

    class ProjectedSourceDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension
            for name, parameter in self.body.named_parameters():
                if name.startswith(("body.projection_down.", "body.projection_up.")):
                    parameter.requires_grad_(False)
            for name, value in fixed_buffers.items():
                self.register_buffer(name, value.clone())
            _require(bool(torch.isfinite(self.source_mean).all()) and bool(torch.isfinite(self.source_scale))
                and float(self.source_scale) > 0., "unrepresentable model normalization")
            with torch.random.fork_rng(devices=[]):
                self.count_head = torch.nn.Linear(self.dimension, MAX_COUNTS, dtype=torch.float32)
                self.source_value_head = torch.nn.Linear(self.dimension, MAX_RULES*len(SOURCE_FIELDS)*size, dtype=torch.float32)
            with torch.no_grad():
                for head in (self.count_head, self.source_value_head):
                    head.weight.zero_(); head.bias.zero_()
            _require(core.tensor_digest(self.body) == inherited_digest, "private inherited decoder changed")

        def load_state_dict(self, state_dict, strict=True, assign=False):
            # A saved candidate cannot silently substitute normalization or
            # count-prior statistics while retaining this architecture receipt.
            for name, expected in fixed_buffers.items():
                actual = state_dict.get(name)
                _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                    and actual.device.type == "cpu" and tuple(actual.shape) == tuple(expected.shape)
                    and torch.equal(actual, expected), "restored frozen source buffer differs: "+name)
            return super().load_state_dict(state_dict, strict=strict, assign=assign)

        def project(self, values):
            return self.body.project(values)

        def _features(self, projected):
            self.body._inputs(projected)
            features = (projected-self.source_mean)/self.source_scale
            _require(bool(torch.isfinite(features).all()), "nonfinite normalized source features")
            return features

        def _counts(self, features):
            logits = self.count_head(features)+self.count_prior_logits
            _require(bool(torch.isfinite(logits).all()), "nonfinite projected count logits")
            return logits

        def _values(self, features):
            logits = self.source_value_head(features).reshape(len(features), MAX_RULES, len(SOURCE_FIELDS), size)
            _require(bool(torch.isfinite(logits).all()), "nonfinite projected scalar logits")
            return logits

        def count_logits(self, projected):
            return self._counts(self._features(projected))

        def source_value_logits(self, projected):
            return self._values(self._features(projected))

        def start(self, projected):
            base = self.body.start(projected)
            features = self._features(projected)
            grammar = torch.zeros((len(projected), 6), dtype=torch.long)
            return (*base, self._counts(features), grammar, self._values(features))

        def next_logits(self, tokens, state):
            _require(type(state) is tuple and len(state) == 6, "explicit recurrent/count/grammar/value state required")
            counts, grammar, values = state[3:]
            _require(isinstance(counts, torch.Tensor) and counts.dtype == torch.float32
                and counts.device.type == "cpu" and tuple(counts.shape) == (len(tokens), MAX_COUNTS)
                and bool(torch.isfinite(counts).all()), "finite source count state required")
            _require(isinstance(values, torch.Tensor) and values.dtype == torch.float32
                and values.device.type == "cpu" and tuple(values.shape) == (len(tokens), MAX_RULES, len(SOURCE_FIELDS), size)
                and bool(torch.isfinite(values).all()), "finite source value state required")
            _require(isinstance(grammar, torch.Tensor) and grammar.dtype == torch.long
                and grammar.device.type == "cpu" and tuple(grammar.shape) == (len(tokens), 6)
                and bool((grammar >= 0).all()) and bool((grammar[:, 0] <= cardinality._INVALID).all())
                and bool((grammar[:, 1] <= 127).all()) and bool((grammar[:, 2] <= 6).all())
                and bool((grammar[:, 3] <= 1023).all()) and bool((grammar[:, 4] <= 4).all())
                and bool((grammar[:, 5] <= size).all()), "bounded causal grammar state required")
            logits, next_base = self.body.next_logits(tokens, state[:3])
            final, boundaries = cardinality._scan_prefix(tokens.tolist(), grammar.tolist(), tables)
            value_final, sites = source_values._scan_value_prefix(tokens.tolist(), grammar.tolist(), tables, MAX_RULES)
            _require(final == value_final, "causal cardinality/value recognizers disagree")
            if guide_boundary and boundaries:
                locations = torch.tensor(boundaries, dtype=torch.long)
                batch, offset, completed = locations.unbind(1)
                correction = prior_centered_boundary_log_odds(counts[batch], completed, self.count_prior_logits)
                flat = batch*tokens.shape[1]+offset
                adjustment = logits.new_zeros(len(tokens)*tokens.shape[1]).scatter(0, flat, correction)
                closing = logits.new_zeros(size); closing[tables[0]["]"]] = 1.
                logits = logits + adjustment.reshape(*tokens.shape, 1)*closing
            if scalar_guidance and sites:
                locations = torch.tensor(sites, dtype=torch.long)
                batch, offset, slot, field = locations.unbind(1)
                flat = batch*tokens.shape[1]+offset
                residual = logits.new_zeros(len(tokens)*tokens.shape[1], size).index_add(0, flat, values[batch, slot, field])
                logits = logits + residual.reshape_as(logits)
            _require(bool(torch.isfinite(logits).all()), "nonfinite projected-source decoder logits")
            return logits, (*next_base, counts, torch.tensor(final, dtype=torch.long), values)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, dimension=self.dimension, feature_kind="projected_source",
                feature_dimension=self.dimension, max_rules=MAX_RULES, source_fields=list(SOURCE_FIELDS),
                vocabulary_size=size, codec_sha256=core.digest(codec), guidance=scalar_guidance,
                guide_boundary=guide_boundary, count_classes=list(range(1, MAX_COUNTS+1)),
                count_features="normalized_projected_source", normalization=deepcopy(normalization),
                count_prior=deepcopy(prior), count_residual_head_zero_initialized=True,
                initial_count_logits="frozen_smoothed_training_log_prior_plus_zero_learned_residual",
                source_value_head_zero_initialized=True, initial_decoder_logits_unchanged=True,
                inherited_weights_sha256=inherited_digest, inherited_architecture=deepcopy(description),
                source_value_parameter_count=(self.dimension+1)*MAX_RULES*len(SOURCE_FIELDS)*size,
                count_parameter_count=(self.dimension+1)*MAX_COUNTS,
                source_value_parameter_names=["source_value_head.weight", "source_value_head.bias"],
                count_parameter_names=["count_head.weight", "count_head.bias"],
                guidance_kind="source_count_stop_vs_tail_log_odds_minus_frozen_training_prior_log_odds",
                guidance_inactive_at_or_above_count=MAX_COUNTS,
                scalar_guidance_kind="soft_full_vocabulary_residual_at_causal_scalar_colon",
                output_support="complete_inherited_vocabulary", count_support="all_32_positive_prior_classes",
                projection_frozen=True, normalization_statistics_frozen=True, count_prior_frozen=True,
                source_value_target_access_during_generation=False, source_reference_count_access=False,
                source_context_cached_on_module=False, invalid_prefix_guidance="permanently_disabled",
                parser_is_semantic_validator=False, syntax_forced=False, closure_forced=False,
                state_layout=["recurrent_hidden", "projected_source", "consumed_prefix_position",
                    "source_count_logits", "causal_grammar_state", "source_value_logits"],
                encoder_context_changed=False, output_budget_changed=False,
                scope="exposed_development_only", production_runtime_compatible=False, **FALSE)

    return ProjectedSourceDecoder()


def bind_zero_condition_model(model):
    """Zero recurrent source and normalized head features, retaining learned priors.

For centered features, the heads see the training feature mean. For the identity
transform they see the origin. All source-independent head biases are retained.
"""
    torch = core._torch()
    core._model(model, torch)
    _require(model.describe().get("schema") == SCHEMA, "projected-source model required")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension

        def project(self, values):
            return self.body.project(values)

        def _zero_features(self, projected):
            self.body.body._inputs(projected)
            return torch.zeros_like(projected)

        def count_logits(self, projected):
            return self.body._counts(self._zero_features(projected))

        def source_value_logits(self, projected):
            return self.body._values(self._zero_features(projected))

        def start(self, projected):
            hidden, source, position = self.body.body.start(projected)
            zeros = self._zero_features(projected)
            return (torch.zeros_like(hidden), torch.zeros_like(source), position,
                self.body._counts(zeros), torch.zeros((len(projected), 6), dtype=torch.long), self.body._values(zeros))

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema="zero-projected-source-control/v1", dimension=self.dimension,
                initial_hidden_zeroed=True, persistent_source_zeroed=True,
                normalized_count_and_scalar_source_features_zeroed=True,
                head_biases_and_frozen_count_prior_retained=True,
                zero_feature_interpretation="training_mean" if model.describe()["normalization"]["kind"] == "center_rms" else "raw_origin",
                projection_preserved=True, prefix_and_parser_state_preserved=True,
                scope="development_ablation_only", **FALSE)

    return ZeroCondition()
