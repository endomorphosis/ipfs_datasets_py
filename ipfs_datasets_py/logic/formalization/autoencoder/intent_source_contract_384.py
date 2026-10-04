"""Exact rich Intent candidates into an additional ground DFOL declaration.

The source grammar is checked after inference, never used to replace a model
prediction. Existing family targets remain intact. A complete O/P/F formula is
reparsed through the DFOL owner and compared both to the rich native AST and to
the original candidate's semantic structure. This is no Lake or proof gate.
"""
from __future__ import annotations

from copy import deepcopy
import importlib

from . import family_training as core
from . import family_training_v7 as training
from . import intent_candidate_fidelity as fidelity
from . import native_formula_evidence as formulas
from ...intent_ir.formalize import rich_logic

SCHEMA = "source-intent-rich-qualification/v1"
FALSE = {**fidelity.FALSE, "promotion_performed": False}
_UNPROJECTED = ["quantified_referent_semantics", "temporal_intervals_or_clock",
    "observed_events_or_event_calculus_axioms", "actor_cognition_or_intention",
    "recommendation_policy", "execution_preconditions_or_action_effects",
    "actual_guard_truth", "source_code_equivalence", "norm_compliance"]


def _pins():
    return {name: sha for module in (importlib.import_module(__name__), core,
        training, fidelity, formulas, rich_logic) for name, sha in core._pin(module).items()}


def _expected_shape(ast):
    kind = ast["kind"]
    if kind == "atom":
        return ("modal", ast["modality"], ("predicate", "action:" + ast["action"],
            ((ast["actor"], "Agent"), (ast["object"], "Entity"))))
    if kind in {"and", "or"}:
        return kind, _expected_shape(ast["left"]), _expected_shape(ast["right"])
    if kind == "if":
        guard = ast["guard"]
        condition = ("predicate", "property:" + guard["property"], ((guard["subject"], "Entity"),))
        if guard["negated"]:
            condition = ("not", condition)
        return "implies", condition, _expected_shape(ast["body"])
    raise ValueError("ordered Intent actions are not a Boolean deontic formula")


def _check_ground_structure(payload, representation, candidate):
    """Compare all native operators, ordered terms, sorts and source surfaces."""
    if payload["ast_format"] != "tdfol_native" or payload["native_ast"] != representation["ast"]:
        raise ValueError("DFOL parser changed the complete rich native AST")
    counts = payload["operator_counts"]
    if not counts["deontic"] or counts["temporal"] or counts["quantifier"]:
        raise ValueError("rich Intent DFOL must retain ground deontic operators only")
    table = {}
    for row in representation["symbols"]:
        if set(row) != {"symbol", "role", "value"} or row["symbol"] in table:
            raise ValueError("closed unique rich symbol declarations required")
        table[row["symbol"]] = row
    used = set()

    def meaning(symbol, role):
        row = table.get(symbol)
        if row is None or row["role"] != role:
            raise ValueError("native symbol lost its typed source declaration")
        used.add(symbol)
        return row["value"]

    def constant(node):
        if node.get("node_type") != "Constant" or not node["name"].startswith("entity:"):
            raise ValueError("rich native argument is not a declared ground constant")
        slot = meaning(node["name"][len("entity:"):], "slot")
        if type(slot) is not dict or set(slot) != {"surface", "sort"}:
            raise ValueError("closed rich source slot required")
        return slot["surface"], slot["sort"]

    def shape(node):
        kind = node.get("node_type")
        if kind == "Predicate":
            return "predicate", meaning(node["name"], "predicate"), tuple(constant(arg) for arg in node["arguments"])
        if kind == "DeonticFormula" and node["agent"] is None:
            modality = {"O": "required", "P": "permitted", "F": "prohibited"}.get(node["operator"]["value"])
            if modality is not None:
                return "modal", modality, shape(node["formula"])
        if kind == "UnaryFormula" and node["operator"]["value"] == "¬":
            return "not", shape(node["formula"])
        if kind == "BinaryFormula":
            connective = {"∧": "and", "∨": "or", "→": "implies"}.get(node["operator"]["value"])
            if connective is not None:
                return connective, shape(node["left"]), shape(node["right"])
        raise ValueError("native DFOL contains a constructor outside the complete rich candidate")

    if shape(payload["native_ast"]) != _expected_shape(candidate["document"]):
        raise ValueError("DFOL changed the candidate modality, guard, branch order, action or referent")
    if used != set(table):
        raise ValueError("rich native formula omitted a declared semantic symbol")
    return {"complete_candidate_structure_equal": True, "complete_rich_native_ast_equal": True,
        "ordered_terms_and_branches_preserved": True, "symbols_used": len(used),
        "deontic_operators": counts["deontic"], "predicates": counts["predicate"],
        "quantifiers": 0, "temporal_operators": 0, "free_variables": 0}


