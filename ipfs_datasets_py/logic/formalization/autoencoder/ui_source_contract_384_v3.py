"""Declared UI graph details and explicit caller-supplied behavior interpretations.

Graph literals retain field presence, reference membership, edge identity/slots
and child positions. They do not interpret purpose prose or establish policies.
Behavior is never inferred from a wire document or from the source sentence.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
import importlib
import json

from . import ui_source_contract_384_v2 as previous

SCHEMA = "source-ui-graph-qualification/v3"
BEHAVIOR_SCHEMA = "ui-behavior-interpretation/v1"
DECLARATION_SCOPE = "caller_supplied_behavior_interpretation_not_source_translation"
FALSE = previous.FALSE
_REFERENCE_SETS = {
    "modality_binding_ids": "ModalityBinding", "data_binding_ids": "DataBinding",
    "program_binding_ids": "ProgramBinding", "feedback_ids": "Feedback",
    "source_ref_ids": "SourceRef",
}
_LITERALS = {"purpose": "PurposeText", "accessible_name_ref": "AccessibleNameRef",
             "accessible_description_ref": "AccessibleDescriptionRef"}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _closed(value, names, label):
    _require(type(value) is dict and set(value) == set(names), "complete explicit " + label + " fields required")


def _model_from_wire(wire):
    from ...ui_ux_ir.model.behavior import (
        BehaviorModel, BehaviorState, BehaviorTransition, TransitionJoinKind, validate_behavior_model,
    )
    _closed(wire, (field.name for field in fields(BehaviorModel)), "BehaviorModel")
    _require(wire["schema_version"] == "ui-behavior-model/v1", "native behavior schema required")
    _require(type(wire["states"]) is list and 1 <= len(wire["states"]) <= 64
        and type(wire["transitions"]) is list and 1 <= len(wire["transitions"]) <= 128,
        "bounded nonempty behavior states and transitions required")
    _require(type(wire["model_id"]) is str and type(wire["initial_state_ids"]) is list
        and all(type(item) is str for item in wire["initial_state_ids"]), "explicit native behavior identifiers required")
    states = []
    for row in wire["states"]:
        _closed(row, (field.name for field in fields(BehaviorState)), "BehaviorState")
        _require(all(type(row[name]) is str for name in ("state_id", "label", "parallel_region"))
            and type(row["terminal"]) is bool, "explicit typed behavior state values required")
        states.append(BehaviorState(**row))
    transitions = []
    for row in wire["transitions"]:
        _closed(row, (field.name for field in fields(BehaviorTransition)), "BehaviorTransition")
        _require(all(type(row[name]) is str for name in ("transition_id", "target_state_id", "event_id",
            "guard_id", "rollback_target_state_id", "join_kind")), "explicit typed behavior transition identifiers required")
        _require(type(row["priority"]) is int and all(type(row[name]) is bool
            for name in ("cancelable", "retryable", "undoable")), "explicit typed priority and recovery declarations required")
        _require(row["timeout_ms"] is None or type(row["timeout_ms"]) is int,
            "explicit integer or null timeout required")
        values = dict(row)
        for name in ("source_state_ids", "effect_ids"):
            _require(type(row[name]) is list and all(type(item) is str for item in row[name]),
                "explicit native behavior reference arrays required")
            values[name] = tuple(row[name])
        values["join_kind"] = TransitionJoinKind(row["join_kind"])
        transitions.append(BehaviorTransition(**values))
    model = BehaviorModel(model_id=wire["model_id"], states=tuple(states), transitions=tuple(transitions),
        initial_state_ids=tuple(wire["initial_state_ids"]), schema_version=wire["schema_version"])
    validate_behavior_model(model)
    _require(len({row.transition_id for row in model.transitions}) == len(model.transitions),
        "unique explicit behavior transition identities required")
    return model


@dataclass(frozen=True)
class UIBehaviorInterpretation:
    """Immutable complete native-model declaration bound to source and candidate."""

    _encoded: bytes

    def __post_init__(self):
        _require(type(self._encoded) is bytes and 0 < len(self._encoded) <= 131072,
            "bounded behavior interpretation bytes required")
        value = json.loads(self._encoded)
        _closed(value, {"schema", "source_sha256", "candidate_sha256", "declaration_scope", "behavior_model"},
            "UI behavior interpretation")
        _require(value["schema"] == BEHAVIOR_SCHEMA and value["declaration_scope"] == DECLARATION_SCOPE,
            "explicit caller behavior interpretation scope required")
        for key in ("source_sha256", "candidate_sha256"):
            _require(type(value[key]) is str and len(value[key]) == 64
                and all(c in "0123456789abcdef" for c in value[key]), "exact source and candidate hashes required")
        _model_from_wire(value["behavior_model"])
        _require(previous._wire(value) == self._encoded, "canonical behavior interpretation bytes required")

    @classmethod
    def from_dict(cls, value):
        return cls(previous._wire(value))

    @classmethod
    def from_model(cls, source_text, target, model):
        from . import family_training as core
        from ...ui_ux_ir.model.behavior import BehaviorModel
        _require(type(model) is BehaviorModel, "exact native BehaviorModel required")
        return cls.from_dict({"schema": BEHAVIOR_SCHEMA, "source_sha256": previous._source(source_text),
            "candidate_sha256": previous._digest(target), "declaration_scope": DECLARATION_SCOPE,
            "behavior_model": core._json(model)})

    def to_dict(self):
        return json.loads(self._encoded)


def _behavior(interpretation, source_text, target, kind, raw):
    if interpretation is None:
        return None, None
    _require(type(interpretation) is UIBehaviorInterpretation, "immutable UIBehaviorInterpretation required")
    receipt = interpretation.to_dict()
    _require(receipt["source_sha256"] == previous._source(source_text)
        and receipt["candidate_sha256"] == previous._digest(target), "behavior source/candidate binding differs")
    _require(kind == "document", "behavior interpretation requires a complete native UI document")
    _require(all(name in raw for name in ("states", "transitions", "initial_states", "events")),
        "explicit UI state, transition, initial and event declarations required")
    model = _model_from_wire(receipt["behavior_model"])
    states = {row.state_id: row for row in model.states}
    _require(set(states) == {row["state_id"] for row in raw["states"]}, "UI/behavior state identities differ")
    for row in raw["states"]:
        if "region_id" in row:
            _require(row["region_id"] == states[row["state_id"]].parallel_region, "UI/behavior state region differs")
    _require(sorted(model.initial_state_ids) == sorted(raw["initial_states"]), "UI/behavior initial states differ")
    transitions = {row.transition_id: row for row in model.transitions}
    _require(set(transitions) == {row["transition_id"] for row in raw["transitions"]},
        "UI/behavior transition identities differ")
    event_ids = {row["event_id"] for row in raw["events"]}
    for row in raw["transitions"]:
        edge = transitions[row["transition_id"]]
        _require(edge.source_state_ids == (row["source_state_id"],)
            and edge.target_state_id == row["target_state_id"], "UI/behavior transition endpoints differ")
        for name in ("event_id", "guard_id", "effect_ids", "priority"):
            if name in row:
                actual = list(getattr(edge, name)) if name == "effect_ids" else getattr(edge, name)
                _require(type(actual) is type(row[name]) and actual == row[name],
                    "UI/behavior transition " + name + " differs")
        _require(not edge.event_id or edge.event_id in event_ids, "behavior event label lacks explicit UI event declaration")
        # The legacy EC compiler substitutes transition_id when event_id is
        # empty. This adapter must not manufacture that apparent event label.
        _require(bool(edge.event_id), "explicit nonempty event label required; no transition-ID event fallback")
    return model, receipt


def _declarations(kind, raw):
    rows = [raw] if kind == "ui_component" else raw["components"]
    _, table, base = previous._declarations(rows)
    decode = {row["symbol"]: (row["category"], row["value"]) for row in table}
    declarations = [(row["predicate"], tuple(decode[arg] for arg in row["arguments"]),
                     "component:" + row["component_id"] + "/" + row["source_field"], "component_classification") for row in base]

    def add(predicate, args, path, scope="declared_graph_structure"):
        declarations.append((predicate, tuple(args), path, scope))

    for index, row in enumerate(rows):
        identity = ("component", row["component_id"])
        prefix = "/document" if kind == "ui_component" else f"/document/components/{index}"
        if "parent_id" in row:
            if row["parent_id"]:
                add("UIParent", (identity, ("component", row["parent_id"])), prefix + "/parent_id")
            else:
                add("UIEmptyParentField", (identity,), prefix + "/parent_id", "explicit_empty_parent_field_not_world_closedness")
        if "child_ids" in row:
            add("UIChildListLength", (identity, ("list_length", str(len(row["child_ids"])))), prefix + "/child_ids")
            for position, child in enumerate(row["child_ids"]):
                add("UIChildAt", (identity, ("list_position", str(position)), ("component", child)),
                    prefix + f"/child_ids/{position}", "ordered_declaration_not_arithmetic_order_theory")
        for name, suffix in _LITERALS.items():
            if name in row:
                add("UI" + suffix, (identity, (name, row[name])), prefix + "/" + name,
                    "literal_field_not_interpreted_prose_or_resolved_reference")
        for name, suffix in _REFERENCE_SETS.items():
            if name in row:
                add("UI" + suffix + "SetSize", (identity, ("set_size", str(len(row[name])))), prefix + "/" + name)
                for reference in row[name]:
                    add("UI" + suffix + "Ref", (identity, (name, reference)), prefix + "/" + name,
                        "declared_reference_not_target_fidelity_or_authority")
    if kind == "document":
        doc = ("document", raw["document_id"])
        add("UIDeclaredComponentSetSize", (doc, ("set_size", str(len(rows)))), "/document/components")
        for row in rows:
            add("UIDocumentComponent", (doc, ("component", row["component_id"])), "/document/components")
        if "entry_components" in raw:
            add("UIEntrySetSize", (doc, ("set_size", str(len(raw["entry_components"])))), "/document/entry_components")
            for value in raw["entry_components"]:
                add("UIEntryComponent", (doc, ("component", value)), "/document/entry_components")
        if "composition_edges" in raw:
            _require(len(raw["composition_edges"]) <= 128, "at most 128 explicit composition edges; no truncation")
            add("UICompositionEdgeSetSize", (doc, ("set_size", str(len(raw["composition_edges"])))), "/document/composition_edges")
            for index, edge in enumerate(raw["composition_edges"]):
                identity = ("composition_edge", edge["edge_id"])
                prefix = f"/document/composition_edges/{index}"
                add("UIDocumentEdge", (doc, identity), prefix)
                add("UICompositionEdge", (identity, ("edge_kind", edge["kind"]),
                    ("component", edge["source_component_id"]), ("component", edge["target_component_id"])), prefix)
                if "slot_name" in edge:
                    add("UIEdgeSlot", (identity, ("slot_name", edge["slot_name"])), prefix + "/slot_name",
                        "declared_slot_label_not_executable_binding")
                if "source_ref_ids" in edge:
                    add("UIEdgeSourceRefSetSize", (identity, ("set_size", str(len(edge["source_ref_ids"])))), prefix + "/source_ref_ids")
                    for ref in edge["source_ref_ids"]:
                        add("UIEdgeSourceRef", (identity, ("source_ref_ids", ref)), prefix + "/source_ref_ids",
                            "declared_provenance_link_not_source_truth")
    values = {arg for _, args, _, _ in declarations for arg in args}
    symbols = {(category, value): f"ui_{category}:v{value.encode('utf-8').hex()}" for category, value in sorted(values)}
    records = [{"predicate": predicate, "arguments": [symbols[arg] for arg in args],
                "source_path": path, "scope": scope} for predicate, args, path, scope in declarations]
    records.sort(key=lambda row: (row["predicate"], row["arguments"], row["source_path"]))
    formula = previous._conjunction([row["predicate"] + "(" + ",".join(row["arguments"]) + ")" for row in records])
    _require(len(formula.encode()) <= 16384, "UI graph formula exceeds native 16384-byte capacity; no truncation")
    table = [{"symbol": symbol, "category": category, "value": value} for (category, value), symbol in symbols.items()]
    return formula, table, records


def prepare_family_targets(source_text, target, requested_families=None, *, behavior_interpretation=None):
    """Preserve graph declarations; route only an explicit behavior interpretation."""
    source_sha = previous._source(source_text)
    from . import family_training as core, family_training_v7 as training
    from .native_formula_evidence import NativeFormulaEvidence, prepare_native_formula_evidence
    from ...ui_ux_ir.formalize.roundtrip import RoundTripDocument
    graph, scope = previous.previous._native(target)
    graph.validate()
    kind, raw = previous._raw_document(target)
    model, interpretation = _behavior(behavior_interpretation, source_text, target, kind, raw)
    formula, symbols, declarations = _declarations(kind, raw)
    candidate_sha = previous._digest(target)
    interpretation_sha = previous._digest(interpretation) if interpretation is not None else None
    identity = previous._digest({"candidate": candidate_sha, "behavior_interpretation": interpretation_sha})
    document = RoundTripDocument(document_id="ui-candidate:" + identity, component_graph=graph,
                                 behavior_model=model, actor_id="")
    source_inputs = {"document": document, "source_text": source_text}
    if requested_families is not None:
        source_inputs["requested_families"] = requested_families
    source_ref = training.supplemental_source_ref("ui_ux_ir", **source_inputs)
    evidence = NativeFormulaEvidence("FOL", formula, source_ref)
    native_formula = prepare_native_formula_evidence(evidence, source_ref)
    structure = previous._check_ground_ast(native_formula["payload"], declarations, symbols)
    source_inputs["formula_inputs"] = (evidence,)
    report = training.prepare_family_training_targets_v7("ui_ux_ir", **source_inputs)
    available = sorted({row["logic_family"] for row in report["projections"] if row["ready_for_training"]})
    requested = report["requested_families"]
    behavior_frontier = [deepcopy(row) for row in report["frontier"]
                         if row.get("family_id") in {"transition_system", "event_calculus"}]
    if model is None:
        behavior_status = "not_supplied_no_behavior_inferred"
    elif "transition_system" not in requested:
        behavior_status = "explicit_behavior_retained_but_state_route_not_requested"
    elif "transition_system" not in available:
        behavior_status = "blocked_explicit_behavior_native_state_route"
    else:
        behavior_status = "explicit_declared_control_targets_available_native_build_required"
    status = "projected_candidate_with_blocked_behavior" if behavior_status.startswith("blocked") else "projected_candidate"
    field_accounting = previous._field_accounting(kind, raw, [raw] if kind == "ui_component" else raw["components"], available)
    for row in field_accounting["component_fields"]:
        if row["supplied"]:
            row["disposition"] = "explicit_literal_graph_declaration_not_behavior_or_policy"
            row["declaration_families"] = sorted(set(row["declaration_families"]) | {"first_order"})
            row["represented_families"] = sorted(set(row["represented_families"]) | ({"first_order"} & set(available)))
    for row in field_accounting["document_fields"]:
        if row["supplied"] and row["path"] in {"/document/entry_components", "/document/composition_edges"}:
            row["disposition"] = "explicit_graph_declaration_projected"
    audit = {"schema": SCHEMA, "status": status, "scope": scope, "source_sha256": source_sha,
        "candidate_sha256": candidate_sha, "candidate": deepcopy(target), "candidate_rewritten": False,
        "source_fidelity_check_required": True, "continue_planning": True,
        "projection_scope": "literal_UI_graph_declarations_and_explicit_behavior_interpretation_only",
        "formula_scope": "ground_declaration_relations_not_world_closedness_or_numeric_order_theory",
        "symbol_table": symbols, "declarations": declarations, "native_formula": native_formula,
        "declaration_count": len(declarations), "ground_structure": structure, "field_accounting": field_accounting,
        "graph_scope": {"child_order_recorded": True, "edge_identity_and_explicit_slot_recorded": True,
            "literal_prose_interpreted": False, "binding_targets_resolved": False,
            "provenance_references_attested": False, "layout_or_policy_semantics_claimed": False},
        "behavior_interpretation": interpretation, "behavior_interpretation_sha256": interpretation_sha,
        "behavior_status": behavior_status, "behavior_frontier": behavior_frontier,
        "native_defaults_promoted": False, "source_text_to_formula_inference": False,
        "observed_events_invented": False, "actors_inferred": False,
        "unprojected_facets": list(previous._UNPROJECTED),
        "requested_families": requested, "available_families": available,
        "missing_requested_families": sorted(set(requested) - set(available)),
        "family_report_sha256": report["report_sha256"], "family_source_digest": report["source_digest"],
        "producer_pins": core._pin(importlib.import_module(__name__)), "lake_executed": False, **FALSE}
    audit["audit_sha256"] = previous._digest(audit)
    return {"report": report, "source_inputs": source_inputs, "audit": audit}


def qualify_source_candidate(source_text, target, requested_families=None, *, behavior_interpretation=None):
    source_sha = previous._source(source_text)
    try:
        prepared = prepare_family_targets(source_text, target, requested_families,
            behavior_interpretation=behavior_interpretation)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {"schema": SCHEMA, "status": "invalid_or_missing_context", "source_sha256": source_sha,
            "reason": str(error)[:1024], "continue_planning": True, "candidate_rewritten": False,
            "projections": [], "lake_executed": False, **FALSE}
    return {"status": prepared["audit"]["status"], "audit": prepared["audit"], "report": prepared["report"], **FALSE}


def validate_prepared(prepared, source_text, target, *, behavior_interpretation=None):
    _require(type(prepared) is dict and {"report", "source_inputs", "audit"} <= set(prepared),
        "prepared UI v3 adapter envelope required")
    expected = prepare_family_targets(source_text, target, prepared["source_inputs"].get("requested_families"),
        behavior_interpretation=behavior_interpretation)
    _require(expected == prepared, "UI v3 source/candidate/interpretation/symbol/report replay differs")
    return True


__all__ = ["UIBehaviorInterpretation", "prepare_family_targets", "qualify_source_candidate", "validate_prepared"]
