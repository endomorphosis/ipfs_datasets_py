"""Private fixed-state and trainable scalar-evidence centering experiment.

The auxiliary classifier remains raw. Only scalar guidance at the inherited
causal sites is raw, disabled, or centered on authenticated training features.
Centering removes an affine reference score; it is not posterior calibration.
"""
from copy import deepcopy

from . import decoder_distillation_experiment as core
from . import projected_source_decoder_experiment as projected_values

SCHEMA = "mean-centered-source-decoder-development/v1"
SCALAR_MODES = ("raw", "off", "mean_centered")
FALSE = dict(projected_values.FALSE)
_require = core._require


def _reference_receipt(description, receipt, dimension):
    """Bind a fitted reference mean to the base model's actual training cohort."""
    normalization = description["normalization"]
    if receipt is None:
        _require(normalization["kind"] == "center_rms",
            "identity-normalized model requires authenticated centered training receipt")
        receipt = normalization
    _require(type(receipt) is dict and receipt.get("kind") == "center_rms",
        "centered training-only reference receipt required")
    projected_values._checked_receipts(receipt, description["count_prior"], dimension)
    for key in ("training_inventory", "expected_training_ids", "forbidden_validation_ids",
                "training_rows_sha256", "training_feature_rows_sha256", "fitted_training_mean",
                "fitted_training_scale", "fitted_training_centered_row_squared_norm"):
        _require(receipt.get(key) == normalization.get(key),
            "scalar reference mean differs from base training features: " + key)
    return deepcopy(receipt)


def bind_mean_centered_source_model(model, *, scalar_mode="mean_centered",
                                    training_feature_mean_receipt=None):
    """Copy a projected-source model without modifying its count or recurrent paths.

``raw`` retains exact original arithmetic. ``off`` omits scalar guidance but
still exposes the original auxiliary readout. ``mean_centered`` adds
``head(features(x)) - head(features(training_mean))``. Both terms remain in
the training graph, so scalar bias cancels in sequence loss and still receives
raw auxiliary supervision. References and target tokens are never inputs.
"""
    torch = core._torch()
    core._model(model, torch)
    _require(type(scalar_mode) is str and scalar_mode in SCALAR_MODES,
        "explicit supported scalar guidance mode required")
    description = model.describe()
    _require(description.get("schema") == projected_values.SCHEMA
        and description.get("guidance") is True,
        "authenticated projected model with scalar guidance enabled required")
    projected_values._checked_receipts(description["normalization"], description["count_prior"], model.dimension)
    expected_buffers = dict(source_mean=description["normalization"]["mean"],
        source_scale=description["normalization"]["scale"], count_prior_logits=description["count_prior"]["log_prior"])
    for name, value in expected_buffers.items():
        actual = getattr(model, name, None)
        expected = torch.tensor(value, dtype=torch.float32)
        _require(isinstance(actual, torch.Tensor) and actual.dtype == torch.float32
            and actual.device.type == "cpu" and torch.equal(actual, expected),
            "projected base buffer differs from authenticated receipt: "+name)
    reference = _reference_receipt(description, training_feature_mean_receipt, model.dimension)
    raw_mean = (model.source_mean.detach().clone() if description["normalization"]["kind"] == "center_rms"
        else torch.tensor(reference["fitted_training_mean"], dtype=torch.float32))
    frozen = {"body."+name: value.detach().clone() for name, value in model.named_buffers()}
    frozen["source_reference_mean"] = raw_mean.clone()
    inherited_digest = core.tensor_digest(model)

    class MeanCenteredSourceDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = model.dimension
            self.register_buffer("source_reference_mean", raw_mean.clone())
            _require(core.tensor_digest(self.body) == inherited_digest, "private projected base changed")

        def load_state_dict(self, state_dict, strict=True, assign=False):
            # Parent load_state_dict traverses child _load_from_state_dict;
            # it does not invoke the projected child's public load guard.
            for name, expected in frozen.items():
                actual = state_dict.get(name)
                _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                    and actual.device.type == "cpu" and tuple(actual.shape) == tuple(expected.shape)
                    and torch.equal(actual, expected), "restored frozen scalar reference or base buffer differs: "+name)
            return super().load_state_dict(state_dict, strict=strict, assign=assign)

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            return self.body.count_logits(projected)

        def source_value_logits(self, projected):
            # The auxiliary head is an unmodified full-vocabulary classifier.
            return self.body.source_value_logits(projected)

        def _guidance(self, raw_logits):
            if scalar_mode == "raw":
                return raw_logits
            if scalar_mode == "off":
                guided = torch.zeros_like(raw_logits)
            else:
                reference_source = self.source_reference_mean.unsqueeze(0).expand(len(raw_logits), -1)
                reference_logits = self.body.source_value_logits(reference_source)
                guided = raw_logits-reference_logits
            _require(bool(torch.isfinite(guided).all()), "nonfinite centered scalar guidance")
            return guided

        def source_value_guidance_logits(self, projected):
            """Applied residual scores; these are not raw auxiliary posteriors."""
            return self._guidance(self.body.source_value_logits(projected))

        def start(self, projected):
            state = self.body.start(projected)
            if scalar_mode == "raw":
                return state
            guided = self._guidance(state[-1])
            return (*state[:-1], guided)

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, dimension=self.dimension, scalar_mode=scalar_mode,
                base_architecture=deepcopy(description), inherited_weights_sha256=inherited_digest,
                feature_kind="projected_source", feature_dimension=self.dimension,
                max_rules=projected_values.MAX_RULES, source_fields=list(projected_values.SOURCE_FIELDS),
                vocabulary_size=description["vocabulary_size"], codec_sha256=description["codec_sha256"],
                normalization=deepcopy(description["normalization"]), count_prior=deepcopy(description["count_prior"]),
                training_feature_mean_receipt=deepcopy(reference), source_reference_mean=raw_mean.tolist(),
                source_reference_mean_frozen=True, source_auxiliary_logits="unchanged_raw_classifier",
                scalar_guidance_formula={"raw":"raw_head(features)", "off":"zero",
                    "mean_centered":"raw_head(features)-raw_head(training_feature_mean)"}[scalar_mode],
                reference_baseline_detached=False, source_auxiliary_objective_changed=False,
                count_path_changed=False, recurrent_path_changed=False, projection_path_changed=False,
                full_vocabulary_retained=True, syntax_forced=False, closure_forced=False,
                reference_documents_passed_to_generation=False, generation_reference_count_access=False,
                training_reference_statistics_only=True, calibrated_posterior_claim=False,
                source_context_cached_on_module=False, added_trainable_parameters=0,
                scope="exposed_development_only", production_runtime_compatible=False, **FALSE)

    return MeanCenteredSourceDecoder()


