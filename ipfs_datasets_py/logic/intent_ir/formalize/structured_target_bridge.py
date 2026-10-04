"""Retain weak structured targets without weakening conditional obligations.

The existing learned codec accepts only a single unconditioned action. Native
IntentIR can additionally preserve declared action ordering. Conditional norms
have no native guard-to-modality relation, so their complete text stays opaque;
neither an unconditional obligation nor an execution precondition is invented.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

from .projection_contracts import AUTHORITY, canonical_bytes, source_ir_sha256
from .roundtrip import MODALS, frame_to_intent_ir, validate_frame

SCHEMA = "intent-structured-target-qualification/v1"
MAX_INSTRUCTION_CHARS = 4096
MAX_CONDITION_CHARS = 256
MAX_CONDITION_WORDS = 32


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def validate_structured_target(target):
    """Validate a closed candidate grammar; opaque guards are never evaluated."""
    if type(target) is not dict or set(target) != {"kind", "actions", "condition"}:
        raise ValueError("closed structured Intent target required")
    kind = target["kind"]
    if type(kind) is not str or kind not in {"action", "sequence", "conditional"}:
        raise ValueError("supported structured Intent target kind required")
    actions = target["actions"]
    if type(actions) is not list or len(actions) != (2 if kind == "sequence" else 1):
        raise ValueError("exact action count required for structured target kind")
    frames = []
    for row in actions:
        if type(row) is not dict or type(row.get("object")) is not str:
            raise ValueError("bounded structured action frame required")
        # The old learned codec is lowercase-only. The native candidate can
        # preserve case in opaque object atoms without training on an alias.
        frame = validate_frame({**row, "object": row["object"].lower()})
        if not row["object"].isascii():
            raise ValueError("bounded ASCII lexical object phrase required")
        frame["object"] = row["object"]
        frames.append(frame)
    condition = target["condition"]
    if kind == "conditional":
        if (type(condition) is not str or not condition
                or len(condition) > MAX_CONDITION_CHARS
                or len(condition.split()) > MAX_CONDITION_WORDS
                or condition != " ".join(condition.split())
                or not condition.isprintable()):
            raise ValueError("bounded normalized opaque condition required")
    elif condition is not None:
        raise ValueError("unconditioned target must have condition=None")
    return {"kind": kind, "actions": frames, "condition": condition}


def _instruction(value):
    if type(value) is not str or not value.strip() or len(value) > MAX_INSTRUCTION_CHARS:
        raise ValueError("bounded nonempty original instruction required")
    return value


def _frame_document(frame, instruction):
    document = frame_to_intent_ir({**frame, "object": frame["object"].lower()}, instruction=instruction)
    statement = replace(document.statements[0], arguments=(frame["actor"], frame["object"]),
        normalized_text=f"{frame['actor']} {MODALS[frame['modality']]} {frame['action']} {frame['object']}.")
    action = replace(document.actions[0], object_refs=(frame["object"],))
    return replace(document, statements=(statement,), actions=(action,))


def build_structured_target_ir(target, instruction):
    """Materialize native candidates while preserving every supported relation.

    Source binding records exact input bytes. It does not establish that the
    weak target correctly interprets them. All materialized nodes are inferred.
    """
    from ..decoder import decode_intent_ir
    from ..schema import (ControlEdgeKind, IntentControlEdge, IntentKind,
                          IntentModality, NodeGrounding)

    target = validate_structured_target(target)
    instruction = _instruction(instruction)
    base = _frame_document(target["actions"][0], instruction)
    source = replace(base.sources[0], source_uri="instruction:structured-intent-target")
    identity = _sha(canonical_bytes({"instruction": instruction, "target": target}))
    document = replace(base, document_id="intent-structured-target:" + identity,
        title="Unreviewed structured intent target", sources=(source,),
        tags=("weak-target-candidate", target["kind"]))
    if target["kind"] == "sequence":
        second = _frame_document(target["actions"][1], instruction)
        action = replace(second.actions[0], action_id="action_2")
        statement = replace(second.statements[0], statement_id="goal_2")
        edge = IntentControlEdge(edge_id="next", source_action_id="action",
            target_action_id="action_2", kind=ControlEdgeKind.NEXT,
            source_ref_ids=("source",), grounding=NodeGrounding.INFERRED)
        document = replace(document, intent_kind=IntentKind.PROCEDURE,
            statements=(*document.statements, statement), actions=(*document.actions, action),
            control_edges=(edge,), terminal_action_ids=("action_2",))
    elif target["kind"] == "conditional":
        # G -> norm(A) neither entails norm(A) nor says that A can run only
        # when G holds. Preserve the entire conditional as one opaque goal.
        # Native formula statements reject surrounding whitespace; source
        # bytes and the source span still retain it exactly.
        opaque = replace(document.statements[0], normalized_text=instruction.strip(),
            predicate="", arguments=(), modality=IntentModality.INTENDED)
        document = replace(document, statements=(opaque,))
    document.validate()
    return decode_intent_ir(document.to_dict())


def _candidate_ast(target):
    actions = [{"op": "modal_action", "frame": dict(frame)} for frame in target["actions"]]
    if target["kind"] == "conditional":
        return {"op": "implies", "antecedent": {"op": "opaque_condition", "text": target["condition"]},
                "consequent": actions[0]}
    if target["kind"] == "sequence":
        return {"op": "sequence", "steps": actions}
    return actions[0]


def structured_target_producer_pins():
    """Pin this bridge and native producers without changing existing codecs."""
    from .. import canonicalize, decoder, schema
    from . import compiler, decompiler, roundtrip, typed_compiler
    from .extended_projections import projection_producer_pins
    from ...formalization.autoencoder import domain_targets

    pins = projection_producer_pins()
    for module in (canonicalize, decoder, schema, compiler, decompiler, roundtrip,
                   typed_compiler, domain_targets):
        pins[module.__name__] = _sha(Path(module.__file__).read_bytes())
    pins[__name__] = _sha(Path(__file__).read_bytes())
    return pins


def qualify_structured_target(target, instruction):
    """Project a weak target; rich candidates remain outside the learned codec."""
    from .extended_projections import project_intent_families

    target = validate_structured_target(target)
    instruction = _instruction(instruction)
    document = build_structured_target_ir(target, instruction)
    projections = project_intent_families(document)
    unsupported = []
    case_sensitive = any(row["object"] != row["object"].lower() for row in target["actions"])
    if case_sensitive:
        unsupported.append("case_sensitive_object_outside_roundtrip_codec")
    if target["kind"] == "conditional":
        unsupported += ["conditional_modality_relation", "opaque_condition_has_no_state_binding",
                        "conditional_target_requires_separate_learned_codec"]
        # A native projector must not silently turn the opaque umbrella goal
        # into an independent norm about the retained action.
        for row in projections["projections"]:
            if row["family_id"] in {"dcec", "tdfol"}:
                if row["representation"]["payload"].get("formulas"):
                    raise ValueError("conditional target acquired an unconditional modal formula")
        if projections["native_targets"]["ready_for_training"]:
            raise ValueError("opaque conditional unexpectedly passed full native training readiness")
    elif target["kind"] == "sequence":
        unsupported.append("sequence_target_requires_separate_learned_codec")
    native_ready = projections["native_targets"]["ready_for_training"]
    if not native_ready:
        unsupported.append("native_target_has_unsupported_semantics")
    report = {"schema": SCHEMA, "target": target, "candidate_ast": _candidate_ast(target),
        "instruction_sha256": _sha(instruction.encode("utf-8")),
        "native_intent_ir": document.to_dict(), "source_ir_sha256": source_ir_sha256(document),
        "projections": projections,
        "training_supported": target["kind"] == "action" and native_ready and not case_sensitive,
        "training_support_scope": "existing_single_clause_roundtrip_codec_only",
        "unsupported": unsupported, "producer_pins": structured_target_producer_pins(),
        "condition_semantics": "opaque_source_text_not_a_state_predicate" if target["kind"] == "conditional" else None,
        "code_state_bound": False, "state_effects_inferred": False,
        "source_content_executed": False, "training_executed": False,
        "learned_inference_executed": False, "provider_calls": 0, "external_backend_calls": 0,
        "supervision": "caller_supplied_unreviewed_weak_target", **AUTHORITY}
    report["report_sha256"] = _sha(canonical_bytes(report))
    return report


def validate_structured_target_report(report, target, instruction):
    """Replay source bytes, target, producers and every derived projection."""
    if type(report) is not dict:
        raise ValueError("structured target qualification report required")
    expected = qualify_structured_target(target, instruction)
    if canonical_bytes(report) != canonical_bytes(expected):
        raise ValueError("structured target report differs from deterministic source replay")
    return report


__all__ = ["build_structured_target_ir", "qualify_structured_target",
           "validate_structured_target", "validate_structured_target_report",
           "structured_target_producer_pins"]
