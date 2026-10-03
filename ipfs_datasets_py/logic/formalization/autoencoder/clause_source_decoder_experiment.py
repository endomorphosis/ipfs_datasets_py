"""Private ordered clause-context decoder with a position-free shared scalar head.

Clause vectors are explicit source-only arguments, never mutable model lookup
state. Padding disables only scalar residuals; it does not force syntax or EOS.
"""
from copy import deepcopy
import math

from . import decoder_distillation_experiment as core
from . import projected_source_decoder_experiment as projected_values
from . import shared_slot_source_decoder_experiment as shared_values

SCHEMA = "clause-source-decoder-development/v1"
HIDDEN_WIDTH = 64
MAX_RULES = projected_values.MAX_RULES
SOURCE_FIELDS = projected_values.SOURCE_FIELDS
FALSE = dict(projected_values.FALSE)
HEAD_NAMES = ("source_projection.weight", "source_projection.bias", "field_readout.weight", "field_readout.bias")
FORMULA = "shared_per_field_full_vocabulary_affine(tanh(shared_affine(normalized_projected_clause)))"
_require = core._require


def _normalization(receipt, dimension):
    _require(type(receipt) is dict and receipt.get("schema") == projected_values.NORMALIZATION_SCHEMA
        and receipt.get("receipt_sha256") == core.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"}),
        "clause training normalization receipt digest differs")
    _require(receipt.get("kind") == "center_rms" and receipt.get("dimension") == dimension
        and all(receipt.get(key) is False for key in FALSE)
        and receipt.get("validation_rows_used_for_fitting") == 0,
        "training-only centered clause normalization required")
    inventory = receipt.get("training_inventory")
    projected_values._identities(inventory, receipt.get("expected_training_ids"),
        receipt.get("forbidden_validation_ids"), receipt.get("training_rows_sha256"), {"id", "source_sha256"})
    _require(receipt.get("fitted_rows") == len(inventory)
        and [row["id"] for row in inventory] == receipt["expected_training_ids"]
        and all(row["id"] == "clause:"+row["source_sha256"] for row in inventory)
        and all(value.startswith("clause:") and core._SHA.fullmatch(value[7:])
                for value in receipt["forbidden_validation_ids"]), "source-derived unique clause identities required")
    core._vector(receipt.get("mean"), dimension)
    core._vector(receipt.get("fitted_training_mean"), dimension)
    energy = receipt.get("fitted_training_centered_row_squared_norm")
    _require(type(energy) in (int, float) and math.isfinite(energy) and energy >= 0.
        and type(receipt.get("constant_training_features")) is bool
        and receipt["constant_training_features"] == (energy == 0.)
        and receipt.get("fitted_training_scale") == (1. if energy == 0. else math.sqrt(energy))
        and receipt.get("mean") == receipt["fitted_training_mean"]
        and receipt.get("scale") == receipt["fitted_training_scale"], "clause fitted normalization statistics differ")
    _require(receipt.get("normalization") == "center_then_global_RMS_of_row_L2_norm"
        and receipt.get("statistics_dtype") == "float64" and receipt.get("model_buffer_dtype") == "float32"
        and receipt.get("scope") == "training_only_frozen_transform"
        and type(receipt.get("training_feature_rows_sha256")) is str
        and core._SHA.fullmatch(receipt["training_feature_rows_sha256"])
        and type(receipt.get("training_contexts_sha256")) is str
        and core._SHA.fullmatch(receipt["training_contexts_sha256"]), "clause normalization provenance differs")
    torch = core._torch()
    scale = torch.tensor(receipt["scale"], dtype=torch.float32)
    _require(bool(torch.isfinite(scale)) and float(scale) > 0
        and bool(torch.isfinite(torch.tensor(receipt["mean"], dtype=torch.float32)).all()),
        "unrepresentable clause normalization")
    return deepcopy(receipt)


