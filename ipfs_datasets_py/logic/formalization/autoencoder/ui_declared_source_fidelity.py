"""Post-generation agreement for explicitly declared complete UI source documents.

This closed JSON source is an authored declaration, not natural-language inference
or authenticated event history. It supplies every semantic interpretation body;
only source/candidate binding hashes are derived. No model context is enlarged.
"""
from copy import deepcopy
import importlib
import json

from . import intent_candidate_fidelity as json_audit
from . import ui_candidate_fidelity as component_audit
from . import ui_source_contract_384 as native_owner
from . import ui_source_contract_384_v3 as behavior_owner
from . import ui_source_contract_384_v5 as projection
from . import native_ui_guarded_lean as guard_owner
from . import native_ui_bounded_event_calculus as event_owner
from ...ui_ux_ir.decoder import decode_ui_ir

SOURCE_SCHEMA = "ui-declared-source/v1"
SCHEMA = "ui-declared-source-fidelity/v1"
MAX_BYTES = json_audit.MAX_BYTES
FALSE = {**json_audit.FALSE, "roundtrip_ok": False, "event_authenticity_verified": False}
_REQUIREMENTS = {
    "transition_system": ["complete_native_behavior_model", "explicit_state_transition_event_correspondence",
        "explicit_Boolean_guard_meaning_when_guards_present"],
    "event_calculus": ["complete_native_behavior_model", "explicit_frozen_Boolean_parameters_and_guard_meaning",
        "explicit_clock_unit_epoch_origin_resolution", "complete_signed_transition_by_tick_occurrence_prefix",
        "explicit_initial_fluents_effect_timing_inertia_and_unknown_boundary_policy"],
    "temporal": ["explicit_temporal_formula_and_time_semantics_not_only_component_labels"],
    "deontic": ["explicit_actors_actions_and_norms_not_privacy_classification_labels"],
    "tdfol": ["explicit_actors_actions_norms_and_temporal_semantics"],
    "dcec": ["explicit_cognitive_actors_events_and_norms"],
}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _closed(value, names, label):
    _require(type(value) is dict and set(value) == set(names), "complete explicit " + label + " fields required")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate declared-source JSON key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite declared-source JSON constant: " + value)


def _pins():
    pins = component_audit._pins()
    from . import family_training as core
    modules = (importlib.import_module(__name__), behavior_owner, projection, guard_owner, event_owner,
        importlib.import_module(decode_ui_ir.__module__))
    for module in modules:
        pins.update(core._pin(module))
    return pins


def _complete_document(document):
    native = decode_ui_ir(document)
    _require(not json_audit._differences(native.to_dict(), document),
             "complete native UI wire required; omitted defaults are not source facts")
    native_owner.validate_training_target({"kind": "document", "document": document})


