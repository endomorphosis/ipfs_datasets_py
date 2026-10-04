"""Private clause decoder with an independently learned action representation.

The original source projection is copied into two independent branches. The
non-action branch owns actor/modality/object rows, and the action branch owns
only action rows. No old action parameters remain as dead trainable state.
Generation retains the inherited causal, full-vocabulary scalar residual.
"""
from copy import deepcopy

from . import clause_source_decoder_experiment as clauses
from . import decoder_distillation_experiment as core
from . import shared_slot_source_decoder_experiment as shared

SCHEMA = "action-factorized-clause-source-decoder-development/v1"
HIDDEN_WIDTH = clauses.HIDDEN_WIDTH
MAX_RULES = clauses.MAX_RULES
SOURCE_FIELDS = clauses.SOURCE_FIELDS
NON_ACTION_FIELDS = ("actor", "modality", "object")
HEAD_NAMES = clauses.HEAD_NAMES
FALSE = dict(clauses.FALSE)
FORMULA = "independent_action_tanh_projection_and_full_vocabulary_readout;shared_actor_modality_object_tanh_projection"
_require = core._require


def _slice_linear(torch, layer, indices):
    """Copy real rows without constructing unused parameters or consuming RNG."""
    result = deepcopy(layer)
    index = torch.tensor(indices, dtype=torch.long)
    result.out_features = len(indices)
    result.weight = torch.nn.Parameter(layer.weight.detach().index_select(0, index).clone(),
        requires_grad=layer.weight.requires_grad)
    result.bias = torch.nn.Parameter(layer.bias.detach().index_select(0, index).clone(),
        requires_grad=layer.bias.requires_grad)
    return result