def _prepare(source_text, target, source_audit, requested_families):
    if source_audit["status"] != "source_agreement":
        raise ValueError("Intent candidate requires exact complete source agreement: " + source_audit["status"])
    pins = _pins()
    original = deepcopy(target)
    if fidelity._json_input(original) != fidelity._json_input(source_audit["candidate"]):
        raise ValueError("Intent candidate changed after source agreement audit")
    rich = rich_logic.project_rich_intent_logic(original["document"], instruction=source_text)
    source_inputs = {"document": deepcopy(original["document"]), "source_text": source_text}
    if requested_families is not None:
        if type(requested_families) not in (tuple, list) or any(type(item) is not str for item in requested_families):
            raise ValueError("canonical family ID sequence required")
        # Existing v5 replay compares the exact canonical order recorded by
        # core. Sorting preserves every request; core still rejects duplicates,
        # unknown IDs and empty requests rather than silently filtering them.
        source_inputs["requested_families"] = sorted(requested_families)
    native = structure = None
    supplemental = {"requirement_id": "DFOL", "family_id": "deontic", "status": "unsupported",
        "reason": "ordered_actions_have_no_Boolean_deontic_formula", "included_in_family_report": False}
    rows = [row for row in rich["projections"] if row["family_id"] == "tdfol"]
    if len(rows) > 1:
        raise ValueError("one complete rich TDFOL projection required")
    if rows and rows[0]["status"] == "projected":
        representation = rows[0]["representation"]
        source_ref = training.supplemental_source_ref("intent_ir", **source_inputs)
        evidence = formulas.NativeFormulaEvidence("DFOL", representation["source"], source_ref)
        native = formulas.prepare_native_formula_evidence(evidence, source_ref)
        structure = _check_ground_structure(native["payload"], representation, original)
        source_inputs["formula_inputs"] = (evidence,)
        supplemental.update(status="derived", reason=None)
    elif rows:
        supplemental["reason"] = "; ".join(rows[0].get("unsupported", ())) or "complete_rich_deontic_formula_unavailable"
    report = training.prepare_family_training_targets_v7("intent_ir", **source_inputs)
    supplemental["included_in_family_report"] = any(row["projection_id"] == "intent_ir/native_formula/DFOL/v3"
                                                     for row in report["projections"])
    available = sorted({row["logic_family"] for row in report["projections"] if row["ready_for_training"]})
    requested = report["requested_families"]
    audit = {"schema": SCHEMA, "status": "projected_candidate", "domain_id": "intent_ir",
        "candidate": original, "source_sha256": source_audit["source_sha256"],
        "candidate_sha256": source_audit["candidate_sha256"], "source_agreement_audit": source_audit,
        "source_fidelity_check_required": True, "continue_planning": True,
        "scope": "exact_bounded_source_grammar_and_unchanged_learned_rich_candidate",
        "projection_scope": "existing_family_views_plus_complete_ground_deontic_formula_when_supported",
        "formula_scope": "ground_DFOL_not_quantified_temporal_cognitive_or_execution_semantics",
        "source_text_to_formula_inference": False, "candidate_to_formula_compilation": True,
        "rich_logic_report": rich, "supplemental_DFOL": supplemental,
        "native_formula": native, "ground_structure": structure,
        "unprojected_facets": list(_UNPROJECTED),
        "unprojected_facets_scope": "supplemental_DFOL_only_existing_family_views_retained",
        "requested_families": requested,
        "available_families": available, "missing_requested_families": sorted(set(requested) - set(available)),
        "family_report_sha256": report["report_sha256"], "family_source_digest": report["source_digest"],
        "producer_pins": pins, "owner_pin_scope": "direct_owners_not_transitive_callgraph", **FALSE}
    audit["audit_sha256"] = core._sha(audit)
    if _pins() != pins or fidelity._json_input(target) != fidelity._json_input(original):
        raise ValueError("Intent adapter producer or candidate changed during preparation")
    return {"report": report, "source_inputs": source_inputs, "audit": audit}


def prepare_family_targets(source_text, target, requested_families=None):
    """Return the unchanged v7 report, replayable typed inputs and a JSON audit.

    Source disagreement blocks every projection. Unsupported supplemental DFOL
    never removes a supported existing route or fabricates missing context.
    """
    source_audit = fidelity.audit_intent_candidate(source_text, target)
    return _prepare(source_text, target, source_audit, requested_families)


def qualify_source_candidate(source_text, target, requested_families=None):
    """JSON-only diagnostic; successful preparation implies no qualification."""
    source_audit = None
    try:
        source_audit = fidelity.audit_intent_candidate(source_text, target)
        if source_audit["status"] != "source_agreement":
            return {"schema": SCHEMA, "status": source_audit["status"], "audit": source_audit,
                "report": None, "projections": [], "continue_planning": True, **FALSE}
        prepared = _prepare(source_text, target, source_audit, requested_families)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {"schema": SCHEMA, "status": "invalid_or_missing_context", "audit": source_audit,
            "reason": str(error)[:1024], "report": None, "projections": [], "continue_planning": True, **FALSE}
    return {"audit": prepared["audit"], "report": prepared["report"], "status": "projected_candidate", **FALSE}


def validate_prepared(prepared, source_text, target):
    """Replay exact source, full candidate, typed evidence, symbols and report."""
    if type(prepared) is not dict or set(prepared) != {"report", "source_inputs", "audit"}:
        raise ValueError("closed prepared Intent adapter envelope required")
    expected = prepare_family_targets(source_text, target, prepared["source_inputs"].get("requested_families"))
    if any(expected[key] != prepared[key] for key in expected):
        raise ValueError("Intent adapter source/candidate/native formula/report replay differs")
    return True


__all__ = ["prepare_family_targets", "qualify_source_candidate", "validate_prepared"]
