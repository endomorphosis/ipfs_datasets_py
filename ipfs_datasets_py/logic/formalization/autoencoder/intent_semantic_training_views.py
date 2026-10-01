"""Source-derived Intent predicates and ground rule constraints, without facts of execution.

The semantic atom program abbreviates supplied formulas. It is a satisfaction
condition, not a database asserting goals true or a modal inference calculus.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import json

from . import family_training as core
from . import family_training_v4 as previous
from . import native_intent_lean as old
from ...intent_ir import schema, decoder, canonicalize
from ...intent_ir.formalize import compiler, rich_logic, rich_grammar
from ...parsers import rules

SCHEMA = "intent-semantic-source-views/v1"
PREFIX = "intent_ir/semantic/"
REPLACED = {"intent-route/facts/v1", "intent-extended/datalog/default/v1", "intent-extended/horn_chc/default/v1"}
_PINS = {name: sha for module in (core, previous, old, schema, decoder, canonicalize, compiler, rich_logic, rich_grammar, rules, importlib.import_module(__name__))
         for name, sha in core._pin(module).items()}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, sha in _PINS.items():
        _require(_pin_imported_module(importlib.import_module(name)) == sha, "Intent semantic producer drift")


def _document(value):
    document = value if type(value) is schema.IntentIRDocument else decoder.decode_intent_ir(value)
    _require(type(document) is schema.IntentIRDocument, "native IntentIR document required")
    raw = canonicalize.canonical_intent_ir_bytes(document)
    _require(len(raw) <= 128 * 1024 and len(document.statements) <= 128 and len(document.actions) <= 128,
             "bounded Intent semantic source required")
    return document, json.loads(raw)


def _source_document(source_inputs):
    value = source_inputs["document"]
    if type(value) is dict and "kind" in value:
        text = source_inputs.get("source_text")
        _require(value["kind"] == "atom" and text is not None
            and rich_grammar.parse_instruction(text) == rich_grammar.validate_ast(value),
            "atomic rich Intent requires exact complete source agreement")
        # Use the same pinned native owner as the original v4 producer. Rich
        # branches/sequences never become an unconditional atomic declaration.
        rich = rich_logic.project_rich_intent_logic(value, instruction=text, context=source_inputs.get("context"))
        value = rich["native_intent_ir"]
        _require(value is not None, "rich atomic owner must supply its native IntentIR")
    return value


def semantic_document(value):
    """Partition native statements by force and role; never infer an observed event."""
    _guard()
    document, wire = _document(value)
    records, accounting, blocked = [], [], []
    action_rows = []
    for action in document.actions:
        action_rows.append({"native_action_id": action.action_id,
            "replacement_projection_ids": ["intent-route/action-hoare/v1"],
            "disposition": "declared_action_contract_not_observed_event"})
    for statement in document.statements:
        body = compiler._statement_body(statement)
        role, modality = statement.kind.value, compiler._modal_operator(statement)
        identity = statement.statement_id
        record = {"statement_id": identity, "native_record": statement.to_dict(), "body": body,
                  "operator": None, "actor": None, "logic_family": None}
        destination, reason = [], None
        if not statement.predicate or len(statement.arguments) > 32:
            reason = "explicit_bounded_native_predicate_required"
        elif role in ("goal", "assumption"):
            if modality == "asserted" and role == "assumption":
                record.update(operator="predicate", logic_family="first_order")
            elif modality in ("required", "permitted", "prohibited"):
                record.update(operator={"required": "O", "permitted": "P", "prohibited": "F"}[modality], logic_family="deontic")
            elif modality == "intended":
                matches = [a for a in document.actions if a.verb == statement.predicate
                    and [a.actor, *a.object_refs] == list(statement.arguments)]
                if len(matches) != 1:
                    reason = "intention_requires_unique_exact_native_action_actor"
                else:
                    record.update(operator="I", actor=matches[0].actor, logic_family="intention_agency")
            else:
                reason = "unreviewed_Intent_modality"
            if not reason:
                destination = [PREFIX + record["logic_family"] + "/v1"]
                records.append(record)
        elif role in ("precondition", "postcondition", "effect") and modality == "asserted":
            attribute = "precondition_ids" if role == "precondition" else "effect_ids"
            matches = [a for a in document.actions if identity in getattr(a, attribute)]
            if matches:
                destination = ["intent-route/action-hoare/v1"]
            else:
                reason = "unjoined_action_condition_is_not_a_global_fact"
        else:
            reason = "statement_role_requires_dedicated_semantic_projection"
        if reason:
            blocked.append({"statement_id": identity, "reason": reason, "native_record": statement.to_dict()})
            destination = [PREFIX + "unhandled/v1"]
        accounting.append({"statement_id": identity, "replacement_projection_ids": destination,
            "disposition": "blocked" if reason else "formula_definition_not_asserted_truth"})
    records.sort(key=lambda r: r["statement_id"])
    return {"schema": SCHEMA, "native_document": wire,
        "native_document_sha256": canonicalize.intent_ir_sha256(document),
        "semantic_records": records, "statement_accounting": sorted(accounting, key=lambda r: r["statement_id"]),
        "action_accounting": sorted(action_rows, key=lambda r: r["native_action_id"]), "blocked": blocked,
        "observed_events": [], "source_semantics_verified": False, "goals_asserted_true": False}


def _rule_program(semantic, family):
    records = semantic["semantic_records"]
    _require(family in ("datalog", "horn_chc") and records, "nonempty semantic ground program required")
    bindings, lines = [], []
    for index, record in enumerate(records):
        predicate = "intent_semantic_" + str(index)
        arguments = record["body"]["arguments"]
        lines.append(predicate + "(" + ",".join(json.dumps(a, ensure_ascii=False) for a in arguments) + ").")
        bindings.append({"rule_predicate": predicate, "rule_arguments": arguments, "typed_formula": record})
    source = "\n".join(lines) + "\n"
    parsed = rules.parse_print_parse_rules(source, profile="datalog")
    _require(parsed.ok and not parsed.diagnostics and not parsed.document.unsupported and
        len(parsed.document.facts) == len(bindings) and not parsed.document.rules and not parsed.document.queries,
        "exact positive native ground rule parse required")
    # Native round-trip printing introduces its explicit profile and stratum;
    # these two checked directives are not domain clauses or additional rules.
    for item in parsed.document.statements:
        if item.kind.value != "fact":
            _require(item.kind.value == "directive" and (item.directive_name, item.directive_value)
                in (("profile", "datalog"), ("stratum", "0")), "unexpected ground program directive")
    for item, binding in zip(parsed.document.facts, bindings):
        _require(item.effect.value == "derive" and not item.body and not item.head.issuer and
            item.head.polarity.value == "positive" and item.head.predicate == binding["rule_predicate"] and
            [term.name for term in item.head.arguments] == binding["rule_arguments"] and
            all(term.kind.value == "string" for term in item.head.arguments), "ground semantic atom readback differs")
    lowering = rules.lower_to_chc(parsed.document)
    _require(lowering.ok and not lowering.unsupported and not lowering.loss_receipts and
        len(lowering.clauses) == len(bindings), "lossless native ground Horn lowering required")
    for clause, fact in zip(lowering.clauses, parsed.document.facts):
        _require(clause.head == fact.head and not clause.body and not clause.constraints and not clause.is_query,
            "Horn semantic atom readback differs")
    return {"source": source, "native_profile": "datalog", "native_rule_document": parsed.document.to_dict(),
        "native_chc": lowering.to_dict(), "atom_bindings": bindings,
        "program_interpretation": "ground_clause_satisfaction_under_explicit_typed_formula_bindings",
        "least_fixed_point_executed": False, "facts_asserted_true": False,
        "capability_floor_eligible": any(r["logic_family"] == "first_order" for r in records)}


def _payload(semantic, family):
    records = [r for r in semantic["semantic_records"] if r["logic_family"] == family]
    payload = {"schema": SCHEMA, "family": family, "semantic_source": semantic,
        "records": records, "rule_program": None}
    if family in ("datalog", "horn_chc"):
        payload["records"] = semantic["semantic_records"]
        payload["rule_program"] = _rule_program(semantic, family) if semantic["semantic_records"] else None
    return payload


def verify_payload(payload):
    """Rebuild every binding from the full native source, then compare exactly."""
    _guard()
    _require(type(payload) is dict and payload.get("schema") == SCHEMA, "native semantic payload required")
    semantic = semantic_document(payload["semantic_source"]["native_document"])
    family = payload["family"]
    _require(family in ("first_order", "deontic", "intention_agency", "datalog", "horn_chc", "modal"),
        "reviewed semantic family required")
    expected = _payload(semantic, family)
    _require(core._wire(expected) == core._wire(payload), "semantic formula or native rule binding differs from source")
    return expected


def transform(report, source_inputs):
    """Transform exact v4 Intent rows; caller finalizes the v5 report identity."""
    _guard()
    result = deepcopy(report)
    if report.get("domain_id") != "intent_ir":
        return result
    replay_inputs = dict(source_inputs)
    if "requested_families" in replay_inputs:
        _require(list(replay_inputs.pop("requested_families")) == report["requested_families"],
            "Intent replay family request differs from exact original report")
    # v4's validator reconstructs the report's fixed request itself. v5 source
    # replay may already carry that same request; it must not be supplied twice.
    previous.validate_family_training_report_v4(report, **replay_inputs)
    originals = [r for r in result["projections"] if r["projection_id"] in REPLACED]
    if not originals:
        return result
    semantic = semantic_document(_source_document(source_inputs))
    # Exact source replay above prevents a caller supplying unrelated archived
    # rows while reusing the semantic native document below.
    original_ids = {r["projection_id"] for r in originals}
    result["projections"] = [r for r in result["projections"] if r["projection_id"] not in REPLACED]
    result.setdefault("superseded_intent_observations", []).extend({**deepcopy(row),
        "active_for_training": False, "superseded_reason": "typed_statement_force_and_action_role_are_not_world_facts"}
        for row in originals)
    result["intent_semantic_replacement_accounting"] = deepcopy(semantic)
    families = {r["logic_family"] for r in semantic["semantic_records"]} if "intent-route/facts/v1" in original_ids else set()
    families |= {family for family in ("datalog", "horn_chc")
        if "intent-extended/" + family + "/default/v1" in original_ids}
    if semantic["blocked"]:
        families.add("modal")
    _require(families <= set(report["requested_families"]),
        "Intent semantic reclassification requires its actual families to remain requested")
    ids = {r["projection_id"] for r in result["projections"]}
    for mapping in semantic["action_accounting"]:
        _require(set(mapping["replacement_projection_ids"]) <= ids, "action declaration lacks retained native contract projection")
    for family in sorted(families):
        payload = _payload(semantic, family)
        identity = PREFIX + ("unhandled" if family == "modal" else family) + "/v1"
        ready = family != "modal" and not (family in ("datalog", "horn_chc") and semantic["blocked"])
        checks = [{"validator_id": "native_Intent_source_role_and_force_replay", "stage": "target",
            "status": "passed" if ready else "failed", "details": {"unknown_semantics": deepcopy(semantic["blocked"]),
                "native_rule_parser_executed": family in ("datalog", "horn_chc"), "Lake_executed": False}}]
        result["projections"].append({"projection_id": identity, "logic_family": family,
            "profile": "intent_semantic_" + family, "representation_kind": "native_typed_projection",
            "producer_id": __name__, "payload": payload, "validation": checks,
            "qualification_gaps": ["source_meaning_not_verified", "formula_definition_not_truth",
                "action_declarations_are_not_observed_execution", "ground_rule_abstraction_not_modal_inference_calculus"],
            "ready_for_training": ready, "source_digest": report["source_digest"], **core.AUTHORITY})
        if not ready:
            result["frontier"].append({"family_id": family, "projection_id": identity,
                "reason": "unreviewed_Intent_semantic_statements", "details": deepcopy(semantic["blocked"])})
    actual_ids = {r["projection_id"] for r in result["projections"]}
    for mapping in semantic["statement_accounting"]:
        _require(set(mapping["replacement_projection_ids"]) <= actual_ids,
            "native statement lacks its complete semantic replacement projection")
    result["producer_pins"].update(_PINS)
    return result
