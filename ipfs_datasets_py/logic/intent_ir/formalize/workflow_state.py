"""Explicit finite token-flow premises for abstract Intent workflow models.

No edge label supplies scheduling or guard truth by itself. The caller must
select exclusive choices and all-branch fork/join barriers against the exact
source IR. Configurations describe declared action labels, never code effects.
"""
from __future__ import annotations

from collections import deque

SEMANTICS = "finite_single_use_token_flow"
MAX_ACTIONS = 16
MAX_EDGES = 64
MAX_CONFIGURATIONS = 128
MAX_TRANSITIONS = 120
ASSUMPTIONS = (
    "Token-flow premises are caller-supplied source-bound modeling assumptions, not verified source semantics.",
    "An enabled action label completes atomically once; the model does not execute code or model its effects.",
    "Exclusive choices are nondeterministic; no condition truth or outcome is inferred.",
    "A declared fork activates every branch; its join waits for all declared branch tails.",
    "Concurrent branch labels are explored by interleaving without fairness or shared-memory semantics.",
    "The pc value names a complete active/completed token configuration, not an implementation program counter.",
)


class WorkflowScopeError(ValueError):
    def __init__(self, node_id, reason):
        self.node_id, self.reason = node_id, reason
        super().__init__(reason)


def _reject(node, reason):
    raise WorkflowScopeError(node, reason)


