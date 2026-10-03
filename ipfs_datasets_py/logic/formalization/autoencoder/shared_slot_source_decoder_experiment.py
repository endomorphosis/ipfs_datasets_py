"""Private shared-slot source classifier with inherited causal decoder guidance.

This experiment replaces eight independent scalar classifiers with a nonlinear
source/position interaction and field readouts shared across positions. It does
not alter the recurrent decoder, count policy, output support, or qualification.
"""
from copy import deepcopy
import math

from . import decoder_distillation_experiment as core
from . import projected_source_decoder_experiment as projected_values

SCHEMA = "shared-slot-source-decoder-development/v1"
HIDDEN_WIDTH = 64
MAX_RULES = projected_values.MAX_RULES
SOURCE_FIELDS = projected_values.SOURCE_FIELDS
FALSE = dict(projected_values.FALSE)
_require = core._require
HEAD_NAMES = ("source_projection.weight", "source_projection.bias", "slot_embeddings",
              "field_readout.weight", "field_readout.bias")
SLOT_INTERACTIONS = ("additive", "additive_multiplicative")
ADDITIVE_FORMULA = "tanh(shared_source_projection(normalized_source)+learned_slot_embedding)"
MULTIPLICATIVE_FORMULA = "tanh(shared_source_projection(normalized_source)*(1+learned_slot_embedding)+learned_slot_embedding)"
INTERACTION_FIELDS = ("slot_interaction", "slot_interaction_version", "source_slot_multiplication",
                      "slot_modulation_formula", "slot_modulation_and_offset_parameters_tied",
                      "additional_trainable_parameters")


def _projected_specification(model, torch):
    core._model(model, torch)
    description = model.describe()
    _require(description.get("schema") == projected_values.SCHEMA
        and description.get("guidance") is True
        and description.get("max_rules") == MAX_RULES
        and description.get("source_fields") == list(SOURCE_FIELDS)
        and description.get("feature_kind") == "projected_source"
        and description.get("feature_dimension") == model.dimension,
        "authenticated projected-source model with raw scalar guidance required")
    projected_values._checked_receipts(description["normalization"], description["count_prior"], model.dimension)
    expected = dict(source_mean=description["normalization"]["mean"],
        source_scale=description["normalization"]["scale"], count_prior_logits=description["count_prior"]["log_prior"])
    for name, value in expected.items():
        actual = getattr(model, name, None)
        target = torch.tensor(value, dtype=torch.float32)
        _require(isinstance(actual, torch.Tensor) and actual.dtype == torch.float32
            and actual.device.type == "cpu" and torch.equal(actual, target),
            "projected buffer differs from authenticated receipt: " + name)
    _require(type(description.get("guide_boundary")) is bool
        and all(description.get(key) is False for key in FALSE)
        and description.get("syntax_forced") is False and description.get("closure_forced") is False,
        "projected policy or authority differs")
    count_head = getattr(model, "count_head", None)
    _require(type(count_head) is torch.nn.Linear and count_head.in_features == model.dimension
        and count_head.out_features == projected_values.MAX_COUNTS,
        "inherited projected count head geometry differs")
    return description


