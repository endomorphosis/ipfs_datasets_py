"""Private 8D formula sidecar with a separate object source projection.

The historical linguistic teacher is neither accepted nor changed. This is an
explicit architectural experiment, not qualification or a new target decoder.
"""
from copy import deepcopy

from . import decoder_distillation_experiment as core
from . import ordered_clause_recurrent_decoder_experiment as ordered

SCHEMA = "isolated-object-8d-clause-source-decoder-development/v1"
LINEAGE = "isolated_object_8d_formula_sidecar_v1"
EXTRA_NAMES = ("non_action_head.object_projection.weight", "non_action_head.object_projection.bias")
ADDITIONAL_PARAMETERS = 64 * (8 + 1)
_require = core._require


def _storage_unique(model):
    parameters = list(model.named_parameters(remove_duplicate=False))
    ids = [id(p) for _, p in parameters]
    pointers = [p.untyped_storage().data_ptr() for _, p in parameters]
    _require(len(ids) == len(set(ids)) and len(pointers) == len(set(pointers)),
             "isolated object model parameters must not alias each other")


def bind_isolated_object_model(model, *, codec):
    """Clone a checked ordered 8D model without RNG or caller mutations.

    Full96-row affine geometry is retained for both readouts. Actor/modality
    slices use shared features; only the object slice uses the cloned private
    features. This also preserves initial logits for fitted donors, without
    introducing unused trainable readout rows or forcing generated syntax.
    """
    torch = core._torch()
    inherited = ordered.checked_specification(model, codec)
    _require(model.dimension == 8, "isolated object experiment requires actual8D formula inputs")
    _storage_unique(model)
    old_digest = core.tensor_digest(model)
    size = inherited["vocabulary_size"]
    original_type = type(model)
    fixed = {name: value.detach().clone() for name, value in model.named_buffers()}
    fixed.update({name: value.detach().clone() for name, value in model.named_parameters()
                  if not value.requires_grad})

    class ObjectSeparatedHead(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source_projection = deepcopy(model.non_action_head.source_projection)
            self.field_readout = deepcopy(model.non_action_head.field_readout)
            self.object_projection = deepcopy(model.non_action_head.source_projection)
            self.training = model.non_action_head.training

        def features(self, values):
            # Existing ordered recurrence consumes precisely these64 features.
            return torch.tanh(self.source_projection(values))

        def object_features(self, values):
            return torch.tanh(self.object_projection(values))

        def forward(self, values):
            shared = self.field_readout(self.features(values))
            private = self.field_readout(self.object_features(values))
            return torch.cat((shared[..., :2 * size], private[..., 2 * size:]), dim=-1)

    class IsolatedObjectDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model.body)
            self.non_action_head = ObjectSeparatedHead()
            self.action_head = deepcopy(model.action_head)
            self.clause_to_embedding = deepcopy(model.clause_to_embedding)
            self.dimension = 8
            self.training = model.training
            for name, value in model._buffers.items():
                self.register_buffer(name, value.detach().clone())
            for parameter in self.parameters():
                parameter.grad = None

        project = original_type.project
        count_logits = original_type.count_logits
        clause_features = original_type.clause_features
        source_action_features = original_type.source_action_features
        action_features = original_type.action_features
        _values = original_type._values
        source_value_logits = original_type.source_value_logits
        source_value_guidance_logits = original_type.source_value_guidance_logits
        source_recurrent_features = original_type.source_recurrent_features
        start = original_type.start
        next_logits = original_type.next_logits
        forward = original_type.forward

        def load_state_dict(self, state_dict, strict=True, assign=False):
            _require(strict is True and assign is False and hasattr(state_dict, "items"),
                     "strict nonassigning isolated object restoration required")
            expected = self.state_dict()
            _require(set(state_dict) == set(expected), "isolated object state inventory differs")
            # Validate everything before copying any destination tensor.
            for name, wanted in expected.items():
                actual = state_dict[name]
                _require(isinstance(actual, torch.Tensor) and actual.dtype == wanted.dtype
                         and actual.device.type == "cpu" and actual.shape == wanted.shape
                         and (not actual.is_floating_point() or bool(torch.isfinite(actual).all())),
                         "isolated object restored geometry or finiteness differs: " + name)
            for name, wanted in fixed.items():
                _require(torch.equal(state_dict[name], wanted), "isolated object frozen tensor differs: " + name)
            return super().load_state_dict(state_dict, strict=True, assign=False)

        def describe(self):
            result = deepcopy(inherited)
            names = inherited["source_value_parameter_names"] + list(EXTRA_NAMES)
            result.update(schema=SCHEMA, experimental_lineage=LINEAGE,
                inherited_ordered_architecture=deepcopy(inherited), isolated_object_parent_tensor_sha256=old_digest,
                object_feature_dimension=64, object_source_projection_separate=True,
                object_projection_initialization="independent_exact_copy_of_shared_projection",
                object_projection_shares_storage=False, object_readout_rows=[2 * size, 3 * size],
                shared_fields=["actor", "modality"], independent_fields=["action", "object"],
                shared_recurrent_features_unchanged=True, object_features_added_to_recurrence=False,
                recurrent_feature_order=["non_action", "action"],
                object_full_affine_geometry_preserved=True, source_readout_affine_calls=3,
                duplicated_readout_parameters=False, dead_trainable_readout_rows=False,
                source_value_parameter_names=names,
                source_value_parameter_count=inherited["source_value_parameter_count"] + ADDITIONAL_PARAMETERS,
                isolated_object_additional_parameters=ADDITIONAL_PARAMETERS,
                initial_full_logits_exact=True, fitted_donor_affine_rounding_possible=False,
                ambient_rng_preserved=True, existing_targets_changed=False, existing_loss_reduction_changed=False,
                historical_linguistic_teacher_modified=False, parameter_only_comparison=False)
            return result

    result = IsolatedObjectDecoder()
    checked_specification(result, codec)
    _require(core.tensor_digest(model) == old_digest, "caller ordered model changed during object split")
    return result