def bind_action_factorized_clause_model(model, *, codec):
    """Privately split a validated clause head while preserving inherited paths.

Fresh zero-readout donors have exactly identical initial logits. A fitted
donor retains every parameter value in its corresponding branch, although
separate affine readouts can introduce ordinary floating-point rounding.
Neither target labels nor the contrastive training objective are accepted here.
"""
    torch = core._torch()
    inherited = clauses.checked_specification(model, codec)
    dimension, size = model.dimension, inherited["vocabulary_size"]
    action_rows = list(range(size, 2*size))
    other_rows = [i*size+j for i in (0, 2, 3) for j in range(size)]
    parameter_count = 2*(dimension+1)*HIDDEN_WIDTH + (HIDDEN_WIDTH+1)*4*size
    _require(parameter_count*4 <= 67108864, "factorized head allocation exceeds64MiB")
    inherited_digest = core.tensor_digest(model)
    fresh = not bool(model.clause_head.field_readout.weight.detach().any()) and not bool(
        model.clause_head.field_readout.bias.detach().any())
    frozen = {name: value.detach().clone() for name, value in model.named_buffers()}
    projection = {name: value.detach().clone() for name, value in model.named_parameters()
        if name.startswith(("body.body.body.projection_down.", "body.body.body.projection_up."))}
    _require(projection and all(not parameter.requires_grad for name, parameter in model.named_parameters()
        if name in projection), "frozen inherited projection required")
    frozen.update(projection)

    class FieldHead(torch.nn.Module):
        def __init__(self, rows):
            super().__init__()
            self.source_projection = deepcopy(model.clause_head.source_projection)
            self.field_readout = _slice_linear(torch, model.clause_head.field_readout, rows)
            self.training = model.clause_head.training

        def features(self, values):
            return torch.tanh(self.source_projection(values))

        def forward(self, values):
            return self.field_readout(self.features(values))

    class ActionFactorizedDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            # Keep the same body nesting, so raw native decoder provenance and
            # strict restoration do not need another wrapper-prefix exception.
            self.body = deepcopy(model.body)
            self.dimension = dimension
            self.non_action_head = FieldHead(other_rows)
            self.action_head = FieldHead(action_rows)
            self.training = model.training
            for name, value in model.named_buffers():
                if not name.startswith("body."):
                    self.register_buffer(name, value.detach().clone())
            for parameter in self.parameters():
                parameter.grad = None

        def load_state_dict(self, state_dict, strict=True, assign=False):
            _require(strict is True and assign is False and hasattr(state_dict, "items"),
                "strict nonassigning factorized state restoration required")
            current = self.state_dict()
            _require(set(state_dict) == set(current), "factorized state inventory differs")
            for name, expected in current.items():
                actual = state_dict[name]
                _require(isinstance(actual, torch.Tensor) and actual.dtype == expected.dtype
                    and actual.device.type == "cpu" and actual.shape == expected.shape
                    and (not actual.is_floating_point() or bool(torch.isfinite(actual).all())),
                    "factorized restored tensor geometry or finiteness differs: "+name)
            for name, expected in frozen.items():
                _require(torch.equal(state_dict[name], expected),
                    "factorized frozen projection or preprocessing differs: "+name)
            return super().load_state_dict(state_dict, strict=True, assign=False)

        def project(self, values): return self.body.project(values)
        def count_logits(self, projected): return self.body.count_logits(projected)

        def clause_features(self, projected, *, source_context):
            self.body.body._inputs(projected)
            vectors, mask = clauses._context(torch, projected, source_context, dimension)
            values = self.body.project(vectors.reshape(-1, dimension)).reshape(len(projected), MAX_RULES, dimension)
            return (values-self.clause_source_mean)/self.clause_source_scale, mask

        def source_action_features(self, projected, *, source_context):
            values, mask = self.clause_features(projected, source_context=source_context)
            result = self.action_head.features(values)*mask[:, :, None]
            _require(bool(torch.isfinite(result).all()), "nonfinite factorized action features")
            return result

        def action_features(self, projected, *, source_context):
            return self.source_action_features(projected, source_context=source_context)

        def _values(self, features):
            non_action = self.non_action_head(features).reshape(len(features), MAX_RULES, 3, size)
            action = self.action_head(features).reshape(len(features), MAX_RULES, size)
            return torch.stack((non_action[:, :, 0], action, non_action[:, :, 1], non_action[:, :, 2]), dim=2)

        def source_value_logits(self, projected, *, source_context):
            features, mask = self.clause_features(projected, source_context=source_context)
            return self._values(features)*mask[:, :, None, None]

        def source_value_guidance_logits(self, projected, *, source_context):
            return self.source_value_logits(projected, source_context=source_context)

        def start(self, projected, *, source_context):
            values = self.source_value_logits(projected, source_context=source_context)
            inherited_state = self.body.start(projected)
            return (*inherited_state[:-1], values)

        def next_logits(self, tokens, state): return self.body.next_logits(tokens, state)

        def forward(self, values, prefix, *, source_context):
            projected = self.project(values)
            logits, _ = self.next_logits(prefix, self.start(projected, source_context=source_context))
            return projected, logits

        def describe(self):
            result = deepcopy(inherited)
            result.update(schema=SCHEMA, inherited_clause_architecture=deepcopy(inherited),
                inherited_weights_sha256=inherited_digest,
                feature_kind="action_factorized_projected_clause_source", source_formula=FORMULA,
                action_representation_separate=True, non_action_fields=list(NON_ACTION_FIELDS), action_field="action",
                action_feature_dimension=HIDDEN_WIDTH,
                action_features="masked_tanh_of_independent_normalized_clause_affine",
                action_feature_target_access=False, action_features_normalized_to_unit_length=False,
                action_projection_initialized_from_shared_projection=True,
                action_projection_shares_storage=False, old_action_readout_rows_retained=False,
                split_readout_rows={"non_action": other_rows.copy(), "action": action_rows.copy()},
                source_value_parameter_names=[head+"."+name for head in ("non_action_head", "action_head") for name in HEAD_NAMES],
                source_value_parameter_count=parameter_count,
                additional_trainable_parameters=HIDDEN_WIDTH*(dimension+1),
                parameter_only_comparison=False, paired_fresh_initial_logits_exact=fresh,
                fitted_donor_affine_rounding_possible=not fresh,
                initial_decoder_logits_unchanged=fresh,
                field_readout_initialization="exact_original_field_rows",
                source_weight_initialization="independent_exact_copy_of_original_shared_projection",
                source_bias_initialization="independent_exact_copy_of_original_shared_projection_bias",
                ambient_rng_preserved=True, count_path_changed=False, recurrent_path_changed=False,
                paragraph_projection_path_changed=False, source_context_used_for_scalar_head_only=True,
                contrastive_loss_owned_by_model=False, closed_actor_action_pair_classifier=False)
            return result

    result = ActionFactorizedDecoder()
    _require(core.tensor_digest(model) == inherited_digest, "caller clause decoder changed")
    return result