def _parse_source(source_text):
    _require(type(source_text) is str and 0 < len(source_text.encode()) <= MAX_BYTES,
             "bounded nonempty declared source required")
    try:
        source = json.loads(source_text, object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("invalid declared UI source JSON: " + str(error)) from error
    json_audit._json_input(source)
    _closed(source, {"schema", "document", "interpretations"}, "declared UI source")
    _require(source["schema"] == SOURCE_SCHEMA, "unsupported declared UI source schema")
    _complete_document(source["document"])
    _closed(source["interpretations"], {"behavior", "guard", "event"}, "interpretation declarations")
    bodies = source["interpretations"]
    for key in bodies:
        _require(bodies[key] is None or type(bodies[key]) is dict,
                 "interpretation must be explicit object or null: " + key)
    _require(bodies["guard"] is None or bodies["behavior"] is not None,
             "guard declaration requires explicit behavior declaration")
    _require(bodies["event"] is None or bodies["guard"] is not None,
             "event declaration requires explicit guard declaration")
    return source


def _bound_options(source_text, candidate, bodies):
    """Bind only independently parsed declarations; never manufacture semantics."""
    source_sha = json_audit._sha(source_text.encode())
    candidate_sha = event_owner.digest(candidate)
    options = {}
    if bodies["behavior"] is not None:
        body = bodies["behavior"]
        _closed(body, {"schema", "declaration_scope", "behavior_model"}, "behavior body")
        options["behavior_interpretation"] = projection.UIBehaviorInterpretation.from_dict({
            **deepcopy(body), "source_sha256": source_sha, "candidate_sha256": candidate_sha})
    if bodies["guard"] is not None:
        body = bodies["guard"]
        _closed(body, {"schema", "declaration_scope", "parameter_update_semantics", "variables", "guards", "max_steps"},
                "guard body")
        options["guard_interpretation"] = projection.UIGuardInterpretation.from_dict({**deepcopy(body),
            "source_sha256": source_sha, "candidate_sha256": candidate_sha,
            "behavior_sha256": event_owner.digest(options["behavior_interpretation"].to_dict())})
    if bodies["event"] is not None:
        body = bodies["event"]
        _closed(body, {"schema", "policy", "origin", "initial_true_fluents", "trace"}, "bounded event body")
        options["event_interpretation"] = projection.UIBoundedECInterpretation.from_dict({**deepcopy(body),
            "source_sha256": source_sha, "candidate_sha256": candidate_sha,
            "behavior_sha256": event_owner.digest(options["behavior_interpretation"].to_dict()),
            "guard_sha256": event_owner.digest(options["guard_interpretation"].to_dict())})
    return options


def _token_window(candidate):
    from ....optimizers.logic_theorem_optimizer import domain_384_autoencoder as source384
    raw = source384._raw(candidate).decode()
    pieces = source384._TOKEN.findall(raw)
    _require("".join(pieces) == raw, "native target has no exact lexical token encoding")
    return {"lexical_tokens": len(pieces), "tokens_with_boundaries": len(pieces) + 2,
        "model_target_token_limit": 64, "fits_current_model_window": len(pieces) + 2 <= 64,
        "current_learned_decoder_coverage_demonstrated": False, "context_window_changed": False}


def audit_candidate(source_text, candidate):
    """Full typed document equality after generation, before projection.

    The original source and rejected candidate are retained. Semantic context is
    checked by the existing projection owners during ``prepare_family_targets``;
    source agreement alone never implies a usable interpretation or qualification.
    """
    _require(type(source_text) is str and len(source_text.encode()) <= MAX_BYTES,
             "bounded original source string required")
    candidate_bytes = json_audit._json_input(candidate)
    original = deepcopy(candidate)
    pins = _pins()
    resolved_tree = component_audit.tree_pin.require_workspace_logic_tree()
    native_error = source_error = None
    try:
        _closed(original, {"kind", "document"}, "UI document candidate envelope")
        _require(original["kind"] == "document", "complete UI document candidate required")
        _complete_document(original["document"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        native_error = str(error)
    parsed = reference = None
    try:
        parsed = _parse_source(source_text)
        reference = {"kind": "document", "document": deepcopy(parsed["document"])}
        # Constructing immutable wrappers checks body shape/types only. Full
        # behavior/guard/trace cross-validation remains the projection owner's job.
        _bound_options(source_text, reference, parsed["interpretations"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        source_error = str(error)
    differences = None if reference is None else json_audit._differences(reference, original)
    exact = native_error is None and source_error is None and not differences
    status = ("native_invalid" if native_error is not None else "source_unsupported" if source_error is not None
              else "source_agreement" if exact else "source_disagreement")
    report = {"schema": SCHEMA, "domain_id": "ui_ux_ir", "status": status,
        "source_text": source_text, "source_sha256": json_audit._sha(source_text.encode()),
        "candidate": original, "candidate_sha256": json_audit._sha(candidate_bytes),
        "native_valid": native_error is None, "native_error": native_error,
        "native_validation_scope": "complete_native_UI_document_and_component_graph",
        "source_supported": source_error is None, "source_error": source_error,
        "source_reference": reference, "declared_interpretation_bodies": None if parsed is None else parsed["interpretations"],
        "source_reference_scope": "explicit_structured_source_document_not_inferred_natural_language",
        "source_grammar": SOURCE_SCHEMA, "exact": exact, "source_agreement": exact,
        "differences": differences, "comparison_scope": "complete_typed_UI_document_fields_and_array_order",
        "interpretation_semantics_checked": False,
        "producer_pins": pins, "resolved_logic_tree": resolved_tree,
        "owner_pin_scope": "direct_owners_loaded_code_and_disk_not_transitive_callgraph",
        "model_inference_executed": False, "model_inputs_modified": False,
        "neural_rich_document_generation_verified": False, "training_token_limit_changed": False,
        "target_token_window": _token_window(original) if native_error is None else None, **FALSE}
    _require(pins == _pins(), "declared UI fidelity producer changed during audit")
    _require(json_audit._json_input(candidate) == candidate_bytes and json_audit._json_input(original) == candidate_bytes,
             "declared UI fidelity candidate changed during audit")
    report["report_sha256"] = json_audit._sha(json_audit._raw(report))
    return report


def coverage_requirements(report):
    """Explain missing input requirements without creating nominal projections."""
    available = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    return [{"family_id": family, "status": "missing_or_unsupported",
             "required_explicit_semantics": _REQUIREMENTS.get(family,
                 ["family_specific_source_semantics_and_native_projection_not_supplied_by_component_classification"])}
            for family in report["requested_families"] if family not in available]


def prepare_family_targets(source_text, candidate, requested_families=None):
    """Route source-agreeing declarations to unchanged v5 projection owners."""
    audit = audit_candidate(source_text, candidate)
    _require(audit["status"] == "source_agreement", "declared UI source agreement required: " + audit["status"])
    parsed = _parse_source(source_text)
    options = _bound_options(source_text, candidate, parsed["interpretations"])
    before = json_audit._json_input(candidate)
    prepared = projection.prepare_family_targets(source_text, candidate, requested_families, **options)
    _require(json_audit._json_input(candidate) == before, "projection changed declared UI candidate")
    return {**prepared, "source_audit": audit,
            "missing_context_requirements": coverage_requirements(prepared["report"])}


__all__ = ["SOURCE_SCHEMA", "SCHEMA", "audit_candidate", "prepare_family_targets", "coverage_requirements"]
