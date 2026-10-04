"""Private native-width formula bodies with a preserved token decoder.

This constructor resets source conditioning; it is not a continuation of the
historical linguistic teacher or a conversion of semantic embedding coordinates.
The frozen identity projection has zero diagnostic reconstruction error by
construction. That error is not evidence of learned reconstruction or fidelity.
"""
from copy import deepcopy
import math

from . import decoder_distillation_experiment as core
from . import decoder_distillation_experiment_v2 as adapter

SCHEMA = "dimension-native-raw-decoder-development/v1"
ARCHITECTURE = "native-source-neutral-inherited-token-gru/v1"
COPIED_NAMES = tuple(sorted(name for name in adapter._BODY_PARAMETERS
    if name.startswith(("target_embedding.", "decoder.", "output."))))
RESET_NAMES = tuple(sorted(adapter._BODY_PARAMETERS-set(COPIED_NAMES)))
PROJECTION_NAMES = tuple(name for name in RESET_NAMES if name.startswith("projection_"))
FALSE = dict(core.FALSE, historical_linguistic_teacher_changed=False,
    embeddings_produced=False, embeddings_verified=False, encoder_executed=False,
    encoder_context_changed=False, output_budget_changed=False,
    production_runtime_compatible=False, learned_projection_reconstruction=False,
    source_semantics_verified=False, lake_executed=False)
_require = core._require


def bind_dimension_native_body(raw_donor, *, dimension, source_seed=1729):
    """Return an independent native-D raw body and its initialization receipt.

    The donor must be an unwrapped 384D numerical GRU. Its source-independent
    decoder tensors and trainability are copied exactly. The new condition is
    zero-initialized and trainable; projection-down is locally seeded while the
    frozen zero projection-up makes the residual projection exactly identity.
    A subsequent persistent-source adapter supplies its own zero-initialized
    native-D source-to-token layer. This function does not create that layer.
    """
    torch = core._torch()
    _require(type(dimension) is int and dimension in (8, 384, 768),
        "explicit supported native dimension required")
    _require(type(source_seed) is int and 0 <= source_seed <= 2**31-1,
        "bounded independent source seed required")
    donor_spec = adapter._body_spec(raw_donor, 384, torch)
    donor_digest = core.tensor_digest(raw_donor)
    width, hidden = donor_spec["projection_width"], donor_spec["hidden_width"]
    size = donor_spec["vocabulary_size"]

    class NativeDimensionBody(torch.nn.Module):
        def __init__(self):
            super().__init__()
            with torch.random.fork_rng(devices=[]):
                self.projection_down = torch.nn.Linear(dimension, width, dtype=torch.float32)
                self.projection_up = torch.nn.Linear(width, dimension, dtype=torch.float32)
                self.condition = torch.nn.Linear(dimension, hidden, dtype=torch.float32)
            for name in ("target_embedding", "decoder", "output"):
                setattr(self, name, deepcopy(getattr(raw_donor, name)))
            generator = torch.Generator(device="cpu").manual_seed(source_seed)
            with torch.no_grad():
                self.projection_down.weight.uniform_(-1./math.sqrt(dimension),
                    1./math.sqrt(dimension), generator=generator)
                self.projection_down.bias.zero_()
                self.projection_up.weight.zero_(); self.projection_up.bias.zero_()
                self.condition.weight.zero_(); self.condition.bias.zero_()
            for name, parameter in self.named_parameters():
                if name in PROJECTION_NAMES:
                    parameter.requires_grad_(False)
                parameter.grad = None

        def _inputs(self, values):
            _require(isinstance(values, torch.Tensor) and values.device.type == "cpu"
                and values.dtype == torch.float32 and values.ndim == 2
                and 1 <= len(values) <= 128 and values.shape[1] == dimension
                and bool(torch.isfinite(values).all()), "finite native-width CPU source input required")

        def project(self, values):
            self._inputs(values)
            result = values+self.projection_up(torch.tanh(self.projection_down(values)))
            _require(bool(torch.isfinite(result).all()), "nonfinite native projection")
            return result

        def start(self, projected):
            self._inputs(projected)
            return torch.tanh(self.condition(projected)).unsqueeze(0)

        def next_logits(self, tokens, hidden):
            _require(isinstance(tokens, torch.Tensor) and tokens.device.type == "cpu"
                and tokens.dtype == torch.long and tokens.ndim == 2 and 1 <= len(tokens) <= 128
                and 1 <= tokens.shape[1] <= 1023 and bool((tokens >= 0).all())
                and bool((tokens < size).all()), "bounded original-vocabulary prefix required")
            _require(isinstance(hidden, torch.Tensor) and hidden.device.type == "cpu"
                and hidden.dtype == torch.float32 and tuple(hidden.shape) == (1, len(tokens), hidden_size)
                and bool(torch.isfinite(hidden).all()), "finite inherited recurrent state required")
            outputs, updated = self.decoder(self.target_embedding(tokens), hidden)
            logits = self.output(outputs)
            _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(updated).all()),
                "nonfinite native decoder output")
            return logits, updated

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def validate_restored_state(self, state_dict):
            current = self.state_dict()
            _require(hasattr(state_dict, "items") and set(state_dict) == set(current),
                "native restored tensor inventory differs")
            # Preflight every tensor before nn.Module can mutate any parameter.
            for name, value in state_dict.items():
                template = current[name]
                _require(isinstance(value, torch.Tensor) and value.device.type == "cpu"
                    and value.dtype == torch.float32 and value.shape == template.shape
                    and bool(torch.isfinite(value).all()), "native restored tensor differs: "+name)
            for name, value in frozen_projection.items():
                _require(torch.equal(state_dict[name], value), "frozen native projection differs: "+name)

        def load_state_dict(self, state_dict, strict=True, assign=False):
            _require(strict is True and assign is False, "strict nonassigning native restore required")
            self.validate_restored_state(state_dict)
            return super().load_state_dict(state_dict, strict=True, assign=False)

        def native_initialization_receipt(self):
            return deepcopy(receipt)

        def check_frozen_projection(self):
            current = self.state_dict()
            _require(all(torch.equal(current[name], value) for name,value in frozen_projection.items()),
                "frozen native projection differs")

    hidden_size = hidden
    body = NativeDimensionBody()
    frozen_projection = {name:body.state_dict()[name].detach().clone() for name in PROJECTION_NAMES}
    specification = adapter._body_spec(body, dimension, torch)
    donor_values, values = raw_donor.state_dict(), body.state_dict()
    _require(all(torch.equal(values[name], donor_values[name]) for name in COPIED_NAMES),
        "copied source-independent decoder differs")
    _require(core.tensor_digest(raw_donor) == donor_digest, "native constructor changed donor")
    receipt = dict(schema=SCHEMA, architecture=ARCHITECTURE, **specification,
        donor_dimension=384, input_dimension=dimension, projected_output_dimension=dimension,
        dimension_role="actual_source_input_and_projected_output_width",
        donor_tensor_sha256=donor_digest, initial_tensor_sha256=core.tensor_digest(body),
        copied_parameter_names=list(COPIED_NAMES), reset_parameter_names=list(RESET_NAMES),
        frozen_parameter_names=list(PROJECTION_NAMES),
        copied_parameter_trainability={name:dict(raw_donor.named_parameters())[name].requires_grad for name in COPIED_NAMES},
        source_seed=source_seed, initialization_rng="independent_local_cpu_generator",
        source_conditioning_reset=True, source_condition_initialization="zero_weights_and_bias",
        projection_down_initialization="uniform(-1/sqrt(dimension),1/sqrt(dimension));zero_bias",
        projection_up_initialization="zero_weights_and_bias", projection_policy="frozen_identity_residual",
        reconstruction_mse_scope="identity_by_construction_not_learned_reconstruction",
        native_sidecar=True, historical_8d_linguistic_teacher=False,
        runtime_lineage="new_dimension_native_formula_sidecar",
        persistent_source_adapter_included=False, original_token_decoder_preserved=True,
        initial_source_condition_is_zero=True, ambient_rng_preserved=True,
        scope="exposed_development_comparison_only", **FALSE)
    receipt["receipt_sha256"] = core.digest(receipt)
    return body, deepcopy(receipt)


