"""Fresh bounded native compositions, authored premises rather than corpus gold.

Only the source specification manifest is eager. Test native targets are built
only by explicit request after a caller seals every compared checkpoint.
Source-to-model correspondence is a supplied fixture premise, never a proof.
The UI and Security constructors preserve the established native smoke profiles.
UI transitions are authored as untimed: transition timeout semantics remain
unsupported by the native UI owner and are outside this panel. Confirmation
freshness uses the separate supported request-token clock interpretation.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "authored-complete-feature-panel/v2"
DOMAINS = ("intent_ir", "ui_ux_ir")
ACTORS = ("curator", "reviewer")
ACTIONS = ("authorize", "publish", "dispatch", "revoke", "schedule")
OBJECTS = ("request", "submission")


def manifest():
    rows = []
    for domain in DOMAINS:
        for actor in range(2):
            for action in range(5):
                split = "test" if action == (actor + 4) % 5 else "validation" if action == (actor + 2) % 5 else "train"
                group = f"complete-features-v2:{domain}:{actor}:{action}"
                rows.append({"domain_id": domain, "source_id": group, "group_id": group,
                    "split": split, "actor": actor, "action": action, "variant": action % 2})
    return {"schema": SCHEMA, "rows": rows, "partition_unit": "actor/action composition",
        "scope": "new authored compositions of supported native profiles; no natural-source generalization claim",
        "ui_scope": "untimed state transitions with explicit timed request-token confirmation policies",
        "unsupported_profiles_excluded_from_panel_design": ["UI transition timeout semantics"],
        "source_semantics_verified": False, "qualified": False, "admitted": False}


def rows(domain, split):
    if domain not in DOMAINS or split not in {"train", "validation", "test"}:
        raise ValueError("explicit supported domain and split required")
    return [row for row in manifest()["rows"] if row["domain_id"] == domain and row["split"] == split]


def formulas(row):
    actor, action = ACTORS[row["actor"]], ACTIONS[row["action"]]
    person, event = actor.title(), action.title()
    return {"FOL": f"forall x. {person}(x) -> {event}(x)",
        "DFOL": f"forall x. O({event}(x))", "TFOL": f"forall x. □({event}(x))",
        "TDFOL": f"forall x. O(□({event}(x)))", "CEC": f"K({person},Happens({event},Time))",
        "DCEC": f"O(K({person},Happens({event},Time)))", "frame_logic": f"{actor}[role -> {action}].",
        "propositional": f"{actor} and {action}"}


def _ui(row):
    from ipfs_datasets_py.logic.formalization.autoencoder.ui_training_inputs import SCHEMA as UI_SCHEMA
    from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl_identity import compute_verified_interface_cid
    obj, action = OBJECTS[row["actor"]], ACTIONS[row["action"]]
    method = f"{action}_{obj}"
    descriptor = {"name": "records", "namespace": "authored.panel", "version": "1.0.0",
        "methods": [{"name": method, "input_schema": {"type": "object", "properties": {
            "record_id": {"type": "string"}}, "required": ["record_id"], "additionalProperties": False},
            "output_schema": {"type": "object", "properties": {"complete": {"type": "boolean"}},
                "required": ["complete"], "additionalProperties": False}}]}
    title = f"{action.title()} {obj}"
    component, event = "component:action", "event:activate"
    return {"schema_version": UI_SCHEMA,
        "provenance": {"dataset": SCHEMA, "revision": "authored-complete-features-20261001-v2", "split": row["split"],
            "row_id": row["source_id"], "group_id": row["group_id"]},
        "dom_aria": {"document_id": row["source_id"], "title": title, "source_id": row["source_id"],
            "source_revision": "authored-complete-features-20261001-v2", "root": {"node_id": component,
                "role": "button", "name": title, "actions": ["activate"]}},
        "interface": {"descriptor": descriptor, "claimed_interface_cid": compute_verified_interface_cid(descriptor)},
        "bindings": [{"binding_id": "binding:action", "action_id": method, "component_id": component,
            "dom_action": "activate", "method_name": method, "risk_class": "high",
            "confirmation_class": "confirm", "idempotency": "non_idempotent"}],
        "behavior": {"model_id": method, "states": [{"state_id": "pending"},
            {"state_id": "finished", "terminal": True}], "initial_state_ids": ["pending"],
            "transitions": [{"transition_id": "complete", "source_state_ids": ["pending"],
                "target_state_id": "finished", "event_id": event}]},
        "events": [{"event_id": event, "kind": "activate", "target_component_id": component,
            "timestamp_ms": 1, "provenance": "synthetic", "capability_id": "pointer_mouse",
            "consent_ok": True, "source_adapter": "authored-structural-panel"}]}

def _security(row):
    from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
    from ipfs_datasets_py.logic.ir_core.provenance import SourceRef
    from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import CodeUnit
    from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence
    from ipfs_datasets_py.logic.software_verification.program import (
        ProgramIR, ProgramExpression, ProgramCommand, ProgramFunction, ControlFlowGraph, BasicBlock)
    from ipfs_datasets_py.logic.software_verification.state import StateSchema, StateVariable, FiniteDomainBound, StatePredicate
    from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR, Action, ActionFrame, TransitionRelation
    from ipfs_datasets_py.logic.software_verification.temporal import TemporalFormula
    from ipfs_datasets_py.logic.software_verification.contracts import ProgramContract, ContractClause
    from ipfs_datasets_py.logic.software_verification.heap import HeapModel, HeapLocation, HeapValue
    from ipfs_datasets_py.logic.software_verification.separation import SeparationLogicIR, emp_formula
    from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR, InformationFlowPolicy, SelfCompositionBound
    name = f"{ACTIONS[row['action']]}_{OBJECTS[row['actor']]}"
    value = row["variant"]
    raw = f"def {name}():\n    return {value}\n".encode()
    origin = canonical_identity({"panel": SCHEMA}, domain="authored", schema_version="v1").cid
    body_cid = canonical_identity({"body": raw.decode()}, domain="cvefixes-security-ir/code-body",
                                  schema_version="cvefixes-code-body/v1").cid
    unit = CodeUnit(source_cids=(origin,), parent_cids=(origin,), config_cid=origin,
        unit_kind="symbol", language="Python", path=name + ".py", polarity="fixed",
        payload={"body_sha256": hashlib.sha256(raw).hexdigest(), "body_cid": body_cid})
    source = SourceRef(ref_id=unit.cid, source_uri="code-unit:" + unit.cid, source_id=unit.path,
        source_revision=SCHEMA, content_sha256=unit.payload["body_sha256"], content_cid=body_cid)
    refs = {"source_ref_ids": (source.ref_id,)}
    expression = ProgramExpression("expr:return", "literal", "integer", attributes={"value": value}, **refs)
    true = ProgramExpression("expr:true", "literal", "boolean", attributes={"value": True}, **refs)
    command = ProgramCommand("cmd:return", "return", expression_ids=(expression.expression_id,), **refs)
    graph = ControlFlowGraph(graph_id="cfg:return", entry_block_id="block:return",
        blocks=(BasicBlock("block:return", (command.command_id,), **refs),), edges=(),
        normal_exit_block_ids=("block:return",))
    function = ProgramFunction("function:return", name, graph, return_type="integer", **refs)
    program = ProgramIR(sources=(source,), spans=(), symbols=(), expressions=(expression, true), commands=(command,), functions=(function,))
    contract = ProgramContract("contract:return", function.function_id,
        preconditions=(ContractClause("pre:true", "precondition", "expr:true", "true", **refs),),
        postconditions=(ContractClause("post:true", "postcondition", "expr:true", "true", **refs),), **refs)
    schema = StateSchema(variables=(StateVariable("var:result", "result", "integer", "finite",
        domain_bound=FiniteDomainBound("bound:result", lower=0, upper=1)),))
    initial = StatePredicate("pred:initial", "initial", "result = 0", expression={"result": 0},
        subject_variable_ids=("var:result",), **refs)
    nxt = StatePredicate("pred:next", "next", f"result' = {value}", expression={"result": value},
        subject_variable_ids=("var:result",), **refs)
    step = Action("action:return", "Return", ActionFrame(reads=("var:result",), writes=("var:result",)),
        next_predicate_id="pred:next")
    transition = StateTransitionIR(schema=schema, predicates=(initial, nxt), actions=(step,),
        transitions=(TransitionRelation("rel:return", "action", "Return or stutter",
            action_ids=(step.action_id,), allows_stutter=True),))
    temporal = TemporalFormula("always", operands=(TemporalFormula("atom", proposition="bounded_result", **refs),), **refs)
    heap = HeapModel(locations=(HeapLocation("loc:cell", "cell", "address", "integer", **refs),),
        values=(HeapValue("val:result", "integer", "integer", literal=str(value), **refs),), model_id="heap:result")
    separation = SeparationLogicIR(sources=(source,), heap=heap,
        formulas=(emp_formula("formula:emp", **refs),), root_formula_id="formula:emp")
    hyper = HyperpropertyIR.noninterference_document(policy=InformationFlowPolicy(policy_id="policy:flow",
        low_input_fields=("public",), high_input_fields=("secret",), observation_fields=("result",)),
        bound=SelfCompositionBound("bound:flow", max_traces=2, max_pairs=1, max_steps=4))
    return {"code_unit": unit, "source_bytes": raw,
        "typed_inputs": [CodeLogicEvidence(model, source) for model in (program, contract, transition, temporal, heap, separation, hyper)]}


def _intent(row):
    from ipfs_datasets_py.logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
        StatementKind, IntentModality, IntentAction, SourceRef)
    from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
    from ipfs_datasets_py.logic.formalization.autoencoder.native_intent_guarded_lean import IntentEffectBindings
    actor, action, obj = ACTORS[row["actor"]], ACTIONS[row["action"]], OBJECTS[row["actor"]]
    text = (f"Authored {SCHEMA} premise: {actor} is required and intends to {action} {obj}. "
        f"The declared action requires {obj} readiness and establishes completion. "
        "Explicit finite model assumptions: ready initially true; completed initially false; "
        "the action sets completed true and preserves readiness.")
    ref = SourceRef("source", "urn:" + row["source_id"], row["source_id"], SCHEMA,
        content_sha256=hashlib.sha256(text.encode()).hexdigest())
    statements = (
        IntentStatement("goal:required", StatementKind.GOAL, IntentModality.REQUIRED,
            f"{actor} must {action} {obj}.", ("source",), action, (actor, obj)),
        IntentStatement("goal:intended", StatementKind.GOAL, IntentModality.ASSERTED,
            f"{actor} intends to {action} {obj}.", ("source",), action, (actor, obj)),
        IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED,
            f"{obj} is ready.", ("source",), "ready", (obj,)),
        IntentStatement("effect", StatementKind.EFFECT, IntentModality.ASSERTED,
            f"{obj} operation is complete.", ("source",), "complete", (obj,)))
    operation = IntentAction("action:declared", actor, action, (obj,), ("source",),
        precondition_ids=("pre",), effect_ids=("effect",))
    document = IntentIRDocument(row["source_id"], "Authored family-safe guarded Intent premise",
        IntentKind.PROCEDURE, (ref,), statements, (operation,), (),
        (operation.action_id,), (operation.action_id,))
    document.validate()
    workflow = {"semantics": "finite_guarded_state_flow", "source_ir_sha256": source_ir_sha256(document),
        "evidence_ref": "source", "variables": [
            {"variable_id": "ready", "kind": "boolean", "domain": [False, True],
             "initial_values": [True], "evidence_ref": "source"},
            {"variable_id": "completed", "kind": "boolean", "domain": [False, True],
             "initial_values": [False], "evidence_ref": "source"}],
        "predicate_bindings": [{"statement_id": "pre", "expression": {"op": "eq", "variable_id": "ready", "value": True},
                                "evidence_ref": "source"}],
        "action_updates": [{"action_id": operation.action_id, "outcomes": [
            {"values": {"completed": True}, "evidence_ref": "source"}], "evidence_ref": "source"}],
        "retry_bounds": []}
    binding = IntentEffectBindings.from_dict({"schema": "intent-guarded-effect-bindings/v1",
        "source_ir_sha256": source_ir_sha256(document),
        "bindings": [{"statement_id": "effect", "expression": {"op": "eq", "variable_id": "completed", "value": True},
                      "evidence_ref": "source"}]})
    return {"document": document, "source_text": text, "context": {"state": {"max_steps": 4, "workflow": workflow}},
        "guarded_effect_bindings": binding}


def _legal(row):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (ModalIRDocument, ModalIRFormula,
        ModalIROperator, ModalIRPredicate, ModalIRProvenance, ModalIRFrameLogic, ModalIRFrameLogicTriple)
    actor, action, obj = ACTORS[row["actor"]], ACTIONS[row["action"]], OBJECTS[row["actor"]]
    mode = row["action"] % 3
    symbol, label = (("O", "obligation"), ("P", "permission"), ("F", "prohibition"))[mode]
    duration = ("within 7 days", "for at least 14 days", "for at least 18 hours")[mode]
    condition, exception = "request received and not withdrawn", "emergency or closure"
    text = (f"Authored {SCHEMA} premise: {actor} has the declared {label} to {action} {obj} "
        f"{duration}, conditioned on {condition}, except {exception}. "
        "The separate interval view is an explicit interpretation declaration.")
    provenance = ModalIRProvenance(row["source_id"], 0, len(text))
    formulas = [ModalIRFormula("norm:one", ModalIROperator("deontic", "D", symbol, label),
        ModalIRPredicate(action, [actor, obj], "clause"), provenance,
        conditions=[condition, duration], exceptions=[exception]),
        ModalIRFormula("time:one", ModalIROperator("temporal", "LTL", "F" if mode == 0 else "G",
            "eventually" if mode == 0 else "always"), ModalIRPredicate(action, [actor, obj], "clause"), provenance,
            conditions=[condition, duration], exceptions=[exception])]
    document = ModalIRDocument(row["source_id"], SCHEMA, text, formulas=formulas,
        frame_logic=ModalIRFrameLogic(selected_frame=action, graph_id=row["source_id"],
            triples=[ModalIRFrameLogicTriple(actor, action, obj)]))
    return {"document": document, "source_text": text}


def _envelope(module, target, source, declarations):
    return {"schema": module.EVIDENCE_SCHEMA, "source_ref": source.to_dict(),
        "original_projection_id": target["projection_id"], "original_source_digest": target["source_digest"],
        "original_payload_sha256": module.digest(target["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": declarations}


def _qualify_legal(row, report, source):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_legal_qualified_lean as owner
    mode = row["action"] % 3
    obj = OBJECTS[row["actor"]]
    def atom(name, *args):
        return {"op": "atom", "predicate": {"name": name, "arguments": list(args)}}
    result = []
    for family in ("deontic", "temporal"):
        target = next(p for p in report["projections"] if p["projection_id"] == f"legal-ir/modal-family/{family}/v3")
        formula, = target["payload"]["formulas"]
        declaration = {"formula_index": 0, "original_formula_sha256": owner.digest(formula),
            "kind": "activation_guarded_legal_rule", "activation_scope": "all_conditions_at_evaluation_origin",
            "conditions": [{"source_index": 0, "source_text": formula["conditions"][0],
                "expression": {"op": "all", "operands": [atom("request_received", obj),
                    {"op": "not", "operand": atom("withdrawn", obj)}]}}],
            "temporal": {"source_index": 1, "source_text": formula["conditions"][1],
                "temporal_kind": "within_duration" if mode == 0 else "minimum_duration",
                "quantity": (7, 14, 18)[mode], "unit": "hour" if mode == 2 else "day",
                "time_domain": "discrete_nat", "origin": "caller_supplied_evaluation_time",
                "lower_inclusive": True, "upper_inclusive": True},
            "exception_scope": "activation_time_waiver" if mode == 0 else "per_tick_exemption",
            "exceptions": [{"source_index": 0, "source_text": formula["exceptions"][0],
                "expression": {"op": "any", "operands": [atom("emergency"), atom("closure")]}}]}
        result.append(owner.LegalQualifierInterpretation.from_dict(_envelope(owner, target, source, [declaration])))
    return result


def _qualify_ui(row, report, source, action):
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_confirmation_lean as owner
    target = next(p for p in report["projections"] if p["projection_id"] == "ui_ux_ir:tdfol")
    declarations = []
    for offset, formula in enumerate(target["payload"]["formulas"]):
        item = {"formula_index": offset, "original_formula_sha256": owner.digest(formula), "kind": "atomic_UI_norm"}
        if offset < 2:
            item.update(kind="UI_request_token_confirmation_policy", action_id=action,
                policy="every_invocation_has_valid_confirmation" if offset == 0 else "unconfirmed_invocation",
                event_order="strict_sequence_position", time_domain="discrete_nat_ticks", clock_order="nondecreasing",
                max_age_ticks=(7, 14, 21, 7, 14)[row["action"]], freshness_upper_inclusive=True,
                correlation="action_request_token", cancellation="since_latest_confirmation",
                consumption="every_prior_invocation_consumes_token", trace_scope="finite_observed_prefix",
                unobserved_future="unknown")
        declarations.append(item)
    return [owner.UIConfirmationInterpretation.from_dict(_envelope(owner, target, source, declarations))]


def prepare_case(row):
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v6 as previous, family_training_v7 as native
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    if row not in manifest()["rows"]:
        raise ValueError("exact declared authored manifest row required")
    domain = row["domain_id"]
    inputs = (_legal(row) if domain == "legal_ir" else _intent(row) if domain == "intent_ir"
        else _security(row) if domain == "security_ir" else {"ui_training_row": _ui(row)})
    source = native.supplemental_source_ref(domain, **inputs)
    supplied_formulas = formulas(row)
    inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, source)
        for name, formula in supplied_formulas.items()]
    original = previous.prepare_family_training_targets_v6(domain, **inputs)
    if domain == "legal_ir":
        inputs["legal_qualifier_inputs"] = _qualify_legal(row, original, source)
    elif domain == "ui_ux_ir":
        inputs["ui_confirmation_inputs"] = _qualify_ui(row, original, source, inputs["ui_training_row"]["bindings"][0]["action_id"])
    report = native.prepare_family_training_targets_v7(domain, **inputs)
    return {"source_inputs": inputs, "report": report,
        "fixture": {"schema": SCHEMA, "specification": row, "formulas": supplied_formulas,
            "source_ref": source.to_dict(), "source_semantics_verified": False,
            "qualified": False, "admitted": False, "source_decoder_trained": False}}


def reviews(report, row):
    present = {p["logic_family"] for p in report["projections"]}
    return [{"family_id": family["family_id"], "source_digest": report["source_digest"],
        "disposition": "inapplicable", "reason": "Closed authored native composition supplies only its exact explicit models, formulas and policies; not a review of real corpus sources.",
        "evidence_refs": ["urn:" + row["source_id"]]}
        for family in report["family_inventory"] if family["family_id"] not in present]
