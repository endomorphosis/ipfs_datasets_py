"""Private trainability policy for the source-value residual experiment.

Only the already defined scalar head is trainable. No forward path, feature
normalization, output support, objective, or selection gate is changed. The
inherited decoder and count parameters retain their exact numeric bytes.
"""
from copy import deepcopy

from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as values

SCHEMA = "source-value-frozen-inherited-policy/v1"
HEAD_NAMES = ("source_value_head.weight", "source_value_head.bias")
FALSE = dict(core.FALSE, native_validation_executed=False, lake_executed=False,
    optimizer_resumable=False, historical_linguistic_teacher_modified=False)


def _inventory(model):
    torch = core._torch()
    core._model(model, torch)
    core._require(callable(getattr(model, "describe", None)), "described source-value model required")
    architecture = model.describe()
    core._require(architecture.get("schema") == values.SCHEMA
        and architecture.get("max_rules") == values.MAX_RULES
        and architecture.get("source_fields") == list(values.SOURCE_FIELDS)
        and architecture.get("feature_kind") in ("projected_source", "inherited_conditioning")
        and architecture.get("guidance") is True
        and architecture.get("source_value_parameter_names") == list(HEAD_NAMES),
        "unchanged guided source-value model required")
    parameters = dict(model.named_parameters())
    core._require(set(HEAD_NAMES) < set(parameters)
        and all(name in HEAD_NAMES or name.startswith("body.") for name in parameters),
        "exact source-head and inherited-body parameter inventory required")
    core._require(sum(parameters[name].numel() for name in HEAD_NAMES)
        == architecture["source_value_parameter_count"], "source-head parameter count differs")
    return architecture, parameters


def verify_frozen_body(model, receipt):
    """Check body identity and exact trainability before and after private fits."""
    architecture, parameters = _inventory(model)
    core._require(type(receipt) is dict and receipt.get("schema") == SCHEMA
        and receipt.get("architecture_sha256") == core.digest(architecture)
        and receipt.get("trainable_parameter_names") == list(HEAD_NAMES),
        "bound frozen-body policy receipt required")
    core._require([name for name, parameter in parameters.items() if parameter.requires_grad] == list(HEAD_NAMES),
        "only source-value head parameters may be trainable")
    frozen = [name for name in parameters if name.startswith("body.")]
    core._require(frozen == receipt["frozen_parameter_names"]
        and core.tensor_digest(model.body) == receipt["inherited_body_tensor_sha256"],
        "frozen inherited body changed")
    return dict(verified=True, inherited_body_tensor_sha256=core.tensor_digest(model.body),
        full_model_tensor_sha256=core.tensor_digest(model), trainable_parameter_names=list(HEAD_NAMES),
        trainable_parameter_count=sum(parameters[name].numel() for name in HEAD_NAMES),
        frozen_parameter_count=sum(parameters[name].numel() for name in frozen), **FALSE)


def bind_head_only_model(model):
    """Return ``model`` and ``report`` after a private copy and explicit freeze.

    Tensor names and values stay identical to the supplied guided source-value
    wrapper. Existing caller gradients, modes, trainability, and RNG are intact;
    stale gradients are cleared on the private model only.
    """
    architecture, parameters = _inventory(model)
    initial = core.tensor_digest(model)
    inherited = core.tensor_digest(model.body)
    private = deepcopy(model)
    for name, parameter in private.named_parameters():
        parameter.requires_grad_(name in HEAD_NAMES)
        parameter.grad = None
    core._require(core.tensor_digest(private) == initial and core.tensor_digest(private.body) == inherited,
        "private freezing changed numerical state")
    report = dict(schema=SCHEMA, architecture_sha256=core.digest(architecture),
        initial_model_tensor_sha256=initial, inherited_body_tensor_sha256=inherited,
        trainable_parameter_names=list(HEAD_NAMES),
        frozen_parameter_names=[name for name in parameters if name.startswith("body.")],
        original_trainable_parameter_names=[name for name, parameter in parameters.items() if parameter.requires_grad],
        feature_kind=architecture["feature_kind"], feature_dimension=architecture["feature_dimension"],
        feature_normalization="none; original source-head geometry unchanged",
        autoregressive_source_guidance=True, inherited_count_head_frozen=True,
        selection_gates_changed=False, objective_changed=False, numeric_parameter_values_changed=False,
        private_gradients_cleared=True, caller_modified=False,
        scope="private exposed-development trainability ablation only", **FALSE)
    report["verification"] = verify_frozen_body(private, report)
    core._require(core.tensor_digest(model) == initial, "caller model changed")
    return dict(model=private, report=report)