def checked_specification(model, codec):
    torch = core._torch(); core._model(model, torch)
    spec = model.describe()
    _require(spec.get("schema") == SCHEMA and spec.get("source_formula") == FORMULA
        and spec.get("feature_kind") == "action_factorized_projected_clause_source", "explicit factorized clause architecture required")
    base = shared._projected_specification(model.body, torch)
    old = spec.get("inherited_clause_architecture")
    _require(type(old) is dict and old.get("schema") == clauses.SCHEMA and old.get("source_formula") == clauses.FORMULA
        and old.get("base_architecture") == base and spec.get("base_architecture") == base,
        "factorized original clause architecture differs")
    for name in ("dimension", "feature_dimension", "max_rules", "source_fields", "vocabulary_size", "codec_sha256",
                 "normalization", "count_prior", "guide_boundary", "clause_normalization", "head_initialization_seed"):
        _require(spec.get(name) == old.get(name), "factorized inherited receipt differs: "+name)
    _require(spec["codec_sha256"] == core.digest(codec)
        and spec["vocabulary_size"] == len(codec["target_vocabulary"]), "factorized codec differs")
    norm = clauses._normalization(spec["clause_normalization"], model.dimension)
    _require(norm["training_rows_sha256"] == base["normalization"]["training_rows_sha256"], "factorized training cohort differs")
    for name, value in (("clause_source_mean", norm["mean"]), ("clause_source_scale", norm["scale"])):
        actual = getattr(model, name, None)
        _require(isinstance(actual, torch.Tensor) and actual.dtype == torch.float32 and actual.device.type == "cpu"
            and torch.equal(actual, torch.tensor(value, dtype=torch.float32)), "factorized clause normalization buffer differs")
    seed = getattr(model, "head_initialization_seed", None)
    _require(isinstance(seed, torch.Tensor) and seed.dtype == torch.long and seed.device.type == "cpu" and seed.ndim == 0
        and type(spec.get("head_initialization_seed")) is int and 0 <= int(seed) <= 2**31-1
        and int(seed) == spec["head_initialization_seed"], "factorized seed differs")
    size, dim = spec["vocabulary_size"], model.dimension
    expected_names=[]
    for head_name, count in (("non_action_head", 3), ("action_head", 1)):
        head = getattr(model, head_name, None)
        _require(isinstance(head, torch.nn.Module), "factorized field head missing")
        expected = {"source_projection.weight": (HIDDEN_WIDTH, dim), "source_projection.bias": (HIDDEN_WIDTH,),
            "field_readout.weight": (count*size, HIDDEN_WIDTH), "field_readout.bias": (count*size,)}
        params = dict(head.named_parameters())
        _require(set(params) == set(expected) and not dict(head.named_buffers())
            and all(tuple(params[name].shape) == shape and params[name].requires_grad for name, shape in expected.items())
            and type(head.source_projection) is torch.nn.Linear and type(head.field_readout) is torch.nn.Linear,
            "factorized head geometry or trainability differs")
        expected_names.extend(head_name+"."+name for name in HEAD_NAMES)
    _require(model.action_head.source_projection.weight.data_ptr() != model.non_action_head.source_projection.weight.data_ptr()
        and model.action_head.source_projection.bias.data_ptr() != model.non_action_head.source_projection.bias.data_ptr(),
        "action and non-action projection storage is shared")
    _require(not hasattr(model, "clause_head") and not dict(model.body.source_value_head.named_parameters()),
        "dead inherited scalar parameters remain")
    total = sum(p.numel() for name, p in model.named_parameters() if name.startswith(("non_action_head.", "action_head.")))
    _require(set(model._modules) == {"body", "non_action_head", "action_head"}
        and set(model._buffers) == {"head_initialization_seed", "clause_source_mean", "clause_source_scale"}
        and set(dict(model.named_parameters())) == {"body."+name for name, _ in model.body.named_parameters()} | set(expected_names),
        "factorized outer state has unregistered or dead parameters")
    _require(spec.get("source_value_parameter_names") == expected_names and spec.get("source_value_parameter_count") == total
        and total == 2*(dim+1)*HIDDEN_WIDTH+(HIDDEN_WIDTH+1)*4*size
        and spec.get("additional_trainable_parameters") == HIDDEN_WIDTH*(dim+1), "factorized parameter inventory differs")
    _require(spec.get("split_readout_rows") == {"non_action": [i*size+j for i in (0, 2, 3) for j in range(size)],
        "action": list(range(size, 2*size))} and spec.get("non_action_fields") == list(NON_ACTION_FIELDS)
        and spec.get("action_field") == "action" and spec.get("action_feature_dimension") == HIDDEN_WIDTH,
        "factorized field ownership differs")
    for name in ("action_representation_separate", "action_projection_initialized_from_shared_projection", "ambient_rng_preserved",
        "guidance", "source_context_required", "projection_frozen", "normalization_statistics_frozen", "count_prior_frozen",
        "full_vocabulary_retained", "source_context_used_for_scalar_head_only"):
        _require(spec.get(name) is True, "factorized policy differs: "+name)
    for name in (*FALSE, "action_feature_target_access", "action_features_normalized_to_unit_length",
        "action_projection_shares_storage", "old_action_readout_rows_retained", "closed_actor_action_pair_classifier",
        "contrastive_loss_owned_by_model", "count_path_changed", "recurrent_path_changed", "paragraph_projection_path_changed",
        "source_context_cached_on_module", "source_clause_count_used_for_stopping", "syntax_forced", "closure_forced",
        "generation_reference_count_access", "reference_documents_passed_to_generation", "encoder_context_changed", "output_budget_changed"):
        _require(spec.get(name) is False, "factorized authority or source policy differs: "+name)
    _require(type(spec.get("paired_fresh_initial_logits_exact")) is bool
        and spec["fitted_donor_affine_rounding_possible"] is not spec["paired_fresh_initial_logits_exact"]
        and spec["initial_decoder_logits_unchanged"] is spec["paired_fresh_initial_logits_exact"], "factorized initialization claim differs")
    projection=[p for name,p in model.named_parameters() if name.startswith(("body.body.body.projection_down.","body.body.body.projection_up."))]
    _require(projection and all(not p.requires_grad for p in projection), "factorized projection must remain frozen")
    return deepcopy(spec)


