"""Explicit typed interpretations of an unchanged native ConcurrencyIR.

This is a caller-authored model, not an inferred translation. Native identity,
all textual clause bindings, expression carrier and effect frames are checked.
ProgramIR owns integer/Boolean expression semantics; native channel/session
declarations receive separate operational semantics because ConcurrencyIR has
no field connecting a component step to a channel or session action.
"""
from __future__ import annotations

import json
import ast
import re

from . import native_interpretation_expressions as expressions
from .native_family_lean_emitters import require, string
from ...software_verification import concurrency as native

SCHEMA = "native-concurrency-interpretation/v1"
PROFILE = "native-concurrency-explicit-typed-interpretation-lean/v1"
PRODUCERS = (expressions, native, *expressions.PRODUCERS)


def _closed(value, fields, reason):
    require(type(value) is dict and set(value) == set(fields), reason)


def _list(values):
    return "[" + ", ".join(values) + "]"


def _conj(values):
    return " ∧ ".join("(" + value + ")" for value in values) or "True"


def _rows(rows, key, expected):
    require(type(rows) is list and len(rows) <= 128, "bounded_concurrency_interpretation_records_required")
    result = {}
    for row in rows:
        require(type(row) is dict and type(row.get(key)) is str and row[key] not in result,
                "unique_concurrency_interpretation_records_required")
        result[row[key]] = row
    require(set(result) == set(expected), "complete_exact_concurrency_interpretation_records_required:" + key)
    return result


def _evidence(value):
    require(type(value) is str and value.strip() == value and 1 <= len(value) <= 512,
            "explicit_concurrency_interpretation_evidence_id_required")


def _surface_bindings(payload, interpretation, expr, aliases, typed_steps):
    """Check the small arithmetic surface grammar against typed native DAGs.

    Names such as buffer_space need an explicit alias. This is syntax replay,
    not a guess that an English sentence has some chosen mathematical meaning.
    """
    surface = {row["name"]: ("symbol", row["symbol_id"]) for row in expr.payload["symbols"]}
    require(len(surface) == len(expr.payload["symbols"]), "unique_concurrency_surface_symbol_names_required")
    nodes = {row["expression_id"]: row for row in expr.payload["expressions"]}
    def tree(key, depth=0):
        require(depth <= 32, "bounded_concurrency_surface_expression_required")
        row = nodes[key]; kind = row["kind"]
        if kind == "literal": return ("literal", row["type_ref"], row["attributes"]["value"])
        if kind == "symbol": return ("symbol", row["symbol_ids"][0])
        require(kind in ("unary", "binary"), "concurrency_surface_expression_operator_not_supported")
        return (row["operator"], *(tree(key, depth + 1) for key in row["operand_ids"]))
    extra = interpretation["surface_aliases"]
    require(type(extra) is dict and len(extra) <= 64, "bounded_concurrency_surface_aliases_required")
    for name, key in extra.items():
        require(type(name) is str and name.isidentifier() and name not in surface,
                "unique_named_concurrency_surface_alias_required")
        expr.require_root(key, "integer")
        surface[name] = tree(key)
    operators = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.And: "and", ast.Or: "or",
        ast.Eq: "eq", ast.NotEq: "ne", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
        ast.Not: "not", ast.USub: "neg", ast.UAdd: "pos"}
    def parse(text):
        require(type(text) is str and len(text) <= 4096, "bounded_concurrency_surface_text_required")
        try: value = ast.parse(text, mode="eval")
        except SyntaxError as error: raise ValueError("concurrency_surface_syntax_requires_explicit_typed_grammar") from error
        require(sum(1 for _ in ast.walk(value)) <= 256, "bounded_concurrency_surface_AST_required")
        def visit(node):
            if type(node) is ast.Name:
                if node.id in ("true", "false"): return ("literal", "boolean", node.id == "true")
                require(node.id in surface, "concurrency_surface_name_requires_explicit_alias:" + node.id)
                return surface[node.id]
            if type(node) is ast.Constant:
                require(type(node.value) in (bool, int), "concurrency_surface_literal_type_not_supported")
                return ("literal", "boolean" if type(node.value) is bool else "integer", node.value)
            if type(node) in (ast.BinOp, ast.UnaryOp, ast.BoolOp):
                require(type(node.op) in operators, "concurrency_surface_operator_not_supported")
                values = [node.left, node.right] if type(node) is ast.BinOp else [node.operand] if type(node) is ast.UnaryOp else node.values
                require(len(values) <= 2, "concurrency_surface_Boolean_arity_not_supported")
                return (operators[type(node.op)], *(visit(child) for child in values))
            if type(node) is ast.Compare:
                require(len(node.ops) == 1 and type(node.ops[0]) in operators, "concurrency_surface_comparison_not_supported")
                return (operators[type(node.ops[0])], visit(node.left), visit(node.comparators[0]))
            require(False, "concurrency_surface_construct_not_supported")
        return visit(value.body)
    symbol_vars = {row["name"]: next(var for var, sym in aliases.items() if sym == row["symbol_id"]) for row in expr.payload["symbols"]}
    for step in payload["steps"]:
        row = typed_steps[step["step_id"]]
        require(parse(step["guard_statement"]) == tree(row["guard_expression_id"]),
                "concurrency_guard_surface_and_typed_interpretation_differ")
        effect = step["effect_statement"]
        assignment = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*(.+)", effect)
        read = re.fullmatch(r"may read ([A-Za-z_][A-Za-z0-9_]*)", effect)
        if assignment:
            name, right = assignment.groups()
            require(name in symbol_vars and set(row["updates"]) == {symbol_vars[name]}, "concurrency_assignment_target_differs")
            require(parse(right) == tree(row["updates"][symbol_vars[name]]), "concurrency_assignment_surface_and_typed_update_differ")
        elif read:
            name = read.group(1)
            require(name in symbol_vars and step["read_variable_ids"] == [symbol_vars[name]] and not row["updates"],
                    "concurrency_read_surface_and_declared_frame_differ")
        else:
            require(effect == "skip" and not row["updates"], "concurrency_effect_surface_requires_explicit_typed_grammar")