def bind_shared_slot_source_model(model, *, head_seed, hidden_width=HIDDEN_WIDTH,
                                  slot_interaction="additive"):
    """Copy a fresh projected decoder and install a locally seeded shared head.

``h_i = tanh(W*x + b + e_i)`` and ``logits[i,f,:] = A_f*h_i + c_f``.
The readout A/c starts at zero; W/e use only a private CPU RNG. The inherited
scalar head must be zero so initial full-prefix and greedy parity is meaningful.
The original module and all ambient random-generator states remain unchanged.
The explicit additive_multiplicative variant instead uses
``tanh((W*x+b)*(1+e_i)+e_i)`` with exactly the same parameters and initialization.
Its mode buffer prevents loading a checkpoint under a different source formula.
"""
    torch = core._torch()
    description = _projected_specification(model, torch)
    _require(type(head_seed) is int and 0 <= head_seed <= 2**31-1,
        "explicit bounded independent initialization seed required")
    _require(type(hidden_width) is int and hidden_width == HIDDEN_WIDTH,
        "explicit shared hidden width64 required")
    _require(type(slot_interaction) is str and slot_interaction in SLOT_INTERACTIONS,
        "explicit supported source-slot interaction required")
    dimension, size = model.dimension, description["vocabulary_size"]
    original_head = getattr(model, "source_value_head", None)
    _require(type(original_head) is torch.nn.Linear and original_head.in_features == dimension
        and original_head.out_features == MAX_RULES*len(SOURCE_FIELDS)*size
        and torch.count_nonzero(original_head.weight).item() == 0
        and torch.count_nonzero(original_head.bias).item() == 0,
        "zero independent scalar donor head required; fitted heads must not be discarded")
    parameter_count = (dimension+1)*hidden_width + MAX_RULES*hidden_width + (hidden_width+1)*len(SOURCE_FIELDS)*size
    _require(parameter_count*4 <= 67108864, "shared source head allocation exceeds64MiB")
    inherited_digest = core.tensor_digest(model)
    frozen = {"body."+name: value.detach().clone() for name, value in model.named_buffers()}
    frozen["head_initialization_seed"] = torch.tensor(head_seed, dtype=torch.long)
    if slot_interaction == "additive_multiplicative":
        frozen["slot_interaction_version"] = torch.tensor(1, dtype=torch.long)

    class SharedHead(torch.nn.Module):
        def __init__(self):
            super().__init__()
            # Linear constructors consume randomness internally. Forking restores
            # that state; every resulting parameter is then explicitly replaced.
            with torch.random.fork_rng(devices=[]):
                self.source_projection = torch.nn.Linear(dimension, hidden_width, dtype=torch.float32)
                self.field_readout = torch.nn.Linear(hidden_width, len(SOURCE_FIELDS)*size, dtype=torch.float32)
            self.slot_embeddings = torch.nn.Parameter(torch.empty(MAX_RULES, hidden_width, dtype=torch.float32))
            generator = torch.Generator(device="cpu").manual_seed(head_seed)
            with torch.no_grad():
                self.source_projection.weight.uniform_(-1./math.sqrt(dimension), 1./math.sqrt(dimension), generator=generator)
                self.source_projection.bias.zero_()
                self.slot_embeddings.uniform_(-1./math.sqrt(hidden_width), 1./math.sqrt(hidden_width), generator=generator)
                self.field_readout.weight.zero_(); self.field_readout.bias.zero_()

        @property
        def slot_interaction(self):
            return slot_interaction

        def forward(self, features):
            source = self.source_projection(features).unsqueeze(1)
            slots = self.slot_embeddings.unsqueeze(0)
            if slot_interaction == "additive_multiplicative":
                hidden = torch.tanh(source*(1+slots)+slots)
            else:
                hidden = torch.tanh(source+slots)
            return self.field_readout(hidden).reshape(len(features), MAX_RULES*len(SOURCE_FIELDS)*size)

    class SharedSlotSourceDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = dimension
            self.register_buffer("head_initialization_seed", frozen["head_initialization_seed"].clone())
            if slot_interaction == "additive_multiplicative":
                self.register_buffer("slot_interaction_version", frozen["slot_interaction_version"].clone())
            _require(core.tensor_digest(self.body) == inherited_digest, "private donor copy differs")
            self.body.source_value_head = SharedHead()
            for name, parameter in self.body.named_parameters():
                if name.startswith(("body.body.projection_down.", "body.body.projection_up.")):
                    parameter.requires_grad_(False)

        def load_state_dict(self, state_dict, strict=True, assign=False):
            # Public child load guards do not run during parent recursive load.
            if slot_interaction == "additive":
                _require("slot_interaction_version" not in state_dict,
                    "restored source-slot interaction differs from additive architecture")
            for name, expected in frozen.items():
                actual = state_dict.get(name)
                _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                    and actual.device.type == "cpu" and tuple(actual.shape) == tuple(expected.shape)
                    and torch.equal(actual, expected), "restored frozen shared-source buffer differs: " + name)
            return super().load_state_dict(state_dict, strict=strict, assign=assign)

        def project(self, values):
            return self.body.project(values)

        def count_logits(self, projected):
            return self.body.count_logits(projected)

        def source_value_logits(self, projected):
            return self.body.source_value_logits(projected)

        def source_value_guidance_logits(self, projected):
            return self.body.source_value_logits(projected)

        def start(self, projected):
            return self.body.start(projected)

        def next_logits(self, tokens, state):
            return self.body.next_logits(tokens, state)

        def forward(self, values, prefix):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits

        def describe(self):
            result = dict(schema=SCHEMA, dimension=dimension, scalar_mode="raw",
                base_architecture=deepcopy(description), base_architecture_is_pre_replacement_donor=True,
                inherited_weights_sha256=inherited_digest, independent_source_head_replaced=True,
                feature_kind="projected_source", feature_dimension=dimension,
                max_rules=MAX_RULES, source_fields=list(SOURCE_FIELDS), vocabulary_size=size,
                codec_sha256=description["codec_sha256"], normalization=deepcopy(description["normalization"]),
                count_prior=deepcopy(description["count_prior"]), guide_boundary=description["guide_boundary"],
                guidance=True, hidden_width=hidden_width, activation="tanh",
                source_formula=ADDITIVE_FORMULA,
                readout_formula="shared_per_field_full_vocabulary_affine(hidden_at_slot)",
                field_readouts_shared_across_slots=True, nonlinear_source_position_interaction=True,
                head_initialization_seed=head_seed, initialization_rng="independent_local_cpu_generator",
                ambient_rng_preserved=True, source_weight_initialization="uniform(-1/sqrt(dimension),1/sqrt(dimension))",
                source_bias_initialization="zero", slot_initialization="uniform(-1/sqrt(width),1/sqrt(width))",
                field_readout_initialization="zero_weights_and_biases", initial_decoder_logits_unchanged=True,
                source_value_parameter_names=["body.source_value_head."+name for name in HEAD_NAMES],
                source_value_parameter_count=parameter_count,
                replaced_source_value_parameter_count=(dimension+1)*MAX_RULES*len(SOURCE_FIELDS)*size,
                count_path_changed=False, recurrent_path_changed=False, projection_path_changed=False,
                projection_frozen=True, normalization_statistics_frozen=True, count_prior_frozen=True,
                full_vocabulary_retained=True, output_support="complete_inherited_vocabulary",
                syntax_forced=False, closure_forced=False, source_context_cached_on_module=False,
                generation_reference_count_access=False, reference_documents_passed_to_generation=False,
                scalar_guidance_kind="soft_full_vocabulary_residual_at_inherited_causal_scalar_colon",
                head_slot_limit_changes_output_limit=False, encoder_context_changed=False, output_budget_changed=False,
                scope="exposed_development_only", production_runtime_compatible=False, **FALSE)
            if slot_interaction == "additive_multiplicative":
                result.update(slot_interaction=slot_interaction, slot_interaction_version=1,
                    source_formula=MULTIPLICATIVE_FORMULA, source_slot_multiplication=True,
                    slot_modulation_formula="1+learned_slot_embedding",
                    slot_modulation_and_offset_parameters_tied=True, additional_trainable_parameters=0)
            return result

    return SharedSlotSourceDecoder()