def _context(torch, projected, source_context, dimension):
    _require(type(source_context) is dict and set(source_context) == {"vectors", "mask"},
        "explicit closed clause source context required")
    vectors, mask = source_context["vectors"], source_context["mask"]
    _require(isinstance(vectors, torch.Tensor) and vectors.dtype == torch.float32 and vectors.device.type == "cpu"
        and tuple(vectors.shape) == (len(projected), MAX_RULES, dimension)
        and bool(torch.isfinite(vectors).all()) and not vectors.requires_grad,
        "finite detached CPU clause source vectors required")
    _require(isinstance(mask, torch.Tensor) and mask.dtype == torch.bool and mask.device.type == "cpu"
        and tuple(mask.shape) == (len(projected), MAX_RULES)
        and bool(mask[:, 0].all()) and not bool((mask[:, 1:] & ~mask[:, :-1]).any()),
        "source-derived contiguous nonempty clause mask required")
    _require(not bool(vectors[~mask].any()), "inactive clause vectors must be zero padding")
    return vectors, mask


def bind_clause_source_model(model, *, head_seed, clause_normalization_receipt):
    """Copy a fresh projected decoder, replacing its scalar head with clause input.

Initialization of W/b/readout matches the shared-slot head under the same local
seed, while deliberately omitting slot embeddings. Frozen clause statistics use
unique training clause sources; paragraph statistics/count policy stay intact.
"""
    torch = core._torch()
    description = shared_values._projected_specification(model, torch)
    _require(type(head_seed) is int and 0 <= head_seed <= 2**31-1, "bounded independent head seed required")
    dimension, size = model.dimension, description["vocabulary_size"]
    normalization = _normalization(clause_normalization_receipt, dimension)
    _require(normalization["training_rows_sha256"] == description["normalization"]["training_rows_sha256"],
        "clause and paragraph normalization training cohort differs")
    head = getattr(model, "source_value_head", None)
    _require(type(head) is torch.nn.Linear and head.in_features == dimension
        and head.out_features == MAX_RULES*len(SOURCE_FIELDS)*size
        and torch.count_nonzero(head.weight).item() == 0 and torch.count_nonzero(head.bias).item() == 0,
        "fresh zero scalar donor head required")
    parameter_count = (dimension+1)*HIDDEN_WIDTH + (HIDDEN_WIDTH+1)*len(SOURCE_FIELDS)*size
    _require(parameter_count*4 <= 67108864, "clause head allocation exceeds64MiB")
    inherited_digest = core.tensor_digest(model)
    frozen = {"body."+name: value.detach().clone() for name, value in model.named_buffers()}
    frozen.update(head_initialization_seed=torch.tensor(head_seed, dtype=torch.long),
        clause_source_mean=torch.tensor(normalization["mean"], dtype=torch.float32),
        clause_source_scale=torch.tensor(normalization["scale"], dtype=torch.float32))

    class InactiveParagraphHead(torch.nn.Module):
        def forward(self, features):
            return features.new_zeros((len(features), MAX_RULES*len(SOURCE_FIELDS)*size))

    class ClauseHead(torch.nn.Module):
        def __init__(self):
            super().__init__()
            with torch.random.fork_rng(devices=[]):
                self.source_projection = torch.nn.Linear(dimension, HIDDEN_WIDTH, dtype=torch.float32)
                self.field_readout = torch.nn.Linear(HIDDEN_WIDTH, len(SOURCE_FIELDS)*size, dtype=torch.float32)
            generator = torch.Generator(device="cpu").manual_seed(head_seed)
            with torch.no_grad():
                self.source_projection.weight.uniform_(-1./math.sqrt(dimension), 1./math.sqrt(dimension), generator=generator)
                self.source_projection.bias.zero_()
                self.field_readout.weight.zero_(); self.field_readout.bias.zero_()

        def forward(self, features):
            return self.field_readout(torch.tanh(self.source_projection(features))).reshape(
                len(features), MAX_RULES, len(SOURCE_FIELDS), size)

    class ClauseSourceDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = dimension
            _require(core.tensor_digest(self.body) == inherited_digest, "private projected donor copy differs")
            self.body.source_value_head = InactiveParagraphHead()
            self.clause_head = ClauseHead()
            for name in ("head_initialization_seed", "clause_source_mean", "clause_source_scale"):
                self.register_buffer(name, frozen[name].clone())
            for name, parameter in self.body.named_parameters():
                if name.startswith(("body.body.projection_down.", "body.body.projection_up.")):
                    parameter.requires_grad_(False)

        def load_state_dict(self, state_dict, strict=True, assign=False):
            current = self.state_dict()
            _require(hasattr(state_dict, "items") and (not strict or set(state_dict) == set(current)),
                "restored clause state inventory differs")
            for name, actual in state_dict.items():
                if name in current:
                    expected = current[name]
                    _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                        and actual.device.type == "cpu" and actual.shape == expected.shape
                        and (not actual.is_floating_point() or bool(torch.isfinite(actual).all())),
                        "restored clause tensor geometry or finiteness differs: "+name)
            for name, expected in frozen.items():
                actual = state_dict.get(name)
                _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                    and actual.device.type == "cpu" and actual.shape == expected.shape and torch.equal(actual, expected),
                    "restored frozen clause-source buffer differs: "+name)
            _require(not any(name.startswith("body.source_value_head.") for name in state_dict),
                "stale paragraph scalar parameters must not be restored")
            return super().load_state_dict(state_dict, strict=strict, assign=assign)

        def project(self, values): return self.body.project(values)
        def count_logits(self, projected): return self.body.count_logits(projected)

        def clause_features(self, projected, *, source_context):
            self.body.body._inputs(projected)
            vectors, mask = _context(torch, projected, source_context, dimension)
            clause_projected = self.body.project(vectors.reshape(-1, dimension)).reshape(len(projected), MAX_RULES, dimension)
            return (clause_projected-self.clause_source_mean)/self.clause_source_scale, mask

        def source_value_logits(self, projected, *, source_context):
            features, mask = self.clause_features(projected, source_context=source_context)
            return self.clause_head(features)*mask[:, :, None, None]

        def source_value_guidance_logits(self, projected, *, source_context):
            return self.source_value_logits(projected, source_context=source_context)

        def start(self, projected, *, source_context):
            values = self.source_value_logits(projected, source_context=source_context)
            inherited = self.body.start(projected)
            return (*inherited[:-1], values)

        def next_logits(self, tokens, state): return self.body.next_logits(tokens, state)

        def forward(self, values, prefix, *, source_context):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected, source_context=source_context))
            return projected, logits

        def describe(self):
            return dict(schema=SCHEMA, dimension=dimension, scalar_mode="raw",
                base_architecture=deepcopy(description), base_architecture_is_pre_replacement_donor=True,
                inherited_weights_sha256=inherited_digest, independent_source_head_replaced=True,
                feature_kind="projected_clause_source", feature_dimension=dimension, max_rules=MAX_RULES,
                source_fields=list(SOURCE_FIELDS), vocabulary_size=size, codec_sha256=description["codec_sha256"],
                normalization=deepcopy(description["normalization"]), count_prior=deepcopy(description["count_prior"]),
                clause_normalization=deepcopy(normalization), clause_normalization_weighting="unique_training_source_first_occurrence",
                guide_boundary=description["guide_boundary"], guidance=True, hidden_width=HIDDEN_WIDTH,
                activation="tanh", source_formula=FORMULA, field_readouts_shared_across_slots=True,
                slot_parameters=False, head_initialization_seed=head_seed,
                initialization_rng="independent_local_cpu_generator", ambient_rng_preserved=True,
                source_weight_initialization="uniform(-1/sqrt(dimension),1/sqrt(dimension))",
                source_bias_initialization="zero", field_readout_initialization="zero_weights_and_biases",
                source_value_parameter_names=["clause_head."+name for name in HEAD_NAMES],
                source_value_parameter_count=parameter_count,
                initial_decoder_logits_unchanged=True, count_path_changed=False, recurrent_path_changed=False,
                paragraph_projection_path_changed=False, clause_projection="same_frozen_paragraph_projection",
                projection_frozen=True, normalization_statistics_frozen=True, count_prior_frozen=True,
                source_context_required=True, source_context_cached_on_module=False,
                source_context_input="explicit_transformed_vectors_and_source_padding_mask",
                padding_policy="zero_only_scalar_residual", source_clause_count_used_for_stopping=False,
                full_vocabulary_retained=True, output_support="complete_inherited_vocabulary",
                syntax_forced=False, closure_forced=False, generation_reference_count_access=False,
                reference_documents_passed_to_generation=False, encoder_context_changed=False, output_budget_changed=False,
                scalar_guidance_kind="soft_full_vocabulary_residual_at_inherited_causal_scalar_colon",
                scope="exposed_authored_paragraph_development_only", production_runtime_compatible=False, **FALSE)

    return ClauseSourceDecoder()