def bind_zero_condition_model(model):
    """Remove paragraph and clause information, retaining both learned bias priors."""
    torch = core._torch(); core._model(model, torch)
    _require(model.describe().get("schema") == SCHEMA, "factorized clause model required")

    class ZeroCondition(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.body=deepcopy(model); self.dimension=model.dimension
        def project(self, values): return self.body.project(values)
        def count_logits(self, projected):
            self.body.body.body._inputs(projected)
            return self.body.body._counts(torch.zeros_like(projected))
        def source_action_features(self, projected, *, source_context):
            self.body.body.body._inputs(projected)
            clauses._context(torch, projected, source_context, self.dimension)
            return self.body.action_head.features(projected.new_zeros((len(projected), MAX_RULES, self.dimension)))
        def action_features(self, projected, *, source_context):
            return self.source_action_features(projected, source_context=source_context)
        def source_value_logits(self, projected, *, source_context):
            self.body.body.body._inputs(projected)
            clauses._context(torch, projected, source_context, self.dimension)
            return self.body._values(projected.new_zeros((len(projected), MAX_RULES, self.dimension)))
        def source_value_guidance_logits(self, projected, *, source_context):
            return self.source_value_logits(projected, source_context=source_context)
        def start(self, projected, *, source_context):
            values=self.source_value_logits(projected, source_context=source_context)
            hidden,source,position=self.body.body.body.start(projected)
            return (torch.zeros_like(hidden),torch.zeros_like(source),position,self.count_logits(projected),
                torch.zeros((len(projected),6),dtype=torch.long),values)
        def next_logits(self,tokens,state): return self.body.next_logits(tokens,state)
        def forward(self,values,prefix,*,source_context):
            projected=self.project(values)
            logits,_=self.next_logits(prefix,self.start(projected,source_context=source_context))
            return projected,logits
        def describe(self):
            return dict(schema="zero-action-factorized-clause-control/v1",dimension=self.dimension,scalar_mode="raw",
                initial_hidden_zeroed=True,persistent_source_zeroed=True,normalized_count_source_zeroed=True,
                normalized_clause_features_zeroed=True,original_clause_mask_ignored=True,all_eight_bias_slots_retained=True,
                action_and_non_action_bias_priors_retained=True,learned_head_biases_and_frozen_count_prior_retained=True,
                projection_preserved=True,prefix_and_parser_state_preserved=True,source_context_required=True,
                scope="development_ablation_only",**FALSE)

    return ZeroCondition()