def checked_specification(body, receipt):
    """Check a live raw body's frozen recipe; learned decoder tensors may change."""
    torch = core._torch()
    _require(type(receipt) is dict and receipt.get("schema") == SCHEMA
        and receipt.get("receipt_sha256") == core.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"}),
        "native initialization receipt differs")
    _require(callable(getattr(body, "native_initialization_receipt", None))
        and body.native_initialization_receipt() == receipt, "native body provenance differs")
    specification = adapter._body_spec(body, receipt.get("dimension"), torch)
    _require(all(receipt.get(k) == v for k,v in specification.items())
        and all(receipt.get(k) is False for k in FALSE), "native specification or authority differs")
    parameters = dict(body.named_parameters())
    _require(all(not parameters[name].requires_grad for name in PROJECTION_NAMES)
        and all(parameters[name].requires_grad == value for name,value in receipt["copied_parameter_trainability"].items())
        and parameters["condition.weight"].requires_grad and parameters["condition.bias"].requires_grad,
        "native trainability policy differs")
    body.check_frozen_projection()
    return deepcopy(receipt)


def validate_restored_state(body, receipt, raw_state):
    """Preflight an unprefixed raw slice before restoring a surrounding wrapper.

    PyTorch parent restoration does not call a child's public load_state_dict.
    Callers must run this check before loading a persisted wrapper, then retain
    their wrapper's own strict buffer, geometry and provenance checks as well.
    No live weights, gradients or modes are changed by this function.
    """
    checked_specification(body, receipt)
    body.validate_restored_state(raw_state)
