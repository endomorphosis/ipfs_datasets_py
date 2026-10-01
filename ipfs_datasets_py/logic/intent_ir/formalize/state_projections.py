"""Loss-aware abstract Intent control flow in native state IR and TLA+.

Default translation covers finite, unguarded linear NEXT workflows. Explicit
source-bound token-flow premises can select finite choices and fork/join
interleavings. A separate guarded-state mode exhaustively evaluates supplied
finite data, predicate bindings and bounded retries. The program counter records abstract configurations, not code,
action effects, permissions, or satisfaction of a goal. Projection performs no
external calls. Explicit qualification uses the shared bounded tool lifecycle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

SCHEMA = "intent-abstract-state-projection/v1"
_MODE = "abstract_intent_control_flow"
_ASSUMPTIONS = (
    "pc is an adapter-created position in a declared intent graph, not a code variable",
    "an abstract step advances one action label without asserting execution or effects",
    "normative goals remain unmodeled; an abstract prohibited-action label grants no permission",
    "terminal Done has an explicit self-loop; the finite step frontier explicitly stutters",
    "only abstract TypeOK and deadlock freedom are qualification properties; no liveness claim",
)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _document(value):
    from ..schema import IntentIRDocument
    from ..decoder import decode_intent_ir
    if type(value) is dict:
        value = decode_intent_ir(value)
    if not isinstance(value, IntentIRDocument):
        raise ValueError("native IntentIR document required")
    value.validate()
    return value


def _options(context):
    if context is None:
        context = {}
    if type(context) is not dict:
        raise ValueError("projection context must be an object")
    selected = context.get("state", {})
    if type(selected) is not dict or set(selected) - {"abstraction", "max_steps", "workflow"}:
        raise ValueError("closed state projection context required")
    mode, steps = selected.get("abstraction", _MODE), selected.get("max_steps", 64)
    if mode != _MODE or type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("unsupported state abstraction or bounded step count")
    result = {"abstraction": mode, "max_steps": steps}
    if "workflow" in selected:
        if type(selected["workflow"]) is not dict or len(_raw(selected["workflow"])) > 32768:
            raise ValueError("bounded explicit workflow premises required")
        result["workflow"] = json.loads(_raw(selected["workflow"]))
    return result


def _linear_order(document, options):
    from ..schema import ControlEdgeKind
    unsupported = []
    actions = {a.action_id: a for a in document.actions}
    if not 1 <= len(actions) <= 64:
        unsupported.append({"node_id": document.document_id, "reason": "requires_between_one_and_64_actions"})
    if len(document.entry_action_ids) != 1 or len(document.terminal_action_ids) != 1:
        unsupported.append({"node_id": document.document_id, "reason": "requires_one_entry_and_one_terminal_action"})
    outgoing, incoming = {}, {}
    for edge in document.control_edges:
        if edge.kind is not ControlEdgeKind.NEXT or edge.guard_statement_id:
            unsupported.append({"node_id": edge.edge_id, "reason": "only_unguarded_NEXT_edges_have_a_state_projection"})
        if edge.source_action_id in outgoing or edge.target_action_id in incoming:
            unsupported.append({"node_id": edge.edge_id, "reason": "branching_and_merging_require_explicit_transition_semantics"})
        outgoing[edge.source_action_id] = edge.target_action_id
        incoming[edge.target_action_id] = edge.source_action_id
    for action in document.actions:
        if action.precondition_ids:
            unsupported.append({"node_id": action.action_id, "reason": "action_preconditions_have_no_reviewed_state_binding"})
    if unsupported:
        return [], unsupported
    current = document.entry_action_ids[0]
    order = []
    while current not in order:
        order.append(current)
        if current not in outgoing:
            break
        current = outgoing[current]
    if (set(order) != set(actions) or order[-1] != document.terminal_action_ids[0]
            or order[-1] in outgoing or order[0] in incoming
            or len(document.control_edges) != len(order) - 1):
        return [], [{"node_id": document.document_id,
                     "reason": "workflow_must_be_one_complete_acyclic_linear_chain"}]
    if len(order) > options["max_steps"]:
        return [], [{"node_id": document.document_id,
                     "reason": "step_budget_does_not_cover_the_declared_workflow"}]
    return order, []


def _state(document, order, options):
    from .projection_contracts import source_ir_sha256
    from ...software_verification.state import (StateSchema, StateVariable, StateTypeKind,
        Boundedness, FiniteDomainBound, StatePredicate, PredicateRole)
    from ...software_verification.transitions import (StateTransitionIR, Action, ActionFrame,
                                                      TransitionRelation, TransitionKind)
    positions = {action_id: f"position_{index}" for index, action_id in enumerate(order)}
    all_refs = tuple(sorted(s.ref_id for s in document.sources))
    variable = StateVariable("var:pc", "pc", StateTypeKind.ENUMERATION, Boundedness.FINITE,
        domain_bound=FiniteDomainBound("bound:pc", members=tuple(positions.values()) + ("done",)),
        description="Abstract intent graph position; no executable-code state semantics.",
        source_ref_ids=all_refs)
    schema = StateSchema(variables=(variable,), metadata={"abstraction": _MODE})
    predicates = [StatePredicate("pred:init", PredicateRole.INITIAL, "Initial intent graph position.",
        expression={"var:pc": positions[order[0]]}, subject_variable_ids=("var:pc",), source_ref_ids=all_refs)]
    actions, origins = [], []
    declared = {a.action_id: a for a in document.actions}
    for index, action_id in enumerate(order):
        before = positions[action_id]
        after = positions[order[index + 1]] if index + 1 < len(order) else "done"
        ref_ids = declared[action_id].source_ref_ids
        guard_id, next_id = f"pred:guard:{index}", f"pred:next:{index}"
        predicates.extend((
            StatePredicate(guard_id, PredicateRole.GUARD, "At declared abstract position.",
                expression={"var:pc": before}, subject_variable_ids=("var:pc",), source_ref_ids=ref_ids),
            StatePredicate(next_id, PredicateRole.NEXT, "Advance the abstract control position.",
                expression={"var:pc": after}, subject_variable_ids=("var:pc",), source_ref_ids=ref_ids)))
        actions.append(Action(f"action:abstract:{index}", f"AdvanceIntent{index}",
            ActionFrame(reads=("var:pc",), writes=("var:pc",)),
            guard_predicate_id=guard_id, next_predicate_id=next_id, source_ref_ids=ref_ids,
            attributes={"intent_action_id": action_id, "abstract_event_only": True}))
        origins.append({"state_action_id": actions[-1].action_id, "intent_action_id": action_id,
                        "from_position": before, "to_position": after})
    predicates.extend((
        StatePredicate("pred:done-guard", PredicateRole.GUARD, "Terminal abstract position.",
            expression={"var:pc": "done"}, subject_variable_ids=("var:pc",)),
        StatePredicate("pred:done-next", PredicateRole.NEXT, "Explicit terminal self-loop.",
            expression={"var:pc": "done"}, subject_variable_ids=("var:pc",))))
    actions.append(Action("action:done", "Done", ActionFrame(reads=("var:pc",), writes=("var:pc",)),
        guard_predicate_id="pred:done-guard", next_predicate_id="pred:done-next", enables_stutter=True,
        attributes={"origin": "adapter_generated_terminal_self_loop", "abstract_event_only": True}))
    transition = TransitionRelation("transition:next", TransitionKind.ACTION,
        "Disjunction of abstract control advances and terminal self-loop.",
        action_ids=tuple(a.action_id for a in actions), allows_stutter=True)
    return StateTransitionIR(schema=schema, predicates=tuple(predicates), actions=tuple(actions),
        transitions=(transition,), metadata={"abstraction": _MODE,
            "intent_document_id": document.document_id, "intent_ir_sha256": source_ir_sha256(document),
            "position_map": origins, "max_steps": options["max_steps"],
            "code_effects_modeled": False, "normative_compliance_modeled": False}), origins


def _qualification_artifacts(native, guarded_graph=None):
    """Add an explicit finite frontier self-loop; retain the native artifact."""
    declared = re.match(r"---- MODULE ([A-Za-z][A-Za-z0-9_]*) ----\n", native.model_text)
    if declared is None:
        raise ValueError("native compiler did not declare a canonical module header")
    if declared.group(1) != native.module_name:
        raise ValueError("native artifact module name differs from its source header")
    suffix = (
        "\\* Intent adapter qualification: finite control graph only.\n"
        "BudgetStutter == /\\ step = MaxSteps /\\ UNCHANGED vars\n"
        "AbstractNext == Next \\/ BudgetStutter\n"
        "AbstractSpec == Init /\\ [][AbstractNext]_vars\n\n"
        "====\n")
    if not native.model_text.endswith("====\n"):
        raise ValueError("unexpected native TLA module terminator")
    config = "SPECIFICATION AbstractSpec\nINVARIANT TypeOK\nCHECK_DEADLOCK TRUE\n"
    properties = ["TypeOK", "deadlock_freedom_of_abstract_bounded_control"]
    additions = ["BudgetStutter", "AbstractNext", "AbstractSpec"]
    if guarded_graph is not None:
        # TLC's global step cutoff must not hide an already enumerated abstract
        # deadlock, even when that configuration is reached at exactly MaxSteps.
        deadlocks = sorted(row["position"] for row in guarded_graph["deadlocks"])
        predicate = " /\\ ".join("pc /= " + json.dumps(position) for position in deadlocks) or "TRUE"
        suffix = "NoAbstractDeadlock == " + predicate + "\n" + suffix
        config = "SPECIFICATION AbstractSpec\nINVARIANT TypeOK\nINVARIANT NoAbstractDeadlock\nCHECK_DEADLOCK TRUE\n"
        properties.append("NoAbstractDeadlock")
        additions.append("NoAbstractDeadlock")
    return {"module_name": declared.group(1),
            "model_text": native.model_text[:-5] + suffix,
            "tlc_config_text": config,
            "excluded_liveness_properties": list(native.liveness_properties),
            "qualification_properties": properties,
            "generated_additions": additions,
            "modification_reason": "explicit_cutoff_self_loop_and_no_unasserted_liveness_property",
            "native_model_digest": native.model_digest,
            "native_artifact_module_name": native.module_name,
            "module_filename_uses_declared_source_header": True}


def project_state_families(document, context=None):
    """Return native transition-system and TLA+ projections without running tools."""
    from .projection_contracts import make_projection
    from ...backends.tla.compiler import TLACompiler, TLACompileBounds
    document, options = _document(document), _options(context)
    graph = None
    guarded = False
    assumptions, semantics = _ASSUMPTIONS, _MODE
    if "workflow" in options:
        from .workflow_state import (workflow_graph, workflow_state, WorkflowScopeError,
                                     ASSUMPTIONS, SEMANTICS)
        if options["workflow"].get("semantics") == "finite_guarded_state_flow":
            from .guarded_workflow import (guarded_workflow_graph, guarded_workflow_state,
                                           ASSUMPTIONS, SEMANTICS)
            guarded = True
            workflow_graph, workflow_state = guarded_workflow_graph, guarded_workflow_state
        assumptions = (_ASSUMPTIONS[2],
            ("Each terminal guarded configuration has an explicit self-loop; NoAbstractDeadlock separately rejects deadlocks at every step frontier."
             if guarded else "Each terminal token configuration has an explicit self-loop; the finite step frontier explicitly stutters."),
            _ASSUMPTIONS[4], *ASSUMPTIONS)
        semantics = SEMANTICS
        try:
            graph = workflow_graph(document, options["workflow"], options["max_steps"])
            blocked = []
        except WorkflowScopeError as exc:
            blocked = [{"node_id": exc.node_id, "reason": exc.reason}]
    else:
        order, blocked = _linear_order(document, options)
    nodes = tuple(sorted([a.action_id for a in document.actions] + [e.edge_id for e in document.control_edges]
                         + [s.statement_id for s in document.statements]))
    if blocked:
        return [make_projection(document, family_id="transition_system", profile_id=profile, status="unsupported",
            representation={"format": SCHEMA, "payload": None, "source": "native_intent_ir",
                            "context": options}, source_node_ids=nodes, assumptions=assumptions,
            unsupported=blocked, semantics=semantics,
            validation=[{"validator": "intent_guarded_workflow_scope" if guarded else "intent_token_workflow_scope" if "workflow" in options else "intent_linear_workflow_scope",
                         "status": "failed", "details": {}}])
            for profile in (None, "tla_plus")]
    if graph is None:
        state, origins = _state(document, order, options)
        details = {"states": len(order) + 1, "abstract_actions": len(order), "terminal_self_loop": True}
        extra = {}
    else:
        state, origins = workflow_state(document, graph, options)
        details = {"states": len(graph["configurations"]), "abstract_actions": len(graph["transitions"]),
                   "terminal_self_loop": True, "all_configurations_enumerated": True,
                   "max_abstract_steps": graph["max_abstract_steps"], "premises_verified": False}
        extra = {"configuration_map": graph["configurations"]}
        if guarded:
            details["terminal_self_loop"] = any(c["terminal"] for c in graph["configurations"])
            extra["guarded_model"] = {"data_schema": graph["data_schema"], "deadlocks": graph["deadlocks"],
                "deadlock_free": graph["deadlock_free"], "initial_valuation_count": graph["initial_valuation_count"],
                "predicate_binding_semantics": "caller_supplied_abstract_truth_not_source_code_equivalence"}
    native = TLACompiler(bounds=TLACompileBounds(max_steps=options["max_steps"], max_enum_members=128)).compile(
        state, module_name="IntentControlFlow")
    qualification = _qualification_artifacts(native, graph if guarded else None)
    omitted = [{"node_id": s.statement_id,
                "reason": "statement_meaning_and_modality_not_encoded_in_abstract_pc"}
               for s in (sorted(document.statements, key=lambda s: s.statement_id) if graph else document.statements)]
    for action in (sorted(document.actions, key=lambda a: a.action_id) if graph else document.actions):
        omitted.append({"node_id": action.action_id, "reason": "action_execution_and_code_effects_not_modeled"})
        for field in ("tool_refs", "input_refs", "output_refs", "effect_ids", "verification_ids"):
            if getattr(action, field):
                omitted.append({"node_id": action.action_id, "reason": f"{field}_not_encoded_in_abstract_pc"})
    common = {"source_node_ids": nodes, "assumptions": assumptions, "unsupported": omitted,
              "semantics": semantics, "status": "partial"}
    extra_validation = ([{"validator": "finite_guarded_deadlock_scan", "status": "passed" if graph["deadlock_free"] else "failed",
        "details": {"all_configurations_enumerated": True, "deadlock_count": len(graph["deadlocks"]),
                    "initial_valuation_count": graph["initial_valuation_count"], "premises_verified": False}}]
                        if guarded else [])
    state_report = make_projection(document, family_id="transition_system", **common,
        representation={"format": "StateTransitionIR@1", "payload": state.to_dict(),
                        "source": "native_intent_ir", "context": options, "node_map": origins, **extra},
        validation=[{"validator": "StateTransitionIR.validate", "status": "passed",
                     "details": details}, *extra_validation])
    tla_report = make_projection(document, family_id="transition_system", profile_id="tla_plus", **common,
        representation={"format": "TLABackend@1", "payload": native.to_dict(),
                        "source": "StateTransitionIR@1", "context": options, "node_map": origins,
                        "qualification": qualification, **extra},
        validation=[{"validator": "TLACompiler.compile_state", "status": "passed",
                     "details": {"native_losses": len(native.losses)}},
                    {"validator": "tla2sany.SANY", "status": "not_run", "details": {}},
                    {"validator": "tlc2.TLC", "status": "not_run", "details": {}}, *extra_validation])
    return [state_report, tla_report]


def validate_tla_projection(report, jar_path, *, document, context=None,
                            java_executable="java", run_model_checker=False,
                            timeout_seconds=20, runner=None):
    """Explicitly check exact regenerated TLA source through a bounded runner.

    The original IntentIR is required for replay before launching any external
    process. A tool success concerns only the disclosed abstract control graph.
    """
    from ...backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits, ToolRuntime
    if type(run_model_checker) is not bool or type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded explicit TLA qualification settings required")
    expected = project_state_families(document, context)[1]
    if _raw(report) != _raw(expected) or report["status"] != "partial":
        raise ValueError("TLA projection differs from exact native source replay or is unsupported")
    jar = Path(jar_path).resolve()
    executable = shutil.which(str(java_executable))
    if not jar.is_file() or jar.stat().st_size > 256 * 1024 * 1024 or executable is None:
        return {"schema": "intent-tla-qualification/v1", "status": "unavailable",
                "reason": "explicit_jar_or_java_unavailable", "proof_authority": False,
                "projection_sha256": report["projection_sha256"],
                "source_ir_sha256": report["source_ir_sha256"],
                "code_correctness_verified": False, "runs": []}
    qualifier = expected["representation"]["qualification"]
    name = qualifier["module_name"]
    model = qualifier["model_text"]
    config = qualifier["tlc_config_text"]
    files = {name + ".tla": model, name + ".cfg": config}
    native_runner = runner or BoundedToolRunner()
    limits = ToolRunLimits(timeout_seconds=float(timeout_seconds), cpu_seconds=float(timeout_seconds),
        max_output_bytes=262144, max_input_bytes=1024 * 1024, max_workspace_bytes=16 * 1024 * 1024)
    runs = []
    checks = [("tla2sany.SANY", (name + ".tla",))]
    if run_model_checker:
        checks.append(("tlc2.TLC", ("-workers", "1", "-config", name + ".cfg", name + ".tla")))
    for main, args in checks:
        result = native_runner.run(ToolRunRequest(
            argv=(executable, "-Xmx256m", "-cp", str(jar), main, *args), runtime=ToolRuntime.JVM,
            limits=limits, input_files=files))
        output = result.stdout + "\n" + result.stderr
        passed = result.ok and not (result.output_truncated or result.workspace_limit_exceeded)
        if main == "tla2sany.SANY":
            passed = (passed and f"Semantic processing of module {name}" in output
                      and not re.search(r"(?:Fatal errors|Semantic errors|Parse errors|Errors:)\s*", output, re.I))
        else:
            passed = passed and "Model checking completed. No error has been found." in output
        runs.append({"validator": main, "status": "passed" if passed else "failed", "result": result.to_dict()})
        if not passed:
            break
    return {"schema": "intent-tla-qualification/v1",
        "status": "passed" if len(runs) == len(checks) and all(r["status"] == "passed" for r in runs) else "failed",
        "projection_sha256": report["projection_sha256"], "source_ir_sha256": report["source_ir_sha256"],
        "model_sha256": _sha(model.encode()), "config_sha256": _sha(config.encode()),
        "model_text": model, "tlc_config_text": config,
        "jar_sha256": _sha(jar.read_bytes()), "java_executable": executable,
        "runs": runs, "properties": qualifier["qualification_properties"] if run_model_checker else [],
        "bounded": True, "proof_authority": False, "code_correctness_verified": False,
        "unbounded_liveness_verified": False, "normative_compliance_verified": False,
        "assumptions": list(expected["assumptions"])}
