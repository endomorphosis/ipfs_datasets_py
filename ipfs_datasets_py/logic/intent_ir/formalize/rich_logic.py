"""Loss-aware logic views of the bounded, learned rich Intent grammar.

The rich AST remains authoritative. Native IntentIR v1 has no conditional norm
or disjunction node; those constructs never become unconditional native goals.
Guards are typed unary properties whose truth is an explicit parameter, not an
asserted observation. Boolean operators have their ordinary Lean semantics.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ...formalization import typed_slots

SCHEMA = "intent-rich-logic-projection/v1"
AUTHORITY = {"proof_authority": False, "execution_authority": False,
             "source_semantics_verified": False, "claim_proved": False}
ASSUMPTIONS = [
    "The complete rich AST is a source-bound candidate, not a verified interpretation of natural language.",
    "Exact repeated surface strings within one sort share a symbolic referent; distinct surfaces are not asserted unequal.",
    "A guard is a typed unary property of its subject; its truth and relationship to software state are parameters, not observations.",
    "Conditional norms mean guard implies modal action, not an unconditional norm, execution precondition, or modality over an implication.",
    "Conjunction and disjunction compose complete modal propositions; neither connective introduces an execution order.",
    "Parameterized Lean modal operators have no deontic, cognitive, temporal, or recommendation axioms.",
]


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return typed_slots.canonical_slot_digest(value)


def _pins():
    from . import rich_grammar
    from ...syntax_core import ast, signatures, extensions
    from . import modal_projections, state_projections
    from ...CEC.native import dcec_core, dcec_integration
    from ...TDFOL import tdfol_core, tdfol_parser
    modules = (rich_grammar, typed_slots, ast, signatures, extensions,
               modal_projections, state_projections, dcec_core, dcec_integration,
               tdfol_core, tdfol_parser)
    paths = [Path(__file__), *(Path(module.__file__) for module in modules)]
    return [{"module": path.name, "sha256": _sha(path.read_bytes())} for path in paths]


def _formula_and_slots(ast):
    slots, identities = [], {}

    def slot(surface, sort, role):
        key = (sort, surface)
        if key not in identities:
            name = role + "_" + str(sum(row["slot_id"].startswith(role + "_") for row in slots))
            identities[key] = name
            slots.append({"slot_id": name, "surface": surface, "sort": sort})
        return {"slot_id": identities[key]}

    def atom(row):
        actor = slot(row["actor"], "Agent", "actor")
        obj = slot(row["object"], "Entity", "object")
        # Agency parameters are separate for separate actor slots. They cannot
        # accidentally collapse Alice's intention into Bob's intention.
        modality = row["modality"]
        if modality == "intended":
            modality += "@" + actor["slot_id"]
        return {"op": "modal", "modality": modality,
                "body": {"op": "predicate", "predicate": "action:" + row["action"],
                         "arguments": [actor, obj]}}

    kind = ast["kind"]
    if kind == "atom":
        formula = atom(ast)
    elif kind in {"and", "or"}:
        formula = {"op": kind, "left": atom(ast["left"]), "right": atom(ast["right"])}
    elif kind == "if":
        guard = ast["guard"]
        antecedent = {"op": "predicate", "predicate": "property:" + guard["property"],
                      "arguments": [slot(guard["subject"], "Entity", "guard")]}
        if guard["negated"]:
            antecedent = {"op": "not", "body": antecedent}
        formula = {"op": "implies", "left": antecedent, "right": atom(ast["body"])}
    else:
        return [], None
    return slots, formula


def _typed_expression(formula, environment):
    """Use shared sort/arity checking and a locally registered modal schema."""
    from ...syntax_core.ast import (TypedExpression, Binder, ExprCategory,
        mk_variable, mk_predicate, mk_and, mk_or, mk_implies, mk_not, mk_extension, mk_forall, elaborate)
    from ...syntax_core.signatures import atomic_sort, many_sorted_fol_signature
    from ...syntax_core.extensions import (empty_extension_registry, ExtensionSchemaDescriptor,
        ExtensionPosition, ExtensionPositionKind)

    sorts = {row["resolved_sort"]: atomic_sort(row["resolved_sort"]) for row in environment["slots"]}
    slots = {row["slot_id"]: row for row in environment["slots"]}
    symbols, counter = {}, 0

    def identifier():
        nonlocal counter
        counter += 1
        return "rich-node:" + str(counter)

    def lower(node):
        op = node["op"]
        if op == "predicate":
            domain = tuple(sorts[slots[arg["slot_id"]]["resolved_sort"]] for arg in node["arguments"])
            previous = symbols.get(node["predicate"])
            if previous is not None and previous[1] != domain:
                raise ValueError("conflicting_rich_predicate_signature")
            symbols.setdefault(node["predicate"], ("P" + str(len(symbols)), domain))
            args = tuple(mk_variable(identifier(), slots[arg["slot_id"]]["lean_name"], sort)
                         for arg, sort in zip(node["arguments"], domain))
            return mk_predicate(identifier(), symbols[node["predicate"]][0], args)
        if op == "modal":
            return mk_extension(identifier(), family="higher_order", profile="default",
                features=("intent.parameterized_modality",), payload_schema="intent.modal_parameter/v1",
                payload={"kind": "modal_parameter", "modality": node["modality"]},
                children=(lower(node["body"]),))
        if op == "not":
            return mk_not(identifier(), lower(node["body"]))
        return {"and": mk_and, "or": mk_or, "implies": mk_implies}[op](
            identifier(), lower(node["left"]), lower(node["right"]))

    root = lower(formula)
    signature = many_sorted_fol_signature("rich-signature", sorts=tuple(sorts.values()),
        predicates=tuple(symbols.values()), family="higher_order", profile="default")
    registry = empty_extension_registry("intent-rich-local-modal-schema")

    def validate_payload(payload):
        if (set(payload) != {"kind", "modality"} or payload["kind"] != "modal_parameter"
                or type(payload["modality"]) is not str or payload["modality"] not in {
                    node["modality"] for node in _walk(formula) if node["op"] == "modal"}):
            raise ValueError("invalid_rich_modal_parameter")

    registry.register(ExtensionSchemaDescriptor(schema_id="ext:intent.modal_parameter/v1",
        payload_schema="intent.modal_parameter/v1", family="higher_order", profile="default",
        features=("intent.parameterized_modality",), required_keys=("kind", "modality"),
        child_positions=(ExtensionPosition("body", ExtensionPositionKind.CHILD,
            category=ExprCategory.FORMULA),), payload_validator=validate_payload))
    # Universal closure records the parameterization without inventing a
    # constant, witness, or nonempty carrier assumption.
    root = mk_forall(identifier(), tuple(Binder(row["lean_name"], sorts[row["resolved_sort"]])
        for row in slots.values()), root)
    checked = elaborate(root, signature, extension_registry=registry)
    expression = TypedExpression("rich-typed-expression", checked, signature,
        metadata={"semantics": "parameterized_modal_formula", "free_referents_are_parameters": True,
                  "local_modal_extension_schema_checked": True,
                  "referent_scope": "universal_parameter_closure"})
    return expression.to_dict()


def _walk(node):
    yield node
    for key in ("body", "left", "right"):
        if key in node:
            yield from _walk(node[key])


def _native_modal(formula, family, slots):
    """Check parsed operators and arguments against independent expected shape."""
    from .modal_projections import _ast
    symbols = {}
    declarations = {row["slot_id"]: row for row in slots}

    def symbol(role, value):
        result = "S" + _digest([role, value])
        symbols[result] = {"role": role, "value": value, "symbol": result}
        return result

    def term(slot_id):
        row = declarations[slot_id]
        value = symbol("slot", {"surface": row["surface"], "sort": row["sort"]})
        return value if family == "dcec" else "entity:" + value

    def source(node):
        op = node["op"]
        if op == "predicate":
            return symbol("predicate", node["predicate"]) + "(" + ", ".join(term(arg["slot_id"]) for arg in node["arguments"]) + ")"
        if op == "modal":
            modal = node["modality"]
            if modal == "recommended":
                raise ValueError("recommendation_has_no_equivalent_strict_deontic_operator")
            if modal.startswith("intended@"):
                if family != "dcec":
                    raise ValueError("intention_agency_operator_not_in_tdfol_subset")
                return "I(" + term(modal.split("@", 1)[1]) + ", " + source(node["body"]) + ")"
            return {"required": "O", "permitted": "P", "prohibited": "F"}[modal] + "(" + source(node["body"]) + ")"
        if family == "dcec":
            args = [source(node["body"])] if op == "not" else [source(node["left"]), source(node["right"])]
            return op + "(" + ", ".join(args) + ")"
        if op == "not":
            return "¬(" + source(node["body"]) + ")"
        return "(" + source(node["left"]) + {"and": " ∧ ", "or": " ∨ ", "implies": " → "}[op] + source(node["right"]) + ")"

    text = source(formula)
    if family == "dcec":
        from ...CEC.native.dcec_integration import parse_dcec_string as parse
        from ...CEC.native import dcec_core as c

        def constant(value):
            if type(value) is not c.FunctionTerm or value.arguments:
                raise ValueError("native_modal_term_changed")
            return value.function.name

        def inspect(value, expected):
            op = expected["op"]
            if op == "predicate":
                return (type(value) is c.AtomicFormula and value.predicate.name == symbol("predicate", expected["predicate"])
                    and [constant(arg) for arg in value.arguments] == [term(arg["slot_id"]) for arg in expected["arguments"]])
            if op == "modal":
                modal = expected["modality"]
                if modal.startswith("intended@"):
                    return (type(value) is c.CognitiveFormula and value.operator is c.CognitiveOperator.INTENTION
                        and constant(value.agent) == term(modal.split("@", 1)[1]) and inspect(value.formula, expected["body"]))
                return (type(value) is c.DeonticFormula and value.agent is None and value.operator.value == {
                    "required": "O", "permitted": "P", "prohibited": "F"}[modal] and inspect(value.formula, expected["body"]))
            children = [expected["body"]] if op == "not" else [expected["left"], expected["right"]]
            return (type(value) is c.ConnectiveFormula and value.connective.value == {
                "not": "¬", "and": "∧", "or": "∨", "implies": "→"}[op]
                and len(value.formulas) == len(children) and all(inspect(v, child) for v, child in zip(value.formulas, children)))
    else:
        from ...TDFOL.tdfol_parser import parse_tdfol as parse
        from ...TDFOL import tdfol_core as c

        def inspect(value, expected):
            op = expected["op"]
            if op == "predicate":
                return (type(value) is c.Predicate and value.name == symbol("predicate", expected["predicate"])
                    and all(type(arg) is c.Constant for arg in value.arguments)
                    and [arg.name for arg in value.arguments] == [term(arg["slot_id"]) for arg in expected["arguments"]])
            if op == "modal":
                return (type(value) is c.DeonticFormula and value.agent is None and value.operator.value == {
                    "required": "O", "permitted": "P", "prohibited": "F"}[expected["modality"]] and inspect(value.formula, expected["body"]))
            if op == "not":
                return type(value) is c.UnaryFormula and value.operator is c.LogicOperator.NOT and inspect(value.formula, expected["body"])
            return (type(value) is c.BinaryFormula and value.operator.value == {"and": "∧", "or": "∨", "implies": "→"}[op]
                and inspect(value.left, expected["left"]) and inspect(value.right, expected["right"]))
    parsed = parse(text)
    if parsed is None or not inspect(parsed, formula) or parsed.get_free_variables() or parsed != parse(text):
        raise ValueError("native_modal_parser_changed_rich_formula_structure")
    return {"source": text, "ast": _ast(parsed), "ast_sha256": _digest(_ast(parsed)),
        "symbols": list(symbols.values()), "slot_declarations_sha256": _digest(slots), "native_parse_passed": True,
        "native_structure_checked": True, "native_reparse_passed": True,
        "backend_proof_executed": False, "typed_slot_specializations_applied": False}


def _native_document(ast, instruction):
    from ..schema import (IntentIRDocument, IntentKind, IntentStatement, StatementKind, IntentModality,
        IntentAction, SourceRef, SourceSpan, NodeGrounding, ReviewStatus, IntentControlEdge, ControlEdgeKind)
    from .rich_grammar import ast_to_text
    digest = _sha(instruction.encode())
    source = SourceRef("source", "instruction:learned-rich-intent", digest, digest, digest,
        review_status=ReviewStatus.MACHINE_EXTRACTED, span=SourceSpan(0, len(instruction)))
    atoms = [ast] if ast["kind"] == "atom" else [ast["left"], ast["right"]]
    statements, actions = [], []
    for index, atom in enumerate(atoms):
        statements.append(IntentStatement("goal:" + str(index), StatementKind.GOAL,
            IntentModality(atom["modality"]), ast_to_text(atom), ("source",), predicate=atom["action"],
            arguments=(atom["actor"], atom["object"]), confidence=0.0, grounding=NodeGrounding.INFERRED))
        actions.append(IntentAction("action:" + str(index), atom["actor"], atom["action"],
            (atom["object"],), ("source",), grounding=NodeGrounding.INFERRED))
    edges = () if len(actions) == 1 else (IntentControlEdge("edge:next", "action:0", "action:1",
        ControlEdgeKind.NEXT, source_ref_ids=("source",), grounding=NodeGrounding.INFERRED),)
    document = IntentIRDocument("intent-rich:" + digest, "Rich candidate action/workflow view",
        IntentKind.PROCEDURE if edges else IntentKind.DECLARATIVE, (source,), tuple(statements),
        tuple(actions), edges, ("action:0",), (actions[-1].action_id,), tags=("learned-candidate",))
    document.validate()
    return document


def project_rich_intent_logic(ast, *, instruction, context=None):
    """Project a validated rich candidate without reducing it to old flat slots."""
    from .rich_grammar import validate_ast
    ast = validate_ast(ast)
    if type(instruction) is not str or not instruction.strip() or len(instruction.encode()) > 65536:
        raise ValueError("bounded_original_rich_instruction_required")
    slots, formula = _formula_and_slots(ast)
    report = {"schema": SCHEMA, "status": "candidate", "source_sha256": _sha(instruction.encode()),
        "rich_ast": ast, "rich_ast_sha256": _digest(ast), "context_sha256": _digest(context),
        "slot_declarations": slots, "slot_environment": None, "typed_ir": None,
        "formula": formula, "lean_fixture": None, "native_intent_ir": None,
        "native_intent_ir_scope": "unsupported", "projections": [], "frontiers": [],
        "assumptions": list(ASSUMPTIONS), "producer_pins": _pins(), "provider_calls": 0,
        "external_backend_calls": 0, **AUTHORITY}
    if ast["kind"] in {"atom", "then"}:
        document = _native_document(ast, instruction)
        report["native_intent_ir"] = document.to_dict()
        report["native_intent_ir_scope"] = "action_declaration" if ast["kind"] == "atom" else "ordered_action_workflow"
        if ast["kind"] == "then":
            if context is not None:
                raise ValueError("typed_slot_context_unused_for_sequence")
            from .state_projections import project_state_families
            report["projections"] = list(project_state_families(document))
            report["status"] = "partial"
            report["frontiers"] = ["sequence_order_is_native_NEXT_not_Boolean_conjunction",
                "sequence_has_no_parameterized_Lean_order_semantics", "abstract_control_flow_not_execution_or_norm_compliance"]
    else:
        report["frontiers"].append("native_IntentIR_v1_lacks_scoped_Boolean_or_conditional_norms")
    if formula is not None:
        environment = typed_slots.prepare_typed_slot_environment(source_text=instruction, slots=slots, context=context)
        fixture = typed_slots.render_parameterized_fixture(environment, formula)
        report.update(slot_environment=environment, lean_fixture=fixture)
        if fixture["status"] == "candidate":
            report["typed_ir"] = _typed_expression(formula, environment)
        else:
            report["status"] = "unsupported"
            report["frontiers"].extend(row["code"] for row in fixture["diagnostics"])
        report["projections"].append({"family_id": "higher_order", "status": fixture["status"],
            "representation": {"format": "parameterized_Lean_formula", "payload": fixture},
            "semantics": "typed_parameterized_modal_formula", "backend_executed": False, **AUTHORITY})
        for family in ("dcec", "tdfol"):
            try:
                representation = _native_modal(formula, family, slots)
                projection = {"family_id": family, "status": "projected", "representation": representation,
                    "unsupported": [], "backend_executed": False, **AUTHORITY}
            except ValueError as exc:
                projection = {"family_id": family, "status": "unsupported", "representation": None,
                    "unsupported": [str(exc)], "backend_executed": False, **AUTHORITY}
            report["projections"].append(projection)
        if ast["kind"] == "if":
            report["frontiers"].append("guard_property_has_no_source_code_state_binding_or_observed_truth")
    report["projection_sha256"] = _digest(report)
    return report


def validate_rich_intent_logic(report, *, instruction, ast, context=None, lake_executable, timeout_seconds=30):
    """Replay every view before executing native Lake; no source text is run."""
    expected = project_rich_intent_logic(ast, instruction=instruction, context=context)
    if report != expected:
        raise ValueError("rich_logic_report_differs_from_exact_source_AST_context_replay")
    if report["lean_fixture"] is None:
        return {"schema": "intent-rich-logic-lake/v1", "status": "unsupported", "backend_status": "not_run",
            "backend_executed": False, "syntax_verified": False, "projection_sha256": report["projection_sha256"],
            "reason": "no_Lean_semantics_for_sequence", **AUTHORITY}
    receipt = typed_slots.validate_parameterized_fixture(report["lean_fixture"], source_text=instruction,
        slots=report["slot_declarations"], context=context, lake_executable=lake_executable,
        timeout_seconds=timeout_seconds)
    return {**receipt, "schema": "intent-rich-logic-lake/v1", "backend_status": receipt["status"],
        "projection_sha256": report["projection_sha256"], "validated_scope": "parameterized_rich_formula_syntax_only",
        "other_family_backends_executed": False, "actual_guard_truth_checked": False}


__all__ = ["project_rich_intent_logic", "validate_rich_intent_logic"]
