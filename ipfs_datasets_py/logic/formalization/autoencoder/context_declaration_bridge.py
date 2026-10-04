"""Replay explicit context-slot declarations into existing Legal/UI v7 targets.

Retrieval does not select the declarations. Both provisional fixtures and
source-cited caller interpretations remain interpretations, with no fidelity,
training-review, runtime, or admission authority. The closed first profile
supports a single duration-qualified Legal norm/body pair and high-risk UI
single-confirm bindings. Unsupported structures remain explicit errors.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import weakref

from .. import context_resolution as context
from .. import context_slot_bindings as bindings_owner
from . import family_training_v2 as source_owner
from . import family_training_v6 as previous
from . import family_training_v7 as targets
from . import native_family_lake_v5 as native
from . import native_legal_qualified_lean as legal
from . import native_ui_confirmation_lean as ui
from . import projection_validation_contract_v5 as policy

SCHEMA = "context-declaration-target-bridge/v1"
LEGAL_PROJECTIONS = ("legal-ir/modal-family/deontic/v3", "legal-ir/modal-family/temporal/v3")
UI_PROJECTIONS = ("ui_ux_ir:tdfol",)
SLOTS = {
    "legal_ir": {"legal.temporal_anchor": "temporal_anchor", "legal.temporal_model": "temporal_model", "legal.scope": "scope"},
    "ui_ux_ir": {"ui.confirmation_policy": "confirmation_policy", "ui.trace_scope": "trace_scope"},
}
FALSE = {"source_semantics_verified": False, "qualified": False, "admitted": False,
    "formalized": False, "roundtrip_ok": False, "constitution_formalized": False,
    "applicability_reviews_created": False, "capability_floor_credit_granted": False,
    "event_occurrences_attested": False, "backend_execution_verified": False,
    "training_executed": False, "supervisor_importable": False}
_PINS = {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    for module in (context, bindings_owner, source_owner, previous, targets, native, legal, ui, policy)}
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_REGISTRY = weakref.WeakKeyDictionary()
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]{0,255}\Z")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed_" + label + "_required")


def _guard():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA256,
             "context_bridge_producer_changed")
    for module in (context, bindings_owner, source_owner, previous, targets, native, legal, ui, policy):
        _require(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == _PINS[module.__name__],
                 "context_bridge_dependency_changed:" + module.__name__)


def _clone_inputs(domain_id, inputs, *, interpreted=False):
    from ....optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument
    from .native_formula_evidence import NativeFormulaEvidence
    from ...ir_core.provenance import SourceRef
    required = {"document", "source_text"} if domain_id == "legal_ir" else {"ui_training_row"}
    allowed = required | {"formula_inputs"}
    if interpreted:
        allowed |= {"legal_qualifier_inputs" if domain_id == "legal_ir" else "ui_confirmation_inputs"}
    _require(type(inputs) is dict and required <= set(inputs) <= allowed, "closed_bridge_source_inputs_required")
    if domain_id == "legal_ir":
        _require(type(inputs["document"]) is ModalIRDocument and type(inputs["source_text"]) is str
                 and inputs["source_text"] == inputs["document"].normalized_text, "exact_legal_document_text_required")
        result = {"document": deepcopy(inputs["document"]), "source_text": inputs["source_text"]}
    else:
        _require(type(inputs["ui_training_row"]) is dict, "canonical_UI_training_row_required")
        result = {"ui_training_row": json.loads(_wire(inputs["ui_training_row"]))}
    if "formula_inputs" in inputs:
        formulas = inputs["formula_inputs"]
        _require(type(formulas) in (tuple, list) and len(formulas) <= 32 and
                 all(type(item) is NativeFormulaEvidence for item in formulas), "bounded_native_formula_inputs_required")
        result["formula_inputs"] = [NativeFormulaEvidence(item.requirement_id, item.formula,
            SourceRef.from_dict(item.source_ref.to_dict())) for item in formulas]
    if interpreted:
        for key, kind in (("legal_qualifier_inputs", legal.LegalQualifierInterpretation),
                          ("ui_confirmation_inputs", ui.UIConfirmationInterpretation)):
            if key in inputs:
                _require(all(type(item) is kind for item in inputs[key]), "typed_bridge_interpretations_required")
                result[key] = [kind.from_dict(item.to_dict()) for item in inputs[key]]
    return result


def _selected_source(domain_id, inputs, bundle):
    raw, _, _ = source_owner._source_bytes(domain_id, inputs)
    expected = targets.supplemental_source_ref(domain_id, **inputs)
    selected = bundle["selected_source"]
    span = selected["span"]
    _require(selected["source_ref"] == expected.to_dict(), "context_selected_source_ref_differs")
    _require(span["source_ref_id"] == expected.ref_id and span["start_byte"] == 0
             and span["end_byte"] == len(raw), "whole_native_source_context_span_required")
    _require(selected["text"].encode("utf-8") == raw and selected["text_sha256"] == hashlib.sha256(raw).hexdigest(),
             "context_selected_source_bytes_differ")
    return expected


def _slot_values(domain_id, bundle, index, declarations):
    _require(type(declarations) in (tuple, list) and len(declarations) == len(SLOTS[domain_id]),
             "complete_closed_context_binding_set_required")
    slots = {row["slot_id"]: row for row in bundle["slots"]}
    _require(len(slots) == len(bundle["slots"]) and set(slots) == set(SLOTS[domain_id]), "exact_bridge_slots_required")
    projections = LEGAL_PROJECTIONS if domain_id == "legal_ir" else UI_PROJECTIONS
    records = {}
    for declaration in declarations:
        _require(type(declaration) is bindings_owner.ContextBindingDeclaration, "issued_context_binding_type_required")
        bindings_owner.validate_context_binding(declaration, bundle=bundle, index=index)
        record = declaration.to_dict()
        identity = record["slot_id"]
        _require(identity in slots and identity not in records, "unknown_or_duplicate_bridge_binding")
        _require(record["mode"] in {"fixture_assumption", "source_cited_declaration"}, "explicit_interpretation_mode_required")
        _require(record["bundle_sha256"] == bundle["bundle_sha256"], "context_binding_bundle_differs")
        _require(slots[identity]["sort"] == SLOTS[domain_id][identity], "context_slot_sort_differs")
        _require(sorted(record["projection_ids"]) == sorted(projections) == sorted(slots[identity]["projection_ids"]),
                 "context_binding_projection_coverage_differs")
        records[identity] = record
    _require(set(records) == set(slots), "unconsumed_context_slot")
    return {identity: records[identity]["value"] for identity in sorted(records)}, [records[k] for k in sorted(records)]


def _envelope(module, row, source, declarations):
    return {"schema": module.EVIDENCE_SCHEMA, "source_ref": source.to_dict(),
        "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
        "original_payload_sha256": module.digest(row["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": declarations}


def _legal(report, source, values):
    anchor, clock, scope = (values["legal.temporal_anchor"], values["legal.temporal_model"], values["legal.scope"])
    _closed(anchor, {"origin", "binding_kind", "trigger_ref"}, "legal_anchor")
    _require(anchor["origin"] == "caller_supplied_evaluation_time" and
        anchor["binding_kind"] == "evaluation_origin_declared_as_trigger" and type(anchor["trigger_ref"]) is str
        and _ID.fullmatch(anchor["trigger_ref"]), "supported_explicit_abstract_trigger_required")
    _closed(clock, {"temporal_kind", "quantity", "unit", "time_domain", "lower_inclusive", "upper_inclusive"}, "legal_clock")
    _require(clock["temporal_kind"] in {"within_duration", "minimum_duration"}
        and type(clock["quantity"]) is int and 1 <= clock["quantity"] <= 1000000
        and clock["unit"] in {"day", "hour"} and clock["time_domain"] == "discrete_nat"
        and clock["lower_inclusive"] is True and clock["upper_inclusive"] is True, "supported_explicit_duration_required")
    _closed(scope, {"norm_projection_id", "body_projection_id", "body_relation", "enclosing_modal_symbol",
        "activation_scope", "exception_scope", "independent_event_fact"}, "legal_scope")
    _require(scope["norm_projection_id"] == LEGAL_PROJECTIONS[0] and scope["body_projection_id"] == LEGAL_PROJECTIONS[1]
        and scope["body_relation"] == "temporal_view_is_auxiliary_body_not_fact"
        and scope["enclosing_modal_symbol"] in {"O", "P", "F"}
        and scope["activation_scope"] == "all_conditions_at_evaluation_origin"
        and scope["exception_scope"] == "activation_time_waiver" and scope["independent_event_fact"] is False,
        "explicit_scoped_legal_auxiliary_view_required")
    quantity, unit = clock["quantity"], clock["unit"]
    literal = ("within " if clock["temporal_kind"] == "within_duration" else "for at least ") + str(quantity) + " " + unit + ("s" if quantity != 1 else "")
    interpretations, formulas = [], {}
    for identity in LEGAL_PROJECTIONS:
        matches = [row for row in report["projections"] if row["projection_id"] == identity]
        _require(len(matches) == 1, "exact_legal_projection_pair_required")
        row, = matches
        _require(len(row["payload"]["formulas"]) == 1, "single_legal_norm_body_profile_required")
        formula, = row["payload"]["formulas"]
        _require(formula["conditions"] == [literal] and formula["exceptions"] == [], "legal_context_duration_or_qualifier_coverage_differs")
        formulas[identity] = formula
        declaration = {"formula_index": 0, "original_formula_sha256": legal.digest(formula),
            "kind": "activation_guarded_legal_rule", "activation_scope": scope["activation_scope"], "conditions": [],
            "temporal": {**clock, "source_index": 0, "source_text": literal, "origin": anchor["origin"]},
            "exception_scope": scope["exception_scope"], "exceptions": []}
        interpretations.append(legal.LegalQualifierInterpretation.from_dict(_envelope(legal, row, source, [declaration])))
    norm, body = (formulas[k] for k in LEGAL_PROJECTIONS)
    _require(norm["operator"]["symbol"] == scope["enclosing_modal_symbol"] and norm["predicate"] == body["predicate"],
             "legal_scope_or_body_predicate_differs")
    return interpretations, {"kind": "caller_declared_auxiliary_body_relation", **scope,
        "trigger_binding": anchor, "norm_formula_sha256": legal.digest(norm), "body_formula_sha256": legal.digest(body),
        "native_AST_containment_verified": False, "scope_truth_verified": False,
        "trigger_origin_correspondence_verified": False, "trigger_occurrence_attested": False,
        "trigger_binding_scope": "retained_caller_declaration; native_lowering_only_has_an_abstract_Nat_origin_parameter"}


def _ui(report, source, values, inputs):
    declared, trace = values["ui.confirmation_policy"], values["ui.trace_scope"]
    fixed = {"event_order": "strict_sequence_position", "clock_order": "nondecreasing", "time_domain": "discrete_nat_ticks",
        "freshness_upper_inclusive": True, "correlation": "action_request_token", "cancellation": "since_latest_confirmation",
        "consumption": "every_prior_invocation_consumes_token"}
    _closed(declared, set(fixed) | {"action_ids", "max_age_ticks"}, "UI_confirmation_policy")
    _require(all(type(declared[k]) is type(v) and declared[k] == v for k, v in fixed.items())
        and type(declared["max_age_ticks"]) is int and 1 <= declared["max_age_ticks"] <= 1000000,
        "supported_explicit_UI_policy_required")
    expected_trace = {"trace_scope": "finite_observed_prefix", "unobserved_future": "unknown",
        "origin": "caller_supplied_sequence_position", "event_occurrences_attested": False, "whole_workflow_verified": False}
    _closed(trace, expected_trace, "UI_trace_scope")
    _require(all(type(trace[k]) is type(v) and trace[k] == v for k, v in expected_trace.items()), "supported_UI_trace_scope_required")
    native_bindings = inputs["ui_training_row"]["bindings"]
    actions = [binding["action_id"] for binding in native_bindings]
    _require(type(declared["action_ids"]) is list and all(type(action) is str for action in declared["action_ids"])
        and sorted(declared["action_ids"]) == sorted(actions)
        and len(set(actions)) == len(actions), "UI_policy_must_account_for_every_native_action")
    _require(all(binding["risk_class"] == "high" and binding["confirmation_class"] == "confirm" for binding in native_bindings),
        "high_risk_single_confirm_profile_required")
    matches = [row for row in report["projections"] if row["projection_id"] == UI_PROJECTIONS[0]]
    _require(len(matches) == 1, "exact_UI_TDFOL_partition_required")
    row, = matches
    expected = {}
    for action in actions:
        expected[("obligation", f"confirm({action}) before invoke({action})", "strict")] = (action, "every_invocation_has_valid_confirmation")
        expected[("prohibition", f"invoke({action}) before confirm({action})", "strict")] = (action, "unconfirmed_invocation")
        expected[("prohibition", f"weaken_norm({action})", "strict")] = (action, None)
    seen, declarations = set(), []
    for index, formula in enumerate(row["payload"]["formulas"]):
        key = (formula["operator"], formula["proposition"], formula["strength"])
        _require(key in expected and key not in seen, "UI_formula_policy_coverage_differs")
        seen.add(key)
        action, policy_kind = expected[key]
        declaration = {"formula_index": index, "original_formula_sha256": ui.digest(formula), "kind": "atomic_UI_norm"}
        if policy_kind is not None:
            declaration.update(kind="UI_request_token_confirmation_policy", action_id=action, policy=policy_kind,
                max_age_ticks=declared["max_age_ticks"], trace_scope=trace["trace_scope"], unobserved_future=trace["unobserved_future"], **fixed)
        declarations.append(declaration)
    _require(seen == set(expected), "UI_formula_partition_omitted_native_policy")
    return [ui.UIConfirmationInterpretation.from_dict(_envelope(ui, row, source, declarations))]


def _prepare_record(domain_id, *, source_inputs, context_index, context_bundle, bindings):
    from ...autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    _guard()
    _require(domain_id in SLOTS, "supported_context_bridge_domain_required")
    context.validate_context_bundle(context_bundle, index=context_index)
    inputs = _clone_inputs(domain_id, source_inputs)
    source = _selected_source(domain_id, inputs, context_bundle)
    values, binding_records = _slot_values(domain_id, context_bundle, context_index, bindings)
    original = previous.prepare_family_training_targets_v6(domain_id, **inputs)
    relation = None
    if domain_id == "legal_ir":
        inputs["legal_qualifier_inputs"], relation = _legal(original, source, values)
        interpretation_key = "legal_qualifier_inputs"
        replaced = LEGAL_PROJECTIONS
    else:
        inputs["ui_confirmation_inputs"] = _ui(original, source, values, inputs)
        interpretation_key = "ui_confirmation_inputs"
        replaced = UI_PROJECTIONS
    report = targets.prepare_family_training_targets_v7(domain_id, **inputs)
    _require(len(report["requested_families"]) == len(report["family_inventory"]) == 40,
             "complete_contextual_family_inventory_required")
    _require(len(report["projections"]) == len(original["projections"]) and
        {row["projection_id"] for row in report["superseded_v7_qualifier_observations"]} == set(replaced),
        "context_bridge_projection_coverage_changed")
    receipt = {"schema": SCHEMA, "domain_id": domain_id, "native_source_ref": source.to_dict(),
        "original_report_sha256": original["report_sha256"], "interpreted_report_sha256": report["report_sha256"],
        "context_bundle_sha256": context_bundle["bundle_sha256"], "context_index_sha256": context_index.index_sha256,
        "context_index_revision": context_bundle["index_revision"], "context_bindings": binding_records,
        "binding_sha256": [declaration.sha256 for declaration in sorted(bindings, key=lambda item: item.to_dict()["slot_id"])],
        "consumed_slot_ids": sorted(values), "replaced_projection_ids": list(replaced),
        "explicit_interpretations": [item.to_dict() for item in inputs[interpretation_key]],
        "legal_auxiliary_view_relation": relation, "native_projection_count": len(report["projections"]),
        "producer_pins": {**_PINS, __name__: _SOURCE_SHA256},
        "scope": "explicit_context_bound_interpretations_not_inferred_source_truth",
        "cache_key_scope": "source_context_index_bindings_producers_and_both_native_reports",
        "Lake_executed": False, "SANY_executed": False, **FALSE}
    receipt["contextual_target_sha256"] = _digest(receipt)
    _guard()
    return {"receipt": _wire(receipt), "report": _wire(report), "source_inputs": inputs}


@dataclass(frozen=True, eq=False)
class PreparedContextualTargets:
    """Process-local replayable preparation; JSON alone carries no live gate."""

    def to_dict(self):
        _require(self in _REGISTRY, "issued_contextual_preparation_required")
        return json.loads(_REGISTRY[self]["receipt"])

    @property
    def report(self):
        _require(self in _REGISTRY, "issued_contextual_preparation_required")
        return json.loads(_REGISTRY[self]["report"])

    @property
    def source_inputs(self):
        _require(self in _REGISTRY, "issued_contextual_preparation_required")
        stored = _REGISTRY[self]
        return _clone_inputs(stored["domain_id"], stored["source_inputs"], interpreted=True)


def prepare_contextual_targets(domain_id, *, source_inputs, context_index, context_bundle, bindings):
    record = _prepare_record(domain_id, source_inputs=source_inputs, context_index=context_index,
        context_bundle=context_bundle, bindings=bindings)
    handle = PreparedContextualTargets()
    _REGISTRY[handle] = {**record, "domain_id": domain_id}
    return handle


def _replay(prepared, *, source_inputs, context_index, context_bundle, bindings):
    _require(type(prepared) is PreparedContextualTargets and prepared in _REGISTRY,
             "issued_contextual_preparation_required")
    stored = _REGISTRY[prepared]
    fresh = _prepare_record(stored["domain_id"], source_inputs=source_inputs,
        context_index=context_index, context_bundle=context_bundle, bindings=bindings)
    _require(fresh["receipt"] == stored["receipt"] and fresh["report"] == stored["report"],
             "contextual_preparation_differs_from_live_replay")
    return fresh


def validate_contextual_targets(prepared, *, source_inputs, context_index, context_bundle, bindings):
    _replay(prepared, source_inputs=source_inputs, context_index=context_index,
            context_bundle=context_bundle, bindings=bindings)
    return True


def build_contextual_family_lake(prepared, *, source_inputs, context_index, context_bundle, bindings,
                                lake_executable, output_directory,
                                java_executable=None, tla2tools_jar=None, timeout_seconds=60):
    """Replay context before/after actual native checks; never manufacture reviews.

    ``native_execution`` and ``observation`` are live owner handles. ``receipt``
    is a detached serializable observation, not training or proof authority.
    """
    fresh = _replay(prepared, source_inputs=source_inputs, context_index=context_index,
            context_bundle=context_bundle, bindings=bindings)
    report = json.loads(fresh["report"])
    execution = native.build_native_family_lake(report, source_inputs=fresh["source_inputs"],
        lake_executable=lake_executable, output_directory=output_directory, timeout_seconds=timeout_seconds,
        java_executable=java_executable, tla2tools_jar=tla2tools_jar)
    _replay(prepared, source_inputs=source_inputs, context_index=context_index,
            context_bundle=context_bundle, bindings=bindings)
    observation = policy.validate_projection_report(report, lake_execution=execution)
    gate = policy.evaluate_projection_training_batch([observation], domain_id=report["domain_id"], target_reports=[report])
    receipt = {"schema": "context-declaration-native-execution/v1", "preparation": prepared.to_dict(),
        "native": execution.to_dict(), "projection_validation": observation.to_dict(), "training_gate": gate,
        "context_replayed_before_and_after_native_checks": True, **FALSE}
    return {"native_execution": execution, "observation": observation, "report": report, "receipt": receipt}


__all__ = ["SCHEMA", "SLOTS", "LEGAL_PROJECTIONS", "UI_PROJECTIONS", "PreparedContextualTargets",
    "prepare_contextual_targets", "validate_contextual_targets", "build_contextual_family_lake"]