def statement_bindings(payload):
    """Enumerate every semantic prose field requiring an explicit interpretation."""
    fields = {"steps": ("guard_statement", "effect_statement"),
        "atomic_regions": ("statement",), "interference": ("statement",),
        "fairness": ("statement",), "rely_guarantee": ("rely_statement", "guarantee_statement"),
        "linearizability_points": ("statement", "abstract_operation"), "schedules": ("statement",)}
    result = {}
    for collection, keys in fields.items():
        for index, row in enumerate(payload[collection]):
            for key in keys:
                result[f"/{collection}/{index}/{key}"] = row[key]
    if payload["metadata"]:
        require(set(payload["metadata"]) <= {"example"} and type(payload["metadata"].get("example")) is str,
                "concurrency_only_explicit_descriptive_example_metadata_supported")
        result["/metadata/example"] = payload["metadata"]["example"]
    return result


def emit_interpreted_concurrency(payload, interpretation):
    require(type(payload) is dict and len(expressions.canonical(payload).encode()) <= 262144,
            "bounded_concurrency_document_required")
    model = native.ConcurrencyIR.from_dict(payload)
    require(model.to_dict() == payload, "exact_native_concurrency_roundtrip_required")
    _closed(interpretation, {"schema", "native_document_sha256", "expression_program", "variable_symbols", "surface_aliases",
        "steps", "contracts", "linearizations", "channel_semantics", "statement_bindings", "evidence_id"},
        "closed_concurrency_interpretation_required")
    require(interpretation["schema"] == SCHEMA and interpretation["native_document_sha256"] == expressions.digest(payload),
            "concurrency_interpretation_native_document_digest_differs")
    require(len(expressions.canonical(interpretation).encode()) <= 524288,
            "bounded_concurrency_interpretation_required")
    _evidence(interpretation["evidence_id"])
    required_statements = statement_bindings(payload)
    bindings = _rows(interpretation["statement_bindings"], "path", required_statements)
    for path, row in bindings.items():
        _closed(row, {"path", "statement_sha256", "meaning", "evidence_id"}, "closed_concurrency_statement_binding_required")
        require(row["statement_sha256"] == expressions.digest(required_statements[path]),
                "concurrency_statement_binding_digest_differs")
        _evidence(row["evidence_id"])
        meaning = "descriptive" if path.startswith("/metadata/") else "typed_expression" if path.startswith(("/steps/", "/rely_guarantee/", "/linearizability_points/")) else "native_structure"
        require(row["meaning"] == meaning, "concurrency_statement_interpretation_kind_differs")
    for key in ("components", "steps", "atomic_regions", "interference", "fairness", "rely_guarantee", "channels", "sessions", "linearizability_points", "schedules"):
        require(len(payload[key]) <= 64 and all(not row["attributes"] for row in payload[key]),
                "bounded_concurrency_native_records_without_unknown_attributes_required")
    require(all(len(row["actions"]) <= 64 and all(not action["attributes"] for action in row["actions"]) for row in payload["sessions"]),
            "bounded_session_actions_without_unknown_attributes_required")

    expr = expressions.TypedExpressions(interpretation["expression_program"])
    variables = set(payload["shared_variable_ids"])
    for component in payload["components"]:
        require(not (variables & set(component["local_variable_ids"])), "concurrency_variable_scopes_overlap")
        variables.update(component["local_variable_ids"])
    aliases = interpretation["variable_symbols"]
    require(type(aliases) is dict and set(aliases) == variables and set(aliases.values()) == set(expr.symbol_types)
        and len(set(aliases.values())) == len(aliases), "concurrency_variable_symbol_bijection_required")
    reverse = {symbol: variable for variable, symbol in aliases.items()}
    def root(key, kind, *, old=False):
        return expr.require_root(key, kind, allow_old=old)
    def render(key, *, after="after", before="before"):
        return expr.render(key, current=after, initial=before)
    components = payload["components"]; steps = payload["steps"]
    csyms = {row["component_id"]: "Component.c" + str(i) for i, row in enumerate(components)}
    ssyms = {row["step_id"]: "Step.s" + str(i) for i, row in enumerate(steps)}
    typed_steps = _rows(interpretation["steps"], "step_id", ssyms)
    for step in steps:
        row = typed_steps[step["step_id"]]
        _closed(row, {"step_id", "guard_expression_id", "updates", "evidence_id"}, "closed_concurrency_step_interpretation_required")
        _evidence(row["evidence_id"])
        root(row["guard_expression_id"], "boolean")
        require(type(row["updates"]) is dict and set(row["updates"]) == set(step["write_variable_ids"]),
                "concurrency_typed_updates_must_match_exact_native_write_frame")
        reads = set(expr.reads[row["guard_expression_id"]])
        for variable, expression in row["updates"].items():
            require(variable in aliases, "concurrency_update_references_unknown_variable")
            root(expression, expr.symbol_types[aliases[variable]])
            reads.update(expr.reads[expression])
        require({reverse[key] for key in reads} <= set(step["read_variable_ids"]),
                "concurrency_expression_reads_exceed_native_frame")
        require(set(step["read_variable_ids"]) <= variables, "concurrency_read_frame_references_unknown_variable")
        visible = set(payload["shared_variable_ids"]) | (set(next(c["local_variable_ids"] for c in components if c["component_id"] == step["component_id"])) if step["owner"] == "component" else set())
        require(set(step["read_variable_ids"]) | set(step["write_variable_ids"]) <= visible,
                "concurrency_step_accesses_another_component_local_state")
    _surface_bindings(payload, interpretation, expr, aliases, typed_steps)

    used = set()
    for region in payload["atomic_regions"]:
        require(region["atomicity"] == "atomic" and len(region["step_ids"]) == 1,
                "interpreted_concurrency_only_single_step_atomic_regions_supported")
        step = next(s for s in steps if s["step_id"] == region["step_ids"][0])
        require(step["atomic_region_id"] == region["region_id"] and step["step_id"] not in used,
                "concurrency_exact_disjoint_atomic_membership_required")
        used.add(step["step_id"])
    require(all(not step["atomic_region_id"] or step["step_id"] in used for step in steps),
            "concurrency_atomic_membership_must_resolve_bidirectionally")
    contracts = _rows(interpretation["contracts"], "contract_id", [r["contract_id"] for r in payload["rely_guarantee"]])
    for native_row in payload["rely_guarantee"]:
        row = contracts[native_row["contract_id"]]
        _closed(row, {"contract_id", "rely_expression_id", "guarantee_expression_id", "evidence_id"}, "closed_typed_rely_guarantee_binding_required")
        _evidence(row["evidence_id"])
        for key in ("rely_expression_id", "guarantee_expression_id"):
            root(row[key], "boolean", old=True)
            require({reverse[symbol] for symbol in expr.reads[row[key]]} <= set(native_row["shared_variable_ids"]),
                    "concurrency_contract_reads_outside_declared_shared_state")
    linearizations = _rows(interpretation["linearizations"], "point_id", [r["point_id"] for r in payload["linearizability_points"]])
    for row in linearizations.values():
        _closed(row, {"point_id", "relation_expression_id", "evidence_id"}, "closed_linearization_interpretation_required")
        _evidence(row["evidence_id"]); root(row["relation_expression_id"], "boolean", old=True)
    channels = _rows(interpretation["channel_semantics"], "channel_id", [r["channel_id"] for r in payload["channels"]])
    for channel in payload["channels"]:
        row = channels[channel["channel_id"]]
        _closed(row, {"channel_id", "discipline", "evidence_id"}, "closed_channel_interpretation_required")
        _evidence(row["evidence_id"])
        require(row["discipline"] == "fifo" and channel["mode"] in ("buffered", "asynchronous"),
                "explicit_fifo_buffered_or_asynchronous_channel_interpretation_required")
        require(channel["capacity"] is None or channel["capacity"] <= 1048576, "bounded_channel_capacity_required")

    lines = ["set_option linter.unusedVariables false", expr.store_declaration(),
        "inductive Component where\n" + "\n".join("  | c" + str(i) for i in range(len(components))) + "\n  deriving DecidableEq, Repr",
        "inductive Actor where\n  | component (component : Component)\n  | environment\n  deriving DecidableEq, Repr",
        "inductive Step where\n" + "\n".join("  | s" + str(i) for i in range(len(steps))) + "\n  deriving DecidableEq, Repr"]
    def lookup(name, arg, ty, pairs):
        lines.append("def " + name + " : " + arg + " → " + ty + "\n" + "\n".join("  | " + key + " => " + value for key, value in pairs))
    lookup("componentId", "Component", "String", [(csyms[r["component_id"]], string(r["component_id"])) for r in components])
    lookup("stepId", "Step", "String", [(ssyms[r["step_id"]], string(r["step_id"])) for r in steps])
    lookup("stepActor", "Step", "Actor", [(ssyms[r["step_id"]], "Actor.environment" if r["owner"] == "environment" else "Actor.component " + csyms[r["component_id"]]) for r in steps])
    lookup("stepGuard", "Step", "Store → Bool", [(ssyms[r["step_id"]], "fun before => " + render(typed_steps[r["step_id"]]["guard_expression_id"], after="before")) for r in steps])
    update_rows = []
    for step in steps:
        changes = typed_steps[step["step_id"]]["updates"]
        body = "{ before with " + ", ".join(expr.fields[aliases[var]] + " := " + render(key, after="before") for var, key in sorted(changes.items())) + " }" if changes else "before"
        update_rows.append((ssyms[step["step_id"]], "fun before => " + body))
    lookup("stepUpdate", "Step", "Store → Store", update_rows)
    for kind in ("read", "write"):
        lookup(kind + "Frame", "Step", "List String", [(ssyms[r["step_id"]], _list(map(string, r[kind + "_variable_ids"]))) for r in steps])
    lines.extend([
        "def stepRelation (step : Step) (before after : Store) : Prop := stepGuard step before = true ∧ after = stepUpdate step before",
        "def componentStep (actor : Component) (step : Step) (before after : Store) : Prop := stepActor step = .component actor ∧ stepRelation step before after",
        "def environmentStep (step : Step) (before after : Store) : Prop := stepActor step = .environment ∧ stepRelation step before after",
        "theorem actors_disjoint (actor : Component) (step : Step) (before after : Store) :\n    ¬ (componentStep actor step before after ∧ environmentStep step before after) := by\n  intro h\n  have wrong : Actor.component actor = Actor.environment := h.1.1.symm.trans h.2.1\n  cases wrong",
        "structure Execution where\n  state : Nat → Store\n  event : Nat → Step",
        "def validExecution (trace : Execution) : Prop := ∀ t, stepRelation (trace.event t) (trace.state t) (trace.state (t + 1))",
        "def selectedEnabled (selected : List Step) (state : Store) : Prop := ∃ step ∈ selected, stepGuard step state = true",
        "def infinitelyOften (predicate : Nat → Prop) : Prop := ∀ start, ∃ t, start ≤ t ∧ predicate t",
        "def continuouslyEventually (predicate : Nat → Prop) : Prop := ∃ start, ∀ t, start ≤ t → predicate t",
        "def weakFair (selected : List Step) (trace : Execution) : Prop := continuouslyEventually (fun t => selectedEnabled selected (trace.state t)) → infinitelyOften (fun t => trace.event t ∈ selected)",
        "def strongFair (selected : List Step) (trace : Execution) : Prop := infinitelyOften (fun t => selectedEnabled selected (trace.state t)) → infinitelyOften (fun t => trace.event t ∈ selected)",
        "def unconditionalFair (selected : List Step) (trace : Execution) : Prop := infinitelyOften (fun t => trace.event t ∈ selected)",
    ])
    def selected(row):
        require(not (row["step_ids"] and row["component_ids"]), "concurrency_mixed_selectors_need_interpretation")
        if row["step_ids"]: return [ssyms[key] for key in row["step_ids"]]
        if row["component_ids"]: return [ssyms[s["step_id"]] for s in steps if s["component_id"] in row["component_ids"]]
        return list(ssyms.values())
    for i, row in enumerate(payload["fairness"]):
        require(len(row["step_ids"]) <= 1 and len(row["component_ids"]) <= 1, "concurrency_group_fairness_needs_additional_semantics")
        function = {"weak": "weakFair", "strong": "strongFair", "unconditional": "unconditionalFair"}[row["kind"]]
        lines.append(f"def fairness_{i} (trace : Execution) : Prop := {function} " + _list(selected(row)) + " trace")
    interference_names = {}
    for i, row in enumerate(payload["interference"]):
        shared = set(row["shared_variable_ids"])
        require(shared <= set(payload["shared_variable_ids"]), "concurrency_interference_unknown_shared_variables")
        actor = ".environment" if row["interferer_is_environment"] else ".component " + csyms[row["interferer_component_id"]]
        clauses = []
        for step in steps:
            reads, writes = set(step["read_variable_ids"]) & set(payload["shared_variable_ids"]), set(step["write_variable_ids"]) & set(payload["shared_variable_ids"])
            allowed = reads <= shared and writes <= shared and (not writes if row["kind"] == "read" else not reads if row["kind"] == "write" else not reads and not writes if row["kind"] == "internal" else True)
            clauses.append((ssyms[step["step_id"]], str(allowed).lower()))
        lookup(f"interferenceAccess_{i}", "Step", "Bool", clauses)
        lines.append(f"def interference_{i} (trace : Execution) : Prop := ∀ t, stepActor (trace.event t) = {actor} → interferenceAccess_{i} (trace.event t) = true")
        lines.append(f"def interferenceSubject_{i} : Component := " + csyms[row["subject_component_id"]])
        interference_names[row["interference_id"]] = f"interference_{i}"
    for i, native_row in enumerate(payload["rely_guarantee"]):
        row = contracts[native_row["contract_id"]]; actor = ".component " + csyms[native_row["component_id"]]
        for kind in ("rely", "guarantee"):
            lines.append(f"def {kind}Relation_{i} (before after : Store) : Prop := " + render(row[kind + "_expression_id"]) + " = true")
        assumption = _conj([interference_names[key] + " trace" for key in native_row["interference_ids"]] + [f"∀ t, stepActor (trace.event t) ≠ {actor} → relyRelation_{i} (trace.state t) (trace.state (t + 1))"])
        lines.append(f"def rely_{i} (trace : Execution) : Prop := " + assumption)
        lines.append(f"def guarantee_{i} (trace : Execution) : Prop := ∀ t, stepActor (trace.event t) = {actor} → guaranteeRelation_{i} (trace.state t) (trace.state (t + 1))")
        lines.append(f"def contract_{i} (trace : Execution) : Prop := rely_{i} trace → guarantee_{i} trace")
    for i, row in enumerate(payload["linearizability_points"]):
        lines.append(f"def linearizationRelation_{i} (before after : Store) : Prop := " + render(linearizations[row["point_id"]]["relation_expression_id"]) + " = true")
        lines.append(f"def linearizationObligation_{i} : Prop := ∀ before after, stepRelation " + ssyms[row["step_id"]] + f" before after → linearizationRelation_{i} before after")
        lines.append(f"def abstractOperation_{i} : String := " + string(row["abstract_operation"]))
    for i, row in enumerate(payload["schedules"]):
        require(row["max_steps"] <= 1048576, "bounded_concurrency_schedule_required")
        lines.append(f"def schedule_{i} (events : List Step) : Prop := events.length ≤ {row['max_steps']} ∧ ∀ step ∈ events, step ∈ " + _list(selected(row)))
    lines.extend(_channel_sessions(payload, csyms))
    lines.append("def declaredSpecification (trace : Execution) : Prop := " + _conj(["validExecution trace"] + [f"{prefix}_{i} trace" for key, prefix in (("fairness", "fairness"), ("interference", "interference"), ("rely_guarantee", "contract")) for i in range(len(payload[key]))]))
    lines.extend([expressions.evidence_strings("nativeConcurrencyEvidence", payload), expressions.evidence_strings("typedInterpretationEvidence", interpretation),
        "def sourceSemanticsVerified : Bool := false", "def channelStoreCouplingVerified : Bool := false",
        "def sessionExecutionLinked : Bool := false", "def globalLinearizabilityVerified : Bool := false"])
    return "\n\n".join(lines), {
        "profile": PROFILE, "validator": "exact_native_concurrency_and_explicit_ProgramIR_interpretation",
        "payload_sha256": expressions.digest(payload), "interpretation_sha256": expressions.digest(interpretation),
        "expression_program_sha256": expr.sha256, "variable_symbols": aliases, "store_fields": expr.fields,
        "component_symbols": csyms, "step_symbols": ssyms,
        "operators": ["typed_integer_Boolean_expressions", "simultaneous_store_updates", "native_read_write_frames", "actor_distinction", "dynamic_trace_fairness", "typed_rely_guarantee", "FIFO_channel_actions", "session_action_graph", "linearization_relation_obligations"],
        "assumptions": ["Every semantic statement is explicitly bound by caller evidence; none is inferred from source prose.",
            "The pure ProgramIR carrier provides expression typing only; its return-true scaffolding is never source execution or proof.",
            "Integer symbols denote mathematical Int and guards/effects use the supplied typed interpretation.",
            "Native declared reads are access bounds; updates exactly match the declared write frame.",
            "Channel FIFO discipline is explicit evidence; channel and session declarations have operational definitions but no invented links to component steps.",
            "Point relations are obligations for explicitly interpreted abstract operations, not history-based linearizability proofs.",
            "Original metadata, prose and native identity remain in bounded evidence strings; they are not asserted axioms."],
        "original_native_document_modified": False, "source_semantics_verified": False,
        "channel_store_coupling_verified": False, "session_execution_linked": False,
        "global_linearizability_verified": False, "interpretation_authenticity_verified": False,
        "obligations_discharged": False, "capability_floor_eligible": False, "model_checker_executed": False,
        "proof_authority": False, "admitted": False, "qualified": False,
    }