def checked_specification(model, codec):
    """Validate actual shared geometry and frozen training receipts for the trainer."""
    torch = core._torch(); core._model(model, torch)
    description = model.describe()
    _require(description.get("schema") == SCHEMA and description.get("scalar_mode") == "raw"
        and description.get("hidden_width") == HIDDEN_WIDTH and description.get("activation") == "tanh",
        "explicit raw shared-slot decoder required")
    base = _projected_specification(model.body, torch)
    _require(description.get("base_architecture") == base
        and description.get("base_architecture_is_pre_replacement_donor") is True,
        "inherited projected architecture binding differs")
    for name in ("dimension", "feature_kind", "feature_dimension", "max_rules", "source_fields",
                 "vocabulary_size", "codec_sha256", "normalization", "count_prior", "guide_boundary"):
        _require(description.get(name) == base.get(name), "shared architecture binding differs: " + name)
    _require(description["codec_sha256"] == core.digest(codec)
        and description["vocabulary_size"] == len(codec["target_vocabulary"]), "shared codec differs")
    for name in ("guidance", "independent_source_head_replaced", "field_readouts_shared_across_slots",
                 "nonlinear_source_position_interaction", "projection_frozen", "normalization_statistics_frozen",
                 "count_prior_frozen", "full_vocabulary_retained", "ambient_rng_preserved"):
        _require(description.get(name) is True, "shared source policy differs: " + name)
    for name in (*FALSE, "count_path_changed", "recurrent_path_changed", "projection_path_changed", "syntax_forced",
                 "closure_forced", "source_context_cached_on_module", "generation_reference_count_access",
                 "reference_documents_passed_to_generation", "head_slot_limit_changes_output_limit"):
        _require(description.get(name) is False, "shared source authority or generation policy differs: " + name)
    dimension, size = model.dimension, description["vocabulary_size"]
    head = model.body.source_value_head
    interaction = getattr(head, "slot_interaction", "additive")
    _require(type(interaction) is str and interaction in SLOT_INTERACTIONS,
        "unknown actual source-slot interaction")
    if interaction == "additive":
        _require(not any(key in description for key in INTERACTION_FIELDS)
            and description.get("source_formula") == ADDITIVE_FORMULA
            and "slot_interaction_version" not in dict(model.named_buffers()),
            "additive source-slot architecture receipt differs")
    else:
        version = getattr(model, "slot_interaction_version", None)
        _require(description.get("slot_interaction") == interaction
            and type(description.get("slot_interaction_version")) is int
            and description["slot_interaction_version"] == 1
            and description.get("source_formula") == MULTIPLICATIVE_FORMULA
            and description.get("source_slot_multiplication") is True
            and description.get("slot_modulation_formula") == "1+learned_slot_embedding"
            and description.get("slot_modulation_and_offset_parameters_tied") is True
            and type(description.get("additional_trainable_parameters")) is int
            and description["additional_trainable_parameters"] == 0
            and isinstance(version, torch.Tensor) and version.dtype == torch.long
            and version.device.type == "cpu" and version.shape == torch.Size([]) and int(version) == 1,
            "multiplicative source-slot architecture receipt or frozen mode differs")
    shapes = {"source_projection.weight": (HIDDEN_WIDTH, dimension), "source_projection.bias": (HIDDEN_WIDTH,),
        "slot_embeddings": (MAX_RULES, HIDDEN_WIDTH), "field_readout.weight": (len(SOURCE_FIELDS)*size, HIDDEN_WIDTH),
        "field_readout.bias": (len(SOURCE_FIELDS)*size,)}
    actual = dict(head.named_parameters())
    _require(set(actual) == set(HEAD_NAMES) and not dict(head.named_buffers())
        and all(tuple(actual[name].shape) == shape and actual[name].requires_grad
            for name, shape in shapes.items()), "shared head trainable parameter geometry differs")
    _require(type(head.source_projection) is torch.nn.Linear and type(head.field_readout) is torch.nn.Linear
        and head.source_projection.in_features == dimension and head.source_projection.out_features == HIDDEN_WIDTH
        and head.field_readout.in_features == HIDDEN_WIDTH and head.field_readout.out_features == len(SOURCE_FIELDS)*size,
        "shared affine modules differ")
    _require(description["source_value_parameter_names"] == ["body.source_value_head."+name for name in HEAD_NAMES]
        and description["source_value_parameter_count"] == sum(parameter.numel() for parameter in actual.values()),
        "shared parameter inventory differs")
    seed = model.head_initialization_seed
    _require(seed.dtype == torch.long and seed.device.type == "cpu" and seed.shape == torch.Size([])
        and type(description["head_initialization_seed"]) is int
        and 0 <= description["head_initialization_seed"] <= 2**31-1
        and int(seed) == description["head_initialization_seed"],
        "shared initialization seed binding differs")
    projection = [parameter for name, parameter in model.named_parameters()
        if name.startswith(("body.body.body.projection_down.", "body.body.body.projection_up."))]
    _require(bool(projection) and all(not parameter.requires_grad for parameter in projection),
        "shared model inherited projection must remain frozen")
    return deepcopy(description)