def checked_specification(model, codec):
    torch = core._torch(); core._model(model, torch)
    description = model.describe()
    _require(description.get("schema") == SCHEMA and description.get("scalar_mode") == "raw"
        and description.get("feature_kind") == "projected_clause_source"
        and description.get("hidden_width") == HIDDEN_WIDTH and description.get("source_formula") == FORMULA,
        "explicit clause-source model architecture required")
    base = shared_values._projected_specification(model.body, torch)
    _require(description.get("base_architecture") == base
        and description.get("base_architecture_is_pre_replacement_donor") is True,
        "clause donor architecture binding differs")
    for name in ("dimension", "feature_dimension", "max_rules", "source_fields", "vocabulary_size",
                 "codec_sha256", "normalization", "count_prior", "guide_boundary"):
        _require(description.get(name) == base.get(name), "clause inherited receipt differs: "+name)
    _require(description["codec_sha256"] == core.digest(codec)
        and description["vocabulary_size"] == len(codec["target_vocabulary"]), "clause codec differs")
    normalization = _normalization(description.get("clause_normalization"), model.dimension)
    _require(normalization["training_rows_sha256"] == description["normalization"]["training_rows_sha256"],
        "clause normalization cohort differs")
    for name, value in (("clause_source_mean", normalization["mean"]), ("clause_source_scale", normalization["scale"])):
        tensor = getattr(model, name, None)
        _require(isinstance(tensor, torch.Tensor) and tensor.dtype == torch.float32 and tensor.device.type == "cpu"
            and torch.equal(tensor, torch.tensor(value, dtype=torch.float32)), "clause frozen normalization buffer differs")
    seed = getattr(model, "head_initialization_seed", None)
    _require(isinstance(seed, torch.Tensor) and seed.dtype == torch.long and seed.device.type == "cpu"
        and seed.shape == torch.Size([]) and type(description.get("head_initialization_seed")) is int
        and 0 <= description["head_initialization_seed"] <= 2**31-1
        and int(seed) == description["head_initialization_seed"], "clause seed binding differs")
    size, dimension = description["vocabulary_size"], model.dimension
    head = model.clause_head
    shapes = {"source_projection.weight": (HIDDEN_WIDTH, dimension), "source_projection.bias": (HIDDEN_WIDTH,),
        "field_readout.weight": (len(SOURCE_FIELDS)*size, HIDDEN_WIDTH), "field_readout.bias": (len(SOURCE_FIELDS)*size,)}
    parameters = dict(head.named_parameters())
    _require(set(parameters) == set(HEAD_NAMES) and not dict(head.named_buffers())
        and all(tuple(parameters[name].shape) == shape and parameters[name].requires_grad for name, shape in shapes.items()),
        "clause shared head geometry differs")
    _require(type(head.source_projection) is torch.nn.Linear and type(head.field_readout) is torch.nn.Linear
        and not dict(model.body.source_value_head.named_parameters()) and not dict(model.body.source_value_head.named_buffers()),
        "clause head contains stale or non-affine modules")
    _require(description["source_value_parameter_names"] == ["clause_head."+name for name in HEAD_NAMES]
        and description["source_value_parameter_count"] == sum(value.numel() for value in parameters.values()),
        "clause parameter inventory differs")
    for name in ("guidance", "independent_source_head_replaced", "field_readouts_shared_across_slots",
                 "projection_frozen", "normalization_statistics_frozen", "count_prior_frozen", "source_context_required",
                 "full_vocabulary_retained", "ambient_rng_preserved", "initial_decoder_logits_unchanged"):
        _require(description.get(name) is True, "clause policy differs: "+name)
    for name in (*FALSE, "slot_parameters", "count_path_changed", "recurrent_path_changed", "paragraph_projection_path_changed",
                 "source_context_cached_on_module", "source_clause_count_used_for_stopping", "syntax_forced", "closure_forced",
                 "generation_reference_count_access", "reference_documents_passed_to_generation", "encoder_context_changed", "output_budget_changed"):
        _require(description.get(name) is False, "clause authority or source policy differs: "+name)
    _require(description.get("padding_policy") == "zero_only_scalar_residual"
        and description.get("clause_projection") == "same_frozen_paragraph_projection"
        and description.get("clause_normalization_weighting") == "unique_training_source_first_occurrence",
        "clause projection or normalization policy differs")
    projection = [parameter for name, parameter in model.named_parameters()
        if name.startswith(("body.body.body.projection_down.", "body.body.body.projection_up."))]
    _require(projection and all(not parameter.requires_grad for parameter in projection), "clause projection must remain frozen")
    return deepcopy(description)


