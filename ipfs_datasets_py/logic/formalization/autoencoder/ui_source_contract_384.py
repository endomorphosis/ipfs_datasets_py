"""Native semantic UI contracts for learned source candidates.

The source hash binds evidence to text; it does not prove the text's meaning.
F-logic covers component structure only, leaving other UI facets explicit.
"""
from __future__ import annotations

import hashlib
import json

FALSE = dict(proof_authority=False, source_semantics_verified=False,
             execution_authority=False, claim_proved=False)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()


def _native(target):
    from ....optimizers.logic_theorem_optimizer.domain_384_autoencoder import validate_target
    from ...ui_ux_ir.schema import UIComponent
    from ...ui_ux_ir.decoder import decode_ui_ir
    from ...ui_ux_ir.model.components import SemanticComponent, UIComponentGraph, CompositionRelationship
    validated = validate_target("ui_ux_ir", target)
    if validated["kind"] == "ui_component":
        values = dict(validated["native_ir"])
        for key, value in tuple(values.items()):
            if key.endswith("_ids"):
                values[key] = tuple(value)
        components = (SemanticComponent.from_envelope(UIComponent(**values)),)
        graph = UIComponentGraph(components)
        scope = "local_component_fragment"
    else:
        document = decode_ui_ir(validated["native_ir"])
        components = tuple(SemanticComponent.from_envelope(c) for c in document.components)
        graph = UIComponentGraph(components,
            tuple(CompositionRelationship.from_envelope(e) for e in document.composition_edges),
            document.entry_components)
        scope = "document_component_graph"
    for component in components:
        component.validate()
    if scope == "document_component_graph":
        graph.validate()
    return graph, scope


def validate_training_target(target):
    """Reject semantic vocabulary failures in fragments and full documents."""
    graph, scope = _native(target)
    return dict(valid=True, scope=scope, component_count=len(graph.components),
                target_sha256=_digest(target), **FALSE)


def qualify_source_candidate(source_text, target):
    """Validate and project without replacing or relabeling the prediction."""
    if type(source_text) is not str or not source_text.strip() or len(source_text.encode()) > 131072:
        raise ValueError("bounded nonempty UI source text required")
    report = dict(schema="source-ui-component-qualification/v1",
        source_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
        candidate_sha256=None, continue_planning=True,
        candidate_rewritten=False, **FALSE)
    try:
        report["candidate_sha256"] = _digest(target)
        graph, scope = _native(target)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {**report, "status": "invalid", "reason": str(error)[:1024], "projections": []}
    from ...ui_ux_ir.formalize.flogic import compile_component_graph_to_flogic
    try:
        compiled = compile_component_graph_to_flogic(graph)
    except (ValueError, TypeError, KeyError) as error:
        return {**report, "status": "missing_context", "scope": scope,
                "reason": str(error)[:1024], "projections": []}
    facts = [dict(predicate=f.predicate, args=list(f.args), source_ref_ids=list(f.source_ref_ids))
             for f in compiled.facts]
    return {**report, "status": "projected_candidate", "scope": scope,
        "component_count": len(graph.components),
        "projections": [dict(family_id="frame_logic", compiler=compiled.compiler,
            facts=facts, unsupported=list(compiled.unsupported), **FALSE)],
        "projection_scope": "component_identity_role_and_relationship_facts_only",
        "unprojected_facets": ["privacy_policy", "presentation_behavior", "accessibility_compliance",
            "temporal_interaction", "authorization", "program_bindings"],
        "source_fidelity_check_required": True}


__all__ = ["validate_training_target", "qualify_source_candidate"]
