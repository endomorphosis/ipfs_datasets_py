"""Explicit UI cognition/norms over known, source-bound finite EC facts.

The cognitive and deontic operators are interpretation parameters, not assertions
that an actor knows, believes, intends, or complies. Every Happens/HoldsAt leaf
has an explicit native event/fluent/time binding and is inside the known prefix.
Unknown future observations are rejected, never converted to false predicates.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
import re

from . import family_training as core
from . import native_family_lean_emitters as lean
from . import native_formula_evidence as formulas
from . import native_ui_bounded_event_calculus as events
from . import intent_candidate_fidelity as json_audit
from . import ui_declared_source_fidelity as declared
from ...CEC.native import dcec_core, dcec_integration, dcec_parsing, dcec_cleaning, dcec_prototypes

SCHEMA = "native-ui-bounded-dcec/v1"
DESCRIPTOR_SCHEMA = "ui-bounded-dcec-formulas/v1"
PROJECTION_ID = "ui_ux_ir/explicit_logic/bounded_dcec/v1"
PROFILE = "explicit_ui_bounded_dcec/v1"
REPORT_SCHEMA = "ui-declared-logic-family-targets/v1"
MAX_FORMULAS = 8
require, wire, digest = events.require, events.wire, events.digest
_PINS = {name: sha for module in (core, lean, formulas, events, json_audit, declared,
                                 dcec_core, dcec_integration, dcec_parsing, dcec_cleaning, dcec_prototypes,
                                 importlib.import_module(__name__)) for name, sha in core._pin(module).items()}
_RESERVED = {"O", "P", "F", "K", "B", "I", "Happens", "HoldsAt", "Initiates", "Terminates",
             "Releases", "Clipped", "Initially", "ReleasedAt"}


def producer_pins():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        require(_pin_imported_module(importlib.import_module(name)) == sha, "UI DCEC producer changed: " + name)
    return {**events.producer_pins(), **_PINS}


def _closed(value, names, label):
    require(type(value) is dict and set(value) == set(names), "closed explicit " + label + " required")


def _text(value, label):
    require(type(value) is str and 0 < len(value.encode()) <= 256 and value.strip() == value,
            "bounded explicit " + label + " required")
    return value


def _refs(value, available):
    require(type(value) is list and value and all(type(item) is str for item in value)
            and value == sorted(set(value)) and set(value) <= available,
            "exact nonempty known UI source reference list required")


def _source_and_ec(source_text, candidate, ec_payload):
    require(type(source_text) is str and 0 < len(source_text.encode()) <= json_audit.MAX_BYTES,
            "bounded complete declared UI source required")
    json_audit._json_input(candidate)
    _closed(candidate, {"kind", "document", "logic"}, "UI logic candidate")
    require(candidate["kind"] == "ui_declared_logic", "explicit UI logic candidate required")
    _closed(candidate["logic"], {"temporal", "tdfol", "dcec"}, "UI logic family declarations")
    require(all(value is None or type(value) is dict for value in candidate["logic"].values()),
            "explicit nullable logic descriptors required")
    try:
        source = json.loads(source_text, object_pairs_hook=declared._unique, parse_constant=declared._constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("invalid declared UI logic source: " + str(error)) from error
    json_audit._json_input(source)
    _closed(source, {"schema", "candidate", "interpretations"}, "UI logic source")
    require(source["schema"] == "ui-declared-logic-source/v1" and wire(source["candidate"]) == wire(candidate),
            "complete original UI source/candidate disagreement")
    _closed(source["interpretations"], {"behavior", "guard", "event"}, "UI EC source declarations")
    require(type(ec_payload) is dict and ec_payload.get("schema") == events.SCHEMA,
            "existing bounded native UI EC payload required")
    native_target = {"kind": "document", "document": deepcopy(candidate["document"])}
    require(ec_payload.get("source_text") == source_text and wire(ec_payload.get("candidate")) == wire(native_target),
            "UI DCEC and EC must bind exact source and native document")
    behavior = events.previous.UIBehaviorInterpretation.from_dict(ec_payload["behavior_interpretation"])
    guard = events.previous.UIGuardInterpretation.from_dict(ec_payload["guard_interpretation"])
    event = events.UIBoundedECInterpretation.from_dict(ec_payload["event_interpretation"])
    hash_fields = {"source_sha256", "candidate_sha256", "behavior_sha256", "guard_sha256"}
    bodies = {name: {key: value for key, value in item.to_dict().items() if key not in hash_fields}
              for name, item in (("behavior", behavior), ("guard", guard), ("event", event))}
    require(wire(bodies) == wire(source["interpretations"]), "EC interpretation bodies differ from complete source")
    replay = events.prepare_payload(source_text, native_target, behavior, guard, event)
    require(wire(replay) == wire(ec_payload), "complete signed UI EC payload replay differs")
    return replay


def _tables(descriptor, candidate, ec):
    _closed(descriptor, {"schema", "agents", "events", "fluents", "times", "formulas"}, "UI DCEC descriptor")
    require(descriptor["schema"] == DESCRIPTOR_SCHEMA, "unsupported UI DCEC descriptor schema")
    references = {row["ref_id"] for row in candidate["document"]["sources"]}
    native_events = {row["event_id"]: row for row in candidate["document"]["events"]}
    native_states = {row["state_id"]: row for row in candidate["document"]["states"]}
    edges = {row["transition_id"]: row for row in ec["edges"]}
    fields = {"agents": {"symbol", "actor_id", "source_ref_ids"},
        "events": {"symbol", "transition_id", "event_id", "source_ref_ids"},
        "fluents": {"symbol", "state_id", "source_ref_ids"}, "times": {"symbol", "clock_time"}}
    aliases, tables = set(), {}
    for name, names in fields.items():
        rows = descriptor[name]
        require(type(rows) is list and len(rows) <= 32, "bounded explicit UI DCEC " + name + " table required")
        table, identities = {}, set()
        for row in rows:
            _closed(row, names, "UI DCEC " + name + " binding")
            symbol = row["symbol"]
            require(type(symbol) is str and re.fullmatch(r"[A-Z][A-Za-z0-9_]{0,63}", symbol)
                    and symbol not in aliases and symbol not in _RESERVED,
                    "unique nonreserved ground symbols with noncolliding roles required")
            aliases.add(symbol)
            if name != "times": _refs(row["source_ref_ids"], references)
            if name == "agents":
                identity = _text(row["actor_id"], "declared actor identity")
            elif name == "events":
                identity = _text(row["transition_id"], "native transition identity")
                event_id = _text(row["event_id"], "native event identity")
                require(identity in edges and event_id in native_events and edges[identity]["event_id"] == event_id,
                        "DCEC event must join one exact native transition and UI event")
                require(set(row["source_ref_ids"]) <= set(native_events[event_id]["source_ref_ids"]),
                        "DCEC event evidence must join original native event sources")
            elif name == "fluents":
                identity = _text(row["state_id"], "native fluent state identity")
                require(identity in native_states and identity in ec["states"], "DCEC fluent must join exact native UI state")
                require(set(row["source_ref_ids"]) <= set(native_states[identity]["source_ref_ids"]),
                        "DCEC fluent evidence must join original native state sources")
            else:
                identity = row["clock_time"]
                require(type(identity) is int and ec["origin"] <= identity <= 10**9
                        and (identity - ec["origin"]) % ec["resolution"] == 0,
                        "explicit aligned native clock time required")
            require(identity not in identities, "duplicate semantic identity in DCEC role table")
            identities.add(identity)
            table[symbol] = deepcopy(row)
        tables[name] = table
    require(tables["agents"] and tables["times"] and (tables["events"] or tables["fluents"]),
            "explicit agent, event/fluent and time bindings required")
    return tables, references


def _formula_records(descriptor, tables, references, ec):
    rows = descriptor["formulas"]
    require(type(rows) is list and 1 <= len(rows) <= MAX_FORMULAS, "one to eight explicit DCEC formulas required")
    records, identities, used = [], set(), {name: set() for name in tables}

    def term(tree, role):
        name, children = tree
        require(not children and name in tables[role], "undeclared or wrong-role DCEC ground constant: " + name)
        used[role].add(name)
        return tables[role][name]

    def inspect(tree, leaves, depth=0):
        require(depth <= 16, "bounded UI DCEC formula depth required")
        name, children = tree
        if name in {"O", "P", "F"}:
            require(len(children) == 1, "DCEC norm arity differs")
            inspect(children[0], leaves, depth + 1)
        elif name in {"K", "B", "I"}:
            require(len(children) == 2, "DCEC cognitive arity differs")
            term(children[0], "agents")
            inspect(children[1], leaves, depth + 1)
        elif name in {"and", "or", "not", "implies", "iff"}:
            require(len(children) == (1 if name == "not" else 2), "DCEC Boolean arity differs")
            for child in children: inspect(child, leaves, depth + 1)
        else:
            require(name in {"Happens", "HoldsAt"} and len(children) == 2,
                    "only explicit Happens/HoldsAt EC leaves supported")
            binding = term(children[0], "events" if name == "Happens" else "fluents")
            at = term(children[1], "times")["clock_time"]
            tick = (at - ec["origin"]) // ec["resolution"]
            require(tick < len(ec["occurrences"]) if name == "Happens" else tick < len(ec["fluent_values"]),
                    "DCEC event/fluent time lies beyond its known prefix; unknown is not false")
            identity = binding["transition_id"] if name == "Happens" else binding["state_id"]
            truth = ec["occurrences"][tick] == identity if name == "Happens" else identity in ec["fluent_values"][tick]
            leaves.append({"operator": name, "symbol": children[0][0], "identity": identity,
                "time_symbol": children[1][0], "clock_time": at, "logical_tick": tick, "known": True, "truth": truth})

    for row in rows:
        _closed(row, {"formula_id", "formula", "source_ref_ids"}, "DCEC formula record")
        identity = _text(row["formula_id"], "formula identity")
        require(identity not in identities, "unique DCEC formula identity required")
        identities.add(identity)
        _refs(row["source_ref_ids"], references)
        require(type(row["formula"]) is str and 0 < len(row["formula"].encode()) <= 4096,
                "bounded original DCEC formula required")
        tree = formulas._functional_tree(row["formula"])
        leaves = []
        inspect(tree, leaves)
        ast, printed, ast_format, counts, _ = formulas._dcec(row["formula"], "DCEC")
        records.append({**deepcopy(row), "printed": printed, "native_ast": ast, "ast_format": ast_format,
            "operator_counts": counts, "functional_tree": core._json(tree), "known_event_leaves": leaves})
    require(all(used[name] == set(table) for name, table in tables.items()),
            "every explicit DCEC role binding must occur in a complete formula")
    return records


def prepare_payload(source_text, candidate, *, ec_payload, descriptor):
    """Replay complete source, original candidate, native EC and DCEC structure."""
    pins = producer_pins()
    before = json_audit._json_input(candidate)
    require(type(candidate) is dict and type(candidate.get("logic")) is dict
            and type(descriptor) is dict and wire(descriptor) == wire(candidate["logic"].get("dcec")),
            "DCEC descriptor must be present unchanged in the original candidate")
    ec = _source_and_ec(source_text, candidate, ec_payload)
    tables, references = _tables(descriptor, candidate, ec)
    records = _formula_records(descriptor, tables, references, ec)
    payload = {"schema": SCHEMA, "source_text": source_text, "candidate": deepcopy(candidate),
        "source_sha256": json_audit._sha(source_text.encode()), "candidate_sha256": json_audit._sha(before),
        "descriptor": deepcopy(descriptor), "ec_payload": ec, "ec_payload_sha256": digest(ec),
        "native_document_target_sha256": digest(ec["candidate"]), "role_bindings": tables,
        "native_dcec_formulas": records, "producer_pins": pins,
        "source_semantics_verified": False, "event_authenticity_verified": False,
        "cognitive_truth_asserted": False, "normative_compliance_verified": False,
        "admitted": False, "qualified": False, "training_executed": False,
        "limitations": ["explicit_authored_modal_descriptors_not_neural_or_NL_inference",
            "agent_indexed_cognitive_and_deontic_parameters_without_axioms_or_truth_claims",
            "ground_Happens_HoldsAt_at_known_signed_prefix_times_only",
            "unknown_beyond_prefix_preserved_and_not_allowed_as_false_modal_contents",
            "declared_finite_EC_occurrences_not_authenticated_history", "actual_Lake_execution_required"]}
    require(len(wire(payload)) <= 8 * 1024 * 1024, "bounded complete DCEC payload capacity exceeded; no pruning")
    require(pins == producer_pins() and before == json_audit._json_input(candidate),
            "DCEC source owner or original candidate changed during preparation")
    return json.loads(wire(payload))


def _render(tree, tables):
    name, children = tree
    if name in {"K", "B", "I"}:
        actor = tables["agents"][children[0][0]]["actor_id"]
        return "(i.cognitive " + lean.string(name) + " (i.agent " + lean.string(actor) + ") " + _render(children[1], tables) + ")"
    if name in {"O", "P", "F"}:
        return "(i.modal " + lean.string("deontic:" + name) + " [] none " + _render(children[0], tables) + ")"
    if name in {"Happens", "HoldsAt"}:
        role, field, function = (("events", "transition_id", "happens") if name == "Happens"
                                 else ("fluents", "state_id", "holdsAt"))
        identity = tables[role][children[0][0]][field]
        at = tables["times"][children[1][0]]["clock_time"]
        return f"(fun _ => UIDCECEventModel.{function} {lean.string(identity)} {at} = some true)"
    values = ["(" + _render(child, tables) + " t)" for child in children]
    body = "¬ " + values[0] if name == "not" else (" " + {"and": "∧", "or": "∨", "implies": "→", "iff": "↔"}[name] + " ").join(values)
    return "(fun t => " + body + ")"


def _lean(payload):
    lines = ["namespace UIDCECEventModel", events._lean(payload["ec_payload"]), "end UIDCECEventModel"]
    for index, record in enumerate(payload["native_dcec_formulas"]):
        expression = _render(record["functional_tree"], payload["role_bindings"])
        lines.append(f"def uiDCECFormula{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + expression)
        for leaf in record["known_event_leaves"]:
            function = "happens" if leaf["operator"] == "Happens" else "holdsAt"
            call = f"UIDCECEventModel.{function} {lean.string(leaf['identity'])} {leaf['clock_time']}"
            lines.append(f"example : ({call}).isSome = true := by decide")
            lines.append(f"example : {call} = some {str(leaf['truth']).lower()} := by decide")
    return "\n".join(lines)


def emit_projection(row, *, report=None):
    """Lower this exact owned route; unrelated routes alone use NotImplementedError."""
    if type(row) is not dict or row.get("projection_id") != PROJECTION_ID:
        raise NotImplementedError
    producer_pins()
    lean.require(type(report) is dict and report.get("schema") == REPORT_SCHEMA
        and report.get("domain_id") == "ui_ux_ir" and row.get("logic_family") == "dcec"
        and row.get("profile") == PROFILE and row.get("ready_for_training") is True
        and row.get("source_digest") == report.get("source_digest")
        and sum(item == row for item in report.get("projections", [])) == 1,
        "exact source-bound UI DCEC report and unique owned row required")
    from . import ui_declared_logic_source as adapter
    binding = report["declared_logic_source_binding"]
    adapter.validate_family_training_report(report, source_text=binding["source_text"], candidate=binding["candidate"])
    payload = row["payload"]
    expected = prepare_payload(binding["source_text"], binding["candidate"], ec_payload=payload["ec_payload"],
                               descriptor=binding["candidate"]["logic"]["dcec"])
    lean.require(wire(expected) == wire(payload), "complete UI DCEC native source/payload replay differs")
    return _lean(expected), {"validator": "complete_native_DCEC_and_known_bounded_EC_source_replay",
        "operators": sorted({name for record in expected["native_dcec_formulas"]
            for name in _operators(record["functional_tree"])}),
        "capability_floor_eligible": True,
        "capability_scope": "explicit_cognitive_normative_composition_over_known_bounded_UI_EC_facts",
        "native_formula_count": len(expected["native_dcec_formulas"]),
        "known_event_leaf_count": sum(len(row["known_event_leaves"]) for row in expected["native_dcec_formulas"]),
        "assumptions": expected["limitations"], "source_semantics_verified": False,
        "event_authenticity_verified": False, "cognitive_truth_asserted": False,
        "normative_compliance_verified": False, "syntax_requirements": []}


def _operators(tree):
    name, children = tree
    if children:
        yield name
        for child in children: yield from _operators(child)


__all__ = ["prepare_payload", "emit_projection", "producer_pins", "PROJECTION_ID", "PROFILE", "SCHEMA"]