def _channel_sessions(payload, components):
    """Native channel/session declarations; deliberately no inferred step links."""
    lines = []
    for i, row in enumerate(payload["channels"]):
        endpoints = _list(components[key] for key in row["endpoint_component_ids"])
        ty = "Value " + string(row["payload_sort"])
        cap = "True" if row["capacity"] is None else f"before.length ≤ {row['capacity']} ∧ after.length ≤ {row['capacity']}"
        lines.append(f"def channelSend_{i} {{Value : String → Type}} (sender : Component) (value : {ty}) (before after : List ({ty})) : Prop := sender ∈ {endpoints} ∧ after = before ++ [value] ∧ {cap}")
        lines.append(f"def channelReceive_{i} {{Value : String → Type}} (receiver : Component) (value : {ty}) (before after : List ({ty})) : Prop := receiver ∈ {endpoints} ∧ before = value :: after ∧ {cap}")
        lines.append(f"def channelPayloadSort_{i} : String := " + string(row["payload_sort"]))
    if payload["sessions"]:
        lines.extend(["structure SessionAction where\n  identity : String\n  polarity : String\n  label : String\n  payloadSort : String\n  next : List String\n  deriving DecidableEq, BEq",
            "def dualPolarity : String → String\n  | \"send\" => \"receive\"\n  | \"receive\" => \"send\"\n  | other => other",
            "def sessionDual (left right : List SessionAction) : Bool := left.all (fun action => right.any (fun other => other.identity == action.identity && other.polarity == dualPolarity action.polarity && other.label == action.label && other.payloadSort == action.payloadSort && other.next == action.next)) && left.length == right.length"])
    sessions = {row["protocol_id"]: i for i, row in enumerate(payload["sessions"])}
    for i, row in enumerate(payload["sessions"]):
        values = ["⟨" + ", ".join([*(string(action[key]) for key in ("action_id", "polarity", "label", "payload_sort")), _list(map(string, action["continuation_action_ids"]))]) + "⟩" for action in row["actions"]]
        lines.append(f"def sessionActions_{i} : List SessionAction := " + _list(values))
        lines.append(f"def sessionEntry_{i} : String := " + string(row["entry_action_id"]))
        lines.append(f"def sessionStep_{i} (current polarity payloadSort : String) (next : Option String) : Prop := ∃ action, action ∈ sessionActions_{i} ∧ action.identity = current ∧ action.polarity = polarity ∧ action.payloadSort = payloadSort ∧ (match next with | none => action.polarity = \"end\" | some following => following ∈ action.next)")
    for i, row in enumerate(payload["sessions"]):
        if row["dual_protocol_id"]:
            lines.append(f"def sessionDuality_{i} : Bool := sessionDual sessionActions_{i} sessionActions_{sessions[row['dual_protocol_id']]}")
    return lines


__all__ = ["SCHEMA", "PROFILE", "PRODUCERS", "statement_bindings", "emit_interpreted_concurrency"]
