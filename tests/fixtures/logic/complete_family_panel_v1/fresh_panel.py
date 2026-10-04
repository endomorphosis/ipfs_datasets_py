"""Authored, compositional four-domain diagnostics, never independent legal gold.

The manifest contains source specifications only. Native targets for a partition
are created only when explicitly requested. Actor/action pairs, including both
variants, stay together; training vocabulary never sees held-out targets.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "authored-complete-family-holdout/v1"
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
ACTORS = ("analyst", "clerk", "auditor", "editor", "supervisor", "manager", "delegate")
ACTIONS = ("compress", "encrypt", "decrypt", "validate", "notarize", "reconcile", "export", "import")
OBJECTS = ("docket", "memo", "record", "brief", "packet", "folder", "ticket")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def manifest():
    rows = []
    for domain in DOMAINS:
        for actor in range(7):
            for action in range(8):
                split = "test" if action == actor else "validation" if action == actor + 1 else "train"
                for variant in range(2):
                    group = f"{domain}:pair:{actor}:{action}"
                    rows.append(dict(domain_id=domain, source_id=f"{group}:{variant}",
                        group_id=group, split=split, actor=actor, action=action, variant=variant))
    return {"schema": SCHEMA, "rows": rows,
        "scope": "authored known-vocabulary combinations, not unseen-domain or natural-corpus quality",
        "partition_unit": "actor/action pair including both variants",
        "independent_test_groups_per_domain": 7,
        "all_logic_families_assumed_available": False,
        "source_semantics_verified": False, "qualified": False, "admitted": False}


def rows(domain, split):
    if domain not in DOMAINS or split not in {"train", "validation", "test"}:
        raise ValueError("explicit supported domain and partition required")
    return [row for row in manifest()["rows"] if row["domain_id"] == domain and row["split"] == split]


def _ui(row):
    from ...logic.formalization.autoencoder.ui_training_inputs import SCHEMA as UI_SCHEMA
    from ...logic.ui_ux_ir.source_adapters.mcp_idl_identity import compute_verified_interface_cid
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
        "provenance": {"dataset": SCHEMA, "revision": "authored-20261001-v1", "split": row["split"],
            "row_id": row["source_id"], "group_id": row["group_id"]},
        "dom_aria": {"document_id": row["source_id"], "title": title, "source_id": row["source_id"],
            "source_revision": "authored-20261001-v1", "root": {"node_id": component,
                "role": "button", "name": title, "actions": ["activate"]}},
        "interface": {"descriptor": descriptor, "claimed_interface_cid": compute_verified_interface_cid(descriptor)},
        "bindings": [{"binding_id": "binding:action", "action_id": method, "component_id": component,
            "dom_action": "activate", "method_name": method, "risk_class": "high",
            "confirmation_class": "confirm", "idempotency": "non_idempotent"}],
        "behavior": {"model_id": method, "states": [{"state_id": "pending"},
            {"state_id": "finished", "terminal": True}], "initial_state_ids": ["pending"],
            "transitions": [{"transition_id": "complete", "source_state_ids": ["pending"],
                "target_state_id": "finished", "event_id": event,
                **({"timeout_ms": 1000} if row["variant"] else {})}]},
        "events": [{"event_id": event, "kind": "activate", "target_component_id": component,
            "timestamp_ms": 1, "provenance": "synthetic", "capability_id": "pointer_mouse",
            "consent_ok": True, "source_adapter": "authored-structural-panel"}]}


def _security(row):
    from ...logic.ir_core.identity import canonical_identity
    from ...logic.ir_core.provenance import SourceRef
    from ...logic.security_ir.cvefixes.schemas import CodeUnit
    from ...logic.security_ir.code_logic_projection import CodeLogicEvidence
    from ...logic.software_verification.program import (
        ProgramIR, ProgramExpression, ProgramCommand, ProgramFunction, ControlFlowGraph, BasicBlock)
    from ...logic.software_verification.state import StateSchema, StateVariable, FiniteDomainBound, StatePredicate
    from ...logic.software_verification.transitions import StateTransitionIR, Action, ActionFrame, TransitionRelation
    from ...logic.software_verification.temporal import TemporalFormula
    from ...logic.software_verification.contracts import ProgramContract, ContractClause
    from ...logic.software_verification.heap import HeapModel, HeapLocation, HeapValue
    from ...logic.software_verification.separation import SeparationLogicIR, emp_formula
    from ...logic.software_verification.hyperproperties import HyperpropertyIR, InformationFlowPolicy, SelfCompositionBound
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


def source_inputs(row):
    if row not in manifest()["rows"]:
        raise ValueError("exact authored manifest row required")
    domain = row["domain_id"]
    if domain == "ui_ux_ir":
        return {"ui_training_row": _ui(row)}
    if domain == "security_ir":
        return _security(row)
    actor, action, obj = ACTORS[row["actor"]], ACTIONS[row["action"]], "record"
    text = f"{actor} {'may' if row['variant'] else 'must'} {action} {obj}."
    if domain == "intent_ir":
        from ...logic.intent_ir.formalize.rich_grammar import parse_instruction
        return {"document": parse_instruction(text), "source_text": text}
    from .modal_ir import (ModalIRDocument, ModalIRFormula, ModalIROperator, ModalIRPredicate,
        ModalIRProvenance, ModalIRFrameLogic, ModalIRFrameLogicTriple)
    text = f"{actor} {'may' if row['variant'] else 'must'} {action} {obj} within 10 days."
    provenance = ModalIRProvenance(row["source_id"], 0, len(text))
    document = ModalIRDocument(row["source_id"], SCHEMA, text, formulas=[
        ModalIRFormula("norm:one", ModalIROperator("deontic", "D", "P" if row["variant"] else "O",
            "permission" if row["variant"] else "obligation"),
            ModalIRPredicate(action, [actor, obj], "clause"), provenance, conditions=["within 10 days"]),
        ModalIRFormula("time:one", ModalIROperator("temporal", "LTL", "F", "eventually"),
            ModalIRPredicate(action, [actor, obj], "clause"), provenance, conditions=["within 10 days"]),
    ], frame_logic=ModalIRFrameLogic(selected_frame=action, graph_id=row["source_id"],
        triples=[ModalIRFrameLogicTriple(actor, action, obj)]))
    return {"document": document, "source_text": text}


def prepare_partition(domain, split):
    """No implicit preparation of any other partition; callers control exposure."""
    from ...logic.formalization.autoencoder.family_training_v2 import prepare_family_training_targets_v2
    return [prepare_family_training_targets_v2(domain, **source_inputs(row)) for row in rows(domain, split)]