def checked_specification(model, codec):
    """Validate the new inventory explicitly; old architecture checks stay strict."""
    torch = core._torch()
    core._model(model, torch)
    spec = model.describe()
    _require(model.dimension == 8 and spec.get("schema") == SCHEMA
             and spec.get("experimental_lineage") == LINEAGE, "explicit isolated8D object architecture required")
    inherited = spec.get("inherited_ordered_architecture")
    _require(type(inherited) is dict and inherited.get("schema") == ordered.SCHEMA,
             "checked ordered predecessor required")
    head = getattr(model, "non_action_head", None)
    _require(isinstance(head, torch.nn.Module) and set(head._modules) == {
        "source_projection", "field_readout", "object_projection"} and not head._buffers,
        "closed isolated object head required")

    class SharedHeadView(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.source_projection = head.source_projection
            self.field_readout = head.field_readout

    class OrderedView(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dimension = 8
            for name in ("body", "action_head", "clause_to_embedding"):
                self.add_module(name, getattr(model, name))
            self.non_action_head = SharedHeadView()
            for name, value in model._buffers.items():
                self.register_buffer(name, value)

        project = lambda self, *a, **kw: model.project(*a, **kw)
        start = lambda self, *a, **kw: model.start(*a, **kw)
        next_logits = lambda self, *a, **kw: model.next_logits(*a, **kw)
        describe = lambda self: deepcopy(inherited)

    ordered.checked_specification(OrderedView(), codec)
    layer = head.object_projection
    _require(type(layer) is torch.nn.Linear and layer.in_features == 8 and layer.out_features == 64
             and tuple(layer.weight.shape) == (64, 8) and tuple(layer.bias.shape) == (64,)
             and layer.weight.requires_grad and layer.bias.requires_grad,
             "trainable independent8to64 object projection required")
    names = inherited["source_value_parameter_names"] + list(EXTRA_NAMES)
    original_names = {"body." + n for n, _ in model.body.named_parameters()} | {
        h + "." + n for h in ("non_action_head", "action_head") for n in ordered.action.HEAD_NAMES} | {"clause_to_embedding.weight"}
    _require(set(model._modules) == {"body", "non_action_head", "action_head", "clause_to_embedding"}
             and set(dict(model.named_parameters())) == original_names | set(EXTRA_NAMES),
             "isolated object model has unexpected or dead parameters")
    _storage_unique(model)
    _require(spec.get("source_value_parameter_names") == names
             and spec.get("source_value_parameter_count") == inherited["source_value_parameter_count"] + ADDITIONAL_PARAMETERS
             and spec.get("isolated_object_additional_parameters") == ADDITIONAL_PARAMETERS,
             "isolated object parameter receipt differs")
    expected = dict(object_feature_dimension=64, object_source_projection_separate=True,
        object_projection_initialization="independent_exact_copy_of_shared_projection",
        object_projection_shares_storage=False, object_readout_rows=[2 * spec["vocabulary_size"], 3 * spec["vocabulary_size"]],
        shared_fields=["actor", "modality"], independent_fields=["action", "object"],
        shared_recurrent_features_unchanged=True, object_features_added_to_recurrence=False,
        object_full_affine_geometry_preserved=True, source_readout_affine_calls=3,
        duplicated_readout_parameters=False, dead_trainable_readout_rows=False,
        initial_full_logits_exact=True, fitted_donor_affine_rounding_possible=False,
        ambient_rng_preserved=True, existing_targets_changed=False, existing_loss_reduction_changed=False,
        historical_linguistic_teacher_modified=False, parameter_only_comparison=False)
    _require(set(spec) == set(inherited) | set(expected) | {
        "experimental_lineage", "inherited_ordered_architecture", "isolated_object_parent_tensor_sha256",
        "isolated_object_additional_parameters"}, "isolated object specification inventory differs")
    _require(all(spec.get(k) == v for k, v in expected.items()), "isolated object policy receipt differs")
    _require(core._SHA.fullmatch(spec.get("isolated_object_parent_tensor_sha256", "")) is not None,
             "isolated object parent tensor identity required")
    changed = {"schema", "source_value_parameter_names", "source_value_parameter_count", *expected}
    _require(all(spec.get(k) == v for k, v in inherited.items() if k not in changed),
             "isolated object changed an inherited semantic or source contract")
    for name in (*ordered.FALSE, "syntax_forced", "closure_forced", "encoder_context_changed", "output_budget_changed"):
        _require(spec.get(name) is False, "isolated object confers no authority: " + name)
    return deepcopy(spec)


def optimizer_groups(model, trainable, specification, options, multiplier):
    """Use the existing non-action learning rate for all six owned tensors.

    The base group and global clip order retain the model's original parameter
    iteration order. This helper is dispatched only after full schema checking.
    """
    _require(specification.get("schema") == SCHEMA and model.describe() == specification,
             "checked isolated object specification required for optimizer groups")
    _storage_unique(model)
    expected = {"non_action_head." + n for n in (
        "source_projection.weight", "source_projection.bias", "field_readout.weight", "field_readout.bias",
        "object_projection.weight", "object_projection.bias")}
    named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    _require({n for n, _ in named if n.startswith("non_action_head.")} == expected,
             "exact six isolated non-action tensors required")
    original_ids = [id(p) for p in trainable]
    _require(original_ids == [id(p) for _, p in named] and len(original_ids) == len(set(original_ids)),
             "original-order isolated trainable inventory required")
    groups, inventory = [], []
    for label, part, factor in (
            ("base", [(n, p) for n, p in named if n not in expected], 1.),
            ("non_action_head", [(n, p) for n, p in named if n in expected], multiplier)):
        _require(bool(part), "nonempty isolated optimizer groups required")
        rate = options["learning_rate"] * factor
        groups.append(dict(params=[p for _, p in part], lr=rate))
        inventory.append(dict(name=label, parameter_names=[n for n, _ in part],
            parameter_count=sum(p.numel() for _, p in part), learning_rate_multiplier=factor,
            initial_learning_rate=rate, minimum_learning_rate=rate * options["min_learning_rate_ratio"],
            weight_decay=options["weight_decay"]))
    _require({id(p) for group in groups for p in group["params"]} == set(original_ids)
             and sum(len(group["params"]) for group in groups) == len(original_ids),
             "isolated optimizer groups must be disjoint and exhaustive")
    return groups, inventory


def bind_inference_control(model, *, codec, zero_condition=False):
    """Copy the explicit new schema for residual-off or all-source-off controls."""
    checked_specification(model, codec)
    _require(type(zero_condition) is bool, "explicit inference control flag required")
    torch = core._torch()

    class Control(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.body = deepcopy(model); self.dimension = 8
        def project(self, x): return self.body.project(x)
        def _features(self, x, source_context):
            self.body.body.body._inputs(x)
            ordered.clauses._context(torch, x, source_context, 8)
            return x.new_zeros((len(x), ordered.MAX_RULES, 8))
        def count_logits(self, x):
            return self.body.body._counts(torch.zeros_like(x)) if zero_condition else self.body.count_logits(x)
        def source_action_features(self, x, *, source_context):
            return self.body.action_head.features(self._features(x, source_context)) if zero_condition else self.body.source_action_features(x, source_context=source_context)
        action_features = source_action_features
        def source_value_logits(self, x, *, source_context):
            return self.body._values(self._features(x, source_context)) if zero_condition else self.body.source_value_logits(x, source_context=source_context)
        source_value_guidance_logits = source_value_logits
        def source_recurrent_features(self, x, *, source_context):
            return torch.zeros_like(self.body.source_recurrent_features(x, source_context=source_context))
        def start(self, x, *, source_context):
            state = self.body.start(x, source_context=source_context)
            if not zero_condition: return (*state[:6], torch.zeros_like(state[6]))
            hidden, source, position = state[:3]
            return (torch.zeros_like(hidden), torch.zeros_like(source), position, self.count_logits(x),
                torch.zeros((len(x), 6), dtype=torch.long), self.source_value_logits(x, source_context=source_context),
                self.source_recurrent_features(x, source_context=source_context))
        def next_logits(self, tokens, state): return self.body.next_logits(tokens, state)
        def forward(self, x, prefix, *, source_context):
            projected = self.project(x)
            logits, _ = self.next_logits(prefix, self.start(projected, source_context=source_context))
            return projected, logits
        def describe(self):
            return dict(schema="isolated-object-inference-control/v1", dimension=8,
                all_source_routes_removed=zero_condition, only_recurrent_clause_residual_zeroed=not zero_condition,
                original_architecture=SCHEMA, source_context_required=True, scope="development_ablation_only", **ordered.FALSE)
    return Control()
