"""Validate explicit world-state interpretations for unchanged Intent predictions.

This adapter reuses the native guarded workflow and effect checker. It supplies
no guessed state variables, action effects, goal truth, or execution authority.
"""
from copy import deepcopy

from .contracts import require
from .projection_context_contract import bind_context
from .projection_inputs import prepare_source_inputs
from .. import native_intent_guarded_lean as guarded
from ....intent_ir.formalize.projection_contracts import source_ir_sha256

SCHEMA = "distributed-384-intent-world-model/v1"
FIELDS = {"schema", "native_document_sha256", "evidence_ref", "variables",
          "predicate_bindings", "action_updates", "retry_bounds", "effect_bindings", "max_steps"}


def intent_document(candidate, source_text):
    """Resolve the exact native owner used when a world interpretation is given."""
    context = bind_context("intent_ir", candidate, source_text, {"projection_context": {}})
    return prepare_source_inputs("intent_ir", candidate, source_text, context=context)["document"]


def world_model_requirements(candidate, source_text):
    """Expose native IDs so callers can declare bindings without guessing them."""
    document = intent_document(candidate, source_text)
    return dict(schema="distributed-384-intent-world-requirements/v1",
        native_document_sha256=source_ir_sha256(document),
        source_ref_ids=[row.ref_id for row in document.sources],
        actions=[row.to_dict() for row in document.actions],
        statements=[row.to_dict() for row in document.statements],
        control_edges=[row.to_dict() for row in document.control_edges],
        world_model_inferred=False, source_semantics_verified=False)


def bind_intent_world_model(candidate, source_text, world_model, *, additional_inputs=None):
    """Bind and replay all declared outcomes; retain false effects as blockers."""
    require(type(world_model) is dict and set(world_model) == FIELDS
            and world_model["schema"] == SCHEMA, "closed Intent world model required")
    document = intent_document(candidate, source_text)
    identity = source_ir_sha256(document)
    require(world_model["native_document_sha256"] == identity,
            "Intent world model belongs to another native prediction")
    require(additional_inputs is None or type(additional_inputs) is dict,
            "structured additional Intent declarations required")
    inputs = deepcopy({} if additional_inputs is None else additional_inputs)
    require(not set(inputs).intersection({"rich_slot_context", "projection_context", "guarded_effect_bindings"}),
            "Intent world model cannot overwrite an existing interpretation")
    workflow = dict(semantics="finite_guarded_state_flow", source_ir_sha256=identity,
        **{key: deepcopy(world_model[key]) for key in ("evidence_ref", "variables", "predicate_bindings",
                                                      "action_updates", "retry_bounds")})
    projection_context = {"state": {"max_steps": world_model["max_steps"], "workflow": workflow}}
    effects = dict(schema=guarded.BINDING_SCHEMA, source_ir_sha256=identity,
                   bindings=deepcopy(world_model["effect_bindings"]))
    # The existing owner checks finite domains, exact statement/action/source
    # joins, simultaneous updates, every reachable outcome, and step budgets.
    # A well-typed counterexample remains a reportable model, never a repair.
    guarded.prepare_guarded_payload(document, projection_context, guarded.IntentEffectBindings.from_dict(effects))
    inputs.update(projection_context=projection_context, guarded_effect_bindings=effects)
    context = bind_context("intent_ir", candidate, source_text, inputs)
    prepare_source_inputs("intent_ir", candidate, source_text, context=context)
    return context