def bind_zero_condition_model(model):
    """Remove paragraph and clause signal, including clause-mask length information."""
    torch = core._torch(); core._model(model, torch)
    _require(model.describe().get("schema") == SCHEMA, "clause-source model required")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.body = deepcopy(model); self.dimension = model.dimension

        def project(self, values): return self.body.project(values)
        def count_logits(self, projected):
            self.body.body.body._inputs(projected)
            return self.body.body._counts(torch.zeros_like(projected))
        def source_value_logits(self, projected, *, source_context):
            self.body.body.body._inputs(projected)
            _context(torch, projected, source_context, self.dimension)
            return self.body.clause_head(projected.new_zeros((len(projected), MAX_RULES, self.dimension)))
        def source_value_guidance_logits(self, projected, *, source_context):
            return self.source_value_logits(projected, source_context=source_context)
        def start(self, projected, *, source_context):
            values = self.source_value_logits(projected, source_context=source_context)
            hidden, source, position = self.body.body.body.start(projected)
            return (torch.zeros_like(hidden), torch.zeros_like(source), position, self.count_logits(projected),
                torch.zeros((len(projected), 6), dtype=torch.long), values)
        def next_logits(self, tokens, state): return self.body.next_logits(tokens, state)
        def forward(self, values, prefix, *, source_context):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected, source_context=source_context))
            return projected, logits
        def describe(self):
            return dict(schema="zero-clause-source-control/v1", dimension=self.dimension, scalar_mode="raw",
                initial_hidden_zeroed=True, persistent_source_zeroed=True, normalized_count_source_zeroed=True,
                normalized_clause_features_zeroed=True, original_clause_mask_ignored=True, all_eight_bias_slots_retained=True,
                learned_head_biases_and_frozen_count_prior_retained=True, projection_preserved=True,
                prefix_and_parser_state_preserved=True, source_context_required=True,
                scope="development_ablation_only", **FALSE)

    return ZeroCondition()
