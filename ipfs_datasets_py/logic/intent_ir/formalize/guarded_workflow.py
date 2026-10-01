"""Exhaustive finite guard/retry models from explicit, source-bound premises.

This interpreter evaluates a deliberately closed data language, never Python,
source code, or natural-language predicates. Supplied models are assumptions;
the original IntentIR and its norms retain their independent meaning.
"""
from __future__ import annotations

from collections import deque
from itertools import product
import json

from .workflow_state import WorkflowScopeError, _record, _reject

SEMANTICS = "finite_guarded_state_flow"
MAX_ACTIONS, MAX_EDGES = 16, 64
MAX_VARIABLES, MAX_DOMAIN_VALUES, MAX_INITIAL_VALUATIONS = 6, 8, 32
MAX_CONFIGURATIONS, MAX_TRANSITIONS = 128, 120
ASSUMPTIONS = (
    "Guarded workflow premises are caller-supplied source-bound assumptions, not verified source semantics.",
    "Every initial Cartesian valuation and reachable abstract configuration is explored or the entire projection is rejected.",
    "Preconditions are evaluated before an atomic action update; outgoing edge guards are evaluated after that update.",
    "Each enabled action chooses one supplied outcome nondeterministically; its constant assignments are simultaneous and omitted variables retain their values.",
    "Enabled outgoing edges are exclusive nondeterministic choices; no priority or fairness is inferred.",
    "Retry counters count traversals of individual RETRY edges globally; exhaustion disables that edge and does not imply success.",
    "Nonterminal states without enabled actions or edges remain deadlocks, including failed preconditions and exhausted retries without an exit.",
    "A synthetic initial choice and separate action/routing phases count toward the abstract step budget.",
    "The pc value encodes complete abstract data, phase, action label and retry counts; code effects and normative compliance are not verified.",
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _list(value, minimum, maximum, label):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError("bounded " + label + " required")
    return value


def _reference(value, refs, label):
    if type(value) is not str or value not in refs:
        raise ValueError(label + " requires a known source evidence reference")


def _value(value, variable):
    return any(type(value) is type(v) and value == v for v in variable["domain"])


def _expression(expression, variables, depth=0):
    if depth > 8 or type(expression) is not dict:
        raise ValueError("bounded closed predicate expression required")
    op = expression.get("op")
    if type(op) is not str:
        raise ValueError("predicate expression operator must be a string")
    if op == "literal":
        _record(expression, {"op", "value"}, "literal expression")
        if type(expression["value"]) is not bool:
            raise ValueError("literal expression requires a Boolean")
    elif op in {"eq", "ne"}:
        _record(expression, {"op", "variable_id", "value"}, "comparison expression")
        variable = expression["variable_id"]
        if type(variable) is not str or variable not in variables or not _value(expression["value"], variables[variable]):
            raise ValueError("comparison requires a known variable and exactly typed domain value")
    elif op == "not":
        _record(expression, {"op", "arg"}, "negation expression")
        _expression(expression["arg"], variables, depth + 1)
    elif op in {"and", "or"}:
        _record(expression, {"op", "args"}, "Boolean expression")
        for arg in _list(expression["args"], 2, 8, "Boolean arguments"):
            _expression(arg, variables, depth + 1)
    else:
        raise ValueError("unsupported predicate expression operator")


def _evaluate(expression, values):
    op = expression["op"]
    if op == "literal":
        return expression["value"]
    if op in {"eq", "ne"}:
        # The validator already rejects Python's bool/int equality coercion.
        equal = values[expression["variable_id"]] == expression["value"]
        return equal if op == "eq" else not equal
    if op == "not":
        return not _evaluate(expression["arg"], values)
    args = (_evaluate(arg, values) for arg in expression["args"])
    return all(args) if op == "and" else any(args)


def _data_schema(rows, refs):
    from ...software_verification.state import StateSchema, StateVariable, StateTypeKind, Boundedness, FiniteDomainBound
    variables, native = {}, []
    for row in _list(rows, 1, MAX_VARIABLES, "state variables"):
        _record(row, {"variable_id", "kind", "domain", "initial_values", "evidence_ref"}, "variable")
        variable_id, kind = row["variable_id"], row["kind"]
        if type(variable_id) is not str or variable_id in variables:
            raise ValueError("unique state variable IDs required")
        domain = _list(row["domain"], 1, MAX_DOMAIN_VALUES, "variable domain")
        if len({_json(v) for v in domain}) != len(domain):
            raise ValueError("unique variable domain values required")
        if kind == "boolean" and all(type(v) is bool for v in domain):
            bound = FiniteDomainBound("bound:" + variable_id, cardinality=2)
        elif kind == "integer" and all(type(v) is int and abs(v) <= 1_000_000 for v in domain):
            bound = FiniteDomainBound("bound:" + variable_id, lower=min(domain), upper=max(domain))
        elif kind == "enumeration" and all(type(v) is str for v in domain):
            bound = FiniteDomainBound("bound:" + variable_id, members=tuple(sorted(domain)))
        else:
            raise ValueError("variable domain must match finite Boolean, integer or enumeration kind")
        _reference(row["evidence_ref"], refs, "variable")
        initial = _list(row["initial_values"], 1, MAX_DOMAIN_VALUES, "initial values")
        if len({_json(v) for v in initial}) != len(initial) or not all(_value(v, row) for v in initial):
            raise ValueError("initial values must be a unique, exactly typed domain subset")
        native.append(StateVariable(variable_id, variable_id, StateTypeKind(kind), Boundedness.FINITE,
            domain_bound=bound, source_ref_ids=(row["evidence_ref"],),
            attributes={"explicit_domain": sorted(domain, key=_json)}))
        variables[variable_id] = row
    schema = StateSchema(variables=tuple(native), metadata={"abstraction": SEMANTICS, "premises_verified": False})
    schema.validate()
    return variables, schema


def _premises(document, premise):
    from .projection_contracts import source_ir_sha256
    from ..schema import ControlEdgeKind as K, StatementKind as S, IntentModality as M
    _record(premise, {"semantics", "source_ir_sha256", "evidence_ref", "variables", "predicate_bindings",
                      "action_updates", "retry_bounds"}, "guarded workflow premise")
    if premise["semantics"] != SEMANTICS or premise["source_ir_sha256"] != source_ir_sha256(document):
        raise ValueError("guarded workflow premise must bind the exact IntentIR and supported semantics")
    refs = {s.ref_id for s in document.sources}
    _reference(premise["evidence_ref"], refs, "guarded workflow")
    variables, schema = _data_schema(premise["variables"], refs)
    actions, edges = {a.action_id: a for a in document.actions}, {e.edge_id: e for e in document.control_edges}
    statements = {s.statement_id: s for s in document.statements}
    if not 1 <= len(actions) <= MAX_ACTIONS or len(edges) > MAX_EDGES:
        _reject(document.document_id, "guarded_workflow_exceeds_action_or_edge_bound")
    if len(document.entry_action_ids) != 1 or len(document.terminal_action_ids) != 1:
        _reject(document.document_id, "guarded_workflow_requires_one_entry_and_one_terminal")
    entry, terminal = document.entry_action_ids[0], document.terminal_action_ids[0]
    outgoing = {action: [] for action in actions}
    degree = {action: 0 for action in actions}
    required = set()
    for action in actions.values():
        required.update(action.precondition_ids)
        for sid in action.precondition_ids:
            if statements[sid].kind is not S.PRECONDITION:
                _reject(sid, "action_precondition_binding_requires_precondition_statement")
    for edge in sorted(edges.values(), key=lambda e: e.edge_id):
        if edge.kind not in {K.NEXT, K.CONDITIONAL, K.RETRY}:
            _reject(edge.edge_id, "guarded_workflow_supports_only_NEXT_CONDITIONAL_and_RETRY")
        if edge.kind is K.CONDITIONAL and not edge.guard_statement_id:
            _reject(edge.edge_id, "conditional_edge_requires_explicit_guard_statement")
        if edge.source_action_id == terminal:
            _reject(edge.edge_id, "guarded_workflow_terminal_action_must_have_no_outgoing_edges")
        if edge.guard_statement_id:
            required.add(edge.guard_statement_id)
            if statements[edge.guard_statement_id].kind not in {S.GUARD, S.PRECONDITION}:
                _reject(edge.guard_statement_id, "edge_guard_binding_requires_guard_or_precondition_statement")
        outgoing[edge.source_action_id].append(edge)
        if edge.kind is not K.RETRY:
            degree[edge.target_action_id] += 1
    queue, visited = deque(sorted(a for a, d in degree.items() if d == 0)), []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for edge in outgoing[node]:
            if edge.kind is not K.RETRY:
                degree[edge.target_action_id] -= 1
                if degree[edge.target_action_id] == 0:
                    queue.append(edge.target_action_id)
    if len(visited) != len(actions):
        _reject(document.document_id, "all_control_cycles_require_explicit_bounded_RETRY_edges")
    reachable, todo = set(), [entry]
    while todo:
        node = todo.pop()
        if node not in reachable:
            reachable.add(node)
            todo.extend(e.target_action_id for e in outgoing[node])
    if reachable != set(actions):
        _reject(document.document_id, "guarded_workflow_contains_structurally_unreachable_actions")
    bindings = {}
    for row in _list(premise["predicate_bindings"], 0, 128, "predicate bindings"):
        _record(row, {"statement_id", "expression", "evidence_ref"}, "predicate binding")
        sid = row["statement_id"]
        if type(sid) is not str or sid not in required or sid in bindings:
            raise ValueError("unique bindings for exactly the used guards and preconditions required")
        if statements[sid].modality is not M.ASSERTED:
            _reject(sid, "normative_statement_cannot_be_used_as_state_truth")
        _reference(row["evidence_ref"], statements[sid].source_ref_ids, "predicate binding")
        _expression(row["expression"], variables)
        bindings[sid] = row["expression"]
    if set(bindings) != required:
        raise ValueError("every guard and precondition requires an explicit predicate binding")
    updates = {}
    for row in _list(premise["action_updates"], 1, MAX_ACTIONS, "action updates"):
        _record(row, {"action_id", "outcomes", "evidence_ref"}, "action update")
        aid = row["action_id"]
        if type(aid) is not str or aid not in actions or aid in updates:
            raise ValueError("exactly one explicit update premise per action required")
        _reference(row["evidence_ref"], actions[aid].source_ref_ids, "action update")
        outcomes = _list(row["outcomes"], 1, 8, "action outcomes")
        seen = set()
        for outcome in outcomes:
            _record(outcome, {"values", "evidence_ref"}, "action outcome")
            _reference(outcome["evidence_ref"], actions[aid].source_ref_ids, "action outcome")
            values = outcome["values"]
            if type(values) is not dict or set(values) - set(variables):
                raise ValueError("action outcome requires known state variables")
            if not all(_value(value, variables[key]) for key, value in values.items()):
                raise ValueError("action outcome values must exactly match declared finite domains")
            if _json(values) in seen:
                raise ValueError("duplicate abstract action outcomes")
            seen.add(_json(values))
        updates[aid] = tuple(sorted((o["values"] for o in outcomes), key=_json))
    if set(updates) != set(actions):
        raise ValueError("every action requires an explicit update premise, including identity updates")
    retries = {}
    for row in _list(premise["retry_bounds"], 0, MAX_EDGES, "retry bounds"):
        _record(row, {"edge_id", "max_traversals", "evidence_ref"}, "retry bound")
        eid, limit = row["edge_id"], row["max_traversals"]
        if type(eid) is not str or eid not in edges or edges[eid].kind is not K.RETRY or eid in retries:
            raise ValueError("unique bounds for exactly the RETRY edges required")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("retry max_traversals must be an integer between one and eight")
        _reference(row["evidence_ref"], edges[eid].source_ref_ids, "retry bound")
        retries[eid] = limit
    if set(retries) != {e.edge_id for e in edges.values() if e.kind is K.RETRY}:
        raise ValueError("every RETRY edge requires an explicit bound")
    return variables, schema, actions, outgoing, bindings, updates, retries, entry, terminal


def guarded_workflow_graph(document, premise, max_steps):
    """Enumerate all supplied initial valuations and every finite successor."""
    from ..schema import ControlEdgeKind as K
    from ...software_verification.state import StateValuation
    variables, schema, actions, outgoing, bindings, updates, retries, entry, terminal = _premises(document, premise)
    variable_ids, retry_ids = tuple(sorted(variables)), tuple(sorted(retries))
    initial_values = [sorted(variables[v]["initial_values"], key=_json) for v in variable_ids]
    count = 1
    for values in initial_values:
        count *= len(values)
    if count > MAX_INITIAL_VALUATIONS:
        _reject(document.document_id, "guarded_workflow_initial_valuation_bound_exceeded")
    # Tuples have a fixed variable type at each position, so bool/int identity
    # cannot collide within a configuration.
    initial = ("initial", "", (), ())
    configurations, names, todo = [initial], {initial: "configuration_0"}, deque([initial])
    transitions, deadlocks = [], []

    def add(before, after, action_id=None, edge_ids=(), kind="route"):
        if after not in names:
            if len(configurations) >= MAX_CONFIGURATIONS:
                _reject(document.document_id, "guarded_workflow_configuration_bound_exceeded")
            names[after] = f"configuration_{len(configurations)}"
            configurations.append(after)
            todo.append(after)
        transitions.append({"from_position": names[before], "to_position": names[after],
            "intent_action_id": action_id, "intent_edge_ids": list(edge_ids), "transition_kind": kind})
        if len(transitions) > MAX_TRANSITIONS:
            _reject(document.document_id, "guarded_workflow_transition_bound_exceeded")

    while todo:
        configuration = todo.popleft()
        phase, action_id, assignment, counts = configuration
        if phase == "initial":
            for assignment in product(*initial_values):
                add(configuration, ("ready", entry, assignment, (0,) * len(retry_ids)), kind="initialize")
            continue
        values = dict(zip(variable_ids, assignment))
        StateValuation(names[configuration], values).validate_against(schema)
        if phase == "done":
            add(configuration, configuration, kind="terminal_stutter")
        elif phase == "ready":
            failed = [sid for sid in sorted(actions[action_id].precondition_ids) if not _evaluate(bindings[sid], values)]
            if failed:
                deadlocks.append({"position": names[configuration], "reason": "precondition_false",
                                  "statement_ids": failed, "exhausted_retry_edge_ids": []})
                continue
            for update in updates[action_id]:
                changed = {**values, **update}
                after = ("done" if action_id == terminal else "routing", action_id,
                         tuple(changed[v] for v in variable_ids), counts)
                add(configuration, after, action_id, kind="action")
        else:
            enabled, exhausted = [], []
            retry_counts = dict(zip(retry_ids, counts))
            for edge in outgoing[action_id]:
                if edge.guard_statement_id and not _evaluate(bindings[edge.guard_statement_id], values):
                    continue
                if edge.kind is K.RETRY and retry_counts[edge.edge_id] >= retries[edge.edge_id]:
                    exhausted.append(edge.edge_id)
                    continue
                enabled.append(edge)
            if not enabled:
                deadlocks.append({"position": names[configuration], "reason": "no_enabled_outgoing_edge",
                                  "statement_ids": [], "exhausted_retry_edge_ids": sorted(exhausted)})
            for edge in enabled:
                after_counts = dict(retry_counts)
                if edge.kind is K.RETRY:
                    after_counts[edge.edge_id] += 1
                add(configuration, ("ready", edge.target_action_id, assignment,
                    tuple(after_counts[e] for e in retry_ids)), edge_ids=(edge.edge_id,))

    # The nonretry graph is acyclic and every retry increases a bounded counter.
    # Compute the exact longest path, including initial and routing phases, and
    # reject rather than truncating paths at the requested compiler step budget.
    successors, degree = {v: [] for v in names.values()}, {v: 0 for v in names.values()}
    for row in transitions:
        if row["transition_kind"] != "terminal_stutter":
            successors[row["from_position"]].append(row["to_position"])
            degree[row["to_position"]] += 1
    queue, distance, visited = deque(sorted(v for v, d in degree.items() if d == 0)), {names[initial]: 0}, 0
    while queue:
        node = queue.popleft()
        visited += 1
        for target in successors[node]:
            distance[target] = max(distance.get(target, 0), distance[node] + 1)
            degree[target] -= 1
            if degree[target] == 0:
                queue.append(target)
    if visited != len(configurations):
        _reject(document.document_id, "guarded_workflow_has_unbounded_configuration_cycle")
    longest = max(distance.values())
    if longest > max_steps:
        _reject(document.document_id, "step_budget_does_not_cover_the_complete_guarded_workflow")
    rows = [{"position": names[c], "phase": c[0], "action_id": c[1] or None,
             "values": dict(zip(variable_ids, c[2])), "retry_counts": dict(zip(retry_ids, c[3])),
             "terminal": c[0] == "done"} for c in configurations]
    return {"configurations": rows, "transitions": transitions, "initial_position": names[initial],
        "initial_valuation_count": count, "max_abstract_steps": longest, "deadlocks": deadlocks,
        "deadlock_free": not deadlocks, "data_schema": schema.to_dict(), "bounds": {
            "actions": MAX_ACTIONS, "edges": MAX_EDGES, "variables": MAX_VARIABLES,
            "domain_values": MAX_DOMAIN_VALUES, "initial_valuations": MAX_INITIAL_VALUATIONS,
            "configurations": MAX_CONFIGURATIONS, "transitions": MAX_TRANSITIONS},
        "premises_verified": False, "shared_memory_modeled": False, "fairness_assumed": False}


def guarded_workflow_state(document, graph, options):
    """Lower the fully explored graph to exact pc guards, never opaque guards."""
    from .projection_contracts import source_ir_sha256
    from ...software_verification.state import StateSchema, StateVariable, StateTypeKind, Boundedness, FiniteDomainBound, StatePredicate, PredicateRole
    from ...software_verification.transitions import StateTransitionIR, Action, ActionFrame, TransitionRelation, TransitionKind
    refs = tuple(sorted(s.ref_id for s in document.sources))
    schema = StateSchema(variables=(StateVariable("var:pc", "pc", StateTypeKind.ENUMERATION, Boundedness.FINITE,
        domain_bound=FiniteDomainBound("bound:pc", members=tuple(c["position"] for c in graph["configurations"])),
        description="Enumerated complete abstract data/phase/retry configuration.", source_ref_ids=refs),),
        metadata={"abstraction": SEMANTICS})
    predicates = [StatePredicate("pred:init", PredicateRole.INITIAL, "Initial data selection configuration.",
        expression={"var:pc": graph["initial_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs)]
    actions, origins = [], []
    for index, row in enumerate(graph["transitions"]):
        guard, effect = f"pred:guard:{index}", f"pred:next:{index}"
        predicates.extend((StatePredicate(guard, PredicateRole.GUARD, "Exact abstract configuration.",
            expression={"var:pc": row["from_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs),
            StatePredicate(effect, PredicateRole.NEXT, "Exact exhaustive guarded successor.",
                expression={"var:pc": row["to_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs)))
        aid = f"action:guarded:{index}"
        actions.append(Action(aid, f"AdvanceGuarded{index}", ActionFrame(reads=("var:pc",), writes=("var:pc",)),
            guard_predicate_id=guard, next_predicate_id=effect, source_ref_ids=refs,
            enables_stutter=row["transition_kind"] == "terminal_stutter", attributes={**row, "abstract_event_only": True}))
        origins.append({"state_action_id": aid, **row})
    relation = TransitionRelation("transition:next", TransitionKind.ACTION,
        "Exact finite guarded transitions; deadlock configurations have no successor.",
        action_ids=tuple(a.action_id for a in actions), allows_stutter=any(c["terminal"] for c in graph["configurations"]))
    return StateTransitionIR(schema=schema, predicates=tuple(predicates), actions=tuple(actions), transitions=(relation,),
        metadata={"abstraction": SEMANTICS, "intent_document_id": document.document_id,
            "intent_ir_sha256": source_ir_sha256(document), "max_steps": options["max_steps"],
            "guarded_graph": graph, "code_effects_modeled": False, "normative_compliance_modeled": False}), origins