def _record(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("closed " + label + " required")


def _ids(value, minimum, maximum, label):
    if (type(value) is not list or not minimum <= len(value) <= maximum
            or any(type(v) is not str or not v for v in value) or len(set(value)) != len(value)):
        raise ValueError("bounded unique " + label + " required")
    return set(value)


def _premises(document, premise):
    from .projection_contracts import source_ir_sha256
    _record(premise, {"semantics", "source_ir_sha256", "evidence_ref", "choices", "fork_joins"},
            "workflow premise")
    if premise["semantics"] != SEMANTICS or premise["source_ir_sha256"] != source_ir_sha256(document):
        raise ValueError("workflow premise must bind the exact IntentIR and supported semantics")
    refs = {s.ref_id for s in document.sources}
    if type(premise["evidence_ref"]) is not str or premise["evidence_ref"] not in refs:
        raise ValueError("workflow premise requires a known source evidence reference")
    for name in ("choices", "fork_joins"):
        if type(premise[name]) is not list or len(premise[name]) > 16:
            raise ValueError("bounded workflow premise groups required")
    return refs


def _structure(document, premise):
    from ..schema import ControlEdgeKind as K
    refs = _premises(document, premise)
    actions = {a.action_id: a for a in document.actions}
    edges = {e.edge_id: e for e in document.control_edges}
    if not 1 <= len(actions) <= MAX_ACTIONS or len(edges) > MAX_EDGES:
        _reject(document.document_id, "workflow_exceeds_finite_action_or_edge_bound")
    if len(document.entry_action_ids) != 1 or len(document.terminal_action_ids) != 1:
        _reject(document.document_id, "token_workflow_requires_one_entry_and_one_terminal")
    outgoing, incoming = {a: [] for a in actions}, {a: [] for a in actions}
    for a in document.actions:
        if a.precondition_ids:
            _reject(a.action_id, "token_workflow_preconditions_require_explicit_state_binding")
    for e in sorted(edges.values(), key=lambda e: e.edge_id):
        if e.guard_statement_id or e.kind not in {K.NEXT, K.PARALLEL, K.JOIN}:
            _reject(e.edge_id, "token_workflow_guards_outcomes_and_retries_have_no_state_binding")
        outgoing[e.source_action_id].append(e)
        incoming[e.target_action_id].append(e)
    entry, terminal = document.entry_action_ids[0], document.terminal_action_ids[0]
    if incoming[entry] or outgoing[terminal]:
        _reject(document.document_id, "token_workflow_entry_and_terminal_boundaries_are_inconsistent")
    degree = {a: len(v) for a, v in incoming.items()}
    queue = deque(sorted(a for a, d in degree.items() if d == 0))
    visited = []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for e in outgoing[node]:
            degree[e.target_action_id] -= 1
            if degree[e.target_action_id] == 0:
                queue.append(e.target_action_id)
    if len(visited) != len(actions):
        _reject(document.document_id, "single_use_token_workflow_requires_acyclic_control_flow")
    def reachable(start, graph, field):
        seen, todo = set(), [start]
        while todo:
            node = todo.pop()
            if node not in seen:
                seen.add(node)
                todo.extend(getattr(e, field) for e in graph[node])
        return seen
    if (reachable(entry, outgoing, "target_action_id") != set(actions)
            or reachable(terminal, incoming, "source_action_id") != set(actions)):
        _reject(document.document_id, "token_workflow_requires_all_nodes_between_entry_and_terminal")

    choices, forks, joins, covered_parallel, covered_join = {}, {}, {}, set(), set()
    for group in premise["choices"]:
        _record(group, {"source_action_id", "edge_ids", "semantics", "evidence_ref"}, "choice group")
        source = group["source_action_id"]
        ids = _ids(group["edge_ids"], 2, 8, "choice edge IDs")
        if (type(source) is not str or source not in actions or source in choices
                or group["semantics"] != "exclusive_nondeterministic"
                or type(group["evidence_ref"]) is not str or group["evidence_ref"] not in refs
                or ids != {e.edge_id for e in outgoing[source]}
                or any(e.kind is not K.NEXT or group["evidence_ref"] not in e.source_ref_ids for e in outgoing[source])):
            raise ValueError("choice premise must exactly bind source NEXT edges and source evidence")
        if len({e.target_action_id for e in outgoing[source]}) != len(ids):
            _reject(source, "exclusive_choice_has_duplicate_targets")
        choices[source] = ids

    all_interiors = set()
    for group in premise["fork_joins"]:
        _record(group, {"fork_action_id", "join_action_id", "parallel_edge_ids", "join_edge_ids",
                        "semantics", "evidence_ref"}, "fork/join group")
        fork, join = group["fork_action_id"], group["join_action_id"]
        parallel_ids = _ids(group["parallel_edge_ids"], 2, 4, "parallel edge IDs")
        join_ids = _ids(group["join_edge_ids"], 2, 4, "join edge IDs")
        if (type(fork) is not str or type(join) is not str or fork not in actions or join not in actions
                or fork in forks or join in joins or fork == join
                or group["semantics"] != "all_branches_then_join"
                or type(group["evidence_ref"]) is not str or group["evidence_ref"] not in refs
                or parallel_ids != {e.edge_id for e in outgoing[fork]}
                or join_ids != {e.edge_id for e in incoming[join]}
                or len(parallel_ids) != len(join_ids)):
            raise ValueError("fork/join premise must exactly bind its fork and barrier edges")
        bound_edges = [edges[i] for i in parallel_ids | join_ids]
        if (any(edges[i].kind is not K.PARALLEL for i in parallel_ids)
                or any(edges[i].kind is not K.JOIN for i in join_ids)
                or any(group["evidence_ref"] not in e.source_ref_ids for e in bound_edges)):
            raise ValueError("fork/join premise kinds or source evidence do not match")
        interiors, tails = set(), set()
        for first in sorted(parallel_ids):
            edge = edges[first]
            node = edge.target_action_id
            while True:
                if (node in interiors or node in all_interiors or node in {fork, join}
                        or len(incoming[node]) != 1 or incoming[node][0].edge_id != edge.edge_id
                        or len(outgoing[node]) != 1):
                    _reject(node, "fork_branches_require_disjoint_linear_interiors_without_nested_control")
                interiors.add(node)
                edge = outgoing[node][0]
                if edge.kind is K.JOIN:
                    if edge.edge_id not in join_ids or edge.target_action_id != join:
                        _reject(edge.edge_id, "fork_branch_joins_a_different_barrier")
                    tails.add(node)
                    break
                if edge.kind is not K.NEXT:
                    _reject(edge.edge_id, "nested_parallel_control_requires_separate_explicit_semantics")
                node = edge.target_action_id
        if tails != {edges[i].source_action_id for i in join_ids}:
            raise ValueError("fork/join tail coverage differs")
        all_interiors.update(interiors)
        forks[fork] = tuple(sorted(edges[i].target_action_id for i in parallel_ids))
        joins[join] = frozenset(tails)
        covered_parallel.update(parallel_ids)
        covered_join.update(join_ids)
    for e in edges.values():
        if ((e.kind is K.PARALLEL and e.edge_id not in covered_parallel)
                or (e.kind is K.JOIN and e.edge_id not in covered_join)):
            _reject(e.edge_id, "parallel_or_join_edge_requires_an_exact_structured_group")
    for a, out in outgoing.items():
        if len(out) > 1 and a not in choices and a not in forks:
            _reject(a, "branching_requires_an_explicit_exclusive_choice_or_fork_premise")
    return actions, outgoing, forks, joins, entry, terminal


def workflow_graph(document, premise, max_steps):
    """Enumerate every reachable configuration or reject the entire projection."""
    from ..schema import ControlEdgeKind as K
    actions, outgoing, forks, joins, entry, terminal = _structure(document, premise)
    # A configuration retains completed labels so a barrier cannot fire early.
    initial = ((entry,), ())
    configurations, names, todo, transitions = [initial], {initial: "configuration_0"}, deque([initial]), []
    while todo:
        configuration = todo.popleft()
        active, completed = map(set, configuration)
        if not active:
            if terminal not in completed:
                _reject(document.document_id, "token_workflow_reaches_a_nonterminal_deadlock")
            transitions.append({"from_position": names[configuration], "to_position": names[configuration],
                                "intent_action_id": None, "intent_edge_ids": []})
            if len(transitions) > MAX_TRANSITIONS:
                _reject(document.document_id, "token_workflow_transition_bound_exceeded")
            continue
        for action in sorted(active):
            done = completed | {action}
            if len(done) > max_steps:
                _reject(document.document_id, "step_budget_does_not_cover_the_declared_workflow")
            if action in completed:
                _reject(action, "single_use_action_would_execute_twice")
            out = outgoing[action]
            if action in forks:
                options = [(list(forks[action]), [e.edge_id for e in out])]
            elif out and out[0].kind is K.JOIN:
                join = out[0].target_action_id
                options = [([join] if joins[join] <= done else [], [out[0].edge_id])]
            elif out:
                options = [([e.target_action_id], [e.edge_id]) for e in out]
            else:
                options = [([], [])]
            for activated, edge_ids in options:
                if set(activated) & ((active - {action}) | done):
                    _reject(action, "token_workflow_would_duplicate_or_reactivate_a_label")
                remaining = (active - {action}) | set(activated)
                after = (tuple(sorted(remaining)), tuple(sorted(done)))
                if after not in names:
                    if len(configurations) >= MAX_CONFIGURATIONS:
                        _reject(document.document_id, "token_workflow_configuration_bound_exceeded")
                    names[after] = f"configuration_{len(configurations)}"
                    configurations.append(after)
                    todo.append(after)
                transitions.append({"from_position": names[configuration], "to_position": names[after],
                                    "intent_action_id": action, "intent_edge_ids": sorted(edge_ids)})
                if len(transitions) > MAX_TRANSITIONS:
                    _reject(document.document_id, "token_workflow_transition_bound_exceeded")
    return {"configurations": [{"position": names[c], "active_action_ids": list(c[0]),
                                "completed_action_ids": list(c[1]), "terminal": not c[0]} for c in configurations],
            "transitions": transitions, "initial_position": names[initial],
            "max_abstract_steps": max(len(c[1]) for c in configurations),
            "bounds": {"actions": MAX_ACTIONS, "edges": MAX_EDGES,
                       "configurations": MAX_CONFIGURATIONS, "transitions": MAX_TRANSITIONS},
            "premises_verified": False, "shared_memory_modeled": False, "fairness_assumed": False}


def workflow_state(document, graph, options):
    from .projection_contracts import source_ir_sha256
    from ...software_verification.state import (StateSchema, StateVariable, StateTypeKind,
        Boundedness, FiniteDomainBound, StatePredicate, PredicateRole)
    from ...software_verification.transitions import (StateTransitionIR, Action, ActionFrame,
                                                      TransitionRelation, TransitionKind)
    refs = tuple(sorted(s.ref_id for s in document.sources))
    schema = StateSchema(variables=(StateVariable("var:pc", "pc", StateTypeKind.ENUMERATION, Boundedness.FINITE,
        domain_bound=FiniteDomainBound("bound:pc", members=tuple(c["position"] for c in graph["configurations"])),
        description="Enumerated abstract active/completed token configuration.", source_ref_ids=refs),),
        metadata={"abstraction": SEMANTICS})
    predicates = [StatePredicate("pred:init", PredicateRole.INITIAL, "Initial token configuration.",
        expression={"var:pc": graph["initial_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs)]
    actions, origins = [], []
    for index, row in enumerate(graph["transitions"]):
        guard, effect = f"pred:guard:{index}", f"pred:next:{index}"
        predicates.extend((StatePredicate(guard, PredicateRole.GUARD, "Exact abstract configuration.",
            expression={"var:pc": row["from_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs),
            StatePredicate(effect, PredicateRole.NEXT, "Exact token-flow successor configuration.",
                expression={"var:pc": row["to_position"]}, subject_variable_ids=("var:pc",), source_ref_ids=refs)))
        action_id = f"action:token:{index}"
        actions.append(Action(action_id, f"AdvanceTokens{index}", ActionFrame(reads=("var:pc",), writes=("var:pc",)),
            guard_predicate_id=guard, next_predicate_id=effect, source_ref_ids=refs,
            enables_stutter=row["intent_action_id"] is None,
            attributes={"intent_action_id": row["intent_action_id"], "intent_edge_ids": row["intent_edge_ids"],
                        "abstract_event_only": True}))
        origins.append({"state_action_id": action_id, **row})
    transition = TransitionRelation("transition:next", TransitionKind.ACTION,
        "Exact disjunction of finite token-flow transitions and terminal self-loops.",
        action_ids=tuple(a.action_id for a in actions), allows_stutter=True)
    return StateTransitionIR(schema=schema, predicates=tuple(predicates), actions=tuple(actions),
        transitions=(transition,), metadata={"abstraction": SEMANTICS, "intent_document_id": document.document_id,
            "intent_ir_sha256": source_ir_sha256(document), "max_steps": options["max_steps"],
            "token_graph": graph, "code_effects_modeled": False, "normative_compliance_modeled": False}), origins