def bind_zero_condition_model(model):
    """Remove source vectors while retaining learned slot/bias and count priors."""
    torch = core._torch(); core._model(model, torch)
    _require(model.describe().get("schema") == SCHEMA, "shared-slot decoder required")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = projected_values.bind_zero_condition_model(model.body)
            self.dimension = model.dimension

        def project(self, values): return self.body.project(values)
        def count_logits(self, projected): return self.body.count_logits(projected)
        def source_value_logits(self, projected): return self.body.source_value_logits(projected)
        def source_value_guidance_logits(self, projected): return self.body.source_value_logits(projected)
        def start(self, projected): return self.body.start(projected)
        def next_logits(self, tokens, state): return self.body.next_logits(tokens, state)
        def forward(self, values, prefix):
            projected = self.project(values); logits, _ = self.next_logits(prefix, self.start(projected))
            return projected, logits
        def describe(self):
            result = dict(schema="zero-shared-slot-source-control/v1", dimension=self.dimension, scalar_mode="raw",
                initial_hidden_zeroed=True, persistent_source_zeroed=True,
                normalized_count_and_scalar_source_features_zeroed=True,
                learned_slot_embeddings_and_all_head_biases_retained=True, frozen_count_prior_retained=True,
                projection_preserved=True, prefix_and_parser_state_preserved=True,
                scope="development_ablation_only", **FALSE)
            if model.describe().get("slot_interaction") == "additive_multiplicative":
                result.update(slot_interaction="additive_multiplicative", slot_interaction_version=1,
                    slot_modulation_and_offset_parameters_tied=True)
            return result

    return ZeroCondition()
