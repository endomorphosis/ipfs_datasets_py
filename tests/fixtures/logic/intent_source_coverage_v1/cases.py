"""Authored source-contract cases, never learned outputs or held-out evidence."""
from copy import deepcopy

from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_coverage_384 as api
from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as compact
from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_guarded_lean as guarded
from ipfs_datasets_py.logic.intent_ir.decoder import decode_intent_ir
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction

CONTRACT = ("The officer must publish the report. "
    "Precondition of publish by officer on report: report is ready. "
    "Effect of publish by officer on report: report is complete.")


def finite_options(candidate):
    """Explicit fixture assumptions, not interpretations inferred from the text."""
    document = decode_intent_ir(candidate["document"])
    digest = source_ir_sha256(document)
    pre = next(row for row in document.statements if row.kind.value == "precondition")
    effect = next(row for row in document.statements if row.kind.value in {"effect", "postcondition"})
    workflow = {"semantics": "finite_guarded_state_flow", "source_ir_sha256": digest,
        "evidence_ref": "source", "variables": [
            {"variable_id": "ready", "kind": "boolean", "domain": [False, True],
             "initial_values": [True], "evidence_ref": "source"},
            {"variable_id": "complete", "kind": "boolean", "domain": [False, True],
             "initial_values": [False], "evidence_ref": "source"}],
        "predicate_bindings": [{"statement_id": pre.statement_id,
            "expression": {"op": "eq", "variable_id": "ready", "value": True}, "evidence_ref": "source"}],
        "action_updates": [{"action_id": "action:0", "outcomes": [
            {"values": {"complete": True}, "evidence_ref": "source"}], "evidence_ref": "source"}],
        "retry_bounds": []}
    effects = {"schema": guarded.BINDING_SCHEMA, "source_ir_sha256": digest,
        "bindings": [{"statement_id": effect.statement_id,
            "expression": {"op": "eq", "variable_id": "complete", "value": True}, "evidence_ref": "source"}]}
    return {"context": {"state": {"max_steps": 10, "workflow": workflow}},
            "guarded_effect_bindings": effects}


def _row(identity, source_text, *, finite=False):
    candidate = api.source_target(source_text)
    return {"id": identity, "domain": "intent_ir", "source_text": source_text, "candidate": candidate,
        "candidate_origin": "authored_bounded_source_reference_not_model_output",
        "options": finite_options(candidate) if finite else {}, "expected_disposition": "prepared"}


def cases():
    rows = [
        _row("explicit-assumption-with-permitted-goal", "Assume report is ready. The officer may publish the report."),
        _row("explicit-intention", "The officer intends to publish the report."),
        _row("assumption-and-norm", "Assume report is ready. The officer must publish the report."),
        _row("assumption-intention-norm", "Assume report is ready. The officer intends to publish the report. The officer must publish the report."),
        _row("declared-contract-without-finite-interpretation", CONTRACT),
        _row("explicit-finite-effect-contract", CONTRACT, finite=True),
        _row("explicit-finite-postcondition-contract", CONTRACT.replace("Effect of", "Postcondition of"), finite=True),
    ]
    source = "The officer intends to publish the report."
    rows.append({"id": "existing-compact-intention", "domain": "intent_ir", "source_text": source,
        "candidate": {"kind": "intent_rich_ast", "document": parse_instruction(source)},
        "candidate_origin": "authored_existing_compact_grammar_not_model_output", "options": {},
        "expected_disposition": "prepared"})
    for identity, base, mutate in (
        ("wrong-intended-actor", rows[1], lambda row: row["candidate"]["document"]["actions"][0].update(actor="clerk")),
        ("wrong-assumption-property", rows[0], lambda row: row["candidate"]["document"]["statements"][0].update(predicate="complete")),
        ("wrong-source-hash", rows[0], lambda row: row["candidate"]["document"]["sources"][0].update(content_sha256="0" * 64)),
        ("unsupported-extra-clause", rows[0], lambda row: row.update(source_text=row["source_text"] + " Something else happens.")),
        ("wrong-effect-source-binding", rows[5], lambda row: row["options"]["guarded_effect_bindings"].update(source_ir_sha256="0" * 64)),
        ("wrong-state-source-binding", rows[5], lambda row: row["options"]["context"]["state"]["workflow"].update(source_ir_sha256="0" * 64)),
        ("standalone-assumption-has-no-native-goal", rows[0], lambda row: row.update(source_text="Assume report is ready.")),
    ):
        row = deepcopy(base)
        reason = ("source_unsupported" if identity in {"unsupported-extra-clause", "standalone-assumption-has-no-native-goal"}
                  else "effect bindings must match" if identity == "wrong-effect-source-binding"
                  else "guarded workflow premise must bind" if identity == "wrong-state-source-binding"
                  else "source_disagreement")
        row.update(id=identity, expected_disposition="blocked", expected_reason=reason)
        mutate(row)
        rows.append(row)
    return rows


def prepare_case(row):
    options = deepcopy(row["options"])
    if "guarded_effect_bindings" in options:
        options["guarded_effect_bindings"] = guarded.IntentEffectBindings.from_dict(options["guarded_effect_bindings"])
    if row["candidate"].get("kind") == "intent_rich_ast":
        if options:
            raise ValueError("compact comparison fixture has no additional context")
        return compact.prepare_family_targets(row["source_text"], row["candidate"])
    return api.prepare_family_targets(row["source_text"], row["candidate"], **options)