def bind_zero_condition_model(model):
    """Ablate recurrent/normalized-head source; centered guidance is exactly zero.

Raw auxiliary scalar biases, count biases and the fixed count prior remain.
For mean-centered guidance the evidence path is absent, so the generated-token
residual is zero even when the identity-normalized training mean is nonzero.
"""
    torch = core._torch()
    core._model(model, torch)
    description = model.describe()
    _require(description.get("schema") == SCHEMA and description.get("scalar_mode") in SCALAR_MODES,
        "authenticated mean-centered wrapper required")
    scalar_mode = description["scalar_mode"]

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = projected_values.bind_zero_condition_model(model.body)
            self.dimension = model.dimension

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            return self.body.count_logits(projected)

        def source_value_logits(self, projected):
            return self.body.source_value_logits(projected)

        def source_value_guidance_logits(self, projected):
            raw = self.body.source_value_logits(projected)
            return raw if scalar_mode == "raw" else torch.zeros_like(raw)

        def start(self, projected):
            state = self.body.start(projected)
            return state if scalar_mode == "raw" else (*state[:-1], torch.zeros_like(state[-1]))

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            return dict(schema="zero-mean-centered-source-control/v1", dimension=self.dimension,
                scalar_mode=scalar_mode, initial_hidden_zeroed=True, persistent_source_zeroed=True,
                normalized_count_and_scalar_source_features_zeroed=True,
                centered_scalar_guidance_zeroed=scalar_mode == "mean_centered",
                raw_auxiliary_biases_and_frozen_count_prior_retained=True,
                projection_preserved=True, prefix_and_parser_state_preserved=True,
                scope="development_ablation_only", **FALSE)

    return ZeroCondition()
