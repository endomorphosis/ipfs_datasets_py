"""Exact bounded equality-state TLA+ projections with paired Lean semantics.

The old TLA compiler is unchanged. This explicit profile preserves both variable
names and IDs, action labels, guards, write frames and finite step bounds. It
does not generate a liveness obligation that the source never declared.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
from copy import deepcopy

from . import native_family_lean_emitters as lean
from ...software_verification.transitions import StateTransitionIR
from ...backends.process import BoundedToolRunner, ToolRunLimits, ToolRunRequest

SCHEMA = "native-bounded-state-tla/v2"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _literal(value):
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) is int:
        return str(value) if value >= 0 else "(" + str(value) + ")"
    lean.require(type(value) is str and value.isascii() and all(32 <= ord(c) < 127 for c in value),
                 "bounded_TLA_string_literal_required")
    return json.dumps(value)


def _review_ui_metadata(wire):
    """Review the exact untimed declaration fragment emitted by the UI owner."""
    meta = wire["metadata"]
    lean.require(set(meta) == {"UI_document_id", "UI_model_id", "source_sha256", "state_map", "origins",
        "terminal_states", "actual_event_occurrence_asserted", "guard_effect_timeout_loss"}
        and not wire["schema"]["metadata"] and meta["actual_event_occurrence_asserted"] is False
        and meta["guard_effect_timeout_loss"] is False, "TLA_UI_metadata_scope_requires_exact_review")
    lean.require(all(type(meta[key]) is str and meta[key] for key in ("UI_document_id", "UI_model_id", "source_sha256"))
        and re.fullmatch(r"[0-9a-f]{64}", meta["source_sha256"]) is not None, "TLA_UI_source_identity_required")
    states = meta["state_map"]
    lean.require(type(states) is dict and 1 <= len(states) <= 64
        and all(type(key) is str and key for key in states), "TLA_UI_state_map_required")
    lean.require(states == {key: "state_" + str(i) for i, key in enumerate(sorted(states))}, "TLA_UI_state_map_not_canonical_bijection")
    variables = wire["schema"]["variables"]
    lean.require(len(variables) == 1 and variables[0]["variable_id"] == "var:ui-state"
        and variables[0]["name"] == "ui_state" and variables[0]["type_kind"] == "enumeration"
        and variables[0]["domain_bound"]["members"] == list(states.values()), "TLA_UI_state_map_domain_differs")
    expected_refs = ["source:ui_ux_ir:" + meta["source_sha256"]]
    lean.require(all(item["source_ref_ids"] == expected_refs for item in
        [*variables, *wire["predicates"], *wire["actions"]]), "TLA_UI_source_reference_metadata_digest_differs")
    terminal = meta["terminal_states"]
    lean.require(type(terminal) is list and all(type(x) is str for x in terminal)
        and len(set(terminal)) == len(terminal) and set(terminal) <= set(states.values()), "TLA_UI_terminal_state_declarations_invalid")
    origins = meta["origins"]
    lean.require(type(origins) is list and 1 <= len(origins) <= 128 and len(origins) == len(wire["actions"]),
                 "TLA_UI_exact_all_action_origins_required")
    predicates = {p["predicate_id"]: p for p in wire["predicates"]}
    actions = {a["action_id"]: a for a in wire["actions"]}
    expected_predicates = {"pred:ui-init"}; expected_actions = []; transition_ids = []; source_events = set()
    for index, origin in enumerate(origins):
        lean.require(type(origin) is dict and set(origin) == {"action_id", "from_state", "to_state", "transition"},
                     "TLA_UI_closed_origin_required")
        transition = origin["transition"]
        lean.require(type(transition) is dict and set(transition) == {"transition_id", "source_state_ids", "target_state_id",
            "event_id", "guard_id", "effect_ids", "priority", "join_kind", "cancelable", "retryable", "undoable",
            "timeout_ms", "rollback_target_state_id"}, "TLA_UI_closed_transition_origin_required")
        lean.require(type(transition["source_state_ids"]) is list and len(transition["source_state_ids"]) == 1
            and transition["source_state_ids"][0] in states and transition["target_state_id"] in states
            and transition["join_kind"] == "all", "TLA_UI_single_declared_source_target_required")
        lean.require(transition["guard_id"] == "" and transition["effect_ids"] == [] and transition["timeout_ms"] is None
            and type(transition["priority"]) is int and transition["priority"] == 0 and transition["cancelable"] is True
            and transition["retryable"] is False and transition["undoable"] is False
            and transition["rollback_target_state_id"] == "", "TLA_UI_guard_effect_timeout_recovery_semantics_not_lowered")
        lean.require(all(type(transition[key]) is str and transition[key] for key in ("transition_id", "event_id")),
                     "TLA_UI_transition_event_identity_required")
        before = states[transition["source_state_ids"][0]]; after = states[transition["target_state_id"]]
        lean.require(origin["from_state"] == before and origin["to_state"] == after and before not in terminal,
                     "TLA_UI_origin_or_terminal_edge_mismatch")
        join = (before, transition["event_id"])
        lean.require(join not in source_events, "TLA_UI_ambiguous_event_edge"); source_events.add(join)
        transition_ids.append(transition["transition_id"])
        action_id = "action:ui:" + str(index); expected_actions.append(action_id)
        guard = "pred:ui-guard:" + str(index); nxt = "pred:ui-next:" + str(index)
        expected_predicates.update((guard, nxt))
        lean.require(action_id in actions, "TLA_UI_action_origin_without_native_action")
        action = actions[action_id]
        lean.require(origin["action_id"] == action_id == action["action_id"] and action["guard_predicate_id"] == guard
            and action["next_predicate_id"] == nxt and not action["label_ids"] and action["enables_stutter"] is False,
            "TLA_UI_exact_action_origin_join_required")
        lean.require(action["frame"] == {"reads": ["var:ui-state"], "writes": ["var:ui-state"], "allows_all_reads": False,
            "allows_all_writes": False, "schema_version": "action-frame/v1"}, "TLA_UI_action_frame_differs")
        lean.require(action["attributes"] == {"UI_transition_id": transition["transition_id"], "event_id": transition["event_id"],
            "step_is_declared_possibility_not_observed_occurrence": True}, "TLA_UI_action_event_origin_differs")
        for key, role, value in ((guard, "guard", before), (nxt, "next", after)):
            p = predicates.get(key, {})
            lean.require(p.get("role") == role and p.get("expression") == {"var:ui-state": value}
                and p.get("subject_variable_ids") == ["var:ui-state"], "TLA_UI_origin_native_predicate_differs")
    lean.require(transition_ids == sorted(set(transition_ids)), "TLA_UI_transition_origins_not_unique_canonical")
    lean.require(set(actions) == set(expected_actions), "TLA_UI_extra_or_missing_native_action")
    lean.require(set(predicates) == expected_predicates, "TLA_UI_extra_or_missing_native_predicate")
    initial = predicates["pred:ui-init"]
    lean.require(initial["role"] == "initial" and set(initial["expression"]) == {"var:ui-state"}
        and initial["expression"]["var:ui-state"] in states.values() and initial["subject_variable_ids"] == ["var:ui-state"],
        "TLA_UI_explicit_initial_state_required")
    relations = wire["transitions"]
    lean.require(len(relations) == 1 and relations[0]["relation_id"] == "transition:ui" and relations[0]["kind"] == "action"
        and relations[0]["action_ids"] == sorted(expected_actions) and not relations[0]["predicate_id"]
        and relations[0]["allows_stutter"] is False, "TLA_UI_extra_or_missing_declared_edge")
    return meta


def _review_annotations(wire, max_steps):
    """Recognize only reviewed abstractions; retain their source joins explicitly."""
    metadata = wire["metadata"]
    schema_metadata = wire["schema"]["metadata"]
    intent = None; ui = None
    if "UI_document_id" in metadata:
        ui = _review_ui_metadata(wire)
    elif metadata or schema_metadata:
        lean.require(schema_metadata == {"abstraction": "abstract_intent_control_flow"}
            and type(metadata) is dict and metadata.get("abstraction") == "abstract_intent_control_flow"
            and metadata.get("max_steps") == max_steps, "TLA_state_metadata_requires_exact_reviewed_Intent_scope")
        from . import native_intent_lean
        wrapper = {"context": {"abstraction": "abstract_intent_control_flow", "max_steps": max_steps},
            "format": "StateTransitionIR@1", "node_map": metadata.get("position_map"),
            "payload": wire, "source": "native_intent_ir"}
        native_intent_lean._linear_native(wrapper)
        lean.require(type(metadata["intent_document_id"]) is str and bool(metadata["intent_document_id"])
            and type(metadata["intent_ir_sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", metadata["intent_ir_sha256"]) is not None,
            "TLA_Intent_source_identity_required")
        intent = metadata
    intent_origins = []; events = []; synthetic = []; abstracts = []
    for action in wire["actions"]:
        attributes = action["attributes"]
        if "UI_transition_id" in attributes:
            lean.require(set(attributes) == {"UI_transition_id", "event_id", "step_is_declared_possibility_not_observed_occurrence"}
                and attributes["step_is_declared_possibility_not_observed_occurrence"] is True
                and all(type(attributes[k]) is str and attributes[k] for k in ("UI_transition_id", "event_id")),
                "TLA_UI_action_annotations_require_review")
            events.append((action["action_id"], attributes["UI_transition_id"], attributes["event_id"]))
        elif "abstract_event_only" in attributes:
            lean.require(intent is not None and attributes["abstract_event_only"] is True,
                         "TLA_Intent_action_annotations_require_reviewed_Intent_model")
            abstracts.append(action["action_id"])
            if set(attributes) == {"abstract_event_only", "intent_action_id"}:
                lean.require(type(attributes["intent_action_id"]) is str and bool(attributes["intent_action_id"]),
                             "TLA_Intent_action_origin_required")
                intent_origins.append((action["action_id"], attributes["intent_action_id"]))
            else:
                lean.require(set(attributes) == {"abstract_event_only", "origin"}
                    and attributes["origin"] == "adapter_generated_terminal_self_loop", "TLA_Intent_action_annotations_require_review")
                synthetic.append((action["action_id"], attributes["origin"]))
        else:
            lean.require(not attributes, "TLA_action_annotations_require_review")
    return {"intent": intent, "ui": ui, "intent_origins": intent_origins, "event_origins": events,
            "synthetic_origins": synthetic, "abstract_actions": abstracts}


def _annotation_declarations(annotations, aliases):
    tla_lines = []; lean_lines = []
    for name, values, width in (("SourceVariableAliases", list(aliases.items()), 2),
            ("ActionIntentOrigins", annotations["intent_origins"], 2),
            ("ActionEventOrigins", annotations["event_origins"], 3),
            ("SyntheticActionOrigins", annotations["synthetic_origins"], 2)):
        tla_lines.append(name + " == <<" + ", ".join("<<" + ", ".join(_literal(x) for x in row) + ">>" for row in values) + ">>")
        lean_lines.append("def " + name[0].lower() + name[1:] + " : List (" + " × ".join(["String"] * width) + ") := [" +
            ", ".join("(" + ", ".join(lean.string(x) for x in row) + ")" for row in values) + "]")
    intent = annotations["intent"]
    if intent is not None:
        for name, value in (("StateAbstraction", intent["abstraction"]), ("SourceIntentDocument", intent["intent_document_id"]),
                            ("SourceIntentIRSHA256", intent["intent_ir_sha256"])):
            tla_lines.append(name + " == " + _literal(value))
            lean_lines.append("def " + name[0].lower() + name[1:] + " : String := " + lean.string(value))
        values = [(r["state_action_id"], r["intent_action_id"], r["from_position"], r["to_position"]) for r in intent["position_map"]]
        tla_lines.append("IntentPositionMap == <<" + ", ".join("<<" + ", ".join(_literal(x) for x in row) + ">>" for row in values) + ">>")
        lean_lines.append("def intentPositionMap : List (String × String × String × String) := [" +
            ", ".join("(" + ", ".join(lean.string(x) for x in row) + ")" for row in values) + "]")
        tla_lines += ["CodeEffectsModeled == FALSE", "NormativeComplianceModeled == FALSE"]
        lean_lines += ["def codeEffectsModeled : Bool := false", "def normativeComplianceModeled : Bool := false"]
    ui = annotations["ui"]
    if ui is not None:
        for name, value in (("SourceUIDocument", ui["UI_document_id"]), ("SourceUIModel", ui["UI_model_id"]),
                            ("SourceUISHA256", ui["source_sha256"])):
            tla_lines.append(name + " == " + _literal(value))
            lean_lines.append("def " + name[0].lower() + name[1:] + " : String := " + lean.string(value))
        pairs = list(ui["state_map"].items())
        tla_lines.append("UIStateMap == <<" + ", ".join("<<" + _literal(a) + ", " + _literal(b) + ">>" for a, b in pairs) + ">>")
        lean_lines.append("def uiStateMap : List (String × String) := [" + ", ".join("(" + lean.string(a) + ", " + lean.string(b) + ")" for a, b in pairs) + "]")
        terminal = ", ".join(_literal(x) for x in ui["terminal_states"])
        tla_lines += ["UITerminalStates == {" + terminal + "}", "UITerminal == " + aliases["var:ui-state"] + " \\in UITerminalStates"]
        lean_lines += ["def uiTerminalStates : List String := [" + ", ".join(lean.string(x) for x in ui["terminal_states"]) + "]",
            "def uiTerminal (s : State) : Prop := s." + aliases["var:ui-state"] + " ∈ uiTerminalStates"]
        ids = [row["action_id"] for row in ui["origins"]]
        tla_lines += ["UIDeclaredCancelableActions == {" + ", ".join(_literal(x) for x in ids) + "}",
            "UIDeclaredCancelable(action) == action \\in UIDeclaredCancelableActions", "CancellationExecutionModeled == FALSE"]
        lean_lines += ["def uiDeclaredCancelable (action : String) : Bool := [" + ", ".join(lean.string(x) for x in ids) + "].contains action",
                      "def cancellationExecutionModeled : Bool := false"]
    tla_lines += ["RuntimeEventOccurrencesAttested == FALSE"]
    lean_lines += ["def runtimeEventOccurrencesAttested : Bool := false"]
    return tla_lines, lean_lines


def compile_bounded_state(document, *, max_steps=64):
    """Compile a native equality-map model; unsupported semantics fail closed."""
    lean.require(type(document) is StateTransitionIR, "exact_native_state_document_required")
    lean.require(type(max_steps) is int and 1 <= max_steps <= 1024, "bounded_step_count_required")
    wire = document.to_dict()
    annotations = _review_annotations(wire, max_steps)
    interpreted = deepcopy(wire)
    normalization = []
    variable_ids = {v["variable_id"] for v in wire["schema"]["variables"]}
    variable_aliases = {key: v["variable_id"] for v in wire["schema"]["variables"] for key in (v["variable_id"], v["name"])}
    predicates_by_id = {p["predicate_id"]: p for p in wire["predicates"]}
    for action in interpreted["actions"]:
        if action["enables_stutter"]:
            guard = predicates_by_id.get(action["guard_predicate_id"], {}).get("expression", {})
            nxt = predicates_by_id.get(action["next_predicate_id"], {}).get("expression", {})
            def canonical_values(values):
                result = {}
                for key, value in values.items():
                    identity = variable_aliases.get(key)
                    lean.require(identity not in result or result[identity] == value,
                                 "conflicting_aliases_in_self_loop_predicate")
                    result[identity] = value
                return result
            guard_values = canonical_values(guard)
            next_values = canonical_values(nxt)
            lean.require(guard_values and guard_values == next_values and None not in guard_values
                and set(action["frame"]["writes"]) <= set(guard_values) <= variable_ids
                and not action["frame"]["allows_all_writes"], "stutter_annotation_requires_explicit_self_loop")
            action["enables_stutter"] = False
            normalization.append({"action_id": action["action_id"], "reason": "guard_and_next_force_identical_state"})
    interpreted.pop("document_id", None)
    interpreted = StateTransitionIR.from_dict(interpreted).to_dict()
    native_lean, details = lean.state_document(interpreted)
    variables, predicates, actions = wire["schema"]["variables"], wire["predicates"], wire["actions"]
    for item in normalization:
        index = next(i for i, action in enumerate(actions) if action["action_id"] == item["action_id"])
        action = actions[index]
        guard = next(i for i, p in enumerate(predicates) if p["predicate_id"] == action["guard_predicate_id"])
        nxt = next(i for i, p in enumerate(predicates) if p["predicate_id"] == action["next_predicate_id"])
        native_lean += (f"\nexample (s : State) (h : predicate_{guard} s) : action_{index} s s := by\n"
            f"  simp_all [action_{index}, predicate_{guard}, predicate_{nxt}]\n")
    lean.require(all(not v["attributes"] and v["element_type_kind"] is None for v in variables),
                 "TLA_variable_annotations_require_review")
    lean.require(all(not p["attributes"] for p in predicates), "TLA_predicate_annotations_require_review")
    lean.require(all(not t["attributes"] for t in wire["transitions"]), "TLA_transition_annotations_require_review")
    names = {v["variable_id"]: "v" + str(i) for i, v in enumerate(variables)}
    aliases = {}
    for v in variables:
        for key in (v["variable_id"], v["name"]):
            lean.require(key not in aliases or aliases[key] == names[v["variable_id"]], "ambiguous_state_alias")
            aliases[key] = names[v["variable_id"]]
    pnames = {p["predicate_id"]: "Pred" + str(i) for i, p in enumerate(predicates)}
    anames = {a["action_id"]: "Action" + str(i) for i, a in enumerate(actions)}
    lean.require(not {"initial", "stutter"} & set(anames), "reserved_bounded_state_label")
    lines = ["---- MODULE BoundedNativeState ----", "EXTENDS Integers, Sequences", "", f"MaxSteps == {max_steps}"]
    annotation_tla, annotation_lean = _annotation_declarations(annotations, aliases)
    for v in variables:
        bound, kind = v["domain_bound"], v["type_kind"]
        if kind == "integer":
            domain = _literal(bound["lower"]) + ".." + _literal(bound["upper"])
        elif kind == "boolean":
            domain = "BOOLEAN"
        else:
            domain = "{" + ", ".join(_literal(x) for x in bound["members"]) + "}"
        lines.append(names[v["variable_id"]] + "Domain == " + domain)
    symbols = list(names.values())
    lines += ["VARIABLES " + ", ".join([*symbols, "step", "actionLabel"]),
              "vars == <<" + ", ".join([*symbols, "step", "actionLabel"]) + ">>"]
    lines += annotation_tla
    labels = ["initial", "stutter", *anames]
    clauses = [x + " \\in " + x + "Domain" for x in symbols]
    clauses += ["step \\in 0..MaxSteps", "actionLabel \\in {" + ", ".join(_literal(x) for x in labels) + "}"]
    lines.append("TypeOK == " + " /\\ ".join(clauses))
    for p in predicates:
        suffix = "'" if p["role"] == "next" else ""
        equalities = [aliases[key] + suffix + " = " + _literal(value) for key, value in sorted(p["expression"].items())]
        lines.append(pnames[p["predicate_id"]] + " == " + " /\\ ".join(equalities))
    initial = [pnames[p["predicate_id"]] for p in predicates if p["role"] == "initial"]
    lines.append("Init == TypeOK /\\ step = 0 /\\ actionLabel = \"initial\" /\\ " + " /\\ ".join(initial))
    for a in actions:
        parts = [pnames[a["next_predicate_id"]], "actionLabel' = " + _literal(a["action_id"])]
        if a["guard_predicate_id"]:
            parts.insert(0, pnames[a["guard_predicate_id"]])
        for var_id, symbol in names.items():
            if var_id not in a["frame"]["writes"]:
                parts.append(symbol + "' = " + symbol)
        lines.append(anames[a["action_id"]] + " == " + " /\\ ".join(parts))
    stutter = any(t["allows_stutter"] for t in wire["transitions"])
    used = {a for t in wire["transitions"] for a in t["action_ids"]}
    choices = [anames[a] for a in anames if a in used]
    if stutter:
        lines.append("DeclaredStutter == UNCHANGED <<" + ", ".join(symbols) + ">> /\\ actionLabel' = \"stutter\"")
        choices.append("DeclaredStutter")
    lean.require(choices, "nonempty_declared_transition_required")
    lines += ["Next == TypeOK /\\ TypeOK' /\\ step < MaxSteps /\\ step' = step + 1 /\\ (" + " \\/ ".join(choices) + ")",
              "Spec == Init /\\ [][Next]_vars"]
    invariants = [pnames[p["predicate_id"]] for p in predicates if p["role"] == "invariant"]
    lines += ["Safety == TypeOK" + (" /\\ " + " /\\ ".join(invariants) if invariants else ""), "====", ""]
    lean_source = native_lean + "\n" + "\n".join(annotation_lean) + f'''\n
def maxSteps : Nat := {max_steps}
structure BoundedState where
  state : State
  steps : Nat
  lastLabel : String
def boundedTypeOK (s : BoundedState) : Prop :=
  typeOK s.state ∧ s.steps ≤ maxSteps ∧ s.lastLabel ∈ [{', '.join(lean.string(x) for x in labels)}]
def boundedInitial (s : BoundedState) : Prop :=
  boundedTypeOK s ∧ initial s.state ∧ s.steps = 0 ∧ s.lastLabel = "initial"
def boundedNext (s t : BoundedState) : Prop :=
  boundedTypeOK s ∧ boundedTypeOK t ∧ s.steps < maxSteps ∧ t.steps = s.steps + 1 ∧
  next t.lastLabel s.state t.state
def specification (trace : Nat → BoundedState) : Prop :=
  boundedInitial (trace 0) ∧ ∀ n, boundedNext (trace n) (trace (n + 1)) ∨ trace (n + 1) = trace n
def safety (trace : Nat → BoundedState) : Prop :=
  ∀ n, boundedTypeOK (trace n){''.join(' ∧ predicate_' + str(i) + ' (trace n).state' for i, p in enumerate(predicates) if p['role'] == 'invariant')}
theorem next_preserves_declared_type (s t : BoundedState) (h : boundedNext s t) : boundedTypeOK t := h.2.1
'''
    artifact = {"schema": SCHEMA, "native_document": wire, "native_document_sha256": _digest(wire),
        "module_name": "BoundedNativeState", "model_text": "\n".join(lines),
        "tlc_config_text": "SPECIFICATION Spec\nINVARIANT Safety\nCHECK_DEADLOCK FALSE\n",
        "max_steps": max_steps, "lean_source": lean_source, "lowering": details,
        "source_action_event_annotations": {a["action_id"]: a["attributes"] for a in actions},
        "self_loop_normalization": normalization,
        "semantics": "bounded_labelled_equality_state_with_explicit_TLA_stuttering",
        "cancellation_execution_modeled": False, "actual_event_occurrence_asserted": False,
        "source_variable_aliases": aliases, "generated_liveness_properties": [],
        "unbounded_proof": False, "source_semantics_verified": False,
        "syntax_checker_executed": False, "model_checker_executed": False, "admitted": False,
        "limitations": ["finite_step_budget", "TLA_specification_allows_stuttering", "no_source_program_equivalence_proof"]}
    artifact["artifact_sha256"] = _digest(artifact)
    return artifact


def emit_projection(row, *, report=None):
    if row.get("profile") != "tla_plus" or row.get("payload", {}).get("schema") != SCHEMA:
        raise NotImplementedError
    payload = row["payload"]
    native = StateTransitionIR.from_dict(payload["native_document"])
    replay = compile_bounded_state(native, max_steps=payload["max_steps"])
    lean.require(replay == payload, "bounded_TLA_projection_replay_differs")
    return payload["lean_source"], {"validator": "exact_bounded_native_TLA_and_Lean_regeneration",
        "operators": [*payload["lowering"]["operators"], "finite_step_budget", "TLA_box_stuttering"],
        "assumptions": payload["limitations"], "syntax_requirements": [{"kind": "SANY",
            "module_name": payload["module_name"], "model_text": payload["model_text"]}]}


def check_sany(requirement, *, java_executable=None, tla2tools_jar=None, timeout_seconds=30):
    """Run the supplied local SANY parser with error exit codes and level checks."""
    if not java_executable or not tla2tools_jar:
        return {"status": "blocked", "executed": False, "reason": "local_Java_and_tla2tools_required"}
    java = shutil.which(str(java_executable)); jar = Path(tla2tools_jar).resolve()
    if java is None or not jar.is_file():
        return {"status": "blocked", "executed": False, "reason": "local_SANY_tool_unavailable"}
    name = requirement["module_name"]
    lean.require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name), "native_TLA_module_name_required")
    pins = {str(Path(java).resolve()): hashlib.sha256(Path(java).read_bytes()).hexdigest(),
            str(jar): hashlib.sha256(jar.read_bytes()).hexdigest()}
    environment = {"JAVA_TOOL_OPTIONS": "", "_JAVA_OPTIONS": "", "JDK_JAVA_OPTIONS": ""}
    runtime = BoundedToolRunner()
    probe = runtime.run(ToolRunRequest(argv=(java, "-version"), environment=environment,
        limits=ToolRunLimits(timeout_seconds=5, max_output_bytes=16384)))
    version_output = probe.stdout + "\n" + probe.stderr
    version = re.search(r'(?m)^(?:openjdk|java) version "(\d+)(?:[.][^"]*)?"', version_output)
    if not (probe.ok and not probe.output_truncated and version and int(version.group(1)) >= 17):
        return {"status": "blocked", "executed": False, "reason": "native_Java17_or_newer_version_probe_required",
                "version_probe": {"returncode": probe.returncode, "stdout": probe.stdout, "stderr": probe.stderr},
                "tool_sha256": pins, "admitted": False, "model_checker_executed": False}
    request = ToolRunRequest(argv=(java, "-Xmx128m", "-cp", str(jar), "tla2sany.SANY", "-error-codes", name + ".tla"),
        input_files={name + ".tla": requirement["model_text"]},
        environment=environment,
        limits=ToolRunLimits(timeout_seconds=timeout_seconds, max_output_bytes=131072,
                             max_input_bytes=1048576, max_workspace_bytes=16777216))
    result = runtime.run(request)
    stable = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in pins.items())
    parsed = re.search(r"(?m)^Parsing file [^\r\n]*/" + re.escape(name) + r"\.tla(?:\s|$)", result.stdout) is not None
    processed = re.search(r"(?m)^Semantic processing of module " + re.escape(name) + r"\s*$", result.stdout) is not None
    banner = re.search(r"(?m)^\*+ SANY\d* Version ", result.stdout) is not None
    passed = result.ok and stable and not result.output_truncated and not result.workspace_limit_exceeded and parsed and processed and banner
    return {"status": "passed" if passed else "failed", "executed": True, "command": list(request.argv),
        "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
        "timed_out": result.timed_out, "output_truncated": result.output_truncated,
        "tool_sha256": pins, "model_sha256": hashlib.sha256(requirement["model_text"].encode()).hexdigest(),
        "java_version_output": version_output, "matching_module_parse_observed": parsed,
        "matching_module_semantic_processing_observed": processed, "SANY_version_banner_observed": banner,
        "level_checking_enabled": True, "model_checker_executed": False, "admitted": False}
